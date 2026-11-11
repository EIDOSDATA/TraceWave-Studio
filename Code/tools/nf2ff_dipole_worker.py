"""! @brief 자유공간 PEC 반파장 다이폴의 NF2FF 참조 계산을 격리 guest에서 수행한다."""

import json
from pathlib import Path
import sys
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def run():
    """! @brief 고정된 참조 형상만 실행하고 사용자 PCB의 물리 합격과 구분한다."""
    if not sys.stdin.buffer.readline():
        return 19
    import numpy as np
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
    from rfad.application.radiation import power_metrics

    output = Path('output').resolve()
    native = output / 'native'
    reuse = Path('input/native').resolve()
    if reuse.is_dir():
        shutil.copytree(reuse, native)
        native.chmod(0o700)
    else:
        native.mkdir()
    csx = ContinuousStructure()
    solver = openEMS(NrTS=30000, EndCriteria=1e-5)
    solver.SetCSX(csx)
    solver.SetGaussExcite(2.4e9, 0.4e9)
    solver.SetBoundaryCond(['PML_8'] * 6)
    grid = csx.GetGrid()
    grid.SetDeltaUnit(1e-3)
    for axis in 'xyz':
        grid.AddLine(axis, sorted(set(np.arange(-90, 91, 2).tolist() + [-1, -0.5, 0, 0.5, 1, -30, 30, -60, 60])))
    metal = csx.AddMetal('reference_PEC')
    metal.AddCylinder(start=[0, 0, -30], stop=[0, 0, -0.5], radius=1, priority=10)
    metal.AddCylinder(start=[0, 0, 0.5], stop=[0, 0, 30], radius=1, priority=10)
    port = solver.AddLumpedPort(1, 50, [-1, -1, -0.5], [1, 1, 0.5], 'z', 1, priority=20)
    box = solver.CreateNF2FFBox(start=[-60] * 3, stop=[60] * 3, frequency=[2.4e9])
    if not reuse.is_dir():
        solver.Run(str(native), cleanup=False, verbose=0, numThreads=2)
    port.CalcPort(str(native), [2.4e9])
    theta, phi = np.arange(0, 181, 5), np.arange(0, 360, 5)
    field = box.CalcNF2FF(str(native), [2.4e9], theta, phi, center=[0, 0, 0], read_cached=False)
    incident = float(port.P_inc[0])
    accepted = float(port.P_acc[0])
    metrics = power_metrics(float(field.Prad[0]), accepted, incident, float(field.Dmax[0]))
    pattern = np.asarray(field.E_norm[0]) ** 2
    pattern /= pattern.max()
    radians = np.deg2rad(theta)
    ideal = np.zeros_like(radians)
    valid = np.sin(radians) > 1e-8
    ideal[valid] = (np.cos(np.pi / 2 * np.cos(radians[valid])) / np.sin(radians[valid])) ** 2
    maximum_error = float(np.max(np.abs(pattern[:, 0] - ideal)))
    relative_directivity_error = abs(metrics['directivity_linear'] / 1.6409 - 1)
    accepted_test = maximum_error <= 0.15 and relative_directivity_error <= 0.1 and abs(metrics['radiation_efficiency'] - 1) <= 0.15
    result = {'schema': 'rfad.nf2ff-reference/0.1', 'status': 'passed' if accepted_test else 'requires_review',
              'frequency_hz': 2.4e9, 'model': 'PEC 60 mm dipole, radius 1 mm, 1 mm ideal lumped gap in free space',
              'fdtd_executed_this_run': not reuse.is_dir(), 'raw_input_reused': reuse.is_dir(),
              'theta_deg': theta.tolist(), 'phi_deg': phi.tolist(), 'normalized_power_pattern': pattern.tolist(),
              'e_theta_v_per_m': {'real': np.asarray(field.E_theta[0]).real.tolist(), 'imag': np.asarray(field.E_theta[0]).imag.tolist()},
              'e_phi_v_per_m': {'real': np.asarray(field.E_phi[0]).real.tolist(), 'imag': np.asarray(field.E_phi[0]).imag.tolist()},
              'metrics': metrics, 'reference_directivity': 1.6409, 'maximum_pattern_error': maximum_error,
              'relative_directivity_error': relative_directivity_error,
              'acceptance': {'maximum_pattern_error': 0.15, 'relative_directivity_error': 0.1, 'efficiency_error': 0.15},
              'reference_scope': 'finite-radius discretized dipole versus ideal thin half-wave pattern; preliminary reference only',
              'physics_validated': False, 'manufacturing_validated': False}
    (output / 'radiation.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
