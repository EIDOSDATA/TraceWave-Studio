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
        original_name = TDataStd_Name()
        definition_name = (" ".join(original_name.Get().ToExtString().split())[:120]
                           if definition.FindAttribute(TDataStd_Name.GetID_s(), original_name) else "")
        transform = location.Transformation()
        assembled = tool.IsAssembly_s(definition)
        source_shape = tool.GetShape_s(definition)
        _require(assembled or source_shape.ShapeType() == TopAbs_SOLID,
                 "조립의 각 말단 부품은 하나의 닫힌 B-rep 고체여야 합니다.", code="E_UNSUPPORTED")
        result.append({"path": path, "name": title, "definition_name": definition_name, "definition": entry.ToCString(), "assembly": assembled,
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


def _source_units(core):
    """! @brief STEP의 각 형상 표현이 실제 참조하는 길이 단위와 인치 환산 근거를 확인한다."""
    from OCP.StepBasic import (StepBasic_ConversionBasedUnitAndLengthUnit, StepBasic_SiUnitAndLengthUnit,
                               StepBasic_SiUnitName, StepBasic_SiPrefix)
    from OCP.StepShape import StepShape_ShapeRepresentation

    def si_scale(unit):
        """! @brief 길이 문맥과 인치 변환의 기준 SI 단위를 mm로 환산한다."""
        if not isinstance(unit, StepBasic_SiUnitAndLengthUnit) or unit.Name() != StepBasic_SiUnitName.StepBasic_sunMetre:
            return None
        if not unit.HasPrefix():
            return 1000.0
        return {StepBasic_SiPrefix.StepBasic_spMilli: 1.0, StepBasic_SiPrefix.StepBasic_spCenti: 10.0}.get(unit.Prefix())

    model, names = core.StepModel(), set()
    for index in range(1, model.NbEntities() + 1):
        entity = model.Value(index)
        if not isinstance(entity, StepShape_ShapeRepresentation):
            continue
        context = entity.ContextOfItems()
        _require(hasattr(context, "NbUnits"), "STEP 형상 표현에 길이 단위 문맥이 없습니다.", code="E_UNIT")
        lengths = [unit for i in range(1, context.NbUnits() + 1) if hasattr(unit := context.UnitsValue(i), "LengthUnit")]
        _require(len(lengths) == 1, "STEP 형상 표현마다 하나의 길이 단위를 명시하십시오.", code="E_UNIT")
        unit = lengths[0]
        if si_scale(unit) == 1:
            names.add("mm")
        elif isinstance(unit, StepBasic_ConversionBasedUnitAndLengthUnit) and unit.Name().ToCString().casefold() == "inch":
            factor = unit.ConversionFactor()
            base = si_scale(factor.UnitComponent().Value()) if factor is not None else None
            _require(base is not None and math.isclose(base * factor.ValueComponent(), 25.4, rel_tol=1e-10),
                     "STEP 인치 길이의 환산값이 25.4 mm와 다릅니다.", code="E_UNIT")
            names.add("inch")
        else:
            _require(False, "STEP 형상 표현의 지원 길이 단위는 mm 또는 inch입니다.", code="E_UNIT")
    _require(bool(names), "STEP 형상 표현에서 길이 단위를 찾지 못했습니다.", code="E_UNIT")
    return ("mixed", None) if len(names) > 1 else next(pair for pair in _LENGTH_UNITS.values() if pair[0] in names)


def _read_external(source):
    """! @brief STEP의 명시 길이 단위를 확인하고 mm 형상으로 한 번 옮긴다."""
    import cadquery as cq
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
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
        source_unit, scale = _source_units(core)
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
    shape, source_unit, scale, instances, leaves = _read_external(item)
    datums = leaves if instances else {(1,): shape.wrapped}
    return {"sha256": item["sha256"], "unit": "mm", "source_length_unit": source_unit, "source_to_mm": scale,
            **({"source_units_to_mm": dict(_LENGTH_UNITS.values())} if source_unit == "mixed" else {}),
            "shape": "assembly" if instances else "single_solid", "faces": len(shape.Faces()),
            "assembly_instances": instances,
            "mate_faces": [{"path": list(path), "faces": _face_catalog(leaf)} for path, leaf in datums.items()],
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


def _instance_translation(row, placement, origin):
    """! @brief 기판 목표점을 조립 로컬 좌표로 변환하고 원본 원점과의 차이를 구한다."""
    if "target_origin_mm" not in placement:
        return tuple(placement["translation_mm"])
    dx, dy, dz = (target - base for target, base in zip(placement["target_origin_mm"], row["translation_mm"]))
    angle = math.radians(math.remainder(row["yaw_deg"], 360))
    cosine, sine = math.cos(angle), math.sin(angle)
    target_local = (cosine * dx + sine * dy, -sine * dx + cosine * dy, dz)
    return tuple(target - base for target, base in zip(target_local, origin))


def _face_datum(face, kind):
    """! @brief 원본 평면의 외향 법선 또는 원통면의 해석축과 해당 기준점을 읽는다."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.gp import gp_Dir, gp_Pnt

    if kind == "plane":
        _require(face.geomType() == "PLANE", "메이트 원본 면이 평면이 아닙니다.")
        return gp_Pnt(*face.Center().toTuple()), gp_Dir(*face.normalAt().toTuple())
    _require(face.geomType() == "CYLINDER", "축 메이트에 원통면을 지정하십시오.")
    axis = BRepAdaptor_Surface(face.wrapped).Cylinder().Axis()
    return axis.Location(), axis.Direction()


def _face_catalog(leaf):
    """! @brief 미리보기에서 선택할 수 있는 원본 B-rep 평면 및 원통면 번호를 반환한다."""
    import cadquery as cq

    result = []
    for index, face in enumerate(cq.Shape.cast(leaf).Faces(), 1):
        kind = {"PLANE": "plane", "CYLINDER": "axis"}.get(face.geomType())
        if kind is not None:
            point, direction = _face_datum(face, kind)
            result.append({"index": index, "kind": kind, "point_mm": list(point.Coord()),
                           "direction": list(direction.Coord())})
    return result


def _mate_delta(source, reference, mate, reference_delta):
    """! @brief 원본 말단을 최단 회전한 뒤 평면 거리 또는 두 축의 수직 거리를 제거한다."""
    from OCP.gp import gp_Quaternion, gp_Trsf, gp_Vec

    def datum(solid, index):
        """! @brief 경로와 원본 고체에서 확인한 면을 읽는다."""
        faces = solid.Faces()
        _require(1 <= index <= len(faces), "원본 메이트 면 번호가 없습니다.")
        return _face_datum(faces[index - 1], mate["kind"])

    pivot, normal = datum(source, mate["face"])
    target, direction = datum(reference, mate["target_face"])
    target.Transform(reference_delta)
    direction.Transform(reference_delta)
    if mate["sense"] == "opposed":
        direction.Reverse()
    correction = gp_Trsf()
    correction.SetRotation(gp_Quaternion(gp_Vec(normal), gp_Vec(direction)))
    separation = gp_Vec(pivot, target)
    along = gp_Vec(direction).Multiplied(separation.Dot(gp_Vec(direction)))
    adjustment = along if mate["kind"] == "plane" else separation.Subtracted(along)
    # @brief 회전 중심인 면 기준점을 유지하고 제약에서 결정한 이동만 더한다.
    correction.SetTranslationPart(gp_Vec(pivot.Transformed(correction), pivot).Added(adjustment))
    return correction


def _local_deltas(row, instances, shapes):
    """! @brief 메이트 상대 말단의 최종 이동을 먼저 구하고 각 경로의 강체 변환을 한 번 계산한다."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

    offsets = row.get("instance_offsets", [])
    if offsets:
        validate_instance_offsets(offsets)
    placements = {tuple(item["path"]): item for item in offsets}
    _require(placements.keys() <= shapes.keys(), "STEP 원본의 말단 부품 경로를 확인하십시오.",
             field="part." + row["id"] + ".instance_offsets")
    origins = {tuple(item["path"]): tuple(axis[3] for axis in item["transform_mm"]) for item in instances}
    deltas = {}

    def solve(path):
        """! @brief 저장 시 순환 검사를 마친 상대 경로에서 조립 좌표의 변환을 구성한다."""
        if path in deltas:
            return deltas[path]
        edit = placements.get(path)
        delta = gp_Trsf()
        if edit is not None:
            if "mate" in edit:
                mate = dict(edit["mate"])
                other = tuple(mate["target_path"])
                for key, member in (("face", path), ("target_face", other)):
                    for replacement in row.get("instance_replacements", []):
                        if tuple(replacement["path"]) == member:
                            links = dict(replacement["faces"])
                            _require(mate[key] in links, "교체 부품의 메이트 면을 지정하십시오.")
                            mate[key] = links[mate[key]]
                _require(other in shapes, "상대 STEP 말단 경로가 없습니다.")
                delta = _mate_delta(shapes[path], shapes[other], mate, solve(other))
            else:
                origin = origins[path]
                for axis, angle in enumerate(edit.get("rotation_deg", [])):
                    if angle:
                        turn = gp_Trsf()
                        vector = gp_Dir(*(float(index == axis) for index in range(3)))
                        turn.SetRotation(gp_Ax1(gp_Pnt(*origin), vector), math.radians(math.remainder(angle, 360)))
                        delta.PreMultiply(turn)
                delta.SetTranslationPart(gp_Vec(delta.TranslationPart()).Added(gp_Vec(*_instance_translation(row, edit, origin))))
        deltas[path] = delta
        return delta

    for path in shapes:
        solve(path)
    return deltas


def _check_instance_clashes(row, shapes, tolerance):
    """! @brief 편집된 말단에서 체적이 겹치는 부품 경로를 보고한다."""
    placements = {tuple(item["path"]) for key in ("instance_offsets", "instance_replacements") for item in row.get(key, [])}
    field = "part." + row["id"] + ".instance_offsets"
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


def _assembly_export(row, instances, leaves, deltas):
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
    definitions, placed = {}, {}
    for instance in instances:
        path = tuple(instance["path"])
        matrix = instance["transform_mm"]
        original = gp_Trsf()
        original.SetValues(*(value for axis in matrix for value in axis))
        if path in leaves:
            local_shape = leaves[path].Moved(TopLoc_Location(original.Inverted()))
            location = local_shape.Location().Transformation()
            if all(abs(location.Value(i, j) - float(i == j)) <= 1e-12 for i in range(1, 4) for j in range(1, 5)):
                local_shape = local_shape.Located(TopLoc_Location())
            definitions.setdefault(instance["definition"], local_shape)
        location = deltas[path].Multiplied(original) if path in deltas else original
        placed[path] = TopLoc_Location(root.Multiplied(location))
    return {"definitions": definitions, "locations": placed, "instances": instances}


def _replacement_leaves(row, instances, leaves, storage):
    """! @brief 원본 말단의 로컬 원점에 독립 STEP 단일 고체를 놓고 교체 정의만 따로 공유한다."""
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    changes = {tuple(item["path"]): item for item in row.get("instance_replacements", [])}
    if not changes:
        return instances, leaves
    _require(changes.keys() <= leaves.keys(), "교체할 STEP 원본 말단 경로가 없습니다.")
    new_nodes, new_leaves, originals = [], dict(leaves), {}
    for node in instances:
        path = tuple(node["path"])
        if path in changes:
            item = changes[path]
            donor = storage.get(item["source_part_id"])
            _require(donor and donor["sha256"] == item["source_sha256"], "교체 원본의 식별자와 해시를 확인하십시오.")
            if donor["sha256"] not in originals:
                shape, _, _, nested, _ = _read_external(donor)
                _require(not nested, "말단 교체 원본에는 조립 대신 단일 고체가 필요합니다.")
                originals[donor["sha256"]] = shape.wrapped
            original = gp_Trsf()
            original.SetValues(*(value for axis in node["transform_mm"] for value in axis))
            new_leaves[path] = originals[donor["sha256"]].Moved(TopLoc_Location(original))
            node = {**node, "definition": "replacement:" + donor["sha256"]}
        new_nodes.append(node)
    return new_nodes, new_leaves


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
                                          "source_to_mm": scale, "assembly_instances": instances,
                                          **({"source_units_to_mm": dict(_LENGTH_UNITS.values())} if source_unit == "mixed" else {})}}
            if row.get("instance_replacements"):
                instances, leaves = _replacement_leaves(row, instances, leaves, storage)
                source_step["source_step"].update(effective_assembly_instances=instances,
                                                  instance_replacements=row["instance_replacements"])
            if instances:
                from OCP.TopLoc import TopLoc_Location

                originals = {path: cq.Shape.cast(leaf) for path, leaf in leaves.items()}
                deltas = _local_deltas(row, instances, originals)
                assembly_export["_step_assembly"] = _assembly_export(row, instances, leaves, deltas)
                if row.get("instance_offsets") or row.get("instance_replacements"):
                    placed_leaves = {path: cq.Shape.cast(leaf.Moved(TopLoc_Location(deltas[path])))
                                     for path, leaf in leaves.items()}
                    _check_instance_clashes(row, placed_leaves, projection["tolerance_mm"])
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
