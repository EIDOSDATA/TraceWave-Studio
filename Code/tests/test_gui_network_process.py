"""! @brief 실제 Windows 복소 자료/RLC/목표 창의 저장 결과를 독립 서비스로 재검증한다."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.network_hdf5 import decode_network_hdf5
from rfad.application import network_service
from rfad.application.projects import ProjectService
from rfad.domain.network_library import KEY
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture
from test_design_rules import scenario
from test_network_service import import_parameters

ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


def request(service, project, data, mutation=False):
    """! @brief 시험도 제품의 개정과 영수증 계약을 통해 저장한다."""
    result = {"contract_version": "rfad.api/2.0", "context": {"project_id": project}, "input": data}
    if mutation:
        result.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
    return result


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiNetworkTests(unittest.TestCase):
    """! @brief native 대화상자에서 만든 불변 복소 자료와 과거 근거의 보존을 검사한다."""

    def test_native_import_rlc_assessment_history_and_reopen(self):
        """! @brief 오류 복구/명시 열 대응/원자 이력과 실제 재시작 결과를 함께 대조한다."""
        with TemporaryDirectory(prefix="TraceWave 복소 GUI ") as temporary:
            workspace = Path(temporary) / "작업 영역"
            original = scenario()
            target = original["targets"][0]
            target["band"] = {
                "start": Quantity.from_value(1, "GHz", source_refs=["GUI 명시 목표"]).to_dict(),
                "end": Quantity.from_value(2, "GHz", source_refs=["GUI 명시 목표"]).to_dict(),
                "reference": Quantity.from_value(1.5, "GHz", source_refs=["GUI 명시 목표"]).to_dict(),
                "sampling": {"kind": "linear", "count": 3},
            }
            target["port_id"] = original["ports"][0]["id"]
            target["reference_impedance"] = Quantity.from_value(50, "ohm", source_refs=["시험 기준 Z0"]).to_dict()
            original["extensions"]["test.reference"] = {
                "source_refs": ["사용자 원문 출처"], "manufacturing_condition": None, "measurement_condition": None,
            }
            for material in original["materials"]:
                if material["name"] == "Explicit test substrate":
                    material["tan_delta"] = Quantity(None, "dimensionless", "1", "missing", ["실제 제작 Df 미확보"]).to_dict()
            validate_project(original)
            project = original["project_id"]
            with ProjectService(workspace, auto_run=False) as service:
                original, snapshot = register_fixture(service, original)
                parameters = import_parameters(declared=False)
                parameters["name"] = "과거 미정 자료"
                preview = network_service.read(service.host_calculation_context, "network.preview", request(service, project,
                    {"expected_revision": original["revision_id"], "operation": "import", "parameters": parameters}))
                self.assertTrue(preview["can_apply"], preview)
                result = service.mutate("network.apply", request(service, project,
                    {"expected_revision": original["revision_id"], "operation": "import", "parameters": parameters,
                     "command_id": str(uuid4()), "review_hash": preview["review_hash"]}, True))
                baseline = service._load(service.journal.read()["projects"][project])
                old_entry = deepcopy(baseline["extensions"][KEY]["datasets"][0])
                old_files = {key: service.journal.read_artifact(old_entry[key]) for key in ("dataset", "raw", "normalized_hdf5")}
                save = service.mutate("project.save", request(service, project, {"expected_revision": result["new_revision"]}, True))
                service.run_next()
                saved = service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": save["job_id"]}})
                self.assertEqual(saved["state"], "completed", saved)
            raw = "! GUI 사용자 원문; 실제 측정 아님\n# Hz S RI R 50\n1000000000 0.1 0\n1500000000 0.1 0\n2000000000 0.1 0\n".encode("utf-8")
            csv = "주파수,실수,허수,생략 주석\n1,0.2,-0.1,원문 A\n1.5,0.3,-0.1,원문 B\n2,0.4,-0.1,원문 C\n".encode("utf-8")
            (workspace / "GUI 원문.s1p").write_bytes(raw)
            (workspace / "GUI 거절.s1p").write_bytes(b"# Hz S RI R 50\n1000 NaN 0\n")
            (workspace / "GUI 열 대응.csv").write_bytes(csv)
            report_path = Path(temporary) / "복소 자료 GUI 검증.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([
                str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--network-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, startupinfo=startup, timeout=240, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / "network.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2, report)
            self.assertEqual(set(report["setup_checks"]), {
                "network_late_response_close_destroy_safe", "network_definitive_rejection_preserves_draft",
                "network_uncertain_mutation_locks_replay", "network_dirty_close_requires_discard",
                "network_invalid_source_keeps_draft_editable", "network_unknown_preview_and_input_invalidation",
                "network_import_single_command_undo_redo", "network_rlc_missing_value_and_review_invalidation",
                "network_rlc_saved_definition_and_derived_candidate", "network_target_assessment_preserves_validation_boundary",
                "network_csv_explicit_mapping_preserves_unknown", "network_saved_service_restart_preserves_library",
                "network_explicit_s_to_z_preserves_source", "network_export_pair_and_existing_workspace_protection",
                "network_studio_results_marker_and_design_return",
                "network_studio_assessment_source_points_and_design_return",
                "network_frequency_units_preserve_si_and_revision",
            }, report)
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                stored = service._load(state["projects"][project])
                self.assertEqual(stored["revision_id"], report["saved_revision"])
                for key in ("board", "materials", "stackup", "geometry", "ports", "targets", "connections", "manufacturing_profiles", "parameters"):
                    self.assertEqual(stored[key], baseline[key], key)
                self.assertEqual({key: value for key, value in stored["extensions"].items() if key != KEY},
                                 {key: value for key, value in baseline["extensions"].items() if key != KEY})
                model = stored["extensions"][KEY]
                entries = {item["name"]: item for item in model["datasets"]}
                self.assertEqual(entries["과거 미정 자료"], old_entry)
                for key, payload in old_files.items():
                    self.assertEqual(service.journal.read_artifact(old_entry[key]), payload)
                imported = entries["GUI 신규 복소 자료"]
                canonical = json.loads(service.journal.read_artifact(imported["dataset"]))
                self.assertEqual(canonical["frequency_hz"], [1e9, 1.5e9, 2e9])
                self.assertEqual(service.journal.read_artifact(imported["raw"]), raw)
                self.assertEqual(imported["raw"]["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(decode_network_hdf5(service.journal.read_artifact(imported["normalized_hdf5"])), canonical)
                self.assertEqual(canonical["provenance"]["original_conditions"]["port_ids"], [])
                self.assertEqual(canonical["provenance"]["original_conditions"]["reference_planes"], [None])
                self.assertEqual(canonical["provenance"]["original_conditions"]["phasor_convention"], "unknown")
                self.assertEqual(canonical["reference_planes"], ["시험 기준면"])
                self.assertEqual(canonical["port_ids"], [target["port_id"]])
                self.assertIsNone(canonical["conditions"])
                exported = Path(temporary) / "GUI 교환.h5"
                self.assertEqual(exported.read_bytes(), service.journal.read_artifact(imported["normalized_hdf5"]))
                exported_conditions = json.loads(exported.with_name(exported.name + ".conditions.json").read_bytes())
                self.assertEqual(exported_conditions["provenance"], canonical["provenance"])
                self.assertFalse((workspace / "source.h5").exists())
                unknown_entry = entries["GUI 미정 CSV"]
                unknown = json.loads(service.journal.read_artifact(unknown_entry["dataset"]))
                self.assertEqual(service.journal.read_artifact(unknown_entry["raw"]), csv)
                self.assertIsNone(unknown["z0_ohm"])
                self.assertEqual(unknown["reference_planes"], [None])
                self.assertEqual(unknown["phasor_convention"], "unknown")
                self.assertIsNone(unknown["conditions"])
                derived_entry = entries["GUI RLC 결합"]
                derived = json.loads(service.journal.read_artifact(derived_entry["dataset"]))
                self.assertEqual(derived_entry["inputs"], [imported["id"]])
                self.assertEqual(derived_entry["circuit_id"], model["circuits"][0]["id"])
                self.assertAlmostEqual(derived["values_ri"][0][0][0][0], 11 / 29)
                self.assertEqual(derived["reference_planes"], ["입력 기준면"])
                self.assertIsNone(derived["conditions"])
                transformed_entry = entries["GUI Z 변환"]
                transformed = json.loads(service.journal.read_artifact(transformed_entry["dataset"]))
                self.assertEqual(transformed_entry["inputs"], [imported["id"]])
                self.assertEqual(transformed["parameter_kind"], "Z")
                self.assertAlmostEqual(transformed["values_ri"][0][0][0][0], 550 / 9)
                self.assertEqual(transformed["reference_planes"], canonical["reference_planes"])
                self.assertEqual(model["circuits"][0]["definition"]["elements"][0]["value"]["value_si"], 50)
                assessment = json.loads(service.journal.read_artifact(model["assessments"][0]["artifact"]))
                self.assertEqual(assessment["evidence"]["target_original"], target)
                self.assertFalse(assessment["continuous_band_verified"])
                self.assertFalse(assessment["physics_validated"])
                self.assertEqual(len(state["projects"][project]["history"]["undo"]), 7)
                sealed = workspace / snapshot["artifact"]["uri"]
                self.assertEqual(hashlib.sha256(sealed.read_bytes()).hexdigest(), snapshot["artifact"]["sha256"])
                self.assertTrue(all("solver" not in job for job in state["jobs"].values()))


if __name__ == "__main__":
    unittest.main()
