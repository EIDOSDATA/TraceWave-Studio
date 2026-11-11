"""! @brief 적층 적용이 기존 패턴, 비아와 포트에 미치는 영향을 검토한다."""

from copy import deepcopy
import math

from rfad.application.pcb_selection_contract import number, text
from rfad.application.pcb_selection_layers import decision, length
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.design import preflight_design, resolve_scalar
from rfad.domain.errors import ProjectError


def issue(code, message, *, blocker=False, **context):
    """! @brief 적용 불가와 후속 CAD/해석 검사 필요를 구분한다."""
    return {"code": code, "severity": "blocker" if blocker else "warning", "message": message, **context}


def update_ports(document, entries):
    """! @brief 사용자가 명시한 급전 상자만 바꾸고 포트 의미와 ID는 보존한다."""
    if type(entries) is not list or len(entries) > 8:
        raise ProjectError("E_SCHEMA", "포트 좌표 변경은 최대 8개 목록이어야 합니다.")
    ports = deepcopy(document["ports"])
    indexed = {item["id"]: item for item in ports}
    seen, decisions = set(), []
    for entry in entries:
        _fields(entry, {"id", "start_mm", "stop_mm", "reason"})
        identity = _uuid(entry["id"])
        if identity not in indexed or identity in seen:
            raise ProjectError("E_SCHEMA", "포트 변경 ID가 없거나 중복됩니다.")
        reason = text(entry["reason"], "port_updates.reason", maximum=1024)
        box = {}
        missing = False
        for endpoint in ("start", "stop"):
            values = entry[endpoint + "_mm"]
            if type(values) is not list or len(values) != 3:
                raise ProjectError("E_SCHEMA", "급전 좌표는 명시적 mm 값 또는 미정값 3개입니다.")
            values = [number(value, "port_updates." + endpoint, nullable=True) for value in values]
            missing |= None in values
            box[endpoint] = [length(value) for value in values]
        indexed[identity]["excitation_box"] = box
        decisions.append(decision(identity, "excitation_box", box, "missing" if missing else "user_override",
                                  reason, collection="ports"))
        seen.add(identity)
    return ports, decisions, seen


def _interval(document, layer):
    """! @brief 매개변수 결합도 현재 개정의 실제 SI 값으로 비교한다."""
    return tuple(resolve_scalar(document, layer[field], "length", "stackup." + layer["id"] + "." + field).value_si
                 for field in ("z_min", "thickness"))


def _same_interval(left, right):
    """! @brief 자료 표현만 다른 미세 부동소수점 차이는 이동으로 표시하지 않는다."""
    return all(a is b if a is None or b is None else math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
               for a, b in zip(left, right))


def _surface(document, layer, layers):
    """! @brief 현재 외측 sheet 모델의 유일한 유전체 접면만 판별한다."""
    lower, thickness = _interval(document, layer)
    if lower is None or thickness is None:
        return None
    surfaces = []
    for other in layers.values():
        if other["role"] != "dielectric":
            continue
        bottom, height = _interval(document, other)
        if bottom is None or height is None:
            continue
        if math.isclose(lower, bottom + height, rel_tol=0, abs_tol=1e-11):
            surfaces.append(lower)
        if math.isclose(lower + thickness, bottom, rel_tol=0, abs_tol=1e-11):
            surfaces.append(lower + thickness)
    return surfaces[0] if len(surfaces) == 1 else None


def review_references(before, after, updated_ports):
    """! @brief 층 위치 변경을 숨기지 않고 급전 좌표 재지정과 비아 span 검토를 요구한다."""
    old_layers = {layer["id"]: layer for layer in before["stackup"]}
    layers = {layer["id"]: layer for layer in after["stackup"]}
    moved = {identity for identity in old_layers.keys() & layers.keys()
             if not _same_interval(_interval(before, old_layers[identity]), _interval(after, layers[identity]))}
    geometry = {item["id"]: item for item in after["geometry"]}
    issues = []
    for shape in geometry.values():
        if shape["kind"] == "via" and {shape["layer_id"], shape["end_layer_id"]} & moved:
            issues.append(issue("via_span_changed", "비아의 층 간 span이 변경됩니다. 끝층과 패드 참조를 보존하며 CAD 접촉 검사가 추가로 필요합니다.",
                                object_id=shape["id"]))
    for port in after["ports"]:
        attached = [geometry[port[key]] for key in ("reference_geometry_id", "positive_geometry_id")]
        affected = any(shape["layer_id"] in moved for shape in attached)
        if affected and "excitation_box" in port and port["id"] not in updated_ports:
            issues.append(issue("port_coordinates_require_review", "급전 도체의 z 위치/두께가 바뀝니다. port_updates에 급전 좌표와 이유를 명시하십시오.",
                                blocker=True, object_id=port["id"]))
        if port["id"] in updated_ports:
            for endpoint, shape in zip(("start", "stop"), attached):
                surface = _surface(after, layers[shape["layer_id"]], layers)
                point = port["excitation_box"][endpoint]
                z = resolve_scalar(after, point[2], "length", "ports.excitation_box").value_si
                if surface is not None and z is not None and not math.isclose(z, surface, rel_tol=0, abs_tol=1e-11):
                    issues.append(issue("port_not_on_selected_layer", "명시한 급전 z 좌표가 새 적층의 유전체/도체 접면과 다릅니다.",
                                        blocker=True, object_id=port["id"], endpoint=endpoint))
                elif surface is None or z is None:
                    issues.append(issue("port_surface_unresolved", "미정 치수 또는 미지원 sheet 접면입니다. 급전의 해석 유효성은 아직 확인되지 않았습니다.",
                                        object_id=port["id"]))
    return issues, sorted(moved)


def describe_changes(before, after, moved):
    """! @brief 전체 객체 대신 실제 변경 ID와 유지되는 원본 경계를 보여준다."""
    changes = {"moved_layers": moved, "board_preserved": before["board"] == after["board"],
               "geometry_preserved": before["geometry"] == after["geometry"], "nets_preserved": before["nets"] == after["nets"]}
    for collection in ("materials", "stackup", "ports"):
        old = {item["id"]: item for item in before[collection]}
        new = {item["id"]: item for item in after[collection]}
        changes[collection] = {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
                               "changed": sorted(key for key in new.keys() & old.keys() if new[key] != old[key])}
    return changes


def input_checks(document):
    """! @brief 기존 목적별 입력 검사 결과를 해석 준비 완료와 분리해 반환한다."""
    result = {}
    for purpose in ("geometry", "step", "em"):
        diagnostics = preflight_design(document, purpose)
        result[purpose] = {"input_status": "valid" if not diagnostics else "incomplete",
                           "diagnostic_count": len(diagnostics), "diagnostics": diagnostics[:16],
                           "diagnostics_truncated": len(diagnostics) > 16}
    result["solver_ready"] = False
    return result
