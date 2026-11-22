"""! @brief RLC와 기준 임피던스 입력의 단위 해석을 GUI 대신 서비스에서 수행한다."""

from copy import deepcopy

from rfad.adapters.network_text import number
from rfad.domain.network_library import fail
from rfad.domain.units import Quantity, QuantityError

COMPONENT_DIMENSIONS = {"R": "impedance", "L": "inductance", "C": "capacitance"}
COMPONENT_UNITS = {"R": ["ohm", "kohm"], "L": ["H", "uH", "nH"], "C": ["F", "uF", "nF", "pF"]}


def input_quantity(value, dimension, field):
    """! @brief 바꾸지 않은 원본 수량은 복사하고 명시 문자열 입력만 환산한다."""
    if type(value) is not dict:
        fail("수량 또는 값/단위 입력이 필요합니다.", field)
    if set(value) == {"value_si", "dimension", "display_unit", "status", "source_refs"}:
        try:
            quantity = Quantity(**value)
        except (ValueError, TypeError, QuantityError) as error:
            fail("수량을 해석할 수 없습니다: " + str(error), field, "E_UNIT")
        if quantity.dimension.value != dimension:
            fail("소자 종류와 수량 차원이 다릅니다.", field, "E_UNIT")
        return deepcopy(value)
    if set(value) != {"text", "unit", "source_refs"} or type(value["text"]) is not str or len(value["text"]) > 128:
        fail("값 문자열/단위/출처 입력 계약이 다릅니다.", field)
    text = value["text"].strip()
    try:
        if not text:
            return Quantity(None, dimension, value["unit"], "missing", deepcopy(value["source_refs"])).to_dict()
        numeric_value = number(text, field=field)
        quantity = Quantity.from_value(numeric_value, value["unit"], source_refs=deepcopy(value["source_refs"]))
        if quantity.dimension.value != dimension:
            fail("소자 종류와 단위 차원이 다릅니다.", field, "E_UNIT")
        return quantity.to_dict()
    except (ValueError, TypeError, QuantityError) as error:
        fail("수량을 해석할 수 없습니다: " + str(error), field, "E_UNIT")


def circuit_input(definition):
    """! @brief 회로 입력의 수정된 값만 SI 수량으로 변환한다."""
    if type(definition) is not dict or type(definition.get("elements")) is not list or len(definition["elements"]) > 16:
        fail("회로 입력은 최대 16개 소자 목록이 필요합니다.", "definition")
    result = deepcopy(definition)
    for index, element in enumerate(result["elements"]):
        if type(element) is not dict or type(element.get("kind")) is not str or element["kind"] not in COMPONENT_DIMENSIONS or "value" not in element:
            fail("R/L/C 소자 입력이 유효하지 않습니다.", "definition.elements")
        element["value"] = input_quantity(element["value"], COMPONENT_DIMENSIONS[element["kind"]], f"elements.{index}.value")
    return result


def circuit_display(definition):
    """! @brief native 표에 표시할 수치 문자열과 원본 사본을 따로 제공한다."""
    result = deepcopy(definition)
    for element in result["elements"]:
        quantity = Quantity(**element["value"])
        element["value_text"] = "" if quantity.value_si is None else format(quantity.as_unit(quantity.display_unit), ".15g")
        element["value_unit"] = quantity.display_unit
        element["allowed_units"] = COMPONENT_UNITS[element["kind"]]
    return result


def transform_input(data, options):
    """! @brief 표시용 정규화 및 기준면 문자열을 명시 수치와 포트 ID로 바꾼다."""
    if type(options) is dict and set(options) == {"operation", "line_table"} and options["operation"] == "shift_plane":
        table = options["line_table"]
        if type(table) is not str or len(table) > 2048:
            fail("이동할 포트의 선로 조건을 확인하십시오.", "options.line_table")
        rows = []
        for line in table.splitlines():
            if not line.strip():
                continue
            fields = [item.strip() for item in line.split("|", 4)]
            if len(fields) != 5 or fields[0] not in {str(i) for i in range(1, len(data["port_ids"]) + 1)}:
                fail("포트 번호 | 길이(mm) | 위상 속도(m/s) | 감쇠(dB/m) | 새 기준면 순으로 입력하십시오.", "options.line_table")
            index, length, velocity, attenuation, plane = fields
            rows.append({"port_id": data["port_ids"][int(index) - 1],
                         "length_mm": number(length, field="options.line_table.length_mm"),
                         "phase_velocity_m_per_s": number(velocity, field="options.line_table.phase_velocity_m_per_s"),
                         "attenuation_db_per_m": number(attenuation, field="options.line_table.attenuation_db_per_m"),
                         "reference_plane": plane})
        return {"operation": "shift_plane", "lines": rows}
    if type(options) is dict and set(options) == {"operation", "reference"} and options["operation"] == "renormalize":
        quantity = Quantity(**input_quantity(options["reference"], "impedance", "reference"))
        if quantity.value_si is None or quantity.value_si <= 0:
            fail("정규화에는 명시한 양의 기준 임피던스가 필요합니다.", "reference", "E_UNIT")
        return {"operation": "renormalize", "z0_ohm": [[[quantity.value_si, 0.0] for _ in data["port_ids"]] for _ in data["frequency_hz"]]}
    return deepcopy(options)
