"""! @brief 스윕의 유한 조합, 원본 보존, 계산 재사용 및 실패 후보 경계를 검증한다."""

from copy import deepcopy
import math
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design_sweep import SCHEMA, candidate_at, candidate_count, context_variables, validate_specification
from rfad.domain.errors import ProjectError
from rfad.domain.parameter_graph import evaluate_parameters, expression_record
from rfad.domain.project import validate_project
from rfad.domain.sweep_inputs import input_quantity, normalize_budget, normalize_settings, numerical_fields
from rfad.domain.units import Quantity
from test_network_domain import circuit, component, target
from test_pcb_solver import SETTINGS, fixture_document


def quantity(value, unit="mm", sources=None):
    """! @brief 실제 제조 근거가 아닌 시험 입력 출처를 명시한다."""
    return Quantity.from_value(value, unit, source_refs=["test:sweep-explicit"] if sources is None else sources).to_dict()


def typed(text, unit="mm"):
    """! @brief GUI가 전달하는 원문 문자열과 명시 단위를 만든다."""
    return {"text": text, "unit": unit, "source_refs": ["test:사용자 입력"]}


def fixture():
    """! @brief 독립 선폭 매개변수 둘과 기존 미정 금속 유전율을 가진 설계를 만든다."""
    document = fixture_document()
    identities = []
    for index, shape in enumerate(document["geometry"]):
        identity = str(uuid4())
        identities.append(identity)
        document["parameters"][identity] = {"id": identity, "name": "선폭 " + str(index + 1), "quantity": quantity(1)}
        shape["width"] = {"parameter_id": identity}
    metal = next(row for row in document["materials"] if row["id"] == document["stackup"][1]["material_id"])
    metal["epsilon_r"] = Quantity.missing("dimensionless", "1").to_dict()
    validate_project(document)
    return document, identities


def definition(variables, *, kind="grid_sweep", combination="cartesian"):
    """! @brief 명시 자원 예산을 가진 원문 연구 정의를 생성한다."""
    return {"schema": SCHEMA, "type": kind, "name": "단위와 원문 보존 시험", "combination": combination,
            "variables": variables, "settings": deepcopy(SETTINGS) if kind != "circuit_sweep" else None,
            "network": {"dataset_id": str(uuid4()), "circuit_id": str(uuid4())} if kind == "circuit_sweep" else None,
            "target_ids": [], "budget": {"max_candidates": 128, "max_native_solves": 0 if kind == "circuit_sweep" else 128,
                                        "wall_seconds": 600, "ram_bytes": 2**30, "disk_bytes": 2**30, "concurrency": 1},
            "source_refs": ["test:연구 원문"]}


def axis(identity, values, kind="parameter", dimension="length"):
    """! @brief 축 순서 및 값 원문을 그대로 전달한다."""
    return {"kind": kind, "id": identity, "dimension": dimension, "values": values}


class DesignSweepTests(unittest.TestCase):
    """! @brief 실제 설계와 회로 모델에서 후보 불변성과 의미 경계를 확인한다."""

    def setUp(self):
        """! @brief 각 시험은 독립 UUID와 원문 사본으로 수행한다."""
        self.document, self.ids = fixture()

    def test_cartesian_order_duplicates_and_lazy_generation(self):
        """! @brief 조합을 저장하지 않고 마지막 축부터 증가하며 중복 입력은 별도 ordinal로 남긴다."""
        raw = definition([axis(self.ids[0], [typed("1"), typed("1000", "um")]),
                          axis(self.ids[1], [typed("1"), typed("2")])])
        before = canonical_bytes(raw)
        with patch("rfad.domain.design_sweep.candidate_at", side_effect=AssertionError("eager generation")):
            normalized = validate_specification(raw, self.document)
            self.assertEqual(candidate_count(normalized), 4)
        candidates = [candidate_at(self.document, normalized, index) for index in range(4)]
        self.assertEqual([row["indices"] for row in candidates], [[0, 0], [0, 1], [1, 0], [1, 1]])
        self.assertEqual(candidates[0]["evaluation_key"], candidates[2]["evaluation_key"])
        self.assertNotEqual(candidates[0]["document"]["revision_id"], candidates[2]["document"]["revision_id"])
        self.assertEqual(canonical_bytes(raw), before)

    def test_paired_and_explicit_rows_preserve_order_and_repeats(self):
        """! @brief paired에 숨은 broadcast를 두지 않고 명시한 행 중복도 유지한다."""
        raw = definition([axis(self.ids[0], [quantity(1), quantity(2)]), axis(self.ids[1], [quantity(2), quantity(1)])], combination="paired")
        normalized = validate_specification(raw, self.document)
        self.assertEqual(candidate_at(self.document, normalized, 1)["indices"], [1, 1])
        raw["variables"][1]["values"].pop()
        with self.assertRaises(ProjectError):
            validate_specification(raw, self.document)
        raw["combination"], raw["rows"] = "explicit_rows", [[1, 0], [0, 0], [1, 0]]
        normalized = validate_specification(raw, self.document)
        self.assertEqual(candidate_count(normalized), 3)
        self.assertEqual([candidate_at(self.document, normalized, i)["indices"] for i in range(3)], raw["rows"])
        self.assertEqual(candidate_at(self.document, normalized, 0)["evaluation_key"], candidate_at(self.document, normalized, 2)["evaluation_key"])
        raw["rows"][0][0] = True
        with self.assertRaises(ProjectError):
            validate_specification(raw, self.document)

    def test_range_endpoints_sources_and_decreasing_order(self):
        """! @brief 범위의 양끝 원문 단위/출처와 사용자 지정 감소 방향을 보존한다."""
        raw = definition([{"kind": "parameter", "id": self.ids[0], "dimension": "length",
                           "range": {"start": typed("3"), "stop": quantity(1000, "um", ["test:endpoint"]), "count": 3}}])
        before = deepcopy(raw)
        normalized = validate_specification(raw, self.document)
        values = normalized["variables"][0]["values"]
        self.assertEqual([row["value_si"] for row in values], [0.003, 0.002, 0.001])
        self.assertEqual(values[-1], raw["variables"][0]["range"]["stop"])
        self.assertEqual(values[1]["source_refs"], ["test:사용자 입력", "test:endpoint"])
        self.assertEqual(before, raw)
        self.assertNotIn("range", normalized["variables"][0])

    def test_deterministic_revision_original_unknowns_and_metadata(self):
        """! @brief 다른 내용의 후보에는 별도 개정을 부여하고 원문 시간/미정 물성은 그대로 둔다."""
        raw = definition([axis(self.ids[0], [quantity(1), quantity(2)])])
        before_document, before_raw = canonical_bytes(self.document), canonical_bytes(raw)
        normalized = validate_specification(raw, self.document)
        first = candidate_at(self.document, normalized, 0)
        repeated = candidate_at(self.document, normalized, 0)
        self.assertEqual(first, repeated)
        self.assertNotEqual(first["document"]["revision_id"], self.document["revision_id"])
        self.assertEqual(first["document"]["parent_revision_ids"], [self.document["revision_id"]])
        self.assertEqual(first["document"]["metadata"], self.document["metadata"])
        self.assertEqual(first["document"]["materials"], self.document["materials"])
        self.assertEqual(first["document"]["extensions"], self.document["extensions"])
        self.assertTrue(any(row["epsilon_r"]["value_si"] is None for row in first["document"]["materials"]))
        self.assertEqual(canonical_bytes(self.document), before_document)
        self.assertEqual(canonical_bytes(raw), before_raw)
        self.assertTrue(any(row["severity"] == "warning" for row in first["diagnostics"]))

    def test_batch_dag_update_precedes_geometry_validation(self):
        """! @brief 중간 적용만 음수가 되는 두 축을 한 번에 변경한 다음 표현식 그래프를 갱신한다."""
        a, b = self.ids
        self.document["parameters"][a]["quantity"] = quantity(2)
        derived = str(uuid4())
        self.document["parameters"][derived] = {"id": derived, "name": "차이", "quantity": quantity(1),
                                                "expression": expression_record("a-b", {"a": a, "b": b})}
        self.document["geometry"][0]["width"] = {"parameter_id": derived}
        evaluate_parameters(self.document["parameters"], update=True)
        raw = definition([axis(a, [quantity(0.5)]), axis(b, [quantity(0.25)])])
        normalized = validate_specification(raw, self.document)
        with patch("rfad.domain.design_sweep.evaluate_parameters", wraps=evaluate_parameters) as update:
            result = candidate_at(self.document, normalized, 0)
        self.assertEqual(result["status"], "valid", result["diagnostics"])
        self.assertEqual(result["document"]["parameters"][derived]["quantity"]["value_si"], 0.00025)
        self.assertEqual(update.call_count, 1)
        self.assertTrue(update.call_args.kwargs["update"])
        self.assertEqual(self.document["parameters"][derived]["quantity"]["value_si"], 0.001)
        descriptor = next(row for row in context_variables(self.document) if row["id"] == derived)
        self.assertTrue(descriptor["read_only"])
        with self.assertRaises(ProjectError):
            validate_specification(definition([axis(derived, [quantity(2)])]), self.document)

    def test_invalid_geometry_retains_candidate_without_mutating_next(self):
        """! @brief 음수 선폭은 해당 후보만 무효이며 다음 후보와 기준 원본에 번지지 않는다."""
        raw = definition([axis(self.ids[0], [quantity(-1), quantity(1)])])
        normalized = validate_specification(raw, self.document)
        before = canonical_hash(self.document)
        bad, good = (candidate_at(self.document, normalized, i) for i in (0, 1))
        self.assertEqual(bad["status"], "invalid")
        self.assertIsNone(bad["evaluation_key"])
        self.assertEqual(bad["values"][0]["value"]["value_si"], -0.001)
        self.assertEqual(good["status"], "valid")
        self.assertEqual(canonical_hash(self.document), before)

    def test_missing_parameter_and_missing_settings_remain_explicit(self):
        """! @brief 미정 수량을 0으로 채우지 않고 실행 설정의 부재도 지원 상태와 구분한다."""
        raw = definition([axis(self.ids[0], [Quantity.missing("length", "mm").to_dict()])])
        normalized = validate_specification(raw, self.document)
        result = candidate_at(self.document, normalized, 0)
        self.assertIsNone(result["document"]["parameters"][self.ids[0]]["quantity"]["value_si"])
        raw["settings"] = None
        result = candidate_at(self.document, validate_specification(raw, self.document), 0)
        self.assertEqual(result["status"], "unsupported")
        self.assertIsNone(result["settings"])

    def test_evaluation_key_ignores_presentation_but_preserves_physics(self):
        """! @brief SI 동치/이름/출처는 재사용하고 실제 물성 변경은 재사용하지 않는다."""
        raw = definition([axis(self.ids[0], [quantity(1, "mm", ["test:first"]), quantity(0.001, "m", ["test:second"])])])
        normalized = validate_specification(raw, self.document)
        first = candidate_at(self.document, normalized, 0)
        self.assertEqual(first["evaluation_key"], candidate_at(self.document, normalized, 1)["evaluation_key"])
        renamed = deepcopy(self.document)
        renamed["metadata"]["name"] = "다른 표시명"
        renamed["parameters"][self.ids[0]]["name"] = "읽기 쉬운 이름"
        self.assertEqual(first["evaluation_key"], candidate_at(renamed, normalized, 0)["evaluation_key"])
        changed = deepcopy(self.document)
        dielectric = next(row for row in changed["materials"] if row["id"] == changed["stackup"][0]["material_id"])
        dielectric["epsilon_r"] = quantity(2.3, "1")
        self.assertNotEqual(first["evaluation_key"], candidate_at(changed, normalized, 0)["evaluation_key"])

    def test_numerical_inputs_are_converted_in_service_and_integers_are_strict(self):
        """! @brief GHz/mm 입력 환산과 정수 설정 실패를 구분하고 수치 축마다 원본을 복제한다."""
        raw = definition([axis("frequency_hz.count", [typed("31", "1"), typed("31.5", "1")], "solver_setting", "dimensionless")], kind="numerical_study")
        raw["settings_inputs"] = {"frequency_hz.start": typed("8", "GHz"), "frequency_hz.stop": typed("12", "GHz"), "grid_mm": typed("500", "um")}
        before = canonical_bytes(raw)
        normalized = validate_specification(raw, self.document)
        self.assertNotIn("settings_inputs", normalized)
        self.assertEqual(normalized["settings"]["frequency_hz"]["start"], 8e9)
        self.assertEqual(normalized["settings"]["grid_mm"], 0.5)
        self.assertEqual(candidate_at(self.document, normalized, 0)["status"], "valid")
        self.assertEqual(candidate_at(self.document, normalized, 1)["status"], "invalid")
        self.assertEqual(canonical_bytes(raw), before)
        self.assertTrue(next(row for row in numerical_fields() if row["id"] == "frequency_hz.count")["integer"])

    def test_numerical_invalid_joint_geometry_is_candidate_failure(self):
        """! @brief 공기 여백/격자 결합 조건을 정의 전체 거절 대신 해당 후보 실패로 보존한다."""
        raw = definition([axis("grid_mm", [quantity(0.5), quantity(1)], "solver_setting")], kind="numerical_study")
        normalized = validate_specification(raw, self.document)
        self.assertEqual(candidate_at(self.document, normalized, 0)["status"], "valid")
        self.assertEqual(candidate_at(self.document, normalized, 1)["status"], "invalid")
        self.assertEqual(normalized["settings"]["grid_mm"], 0.5)

    def test_explicit_radiation_frequencies_are_fixed_conditions_not_an_axis(self):
        """! @brief 선택 기록 주파수의 단위만 환산하고 임의 방사 설정을 생성하지 않는다."""
        settings = deepcopy(SETTINGS)
        settings["radiation"] = {"frequency_hz": [10e9], "theta_step_deg": 15, "phi_step_deg": 15}
        inputs = {"radiation.frequency_hz": [typed("8", "GHz"), typed("10000", "MHz"), typed("12", "GHz")]}
        normalized = normalize_settings(settings, inputs)
        self.assertEqual(normalized["radiation"]["frequency_hz"], [8e9, 10e9, 12e9])
        self.assertEqual(settings["radiation"]["frequency_hz"], [10e9])
        self.assertNotIn("radiation.frequency_hz", [row["id"] for row in numerical_fields()])
        with self.assertRaises(ProjectError):
            normalize_settings(SETTINGS, inputs)
        with self.assertRaises(ProjectError):
            normalize_settings(settings, {"radiation.frequency_hz": [typed("8", "GHz")] * 4})

    def test_circuit_values_and_states_preserve_source_and_no_em_settings(self):
        """! @brief 외부 이상 소자 값/상태 조합은 EM 원본과 미정 기준면을 바꾸지 않는다."""
        original = circuit(component())
        original["input_reference_plane"] = None
        element = original["elements"][0]["id"]
        raw = definition([axis(element, [typed("50", "ohm"), typed("0.05", "kohm")], "circuit_value", "impedance"),
                          axis(element, ["connected", "open", "dnp"], "circuit_state", "state")], kind="circuit_sweep")
        before = deepcopy(original)
        normalized = validate_specification(raw, self.document, original)
        self.assertEqual(candidate_count(normalized), 6)
        first = candidate_at(self.document, normalized, 0, original)
        duplicate = candidate_at(self.document, normalized, 3, original)
        opened = candidate_at(self.document, normalized, 1, original)
        self.assertEqual(first["evaluation_key"], duplicate["evaluation_key"])
        self.assertNotEqual(first["evaluation_key"], opened["evaluation_key"])
        self.assertEqual(opened["circuit"]["elements"][0]["state"], "open")
        self.assertIsNone(opened["circuit"]["input_reference_plane"])
        self.assertEqual(opened["document"]["geometry"], self.document["geometry"])
        self.assertIsNone(opened["settings"])
        self.assertEqual(original, before)

    def test_budget_inputs_preserve_raw_and_exact_bytes(self):
        """! @brief 사용자 시간/메모리 표시만 환산하며 원문이나 기준 예산은 변경하지 않는다."""
        raw = definition([axis(self.ids[0], [quantity(1)])])
        raw["budget_inputs"] = {"wall_seconds": {"text": "1.5", "unit": "min"},
                                "ram_bytes": {"text": "1.5", "unit": "GiB"}, "disk_bytes": {"text": "512", "unit": "MiB"}}
        before = deepcopy(raw)
        normalized = validate_specification(raw, self.document)
        self.assertEqual(normalized["budget"]["wall_seconds"], 90)
        self.assertEqual(normalized["budget"]["ram_bytes"], 1610612736)
        self.assertEqual(normalized["budget"]["disk_bytes"], 536870912)
        self.assertNotIn("budget_inputs", normalized)
        self.assertEqual(before, raw)
        with self.assertRaises(ProjectError):
            normalize_budget(raw["budget"], {"ram_bytes": {"text": "0.00000001", "unit": "MiB"}})
        with self.assertRaises(ProjectError):
            normalize_budget(raw["budget"], {"ram_bytes": {"text": "0.000976562500000000000000000000000000000000001", "unit": "GiB"}})

    def test_target_context_is_explicit_and_external_port_is_not_project_port(self):
        """! @brief 목표 포트 대응은 검증하고 자료 포트/미정 기준면은 명시 원문 그대로 둔다."""
        goal = target(frequencies=(8e9, 10e9, 12e9))
        goal["port_id"] = self.document["ports"][0]["id"]
        self.document["targets"].append(goal)
        raw = definition([axis(self.ids[0], [quantity(1)])])
        raw["target_ids"] = [goal["id"]]
        external_port = str(uuid4())
        raw["target_contexts"] = [{"target_id": goal["id"], "context": {"port_id": external_port,
                                   "target_port_id": goal["port_id"], "reference_plane": None, "frequency_policy": "exact_only"}}]
        normalized = validate_specification(raw, self.document)
        self.assertEqual(normalized["target_contexts"], raw["target_contexts"])
        self.assertIsNone(normalized["target_contexts"][0]["context"]["reference_plane"])
        raw["target_contexts"][0]["context"]["target_port_id"] = str(uuid4())
        with self.assertRaises(ProjectError):
            validate_specification(raw, self.document)
        raw.pop("target_contexts")
        self.assertEqual(validate_specification(raw, self.document)["target_contexts"], [])

    def test_confirmed_board_containment_failure_is_invalid_candidate(self):
        """! @brief 수량 자체가 양수여도 실제 기판 밖 도체가 되는 후보는 무효로 기록한다."""
        identity = str(uuid4())
        self.document["parameters"][identity] = {"id": identity, "name": "기판 폭", "quantity": quantity(16)}
        self.document["board"]["outline"]["width"] = {"parameter_id": identity}
        raw = definition([axis(identity, [quantity(16), quantity(2)])])
        normalized = validate_specification(raw, self.document)
        good, bad = (candidate_at(self.document, normalized, index) for index in (0, 1))
        self.assertEqual(good["status"], "valid")
        self.assertEqual(bad["status"], "invalid")
        self.assertTrue(any(row["code"] == "E_DESIGN_CONSTRAINT" for row in bad["diagnostics"]))
        self.assertIsNone(bad["evaluation_key"])

    def test_unknown_extension_and_mixed_source_quantities_are_not_deleted(self):
        """! @brief 미지 확장/자료 출처/미정 수량은 후보 사본에 남고 solver 허용을 주장하지 않는다."""
        self.document["extensions"]["vendor.future"] = {"fabrication": None, "values": [1, 2], "source": "원문"}
        raw = definition([axis(self.ids[0], [{**quantity(1), "status": "estimated"}])])
        normalized = validate_specification(raw, self.document)
        candidate = candidate_at(self.document, normalized, 0)
        self.assertEqual(candidate["document"]["extensions"], self.document["extensions"])
        self.assertEqual(candidate["document"]["parameters"][self.ids[0]]["quantity"]["status"], "estimated")
        changed = deepcopy(self.document)
        changed["extensions"]["vendor.future"]["values"] = [2, 3]
        self.assertNotEqual(candidate["evaluation_key"], candidate_at(changed, normalized, 0)["evaluation_key"])
        self.assertNotIn("solver_ready", candidate)
        self.assertNotIn("physics_validated", candidate)

    def test_integer_and_float_solver_representations_have_equal_evaluation_keys(self):
        """! @brief 같은 Hz 설정을 정수 또는 실수로 입력한 차이만으로 중복 계산하지 않는다."""
        raw = definition([axis(self.ids[0], [quantity(1)])])
        raw["settings"]["frequency_hz"]["start"] = 8000000000
        integer = candidate_at(self.document, validate_specification(raw, self.document), 0)
        raw["settings_inputs"] = {"frequency_hz.start": typed("8", "GHz")}
        floating = candidate_at(self.document, validate_specification(raw, self.document), 0)
        self.assertEqual(integer["evaluation_key"], floating["evaluation_key"])

    def test_range_does_not_turn_tiny_nonzero_values_into_zero(self):
        """! @brief 부동 소수 중간 연산 때문에 같은 최소 양수가 0으로 소실되지 않는다."""
        smallest = math.ulp(0.0)
        raw = definition([{"kind": "parameter", "id": self.ids[0], "dimension": "length",
                           "range": {"start": quantity(smallest, "m"), "stop": quantity(smallest, "m"), "count": 3}}])
        values = validate_specification(raw, self.document)["variables"][0]["values"]
        self.assertEqual([value["value_si"] for value in values], [smallest] * 3)
        raw["variables"][0]["range"]["stop"] = quantity(0, "m")
        with self.assertRaises(ProjectError):
            validate_specification(raw, self.document)

    def test_range_source_union_is_bounded_without_discarding_evidence(self):
        """! @brief 양끝 출처의 합집합이 넘치면 정규화 단계에서 거부하며 출처를 잘라내지 않는다."""
        raw = definition([{"kind": "parameter", "id": self.ids[0], "dimension": "length",
                           "range": {"start": quantity(1, sources=["a" + str(i) for i in range(128)]),
                                     "stop": quantity(2, sources=["b" + str(i) for i in range(128)]), "count": 3}}])
        before = canonical_bytes(raw)
        with self.assertRaises(ProjectError) as caught:
            validate_specification(raw, self.document)
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        self.assertEqual(canonical_bytes(raw), before)
        raw["variables"][0]["range"]["count"] = 2
        normalized = validate_specification(raw, self.document)
        self.assertEqual([len(row["source_refs"]) for row in normalized["variables"][0]["values"]], [128, 128])

    def test_invalid_range_and_resource_contracts_are_not_silently_clamped(self):
        """! @brief 범위/예산 오류를 명시적으로 거부하며 값 목록이나 예산을 잘라내지 않는다."""
        raw = definition([axis(self.ids[0], [quantity(1), quantity(2)])])
        for key, value in (("max_candidates", 1), ("max_candidates", 129), ("max_native_solves", True),
                           ("wall_seconds", 0), ("ram_bytes", 1.5), ("concurrency", 2)):
            with self.subTest(key=key, value=value):
                changed = deepcopy(raw)
                changed["budget"][key] = value
                with self.assertRaises(ProjectError):
                    validate_specification(changed, self.document)
        raw["variables"][0].pop("values")
        raw["variables"][0]["range"] = {"start": quantity(1), "stop": quantity(2), "count": 129}
        with self.assertRaises(ProjectError):
            validate_specification(raw, self.document)

    def test_cartesian_budget_and_kind_mixing_are_rejected_before_generation(self):
        """! @brief 큰 곱/중복 축/연구 종류 혼합을 계획 및 작업 생성 전에 차단한다."""
        raw = definition([axis(self.ids[0], [quantity(1)] * 16), axis(self.ids[1], [quantity(1)] * 16)])
        with self.assertRaises(ProjectError) as caught:
            validate_specification(raw, self.document)
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        raw["variables"] = [axis(self.ids[0], [quantity(1)]), axis("grid_mm", [quantity(1)], "solver_setting")]
        with self.assertRaises(ProjectError) as caught:
            validate_specification(raw, self.document)
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
        raw["variables"] = [axis(self.ids[0], [quantity(1)])] * 2
        with self.assertRaises(ProjectError):
            validate_specification(raw, self.document)

    def test_malformed_nonfinite_underflow_and_unknown_fields_fail_closed(self):
        """! @brief JSON 타입/비유한/수치 소실/미지 입력을 임의 교정하지 않는다."""
        raw = definition([axis(self.ids[0], [quantity(1)])])
        for key, value in (("schema", "future"), ("type", []), ("extra", 1), ("combination", {})):
            with self.subTest(key=key):
                changed = deepcopy(raw)
                changed[key] = value
                with self.assertRaises(ProjectError):
                    validate_specification(changed, self.document)
        for value in (typed("NaN"), typed("1e-999"), typed("1e999"), {**quantity(1), "value_si": math.inf}, {**quantity(1), "value_si": True}):
            with self.subTest(value=value):
                with self.assertRaises(ProjectError):
                    input_quantity(value, "length", "test")
        with self.assertRaises(ProjectError):
            normalize_settings(SETTINGS, {"arbitrary.path": typed("1")})


if __name__ == "__main__":
    unittest.main()
