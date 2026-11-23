"""! @brief 제품의 읽기 전용 개정을 주기 PCB 해석 입력으로 투영한다."""

import math

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_geometry import length, point, scalar, shape_polygons, _inside_board
from rfad.application.pcb_projection import project_board
from rfad.domain.design import material_input_fields
from rfad.domain.network_data import fail, finite
from rfad.domain.physical_setup import candidates
from rfad.domain.project import validate_project


SETTINGS = {"epsilon_left", "epsilon_right", "frequencies_hz", "theta_deg", "phi_deg", "polarization",
            "grid", "comparison_grid", "curve_tolerance_mm"}
AIR = {"epsilon_r": 1, "tan_delta": 0, "conductivity_s_per_m": 0}


def _geometry(document, source, layer, board, tolerance):
    """! @brief 검증된 보드 좌표의 구리 면, 패드, 선과 원호를 평면 영역으로 읽는다."""
    field = "geometry." + source["id"]

    def lengths(key):
        """! @brief 길이 배열을 원본 단위에서 mm로 평가한다."""
        return [length(document, value, field + "." + key, positive=True) for value in source[key]]

    def coordinate(key):
        """! @brief 위치 수량을 원본 좌표계에서 평가한다."""
        return point(document, source[key], field + "." + key)

    def angle(key):
        """! @brief 원본 각도 수량을 도로 변환한다."""
        return math.degrees(scalar(document, source[key], "angle", field + "." + key))

    kind = source["kind"]
    shape = {"kind": kind}
    if kind == "planar_region":
        shape["outer_mm"] = [point(document, xy, field + ".outer") for xy in source["outer"]]
        shape["holes_mm"] = [[point(document, xy, field + ".holes") for xy in loop] for loop in source["holes"]]
    elif kind == "pad":
        shape.update(center_mm=coordinate("center"), pad_shape=source["pad_shape"], size_mm=lengths("size"),
                     rotation_deg=angle("rotation"))
    elif kind == "line_path":
        shape.update(start_mm=coordinate("start"), end_mm=coordinate("end"),
                     width_mm=length(document, source["width"], field + ".width", positive=True))
    elif kind == "arc_path":
        shape.update(center_mm=coordinate("center"),
                     radius_mm=length(document, source["radius"], field + ".radius", positive=True),
                     width_mm=length(document, source["width"], field + ".width", positive=True),
                     start_angle_deg=angle("start_angle"), sweep_angle_deg=angle("sweep_angle"))
        if shape["radius_mm"] - shape["width_mm"] / 2 < tolerance:
            fail("원호 안쪽 반경이 곡선 근사 오차보다 작습니다.", field, "E_GEOMETRY")
    else:
        fail("주기 PCB의 지원 동박 평면 형상을 사용하십시오.", field, "E_UNSUPPORTED")
    if not _inside_board(board, shape, tolerance):
        fail("동박 윤곽이 주기셀을 벗어났습니다. 경계를 가로지르는 면은 양쪽으로 나누십시오.", field, "E_GEOMETRY")
    outline = [shape["outer_mm"]] if kind == "planar_region" else shape_polygons(shape, tolerance)
    holes = shape.get("holes_mm", [])
    return [{"material": source["material_ref"] or layer["material_id"], "outer": loop, "holes": holes}
            for loop in outline]


def _material(document, source, frequencies, conductor):
    """! @brief 선언된 주파수 대역과 손실 모델을 적용하고 재료 속성을 추정하지 않는다."""
    field = "materials." + source["id"]
    low, high = (scalar(document, source["validity_hz"][key], "frequency", field + ".validity_hz." + key, positive=True)
                 for key in ("min", "max"))
    if min(frequencies) < low or max(frequencies) > high:
        fail("해석 주파수가 재료 유효 범위를 벗어났습니다.", field + ".validity_hz", "E_MATERIAL_RANGE")
    properties = material_input_fields(model=source["model"], conductor_only=conductor, volume_conductor=conductor,
                                       field=field + ".model")
    material = {key: scalar(document, source[key], dimension, field + "." + key, nonnegative=True)
                for key, dimension in properties}
    conductivity = material.pop("conductivity", 0)
    if conductor and conductivity <= 0:
        fail("동박 체적에는 유한한 양의 전도도가 필요합니다.", field + ".conductivity", "E_MATERIAL_RANGE")
    return {**material, "conductivity_s_per_m": conductivity, "tan_delta": material.get("tan_delta", 0)}


def project_case(document, settings):
    """! @brief 지원하는 저장 PCB에서만 적층, 동박 및 출처를 계산 명세로 만든다."""
    validate_project(document)
    if type(settings) is not dict or set(settings) != SETTINGS:
        fail("주기 PCB 해석 설정의 입사, 격자와 외부 매질 필드를 확인하십시오.", "settings")
    tolerance = finite(settings["curve_tolerance_mm"], "settings.curve_tolerance_mm")
    if not 0.001 <= tolerance <= 0.25:
        fail("곡선 근사 오차는 0.001~0.25 mm입니다.", "settings.curve_tolerance_mm")
    frequencies = settings["frequencies_hz"]
    if type(frequencies) is not list or not frequencies:
        fail("해석 주파수를 입력하십시오.", "settings.frequencies_hz")
    frequencies = [finite(value, "settings.frequencies_hz") for value in frequencies]
    board = project_board(document)
    if board["kind"] != "rectangle":
        fail("보드 전체가 직교 주기셀인 직사각 기판이 필요합니다.", "board.outline", "E_UNSUPPORTED")
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    if any(frame["translation_si"] != [0, 0, 0] or frame["rotation"] != identity or frame["handedness"] != "right"
           for frame in document["frames"].values()):
        fail("주기 PCB의 원본 좌표계는 항등 오른손 좌표계여야 합니다.", "frames", "E_UNSUPPORTED")
    surfaces, parts = candidates(document)
    if any(row["include_in_em"] for row in surfaces + parts):
        fail("활성 표면층이나 설치물이 포함된 개정은 평면 적층으로 자동 투영할 수 없습니다.",
             "extensions", "E_UNSUPPORTED")
    if document.get("pcb", {}).get("holes") or document["board"].get("cutouts"):
        fail("제조 홀 또는 절삭이 있는 개정은 현재 주기 적층으로 투영할 수 없습니다.", "pcb", "E_UNSUPPORTED")
    sources = {item["id"]: item for item in document["materials"]}
    layer_sources = {item["id"]: item for item in document["stackup"]}
    patterns = {key: [] for key in layer_sources}
    excluded, regions_by_source = [], []
    for source in document["geometry"]:
        if not source["include_in_em"]:
            excluded.append(source["id"])
            continue
        layer = layer_sources[source["layer_id"]]
        if layer["role"] != "conductor":
            fail("포함 동박은 도체 적층에 놓여야 합니다.", "geometry." + source["id"], "E_UNSUPPORTED")
        regions = _geometry(document, source, layer, board, tolerance)
        regions_by_source.append({"id": source["id"], "source_ref": source["source_ref"], "layer_id": layer["id"],
                                  "first_region": len(patterns[layer["id"]]), "region_count": len(regions)})
        patterns[layer["id"]].extend(regions)
    materials = {"air": AIR.copy()}
    layer_rows = []
    used_roles = {}
    for layer in document["stackup"]:
        field = "stackup." + layer["id"]
        if layer["role"] not in ("conductor", "dielectric"):
            fail("도체와 유전체 적층을 사용하십시오.", field, "E_UNSUPPORTED")
        conductor = layer["role"] == "conductor"
        regions = patterns[layer["id"]]
        background = "air" if conductor else layer["material_id"]
        ids = {item["material"] for item in regions} if conductor else {background}
        for material_id in sorted(ids):
            if material_id in used_roles and used_roles[material_id] != conductor:
                fail("한 재료를 도체와 유전체 양쪽으로 소비할 수 없습니다.", field, "E_MATERIAL_RANGE")
            if material_id not in sources:
                fail("적층에 명시 재료가 필요합니다.", field + ".material_id", "E_MATERIAL_UNKNOWN")
            used_roles[material_id] = conductor
            materials[material_id] = _material(document, sources[material_id], frequencies, conductor)
        z = length(document, layer["z_min"], field + ".z_min")
        depth = length(document, layer["thickness"], field + ".thickness", positive=True)
        layer_rows.append((z, depth, layer["id"], background, regions))
    if not layer_rows or all(row[3] == "air" for row in layer_rows):
        fail("유전체 적층이 필요합니다.", "stackup", "E_GEOMETRY")
    layer_rows.sort()
    cursor = layer_rows[0][0]
    layers, layer_ids = [], []
    for z, depth, layer_id, background, regions in layer_rows:
        gap = z - cursor
        if gap < -1e-8:
            fail("이 해석의 두께 방향 적층 구간은 겹칠 수 없습니다.", "stackup." + layer_id, "E_GEOMETRY")
        if gap > 1e-8:
            layers.append({"thickness_mm": gap, "background": "air", "regions": []})
            layer_ids.append(None)
        layers.append({"thickness_mm": depth, "background": background, "regions": regions})
        layer_ids.append(layer_id)
        cursor = z + depth
    original = {
        "project_id": document["project_id"], "revision_id": document["revision_id"],
        "document_sha256": canonical_hash(document), "settings_sha256": canonical_hash(settings),
        "curve_tolerance_mm": tolerance, "board_z_origin_mm": layer_rows[0][0],
        "layer_ids": layer_ids, "geometry_regions": regions_by_source, "excluded_geometry_ids": excluded,
        "unexcited_port_ids": [port["id"] for port in document["ports"]],
        "materials": {key: {"source_refs": sources[key]["source_refs"], "assumptions": sources[key]["assumptions"]}
                      for key in used_roles},
    }
    case = {key: settings[key] for key in SETTINGS - {"curve_tolerance_mm"}}
    case.update(period_mm=board["dimensions_mm"], layers=layers, materials=materials)
    return case, original
