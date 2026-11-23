"""! @brief 혼합 길이 단위와 두 번 배치한 같은 STEP 하위조립 정의를 독립 입력으로 검증한다."""
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import json
import unittest
import re


def source_assembly(path):
    """! @brief 하나의 XCAF 하위조립 정의를 같은 포인터로 두 번 배치한다."""
    import cadquery as cq
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Controller
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    def name(label, text):
        """! @brief 정의 및 발생 이름을 원본 문서에 부여한다."""
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(text))
    def place(owner, child, text, x):
        """! @brief XCAF의 실제 자식 정의 참조와 상대 변환을 구성한다."""
        trsf = gp_Trsf()
        trsf.SetTranslation(gp_Vec(x, 0, 0))
        name(tool.AddComponent(owner, child, TopLoc_Location(trsf)), text)

    root, group = tool.NewShape(), tool.NewShape()
    name(root, "frame")
    name(group, "rack")
    solid = tool.AddShape(cq.Solid.makeBox(1, 2, 3).wrapped, False)
    name(solid, "inch_block")
    small = tool.AddShape(cq.Solid.makeBox(2, 2, 2).wrapped, False)
    name(small, "mm_block")
    place(group, solid, "large", 0)
    place(group, small, "small", 40)
    place(root, group, "west", 10)
    place(root, group, "east", 110)
    tool.UpdateAssemblies()
    STEPControl_Controller.Init_s()
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    Interface_Static.SetCVal_s("write.step.schema", "AP242DIS")
    writer = STEPCAFControl_Writer()
    writer.Transfer(document, STEPControl_AsIs)
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError("독립 STEP 시험 원본을 만들 수 없습니다.")


def mixed_source(path):
    """! @brief 독립 STEP 데이터의 첫 고체만 inch 표현 문맥으로 바꾸고 두 조립 배치는 mm로 둔다."""
    source_assembly(path)
    raw = path.read_text("ascii")
    entities = {int(n): text for n, text in re.findall(r"#(\d+)\s*=\s*(.*?);", raw, re.S)}
    rep, second = [text for text in entities.values() if text.startswith("ADVANCED_BREP_SHAPE_REPRESENTATION")]
    def length_id(text):
        """! @brief 지정한 표현이 참조하는 3D 문맥의 첫 단위 식별자를 반환한다."""
        context = entities[int(re.findall(r"#(\d+)", text)[-1])]
        return int(re.search(r"GLOBAL_UNIT_ASSIGNED_CONTEXT\s*\(\s*\(\s*#(\d+)", context)[1])
    old, other = length_id(rep), length_id(second)
    if old == other or ".MILLI." not in entities[old] or ".MILLI." not in entities[other]:
        raise ValueError("독립 시험 원본에 분리된 두 mm 문맥이 필요합니다.")
    dim = max(entities) + 1
    conversion = dim + 1
    raw = re.sub(r"#" + str(old) + r"\s*=\s*[^;]+;",
                 f"#{old} = ( CONVERSION_BASED_UNIT('INCH',#{conversion}) LENGTH_UNIT() NAMED_UNIT(#{dim}) );", raw)
    raw = raw.replace("ENDSEC;\nEND-ISO-10303-21;",
                      f"#{dim} = DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.);\n"
                      f"#{conversion} = LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#{other});\nENDSEC;\nEND-ISO-10303-21;")
    path.write_text(raw, "ascii")

def subassembly_references(path):
    """! @brief 커널을 사용하지 않고 STEP 사용 발생의 부모와 자식 제품 정의 번호를 직접 읽는다."""
    text = path.read_text("ascii")
    return {name: (parent, target) for name, parent, target in re.findall(
        r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\(\s*'[^']*',\s*'(west|east)',\s*'[^']*',\s*#(\d+),\s*#(\d+)", text, re.S)}


@unittest.skipUnless(importlib.util.find_spec("cadquery"), "격리 CAD 환경이 필요합니다.")
class StepSharedAssemblyTests(unittest.TestCase):
    """! @brief 공유된 하위조립에 개별 편집이 있으면 그 발생에만 새 정의가 생기는지 검사한다."""

    def test_shared_definitions_and_mixed_length_contexts(self):
        """! @brief 혼합 단위 입출력, 원본 보존 및 배치 변경에 따른 정의 분리를 실제 B-rep에서 대조한다."""
        from rfad.adapters.cad.native import build_package
        from rfad.adapters.cad.physical import inspect_step
        from rfad.adapters.cad.step_io import _read_step_shapes
        from rfad.domain.errors import ProjectError
        from rfad.domain.physical_setup import KEY
        from test_cad_native import fixture, identity
        from test_step_replacement import source_file

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "mixed.step"
            mixed_source(path)
            original = path.read_bytes()
            original_refs = subassembly_references(path)
            self.assertEqual(original_refs["west"], original_refs["east"])
            source = source_file(path)
            detail = inspect_step(source)
            self.assertEqual((detail["source_length_unit"], detail["source_to_mm"], detail["source_units_to_mm"]),
                             ("mixed", None, {"mm": 1., "inch": 25.4}))
            expected_volume = 2 * (25.4**3 * 6 + 8)
            self.assertAlmostEqual(detail["volume_mm3"], expected_volume, places=6)
            part = identity("shared-rack")
            sample = fixture()
            row = {"id": part, "kind": "step", "material_id": None, "yaw_deg": 0, "translation_mm": [0, 0, 12]}
            sample["environment_parts"] = [row]
            sample["source_semantics"]["extensions"] = {KEY: {"parts": [{"id": part, "step": source}]}}
            for label, offset in (("shared", 0), ("one-child", 5)):
                if offset:
                    row["instance_offsets"] = [{"path": [1, 2, 2], "translation_mm": [offset, 0, 0]}]
                package = root / label
                result = build_package(sample, package)
                sidecar = json.loads((package / "sidecar.json").read_bytes())
                saved = next(r["source_step"] for r in sidecar["body_map"] if r["id"] == part)
                self.assertEqual(saved["source_units_to_mm"], detail["source_units_to_mm"])
                self.assertEqual(saved["sha256"], source["sha256"])
                tree, = result["validation"]["environment_assembly_hierarchy"]
                self.assertEqual((tree["instances"], tree["leaves"], tree["shared_leaf_definitions"]), (7, 4, 2))
                self.assertEqual((tree["subassembly_occurrences"], tree["subassembly_definitions"]), (2, 2 if offset else 1))
                written = package / "model.step"
                records = written.read_text("ascii")
                for name in ("rack", "inch_block", "mm_block"):
                    self.assertRegex(records, r"PRODUCT\(\s*'" + name + r"'")
                refs = subassembly_references(written)
                self.assertEqual(refs["west"][0], refs["east"][0])
                self.assertEqual(refs["west"][1] == refs["east"][1], not offset)
                assemblies = {}
                _read_step_shapes(written, assemblies)
                _, leaves = assemblies["environment_" + part]
                for path_index, x in enumerate((10,110), 1):
                    large = leaves[(1,path_index,1)].BoundingBox()
                    small = leaves[(1,path_index,2)].BoundingBox()
                    for got, expected in ((large.xmin,x),(large.ymin,0),(large.zmin,12),
                                          (large.xlen,25.4),(large.ylen,50.8),(large.zlen,76.2),
                                          (small.xmin,x+40+(offset if path_index == 2 else 0)),(small.xlen,2)):
                        self.assertAlmostEqual(got, expected, places=6)
            self.assertEqual(path.read_bytes(), original)
            for old, new in ((b"LENGTH_MEASURE(25.4)", b"LENGTH_MEASURE(12.7)"),
                             (b"CONVERSION_BASED_UNIT('INCH'", b"CONVERSION_BASED_UNIT('CUSTOM'")):
                bad = root / "unsupported.step"
                bad.write_bytes(original.replace(old, new))
                with self.assertRaises(ProjectError) as caught:
                    inspect_step(source_file(bad))
                self.assertEqual(caught.exception.code, "E_UNIT")
