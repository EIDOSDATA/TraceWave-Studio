"""! @brief 명시적 사용자 PCB와 단일 급전의 제한된 openEMS 해석 계획을 만든다.

@details 물성을 추정하지 않는다. 원형 기판은 실제 원으로 유지하고 도체의 native
polygon 근사, 외측 동박 sheet 변환과 중심 주파수 손실 근사를 계획에 기록한다.
"""

from copy import deepcopy
import math
import re
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_contacts import validate_native_contacts
from rfad.application.pcb_mesh import graded_axis, policy_report, validate_policy
from rfad.application.solver import _snapshot, _runtime, _uuid
from rfad.domain.design import material_input_fields, resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.planar import decompose_region, validate_region
from rfad.domain.project import validate_project


PROFILE = "rfad.openems.pcb-single-port/0.1"
RAW_NAMES = ("port_ut_1", "port_it_1", "openEMS_stats.txt", "openEMS_run_stats.txt", "native.log", "pcb.xml")
EPSILON0 = 8.8541878128e-12
MAX_GRID_POINTS = 1500000
MAX_POLYGON_POINTS = 8192


def fail(code, message, field=""):
    """! @brief 원본 입력 위치를 포함한 구조화된 거절 사유를 만든다."""
    raise ProjectError(code, message, details={"field_path": field})


def scalar(document, value, dimension, field, *, positive=False, nonnegative=False):
    """! @brief 미정값을 대체하지 않고 유한 SI 수량만 소비한다."""
    quantity = resolve_scalar(document, value, dimension, field)
    number = quantity.value_si
    if number is None:
        fail("E_MATERIAL_UNKNOWN" if dimension in ("conductivity", "dimensionless") else "E_GEOMETRY", "해석 필수 입력이 미정입니다.", field)
    if not math.isfinite(number) or (positive and number <= 0) or (nonnegative and number < 0):
        fail("E_SCHEMA", "해석 입력의 수치 범위가 유효하지 않습니다.", field)
    return number


def length(document, value, field, *, positive=False):
    """! @brief mm 출력 범위를 검사하고 원본 Quantity는 변경하지 않는다."""
    result = scalar(document, value, "length", field, positive=positive) * 1000.0
    if abs(result) > 1000 or (positive and result < 1e-4):
        fail("E_GEOMETRY", "PCB 해석의 좌표 또는 최소 치수 범위를 벗어났습니다.", field)
    # @brief 0두께 sheet와 격자선을 동일한 mm 표현 정밀도로 맞추고 원본 Quantity는 보존한다.
    return round(result, 12)


def point(document, values, field):
    """! @brief 원본 좌표를 mm로 평가한다."""
    return [length(document, value, field + f"[{i}]") for i, value in enumerate(values)]


def validate_settings(settings):
    """! @brief 공개 설정을 명시적이고 유한한 범위로 한정한다."""
    keys = {"frequency_hz", "grid_mm", "air_padding_mm", "curve_tolerance_mm", "max_timesteps", "end_criterion"}
    if type(settings) is not dict or set(settings) not in (keys, keys | {"mesh_policy"}):
        fail("E_SCHEMA", "PCB 해석 설정의 필수 필드가 다릅니다.", "settings")
    frequency = settings["frequency_hz"]
    if type(frequency) is not dict or set(frequency) != {"start", "stop", "count"}:
        fail("E_SCHEMA", "주파수 시작/끝/표본 수가 필요합니다.", "settings.frequency_hz")
    for key in ("start", "stop"):
        if type(frequency[key]) not in (int, float) or not 1e6 <= frequency[key] <= 50e9:
            fail("E_SCHEMA", "지원 주파수 범위는 1 MHz~50 GHz입니다.", "settings.frequency_hz." + key)
    if not frequency["start"] < frequency["stop"] <= frequency["start"] * 2:
        fail("E_UNSUPPORTED", "상수 손실 근사는 stop/start가 2 이하인 대역을 지원합니다.", "settings.frequency_hz")
    if type(frequency["count"]) is not int or not 3 <= frequency["count"] <= 201:
        fail("E_RESOURCE", "주파수 표본 수는 3~201개입니다.", "settings.frequency_hz.count")
    for key, low, high in (("grid_mm", 0.05, 5.0), ("air_padding_mm", 1.0, 200.0), ("curve_tolerance_mm", 0.001, 0.25), ("end_criterion", 1e-9, 1e-3)):
        value = settings[key]
        if type(value) not in (int, float) or not low <= value <= high:
            fail("E_RESOURCE", "PCB 수치 설정의 지원 범위를 벗어났습니다.", "settings." + key)
    if settings["air_padding_mm"] < 10 * settings["grid_mm"] or settings["curve_tolerance_mm"] > settings["grid_mm"] / 2:
        fail("E_GEOMETRY", "공기 여백은 격자의 10배 이상, 곡선 근사 오차는 격자의 절반 이하여야 합니다.", "settings")
    if type(settings["max_timesteps"]) is not int or not 1000 <= settings["max_timesteps"] <= 200000:
        fail("E_RESOURCE", "최대 time step은 1000~200000입니다.", "settings.max_timesteps")
    if "mesh_policy" in settings:
        validate_policy(settings)


def _angles(start, sweep, radius, tolerance):
    """! @brief 원의 chord sagitta가 지정 오차 이내가 되는 각도 표본을 만든다."""
    angle = 2 * math.acos(max(-1.0, min(1.0, 1 - tolerance / radius)))
    count = max(1, math.ceil(abs(sweep) / min(angle, math.pi / 8)))
    if math.isclose(abs(sweep), math.pi, abs_tol=1e-12) and count % 2:
        count += 1
    if count > MAX_POLYGON_POINTS:
        fail("E_RESOURCE", "곡선의 native polygon 분할 수가 상한을 넘습니다.", "settings.curve_tolerance_mm")
    return [start + sweep * i / count for i in range(count + 1)]


def shape_polygons(shape, tolerance):
    """! @brief 원형 끝단을 포함한 선/원호를 오차가 제한된 polygon으로 투영한다."""
    if shape["kind"] == "planar_region":
        return decompose_region(shape["outer_mm"], shape["holes_mm"])
    if shape["kind"] == "pad":
        cx, cy = shape["center_mm"]
        if shape["pad_shape"] == "circle":
            radius = shape["size_mm"][0] / 2
            angles = _angles(0, 2 * math.pi, radius, tolerance)
            return [[[cx + radius * math.cos(t), cy + radius * math.sin(t)] for t in angles[:-1]]]
        half_x, half_y = (size / 2 for size in shape["size_mm"])
        angle = math.radians(shape["rotation_deg"])
        return [[[cx + x * math.cos(angle) - y * math.sin(angle), cy + x * math.sin(angle) + y * math.cos(angle)]
                 for x, y in ((-half_x, -half_y), (half_x, -half_y), (half_x, half_y), (-half_x, half_y))]]
    width = shape["width_mm"]
    half = width / 2
    if shape["kind"] == "line_path":
        a, b = shape["start_mm"], shape["end_mm"]
        direction = math.atan2(b[1] - a[1], b[0] - a[0])
        result = [[b[0] + half * math.cos(t), b[1] + half * math.sin(t)] for t in _angles(direction - math.pi / 2, math.pi, half, tolerance)]
        result += [[a[0] + half * math.cos(t), a[1] + half * math.sin(t)] for t in _angles(direction + math.pi / 2, math.pi, half, tolerance)]
        return [result]
    cx, cy = shape["center_mm"]
    radius, start, sweep = shape["radius_mm"], math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
    inner, outer = radius - half, radius + half
    def arc(r, a, d):
        return [[cx + r * math.cos(t), cy + r * math.sin(t)] for t in _angles(a, d, r, tolerance)]
    if abs(sweep) >= 2 * math.pi - 1e-12:
        sign = 1 if sweep > 0 else -1
        return [arc(outer, start + index * sign * math.pi / 2, sign * math.pi / 2) + arc(inner, start + (index + 1) * sign * math.pi / 2, -sign * math.pi / 2) for index in range(4)]
    sign = 1 if sweep > 0 else -1
    end = start + sweep
    ex, ey = cx + radius * math.cos(end), cy + radius * math.sin(end)
    sx, sy = cx + radius * math.cos(start), cy + radius * math.sin(start)
    return [arc(outer, start, sweep)
            + [[ex + half * math.cos(t), ey + half * math.sin(t)] for t in _angles(end, sign * math.pi, half, tolerance)][1:]
            + arc(inner, end, -sweep)[1:]
            + [[sx + half * math.cos(t), sy + half * math.sin(t)] for t in _angles(start + sign * math.pi, sign * math.pi, half, tolerance)][1:]]


def distance_to_shape(position, shape):
    """! @brief 원형 끝단을 포함한 analytic 중심선까지의 거리를 반환한다."""
    if shape["kind"] == "line_path":
        a, b = shape["start_mm"], shape["end_mm"]
        delta = [b[i] - a[i] for i in range(2)]
        t = max(0, min(1, sum((position[i] - a[i]) * delta[i] for i in range(2)) / sum(v * v for v in delta)))
        return math.dist(position, [a[i] + t * delta[i] for i in range(2)])
    center, radius = shape["center_mm"], shape["radius_mm"]
    start, sweep = math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
    angle = math.atan2(position[1] - center[1], position[0] - center[0])
    delta = ((angle - start) * (1 if sweep > 0 else -1)) % (2 * math.pi)
    if delta <= abs(sweep) + 1e-12:
        return abs(math.dist(position, center) - radius)
    return min(math.dist(position, [center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)]) for a in (start, start + sweep))


def _bounds(shape):
    """! @brief analytic 도체 중심선의 축 극값과 round cap 외곽을 구한다."""
    if shape["kind"] == "planar_region":
        return [[min(p[i] for p in shape["outer_mm"]), max(p[i] for p in shape["outer_mm"])] for i in range(2)]
    if shape["kind"] == "pad":
        if shape["pad_shape"] == "circle":
            radius = shape["size_mm"][0] / 2
            return [[c - radius, c + radius] for c in shape["center_mm"]]
        points = shape_polygons(shape, 0.01)[0]
        return [[min(p[i] for p in points), max(p[i] for p in points)] for i in range(2)]
    half = shape["width_mm"] / 2
    if shape["kind"] == "line_path":
        points = [shape["start_mm"], shape["end_mm"]]
    else:
        start, sweep = math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
        angles = [start, start + sweep]
        for a in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
            if ((a - start) * (1 if sweep > 0 else -1)) % (2 * math.pi) <= abs(sweep) + 1e-12:
                angles.append(a)
        points = [[shape["center_mm"][0] + shape["radius_mm"] * math.cos(a), shape["center_mm"][1] + shape["radius_mm"] * math.sin(a)] for a in angles]
    return [[min(p[i] for p in points) - half, max(p[i] for p in points) + half] for i in range(2)]


def _inside_board(board, shape):
    """! @brief polygon 표본 대신 analytic 중심선 극값으로 원/직사각 외곽을 검사한다."""
    if board["kind"] == "rectangle":
        bounds = _bounds(shape)
        return all(bounds[i][0] >= -1e-9 and bounds[i][1] <= board["dimensions_mm"][i] + 1e-9 for i in range(2))
    center = board["center_mm"]
    if shape["kind"] in ("planar_region", "pad"):
        if shape["kind"] == "pad" and shape["pad_shape"] == "circle":
            return math.dist(center, shape["center_mm"]) + shape["size_mm"][0] / 2 <= board["radius_mm"] + 1e-9
        points = shape["outer_mm"] if shape["kind"] == "planar_region" else shape_polygons(shape, 0.01)[0]
        return all(math.dist(center, p) <= board["radius_mm"] + 1e-9 for p in points)
    if shape["kind"] == "line_path":
        maximum = max(math.dist(center, p) for p in (shape["start_mm"], shape["end_mm"]))
    else:
        sc = shape["center_mm"]
        start, sweep = math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
        angles = [start, start + sweep]
        far = math.atan2(sc[1] - center[1], sc[0] - center[0])
        if ((far - start) * (1 if sweep > 0 else -1)) % (2 * math.pi) <= abs(sweep) + 1e-12:
            angles.append(far)
        maximum = max(math.dist(center, [sc[0] + shape["radius_mm"] * math.cos(a), sc[1] + shape["radius_mm"] * math.sin(a)]) for a in angles)
    return maximum + shape["width_mm"] / 2 <= board["radius_mm"] + 1e-9


def mesh_lines(case):
    """! @brief 외곽과 유전체 경계/port gap을 보존하는 제한된 Cartesian 격자를 만든다."""
    board, settings = case["board"], case["settings"]
    bounds = board["bounds_mm"]
    z = [v for layer in case["layers"] for v in (layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"])]
    dielectric = [layer for layer in case["layers"] if layer["role"] == "dielectric"]
    # @brief 동박은 sheet이므로 동박 두께를 별도 Yee 간격으로 강제하지 않는다.
    critical = [[bounds[i][0], bounds[i][1]] for i in range(2)] + [[v for layer in dielectric for v in (layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"])]]
    for shape in case["shapes"]:
        for axis, extent in enumerate(_bounds(shape)):
            critical[axis].extend(extent)
        critical[2].append(shape["sheet_z_mm"])
        if shape["kind"] == "planar_region":
            for loop in [shape["outer_mm"], *shape["holes_mm"]]:
                for axis in range(2):
                    critical[axis].extend(p[axis] for p in loop)
                    critical[axis].append((min(p[axis] for p in loop) + max(p[axis] for p in loop)) / 2)
        elif shape["kind"] == "pad":
            for axis in range(2):
                critical[axis].append(shape["center_mm"][axis])
    for via in case.get("vias", []):
        # @brief 얇은 실제 배럴을 임의로 굵게 만들지 않고 내/중앙/외 반지름을 국부 격자선으로 보존한다.
        inner, outer = via["inner_radius_mm"], via["outer_radius_mm"]
        for axis in range(2):
            center = via["center_mm"][axis]
            critical[axis].extend(center + sign * r for sign in (-1, 1) for r in (inner, (inner + outer) / 2, outer))
            critical[axis].append(center)
        critical[2].extend((via["z_min_mm"], (via["z_min_mm"] + via["z_max_mm"]) / 2, via["z_max_mm"]))
    for axis in range(3):
        critical[axis].extend([case["port"]["start_mm"][axis], case["port"]["stop_mm"][axis], (case["port"]["start_mm"][axis] + case["port"]["stop_mm"][axis]) / 2])
    result = {}
    total = 1
    for axis, positions in enumerate(critical):
        lower, upper = (bounds[axis] if axis < 2 else [min(z), max(z)])
        padding = settings["air_padding_mm"]
        inner_lower, inner_upper = min(positions), max(positions)
        graded = settings.get("mesh_policy")
        critical_positions = sorted(set(positions if graded else positions + [lower - padding, upper + padding]))
        points = []
        for left, right in zip(critical_positions, critical_positions[1:]):
            gap = right - left
            if gap < 1e-4:
                if gap > 1e-9:
                    fail("E_GEOMETRY", "격자 임계선 사이 간격이 너무 작습니다.", "mesh")
                continue
            count = math.ceil(gap / settings["grid_mm"])
            points.extend(left + gap * i / count for i in range(count))
        points.append(critical_positions[-1])
        points = sorted(set(round(v, 12) for v in points))
        if graded:
            points = graded_axis(points, [lower, upper], padding, graded["air_cell_mm"], graded["growth_ratio"])
        if len(points) < 19 or sum(v < inner_lower for v in points) < 9 or sum(v > inner_upper for v in points) < 9:
            fail("E_GEOMETRY", "PML 8 cells와 모델 사이의 공기 격자가 부족합니다.", "mesh")
        total *= len(points)
        if total > MAX_GRID_POINTS:
            fail("E_RESOURCE", "초기 PCB profile의 실제 격자점 상한 1500000을 초과했습니다.", "mesh")
        result["xyz"[axis]] = points
    return result


def normalization_contract(port):
    """! @brief 명시적 lumped 저항과 pulse Fourier 비율의 결과 규약을 반환한다."""
    return {"schema": "rfad.normalization.pcb-single-port/0.1", "fourier_convention": "exp(-j*2*pi*f*t)",
            "native_fourier_scale": "2*dt*sum(value*exp(-j*2*pi*f*t))", "native_voltage_unit": "V*s", "native_current_unit": "A*s",
            "wave_definition": "voltage_wave_real_lumped_resistance", "reference_impedance_ohm": port["resistance_ohm"],
            "reference_plane": port["reference_plane"], "reference_plane_shift_mm": 0.0,
            "start_terminal": "reference_geometry_id", "stop_terminal": "positive_geometry_id", "polarity": 1,
            "absolute_power_gain_efficiency": "not_evaluated", "vswr_invalid_when_reflection_ge_one": True}


def _payload(document, snapshot, runtime, settings):
    """! @brief 보존한 사용자 설계에서 native 소비 조건을 결정적으로 만든다."""
    validate_project(document)
    _snapshot(snapshot)
    _runtime(runtime)
    validate_settings(settings)
    if snapshot["content_hash"] != canonical_hash(document) or any(snapshot[key] != document[key] for key in ("project_id", "revision_id", "schema_version")):
        fail("E_HASH", "PCB 원본과 스냅샷 참조가 다릅니다.", "snapshot")
    if document["extensions"]:
        fail("E_UNSUPPORTED", "의미를 해석하지 않은 확장이 있는 PCB는 실행할 수 없습니다.", "extensions")
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    if any(frame["rotation"] != identity or frame["translation_si"] != [0.0, 0.0, 0.0] or frame["handedness"] != "right" for frame in document["frames"].values()):
        fail("E_UNSUPPORTED", "PCB 해석은 항등 오른손 좌표계만 지원합니다.", "frames")
    source_board = document["board"]
    if source_board is None:
        fail("E_GEOMETRY", "해석에는 명시적 기판 외곽이 필요합니다.", "board")
    outline = source_board["outline"]
    board = {"id": source_board["id"], "kind": outline["kind"]}
    if outline["kind"] == "rectangle":
        board["dimensions_mm"] = [length(document, outline[key], "board.outline." + key, positive=True) for key in ("width", "height")]
        board["bounds_mm"] = [[0.0, v] for v in board["dimensions_mm"]]
    elif outline["kind"] == "circle":
        board["center_mm"] = point(document, outline["center"], "board.outline.center")
        board["radius_mm"] = length(document, outline["radius"], "board.outline.radius", positive=True)
        board["bounds_mm"] = [[v - board["radius_mm"], v + board["radius_mm"]] for v in board["center_mm"]]
    else:
        fail("E_UNSUPPORTED", "직사각 또는 원형 PCB 외곽만 지원합니다.", "board.outline.kind")
    materials = {item["id"]: item for item in document["materials"]}
    frequency = settings["frequency_hz"]
    center_hz = (frequency["start"] + frequency["stop"]) / 2
    consumed_materials = {}
    def material(material_id, field, *, conductor=False, volume=False):
        if material_id not in materials:
            fail("E_MATERIAL_UNKNOWN", "해석에 소비할 실제 재료를 지정하십시오.", field)
        source = materials[material_id]
        low = scalar(document, source["validity_hz"]["min"], "frequency", field + ".validity_hz.min", positive=True)
        high = scalar(document, source["validity_hz"]["max"], "frequency", field + ".validity_hz.max", positive=True)
        if not low <= frequency["start"] < frequency["stop"] <= high:
            fail("E_MATERIAL_RANGE", "재료 물성의 유효 대역이 해석 대역을 포함하지 않습니다.", field)
        values = {name: scalar(document, source[name], dimension, field + "." + name,
                               positive=name == "epsilon_r", nonnegative=name != "epsilon_r")
                  for name, dimension in material_input_fields(conductor_only=conductor, volume_conductor=volume)}
        result = {"id": material_id, "name": source["name"],
                  "conductivity_s_per_m": values["conductivity"],
                  "validity_hz": {"min": low, "max": high}, "source_refs": deepcopy(source["source_refs"]), "assumptions": deepcopy(source["assumptions"])}
        if conductor:
            result["consumed_properties"] = ["conductivity"]
            result["unconsumed_properties"] = ["epsilon_r", "tan_delta"]
            result["consumption_models"] = ["bulk_conductor" if volume else "conducting_sheet"]
            if volume:
                result["epsilon_r"] = values["epsilon_r"]
                if not 1 <= result["epsilon_r"] <= 100:
                    fail("E_MATERIAL_RANGE", "초기 유한 전도 체적의 상대 유전율 범위는 1~100입니다.", field + ".epsilon_r")
                result["consumed_properties"].append("epsilon_r")
                result["unconsumed_properties"] = ["tan_delta"]
        else:
            result["epsilon_r"] = values["epsilon_r"]
            result["tan_delta"] = values["tan_delta"]
            result["consumed_properties"] = ["epsilon_r", "tan_delta", "conductivity"]
            result["unconsumed_properties"] = []
            result["consumption_models"] = ["dielectric"]
            if result["epsilon_r"] < 1 or result["epsilon_r"] > 100 or result["tan_delta"] > 1:
                fail("E_MATERIAL_RANGE", "초기 PCB profile의 물성 범위를 벗어났습니다.", field)
        if material_id in consumed_materials and consumed_materials[material_id] != result:
            previous = consumed_materials[material_id]
            if "dielectric" in previous["consumption_models"] or not conductor:
                fail("E_MATERIAL_RANGE", "같은 재료를 유전체와 도체로 동시에 소비할 수 없습니다.", field)
            result["consumption_models"] = sorted(set(previous["consumption_models"] + result["consumption_models"]))
            if "epsilon_r" in previous:
                result["epsilon_r"] = previous["epsilon_r"]
            result["consumed_properties"] = ["conductivity"] + (["epsilon_r"] if "epsilon_r" in result else [])
            result["unconsumed_properties"] = [name for name in ("epsilon_r", "tan_delta") if name not in result["consumed_properties"]]
        consumed_materials[material_id] = result
        return result
    layers = []
    for source in document["stackup"]:
        field = "stackup." + source["id"]
        if source["role"] not in ("dielectric", "conductor"):
            fail("E_UNSUPPORTED", "현재 명시적 유전체와 외측 도체 층만 해석합니다.", field)
        item = {"id": source["id"], "role": source["role"], "material_id": source["material_id"],
                "z_min_mm": length(document, source["z_min"], field + ".z_min"), "thickness_mm": length(document, source["thickness"], field + ".thickness", positive=True)}
        if item["role"] == "dielectric":
            mat = material(item["material_id"], field + ".material_id")
            item["epsilon_r"] = mat["epsilon_r"]
            item["kappa_s_per_m"] = mat["conductivity_s_per_m"] + 2 * math.pi * center_hz * EPSILON0 * mat["epsilon_r"] * mat["tan_delta"]
            item["loss_reference_frequency_hz"] = center_hz
        layers.append(item)
    dielectrics = [item for item in layers if item["role"] == "dielectric"]
    if not dielectrics or len(layers) > 8:
        fail("E_GEOMETRY", "유전체가 필요하며 초기 profile은 최대 8개 층을 지원합니다.", "stackup")
    layer_map = {item["id"]: item for item in layers}
    def sheet_surface(layer, field):
        """! @brief 외측 도체와 인접 유전체의 실제 접면을 유일하게 구한다."""
        surfaces = []
        for dielectric in dielectrics:
            if math.isclose(layer["z_min_mm"], dielectric["z_min_mm"] + dielectric["thickness_mm"], abs_tol=1e-8):
                surfaces.append(layer["z_min_mm"])
            if math.isclose(layer["z_min_mm"] + layer["thickness_mm"], dielectric["z_min_mm"], abs_tol=1e-8):
                surfaces.append(dielectric["z_min_mm"])
        if len(surfaces) != 1:
            fail("E_UNSUPPORTED", "외측 동박이 한 유전체 경계와 접하는 sheet 모델만 지원합니다.", field)
        return surfaces[0]
    shapes, vias, omissions, polygons_by_id = [], [], [], {}
    polygon_points = 0
    for source in document["geometry"]:
        if not source["include_in_em"]:
            omissions.append({"id": source["id"], "reason": "include_in_em=false"})
            continue
        field = "geometry." + source["id"]
        if len(shapes) + len(vias) >= 64 or source["net_id"] is None:
            fail("E_CONNECTIVITY", "명시적인 net이 필요하며 최대 64개 도체를 지원합니다.", field + ".net_id")
        layer = layer_map[source["layer_id"]]
        mat = material(source["material_ref"] or layer["material_id"], field + ".material_ref", conductor=True, volume=source["kind"] == "via")
        if not 1e3 <= mat["conductivity_s_per_m"] <= 1e9 or layer["thickness_mm"] > 0.2:
            fail("E_MATERIAL_RANGE", "유한 전도도와 0.2 mm 이하 동박 두께가 필요한 sheet 모델입니다.", field)
        item = {key: deepcopy(source[key]) for key in ("id", "kind", "role", "layer_id", "net_id", "material_ref", "source_ref")}
        if item["kind"] == "via":
            conductor_layers = [entry["id"] for entry in layers if entry["role"] == "conductor"]
            if len(conductor_layers) < 2 or source["layer_id"] != conductor_layers[0] or source["end_layer_id"] != conductor_layers[-1]:
                fail("E_UNSUPPORTED", "초기 PTH 해석은 전체 적층의 최외측 두 conductor를 잇는 관통 비아만 지원합니다.", field)
            physical_lower = layer_map[conductor_layers[0]]["z_min_mm"]
            last_layer = layer_map[conductor_layers[-1]]
            physical_upper = last_layer["z_min_mm"] + last_layer["thickness_mm"]
            if any(entry["z_min_mm"] < physical_lower - 1e-8 or entry["z_min_mm"] + entry["thickness_mm"] > physical_upper + 1e-8 for entry in layers):
                fail("E_UNSUPPORTED", "초기 관통 비아는 최외측 conductor 바깥의 추가 적층을 지원하지 않습니다.", field)
            lower, upper = sorted((sheet_surface(layer, field), sheet_surface(layer_map[source["end_layer_id"]], field)))
            inner = length(document, source["finished_hole_diameter"], field + ".finished_hole_diameter", positive=True) / 2
            plating = length(document, source["plating_thickness"], field + ".plating_thickness", positive=True)
            tool_value = resolve_scalar(document, source["tool_hole_diameter"], "length", field + ".tool_hole_diameter").value_si
            tool = None if tool_value is None else length(document, source["tool_hole_diameter"], field + ".tool_hole_diameter", positive=True)
            if tool is not None and abs(tool - 2 * (inner + plating)) > 1e-6:
                fail("E_GEOMETRY", "초기 PTH의 알려진 tool hole은 finished hole + 2*plating과 일치해야 합니다.", field + ".tool_hole_diameter")
            item.update(center_mm=point(document, source["center"], field + ".center"), z_min_mm=lower, z_max_mm=upper,
                        inner_radius_mm=inner, outer_radius_mm=inner + plating, plating_thickness_mm=plating,
                        tool_hole_diameter_mm=tool, tool_hole_used_for_native_geometry=False,
                        end_layer_id=source["end_layer_id"], pad_ids=deepcopy(source["pad_ids"]), fill=source["fill"],
                        material_id=mat["id"], conductivity_s_per_m=mat["conductivity_s_per_m"], epsilon_r=mat["epsilon_r"],
                        native_model="finite_conductivity_hollow_volume")
            if item["fill"] != "none" or lower >= upper or plating > inner:
                fail("E_UNSUPPORTED", "초기 PTH는 중공 배럴과 반지름 이하의 도금 두께가 필요합니다.", field)
            probe = {"kind": "pad", "pad_shape": "circle", "center_mm": item["center_mm"], "size_mm": [2 * (inner + plating)] * 2}
            if not _inside_board(board, probe):
                fail("E_GEOMETRY", "비아 배럴이 실제 기판 외곽을 벗어났습니다.", field)
            vias.append(item)
            continue
        item.update(material_id=mat["id"], conductivity_s_per_m=mat["conductivity_s_per_m"], thickness_m=layer["thickness_mm"] * 0.001,
                    sheet_z_mm=sheet_surface(layer, field + ".layer_id"))
        if item["kind"] in ("line_path", "arc_path"):
            item["width_mm"] = length(document, source["width"], field + ".width", positive=True)
            if item["width_mm"] < 2 * settings["grid_mm"]:
                fail("E_GEOMETRY", "도체 폭을 최소 두 격자로 표현하도록 grid_mm을 줄이십시오.", field + ".width")
        if item["kind"] == "line_path":
            item.update(start_mm=point(document, source["start"], field + ".start"), end_mm=point(document, source["end"], field + ".end"))
        elif item["kind"] == "arc_path":
            item.update(center_mm=point(document, source["center"], field + ".center"), radius_mm=length(document, source["radius"], field + ".radius", positive=True),
                        start_angle_deg=math.degrees(scalar(document, source["start_angle"], "angle", field + ".start_angle")),
                        sweep_angle_deg=math.degrees(scalar(document, source["sweep_angle"], "angle", field + ".sweep_angle")))
            if abs(item["start_angle_deg"]) > 1e6 or item["radius_mm"] - item["width_mm"] / 2 < settings["curve_tolerance_mm"]:
                fail("E_GEOMETRY", "원호의 안정적인 native 근사 범위를 벗어났습니다.", field)
            sweep = abs(item["sweep_angle_deg"])
            chord = 2 * item["radius_mm"] * abs(math.sin(math.radians(sweep) / 2))
            if 180 < sweep < 360 - 1e-10 and chord <= item["width_mm"] + 2 * settings["curve_tolerance_mm"]:
                fail("E_GEOMETRY", "거의 닫힌 원호의 round cap이 자체 중첩하거나 근사 오차보다 가깝습니다.", field)
        elif item["kind"] == "planar_region":
            item.update(outer_mm=[point(document, p, field + ".outer") for p in source["outer"]],
                        holes_mm=[[point(document, p, field + ".holes") for p in loop] for loop in source["holes"]])
            validate_region(item["outer_mm"], item["holes_mm"], field)
        elif item["kind"] == "pad":
            item.update(pad_shape=source["pad_shape"], center_mm=point(document, source["center"], field + ".center"),
                        size_mm=[length(document, v, field + ".size", positive=True) for v in source["size"]],
                        rotation_deg=math.degrees(scalar(document, source["rotation"], "angle", field + ".rotation")))
            if min(item["size_mm"]) < 2 * settings["grid_mm"]:
                fail("E_GEOMETRY", "패드 최소 크기는 격자 두 배 이상이어야 합니다.", field + ".size")
        else:
            fail("E_UNSUPPORTED", "지원하지 않는 PCB 도체 종류입니다.", field + ".kind")
        if not _inside_board(board, item):
            fail("E_GEOMETRY", "원형 끝단을 포함한 도체가 실제 기판 외곽을 벗어났습니다.", field)
        polygons_by_id[item["id"]] = shape_polygons(item, settings["curve_tolerance_mm"])
        polygon_points += sum(len(poly) for poly in polygons_by_id[item["id"]])
        if polygon_points > MAX_POLYGON_POINTS:
            fail("E_RESOURCE", "전체 도체 polygon의 점 개수 상한을 초과했습니다.", field)
        shapes.append(item)
    if len(document["ports"]) != 1 or not shapes:
        fail("E_PORT", "하나의 명시적 lumped 포트와 해석 도체가 필요합니다.", "ports")
    source = document["ports"][0]
    shape_map = {item["id"]: item for item in shapes}
    if source["positive_geometry_id"] not in shape_map or source["reference_geometry_id"] not in shape_map or "excitation_box" not in source:
        fail("E_PORT", "포트 양단의 해석 도체와 명시적 excitation_box가 필요합니다.", "ports." + source["id"])
    pos, ref = shape_map[source["positive_geometry_id"]], shape_map[source["reference_geometry_id"]]
    start, stop = (point(document, source["excitation_box"][key], "ports." + source["id"] + ".excitation_box." + key) for key in ("start", "stop"))
    direction = source["direction"]
    axis = next((i for i in (0, 1, 2) if abs(direction[i]) == 1 and all(direction[j] == 0 for j in range(3) if j != i)), None)
    if (axis is None or source["polarity"] != 1 or (axis != 2 and start[2] != stop[2]) or not math.isclose(stop[2], pos["sheet_z_mm"], abs_tol=1e-8)
            or not math.isclose(start[2], ref["sheet_z_mm"], abs_tol=1e-8) or (stop[axis] - start[axis]) * direction[axis] <= 0):
        fail("E_PORT", "포트는 x/y 평면 gap 또는 두 sheet 사이 z gap과 +1 극성을 지원합니다.", "ports." + source["id"])
    if any(start[i] != stop[i] for i in range(3) if i != axis):
        fail("E_UNSUPPORTED", "초기 PCB 포트는 명시적 1D gap을 지원합니다.", "ports." + source["id"] + ".excitation_box")
    if axis != 2 and abs(stop[axis] - start[axis]) < 2 * settings["grid_mm"]:
        fail("E_PORT", "급전 간극은 최소 두 격자로 표현해야 합니다.", "ports." + source["id"])
    for position, shape in ((start, ref), (stop, pos)):
        if axis != 2 and shape["kind"] in ("line_path", "arc_path") and abs(distance_to_shape(position[:2], shape) - shape["width_mm"] / 2) > 1e-6:
            fail("E_PORT", "포트 양끝은 참조한 도체의 가장자리와 접해야 합니다.", "ports." + source["id"])
    low = scalar(document, source["validity_hz"]["min"], "frequency", "ports.validity_hz.min", positive=True)
    high = scalar(document, source["validity_hz"]["max"], "frequency", "ports.validity_hz.max", positive=True)
    if not low <= frequency["start"] < frequency["stop"] <= high:
        fail("E_PORT", "포트 유효 대역이 해석 대역을 포함하지 않습니다.", "ports.validity_hz")
    port = {"id": source["id"], "number": 1, "start_mm": start, "stop_mm": stop, "axis": "xyz"[axis], "direction": direction,
            "positive_geometry_id": pos["id"], "reference_geometry_id": ref["id"], "reference_plane": source["reference_plane"],
            "resistance_ohm": scalar(document, source["resistance"], "impedance", "ports.resistance", positive=True)}
    connectivity = validate_native_contacts(shapes, port, settings["curve_tolerance_mm"], polygons_by_id, vias)
    excitation = {"kind": "gaussian", "center_hz": center_hz, "width_hz": center_hz / 2}
    shortest = 299792458.0 / (center_hz * 1.5 * math.sqrt(max(l["epsilon_r"] for l in dielectrics))) * 1000
    if settings["grid_mm"] > shortest / 10:
        fail("E_GEOMETRY", "최소 모델 파장당 10개 격자 초기 기준을 충족하지 못했습니다.", "settings.grid_mm")
    case = {"source": "user_project", "board": board, "layers": layers, "shapes": shapes, "vias": vias, "connectivity": connectivity, "materials": list(consumed_materials.values()),
            "port": port, "settings": deepcopy(settings), "frequency_hz": deepcopy(frequency), "excitation": excitation,
            "native_length_unit": "mm", "delta_unit_m": 0.001, "coordinate_round_decimals_mm": 12, "boundary_conditions": ["PML_8"] * 6, "num_threads": 2,
            "stop_criteria": {"max_timesteps": settings["max_timesteps"], "energy_decay": settings["end_criterion"], "exact_end_criteria": True}}
    lines = mesh_lines(case)
    if "mesh_policy" in settings:
        case["mesh_policy_report"] = policy_report(case, lines)
    cells = math.prod(len(values) for values in lines.values())
    return {"schema": "rfad.analysis-plan/0.1", "analysis_profile": PROFILE, "runtime_profile": runtime["runtime_profile"],
            "snapshot": deepcopy(snapshot), "source_semantics": deepcopy(document), "runtime_identity": deepcopy(runtime), "case": case,
            "normalization": normalization_contract(port),
            "model_report": {"scope": "user_pcb_single_port", "user_geometry_consumed": True, "user_materials_consumed": True,
                             "physical_validation_state": "not_validated", "omissions": omissions,
                             "approximations": ["outer copper collapsed to adjacent dielectric interface with finite-conductivity sheet model",
                                                "dielectric tan_delta converted to constant conductivity at evaluation band center",
                                                "analytic line/arc/pad converted to bounded-error polygons before Cartesian Yee discretization",
                                                "PTH uses explicit finite-kappa hollow volume; RF skin depth loss accuracy is unvalidated"],
                             "unsupported_observables": ["NF2FF", "gain", "efficiency", "absolute_power", "full_s_matrix"]},
            "resource_estimate": {"kind": "initial_estimate_not_measured", "estimated_grid_points": cells,
                                  "estimated_memory_bytes": 128 * 1024 * 1024 + cells * 160, "max_wall_time_seconds": 300,
                                  "max_output_bytes": 128 * 1024 * 1024, "max_artifact_bytes": 64 * 1024 * 1024},
            "validation_policy": {"scope": "numerical_execution_only", "formal_convergence_tested": False, "measurement_validated": False}}


def build_pcb_plan(document, snapshot, runtime_identity, settings):
    """! @brief 원본 설계와 가정을 보존한 독립 불변 계획을 생성한다."""
    result = _payload(document, snapshot, runtime_identity, settings)
    result["plan_id"] = str(uuid4())
    if len(canonical_bytes(result)) > 256 * 1024:
        fail("E_RESOURCE", "PCB 해석 계획이 256 KiB를 초과했습니다.", "analysis_plan")
    return result


def validate_pcb_plan(plan):
    """! @brief worker가 소비할 계획을 원본에서 재계산하여 숨은 변경을 차단한다."""
    if type(plan) is not dict or plan.get("analysis_profile") != PROFILE:
        fail("E_VERSION", "지원하지 않는 PCB 계획입니다.")
    _uuid(plan.get("plan_id"), "plan_id")
    expected = _payload(plan["source_semantics"], plan["snapshot"], plan["runtime_identity"], plan["case"]["settings"])
    expected["plan_id"] = plan["plan_id"]
    if canonical_bytes(plan) != canonical_bytes(expected):
        fail("E_HASH", "PCB 해석 계획이 원본 또는 명시 설정과 다릅니다.")


def read_statistics_values(text, max_timesteps):
    """! @brief 유한 native 통계와 time step 상한 미도달을 검사한다."""
    values = [float(line.split()[0]) for line in text.splitlines() if line.strip()]
    if (len(values) < 6 or not all(math.isfinite(v) for v in values) or values[0] != int(values[0])
            or values[2] != int(values[2]) or not 0 < values[2] < max_timesteps or values[1] <= 0):
        fail("E_SOLVER", "PCB native 통계가 불완전하거나 시간 상한에 도달했습니다.")
    return {"native_cells": int(values[0]), "timestep_seconds": values[1], "iterations": int(values[2]), "raw_values": values}


def check_termination(log, iterations, settings):
    """! @brief 요청한 에너지 종료 목표를 실제 native 로그에서 확인한다."""
    lowered = log.lower()
    if any(token in lowered for token in ("checkabortcond", "aborting simulation", "max. number of timesteps was reached", "fallback to pec")) or "Exact-endcriteria: evaluating the end criteria every " not in log:
        fail("E_SOLVER", "PCB 해석이 정상 에너지 종료 조건을 충족하지 못했습니다.")
    pattern = r"RunFDTD: end-criteria of -([0-9.]+)dB reached after ([0-9]+) timesteps \(-([0-9.]+|inf)dB\)"
    matches = re.findall(pattern, log)
    target = -10 * math.log10(settings["end_criterion"])
    if len(matches) != 1 or int(matches[0][1]) != iterations or not 0 < iterations < settings["max_timesteps"] or abs(float(matches[0][0]) - target) > 0.011 or float(matches[0][2]) + 0.011 < target:
        fail("E_SOLVER", "PCB 종료 에너지 또는 반복 수의 근거가 다릅니다.")
    decay = float(matches[0][2])
    return {"status": "end_criterion_reached", "iterations": iterations, "target_energy_ratio": settings["end_criterion"],
            "reported_decay_db": decay if math.isfinite(decay) else None, "reported_zero_energy": math.isinf(decay),
            "evidence": list(matches[0]), "exact_endcriterion_schedule": True}


def validate_preparation(plan, preparation):
    """! @brief 실제 준비 통계/소비/정규화가 계획의 결정적 투영과 같은지 확인한다."""
    lines = mesh_lines(plan["case"])
    mesh = preparation["mesh_statistics"]
    consumption = preparation["consumption_report"]
    counts = [len(lines[axis]) for axis in "xyz"]
    mappings = []
    for shape in plan["case"]["shapes"]:
        polygons = shape_polygons(shape, plan["case"]["settings"]["curve_tolerance_mm"])
        mappings.append({"source_entity_id": shape["id"], "native_property": "conductor_" + shape["id"],
                         "polygon_count": len(polygons), "polygon_point_count": sum(len(poly) for poly in polygons),
                         "curve_tolerance_mm": plan["case"]["settings"]["curve_tolerance_mm"], "sheet_z_mm": shape["sheet_z_mm"],
                         "modeled_thickness_m": shape["thickness_m"], "conductivity_s_per_m": shape["conductivity_s_per_m"]})
    via_mappings = [{"source_entity_id": via["id"], "native_property": "via_" + via["id"], "drill_property": "drill_" + via["id"],
                     "model": via["native_model"], "center_mm": via["center_mm"], "z_range_mm": [via["z_min_mm"], via["z_max_mm"]],
                     "inner_radius_mm": via["inner_radius_mm"], "outer_radius_mm": via["outer_radius_mm"],
                     "conductivity_s_per_m": via["conductivity_s_per_m"], "epsilon_r": via["epsilon_r"], "skin_depth_loss_validated": False,
                     "tool_hole_diameter_mm": via["tool_hole_diameter_mm"], "tool_hole_used_for_native_geometry": False, "native_drill_basis": "finished_hole_diameter"}
                    for via in plan["case"].get("vias", [])]
    connectivity = consumption.get("native_connectivity", {})
    expected_entities = sorted(item["id"] for item in plan["case"]["shapes"] + plan["case"].get("vias", []))
    records = connectivity.get("entities", [])
    if (connectivity.get("schema") != "rfad.pcb-native-connectivity/0.1" or connectivity.get("yee_connectivity_checked") is not True
            or connectivity.get("operator_coefficients_checked") is not False or connectivity.get("physics_validated") is not False
            or connectivity.get("port_terminals_connected") is not True or type(connectivity.get("port_gap_edge_count")) is not int
            or connectivity["port_gap_edge_count"] < 2 or connectivity.get("components") != sorted(plan["case"]["connectivity"]["components"])
            or type(records) is not list or [record.get("entity_id") for record in records] != expected_entities
            or any(type(record.get("conductor_edge_count")) is not int or record["conductor_edge_count"] <= 0 or record.get("component_count") != 1 for record in records)):
        fail("E_HASH", "PCB native 격자 연결/급전 보고가 계획한 도체와 다릅니다.")
    if (mesh.get("lines_mm") != lines or mesh.get("line_counts") != counts or mesh.get("native_grid_points") != math.prod(counts)
            or mesh.get("interval_counts") != [c - 1 for c in counts] or mesh.get("yee_interval_cells") != math.prod(c - 1 for c in counts)
            or mesh.get("fdtd_executed") is not False or mesh.get("native_preprocessing_executed") is not False
            or mesh.get("delta_unit_m") != 0.001 or mesh.get("native_length_unit") != "mm"
            or mesh.get("mesh_policy_report") != plan["case"].get("mesh_policy_report")
            or preparation.get("normalization") != plan["normalization"] or preparation["consumption_report"].get("consumed_case") != plan["case"]
            or consumption.get("project_geometry_consumed") is not True or consumption.get("project_materials_consumed") is not True
            or consumption.get("source_mapping") != mappings or consumption.get("fdtd_executed") is not False or consumption.get("physics_validated") is not False
            or consumption.get("board_native_primitive") != ("cylinder" if plan["case"]["board"]["kind"] == "circle" else "box")
            or consumption.get("approximations") != plan["model_report"]["approximations"]
            or consumption.get("via_source_mapping") != via_mappings
            or consumption.get("analysis_plan_id") != plan["plan_id"] or consumption.get("source") != "user_project"):
        fail("E_HASH", "PCB 준비된 격자/소비 보고 또는 정규화가 계획과 다릅니다.")


def validate_result(plan, result, prepared_plan=None):
    """! @brief 유한 복소 결과와 계산 상태를 검사하되 물리 검증 합격을 만들지 않는다."""
    if result.get("schema") != "rfad.openems-pcb-result/0.1" or result.get("analysis_plan_id") != plan["plan_id"] or result.get("normalization") != plan["normalization"]:
        fail("E_HASH", "PCB 정규화 결과의 계획 또는 단위가 다릅니다.")
    if prepared_plan is not None and result.get("prepared_plan_id") != prepared_plan["prepared_plan_id"]:
        fail("E_HASH", "PCB 결과의 준비 계획이 다릅니다.")
    frequency = plan["case"]["frequency_hz"]
    samples = result.get("samples", [])
    if len(samples) != frequency["count"]:
        fail("E_SOLVER", "PCB 결과 주파수 표본 수가 다릅니다.")
    for index, row in enumerate(samples):
        target = frequency["start"] + (frequency["stop"] - frequency["start"]) * index / (frequency["count"] - 1)
        if (type(row) is not dict or type(row.get("frequency_hz")) not in (int, float)
                or not frequency["start"] <= row["frequency_hz"] <= frequency["stop"] or abs(row["frequency_hz"] - target) > 1e-5):
            fail("E_HASH", "PCB 결과 주파수 축이 계획과 다릅니다.")
        for key in ("s11", "impedance_ohm"):
            pair = row.get(key)
            if type(pair) is not list or len(pair) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pair):
                fail("E_SOLVER", "PCB 복소 결과는 유한한 실수 쌍이어야 합니다.")
        magnitude = math.hypot(*row["s11"])
        if not math.isfinite(magnitude):
            fail("E_SOLVER", "PCB 반사 계수의 크기가 유한 범위를 벗어났습니다.")
        expected_vswr = (1 + magnitude) / (1 - magnitude) if magnitude < 1 else None
        expected_db = 20 * math.log10(magnitude) if magnitude > 0 else None
        if row.get("vswr_status") != ("defined" if expected_vswr is not None else "undefined_reflection_ge_one"):
            fail("E_HASH", "PCB VSWR의 정의 상태가 반사 계수와 다릅니다.")
        for key, expected in (("vswr", expected_vswr), ("s11_db", expected_db)):
            actual = row.get(key)
            if expected is None:
                if actual is not None:
                    fail("E_HASH", "정의되지 않은 VSWR/dB를 유한한 합격값으로 대체할 수 없습니다.")
            elif type(actual) not in (int, float) or not math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-12):
                fail("E_HASH", "복소 결과와 표시용 VSWR/dB가 다릅니다.")
    expected_assessment = {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True}
    if result.get("assessment") != expected_assessment or result.get("termination", {}).get("status") != "end_criterion_reached":
        fail("E_SOLVER", "PCB 계산 완료와 물리 검증 합격을 구분해야 합니다.")
