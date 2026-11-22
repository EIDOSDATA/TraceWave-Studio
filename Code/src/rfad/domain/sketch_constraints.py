"""! @brief 기판 평면 스케치의 안정 기준과 보존할 기하 관계를 검증한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_bytes
from rfad.domain.design import _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.layer_surface import single_dielectric_contact
from rfad.domain.object_names import validate_name
from rfad.domain.precision_transform import fail, number, point, scalar


KEY = "rfad.sketch-constraints"
PROFILE = "rfad.sketch-constraints/0.1"
COMMAND = "sketch.constraints.replace"
TOLERANCE = 1e-7
MAX_GROUPS = 16
MAX_SELECTION = 12
MAX_RELATIONS = 512
SHAPES = {
    "line_path": (("sx", "start", 0), ("sy", "start", 1), ("ex", "end", 0), ("ey", "end", 1)),
    "arc_path": (("cx", "center", 0), ("cy", "center", 1), ("radius", "radius", None),
                 ("start", "start_angle", None), ("sweep", "sweep_angle", None)),
    "pad": (("cx", "center", 0), ("cy", "center", 1), ("rotation", "rotation", None)),
}
ANCHORS = {"line_path": ("start", "end"), "arc_path": ("start", "end", "center"), "pad": ("center",)}
ANGULAR = {"start", "sweep", "rotation"}
SPEC = {
    "fixed": (1, {"axis", "value"}),
    "offset": (2, {"axis", "value"}),
    "scalar": (1, {"field", "value"}),
    "length": (1, {"value"}),
    "angle": (1, {"axis", "value"}),
    "parallel": (1, {"axis"}),
    "perpendicular": (1, {"axis"}),
    "coincident": (2, set()),
    "point_on_line": (2, set()),
    "tangent": (2, set()),
    "contact": (1, {"port_id", "end"}),
}


def groups(document):
    """! @brief 과거 프로젝트는 빈 목록으로 열며 확장을 자동 삽입하지 않는다."""
    return document["extensions"].get(KEY, {}).get("groups", [])


def anchor(identity, point_name):
    """! @brief 현재 이름과 무관한 기준 객체 및 기하점 ID를 반환한다."""
    return {"id": identity, "point": point_name}


def validate_anchor(ref):
    """! @brief 안정 객체와 닫힌 기준점 종류만 받는다."""
    _fields(ref, {"id", "point"}, "sketch.anchor")
    _uuid(ref["id"], "sketch.anchor.id")
    if ref["point"] not in ("start", "end", "center"):
        fail("선택한 스케치 기준점 종류가 올바르지 않습니다.", "datum", "E_SCHEMA")


def relation(kind, *refs, **values):
    """! @brief 관계에 필요한 참조와 기준값만 보존한다."""
    return {"kind": kind, "refs": list(refs), **values}


def _validate_relation(row):
    """! @brief 저장한 관계의 종류와 값 경계를 대조한다."""
    kind = row.get("kind") if isinstance(row, dict) else None
    if not isinstance(kind, str) or kind not in SPEC:
        fail("지원하지 않는 스케치 관계입니다.", "constraints", "E_SCHEMA")
    count, extra = SPEC[kind]
    _fields(row, {"kind", "refs"} | extra, "sketch.relation")
    if type(row["refs"]) is not list or len(row["refs"]) != count:
        fail("관계의 기준점 수를 확인하세요.", "constraints", "E_SCHEMA")
    for ref in row["refs"]:
        validate_anchor(ref)
    if "value" in row:
        number(row["value"], "constraints.value")
    if "field" in row and (not isinstance(row["field"], str)
                           or row["field"] not in {key for fields in SHAPES.values() for key, _, _ in fields}):
        fail("지원하는 스케치 치수 필드를 선택하세요.", "constraints", "E_SCHEMA")
    if "axis" in row and row["axis"] not in ("x", "y"):
        fail("스케치 기준축은 X 또는 Y입니다.", "axis", "E_SCHEMA")
    if "port_id" in row:
        _uuid(row["port_id"], "constraints.port_id")
        if row["end"] not in ("start", "stop"):
            fail("급전의 기준단 또는 신호단을 선택하세요.", "constraints", "E_SCHEMA")


class Model:
    """! @brief 설계 원본과 분리한 평면 수량 및 기준점 평가를 제공한다."""

    def __init__(self, document):
        """! @brief 지워지거나 미정인 원본을 다른 형상으로 대체하지 않는다."""
        self.document = document
        self.geometry = {row["id"]: row for row in document["geometry"]}
        self.ports = {row["id"]: row for row in document["ports"]}
        self.values = {}
        self.raw = {}
        self.widths = {}

    def shape(self, identity):
        """! @brief 기판 좌표계의 유한한 원본 변수와 표시점만 읽는다."""
        row = self.geometry.get(identity)
        board = self.document["board"]
        if row is None or row["kind"] not in SHAPES or board is None or row["frame_id"] != board["frame_id"]:
            fail("같은 기판 좌표계의 선·원호·패드를 선택하세요.", "selection_ids", "E_CONFLICT")
        if identity not in self.values:
            fields = SHAPES[row["kind"]]
            if row["kind"] == "pad" and row["pad_shape"] == "circle":
                fields = fields[:2]
            raw = {key: row[name] if index is None else row[name][index] for key, name, index in fields}
            values = {key: scalar(self.document, value, "angle" if key in ANGULAR else "length",
                                  "rad" if key in ANGULAR else "mm", "geometry." + identity)
                      for key, value in raw.items()}
            if row["kind"] == "line_path" and math.hypot(values["ex"] - values["sx"], values["ey"] - values["sy"]) <= TOLERANCE:
                fail("길이가 0인 선의 자유도를 계산할 수 없습니다.", "selection_ids", "E_CONFLICT")
            if row["kind"] == "arc_path" and (values["radius"] <= TOLERANCE or abs(values["sweep"]) <= TOLERANCE):
                fail("반경과 회전량이 유효한 원호가 필요합니다.", "selection_ids", "E_CONFLICT")
            self.raw[identity], self.values[identity] = raw, values
        return row

    def location(self, ref):
        """! @brief 원호 끝점은 현재 해석형 중심·반경·각에서 계산한다."""
        identity, name = ref["id"], ref["point"]
        row = self.shape(identity)
        v = self.values[identity]
        kind = row["kind"]
        if name not in ANCHORS[kind]:
            fail("기준점이 현재 형상에 없습니다.", "datum", "E_CONFLICT")
        if kind == "line_path":
            return (v["sx"], v["sy"]) if name == "start" else (v["ex"], v["ey"])
        if name == "center":
            return v["cx"], v["cy"]
        angle = v["start"] + (v["sweep"] if name == "end" else 0)
        return v["cx"] + v["radius"] * math.cos(angle), v["cy"] + v["radius"] * math.sin(angle)

    def size(self, identity):
        """! @brief 접촉 검사에는 기존 선폭과 패드의 원래 크기를 사용한다."""
        if identity not in self.widths:
            row = self.geometry[identity]
            if row["kind"] == "pad":
                self.widths[identity] = point(self.document, row["size"], "geometry.size")
            else:
                self.widths[identity] = [scalar(self.document, row["width"], field="geometry.width")]
        return self.widths[identity]

    def orientation(self, ref):
        """! @brief 선은 시작에서 끝 방향, 원호 끝점은 해석적 접선 방향을 평가한다."""
        identity = ref["id"]
        row = self.shape(identity)
        v = self.values[identity]
        if row["kind"] == "line_path":
            return math.atan2(v["ey"] - v["sy"], v["ex"] - v["sx"])
        if row["kind"] != "arc_path" or ref["point"] == "center":
            fail("접선에는 선 또는 원호의 끝점이 필요합니다.", "constraints", "E_SCHEMA")
        theta = v["start"] + (v["sweep"] if ref["point"] == "end" else 0)
        return theta + math.copysign(math.pi / 2, v["sweep"])

    def _contact(self, row):
        """! @brief 같은 급전 참조의 기존 XY 경계 접촉을 해석적으로 대조한다."""
        identity = row["refs"][0]["id"]
        port = self.ports.get(row["port_id"])
        end = row["end"]
        key = "reference_geometry_id" if end == "start" else "positive_geometry_id"
        if port is None or port[key] != identity or "excitation_box" not in port:
            fail("보존할 급전 단자가 변경되었거나 미정입니다.", "constraints", "E_CONFLICT")
        original = self.shape(identity)
        v = self.values[identity]
        start, stop = (point(self.document, port["excitation_box"][side], "ports." + port["id"])
                       for side in ("start", "stop"))
        layer = next(item for item in self.document["stackup"] if item["id"] == original["layer_id"])

        def level(item):
            """! @brief 실제 적층의 도체 접면을 판정할 높이와 두께다."""
            return tuple(scalar(self.document, item[key], field="stackup." + key) for key in ("z_min", "thickness"))

        surface = single_dielectric_contact(*level(layer),
            [level(item) for item in self.document["stackup"] if item["role"] == "dielectric"],
            tolerance=1e-8, field="stackup." + layer["id"])
        if abs(start[2] - stop[2]) > TOLERANCE or abs(start[2] - surface) > TOLERANCE:
            fail("보존할 급전이 실제 평면 도체 높이와 다릅니다.", "constraints", "E_CONFLICT")
        x, y = (start if end == "start" else stop)[:2]
        sizes = self.size(identity)
        if original["kind"] == "line_path":
            dx, dy = v["ex"] - v["sx"], v["ey"] - v["sy"]
            t = max(0, min(1, ((x - v["sx"]) * dx + (y - v["sy"]) * dy) / (dx * dx + dy * dy)))
            return math.hypot(x - v["sx"] - t * dx, y - v["sy"] - t * dy) - sizes[0] / 2
        dx, dy = x - v["cx"], y - v["cy"]
        if original["kind"] == "pad":
            if original["pad_shape"] == "circle":
                return math.hypot(dx, dy) - sizes[0] / 2
            cs, sn = math.cos(v["rotation"]), math.sin(v["rotation"])
            return max(abs(dx * cs + dy * sn) - sizes[0] / 2, abs(-dx * sn + dy * cs) - sizes[1] / 2)
        angle = ((math.atan2(dy, dx) - v["start"]) * math.copysign(1, v["sweep"])) % math.tau
        if angle <= abs(v["sweep"]):
            distance = abs(math.hypot(dx, dy) - v["radius"])
        else:
            distance = min(math.dist((x, y), self.location(anchor(identity, key))) for key in ("start", "end"))
        return distance - sizes[0] / 2

    def line_position(self, ref, line):
        """! @brief 실제 선분에 투영한 위치와 부호 있는 직교 거리를 반환한다."""
        identity = line["id"]
        if self.shape(identity)["kind"] != "line_path":
            fail("선 위의 점 관계에는 직선이 필요합니다.", "constraints", "E_SCHEMA")
        x, y = self.location(ref)
        v = self.values[identity]
        dx, dy = v["ex"] - v["sx"], v["ey"] - v["sy"]
        px, py = x - v["sx"], y - v["sy"]
        length = math.hypot(dx, dy)
        distance = (dx * py - dy * px) / length
        return (px * dx + py * dy) / length, length, distance

    def residual(self, row):
        """! @brief 각 보존 관계의 부호 있는 길이 또는 각 잔차를 반환한다."""
        kind = row["kind"]
        first = row["refs"][0]
        if kind == "contact":
            return (self._contact(row),)
        if kind == "scalar":
            self.shape(first["id"])
            value = self.values[first["id"]].get(row["field"])
            if value is None:
                fail("스케치 치수가 가리키는 필드가 없습니다.", "constraints", "E_CONFLICT")
            delta = value - row["value"]
            return (math.remainder(delta, math.tau) if row["field"] in ("start", "rotation") else delta,)
        if kind == "point_on_line":
            position, length, distance = self.line_position(first, row["refs"][1])
            outside = max(0, -position, position - length)
            return (math.hypot(outside, distance) if outside else distance,)
        if kind == "tangent":
            return (math.sin(self.orientation(first) - self.orientation(row["refs"][1])),)
        p = self.location(first)
        axis = 0 if row.get("axis") == "x" else 1
        if kind == "fixed":
            return (p[axis] - row["value"],)
        if kind in ("offset", "coincident"):
            q = self.location(row["refs"][1])
            if kind == "coincident":
                return p[0] - q[0], p[1] - q[1]
            return (p[axis] - q[axis] - row["value"],)
        shape = self.shape(first["id"])
        if shape["kind"] != "line_path":
            fail("선 길이와 축 관계에는 선을 선택하세요.", "constraints", "E_SCHEMA")
        v = self.values[first["id"]]
        dx, dy = v["ex"] - v["sx"], v["ey"] - v["sy"]
        if kind == "length":
            return (math.hypot(dx, dy) - row["value"],)
        if kind == "angle":
            return (math.remainder(math.atan2(dy, dx) - axis * math.pi / 2 - row["value"], math.tau),)
        return ((dx, dy)[axis if kind == "perpendicular" else 1 - axis],)


def validate(document):
    """! @brief 이후 직접 편집도 보존한 치수와 접촉 관계를 어길 수 없게 한다."""
    extension = document["extensions"].get(KEY)
    if extension is None:
        return
    _fields(extension, {"schema", "groups"}, KEY)
    rows = extension["groups"]
    if (extension["schema"] != PROFILE or type(rows) is not list or not 1 <= len(rows) <= MAX_GROUPS
            or len(canonical_bytes(extension)) > 96 * 1024):
        fail("스케치 관계의 버전 또는 저장 상한을 확인하세요.", KEY, "E_RESOURCE")
    geometry = Model(document)
    ids, count = [], 0
    for group in rows:
        _fields(group, {"id", "name", "selection_ids", "datum", "axis", "constraints", "protected"}, KEY)
        ids.append(_uuid(group["id"], KEY + ".id"))
        validate_name(group["name"], KEY + ".name")
        validate_setup(group)
        for identity in group["selection_ids"]:
            geometry.shape(identity)
        geometry.location(group["datum"])
        for key in ("constraints", "protected"):
            values = group[key]
            if type(values) is not list:
                fail("스케치 관계는 목록이어야 합니다.", KEY, "E_SCHEMA")
            count += len(values)
            if count > MAX_RELATIONS:
                fail("스케치 관계의 최대 저장 수를 초과했습니다.", KEY, "E_RESOURCE")
            for row in values:
                _validate_relation(row)
                if not any(ref["id"] in group["selection_ids"] for ref in row["refs"]):
                    fail("보존된 관계가 스케치 선택과 연결되어야 합니다.", "constraints", "E_SCHEMA")
                try:
                    for ref in row["refs"]:
                        geometry.location(ref)
                    residual = geometry.residual(row)
                except ProjectError as error:
                    fail(f"스케치 '{group['name']}'에서 {error.message}", "constraints", "E_CONFLICT")
                if max(map(abs, residual)) > TOLERANCE:
                    fail(f"스케치 '{group['name']}'의 보존 관계({row['kind']})와 충돌합니다. 구속을 확인하세요.",
                         "constraints", "E_CONFLICT")
    if ids != sorted(set(ids)):
        fail("스케치 구속 ID의 중복이나 순서를 확인하세요.", KEY, "E_HASH")


def validate_setup(data):
    """! @brief 선택과 기준점이 같은 제한 스케치에 속하는지 확인한다."""
    ids = data["selection_ids"]
    if type(ids) is not list or not 1 <= len(ids) <= MAX_SELECTION:
        fail("스케치에는 선·원호·패드 1~12개를 선택하세요.", "selection_ids", "E_RESOURCE")
    for identity in ids:
        _uuid(identity, "selection_ids")
    if len(ids) != len(set(ids)):
        fail("스케치 객체를 중복 선택했습니다.", "selection_ids", "E_CONFLICT")
    validate_anchor(data["datum"])
    if data["datum"]["id"] not in ids or data["axis"] not in ("x", "y"):
        fail("선택한 객체의 기준점과 X 또는 Y 기준축을 지정하세요.", "datum", "E_CONFLICT")


def apply(document, payload):
    """! @brief 관계 원본을 한 개정에 보존하고 취소에 쓸 정확한 역명령을 반환한다."""
    _fields(payload, {"id", "expected", "replacement"}, "command.payload")
    identity = _uuid(payload["id"], "command.id")
    existing = groups(document)
    old = next((row for row in existing if row["id"] == identity), None)
    replacement = payload["replacement"]
    if old != payload["expected"] or (replacement is None and old is None):
        fail("검토한 스케치 구속과 현재 원본이 다릅니다.", "id", "E_CONFLICT")
    if replacement is not None and (type(replacement) is not dict or replacement.get("id") != identity):
        fail("스케치 구속 ID가 원본과 다릅니다.", "id", "E_HASH")
    remaining = [row for row in existing if row["id"] != identity]
    if replacement is not None:
        remaining.append(deepcopy(replacement))
    if remaining:
        document["extensions"][KEY] = {"schema": PROFILE, "groups": sorted(remaining, key=lambda item: item["id"])}
    else:
        document["extensions"].pop(KEY, None)
    return [identity], ["revision", "sketch_constraints"], {"type": COMMAND, "payload": {
        "id": identity, "expected": deepcopy(replacement), "replacement": deepcopy(old)}}
