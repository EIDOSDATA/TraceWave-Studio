"""! @brief 원시 네트워크를 바꾸지 않는 명시 변환과 조건 일치 검사를 제공한다."""

import cmath
from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash
from rfad.adapters import network_backend
from rfad.domain.network_data import UNITS, complex_value, fail, finite, text, validate_dataset


def require_basis(data, *, phasor=False):
    """! @brief 모르는 파/포트/기준면 조건을 50 ohm 또는 동일 기준으로 치환하지 않는다."""
    if data["wave_definition"] == "unknown" or any(value != "single_ended" for value in data["port_modes"]):
        fail("파 정의와 단일종단 포트 모드를 명시하십시오.", "wave_definition", "E_UNSUPPORTED")
    if any(value != "into_dut" for value in data["current_orientation"]):
        fail("DUT 안쪽을 향하는 전류 규약을 명시하십시오.", "current_orientation", "E_UNSUPPORTED")
    if any(value is None for value in data["reference_planes"]):
        fail("기준면이 미정입니다. 조건을 명시적으로 확인하십시오.", "reference_planes", "E_CONFLICT")
    if phasor and data["phasor_convention"] == "unknown":
        fail("RLC 결합에는 시간/위상 부호 규약이 필요합니다.", "phasor_convention", "E_UNSUPPORTED")


def real_references(data, index):
    """! @brief R1의 양의 실수 기준 임피던스만 계산하며 복소/미정 원본은 보존한다."""
    if data["z0_ohm"] is None:
        fail("기준 임피던스가 미정입니다.", "z0_ohm", "E_CONFLICT")
    result = []
    for value in data["z0_ohm"][index]:
        if value is None:
            fail("기준 임피던스가 미정입니다.", "z0_ohm", "E_CONFLICT")
        impedance = complex_value(value, "z0_ohm")
        if impedance.imag != 0 or impedance.real <= 0:
            fail("현재 변환은 양의 실수 Z0만 지원합니다. 복소 Z0를 버리지 않습니다.", "z0_ohm", "E_UNSUPPORTED")
        result.append(impedance.real)
    return result


def derived(data, values, masks, statuses, options, engine, *, kind=None, z0=None, planes=None):
    """! @brief 입력 해시와 원래 표본 종류를 남기며 별도 결과 사본을 만든다."""
    result = deepcopy(data)
    kind = data["parameter_kind"] if kind is None else kind
    result.update(parameter_kind=kind, unit=UNITS[kind], values_ri=values, valid_mask=masks, sample_status=statuses,
                  sample_origin=["derived"] * len(values))
    if z0 is not None:
        result["z0_ohm"] = deepcopy(z0)
    if planes is not None:
        result["reference_planes"] = list(planes)
    operations = result["provenance"].setdefault("network_operations", [])
    if type(operations) is not list or len(operations) >= 32:
        fail("파생 연산의 출처 상한을 초과했습니다.", "provenance", "E_RESOURCE")
    operations.append({"input_hash": canonical_hash(data), "options": deepcopy(options), "engine": deepcopy(engine),
                       "source_sample_origin": list(data["sample_origin"])})
    validate_dataset(result)
    return result


def _shift_planes(data, options):
    """! @brief 포트별 정합 선로를 더하거나 제거하여 S 파의 기준면을 이동한다."""
    if set(options) != {"operation", "lines"} or data["parameter_kind"] != "S":
        fail("정합 선로 기준면 이동에는 S 자료와 선로 조건이 필요합니다.", "options", "E_UNSUPPORTED")
    require_basis(data)
    if data["phasor_convention"] == "unknown":
        fail("기준면을 이동하려면 시간/위상 부호 규약이 필요합니다.", "phasor_convention", "E_UNSUPPORTED")
    port_ids = data["port_ids"]
    lines = options["lines"]
    if type(lines) is not list or not 1 <= len(lines) <= len(port_ids):
        fail("이동할 포트마다 하나의 정합 선로를 지정하십시오.", "options.lines")
    planes = list(data["reference_planes"])
    delays, log_gains = [0.0] * len(planes), [0.0] * len(planes)
    used = set()
    fields = {"port_id", "length_mm", "phase_velocity_m_per_s", "attenuation_db_per_m", "reference_plane"}
    for line in lines:
        if type(line) is not dict or set(line) != fields:
            fail("포트, 길이, 전파 속도, 감쇠와 새 기준면을 입력하십시오.", "options.lines")
        identity = line["port_id"]
        if type(identity) is not str or identity not in port_ids or identity in used:
            fail("현재 자료의 서로 다른 포트를 선택하십시오.", "options.lines.port_id")
        used.add(identity)
        index = port_ids.index(identity)
        length = finite(line["length_mm"], "options.lines.length_mm") * 1e-3
        velocity = finite(line["phase_velocity_m_per_s"], "options.lines.phase_velocity_m_per_s")
        loss = finite(line["attenuation_db_per_m"], "options.lines.attenuation_db_per_m")
        new_plane = line["reference_plane"]
        text(new_plane, "options.lines.reference_plane", limit=256)
        if not length or velocity <= 0 or loss < 0 or new_plane == planes[index]:
            fail("0 아닌 길이, 양의 위상 속도, 0 이상의 감쇠와 다른 기준면 이름이 필요합니다.", "options.lines", "E_UNIT")
        delay = length / velocity
        gain = -loss * (math.log(10) / 20) * length
        if abs(delay) * max(data["frequency_hz"]) > 5e7 or abs(gain) > 300:
            fail("정합 선로의 위상 또는 감쇠가 계산 범위를 넘었습니다.", "options.lines", "E_RESOURCE")
        planes[index], delays[index], log_gains[index] = new_plane, delay, gain

    sign = -1.0 if data["phasor_convention"] == "exp(+j*omega*t)" else 1.0
    values, diagnostics = [], []
    for index, frequency in enumerate(data["frequency_hz"]):
        real_references(data, index)
        factors = [cmath.exp(complex(gain, sign * math.tau * math.remainder(frequency * delay, 1.0)))
                   for gain, delay in zip(log_gains, delays)]
        matrix = []
        for i, row in enumerate(data["values_ri"][index]):
            converted = []
            for j, sample in enumerate(row):
                if not data["valid_mask"][index][i][j]:
                    converted.append(None)
                    continue
                value = complex_value(sample, "values_ri") * (factors[i] * factors[j])
                if not (math.isfinite(value.real) and math.isfinite(value.imag)):
                    fail("정합 선로 이동 결과의 복소 크기가 표현 범위를 넘었습니다.", "values_ri", "E_RESOURCE")
                converted.append([value.real, value.imag])
            matrix.append(converted)
        values.append(matrix)
        count = sum(sum(row) for row in data["valid_mask"][index])
        diagnostics.append({"frequency_hz": frequency, "status": "valid" if count == len(planes)**2 else "missing",
                            "valid_channels": count, "operation": "shift_plane"})
    engine = {"name": "rfad.matched-line-reference", "version": "0.1", "available": True}
    evidence = {**options, "source_reference_planes": data["reference_planes"], "matched_to_port_z0": True}
    return {"dataset": derived(data, values, data["valid_mask"], data["sample_status"], evidence, engine, planes=planes),
            "diagnostics": diagnostics, "engine": engine}


def _deembed_fixtures(data, options):
    """! @brief 표시된 두 기준면의 치구를 동일 주파수의 결합 S행렬에서 제거한다."""
    if set(options) != {"operation", "left", "right", "fixture_ids"}:
        fail("왼쪽과 오른쪽 치구의 봉인 자료가 필요합니다.", "options", "E_SCHEMA")
    left, right = options["left"], options["right"]
    networks = (left, data, right)
    for item in networks:
        validate_dataset(item)
        require_basis(item)
        if item["parameter_kind"] != "S" or len(item["port_ids"]) != 2:
            fail("결합 자료와 양쪽 치구에 모두 단일종단 2포트 S 자료가 필요합니다.", "options", "E_UNSUPPORTED")
        if item["frequency_hz"] != data["frequency_hz"]:
            fail("세 자료의 주파수 축이 정확히 같아야 합니다.", "frequency_hz", "E_CONFLICT")
        if (item["phasor_convention"] == "unknown" or item["phasor_convention"] != data["phasor_convention"]
                or item["wave_definition"] != data["wave_definition"]):
            fail("세 자료의 파 정의와 시간/위상 규약이 같아야 합니다.", "options", "E_CONFLICT")
    if [left["reference_planes"][0], right["reference_planes"][1]] != data["reference_planes"]:
        fail("왼쪽 치구의 포트 1과 오른쪽 치구의 포트 2를 결합 자료의 바깥 기준면에 맞추십시오.",
             "reference_planes", "E_CONFLICT")
    planes = [left["reference_planes"][1], right["reference_planes"][0]]
    engine = network_backend.runtime()[3]
    values, masks, statuses, diagnostics = [], [], [], []
    for index, frequency in enumerate(data["frequency_hz"]):
        reference, other = real_references(data, index)
        if reference != other or any(real_references(item, index) != [reference, reference] for item in (left, right)):
            fail("각 주파수의 양의 실수 Z0가 세 자료의 모든 포트에서 같아야 합니다.", "z0_ohm", "E_CONFLICT")
        missing = [label for label, item in zip(("left", "combined", "right"), networks)
                   if not all(value for row in item["valid_mask"][index] for value in row)]
        if missing:
            result, diagnostic = None, {"status": "missing", "missing_inputs": missing}
        else:
            matrix = [[[complex_value(sample, "values_ri") for sample in row] for row in item["values_ri"][index]]
                      for item in networks]
            result, diagnostic = network_backend.remove_two_port_fixtures(*matrix)
        valid = result is not None
        values.append([[[float(value.real), float(value.imag)] for value in row] for row in result]
                      if valid else [[None, None], [None, None]])
        masks.append([[valid] * 2 for _ in range(2)])
        statuses.append([[diagnostic["status"]] * 2 for _ in range(2)])
        diagnostics.append({"frequency_hz": frequency, **diagnostic})
    evidence = {"operation": "deembed_fixtures", "fixture_ids": options["fixture_ids"],
                "fixture_sha256": {"left": canonical_hash(left), "right": canonical_hash(right)},
                "source_reference_planes": data["reference_planes"], "reference_planes": planes,
                "port_order": {"left": ["outside", "inside"], "right": ["inside", "outside"]}}
    return {"dataset": derived(data, values, masks, statuses, evidence, engine, planes=planes),
            "diagnostics": diagnostics, "engine": engine}


def transform_dataset(data, options):
    """! @brief 고정 주파수의 명시 S/Z/Y 변환, Z0 재정규화 또는 정합 선로 기준면 이동을 수행한다."""
    validate_dataset(data)
    if type(options) is dict:
        if options.get("operation") == "shift_plane":
            return _shift_planes(data, options)
        if options.get("operation") == "deembed_fixtures":
            return _deembed_fixtures(data, options)
    if type(options) is not dict or options.get("operation") not in ("convert", "renormalize"):
        fail("지원하지 않는 네트워크 변환입니다.", "options", "E_UNSUPPORTED")
    renormalize = options["operation"] == "renormalize"
    if set(options) != ({"operation", "z0_ohm"} if renormalize else {"operation", "parameter_kind"}):
        fail("변환 입력 필드가 다릅니다.", "options")
    target = "S" if renormalize else options["parameter_kind"]
    if type(target) is not str or target not in UNITS or (renormalize and data["parameter_kind"] != "S"):
        fail("Z0 재정규화 입력은 S이며 변환 종류는 S/Z/Y여야 합니다.", "options", "E_UNSUPPORTED")
    require_basis(data)
    target_data = deepcopy(data)
    if renormalize:
        target_data["z0_ohm"] = deepcopy(options["z0_ohm"])
        validate_dataset(target_data)
    values, masks, statuses, diagnostics = [], [], [], []
    ports = len(data["port_ids"])
    engine = network_backend.runtime()[3]
    for index, frequency in enumerate(data["frequency_hz"]):
        old_z0, new_z0 = real_references(data, index), real_references(target_data, index)
        matrix = data["values_ri"][index]
        if not all(value for row in data["valid_mask"][index] for value in row):
            result, diagnostic = None, {"status": "missing", "condition_number": None, "relative_residual": None}
        else:
            matrix = [[complex_value(value, "values_ri") for value in row] for row in matrix]
            result, diagnostic, _ = network_backend.convert(matrix, data["parameter_kind"], "Z" if renormalize else target, old_z0)
            if renormalize and result is not None:
                result, second, _ = network_backend.convert(result, "Z", "S", new_z0)
                diagnostic = {**second, "first_conversion": diagnostic}
        valid = result is not None
        values.append([[[float(value.real), float(value.imag)] for value in row] for row in result] if valid else [[None] * ports for _ in range(ports)])
        masks.append([[valid] * ports for _ in range(ports)])
        statuses.append([[diagnostic["status"]] * ports for _ in range(ports)])
        diagnostics.append({"frequency_hz": frequency, **diagnostic})
    return {"dataset": derived(data, values, masks, statuses, options, engine, kind=target,
                               z0=options["z0_ohm"] if renormalize else None), "diagnostics": diagnostics, "engine": engine}
