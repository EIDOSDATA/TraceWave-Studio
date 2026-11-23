"""! @brief 외부 복소 표의 유한 텍스트/수치 경계와 원문 해석 출처를 공통 처리한다."""

import hashlib
import math
import re

from rfad.domain.errors import ProjectError
from rfad.domain.network_data import MAX_PORTS, MAX_SAMPLES, SCHEMA, UNITS, validate_dataset


MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_LINE_CHARS = 4096
MAX_LINES = 100000
MAX_COLUMNS = max(64, 1 + 2 * MAX_PORTS ** 2)
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
FREQUENCY_UNITS = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}


def fail(message, field="file", *, line=None, code="E_SCHEMA"):
    """! @brief 파서 위치를 보존하며 자동 수정 없이 오류를 반환한다."""
    details = {"field_path": field}
    if line is not None:
        details["line"] = line
    raise ProjectError(code, message, details=details)


def decode_text(raw):
    """! @brief 원문 bytes를 바꾸지 않고 UTF-8/BOM과 물리 행 예산을 검사한다."""
    if type(raw) is not bytes or not raw:
        fail("비어 있지 않은 파일 bytes가 필요합니다.")
    if len(raw) > MAX_FILE_BYTES:
        fail("파일 4 MiB 상한을 초과했습니다.", code="E_RESOURCE")
    try:
        value = raw.decode("utf-8-sig")
    except UnicodeError:
        fail("UTF-8로 읽을 수 없는 파일입니다.")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in value) or "\x7f" in value:
        fail("파일에 지원하지 않는 제어 문자가 있습니다.")
    lines = re.split(r"\r\n|\r|\n", value)
    if lines and not lines[-1]:
        lines.pop()
    if len(lines) > MAX_LINES:
        fail("파일의 물리 행 상한을 초과했습니다.", code="E_RESOURCE")
    for index, line in enumerate(lines, 1):
        if len(line) > MAX_LINE_CHARS:
            fail("한 행의 4096문자 상한을 초과했습니다.", line=index, code="E_RESOURCE")
    return lines, {"encoding": "utf-8", "bom": raw.startswith(b"\xef\xbb\xbf"),
                   "source_bytes": len(raw), "source_sha256": hashlib.sha256(raw).hexdigest()}


def number(token, *, line=None, field="file"):
    """! @brief 유한 십진수만 읽고 overflow와 0으로의 underflow를 거절한다."""
    if type(token) is not str or len(token) > 128 or NUMBER.fullmatch(token) is None:
        fail("유한 십진수 또는 E 지수 표기가 필요합니다.", field, line=line)
    value = float(token)
    mantissa = token.lower().split("e", 1)[0]
    if not math.isfinite(value) or (value == 0 and any(char in "123456789" for char in mantissa)):
        fail("숫자가 float64 표현 범위를 벗어납니다.", field, line=line, code="E_RESOURCE")
    return value


def complex_pair(first, second, representation, *, line=None):
    """! @brief 명시된 RI/MA/DB를 실수/허수로 바꾸며 위상 단위는 deg로 고정한다."""
    left, right = number(first, line=line), number(second, line=line)
    if representation == "RI":
        return [left, right]
    if representation == "MA" and left < 0:
        fail("크기는 0 이상이어야 합니다.", line=line)
    if representation == "DB":
        try:
            magnitude = 10.0 ** (left / 20.0)
        except OverflowError:
            fail("dB 변환 결과가 표현 범위를 벗어납니다.", line=line, code="E_RESOURCE")
        if magnitude == 0 or not math.isfinite(magnitude):
            fail("dB 변환 결과가 표현 범위를 벗어납니다.", line=line, code="E_RESOURCE")
    else:
        magnitude = left
    phase = math.radians(math.remainder(right, 360.0))
    return [magnitude * math.cos(phase), magnitude * math.sin(phase)]


def frequency(token, unit, previous, *, line=None):
    """! @brief 주파수의 단위를 한 번만 환산하고 원문 순서/중복을 검증한다."""
    if type(unit) is not str or unit.lower() not in FREQUENCY_UNITS:
        fail("주파수 단위는 Hz/kHz/MHz/GHz 중 하나여야 합니다.", "frequency_unit")
    value = number(token, line=line) * FREQUENCY_UNITS[unit.lower()]
    if not math.isfinite(value):
        fail("주파수 환산 결과가 표현 범위를 벗어납니다.", line=line, code="E_RESOURCE")
    if value < 0 or value <= previous:
        fail("주파수는 0 이상이며 중복 없이 증가해야 합니다. 정렬/중복 제거는 자동 수행하지 않습니다.", line=line)
    return value


def parsed_network(kind, frequencies, matrices, ports, metadata, *, z0=None, single_ended=False):
    """! @brief 서비스가 포트 ID를 부여하기 전의 공통 자료와 해석 근거를 반환한다."""
    count = len(frequencies)
    if not 1 <= count <= MAX_SAMPLES:
        fail("네트워크 표본은 1~1001개여야 합니다.", code="E_RESOURCE")
    data = {"schema": SCHEMA, "parameter_kind": kind, "unit": UNITS[kind],
            "frequency_hz": frequencies, "port_ids": [], "port_names": [None] * ports,
            "values_ri": matrices, "valid_mask": [[[True] * ports for _ in range(ports)] for _ in range(count)],
            "sample_status": [[["valid"] * ports for _ in range(ports)] for _ in range(count)],
            "z0_ohm": None if z0 is None else [[[value, 0.0] for value in z0] for _ in range(count)],
            "wave_definition": "unknown", "phasor_convention": "unknown", "reference_planes": [None] * ports,
            "port_modes": ["single_ended" if single_ended else "unknown"] * ports,
            "current_orientation": ["unknown"] * ports, "sample_origin": ["imported"] * count,
            "provenance": {"file_interpretation": metadata}, "conditions": None, "source_refs": []}
    return {"network": data, "port_count": ports, "source_port_names": [None] * ports, "parser_metadata": metadata}


def exportable(data):
    """! @brief 출력 불가능한 null/mask를 0이나 누락 행으로 바꾸지 않는다."""
    validate_dataset(data)
    if any(not cell for matrix in data["valid_mask"] for row in matrix for cell in row):
        fail("현재 파일 출력 profile은 모든 행렬 값이 유효한 자료만 지원합니다.", "valid_mask", code="E_UNSUPPORTED")
    return len(data["port_ids"])


def encoded(lines):
    """! @brief 고정 출력의 크기/행 상한도 가져오기와 같은 경계로 검사한다."""
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    decode_text(raw)
    return raw
