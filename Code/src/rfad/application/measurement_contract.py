"""! @brief 측정 기록의 공개 요청, 고정 참조와 유한 전송 경계를 정의한다."""

from datetime import datetime, timezone

from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields, _uuid
from rfad.application.result_sources import validate_pin, validate_source
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import digest

PROFILE = "rfad.measurement-workspace/0.1"
WORKSPACE_COMMAND = "measurement.workspace.replace"
MAX_ATTACHMENTS = 16
MAX_ATTACHMENT_BYTES = 512 * 1024
MAX_ATTACHMENT_TOTAL = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
ATTACHMENT_ROLES = ("calibration", "specimen", "environment", "processing", "other")
OPERATIONS = {
    "import_record": {"network", "name", "changes", "reason"},
    "record": {"source", "pin", "previous_record", "name", "changes", "reason"},
    "align": {"source", "pin", "record", "name", "specification"},
    "compare_record": {"name", "reason", "comparison"},
}
COMPARISON_FIELDS = {"left", "right", "right_port_order", "row", "column", "frequency_policy"}
REVIEW_FIELDS = {"expected_revision", "draft_time_utc", "operation", "parameters"}
FIELDS = {
    "measurement.context": {"revision_id", "offset", "limit"},
    "measurement.get": {"record"},
    "measurement.history": {"collection", "record", "section", "offset", "limit"},
    "measurement.preview": REVIEW_FIELDS,
    "measurement.compare": COMPARISON_FIELDS | {"offset", "limit"},
    "measurement.conditions": {"left", "right", "offset", "limit"},
    "measurement.quantity": {"path", "value", "input", "display_unit"},
    "measurement.receipt": {"request_key", "request_key_epoch"},
    "measurement.attachment.read": {"attachment_id", "offset", "limit"},
    "measurement.attachment.add": {"name", "role", "media_type", "content_base64", "sha256"},
    "measurement.apply": REVIEW_FIELDS | {"command_id", "review_hash"},
    "measurement.align": REVIEW_FIELDS | {"command_id", "review_hash"},
}
MUTATIONS = {"measurement.apply", "measurement.align", "measurement.attachment.add"}
READS = set(FIELDS) - MUTATIONS


def fail(message, code="E_SCHEMA", field=None):
    """! @brief 원문을 보정하지 않고 공개 제품 진단으로 거절한다."""
    raise ProjectError(code, message, details={} if field is None else {"field_path": field})


def bounded(value):
    """! @brief 응답 초과를 조용히 자르지 않고 더 작은 조회를 요구한다."""
    if len(canonical_bytes(value)) > MAX_RESPONSE_BYTES:
        fail("측정 응답이 256 KiB를 초과했습니다. 작은 페이지로 조회하십시오.", "E_RESOURCE")
    return value


def record_ref(value):
    """! @brief 같은 이름의 최신 기록으로 대체하지 않는 과거 개정 참조다."""
    _fields(value, {"id", "sha256", "revision_id"})
    _uuid(value["id"])
    _uuid(value["revision_id"])
    digest(value["sha256"], "record.sha256")


def selection(value):
    """! @brief 결과 고정과 측정 기록 고정을 각각 검사한다."""
    _fields(value, {"source", "pin", "record"})
    validate_source(value["source"])
    validate_pin(value["pin"])
    if value["record"] is not None:
        record_ref(value["record"])


def page(data, maximum):
    """! @brief 빈 목록의 첫 페이지도 허용하되 음수와 bool을 거절한다."""
    if (type(data["offset"]) is not int or data["offset"] < 0
            or type(data["limit"]) is not int or not 1 <= data["limit"] <= maximum):
        fail("조회 시작 순번 또는 페이지 크기가 유효하지 않습니다.", "E_RESOURCE")


def draft_time(value):
    """! @brief 초안 작성 시각을 실제 측정 일시나 명령 게시 시각과 구분한다."""
    if type(value) is not str or not 1 <= len(value) <= 40:
        fail("측정 기록 초안의 UTC 작성 시각이 필요합니다.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
            raise ValueError()
    except ValueError as error:
        raise ProjectError("E_SCHEMA", "초안 작성 시각에 명시 UTC offset이 필요합니다.") from error
    return result


def now_text(service):
    """! @brief 초안용 서비스 시각만 제공하며 시료/교정 날짜를 만들지 않는다."""
    return datetime.fromtimestamp(service._now(), timezone.utc).isoformat()


def validate_input(method, context, data):
    """! @brief 조회와 변경의 모든 필드를 명시 계약으로 제한한다."""
    if method not in FIELDS:
        fail("지원하지 않는 측정 작업입니다.", "E_UNSUPPORTED")
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, FIELDS[method])
    for key in ("expected_revision", "command_id", "request_key_epoch", "attachment_id"):
        if key in data:
            _uuid(data[key])
    if "revision_id" in data and data["revision_id"] is not None:
        _uuid(data["revision_id"])
    if "record" in data:
        record_ref(data["record"])
    if "review_hash" in data:
        digest(data["review_hash"], "review_hash")
    if "draft_time_utc" in data:
        draft_time(data["draft_time_utc"])
    if "operation" in data:
        operation = data["operation"]
        if type(operation) is not str or operation not in OPERATIONS:
            fail("지원하지 않는 측정 후보 작업입니다.", "E_UNSUPPORTED")
        if method == "measurement.align" and operation != "align":
            fail("measurement.align에는 명시 정렬 작업만 사용할 수 있습니다.")
        _fields(data["parameters"], OPERATIONS[operation])
    if "left" in data:
        selection(data["left"])
        selection(data["right"])
    if "offset" in data:
        maximum = 201 if method in ("measurement.compare", "measurement.history") else 128 * 1024 if method == "measurement.attachment.read" else 32
        page(data, maximum)
    if method == "measurement.receipt":
        key = data["request_key"]
        if type(key) is not str or not 1 <= len(key) <= 128 or any(ord(char) < 32 for char in key):
            fail("측정 요청의 원래 영수증 키가 필요합니다.")


def validate_read(method, params):
    """! @brief 읽기는 쓰기 영수증을 만들지 않는 기존 봉투를 사용한다."""
    if method not in READS:
        fail("측정 변경 작업은 영수증이 있는 명령으로 요청하십시오.", "E_UNSUPPORTED")
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 측정 API 버전입니다.", "E_VERSION")
    validate_input(method, params["context"], params["input"])
    return params["context"], params["input"]
