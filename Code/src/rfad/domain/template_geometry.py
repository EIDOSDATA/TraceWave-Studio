"""! @brief 원호/평면 IFA의 명시 기하를 매개변수와 기존 설계 객체로 생성한다."""

from copy import deepcopy
import math
from uuid import UUID, uuid5

from rfad.domain.design import _fail, _fields, _uuid, resolve_scalar
from rfad.domain.parameter_graph import evaluate_parameters, expression_record
from rfad.domain.units import Quantity
from rfad.templates.cards import ARC, IFA
from rfad.templates.g031 import IDENTITY as G031
from rfad.templates import printed_references as printed


_DERIVED_LABELS = {"arc_start_x": "원호 시작 X", "arc_start_y": "원호 시작 Y", "ground_right": "접지 오른쪽 X",
                   "ground_top": "접지 위쪽 Y", "radiator_end_x": "방사 가지 끝 X", "pad_rotation": "패드 회전각",
                   "placed_center_x": "배치 원호 중심 X", "placed_center_y": "배치 원호 중심 Y",
                   "placed_feed_start_x": "배치 stub 시작 X", "placed_feed_start_y": "배치 stub 시작 Y",
                   "placed_feed_end_x": "배치 stub 끝 X", "placed_feed_end_y": "배치 stub 끝 Y",
                   "mono_left": "모노폴 왼쪽 X", "mono_right": "모노폴 오른쪽 X", "mono_tip": "모노폴 끝 Y",
                   "arm_right": "수평 가지 오른쪽 X", "arm_bottom": "수평 가지 아래 Y", "arm_top": "수평 가지 위 Y",
                   "short_right": "단락 가지 오른쪽 X", "feed_left": "급전 가지 왼쪽 X", "feed_right": "급전 가지 오른쪽 X"}


def parameter_roles(card: dict) -> list[str]:
    """! @brief 표시 이름과 무관한 고정 생성 역할로 ID 대응을 검사한다."""
    if card["template_id"] in printed.IDENTITIES:
        derived = (("mono_left", "mono_right", "mono_tip") if card["template_id"] == printed.MONOPOLE else
                   ("arm_right", "arm_bottom", "arm_top", "short_right", "feed_left", "feed_right"))
    elif card["template_id"] == G031:
        derived = tuple("placed_" + key for key in ("center_x", "center_y", "feed_start_x", "feed_start_y", "feed_end_x", "feed_end_y"))
    else:
        derived = ("arc_start_x", "arc_start_y") if card["template_id"] == ARC else ("ground_right", "ground_top", "radiator_end_x", "pad_rotation")
    return [*(item["key"] for item in card["input_fields"]), *derived]


def object_id(instance_id: str, role: str) -> str:
    """! @brief 인스턴스와 의미 역할로 안정적인 생성 객체 UUID를 계산한다."""
    return str(uuid5(UUID(instance_id), role))


def all_ids(document: dict) -> set[str]:
    """! @brief 프로젝트의 서로 다른 객체 종류를 포함한 충돌 집합을 만든다."""
    identities = {document["project_id"], document["revision_id"], *document["parent_revision_ids"], *document["parameters"]}
    identities.update(frame["id"] for frame in document["frames"].values())
    if document["board"] is not None:
        identities.add(document["board"]["id"])
    for collection in ("materials", "stackup", "nets", "geometry", "ports", "targets"):
        identities.update(item["id"] for item in document[collection])
    identities.update(item["revision_id"] for item in document["targets"])
    return identities


def literal(document: dict, value: object, dimension: str, field: str) -> float:
    """! @brief 명시 기하 입력의 literal SI 값만 소비하고 미정/참조를 추정하지 않는다."""
    if type(value) is dict and "parameter_id" in value:
        _fail("E_UNSUPPORTED", "템플릿 초기 입력은 literal Quantity만 지원합니다.", field)
    quantity = resolve_scalar(document, value, dimension, field)
    if quantity.value_si is None:
        _fail("E_GEOMETRY", "후보 생성에 필요한 치수가 미정입니다.", field)
    return quantity.value_si


def validate_binding(document: dict, binding: object, card: dict) -> None:
    """! @brief 기존 보드/좌표계/도체층에만 생성하며 물성을 채우지 않는다."""
    _fields(binding, {"board_id", "frame_id", "layer_id", "material_id"}, "binding")
    board = document["board"]
    if board is None or binding["board_id"] != board["id"] or binding["frame_id"] != board["frame_id"]:
        _fail("E_CONFLICT", "선택한 기존 보드와 좌표계가 다릅니다.", "binding.board_id")
    if board["outline"]["kind"] not in card["board_kinds"]:
        _fail("E_UNSUPPORTED", "이 템플릿이 지원하지 않는 보드 외곽입니다.", "binding.board_id")
    _uuid(binding["layer_id"], "binding.layer_id")
    layer = next((item for item in document["stackup"] if item["id"] == binding["layer_id"]), None)
    if layer is None or layer["role"] != "conductor":
        _fail("E_CONFLICT", "기존 도체 층을 선택하십시오.", "binding.layer_id")
    if binding["material_id"] is not None:
        _uuid(binding["material_id"], "binding.material_id")
        if not any(item["id"] == binding["material_id"] for item in document["materials"]):
            _fail("E_CONFLICT", "지정한 재료가 프로젝트에 없습니다.", "binding.material_id")


def _inside(document: dict, point: tuple[float, float], margin: float, field: str) -> None:
    """! @brief round cap 여유까지 실제 원형/직사각 외곽에 포함되는지 검사한다."""
    outline = document["board"]["outline"]
    if outline["kind"] == "rectangle":
        width = resolve_scalar(document, outline["width"], "length", "board.outline.width").value_si
        height = resolve_scalar(document, outline["height"], "length", "board.outline.height").value_si
        if width is None or height is None:
            _fail("E_GEOMETRY", "보드 외곽 치수가 미정입니다.", "board.outline")
        valid = margin <= point[0] <= width - margin and margin <= point[1] <= height - margin
    else:
        center = [resolve_scalar(document, value, "length", "board.outline.center").value_si for value in outline["center"]]
        radius = resolve_scalar(document, outline["radius"], "length", "board.outline.radius").value_si
        if radius is None or None in center:
            _fail("E_GEOMETRY", "원형 보드 외곽 치수가 미정입니다.", "board.outline")
        valid = math.hypot(point[0] - center[0], point[1] - center[1]) + margin <= radius + 1e-12
    if not valid:
        _fail("E_GEOMETRY", "생성 패턴과 선폭이 실제 보드 외곽을 벗어납니다.", field)


def _on_arc(angle: float, start: float, sweep: float) -> bool:
    """! @brief signed sweep 방향을 보존하여 극값 각도가 열린 원호 구간에 있는지 확인한다."""
    return ((angle - start) if sweep > 0 else (start - angle)) % math.tau <= abs(sweep) + 1e-12


def validate_arc_envelope(document, cx, cy, radius, start, sweep, width):
    """! @brief 기하 카드 종류와 무관하게 원호 극값과 round cap의 실제 외곽을 검사한다."""
    angles = [start, start + sweep]
    angles.extend(angle for angle in (0, math.pi / 2, math.pi, 3 * math.pi / 2) if _on_arc(angle, start, sweep))
    outline = document["board"]["outline"]
    if outline["kind"] == "circle":
        center = [resolve_scalar(document, item, "length", "board.outline.center").value_si for item in outline["center"]]
        if None in center:
            _fail("E_GEOMETRY", "원형 보드 중심이 미정입니다.", "board.outline.center")
        farthest = math.atan2(cy - center[1], cx - center[0])
        if _on_arc(farthest, start, sweep):
            angles.append(farthest)
    for angle in angles:
        _inside(document, (cx + radius * math.cos(angle), cy + radius * math.sin(angle)), width / 2, "explicit_inputs.radius")


class _Builder:
    """! @brief 입력별 stable parameter와 기하식 DAG를 연결하는 일회성 생성기다."""

    def __init__(self, document, instance_id, binding, card, inputs):
        """! @brief 원본과 입력을 변경하지 않고 생성 영역을 분리한다."""
        self.document, self.instance_id, self.binding = document, instance_id, binding
        prefix = (card["evidence"]["geometry_id"] + " " if card["template_id"] in printed.IDENTITIES else
                  ("G031 " if card["template_id"] == G031 else ("원호 " if card["template_id"] == ARC else "IFA ")))
        self.label_prefix = prefix + instance_id[:8] + " / "
        self.parameters, self.geometry, self.values = {}, [], {}
        descriptors = {item["key"]: item for item in card["input_fields"]}
        _fields(inputs, set(descriptors), "explicit_inputs")
        for key, descriptor in descriptors.items():
            self.values[key] = literal(document, inputs[key], descriptor["dimension"], "explicit_inputs." + key)
            identity = self.identity("parameter:" + key)
            self.parameters[identity] = {"id": identity, "name": self.label_prefix + descriptor["label"], "quantity": deepcopy(inputs[key])}
        self.net = {"id": self.identity("net"), "name": "template:" + instance_id}

    def identity(self, role):
        """! @brief 같은 후보 요청이 같은 객체 ID를 사용하도록 한다."""
        return object_id(self.instance_id, role)

    def ref(self, key):
        """! @brief geometry에 입력 Quantity 복제 대신 매개변수 참조를 둔다."""
        return {"parameter_id": self.identity("parameter:" + key)}

    def point(self, x, y):
        """! @brief 평면 좌표의 두 parameter 참조를 생성한다."""
        return [self.ref(x), self.ref(y)]

    def derived(self, key, expression, bindings, *, dimension="length", unit="mm"):
        """! @brief 좌표 유도식을 기존 표현식 엔진의 명시 DAG로 저장한다."""
        identity = self.identity("parameter:" + key)
        self.parameters[identity] = {
            "id": identity, "name": self.label_prefix + _DERIVED_LABELS[key],
            "quantity": Quantity.missing(dimension, unit).to_dict(),
            "expression": expression_record(expression, {name: self.identity("parameter:" + role) for name, role in bindings.items()}),
        }

    def shape(self, role, kind, **values):
        """! @brief 실제 도체 layer/net과 출처 ID를 가진 기존 geometry 객체를 만든다."""
        result = {"id": self.identity(role), "kind": kind, "role": role,
                  "frame_id": self.binding["frame_id"], "layer_id": self.binding["layer_id"],
                  "net_id": self.net["id"], "material_ref": self.binding["material_id"],
                  "source_ref": "template:" + self.instance_id, "include_in_em": True, "include_in_export": True, **values}
        self.geometry.append(result)
        return result

    def line(self, role, start, end, width):
        """! @brief 별도 의미 역할의 유한 폭 선을 만든다."""
        return self.shape(role, "line_path", start=self.point(*start), end=self.point(*end), width=self.ref(width))

    def positive(self, *names):
        """! @brief 길이/폭의 양수 정의역을 clamp 없이 검사한다."""
        for key in names:
            if self.values[key] <= 0:
                _fail("E_GEOMETRY", "길이와 폭은 양수여야 합니다.", "explicit_inputs." + key)


def _arc(builder):
    """! @brief 원호 극값과 feed 연결을 검사하고 정확한 기하식을 생성한다."""
    v = builder.values
    builder.positive("radius", "width", "feed_width")
    if v["radius"] <= v["width"] / 2 or not 0 < abs(v["sweep_angle"]) < math.tau:
        _fail("E_GEOMETRY", "원호는 양의 inner radius와 0/360도 사이 signed sweep가 필요합니다.", "explicit_inputs.sweep_angle")
    cx, cy, radius, start, sweep = (v[key] for key in ("center_x", "center_y", "radius", "start_angle", "sweep_angle"))
    validate_arc_envelope(builder.document, cx, cy, radius, start, sweep, v["width"])
    end = (cx + radius * math.cos(start), cy + radius * math.sin(start))
    feed = (v["feed_start_x"], v["feed_start_y"])
    if math.dist(feed, end) <= 1e-12:
        _fail("E_GEOMETRY", "급전 선의 시작과 원호 연결점이 같습니다.", "explicit_inputs.feed_start_x")
    for point in (feed, end):
        _inside(builder.document, point, v["feed_width"] / 2, "explicit_inputs.feed_start_x")
    builder.derived("arc_start_x", "c + r * cos(a)", {"c": "center_x", "r": "radius", "a": "start_angle"})
    builder.derived("arc_start_y", "c + r * sin(a)", {"c": "center_y", "r": "radius", "a": "start_angle"})
    builder.shape("radiator", "arc_path", center=builder.point("center_x", "center_y"), radius=builder.ref("radius"),
                  start_angle=builder.ref("start_angle"), sweep_angle=builder.ref("sweep_angle"), width=builder.ref("width"))
    builder.line("feed", ("feed_start_x", "feed_start_y"), ("arc_start_x", "arc_start_y"), "feed_width")


def _ifa(builder):
    """! @brief 접지/단락/급전이 분리된 명시 IFA의 평면 연결 조건을 검사한다."""
    v = builder.values
    builder.positive("ground_width", "ground_height", "radiator_length", "trace_width", "pad_width", "pad_height")
    left, bottom = v["ground_left"], v["ground_bottom"]
    right, top = left + v["ground_width"], bottom + v["ground_height"]
    radiator_end = v["radiator_start_x"] + v["radiator_length"]
    half = v["trace_width"] / 2
    if not left + half <= v["short_x"] <= right - half or not bottom <= v["short_start_y"] <= top:
        _fail("E_CONNECTIVITY", "단락 가지의 시작이 유한 접지에 연결되지 않습니다.", "explicit_inputs.short_start_y")
    if not all(v["radiator_start_x"] <= v[key] <= radiator_end for key in ("short_x", "feed_x")):
        _fail("E_CONNECTIVITY", "단락과 급전 가지가 방사 가지에 연결되지 않습니다.", "explicit_inputs.radiator_start_x")
    if (v["radiator_y"] - half <= top or v["feed_start_y"] - max(v["pad_height"] / 2, half) <= top
            or v["feed_start_y"] >= v["radiator_y"] or v["short_start_y"] >= v["radiator_y"]):
        _fail("E_CONNECTIVITY", "방사체/급전 패드와 접지 사이에 양의 gap이 필요합니다.", "explicit_inputs.feed_start_y")
    if abs(v["feed_x"] - v["short_x"]) <= max(v["trace_width"], (v["pad_width"] + v["trace_width"]) / 2):
        _fail("E_CONNECTIVITY", "급전 패드가 단락 가지에 직접 닿습니다.", "explicit_inputs.feed_x")
    for point in ((left, bottom), (right, bottom), (right, top), (left, top)):
        _inside(builder.document, point, 0, "explicit_inputs.ground_width")
    for point in ((v["radiator_start_x"], v["radiator_y"]), (radiator_end, v["radiator_y"]),
                  (v["short_x"], v["short_start_y"]), (v["short_x"], v["radiator_y"]),
                  (v["feed_x"], v["feed_start_y"]), (v["feed_x"], v["radiator_y"])):
        _inside(builder.document, point, half, "explicit_inputs.radiator_length")
    for dx in (-1, 1):
        for dy in (-1, 1):
            _inside(builder.document, (v["feed_x"] + dx * v["pad_width"] / 2, v["feed_start_y"] + dy * v["pad_height"] / 2), 0, "explicit_inputs.pad_width")
    builder.derived("ground_right", "a + b", {"a": "ground_left", "b": "ground_width"})
    builder.derived("ground_top", "a + b", {"a": "ground_bottom", "b": "ground_height"})
    builder.derived("radiator_end_x", "a + b", {"a": "radiator_start_x", "b": "radiator_length"})
    builder.derived("pad_rotation", "0 deg", {}, dimension="angle", unit="deg")
    builder.shape("ground", "planar_region", outer=[builder.point(*keys) for keys in (
        ("ground_left", "ground_bottom"), ("ground_right", "ground_bottom"), ("ground_right", "ground_top"), ("ground_left", "ground_top"))], holes=[])
    builder.line("radiator", ("radiator_start_x", "radiator_y"), ("radiator_end_x", "radiator_y"), "trace_width")
    builder.line("short", ("short_x", "short_start_y"), ("short_x", "radiator_y"), "trace_width")
    builder.line("feed", ("feed_x", "feed_start_y"), ("feed_x", "radiator_y"), "trace_width")
    pad = builder.shape("pad", "pad", pad_shape="rectangle", center=builder.point("feed_x", "feed_start_y"),
                        size=[builder.ref("pad_width"), builder.ref("pad_height")], rotation=builder.ref("pad_rotation"))
    pad["role"] = "feed"


def generate_geometry(document: dict, instance_id: str, binding: dict, card: dict, inputs: dict) -> dict:
    """! @brief 기존 프로젝트를 변경하지 않고 매개변수/네트/기하의 작은 patch를 만든다."""
    _uuid(instance_id, "instance_id")
    validate_binding(document, binding, card)
    builder = _Builder(document, instance_id, binding, card, inputs)
    if card["template_id"] == ARC:
        _arc(builder)
    elif card["template_id"] == IFA:
        _ifa(builder)
    elif card["template_id"] == G031:
        from rfad.domain.literature_geometry import generate_g031
        generate_g031(builder)
    elif card["template_id"] in printed.IDENTITIES:
        from rfad.domain.printed_geometry import generate_printed
        generate_printed(builder, card["template_id"])
    else:
        _fail("E_UNSUPPORTED", "기하 생성기를 찾을 수 없습니다.", "template.template_id")
    evaluate_parameters(builder.parameters, update=True)
    additions = {"parameters": builder.parameters, "nets": [builder.net],
                 "geometry": sorted(builder.geometry, key=lambda item: item["id"]), "ports": []}
    identities = [*builder.parameters, builder.net["id"], *(item["id"] for item in builder.geometry), instance_id]
    if len(set(identities)) != len(identities) or set(identities) & all_ids(document):
        _fail("E_CONFLICT", "생성할 객체 UUID가 기존 객체와 충돌합니다.", "instance_id")
    return additions
