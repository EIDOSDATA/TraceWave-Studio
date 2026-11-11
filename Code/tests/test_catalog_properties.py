"""! @brief 공개값의 범위와 조건이 임의의 해석 입력으로 바뀌지 않음을 검사한다."""

from copy import deepcopy
import json
import unittest

from rfad.catalog.models import CatalogError
from rfad.catalog.properties import MAX_PROPERTY_BYTES, property_views


class CatalogPropertyTests(unittest.TestCase):
    """! @brief 원문, 물성별 조건과 작은 표시 DTO의 의미를 확인한다."""

    def test_independent_frequency_and_method_preserve_original(self):
        record = {"record_id": "PCB1", "source_id": "S1", "dk": 4.3, "df": 0.02,
                  "frequency_ghz": 10, "df_frequency_ghz": 1, "method": "method Dk",
                  "df_method": "method Df", "value_type": "process Dk"}
        original = deepcopy(record)
        result = property_views(record)
        self.assertEqual(result["properties"]["dk"]["frequency"]["point_hz"], 10_000_000_000)
        self.assertEqual(result["properties"]["df"]["frequency"]["point_hz"], 1_000_000_000)
        self.assertEqual(result["properties"]["df"]["method"]["value"], "method Df")
        self.assertEqual(result["record_context"]["value_type"], "process Dk")
        self.assertEqual(record, original)

    def test_shared_condition_is_not_copied_into_df(self):
        result = property_views({"dk": 4, "df": 0.01, "frequency_ghz": 10, "method": "common note"})
        self.assertIsNone(result["properties"]["df"]["frequency"]["point_hz"])
        self.assertIsNone(result["properties"]["df"]["method"]["value"])
        self.assertEqual(result["record_context"]["frequency"]["point_hz"], 10_000_000_000)
        self.assertEqual(result["record_context"]["method"], "common note")

    def test_range_qualifier_and_missing_are_preserved(self):
        result = property_views({"dk_min": 3, "dk_max": 4, "df": 0.02, "df_limit_operator": "<",
                                 "frequency_min_ghz": 1, "frequency_max_ghz": 10})
        dk, df = (result["properties"][name] for name in ("dk", "df"))
        self.assertEqual(dk["value"]["representation"], "range")
        self.assertIsNone(dk["value"]["scalar"])
        self.assertEqual(df["value"]["representation"], "qualified")
        self.assertEqual(df["value"]["limit_operator"], "<")
        self.assertIsNone(df["frequency"]["minimum_hz"])
        missing = property_views({})["properties"]["df"]["value"]
        self.assertEqual(missing["representation"], "missing")
        self.assertIsNone(missing["scalar"])

    def test_large_unicode_fields_are_bounded_and_marked(self):
        record = {name: "자료" * 9000 for name in ("method", "df_method", "axis", "conditioning", "construction")}
        result = property_views(record)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode("utf-8")), MAX_PROPERTY_BYTES)
        self.assertEqual(set(result["truncated_fields"]), set(record))
        self.assertEqual(len(record["method"]), 18000)

    def test_nonfinite_and_boolean_are_not_material_numbers(self):
        for value in (True, float("inf"), float("nan"), "4.3", 10 ** 400):
            with self.subTest(value=value), self.assertRaises(CatalogError):
                property_views({"dk": value})
        with self.assertRaises(CatalogError):
            property_views({"frequency_ghz": 10 ** 305})


if __name__ == "__main__":
    unittest.main()
