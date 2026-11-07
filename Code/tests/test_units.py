"""! @brief 단위 변환과 누락 상태의 초기 계약을 검증한다."""

from dataclasses import FrozenInstanceError
import json
import math
import sys
import unittest

from rfad.domain import Dimension, Quantity, QuantityError, QuantityStatus


class QuantityTests(unittest.TestCase):
    """! @brief SI 보존, 상태 구분, 오류 경계와 불변성을 검증한다."""

    def test_board_dimensions_are_converted_once(self) -> None:
        """! @brief 보드 치수를 표시 단위와 무관한 SI 길이로 보존한다."""
        width = Quantity.from_value(40, "mm")
        self.assertEqual(width.value_si, 0.04)
        self.assertEqual(width.as_unit("m"), 0.04)
        self.assertEqual(width.as_unit("um"), 40000.0)
        self.assertEqual(width.as_unit("mm"), 40.0)
        self.assertEqual(width.value_si, 0.04)
        self.assertEqual(width.display_unit, "mm")

    def test_frequency_units_have_the_same_physical_value(self) -> None:
        """! @brief 주파수 단위별 입력을 동일한 Hz 값으로 변환한다."""
        for value, unit in ((2.45, "GHz"), (2450, "MHz"), (2450000, "kHz"), (2450000000, "Hz")):
            with self.subTest(unit=unit):
                quantity = Quantity.from_value(value, unit)
                self.assertEqual(quantity.dimension, Dimension.FREQUENCY)
                self.assertEqual(quantity.value_si, 2450000000.0)
                self.assertEqual(quantity.as_unit("MHz"), 2450.0)

    def test_time_and_angle_conversions(self) -> None:
        """! @brief 시간 배율과 음의 각도 변환을 확인한다."""
        for value, unit in ((1, "s"), (1000, "ms"), (1000000, "us"), (1000000000, "ns")):
            with self.subTest(unit=unit):
                self.assertEqual(Quantity.from_value(value, unit).value_si, 1.0)
        angle = Quantity.from_value(-180, "deg")
        self.assertEqual(angle.value_si, -math.pi)
        self.assertAlmostEqual(angle.as_unit("deg"), -180.0)

    def test_explicit_scalar_units(self) -> None:
        """! @brief 전력과 저항, 전도도, 무차원 입력의 차원을 구분한다."""
        cases = (
            (1000, "mW", Dimension.POWER, 1.0),
            (2, "W", Dimension.POWER, 2.0),
            (50, "ohm", Dimension.IMPEDANCE, 50.0),
            (58000000, "S/m", Dimension.CONDUCTIVITY, 58000000.0),
            (4.1, "1", Dimension.DIMENSIONLESS, 4.1),
            (35, "um", Dimension.LENGTH, 35.0e-6),
        )
        for value, unit, dimension, expected in cases:
            with self.subTest(unit=unit):
                quantity = Quantity.from_value(value, unit)
                self.assertEqual(quantity.dimension, dimension)
                self.assertAlmostEqual(quantity.value_si, expected)

    def test_missing_material_value_remains_null(self) -> None:
        """! @brief 미정 물성을 임의 상수나 0으로 채우지 않는다."""
        quantity = Quantity.missing(Dimension.DIMENSIONLESS, "1")
        self.assertIsNone(quantity.value_si)
        self.assertEqual(quantity.status, QuantityStatus.MISSING)
        self.assertEqual(quantity.to_dict()["source_refs"], [])
        self.assertIsNone(json.loads(json.dumps(quantity.to_dict(), allow_nan=False))["value_si"])
        with self.assertRaises(QuantityError):
            quantity.as_unit("1")

    def test_explicit_zero_is_not_missing(self) -> None:
        """! @brief 명시적으로 입력한 0의 입력 상태를 유지한다."""
        quantity = Quantity.from_value(0, "S/m")
        self.assertEqual(quantity.value_si, 0.0)
        self.assertEqual(quantity.status, QuantityStatus.USER_ENTERED)
        self.assertEqual(quantity.as_unit("S/m"), 0.0)

    def test_negative_zero_is_normalized(self) -> None:
        """! @brief SI 저장값과 변환값의 음의 0을 양의 0으로 정규화한다."""
        quantity = Quantity.from_value(-0.0, "mm")
        self.assertEqual(math.copysign(1.0, quantity.value_si), 1.0)
        self.assertEqual(math.copysign(1.0, quantity.as_unit("um")), 1.0)

    def test_dimension_mismatch_is_rejected(self) -> None:
        """! @brief 각도와 무차원 및 길이와 주파수를 묵시 변환하지 않는다."""
        for quantity, unit in ((Quantity.from_value(1, "mm"), "GHz"), (Quantity.from_value(1, "rad"), "1")):
            with self.subTest(unit=unit):
                with self.assertRaises(QuantityError):
                    quantity.as_unit(unit)
        with self.assertRaises(QuantityError):
            Quantity.missing(Dimension.LENGTH, "Hz")
        with self.assertRaises(QuantityError):
            Quantity(1.0, Dimension.LENGTH, "Hz", QuantityStatus.USER_ENTERED)

    def test_unknown_and_logarithmic_units_are_rejected(self) -> None:
        """! @brief 미지원 단위와 dB 입력을 선형 수량으로 추정하지 않는다."""
        for unit in ("dB", "dBm", "MM", "", "FR-4", None, []):
            with self.subTest(unit=unit):
                with self.assertRaises(QuantityError):
                    Quantity.from_value(1, unit)

    def test_non_numeric_and_non_finite_values_are_rejected(self) -> None:
        """! @brief 불리언, 문자열, 누락값 및 비유한 수치를 거부한다."""
        for value in (True, False, "4.4", None, complex(1, 0), math.nan, math.inf, -math.inf, 10 ** 400):
            with self.subTest(value=value):
                with self.assertRaises(QuantityError):
                    Quantity.from_value(value, "m")
                with self.assertRaises(QuantityError):
                    Quantity(value, Dimension.LENGTH, "m", QuantityStatus.USER_ENTERED)

    def test_numeric_states_require_values_and_preserve_provenance(self) -> None:
        """! @brief 입력 경로를 검증 합격으로 바꾸지 않고 출처와 함께 보존한다."""
        for status in (QuantityStatus.USER_ENTERED, QuantityStatus.SOURCE_DEFAULT, QuantityStatus.ESTIMATED):
            with self.subTest(status=status):
                quantity = Quantity.from_value(2.4, "GHz", status=status, source_refs=("source-001",))
                self.assertEqual(quantity.to_dict()["status"], status.value)
                self.assertEqual(quantity.to_dict()["source_refs"], ["source-001"])
                with self.assertRaises(QuantityError):
                    Quantity(None, Dimension.FREQUENCY, "GHz", status)

    def test_absent_states_do_not_accept_values(self) -> None:
        """! @brief missing, not_applicable, unsupported 상태에는 숫자를 넣지 않는다."""
        for status in (QuantityStatus.MISSING, QuantityStatus.NOT_APPLICABLE, QuantityStatus.UNSUPPORTED):
            with self.subTest(status=status):
                quantity = Quantity(None, Dimension.LENGTH, "mm", status)
                self.assertIsNone(quantity.to_dict()["value_si"])
                with self.assertRaises(QuantityError):
                    Quantity.from_value(0.0, "mm", status=status)

    def test_conflicting_state_requires_a_future_candidate_model(self) -> None:
        """! @brief 충돌 후보 보존 계약 없이 conflicting 값을 생성하지 않는다."""
        for value in (None, 4.4):
            with self.subTest(value=value):
                with self.assertRaises(QuantityError):
                    Quantity(value, Dimension.DIMENSIONLESS, "1", QuantityStatus.CONFLICTING)

    def test_unknown_dimension_and_status_are_rejected(self) -> None:
        """! @brief 선언하지 않은 차원과 상태를 입력값으로 수용하지 않는다."""
        with self.assertRaises(QuantityError):
            Quantity(1.0, "arbitrary", "1", QuantityStatus.USER_ENTERED)
        with self.assertRaises(QuantityError):
            Quantity.from_value(1, "m", status="verified")

    def test_source_references_are_immutable_and_validated(self) -> None:
        """! @brief 외부 목록이나 직렬화 결과 수정이 원본 출처를 바꾸지 않는다."""
        source_refs = ["source-001"]
        quantity = Quantity.from_value(1, "m", source_refs=source_refs)
        source_refs.append("source-002")
        serialized = quantity.to_dict()
        serialized["source_refs"].append("source-003")
        self.assertEqual(quantity.source_refs, ("source-001",))
        with self.assertRaises(FrozenInstanceError):
            quantity.value_si = 2.0
        for references in ("source-001", None, ("",), ("  ",), (42,), {"source-001"}):
            with self.subTest(references=references):
                with self.assertRaises(QuantityError):
                    Quantity.from_value(1, "m", source_refs=references)

    def test_conversion_overflow_is_rejected(self) -> None:
        """! @brief 유한 입력이 단위 변환으로 무한대가 되는 경우를 거부한다."""
        with self.assertRaises(QuantityError):
            Quantity.from_value(sys.float_info.max, "GHz")
        with self.assertRaises(QuantityError):
            Quantity.from_value(sys.float_info.max, "s").as_unit("ns")

    def test_conversion_underflow_to_zero_is_rejected(self) -> None:
        """! @brief 작은 비영 값이 단위 변환 중 몰래 0으로 바뀌지 않는다."""
        smallest = math.ulp(0.0)
        self.assertEqual(Quantity.from_value(smallest, "m").value_si, smallest)
        with self.assertRaises(QuantityError):
            Quantity.from_value(smallest, "mm")
        with self.assertRaises(QuantityError):
            Quantity.from_value(smallest, "Hz").as_unit("GHz")


if __name__ == "__main__":
    unittest.main()
