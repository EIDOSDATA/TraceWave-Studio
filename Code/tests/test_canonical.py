"""! @brief canonical 바이트, 해시와 거부 경계의 독립 계약을 검사한다."""

import hashlib
import json
import math
import unittest
from decimal import Decimal

from rfad.application.canonical import (
    CANONICAL_VERSION,
    CanonicalEncodingError,
    canonical_bytes,
    canonical_hash,
)


class CanonicalTests(unittest.TestCase):
    """! @brief 버전 1.0의 출력과 입력 경계를 고정된 기대값으로 검수한다."""

    def test_exact_reference_bytes_and_hash(self):
        """! @brief 별도 .NET SHA256으로 산출한 고정 벡터와 byte를 비교한다."""
        value = {
            "한글": "안테나",
            "values": [None, True, False, 1, 1.0, -0.0, 1e-7, 1e20],
            "ports": [2, 1],
            "name": "IFA",
            "escaped": '"\\\b\f\n\r\t\u0000',
        }
        expected = (
            r'{"escaped":"\"\\\b\f\n\r\t\u0000","name":"IFA","ports":[2,1],'
            r'"values":[null,true,false,1,1.0,0.0,1e-07,1e+20],"한글":"안테나"}'
        ).encode("utf-8")
        self.assertEqual(canonical_bytes(value), expected)
        self.assertEqual(len(expected), 131)
        self.assertEqual(
            canonical_hash(value),
            "5fad15c20e0b742df247758481d3b79223afeccc341a8bbb4e9df5afc019fab1",
        )
        self.assertEqual(CANONICAL_VERSION, "rfad.canonical/1.0")

    def test_hash_is_version_prefixed(self):
        """! @brief raw JSON 해시와 버전 구분 해시를 혼동하지 않는다."""
        payload = b'{"a":1}'
        expected = hashlib.sha256(b"rfad.canonical/1.0\n" + payload).hexdigest()
        self.assertEqual(canonical_hash({"a": 1}), expected)
        self.assertNotEqual(canonical_hash({"a": 1}), hashlib.sha256(payload).hexdigest())

    def test_key_insertion_order_does_not_change_hash(self):
        """! @brief 중첩 object의 삽입 순서는 canonical 결과에 영향을 주지 않는다."""
        first = {"z": {"b": 2, "a": 1}, "a": [3, 2, 1]}
        second = {"a": [3, 2, 1], "z": {"a": 1, "b": 2}}
        self.assertEqual(canonical_bytes(first), b'{"a":[3,2,1],"z":{"a":1,"b":2}}')
        self.assertEqual(canonical_hash(first), canonical_hash(second))

    def test_keys_use_unicode_code_point_order(self):
        """! @brief astral key도 UTF-16 순서가 아닌 Unicode code point로 정렬한다."""
        value = {"\U00010000": 4, "\ue000": 3, "가": 2, "a": 1}
        expected = '{"a":1,"가":2,"\ue000":3,"\U00010000":4}'.encode("utf-8")
        self.assertEqual(canonical_bytes(value), expected)

    def test_meaningful_array_order_is_preserved(self):
        """! @brief port와 layer 등의 의미 있는 배열 순서를 정렬하지 않는다."""
        first = {"ports": ["feed", "ground"]}
        second = {"ports": ["ground", "feed"]}
        self.assertEqual(canonical_bytes(first), b'{"ports":["feed","ground"]}')
        self.assertNotEqual(canonical_hash(first), canonical_hash(second))

    def test_negative_zero_only_is_normalized(self):
        """! @brief 부호 있는 실수 0만 정규화하고 int와 float는 구별한다."""
        self.assertEqual(canonical_bytes(-0.0), b"0.0")
        self.assertEqual(canonical_hash(-0.0), canonical_hash(0.0))
        self.assertEqual(canonical_bytes([0, 0.0, 1, 1.0]), b"[0,0.0,1,1.0]")
        self.assertNotEqual(canonical_hash(0), canonical_hash(0.0))

    def test_adjacent_float64_values_are_not_rounded_together(self):
        """! @brief float64 인접 값과 극단 유한 값을 표시 반올림 없이 보존한다."""
        values = [math.nextafter(1.0, 0.0), 1.0, math.nextafter(1.0, math.inf)]
        self.assertEqual(canonical_bytes(values), b"[0.9999999999999999,1.0,1.0000000000000002]")
        self.assertEqual(len({canonical_hash(value) for value in values}), 3)
        extremes = [math.ulp(0.0), float.fromhex("0x1.fffffffffffffp+1023")]
        self.assertEqual(canonical_bytes(extremes), b"[5e-324,1.7976931348623157e+308]")
        self.assertEqual(json.loads(canonical_bytes(values)), values)

    def test_nonfinite_floats_are_rejected(self):
        """! @brief root와 중첩 입력의 비유한 값은 바이트와 해시 양쪽에서 거부한다."""
        for number in [math.nan, math.inf, -math.inf]:
            for operation in [canonical_bytes, canonical_hash]:
                with self.subTest(number=number, operation=operation.__name__):
                    with self.assertRaises(CanonicalEncodingError):
                        operation(number)
                    with self.assertRaises(CanonicalEncodingError):
                        operation({"value": [number]})

    def test_integer_safe_range_and_bool_are_distinct(self):
        """! @brief 안전한 정수 경계는 보존하고 bool은 JSON boolean으로 유지한다."""
        values = [-9_007_199_254_740_991, 9_007_199_254_740_991, True, False]
        self.assertEqual(
            canonical_bytes(values),
            b"[-9007199254740991,9007199254740991,true,false]",
        )
        self.assertNotEqual(canonical_hash(True), canonical_hash(1))
        self.assertNotEqual(canonical_hash(False), canonical_hash(0))
        for number in [-9_007_199_254_740_992, 9_007_199_254_740_992, 10**100]:
            with self.subTest(number=number):
                with self.assertRaises(CanonicalEncodingError):
                    canonical_bytes(number)

    def test_utf8_text_has_no_bom_or_unicode_normalization(self):
        """! @brief 한글 UTF-8 원문을 보존하고 Unicode 정규화를 강제하지 않는다."""
        self.assertEqual(canonical_bytes("안테나"), '"안테나"'.encode("utf-8"))
        self.assertFalse(canonical_bytes("안테나").startswith(b"\xef\xbb\xbf"))
        self.assertNotEqual(canonical_hash("\uac00"), canonical_hash("\u1100\u1161"))

    def test_surrogate_values_and_keys_are_rejected(self):
        """! @brief surrogate는 escape로 숨기지 않고 값과 key 모두에서 거부한다."""
        for text in ["\ud800", "\udfff", "\ud800\udc00"]:
            for value in [text, {"value": text}, {text: 1}]:
                with self.subTest(value=ascii(value)):
                    with self.assertRaises(CanonicalEncodingError):
                        canonical_bytes(value)

    def test_object_keys_must_be_strings(self):
        """! @brief 숫자와 bool key를 문자열로 조용히 바꾸지 않는다."""
        for key in [1, True, None, ("a",)]:
            with self.subTest(key=key):
                with self.assertRaises(CanonicalEncodingError):
                    canonical_bytes({"valid": 1, key: 2})

    def test_unsupported_types_are_rejected(self):
        """! @brief JSON 밖의 타입과 동작을 바꿀 수 있는 subclass를 거부한다."""
        class CustomInt(int):
            """! @brief 내장 int와 구별할 시험용 subclass이다."""

        class CustomString(str):
            """! @brief 내장 str과 구별할 시험용 subclass이다."""

        class CustomList(list):
            """! @brief 내장 list와 구별할 시험용 subclass이다."""

        values = [
            (1, 2),
            {1, 2},
            b"bytes",
            bytearray(b"bytes"),
            Decimal("1.25"),
            complex(1, 2),
            object(),
            CustomInt(1),
            CustomString("text"),
            CustomList([1]),
            {CustomString("key"): 1},
        ]
        for value in values:
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(CanonicalEncodingError):
                    canonical_bytes(value)

    def test_direct_and_indirect_cycles_are_rejected(self):
        """! @brief list 자체 순환과 dict/list 간접 순환을 명시적으로 거부한다."""
        direct = []
        direct.append(direct)
        indirect = {"child": []}
        indirect["child"].append(indirect)
        for value in [direct, indirect]:
            with self.subTest(type=type(value).__name__):
                with self.assertRaisesRegex(CanonicalEncodingError, "순환"):
                    canonical_bytes(value)

    def test_shared_acyclic_subtree_is_allowed(self):
        """! @brief 반복 참조를 ancestor 순환과 혼동하지 않는다."""
        shared = {"x": [1, 2]}
        value = [shared, shared]
        self.assertEqual(canonical_bytes(value), b'[{"x":[1,2]},{"x":[1,2]}]')

    def test_depth_boundary_is_explicit(self):
        """! @brief root 깊이 0에서 64는 허용하고 65는 거부한다."""
        value = None
        for _ in range(64):
            value = [value]
        self.assertEqual(canonical_bytes(value), b"[" * 64 + b"null" + b"]" * 64)
        with self.assertRaisesRegex(CanonicalEncodingError, "깊이"):
            canonical_bytes([value])

        value = None
        for _ in range(64):
            value = {"child": value}
        self.assertEqual(json.loads(canonical_bytes(value)), value)
        with self.assertRaisesRegex(CanonicalEncodingError, "깊이"):
            canonical_bytes({"child": value})

    def test_encoding_does_not_mutate_or_convert_domain_values(self):
        """! @brief 표시 단위와 SI 값을 해석하거나 입력 순서/부호를 변경하지 않는다."""
        value = {"value_si": 0.001, "display_unit": "mm", "zero": -0.0}
        original_keys = list(value)
        self.assertEqual(
            canonical_bytes(value),
            b'{"display_unit":"mm","value_si":0.001,"zero":0.0}',
        )
        self.assertEqual(list(value), original_keys)
        self.assertEqual(value["value_si"], 0.001)
        self.assertEqual(math.copysign(1.0, value["zero"]), -1.0)


if __name__ == "__main__":
    unittest.main()
