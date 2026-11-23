"""! @brief 사용자가 선택한 실제 재료를 비아 배럴 끝의 유한 길이 접합층에 배정한다."""

import math

from rfad.application.pcb_geometry import fail
from rfad.domain.design import _uuid


def validate(settings):
    """! @brief 동일 비아 끝의 중복 지정 및 비유한 두께를 거부한다."""
    if "via_junctions" not in settings:
        return
    rows = settings["via_junctions"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
        fail("E_SCHEMA", "비아 접합은 1~64개로 지정하십시오.", "settings.via_junctions")
    seen = set()
    for index, row in enumerate(rows):
        field = f"settings.via_junctions[{index}]"
        if type(row) is not dict or set(row) != {"via_id", "end", "material_id", "thickness_mm"}:
            fail("E_SCHEMA", "비아, 상하단, 재료와 접합 두께가 필요합니다.", field)
        _uuid(row["via_id"], field + ".via_id")
        _uuid(row["material_id"], field + ".material_id")
        if row["end"] not in ("lower", "upper"):
            fail("E_SCHEMA", "비아의 낮은 z 끝(lower) 또는 높은 z 끝(upper)을 지정하십시오.", field + ".end")
        if (type(row["thickness_mm"]) not in (int, float) or not math.isfinite(row["thickness_mm"])
                or not 0.0002 <= row["thickness_mm"] < 1000):
            fail("E_GEOMETRY", "유한 접합층은 0.0002 mm 이상이며 배럴 길이보다 얇아야 합니다.", field + ".thickness_mm")
        identity = (row["via_id"], row["end"])
        if identity in seen:
            fail("E_CONFLICT", "같은 비아 끝의 접합층이 중복됩니다.", field)
        seen.add(identity)


def project(settings, vias, materials):
    """! @brief 원래 배럴 외형 안에서 접합층과 남은 배럴의 길이를 확정한다."""
    by_id = {row["id"]: row for row in vias}
    for index, row in enumerate(settings.get("via_junctions", [])):
        field = f"settings.via_junctions[{index}]"
        via = by_id.get(row["via_id"])
        if via is None:
            fail("E_GEOMETRY", "현재 해석에 포함한 PTH를 선택하십시오.", field + ".via_id")
        thickness = row["thickness_mm"]
        low = via["z_min_mm"] if row["end"] == "lower" else via["z_max_mm"] - thickness
        high = low + thickness
        previous = via.setdefault("junctions", [])
        remaining = via["z_max_mm"] - via["z_min_mm"] - thickness - sum(item["thickness_mm"] for item in previous)
        if remaining < 0.0002:
            fail("E_GEOMETRY", "두 접합 사이에 해상 가능한 연속 배럴이 남아야 합니다.", field + ".thickness_mm")
        material = materials.consume(row["material_id"], field + ".material_id", conductor=True, volume=True)
        if material["conductivity_s_per_m"] <= 0:
            fail("E_MATERIAL_RANGE", "접합층의 전도도는 양수여야 합니다.", field + ".material_id")
        previous.append({"end": row["end"], "material_id": material["id"], "thickness_mm": thickness,
                         "z_min_mm": round(low, 12), "z_max_mm": round(high, 12),
                         "epsilon_r": material["epsilon_r"], "conductivity_s_per_m": material["conductivity_s_per_m"],
                         "native_property": "joint_" + row["end"] + "_" + via["id"]})
