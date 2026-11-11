"""! @brief 요청 epoch와 재전송 영수증을 실제 변경과 원자적으로 보존한다."""

from copy import deepcopy
from typing import Callable
from uuid import uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.project_contract import MAX_RECEIPTS, RETENTION_SECONDS, _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.storage.journal import Journal


class RequestLedger:
    """! @brief 원 작업과 영수증 사이에 별도 commit을 만들지 않는 멱등 요청 경계다."""

    def __init__(self, journal: Journal, now: Callable[[], float]):
        """! @brief 저장소와 검증된 시각 공급자를 공유한다."""
        self.journal = journal
        self.now = now

    def ensure_epoch(self, state: dict) -> None:
        """! @brief 활성 epoch가 없을 때 보존 예산 안에서 새 epoch를 발급한다."""
        now = self.now()
        if any(epoch["expires_at"] > now for epoch in state["epochs"].values()):
            return
        if len(state["epochs"]) >= 128:
            raise ProjectError("E_RESOURCE", "초기 profile의 epoch 보존 상한에 도달했습니다.")
        key = str(uuid4())
        state["epochs"][key] = {"issued_at": now, "expires_at": now + RETENTION_SECONDS}

    def active_policy(self) -> dict | None:
        """! @brief 현재 활성 epoch만 조회하며 복구나 작업 상태를 변경하지 않는다."""
        state = self.journal.read()
        now = self.now()
        valid = [(key, epoch) for key, epoch in state["epochs"].items() if epoch["expires_at"] > now]
        if not valid:
            return None
        key, epoch = max(valid, key=lambda item: item[1]["issued_at"])
        return {"status": "implemented", "mutations_enabled": True,
                "request_key_epoch": key, "epoch_expires_at": epoch["expires_at"],
                "receipt_retention_seconds": RETENTION_SECONDS,
                "authority": "workspace_journal", "max_receipts": MAX_RECEIPTS}

    def execute(self, method: str, params: dict, handler: Callable[[dict, str, dict, dict], dict]) -> dict:
        """! @brief 같은 transaction에서 영수증을 조회하거나 실제 변경과 응답을 함께 게시한다."""
        _fields(params, {"contract_version", "context", "input", "request_key", "request_key_epoch"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        key, epoch_id = params["request_key"], params["request_key_epoch"]
        if type(key) is not str or not 1 <= len(key) <= 128 or any(ord(c) < 32 for c in key):
            raise ProjectError("E_SCHEMA", "request_key는 1~128자의 식별자여야 합니다.")
        _uuid(epoch_id)
        canonical = {"method": method, "context": params["context"], "input": params["input"]}
        try:
            digest = canonical_hash(canonical)
        except (ValueError, TypeError, UnicodeError) as error:
            raise ProjectError("E_SCHEMA", "명령 데이터의 정규 표현이 유효하지 않습니다.") from error
        receipt_id = canonical_hash([epoch_id, key])
        def update(state):
            """! @brief 재전송을 먼저 확인하고 신규 변경에만 영수증을 생성한다."""
            now = self.now()
            receipt = state["receipts"].get(receipt_id)
            if receipt is not None:
                if receipt["expires_at"] <= now:
                    raise ProjectError("E_IDEMPOTENCY_EXPIRED", "접수 기록이 만료되었습니다. 원 작업을 먼저 조회하십시오.")
                if receipt["payload_hash"] != digest:
                    raise ProjectError("E_CONFLICT", "같은 request_key를 다른 명령에 사용할 수 없습니다.")
                return deepcopy(receipt["response"])
            epoch = state["epochs"].get(epoch_id)
            if epoch is None or epoch["expires_at"] <= now:
                raise ProjectError("E_IDEMPOTENCY_EXPIRED", "알 수 없거나 만료된 발급 epoch입니다.")
            if len(state["receipts"]) >= MAX_RECEIPTS:
                raise ProjectError("E_RESOURCE", "접수 기록 보존 상한에 도달했습니다.")
            context, data = params["context"], params["input"]
            response = handler(state, method, context, data)
            state["receipts"][receipt_id] = {
                "request_key": key, "epoch": epoch_id, "method": method,
                "scope": deepcopy(context) or {"path": data.get("path")},
                "expected_revision": data.get("expected_revision"), "payload_hash": digest,
                "accepted_at": now, "expires_at": now + RETENTION_SECONDS, "response": deepcopy(response),
            }
            return response
        return self.journal.transaction(update)
