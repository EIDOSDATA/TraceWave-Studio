"""! @brief 저장된 직접 계산 표본으로 IFA 수렴 비교 그림을 만든다.

@details matplotlib이 있는 별도 과학 계산 환경에서 실행하며 solver를 시작하지 않는다.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def render(report_path, output):
    """! @brief 세 독립 연구의 S11과 마지막 두 수준의 복소 차이를 표시한다."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "completed" or report.get("schema") != "rfad.ifa-convergence-run/0.1":
        raise ValueError("완료한 연구 보고서가 필요합니다.")
    csv_path = report_path.with_suffix(".samples.csv")
    raw = csv_path.read_bytes()
    expected = report["samples_csv_artifact"]
    if expected["path"] != csv_path.name or expected["bytes"] != len(raw) or expected["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("직접 계산 CSV가 보고서에 기록된 바이트와 다릅니다.")
    groups = {}
    with csv_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            groups.setdefault(row["case"], []).append(row)
    fig, panels = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    titles = {"mesh": "Mesh refinement", "boundary": "PML distance", "termination": "Time termination"}
    delta_panel = panels[1, 1]
    for axis, panel in zip(("mesh", "boundary", "termination"), (panels[0, 0], panels[0, 1], panels[1, 0])):
        cases = [case for case in report["cases"] if case["axis"] == axis]
        for case in cases:
            rows = groups[case["label"]]
            settings = case["settings"]
            if axis == "mesh":
                label = f'h = {settings["grid_mm"]:g} mm'
            elif axis == "boundary":
                clearance = settings["air_padding_mm"] - 8 * settings["mesh_policy"]["air_cell_mm"]
                label = f'PCB to PML = {clearance:g} mm'
            else:
                label = f'Energy = {settings["end_criterion"]:g}'
            panel.plot([float(row["frequency_hz"]) / 1e9 for row in rows],
                       [float(row["s11_db"]) if row["s11_db"] else float("nan") for row in rows], label=label)
        panel.set(title=titles[axis], xlabel="Frequency (GHz)", ylabel="S11 (dB)")
        panel.axvspan(2.4, 2.4835, color="#777777", alpha=0.08)
        panel.grid(alpha=0.25)
        panel.legend(fontsize=8)
        left, right = (groups[case["label"]] for case in cases[-2:])
        if [row["frequency_hz"] for row in left] != [row["frequency_hz"] for row in right]:
            raise ValueError("마지막 두 수준의 주파수 배열이 다릅니다.")
        values = [abs(complex(float(a["s11_real"]), float(a["s11_imag"])) - complex(float(b["s11_real"]), float(b["s11_imag"]))) for a, b in zip(left, right)]
        delta_panel.plot([float(row["frequency_hz"]) / 1e9 for row in left], values, label=titles[axis])
    delta_panel.axhline(report["study"]["acceptance_profile"]["max_s11_complex_delta"], color="#aa3333", linestyle="--", label="Declared limit")
    delta_panel.set(title="Last two levels: complex S11 difference", xlabel="Frequency (GHz)", ylabel="|Delta S11|")
    delta_panel.grid(alpha=0.25)
    delta_panel.legend(fontsize=8)
    stability = report["assessment"]["numerical_stability"]["status"]
    fig.suptitle("TraceWave Studio - IFA numerical study\n"
                 "Explicit material assumptions; local gap feed; no measured accuracy claim\n"
                 f"Status: {stability} | Shaded area: 2.400-2.4835 GHz (context only)", fontsize=12)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output.with_suffix(".png"), dpi=170)
    fig.savefig(output.with_suffix(".svg"))
    plt.close(fig)


def main():
    """! @brief 별도 환경에서 보고서와 같은 표본을 시각화한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.report, args.output)


if __name__ == "__main__":
    main()
