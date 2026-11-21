"""! @brief 실제 CSXCAD에 솔더마스크와 개구를 만들고 재료 점유를 확인한다."""

from rfad.domain.errors import ProjectError
from rfad.application.pcb_surfaces import native_surface_name


def add_surfaces(csx, case):
    """! @brief 사각 타일 또는 원형 피복 및 개구를 원본 ID로 등록한다."""
    records = []
    for surface in case.get("surface_layers", []):
        identity = surface["id"]
        name = native_surface_name(surface)
        mask = csx.AddMaterial(name, epsilon=surface["epsilon_r"], kappa=surface["kappa_s_per_m"])
        low, high = surface["bounds_mm"][2]
        z_mid = (low + high) / 2
        openings = surface["openings_mm"]
        def add_box(prop, rect, priority):
            """! @brief 피복 z 범위를 사용해 동일한 직사각 체적을 만든다."""
            (x0, x1), (y0, y1) = rect
            prop.AddBox(start=[x0, y0, low], stop=[x1, y1, high], priority=priority)

        if surface["profile"] == "rectangular_tiles":
            for tile in surface["tiles_mm"]:
                add_box(mask, tile, 2)
            witness = [(a + b) / 2 for a, b in surface["tiles_mm"][0]]
        elif surface["profile"] == "linear_polygon_tiles":
            import numpy as np

            linear_tiles = surface["linear_tiles_mm"]
            for tile in linear_tiles:
                mask.AddLinPoly(np.asarray(tile).T, norm_dir=2, elevation=low, length=high-low, priority=2)
            witness = list(np.mean(linear_tiles[0], axis=0))
        else:
            board = case["board"]
            cx, cy = board["center_mm"]
            rim = cy + board["radius_mm"]
            mask.AddCylinder(start=[cx, cy, low], stop=[cx, cy, high], radius=board["radius_mm"], priority=2)
            if openings:
                opening_name = "mask_opening_" + identity if surface["kind"] == "solder_mask" else name + "_opening"
                air = csx.AddMaterial(opening_name, epsilon=1.0, kappa=0.0)
                for hole in openings:
                    add_box(air, hole, 3)
            witness = [cx, (rim + max((hole[1][1] for hole in openings), default=cy)) / 2]

        def sampled(at):
            """! @brief 경계가 아닌 내부 위치의 실제 재료 우선순위를 읽는다."""
            prop = csx.GetPropertyByCoordPriority([*at, z_mid], prop_type=0x002)
            return prop.GetName() if prop is not None else None

        observed = [sampled([(a + b) / 2 for a, b in hole]) for hole in openings]
        if sampled(witness) != name or name in observed:
            raise ProjectError("E_GEOMETRY", "native 표면층 피복 또는 개구 재료가 계획과 다릅니다.",
                               details={"field_path": "surface." + identity})
        records.append({"id": identity, "native_property": name, "profile": surface["profile"],
                        "covered_point_checked": True, "openings_checked": len(observed)})
    return records
