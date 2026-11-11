"""! @brief 불변 방사 판정을 확인한 후 수치 비교 그림을 PNG/SVG로 출력한다."""

import argparse
import hashlib
import json
from pathlib import Path


def read_assessment(path):
    """! @brief 진행표의 판정과 같은 폴더 안의 불변 판정 파일이 일치해야 그린다."""
    path = path.resolve()
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("보고서가 표시 상한을 초과했습니다.")
    report = json.loads(path.read_bytes())
    if report["schema"] != "rfad.pcb-radiation-study-run/0.1" or report["status"] != "completed":
        raise ValueError("완료된 방사 연구 보고서가 필요합니다.")
    ref = report["assessment_artifact"]
    source = (path.parent / ref["path"]).resolve()
    if not source.is_relative_to(path.parent) or source.is_symlink():
        raise ValueError("판정 파일은 보고서 폴더 안에 있어야 합니다.")
    raw = source.read_bytes()
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("불변 판정 파일의 길이 또는 hash가 다릅니다.")
    record = json.loads(raw)
    if (record["schema"] != "rfad.pcb-radiation-assessment/0.1" or record["assessment"] != report["assessment"]
            or record["study_hash"] != report["study_hash"] or record["fixture_hash"] != report["fixture_hash"]):
        raise ValueError("진행표와 원래 판정의 근거가 다릅니다.")
    return report["assessment"]


def plot(report, output):
    """! @brief 보간하지 않은 인접 차이와 구면 오차를 명시적 초기 기준과 비교한다."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outputs = [output.with_suffix(suffix) for suffix in (".png", ".svg")]
    if any(path.exists() for path in outputs):
        raise ValueError("새 그림 출력 경로가 필요합니다.")
    assessment = read_assessment(report)
    profile = assessment["acceptance_profile"]
    figure, axes = plt.subplots(3, 3, figsize=(13, 10))
    titles = {"mesh": "Interior grid (mm)", "box": "Recording clearance (mm)", "angle": "Theta/Phi step (deg)"}
    for column, axis in enumerate(("mesh", "box", "angle")):
        definitions = [row for row in assessment["source_settings"] if row["axis"] == axis]
        labels = []
        for row in definitions:
            settings = row["settings"]
            value = settings["grid_mm"] if axis == "mesh" else settings["radiation"]["box_clearance_mm" if axis == "box" else "theta_step_deg"]
            labels.append(str(value))
        comparisons = assessment["numerical_stability"]["axes"][axis]["comparisons"]
        powers = [next(value for value in assessment["power_balance"]["cases"] if value["label"] == row["label"]) for row in definitions]
        frequencies = [row["frequency_hz"] for row in comparisons[0]["frequencies"]]
        for index, frequency in enumerate(frequencies):
            label = f"{frequency / 1e9:g} GHz"
            for line, key in ((0, "pattern_max_delta"), (1, "realized_gain_delta_db")):
                values = [row["frequencies"][index]["metrics"][key] for row in comparisons]
                axes[line][column].plot(range(1, len(labels)), values, marker="o", label=label)
            values = [row["frequencies"][index]["sphere_relative_error"] * 100 for row in powers]
            axes[2][column].plot(range(len(labels)), values, marker="o", label=label)
        for line, limit, ylabel in ((0, profile["max_pattern_delta"], "Adjacent pattern max delta"),
                                    (1, profile["max_gain_delta_db"], "Adjacent realized-gain delta (dB)"),
                                    (2, profile["max_sphere_relative_error"] * 100, "Sphere / NF2FF Prad error (%)")):
            panel = axes[line][column]
            panel.axhline(limit, color="firebrick", linestyle="--", linewidth=1, label="Initial limit")
            panel.set_xticks(range(len(labels)), labels)
            panel.set_ylim(bottom=0)
            panel.set_xlabel(titles[axis])
            panel.set_ylabel(ylabel)
            panel.grid(alpha=0.3)
            panel.legend(fontsize=8)
    status = assessment["numerical_stability"]["status"]
    figure.suptitle("PCB NF2FF numerical study: " + status + "\nFabrication/measurement unvalidated; independent absorption integral not evaluated", fontsize=12)
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    output.parent.mkdir(parents=True, exist_ok=True)
    for path in outputs:
        figure.savefig(path, dpi=150)
    plt.close(figure)
    return [{"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in outputs]


def main():
    """! @brief 추가 solver 실행 없이 별도 경로에만 그림을 생성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps({"status": "written", "figures": plot(args.report, args.output)}))
        return 0
    except Exception as error:
        print(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
