"""! @brief 명시적 총 손실 모델을 2층 합성 IFA의 실제 CAD/openEMS와 재열기로 검증한다.

@details 기존 fixture의 시험 가정을 사용하며 실제 JLC 재료나 제조품을
검증하지 않는다. WSL과 격리 CAD를 모두 명시적으로 활성화해야 실행한다.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from catalog_pcb_verification.common import call, publish_report, read_json_artifact, wait
from catalog_pcb_verification.runner import run as run_integration
from rfad.application.cad_runtime import CadRuntime
from rfad.application.pcb_projection import EPSILON0
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from rfad.catalog.build import build_catalog
from rfad.domain.material_models import TOTAL_TAN_DELTA_MODEL
from rfad.domain.pcb_selection import EXTENSION_KEY
from test_catalog_pcb_solver_native import fixture_catalog, native_output
from verify_pcb_worker import create_fixture


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_TEST_WSL") == "1"
                     and os.environ.get("RFAD_CAD_PYTHON"),
                     "RFAD_TEST_WSL=1과 RFAD_CAD_PYTHON으로 실제 WSL/CAD 환경을 함께 지정해야 합니다.")
class MaterialLossModelNativeTests(unittest.TestCase):
    """! @brief 총 Df 선택의 source/plan/native XML/결과 소비 의미를 실제 worker에서 대조한다."""

    def select_fixture(self, service, fixture, catalog, substrate):
        """! @brief 공개 선택 명령으로 기존 시험 Dk/Df와 모델을 채택하고 별도 전도도는 미정으로 남긴다."""
        context, project_path, initial = create_fixture(service, fixture)
        before = read_json_artifact(service, initial["artifact"])
        reason = "기존 ifa_feed_smoke의 시험 Dk/Df와 적용 대역만 복사함. 실제 제조사 물성 또는 측정 증거가 아님."
        model_reason = "총 전기 손실을 시험 Df로 표현하는 모델을 명시 선택함. 독립 전도도는 소비하지 않으며 0으로 채우지 않음."
        material = {
            "key": "fixture-total-loss-core", "name": substrate["name"],
            "model": TOTAL_TAN_DELTA_MODEL, "model_reason": model_reason,
            "properties": {field: {"mode": "catalog", "record_id": "EXPLICIT-FIXTURE", "reason": reason}
                           for field in ("epsilon_r", "tan_delta")},
            "validity_hz": {boundary: substrate["validity_hz"][boundary]["value_si"] for boundary in ("min", "max")},
        }
        material["properties"]["conductivity"] = {"mode": "missing", "reason": model_reason}
        material["validity_hz"]["reason"] = reason
        requested = {"expected_revision": initial["revision_id"], "selection_id": str(uuid4()),
                     "specification": {"source": None, "catalog_id": catalog["catalog_id"], "materials": [material],
                                       "material_ids": {material["key"]: substrate["id"]}, "notes": [reason, model_reason]}}
        preview = call(service, "pcb.selection.preview", requested, context)
        self.assertTrue(preview["can_apply"], preview["issues"])
        changed = call(service, "pcb.selection.apply", {
            **requested, "preview_hash": preview["preview_hash"], "command_id": str(uuid4()),
        }, context, mutation=True)
        wait(service, call(service, "project.save", {"expected_revision": changed["new_revision"]}, context, mutation=True))
        selected, _ = wait(service, call(service, "snapshot.create", {
            "expected_revision": changed["new_revision"], "description": "합성 IFA 총 손실 모델의 명시 선택; 실제 제조사 자료가 아님",
        }, context, mutation=True))
        after = read_json_artifact(service, selected["artifact"])
        for collection in ("board", "stackup", "geometry", "ports", "nets"):
            self.assertEqual(after[collection], before[collection])
        for previous, current in zip(before["materials"], after["materials"], strict=True):
            self.assertEqual(previous["id"], current["id"])
            if current["id"] == substrate["id"]:
                self.assertEqual(current["model"], TOTAL_TAN_DELTA_MODEL)
                self.assertIsNone(current["conductivity"]["value_si"])
                self.assertEqual(current["conductivity"]["status"], "missing")
                for field in ("epsilon_r", "tan_delta"):
                    self.assertEqual(current[field]["value_si"], previous[field]["value_si"])
                self.assertEqual([current["validity_hz"][key]["value_si"] for key in ("min", "max")],
                                 [previous["validity_hz"][key]["value_si"] for key in ("min", "max")])
            else:
                self.assertEqual(current, previous)
        selection = after["extensions"][EXTENSION_KEY]
        decisions = [entry for entry in selection["decisions"] if entry["target"]["field"] == "model"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["basis"], "user_assumption")
        self.assertEqual(decisions[0]["reason"], model_reason)
        return project_path, selected, substrate["id"]

    def check_native_loss(self, workspace, report, material_id):
        """! @brief 준비 및 실제 실행 XML이 총 Df 손실만 사용하고 원본 전도도는 미정인지 확인한다."""
        with ProjectService(workspace, auto_run=False) as service:
            solver = report["solver"]
            plan = read_json_artifact(service, solver["analysis_plan"]["artifact"])
            prepared = read_json_artifact(service, solver["preparation_artifact"])
            result = read_json_artifact(service, solver["result"])
            for document in (read_json_artifact(service, report["snapshot"]["artifact"]), plan["source_semantics"],
                             result["provenance"]["analysis_plan"]["source_semantics"]):
                source = next(item for item in document["materials"] if item["id"] == material_id)
                self.assertEqual(source["model"], TOTAL_TAN_DELTA_MODEL)
                self.assertIsNone(source["conductivity"]["value_si"])
                self.assertEqual(source["conductivity"]["status"], "missing")
            consumed = next(item for item in plan["case"]["materials"] if item["id"] == material_id)
            self.assertEqual(consumed["consumed_properties"], ["epsilon_r", "tan_delta"])
            self.assertEqual(consumed["unconsumed_properties"], ["conductivity"])
            self.assertNotIn("conductivity_s_per_m", consumed)
            self.assertEqual(prepared["consumption_report"]["consumed_case"], plan["case"])
            self.assertEqual(result["provenance"]["preparation"], prepared)
            layer = next(item for item in plan["case"]["layers"] if item["material_id"] == material_id)
            self.assertEqual(layer["loss_model"], TOTAL_TAN_DELTA_MODEL)
            self.assertEqual(layer["loss_partition"], consumed["loss_partition"])
            expected = 2 * math.pi * layer["loss_reference_frequency_hz"] * EPSILON0 * consumed["epsilon_r"] * consumed["tan_delta"]
            self.assertEqual(layer["kappa_s_per_m"], expected)
            raw = next(item for item in solver["restoration"]["view"]["files"] if item["role"] == "raw/pcb.xml")
            xml_bytes = service.journal.read_artifact({key: raw[key] for key in ("uri", "sha256", "bytes")})
            tree = ElementTree.fromstring(xml_bytes)
            nodes = [item for item in tree.findall(".//Material") if item.get("Name") == "dielectric_" + layer["id"]]
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0].get("Isotropy"), "1")
            properties = nodes[0].find("Property")
            self.assertIsNotNone(properties)
            observed_kappa = float(properties.get("Kappa").split(",")[0])
            observed_epsilon = float(properties.get("Epsilon").split(",")[0])
            self.assertTrue(math.isclose(observed_kappa, expected, rel_tol=1e-6))
            self.assertTrue(math.isclose(observed_epsilon, consumed["epsilon_r"], rel_tol=1e-6))
            return {"status": "passed", "source_conductivity_still_missing": True, "separate_conductivity_consumed": False,
                    "total_tan_delta_consumed": consumed["tan_delta"], "epsilon_r_consumed": consumed["epsilon_r"],
                    "reference_frequency_hz": layer["loss_reference_frequency_hz"], "planned_kappa_s_per_m": expected,
                    "native_xml_kappa_s_per_m": observed_kappa, "native_xml_sha256": raw["sha256"]}

    def test_total_tan_delta_catalog_selection_reaches_native_and_reopens(self):
        """! @brief 같은 불변 스냅샷의 CAD/STEP/실제 해석/재후처리와 런타임 없는 재열기를 확인한다."""
        fixture_path = Path(__file__).resolve().parents[1] / "fixtures/ifa_feed_smoke.json"
        fixture_bytes = fixture_path.read_bytes()
        fixture = json.loads(fixture_bytes)
        self.assertEqual(sum(layer["role"] == "conductor" for layer in fixture["document"]["stackup"]), 2)
        with native_output("total-tan-delta") as output:
            database = output / "synthetic-catalog.sqlite"
            substrate = fixture_catalog(output / "synthetic-source", fixture, fixture_path.stem)
            catalog = build_catalog(output / "synthetic-source", database)
            workspace = output / "workspace"
            with ProjectService(workspace, catalog_database=database) as service:
                project_path, selected, material_id = self.select_fixture(service, fixture, catalog, substrate)
            report_path = output / "report.json"
            report = run_integration(workspace, project_path, report_path, mode="full", expected_revision=selected["revision_id"],
                                     settings=fixture["settings"], cad_runtime=CadRuntime(Path(os.environ["RFAD_CAD_PYTHON"])),
                                     solver_runtime=SolverRuntime())
            report.update(evidence_scope="synthetic_catalog_explicit_ifa_total_tan_delta_model_only",
                          actual_manufacturer_pcb_tested=False, fixture_source="fixtures/ifa_feed_smoke.json",
                          original_fixture_sha256=hashlib.sha256(fixture_bytes).hexdigest())
            try:
                self.assertEqual(report["status"], "passed", {
                    "report": str(report_path), "failures": report.get("failures", []),
                    "error": report.get("error"),
                })
                self.assertTrue(report["restored_without_catalog_or_workers"])
                self.assertTrue(report["project_unchanged"])
                self.assertEqual(report["snapshot"], report["solver"]["snapshot"])
                self.assertFalse(report["solver"]["assessment"]["physics_validated"])
                self.assertEqual(fixture_path.read_bytes(), fixture_bytes)
                report["material_loss_checks"] = self.check_native_loss(workspace, report, material_id)
            except Exception as error:
                report.update(status="failed", material_loss_checks={"status": "failed", "message": str(error)})
                raise
            finally:
                publish_report(report_path, report)


if __name__ == "__main__":
    unittest.main()
