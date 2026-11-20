"""! @brief 측정 기록의 미정/출처/불확도와 자기 참조 없는 영구 색인을 검증한다."""

from copy import deepcopy
import hashlib
import unittest
from uuid import UUID

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain import measurement as model
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import make_dataset


def identity(number):
    """! @brief 시험에서만 고정 ID를 발급한다."""
    return str(UUID(int=number))


def network():
    """! @brief 측정 성공을 가장하지 않는 비상호 2포트 독립 수치 입력이다."""
    return make_dataset(parameter_kind="S", frequency_hz=[1e9, 3e9], port_ids=[identity(1), identity(2)],
                        values_ri=[[[[0.1, -0.2], [0.2, 0.3]], [[0.7, -0.1], [0.4, 0.0]]],
                                   [[[0.3, 0.2], [0.4, -0.3]], [[0.5, 0.1], [0.2, 0.4]]]],
                        z0_ohm=[[[50.0, 0.0], [75.0, 0.0]], [[50.0, 0.0], [75.0, 0.0]]],
                        port_names=["입력 원문", None], reference_planes=["A 접속면", "B 접속면"],
                        wave_definition="traveling", phasor_convention="exp(+j*omega*t)",
                        port_modes=["single_ended", "single_ended"], current_orientation=["into_dut", "into_dut"],
                        sample_origin=["imported", "unknown"], source_refs=["fixture:not-measured"],
                        conditions={"measurement": None, "fabrication": {"value": None}, "original_ports": ["A", "B"]},
                        provenance={"original_comment": "장비/시료/교정은 미확정", "raw_sha256": "b" * 64})


def artifact(value=b"raw", name="source.json"):
    """! @brief 원문 파일을 쓰지 않고 실제 바이트 hash를 가진 참조를 만든다."""
    return {"uri": "projects/fixture/measurement/" + name, "sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}


def record(data=None, number=10, pinned=False):
    """! @brief 식별자와 UTC만 명시하고 실물 조건은 모두 null로 둔다."""
    data = network() if data is None else data
    anchor = {"kind": "network_artifact", "project_id": identity(100), "dataset_id": identity(101),
              "dataset": artifact(canonical_bytes(data), "dataset.json"), "raw": artifact(b"exact raw"),
              "normalized_hdf5": artifact(b"preserved HDF5", "normalized.h5")}
    if pinned:
        anchor = {"kind": "pinned_result", "source": {"kind": "network", "dataset_id": identity(101),
                  "revision_id": identity(102), "snapshot_id": None},
                  "pin": {"identity_hash": "c" * 64, "dataset_sha256": canonical_hash(data)}}
    return model.record_template(identity=identity(number), name="측정 원문 기록", data_anchor=anchor,
                                 created_at_utc="2026-11-17T00:00:00Z", reason="미정 그대로 보존")


def leaf(value, evidence="declared"):
    """! @brief 제출 사실과 계획을 구분하는 원문 leaf를 만든다."""
    return {"value": value, "evidence": evidence, "source_refs": ["fixture:submitted"]}


def uncertainty():
    """! @brief k와 상관이 없는 확장 불확도를 임의 완성하지 않는 입력이다."""
    return {"id": identity(50), "measurand": {"parameter_kind": "S", "row_port_id": identity(1),
            "column_port_id": identity(2), "representation": "magnitude_db"},
            "scope": {"frequency_range_hz": [1e9, 3e9], "sample_indices": None},
            "form": "expanded", "scale": "absolute", "value": {"number": 0.2, "unit": "dB"},
            "coverage_factor": None, "coverage_probability": None, "distribution": None,
            "estimation": "unspecified", "degrees_of_freedom": None,
            "correlation": {"state": "unknown", "reference": None}, "method": None,
            "repetitions": None, "source_refs": ["fixture:uncertainty"]}


def indexed(value):
    """! @brief application이 봉인할 원문 artifact와 작은 색인 참조를 연결한다."""
    return {"id": value["id"], "name": value["name"], "artifact": artifact(canonical_bytes(value), value["id"] + ".json"),
            "previous_record_id": value["previous_record_id"]}


class MeasurementTests(unittest.TestCase):
    """! @brief 순수 기록 조회가 기존 복소 원문/미정/과거 평가를 바꾸지 않음을 검사한다."""

    def test_unknown_record_and_dataset_remain_byte_identical(self):
        """! @brief null과 제출 분류는 원문에 남고 검증 합격으로 승격하지 않는다."""
        data, value = network(), record()
        before = canonical_bytes([data, value])
        for classification in ("measurement", "synthetic_fixture", "unknown"):
            candidate = deepcopy(value)
            candidate["data_class"] = classification
            assessment = model.condition_assessment(candidate, data)
            self.assertEqual(assessment["status"], "incomplete")
            self.assertFalse(assessment["measurement_validated"])
            self.assertEqual(assessment["physical_acceptance"], "not_established")
            self.assertIn("missing_uncertainty", [item["code"] for item in assessment["diagnostics"]])
        self.assertEqual(canonical_bytes([data, value]), before)

    def test_artifact_anchor_and_existing_pin_use_different_hash_contracts(self):
        """! @brief 새 파일 hash와 기존 결과 canonical pin을 혼동하거나 미래 문서 pin을 넣지 않는다."""
        data = network()
        for pinned in (False, True):
            value = record(data, pinned=pinned)
            model.validate_record(value, data, identity(100))
            bad = deepcopy(value)
            bad["data_anchor"]["future_revision_pin"] = {"identity_hash": "a" * 64}
            with self.assertRaises(ProjectError):
                model.validate_record(bad, data)
            corrupted = deepcopy(data)
            corrupted["conditions"]["measurement"] = "different"
            with self.assertRaises(ProjectError) as raised:
                model.validate_record(value, corrupted)
            self.assertEqual(raised.exception.code, "E_HASH")
        with self.assertRaises(ProjectError):
            model.validate_record(record(), data, identity(999))

    def test_calibration_port_band_and_plane_mismatch_stays_recorded(self):
        """! @brief 외부 포트는 거절하고 교정 밖 대역과 다른 기준면은 명시 진단한다."""
        value, data = record(), network()
        value["calibration"]["port_ids"] = leaf([identity(1)])
        value["calibration"]["frequency_range_hz"] = leaf([1.5e9, 2.5e9])
        value["calibration"]["reference_planes"] = leaf([{"port_id": identity(1), "reference_plane": "다른 면"}])
        before = canonical_bytes(value)
        result = model.condition_assessment(value, data)
        self.assertEqual(result["status"], "incompatible_scope")
        self.assertTrue({"uncovered_ports", "outside_calibration", "plane_mismatch"}.issubset({x["code"] for x in result["diagnostics"]}))
        self.assertEqual(canonical_bytes(value), before)
        value["calibration"]["port_ids"] = leaf([identity(999)])
        with self.assertRaises(ProjectError):
            model.validate_record(value, data)

    def test_planned_time_and_nullable_sections_are_not_performed_facts(self):
        """! @brief PC 시간대를 만들지 않고 null 묶음과 계획 근거를 각각 보존한다."""
        value = record()
        value["environment"] = None
        value["acquisition"]["measured_at"] = leaf("2026-11-17T12:00:00", "planned")
        diagnostics = model.validate_record(value)
        self.assertTrue({"timezone_missing", "planned_only"}.issubset({x["code"] for x in diagnostics}))
        self.assertIsNone(value["environment"])
        value["acquisition"]["instrument"] = leaf("없는 장비", "unknown")
        with self.assertRaises(ProjectError):
            model.validate_record(value)

    def test_actual_units_counts_and_port_plane_shape_are_strict(self):
        """! @brief 음수 전력/온도/습도 정의역과 bool 횟수 및 잘못된 단위를 차단한다."""
        invalid = [("acquisition", "averages", True), ("acquisition", "if_bandwidth_hz", 0),
                   ("acquisition", "stimulus_power", {"number": -1, "unit": "W"}),
                   ("environment", "temperature", {"number": -1, "unit": "K"}),
                   ("environment", "humidity", {"number": 101, "unit": "%"}),
                   ("calibration", "frequency_range_hz", [2, 1])]
        for section, field, item in invalid:
            with self.subTest(field=field):
                value = record()
                value[section][field] = leaf(item)
                with self.assertRaises(ProjectError):
                    model.validate_record(value, network())
        value = record()
        value["acquisition"]["stimulus_power"] = leaf({"number": -30, "unit": "dBm"})
        model.validate_record(value)

    def test_uncertainty_missing_k_and_correlation_remain_incomplete(self):
        """! @brief dB를 선형 수량으로 치환하거나 k=2/독립 상관을 생성하지 않는다."""
        row = uncertainty()
        before = canonical_bytes(row)
        self.assertEqual(model.validate_uncertainty(row, network())[0]["code"], "incomplete_uncertainty")
        self.assertEqual(canonical_bytes(row), before)
        self.assertIsNone(row["coverage_factor"])
        row["value"]["unit"] = "1"
        with self.assertRaises(ProjectError) as raised:
            model.validate_uncertainty(row, network())
        self.assertEqual(raised.exception.code, "E_UNIT")

    def test_uncertainty_scope_definition_and_nonfinite_boundaries(self):
        """! @brief 표본 범위/포함 계수/자유도와 유한 입력을 독립적으로 거절한다."""
        for key, item in (("coverage_factor", 0), ("coverage_probability", 1), ("degrees_of_freedom", -1),
                          ("repetitions", True), ("value", {"number": float("nan"), "unit": "dB"})):
            with self.subTest(key=key):
                row = uncertainty()
                row[key] = item
                with self.assertRaises(ProjectError):
                    model.validate_uncertainty(row, network())
        for indices in ([True], [0, 0], [2]):
            row = uncertainty()
            row["scope"]["sample_indices"] = indices
            with self.assertRaises(ProjectError):
                model.validate_uncertainty(row, network())
        row = uncertainty()
        row["scope"] = {"frequency_range_hz": [1e9, 2e9], "sample_indices": [1]}
        with self.assertRaises(ProjectError):
            model.validate_uncertainty(row, network())

    def test_same_values_with_different_evidence_and_nulls_are_not_equal_context(self):
        """! @brief 같은 문자열의 계획/보고 근거 차이와 두 null을 비교 조건에 남긴다."""
        first, second = record(), record(number=11)
        first["specimen"]["identifier"] = leaf("시료 A", "planned")
        second["specimen"]["identifier"] = leaf("시료 A", "reported")
        result = model.condition_assessment(first, network(), comparison_record=second)
        rows = {row["field_path"]: row for row in result["condition_differences"]}
        self.assertEqual(rows["specimen.identifier"]["state"], "different")
        self.assertEqual(rows["specimen.serial"]["state"], "unknown")

    def test_attachment_descriptor_and_external_processing_preserve_original_order(self):
        """! @brief 첨부명은 원문이고 저장 경로와 외부 보정 실행 여부는 별도다."""
        value = record()
        value["attachments"] = [{"id": identity(60), "name": "교정 성적서.pdf", "role": "calibration",
                                 "media_type": "application/pdf", "artifact": artifact(b"original", "source.bin")}]
        value["external_processing"] = [{"name": "제출된 보정", "tool": None, "version": None, "input_anchor": None,
                                         "output_anchor": None, "order": 0, "reference_plane_before": None,
                                         "reference_plane_after": None, "uncertainty_notes": None, "source_refs": []}]
        before = canonical_bytes(value)
        result = model.condition_assessment(value, network())
        self.assertFalse(result["external_processing_reproduced"])
        self.assertEqual(canonical_bytes(value), before)
        value["attachments"].append(deepcopy(value["attachments"][0]))
        with self.assertRaises(ProjectError):
            model.validate_record(value)

    def test_registry_past_record_chain_and_absent_inverse_are_exact(self):
        """! @brief 한 명령의 undo/redo는 파일/현재 해석 없이 이전 absent까지 복원한다."""
        value = model.empty_registry()
        first, second = record(), record(number=11)
        second["previous_record_id"] = first["id"]
        value["records"] = [indexed(first), indexed(second)]
        document = {"extensions": {"custom": {"missing": None}}, "existing_result": {"status": "conditional"}}
        before = deepcopy(document)
        command = {"expected_hash": canonical_hash(None), "replacement": value}
        _, _, inverse = model.apply_measurement_command(document, command)
        after = deepcopy(document)
        _, _, redo = model.apply_measurement_command(document, inverse["payload"])
        self.assertEqual(document, before)
        model.apply_measurement_command(document, redo["payload"])
        self.assertEqual(document, after)
        with self.assertRaises(ProjectError):
            model.apply_measurement_command(document, command)
        self.assertEqual(document, after)

    def test_registry_cycle_fork_foreign_previous_and_limits_reject_without_mutation(self):
        """! @brief 과거 색인을 지워 상한을 우회하지 않고 잘못된 사슬을 거절한다."""
        base = model.empty_registry()
        first, second = record(), record(number=11)
        second["previous_record_id"] = first["id"]
        base["records"] = [indexed(first), indexed(second)]
        for previous in (second["id"], identity(999)):
            bad = deepcopy(base)
            bad["records"][0]["previous_record_id"] = previous
            with self.assertRaises(ProjectError):
                model.validate_registry(bad)
        third = record(number=12)
        third["previous_record_id"] = first["id"]
        bad = deepcopy(base)
        bad["records"].append(indexed(third))
        with self.assertRaises(ProjectError):
            model.validate_registry(bad)
        bad = model.empty_registry()
        bad["records"] = [indexed(record(number=100 + i)) for i in range(33)]
        with self.assertRaises(ProjectError):
            model.validate_registry(bad)

    def test_json_bounds_and_unknown_fields_never_silently_drop_original(self):
        """! @brief extra 상한/비유한/미지원 키를 원문을 잘라내지 않고 거절한다."""
        for extra in ({"raw": ["x" * 4096] * 5}, {"value": float("inf")}):
            value = record()
            value["extra"] = extra
            with self.assertRaises(ProjectError):
                model.validate_record(value)
        value = record()
        value["new_implicit_condition"] = 50
        with self.assertRaises(ProjectError):
            model.validate_record(value)

    def test_registry_artifact_caps_are_per_kind_not_metadata_only(self):
        """! @brief 비교 표본 보고서의 유한 1 MiB와 작은 기록/정렬 상한을 구분한다."""
        value = model.empty_registry()
        for number, collection in enumerate(("records", "alignments", "comparisons"), 200):
            row = {"id": identity(number), "name": collection,
                   "artifact": {**artifact(), "bytes": model.ARTIFACT_LIMITS[collection]}}
            if collection == "records":
                row["previous_record_id"] = None
            value[collection].append(row)
        model.validate_registry(value)
        for collection in model.ARTIFACT_LIMITS:
            bad = deepcopy(value)
            bad[collection][0]["artifact"]["bytes"] += 1
            with self.assertRaises(ProjectError) as raised:
                model.validate_registry(bad)
            self.assertEqual(raised.exception.code, "E_RESOURCE")

    def test_malformed_metadata_produces_project_error_not_python_type_error(self):
        """! @brief 잘못된 배열/객체/nullable 입력도 정해진 계약 오류로 반환한다."""
        cases = [("data_class", []), ("created_at_utc", None), ("source_refs", {}), ("attachments", [None]),
                 ("calibration", []), ("previous_record_id", True), ("extra", []), ("data_anchor", []),
                 ("uncertainty", [None]), ("external_processing", [None])]
        for key, bad in cases:
            with self.subTest(key=key):
                value = record()
                value[key] = bad
                with self.assertRaises(ProjectError):
                    model.validate_record(value, network())
        cyclic = {}
        cyclic["self"] = cyclic
        value = record()
        value["extra"] = cyclic
        with self.assertRaises(ProjectError):
            model.validate_record(value)

    def test_complete_submitted_context_still_has_no_physical_acceptance(self):
        """! @brief 형식상 제출 근거가 완전해도 측정 합격/외부 보정 재현을 만들지 않는다."""
        value, data = record(), network()
        for section, field, item in (("specimen", "identifier", "시료 1"), ("acquisition", "instrument", "장비 1"),
                                     ("acquisition", "measured_at", "2026-11-17T01:00:00+09:00"),
                                     ("calibration", "method", "제출 교정법"), ("calibration", "port_ids", data["port_ids"]),
                                     ("calibration", "frequency_range_hz", [1e9, 3e9]), ("fixture", "mounting_notes", "제출 장착 기록"),
                                     ("calibration", "reference_planes", [{"port_id": p, "reference_plane": plane}
                                                                          for p, plane in zip(data["port_ids"], data["reference_planes"])])):
            value[section][field] = leaf(item, "reported")
        row = uncertainty()
        row["coverage_factor"] = 2.5
        row["correlation"] = {"state": "documented", "reference": artifact(b"correlation report")}
        value["uncertainty"] = [row]
        result = model.condition_assessment(value, data)
        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["measurement_validated"])
        self.assertEqual(result["physical_acceptance"], "not_established")
