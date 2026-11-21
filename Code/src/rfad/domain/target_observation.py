"""! @brief 목표의 단일 방사 관측 방향과 편파 조건을 검증한다."""

import math

from rfad.domain.design import _fail, _fields, resolve_scalar


COMPONENTS = {"total": "총 전계", "theta": "Etheta", "phi": "Ephi",
              "rhcp": "RHCP (openEMS)", "lhcp": "LHCP (openEMS)"}
FIELDS = ("frequency", "theta_deg", "phi_deg", "polarization", "minimum_gain_dbi")


def validate(target, field):
    """! @brief 명시 주파수와 원본 구면 각도 밖의 값 및 미지원 편파를 거절한다."""
    point = target.get("observation")
    if point is None and "observation" not in target:
        return
    _fields(point, set(FIELDS), field)
    frequency = point["frequency"]
    if frequency is not None:
        if type(frequency) is not dict or "value_si" not in frequency:
            _fail("E_SCHEMA", "관측 주파수는 명시 수량이 필요합니다.", field + ".frequency")
        quantity = resolve_scalar({}, frequency, "frequency", field + ".frequency")
        lo, hi = (target["band"][key]["value_si"] for key in ("start", "end"))
        if quantity.value_si is None or not lo <= quantity.value_si <= hi:
            _fail("E_SCHEMA", "관측 주파수는 목표 대역 안이어야 합니다.", field + ".frequency")
    for key in ("theta_deg", "phi_deg", "minimum_gain_dbi"):
        value = point[key]
        if value is None:
            continue
        try:
            finite = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            _fail("E_SCHEMA", "유한한 관측 값을 입력하십시오.", field + "." + key)
        if (key == "theta_deg" and not 0 <= value <= 180) or (key == "phi_deg" and not 0 <= value < 360):
            _fail("E_SCHEMA", "theta는 0~180 deg, phi는 0 이상 360 deg 미만이어야 합니다.", field + "." + key)
    component = point["polarization"]
    if component is not None and (type(component) is not str or component not in COMPONENTS):
        _fail("E_SCHEMA", "명시 편파 성분을 선택하십시오.", field + ".polarization")
