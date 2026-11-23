"""! @brief 여섯 실제 Yee 격자의 개방면/폐곡면 적분을 해석식과 독립 보간기로 검산한다."""

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import unittest

from rfad.application.result_field_flux import integrate_surface
from rfad.domain.errors import ProjectError


PLANE = {"kind": "rectangle", "axis": "z", "direction": 1, "bounds_mm": [[7., 9.], [5., 7.], [2., 2.]]}
BOX = {"kind": "box", "bounds_mm": [[7., 9.], [5., 7.], [1.75, 2.2]]}


class FieldFluxTests(unittest.TestCase):
    def test_staggered_nonuniform_wave_orientation_area_and_signed_box(self):
        """! @brief 주파수 스펙트럼의 평면파와 단면별 선형 진폭으로 면적과 닫힌 합을 검산한다."""
        import numpy as np

        for normal in range(3):
            tangent, transverse = (normal + 1) % 3, (normal + 2) % 3
            e, h = [], []
            for magnetic, fields in ((False, e), (True, h)):
                for i in range(3):
                    coords = {}
                    for j, axis in enumerate("xyz"):
                        line = np.array([-2., -1., 0., .3, 2., 2.5, 4., 7.])
                        coords[axis] = ((line[:-1] + line[1:]) * .5 if (i == j) != magnetic else line[:-1]).tolist()
                    grid = np.meshgrid(*(coords[a] for a in "xyz"), indexing="ij")
                    signal = (2. + 3j) * (1 + grid[normal] * .1)
                    array = signal / 377 if magnetic and i == transverse else signal if not magnetic and i == tangent else signal * 0
                    fields.append((coords, array))
            bounds = [[.2, 1.2], [.4, 1.9], [.6, 2.6]]
            area = math.prod(hi - lo for i, (lo, hi) in enumerate(bounds) if i != normal) * 1e-6
            def expected(pos):
                """! @brief 선택 위치에서 평면파의 시간 평균 통과량을 해석식으로 계산한다."""
                return 6.5 / 377 * (1 + pos * .1) ** 2 * area
            result = integrate_surface(e, h, {"kind": "box", "bounds_mm": bounds})
            self.assertEqual(len(result["faces"]), 6)
            self.assertAlmostEqual(result["total_flux_w_s2"], expected(bounds[normal][1]) - expected(bounds[normal][0]), delta=1e-21)
            plane = {"kind": "rectangle", "axis": "xyz"[normal], "bounds_mm": deepcopy(bounds)}
            plane["bounds_mm"][normal] = [.8, .8]
            for sign in (-1, 1):
                result = integrate_surface(e, h, {**plane, "direction": sign})
                self.assertAlmostEqual(result["total_flux_w_s2"], sign * expected(.8), delta=1e-21)
                self.assertAlmostEqual(result["faces"][0]["area_m2"], area, delta=1e-21)
            for bad in ({"bounds_mm": [[0, 0]] * 3}, {"direction": 0}, {"bounds_mm": [[-5, 0]] * 3}):
                with self.assertRaises(ProjectError):
                    integrate_surface(e, h, {**plane, "direction": 1, **bad})

    def test_single_traveling_plane_wave_and_closed_surface(self):
        """! @brief 실제 위상이 진행하는 자유공간 단일 평면파의 부호, 면적 및 닫힌 합을 대조한다."""
        import numpy as np

        k_per_mm = 2 * math.pi * 2e9 / 299792458. * .001
        impedance = 376.730313668
        e, h = [], []
        for magnetic, fields in ((False, e), (True, h)):
            for component in range(3):
                line = np.array([-.8, -.3, .1, .36, .7, 1.14, 1.5, 1.9, 2.2, 2.6])
                coords = {axis: (((line[:-1] + line[1:]) / 2) if (component == j) != magnetic else line[:-1]).tolist()
                          for j, axis in enumerate("xyz")}
                grid = np.meshgrid(*coords.values(), indexing="ij")
                phasor = (2. + 3j) * np.exp(-1j * k_per_mm * grid[2])
                value = phasor / impedance if magnetic and component == 1 else phasor if not magnetic and component == 0 else phasor * 0
                fields.append((coords, value))
        bounds = [[0., 1.5], [.3, 1.7], [.42, .42]]
        expected = .5 * 13 / impedance * 1.5 * 1.4e-6
        for sign in (-1, 1):
            out = integrate_surface(e, h, {"kind": "rectangle", "axis": "z", "direction": sign, "bounds_mm": bounds})
            self.assertLess(abs(out["total_flux_w_s2"] / expected - sign), .0001)
        box = {"kind": "box", "bounds_mm": [bounds[0], bounds[1], [.42, 1.24]]}
        out = integrate_surface(e, h, box)
        self.assertLess(abs(out["total_flux_w_s2"] / expected), .0001)

    @unittest.skipUnless(os.environ.get("RFAD_PROBE_EVIDENCE"), "두 실제 native 격자 기록 필요")
    def test_two_native_grids_against_scipy_tensor_simpson(self):
        """! @brief 실제 raw를 직접 읽고 SciPy 정규격자 보간과 구간별 Simpson 합으로 여섯 면을 검산한다."""
        import h5py
        import numpy as np
        from scipy.interpolate import RegularGridInterpolator

        for label in ("coarse", "fine"):
            root = Path(os.environ["RFAD_PROBE_EVIDENCE"]) / label
            result = json.loads((root / "normalized.json").read_bytes())
            plan = result["provenance"]["analysis_plan"]["case"]["field_recording"]
            lines = [np.array(result["mesh_statistics"]["lines_mm"][a]) for a in "xyz"]
            e, h, interpolators, fingerprints = [], [], [], {}
            for is_h, fields in ((False, e), (True, h)):
                recording = plan["magnetic"] if is_h else plan
                path = root / ("pcb_probe_H.h5" if is_h else "pcb_probe_E.h5")
                fingerprints[path] = hashlib.sha256(path.read_bytes()).hexdigest()
                with h5py.File(path) as raw:
                    values = raw["FieldData/FD/f0"][:]
                for i in range(3):
                    coords = {}
                    for j, axis in enumerate("xyz"):
                        line = lines[j]
                        nodes = (line[:-1] + line[1:]) * .5 if (i == j) != is_h else line
                        coords[axis] = nodes[recording["start_indices"][j]:recording["stop_indices"][j]+1].tolist()
                    fields.append((coords, values[i]))
                    interpolators.append(RegularGridInterpolator(tuple(coords.values()), values[i]))
            for surface in (PLANE, BOX):
                total = integrate_surface(e, h, surface)
                independent = []
                for face in total["faces"]:
                    n = "xyz".index(face["axis"])
                    transverse = [i for i in range(3) if i != n]
                    positions, weights = {}, {}
                    for i in transverse:
                        lo, hi = face["bounds_mm"][i]
                        axis = "xyz"[i]
                        nodes = sorted({lo, hi} | {k for c, _ in e+h for k in c[axis] if lo < k < hi})
                        weights[i] = np.zeros(2 * len(nodes) - 1)
                        positions[i] = np.empty_like(weights[i])
                        for j, (a, b) in enumerate(zip(nodes, nodes[1:])):
                            positions[i][2*j:2*j+3] = (a, (a+b)/2, b)
                            weights[i][2*j:2*j+3] += np.array([1, 4, 1]) * (b-a)/6
                    i, j = transverse
                    u, v = np.meshgrid(positions[i], positions[j], indexing="ij")
                    points = np.empty((*u.shape, 3))
                    points[:, :, i], points[:, :, j], points[:, :, n] = u, v, face["bounds_mm"][n][0]
                    vectors = [np.stack([interpolators[k](points) for k in indices], axis=-1)
                               for indices in ((0, 1, 2), (3, 4, 5))]
                    density = np.cross(vectors[0], vectors[1].conj()).real[:, :, n] / 2
                    actual = np.sum(weights[i][:, None] * weights[j][None, :] * density) * 1e-6 * face["direction"]
                    independent.append(float(actual))
                    np.testing.assert_allclose(face["flux_w_s2"], actual, rtol=1e-12, atol=1e-44)
                self.assertAlmostEqual(total["total_flux_w_s2"], math.fsum(independent),
                                       delta=max(1e-44, sum(map(abs, independent)) * 1e-12))
                print(label, surface["kind"], "native W*s^2", total["total_flux_w_s2"], "independent", independent, flush=True)
            for path, before in fingerprints.items():
                self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    @unittest.skipUnless(os.environ.get("RFAD_PROBE_EVIDENCE"), "실제 단면 및 체적의 봉인 기록 필요")
    def test_plane_only_and_absent_monitor_are_rejected(self):
        """! @brief 실제 평면만 기록한 결과와 E만 기록한 결과에서 면 전력을 유추하지 않는다."""
        from rfad.application.result_field_flux import _volume

        root = Path(os.environ["RFAD_PROBE_EVIDENCE"])
        plane = json.loads((root / "plane" / "normalized.json").read_bytes())
        resolved = {"normalized": plane, "solver_record": {}}
        with self.assertRaises(ProjectError) as issue:
            _volume(None, resolved, "probe_electric", 0)
        self.assertEqual(issue.exception.code, "E_UNSUPPORTED")
        electric = json.loads((root / "coarse" / "normalized.json").read_bytes())
        del electric["provenance"]["analysis_plan"]["case"]["field_recording"]["magnetic"]
        with self.assertRaises(ProjectError) as issue:
            _volume(None, {"normalized": electric, "solver_record": {}}, "probe_magnetic", 0)
        self.assertEqual(issue.exception.code, "E_UNSUPPORTED")

    @unittest.skipUnless(os.environ.get("RFAD_FLUX_WORKSPACE") and os.environ.get("RFAD_FLUX_ARTIFACT"),
                         "실제 봉인된 E/H 체적 프로젝트 필요")
    def test_service_seal_domain_frequency_and_reopen(self):
        """! @brief 일반 서비스에서 공통 영역 밖, 잘못된 주파수와 원본 손상을 검출한다."""
        from shutil import copytree
        from tempfile import TemporaryDirectory
        from rfad.application import result_service
        from rfad.application.projects import ProjectService

        source = {"kind": "solver", "artifact_id": os.environ["RFAD_FLUX_ARTIFACT"]}
        with TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            copytree(os.environ["RFAD_FLUX_WORKSPACE"], workspace)
            with ProjectService(workspace, auto_run=False) as service:
                record = service.journal.read()["solver_results"][source["artifact_id"]]
                envelope = {"contract_version": "rfad.api/2.0", "context": {"project_id": record["project_id"]},
                            "input": {"source": source}}
                pin = result_service.read(service, "result.describe", envelope)["pin"]
                query = {"source": source, "pin": pin, "surface": BOX, "frequency_index": 0}
                value = result_service.read(service, "result.field.flux", {**envelope, "input": query})
                for change in ({"frequency_index": 100}, {"surface": {**PLANE, "bounds_mm": [[1, 9], [5, 7], [2, 2]]}}):
                    with self.assertRaises(ProjectError) as issue:
                        result_service.read(service, "result.field.flux", {**envelope, "input": {**query, **change}})
                    self.assertEqual(issue.exception.code, "E_SCHEMA")
            with ProjectService(workspace, auto_run=False) as service:
                self.assertEqual(result_service.read(service, "result.field.flux", {**envelope, "input": query}), value)
                path = workspace / value["magnetic_ref"]["uri"]
                with path.open("r+b") as raw:
                    raw.seek(-1, 2)
                    original = raw.read(1)[0]
                    raw.seek(-1, 2)
                    raw.write(bytes([original ^ 1]))
                with self.assertRaises(ProjectError) as issue:
                    result_service.read(service, "result.field.flux", {**envelope, "input": query})
                self.assertEqual(issue.exception.code, "E_HASH")
