"""! @brief 스마트 치수를 읽고 검토한 치수와 형상 변경을 한 개정에 적용한다."""

from copy import deepcopy
from uuid import UUID, uuid5

from rfad.application.canvas import project_canvas
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields, _uuid
from rfad.application.smart_dimension_geometry import drive, drive_reason
from rfad.domain import smart_dimensions as model
from rfad.domain.object_names import display_names, validate_name
from rfad.domain.pcb_features import make_patch
from rfad.domain.precision_transform import MAX_COORDINATE_MM, fail, number
from rfad.domain.errors import ProjectError


GET = "precision.smart.get"
PREVIEW = "precision.smart.preview"
MUTATION = "precision.smart.apply"
READS = {GET, PREVIEW}


def _measure(document, anchors):
    """! @brief 미정 또는 삭제된 참조에는 원래 식별자와 사유를 유지한다."""
    try:
        points = model.positions(document, anchors)
        return {"measurement": model.measurement(points), "reason": "", "drive_reason": drive_reason(document, anchors)}
    except ProjectError as error:
        return {"measurement": None, "reason": error.message, "drive_reason": error.message}


def get(document):
    """! @brief 기준 후보와 저장 치수를 당시 원본 좌표에서 평가한다."""
    names = display_names(document)
    holes = []
    for identity, row in model.hole_sources(document).items():
        try:
            center = model.hole_center(document, row)
        except ProjectError:
            continue
        holes.append({"id": identity, "name": row.get("name") or names[identity], "point_mm": center})
    geometry_names = display_names(document)
    ports = []
    for row in document["ports"]:
        anchor = {"kind": "feed", "ids": [row["id"]]}
        ports.append({"id": row["id"], "name": row["name"], **_measure(document, anchor),
                      "reference_name": geometry_names.get(row["reference_geometry_id"], "미정"),
                      "positive_name": geometry_names.get(row["positive_geometry_id"], "미정")})
    return {"profile": model.PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
            "holes": holes, "ports": ports,
            "items": [{**row, **_measure(document, row["anchors"])} for row in model.dimensions(document)]}


def validate_input(context, data, method=MUTATION):
    """! @brief 서비스는 명시 개정과 검토 해시로만 변경을 접수한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    required = {"expected_revision"}
    if method != GET:
        required |= {"operation"}
    if method == MUTATION:
        required |= {"command_id", "review_hash"}
    operation = data.get("operation") if isinstance(data, dict) else None
    if method != GET:
        if operation not in ("save", "remove"):
            fail("지원하는 치수 편집 작업을 선택하세요.", "operation", "E_SCHEMA")
        required |= {"record"} if operation == "save" else {"id"}
    _fields(data, required)
    _uuid(data["expected_revision"])
    if operation == "save":
        row = _fields(data["record"], {"id", "name", "anchors", "mode", "target_mm"})
        if row["id"] is not None:
            _uuid(row["id"])
        validate_name(row["name"], "name")
        model.validate_anchors(row["anchors"])
        if row["mode"] not in ("reference", "driving") or (row["mode"] == "reference" and row["target_mm"] is not None):
            fail("참조 치수와 구동 치수 모드를 확인하세요.", "mode", "E_SCHEMA")
        if row["mode"] == "driving" and not model.EPSILON_MM < number(row["target_mm"], "target_mm") <= MAX_COORDINATE_MM:
            fail("양수 구동 거리를 mm로 입력하세요.", "target_mm", "E_UNIT")
    elif operation == "remove":
        _uuid(data["id"])
    if method == MUTATION:
        _uuid(data["command_id"])
        digest = data["review_hash"]
        if type(digest) is not str or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            fail("검토한 후보의 해시를 요구합니다.", "review_hash", "E_SCHEMA")


def _document(service, state, context, data):
    """! @brief 편집 앞뒤에 같은 소유 개정을 확인한다."""
    project = service._project(state, context)
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != data["expected_revision"]:
        fail("스마트 치수의 기준 개정이 바뀌었습니다.", "expected_revision", "E_CONFLICT")
    return document


def preview(document, data):
    """! @brief 좌표를 이동하기 전에 제약, 접촉, 기존 구동 치수와 미리보기 해시를 확인한다."""
    from rfad.domain.project import SCHEMA_VERSION, validate_project

    lookup = {row["id"]: row for row in model.dimensions(document)}
    try:
        replacement = deepcopy(data.get("record"))
        candidate, patch = document, None
        metrics = None
        if data["operation"] == "remove":
            identity = data["id"]
            if identity not in lookup:
                fail("삭제할 치수를 찾을 수 없습니다.", "id", "E_CONFLICT")
        else:
            anchors = replacement["anchors"]
            identity = replacement["id"]
            if identity is not None:
                if identity not in lookup or anchors != lookup[identity]["anchors"]:
                    fail("기존 치수는 저장한 기준 쌍을 사용합니다.", "anchors", "E_CONFLICT")
            else:
                if any(model.key_for(anchors) == model.key_for(row["anchors"]) for row in lookup.values()):
                    fail("이미 저장한 쌍입니다. 저장 치수 목록에서 편집하세요.", "anchors", "E_CONFLICT")
                identity = str(uuid5(UUID(document["project_id"]), "smart:" + canonical_hash(anchors)))
            replacement["id"] = identity
            if replacement == lookup.get(identity):
                fail("저장한 치수와 같은 입력입니다.", "record", "E_CONFLICT")
            if replacement["mode"] == "driving":
                candidate = drive(document, anchors, replacement["target_mm"])
                if candidate != document:
                    patch = make_patch(document, candidate, "smart_dimension.drive", "스마트 치수 구동 거리 변경")
            try:
                metrics = model.measurement(model.positions(candidate, anchors))
            except ProjectError:
                if identity not in lookup or replacement["mode"] != "reference":
                    raise
        payload = {"id": identity, "expected": lookup.get(identity), "replacement": replacement, "pcb_patch": patch}
        staged = deepcopy(document)
        staged["schema_version"] = SCHEMA_VERSION
        model.apply(staged, payload)
        validate_project(staged)
        digest = canonical_hash({"base": canonical_hash(document), "command": payload})
        return {"can_apply": True, "review_hash": digest, "message": "", "measurement": metrics,
                "scene": project_canvas(staged) if patch is not None else None,
                "changes": [row["id"] for row in patch["changes"]] if patch else []}, payload
    except ProjectError as error:
        return {"can_apply": False, "review_hash": None, "message": error.message, "diagnostic": error.code,
                "measurement": None, "scene": None, "changes": []}, None


def _bounded(value):
    """! @brief 미리보기의 실제 장면을 일부 생략하지 않고 프레임 한도를 적용한다."""
    if len(canonical_bytes(value)) > 512 * 1024:
        fail("스마트 치수의 표시 자료가 전송 범위를 초과했습니다.", "scene", "E_RESOURCE")
    return value


def read(service, method, params):
    """! @brief 조회와 미리보기로 개정이나 선형 형상을 변경하지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 API 버전입니다.", "contract_version", "E_VERSION")
    context, data = params["context"], params["input"]
    validate_input(context, data, method)
    document = _document(service, service.journal.read(), context, data)
    return _bounded(get(document) if method == GET else preview(document, data)[0])


def admit(service, state, context, data):
    """! @brief 적용 트랜잭션에서 같은 후보를 계산하고 한 이력으로 보존한다."""
    validate_input(context, data)
    document = _document(service, state, context, data)
    reviewed, payload = preview(document, data)
    if not reviewed["can_apply"]:
        fail(reviewed["message"], "record", "E_CONFLICT")
    if reviewed["review_hash"] != data["review_hash"]:
        fail("미리보기와 적용할 치수/형상이 다릅니다. 다시 검토하세요.", "review_hash", "E_CONFLICT")
    result = service._apply(state, context, {"expected_revision": data["expected_revision"],
                            "command_id": data["command_id"], "type": model.COMMAND, "payload": payload})
    return {**result, "dimension_id": payload["id"]}
