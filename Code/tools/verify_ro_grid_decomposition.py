"""! @brief RO4350B 비교의 두 격자 요인과 포트 적분의 영향을 분리한다."""
import argparse
import cmath
from hashlib import sha256
import json
import math
from pathlib import Path

from verify_ro_grid_ablation import COMPLEMENT, DURATION, FREQUENCIES, PORT_NAMES, sha, source


# @brief 구간 안의 4점 Gauss-Legendre 위치와 가중치를 [0, 1]에 옮긴다.
QUADRATURE = (
    (0.06943184420297371, 0.17392742256872693),
    (0.33000947820757187, 0.32607257743127307),
    (0.6699905217924281, 0.32607257743127307),
    (0.9305681557970262, 0.17392742256872693),
)
METRICS = ("incident_w_s2", "accepted_fraction", "accepted_w_s2")


def integrate(path, frequency):
    """! @brief 포트 표본을 선형 연결해 양쪽 기록을 같은 시각 끝까지 독립 적분한다."""
    samples = [tuple(map(float, line.split())) for line in path.read_text(encoding="ascii").splitlines()
               if line.strip() and not line.lstrip().startswith(("%", "#"))]
    if len(samples) < 3 or samples[-1][0] < DURATION:
        raise ValueError("공통 시각까지 선형 보간할 원시 표본이 필요합니다.")
    exponent = -1j * math.tau * frequency
    result = 0j
    for (t0, y0), (t1, y1) in zip(samples, samples[1:]):
        if t0 >= DURATION:
            break
        if t1 <= t0:
            raise ValueError("포트 표본 시각은 증가해야 합니다.")
        width = min(t1, DURATION) - t0
        delta = (y1 - y0) * width / (t1 - t0)
        result += 2 * width * sum(weight * (y0 + node * delta) * cmath.exp(exponent * (t0 + node * width))
                                  for node, weight in QUADRATURE)
    return result


def dt_comparison(sealed_result, workspace, replay, raw_trial):
    """! @brief N7과 시간 간격만 바꾼 실행에서 파 전력의 차이가 적분 방식에 민감한지 확인한다."""
    report = json.loads(sealed_result.read_bytes())
    coarse, = (item for item in report["runs"].values() if item["settings"]["feature_subdivisions"] == 7)
    original, _ = source(workspace, coarse)
    replay_run, = (item for item in replay["runs"] if item["name"] == "same_grid_shorter_dt")
    raw = {name: raw_trial / name for name in PORT_NAMES}
    if any(sha(raw[name]) != replay_run["raw_sha256"][name] for name in PORT_NAMES):
        raise ValueError("재생한 시간 간격 대조의 포트 해시가 다릅니다.")
    changes = []
    for f, n7, trial in zip(FREQUENCIES, replay["original"]["N7"]["points"], replay_run["points"], strict=True):
        accepted = []
        for files in (original, raw):
            v, i = (integrate(files[key], f) for key in PORT_NAMES)
            accepted.append(0.5 * (v * i.conjugate()).real)
        linear = 100 * (accepted[1] / accepted[0] - 1)
        rectangular = 100 * (trial["accepted_w_s2"] / n7["accepted_w_s2"] - 1)
        changes.append({"frequency_hz": f, "linear_gauss_change_percent": linear,
                        "rectangular_change_percent": rectangular, "difference_percentage_points": linear - rectangular})
    return changes


def factorial(replay, complement):
    """! @brief 입사·수용률·수용전력에 두 격자 요인과 잔차를 각각 기록한다."""
    for field in ("fixed_dt_seconds", "cutoff_seconds", "native_executable_sha256", "original"):
        if complement[field] != replay[field]:
            raise ValueError("보완 대조에 사용한 공통 실행 기준이 다릅니다.")
    original, local = (next(row for row in replay["runs"] if row["name"] == name)
                       for name in ("same_grid_shorter_dt", "feed_strips_and_substrate"))
    outer, = (row for row in complement["runs"] if row["name"] == COMPLEMENT and row["status"] == "completed")
    comparisons = []
    for base, inner, remaining, whole in zip(original["points"], local["points"], outer["points"],
                                            replay["original"]["N8"]["points"], strict=True):
        row = {"frequency_hz": base["frequency_hz"]}
        for field in METRICS:
            x, y, z = (option[field] / base[field] for option in (inner, remaining, whole))
            row[field] = {"local_only_percent": 100 * (x - 1), "outside_only_percent": 100 * (y - 1),
                          "whole_percent": 100 * (z - 1), "multiplicative_interaction_percent": 100 * (z / (x * y) - 1)}
        a, b, c, d = (complex(*option["impedance_ohm"]) for option in (base, inner, remaining, whole))
        interaction = d - c - b + a
        row["reactance_ohm"] = {"local_only": (b - a).imag, "outside_only": (c - a).imag,
                                "whole": (d - a).imag, "interaction": interaction.imag}
        comparisons.append(row)
    return comparisons


def compare(sealed_result, workspace, replay_path, raw_trial, complement_path):
    """! @brief 재생 결과의 해시와 두 종류의 독립 재판독을 출력한다."""
    replay = json.loads(replay_path.read_bytes())
    analytic = dt_comparison(sealed_result, workspace.resolve(), replay, raw_trial)
    report = {"schema": "rfad.ro-grid-factorial/0.1", "physics_validated": False,
              "scope": "port_normalization_and_local_mesh_factors",
              "replay_sha256": sha256(replay_path.read_bytes()).hexdigest(), "independent_dt_quadrature": analytic}
    if complement_path is not None:
        complement = json.loads(complement_path.read_bytes())
        report.update(complement_sha256=sha256(complement_path.read_bytes()).hexdigest(),
                      factorial=factorial(replay, complement))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sealed_result", "workspace", "replay", "raw_trial"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--complement", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.sealed_result, args.workspace, args.replay, args.raw_trial, args.complement),
                     allow_nan=False))
