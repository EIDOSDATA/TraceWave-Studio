"""! @brief 문헌의 평면 사각 도체만 생성하고 미정 접지/적층/포트를 추가하지 않는다."""

from rfad.domain.design import _fail
from rfad.domain.template_geometry import _inside
from rfad.templates.printed_references import MONOPOLE


def _rectangle(builder, role, left, bottom, right, top):
    """! @brief 원문의 날카로운 사각 경계에 임의 round cap이나 taper를 추가하지 않는다."""
    builder.shape(role, "planar_region", outer=[builder.point(x, y) for x, y in (
        (left, bottom), (right, bottom), (right, top), (left, top))], holes=[])


def generate_printed(builder, identity):
    """! @brief 원문 치수와 사용자 기준점에서 모노폴/IFA의 편집 가능한 사각 도체를 만든다."""
    v = builder.values
    if identity == MONOPOLE:
        builder.positive("length", "width")
        left, right, bottom, top = v["offset_x"] - v["width"] / 2, v["offset_x"] + v["width"] / 2, v["offset_y"], v["offset_y"] + v["length"]
        builder.derived("mono_left", "x - w / 2", {"x": "offset_x", "w": "width"})
        builder.derived("mono_right", "x + w / 2", {"x": "offset_x", "w": "width"})
        builder.derived("mono_tip", "y + l", {"y": "offset_y", "l": "length"})
        _rectangle(builder, "radiator", "mono_left", "offset_y", "mono_right", "mono_tip")
    else:
        builder.positive("arm_length", "arm_width", "short_width", "feed_width", "inner_gap", "arm_clearance")
        if v["short_width"] + v["inner_gap"] + v["feed_width"] >= v["arm_length"]:
            _fail("E_CONNECTIVITY", "급전/단락 가지가 수평 가지의 열린 끝을 넘어갑니다.", "explicit_inputs.inner_gap")
        left, right = v["offset_x"], v["offset_x"] + v["arm_length"]
        bottom, top = v["offset_y"], v["offset_y"] + v["arm_clearance"] + v["arm_width"]
        for key, expression, bindings in (
            ("arm_right", "x + l", {"x": "offset_x", "l": "arm_length"}),
            ("arm_bottom", "y + h", {"y": "offset_y", "h": "arm_clearance"}),
            ("arm_top", "y + h + w", {"y": "offset_y", "h": "arm_clearance", "w": "arm_width"}),
            ("short_right", "x + w", {"x": "offset_x", "w": "short_width"}),
            ("feed_left", "x + t + g", {"x": "offset_x", "t": "short_width", "g": "inner_gap"}),
            ("feed_right", "x + t + g + w", {"x": "offset_x", "t": "short_width", "g": "inner_gap", "w": "feed_width"})):
            builder.derived(key, expression, bindings)
        _rectangle(builder, "radiator", "offset_x", "arm_bottom", "arm_right", "arm_top")
        _rectangle(builder, "short", "offset_x", "offset_y", "short_right", "arm_top")
        _rectangle(builder, "feed", "feed_left", "offset_y", "feed_right", "arm_top")
    for point in ((left, bottom), (right, bottom), (right, top), (left, top)):
        _inside(builder.document, point, 0, "explicit_inputs.offset_x")
