"""! @brief 보드의 동일한 물리 곡면에서 삼각화와 실제 Yee 격자의 영향을 검증한다."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from rfad.adapters import field_hdf5
from rfad.adapters.solvers.openems.pcb import add_geometry, statistics_and_termination
from rfad.adapters.solvers.openems.pcb_mesh import audit_native_mesh
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_field_probe import NAME, MAGNETIC_NAME
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_projection import project_pcb
from rfad.application.pcb_solver import check_pcb_input
from rfad.application import result_fields
from rfad.application.result_field_flux import integrate_surface


FREQUENCY = 10e9
CENTER = (0., 0., 2.8)
RADIUS = 0.9


def _record(case_file, executable, folder, pitch):
    """! @brief 제품 PCB 투영을 그대로 사용해 E/H 체적 두 파일을 실제 실행에서 얻는다."""
    import CSXCAD
    import openEMS

    original = json.loads(case_file.read_bytes())
    settings = {**original["settings"], "grid_mm": pitch, "air_padding_mm": 8,
                "compute_profile": {"kind": "tuning_refinement/0.1", "num_threads": 4},
                "field_probe": {"frequency_hz": FREQUENCY, "x_mm": [-2.1, 2.1], "y_mm": [-2.1, 2.1],
                                "z_mm": [1.1, 4.45], "magnetic": True}}
    if pitch < 0.30:
        settings["field_probe"].update(x_mm=[-1.7, 1.7], y_mm=[-1.7, 1.7])
    document = original["document"]
    check_pcb_input(document, settings)
    case = project_pcb(document, settings)["case"]
    lines = mesh_lines(case)
    region = case["field_recording"]
    folder.mkdir()
    csx = CSXCAD.ContinuousStructure()
    fdtd = openEMS.openEMS(NrTS=settings["max_timesteps"], EndCriteria=settings["end_criterion"])
    fdtd.SetCellConstantMaterial(False)
    fdtd.SetCSX(csx)
    fdtd.SetGaussExcite(case["excitation"]["center_hz"], case["excitation"]["width_hz"])
    fdtd.SetBoundaryCond(case["boundary_conditions"])
    grid = csx.GetGrid()
    grid.SetDeltaUnit(0.001)
    for axis, values in lines.items():
        grid.AddLine(axis, values)
    add_geometry(csx, case)
    audit_native_mesh(csx, case, lines)
    port = case["port"]
    fdtd.AddLumpedPort(1, port["resistance_ohm"], port["start_mm"], port["stop_mm"], port["axis"],
                      excite=1, priority=10)
    for name, record in ((NAME, region), (MAGNETIC_NAME, region["magnetic"])):
        field = csx.AddDump(name[:-3], dump_type=record["dump_type"], dump_mode=0,
                            file_type=1, frequency=[FREQUENCY])
        field.AddBox(record["primitive_start_mm"], record["primitive_stop_mm"])
    fdtd.Write2XML(str(folder / "pcb.xml"))
    with (folder / "native.log").open("xb") as log:
        subprocess.run([str(executable), "pcb.xml", "--engine=multithreaded", "--numThreads=4",
                        "--dump-statistics", "--exact-endcriteria"], cwd=folder, stdin=subprocess.DEVNULL,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
    statistics, termination = statistics_and_termination(folder, {"case": case})
    if termination["status"] != "end_criterion_reached":
        raise RuntimeError(str(termination))
    files = {name: _identity(folder / name) for name in (NAME, MAGNETIC_NAME, "pcb.xml", "native.log", "openEMS_stats.txt")}
    _write(folder / "recording.json", {"grid_mm": pitch, "lines": lines, "region": region, "frequency_hz": FREQUENCY,
        "document_sha256": canonical_hash(document), "statistics": statistics, "termination": termination, "files": files})


def _identity(path):
    """! @brief 읽기 전에 확인할 원문 바이트 수와 SHA-256을 반환한다."""
    content = path.read_bytes()
    return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "uri": path.name}


def _write(path, value):
    """! @brief 새 증거 파일에만 기록한다."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def _volume(folder, info, magnetic):
    """! @brief 실제 계획의 primary/dual 축과 원문 배열을 제품 reader로 대조한다."""
    lines = info["lines"]
    recording = info["region"]["magnetic"] if magnetic else info["region"]
    starts, stops = recording["start_indices"], recording["stop_indices"]
    edges = {axis: lines[axis][a:b + 1] for axis, a, b in zip("xyz", starts, stops)}
    following = {axis: lines[axis][b + 1] for axis, b in zip("xyz", stops)}
    primary = edges
    if magnetic:
        primary = {axis: [(a + b) / 2 for a, b in zip(row, row[1:] + [following[axis]])]
                   for axis, row in edges.items()}
    shape = [len(row) for row in edges.values()]
    name = MAGNETIC_NAME if magnetic else NAME
    expected = {"shape": shape, "frequency_hz": recording["frequency_hz"], "primary_coordinates_mm": primary,
                "dump_type": int(magnetic), "dual_mesh": int(magnetic)}
    with field_hdf5.opened(folder / name, info["files"][name]) as (handle, h5py, np):
        datasets, axes = field_hdf5.inspect(handle, h5py, np, expected, max_points=4096)
        data = np.array(datasets[0], dtype=np.complex128)
    model = {"magnetic": magnetic, "electric_nodes_mm": edges, "next_nodes_mm": following}
    return [(result_fields._coordinates(model, axes, a), data[i]) for i, a in enumerate("xyz")]


def _sphere(np, refinements, closed):
    """! @brief 같은 반지름으로 투영한 사분할 삼각형으로 바깥쪽 구면을 만든다."""
    vertices = [np.array(v, dtype=float) for v in ((1,0,0),(0,1,0),(-1,0,0),(0,-1,0),(0,0,1),(0,0,-1))]
    faces = [(i, (i + 1) % 4, 4) for i in range(4)]
    if closed:
        faces += [((i + 1) % 4, i, 5) for i in range(4)]
    for _ in range(refinements):
        lookup = {}

        def middle(a, b):
            """! @brief 인접 삼각형은 곡률 투영한 공통 변 절점을 공유한다."""
            key = tuple(sorted((a, b)))
            if key not in lookup:
                value = vertices[a] + vertices[b]
                lookup[key] = len(vertices)
                vertices.append(value / np.linalg.norm(value))
            return lookup[key]

        updated = []
        for a, b, c in faces:
            ab, bc, ca = middle(a, b), middle(b, c), middle(c, a)
            updated.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        faces = updated
    return {"kind": "mesh", "vertices_mm": (np.asarray(vertices) * RADIUS + CENTER).tolist(),
            "triangles": [list(row) for row in faces]}


def _smooth(np, electric, magnetic, closed):
    """! @brief 매끈한 구면을 직접 Gauss 적분하여 삼각 면 근사 오차를 확인한다."""
    from scipy.interpolate import RegularGridInterpolator

    root, weights = np.polynomial.legendre.leggauss(64)
    phi, phi_w = math.pi * (root + 1), math.pi * weights
    mu, mu_w = (root, weights) if closed else ((root + 1) / 2, weights / 2)
    mu, phi = np.meshgrid(mu, phi, indexing="ij")
    radius = np.sqrt(1 - mu**2)
    normals = np.stack((radius * np.cos(phi), radius * np.sin(phi), mu), axis=-1)
    points = CENTER + RADIUS * normals
    vector = []
    for group in (electric, magnetic):
        vector.append(np.stack([RegularGridInterpolator(tuple(coords[a] for a in "xyz"), vals)(points)
                                for coords, vals in group], axis=-1))
    density = 0.5 * np.sum(np.cross(vector[0], vector[1].conj()).real * normals, axis=-1)
    return float(RADIUS**2 * 1e-6 * (mu_w @ density @ phi_w))


def measure(folder):
    """! @brief 같은 원문에서 두 방향, 삼각화 수준과 독립 매끈한 면 적분을 비교한다."""
    import numpy as np

    info = json.loads((folder / "recording.json").read_bytes())
    electric, magnetic = (_volume(folder, info, flag) for flag in (False, True))
    output = {"grid_mm": info["grid_mm"], "source_sha256": info["document_sha256"], "frequency_hz": FREQUENCY,
              "center_mm": CENTER, "radius_mm": RADIUS, "direction": "outward", "unit": "W*s^2", "surfaces": {}}
    for label, closed in (("hemisphere", False), ("sphere", True)):
        levels = []
        for level in range(4):
            mesh = _sphere(np, level, closed)
            value = integrate_surface(electric, magnetic, mesh)
            levels.append({"triangles": len(mesh["triangles"]), "mesh_sha256": canonical_hash(mesh),
                           "area_m2": value["surface"]["area_m2"], "flux": value["total_flux_w_s2"]})
        flipped = integrate_surface(electric, magnetic, {**mesh, "triangles": [row[::-1] for row in mesh["triangles"]]})
        output["surfaces"][label] = {"levels": levels, "flipped_finest_flux": flipped["total_flux_w_s2"],
                                    "smooth_surface_flux": _smooth(np, electric, magnetic, closed)}
    print(json.dumps(output, indent=2))


def main():
    """! @brief 실제 여기와 고정 수치 환경의 원문 읽기를 별도 프로세스로 진행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--grid", type=float)
    options = parser.parse_args()
    if options.executable:
        if options.case is None or options.grid is None:
            parser.error("실제 기록에는 --case 및 --grid가 필요합니다.")
        with os.add_dll_directory(str(options.executable.resolve().parent)):
            _record(options.case, options.executable.resolve(), options.folder.resolve(), options.grid)
    else:
        measure(options.folder)


if __name__ == "__main__":
    main()
