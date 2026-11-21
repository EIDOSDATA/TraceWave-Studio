"""! @brief 같은 설치 후보의 회로 입력면에서 격자·경계·유한 기록의 복소 차이를 대조한다."""
import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from uuid import UUID

from verify_installed_port_band import Trace, inputs


START, STOP = 2.4e9, 2.4835e9
STEPS = 3200
SPACING = (STOP - START) / STEPS
LIMIT_DB = -10
REFERENCE_OHM = 50
PHYSICAL = ("board", "layers", "shapes", "port", "vias", "environment", "surface_layers", "mechanical_voids",
            "materials", "excitation", "delta_unit_m", "frequency_hz")
ROUTES = {"ifa": (1.4438032647540764, "C", 1.5916610574558383),
          "arc": (1.8770043638707952, "L", 1.8937272092811077)}


@dataclass(frozen=True)
class Circuit:
    """! @brief 고정 직렬 소자와 입력 쪽 병렬 커패시턴스로 포트의 파를 구한다."""

    parallel_f: float
    series_kind: str
    series_value: float

    def waves(self, f, voltage, current):
        """! @brief 부하의 복소 V/I를 공통 50 ohm 정합 입력면의 파로 변환한다."""
        omega = math.tau * f
        series = 1 / (1j * omega * self.series_value) if self.series_kind == "C" else 1j * omega * self.series_value
        u = voltage + series * current
        ri = REFERENCE_OHM * (current + 1j * omega * self.parallel_f * u)
        return u - ri, u + ri

    def bound(self, voltage, current):
        """! @brief 표본 간 파의 변화량을 V/I와 회로의 미분 상한으로 구한다."""
        v, dv = voltage.bounds()
        i, di = current.bounds()
        if self.series_kind == "C":
            z = 1 / (math.tau * START * self.series_value)
            dz = z / START
        else:
            dz = math.tau * self.series_value
            z = dz * STOP
        u, du = v + z * i, dv + z * di + dz * i
        lower, upper = math.tau * self.parallel_f, math.tau * STOP * self.parallel_f
        slope = du + REFERENCE_OHM * (di + upper * du + lower * u)
        return slope * SPACING * 0.5 + (u + REFERENCE_OHM * (i + upper * u)) * 1e-12


def payload(workspace, run_id):
    """! @brief journal에 등록된 결과와 시간 트레이스를 검증하고 원래 51개 정규 표본을 대조한다."""
    result, voltage, current, digest = inputs(workspace.resolve(), UUID(run_id))
    samples = result["samples"]
    plan = result["provenance"]["analysis_plan"]
    case = plan["case"]
    if (samples[0]["frequency_hz"], samples[-1]["frequency_hz"], len(samples)) != (START, STOP, 51):
        raise ValueError("같은 승인 대역과 51개 직접 표본이 필요합니다.")
    if case["port"]["resistance_ohm"] != REFERENCE_OHM:
        raise ValueError("50 ohm 기준면이 필요합니다.")
    for row in samples:
        f = row["frequency_hz"]
        v, i = voltage.at(f), REFERENCE_OHM * current.at(f)
        if abs((v - i) / (v + i) - complex(*row["s11"])) > 1e-12:
            raise ValueError("복소 포트 변환과 보존 표본이 다릅니다.")
    end = min(-trace.terms[-1][0] / math.tau for trace in (voltage, current))
    return {"physical": {key: case.get(key) for key in PHYSICAL}, "traces": (voltage, current),
            "evidence": {"run_id": run_id, "normalized_sha256": digest, "last_common_time_s": end,
                         "reference_plane": case["port"]["reference_plane"], "settings": case["settings"],
                         "snapshot_sha256": plan["snapshot"]["content_hash"]}}


def sampled(circuit, traces):
    """! @brief 모든 주파수 구간을 덮는 복소 반사 중심과 거리 상한을 구한다."""
    voltage, current = traces
    addition = circuit.bound(voltage, current)
    points = []
    for index in range(STEPS + 1):
        f = START + index * SPACING
        n, d = circuit.waves(f, voltage.at(f), current.at(f))
        if abs(d) <= addition:
            raise ValueError("입사 파의 표본 간 하한이 양수가 아닙니다.")
        reflected = n / d
        # @brief |n(f)/d(f)-n(f0)/d(f0)|에 같은 표본 간의 입사 파 하한을 적용한다.
        radius = addition * (1 + abs(reflected)) / (abs(d) - addition)
        points.append((reflected, radius))
    return points


def relative_bound(first, second):
    """! @brief 두 유한 기록의 연속 대역 복소 반사 차이를 상한으로 대조한다."""
    return max(abs(a - b) + da + db for (a, da), (b, db) in zip(first, second, strict=True))


def shorten(traces, end):
    """! @brief 이미 기록된 시간 구간의 끝만 줄여 민감도를 확인한다."""
    return tuple(Trace(tuple(term for term in trace.terms if -term[0] / math.tau <= end)) for trace in traces)


def collapse(kind, cases, route=None):
    """! @brief 기준 격자와 대조한 교환 조건의 복소 편차 및 관측 상한을 보고한다."""
    fine, coarse, boundary = (cases[key] for key in ("fine", "coarse", "boundary"))
    if any(other["physical"] != fine["physical"] for other in (coarse, boundary)):
        raise ValueError("격자나 경계 외의 고정 설치 물리 입력이 다릅니다.")
    p, serial, value = ROUTES[kind] if route is None else route
    circuit = Circuit(p * 1e-12, serial, value * (1e-12 if serial == "C" else 1e-9))
    curves = {name: sampled(circuit, case["traces"]) for name, case in cases.items()}
    cell = {name: max(abs(value) + radius for value, radius in curve) for name, curve in curves.items()}
    fine_curve = curves["fine"]
    grid = relative_bound(fine_curve, curves["coarse"])
    air = relative_bound(curves["coarse"], curves["boundary"])
    end = fine["evidence"]["last_common_time_s"]
    time = {str(percentage): relative_bound(fine_curve, sampled(circuit, shorten(fine["traces"], end * percentage / 100)))
            for percentage in (90, 80)}
    total = cell["fine"] + grid + air + max(time.values())
    return {"kind": kind, "shunt_capacitance_pf": p, "series_kind": serial, "series_value_pf_or_nh": value,
            "runs": {name: case["evidence"] for name, case in cases.items()},
            "continuous_upper_db": {name: 20 * math.log10(v) for name, v in cell.items()},
            "complex_difference_upper": {"grid": grid, "boundary_at_coarse_grid": air, "shortened_percent": time},
            "observed_additive_margin_upper_db": 20 * math.log10(total),
            "observed_additive_margin_within_goal": 20 * math.log10(total) <= LIMIT_DB,
            "numerical_accuracy_validated": False}


def main():
    """! @brief 후보마다 세 보존 실행을 받아 유한 기록에 한정한 비교를 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=ROUTES)
    for label in ("fine", "coarse", "boundary"):
        parser.add_argument("--" + label, required=True, nargs=2, metavar=("WORKSPACE", "RUN_ID"))
    args = parser.parse_args()
    cases = {name: payload(Path(folder), run) for name in ("fine", "coarse", "boundary") for folder, run in [getattr(args, name)]}
    result = {"schema": "rfad.installed-port-sensitivity-budget/0.1", "scope": "observed_finite_records_only",
              "limit_db": LIMIT_DB, "frequency_step_hz": SPACING, "candidate": collapse(args.kind, cases)}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
