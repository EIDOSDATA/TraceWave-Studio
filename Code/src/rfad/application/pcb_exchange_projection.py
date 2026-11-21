"""! @brief PCB 원문을 바꾸지 않고 기계/제조/풋프린트 표시와 교환용 SI 투영을 만든다."""

from copy import deepcopy
import math

from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names
from rfad.domain.pcb_features import empty_pcb, owner_map, fail


def scalar(document, value, dimension="length"):
    """! @brief 미정 상태는 null로 유지하며 표시용 mm/deg만 서비스에서 계산한다."""
    quantity = resolve_scalar(document, value, dimension)
    if quantity.value_si is None:
        return None
    output = quantity.as_unit({"length": "mm", "angle": "deg", "dimensionless": "1"}[dimension])
    if not math.isfinite(output) or (dimension == "length" and abs(output) > 1e6):
        fail("PCB 투영의 유한 좌표 범위를 벗어났습니다.", "shape", "E_RESOURCE")
    return output


def point(document, value):
    """! @brief 두 좌표 중 미정이 있어도 다른 원문 값을 대체하지 않는다."""
    return [scalar(document, item) for item in value]


def shape_projection(document, shape):
    """! @brief 순서/방향과 원점이 있는 해석형 경계를 그대로 투영한다."""
    kind = shape["kind"]
    if kind == "polygon":
        return {"kind": kind, "outer_mm": [point(document, item) for item in shape["outer"]],
                "holes_mm": [[point(document, item) for item in loop] for loop in shape["holes"]]}
    output = {"kind": kind, "center_mm": point(document, shape["center"])}
    if kind == "circle":
        output["diameter_mm"] = scalar(document, shape["diameter"])
    else:
        output["rotation_deg"] = scalar(document, shape["rotation"], "angle")
        if kind == "rectangle":
            output["size_mm"] = point(document, shape["size"])
        else:
            output.update(finished_length_mm=scalar(document, shape["finished_length"]),
                          finished_width_mm=scalar(document, shape["finished_width"]))
    return output


def mechanical_projection(document):
    """! @brief 공구를 완성 홀에서 추정하지 않고 공통 CAD/도면 기계 입력을 반환한다."""
    result = {"cutouts": [], "holes": []}
    for row in (document.get("board") or {}).get("cutouts", []):
        result["cutouts"].append({"id": row["id"], "shape": shape_projection(document, row["shape"]),
                                   "surface_cut_ids": deepcopy(row["surface_cut_ids"])})
    for row in document.get("pcb", empty_pcb())["holes"]:
        result["holes"].append({"id": row["id"], "shape": shape_projection(document, row["shape"]),
            "surface_cut_ids": deepcopy(row["surface_cut_ids"]), "tool_diameter_mm": scalar(document, row["tool_diameter"]),
            "plating": {**{key: deepcopy(row["plating"][key]) for key in ("state", "material_ref", "net_id", "pad_ids")},
                        "thickness_mm": scalar(document, row["plating"]["thickness"])}})
    return result


def aperture_projection(document, row):
    """! @brief 패드 기반 개구의 비율/여유값을 명시 입력에서 계산하며 미정을 보존한다."""
    definition = row["definition"]
    if definition["mode"] == "explicit_shape":
        return shape_projection(document, definition["shape"])
    pad = next(item for item in document["geometry"] if item["id"] == definition["pad_id"])
    margin = scalar(document, definition["margin"])
    ratio = scalar(document, definition["size_ratio"], "dimensionless")
    sizes = point(document, pad["size"])
    resolved = [None if item is None or margin is None or ratio is None else item * (1.0 + ratio) + 2.0 * margin for item in sizes]
    if any(item is not None and (not math.isfinite(item) or item <= 0 or item > 1e6) for item in resolved):
        fail("패드 비율과 여유값으로 만든 개구의 폭/높이가 양의 유한값이 아닙니다.", "definition", "E_GEOMETRY")
    result = {"kind": "circle" if pad["pad_shape"] == "circle" else "rectangle", "center_mm": point(document, pad["center"])}
    if result["kind"] == "circle":
        result["diameter_mm"] = resolved[0]
    else:
        result.update(size_mm=resolved, rotation_deg=scalar(document, pad["rotation"], "angle"))
    return result


def _missing(value):
    """! @brief 해석형 투영의 null을 렌더 불가 상태로 보존한다."""
    return value is None or (type(value) is dict and any(_missing(item) for item in value.values())) or (type(value) is list and any(_missing(item) for item in value))


def feature_scene(document):
    """! @brief 비도체 객체를 가짜 도체층 없이 별도 선택 종류로 표시한다."""
    output, owners = [], owner_map(document)
    model = document.get("pcb", empty_pcb())
    collections = [("cutout", (document.get("board") or {}).get("cutouts", [])), *[(key, model[value]) for key, value in
                   (("hole", "holes"), ("keepout", "keepouts"), ("aperture", "apertures"), ("footprint", "footprints"))]]
    for kind, rows in collections:
        for row in rows:
            shape = None
            error = None
            try:
                if kind == "aperture":
                    shape = aperture_projection(document, row)
                elif kind == "footprint":
                    shape = None if row["placement_envelope"] is None else shape_projection(document, row["placement_envelope"])
                else:
                    shape = shape_projection(document, row["shape"])
            except ProjectError as caught:
                error = {"code": caught.code, "message_ko": caught.message}
            output.append({"id": row["id"], "kind": kind, "owner_footprint_id": owners.get((kind + "s", row["id"])),
                           "shape_mm": shape, "source_label": row["name"], "missing": _missing(shape), "diagnostic": error})
    return output


def exchange_projection(document, snapshot):
    """! @brief native package 없이 원본 사본 하나와 공통 evaluated 도체/기계/제조 입력을 만든다."""
    from rfad.application.cad import build_cad_input
    cad = build_cad_input(document, snapshot)
    model = document.get("pcb", empty_pcb())
    labels = display_names(document)
    result = {"schema": "rfad.pcb-projection/0.1", "snapshot": deepcopy(snapshot), "source_semantics": deepcopy(document),
              **{key: deepcopy(cad[key]) for key in ("board", "layers", "shapes")}, "mechanical": mechanical_projection(document),
              "footprints": [], "artwork_layers": deepcopy(model["artwork_layers"]), "apertures": [], "keepouts": [],
              "names": {row["id"]: labels[row["id"]] for row in document["geometry"]}, "diagnostics": deepcopy(cad["omissions"])}
    for row in model["footprints"]:
        result["footprints"].append({**{key: deepcopy(value) for key, value in row.items() if key not in ("placement", "placement_envelope")},
            "placement": {"origin_mm": point(document, row["placement"]["origin"]),
                          "rotation_deg": scalar(document, row["placement"]["rotation"], "angle"), "side": row["placement"]["side"]},
            "placement_envelope": None if row["placement_envelope"] is None else shape_projection(document, row["placement_envelope"])})
    for row in model["apertures"]:
        result["apertures"].append({**{key: deepcopy(value) for key, value in row.items() if key != "definition"},
                                    "shape": aperture_projection(document, row), "definition": deepcopy(row["definition"])})
    for row in model["keepouts"]:
        result["keepouts"].append({**{key: deepcopy(value) for key, value in row.items() if key != "shape"},
                                   "shape": shape_projection(document, row["shape"])})
    for key in ("holes", "footprints", "artwork_layers", "apertures", "keepouts"):
        result["names"].update({row["id"]: row["name"] for row in model[key]})
    result["names"].update({row["id"]: row["name"] for row in (document.get("board") or {}).get("cutouts", [])})
    result["materials"] = {row["id"]: {"id": row["id"], "name": row["name"], "model": row["model"],
        "epsilon_r": resolve_scalar(document, row["epsilon_r"], "dimensionless").value_si,
        "loss_tangent": resolve_scalar(document, row["tan_delta"], "dimensionless").value_si,
        "conductivity_s_per_m": resolve_scalar(document, row["conductivity"], "conductivity").value_si,
        "validity_hz": {key: resolve_scalar(document, value, "frequency").value_si for key, value in row["validity_hz"].items()},
        "states": {key: resolve_scalar(document, row[key], "conductivity" if key == "conductivity" else "dimensionless").status.value for key in ("epsilon_r", "tan_delta", "conductivity")}}
        for row in document["materials"]}
    return result


def geometry_projection(document, row):
    """! @brief DRC에 적층/재료 CAD 목적 검증을 끌어오지 않고 실제 도체 좌표만 해석한다."""
    result = {key: deepcopy(row[key]) for key in ("id", "kind", "layer_id", "net_id")}
    for name in ("center", "start", "end", "size"):
        if name in row:
            result[name + "_mm"] = point(document, row[name])
    for name in ("radius", "width", "finished_hole_diameter", "plating_thickness", "tool_hole_diameter"):
        if name in row:
            result[name + "_mm"] = scalar(document, row[name])
    for name in ("rotation", "start_angle", "sweep_angle"):
        if name in row:
            result[name + "_deg"] = scalar(document, row[name], "angle")
    for name in ("pad_shape", "pad_ids", "end_layer_id"):
        if name in row:
            result[name] = deepcopy(row[name])
    if row["kind"] == "planar_region":
        result.update(outer_mm=[point(document, item) for item in row["outer"]],
                      holes_mm=[[point(document, item) for item in loop] for loop in row["holes"]])
    return result


def _signed_area(loop):
    """! @brief 해석형 Green 적분으로 절삭 후 양의 외곽 성분 수를 구분한다."""
    terms = []
    for edge in loop:
        if edge["kind"] == "line":
            a, b = edge["start"], edge["end"]
            terms.append((a[0] * b[1] - a[1] * b[0]) / 2)
        else:
            start = math.radians(edge["start_deg"])
            sweep = math.radians(edge["sweep_deg"])
            stop, radius = start + sweep, edge["radius"]
            cx, cy = edge["center"]
            terms.append((radius * cx * (math.sin(stop) - math.sin(start)) - radius * cy * (math.cos(stop) - math.cos(start)) + radius * radius * sweep) / 2)
    return math.fsum(terms)


def _footprint_from_loops(row, loops):
    """! @brief 도면의 해석형 경계로 동일한 거리 및 재료 내부 판정을 만든다."""
    from rfad.domain.boundary_distance import Arc, Segment
    from rfad.domain.check_geometry import Footprint
    from rfad.domain.drawing_layout import _inside

    edges = [Segment(tuple(edge["start"]), tuple(edge["end"])) if edge["kind"] == "line" else
             Arc(tuple(edge["center"]), edge["radius"], math.radians(edge["start_deg"] + min(0, edge["sweep_deg"])),
                 math.radians(abs(edge["sweep_deg"]))) for loop in loops for edge in loop]
    return Footprint(row, edges, lambda value: _inside(value, loops), None)


def _local_mechanical(mechanical, copper):
    """! @brief 떨어진 절삭을 도체에서 빼지 않으며 미정이거나 접하는 경계는 원래 검사를 사용한다."""
    from rfad.domain.check_geometry import separation
    from rfad.domain.drawing_layout import mechanical_loops, number

    result, budget = {"cutouts": [], "holes": []}, [200000]
    for key, records in mechanical.items():
        for row in records:
            offset = 0.0
            plating = row.get("plating")
            if plating is not None:
                if plating["state"] not in ("plated", "unplated"):
                    result[key].append(row)
                    continue
                if plating["state"] == "plated":
                    offset = number(plating["thickness_mm"], positive=True)
            cutter = _footprint_from_loops(row, mechanical_loops(row["shape"], offset))
            guard = max(copper.guard, cutter.guard)
            a, b = copper.bounds, cutter.bounds
            lower = max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])
            if lower <= guard and separation(copper, cutter, budget)[0] <= guard:
                result[key].append(row)
    return result


def effective_footprint(document, row, original):
    """! @brief 기계 제거 후 경계로 DRC를 수행하며 분리된 객체를 연결 하나로 가장하지 않는다."""
    mechanical = _local_mechanical(mechanical_projection(document), original)
    if not mechanical["holes"] and not mechanical["cutouts"]:
        return original
    from rfad.domain.drawing_layout import shape_loops, _mechanical_removed
    projection = {"mechanical": mechanical}
    loops = _mechanical_removed(shape_loops(geometry_projection(document, row)), projection)
    if sum(_signed_area(loop) > 0 for loop in loops) != 1:
        fail("기계 절삭으로 나뉜 한 원본의 여러 도체 섬은 객체 단위 연결 검사에서 미평가입니다.", "geometry." + row["id"], "E_CHECK_UNSUPPORTED")
    return _footprint_from_loops(row, loops)


def extra_diagnostics(document, shapes, report):
    """! @brief 새 제조/배치 규칙과 실제 수직 접합의 미평가 범위를 분리해 기록한다."""
    from rfad.domain.drawing_layout import mechanical_loops
    from rfad.domain.check_geometry import separation
    def footprint_of(row, shape):
        """! @brief 명시 형상은 동일 해석형 경계 거리 엔진으로 비교한다."""
        return _footprint_from_loops(row, mechanical_loops(shape))
    model = document.get("pcb", empty_pcb())
    budget = [200000]
    orders = {layer["id"]: layer["order"] for layer in document["stackup"] if layer["role"] == "conductor"}
    for row in model["holes"]:
        if row["plating"]["state"] != "unplated":
            report.add("mechanical_plated_connectivity", "not_evaluated", "새 도금 홀/슬롯의 수직 접합은 전용 native 검수와 별도 평가가 필요합니다.", objects=[row["id"]], paths=["pcb.holes"])
    for row in model["keepouts"]:
        try:
            guard = footprint_of(row, shape_projection(document, row["shape"]))
            selected_layers = orders if row.get("all_conductor_layers") else row["layer_ids"]
            selected_orders = {orders[identity] for identity in selected_layers}
            candidates = []
            for shape in shapes.values():
                role = {"line_path": "tracks", "arc_path": "tracks", "pad": "pads", "via": "vias", "planar_region": "copper_pours"}[shape.source["kind"]]
                start = orders.get(shape.source["layer_id"])
                stop = orders.get(shape.source.get("end_layer_id"), start)
                if start is not None and any(start <= order <= stop for order in selected_orders) and row["prohibit"][role]:
                    candidates.append(shape)
            if row["prohibit"]["footprints"]:
                for owner in model["footprints"]:
                    if owner["placement_envelope"] is None:
                        report.add("footprint_keepout", "not_evaluated", "풋프린트 배치 외곽이 미정입니다. 패드 크기로 추정하지 않습니다.", objects=[row["id"], owner["id"]], paths=["pcb.footprints.placement_envelope"])
                    else:
                        candidates.append(footprint_of(owner, shape_projection(document, owner["placement_envelope"])))
            for candidate in candidates:
                distance, left, right = separation(guard, candidate, budget)
                status = "failed" if distance == 0 else "not_evaluated" if distance <= max(guard.guard, candidate.guard) else "passed"
                report.add("pcb_keepout", status,
                           "금지 영역을 침범했습니다." if status == "failed" else "명시 금지 영역과 실제 제거 후 경계를 비교했습니다.",
                           objects=[row["id"], candidate.source["id"]], paths=["pcb.keepouts." + row["id"]],
                           measured=distance, limit=0.0, location=list(left),
                           details={"scope": "all_conductors" if row.get("all_conductor_layers") else "selected_layers"})
        except ProjectError as error:
            report.add("pcb_keepout", "not_evaluated", error.message, objects=[row["id"]], paths=["pcb.keepouts"])
