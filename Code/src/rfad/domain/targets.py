"""! @brief 사용자 정의 RF 대역과 미평가 목표를 버전이 있는 입력으로 보존한다.

@details 목표 저장은 해석 실행, 수렴, 성능 합격 또는 인증을 뜻하지 않는다.
각 목표는 한 대역을 가지며 복수 목표로 서로 떨어진 대역을 표현한다.
"""

from copy import deepcopy
import math
from uuid import uuid4

from rfad.domain.design import _fields, _fail, _strings, _text, _uuid, resolve_scalar


TARGET_PROFILE = "rfad.target/0.1"
TARGET_COMMANDS = ("target.set", "target.remove")
MAX_TARGETS = 32
MAX_SAMPLES = 1001
METRICS = {
    "s11_db": {"unit": "dB", "operator": "le", "minimum": None, "maximum": 0.0},
    "radiation_efficiency": {"unit": "1", "operator": "ge", "minimum": 0.0, "maximum": 1.0},
    "total_efficiency": {"unit": "1", "operator": "ge", "minimum": 0.0, "maximum": 1.0},
    "fractional_bandwidth": {"unit": "1", "operator": "ge", "minimum": 0.0, "maximum": 2.0},
}
_TARGET_FIELDS = {"id", "revision_id", "name", "physical_mode", "band", "port_id", "reference_impedance", "criteria", "source_refs"}
_INPUT_FIELDS = _TARGET_FIELDS - {"revision_id"}
_NUMERIC_STATUSES = {"user_entered", "source_default", "estimated"}


def _quantity(document: dict, value: object, dimension: str, field: str, *, missing: bool = False) -> float | None:
    """! @brief 목표의 literal 수량을 검사하고 미정과 양수 입력을 구분한다."""
    if type(value) is dict and set(value) == {"parameter_id"}:
        _fail("E_UNSUPPORTED", "목표 입력은 현재 literal 수량만 지원합니다.", field)
    quantity = resolve_scalar(document, value, dimension, field)
    if quantity.value_si is None:
        if not missing or quantity.status.value != "missing":
            _fail("E_SCHEMA", "목표에 필요한 명시적 값 또는 허용된 미정 상태가 필요합니다.", field)
    elif quantity.value_si <= 0.0:
        _fail("E_SCHEMA", "주파수와 기준 임피던스는 양수여야 합니다.", field)
    return quantity.value_si


def _band(document: dict, band: object, field: str) -> None:
    """! @brief 대역, 기준 주파수와 명시적 샘플링 규칙을 검증한다."""
    _fields(band, {"start", "end", "reference", "sampling"}, field)
    start = _quantity(document, band["start"], "frequency", field + ".start")
    end = _quantity(document, band["end"], "frequency", field + ".end")
    if start >= end:
        _fail("E_SCHEMA", "목표 대역의 끝은 시작보다 커야 합니다.", field)
    reference = _quantity(document, band["reference"], "frequency", field + ".reference", missing=True)
    if reference is not None and not start <= reference <= end:
        _fail("E_SCHEMA", "기준 주파수는 목표 대역 안에 있어야 합니다.", field + ".reference")
    sampling = band["sampling"]
    if type(sampling) is not dict:
        _fail("E_SCHEMA", "목표 샘플링 규칙은 object여야 합니다.", field + ".sampling")
    if sampling.get("kind") == "linear":
        _fields(sampling, {"kind", "count"}, field + ".sampling")
        if type(sampling["count"]) is not int or not 2 <= sampling["count"] <= MAX_SAMPLES:
            _fail("E_RESOURCE", "양끝을 포함한 표본 수는 2~1001 정수여야 합니다.", field + ".sampling.count")
    elif sampling.get("kind") == "explicit":
        _fields(sampling, {"kind", "frequencies"}, field + ".sampling")
        values = sampling["frequencies"]
        if type(values) is not list or not 1 <= len(values) <= MAX_SAMPLES:
            _fail("E_RESOURCE", "명시적 주파수 표본은 1~1001개여야 합니다.", field + ".sampling.frequencies")
        previous = None
        for index, value in enumerate(values):
            location = f"{field}.sampling.frequencies[{index}]"
            current = _quantity(document, value, "frequency", location)
            if not start <= current <= end or (previous is not None and current <= previous):
                _fail("E_SCHEMA", "명시적 주파수는 대역 안에서 중복 없이 증가해야 합니다.", location)
            previous = current
    else:
        _fail("E_UNSUPPORTED", "목표 샘플링은 linear 또는 explicit을 지원합니다.", field + ".sampling.kind")


def _criteria(values: object, field: str) -> None:
    """! @brief 지원 지표의 단위, 통과 규칙과 미정 한계를 입력으로만 검사한다."""
    if type(values) is not list or len(values) > len(METRICS):
        _fail("E_RESOURCE", "지원하는 지표별로 최대 한 개의 목표 한계를 지정하십시오.", field)
    seen = set()
    for index, criterion in enumerate(values):
        location = f"{field}[{index}]"
        _fields(criterion, {"metric", "operator", "limit"}, location)
        metric = criterion["metric"]
        if type(metric) is not str or metric not in METRICS:
            _fail("E_UNSUPPORTED", "저장 profile에서 지원하지 않는 목표 지표입니다.", location + ".metric")
        if metric in seen:
            _fail("E_CONFLICT", "동일 대역의 목표 지표가 중복됩니다.", location + ".metric")
        seen.add(metric)
        rule = METRICS[metric]
        if criterion["operator"] != rule["operator"]:
            _fail("E_SCHEMA", "지표의 통과 연산자가 다릅니다.", location + ".operator")
        limit = criterion["limit"]
        _fields(limit, {"value", "unit", "status", "source_refs"}, location + ".limit")
        _strings(limit["source_refs"], location + ".limit.source_refs")
        if limit["unit"] != rule["unit"]:
            _fail("E_UNIT", "지표 한계의 단위가 다릅니다.", location + ".limit.unit")
        status, value = limit["status"], limit["value"]
        if status == "missing" and value is None:
            continue
        if type(status) is not str or status not in _NUMERIC_STATUSES:
            _fail("E_SCHEMA", "목표 한계의 입력 상태와 값이 다릅니다.", location + ".limit.status")
        if type(value) is not float or not math.isfinite(value):
            _fail("E_SCHEMA", "목표 한계는 유한 float64 또는 미정이어야 합니다.", location + ".limit.value")
        if (rule["minimum"] is not None and value < rule["minimum"]) or (rule["maximum"] is not None and value > rule["maximum"]):
            _fail("E_SCHEMA", "목표 한계가 지표의 허용 범위를 벗어났습니다.", location + ".limit.value")


def validate_targets(document: dict) -> None:
    """! @brief 프로젝트 전체 ID와 포트 참조를 포함해 목표 목록을 검증한다.

    @param document 설계 및 매개변수 검증을 통과한 프로젝트 원본.
    @details 호출은 원본과 출처를 변경하지 않으며 미정 성능을 합격으로 만들지 않는다.
    """
    targets = document["targets"]
    if type(targets) is not list or len(targets) > MAX_TARGETS:
        _fail("E_RESOURCE", "목표 목록은 최대 32개여야 합니다.", "targets")
    used = {document["project_id"], document["revision_id"], *document["parent_revision_ids"], *document["parameters"]}
    used.update(item["id"] for item in document["frames"].values())
    if document["board"] is not None:
        used.add(document["board"]["id"])
    for collection in ("materials", "stackup", "nets", "geometry", "ports"):
        used.update(item["id"] for item in document[collection])
    ports = {item["id"] for item in document["ports"]}
    identities = []
    for index, target in enumerate(targets):
        field = f"targets[{index}]"
        _fields(target, _TARGET_FIELDS, field)
        for key in ("id", "revision_id"):
            identity = _uuid(target[key], field + "." + key)
            if identity in used:
                _fail("E_CONFLICT", "목표 또는 목표 개정 UUID가 다른 식별자와 충돌합니다.", field + "." + key)
            used.add(identity)
        identities.append(target["id"])
        _text(target["name"], field + ".name", limit=256)
        _strings(target["source_refs"], field + ".source_refs")
        if target["physical_mode"] != "radiating_rf":
            _fail("E_UNSUPPORTED", "현재 목표 저장은 radiating_rf 모드만 지원합니다.", field + ".physical_mode")
        _band(document, target["band"], field + ".band")
        port = target["port_id"]
        if port is not None:
            _uuid(port, field + ".port_id")
            if port not in ports:
                _fail("E_CONFLICT", "목표가 참조한 포트가 없습니다.", field + ".port_id")
        _quantity(document, target["reference_impedance"], "impedance", field + ".reference_impedance", missing=True)
        _criteria(target["criteria"], field + ".criteria")
    if identities != sorted(identities):
        _fail("E_SCHEMA", "목표 목록은 UUID 오름차순으로 저장해야 합니다.", "targets")


def target_input_status(target: dict) -> dict:
    """! @brief 저장된 입력의 미정 항목을 계산 결과나 합격 판정과 분리한다."""
    criteria = {item["metric"]: item for item in target["criteria"]}
    return {
        "id": target["id"], "revision_id": target["revision_id"],
        "metrics": {name: "missing_target" if name not in criteria or criteria[name]["limit"]["value"] is None else "not_evaluated" for name in METRICS},
        "missing_conditions": [name for name, missing in (
            ("port_id", target["port_id"] is None),
            ("reference_impedance", target["reference_impedance"]["value_si"] is None),
            ("band.reference", target["band"]["reference"]["value_si"] is None),
        ) if missing],
        "evaluation_status": "not_evaluated",
    }


def apply_target_command(document: dict, command_type: str, payload: dict) -> tuple[list[str], list[str], dict]:
    """! @brief 복제본에 목표 변경과 의미상 역명령을 만들고 새 목표 개정을 부여한다."""
    _fields(payload, {"target"} if command_type == "target.set" else {"id"}, "command.payload")
    if command_type == "target.set":
        _fields(payload["target"], _INPUT_FIELDS, "command.payload.target")
        identity = _uuid(payload["target"]["id"], "command.payload.target.id")
    else:
        identity = _uuid(payload["id"], "command.payload.id")
    previous = next((item for item in document["targets"] if item["id"] == identity), None)
    inverse = {"type": "target.remove", "payload": {"id": identity}}
    if previous is not None:
        inverse = {"type": "target.set", "payload": {"target": {key: deepcopy(value) for key, value in previous.items() if key != "revision_id"}}}
    remaining = [item for item in document["targets"] if item["id"] != identity]
    if command_type == "target.set":
        remaining.append({**deepcopy(payload["target"]), "revision_id": str(uuid4())})
    elif previous is None:
        _fail("E_CONFLICT", "제거할 목표가 없습니다.", "command.payload.id")
    document["targets"] = sorted(remaining, key=lambda item: item["id"])
    return [identity], ["revision", "metrics", "assessment", "exports"], inverse
