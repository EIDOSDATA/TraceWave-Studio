"""! @brief 동일 PCB의 두 물성 구간을 독립 계산하며 경계 표본과 사용 물성이 보존되는지 확인한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest

from rfad.application.pcb_material_bands import split
from rfad.application.pcb_solver import build_pcb_plan
from rfad.domain.errors import ProjectError
from test_pcb_junctions import fixture, JOINT_ID
from test_pcb_solver import snapshot_for, runtime_identity


def cases():
    """! @brief 낮은/높은 대역에서 각각 출처를 지정한 합성 유전체와 합성 접합을 만든다."""
    doc, settings = fixture(False)
    original = next(m for m in doc["materials"] if m["id"] == next(layer["material_id"] for layer in doc["stackup"]
                                                                   if layer["role"] == "dielectric"))
    second = deepcopy(original)
    second.update(id="bce6e69b-72b4-4d44-a5ca-547fa0288e45", name="Synthetic upper band dielectric")
    second["tan_delta"]["value_si"] = 0.04
    second["assumptions"] = ["Synthetic upper band loss input for numerical reproduction"]
    doc["materials"].append(second)
    doc["materials"].sort(key=lambda row: row["id"])
    via = next(g for g in doc["geometry"] if g["kind"] == "via")
    settings["material_bands"] = [
        {"material_id": owner, "start_hz": low, "stop_hz": high, "source_material_id": source}
        for owner, first, last in [(original["id"], original["id"], second["id"]), (JOINT_ID, via["material_ref"], JOINT_ID)]
        for low, high, source in [(10e9, 10.5e9, first), (10.5e9, 11e9, last)]]
    return doc, settings


class BandTests(unittest.TestCase):
    """! @brief 물성 공백과 겹침을 차단하고 각 직접 주파수의 물성 근거를 남긴다."""

    def test_overlap_missing_and_boundary(self):
        doc, settings = cases()
        sources = {m["id"]: m for m in doc["materials"]}
        with self.assertRaises(ProjectError):
            build_pcb_plan(doc, snapshot_for(doc), runtime_identity(), settings)
        runs = split(settings, sources)
        self.assertEqual([r["frequency_hz"]["count"] for r in runs], [26, 26])
        self.assertEqual(runs[0]["frequency_hz"]["points"][-1], runs[1]["frequency_hz"]["points"][0])
        for index, run in enumerate(runs):
            plan = build_pcb_plan(doc, snapshot_for(doc), runtime_identity(), run)
            self.assertEqual(plan["case"]["vias"][0]["junctions"][0]["conductivity_s_per_m"], [1000,100][index])
            self.assertEqual(len([m for m in plan["case"]["materials"] if "frequency_band_source" in m]), 2)
        for changed in (10.4e9, 10.6e9):
            bad = deepcopy(settings)
            bad["material_bands"][0]["stop_hz"] = changed
            with self.assertRaises(ProjectError):
                split(bad, sources)

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 Linux openEMS 필요")
    def test_two_native_bands_keep_distinct_boundary(self):
        """! @brief 각 대역에 별도 펄스와 유효 물성을 사용하고 공통 끝점의 두 계산을 각각 검증한다."""
        from test_pcb_native import PcbNativeTests

        doc, settings = cases()
        rows = []
        for run in split(settings, {m["id"]: m for m in doc["materials"]}):
            helper = PcbNativeTests()
            helper.setUp()
            try:
                source, _, plan, preparation, prepared = helper.prepare_case(document=doc, settings=run)
                stage, runtime = helper.stage("analysis")
                request = helper.request("analysis", plan, runtime)
                request.update(preparation=preparation, prepared_plan=prepared)
                request["input_files"] = helper.copy_inputs(source, stage, preparation["files"])
                result = helper.run_worker(stage, request)["result"]
                self.assertEqual(result["termination"]["status"], "end_criterion_reached")
                rows.append({"samples": result["samples"], "power": result["power_balance"]["frequencies"],
                             "materials": plan["case"]["materials"], "termination": result["termination"]})
            finally:
                helper.tearDown()
        a, b = rows[0]["samples"][-1], rows[1]["samples"][0]
        self.assertEqual(a["frequency_hz"], b["frequency_hz"])
        self.assertNotEqual(a["s11"], b["s11"])
        if "RFAD_BAND_REPORT" in os.environ:
            Path(os.environ["RFAD_BAND_REPORT"]).write_text(json.dumps(rows), encoding="utf-8")
