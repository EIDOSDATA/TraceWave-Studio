"""! @brief 유한 후보 시험의 연결점/출처/미정값과 전 대역 표본을 native 실행 전에 검증한다."""

from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from tuning_workflow_cases import create_case, FREQUENCIES
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
from rfad.application.projects import ProjectService
from rfad.domain.design import resolve_scalar
from rfad.domain.design_sweep import validate_specification, candidate_at
from rfad.domain.physical_setup import setup
from test_cad_projection import snapshot_for
from test_pcb_solver import runtime_identity


class TuningWorkflowCasesTests(unittest.TestCase):
    """! @brief 시험 치수의 유효성을 안테나 성능 검증과 구분한다."""

    def check_case(self, kind):
        """! @brief 세 후보의 실제 계획에서 고정 급전점과 제외 환경, 미정 물성을 대조한다."""
        with TemporaryDirectory() as temporary:
            with ProjectService(Path(temporary)) as service:
                case = create_case(service, kind)
                original = deepcopy(case["document"])
                target = original["targets"][0]
                self.assertEqual([q["value_si"] for q in target["band"]["sampling"]["frequencies"]], FREQUENCIES)
                self.assertEqual([FREQUENCIES[0], FREQUENCIES[-1]], [2.4e9, 2.4835e9])
                self.assertTrue(all(c["limit"]["value"] is None and c["limit"]["status"] == "missing"
                                    for c in target["criteria"] if c["metric"] != "s11_db"))
                unknown = next(row for row in original["materials"] if row["name"].startswith("실제 납품"))
                self.assertTrue(all(unknown[key]["value_si"] is None for key in ("epsilon_r", "tan_delta", "conductivity")))
                part = setup(original)["parts"][0]
                self.assertIsNone(part["material_id"])
                self.assertTrue(all(part[key]["value_si"] is None for key in ("x", "y", "z", "width", "height", "depth", "yaw")))
                specification = validate_specification(case["specification"], original)
                for index in range(3):
                    candidate = candidate_at(original, specification, index)
                    self.assertEqual(candidate["status"], "valid", candidate["diagnostics"])
                    selected = candidate["document"]
                    self.assertEqual(selected["ports"], original["ports"])
                    self.assertEqual(selected["materials"], original["materials"])
                    self.assertEqual(selected["extensions"], original["extensions"])
                    self.assertEqual(selected["targets"], original["targets"])
                    shape = next(row for row in selected["geometry"] if row["role"] == "radiator")
                    if kind == "arc":
                        endpoint_x = resolve_scalar(selected, shape["radius"], "length").value_si
                        endpoint_x += resolve_scalar(selected, shape["center"][0], "length").value_si
                        self.assertAlmostEqual(endpoint_x, 0.025)
                        self.assertEqual(shape["start_angle"]["value_si"], 0)
                    else:
                        self.assertAlmostEqual(resolve_scalar(selected, shape["start"][0], "length").value_si, 0.005)
                        self.assertIn("parameter_id", shape["end"][0])
                    plan = build_pcb_plan(selected, snapshot_for(selected), runtime_identity(), candidate["settings"])
                    validate_pcb_plan(plan)
                    self.assertEqual(plan["source_semantics"], selected)
                    self.assertEqual(plan["physical_setup_omissions"], [{"id": part["id"], "section": "part", "reason": "excluded_by_user"}])
                    self.assertFalse(plan["case"]["radiation_recording"]["physics_validated"])
                self.assertEqual(service._load(service.journal.read()["projects"][original["project_id"]]), original)
            with ProjectService(Path(temporary), auto_run=False) as reopened:
                self.assertEqual(reopened._load(reopened.journal.read()["projects"][original["project_id"]]), original)

    def test_ifa_keeps_short_feed_and_missing_installation(self):
        """! @brief 길이 축만 바꾸고 단락/급전 및 미확보 설치 자료를 보존한다."""
        self.check_case("ifa")

    def test_arc_radius_keeps_connected_feed_endpoint(self):
        """! @brief 반지름 변화에도 급전 시작점은 같은 좌표에 연결한다."""
        self.check_case("arc")
