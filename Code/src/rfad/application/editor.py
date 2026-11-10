"""! @brief GUI가 수량과 원본 문서를 해석하지 않도록 선택 객체의 편집 DTO를 만든다."""

from copy import deepcopy
import json
import math
from uuid import UUID

from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.parameter_graph import restore_parameter_command
from rfad.domain.units import Quantity, QuantityError, _UNITS


PROFILE = "rfad.editor/0.1"
MAX_DTO_BYTES = 60 * 1024
COLLECTIONS = {"material": "materials", "layer": "stackup", "net": "nets", "geometry": "geometry", "port": "ports"}
LABELS = {
    "name": "이름", "description": "설명", "id": "식별자", "kind": "형식", "role": "역할",
    "frame_id": "좌표계", "model": "재료 모델", "width": "폭", "height": "높이", "outline": "외곽",
    "thickness_convention": "두께 규약", "epsilon_r": "상대 유전율", "tan_delta": "손실 탄젠트",
    "conductivity": "전도도", "validity_hz": "유효 주파수", "min": "하한", "max": "상한",
    "z_min": "하부 위치", "thickness": "두께", "order": "층 순서", "material_id": "재료",
    "layer_id": "층", "net_id": "네트", "material_ref": "재료", "source_ref": "출처",
    "include_in_em": "해석에 포함", "include_in_export": "내보내기에 포함", "start": "시작점",
    "end": "끝점", "center": "중심", "radius": "반지름", "start_angle": "시작 각도",
    "sweep_angle": "회전 각도", "positive_geometry_id": "양극 도체", "reference_geometry_id": "기준 도체",
    "resistance": "기준 저항", "reference_plane": "기준면", "polarity": "극성", "direction": "방향",
    "source_refs": "출처 기록", "assumptions": "가정 기록",
    "excitation_box": "급전 영역", "stop": "끝점",
    "outer": "외곽 꼭짓점", "holes": "비어 있는 영역", "pad_shape": "패드 형태", "size": "패드 치수", "rotation": "회전각",
    "end_layer_id": "도착 층", "finished_hole_diameter": "완성 구멍 지름", "plating_thickness": "도금 두께",
    "tool_hole_diameter": "제작 드릴 지름", "fill": "구멍 충진", "pad_ids": "연결 패드",
}
VALUE_LABELS = {
    "length": "길이", "frequency": "주파수", "time": "시간", "angle": "각도",
    "impedance": "임피던스", "conductivity": "전도도", "power": "전력", "dimensionless": "무차원",
    "user_entered": "직접 입력", "source_default": "자료 기본값", "estimated": "추정값",
    "missing": "미정", "not_applicable": "해당 없음", "unsupported": "미지원", "conflicting": "값 충돌",
    "conductor": "도체", "dielectric": "유전체", "coating": "코팅", "adhesive": "접착층", "air": "공기층",
    "radiator": "방사체", "ground": "접지", "feed": "급전", "short": "단락부",
    "rectangle": "직사각형", "circle": "원형", "line_path": "선 패턴", "arc_path": "원호 패턴", "lumped": "집중소자 포트",
    "isotropic_constant": "등방성 상수 모델", "finished": "완성 두께",
    "planar_region": "면 패턴", "pad": "패드", "via": "도금 비아", "none": "충진 없음",
    "material": "재료", "layer": "적층", "net": "네트", "geometry": "형상", "port": "포트",
}
FIELD_HELP = {
    "mode": "직접 값을 입력하거나, 아직 모르는 값은 미정으로 남길 수 있습니다.",
    "unit": "단위만 바꾸면 물리값은 유지됩니다. 숫자와 단위를 함께 바꾸면 새 값으로 입력됩니다.",
    "dimension": "입력하는 물리량의 종류입니다. 표시 단위와 같은 종류를 선택하십시오.",
    "expression": "단위를 포함한 수식을 입력하고, 사용한 변수는 아래에서 매개변수와 연결하십시오.",
    "bindings": "표현식의 변수와 매개변수를 연결합니다. 매개변수 이름을 바꿔도 연결은 유지됩니다.",
    "parameter_id": "선택한 매개변수가 바뀌면 이 값도 함께 바뀝니다.",
    "status": "값의 입력 상태입니다. 미정은 0과 다르며, 이 표시는 설계 검증 합격 여부를 뜻하지 않습니다.",
}


def _fail(message: str, key: str, code: str = "E_SCHEMA") -> None:
    """! @brief 입력 위치를 잃지 않는 편집 진단을 만든다."""
    raise ProjectError(code, message, details={"field_path": key})


def _uuid(value: object) -> str:
    """! @brief 선택 식별자는 정규 UUID만 허용한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _fail("선택 식별자가 유효하지 않습니다.", "selection.id")
    return value


def selected_object(document: dict, selection: dict) -> tuple[str, dict]:
    """! @brief 허용한 종류와 안정 ID로 선택하고 새 매개변수는 명시적으로 구분한다."""
    if type(selection) is not dict or set(selection) != {"kind", "id"}:
        _fail("선택에는 kind와 id가 필요합니다.", "selection")
    kind, identity = selection["kind"], _uuid(selection["id"])
    if kind == "project" and identity == document["project_id"]:
        return kind, {"name": document["metadata"]["name"], "description": document["metadata"]["description"]}
    if kind in {"new_parameter", "new_material", "new_net", "new_port"}:
        used = {document["project_id"], document["revision_id"], *document["parent_revision_ids"], *document["parameters"]}
        used.update(frame["id"] for frame in document["frames"].values())
        used.update(item["id"] for collection in COLLECTIONS.values() for item in document[collection])
        if document["board"] is not None:
            used.add(document["board"]["id"])
        if identity in used:
            _fail("새 식별자가 기존 객체와 충돌합니다.", "selection.id", "E_CONFLICT")
        if kind == "new_parameter":
            return kind, {"id": identity, "name": "", "quantity": Quantity.missing("length", "mm").to_dict()}
        if kind == "new_net":
            return kind, {"id": identity, "name": ""}
        frequency_range = {key: Quantity.missing("frequency", "GHz").to_dict() for key in ("min", "max")}
        if kind == "new_material":
            return kind, {"id": identity, "name": "", "model": "isotropic_constant",
                "epsilon_r": Quantity.missing("dimensionless", "1").to_dict(),
                "tan_delta": Quantity.missing("dimensionless", "1").to_dict(),
                "conductivity": Quantity.missing("conductivity", "S/m").to_dict(),
                "validity_hz": frequency_range, "source_refs": [], "assumptions": []}
        if document["board"] is None or len(document["geometry"]) < 2:
            _fail("포트를 생성하려면 기판과 서로 다른 도체 패턴 두 개가 필요합니다.", "ports", "E_PORT")
        if document["ports"]:
            _fail("현재 단일 포트만 지원합니다. 기존 포트 속성을 편집하십시오.", "ports", "E_PORT")
        return kind, {"id": identity, "name": "", "kind": "lumped", "positive_geometry_id": "", "reference_geometry_id": "",
            "resistance": Quantity.missing("impedance", "ohm").to_dict(), "reference_plane": "집중 포트의 급전 영역",
            "polarity": 1, "direction": [1.0, 0.0, 0.0], "validity_hz": frequency_range,
            "excitation_box": {key: [Quantity.missing("length", "mm").to_dict() for _ in range(3)] for key in ("start", "stop")}}
    if kind == "parameter" and identity in document["parameters"]:
        return kind, document["parameters"][identity]
    if kind == "board" and document["board"] is not None and document["board"]["id"] == identity:
        return kind, document["board"]
    if type(kind) is str and kind in COLLECTIONS:
        for item in document[COLLECTIONS[kind]]:
            if item["id"] == identity:
                if kind == "port" and "excitation_box" not in item:
                    return kind, {**deepcopy(item), "excitation_box": {key: [Quantity.missing("length", "mm").to_dict() for _ in range(3)] for key in ("start", "stop")}}
                return kind, item
    _fail("선택한 객체가 없거나 지원하지 않는 종류입니다.", "selection", "E_CONFLICT")


def _choice(value: str, label: str | None = None) -> dict:
    """! @brief 표시 이름과 전송 값을 분리한다."""
    return {"value": value, "label": VALUE_LABELS.get(value, value) if label is None else label}


def _field(key: str, label: str, value, *, editor="text", choices=None, readonly=False) -> dict:
    """! @brief 원본 저장 형태와 독립적인 하나의 화면 필드를 만든다."""
    result = {"key": key, "label": label, "editor": editor, "value": value, "choices": choices or [], "readonly": readonly}
    name = key.rsplit(".", 1)[-1]
    if readonly and name in ("status", "kind", "model", "thickness_convention", "fill", "pad_shape"):
        result["display_value"] = VALUE_LABELS.get(value, value)
    if name in ("id", "frame_id"):
        result["advanced"] = True
    if name in FIELD_HELP:
        result["help"] = FIELD_HELP[name]
    return result


def _object_label(obj: dict, fallback: str = "객체") -> str:
    """! @brief 사용자가 정한 이름은 그대로 두고 무명 객체 종류만 한국어로 표시한다."""
    if "name" in obj:
        return obj["name"]
    kind = obj.get("kind", fallback)
    return VALUE_LABELS.get(kind, kind) + " " + obj["id"][:8]


def _parameter_choices(document: dict, dimension: str | None = None) -> list[dict]:
    """! @brief 표시 이름을 결합 키로 사용하지 않고 UUID 선택지를 제공한다."""
    return [_choice(key, value["name"]) for key, value in sorted(document["parameters"].items()) if dimension is None or value["quantity"]["dimension"] == dimension]


def _display_quantity(quantity: Quantity) -> tuple[str, str, str]:
    """! @brief 표시 환산이 표현 범위를 넘으면 0으로 바꾸지 않고 SI 편집 표시로 전환한다."""
    if quantity.value_si is None:
        return "", quantity.display_unit, ""
    try:
        return repr(quantity.as_unit(quantity.display_unit)), quantity.display_unit, ""
    except QuantityError:
        unit = next(unit for unit, definition in _UNITS.items() if definition.dimension == quantity.dimension and definition.scale == 1.0)
        return repr(quantity.value_si), unit, "원래 표시 단위로 값을 표현할 수 없어 SI 단위로 표시합니다. 저장된 값과 단위는 유지됩니다."


def _quantity_fields(document: dict, value: dict, key: str, label: str) -> list[dict]:
    """! @brief 참조/미정과 숫자를 구분하고 표시 단위 환산은 서비스에서 수행한다."""
    reference = "parameter_id" in value
    raw = document["parameters"][value["parameter_id"]]["quantity"] if reference else value
    quantity = Quantity(**raw)
    number, unit, note = _display_quantity(quantity)
    mode = "parameter" if reference else ("value" if quantity.value_si is not None else "missing")
    modes = [_choice("value", "직접 입력"), _choice("missing", "미정"), _choice("parameter", "매개변수 참조")]
    result = [
        _field(key + ".mode", label + " 입력 방식", mode, editor="choice", choices=modes),
        _field(key + ".value", label + " 값", number),
        _field(key + ".unit", label + " 단위", unit, editor="choice", choices=[_choice(unit) for unit, definition in _UNITS.items() if definition.dimension == quantity.dimension]),
        _field(key + ".parameter_id", label + " 참조", value["parameter_id"] if reference else "", editor="choice", choices=[_choice("", "선택 없음"), *_parameter_choices(document, quantity.dimension.value)]),
        _field(key + ".status", label + " 입력 상태", quantity.status.value, readonly=True),
        _field(key + ".display_note", label + " 표시 안내", note, readonly=True),
    ]
    return result


def _coordinate_table(document, points, key):
    """! @brief 다각형 64점도 전송 상한 안에 머물도록 좌표 상태를 작은 표로 투영한다."""
    rows = []
    for index, point in enumerate(points):
        row = []
        for axis, value in enumerate(point):
            quantity = resolve_scalar(document, value, "length", f"{key}.{index}.{axis}")
            reference = value.get("parameter_id", "")
            unit = "mm"
            try:
                number = "" if quantity.value_si is None else repr(quantity.as_unit("mm"))
            except QuantityError:
                number, unit = repr(quantity.value_si), "m"
            row.append({"mode": "parameter" if reference else ("missing" if quantity.value_si is None else "value"),
                        "value": number, "parameter_id": reference, "unit": unit})
        rows.append(row)
    return rows


def _edited_coordinate_table(document, original, incoming, key):
    """! @brief 표에서 명시적으로 바꾼 좌표만 적용하고 나머지 단위/출처/결합을 보존한다."""
    displayed = _coordinate_table(document, original, key)
    if type(incoming) is not list or len(incoming) != len(original):
        _fail("좌표 표에서는 꼭짓점 개수를 바꿀 수 없습니다.", key)
    result = deepcopy(original)
    for index, row in enumerate(incoming):
        if type(row) is not list or len(row) != 2:
            _fail("각 점은 x/y 두 좌표여야 합니다.", key)
        for axis, cell in enumerate(row):
            field = f"{key}.{index}.{axis}"
            if (type(cell) is not dict or set(cell) != {"mode", "value", "parameter_id", "unit"}
                    or any(type(value) is not str for value in cell.values()) or cell["mode"] not in {"value", "missing", "parameter"}):
                _fail("좌표 입력 방식과 숫자/매개변수 선택을 확인하십시오.", field)
            if cell["unit"] != displayed[index][axis]["unit"]:
                _fail("좌표 표의 표시 단위는 읽기 전용입니다.", field + ".unit")
            if cell == displayed[index][axis]:
                continue
            value = original[index][axis]
            quantity = resolve_scalar(document, value, "length", field)
            if cell["mode"] == "parameter":
                reference = {"parameter_id": _uuid(cell["parameter_id"])}
                resolve_scalar(document, reference, "length", field)
                result[index][axis] = reference
            elif cell["mode"] == "missing":
                result[index][axis] = Quantity(None, "length", quantity.display_unit, "missing", quantity.source_refs).to_dict()
            else:
                result[index][axis] = Quantity.from_value(_number(cell["value"], field), cell["unit"], source_refs=quantity.source_refs).to_dict()
    return result


def fields_for(document: dict, selection: dict) -> list[dict]:
    """! @brief 선택 객체의 현재 지원 속성만 표시하고 원본 provenance는 읽기 전용으로 보존한다."""
    kind, obj = selected_object(document, selection)
    if kind in ("parameter", "new_parameter"):
        quantity = Quantity(**obj["quantity"])
        number, unit, note = _display_quantity(quantity)
        expression = obj.get("expression")
        mode = "expression" if expression else ("value" if quantity.value_si is not None else "missing")
        return [
            _field("name", "이름", obj["name"]),
            _field("mode", "입력 방식", mode, editor="choice", choices=[_choice("value", "직접 입력"), _choice("missing", "미정"), _choice("expression", "표현식")]),
            _field("value", "값", number),
            _field("unit", "표시 단위", unit, editor="choice", choices=[_choice(unit) for unit in _UNITS]),
            _field("dimension", "물리 차원", quantity.dimension.value, editor="choice", choices=[_choice(dimension) for dimension in dict.fromkeys(unit.dimension.value for unit in _UNITS.values())]),
            _field("expression", "표현식", expression["text"] if expression else ""),
            _field("bindings", "변수 결합", deepcopy(expression["bindings"]) if expression else {}, editor="bindings", choices=_parameter_choices(document)),
            _field("status", "입력 상태", quantity.status.value, readonly=True),
            _field("display_note", "표시 안내", note, readonly=True),
        ]
    fields = []

    def walk(value, path: list[str], labels: list[str]) -> None:
        """! @brief 알려진 객체의 값만 순회하고 필드 경로는 객체 밖으로 벗어나지 않는다."""
        key, label = ".".join(path), " / ".join(labels)
        if type(value) is dict:
            if "value_si" in value or set(value) == {"parameter_id"}:
                fields.extend(_quantity_fields(document, value, key, label))
            else:
                for name, child in value.items():
                    walk(child, [*path, name], [*labels, LABELS.get(name, name)])
        elif type(value) is list:
            if path[-1] == "outer" or (len(path) >= 2 and path[-2] == "holes"):
                fields.append(_field(key, label, _coordinate_table(document, value, key), editor="coordinate_table"))
            elif path[-1] in ("source_refs", "assumptions"):
                fields.append(_field(key, label, "\n".join(value), readonly=True))
            elif path[-1] == "pad_ids":
                layer_names = {layer["id"]: layer["name"] for layer in document["stackup"]}
                choices = [_choice(item["id"], _object_label(item) + " / " + layer_names[item["layer_id"]])
                           for item in document["geometry"] if item["kind"] == "pad"]
                fields.append(_field(key, label, deepcopy(value), editor="multichoice", choices=choices))
            else:
                coordinate = len(value) <= 3 and all(type(item) is not list for item in value)
                for index, child in enumerate(value):
                    walk(child, [*path, str(index)], [*labels, "xyz"[index] if coordinate else str(index + 1)])
        else:
            name = path[-1]
            readonly = name in ("id", "kind", "frame_id", "model", "thickness_convention", "fill", "pad_shape")
            choices = None
            references = {"material_id": "materials", "material_ref": "materials", "net_id": "nets", "layer_id": "stackup", "end_layer_id": "stackup", "positive_geometry_id": "geometry", "reference_geometry_id": "geometry"}
            if name in references:
                choices = [_choice(item["id"], _object_label(item)) for item in document[references[name]]]
                if name in ("material_id", "material_ref", "net_id"):
                    choices.insert(0, _choice("", "선택 없음"))
                elif kind == "new_port" and name in ("positive_geometry_id", "reference_geometry_id"):
                    choices.insert(0, _choice("", "도체를 선택하십시오"))
            elif name == "role":
                choices = [_choice(item) for item in (("conductor", "dielectric", "coating", "adhesive", "air") if kind == "layer" else ("radiator", "ground", "feed", "short", "conductor"))]
            elif name == "polarity":
                choices = [_choice("1", "+1"), _choice("-1", "-1")]
            display = value if type(value) is bool else ("" if value is None else str(value))
            field = _field(key, label, display, editor="bool" if type(value) is bool else ("choice" if choices is not None else "text"), choices=choices, readonly=readonly)
            if name == "frame_id":
                frame_name = next((name for name, frame in document["frames"].items() if frame["id"] == value), None)
                field["display_value"] = {"world": "기준 좌표계", "board": "기판 좌표계"}.get(frame_name, display)
            fields.append(field)

    walk(obj, [], [])
    return fields


def build_dto(document: dict, saved_revision: str, history: dict, selection: dict | None) -> dict:
    """! @brief 객체 목록과 선택 속성만 전송하며 전체 원본과 계산 캐시는 내보내지 않는다."""
    items = [{"kind": "project", "id": document["project_id"], "label": document["metadata"]["name"]}]
    items += [{"kind": "parameter", "id": identity, "label": obj["name"]} for identity, obj in sorted(document["parameters"].items())]
    if document["board"] is not None:
        items.append({"kind": "board", "id": document["board"]["id"], "label": "기판"})
    for kind, collection in COLLECTIONS.items():
        items += [{"kind": kind, "id": obj["id"], "label": _object_label(obj, kind)} for obj in document[collection]]
    selected = {"kind": "project", "id": document["project_id"]} if selection is None else selection
    selected_fields = fields_for(document, selected)
    result = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"], "saved_revision": saved_revision,
              "metadata": {key: document["metadata"][key] for key in ("name", "description")}, "history": history, "items": items,
              "selection": {**selected, "fields": selected_fields}}
    if any(field["editor"] == "coordinate_table" for field in selected_fields):
        result["coordinate_choices"] = _parameter_choices(document, "length")
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_DTO_BYTES:
        _fail("선택 속성 DTO가 초기 전송 크기 상한을 초과합니다.", "selection", "E_RESOURCE")
    return result


def _number(text: str, key: str, *, integer=False):
    """! @brief 문자열 수치를 명시적으로 변환하고 NaN/Infinity와 빈값을 거부한다."""
    try:
        number = int(text) if integer else float(text)
        if not text.strip() or not math.isfinite(number):
            raise ValueError()
    except (ValueError, OverflowError):
        _fail("유한한 숫자를 입력하십시오.", key, "E_UNIT")
    return number


def _edited_quantity(original: dict, document: dict, values: dict, prefix: str, dimension: str, changed: set[str]) -> dict:
    """! @brief 입력 방식에 맞는 수량 또는 참조를 만들고 원본 출처를 보존한다."""
    mode = values[prefix + ".mode"]
    local_changes = {key[len(prefix) + 1:] for key in changed if key.startswith(prefix + ".")}
    active = {"mode", "parameter_id"} if mode == "parameter" else ({"mode", "unit", "value"} if mode == "value" else {"mode", "unit"})
    if local_changes - active:
        _fail("현재 입력 방식에서 사용하지 않는 속성입니다.", prefix + "." + sorted(local_changes - active)[0])
    if mode == "parameter":
        result = {"parameter_id": values[prefix + ".parameter_id"]}
        resolve_scalar(document, result, dimension, prefix)
        return result
    unit = values[prefix + ".unit"]
    raw = document["parameters"][original["parameter_id"]]["quantity"] if "parameter_id" in original else original
    try:
        if local_changes == {"unit"}:
            quantity = Quantity(raw["value_si"], dimension, unit, raw["status"], tuple(raw["source_refs"]))
        elif mode == "missing":
            quantity = Quantity(None, dimension, unit, "missing", tuple(raw["source_refs"]))
        else:
            quantity = Quantity.from_value(_number(values[prefix + ".value"], prefix + ".value"), unit, source_refs=tuple(raw["source_refs"]))
            if quantity.dimension.value != dimension:
                _fail("필드의 물리 차원과 단위가 다릅니다.", prefix + ".unit", "E_UNIT")
        return quantity.to_dict()
    except QuantityError as error:
        _fail(str(error), prefix + ".unit", "E_UNIT")


def edit_command(document: dict, selection: dict, changes: dict) -> dict:
    """! @brief 허용된 화면 필드만 받아 기존 도메인 명령으로 변환한다."""
    kind, original = selected_object(document, selection)
    descriptors = {field["key"]: field for field in fields_for(document, selection)}
    if type(changes) is not dict or not changes:
        _fail("변경할 속성이 필요합니다.", "values")
    values = {key: deepcopy(field["value"]) for key, field in descriptors.items()}
    for key, value in changes.items():
        field = descriptors.get(key)
        if field is None or field["readonly"]:
            _fail("이 속성은 편집할 수 없습니다.", "values." + key)
        if field["editor"] == "bool":
            if type(value) is not bool:
                _fail("포함 여부는 bool이어야 합니다.", key)
        elif field["editor"] == "bindings":
            if type(value) is not dict or any(type(alias) is not str or type(target) is not str for alias, target in value.items()):
                _fail("변수 결합은 이름과 매개변수 ID의 사전이어야 합니다.", key)
        elif field["editor"] == "multichoice":
            if (type(value) is not list or any(type(item) is not str for item in value)
                    or len(set(value)) != len(value) or not set(value) <= {item["value"] for item in field["choices"]}):
                _fail("중복 없이 표시된 패드를 선택하십시오.", key)
        elif field["editor"] == "coordinate_table":
            if type(value) is not list:
                _fail("좌표 표의 점 목록이 필요합니다.", key)
        elif type(value) is not str:
            _fail("편집 필드는 문자열이어야 합니다.", key)
        if field["editor"] == "choice" and value not in {item["value"] for item in field["choices"]}:
            _fail("허용된 선택지를 사용하십시오.", key)
        values[key] = deepcopy(value)
    changed = {key for key in changes if changes[key] != descriptors[key]["value"]}
    if not changed and not kind.startswith("new_"):
        _fail("변경된 속성이 없습니다.", "values", "E_CONFLICT")
    if kind == "project":
        return {"type": "metadata.set", "payload": {key: values[key] for key in ("name", "description")}}
    if kind in ("parameter", "new_parameter"):
        active = {"name", "mode", "unit", "dimension"}
        active.update({"expression", "bindings"} if values["mode"] == "expression" else ({"value"} if values["mode"] == "value" else set()))
        if changed - active:
            _fail("현재 입력 방식에서 사용하지 않는 속성입니다.", sorted(changed - active)[0])
        payload = {"id": selection["id"], "name": values["name"]}
        if values["mode"] == "expression":
            payload.update(expression=values["expression"], bindings=values["bindings"], dimension=values["dimension"], display_unit=values["unit"])
            return {"type": "parameter.set_expression", "payload": payload}
        if not ({"mode", "value", "unit", "dimension"} & changed) and kind != "new_parameter":
            payload["quantity"] = deepcopy(original["quantity"])
        else:
            try:
                if kind != "new_parameter" and ({"mode", "value", "unit", "dimension"} & changed) == {"unit"}:
                    raw = original["quantity"]
                    quantity = Quantity(raw["value_si"], values["dimension"], values["unit"], raw["status"], tuple(raw["source_refs"]))
                elif values["mode"] == "missing":
                    quantity = Quantity(None, values["dimension"], values["unit"], "missing", tuple(original["quantity"]["source_refs"]))
                else:
                    quantity = Quantity.from_value(_number(values["value"], "value"), values["unit"], source_refs=tuple(original["quantity"]["source_refs"]))
                    if quantity.dimension.value != values["dimension"]:
                        _fail("물리 차원과 표시 단위가 다릅니다.", "unit", "E_UNIT")
                payload["quantity"] = quantity.to_dict()
            except QuantityError as error:
                _fail(str(error), "unit", "E_UNIT")
        result = {"type": "parameter.set", "payload": payload}
        if kind != "new_parameter" and result == restore_parameter_command(original):
            _fail("원본을 변경하지 않는 입력입니다.", "values", "E_CONFLICT")
        return result
    obj = deepcopy(original)

    def update(value, path: list[str]):
        """! @brief DTO에 노출한 기존 필드만 바꾸고 수량은 한 번만 변환한다."""
        key = ".".join(path)
        if type(value) is dict:
            if "value_si" in value or set(value) == {"parameter_id"}:
                if not any(item.startswith(key + ".") for item in changed):
                    return value
                raw = document["parameters"][value["parameter_id"]]["quantity"] if "parameter_id" in value else value
                return _edited_quantity(value, document, values, key, raw["dimension"], changed)
            return {name: update(child, [*path, name]) for name, child in value.items()}
        if type(value) is list:
            if descriptors.get(key, {}).get("editor") == "coordinate_table":
                return _edited_coordinate_table(document, value, values[key], key) if key in changed else value
            if path[-1] in ("source_refs", "assumptions"):
                return value
            if path[-1] == "pad_ids":
                return deepcopy(values[key]) if key in changed else value
            return [update(child, [*path, str(index)]) for index, child in enumerate(value)]
        if key not in changed:
            return value
        edited = values[key]
        if type(value) is bool:
            return edited
        if "direction" in path:
            return _number(edited, key)
        if type(value) is int:
            return _number(edited, key, integer=True)
        if type(value) is float:
            return _number(edited, key)
        if path[-1] in ("material_id", "material_ref", "net_id", "source_ref") and edited == "":
            return None
        return edited

    obj = update(obj, [])
    if kind == "port" and "excitation_box" not in next(item for item in document["ports"] if item["id"] == selection["id"]):
        if not any(key.startswith("excitation_box.") for key in changed):
            obj.pop("excitation_box", None)
    if obj == original and not kind.startswith("new_"):
        _fail("원본을 변경하지 않는 입력입니다.", "values", "E_CONFLICT")
    kind = kind.removeprefix("new_")
    return {"type": kind + ".set", "payload": {kind: obj}}
