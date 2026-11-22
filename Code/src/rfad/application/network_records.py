"""! @brief 네트워크의 불변 원본/정규 자료와 표시용 작은 응답을 분리한다."""

from copy import deepcopy
import hashlib
import json
import math

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.network_data import validate_dataset
from rfad.domain.network_library import fail

MAX_RESPONSE = 256 * 1024
MAX_PAGE = 201


def bounded(value):
    """! @brief 원문을 생략하는 대신 응답 예산 초과를 명시적으로 알린다."""
    if len(canonical_bytes(value)) > MAX_RESPONSE:
        fail("네트워크 응답이 256 KiB를 초과했습니다.", "response", "E_RESOURCE")
    return value


def reference(path, payload):
    """! @brief 미리보기는 파일을 쓰지 않고 게시할 바이트의 참조를 만든다."""
    return {"uri": path, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def read_json(service, project, artifact):
    """! @brief 다른 프로젝트의 참조와 변조 파일을 읽기 전에 차단한다."""
    if not artifact["uri"].startswith(project["path"] + "/"):
        fail("자료가 현재 프로젝트의 저장 영역에 속하지 않습니다.", "artifact.uri", "E_HASH")
    raw = service.journal.read_artifact(artifact)
    try:
        result = json.loads(raw)
        if canonical_bytes(result) != raw:
            fail("네트워크 자료의 정규 바이트가 다릅니다.", "artifact", "E_HASH")
        return result
    except (ValueError, UnicodeError, RecursionError) as error:
        fail("네트워크 자료 파일을 해석할 수 없습니다: " + str(error), "artifact", "E_HASH")


def find_record(model, collection, identity):
    """! @brief 목록 선택은 표시 이름 대신 안정 ID를 사용한다."""
    row = next((item for item in model[collection] if item["id"] == identity), None)
    if row is None:
        fail("현재 프로젝트에 선택한 자료가 없습니다.", collection, "E_CONFLICT")
    return row


def read_dataset(service, project, model, identity):
    """! @brief 메타데이터만 믿지 않고 실제 정규 자료와 mask를 다시 검사한다."""
    entry = find_record(model, "datasets", identity)
    for key in ("dataset", "normalized_hdf5", "raw", "diagnostics"):
        if entry[key] is not None and not entry[key]["uri"].startswith(project["path"] + "/"):
            fail("자료의 원본/정규 파일이 현재 프로젝트에 속하지 않습니다.", key, "E_HASH")
    data = read_json(service, project, entry["dataset"])
    validate_dataset(data)
    return data, entry


def descriptor(data):
    """! @brief 큰 표본 배열을 응답에 복제하지 않고 축/조건/출처를 설명한다."""
    result = {key: deepcopy(data[key]) for key in (
        "schema", "parameter_kind", "unit", "port_ids", "port_names", "wave_definition",
        "phasor_convention", "reference_planes", "port_modes", "current_orientation", "conditions", "source_refs")}
    frequencies = data["frequency_hz"]
    z0 = data["z0_ohm"]
    result.update(sample_count=len(frequencies), frequency_min_hz=frequencies[0], frequency_max_hz=frequencies[-1],
                  source_snapshot=deepcopy(data["provenance"].get("snapshot")),
                  z0_ohm=None if z0 is None else deepcopy(z0[0]),
                  z0_frequency_dependent=False if z0 is None else any(row != z0[0] for row in z0[1:]),
                  invalid_value_count=sum(not flag for matrix in data["valid_mask"] for row in matrix for flag in row),
                  sample_origins=sorted(set(data["sample_origin"])))
    return result


def assessment_summary(assessment):
    """! @brief 평가 전체는 봉인 파일에 보존하고 화면 요약에는 명시된 앞 8개 표본만 둔다."""
    result = deepcopy(assessment)
    frequencies = [point["frequency_hz"] for criterion in result["criteria"]
                   for point in criterion.get("points", [])]
    #! 표시 단위는 현재 페이지가 아닌 실제 평가의 전체 목표 표본 범위에 고정한다.
    result["frequency_min_hz"] = min(frequencies) if frequencies else None
    result["frequency_max_hz"] = max(frequencies) if frequencies else None
    for criterion in result["criteria"]:
        points = criterion.pop("points", [])
        criterion.update(point_count=len(points), points_preview=points[:8],
                         points_preview_limit=8, all_points_method="network.assessment.points")
    evidence = result.get("evidence", {})
    target = evidence.get("target_original")
    if target is not None and len(canonical_bytes(target)) > 64 * 1024:
        evidence.pop("target_original")
        evidence["target_original_summary"] = {"id": target["id"], "revision_id": target["revision_id"], "name": target["name"],
            "sha256": canonical_hash(target), "bytes": len(canonical_bytes(target)), "full_original_in": "assessment_artifact"}
    return result


def _quality(data, index):
    """! @brief 명시 기준을 가진 S 행렬의 최대 특이값과 상호성 잔차를 계산한다."""
    size = len(data["port_ids"])
    if data["parameter_kind"] != "S":
        return None, "not_applicable", None, "not_applicable"
    references = None if data["z0_ohm"] is None else data["z0_ohm"][index]
    if (not references or references[0] is None or references[0][1] != 0 or references[0][0] <= 0
            or any(value != references[0] for value in references)
            or data["wave_definition"] not in ("power", "traveling")
            or any(mode != "single_ended" for mode in data["port_modes"])
            or any(direction != "into_dut" for direction in data["current_orientation"])):
        return None, "quality_basis_unknown", None, "quality_basis_unknown" if size == 2 else "not_applicable"
    if not all(flag for row in data["valid_mask"][index] for flag in row):
        return None, "matrix_incomplete", None, "matrix_incomplete" if size == 2 else "not_applicable"
    pairs = [pair for row in data["values_ri"][index] for pair in row]
    scale = max(abs(value) for pair in pairs for value in pair)
    if scale == 0:
        sigma, residual = 0.0, 0.0
    elif size == 1:
        sigma, residual = math.hypot(*pairs[0]), None
    else:
        a, b, c, d = (complex(x / scale, y / scale) for x, y in pairs)
        left, right = abs(a) ** 2 + abs(c) ** 2, abs(b) ** 2 + abs(d) ** 2
        cross = a.conjugate() * b + c.conjugate() * d
        sigma = scale * math.sqrt((left + right + math.hypot(left - right, 2 * abs(cross))) / 2)
        residual = scale * abs(b - c)
    roundoff = 1e-12
    passivity = ("over_unity" if sigma > 1 + roundoff else "finite") if math.isfinite(sigma) else "nonfinite"
    reciprocity = "not_applicable"
    if size == 2:
        reciprocity = ("nonzero_residual" if residual > roundoff else "finite") if math.isfinite(residual) else "nonfinite"
    return (sigma if passivity != "nonfinite" else None, passivity,
            residual if reciprocity in ("nonzero_residual", "finite") else None, reciprocity)


def _group_delay(data, row, column, index):
    """! @brief 한 채널의 실제 인접 S 표본만으로 위상 기울기를 ns로 산출한다."""
    if data["parameter_kind"] != "S":
        return None, "not_applicable"
    sign = {"exp(+j*omega*t)": -1, "exp(-j*omega*t)": 1}.get(data["phasor_convention"])
    if sign is None:
        return None, "unknown_phasor"
    axis = data["frequency_hz"]
    values = data["values_ri"]
    mask = data["valid_mask"]

    def phase(point):
        """! @brief 크기 0 또는 실제 미정 표본에는 위상을 두지 않는다."""
        if not mask[point][row][column]:
            return None
        real, imaginary = values[point][row][column]
        return math.atan2(imaginary, real) if real or imaginary else None

    center = phase(index)
    if center is None:
        return None, "phase_unavailable"
    slopes = []
    for neighbor in (index - 1, index + 1):
        if not 0 <= neighbor < len(axis):
            continue
        nearby = phase(neighbor)
        if nearby is None:
            return None, "phase_unavailable"
        delta = math.remainder(nearby - center, math.tau)
        if math.isclose(abs(delta), math.pi, rel_tol=0.0, abs_tol=1e-10):
            return None, "ambiguous_phase_step"
        span = axis[neighbor] - axis[index]
        slopes.append((abs(span), delta / span))
    if not slopes:
        return None, "insufficient_samples"
    estimate = slopes[0][1]
    if len(slopes) == 2:
        (left, first), (right, second) = slopes
        span = left + right
        estimate = first * (right / span) + second * (left / span)
    delay = sign * estimate * (1e9 / math.tau)
    return (delay, "finite") if math.isfinite(delay) else (None, "nonfinite")


def samples(data, offset=0, limit=MAX_PAGE, row=0, column=0):
    """! @brief 표본을 보간하지 않고 요청 범위의 실제 복소 값과 표시값만 투영한다."""
    if type(offset) is not int or not 0 <= offset < len(data["frequency_hz"]):
        fail("표본 시작 위치가 범위를 벗어났습니다.", "offset")
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        fail("표본 페이지 크기는 1~201입니다.", "limit", "E_RESOURCE")
    count = len(data["port_ids"])
    if any(type(index) is not int or not 0 <= index < count for index in (row, column)):
        fail("복소 행렬 채널이 범위를 벗어났습니다.", "channel")
    output = []
    for index in range(offset, min(offset + limit, len(data["frequency_hz"]))):
        pair = data["values_ri"][index][row][column]
        status = data["sample_status"][index][row][column]
        valid = data["valid_mask"][index][row][column]
        magnitude = math.hypot(*pair) if valid else None
        magnitude_db = 20 * math.log10(magnitude) if data["parameter_kind"] == "S" and magnitude is not None and magnitude > 0 else None
        phase = math.degrees(math.atan2(pair[1], pair[0])) if magnitude is not None and magnitude > 0 else None
        vswr = (1 + magnitude) / (1 - magnitude) if data["parameter_kind"] == "S" and row == column and magnitude is not None and magnitude < 1 else None
        db_state = "not_applicable" if data["parameter_kind"] != "S" else "missing" if not valid else "negative_infinity" if magnitude == 0 else "finite" if magnitude_db is not None and math.isfinite(magnitude_db) else "nonfinite"
        phase_state = "missing" if not valid else "undefined_zero_magnitude" if magnitude == 0 else "finite"
        vswr_state = "not_applicable" if data["parameter_kind"] != "S" or row != column else "missing" if not valid else "positive_infinity" if magnitude == 1 else "undefined_active" if magnitude > 1 else "finite" if math.isfinite(vswr) else "nonfinite"
        delay, delay_state = _group_delay(data, row, column, index)
        sigma, passivity, reciprocity, reciprocity_state = _quality(data, index)
        output.append({"index": index, "frequency_hz": data["frequency_hz"][index],
                       "sigma_max": sigma, "sigma_max_state": passivity,
                       "reciprocity_residual": reciprocity, "reciprocity_residual_state": reciprocity_state,
                       "group_delay_ns": delay, "group_delay_ns_state": delay_state,
                       "z0_ohm": None if data["z0_ohm"] is None else deepcopy(data["z0_ohm"][index]),
                       "real": pair[0] if valid else None, "imag": pair[1] if valid else None,
                       "magnitude": magnitude if magnitude is None or math.isfinite(magnitude) else None,
                       "magnitude_db": magnitude_db if magnitude_db is None or math.isfinite(magnitude_db) else None,
                       "phase_deg": phase, "vswr": vswr if vswr is None or math.isfinite(vswr) else None,
                       "magnitude_db_state": db_state, "phase_state": phase_state, "vswr_state": vswr_state,
                       "status": status, "valid": valid, "origin": data["sample_origin"][index],
                       "zero_magnitude": magnitude == 0 if magnitude is not None else False})
    return {"samples": output, "offset": offset, "total": len(data["frequency_hz"]),
            "next_offset": offset + len(output) if offset + len(output) < len(data["frequency_hz"]) else None,
            "channel": {"row": row, "column": column}, "parameter_kind": data["parameter_kind"], "unit": data["unit"]}
