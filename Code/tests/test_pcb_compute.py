"""! @brief 확장 손실 연구는 명시적으로 선택하고 과거 계획의 예산/취소 경계를 유지한다."""

from copy import deepcopy
import unittest

from rfad.application.pcb_compute import limits
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan, validate_settings
from rfad.domain.errors import ProjectError
from test_pcb_power import power_plan
import test_solver_jobs as jobs
from test_cad_worker_process import register_fixture


class ComputeProfileTests(unittest.TestCase):
    """! @brief 유한 확장 예산을 실제 계획/공개 접수와 교차 검증한다."""

    def test_opt_in_preserves_physics_and_default_profile(self):
        """! @brief 스레드/예산 외에 원본 재료/기하/격자와 과거 기본값이 달라지지 않는다."""
        old = power_plan()
        settings = deepcopy(old["case"]["settings"])
        settings["compute_profile"] = {"kind": "loss_refinement/0.1", "num_threads": 4}
        new = build_pcb_plan(old["source_semantics"], old["snapshot"], old["runtime_identity"], settings)
        validate_pcb_plan(old)
        validate_pcb_plan(new)
        self.assertEqual(new["source_semantics"], old["source_semantics"])
        self.assertEqual(new["normalization"], old["normalization"])
        self.assertEqual(old["case"]["num_threads"], 2)
        self.assertEqual(old["resource_estimate"]["max_wall_time_seconds"], 300)
        self.assertEqual(new["case"]["num_threads"], 4)
        self.assertEqual(new["resource_estimate"]["max_wall_time_seconds"], 900)
        self.assertEqual(limits(settings)["max_grid_points"], 2400000)
        for key in ("layers", "shapes", "vias", "port", "loss_recording", "radiation_recording"):
            self.assertEqual(new["case"][key], old["case"][key])

    def test_invalid_compute_profiles_are_not_silently_normalized(self):
        """! @brief bool/자동 스레드/무제한/알 수 없는 profile은 접수하지 않는다."""
        settings = power_plan()["case"]["settings"]
        variants = [None, {}, {"kind": "unknown", "num_threads": 4}]
        variants += [{"kind": "loss_refinement/0.1", "num_threads": n} for n in (True, 0, 9, 2.5)]
        for profile in variants:
            with self.subTest(profile=profile), self.assertRaises(ProjectError):
                validate_settings({**settings, "compute_profile": profile})
        settings = {**settings, "compute_profile": {"kind": "loss_refinement/0.1", "num_threads": 4}}
        del settings["power_balance"]
        with self.assertRaises(ProjectError):
            validate_settings(settings)

    def test_extended_budget_is_publicly_admitted_and_cancellable(self):
        """! @brief 900초는 확장 불변 계획에서만 허용하고 대기 취소 뒤 슬롯 예약을 해제한다."""
        fixture = jobs.SolverJobTests()
        fixture.setUp()
        try:
            source = power_plan()
            document, snapshot = register_fixture(fixture.service, source["source_semantics"])
            fixture.project, fixture.revision = document["project_id"], document["revision_id"]
            settings = {**source["case"]["settings"], "compute_profile": {"kind": "loss_refinement/0.1", "num_threads": 4}}
            plan = fixture.complete("solver.plan", {"snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
                                      "analysis_profile": "rfad.openems.pcb-single-port/0.1", "runtime_profile": "openems-wsl-reference/0.1", "settings": settings})["analysis_plan"]
            data = {"analysis_plan": {key: plan[key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 901}}
            with self.assertRaises(ProjectError):
                fixture.service.mutate("solver.prepare", fixture.request(data))
            data["budget"]["timeout_seconds"] = 900
            task = fixture.service.mutate("solver.prepare", fixture.request(data))
            self.assertEqual(fixture.job(task)["input"]["budget"]["timeout_seconds"], 900)
            fixture.service.mutate("job.cancel", fixture.request({"job_id": task["job_id"], "reason": "확장 연구 대기 취소 시험"}, {}))
            self.assertEqual(fixture.status(task)["state"], "cancelled")
            self.assertFalse(fixture.job(task)["solver"]["resource_reserved"])
            self.assertEqual(fixture.transport.calls, [])
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
