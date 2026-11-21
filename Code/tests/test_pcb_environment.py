"""! @brief PCB와 급전을 고정한 설치 환경의 해석 투영을 검증한다."""

from copy import deepcopy
import unittest
from uuid import uuid4

from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
from rfad.application.pcb_mesh import mesh_lines
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import KEY, setup
from rfad.domain.units import Quantity
from test_pcb_solver import SETTINGS, fixture_document, quantity, runtime_identity, snapshot_for
from test_physical_setup import fixture


ENV_SETTINGS = {**SETTINGS, "air_padding_mm": 8,
                "radiation": {"frequency_hz": [10e9], "theta_step_deg": 15, "phi_step_deg": 15, "box_clearance_mm": 1}}


def board_fixture():
    """! @brief 미정 실물 부품을 보존하는 설치 비교용 기판을 만든다."""
    document = fixture_document()
    physical = deepcopy(setup(fixture()))
    physical["active_scenario_id"] = None
    physical["scenarios"][0]["name"] = "유전체 케이스 시험"
    document["extensions"][KEY] = physical
    plastic = {"id": str(uuid4()), "name": "검증용 유전체 케이스 재료", "model": "isotropic_constant",
               "epsilon_r": quantity(3.5, "1"), "tan_delta": quantity(.01, "1"), "conductivity": quantity(0, "S/m"),
               "validity_hz": {"min": quantity(1, "GHz"), "max": quantity(20, "GHz")},
               "source_refs": ["합성 시험 유전체 근거"], "assumptions": ["납품 또는 시료 실측값 미정"]}
    document["materials"] = sorted([*document["materials"], plastic], key=lambda item: item["id"])
    return document


def add_case(document):
    """! @brief 벽 두께와 플라스틱을 명시한 하부 개방 시험 케이스를 넣는다."""
    model = setup(document)
    scenario = model["scenarios"][0]["id"]
    model["active_scenario_id"] = scenario
    part = {"id": str(uuid4()), "kind": "dielectric_case", "name": "시험 케이스", "scenario_id": scenario,
            "step": None, "source_refs": ["합성 시험 케이스 치수"], "include_in_em": True, "visible": True,
            "include_in_export": False, "yaw": quantity(0, "deg"),
            "material_id": next(row["id"] for row in document["materials"] if row["name"].startswith("검증용"))}
    part.update({key: quantity(value, "mm") for key, value in
                 {"x": -2, "y": -2, "z": 0, "width": 20, "height": 16, "depth": 3.5, "case_thickness": 1}.items()})
    model["parts"] = sorted([*model["parts"], part], key=lambda item: item["id"])
    return part


def plan(document):
    """! @brief 공통 조건으로 봉인 계획을 생성한다."""
    return build_pcb_plan(document, snapshot_for(document), runtime_identity(), ENV_SETTINGS)


def ground_fixture():
    """! @brief 기판 바로 위에 떠 있는 PEC와 상부 사각 기준 접지 패드를 명시한다."""
    document = board_fixture()
    reference = document["ports"][0]["reference_geometry_id"]
    pad = next(row for row in document["geometry"] if row["id"] == reference)
    for key in ("width", "start", "end"):
        del pad[key]
    pad.update(kind="pad", pad_shape="rectangle", center=[quantity(4, "mm"), quantity(6, "mm")],
               size=[quantity(6, "mm"), quantity(4, "mm")], rotation=quantity(0, "deg"))
    case = add_case(document)
    case["depth"] = quantity(4.5, "mm")
    metal = {key: value for key, value in case.items() if key != "case_thickness"}
    metal.update(id=str(uuid4()), kind="isolated_pec_box", name="시험용 금속 접지 비교",
                 material_id=document["stackup"][-1]["material_id"], source_refs=["시험 금속 원본 출처"])
    metal.update({key: quantity(value, "mm") for key, value in
                  {"x": 3.5, "y": 5.5, "z": 1.635, "width": 1, "height": 1, "depth": 1}.items()})
    model = setup(document)
    model["parts"] = sorted([*model["parts"], metal], key=lambda row: row["id"])
    return document, metal


class PcbEnvironmentTests(unittest.TestCase):
    def test_grounded_box_requires_explicit_pad_contact_and_maps_to_native_sheet(self):
        """! @brief 간극만 보고 접지를 추정하지 않으며 계산 접면을 기록한다."""
        document, metal = ground_fixture()
        self.assertEqual(plan(document)["case"]["environment"]["parts"][1]["electrical_connection"], "isolated")
        metal["kind"] = "grounded_pec_box"
        with self.assertRaisesRegex(ProjectError, "실제 윗면"):
            plan(document)
        metal["z"] = quantity(1.035, "mm")
        grounded = plan(document)["case"]["environment"]["parts"][1]
        self.assertEqual(grounded["ground_geometry_id"], document["ports"][0]["reference_geometry_id"])
        self.assertAlmostEqual(grounded["physical_contact_z_mm"], 1.035)
        self.assertEqual(grounded["boxes_mm"][0][0][2], 1.0)
        metal["x"] = quantity(7, "mm")
        with self.assertRaisesRegex(ProjectError, "패드 안"):
            plan(document)

    def test_metal_requires_clearance_and_leaves_reference_material_unconsumed(self):
        """! @brief PEC의 계산 조건과 명시 재료 참조 및 간극을 구분한다."""
        document = board_fixture()
        case = add_case(document)
        metal = {key: value for key, value in case.items() if key != "case_thickness"}
        metal.update(id=str(uuid4()), kind="isolated_pec_box", name="시험 금속",
                     x=quantity(19, "mm"), width=quantity(2, "mm"), depth=quantity(1, "mm"))
        model = setup(document)
        without_metal = plan(document)["case"]
        model["parts"] = sorted([*model["parts"], metal], key=lambda row: row["id"])
        installed = plan(document)["case"]
        result = installed["environment"]["parts"][1]
        self.assertEqual(result["electrical_connection"], "isolated")
        self.assertFalse(result["material_values_consumed"])
        self.assertEqual(result["material_id"], metal["material_id"])
        self.assertEqual(result["minimum_axis_clearance_mm"], 1)
        self.assertGreater(installed["radiation_recording"]["stop_mm"][0], 21)
        metal["x"] = quantity(18, "mm")
        with self.assertRaisesRegex(ProjectError, "간극"):
            plan(document)
        metal["include_in_em"] = False
        self.assertEqual(plan(document)["case"], without_metal)

    def test_case_keeps_pcb_port_and_sources_and_moves_recording_outside(self):
        """! @brief 설치 경계와 방사 중심이 실제 모델에 일치하는지 대조한다."""
        document = board_fixture()
        bare = plan(document)["case"]
        row = add_case(document)
        installed_plan = plan(document)
        validate_pcb_plan(installed_plan)
        installed = installed_plan["case"]
        for key in ("port", "board", "layers", "shapes", "settings"):
            self.assertEqual(installed[key], bare[key])
        part = installed["environment"]["parts"][0]
        self.assertEqual(part["boxes_mm"][0], [[-2.0, -2.0, 2.5], [18.0, 14.0, 3.5]])
        self.assertEqual(len(part["boxes_mm"]), 5)
        self.assertGreaterEqual(part["pcb_ceiling_clearance_mm"], 0.5)
        self.assertEqual(installed["radiation_recording"]["center_m"], bare["radiation_recording"]["center_m"])
        self.assertGreater(installed["radiation_recording"]["stop_mm"][2], 3.5)
        self.assertIn(2.5, mesh_lines(installed)["z"])
        self.assertEqual(installed_plan["source_semantics"], document)
        row["visible"] = False
        self.assertEqual(plan(document)["case"], installed)

    def test_required_missing_and_small_clearance_are_rejected(self):
        """! @brief 격자에 맞추어 치수나 미정 재료를 보완하지 않는다."""
        document = board_fixture()
        part = add_case(document)
        part["case_thickness"] = Quantity.missing("length", "mm").to_dict()
        with self.assertRaisesRegex(ProjectError, "미정"):
            plan(document)
        part["case_thickness"] = quantity(1, "mm")
        part["depth"] = quantity(2.1, "mm")
        with self.assertRaisesRegex(ProjectError, "간극"):
            plan(document)
        part["depth"] = quantity(3.5, "mm")
        part["material_id"] = None
        with self.assertRaisesRegex(ProjectError, "재료"):
            plan(document)
