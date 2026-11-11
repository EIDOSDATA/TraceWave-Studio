"""! @brief 카탈로그 통합 검증기의 해석 출처 혼합과 무단 입력 보정을 차단한다.

@details 수명 검사는 명시적 시험 물성과 가짜 공개 API 응답을 사용한다.
실제 WSL 실행이나 native 준비 검증의 증거로 사용하지 않는다.
"""

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from catalog_pcb_verification import solver
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.solver import make_prepared_plan
from test_pcb_solver import SETTINGS, fixture_document, runtime_identity, snapshot_for


class SolverContractFixture:
    """! @brief 저장 바이트와 공개 응답을 고정한 비 native 시험 이중체이다."""

    def __init__(self):
        """! @brief 실제 제품 물성이 아닌 기존 명시 fixture로 봉인 참조를 구성한다."""
        self.files = {}
        self.calls = []
        self.document = fixture_document()
        self.snapshot = snapshot_for(self.document)
        self.snapshot["artifact"] = self.add("source.json", self.document)
        self.context = {"project_id": self.document["project_id"]}
        self.plan = build_pcb_plan(self.document, self.snapshot, runtime_identity(), SETTINGS)
        self.plan_ref = self.reference(self.plan, "plan_id", "plan.json")
        observed = {**self.plan["runtime_identity"], "qt_found": False}
        native = {"role": "native_input", "sha256": "a" * 64, "bytes": 17}
        self.preparation = {"files": [native], "runtime_identity": observed,
                            "mesh_statistics": {}, "consumption_report": {"consumed_case": self.plan["case"]}}
        self.prep_ref = self.add("preparation.json", self.preparation)
        self.prepared = make_prepared_plan(self.plan_ref, self.snapshot, self.prep_ref, self.plan["runtime_identity"])
        self.prepared_ref = self.reference(self.prepared, "prepared_plan_id", "prepared.json")
        manifest = {"complete": True, "analysis_plan_hash": canonical_hash(self.plan),
                    "prepared_plan_hash": canonical_hash(self.prepared),
                    "files": [{**native, "role": "raw/pcb.xml"}],
                    "execution": {"native_input_sha256": native["sha256"]}}
        self.result = {
            "schema": "rfad.openems-pcb-result/0.1", "analysis_plan_id": self.plan["plan_id"],
            "prepared_plan_id": self.prepared["prepared_plan_id"], "normalization": self.plan["normalization"],
            "samples": [{"frequency_hz": 8e9 + 4e9 * index / 30, "s11": [0.5, 0.0],
                         "impedance_ohm": [150.0, 0.0], "vswr": 3.0, "s11_db": 20 * math.log10(0.5),
                         "vswr_status": "defined"} for index in range(31)],
            "assessment": {"status": "computed_unvalidated", "physics_validated": False,
                           "converged": True, "finite_samples": True},
            "termination": {"status": "end_criterion_reached"}, "native_statistics": {}, "mesh_statistics": {},
            "raw_manifest": manifest,
            "provenance": {"analysis_plan": self.plan, "prepared_plan": self.prepared,
                           "preparation": self.preparation, "runtime": observed, "raw_manifest": manifest},
        }
        self.results = [deepcopy(self.result), deepcopy(self.result)]
        self.result_ids = [str(uuid4()), str(uuid4())]
        self.result_refs = [self.add("result-" + str(index) + ".json", result)
                            for index, result in enumerate(self.results)]
        self.submitted = 0
        self.service = SimpleNamespace(journal=SimpleNamespace(read_artifact=self.read))

    def add(self, name, value):
        """! @brief 이중체에도 실제 JSON 바이트 크기와 SHA256을 사용한다."""
        raw = canonical_bytes(value)
        self.files[name] = raw
        return {"uri": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def reference(self, value, identifier, name):
        """! @brief 계획의 canonical 해시와 저장 바이트 해시를 구별한다."""
        return {identifier: value[identifier], "content_hash": canonical_hash(value), "artifact": self.add(name, value)}

    def read(self, descriptor):
        """! @brief 저장 참조가 손상되면 해시 검사 실패를 반환한다."""
        raw = self.files[descriptor["uri"]]
        if len(raw) != descriptor["bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise ValueError("시험 저장 파일의 봉인이 다릅니다.")
        return raw

    def call(self, service, method, data, context=None, mutation=False):
        """! @brief 실행 요청을 기록하고 동일한 입력에 대응하는 제한된 공개 응답을 반환한다."""
        self.calls.append((method, deepcopy(data)))
        if method == "solver.plan":
            return {"analysis_plan": self.plan_ref}
        if method == "solver.prepare":
            return {"prepared_plan": self.prepared_ref, "preparation_artifact": self.prep_ref}
        if method == "job.submit":
            index = self.submitted
            self.submitted += 1
            self.result_refs[index] = self.add("result-" + str(index) + ".json", self.results[index])
            return {"artifact_id": self.result_ids[index], "normalized_result": self.result_refs[index]}
        if method == "solver.latest":
            return {"result": {"artifact_id": self.result_ids[1]}}
        index = self.result_ids.index(data["artifact_id"])
        if method == "result.open":
            return {"artifact_id": self.result_ids[index], "files": [self.result_refs[index]]}
        if method == "solver.samples":
            return {"snapshot": deepcopy(self.snapshot), "samples": deepcopy(self.results[index]["samples"])}
        raise AssertionError("허용하지 않은 공개 호출: " + method)

    def run(self):
        """! @brief native 준비 검사만 분리하고 검증기의 나머지 출처 경계를 실행한다."""
        with patch.object(solver, "call", side_effect=self.call), patch.object(solver, "wait", side_effect=self.wait), \
                patch.object(solver, "validate_preparation"):
            return solver.verify_solver(self.service, self.context, self.snapshot, deepcopy(SETTINGS))

    @staticmethod
    def wait(service, result):
        """! @brief 시험 API의 즉시 완료를 명시하며 실제 worker 상태를 주장하지 않는다."""
        return result, {"events": [{"state": "completed"}]}


class CatalogPcbSolverTests(unittest.TestCase):
    """! @brief 입력/worker/원시 자료/저장 결과를 섞은 통합 합격을 거부한다."""

    def test_public_lifecycle_and_reopen_preserve_exact_input(self):
        """! @brief 계획과 결과 복원에서 추가 실행이나 직접 입력 보정이 발생하지 않는다."""
        fixture = SolverContractFixture()
        before = deepcopy(fixture.document)
        report = fixture.run()
        self.assertFalse(report["assessment"]["physics_validated"])
        self.assertEqual(report["consumed_materials"], fixture.plan["case"]["materials"])
        submits = [data for method, data in fixture.calls if method == "job.submit"]
        self.assertEqual([data["task_plan"]["execution_mode"] for data in submits],
                         ["solve_and_postprocess", "postprocess_only"])
        self.assertEqual(submits[1]["task_plan"]["raw_result_id"], report["artifact_id"])
        self.assertEqual(fixture.document, before)
        fixture.calls.clear()
        with patch.object(solver, "call", side_effect=fixture.call), patch.object(solver, "validate_preparation"):
            solver.restore_solver(fixture.service, fixture.context, fixture.snapshot, report)
        self.assertEqual(set(method for method, _ in fixture.calls), {"result.open", "solver.samples", "solver.latest"})

    def test_missing_material_is_not_filled_and_prepare_is_not_requested(self):
        """! @brief 입력에서 사라진 필수 물성을 fixture 값으로 대입하지 않는다."""
        fixture = SolverContractFixture()
        dielectric = next(item for item in fixture.document["materials"]
                          if item["id"] == fixture.document["stackup"][0]["material_id"])
        dielectric["tan_delta"]["value_si"] = None
        fixture.snapshot["artifact"] = fixture.add("source.json", fixture.document)
        fixture.snapshot["content_hash"] = canonical_hash(fixture.document)
        with self.assertRaises((ValueError, RuntimeError)):
            fixture.run()
        self.assertNotIn("solver.prepare", [method for method, _ in fixture.calls])
        self.assertIsNone(dielectric["tan_delta"]["value_si"])

    def test_changed_worker_or_xml_is_rejected_before_postprocess(self):
        """! @brief Qt 탐지/worker 교체/준비 XML 교체를 완료 결과로 받아들이지 않는다."""
        for kind in ("qt", "worker", "xml"):
            with self.subTest(kind=kind):
                fixture = SolverContractFixture()
                result = fixture.results[0]
                if kind == "qt":
                    result["provenance"]["runtime"]["qt_found"] = True
                elif kind == "worker":
                    result["provenance"]["runtime"]["manifest_sha256"] = "0" * 64
                else:
                    result["raw_manifest"]["execution"]["native_input_sha256"] = "0" * 64
                with self.assertRaises((ValueError, RuntimeError)):
                    fixture.run()
                self.assertEqual(fixture.submitted, 1)

    def test_reprocess_cannot_replace_raw_data_or_samples(self):
        """! @brief 독립 후처리의 원시 자료나 계산값 차이를 동일 결과로 보고하지 않는다."""
        for kind in ("raw", "sample"):
            with self.subTest(kind=kind):
                fixture = SolverContractFixture()
                if kind == "raw":
                    fixture.results[1]["raw_manifest"]["other_data"] = "changed"
                else:
                    fixture.results[1]["samples"][0]["impedance_ohm"][0] = 151.0
                with self.assertRaises((ValueError, RuntimeError)):
                    fixture.run()

    def test_reopen_detects_saved_file_damage(self):
        """! @brief 저장된 정규화 결과가 변경되면 재계산 없이 복원을 거부한다."""
        fixture = SolverContractFixture()
        report = fixture.run()
        fixture.files[report["result"]["uri"]] += b" "
        fixture.calls.clear()
        with patch.object(solver, "call", side_effect=fixture.call), patch.object(solver, "validate_preparation"), \
                self.assertRaises((ValueError, RuntimeError)):
            solver.restore_solver(fixture.service, fixture.context, fixture.snapshot, report)
        self.assertNotIn("job.submit", [method for method, _ in fixture.calls])


if __name__ == "__main__":
    unittest.main()
