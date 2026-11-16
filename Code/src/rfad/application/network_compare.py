"""! @brief 같은 복소 정의의 실제 표본만 명시적 포트 대응으로 비교한다."""

import math

from rfad.application.network_records import bounded, read_dataset
from rfad.domain.network_library import fail, library


def compare(service, project, document, data):
    """! @brief 보간/기준면 이동 없이 원본 개정과 비교 불가 원인을 함께 반환한다."""
    model = library(document)
    left, left_entry = read_dataset(service, project, model, data["left_id"])
    right, right_entry = read_dataset(service, project, model, data["right_id"])
    order = data["right_port_order"]
    count = len(left["port_ids"])
    if type(order) is not list or len(order) != count or any(type(index) is not int for index in order) or sorted(order) != list(range(count)):
        fail("오른쪽 포트 순서를 중복 없는 명시 인덱스로 지정하십시오.", "right_port_order")
    row, column = data["row"], data["column"]
    if any(type(index) is not int or not 0 <= index < count for index in (row, column)):
        fail("비교 채널이 자료의 포트 범위를 벗어났습니다.", "channel")
    offset, limit = data["offset"], data["limit"]
    if type(offset) is not int or not 0 <= offset < len(left["frequency_hz"]) or type(limit) is not int or not 1 <= limit <= 201:
        fail("비교 표본 조회는 유효한 시작 위치와 1~201개 크기가 필요합니다.", "offset")
    reasons = []
    if len(right["port_ids"]) != count:
        reasons.append("port_count_mismatch")
    if left["parameter_kind"] != right["parameter_kind"]:
        reasons.append("parameter_kind_mismatch")
    for key in ("wave_definition", "phasor_convention"):
        if left[key] == "unknown" or right[key] == "unknown" or left[key] != right[key]:
            reasons.append(key + "_unknown_or_mismatch")
    if len(right["port_ids"]) == count:
        for key in ("reference_planes", "port_modes", "current_orientation"):
            if any(left[key][index] in (None, "unknown") or left[key][index] != right[key][order[index]] for index in range(count)):
                reasons.append(key + "_unknown_or_mismatch")
    indices = {frequency: index for index, frequency in enumerate(right["frequency_hz"])}
    points = []
    for index in range(offset, min(offset + limit, len(left["frequency_hz"]))):
        frequency = left["frequency_hz"][index]
        right_index = indices.get(frequency)
        point_reasons = list(reasons)
        difference = None
        if right_index is None:
            point_reasons.append("frequency_missing")
        elif not reasons:
            left_z0, right_z0 = left["z0_ohm"], right["z0_ohm"]
            if left_z0 is None or right_z0 is None or any(left_z0[index][port] is None or left_z0[index][port] != right_z0[right_index][order[port]] for port in range(count)):
                point_reasons.append("z0_unknown_or_mismatch")
            if not left["valid_mask"][index][row][column] or not right["valid_mask"][right_index][order[row]][order[column]]:
                point_reasons.append("masked_sample")
            if not point_reasons:
                a = left["values_ri"][index][row][column]
                b = right["values_ri"][right_index][order[row]][order[column]]
                value = [a[part] - b[part] for part in range(2)]
                if all(math.isfinite(item) for item in value):
                    difference = value
                else:
                    point_reasons.append("nonfinite_difference")
        points.append({"frequency_hz": frequency, "left_index": index, "right_index": right_index,
                       "difference_ri": difference, "status": "comparable" if difference is not None else "not_comparable", "reasons": point_reasons})
    return bounded({"profile": "rfad.network-comparison/0.1", "left": left_entry, "right": right_entry,
        "right_port_order": order, "frequency_policy": "exact_only", "channel": {"row": row, "column": column},
        "parameter_kind": left["parameter_kind"], "unit": left["unit"], "conditions_equal": left["conditions"] == right["conditions"],
        "physics_validated": False, "points": points, "offset": offset, "total": len(left["frequency_hz"]),
        "next_offset": offset + len(points) if offset + len(points) < len(left["frequency_hz"]) else None})
