"""! @brief EM 외부의 명시적 이상 RLC 사다리망을 별도 네트워크 파생값으로 계산한다."""

from copy import deepcopy
import math

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design import _fields, _strings, _uuid, resolve_scalar
from rfad.domain.network_data import complex_value, fail, text, validate_dataset
from rfad.domain.network_transform import derived, real_references, require_basis
from rfad.domain.units import QuantityError


SCHEMA = "rfad.ideal-rlc/0.1"
MAX_ELEMENTS = 16
DIMENSIONS = {"R": "impedance", "L": "inductance", "C": "capacitance"}


def validate_circuit(definition):
    """! @brief 값/출처/미정은 보존하며 외부 이상 소자의 한정된 토폴로지만 검증한다."""
    _fields(definition, {"schema", "name", "em_scope", "input_reference_plane", "load_reference_plane",
                         "elements", "source_refs", "assumptions"}, "circuit")
    if definition["schema"] != SCHEMA or definition["em_scope"] != "outside_em":
        fail("현재 회로는 명시적 EM 외부 이상 RLC profile만 지원합니다.", "circuit", "E_UNSUPPORTED")
    text(definition["name"], "circuit.name", limit=256)
    for field in ("input_reference_plane", "load_reference_plane"):
        text(definition[field], "circuit." + field, nullable=True)
    for field in ("source_refs", "assumptions"):
        _strings(definition[field], "circuit." + field)
    elements = definition["elements"]
    if type(elements) is not list or not 1 <= len(elements) <= MAX_ELEMENTS:
        fail("직렬/병렬 요소는 1~16개여야 합니다.", "circuit.elements", "E_RESOURCE")
    identities = set()
    for index, element in enumerate(elements):
        path = f"circuit.elements.{index}"
        _fields(element, {"id", "name", "connection", "kind", "state", "value", "source_refs"}, path)
        identity = _uuid(element["id"], path + ".id")
        if identity in identities:
            fail("회로 요소 ID가 중복됩니다.", path + ".id", "E_CONFLICT")
        identities.add(identity)
        text(element["name"], path + ".name", limit=256)
        if element["connection"] not in ("series", "shunt") or element["state"] not in ("connected", "open", "short", "dnp"):
            fail("지원하는 직렬/병렬 연결과 소자 상태가 필요합니다.", path, "E_UNSUPPORTED")
        kind = element["kind"]
        if type(kind) is not str or kind not in DIMENSIONS:
            fail("현재 이상 R/L/C만 지원합니다.", path + ".kind", "E_UNSUPPORTED")
        value = resolve_scalar({}, element["value"], DIMENSIONS[kind], path + ".value")
        if value.value_si is not None and value.value_si <= 0:
            fail("연결 소자값은 양수이며 open/short는 별도 상태로 지정하십시오.", path + ".value")
        if value.value_si is None and value.status != "missing":
            fail("미정 소자값은 missing 상태로 보존하십시오.", path + ".value")
        if value.value_si is not None:
            try:
                value.as_unit(value.display_unit)
            except QuantityError as error:
                fail("소자 표시 단위를 유한값으로 표현할 수 없습니다: " + str(error), path + ".value", "E_UNIT")
        _strings(element["source_refs"], path + ".source_refs")
    if len(canonical_bytes(definition)) > 32 * 1024:
        fail("회로 정의 32 KiB 상한을 초과했습니다.", "circuit", "E_RESOURCE")
    return definition


def _impedance(element, frequency, sign):
    """! @brief DC의 L short/C open은 큰 수 근사 없이 위상 연결 상태로 반환한다."""
    state = element["state"]
    if state != "connected":
        return ("open" if state == "dnp" else state), None
    value = element["value"]["value_si"]
    if value is None:
        fail("연결 소자의 값이 미정입니다.", "circuit.elements.value", "E_CONFLICT")
    kind = element["kind"]
    if kind == "R":
        return "finite", complex(value)
    if frequency == 0:
        return ("short" if kind == "L" else "open"), None
    angular_value = 2 * math.pi * frequency * value
    if not math.isfinite(angular_value) or angular_value == 0:
        return "nonfinite", None
    value = complex(0, sign * angular_value) if kind == "L" else complex(0, -sign / angular_value)
    if not (math.isfinite(value.real) and math.isfinite(value.imag)) or value == 0:
        return "nonfinite", None
    return "finite", value


def _sample(data, definition, index, np, skrf):
    """! @brief 동일 Z0의 2포트 요소를 부하 쪽부터 결합하고 연결 분모와 잔차를 기록한다."""
    z0 = real_references(data, index)[0]
    frequency = data["frequency_hz"][index]
    if not data["valid_mask"][index][0][0]:
        return None, {"status": "missing", "elements": []}
    reflection = complex_value(data["values_ri"][index][0][0], "values_ri")
    sign = 1 if data["phasor_convention"] == "exp(+j*omega*t)" else -1
    diagnostics = []
    for element in reversed(definition["elements"]):
        state, impedance = _impedance(element, frequency, sign)
        connection = element["connection"]
        row = {"id": element["id"], "status": state, "relative_residual": None, "condition_number": None}
        diagnostics.append(row)
        if state == "nonfinite":
            return None, {"status": "nonfinite", "elements": diagnostics}
        if state in ("open", "short"):
            if connection == "series" and state == "open":
                reflection = complex(1)
            elif connection == "shunt" and state == "short":
                reflection = complex(-1)
            continue
        try:
            with np.errstate(all="raise"):
                axis = skrf.Frequency.from_f([frequency], unit="Hz")
                if connection == "series":
                    component = skrf.circuit.Circuit.SeriesImpedance(axis, impedance, element["id"], z0=z0)
                else:
                    component = skrf.circuit.Circuit.ShuntAdmittance(axis, 1 / impedance, element["id"], z0=z0)
                scattering = component.s[0]
                if not np.all(np.isfinite(scattering)):
                    raise FloatingPointError()
                product = complex(scattering[1, 1]) * reflection
                denominator = 1 - product
                conditioning = (1 + abs(product)) / abs(denominator) if denominator != 0 else None
                row["condition_number"] = conditioning if conditioning is not None and math.isfinite(conditioning) else None
                if denominator == 0 or conditioning is None:
                    row["status"] = "singular"
                    return None, {"status": "singular", "elements": diagnostics}
                if not math.isfinite(conditioning) or conditioning >= network_backend.CONDITION_LIMIT:
                    row["status"] = "ill_conditioned"
                    return None, {"status": "ill_conditioned", "elements": diagnostics}
                load = skrf.Network(frequency=axis, s=np.array([[[reflection]]]), z0=z0, s_def="power")
                result = complex(skrf.network.cascade(component, load).s[0, 0, 0])
                expected = scattering[0, 1] * scattering[1, 0] * reflection
                residual = abs((result - scattering[0, 0]) * denominator - expected) / max(1.0, abs(expected))
                if not (math.isfinite(result.real) and math.isfinite(result.imag) and math.isfinite(residual)):
                    raise FloatingPointError()
                row["relative_residual"] = float(residual)
                if residual > network_backend.RESIDUAL_LIMIT:
                    row["status"] = "ill_conditioned"
                    return None, {"status": "ill_conditioned", "elements": diagnostics}
                row["status"] = "valid"
                reflection = result
        except (FloatingPointError, OverflowError, ZeroDivisionError, ValueError, np.linalg.LinAlgError):
            row["status"] = "nonfinite"
            return None, {"status": "nonfinite", "elements": diagnostics}
    return reflection, {"status": "valid", "elements": diagnostics}


def apply_circuit(data, definition):
    """! @brief 원본 EM/측정 자료와 소자 출처를 바꾸지 않고 외부 정합 결과만 반환한다."""
    validate_dataset(data)
    validate_circuit(definition)
    if data["parameter_kind"] != "S" or len(data["port_ids"]) != 1:
        fail("현재 외부 RLC 결합에는 1포트 S 부하가 필요합니다.", "network", "E_UNSUPPORTED")
    require_basis(data, phasor=True)
    if definition["input_reference_plane"] is None or definition["load_reference_plane"] != data["reference_planes"][0]:
        fail("회로 입출력 기준면과 부하 자료 기준면을 명시적으로 일치시키십시오.", "circuit.load_reference_plane", "E_CONFLICT")
    for element in definition["elements"]:
        if element["state"] == "connected" and element["value"]["value_si"] is None:
            fail("연결 소자의 값이 미정입니다.", "circuit.elements.value", "E_CONFLICT")
    np, _, skrf, engine = network_backend.runtime()
    values, masks, statuses, diagnostics = [], [], [], []
    for index, frequency in enumerate(data["frequency_hz"]):
        result, diagnostic = _sample(data, definition, index, np, skrf)
        valid = result is not None
        values.append([[[float(result.real), float(result.imag)]] if valid else [None]])
        masks.append([[valid]])
        statuses.append([[diagnostic["status"]]])
        diagnostics.append({"frequency_hz": frequency, **diagnostic})
    result = derived(data, values, masks, statuses,
                     {"operation": "ideal_rlc", "definition_hash": canonical_hash(definition), "definition": deepcopy(definition),
                      "field_metrics_carried": False, "actual_component_parasitics": "not_supplied"}, engine)
    result["reference_planes"] = [definition["input_reference_plane"]]
    validate_dataset(result)
    return {"dataset": result, "diagnostics": diagnostics, "engine": engine}
