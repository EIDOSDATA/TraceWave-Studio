"""! @brief 프로젝트와 저장 계층의 구조화된 오류를 정의한다."""


class ProjectError(Exception):
    """! @brief 사용자 메시지와 별도의 오류 코드 및 세부 원인을 보존한다."""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        """! @brief 계층 사이에서 전달할 오류를 초기화한다."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {} if details is None else details

    def diagnostic(self) -> dict:
        """! @brief 시스템 명세의 진단 공통 필드를 반환한다."""
        return {
            "code": self.code,
            "severity": "blocking",
            "message_ko": self.message,
            "entity_ids": [],
            "field_paths": [],
            "details": self.details,
            "suggested_actions": ["현재 상태와 오류 원인을 확인한 후 다시 요청하십시오."],
            "recoverable": self.code not in {"E_HASH", "E_VERSION"},
        }
