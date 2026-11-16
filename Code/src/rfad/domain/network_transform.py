"""! @brief 원시 네트워크를 바꾸지 않는 명시 변환과 조건 일치 검사를 제공한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_hash
from rfad.adapters import network_backend
from rfad.domain.network_data import UNITS, complex_value, fail, validate_dataset


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


def derived(data, values, masks, statuses, options, engine, *, kind=None, z0=None):
    """! @brief 입력 해시와 원래 표본 종류를 남기며 별도 결과 사본을 만든다."""
    result = deepcopy(data)
    kind = data["parameter_kind"] if kind is None else kind
    result.update(parameter_kind=kind, unit=UNITS[kind], values_ri=values, valid_mask=masks, sample_status=statuses,
                  sample_origin=["derived"] * len(values))
    if z0 is not None:
        result["z0_ohm"] = deepcopy(z0)
    operations = result["provenance"].setdefault("network_operations", [])
    if type(operations) is not list or len(operations) >= 32:
        fail("파생 연산의 출처 상한을 초과했습니다.", "provenance", "E_RESOURCE")
    operations.append({"input_hash": canonical_hash(data), "options": deepcopy(options), "engine": deepcopy(engine),
                       "source_sample_origin": list(data["sample_origin"])})
    validate_dataset(result)
    return result


def transform_dataset(data, options):
    """! @brief 명시 S/Z/Y 변환 또는 Z0 재정규화만 수행하며 주파수/기준면을 이동하지 않는다."""
    validate_dataset(data)
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
