"""! @brief PCB 기계/제조/풋프린트의 명시 입력, 검토와 한 명령 적용을 연결한다."""

from copy import deepcopy
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.network_forms import input_quantity
from rfad.application.pcb_exchange_projection import aperture_projection, feature_scene, shape_projection
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.design import resolve_scalar, _text
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names
from rfad.domain.pcb_features import (COMMAND, COLLECTIONS, LIMITS, PROJECT_SCHEMA, apply_pcb_command,
    empty_pcb, fail, finalize_pcb_edits, make_patch, owner_map, records, validate_pcb)
from rfad.domain.units import Quantity, units_for_dimension

PROFILE = "rfad.pcb-features-editor/0.1"
READS = {"pcb.features.get", "pcb.features.preview", "pcb.features.receipt"}
MUTATION = "pcb.features.apply"
SECTIONS = {"cutout": "기판 내부 절삭", "hole": "관통 홀과 슬롯", "footprint": "풋프린트",
            "artwork_layer": "제조 이미지 층", "aperture": "마스크 및 페이스트 개구", "keepout": "금지 영역"}
OPERATIONS = {section + suffix for section in SECTIONS for suffix in (".set", ".remove")} | {"footprint.place", "footprint.member_edit", "footprint.detach"}
MAX_DTO_BYTES = 384 * 1024


def bounded(value):
    """! @brief 원문과 표시를 잘라서 성공으로 응답하지 않는다."""
    if len(canonical_bytes(value)) > MAX_DTO_BYTES:
        fail("PCB 편집 응답의 384 KiB 상한을 초과했습니다.", "response", "E_RESOURCE")
    return value


def collection(section):
    """! @brief 공개 종류를 고정된 원본 collection에 연결한다."""
    return "board.cutouts" if section == "cutout" else "pcb." + COLLECTIONS[section]


def _missing(dimension="length", unit="mm"):
    """! @brief 신규 형상 치수를 임의 숫자로 채우지 않는다."""
    return Quantity.missing(dimension, unit).to_dict()


def _shape(kind):
    """! @brief native 폼이 편집할 모든 필드를 명시적 미정으로 만든다."""
    point = lambda: [_missing(), _missing()]
    if kind == "polygon":
        return {"kind": kind, "outer": [point(), point(), point()], "holes": []}
    result = {"kind": kind, "center": point()}
    if kind == "circle":
        result["diameter"] = _missing()
    elif kind == "rectangle":
        result.update(size=point(), rotation=_missing("angle", "deg"))
    elif kind == "capsule":
        result.update(finished_length=_missing(), finished_width=_missing(), rotation=_missing("angle", "deg"))
    else:
        fail("지원하지 않는 PCB 형상 종류입니다.", "shape_kind", "E_UNSUPPORTED")
    return result


def new_record(document, section, shape_kind="circle"):
    """! @brief 현재 개정에 묶인 새 ID와 중복 없는 이름을 서비스가 제안한다."""
    target = records(document, collection(section))
    names = {row["name"] for row in target}
    index = 1
    while f"{SECTIONS[section]} {index:02d}" in names:
        index += 1
    result = {"id": str(uuid5(UUID(document["project_id"]), f"pcb:{document['revision_id']}:{section}:{shape_kind}")),
              "name": f"{SECTIONS[section]} {index:02d}", "source_refs": [], "origin": None}
    if section in ("cutout", "hole", "keepout"):
        result.update(frame_id=document["frames"]["board"]["id"], shape=_shape(shape_kind))
    if section == "cutout":
        result["surface_cut_ids"] = []
    elif section == "hole":
        result.update(span={"kind": "through_base_stackup"}, tool_diameter=_missing(), surface_cut_ids=[],
                      plating={"state": "unknown", "thickness": _missing(), "material_ref": None, "net_id": None, "pad_ids": []})
    elif section == "footprint":
        result.update(reference=None, value=None, library_id=None, members=[], pins=[], edit_state="custom", placement_envelope=None,
                      placement={"origin": [_missing(), _missing()], "rotation": _missing("angle", "deg"), "side": None})
    elif section == "artwork_layer":
        result.update(role="solder_mask", side="top", use_state="unknown", physical_surface_id=None)
    elif section == "aperture":
        available = [row for row in document.get("pcb", empty_pcb())["artwork_layers"] if row["use_state"] == "used"]
        result.update(artwork_layer_id=available[0]["id"] if len(available) == 1 else None,
                      definition={"mode": "explicit_shape", "shape": _shape(shape_kind)})
    elif section == "keepout":
        result.update(layer_ids=[], prohibit={key: False for key in ("tracks", "vias", "pads", "copper_pours", "footprints")})
    return result


def _scalar_input(document, value, dimension, field):
    """! @brief 실제 변경한 문자열만 환산하고 참조/수량 원본은 그대로 보존한다."""
    if type(value) is dict and set(value) == {"parameter_id"}:
        resolve_scalar(document, value, dimension, field)
        return deepcopy(value)
    return input_quantity(value, dimension, field)


def normalize_record(document, record):
    """! @brief 허용한 Scalar 위치만 변환하고 나머지 필드는 도메인 exact 검증에 맡긴다."""
    result = deepcopy(record)
    def shape(value):
        """! @brief 해석형 종류별로 닫힌 수량 위치만 해석한다."""
        if type(value) is not dict:
            fail("형상 원문이 필요합니다.", "record.shape")
        if value.get("kind") == "polygon":
            for loop in [value.get("outer", []), *value.get("holes", [])]:
                for point in loop:
                    for axis, item in enumerate(point):
                        point[axis] = _scalar_input(document, item, "length", "shape.point")
        else:
            for key in ("center", "size"):
                if key in value:
                    value[key] = [_scalar_input(document, item, "length", "shape." + key) for item in value[key]]
            for key in ("diameter", "finished_length", "finished_width", "rotation"):
                if key in value:
                    value[key] = _scalar_input(document, value[key], "angle" if key == "rotation" else "length", "shape." + key)
    if type(result) is not dict:
        fail("PCB record 원문이 필요합니다.", "record")
    if "shape" in result:
        shape(result["shape"])
    if result.get("placement_envelope") is not None:
        shape(result["placement_envelope"])
    if "plating" in result:
        result["plating"]["thickness"] = _scalar_input(document, result["plating"]["thickness"], "length", "plating.thickness")
        result["tool_diameter"] = _scalar_input(document, result["tool_diameter"], "length", "tool_diameter")
    if "placement" in result:
        result["placement"]["origin"] = [_scalar_input(document, item, "length", "placement.origin") for item in result["placement"]["origin"]]
        result["placement"]["rotation"] = _scalar_input(document, result["placement"]["rotation"], "angle", "placement.rotation")
    if "definition" in result:
        definition = result["definition"]
        if definition.get("mode") == "explicit_shape":
            shape(definition["shape"])
        elif definition.get("mode") == "pad_margin":
            for key, dimension in (("margin", "length"), ("size_ratio", "dimensionless")):
                definition[key] = _scalar_input(document, definition[key], dimension, "definition." + key)
    return result


def _choices(rows, *, optional=False):
    """! @brief UUID 대신 원본 이름을 표시하되 선택 값은 안정 ID를 유지한다."""
    return ([{"value": None, "label": "미정 (연결 없음)"}] if optional else []) + [{"value": row["id"], "label": row.get("label", row.get("name", "원본 객체"))} for row in rows]


def _quantity_display(document, value):
    """! @brief 단위 전환용 Quantity와 원본 Scalar를 분리한다."""
    source = document["parameters"][value["parameter_id"]]["quantity"] if "parameter_id" in value else value
    quantity = Quantity(**source)
    from rfad.application.editor import _display_quantity
    text, unit, note = _display_quantity(quantity)
    return {"original": deepcopy(value), "quantity": deepcopy(source), "dimension": quantity.dimension.value,
            "text": text, "display_note": note, "unit": unit, "units": list(units_for_dimension(quantity.dimension.value))}


def form_fields(document, record, section, context):
    """! @brief raw JSON 편집 없이 허용 필드별 native 폼 descriptor를 만든다."""
    output = []
    def field(path, label, kind="text", **extra):
        """! @brief 원본 내 실제 존재하는 경로만 공개한다."""
        output.append({"path": path, "label": label, "kind": kind, **extra})
    def numeric(path, value, label):
        """! @brief 참조는 해제하지 않고 현재 Quantity와 함께 보여 준다."""
        field(path, label, "scalar", **_quantity_display(document, value),
              parameters=[row for row in context["parameters"] if row["dimension"] == _quantity_display(document, value)["dimension"]])
    def shape(value, path):
        """! @brief 좌표 표와 실제 scalar 필드를 나누어 생성한다."""
        if value["kind"] == "polygon":
            field(path + ["outer"], "외곽 좌표", "coordinates",
                  display_rows=[{axis: _quantity_display(document, point[i]) for i, axis in enumerate(("x", "y"))} for point in value["outer"]], units=["mm", "um", "m"])
            if section != "cutout":
                field(path + ["holes"], "내부 구멍 목록", "coordinate_loops",
                      display_loops=[[{axis: _quantity_display(document, point[i]) for i, axis in enumerate(("x", "y"))} for point in loop] for loop in value["holes"]],
                      units=["mm", "um", "m"], max_loops=8, max_total_points=64)
        else:
            for key in ("center", "size"):
                if key in value:
                    for axis in range(2):
                        numeric(path + [key, axis], value[key][axis], ("중심 " if key == "center" else "크기 ") + ("X" if axis == 0 else "Y"))
            for key, label in (("diameter", "완성 지름"), ("finished_length", "슬롯 완성 전체 길이"), ("finished_width", "슬롯 완성 폭"), ("rotation", "회전각")):
                if key in value:
                    numeric(path + [key], value[key], label)
    field(["name"], "객체 이름")
    if "shape" in record:
        shape(record["shape"], ["shape"])
    if "frame_id" in record:
        field(["frame_id"], "좌표계", "reference", choices=_choices(context["frames"]))
    if "surface_cut_ids" in record:
        field(["surface_cut_ids"], "실제로 함께 절삭할 표면층", "reference_list", choices=_choices(context["surfaces"]))
    if section == "hole":
        field(["plating", "state"], "도금 상태", "choice", choices=[{"value": value, "label": label} for value, label in (("unknown", "미정"), ("unplated", "비도금"), ("plated", "도금"))])
        numeric(["plating", "thickness"], record["plating"]["thickness"], "도금 두께")
        numeric(["tool_diameter"], record["tool_diameter"], "실제 공구 지름 (완성 지름과 별도)")
        for key, label, source in (("material_ref", "도금 재료", "materials"), ("net_id", "도금 net", "nets")):
            field(["plating", key], label, "reference", choices=_choices(context[source], optional=True))
        field(["plating", "pad_ids"], "연결 패드", "reference_list", choices=_choices(context["pads"]))
    elif section == "artwork_layer":
        for key, choices in (("role", [("solder_mask", "솔더 마스크"), ("solder_paste", "솔더 페이스트")]), ("side", [("top", "상면"), ("bottom", "하면")]), ("use_state", [("unknown", "미정"), ("used", "사용"), ("not_used", "사용 안 함")])):
            field([key], {"role": "종류", "side": "면", "use_state": "사용 상태"}[key], "choice", choices=[{"value": value, "label": label} for value, label in choices])
        field(["physical_surface_id"], "별도 실제 표면층과 대응", "reference", choices=_choices(context["surfaces"], optional=True))
    elif section == "aperture":
        field(["artwork_layer_id"], "제조 이미지 층", "reference", choices=_choices(context["artwork_layers"], optional=True))
        if record["definition"]["mode"] == "explicit_shape":
            shape(record["definition"]["shape"], ["definition", "shape"])
        else:
            field(["definition", "pad_id"], "참조 패드", "reference", choices=_choices(context["pads"]))
            for key, label in (("margin", "둘레 여유값"), ("size_ratio", "크기 부가 비율 (0은 원래 크기)")):
                numeric(["definition", key], record["definition"][key], label)
    elif section == "keepout":
        field(["all_conductor_layers"], "모든 도체층에 적용", "boolean")
        field(["layer_ids"], "개별 도체층 (모든 도체층을 선택하면 보존)", "reference_list", choices=_choices(context["layers"]))
        for key, label in (("tracks", "선과 원호"), ("vias", "비아와 도금 홀"), ("pads", "패드"), ("copper_pours", "도체 영역"), ("footprints", "풋프린트")):
            field(["prohibit", key], label + " 금지", "boolean")
    elif section == "footprint":
        for key, label in (("reference", "참조 번호"), ("value", "표시값"), ("library_id", "원본 라이브러리 식별")):
            field([key], label, nullable=True)
        for axis in range(2):
            numeric(["placement", "origin", axis], record["placement"]["origin"][axis], "배치 기준 " + ("X" if axis == 0 else "Y"))
        numeric(["placement", "rotation"], record["placement"]["rotation"], "배치 회전")
        field(["placement", "side"], "배치 면", "choice", choices=[{"value": None, "label": "미정"}, {"value": "top", "label": "상면"}, {"value": "bottom", "label": "하면"}])
        field(["members"], "소유 객체", "members", choices=context["member_choices"])
        field(["pins"], "핀, 패드 및 홀 대응", "pins", choices=_choices(context["pads"]), hole_choices=_choices(context["holes"], optional=True))
        if record["placement_envelope"] is not None:
            shape(record["placement_envelope"], ["placement_envelope"])
    field(["source_refs"], "출처 원문", "source_refs")
    return output


def get(document, data):
    """! @brief 현재 원문과 미정 상태 및 실제 참조 선택 목록을 비변경 조회한다."""
    from rfad.application.canvas import build_canvas_dto
    section, identity = data["section"], data["record_id"]
    model, owners = document.get("pcb", empty_pcb()), owner_map(document)
    rows = []
    for key in SECTIONS:
        for row in records(document, collection(key)):
            rows.append({"collection": collection(key), "section": key, "id": row["id"], "label": row["name"], "name": row["name"],
                         "owner_footprint_id": owners.get((COLLECTIONS.get(key, "cutouts"), row["id"])), "record": deepcopy(row),
                         "missing_fields": missing_fields(row)})
    labels = display_names(document)
    result = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
              "source_revision_id": document["revision_id"], "rows": rows, "limits": {**LIMITS, "max_dto_bytes": MAX_DTO_BYTES},
              "layers": [deepcopy(row) for row in document["stackup"] if row["role"] == "conductor"],
              "nets": deepcopy(document["nets"]), "materials": deepcopy(document["materials"]),
              "surfaces": deepcopy(document["extensions"].get("rfad.physical_setup", {}).get("surfaces", [])),
              "frames": [{"id": row["id"], "label": {"world": "전체 좌표계", "board": "기판 좌표계"}[key]} for key, row in document["frames"].items()],
              "parameters": [{"id": row["id"], "label": row["name"], "dimension": row["quantity"]["dimension"], "derived": "expression" in row} for row in document["parameters"].values()],
              "pads": [{"id": row["id"], "label": labels[row["id"]]} for row in document["geometry"] if row["kind"] == "pad"],
              "holes": [{"id": row["id"], "label": row["name"]} for row in model["holes"]] + [{"id": row["id"], "label": labels[row["id"]]} for row in document["geometry"] if row["kind"] == "via"],
              "artwork_layers": deepcopy(model["artwork_layers"]), "form": None, "operation_inputs": {},
              "scene": build_canvas_dto(document),
              "preflight": {"manufacturing_verified": False, "measurement_verified": False,
                            "solver_mechanical_supported": True, "solver_mechanical_scope": "declared_unplated_and_internal_cutouts"}}
    result["member_choices"] = [{"value": {"collection": "geometry", "id": row["id"]}, "label": labels[row["id"]]} for row in document["geometry"]]
    result["member_choices"] += [{"value": {"collection": key, "id": row["id"]}, "label": row["name"]} for key in ("holes", "apertures", "keepouts") for row in model[key]]
    result["operations"] = [{"id": op, "label": SECTIONS[op.split(".")[0]] + " " + {"set": "저장", "remove": "삭제", "place": "배치", "member_edit": "멤버 편집", "detach": "그룹 해제"}[op.split(".")[1]],
                            "allowed": document["board"] is not None, "reason": "" if document["board"] is not None else "기판이 필요합니다."} for op in sorted(OPERATIONS)]
    if section != "overview":
        row = next((row for row in records(document, collection(section)) if row["id"] == identity), None)
        if identity is not None and row is None:
            fail("선택한 PCB 원본이 없습니다.", "record_id", "E_CONFLICT")
        if row is None:
            row = new_record(document, section, data.get("shape_kind", "circle"))
        original = deepcopy(row)
        row = deepcopy(row)
        if section == "keepout":
            row.setdefault("all_conductor_layers", False)
        if section == "aperture" and data.get("definition_mode", row["definition"]["mode"]) != row["definition"]["mode"]:
            row["definition"] = {"mode": "pad_margin", "pad_id": None, "margin": _missing(), "size_ratio": _missing("dimensionless", "1")} if data["definition_mode"] == "pad_margin" else {"mode": "explicit_shape", "shape": _shape(data.get("shape_kind", "circle"))}
        if "shape_kind" in data:
            if "shape" in row and row["shape"]["kind"] != data["shape_kind"]:
                row["shape"] = _shape(data["shape_kind"])
            if section == "aperture" and row["definition"]["mode"] == "explicit_shape" and row["definition"]["shape"]["kind"] != data["shape_kind"]:
                row["definition"]["shape"] = _shape(data["shape_kind"])
        if section == "footprint" and "envelope_kind" in data:
            row["placement_envelope"] = None if data["envelope_kind"] is None else _shape(data["envelope_kind"])
        result["form"] = {"section": section, "record_id": identity, "original_record": original, "record": deepcopy(row), "fields": form_fields(document, row, section, result)}
        result["operation_inputs"][section + ".set"] = {"record": deepcopy(row)}
        result["operation_inputs"][section + ".remove"] = {"id": row["id"]}
        if section == "footprint":
            result["operation_inputs"].update({"footprint.place": {"id": row["id"], "placement": deepcopy(row["placement"])},
                "footprint.detach": {"id": row["id"]},
                "footprint.remove": {"id": row["id"], "remove_members": deepcopy(row["members"])},
                "footprint.member_edit": {"id": row["id"], "members": deepcopy(row["members"]), "pins": deepcopy(row["pins"]),
                                           "placement_envelope": deepcopy(row["placement_envelope"]), "changes": []}})
        if section == "artwork_layer":
            dependencies = [item["id"] for item in model["apertures"] if item["artwork_layer_id"] == row["id"]]
            result["operation_inputs"]["artwork_layer.remove"]["remove_aperture_ids"] = dependencies
            result["operation_inputs"]["artwork_layer.set"]["remove_aperture_ids"] = []
        owner = owners.get((COLLECTIONS.get(section, "cutouts"), row["id"]))
        if owner is not None:
            parent = next(item for item in model["footprints"] if item["id"] == owner)
            result["operation_inputs"]["footprint.member_edit"] = {"id": owner, "members": deepcopy(parent["members"]), "pins": deepcopy(parent["pins"]),
                "placement_envelope": deepcopy(parent["placement_envelope"]), "changes": [{"collection": COLLECTIONS[section], "id": row["id"], "record": deepcopy(row)}]}
    return bounded(result)


def missing_fields(value, path="record"):
    """! @brief 미정/null의 위치를 원문 변경 없이 표시한다."""
    if value is None or (type(value) is dict and "value_si" in value and value["value_si"] is None):
        return [path]
    if type(value) is dict:
        return [name for key, item in value.items() for name in missing_fields(item, path + "." + key)]
    if type(value) is list:
        return [name for index, item in enumerate(value) for name in missing_fields(item, path + f"[{index}]")]
    return []


def record_summary(document, record):
    """! @brief 비교 표에 현재 수량/미정/개수를 표시하고 원문 사본은 별도로 보존한다."""
    if record is None:
        return "없음"
    values = []
    labels = {"center": "중심", "diameter": "완성 지름", "size": "크기", "finished_length": "완성 길이", "finished_width": "완성 폭",
              "rotation": "회전", "thickness": "도금 두께", "tool_diameter": "공구 지름", "origin": "배치 기준", "margin": "여유값", "size_ratio": "부가 비율"}
    def walk(value, name):
        """! @brief 원문 숫자를 GUI가 재환산하지 않도록 표시 문자열을 제공한다."""
        if type(value) is dict and ("value_si" in value or set(value) == {"parameter_id"}):
            displayed = _quantity_display(document, value)
            values.append(name + ": " + ((displayed["text"] + " " + displayed["unit"]) if displayed["text"] else "미정"))
        elif type(value) is dict:
            for key, item in value.items():
                if key not in ("origin", "source_refs", "plating", "definition", "placement") and key not in labels:
                    continue
                if key == "origin" and set(value) != {"origin", "rotation", "side"}:
                    continue
                walk(item, labels.get(key, name))
        elif type(value) is list:
            if len(value) <= 2 and all(type(item) is dict for item in value):
                for axis, item in enumerate(value):
                    walk(item, name + (" X" if axis == 0 else " Y"))
    walk(record.get("shape", record), "값")
    if "members" in record:
        values.append(f"멤버 {len(record['members'])}개, 핀 {len(record['pins'])}개")
    if "use_state" in record:
        values.append({"used": "사용", "not_used": "사용 안 함", "unknown": "사용 여부 미정"}[record["use_state"]])
    if not values:
        values.append("원문 객체와 참조 보존")
    return " / ".join(values)


def _replace(document, section, row):
    """! @brief 최초 신형 필드만 필요할 때 만들며 나머지는 stable ID로 교체한다."""
    if section == "cutout":
        document["board"].setdefault("cutouts", [])
    else:
        document.setdefault("pcb", empty_pcb())
    target = records(document, collection(section))
    target[:] = sorted([item for item in target if item["id"] != row["id"]] + [deepcopy(row)], key=lambda item: item["id"])


def _delete(document, section, identity):
    """! @brief 삭제 대상이 없으면 성공으로 가장하지 않는다."""
    target = records(document, collection(section))
    if not any(row["id"] == identity for row in target):
        fail("삭제할 PCB 원본이 없습니다.", "id", "E_CONFLICT")
    target[:] = [row for row in target if row["id"] != identity]


def _protected(old, row):
    """! @brief 직접 입력은 수입 출처와 최초 수정 상태를 만들어 내거나 덮어쓰지 않는다."""
    if old is None:
        if row.get("origin") is not None or row.get("edit_state", "custom") != "custom":
            fail("새 직접 입력에 수입 출처나 원본 상태를 지정할 수 없습니다.", "record.origin", "E_CONFLICT")
    elif row.get("origin") != old.get("origin") or row.get("edit_state") != old.get("edit_state"):
        fail("수입 출처와 수정 상태는 원본 처리 서비스가 보존합니다.", "record.origin", "E_CONFLICT")


def mutate_candidate(document, operation, values):
    """! @brief 명시한 종속 삭제/멤버 편집을 한 사본에 조립하고 원본은 쓰지 않는다."""
    candidate = deepcopy(document)
    candidate["schema_version"] = PROJECT_SCHEMA
    section, action = operation.split(".")
    if document["board"] is None:
        fail("PCB 편집에는 기판 원본이 필요합니다.", "board", "E_CONFLICT")
    owners = owner_map(document)
    if operation == "footprint.detach":
        _fields(values, {"id"})
        _delete(candidate, "footprint", values["id"])
    elif operation == "footprint.place":
        _fields(values, {"id", "placement"})
        place_footprint(candidate, values)
    elif operation == "footprint.member_edit":
        _fields(values, {"id", "members", "pins", "placement_envelope", "changes"})
        owner = next((row for row in candidate.get("pcb", empty_pcb())["footprints"] if row["id"] == values["id"]), None)
        if owner is None or type(values["changes"]) is not list or len(values["changes"]) > 64:
            fail("실제 소유 풋프린트와 64개 이내 멤버 변경이 필요합니다.", "changes", "E_CONFLICT")
        owner_before = deepcopy(owner)
        physically_changed = False
        allowed = {(item["collection"], item["id"]) for item in owner["members"]} | {(item["collection"], item["id"]) for item in values["members"]}
        seen = set()
        for item in values["changes"]:
            _fields(item, {"collection", "id", "record"})
            key = (item["collection"], item["id"])
            if key not in allowed or key in seen or key[0] not in ("geometry", "holes", "apertures", "keepouts"):
                fail("소유 멤버만 한 번씩 편집할 수 있습니다.", "changes", "E_CONFLICT")
            seen.add(key)
            destination = key[0] if key[0] == "geometry" else "pcb." + key[0]
            target = records(candidate, destination)
            old = next((row for row in target if row["id"] == key[1]), None)
            if item["record"] is not None:
                row = normalize_record(candidate, item["record"]) if key[0] != "geometry" else deepcopy(item["record"])
                if row.get("id") != key[1]:
                    fail("멤버 ID와 교체 원본이 다릅니다.", "changes.record", "E_CONFLICT")
                if key[0] != "geometry":
                    _protected(old, row)
                from rfad.domain.pcb_features import _physical_value
                physically_changed = physically_changed or _physical_value(document, old) != _physical_value(candidate, row)
                target[:] = sorted([entry for entry in target if entry["id"] != key[1]] + [row], key=lambda entry: entry["id"])
            else:
                if old is None:
                    fail("삭제할 멤버가 없습니다.", "changes", "E_CONFLICT")
                target[:] = [entry for entry in target if entry["id"] != key[1]]
                physically_changed = True
        envelope = None if values["placement_envelope"] is None else normalize_record(candidate, {"shape": values["placement_envelope"]})["shape"]
        owner.update(members=deepcopy(values["members"]), pins=deepcopy(values["pins"]), placement_envelope=envelope)
        if owner["edit_state"] == "original" and (physically_changed or any(owner_before[key] != owner[key] for key in ("members", "pins", "placement_envelope"))):
            owner["edit_state"] = "locally_modified"
    elif action == "set":
        _fields(values, {"record", *({"remove_aperture_ids"} if section == "artwork_layer" else set())})
        row = normalize_record(candidate, values["record"])
        old = next((item for item in records(document, collection(section)) if item["id"] == row.get("id")), None)
        _protected(old, row)
        if (COLLECTIONS.get(section, "cutouts"), row.get("id")) in owners:
            fail("소유 객체의 편집은 풋프린트 멤버 편집으로 검토하십시오.", "record", "E_CONFLICT")
        if section == "footprint" and old is not None and any(row.get(key) != old[key] for key in ("placement", "members", "pins", "placement_envelope")):
            fail("배치/멤버는 풋프린트 전용 원자 작업으로 편집하십시오.", "record", "E_CONFLICT")
        if section == "artwork_layer":
            dependencies = [item["id"] for item in candidate.get("pcb", empty_pcb())["apertures"] if item["artwork_layer_id"] == row["id"]]
            expected = dependencies if row["use_state"] != "used" else []
            if values["remove_aperture_ids"] != expected:
                fail("사용 상태 변경에 따른 개구 삭제 목록을 명시적으로 확인하십시오.", "remove_aperture_ids", "E_CONFLICT")
            for identity in expected:
                if ("apertures", identity) in owners:
                    fail("소유 개구를 먼저 풋프린트 멤버에서 분리하십시오.", "remove_aperture_ids", "E_CONFLICT")
                _delete(candidate, "aperture", identity)
        _replace(candidate, section, row)
    else:
        keys = {"id"} | ({"remove_members"} if section == "footprint" else {"remove_aperture_ids"} if section == "artwork_layer" else set())
        _fields(values, keys)
        if (COLLECTIONS.get(section, "cutouts"), values["id"]) in owners:
            fail("소유 객체의 삭제는 풋프린트 멤버 편집으로 처리하십시오.", "id", "E_CONFLICT")
        if section == "footprint":
            old = next((row for row in records(document, collection(section)) if row["id"] == values["id"]), None)
            if old is None or values["remove_members"] != old["members"]:
                fail("풋프린트와 함께 지울 정확한 멤버를 확인하십시오.", "remove_members", "E_CONFLICT")
            for member in old["members"]:
                target = records(candidate, "geometry" if member["collection"] == "geometry" else "pcb." + member["collection"])
                target[:] = [row for row in target if row["id"] != member["id"]]
        if section == "artwork_layer":
            expected = [item["id"] for item in candidate.get("pcb", empty_pcb())["apertures"] if item["artwork_layer_id"] == values["id"]]
            if values["remove_aperture_ids"] != expected:
                fail("제조 이미지와 함께 지울 정확한 개구를 확인하십시오.", "remove_aperture_ids", "E_CONFLICT")
            for identity in expected:
                if ("apertures", identity) in owners:
                    fail("풋프린트 소유 개구를 먼저 분리하십시오.", "remove_aperture_ids", "E_CONFLICT")
                _delete(candidate, "aperture", identity)
        _delete(candidate, section, values["id"])
    if operation != "footprint.member_edit":
        finalize_pcb_edits(document, candidate, "footprint.place" if operation == "footprint.place" else COMMAND)
    return candidate


def place_footprint(document, values):
    """! @brief 단일 권위인 world 멤버에 강체 변환을 적용하며 바뀌는 parameter binding은 차단한다."""
    from rfad.domain.precision_transform import replace_literal, rotation_sin_cos, scalar, point_fields
    owner = next((row for row in document.get("pcb", empty_pcb())["footprints"] if row["id"] == values["id"]), None)
    if owner is None:
        fail("배치할 풋프린트가 없습니다.", "id", "E_CONFLICT")
    placement = normalize_record(document, {"placement": values["placement"]})["placement"]
    old = owner["placement"]
    if old["side"] is None or placement["side"] is None:
        fail("배치 변환에는 이전/새 배치 면이 명시되어야 합니다.", "placement.side", "E_CONFLICT")
    pivot = [scalar(document, item) for item in old["origin"]]
    destination = [scalar(document, item) for item in placement["origin"]]
    previous_angle = scalar(document, old["rotation"], "angle", "deg")
    next_angle = scalar(document, placement["rotation"], "angle", "deg")
    flip = old["side"] != placement["side"]
    sign = -1.0 if flip else 1.0
    si, co = rotation_sin_cos(-previous_angle)
    sn, cn = rotation_sin_cos(next_angle)
    def transform_point(values):
        """! @brief 과거 pivot의 역변환 뒤 선택한 면/방향과 새 pivot을 적용한다."""
        x, y = [scalar(document, item) for item in values]
        dx, dy = x - pivot[0], y - pivot[1]
        local_x, local_y = co * dx - si * dy, si * dx + co * dy
        local_x *= sign
        updated = [destination[0] + cn * local_x - sn * local_y, destination[1] + sn * local_x + cn * local_y]
        values[:] = [replace_literal(document, item, updated[axis], "mm", "footprint.member.position") for axis, item in enumerate(values)]
    def transform_angle(value):
        """! @brief 좌우 반사 방향각을 부호/180도 규약으로 계산한다."""
        angle = scalar(document, value, "angle", "deg") - previous_angle
        return replace_literal(document, value, next_angle + (180.0 - angle if flip else angle), "deg", "footprint.member.angle")
    def transform_shape(shape):
        """! @brief 곡선 종류를 바꾸거나 로컬 좌표 사본을 저장하지 않는다."""
        if shape["kind"] == "polygon":
            for loop in [shape["outer"], *shape["holes"]]:
                for values in loop:
                    transform_point(values)
        else:
            transform_point(shape["center"])
            if "rotation" in shape:
                shape["rotation"] = transform_angle(shape["rotation"])
    member_ids = {item["id"] for item in owner["members"]}
    if any(port.get(key) in member_ids for port in document["ports"] for key in ("positive_geometry_id", "reference_geometry_id")):
        fail("급전 참조가 있는 풋프린트는 포트 경계를 함께 검토하는 배치가 필요합니다.", "ports", "E_UNSUPPORTED")
    conductor = [row["id"] for row in sorted(document["stackup"], key=lambda row: row["order"]) if row["role"] == "conductor"]
    if flip and len(conductor) < 2:
        fail("상하면 반전에는 양면의 실제 도체층이 필요합니다.", "stackup", "E_UNSUPPORTED")
    layer_map = dict(zip(conductor, reversed(conductor)))
    artwork = document.get("pcb", empty_pcb())["artwork_layers"]
    for member in owner["members"]:
        rows = records(document, "geometry" if member["collection"] == "geometry" else "pcb." + member["collection"])
        row = next(item for item in rows if item["id"] == member["id"])
        if member["collection"] == "geometry":
            for _, values in point_fields(row):
                transform_point(values)
            for key in ("rotation", "start_angle"):
                if key in row:
                    row[key] = transform_angle(row[key])
            if flip and "sweep_angle" in row:
                row["sweep_angle"] = replace_literal(document, row["sweep_angle"], -scalar(document, row["sweep_angle"], "angle", "deg"), "deg", "sweep_angle")
            if flip:
                row["layer_id"] = layer_map[row["layer_id"]]
                if "end_layer_id" in row:
                    row["layer_id"], row["end_layer_id"] = layer_map[row["end_layer_id"]], row["layer_id"]
        elif member["collection"] == "apertures":
            if row["definition"]["mode"] == "explicit_shape":
                transform_shape(row["definition"]["shape"])
            if flip:
                source = next(item for item in artwork if item["id"] == row["artwork_layer_id"])
                target = next((item for item in artwork if item["role"] == source["role"] and item["side"] != source["side"] and item["use_state"] == "used"), None)
                if target is None:
                    fail("반대면의 실제 사용하는 제조 이미지 층이 필요합니다.", "artwork_layer_id", "E_CONFLICT")
                row["artwork_layer_id"] = target["id"]
        else:
            transform_shape(row["shape"])
            if flip and "layer_ids" in row:
                row["layer_ids"] = [layer_map[identity] for identity in row["layer_ids"]]
    if owner["placement_envelope"] is not None:
        transform_shape(owner["placement_envelope"])
    owner["placement"] = placement


def preview(document, data):
    """! @brief 표시 장면/모든 변경 원문을 hash로 고정하며 물리 합격을 만들지 않는다."""
    from rfad.application.canvas import build_canvas_dto
    from rfad.domain.project import validate_project
    base = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
            "source_revision_id": document["revision_id"], "operation": data["operation"], "manufacturing_verified": False, "measurement_verified": False}
    try:
        candidate = mutate_candidate(document, data["operation"], data["values"])
        validate_project(candidate)
        for row in candidate.get("pcb", empty_pcb())["apertures"]:
            aperture_projection(candidate, row)
        if len(canonical_bytes(candidate)) > 512 * 1024:
            fail("원문을 포함한 프로젝트가 512 KiB를 초과했습니다.", "record", "E_RESOURCE")
        patch = make_patch(document, candidate, data["operation"], data["reason"])
        probe = deepcopy(document)
        probe["schema_version"] = PROJECT_SCHEMA
        apply_pcb_command(probe, patch)
        digest = canonical_hash({"profile": PROFILE, "source": canonical_hash(document), "input": {key: data[key] for key in ("expected_revision", "operation", "values", "reason")}, "patch": patch})
        changes = [{"collection": item["collection"], "id": item["id"], "label": (item["replacement"]["value"] or item["expected"]["value"]).get("name", "원본 도체"),
                    "before": item["expected"]["value"], "after": item["replacement"]["value"],
                    "before_display": record_summary(document, item["expected"]["value"]), "after_display": record_summary(candidate, item["replacement"]["value"]), "unit": ""} for item in patch["changes"]]
        section = data["operation"].split(".")[0]
        identity = data["values"].get("id", data["values"].get("record", {}).get("id"))
        selection = {"kind": section, "id": identity} if any(row["id"] == identity for row in records(candidate, collection(section))) else {"kind": "project", "id": document["project_id"]}
        return bounded({**base, "can_apply": True, "review_hash": digest, "before_scene": build_canvas_dto(document), "scene": build_canvas_dto(candidate), "changes": changes,
                        "issues": [], "selection": selection,
                        "missing_fields": missing_fields(data["values"]), "document_bytes": len(canonical_bytes(candidate))}), patch
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
        return bounded({**base, "can_apply": False, "review_hash": None, "scene": None, "changes": [],
                        "issues": [{"severity": "blocker", "code": "E_SCHEMA", "message_ko": "PCB 입력의 JSON 형태/필수 필드가 유효하지 않습니다.",
                                    "details": {"field_path": "values", "error_type": type(error).__name__}}]}), None
    except ProjectError as error:
        return bounded({**base, "can_apply": False, "review_hash": None, "scene": None, "changes": [],
                        "issues": [{"severity": "blocker", "code": error.code, "message_ko": error.message, "details": error.details}]}), None


def validate_input(context, data, method=MUTATION):
    """! @brief 공개 입력의 필드/크기를 먼저 제한하고 내부 patch 명령은 노출하지 않는다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    if method == "pcb.features.receipt":
        _fields(data, {"request_key", "request_key_epoch"})
        _uuid(data["request_key_epoch"])
        _text(data["request_key"], "request_key", limit=128)
        return
    keys = {"expected_revision", "section", "record_id"} if method == "pcb.features.get" else {"expected_revision", "operation", "values", "reason"}
    if method == "pcb.features.get":
        keys |= set(data) & {"shape_kind", "definition_mode", "envelope_kind"}
    if method == MUTATION:
        keys |= {"command_id", "review_hash"}
    _fields(data, keys)
    _uuid(data["expected_revision"])
    if len(canonical_bytes(data)) > 256 * 1024:
        fail("PCB 편집 입력이 256 KiB를 초과했습니다.", "input", "E_RESOURCE")
    if method == "pcb.features.get":
        if data["section"] not in {*SECTIONS, "overview"}:
            fail("지원하지 않는 PCB 편집 종류입니다.", "section", "E_UNSUPPORTED")
        if data["record_id"] is not None:
            _uuid(data["record_id"])
        if "shape_kind" in data and data["shape_kind"] not in ("circle", "rectangle", "capsule", "polygon"):
            fail("지원하지 않는 형상 종류입니다.", "shape_kind", "E_UNSUPPORTED")
        if "definition_mode" in data and (data["section"] != "aperture" or data["definition_mode"] not in ("explicit_shape", "pad_margin")):
            fail("지원하지 않는 개구 정의입니다.", "definition_mode", "E_UNSUPPORTED")
        if "envelope_kind" in data and (data["section"] != "footprint" or data["envelope_kind"] not in (None, "circle", "rectangle", "capsule", "polygon")):
            fail("지원하지 않는 배치 외곽입니다.", "envelope_kind", "E_UNSUPPORTED")
    else:
        if type(data["operation"]) is not str or data["operation"] not in OPERATIONS or type(data["values"]) is not dict:
            fail("지원하지 않는 PCB 작업 또는 입력입니다.", "operation", "E_UNSUPPORTED")
        _text(data["reason"], "reason", empty=True, limit=512)
    if method == MUTATION:
        _uuid(data["command_id"])
        digest = data["review_hash"]
        if type(digest) is not str or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            fail("검토 hash가 필요합니다.", "review_hash", "E_HASH")


def _document(service, state, context, data):
    """! @brief 동일 writer/읽기 snapshot에서 현재 원본 개정을 확인한다."""
    project = service._project(state, context)
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != data["expected_revision"]:
        fail("PCB 편집 기준 개정이 변경됐습니다.", "expected_revision", "E_CONFLICT")
    return document


def read(service, method, params):
    """! @brief 조회는 원본/영수증을 만들지 않으며 불명 변경을 부재로 추정하지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0" or method not in READS:
        fail("지원하지 않는 PCB 조회 계약입니다.", "contract_version", "E_VERSION")
    context, data = params["context"], params["input"]
    validate_input(context, data, method)
    state = service.journal.read()
    if method == "pcb.features.receipt":
        service._project(state, context)
        receipt = state["receipts"].get(canonical_hash([data["request_key_epoch"], data["request_key"]]))
        if receipt is not None and (receipt["method"] != MUTATION or receipt["scope"] != context):
            fail("다른 원본/메서드의 영수증입니다.", "request_key", "E_CONFLICT")
        found = receipt is not None and receipt["expires_at"] > service._now()
        return {"project_id": context["project_id"], "authoritative": True, "status": "found" if found else "expired" if receipt is not None else "unresolved",
                "response": deepcopy(receipt["response"]) if found else None, "may_resubmit": False}
    document = _document(service, state, context, data)
    return get(document, data) if method == "pcb.features.get" else preview(document, data)[0]


def admit(service, state, context, data):
    """! @brief 재검토한 동일 후보를 원본 한 명령과 영수증으로 원자 적용한다."""
    validate_input(context, data)
    document = _document(service, state, context, data)
    review, patch = preview(document, data)
    if not review["can_apply"] or review["review_hash"] != data["review_hash"]:
        fail("PCB 후보가 변경됐거나 적용할 수 없습니다. 다시 검토하십시오.", "review_hash", "E_CONFLICT")
    result = service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"], "type": COMMAND, "payload": patch})
    state["commands"][data["command_id"]]["pcb_editor"] = {"operation": data["operation"], "input": deepcopy(data["values"]), "reason": data["reason"], "review_hash": review["review_hash"]}
    return {**result, "profile": PROFILE, "review_hash": review["review_hash"], "selection": review["selection"]}
