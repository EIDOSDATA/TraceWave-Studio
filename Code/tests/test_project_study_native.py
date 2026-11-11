"""! @brief 실제 WSL 작업 도중 서비스를 종료하고 고정 연구를 명시적으로 재개한다."""

import json
import os
from pathlib import Path
import sys
import time
import unittest
from uuid import uuid4

from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from test_cad_worker_process import register_fixture
from test_pcb_solver import fixture_document
from test_project_studies import specification

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from verify_openems_worker import call


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_TEST_WSL") == "1", "실제 연구 중단/재개는 RFAD_TEST_WSL=1이 필요합니다.")
class ProjectStudyNativeRecoveryTests(unittest.TestCase):
    """! @brief 합성 gap fixture의 실행 수명을 검증하며 제조품 정확도를 주장하지 않는다."""

    def test_restart_during_native_execution_preserves_preparation(self):
        """! @brief 실제 실행 종료/이전 시도를 보존하고 완료 준비를 재사용한다."""
        folder = Path(os.environ.get("RFAD_PROJECT_STUDY_NATIVE_DIR", str(ROOT / ".local" / ("study-recovery-" + uuid4().hex)))).resolve()
        self.assertTrue(folder.is_relative_to((ROOT / ".local").resolve()))
        self.assertFalse(folder.exists())
        workspace = folder / "workspace"
        with ProjectService(workspace, auto_run=False) as service:
            document, _ = register_fixture(service, fixture_document())
        runtime = SolverRuntime()
        context = {"project_id": document["project_id"]}
        spec = specification()
        spec["settings"]["radiation"] = {"frequency_hz": [10e9], "theta_step_deg": 15, "phi_step_deg": 15, "box_clearance_mm": 6}
        spec["settings"]["power_balance"] = {"max_relative_residual": 0.03}
        with ProjectService(workspace, solver_runtime=runtime) as service:
            created = call(service, "study.create", {"expected_revision": document["revision_id"], "specification": spec}, context, mutation=True)
            identity = created["study_id"]
            call(service, "study.start", {"study_id": identity}, context, mutation=True)
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                state = service.journal.read()
                study = state["studies"][identity]
                job = state["jobs"].get(study["current_job_id"])
                if job is not None and study["cases"][0]["phase"] == "solve" and job["state"] == "running":
                    break
                self.assertNotIn(study["state"], {"blocked", "failed", "completed"}, study)
                time.sleep(0.1)
            else:
                self.fail("실제 native 작업 시작을 관측하지 못했습니다.")
            original_job = job["job_id"]
            original_prepared = study["cases"][0]["prepared_plan"]
        with ProjectService(workspace, solver_runtime=runtime) as reopened:
            view = call(reopened, "study.get", {"study_id": identity}, context)
            self.assertEqual(view["state"], "interrupted")
            count_before = len(reopened.journal.read()["jobs"])
            time.sleep(0.4)
            self.assertEqual(len(reopened.journal.read()["jobs"]), count_before)
            call(reopened, "study.resume", {"study_id": identity}, context, mutation=True)
            deadline = time.monotonic() + 360
            while time.monotonic() < deadline:
                view = call(reopened, "study.get", {"study_id": identity}, context)
                if view["state"] == "completed":
                    break
                self.assertNotIn(view["state"], {"blocked", "failed", "cancelled"}, view)
                time.sleep(0.2)
            else:
                self.fail("명시적 연구 재개가 완료되지 않았습니다.")
            state = reopened.journal.read()
            study = state["studies"][identity]
            self.assertEqual(study["cases"][0]["prepared_plan"], original_prepared)
            self.assertEqual([item["phase"] for item in study["cases"][0]["attempts"]], ["prepare", "solve", "solve"])
            self.assertEqual(state["jobs"][original_job]["state"], "interrupted")
            self.assertIsNotNone(view["cases"][0]["power_balance"])
            proof = {"schema": "rfad.verification.study-native-recovery/0.1", "status": "passed", "workspace": str(workspace),
                     "original_job_id": original_job, "original_prepared_plan": original_prepared,
                     "attempts": study["cases"][0]["attempts"], "runtime_identity": runtime.identity,
                     "view": view, "no_automatic_restart": True, "prepared_plan_reused": True, "physics_validated": False}
            (folder / "report.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
