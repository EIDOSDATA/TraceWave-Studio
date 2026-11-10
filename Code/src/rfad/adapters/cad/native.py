"""! @brief 격리 worker에서 정확한 선/원호 고체와 AP242 STEP 패키지를 생성한다.

@details 무거운 CadQuery/OCP 모듈은 실행 함수 안에서만 읽는다. 이 모듈의
재입력 검사는 같은 OCCT 커널의 교환 검사이며 제조 또는 RF 합격이 아니다.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
from uuid import NAMESPACE_URL, uuid5

from rfad.application.canonical import canonical_bytes
from rfad.application.display_mesh import (ANGULAR_DEFLECTION_RAD, LINEAR_DEFLECTION_MM, MAX_MESH_BYTES,
                                          MAX_TRIANGLES, MAX_VERTICES, MAPPING_KEYS, SCHEMA as MESH_SCHEMA,
                                          validate_display_mesh)
from rfad.domain.errors import ProjectError


PROFILE = "rfad.step.mechanical/0.1"
SCHEMA = "rfad.cad-input/0.1"
MAX_FILE_BYTES = 64 * 1024 * 1024


def _require(condition: bool, message: str, *, code: str = "E_GEOMETRY", field: str = "cad") -> None:
    """! @brief 지원 범위와 native 검사 실패를 원본 필드 진단으로 전달한다."""
    if not condition:
        raise ProjectError(code, message, details={"field_path": field})


def _number(value: object, field: str, *, positive: bool = False) -> float:
    """! @brief native 경계에서도 유한 숫자와 양수 조건을 다시 확인한다."""
    _require(type(value) in (int, float), "CAD 입력에는 유한 숫자가 필요합니다.", field=field)
    number = float(value)
    _require(math.isfinite(number) and abs(number) <= 1e6 and (not positive or number >= 1e-5),
             "CAD 표시 범위 또는 최소 형상 크기를 벗어났습니다.", field=field)
    return number


def _point(values: object, field: str) -> tuple[float, float]:
    """! @brief mm 평면 좌표를 외부 코드 실행 없이 읽는다."""
    _require(type(values) is list and len(values) == 2, "CAD 평면 점에는 좌표 두 개가 필요합니다.", field=field)
    return tuple(_number(value, field) for value in values)


def _circle_arc(cq, radius: float, center: tuple, start: float, sweep: float):
    """! @brief 세 점으로 원을 추정하지 않고 명시한 반지름과 signed 각도로 자른다."""
    if sweep > 0.0:
        return cq.Edge.makeCircle(radius, center, (0, 0, 1), start, start + sweep)
    return cq.Edge.makeCircle(radius, center, (0, 0, 1), start + sweep, start).reverse()


def _line(cq, shape: dict, layer: dict):
    """! @brief 선 중심선에 정확한 반원 끝단을 연결하여 양의 두께 고체를 만든다."""
    start = _point(shape["start_mm"], "geometry." + shape["id"] + ".start")
    end = _point(shape["end_mm"], "geometry." + shape["id"] + ".end")
    width = _number(shape["width_mm"], "geometry." + shape["id"] + ".width", positive=True)
    length = math.dist(start, end)
    _require(length >= 1e-5, "CAD 선 길이가 최소 형상 크기보다 작습니다.")
    ux, uy = ((end[index] - start[index]) / length for index in range(2))
    radius = width / 2.0
    z = layer["z_min_mm"]
    start_left = (start[0] - uy * radius, start[1] + ux * radius, z)
    start_right = (start[0] + uy * radius, start[1] - ux * radius, z)
    end_left = (end[0] - uy * radius, end[1] + ux * radius, z)
    end_right = (end[0] + uy * radius, end[1] - ux * radius, z)
    direction = math.degrees(math.atan2(uy, ux))
    edges = [
        cq.Edge.makeLine(start_left, end_left),
        _circle_arc(cq, radius, (end[0], end[1], z), direction + 90.0, -180.0),
        cq.Edge.makeLine(end_right, start_right),
        _circle_arc(cq, radius, (start[0], start[1], z), direction - 90.0, -180.0),
    ]
    wire = cq.Wire.assembleEdges(edges)
    return cq.Solid.extrudeLinear(wire, [], (0.0, 0.0, layer["thickness_mm"]))


def _arc(cq, shape: dict, layer: dict):
    """! @brief signed sweep의 원호 양쪽 offset과 반원 끝단을 analytic wire로 만든다."""
    cx, cy = _point(shape["center_mm"], "geometry." + shape["id"] + ".center")
    radius = _number(shape["radius_mm"], "geometry." + shape["id"] + ".radius", positive=True)
    width = _number(shape["width_mm"], "geometry." + shape["id"] + ".width", positive=True)
    start_degrees = math.remainder(_number(shape["start_angle_deg"], "geometry." + shape["id"] + ".start_angle"), 360.0)
    start = math.radians(start_degrees)
    sweep = _number(shape["sweep_angle_deg"], "geometry." + shape["id"] + ".sweep_angle")
    _require(1e-6 <= abs(sweep) <= 360.0, "CAD 원호 회전량은 0보다 크고 360도 이하여야 합니다.")
    outer, inner = radius + width / 2.0, radius - width / 2.0
    _require(inner >= 1e-5, "원호 안쪽 반지름이 CAD 최소 형상 크기보다 작습니다.")
    z = layer["z_min_mm"]
    height = layer["thickness_mm"]
    if abs(sweep) == 360.0:
        outer_wire = cq.Wire.makeCircle(outer, (cx, cy, z), (0, 0, 1))
        inner_wire = cq.Wire.makeCircle(inner, (cx, cy, z), (0, 0, 1))
        return cq.Solid.extrudeLinear(outer_wire, [inner_wire], (0.0, 0.0, height))
    if abs(sweep) > 180.0:
        gap = 2.0 * radius * math.sin(math.radians(360.0 - abs(sweep)) / 2.0)
        _require(gap > width + 1e-5,
                 "근접한 원호 끝단의 반원 cap이 겹치거나 최소 간격보다 가깝습니다. 이 profile은 해당 자기 중첩을 지원하지 않습니다.",
                 code="E_UNSUPPORTED", field="geometry." + shape["id"] + ".sweep_angle")
    angle = math.radians(sweep)
    end = start + angle
    sign = 1.0 if sweep > 0.0 else -1.0
    end_degrees = start_degrees + sweep
    edges = [
        _circle_arc(cq, outer, (cx, cy, z), start_degrees, sweep),
        _circle_arc(cq, width / 2.0, (cx + radius * math.cos(end), cy + radius * math.sin(end), z), end_degrees, sign * 180.0),
        _circle_arc(cq, inner, (cx, cy, z), end_degrees, -sweep),
        _circle_arc(cq, width / 2.0, (cx + radius * math.cos(start), cy + radius * math.sin(start), z), start_degrees + 180.0, sign * 180.0),
    ]
    wire = cq.Wire.assembleEdges(edges)
    return cq.Solid.extrudeLinear(wire, [], (0.0, 0.0, height))


def _metrics(shape) -> dict:
    """! @brief 비교용 부피, 중심, 경계와 닫힌 고체 수를 mm 단위로 측정한다."""
    solids = shape.Solids()
    _require(bool(solids) and shape.isValid(), "CAD 결과가 유효한 B-rep 고체가 아닙니다.")
    _require(all(solid.Volume() > 0.0 and solid.isValid() and all(shell.Closed() for shell in solid.Shells()) for solid in solids),
             "CAD 결과에 빈 고체, 역방향 고체 또는 열린 외피가 있습니다.")
    box = shape.BoundingBox()
    center = shape.Center()
    top_faces = [face for face in shape.Faces() if face.geomType() == "PLANE" and face.normalAt().z > 0.999999]
    _require(bool(top_faces), "지원 prismatic 고체의 상부 평면 단면이 없습니다.")
    section_area = sum(face.Area() for face in top_faces)
    hole_count = sum(len(face.innerWires()) for face in top_faces)
    values = [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax, shape.Volume(), center.x, center.y, center.z]
    _require(all(math.isfinite(value) for value in values), "CAD 측정 결과에 유한하지 않은 값이 있습니다.")
    return {"solid_count": len(solids), "volume_mm3": shape.Volume(),
            "bbox_mm": values[:6], "center_mm": [center.x, center.y, center.z], "valid_brep": True,
            "thickness_mm": box.zlen, "section_area_mm2": section_area,
            "section_loop_count": len(top_faces) + hole_count, "through_hole_count": hole_count,
            "section_method": "Upper planar caps, equivalent to normal section for constant-thickness prismatic profile"}


def _make_bodies(cq, projection: dict) -> list[dict]:
    """! @brief dielectric와 도체를 분리하고 같은 net의 명시적 도체만 합친다."""
    layers = {layer["id"]: layer for layer in projection["layers"]}
    _require(len(layers) == len(projection["layers"]) and len(layers) <= 64,
             "중복 층 또는 지원 상한을 넘는 층이 있습니다.")
    board = projection["board"]
    width = _number(board["width_mm"], "board.outline.width", positive=True)
    height = _number(board["height_mm"], "board.outline.height", positive=True)
    bodies = []
    for layer in layers.values():
        _number(layer["z_min_mm"], "stackup." + layer["id"] + ".z_min")
        _number(layer["thickness_mm"], "stackup." + layer["id"] + ".thickness", positive=True)
        _require(layer["role"] in ("dielectric", "conductor"), "해당 층 역할의 CAD coverage를 지원하지 않습니다.", code="E_UNSUPPORTED")
        if layer["role"] == "dielectric":
            solid = cq.Solid.makeBox(width, height, layer["thickness_mm"], (0.0, 0.0, layer["z_min_mm"]))
            bodies.append({"id": layer["id"], "name": "dielectric_" + layer["id"], "role": "dielectric",
                           "layer_id": layer["id"], "net_id": None, "material_id": layer["material_id"],
                           "source_entity_ids": [board["id"], layer["id"]], "shape": solid})
    groups = {}
    _require(len(projection["shapes"]) <= 128, "초기 CAD 형상 상한 128개를 초과했습니다.", code="E_RESOURCE")
    for source in projection["shapes"]:
        layer = layers.get(source["layer_id"])
        _require(layer is not None and layer["role"] == "conductor", "도체 형상이 conductor 층에 연결되지 않았습니다.")
        _require(source["kind"] in ("line_path", "arc_path"), "해당 CAD 형상은 지원하지 않습니다.", code="E_UNSUPPORTED")
        solid = _line(cq, source, layer) if source["kind"] == "line_path" else _arc(cq, source, layer)
        stats = _metrics(solid)
        if source["kind"] == "line_path":
            expected_area = math.dist(source["start_mm"], source["end_mm"]) * source["width_mm"] + math.pi * (source["width_mm"] / 2.0) ** 2
        else:
            expected_area = source["radius_mm"] * source["width_mm"] * math.radians(abs(source["sweep_angle_deg"]))
            if abs(source["sweep_angle_deg"]) != 360.0:
                expected_area += math.pi * (source["width_mm"] / 2.0) ** 2
        expected_volume = expected_area * layer["thickness_mm"]
        _require(math.isclose(stats["volume_mm3"], expected_volume, rel_tol=1e-7, abs_tol=1e-18),
                 "CAD 수치 정밀도로 analytic 원본의 체적을 보존하지 못했습니다.", field="geometry." + source["id"])
        box = stats["bbox_mm"]
        tolerance = projection["tolerance_mm"]
        _require(box[0] >= -tolerance and box[1] >= -tolerance and box[3] <= width + tolerance and box[4] <= height + tolerance,
                 "도체가 기판 외곽을 벗어납니다. 이 profile은 임의 절개 또는 잘라내기를 하지 않습니다.", field="geometry." + source["id"])
        material = source["material_ref"] if source["material_ref"] is not None else layer["material_id"]
        key = (source["layer_id"], source["net_id"], material, None if source["net_id"] is not None else source["id"])
        groups.setdefault(key, []).append((source["id"], solid))
    for (layer_id, net_id, material, _), members in sorted(groups.items(), key=lambda pair: str(pair[0])):
        ids = sorted(identity for identity, _ in members)
        solid = members[0][1]
        for _, other in members[1:]:
            solid = solid.fuse(other)
        identity = ids[0] if len(ids) == 1 else str(uuid5(NAMESPACE_URL, "rfad/cad/" + "/".join(ids)))
        bodies.append({"id": identity, "name": "conductor_" + identity, "role": "conductor",
                       "layer_id": layer_id, "net_id": net_id, "material_id": material,
                       "source_entity_ids": ids, "shape": solid})
    _require(bool(bodies), "내보낼 CAD 고체가 없습니다.")
    tolerance = projection["tolerance_mm"]
    for body in bodies:
        body["metrics"] = _metrics(body["shape"])
    _check_pairs(bodies, tolerance)
    return sorted(bodies, key=lambda body: body["name"])


def _check_pairs(bodies: list[dict], tolerance: float) -> None:
    """! @brief 형상 생성과 재입력 양쪽에서 body 간 중첩과 net 접촉을 검사한다."""
    for index, body in enumerate(bodies):
        for other in bodies[index + 1:]:
            bounds = body["metrics"]["bbox_mm"]
            other_bounds = other["metrics"]["bbox_mm"]
            if any(bounds[axis + 3] < other_bounds[axis] - tolerance or other_bounds[axis + 3] < bounds[axis] - tolerance for axis in range(3)):
                continue
            common = body["shape"].intersect(other["shape"])
            _require(abs(common.Volume()) <= tolerance ** 3,
                     "서로 다른 도체 또는 유전체 body의 부피가 중첩합니다.", code="E_CONNECTIVITY")
            if body["role"] == other["role"] == "conductor":
                _require(body["shape"].distance(other["shape"]) > tolerance,
                         "분리된 net 또는 미지정 net의 도체가 접촉하거나 CAD 허용오차보다 가깝습니다.", code="E_CONNECTIVITY")


def _write_step(bodies: list[dict], path: Path, tolerance: float) -> None:
    """! @brief stable product 이름과 명시적 mm/AP242 설정으로 XCAF 문서를 저장한다."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_Controller, STEPControl_AsIs
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    STEPControl_Controller.Init_s()
    _require(Interface_Static.SetCVal_s("write.step.schema", "AP242DIS"), "설치한 writer가 AP242 profile을 지원하지 않습니다.", code="E_UNSUPPORTED")
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    Interface_Static.SetIVal_s("write.precision.mode", 1)
    Interface_Static.SetRVal_s("write.precision.val", tolerance)
    Interface_Static.SetIVal_s("write.surfacecurve.mode", 1)
    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    XCAFDoc_DocumentTool.SetLengthUnit_s(document, 0.001)
    for body in bodies:
        label = shape_tool.AddShape(body["shape"].wrapped, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(body["name"]))
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.SetPropsMode(True)
    _require(writer.Transfer(document, STEPControl_AsIs), "AP242 변환이 실패했습니다.")
    _require(writer.Write(str(path)) == IFSelect_RetDone, "STEP 파일 저장이 실패했습니다.", code="E_DISK")


def _read_step_shapes(path: Path) -> dict:
    """! @brief writer와 별도 OCP reader로 STEP product 이름과 B-rep를 읽는다."""
    import cadquery as cq
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetPropsMode(True)
    _require(reader.ReadFile(str(path)) == IFSelect_RetDone, "STEP reader가 파일을 읽지 못했습니다.")
    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    _require(reader.Transfer(document), "STEP reader가 B-rep를 재구성하지 못했습니다.")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    result = {}
    for index in range(1, roots.Length() + 1):
        label = roots.Value(index)
        name = TDataStd_Name()
        _require(label.FindAttribute(TDataStd_Name.GetID_s(), name), "재입력한 STEP body에 이름이 없습니다.")
        text = name.Get().ToExtString()
        _require(text not in result, "재입력한 STEP body 이름이 중복됩니다.")
        shape = cq.Shape.cast(shape_tool.GetShape_s(label))
        result[text] = shape
    return result


def read_step(path: Path) -> dict:
    """! @brief 별도 reader가 복원한 이름별 측정값만 외부 호출자에 반환한다."""
    return {name: _metrics(shape) for name, shape in _read_step_shapes(path).items()}


def _compare(expected: dict, actual: dict, tolerance: float) -> dict:
    """! @brief 이름별 고체 수, 경계, 중심과 부피의 교환 오차를 검증한다."""
    _require(set(expected) == set(actual), "STEP 재입력에서 stable body 이름 또는 객체 수가 달라졌습니다.")
    comparisons = []
    for name in sorted(expected):
        left, right = expected[name], actual[name]
        _require(left["solid_count"] == right["solid_count"], "STEP 재입력에서 연결 성분 수가 달라졌습니다.")
        _require(left["section_loop_count"] == right["section_loop_count"] and left["through_hole_count"] == right["through_hole_count"],
                 "STEP 재입력에서 단면의 경계 또는 관통 구멍 수가 달라졌습니다.")
        bbox_error = max(abs(a - b) for a, b in zip(left["bbox_mm"], right["bbox_mm"]))
        center_error = max(abs(a - b) for a, b in zip(left["center_mm"], right["center_mm"]))
        volume_error = abs(left["volume_mm3"] - right["volume_mm3"])
        volume_tolerance = max(tolerance ** 3, left["volume_mm3"] * 1e-7)
        section_error = abs(left["section_area_mm2"] - right["section_area_mm2"])
        section_tolerance = max(tolerance ** 2, left["section_area_mm2"] * 1e-7)
        thickness_error = abs(left["thickness_mm"] - right["thickness_mm"])
        _require(bbox_error <= tolerance and center_error <= tolerance and volume_error <= volume_tolerance and
                 section_error <= section_tolerance and thickness_error <= tolerance,
                 "STEP 재입력의 치수, 중심 또는 체적 오차가 profile을 초과합니다.")
        comparisons.append({"name": name, "bbox_error_mm": bbox_error, "center_error_mm": center_error,
                            "volume_error_mm3": volume_error, "volume_tolerance_mm3": volume_tolerance,
                            "section_area_error_mm2": section_error, "section_area_tolerance_mm2": section_tolerance,
                            "section_loop_count": right["section_loop_count"], "through_hole_count": right["through_hole_count"],
                            "thickness_error_mm": thickness_error,
                            "solid_count": right["solid_count"]})
    return {"status": "passed_same_kernel", "kernel_independent": False, "reader": "OCP STEPCAFControl_Reader",
            "linear_tolerance_mm": tolerance, "relative_volume_tolerance": 1e-7, "bodies": comparisons,
            "body_overlap_checked_before_and_after": True,
            "not_evaluated": ["independent CAD kernel", "manufacturing DRC", "RF accuracy", "ports and intended net connectivity",
                              "drilled holes/vias/slots", "assembly placement", "source color preservation"]}


def _file(path: Path, role: str, media_type: str) -> dict:
    """! @brief 닫힌 산출물의 크기와 streaming hash를 계산한다."""
    size = path.stat().st_size
    _require(0 < size <= MAX_FILE_BYTES, "CAD 산출물 크기가 허용 범위를 벗어났습니다.", code="E_RESOURCE")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.name, "role": role, "sha256": digest.hexdigest(), "bytes": size, "media_type": media_type}


def _write_display_mesh(bodies: list[dict], projection: dict, path: Path) -> None:
    """! @brief 정확한 교환 파일 저장 후 실제 고체를 절대 mm 허용오차로 삼각화한다.

    @details 표시 근사는 기하 원본과 이미 저장한 STEP/B-rep에 되먹임하지 않는다.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    mesh = {"schema": MESH_SCHEMA, "snapshot": deepcopy(projection["snapshot"]), "run_id": projection.get("run_id"),
            "unit": "mm", "purpose": "display_only", "linear_deflection_mm": LINEAR_DEFLECTION_MM,
            "angular_deflection_rad": ANGULAR_DEFLECTION_RAD, "bodies": []}
    vertex_count = triangle_count = 0
    for body in bodies:
        mesher = BRepMesh_IncrementalMesh(body["shape"].wrapped, LINEAR_DEFLECTION_MM, False, ANGULAR_DEFLECTION_RAD, False)
        _require(mesher.IsDone(), "CAD 표시 삼각화가 완료되지 않았습니다.")
        item = {key: deepcopy(body[key]) for key in MAPPING_KEYS}
        vertices, triangles = [], []
        for face in body["shape"].Faces():
            location = TopLoc_Location()
            poly = BRep_Tool.Triangulation_s(face.wrapped, location)
            _require(poly is not None and poly.NbNodes() > 0 and poly.NbTriangles() > 0,
                     "CAD 표시 삼각화에 누락된 면이 있습니다.")
            vertex_count += poly.NbNodes()
            triangle_count += poly.NbTriangles()
            _require(vertex_count <= MAX_VERTICES and triangle_count <= MAX_TRIANGLES,
                     "표시 mesh 정점 또는 삼각형 상한을 초과했습니다.", code="E_RESOURCE")
            offset = len(vertices)
            transform = location.Transformation()
            for index in range(1, poly.NbNodes() + 1):
                point = poly.Node(index).Transformed(transform)
                vertices.append([point.X(), point.Y(), point.Z()])
            reverse = face.wrapped.Orientation() == TopAbs_REVERSED
            for index in range(1, poly.NbTriangles() + 1):
                a, b, c = poly.Triangle(index).Get()
                triangles.append([offset + a - 1, offset + (c if reverse else b) - 1, offset + (b if reverse else c) - 1])
        item.update(vertices=vertices, triangles=triangles)
        mesh["bodies"].append(item)
    validate_display_mesh(mesh, snapshot=projection["snapshot"], run_id=projection.get("run_id"), body_map=bodies)
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    written = 0
    with path.open("xb") as stream:
        for chunk in encoder.iterencode(mesh):
            raw = chunk.encode("utf-8")
            written += len(raw)
            _require(written <= MAX_MESH_BYTES, "표시 mesh 파일이 16 MiB 상한을 초과했습니다.", code="E_RESOURCE")
            stream.write(raw)


def build_package(projection: dict, output_dir: Path) -> dict:
    """! @brief 고정 projection에서 STEP/B-rep/sidecar와 같은 커널 재입력 증거를 만든다.

    @param projection 서비스가 snapshot에서 봉인한 mm 기하와 원본 의미 정보.
    @param output_dir 새 작업 전용 디렉터리. 기존 산출물을 덮어쓰지 않는다.
    @return 최종 게시 전 확인할 파일 이름/hash와 생성 상태 manifest.
    """
    _require(projection.get("schema") == SCHEMA and projection.get("profile") == PROFILE,
             "지원하지 않는 CAD 입력 또는 STEP profile입니다.", code="E_UNSUPPORTED")
    _require(projection.get("unit") == "mm" and projection.get("angle_unit") == "deg",
             "CAD 입력 단위는 명시적인 mm/deg이어야 합니다.", code="E_UNIT")
    tolerance = projection.get("tolerance_mm")
    _require(type(tolerance) is float and tolerance == 1e-6, "지원하지 않는 CAD 허용오차입니다.", code="E_UNSUPPORTED")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: output_dir / name for name in ("model.step", "model.brep", "sidecar.json", "validation.json", "mesh.json")}
    _require(not any(path.exists() for path in paths.values()), "기존 CAD 산출물을 덮어쓸 수 없습니다.", code="E_CONFLICT")
    import cadquery as cq
    import OCP

    bodies = _make_bodies(cq, projection)
    _write_step(bodies, paths["model.step"], tolerance)
    _require(paths["model.step"].stat().st_size <= MAX_FILE_BYTES, "STEP 파일 상한을 초과했습니다.", code="E_RESOURCE")
    step = paths["model.step"].read_text(encoding="ascii")
    match = re.search(r"FILE_SCHEMA\s*\(\s*\((.*?)\)\s*\)", step, re.DOTALL)
    _require(match is not None and "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING" in match.group(1),
             "실제 STEP FILE_SCHEMA가 요청한 AP242가 아닙니다.")
    _require("SI_UNIT(.MILLI.,.METRE.)" in re.sub(r"\s+", "", step), "STEP 길이 단위가 mm로 선언되지 않았습니다.", code="E_UNIT")
    schema = match.group(1).strip().strip("'")
    expected = {body["name"]: body["metrics"] for body in bodies}
    restored_shapes = _read_step_shapes(paths["model.step"])
    restored = {name: _metrics(shape) for name, shape in restored_shapes.items()}
    validation = _compare(expected, restored, tolerance)
    _check_pairs([{**body, "shape": restored_shapes[body["name"]], "metrics": restored[body["name"]]} for body in bodies], tolerance)
    compound = cq.Compound.makeCompound([body["shape"] for body in bodies])
    _require(compound.exportBrep(str(paths["model.brep"])), "B-rep 파일 저장이 실패했습니다.", code="E_DISK")
    _write_display_mesh(bodies, projection, paths["mesh.json"])
    runtime = {"cadquery": importlib.metadata.version("cadquery"),
               "cadquery_ocp": importlib.metadata.version("cadquery-ocp"),
               "ocp": OCP.__version__, "python": platform.python_version(), "platform": platform.platform()}
    files = [_file(paths["model.step"], "step", "model/step"),
             _file(paths["model.brep"], "brep", "application/vnd.opencascade.brep"),
             _file(paths["mesh.json"], "display_mesh", "application/json")]
    paths["validation.json"].write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files.append(_file(paths["validation.json"], "validation", "application/json"))
    sidecar = {"schema": "rfad.step-sidecar/0.1", "status": "generated_unverified", "profile": PROFILE,
               "snapshot": deepcopy(projection["snapshot"]), "project_id": projection["project_id"],
               "revision_id": projection["revision_id"], "run_id": projection.get("run_id"),
               "projection_sha256": hashlib.sha256(canonical_bytes(projection)).hexdigest(),
               "unit": "mm", "transform": deepcopy(projection["transform"]), "runtime": runtime,
               "step_schema": schema, "writer": "OCP STEPCAFControl_Writer", "cap": "round",
               "files": files, "body_map": [{key: value for key, value in body.items() if key != "shape"} for body in bodies],
               "source_semantics": deepcopy(projection["source_semantics"]), "omissions": deepcopy(projection.get("omissions", [])),
               "brep_identity_scope": "Compound geometry only. Stable identities are STEP product names and this body_map; file/body order is not an identity.",
               "verification": validation, "manufacturing_verified": False, "rf_verified": False}
    paths["sidecar.json"].write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files.append(_file(paths["sidecar.json"], "sidecar", "application/json"))
    return {"schema": "rfad.cad-package/0.1", "status": "generated_unverified", "profile": PROFILE,
            "source_snapshot": deepcopy(projection["snapshot"]), "files": files, "step_schema": schema,
            "body_count": len(bodies), "solid_count": sum(body["metrics"]["solid_count"] for body in bodies),
            "runtime": runtime, "validation": {key: value for key, value in validation.items() if key != "bodies"}}
