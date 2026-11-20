"""! @brief 수학적으로 가능한 복소 차이와 설계/제작/측정 조건 차이를 분리한다."""

from copy import deepcopy
import math

from rfad.domain.errors import ProjectError


def fail(message, code="E_SCHEMA"):
    """! @brief 순수 비교 계산이 저장소나 원본 선택 서비스를 역으로 호출하지 않는다."""
    raise ProjectError(code, message)


REASONS = {"port_count_mismatch": "포트 수가 다릅니다.", "parameter_kind_mismatch": "자료의 S/Z/Y 종류가 다릅니다.",
    "wave_definition_unknown_or_mismatch": "파 정의가 미정이거나 다릅니다.",
    "phasor_convention_unknown_or_mismatch": "시간/위상 규약이 미정이거나 다릅니다.",
    "reference_planes_unknown_or_mismatch": "포트 기준면이 미정이거나 다릅니다.",
    "port_modes_unknown_or_mismatch": "포트 모드가 미정이거나 다릅니다.",
    "current_orientation_unknown_or_mismatch": "전류 방향이 미정이거나 다릅니다.",
    "frequency_missing": "오른쪽에 같은 실제 주파수 표본이 없습니다.",
    "z0_unknown_or_mismatch": "기준 임피던스가 미정이거나 다릅니다.",
    "real_positive_z0_required": "양의 실수 기준 임피던스가 필요합니다.",
    "masked_sample": "한쪽 표본이 유효하지 않습니다.", "nonfinite_difference": "차이가 유한 수 범위를 벗어납니다."}


def compare_data(left, right, data):
    """! @brief 다른 형상 비교를 허용하되 파/기준면/포트/Z0가 미정이면 차이를 만들지 않는다."""
    row, column, offset, limit = (data[key] for key in ("row", "column", "offset", "limit"))
    count, right_count = len(left["port_ids"]), len(right["port_ids"])
    if data["frequency_policy"] != "exact_only":
        fail("비교는 실제 같은 주파수 표본만 지원합니다.", "E_UNSUPPORTED")
    if any(type(value) is not int or not 0 <= value < count for value in (row, column)):
        fail("비교 채널이 왼쪽 포트 범위를 벗어났습니다.")
    if type(offset) is not int or not 0 <= offset < len(left["frequency_hz"]) or type(limit) is not int or not 1 <= limit <= 201:
        fail("비교 표본은 유효한 시작 위치와 1~201개 크기가 필요합니다.", "E_RESOURCE")
    order = data["right_port_order"]
    if type(order) is not list or any(type(index) is not int for index in order):
        fail("오른쪽 포트 대응은 명시 정수 인덱스 목록이어야 합니다.")
    if count == right_count:
        if sorted(order) != list(range(count)):
            fail("오른쪽 포트 대응은 중복 없는 전체 포트 순서여야 합니다.")
    elif order:
        fail("포트 수가 다르면 임의 종단을 만들지 않도록 대응 목록을 비워야 합니다.")
    reasons = []
    if count != right_count:
        reasons.append("port_count_mismatch")
    if left["parameter_kind"] != right["parameter_kind"]:
        reasons.append("parameter_kind_mismatch")
    for key in ("wave_definition", "phasor_convention"):
        if left[key] == "unknown" or right[key] == "unknown" or left[key] != right[key]:
            reasons.append(key + "_unknown_or_mismatch")
    if count == right_count:
        for key in ("reference_planes", "port_modes", "current_orientation"):
            if any(left[key][index] in (None, "unknown") or left[key][index] != right[key][order[index]] for index in range(count)):
                reasons.append(key + "_unknown_or_mismatch")
    right_indices = {value: index for index, value in enumerate(right["frequency_hz"])}
    points = []
    for index in range(offset, min(offset + limit, len(left["frequency_hz"]))):
        frequency = left["frequency_hz"][index]
        right_index = right_indices.get(frequency)
        point_reasons, difference = list(reasons), None
        if right_index is None:
            point_reasons.append("frequency_missing")
        elif not reasons:
            a, b = left["z0_ohm"], right["z0_ohm"]
            if a is None or b is None or any(a[index][port] is None or a[index][port] != b[right_index][order[port]] for port in range(count)):
                point_reasons.append("z0_unknown_or_mismatch")
            elif any(value[0] <= 0 or value[1] != 0 for value in a[index]):
                point_reasons.append("real_positive_z0_required")
            if not left["valid_mask"][index][row][column] or not right["valid_mask"][right_index][order[row]][order[column]]:
                point_reasons.append("masked_sample")
            if not point_reasons:
                a = left["values_ri"][index][row][column]
                b = right["values_ri"][right_index][order[row]][order[column]]
                values = [b[part] - a[part] for part in range(2)]
                if all(math.isfinite(value) for value in values):
                    difference = values
                else:
                    point_reasons.append("nonfinite_difference")
        points.append({"frequency_hz": frequency, "left_index": index, "right_index": right_index,
                       "difference_ri": difference, "status": "comparable" if difference is not None else "not_comparable",
                       "reasons": point_reasons,
                       "reason": "같은 실제 주파수에서 비교 - 기준의 차이입니다." if not point_reasons else " ".join(REASONS[key] for key in point_reasons)})
    return {"frequency_policy": "exact_only", "channel": {"row": row, "column": column},
            "right_port_order": list(order), "parameter_kind": left["parameter_kind"], "unit": left["unit"],
            "difference_definition": "right_minus_left",
            "math_comparability": {"status": "not_comparable" if reasons else "sample_dependent", "reasons": reasons},
            "physical_comparability": {"status": "not_established", "reasons": ["independent_physical_evidence_not_assessed"]},
            "points": points, "offset": offset, "total": len(left["frequency_hz"]),
            "next_offset": offset + len(points) if offset + len(points) < len(left["frequency_hz"]) else None,
            "physics_validated": False}


def _display(value, depth=0):
    """! @brief 기본 조건 표에는 JSON 대신 원문 값 또는 상세 기록 안내를 표시한다."""
    if value is None:
        return "미정"
    if isinstance(value, str):
        return value
    if type(value) is bool:
        return "예" if value else "아니오"
    if type(value) in (int, float):
        return format(value, ".15g")
    if type(value) is list and len(value) <= 8 and depth < 2:
        return "; ".join(_display(item, depth + 1) for item in value) if value else "기록 없음"
    return "원문 조건 " + str(len(value)) + "개 (상세 보기)"


def condition_differences(left, right):
    """! @brief 기하/제작 조건 차이는 알리되 복소 차이 계산의 전제와 혼합하지 않는다."""
    result = []
    labels = {"manufacturing": "제작 조건", "fabrication": "제작 조건", "measurement": "측정 조건",
              "calibration": "교정 조건", "environment": "외부 환경", "uncertainty": "불확도",
              "absolute_power_w": "절대 입력 전력", "power_normalization": "전력 정규화"}
    def add(field, label, a, b, *, affects_math=False, unit=None, display_a=None, display_b=None):
        """! @brief 미정 두 개를 조건 확인 완료로 표시하지 않는다."""
        state = "both_unknown" if a is None and b is None else "one_unknown" if a is None or b is None else "equal" if a == b else "different"
        result.append({"field": field, "label": label, "left_display": _display(a) if display_a is None else display_a,
            "right_display": _display(b) if display_b is None else display_b,
            "left_state": "missing" if a is None else "recorded", "right_state": "missing" if b is None else "recorded",
            "unit": unit, "difference": state, "affects_math": affects_math,
            "reason": "두 자료 모두 해당 조건이 미정입니다." if state == "both_unknown" else
                      "한쪽 조건이 미정입니다." if state == "one_unknown" else
                      "기록된 조건이 같습니다. 물리 검증 완료를 뜻하지 않습니다." if state == "equal" else
                      "기록된 조건이 다릅니다. 비교 목적과 적용 범위를 확인하세요."})
    add("source_revision", "입력 개정", left["source_revision"]["label"], right["source_revision"]["label"])
    add("numerical.termination", "보존된 해석 종료 상태", left.get("numerical_details", {}).get("termination"), right.get("numerical_details", {}).get("termination"))
    add("numerical.formal_convergence", "독립 수렴 검증", None, None)
    for key, label in (("wave_definition", "파 정의"), ("phasor_convention", "위상 규약"),
                       ("reference_planes", "기준면"), ("port_modes", "포트 모드"), ("current_orientation", "전류 방향")):
        a, b = left["descriptor"][key], right["descriptor"][key]
        if type(a) is list and all(value in (None, "unknown") for value in a):
            a = None
        if type(b) is list and all(value in (None, "unknown") for value in b):
            b = None
        add(key, label, None if a == "unknown" else a, None if b == "unknown" else b, affects_math=True)
    def impedance(value):
        """! @brief 기준 임피던스는 포트별 실제 첫 표본과 주파수 의존 여부를 표시한다."""
        if value is None:
            return "미정"
        ports = ["미정" if pair is None else format(pair[0], ".15g") + ("" if pair[1] == 0 else " + j" + format(pair[1], ".15g")) + " ohm" for pair in value[0]]
        return "; ".join(ports) + (" (주파수별 값)" if any(row != value[0] for row in value[1:]) else "")
    a, b = left["dataset"]["z0_ohm"], right["dataset"]["z0_ohm"]
    add("z0_ohm", "기준 임피던스", a, b, affects_math=True, unit="ohm", display_a=impedance(a), display_b=impedance(b))
    for key, label in (("geometry", "기하 원본"), ("materials", "재료 원본"), ("parameters", "설계 변수 원본")):
        a, b = left["source_document"][key], right["source_document"][key]
        add("design." + key, label, a, b)
    add("selection_values", "선택 후보 변수", left["selection_values"], right["selection_values"])
    a, b = left["dataset"]["conditions"], right["dataset"]["conditions"]
    for key in sorted({"manufacturing", "measurement", *(a or {}), *(b or {})}):
        add("conditions." + key, labels.get(key, "조건 / " + key), None if a is None else a.get(key), None if b is None else b.get(key))
    return result


def marker(dataset, *, frequency_hz, row, column):
    """! @brief 다른 곡선에 같은 실제 주파수가 없으면 근처 값으로 대신하지 않는다."""
    from rfad.application.network_records import samples
    if type(frequency_hz) not in (int, float) or not math.isfinite(frequency_hz) or frequency_hz < 0:
        fail("마커 주파수는 유한한 0 이상의 Hz여야 합니다.")
    if any(type(value) is not int or not 0 <= value < len(dataset["port_ids"]) for value in (row, column)):
        fail("마커 채널이 포트 범위를 벗어났습니다.")
    try:
        index = dataset["frequency_hz"].index(frequency_hz)
    except ValueError:
        return {"found": False, "reason": "frequency_missing", "point": None}
    return {"found": True, "reason": None, "point": samples(dataset, index, 1, row, column)["samples"][0]}
