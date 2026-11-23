"""! @brief IPC-2581C의 반복, 단위와 특수 제조 원문을 독립 XML 판독으로 확인한다."""

from hashlib import sha256
import os
from pathlib import Path
import unittest
from xml.etree import ElementTree

from rfad.adapters.exchange import ipc_panel
from rfad.domain.errors import ProjectError


SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "manufacturing" / "ipc2581c_special_drill.xml"
NS = "{http://webstds.ipc.org/2581}"


class IpcPanelTests(unittest.TestCase):
    """! @brief 원본의 도금 span, 깊이, 안티패드 형상과 보드 반복을 비교한다."""

    def test_rotated_panel_roundtrip_and_source_declarations(self):
        """! @brief 두 축 반복의 실제 위치와 특수 홀/랜드의 원래 속성을 각각 대조한다."""
        original = SOURCE.read_bytes()
        result = ipc_panel.build(original, [2, 3], [30, 47], 3, 90)
        self.assertEqual(ipc_panel.build(original, [2, 3], [30, 47], 3, 90), result)
        self.assertEqual(SOURCE.read_bytes(), original)
        expected = ipc_panel.read(original)
        observed = ipc_panel.read(result)
        self.assertEqual(expected["source_sha256"], sha256(original).hexdigest())
        self.assertEqual(observed["units"], "INCH")
        self.assertEqual(observed["manufacturing_declarations"], expected["manufacturing_declarations"])
        [panel] = observed["panels"]
        [repeat] = panel["repeats"]
        self.assertEqual(panel["outline_mm"], [[0, 0], [61.4, 0], [61.4, 138.1], [0, 138.1], [0, 0]])
        self.assertEqual(repeat["angle_deg"], 90)
        self.assertFalse(repeat["mirror"])
        self.assertEqual(repeat["count"], [2, 3])
        self.assertEqual(repeat["pitch_mm"], [30, 47])
        self.assertEqual(repeat["origin_mm"], [25.86, 5.54])
        src, out = (ElementTree.fromstring(raw) for raw in (original, result))
        steps = NS + "Ecad/" + NS + "CadData/" + NS + "Step"
        original_board = src.find(steps)
        actual_board, panel_node = out.findall(steps)
        self.assertEqual(ElementTree.tostring(actual_board), ElementTree.tostring(original_board))
        step_ref = panel_node.find(NS + "StepRepeat")
        origins = {(round((float(step_ref.get("x")) + i * float(step_ref.get("dx"))) * 25.4, 6),
                    round((float(step_ref.get("y")) + j * float(step_ref.get("dy"))) * 25.4, 6))
                   for i in range(2) for j in range(3)}
        self.assertEqual(origins, {(25.86, 5.54), (55.86, 5.54), (25.86, 52.54), (55.86, 52.54),
                                   (25.86, 99.54), (55.86, 99.54)})
        self.assertIn(("z_axis_dimension", "0.045"),
                      {(row["kind"], row["attributes"].get("depth")) for row in observed["manufacturing_declarations"]})
        shrink = [row for row in observed["manufacturing_declarations"] if row["kind"] == "antipad"]
        self.assertEqual(shrink[0]["children"][2], {"tag": "RectCenter",
                                                  "attributes": {"width": "0.042", "height": "0.037"}})

    def test_invalid_overlap_and_circular_reference(self):
        """! @brief 회전 뒤 겹치는 보드와 원본을 순환 참조하는 패널을 진단한다."""
        original = SOURCE.read_bytes()
        with self.assertRaises(ProjectError):
            ipc_panel.build(original, [2, 3], [20, 47], 3, 90)
        panel = ipc_panel.build(original, [1, 2], [0, 45], 3, 90)
        invalid = panel.replace(b'stepRef="BOARD1"', b'stepRef="TW_PANEL"')
        reported = ipc_panel.read(invalid)
        self.assertEqual(reported["panels"], [])
        self.assertEqual(reported["panel_exclusions"][0]["code"], "E_UNSUPPORTED")

    @unittest.skipUnless(os.environ.get("RFAD_IPC2581C_XSD"), "공식 IPC-2581C XSD 경로가 필요합니다.")
    def test_schema_compatibility_with_official_source(self):
        """! @brief 제품 XML 코드와 분리된 libxml2에서 실제 공식 스키마를 검증한다."""
        from lxml import etree

        schema = etree.XMLSchema(etree.parse(os.environ["RFAD_IPC2581C_XSD"]))
        original = SOURCE.read_bytes()
        for xml in (original, ipc_panel.build(original, [2, 3], [30, 47], 3, 90)):
            schema.assertValid(etree.fromstring(xml))
