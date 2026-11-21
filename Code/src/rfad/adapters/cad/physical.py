"""! @brief 표면 피복과 자체 포함 STEP 고체의 격리 CAD 변환을 담당한다."""

import math
from pathlib import Path
from tempfile import TemporaryDirectory

from rfad.adapters.cad.geometry import _require
from rfad.adapters.cad.mechanical import board_solid, cut_surface
from rfad.domain.physical_setup import KEY, step_bytes


def _positive_solid(shape):
    """! @brief 단일 닫힌 유효 고체만 사용한다."""
    solids = shape.Solids()
    _require(len(solids) == 1 and shape.isValid() and solids[0].Volume() > 0.0 and
             all(shell.Closed() for shell in solids[0].Shells()), "STEP에서 단일 닫힌 유효 고체를 확인하지 못했습니다.")
    return solids[0]


def read_external(source):
    """! @brief 고정 작업 파일에서 실제 단위와 루트/전송 성공을 확인한다."""
    import cadquery as cq
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TColStd import TColStd_SequenceOfAsciiString

    with TemporaryDirectory(prefix="step-reader-", dir=Path.cwd()) as directory:
        path = Path(directory) / "source.step"
        path.write_bytes(step_bytes(source))
        reader = STEPControl_Reader()
        _require(reader.ReadFile(str(path)) == IFSelect_RetDone, "STEP 구문을 읽지 못했습니다.")
        length, angle, solid_angle = (TColStd_SequenceOfAsciiString() for _ in range(3))
        reader.FileUnits(length, angle, solid_angle)
        units = [length.Value(index).ToCString().lower() for index in range(1, length.Length() + 1)]
        _require(units == ["millimetre"], "현재 외부 STEP 가져오기는 mm 길이 선언 한 종류만 지원합니다.", code="E_UNIT")
        reader.SetSystemLengthUnit(1.0)
        _require(reader.NbRootsForTransfer() == 1 and reader.TransferRoots() == 1 and reader.NbShapes() == 1,
                 "STEP 단일 루트를 모두 전송할 수 없습니다.")
        shape = cq.Shape.cast(reader.OneShape())
        _require(shape.ShapeType() == "Solid",
                 "STEP 단일 B-rep 고체만 지원합니다. 조립체 또는 다른 entity를 펼치지 않습니다.", code="E_UNSUPPORTED")
        solid = _positive_solid(shape)
        _require(len(solid.Faces()) <= 256, "외부 STEP 고체는 최대 256면입니다.", code="E_RESOURCE")
        return solid


def external_metrics(shape):
    """! @brief 회전 또는 곡면 외부 고체의 물리 경계와 부피를 산출한다."""
    solid = _positive_solid(shape)
    box, center = solid.BoundingBox(), solid.Center()
    bounds = [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax]
    volume, centroid = solid.Volume(), [center.x, center.y, center.z]
    _require(all(math.isfinite(value) for value in [*bounds, volume, *centroid]) and
             all(abs(value) <= 1000000.0 for value in bounds), "외부 고체 치수가 CAD 프로파일 상한을 벗어났습니다.")
    return {"bbox_mm": bounds, "solid_count": 1, "volume_mm3": volume, "center_mm": centroid,
            "valid_brep": True, "thickness_mm": box.zlen}


def inspect_step(item):
    """! @brief 가져오기 미리보기에는 실제 B-rep 확인 범위와 미정 물성을 반환한다."""
    shape = read_external(item)
    return {"sha256": item["sha256"], "unit": "mm", "shape": "single_solid", "faces": len(shape.Faces()),
            "material_id": None, **external_metrics(shape)}


def cover_board(cq, board, z, depth):
    """! @brief 기준 외곽의 바뀐 위치나 형상을 있는 그대로 사용한다."""
    return board_solid(cq, board, z, depth)


def surface_bodies(cq, projection, mechanical=()):
    """! @brief 피복을 돌출하고 명시한 개구만 절삭한다."""
    result = []
    tolerance = projection["tolerance_mm"]
    for row in projection.get("surface_layers", []):
        lower, thickness = row["z_min_mm"], row["thickness_mm"]
        outline = cover_board(cq, projection["board"], lower, thickness)
        shape = outline
        if row["rectangle_mm"] is not None:
            x, y, width, height = row["rectangle_mm"]
            shape = cq.Solid.makeBox(width, height, thickness, (x, y, lower))
            _require(shape.cut(outline).Volume() <= tolerance ** 3,
                     "표면층의 사각 피복이 기판 외곽을 벗어났습니다.", field="surface." + row["id"])
        uncut = shape
        for x, y, width, height in row["openings_mm"]:
            opening = cq.Solid.makeBox(width, height, thickness, (x, y, lower))
            _require(opening.cut(uncut).Volume() <= tolerance ** 3 and
                     abs(shape.intersect(opening).Volume() - opening.Volume()) <= max(tolerance ** 3, opening.Volume() * 1e-10),
                     "표면층 개구가 피복을 벗어나거나 다른 개구와 겹칩니다.", field="surface." + row["id"])
            shape = shape.cut(opening)
        shape, mechanical_ids = cut_surface(cq, shape, row, mechanical)
        result.append({"id": row["id"], "name": "surface_" + row["id"], "role": "surface",
                       "layer_id": row["id"], "net_id": None, "material_id": row["material_id"], "source_entity_ids": [row["id"]],
                       **({"mechanical_cut_source_ids": mechanical_ids} if mechanical_ids else {}),
                       "feature_kind": row["kind"], "shape": shape})
    return result


def part_bodies(cq, projection):
    """! @brief 원점 기준 yaw를 적용한 뒤 기판 좌표계의 x/y/z만 더한다."""
    result = []
    rows = projection.get("environment_parts", [])
    if not rows:
        return result
    storage = {row["id"]: row["step"] for row in projection["source_semantics"]["extensions"][KEY]["parts"]}
    for row in rows:
        if row["kind"] == "dielectric_case":
            width, length, height = row["size_mm"]
            wall = row["wall_mm"]
            _require(min(width, length) > 2 * wall and height > wall,
                     "케이스 벽 두께 안에 빈 내부 공간이 필요합니다.", field="part." + row["id"])
            outer = cq.Solid.makeBox(width, length, height)
            cavity = cq.Solid.makeBox(width - 2 * wall, length - 2 * wall, height - wall, (wall, wall, 0))
            shape = _positive_solid(outer.cut(cavity))
        elif row["kind"] in ("box", "isolated_pec_box"):
            shape = cq.Solid.makeBox(*row["size_mm"])
        else:
            shape = read_external(storage[row["id"]])
        shape = shape.rotate((0, 0, 0), (0, 0, 1), row["yaw_deg"]).translate(tuple(row["translation_mm"]))
        result.append({"id": row["id"], "name": "environment_" + row["id"], "role": "environment", "layer_id": row["id"],
                       "net_id": None, "material_id": row["material_id"], "source_entity_ids": [row["id"]],
                       "feature_kind": row["kind"], "shape": shape})
    return result


def placement_review(bodies, tolerance):
    """! @brief 현재 포함 모델의 형상 간극과 접촉을 전기 접속과 구분해 반환한다."""
    review = []
    for body in bodies:
        if body["role"] != "environment":
            continue
        other_bodies = [other for other in bodies if other is not body]
        nearest, distance = None, None
        for other in other_bodies:
            measured = body["shape"].distance(other["shape"])
            if distance is None or measured < distance:
                distance, nearest = measured, other["id"]
        review.append({"id": body["id"], "nearest_id": nearest, "clearance_mm": distance,
                       "relation": "not_evaluated" if distance is None else "touching" if distance <= tolerance else "separated",
                       "electrical_connection": "not_evaluated", "material_id": body["material_id"]})
    return review
