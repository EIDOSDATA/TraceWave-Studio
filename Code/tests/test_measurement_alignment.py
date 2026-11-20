"""! @brief 비상호 행렬 순열과 RI 독립식, 결측/출처/수치 한계의 정렬 경계를 검사한다."""

from copy import deepcopy
import math
import unittest

import test_measurement as fixture
from rfad.adapters import network_backend
from rfad.application.canonical import canonical_bytes
from rfad.domain import measurement_alignment as alignment
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import make_dataset, validate_dataset


def specification(*operations):
    """! @brief 실제 연산 순서를 명시하고 자동 맞춤을 요청하지 않는다."""
    return {"schema": alignment.SCHEMA, "operations": list(operations), "reason": "독립 수치 정렬 시험", "source_refs": ["fixture:alignment"]}


def single(values, frequencies=None):
    """! @brief 독립 복소 RI 기대값을 위한 단일 포트 입력이다."""
    data = fixture.network()
    data.update(port_ids=[fixture.identity(1)], port_names=[None], reference_planes=["명시 단자"],
                port_modes=["single_ended"], current_orientation=["into_dut"],
                frequency_hz=[1.0, 3.0] if frequencies is None else frequencies)
    data["values_ri"] = [[[[value.real, value.imag]]] for value in values]
    data["valid_mask"] = [[[True]] for _ in values]
    data["sample_status"] = [[["valid"]] for _ in values]
    data["z0_ohm"] = [[[50.0, 0.0]] for _ in values]
    data["sample_origin"] = ["imported"] * len(values)
    validate_dataset(data)
    return data


ENGINE_READY = network_backend.installation_metadata()["installed"] == network_backend.VERSIONS


class MeasurementAlignmentTests(unittest.TestCase):
    """! @brief 입력이 동일한 척 보정하지 않고 새 자료의 연산/계보를 대조한다."""

    def test_nonreciprocal_permutation_moves_both_axes_every_port_field(self):
        """! @brief S12와 S21이 다른 행렬로 단일 축 이동 오류를 드러낸다."""
        data = fixture.network()
        original = canonical_bytes(data)
        result = alignment.permute_ports(data, [1, 0])["dataset"]
        self.assertEqual(result["values_ri"][0], [[[0.4, 0.0], [0.7, -0.1]], [[0.2, 0.3], [0.1, -0.2]]])
        self.assertEqual(result["z0_ohm"][0], [[75.0, 0.0], [50.0, 0.0]])
        for key in alignment.PORT_FIELDS:
            self.assertEqual(result[key], list(reversed(data[key])))
        self.assertEqual(result["sample_origin"], data["sample_origin"])
        self.assertEqual(result["conditions"], data["conditions"])
        self.assertEqual(result["source_refs"], data["source_refs"])
        self.assertEqual(result["provenance"]["raw_sha256"], data["provenance"]["raw_sha256"])
        again = alignment.permute_ports(result, [1, 0])["dataset"]
        for key in data:
            if key != "provenance":
                self.assertEqual(again[key], data[key], key)
        self.assertEqual(canonical_bytes(data), original)

    def test_permutation_preserves_unknown_complex_z0_and_mask_locations(self):
        """! @brief 재배열만 할 때 미정 파/복소 Z0를 계산 불능 이유로 지우지 않는다."""
        data = fixture.network()
        data.update(wave_definition="unknown", phasor_convention="unknown", reference_planes=[None, None])
        data["z0_ohm"][0][1] = [75, 4]
        data["values_ri"][0][0][1] = None
        data["valid_mask"][0][0][1] = False
        data["sample_status"][0][0][1] = "missing"
        result = alignment.permute_ports(data, [1, 0])["dataset"]
        self.assertIsNone(result["values_ri"][0][1][0])
        self.assertFalse(result["valid_mask"][0][1][0])
        self.assertEqual(result["sample_status"][0][1][0], "missing")
        self.assertEqual(result["z0_ohm"][0][0], [75, 4])

    def test_bad_permutations_do_not_become_partial_port_selection(self):
        """! @brief 중복/bool/부분/범위 밖 순열은 채널 선택으로 해석하지 않는다."""
        for order in ([0, 0], [True, 0], [0], [2, 0], [0.0, 1], None):
            with self.subTest(order=order), self.assertRaises(ProjectError):
                alignment.permute_ports(fixture.network(), order)

    def test_affine_ri_interpolation_and_compact_lineage_are_independent(self):
        """! @brief 기울기/절편으로 구한 RI 기대값과 정확 표본 출처를 대조한다."""
        data = fixture.network()
        original = canonical_bytes(data)
        output = alignment.interpolate_ri(data, [1e9, 1.5e9, 2e9, 3e9], 2e9)
        result = output["dataset"]
        for channel, expected in (((0, 0), (0.15, -0.1)), ((0, 1), (0.25, 0.15)), ((1, 0), (0.65, -0.05))):
            for actual, wanted in zip(result["values_ri"][1][channel[0]][channel[1]], expected):
                self.assertAlmostEqual(actual, wanted, places=15)
        self.assertEqual(result["sample_origin"], ["imported", "interpolated", "interpolated", "unknown"])
        self.assertEqual(output["lineage"]["samples"], [[0, 0, 0.0], [0, 1, 0.25], [0, 1, 0.5], [1, 1, 0.0]])
        self.assertEqual(result["values_ri"][0], data["values_ri"][0])
        self.assertEqual(result["conditions"], data["conditions"])
        self.assertEqual(canonical_bytes(data), original)

    def test_ri_not_phase_or_db_interpolation_and_exact_zero(self):
        """! @brief 위상 경계/영 반사점에서 magnitude/phase를 따로 맞추지 않는다."""
        data = single([complex(-1, 0.1), complex(-1, -0.1)])
        result = alignment.interpolate_ri(data, [2], 2)["dataset"]
        self.assertEqual(result["values_ri"], [[[[-1.0, 0.0]]]])
        data = single([1 + 1j, -1 - 1j])
        self.assertEqual(alignment.interpolate_ri(data, [2], 2)["dataset"]["values_ri"], [[[[0.0, 0.0]]]])

    def test_exact_selection_keeps_missing_values_and_unknown_basis(self):
        """! @brief 실제 보간 없는 exact 원문 선택은 누락을 0으로 만들지 않는다."""
        data = single([0j, 1j])
        data.update(wave_definition="unknown", phasor_convention="unknown", z0_ohm=None, reference_planes=[None])
        data["values_ri"][0][0][0] = None
        data["valid_mask"][0][0][0] = False
        data["sample_status"][0][0][0] = "missing"
        result = alignment.interpolate_ri(data, [1], 0.1)["dataset"]
        self.assertIsNone(result["values_ri"][0][0][0])
        self.assertFalse(result["valid_mask"][0][0][0])
        self.assertEqual(result["sample_origin"], ["imported"])
        self.assertIsNone(result["z0_ohm"])
        with self.assertRaises(ProjectError):
            alignment.interpolate_ri(data, [2], 2)

    def test_masked_gap_does_not_skip_to_distant_valid_sample(self):
        """! @brief 더 먼 유효 표본으로 결측을 뛰어넘는 수선은 하지 않는다."""
        data = single([0j, 1j, 2j], [1, 2, 3])
        data["values_ri"][1][0][0] = None
        data["valid_mask"][1][0][0] = False
        data["sample_status"][1][0][0] = "missing"
        original = deepcopy(data)
        with self.assertRaises(ProjectError) as raised:
            alignment.interpolate_ri(data, [1, 1.5, 3], 3)
        self.assertEqual(raised.exception.code, "E_CONFLICT")
        self.assertEqual(data, original)

    def test_extrapolation_maximum_gap_and_frequency_limits(self):
        """! @brief 유효하지 않은 주파수 목록을 자르거나 자동 생성하지 않는다."""
        for values, gap in (([0], 2), ([4], 2), ([2], 1.9), ([1, 1], 2), ([True], 2),
                            ([float("nan")], 2), ([3, 1], 2), ([2], 0), (list(range(1002)), 2)):
            with self.subTest(values=values[:4]), self.assertRaises(ProjectError):
                alignment.interpolate_ri(single([0j, 1j]), values, gap)

    def test_varying_complex_or_unknown_z0_and_unknown_rules_reject_interpolation(self):
        """! @brief 모르는 물리적 정의를 임의 50 ohm/단일종단으로 채우지 않는다."""
        for key, value in (("z0_ohm", [[[50, 0]], [[51, 0]]]), ("z0_ohm", [[[50, 1]], [[50, 1]]]),
                           ("phasor_convention", "unknown"), ("reference_planes", [None]),
                           ("port_modes", ["unknown"]), ("current_orientation", ["unknown"])):
            with self.subTest(key=key):
                data = single([0j, 1j])
                data[key] = value
                with self.assertRaises(ProjectError):
                    alignment.interpolate_ri(data, [2], 2)

    def test_large_opposite_ri_avoids_difference_overflow_and_detects_underflow(self):
        """! @brief 큰 반대 부호 값을 차분하지 않고 비영 underflow를 영 반사로 숨기지 않는다."""
        data = single([1e308 + 1e308j, -1e308 - 1e308j])
        self.assertEqual(alignment.interpolate_ri(data, [2], 2)["dataset"]["values_ri"], [[[[0.0, 0.0]]]])
        tiny = math.ulp(0.0)
        data = single([complex(tiny, 0), 0j])
        with self.assertRaises(ProjectError) as raised:
            alignment.interpolate_ri(data, [2], 2)
        self.assertEqual(raised.exception.code, "E_NUMERIC")
        data = single([0j, 1j], [0, 1e308])
        with self.assertRaises(ProjectError):
            alignment.interpolate_ri(data, [tiny], 1e308)
        constant = single([complex(tiny, tiny), complex(tiny, tiny)])
        self.assertEqual(alignment.interpolate_ri(constant, [2], 2)["dataset"]["values_ri"], [[[[tiny, tiny]]]])

    def test_maximum_sample_lineage_is_compact_and_provenance_overflow_is_explicit(self):
        """! @brief 1001개 작은 계보는 보존하며 기존 원문으로 상한이 넘으면 거절한다."""
        data = single([0j, 1j], [0, 1000])
        result = alignment.interpolate_ri(data, list(range(1001)), 1000)
        self.assertEqual(len(result["lineage"]["samples"]), 1001)
        self.assertLess(len(canonical_bytes(result["dataset"]["provenance"])), 65536)
        data["provenance"]["original"] = ["x" * 4096] * 15
        validate_dataset(data)
        before = canonical_bytes(data)
        with self.assertRaises(ProjectError) as raised:
            alignment.interpolate_ri(data, list(range(1001)), 1000)
        self.assertEqual(raised.exception.code, "E_RESOURCE")
        self.assertEqual(canonical_bytes(data), before)

    def test_specification_order_shapes_and_no_native_pure_operations(self):
        """! @brief 중간 표본 수의 Z0 축과 연산 순서를 원문 그대로 검사한다."""
        data = fixture.network()
        operations = [{"kind": "permute_ports", "order": [1, 0]},
                      {"kind": "linear_ri", "frequency_hz": [2e9], "max_gap_hz": 2e9}]
        spec = specification(*operations)
        result = alignment.align_dataset(data, spec, {"source_hash": "a" * 64, "profile": "pure-fixture"})
        self.assertEqual(result["dataset"]["port_ids"], list(reversed(data["port_ids"])))
        self.assertEqual([step["kind"] for step in result["lineage"]], ["permute_ports", "linear_ri"])
        self.assertEqual(spec["operations"], operations)
        for bad in (specification(operations[0], operations[0]), specification({"kind": "shift", "hz": 1}),
                    specification(operations[1], {"kind": "renormalize", "z0_ohm": data["z0_ohm"]})):
            with self.assertRaises(ProjectError):
                alignment.validate_alignment_specification(bad, data)

    def test_alignment_identity_and_unknown_operations_are_strict(self):
        """! @brief 엔진 identity를 도메인에서 발급하거나 임의 callable을 실행하지 않는다."""
        data = fixture.network()
        for bad in (None, {}, [], {"source_hash": float("inf")}):
            with self.subTest(identity=bad), self.assertRaises(ProjectError):
                alignment.align_dataset(data, specification({"kind": "permute_ports", "order": [0, 1]}), bad)
        for operation in ({"kind": []}, {"kind": "linear_ri", "frequency_hz": [2e9], "max_gap_hz": True},
                          {"kind": "renormalize", "z0_ohm": [None]}, {"kind": "permute_ports", "order": [0, 1], "callback": "x"}):
            with self.subTest(operation=operation), self.assertRaises(ProjectError):
                alignment.validate_alignment_specification(specification(operation), data)

    @unittest.skipUnless(ENGINE_READY, "고정 실제 network engine이 필요합니다.")
    def test_actual_renormalization_matches_independent_load_formula(self):
        """! @brief 100 ohm 부하의 Z0=50/75 반사식을 실제 엔진 파생 자료와 대조한다."""
        data = single([complex(1 / 3, 0), complex(1 / 3, 0)])
        original = canonical_bytes(data)
        spec = specification({"kind": "renormalize", "z0_ohm": [[[75.0, 0.0]], [[75.0, 0.0]]]})
        result = alignment.align_dataset(data, spec, {"source_hash": "b" * 64, "profile": "explicit-runtime"})
        for matrix in result["dataset"]["values_ri"]:
            self.assertAlmostEqual(matrix[0][0][0], (100 - 75) / (100 + 75), places=13)
            self.assertAlmostEqual(matrix[0][0][1], 0.0, places=13)
        self.assertEqual(result["lineage"][0]["kind"], "renormalize")
        self.assertTrue(result["lineage"][0]["engine"]["runtime_checked"])
        self.assertEqual(result["dataset"]["conditions"], data["conditions"])
        self.assertEqual(canonical_bytes(data), original)
