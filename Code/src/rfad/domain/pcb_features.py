"""! @brief PCB 기계/제조/풋프린트 원본과 유한 원자 patch 및 역명령을 검증한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design import _fields, _number, _reference, _strings, _text, _uuid, _vector2, resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import validate_name
from rfad.domain.planar import validate_region

SCHEMA = "rfad.pcb/0.1"
PROJECT_SCHEMA = "rfad.project/0.6"
COMMAND = "pcb.features.replace"
REPLAY_COMMAND = "pcb.features.replay"
COLLECTIONS = {"hole": "holes", "footprint": "footprints", "artwork_layer": "artwork_layers",
               "aperture": "apertures", "keepout": "keepouts", "import": "imports"}
LIMITS = {"holes": 64, "footprints": 32, "artwork_layers": 4, "apertures": 128,
          "keepouts": 64, "imports": 16, "cutouts": 16}
PATCH_COLLECTIONS = {"board.cutouts", *("pcb." + key for key in COLLECTIONS.values()), "geometry", "ports", "connections"}
MAX_PATCH_BYTES = 256 * 1024


def fail(message, field="pcb", code="E_SCHEMA"):
    """! @brief 원문 필드와 함께 실패하며 미정값을 추정하지 않는다."""
    raise ProjectError(code, message, details={"field_path": field})


def empty_pcb():
    """! @brief 읽기 전용 빈 모델을 만들고 원본에 삽입하지 않는다."""
    return {"schema": SCHEMA, **{key: [] for key in COLLECTIONS.values()}}


def pcb(document):
    """! @brief 없는 신형 컨테이너를 저장하지 않고 사본만 제공한다."""
    return deepcopy(document.get("pcb", empty_pcb()))


def records(document, collection):
    """! @brief 허용한 collection만 읽고 임의 JSON pointer를 사용하지 않는다."""
    if collection == "board.cutouts":
        return (document.get("board") or {}).get("cutouts", [])
    if collection.startswith("pcb.") and collection[4:] in COLLECTIONS.values():
        return document.get("pcb", empty_pcb())[collection[4:]]
    if collection in ("geometry", "ports", "connections"):
        return document[collection]
    fail("지원하지 않는 PCB collection입니다.", collection, "E_UNSUPPORTED")


def presence(document):
    """! @brief 과거 absent와 명시한 빈 목록을 구분한다."""
    return {"pcb": "pcb" in document, "board_cutouts": "cutouts" in (document.get("board") or {})}


def validate_shape(document, value, field="shape", *, kinds=None):
    """! @brief 공통 평면 형상의 원문과 미정 수량을 검증하며 좌표를 정규화하지 않는다."""
    if type(value) is not dict:
        fail("평면 형상 원본이 필요합니다.", field)
    kind = value.get("kind")
    keys = {"circle": {"center", "diameter"}, "rectangle": {"center", "size", "rotation"},
            "capsule": {"center", "finished_length", "finished_width", "rotation"},
            "polygon": {"outer", "holes"}}
    if kind not in keys or (kinds is not None and kind not in kinds):
        fail("지원하지 않는 평면 형상 종류입니다.", field + ".kind", "E_UNSUPPORTED")
    _fields(value, {"kind", *keys[kind]}, field)
    if kind == "polygon":
        outer, holes = value["outer"], value["holes"]
        if type(outer) is not list or type(holes) is not list or len(holes) > 8:
            fail("다각형 외곽/구멍 목록이 유효하지 않습니다.", field)
        if any(type(loop) is not list or len(loop) < 3 for loop in [outer, *holes]) or sum(map(len, [outer, *holes])) > 64:
            fail("다각형은 합계 64점/8구멍 이내여야 합니다.", field, "E_RESOURCE")
        loops = [[list(_vector2(document, point, field)) for point in loop] for loop in [outer, *holes]]
        if all(number is not None for loop in loops for point in loop for number in point):
            validate_region(loops[0], loops[1:], field)
    else:
        _vector2(document, value["center"], field + ".center")
        if kind == "circle":
            _number(document, value["diameter"], "length", field + ".diameter", positive=True)
        else:
            _number(document, value["rotation"], "angle", field + ".rotation")
            sizes = value["size"] if kind == "rectangle" else [value["finished_length"], value["finished_width"]]
            if type(sizes) is not list or len(sizes) != 2:
                fail("폭/길이 수량 두 개가 필요합니다.", field)
            length, width = [_number(document, item, "length", field, positive=True) for item in sizes]
            if kind == "capsule" and length is not None and width is not None and length <= width:
                fail("슬롯의 완성 전체 길이는 완성 폭보다 커야 합니다. 같은 값이면 원형을 명시하십시오.", field, "E_GEOMETRY")


def _ids(values, mapping, field, *, maximum=64):
    """! @brief 순서를 보존하되 중복/없는 안정 참조를 거절한다."""
    if type(values) is not list or len(values) > maximum:
        fail("참조 목록의 유한 상한을 초과했습니다.", field, "E_RESOURCE")
    for value in values:
        _reference(value, mapping, field)
    if len(set(values)) != len(values):
        fail("참조가 중복되었습니다.", field, "E_CONFLICT")


def _artifact(value, field):
    """! @brief 원본 파일 이름과 유한 ArtifactRef만 저장하며 파일을 여기서 열지 않는다."""
    from rfad.domain.network_library import digest
    _fields(value, {"uri", "sha256", "bytes"}, field)
    digest(value["sha256"], field + ".sha256")
    _text(value["uri"], field + ".uri", limit=1024)
    parts = value["uri"].split("/")
    if len(parts) < 4 or parts[0] != "projects" or any(item in ("", ".", "..") for item in parts) or any(char in value["uri"] for char in "\\:"):
        fail("PCB 원문 참조는 projects 아래의 정규 상대 경로여야 합니다.", field + ".uri")
    if type(value["bytes"]) is not int or not 0 < value["bytes"] <= 16 * 1024 * 1024:
        fail("PCB 원문 파일 하나는 최대 16 MiB입니다.", field + ".bytes", "E_RESOURCE")


def _origin(row, imports, field, collection):
    """! @brief 수입 원본 식별은 보존한 import 기록에만 연결한다."""
    _strings(row["source_refs"], field + ".source_refs")
    if row["origin"] is not None:
        _fields(row["origin"], {"import_id", "source_object_id"}, field + ".origin")
        _reference(row["origin"]["import_id"], imports, field + ".origin.import_id")
        _text(row["origin"]["source_object_id"], field + ".origin.source_object_id")
        origin = imports[row["origin"]["import_id"]]
        if {"source_object_id": row["origin"]["source_object_id"], "collection": collection, "id": row["id"]} not in origin["bindings"]:
            fail("객체의 수입 출처와 보존한 원본 대응이 다릅니다.", field + ".origin", "E_CONFLICT")


def owner_map(document):
    """! @brief 중복 소유는 검증에서 거절하고 조회에는 한 소유 UUID만 반환한다."""
    return {(member["collection"], member["id"]): row["id"]
            for row in document.get("pcb", empty_pcb())["footprints"] for member in row["members"]}


def validate_pcb(document):
    """! @brief 잘못된 JSON 형태를 구조화 오류로 거절하고 원본을 변경하지 않는다."""
    try:
        _validate_pcb(document)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
        fail("PCB 필드의 JSON 형태/참조/수치가 유효하지 않습니다: " + type(error).__name__, "pcb")


def _validate_pcb(document):
    """! @brief 엔진 없이 PCB 원문/소유권/참조를 검증하고 실제 기하 검수와 구분한다."""
    board = document.get("board")
    declared = "pcb" in document or "cutouts" in (board or {})
    if declared and document["schema_version"] != PROJECT_SCHEMA:
        fail("PCB 기계/제조 원본은 프로젝트 0.6에서만 지원합니다.", "schema_version", "E_VERSION")
    if not declared:
        return
    model = document.get("pcb", empty_pcb())
    _fields(model, {"schema", *COLLECTIONS.values()}, "pcb")
    if model["schema"] != SCHEMA:
        fail("지원하지 않는 PCB 모델 버전입니다.", "pcb.schema", "E_VERSION")
    if board is None:
        fail("PCB 기능을 저장하려면 실제 기판 원본이 필요합니다.", "board")
    all_rows = {**{key: model[key] for key in COLLECTIONS.values()}, "cutouts": board.get("cutouts", [])}
    used = {document["project_id"], document["revision_id"], *document["parent_revision_ids"], board["id"],
            *document["parameters"], *(row["id"] for row in document["frames"].values())}
    for key, values in document.items():
        if type(values) is list:
            used.update(row["id"] for row in values if type(row) is dict and "id" in row)
    used.update(row["revision_id"] for row in document["targets"])
    physical = document["extensions"].get("rfad.physical_setup", {})
    used.update(row["id"] for key in ("surfaces", "parts", "scenarios") for row in physical.get(key, []))
    total = sum(len(document[key]) for key in ("materials", "stackup", "nets", "geometry", "ports"))
    indexes = {}
    for key, rows in all_rows.items():
        if type(rows) is not list or len(rows) > LIMITS[key]:
            fail("PCB collection 상한을 초과했습니다.", key, "E_RESOURCE")
        names, ids = set(), []
        for row in rows:
            if type(row) is not dict:
                fail("PCB 객체 원문은 object여야 합니다.", key)
            identity = _uuid(row.get("id"), key + ".id")
            if identity in used:
                fail("PCB 객체 ID가 다른 원본과 중복됩니다.", key + ".id", "E_CONFLICT")
            used.add(identity)
            ids.append(identity)
            if key != "imports":
                name = validate_name(row.get("name"), key + ".name")
                if name in names:
                    fail("같은 PCB collection의 이름이 중복됩니다.", key + ".name", "E_CONFLICT")
                names.add(name)
        if ids != sorted(ids):
            fail("PCB collection은 UUID 순서로 보존해야 합니다.", key)
        indexes[key] = {row["id"]: row for row in rows}
        total += len(rows)
    if total > 256:
        fail("PCB를 포함한 설계 객체 상한 256개를 초과했습니다.", "pcb", "E_RESOURCE")
    frames = {row["id"]: row for row in document["frames"].values()}
    layers = {row["id"]: row for row in document["stackup"] if row["role"] == "conductor"}
    nets = {row["id"]: row for row in document["nets"]}
    materials = {row["id"]: row for row in document["materials"]}
    geometry = {row["id"]: row for row in document["geometry"]}
    pads = {key: row for key, row in geometry.items() if row["kind"] == "pad"}
    surfaces = {row["id"]: row for row in physical.get("surfaces", [])}
    artifact_count, artifact_bytes = 0, 0
    for row in model["imports"]:
        _fields(row, {"id", "format", "format_version", "parser_profile", "source_files", "report", "bindings", "source_refs"}, "pcb.imports")
        if row["format"] not in ("kicad_board", "kicad_footprint", "gerber_x2", "xnc", "gerber_job", "vendor_antenna"):
            fail("지원하지 않는 PCB 수입 원문 종류입니다.", "pcb.imports.format", "E_UNSUPPORTED")
        for key in ("format_version", "parser_profile"):
            _text(row[key], "pcb.imports." + key)
        _strings(row["source_refs"], "pcb.imports.source_refs")
        if type(row["source_files"]) is not list or not 1 <= len(row["source_files"]) <= 40:
            fail("수입 원문 파일은 1~40개여야 합니다.", "pcb.imports.source_files", "E_RESOURCE")
        for reference in [*row["source_files"], row["report"]]:
            _artifact(reference, "pcb.imports.artifact")
            artifact_count += 1
            artifact_bytes += reference["bytes"]
        if type(row["bindings"]) is not list or len(row["bindings"]) > 256:
            fail("원본 대응은 최대 256개입니다.", "pcb.imports.bindings", "E_RESOURCE")
        for binding in row["bindings"]:
            _fields(binding, {"source_object_id", "collection", "id"}, "pcb.imports.bindings")
            _text(binding["source_object_id"], "pcb.imports.bindings.source_object_id")
            if binding["collection"] not in PATCH_COLLECTIONS | {"board"}:
                fail("수입 객체 대응 collection이 유효하지 않습니다.", "pcb.imports.bindings.collection")
            _uuid(binding["id"], "pcb.imports.bindings.id")
    if artifact_count > 41 or artifact_bytes > 16 * 1024 * 1024:
        fail("PCB 수입 원문 전체 파일/바이트 상한을 초과했습니다.", "pcb.imports", "E_RESOURCE")
    for key, rows in all_rows.items():
        if key == "imports":
            continue
        for row in rows:
            field = "pcb." + key + "." + row["id"]
            _origin(row, indexes["imports"], field, "board.cutouts" if key == "cutouts" else "pcb." + key)
            common = {"id", "name", "source_refs", "origin"}
            if key in ("cutouts", "holes", "keepouts"):
                _reference(row.get("frame_id"), frames, field + ".frame_id")
                kinds = {"circle", "capsule", "polygon"} if key == "cutouts" else {"circle", "capsule"} if key == "holes" else None
                validate_shape(document, row.get("shape"), field + ".shape", kinds=kinds)
            if key == "cutouts":
                _fields(row, common | {"frame_id", "shape", "surface_cut_ids"}, field)
                _ids(row["surface_cut_ids"], surfaces, field + ".surface_cut_ids")
                if row["shape"]["kind"] == "polygon" and row["shape"]["holes"]:
                    fail("절삭 외곽에는 내부 재료 섬을 넣을 수 없습니다.", field + ".shape")
            elif key == "holes":
                _fields(row, common | {"frame_id", "shape", "span", "plating", "tool_diameter", "surface_cut_ids"}, field)
                _fields(row["span"], {"kind"}, field + ".span")
                if row["span"]["kind"] != "through_base_stackup":
                    fail("현재 기계 홀은 기본 적층 관통만 지원합니다.", field + ".span", "E_UNSUPPORTED")
                plating = row["plating"]
                _fields(plating, {"state", "thickness", "material_ref", "net_id", "pad_ids"}, field + ".plating")
                if plating["state"] not in ("unplated", "plated", "unknown"):
                    fail("도금 상태가 유효하지 않습니다.", field + ".plating.state")
                thickness = _number(document, plating["thickness"], "length", field + ".plating.thickness", positive=True)
                _reference(plating["material_ref"], materials, field + ".material_ref", optional=True)
                _reference(plating["net_id"], nets, field + ".net_id", optional=True)
                _ids(plating["pad_ids"], pads, field + ".pad_ids", maximum=8)
                if plating["state"] != "plated" and (thickness is not None or plating["material_ref"] is not None or plating["net_id"] is not None or plating["pad_ids"]):
                    fail("비도금/도금 미정 홀에는 도금 또는 전기 접속을 추정할 수 없습니다.", field + ".plating")
                if any(pads[identity]["net_id"] != plating["net_id"] for identity in plating["pad_ids"]):
                    fail("도금 홀과 연결 패드의 net이 다릅니다.", field + ".plating.pad_ids", "E_CONFLICT")
                _number(document, row["tool_diameter"], "length", field + ".tool_diameter", positive=True)
                _ids(row["surface_cut_ids"], surfaces, field + ".surface_cut_ids")
            elif key == "artwork_layers":
                _fields(row, common | {"role", "side", "use_state", "physical_surface_id"}, field)
                if row["role"] not in ("solder_mask", "solder_paste") or row["side"] not in ("top", "bottom") or row["use_state"] not in ("used", "not_used", "unknown"):
                    fail("제조 이미지의 역할/면/사용 상태가 유효하지 않습니다.", field)
                _reference(row["physical_surface_id"], surfaces, field + ".physical_surface_id", optional=True)
            elif key == "apertures":
                _fields(row, common | {"artwork_layer_id", "definition"}, field)
                _reference(row["artwork_layer_id"], indexes["artwork_layers"], field + ".artwork_layer_id")
                if indexes["artwork_layers"][row["artwork_layer_id"]]["use_state"] != "used":
                    fail("활성 개구에는 명시적으로 사용하는 제조 이미지 층이 필요합니다.", field + ".artwork_layer_id")
                definition = row["definition"]
                mode = definition.get("mode") if type(definition) is dict else None
                if mode == "explicit_shape":
                    _fields(definition, {"mode", "shape"}, field + ".definition")
                    validate_shape(document, definition["shape"], field + ".definition.shape")
                elif mode == "pad_margin":
                    _fields(definition, {"mode", "pad_id", "margin", "size_ratio"}, field + ".definition")
                    _reference(definition["pad_id"], pads, field + ".definition.pad_id")
                    _number(document, definition["margin"], "length", field + ".definition.margin")
                    _number(document, definition["size_ratio"], "dimensionless", field + ".definition.size_ratio")
                else:
                    fail("개구의 명시 형상/패드 여유값 모드를 하나만 선택하십시오.", field + ".definition")
            elif key == "keepouts":
                optional = {"all_conductor_layers"} if "all_conductor_layers" in row else set()
                _fields(row, common | {"frame_id", "shape", "layer_ids", "prohibit"} | optional, field)
                _ids(row["layer_ids"], layers, field + ".layer_ids")
                if type(row.get("all_conductor_layers", False)) is not bool:
                    fail("모든 도체층의 적용 여부를 명시하십시오.", field + ".all_conductor_layers")
                _fields(row["prohibit"], {"tracks", "vias", "pads", "copper_pours", "footprints"}, field + ".prohibit")
                if any(type(flag) is not bool for flag in row["prohibit"].values()) or not any(row["prohibit"].values()):
                    fail("금지할 객체 종류를 하나 이상 명시하십시오.", field + ".prohibit")
                if (not row.get("all_conductor_layers") and not row["layer_ids"]
                        and any(flag for name, flag in row["prohibit"].items() if name != "footprints")):
                    fail("도체 금지 규칙에는 명시 도체층이 필요합니다.", field + ".layer_ids")
            elif key == "footprints":
                _fields(row, common | {"reference", "value", "library_id", "placement", "members", "pins", "edit_state", "placement_envelope"}, field)
                for name in ("reference", "value", "library_id"):
                    if row[name] is not None:
                        _text(row[name], field + "." + name, limit=256)
                if row["edit_state"] not in ("original", "locally_modified", "custom") or (row["origin"] is None and row["edit_state"] != "custom"):
                    fail("풋프린트 출처와 수정 상태가 다릅니다.", field + ".edit_state")
                _fields(row["placement"], {"origin", "rotation", "side"}, field + ".placement")
                placement = row["placement"]
                _vector2(document, placement["origin"], field + ".placement.origin")
                _number(document, placement["rotation"], "angle", field + ".placement.rotation")
                if any("parameter_id" in item for item in [*placement["origin"], placement["rotation"]]) or placement["side"] not in (None, "top", "bottom"):
                    fail("배치 기준은 명시 리터럴 수량과 상/하면 또는 미정이어야 합니다.", field + ".placement")
                if row["placement_envelope"] is not None:
                    validate_shape(document, row["placement_envelope"], field + ".placement_envelope")
    roles = [(row["role"], row["side"]) for row in model["artwork_layers"]]
    if len(set(roles)) != len(roles):
        fail("같은 역할/면의 제조 이미지 층이 중복됩니다.", "pcb.artwork_layers", "E_CONFLICT")
    owned = {}
    members_index = {"geometry": geometry, **{key: indexes[key] for key in ("holes", "apertures", "keepouts")}}
    for row in model["footprints"]:
        field = "pcb.footprints." + row["id"]
        if type(row["members"]) is not list or len(row["members"]) > 64 or type(row["pins"]) is not list or len(row["pins"]) > 64:
            fail("풋프린트 멤버/핀은 각각 최대 64개입니다.", field, "E_RESOURCE")
        member_ids = set()
        for member in row["members"]:
            _fields(member, {"collection", "id"}, field + ".members")
            if member["collection"] not in members_index:
                fail("지원하지 않는 풋프린트 멤버 종류입니다.", field + ".members")
            _reference(member["id"], members_index[member["collection"]], field + ".members.id")
            key = (member["collection"], member["id"])
            if key in owned:
                fail("객체는 최대 한 풋프린트에 한 번만 속할 수 있습니다.", field + ".members", "E_CONFLICT")
            owned[key] = row["id"]
            member_ids.add(member["id"])
        pin_numbers = set()
        for pin in row["pins"]:
            _fields(pin, {"number", "pad_ids", "hole_id"}, field + ".pins")
            _text(pin["number"], field + ".pins.number", limit=128)
            if pin["number"] in pin_numbers:
                fail("같은 풋프린트의 핀 번호가 중복됩니다.", field + ".pins.number", "E_CONFLICT")
            pin_numbers.add(pin["number"])
            _ids(pin["pad_ids"], pads, field + ".pins.pad_ids", maximum=8)
            if not pin["pad_ids"] or any(identity not in member_ids for identity in pin["pad_ids"]):
                fail("핀은 소유한 실제 패드에 연결되어야 합니다.", field + ".pins.pad_ids")
            if len({pads[identity]["net_id"] for identity in pin["pad_ids"]}) > 1:
                fail("같은 핀의 패드 net이 다릅니다.", field + ".pins.pad_ids", "E_CONFLICT")
            if pin["hole_id"] is not None:
                holes = {**indexes["holes"], **{key: value for key, value in geometry.items() if value["kind"] == "via"}}
                _reference(pin["hole_id"], holes, field + ".pins.hole_id")
                if pin["hole_id"] not in member_ids:
                    fail("핀의 홀도 같은 풋프린트가 소유해야 합니다.", field + ".pins.hole_id")
                hole = holes[pin["hole_id"]]
                connected = hole.get("plating", hole)
                if connected.get("net_id") != pads[pin["pad_ids"][0]]["net_id"]:
                    fail("핀의 홀/패드 net이 다릅니다.", field + ".pins.hole_id", "E_CONFLICT")
    for row in model["apertures"]:
        if row["definition"]["mode"] == "pad_margin":
            owner = owned.get(("apertures", row["id"]))
            if owner is not None and owner != owned.get(("geometry", row["definition"]["pad_id"])):
                fail("소유 개구는 같은 풋프린트 패드만 참조할 수 있습니다.", "pcb.apertures.definition.pad_id", "E_CONFLICT")


def make_patch(before, after, operation, reason):
    """! @brief 전체 컨테이너 복제 대신 변경 record와 absent 상태만 고정한다."""
    changes = []
    for collection in sorted(PATCH_COLLECTIONS):
        old = {row["id"]: row for row in records(before, collection)}
        new = {row["id"]: row for row in records(after, collection)}
        for identity in sorted(old.keys() | new.keys()):
            if old.get(identity) != new.get(identity):
                changes.append({"collection": collection, "id": identity,
                    "expected": {"present": identity in old, "value": deepcopy(old.get(identity))},
                    "replacement": {"present": identity in new, "value": deepcopy(new.get(identity))}})
    result = {"schema": "rfad.pcb-command/0.1", "operation": operation, "reason": reason,
              "container_presence": {"expected": presence(before), "replacement": presence(after)}, "changes": changes}
    result["provenance"] = {"patch_hash": canonical_hash(result)}
    return result


def inverse_patch(payload):
    """! @brief 원본 record와 컨테이너 존재 상태를 정확히 역전한다."""
    result = deepcopy(payload)
    result["operation"] = "history.restore"
    for item in [result["container_presence"], *result["changes"]]:
        item["expected"], item["replacement"] = item["replacement"], item["expected"]
    result["provenance"] = {"patch_hash": canonical_hash({key: value for key, value in result.items() if key != "provenance"})}
    return result


def apply_pcb_command(document, payload):
    """! @brief 도메인 직접 호출도 실패 시 부분 record 변경을 남기지 않는다."""
    candidate = deepcopy(document)
    result = _apply_pcb_command(candidate, payload)
    document.clear()
    document.update(candidate)
    return result


def _apply_pcb_command(document, payload):
    """! @brief 모든 expected를 먼저 대조하고 원자 record 교체와 정확한 역명령을 만든다."""
    _fields(payload, {"schema", "operation", "reason", "container_presence", "changes", "provenance"}, "pcb.command")
    if payload["schema"] != "rfad.pcb-command/0.1":
        fail("지원하지 않는 PCB 명령 버전입니다.", "pcb.command.schema", "E_VERSION")
    _text(payload["operation"], "pcb.command.operation", limit=128)
    if payload["operation"] not in {"history.restore", "import.apply", "footprint.place", "footprint.member_edit", "footprint.detach",
            *(section + suffix for section in ("cutout", "hole", "footprint", "artwork_layer", "aperture", "keepout") for suffix in (".set", ".remove"))}:
        fail("미지원 PCB patch 작업입니다.", "pcb.command.operation", "E_UNSUPPORTED")
    _text(payload["reason"], "pcb.command.reason", limit=512)
    _fields(payload["provenance"], {"patch_hash"}, "pcb.command.provenance")
    if payload["provenance"]["patch_hash"] != canonical_hash({key: value for key, value in payload.items() if key != "provenance"}):
        fail("PCB 명령의 변경 근거 hash가 다릅니다.", "pcb.command.provenance", "E_HASH")
    if len(canonical_bytes(payload)) > MAX_PATCH_BYTES or type(payload["changes"]) is not list or not 1 <= len(payload["changes"]) <= 256:
        fail("PCB 변경 record/명령 바이트 상한을 초과했습니다.", "pcb.command", "E_RESOURCE")
    containers = payload["container_presence"]
    _fields(containers, {"expected", "replacement"}, "pcb.command.container_presence")
    for side in ("expected", "replacement"):
        _fields(containers[side], {"pcb", "board_cutouts"}, "pcb.command.container_presence." + side)
        if any(type(value) is not bool for value in containers[side].values()):
            fail("컨테이너 존재 상태는 bool이어야 합니다.", "pcb.command.container_presence")
    if presence(document) != containers["expected"]:
        fail("검토한 PCB 컨테이너의 존재 상태가 다릅니다.", "pcb.command.container_presence", "E_CONFLICT")
    seen = set()
    for change in payload["changes"]:
        _fields(change, {"collection", "id", "expected", "replacement"}, "pcb.command.changes")
        collection, identity = change["collection"], _uuid(change["id"], "pcb.command.id")
        if collection not in PATCH_COLLECTIONS or (collection, identity) in seen:
            fail("PCB 변경 대상이 미지원이거나 중복입니다.", "pcb.command.changes", "E_CONFLICT")
        seen.add((collection, identity))
        old = next((row for row in records(document, collection) if row["id"] == identity), None)
        for side in ("expected", "replacement"):
            item = change[side]
            _fields(item, {"present", "value"}, "pcb.command." + side)
            if type(item["present"]) is not bool or (item["present"] and (type(item["value"]) is not dict or item["value"].get("id") != identity)) or (not item["present"] and item["value"] is not None):
                fail("record 존재 여부/ID가 실제 교체값과 다릅니다.", "pcb.command." + side)
        if change["expected"] != {"present": old is not None, "value": old} or change["expected"] == change["replacement"]:
            fail("검토한 PCB 원본 record가 다르거나 변경이 없습니다.", "pcb.command.expected", "E_CONFLICT")
        if change["replacement"]["present"] and ((collection.startswith("pcb.") and not containers["replacement"]["pcb"]) or
                (collection == "board.cutouts" and not containers["replacement"]["board_cutouts"])):
            fail("존재하지 않는 컨테이너에 record를 게시할 수 없습니다.", "pcb.command.container_presence", "E_CONFLICT")
    if containers["replacement"]["pcb"]:
        document.setdefault("pcb", empty_pcb())
    if containers["replacement"]["board_cutouts"]:
        if document["board"] is None:
            fail("절삭 컨테이너에는 기판이 필요합니다.", "board")
        document["board"].setdefault("cutouts", [])
    for change in payload["changes"]:
        collection, identity = change["collection"], change["id"]
        target = records(document, collection)
        target[:] = [row for row in target if row["id"] != identity]
        if change["replacement"]["present"]:
            target.append(deepcopy(change["replacement"]["value"]))
        target.sort(key=lambda row: row["id"])
    if not containers["replacement"]["pcb"]:
        if any(document.get("pcb", empty_pcb())[key] for key in COLLECTIONS.values()):
            fail("원본이 남은 PCB 컨테이너를 제거할 수 없습니다.", "pcb.command.container_presence")
        document.pop("pcb", None)
    if not containers["replacement"]["board_cutouts"]:
        if (document.get("board") or {}).get("cutouts"):
            fail("절삭 원본이 남은 컨테이너를 제거할 수 없습니다.", "pcb.command.container_presence")
        if document["board"] is not None:
            document["board"].pop("cutouts", None)
    validate_pcb(document)
    return list(dict.fromkeys(change["id"] for change in payload["changes"])), ["revision", "geometry", "physics", "network", "metrics", "assessment", "exports", "design_checks"], {"type": COMMAND, "payload": inverse_patch(payload)}


def _physical_value(document, value):
    """! @brief 표시 단위/이름/출처 변경과 실제 local 형상/참조 변경을 구분한다."""
    if type(value) is dict:
        if set(value) == {"parameter_id"}:
            return _physical_value(document, document["parameters"][value["parameter_id"]]["quantity"])
        if "value_si" in value and "dimension" in value:
            return {"value_si": value["value_si"], "dimension": value["dimension"]}
        return {key: _physical_value(document, item) for key, item in value.items()
                if key not in ("name", "source_refs", "source_ref", "origin", "edit_state")}
    if type(value) is list:
        return [_physical_value(document, item) for item in value]
    return value


def finalize_pcb_edits(before, after, operation):
    """! @brief 하위 일반 명령의 실제 변화만 수정 상태에 반영하고 역명령에 넣을 metadata를 반환한다."""
    changes = []
    old_owners = {row["id"]: row for row in before.get("pcb", empty_pcb())["footprints"]}
    for row in after.get("pcb", empty_pcb())["footprints"]:
        old = old_owners.get(row["id"])
        if old is None or operation in (COMMAND, "footprint.place"):
            continue
        changed = False
        for member in old["members"]:
            collection = member["collection"] if member["collection"] == "geometry" else "pcb." + member["collection"]
            original = next((item for item in records(before, collection) if item["id"] == member["id"]), None)
            current = next((item for item in records(after, collection) if item["id"] == member["id"]), None)
            if current is None:
                fail("소유한 멤버 삭제는 풋프린트의 명시 편집으로 처리하십시오.", "pcb.footprints.members", "E_CONFLICT")
            changed = changed or _physical_value(before, original) != _physical_value(after, current)
        if changed and row["edit_state"] == "original":
            previous = deepcopy(row)
            row["edit_state"] = "locally_modified"
            changes.append({"id": row["id"], "expected": previous, "replacement": deepcopy(row)})
    return changes


def apply_metadata_replay(document, changes):
    """! @brief 이력의 보존된 풋프린트 상태만 복원하며 local 수정 여부를 다시 추정하지 않는다."""
    if type(changes) is not list or len(changes) > 32:
        fail("풋프린트 이력 metadata 상한을 초과했습니다.", "pcb.replay", "E_RESOURCE")
    index = {row["id"]: row for row in document.get("pcb", empty_pcb())["footprints"]}
    used = set()
    for change in changes:
        _fields(change, {"id", "expected", "replacement"}, "pcb.replay")
        if type(change["expected"]) is not dict or type(change["replacement"]) is not dict:
            fail("풋프린트 이력에는 전체 record 원본이 필요합니다.", "pcb.replay")
        if change["id"] in used or index.get(change["id"]) != change["expected"]:
            fail("풋프린트 이력의 expected 원본이 다릅니다.", "pcb.replay", "E_CONFLICT")
        used.add(change["id"])
        if {key: value for key, value in change["expected"].items() if key != "edit_state"} != {key: value for key, value in change["replacement"].items() if key != "edit_state"}:
            fail("자동 수정 상태 이력은 다른 원본 필드를 바꿀 수 없습니다.", "pcb.replay", "E_CONFLICT")
    for change in changes:
        index[change["id"]].update(deepcopy(change["replacement"]))
    return [{"id": change["id"], "expected": deepcopy(change["replacement"]), "replacement": deepcopy(change["expected"])} for change in changes]
