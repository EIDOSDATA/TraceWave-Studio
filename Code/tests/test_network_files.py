"""! @brief 원문 순서/단위/미정 조건과 유한 Touchstone/CSV 파서 경계를 독립 검증한다."""

from copy import deepcopy
import hashlib
import unittest
from uuid import uuid4

from rfad.adapters.network_files import (
    MAX_FILE_BYTES, MAX_LINE_CHARS, MAX_LINES, capabilities, csv_export_mapping,
    parse_csv, parse_touchstone, write_csv, write_touchstone,
)
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import validate_dataset


def sealed(parsed):
    """! @brief 서비스 경계처럼 파일 포트 순서에 새 안정 ID를 부여한다."""
    data = deepcopy(parsed["network"])
    data["port_ids"] = [str(uuid4()) for _ in range(parsed["port_count"])]
    validate_dataset(data)
    return data


def mapping(*, ports=1, form="RI", unit="MHz", delimiter=","):
    """! @brief 열을 추정하지 않는 시험용 명시 대응표를 만든다."""
    return {"delimiter": delimiter, "header": True, "frequency_column": 0, "frequency_unit": unit,
            "parameter_kind": "S", "complex_format": form, "value_unit": "1", "port_count": ports,
            "pairs": [{"row": row, "column": column, "first_column": 1 + 2 * (row * ports + column),
                       "second_column": 2 + 2 * (row * ports + column)} for row in range(ports) for column in range(ports)],
            "ignored_columns": []}


class TouchstoneFilesTests(unittest.TestCase):
    """! @brief 비상호 2포트 수치와 명세 기본값을 원문 순서에 독립 대조한다."""

    def test_v1_nonreciprocal_two_port_order_and_unknown_context(self):
        """! @brief S21과 S12가 다른 자료로 열 순서 전치를 검출한다."""
        raw = b"! sample\r\n# RI R 75 MHz S\r\n0 .1 -.2 .3 .4 .5 .6 .7 -.8 ! DC\r\n2 .2 -.1 .4 .3 .6 .5 .8 -.7\r\n"
        before = bytes(raw)
        parsed = parse_touchstone(raw, "원본.S2P")
        data = sealed(parsed)
        self.assertEqual(raw, before)
        self.assertEqual(data["frequency_hz"], [0, 2e6])
        self.assertEqual(data["values_ri"][0], [[[.1, -.2], [.5, .6]], [[.3, .4], [.7, -.8]]])
        self.assertEqual(data["z0_ohm"], [[[75, 0], [75, 0]]] * 2)
        self.assertEqual(data["reference_planes"], [None, None])
        self.assertEqual(data["phasor_convention"], "unknown")
        self.assertEqual(data["wave_definition"], "unknown")
        self.assertIsNone(data["conditions"])
        self.assertEqual(parsed["parser_metadata"]["source_sha256"], hashlib.sha256(raw).hexdigest())

    def test_v2_order_multiline_reference_and_split_network(self):
        """! @brief 2.x 명시 순서와 여러 줄 Reference/행렬을 정확히 적용한다."""
        for version in ("2.0", "2.1"):
            with self.subTest(version=version):
                raw = f"[Version] {version}\n# Hz S RI R 50\n[Number of Ports] 2\n[Reference]\n50\n75\n[Two-Port Data Order] 12_21\n[Number of Frequencies] 1\n[Matrix Format] Full\n[Network Data]\n1 .1 .2\n.3 .4 .5 .6\n.7 .8\n[End]\n".encode()
                parsed = parse_touchstone(raw, "network.ts")
                data = sealed(parsed)
                self.assertEqual(data["values_ri"], [[[[.1, .2], [.3, .4]], [[.5, .6], [.7, .8]]]])
                self.assertEqual(data["z0_ohm"], [[[50, 0], [75, 0]]])
                self.assertEqual(parsed["parser_metadata"]["reference_origin"], "reference_keyword")

    def test_default_reference_and_utf8_comment_extension_are_explicit(self):
        """! @brief 한글 주석과 R 누락은 ASCII 원문 명시값과 구분한다."""
        raw = "\ufeff! 직접 입력, 실측 아님\n#\n1 2 90\n".encode("utf-8")
        parsed = parse_touchstone(raw, "시험.s1p")
        data = sealed(parsed)
        self.assertEqual(data["frequency_hz"], [1e9])
        self.assertAlmostEqual(data["values_ri"][0][0][0][0], 0)
        self.assertEqual(data["values_ri"][0][0][0][1], 2)
        self.assertEqual(data["z0_ohm"], [[[50, 0]]])
        self.assertTrue(parsed["parser_metadata"]["utf8_comment_extension"])
        self.assertTrue(parsed["parser_metadata"]["bom"])
        self.assertEqual(parsed["parser_metadata"]["reference_origin"], "spec_default")
        self.assertIn("reference_ohm", parsed["parser_metadata"]["options"]["defaulted_options"])

    def test_db_and_ma_conversion_use_degree_and_twenty_log(self):
        """! @brief DB의 20log와 MA의 deg를 알려진 복소수와 대조한다."""
        db = sealed(parse_touchstone(b"# kHz S DB R 50\n1 20 90\n2 -20 180\n", "db.s1p"))
        ma = sealed(parse_touchstone(b"# Hz S MA R 50\n1 2 -90\n", "ma.s1p"))
        self.assertAlmostEqual(db["values_ri"][0][0][0][1], 10)
        self.assertAlmostEqual(db["values_ri"][1][0][0][0], -.1)
        self.assertAlmostEqual(ma["values_ri"][0][0][0][1], -2)
        self.assertEqual(db["frequency_hz"], [1000, 2000])

    def test_v1_unsupported_and_malformed_values_are_not_silently_dropped(self):
        """! @brief 미지원 종류/두 번째 옵션/노이즈/비유한 값과 정렬 오류를 차단한다."""
        cases = [b"# Hz Z RI R 50\n1 2 3\n", b"# Hz S RI R 50 75\n1 2 3\n",
                 b"# Hz S RI R 0\n1 2 3\n", b"# Hz S RI R 50\n# MHz S RI R 50\n1 2 3\n",
                 b"# Hz S RI R 50\n1 NaN 3\n", b"# Hz S RI R 50\n1 1e309 3\n",
                 b"# Hz S RI R 50\n1 1e-999 3\n", b"# Hz S RI R 50\n1 1e-999999999999999999999999999999999 3\n",
                 b"# Hz S RI R 50\n2 1 2\n1 1 2\n",
                 b"# Hz S RI R 50\n1 1 2\n1 2 3\n", b"# Hz S RI R 50\n-1 1 2\n",
                 b"# Hz S MA R 50\n1 -1 90\n", b"# Hz S DB R 50\n1 -10000 90\n",
                 b"# Hz S DB R 50\n1 10000 90\n", b"# Hz S RI R 50\n1 2D+0 3\n",
                 b"# Hz S RI R 50\n1 2 3 4 5\n", b"# Hz S RI R 50\n"]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ProjectError):
                parse_touchstone(raw, "bad.s1p")
        for name in ("bad.ts", "bad.s3p", "dir/bad.s1p"):
            with self.subTest(name=name), self.assertRaises(ProjectError):
                parse_touchstone(b"# Hz S RI R 50\n1 2 3\n", name)

    def test_v2_strict_keywords_counts_and_end(self):
        """! @brief 선언 누락/중복/미지원 부분행렬과 End 뒤 자료를 거절한다."""
        base = "[Version] 2.1\n# Hz S RI R 50\n[Number of Ports] 1\n[Number of Frequencies] 1\n[Network Data]\n1 2 3\n[End]\n"
        replacements = [("[Version] 2.1", "[Version] 3.0"), ("[Number of Frequencies] 1", "[Number of Frequencies] 2"),
                        ("[Network Data]", "[Matrix Format] Lower\n[Network Data]"),
                        ("[Network Data]", "[Mixed-Mode Order] S1\n[Network Data]"),
                        ("[Network Data]", "[Number of Noise Frequencies] 1\n[Network Data]"),
                        ("[Network Data]", "[Begin Information]\n[Network Data]"),
                        ("[Number of Ports] 1", " [Number of Ports] 1"),
                        ("[Number of Ports] 1", "[Number of Ports] 1\n[Number of Ports] 1"),
                        ("[End]", ""), ("[End]", "[End]\n2 3 4"), ("1 2 3", "1 2 3 2 4 5")]
        for old, new in replacements:
            with self.subTest(new=new), self.assertRaises(ProjectError):
                parse_touchstone(base.replace(old, new).encode(), "input.ts")
        with self.assertRaises(ProjectError):
            parse_touchstone(base.encode(), "wrong.s2p")

    def test_raw_line_row_and_sample_limits(self):
        """! @brief 크기 예산을 초과하는 파일을 자르지 않고 거절한다."""
        for raw in (b" " * (MAX_FILE_BYTES + 1), b"!" * (MAX_LINE_CHARS + 1), b"!\n" * (MAX_LINES + 1)):
            with self.assertRaises(ProjectError) as error:
                parse_touchstone(raw, "large.s1p")
            self.assertEqual(error.exception.code, "E_RESOURCE")
        values = "# Hz S RI R 50\n" + "".join(f"{index} 0 0\n" for index in range(1001))
        self.assertEqual(len(sealed(parse_touchstone(values.encode(), "limit.s1p"))["frequency_hz"]), 1001)
        with self.assertRaises(ProjectError):
            parse_touchstone((values + "1001 0 0\n").encode(), "over.s1p")

    def test_export_roundtrip_constant_unequal_z0_and_reject_lossy_cases(self):
        """! @brief 포트별 Z0와 비상호 행렬을 반올림 없이 다시 읽고 손실 출력은 차단한다."""
        data = sealed(parse_touchstone(b"# Hz S RI R 50\n1 .1 .2 .3 .4 .5 .6 .7 .8\n2 .9 .1 .2 .3 .4 .5 .6 .7\n", "source.s2p"))
        data["z0_ohm"] = [[[50, 0], [75, 0]]] * 2
        data["reference_planes"] = [None, "사용자 기준면"]
        before = deepcopy(data)
        exported = write_touchstone(data)
        parsed = sealed(parse_touchstone(exported, "output.ts"))
        for key in ("frequency_hz", "values_ri", "z0_ohm"):
            self.assertEqual(parsed[key], data[key])
        self.assertEqual(data, before)
        self.assertEqual(parsed["reference_planes"], [None, None])
        self.assertEqual(write_touchstone(data), exported)
        for key, value in (("z0_ohm", None), ("z0_ohm", [[[50, 1], [75, 0]]] * 2),
                           ("z0_ohm", [[[50, 0], [75, 0]], [[51, 0], [75, 0]]]), ("port_modes", ["unknown", "unknown"])):
            changed = deepcopy(data)
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ProjectError):
                write_touchstone(changed)
        data["valid_mask"][0][0][0] = False
        data["sample_status"][0][0][0] = "missing"
        data["values_ri"][0][0][0] = None
        with self.assertRaises(ProjectError):
            write_touchstone(data)


class CsvNetworkTests(unittest.TestCase):
    """! @brief UTF-8 원문과 명시 열 대응, 미정 조건 및 출력 재현성을 검증한다."""

    def test_utf8_explicit_mapping_and_missing_context(self):
        """! @brief 한글 헤더와 BOM을 읽어도 Z0/기준면/실측 여부를 만들지 않는다."""
        raw = "\ufeff주파수,실수,허수\n1,.25,-.5\n2,-.5,.75\n".encode("utf-8")
        parsed = parse_csv(raw, mapping())
        data = sealed(parsed)
        self.assertEqual(data["frequency_hz"], [1e6, 2e6])
        self.assertEqual(data["values_ri"], [[[[.25, -.5]]], [[[-.5, .75]]]])
        self.assertIsNone(data["z0_ohm"])
        self.assertEqual(data["sample_origin"], ["imported", "imported"])
        self.assertEqual(data["reference_planes"], [None])
        self.assertIsNone(data["conditions"])
        self.assertEqual(parsed["parser_metadata"]["column_names"], ["주파수", "실수", "허수"])

    def test_nonreciprocal_reordered_columns_and_explicit_ignored_column(self):
        """! @brief 헤더 이름과 무관하게 지정 인덱스만 행렬에 반영한다."""
        options = mapping(ports=2)
        options["frequency_column"] = 8
        for item in options["pairs"]:
            item["first_column"] -= 1
            item["second_column"] -= 1
        options["ignored_columns"] = [9]
        options["z0_ohm"] = [50, 75]
        raw = b"a,b,c,d,e,f,g,h,freq,notes\n.1,.2,.3,.4,.5,.6,.7,.8,2,not a number\n"
        data = sealed(parse_csv(raw, options))
        self.assertEqual(data["values_ri"], [[[[.1, .2], [.3, .4]], [[.5, .6], [.7, .8]]]])
        self.assertEqual(data["z0_ohm"], [[[50, 0], [75, 0]]])

    def test_units_representation_and_delimiters(self):
        """! @brief 구분자/표현/단위는 입력 대응표와 일치할 때만 변환한다."""
        for form, first, expected in (("MA", "2", 2), ("DB", "20", 10)):
            for delimiter in (";", "\t"):
                options = mapping(form=form, delimiter=delimiter)
                raw = (delimiter.join(("f", "m", "deg")) + "\n" + delimiter.join(("1", first, "90")) + "\n").encode()
                data = sealed(parse_csv(raw, options))
                self.assertAlmostEqual(data["values_ri"][0][0][0][1], expected)
        for kind, unit in (("Z", "ohm"), ("Y", "S")):
            options = mapping()
            options.update(parameter_kind=kind, value_unit=unit)
            data = sealed(parse_csv(b"f,re,im\n1,2,3\n", options))
            self.assertEqual(data["unit"], unit)
            self.assertEqual(data["values_ri"], [[[[2, 3]]]])

    def test_bad_columns_quotes_numbers_and_metadata_are_rejected(self):
        """! @brief 불명확한 열/자료를 제거하거나 0으로 채우지 않는다."""
        for raw in (b"f,re,im,extra\n1,2,3,4\n", b"f,re,im\n1,2\n", b"f,re,im\n1,,3\n",
                    b"f,re,im\n1,NaN,3\n", b"f,re,im\n2,2,3\n1,3,4\n",
                    b'f,re,im\n1,"2\n3",4\n', b'f,re,im\n1,"2"oops,3\n', b"f,re,im\n"):
            with self.subTest(raw=raw), self.assertRaises(ProjectError):
                parse_csv(raw, mapping())
        for update in ({"frequency_column": True}, {"ignored_columns": [2]}, {"value_unit": "ohm"},
                       {"frequency_unit": "auto"}, {"z0_ohm": [None]}, {"z0_ohm": [-1]}, {"extra": "guess"}):
            options = mapping()
            options.update(update)
            with self.subTest(update=update), self.assertRaises(ProjectError):
                parse_csv(b"f,re,im\n1,2,3\n", options)

    def test_csv_export_preserves_data_and_does_not_guess_context(self):
        """! @brief 내보낸 고정 열을 다시 가져오고 별도 조건/원본을 변경하지 않는다."""
        data = sealed(parse_touchstone(b"# MHz S RI R 75\n1 .1 -.2\n", "source.s1p"))
        before = deepcopy(data)
        raw = write_csv(data)
        self.assertEqual(raw, b"frequency_Hz,S11_re,S11_im\n1000000,0.10000000000000001,-0.20000000000000001\n")
        parsed = sealed(parse_csv(raw, csv_export_mapping(data)))
        self.assertEqual(parsed["values_ri"], data["values_ri"])
        self.assertEqual(parsed["frequency_hz"], data["frequency_hz"])
        self.assertIsNone(parsed["z0_ohm"])
        self.assertEqual(data, before)
        self.assertEqual(capabilities()["max_samples"], 1001)


if __name__ == "__main__":
    unittest.main()
