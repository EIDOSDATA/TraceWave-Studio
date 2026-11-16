"""! @brief 정밀 편집 입력을 검토 가능한 원본 후보와 출처 사본으로 구성한다."""

from copy import deepcopy
from uuid import UUID, uuid5

from rfad.adapters.planar_backend import operate, runtime
from rfad.application.canonical import canonical_hash
from rfad.domain.design import _uuid
from rfad.domain.object_names import allocate_name, object_label
from rfad.domain.precision_dimensions import bind_dimension, dimensions, set_dimension
from rfad.domain.precision_transform import MAX_SELECTION, fail, point, point_fields, transform
from rfad.domain.units import Quantity


OPERATIONS = {
    "rotate": ("회전", {"pivot_x_mm", "pivot_y_mm", "angle_deg"}),
    "mirror": ("미러", {"axis", "offset_mm"}),
    "dimension_set": ("치수 변경", {"dimension_key", "value", "unit"}),
    "bind_dimension": ("매개변수 연결", {"dimension_key", "parameter_id"}),
    "union": ("영역 합치기", set()),
    "difference": ("첫 영역에서 빼기", set()),
    "intersection": ("영역 교차", set()),
    "offset": ("영역 오프셋", {"distance_mm", "join", "mitre_limit"}),
}
PLANAR_OPERATIONS = {"union", "difference", "intersection", "offset"}


def selected(document, identities):
    """! @brief 명시 선택 순서를 보존하며 모르는 UUID와 중복을 차단한다."""
    if type(identities) is not list or len(identities) > MAX_SELECTION:
        fail("선택은 최대 16개 UUID 목록이어야 합니다.", "selection_ids", "E_RESOURCE")
    for identity in identities:
        _uuid(identity, "selection_ids")
    if len(set(identities)) != len(identities):
        fail("같은 객체를 중복 선택할 수 없습니다.", "selection_ids", "E_CONFLICT")
    geometry = {row["id"]: row for row in document["geometry"]}
    if any(identity not in geometry for identity in identities):
        fail("선택 객체가 현재 개정에 없습니다.", "selection_ids", "E_CONFLICT")
    return [geometry[identity] for identity in identities]


def _referenced(document, identities):
    """! @brief 객체 교체에서 단자/비아/기대 연결을 자동으로 다른 객체에 넘기지 않는다."""
    ids = set(identities)
    for port in document["ports"]:
        if ids & {port["positive_geometry_id"], port["reference_geometry_id"]}:
            return "포트가 참조한 영역입니다. 급전 의미를 자동으로 새 객체에 넘기지 않습니다."
    for row in document["connections"]:
        if ids & set(row["object_ids"]):
            return "기대 연결이 참조한 영역입니다. 먼저 연결 참조를 명시적으로 정리하십시오."
    for row in document["geometry"]:
        if ids & set(row.get("pad_ids", [])):
            return "비아가 참조한 패드입니다. 참조를 자동 교체하지 않습니다."
    return ""


def operation_reason(document, rows, operation):
    """! @brief 비활성 사유를 서비스와 GUI가 같은 선택 기준으로 표시한다."""
    if not rows:
        return "도체 객체를 선택하십시오."
    if operation in ("dimension_set", "bind_dimension", "offset") and len(rows) != 1:
        return "이 작업에는 객체 한 개를 선택하십시오."
    if operation in PLANAR_OPERATIONS:
        engine = runtime()[1]
        if not engine["available"]:
            return engine["reason"]
        if any(row["kind"] != "planar_region" for row in rows):
            return "현재 평면 연산은 직선 외곽과 구멍을 가진 도체 영역만 지원합니다."
        if operation != "offset" and len(rows) < 2:
            return "집합 연산에는 두 개 이상 영역이 필요합니다."
        fields = ("frame_id", "layer_id", "net_id", "material_ref", "role", "include_in_em", "include_in_export")
        if any(any(row[key] != rows[0][key] for key in fields) for row in rows[1:]):
            return "좌표계/층/net/재료/역할/해석 및 출력 포함 상태가 같은 영역만 연산할 수 있습니다."
        if any("parameter_id" in value or value.get("value_si") is None for row in rows for _, coordinates in point_fields(row) for value in coordinates):
            return "좌표가 미정이거나 매개변수에 결합되어 있습니다. 자동으로 리터럴 영역으로 변환하지 않습니다."
        return _referenced(document, [row["id"] for row in rows])
    if operation in ("dimension_set", "bind_dimension"):
        key = "editable" if operation == "dimension_set" else "binding_supported"
        return "" if any(row[key] for row in dimensions(document, rows[0])) else "선택 객체에 지원하는 직접 치수가 없습니다."
    for row in rows:
        if any("parameter_id" in value or value.get("value_si") is None for _, coordinates in point_fields(row) for value in coordinates):
            return "위치가 미정이거나 매개변수에 연결되어 있습니다. 해당 속성/매개변수를 편집하십시오."
        angles = [row["start_angle"]] if row["kind"] == "arc_path" else []
        if row["kind"] == "arc_path" and operation == "mirror":
            angles.append(row["sweep_angle"])
        if row["kind"] == "pad" and row["pad_shape"] == "rectangle":
            angles.append(row["rotation"])
        if any("parameter_id" in value or value.get("value_si") is None for value in angles):
            return "변환 각도가 미정이거나 매개변수에 연결되어 있습니다. 해당 매개변수를 편집하십시오."
    return ""


def parameter_copies(document, objects):
    """! @brief 선택 객체가 참조한 매개변수와 표현식 의존 사본만 추출한다."""
    pending = []

    def visit(value):
        """! @brief 기하 원본의 제한 JSON 트리에서 참조를 읽는다."""
        if type(value) is dict:
            if set(value) == {"parameter_id"}:
                pending.append(value["parameter_id"])
            else:
                for child in value.values():
                    visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)

    visit(objects)
    result = {}
    while pending:
        identity = pending.pop()
        if identity in result:
            continue
        record = document["parameters"].get(identity)
        if record is None:
            fail("의존 매개변수가 없습니다.", "selection_ids", "E_CONFLICT")
        result[identity] = deepcopy(record)
        pending.extend(record.get("expression", {}).get("dependencies", []))
    return result


def _planar_objects(document, rows, operation, values, origin_id):
    """! @brief 명시 연산 결과에 새 UUID를 주고 모든 입력의 출처 사본을 따로 보존한다."""
    operands = [{"outer": [point(document, item) for item in row["outer"]],
                 "holes": [[point(document, item) for item in hole] for hole in row["holes"]]} for row in rows]
    shapes, engine = operate(operands, operation, values)
    sources = []
    for row in rows:
        for _, coordinates in point_fields(row):
            for quantity in coordinates:
                sources.extend(quantity.get("source_refs", []))
    sources = list(dict.fromkeys(sources))
    if len(sources) > 128:
        fail("결과 좌표의 합친 출처가 128개 상한을 초과했습니다.", "selection_ids", "E_RESOURCE")
    result = []
    for index, shape in enumerate(shapes):
        output = deepcopy(rows[0])
        output["id"] = str(uuid5(UUID(origin_id), "geometry:" + str(index)))
        output["outer"] = [[Quantity.from_value(value, "mm", source_refs=sources).to_dict() for value in point] for point in shape["outer"]]
        output["holes"] = [[[Quantity.from_value(value, "mm", source_refs=sources).to_dict() for value in point] for point in loop] for loop in shape["holes"]]
        output["name"] = allocate_name(document, output, reserved=[item["name"] for item in result])
        result.append(output)
    return result, engine


def replacements(document, rows, operation, values, origin_id):
    """! @brief 지원 범위만 실행하고 서비스 검토 전에 원본을 변경하지 않는다."""
    reason = operation_reason(document, rows, operation)
    if reason:
        fail(reason, "selection_ids", "E_CONFLICT")
    engine = {"name": "rfad.precision", "version": "0.1", "available": True, "reason": ""}
    if operation in PLANAR_OPERATIONS:
        return _planar_objects(document, rows, operation, values, origin_id)
    if operation == "dimension_set":
        return [set_dimension(document, rows[0], values["dimension_key"], values["value"], values["unit"])], engine
    if operation == "bind_dimension":
        _uuid(values["parameter_id"], "parameter_id")
        return [bind_dimension(document, rows[0], values["dimension_key"], values["parameter_id"])], engine
    return [transform(document, row, operation, values) for row in rows], engine


def item_label(document, item):
    """! @brief 기존 편집기의 객체 표시 이름 규칙을 재사용한다."""
    return object_label(document, item)
