"""! @brief 유전체층/평면 도체/PTH의 독립 손실 식별과 분할 합계를 검증한다."""

import math
from bisect import bisect_left, bisect_right

from rfad.application.pcb_geometry import fail


def via_resolution(case, lines):
    """! @brief 실제 배럴 주변 Cartesian 간격과 비자성 도체 skin depth의 보수적 비를 남긴다."""
    result = []
    for via in case.get("vias", []):
        widths = []
        for axis, center in zip("xy", via["center_mm"]):
            values, radius = lines[axis], via["outer_radius_mm"]
            first = max(0, bisect_left(values, center - radius) - 1)
            last = min(len(values) - 1, bisect_right(values, center + radius))
            widths += [b - a for a, b in zip(values[first:last], values[first + 1:last + 1])]
        frequencies = []
        for frequency in case["loss_recording"]["frequency_hz"]:
            depth = 1000 / math.sqrt(math.pi * frequency * 4e-7 * math.pi * via["conductivity_s_per_m"])
            frequencies.append({"frequency_hz": frequency, "skin_depth_mm": depth,
                                "max_transverse_cell_over_skin_depth": max(widths) / depth,
                                "three_cells_per_skin_depth_condition_met": max(widths) <= depth / 3})
        result.append({"entity_id": via["id"], "conductivity_s_per_m": via["conductivity_s_per_m"],
                       "plating_thickness_mm": via["plating_thickness_mm"],
                       "transverse_cell_bounds_mm": [min(widths), max(widths)], "frequencies": frequencies,
                       "scope": "conservative_resolution_diagnostic_not_accuracy_validation", "skin_depth_loss_validated": False})
    return result


def validate_components(plan, row):
    """! @brief 비아를 sheet 합계나 유전체 합계에 중복 게시하는 결과를 차단한다."""
    case = plan["case"]
    for key, entities, total in (("via_components", case.get("vias", []), "via_loss_w_s2"),
                                 ("dielectric_components", [item for item in case["layers"] if item["role"] == "dielectric"], "dielectric_loss_w_s2")):
        components = row.get(key)
        if (type(components) is not list or len(components) != len(entities)
                or any(type(item) is not dict or set(item) != {"entity_id", "loss_w_s2"}
                       or type(item["loss_w_s2"]) not in (int, float) or not math.isfinite(item["loss_w_s2"]) for item in components)
                or {item["entity_id"] for item in components} != {item["id"] for item in entities}
                or type(row.get(total)) not in (int, float) or not math.isfinite(row[total])
                or not math.isclose(math.fsum(item["loss_w_s2"] for item in components), row[total], rel_tol=1e-10, abs_tol=0)):
            fail("E_HASH", "체적 손실의 원본 식별/재료별 합계가 다릅니다.")
    planar, via, conductor = [row.get(key) for key in ("sheet_loss_w_s2", "via_loss_w_s2", "conductor_loss_w_s2")]
    if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (planar, via, conductor))
            or not math.isclose(planar + via, conductor, rel_tol=1e-10, abs_tol=0)):
        fail("E_HASH", "평면 도체와 비아의 독립 합계가 전체 도체 손실과 다릅니다.")


def validate_audit(plan, result):
    """! @brief 새 분할의 재료 전류 대조/중복 없는 체적 합계와 비아 표본을 재확인한다."""
    integration = result.get("integration", {})
    expected_ids = {item["id"] for item in plan["case"].get("vias", [])}
    edges = integration.get("via_edge_counts", [])
    audits = integration.get("frequency_audits", [])
    rows = result["frequencies"]
    from rfad.application.pcb_mesh import mesh_lines

    if (integration.get("partition_method") != "quarter_cell_volume_and_native_sheet_override/0.1"
            or integration.get("method") != plan["case"]["loss_recording"]["method"]
            or integration.get("sheet_material_current_excluded") is not True
            or integration.get("sheet_coefficient_model") != "native_ade_overrides_ec_g_c"
            or integration.get("volume_material_averaging") != "native_quarter_cell_material_only"
            or integration.get("source_resistor_excluded") is not True or integration.get("pml_excluded") is not True
            or integration.get("via_resolution") != via_resolution(plan["case"], mesh_lines(plan["case"]))
            or len(edges) != len(expected_ids) or {item.get("entity_id") for item in edges} != expected_ids
            or any(type(item.get("count")) is not int or item["count"] <= 0 for item in edges)
            or type(audits) is not list or len(audits) != len(rows)):
        fail("E_HASH", "독립 체적 분할의 방법/비아 표본/주파수 근거가 다릅니다.")
    for row, audit in zip(rows, audits):
        values = [audit.get(key) for key in ("material_current_max_mixed_relative_error", "volume_work_w_s2", "assigned_volume_work_w_s2")]
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                or not 0 <= values[0] <= 0.005
                or not math.isclose(values[1], values[2], rel_tol=1e-10, abs_tol=1e-300)
                or not math.isclose(values[2], row["dielectric_loss_w_s2"] + row["via_loss_w_s2"], rel_tol=1e-10, abs_tol=1e-300)):
            fail("E_HASH", "독립 체적 전류/손실의 보존 근거가 다릅니다.")
