"""! @brief 일반 프로젝트 연구의 원본 보존, 원자 접수와 취소/명시적 재개를 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.projects import ProjectService
from rfad.application.project_study_contract import initial_specification
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command, validate_project
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture
from test_pcb_solver import fixture_document, runtime_identity, SETTINGS, quantity
from test_convergence import fixture_result, PROFILE as COMPARISON_PROFILE
from rfad.application.convergence import compare_samples


def specification(levels=None):
    """! @brief 물성은 기존 명시적 합성 fixture를 사용하고 수치 조건만 변경한다."""
    result = initial_specification()
    result["grid_levels_mm"] = [0.5] if levels is None else levels
    result["settings"].update(deepcopy(SETTINGS))
    result["settings"].update(grid_mm=result["grid_levels_mm"][-1], air_padding_mm=30)
    result["settings"]["mesh_policy"]["air_cell_mm"] = 1.5
    return result


class ProjectStudyTests(unittest.TestCase):
    """! @brief 실제 journal/API를 사용하되 단위 시험의 native 단계만 대역한다."""

    def setUp(self):
        """! @brief 독립 workspace와 순수 계약 시험용 runtime을 만든다."""
        self.temporary = TemporaryDirectory()
        self.runtime = SimpleNamespace(identity=runtime_identity(), manifest_bytes=b"{}", source_bytes=b"{}")
        self.service = ProjectService(Path(self.temporary.name), auto_run=False, solver_runtime=self.runtime)
        self.document, _ = register_fixture(self.service, fixture_document())
        self.context = {"project_id": self.document["project_id"]}

    def tearDown(self):
        """! @brief 시험이 소유한 서비스와 임시 경로를 회수한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, data):
        """! @brief 실제 epoch와 새 요청 키로 변경을 접수한다."""
        return {"contract_version": "rfad.api/2.0", "context": self.context, "input": data,
                "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def create(self, spec=None):
        """! @brief 현재 개정에 결합된 연구를 생성한다."""
        return self.service.mutate("study.create", self.request({"expected_revision": self.document["revision_id"],
                                                                 "specification": specification() if spec is None else spec}))

    def control(self, method, identity):
        """! @brief 실행 제어도 공개 변경 경계를 통과한다."""
        return self.service.mutate(method, self.request({"study_id": identity}))

    def fake_admit(self, state, method, context, data):
        """! @brief 물리 결과가 아닌 상태 전이 검사용 native 대역 작업을 기록한다."""
        identity = str(uuid4())
        job = {"job_id": identity, "run_id": str(uuid4()), "kind": "em_prepare" if method == "solver.prepare" else "em_analysis",
               "operation_method": method, "context": context, "input": data,
               "solver": {"resource_reserved": True}, "events": []}
        self.service._event(job, "queued")
        state["jobs"][identity] = job
        return {"job_id": identity, "state": "queued"}

    def test_creation_is_idempotent_and_does_not_modify_revision_or_history(self):
        """! @brief 동일 요청의 응답 유실은 같은 연구/snapshot만 재조회한다."""
        request = self.request({"expected_revision": self.document["revision_id"], "specification": specification()})
        before = deepcopy(self.service.journal.read()["projects"])
        first = self.service.mutate("study.create", request)
        self.assertEqual(first, self.service.mutate("study.create", request))
        state = self.service.journal.read()
        self.assertEqual(state["projects"], before)
        self.assertEqual(len(state["studies"]), 1)
        original = json.loads(self.service.journal.read_artifact(first["snapshot"]["artifact"]))
        self.assertEqual(original, self.document)

    def test_parameter_binding_and_unused_missing_materials_are_preserved(self):
        """! @brief 표현식 입력을 리터럴로 바꾸거나 미소비 물성을 보완하지 않는다."""
        param = str(uuid4())
        changed = self.service.mutate("project.apply_command", self.request({"expected_revision": self.document["revision_id"],
                    "command_id": str(uuid4()), "type": "parameter.set", "payload": {"id": param, "name": "line width", "quantity": quantity(1, "mm")}}))
        self.document = self.service._load(self.service.journal.read()["projects"][self.context["project_id"]])
        shape = deepcopy(self.document["geometry"][0])
        shape["width"] = {"parameter_id": param}
        self.service.mutate("project.apply_command", self.request({"expected_revision": changed["new_revision"], "command_id": str(uuid4()),
                            "type": "geometry.set", "payload": {"geometry": shape}}))
        self.document = self.service._load(self.service.journal.read()["projects"][self.context["project_id"]])
        created = self.create()
        state = self.service.journal.read()
        case = state["studies"][created["study_id"]]["cases"][0]
        plan = json.loads(self.service.journal.read_artifact(case["analysis_plan"]["artifact"]))
        self.assertEqual(plan["source_semantics"], self.document)
        self.assertEqual(plan["source_semantics"]["geometry"][0]["width"], {"parameter_id": param})
        self.assertEqual(canonical_hash(self.document), created["snapshot"]["content_hash"])

    def test_missing_material_or_stale_revision_is_rejected_atomically(self):
        """! @brief 미정 입력을 임의로 채우거나 실패한 연구를 등록하지 않는다."""
        with self.assertRaises(ProjectError):
            self.service.mutate("study.create", self.request({"expected_revision": str(uuid4()), "specification": specification()}))
        self.assertFalse(self.service.journal.read()["studies"])
        material = deepcopy(next(item for item in self.document["materials"] if item["id"] == self.document["stackup"][0]["material_id"]))
        material["epsilon_r"] = Quantity.missing("dimensionless", "1").to_dict()
        self.service.mutate("project.apply_command", self.request({"expected_revision": self.document["revision_id"], "command_id": str(uuid4()),
                            "type": "material.set", "payload": {"material": material}}))
        self.document = self.service._load(self.service.journal.read()["projects"][self.context["project_id"]])
        before = self.service.journal.read()
        with self.assertRaises(ProjectError):
            self.create()
        self.assertEqual(self.service.journal.read(), before)

    def test_changed_runtime_and_cross_project_queries_are_rejected(self):
        """! @brief 다른 worker로 고정 연구를 이어 계산하거나 타 프로젝트 결과를 열지 않는다."""
        identity = self.create()["study_id"]
        self.control("study.start", identity)
        self.control("study.cancel", identity)
        self.service.studies.run_next()
        self.runtime.identity["manifest_sha256"] = "f" * 64
        with self.assertRaises(ProjectError):
            self.control("study.resume", identity)
        with self.assertRaises(ProjectError):
            self.service.studies.read("study.get", {"contract_version": "rfad.api/2.0", "context": {"project_id": str(uuid4())}, "input": {"study_id": identity}})

    def test_busy_solver_does_not_create_attempt_or_journal_commit_loop(self):
        """! @brief 다른 작업의 슬롯을 침범하거나 대기 중 동일 상태 commit을 반복하지 않는다."""
        identity = self.create()["study_id"]
        self.control("study.start", identity)
        def reserve(state):
            """! @brief 다른 실제 작업이 슬롯을 소유하는 상황을 구성한다."""
            self.fake_admit(state, "solver.prepare", self.context, {})
        self.service.journal.transaction(reserve)
        pointer = (Path(self.temporary.name) / "current.json").read_bytes()
        self.assertFalse(self.service.studies.run_next())
        self.assertEqual(pointer, (Path(self.temporary.name) / "current.json").read_bytes())
        self.assertFalse(self.service.journal.read()["studies"][identity]["cases"][0]["attempts"])

    def test_idle_coordinator_has_no_periodic_workspace_polling(self):
        """! @brief 연구가 없을 때 반복 JSON 읽기를 수행하지 않고 명령 이벤트만 기다린다."""
        self.assertFalse(self.service.studies.run_next())
        self.assertFalse(self.service.studies.polling)
        identity = self.create()["study_id"]
        self.control("study.start", identity)
        with patch.object(self.service.solver, "admit", side_effect=self.fake_admit):
            self.service.studies.run_next()
        self.assertTrue(self.service.studies.polling)
        self.control("study.cancel", identity)
        self.service.studies.run_next()
        self.service.studies.run_next()
        self.assertFalse(self.service.studies.polling)

    def test_definition_tampering_blocks_read_only_query(self):
        """! @brief 연구 정의의 실제 바이트 변조를 판정/실행 자료로 수용하지 않는다."""
        identity = self.create()["study_id"]
        reference = self.service.journal.read()["studies"][identity]["definition"]
        path = Path(self.temporary.name) / reference["uri"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ProjectError):
            self.service.studies.read("study.get", {"contract_version": "rfad.api/2.0", "context": self.context, "input": {"study_id": identity}})

    def test_cancel_before_next_phase_and_explicit_resume_preserve_attempt(self):
        """! @brief 취소 직후 자동 진행하지 않고 사용자 재개에서만 새 시도를 만든다."""
        identity = self.create()["study_id"]
        with patch.object(self.service.solver, "admit", side_effect=self.fake_admit):
            self.control("study.start", identity)
            self.assertTrue(self.service.studies.run_next())
            first = self.service.journal.read()["studies"][identity]["current_job_id"]
            self.control("study.cancel", identity)
            self.service.studies.run_next()
            self.assertEqual(self.service.journal.read()["studies"][identity]["state"], "cancelled")
            self.assertFalse(self.service.studies.run_next())
            self.control("study.resume", identity)
            self.service.studies.run_next()
            study = self.service.journal.read()["studies"][identity]
            self.assertNotEqual(first, study["current_job_id"])
            self.assertEqual(len(study["cases"][0]["attempts"]), 2)

    def test_prepared_phase_is_reused_after_cancel(self):
        """! @brief 이미 완료한 준비를 재실행하지 않고 다음 해석 단계부터 진행한다."""
        identity = self.create()["study_id"]
        with patch.object(self.service.solver, "admit", side_effect=self.fake_admit):
            self.control("study.start", identity)
            self.service.studies.run_next()
            job_id = self.service.journal.read()["studies"][identity]["current_job_id"]
            def complete(state):
                """! @brief 완료/취소 경합에서 완료 준비의 근거를 보존한다."""
                job = state["jobs"][job_id]
                job["solver"]["resource_reserved"] = False
                self.service._event(job, "running")
                self.service._event(job, "completed", operation_result={"prepared_plan": {"prepared_plan_id": str(uuid4()), "content_hash": "a" * 64}})
            self.service.journal.transaction(complete)
            self.control("study.cancel", identity)
            self.service.studies.run_next()
            self.control("study.resume", identity)
            self.service.studies.run_next()
            study = self.service.journal.read()["studies"][identity]
            self.assertEqual([attempt["phase"] for attempt in study["cases"][0]["attempts"]], ["prepare", "solve"])

    def test_explicit_resume_reconciles_unknown_guest_before_new_attempt(self):
        """! @brief 종료 불명인 이전 guest를 확인하기 전에 새 native 단계를 접수하지 않는다."""
        identity = self.create()["study_id"]
        order = []
        def admitted(state, method, context, data):
            """! @brief 종료 확인 이후의 접수 순서를 기록한다."""
            order.append("admit")
            return self.fake_admit(state, method, context, data)
        with patch.object(self.service.solver, "admit", side_effect=admitted):
            self.control("study.start", identity)
            self.service.studies.run_next()
            job_id = self.service.journal.read()["studies"][identity]["current_job_id"]
            def interrupted(state):
                """! @brief 실제 종료를 확인하지 못한 서비스 중단을 구성한다."""
                job = state["jobs"][job_id]
                self.service._event(job, "running")
                self.service._event(job, "interrupted", outcome_unknown=True)
                state["studies"][identity]["state"] = "interrupted"
            self.service.journal.transaction(interrupted)
            self.assertFalse(self.service.studies.run_next())
            self.control("study.resume", identity)
            def reconciled(value):
                """! @brief 기존 실행을 재시작하지 않고 종료 근거만 확정한다."""
                self.assertEqual(value, job_id)
                order.append("reconcile")
                self.service.journal.transaction(lambda state: state["jobs"][job_id]["solver"].update(resource_reserved=False, termination_confirmed=True))
            with patch.object(self.service.solver, "reconcile", side_effect=reconciled):
                self.service.studies.run_next()
            self.assertEqual(order, ["admit", "reconcile", "admit"])

    def test_restart_requires_explicit_resume_and_can_read_without_runtime(self):
        """! @brief 서비스 재시작으로 연구를 자동 재제출하지 않고 원본을 조회한다."""
        identity = self.create()["study_id"]
        self.control("study.start", identity)
        self.service.close()
        self.service = ProjectService(Path(self.temporary.name), auto_run=False)
        result = self.service.studies.read("study.get", {"contract_version": "rfad.api/2.0", "context": self.context, "input": {"study_id": identity}})
        self.assertEqual(result["state"], "interrupted")
        self.assertFalse(result["runtime_configured"])
        with self.assertRaises(ProjectError):
            self.control("study.resume", identity)

    def test_rpc_and_mcp_discover_project_studies(self):
        """! @brief GUI와 MCP가 같은 공개 메서드를 발견하고 사용한다."""
        request = {"jsonrpc": "2.0", "id": 1, "method": "capabilities.get", "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
        result = handle_frame(json.dumps(request).encode(), self.service)["result"]
        self.assertIn("study.create", result["methods"])
        self.assertTrue(result["study_profile"]["resume_supported"])
        request.update(method="study.context", params={"contract_version": "rfad.api/2.0", "context": self.context, "input": {}})
        self.assertFalse(handle_frame(json.dumps(request).encode(), self.service)["result"]["material_defaults_supplied"])

    def test_loss_recording_indices_are_observations_not_changed_physics(self):
        """! @brief 같은 물리 입력에서 격자별 손실 dump 크기만 달라져도 포트 비교는 가능하다."""
        left, right = fixture_result(grid=0.5), fixture_result(grid=0.25)
        left["provenance"]["analysis_plan"]["case"]["loss_recording"] = {"start_indices": [10, 10, 10], "estimated_field_bytes": 1000}
        right["provenance"]["analysis_plan"]["case"]["loss_recording"] = {"start_indices": [12, 12, 12], "estimated_field_bytes": 2000}
        compared = compare_samples(left, right, COMPARISON_PROFILE)
        self.assertLessEqual(compared["metrics"]["max_s11_complex_delta"], 0.02)
        right["provenance"]["analysis_plan"]["source_semantics"]["material"]["epsilon_r"] = 9
        with self.assertRaises(ValueError):
            compare_samples(left, right, COMPARISON_PROFILE)


if __name__ == "__main__":
    unittest.main()
