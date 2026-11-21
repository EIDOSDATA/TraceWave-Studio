"""! @brief 공통 복소 자료와 회로/목표 판정을 독립 수식 및 실패 경계로 검증한다."""

from copy import deepcopy
import json
import math
import subprocess
import sys
import unittest
from uuid import UUID

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_hash
from rfad.domain.errors import ProjectError
from rfad.domain.expressions import evaluate_expression, RESERVED_NAMES
from rfad.domain.network_assessment import evaluate_target, reflection_metrics
from rfad.domain.network_circuit import SCHEMA as CIRCUIT_SCHEMA, apply_circuit, validate_circuit
from rfad.domain.network_data import make_dataset, validate_dataset
from rfad.domain.network_transform import transform_dataset
from rfad.domain.units import Dimension, Quantity


def identity(number):
    """! @brief 시험 ID를 재현 가능하게 만든다."""
    return str(UUID(int=number))


def network(values=(0j,), frequencies=None):
    """! @brief 실제 측정/제작 조건을 채우지 않은 명시 1포트 계산 예제를 만든다."""
    frequencies = [1e9 + index * 1e8 for index in range(len(values))] if frequencies is None else frequencies
    return make_dataset(parameter_kind="S", frequency_hz=frequencies, port_ids=[identity(1)],
                        values_ri=[[[[value.real, value.imag]]] for value in values], z0_ohm=[[[50.0, 0.0]]] * len(values),
                        wave_definition="traveling", phasor_convention="exp(+j*omega*t)", reference_planes=["부하 단자"],
                        port_names=["급전 1"], port_modes=["single_ended"], current_orientation=["into_dut"],
                        sample_origin=["computed"] * len(values), conditions={"manufacture": None, "measurement": None},
                        source_refs=["fixture:analytic"])


def component(kind="R", value=50, unit="ohm", connection="series", state="connected", number=10):
    """! @brief 외부 회로 요소의 값/출처를 명시한다."""
    return {"id": identity(number), "name": kind + str(number), "kind": kind, "connection": connection, "state": state,
            "value": Quantity.from_value(value, unit, source_refs=("fixture:component",)).to_dict(), "source_refs": ["fixture:component"]}


def circuit(*elements):
    """! @brief 소자는 입력에서 부하 순서이며 기준면 이동을 회로 결합으로 기록한다."""
    return {"schema": CIRCUIT_SCHEMA, "name": "외부 이상망", "em_scope": "outside_em",
            "input_reference_plane": "회로 입력", "load_reference_plane": "부하 단자",
            "elements": list(elements) if elements else [component()], "source_refs": [], "assumptions": ["기생 성분 미정"]}


def target(*metrics, frequencies=(1e9, 1.1e9, 1.2e9)):
    """! @brief 표본과 한계를 명시한 목표를 생성한다."""
    return {"id": identity(100), "revision_id": identity(101), "name": "시험 목표", "physical_mode": "radiating_rf",
            "band": {"start": Quantity.from_value(frequencies[0], "Hz").to_dict(),
                     "end": Quantity.from_value(frequencies[-1], "Hz").to_dict(),
                     "reference": Quantity.from_value(frequencies[len(frequencies) // 2], "Hz").to_dict(),
                     "sampling": {"kind": "explicit", "frequencies": [Quantity.from_value(value, "Hz").to_dict() for value in frequencies]}},
            "port_id": identity(200), "reference_impedance": Quantity.from_value(50, "ohm").to_dict(),
            "criteria": [{"metric": metric, "operator": "le" if metric == "s11_db" else "ge",
                          "limit": {"value": float(value), "unit": "dB" if metric == "s11_db" else "1",
                                    "status": "user_entered", "source_refs": []}} for metric, value in (metrics or (("s11_db", -10),))],
            "source_refs": ["fixture:target"]}


CONTEXT = {"port_id": identity(1), "target_port_id": identity(200), "reference_plane": "부하 단자", "frequency_policy": "exact_only"}
ENGINE_READY = network_backend.installation_metadata()["installed"] == network_backend.VERSIONS


class NetworkDataTests(unittest.TestCase):
    """! @brief 원본 조건과 유한 행렬 계약을 보존하는 경계를 검사한다."""

    def test_unknown_conditions_and_complex_z0_are_preserved(self):
        """! @brief 보존은 계산 지원 여부와 분리한다."""
        data = network()
        data.update(z0_ohm=[[[50, 7]]], reference_planes=[None], wave_definition="unknown", phasor_convention="unknown")
        original = deepcopy(data)
        validate_dataset(data)
        self.assertEqual(original, data)

    def test_masked_missing_cell_and_measured_origin_remain_distinct(self):
        """! @brief 누락값을 0으로 만들거나 imported를 measured로 승격하지 않는다."""
        data = network()
        data.update(values_ri=[[[None]]], valid_mask=[[[False]]], sample_status=[[["missing"]]], sample_origin=["imported"])
        validate_dataset(data)
        self.assertIsNone(data["values_ri"][0][0][0])
        self.assertEqual(data["sample_origin"], ["imported"])

    def test_bad_metadata_and_axes_fail_with_project_errors(self):
        """! @brief 잘못된 JSON 타입도 내부 TypeError 대신 계약 오류로 반환한다."""
        for key, value in (("wave_definition", []), ("phasor_convention", {}), ("sample_origin", [[]]),
                           ("values_ri", []), ("valid_mask", [[[1]]]), ("sample_status", [[["missing"]]]),
                           ("z0_ohm", [[None, None]]), ("frequency_hz", [float("nan")])):
            with self.subTest(key=key):
                data = network()
                data[key] = value
                with self.assertRaises(ProjectError):
                    validate_dataset(data)

    def test_duplicate_frequency_port_and_budgets_are_rejected(self):
        """! @brief 잘라내지 않고 중복 축과 상한을 명확히 거부한다."""
        for frequencies in ([1e9, 1e9], [1e9, 0], list(range(1002))):
            with self.assertRaises(ProjectError):
                network([0j] * len(frequencies), frequencies)
        data = network()
        data["provenance"] = {"history": ["x" * 4096] * 17}
        with self.assertRaises(ProjectError):
            validate_dataset(data)

    def test_quantity_inductance_capacitance_and_source_are_preserved(self):
        """! @brief RF 소자 표시 단위는 기존 Quantity의 SI/출처 규약을 따른다."""
        inductance = Quantity.from_value(5, "nH", source_refs=("source:original",))
        capacitance = Quantity.from_value(2.2, "pF")
        self.assertEqual(inductance.dimension, Dimension.INDUCTANCE)
        self.assertAlmostEqual(inductance.as_unit("uH"), 0.005)
        self.assertEqual(inductance.source_refs, ("source:original",))
        self.assertEqual(capacitance.dimension, Dimension.CAPACITANCE)
        self.assertAlmostEqual(capacitance.as_unit("pF"), 2.2)

    def test_circuit_rejects_unrepresentable_display_quantity_before_saving(self):
        """! @brief 유한 SI라도 표시 환산 overflow가 있으면 재열기 전에 거절한다."""
        definition = circuit(component("C", 1, "pF"))
        definition["elements"][0]["value"]["value_si"] = 1e308
        with self.assertRaises(ProjectError) as caught:
            validate_circuit(definition)
        self.assertEqual(caught.exception.code, "E_UNIT")

    def test_metadata_and_model_import_do_not_import_native_modules(self):
        """! @brief 재열기/지원 조회는 선택 NumPy/scikit-rf 설치에 의존하지 않는다."""
        code = """
import sys
class Guard:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('numpy', 'scipy', 'skrf', 'h5py'):
            raise RuntimeError('eager native import:' + fullname)
sys.meta_path.insert(0, Guard())
from rfad.domain.network_data import validate_dataset
from rfad.domain.network_circuit import validate_circuit
from rfad.domain.network_assessment import reflection_metrics
from rfad.adapters.network_backend import installation_metadata
installation_metadata()
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_quantity_dimensions_do_not_reclassify_existing_parameter_names(self):
        """! @brief L/C 차원 추가가 과거 C/H/F 변수의 의미나 이름 유효성을 바꾸지 않는다."""
        for name in ("H", "F", "C", "nH", "pF"):
            self.assertNotIn(name, RESERVED_NAMES)
        capacitance = evaluate_expression("1e-12 * s / ohm", {}, expected_dimension="capacitance", display_unit="pF")
        inductance = evaluate_expression("1e-9 * ohm * s", {}, expected_dimension="inductance", display_unit="nH")
        self.assertEqual(capacitance.as_unit("pF"), 1.0)
        self.assertEqual(inductance.as_unit("nH"), 1.0)


@unittest.skipUnless(ENGINE_READY, "고정 선택 네트워크 엔진이 필요함")
class NetworkTransformTests(unittest.TestCase):
    """! @brief 독립 1포트 수식과 비대칭 2포트 왕복으로 변환을 검증한다."""

    def test_complex_one_port_s_z_y_matches_analytic_impedance(self):
        """! @brief 알려진 복소 부하에서 S/Z/Y를 독립 식과 대조한다."""
        impedance = 80 + 25j
        reflection = (impedance - 50) / (impedance + 50)
        data = network([reflection])
        for kind, expected in (("Z", impedance), ("Y", 1 / impedance)):
            result = transform_dataset(data, {"operation": "convert", "parameter_kind": kind})
            actual = complex(*result["dataset"]["values_ri"][0][0][0])
            self.assertAlmostEqual(abs(actual - expected), 0, places=10)
            self.assertLess(result["diagnostics"][0]["relative_residual"], 1e-12)

    def test_asymmetric_two_port_unequal_z0_roundtrip(self):
        """! @brief outgoing/incident 축과 서로 다른 포트 Z0를 보존한다."""
        data = make_dataset(parameter_kind="Z", frequency_hz=[2e9], port_ids=[identity(1), identity(2)],
                            values_ri=[[[[75., 12.], [8., 2.]], [[-3., 4.], [120., -11.]]]],
                            z0_ohm=[[[50., 0.], [75., 0.]]], wave_definition="power", reference_planes=["A", "B"],
                            port_modes=["single_ended"] * 2, current_orientation=["into_dut"] * 2)
        scattering = transform_dataset(data, {"operation": "convert", "parameter_kind": "S"})["dataset"]
        for kind in ("Z", "Y"):
            converted = transform_dataset(scattering, {"operation": "convert", "parameter_kind": kind})["dataset"]
            restored = converted if kind == "Z" else transform_dataset(converted, {"operation": "convert", "parameter_kind": "Z"})["dataset"]
            self.assertEqual(restored["port_ids"], data["port_ids"])
            for row in range(2):
                for column in range(2):
                    self.assertLess(abs(complex(*restored["values_ri"][0][row][column]) - complex(*data["values_ri"][0][row][column])), 1e-9)

    def test_explicit_renormalization_preserves_original_plane_and_sources(self):
        """! @brief 50 ohm 부하를 75 ohm 기준으로 바꾸면 -0.2이며 원본은 불변이다."""
        data = network()
        before = deepcopy(data)
        result = transform_dataset(data, {"operation": "renormalize", "z0_ohm": [[[75., 0.]]]})["dataset"]
        self.assertAlmostEqual(result["values_ri"][0][0][0][0], -0.2)
        self.assertEqual(result["reference_planes"], data["reference_planes"])
        self.assertEqual(result["conditions"], data["conditions"])
        self.assertEqual(data, before)
        self.assertEqual(result["provenance"]["network_operations"][0]["input_hash"], canonical_hash(data))

    def test_singular_and_near_singular_s_to_z_are_masked_without_nudge(self):
        """! @brief 엔진이 개방을 큰 유한 저항으로 바꾸지 못하게 차단한다."""
        result = transform_dataset(network([1 + 0j, 1 - 1e-14 + 0j]), {"operation": "convert", "parameter_kind": "Z"})
        self.assertEqual(result["dataset"]["valid_mask"], [[[False]], [[False]]])
        self.assertEqual(result["dataset"]["sample_status"], [[["singular"]], [["ill_conditioned"]]])
        self.assertEqual(result["dataset"]["values_ri"], [[[None]], [[None]]])

    def test_unknown_and_complex_references_block_without_default(self):
        """! @brief 원문에 없는 50 ohm 또는 기준면을 몰래 보충하지 않는다."""
        for key, value in (("z0_ohm", None), ("z0_ohm", [[[50., 1.]]]), ("reference_planes", [None]), ("wave_definition", "unknown")):
            data = network()
            data[key] = value
            original = deepcopy(data)
            with self.assertRaises(ProjectError):
                transform_dataset(data, {"operation": "convert", "parameter_kind": "Z"})
            self.assertEqual(data, original)

    def test_mask_and_extreme_values_do_not_crash_or_become_zero(self):
        """! @brief 누락 및 overflow 표본은 유효 숫자처럼 취급하지 않는다."""
        data = network([0j, complex(1e308, 1e308)])
        data["values_ri"][0][0][0] = None
        data["valid_mask"][0][0][0] = False
        data["sample_status"][0][0][0] = "missing"
        result = transform_dataset(data, {"operation": "convert", "parameter_kind": "Z"})["dataset"]
        self.assertFalse(result["valid_mask"][0][0][0])
        self.assertFalse(result["valid_mask"][1][0][0])
        json.dumps(result, allow_nan=False)


@unittest.skipUnless(ENGINE_READY, "고정 선택 네트워크 엔진이 필요함")
class NetworkCircuitTests(unittest.TestCase):
    """! @brief 독립 임피던스 계산으로 기본 사다리망과 DC 상태를 검증한다."""

    def test_series_and_shunt_resistor_match_independent_load_formula(self):
        """! @brief 동일 50 ohm 소자의 직렬/병렬 부하는 +/-1/3 반사를 갖는다."""
        for connection, expected in (("series", 1 / 3), ("shunt", -1 / 3)):
            result = apply_circuit(network(), circuit(component(connection=connection)))["dataset"]
            self.assertAlmostEqual(result["values_ri"][0][0][0][0], expected)
            self.assertAlmostEqual(result["values_ri"][0][0][0][1], 0)

    def test_reactive_sequence_and_phasor_sign_match_independent_rlc(self):
        """! @brief 입력->부하 순서를 유지하고 시간 규약 반전은 허수 부호를 반전한다."""
        definition = circuit(component("L", 5, "nH"), component("C", 2, "pF", "shunt", number=11))
        for sign, phasor in ((1, "exp(+j*omega*t)"), (-1, "exp(-j*omega*t)")):
            data = network()
            data["phasor_convention"] = phasor
            actual = complex(*apply_circuit(data, definition)["dataset"]["values_ri"][0][0][0])
            impedance = sign * 1j * 2 * math.pi * 1e9 * 5e-9 + 1 / (1 / 50 + sign * 1j * 2 * math.pi * 1e9 * 2e-12)
            expected = (impedance - 50) / (impedance + 50)
            self.assertLess(abs(actual - expected), 1e-12)

    def test_dc_open_short_are_topology_not_huge_values(self):
        """! @brief DC L/C와 명시 open/short/DNP 상태를 유한 정확값으로 처리한다."""
        for kind, unit, connection, expected in (("C", "pF", "series", 1), ("C", "pF", "shunt", 0),
                                                  ("L", "nH", "series", 0), ("L", "nH", "shunt", -1)):
            result = apply_circuit(network(frequencies=[0]), circuit(component(kind, 1, unit, connection)))
            self.assertEqual(result["dataset"]["values_ri"][0][0][0], [float(expected), 0.0])
        for connection, state, expected in (("series", "dnp", 1), ("shunt", "dnp", 0), ("series", "short", 0), ("shunt", "short", -1)):
            result = apply_circuit(network(), circuit(component(connection=connection, state=state)))
            self.assertEqual(result["dataset"]["values_ri"][0][0][0], [float(expected), 0.0])

    def test_missing_quantity_stores_but_application_blocks(self):
        """! @brief 미정 설계를 저장할 수 있어도 회로값을 임의 추천하지 않는다."""
        definition = circuit()
        definition["elements"][0]["value"] = Quantity.missing(Dimension.IMPEDANCE, "ohm").to_dict()
        validate_circuit(definition)
        with self.assertRaises(ProjectError):
            apply_circuit(network(), definition)

    def test_reference_plane_em_scope_and_phasor_are_explicit(self):
        """! @brief EM 내부 이중계산 및 기준면/위상 미정을 차단한다."""
        for key, value in (("load_reference_plane", "다른 면"), ("input_reference_plane", None), ("em_scope", "inside_em")):
            definition = circuit()
            definition[key] = value
            with self.assertRaises(ProjectError):
                apply_circuit(network(), definition)
        data = network()
        data["phasor_convention"] = "unknown"
        with self.assertRaises(ProjectError):
            apply_circuit(data, circuit())

    def test_original_and_component_sources_preserved_without_field_claim(self):
        """! @brief 외부 회로 파생값은 이전 실물/방사 검증을 승계하지 않는다."""
        data, definition = network(), circuit()
        before = deepcopy((data, definition))
        result = apply_circuit(data, definition)["dataset"]
        self.assertEqual((data, definition), before)
        self.assertEqual(result["reference_planes"], ["회로 입력"])
        record = result["provenance"]["network_operations"][-1]["options"]
        self.assertEqual(record["definition"], definition)
        self.assertFalse(record["field_metrics_carried"])
        self.assertEqual(record["actual_component_parasitics"], "not_supplied")

    def test_active_load_singular_connection_is_masked(self):
        """! @brief R=50 직렬 요소 S22=1/3와 부하 반사3의 특이 결합을 판정한다."""
        result = apply_circuit(network([3 + 0j]), circuit())
        self.assertFalse(result["dataset"]["valid_mask"][0][0][0])
        self.assertIn(result["dataset"]["sample_status"][0][0][0], ("singular", "ill_conditioned"))


class NetworkAssessmentTests(unittest.TestCase):
    """! @brief 샘플 통과, 미정 및 연속 대역 검증을 분리한다."""

    def test_perfect_match_open_and_active_reflection_special_states(self):
        """! @brief 무한 지표는 JSON 숫자로 내보내지 않는다."""
        match = reflection_metrics(0j)
        self.assertEqual(match["s11_state"], "negative_infinity")
        self.assertEqual(match["vswr"], 1)
        self.assertEqual(reflection_metrics(1j)["vswr_state"], "positive_infinity")
        self.assertEqual(reflection_metrics(2j)["vswr_state"], "undefined_active")
        json.dumps([match, reflection_metrics(1j), reflection_metrics(2j)], allow_nan=False)

    def test_all_sample_pass_is_conditional_not_continuous_band_verification(self):
        """! @brief 3개 점 통과를 대역 전체나 실물 합격으로 확대하지 않는다."""
        data, goal = network([0j, 0.1 + 0j, 0.2 + 0j]), target()
        before = deepcopy((data, goal))
        result = evaluate_target(goal, data, CONTEXT)
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["criteria"][0]["sample_status"], "pass")
        self.assertFalse(result["continuous_band_verified"])
        self.assertFalse(result["physics_validated"])
        self.assertEqual((data, goal), before)

    def test_failed_sample_rejects_target_even_if_other_sample_missing(self):
        """! @brief 확인된 반례는 불완전 커버리지 때문에 사라지지 않는다."""
        result = evaluate_target(target(), network([0.5 + 0j, 0j], [1e9, 1.2e9]), CONTEXT)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["criteria"][0]["coverage"], {"required": 3, "available": 2, "missing": 1})

    def test_near_frequency_does_not_imply_nearest_or_interpolation(self):
        """! @brief 주파수 오차를 자동 정렬하지 않는다."""
        result = evaluate_target(target(), network([0j] * 3, [1e9, 1.1e9 + 1, 1.2e9]), CONTEXT)
        self.assertEqual(result["status"], "not_evaluated")
        self.assertEqual(result["criteria"][0]["coverage"]["missing"], 1)

    def test_z0_plane_port_mapping_and_missing_limit_block_evaluation(self):
        """! @brief 서로 다른 기준이나 원문 미정값에서 합격을 생성하지 않는다."""
        for field, value in (("reference_plane", "다른 면"), ("target_port_id", identity(999)), ("reference_plane", None)):
            context = {**CONTEXT, field: value}
            self.assertEqual(evaluate_target(target(), network([0j] * 3), context)["status"], "not_evaluated")
        goal = target()
        goal["reference_impedance"] = Quantity.from_value(75, "ohm").to_dict()
        self.assertEqual(evaluate_target(goal, network([0j] * 3), CONTEXT)["status"], "not_evaluated")
        goal = target()
        goal["criteria"][0]["limit"].update(value=None, status="missing")
        self.assertEqual(evaluate_target(goal, network([0j] * 3), CONTEXT)["status"], "not_evaluated")

    def test_saved_target_plane_cannot_be_bypassed_by_matching_other_data(self):
        """! @brief 자료와 요청이 일치해도 저장한 목표 기준면이 다르면 판정하지 않는다."""
        data = network([0j] * 3)
        goal = {**target(), "reference_plane": "칩 패드 기준면"}
        before = deepcopy((data, goal))
        result = evaluate_target(goal, data, CONTEXT)
        self.assertEqual(result["status"], "not_evaluated")
        self.assertTrue(all("설계 목표에 저장된 기준면" in row["reason"] for row in result["criteria"][0]["points"]))
        self.assertEqual((data, goal), before)
        same_plane = {**goal, "reference_plane": CONTEXT["reference_plane"]}
        self.assertEqual(evaluate_target(same_plane, data, CONTEXT)["status"], "conditional")
        renamed = {**CONTEXT, "reference_plane": goal["reference_plane"]}
        self.assertEqual(evaluate_target(goal, data, renamed)["status"], "not_evaluated")

    def test_efficiency_requires_matching_dataset_hash_and_physical_range(self):
        """! @brief 방사 효율은 S11로 추정하지 않으며 다른 정합 결과에 복사하지 않는다."""
        data = network([0j] * 3)
        goal = target(("radiation_efficiency", 0.8), ("total_efficiency", 0.7))
        metrics = {"dataset_hash": canonical_hash(data), "source_refs": ["fixture:nf2ff"], "physics_validated": False,
                   "frequency_hz": data["frequency_hz"], "radiation_efficiency": [0.9] * 3, "total_efficiency": [0.8] * 3}
        self.assertEqual(evaluate_target(goal, data, CONTEXT)["status"], "not_evaluated")
        self.assertEqual(evaluate_target(goal, data, CONTEXT, metrics)["status"], "conditional")
        metrics["radiation_efficiency"][1] = 1.02
        self.assertEqual(evaluate_target(goal, data, CONTEXT, metrics)["status"], "not_evaluated")
        metrics["dataset_hash"] = "0" * 64
        with self.assertRaises(ProjectError):
            evaluate_target(goal, data, CONTEXT, metrics)

    def test_fractional_bandwidth_remains_sampled_estimate(self):
        """! @brief 원문 한계를 사용한 표본 폭은 임계 교차점 검증을 대신하지 않는다."""
        result = evaluate_target(target(("s11_db", -10), ("fractional_bandwidth", 0.1)), network([0.1 + 0j] * 3), CONTEXT)
        bandwidth = next(row for row in result["criteria"] if row["metric"] == "fractional_bandwidth")
        self.assertEqual(bandwidth["status"], "not_evaluated")
        self.assertAlmostEqual(bandwidth["sampled_estimate"]["value"], 2 * (1.2e9 - 1e9) / (1.2e9 + 1e9))
        self.assertTrue(bandwidth["sampled_estimate"]["meets_limit_at_sampled_span"])

    def test_efficiency_cannot_be_reassigned_to_another_excitation_in_two_ports(self):
        """! @brief 동일 2포트 행렬 해시만으로 어느 여기의 방사인지 추정하지 않는다."""
        data = make_dataset(parameter_kind="S", frequency_hz=[1e9], port_ids=[identity(1), identity(2)],
                            values_ri=[[[[0., 0.], [0., 0.]], [[0., 0.], [0., 0.]]]])
        metrics = {"dataset_hash": canonical_hash(data), "source_refs": [], "physics_validated": False,
                   "frequency_hz": [1e9], "radiation_efficiency": [0.9], "total_efficiency": [0.8]}
        with self.assertRaises(ProjectError) as caught:
            evaluate_target(target(("radiation_efficiency", 0.7)), data, CONTEXT, metrics)
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")

    def test_bandwidth_without_s11_threshold_does_not_invent_minus_10_db(self):
        """! @brief 흔한 -10 dB 기준도 목표에 없으면 추가하지 않는다."""
        result = evaluate_target(target(("fractional_bandwidth", 0.1)), network([0j] * 3), CONTEXT)
        self.assertIsNone(result["criteria"][0]["sampled_estimate"])


if __name__ == "__main__":
    unittest.main()
