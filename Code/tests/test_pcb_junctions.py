"""! @brief 유한 PTH 접합층의 투영, 실제 GHz 급전과 독립 전도 손실을 확인한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_loss_components import validate_components
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_solver import build_pcb_plan
from rfad.domain.errors import ProjectError
from test_pcb_solver import runtime_identity, snapshot_for


ROOT = Path(__file__).resolve().parents[1]
JOINT_ID = "281389f8-cb5c-4f0c-83cb-59812d35b550"


def fixture(control):
    """! @brief 기존 수치 검증 PCB의 전도도 1000 S/m와 합성 접합 100 S/m를 같은 격자에서 비교한다."""
    document = json.loads((ROOT / "fixtures/pth_loss_numerical_reference.json").read_bytes())["document"]
    settings = json.loads((ROOT / "fixtures/pth_loss_reference_study.json").read_bytes())["cases"][0]["settings"]
    via = next(item for item in document["geometry"] if item["kind"] == "via")
    original = next(row for row in document["materials"] if row["id"] == via["material_ref"])
    material = deepcopy(original)
    material.update(id=JOINT_ID, name="Synthetic finite junction 100 S/m", assumptions=["Synthetic numerical test only"])
    material["conductivity"]["value_si"] = 100.0
    document["materials"].append(material)
    document["materials"].sort(key=lambda item: item["id"])
    settings["via_junctions"] = [{"via_id": via["id"], "end": "upper", "thickness_mm": 0.2,
                                  "material_id": original["id"] if control else JOINT_ID}]
    return document, settings


class JunctionTest(unittest.TestCase):
    """! @brief 같은 분할과 사용자 지정 물성의 연결 여부를 검사한다."""

    def test_projection_and_grid_and_errors(self):
        """! @brief 양 끝 중복, 존재하지 않는 재료 및 배럴 전체를 덮는 두께를 차단한다."""
        meshes = []
        for control in (True, False):
            doc, settings = fixture(control)
            plan = build_pcb_plan(doc, snapshot_for(doc), runtime_identity(), settings)
            via = plan["case"]["vias"][0]
            joint = via["junctions"][0]
            self.assertEqual(joint["conductivity_s_per_m"], 1000 if control else 100)
            self.assertAlmostEqual(joint["z_max_mm"], via["z_max_mm"])
            lines = mesh_lines(plan["case"])
            for position in (joint["z_min_mm"], joint["z_max_mm"] - 0.1, joint["z_max_mm"]):
                self.assertTrue(any(abs(z-position) < 1e-8 for z in lines["z"]))
            meshes.append(lines)
        self.assertEqual(*meshes)
        row = settings["via_junctions"][0]
        for bad in ([row, row], [{**row, "material_id": "00000000-0000-0000-0000-000000000000"}],
                    [{**row, "thickness_mm": 10.0}]):
            with self.assertRaises(ProjectError):
                build_pcb_plan(doc, snapshot_for(doc), runtime_identity(), {**settings, "via_junctions": bad})

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 Linux openEMS 필요")
    def test_arc_current_and_two_junction_conductivities(self):
        """! @brief 실제 포트의 공식 U/I와 복소 S 및 접합 E.J / sigma|E|^2를 대조한다."""
        import CSXCAD
        import numpy as np
        import openEMS
        from test_pcb_native import PcbNativeTests

        reports = []
        for control in (True, False):
            helper = PcbNativeTests()
            helper.setUp()
            try:
                doc, settings = fixture(control)
                prepared_stage, runtime, plan, preparation, prepared = helper.prepare_case(document=doc, settings=settings)
                stage, runtime = helper.stage("analysis")
                request = helper.request("analysis", plan, runtime)
                request.update(preparation=preparation, prepared_plan=prepared)
                request["input_files"] = helper.copy_inputs(prepared_stage, stage, preparation["files"])
                result = helper.run_worker(stage, request)["result"]
                cfg = plan["case"]["port"]
                structure = CSXCAD.ContinuousStructure()
                solver = openEMS.openEMS()
                solver.SetCSX(structure)
                port = solver.AddLumpedPort(1, cfg["resistance_ohm"], cfg["start_mm"], cfg["stop_mm"], cfg["axis"], excite=1, priority=10)
                freq = [row["frequency_hz"] for row in result["samples"]]
                port.CalcPort(str(stage / "output/raw"), np.asarray(freq))
                s11 = port.uf_ref / port.uf_inc
                np.testing.assert_allclose([complex(*row["s11"]) for row in result["samples"]], s11, rtol=1e-10, atol=1e-10)
                rows = result["power_balance"]["frequencies"]
                for row in rows:
                    i = freq.index(row["frequency_hz"])
                    accepted = 0.5 * np.real(port.uf_tot[i] * np.conj(port.if_tot[i]))
                    np.testing.assert_allclose(row["accepted_power_w_s2"], accepted, rtol=1e-9, atol=0)
                    self.assertGreater(row["junction_components"][0]["loss_w_s2"], 0)
                broken = deepcopy(rows[0])
                broken["junction_components"][0]["sigma_e2_w_s2"] *= 2
                with self.assertRaises(ProjectError):
                    validate_components(plan, broken)
                reports.append({"control": control, "mesh_sha256": canonical_hash(mesh_lines(plan["case"])),
                                "termination": result["termination"], "junction": plan["case"]["vias"][0]["junctions"][0],
                                "samples": result["samples"], "power": rows, "port": cfg})
                print(json.dumps({"control": control, "rows": [(r["frequency_hz"], r["junction_components"][0]["loss_w_s2"],
                      r["relative_residual"]) for r in rows]}), flush=True)
            finally:
                helper.tearDown()
        self.assertEqual(reports[0]["mesh_sha256"], reports[1]["mesh_sha256"])
        self.assertGreater(max(abs(complex(*a["s11"])-complex(*b["s11"])) for a,b in
                               zip(reports[0]["samples"], reports[1]["samples"])), 1e-8)
        if "RFAD_JUNCTION_REPORT" in os.environ:
            Path(os.environ["RFAD_JUNCTION_REPORT"]).write_text(json.dumps(reports), encoding="utf-8")
