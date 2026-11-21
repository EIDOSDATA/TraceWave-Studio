"""! @brief openEMS 기판 내부의 관통 공기 영역을 원본 절삭과 연결한다."""

import math

from rfad.domain.errors import ProjectError


def add_voids(csx, case):
    """! @brief 원형, 직선 슬롯과 내부 다각형의 중앙 공기 점유를 실제 재료에서 확인한다."""
    import numpy as np

    report = []
    for row in case.get("mechanical_voids", []):
        identity = row["id"]
        name = "mechanical_void_" + identity
        air = csx.AddMaterial(name, epsilon=1.0, kappa=0.0)
        lo, hi = row["z_mm"]
        if row["kind"] == "polygon":
            air.AddLinPoly(np.asarray(row["outline_mm"]).T, norm_dir=2, elevation=lo, length=hi-lo, priority=4)
        else:
            centers = [row["witness_mm"]]
            if row["kind"] == "capsule":
                start, stop = centers = [row["start_mm"], row["stop_mm"]]
                dx, dy = (b - a for a, b in zip(start, stop))
                scale = row["radius_mm"] / math.hypot(dx, dy)
                nx, ny = -dy * scale, dx * scale
                vertices = [[start[0] + nx, start[1] + ny], [start[0] - nx, start[1] - ny],
                            [stop[0] - nx, stop[1] - ny], [stop[0] + nx, stop[1] + ny]]
                air.AddLinPoly(np.asarray(vertices).T, norm_dir=2, elevation=lo, length=hi-lo, priority=4)
            for center in centers:
                air.AddCylinder(start=[*center, lo], stop=[*center, hi], radius=row["radius_mm"], priority=4)
        prop = csx.GetPropertyByCoordPriority([*row["witness_mm"], (lo + hi) / 2], prop_type=0x002)
        if prop is None or prop.GetName() != name:
            raise ProjectError("E_GEOMETRY", "native PCB 절삭 중앙에서 공기 재료를 확인할 수 없습니다.",
                               details={"field_path": "pcb.mechanical." + identity})
        report.append({"id": identity, "kind": row["kind"], "native_property": name, "vacuum_point_checked": True})
    return report
