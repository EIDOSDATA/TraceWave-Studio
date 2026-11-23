"""! @brief 봉인된 이전 풀이의 전계 변화로 다음 사용자 PCB 격자를 구성한다."""

from bisect import bisect_left, bisect_right
from copy import deepcopy
import math

from rfad.application import result_fields
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_environment import scene_extents
from rfad.application.pcb_geometry import fail
from rfad.application.pcb_local_mesh import MAX_RULES
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_projection import project_pcb
from rfad.application.pcb_solver import check_pcb_input


def cells(values, axes, coordinates, normal, position, lines, bounds, threshold):
    """! @brief 한 Yee 성분의 복소 차이가 큰 곳을 원래 격자 구간별로 찾는다."""
    peak = max((abs(complex(value)) for row in values for value in row), default=0.0)
    if not math.isfinite(peak) or any(not math.isfinite(abs(complex(value))) for row in values for value in row):
        fail("E_GEOMETRY", "전계 원문에 비유한 표본이 있습니다.", "roi")
    if peak == 0:
        return []
    chosen = {}
    for v, row in enumerate(values):
        for u, value in enumerate(row):
            for dim, (du, dv) in enumerate(((1, 0), (0, 1))):
                if v + dv >= len(values) or u + du >= len(row):
                    continue
                score = abs(complex(values[v + dv][u + du]) - complex(value)) / peak
                if score <= 0 or score < threshold:
                    continue
                axis = axes[dim]
                point = {normal: position, axes[0]: coordinates[0][u], axes[1]: coordinates[1][v]}
                left = point[axis]
                right = coordinates[dim][(u, v)[dim] + 1]
                if any(not lo - 1e-9 <= point[name] <= hi + 1e-9
                       for name, (lo, hi) in zip("xyz", bounds)):
                    continue
                # @brief staggered 전기장 중심 두 개 사이에 걸치는 실제 원 격자 셀을 모두 후보로 삼는다.
                for i in range(max(0, bisect_right(lines[axis], left) - 1),
                               min(len(lines[axis]) - 1, bisect_left(lines[axis], right))):
                    box = []
                    for name, (lo, hi) in zip("xyz", bounds):
                        nodes = lines[name]
                        index = i if name == axis else min(bisect_right(nodes, point[name]) - 1, bisect_left(nodes, hi) - 1)
                        if not 0 <= index < len(nodes) - 1:
                            break
                        box.append([max(lo, nodes[index]), min(hi, nodes[index + 1])])
                    if len(box) != 3 or any(high - low < 0.0001 for low, high in box):
                        continue
                    width = lines[axis][i + 1] - lines[axis][i]
                    target = round(width / 2, 12)
                    if not 0.001 <= target <= 5:
                        continue
                    key = (axis, i)
                    if key not in chosen or chosen[key]["relative_change"] < score:
                        chosen[key] = {"axis": axis, "source_interval": i, "bounds_mm": box,
                                       "relative_change": score, "source_cell_mm": width, "target_cell_mm": target}
    return sorted(chosen.values(), key=lambda item: (-item["relative_change"], item["axis"], item["source_interval"]))


def propose(service, resolved, parameters):
    """! @brief 원래 개정과 조건을 보존하고 메모리 예산 안에서 실제 증가한 격자를 반환한다."""
    parameters = dict(parameters)
    threshold = parameters.pop("threshold_fraction")
    limit = parameters.pop("max_rules")
    budget = parameters.pop("memory_limit_mib")
    if (type(threshold) not in (float, int) or not 0 < threshold <= 2 or type(limit) is not int or not 1 <= limit <= MAX_RULES
            or type(budget) is not int or not 128 <= budget <= 16384):
        fail("E_SCHEMA", "전계 변화 기준(0 초과~2), 최대 규칙 수(1~16), 메모리 MiB(128~16384)를 확인하십시오.", "field_refinement")
    monitor = parameters["monitor_id"]
    if monitor not in ("electric", "probe_electric"):
        fail("E_UNSUPPORTED", "격자 보완에는 기록한 전기장 E 성분이 필요합니다.", "monitor_id")
    model = result_fields._model(resolved, monitor)
    if model is None:
        fail("E_MISSING_ARTIFACT", "이 결과에 요청한 전계 원문이 없습니다.", "monitor_id")
    parameters["stride"] = 1
    axes, selection, indices = result_fields._selection(model, parameters)
    raw, reference = result_fields._read(service, resolved, model, monitor, selection)
    component = parameters["component"]
    primary = raw["primary_coordinates_mm"]
    def coordinate(axis, index):
        """! @brief 해당 성분의 원래 Yee 위치를 사용한다."""
        return result_fields._coordinate(model, primary, axis, component, index)
    positions = [[coordinate(axis, i) for i in indexes] for axis, indexes in zip(axes, indices)]
    normal = parameters["plane"]["normal_axis"]
    normalized = resolved["normalized"]
    plan = normalized["provenance"]["analysis_plan"]
    case = plan["case"]
    source = plan["source_semantics"]
    old_lines = normalized["mesh_statistics"]["lines_mm"]
    if canonical_hash(source) != plan["snapshot"]["content_hash"] or mesh_lines(case) != old_lines:
        fail("E_HASH", "현재 엔진으로 이전 풀이의 개정 또는 격자를 재현할 수 없습니다.", "source")
    settings = deepcopy(case["settings"])
    existing = settings.get("local_mesh", [])
    ranked = cells(raw["values"], axes, positions, normal, coordinate(normal, parameters["plane"]["index"]),
                   old_lines, scene_extents(case, sheet=True), threshold)
    selected = ranked[:min(limit, MAX_RULES - len(existing))]
    response = {"profile": "rfad.result-field-refinement/0.1", "source": deepcopy(resolved["source"]),
                "pin": deepcopy(resolved["pin"]), "source_ref": reference,
                "project_id": source["project_id"], "revision_id": source["revision_id"], "source_hash": canonical_hash(source),
                "selection": parameters, "threshold_fraction": threshold, "memory_limit_mib": budget,
                "source_mesh_sha256": canonical_hash(old_lines), "eligible_intervals": len(ranked),
                "source_grid_points": math.prod(len(row) for row in old_lines.values()), "physics_validated": False}
    if not selected:
        return {**response, "status": "rule_limit" if ranked else "no_eligible_change", "added_rules": []}
    additions = [{"kind": "gap", "name": f"전계 {selection['frequency_index'] + 1} {item['axis']} {item['source_interval']}",
                  "priority": 100, "bounds_mm": item["bounds_mm"], "max_cell_mm": {item["axis"]: item["target_cell_mm"]}}
                 for item in selected]
    settings["local_mesh"] = [*existing, *additions]
    check_pcb_input(source, settings)
    projected = project_pcb(source, settings)
    actual = mesh_lines(projected["case"])
    memory = projected["resource_estimate"]["estimated_memory_bytes"]
    response.update(predicted_bytes=memory, observations=selected,
                    next_grid_points=math.prod(len(row) for row in actual.values()), next_mesh_sha256=canonical_hash(actual))
    if memory > budget * 1024 ** 2:
        return {**response, "status": "memory_limit", "added_rules": []}
    if response["next_grid_points"] <= response["source_grid_points"]:
        return {**response, "status": "unchanged_mesh", "added_rules": []}
    return {**response, "status": "refined", "settings": settings, "added_rules": additions}
