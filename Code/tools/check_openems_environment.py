"""! @file
@brief 격리 Linux openEMS에서 작은 TE10 도파관을 계산하고 해석식과 대조한다.
@details 제품 solver adapter나 IFA/NF2FF 정확도 인증을 제공하지 않는다.
"""

from __future__ import annotations

import argparse
import cmath
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time
from uuid import uuid4


CASE_VERSION = "rfad.reference.rect-waveguide/0.1"
C0 = 299792458.0
Z0 = 376.730313668
WIDTH_M = 0.020
HEIGHT_M = 0.010
LENGTH_M = 0.080
PROBE_SEPARATION_M = 0.050
END_CRITERION = 1e-7
LIMITS = {
    "max_reflection_amplitude": 0.15,
    "max_transmission_amplitude_error": 0.08,
    "max_impedance_relative_error": 0.08,
    "max_group_delay_relative_error": 0.10,
    "max_grid_transmission_amplitude_delta": 0.03,
    "max_grid_impedance_relative_delta": 0.04,
}


def require(condition: bool, message: str) -> None:
    """! @brief 검사 실패를 성공 결과와 구분할 수 있는 오류로 만든다."""
    if not condition:
        raise RuntimeError(message)


def write_json(path: Path, data: dict) -> None:
    """! @brief 비유한 수치를 거부하고 보고서를 한 번에 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending-" + uuid4().hex)
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def file_identity(path: Path) -> dict:
    """! @brief 실제 사용한 파일을 크기와 SHA256으로 식별한다."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def analytic_te10(frequency_hz: float) -> tuple[float, float]:
    """! @brief 진공 PEC 도파관의 독립 TE10 임피던스와 군지연을 계산한다."""
    cutoff = C0 / (2 * WIDTH_M)
    require(math.isfinite(frequency_hz) and frequency_hz > cutoff, "Frequency must be finite and above TE10 cutoff.")
    factor = math.sqrt(1 - (cutoff / frequency_hz) ** 2)
    return Z0 / factor, PROBE_SEPARATION_M / (C0 * factor)


def assess_samples(samples: list[dict]) -> dict:
    """! @brief 실제 복소 포트 결과를 유한성, 진폭, 임피던스와 군지연으로 판정한다."""
    require(len(samples) >= 3, "At least three frequency samples are required.")
    frequencies, transmissions, impedances, reflections = [], [], [], []
    for sample in samples:
        values = [sample["frequency_hz"], *sample["s11"], *sample["s21"], *sample["impedance_ohm"]]
        require(all(type(value) in (float, int) and math.isfinite(value) for value in values), "Port data contains non-finite values.")
        frequency = sample["frequency_hz"]
        require(not frequencies or frequency > frequencies[-1], "Frequency samples must be strictly increasing.")
        require(frequency < min(C0 / WIDTH_M, C0 / (2 * HEIGHT_M)), "Frequency must be below the next propagating mode.")
        analytic_te10(frequency)
        frequencies.append(frequency)
        reflections.append(complex(*sample["s11"]))
        transmissions.append(complex(*sample["s21"]))
        impedances.append(complex(*sample["impedance_ohm"]))
    delays = []
    for index in range(len(samples) - 1):
        require(abs(transmissions[index]) > 1e-12 and abs(transmissions[index + 1]) > 1e-12, "Transmission is too small for a phase slope.")
        difference = frequencies[index + 1] - frequencies[index]
        phase_change = cmath.phase(transmissions[index + 1] / transmissions[index])
        delay = -phase_change / (2 * math.pi * difference)
        _, reference = analytic_te10(0.5 * (frequencies[index + 1] + frequencies[index]))
        require(reference * difference < 0.25, "Frequency spacing cannot resolve the expected phase slope.")
        delays.append(abs(delay / reference - 1))
    metrics = {
        "max_reflection_amplitude": max(map(abs, reflections)),
        "max_transmission_amplitude_error": max(abs(abs(value) - 1) for value in transmissions),
        "max_impedance_relative_error": max(abs(value / analytic_te10(frequency)[0] - 1) for value, frequency in zip(impedances, frequencies)),
        "max_group_delay_relative_error": max(delays),
    }
    return {"passed": all(value <= LIMITS[name] for name, value in metrics.items()), "metrics": metrics}


def compare_grids(coarse: list[dict], fine: list[dict]) -> dict:
    """! @brief 같은 주파수에서 두 격자의 결과가 크게 달라지지 않는지 검사한다."""
    require(len(coarse) == len(fine) and len(coarse) >= 3, "Grid sample counts differ.")
    for left, right in zip(coarse, fine):
        require(left["frequency_hz"] == right["frequency_hz"], "Grid frequency values differ.")
    metrics = {
        "max_grid_transmission_amplitude_delta": max(abs(abs(complex(*a["s21"])) - abs(complex(*b["s21"]))) for a, b in zip(coarse, fine)),
        "max_grid_impedance_relative_delta": max(abs(complex(*a["impedance_ohm"]) - complex(*b["impedance_ohm"])) / analytic_te10(a["frequency_hz"])[0] for a, b in zip(coarse, fine)),
    }
    require(all(math.isfinite(value) for value in metrics.values()), "Grid comparison is non-finite.")
    return {"passed": all(value <= LIMITS[name] for name, value in metrics.items()), "metrics": metrics}


def check_termination(log_text: str, iterations: int) -> dict:
    """! @brief 조기 중단과 step 상한을 거부하고 native 종료 에너지 근거를 확인한다.

    @details 고정 openEMS 0.37.0의 완료 메시지와 실제 통계가 모두 일치해야 한다.
    로그의 반올림된 감쇠값을 임계값보다 더 정밀한 에너지 측정으로 표현하지 않는다.
    """
    lowered = log_text.lower()
    require("checkabortcond" not in lowered and "aborting simulation" not in lowered, "Native solver reported an aborted simulation.")
    require("max. number of timesteps was reached" not in lowered, "Native solver reported an unmet end criterion.")
    require("Exact-endcriteria: evaluating the end criteria every " in log_text, "Native exact end-criterion evaluation was not confirmed.")
    number = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
    pattern = rf"RunFDTD: end-criteria of -({number})dB reached after ([0-9]+) timesteps \(-({number}|inf)dB\)"
    matches = re.findall(pattern, log_text)
    require(len(matches) == 1, "Exactly one successful native end-criterion message is required.")
    target_text, iteration_text, decay_text = matches[0]
    target_db = float(target_text)
    decay_db = float(decay_text)
    expected_db = -10 * math.log10(END_CRITERION)
    require(math.isfinite(target_db) and abs(target_db - expected_db) < 1e-8, "Native termination target differs from the requested criterion.")
    require(int(iteration_text) == iterations and 0 < iterations < 20000, "Native log and run-statistics iteration counts differ.")
    require(decay_db >= expected_db, "Native termination energy did not meet the requested criterion.")
    return {"status": "end_criterion_reached", "iterations": iterations, "target_energy_ratio": END_CRITERION, "reported_decay_db": decay_db if math.isfinite(decay_db) else None, "reported_zero_energy": math.isinf(decay_db), "evidence": matches[0], "exact_endcriterion_schedule": True}


def runtime_identity() -> dict:
    """! @brief 실제 로딩한 native 모듈과 Qt 부재를 기록한다."""
    packages = {item.metadata["Name"].lower().replace("_", "-"): item.version for item in importlib.metadata.distributions()}
    qt_packages = sorted(name for name in packages if re.match(r"^(pyqt|pyside|shiboken|qt[0-9-])", name))
    mapped = set()
    for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
        fields = line.split(None, 5)
        if len(fields) == 6 and fields[-1].startswith("/") and Path(fields[-1]).is_file():
            mapped.add(Path(fields[-1]).resolve())
    qt_libraries = sorted(str(path) for path in mapped if re.search(r"libQt[0-9]", path.name))
    qt_modules = sorted(name for name in sys.modules if name.startswith(("PyQt", "PySide", "qtpy")))
    require(not qt_packages and not qt_libraries and not qt_modules, "Qt was found in the solver runtime.")
    native = [path for path in sorted(mapped) if any(token in path.name.lower() for token in ("openems", "csxcad", "fparser", "nf2ff"))]
    require(any("openems" in path.name.lower() for path in native), "Actual openEMS native library was not mapped.")
    return {"python": platform.python_version(), "executable": file_identity(Path(sys.executable).resolve()), "platform": platform.platform(), "packages": packages, "native_libraries": [file_identity(path) for path in native], "qt_packages": qt_packages, "qt_libraries": qt_libraries, "qt_modules": qt_modules}


def run_case(directory: Path, target_mm: float, report_path: Path) -> int:
    """! @brief 자식 프로세스에서 작은 진공 PEC 도파관의 실제 FDTD를 실행한다."""
    import numpy as np
    import CSXCAD
    import openEMS as solver_module

    require(sys.platform.startswith("linux"), "This runtime profile requires Linux.")
    require(sys.prefix != sys.base_prefix, "Run this check inside the dedicated solver virtual environment.")
    require(str(solver_module.__version__) == "0.37.0", "Expected openEMS 0.37.0.")
    require(str(CSXCAD.__version__) == "0.7.0", "Expected CSXCAD 0.7.0.")
    require(target_mm in (1.0, 0.75), "Only the two fixed reference grids are supported.")
    directory.mkdir(parents=True, exist_ok=False)
    structure = CSXCAD.ContinuousStructure()
    solver = solver_module.openEMS(NrTS=20000, EndCriteria=END_CRITERION)
    solver.SetCSX(structure)
    solver.SetGaussExcite(10e9, 2e9)
    solver.SetBoundaryCond(["PEC", "PEC", "PEC", "PEC", "PML_8", "PML_8"])
    mesh = structure.GetGrid()
    mesh.SetDeltaUnit(1e-3)
    mesh.AddLine("x", np.linspace(0, 20, math.ceil(20 / target_mm) + 1))
    mesh.AddLine("y", np.linspace(0, 10, math.ceil(10 / target_mm) + 1))
    critical = [0, 10, 15, 65, 70, 80]
    z = sorted({float(value) for start, stop in zip(critical, critical[1:]) for value in np.linspace(start, stop, math.ceil((stop - start) / target_mm) + 1)})
    mesh.AddLine("z", z)
    inlet = solver.AddRectWaveGuidePort(1, [0, 0, 10], [20, 10, 15], "z", WIDTH_M, HEIGHT_M, "TE10", excite=1)
    outlet = solver.AddRectWaveGuidePort(2, [0, 0, 70], [20, 10, 65], "z", WIDTH_M, HEIGHT_M, "TE10", excite=0)
    xml = directory / "waveguide.xml"
    solver.Write2XML(str(xml))
    started = time.monotonic()
    result = solver.Run(str(directory), cleanup=False, numThreads=2, verbose=0, dump_statistics=True, exact_endcriteria=True)
    require(result in (None, 0), f"Solver setup failed: {result}")
    statistics = [float(line.split()[0]) for line in (directory / "openEMS_stats.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(statistics) >= 6 and all(math.isfinite(value) for value in statistics), "Native run statistics are missing or invalid.")
    require(0 < statistics[2] < 20000, "Solver did not finish before the timestep cap.")
    frequency = np.linspace(9.5e9, 10.5e9, 31)
    for port in (inlet, outlet):
        port.CalcPort(str(directory), frequency)
    for data in (inlet.uf_inc, inlet.uf_ref, outlet.uf_ref, inlet.uf_tot, inlet.if_tot):
        require(bool(np.all(np.isfinite(data))), "Native port data contains a non-finite value.")
    require(float(np.max(np.abs(inlet.uf_inc))) > 1e-18, "No incident signal was measured.")
    require(bool(np.all(np.abs(inlet.uf_inc) > np.max(np.abs(inlet.uf_inc)) * 1e-4)), "Incident spectrum is too small in the reference band.")
    require(bool(np.all(np.abs(inlet.if_tot) > 1e-24)), "Current is too small for impedance extraction.")
    s11, s21 = inlet.uf_ref / inlet.uf_inc, outlet.uf_ref / inlet.uf_inc
    impedance = inlet.uf_tot / inlet.if_tot
    samples = [{"frequency_hz": float(f), "s11": [float(r.real), float(r.imag)], "s21": [float(t.real), float(t.imag)], "impedance_ohm": [float(z.real), float(z.imag)]} for f, r, t, z in zip(frequency, s11, s21, impedance)]
    assessment = assess_samples(samples)
    report = {"case_version": CASE_VERSION, "status": "passed" if assessment["passed"] else "failed", "target_cell_mm": target_mm, "mesh_cells": [len(mesh.GetLines(axis)) - 1 for axis in ("x", "y", "z")], "native_statistics": {"cells": int(statistics[0]), "timestep_seconds": statistics[1], "iterations": int(statistics[2]), "simulated_seconds": statistics[3]}, "elapsed_seconds": time.monotonic() - started, "openems_version": str(solver_module.__version__), "csxcad_version": str(CSXCAD.__version__), "samples": samples, **assessment, "runtime": runtime_identity(), "artifacts": [file_identity(path) for path in sorted(directory.iterdir()) if path.is_file()]}
    write_json(report_path, report)
    return 0 if assessment["passed"] else 2


def run_child(command: list[str], log_path: Path, timeout_seconds: float) -> int:
    """! @brief 시간 제한으로 자식 전체를 회수하고 native 로그를 파일로 보존한다."""
    with log_path.open("wb") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return child.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise RuntimeError(f"Solver child exceeded {timeout_seconds:g} seconds; process group terminated.")


def main(argv: list[str] | None = None) -> int:
    """! @brief 두 격자를 격리 실행하고 한 개의 종합 JSON 결과를 기록한다."""
    parser = argparse.ArgumentParser(description="Linux openEMS 0.37.0 / CSXCAD 0.7.0 TE10 reference environment check")
    parser.add_argument("--output", type=Path, required=True, help="Final JSON report; run artifacts remain beside it.")
    parser.add_argument("--timeout-seconds", type=float, default=300, help="Hard timeout for each grid, including import (default: 300).")
    parser.add_argument("--child-grid-mm", type=float, choices=(1.0, 0.75), help=argparse.SUPPRESS)
    parser.add_argument("--child-directory", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if args.child_grid_mm is not None:
        try:
            require(args.child_directory is not None, "Child run directory is required.")
            return run_case(args.child_directory.resolve(), args.child_grid_mm, output)
        except Exception as error:
            write_json(output, {"status": "failed", "error": str(error), "error_type": type(error).__name__})
            raise
    report = {"schema": "rfad.runtime.openems-reference/0.1", "case_version": CASE_VERSION, "checker": file_identity(Path(__file__).resolve()), "checked_at_utc": datetime.now(timezone.utc).isoformat(), "status": "failed", "limits": LIMITS, "case": {"medium": "vacuum", "side_walls": "PEC", "end_boundaries": "PML_8", "mode": "TE10", "width_m": WIDTH_M, "height_m": HEIGHT_M, "length_m": LENGTH_M, "probe_separation_m": PROBE_SEPARATION_M, "cutoff_hz": C0 / (2 * WIDTH_M), "frequency_hz": [9.5e9, 10.5e9], "max_timesteps": 20000, "requested_end_criterion": END_CRITERION, "exact_endcriterion_schedule": True}, "product_adapter_tested": False, "ifa_tested": False, "nf2ff_tested": False, "formal_convergence_tested": False, "grids": []}
    try:
        require(sys.platform.startswith("linux"), "Run this checker in the dedicated Linux solver environment.")
        require(math.isfinite(args.timeout_seconds) and 1 <= args.timeout_seconds <= 3600, "Timeout must be within 1..3600 seconds.")
        run_root = output.parent / ("openems-run-" + uuid4().hex)
        run_root.mkdir(parents=True, exist_ok=False)
        report["run_directory"] = str(run_root)
        for index, grid in enumerate((1.0, 0.75)):
            child_report = run_root / f"grid-{index}.json"
            log_path = run_root / f"grid-{index}.log"
            command = [sys.executable, "-I", "-X", "utf8", str(Path(__file__).resolve()), "--output", str(child_report), "--child-grid-mm", str(grid), "--child-directory", str(run_root / f"grid-{index}")]
            exit_code = run_child(command, log_path, args.timeout_seconds)
            child_result = json.loads(child_report.read_text(encoding="utf-8")) if child_report.exists() else {"status": "failed", "error": "Child report is missing."}
            child_result["process_exit_code"] = exit_code
            child_result["log"] = file_identity(log_path)
            report["grids"].append(child_result)
            require(exit_code == 0 and child_result["status"] == "passed", f"Grid {grid:g} mm did not pass; inspect its report and log.")
            child_result["termination"] = check_termination(log_path.read_text(encoding="utf-8", errors="replace"), child_result["native_statistics"]["iterations"])
        report["grid_comparison"] = compare_grids(report["grids"][0]["samples"], report["grids"][1]["samples"])
        require(report["grid_comparison"]["passed"], "Two-grid consistency limits were exceeded.")
        report["status"] = "passed"
    except Exception as error:
        report["error"] = str(error)
        report["error_type"] = type(error).__name__
    write_json(output, report)
    print(json.dumps({"status": report["status"], "report": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
