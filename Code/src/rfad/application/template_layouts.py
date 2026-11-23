"""! @brief 사용자가 지정한 설치 직사각형에 실제 생성 가능한 원호와 IFA를 제안한다."""

from copy import deepcopy
import math

from rfad.application.interactive_route import forbidden_areas, on_layer
from rfad.application.pcb_exchange_projection import _footprint_from_loops
from rfad.domain.check_geometry import board_clearance, footprint, separation
from rfad.domain.design import _fail
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity
from rfad.domain.template_geometry import generate_geometry, validate_binding
from rfad.domain.template_seeds import goal_inputs, goal_layout_note
from rfad.templates.cards import ARC, IFA, VERSION, describe_card


def _coordinates(card, region, ground, width, gap, pitch, path):
    """! @brief 위쪽 반원 또는 직선 가지를 영역 안에서 왼쪽부터 배치한다."""
    left, bottom, right, top = region
    half = width / 2
    base = bottom + ground
    if card == ARC:
        radius = path / math.pi
        cx = (left + right) / 2
        cy = base + gap + width
        return {"center_x": cx, "center_y": cy, "radius": radius, "start_angle": 0., "sweep_angle": 180.,
                "width": width, "feed_start_x": cx + radius, "feed_start_y": base + gap,
                "feed_width": width}
    short = left + width
    feed = short + pitch
    # @brief 수평 가지가 영역을 넘으면 그 길이만큼 단락 가지 높이를 늘린다.
    rise = max(gap + 2*width, path - (right - half - short))
    return {"ground_left": left, "ground_bottom": bottom, "ground_width": right-left, "ground_height": ground,
            "radiator_start_x": short, "radiator_y": base + rise, "radiator_length": path-rise,
            "trace_width": width, "short_x": short, "short_start_y": base, "feed_x": feed,
            "feed_start_y": base + gap + half, "pad_width": width, "pad_height": width}


def _fits(document, binding, additions, region, clearance):
    """! @brief 새 도체의 해석 경계와 기존 층별 도체, 절삭 및 금지 영역 사이의 간격을 검사한다."""
    probe = {**document, "parameters": {**document["parameters"], **additions["parameters"]}}
    layer = binding["layer_id"]
    orders = {r["id"]: r["order"] for r in document["stackup"] if r["role"] == "conductor"}
    obstacles = []
    for row in document["geometry"]:
        if on_layer(row, layer, orders):
            if row["frame_id"] != binding["frame_id"]:
                _fail("E_CONFLICT", "선택 층의 기존 도체 좌표계를 먼저 확인하십시오.", "layer_id")
            obstacles.append((row, footprint(document, row)))
    forbidden = {}
    budget = [200000]
    x0, y0, x1, y1 = region
    for row in additions["geometry"]:
        shape = footprint(probe, row)
        margin, _ = board_clearance(document, shape)
        if margin < -shape.guard:
            _fail("E_GEOMETRY", "생성 도체가 실제 기판 외곽을 벗어납니다.", "region_mm")
        l, b, r, t = shape.bounds
        if min(l-x0, b-y0, x1-r, y1-t) < -shape.guard:
            _fail("E_GEOMETRY", "생성 도체가 지정한 설치 영역을 벗어납니다.", "region_mm")
        flag = {"planar_region": "copper_pours", "pad": "pads"}.get(row["kind"], "tracks")
        if flag not in forbidden:
            forbidden[flag] = [(item, _footprint_from_loops(item, loops))
                               for item, loops in forbidden_areas(document, layer, flag)]
        for item, obstacle in [*obstacles, *forbidden[flag]]:
            distance, _, _ = separation(shape, obstacle, budget)
            guard = max(shape.guard, obstacle.guard)
            if distance <= guard or distance + guard < clearance:
                _fail("E_GEOMETRY", f"기존 도체, 절삭 또는 금지 영역 {item['id']}의 간격이 부족합니다.", "clearance_mm")


def screen(document, options):
    """! @brief 동일한 목표와 설치 조건에서 두 카드의 생성 결과와 제외 사유를 반환한다."""
    region = options["region_mm"]
    fields = ("ground_height_mm", "width_mm", "feed_gap_mm", "branch_pitch_mm", "clearance_mm")
    if not isinstance(region, list) or len(region) != 4:
        _fail("E_SCHEMA", "설치 영역의 최소 X/Y와 최대 X/Y가 필요합니다.", "region_mm")
    values = [*region, *(options[key] for key in fields)]
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in values):
        _fail("E_UNIT", "설치 치수는 유한한 밀리미터 값으로 입력하십시오.", "region_mm")
    ground, width, gap, pitch, clearance = values[4:]
    if (region[2] <= region[0] or region[3] <= region[1] or min(ground, width, gap, pitch) <= 0 or clearance < 0):
        _fail("E_GEOMETRY", "양의 설치 크기, 접지 높이, 선폭, 급전 간극과 가지 간격이 필요합니다.", "region_mm")
    target = next((t for t in document["targets"] if t["id"] == options["target_id"]), None)
    if target is None:
        _fail("E_CONFLICT", "현재 개정의 설계 목표를 선택하십시오.", "target_id")
    note = goal_layout_note(document, target)
    if note is None:
        _fail("E_UNIT", "목표에서 유효한 초기 길이를 계산할 수 없습니다.", "target_id")
    path = note["candidates"][1]["size_mm"]
    result = []
    for identity, field in ((ARC, "radius"), (IFA, "radiator_length")):
        card = describe_card(identity, VERSION)
        record = {"template_id": identity, "name": card["name"]}
        try:
            validate_binding(document, options["binding"], card)
            coords = _coordinates(identity, region, ground, width, gap, pitch, path)
            descriptors = {f["key"]: f["display_unit"] for f in card["input_fields"]}
            origin = (f"설치 제안 / 목표 {target['id']} / 개정 {target['revision_id']}",
                      f"설치 영역 mm {region}, 접지 높이 {ground:g}, 선폭 {width:g}, 간극 {gap:g}, 가지 간격 {pitch:g}, 여유 {clearance:g}")
            raw = {k: Quantity.from_value(v, descriptors[k], status="estimated", source_refs=origin).to_dict()
                   for k, v in coords.items()}
            raw[field] = {"source": "target_quarter_wave"}
            inputs = goal_inputs(card, raw, [target])
            additions = generate_geometry(document, options["instance_id"], options["binding"], card, inputs)
            _fits(document, options["binding"], additions, region, clearance)
            record.update(available=True, requested_inputs=raw, display_values={k: format(v, ".15g") for k, v in coords.items()},
                          size_mm=inputs[field]["value_si"]*1000)
        except ProjectError as error:
            record.update(available=False, reason=error.message, code=error.code)
        result.append(record)
    return {"project_id": document["project_id"], "revision_id": document["revision_id"],
            "target_id": target["id"], "target_revision_id": target["revision_id"],
            "candidates": result, "conditions": deepcopy({k: options[k] for k in ("region_mm", *fields)}),
            "scope": "planar_geometry_clearance", "rf_evaluated": False}
