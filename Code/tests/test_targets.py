"""! @brief 목표 입력의 저장, 개정, 기존 원본 호환성과 해석 설정 독립성을 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from rfad.application.cad import build_cad_input
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.application.solver import build_analysis_plan, validate_reference_plan
from rfad.domain.errors import ProjectError
from rfad.domain.project import SCHEMA_VERSION, READABLE_SCHEMA_VERSIONS, apply_command, new_project, validate_project
from rfad.domain.targets import METRICS, MAX_TARGETS, target_input_status
from rfad.domain.units import Quantity
from test_design import build_design
from test_pcb_solver import fixture_document, runtime_identity, snapshot_for, SETTINGS


def frequency(value, unit="GHz"):
    """! @brief 단위와 사용자가 명시한 출처를 보존한 주파수를 만든다."""
    return Quantity.from_value(value, unit, source_refs=["사용자 목표 입력"]).to_dict()


def target_input(*, start=2.4, end=2.5, unit="GHz", identity=None):
    """! @brief 실제 성능 보증과 구분한 사용자 목표 입력을 생성한다."""
    return {
        "id": identity or str(uuid4()), "name": "사용자 목표", "physical_mode": "radiating_rf",
        "band": {"start": frequency(start, unit), "end": frequency(end, unit),
                 "reference": Quantity.missing("frequency", "GHz").to_dict(), "sampling": {"kind": "linear", "count": 11}},
        "port_id": None, "reference_impedance": Quantity.missing("impedance", "ohm").to_dict(),
        "criteria": [
            {"metric": "s11_db", "operator": "le", "limit": {"value": -10.0, "unit": "dB", "status": "user_entered", "source_refs": ["사용자 정합 목표"]}},
            {"metric": "total_efficiency", "operator": "ge", "limit": {"value": None, "unit": "1", "status": "missing", "source_refs": []}},
        ],
        "source_refs": ["인증 또는 측정값이 아닌 사용자 입력"],
    }


def command(document, kind, payload):
    """! @brief 실제 공개 명령과 같은 입력으로 새 도메인 개정을 생성한다."""
    return apply_command(document, {"command_id": str(uuid4()), "type": kind, "payload": payload}, document["revision_id"])


def set_target(document, value):
    """! @brief 목표 입력을 공개 target.set payload로 변환한다."""
    return command(document, "target.set", {"target": value})


class TargetDomainTests(unittest.TestCase):
    """! @brief 입력 단계의 목표 의미, 실패 원자성과 과거 개정 보존을 검증한다."""

    def test_multiple_bands_units_missing_metrics_and_source_are_preserved(self):
        """! @brief 떨어진 대역과 단위의 SI 값은 보존되며 미정 지표는 합격하지 않는다."""
        first = target_input()
        second = target_input(start=5.7e9, end=5.9e9, unit="Hz")
        document = new_project("다중 대역")
        document, changed, invalidation, _ = set_target(document, first)
        document = set_target(document, second)[0]
        by_id = {item["id"]: item for item in document["targets"]}
        self.assertEqual(by_id[first["id"]]["band"]["start"]["value_si"], 2.4e9)
        self.assertEqual(by_id[second["id"]]["band"]["end"]["value_si"], 5.9e9)
        self.assertEqual(by_id[second["id"]]["band"]["end"]["display_unit"], "Hz")
        equivalent = target_input(start=2.4e9, end=2.5e9, unit="Hz")
        self.assertEqual(first["band"]["start"]["value_si"], equivalent["band"]["start"]["value_si"])
        self.assertEqual(changed, [first["id"]])
        self.assertEqual(invalidation, ["revision", "metrics", "assessment", "exports"])
        status = target_input_status(by_id[first["id"]])
        self.assertEqual(status["metrics"]["s11_db"], "not_evaluated")
        self.assertEqual(status["metrics"]["total_efficiency"], "missing_target")
        self.assertEqual(status["metrics"]["radiation_efficiency"], "missing_target")
        self.assertEqual(status["evaluation_status"], "not_evaluated")
        self.assertEqual(set(status["missing_conditions"]), {"port_id", "reference_impedance", "band.reference"})
        self.assertIsNone(by_id[first["id"]]["reference_impedance"]["value_si"])
        self.assertEqual(document["materials"], [])
        first["source_refs"].append("외부 변경")
        first["criteria"][0]["limit"]["source_refs"].append("외부 변경")
        self.assertNotIn("외부 변경", by_id[first["id"]]["source_refs"])
        self.assertNotIn("외부 변경", by_id[first["id"]]["criteria"][0]["limit"]["source_refs"])

    def test_explicit_sampling_and_reference_frequency(self):
        """! @brief 명시적 표본과 기준 주파수를 저장하고 중복/범위 위반을 거부한다."""
        value = target_input()
        value["band"]["reference"] = frequency(2.45)
        value["band"]["sampling"] = {"kind": "explicit", "frequencies": [frequency(2.4), frequency(2.45), frequency(2.5)]}
        document = set_target(new_project("명시 표본"), value)[0]
        self.assertEqual(document["targets"][0]["band"], value["band"])
        for samples in ([2.4, 2.4], [2.5, 2.4], [2.3, 2.5], [2.4, 2.6]):
            bad = deepcopy(value)
            bad["band"]["sampling"]["frequencies"] = [frequency(item) for item in samples]
            with self.subTest(samples=samples), self.assertRaises(ProjectError):
                set_target(document, bad)

    def test_invalid_input_does_not_change_the_document(self):
        """! @brief 단위/수치/미지원 의미 오류는 원본 전체를 그대로 보존한다."""
        def assign(value, path, item):
            """! @brief 시험용으로 하나의 정확한 입력 위치만 바꾼다."""
            current = value
            for key in path[:-1]:
                current = current[key]
            current[path[-1]] = item
        cases = [
            (("band", "start"), frequency(0)), (("band", "end"), frequency(2.3)),
            (("band", "reference"), frequency(3)), (("band", "start", "value_si"), float("nan")),
            (("band", "start"), Quantity.from_value(1, "mm").to_dict()),
            (("band", "sampling", "count"), True), (("band", "sampling", "count"), 1002),
            (("criteria", 0, "metric"), "realized_gain"), (("criteria", 0, "operator"), "ge"),
            (("criteria", 0, "limit", "unit"), "1"), (("criteria", 0, "limit", "value"), True),
            (("criteria", 0, "limit", "value"), float("inf")), (("criteria", 0, "limit", "value"), 1.0),
            (("criteria", 1, "limit", "status"), "source_default"),
            (("physical_mode",), "nfc"), (("port_id",), str(uuid4())),
            (("reference_impedance",), Quantity.from_value(-1, "ohm").to_dict()),
            (("source_refs",), [None]), (("source_refs",), ["\0"]),
        ]
        document = new_project("오류 보존")
        original = canonical_bytes(document)
        for path, item in cases:
            value = target_input()
            assign(value, path, item)
            with self.subTest(path=path, item=item), self.assertRaises(ProjectError):
                set_target(document, value)
            self.assertEqual(canonical_bytes(document), original)

    def test_set_remove_inverse_restores_values_with_new_target_revision(self):
        """! @brief 역명령은 이전 의미를 복원하며 과거 목표 개정은 재사용하지 않는다."""
        original = new_project("목표 개정")
        value = target_input()
        added, _, _, undo_add = set_target(original, value)
        frozen = deepcopy(added)
        replacement = deepcopy(value)
        replacement["criteria"][0]["limit"]["value"] = -15.0
        updated, _, _, inverse = set_target(added, replacement)
        self.assertEqual(added, frozen)
        self.assertNotEqual(added["targets"][0]["revision_id"], updated["targets"][0]["revision_id"])
        restored = command(updated, inverse["type"], inverse["payload"])[0]
        self.assertEqual({key: item for key, item in restored["targets"][0].items() if key != "revision_id"}, value)
        self.assertNotEqual(restored["targets"][0]["revision_id"], added["targets"][0]["revision_id"])
        removed, _, _, inverse_remove = command(restored, "target.remove", {"id": value["id"]})
        self.assertEqual(removed["targets"], [])
        self.assertEqual(command(removed, inverse_remove["type"], inverse_remove["payload"])[0]["targets"][0]["source_refs"], value["source_refs"])
        self.assertEqual(command(added, undo_add["type"], undo_add["payload"])[0]["targets"], [])
        with self.assertRaises(ProjectError):
            command(removed, "target.remove", {"id": value["id"]})

    def test_port_dependency_and_global_ids_are_checked_in_both_directions(self):
        """! @brief 목표의 포트 제거 및 설계 객체/목표 개정 UUID 충돌을 차단한다."""
        document = fixture_document()
        value = target_input()
        value["port_id"] = document["ports"][0]["id"]
        document = set_target(document, value)[0]
        before = canonical_bytes(document)
        with self.assertRaises(ProjectError):
            command(document, "port.remove", {"id": value["port_id"]})
        payload = {key: deepcopy(document[key]) for key in ("materials", "stackup", "ports")}
        payload.update(ports=[], selection=None)
        with self.assertRaises(ProjectError):
            command(document, "pcb_stackup.apply", payload)
        self.assertEqual(canonical_bytes(document), before)
        for identity in (document["project_id"], document["revision_id"], document["frames"]["world"]["id"], document["board"]["id"], document["materials"][0]["id"], document["targets"][0]["revision_id"]):
            with self.subTest(identity=identity), self.assertRaises(ProjectError):
                set_target(document, target_input(identity=identity))
        for identity in (value["id"], document["targets"][0]["revision_id"]):
            with self.subTest(reverse=identity), self.assertRaises(ProjectError):
                command(document, "net.set", {"net": {"id": identity, "name": "충돌 네트"}})
        corrupted = deepcopy(document)
        corrupted["targets"][0]["revision_id"] = value["id"]
        with self.assertRaises(ProjectError):
            validate_project(corrupted)

    def test_old_schemas_remain_read_only_and_next_command_migrates(self):
        """! @brief 0.1/0.2 읽기는 바이트를 유지하고 변경 복사본만 0.3이 된다."""
        for schema in READABLE_SCHEMA_VERSIONS[:-1]:
            document = new_project("과거 원본") if schema.endswith("0.1") else build_design(with_port=True)
            document["schema_version"] = schema
            before = canonical_bytes(document)
            validate_project(document)
            updated = set_target(document, target_input())[0]
            self.assertEqual(canonical_bytes(document), before)
            self.assertEqual(updated["schema_version"], SCHEMA_VERSION)
            self.assertEqual(updated["parent_revision_ids"], [document["revision_id"]])
            invalid_legacy = deepcopy(updated)
            invalid_legacy["schema_version"] = schema
            with self.assertRaises(ProjectError):
                validate_project(invalid_legacy)
            self.assertEqual(updated["materials"], document["materials"])

    def test_unknown_fields_duplicate_metrics_and_target_budget_are_rejected(self):
        """! @brief 범위가 없는 확장 입력과 자원 상한 초과를 조용히 허용하지 않는다."""
        document = new_project("상한")
        value = target_input()
        value["criteria"].append(deepcopy(value["criteria"][0]))
        with self.assertRaises(ProjectError):
            set_target(document, value)
        value = target_input()
        value["protocol"] = "자동 인증"
        with self.assertRaises(ProjectError):
            set_target(document, value)
        for index in range(MAX_TARGETS):
            document = set_target(document, target_input())[0]
        with self.assertRaises(ProjectError):
            set_target(document, target_input())

    def test_actual_pcb_and_cad_plans_preserve_targets_without_changing_settings(self):
        """! @brief 해석 계획은 목표 원본만 보존하며 대역/물성/물리 형상을 자동 변경하지 않는다."""
        document = fixture_document()
        before = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        value = target_input(start=2.4, end=2.5)
        value["port_id"] = document["ports"][0]["id"]
        document = set_target(document, value)[0]
        original = canonical_bytes(document)
        after = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        validate_pcb_plan(after)
        self.assertEqual(after["case"], before["case"])
        self.assertEqual(after["source_semantics"]["targets"], document["targets"])
        self.assertEqual(after["case"]["settings"], SETTINGS)
        self.assertEqual(canonical_bytes(document), original)
        cad = build_cad_input(document, snapshot_for(document))
        self.assertEqual(cad["source_semantics"]["targets"], document["targets"])
        self.assertEqual(document["materials"], before["source_semantics"]["materials"])

    def test_supported_historical_snapshots_build_plans_without_rehashing(self):
        """! @brief 과거 스키마의 봉인 참조와 hash를 그대로 소비한다."""
        for schema in READABLE_SCHEMA_VERSIONS:
            document = new_project("참조 사례")
            document["schema_version"] = schema
            snapshot = snapshot_for(document)
            before = deepcopy((document, snapshot))
            plan = build_analysis_plan(document, snapshot, runtime_identity(), 1.0)
            validate_reference_plan(plan)
            self.assertEqual(plan["snapshot"], snapshot)
            self.assertEqual((document, snapshot), before)
        document = fixture_document()
        document["schema_version"] = "rfad.project/0.2"
        snapshot = snapshot_for(document)
        expected = deepcopy(snapshot)
        plan = build_pcb_plan(document, snapshot, runtime_identity(), SETTINGS)
        validate_pcb_plan(plan)
        self.assertEqual(plan["snapshot"], expected)
        build_cad_input(document, snapshot)


class TargetServiceTests(unittest.TestCase):
    """! @brief 실제 공개 RPC와 파일 저장소에서 목표의 전체 명령 수명을 검사한다."""

    def setUp(self):
        """! @brief worker 실행 없이 파일 작업만 제어할 임시 저장소를 준비한다."""
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.service = ProjectService(self.workspace, auto_run=False)
        self.project = self.complete("project.open", {"path": "projects/targets", "open_mode": "create", "name": "다중 목표"}, context={})
        self.project_id = self.project["project_id"]
        self.revision = self.project["revision_id"]

    def tearDown(self):
        """! @brief 파일 잠금과 임시 자료를 해제한다."""
        self.service.close()
        self.temp.cleanup()

    def request(self, data, context=None):
        """! @brief 공개 계약과 현재 서비스의 영속 멱등 키를 사용한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project_id} if context is None else context,
                "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def rpc(self, method, params):
        """! @brief 직접 도메인 접근 대신 실제 JSON RPC 입력을 통과시킨다."""
        frame = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        response = handle_frame(json.dumps(frame, ensure_ascii=False).encode("utf-8"), self.service)
        self.assertNotIn("error", response, response)
        return response["result"]

    def complete(self, method, data, context=None):
        """! @brief 공개 접수 후 자료 처리 작업을 완료한다."""
        task = self.rpc(method, self.request(data, context))
        self.assertTrue(self.service.run_next())
        status = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def apply(self, kind, payload):
        """! @brief 성공한 공개 명령 응답으로 현재 개정을 갱신한다."""
        params = self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": kind, "payload": payload})
        response = self.rpc("project.apply_command", params)
        self.revision = response["new_revision"]
        return response, params

    def reopen(self):
        """! @brief 등록된 프로젝트의 실제 저장 원본을 공개 API로 읽는다."""
        return self.complete("project.open", {"open_mode": "open", "path": "projects/targets"}, {})

    def history(self, method):
        """! @brief 실행 취소와 재실행도 현재 개정으로 요청한다."""
        result = self.rpc(method, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
        self.revision = result["new_revision"]

    def test_public_save_restart_reopen_snapshot_undo_redo_and_retry(self):
        """! @brief 다중 대역과 출처/미정 상태를 모든 영속 경계에서 보존한다."""
        first, second = target_input(), target_input(start=5.7, end=5.9)
        self.apply("target.set", {"target": first})
        response, params = self.apply("target.set", {"target": second})
        self.assertEqual(self.rpc("project.apply_command", params), response)
        before = self.reopen()["document"]
        snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})
        sealed = self.service.journal.read_artifact(snapshot["artifact"])
        self.complete("project.save", {"expected_revision": self.revision})
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        reopened = self.reopen()
        self.assertEqual(reopened["document"], before)
        self.assertEqual(reopened["target_input_statuses"][0]["evaluation_status"], "not_evaluated")
        self.assertEqual(self.rpc("project.apply_command", params), response)
        self.history("project.undo")
        self.assertEqual([item["id"] for item in self.reopen()["document"]["targets"]], [first["id"]])
        self.history("project.redo")
        restored = self.reopen()["document"]
        self.assertEqual({item["id"] for item in restored["targets"]}, {first["id"], second["id"]})
        self.assertEqual(self.service.journal.read_artifact(snapshot["artifact"]), sealed)
        self.assertEqual(json.loads(sealed), before)
        self.apply("target.remove", {"id": first["id"]})
        self.history("project.undo")
        restored = self.reopen()["document"]
        self.assertEqual(next(item for item in restored["targets"] if item["id"] == first["id"])["source_refs"], first["source_refs"])
        self.assertEqual(restored["materials"], [])

    def test_public_stale_revision_and_invalid_target_preserve_journal(self):
        """! @brief 목표 실패가 이력, receipt 또는 현재 개정을 게시하지 않는다."""
        _, params = self.apply("target.set", {"target": target_input()})
        before = self.service.journal.read()
        stale = deepcopy(params)
        stale["request_key"], stale["input"]["command_id"] = str(uuid4()), str(uuid4())
        for request in (stale, self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": "target.set", "payload": {"target": target_input(start=3, end=2)}})):
            frame = {"jsonrpc": "2.0", "id": 1, "method": "project.apply_command", "params": request}
            response = handle_frame(json.dumps(frame).encode(), self.service)
            self.assertIn("error", response)
            self.assertEqual(self.service.journal.read(), before)

    def test_old_registered_revisions_migrate_without_overwriting_source_or_snapshot(self):
        """! @brief 기존 등록 원본과 봉인 바이트는 첫 새 명령 이후에도 보존된다."""
        for schema in READABLE_SCHEMA_VERSIONS[:-1]:
            document = new_project("과거 파일", project_id=self.project_id)
            document["schema_version"] = schema
            raw = canonical_bytes(document)
            def install(state):
                """! @brief 구버전 앱이 기록한 등록 상태를 손상 없이 시험에 준비한다."""
                reference = self.service.repository.store("projects/targets", document)
                project = state["projects"][self.project_id]
                project.update(current=reference, saved=deepcopy(reference), revisions={document["revision_id"]: reference},
                               history={"undo": [], "redo": [], "head_revision": document["revision_id"]})
            self.service.journal.transaction(install)
            self.revision = document["revision_id"]
            opened = self.reopen()
            self.assertEqual(canonical_bytes(opened["document"]), raw)
            snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})
            self.assertEqual(snapshot["schema_version"], schema)
            changed, params = self.apply("target.set", {"target": target_input()})
            self.assertEqual(changed["schema_migration"], {"from": schema, "to": SCHEMA_VERSION, "original_revision": document["revision_id"]})
            record = self.service.journal.read()["commands"][params["input"]["command_id"]]
            self.assertEqual(record["schema_migration"], changed["schema_migration"])
            self.assertEqual(self.service.journal.read_artifact(record["previous_artifact"]), raw)
            self.assertEqual(self.service.journal.read_artifact(snapshot["artifact"]), raw)
            self.assertEqual(snapshot["content_hash"], canonical_hash(document))
            self.assertEqual(self.reopen()["document"]["schema_version"], SCHEMA_VERSION)

    def test_capabilities_distinguish_input_storage_from_evaluation(self):
        """! @brief 저장 지원 목록과 아직 제공하지 않는 판정/자동설정을 공개한다."""
        params = {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}
        response = handle_frame(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "capabilities.get", "params": params}).encode(), self.service)
        self.assertNotIn("error", response, response)
        profile = response["result"]["project_profile"]
        self.assertEqual(profile["readable_schema_versions"], list(READABLE_SCHEMA_VERSIONS))
        self.assertIn("target.set", profile["commands"])
        self.assertIn("target.remove", profile["commands"])
        self.assertEqual(set(profile["target_input"]["metrics"]), set(METRICS))
        self.assertFalse(profile["target_input"]["evaluation_supported"])
        self.assertFalse(profile["target_input"]["changes_solver_settings"])


