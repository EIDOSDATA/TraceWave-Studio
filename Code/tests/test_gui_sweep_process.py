"""! @brief 실제 Windows 연구 폼과 외부 회로 계산의 출처/미정/저장 재열기를 검증한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import network_service
from rfad.application.canonical import canonical_bytes
from rfad.application.design_sweep_store import baseline, candidate_source, load_candidate, load_definition, read_json
from rfad.application.projects import ProjectService
from rfad.domain.project import validate_project
from test_cad_worker_process import register_fixture
from test_design_sweep import fixture
from test_network_domain import target
from test_network_service import circuit_definition, import_parameters


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


def request(service, project, data, *, mutation=False):
    """! @brief GUI와 같은 공개 요청/영수증 경계로 시험 준비를 수행한다."""
    result = {"contract_version": "rfad.api/2.0", "context": {"project_id": project}, "input": data}
    if mutation:
        result.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
    return result


def apply_network(service, project, operation, parameters):
    """! @brief 실제 import/회로 원자 명령으로 계산할 기준 원본을 저장한다."""
    document = service._load(service.journal.read()["projects"][project])
    data = {"expected_revision": document["revision_id"], "operation": operation, "parameters": parameters}
    preview = network_service.read(service.host_calculation_context, "network.preview", request(service, project, data))
    if not preview["can_apply"]:
        raise AssertionError(preview)
    return service.mutate("network.apply", request(service, project,
        {**data, "review_hash": preview["review_hash"], "command_id": str(uuid4())}, mutation=True))


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 실제 Windows GUI를 지정합니다.")
class GuiSweepTests(unittest.TestCase):
    """! @brief 실제 외부 R 회로만 계산하며 FDTD/실측 검증으로 확대하지 않는다."""

    def test_native_sweep_preview_cancel_resume_save_and_reopen(self):
        """! @brief 2x2 설계 후보와 중복 포함 회로 후보를 실제 폼에서 저장/취소/재개한다."""
        with TemporaryDirectory(prefix="TraceWave 스윕 GUI ") as temporary:
            workspace = Path(temporary) / "작업 영역"
            original, _ = fixture()
            original["extensions"]["test.preserved"] = {"source_refs": ["원문 출처; 제작 자료 아님"],
                "manufacturing": None, "measurement": None}
            goal = target(frequencies=(1e9, 1.5e9, 2e9))
            goal["port_id"] = original["ports"][0]["id"]
            original["targets"] = [goal]
            validate_project(original)
            project = original["project_id"]
            with ProjectService(workspace, auto_run=False) as service:
                original, snapshot = register_fixture(service, original)
                apply_network(service, project, "import", import_parameters(goal["port_id"], count=201))
                circuit = circuit_definition()
                # @brief 실제 native 회로 계산이 취소 요청과 겹치도록 유한 201표본/8소자를 사용한다.
                for index in range(7):
                    element = deepcopy(circuit["elements"][0])
                    element.update(id=str(uuid4()), name="보조 R " + str(index + 1))
                    element["value"] = {"text": "1", "unit": "ohm", "source_refs": ["명시 이상 저항 시험값"]}
                    circuit["elements"].append(element)
                apply_network(service, project, "circuit_save", {"name": "GUI 외부 회로 기준", "definition": circuit})
                stored_before = service._load(service.journal.read()["projects"][project])
                old_entry = stored_before["extensions"]["rfad.network-library"]["datasets"][0]
                old_artifacts = {key: service.journal.read_artifact(old_entry[key]) for key in ("raw", "dataset", "normalized_hdf5")}
                old_snapshot = service.journal.read_artifact(snapshot["artifact"])
                operation = service.mutate("project.save", request(service, project,
                    {"expected_revision": stored_before["revision_id"]}, mutation=True))
                service.run_next()
                self.assertEqual(service.journal.read()["jobs"][operation["job_id"]]["state"], "completed")
            report_path = Path(temporary) / "설계 연구 GUI 검증.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--sweep-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, startupinfo=startup, timeout=240, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / "sweep.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2, report)
            self.assertEqual(set(report["setup_checks"]), {
                "sweep_cartesian_preview_2_by_2", "sweep_changed_input_invalidates_review",
                "sweep_frequency_display_preserves_review_and_si",
                "sweep_native_fields_and_viewport", "sweep_create_does_not_start_or_change_design",
                "sweep_circuit_units_and_duplicate_preserved", "sweep_cancel_preserves_explicit_resume",
                "sweep_real_circuit_completion_and_reuse", "sweep_saved_service_restart_preserves_history",
                "sweep_studio_candidates_and_design_return",
                "sweep_studio_titles_and_result_button", "sweep_candidate_result_native_conditions",
                "sweep_value_mode_explicit_rows_safe_reset",
            }, report)
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                current = service._load(state["projects"][project])
                self.assertEqual(canonical_bytes(current), canonical_bytes(stored_before))
                self.assertEqual(report["saved_revision"], stored_before["revision_id"])
                self.assertEqual(service.journal.read_artifact(snapshot["artifact"]), old_snapshot)
                for key, raw in old_artifacts.items():
                    self.assertEqual(service.journal.read_artifact(old_entry[key]), raw)
                self.assertEqual(len(state["sweeps"]), 2)
                grid = state["sweeps"][report["sweep_grid_id"]]
                circuit = state["sweeps"][report["sweep_circuit_id"]]
                self.assertEqual(grid["state"], "ready")
                self.assertEqual(grid["counts"]["total"], 4)
                self.assertEqual(grid["records"], {})
                self.assertEqual(circuit["state"], "completed")
                self.assertEqual(circuit["counts"]["completed"], 3)
                self.assertEqual(circuit["usage"]["native_solves"], 0)
                self.assertEqual(circuit["current_job_id"], None)
                self.assertFalse(state["solver_results"])
                for study in (grid, circuit):
                    definition, saved = baseline(service, study)
                    self.assertEqual(saved, stored_before)
                    self.assertEqual(definition["original_specification"]["source_refs"], ["GUI 명시 스윕 입력; 실측 아님"])
                    self.assertEqual(definition["specification"]["target_contexts"], [])
                    self.assertFalse(definition["runtime_identity"])
                definition = load_definition(service, circuit)
                self.assertEqual(definition["original_specification"]["variables"][0]["values"], [
                    {"text": text, "unit": unit, "source_refs": ["GUI 명시 스윕 입력; 실측 아님"]}
                    for text, unit in (("50", "ohm"), ("100", "ohm"), ("0.05", "kohm"))])
                self.assertEqual(definition["specification"]["target_ids"], [goal["id"]])
                rows = [load_candidate(service, circuit, index) for index in range(3)]
                self.assertEqual(rows[2]["cached_from_ordinal"], 0)
                self.assertEqual(rows[0]["evaluation_key"], rows[2]["evaluation_key"])
                for index, expected in enumerate((613 / 1513, 1063 / 1963, 613 / 1513)):
                    data = read_json(service, rows[index]["results"]["dataset"])
                    self.assertEqual(len(data["frequency_hz"]), 201)
                    self.assertAlmostEqual(data["values_ri"][0][0][0][0], expected)
                    self.assertAlmostEqual(data["values_ri"][0][0][0][1], 0)
                    self.assertEqual(data["conditions"], {"manufacturing": None, "measurement": None})
                    self.assertEqual(data["reference_planes"], ["입력 기준면"])
                    assessment = read_json(service, rows[index]["results"]["assessment"])
                    self.assertFalse(assessment["physics_validated"])
                    self.assertEqual(assessment["assessments"][0]["status"], "not_evaluated")
                    self.assertIsNone(assessment["assessments"][0]["evidence"]["context"])
                    candidate = candidate_source(service, circuit, index)
                    self.assertEqual(candidate["document"]["extensions"], stored_before["extensions"])
                    self.assertEqual(candidate["document"]["materials"], stored_before["materials"])
                    self.assertEqual(candidate["document"]["metadata"], stored_before["metadata"])


if __name__ == "__main__":
    unittest.main()
