"""! @brief 영속 연구의 상태 전이와 기존 단일 solver 슬롯의 순차 실행을 조정한다."""

import threading
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.job_state import TERMINAL
from rfad.application.project_study_contract import ACTIVE, validate_input
from rfad.application.project_study_commands import control, query
from rfad.application.project_study_results import assessment
from rfad.domain.errors import ProjectError


class StudyCoordinator:
    """! @brief GUI 수명과 분리된 연구 진행을 맡으며 물리 계산은 solver에 위임한다."""

    def __init__(self, service):
        """! @brief 서비스/스레드 동기화만 보유하고 별도 native 실행기를 만들지 않는다."""
        self.service = service
        self.stop, self.wake = threading.Event(), threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.polling = False

    def start(self):
        """! @brief 회로 스윕도 처리하되 native 실행 여부는 각 연구의 고정 환경을 따른다."""
        self.thread = threading.Thread(target=self._loop, name="rfad-study-coordinator", daemon=False)
        self.thread.start()

    def close(self):
        """! @brief solver 종료 전에 새 단계 접수를 중지한다."""
        self.stop.set()
        self.wake.set()
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join()

    @staticmethod
    def recover(state):
        """! @brief 서비스 재시작은 연구를 자동 재실행하지 않고 명시적 재개를 요구한다."""
        for study in state.setdefault("studies", {}).values():
            if study["state"] in ACTIVE:
                study["state"] = "interrupted"
                study["message"] = "이전 서비스가 종료됐습니다. 재개로 실제 종료와 고정 출처를 확인하십시오."

    def admit(self, state, method, context, data):
        """! @brief 외부 요청의 영수증과 같은 transaction에서 상태를 변경한다."""
        validate_input(method, context, data)
        return control(self.service, state, method, context, data)

    def read(self, method, params):
        """! @brief 변경 없는 조회도 공개 요청 형태와 소유 프로젝트를 검사한다."""
        from rfad.application.solver_requests import require_fields

        require_fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 연구 API 버전입니다.")
        validate_input(method, params["context"], params["input"])
        return query(self.service, method, params["context"], params["input"])

    def _loop(self):
        """! @brief 상태 변화/완료 작업을 유한 간격으로 확인하고 오류 시 해당 연구만 멈춘다."""
        while not self.stop.is_set():
            self.wake.wait(0.25 if self.polling else None)
            self.wake.clear()
            self.run_next()

    def run_next(self):
        """! @brief 잠금 밖의 종료 확인/판정과 원자적 단계 접수를 분리한다."""
        if self.stop.is_set() or not self.lock.acquire(blocking=False):
            return False
        identity = None
        try:
            state = self.service.journal.read()
            sweep_active = any(row["state"] in ACTIVE for row in state.get("sweeps", {}).values())
            if sweep_active:
                from rfad.application.design_sweep_runner import run_next

                self.polling = True
                return run_next(self.service, self.stop)
            study = next((row for row in state.get("studies", {}).values() if row["state"] in ACTIVE), None)
            self.polling = study is not None
            if study is None or self.service.solver.runtime is None:
                return False
            identity = study["study_id"]
            self.service.verify_calculation()
            job = state["jobs"].get(study["current_job_id"])
            if study["state"] == "resuming" and job is not None and job["solver"].get("resource_reserved") and job["state"] == "interrupted":
                self.service.solver.reconcile(job["job_id"])
            elif job is not None and job["state"] not in TERMINAL:
                return False
            elif study["state"] in {"running", "resuming"} and job is None and any(row.get("solver", {}).get("resource_reserved") for row in state["jobs"].values()):
                return False
            if not (study["state"] in {"running", "resuming"} and job is None and self._assess(study)):
                self.service.journal.transaction(lambda current: self._advance(current, identity))
            self.service.solver.wake.set()
            return True
        except Exception as error:
            if identity is not None:
                def fail(state):
                    """! @brief 원본/시도를 남기고 자동 교체 실행을 방지한다."""
                    study = state["studies"][identity]
                    study.update(state="blocked", message=str(error)[:2048])
                self.service.journal.transaction(fail)
            return False
        finally:
            self.lock.release()

    def _assess(self, study):
        """! @brief 완료한 격자만 비교하고 다음 수준, 수렴 또는 예산 중단을 결정한다."""
        pending = [case for case in study["cases"] if case["phase"] != "done"]
        completed = len(study["cases"]) - len(pending)
        adaptive = study["specification"].get("adaptive_mesh")
        decision = None
        if adaptive and pending and completed:
            memory_limit = adaptive["memory_limit_mib"] * 1024 ** 2
            next_memory = pending[0]["resource_estimate"]["estimated_memory_bytes"]
            if next_memory > memory_limit:
                decision = "memory_limit"
            elif completed < 3:
                return False
        elif pending:
            return False
        result = assessment(self.service, study)
        message = "모든 계산과 격자 비교를 완료했습니다."
        if adaptive:
            stable = result["port_stability"] == "established"
            settings = study["specification"]["settings"]
            if "radiation" in settings:
                stable = stable and result["radiation_mesh_stability"] == "passed"
            if "power_balance" in settings:
                loss = result["individual_loss_stability"] or {}
                stable = (stable and loss.get("status") == "passed"
                          and result["reference_energy_closure"] == "within_initial_numerical_budget")
            if stable:
                decision = "stability_reached"
                message = "지정한 격자 안정성 기준을 충족했습니다."
            elif decision == "memory_limit":
                message = "다음 격자가 예상 메모리 상한을 넘어 중단했습니다."
            elif not pending:
                decision = "levels_exhausted"
                message = "지정한 격자 수준을 모두 사용했습니다."
            else:
                return False
            result["adaptive_mesh_decision"] = {"reason": decision, "completed_levels": completed,
                                                "skipped_levels_mm": [case["settings"]["grid_mm"] for case in pending],
                                                "memory_limit_mib": adaptive["memory_limit_mib"]}
        identity = study["study_id"]
        artifact = self.service.journal.put_immutable(f"study-artifacts/{identity}/assessment-{uuid4()}.json", canonical_bytes(result))

        def publish(current):
            """! @brief 취소와 경합한 판정을 완료로 승격하지 않는다."""
            active = current["studies"][identity]
            if active["state"] in {"running", "resuming"}:
                for case in active["cases"]:
                    if case["phase"] != "done":
                        case["phase"] = "skipped"
                active.update(state="completed", assessment=artifact, message=message)

        self.service.journal.transaction(publish)
        return True

    def _advance(self, state, identity):
        """! @brief 완료 결과를 수집하고 취소/명시적 재개를 처리한 뒤 한 단계만 접수한다."""
        study = state["studies"][identity]
        if study["state"] not in ACTIVE or self.stop.is_set():
            return
        job = state["jobs"].get(study["current_job_id"])
        if job is not None:
            if job["state"] not in TERMINAL:
                return
            case = next(case for case in study["cases"] if any(attempt["job_id"] == job["job_id"] for attempt in case["attempts"]))
            if job["state"] == "completed":
                result = job["events"][-1]["operation_result"]
                if case["phase"] == "prepare":
                    case.update(phase="solve", prepared_plan=result["prepared_plan"])
                else:
                    case.update(phase="done", result_id=result["artifact_id"])
                study["current_job_id"] = None
                if (case["phase"] == "done" and study["state"] in {"running", "resuming"}
                        and "adaptive_mesh" in study["specification"]):
                    study["state"] = "running"
                    return
            elif study["state"] == "resuming":
                if job["solver"].get("resource_reserved"):
                    raise ProjectError("E_CONFLICT", "이전 guest 종료 확인 전에는 새 단계를 실행할 수 없습니다.")
                study["current_job_id"] = None
            else:
                study.update(state="cancelled" if study["state"] == "cancel_requested" else job["state"],
                             message="작업이 중단됐습니다. 완료 결과와 이전 시도를 보존하며 명시적 재개를 기다립니다.")
                return
        if study["state"] == "cancel_requested":
            study.update(state="cancelled", message="현재 작업의 종료를 확인하고 연구를 취소했습니다.")
            return
        study["state"] = "running"
        case = next((case for case in study["cases"] if case["phase"] != "done"), None)
        if case is None:
            return
        if any(job.get("solver", {}).get("resource_reserved") for job in state["jobs"].values()):
            return
        if case["phase"] == "prepare":
            method = "solver.prepare"
            data = {"analysis_plan": {key: case["analysis_plan"][key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 300}}
        else:
            method = "job.submit"
            data = {"task_plan": {"kind": "em_analysis", "execution_mode": "solve_and_postprocess",
                                  "prepared_plan": {key: case["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")}}, "budget": {"timeout_seconds": 300}}
        task = self.service.solver.admit(state, method, {"project_id": study["project_id"]}, data)
        case["attempts"].append({"phase": case["phase"], "job_id": task["job_id"]})
        study.update(current_job_id=task["job_id"], message="격자 연구의 " + case["phase"] + " 단계를 실행 중입니다.")
