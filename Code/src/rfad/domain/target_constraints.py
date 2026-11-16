"""! @brief 목표의 공간/매개변수 강제 제약을 성능 평가와 분리하여 저장한다."""

from copy import deepcopy
from uuid import uuid4

from rfad.domain.design import _fields, _fail, _strings, _uuid, resolve_scalar
from rfad.domain.units import Quantity


BOARD_LIMITS = {"board_width_max": "기판 X 최대 크기", "board_height_max": "기판 Y 최대 크기",
                "board_diameter_max": "원형 기판 최대 지름", "board_thickness_max": "적층 전체 최대 두께"}
MAX_PARAMETER_BOUNDS = 16


def empty_constraints():
    """! @brief 수치 기본값 없이 명시적 미정 제약 초안을 만든다."""
    return {**{key: Quantity(None, "length", "mm", "not_applicable", []).to_dict() for key in BOARD_LIMITS},
            "parameter_bounds": [], "manufacturing_profile_id": None, "source_refs": []}


def validate_constraints(document, value, field):
    """! @brief 미정 한계와 실제 위반 상태를 저장하고 참조/차원/역전만 거부한다."""
    _fields(value, {*BOARD_LIMITS, "parameter_bounds", "manufacturing_profile_id", "source_refs"}, field)
    _strings(value["source_refs"], field + ".source_refs")
    for key in BOARD_LIMITS:
        if type(value[key]) is not dict or "parameter_id" in value[key]:
            _fail("E_SCHEMA", "공간 한계에는 literal Quantity가 필요합니다.", field + "." + key)
        bound = resolve_scalar(document, value[key], "length", field + "." + key).value_si
        if bound is not None and bound <= 0:
            _fail("E_UNIT", "공간 최대 크기는 양수 또는 미정이어야 합니다.", field + "." + key)
    profile = value["manufacturing_profile_id"]
    profiles = document["manufacturing_profiles"]
    if type(profiles) is not list:
        _fail("E_SCHEMA", "제조 규칙 목록이 필요합니다.", "manufacturing_profiles")
    if profile is not None and _uuid(profile, field + ".manufacturing_profile_id") not in {row.get("id") for row in profiles if type(row) is dict and type(row.get("id")) is str}:
        _fail("E_CONFLICT", "제약이 참조한 제조 규칙이 없습니다.", field + ".manufacturing_profile_id")
    rows = value["parameter_bounds"]
    if type(rows) is not list or len(rows) > MAX_PARAMETER_BOUNDS:
        _fail("E_RESOURCE", "목표별 매개변수 제약은 최대 16개입니다.", field + ".parameter_bounds")
    ids = []
    for index, row in enumerate(rows):
        location = f"{field}.parameter_bounds[{index}]"
        _fields(row, {"parameter_id", "minimum", "maximum", "integer", "source_refs"}, location)
        identity = _uuid(row["parameter_id"], location + ".parameter_id")
        parameter = document["parameters"].get(identity)
        if parameter is None or identity in ids:
            _fail("E_CONFLICT", "매개변수 제약의 참조가 없거나 중복됩니다.", location + ".parameter_id")
        ids.append(identity)
        dimension = parameter["quantity"]["dimension"]
        if type(row["integer"]) is not bool or (row["integer"] and dimension != "dimensionless"):
            _fail("E_UNIT", "정수 제약은 무차원 매개변수에서만 지원합니다.", location + ".integer")
        bounds = []
        for key in ("minimum", "maximum"):
            if type(row[key]) is not dict or "parameter_id" in row[key]:
                _fail("E_SCHEMA", "범위 한계에는 literal Quantity가 필요합니다.", location + "." + key)
            bounds.append(resolve_scalar(document, row[key], dimension, location + "." + key).value_si)
        if None not in bounds and bounds[0] > bounds[1]:
            _fail("E_UNIT", "매개변수 하한이 상한보다 큽니다.", location)
        _strings(row["source_refs"], location + ".source_refs")
    if ids != sorted(ids):
        _fail("E_SCHEMA", "매개변수 제약은 UUID 오름차순이어야 합니다.", field + ".parameter_bounds")


def apply_constraints(document, payload):
    """! @brief 다른 목표 필드/출처를 유지하며 제약만 교체하거나 원래 미지정 상태로 되돌린다."""
    _fields(payload, {"target_id", "constraints"}, "command.payload")
    identity = _uuid(payload["target_id"], "command.payload.target_id")
    target = next((row for row in document["targets"] if row["id"] == identity), None)
    if target is None:
        _fail("E_CONFLICT", "제약을 편집할 목표가 없습니다.", "command.payload.target_id")
    inverse = {"type": "target.constraints.set", "payload": {"target_id": identity, "constraints": deepcopy(target.get("constraints"))}}
    if payload["constraints"] is None:
        target.pop("constraints", None)
    else:
        target["constraints"] = deepcopy(payload["constraints"])
    target["revision_id"] = str(uuid4())
    return [identity], ["revision", "design_checks", "metrics", "assessment", "exports"], inverse
