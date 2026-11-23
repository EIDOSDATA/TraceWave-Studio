"""! @brief 저장 PCB를 직사각 도파관의 두 분포 모드 포트 사이에서 해석한다."""

import argparse
from contextlib import nullcontext
import json
import math
from pathlib import Path
import os
import shutil
import subprocess
import sys

from rfad.adapters.solvers.openems.native import file_identity, write_json
from rfad.adapters.solvers.openems.pcb import statistics_and_termination
from rfad.adapters.solvers.openems.pcb_multiport import scattering
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_periodic import project_case
from rfad.application.pcb_projection import EPSILON0
from rfad.cli.em_case import _read_json
from rfad.cli.pcb_multiport import read_input
from rfad.domain.errors import ProjectError
from rfad.domain.floquet import LIGHT_SPEED
from rfad.domain.network_data import fail, finite
from rfad.domain.periodic_cell import validate as validate_cell
from rfad.domain.planar import decompose_region
from rfad.domain.waveguide_section import VACUUM_IMPEDANCE_OHM


def _validate(document, settings):
    """! @brief 물리 셀의 실제 재료와 계산 상한을 하나의 입력으로 고정한다."""
    keys = {"frequencies_hz", "grid_mm", "lead_mm", "curve_tolerance_mm", "max_timesteps", "end_criterion", "num_threads"}
    if type(settings) is not dict or set(settings) != keys:
        fail("주파수, 격자, 도파관 길이와 실행 상한을 지정하십시오.", "settings")
    grid = finite(settings["grid_mm"], "grid_mm")
    lead = finite(settings["lead_mm"], "lead_mm")
    if not 0.1 <= grid <= 2 or not 32 * grid <= lead <= 100:
        fail("격자는 0.1~2 mm이며 두 도파관 길이는 32 격자 이상입니다.", "settings")
    if (type(settings["max_timesteps"]) is not int or not 1000 <= settings["max_timesteps"] <= 200000
            or not 1e-9 <= finite(settings["end_criterion"], "end_criterion") <= 1e-3
            or type(settings["num_threads"]) is not int or not 1 <= settings["num_threads"] <= 8):
        fail("스텝 1000~200000, 종료 기준 1e-9~1e-3, 스레드 1~8을 사용하십시오.", "settings")
    frequencies = settings["frequencies_hz"]
    if (type(frequencies) is not list or not 3 <= len(frequencies) <= 31
            or any(not 1e6 <= finite(f, "frequencies_hz") <= 50e9 for f in frequencies)
            or any(b <= a for a, b in zip(frequencies, frequencies[1:]))):
        fail("양의 증가 주파수를 3~31개 지정하십시오.", "frequencies_hz")
    if frequencies[-1] > 2 * frequencies[0]:
        fail("재료 손실의 상수 근사에서는 주파수 비율을 2 이하로 지정하십시오.", "frequencies_hz")
    geometry, provenance = project_case(document, {
        "epsilon_left": 1, "epsilon_right": 1, "frequencies_hz": frequencies,
        "theta_deg": 0, "phi_deg": 0, "polarization": "TE", "grid": [1, 1], "comparison_grid": [3, 3],
        "curve_tolerance_mm": settings["curve_tolerance_mm"],
    })
    validate_cell(geometry)
    provenance["settings_sha256"] = canonical_hash(settings)
    return geometry, provenance


def _field_files(np, h5py, directory, period, frequencies):
    """! @brief 봉인된 E/H 표본이 PCB 단면, 공기 매질과 계산 대역에 맞는지 확인한다."""
    manifest = _read_json(directory / "mode.json")
    if (type(manifest) is not dict or manifest.get("schema") != "rfad.openems.waveguide-mode-files/0.1"
            or manifest.get("epsilon_r") != 1 or manifest.get("coordinates") != "global_xy_mm"
            or manifest.get("section_geometry") != "rectangle"
            or manifest.get("polarization") not in ("TE", "TM")):
        fail("공기 직사각 도파관의 TE/TM 모드 파일 묶음이 필요합니다.", "mode")
    cutoff = finite(manifest.get("cutoff_rad_per_m"), "mode.cutoff_rad_per_m")
    k0 = np.asarray(frequencies) * (2 * math.pi / LIGHT_SPEED)
    if not 0 < cutoff < k0[0] * (1 - 1e-10):
        fail("모드가 전체 계산 대역에서 전파해야 합니다.", "frequencies_hz", "E_CONFLICT")
    paths = []
    reference_axes = None
    for kind in ("electric", "magnetic"):
        path = directory / (kind + ".h5")
        reference = manifest.get(kind)
        if (type(reference) is not dict or reference.get("name") != path.name or not path.is_file()
                or path.stat().st_size > 8 * 1024**2 or file_identity(path)["sha256"] != reference.get("sha256")):
            fail("E/H 모드의 경로, 크기 또는 원문 해시를 확인하십시오.", "mode." + kind, "E_HASH")
        with h5py.File(path, "r") as handle:
            if set(handle) != {"x", "y", "Vx", "Vy"} or handle.attrs.get("Version") != 1:
                fail("지원하는 CSXCAD 모드 HDF5가 필요합니다.", "mode." + kind)
            datasets = []
            for name in ("x", "y", "Vx", "Vy"):
                if not isinstance(handle.get(name, getlink=True), h5py.HardLink):
                    fail("모드의 외부 및 심볼릭 데이터를 사용할 수 없습니다.", "mode." + kind)
                item = handle[name]
                if (not isinstance(item, h5py.Dataset) or item.is_virtual or item.external
                        or item.size > 262144 or item.dtype.kind != "f" or item.compression is not None):
                    fail("유한 실수 모드 데이터가 필요합니다.", "mode." + kind)
                datasets.append(item[...])
        x, y, vx, vy = datasets
        if (any(axis.ndim != 1 or len(axis) < 3 or not np.isclose(axis[0], 0)
                or not np.isclose(axis[-1], span) or np.any(np.diff(axis) <= 0)
                for axis, span in zip((x, y), period))
                or any(data.shape != (len(x), len(y)) for data in (vx, vy))
                or not all(np.isfinite(data).all() for data in datasets)):
            fail("모드 샘플과 보드의 직사각 단면이 일치해야 합니다.", "mode." + kind, "E_GEOMETRY")
        if reference_axes is not None and not all(np.array_equal(a, b) for a, b in zip(reference_axes, (x, y))):
            fail("전계와 자계의 원문 표본 축이 다릅니다.", "mode", "E_HASH")
        reference_axes = (x, y)
        paths.append(path)
    q = np.sqrt(1 - (cutoff / k0)**2)
    impedance = VACUUM_IMPEDANCE_OHM / q if manifest["polarization"] == "TE" else VACUUM_IMPEDANCE_OHM * q
    return manifest, paths, cutoff, impedance


def _geometry(csx, geometry, frequency, depth):
    """! @brief 저장 적층의 배경 유전체와 전도성 동박 구역을 원래 좌표에 놓는다."""
    width, height = geometry["period_mm"]
    z = 0
    bulk = {}
    materials = geometry["materials"]
    for index, layer in enumerate(geometry["layers"]):
        stop = z + layer["thickness_mm"]
        background = layer["background"]
        if background != "air":
            item = materials[background]
            if background not in bulk:
                kappa = item["conductivity_s_per_m"] + 2 * math.pi * frequency * EPSILON0 * item["epsilon_r"] * item["tan_delta"]
                bulk[background] = csx.AddMaterial("pcb_dielectric_" + str(index), epsilon=item["epsilon_r"], kappa=kappa)
            bulk[background].AddBox([0, 0, z], [width, height, stop], priority=1)
        sheets = {}
        for region in layer["regions"]:
            name = region["material"]
            material = materials[name]
            if material["conductivity_s_per_m"] <= 0:
                fail("패턴 층에는 유한 전도성 동박을 지정하십시오.", "geometry", "E_MATERIAL_RANGE")
            if name not in sheets:
                sheets[name] = csx.AddConductingSheet(
                    "foil_" + str(index) + "_" + str(len(sheets)), conductivity=material["conductivity_s_per_m"],
                    thickness=layer["thickness_mm"] * 0.001)
            elevation = z if index > 0 or stop == depth else stop
            for polygon in decompose_region(region["outer"], region["holes"]):
                sheets[name].AddPolygon(list(map(list, zip(*polygon))), norm_dir=2, elevation=elevation, priority=5)
        z = stop


def run(document, settings, mode_directory, executable, output):
    """! @brief 각 포트를 한 번씩 여기해 두 기준면의 정규 복소 S를 기록한다."""
    import CSXCAD
    import h5py
    import numpy as np
    import openEMS
    from openEMS.ports import WaveguidePort

    if CSXCAD.__version__ != "0.7.0" or openEMS.__version__ != "0.37.0":
        fail("openEMS 0.37.0과 CSXCAD 0.7.0이 필요합니다.", "engine", "E_UNSUPPORTED")
    geometry, provenance = _validate(document, settings)
    frequency = np.asarray(settings["frequencies_hz"])
    mode, field_paths, cutoff, impedance = _field_files(np, h5py, mode_directory, geometry["period_mm"], frequency)
    step, lead = settings["grid_mm"], settings["lead_mm"]
    width, height = geometry["period_mm"]
    depth = math.fsum(layer["thickness_mm"] for layer in geometry["layers"])
    planes = [-0.4 * lead, depth + 0.4 * lead]
    sources = [-0.65 * lead, depth + 0.65 * lead]
    z_knots = sorted(set([-lead, *planes, *sources, depth + lead, 0, depth,
                         *np.cumsum([layer["thickness_mm"] for layer in geometry["layers"]]).tolist()]))
    z = np.concatenate([np.linspace(a, b, math.ceil((b - a) / step), endpoint=False)
                        for a, b in zip(z_knots, z_knots[1:]) if b - a > 1e-12] + [[z_knots[-1]]])
    axes = [np.linspace(0, length, math.ceil(length / step) + 1) for length in (width, height)] + [z]
    if math.prod(map(len, axes)) > 1500000:
        fail("도파관과 보드의 공통 격자 상한을 넘었습니다.", "grid_mm", "E_RESOURCE")
    executable_identity = file_identity(executable)
    output.mkdir(exist_ok=False)
    copied = []
    for field, path in zip(("electric", "magnetic"), field_paths):
        target = output / path.name
        shutil.copyfile(path, target)
        if file_identity(target)["sha256"] != mode[field]["sha256"]:
            fail("실행 중 모드 원문이 변경되었습니다.", "mode." + field, "E_HASH")
        copied.append(target)
    write_json(output / "input.json", {"document": document, "settings": settings, "mode": mode})
    center, bandwidth = (frequency[0] + frequency[-1]) / 2, (frequency[-1] - frequency[0]) / 2
    incoming, outgoing, runs = [], [], []
    for drive in range(2):
        folder = output / f"excitation-{drive + 1}"
        folder.mkdir()
        csx = CSXCAD.ContinuousStructure()
        fdtd = openEMS.openEMS(NrTS=settings["max_timesteps"], EndCriteria=settings["end_criterion"])
        fdtd.SetCellConstantMaterial(False)
        fdtd.SetCSX(csx)
        fdtd.SetGaussExcite(center, bandwidth)
        fdtd.SetBoundaryCond(["PEC", "PEC", "PEC", "PEC", "PML_8", "PML_8"])
        grid = csx.GetGrid()
        grid.SetDeltaUnit(0.001)
        for name, coords in zip("xyz", axes):
            grid.AddLine(name, coords)
        _geometry(csx, geometry, center, depth)
        ports = [WaveguidePort(csx, i + 1, [0, 0, source], [width, height, reference], "z", None, None,
                               cutoff, excite=int(i == drive), excite_type=0,
                               E_WG_file=os.path.relpath(copied[0], folder), H_WG_file=os.path.relpath(copied[1], folder))
                 for i, (source, reference) in enumerate(zip(sources, planes))]
        fdtd.Write2XML(str(folder / "pcb.xml"))
        with (folder / "native.log").open("xb") as log:
            subprocess.run([str(executable), "pcb.xml", "--engine=multithreaded", f"--numThreads={settings['num_threads']}",
                            "--dump-statistics", "--exact-endcriteria"], cwd=folder, stdin=subprocess.DEVNULL,
                           stdout=log, stderr=subprocess.STDOUT, timeout=300, check=True)
        stats, end = statistics_and_termination(folder, {"case": {"settings": settings}})
        if end["status"] != "end_criterion_reached":
            fail("분포 모드 여기에서 에너지 종료 기준을 충족하지 못했습니다.", "settings", "E_CONFLICT")
        for port in ports:
            port.CalcPort(str(folder), frequency, ref_impedance=impedance)
        incoming.append(np.stack([port.uf_inc / np.sqrt(impedance) for port in ports], axis=-1))
        outgoing.append(np.stack([port.uf_ref / np.sqrt(impedance) for port in ports], axis=-1))
        runs.append({"excited_port": drive + 1, "statistics": stats, "termination": end,
                     "files": {path.name: file_identity(path) for path in folder.iterdir() if path.is_file()}})
    matrix, condition = scattering(np.stack(incoming, axis=-1), np.stack(outgoing, axis=-1))
    result = {"schema": "rfad.openems.pcb-waveguide-mode/0.1", "project_source": provenance,
              "settings_sha256": canonical_hash(settings), "mode": mode, "engine": executable_identity,
              "reference_planes_z_mm": planes, "port_inward_directions": [[0, 0, 1], [0, 0, -1]],
              "wave_definition": "power", "phasor_convention": "exp(+j*omega*t)",
              "frequency_hz": list(settings["frequencies_hz"]), "reference_impedance_ohm": impedance.tolist(),
              "s_ri": np.stack((matrix.real, matrix.imag), axis=-1).tolist(),
              "incident_condition_max": condition, "runs": runs}
    write_json(output / "result.json", result)
    return output / "result.json"


def main(argv=None):
    """! @brief 사용자 개정의 읽기 전용 모드 여기와 명시한 native 환경을 연결한다."""
    parser = argparse.ArgumentParser(prog="rfad pcb-waveguide", description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--mode-files", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    try:
        exe = args.executable.resolve(strict=True)
        value = read_input(args.project)
        scope = os.add_dll_directory(str(exe.parent)) if os.name == "nt" else nullcontext()
        with scope:
            result = run(value.get("document", value), _read_json(args.settings), args.mode_files.resolve(),
                         exe, args.output.resolve())
        print(result)
    except (OSError, ImportError, ValueError, ProjectError, subprocess.SubprocessError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        return 1
    return 0
