"""! @brief 같은 PCB 여기의 복소 E/H 단면과 작은 체적 및 독립 격자 결과를 비교한다."""

import json
import math
import os
from pathlib import Path
from shutil import copyfile
from threading import RLock
from types import SimpleNamespace
import sys
import unittest

from rfad.application import result_fields
from rfad.application.pcb_field_probe import MAGNETIC_NAME, NAME, raw_names
from rfad.application.pcb_results import validate_preparation, validate_result
from rfad.application.pcb_solver import build_pcb_plan
from rfad.domain.errors import ProjectError
from test_pcb_solver import SETTINGS, fixture_document, runtime_identity, snapshot_for


PROBE = {"frequency_hz": 10e9, "x_mm": [6, 10], "y_mm": [4.5, 7.5], "z_mm": [1.1, 2.8], "magnetic": True}


class MagneticProbeTests(unittest.TestCase):
    def test_native_primary_and_dual_boxes_and_legacy_output(self):
        """! @brief 단면과 체적의 각 격자가 서로 독립이고 기존 E 단면의 파일/설정을 보존한다."""
        doc = fixture_document()
        snap = snapshot_for(doc)
        def plan(probe):
            """! @brief 동일 개정의 실제 solver 계획으로 요청을 확인한다."""
            return build_pcb_plan(doc, snap, runtime_identity(), {**SETTINGS, "field_probe": probe})
        for z in (2, PROBE["z_mm"]):
            item = plan({**PROBE, "z_mm": z})
            e = item["case"]["field_recording"]
            h = e["magnetic"]
            self.assertEqual(raw_names(item), (NAME, MAGNETIC_NAME))
            self.assertEqual((e["dump_type"], h["dump_type"]), (10, 11))
            self.assertNotEqual(e["start_mm"], h["start_mm"])
            for recording in (e, h):
                self.assertEqual(recording["start_indices"][2] == recording["stop_indices"][2], z == 2)
        for axis, position in (("x", 8), ("y", 6)):
            region = plan({**PROBE, axis + "_mm": position})["case"]["field_recording"]
            normal = "xyz".index(axis)
            for recording in (region, region["magnetic"]):
                self.assertEqual(recording["start_indices"][normal], recording["stop_indices"][normal])
        legacy = plan({k: (2 if k == "z_mm" else v) for k, v in PROBE.items() if k != "magnetic"})
        self.assertEqual(raw_names(legacy), (NAME,))
        self.assertEqual(legacy["case"]["field_recording"]["schema"], "rfad.pcb-electric-plane/0.1")
        for invalid in ({"z_mm": [2, 2]}, {"magnetic": 1}, {"x_mm": [7.01, 7.02]}):
            with self.assertRaises(ProjectError):
                plan({**PROBE, **invalid})

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 openEMS 필요")
    def test_two_native_grids_with_complex_fields(self):
        """! @brief 같은 물리 좌표에서 독립 두 격자의 장을 비교하고 모든 성분의 원본 HDF5와 대조한다."""
        import h5py
        import numpy as np
        from test_pcb_native import PcbNativeTests

        def interpolate(axes, values, point):
            """! @brief 두 독립 격자 비교용으로 시험점 주변 여덟 원시 표본만 삼선형 보간한다."""
            from itertools import product
            brackets = []
            for axis, pos in zip(axes, point):
                hi = int(np.searchsorted(axis, pos))
                self.assertTrue(0 < hi < len(axis))
                t = (pos - axis[hi - 1]) / (axis[hi] - axis[hi - 1])
                brackets.append([(hi - 1, 1 - t), (hi, t)])
            return sum(values[i, j, k] * a * b * c for ((i, a), (j, b), (k, c)) in product(*brackets))

        doc = fixture_document()
        measures = []
        plane_rows = {}
        cases = (("coarse", .5, "z", PROBE["z_mm"]), ("fine", .35, "z", PROBE["z_mm"]),
                 ("plane", .5, "z", 2.1), ("plane_x", .5, "x", 8.1), ("plane_y", .5, "y", 6.1))
        for label, width, axis, target in cases:
            plane = label.startswith("plane")
            normal = "xyz".index(axis)
            helper = PcbNativeTests()
            helper.setUp()
            try:
                settings = {**SETTINGS, "grid_mm": width, "end_criterion": 1e-5, "field_probe": {**PROBE, axis + "_mm": target}}
                prep, identity, plan, audit, prepared = helper.prepare_case(settings=settings, document=doc)
                validate_preparation(plan, audit)
                stage, identity = helper.stage("field")
                request = helper.request("analysis", plan, identity)
                request.update(preparation=audit, prepared_plan=prepared)
                request["input_files"] = helper.copy_inputs(prep, stage, audit["files"])
                run = helper.run_worker(stage, request)
                result = run["result"]
                validate_result(plan, result, prepared)
                output = os.environ.get("RFAD_PROBE_EVIDENCE")
                if output:
                    destination = Path(output) / label
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / "normalized.json").write_text(json.dumps(result), encoding="utf8")
                    for filename in (NAME, MAGNETIC_NAME):
                        copyfile(stage / "output" / "raw" / filename, destination / filename)
                observed = {}
                lines = audit["mesh_statistics"]["lines_mm"]
                for filename, prefix in zip((NAME, MAGNETIC_NAME), "EH"):
                    record = plan["case"]["field_recording"]
                    magnetic = prefix == "H"
                    if magnetic:
                        record = record["magnetic"]
                    with h5py.File(stage / "output" / "raw" / filename) as raw:
                        self.assertEqual(int(raw.attrs["dual_mesh"]), int(magnetic))
                        self.assertEqual(int(raw.attrs["dump_type"]), int(magnetic))
                        values = raw["FieldData/FD/f0"][:]
                        self.assertTrue(np.all(np.isfinite(values)))
                        for ci, comp in enumerate("xyz"):
                            axes = []
                            for i, ax in enumerate("xyz"):
                                a, b = record["start_indices"][i], record["stop_indices"][i]
                                line = np.array(lines[ax])
                                physical = (line[:-1] + line[1:]) / 2 if (ci == i) != magnetic else line
                                source = physical[a:b + 1]
                                axes.append(source)
                                base = (line[a:b + 1] + line[a + 1:b + 2]) * .5 if magnetic else line[a:b + 1]
                                np.testing.assert_allclose(np.array(raw["Mesh/" + ax]) * 1000, base, atol=1e-9, rtol=0)
                            if plane:
                                reference_axes, from_volume = plane_rows[prefix + comp]
                                coordinate = axes[normal][0]
                                slice_index = int(np.argmin(abs(reference_axes[normal] - coordinate)))
                                self.assertAlmostEqual(reference_axes[normal][slice_index], coordinate, places=9)
                                np.testing.assert_allclose(np.take(values[ci], 0, axis=normal),
                                    np.take(from_volume, slice_index, axis=normal), atol=1e-24, rtol=1e-5)
                            else:
                                if width == .5:
                                    plane_rows[prefix + comp] = (axes, values[ci])
                                observed[prefix + comp] = complex(interpolate(axes, values[ci], [8.5, 6.5, 2.1]))
                    print("grid", width, prefix, record["point_count"], record["start_mm"], record["stop_mm"], flush=True)
                if not plane:
                    measures.append(observed)
                    print("grid", width, "complex", observed, flush=True)
            finally:
                helper.tearDown()
        for prefix in "EH":
            vectors = [np.array([case[prefix + axis] for axis in "xyz"]) for case in measures]
            relative = float(np.linalg.norm(vectors[1] - vectors[0]) / np.linalg.norm(vectors[1]))
            print(prefix, "relative complex vector difference", relative, flush=True)
            self.assertTrue(math.isfinite(relative))
            self.assertGreater(np.linalg.norm(vectors[1]), 0)


    @unittest.skipUnless(os.environ.get("RFAD_PROBE_EVIDENCE"), "실제 native 필드 보존 폴더 필요")
    def test_recorded_result_reader_matches_all_complex_samples_and_positions(self):
        """! @brief 호스트 고정 HDF5 reader의 실제 봉인 확인, 급전 출처, XYZ 복소 단면을 원본과 대조한다."""
        import h5py
        import numpy as np
        for name in ("coarse", "fine", "plane"):
            root = Path(os.environ["RFAD_PROBE_EVIDENCE"]) / name
            result = json.loads((root / "normalized.json").read_bytes())
            plan = result["provenance"]["analysis_plan"]
            originals = result["raw_manifest"]["files"]
            owned = [{**row, "artifact": {"uri": "projects/fixture/" + Path(row["path"]).name,
                      "sha256": row["sha256"], "bytes": row["bytes"]}} for row in originals]
            resolved = {"normalized": result, "source": {"kind": "solver", "artifact_id": result["provenance"]["run_id"]},
                        "pin": {"plan": plan["plan_id"]}, "project": {"path": "projects/fixture"},
                        "solver_record": {"raw_files": owned, "normalized": {"uri": "projects/fixture/normalized.json"}}}
            service = SimpleNamespace(journal=SimpleNamespace(_mutex=RLock(), _ensure_open=lambda: None,
                                      _safe_path=lambda uri: root / Path(uri).name))
            desc = result_fields.describe(service, resolved)
            self.assertEqual(desc["drive_reference"]["port_id"], plan["case"]["port"]["id"])
            self.assertEqual([m["monitor_id"] for m in desc["monitors"]], ["probe_electric", "probe_magnetic"])
            for mon, filename in zip(desc["monitors"], (NAME, MAGNETIC_NAME)):
                magnetic = filename == MAGNETIC_NAME
                record = plan["case"]["field_recording"]
                if magnetic:
                    record = record["magnetic"]
                with h5py.File(root / filename) as raw:
                    values = raw["FieldData/FD/f0"][:]
                    for ci, comp in enumerate("xyz"):
                        for i, ax in enumerate("xyz"):
                            a, b = record["start_indices"][i], record["stop_indices"][i]
                            lines = np.array(result["mesh_statistics"]["lines_mm"][ax])
                            coords = (lines[:-1] + lines[1:]) / 2 if (ci == i) != magnetic else lines
                            np.testing.assert_allclose(mon["components"][ci]["coordinates_mm"][ax], coords[a:b + 1], atol=1e-10, rtol=0)
                        for normal, axis in enumerate("xyz"):
                            others = [i for i in range(3) if i != normal]
                            for index in range(values.shape[normal + 1]):
                                params = {"monitor_id": mon["monitor_id"], "frequency_index": 0, "component": comp,
                                    "plane": {"normal_axis": axis, "index": index}, "stride": 1,
                                    "roi": {"u_start": 0, "u_count": values.shape[others[0] + 1],
                                            "v_start": 0, "v_count": values.shape[others[1] + 1]}}
                                page = result_fields.page(service, resolved, params)
                                actual = np.asarray(page["values_ri"])
                                expected = np.take(values[ci], index, axis=normal).T
                                np.testing.assert_array_equal(actual[..., 0] + 1j * actual[..., 1], expected)
                                self.assertEqual(page["drive_reference"], desc["drive_reference"])
                                self.assertEqual(page["unit"], "A*s/m" if magnetic else "V*s/m")

            if name != "plane":
                self.check_faraday_in_air(root, result)

    def check_faraday_in_air(self, root, result):
        """! @brief 공기 중 같은 Yee 면에서 E 순환과 독립 기록 H의 시간 변화량을 비교한다."""
        import h5py
        import numpy as np
        record = result["provenance"]["analysis_plan"]["case"]["field_recording"]
        electric_origin = record["start_indices"]
        magnetic_origin = record["magnetic"]["start_indices"]
        lines = [np.array(result["mesh_statistics"]["lines_mm"][axis]) * .001 for axis in "xyz"]
        with h5py.File(root / NAME) as ef, h5py.File(root / MAGNETIC_NAME) as hf:
            electric = ef["FieldData/FD/f0"][:]
            magnetic = hf["FieldData/FD/f0"][:]
        circulation, induction = [], []
        omega = 2 * math.pi * record["frequency_hz"][0]
        for normal in range(3):
            u, v = (normal + 1) % 3, (normal + 2) % 3
            for local in np.ndindex(*magnetic.shape[1:]):
                idx = np.array(local) + magnetic_origin
                start = idx - electric_origin
                end_u, end_v = start.copy(), start.copy()
                end_u[u] += 1
                end_v[v] += 1
                if min(start) < 0 or any(end_u >= electric.shape[1:]) or any(end_v >= electric.shape[1:]):
                    continue
                du = lines[u][idx[u] + 1] - lines[u][idx[u]]
                dv = lines[v][idx[v] + 1] - lines[v][idx[v]]
                curl = ((electric[(v, *end_u)] - electric[(v, *start)]) / du
                        - (electric[(u, *end_v)] - electric[(u, *start)]) / dv)
                circulation.append(curl)
                induction.append(-1j * omega * (4e-7 * math.pi) * magnetic[(normal, *local)])
        self.assertGreater(len(induction), 0)
        relative = np.linalg.norm(np.array(circulation) - induction) / np.linalg.norm(induction)
        print(root.name, "discrete Faraday count/relative residual", len(induction), relative, flush=True)
        self.assertLess(relative, .002)
