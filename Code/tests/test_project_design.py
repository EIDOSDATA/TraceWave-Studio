"""! @brief 실제 저장소에서 설계와 표현식의 저장, 실패 보존, 입력 검증을 확인한다."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity
from test_design import build_design


class ProjectDesignTests(unittest.TestCase):
    """! @brief GUI와 자동화가 공유하는 명령 경로의 설계 데이터 통합을 검증한다."""

    def setUp(self):
        """! @brief 실제 파일 저장소와 현재 프로젝트를 준비한다."""
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.service = ProjectService(self.workspace, auto_run=False)
        self.project = self.complete("project.open", {"path": "projects/design", "open_mode": "create", "name": "설계"}, context={})
        self.project_id = self.project["project_id"]
        self.revision = self.project["revision_id"]

    def tearDown(self):
        """! @brief 잠금과 임시 파일을 정리한다."""
        self.service.close()
        self.temp.cleanup()

    def request(self, data, context=None):
        """! @brief 영속 멱등 키와 현재 프로젝트 문맥을 지정한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project_id} if context is None else context, "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def result(self, task):
        """! @brief 대기열의 한 작업을 수행하고 완료 결과를 읽는다."""
        self.assertTrue(self.service.run_next())
        status = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def complete(self, method, data, context=None):
        """! @brief 접수된 작업을 실제로 완료한다."""
        return self.result(self.service.mutate(method, self.request(data, context)))

    def command(self, kind, payload):
        """! @brief 명령 성공 후 다음 명령의 기준 개정을 갱신한다."""
        response = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": kind, "payload": payload}))
        self.revision = response["new_revision"]
        return response

    def install_design(self):
        """! @brief 모든 의미 객체를 실제 명령으로 등록한다."""
        design = build_design()
        frame = self.project["document"]["frames"]["board"]["id"]
        design["board"]["frame_id"] = frame
        self.command("board.set", {"board": design["board"]})
        for collection, kind in (("materials", "material"), ("stackup", "layer"), ("nets", "net"), ("geometry", "geometry"), ("ports", "port")):
            for entity in design[collection]:
                if "frame_id" in entity:
                    entity["frame_id"] = frame
                self.command(kind + ".set", {kind: entity})
        return design

    def test_design_survives_save_snapshot_restart_and_reopen(self):
        design = self.install_design()
        expected = {key: design[key] for key in ("board", "materials", "stackup", "nets", "geometry", "ports")}
        self.complete("project.save", {"expected_revision": self.revision})
        snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})
        frozen = self.service.journal.read_artifact(snapshot["artifact"])
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        reopened = self.complete("project.open", {"open_mode": "open", "path": "projects/design"}, {})
        self.assertEqual({key: reopened["document"][key] for key in expected}, expected)
        self.assertEqual(json.loads(frozen), reopened["document"])
        self.command("metadata.rename", {"name": "다음 개정"})
        self.assertEqual(self.service.journal.read_artifact(snapshot["artifact"]), frozen)

    def test_validation_is_captured_revision_and_missing_material_never_becomes_zero(self):
        self.install_design()
        captured = self.revision
        params = self.request({"expected_revision": captured, "purpose": "em", "profile": "rfad.design/0.1"})
        task = self.service.mutate("design.validate", params)
        self.command("metadata.rename", {"name": "검증 이후"})
        report = self.result(task)
        self.assertEqual(report["revision_id"], captured)
        self.assertEqual(report["input_status"], "blocked")
        self.assertFalse(report["solver_ready"])
        self.assertIn("E_MATERIAL_UNKNOWN", {item["code"] for item in report["diagnostics"]})
        self.assertEqual(self.service.mutate("design.validate", params), task)
        geometry = self.complete("design.validate", {"expected_revision": self.revision, "purpose": "geometry", "profile": "rfad.design/0.1"})
        self.assertEqual(geometry["input_status"], "valid")
        self.assertFalse(geometry["solver_ready"])

    def test_invalid_geometry_and_referenced_removal_preserve_journal(self):
        design = self.install_design()
        bad = deepcopy(design["geometry"][0])
        bad["end"] = deepcopy(bad["start"])
        for kind, payload in (("geometry.set", {"geometry": bad}), ("layer.remove", {"id": design["stackup"][0]["id"]}), ("material.remove", {"id": design["materials"][0]["id"]})):
            before = self.service.journal.read()
            with self.assertRaises(ProjectError):
                self.command(kind, payload)
            self.assertEqual(self.service.journal.read(), before)

    def test_expression_snapshot_preserves_source_and_recomputes_after_reopen(self):
        width, derived = str(uuid4()), str(uuid4())
        self.command("parameter.set", {"id": width, "name": "보드 폭", "quantity": Quantity.from_value(40, "mm").to_dict()})
        self.command("parameter.set_expression", {"id": derived, "name": "절반 폭", "expression": "width / 2", "bindings": {"width": width}, "dimension": "length", "display_unit": "mm"})
        snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})
        raw = self.service.journal.read_artifact(snapshot["artifact"])
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        response = self.command("parameter.set", {"id": width, "name": "보드 폭", "quantity": Quantity.from_value(60, "mm").to_dict()})
        self.assertEqual(set(response["changed_ids"]), {width, derived})
        reopened = self.complete("project.open", {"open_mode": "open", "path": "projects/design"}, {})
        self.assertAlmostEqual(reopened["document"]["parameters"][derived]["quantity"]["value_si"], 0.03)
        self.assertAlmostEqual(json.loads(raw)["parameters"][derived]["quantity"]["value_si"], 0.02)
        self.assertEqual(self.service.journal.read_artifact(snapshot["artifact"]), raw)

    def test_rpc_advertises_only_implemented_profile_and_structured_expression_errors(self):
        hello = {"jsonrpc": "2.0", "id": "한글", "method": "capabilities.get", "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
        response = handle_frame(json.dumps(hello).encode(), self.service)["result"]
        self.assertIn("design.validate", response["methods"])
        self.assertIn("parameter.set_expression", response["project_profile"]["commands"])
        self.assertEqual(response["project_profile"]["schema_version"], "rfad.project/0.2")
        payload = {"id": str(uuid4()), "name": "잘못된 계산", "expression": "sqrt(-1) * 1 mm", "bindings": {}, "dimension": "length", "display_unit": "mm"}
        request = {"jsonrpc": "2.0", "id": 2, "method": "project.apply_command", "params": self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": "parameter.set_expression", "payload": payload})}
        error = handle_frame(json.dumps(request).encode(), self.service)["error"]
        self.assertEqual(error["data"]["domain_code"], "E_EXPR_DOMAIN")
        self.assertEqual(error["code"], 1010)


if __name__ == "__main__":
    unittest.main()
