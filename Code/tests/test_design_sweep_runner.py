"""! @brief 원본/예산/실제 종료를 보존하는 스윕 실행과 compact 해석 작업을 검증한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.design_sweep_store import load_candidate, load_definition
from rfad.application.projects import ProjectService
from rfad.application.solver_capture import hydrate_job
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity
from test_targets import target_input
import test_design_sweep_service as service_fixtures
import test_solver_jobs as solver_fixtures


class CompactSolverTests(unittest.TestCase):
    """! @brief 가짜 전송과 실제 봉인 저장소로 실행 계획 참조의 호환성을 검증한다."""

    def setUp(self):
        """! @brief 이미 검증된 전송 fixture를 새 작업마다 독립 생성한다."""
        self.fixture = solver_fixtures.SolverJobTests("runTest")
        self.fixture.setUp()
        self.service = self.fixture.service

    def tearDown(self):
        """! @brief 시험이 만든 전송 gate와 저장소를 회수한다."""
        self.fixture.tearDown()

    def prepare(self):
        """! @brief 공개 계획 봉인 뒤 내부 스윕과 같은 compact 접수를 사용한다."""
        plan = self.fixture.complete("solver.plan", self.fixture.plan_input())["analysis_plan"]
        data = {"analysis_plan": {key: plan[key] for key in ("plan_id", "content_hash")},
                "budget": {"timeout_seconds": 120}}
        task = self.service.journal.transaction(lambda state: self.service.solver.admit(
            state, "solver.prepare", {"project_id": self.fixture.project}, data, compact=True))
        return task, plan

    def test_compact_prepare_solve_and_legacy_plan_share_one_slot(self):
        """! @brief 작은 journal 참조를 복원해 기존 준비/계산 파일 계약까지 실제 통과한다."""
        task, _ = self.prepare()
        job = self.fixture.job(task)
        self.assertNotIn("analysis_plan", job["solver"])
        self.assertNotIn("runtime", job["solver"])
        self.assertLess(len(canonical_bytes(job["solver"])), 2048)
        self.assertTrue(self.service.solver.run_next())
        status = self.fixture.status(task)
        self.assertEqual(status["state"], "completed", status)
        prepared = status["events"][-1]["operation_result"]["prepared_plan"]
        data = self.fixture.analysis_input(prepared)
        solve = self.service.journal.transaction(lambda state: self.service.solver.admit(
            state, "job.submit", {"project_id": self.fixture.project}, data, compact=True))
        self.service.solver.run_next()
        status = self.fixture.status(solve)
        self.assertEqual(status["state"], "completed", status)
        self.assertEqual(len(self.fixture.transport.calls), 2)
        self.assertNotIn("prepared_plan", self.fixture.job(solve)["solver"])
        self.assertFalse(self.fixture.job(solve)["solver"]["resource_reserved"])

    def test_tampered_capture_or_plan_never_starts_transport(self):
        """! @brief 해시가 바뀐 불변 입력은 guest 시작 전에 차단하고 예약을 해제한다."""
        task, _ = self.prepare()
        job = self.fixture.job(task)
        path = self.service.journal._safe_path(job["solver"]["capture"]["uri"])
        path.write_bytes(path.read_bytes() + b" ")
        self.service.solver.run_next()
        status = self.fixture.status(task)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["events"][-1]["error"]["code"], "E_HASH")
        self.assertEqual(self.fixture.transport.calls, [])
        self.assertFalse(self.fixture.job(task)["solver"]["resource_reserved"])

    def test_unknown_guest_reservation_survives_capture_damage_until_reconcile(self):
        """! @brief 입력이 손상돼도 guest 소유 nonce로 종료만 확인하며 계산을 재개하지 않는다."""
        task, _ = self.prepare()
        self.fixture.transport.mode = "unknown"
        self.service.solver.run_next()
        job = self.fixture.job(task)
        self.assertEqual(job["state"], "interrupted")
        self.assertTrue(job["solver"]["resource_reserved"])
        self.service.journal._safe_path(job["solver"]["capture"]["uri"]).write_bytes(b"{}")
        with self.assertRaises(ProjectError):
            hydrate_job(self.service.journal, job)
        self.fixture.transport.reconcile_confirmed = False
        with patch("rfad.application.solver_jobs.time.monotonic", side_effect=[0, 21]):
            result = self.service.solver.reconcile(job["job_id"])
        self.assertFalse(result["termination_confirmed"])
        self.assertTrue(self.fixture.job(task)["solver"]["resource_reserved"])
        self.fixture.transport.reconcile_confirmed = True
        self.assertTrue(self.service.solver.reconcile(job["job_id"])["termination_confirmed"])
        self.assertEqual(len(self.fixture.transport.calls), 1)


class DesignSweepRunnerTests(unittest.TestCase):
    """! @brief native runtime 없이 실제 외부 RLC 후보와 실패/취소/재개 상태를 검사한다."""

    def setUp(self):
        """! @brief 0/50 ohm 및 단위 동치 후보와 원문 출처를 준비한다."""
        self.fixture = service_fixtures.DesignSweepServiceTests("runTest")
        self.fixture.setUp()
        self.service = self.fixture.service

    def tearDown(self):
        """! @brief 실제 fixture가 가진 최종 서비스를 닫는다."""
        self.fixture.tearDown()

    def command(self, method, identity):
        """! @brief 공개 영수증 경로로 시작/취소/재개한다."""
        return self.service.mutate("sweep." + method, self.fixture.request({"study_id": identity}, mutation=True))

    def study(self, identity):
        """! @brief 시험만 내부 누적 바이트와 작은 참조를 읽는다."""
        return self.service.journal.read()["sweeps"][identity]

    def run_all(self, identity):
        """! @brief 무한 반복을 허용하지 않고 실제 조정기 단계를 진행한다."""
        for _ in range(24):
            if self.study(identity)["state"] not in {"running", "resuming", "cancel_requested"}:
                break
            self.service.studies.run_next()
        return self.study(identity)

    def test_target_ranking_is_read_only_and_reopens_actual_circuit_candidates(self):
        """! @brief 실제 계산한 대역 평가, 실패 후보, 해시와 재열기 순위를 비교한다."""
        document = self.fixture.document()
        port = document["ports"][0]["id"]
        targets = []
        for limit in (-10, -7):
            value = target_input(start=1, end=2)
            value["name"] = f"2 GHz까지 정합 {limit} dB"
            value["band"]["sampling"]["count"] = 3
            value["port_id"] = port
            value["reference_impedance"] = Quantity.from_value(50, "ohm").to_dict()
            value["reference_plane"] = "입력 기준면"
            value["criteria"] = value["criteria"][:1]
            value["criteria"][0]["limit"]["value"] = float(limit)
            self.service.mutate("project.apply_command", self.fixture.request({
                "expected_revision": self.fixture.document()["revision_id"], "command_id": str(uuid4()),
                "type": "target.set", "payload": {"target": value}}, mutation=True))
            targets.append(value["id"])
        self.fixture.spec["target_ids"] = targets
        self.fixture.spec["target_contexts"] = [
            {"target_id": identity, "context": {"port_id": port, "target_port_id": port,
             "reference_plane": "입력 기준면", "frequency_policy": "exact_only"}} for identity in targets]
        values = self.fixture.spec["variables"][0]["values"]
        values.insert(1, {**values[1], "text": "10"})
        identity = self.fixture.create()
        self.command("start", identity)
        self.assertEqual(self.run_all(identity)["state"], "completed")
        before = self.service.journal.read()
        ranking = self.fixture.read("sweep.rank", study_id=identity)
        weights = {targets[0]: 3}
        weighted = self.fixture.read("sweep.rank", study_id=identity, weights=weights)
        self.assertEqual(weighted["excluded"], ranking["excluded"])
        self.assertEqual([(row["ordinal"], row["front"], row["weighted_score"]) for row in weighted["items"]],
                         [(1, 1, 1), (2, 2, .25), (3, 2, .25)])
        self.assertEqual([row["normalized_weight"] for row in weighted["weights"]], [.75, .25])
        relaxed = self.fixture.read("sweep.rank", study_id=identity, weights={targets[0]: 0})
        self.assertEqual([row["weighted_score"] for row in relaxed["items"]], [1, 1, 1])
        for invalid in ({targets[0]: True}, {targets[0]: -1}, {targets[0]: 0, targets[1]: 0}, {str(uuid4()): 1}):
            with self.assertRaises(ProjectError):
                self.fixture.read("sweep.rank", study_id=identity, weights=invalid)
        self.assertEqual(weighted["ranking_sha256"], canonical_hash(
            {key: value for key, value in weighted.items() if key != "ranking_sha256"}))
        recipe = self.fixture.read("sweep.recipe", study_id=identity)
        self.assertEqual(self.service.journal.read(), before)
        definition = load_definition(self.service, before["sweeps"][identity])
        self.assertEqual(recipe["original_specification"], self.fixture.spec)
        self.assertEqual(recipe["specification"], definition["specification"])
        self.assertEqual(recipe["snapshot"]["content_hash"], definition["snapshot"]["content_hash"])
        self.assertEqual(recipe["recipe_sha256"], canonical_hash({key: value for key, value in recipe.items() if key != "recipe_sha256"}))
        self.assertEqual(ranking["excluded"], {"not_completed": 1})
        self.assertEqual([(row["ordinal"], row["front"], row["target_scores"]) for row in ranking["items"]],
                         [(1, 1, [1, 1]), (2, 2, [0, 1]), (3, 2, [0, 1])])
        self.assertTrue(self.fixture.read("sweep.get", study_id=identity)["allowed_actions"]["rank"])
        self.assertFalse(ranking["continuous_band_verified"])
        self.service.close()
        self.service = self.fixture.service = ProjectService(self.fixture.workspace, auto_run=False)
        self.assertEqual(self.fixture.read("sweep.rank", study_id=identity), ranking)
        self.assertEqual(self.fixture.read("sweep.rank", study_id=identity, weights=weights), weighted)
        self.assertEqual(self.fixture.read("sweep.recipe", study_id=identity), recipe)
        with self.assertRaisesRegex(ProjectError, "공차 모서리"):
            self.fixture.read("sweep.rank", study_id=identity, tolerance=True)

        values[:] = [{**values[1], "text": str(value)} for value in (10, 20, 50)]
        tolerance_id = self.fixture.create()
        unavailable = self.fixture.read("sweep.rank", study_id=tolerance_id, tolerance=True)["tolerance_analysis"]
        self.assertFalse(unavailable["nominal_available"])
        self.assertEqual(unavailable["missing_corner_ordinals"], [0, 2])
        self.assertTrue(all(row["complete_corner_score"] is None for row in unavailable["targets"]))
        self.command("start", tolerance_id)
        self.assertEqual(self.run_all(tolerance_id)["state"], "completed")
        before = self.service.journal.read()
        report = self.fixture.read("sweep.rank", study_id=tolerance_id, tolerance=True)["tolerance_analysis"]
        self.assertEqual((report["nominal_ordinal"], report["corner_ordinals"]), (1, [0, 2]))
        self.assertTrue(report["nominal_available"] and report["complete_corners"])
        self.assertEqual(report["missing_corner_ordinals"], [])
        strict, relaxed = report["targets"]
        self.assertEqual((strict["nominal_score"], strict["complete_corner_score"], strict["observed_min_ordinals"]), (1, 0, [2]))
        self.assertEqual((relaxed["nominal_score"], relaxed["complete_corner_score"]), (1, 1))
        self.assertEqual(self.service.journal.read(), before)

    def test_circuit_lazy_failure_duplicate_and_results_keep_originals(self):
        """! @brief 0 ohm 실패와 50 ohm의 독립 반사값 11/29, 동치 재사용을 구분한다."""
        identity = self.fixture.create()
        self.command("start", identity)
        self.assertEqual(self.study(identity)["records"], {})
        context = self.service.host_calculation_context
        with patch.object(context, "calculate", wraps=context.calculate) as calculate:
            study = self.run_all(identity)
        self.assertEqual(study["state"], "completed", study)
        self.assertEqual(study["counts"], {"total": 3, "completed": 2, "failed": 1, "pending": 0, "running": 0, "skipped": 0})
        self.assertEqual(sum(call.args[0] == "network.circuit" for call in calculate.call_args_list), 1)
        self.assertEqual(study["usage"]["native_solves"], 0)
        self.assertEqual(load_candidate(self.service, study, 0)["outcome"], "invalid_input")
        self.assertIsNone(self.service.solver.runtime)
        duplicate = load_candidate(self.service, study, 2)
        self.assertEqual(duplicate["cached_from_ordinal"], 1)
        result = self.fixture.read("sweep.result", study_id=identity, index=1, offset=0, limit=201, row=0, column=0)
        self.assertAlmostEqual(result["page"]["samples"][0]["real"], 11 / 29)
        self.assertIsNone(result["descriptor"]["conditions"]["manufacturing"])
        self.assertFalse(result["candidate"]["physics_validated"])
        self.assertEqual(self.fixture.document(), self.fixture.original)
        self.assertLess(len(canonical_bytes(study)), 8192)

    def test_cancel_during_circuit_keeps_result_and_resume_does_not_recompute(self):
        """! @brief 완료 파일 봉인 전 취소가 들어와도 결과를 보존하고 새 계산을 피한다."""
        self.fixture.spec["variables"][0]["values"] = self.fixture.spec["variables"][0]["values"][1:2]
        identity = self.fixture.create()
        self.command("start", identity)
        context = self.service.host_calculation_context
        original_calculate = context.calculate
        def cancel_after_calculation(operation, inputs):
            """! @brief 느린 계산 직후 들어온 실제 취소 요청을 재현한다."""
            result = original_calculate(operation, inputs)
            if operation == "network.circuit":
                self.command("cancel", identity)
            return result
        with patch.object(context, "calculate", side_effect=cancel_after_calculation) as calculate:
            self.service.studies.run_next()
            self.service.studies.run_next()
            self.assertEqual(sum(call.args[0] == "network.circuit" for call in calculate.call_args_list), 1)
        study = self.study(identity)
        self.assertEqual(study["state"], "cancelled", study)
        candidate = load_candidate(self.service, study, 0)
        self.assertEqual(candidate["phase"], "results_ready")
        self.assertIn("dataset", candidate["results"])
        original_diagnostics = json.loads(self.service.journal.read_artifact(candidate["results"]["diagnostics"]))["items"]
        self.command("resume", identity)
        def retained_only(operation, inputs):
            """! @brief 원래 회로 worker 재실행은 막고 보존 자료의 목표 평가는 실제 worker로 한다."""
            if operation == "network.circuit":
                raise AssertionError("재계산 금지")
            return original_calculate(operation, inputs)
        with patch.object(context, "calculate", side_effect=retained_only):
            self.assertEqual(self.run_all(identity)["state"], "completed")
        retained = load_candidate(self.service, self.study(identity), 0)
        current_diagnostics = json.loads(self.service.journal.read_artifact(retained["results"]["diagnostics"]))["items"]
        self.assertEqual(current_diagnostics[:-1], original_diagnostics)
        self.assertEqual(current_diagnostics[-1]["code"], "I_RETAINED")

    def test_ram_and_wall_budget_block_without_native_and_keep_source(self):
        """! @brief 초기 RAM 예약과 누적 시간이 부족하면 결과를 꾸미거나 예산을 초기화하지 않는다."""
        self.fixture.spec["variables"][0]["values"] = self.fixture.spec["variables"][0]["values"][1:2]
        self.fixture.spec["budget"]["ram_bytes"] = 1
        identity = self.fixture.create()
        self.command("start", identity)
        self.service.studies.run_next()
        self.assertEqual(self.study(identity)["state"], "blocked")
        self.assertIn("RAM", self.study(identity)["message"])
        self.assertEqual(self.fixture.document(), self.fixture.original)

    def test_last_calculation_over_wall_budget_preserves_result_but_blocks_completion(self):
        """! @brief 마지막 후보라도 계산 중 초과한 누적 시간을 정상 완료로 숨기지 않는다."""
        self.fixture.spec["variables"][0]["values"] = self.fixture.spec["variables"][0]["values"][1:2]
        self.fixture.spec["budget"]["wall_seconds"] = 1
        identity = self.fixture.create()
        self.command("start", identity)
        context = self.service.host_calculation_context
        original_calculate = context.calculate
        def elapsed_calculation(operation, inputs):
            """! @brief 실제 계산 반환 직전 서비스 시계의 경과를 재현한다."""
            result = original_calculate(operation, inputs)
            if operation == "network.circuit":
                self.fixture.now += 2
            return result
        with patch.object(context, "calculate", side_effect=elapsed_calculation):
            self.service.studies.run_next()
        study = self.study(identity)
        self.assertEqual(study["state"], "blocked")
        self.assertEqual(study["usage"]["wall_seconds"], 2)
        self.assertEqual(study["counts"]["completed"], 1)
        self.assertIn("dataset", load_candidate(self.service, study, 0)["results"])
        with self.assertRaises(ProjectError):
            self.command("resume", identity)

    def test_restart_and_tampered_retained_result_forbid_automatic_replacement(self):
        """! @brief 완료 후보가 있는 중단 연구는 원본 검증 후에만 재개한다."""
        identity = self.fixture.create()
        self.command("start", identity)
        self.service.studies.run_next()
        self.service.studies.run_next()
        self.command("cancel", identity)
        self.service.studies.run_next()
        old = self.study(identity)
        artifact = load_candidate(self.service, old, 1)["results"]["dataset"]
        self.service.close()
        self.fixture.service = self.service = ProjectService(self.fixture.workspace, auto_run=False)
        self.assertFalse(self.service.studies.run_next())
        self.service.journal._safe_path(artifact["uri"]).write_bytes(b"{}")
        with self.assertRaises(ProjectError) as raised:
            self.command("resume", identity)
        self.assertEqual(raised.exception.code, "E_HASH")
        self.assertEqual(self.study(identity)["records"], old["records"])


class NativeSweepRunnerTests(unittest.TestCase):
    """! @brief 실제 PCB 계획/compact 접수와 대역 종료 상태로 자원/재개 경계를 검사한다."""

    def setUp(self):
        """! @brief 실제 EM 실행 증거와 구분되는 명시 PCB 시험 원본을 등록한다."""
        from test_cad_worker_process import register_fixture
        from test_design_sweep import fixture, definition, axis, typed
        self.fixture = solver_fixtures.SolverJobTests("runTest")
        self.fixture.setUp()
        self.service = self.fixture.service
        document, identities = fixture()
        self.document, _ = register_fixture(self.service, document)
        self.fixture.project = self.document["project_id"]
        self.fixture.revision = self.document["revision_id"]
        self.spec = definition([axis(identities[0], [typed("1")])])

    def tearDown(self):
        """! @brief fake transport와 임시 작업 폴더를 회수한다."""
        self.fixture.tearDown()

    def create_start(self):
        """! @brief 공개 검토/생성/시작 API로 실제 스윕을 접수한다."""
        from rfad.application import design_sweep_service
        request = self.fixture.request({"expected_revision": self.document["revision_id"], "specification": self.spec})
        request.pop("request_key")
        request.pop("request_key_epoch")
        preview = design_sweep_service.read(self.service.host_calculation_context, "sweep.preview", request)
        result = self.service.mutate("sweep.create", self.fixture.request({**request["input"], "review_hash": preview["review_hash"]}))
        identity = result["study_id"]
        self.control("start", identity)
        return identity

    def control(self, action, identity):
        """! @brief 공개 영수증과 스윕 식별자를 그대로 사용한다."""
        return self.service.mutate("sweep." + action, self.fixture.request({"study_id": identity}))

    def study(self, identity):
        """! @brief 내부 전이는 시험에서만 읽는다."""
        return self.service.journal.read()["sweeps"][identity]

    def test_lazy_compact_unknown_resume_preserves_prior_attempt(self):
        """! @brief 종료 미확인 실행은 예약을 유지하고 명시 재개에서만 새 시도를 만든다."""
        identity = self.create_start()
        self.assertEqual(self.study(identity)["records"], {})
        self.service.studies.run_next()
        candidate = load_candidate(self.service, self.study(identity), 0)
        self.assertEqual(candidate["phase"], "prepare")
        self.assertEqual(candidate["attempts"], [])
        self.service.studies.run_next()
        study = self.study(identity)
        job_id = study["current_job_id"]
        self.assertIn("capture", self.service.journal.read()["jobs"][job_id]["solver"])
        self.fixture.transport.mode = "unknown"
        self.service.solver.run_next()
        self.service.studies.run_next()
        self.assertEqual(self.study(identity)["state"], "interrupted")
        self.control("resume", identity)
        self.service.studies.run_next()
        self.assertIsNone(self.study(identity)["current_job_id"])
        self.service.studies.run_next()
        final = self.study(identity)
        self.assertNotEqual(final["current_job_id"], job_id)
        candidate = load_candidate(self.service, final, 0)
        self.assertEqual(len(candidate["attempts"]), 2)
        self.assertEqual(candidate["attempts"][0]["job_id"], job_id)
        self.assertGreater(final["usage"]["disk_bytes"], study["usage"]["disk_bytes"])
        self.assertEqual(final["usage"]["native_solves"], 0)
        actual = self.service._load(self.service.journal.read()["projects"][self.document["project_id"]])
        self.assertEqual(actual, self.document)

    def test_disk_reservation_stops_before_any_native_job(self):
        """! @brief 원본 저장이 가능해도 staging/출력 예약이 부족하면 실행을 접수하지 않는다."""
        self.spec["budget"]["disk_bytes"] = 8 * 1024**2
        identity = self.create_start()
        self.service.studies.run_next()
        self.service.studies.run_next()
        study = self.study(identity)
        self.assertEqual(study["state"], "blocked", study)
        self.assertIsNone(study["current_job_id"])
        self.assertEqual(self.fixture.transport.calls, [])
        self.assertIn("디스크", study["message"])

    def test_busy_shared_slot_waits_without_commits_or_candidate_materialization(self):
        """! @brief 다른 명시 해석 작업을 침범하거나 대기 중 반복 journal 쓰기를 하지 않는다."""
        identity = self.create_start()
        foreign = str(uuid4())
        self.service.journal.transaction(lambda state: state["jobs"].update({foreign: {
            "job_id": foreign, "state": "running", "solver": {"resource_reserved": True}}}))
        before = self.service.journal.read()
        for _ in range(3):
            self.assertFalse(self.service.studies.run_next())
        self.assertEqual(self.service.journal.read(), before)
        self.assertEqual(self.study(identity)["records"], {})

    def test_solve_attempt_budget_survives_failure_and_explicit_resume(self):
        """! @brief solve 접수 후 실패해도 횟수를 환급하거나 재개에서 초기화하지 않는다."""
        from rfad.application.canonical import canonical_hash
        from rfad.application.solver import make_prepared_plan
        self.spec["budget"]["max_native_solves"] = 1
        identity = self.create_start()
        self.service.studies.run_next()
        self.service.studies.run_next()
        study = self.study(identity)
        candidate = load_candidate(self.service, study, 0)
        plan_ref = candidate["analysis_plan"]
        preparation = {"analysis_plan_id": plan_ref["plan_id"], "analysis_plan_hash": plan_ref["content_hash"]}
        preparation_ref = self.service.journal.put_immutable("test-preparation.json", canonical_bytes(preparation))
        prepared = make_prepared_plan(plan_ref, candidate["snapshot"], preparation_ref, self.fixture.runtime.identity)
        artifact = self.service.journal.put_immutable("test-prepared-plan.json", canonical_bytes(prepared))
        reference = {"prepared_plan_id": prepared["prepared_plan_id"], "content_hash": canonical_hash(prepared), "artifact": artifact}
        def finish_preparation(state):
            """! @brief 이 시험은 native 물리값 대신 접수 이후의 상태 전이만 대역한다."""
            state["prepared_plans"][prepared["prepared_plan_id"]] = {"project_id": self.document["project_id"],
                "analysis_plan_id": plan_ref["plan_id"], "reference": reference,
                "preparation_artifact": preparation_ref, "files": []}
            job = state["jobs"][study["current_job_id"]]
            job["solver"]["resource_reserved"] = False
            self.service._event(job, "preparing")
            self.service._event(job, "completed", operation_result={"prepared_plan": reference})
        self.service.journal.transaction(finish_preparation)
        self.service.studies.run_next()
        self.service.studies.run_next()
        self.assertEqual(self.study(identity)["usage"]["native_solves"], 1)
        self.fixture.transport.mode = "not_started"
        self.service.solver.run_next()
        self.service.studies.run_next()
        self.assertEqual(self.study(identity)["state"], "failed")
        self.control("resume", identity)
        self.service.studies.run_next()
        self.service.studies.run_next()
        final = self.study(identity)
        self.assertEqual(final["state"], "blocked", final)
        self.assertEqual(final["usage"]["native_solves"], 1)
        self.assertIsNone(final["current_job_id"])

    def test_structured_nonconvergence_survives_worker_and_sweep(self):
        """! @brief worker의 명시 미수렴 details만 outcome에 연결하고 문장을 추정하지 않는다."""
        from rfad.application.pcb_results import check_termination
        identity = self.create_start()
        self.service.studies.run_next()
        self.service.studies.run_next()
        def nonconverged(stage, **arguments):
            """! @brief 봉투 계약만 대역하며 실제 FDTD 미수렴 시험이라고 주장하지 않는다."""
            request = json.loads((stage / "request.json").read_bytes())
            try:
                check_termination("max. number of timesteps was reached", 1000, {"max_timesteps": 1000})
            except ProjectError as error:
                diagnostic = error.diagnostic()
            payload = {"schema": "rfad.openems-worker-result/0.1", "phase": request["phase"],
                "run_id": request["run_id"], "nonce": request["nonce"],
                "analysis_plan_id": request["analysis_plan"]["plan_id"], "files": [], "error": diagnostic}
            destination = stage / "output/result.json"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(canonical_bytes(payload))
            return {"state": "failed", "termination_confirmed": True, "outcome_unknown": False}
        with patch.object(self.fixture.transport, "execute", side_effect=nonconverged):
            self.service.solver.run_next()
        self.service.studies.run_next()
        study = self.study(identity)
        candidate = load_candidate(self.service, study, 0)
        self.assertEqual(candidate["outcome"], "nonconverged")
        self.assertEqual(candidate["convergence_state"], "not_converged")
        self.assertEqual(candidate["diagnostics"][-1]["details"]["criterion"], "native_timestep_limit")
        self.assertFalse(self.service.journal.read()["jobs"][study["current_job_id"]]["solver"]["resource_reserved"])


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_TEST_WSL") == "1",
                     "실제 단일 후보 스윕은 Windows 고정 WSL과 RFAD_TEST_WSL=1이 필요합니다.")
class ActualNativeSweepTests(unittest.TestCase):
    """! @brief 합성 PCB 한 후보의 실제 준비/해석/봉인/재열기를 물리 검증과 구분한다."""

    def test_one_explicit_pcb_candidate_and_reopen_without_runtime(self):
        """! @brief 원문 미정 보존과 compact 계획의 실제 worker 소비만 검증한다."""
        from rfad.application import design_sweep_service
        from rfad.application.canonical import canonical_hash
        from rfad.application.solver_runtime import SolverRuntime
        from test_cad_worker_process import register_fixture
        from test_design_sweep import definition, axis, typed
        from test_pcb_solver import fixture_document
        root = Path(__file__).resolve().parents[1]
        destination = Path(os.environ.get("RFAD_SWEEP_NATIVE_DIR", str(root / ".local" / ("sweep-native-" + uuid4().hex)))).resolve()
        self.assertTrue(destination.is_relative_to((root / ".local").resolve()))
        self.assertFalse(destination.exists())
        workspace = destination / "workspace"
        original = fixture_document()
        with ProjectService(workspace, auto_run=False) as initial:
            original, _ = register_fixture(initial, original)
        runtime = SolverRuntime()
        context = {"project_id": original["project_id"]}
        spec = definition([axis("grid_mm", [typed("0.5")], "solver_setting")], kind="numerical_study")
        spec["budget"].update(max_candidates=1, max_native_solves=1, wall_seconds=600,
                              ram_bytes=2 * 1024**3, disk_bytes=1024**3)
        def request(service, data, mutation=False):
            """! @brief 실제 API와 동일한 요청/영수증 키를 구성한다."""
            value = {"contract_version": "rfad.api/2.0", "context": context, "input": data}
            if mutation:
                value.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
            return value
        with ProjectService(workspace, solver_runtime=runtime) as service:
            inputs = {"expected_revision": original["revision_id"], "specification": spec}
            preview = design_sweep_service.read(service.host_calculation_context, "sweep.preview", request(service, inputs))
            created = service.mutate("sweep.create", request(service, {**inputs, "review_hash": preview["review_hash"]}, True))
            identity = created["study_id"]
            service.mutate("sweep.start", request(service, {"study_id": identity}, True))
            deadline = time.monotonic() + 620
            while time.monotonic() < deadline:
                study = service.journal.read()["sweeps"][identity]
                if study["state"] == "completed":
                    break
                self.assertNotIn(study["state"], {"failed", "blocked", "cancelled", "interrupted"}, study)
                time.sleep(0.2)
            else:
                self.fail("실제 단일 후보 연구가 명시 예산 안에 완료되지 않았습니다.")
            candidate = load_candidate(service, study, 0)
            self.assertEqual([item["phase"] for item in candidate["attempts"]], ["prepare", "solve"])
            self.assertEqual(study["usage"]["native_solves"], 1)
            self.assertEqual(candidate["convergence_state"], "solver_end_criterion_only")
            self.assertFalse(candidate["physics_validated"])
            self.assertEqual(service._load(service.journal.read()["projects"][original["project_id"]]), original)
            result = design_sweep_service.read(service.host_calculation_context, "sweep.result", request(service,
                {"study_id": identity, "index": 0, "offset": 0, "limit": 201, "row": 0, "column": 0}))
            self.assertEqual(result["page"]["total"], 31)
            self.assertIsNone(result["descriptor"]["conditions"]["measurement"])
            proof = {"schema": "rfad.verification.design-sweep-native/0.1", "status": "passed",
                "source_profile": "explicit_synthetic_pcb_gap_not_manufacturing_reference", "workspace": str(workspace),
                "runtime_identity": runtime.identity, "study": study, "candidate": candidate,
                "original_project_hash": canonical_hash(original), "result": result, "physics_validated": False}
        with ProjectService(workspace, auto_run=False) as reopened:
            repeated = design_sweep_service.read(reopened.host_calculation_context, "sweep.result", request(reopened,
                {"study_id": identity, "index": 0, "offset": 0, "limit": 201, "row": 0, "column": 0}))
            self.assertEqual(result, repeated)
            self.assertFalse(reopened.studies.run_next())
            proof["reopened_without_runtime"] = True
        (destination / "report.json").write_bytes(canonical_bytes(proof))
