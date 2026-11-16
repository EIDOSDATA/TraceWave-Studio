"""! @brief 고정 RF 참조의 물리 입력과 출처 경계를 native 실행 없이 검사한다."""

from copy import deepcopy
import unittest

from rfad.application.rf_reference_contract import (
    CASE, PROFILE, REFERENCE_SCOPE, build_plan, raw_names, validate_plan, validate_settings,
)
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.solver_requests import validate_solver_input
from rfad.domain.errors import ProjectError
from rfad.domain.project import new_project
from test_cad_projection import snapshot_for
from test_pcb_solver import fixture_document
from test_solver_plan import runtime_fixture


class RFReferenceContractTests(unittest.TestCase):
    """! @brief 사용자 설계 대체와 암묵적 추가 사례를 차단한다."""

    def test_fixed_physical_geometry_and_pml_survive_three_grid_levels(self):
        """! @brief 수준 간 바뀌는 것은 내부 격자이며 PML/급전/NF2FF는 고정한다."""
        document = new_project("PEC 다이폴 합성 참조")
        snapshot, runtime = snapshot_for(document), runtime_fixture()
        before = deepcopy((document, snapshot, runtime))
        plans = [build_plan(document, snapshot, runtime, {"case": CASE, "grid_mm": grid}) for grid in (3, 2.5, 2)]
        for plan, expected_lines in zip(plans, (71, 81, 95)):
            validate_plan(plan)
            self.assertEqual(plan["analysis_profile"], PROFILE)
            self.assertEqual(plan["model_report"]["reference_scope"], REFERENCE_SCOPE)
            self.assertEqual(plan["resource_estimate"]["kind"], "initial_estimate_not_actual_mesh")
            self.assertEqual(plan["resource_estimate"]["estimated_grid_points"], expected_lines ** 3)
            self.assertLess(plan["resource_estimate"]["estimated_memory_bytes"], 1024 ** 3)
            for lines in plan["case"]["mesh"]["lines_mm"].values():
                self.assertEqual(len(lines), expected_lines)
                self.assertEqual(lines[:9], list(range(-90, -73, 2)))
                self.assertEqual(lines[-9:], list(range(74, 91, 2)))
                self.assertTrue(set((-60, -30, -1, -0.5, 0, 0.5, 1, 30, 60)) <= set(lines))
            self.assertEqual(plan["case"]["port"], plans[0]["case"]["port"])
            self.assertEqual(plan["case"]["geometry"], plans[0]["case"]["geometry"])
            self.assertEqual(plan["case"]["radiation_recording"]["start_mm"], [-60.0] * 3)
            self.assertEqual(len(raw_names(plan)), 18)
            self.assertNotIn("port_ut_2", raw_names(plan))
            self.assertIsNone(plan["case"]["manufacturing"])
            self.assertIsNone(plan["case"]["measurement"])
        self.assertEqual((document, snapshot, runtime), before)
        self.assertEqual(len({plan["plan_id"] for plan in plans}), 3)

    def test_unfrozen_cases_and_extra_settings_cannot_start(self):
        """! @brief sheet/유한 급전, 추가 수준과 예산 확대는 명시 거절한다."""
        for settings in ({"case": "planar-sheet-canonical", "grid_mm": 1.0},
                         {"case": "finite-feed", "grid_mm": 3.0},
                         {"case": CASE, "grid_mm": True}, {"case": CASE, "grid_mm": 1.5},
                         {"case": CASE, "grid_mm": 3.0, "max_timesteps": 100000},
                         {"case": CASE, "grid_mm": 3.0, "geometry": {}}, None):
            with self.subTest(settings=settings), self.assertRaises(ProjectError):
                validate_settings(settings)

    def test_nonempty_user_pcb_is_never_ignored(self):
        """! @brief 참조 선택으로 사용자 기하와 제조 탐색 물성을 대체하지 않는다."""
        document = fixture_document()
        before = deepcopy(document)
        with self.assertRaises(ProjectError) as error:
            build_plan(document, snapshot_for(document), runtime_fixture(), {"case": CASE, "grid_mm": 3.0})
        self.assertEqual(error.exception.code, "E_UNSUPPORTED")
        self.assertEqual(document, before)

    def test_changed_geometry_pml_source_and_schema_are_rejected(self):
        """! @brief 불변 계획의 값 하나를 바꿔 다른 물리 조건으로 재개하지 않는다."""
        document = new_project("고정 참조")
        original = build_plan(document, snapshot_for(document), runtime_fixture(), {"case": CASE, "grid_mm": 3.0})
        for mode in ("radius", "pml", "port", "source", "profile", "scope"):
            plan = deepcopy(original)
            if mode == "radius":
                plan["case"]["geometry"]["radius_mm"] = 0.5
            elif mode == "pml":
                plan["case"]["mesh"]["lines_mm"]["x"][8] = -73.0
            elif mode == "port":
                plan["case"]["port"]["stop_mm"][2] = 1.0
            elif mode == "source":
                plan["source_semantics"]["metadata"]["description"] = "다른 원문"
            elif mode == "profile":
                plan["analysis_profile"] = "rfad.openems.rect-waveguide/0.1"
            else:
                plan["model_report"]["reference_scope"]["measurement"] = "passed"
            with self.subTest(mode=mode), self.assertRaises(ProjectError):
                validate_plan(plan)

    def test_public_input_is_closed_and_legacy_profile_is_not_fallback(self):
        """! @brief 새 profile의 exact 설정과 기존 도파관 입력을 구분한다."""
        document = new_project("접수 시험")
        snapshot = snapshot_for(document)
        data = {"snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
                "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE,
                "settings": {"case": CASE, "grid_mm": 2.5}}
        context = {"project_id": document["project_id"]}
        validate_solver_input("solver.plan", context, data)
        for patch in ({"grid_mm": 2.5}, {"analysis_profile": "rfad.openems.unknown/0.1"}):
            with self.subTest(patch=patch), self.assertRaises(ProjectError):
                validate_solver_input("solver.plan", context, {**data, **patch})
