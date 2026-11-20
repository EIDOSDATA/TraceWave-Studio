"""! @brief 측정 기록 조회의 실제 resolver와 봉인 원문/소유권 경계를 native 없이 검증한다."""

from copy import deepcopy
import hashlib
import json
import unittest

import test_measurement as fixture
from rfad.application import measurement_records as records
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.result_sources import resolve
from rfad.domain import measurement, network_library
from rfad.domain.errors import ProjectError


class MemoryJournal:
    """! @brief 파일 대신 바이트 저장소를 쓰되 크기/hash 검증은 생략하지 않는다."""

    def __init__(self):
        self.files = {}
        self.state = {"projects": {}, "snapshots": {}, "solver_results": {}, "jobs": {}, "commands": {}, "measurement_attachments": {}}

    def put(self, name, raw):
        """! @brief 시험의 봉인 파일을 등록하고 실제 바이트 참조를 반환한다."""
        reference = {"uri": "projects/fixture/" + name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        self.files[reference["uri"]] = raw
        return reference

    def read(self):
        """! @brief resolver가 읽는 상태를 사본으로 반환한다."""
        return deepcopy(self.state)

    def read_artifact(self, reference):
        """! @brief 누락/변조 파일을 원래 자료처럼 읽지 않는다."""
        raw = self.files.get(reference["uri"])
        if raw is None or len(raw) != reference["bytes"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise ProjectError("E_HASH", "시험 봉인 파일이 다릅니다.")
        return raw

    def verify_file(self, reference):
        """! @brief 원문/HDF5 조회 없이도 실제 바이트 일치를 검사한다."""
        self.read_artifact(reference)


class MemoryRepository:
    """! @brief 실제 revision_document의 파일/소유자 대조를 사용하는 작은 저장소다."""

    def __init__(self, journal):
        self.journal = journal

    def read(self, reference):
        """! @brief hash를 확인한 같은 바이트에서 JSON을 해독한다."""
        raw = self.journal.read_artifact(reference)
        return raw, json.loads(raw)


class RecordFixture:
    """! @brief 가짜 RF 계산 없이 실제 2포트 원문과 두 명시 개정을 연결한다."""

    def __init__(self):
        self.journal = MemoryJournal()
        self.repository = MemoryRepository(self.journal)
        self.project_id = fixture.identity(100)
        self.context = {"project_id": self.project_id}
        self.data = fixture.network()
        self.document = {"project_id": self.project_id, "revision_id": fixture.identity(102),
            "metadata": {"name": "과거 시료 설계", "modified_at": "2026-11-17T00:00:00Z"},
            "geometry": [], "materials": [{"known": None}], "parameters": [],
            "extensions": {"example.original": {"missing": None, "source_refs": ["original:exact"]}}}
        self.entry = {"id": fixture.identity(101), "name": "보존 복소 원문", "created_revision": self.document["revision_id"],
            "kind": "imported", "dataset": self.journal.put("network/dataset.json", canonical_bytes(self.data)),
            "raw": self.journal.put("network/source.txt", b"exact raw source\r\n"),
            "normalized_hdf5": self.journal.put("network/normalized.h5", b"preserved HDF5 fixture"),
            "inputs": [], "circuit_id": None, "diagnostics": None}
        model = network_library.empty_library()
        model["datasets"].append(deepcopy(self.entry))
        network_library.validate_library(model)
        self.document["extensions"][network_library.KEY] = model
        self.project = {"path": "projects/fixture", "revisions": {}}
        self.journal.state["projects"][self.project_id] = self.project
        self.publish(self.document)
        self.record = fixture.record()
        self.record["data_anchor"] = {"kind": "network_artifact", "project_id": self.project_id,
            "dataset_id": self.entry["id"], **{key: deepcopy(self.entry[key]) for key in ("dataset", "raw", "normalized_hdf5")}}
        self.selected = None

    def _project(self, state, context):
        """! @brief 명시 프로젝트에만 접근한다."""
        if context != self.context:
            raise ProjectError("E_CONFLICT", "다른 프로젝트입니다.")
        return state["projects"][self.project_id]

    def _load(self, project):
        """! @brief 현재 문서도 등록된 바이트에서 읽는다."""
        return self.repository.read(project["current"])[1]

    def _now(self):
        """! @brief 초안 표시 시각만 고정하고 실제 측정 시각은 만들지 않는다."""
        return 1794873600.0

    def publish(self, document):
        """! @brief 테스트의 명시 개정 파일을 추가하며 기존 바이트는 덮지 않는다."""
        reference = self.journal.put("revisions/" + document["revision_id"] + ".json", canonical_bytes(document))
        self.project["revisions"][document["revision_id"]] = reference
        self.project["current"] = reference

    def save_record(self, *, execution=None, raw_input=None, wrapper_changes=None):
        """! @brief 자료 artifact를 먼저 고정하여 새 기록에 미래 문서 pin을 넣지 않는다."""
        stored = {"schema": "rfad.measurement-document/0.1", "record": deepcopy(self.record),
            "input": {"changes": {"values": {}, "quantities": {}}} if raw_input is None else deepcopy(raw_input),
            "execution": deepcopy(execution)}
        if wrapper_changes is not None:
            stored.update(wrapper_changes)
        reference = self.journal.put("measurement/record.json", canonical_bytes(stored))
        document = deepcopy(self.document)
        document["revision_id"] = fixture.identity(103)
        model = measurement.empty_registry()
        model["records"].append({"id": self.record["id"], "name": self.record["name"],
            "artifact": reference, "previous_record_id": self.record["previous_record_id"]})
        document["extensions"][measurement.KEY] = model
        self.publish(document)
        self.selected = records.reference(model["records"][0], document["revision_id"])
        self.journal.state["commands"][fixture.identity(400)] = {"project_id": self.project_id,
            "new_revision": document["revision_id"], "measurement": {"record_id": self.record["id"], "record_artifact": reference}}
        return stored

    def load(self):
        """! @brief 제품의 원문 기록 조회 경로를 그대로 실행한다."""
        return records.load_record(self, self.journal.read(), self.project, self.selected)

    def attachment(self):
        """! @brief 등록된 교정 첨부를 실제 원문 hash와 함께 만든다."""
        row = {"id": fixture.identity(200), "name": "교정 원문.txt", "role": "calibration", "media_type": "text/plain",
            "artifact": self.journal.put("measurement/attachments/source.bin", "제출 원문; 보정 미수행".encode())}
        self.journal.state["measurement_attachments"][row["id"]] = {"project_id": self.project_id, "descriptor": deepcopy(row)}
        return row


class MeasurementRecordsTests(unittest.TestCase):
    """! @brief 동명/동일 곡선만으로 과거 기록의 원본 또는 검증 상태를 바꾸지 않는다."""

    def test_get_after_current_library_removal_reads_exact_old_revision_and_preserves_all_bytes(self):
        """! @brief runtime 없는 조회가 과거 원문/미정/입력 문자열과 명시 개정을 보존한다."""
        value = RecordFixture()
        value.record["environment"] = None
        value.record["extra"] = {"instrument_unknown": None, "source_refs": ["source:raw", "source:raw"]}
        original_input = {"changes": {"quantities": {"acquisition.stimulus_power": {"text": "2.5000", "unit": "mW"}}}}
        stored = value.save_record(raw_input=original_input)
        later = deepcopy(value.document)
        later["revision_id"] = fixture.identity(104)
        later["metadata"]["name"] = "현재 자료 없음"
        later["extensions"].pop(network_library.KEY)
        value.publish(later)
        before = deepcopy(value.journal.files)
        response = records.get(value, value.journal.read(), value.project, value.selected)
        self.assertEqual(response["record"], stored["record"])
        self.assertEqual(response["original_input"], original_input)
        self.assertEqual(response["source"]["revision_id"], fixture.identity(103))
        self.assertEqual(response["revision_id"], later["revision_id"])
        self.assertEqual(response["source_revision"]["name"], "과거 시료 설계")
        self.assertFalse(response["summary"]["measurement_validated"])
        self.assertEqual(response["context_assessment"]["physical_acceptance"], "not_established")
        self.assertIsNone(response["record"]["environment"])
        self.assertIsNone(response["execution"])
        self.assertIn("자동 연결", response["evidence_scope"]["physical_setup_snapshot"])
        self.assertEqual(before, value.journal.files)

    def test_each_source_file_and_record_hash_are_verified(self):
        """! @brief dataset뿐 아니라 raw/HDF5와 기록 wrapper 변조도 거절한다."""
        for target in ("dataset", "raw", "normalized_hdf5", "record"):
            with self.subTest(target=target):
                value = RecordFixture()
                value.save_record()
                path = "projects/fixture/measurement/record.json" if target == "record" else value.entry[target]["uri"]
                value.journal.files[path] += b"tamper"
                with self.assertRaises(ProjectError) as raised:
                    value.load()
                self.assertEqual(raised.exception.code, "E_HASH")
        value = RecordFixture()
        value.save_record()
        value.selected["sha256"] = "f" * 64
        with self.assertRaises(ProjectError):
            value.load()

    def test_later_membership_cannot_reanchor_import_record_to_new_geometry_or_removed_dataset(self):
        """! @brief 이후 개정의 목록 참조로 조회해도 최초 설계/자료의 source와 pin은 고정된다."""
        value = RecordFixture()
        value.save_record()
        original = value.load()
        later = value._load(value.project)
        later["revision_id"] = fixture.identity(104)
        later["geometry"] = [{"different": "later design"}]
        later["extensions"].pop(network_library.KEY)
        value.publish(later)
        selected_later = {**value.selected, "revision_id": later["revision_id"]}
        result = records.load_record(value, value.journal.read(), value.project, selected_later)
        self.assertEqual(result["source"]["source"], original["source"]["source"])
        self.assertEqual(result["source"]["pin"], original["source"]["pin"])
        self.assertEqual(result["source"]["source_document"]["geometry"], [])
        self.assertEqual(result["record_ref"], value.selected)
        self.assertEqual(records.creation_reference(value.journal.read(), value.project_id, result["entry"]), value.selected)
        absent = {**selected_later, "revision_id": value.document["revision_id"]}
        with self.assertRaises(ProjectError):
            records.load_record(value, value.journal.read(), value.project, absent)

    def test_creation_command_owner_artifact_and_revision_membership_are_required(self):
        """! @brief 같은 record ID만으로 위조/다른 소유 명령 또는 현재 개정을 생성 근거로 택하지 않는다."""
        for action in ("absent", "foreign", "artifact", "missing_revision", "no_membership", "ambiguous"):
            with self.subTest(action=action):
                value = RecordFixture()
                value.save_record()
                commands = value.journal.state["commands"]
                command = commands[fixture.identity(400)]
                if action == "absent":
                    commands.clear()
                elif action == "foreign":
                    command["project_id"] = fixture.identity(999)
                elif action == "artifact":
                    command["measurement"]["record_artifact"] = {**command["measurement"]["record_artifact"], "sha256": "f" * 64}
                elif action == "missing_revision":
                    command["new_revision"] = fixture.identity(999)
                elif action == "no_membership":
                    command["new_revision"] = value.document["revision_id"]
                else:
                    commands[fixture.identity(401)] = {**deepcopy(command), "new_revision": value.document["revision_id"]}
                with self.assertRaises(ProjectError):
                    value.load()

    def test_anchor_foreign_ownership_ref_substitution_and_entry_identity_are_rejected(self):
        """! @brief 유효한 hash라도 다른 원본/프로젝트 참조로 교체할 수 없다."""
        for action in ("project", "file", "dataset", "index_name"):
            with self.subTest(action=action):
                value = RecordFixture()
                if action == "project":
                    value.record["data_anchor"]["project_id"] = fixture.identity(999)
                elif action == "file":
                    value.record["data_anchor"]["raw"]["uri"] = "projects/another/network/source.txt"
                elif action == "dataset":
                    value.record["data_anchor"]["dataset_id"] = fixture.identity(999)
                value.save_record()
                if action == "index_name":
                    document = value._load(value.project)
                    document["extensions"][measurement.KEY]["records"][0]["name"] = "위조 색인 이름"
                    value.publish(document)
                with self.assertRaises(ProjectError):
                    value.load()

    def test_wrapper_exact_shape_receipt_and_size_are_bounded(self):
        """! @brief 단순 엔진 identity를 실행 영수증으로 가장하거나 wrapper를 늘리지 않는다."""
        for change in ({"schema": "unknown"}, {"input": []}, {"extra": None},
                       {"execution": {"host_identity_hash": "a" * 64}},
                       {"input": {"oversized": "x" * 65536}}):
            with self.subTest(change=list(change)):
                value = RecordFixture()
                value.save_record(wrapper_changes=change)
                with self.assertRaises(ProjectError):
                    value.load()
        value = RecordFixture()
        receipt = {"schema": "rfad.host-execution/0.1", "operation": "network.import",
            "input_sha256": "a" * 64, "identity_hash": "b" * 64, "result_hash": "c" * 64}
        value.save_record(execution=receipt)
        self.assertEqual(value.load()["stored"]["execution"], receipt)

    def test_same_dataset_different_revision_pin_cannot_replace_record_source(self):
        """! @brief 동일 곡선이라도 선택 record와 source의 문서 개정을 엄격히 구분한다."""
        value = RecordFixture()
        value.save_record()
        loaded = value.load()
        selection = {"source": loaded["source"]["source"], "pin": loaded["source"]["pin"], "record": value.selected}
        original, recorded = records.selected_source(value, value.journal.read(), value.project, value.context, selection)
        self.assertEqual(original["source"], recorded["source"]["source"])
        old = resolve(value, value.context, {**selection["source"], "revision_id": fixture.identity(102)})
        self.assertEqual(old["dataset"], original["dataset"])
        self.assertNotEqual(old["pin"], original["pin"])
        with self.assertRaises(ProjectError) as raised:
            records.selected_source(value, value.journal.read(), value.project, value.context,
                                    {"source": old["source"], "pin": old["pin"], "record": value.selected})
        self.assertEqual(raised.exception.code, "E_CONFLICT")

    def test_external_processing_both_anchors_are_verified_and_not_claimed_as_reproduced(self):
        """! @brief 처리 이름/도구는 제출 기록이며 입출력 실제 참조는 각각 확인한다."""
        value = RecordFixture()
        source = resolve(value, value.context, {"kind": "network", "dataset_id": value.entry["id"],
            "revision_id": value.document["revision_id"], "snapshot_id": None})
        anchor = {"kind": "pinned_result", "source": source["source"], "pin": source["pin"]}
        value.record["external_processing"] = [{"name": "제출 보정", "tool": "외부 도구", "version": None,
            "input_anchor": anchor, "output_anchor": deepcopy(value.record["data_anchor"]), "order": 0,
            "reference_plane_before": "케이블 앞", "reference_plane_after": "단자", "uncertainty_notes": None,
            "source_refs": ["source:submitted-order"]}]
        value.save_record()
        self.assertEqual(value.load()["record"]["external_processing"], value.record["external_processing"])
        for which in ("input_anchor", "output_anchor"):
            with self.subTest(which=which):
                bad = deepcopy(value.record)
                if which == "input_anchor":
                    bad["external_processing"][0][which]["pin"]["identity_hash"] = "e" * 64
                else:
                    bad["external_processing"][0][which]["raw"]["sha256"] = "e" * 64
                with self.assertRaises(ProjectError):
                    records.validate_evidence(value, value.journal.read(), value.project, bad)

    def test_attachment_descriptor_registration_and_nested_references_are_verified(self):
        """! @brief 교정/상관/설정의 중첩 파일 근거도 등록된 프로젝트 원문만 허용한다."""
        value = RecordFixture()
        attached = value.attachment()
        value.record["attachments"] = [attached]
        value.record["calibration"]["certificate_refs"] = fixture.leaf([attached["artifact"]])
        value.record["acquisition"]["setting_artifacts"] = fixture.leaf([attached["artifact"]])
        value.record["uncertainty"] = [fixture.uncertainty()]
        value.record["uncertainty"][0]["correlation"] = {"state": "documented", "reference": attached["artifact"]}
        value.save_record()
        self.assertEqual(value.load()["record"], value.record)
        for action in ("name", "role", "unregistered", "foreign", "bytes"):
            with self.subTest(action=action):
                bad = deepcopy(value.record)
                state = value.journal.read()
                if action in ("name", "role"):
                    bad["attachments"][0][action] = "changed" if action == "name" else "other"
                elif action == "unregistered":
                    state["measurement_attachments"].clear()
                elif action == "foreign":
                    state["measurement_attachments"][attached["id"]]["project_id"] = fixture.identity(999)
                else:
                    bad["calibration"]["certificate_refs"]["value"][0]["bytes"] += 1
                with self.assertRaises(ProjectError):
                    records.validate_evidence(value, state, value.project, bad)
        value.journal.files[attached["artifact"]["uri"]] += b"tampered"
        with self.assertRaises(ProjectError):
            value.load()

    def test_design_snapshot_exact_binding_and_generic_environment_json_remain_distinct(self):
        """! @brief 지원하는 설계 snapshot은 파일까지 검증하고 환경 JSON은 자동 연결하지 않는다."""
        value = RecordFixture()
        snapshot = {"snapshot_id": fixture.identity(300), "project_id": value.project_id,
            "revision_id": value.document["revision_id"], "content_hash": canonical_hash(value.document),
            "artifact": value.project["current"]}
        value.journal.state["snapshots"][snapshot["snapshot_id"]] = snapshot
        value.record["specimen"]["design_snapshot"] = fixture.leaf({"snapshot_id": snapshot["snapshot_id"], "content_hash": snapshot["content_hash"]})
        value.record["environment"]["physical_setup_snapshot"] = fixture.leaf({"legacy": "submitted-only", "value": None})
        value.save_record()
        self.assertEqual(value.load()["record"], value.record)
        for key in ("project_id", "revision_id", "content_hash"):
            with self.subTest(key=key):
                state = value.journal.read()
                state["snapshots"][snapshot["snapshot_id"]][key] = "f" * 64 if key == "content_hash" else fixture.identity(999)
                with self.assertRaises(ProjectError):
                    records.validate_evidence(value, state, value.project, value.record)
        legacy = deepcopy(value.record)
        legacy["specimen"]["design_snapshot"] = fixture.leaf({"legacy_name": "미연결", "source": None})
        before = canonical_bytes(legacy)
        records.validate_evidence(value, value.journal.read(), value.project, legacy)
        self.assertEqual(canonical_bytes(legacy), before)

    def test_metadata_conditions_preserve_evidence_unknowns_and_readable_port_names(self):
        """! @brief 같은 값의 계획/제출 차이와 양쪽 미정을 물리 합격과 분리한다."""
        value = RecordFixture()
        value.save_record()
        source = value.load()["source"]
        left, right = deepcopy(value.record), deepcopy(value.record)
        left["calibration"]["method"] = fixture.leaf("SOLT", "planned")
        right["calibration"]["method"] = fixture.leaf("SOLT", "reported")
        right["calibration"]["port_ids"] = fixture.leaf(value.data["port_ids"])
        right["calibration"]["reference_planes"] = fixture.leaf([{"port_id": value.data["port_ids"][1], "reference_plane": None}])
        before = canonical_bytes([left, right, source["dataset"]])
        rows = {row["field"]: row for row in records.metadata_conditions(source, source, left, right)}
        row = rows["measurement.calibration.method"]
        self.assertEqual(row["difference"], "different")
        self.assertIn("계획", row["left_display"])
        self.assertIn("제출 근거", row["right_display"])
        self.assertFalse(row["affects_math"])
        self.assertEqual(rows["measurement.specimen.serial"]["difference"], "both_unknown")
        self.assertIn("자료 포트 2 (이름 미정)", rows["measurement.calibration.port_ids"]["right_display"])
        self.assertNotIn(value.data["port_ids"][1], rows["measurement.calibration.reference_planes"]["right_display"])
        self.assertEqual(canonical_bytes([left, right, source["dataset"]]), before)


if __name__ == "__main__":
    unittest.main()
