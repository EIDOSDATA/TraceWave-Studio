"""! @brief 검증된 사용자 PCB에서 재료/적층/도체/급전의 물리 소비 조건을 투영한다.

@details snapshot과 런타임의 identity는 계획 조립기가 관리한다. 이 모듈은
기존 SI/mm 변환, sheet/비아 모델, 연결 검사와 격자 알고리즘을 그대로 사용한다.
"""

from copy import deepcopy
import math

from rfad.application.pcb_contacts import validate_native_contacts
from rfad.application.pcb_geometry import (MAX_POLYGON_POINTS, fail, scalar, length, point,
                                            shape_polygons, distance_to_shape, _inside_board)
from rfad.application.pcb_mesh import mesh_lines, policy_report
from rfad.application.pcb_results import normalization_contract
from rfad.domain.design import material_input_fields, resolve_scalar
from rfad.domain.material_models import TOTAL_TAN_DELTA_MODEL
from rfad.domain.planar import validate_region

EPSILON0 = 8.8541878128e-12


class MaterialProjection:
    """! @brief 한 물리 투영 안에서 재료 소비 내역을 보존한다."""

    def __init__(self, document, frequency):
        """! @brief 원본 재료를 조회하고 사용한 모델/물성만 별도로 누적한다."""
        self.document = document
        self.frequency = frequency
        self.sources = {item["id"]: item for item in document["materials"]}
        self.consumed = {}

    def consume(self, material_id, field, *, conductor=False, volume=False):
        """! @brief 사용 목적과 유효 대역을 검증하며 소비 물성을 누적한다."""
        if material_id not in self.sources:
            fail("E_MATERIAL_UNKNOWN", "해석에 소비할 실제 재료를 지정하십시오.", field)
        source = self.sources[material_id]
        fields = material_input_fields(model=source["model"], conductor_only=conductor, volume_conductor=volume,
                                       field="materials." + material_id + ".model")
        low = scalar(self.document, source["validity_hz"]["min"], "frequency", field + ".validity_hz.min", positive=True)
        high = scalar(self.document, source["validity_hz"]["max"], "frequency", field + ".validity_hz.max", positive=True)
        if not low <= self.frequency["start"] < self.frequency["stop"] <= high:
            fail("E_MATERIAL_RANGE", "재료 물성의 유효 대역이 해석 대역을 포함하지 않습니다.", field)
        values = {name: scalar(self.document, source[name], dimension, field + "." + name,
                               positive=name == "epsilon_r", nonnegative=name != "epsilon_r")
                  for name, dimension in fields}
        result = {"id": material_id, "name": source["name"],
                  "validity_hz": {"min": low, "max": high}, "source_refs": deepcopy(source["source_refs"]), "assumptions": deepcopy(source["assumptions"])}
        if "conductivity" in values:
            result["conductivity_s_per_m"] = values["conductivity"]
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
            if source["model"] == TOTAL_TAN_DELTA_MODEL:
                result["model"] = source["model"]
                result["consumed_properties"] = ["epsilon_r", "tan_delta"]
                result["unconsumed_properties"] = ["conductivity"]
                result["loss_partition"] = "total_electric_loss_from_tan_delta_no_separate_conductivity"
            if result["epsilon_r"] < 1 or result["epsilon_r"] > 100 or result["tan_delta"] > 1:
                fail("E_MATERIAL_RANGE", "초기 PCB profile의 물성 범위를 벗어났습니다.", field)
        if material_id in self.consumed and self.consumed[material_id] != result:
            previous = self.consumed[material_id]
            if "dielectric" in previous["consumption_models"] or not conductor:
                fail("E_MATERIAL_RANGE", "같은 재료를 유전체와 도체로 동시에 소비할 수 없습니다.", field)
            result["consumption_models"] = sorted(set(previous["consumption_models"] + result["consumption_models"]))
            if "epsilon_r" in previous:
                result["epsilon_r"] = previous["epsilon_r"]
            result["consumed_properties"] = ["conductivity"] + (["epsilon_r"] if "epsilon_r" in result else [])
            result["unconsumed_properties"] = [name for name in ("epsilon_r", "tan_delta") if name not in result["consumed_properties"]]
        self.consumed[material_id] = result
        return result


def project_board(document):
    """! @brief 원본 기판 외곽의 의미와 mm 좌표를 보존한다."""
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
    return board


def project_port(document, shapes, frequency, settings):
    """! @brief 한 개의 명시적 급전 모델과 실제 도체 접점을 투영한다."""
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
    return port


def project_pcb(document, settings):
    """! @brief 계획 경계에서 검증한 문서와 설정을 native 소비 조건으로 변환한다."""
    board = project_board(document)
    frequency = settings["frequency_hz"]
    center_hz = (frequency["start"] + frequency["stop"]) / 2
    materials = MaterialProjection(document, frequency)
    layers = []
    for source in document["stackup"]:
        field = "stackup." + source["id"]
        if source["role"] not in ("dielectric", "conductor"):
            fail("E_UNSUPPORTED", "현재 명시적 유전체와 외측 도체 층만 해석합니다.", field)
        item = {"id": source["id"], "role": source["role"], "material_id": source["material_id"],
                "z_min_mm": length(document, source["z_min"], field + ".z_min"), "thickness_mm": length(document, source["thickness"], field + ".thickness", positive=True)}
        if item["role"] == "dielectric":
            mat = materials.consume(item["material_id"], field + ".material_id")
            item["epsilon_r"] = mat["epsilon_r"]
            dielectric_loss = 2 * math.pi * center_hz * EPSILON0 * mat["epsilon_r"] * mat["tan_delta"]
            if mat.get("model") == TOTAL_TAN_DELTA_MODEL:
                item["kappa_s_per_m"] = dielectric_loss
                item["loss_model"] = TOTAL_TAN_DELTA_MODEL
                item["loss_partition"] = mat["loss_partition"]
                item["loss_approximation"] = "constant_kappa_from_total_tan_delta_at_band_center_not_broadband_constant_tan_delta"
            else:
                item["kappa_s_per_m"] = mat["conductivity_s_per_m"] + dielectric_loss
            item["loss_reference_frequency_hz"] = center_hz
        elif source["material_id"] in materials.sources and materials.sources[source["material_id"]]["model"] == TOTAL_TAN_DELTA_MODEL:
            fail("E_UNSUPPORTED", "총 손실 탄젠트 모델은 도체 층에 사용할 수 없습니다.",
                 "materials." + source["material_id"] + ".model")
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
        mat = materials.consume(source["material_ref"] or layer["material_id"], field + ".material_ref", conductor=True, volume=source["kind"] == "via")
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
    port = project_port(document, shapes, frequency, settings)
    connectivity = validate_native_contacts(shapes, port, settings["curve_tolerance_mm"], polygons_by_id, vias)
    excitation = {"kind": "gaussian", "center_hz": center_hz, "width_hz": center_hz / 2}
    shortest = 299792458.0 / (center_hz * 1.5 * math.sqrt(max(l["epsilon_r"] for l in dielectrics))) * 1000
    if settings["grid_mm"] > shortest / 10:
        fail("E_GEOMETRY", "최소 모델 파장당 10개 격자 초기 기준을 충족하지 못했습니다.", "settings.grid_mm")
    case = {"source": "user_project", "board": board, "layers": layers, "shapes": shapes, "vias": vias, "connectivity": connectivity, "materials": list(materials.consumed.values()),
            "port": port, "settings": deepcopy(settings), "frequency_hz": deepcopy(frequency), "excitation": excitation,
            "native_length_unit": "mm", "delta_unit_m": 0.001, "coordinate_round_decimals_mm": 12, "boundary_conditions": ["PML_8"] * 6, "num_threads": 2,
            "stop_criteria": {"max_timesteps": settings["max_timesteps"], "energy_decay": settings["end_criterion"], "exact_end_criteria": True}}
    lines = mesh_lines(case)
    if "mesh_policy" in settings:
        case["mesh_policy_report"] = policy_report(case, lines)
    from rfad.application.pcb_radiation import recording

    radiation = recording(case, lines)
    if radiation is not None:
        case["radiation_recording"] = radiation
    cells = math.prod(len(values) for values in lines.values())
    return {"case": case,
            "normalization": normalization_contract(port, radiation=radiation is not None),
            "model_report": {"scope": "user_pcb_single_port", "user_geometry_consumed": True, "user_materials_consumed": True,
                             "physical_validation_state": "not_validated", "omissions": omissions,
                             "approximations": ["outer copper collapsed to adjacent dielectric interface with finite-conductivity sheet model",
                                                "dielectric tan_delta converted to constant conductivity at evaluation band center",
                                                "analytic line/arc/pad converted to bounded-error polygons before Cartesian Yee discretization",
                                                "PTH uses explicit finite-kappa hollow volume; RF skin depth loss accuracy is unvalidated"],
                             "unsupported_observables": ["absolute_power", "full_s_matrix"] if radiation is not None else ["NF2FF", "gain", "efficiency", "absolute_power", "full_s_matrix"]},
            "resource_estimate": {"kind": "initial_estimate_not_measured", "estimated_grid_points": cells,
                                  "estimated_memory_bytes": 128 * 1024 * 1024 + cells * 160, "max_wall_time_seconds": 300,
                                  "max_output_bytes": 128 * 1024 * 1024, "max_artifact_bytes": 64 * 1024 * 1024},
            "validation_policy": {"scope": "numerical_execution_only", "formal_convergence_tested": False, "measurement_validated": False}}
