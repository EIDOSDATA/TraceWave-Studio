"""! @brief AP242 STEP 교환과 같은 커널의 재입력 비교를 담당한다."""

from pathlib import Path

from rfad.adapters.cad.geometry import _require
from rfad.adapters.cad.bodies import _metrics


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
            "not_evaluated": ["independent CAD kernel", "manufacturing DRC", "RF accuracy", "full intended net connectivity",
                              "blind/buried vias and slots", "assembly placement", "source color preservation"]}
