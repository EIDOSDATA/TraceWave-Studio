"""! @brief rfad.canonical/1.0의 JSON 바이트와 버전 구분 해시를 생성한다.

@details RFAD 07의 6절과 RFAD 08의 11절에 따른 초기 codec이다.
정확한 내장 None/bool/int/float/str/list/dict만 허용한다. object key는
Unicode code point 순서이고 배열 순서와 Unicode 원문은 보존한다.
유한 float64는 Python repr의 왕복 가능한 최단 표현을 사용하며 -0.0만
0.0으로 바꾼다. int와 float의 표현은 구별한다. 문자열은 JSON escaping을
적용하되 ASCII 이외의 유효 문자는 UTF-8로 보존하고 BOM을 붙이지 않는다.
이 규약은 일반 JSON의 임의 출력이나 RFC 8785와 동일한 규약이 아니다.
SI 정규화, hash 대상 subset 선택, snapshot 및 cache 의존성은 호출자 책임이다.
"""

import hashlib
import json
import math


CANONICAL_VERSION = "rfad.canonical/1.0"
MAX_DEPTH = 64
MAX_SAFE_INTEGER = 9_007_199_254_740_991
_HASH_PREFIX = b"rfad.canonical/1.0\n"


class CanonicalEncodingError(ValueError):
    """! @brief canonical 정책에 맞지 않는 값 또는 구조를 나타낸다."""


def canonical_bytes(value: object) -> bytes:
    """! @brief 입력을 정책 버전 1.0의 canonical JSON UTF-8 바이트로 반환한다.

    @param value 내장 JSON primitive로 구성된 입력 값.
    @return BOM, 공백 구분자와 마지막 newline이 없는 UTF-8 바이트.
    @throws CanonicalEncodingError 자료형, 숫자, 문자열, 순환 또는 깊이 오류.
    @details root의 깊이는 0이며 배열 원소와 object 값마다 1 증가한다.
    깊이 64까지 허용하고 key 자체는 추가 깊이로 계산하지 않는다.
    같은 subtree의 반복 참조는 허용하지만 ancestor로 돌아가는 순환은 거부한다.
    입력을 변경하거나 단위를 변환하지 않는다. 호출 중 입력 변경은 지원하지 않는다.
    """
    return _encode(value, 0, set()).encode("utf-8", errors="strict")


def canonical_hash(value: object) -> str:
    """! @brief 버전 prefix와 canonical 바이트의 SHA256을 반환한다.

    @param value canonical_bytes와 같은 입력 계약을 가진 값.
    @return 소문자 64자리 SHA256 hexadecimal 문자열.
    @throws CanonicalEncodingError 입력이 canonical 정책을 위반한 경우.
    @details 해시 입력은 b'rfad.canonical/1.0\\n' + canonical_bytes(value)이다.
    이 prefix는 canonical JSON payload 자체에는 포함되지 않는다.
    """
    return hashlib.sha256(_HASH_PREFIX + canonical_bytes(value)).hexdigest()


def _encode(value: object, depth: int, active_ids: set[int]) -> str:
    """! @brief 타입, 깊이와 ancestor 순환을 검사하며 JSON 토큰을 생성한다.

    @param value 현재 검사하는 값.
    @param depth root에서 현재 값까지의 깊이.
    @param active_ids 현재 경로에서 활성화된 container의 식별자 집합.
    @return 현재 값의 canonical JSON 문자열.
    @throws CanonicalEncodingError canonical 입력 계약을 위반한 경우.
    """
    if depth > MAX_DEPTH:
        raise CanonicalEncodingError("canonical 값의 최대 깊이 64를 초과했습니다.")

    value_type = type(value)
    if value is None:
        return "null"
    if value_type is bool:
        if value:
            return "true"
        return "false"
    if value_type is int:
        if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
            raise CanonicalEncodingError("정수가 허용된 53 bit 안전 범위를 벗어났습니다.")
        return str(value)
    if value_type is float:
        if not math.isfinite(value):
            raise CanonicalEncodingError("NaN과 Infinity는 canonical 숫자가 아닙니다.")
        if value == 0.0:
            return "0.0"
        return repr(value)
    if value_type is str:
        return _encode_string(value)
    if value_type is not list and value_type is not dict:
        raise CanonicalEncodingError("정확한 내장 JSON primitive만 허용합니다.")

    identity = id(value)
    if identity in active_ids:
        raise CanonicalEncodingError("canonical 입력에 순환 참조가 있습니다.")
    active_ids.add(identity)
    try:
        if value_type is list:
            items = [_encode(item, depth + 1, active_ids) for item in value]
            return "[" + ",".join(items) + "]"

        encoded_keys = {}
        for key in value:
            if type(key) is not str:
                raise CanonicalEncodingError("object key는 내장 str이어야 합니다.")
            encoded_keys[key] = _encode_string(key)

        members = []
        for key in sorted(encoded_keys):
            item = _encode(value[key], depth + 1, active_ids)
            members.append(encoded_keys[key] + ":" + item)
        return "{" + ",".join(members) + "}"
    finally:
        active_ids.remove(identity)


def _encode_string(value: str) -> str:
    """! @brief UTF-8 유효성을 확인한 뒤 고정된 JSON 문자열 escaping을 적용한다.

    @param value 정규화하거나 치환하지 않을 원문 문자열.
    @return 따옴표와 필수 escape를 포함하는 JSON 문자열 토큰.
    @throws CanonicalEncodingError surrogate code point가 포함된 경우.
    """
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise CanonicalEncodingError("문자열에 UTF-8로 인코딩할 수 없는 surrogate가 있습니다.") from error
    return json.dumps(value, ensure_ascii=False, allow_nan=False)
