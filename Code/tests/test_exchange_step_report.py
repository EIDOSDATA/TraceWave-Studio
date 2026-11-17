"""! @brief STEP 출력 조회가 봉인된 바디별 검수 수치와 당시 객체 이름을 함께 제공하는지 확인한다."""
from copy import deepcopy
import json
import os
import sys
import unittest

from rfad.application.exchange_service import read
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
import test_cad_verification as fixtures


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_CAD_PYTHON"),
                     "RFAD_CAD_PYTHON으로 실제 별도 CAD reader를 지정합니다.")
class ExchangeStepReportTests(unittest.TestCase):
    """! @brief 조회 전용 표시 필드가 원래 검수 바이트와 현재 원본을 변경하지 않는다."""

    def test_full_body_reports_named_and_runtime_free_with_hash_guard(self):
        """! @brief 생성/재검수 body 수치를 모두 읽고 이름을 붙이되 안정 ID와 원문을 보존한다."""
        f = fixtures.StepVerificationProcessTests("test_fresh_reader_replay_reopen_and_original_unknowns")
        f.setUp()
        self.addCleanup(f.tearDown)
        task = f.admit()
        self.assertTrue(f.service.cad.run_next())
        state = f.service.journal.read()
        expected = []
        for job_id in (f.original_task["job_id"], task["job_id"]):
            params = {"contract_version": "rfad.api/2.0", "context": {"project_id": f.document["project_id"]},
                      "input": {"job_id": job_id}}
            viewed = read(f.service, "export.get", params)
            report = viewed["report"]
            validation = report.get("verification", report)
            self.assertTrue(validation["bodies"])
            self.assertFalse(validation["kernel_independent"])
            role = "verification" if job_id == task["job_id"] else "validation"
            reference = next(item for item in viewed["result"]["artifacts"] if item["role"] == role)
            raw = f.service.journal.read_artifact(reference)
            plain = deepcopy(report)
            for body in plain.get("verification", plain)["bodies"]:
                self.assertTrue(body.pop("label"))
                self.assertTrue(body.pop("source_entity_ids"))
                self.assertIn("volume_error_mm3", body)
                self.assertIn("through_hole_count", body)
                self.assertIn("name", body)
            self.assertEqual(plain, json.loads(raw))
            expected.append((params, viewed, reference, raw))
        self.assertEqual(f.service.journal.read(), state)
        f.assert_original()
        f.service.close()
        f.service = ProjectService(f.workspace, auto_run=False)
        for params, viewed, reference, raw in expected:
            self.assertEqual(read(f.service, "export.get", params), viewed)
            self.assertEqual(f.service.journal.read_artifact(reference), raw)
        params, _, reference, raw = expected[-1]
        (f.workspace / reference["uri"]).write_bytes(raw + b" ")
        with self.assertRaises(ProjectError) as raised:
            read(f.service, "export.get", params)
        self.assertEqual(raised.exception.code, "E_HASH")


if __name__ == "__main__":
    unittest.main()
