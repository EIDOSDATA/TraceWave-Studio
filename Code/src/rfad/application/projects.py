"""! @brief 프로젝트 공개 API와 작업 수명을 조정하는 응용 서비스 facade다."""

from copy import deepcopy
import math
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from rfad.application.canvas import build_canvas_dto, canvas_command
from rfad.application.editor import build_dto, edit_command
from rfad.application.cad_jobs import CAD_METHODS, CadCoordinator, CadRuntime
from rfad.application.solver_jobs import SOLVER_METHODS, SolverCoordinator, SolverRuntime
from rfad.application.job_state import TERMINAL, append_event
from rfad.application.project_contract import (
    MAX_DOCUMENT_BYTES, MAX_HISTORY, MAX_JOBS, MAX_PROJECTS, MAX_RECEIPTS,
    MAX_SNAPSHOTS, RETENTION_SECONDS, _fields, _path, _uuid, validate_project_request,
)
from rfad.application.project_history import ProjectHistory
from rfad.application.project_operations import ProjectOperations
from rfad.application.project_repository import ProjectRepository
from rfad.application.request_ledger import RequestLedger
from rfad.application.pcb_selection import PcbSelectionCoordinator
from rfad.application.pcb_selection_contract import MUTATION_METHODS as PCB_SELECTION_MUTATIONS
from rfad.domain.errors import ProjectError
from rfad.storage.journal import Journal

ASYNC_METHODS = {
    "project.open", "project.save", "snapshot.create", "design.validate", "export.preview",
} | CAD_METHODS | SOLVER_METHODS
MUTATION_METHODS = ASYNC_METHODS | {
    "project.apply_command", "editor.apply", "canvas.apply", "project.undo", "project.redo", "job.cancel",
} | PCB_SELECTION_MUTATIONS


class ProjectService:
    """! @brief 단일 writer와 제한된 자료 처리 worker를 소유한다."""

    def __init__(
        self,
        workspace: Path,
        *,
        clock=time.time,
        auto_run: bool = True,
        fault_hook=None,
        cad_runtime: CadRuntime | None = None,
        solver_runtime: SolverRuntime | None = None,
        catalog_database: Path | None = None,
    ):
        """! @brief 저장소를 열고 이전에 실행 중이던 작업을 명시적으로 중단 처리한다."""
        self.workspace = Path(os.path.abspath(workspace))
        self.clock = clock
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._worker_error = None
        self.cad = CadCoordinator(self, cad_runtime)
        self.solver = SolverCoordinator(self, solver_runtime)
        self.journal = Journal(self.workspace, {
            "schema_version": "rfad.workspace/0.1", "epochs": {}, "projects": {},
            "paths": {}, "receipts": {}, "jobs": {}, "snapshots": {}, "commands": {},
        }, fault_hook=fault_hook)
        self.repository = ProjectRepository(self.workspace, self.journal, max_document_bytes=MAX_DOCUMENT_BYTES)
        self.history = ProjectHistory(self.repository)
        self.operations = ProjectOperations(self.repository, self._now)
        self.requests = RequestLedger(self.journal, self._now)
        self.pcb_selection = PcbSelectionCoordinator(self, catalog_database)
        try:
            self._initialize()
            if auto_run:
                self._thread = threading.Thread(target=self._worker, name="rfad-project-io", daemon=False)
                self._thread.start()
                self._wake.set()
                self.cad.start()
                self.solver.start()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        """! @brief 서비스 수명 범위를 시작한다."""
        return self

    def __exit__(self, *_):
        """! @brief worker 종료 후 파일 잠금을 해제한다."""
        self.close()

    def close(self) -> None:
        """! @brief 실행 중인 원자적 작업을 마친 뒤 종료한다."""
        self._stop.set()
        self._wake.set()
        self.cad.close()
        self.solver.close()
        if self._thread is not None:
            if self._thread.ident is not None:
                self._thread.join()
            self._thread = None
        self.journal.close()

    def _now(self) -> float:
        """! @brief 비교 가능한 유한 UTC epoch 초를 구한다."""
        value = float(self.clock())
        if not math.isfinite(value) or value < 0:
            raise ProjectError("E_SCHEMA", "유효하지 않은 서비스 시각입니다.")
        return value

    def _initialize(self, *, recover: bool = True) -> None:
        """! @brief 지원 저장소 버전과 미완료 작업을 확인한다."""
        def initialize(state):
            """! @brief 기존 개정과 작업을 보존하면서 복구 및 epoch 발급을 함께 게시한다."""
            if state.get("schema_version") != "rfad.workspace/0.1":
                raise ProjectError("E_VERSION", "지원하지 않는 작업 영역 버전입니다.")
            for name in ("analysis_plans", "prepared_plans", "solver_results"):
                state.setdefault(name, {})
            self.history.restore(state, limit=MAX_HISTORY)
            if recover:
                for job in state["jobs"].values():
                    if "solver" in job and job["state"] in {
                        "preparing", "running", "postprocessing", "cancel_requested",
                    }:
                        native = job["operation_method"] != "solver.plan"
                        job["solver"]["resource_reserved"] = native
                        self._event(
                            job, "interrupted", outcome_unknown=native,
                            error=ProjectError(
                                "E_CONFLICT", "이전 해석 작업을 자동 재실행하지 않습니다. guest 종료 상태를 확인하십시오.",
                            ).diagnostic(),
                        )
                    elif "cad" in job and job["state"] in {"running", "cancel_requested"}:
                        job["cad"]["resource_reserved"] = True
                        self._event(
                            job, "interrupted", outcome_unknown=True,
                            error=ProjectError(
                                "E_CONFLICT", "이전 CAD 실행의 종료를 확인하지 못했습니다. 자동 재실행하지 않습니다.",
                            ).diagnostic(),
                        )
                    elif job["state"] == "running":
                        self._event(job, "interrupted", error={
                            "domain_code": "E_CONFLICT", "message": "이전 프로세스가 완료 전에 종료되었습니다.",
                        })
            self.requests.ensure_epoch(state)
        self.journal.transaction(initialize)

    def policy(self) -> dict:
        """! @brief 작업을 복구하지 않고 현재 epoch와 보존 제한을 공개한다."""
        policy = self.requests.active_policy()
        while policy is None:
            self._initialize(recover=False)
            policy = self.requests.active_policy()
        return policy

    def _event(self, job: dict, state: str, **extra) -> None:
        """! @brief 공통 작업 상태 규칙으로 상태와 단조 증가 event를 함께 변경한다."""
        append_event(job, state, self._now(), **extra)

    def _load(self, project: dict) -> dict:
        """! @brief 공유 저장소를 통해 현재 불변 문서를 읽는다."""
        return self.repository.load(project)

    def _store_document(self, path: str, document: dict) -> dict:
        """! @brief 공유 저장소를 통해 새 revision을 봉인한다."""
        return self.repository.store(path, document)

    def _project(self, state: dict, context: dict) -> dict:
        """! @brief 명시한 프로젝트를 저장소 계약으로 조회한다."""
        return self.repository.project(state, context)

    def _preflight(self, method: str, context: dict, data: dict) -> None:
        """! @brief 기능별 요청 계약에 따라 접수 가능 여부를 검사한다."""
        if method in PCB_SELECTION_MUTATIONS:
            self.pcb_selection.validate_input(method, context, data)
        elif method in CAD_METHODS | {"export.preview"}:
            self.cad.validate_input(method, context, data)
        elif method in SOLVER_METHODS:
            self.solver.validate_input(method, context, data)
        else:
            validate_project_request(method, context, data)

    def mutate(self, method: str, params: dict) -> dict:
        """! @brief 원자 접수 후 작업자에게 변경 사실만 알린다."""
        if self._worker_error is not None:
            raise ProjectError("E_RESOURCE", "자료 처리 worker가 중단되었습니다. 서비스를 다시 열고 작업 상태를 확인하십시오.")
        result = self.requests.execute(method, params, self._dispatch_mutation)
        self._wake.set()
        self.cad.wake.set()
        self.solver.wake.set()
        return result

    def _dispatch_mutation(self, state: dict, method: str, context: dict, data: dict) -> dict:
        """! @brief 영수증과 동일한 transaction에서 기능별 명령을 실행한다."""
        self._preflight(method, context, data)
        if method == "project.apply_command":
            if data["type"] == "pcb_stackup.apply":
                raise ProjectError("E_UNSUPPORTED", "적층 적용은 pcb.selection.preview와 pcb.selection.apply를 사용하십시오.")
            return self._apply(state, context, data)
        elif method == "pcb.selection.apply":
            return self.pcb_selection.apply(state, context, data)
        elif method in {"editor.apply", "canvas.apply"}:
            project = self._project(state, context)
            document = self._load(project)
            if document["revision_id"] != data["expected_revision"]:
                message = (
                    "선택 속성의 기준 개정이 현재 개정과 다릅니다."
                    if method == "editor.apply" else "2D 편집의 기준 개정이 현재 개정과 다릅니다."
                )
                raise ProjectError("E_CONFLICT", message, details={"field_path": "expected_revision"})
            if method == "editor.apply":
                command = edit_command(document, data["selection"], data["values"])
            else:
                command = canvas_command(document, data["operation"], data["values"])
            return self._apply(state, context, {
                "expected_revision": data["expected_revision"],
                "command_id": data["command_id"],
                **command,
            })
        elif method in {"project.undo", "project.redo"}:
            return self._history(state, context, data, undo=method == "project.undo")
        elif method == "job.cancel":
            return self._cancel(state, data)
        elif method in CAD_METHODS:
            return self.cad.admit(state, method, context, data)
        elif method in SOLVER_METHODS:
            return self.solver.admit(state, method, context, data)
        else:
            return self._admit(state, method, context, data)

    def _apply(self, state: dict, context: dict, data: dict, *, record_history: bool = True) -> dict:
        """! @brief 현재 transaction의 명령과 이력을 함께 갱신한다."""
        return self.history.apply(state, context, data, limit=MAX_HISTORY, record_history=record_history)

    @staticmethod
    def _check_history_head(project: dict, revision: str) -> None:
        """! @brief 이력과 현재 개정의 연결을 공통 규칙으로 검사한다."""
        ProjectHistory.check_head(project, revision)

    @staticmethod
    def _history_status(project: dict) -> dict:
        """! @brief 현재 예산과 실행 취소/다시 실행 가능 상태를 반환한다."""
        return ProjectHistory.status(project, limit=MAX_HISTORY)

    def _history(self, state: dict, context: dict, data: dict, *, undo: bool) -> dict:
        """! @brief 영속 이력의 검증된 역명령을 새 개정으로 실행한다."""
        return self.history.move(state, context, data, limit=MAX_HISTORY, undo=undo)

    def editor_state(self, params: dict) -> dict:
        """! @brief 개정에 결합된 선택 속성 DTO를 읽고 조회로 저장 이력을 변경하지 않는다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        data = _fields(params["input"], {"expected_revision"}, {"selection"})
        _uuid(data["expected_revision"])
        state = self.journal.read()
        project = self._project(state, params["context"])
        document = self._load(project)
        self._check_history_head(project, document["revision_id"])
        if document["revision_id"] != data["expected_revision"]:
            raise ProjectError("E_CONFLICT", "속성 조회의 기준 개정이 현재 개정과 다릅니다.", details={"field_path": "expected_revision"})
        return build_dto(document, self._saved_revision(project), self._history_status(project), data.get("selection"))

    def canvas_state(self, params: dict) -> dict:
        """! @brief 개정에 결합된 2D 표시 데이터만 조회하며 전체 원본을 전송하지 않는다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        data = _fields(params["input"], {"expected_revision"})
        _uuid(data["expected_revision"])
        state = self.journal.read()
        project = self._project(state, params["context"])
        document = self._load(project)
        self._check_history_head(project, document["revision_id"])
        if document["revision_id"] != data["expected_revision"]:
            raise ProjectError("E_CONFLICT", "2D 조회의 기준 개정이 현재 개정과 다릅니다.", details={"field_path": "expected_revision"})
        return build_canvas_dto(document)

    def _admit(self, state: dict, method: str, context: dict, data: dict) -> dict:
        """! @brief 작은 작업도 queued TaskRef로만 접수한다."""
        if len(state["jobs"]) >= MAX_JOBS or sum(job["state"] == "queued" for job in state["jobs"].values()) >= 32:
            raise ProjectError("E_RESOURCE", "작업 보존 또는 대기열 상한에 도달했습니다.")
        if method == "export.preview":
            return self.cad.admit_preview(state, context, data)
        captured = None
        if method != "project.open":
            project = self._project(state, context)
            document = self._load(project)
            if document["revision_id"] != data["expected_revision"]:
                raise ProjectError("E_CONFLICT", "현재 revision과 요청 revision이 다릅니다.")
            if "target" in data and data["target"] != project["path"]:
                raise ProjectError("E_UNSUPPORTED", "다른 경로로 저장은 copy/export 구현 후 지원합니다.")
            captured = deepcopy(project["current"])
        job_id = str(uuid4())
        job = {
            "job_id": job_id,
            "run_id": str(uuid4()),
            "kind": "data_processing",
            "operation_method": method,
            "context": deepcopy(context),
            "input": deepcopy(data),
            "captured": captured,
            "events": [],
        }
        self._event(job, "queued")
        state["jobs"][job_id] = job
        return {"job_id": job_id, "state": "queued", "events_cursor": 1}

    def _cancel(self, state: dict, data: dict) -> dict:
        """! @brief 미시작 자료 처리 작업을 제거하고 이미 확정된 terminal은 보존한다."""
        job = state["jobs"].get(data["job_id"])
        if job is None:
            raise ProjectError("E_SCHEMA", "작업을 찾을 수 없습니다.")
        if "cad" in job:
            self.cad.cancel_job(job, data.get("reason", ""))
        elif "solver" in job:
            self.solver.cancel_job(job, data.get("reason", ""))
        elif job["state"] not in TERMINAL:
            self._event(job, "cancel_requested", reason=data.get("reason", ""))
            self._event(job, "cancelled")
        return {"job_id": job["job_id"], "state": job["state"], "events_cursor": len(job["events"])}

    def cad_latest(self, params: dict) -> dict:
        """! @brief 지정 프로젝트의 마지막 게시 완료 CAD 참조만 읽고 큰 산출물은 열지 않는다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        _fields(params["input"], set())
        state = self.journal.read()
        self._project(state, params["context"])
        completed = [job for job in state["jobs"].values()
                     if "cad" in job and job["state"] == "completed"
                     and job["context"].get("project_id") == params["context"]["project_id"]]
        if not completed:
            return {"profile": "rfad.cad-view/0.1", "result": None, "job_id": None}
        job = max(completed, key=lambda item: (item["events"][-1]["timestamp"], item["job_id"]))
        return {"profile": "rfad.cad-view/0.1", "result": deepcopy(job["events"][-1]["operation_result"]),
                "job_id": job["job_id"]}

    def status(self, params: dict) -> dict:
        """! @brief 영속 상태와 마지막 cursor 이후 event를 반환한다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        _fields(params["context"], set())
        data = _fields(params["input"], {"job_id"}, {"cursor"})
        _uuid(data["job_id"])
        cursor = data.get("cursor", 0)
        if type(cursor) is not int or cursor < 0:
            raise ProjectError("E_SCHEMA", "cursor는 음수가 아닌 정수여야 합니다.")
        state = self.journal.read()
        job = state["jobs"].get(data["job_id"])
        if job is None or cursor > len(job["events"]):
            raise ProjectError("E_SCHEMA", "작업 또는 cursor가 유효하지 않습니다.")
        return {
            "job_id": job["job_id"],
            "state": job["state"],
            "events_cursor": len(job["events"]),
            "events": deepcopy(job["events"][cursor:]),
            "artifacts": deepcopy(job.get("artifacts", [])),
        }

    def run_next(self) -> bool:
        """! @brief queued 작업 하나를 실제 처리하고 terminal 결과를 영속화한다."""
        def begin(state):
            """! @brief worker가 소유할 미시작 자료 처리 작업 하나를 선택한다."""
            for job in state["jobs"].values():
                if job["state"] == "queued" and "cad" not in job and "solver" not in job:
                    self._event(job, "running")
                    return job["job_id"]
            return None
        if not any(
            job["state"] == "queued" and "cad" not in job and "solver" not in job
            for job in self.journal.read()["jobs"].values()
        ):
            return False
        job_id = self.journal.transaction(begin)
        if job_id is None:
            return False
        try:
            def finish(state):
                """! @brief 결과와 terminal event를 같은 commit으로 게시한다."""
                job = state["jobs"][job_id]
                if job["state"] != "running":
                    return
                result = self._execute(state, job)
                self._event(job, "completed", operation_result=result)
            self.journal.transaction(finish)
        except (ProjectError, OSError) as error:
            def fail(state):
                """! @brief 이전 terminal 상태를 덮어쓰지 않고 실패 진단을 기록한다."""
                job = state["jobs"][job_id]
                if job["state"] not in TERMINAL:
                    diagnostic = (
                        error.diagnostic() if isinstance(error, ProjectError)
                        else ProjectError("E_DISK", str(error)).diagnostic()
                    )
                    self._event(job, "failed", error=diagnostic)
            self.journal.transaction(fail)
        return True

    def _execute(self, state: dict, job: dict) -> dict:
        """! @brief transaction 안의 파일 작업을 전용 실행기로 전달한다."""
        return self.operations.execute(state, job)

    def _saved_revision(self, project: dict) -> str:
        """! @brief 저장 기준점도 같은 무결성 검사로 조회한다."""
        return self.repository.saved_revision(project)

    def _worker(self) -> None:
        """! @brief 요청이 있을 때만 작은 파일 작업을 순차 처리한다."""
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            try:
                while not self._stop.is_set() and self.run_next():
                    pass
            except Exception as error:
                self._worker_error = error
                return
