"""! @brief 결과 그래프 조회와 마지막 완료 참조의 읽기 전용 경계를 검사한다."""

from copy import deepcopy
import json
import unittest
from uuid import uuid4

import test_solver_jobs as fixtures
from rfad.application.canonical import canonical_bytes
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError


class SolverViewTests(unittest.TestCase):
    """! @brief 실제 journal과 명시적 fake 계산 결과로 표시 계약만 검증한다."""

    def setUp(self):
        """! @brief 독립 workspace와 기존 worker 계약 fixture를 사용한다."""
        self.fixture = fixtures.SolverJobTests()
        self.fixture.setUp()
        self.service = self.fixture.service

    def tearDown(self):
        """! @brief fixture가 소유한 자원만 닫는다."""
        self.fixture.tearDown()

    def query(self, method, data):
        """! @brief 표시 조회도 실제 JSON-RPC dispatch로 호출한다."""
        return handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": method, "params": {
            "contract_version": "rfad.api/2.0", "context": {"project_id": self.fixture.project}, "input": data}}), self.service)

    def completed(self):
        """! @brief 실제 계산으로 오인하지 않는 봉인된 도파관 시험 표본을 게시한다."""
        return self.fixture.complete("job.submit", self.fixture.analysis_input(self.fixture.prepared()))

    def test_empty_then_completed_latest_and_chart_are_read_only(self):
        """! @brief 조회는 작업을 접수하거나 원본을 변경하지 않고 snapshot을 보존한다."""
        self.assertIsNone(self.query("solver.latest", {})["result"]["result"])
        result = self.completed()
        before = self.service.journal.read()
        calls = len(self.fixture.transport.calls)
        self.assertEqual(self.query("solver.latest", {})["result"]["result"], result)
        dto = self.query("solver.samples", {"artifact_id": result["artifact_id"]})["result"]
        self.assertEqual(dto["snapshot"], self.fixture.snapshot)
        self.assertEqual(len(dto["samples"]), 31)
        self.assertIsNone(dto["samples"][0]["s11_db"])
        self.assertEqual(dto["samples"][0]["vswr"], 1)
        self.assertEqual(self.service.journal.read(), before)
        self.assertEqual(len(self.fixture.transport.calls), calls)

    def test_snapshot_remains_original_after_edit_and_cancelled_job(self):
        """! @brief 새 편집 또는 취소가 마지막 완료 결과를 현재 개정으로 바꾸지 않는다."""
        result = self.completed()
        self.service.mutate("project.apply_command", self.fixture.request({"expected_revision": self.fixture.revision,
            "command_id": str(uuid4()), "type": "metadata.describe", "payload": {"description": "결과 이후의 편집"}}))
        task = self.service.mutate("solver.plan", self.fixture.request(self.fixture.plan_input()))
        self.service.mutate("job.cancel", self.fixture.request({"job_id": task["job_id"]}, {}))
        self.assertEqual(self.query("solver.latest", {})["result"]["result"]["artifact_id"], result["artifact_id"])
        self.assertEqual(self.query("solver.samples", {"artifact_id": result["artifact_id"]})["result"]["snapshot"], self.fixture.snapshot)

    def test_missing_or_tampered_result_fails_without_computation(self):
        """! @brief 임의 ID와 파일 변조는 그래프를 만들거나 solver 재실행으로 보정하지 않는다."""
        missing = self.query("solver.samples", {"artifact_id": str(uuid4())})
        self.assertEqual(missing["error"]["data"]["domain_code"], "E_MISSING_ARTIFACT")
        result = self.completed()
        calls = len(self.fixture.transport.calls)
        path = self.fixture.workspace / result["normalized_result"]["uri"]
        path.write_bytes(b"{}")
        response = self.query("solver.samples", {"artifact_id": result["artifact_id"]})
        self.assertEqual(response["error"]["data"]["domain_code"], "E_HASH")
        self.assertEqual(len(self.fixture.transport.calls), calls)

    def test_plot_rejects_unsupported_input_fields(self):
        """! @brief 조회에 실행 옵션을 끼워 넣거나 미지원 표본 범위를 요청할 수 없다."""
        response = self.query("solver.samples", {"artifact_id": str(uuid4()), "execute": True})
        self.assertEqual(response["error"]["data"]["domain_code"], "E_SCHEMA")

    def test_publication_rejects_nonfinite_or_malformed_frequency(self):
        """! @brief NaN 비교가 완료 게시의 주파수 축 검사를 우회하지 못한다."""
        solved = self.completed()
        state = self.service.journal.read()
        record = state["solver_results"][solved["artifact_id"]]
        job = next(value for value in state["jobs"].values() if value["kind"] == "em_analysis")
        original = json.loads(self.service.journal.read_artifact(record["normalized"]))
        for malformed in (float("nan"), float("inf"), "9500000000", None, True):
            with self.subTest(value=malformed):
                candidate = deepcopy(original)
                candidate["samples"][0]["frequency_hz"] = malformed
                with self.assertRaises(ProjectError) as error:
                    self.service.solver._check_result(job, candidate, record["files"])
                self.assertEqual(error.exception.code, "E_HASH")
        candidate = deepcopy(original)
        candidate["samples"][0] = None
        with self.assertRaises(ProjectError):
            self.service.solver._check_result(job, candidate, record["files"])


if __name__ == "__main__":
    unittest.main()
