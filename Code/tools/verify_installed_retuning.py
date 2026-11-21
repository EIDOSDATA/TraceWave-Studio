"""! @brief 봉인 설치 후보의 이상 정합을 다시 탐색하고 독립 실행에 교차 적용한다."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

from verify_installed_port_uncertainty import (
    ROUTES, START, STEPS, STOP, Circuit, collapse, payload, relative_bound, sampled, shorten,
)


TRAINING_STEPS = 400
BOUNDS = ((0.2, 5.0), (0.2, 5.0))
SEED = 17468


def circuit(route):
    """! @brief pF와 nH로 기록된 두 이상 소자를 SI 값으로 변환한다."""
    parallel, series, value = route
    return Circuit(parallel * 1e-12, series, value * (1e-12 if series == "C" else 1e-9))


def frequency_projection(trace, frequencies):
    """! @brief 탐색 표본을 원시 Fourier 항에서 작은 행렬 묶음으로 계산한다."""
    terms = np.asarray(trace.terms)
    batches = np.array_split(frequencies, math.ceil(len(frequencies) / 64))
    return np.concatenate([np.exp(1j * batch[:, None] * terms[None, :, 0]) @ terms[:, 1] for batch in batches])


def propose(kind, cases):
    """! @brief 보존 세 실행과 두 유한 시간 절단의 관측 상한을 최소화하는 소자를 찾는다."""
    end = cases["fine"]["evidence"]["last_common_time_s"]
    traces = [cases[key]["traces"] for key in ("fine", "coarse", "boundary")]
    traces.extend(shorten(traces[0], end * fraction) for fraction in (0.9, 0.8))
    frequencies = np.linspace(START, STOP, TRAINING_STEPS + 1)
    projections = [tuple(frequency_projection(trace, frequencies) for trace in pair) for pair in traces]
    series = ROUTES[kind][1]

    def objective(values):
        """! @brief 탐색에서 사용한 파의 표본값과 각 표본 사이의 관측 여유를 합산한다."""
        parallel, value = values
        model = circuit((parallel, series, value))
        curves = []
        for (voltage, current), (v, i) in zip(projections, traces, strict=True):
            reflection, incidence = model.waves(frequencies, voltage, current)
            pad = model.bound(v, i) * STEPS / TRAINING_STEPS
            denominator = abs(incidence) - pad
            if np.any(denominator <= 0):
                return math.inf
            gamma = reflection / incidence
            radius = pad * (1 + abs(gamma)) / denominator
            curves.append((gamma, radius))
        gamma, radius = curves[0]

        def distance(first, second):
            """! @brief 두 파의 복소 표본 차이에 각 기록의 구간 여유를 더한다."""
            a, ra = curves[first]
            b, rb = curves[second]
            return np.max(abs(a - b) + ra + rb)

        return np.max(abs(gamma) + radius) + distance(0, 1) + distance(1, 2) + max(distance(0, 3), distance(0, 4))

    optimized = differential_evolution(objective, BOUNDS, rng=SEED)
    if not optimized.success or not math.isfinite(optimized.fun):
        raise ValueError("이상 정합 탐색이 유한한 후보에 도달하지 못했습니다.")
    parallel, serial = (round(float(value), 8) for value in optimized.x)
    return parallel, series, serial


def validation_cases(folder, kind, reference):
    """! @brief 더 정밀한 두 검증 실행은 탐색 자료와 분리해 봉인을 확인한다."""
    if folder is None:
        return {}
    target = json.loads((folder / "report.json").read_bytes())
    if target["kind"] != kind or target["baseline"] != reference["evidence"]:
        raise ValueError("정밀 실행 보고서와 채택 기준 실행이 다릅니다.")
    cases = {}
    for key in ("end_criterion", "grid_mm"):
        row = target["axes"].get(key, {})
        if row.get("status") != "completed":
            continue
        evidence = row["evidence"]
        value = payload(folder / "workspace", evidence["run_id"])
        if value["evidence"] != evidence or value["physical"] != reference["physical"]:
            raise ValueError("정밀 실행의 물리 입력 또는 봉인 기록이 다릅니다.")
        cases[key] = value
    return cases


def compare_holdouts(route, reference, cases):
    """! @brief 동일 소자를 기준과 독립 검증 실행에 고정해 전 대역 상한을 비교한다."""
    if not cases:
        return {}
    model = circuit(route)
    baseline = sampled(model, reference["traces"])
    report = {}
    for key, case in cases.items():
        points = sampled(model, case["traces"])
        peak = max(abs(value) + radius for value, radius in points)
        report[key] = {"evidence": case["evidence"], "continuous_upper_db": 20 * math.log10(peak),
                       "complex_difference_upper": relative_bound(baseline, points)}
    return report


def examine(kind, cases, refinement):
    """! @brief 탐색 소자를 전체 표본과 도함수로 다시 검산하고 독립 실행과 비교한다."""
    original = collapse(kind, cases)
    choice = propose(kind, cases)
    retuned = collapse(kind, cases, choice)
    additional = validation_cases(refinement, kind, cases["fine"])
    return {
        "schema": "rfad.installed-ideal-retuning/0.1",
        "scope": "synthetic_ideal_circuit_on_observed_finite_port_records",
        "numerical_accuracy_validated": False,
        "original": original,
        "retuned": retuned,
        "search": {"seed": SEED, "sample_count": TRAINING_STEPS + 1, "component_bounds_pf_or_nh": BOUNDS},
        "independent_original": compare_holdouts(ROUTES[kind], cases["fine"], additional),
        "independent_retuned": compare_holdouts(choice, cases["fine"], additional),
        "independent_unmatched": compare_holdouts((0.0, "L", 0.0), cases["fine"], additional),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=ROUTES)
    for label in ("fine", "coarse", "boundary"):
        parser.add_argument("--" + label, required=True, nargs=2, metavar=("WORKSPACE", "RUN_ID"))
    parser.add_argument("--refinement", type=Path)
    args = parser.parse_args()
    cases = {}
    for label in ("fine", "coarse", "boundary"):
        folder, identity = getattr(args, label)
        cases[label] = payload(Path(folder), identity)
    print(json.dumps(examine(args.kind, cases, args.refinement), allow_nan=False))
