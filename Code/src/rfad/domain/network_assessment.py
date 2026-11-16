"""! @brief 목표의 표본 판정, 미정 조건과 연속 대역/물리 검증을 분리한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash
from rfad.domain.design import _fields, _strings, _uuid
from rfad.domain.network_data import complex_value, fail, finite, text, validate_dataset
from rfad.domain.targets import _band, _criteria, _quantity


SCHEMA = "rfad.target-assessment/0.1"


def reflection_metrics(value):
    """! @brief 개방/완전 정합/능동 반사 상태를 Infinity JSON이나 임의 clipping 없이 표현한다."""
    magnitude = abs(value)
    if not math.isfinite(magnitude):
        return {"s11_db": None, "return_loss_db": None, "vswr": None,
                "s11_state": "nonfinite", "return_loss_state": "nonfinite", "vswr_state": "nonfinite"}
    db = None if magnitude == 0 else 20 * math.log10(magnitude)
    return {"s11_db": db, "return_loss_db": None if db is None else -db,
            "vswr": (1 + magnitude) / (1 - magnitude) if magnitude < 1 else None,
            "s11_state": "negative_infinity" if magnitude == 0 else "finite",
            "return_loss_state": "positive_infinity" if magnitude == 0 else "finite",
            "vswr_state": "positive_infinity" if magnitude == 1 else "undefined_active" if magnitude > 1 else "finite"}


def _target(target):
    """! @brief 프로젝트에서 선택한 목표의 literal 입력과 개정만 재검사한다."""
    required = {"id", "revision_id", "name", "physical_mode", "band", "port_id", "reference_impedance", "criteria", "source_refs"}
    if type(target) is not dict or set(target) not in (required, required | {"constraints"}):
        fail("평가할 목표의 필드가 다릅니다.", "target")
    for field in ("id", "revision_id"):
        _uuid(target[field], "target." + field)
    text(target["name"], "target.name", limit=256)
    if target["physical_mode"] != "radiating_rf":
        fail("지원하지 않는 목표 모드입니다.", "target.physical_mode", "E_UNSUPPORTED")
    if target["port_id"] is not None:
        _uuid(target["port_id"], "target.port_id")
    _band({}, target["band"], "target.band")
    _criteria(target["criteria"], "target.criteria")
    _quantity({}, target["reference_impedance"], "impedance", "target.reference_impedance", missing=True)
    _strings(target["source_refs"], "target.source_refs")


def _frequencies(target):
    """! @brief 승인된 표본만 생성하며 nearest와 보간으로 자료 누락을 숨기지 않는다."""
    band = target["band"]
    sampling = band["sampling"]
    if sampling["kind"] == "explicit":
        return [value["value_si"] for value in sampling["frequencies"]]
    start, end, count = band["start"]["value_si"], band["end"]["value_si"], sampling["count"]
    return [start if index == 0 else end if index == count - 1 else start + (end - start) * (index / (count - 1))
            for index in range(count)]


def _metric_values(metrics, data):
    """! @brief 효율 자료는 동일 원본 해시에 묶어 정합망 뒤의 방사 효율로 잘못 사용하지 않는다."""
    if metrics is None:
        return {}
    if len(data["port_ids"]) != 1:
        fail("현재 효율 평가는 명시 1포트 여기만 지원합니다. 다중 포트 여기 조건은 추정하지 않습니다.", "metrics", "E_UNSUPPORTED")
    _fields(metrics, {"dataset_hash", "source_refs", "physics_validated", "frequency_hz",
                      "radiation_efficiency", "total_efficiency"}, "metrics")
    if metrics["dataset_hash"] != canonical_hash(data):
        fail("효율 자료가 평가 네트워크와 다른 원본에 속합니다.", "metrics.dataset_hash", "E_HASH")
    if metrics["physics_validated"] is not False:
        fail("현재 계산 효율은 실물 물리 검증 합격으로 승격할 수 없습니다.", "metrics.physics_validated", "E_UNSUPPORTED")
    _strings(metrics["source_refs"], "metrics.source_refs")
    frequencies = metrics["frequency_hz"]
    if type(frequencies) is not list or not 1 <= len(frequencies) <= 1001:
        fail("효율 주파수 표본 상한을 초과했습니다.", "metrics.frequency_hz", "E_RESOURCE")
    previous = -1.0
    for value in frequencies:
        number = finite(value, "metrics.frequency_hz")
        if number < 0 or number <= previous:
            fail("효율 주파수는 중복 없이 증가해야 합니다.", "metrics.frequency_hz")
        previous = number
    result = {}
    for metric in ("radiation_efficiency", "total_efficiency"):
        values = metrics[metric]
        if type(values) is not list or len(values) != len(frequencies):
            fail("효율 자료의 표본 수가 다릅니다.", "metrics." + metric)
        for value in values:
            if value is not None:
                finite(value, "metrics." + metric)
        result[metric] = dict(zip(frequencies, values))
    return result


def _basis_reason(target, data, context, port, index):
    """! @brief 비교 조건이 다르면 자동 재정규화/기준면 이동 없이 미평가로 남긴다."""
    if target["port_id"] is None or context["target_port_id"] != target["port_id"]:
        return "목표 포트와 명시적 자료 포트 대응이 미정입니다."
    if context["reference_plane"] is None or data["reference_planes"][port] != context["reference_plane"]:
        return "목표 평가 기준면과 자료 기준면이 다르거나 미정입니다."
    if data["wave_definition"] == "unknown" or data["port_modes"][port] != "single_ended" or data["current_orientation"][port] != "into_dut":
        return "파 정의 또는 포트/전류 규약이 미정입니다."
    expected = target["reference_impedance"]["value_si"]
    reference = None if data["z0_ohm"] is None else data["z0_ohm"][index][port]
    if expected is None or reference is None or reference != [expected, 0.0]:
        return "목표와 자료의 양의 실수 Z0가 다르거나 미정입니다. 명시적 재정규화가 필요합니다."
    return None


def _point(metric, frequency, limit, data, port, index, reason, efficiencies):
    """! @brief 값이 없는 경우와 수치 부등식의 실패를 구분한다."""
    point = {"frequency_hz": frequency, "value": None, "value_state": "missing", "status": "not_evaluated", "reason": reason}
    if reason is not None:
        return point
    if metric == "s11_db":
        if data["parameter_kind"] != "S" or not data["valid_mask"][index][port][port]:
            point["reason"] = "유효한 S 대각 표본이 없습니다."
            return point
        measured = reflection_metrics(complex_value(data["values_ri"][index][port][port], "values_ri"))
        value, state = measured["s11_db"], measured["s11_state"]
        accepted = state == "negative_infinity" or (state == "finite" and value <= limit)
        if state not in ("negative_infinity", "finite"):
            point["reason"] = "반사계수 지표가 유한 범위를 벗어났습니다."
            return point
    else:
        value = efficiencies.get(metric, {}).get(frequency)
        state = "finite"
        if value is None or not 0 <= value <= 1:
            point["reason"] = "동일 원본의 유효한 효율 표본이 없거나 물리 범위를 벗어났습니다."
            return point
        accepted = value >= limit
    point.update(value=value, value_state=state, status="pass" if accepted else "fail", reason=None)
    return point


def _criterion(criterion, target, data, context, port, frequencies, efficiencies):
    """! @brief 표본별 통과와 범위 커버리지를 기록하며 연속 대역 합격을 생성하지 않는다."""
    metric, limit = criterion["metric"], criterion["limit"]["value"]
    indices = {value: index for index, value in enumerate(data["frequency_hz"])}
    points = []
    for frequency in frequencies:
        index = indices.get(frequency)
        reason = "목표 한계가 미정입니다." if limit is None else "요구 주파수의 정확한 표본이 없습니다." if index is None else _basis_reason(target, data, context, port, index)
        points.append(_point(metric, frequency, limit, data, port, index, reason, efficiencies))
    states = {point["status"] for point in points}
    sample_status = "fail" if "fail" in states else "pass" if states == {"pass"} else "not_evaluated"
    available = sum(point["status"] != "not_evaluated" for point in points)
    return {"metric": metric, "operator": criterion["operator"], "limit": deepcopy(criterion["limit"]),
            "status": "conditional" if sample_status == "pass" else sample_status, "sample_status": sample_status,
            "points": points, "coverage": {"required": len(points), "available": available, "missing": len(points) - available},
            "reason": "지정 표본의 판정이며 표본 사이와 실물 정확도는 검증하지 않았습니다."}


def _bandwidth(criterion, target, s11):
    """! @brief 기준 주파수를 포함하는 통과 표본 폭만 추정하며 임계 교차 주파수를 만들어내지 않는다."""
    reference = target["band"]["reference"]["value_si"]
    result = {"metric": "fractional_bandwidth", "operator": criterion["operator"], "limit": deepcopy(criterion["limit"]),
              "status": "not_evaluated", "sample_status": "not_evaluated", "points": [],
              "coverage": {"required": 0, "available": 0, "missing": 0}, "sampled_estimate": None,
              "reason": "FBW에는 명시 S11 한계, 기준 주파수와 임계 교차점의 검증이 필요합니다."}
    if reference is None or s11 is None or criterion["limit"]["value"] is None:
        return result
    points = s11["points"]
    center = next((index for index, point in enumerate(points) if point["frequency_hz"] == reference and point["status"] == "pass"), None)
    if center is None:
        return result
    left = right = center
    while left > 0 and points[left - 1]["status"] == "pass":
        left -= 1
    while right + 1 < len(points) and points[right + 1]["status"] == "pass":
        right += 1
    low, high = points[left]["frequency_hz"], points[right]["frequency_hz"]
    estimate = 2 * ((high - low) / high) / (1 + low / high) if high > 0 else None
    result["sampled_estimate"] = {"value": estimate, "unit": "1", "low_hz": low, "high_hz": high,
                                  "s11_limit_db": s11["limit"]["value"], "status": "estimated",
                                  "meets_limit_at_sampled_span": estimate is not None and estimate >= criterion["limit"]["value"]}
    result["coverage"] = deepcopy(s11["coverage"])
    return result


def evaluate_target(target, data, context, metrics=None):
    """! @brief 목표/자료/기준면을 보존한 별도 평가 기록을 반환한다."""
    _target(target)
    validate_dataset(data)
    _fields(context, {"port_id", "target_port_id", "reference_plane", "frequency_policy"}, "context")
    _uuid(context["port_id"], "context.port_id")
    if context["target_port_id"] is not None:
        _uuid(context["target_port_id"], "context.target_port_id")
    text(context["reference_plane"], "context.reference_plane", nullable=True)
    if context["frequency_policy"] != "exact_only":
        fail("목표 평가는 명시 표본의 정확한 일치만 지원합니다.", "context.frequency_policy", "E_UNSUPPORTED")
    if context["port_id"] not in data["port_ids"]:
        fail("자료에 선택한 포트가 없습니다.", "context.port_id", "E_CONFLICT")
    port = data["port_ids"].index(context["port_id"])
    frequencies = _frequencies(target)
    efficiencies = _metric_values(metrics, data)
    criteria = [_criterion(criterion, target, data, context, port, frequencies, efficiencies)
                for criterion in target["criteria"] if criterion["metric"] != "fractional_bandwidth"]
    for criterion in target["criteria"]:
        if criterion["metric"] == "fractional_bandwidth":
            criteria.append(_bandwidth(criterion, target, next((row for row in criteria if row["metric"] == "s11_db"), None)))
    states = {row["status"] for row in criteria}
    status = "fail" if "fail" in states else "conditional" if states == {"conditional"} else "not_evaluated"
    return {"schema": SCHEMA, "target_id": target["id"], "target_revision_id": target["revision_id"],
            "target_hash": canonical_hash(target), "dataset_hash": canonical_hash(data), "context": deepcopy(context),
            "status": status, "continuous_band_verified": False, "physics_validated": False, "criteria": criteria,
            "source_refs": deepcopy(target["source_refs"]), "metric_source_refs": [] if metrics is None else deepcopy(metrics["source_refs"])}
