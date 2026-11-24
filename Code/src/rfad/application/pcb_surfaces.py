"""! @brief 명시 보조 유전체의 모델 경계, 피복과 개구를 확정한다."""

import math

from rfad.application.pcb_geometry import fail, length, polygon_contains
from rfad.domain.physical_setup import candidates
from rfad.domain.planar import decompose_region


def _rect(document, row, field):
    """! @brief 직사각형의 명시 좌표와 유한 양수 치수를 범위로 변환한다."""
    x, y, width, height = [length(document, row[key], field + "." + key, positive=key in ("width", "height"))
                           for key in ("x", "y", "width", "height")]
    return [[x, x + width], [y, y + height]]


def _overlap(first, second):
    """! @brief 면이나 모서리만 공유하는 경우는 부피 중첩에서 제외한다."""
    return all(min(b, d) > max(a, c) + 1e-9 for (a, b), (c, d) in zip(first, second))


def _contained(inner, outer):
    """! @brief 수치 반올림 오차를 제외하고 경계를 넘어가는 피복/개구를 찾는다."""
    return all(c - 1e-9 <= a < b <= d + 1e-9 for (a, b), (c, d) in zip(inner, outer))


def _fits_board(rect, board):
    """! @brief 원형 기판에서는 사각형의 각 꼭짓점을 실제 원에 대조한다."""
    if board["kind"] == "polygon":
        return polygon_contains(board["outer_mm"], _rect_points(rect), 1e-9)
    return (_contained(rect, board["bounds_mm"]) and
            (board["kind"] != "circle" or all(math.dist((x, y), board["center_mm"]) <= board["radius_mm"] + 1e-9
                                              for x in rect[0] for y in rect[1])))


def _rect_points(rect):
    """! @brief 사각형의 꼭짓점을 둘레 순서로 반환한다."""
    (x0, x1), (y0, y1) = rect
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _tiles(coverage, holes):
    """! @brief 사각 피복에서 개구를 빼고 서로 겹치지 않는 사각 타일을 만든다."""
    xs = sorted(set(coverage[0] + [x for box in holes for x in box[0]]))
    result = []
    for left, right in zip(xs, xs[1:]):
        base = coverage[1][0]
        excluded = sorted(box[1] for box in holes if box[0][0] <= left and right <= box[0][1])
        for low, high in excluded:
            if low > base + 1e-9:
                result.append([[left, right], [base, low]])
            base = high
        if coverage[1][1] > base + 1e-9:
            result.append([[left, right], [base, coverage[1][1]]])
    return result


def project_surfaces(document, case, dielectric):
    """! @brief 피복과 개구를 기존 시트 도체 및 해석 체적에 독립적으로 투영한다."""
    board = case["board"]
    step = case["settings"]["grid_mm"]
    surfaces = []
    for row in candidates(document)[0]:
        if not row["include_in_em"]:
            continue
        field = "surface." + row["id"]
        if "power_balance" in case["settings"]:
            fail("E_UNSUPPORTED", "보조 유전체는 일반 포트/방사 계산을 지원합니다.", field)
        bottom = row["side"] == "bottom"
        layer = case["layers"][0 if bottom else -1]
        offset = length(document, row["offset"], field + ".offset")
        thickness = length(document, row["thickness"], field + ".thickness", positive=True)
        physical_face = layer["z_min_mm"] + (0 if bottom else layer["thickness_mm"])
        model_face = physical_face
        if layer["role"] == "conductor":
            model_face = layer["z_min_mm"] + (layer["thickness_mm"] if bottom else 0)
        z = [model_face - offset - thickness, model_face - offset] if bottom else [model_face + offset, model_face + offset + thickness]
        physical_z = [value + physical_face - model_face for value in z]
        circle = row["coverage"] == "board" and board["kind"] == "circle"
        polygon = row["coverage"] == "board" and board["kind"] == "polygon"
        coverage = board["bounds_mm"] if row["coverage"] == "board" else _rect(document, row, field)
        if row["coverage"] == "rectangle" and not _fits_board(coverage, board):
            fail("E_GEOMETRY", "표면층의 사각 피복이 기판 외곽을 벗어났습니다.", field)
        if any(_overlap([*coverage, z], previous["bounds_mm"]) for previous in surfaces):
            fail("E_GEOMETRY", "해석에 포함한 보조층의 피복과 높이가 중첩됩니다.", field)
        openings = []
        for index, opening in enumerate(row["openings"]):
            path = f"{field}.openings[{index}]"
            box = _rect(document, opening, path)
            if (not _contained(box, coverage) or not _fits_board(box, board)
                    or any(_overlap(box, previous) for previous in openings)):
                fail("E_GEOMETRY", "표면층 개구가 피복을 벗어났거나 다른 개구와 겹칩니다.", path)
            if min(b - a for a, b in box) < step - 1e-9:
                fail("E_GEOMETRY", "개구 폭과 길이는 각각 한 격자 이상이어야 합니다.", path)
            openings.append(box)
        tiles = [] if circle or polygon else _tiles(coverage, openings)
        linear_tiles = decompose_region(board["outer_mm"], [_rect_points(box) for box in openings]) if polygon else []
        if not circle and not polygon and not tiles:
            fail("E_GEOMETRY", "피복 전체가 제거되었습니다. 마스크를 해석에서 제외하십시오.", field)
        for part in case.get("environment", {}).get("parts", []):
            for start, stop in part["boxes_mm"]:
                occupied = list(zip(start, stop))
                if _overlap(occupied, [*coverage, z]) and not any(_contained(occupied[:2], hole) for hole in openings):
                    fail("E_GEOMETRY", "설치 물체가 표면층 피복과 겹칩니다. 배치나 개구를 확인하십시오.", field)
        surfaces.append({**{key: row[key] for key in ("id", "name", "kind", "side", "material_id")}, "bounds_mm": [*coverage, z],
                         "physical_z_mm": physical_z, "openings_mm": openings, "tiles_mm": tiles,
                         "profile": "cylinder_with_air_openings" if circle else "linear_polygon_tiles" if polygon else "rectangular_tiles",
                         **({"linear_tiles_mm": linear_tiles} if polygon else {}),
                         **dielectric(row["material_id"], field + ".material_id")})
    return surfaces


def surface_label(case):
    """! @brief 표면층이 있는 개정의 피복과 개구를 비교 목록에서 구별한다."""
    rows = case.get("surface_layers", [])
    if not rows:
        return ""
    return ", ".join(row["name"] + (f" (개구 {len(row['openings_mm'])}개)" if row["openings_mm"] else " (개구 없음)")
                      for row in rows)


def native_surface_name(surface):
    """! @brief 기존 마스크 재료 식별과 보조층 재료를 구분한다."""
    return ("mask_" if surface["kind"] == "solder_mask" else "surface_") + surface["id"]
