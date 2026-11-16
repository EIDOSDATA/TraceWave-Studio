"""! @brief 실제 journal과 가짜 전송으로 참조 계획/게시/조회 계약만 검사한다.

@details 이 파일의 균일 복소 전계와 probe는 파일 수명 시험용이다.
native 실행, 다이폴 물리 정확도 또는 독립 기준 일치의 증거가 아니다.
"""

from copy import deepcopy
import json
import math
import unittest

from rfad.adapters.solvers.openems.native import descriptor
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_results import check_termination
from rfad.application.projects import ProjectService
from rfad.application.result_service import read
from rfad.application.rf_reference_contract import (
    CASE, PROFILE, RESULT_SCHEMA, RADIATION_SCHEMA, REFERENCE_SCOPE, raw_names, radiation_summary,
)
from rfad.application.solver import RUNTIME_PROFILE
from rfad.domain.errors import ProjectError
from test_pcb_radiation import field_result
from test_solver_jobs import FakeTransport, _json_file
import test_solver_jobs


class ReferenceTransport(FakeTransport):
    """! @brief 설치 환경을 모사하지 않는 참조 파일 계약 전용 전송이다."""

    def _prepare(self, stage, request, runtime):
        """! @brief 고정 계획의 격자/소비와 구분된 참조 native 파일을 게시한다."""
        plan = request["analysis_plan"]
        lines = deepcopy(plan["case"]["mesh"]["lines_mm"])
        counts = [len(lines[axis]) for axis in "xyz"]
        mesh = {"schema": "rfad.openems-reference-mesh/0.1", "grid_mm": plan["case"]["mesh"]["interior_grid_mm"],
                "lines_mm": lines, "line_counts": counts, "interval_counts": [n - 1 for n in counts],
                "native_grid_points": math.prod(counts), "yee_interval_cells": math.prod(n - 1 for n in counts),
                "native_length_unit": "mm", "delta_unit_m": 0.001, "native_preprocessing_executed": False, "fdtd_executed": False}
        consumption = {"schema": "rfad.openems-reference-consumption/0.1", "analysis_plan_id": plan["plan_id"],
                       "source": "explicit_reference_case", "consumed_case": deepcopy(plan["case"]),
                       "project_geometry_consumed": False, "project_materials_consumed": False,
                       "fdtd_executed": False, "physics_validated": False}
        if self.mode == "reference_wrong_mesh":
            mesh["lines_mm"]["x"][8] = -73.0
        path = stage / "output/prepared/reference.xml"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"<openEMS><!-- contract test only; no native geometry --></openEMS>")
        files = [descriptor(stage, path, "native_input")]
        for name, role, value in (("mesh.json", "mesh_statistics", mesh), ("consumption.json", "consumption_report", consumption),
                                 ("normalization.json", "normalization", plan["normalization"]),
                                 ("runtime.json", "runtime_provenance", runtime),
                                 ("radiation_recording.json", "radiation_recording", plan["case"]["radiation_recording"])):
            files.append(_json_file(stage, "output/prepared/" + name, value, role))
        preparation = {"schema": "rfad.preparation-artifact/0.1", "analysis_plan_id": plan["plan_id"],
                       "analysis_plan_hash": canonical_hash(plan), "profile": PROFILE, "files": deepcopy(files),
                       "mesh_statistics": mesh, "consumption_report": consumption, "normalization": plan["normalization"],
                       "radiation_recording": plan["case"]["radiation_recording"], "runtime_identity": runtime}
        files.append(_json_file(stage, "output/prepared/preparation.json", preparation, "preparation_artifact"))
        return preparation, files

    def _analysis(self, stage, request, runtime):
        """! @brief 정규화/별도 방사/원시 manifest를 실제 파일 hash로 결합한다."""
        plan, prepared, preparation = request["analysis_plan"], request["prepared_plan"], request["preparation"]
        xml = next(item for item in request["input_files"] if item["role"] == "native_input")
        log = "Exact-endcriteria: evaluating the end criteria every timestep\nRunFDTD: end-criteria of -50dB reached after 1000 timesteps (-51dB)\n"
        statistics = {"native_cells": preparation["mesh_statistics"]["native_grid_points"], "timestep_seconds": 1e-12,
                      "iterations": 1000, "raw_values": [float(preparation["mesh_statistics"]["native_grid_points"]), 1e-12, 1000.0, 0.1, 1.0, 2.0]}
        files = []
        for name in raw_names(plan):
            path = stage / "output/raw" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = b"0 0\n1e-12 1\n2e-12 0\n"
            if name == "reference.xml":
                content = (stage / xml["path"]).read_bytes()
            elif name == "native.log":
                content = log.encode("ascii")
            elif name == "openEMS_stats.txt":
                content = ("\n".join(map(str, statistics["raw_values"])) + "\n").encode("ascii")
            path.write_bytes(content)
            files.append(descriptor(stage, path, "raw/" + name))
        termination = check_termination(log, 1000, plan["case"]["settings"])
        manifest = {"schema": "rfad.openems-raw/0.1", "complete": True,
                    "analysis_plan_id": plan["plan_id"], "analysis_plan_hash": canonical_hash(plan),
                    "prepared_plan_id": prepared["prepared_plan_id"], "prepared_plan_hash": canonical_hash(prepared),
                    "files": deepcopy(files), "execution": {"command": ["fake-contract-only"], "elapsed_seconds": 0.01,
                        "exit_code": 0, "loaded_native_files": [], "statistics": statistics, "termination": termination,
                        "native_input_sha256": xml["sha256"]}}
        field = field_result(plan)
        field["schema"] = RADIATION_SCHEMA
        field["frequencies"][0]["frequency_hz"] = 2.4e9
        provenance = {"schema": "rfad.openems-provenance/0.1", "run_id": request["run_id"], "nonce": request["nonce"],
                      "execution_mode": request["phase"], "analysis_plan": plan, "prepared_plan": prepared,
                      "preparation": preparation, "runtime": runtime, "raw_manifest": manifest}
        result = {"schema": RESULT_SCHEMA, "analysis_plan_id": plan["plan_id"], "prepared_plan_id": prepared["prepared_plan_id"],
                  "samples": [{"frequency_hz": 2.4e9, "s11": [0.0, 0.0], "impedance_ohm": [50.0, 0.0],
                               "vswr": 1.0, "vswr_status": "defined", "s11_db": None}],
                  "assessment": {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True},
                  "termination": termination, "native_statistics": statistics, "mesh_statistics": preparation["mesh_statistics"],
                  "normalization": plan["normalization"], "provenance": provenance, "raw_manifest": manifest,
                  "reference_scope": deepcopy(REFERENCE_SCOPE), "radiation_summary": radiation_summary(field)}
        if self.mode == "reference_pcb_alias":
            result["schema"] = "rfad.openems-pcb-result/0.1"
        elif self.mode == "reference_wrong_field":
            field["schema"] = "rfad.pcb-radiation/0.1"
        elif self.mode == "reference_physics_pass":
            result["reference_scope"]["physics_validated"] = True
        files.extend([_json_file(stage, "output/raw_manifest.json", manifest, "raw_manifest"),
                      _json_file(stage, "output/radiation.json", field, "radiation_result"),
                      _json_file(stage, "output/native-radiation.json", {"test_only": True}, "radiation_native"),
                      _json_file(stage, "output/normalized.json", result, "normalized_result"),
                      _json_file(stage, "output/provenance.json", provenance, "provenance")])
        return result, files


class RFReferenceJobTests(unittest.TestCase):
    """! @brief 기존 조정기 수명과 새 참조 source의 읽기 전용 보존을 확인한다."""

    def setUp(self):
        """! @brief 기존 작업 시험의 journal/runtime 초기화만 재사용한다."""
        self.host = test_solver_jobs.SolverJobTests("runTest")
        self.host.setUp()
        self.addCleanup(self.host.tearDown)
        self.host.transport.__class__ = ReferenceTransport

    def planned(self, grid=3.0):
        """! @brief 공개 solver.plan으로 고정 참조 계획을 봉인한다."""
        host = self.host
        return host.complete("solver.plan", {"snapshot": {key: host.snapshot[key] for key in ("snapshot_id", "content_hash")},
            "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE,
            "settings": {"case": CASE, "grid_mm": grid}})["analysis_plan"]

    def prepared(self):
        """! @brief 실제 조정기의 준비 파일 검사를 통과한다."""
        plan = self.planned()
        return self.host.complete("solver.prepare", {"analysis_plan": {key: plan[key] for key in ("plan_id", "content_hash")},
            "budget": {"timeout_seconds": 120}})["prepared_plan"]

    def query(self, method, data):
        """! @brief 결과 읽기 전후 journal과 원본 개정을 비교한다."""
        service = self.host.service
        before = service.journal.read()
        result = read(service, method, {"contract_version": "rfad.api/2.0", "context": {"project_id": self.host.project}, "input": data})
        self.assertEqual(service.journal.read(), before)
        return result

    def test_pipeline_reference_scope_projection_and_runtime_free_reopen(self):
        """! @brief 준비/계산/후처리 후에도 합성 scope와 미정 및 원문 hash를 보존한다."""
        host = self.host
        prepared = self.prepared()
        completed = host.complete("job.submit", host.analysis_input(prepared))
        source = {"kind": "solver", "artifact_id": completed["artifact_id"]}
        description = self.query("result.describe", {"source": source})
        self.assertIn("PEC 다이폴 / 격자 수준 1 / 합성 검증 사례", description["label"])
        self.assertEqual(description["reference_scope"], REFERENCE_SCOPE)
        self.assertEqual(description["descriptor"]["sample_count"], 1)
        self.assertEqual(description["states"]["physics"], "not_established")
        self.assertTrue(description["available_views"]["radiation"])
        self.assertFalse(description["available_views"]["field"])
        selected = {"source": source, "pin": description["pin"]}
        field = self.query("result.radiation", {**selected, "theta_limit": 1})
        self.assertEqual(field["reference_scope"], REFERENCE_SCOPE)
        self.assertEqual(field["electric_field_unit"], "V*s/m")
        power = self.query("result.metrics", selected)
        self.assertEqual(power["reference_scope"], REFERENCE_SCOPE)
        self.assertIsNone(power["absolute_power_w"])
        self.assertEqual(power["rows"][0]["independent_losses"], [])
        page = self.query("result.page", {**selected, "row": 0, "column": 0, "offset": 0, "limit": 201})
        self.assertEqual(page["page"]["samples"][0]["frequency_hz"], 2.4e9)
        with self.assertRaises(ProjectError):
            self.query("result.page", {**selected, "row": 0, "column": 1, "offset": 0, "limit": 201})
        before = host.service.journal.read()
        record = before["solver_results"][source["artifact_id"]]
        original = host.service.journal.read_artifact(record["normalized"])
        repeated = host.complete("job.submit", host.analysis_input(prepared, raw_result_id=source["artifact_id"]))
        self.assertNotEqual(repeated["artifact_id"], source["artifact_id"])
        self.assertEqual(host.service.journal.read_artifact(record["normalized"]), original)
        host.service.close()
        host.service = ProjectService(host.workspace, auto_run=False)
        reopened = self.query("result.describe", {"source": source})
        self.assertEqual(reopened["pin"], description["pin"])
        self.assertEqual(reopened["reference_scope"], REFERENCE_SCOPE)
        self.assertEqual(host.service.journal.read_artifact(record["normalized"]), original)
        current = host.service.journal.read()["projects"][host.project]["current"]
        self.assertEqual(json.loads(host.service.journal.read_artifact(current))["revision_id"], host.revision)

    def test_changed_actual_mesh_cannot_publish_prepared_plan(self):
        """! @brief 실제 준비 격자가 고정 PML 계면을 옮기면 게시를 거절한다."""
        host = self.host
        plan = self.planned()
        host.transport.mode = "reference_wrong_mesh"
        task = host.service.mutate("solver.prepare", host.request({"analysis_plan": {key: plan[key] for key in ("plan_id", "content_hash")},
                                                                "budget": {"timeout_seconds": 120}}))
        host.service.solver.run_next()
        self.assertEqual(host.status(task)["state"], "failed")
        self.assertEqual(host.service.journal.read()["prepared_plans"], {})

    def test_wrong_schema_or_physics_scope_cannot_publish_result(self):
        """! @brief PCB schema 위장과 방사 schema 교체 및 합격 주장을 거절한다."""
        host = self.host
        prepared = self.prepared()
        for mode in ("reference_pcb_alias", "reference_wrong_field", "reference_physics_pass"):
            host.transport.mode = mode
            task = host.service.mutate("job.submit", host.request(host.analysis_input(prepared)))
            host.service.solver.run_next()
            with self.subTest(mode=mode):
                self.assertEqual(host.status(task)["state"], "failed")
                self.assertEqual(host.service.journal.read()["solver_results"], {})
