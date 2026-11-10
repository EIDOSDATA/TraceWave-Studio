"""! @brief 실제 고정 Linux 환경에서 사용자 PCB의 XML/실행/포트 후처리를 확인한다."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import build_pcb_plan, validate_result
from rfad.application.solver import make_prepared_plan
from test_pcb_solver import SETTINGS, fixture_document, snapshot_for
from test_pcb_ifa import IFA_SETTINGS, VIA_SETTINGS, ifa_document, via_document, vertical_feed_document
import test_openems_adapter as reference_tests


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 Linux solver venv와 RFAD_OPENEMS_NATIVE=1이 필요합니다.")
class PcbNativeTests(unittest.TestCase):
    """! @brief 사용자 물성/도체/급전이 실제 native 계산과 같은 raw 후처리에 소비되는지 검사한다."""

    setUp = reference_tests.OpenemsNativeTests.setUp
    tearDown = reference_tests.OpenemsNativeTests.tearDown
    stage = reference_tests.OpenemsNativeTests.stage
    request = reference_tests.OpenemsNativeTests.request
    copy_inputs = reference_tests.OpenemsNativeTests.copy_inputs

    def run_worker(self, stage, request, expected_code=0):
        """! @brief 큰 IFA와 얇은 국부 비아 격자의 명시적 실행 예산 안에서 worker를 검사한다."""
        from rfad.adapters.solvers.openems import native
        native.write_json(stage / "request.json", request)
        gate = canonical_bytes({"schema": "rfad.wsl-start/0.1", "run_id": request["run_id"], "nonce": request["nonce"]}) + b"\n"
        run = subprocess.run([sys.executable, "-I", "-B", "tools/openems_worker.py", "--request", "request.json"], cwd=stage,
                             input=gate, capture_output=True, timeout=300)
        path = stage / "output/result.json"
        result = json.loads(path.read_bytes()) if path.exists() else {}
        self.assertEqual(run.returncode, expected_code, str(result)[:3000] + run.stderr.decode(errors="replace"))
        return result

    def prepare_case(self, *, circle=False, arc=False, settings=None, document=None):
        """! @brief 전체 SnapshotRef와 실제 캡처 runtime으로 준비 artifact를 만든다."""
        stage, runtime = self.stage("prepare")
        document = document or fixture_document(circle=circle, arc=arc)
        plan = build_pcb_plan(document, snapshot_for(document), runtime, settings or SETTINGS)
        envelope = self.run_worker(stage, self.request("prepare", plan, runtime))
        preparation = envelope["preparation"]
        raw = canonical_bytes(plan)
        prep_file = next(f for f in envelope["files"] if f["role"] == "preparation_artifact")
        prepared = make_prepared_plan({"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan),
                                     "artifact": {"uri": "test/plan.json", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}},
                                     plan["snapshot"], {"uri": "test/preparation.json", "sha256": prep_file["sha256"], "bytes": prep_file["bytes"]}, runtime)
        return stage, runtime, plan, preparation, prepared

    def test_actual_user_pcb_solve_and_official_port_and_reprocess(self):
        """! @brief 유한전도 sheet와 유전체의 실제 FDTD 및 공식 CalcPort 동등성을 확인한다."""
        prepare_stage, runtime, plan, preparation, prepared = self.prepare_case()
        self.assertFalse((prepare_stage / "output/raw").exists())
        stage, runtime = self.stage("analysis")
        request = self.request("analysis", plan, runtime)
        request.update(preparation=preparation, prepared_plan=prepared)
        request["input_files"] = self.copy_inputs(prepare_stage, stage, preparation["files"])
        envelope = self.run_worker(stage, request)
        result = envelope["result"]
        validate_result(plan, result, prepared)
        self.assertFalse(result["assessment"]["physics_validated"])
        self.assertEqual(result["termination"]["status"], "end_criterion_reached")
        import numpy as np
        import CSXCAD
        import openEMS

        csx = CSXCAD.ContinuousStructure()
        solver = openEMS.openEMS()
        solver.SetCSX(csx)
        cfg = plan["case"]["port"]
        port = solver.AddLumpedPort(1, cfg["resistance_ohm"], cfg["start_mm"], cfg["stop_mm"], cfg["axis"], excite=1, priority=10)
        port.CalcPort(str(stage / "output/raw"), np.asarray([sample["frequency_hz"] for sample in result["samples"]]))
        for key, expected in (("s11", port.uf_ref / port.uf_inc), ("impedance_ohm", port.uf_tot / port.if_tot)):
            np.testing.assert_allclose([complex(*sample[key]) for sample in result["samples"]], expected, rtol=1e-10, atol=1e-10)
        post_stage, post_runtime = self.stage("postprocess")
        post_request = self.request("postprocess_only", plan, post_runtime)
        post_request.update(preparation=preparation, prepared_plan=prepared)
        post_request["input_files"] = self.copy_inputs(prepare_stage, post_stage, preparation["files"])
        post_request["input_files"] += self.copy_inputs(stage, post_stage, [f for f in envelope["files"] if f["role"].startswith("raw/") or f["role"] == "raw_manifest"])
        repeated = self.run_worker(post_stage, post_request)["result"]
        self.assertEqual(repeated["samples"], result["samples"])
        self.assertEqual(repeated["raw_manifest"], result["raw_manifest"])

    def test_circle_and_arc_native_xml_preserve_circle_and_source_mapping(self):
        """! @brief 원형 기판은 실제 cylinder, 원호는 허용오차를 가진 도체 polygon으로 준비한다."""
        stage, _, plan, preparation, _ = self.prepare_case(circle=True, arc=True)
        tree = ET.parse(stage / "output/prepared/pcb.xml")
        self.assertTrue(tree.findall(".//Cylinder"))
        self.assertTrue(tree.findall(".//Polygon"))
        self.assertEqual(preparation["consumption_report"]["board_native_primitive"], "cylinder")
        self.assertEqual({item["source_entity_id"] for item in preparation["consumption_report"]["source_mapping"]}, {shape["id"] for shape in plan["case"]["shapes"]})
        self.assertFalse(preparation["mesh_statistics"]["fdtd_executed"])
        self.assertFalse((stage / "output/raw").exists())

    def test_unmet_native_energy_target_is_failure_without_normalized_result(self):
        """! @brief 최대 반복 수에서 끝난 실제 FDTD를 정상 결과로 게시하지 않는다."""
        prepare_stage, _, plan, preparation, prepared = self.prepare_case(settings={**SETTINGS, "max_timesteps": 1000, "end_criterion": 1e-9})
        stage, runtime = self.stage("limited")
        request = self.request("analysis", plan, runtime)
        request.update(preparation=preparation, prepared_plan=prepared)
        request["input_files"] = self.copy_inputs(prepare_stage, stage, preparation["files"])
        result = self.run_worker(stage, request, expected_code=1)
        self.assertEqual(result["error"]["code"], "E_SOLVER")
        self.assertFalse((stage / "output/normalized.json").exists())

    def test_circle_and_arc_actual_native_execution(self):
        """! @brief 원형 유전체와 접속 원호가 실제 FDTD에서 유한 포트 결과를 만드는지 확인한다."""
        prepare_stage, _, plan, preparation, prepared = self.prepare_case(circle=True, arc=True)
        stage, runtime = self.stage("circle-analysis")
        request = self.request("analysis", plan, runtime)
        request.update(preparation=preparation, prepared_plan=prepared)
        request["input_files"] = self.copy_inputs(prepare_stage, stage, preparation["files"])
        result = self.run_worker(stage, request)["result"]
        validate_result(plan, result, prepared)
        self.assertEqual(result["provenance"]["analysis_plan"]["case"]["board"]["kind"], "circle")
        self.assertTrue(result["assessment"]["finite_samples"])
        self.assertFalse(result["assessment"]["physics_validated"])

    def test_explicit_ifa_ground_void_pad_and_short_actual_execution(self):
        """! @brief 명시적 가정 IFA의 독립 급전/단락/유한 접지를 실제로 계산한다."""
        prepare_stage, _, plan, preparation, prepared = self.prepare_case(document=ifa_document(), settings=IFA_SETTINGS)
        connectivity = preparation["consumption_report"]["native_connectivity"]
        self.assertEqual(len(connectivity["components"]), 1)
        self.assertGreater(connectivity["polygon_holes"][0]["open_electric_edges"], 1)
        stage, runtime = self.stage("ifa-analysis")
        request = self.request("analysis", plan, runtime)
        request.update(preparation=preparation, prepared_plan=prepared)
        request["input_files"] = self.copy_inputs(prepare_stage, stage, preparation["files"])
        result = self.run_worker(stage, request)["result"]
        validate_result(plan, result, prepared)
        self.assertFalse(result["assessment"]["physics_validated"])
        self.assertEqual(result["samples"][0]["frequency_hz"], 2.4e9)
        self.assertEqual(result["samples"][-1]["frequency_hz"], 2.4835e9)

    def test_hollow_finite_conductivity_pth_actual_execution(self):
        """! @brief 중공 PTH의 유한 kappa/실제 구멍과 native 격자 연결을 검사한다."""
        prepare_stage, _, plan, preparation, prepared = self.prepare_case(document=via_document(), settings=VIA_SETTINGS)
        tree = ET.parse(prepare_stage / "output/prepared/pcb.xml")
        self.assertEqual(len(tree.findall(".//CylindricalShell")), 1)
        self.assertTrue(preparation["consumption_report"]["native_connectivity"]["yee_connectivity_checked"])
        self.assertFalse(preparation["consumption_report"]["via_source_mapping"][0]["skin_depth_loss_validated"])
        stage, runtime = self.stage("pth-analysis")
        request = self.request("analysis", plan, runtime)
        request.update(preparation=preparation, prepared_plan=prepared)
        request["input_files"] = self.copy_inputs(prepare_stage, stage, preparation["files"])
        result = self.run_worker(stage, request)["result"]
        validate_result(plan, result, prepared)
        self.assertFalse(result["assessment"]["physics_validated"])
        self.assertNotIn("fallback to PEC", (stage / "output/raw/native.log").read_text())

    def test_vertical_lumped_port_native_execution(self):
        """! @brief z방향 포트가 실제 native 도체 면에 붙고 유한 결과를 만드는지 확인한다."""
        prepare_stage, _, plan, preparation, prepared = self.prepare_case(document=vertical_feed_document())
        stage, runtime = self.stage("vertical-analysis")
        request = self.request("analysis", plan, runtime)
        request.update(preparation=preparation, prepared_plan=prepared)
        request["input_files"] = self.copy_inputs(prepare_stage, stage, preparation["files"])
        result = self.run_worker(stage, request)["result"]
        validate_result(plan, result, prepared)
        self.assertTrue(result["assessment"]["finite_samples"])

    def test_reopened_native_pth_keeps_air_bore_and_finite_wall(self):
        """! @brief 저장 XML을 실제 CSXCAD로 다시 읽어 구멍 중심과 배럴 재료를 독립 확인한다."""
        stage, _, plan, _, _ = self.prepare_case(document=via_document(), settings=VIA_SETTINGS)
        import CSXCAD
        csx = CSXCAD.ContinuousStructure()
        # @brief CSXCAD reader는 openEMS wrapper가 아닌 ContinuousStructure root를 요구한다.
        source = ET.parse(stage / "output/prepared/pcb.xml").find("ContinuousStructure")
        self.assertIsNotNone(source)
        geometry_path = stage / "reopened-csx.xml"
        ET.ElementTree(source).write(geometry_path, encoding="utf-8", xml_declaration=True)
        self.assertEqual(csx.ReadFromXML(str(geometry_path)), "")
        via = plan["case"]["vias"][0]
        cx, cy = via["center_mm"]
        z = (via["z_min_mm"] + via["z_max_mm"]) / 2
        center = csx.GetPropertyByCoordPriority([cx, cy, z], prop_type=0x002 | 0x004)
        wall = csx.GetPropertyByCoordPriority([cx + (via["inner_radius_mm"] + via["outer_radius_mm"]) / 2, cy, z], prop_type=0x002 | 0x004)
        self.assertEqual(center.GetName(), "drill_" + via["id"])
        self.assertEqual(wall.GetName(), "via_" + via["id"])
        self.assertEqual(float(center.GetMaterialProperty("kappa")), 0.0)
        self.assertEqual(float(wall.GetMaterialProperty("kappa")), 58e6)


if __name__ == "__main__":
    unittest.main()
