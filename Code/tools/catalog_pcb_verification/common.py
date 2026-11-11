"""! @brief 통합 검증의 공개 RPC, 제한된 작업 대기와 봉인 자료 읽기를 제공한다."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.rpc import handle_frame


class VerificationError(RuntimeError):
    """! @brief 부분 실패의 구조화된 서비스 진단을 보고서에 보존한다."""

    def __init__(self, message, details=None):
        """! @brief 사용자 설명과 원본 실패 자료를 함께 저장한다."""
        super().__init__(message)
        self.details = details


def require(condition, message):
    """! @brief 검증 실패를 최적화 실행에서도 생략하지 않는다."""
    if not condition:
        raise VerificationError(message)


def call(service, method, data, context=None, *, mutation=False):
    """! @brief GUI와 동일한 공개 JSON-RPC 경계 및 요청 수명을 사용한다."""
    params = {"contract_version": "rfad.api/2.0", "context": context or {}, "input": data}
    if mutation:
        params.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
    response = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}), service)
    if "error" in response:
        raise VerificationError(method + " 요청 실패", response["error"])
    return response["result"]


def wait(service, task, *, timeout_seconds=360):
    """! @brief 완료 상태를 확인하며 시간 초과에는 취소 요청과 마지막 상태를 보존한다."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = call(service, "job.status", {"job_id": task["job_id"]})
        if status["state"] in {"completed", "failed", "cancelled", "interrupted"}:
            if status["state"] != "completed":
                raise VerificationError("작업이 완료되지 않았습니다.", status)
            return status["events"][-1]["operation_result"], status
        if time.monotonic() >= deadline:
            cancellation = call(service, "job.cancel", {"job_id": task["job_id"], "reason": "통합 검증 대기 시간 초과"}, mutation=True)
            raise VerificationError("대기 시간이 초과되었습니다. 취소 요청은 종료 확인과 다릅니다.",
                                    {"last_status": status, "cancellation_request": cancellation})
        time.sleep(0.1)


def read_json_artifact(service, descriptor):
    """! @brief journal의 길이/해시 검증을 거친 JSON 자료만 읽는다."""
    return json.loads(service.journal.read_artifact(descriptor))


def publish_report(path, report):
    """! @brief 완성된 JSON만 원자 교체하여 기록 실패 때 이전 보고서를 보존한다."""
    path = Path(path)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(canonical_bytes(report))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
