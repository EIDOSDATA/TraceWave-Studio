"""! @brief 보존 기하에서 독립적인 스케치 구속과 적용 전후 국소 자유도를 계산한다."""

from itertools import combinations
import math

from rfad.application.canonical import canonical_hash
from rfad.domain import sketch_constraints as sketch
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import object_label
from rfad.domain.precision_command import EXTENSION_KEY as PRECISION_KEY
from rfad.domain.units import Quantity, QuantityError


POINTS = {"start": "시작점", "end": "끝점", "center": "중심"}
LABELS = {"fixed": "기준점 고정", "offset": "기준점과의 거리", "scalar": "치수 고정",
          "length": "선 길이", "angle": "기준축과의 각도", "parallel": "기준축과 평행",
          "perpendicular": "기준축과 수직", "coincident": "점 일치", "point_on_line": "선 위의 점",
          "midpoint": "선분 중점", "tangent": "접선", "contact": "급전 접촉",
          "equal_length": "두 선의 동일 길이", "equal_radius": "두 원호의 동일 반경",
          "concentric": "두 원호의 동심", "lines_parallel": "두 선의 평행",
          "lines_perpendicular": "두 선의 직교", "mirror_points": "기준축 대칭점"}
FIELDS = {"radius": "원호 반경", "start": "원호 시작각", "sweep": "원호 회전량", "rotation": "패드 회전각",
          "sx": "시작점 X", "sy": "시작점 Y", "ex": "끝점 X", "ey": "끝점 Y", "cx": "중심 X", "cy": "중심 Y"}


def label(document, geometry, row):
    """! @brief 기준 UUID를 표시 이름에 붙여 원인을 실제 형상으로 연결한다."""
    kind = row["kind"]
    name = FIELDS.get(row.get("field"), LABELS[kind])
    names = [object_label(document, geometry.geometry[ref["id"]]) for ref in row["refs"]]
    if kind == "contact":
        port = geometry.ports[row["port_id"]]["name"]
        terminal = "기준단" if row["end"] == "start" else "신호단"
        return f"{name} / {port} {terminal} / {names[0]}"
    if kind in ("length", "parallel", "perpendicular", "angle"):
        items = names[0]
    elif kind in ("equal_length", "equal_radius", "lines_parallel", "lines_perpendicular", "concentric"):
        items = " / ".join(names)
    elif kind in ("point_on_line", "midpoint"):
        items = names[0] + " " + POINTS[row["refs"][0]["point"]] + " / " + names[1] + " 선분"
    else:
        items = " / ".join(name + " " + POINTS[ref["point"]] for name, ref in zip(names, row["refs"]))
    value = row.get("value")
    if value is not None:
        angular = kind == "angle" or row.get("field") in sketch.ANGULAR
        if abs(value) < sketch.TOLERANCE:
            value = 0
        text = f"{math.degrees(value):.9g} deg" if angular else f"{value:.9g} mm"
        name += " " + text
    if "axis" in row:
        name += " / " + row["axis"].upper()
    return name + " / " + items


def _matrix(model, variables, row):
    """! @brief 같은 원본 점에서 독립 방정식의 중심 차분 행을 만든다."""
    participating = {ref["id"] for ref in row["refs"]}
    initial = model.residual(row)
    columns = []
    for key, field in variables:
        if key not in participating:
            columns.append([0.0] * len(initial))
            continue
        shape = model.values[key]
        old = shape[field]
        step = 1e-6 if field in sketch.ANGULAR else 1e-5
        if "sx" in shape:
            step = min(step, math.hypot(shape["ex"] - shape["sx"], shape["ey"] - shape["sy"]) / 8)
        elif field in ("radius", "sweep"):
            step = min(step, abs(old) / 8)
        upper, lower = old + step, old - step
        if upper == lower:
            sketch.fail("현재 수량의 정밀도로 스케치 자유도를 계산할 수 없습니다.", "selection_ids", "E_RESOURCE")
        try:
            shape[field] = upper
            plus = model.residual(row)
            shape[field] = lower
            minus = model.residual(row)
        finally:
            shape[field] = old
        columns.append([(a - b) / (upper - lower) for a, b in zip(plus, minus)])
    return list(zip(*columns))


def _append(basis, rows):
    """! @brief 다른 구속으로 이미 결정된 행을 세지 않고 독립 랭크만 증가시킨다."""
    for row in rows:
        norm = math.hypot(*row)
        if norm <= 1e-9:
            continue
        vector = [value / norm for value in row]
        for _ in range(2):
            for old in basis:
                dot = math.fsum(a * b for a, b in zip(vector, old))
                vector = [a - dot * b for a, b in zip(vector, old)]
        length = math.hypot(*vector)
        if length > 1e-7:
            basis.append([value / length for value in vector])


def _proper_point(model, identity):
    """! @brief 중심이나 시작점을 치수 표시의 기본 기준점으로 사용한다."""
    kind = model.shape(identity)["kind"]
    return sketch.anchor(identity, "start" if kind == "line_path" else "center")


def _external_dimensions(document, model, selected, shared_radii=(), *, skip_group=None):
    """! @brief 기본 반경·회전량, 매개변수 결합과 원본에서 재확인한 정밀 길이 및 반경을 읽는다."""
    rows = []
    linked = {ref["id"] for group in sketch.groups(document) if group["id"] != skip_group
              for row in group["constraints"]
              if row["kind"] == "equal_radius" for ref in row["refs"]}
    linked.update(shared_radii)
    for identity in selected:
        shape = model.shape(identity)
        ref = _proper_point(model, identity)
        for field, value in model.raw[identity].items():
            if ("parameter_id" in value or shape["kind"] == "arc_path"
                    and (field == "sweep" or field == "radius" and identity not in linked)):
                rows.append(sketch.relation("scalar", ref, field=field, value=model.values[identity][field]))
    tracked = {}
    for record in document["extensions"].get(PRECISION_KEY, {}).get("records", []):
        values = record["values"]
        key = values.get("dimension_key")
        if record["operation"] != "dimension_set" or key not in ("line.length", "arc.radius"):
            continue
        try:
            mm = Quantity.from_value(values["value"], values["unit"]).as_unit("mm")
        except (KeyError, QuantityError, ValueError, TypeError, OverflowError):
            continue
        for identity in record["selection_ids"]:
            if identity not in selected:
                continue
            shape = model.shape(identity)
            ref = _proper_point(model, identity)
            if key == "line.length" and shape["kind"] == "line_path":
                row = sketch.relation("length", ref, value=mm)
            elif key == "arc.radius" and shape["kind"] == "arc_path":
                row = sketch.relation("scalar", ref, field="radius", value=mm)
            else:
                continue
            if abs(model.residual(row)[0]) <= sketch.TOLERANCE:
                tracked[identity] = row
    return rows + list(tracked.values())


def _observed(model, selected):
    """! @brief 원래 성립하는 점 일치, 접선과 급전 경계를 선택 형상 주변에서 읽는다."""
    found, issues = [], []
    endpoints = {}
    for identity, shape in model.geometry.items():
        if shape["kind"] not in ("line_path", "arc_path", "pad"):
            continue
        try:
            names = ("center",) if shape["kind"] == "pad" else ("start", "end")
            endpoints[identity] = [(ref, model.location(ref)) for ref in
                                   (sketch.anchor(identity, key) for key in names)]
        except ProjectError:
            if identity in selected:
                raise
    identities = sorted(endpoints)
    for index, first in enumerate(identities):
        a = model.geometry[first]
        for second in identities[index + 1:]:
            if first not in selected and second not in selected:
                continue
            b = model.geometry[second]
            if (a["frame_id"], a["layer_id"], a["net_id"]) != (b["frame_id"], b["layer_id"], b["net_id"]):
                continue
            for ref, left in endpoints[first]:
                for other, right in endpoints[second]:
                    if math.dist(left, right) > sketch.TOLERANCE:
                        continue
                    found.append(sketch.relation("coincident", ref, other))
                    if a["kind"] != "pad" and b["kind"] != "pad" and "arc_path" in (a["kind"], b["kind"]):
                        tangent = sketch.relation("tangent", ref, other)
                        if abs(model.residual(tangent)[0]) <= sketch.TOLERANCE:
                            found.append(tangent)
            for source, destination in ((first, second), (second, first)):
                if model.geometry[destination]["kind"] != "line_path":
                    continue
                line = sketch.anchor(destination, "start")
                for ref, _ in endpoints[source]:
                    position, length, distance = model.line_position(ref, line)
                    if sketch.TOLERANCE < position < length - sketch.TOLERANCE and abs(distance) <= sketch.TOLERANCE:
                        found.append(sketch.relation("point_on_line", ref, line))
    for identity, port in model.ports.items():
        for end, key in (("start", "reference_geometry_id"), ("stop", "positive_geometry_id")):
            if port[key] not in selected:
                continue
            if port["direction"][2] != 0:
                # @brief 수직 포트의 접촉 자유도는 평면 스케치에서 감산하지 않는다.
                issues.append("수직 급전 단자는 평면 스케치 선택에서 제외하세요.")
                continue
            row = sketch.relation("contact", _proper_point(model, port[key]), port_id=identity, end=end)
            try:
                if abs(model.residual(row)[0]) > sketch.TOLERANCE:
                    issues.append("선택한 도체와 기존 급전 경계가 맞닿아 있지 않습니다.")
                else:
                    found.append(row)
            except ProjectError as error:
                issues.append(error.message)
    return found, list(dict.fromkeys(issues))


def _paired_rows(model, selected, datum, axis):
    """! @brief 두 선택 형상의 관계와 별도 기준점을 통과하는 축 대칭을 제안한다."""
    for left, right in combinations(sorted(selected), 2):
        a, b = _proper_point(model, left), _proper_point(model, right)
        kinds = model.geometry[left]["kind"], model.geometry[right]["kind"]
        if kinds == ("line_path", "line_path"):
            for kind in ("equal_length", "lines_parallel", "lines_perpendicular"):
                yield sketch.relation(kind, a, b)
        elif kinds == ("arc_path", "arc_path"):
            for kind in ("concentric", "equal_radius"):
                yield sketch.relation(kind, a, b)
        if datum["id"] in (left, right):
            continue
        for lp in sketch.ANCHORS[kinds[0]]:
            for rp in sketch.ANCHORS[kinds[1]]:
                lref, rref = sketch.anchor(left, lp), sketch.anchor(right, rp)
                if math.dist(model.location(lref), model.location(rref)) <= sketch.TOLERANCE:
                    continue
                row = sketch.relation("mirror_points", lref, rref, datum, axis=axis)
                if max(map(abs, model.residual(row))) <= sketch.TOLERANCE:
                    yield row


def _proposal_rows(model, selected, datum, axis):
    """! @brief 같은 원본을 유지할 수 있는 치수와 사용자 기준축의 방향 후보를 낸다."""
    origin = model.location(datum)
    axes = (axis, "y" if axis == "x" else "x")
    for direction in axes:
        index = 0 if direction == "x" else 1
        yield sketch.relation("fixed", datum, axis=direction, value=origin[index])
    for identity in selected:
        shape = model.shape(identity)
        first = _proper_point(model, identity)
        if shape["kind"] == "line_path":
            yield sketch.relation("parallel", first, axis=axis)
            yield sketch.relation("perpendicular", first, axis=axis)
            angle = model.orientation(first) - (0 if axis == "x" else math.pi / 2)
            yield sketch.relation("angle", first, axis=axis, value=math.remainder(angle, math.tau))
            length = math.dist(model.location(first), model.location(sketch.anchor(identity, "end")))
            yield sketch.relation("length", first, value=length)
        elif shape["kind"] == "arc_path":
            yield sketch.relation("scalar", first, field="start", value=model.values[identity]["start"])
        elif "rotation" in model.values[identity]:
            yield sketch.relation("scalar", first, field="rotation", value=model.values[identity]["rotation"])
        if first != datum:
            location = model.location(first)
            for direction in axes:
                index = 0 if direction == "x" else 1
                yield sketch.relation("offset", first, datum, axis=direction, value=location[index] - origin[index])


def analyze(document, setup, requested=None, *, skip_group=None):
    """! @brief 사용자 선택을 적용하기 전후의 독립 랭크, 중복 및 모순을 대조한다."""
    model = sketch.Model(document)
    selected_ids = setup["selection_ids"]
    selected = set(selected_ids)
    for identity in selected_ids:
        model.shape(identity)
    variables = [(identity, field) for identity in selected_ids for field in model.values[identity]]
    observed, issues = _observed(model, selected)
    existing = {}
    paired = list(_paired_rows(model, selected_ids, setup["datum"], setup["axis"])) if len(selected_ids) <= 3 else []
    requested_ids = set(requested or ())
    shared_radii = {ref["id"] for row in paired if row["kind"] == "equal_radius"
                    and canonical_hash(row) in requested_ids for ref in row["refs"]}
    preserved = list(observed)
    for group in sketch.groups(document):
        if group["id"] == skip_group:
            continue
        for row in [*group["constraints"], *group["protected"]]:
            if any(ref["id"] in selected for ref in row["refs"]):
                preserved.append(row)
    for row in [*_external_dimensions(document, model, selected, shared_radii, skip_group=skip_group), *preserved]:
        existing[canonical_hash(row)] = row
    basis = []
    for row in existing.values():
        _append(basis, _matrix(model, variables, row))
    size = len(variables)
    previous_basis = basis.copy()
    if shared_radii:
        # @brief 적용 전 자유도는 사용자가 공유 반경을 선택하기 전의 독립 반경 치수도 포함한다.
        for row in _external_dimensions(document, model, selected, skip_group=skip_group):
            if canonical_hash(row) not in existing:
                _append(previous_basis, _matrix(model, variables, row))
    before = size - len(previous_basis)
    rows, plan, used = [], [], set()

    def can_share_radius(relation):
        """! @brief 해당 쌍의 기본 반경만 해제하고 실제 남는 구속에서 관계가 독립인지 검사한다."""
        released = shared_radii | {ref["id"] for ref in relation["refs"]}
        dimensions = _external_dimensions(document, model, selected, released, skip_group=skip_group)
        alternate = []
        for equation in [*dimensions, *preserved, *plan]:
            _append(alternate, _matrix(model, variables, equation))
        rank = len(alternate)
        _append(alternate, _matrix(model, variables, relation))
        return len(alternate) > rank

    radial_dimensions = [sketch.relation("scalar", _proper_point(model, key), field="radius",
                                         value=model.values[key]["radius"]) for key in sorted(shared_radii)]
    for row in [*paired, *radial_dimensions, *_proposal_rows(model, selected_ids, setup["datum"], setup["axis"])]:
        identity = canonical_hash(row)
        used.add(identity)
        name = label(document, model, row)
        chosen = requested is not None and identity in requested
        candidate = basis.copy()
        if max(map(abs, model.residual(row))) > sketch.TOLERANCE:
            state = "conflict"
            reason = "현재 형상의 치수나 방향과 맞지 않습니다."
        else:
            _append(candidate, _matrix(model, variables, row))
            independent = len(candidate) > len(basis)
            if not independent and row["kind"] == "equal_radius" and not chosen and identity not in existing:
                independent = can_share_radius(row)
            state = "available" if independent else "redundant"
            reason = "" if state == "available" else "기존 치수 또는 앞선 선택과 중복됩니다."
        if state == "available" and (chosen or requested is None and row not in paired):
            state = "selected"
            chosen = True
            plan.append(row)
            basis = candidate
        elif chosen:
            issues.append(name + " / " + reason)
        rows.append({"id": identity, "label": name, "state": state, "selected": chosen, "reason": reason})
    if requested is not None and not set(requested).issubset(used):
        sketch.fail("선택한 제안이 현재 기준과 다릅니다. 다시 검토하세요.", "requested", "E_CONFLICT")
    return {"variables": size, "before": before, "after": size - len(basis), "proposals": rows,
            "existing": [label(document, model, row) for row in existing.values()], "conflicts": issues}, plan, observed
