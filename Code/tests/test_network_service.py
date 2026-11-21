"""! @brief 복소 원본/미정/파생 자료의 검토와 원자 저장 및 재열기를 검증한다."""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import network_service
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import KEY, validate_library
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture
from test_design_rules import scenario


def import_parameters(port=None, *, declared=True, count=3):
    """! @brief 원문 주석과 실측 미정 조건이 있는 알려진 복소 반사 자료다."""
    frequencies = [1e9 + 1e9 * index / (count - 1) for index in range(count)]
    raw = ("! 사용자 원문 출처\n# Hz S RI R 50\n" + "".join(f"{value:.17g} 0.1 0\n" for value in frequencies)).encode("utf-8")
    declarations = {"conditions": {"manufacturing": None, "measurement": None}, "source_refs": ["시험 자료; 실측 아님"]}
    if declared:
        declarations.update(wave_definition="traveling", phasor_convention="exp(+j*omega*t)",
            reference_planes=["시험 기준면"], current_orientation=["into_dut"], port_modes=["single_ended"])
    if port is not None:
        declarations["port_ids"] = [port]
    return {"name": "원본 반사 자료", "file_name": "한글 시험.s1p", "format": "touchstone",
            "source_base64": base64.b64encode(raw).decode("ascii"), "mapping": None, "declarations": declarations}


def circuit_definition(*, missing=False):
    """! @brief 50 ohm 부하와 직렬 결합을 독립 해석할 수 있는 이상 저항망이다."""
    return {"schema": "rfad.ideal-rlc/0.1", "name": "외부 직렬 저항", "em_scope": "outside_em",
            "input_reference_plane": "입력 기준면", "load_reference_plane": "시험 기준면",
            "elements": [{"id": str(uuid4()), "name": "R1", "connection": "series", "kind": "R", "state": "connected",
                          "value": {"text": "" if missing else "50", "unit": "ohm", "source_refs": ["명시 이상 저항 가정"]},
                          "source_refs": ["부품 모델 측정 미확보"]}],
            "source_refs": ["원래 회로 출처"], "assumptions": ["EM 외부의 이상 소자; 패드와 배선 기생 미포함"]}


class NetworkServiceTests(unittest.TestCase):
    """! @brief 실제 프로젝트 저장소와 명령 영수증으로 기능 경계를 검사한다."""

    def setUp(self):
        """! @brief 기존 목표/연결/물성 원본이 있는 프로젝트를 격리 등록한다."""
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "복소 자료 시험"
        self.service = ProjectService(self.workspace, auto_run=False)
        self.original = scenario()
        self.original["extensions"]["test.source"] = {"fabrication": None, "measurement": None, "source_refs": ["원문 보존"]}
        self.original, self.snapshot = register_fixture(self.service, self.original)
        self.project = self.original["project_id"]
        self.revision = self.original["revision_id"]

    def tearDown(self):
        """! @brief 시험이 소유한 workspace와 서비스를 닫는다."""
        self.service.close()
        self.temp.cleanup()

    def request(self, data, *, mutation=False):
        """! @brief 읽기와 영수증을 가진 쓰기를 구분한다."""
        result = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": data}
        if mutation:
            result.update(request_key=str(uuid4()), request_key_epoch=self.service.policy()["request_key_epoch"])
        return result

    def document(self):
        """! @brief 권위 개정의 실제 저장 원본을 읽는다."""
        return self.service._load(self.service.journal.read()["projects"][self.project])

    def read(self, method, **values):
        """! @brief 읽기 요청의 기준 개정을 명시한다."""
        return network_service.read(self.service.host_calculation_context, method, self.request({"expected_revision": self.revision, **values}))

    def preview(self, operation, parameters):
        """! @brief 검토 전후 journal이 동일한지 함께 확인한다."""
        before = self.service.journal.read()
        result = self.read("network.preview", operation=operation, parameters=parameters)
        self.assertEqual(before, self.service.journal.read())
        return result

    def apply(self, operation, parameters):
        """! @brief 검토한 후보만 동일 요청 영수증으로 적용한다."""
        preview = self.preview(operation, parameters)
        self.assertTrue(preview["can_apply"], preview)
        request = self.request({"expected_revision": self.revision, "operation": operation, "parameters": parameters,
                                "command_id": str(uuid4()), "review_hash": preview["review_hash"]}, mutation=True)
        result = self.service.mutate("network.apply", request)
        self.assertEqual(result, self.service.mutate("network.apply", request))
        self.revision = result["new_revision"]
        return result["record_id"]

    def history(self, operation):
        """! @brief 불변 파일을 다시 계산하지 않는 기존 undo/redo를 사용한다."""
        result = self.service.mutate("project." + operation, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}, mutation=True))
        self.revision = result["new_revision"]

    def save_reopen(self):
        """! @brief 실제 저장 작업 후 서비스를 닫고 동일 workspace를 새로 연다."""
        task = self.service.mutate("project.save", self.request({"expected_revision": self.revision}, mutation=True))
        self.service.run_next()
        self.assertEqual(self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})["state"], "completed")
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.assertEqual(self.document()["revision_id"], self.revision)

    def test_source_hdf5_missing_conditions_history_and_reopen(self):
        """! @brief 원문 bytes/미정/기존 출처/불변 snapshot이 이력과 재열기를 통과한다."""
        parameters = import_parameters(declared=False)
        before = self.document()
        identity = self.apply("import", parameters)
        entry = self.read("network.library")["datasets"][0]
        raw = self.service.journal.read_artifact(entry["raw"])
        self.assertEqual(raw, base64.b64decode(parameters["source_base64"]))
        self.assertTrue(self.service.journal.read_artifact(entry["normalized_hdf5"]).startswith(b"\x89HDF"))
        response = self.read("network.get", dataset_id=identity, offset=0, limit=201, row=0, column=0)
        self.assertEqual(response["descriptor"]["reference_planes"], [None])
        self.assertEqual(response["descriptor"]["phasor_convention"], "unknown")
        self.assertEqual(response["descriptor"]["conditions"], {"manufacturing": None, "measurement": None})
        after = self.document()
        for key in ("board", "materials", "geometry", "ports", "targets", "parameters", "connections", "manufacturing_profiles"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["extensions"]["test.source"], before["extensions"]["test.source"])
        self.history("undo")
        self.assertNotIn(KEY, self.document()["extensions"])
        self.history("redo")
        self.save_reopen()
        self.assertEqual(self.read("network.library")["datasets"][0], entry)
        snapshot = self.workspace / self.snapshot["artifact"]["uri"]
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), self.snapshot["artifact"]["sha256"])

    def test_preview_hash_stale_revision_and_internal_command_bypass(self):
        """! @brief 검토와 다른 입력 및 내부 명령 직접 적용을 거절한다."""
        parameters = import_parameters()
        candidate = self.preview("import", parameters)
        self.assertTrue(candidate["can_apply"], candidate)
        changed = deepcopy(parameters)
        changed["name"] = "검토하지 않은 이름"
        with self.assertRaises(ProjectError):
            self.service.mutate("network.apply", self.request({"expected_revision": self.revision, "operation": "import", "parameters": changed,
                "command_id": str(uuid4()), "review_hash": candidate["review_hash"]}, mutation=True))
        with self.assertRaises(ProjectError):
            self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
                "type": "network.library.replace", "payload": {"expected_hash": canonical_hash(None), "replacement": None}}, mutation=True))
        self.assertNotIn(KEY, self.document()["extensions"])

    def test_export_roundtrip_does_not_write_or_drop_source(self):
        """! @brief 파일 내보내기는 원본/이력 변경 없이 재해석 가능한 복소 값을 보존한다."""
        identity = self.apply("import", import_parameters())
        state = self.service.journal.read()
        for format_name in ("touchstone", "csv", "hdf5", "source"):
            output = self.read("network.export", dataset_id=identity, format=format_name)
            raw = base64.b64decode(output["content_base64"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), output["sha256"])
            self.assertIsNone(output["sidecar"]["descriptor"]["conditions"]["measurement"])
            if format_name == "source":
                from rfad.adapters.network_files import parse_touchstone
                self.assertEqual(output["file_name"], import_parameters()["file_name"])
                reparsed = parse_touchstone(raw, output["file_name"])
                self.assertEqual(reparsed["network"]["frequency_hz"], [1e9, 1.5e9, 2e9])
                self.assertEqual(reparsed["network"]["values_ri"], [[[[0.1, 0.0]]]] * 3)
        self.assertEqual(state, self.service.journal.read())

    def test_rlc_missing_save_derive_reference_and_parent_protection(self):
        """! @brief 미정 회로 저장과 계산 차단, 원본/회로를 참조한 파생 결과를 분리한다."""
        source = self.apply("import", import_parameters())
        incomplete = self.apply("circuit_save", {"name": "미정 회로", "definition": circuit_definition(missing=True)})
        failed = self.preview("circuit_apply", {"name": "미정 계산", "dataset_id": source, "circuit_id": incomplete})
        self.assertFalse(failed["can_apply"])
        circuit = self.apply("circuit_save", {"name": "명시 회로", "definition": circuit_definition()})
        derived = self.apply("circuit_apply", {"name": "외부 회로 결합", "dataset_id": source, "circuit_id": circuit})
        response = self.read("network.get", dataset_id=derived, offset=0, limit=201, row=0, column=0)
        self.assertEqual(response["descriptor"]["reference_planes"], ["입력 기준면"])
        self.assertAlmostEqual(response["page"]["samples"][0]["real"], 11 / 29)
        self.assertEqual(response["entry"]["inputs"], [source])
        self.assertFalse(self.preview("remove", {"collection": "datasets", "id": source})["can_apply"])
        self.save_reopen()
        self.assertEqual(len(self.read("network.library")["circuits"]), 2)

    def test_complex_load_conditions_and_loss_survive_assessment_reopen(self):
        """! @brief 독립 Z 입력과 목표 평가의 기준면/진단 파일/원본 보존을 확인한다."""
        port = self.document()["ports"][0]["id"]
        target = deepcopy(self.document()["targets"][0])
        parameters = import_parameters(port)
        raw = b"Hz,R,X\n1000000000,25,25\n1500000000,25,25\n2000000000,25,25\n"
        parameters.update(file_name="명시 복소 부하.csv", format="csv", source_base64=base64.b64encode(raw).decode("ascii"),
            mapping={"delimiter": ",", "header": True, "frequency_column": 0, "frequency_unit": "Hz",
                "parameter_kind": "Z", "complex_format": "RI", "value_unit": "ohm", "port_count": 1, "z0_ohm": [50],
                "pairs": [{"row": 0, "column": 0, "first_column": 1, "second_column": 2}], "ignored_columns": []})
        source = self.apply("import", parameters)
        definition = circuit_definition()
        definition["elements"][0]["value"]["text"] = "25"
        circuit = self.apply("circuit_save", {"name": "직렬 25 ohm", "definition": definition})
        coupling = {"name": "명시 복소 Z의 정합 결과", "dataset_id": source, "circuit_id": circuit}
        preview = self.preview("circuit_apply", coupling)
        self.assertTrue(preview["can_apply"], preview)
        self.assertEqual(preview["load_page"]["parameter_kind"], "S")
        self.assertAlmostEqual(preview["power_budget_preview"][0]["ideal_circuit_loss_fraction"], 8 / 17)
        result = self.apply("circuit_apply", coupling)
        evaluation = self.apply("evaluate", {"name": "정합 후 표본 평가", "dataset_id": result, "target_id": target["id"],
            "context": {"port_id": port, "target_port_id": target["port_id"], "reference_plane": "입력 기준면", "frequency_policy": "exact_only"}})
        saved = self.read("network.assessment", assessment_id=evaluation)["assessment"]
        matching = saved["evidence"]["matching"]
        self.assertEqual(matching["load_dataset_id"], source)
        self.assertEqual(matching["load_reference_plane"], "시험 기준면")
        self.assertEqual(matching["input_reference_plane"], "입력 기준면")
        diagnostics = json.loads(self.service.journal.read_artifact(matching["diagnostics"]))
        self.assertAlmostEqual(diagnostics["samples"][2]["power_budget"]["ideal_circuit_loss_fraction"], 8 / 17)
        self.assertFalse(saved["continuous_band_verified"])
        self.save_reopen()
        self.assertEqual(saved, self.read("network.assessment", assessment_id=evaluation)["assessment"])
        entry = self.read("network.get", dataset_id=source, offset=0, limit=201, row=0, column=0)["entry"]
        self.assertEqual(self.service.journal.read_artifact(entry["raw"]), raw)

    def test_1001_sample_pages_and_target_revision_retention(self):
        """! @brief 많은 표본은 페이지로 조회하고 평가 때의 목표/개정 사본을 보존한다."""
        target = deepcopy(self.document()["targets"][0])
        port = self.document()["ports"][0]["id"]
        source = self.apply("import", import_parameters(port, count=1001))
        first = self.read("network.get", dataset_id=source, offset=0, limit=201, row=0, column=0)["page"]
        last = self.read("network.get", dataset_id=source, offset=804, limit=201, row=0, column=0)["page"]
        self.assertEqual(first["next_offset"], 201)
        self.assertEqual(last["total"], 1001)
        self.assertEqual(len(last["samples"]), 197)
        self.assertIsNone(last["next_offset"])
        parameters = {"name": "목표 판정", "dataset_id": source, "target_id": target["id"],
            "context": {"port_id": port, "target_port_id": target["port_id"], "reference_plane": "시험 기준면", "frequency_policy": "exact_only"}}
        identity = self.apply("evaluate", parameters)
        result = self.read("network.assessment", assessment_id=identity)
        self.assertFalse(result["assessment"]["continuous_band_verified"])
        self.assertFalse(result["assessment"]["physics_validated"])
        self.assertEqual(result["assessment"]["evidence"]["target_original"], target)
        old = deepcopy(result["assessment"])
        payload = {key: value for key, value in target.items() if key != "revision_id"}
        payload["name"] = "바꾼 목표 이름"
        changed = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
            "type": "target.set", "payload": {"target": payload}}, mutation=True))
        self.revision = changed["new_revision"]
        self.save_reopen()
        result = self.read("network.assessment", assessment_id=identity)
        self.assertTrue(result["target_changed"])
        self.assertEqual(old, result["assessment"])

    def test_failed_publish_leaves_no_visible_library_and_tamper_is_detected(self):
        """! @brief 파일 기록 실패가 자료 목록 성공으로 게시되지 않으며 원문 손상을 검사한다."""
        parameters = import_parameters()
        candidate = self.preview("import", parameters)
        request = self.request({"expected_revision": self.revision, "operation": "import", "parameters": parameters,
            "command_id": str(uuid4()), "review_hash": candidate["review_hash"]}, mutation=True)
        with patch.object(self.service.journal, "put_immutable", side_effect=ProjectError("E_DISK", "시험 저장 실패")):
            with self.assertRaises(ProjectError):
                self.service.mutate("network.apply", request)
        self.assertNotIn(KEY, self.document()["extensions"])
        identity = self.apply("import", parameters)
        entry = self.read("network.library")["datasets"][0]
        (self.workspace / entry["dataset"]["uri"]).write_bytes(b"changed")
        with self.assertRaises(ProjectError):
            self.read("network.get", dataset_id=identity, offset=0, limit=201, row=0, column=0)

    def test_malformed_and_unsupported_input_preserves_library(self):
        """! @brief 잘못된 파일/기준면 미정은 값을 채우거나 원문을 버리지 않는다."""
        for raw in (b"# GHz S RI R 50\n1 nan 0\n", b"[Version] 2.0\n[Number of Ports] 4\n", b"# GHz S RI R 50\n2 0 0\n1 0 0\n"):
            parameters = import_parameters()
            parameters["source_base64"] = base64.b64encode(raw).decode("ascii")
            self.assertFalse(self.preview("import", parameters)["can_apply"])
        identity = self.apply("import", import_parameters(declared=False))
        self.assertFalse(self.preview("transform", {"name": "미정 조건 변환", "dataset_id": identity,
            "options": {"operation": "convert", "parameter_kind": "Z"}})["can_apply"])
        self.assertEqual(len(self.read("network.library")["datasets"]), 1)
