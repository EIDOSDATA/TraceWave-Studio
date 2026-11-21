"""! @brief 기판 관통부의 완성 형상과 구리·급전 간격을 검사한다."""

import unittest
from uuid import uuid4

from rfad.application.pcb_exchange_service import new_record
from rfad.application.pcb_mesh import mesh_lines
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_features import empty_pcb
from test_pcb_environment import board_fixture, plan
from test_pcb_features import hole_record
from test_pcb_solver import quantity


def drilled_board():
    """! @brief 원형 비도금 홀, 회전 슬롯 및 내부 다각형 절삭을 원본에서 선언한다."""
    document = board_fixture()
    document["pcb"] = empty_pcb()
    drill = hole_record(document, x=3, y=2, diameter=1.5)
    drill["name"] = "비도금 관통 홀"
    slot = hole_record(document, x=11, y=2, diameter=1.5)
    slot.update(id=str(uuid4()), name="비도금 관통 슬롯", shape={"kind": "capsule", "center": slot["shape"]["center"],
                                               "finished_length": quantity(3, "mm"), "finished_width": quantity(1.5, "mm"),
                                               "rotation": quantity(12, "deg")})
    document["pcb"]["holes"] = sorted([drill, slot], key=lambda row: row["id"])
    region = new_record(document, "cutout")
    region["name"] = "내부 다각형 절삭"
    region["shape"] = {"kind": "polygon", "holes": [],
                       "outer": [[quantity(x, "mm"), quantity(y, "mm")] for x, y in [(10, 8), (13, 8.5), (11, 10)]]}
    document["board"]["cutouts"] = [region]
    return document


class PcbVoidTests(unittest.TestCase):
    def test_mechanical_voids_keep_source_and_compute_bounds(self):
        """! @brief 세 가지 완성 절삭에 실제 격자 경계가 있으며 원본 공구는 미정이다."""
        document = drilled_board()
        sealed = plan(document)
        case = sealed["case"]
        for row in case["mechanical_voids"]:
            self.assertEqual(row["z_mm"], [0, 1])
            self.assertIn(round(row["witness_mm"][0], 12), mesh_lines(case)["x"])
        self.assertEqual({row["kind"] for row in case["mechanical_voids"]}, {"circle", "capsule", "polygon"})
        self.assertEqual(sealed["source_semantics"], document)
        self.assertTrue(all(row["tool_diameter"]["value_si"] is None for row in document["pcb"]["holes"]))

    def test_mechanical_voids_reject_copper_and_unknown_plating(self):
        """! @brief 절삭이 급전이나 도체를 변경하면 계산 전에 중단한다."""
        document = drilled_board()
        drill = next(row for row in document["pcb"]["holes"] if row["shape"]["kind"] == "circle")
        drill["shape"]["center"] = [quantity(8, "mm"), quantity(6, "mm")]
        with self.assertRaisesRegex(ProjectError, "급전 간극"):
            plan(document)
        drill["plating"]["state"] = "unknown"
        with self.assertRaisesRegex(ProjectError, "비도금"):
            plan(document)
