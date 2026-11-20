"""! @brief 대형 3D 창의 30회 반복 회수 기록을 순서 및 자원 상태와 함께 검사한다."""
import argparse
import json
import math
from pathlib import Path
from statistics import median


MIB = 1024 * 1024
MAX_REPORT_BYTES = MIB
RESOURCE_FIELDS = ("private_commit_bytes", "working_set_bytes", "peak_working_set_bytes", "handles")


def _series(rows, key):
    """! @brief 최초 5회와 마지막 10회의 중앙값 및 개별 최댓값을 구한다."""
    values = [row[key] for row in rows]
    if not all(type(value) is int and value >= 0 for value in values):
        raise ValueError(f"잘못된 자원 카운터: {key}")
    first, last = median(values[:5]), median(values[-10:])
    return {"first_5_median": first, "last_10_median": last, "delta": last - first, "maximum": max(values)}


def _gpu(closed):
    """! @brief 어댑터/node별로 지원하지 않는 표본을 0으로 바꾸지 않는다."""
    keys = [(item["ordinal"], item["node"]) for item in closed[0]["gpu_usage"]]
    if any([(item["ordinal"], item["node"]) for item in row["gpu_usage"]] != keys for row in closed):
        raise ValueError("대형 장면 반복 중 GPU adapter 목록이 달라졌습니다.")
    results = []
    for index, (ordinal, node) in enumerate(keys):
        values = [row["gpu_usage"][index] for row in closed]
        results.append({"ordinal": ordinal, "node": node, **{
            field: None if any(row[field] is None for row in values) else _series(values, field)
            for field in ("local_bytes", "nonlocal_bytes")}})
    return results


def summarize(rows):
    """! @brief 완결된 Release 표본만 비교하고 연속된 원시 record의 무결성을 검사한다."""
    if len(rows) != 63 or rows[0].get("event") != "start" or rows[-1].get("event") != "complete":
        raise ValueError("완료한 30회 열기-닫기 기록이 필요합니다.")
    start, baseline, complete = rows[0], rows[1], rows[-1]
    if (start.get("expected_cycles") != 30 or start.get("canvas") != [1920, 1080] or
            start.get("minimum_closed_ms") != 30000 or complete.get("cycles") != 30 or
            baseline.get("event") != "baseline" or baseline.get("cycle") != 0 or
            baseline["vertex_buffer"]["bytes"] != 0):
        raise ValueError("대형 장면 시험의 크기, 횟수 또는 닫기 후 대기 시간이 다릅니다.")
    times = [row["elapsed_ms"] for row in rows]
    if not all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in times):
        raise ValueError("실행 시각은 유한 단조 시간이어야 합니다.")
    if any(earlier >= later for earlier, later in zip(times, times[1:])):
        raise ValueError("실행 시각이 선행 표본보다 다음이어야 합니다.")

    opened, closed = rows[2:-1:2], rows[3:-1:2]
    for cycle, (active, inactive) in enumerate(zip(opened, closed), start=1):
        if (active["event"] != "open" or inactive["event"] != "closed" or
                active["cycle"] != cycle or inactive["cycle"] != cycle or
                active["vertex_buffer"] != {"bytes": 72000000, "uploads": cycle} or
                inactive["vertex_buffer"] != {"bytes": 0, "uploads": cycle} or
                inactive["elapsed_ms"] - active["elapsed_ms"] < start["minimum_closed_ms"]):
            raise ValueError(f"{cycle}회차의 순서, 업로드 또는 회수 상태가 다릅니다.")

    resources = {key: _series(closed, key) for key in RESOURCE_FIELDS}
    commit = resources["private_commit_bytes"]
    allowed = max(32 * MIB, commit["first_5_median"] * 0.05)
    return {"schema": "rfad.windows-model-lifetime-summary/0.1", "cycles": 30,
            "elapsed_ms": times[-1] - times[0], "closed_resources": resources,
            "gpu_usage": _gpu(closed), "peak_open": {key: _series(opened, key)["maximum"] for key in RESOURCE_FIELDS},
            "minimum_open_to_closed_ms": min(b["elapsed_ms"] - a["elapsed_ms"] for a, b in zip(opened, closed)),
            "private_commit_delta_limit_bytes": allowed, "model_private_commit_delta_within_limit": commit["delta"] <= allowed,
            "f5_full_acceptance_measured": False}


def main():
    """! @brief 원시 JSONL의 유한 크기를 확인하고 검증 요약을 stdout으로 보낸다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    with args.trace.open("rb") as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        parser.error("회수 기록이 1 MiB를 초과했습니다.")
    print(json.dumps(summarize([json.loads(line) for line in raw.splitlines()]), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
