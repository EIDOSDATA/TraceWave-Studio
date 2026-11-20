"""! @brief 측정 폼의 변경 필드와 단위만 서비스에서 해석하고 원문 초안을 보존한다."""

from copy import deepcopy
import math

from rfad.adapters.network_text import number
from rfad.application.measurement_contract import fail
from rfad.application.network_forms import input_quantity
from rfad.application.project_contract import _fields
from rfad.domain.measurement import SECTIONS, EVIDENCE, bounded, validate_record, validate_uncertainty
from rfad.domain.network_data import finite, validate_dataset
from rfad.domain.units import Quantity, QuantityError

TOP_LEVEL = {"data_class", "author", "source_refs", "uncertainty", "external_processing", "attachments", "extra"}
LABELS = {
    "identifier": "시료 식별", "serial": "일련 번호", "lot": "제조 로트", "fabrication_revision": "제작 개정",
    "assembly_revision": "조립 개정", "mounting_cycle": "장착 회차", "trim_notes": "수정 이력",
    "design_snapshot": "설계 스냅샷 근거", "delivered_materials": "납품 물성 근거", "instrument": "측정 장비",
    "firmware": "펌웨어", "measured_at": "실제 측정 일시", "timezone": "시간대", "if_bandwidth_hz": "IF 대역폭",
    "averages": "평균 횟수", "stimulus_power": "측정 소스 전력", "setting_artifacts": "장비 설정 원문",
    "method": "교정 방식", "performed_at": "교정 일시", "kit_id": "교정 키트", "standard_ids": "교정 표준",
    "certificate_refs": "교정 성적서", "port_ids": "교정 포트", "frequency_range_hz": "교정 유효 대역",
    "reference_planes": "교정 기준면", "verification_notes": "교정 재확인 기록", "connector": "커넥터",
    "cable": "케이블", "fixture_id": "지그 식별", "path_notes": "실제 케이블 경로", "mounting_notes": "장착 조건",
    "included_effects": "포함 효과", "corrected_effects": "외부 보정 효과", "temperature": "온도", "humidity": "습도",
    "enclosure": "외함", "battery": "배터리", "pose": "측정 자세", "nearby_objects": "주변 물체",
    "physical_setup_snapshot": "환경 구성 근거",
}
UNITS = {"positive_number": ["Hz", "kHz", "MHz", "GHz"], "frequency_range": ["Hz", "kHz", "MHz", "GHz"],
         "frequency_value": ["Hz", "kHz", "MHz", "GHz"],
         "positive_integer": ["1"], "power": ["dBm", "W", "mW"], "temperature": ["degC", "K"], "humidity": ["%", "1"]}


def kind_for(path):
    """! @brief 입력 경로를 알려진 폼 필드에만 연결한다."""
    if type(path) is not str:
        fail("측정 필드 경로가 필요합니다.")
    if path in ("calibration.frequency_range_hz.start", "calibration.frequency_range_hz.stop",
                "uncertainty.frequency_range_hz.start", "uncertainty.frequency_range_hz.stop"):
        return "frequency_value"
    group, separator, key = path.partition(".")
    if separator and group in SECTIONS and key in SECTIONS[group]:
        return SECTIONS[group][key]
    if path.startswith("uncertainty."):
        key = path.removeprefix("uncertainty.")
        kind = {"value": "uncertainty_value", "coverage_factor": "scalar", "coverage_probability": "probability",
                "degrees_of_freedom": "scalar", "repetitions": "positive_integer", "frequency_range_hz": "frequency_range"}.get(key)
        if kind is not None:
            return kind
    fail("지원하지 않는 측정 필드 경로입니다.", field=path)


def allowed_units(path):
    """! @brief 불확도의 로그 단위는 선형 차원의 별명으로 바꾸지 않는다."""
    kind = kind_for(path)
    if kind == "uncertainty_value":
        return ["1", "%", "ohm", "S", "dB", "deg"]
    if kind in ("scalar", "probability"):
        return ["1"]
    return UNITS.get(kind, [])


def _validate_value(path, value):
    """! @brief 표시만 바꾸는 요청도 원문 수량의 타입/단위/정의역을 확인한다."""
    kind = kind_for(path)
    if value is None:
        return
    if kind in ("positive_number", "frequency_value", "positive_integer", "scalar", "probability"):
        numeric = finite(value, path)
        if (kind in ("positive_number", "scalar") and numeric <= 0
                or kind == "frequency_value" and numeric < 0
                or kind == "probability" and not 0 < numeric < 1
                or kind == "positive_integer" and (type(value) is not int or not 1 <= value <= 1_000_000)):
            fail("측정 수량의 값이 정의역 밖입니다.", "E_UNIT", path)
        return
    if kind in ("power", "temperature", "humidity", "uncertainty_value"):
        _fields(value, {"number", "unit"})
        numeric, unit = finite(value["number"], path), value["unit"]
        units = ["W", "dBm"] if kind == "power" else allowed_units(path)
        if type(unit) is not str or unit not in units:
            fail("보존 수량의 단위가 해당 필드와 다릅니다.", "E_UNIT", path)
        if (kind == "power" and unit == "W" and numeric < 0
                or kind == "temperature" and numeric < (0 if unit == "K" else -273.15)
                or kind == "humidity" and not 0 <= numeric <= (100 if unit == "%" else 1)
                or kind == "uncertainty_value" and numeric < 0):
            fail("측정 수량의 값이 정의역 밖입니다.", "E_UNIT", path)
        return
    fail("단일 수량으로 조회할 수 없는 필드입니다.", "E_UNIT", path)


def _scalar_input(path, raw):
    """! @brief 명시 숫자 문자열만 변환하며 공란은 0 대신 미정으로 유지한다."""
    _fields(raw, {"text", "unit"})
    unit, text = raw["unit"], raw["text"]
    if type(text) is not str or len(text) > 128 or unit not in allowed_units(path):
        fail("측정 수량의 문자열 또는 단위가 유효하지 않습니다.", "E_UNIT", path)
    if not text.strip():
        return None
    value = number(text.strip(), field=path)
    kind = kind_for(path)
    if kind in ("positive_number", "frequency_value"):
        result = input_quantity({"text": text, "unit": unit, "source_refs": []}, "frequency", path)["value_si"]
        _validate_value(path, result)
        return result
    if kind == "positive_integer":
        if not value.is_integer() or not 1 <= value <= 1_000_000:
            fail("횟수는 1~1000000의 정수여야 합니다.", field=path)
        return int(value)
    if kind == "probability" and not 0 < value < 1:
        fail("포함 확률은 0과 1 사이여야 합니다.", field=path)
    if kind == "scalar" and value <= 0:
        fail("불확도 계수는 양수여야 합니다.", field=path)
    if kind in ("probability", "scalar"):
        return value
    if kind == "power" and unit == "mW":
        result = value / 1000.0
        if value != 0 and result == 0:
            fail("전력 환산 값이 표현 범위를 벗어났습니다.", "E_UNIT", path)
        normalized = {"number": result, "unit": "W"}
        _validate_value(path, normalized)
        return normalized
    if kind in ("power", "temperature", "humidity", "uncertainty_value"):
        normalized = {"number": value, "unit": unit}
        _validate_value(path, normalized)
        return normalized
    fail("숫자 입력을 지원하지 않는 측정 필드입니다.", "E_UNIT", path)


def _display(path, value, unit):
    """! @brief 표시 전환은 원문 값과 사용자 선언을 변경하지 않는다."""
    if unit not in allowed_units(path):
        fail("선택한 표시 단위를 지원하지 않습니다.", "E_UNIT", path)
    _validate_value(path, value)
    if value is None:
        return ""
    kind = kind_for(path)
    try:
        if kind in ("positive_number", "frequency_value"):
            result = Quantity.from_value(value, "Hz").as_unit(unit)
            if value != 0 and result == 0:
                raise ValueError("주파수 표시 underflow")
        elif kind in ("positive_integer", "scalar", "probability"):
            result = value
        else:
            _fields(value, {"number", "unit"})
            result, source = value["number"], value["unit"]
            if source != unit:
                if kind == "power":
                    if source == "dBm":
                        result = 10.0 ** (result / 10.0 - (3.0 if unit == "W" else 0.0))
                        if result == 0:
                            raise ValueError("전력 표시 underflow")
                    else:
                        result = 10.0 * math.log10(result) + 30.0 if unit == "dBm" else result * 1000.0
                elif kind == "temperature":
                    result += 273.15 if unit == "K" else -273.15
                elif kind == "humidity" or kind == "uncertainty_value" and {source, unit} == {"1", "%"}:
                    result *= 100.0 if unit == "%" else 0.01
                    if value["number"] != 0 and result == 0:
                        raise ValueError("비율 표시 underflow")
                else:
                    fail("서로 다른 불확도 표현을 환산하지 않습니다.", "E_UNIT", path)
        if type(result) not in (int, float) or not math.isfinite(result):
            raise ValueError()
    except (ValueError, OverflowError, TypeError, QuantityError) as error:
        fail("수량 표시가 유한한 범위를 벗어났습니다: " + str(error), "E_UNIT", path)
    return format(result, ".15g")


def quantity(data):
    """! @brief 조회만으로 단위 표시를 바꾸거나 입력 문자열을 서비스에서 해석한다."""
    _fields(data, {"path", "value", "input", "display_unit"})
    path = data["path"]
    value = deepcopy(data["value"]) if data["input"] is None else _scalar_input(path, data["input"])
    return {"path": path, "value": value, "text": _display(path, value, data["display_unit"]),
            "unit": data["display_unit"], "units": allowed_units(path), "original_preserved": data["input"] is None}


def _range(raw, field):
    """! @brief 범위 양 끝의 단위는 각각 해석하고 원문은 명령에 따로 보존한다."""
    _fields(raw, {"start", "stop"})
    values = []
    for key in ("start", "stop"):
        item = raw[key]
        value = _scalar_input(field + "." + key, item) if type(item) is dict else deepcopy(item)
        _validate_value(field + "." + key, value)
        if value is None or value < 0:
            fail("주파수 범위의 양 끝을 명시하십시오.", "E_UNIT", field)
        values.append(value)
    if values[1] < values[0]:
        fail("주파수 범위의 순서가 다릅니다.", field=field)
    return values


def _uncertainties(rows):
    """! @brief 표의 바뀐 수치 문자열만 해석하고 기존 숫자/null/근거는 그대로 남긴다."""
    if type(rows) is not list or len(rows) > 32:
        fail("불확도 표는 최대 32개 항목입니다.", "E_RESOURCE")
    result = deepcopy(rows)
    for row in result:
        if type(row) is not dict:
            fail("불확도 표 항목이 객체여야 합니다.")
        for key in ("value", "coverage_factor", "coverage_probability", "degrees_of_freedom", "repetitions"):
            item = row.get(key)
            if type(item) is dict and set(item) == {"text", "unit"}:
                row[key] = _scalar_input("uncertainty." + key, item)
        scope = row.get("scope")
        if type(scope) is dict:
            band = scope.get("frequency_range_hz")
            if type(band) is dict:
                scope["frequency_range_hz"] = _range(band, "uncertainty.frequency_range_hz")
            elif type(band) is list and len(band) == 2:
                scope["frequency_range_hz"] = _range(dict(zip(("start", "stop"), band)), "uncertainty.frequency_range_hz")
        validate_uncertainty(row)
    return result


def apply_changes(record, changes):
    """! @brief 바뀐 알려진 필드만 적용해 이전 기록의 미정/extra/출처를 보전한다."""
    _fields(changes, {"values", "quantities"})
    if any(type(changes[key]) is not dict or len(changes[key]) > 128 for key in changes):
        fail("측정 변경 필드는 종류별 128개 이내의 객체입니다.", "E_RESOURCE")
    if set(changes["values"]) & set(changes["quantities"]):
        fail("같은 측정 필드를 두 가지 입력으로 변경할 수 없습니다.")
    bounded(changes, "changes")
    result = deepcopy(record)
    normalized = deepcopy(changes["values"])
    for path, raw in changes["quantities"].items():
        if path == "uncertainty":
            normalized[path] = _uncertainties(raw)
            continue
        kind = kind_for(path)
        if raw is None:
            normalized[path] = None
            continue
        fields = {"start", "stop", "evidence", "source_refs"} if kind == "frequency_range" else {"text", "unit", "evidence", "source_refs"}
        _fields(raw, fields)
        value = _range({key: raw[key] for key in ("start", "stop")}, path) if kind == "frequency_range" else _scalar_input(path, {key: raw[key] for key in ("text", "unit")})
        normalized[path] = {"value": value, "evidence": raw["evidence"], "source_refs": deepcopy(raw["source_refs"])}
    for path, value in normalized.items():
        if path in TOP_LEVEL:
            result[path] = deepcopy(value)
            continue
        if type(path) is not str:
            fail("변경할 측정 필드 경로가 필요합니다.")
        group, separator, key = path.partition(".")
        if not separator or group not in SECTIONS or key not in {*SECTIONS[group], "source_refs"}:
            fail("알려진 측정 필드만 변경할 수 있습니다.", field=path)
        if result[group] is None:
            result[group] = {**{name: None for name in SECTIONS[group]}, "source_refs": []}
        result[group][key] = deepcopy(value)
    validate_record(result)
    return result


def form(record, draft_time_utc):
    """! @brief 뷰는 필드 이름/원문과 별도의 서비스 표시 문자열만 받는다."""
    fields = []
    for group, definitions in SECTIONS.items():
        for key, kind in definitions.items():
            path = group + "." + key
            leaf = None if record is None or record[group] is None else record[group][key]
            value = None if leaf is None else leaf["value"]
            units = UNITS.get(kind, [])
            unit = value["unit"] if type(value) is dict and "unit" in value else units[0] if units else None
            if kind in ("positive_number", "frequency_range") and value is not None:
                maximum = max(value) if type(value) is list else value
                unit = "GHz" if maximum >= 1e9 else "MHz" if maximum >= 1e6 else "kHz" if maximum >= 1e3 else "Hz"
            text = _display(path, value, unit) if units and kind != "frequency_range" else "" if value is None else value if type(value) is str else None
            fields.append({"path": path, "label": LABELS[key], "kind": kind, "original": deepcopy(leaf),
                           "value": deepcopy(value), "units": units, "unit": unit, "text": text,
                           "nullable": True, "evidence_choices": list(EVIDENCE)})
            if kind == "frequency_range":
                fields[-1]["range_display"] = {endpoint: quantity({"path": path + "." + endpoint,
                    "value": None if value is None else value[index], "input": None, "display_unit": unit})
                    for index, endpoint in enumerate(("start", "stop"))}
    return {"draft_time_utc": draft_time_utc, "fields": fields,
            "default_changes": {"values": {}, "quantities": {}}, "data_classes": ["unknown", "measurement", "synthetic_fixture"]}


def alignment_input(specification, dataset):
    """! @brief 정렬 폼의 단위만 해석하며 순서/실제 보간은 도메인 계산에 맡긴다."""
    validate_dataset(dataset)
    _fields(specification, {"schema", "operations", "reason", "source_refs"})
    if specification["schema"] != "rfad.measurement-alignment-input/0.1":
        fail("지원하지 않는 정렬 입력 버전입니다.", "E_VERSION")
    operations = specification["operations"]
    if type(operations) is not list or not 1 <= len(operations) <= 3:
        fail("정렬 단계는 1~3개입니다.", "E_RESOURCE")
    result = {**deepcopy(specification), "schema": "rfad.measurement-alignment/0.1", "operations": []}
    sample_count = len(dataset["frequency_hz"])
    for item in operations:
        if type(item) is not dict:
            fail("정렬 단계가 객체여야 합니다.")
        kind = item.get("kind")
        if kind == "permute_ports":
            _fields(item, {"kind", "order"})
            result["operations"].append(deepcopy(item))
        elif kind == "renormalize":
            _fields(item, {"kind", "references"})
            if type(item["references"]) is not list or len(item["references"]) != len(dataset["port_ids"]):
                fail("현재 순서의 모든 포트에 기준 임피던스를 명시하십시오.")
            row = []
            for value in item["references"]:
                impedance = input_quantity(value, "impedance", "reference")["value_si"]
                if impedance is None or impedance <= 0:
                    fail("기준 임피던스는 양의 실수여야 합니다.", "E_UNIT")
                row.append([impedance, 0.0])
            result["operations"].append({"kind": kind, "z0_ohm": [deepcopy(row) for _ in range(sample_count)]})
        elif kind == "linear_ri":
            _fields(item, {"kind", "frequencies", "max_gap"})
            frequencies = item["frequencies"]
            if type(frequencies) is not dict:
                fail("명시 주파수 목록 또는 범위가 필요합니다.")
            if frequencies.get("mode") == "range":
                _fields(frequencies, {"mode", "start", "stop", "count"})
                count = frequencies["count"]
                if type(count) is not int or not 2 <= count <= 1001:
                    fail("범위 표본 수는 2~1001개입니다.", "E_RESOURCE")
                start, stop = [input_quantity(frequencies[key], "frequency", key)["value_si"] for key in ("start", "stop")]
                if start is None or stop is None or start < 0 or stop <= start:
                    fail("증가하는 주파수 범위의 양 끝을 명시하십시오.", "E_UNIT")
                values = [(1.0 - index / (count - 1)) * start + index / (count - 1) * stop for index in range(count)]
                values[0], values[-1] = start, stop
            elif frequencies.get("mode") == "explicit":
                _fields(frequencies, {"mode", "values"})
                if type(frequencies["values"]) is not list or not 1 <= len(frequencies["values"]) <= 1001:
                    fail("명시 표본은 1~1001개입니다.", "E_RESOURCE")
                values = [input_quantity(value, "frequency", "frequency")["value_si"] for value in frequencies["values"]]
            else:
                fail("지원하지 않는 주파수 입력 방식입니다.")
            gap = input_quantity(item["max_gap"], "frequency", "max_gap")["value_si"]
            result["operations"].append({"kind": kind, "frequency_hz": values, "max_gap_hz": gap})
            sample_count = len(values)
        else:
            fail("지원하지 않는 정렬 작업입니다.", "E_UNSUPPORTED")
    from rfad.domain.measurement_alignment import validate_alignment_specification

    return validate_alignment_specification(result, dataset)
