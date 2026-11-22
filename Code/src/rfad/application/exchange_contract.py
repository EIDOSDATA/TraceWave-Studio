"""! @brief 고정 스냅샷의 유한 출력 옵션과 연관 도면 입력을 정의한다."""
from copy import deepcopy
import math
from uuid import UUID

from rfad.application.cad import build_cad_input
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_exchange_projection import exchange_projection
from rfad.domain.errors import ProjectError
from rfad.domain.design import resolve_scalar
from rfad.domain.object_names import display_names
from rfad.domain.precision_dimensions import dimensions
from rfad.domain import drawing_annotations, drawing_layout

PROFILE = "rfad.exchange.drawing/0.1"
PCB_PROFILES = {"rfad.exchange.kicad-board/0.1": "kicad_pcb", "rfad.exchange.kicad-footprint/0.1": "kicad_mod",
                "rfad.exchange.cam/0.1": "gerber_job"}
MAX_INPUT_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 768 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_FILES = 35
MAX_PCB_FILES = 43
READS = {"export.context", "export.list", "export.get", "export.receipt"}


def supported_profile(value):
    """! @brief 임의 profile을 CAD 경로로 잘못 보내지 않는 닫힌 출력 집합을 제공한다."""
    return type(value) is str and (value == PROFILE or value in PCB_PROFILES)


def file_limit(profile):
    """! @brief 도면의 기존 35개와 전체 32층 PCB 패키지의 43개 상한을 구분한다."""
    return MAX_PCB_FILES if type(profile) is str and profile in PCB_PROFILES else MAX_FILES


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
    fields(data, {"snapshot", "profile", "format", "options"} | ({"review_hash"} if method == "export.build" else set()),
           {"view_layer_id"} if method == "export.preview" else set())
    if "view_layer_id" in data:
        identity(data["view_layer_id"])
        if type(data["profile"]) is not str or data["profile"] not in PCB_PROFILES:
            raise ProjectError("E_SCHEMA", "PCB/CAM 미리보기에만 표시 층 선택을 사용할 수 있습니다.")
    fields(data["snapshot"], {"snapshot_id", "content_hash"})
    identity(data["snapshot"]["snapshot_id"])
    hash_value(data["snapshot"]["content_hash"])
    if data["profile"] != PROFILE and type(data["profile"]) is str and data["profile"] in PCB_PROFILES:
        if data["format"] != PCB_PROFILES[data["profile"]]:
            raise ProjectError("E_UNSUPPORTED", "PCB 교환 profile과 파일 형식이 다릅니다.")
        pcb_options(data["options"], data["format"])
        if method == "export.build":
            hash_value(data["review_hash"])
        return
    if data["profile"] != PROFILE or data["format"] not in ("pdf", "svg", "dxf"):
        raise ProjectError("E_UNSUPPORTED", "지원하는 연관 도면 profile/형식을 선택하십시오.")
    if method == "export.build":
        hash_value(data["review_hash"])
    options(data["options"], data["format"])


def options(value, format_name, document=None):
    """! @brief 실제 축척과 명시 뷰만 허용하고 제작용 좌표와 도면 주석을 구분한다."""
    fields(value, {"mode", "sheet", "orientation", "scale", "views", "dimensions", "notes"}, {"annotations"})
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
    if "annotations" in value:
        annotation = value["annotations"]
        drawing_annotations.validate_recipe(annotation)
        if value["mode"] != "drawing" or not value["dimensions"] or views.count(annotation["view"]) != 1:
            raise ProjectError("E_SCHEMA", "자동 치수에는 출력에 한 번 선택한 기술 도면 뷰와 치수 포함이 필요합니다.")
    if value["mode"] == "fabrication_geometry" and (format_name == "pdf" or scale != 1 or value["dimensions"] or value["notes"]
            or len(views) != 1 or views[0]["kind"] not in ("layer", "outline")):
        raise ProjectError("E_UNSUPPORTED", "제작 기하는 SVG/DXF의 단일 층/외곽, 1:1 축척과 주석 제외만 지원합니다.")
    return deepcopy(value)


def pcb_options(value, format_name, projection=None):
    """! @brief PCB/CAM의 고정 원점/1:1와 명시 풋프린트 또는 전체 사용 층만 받는다."""
    if format_name == "kicad_pcb":
        fields(value, set())
    elif format_name == "kicad_mod":
        fields(value, {"footprint_id"})
        identity(value["footprint_id"])
        if projection is not None and value["footprint_id"] not in {row["id"] for row in projection["footprints"]}:
            raise ProjectError("E_REFERENCE", "선택한 풋프린트가 고정 입력에 없습니다.")
    elif format_name == "gerber_job":
        fields(value, {"layer_ids"})
        if type(value["layer_ids"]) is not list or not 1 <= len(value["layer_ids"]) <= 36:
            raise ProjectError("E_RESOURCE", "CAM은 명시한 1~36개 사용 층이 필요합니다.")
        for item in value["layer_ids"]:
            identity(item)
        if len(set(value["layer_ids"])) != len(value["layer_ids"]):
            raise ProjectError("E_SCHEMA", "CAM 출력 층이 중복되었습니다.")
        if projection is not None:
            required = {row["id"] for row in projection["layers"] if row["role"] == "conductor"}
            required.update(row["id"] for row in projection["artwork_layers"] if row["use_state"] == "used")
            if set(value["layer_ids"]) != required:
                raise ProjectError("E_REFERENCE", "Job 패키지에는 모든 명시 도체층과 사용 중인 마스크/페이스트 층을 함께 선택하십시오.")
    else:
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 PCB/CAM 형식입니다.")
    return deepcopy(value)


def build_input(document, snapshot, data, run_id):
    """! @brief 원본 전체와 실제 평가 치수를 별도 파생 입력으로 고정한다."""
    if data["profile"] in PCB_PROFILES:
        projection = exchange_projection(document, snapshot)
        projection["omissions"] = deepcopy(projection.get("diagnostics", []))
        projection["omissions"] += [{"id": row["id"], "reason": "artwork_use_state=" + row["use_state"]}
                                    for row in projection["artwork_layers"] if row["use_state"] != "used"]
        projection["omissions"] += [{"id": row["id"], "reason": "sidecar_only_rf_port"} for row in document["ports"]]
        if data["format"] == "gerber_job":
            projection["omissions"] += [{"id": row["id"], "reason": "sidecar_only_footprint_ownership"} for row in projection["footprints"]]
            projection["omissions"] += [{"id": row["id"], "reason": "sidecar_only_keepout_rule"} for row in projection["keepouts"]]
        selected = pcb_options(data["options"], data["format"], projection)
        if data["format"] == "kicad_mod":
            owner = next(row for row in projection["footprints"] if row["id"] == selected["footprint_id"])
            included = {row["id"] for row in owner["members"]} | {owner["id"]}
            projection["omissions"] += [{"id": row["id"], "reason": "outside_selected_footprint"}
                for rows in (projection["shapes"], projection["mechanical"]["holes"], projection["mechanical"]["cutouts"],
                             projection["footprints"], projection["apertures"], projection["keepouts"], [projection["board"]])
                for row in rows if row["id"] not in included]
        result = {"schema": "rfad.exchange-input/0.1", "profile": data["profile"], "run_id": run_id,
                  "snapshot": deepcopy(snapshot), "format": data["format"], "options": selected,
                  "projection": projection, "names": deepcopy(projection["names"]), "dimensions": []}
        if len(canonical_bytes(result)) > MAX_INPUT_BYTES:
            raise ProjectError("E_RESOURCE", "PCB 교환 입력과 원문 사본이 1 MiB를 초과했습니다.")
        return result
    selected = options(data["options"], data["format"], document)
    projection = build_cad_input(document, snapshot, purpose="step")
    names = display_names(document)
    records = [{"entity_id": item["id"], "label": names[item["id"]], "items": dimensions(document, item)}
               for item in document["geometry"]]
    for prefix, items in (("board.cutouts", (document.get("board") or {}).get("cutouts", [])),
                          ("pcb.holes", document.get("pcb", {}).get("holes", []))):
        for item in items:
            names[item["id"]] = item["name"]
            records.append({"entity_id": item["id"], "label": item["name"], "items": mechanical_dimensions(document, item, prefix)})
    result = {"schema": "rfad.exchange-input/0.1", "profile": PROFILE, "run_id": run_id,
              "snapshot": deepcopy(snapshot), "format": data["format"], "options": selected,
              "projection": projection, "names": names, "dimensions": records}
    if len(canonical_bytes(result)) > MAX_INPUT_BYTES:
        raise ProjectError("E_RESOURCE", "출력 입력과 원문 사본의 합계가 1 MiB를 초과했습니다.")
    return result


def mechanical_dimensions(document, item, prefix):
    """! @brief 완성 치수와 미정 공구를 원래 Quantity에 연관된 도면 표로 만든다."""
    shape = item["shape"]
    fields = []
    for key, label, unit in (("diameter", "완성 지름", "mm"), ("finished_length", "완성 전체 길이", "mm"),
                             ("finished_width", "완성 폭", "mm"), ("rotation", "회전각", "deg")):
        if key in shape:
            fields.append(("shape." + key, label, unit, shape[key]))
    if "size" in shape:
        fields += [("shape.size." + str(index), label, "mm", value) for index, (value, label) in enumerate(zip(shape["size"], ("폭", "높이")))]
    if "tool_diameter" in item:
        fields.append(("tool_diameter", "실제 공구 지름", "mm", item["tool_diameter"]))
        fields.append(("plating.thickness", "도금 두께", "mm", item["plating"]["thickness"]))
    result = []
    for path, label, unit, original in fields:
        quantity = resolve_scalar(document, original, "angle" if unit == "deg" else "length")
        result.append({"key": "mechanical." + path, "label": label, "unit": unit,
                       "value": None if quantity.value_si is None else quantity.as_unit(unit), "status": quantity.status.value,
                       "field_path": prefix + "." + item["id"] + "." + path, "parameter_id": original.get("parameter_id"),
                       "anchors_mm": [], "source_refs": list(quantity.source_refs)})
    return result


def annotation_catalog(document):
    """! @brief 고정 도면에서 가져올 수 있는 수치에 기계 홀과 절삭 치수를 포함한다."""
    result = drawing_annotations.catalog(document)
    views = ["outline", *(row["id"] for row in document["stackup"] if row["role"] == "conductor")]
    for prefix, items in (("board.cutouts", (document["board"] or {}).get("cutouts", [])),
                          ("pcb.holes", document.get("pcb", {}).get("holes", []))):
        for item in items:
            for quantity in mechanical_dimensions(document, item, prefix):
                result["model_dimensions"].append({"source_id": item["id"], "key": quantity["key"], "name": item["name"],
                                                   "label": quantity["label"], "value": quantity["value"],
                                                   "unit": quantity["unit"], "views": views})
    return result


def _footprint_view(projection, footprint_id):
    """! @brief 전체 원문은 유지하고 선택 부품의 파일에 실제 포함되는 객체만 표시한다."""
    result = deepcopy(projection)
    owner = next(row for row in result["footprints"] if row["id"] == footprint_id)
    members = {row["id"] for row in owner["members"]}
    for key in ("shapes", "apertures", "keepouts"):
        result[key] = [row for row in result[key] if row["id"] in members]
    if any(row["kind"] != "pad" for row in result["shapes"]):
        raise ProjectError("E_UNSUPPORTED", "이 KiCad 풋프린트 profile은 소유 패드 형상을 지원합니다. 다른 소유 구리를 생략하지 않습니다.")
    result["mechanical"]["holes"] = [row for row in result["mechanical"]["holes"] if row["id"] in members]
    result["mechanical"]["cutouts"] = []
    result["footprints"] = [owner]
    return result, owner


def _local_footprint_paths(paths, placement):
    """! @brief writer와 같은 역배치를 표시 경계에 한 번 적용하며 Y는 위쪽으로 유지한다."""
    origin = placement["origin_mm"]
    angle = math.radians(placement["rotation_deg"])
    def local(point):
        x, y = point[0] - origin[0], point[1] - origin[1]
        return [x * math.cos(angle) + y * math.sin(angle), -x * math.sin(angle) + y * math.cos(angle)]
    samples = []
    for path in paths:
        for loop in path["loops"]:
            for edge in loop:
                if edge["kind"] == "line":
                    edge["start"], edge["end"] = local(edge["start"]), local(edge["end"])
                    samples.extend((edge["start"], edge["end"]))
                else:
                    edge["center"] = local(edge["center"])
                    edge["start_deg"] -= placement["rotation_deg"]
                    x, y = edge["center"]
                    radius = edge["radius"]
                    samples.extend(([x - radius, y - radius], [x + radius, y + radius]))
    if not samples:
        return [-1.0, -1.0, 1.0, 1.0]
    return [min(row[0] for row in samples) - 1, min(row[1] for row in samples) - 1,
            max(row[0] for row in samples) + 1, max(row[1] for row in samples) + 1]


def pcb_preview(value, view_layer_id=None):
    """! @brief 같은 원본의 실제 평면/대응표를 검토하며 수신 도구의 성공을 미리 확정하지 않는다."""
    projection = value["projection"]
    footprint = None
    if value["format"] == "kicad_mod":
        projection, footprint = _footprint_view(projection, value["options"]["footprint_id"])
    conductors = [row for row in projection["layers"] if row["role"] == "conductor"]
    targets = drawing_layout.pcb_layer_targets(projection, value["format"], value["options"].get("layer_ids"))
    artwork = projection["artwork_layers"]
    used = [row for row in artwork if row["use_state"] == "used"]
    selectable = conductors + used
    if not selectable:
        raise ProjectError("E_GEOMETRY", "PCB 교환에는 명시된 도체 또는 사용 제조층이 필요합니다.")
    selected = next((row for row in selectable if row["id"] == view_layer_id), None) if view_layer_id else (conductors[-1] if conductors else used[-1])
    if selected is None:
        raise ProjectError("E_REFERENCE", "미리볼 제조/도체층이 고정 입력에 없거나 사용 여부가 미정입니다.")
    paths = []
    def path(loops, identity, net_id=None, fill=None):
        return {"kind": "path", "loops": loops, "source_id": identity, "source_name": projection["names"].get(identity, ""),
                "layer_id": selected["id"], "net_id": net_id, "role": "geometry", "stroke": drawing_layout.INK,
                "stroke_width_mm": 0.12, "fill": fill}
    if footprint is None:
        paths.append(path(drawing_layout.substrate_loops(projection, outline_only=True), projection["board"]["id"]))
    elif footprint["placement_envelope"] is not None:
        paths.append(path(drawing_layout.mechanical_loops(footprint["placement_envelope"]), footprint["id"]))
    is_copper = selected in conductors
    if is_copper:
        for shape in projection["shapes"]:
            if shape["kind"] != "via" and shape["layer_id"] == selected["id"]:
                paths.append(path(drawing_layout.copper_loops(projection, shape), shape["id"], shape["net_id"], drawing_layout.COPPER))
            elif shape["kind"] == "via" and next(row["z_min_mm"] for row in conductors if row["id"] == shape["layer_id"]) <= selected["z_min_mm"] <= next(row["z_min_mm"] for row in conductors if row["id"] == shape["end_layer_id"]):
                paths.append(path(drawing_layout.shape_loops(shape), shape["id"], shape["net_id"], drawing_layout.COPPER))
        for item in projection["mechanical"]["holes"]:
            if item["plating"]["state"] == "plated":
                paths.append(path(drawing_layout.mechanical_shell(item), item["id"], item["plating"]["net_id"], drawing_layout.COPPER))
    else:
        for item in projection["apertures"]:
            if item["artwork_layer_id"] == selected["id"]:
                paths.append(path(drawing_layout.mechanical_loops(item["shape"]), item["id"], fill=[125, 182, 160]))
    for item in projection["mechanical"]["holes"]:
        paths.append(path(drawing_layout.mechanical_loops(item["shape"]), item["id"]))
    bounds = drawing_layout.board_bounds(projection["board"])
    coordinate = "world_mm_top_view_no_mirror"
    label = selected["name"] + " / 위에서 본 원본 좌표 / 1:1"
    if footprint is not None:
        bounds = _local_footprint_paths(paths, footprint["placement"])
        coordinate = "footprint_local_mm_y_up_no_mirror"
        label = footprint["name"] + " / 부품 로컬 좌표 / 1:1"
    page = {"unit": "mm", "width_mm": bounds[2] - bounds[0], "height_mm": bounds[3] - bounds[1],
            "view_box_mm": [bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]],
            "primitives": paths, "viewports": [{"rect_mm": [bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]], "world_bounds_mm": bounds,
                "label": label, "dimensions": [], "primitives": [],
                "transform": {"scale": 1, "x_mm": 0, "y_mm": 0, "mirror_x": False}}]}
    mapping = [{"id": row["id"], "name": row["name"], "role": row["role"], "side": row.get("side"),
                "state": row.get("use_state", "explicit_conductor"), "selected": row in selectable,
                "target_label": targets.get(row["id"])} for row in conductors + artwork]
    omissions = deepcopy(projection["omissions"])
    return {"pages": [page], "omissions": omissions, "pcb_preview": {"view_layer_id": selected["id"], "layers": mapping,
            "holes": deepcopy(projection["mechanical"]["holes"]), "cutouts": deepcopy(projection["mechanical"]["cutouts"]),
            "footprints": deepcopy(projection["footprints"]), "names": deepcopy(projection["names"]),
            "coordinate_policy": coordinate, "scale": 1,
            "scope": "source_geometry_preview; recipient_refill_and_file_readback_not_yet_performed"}}


def review_hash(value, runtime):
    """! @brief 임의 실행 ID를 제외한 모든 원본/옵션/실제 실행 환경을 검토에 묶는다."""
    fixed = {key: item for key, item in value.items() if key != "run_id"}
    return canonical_hash({"input": fixed, "runtime": runtime})
