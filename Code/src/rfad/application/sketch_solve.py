"""! @brief 저장 구동 치수와 기하 관계의 전체 잔차로 평면 스케치 좌표를 함께 구한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash
from rfad.application.sketch_analysis import FIELDS, _append, _external_dimensions, _matrix, _observed, label
from rfad.domain import sketch_constraints as sketch
from rfad.domain.precision_transform import MAX_COORDINATE_MM, replace_literal


def dimensions(document, model, group):
    """! @brief 직접 편집할 수 있는 구동 관계의 행 번호와 표시 단위를 돌려준다."""
    for index, row in enumerate(group["constraints"]):
        if "value" in row:
            angular = row["kind"] == "angle" or row.get("field") in sketch.ANGULAR
            yield {"index": index, "label": label(document, model, row), "unit": "deg" if angular else "mm",
                   "value": math.degrees(row["value"]) if angular else row["value"]}


def _step(rows, residual, size):
    """! @brief 감쇠 항을 둔 QR 회전으로 과소 또는 과잉 결정 선형화의 최소 제곱 증분을 구한다."""
    upper = [[0.0] * size for _ in range(size)]
    rhs = [0.0] * size
    for index in range(size):
        upper[index][index] = 1e-5
    for row, value in zip(rows, residual):
        vector, target = list(row), -value
        for index, lower in enumerate(vector):
            if lower == 0:
                continue
            pivot = upper[index]
            scale = math.hypot(pivot[index], lower)
            cosine, sine = pivot[index] / scale, lower / scale
            pivot[index] = scale
            for col in range(index + 1, size):
                a, b = pivot[col], vector[col]
                pivot[col], vector[col] = cosine * a + sine * b, cosine * b - sine * a
            a = rhs[index]
            rhs[index], target = cosine * a + sine * target, cosine * target - sine * a
    for index in reversed(range(size)):
        row = upper[index]
        rhs[index] = (rhs[index] - math.fsum(row[col] * rhs[col] for col in range(index + 1, size))) / row[index]
    return rhs


def _valid(model, selected):
    """! @brief 선분과 원호의 붕괴를 피하고 편집 좌표 한계를 확인한다."""
    for identity in selected:
        v, row = model.values[identity], model.geometry[identity]
        if any(not math.isfinite(value) or abs(value) > MAX_COORDINATE_MM
               for key, value in v.items() if key not in sketch.ANGULAR):
            return False
        if row["kind"] == "line_path" and math.hypot(v["ex"] - v["sx"], v["ey"] - v["sy"]) <= sketch.TOLERANCE:
            return False
        if row["kind"] == "arc_path" and (v["radius"] <= sketch.TOLERANCE or not sketch.TOLERANCE < abs(v["sweep"]) <= math.tau):
            return False
    return True


def _jacobian(model, variables, equations):
    """! @brief 각 기하 관계의 모든 성분을 같은 변수 순서로 적층한다."""
    return [vector for row in equations for vector in _matrix(model, variables, row)]


def _dof(jacobian, size):
    """! @brief 같은 좌표에서 독립 방정식의 수를 제외한 자유도를 계산한다."""
    basis = []
    _append(basis, jacobian)
    return size - len(basis)


def _geometry_edits(document, model, selected, original):
    """! @brief 최종 좌표가 달라진 원본 수량만 바꾸고 역명령에 쓸 행을 함께 돌려준다."""
    geometry, view = [], []
    for identity in selected:
        old = model.geometry[identity]
        new = deepcopy(old)
        for field, key, index in sketch.SHAPES[old["kind"]]:
            if field not in model.values[identity]:
                continue
            before, after = original[identity][field], model.values[identity][field]
            if abs(after - before) <= sketch.TOLERANCE / 100:
                continue
            angular = field in sketch.ANGULAR
            if angular:
                before, after = math.degrees(before), math.degrees(after)
            unit = "deg" if angular else "mm"
            updated = replace_literal(document, model.raw[identity][field], after, unit, "geometry." + identity)
            if index is None:
                new[key] = updated
            else:
                new[key][index] = updated
            view.append({"id": identity, "name": old.get("name", identity), "field": FIELDS[field],
                         "before": before, "after": after, "unit": unit})
        if old != new:
            geometry.append({"before": old, "after": new})
    return geometry, view


def solve(document, group, edits):
    """! @brief 원래 급전과 모든 저장 관계를 유지하며 선택한 그룹의 구동 치수들을 동시에 편집한다."""
    model = sketch.Model(document)
    replacement = deepcopy(group)
    selected = group["selection_ids"]
    dims = {row["index"]: row for row in dimensions(document, model, group)}
    for edit in edits:
        index = edit["index"]
        if index not in dims:
            sketch.fail("구동 치수가 있는 행을 선택하세요.", "edits", "E_SCHEMA")
        target = edit["value"]
        row = replacement["constraints"][index]
        if abs(target) > MAX_COORDINATE_MM or (row["kind"] == "length" or row.get("field") == "radius") and target <= sketch.TOLERANCE:
            sketch.fail("구동 치수의 유효 범위를 확인하세요.", "edits", "E_GEOMETRY")
        if target != dims[index]["value"]:
            row["value"] = math.radians(target) if dims[index]["unit"] == "deg" else target
    if replacement == group:
        sketch.fail("바꿀 구동 치수를 입력하세요.", "edits", "E_CONFLICT")
    equations = _external_dimensions(document, model, selected)
    observed, issues = _observed(model, selected)
    equations.extend(observed)
    for original_group in sketch.groups(document):
        current = replacement if original_group["id"] == group["id"] else original_group
        equations.extend(row for row in (*current["constraints"], *current["protected"])
                         if any(ref["id"] in selected for ref in row["refs"]))
    equations = list({canonical_hash(row): row for row in equations}.values())
    original = deepcopy(model.values)
    variables = [(identity, field) for identity in selected for field in model.values[identity]
                 if "parameter_id" not in model.raw[identity][field]]

    def errors():
        """! @brief 원래 단위의 전체 잔차를 선형화와 같은 순서로 읽는다."""
        return [value for row in equations for value in model.residual(row)]

    residual = errors()
    jacobian = _jacobian(model, variables, equations)
    before = _dof(jacobian, len(variables))
    iterations = 0
    while not issues and variables and max(map(abs, residual)) > sketch.TOLERANCE / 10 and iterations < 48:
        delta = _step(jacobian, residual, len(variables))
        initial = [model.values[i][key] for i, key in variables]
        norm = math.hypot(*residual)
        for division in range(14):
            for (identity, key), first, move in zip(variables, initial, delta):
                model.values[identity][key] = first + move * 0.5**division
            if _valid(model, selected):
                candidate = errors()
                if math.hypot(*candidate) < norm:
                    residual = candidate
                    break
        else:
            for (identity, key), first in zip(variables, initial):
                model.values[identity][key] = first
            break
        iterations += 1
        jacobian = _jacobian(model, variables, equations)
    conflicts = [*issues, *(label(document, model, row) for row in equations
                            if max(map(abs, model.residual(row))) > sketch.TOLERANCE)]
    summary = {"variables": len(variables), "before": before, "after": _dof(jacobian, len(variables)),
               "iterations": iterations, "max_residual": max(map(abs, residual)), "proposals": [],
               "existing": [], "conflicts": conflicts, "geometry_changes": []}
    if conflicts:
        return summary, None, []
    geometry, summary["geometry_changes"] = _geometry_edits(document, model, selected, original)
    return summary, replacement, geometry
