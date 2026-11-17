"""! @brief 고정 스냅샷의 유한 출력 옵션과 연관 도면 입력을 정의한다."""
from copy import deepcopy
import math
from uuid import UUID

from rfad.application.cad import build_cad_input
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import object_label
from rfad.domain.precision_dimensions import dimensions

PROFILE = "rfad.exchange.drawing/0.1"
MAX_INPUT_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 768 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_FILES = 35
READS = {"export.context", "export.list", "export.get", "export.receipt"}


def fields(value, required, optional=()):
    """! @brief 미지 입력을 조용히 버리지 않고 명시적으로 거절한다."""
    if type(value) is not dict or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ProjectError("E_SCHEMA", "출력 요청의 필드가 유효하지 않습니다.")
    return value


def identity(value):
    """! @brief 명시적인 정규 UUID만 원본 식별로 받는다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise ProjectError("E_SCHEMA", "출력 원본 식별자가 유효하지 않습니다.") from error
    return value


def hash_value(value):
    """! @brief 소유 원본과 묶을 SHA256을 검사한다."""
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ProjectError("E_HASH", "출력 SHA256이 유효하지 않습니다.")
    return value


def validate_request(method, context, data):
    """! @brief 옛 STEP 요청과 분리된 새 도면 profile만 받는다."""
    fields(context, {"project_id"})
    identity(context["project_id"])
    if method == "export.verify":
        fields(data, {"job_id", "manifest_sha256"})
        identity(data["job_id"])
        hash_value(data["manifest_sha256"])
        return
    fields(data, {"snapshot", "profile", "format", "options"} | ({"review_hash"} if method == "export.build" else set()))
    fields(data["snapshot"], {"snapshot_id", "content_hash"})
    identity(data["snapshot"]["snapshot_id"])
    hash_value(data["snapshot"]["content_hash"])
    if data["profile"] != PROFILE or data["format"] not in ("pdf", "svg", "dxf"):
        raise ProjectError("E_UNSUPPORTED", "지원하는 연관 도면 profile/형식을 선택하십시오.")
    if method == "export.build":
        hash_value(data["review_hash"])
    options(data["options"], data["format"])


def options(value, format_name, document=None):
    """! @brief 실제 축척과 명시 뷰만 허용하고 제작용 좌표와 도면 주석을 구분한다."""
    fields(value, {"mode", "sheet", "orientation", "scale", "views", "dimensions", "notes"})
    if value["mode"] not in ("drawing", "fabrication_geometry") or value["sheet"] not in ("A4", "A3") or value["orientation"] not in ("portrait", "landscape"):
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 도면 용지 또는 출력 mode입니다.")
    scale = value["scale"]
    if type(scale) not in (int, float) or not math.isfinite(scale) or not .01 <= scale <= 100:
        raise ProjectError("E_SCHEMA", "도면 축척은 0.01~100의 유한값이어야 합니다.")
    if any(type(value[name]) is not bool for name in ("dimensions", "notes")):
        raise ProjectError("E_SCHEMA", "치수 및 주석 포함은 명시적인 boolean입니다.")
    views = value["views"]
    if type(views) is not list or not 1 <= len(views) <= 8:
        raise ProjectError("E_RESOURCE", "도면 뷰는 1~8개입니다.")
    layer_ids = None if document is None else {layer["id"] for layer in document["stackup"]}
    for view in views:
        if type(view) is not dict:
            raise ProjectError("E_SCHEMA", "도면 뷰가 유효하지 않습니다.")
        kind = view.get("kind")
        if kind in ("layer", "detail"):
            fields(view, {"kind", "layer_id"} | ({"bounds_mm", "label"} if kind == "detail" else set()))
            identity(view["layer_id"])
            if layer_ids is not None and view["layer_id"] not in layer_ids:
                raise ProjectError("E_SCHEMA", "선택한 도면 층이 스냅샷에 없습니다.")
            if kind == "detail":
                bounds = view["bounds_mm"]
                if (type(bounds) is not list or len(bounds) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in bounds)
                        or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]
                        or type(view["label"]) is not str or not 1 <= len(view["label"]) <= 120):
                    raise ProjectError("E_SCHEMA", "상세 뷰는 유한한 명시 범위와 이름이 필요합니다.")
        elif kind in ("outline", "stackup"):
            fields(view, {"kind"})
        else:
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 도면 뷰입니다.")
    if value["mode"] == "fabrication_geometry" and (format_name == "pdf" or scale != 1 or value["dimensions"] or value["notes"]
            or len(views) != 1 or views[0]["kind"] not in ("layer", "outline")):
        raise ProjectError("E_UNSUPPORTED", "제작 기하는 SVG/DXF의 단일 층/외곽, 1:1 축척과 주석 제외만 지원합니다.")
    return deepcopy(value)


def build_input(document, snapshot, data, run_id):
    """! @brief 원본 전체와 실제 평가 치수를 별도 파생 입력으로 고정한다."""
    selected = options(data["options"], data["format"], document)
    projection = build_cad_input(document, snapshot, purpose="step")
    names = {item["id"]: object_label(document, item) for item in document["geometry"]}
    records = [{"entity_id": item["id"], "label": names[item["id"]], "items": dimensions(document, item)}
               for item in document["geometry"]]
    result = {"schema": "rfad.exchange-input/0.1", "profile": PROFILE, "run_id": run_id,
              "snapshot": deepcopy(snapshot), "format": data["format"], "options": selected,
              "projection": projection, "names": names, "dimensions": records}
    if len(canonical_bytes(result)) > MAX_INPUT_BYTES:
        raise ProjectError("E_RESOURCE", "출력 입력과 원문 사본의 합계가 1 MiB를 초과했습니다.")
    return result


def review_hash(value, runtime):
    """! @brief 임의 실행 ID를 제외한 모든 원본/옵션/실제 실행 환경을 검토에 묶는다."""
    fixed = {key: item for key, item in value.items() if key != "run_id"}
    return canonical_hash({"input": fixed, "runtime": runtime})
