"""! @brief 명시적 사용자 PCB의 물리 조건과 독립 해석 계획을 조립한다.

@details 원본 물성을 추정하지 않는다. 기하 투영, 격자 생성과 결과 검증은
전용 모듈에서 담당하며 기존 공개 함수 import 경로는 유지한다.
"""

from copy import deepcopy
import math
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_geometry import (MAX_POLYGON_POINTS, fail, scalar, length, point,
                                            shape_polygons, distance_to_shape, _bounds, _inside_board)
from rfad.application.pcb_mesh import MAX_GRID_POINTS, mesh_lines, validate_policy
from rfad.application.pcb_projection import EPSILON0, project_pcb
from rfad.application.pcb_results import (RAW_NAMES, normalization_contract, read_statistics_values,
                                         check_termination, validate_preparation, validate_result)
from rfad.application.solver import _snapshot, _runtime, _uuid
from rfad.domain.project import validate_project
from rfad.domain.pcb_selection import EXTENSION_KEY as PCB_SELECTION_EXTENSION

PROFILE = "rfad.openems.pcb-single-port/0.1"


def validate_settings(settings):
    """! @brief 공개 설정을 명시적이고 유한한 범위로 한정한다."""
    keys = {"frequency_hz", "grid_mm", "air_padding_mm", "curve_tolerance_mm", "max_timesteps", "end_criterion"}
    if type(settings) is not dict or not keys <= set(settings) or set(settings) - keys - {"mesh_policy", "radiation", "power_balance", "feature_subdivisions", "compute_profile"}:
        fail("E_SCHEMA", "PCB 해석 설정의 필수 필드가 다릅니다.", "settings")
    frequency = settings["frequency_hz"]
    if type(frequency) is not dict or set(frequency) != {"start", "stop", "count"}:
        fail("E_SCHEMA", "주파수 시작/끝/표본 수가 필요합니다.", "settings.frequency_hz")
    for key in ("start", "stop"):
        if type(frequency[key]) not in (int, float) or not 1e6 <= frequency[key] <= 50e9:
            fail("E_SCHEMA", "지원 주파수 범위는 1 MHz~50 GHz입니다.", "settings.frequency_hz." + key)
    if not frequency["start"] < frequency["stop"] <= frequency["start"] * 2:
        fail("E_UNSUPPORTED", "상수 손실 근사는 stop/start가 2 이하인 대역을 지원합니다.", "settings.frequency_hz")
    if type(frequency["count"]) is not int or not 3 <= frequency["count"] <= 201:
        fail("E_RESOURCE", "주파수 표본 수는 3~201개입니다.", "settings.frequency_hz.count")
    for key, low, high in (("grid_mm", 0.05, 5.0), ("air_padding_mm", 1.0, 200.0), ("curve_tolerance_mm", 0.001, 0.25), ("end_criterion", 1e-9, 1e-3)):
        value = settings[key]
        if type(value) not in (int, float) or not low <= value <= high:
            fail("E_RESOURCE", "PCB 수치 설정의 지원 범위를 벗어났습니다.", "settings." + key)
    if settings["air_padding_mm"] < 10 * settings["grid_mm"] or settings["curve_tolerance_mm"] > settings["grid_mm"] / 2:
        fail("E_GEOMETRY", "공기 여백은 격자의 10배 이상, 곡선 근사 오차는 격자의 절반 이하여야 합니다.", "settings")
    if type(settings["max_timesteps"]) is not int or not 1000 <= settings["max_timesteps"] <= 200000:
        fail("E_RESOURCE", "최대 time step은 1000~200000입니다.", "settings.max_timesteps")
    if "feature_subdivisions" in settings and (type(settings["feature_subdivisions"]) is not int or not 1 <= settings["feature_subdivisions"] <= 8):
        fail("E_RESOURCE", "임계 구간의 최소 분할 수는 1~8의 정수여야 합니다.", "settings.feature_subdivisions")
    if "mesh_policy" in settings:
        validate_policy(settings)
    from rfad.application.pcb_radiation import validate_settings as validate_radiation_settings

    validate_radiation_settings(settings)
    from rfad.application.pcb_power import validate_settings as validate_power_settings

    validate_power_settings(settings)
    from rfad.application.pcb_compute import limits

    limits(settings)


def _payload(document, snapshot, runtime, settings):
    """! @brief 보존한 사용자 설계에서 native 소비 조건을 결정적으로 만든다."""
    validate_project(document)
    _snapshot(snapshot)
    _runtime(runtime)
    validate_settings(settings)
    if snapshot["content_hash"] != canonical_hash(document) or any(snapshot[key] != document[key] for key in ("project_id", "revision_id", "schema_version")):
        fail("E_HASH", "PCB 원본과 스냅샷 참조가 다릅니다.", "snapshot")
    if document["extensions"].keys() - {PCB_SELECTION_EXTENSION}:
        fail("E_UNSUPPORTED", "의미를 해석하지 않은 확장이 있는 PCB는 실행할 수 없습니다.", "extensions")
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    if any(frame["rotation"] != identity or frame["translation_si"] != [0.0, 0.0, 0.0] or frame["handedness"] != "right" for frame in document["frames"].values()):
        fail("E_UNSUPPORTED", "PCB 해석은 항등 오른손 좌표계만 지원합니다.", "frames")
    return {"schema": "rfad.analysis-plan/0.1", "analysis_profile": PROFILE, "runtime_profile": runtime["runtime_profile"],
            "snapshot": deepcopy(snapshot), "source_semantics": deepcopy(document), "runtime_identity": deepcopy(runtime),
            **project_pcb(document, settings)}


def build_pcb_plan(document, snapshot, runtime_identity, settings):
    """! @brief 원본 설계와 가정을 보존한 독립 불변 계획을 생성한다."""
    result = _payload(document, snapshot, runtime_identity, settings)
    result["plan_id"] = str(uuid4())
    if len(canonical_bytes(result)) > 256 * 1024:
        fail("E_RESOURCE", "PCB 해석 계획이 256 KiB를 초과했습니다.", "analysis_plan")
    return result


def validate_pcb_plan(plan):
    """! @brief worker가 소비할 계획을 원본에서 재계산하여 숨은 변경을 차단한다."""
    if type(plan) is not dict or plan.get("analysis_profile") != PROFILE:
        fail("E_VERSION", "지원하지 않는 PCB 계획입니다.")
    _uuid(plan.get("plan_id"), "plan_id")
    expected = _payload(plan["source_semantics"], plan["snapshot"], plan["runtime_identity"], plan["case"]["settings"])
    expected["plan_id"] = plan["plan_id"]
    if canonical_bytes(plan) != canonical_bytes(expected):
        fail("E_HASH", "PCB 해석 계획이 원본 또는 명시 설정과 다릅니다.")
