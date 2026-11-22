"""! @brief 스케치 해석, 독립 후보 검토와 저장 명령을 같은 개정에 묶는다."""

from copy import deepcopy
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields, _uuid
from rfad.application.sketch_analysis import POINTS, analyze, label
from rfad.domain import sketch_constraints as sketch
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names, validate_name


GET = "precision.sketch.get"
PREVIEW = "precision.sketch.preview"
MUTATION = "precision.sketch.apply"
READS = {GET, PREVIEW}


def validate_input(context, data, method=MUTATION):
    """! @brief 명시한 스케치, 선택한 후보와 검토 해시만 접수한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    required = {"expected_revision"}
    operation = data.get("operation") if isinstance(data, dict) else None
    if method != GET:
        if operation not in ("complete", "remove"):
            sketch.fail("스케치 구속 작업을 선택하세요.", "operation", "E_SCHEMA")
        required |= {"operation"}
        required |= {"name", "selection_ids", "datum", "axis", "requested"} if operation == "complete" else {"id"}
    if method == MUTATION:
        required |= {"command_id", "review_hash"}
    _fields(data, required)
    _uuid(data["expected_revision"])
    if operation == "complete":
        validate_name(data["name"], "name")
        sketch.validate_setup(data)
        requested = data["requested"]
        if requested is not None:
            if type(requested) is not list or len(requested) > 80:
                sketch.fail("제안 선택 목록을 확인하세요.", "requested", "E_SCHEMA")
            for digest in requested:
                _hash(digest, "requested")
            if len(requested) != len(set(requested)):
                sketch.fail("같은 제안을 한 번만 선택하세요.", "requested", "E_CONFLICT")
    elif operation == "remove":
        _uuid(data["id"])
    if method == MUTATION:
        _uuid(data["command_id"])
        _hash(data["review_hash"], "review_hash")


def _hash(value, field):
    """! @brief 후보와 검토를 고정한 정규 해시만 허용한다."""
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        sketch.fail("검토한 제안의 SHA-256을 확인하세요.", field, "E_SCHEMA")


def _document(service, state, context, data):
    """! @brief 동일 프로젝트와 현재 개정에서만 스케치를 조회하거나 갱신한다."""
    project = service._project(state, context)
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != data["expected_revision"]:
        sketch.fail("스케치 구속의 기준 개정이 바뀌었습니다.", "expected_revision", "E_CONFLICT")
    return document


def get(document):
    """! @brief 선택할 원본 점과 저장한 구속의 이름 및 식별자를 반환한다."""
    model = sketch.Model(document)
    names = display_names(document)
    shapes = []
    for identity, row in model.geometry.items():
        if row["kind"] not in sketch.SHAPES:
            continue
        try:
            anchors = [sketch.anchor(identity, name) for name in sketch.ANCHORS[row["kind"]]]
            points = [{"ref": ref, "name": POINTS[ref["point"]], "point_mm": list(model.location(ref))} for ref in anchors]
        except ProjectError:
            continue
        shapes.append({"id": identity, "name": names[identity], "points": points})
    groups = [{**row, "labels": [label(document, model, item) for item in row["constraints"]],
               "preserved": [label(document, model, item) for item in row["protected"]]}
              for row in sketch.groups(document)]
    return {"profile": sketch.PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
            "shapes": shapes, "groups": groups}


def preview(document, data):
    """! @brief 현재 형상에서 성립하는 독립 제안만 검토하고 원본은 기록하지 않는다."""
    from rfad.domain.project import SCHEMA_VERSION, validate_project

    existing = {row["id"]: row for row in sketch.groups(document)}
    summary = {"variables": None, "before": None, "after": None, "proposals": [], "existing": [], "conflicts": []}
    try:
        replacement = None
        if data["operation"] == "remove":
            identity = data["id"]
            if identity not in existing:
                sketch.fail("삭제할 구속을 찾을 수 없습니다.", "id", "E_CONFLICT")
            setup = existing[identity]
            summary = analyze(document, setup, [])[0]
            summary["after"] = analyze(document, setup, [], skip_group=identity)[0]["before"]
            summary["proposals"] = []
            summary["conflicts"] = []
        else:
            setup = {key: deepcopy(data[key]) for key in ("name", "selection_ids", "datum", "axis")}
            summary, constraints, protected = analyze(document, setup, data["requested"])
            if summary["conflicts"]:
                sketch.fail("선택한 제안과 보존 관계의 충돌을 해결하세요.", "requested", "E_CONFLICT")
            if not constraints:
                sketch.fail("추가할 독립 제안이 없습니다.", "requested", "E_CONFLICT")
            identity = str(uuid5(UUID(document["project_id"]),
                "sketch:" + canonical_hash({"setup": setup, "constraints": constraints})))
            replacement = {"id": identity, **setup, "constraints": constraints, "protected": protected}
        payload = {"id": identity, "expected": existing.get(identity), "replacement": replacement}
        staged = deepcopy(document)
        staged["schema_version"] = SCHEMA_VERSION
        sketch.apply(staged, payload)
        validate_project(staged)
        digest = canonical_hash({"base": canonical_hash(document), "command": payload})
        return {**summary, "can_apply": True, "review_hash": digest, "message": ""}, payload
    except ProjectError as error:
        return {**summary, "can_apply": False, "review_hash": None, "message": error.message}, None


def read(service, method, params):
    """! @brief 조회와 미리보기를 현재 개정의 읽기로만 처리한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        sketch.fail("지원하지 않는 API 버전입니다.", "contract_version", "E_VERSION")
    context, data = params["context"], params["input"]
    validate_input(context, data, method)
    document = _document(service, service.journal.read(), context, data)
    result = get(document) if method == GET else preview(document, data)[0]
    if len(canonical_bytes(result)) > 256 * 1024:
        sketch.fail("스케치 표시 자료가 전송 범위를 초과했습니다.", "selection_ids", "E_RESOURCE")
    return result


def admit(service, state, context, data):
    """! @brief 같은 트랜잭션의 후보 해시를 재검증한 뒤 한 이력으로 적용한다."""
    validate_input(context, data)
    document = _document(service, state, context, data)
    reviewed, payload = preview(document, data)
    if not reviewed["can_apply"]:
        sketch.fail(reviewed["message"], "requested", "E_CONFLICT")
    if reviewed["review_hash"] != data["review_hash"]:
        sketch.fail("미리보기한 구속과 적용할 후보가 다릅니다.", "review_hash", "E_CONFLICT")
    result = service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"],
                            "type": sketch.COMMAND, "payload": payload})
    return {**result, "sketch_id": payload["id"]}
