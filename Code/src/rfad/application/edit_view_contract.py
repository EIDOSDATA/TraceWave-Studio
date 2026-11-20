"""! @brief 기존 API와 Studio가 함께 쓰는 편집 조회 전송 한도를 정의한다."""

from rfad.domain.errors import ProjectError
from rfad.domain.resource_limits import MAX_SELECTION_RESULT_BYTES


PROFILE = "rfad.edit-view-transport/0.1"


def extended_view(data: dict) -> bool:
    """! @brief 명시한 전송 프로필만 허용하며 생략하면 기존 응답 상한을 적용한다."""
    if "display_profile" not in data:
        return False
    if data["display_profile"] != PROFILE:
        raise ProjectError("E_VERSION", "지원하지 않는 편집 조회 전송 프로필입니다.",
                           details={"field_path": "display_profile"})
    return True


def result_limit(previous_limit: int, extended: bool) -> int:
    """! @brief 선택 결과의 공통 한도까지 허용하되 전체 RPC 프레임 이내로 제한한다."""
    return MAX_SELECTION_RESULT_BYTES if extended else previous_limit
