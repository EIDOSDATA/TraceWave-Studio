"""! @brief 일반 도파관 단면의 접선 모드를 openEMS의 두 HDF5 급전 원문으로 내보낸다."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.domain.floquet import LIGHT_SPEED
from rfad.domain.network_data import fail, finite
from rfad.domain.waveguide_section import VACUUM_IMPEDANCE_OHM, solve


def _samples(np, points, elements, scalar, family, cut, axes):
    """! @brief P1 요소의 접선 기울기를 단면 표본으로 옮기고 공유 변에서는 면적 가중 평균한다."""
    shape = tuple(len(axis) for axis in axes)
    values = np.zeros((*shape, 2))
    weights = np.zeros(shape)
    for indices in elements:
        corners = points[indices]
        low, high = corners.min(axis=0), corners.max(axis=0)
        x, y = (slice(np.searchsorted(axis, a - 1e-10), np.searchsorted(axis, b + 1e-10, side="right"))
                for axis, a, b in zip(axes, low, high))
        local_points = np.stack(np.meshgrid(axes[0][x], axes[1][y], indexing="ij"), axis=-1)
        jacobian = (corners[1:] - corners[0]).T
        inverse = np.linalg.inv(jacobian)
        barycentric = (local_points - corners[0]) @ inverse.T
        mask = (barycentric.min(axis=-1) >= -1e-9) & (barycentric.sum(axis=-1) <= 1 + 1e-9)
        gradient = (scalar[indices[1:]] - scalar[indices[0]]) @ inverse / cut
        if family == "TE":
            gradient = np.array([gradient[1], -gradient[0]])
        area = abs(np.linalg.det(jacobian)) / 2
        values[x, y] += mask[..., None] * gradient * area
        weights[x, y] += mask * area
    np.divide(values, weights[..., None], out=values, where=weights[..., None] > 0)
    return values


def _write_field(h5py, path, axes, field):
    """! @brief CSXCAD가 읽는 XY 좌표와 Vx/Vy 모드 파일을 만든다."""
    with h5py.File(path, "x") as handle:
        handle.attrs["Version"] = 1.0
        for key, data in zip(("x", "y", "Vx", "Vy"), (*axes, field[..., 0], field[..., 1])):
            handle.create_dataset(key, data=data, dtype="<f8", track_times=False)
    return {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def export_mode(case, side, name, frequency, pitch, destination):
    """! @brief 전파 모드, 축, 기준면과 정규화가 맞는 새 출처 묶음을 원자적으로 게시한다."""
    if side not in ("wide", "narrow"):
        fail("포트는 wide 또는 narrow입니다.", "side")
    frequency = finite(frequency, "frequency_hz")
    if not 1e6 <= frequency <= 1e13:
        fail("지원 주파수는 1 MHz~10 THz입니다.", "frequency_hz")
    pitch = finite(pitch, "pitch_mm")
    if not 0.01 <= pitch <= 10:
        fail("모드 표본 간격은 0.01~10 mm입니다.", "pitch_mm")
    result = solve(case)
    table = result["sections"][side]
    entry = next((row for row in table["modes"] if row["mode"] == name), None)
    if entry is None:
        fail("선택한 단면의 기록된 TE 또는 TM 모드를 지정하십시오.", "mode")
    ratio = entry["cutoff_hz"] / frequency
    if ratio >= 1 - 1e-10:
        fail("전파 모드의 차단점 위 주파수가 필요합니다.", "frequency_hz", "E_CONFLICT")
    np, _, _, _ = network_backend.runtime()
    import h5py

    geometry = np.asarray(case["nodes_mm"], dtype=float)
    elements = np.asarray(case["triangles"], dtype=int)
    if side == "narrow":
        elements = elements[case["aperture_triangles"]]
    scalar = np.zeros(len(geometry))
    scalar[table["node_indices"]] = entry["scalar_nodal_values_per_mm"]
    lower = geometry[table["node_indices"]].min(axis=0)
    upper = geometry[table["node_indices"]].max(axis=0)
    counts = [math.ceil(value / pitch) + 1 for value in upper - lower]
    if min(counts) < 3 or math.prod(counts) > 262144:
        fail("각 축 3점 이상, 총 262144점 이내의 모드 격자를 선택하십시오.", "pitch_mm", "E_RESOURCE")
    axes = tuple(np.linspace(a, b, count) for a, b, count in zip(lower, upper, counts))
    cut = 2 * math.pi * entry["cutoff_hz"] * math.sqrt(case["epsilon_r"]) / LIGHT_SPEED
    field = _samples(np, geometry, elements, scalar, entry["polarization"], cut * 1e-3, axes)
    magnetic = np.stack((-field[..., 1], field[..., 0]), axis=-1)
    q = math.sqrt(case["epsilon_r"] * (1 - ratio**2))
    y = q if entry["polarization"] == "TE" else case["epsilon_r"] / q
    if not np.isfinite(field).all() or not np.any(field):
        fail("단면 표본에서 유한한 모드장을 얻지 못했습니다.", "pitch_mm", "E_CONFLICT")
    destination = Path(destination).resolve()
    if destination.exists():
        fail("새 출력 디렉터리를 지정하십시오.", "output", "E_CONFLICT")
    with TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / "mode"
        staged.mkdir()
        data = {
            "schema": "rfad.openems.waveguide-mode-files/0.1", "input_sha256": result["input_sha256"],
            "section": side, "mode": name, "polarization": entry["polarization"],
            "coordinates": "global_xy_mm", "port_inward_direction": result["port_inward_directions"][side],
            "reference_plane_z_mm": result["reference_planes_z_mm"][side],
            "field_convention": "unit L2 tangential E shape; forward H shape is +Z cross E",
            "frequency_hz": frequency, "epsilon_r": case["epsilon_r"], "cutoff_hz": entry["cutoff_hz"],
            "cutoff_rad_per_m": cut, "propagation_rad_per_m": 2 * math.pi * frequency / LIGHT_SPEED * q,
            "reference_impedance_ohm": VACUUM_IMPEDANCE_OHM / y,
            "modal_voltage_v_per_sqrt_w": math.sqrt(2 * VACUUM_IMPEDANCE_OHM / y),
            "sample_shape": counts, "electric": _write_field(h5py, staged / "electric.h5", axes, field),
            "magnetic": _write_field(h5py, staged / "magnetic.h5", axes, magnetic),
        }
        (staged / "mode.json").write_bytes(canonical_bytes(data) + b"\n")
        staged.rename(destination)
    return data


def main(argv=None):
    """! @brief 입력을 읽고 기존 openEMS 모드 파일을 덮어쓰지 않는다."""
    parser = argparse.ArgumentParser(prog="rfad waveguide-mode-files", description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--side", required=True, choices=("wide", "narrow"))
    parser.add_argument("--mode", required=True)
    parser.add_argument("--frequency-hz", type=float, required=True)
    parser.add_argument("--pitch-mm", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    from rfad.cli.em_case import _read_json

    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    try:
        data = export_mode(_read_json(args.input, 4 * 1024 * 1024), args.side, args.mode,
                           args.frequency_hz, args.pitch_mm, args.output)
        sys.stdout.buffer.write(canonical_bytes(data) + b"\n")
    except (OSError, ImportError, ValueError, ProjectError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        return 1
    return 0
