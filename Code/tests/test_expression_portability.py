"""! @brief 런타임 비교 도구가 실제 계산, 불일치 차단과 원본 보존을 수행하는지 확인한다."""

from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import math
from pathlib import Path
import tempfile
import unittest

from rfad.application.canonical import canonical_bytes, canonical_hash


_PATH = Path(__file__).resolve().parents[1] / "tools/check_expression_portability.py"
_SPEC = importlib.util.spec_from_file_location("expression_portability", _PATH)
portability = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(portability)


class ExpressionPortabilityTests(unittest.TestCase):
    """! @brief OS별 숫자 상수를 고정하지 않고 기준 생성과 대조 계약을 검사한다."""

    def test_runtime_comparison_is_exact_and_input_is_unchanged(self):
        """! @brief 실제 생성 결과는 동일 런타임에서 재현되고 입력 자료는 바뀌지 않는다."""
        baseline = portability.generate_baseline()
        original = canonical_bytes(baseline)
        baseline["origin_runtime"]["system"] = "Independent reference runtime"
        report = portability.compare_baseline(baseline)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["expected_hash"], report["actual_hash"])
        self.assertGreater(report["case_count"], 40)
        baseline["origin_runtime"] = portability.runtime_identity()
        self.assertEqual(canonical_bytes(baseline), original)

    def test_one_ulp_difference_is_rejected_without_rounding(self):
        """! @brief 유효한 기준 자료의 1 ULP 차이도 허용차로 숨기지 않는다."""
        baseline = portability.generate_baseline()
        case = baseline["expected"]["cases"]["sqrt_irrational"]
        changed = math.nextafter(case["quantity"]["value_si"], math.inf)
        case["quantity"]["value_si"] = changed
        case["float_hex"] = changed.hex()
        baseline["body_hash"] = canonical_hash({key: baseline[key] for key in ("inputs", "expected")})
        before = deepcopy(baseline)
        report = portability.compare_baseline(baseline)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("sqrt_irrational" in path for path in report["mismatch_paths"]))
        self.assertEqual(baseline, before)

    def test_graph_and_unknown_material_are_preserved(self):
        """! @brief UUID 그래프의 추정 상태와 미정 재료 값이 비교 대상에 포함된다."""
        baseline = portability.generate_baseline()
        report = portability.compare_baseline(baseline)
        parameters = report["actual"]["parameters"]
        self.assertEqual(len(parameters), 4)
        self.assertTrue(all(item["quantity"]["status"] == "estimated" for item in parameters.values()))
        self.assertEqual(report["actual"]["fixture"]["validation"], {"status": "valid"})
        materials = report["actual"]["fixture"]["materials"]
        self.assertTrue(materials)
        for material in materials:
            self.assertIsNone(material["epsilon_r"]["value_si"])
            self.assertEqual(material["epsilon_r"]["status"], "missing")
        self.assertEqual(report["actual"]["cases"]["missing_input"]["error_code"], "E_SCHEMA")

    def test_version_source_and_content_changes_are_rejected(self):
        """! @brief 다른 코드와 변조 자료를 런타임 차이로 오인하지 않는다."""
        for mutation in (
            lambda b: b.update(engine_version="future"),
            lambda b: b["sources"].update({"domain/units.py": "0" * 64}),
            lambda b: b["inputs"]["cases"][0].update(expression="0 mm"),
            lambda b: b.pop("origin_runtime"),
        ):
            baseline = portability.generate_baseline()
            mutation(baseline)
            with self.assertRaises(ValueError):
                portability.compare_baseline(baseline)

    def test_cli_never_overwrites_baseline_and_writes_comparison_report(self):
        """! @brief 기준 재생성과 결과 경로 충돌은 파일 변경 없이 실패한다."""
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary) / "한글 기준.json"
            report = Path(temporary) / "검사 결과.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(portability.main(["--generate", str(baseline)]), 0)
                original = baseline.read_bytes()
                self.assertEqual(portability.main(["--generate", str(baseline)]), 2)
                self.assertEqual(portability.main(["--compare", str(baseline), "--output", str(baseline)]), 2)
                self.assertEqual(portability.main(["--compare", str(baseline), "--output", str(report)]), 0)
            self.assertEqual(baseline.read_bytes(), original)
            self.assertTrue(report.is_file())

    def test_failed_cli_comparison_returns_nonzero(self):
        """! @brief 손상된 JSON을 성공 보고서로 처리하지 않는다."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            path.write_text("{", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(portability.main(["--compare", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
