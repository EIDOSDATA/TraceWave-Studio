"""! @brief 측정 폼의 변경 수치만 해석하고 단위 표시와 원문/미정을 분리하는지 검사한다."""

from copy import deepcopy
import math
import unittest

import test_measurement as fixture
from rfad.application import measurement_forms as forms
from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError


def quantity(path, value, display_unit, raw=None):
    """! @brief 공개 수량 조회의 exact 입력을 만든다."""
    return forms.quantity({"path": path, "value": value, "input": raw, "display_unit": display_unit})


class MeasurementFormsTests(unittest.TestCase):
    """! @brief GUI가 물리량을 계산하지 않아도 정확한 canonical 입력을 유지한다."""

    def test_frequency_endpoints_unit_only_keep_original_and_null(self):
        """! @brief GHz/MHz 표시 전환은 Hz 원문과 null을 바꾸지 않는다."""
        for path in ("calibration.frequency_range_hz.start", "calibration.frequency_range_hz.stop",
                     "uncertainty.frequency_range_hz.start", "uncertainty.frequency_range_hz.stop"):
            with self.subTest(path=path):
                result = quantity(path, 1_000_000_001.0, "GHz")
                self.assertEqual(result["value"], 1_000_000_001.0)
                self.assertEqual(result["text"], "1.000000001")
                self.assertTrue(result["original_preserved"])
                self.assertEqual(quantity(path, result["value"], "MHz")["text"], "1000.000001")
                self.assertIsNone(quantity(path, None, "GHz")["value"])
                self.assertEqual(quantity(path, None, "GHz")["text"], "")
        self.assertEqual(quantity("calibration.frequency_range_hz.start", None, "MHz", {"text": "0", "unit": "Hz"})["value"], 0.0)

    def test_power_milliwatt_input_is_watt_and_original_request_survives(self):
        """! @brief mW 수치 입력만 W로 저장하고 dBm 표시가 새 전력 사실을 만들지 않는다."""
        record = fixture.record()
        changes = {"values": {}, "quantities": {"acquisition.stimulus_power": {
            "text": "2.5", "unit": "mW", "evidence": "planned", "source_refs": ["original:power"]}}}
        before = canonical_bytes([record, changes])
        result = forms.apply_changes(record, changes)
        leaf = result["acquisition"]["stimulus_power"]
        self.assertEqual(leaf, {"value": {"number": 0.0025, "unit": "W"}, "evidence": "planned", "source_refs": ["original:power"]})
        shown = quantity("acquisition.stimulus_power", leaf["value"], "dBm")
        self.assertAlmostEqual(float(shown["text"]), 10 * math.log10(2.5), places=12)
        self.assertEqual(shown["value"], leaf["value"])
        self.assertEqual(canonical_bytes([record, changes]), before)

    def test_temperature_humidity_and_log_power_display_remain_canonical(self):
        """! @brief offset/로그 단위 표시에서도 원래 단위와 값은 보존한다."""
        for path, value, unit, expected in (
                ("environment.temperature", {"number": 25.0, "unit": "degC"}, "K", 298.15),
                ("environment.humidity", {"number": 0.4, "unit": "1"}, "%", 40.0),
                ("acquisition.stimulus_power", {"number": 0.0, "unit": "dBm"}, "W", 0.001),
                ("uncertainty.value", {"number": 2.0, "unit": "%"}, "1", 0.02)):
            with self.subTest(path=path):
                output = quantity(path, value, unit)
                self.assertAlmostEqual(float(output["text"]), expected)
                self.assertEqual(output["value"], value)
        small = quantity("acquisition.stimulus_power", {"number": -3220.0, "unit": "dBm"}, "mW")
        self.assertGreater(float(small["text"]), 0.0)

    def test_blank_is_missing_and_zero_is_explicit(self):
        """! @brief 공란을 0으로 바꾸지 않고 허용하지 않는 IFBW 영점은 거절한다."""
        self.assertIsNone(quantity("acquisition.if_bandwidth_hz", 1000.0, "Hz", {"text": " ", "unit": "kHz"})["value"])
        self.assertEqual(quantity("acquisition.stimulus_power", None, "W", {"text": "0", "unit": "mW"})["value"], {"number": 0.0, "unit": "W"})
        with self.assertRaises(ProjectError):
            quantity("acquisition.if_bandwidth_hz", None, "Hz", {"text": "0", "unit": "Hz"})

    def test_invalid_numeric_display_and_conversion_never_emit_nonfinite_or_fake_zero(self):
        """! @brief 부호/정의역/부적절 단위/overflow/underflow는 구조화 오류로 남긴다."""
        cases = [("acquisition.averages", True, "1"), ("acquisition.averages", 2.5, "1"),
                 ("environment.temperature", {"number": -1, "unit": "K"}, "degC"),
                 ("environment.humidity", {"number": 101, "unit": "%"}, "1"),
                 ("acquisition.stimulus_power", {"number": -1, "unit": "W"}, "dBm"),
                 ("acquisition.stimulus_power", {"number": 0, "unit": "W"}, "dBm"),
                 ("acquisition.stimulus_power", {"number": 100000, "unit": "dBm"}, "W"),
                 ("calibration.frequency_range_hz.start", math.ulp(0.0), "GHz"),
                 ("uncertainty.value", {"number": 1, "unit": "dB"}, "1"),
                 ("acquisition.if_bandwidth_hz", float("nan"), "MHz")]
        for path, value, unit in cases:
            with self.subTest(path=path, value=value), self.assertRaises(ProjectError):
                quantity(path, value, unit)
        for raw in ({"text": "1e-400", "unit": "W"}, {"text": "NaN", "unit": "W"},
                    {"text": "-1", "unit": "mW"}, {"text": "4.9406564584124654e-324", "unit": "mW"}):
            with self.subTest(raw=raw), self.assertRaises(ProjectError):
                quantity("acquisition.stimulus_power", None, "W", raw)

    def test_range_changed_endpoints_and_missing_endpoint_rejection(self):
        """! @brief 범위 양 끝을 각기 해석하고 미정인 한 끝을 임의 완성하지 않는다."""
        original = fixture.record()
        changes = {"values": {}, "quantities": {"calibration.frequency_range_hz": {
            "start": {"text": "2.4", "unit": "GHz"}, "stop": {"text": "2483.5", "unit": "MHz"},
            "evidence": "reported", "source_refs": ["cal:band"]}}}
        result = forms.apply_changes(original, changes)
        self.assertEqual(result["calibration"]["frequency_range_hz"]["value"], [2.4e9, 2.4835e9])
        shown = next(row for row in forms.form(result, "2026-11-17T00:00:00Z")["fields"] if row["path"] == "calibration.frequency_range_hz")
        self.assertEqual(shown["range_display"]["start"]["text"], "2.4")
        self.assertEqual(shown["range_display"]["start"]["unit"], "GHz")
        changes["quantities"]["calibration.frequency_range_hz"]["stop"]["text"] = ""
        with self.assertRaises(ProjectError):
            forms.apply_changes(original, changes)

    def test_uncertainty_only_changed_numbers_normalize_and_unchanged_rows_survive(self):
        """! @brief 숫자만 바뀐 불확도 표에서 원래 null/정밀 실수/상관/출처는 그대로 둔다."""
        original = fixture.record()
        row = fixture.uncertainty()
        row["coverage_probability"] = 0.9500000000000001
        original["uncertainty"] = [deepcopy(row)]
        changed = deepcopy(row)
        changed["value"] = {"text": "0.35", "unit": "dB"}
        changed["coverage_factor"] = {"text": "2.5", "unit": "1"}
        changed["scope"]["frequency_range_hz"] = {"start": {"text": "1", "unit": "GHz"}, "stop": 3e9}
        result = forms.apply_changes(original, {"values": {}, "quantities": {"uncertainty": [changed]}})
        self.assertEqual(result["uncertainty"][0]["value"], {"number": 0.35, "unit": "dB"})
        self.assertEqual(result["uncertainty"][0]["coverage_factor"], 2.5)
        self.assertEqual(result["uncertainty"][0]["scope"]["frequency_range_hz"], [1e9, 3e9])
        for key in row:
            if key not in ("value", "coverage_factor", "scope"):
                self.assertEqual(result["uncertainty"][0][key], row[key])
        unchanged = forms.apply_changes(original, {"values": {}, "quantities": {"uncertainty": [row]}})
        self.assertEqual(canonical_bytes(unchanged), canonical_bytes(original))
        self.assertEqual(original["uncertainty"], [row])

    def test_unknown_source_extra_and_absent_section_survive_other_change(self):
        """! @brief 알려진 한 필드 수정으로 사용자 extra와 기존 미정을 지우지 않는다."""
        value = fixture.record()
        value["environment"] = None
        value["extra"] = {"legacy": {"unset": None, "source": ["original", "original"]}}
        value["source_refs"] = ["same", "same"]
        output = forms.apply_changes(value, {"values": {"specimen.identifier": fixture.leaf("시료 A")}, "quantities": {}})
        for key in ("environment", "extra", "source_refs", "data_anchor"):
            self.assertEqual(output[key], value[key])
        for changes in ({"values": {"id": fixture.identity(99)}, "quantities": {}},
                        {"values": {"specimen.identifier": None}, "quantities": {"specimen.identifier": None}}):
            with self.assertRaises(ProjectError):
                forms.apply_changes(value, changes)

    def test_alignment_input_units_order_and_float_grid_resolution(self):
        """! @brief GUI 범위를 SI로 한 번만 만들고 표현 불가능한 중복 격자는 거절한다."""
        q = lambda text, unit: {"text": text, "unit": unit, "source_refs": []}
        spec = {"schema": "rfad.measurement-alignment-input/0.1", "operations": [
            {"kind": "linear_ri", "frequencies": {"mode": "range", "start": q("1", "GHz"), "stop": q("3", "GHz"), "count": 3}, "max_gap": q("2", "GHz")},
            {"kind": "renormalize", "references": [q("50", "ohm"), q("0.075", "kohm")]}],
            "reason": "명시 보간 후 정규화", "source_refs": []}
        before = canonical_bytes(spec)
        normalized = forms.alignment_input(spec, fixture.network())
        self.assertEqual(normalized["operations"][0]["frequency_hz"], [1e9, 2e9, 3e9])
        self.assertEqual(normalized["operations"][1]["z0_ohm"], [[[50.0, 0.0], [75.0, 0.0]]] * 3)
        self.assertEqual(canonical_bytes(spec), before)
        spec["operations"][0]["frequencies"].update(start=q("1000000000", "Hz"), stop=q("1000000000.0000001", "Hz"), count=3)
        with self.assertRaises(ProjectError):
            forms.alignment_input(spec, fixture.network())
