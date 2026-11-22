"""! @brief 실제 사용자 PCB 계획의 물성/급전/외곽/불변 입력 경계를 검사한다."""

from copy import deepcopy
import hashlib
import math
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_execution import NATIVE_SCOPE, estimate, stopped, validate_measurement
from rfad.application.pcb_solver import build_pcb_plan, check_termination, mesh_lines, shape_polygons, validate_pcb_plan, validate_result
from rfad.domain.errors import ProjectError
from rfad.domain.project import new_project, validate_project
from rfad.domain.units import Quantity


SETTINGS = {"frequency_hz": {"start": 8e9, "stop": 12e9, "count": 31}, "grid_mm": 0.5,
            "air_padding_mm": 6.0, "curve_tolerance_mm": 0.025, "max_timesteps": 20000, "end_criterion": 1e-4}


def quantity(value, unit):
    """! @brief 시험에서 명시적으로 선택한 값을 provenance와 함께 생성한다."""
    return Quantity.from_value(value, unit, source_refs=["test-only-explicit-assumption"]).to_dict()


def fixture_document(*, circle=False, arc=False):
    """! @brief 제조/IFA 검증이 아닌 작은 유한 도체 gap 시험 입력을 명시적으로 만든다."""
    document = new_project("Explicit PCB runtime verification; not an IFA reference")
    document["metadata"]["description"] = "Only an internal runtime fixture. Material values are explicit test assumptions, not FR4 defaults or measurement evidence."
    board_id, substrate_id, copper_id, dielectric_layer, copper_layer, ground_id, radiator_id, net_a, net_b, port_id = [str(uuid4()) for _ in range(10)]
    outline = {"kind": "circle", "center": [quantity(0, "mm"), quantity(0, "mm")], "radius": quantity(8, "mm")} if circle else {"kind": "rectangle", "width": quantity(16, "mm"), "height": quantity(12, "mm")}
    document["board"] = {"id": board_id, "frame_id": document["frames"]["board"]["id"], "outline": outline, "thickness_convention": "finished"}
    document["materials"] = [
        {"id": substrate_id, "name": "Explicit test substrate", "model": "isotropic_constant", "epsilon_r": quantity(2.2, "1"),
         "tan_delta": quantity(0.002, "1"), "conductivity": quantity(0, "S/m"), "validity_hz": {"min": quantity(1, "GHz"), "max": quantity(20, "GHz")},
         "source_refs": ["test-only-explicit-assumption"], "assumptions": ["Not actual board material; only native interface verification"]},
        {"id": copper_id, "name": "Explicit test conductor", "model": "isotropic_constant", "epsilon_r": quantity(1, "1"),
         "tan_delta": quantity(0, "1"), "conductivity": quantity(58e6, "S/m"), "validity_hz": {"min": quantity(1, "GHz"), "max": quantity(20, "GHz")},
         "source_refs": ["test-only-explicit-assumption"], "assumptions": ["Finite conducting sheet test assumption"]},
    ]
    document["materials"].sort(key=lambda item: item["id"])
    document["stackup"] = [
        {"id": dielectric_layer, "name": "Test dielectric", "role": "dielectric", "order": 0, "z_min": quantity(0, "mm"), "thickness": quantity(1, "mm"), "material_id": substrate_id},
        {"id": copper_layer, "name": "Test outer conductor", "role": "conductor", "order": 1, "z_min": quantity(1, "mm"), "thickness": quantity(35, "um"), "material_id": copper_id},
    ]
    document["nets"] = sorted([{"id": net_a, "name": "test_positive"}, {"id": net_b, "name": "test_reference"}], key=lambda item: item["id"])
    offset = [0, 0] if circle else [8, 6]
    def xy(x, y):
        return [quantity(x + offset[0], "mm"), quantity(y + offset[1], "mm")]
    common = {"kind": "line_path", "frame_id": document["frames"]["board"]["id"], "layer_id": copper_layer,
              "material_ref": copper_id, "source_ref": "test-only-explicit-assumption", "include_in_em": True, "include_in_export": True, "width": quantity(1, "mm")}
    document["geometry"] = [
        {**common, "id": ground_id, "net_id": net_b, "role": "ground", "start": xy(-6, 0), "end": xy(-1.5, 0)},
        {**common, "id": radiator_id, "net_id": net_a, "role": "radiator", "start": xy(1.5, 0), "end": xy(6, 0)},
    ]
    if arc:
        # @brief 급전 line은 유지하고 같은 net의 접속 원호를 별도로 추가한다.
        document["geometry"].append({**common, "id": str(uuid4()), "net_id": net_a, "role": "radiator", "kind": "arc_path",
                                     "center": xy(3, 0), "radius": quantity(3, "mm"), "start_angle": quantity(0, "deg"), "sweep_angle": quantity(90, "deg")})
    document["geometry"].sort(key=lambda item: item["id"])
    document["ports"] = [{"id": port_id, "name": "Explicit test gap", "kind": "lumped", "positive_geometry_id": radiator_id,
                          "reference_geometry_id": ground_id, "resistance": quantity(50, "ohm"), "reference_plane": "physical gap; no deembedding",
                          "polarity": 1, "direction": [1, 0, 0], "validity_hz": {"min": quantity(8, "GHz"), "max": quantity(12, "GHz")},
                          "excitation_box": {"start": [*xy(-1, 0), quantity(1, "mm")], "stop": [*xy(1, 0), quantity(1, "mm")]}}]
    validate_project(document)
    return document


def snapshot_for(document):
    """! @brief 시험 문서의 실제 canonical 바이트와 전체 SnapshotRef를 결합한다."""
    raw = canonical_bytes(document)
    return {"snapshot_id": str(uuid4()), "project_id": document["project_id"], "revision_id": document["revision_id"],
            "schema_version": document["schema_version"], "canonical_version": "rfad.canonical/1.0", "content_hash": canonical_hash(document),
            "sealed_at": 1794340000.0, "description": "Explicit native interface test", "validation_state": "not_evaluated",
            "artifact": {"uri": "test/project.json", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}}


def runtime_identity():
    """! @brief pure 계약 시험용이며 실제 native 설치 증거로 사용하지 않는 식별이다."""
    return {"runtime_profile": "openems-wsl-reference/0.1", "manifest_sha256": "1" * 64,
            "code_files": [{"path": "tools/openems_worker.py", "sha256": "2" * 64, "bytes": 1}], "transport": {"test_only": True}}


class PcbPlanTests(unittest.TestCase):
    """! @brief 사용자 입력과 해석 제한의 경계를 순수 표준 라이브러리로 검사한다."""

    def test_circle_and_rectangle_preserve_source(self):
        """! @brief 두 기판 외곽은 원본 불변성과 실제 형상 의미를 유지한다."""
        for circle in (False, True):
            document = fixture_document(circle=circle, arc=True)
            before = canonical_bytes(document)
            plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
            validate_pcb_plan(plan)
            self.assertEqual(canonical_bytes(document), before)
            self.assertEqual(plan["case"]["board"]["kind"], "circle" if circle else "rectangle")
            self.assertEqual(plan["model_report"]["physical_validation_state"], "not_validated")
            self.assertEqual(len(plan["case"]["shapes"]), 3)

    def test_missing_material_and_port_geometry_are_blocked(self):
        """! @brief 미정 물성과 급전의 실제 편집 객체와 입력 위치를 반환한다."""
        document = fixture_document(arc=True)
        layer = document["stackup"][0]
        material = next(m for m in document["materials"] if m["id"] == layer["material_id"])
        metal_layer = document["stackup"][1]
        metal = next(m for m in document["materials"] if m["id"] == metal_layer["material_id"])
        port = document["ports"][0]
        cases = (
            (layer, "material_id", None, f"stackup.{layer['id']}.material_id"),
            (material, "epsilon_r", Quantity.missing("dimensionless", "1").to_dict(),
             f"materials.{material['id']}.epsilon_r"),
            (material["validity_hz"], "max", quantity(11, "GHz"), f"materials.{material['id']}.validity_hz.max"),
            (metal, "conductivity", quantity(100, "S/m"), f"materials.{metal['id']}.conductivity"),
            (metal_layer, "thickness", quantity(0.201, "mm"), f"stackup.{metal_layer['id']}.thickness"),
            (port, "resistance", Quantity.missing("impedance", "ohm").to_dict(), f"ports.{port['id']}.resistance"),
            (port, "polarity", -1, f"ports.{port['id']}.polarity"),
            (port["excitation_box"]["stop"], 0, Quantity.missing("length", "mm").to_dict(),
             f"ports.{port['id']}.excitation_box.stop[0]"),
        )
        for owner, key, invalid, path in cases:
            with self.subTest(field=path):
                original = owner[key]
                owner[key] = invalid
                with self.assertRaises(ProjectError) as error:
                    build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
                self.assertEqual(error.exception.details["field_path"], path)
                owner[key] = original
        del port["excitation_box"]
        with self.assertRaises(ProjectError) as error:
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        self.assertEqual(error.exception.details["field_path"], f"ports.{port['id']}.excitation_box.start[0]")

    def test_sheet_does_not_require_unconsumed_dielectric_properties(self):
        """! @brief 금속 sheet에서 소비하지 않는 유전율/손실을 임의 수치로 채우지 않는다."""
        document = fixture_document()
        metal = next(m for m in document["materials"] if m["id"] == document["stackup"][1]["material_id"])
        metal["epsilon_r"] = Quantity.missing("dimensionless", "1").to_dict()
        metal["tan_delta"] = Quantity.missing("dimensionless", "1").to_dict()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        consumed = next(m for m in plan["case"]["materials"] if m["id"] == metal["id"])
        self.assertEqual(consumed["consumed_properties"], ["conductivity"])
        self.assertIsNone(plan["source_semantics"]["materials"][document["materials"].index(metal)]["epsilon_r"]["value_si"])

    def test_circle_corner_is_not_admitted_by_bounding_rectangle(self):
        """! @brief 원의 bounding rectangle 안이지만 실제 원 밖인 round cap을 거부한다."""
        document = fixture_document(circle=True)
        shape = document["geometry"][0]
        shape["start"], shape["end"] = [quantity(6, "mm"), quantity(6, "mm")], [quantity(7, "mm"), quantity(6, "mm")]
        with self.assertRaisesRegex(ProjectError, "실제 기판 외곽"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)

    def test_plan_tampering_and_mesh_budget_are_rejected(self):
        """! @brief 계획 원본이나 격자 예산 변경을 정상 입력으로 승격하지 않는다."""
        document = fixture_document()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        plan["case"]["materials"][0]["epsilon_r"] += 1
        with self.assertRaises(ProjectError):
            validate_pcb_plan(plan)
        with self.assertRaises(ProjectError):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), {**SETTINGS, "grid_mm": 0.05})

    def test_tuning_refinement_changes_only_the_explicit_compute_budget(self):
        """! @brief 튜닝용 장시간 계산을 봉인하고 기본 및 손실 연구 조건을 보존한다."""
        document = fixture_document()
        snapshot = snapshot_for(document)
        runtime = runtime_identity()
        default = build_pcb_plan(document, snapshot, runtime, SETTINGS)
        profile = {"kind": "tuning_refinement/0.1", "num_threads": 4}
        settings = {**SETTINGS, "compute_profile": profile}
        extended = build_pcb_plan(document, snapshot, runtime, settings)
        validate_pcb_plan(extended)

        self.assertEqual(extended["case"]["settings"]["compute_profile"], profile)
        self.assertEqual(extended["case"]["num_threads"], 4)
        self.assertEqual(default["case"]["num_threads"], 2)
        self.assertEqual({k: v for k, v in extended["case"].items() if k not in {"settings", "num_threads"}},
                         {k: v for k, v in default["case"].items() if k not in {"settings", "num_threads"}})
        self.assertEqual(extended["resource_estimate"]["estimated_grid_points"], default["resource_estimate"]["estimated_grid_points"])
        self.assertEqual(extended["resource_estimate"]["max_wall_time_seconds"], 900)
        self.assertEqual(default["resource_estimate"]["max_wall_time_seconds"], 300)
        for invalid in ({**profile, "num_threads": 9}, {"kind": "loss_refinement/0.1", "num_threads": 2}):
            with self.assertRaises(ProjectError):
                build_pcb_plan(document, snapshot, runtime, {**SETTINGS, "compute_profile": invalid})

    def test_full_ring_preserves_hole(self):
        """! @brief 전체 회전은 원판 하나로 바꾸지 않고 구멍이 있는 sector 합집합을 사용한다."""
        shape = {"kind": "arc_path", "center_mm": [0, 0], "radius_mm": 4, "width_mm": 1, "start_angle_deg": 17, "sweep_angle_deg": -360}
        polygons = shape_polygons(shape, 0.025)
        self.assertEqual(len(polygons), 4)
        self.assertTrue(all(math.hypot(*p) >= 3.5 - 1e-12 for poly in polygons for p in poly))

    def test_nearly_closed_arc_caps_are_rejected(self):
        """! @brief 전체 ring과 달리 거의 닫힌 원호의 자기 중첩을 허용하지 않는다."""
        document = fixture_document(circle=True, arc=True)
        next(shape for shape in document["geometry"] if shape["kind"] == "arc_path")["sweep_angle"] = quantity(350, "deg")
        with self.assertRaisesRegex(ProjectError, "자체 중첩"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)

    def test_analytic_contact_without_native_polygon_contact_is_rejected(self):
        """! @brief 원래 round cap에 닿아도 실제 근사 polygon에 닿지 않는 포트는 거절한다."""
        document = fixture_document(circle=True)
        gap_end = 1.5 - math.sqrt(0.5 ** 2 - 0.2 ** 2)
        document["ports"][0]["excitation_box"] = {
            "start": [quantity(-gap_end, "mm"), quantity(0.2, "mm"), quantity(1, "mm")],
            "stop": [quantity(gap_end, "mm"), quantity(0.2, "mm"), quantity(1, "mm")],
        }
        with self.assertRaisesRegex(ProjectError, "native polygon 경계"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)

    def test_different_net_contact_is_rejected_in_plan(self):
        """! @brief 도체 역할/외곽이 유효해도 서로 다른 net의 실제 접촉은 차단한다."""
        document = fixture_document(circle=True)
        reference = next(shape for shape in document["geometry"] if shape["role"] == "ground")
        added = {**deepcopy(reference), "id": str(uuid4()), "start": [quantity(2, "mm"), quantity(1, "mm")],
                 "end": [quantity(4, "mm"), quantity(1, "mm")]}
        document["geometry"].append(added)
        document["geometry"].sort(key=lambda item: item["id"])
        with self.assertRaisesRegex(ProjectError, "서로 다른 net"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)

    def test_result_rejects_nonfinite_frequency_and_false_vswr_status(self):
        """! @brief 원시 결과가 아닌 검증 경계에서 NaN 주파수와 잘못된 표시 상태를 차단한다."""
        document = fixture_document(circle=True)
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        samples = [{"frequency_hz": 8e9 + 4e9 * index / 30, "s11": [0.5, 0], "impedance_ohm": [150, 0],
                    "vswr": 3.0, "s11_db": 20 * math.log10(0.5), "vswr_status": "defined"} for index in range(31)]
        result = {"schema": "rfad.openems-pcb-result/0.1", "analysis_plan_id": plan["plan_id"], "normalization": plan["normalization"],
                  "samples": samples, "assessment": {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True},
                  "termination": {"status": "end_criterion_reached"}}
        validate_result(plan, result)
        for bad in (float("nan"), float("inf"), True, "8000000000"):
            tampered = deepcopy(result)
            tampered["samples"][0]["frequency_hz"] = bad
            with self.assertRaises(ProjectError):
                validate_result(plan, tampered)
        tampered = deepcopy(result)
        tampered["samples"][0]["vswr_status"] = "undefined_reflection_ge_one"
        with self.assertRaises(ProjectError):
            validate_result(plan, tampered)

    def test_step_limit_and_cancel_log_never_become_converged(self):
        """! @brief 시간 상한이나 중단 로그를 에너지 종료로 표기하지 않는다."""
        good = "Exact-endcriteria: evaluating the end criteria every 10 steps\nRunFDTD: end-criteria of -40.00dB reached after 1000 timesteps (-41.20dB)"
        self.assertEqual(check_termination(good, 1000, SETTINGS)["status"], "end_criterion_reached")
        for log, steps in ((good + "\nABORTING SIMULATION", 1000), (good, 20000), (good.replace("41.20", "39.00"), 1000)):
            with self.assertRaises(ProjectError):
                check_termination(log, steps, SETTINGS)

    def test_execution_cost_separates_limits_and_actual_measurements(self):
        """! @brief 완료하지 못한 계산의 범위 있는 자원 관측과 시간 단계 종료를 구분한다."""
        document = fixture_document(arc=True)
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        lines = mesh_lines(plan["case"])
        job = {"kind": "em_analysis", "solver": {"analysis_plan": plan, "preparation": {"mesh_statistics": {"lines_mm": lines}}},
               "input": {"budget": {"timeout_seconds": 10}}}
        predicted = estimate(plan, lines)
        self.assertAlmostEqual(predicted["wall_seconds_high"] / predicted["wall_seconds_low"], 3)
        process = {"state": "timeout", "termination_confirmed": True,
                   "native": {"wall_seconds": 10.2, "file_monitor": {"observed_peak_bytes": 1234}}}
        timeout = stopped(job, "failed", process, ProjectError("E_RESOURCE", "시간 한도"))
        self.assertEqual(timeout["termination"]["reason"], "timeout")
        self.assertEqual(timeout["estimate"], predicted)
        self.assertEqual(timeout["actual"]["worker_wall_seconds"], 10.2)
        self.assertEqual(timeout["actual"]["observed_output_peak_bytes"], 1234)
        self.assertIsNone(timeout["actual"]["wall_seconds"])
        self.assertIsNone(timeout["actual"]["peak_rss_bytes"])
        self.assertIsNone(timeout["actual"]["raw_output_bytes"])
        self.assertEqual(stopped(job, "cancelled", process, ProjectError("E_SOLVER", "사용자 취소"))["termination"]["reason"], "cancelled")
        observed = {"scope": NATIVE_SCOPE, "wall_seconds": 7.2, "peak_rss_bytes": 1024, "raw_output_bytes": 321}
        limited = stopped(job, "failed", {"state": "failed", "termination_confirmed": True},
                          ProjectError("E_SOLVER", "시간 단계 한도", details={"criterion": "native_timestep_limit",
                                       "iterations": 1000, "execution_cost": observed}))
        self.assertEqual(limited["termination"]["reason"], "timestep_limit")
        self.assertEqual(limited["termination"]["iterations"], 1000)
        self.assertTrue(limited["actual"]["partial_raw"])
        self.assertEqual(limited["actual"]["peak_rss_bytes"], 1024)
        self.assertEqual(limited["actual"]["raw_output_bytes"], 321)
        with self.assertRaises(ProjectError):
            validate_measurement({**observed, "peak_rss_bytes": True})


if __name__ == "__main__":
    unittest.main()
