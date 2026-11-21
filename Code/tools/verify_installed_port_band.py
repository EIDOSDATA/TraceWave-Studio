"""! @brief 보존된 설치 사례의 포트와 고정 이상 정합을 원시 Fourier 합으로 대조한다."""

import argparse
import cmath
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class Trace:
    """! @brief 두 포트가 공유하는 시간 원점에서 유한 Fourier 합과 미분 상한을 구한다."""

    terms: tuple[tuple[float, float], ...]

    @classmethod
    def load(cls, payload):
        rows = [tuple(map(float, line.split())) for line in payload.decode("ascii").splitlines()
                if line.strip() and not line.lstrip().startswith(("%", "#"))]
        if len(rows) < 3 or any(len(row) != 2 or not all(map(math.isfinite, row)) for row in rows):
            raise ValueError("포트의 유한 시간과 표본이 필요합니다.")
        step = rows[1][0] - rows[0][0]
        if step <= 0 or any(not math.isclose(b[0] - a[0], step, rel_tol=5e-4) for a, b in zip(rows, rows[1:])):
            raise ValueError("포트 시간 간격이 일정해야 합니다.")
        return cls(tuple((-math.tau * t, 2 * step * value) for t, value in rows))

    def at(self, frequency):
        return sum(value * cmath.exp(1j * phase * frequency) for phase, value in self.terms)

    def bounds(self):
        return math.fsum(abs(value) for _, value in self.terms), math.fsum(
            abs(phase * value) for phase, value in self.terms)


def sealed(root, record):
    """! @brief journal이 참조한 파일의 위치, 크기와 SHA256을 확인한다."""
    path = (root / record["uri"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("workspace 밖의 봉인 참조입니다.")
    payload = path.read_bytes()
    if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
        raise ValueError("봉인 결과의 바이트가 다릅니다.")
    return payload


def inputs(root, run_id):
    """! @brief 현재 저장 commit의 결과에서 정규 표본과 두 원시 포트만 읽는다."""
    pointer = json.loads((root / "current.json").read_bytes())
    commit = str(UUID(pointer["commit_id"]))
    manifest_payload = (root / "commits" / commit / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_payload).hexdigest() != pointer["manifest_sha256"]:
        raise ValueError("workspace manifest 봉인이 다릅니다.")
    state = json.loads(sealed(root, json.loads(manifest_payload)["state"]))
    relative = f"solver-artifacts/{run_id}/normalized.json"
    result, = (row for row in state["solver_results"].values() if row["normalized"]["uri"] == relative)
    records = {row["role"]: row["artifact"] for row in result["files"]}
    normalized = json.loads(sealed(root, result["normalized"]))
    voltage, current = (Trace.load(sealed(root, records[role])) for role in ("raw/port_ut_1", "raw/port_it_1"))
    return normalized, voltage, current, result["normalized"]["sha256"]


def audit(normalized, voltage, current, shunt_c, series_kind, series_value):
    """! @brief 원본 복소 대조 및 유한 변환의 연속 주파수 상한을 계산한다."""
    samples = normalized["samples"]
    start, stop = samples[0]["frequency_hz"], samples[-1]["frequency_hz"]
    case = normalized["provenance"]["analysis_plan"]["case"]
    reference = case["port"]["resistance_ohm"]
    if reference != 50 or (start, stop, len(samples)) != (2.4e9, 2.4835e9, 51):
        raise ValueError("이 검증의 포트와 대역은 50 ohm, 2.400~2.4835 GHz의 51점입니다.")
    original = 0.0
    for row in samples:
        f = row["frequency_hz"]
        u, i = voltage.at(f), current.at(f)
        reflection = (u - reference * i) / (u + reference * i)
        original = max(original, abs(reflection - complex(*row["s11"])))
    if original > 1e-12:
        raise ValueError("재계산한 복소 반사가 기존 정규 표본과 일치하지 않습니다.")

    # @brief 입력 전압과 전류에 대한 전 대역 절대값/미분 상한을 곱의 미분으로 전파한다.
    u_bound, u_slope = voltage.bounds()
    i_bound, i_slope = current.bounds()
    if series_kind == "C":
        z_bound, z_slope = 1 / (math.tau * start * series_value), 1 / (math.tau * start**2 * series_value)
    else:
        z_bound, z_slope = math.tau * stop * series_value, math.tau * series_value
    y_bound, y_slope = math.tau * stop * shunt_c, math.tau * shunt_c
    v_bound = u_bound + z_bound * i_bound
    v_slope = u_slope + z_bound * i_slope + z_slope * i_bound
    slope = v_slope + reference * (i_slope + y_bound * v_slope + y_slope * v_bound)
    # @brief 양 끝점과 가장 가까운 점까지의 최대 거리, 수치 계산 여유를 함께 반영한다.
    steps = 3200
    spacing = (stop - start) / steps
    error = slope * spacing / 2 + (v_bound + reference * (i_bound + y_bound * v_bound)) * 1e-12
    worst, enclosure, worst_hz = 0.0, 0.0, start
    for index in range(steps + 1):
        f = start + index * spacing
        z = 1 / (1j * math.tau * f * series_value) if series_kind == "C" else 1j * math.tau * f * series_value
        i = current.at(f)
        v = voltage.at(f) + z * i
        i += 1j * math.tau * f * shunt_c * v
        numerator, denominator = abs(v - reference * i), abs(v + reference * i)
        if denominator <= error:
            raise ValueError("입사파의 대역 분모 하한을 정할 수 없습니다.")
        ratio = numerator / denominator
        if ratio > worst:
            worst, worst_hz = ratio, f
        enclosure = max(enclosure, (numerator + error) / (denominator - error))
    return {"sample_count": steps + 1, "frequency_step_hz": spacing, "original_max_complex_error": original,
            "sampled_worst_s11_db": 20 * math.log10(worst), "sampled_worst_frequency_hz": worst_hz,
            "finite_trace_s11_upper_bound_db": 20 * math.log10(enclosure)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("run", type=UUID)
    parser.add_argument("shunt_c_pf", type=float)
    parser.add_argument("series_kind", choices=("C", "L"))
    parser.add_argument("series_pf_or_nh", type=float)
    args = parser.parse_args()
    if not all(math.isfinite(value) and value > 0 for value in (args.shunt_c_pf, args.series_pf_or_nh)):
        parser.error("정합값에는 유한 양수가 필요합니다.")
    data, voltage, current, digest = inputs(args.workspace.resolve(), str(args.run))
    result = audit(data, voltage, current, args.shunt_c_pf * 1e-12, args.series_kind,
                   args.series_pf_or_nh * (1e-12 if args.series_kind == "C" else 1e-9))
    print(json.dumps({"run_id": str(args.run), "normalized_sha256": digest, **result}))


if __name__ == "__main__":
    main()
