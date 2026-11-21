"""! @brief 솔더마스크의 원본, 실제 계산 경계와 개구를 확인한다."""

import unittest
from uuid import uuid4

from rfad.application.pcb_mesh import mesh_lines
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import setup
from rfad.domain.units import Quantity
from test_pcb_environment import board_fixture, plan
from test_pcb_solver import fixture_document, quantity


def rectangle(x, y, width, height):
    """! @brief 시험용 명시 사각 범위를 만든다."""
    return {key: quantity(value, "mm") for key, value in zip(("x", "y", "width", "height"), (x, y, width, height))}


def add_mask(document):
    """! @brief 직접 선택한 재료, 마스크 두께와 전체 피복을 등록한다."""
    row = {"id": str(uuid4()), "name": "시험 마스크", "source_refs": ["시험 명목 두께"],
           "kind": "solder_mask", "side": "top", "coverage": "board", "openings": [],
           "material_id": document["stackup"][0]["material_id"], "include_in_em": True,
           "visible": True, "include_in_export": False, "offset": quantity(0, "mm"),
           "thickness": quantity(.15, "mm")}
    row.update({key: Quantity.missing("length", "mm").to_dict() for key in ("x", "y", "width", "height")})
    setup(document)["surfaces"].append(row)
    return row


class PcbSurfaceTests(unittest.TestCase):
    def test_auxiliary_layers_use_final_thickness_without_resolving_supply(self):
        """! @brief 공급 수량이 정해져도 경화 두께를 추정하지 않는다."""
        document = board_fixture()
        bond = add_mask(document)
        bond.update(kind="bondply", supply_thickness=quantity(.24, "mm"))
        first = plan(document)["case"]
        bond["supply_thickness"] = Quantity.missing("length", "mm").to_dict()
        self.assertEqual(plan(document)["case"], first)
        bond["thickness"] = Quantity.missing("length", "mm").to_dict()
        with self.assertRaisesRegex(ProjectError, "미정"):
            plan(document)
        bond["thickness"] = quantity(.15, "mm")
        adhesive = add_mask(document)
        adhesive.update(kind="adhesive", offset=quantity(.15, "mm"))
        setup(document)["surfaces"].sort(key=lambda row: row["id"])
        self.assertEqual(len(plan(document)["case"]["surface_layers"]), 2)
        adhesive["offset"] = quantity(.1, "mm")
        with self.assertRaisesRegex(ProjectError, "중첩"):
            plan(document)

    def test_opening_keeps_gap_port_and_material_out_of_window(self):
        """! @brief 피복의 개구 면적만큼 실제 유전체 타일을 제거한다."""
        document = board_fixture()
        bare = plan(document)["case"]
        mask = add_mask(document)
        full = plan(document)["case"]
        mask["openings"] = [rectangle(6, 4, 4, 4)]
        opened = plan(document)["case"]
        row = opened["surface_layers"][0]
        self.assertEqual(bare["port"], full["port"])
        self.assertEqual(full["port"], opened["port"])
        self.assertEqual(row["bounds_mm"][2], [1.0, 1.15])
        area = sum((x1 - x0) * (y1 - y0) for (x0, x1), (y0, y1) in row["tiles_mm"])
        self.assertEqual(area, 16 * 12 - 4 * 4)
        self.assertIn(1.15, mesh_lines(opened)["z"])
        self.assertIn(6, mesh_lines(opened)["x"])
        self.assertEqual(bare["radiation_recording"]["center_m"], opened["radiation_recording"]["center_m"])
        mask["visible"] = False
        self.assertEqual(plan(document)["case"], opened)
        mask["include_in_em"] = False
        self.assertEqual(plan(document)["case"], bare)

    def test_outside_and_missing_openings_fail_before_launch(self):
        """! @brief 중첩, 원형 외곽 바깥 및 미정 재료는 확인된 값으로 대체하지 않는다."""
        document = board_fixture()
        circular = fixture_document(circle=True)
        circular["extensions"] = document["extensions"]
        mask = add_mask(circular)
        mask["openings"] = [rectangle(5, 5, 2, 2)]
        with self.assertRaisesRegex(ProjectError, "피복을 벗어"):
            plan(circular)
        mask["openings"] = [rectangle(-2, -2, 4, 4)]
        self.assertEqual(plan(circular)["case"]["surface_layers"][0]["profile"], "cylinder_with_air_openings")
        mask["openings"].append(rectangle(-1, -1, 2, 2))
        with self.assertRaisesRegex(ProjectError, "겹칩니다"):
            plan(circular)
        mask["openings"].clear()
        mask["material_id"] = None
        with self.assertRaisesRegex(ProjectError, "재료"):
            plan(circular)
