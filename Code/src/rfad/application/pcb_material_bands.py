"""! @brief 사용자 재료의 주파수 구간을 별도 출처 물성에 연결하고 한 실행에서 한 구간만 소비한다."""

import math
from copy import deepcopy

from rfad.application.pcb_geometry import fail
from rfad.domain.design import _uuid


def validate(rows):
    """! @brief 경계에서만 맞닿을 수 있는 실수 주파수 구간과 재료 ID를 검증한다."""
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        fail("E_SCHEMA", "대역별 물성은 1~64개 구간으로 입력하십시오.", "settings.material_bands")
    groups = {}
    for index, row in enumerate(rows):
        field = f"settings.material_bands[{index}]"
        if type(row) is not dict or set(row) != {"material_id", "source_material_id", "start_hz", "stop_hz"}:
            fail("E_SCHEMA", "대상 재료, 출처 재료, 시작과 끝 주파수가 필요합니다.", field)
        for key in ("material_id", "source_material_id"):
            _uuid(row[key], field + "." + key)
        if (any(type(row[key]) not in (int, float) or not math.isfinite(row[key]) for key in ("start_hz", "stop_hz"))
                or not 1e6 <= row["start_hz"] < row["stop_hz"] <= 50e9):
            fail("E_SCHEMA", "재료 구간의 시작과 끝은 1 MHz~50 GHz 범위여야 합니다.", field)
        intervals = groups.setdefault(row["material_id"], [])
        if any(row["start_hz"] < stop and row["stop_hz"] > start for start, stop in intervals):
            fail("E_CONFLICT", "같은 대상 재료의 주파수 구간이 겹칩니다.", field)
        intervals.append((row["start_hz"], row["stop_hz"]))


def select(rows, materials, frequency):
    """! @brief 설정에 지정한 모든 재료의 전 대역을 하나의 보유 출처로 덮는지 확인한다."""
    groups = {}
    for index, row in enumerate(rows):
        field = f"settings.material_bands[{index}]"
        if row["material_id"] not in materials or row["source_material_id"] not in materials:
            fail("E_MATERIAL_UNKNOWN", "대상 및 출처 재료가 모두 현재 프로젝트에 있어야 합니다.", field)
        groups.setdefault(row["material_id"], []).append(row)
    selected = {}
    for identity, options in groups.items():
        found = next((row for row in options if row["start_hz"] <= frequency["start"] < frequency["stop"] <= row["stop_hz"]), None)
        if found is None:
            fail("E_MATERIAL_RANGE", "한 계산 대역 전체를 덮는 단일 물성 구간이 없습니다. 검토할 주파수를 각 구간으로 나누십시오.",
                 "settings.frequency_hz")
        selected[identity] = found
    return selected


def split(settings, sources):
    """! @brief 원래 직접 주파수 표본을 물성 경계로 나누며 결과별 위상과 경계의 양쪽 표본을 보존한다."""
    from rfad.application.pcb_solver import validate_settings

    validate_settings(settings)
    rows = settings.get("material_bands", [])
    if not rows:
        fail("E_SCHEMA", "나눌 재료 구간을 먼저 지정하십시오.", "settings.material_bands")
    band = settings["frequency_hz"]
    start, stop = band["start"], band["stop"]
    samples = band.get("points")
    if samples is None:
        samples = [start + (stop-start)*i/(band["count"]-1) for i in range(band["count"])]
        samples[0], samples[-1] = start, stop
    edges = sorted({start, stop, *(row[key] for row in rows for key in ("start_hz", "stop_hz") if start < row[key] < stop)})
    runs = []
    for low, high in zip(edges, edges[1:]):
        # @brief 사용자가 요청한 범위 사이의 물성 공백도 표본 유무와 무관하게 점검한다.
        select(rows, sources, {"start": low, "stop": high})
        points = [f for f in samples if low <= f <= high]
        if len(points) < 3:
            fail("E_SCHEMA", "각 재료 구간에서 요청한 독립 주파수 표본이 3개 이상 필요합니다.", "settings.frequency_hz")
        child = deepcopy(settings)
        child["frequency_hz"] = {"start": points[0], "stop": points[-1], "count": len(points), "points": points}
        if "radiation" in child:
            original = child["radiation"]["frequency_hz"]
            requested = [f for f in original if points[0] <= f <= points[-1]]
            if not requested:
                fail("E_SCHEMA", "방사 및 전력 비교에는 각 물성 대역 안에 방사 관찰 주파수를 지정하십시오.",
                     "settings.radiation.frequency_hz")
            child["radiation"]["frequency_hz"] = requested
        if "field_probe" in child and not points[0] <= child["field_probe"]["frequency_hz"] <= points[-1]:
            child.pop("field_probe")
        validate_settings(child)
        runs.append(child)
    return runs
