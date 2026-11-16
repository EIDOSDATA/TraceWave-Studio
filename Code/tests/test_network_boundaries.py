"""! @brief 큰 원문 전송과 계산 진단, 과거 입력 보존의 서비스 경계를 검사한다."""

import base64
from copy import deepcopy
import json
import math
from types import SimpleNamespace
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application import rpc
from rfad.application.network_solver_import import solver_dataset, radiation_metrics
from rfad.application.network_records import samples
from rfad.domain.network_data import make_dataset
from rfad.domain.units import Quantity
import test_network_service as fixtures
import test_canvas_process
from test_pcb_solver import fixture_document, snapshot_for, runtime_identity, SETTINGS
from rfad.application.pcb_solver import build_pcb_plan


class NetworkBoundaryTests(unittest.TestCase):
    """! @brief 외부 입력을 기본값으로 채우지 않으면서 전체 근거를 보존한다."""

    def setUp(self):
        """! @brief 공용 fixture를 합성하여 중복 시험 수집을 피한다."""
        self.fixture = fixtures.NetworkServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_original_port_mapping_and_si_only_unit_change(self):
        """! @brief 원문에 없는 포트 ID와 단위 변경을 최초 출처로 덮어쓰지 않는다."""
        fixture = self.fixture
        port = fixture.document()["ports"][0]["id"]
        identity = fixture.apply("import", fixtures.import_parameters(port))
        entry = fixture.read("network.get", dataset_id=identity, offset=0, limit=201, row=0, column=0)["entry"]
        data = json.loads(fixture.service.journal.read_artifact(entry["dataset"]))
        self.assertEqual(data["port_ids"], [port])
        self.assertEqual(data["provenance"]["original_conditions"]["port_ids"], [])
        original = Quantity.from_value(1.2345678901234567, "nH", source_refs=["원문 유지"], status="estimated").to_dict()
        response = fixture.read("network.quantity", quantity=original, display_unit="uH")
        expected = {**original, "display_unit": "uH"}
        self.assertEqual(response["quantity"], expected)
        self.assertNotEqual(original["display_unit"], response["quantity"]["display_unit"])
        fresh = fixture.read("network.quantity", quantity={"text": "5", "unit": "nH", "source_refs": ["신규 입력"]}, display_unit="uH")
        self.assertEqual(fresh["text"], "0.005")
        self.assertEqual(fresh["quantity"]["source_refs"], ["신규 입력"])
        missing = fixture.read("network.quantity", quantity={"text": "", "unit": "pF", "source_refs": ["미확보"]}, display_unit="nF")
        self.assertIsNone(missing["quantity"]["value_si"])
        self.assertEqual(missing["quantity"]["status"], "missing")
        for malformed in ([], {"bad": True}):
            definition = fixtures.circuit_definition()
            definition["elements"][0]["kind"] = malformed
            self.assertFalse(fixture.preview("circuit_save", {"name": "잘못된 종류", "definition": definition})["can_apply"])
        definition = fixtures.circuit_definition()
        definition["elements"][0]["value"] = {**original, "display_unit": "잘못된 단위"}
        self.assertFalse(fixture.preview("circuit_save", {"name": "잘못된 단위", "definition": definition})["can_apply"])
        for invalid_text in ("1e-999", "1e-999999999999999999999999999999999", "1e999", "NaN", "1_000"):
            definition = fixtures.circuit_definition()
            definition["elements"][0]["value"]["text"] = invalid_text
            rejected = fixture.preview("circuit_save", {"name": "표현 범위 밖 소자", "definition": definition})
            self.assertFalse(rejected["can_apply"], invalid_text)

    def test_1001_samples_16_elements_preserve_full_diagnostics(self):
        """! @brief 최대 소자/표본의 진단을 작은 미리보기와 불변 전체 파일로 나눈다."""
        fixture = self.fixture
        source = fixture.apply("import", fixtures.import_parameters(count=1001))
        definition = fixtures.circuit_definition()
        element = definition["elements"][0]
        definition["elements"] = [{**deepcopy(element), "id": str(uuid4()), "name": "R" + str(index + 1)} for index in range(16)]
        circuit = fixture.apply("circuit_save", {"name": "16개 저항", "definition": definition})
        params = {"name": "1001개 표본 결합", "dataset_id": source, "circuit_id": circuit}
        preview = fixture.preview("circuit_apply", params)
        self.assertTrue(preview["can_apply"], preview)
        self.assertEqual(preview["diagnostic_count"], 1001)
        self.assertEqual(len(preview["diagnostics"]), 8)
        identity = fixture.apply("circuit_apply", params)
        first = fixture.read("network.diagnostics", dataset_id=identity, offset=0, limit=32)
        self.assertEqual(len(first["diagnostics"]), 32)
        self.assertEqual(first["total"], 1001)
        raw = fixture.service.journal.read_artifact(first["artifact"])
        self.assertEqual(len(json.loads(raw)["samples"]), 1001)
        last = fixture.read("network.diagnostics", dataset_id=identity, offset=992, limit=32)
        self.assertEqual(len(last["diagnostics"]), 9)
        self.assertIsNone(last["next_offset"])
        fixture.save_reopen()
        self.assertEqual(raw, fixture.service.journal.read_artifact(first["artifact"]))

    def test_exact_comparison_and_explicit_target_pages(self):
        """! @brief 누락 주파수와 다른 기준면은 비교 불가이며 큰 목표 원본은 봉인한다."""
        fixture = self.fixture
        port = fixture.document()["ports"][0]["id"]
        left = fixture.apply("import", fixtures.import_parameters(port, count=5))
        right = fixture.apply("import", fixtures.import_parameters(port, count=3))
        params = {"left_id": left, "right_id": right, "right_port_order": [0], "offset": 0, "limit": 201, "row": 0, "column": 0}
        response = fixture.read("network.compare", **params)
        self.assertEqual([row["status"] for row in response["points"]], ["comparable", "not_comparable", "comparable", "not_comparable", "comparable"])
        self.assertEqual(response["points"][0]["difference_ri"], [0.0, 0.0])
        parameters = fixtures.import_parameters(port)
        parameters["declarations"]["reference_planes"] = ["다른 기준면"]
        other = fixture.apply("import", parameters)
        response = fixture.read("network.compare", **{**params, "right_id": other})
        self.assertTrue(all(row["status"] == "not_comparable" for row in response["points"]))
        target = deepcopy(fixture.document()["targets"][0])
        target.pop("revision_id")
        frequencies = [Quantity.from_value(1e9 + 1e9 * index / 1000, "Hz", source_refs=["명시 요구 표본"]).to_dict() for index in range(1001)]
        target["band"].update(start=frequencies[0], end=frequencies[-1], sampling={"kind": "explicit", "frequencies": frequencies})
        target["band"]["reference"] = Quantity.missing("frequency", "Hz").to_dict()
        changed = fixture.service.mutate("project.apply_command", fixture.request({"expected_revision": fixture.revision, "command_id": str(uuid4()),
            "type": "target.set", "payload": {"target": target}}, mutation=True))
        fixture.revision = changed["new_revision"]
        evaluation = fixture.apply("evaluate", {"name": "1001개 목표", "dataset_id": left, "target_id": target["id"],
            "context": {"port_id": port, "target_port_id": target["port_id"], "reference_plane": "시험 기준면", "frequency_policy": "exact_only"}})
        summary = fixture.read("network.assessment", assessment_id=evaluation)
        self.assertIn("target_original_summary", summary["assessment"]["evidence"])
        self.assertEqual(summary["assessment"]["frequency_min_hz"], 1e9)
        self.assertEqual(summary["assessment"]["frequency_max_hz"], 2e9)
        self.assertLess(summary["assessment"]["criteria"][0]["points_preview"][-1]["frequency_hz"], 2e9)
        frozen = json.loads(fixture.service.journal.read_artifact(summary["entry"]["artifact"]))
        self.assertNotIn("frequency_min_hz", frozen)
        self.assertNotIn("frequency_max_hz", frozen)
        self.assertEqual(frozen["evidence"]["target_original"]["band"]["sampling"]["frequencies"], frequencies)
        page = fixture.read("network.assessment.points", assessment_id=evaluation, criterion=0, offset=804, limit=201)
        self.assertEqual(len(page["points"]), 197)
        self.assertIsNone(page["next_offset"])
        self.assertEqual(fixture.read("network.assessment", assessment_id=evaluation), summary)
        self.assertEqual(json.loads(fixture.service.journal.read_artifact(summary["entry"]["artifact"])), frozen)


class NetworkProcessTests(unittest.TestCase):
    """! @brief 실제 stdio의 큰 가져오기와 강제 재시작 영수증을 검사한다."""

    def test_bounded_import_replay_and_reopen(self):
        """! @brief 8 KiB 초과 원문 예외가 지정 필드에만 적용되며 저장을 통과한다."""
        fixture = test_canvas_process.CanvasProcessTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        client = fixture.client
        parameters = fixtures.import_parameters(declared=False, count=1001)
        self.assertGreater(len(parameters["source_base64"]), rpc.MAX_STRING_BYTES)
        values = {"expected_revision": fixture.revision, "operation": "import", "parameters": parameters}
        preview = client.rpc("network.preview", client.params(values, project=fixture.project_id, mutation=False))
        self.assertTrue(preview["can_apply"], preview)
        request = client.params({**values, "command_id": str(uuid4()), "review_hash": preview["review_hash"]}, project=fixture.project_id)
        result = client.rpc("network.apply", request)
        fixture.revision = result["new_revision"]
        client.finish(client.rpc("project.save", client.params({"expected_revision": fixture.revision}, project=fixture.project_id)))
        fixture.restart()
        client.finish(client.rpc("project.open", client.params({"path": fixture.path, "open_mode": "open"})))
        self.assertEqual(client.rpc("network.apply", request), result)
        selection = client.rpc("network.get", client.params({"expected_revision": fixture.revision, "dataset_id": result["record_id"],
            "offset": 804, "limit": 201, "row": 0, "column": 0}, project=fixture.project_id, mutation=False))
        self.assertEqual(len(selection["page"]["samples"]), 197)
        self.assertIsNone(selection["descriptor"]["reference_planes"][0])
        self.assertEqual(selection["descriptor"]["phasor_convention"], "unknown")
        message = {"jsonrpc": "2.0", "id": 1, "method": "network.preview", "params": client.params(values, project=fixture.project_id, mutation=False)}
        invalid = deepcopy(message)
        invalid["params"]["input"]["parameters"]["name"] = "x" * 8193
        self.assertEqual(rpc.handle_frame(canonical_bytes(invalid))["error"]["data"]["domain_code"], "E_SCHEMA")
        invalid = deepcopy(message)
        invalid["params"]["input"]["operation"] = "transform"
        self.assertIn("error", rpc.handle_frame(canonical_bytes(invalid)))


class NetworkSolverProjectionTests(unittest.TestCase):
    """! @brief 기존 PCB 결과의 복소수/기준면/정규화를 정확히 투영한다."""

    def test_view_special_values_are_distinct_from_missing(self):
        """! @brief 완전 정합/개방/능동 반사와 위상 정의 불가를 미정 0으로 숨기지 않는다."""
        data = make_dataset(parameter_kind="S", frequency_hz=[1, 2, 3], port_ids=[str(uuid4())],
                            values_ri=[[[[0, 0]]], [[[1, 0]]], [[[2, 0]]]],
                            z0_ohm=[[[50, 0]], [[75, 0]], [[100, 0]]])
        points = samples(data)["samples"]
        self.assertIsNone(points[0]["magnitude_db"])
        self.assertEqual(points[0]["magnitude_db_state"], "negative_infinity")
        self.assertEqual(points[0]["phase_state"], "undefined_zero_magnitude")
        self.assertEqual(points[0]["vswr"], 1)
        self.assertEqual(points[1]["vswr_state"], "positive_infinity")
        self.assertEqual(points[2]["vswr_state"], "undefined_active")
        self.assertEqual(points[2]["z0_ohm"], [[100, 0]])

    def test_existing_pcb_complex_and_unknown_physical_conditions(self):
        """! @brief 계약용 표본을 사용하며 새 FDTD나 물리 검증을 주장하지 않는다."""
        document = fixture_document()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        original = {"schema": "rfad.openems-pcb-result/0.1", "analysis_plan_id": plan["plan_id"], "normalization": plan["normalization"],
            "samples": [{"frequency_hz": 8e9 + 4e9 * index / 30, "s11": [0.3, 0.4], "impedance_ohm": [60, 50],
                         "vswr": 3.0, "s11_db": 20 * math.log10(0.5), "vswr_status": "defined"} for index in range(31)],
            "assessment": {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True},
            "termination": {"status": "end_criterion_reached"}, "provenance": {"analysis_plan": plan}}
        raw = canonical_bytes(original)
        identity = str(uuid4())
        ref = {"uri": "projects/test/source.json", "sha256": "1" * 64, "bytes": len(raw)}
        service = SimpleNamespace(journal=SimpleNamespace(read_artifact=lambda value: raw))
        state = {"solver_results": {identity: {"project_id": document["project_id"], "normalized": ref}}}
        data, source = solver_dataset(service, state, document, identity)
        self.assertEqual(source, raw)
        self.assertEqual(data["values_ri"][0][0][0], [0.3, 0.4])
        self.assertEqual(data["reference_planes"], [plan["normalization"]["reference_plane"]])
        self.assertEqual(data["provenance"]["snapshot"], plan["snapshot"])
        self.assertIsNone(data["conditions"]["measurement"])
        self.assertFalse(data["conditions"]["physics_validated"])
        self.assertIsNone(radiation_metrics(service, {"path": "projects/test"}, {"kind": "derived", "raw": ref}, data))


if __name__ == "__main__":
    unittest.main()
