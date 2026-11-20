"""! @brief 실제 저장소에서 측정 원문, 원자 명령, 과거 비교와 복구 경계를 검증한다."""

import base64
from copy import deepcopy
import hashlib
import json
from unittest.mock import patch
import unittest
from uuid import uuid4

from rfad.application import measurement_service, rpc
from rfad.application.canonical import canonical_bytes
from rfad.domain import measurement
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import KEY as NETWORK_KEY
import test_network_service as network_fixture
from test_network_service import import_parameters


class MeasurementServiceTests(unittest.TestCase):
    """! @brief 기존 프로젝트 시험 fixture만 재사용하고 측정 사용자 흐름을 검사한다."""

    setUp = network_fixture.NetworkServiceTests.setUp
    tearDown = network_fixture.NetworkServiceTests.tearDown
    request = network_fixture.NetworkServiceTests.request
    document = network_fixture.NetworkServiceTests.document
    history = network_fixture.NetworkServiceTests.history
    save_reopen = network_fixture.NetworkServiceTests.save_reopen

    def read(self, method, **values):
        """! @brief 고정 원본/개정이 명시된 측정 조회를 실행한다."""
        return measurement_service.read(self.service.host_calculation_context, method, self.request(values))

    def parameters(self, *, declared=True, count=3):
        """! @brief 가짜 시험 자료임을 명시하고 교정/제작/측정 조건은 채우지 않는다."""
        return {"network": import_parameters(declared=declared, count=count), "name": "시험 시료 기록",
                "changes": {"values": {"data_class": "synthetic_fixture", "source_refs": ["통합 시험 원문; 실측 아님"]},
                            "quantities": {}}, "reason": "기록과 원본 보존 시험"}

    def preview(self, operation, parameters):
        """! @brief 실제 초안 시각을 고정하고 검토가 journal을 바꾸지 않는지 확인한다."""
        data = {"expected_revision": self.revision, "draft_time_utc": "2026-11-17T00:00:00+00:00",
                "operation": operation, "parameters": parameters}
        before = self.service.journal.read()
        result = self.read("measurement.preview", **data)
        self.assertEqual(self.service.journal.read(), before)
        return data, result

    def apply(self, operation, parameters, *, reviewed=None):
        """! @brief 동일 검토와 영수증을 재전송해 명령이 한 번만 게시되는지 확인한다."""
        data, preview = self.preview(operation, parameters) if reviewed is None else reviewed
        self.assertTrue(preview["can_apply"], preview)
        request = self.request({**data, "review_hash": preview["review_hash"], "command_id": str(uuid4())}, mutation=True)
        response = self.service.mutate("measurement.apply", request)
        self.assertEqual(response, self.service.mutate("measurement.apply", request))
        self.revision = response["new_revision"]
        return response, request

    def selection(self, response):
        """! @brief 결과는 현재 alias 대신 측정 기록이 실제 고정한 source/pin으로 선택한다."""
        value = self.read("measurement.get", record=response["record_ref"])
        return {key: value[key] for key in ("source", "pin")} | {"record": response["record_ref"]}

    def comparison(self, left, right):
        """! @brief 한 포트 동일 주파수의 비교를 명시한다."""
        return {"left": left, "right": right, "right_port_order": [0], "row": 0, "column": 0,
                "frequency_policy": "exact_only"}

    def test_import_record_is_one_undo_and_original_bytes_survive_reopen(self):
        """! @brief 원문/기록 동시 적용과 undo/redo/재열기 후 미정/출처/기존 형상을 확인한다."""
        before = self.document()
        parameters = self.parameters(declared=False)
        response, _ = self.apply("import_record", parameters)
        record = self.read("measurement.get", record=response["record_ref"])
        raw_ref = record["record"]["data_anchor"]["raw"]
        self.assertEqual(self.service.journal.read_artifact(raw_ref), base64.b64decode(parameters["network"]["source_base64"]))
        self.assertIsNone(record["record"]["calibration"]["method"])
        self.assertIsNone(record["record"]["calibration"]["reference_planes"])
        self.assertIsNone(record["record"]["specimen"]["identifier"])
        self.assertEqual(record["descriptor"]["reference_planes"], [None])
        self.assertEqual(record["descriptor"]["conditions"], {"manufacturing": None, "measurement": None})
        self.assertFalse(record["context_assessment"]["measurement_validated"])
        self.assertIsNone(record["execution"])
        for key in ("board", "geometry", "materials", "ports", "targets", "parameters", "manufacturing_profiles"):
            self.assertEqual(self.document()[key], before[key])
        self.assertEqual(self.document()["extensions"]["test.source"], before["extensions"]["test.source"])
        self.history("undo")
        self.assertNotIn(measurement.KEY, self.document()["extensions"])
        self.assertNotIn(NETWORK_KEY, self.document()["extensions"])
        self.assertEqual(self.read("measurement.get", record=response["record_ref"])["record"], record["record"])
        self.history("redo")
        self.save_reopen()
        restored = self.read("measurement.get", record=response["record_ref"])
        self.assertEqual(restored["record"], record["record"])
        self.assertEqual(restored["pin"], record["pin"])

    def test_record_edit_preserves_previous_record_and_unit_input(self):
        """! @brief 수정은 새 기록을 만들고 이전 미정 원문과 수치 입력 근거를 유지한다."""
        first, _ = self.apply("import_record", self.parameters())
        selected = self.selection(first)
        original = self.read("measurement.get", record=first["record_ref"])
        parameters = {"source": selected["source"], "pin": selected["pin"], "previous_record": first["record_ref"],
            "name": "대역폭 입력 개정", "reason": "장비 설정의 제출 근거 추가",
            "changes": {"values": {}, "quantities": {"acquisition.if_bandwidth_hz":
                {"text": "10", "unit": "kHz", "evidence": "reported", "source_refs": ["시험용 설정 기록"]}}}}
        second, _ = self.apply("record", parameters)
        updated = self.read("measurement.get", record=second["record_ref"])
        self.assertEqual(updated["record"]["acquisition"]["if_bandwidth_hz"]["value"], 10000)
        self.assertEqual(updated["original_input"]["parameters"]["changes"], parameters["changes"])
        self.assertEqual(updated["record"]["previous_record_id"], first["record_id"])
        self.assertEqual(updated["record"]["calibration"], original["record"]["calibration"])
        self.assertEqual(self.read("measurement.get", record=first["record_ref"])["record"], original["record"])
        context = self.read("measurement.context", revision_id=None, offset=0, limit=32)
        self.assertEqual({row["record_ref"]["id"]: row["is_latest"] for row in context["items"]},
                         {first["record_id"]: False, second["record_id"]: True})

    def test_stale_review_and_internal_command_cannot_bypass_atomic_apply(self):
        """! @brief 검토 이후 변경과 내부 복합 명령의 직접 제출을 원본 변경 없이 막는다."""
        data, preview = self.preview("import_record", self.parameters())
        self.assertTrue(preview["can_apply"], preview)
        incomplete = self.parameters()
        del incomplete["network"]["source_base64"]
        _, rejected = self.preview("import_record", incomplete)
        self.assertFalse(rejected["can_apply"])
        self.assertEqual(rejected["issues"][0]["code"], "E_SCHEMA")
        data["parameters"]["name"] = "다른 기록"
        with self.assertRaises(ProjectError):
            self.service.mutate("measurement.apply", self.request({**data, "command_id": str(uuid4()),
                "review_hash": preview["review_hash"]}, mutation=True))
        for command in ("measurement.registry.replace", "measurement.workspace.replace"):
            with self.assertRaises(ProjectError):
                self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision,
                    "command_id": str(uuid4()), "type": command, "payload": {}}, mutation=True))
        self.assertNotIn(measurement.KEY, self.document()["extensions"])
        self.assertNotIn(NETWORK_KEY, self.document()["extensions"])

    def test_receipt_recovery_is_authoritative_and_never_infers_resubmission(self):
        """! @brief 적용 영수증과 미발견 상태를 구분하고 미발견을 미적용으로 해석하지 않는다."""
        response, request = self.apply("import_record", self.parameters())
        recovered = self.read("measurement.receipt", request_key=request["request_key"], request_key_epoch=request["request_key_epoch"])
        self.assertEqual(recovered["status"], "found")
        self.assertEqual(recovered["response"], response)
        missing = self.read("measurement.receipt", request_key=str(uuid4()), request_key_epoch=request["request_key_epoch"])
        self.assertEqual(missing["status"], "unresolved")
        self.assertFalse(missing["may_resubmit"])

    def test_large_attachment_rpc_raw_preservation_and_bounded_reads(self):
        """! @brief 512 KiB 원문은 전용 필드로만 받으며 청크 조회와 재열기 hash를 확인한다."""
        raw = bytes(range(256)) * 2048
        data = {"name": "교정 원문.bin", "role": "calibration", "media_type": "application/octet-stream",
                "content_base64": base64.b64encode(raw).decode("ascii"), "sha256": hashlib.sha256(raw).hexdigest()}
        result = rpc.handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": "measurement.attachment.add",
            "params": self.request(data, mutation=True)}), self.service)
        self.assertIn("result", result, str(result)[:1000])
        attachment = result["result"]
        self.assertEqual(self.document()["revision_id"], self.revision)
        pieces, offset = [], 0
        while offset is not None:
            page = self.read("measurement.attachment.read", attachment_id=attachment["attachment_id"], offset=offset, limit=128 * 1024)
            pieces.append(base64.b64decode(page["content_base64"]))
            offset = page["next_offset"]
        self.assertEqual(b"".join(pieces), raw)
        self.save_reopen()
        self.assertEqual(self.service.journal.read_artifact(attachment["artifact"]), raw)
        data["name"] = "x" * 8193
        invalid = rpc.handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 2, "method": "measurement.attachment.add",
            "params": self.request(data, mutation=True)}), self.service)
        self.assertIn("error", invalid)

    def test_full_journal_rejects_before_any_measurement_file_is_published(self):
        """! @brief 게시 전 실제 명령/역명령/응답의 journal 예산을 확인한다."""
        with patch.object(measurement_service, "MAX_STATE_BYTES", 1), patch.object(self.service.journal, "put_immutable") as write:
            _, preview = self.preview("import_record", self.parameters())
            self.assertFalse(preview["can_apply"])
            self.assertEqual(preview["issues"][0]["code"], "E_RESOURCE")
            write.assert_not_called()

    def test_comparison_preserves_unknown_conditions_and_full_historical_report(self):
        """! @brief 1001개 비교/전체 조건을 고정 저장하고 계산 불가 환경에서도 그대로 조회한다."""
        response, _ = self.apply("import_record", self.parameters(count=1001))
        selected = self.selection(response)
        parameters = {"name": "전체 표본의 고정 비교", "reason": "저장 보고서 재현 확인",
                      "comparison": self.comparison(selected, selected)}
        reviewed = self.preview("compare_record", parameters)
        _, preview = reviewed
        self.assertEqual(preview["comparison_preview"]["comparable_points"], 1001)
        self.assertEqual(len(preview["comparison_preview"]["points"]), 32)
        saved, _ = self.apply("compare_record", parameters, reviewed=reviewed)
        self.save_reopen()
        with patch.object(self.service.host_calculation_context, "calculate", side_effect=AssertionError("재계산 금지")):
            summary = self.read("measurement.history", collection="comparisons", record=saved["record_ref"],
                                section="summary", offset=0, limit=201)
            points, offset = [], 0
            while offset is not None:
                page = self.read("measurement.history", collection="comparisons", record=saved["record_ref"],
                                 section="points", offset=offset, limit=201)
                points.extend(page["items"])
                offset = page["next_offset"]
            conditions = self.read("measurement.history", collection="comparisons", record=saved["record_ref"],
                                   section="conditions", offset=0, limit=201)
        self.assertEqual(len(points), 1001)
        self.assertTrue(all(row["difference_ri"] == [0.0, 0.0] for row in points))
        self.assertGreater(conditions["total"], 32)
        self.assertEqual(len(conditions["items"]), 32)
        self.assertEqual(summary["comparison"]["measurement_context"]["physical_acceptance"], "not_established")
        self.assertFalse(summary["physics_validated"])
        self.assertFalse(self.read("measurement.get", record=response["record_ref"])["context_assessment"]["measurement_validated"])

    def test_alignment_preserves_original_samples_and_marks_interpolation(self):
        """! @brief GHz 입력의 RI 보간은 새 파생 자료에만 적용하고 원문/실행 근거를 보존한다."""
        response, _ = self.apply("import_record", self.parameters())
        selected = self.selection(response)
        original = self.read("measurement.get", record=response["record_ref"])
        parameters = {**selected, "name": "명시 보간 후보", "specification": {
            "schema": "rfad.measurement-alignment-input/0.1", "reason": "시험 주파수 정렬", "source_refs": ["선형 RI 가정"],
            "operations": [{"kind": "linear_ri", "frequencies": {"mode": "range", "start": {"text": "1", "unit": "GHz", "source_refs": []},
                "stop": {"text": "2", "unit": "GHz", "source_refs": []}, "count": 5},
                "max_gap": {"text": "500", "unit": "MHz", "source_refs": []}}]}}
        aligned, _ = self.apply("align", parameters)
        entry = next(row for row in self.document()["extensions"][NETWORK_KEY]["datasets"] if row["id"] == aligned["dataset_id"])
        dataset = json.loads(self.service.journal.read_artifact(entry["dataset"]))
        self.assertEqual(dataset["frequency_hz"], [1e9, 1.25e9, 1.5e9, 1.75e9, 2e9])
        self.assertEqual(dataset["sample_origin"][1::2], ["interpolated", "interpolated"])
        self.assertEqual(self.read("measurement.get", record=response["record_ref"])["record"], original["record"])
        self.assertEqual(self.read("measurement.get", record=response["record_ref"])["page"], original["page"])
        evidence = dataset["provenance"]["measurement_alignment_records"][-1]
        source_bytes = self.service.journal.read_artifact(evidence["host_source"])
        self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), evidence["host_source"]["sha256"])
        self.assertEqual(evidence["execution"]["operation"], "measurement.align")
        self.assertEqual(evidence["original_input"], parameters["specification"])
        lineage = self.read("measurement.history", collection="alignments", record=aligned["record_ref"],
                            section="lineage", offset=1, limit=2)
        self.assertEqual(lineage["total"], 5)
        self.assertEqual(lineage["next_offset"], 3)
        self.assertEqual([(row["frequency_hz"], row["source_indices"], row["weight"]) for row in lineage["items"]],
                         [(1.25e9, [0, 1], 0.5), (1.5e9, [1, 1], 0.0)])


if __name__ == "__main__":
    unittest.main()
