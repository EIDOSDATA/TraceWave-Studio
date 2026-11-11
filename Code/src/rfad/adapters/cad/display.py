"""! @brief 교환용 원본 고체에서만 표시 mesh를 파생한다."""

from copy import deepcopy
import json
from pathlib import Path

from rfad.adapters.cad.geometry import _require
from rfad.application.display_mesh import (ANGULAR_DEFLECTION_RAD, LINEAR_DEFLECTION_MM, MAX_MESH_BYTES,
                                          MAX_TRIANGLES, MAX_VERTICES, MAPPING_KEYS, SCHEMA as MESH_SCHEMA,
                                          validate_display_mesh)


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
