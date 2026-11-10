"""! @brief native 실행 없이 참조 계획의 불변성, 출처와 지원 경계를 검증한다."""

from copy import deepcopy
import math
import unittest
from uuid import UUID, uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.solver import (
    MAX_ARTIFACT_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_WALL_TIME_SECONDS,
    PLAN_SCHEMA,
    PREPARED_PLAN_SCHEMA,
    PROFILE,
    RUNTIME_PROFILE,
    build_analysis_plan,
    case_spec,
    make_prepared_plan,
    normalization_contract,
    validate_reference_plan,
)
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command, new_project
from test_cad_projection import snapshot_for
from test_design import build_design, quantity


def runtime_fixture() -> dict:
    """! @brief 실제 설치를 주장하지 않는 host 식별 형식의 시험 데이터를 만든다."""
    return {
        "runtime_profile": RUNTIME_PROFILE,
        "manifest_sha256": "a" * 64,
        "code_files": [{"path": "rfad/application/solver.py", "sha256": "b" * 64, "bytes": 32}],
        "transport": {"distribution": "test-only", "python": "/test-only/python", "native_version": "test-only"},
    }


class SolverPlanTests(unittest.TestCase):
    """! @brief 사용자 설계와 참조 사례가 혼동되지 않는 계획 계약을 확인한다."""

    def setUp(self):
        """! @brief 각 시험에 새 원본, 봉인 참조와 runtime 관측값을 준비한다."""
        self.document = new_project("명시적 도파관 참조")
        self.snapshot = snapshot_for(self.document)
        self.runtime = runtime_fixture()

    def plan(self, grid_mm=1.0):
        """! @brief 현재 시험 입력에서 새 참조 계획을 만든다."""
        return build_analysis_plan(self.document, self.snapshot, self.runtime, grid_mm)

    def assert_error(self, operation, code, field):
        """! @brief 사용자에게 전달되는 오류 코드와 수정 위치를 함께 검사한다."""
        with self.assertRaises(ProjectError) as raised:
            operation()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.details["field_path"], field)

    def test_build_preserves_all_inputs_and_full_snapshot(self):
        """! @brief 전체 SnapshotRef와 원본은 깊은 복사되며 입력을 변경하지 않는다."""
        original = deepcopy((self.document, self.snapshot, self.runtime))
        plan = self.plan()
        self.assertEqual((self.document, self.snapshot, self.runtime), original)
        self.assertEqual(plan["snapshot"], self.snapshot)
        self.assertEqual(plan["source_semantics"], self.document)
        self.assertEqual(plan["runtime_identity"], self.runtime)
        self.assertEqual(plan["schema"], PLAN_SCHEMA)
        self.assertEqual(plan["analysis_profile"], PROFILE)
        self.assertEqual(plan["runtime_profile"], RUNTIME_PROFILE)
        self.assertEqual(str(UUID(plan["plan_id"])), plan["plan_id"])
        self.assertNotIn(plan["plan_id"], [self.snapshot[key] for key in ("snapshot_id", "project_id", "revision_id")])
        validate_reference_plan(plan)
        plan["snapshot"]["artifact"]["uri"] = "changed/file.json"
        plan["source_semantics"]["metadata"]["name"] = "changed"
        plan["runtime_identity"]["code_files"][0]["bytes"] = 20
        self.assertEqual((self.document, self.snapshot, self.runtime), original)

    def test_each_plan_gets_independent_identity(self):
        """! @brief 동일 원본에서 생성한 별개 계획은 별개 ID를 가진다."""
        first = self.plan()
        second = self.plan()
        self.assertNotEqual(first.pop("plan_id"), second.pop("plan_id"))
        self.assertEqual(first, second)

    def test_estimates_are_labeled_and_do_not_claim_actual_mesh(self):
        """! @brief 초기 추정 격자와 실제 native 준비 통계를 구분한다."""
        for grid, dimensions, count in ((1.0, [20, 10, 80], 16000), (0.75, [27, 14, 109], 41202)):
            with self.subTest(grid=grid):
                plan = self.plan(grid)
                estimate = plan["resource_estimate"]
                self.assertEqual(estimate["estimated_cells_xyz"], dimensions)
                self.assertEqual(estimate["estimated_cell_count"], count)
                self.assertEqual(estimate["kind"], "initial_estimate_not_actual_mesh")
                self.assertEqual(estimate["max_output_bytes"], MAX_OUTPUT_BYTES)
                self.assertEqual(estimate["max_artifact_bytes"], MAX_ARTIFACT_BYTES)
                self.assertEqual(estimate["max_wall_time_seconds"], MAX_WALL_TIME_SECONDS)
                self.assertNotIn("actual_mesh", plan)
                self.assertNotIn("native_input_hashes", plan)
                validate_reference_plan(plan)

    def test_boolean_nonfinite_and_unsupported_grids_are_rejected(self):
        """! @brief True가 1과 같더라도 명시 격자 입력으로 허용하지 않는다."""
        for grid in (True, False, None, "1.0", 0.0, -1.0, 0.5, 1.000001, math.nan, math.inf):
            with self.subTest(grid=grid):
                self.assert_error(lambda: self.plan(grid), "E_UNSUPPORTED", "grid_mm")

    def test_snapshot_id_revision_and_hash_binding(self):
        """! @brief 다른 프로젝트/개정/내용의 봉인 참조를 계획에 사용할 수 없다."""
        for field, value, code in (
            ("project_id", str(uuid4()), "E_CONFLICT"),
            ("revision_id", str(uuid4()), "E_CONFLICT"),
            ("content_hash", "f" * 64, "E_HASH"),
            ("canonical_version", "rfad.canonical/future", "E_VERSION"),
            ("schema_version", "rfad.project/future", "E_VERSION"),
            ("snapshot_id", self.document["project_id"], "E_SCHEMA"),
        ):
            with self.subTest(field=field):
                snapshot = deepcopy(self.snapshot)
                snapshot[field] = value
                self.assert_error(lambda: build_analysis_plan(self.document, snapshot, self.runtime, 1.0), code, "snapshot." + field)

    def test_snapshot_cannot_be_shortened(self):
        """! @brief 접수용 축약 참조를 worker 실행 계획에 보관하지 않는다."""
        for field in self.snapshot:
            with self.subTest(field=field):
                snapshot = deepcopy(self.snapshot)
                del snapshot[field]
                self.assert_error(lambda: build_analysis_plan(self.document, snapshot, self.runtime, 1.0), "E_SCHEMA", "snapshot")

    def test_snapshot_artifact_path_and_size_checks(self):
        """! @brief 봉인 참조는 상대 경로와 제한된 양의 크기를 필요로 한다."""
        for uri in ("/absolute/file", "../file", "x/../file", "x//file", "C:/file", "x\\file", "x/./file", "x/\x00file"):
            with self.subTest(uri=uri):
                snapshot = deepcopy(self.snapshot)
                snapshot["artifact"]["uri"] = uri
                self.assert_error(lambda: build_analysis_plan(self.document, snapshot, self.runtime, 1.0), "E_SCHEMA", "snapshot.artifact.uri")
        for size in (True, 0, -1, MAX_ARTIFACT_BYTES + 1):
            with self.subTest(size=size):
                snapshot = deepcopy(self.snapshot)
                snapshot["artifact"]["bytes"] = size
                self.assert_error(lambda: build_analysis_plan(self.document, snapshot, self.runtime, 1.0), "E_RESOURCE", "snapshot.artifact.bytes")

    def test_user_design_is_not_silently_replaced_with_waveguide(self):
        """! @brief 명시적인 보드/패턴 설계를 참조 도파관으로 오해석하지 않는다."""
        document = build_design(with_port=True)
        before = deepcopy(document)
        snapshot = snapshot_for(document)
        self.assert_error(lambda: build_analysis_plan(document, snapshot, self.runtime, 1.0), "E_UNSUPPORTED", "board")
        self.assertEqual(document, before)

    def test_user_parameters_and_extensions_are_not_ignored(self):
        """! @brief 참조 사례는 사용자 파라미터나 미지 extension을 소비한 척하지 않는다."""
        parameter_document, _, _, _ = apply_command(self.document, {
            "command_id": str(uuid4()), "type": "parameter.set",
            "payload": {"id": str(uuid4()), "name": "length", "quantity": quantity(20.0, "mm")},
        }, self.document["revision_id"])
        extension_document = deepcopy(self.document)
        extension_document["extensions"] = {"material": {"epsilon_r": 4.2}}
        for document, field in ((parameter_document, "parameters"), (extension_document, "extensions")):
            with self.subTest(field=field):
                self.assert_error(lambda: build_analysis_plan(document, snapshot_for(document), self.runtime, 1.0), "E_UNSUPPORTED", field)

    def test_source_hash_catches_post_seal_metadata_changes(self):
        """! @brief geometry 외의 원본 변경도 봉인 후에는 해시 불일치로 판정한다."""
        self.document["metadata"]["name"] = "변경된 이름"
        self.assert_error(self.plan, "E_HASH", "snapshot.content_hash")

    def test_plan_does_not_infer_board_material_or_claim_antenna_validation(self):
        """! @brief 명시적 vacuum과 미정 사용자 물성/안테나 검증 상태를 구분한다."""
        plan = self.plan()
        self.assertIsNone(plan["source_semantics"]["board"])
        self.assertEqual(plan["source_semantics"]["materials"], [])
        self.assertEqual(plan["case"]["medium"]["kind"], "vacuum")
        self.assertFalse(plan["model_report"]["user_geometry_consumed"])
        self.assertFalse(plan["model_report"]["user_materials_consumed"])
        self.assertEqual(plan["model_report"]["physical_validation_state"], "not_evaluated")
        self.assertIn("nf2ff", plan["model_report"]["unsupported_observables"])
        self.assertIn("full_s_matrix", plan["model_report"]["unsupported_observables"])

    def test_normalization_does_not_turn_pulse_spectra_into_absolute_power(self):
        """! @brief 원 pulse unit, stop 기준면과 ratio 정규화 계약을 보존한다."""
        normalization = normalization_contract()
        self.assertEqual(normalization["native_voltage_unit"], "V*s")
        self.assertEqual(normalization["native_current_unit"], "A*s")
        self.assertEqual(normalization["native_to_rms_conversion"], "none")
        self.assertEqual(normalization["reference_planes_mm"], [15.0, 65.0])
        self.assertEqual(normalization["reference_plane_shift_mm"], 0.0)
        self.assertEqual(normalization["absolute_power_gain_efficiency"], "not_evaluated")
        self.assertEqual(normalization["channels"]["s21"]["formula"], "port2.uf_ref/port1.uf_inc")

    def test_fixed_case_and_stop_policy(self):
        """! @brief 참고 checker와 같은 명시 조건을 사용하고 시간 예산을 물리 시간과 분리한다."""
        case = self.plan()["case"]
        self.assertEqual(case["dimensions_mm"], [20.0, 10.0, 80.0])
        self.assertEqual(case["delta_unit_m"], 0.001)
        self.assertEqual(case["frequency_hz"], {"start": 9.5e9, "stop": 10.5e9, "count": 31})
        self.assertEqual(case["boundary_conditions"], ["PEC", "PEC", "PEC", "PEC", "PML_8", "PML_8"])
        self.assertEqual(case["stop_criteria"]["max_timesteps"], 20000)
        self.assertEqual(case["stop_criteria"]["energy_decay"], 1e-7)
        self.assertIsNone(case["stop_criteria"]["simulation_time_limit_s"])
        self.assertTrue(case["stop_criteria"]["exact_end_criteria"])
        self.assertFalse(self.plan()["validation_policy"]["timesteps_exhausted_is_converged"])

    def test_case_and_normalization_helpers_return_fresh_objects(self):
        """! @brief 공개 helper의 반환값 변경으로 후속 계획의 공유 상수를 오염시키지 않는다."""
        case_spec(1.0)["medium"]["epsilon_r"] = 5.0
        normalization_contract()["channels"]["s21"]["unit"] = "W"
        self.assertEqual(case_spec(1.0)["medium"]["epsilon_r"], 1.0)
        self.assertEqual(normalization_contract()["channels"]["s21"]["unit"], "1")

    def test_worker_validator_rejects_mutated_fixed_conditions(self):
        """! @brief runtime 작업이 고정 profile 밖의 모델을 받아 실행하지 않는다."""
        for field, value in (("dimensions_mm", [20.0, 10.0, 81.0]), ("num_threads", 8), ("medium", {"kind": "FR4"})):
            with self.subTest(field=field):
                plan = self.plan()
                plan["case"][field] = value
                self.assert_error(lambda: validate_reference_plan(plan), "E_UNSUPPORTED", "analysis_plan")

    def test_worker_validator_rejects_type_aliases_and_extra_fields(self):
        """! @brief True/1 또는 부가 필드가 canonical 검증을 우회하지 않는다."""
        plan = self.plan()
        plan["case"]["ports"][0]["excite"] = True
        self.assert_error(lambda: validate_reference_plan(plan), "E_UNSUPPORTED", "analysis_plan")
        plan = self.plan()
        plan["actual_mesh"] = {"cells": 1}
        self.assert_error(lambda: validate_reference_plan(plan), "E_UNSUPPORTED", "analysis_plan")

    def test_worker_validator_rejects_mutated_snapshot_and_source(self):
        """! @brief worker 입구에서도 전체 스냅샷과 원본의 결합을 재검사한다."""
        plan = self.plan()
        plan["source_semantics"]["metadata"]["name"] = "변조"
        self.assert_error(lambda: validate_reference_plan(plan), "E_HASH", "snapshot.content_hash")
        plan = self.plan()
        del plan["snapshot"]["sealed_at"]
        self.assert_error(lambda: validate_reference_plan(plan), "E_SCHEMA", "snapshot")

    def test_worker_validator_rejects_schema_and_identity_confusion(self):
        """! @brief 계획 버전과 독립 식별자 규약을 검사한다."""
        plan = self.plan()
        plan["schema"] = "rfad.analysis-plan/future"
        self.assert_error(lambda: validate_reference_plan(plan), "E_VERSION", "analysis_plan.schema")
        plan = self.plan()
        plan["plan_id"] = self.snapshot["snapshot_id"]
        self.assert_error(lambda: validate_reference_plan(plan), "E_SCHEMA", "analysis_plan.plan_id")

    def test_runtime_is_required_and_mismatched_profile_is_rejected(self):
        """! @brief runtime 정보를 추측하지 않고 host의 profile 불일치를 차단한다."""
        for identity in (None, {}, [], "test"):
            with self.subTest(identity=identity):
                self.assert_error(lambda: build_analysis_plan(self.document, self.snapshot, identity, 1.0), "E_SCHEMA", "runtime_identity")
        runtime = deepcopy(self.runtime)
        runtime["runtime_profile"] = "other-profile"
        self.assert_error(lambda: build_analysis_plan(self.document, self.snapshot, runtime, 1.0), "E_VERSION", "runtime_identity.runtime_profile")
        runtime["runtime_profile"] = RUNTIME_PROFILE
        runtime["non_json"] = math.inf
        self.assert_error(lambda: build_analysis_plan(self.document, self.snapshot, runtime, 1.0), "E_SCHEMA", "runtime_identity")

    def test_runtime_fingerprint_requires_hashes_and_unique_sources(self):
        """! @brief runtime 출처가 비어 있거나 서로 겹치는 파일 목록이면 계획을 차단한다."""
        runtime = deepcopy(self.runtime)
        runtime["manifest_sha256"] = "invalid"
        self.assert_error(lambda: build_analysis_plan(self.document, self.snapshot, runtime, 1.0), "E_SCHEMA", "runtime_identity.manifest_sha256")
        runtime = deepcopy(self.runtime)
        runtime["code_files"].append(deepcopy(runtime["code_files"][0]))
        self.assert_error(lambda: build_analysis_plan(self.document, self.snapshot, runtime, 1.0), "E_SCHEMA", "runtime_identity.code_files[1].path")
        runtime = deepcopy(self.runtime)
        runtime["transport"] = {}
        self.assert_error(lambda: build_analysis_plan(self.document, self.snapshot, runtime, 1.0), "E_SCHEMA", "runtime_identity.transport")
        runtime = deepcopy(self.runtime)
        runtime["code_files"] = []
        self.assert_error(lambda: build_analysis_plan(self.document, self.snapshot, runtime, 1.0), "E_RESOURCE", "runtime_identity.code_files")

    def test_prepared_plan_has_independent_identity_and_immutable_references(self):
        """! @brief native 준비 결과는 원 계획을 바꾸지 않고 새 객체로 연결한다."""
        plan = self.plan()
        reference = {"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan), "artifact": {"uri": "plans/analysis.json", "sha256": "c" * 64, "bytes": 1200}}
        preparation = {"uri": "runs/prepare/preparation.json", "sha256": "d" * 64, "bytes": 2500}
        original = deepcopy((plan, reference, preparation, self.snapshot, self.runtime))
        prepared = make_prepared_plan(reference, self.snapshot, preparation, self.runtime)
        self.assertEqual(prepared["schema"], PREPARED_PLAN_SCHEMA)
        self.assertEqual(prepared["validation_state"], "prepared")
        self.assertNotEqual(prepared["prepared_plan_id"], plan["plan_id"])
        self.assertEqual(prepared["analysis_plan"]["content_hash"], canonical_hash(plan))
        self.assertEqual(prepared["snapshot"], self.snapshot)
        self.assertEqual((plan, reference, preparation, self.snapshot, self.runtime), original)
        prepared["analysis_plan"]["artifact"]["bytes"] = 3
        prepared["preparation_artifact"]["bytes"] = 3
        prepared["runtime_identity"]["code_files"][0]["bytes"] = 3
        self.assertEqual((plan, reference, preparation, self.snapshot, self.runtime), original)

    def test_prepared_plan_rejects_incomplete_or_unsafe_artifact_references(self):
        """! @brief 준비 봉인은 축약 계획 참조와 저장소 외부 artifact를 수용하지 않는다."""
        plan = self.plan()
        reference = {"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan), "artifact": {"uri": "plans/analysis.json", "sha256": "c" * 64, "bytes": 1200}}
        preparation = {"uri": "runs/prepare/preparation.json", "sha256": "d" * 64, "bytes": 2500}
        short = {"plan_id": reference["plan_id"], "content_hash": reference["content_hash"]}
        self.assert_error(lambda: make_prepared_plan(short, self.snapshot, preparation, self.runtime), "E_SCHEMA", "analysis_plan")
        preparation["uri"] = "../outside.json"
        self.assert_error(lambda: make_prepared_plan(reference, self.snapshot, preparation, self.runtime), "E_SCHEMA", "preparation_artifact.uri")


if __name__ == "__main__":
    unittest.main()
