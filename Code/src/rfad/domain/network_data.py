"""! @brief 원문 조건과 유효 mask를 보존하는 유한 복소 네트워크 자료를 정의한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_bytes
from rfad.domain.design import _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.resource_limits import MAX_NETWORK_PORTS


SCHEMA = "rfad.network-data/0.1"
MAX_PORTS = MAX_NETWORK_PORTS
MAX_SAMPLES = 1001
MAX_DATA_BYTES = 1024 * 1024
UNITS = {"S": "1", "Z": "ohm", "Y": "S"}
STATUSES = {"valid", "missing", "singular", "ill_conditioned", "unsupported", "outside_validity", "nonfinite"}
ORIGINS = {"computed", "measured", "imported", "derived", "interpolated", "unknown"}
WAVES = {"power", "pseudo", "traveling", "unknown"}
PHASORS = {"exp(+j*omega*t)", "exp(-j*omega*t)", "unknown"}
FIELDS = {"schema", "parameter_kind", "unit", "frequency_hz", "port_ids", "port_names", "values_ri",
          "valid_mask", "sample_status", "z0_ohm", "wave_definition", "phasor_convention", "reference_planes",
          "port_modes", "current_orientation", "sample_origin", "provenance", "conditions", "source_refs"}


def fail(message, field="network", code="E_SCHEMA"):
    """! @brief 자료를 보정하지 않고 문제 위치와 원인을 반환한다."""
    raise ProjectError(code, message, details={"field_path": field})


def finite(value, field):
    """! @brief bool과 비유한 값은 복소수/주파수의 숫자로 받지 않는다."""
    if type(value) not in (int, float):
        fail("유한 숫자가 필요합니다.", field)
    try:
        result = float(value)
    except OverflowError:
        fail("표현 가능한 수치 범위를 초과했습니다.", field, "E_RESOURCE")
    if not math.isfinite(result):
        fail("NaN/Infinity는 값 대신 mask와 상태로 기록하십시오.", field)
    return result


def text(value, field, *, nullable=False, limit=4096):
    """! @brief 원문 문자열을 잘라내거나 이름을 임의 생성하지 않는다."""
    if nullable and value is None:
        return
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        fail("제어 문자 없는 유한 문자열이 필요합니다.", field)
    try:
        value.encode("utf-8")
    except UnicodeError:
        fail("UTF-8로 저장할 수 없는 문자열입니다.", field)


def complex_value(value, field):
    """! @brief JSON의 실수/허수 쌍을 명시적인 복소수로 읽는다."""
    if type(value) is not list or len(value) != 2:
        fail("복소 값은 [real, imag] 두 숫자여야 합니다.", field)
    return complex(finite(value[0], field), finite(value[1], field))


def _json(value, field, depth=0):
    """! @brief 출처와 미정 조건은 유한 JSON으로만 보존한다."""
    if depth > 16:
        fail("출처/조건의 깊이 상한을 초과했습니다.", field, "E_RESOURCE")
    if value is None or type(value) is bool:
        return
    if type(value) in (int, float):
        finite(value, field)
    elif type(value) is str:
        if value:
            text(value, field)
    elif type(value) is list:
        if len(value) > MAX_SAMPLES:
            fail("출처 목록 상한을 초과했습니다.", field, "E_RESOURCE")
        for item in value:
            _json(item, field, depth + 1)
    elif type(value) is dict:
        if len(value) > 128:
            fail("출처 필드 상한을 초과했습니다.", field, "E_RESOURCE")
        for key, item in value.items():
            text(key, field, limit=256)
            _json(item, field + "." + key, depth + 1)
    else:
        fail("출처/조건은 JSON 자료여야 합니다.", field)


def validate_dataset(data):
    """! @brief 행렬 축, 파 정의, 포트와 유효 상태를 원문 무변경으로 검사한다."""
    if type(data) is not dict or set(data) != FIELDS or data["schema"] != SCHEMA:
        fail("네트워크 필드 또는 schema가 다릅니다.")
    kind = data["parameter_kind"]
    if type(kind) is not str or kind not in UNITS or data["unit"] != UNITS[kind]:
        fail("S/Z/Y 종류와 단위가 일치해야 합니다.", "parameter_kind", "E_UNIT")
    frequencies, identities = data["frequency_hz"], data["port_ids"]
    if type(frequencies) is not list or not 1 <= len(frequencies) <= MAX_SAMPLES:
        fail("표본은 1~1001개여야 합니다.", "frequency_hz", "E_RESOURCE")
    previous = -1.0
    for index, value in enumerate(frequencies):
        frequency = finite(value, f"frequency_hz.{index}")
        if frequency < 0 or frequency <= previous:
            fail("주파수는 0 이상이며 중복 없이 증가해야 합니다.", "frequency_hz")
        previous = frequency
    if type(identities) is not list or not 1 <= len(identities) <= MAX_PORTS:
        fail(f"현재 네트워크는 1~{MAX_PORTS}포트를 지원합니다.", "port_ids", "E_RESOURCE")
    for identity in identities:
        _uuid(identity, "port_ids")
    if len(set(identities)) != len(identities):
        fail("포트 ID가 중복됩니다.", "port_ids", "E_CONFLICT")
    count, ports = len(frequencies), len(identities)
    for key in ("port_names", "reference_planes", "port_modes", "current_orientation"):
        if type(data[key]) is not list or len(data[key]) != ports:
            fail("포트별 조건의 길이가 포트 수와 다릅니다.", key)
    for key in ("port_names", "reference_planes"):
        for value in data[key]:
            text(value, key, nullable=True, limit=256 if key == "port_names" else 4096)
    if any(value not in ("single_ended", "rectangular_te10", "unknown") for value in data["port_modes"]):
        fail("지원하는 포트 모드는 단일종단, 직사각 도파관 TE10 또는 미정입니다.", "port_modes", "E_UNSUPPORTED")
    if any(value not in ("into_dut", "unknown") for value in data["current_orientation"]):
        fail("전류 방향은 DUT 안쪽 또는 미정이어야 합니다.", "current_orientation")
    if (type(data["wave_definition"]) is not str or data["wave_definition"] not in WAVES
            or type(data["phasor_convention"]) is not str or data["phasor_convention"] not in PHASORS):
        fail("파 정의 또는 시간 규약이 지원 목록에 없습니다.", "wave_definition", "E_UNSUPPORTED")
    if (type(data["sample_origin"]) is not list or len(data["sample_origin"]) != count
            or any(type(value) is not str or value not in ORIGINS for value in data["sample_origin"])):
        fail("표본별 계산/측정/보간 출처가 필요합니다.", "sample_origin")
    for key in ("values_ri", "valid_mask", "sample_status"):
        if type(data[key]) is not list or len(data[key]) != count:
            fail("행렬의 주파수 축 길이가 다릅니다.", key)
        for matrix in data[key]:
            if type(matrix) is not list or len(matrix) != ports or any(type(row) is not list or len(row) != ports for row in matrix):
                fail("행렬의 포트 축 길이가 다릅니다.", key)
    for index in range(count):
        for row in range(ports):
            for column in range(ports):
                value = data["values_ri"][index][row][column]
                valid = data["valid_mask"][index][row][column]
                status = data["sample_status"][index][row][column]
                if type(valid) is not bool or type(status) is not str or status not in STATUSES or valid != (status == "valid"):
                    fail("유효 mask와 표본 상태가 다릅니다.", "sample_status")
                if valid or value is not None:
                    complex_value(value, "values_ri")
    z0 = data["z0_ohm"]
    if z0 is not None:
        if type(z0) is not list or len(z0) != count or any(type(row) is not list or len(row) != ports for row in z0):
            fail("기준 임피던스는 주파수/포트 축을 명시해야 합니다.", "z0_ohm")
        for row in z0:
            for value in row:
                if value is not None:
                    complex_value(value, "z0_ohm")
    if type(data["source_refs"]) is not list or len(data["source_refs"]) > 128:
        fail("출처 참조 목록 상한을 초과했습니다.", "source_refs", "E_RESOURCE")
    for source in data["source_refs"]:
        text(source, "source_refs")
    for key in ("provenance", "conditions"):
        if type(data[key]) is not dict and not (key == "conditions" and data[key] is None):
            fail("출처는 object, 조건은 object 또는 미정이어야 합니다.", key)
        _json(data[key], key)
        if len(canonical_bytes(data[key])) > 64 * 1024:
            fail("출처/조건 사본 64 KiB 상한을 초과했습니다.", key, "E_RESOURCE")
    if len(canonical_bytes(data)) > MAX_DATA_BYTES:
        fail("네트워크 자료 1 MiB 상한을 초과했습니다.", "network", "E_RESOURCE")
    return data


def make_dataset(*, parameter_kind, frequency_hz, port_ids, values_ri, **metadata):
    """! @brief 생략된 조건은 미정으로 두며 숫자, 기준면, 측정 여부를 만들어내지 않는다."""
    count, ports = len(frequency_hz), len(port_ids)
    data = {"schema": SCHEMA, "parameter_kind": parameter_kind, "unit": UNITS.get(parameter_kind),
            "frequency_hz": deepcopy(frequency_hz), "port_ids": list(port_ids), "port_names": [None] * ports,
            "values_ri": deepcopy(values_ri), "valid_mask": [[[True] * ports for _ in range(ports)] for _ in range(count)],
            "sample_status": [[["valid"] * ports for _ in range(ports)] for _ in range(count)], "z0_ohm": None,
            "wave_definition": "unknown", "phasor_convention": "unknown", "reference_planes": [None] * ports,
            "port_modes": ["unknown"] * ports, "current_orientation": ["unknown"] * ports,
            "sample_origin": ["unknown"] * count, "provenance": {}, "conditions": None, "source_refs": []}
    data.update(deepcopy(metadata))
    validate_dataset(data)
    return data
