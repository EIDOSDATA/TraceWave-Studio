"""! @brief 안정 UUID와 분리된 영속 이름과 읽기 전용 임시 표시 이름을 관리한다."""

import re
import unicodedata

from rfad.domain.errors import ProjectError


PROFILE = "rfad.object-name/0.1"
NAMED_SCHEMA = "rfad.project/0.5"
NAMED_SCHEMAS = (NAMED_SCHEMA, "rfad.project/0.6")
PREFIXES = {"line_path": "선", "arc_path": "원호", "planar_region": "면", "pad": "패드", "via": "비아"}


def validate_name(value: object, field: str = "name") -> str:
    """! @brief 새 이름은 원문을 자르거나 정규화하지 않고 위치와 함께 검사한다."""
    if (type(value) is not str or not 1 <= len(value) <= 256 or value != value.strip()
            or any(unicodedata.category(char) in ("Cc", "Cs") for char in value)):
        raise ProjectError("E_SCHEMA", "이름은 앞뒤 공백과 제어 문자가 없는 1~256자여야 합니다.", details={"field_path": field})
    return value


def _rows(document: dict, collection: str) -> list[dict]:
    """! @brief 원본 목록을 변경하지 않고 이름 범위에 속한 객체를 읽는다."""
    if collection == "board":
        return [] if document.get("board") is None else [document["board"]]
    rows = document.get(collection, [])
    return list(rows.values()) if isinstance(rows, dict) else list(rows)


def name_prefix(obj: dict, collection: str = "geometry") -> str:
    """! @brief 의미 역할이 명시된 경우만 급전선과 접지면 접두어를 사용한다."""
    if collection == "board":
        return "기판"
    if collection == "ports":
        return "급전"
    kind, role = obj.get("kind"), obj.get("role")
    if kind == "line_path" and role == "feed":
        return "급전선"
    if kind == "planar_region" and role == "ground":
        return "접지면"
    return PREFIXES.get(kind, "객체")


def _next_number(used: set[str], prefix: str) -> int:
    """! @brief 접두어와 숫자가 정확히 일치하는 기존 이름에서 다음 번호를 찾는다."""
    pattern = re.compile(re.escape(prefix) + r" ([0-9]+)$")
    numbers = [int(match.group(1)) for name in used if (match := pattern.fullmatch(name))]
    return max(numbers, default=0) + 1


def _next_name(used: set[str], prefix: str) -> str:
    """! @brief 새 이름은 기존 접두어와 두 자리 이상 번호 형식으로 만든다."""
    return f"{prefix} {_next_number(used, prefix):02d}"


def display_names(document: dict, collection: str = "geometry") -> dict[str, str]:
    """! @brief UUID 순서로 임시 이름을 만들되 원본/개정/저장 상태에는 쓰지 않는다."""
    rows = _rows(document, collection)
    result = {obj["id"]: obj["name"] for obj in rows if "name" in obj}
    used = set(result.values())
    next_numbers: dict[str, int] = {}
    for obj in sorted(rows, key=lambda row: row["id"]):
        if "name" not in obj:
            prefix = name_prefix(obj, collection)
            if prefix not in next_numbers:
                next_numbers[prefix] = _next_number(used, prefix)
            result[obj["id"]] = f"{prefix} {next_numbers[prefix]:02d}"
            next_numbers[prefix] += 1
    return result


def object_label(document: dict, obj: dict, collection: str = "geometry") -> str:
    """! @brief 모든 화면에서 동일한 영속 이름 또는 해당 개정의 임시 이름을 읽는다."""
    if "name" in obj:
        return obj["name"]
    names = display_names(document, collection)
    if obj["id"] in names:
        return names[obj["id"]]
    return _next_name(set(names.values()), name_prefix(obj, collection))


def object_name_state(obj: dict) -> str:
    """! @brief 표시 이름이 원본에 있는지 명시하여 임시 표시를 저장값으로 오인하지 않는다."""
    return "stored" if "name" in obj else "temporary"


def name_dto(document: dict, obj: dict, collection: str = "geometry", *, labels: dict[str, str] | None = None) -> dict:
    """! @brief 실제 이름 미정은 null로 유지하며 같은 개정의 표시 이름 목록을 재사용할 수 있다."""
    label = object_label(document, obj, collection) if labels is None else labels[obj["id"]]
    return {"name": obj.get("name"), "name_state": object_name_state(obj), "label": label}


def allocate_name(document: dict, obj: dict, collection: str = "geometry", reserved=(), *, prefix: str | None = None) -> str:
    """! @brief 기존 이름/임시 표시/같은 후보의 예약 이름을 피하는 결정적 생성 이름을 반환한다."""
    used = {*display_names(document, collection).values(), *reserved}
    return validate_name(_next_name(used, name_prefix(obj, collection) if prefix is None else prefix))
