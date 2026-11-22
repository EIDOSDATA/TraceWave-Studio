"""! @brief 표면 피복과 자체 포함 STEP 고체의 격리 CAD 변환을 담당한다."""

from itertools import combinations
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from rfad.adapters.cad.geometry import _require
from rfad.adapters.cad.mechanical import board_solid, cut_surface
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import KEY, step_bytes, validate_instance_offsets


def _positive_solid(shape):
    """! @brief 단일 닫힌 유효 고체만 사용한다."""
    solids = shape.Solids()
    _require(len(solids) == 1 and shape.isValid() and solids[0].Volume() > 0.0 and
             all(shell.Closed() for shell in solids[0].Shells()), "STEP에서 단일 닫힌 유효 고체를 확인하지 못했습니다.")
    return solids[0]


_LENGTH_UNITS = {"millimetre": ("mm", 1.0), "inch": ("inch", 25.4)}


def _external_solids(shape):
    """! @brief 설치 원본의 닫힌 고체를 제한된 개수 안에서 모두 검증한다."""
    solids = shape.Solids()
    _require(1 <= len(solids) <= 16 and shape.isValid(), "STEP 설치 형상은 유효 고체 1~16개를 지원합니다.")
    _require(all(solid.isValid() and solid.Volume() > 0 and all(shell.Closed() for shell in solid.Shells())
                 for solid in solids), "STEP 설치 형상에 열린 외피, 무효 고체 또는 음의 체적이 있습니다.")
    _require(sum(len(solid.Faces()) for solid in solids) <= 256, "STEP 설치 형상은 전체 256면까지 읽습니다.", code="E_RESOURCE")
    return solids


def _assembly_instances(tool, root):
    """! @brief XCAF 조립 계층에서 반복된 부품의 원래 배치와 정의 식별자를 읽는다."""
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_Label, TDF_LabelSequence, TDF_Tool
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopLoc import TopLoc_Location

    result, leaves = [], {}

    def walk(label, parent, path):
        """! @brief 각 참조의 위치를 부모에 합성하고 같은 정의의 반복을 유지한다."""
        _require(len(path) <= 8 and len(result) < 32, "STEP 조립 계층의 깊이 또는 인스턴스 수가 상한을 넘었습니다.", code="E_RESOURCE")
        definition = TDF_Label()
        location = parent.Multiplied(tool.GetLocation_s(label))
        if not tool.GetReferredShape_s(label, definition):
            definition = label
        entry = TCollection_AsciiString()
        TDF_Tool.Entry_s(definition, entry)
        name = TDataStd_Name()
        named = label.FindAttribute(TDataStd_Name.GetID_s(), name)
        title = " ".join(name.Get().ToExtString().split())[:120] if named else ""
        transform = location.Transformation()
        assembled = tool.IsAssembly_s(definition)
        source_shape = tool.GetShape_s(definition)
        _require(assembled or source_shape.ShapeType() == TopAbs_SOLID,
                 "조립의 각 말단 부품은 하나의 닫힌 B-rep 고체여야 합니다.", code="E_UNSUPPORTED")
        result.append({"path": path, "name": title, "definition": entry.ToCString(), "assembly": assembled,
                       "transform_mm": [[transform.Value(i, j) for j in range(1, 5)] for i in range(1, 4)]})
        if assembled:
            components = TDF_LabelSequence()
            tool.GetComponents_s(definition, components, False)
            for index in range(1, components.Length() + 1):
                walk(components.Value(index), location, [*path, index])
        else:
            leaves[tuple(path)] = source_shape.Moved(location)

    walk(root, TopLoc_Location(), [1])
    return result, leaves


def _read_external(source):
    """! @brief STEP의 명시 길이 단위를 확인하고 mm 형상으로 한 번 옮긴다."""
    import cadquery as cq
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TColStd import TColStd_SequenceOfAsciiString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    with TemporaryDirectory(prefix="step-reader-", dir=Path.cwd()) as directory:
        path = Path(directory) / "source.step"
        path.write_bytes(step_bytes(source))
        reader = STEPCAFControl_Reader()
        reader.SetNameMode(True)
        _require(reader.ReadFile(str(path)) == IFSelect_RetDone, "STEP 구문을 읽지 못했습니다.")
        core = reader.ChangeReader()
        length, angle, solid_angle = (TColStd_SequenceOfAsciiString() for _ in range(3))
        core.FileUnits(length, angle, solid_angle)
        units = [length.Value(index).ToCString().lower() for index in range(1, length.Length() + 1)]
        _require(len(units) == 1 and units[0] in _LENGTH_UNITS,
                 "외부 STEP에는 한 가지 길이 단위(mm 또는 inch)가 명시되어야 합니다.", code="E_UNIT")
        source_unit, scale = _LENGTH_UNITS[units[0]]
        core.SetSystemLengthUnit(1.0)
        _require(core.NbRootsForTransfer() == 1, "STEP에는 독립 루트가 하나여야 합니다.", code="E_UNSUPPORTED")
        document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
        _require(reader.Transfer(document), "STEP 루트를 전송할 수 없습니다.")
        tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
        roots = TDF_LabelSequence()
        tool.GetFreeShapes(roots)
        _require(roots.Length() == 1, "읽은 STEP에 단일 루트가 없습니다.", code="E_UNSUPPORTED")
        root = roots.Value(1)
        shape = cq.Shape.cast(tool.GetShape_s(root))
        assembly = tool.IsAssembly_s(root)
        _require(shape.ShapeType() == "Solid" or (assembly and shape.ShapeType() == "Compound"),
                 "닫힌 STEP 고체 또는 자체 포함 조립 루트를 선택하세요.", code="E_UNSUPPORTED")
        solids = _external_solids(shape)
        instances, leaves = _assembly_instances(tool, root) if assembly else ([], {})
        _require(not assembly or len(leaves) == len(solids),
                 "STEP의 조립 인스턴스와 실제 닫힌 고체를 대응하지 못했습니다.", code="E_UNSUPPORTED")
        return shape, source_unit, scale, instances, leaves


def external_metrics(shape):
    """! @brief 회전이나 곡면을 포함한 설치 형상의 경계와 각 고체의 합산 부피를 산출한다."""
    solids = _external_solids(shape)
    box, center = shape.BoundingBox(), shape.Center()
    bounds = [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax]
    volume, centroid = shape.Volume(), [center.x, center.y, center.z]
    _require(all(math.isfinite(value) for value in [*bounds, volume, *centroid]) and
             all(abs(value) <= 1000000.0 for value in bounds), "외부 고체 치수가 CAD 프로파일 상한을 벗어났습니다.")
    return {"bbox_mm": bounds, "solid_count": len(solids), "volume_mm3": volume, "center_mm": centroid,
            "valid_brep": True, "thickness_mm": box.zlen}


def inspect_step(item):
    """! @brief 가져오기 미리보기에는 실제 B-rep 확인 범위와 미정 물성을 반환한다."""
    shape, source_unit, scale, instances, _ = _read_external(item)
    return {"sha256": item["sha256"], "unit": "mm", "source_length_unit": source_unit, "source_to_mm": scale,
            "shape": "assembly" if instances else "single_solid", "faces": len(shape.Faces()),
            "assembly_instances": instances,
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


def _shift_instances(cq, leaves, instances, offsets, part_id, tolerance):
    """! @brief 원본 말단 원점을 중심으로 조립 고정 X Y Z축 회전과 이동을 적용한다."""
    validate_instance_offsets(offsets)
    placements = {tuple(row["path"]): row for row in offsets}
    field = "part." + part_id + ".instance_offsets"
    _require(placements.keys() <= leaves.keys(), "STEP 원본의 말단 부품 경로를 확인하십시오.", field=field)
    origins = {tuple(row["path"]): tuple(axis[3] for axis in row["transform_mm"])
               for row in instances if not row["assembly"]}
    shapes = {path: cq.Shape.cast(value) for path, value in leaves.items()}
    for path, placement in placements.items():
        shape = shapes[path]
        origin = origins[path]
        for axis, angle in enumerate(placement.get("rotation_deg", [])):
            angle = math.remainder(angle, 360)
            if angle:
                end = tuple(value + (index == axis) for index, value in enumerate(origin))
                shape = shape.rotate(origin, end, angle)
        shapes[path] = shape.translate(tuple(placement["translation_mm"]))
    for (first, a), (second, b) in combinations(shapes.items(), 2):
        if first in placements or second in placements:
            bounds_a, bounds_b = a.BoundingBox(), b.BoundingBox()
            if any(min(getattr(bounds_a, axis + "max"), getattr(bounds_b, axis + "max")) -
                   max(getattr(bounds_a, axis + "min"), getattr(bounds_b, axis + "min")) <= tolerance
                   for axis in "xyz"):
                continue
            overlap = a.intersect(b).Volume()
            if overlap > tolerance ** 3:
                raise ProjectError("E_GEOMETRY", "배치한 STEP 말단 부품끼리 체적이 겹칩니다.",
                                   details={"field_path": field, "paths": [list(first), list(second)],
                                            "overlap_mm3": overlap})
    return shapes


def _assembly_export(row, instances, leaves):
    """! @brief 원본 고체 정의와 개별 부품의 최종 위치를 STEP writer에 전달한다."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    def translation(values):
        """! @brief mm 위치 변환을 만든다."""
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*values))
        return move

    def rotation(origin, axis, degrees):
        """! @brief 지정한 원점과 전역 축의 회전을 만든다."""
        turn = gp_Trsf()
        turn.SetRotation(gp_Ax1(gp_Pnt(*origin), gp_Dir(*(float(index == axis) for index in range(3)))),
                         math.radians(math.remainder(degrees, 360)))
        return turn

    root = translation(row["translation_mm"]).Multiplied(rotation((0, 0, 0), 2, row["yaw_deg"]))
    offsets = {tuple(item["path"]): item for item in row.get("instance_offsets", [])}
    definitions, placed = {}, {}
    for instance in instances:
        path = tuple(instance["path"])
        matrix = instance["transform_mm"]
        original = gp_Trsf()
        original.SetValues(*(value for axis in matrix for value in axis))
        if path in leaves:
            definitions.setdefault(instance["definition"], leaves[path].Moved(TopLoc_Location(original.Inverted())))
        location = original
        if path in offsets:
            row_offset = offsets[path]
            origin = tuple(axis[3] for axis in matrix)
            for axis, angle in enumerate(row_offset.get("rotation_deg", [])):
                if angle:
                    location = rotation(origin, axis, angle).Multiplied(location)
            location = translation(row_offset["translation_mm"]).Multiplied(location)
        placed[path] = TopLoc_Location(root.Multiplied(location))
    return {"definitions": definitions, "locations": placed, "instances": instances}


def part_bodies(cq, projection):
    """! @brief 원점 기준 yaw를 적용한 뒤 기판 좌표계의 x/y/z만 더한다."""
    result = []
    rows = projection.get("environment_parts", [])
    if not rows:
        return result
    storage = {row["id"]: row["step"] for row in projection["source_semantics"]["extensions"][KEY]["parts"]}
    for row in rows:
        source_step = {}
        placed_leaves = {}
        assembly_export = {}
        if row["kind"] == "dielectric_case":
            width, length, height = row["size_mm"]
            wall = row["wall_mm"]
            _require(min(width, length) > 2 * wall and height > wall,
                     "케이스 벽 두께 안에 빈 내부 공간이 필요합니다.", field="part." + row["id"])
            outer = cq.Solid.makeBox(width, length, height)
            cavity = cq.Solid.makeBox(width - 2 * wall, length - 2 * wall, height - wall, (wall, wall, 0))
            shape = _positive_solid(outer.cut(cavity))
        elif row["kind"] in ("box", "isolated_pec_box", "grounded_pec_box"):
            shape = cq.Solid.makeBox(*row["size_mm"])
        else:
            source = storage[row["id"]]
            shape, source_unit, scale, instances, leaves = _read_external(source)
            source_step = {"source_step": {"sha256": source["sha256"], "source_length_unit": source_unit,
                                          "source_to_mm": scale, "assembly_instances": instances}}
            if instances:
                assembly_export["_step_assembly"] = _assembly_export(row, instances, leaves)
            if row.get("instance_offsets"):
                placed_leaves = _shift_instances(cq, leaves, instances, row["instance_offsets"],
                                                  row["id"], projection["tolerance_mm"])
                shape = cq.Compound.makeCompound(list(placed_leaves.values()))
        def place(solid):
            """! @brief 조립 원점 회전 후 기판 좌표로 이동한다."""
            return solid.rotate((0, 0, 0), (0, 0, 1), row["yaw_deg"]).translate(tuple(row["translation_mm"]))

        shape = place(shape)
        if assembly_export:
            source_step["source_step"]["hierarchy_in_step"] = True
            if row.get("instance_offsets"):
                source_step["source_step"]["instance_offsets"] = row["instance_offsets"]
            expected_leaves = placed_leaves or {path: cq.Shape.cast(solid) for path, solid in leaves.items()}
            source_step["source_step"]["placed_instances"] = [
                {"path": path, "bbox_mm": external_metrics(place(solid))["bbox_mm"]}
                for path, solid in sorted(expected_leaves.items())]
        result.append({"id": row["id"], "name": "environment_" + row["id"], "role": "environment", "layer_id": row["id"],
                       "net_id": None, "material_id": row["material_id"], "source_entity_ids": [row["id"]],
                       "feature_kind": row["kind"], "shape": shape, **source_step, **assembly_export})
    return result


def _clearance_witness(shape, other):
    """! @brief 가장 가까운 두 바디의 보드 좌표상 증거점을 계산한다."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    measure = BRepExtrema_DistShapeShape(shape.wrapped, other.wrapped)
    if not measure.IsDone() or measure.NbSolution() < 1:
        return None
    return [list(point.Coord()) for point in (measure.PointOnShape1(1), measure.PointOnShape2(1))]


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
                distance, nearest = measured, other
        points = None if nearest is None else _clearance_witness(body["shape"], nearest["shape"])
        review.append({"id": body["id"], "nearest_id": None if nearest is None else nearest["id"],
                       "clearance_mm": distance, "witness_points_mm": points,
                       "relation": "not_evaluated" if distance is None else "touching" if distance <= tolerance else "separated",
                       "electrical_connection": "not_evaluated", "material_id": body["material_id"]})
    return review
