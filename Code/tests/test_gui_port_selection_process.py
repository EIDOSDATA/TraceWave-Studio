"""! @brief Windows Studio에서 급전의 양단과 진단의 원본 이동을 검증한다."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import subprocess
import sys
import unittest
from uuid import uuid4

from rfad.application import network_service
from rfad.application.projects import ProjectService
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture, request
from test_network_service import import_parameters
from test_pcb_solver import fixture_document


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")
CAD = os.environ.get("RFAD_CAD_PYTHON", "")


@unittest.skipUnless(sys.platform == "win32" and GUI and CAD, "실제 Windows Studio와 OCCT가 필요합니다.")
class GuiPortSelectionTests(unittest.TestCase):
    """! @brief 명시 영역과 구버전 미정 영역을 동일한 원본 ID 계약에서 대조한다."""

    def test_defined_gap_selection(self):
        """! @brief 2D 급전 표식과 native 3D 양단, 저장을 확인한다."""
        self.verify_port(missing=False)

    def test_unresolved_gap_selection(self):
        """! @brief 미정 표식과 진단의 Enter 이동, 미정 원본 보존을 확인한다."""
        self.verify_port(missing=True)

    def verify_port(self, *, missing):
        """! @brief 표시 시험과 독립 서비스 재열기의 결과를 비교한다."""
        fixture = fixture_document()
        port = fixture["ports"][0]
        port["name"] = "사용자 원래 급전"
        port["resistance"]["source_refs"] = ["시험용 포트 저항 직접 입력"]
        port["validity_hz"]["max"]["source_refs"] = ["시험용 대역 상한"]
        if missing:
            del port["excitation_box"]
            port["resistance"] = Quantity.missing("impedance", "ohm").to_dict()
            port["resistance"]["source_refs"] = ["실물 포트 저항 자료 미확보"]
        fixture["extensions"]["test.acquisition"] = {
            "source_refs": ["출처가 연결된 검증용 보드"], "manufacturing_condition": None, "measurement_condition": None}
        config = {"port_mode": "missing" if missing else "defined", "id": port["id"],
                  "signal": port["positive_geometry_id"], "reference": port["reference_geometry_id"],
                  "original_name": port["name"]}
        with TemporaryDirectory(prefix="TraceWave GUI 급전 ") as temporary:
            directory = Path(temporary)
            workspace = directory / "작업 영역"
            with ProjectService(workspace, auto_run=False) as service:
                original, snapshot = register_fixture(service, fixture)
                current = self.register_previous_result(service, original)
                record = service.journal.read()["projects"][original["project_id"]]
                active = service._load(record)
                source = service.journal.read_artifact(snapshot["artifact"])
                past_refs = current["datasets"][0]
                before = {key: service.journal.read_artifact(past_refs[key]) for key in ("raw", "normalized_hdf5")}
            (workspace / "precision-antenna.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            report_path = directory / "급전 선택 검증.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 1
            process = subprocess.run([
                str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--cad-python", str(Path(CAD).resolve()), "--precision-editor-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, startupinfo=startup, timeout=220, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / ("port-" + config["port_mode"] + ".json")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            checks = {"port_terminals_native_tree_2d_keyboard_focus", "cancel_port_draft_move_and_canvas_pick",
                      "port_single_history_stale_and_updated_native_mesh", "saved_reopened_port_identity_and_marker"}
            if missing:
                checks.add("missing_port_diagnostic_round_trip")
            self.assertEqual(set(report["setup_checks"]), checks, report)
            with ProjectService(workspace, auto_run=False) as service:
                record = service.journal.read()["projects"][original["project_id"]]
                _, saved = service.repository.read(record["saved"])
                self.assertEqual(saved["revision_id"], report["saved_revision"])
                expected = deepcopy(active)
                expected["ports"][0]["name"] = "저장한 시험 급전"
                for key in ("ports", "board", "geometry", "nets", "stackup", "materials", "extensions"):
                    self.assertEqual(saved[key], expected[key], key)
                self.assertEqual(service.journal.read_artifact(snapshot["artifact"]), source)
                for key, raw in before.items():
                    self.assertEqual(service.journal.read_artifact(past_refs[key]), raw)

    def register_previous_result(self, service, original):
        """! @brief 기존 불변 Touchstone 결과와 정규화 자료를 먼저 저장한다."""
        project = original["project_id"]
        revision = original["revision_id"]
        data = {"expected_revision": revision, "operation": "import",
                "parameters": import_parameters(port=original["ports"][0]["id"])}
        preview_request = {"contract_version": "rfad.api/2.0", "context": {"project_id": project}, "input": data}
        review = network_service.read(service.host_calculation_context, "network.preview", preview_request)
        self.assertTrue(review["can_apply"], review)
        data.update(command_id=str(uuid4()), review_hash=review["review_hash"])
        result = service.mutate("network.apply", request(service, project, data))
        revision = result["new_revision"]
        service.mutate("project.save", request(service, project, {"expected_revision": revision}))
        service.run_next()
        preview_request["input"] = {"expected_revision": revision}
        return network_service.read(service.host_calculation_context, "network.library", preview_request)
