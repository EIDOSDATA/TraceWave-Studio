"""! @brief 동일한 TE10 급전을 전체 영역과 전기 벽 및 자기 벽 반영역으로 실제 해석한다."""

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import CSXCAD
import numpy as np
import openEMS

from check_openems_environment import (
    END_CRITERION, HEIGHT_M, WIDTH_M, assess_samples, check_termination, require,
)


def solve(directory, mode, target_mm, executable):
    """! @brief 전체 모델과 같은 모드, 격자, 측정면을 사용해 복소 포트파를 계산한다."""
    directory.mkdir()
    structure = CSXCAD.ContinuousStructure()
    fdtd = openEMS.openEMS(NrTS=20000, EndCriteria=END_CRITERION)
    fdtd.SetCSX(structure)
    fdtd.SetGaussExcite(10e9, 2e9)
    boundary = ["PEC", "PEC", "PEC", "PEC", "PML_8", "PML_8"]
    # @brief x 중심은 자기장 격자에, y 중심은 전기장 격자에 오도록 맞춘다.
    nx = 2 * math.ceil(10 / target_mm - 0.5) + 1
    ny = 2 * math.ceil(5 / target_mm)
    x = np.linspace(0, 20, nx + 1)
    y = np.linspace(0, 10, ny + 1)
    if mode == "x_pmc":
        x = x[:nx // 2 + 2]
        boundary[1] = "PMC"
    if mode == "y_pec":
        y = y[:ny // 2 + 1]
    fdtd.SetBoundaryCond(boundary)
    grid = structure.GetGrid()
    grid.SetDeltaUnit(1e-3)
    grid.AddLine("x", x)
    grid.AddLine("y", y)
    stations = [0, 10, 15, 65, 70, 80]
    z = sorted({value for start, stop in zip(stations, stations[1:])
                for value in np.linspace(start, stop, math.ceil((stop - start) / target_mm) + 1)})
    grid.AddLine("z", z)
    # @brief 정규화와 급전 함수에는 전체 단면의 폭과 높이를 사용한다.
    inlet = fdtd.AddRectWaveGuidePort(1, [0, 0, 10], [x[-1], y[-1], 15], "z", WIDTH_M, HEIGHT_M, "TE10", excite=1)
    outlet = fdtd.AddRectWaveGuidePort(2, [0, 0, 70], [x[-1], y[-1], 65], "z", WIDTH_M, HEIGHT_M, "TE10", excite=0)
    fdtd.Write2XML(str(directory / "waveguide.xml"))
    command = [executable, "waveguide.xml", "--engine=multithreaded", "--numThreads=2",
               "--dump-statistics", "--exact-endcriteria"]
    completed = subprocess.run(command, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, timeout=180, check=True)
    log = completed.stdout
    iterations = int((directory / "openEMS_stats.txt").read_text().splitlines()[2].split()[0])
    check_termination(log, iterations)
    frequencies = np.linspace(9.5e9, 10.5e9, 31)
    for port in (inlet, outlet):
        port.CalcPort(str(directory), frequencies)
    require(np.all(np.abs(inlet.uf_inc) > np.max(np.abs(inlet.uf_inc)) * 1e-4), "입사파 스펙트럼 부족")
    reflection = inlet.uf_ref / inlet.uf_inc
    transmission = outlet.uf_ref / inlet.uf_inc
    impedance = inlet.uf_tot / inlet.if_tot
    samples = [{"frequency_hz": float(frequency), "s11": [float(s11.real), float(s11.imag)],
                "s21": [float(s21.real), float(s21.imag)], "impedance_ohm": [float(value.real), float(value.imag)]}
               for frequency, s11, s21, value in zip(frequencies, reflection, transmission, impedance)]
    assessment = assess_samples(samples)
    summary = {"intervals": [len(x) - 1, len(y) - 1, len(z) - 1],
               "iterations": iterations, "analytic": assessment}
    return summary, reflection, transmission


def main():
    """! @brief 두 격자의 해석식 오차와 전체 영역 대비 최대 복소 차이를 검사한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openems", default=shutil.which("openEMS"))
    args = parser.parse_args()
    require(args.openems is not None, "--openems로 실행 파일 경로를 지정하세요.")
    executable = str(Path(args.openems).resolve(strict=True))
    require(openEMS.__version__ == "0.37.0", "검증 대상 openEMS 버전은 0.37.0입니다.")
    passed = True
    report = {}
    with TemporaryDirectory() as temp:
        for step in (1.0, 0.75):
            directory = Path(temp) / str(step)
            directory.mkdir()
            full, reference_s11, reference_s21 = solve(directory / "full", "full", step, executable)
            report[str(step)] = {"full": full}
            passed = passed and full["analytic"]["passed"]
            for mode in ("x_pmc", "y_pec"):
                summary, reflection, transmission = solve(directory / mode, mode, step, executable)
                delta_s11 = float(np.max(np.abs(reflection - reference_s11)))
                delta_s21 = float(np.max(np.abs(transmission - reference_s21)))
                summary.update(max_complex_delta_s11=delta_s11, max_complex_delta_s21=delta_s21)
                report[str(step)][mode] = summary
                passed = passed and summary["analytic"]["passed"] and max(delta_s11, delta_s21) <= 0.03
    print(json.dumps({"passed": passed, "grids_mm": report}, indent=2, allow_nan=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
