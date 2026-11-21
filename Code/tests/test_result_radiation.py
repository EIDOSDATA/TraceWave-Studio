"""! @brief 합성 복소 기준과 봉인 산출물로 방사 표시의 수치 및 출처 경계를 검사한다."""

from copy import deepcopy
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_radiation import summary
from rfad.application.radiation import spectral_power_metrics
from rfad.application.result_radiation import radiation
from rfad.application.result_metrics import metrics
from rfad.domain.errors import ProjectError
from rfad.domain.radiation_polarization import polarization, projection
from rfad.domain.units import Quantity
from test_pcb_radiation import radiation_plan, field_result
from test_pcb_power import power_plan, synthetic_result
from test_targets import target_input


def fixture(*, step=30, power=False, negative_loss=False):
    """! @brief 읽기만 허용하는 봉인 저장소 모형과 별도 source/pin 선택을 만든다."""
    plan = power_plan() if power else radiation_plan(step=step)
    value = field_result(plan)
    normalized = {"provenance": {"analysis_plan": plan}, "radiation_summary": summary(value)}
    blobs = {"radiation": canonical_bytes(value)}
    reference = lambda name: {"uri": "projects/test/" + name, "bytes": 0, "sha256": "a" * 64}
    record = {"normalized": reference("normalized"), "files": [{"role": "radiation_result", "artifact": reference("radiation")}]}
    if power:
        balance, value = synthetic_result(plan, dielectric=-0.05 if negative_loss else 0.05)
        normalized["power_balance"] = balance
        blobs["balance"] = canonical_bytes(balance)
        record["files"].append({"role": "power_balance_result", "artifact": reference("balance")})
    resolved = {"source": {"kind": "solver", "artifact_id": "test-source"},
                "pin": {"identity_hash": "a" * 64, "dataset_sha256": "b" * 64},
                "solver_record": record, "normalized": normalized, "solver_result_id": "test-source",
                "project": {"path": "projects/test"}, "source_snapshot": plan["snapshot"],
                "states": {"physics": "unestablished", "manufacturing": None, "measurement": None}}
    service = SimpleNamespace(journal=SimpleNamespace(read_artifact=lambda ref: blobs[ref["uri"].rsplit("/", 1)[1]]))
    params = {"contract_version": "rfad.api/2.0", "context": {"project_id": plan["snapshot"]["project_id"]},
              "input": {"source": deepcopy(resolved["source"]), "pin": deepcopy(resolved["pin"])}}
    return service, params, resolved, blobs, value


class PolarizationTests(unittest.TestCase):
    """! @brief 독립 직선/원형/타원 편파의 정확한 기준과 좌표를 확인한다."""

    def test_linear_circular_and_zero_are_distinct(self):
        """! @brief 무한 축비와 영전계 미정 상태를 유한 원형 값으로 바꾸지 않는다."""
        self.assertEqual(polarization([1, 0], [0, 0], 0)["axial_ratio_state"], "infinite_linear")
        self.assertEqual(polarization([0, 0], [0, 0], 0)["axial_ratio_state"], "undefined_zero_field")
        right = polarization([1, 0], [0, -1], 0)
        self.assertAlmostEqual(right["rhcp_ri"][0], math.sqrt(2))
        self.assertEqual(right["lhcp_ri"], [0, 0])
        self.assertEqual(right["axial_ratio"], 1)
        self.assertEqual(right["axial_ratio_db"], 0)
        self.assertEqual(right["relative_phase_deg"], -90)
        left = polarization([1, 0], [0, 1], 0)
        self.assertEqual(left["rhcp_ri"], [0, 0])
        self.assertAlmostEqual(left["lhcp_ri"][0], math.sqrt(2))

    def test_ellipse_scale_and_azimuth_phase(self):
        """! @brief 축비 2의 타원과 원형 기저의 phi 위상을 별도로 대조한다."""
        value = polarization([2e-100, 0], [0, -1e-100], 90)
        self.assertAlmostEqual(value["axial_ratio"], 2)
        self.assertAlmostEqual(value["axial_ratio_db"], 20 * math.log10(2))
        self.assertAlmostEqual(value["rhcp_ri"][1] / 1e-100, 3 / math.sqrt(2))
        self.assertAlmostEqual(value["lhcp_ri"][1] / 1e-100, -1 / math.sqrt(2))

    def test_normalized_radius_and_floor_are_presentation_only(self):
        """! @brief dB 바닥이 실제 값과 영전계 상태를 덮지 않는다."""
        linear = projection(0.5, 90, 0, "linear_amplitude", -40)
        self.assertAlmostEqual(linear["xyz"][0], 0.5)
        self.assertAlmostEqual(linear["db"], 20 * math.log10(0.5))
        zero = projection(0, 0, 0, "db_amplitude", -40)
        self.assertIsNone(zero["db"])
        self.assertEqual(zero["db_state"], "negative_infinity")
        self.assertTrue(zero["clipped"])
        self.assertEqual(zero["color"], -40)
        tiny = projection(1e-4, 90, 0, "db_amplitude", -40)
        self.assertEqual(tiny["db"], -80)
        self.assertEqual(tiny["amplitude"], 1e-4)
        self.assertEqual(tiny["radius"], 0)

    def test_nearly_linear_ellipse_keeps_finite_minor_axis(self):
        """! @brief 직교한 축 1과 1e-20의 유한 축비를 원형 성분 소거로 무한대 처리하지 않는다."""
        for scale in (1.0, 1e-100):
            value = polarization([scale, 0], [0, scale * 1e-20], 35)
            self.assertEqual(value["axial_ratio_state"], "elliptical")
            self.assertAlmostEqual(value["axial_ratio"] / 1e20, 1.0)
            self.assertAlmostEqual(value["axial_ratio_db"], 400.0)
        tilted = polarization([1, 0], [1, 1e-20], 0)
        self.assertEqual(tilted["axial_ratio_state"], "elliptical")
        self.assertAlmostEqual(tilted["axial_ratio"] / 2e20, 1.0)
        huge = polarization([1, 0], [0, 1e-310], 0)
        self.assertEqual(huge["axial_ratio_state"], "overflow")
        self.assertIsNone(huge["axial_ratio"])
        self.assertIsNone(huge["axial_ratio_db"])
        underflow = polarization([1e100, 0], [0, 1e-310], 0)
        self.assertEqual(underflow["axial_ratio_state"], "overflow")
        linear = polarization([1e100, 0], [1e-310, 0], 0)
        self.assertEqual(linear["axial_ratio_state"], "infinite_linear")
        epsilon = math.ulp(1.0)
        parallel = polarization([1, 1], [1, 1 + epsilon], 0)
        self.assertEqual(parallel["axial_ratio_state"], "elliptical")
        # @brief 행렬 [[1,1],[1,1+eps]]의 큰 특이값 제곱은 약 4이고 정확한 행렬식은 eps다.
        self.assertAlmostEqual(parallel["axial_ratio"] / (4 / epsilon), 1.0)


class ResultRadiationTests(unittest.TestCase):
    """! @brief 읽기 전용 서비스의 원본 재조립과 미기록/변조 경계를 검사한다."""

    def test_target_observation_uses_exact_recorded_direction_and_component(self):
        """! @brief 동일 선형장에서 RHCP는 -3 dB이고 직교 성분과 미기록 각도를 구분한다."""
        service, params, resolved, _, original = fixture()
        plan = resolved["normalized"]["provenance"]["analysis_plan"]
        frequency = original["recording"]["frequency_hz"][0]
        target = target_input()
        target.update(revision_id=plan["snapshot"]["revision_id"], port_id=plan["case"]["port"]["id"],
                      reference_plane="시험 기준면", reference_impedance=Quantity.from_value(50, "ohm").to_dict(),
                      observation={"frequency": Quantity.from_value(frequency, "Hz").to_dict(), "theta_deg": 0,
                                   "phi_deg": 0, "polarization": "rhcp", "minimum_gain_dbi": -100.0})
        resolved["source_document"] = {"targets": [target]}
        resolved["normalized"]["normalization"] = {"reference_plane": "시험 기준면", "reference_impedance_ohm": 50.0}
        params["input"]["target_id"] = target["id"]
        row = original["frequencies"][0]
        self.assertEqual(row["e_phi"][0][0], [0.0, 0.0])
        with patch("rfad.application.result_radiation.resolve", return_value=resolved):
            observation = radiation(service, params)["target_observation"]
            expected = row["metrics"]["realized_gain_dbi"] + 10 * math.log10(row["normalized_power"][0][0] / 2)
            self.assertAlmostEqual(observation["gain_dbi"], expected)
            self.assertEqual(observation["status"], "conditional")
            self.assertEqual(observation["source_refs"], target["source_refs"])
            target["observation"]["polarization"] = "phi"
            observation = radiation(service, params)["target_observation"]
            self.assertEqual((observation["value_state"], observation["status"]), ("negative_infinity", "fail"))
            target["observation"]["phi_deg"] = 1
            self.assertEqual(radiation(service, params)["target_observation"]["value_state"], "unrecorded")
            target["observation"]["phi_deg"] = 0
            target["reference_plane"] = "다른 기준면"
            self.assertEqual(radiation(service, params)["target_observation"]["status"], "not_evaluated")

    def test_pages_preserve_complex_original_and_unknown_conditions(self):
        """! @brief 5도 원문을 전송 상한 안에서 재조립하며 제조 조건을 채우지 않는다."""
        service, params, resolved, blobs, original = fixture(step=5)
        before = deepcopy((resolved, blobs))
        offset, fields, total = 0, [], 0
        with patch("rfad.application.result_radiation.resolve", return_value=resolved) as resolver:
            while offset is not None:
                params["input"]["theta_offset"] = offset
                page = radiation(service, params)
                self.assertLessEqual(len(canonical_bytes(page)), 128 * 1024)
                self.assertGreater(page["returned_count"], 0)
                self.assertIsNone(page["states"]["manufacturing"])
                self.assertIsNone(page["absolute_power_w"])
                self.assertFalse(page["physics_validated"])
                fields.extend(page["e_theta"])
                total += page["returned_count"]
                offset = page["next_offset"]
            resolver.assert_called_with(service, params["context"], params["input"]["source"], params["input"]["pin"])
        self.assertEqual(fields, original["frequencies"][0]["e_theta"])
        self.assertEqual(total, 37)
        self.assertEqual((resolved, blobs), before)

    def test_observable_uses_total_peak_and_explicit_co_basis(self):
        """! @brief 없는 phi 전계는 영전계로 표시하며 co 역할을 자동 추측하지 않는다."""
        service, params, resolved, _, _ = fixture()
        params["input"].update(observable="e_phi", display_scale="db_amplitude")
        with patch("rfad.application.result_radiation.resolve", return_value=resolved):
            page = radiation(service, params)
            self.assertIsNone(page["co_component"])
            self.assertEqual(page["projection"][0][0]["amplitude"], 0)
            self.assertEqual(page["projection"][0][0]["db_state"], "negative_infinity")
            params["input"]["polarization_basis"] = "phi_co"
            self.assertEqual(radiation(service, params)["co_component"], "e_phi")

    def test_missing_and_tampered_original_never_fall_back(self):
        """! @brief 다른 원본이나 누락을 예시 패턴으로 대체하지 않는다."""
        for mode in ("missing", "summary", "snapshot", "duplicate"):
            service, params, resolved, _, _ = fixture()
            if mode == "missing":
                resolved["solver_record"]["files"] = []
            elif mode == "summary":
                resolved["normalized"]["radiation_summary"]["metrics"][0]["frequency_hz"] += 1
            elif mode == "snapshot":
                resolved["source_snapshot"] = {}
            else:
                resolved["solver_record"]["files"] *= 2
            with self.subTest(mode=mode), patch("rfad.application.result_radiation.resolve", return_value=resolved), self.assertRaises(ProjectError):
                radiation(service, params)

    def test_directional_gain_color_has_its_own_unit_and_radius(self):
        """! @brief 방향별 이득은 실제 효율로 계산하고 무차원 반경과 dBi 색을 구분한다."""
        service, params, resolved, blobs, original = fixture()
        # @brief 한 방향의 전계 진폭을 절반으로 줄여 전력 1/4와 -6.0206 dB를 독립 확인한다.
        row = original["frequencies"][0]
        row["e_theta"][0][0] = [0.5e-12, 0]
        row["normalized_power"][0][0] = 0.25
        row["directivity"][0][0] = 1.64 * 0.25
        blobs["radiation"] = canonical_bytes(original)
        params["input"].update(observable="gain", display_scale="linear_amplitude")
        with patch("rfad.application.result_radiation.resolve", return_value=resolved):
            value = radiation(service, params)
            point = value["projection"][0][0]
            self.assertAlmostEqual(point["radius"], 0.5)
            self.assertAlmostEqual(point["quantity_linear"], 0.25 * 1.64 * 0.8)
            self.assertEqual(point["color"], point["quantity_linear"])
            params["input"]["display_scale"] = "db_amplitude"
            value = radiation(service, params)
            point = value["projection"][0][0]
            self.assertEqual(value["color_unit"], "dBi")
            self.assertAlmostEqual(point["quantity_db"], 10 * math.log10(0.25 * 1.64 * 0.8))
            self.assertAlmostEqual(point["db"], 20 * math.log10(0.5))
            self.assertAlmostEqual(value["color_range"][1], row["metrics"]["gain_dbi"])

    def test_options_reject_unknown_frequency_bool_and_invalid_floor(self):
        """! @brief 존재하지 않는 주파수와 비유한 입력을 보간하여 수용하지 않는다."""
        service, params, resolved, _, _ = fixture()
        for extra in ({"frequency_index": 1}, {"frequency_index": True}, {"theta_offset": 37},
                      {"theta_limit": 6}, {"observable": "gain_guessed"}, {"floor_db": float("nan")},
                      {"floor_db": True}, {"floor_db": -121}, {"polarization_basis": "automatic"}):
            with self.subTest(extra=extra), patch("rfad.application.result_radiation.resolve", return_value=resolved), self.assertRaises(ProjectError):
                radiation(service, {**params, "input": {**params["input"], **extra}})

    def test_power_ratios_and_units_have_separate_denominators(self):
        """! @brief 0.4/0.5 방사 효율과 0.4/1 총 효율 및 절대 전력 미정을 구분한다."""
        service, params, resolved, blobs, _ = fixture(power=True)
        before = deepcopy((resolved, blobs))
        with patch("rfad.application.result_metrics.resolve", return_value=resolved):
            result = metrics(service, params)
        row = result["rows"][0]
        self.assertAlmostEqual(row["radiation_efficiency"], 0.8)
        self.assertAlmostEqual(row["total_efficiency"], 0.4)
        self.assertEqual(row["power_unit"], "W*s^2")
        self.assertIsNone(row["absolute_power_w"])
        self.assertEqual(row["numerical_balance_status"], "within_initial_numerical_budget")
        self.assertFalse(result["physics_validated"])
        self.assertEqual((resolved, blobs), before)
        table = {entry["key"]: entry for entry in result["table_rows"]}
        self.assertAlmostEqual(table["radiation_efficiency"]["value"], 80)
        self.assertEqual(table["total_efficiency"]["denominator"], "incident")

    def test_negative_independent_loss_is_not_clamped(self):
        """! @brief 음수 개별 손실과 수치 검토 상태를 그대로 노출한다."""
        service, params, resolved, _, _ = fixture(power=True, negative_loss=True)
        with patch("rfad.application.result_metrics.resolve", return_value=resolved):
            row = metrics(service, params)["rows"][0]
        self.assertLess(row["independent_losses"][0]["value"], 0)
        self.assertEqual(row["numerical_balance_status"], "requires_review")

    def test_efficiency_above_one_remains_reviewable(self):
        """! @brief 전력 비율이 100퍼센트를 넘더라도 표시용 정상 범위로 자르지 않는다."""
        service, params, resolved, blobs, original = fixture()
        original["frequencies"][0]["metrics"] = spectral_power_metrics(1.2e-24, 0.5e-24, 1e-24, 1.64)
        blobs["radiation"] = canonical_bytes(original)
        resolved["normalized"]["radiation_summary"] = summary(original)
        with patch("rfad.application.result_metrics.resolve", return_value=resolved):
            row = metrics(service, params)["rows"][0]
        self.assertAlmostEqual(row["radiation_efficiency"], 2.4)
        self.assertAlmostEqual(row["total_efficiency"], 1.2)
        self.assertEqual(row["power_order_status"], "requires_review")

    def test_derived_data_and_unrecorded_radiation_have_no_efficiency(self):
        """! @brief 반사계수 자료나 방사 미기록 계산에서 효율을 새로 추정하지 않는다."""
        for mode in ("derived", "unrecorded"):
            service, params, resolved, _, _ = fixture()
            if mode == "derived":
                resolved.update(solver_record=None, normalized=None)
            else:
                resolved["solver_record"]["files"] = []
            with self.subTest(mode=mode), patch("rfad.application.result_metrics.resolve", return_value=resolved):
                result = metrics(service, params)
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["status"], "unavailable")
            self.assertTrue(result["warnings"])

    def test_null_or_partial_pin_does_not_reselect_authority(self):
        """! @brief 검토 해시를 생략하여 최신 결과에 자동 재연결하지 않는다."""
        service, params, _, _, _ = fixture()
        for pin in (None, {}, {"identity_hash": "a" * 64}, {"identity_hash": "a" * 64, "dataset_sha256": "b"}):
            for handler in (radiation, metrics):
                with self.subTest(pin=pin, handler=handler.__name__), self.assertRaises(ProjectError):
                    handler(service, {**params, "input": {**params["input"], "pin": pin}})


if __name__ == "__main__":
    unittest.main()
