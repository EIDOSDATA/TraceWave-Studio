"""! @brief 문헌 원호/stub의 원래 연결 방식과 사용자 배치를 명시 기하로 연결한다."""

import math

from rfad.domain.design import _fail
from rfad.domain.template_geometry import _inside, validate_arc_envelope


def generate_g031(builder) -> None:
    """! @brief G031의 두 D10 stroke만 생성하며 stub을 원호 시작점에 붙이지 않는다."""
    v = builder.values
    builder.positive("radius", "width", "feed_width")
    if v["radius"] <= v["width"] / 2 or not 0 < v["sweep_angle"] < math.tau:
        _fail("E_GEOMETRY", "G031은 양의 inner radius와 0/360도 사이 CCW 전개각이 필요합니다.", "explicit_inputs.sweep_angle")
    cx, cy = v["center_x"] + v["offset_x"], v["center_y"] + v["offset_y"]
    start, sweep, radius = v["start_angle"], v["sweep_angle"], v["radius"]
    validate_arc_envelope(builder.document, cx, cy, radius, start, sweep, v["width"])
    a = (v["feed_start_x"] + v["offset_x"], v["feed_start_y"] + v["offset_y"])
    b = (v["feed_end_x"] + v["offset_x"], v["feed_end_y"] + v["offset_y"])
    length2 = sum((b[index] - a[index]) ** 2 for index in (0, 1))
    if length2 <= 1e-24:
        _fail("E_GEOMETRY", "G031 stub의 시작과 끝이 같습니다.", "explicit_inputs.feed_end_x")
    for point in (a, b):
        _inside(builder.document, point, v["feed_width"] / 2, "explicit_inputs.feed_start_x")
    end = (cx + radius * math.cos(start + sweep), cy + radius * math.sin(start + sweep))
    fraction = max(0.0, min(1.0, sum((end[i] - a[i]) * (b[i] - a[i]) for i in (0, 1)) / length2))
    distance = math.dist(end, tuple(a[i] + fraction * (b[i] - a[i]) for i in (0, 1)))
    if distance > (v["width"] + v["feed_width"]) / 2:
        _fail("E_CONNECTIVITY", "stub 폭과 원호 끝의 도체가 겹치지 않습니다. 원문 연결을 임의 보정하지 않습니다.", "explicit_inputs.feed_start_x")
    for key in ("center_x", "center_y", "feed_start_x", "feed_start_y", "feed_end_x", "feed_end_y"):
        builder.derived("placed_" + key, "a + b", {"a": key, "b": "offset_" + key[-1]})
    builder.shape("radiator", "arc_path", center=builder.point("placed_center_x", "placed_center_y"),
                  radius=builder.ref("radius"), start_angle=builder.ref("start_angle"),
                  sweep_angle=builder.ref("sweep_angle"), width=builder.ref("width"))
    builder.line("feed", ("placed_feed_start_x", "placed_feed_start_y"),
                 ("placed_feed_end_x", "placed_feed_end_y"), "feed_width")
