"""! @brief 작업 상태와 단조 증가 이력을 하나의 명시적 전이 규칙으로 관리한다.

@details CAD 프로세스 종료와 WSL 소유권/예약의 증거는 각 조정기가 판단한다.
이 모듈은 이미 결정한 상태가 허용된 순서인지 검사하며 작업을 실행하지 않는다.
"""

from types import MappingProxyType

from rfad.domain.errors import ProjectError


TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
TRANSITIONS = MappingProxyType({
    None: frozenset({"queued"}),
    "queued": frozenset({"running", "preparing", "postprocessing", "cancel_requested"}),
    "running": frozenset({"postprocessing", "completed", "failed", "cancel_requested", "interrupted"}),
    "preparing": frozenset({"completed", "failed", "cancel_requested", "interrupted"}),
    "postprocessing": frozenset({"completed", "failed", "cancel_requested", "interrupted"}),
    "cancel_requested": frozenset({"cancelled", "interrupted"}),
    **{state: frozenset() for state in TERMINAL},
})
_EVENT_FIELDS = frozenset({"seq", "run_id", "timestamp", "state", "phase", "progress_basis"})


def append_event(job: dict, state: str, timestamp: float, **details) -> None:
    """! @brief 전이를 먼저 확인한 뒤 상태와 event를 함께 변경한다.

    @param job journal transaction 안에서 변경하는 작업 레코드.
    @param state 조정기가 결정한 다음 상태.
    @param timestamp 서비스가 검증한 UTC epoch 초.
    @param details 종료 증거, 오류 또는 작업 결과의 부가 필드.
    @details 완료/중단 작업은 다시 활성화하지 않으며 실패한 전이는 원본을 보존한다.
    """
    previous = job.get("state")
    if state not in TRANSITIONS.get(previous, ()):
        raise ProjectError("E_CONFLICT", "허용되지 않은 작업 상태 전이입니다.", details={"previous_state": previous, "next_state": state})
    if _EVENT_FIELDS.intersection(details):
        raise ProjectError("E_CONFLICT", "작업 event의 식별 또는 순서 필드를 덮어쓸 수 없습니다.")
    event = {
        "seq": len(job["events"]) + 1,
        "run_id": job["run_id"],
        "timestamp": timestamp,
        "state": state,
        "phase": state,
        "progress_basis": "indeterminate",
        **details,
    }
    job["state"] = state
    job["events"].append(event)
