"""! @brief Windows GUI와 같은 공개 요청으로 다중 급전 개정, 실제 여기, 전체 행렬 저장과 재열기를 확인한다."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_multiport_job import PROFILE
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from rfad.application.wsl_process import WslRuntime
from test_cad_worker_process import register_fixture
from test_pcb_multiport_extended import fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from verify_openems_worker import call


class MultiportWorkspaceContract(unittest.TestCase):
    def test_snapshot_reconstruction_and_all_terminal_sources(self):
        """! @brief 모든 단자 원본을 확인하고 다른 여기 순서를 주입한 계획을 거절한다."""
        from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
        from rfad.application.solver_evidence import _recorded_objects
        from rfad.domain.errors import ProjectError
        from test_pcb_solver import runtime_identity, snapshot_for

        doc, settings = fixture(4)
        plan = build_pcb_plan(doc, snapshot_for(doc), runtime_identity(), settings, multiport=True)
        validate_pcb_plan(plan)
        self.assertEqual(plan["analysis_profile"], PROFILE)
        self.assertEqual(plan["resource_estimate"]["max_wall_time_seconds"], 1200)
        objects = _recorded_objects(doc, plan["case"])
        for port in doc["ports"]:
            self.assertEqual(objects["port", port["id"]][1], port)
            for side in ("positive_geometry_id", "reference_geometry_id"):
                self.assertEqual(objects["terminal", port[side]][1]["id"], port[side])
        plan["case"]["ports"].reverse()
        with self.assertRaises(ProjectError) as changed:
            validate_pcb_plan(plan)
        self.assertEqual(changed.exception.code, "E_HASH")


@unittest.skipUnless(os.name == "nt" and os.environ.get("RFAD_MULTIPORT_WINDOWS") == "1",
                     "RFAD_MULTIPORT_WINDOWS=1과 검증된 Windows WSL 설치가 필요합니다.")
class WorkspaceMultiportTests(unittest.TestCase):
    """! @brief 등록한 설계의 프로젝트, 개정과 실수 저항을 유지하여 감독 worker 계산을 검수한다."""

    def test_four_port_run_reprocess_register_reopen(self):
        """! @brief 4개 독립 여기와 원시 후처리, S43의 재열기를 검수한다."""
        directory = os.environ.get("RFAD_MULTIPORT_WORKSPACE")
        parent = Path(directory) if directory else Path(tempfile.mkdtemp(prefix="rfad-multiport-"))
        parent.mkdir(exist_ok=True, parents=True)
        workspace = parent / ("workspace-" + uuid4().hex)
        source, conditions = fixture(4)
        audit = os.environ.get("RFAD_OPENEMS_AUDIT")
        runtime = SolverRuntime(transport=WslRuntime(startup_timeout_seconds=240), audit=Path(audit) if audit else None)
        with ProjectService(workspace, solver_runtime=runtime, auto_run=False) as service:
            source, snapshot = register_fixture(service, source)
            context = {"project_id": source["project_id"]}
            revision = source["revision_id"]
            preview = call(service, "solver.preview", {"expected_revision": revision, "settings": conditions}, context)
            self.assertEqual([port["id"] for port in preview["multiport"]], [port["id"] for port in source["ports"]])

            def stage(method, data):
                """! @brief GUI 명령과 동일한 접수 및 공개 상태를 보며 한 번의 소유 작업만 실행한다."""
                job = call(service, method, data, context, mutation=True)
                self.assertTrue(service.solver.run_next())
                final = call(service, "job.status", {"job_id": job["job_id"]})
                last = final["events"][-1]
                self.assertEqual(final["state"], "completed", last)
                return last["operation_result"]

            plan = stage("solver.plan", {"analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE,
                         "snapshot": {k:snapshot[k] for k in ("snapshot_id", "content_hash")}, "settings": conditions})
            budget = {"timeout_seconds": 1200}
            analysis = plan["analysis_plan"]
            prep = stage("solver.prepare", {"analysis_plan": {k:analysis[k] for k in ("plan_id", "content_hash")}, "budget": budget})
            prepared = prep["prepared_plan"]
            task = {"kind": "em_analysis", "execution_mode": "solve_and_postprocess",
                    "prepared_plan": {k:prepared[k] for k in ("prepared_plan_id", "content_hash")}}
            result = stage("job.submit", {"task_plan": task, "budget": budget})
            original = json.loads(service.journal.read_artifact(result["normalized_result"]))
            self.assertEqual(original["snapshot"]["content_hash"], canonical_hash(source))
            self.assertEqual(len(original["raw_manifest"]["runs"]), 4)
            task.update(execution_mode="postprocess_only", raw_result_id=result["artifact_id"])
            restored = stage("job.submit", {"task_plan": task, "budget": budget})
            self.assertEqual(json.loads(service.journal.read_artifact(restored["normalized_result"]))["network"], original["network"])
            args = {"expected_revision": revision, "operation": "solver",
                    "parameters": {"name": "원형 기판 4포트", "artifact_id": result["artifact_id"]}}
            review = call(service, "network.preview", args, context)
            self.assertTrue(review["can_apply"], review["issues"])
            registered = call(service, "network.apply", {**args, "command_id":str(uuid4()), "review_hash":review["review_hash"]}, context, mutation=True)
            query = {"expected_revision": registered["new_revision"], "dataset_id": registered["record_id"],
                     "row": 3, "column": 2, "offset": 0, "limit": 31}
        with ProjectService(workspace, auto_run=False) as reopened:
            read = call(reopened, "network.get", query, context)
            self.assertEqual(read["descriptor"]["source_snapshot"], snapshot)
            self.assertEqual(len(read["page"]["samples"]), 31)
            for row, matrix in zip(read["page"]["samples"], original["network"]["values_ri"]):
                self.assertEqual([row["real"], row["imag"]], matrix[3][2])
            print(json.dumps({"workspace": str(workspace), "artifact":result["artifact_id"], "reprocessed":restored["artifact_id"],
                              "snapshot": snapshot["content_hash"], "dataset": registered["record_id"], "S43":original["network"]["values_ri"][0][3][2]}))
