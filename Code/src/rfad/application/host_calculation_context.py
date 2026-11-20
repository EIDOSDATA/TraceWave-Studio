"""! @brief 계산 서비스에 실제 저장/이력/영수증 capability만 제공하는 단일 writer 경계다."""
import math
import hashlib
from pathlib import Path
import time

from rfad.application import design_sweep_service, network_service, measurement_service
from rfad.application.host_calculation_runtime import HostCalculationRuntime
from rfad.application.job_state import append_event
from rfad.application.project_contract import MAX_DOCUMENT_BYTES, MAX_HISTORY
from rfad.application.project_history import ProjectHistory
from rfad.application.project_operations import ProjectOperations
from rfad.application.project_repository import ProjectRepository
from rfad.application.project_studies import StudyCoordinator
from rfad.application.request_ledger import RequestLedger
from rfad.application.solver_jobs import SolverCoordinator
from rfad.domain.errors import ProjectError
from rfad.storage.journal import Journal, new_workspace_state

MUTATIONS = design_sweep_service.MUTATIONS | {network_service.MUTATION} | measurement_service.MUTATIONS


class HostCalculationContext:
    """! @brief Projects facade/callback 없이 구체 저장 객체와 계산/solver 수명을 연결한다."""
    def __init__(self, workspace, *, clock=time.time, fault_hook=None, solver_runtime=None):
        self.workspace, self.clock = Path(workspace), clock
        self.calculation_runtime = HostCalculationRuntime()
        self._calculation_error = None
        try:
            self.calculation_runtime.establish()
        except ProjectError as error:
            self._calculation_error = error
        self.journal = Journal(self.workspace, new_workspace_state(), fault_hook=fault_hook)
        self.repository = ProjectRepository(self.workspace, self.journal, max_document_bytes=MAX_DOCUMENT_BYTES)
        self.history = ProjectHistory(self.repository)
        self.operations = ProjectOperations(self.repository, self._now)
        self.requests = RequestLedger(self.journal, self._now)
        self.solver = SolverCoordinator(self, solver_runtime)
        self.studies = StudyCoordinator(self)

    def _now(self):
        """! @brief 구체 clock에서 유한 UTC epoch 초만 허용한다."""
        value = float(self.clock())
        if not math.isfinite(value) or value < 0:
            raise ProjectError("E_SCHEMA", "유효하지 않은 계산 서비스 시각입니다.")
        return value

    def _event(self, job, state, **extra):
        """! @brief facade를 다시 호출하지 않고 공통 상태 전이를 직접 사용한다."""
        append_event(job, state, self._now(), **extra)

    def _load(self, project):
        """! @brief 한 repository의 봉인 원본만 읽는다."""
        return self.repository.load(project)

    def _project(self, state, context):
        """! @brief 프로젝트 소유권을 실제 repository에서 검사한다."""
        return self.repository.project(state, context)

    @staticmethod
    def _check_history_head(project, revision):
        """! @brief 계산과 현재 편집 개정의 연결을 같은 history 계약으로 확인한다."""
        ProjectHistory.check_head(project, revision)

    def _apply(self, state, context, data, *, record_history=True):
        """! @brief 계산 source 재확인 후 현재 transaction에 typed 명령을 한 번만 적용한다."""
        self.verify_calculation()
        return self.history.apply(state, context, data, limit=MAX_HISTORY, record_history=record_history)

    def calculation_identity(self):
        """! @brief 최초 고정한 제어/수학/설치 identity를 반환한다."""
        if self._calculation_error is not None:
            raise ProjectError(self._calculation_error.code, "과거 자료는 읽을 수 있으나 새 계산 source를 고정하지 못했습니다.",
                               details={"cause": self._calculation_error.diagnostic()})
        return self.calculation_runtime.verify()

    def verify_calculation(self):
        """! @brief 시작/재개/게시 전에 세션 로딩 pin을 확인한다."""
        self.calculation_identity()

    def calculate(self, operation, inputs):
        """! @brief 원본 JSON만 닫힌 수학 worker에 전달하고 값/영수증을 돌려준다."""
        self.verify_calculation()
        return self.calculation_runtime.execute(operation, inputs)

    def calculation_source(self, project):
        """! @brief 게시 전 검토 가능한 합집합 source 참조/바이트를 반환하며 파일은 쓰지 않는다."""
        self.verify_calculation()
        raw = self.calculation_runtime.source_bytes
        digest = hashlib.sha256(raw).hexdigest()
        return {"uri": project["path"] + "/host-calculation-sources/" + digest + ".json",
                "sha256": digest, "bytes": len(raw)}, raw

    def recover(self, state):
        """! @brief 계산을 자동 재실행하지 않고 기존 연구의 중단 상태만 복원한다."""
        self.studies.recover(state)
        design_sweep_service.recover(self, state)

    def read(self, method, params):
        """! @brief 읽기 API도 닫힌 서비스 입력/소유권 검증을 통과시킨다."""
        if method in network_service.READS:
            return network_service.read(self, method, params)
        if method in design_sweep_service.READS:
            return design_sweep_service.read(self, method, params)
        if method in measurement_service.READS:
            return measurement_service.read(self, method, params)
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 계산 조회입니다.")

    def _dispatch(self, state, method, context, data):
        """! @brief 영수증과 한 transaction에서 실제 계산 서비스 계약을 다시 확인한다."""
        if method != "sweep.cancel":
            self.verify_calculation()
        if method == network_service.MUTATION:
            return network_service.admit(self, state, context, data)
        if method in design_sweep_service.MUTATIONS:
            return design_sweep_service.admit(self, state, method, context, data)
        if method in measurement_service.MUTATIONS:
            return measurement_service.admit(self, state, method, context, data)
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 계산 변경입니다.")

    def mutate(self, method, params):
        """! @brief facade의 검증 완료 선언을 받지 않고 원문 envelope와 receipt를 직접 처리한다."""
        return self.requests.execute(method, params, self._dispatch)
