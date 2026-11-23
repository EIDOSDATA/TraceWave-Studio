"""! @brief AP242 STEP 교환과 같은 커널의 재입력 비교를 담당한다."""

from pathlib import Path

from rfad.adapters.cad.geometry import _require
from rfad.adapters.cad.bodies import _metrics


def _assembly_parts(data):
    """! @brief 원본 정의, 자식의 편집 결과 및 상대 위치가 같은 하위조립끼리만 공유한다."""
    from OCP.TopLoc import TopLoc_Location

    rows = {tuple(row["path"]): row for row in data["instances"]}
    children = {path: [] for path in rows}
    local, keys = {}, {}
    for path in rows:
        if path == (1,):
            continue
        parent = path[:-1]
        children[parent].append(path)
        base = TopLoc_Location() if parent == (1,) else data["locations"][parent]
        local[path] = base.Inverted().Multiplied(data["locations"][path])
    for path, row in reversed(list(rows.items())):
        members = []
        for child in children[path]:
            transform = local[child].Transformation()
            coordinates = tuple(round(transform.Value(i, j), 10) for i in range(1, 4) for j in range(1, 5))
            members.append((keys[child], rows[child]["name"], coordinates))
        keys[path] = (row["assembly"], row["definition"], tuple(members))
    return rows, children, local, keys


def _write_assembly(tool, body):
    """! @brief 배치별 자식 편집은 구분하고 동일 조립 및 말단 정의는 한 번만 작성한다."""
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_Label

    def name(label, text):
        """! @brief 제품 정의와 인스턴스 이름을 각각 보존한다."""
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(text))

    data = body["_step_assembly"]
    rows, children, local, keys = _assembly_parts(data)
    definitions = {}
    def emit(path):
        """! @brief 동일한 원본의 같은 조립 상태를 참조하고 다른 편집 상태에 새 정의를 부여한다."""
        key, row = keys[path], rows[path]
        if key in definitions:
            return definitions[key]
        title = row.get("definition_name") or row["name"] or ".".join(map(str, path))
        definition = tool.NewShape() if row["assembly"] else tool.AddShape(data["definitions"][row["definition"]], False)
        name(definition, body["name"] if path == (1,) else title)
        product = TDF_Label()
        if not row["assembly"] and tool.GetReferredShape_s(definition, product):
            name(product, title)
        definitions[key] = definition
        for child in children[path]:
            component = tool.AddComponent(definition, emit(child), local[child])
            _require(not component.IsNull(), "STEP 조립 인스턴스를 구성하지 못했습니다.")
            name(component, rows[child]["name"] or ".".join(map(str, child)))
        return definition
    emit((1,))


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
        if "_step_assembly" in body:
            _write_assembly(shape_tool, body)
        else:
            label = shape_tool.AddShape(body["shape"].wrapped, False)
            TDataStd_Name.Set_s(label, TCollection_ExtendedString(body["name"]))
    shape_tool.UpdateAssemblies()
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.SetPropsMode(True)
    _require(writer.Transfer(document, STEPControl_AsIs), "AP242 변환이 실패했습니다.")
    _require(writer.Write(str(path)) == IFSelect_RetDone, "STEP 파일 저장이 실패했습니다.", code="E_DISK")


def _read_step_shapes(path: Path, assemblies=None) -> dict:
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
        if assemblies is not None and shape_tool.IsAssembly_s(label):
            from rfad.adapters.cad.physical import _assembly_instances
            instances, leaves = _assembly_instances(shape_tool, label)
            assemblies[text] = (instances, {key: cq.Shape.cast(leaf) for key, leaf in leaves.items()})
    return result


def read_step(path: Path) -> dict:
    """! @brief 별도 reader가 복원한 이름별 측정값만 외부 호출자에 반환한다."""
    from rfad.adapters.cad.physical import external_metrics

    return {name: (external_metrics if name.startswith("environment_") else _metrics)(shape)
            for name, shape in _read_step_shapes(path).items()}


def verify_assemblies(bodies, assemblies, tolerance):
    """! @brief 보존 계층, 반복 말단과 개별 경계를 STEP 재입력 바이트에서 검사한다."""
    from rfad.adapters.cad.physical import external_metrics

    def signature(instances, keys=None):
        """! @brief 재입력한 모든 조립 및 말단 정의의 공유 관계를 최초 발생의 경로로 비교한다."""
        first = {}
        result = []
        for row in instances:
            path = tuple(row["path"])
            key = row["definition"] if keys is None else keys[path]
            result.append((path, row["assembly"], first.setdefault(key, path)))
        return result

    verified = []
    for body in bodies:
        source = body.get("source_step", {})
        if not source.get("hierarchy_in_step"):
            continue
        name = body["name"]
        _require(name in assemblies, "STEP 재입력에서 설치물의 조립 계층을 찾을 수 없습니다.")
        nodes, leaves = assemblies[name]
        _, _, _, keys = _assembly_parts(body["_step_assembly"])
        original = source.get("effective_assembly_instances", source["assembly_instances"])
        _require(signature(nodes) == signature(original, keys),
                 "STEP 재입력에서 조립 경로나 조립 및 말단 정의의 공유 관계가 달라졌습니다.")
        for item in source["placed_instances"]:
            actual = external_metrics(leaves[tuple(item["path"])])["bbox_mm"]
            _require(max(abs(a - b) for a, b in zip(actual, item["bbox_mm"])) <= tolerance,
                     "STEP 재입력에서 조립 말단의 위치가 달라졌습니다.")
        verified.append({"name": name, "instances": len(nodes), "leaves": len(leaves),
                         "shared_leaf_definitions": len({row["definition"] for row in nodes if not row["assembly"]})})
        original_groups = [row["definition"] for row in original if row["assembly"] and len(row["path"]) > 1]
        if len(original_groups) > len(set(original_groups)):
            actual_groups = [row["definition"] for row in nodes if row["assembly"] and len(row["path"]) > 1]
            verified[-1].update(subassembly_occurrences=len(actual_groups), subassembly_definitions=len(set(actual_groups)))
    return verified


def _compare_external(name, left, right, tolerance):
    """! @brief 임의 방향 외부 고체의 경계, 중심과 부피만 대조한다."""
    bbox_error = max(abs(a - b) for a, b in zip(left["bbox_mm"], right["bbox_mm"]))
    center_error = max(abs(a - b) for a, b in zip(left["center_mm"], right["center_mm"]))
    volume_error = abs(left["volume_mm3"] - right["volume_mm3"])
    volume_tolerance = max(tolerance ** 3, left["volume_mm3"] * 1e-7)
    _require(bbox_error <= tolerance and center_error <= tolerance and volume_error <= volume_tolerance,
             "외부 고체의 경계, 중심 또는 부피가 STEP 재입력에서 달라졌습니다.")
    return {"name": name, "bbox_error_mm": bbox_error, "center_error_mm": center_error,
            "volume_error_mm3": volume_error, "volume_tolerance_mm3": volume_tolerance, "solid_count": right["solid_count"]}


def _compare(expected: dict, actual: dict, tolerance: float) -> dict:
    """! @brief 이름별 고체 수, 경계, 중심과 부피의 교환 오차를 검증한다."""
    _require(set(expected) == set(actual), "STEP 재입력에서 stable body 이름 또는 객체 수가 달라졌습니다.")
    comparisons = []
    for name in sorted(expected):
        left, right = expected[name], actual[name]
        _require(left["solid_count"] == right["solid_count"], "STEP 재입력에서 연결 성분 수가 달라졌습니다.")
        if "section_loop_count" not in left:
            comparisons.append(_compare_external(name, left, right, tolerance))
            continue
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
            "not_evaluated": ["independent CAD kernel", "manufacturing DRC", "RF accuracy", "full intended net connectivity",
                              "blind/buried vias and slots", "assembly placement", "source color preservation"]}
