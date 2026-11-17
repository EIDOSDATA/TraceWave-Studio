"""! @brief 도면의 실제 좌표/구멍/출처와 세 파일 parser의 거절 경계를 검증한다."""

from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
import unicodedata
from uuid import uuid4

from rfad.application.cad import build_cad_input
from rfad.domain.drawing_layout import layout, shape_loops, _wrapped
from rfad.domain.errors import ProjectError
from rfad.domain.precision_dimensions import dimensions
from test_cad_projection import cad_fixture, snapshot_for


PACKAGES = all(importlib.util.find_spec(name) for name in ("ezdxf", "reportlab", "pypdf"))
FONT = Path("C:/Windows/Fonts/malgun.ttf")


def fixture(format_name="svg"):
    """! @brief 미정 물성을 포함한 합성 계약시험 원본을 CAD 서비스로 투영한다."""
    document = cad_fixture()
    snapshot = snapshot_for(document)
    return {"schema": "rfad.exchange-input/0.1", "profile": "rfad.exchange.drawing/0.1",
            "run_id": str(uuid4()), "snapshot": snapshot, "format": format_name,
            "options": {"mode": "drawing", "sheet": "A4", "orientation": "landscape", "scale": 1.0,
                        "views": [{"kind": "layer", "layer_id": document["geometry"][0]["layer_id"]}],
                        "dimensions": True, "notes": True},
            "projection": build_cad_input(document, snapshot),
            "names": {row["id"]: "합성 객체 " + str(index + 1) for index, row in enumerate(document["geometry"])},
            "dimensions": [{"entity_id": row["id"], "label": "합성 객체 " + str(index + 1), "items": dimensions(document, row)}
                           for index, row in enumerate(document["geometry"])]}


def signed_area(loop):
    """! @brief writer 경계의 선적분을 독립적인 원/직선 해석식으로 계산한다."""
    total = 0
    for edge in loop:
        if edge["kind"] == "line":
            a, b = edge["start"], edge["end"]
            total += (a[0] * b[1] - a[1] * b[0]) / 2
        else:
            x, y = edge["center"]
            r = edge["radius"]
            a, delta = math.radians(edge["start_deg"]), math.radians(edge["sweep_deg"])
            b = a + delta
            total += (r * x * (math.sin(b) - math.sin(a)) - r * y * (math.cos(b) - math.cos(a)) + r*r*delta) / 2
    return total


class DrawingGeometryTests(unittest.TestCase):
    """! @brief 출력 패키지 없이 기본 도형의 독립 산술 기대값을 검증한다."""

    def test_round_caps_arc_both_directions_and_ring_area(self):
        """! @brief 선과 호의 끝단 면적을 빠뜨리거나 사각 끝단으로 바꾸지 않는다."""
        source = fixture()["projection"]["shapes"][0]
        self.assertAlmostEqual(signed_area(shape_loops(source)[0]), 9 * 0.5 + math.pi * 0.25**2, places=10)
        for sweep in (160, -160):
            shape = {"kind": "arc_path", "center_mm": [17, 20], "radius_mm": 8,
                     "width_mm": 1.2, "start_angle_deg": 25, "sweep_angle_deg": sweep}
            self.assertAlmostEqual(signed_area(shape_loops(shape)[0]), 8 * math.radians(160) * 1.2 + math.pi * .6**2, places=9)
        shape["sweep_angle_deg"] = 360
        outer, hole = shape_loops(shape)
        self.assertAlmostEqual(abs(signed_area(outer)) - abs(signed_area(hole)), math.pi * (8.6**2 - 7.4**2), places=9)

    def test_layout_is_originally_associated_and_scale_is_not_auto_fit(self):
        """! @brief 치수 원본/단위/미정을 보존하고 지정 축척을 조용히 바꾸지 않는다."""
        data = fixture()
        data["dimensions"][0]["items"].append({"key": "missing.fixture", "label": "미정 시험 치수", "value": None,
                                               "unit": "mm", "status": "missing", "anchors_mm": [], "source_refs": []})
        before = deepcopy(data)
        page = layout(data)[0]
        self.assertEqual(data, before)
        self.assertEqual(page["viewports"][0]["transform"]["scale"], 1)
        self.assertTrue(any("미정 시험 치수: 미정" in p.get("text", "") for p in page["primitives"]))
        bars = [p for p in page["primitives"] if p["kind"] == "line" and p["start"] == [16, 48]]
        self.assertEqual(bars[0]["end"], [66, 48])
        data["options"]["scale"] = 100
        with self.assertRaises(ProjectError):
            layout(data)

    def test_fabrication_has_no_annotations_and_keeps_global_coordinates(self):
        """! @brief 제조 형상에는 도면 제목이나 축척 변환을 섞지 않는다."""
        data = fixture()
        data["options"].update(mode="fabrication_geometry", dimensions=False, notes=False)
        page = layout(data)[0]
        self.assertFalse(any(p["role"] != "geometry" for p in page["primitives"]))
        self.assertEqual(page["primitives"][0]["loops"][0][0]["start"], [1.0, .75])
        data["options"]["notes"] = True
        with self.assertRaises(ProjectError):
            layout(data)

    def test_bottom_view_mirrors_only_drawing_and_retains_hole_topology(self):
        """! @brief 화면 뒤면 반전과 제조 원본 좌표를 분리한다."""
        data = fixture()
        lower = deepcopy(data["projection"]["layers"][-1])
        lower.update(id=str(uuid4()), name="하부 동박", z_min_mm=-1.035)
        data["projection"]["layers"].insert(0, lower)
        shape = data["projection"]["shapes"][0]
        shape["layer_id"] = lower["id"]
        shape.update(kind="planar_region", outer_mm=[[1, 1], [11, 1], [11, 11], [1, 11]], holes_mm=[[[3, 3], [5, 3], [5, 5], [3, 5]]])
        data["options"]["views"] = [{"kind": "layer", "layer_id": lower["id"]}]
        page = layout(data)[0]
        self.assertTrue(page["viewports"][0]["transform"]["mirror_x"])
        primitive = next(p for p in page["primitives"] if p.get("source_id") == shape["id"])
        self.assertAlmostEqual(sum([-abs(signed_area(loop)) if i else abs(signed_area(loop)) for i, loop in enumerate(primitive["loops"])]), 96)
        data["options"].update(mode="fabrication_geometry", dimensions=False, notes=False)
        self.assertFalse(layout(data)[0]["viewports"][0]["transform"]["mirror_x"])

    def test_nonfinite_dimensions_and_unknown_geometry_are_blocked(self):
        """! @brief 무한 좌표나 미지원 도형을 누락된 정상 출력으로 바꾸지 않는다."""
        data = fixture()
        data["projection"]["shapes"][0]["width_mm"] = float("nan")
        with self.assertRaises(ProjectError):
            layout(data)

    def test_actual_stack_section_does_not_fill_empty_copper_layer(self):
        """! @brief 단면을 지나는 도체만 그리고 빈 도체 층을 임의의 동박판으로 채우지 않는다."""
        data = fixture()
        data["options"]["views"] = [{"kind": "stackup"}]
        page = layout(data)[0]
        geometry = [p for p in page["primitives"] if p["role"] == "geometry"]
        self.assertEqual(len(geometry), 1)
        self.assertEqual(geometry[0]["source_id"], data["projection"]["layers"][0]["id"])
        self.assertAlmostEqual(abs(signed_area(geometry[0]["loops"][0])), 60.0)
        self.assertIn("Y=20 mm", page["viewports"][0]["label"])

    def test_dimensions_switch_and_large_input_do_not_silently_truncate(self):
        """! @brief 치수 끔을 지키고 많은 치수는 계속 쪽으로 보존한다."""
        data = fixture()
        row = deepcopy(data["dimensions"][0]["items"][0])
        data["dimensions"][0]["items"] = [{**row, "key": "fixture." + str(i), "label": "연관 치수 " + str(i)} for i in range(100)]
        pages = layout(data)
        text = "\n".join(p.get("text", "") for page in pages for p in page["primitives"])
        self.assertIn("연관 치수 99", text)
        self.assertGreater(len(pages), 1)
        data["options"]["dimensions"] = False
        page = layout(data)[0]
        self.assertFalse(page["viewports"][0]["dimensions"])
        self.assertFalse(any("외형 X 범위" in p.get("text", "") for p in page["primitives"]))

    def test_wrap_keeps_numeric_unit_and_words_together(self):
        """! @brief 면적 단위의 m/m^2 분리와 영문 단어 중간 줄바꿈을 막는다."""
        original = "접지면 01 / 구멍을 뺀 도체 면적: 1984 mm^2"
        lines = _wrapped(original, 63, 2.8)
        self.assertTrue(any("1984 mm^2" in value for value in lines), lines)
        self.assertEqual("".join(lines).replace(" ", ""), original.replace(" ", ""))
        english = _wrapped("Test outer conductor thick copper", 25, 2.8)
        self.assertTrue(any("conductor" in value for value in english), english)
        self.assertTrue(any("copper" in value for value in english), english)
        dense = "공백없는매우긴객체명" * 10
        self.assertEqual("".join(_wrapped(dense, 20, 2.8)), dense)
        negative = _wrapped("값 -1.234e-5 mm 단위 보존", 30, 2.8)
        self.assertTrue(any("-1.234e-5 mm" in value for value in negative))
        data = fixture()
        data["projection"]["shapes"][0]["kind"] = "slot_without_contract"
        with self.assertRaises(ProjectError):
            layout(data)

    def test_stackup_wrap_keeps_assignment_value_and_unit_together(self):
        """! @brief 적층 주석의 z=/t= 접두어와 구두점이 붙어도 값과 단위를 나누지 않는다."""
        original = "Test dielectric: z=0.035 mm, t=0.93 mm"
        for width in (48, 63, 90):
            with self.subTest(width_mm=width):
                lines = _wrapped(original, width, 2.8)
                self.assertTrue(any("z=0.035 mm," in line for line in lines), lines)
                self.assertTrue(any("t=0.93 mm" in line for line in lines), lines)
                self.assertEqual("".join(lines).replace(" ", ""), original.replace(" ", ""))
        scientific = "중심: x=-1.234e-5 mm; 두께(t=0.93 mm)"
        lines = _wrapped(scientific, 63, 2.8)
        self.assertTrue(any("x=-1.234e-5 mm;" in line for line in lines), lines)
        self.assertTrue(any("두께(t=0.93 mm)" in line for line in lines), lines)
        self.assertEqual("".join(lines).replace(" ", ""), scientific.replace(" ", ""))


@unittest.skipUnless(PACKAGES, "고정 exchange 환경의 PDF/DXF reader 패키지가 필요합니다.")
class DrawingFileTests(unittest.TestCase):
    """! @brief 별도 writer와 reader에서 실제 파일을 검사한다."""

    def test_svg_dxf_and_pdf_reopen_source_unknown_and_bindings(self):
        """! @brief 세 형식의 실제 도형/단위와 sidecar 원문을 저장 후 다시 검사한다."""
        from rfad.adapters.exchange.drawing import generate, verify
        for format_name in ("svg", "dxf", "pdf"):
            if format_name == "pdf" and not FONT.is_file():
                continue
            with self.subTest(format=format_name), tempfile.TemporaryDirectory() as directory:
                data = fixture(format_name)
                before = deepcopy(data)
                manifest = generate(data, Path(directory), font_path=FONT)
                self.assertEqual(data, before)
                self.assertEqual(verify(data, Path(directory), manifest)["status"], "passed_profile")
                self.assertFalse(manifest["verification"]["kernel_independent"])
                self.assertFalse(manifest["verification"]["manufacturing_verified"])
                sidecar = json.loads((Path(directory) / "sidecar.json").read_text("utf-8"))
                self.assertEqual(sidecar["source_semantics"], data["projection"]["source_semantics"])
                self.assertEqual(sidecar["source_bindings"]["dimensions"], data["dimensions"])
                self.assertIsNone(sidecar["source_semantics"]["materials"][0]["epsilon_r"]["value_si"])

    def test_actual_coordinate_tamper_fails_in_independent_reader(self):
        """! @brief 해시 검사를 생략한 별도 parser 호출도 실제 좌표 변조를 거부한다."""
        from rfad.adapters.exchange.drawing import generate
        from rfad.adapters.exchange.drawing_readers import read_svg
        with tempfile.TemporaryDirectory() as directory:
            data = fixture()
            generate(data, Path(directory))
            path = Path(directory) / "drawing-01.svg"
            raw = path.read_text("utf-8")
            import xml.etree.ElementTree as ET
            root = ET.fromstring(raw)
            target = root.find("{http://www.w3.org/2000/svg}g/{http://www.w3.org/2000/svg}path")
            target.set("d", target.get("d").replace("L ", "L 777 ", 1))
            path.write_bytes(ET.tostring(root))
            with self.assertRaises((ProjectError, ValueError)):
                read_svg(path, layout(data)[0])

    def test_detail_clipping_and_signed_arcs_survive_all_readers(self):
        """! @brief 원호와 급전 상세 영역의 실제 자르기 정보가 보존된다."""
        from rfad.adapters.exchange.drawing import generate, verify
        for format_name in ("svg", "dxf", "pdf"):
            if format_name == "pdf" and not FONT.is_file():
                continue
            with self.subTest(format=format_name), tempfile.TemporaryDirectory() as directory:
                data = fixture(format_name)
                data["projection"]["shapes"][0].update(kind="arc_path", center_mm=[12, 15], radius_mm=8,
                                                        start_angle_deg=165, sweep_angle_deg=-140, width_mm=1.2)
                data["options"]["views"] = [{"kind": "detail", "layer_id": data["projection"]["shapes"][0]["layer_id"],
                                             "bounds_mm": [8, 12, 18, 22], "label": "급전 주변 명시 영역"}]
                manifest = generate(data, Path(directory), font_path=FONT)
                self.assertEqual(verify(data, Path(directory), manifest)["status"], "passed_profile")

    def test_pth_holes_unknown_tool_and_actual_stack_sections(self):
        """! @brief 실제 Quantity 비아 원본에서 중공 단면/미정 공구/출처를 보존한다."""
        from test_cad_copper_features import copper_document
        from test_design import quantity, unknown
        from rfad.adapters.exchange.drawing import generate, verify
        document = copper_document()
        for shape in document["geometry"]:
            shape["center"][1] = quantity(30, "mm")
            if shape["kind"] == "via":
                shape["tool_hole_diameter"] = unknown("length", "mm")
                shape["tool_hole_diameter"]["source_refs"] = ["실제 공구값은 미확보"]
        for format_name in ("svg", "dxf", "pdf"):
            if format_name == "pdf" and not FONT.is_file():
                continue
            with self.subTest(format=format_name), tempfile.TemporaryDirectory() as directory:
                data = fixture(format_name)
                data["snapshot"] = snapshot_for(document)
                data["projection"] = build_cad_input(document, data["snapshot"])
                data["names"] = {row["id"]: row["kind"] for row in document["geometry"]}
                data["dimensions"] = [{"entity_id": row["id"], "label": row["kind"], "items": dimensions(document, row)} for row in document["geometry"]]
                layer = data["projection"]["layers"][-1]
                data["options"]["views"] = [{"kind": "layer", "layer_id": layer["id"]}, {"kind": "stackup"}]
                pages = layout(data)
                via_id = next(row["id"] for row in document["geometry"] if row["kind"] == "via")
                sections = [p for p in pages[1]["primitives"] if p.get("source_id") == via_id and p["role"] == "geometry"]
                span = layer["z_min_mm"] + layer["thickness_mm"] - data["projection"]["layers"][0]["z_min_mm"]
                self.assertEqual(len(sections), 2)
                self.assertAlmostEqual(sum(abs(signed_area(p["loops"][0])) for p in sections), 2 * .025 * span, places=9)
                manifest = generate(data, Path(directory), font_path=FONT)
                self.assertEqual(verify(data, Path(directory), manifest)["status"], "passed_profile")
                sidecar = json.loads((Path(directory) / "sidecar.json").read_text("utf-8"))
                via = next(row for row in sidecar["source_semantics"]["geometry"] if row["kind"] == "via")
                self.assertIsNone(via["tool_hole_diameter"]["value_si"])
                self.assertEqual(via["tool_hole_diameter"]["source_refs"], ["실제 공구값은 미확보"])

    def test_fill_or_axis_tamper_and_source_change_are_rejected(self):
        """! @brief 같은 경로 데이터라도 채움/단위/원문 소유권을 바꾸면 거부한다."""
        import xml.etree.ElementTree as ET
        from rfad.adapters.exchange.drawing import generate, verify
        from rfad.adapters.exchange.drawing_readers import read_svg
        with tempfile.TemporaryDirectory() as directory:
            data = fixture()
            output = Path(directory)
            manifest = generate(data, output)
            wrong = deepcopy(data)
            wrong["projection"]["source_semantics"]["metadata"]["name"] += "변조"
            with self.assertRaises(ProjectError):
                verify(wrong, output, manifest)
            path = output / "drawing-01.svg"
            root = ET.fromstring(path.read_bytes())
            target = root.findall("{http://www.w3.org/2000/svg}g")[1][0]
            target.set("fill", "none")
            path.write_bytes(ET.tostring(root))
            with self.assertRaises(ProjectError):
                read_svg(path, layout(data)[0])

    @unittest.skipUnless(FONT.is_file(), "한글 TTF가 있는 Windows 환경이 필요합니다.")
    def test_pdf_swapped_labels_keep_coordinates_but_fail_object_binding(self):
        """! @brief 페이지 전체 문자 집합과 좌표가 같아도 객체별 문자를 바꾸면 거부한다."""
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import NameObject
        from rfad.adapters.exchange.drawing import generate
        from rfad.adapters.exchange.drawing_readers import read_pdf
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            data = fixture("pdf")
            generate(data, output, font_path=FONT)
            expected = layout(data)
            reader = PdfReader(output / "drawing.pdf")
            writer = PdfWriter()
            writer.append(reader)
            page = writer.pages[0]
            stream = page.get_contents()
            operations = stream.operations
            selected = [index for index, primitive in enumerate(expected[0]["primitives"])
                        if primitive["kind"] == "text" and primitive["height_mm"] == 2.8
                        and primitive["text"].startswith("외형 ")]
            self.assertEqual(len(selected), 2)
            current, positions = None, []
            original_matrices = [deepcopy(values) for values, op in operations if op == b"Tm"]
            for index, (values, op) in enumerate(operations):
                if op == b"BDC":
                    current = int(values[1]["/Id"])
                elif op == b"EMC":
                    current = None
                elif op == b"Tj" and current in selected:
                    positions.append(index)
            self.assertEqual(len(positions), 2)
            a, b = positions
            operations[a], operations[b] = (operations[b][0], operations[a][1]), (operations[a][0], operations[b][1])
            self.assertEqual([values for values, op in operations if op == b"Tm"], original_matrices)
            stream.operations = operations
            page[NameObject("/Contents")] = stream
            changed = output / "swapped.pdf"
            writer.write(changed)
            # @brief 옛 페이지 단위 검사는 통과하는 조건임을 먼저 확인한다.
            recovered = PdfReader(changed).pages[0].extract_text()
            for index in selected:
                self.assertIn(expected[0]["primitives"][index]["text"], recovered)
            with self.assertRaises(ProjectError) as error:
                read_pdf(changed, expected)
            self.assertEqual(error.exception.code, "E_HASH")
            self.assertIn("원본 객체", error.exception.message)

    @unittest.skipUnless(FONT.is_file(), "한글 TTF가 있는 Windows 환경이 필요합니다.")
    def test_pdf_missing_glyph_and_unsupported_composition_keep_original(self):
        """! @brief 글리프 없는 문자와 조합형 원문을 빈 글자나 임의 정규화로 바꾸지 않는다."""
        from rfad.adapters.exchange.drawing import generate
        for name, reason, codepoint in [("검증 " + chr(0x1F9EA), "missing_font_glyph", "U+1F9EA"),
                                        ("검증 " + chr(0x20000), "missing_font_glyph", "U+20000"),
                                        (unicodedata.normalize("NFD", "한글"), "complex_text_shaping_not_supported", "U+1112"),
                                        ("한" + chr(0x200D) + "글", "complex_text_shaping_not_supported", "U+200D")]:
            with self.subTest(reason=reason, codepoint=codepoint), tempfile.TemporaryDirectory() as directory:
                data = fixture("pdf")
                data["projection"]["source_semantics"]["metadata"]["name"] = name
                before = deepcopy(data)
                output = Path(directory)
                with self.assertRaises(ProjectError) as caught:
                    generate(data, output, font_path=FONT)
                self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
                self.assertEqual(caught.exception.details["reason"], reason)
                self.assertIn(codepoint, caught.exception.details["codepoints"])
                self.assertFalse(caught.exception.details["source_modified"])
                self.assertEqual(data, before)
                self.assertFalse((output / "manifest.json").exists())
                self.assertFalse((output / "drawing.pdf").exists())

    def test_existing_output_and_missing_pdf_font_do_not_publish_manifest(self):
        """! @brief 덮어쓰기와 한글 글꼴 없는 부분 출력을 정상 패키지로 게시하지 않는다."""
        from rfad.adapters.exchange.drawing import generate
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "keep.bin").write_bytes(b"original")
            with self.assertRaises(ProjectError):
                generate(fixture(), output)
            self.assertEqual((output / "keep.bin").read_bytes(), b"original")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProjectError):
                generate(fixture("pdf"), Path(directory), font_path=None)
            self.assertFalse((Path(directory) / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
