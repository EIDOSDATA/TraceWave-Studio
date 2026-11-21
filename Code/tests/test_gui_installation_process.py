"""! @brief Windows Studio와 WSL에서 설치 상태의 저장, 실행 및 비교를 검증한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET

from rfad.application.projects import ProjectService
from rfad.domain.physical_setup import setup
from test_cad_worker_process import register_fixture
from test_pcb_environment import ENV_SETTINGS, add_case, board_fixture, ground_fixture
from test_physical_setup import load


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE")


@unittest.skipUnless(sys.platform == "win32" and GUI and os.environ.get("RFAD_TEST_WSL") == "1", "Windows Studio와 WSL 해석 worker가 필요합니다.")
class GuiInstallationTests(unittest.TestCase):
    def test_bare_board_and_case_store_reopen_and_compare(self):
        """! @brief 두 개의 실제 계산과 GUI에서 저장한 설치 원본을 검증한다."""
        self.verify_installations(kind="dielectric_case")

    def test_case_with_noncontact_pec_store_reopen_and_compare(self):
        """! @brief 같은 케이스에 비접촉 도체를 추가해 실제 해석하고 다시 연다."""
        self.verify_installations(kind="isolated_pec_box")

    def test_metal_grounding_yee_connection_and_reopen(self):
        """! @brief 같은 설치 물체를 급전 기준 패드에 연결하고 비접촉 스냅샷과 비교한다."""
        self.verify_installations(kind="grounded_pec_box")

    def verify_installations(self, *, kind):
        """! @brief 시나리오 편집과 실제 원본/XML/결과의 일치를 공통 흐름에서 검증한다."""
        metal = kind != "dielectric_case"
        grounded = kind == "grounded_pec_box"
        with TemporaryDirectory(prefix="TraceWave installation ") as temporary:
            directory = Path(temporary)
            workspace = directory / "work"
            document, previous_metal = ground_fixture() if grounded else (board_fixture(), None)
            if kind == "isolated_pec_box":
                add_case(document)
            if metal:
                (directory / "installation-part.json").write_text(json.dumps({"kind": kind}), encoding="utf-8")
            with ProjectService(workspace, auto_run=False) as service:
                original, _ = register_fixture(service, document)
            report = directory / "gui.json"
            settings = directory / "settings.json"
            settings.write_text(json.dumps(ENV_SETTINGS), encoding="utf-8")
            result = subprocess.run([GUI, "--python", sys.executable, "--source", str(ROOT / "src"),
                                     "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                                     "--openems-wsl", "--installation-smoke-test", "--solver-settings", str(settings),
                                     "--smoke-report", str(report)], capture_output=True, timeout=330)
            self.assertTrue(report.is_file(), result.stderr)
            verification = json.loads(report.read_bytes())
            self.assertEqual(result.returncode, 0, verification)
            self.assertIn("native_installation_reopen_s11_efficiency_radiation", verification["setup_checks"])
            with ProjectService(workspace, auto_run=False) as service:
                stored = load(service, original)
                self.assertEqual(stored["revision_id"], verification["saved_revision"])
                for key in ("board", "stackup", "geometry", "ports", "materials", "source_references", "measurement_sets"):
                    self.assertEqual(stored[key], original[key])
                model = setup(stored)
                for old in setup(original)["parts"]:
                    if old != previous_metal:
                        self.assertIn(old, model["parts"])
                unknown = next(item for item in model["parts"] if item["kind"] == "box")
                self.assertIsNone(unknown["material_id"])
                self.assertIsNone(unknown["width"]["value_si"])
                part = next(item for item in model["parts"] if item["kind"] == kind)
                self.assertIn("사용자 변경 사유: 내부 케이스 검증 출처", part["source_refs"])
                state = service.journal.read()
                records = list(state["solver_results"].values())
                results = [json.loads(service.journal.read_artifact(item["normalized"])) for item in records]
                self.assertEqual(len(results), 2)
                results.sort(key=lambda value: value["provenance"]["analysis_plan"]["snapshot"]["revision_id"] == stored["revision_id"])
                cases = [item["provenance"]["analysis_plan"]["case"] for item in results]
                if grounded:
                    first, second = [item["environment"]["parts"][1] for item in cases]
                    self.assertEqual((first["electrical_connection"], second["electrical_connection"]), ("isolated", "grounded"))
                    self.assertEqual(first["id"], second["id"])
                    self.assertEqual(part["id"], previous_metal["id"])
                    self.assertIn("시험 금속 원본 출처", part["source_refs"])
                elif metal:
                    self.assertEqual(cases[0]["environment"]["parts"], cases[1]["environment"]["parts"][:1])
                    self.assertEqual(cases[1]["environment"]["parts"][1]["electrical_connection"], "isolated")
                    self.assertFalse(cases[1]["environment"]["parts"][1]["material_values_consumed"])
                else:
                    self.assertNotIn("environment", cases[0])
                self.assertEqual(cases[1]["environment"]["parts"][-1]["id"], part["id"])
                self.assertEqual(cases[0]["port"], cases[1]["port"])
                self.assertNotEqual([r["s11"] for r in results[0]["samples"]], [r["s11"] for r in results[1]["samples"]])
                installed = next(r for r in records if r["snapshot"]["revision_id"] == stored["revision_id"])
                prepared = state["prepared_plans"][installed["prepared_plan_id"]]
                native_file = next(item["artifact"] for item in prepared["files"] if item["role"] == "native_input")
                xml = ET.fromstring(service.journal.read_artifact(native_file))
                tag = "Metal" if metal else "Material"
                material = xml.find(f".//{tag}[@Name='environment_{part['id']}']")
                self.assertIsNotNone(material)
                self.assertEqual(len(material.findall("./Primitives/Box")), 1 if metal else 5)
                if grounded:
                    reference = next(item["artifact"] for item in prepared["files"] if item["role"] == "consumption_report")
                    consumption = json.loads(service.journal.read_artifact(reference))
                    contact, = consumption["native_connectivity"]["grounded_environment"]
                    self.assertEqual(contact["part_id"], part["id"])
                    self.assertEqual(contact["ground_geometry_id"], original["ports"][0]["reference_geometry_id"])
                    self.assertGreater(contact["contact_nodes"], 0)
                    verification["native_contact"] = contact
                verification["solver_evidence"] = [{
                    "case": value["provenance"]["analysis_plan"]["case"].get("environment", {}).get("name", "기판 단독"),
                    "s11_at_10_ghz_ri": value["samples"][15]["s11"],
                    "radiation_summary": value["radiation_summary"],
                } for value in results]
                for value in results:
                    self.assertFalse(value["radiation_summary"]["physics_validated"])
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                path = Path(output)
                path.mkdir(parents=True, exist_ok=True)
                name = {"dielectric_case": "installation-gui.json", "isolated_pec_box": "installation-metal-gui.json",
                        "grounded_pec_box": "installation-grounded-gui.json"}[kind]
                (path / name).write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
