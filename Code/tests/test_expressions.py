"""! @brief 표현식의 실제 차원/정의역/입력 격리 경계를 검증한다."""

import math
import unittest

from rfad.domain.errors import ProjectError
from rfad.domain.expressions import RESERVED_NAMES, dependencies, evaluate_expression
from rfad.domain.units import Quantity, QuantityStatus


class ExpressionTests(unittest.TestCase):
    """! @brief 명시적 단위와 변수 표현식을 독립 기대값에 대조한다."""

    def evaluate(self, expression, variables=None, dimension="dimensionless", unit="1"):
        """! @brief 시험의 기대 차원과 표시 단위를 명시한다."""
        return evaluate_expression(expression, variables or {}, expected_dimension=dimension, display_unit=unit)

    def assert_error(self, expression, code, variables=None, dimension="dimensionless", unit="1"):
        """! @brief 실패 분류와 원문 위치를 검사한다."""
        with self.assertRaises(ProjectError) as caught:
            self.evaluate(expression, variables, dimension, unit)
        self.assertEqual(caught.exception.code, code)
        self.assertIn("span", caught.exception.details)

    def test_board_dimension_expression_preserves_si(self):
        """! @brief 40 mm 변수의 반과 1 mm를 더하면 21 mm다."""
        width = Quantity.from_value(40, "mm", source_refs=("설계 입력",))
        result = self.evaluate("w / 2 + 1 mm", {"w": width}, "length", "mm")
        self.assertAlmostEqual(result.value_si, 0.021)
        self.assertAlmostEqual(result.as_unit("mm"), 21.0)
        self.assertEqual(result.source_refs, ("설계 입력",))
        self.assertEqual(width.value_si, 0.04)

    def test_speed_of_light_and_frequency_form_wavelength(self):
        """! @brief c0와 GHz의 역차원으로 자유공간 파장을 계산한다."""
        result = self.evaluate("c0 / 2.45GHz", dimension="length", unit="mm")
        self.assertAlmostEqual(result.value_si, 299792458 / 2450000000)
        self.assertAlmostEqual(self.evaluate("1 / (2 ns)", dimension="frequency", unit="MHz").as_unit("MHz"), 500.0)

    def test_product_dimensions_and_sqrt_are_checked(self):
        """! @brief 중간 면적 및 저항/전도도의 차원을 검사한다."""
        self.assertAlmostEqual(self.evaluate("sqrt((3 mm)**2 + (4 mm)**2)", dimension="length", unit="mm").as_unit("mm"), 5.0)
        self.assertAlmostEqual(self.evaluate("1 / (2 ohm * 0.5 m)", dimension="conductivity", unit="S/m").value_si, 1.0)
        self.assertAlmostEqual(self.evaluate("5 S/m / (1 S/m)").value_si, 5.0)

    def test_fractional_powers_keep_intermediate_dimensions(self):
        """! @brief 작은 유리수 지수는 중간 차원에 정확히 반영한다."""
        self.assertAlmostEqual(self.evaluate("((2 m)**3)**(1/3)", dimension="length", unit="m").value_si, 2.0)
        self.assert_error("(2 m)**pi", "E_UNIT", dimension="length", unit="m")

    def test_power_precedence_and_right_association(self):
        """! @brief 단항 부호와 오른쪽 결합 거듭제곱 순서를 고정한다."""
        expected = {"-2**2": -4.0, "(-2)**2": 4.0, "2**3**2": 512.0, "2**-2": 0.25, "1+2*3": 7.0}
        for expression, value in expected.items():
            with self.subTest(expression=expression):
                self.assertEqual(self.evaluate(expression).value_si, value)

    def test_trigonometric_angles_and_dimensionless_radians(self):
        """! @brief 각도 단위와 명시적 무차원 radian을 허용한다."""
        self.assertAlmostEqual(self.evaluate("sin(90 deg)").value_si, 1.0)
        self.assertAlmostEqual(self.evaluate("cos(pi)").value_si, -1.0)
        self.assertAlmostEqual(self.evaluate("tan(45 deg)").value_si, 1.0)
        self.assertAlmostEqual(self.evaluate("atan2(1 mm, 1 mm)", dimension="angle", unit="deg").as_unit("deg"), 45.0)
        self.assert_error("sin(1 mm)", "E_UNIT")
        self.assert_error("atan2(1 mm, 1 s)", "E_UNIT", dimension="angle", unit="rad")

    def test_abs_min_max_and_clamp_preserve_dimensions(self):
        """! @brief 비교/제한 함수는 동일 차원끼리만 처리한다."""
        expression = "clamp(max(abs(-5 mm), 2 mm), 1 mm, 4 mm)"
        self.assertAlmostEqual(self.evaluate(expression, dimension="length", unit="mm").as_unit("mm"), 4.0)
        self.assertEqual(self.evaluate("min(3, 2, 1)").value_si, 1.0)
        self.assert_error("min(1 mm, 1 s)", "E_UNIT")
        self.assert_error("clamp(1, 3, 2)", "E_EXPR_DOMAIN")

    def test_dependencies_exclude_all_reserved_symbols(self):
        """! @brief 한국어 변수와 함수/상수/단위를 구별한다."""
        text = "max(폭/2, gap + 1 mm) + c0 / 주파수 * sin(pi/2)"
        self.assertEqual(dependencies(text), {"폭", "gap", "주파수"})
        self.assertTrue({"sin", "pi", "c0", "GHz", "mm", "True"} <= RESERVED_NAMES)
        self.assertEqual(dependencies("40mm + 2 mm"), set())

    def test_only_consumed_input_provenance_and_estimation_are_propagated(self):
        """! @brief 사용하지 않은 추정 변수의 상태와 출처를 붙이지 않는다."""
        variables = {"a": Quantity.from_value(1, "mm", source_refs=("A",)), "b": Quantity.from_value(2, "mm", status=QuantityStatus.ESTIMATED, source_refs=("A", "B"))}
        result = self.evaluate("a+b", variables, "length", "mm")
        self.assertEqual(result.status, QuantityStatus.ESTIMATED)
        self.assertEqual(result.source_refs, ("A", "B"))
        self.assertEqual(self.evaluate("a", variables, "length", "mm").status, QuantityStatus.USER_ENTERED)

    def test_missing_unknown_and_invalid_variables_are_rejected(self):
        """! @brief 미정값을 0으로 바꾸거나 외부 객체를 수치로 추정하지 않는다."""
        self.assert_error("width", "E_SCHEMA", {"width": Quantity.missing("length", "mm")}, "length", "mm")
        self.assert_error("width", "E_SCHEMA")
        self.assert_error("width", "E_SCHEMA", {"width": 40})
        self.assert_error("1", "E_SCHEMA", {"pi": Quantity.from_value(1, "1")})

    def test_wrong_result_dimension_and_display_unit_are_rejected(self):
        """! @brief 최종 차원과 표시 단위가 실제 계산과 일치해야 한다."""
        self.assert_error("1 mm + 1 s", "E_UNIT", dimension="length", unit="mm")
        self.assert_error("1 mm", "E_UNIT", dimension="frequency", unit="Hz")
        self.assert_error("1 mm", "E_UNIT", dimension="length", unit="GHz")
        self.assert_error("1 rad + 1", "E_UNIT", dimension="angle", unit="rad")
        self.assert_error("1", "E_UNIT", dimension="unknown")

    def test_undefined_real_operations_are_reported(self):
        """! @brief 0 나누기, 음수 제곱근, 극점과 불명확한 원점을 거부한다."""
        for expression in ("1/0", "sqrt(-1)", "(-1)**0.5", "0**0", "0**-1", "atan2(0,0)", "tan(pi/2)"):
            with self.subTest(expression=expression):
                self.assert_error(expression, "E_EXPR_DOMAIN")

    def test_nonfinite_overflow_and_underflow_are_not_saved(self):
        """! @brief 계산 중 비영 값이 무한대나 0으로 소실되는 것을 거부한다."""
        for expression in ("1e999", "1e-999", "1e308*10", "1e-300*1e-300", "1e-300/1e300", "(1e-300)**2"):
            with self.subTest(expression=expression):
                self.assert_error(expression, "E_EXPR_DOMAIN")
        self.assertEqual(self.evaluate("-0.0").value_si, 0.0)
        self.assertEqual(math.copysign(1.0, self.evaluate("-0.0").value_si), 1.0)
        self.assertEqual(self.evaluate("1-1").value_si, 0.0)

    def test_python_execution_and_other_grammar_are_rejected(self):
        """! @brief 속성, 임의 호출, 대입, 컨테이너와 주석 문법을 허용하지 않는다."""
        for expression in ("__import__('os')", "open(1)", "w.real", "w[0]", "a=1", "[1,2]", "{'x':1}", "1;2", "1 # comment", "lambda:1", "True", "1 if a else 2", "1//2", "1%2", "2(3)", "2 width"):
            with self.subTest(expression=expression):
                self.assert_error(expression, "E_SCHEMA")

    def test_function_arity_and_syntax_are_validated_before_evaluation(self):
        """! @brief 누락/초과 인수와 불완전한 식은 dependency 분석에서도 거부한다."""
        for expression in ("sqrt()", "sin(1,2)", "atan2(1)", "clamp(1,2)", "min()", "max(1,)", "(1+2", "1+", "sin", ""):
            with self.subTest(expression=expression), self.assertRaises(ProjectError) as caught:
                dependencies(expression)
            self.assertEqual(caught.exception.code, "E_SCHEMA")

    def test_input_depth_tokens_and_power_budgets_are_bounded(self):
        """! @brief 원문/토큰/트리/지수 크기로 평가 자원을 제한한다."""
        for expression in (" " * 4096 + "1", "(" * 65 + "1" + ")" * 65, "+".join(["1"] * 300), "max(" + ",".join(["1"] * 33) + ")", "2**1025"):
            with self.subTest(size=len(expression)):
                self.assert_error(expression, "E_RESOURCE")

    def test_unknown_units_are_not_implicitly_accepted(self):
        """! @brief 단위의 대소문자와 알려진 단위만 숫자 접미사로 허용한다."""
        for expression in ("1 MM", "1 db", "1 dB", "1 unknown", "2 1"):
            with self.subTest(expression=expression):
                self.assert_error(expression, "E_SCHEMA")
        self.assertAlmostEqual(self.evaluate("10 mW", dimension="power", unit="W").value_si, 0.01)


if __name__ == "__main__":
    unittest.main()
