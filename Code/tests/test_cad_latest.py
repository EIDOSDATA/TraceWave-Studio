"""! @brief GUI 재열기의 CAD 완료 참조 조회가 프로젝트와 영속 상태 경계를 지키는지 확인한다."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame


class CadLatestTests(unittest.TestCase):
    """! @brief 큰 CAD 파일을 읽지 않는 공개 조회와 재시작 복원을 검증한다."""

    def setUp(self):
        """! @brief 서로 다른 프로젝트의 실제 journal을 준비한다."""
        self.temporary = TemporaryDirectory(prefix="rfad CAD 최근 ")
        self.workspace = Path(self.temporary.name)
        self.service = ProjectService(self.workspace, auto_run=False)
        self.first = self.create_project("첫 프로젝트")
        self.second = self.create_project("다른 프로젝트")

    def tearDown(self):
        """! @brief 서비스 잠금과 임시 저장소를 회수한다."""
        self.service.close()
        self.temporary.cleanup()

    def create_project(self, name):
        """! @brief 공개 명령으로 프로젝트 등록을 완료한다."""
        task = self.service.mutate("project.open", {
            "contract_version": "rfad.api/2.0", "context": {},
            "input": {"path": "projects/" + name, "open_mode": "create", "name": name},
            "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"],
        })
        self.service.run_next()
        result = self.service.status({"contract_version": "rfad.api/2.0", "context": {},
                                      "input": {"job_id": task["job_id"]}})
        return result["events"][-1]["operation_result"]["project_id"]

    def params(self, project=None):
        """! @brief 조회에는 mutation key나 현재 draft 개정을 넣지 않는다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": project or self.first}, "input": {}}

    def rpc(self, params):
        """! @brief 실제 JSON-RPC 라우팅과 응답 식별자 보존을 확인한다."""
        response = handle_frame(json.dumps({"jsonrpc": "2.0", "id": "최근 CAD", "method": "cad.latest", "params": params}).encode(), self.service)
        self.assertEqual(response["id"], "최근 CAD")
        return response

    def record(self, project, timestamp, state="completed", *, cad=True):
        """! @brief native 계산과 무관한 조회 시험용 게시 기록을 journal transaction에 넣는다."""
        identity, run_id, snapshot_id = str(uuid4()), str(uuid4()), str(uuid4())
        result = {"status": "generated_unverified", "snapshot": {"snapshot_id": snapshot_id},
                  "run_id": run_id, "artifacts": [{"uri": "projects/시험/artifacts/" + run_id + "/mesh.json", "role": "display_mesh"}]}
        event = {"seq": 1, "run_id": run_id, "timestamp": timestamp, "state": state,
                 "phase": state, "progress_basis": "indeterminate"}
        if state == "completed":
            event["operation_result"] = result
        job = {"job_id": identity, "run_id": run_id, "kind": "export", "operation_method": "export.build" if cad else "export.preview",
               "context": {"project_id": project}, "state": state, "events": [event]}
        if cad:
            job["cad"] = {"resource_reserved": False}
        self.service.journal.transaction(lambda store: store["jobs"].update({identity: job}))
        return identity, result

    def test_empty_result_and_capability_are_explicit(self):
        """! @brief 완료 CAD가 없는 프로젝트는 추정 결과를 반환하지 않는다."""
        self.assertEqual(self.rpc(self.params())["result"], {"profile": "rfad.cad-view/0.1", "result": None, "job_id": None})
        capability = handle_frame(json.dumps({"jsonrpc": "2.0", "id": "cap", "method": "capabilities.get",
            "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}).encode(), self.service)["result"]
        self.assertEqual(capability["methods"]["cad.latest"]["extension_profile"], "rfad.cad-view/0.1")

    def test_latest_is_project_scoped_ignores_failed_and_preview_and_does_not_read_files(self):
        """! @brief 삽입 순서 대신 완료 시각을 사용하고 다른 프로젝트나 실패를 채택하지 않는다."""
        selected, result = self.record(self.first, 200)
        self.record(self.first, 100)
        self.record(self.first, 500, "failed")
        self.record(self.first, 700, "cancelled")
        self.record(self.first, 900, cad=False)
        self.record(self.second, 1000)
        before = self.service.journal.read()
        with patch.object(self.service.journal, "read_artifact", side_effect=AssertionError("No bulk artifact reads")):
            actual = self.rpc(self.params())["result"]
        self.assertEqual(actual, {"profile": "rfad.cad-view/0.1", "result": result, "job_id": selected})
        actual["result"]["artifacts"].clear()
        self.assertEqual(before, self.service.journal.read())

    def test_latest_survives_service_restart_without_cad_runtime(self):
        """! @brief CAD 환경을 시작하지 않아도 과거 게시 결과 참조를 복원한다."""
        selected, result = self.record(self.first, 200)
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.assertEqual(self.rpc(self.params())["result"], {"profile": "rfad.cad-view/0.1", "result": result, "job_id": selected})

    def test_invalid_project_envelope_and_input_are_rejected_without_mutation(self):
        """! @brief 등록되지 않은 프로젝트와 미지원 필드를 조회로 우회할 수 없다."""
        cases = []
        for field, value in (("contract_version", "wrong"), ("context", {}), ("context", {"project_id": str(uuid4())}),
                             ("input", {"path": "../other"})):
            params = self.params()
            params[field] = value
            cases.append(params)
        extra = deepcopy(self.params())
        extra["request_key"] = str(uuid4())
        cases.append(extra)
        before = self.service.journal.read()
        for params in cases:
            with self.subTest(params=params):
                self.assertIn("error", self.rpc(params))
        self.assertEqual(before, self.service.journal.read())


if __name__ == "__main__":
    unittest.main()
