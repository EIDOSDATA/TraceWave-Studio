"""! @brief 선택적 PCB 방사의 입력, 봉인 결과와 읽기 전용 페이지 경계를 검사한다."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan, validate_settings
from rfad.application.pcb_radiation import raw_names, validate_result, summary, SCHEMA
from rfad.application.radiation import spectral_power_metrics
from rfad.application.radiation_queries import radiation_chart
from rfad.application.solver_artifacts import check_solver_result
from rfad.domain.errors import ProjectError
from test_pcb_solver import fixture_document, snapshot_for, runtime_identity, SETTINGS


def radiation_plan(*, circle=False, step=30):
    """! @brief 제조 물성을 추가하지 않고 명시적 시험 모델의 방사 옵션만 선택한다."""
    document = fixture_document(circle=circle, arc=circle)
    settings = {**deepcopy(SETTINGS), "air_padding_mm": 8.0,
                "radiation": {"frequency_hz": [10e9], "theta_step_deg": step, "phi_step_deg": step}}
    return build_pcb_plan(document, snapshot_for(document), runtime_identity(), settings)


def field_result(plan):
    """! @brief 경계 검사용 복소 패턴을 만들며 실제 NF2FF 물리 계산을 주장하지 않는다."""
    recording = plan["case"]["radiation_recording"]
    nt, np = len(recording["theta_deg"]), len(recording["phi_deg"])
    pair = lambda value: [[[value, 0.0] for _ in range(np)] for _ in range(nt)]
    matrix = lambda value: [[value for _ in range(np)] for _ in range(nt)]
    return {"schema": SCHEMA, "analysis_plan_id": plan["plan_id"], "recording": deepcopy(recording),
            "frequencies": [{"frequency_hz": 10e9, "metrics": spectral_power_metrics(0.4e-24, 0.5e-24, 1e-24, 1.64),
                             "e_theta": pair(1e-12), "e_phi": pair(0), "normalized_power": matrix(1), "directivity": matrix(1.64)}],
            "electric_field_unit": "V*s/m", "power_unit": "W*s^2", "absolute_power_w": None,
            "physics_validated": False, "status": "computed_unvalidated"}


class PcbRadiationTests(unittest.TestCase):
    """! @brief 기록 범위와 원본 출처를 보존하며 크기가 제한된 조회를 검사한다."""

    def test_opt_in_preserves_old_plan_contract(self):
        """! @brief 기존 설정에는 방사 파일/정규화 필드를 자동 추가하지 않는다."""
        document = fixture_document()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        validate_pcb_plan(plan)
        self.assertNotIn("radiation_recording", plan["case"])
        self.assertEqual(len(raw_names(plan)), 6)
        self.assertNotIn("radiation_power_unit", plan["normalization"])

    def test_recording_encloses_rectangular_and_circular_physical_board(self):
        """! @brief PML에서 두 공기 격자를 띄우고 물리 적층 전체를 폐곡면 안에 둔다."""
        for circle in (False, True):
            plan = radiation_plan(circle=circle)
            validate_pcb_plan(plan)
            recording = plan["case"]["radiation_recording"]
            bounds = [*plan["case"]["board"]["bounds_mm"], [0, 1.035]]
            for index, (low, high) in enumerate(bounds):
                self.assertLess(recording["start_mm"][index], low)
                self.assertGreater(recording["stop_mm"][index], high)
                self.assertAlmostEqual(recording["center_m"][index], (recording["start_mm"][index] + recording["stop_mm"][index]) * 0.0005)
            self.assertEqual(len(set(raw_names(plan))), 18)
            self.assertNotIn("NF2FF", plan["model_report"]["unsupported_observables"])

    def test_insufficient_air_is_blocked_before_native_execution(self):
        """! @brief 기판이나 PML과 교차할 폐곡면을 자동 축소하여 수용하지 않는다."""
        document = fixture_document()
        settings = {**deepcopy(SETTINGS), "air_padding_mm": 5,
                    "radiation": {"frequency_hz": [10e9], "theta_step_deg": 30, "phi_step_deg": 30}}
        with self.assertRaisesRegex(ProjectError, "NF2FF"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), settings)

    def test_settings_reject_implicit_out_of_band_and_unbounded_requests(self):
        """! @brief null, bool, 무한 수치와 과도한 각도/주파수 요청을 거부한다."""
        for value in (None, {}, {"frequency_hz": [True], "theta_step_deg": 30, "phi_step_deg": 30},
                      {"frequency_hz": [float("nan")], "theta_step_deg": 30, "phi_step_deg": 30},
                      {"frequency_hz": [7e9], "theta_step_deg": 30, "phi_step_deg": 30},
                      {"frequency_hz": [10e9, 9e9], "theta_step_deg": 30, "phi_step_deg": 30},
                      {"frequency_hz": [9e9] * 4, "theta_step_deg": 30, "phi_step_deg": 30},
                      {"frequency_hz": [10e9], "theta_step_deg": 1, "phi_step_deg": 30},
                      {"frequency_hz": [10e9], "theta_step_deg": 30, "phi_step_deg": True}):
            with self.subTest(value=value), self.assertRaises(ProjectError):
                validate_settings({**SETTINGS, "radiation": value})

    def test_field_and_power_tampering_is_rejected(self):
        """! @brief 전력 비율과 복소 필드의 대응 및 계산/물리 검증 구분을 검사한다."""
        plan = radiation_plan()
        original = field_result(plan)
        validate_result(plan, original)
        rounded = deepcopy(original)
        rounded["frequencies"][0]["metrics"]["gain_dbi"] += 1e-14
        validate_result(plan, rounded)
        for mode in ("frequency", "metric", "shape", "field", "pattern", "unit", "validated", "box", "overflow"):
            value = deepcopy(original)
            row = value["frequencies"][0]
            if mode == "frequency":
                row["frequency_hz"] += 1
            elif mode == "metric":
                row["metrics"]["gain_linear"] = 3
            elif mode == "shape":
                row["e_phi"].pop()
            elif mode == "field":
                row["e_theta"][0][0] = [True, 0]
            elif mode == "pattern":
                row["normalized_power"][0][0] = 0.5
            elif mode == "unit":
                value["power_unit"] = "W"
            elif mode == "validated":
                value["physics_validated"] = True
            elif mode == "box":
                value["recording"]["center_m"][0] += 1
            else:
                row["e_theta"][0][0] = [1e308, 0]
            with self.subTest(mode=mode), self.assertRaises(ProjectError):
                validate_result(plan, value)

    def test_missing_or_duplicate_recording_face_never_becomes_complete(self):
        """! @brief native 변환기가 일부 면만 읽더라도 게시 경계는 12면 전체를 요구한다."""
        plan = radiation_plan()
        roles = ["raw/" + name for name in raw_names(plan)] + ["raw_manifest", "normalized_result", "provenance", "radiation_result", "radiation_native"]
        for missing in ("raw/pcb_nf2ff_E_0.h5", "raw/pcb_nf2ff_H_5.h5", "radiation_result", "radiation_native"):
            with self.subTest(missing=missing), self.assertRaisesRegex(ProjectError, "필수 원시 파일"):
                check_solver_result(None, {"solver": {"analysis_plan": plan}}, {}, [{"role": role} for role in roles if role != missing])

    def test_pages_reassemble_exact_fields_without_solver(self):
        """! @brief 읽기 전용 서비스만으로 페이지를 복원하며 출처와 단위를 유지한다."""
        plan = radiation_plan(step=5)
        value = field_result(plan)
        artifact_id = str(uuid4())
        normalized = {"provenance": {"analysis_plan": plan}, "radiation_summary": summary(value)}
        blobs = {"field": canonical_bytes(value), "normalized": canonical_bytes(normalized)}
        record = {"artifact_id": artifact_id, "project_id": plan["snapshot"]["project_id"], "normalized": "normalized",
                  "files": [{"role": "radiation_result", "artifact": "field"}]}
        service = SimpleNamespace(journal=SimpleNamespace(read=lambda: {"solver_results": {artifact_id: record}}, read_artifact=blobs.__getitem__),
                                  _project=lambda state, context: None)
        params = {"contract_version": "rfad.api/2.0", "context": {"project_id": record["project_id"]}, "input": {"artifact_id": artifact_id}}
        rows, offset = [], 0
        while offset is not None:
            page = radiation_chart(service, {**params, "input": {**params["input"], "theta_offset": offset}})
            self.assertLess(len(canonical_bytes(page)), 128 * 1024)
            self.assertFalse(page["physics_validated"])
            self.assertIsNone(page["absolute_power_w"])
            self.assertEqual(page["snapshot"], plan["snapshot"])
            rows.extend(page["e_theta"])
            offset = page["next_offset"]
        self.assertEqual(rows, value["frequencies"][0]["e_theta"])
        for extra in ({"theta_offset": -1}, {"theta_offset": len(rows)}, {"theta_limit": 6}, {"frequency_index": 1}, {"frequency_index": True}):
            with self.subTest(extra=extra), self.assertRaises(ProjectError):
                radiation_chart(service, {**params, "input": {**params["input"], **extra}})
        record["files"] = []
        with self.assertRaisesRegex(ProjectError, "NF2FF"):
            radiation_chart(service, params)


if __name__ == "__main__":
    unittest.main()
