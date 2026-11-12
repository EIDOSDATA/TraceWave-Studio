"""! @brief 목표 편집의 변경 필드만 수량으로 바꾸고 미수정 값과 출처를 보존한다."""

from copy import deepcopy
import math

from rfad.application.target_editor_fields import FREQUENCY_UNITS, QUANTITIES, explicit_lines, fields_for, quantity_at
from rfad.domain.errors import ProjectError
from rfad.domain.targets import METRICS, MAX_SAMPLES
from rfad.domain.units import Quantity, QuantityError


def fail(message, key, code="E_SCHEMA"):
    """! @brief 화면 필드 키를 유지한 구조화된 오류를 만든다."""
    raise ProjectError(code, message, details={"field_path": key})


def number(text, key, *, integer=False):
    """! @brief 문자열에서 유한 숫자만 읽으며 bool이나 암묵적인 누락값을 거부한다."""
    try:
        if type(text) is not str or not text.strip():
            raise ValueError()
        value = int(text) if integer else float(text)
        if not math.isfinite(value):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        fail("유한한 숫자를 입력하십시오.", key, "E_UNIT")
    return value


def sources(original, reason):
    """! @brief 과거 출처를 지우지 않고 이번 명시적 변경 사유를 덧붙인다."""
    return [*original, "사용자 변경 사유: " + reason]


def quantity(original, values, prefix, changed, dimension, reason):
    """! @brief 단위만 바꾼 값과 실제 수치 변경을 구분해 상태/출처를 보존한다."""
    local = {key[len(prefix) + 1:] for key in changed if key.startswith(prefix + ".")}
    if not local:
        return deepcopy(original)
    mode, unit = values[prefix + ".mode"], values[prefix + ".unit"]
    if mode not in ("value", "missing"):
        fail("직접 입력 또는 미정을 선택하십시오.", prefix + ".mode")
    if mode == "missing" and "value" in local:
        fail("미정 입력에는 숫자 변경을 함께 보낼 수 없습니다.", prefix + ".value")
    allowed = FREQUENCY_UNITS if dimension == "frequency" else ("ohm",)
    if unit not in allowed:
        fail("해당 물리량에서 지원하는 단위를 선택하십시오.", prefix + ".unit", "E_UNIT")
    try:
        if local == {"unit"}:
            return Quantity(original["value_si"], dimension, unit, original["status"], original["source_refs"]).to_dict()
        if mode == "missing":
            result = Quantity(None, dimension, unit, "missing", original["source_refs"]).to_dict()
        else:
            result = Quantity.from_value(number(values[prefix + ".value"], prefix + ".value"), unit, source_refs=original["source_refs"]).to_dict()
    except QuantityError as error:
        fail(str(error), prefix, "E_UNIT")
    if result["value_si"] == original["value_si"]:
        result["status"] = original["status"]
    else:
        result["source_refs"] = sources(original["source_refs"], reason)
    return result


def sampling(original, values, changed, reason):
    """! @brief 표본 형식 변경을 명시적으로 처리하고 같은 표본의 원래 상태를 유지한다."""
    local = {key for key in changed if key.startswith("sampling.")}
    if not local:
        return deepcopy(original)
    kind = values["sampling.kind"]
    if kind == "linear":
        if "sampling.explicit" in local:
            fail("등간격 방식에서는 명시 표본을 수정할 수 없습니다.", "sampling.explicit")
        return {"kind": kind, "count": number(values["sampling.count"], "sampling.count", integer=True)}
    if kind != "explicit":
        fail("등간격 또는 명시 표본을 선택하십시오.", "sampling.kind")
    if "sampling.count" in local:
        fail("명시 표본 방식에서는 등간격 개수를 수정할 수 없습니다.", "sampling.count")
    lines = values["sampling.explicit"]
    if type(lines) is not list or not 1 <= len(lines) <= MAX_SAMPLES:
        fail("명시 표본은 1~1001줄이어야 합니다.", "sampling.explicit", "E_RESOURCE")
    previous = original.get("frequencies", [])
    displayed = explicit_lines(original)
    frequencies = []
    for index, line in enumerate(lines):
        if type(line) is not str or len(line) > 128 or len(line.split()) != 2:
            fail("각 표본은 숫자와 단위로 입력하십시오. 예: 2400 MHz", "sampling.explicit")
        text, unit = line.split()
        if unit not in FREQUENCY_UNITS:
            fail("명시 표본은 Hz/kHz/MHz/GHz 단위를 사용하십시오.", "sampling.explicit", "E_UNIT")
        # @brief 표시 환산의 왕복 오차로 수정하지 않은 표본을 다시 수치화하지 않는다.
        unchanged_index = next((position for position, shown in enumerate(displayed) if shown == line), None)
        if unchanged_index is not None:
            frequencies.append(deepcopy(previous[unchanged_index]))
            continue
        try:
            converted = Quantity.from_value(number(text, "sampling.explicit"), unit).to_dict()
        except QuantityError as error:
            fail(str(error), "sampling.explicit", "E_UNIT")
        exact = next((item for item in previous if item["value_si"] == converted["value_si"] and item["display_unit"] == unit), None)
        same_value = next((item for item in previous if item["value_si"] == converted["value_si"]), None)
        if exact is not None:
            converted = deepcopy(exact)
        elif same_value is not None:
            converted = {**deepcopy(same_value), "display_unit": unit}
        else:
            old_sources = previous[index]["source_refs"] if index < len(previous) else []
            converted["source_refs"] = sources(old_sources, reason)
        frequencies.append(converted)
    return {"kind": kind, "frequencies": frequencies}


def criterion(original, metric, values, changed, reason):
    """! @brief 없는 목표, 명시적 미정과 숫자 목표를 서로 다른 입력으로 유지한다."""
    prefix = "criteria." + metric
    local = {key[len(prefix) + 1:] for key in changed if key.startswith(prefix + ".")}
    if not local:
        return deepcopy(original)
    mode = values[prefix + ".mode"]
    if mode not in ("absent", "missing", "value"):
        fail("목표의 지정 안 함/미정/직접 입력을 선택하십시오.", prefix + ".mode")
    if mode != "value" and "value" in local:
        fail("수치 목표를 선택한 경우에만 한계를 수정할 수 있습니다.", prefix + ".value")
    if mode == "absent":
        return None
    rule = METRICS[metric]
    value = None if mode == "missing" else number(values[prefix + ".value"], prefix + ".value")
    if original is not None and original["limit"]["value"] == value:
        return deepcopy(original)
    old_sources = [] if original is None else original["limit"]["source_refs"]
    return {"metric": metric, "operator": rule["operator"],
            "limit": {"value": value, "unit": rule["unit"], "status": "missing" if value is None else "user_entered",
                      "source_refs": sources(old_sources, reason)}}


def edited_target(document, original, changes, reason):
    """! @brief 읽기 전용 필드 변조를 차단하고 명시한 변경만 원본 복사본에 적용한다."""
    descriptors = {item["key"]: item for item in fields_for(document, original)}
    if type(changes) is not dict:
        fail("변경 필드는 object여야 합니다.", "values")
    values = {key: deepcopy(item["value"]) for key, item in descriptors.items()}
    changed = set()
    for key, value in changes.items():
        if key not in descriptors or descriptors[key]["readonly"]:
            fail("알 수 없거나 읽기 전용인 목표 필드입니다.", key if type(key) is str else "values")
        if key == "sampling.explicit":
            if type(value) is not list or len(value) > MAX_SAMPLES or any(type(line) is not str or len(line) > 128 for line in value):
                fail("명시 표본은 최대 1001개의 짧은 문자열 목록이어야 합니다.", key, "E_RESOURCE")
        elif type(value) is not str:
            fail("편집 값은 문자열이어야 합니다.", key)
        if value != values[key]:
            values[key] = deepcopy(value)
            changed.add(key)
    result = deepcopy(original)
    result["name"] = values["name"]
    for key, (_, dimension) in QUANTITIES.items():
        converted = quantity(quantity_at(original, key), values, key, changed, dimension, reason)
        if key.startswith("band."):
            result["band"][key.split(".")[1]] = converted
        else:
            result[key] = converted
    result["port_id"] = values["port_id"] or None
    result["band"]["sampling"] = sampling(original["band"]["sampling"], values, changed, reason)
    old_criteria = {item["metric"]: item for item in original["criteria"]}
    replaced = {metric: criterion(old_criteria.get(metric), metric, values, changed, reason) for metric in METRICS}
    order = [item["metric"] for item in original["criteria"]] + [metric for metric in METRICS if metric not in old_criteria]
    result["criteria"] = [replaced[metric] for metric in order if replaced[metric] is not None]
    return result
