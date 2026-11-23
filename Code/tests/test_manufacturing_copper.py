"""! @brief 제조 원본 단위, 도형 번호, 변환 및 부분 대응의 안전한 처리를 대조한다."""

from decimal import Decimal
import unittest
from xml.etree import ElementTree

from rfad.adapters.exchange import ipc2581_reader as ipc
from rfad.adapters.exchange import odb_reader as odb


class ManufacturingCopperTests(unittest.TestCase):
    """! @brief 편집 모델에 반영하는 제조 선폭과 전기 참조를 검사한다."""

    def test_odb_copper_requires_trace_subnet_and_feature_index(self):
        """! @brief 도금 및 핀 레코드가 섞여도 TRC의 실제 도형 번호와 inch 선폭만 채택한다."""
        eda = ("LYR bottom top\nNET RF\nSNT TOP T 1 0\nFID C 1 0\n"
               "SNT TRC\nFID H 0 0\nFID C 1 1\nFID C 1 2\n")
        features = ("UNITS=INCH\nF 3\n$0 r10\nP 0 0 0 P 0 0\n"
                    "L 0 0 0.1 0 0 P 0\nA 1 0 0 1 0 0 0 P 0 Y\n")
        nets = odb._trace_nets(eda)
        first, arc = odb._layer_traces(features, "top", nets)
        self.assertEqual(first["source_id"], "copper:top:1")
        self.assertEqual(first["net"], "RF")
        self.assertAlmostEqual(first["width_mm"], .254)
        self.assertAlmostEqual(first["end_mm"][0], 2.54)
        self.assertEqual(arc["sweep_angle_deg"], -270)
        self.assertEqual(odb._layer_traces(features.replace("P 0 0 0 P", "P 0 0 0 N"), "top", nets), [])
        self.assertEqual(odb._trace_nets(eda + "FID C 1 2\n"), {})

    def test_ipc_transformed_or_negative_layers_stay_in_original(self):
        """! @brief 변환된 특징이나 다른 세트의 음극성 절삭이 있는 동박을 그대로 양극성 도체로 바꾸지 않는다."""
        xml = ('<Step xmlns="' + ipc.NAMESPACE + '"><LayerFeature layerRef="L"><Set net="N">'
               '<Features><UserSpecial><Line startX="0" startY="0" endX=".1" endY="0">'
               '<LineDesc lineEnd="ROUND" lineWidth=".01"/></Line></UserSpecial></Features>'
               '</Set></LayerFeature></Step>')
        layer = ElementTree.fromstring('<Layer name="L" layerFunction="CONDUCTOR" polarity="POSITIVE"/>')
        factor = Decimal("25.4")
        line, = ipc._editable_traces(ElementTree.fromstring(xml), [layer], factor)
        self.assertAlmostEqual(line["width_mm"], .254)
        self.assertAlmostEqual(line["end_mm"][0], 2.54)
        for blocked in (xml.replace("<Features>", '<Features><Xform rotation="90"/>'),
                        xml.replace("</Step>", '<LayerFeature layerRef="L"><Set polarity="NEGATIVE"/></LayerFeature></Step>')):
            self.assertEqual(ipc._editable_traces(ElementTree.fromstring(blocked), [layer], factor), [])
