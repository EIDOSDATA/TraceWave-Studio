"""! @brief 물리 설정의 목적별 투영과 불변 변경/재열기 계약을 검증한다."""

from copy import deepcopy
import unittest
from tempfile import TemporaryDirectory
from uuid import uuid4

from rfad.application.cad import build_cad_input
from rfad.application.canonical import canonical_bytes
from rfad.application.physical_projection import check_em
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.design import preflight_design
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import KEY, PROFILE, setup, stack_review
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from test_cad_projection import cad_fixture, snapshot_for
from test_cad_worker_process import register_fixture, request, status
from test_design import quantity
from test_pcb_solver import SETTINGS, build_pcb_plan, fixture_document, runtime_identity, validate_pcb_plan


METHOD = "physical.setup.apply"


def parameters(service, document, area, changes, *, identity=None, operation="set", step_token=None):
    """! @brief 실제 적용 요청에서 수정한 UI 필드만 전달한다."""
    return request(service, document["project_id"], {"expected_revision": document["revision_id"], "command_id": str(uuid4()),
        "section": area, "operation": operation, "record_id": identity, "reason": "회귀 시험 입력 자료", "changes": changes,
        "step_token": step_token})


def load(service, document):
    """! @brief 실제 저장된 개정의 원본을 읽는다."""
    return service._load(service.journal.read()["projects"][document["project_id"]])


def fixture():
    """! @brief 설치 후보와 제공되지 않은 제조/측정 원본을 가진 시험 PCB를 만든다."""
    document = cad_fixture()
    scenario_id, part_id = sorted(str(uuid4()) for _ in range(2))
    missing = Quantity(None, "length", "mm", "missing", ["실물 치수 미확보"]).to_dict()
    document["extensions"][KEY] = {"schema": PROFILE, "stack": None,
        "surfaces": [], "scenarios": [{"id": scenario_id, "name": "검증용 설치 조건", "source_refs": ["설치 기준 출처"]}],
        "active_scenario_id": scenario_id,
        "parts": [{"id": part_id, "scenario_id": scenario_id, "name": "치수 미정 참고 배터리", "kind": "box", "step": None,
                   "material_id": None, "visible": False, "include_in_em": False, "include_in_export": False,
                   "x": missing, "y": missing, "z": missing, "yaw": quantity(0.0, "deg"),
                   "width": missing, "height": missing, "depth": missing, "source_refs": ["시료 참조, 실제 치수 미정"]}]}
    return document


class PhysicalSetupTests(unittest.TestCase):
    def test_projection_with_independent_inclusions_and_nominal_discrepancy(self):
        """! @brief 기존 적층과 출처를 보존하고 유효 범위 밖의 해석 포함을 차단한다."""
        with TemporaryDirectory() as workspace, ProjectService(workspace, auto_run=False) as service:
            original, snapshot = register_fixture(service, fixture())
            service.mutate(METHOD, parameters(service, original, "stack", {"nominal": "1.09", "scope": "with_surfaces"}))
            before = load(service, original)
            applied = service.mutate(METHOD, parameters(service, before, "surface", {
                "name": "공개 피복", "kind": "ferrite", "offset": "0", "thickness": ".02", "openings": "2 3 4 5", "include_in_export": False}))
            stored = load(service, before)
            review = stack_review(stored)
            self.assertAlmostEqual(review["base_sum_si"], 0.001035)
            self.assertAlmostEqual(review["full_extent_si"], 0.001055)
            self.assertAlmostEqual(review["nominal_difference_si"], -0.000035)
            display = build_cad_input(stored, snapshot_for(stored), purpose="geometry")
            self.assertEqual(display["surface_layers"][0]["openings_mm"], [[2.0, 3.0, 4.0, 5.0]])
            self.assertEqual(build_cad_input(stored, snapshot_for(stored))["surface_layers"], [])
            self.assertEqual(display["environment_parts"], [])
            self.assertEqual(display["source_semantics"], stored)
            self.assertEqual(stored["stackup"], original["stackup"])
            self.assertEqual(stored["materials"], original["materials"])
            check_em(stored)
            hidden = service.mutate(METHOD, parameters(service, stored, "surface", {"visible": False}, identity=applied["record_id"]))
            self.assertEqual(hidden["invalidation_set"], ["revision", "geometry"])
            pending = load(service, original)
            service.mutate(METHOD, parameters(service, pending, "surface", {"include_in_em": True}, identity=applied["record_id"]))
            pending = load(service, original)
            self.assertTrue(any(item.get("details", {}).get("field_path", "").endswith(".include_in_em")
                                for item in preflight_design(pending, "em")))
            with self.assertRaisesRegex(ProjectError, "포함할 수 없습니다"):
                check_em(pending)
            self.assertEqual(service.journal.read_artifact(snapshot["artifact"]), canonical_bytes(original))

    def test_solver_plan_records_exclusions_and_refuses_included_parts(self):
        """! @brief 해석 제외와 미지원 해석 포함을 실제 PCBPlan 진입점에서 구분한다."""
        original = fixture_document()
        original["extensions"][KEY] = deepcopy(setup(fixture()))
        part = setup(original)["parts"][0]
        plan = build_pcb_plan(original, snapshot_for(original), runtime_identity(), SETTINGS)
        validate_pcb_plan(plan)
        self.assertEqual(plan["physical_setup_omissions"],
                         [{"id": part["id"], "section": "part", "reason": "excluded_by_user"}])
        part["include_in_em"] = True
        with self.assertRaises(ProjectError) as raised:
            build_pcb_plan(original, snapshot_for(original), runtime_identity(), SETTINGS)
        self.assertEqual(raised.exception.code, "E_UNSUPPORTED")
        self.assertEqual(raised.exception.details["field_path"], f"part.{part['id']}.include_in_em")
        setup(original)["active_scenario_id"] = None
        plan = build_pcb_plan(original, snapshot_for(original), runtime_identity(), SETTINGS)
        self.assertNotIn("physical_setup_omissions", plan)

    def test_active_scenario_reference_undo_and_durable_missing(self):
        """! @brief 기준 선택, 참조 오류, undo와 새 서비스의 저장 기준점을 대조한다."""
        with TemporaryDirectory() as workspace:
            with ProjectService(workspace, auto_run=False) as service:
                original, _ = register_fixture(service, fixture())
                model = setup(original)
                part, scenario = model["parts"][0], model["scenarios"][0]
                with self.assertRaises(ProjectError):
                    service.mutate(METHOD, parameters(service, original, "scenario", {}, identity=scenario["id"], operation="remove"))
                self.assertEqual(load(service, original), original)
                service.mutate(METHOD, parameters(service, original, "part", {"name": "변경한 이름"}, identity=part["id"]))
                after = load(service, original)
                for key in ("width", "x", "y", "z", "material_id"):
                    self.assertEqual(setup(after)["parts"][0][key], part[key])
                service.mutate("project.undo", request(service, original["project_id"], {
                    "expected_revision": after["revision_id"], "command_id": str(uuid4())}))
                undone = load(service, original)
                self.assertEqual(setup(undone), model)
                service.mutate("project.redo", request(service, original["project_id"], {
                    "expected_revision": undone["revision_id"], "command_id": str(uuid4())}))
                service.mutate(METHOD, parameters(service, load(service, original), "activation", {"active_scenario_id": ""}))
                saved = load(service, original)
                task = service.mutate("project.save", request(service, original["project_id"], {"expected_revision": saved["revision_id"]}))
                service.run_next()
                self.assertEqual(status(service, task["job_id"])["state"], "completed")
            with ProjectService(workspace, auto_run=False) as reopened:
                self.assertEqual(load(reopened, original), saved)
                self.assertIsNone(setup(saved)["active_scenario_id"])
                self.assertEqual(saved["measurement_sets"], original["measurement_sets"])
                self.assertEqual(saved["source_references"], original["source_references"])
                self.assertEqual(saved["assumptions"], original["assumptions"])

    def test_public_envelope_guard_and_unknown_dimensions(self):
        """! @brief 외부 STEP은 읽기 검토 이후에만 채택하며 미정 투영에 값을 채우지 않는다."""
        with TemporaryDirectory() as workspace, ProjectService(workspace, auto_run=False) as service:
            doc, _ = register_fixture(service, fixture())
            missing_box = setup(doc)["parts"][0]
            query = {"contract_version": "rfad.api/2.0", "context": {"project_id": doc["project_id"]},
                     "input": {"expected_revision": doc["revision_id"], "section": "part", "record_id": missing_box["id"]}}
            reply = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": "physical.setup.get", "params": query}), service)
            result = reply["result"]
            self.assertEqual(result["condition_status"], "project_conditions_unconfirmed")
            fields = {item["key"]: item for item in result["fields"]}
            self.assertIsNone(fields["width"]["original"]["value_si"])
            self.assertEqual(fields["width"]["original"]["source_refs"], ["실물 치수 미확보"])
            with self.assertRaisesRegex(ProjectError, "미리보기"):
                service.mutate(METHOD, parameters(service, doc, "part", {"kind": "step"}, identity=missing_box["id"]))
            for bad_source in ({"name": "outside.step", "chunks": ["@@"]},
                               {"name": "../ref.step", "chunks": ["QQ=="]}):
                preview = {**query, "input": {"expected_revision": doc["revision_id"], **bad_source}}
                with self.assertRaises(ProjectError):
                    service.physical_setup.read("physical.step.preview", preview)
            changed = deepcopy(doc)
            setup(changed)["parts"][0]["visible"] = True
            with self.assertRaisesRegex(ProjectError, "미정"):
                build_cad_input(changed, snapshot_for(changed), purpose="geometry")
            validate_project(changed)
