"""! @brief 기계 절삭 도면의 단면/연결 성분과 실제 세 형식 재입력을 검증한다."""

from copy import deepcopy
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.domain.drawing_layout import layout
from test_cad_pcb_features import hole
from test_exchange_drawing import fixture, PACKAGES, FONT, signed_area


def mechanical_fixture(format_name="svg"):
    """! @brief 실제 도체 분리와 외곽 내부 절삭을 가진 writer 계약 입력을 만든다."""
    data = fixture(format_name)
    projection = data["projection"]
    shape = projection["shapes"][0]
    shape.update(kind="planar_region", outer_mm=[[2, 19.5], [18, 19.5], [18, 20.5], [2, 20.5]], holes_mm=[])
    projection["shapes"] = [shape]
    data["dimensions"] = []
    item = hole(center=(10, 20))
    cutout = {"id": str(uuid4()), "shape": {"kind": "capsule", "center_mm": [25, 20],
              "finished_length_mm": 4, "finished_width_mm": 2, "rotation_deg": 0}, "surface_cut_ids": []}
    projection["mechanical"] = {"holes": [item], "cutouts": [cutout]}
    data["options"]["views"] = [{"kind": "layer", "layer_id": shape["layer_id"]}, {"kind": "stackup"}, {"kind": "outline"}]
    return data


class MechanicalDrawingTests(unittest.TestCase):
    """! @brief 2D와 실제 적층 단면이 같은 관통 제거를 소비하는지 검증한다."""

    def test_split_copper_and_section_use_finished_hole_and_cutout(self):
        """! @brief 도체 2성분, 유전체 단면의 세 구간 및 단위 면적을 대조한다."""
        data = mechanical_fixture()
        before = deepcopy(data)
        pages = layout(data)
        shape = data["projection"]["shapes"][0]
        path = next(item for item in pages[0]["primitives"] if item.get("source_id") == shape["id"] and item["role"] == "geometry")
        self.assertEqual(len(path["loops"]), 2)
        expected = 16 - 2 * (.5 * math.sqrt(.75) + math.asin(.5))
        self.assertAlmostEqual(sum(signed_area(loop) for loop in path["loops"]), expected, places=8)
        dielectric = data["projection"]["layers"][0]
        sections = [item for item in pages[1]["primitives"] if item.get("source_id") == dielectric["id"] and item["role"] == "geometry"]
        self.assertEqual(len(sections), 3)
        width = data["projection"]["board"]["width_mm"]
        self.assertAlmostEqual(sum(abs(signed_area(item["loops"][0])) for item in sections), (width - 2 - 4) * dielectric["thickness_mm"], places=8)
        outline = next(item for item in pages[2]["primitives"] if item["role"] == "geometry")
        self.assertEqual(len(outline["loops"]), 2)
        self.assertEqual(data, before)

    @unittest.skipUnless(PACKAGES, "고정 도면 Python 환경에서 실행해야 합니다.")
    def test_all_three_formats_preserve_separate_outer_components(self):
        """! @brief SVG/PDF even-odd와 DXF의 복수 외곽 플래그를 실제 파일로 확인한다."""
        from rfad.adapters.exchange.drawing import generate, verify
        import ezdxf
        for format_name in ("svg", "dxf", "pdf"):
            if format_name == "pdf" and not FONT.is_file():
                continue
            with self.subTest(format=format_name), TemporaryDirectory(prefix="TraceWave 기계 도면 ") as directory:
                data = mechanical_fixture(format_name)
                before = deepcopy(data)
                manifest = generate(data, Path(directory), font_path=FONT)
                self.assertEqual(verify(data, Path(directory), manifest)["status"], "passed_profile")
                self.assertEqual(data, before)
                sidecar = json.loads((Path(directory) / "sidecar.json").read_bytes())
                self.assertEqual(sidecar["source_semantics"], data["projection"]["source_semantics"])
                if format_name == "dxf":
                    drawing = ezdxf.readfile(Path(directory) / "drawing-01.dxf")
                    hatches = list(drawing.modelspace().query("HATCH"))
                    self.assertTrue(any(len(item.paths) == 2 and all(path.path_type_flags & 1 for path in item.paths) for item in hatches))


if __name__ == "__main__":
    unittest.main()
