"""! @brief 실행 가능한 표현식 없이 유한한 KiCad S 식 원문을 읽고 쓴다."""
import math
import re

from rfad.domain.errors import ProjectError

MAX_BYTES = 16 * 1024 * 1024
MAX_NODES = 200000


class Atom(str):
    """! @brief 따옴표 문자열과 문법 토큰을 구분한다."""


def parse(raw):
    """! @brief 깊이/바이트/노드 상한 안의 단일 식만 읽는다."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        raise ProjectError("E_RESOURCE", "KiCad 원문은 비어 있지 않은 16 MiB 이하 바이트여야 합니다.")
    try:
        source = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError as error:
        raise ProjectError("E_SCHEMA", "KiCad 원문은 UTF-8이어야 합니다.") from error
    stack, root, position, count = [], None, 0, 0
    while position < len(source):
        char = source[position]
        if char.isspace():
            position += 1
            continue
        if char == ";":
            end = source.find("\n", position)
            position = len(source) if end < 0 else end + 1
            continue
        if char == "(":
            value = []
            if stack:
                stack[-1].append(value)
            elif root is not None:
                raise ProjectError("E_SCHEMA", "KiCad 원문에 최상위 식이 둘 이상 있습니다.")
            else:
                root = value
            stack.append(value)
            if len(stack) > 64:
                raise ProjectError("E_RESOURCE", "KiCad 식의 깊이가 64를 초과했습니다.")
            position += 1
        elif char == ")":
            if not stack or not stack[-1]:
                raise ProjectError("E_SCHEMA", "KiCad 괄호 또는 빈 식이 유효하지 않습니다.")
            stack.pop()
            position += 1
        else:
            if not stack:
                raise ProjectError("E_SCHEMA", "KiCad 식 밖에 토큰이 있습니다.")
            if char == '"':
                position += 1
                token = []
                while position < len(source) and source[position] != '"':
                    char = source[position]
                    if char == "\\":
                        position += 1
                        if position >= len(source) or source[position] not in ('"', "\\", "n", "r", "t"):
                            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 KiCad 문자열 escape입니다.")
                        char = {"n": "\n", "r": "\r", "t": "\t"}.get(source[position], source[position])
                    token.append(char)
                    position += 1
                    if len(token) > 8192:
                        raise ProjectError("E_RESOURCE", "KiCad 문자열이 8192자를 초과했습니다.")
                if position >= len(source):
                    raise ProjectError("E_SCHEMA", "KiCad 문자열이 닫히지 않았습니다.")
                position += 1
                value = "".join(token)
            else:
                start = position
                while position < len(source) and not source[position].isspace() and source[position] not in "();\"":
                    position += 1
                if position == start or position - start > 8192:
                    raise ProjectError("E_SCHEMA", "KiCad 토큰이 유효하지 않습니다.")
                value = Atom(source[start:position])
            stack[-1].append(value)
        count += 1
        if count > MAX_NODES:
            raise ProjectError("E_RESOURCE", "KiCad 토큰 수가 유한 상한을 초과했습니다.")
    if stack or root is None:
        raise ProjectError("E_SCHEMA", "KiCad 식이 닫히지 않았습니다.")
    return root


def children(node, name):
    """! @brief 직접 자식만 조회하여 중첩 소유권을 혼동하지 않는다."""
    return [child for child in node[1:] if type(child) is list and child and child[0] == name]


def one(node, name, required=True):
    """! @brief 단일 필드의 중복을 암묵적으로 덮어쓰지 않는다."""
    values = children(node, name)
    if len(values) > 1 or (required and not values):
        raise ProjectError("E_SCHEMA", "KiCad 단일 필드의 개수가 다릅니다: " + name)
    return values[0] if values else None


def number(value):
    """! @brief 문법 숫자와 유한 좌표 상한을 검사한다."""
    if not isinstance(value, str) or not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        raise ProjectError("E_SCHEMA", "KiCad 숫자 문법이 유효하지 않습니다.")
    result = float(value)
    if not math.isfinite(result) or abs(result) > 1e6:
        raise ProjectError("E_RESOURCE", "KiCad 수치가 유한 상한을 벗어났습니다.")
    return result


def quote(value):
    """! @brief 원문 문자열을 KiCad escape로만 표현한다."""
    if type(value) is not str or len(value) > 8192 or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ProjectError("E_SCHEMA", "출력 문자열이 유효하지 않습니다.")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"'


def decimal(value):
    """! @brief mm 수치를 1 nm 격자로 명시 양자화한다."""
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
        raise ProjectError("E_RESOURCE", "출력 좌표가 유한 상한을 벗어났습니다.")
    result = format(value, ".6f").rstrip("0").rstrip(".")
    return "0" if result in ("", "-0") else result
