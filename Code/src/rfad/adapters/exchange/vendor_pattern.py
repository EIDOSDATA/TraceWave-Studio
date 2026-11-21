"""! @brief 해시가 확인된 제조사 원본을 교환 worker에서 읽는다."""

import hashlib
from io import BytesIO
from zipfile import ZipFile

from rfad.adapters.exchange.vendor_dxf import CHORD_ERROR_MM, read_renesas
from rfad.domain.errors import ProjectError
from rfad.domain.planar import MAX_REGION_HOLES, MAX_REGION_POINTS
from rfad.domain.vendor_catalog import VENDOR_FORMATS


SCHEMA = "rfad.vendor-pattern-read/0.1"

_WB003_COPPER = (
    ("Top", "top", "안테나", "minihoe_milling_top_antenna.gbr",
     "c66e6867f686e90dbd6e9cdc1de0b2ce9fc86d5ddadc1fbd57c2b06432978989"),
    ("Top", "top", "CPW 접지", "minihoe_milling_top_CPW_ground.gbr",
     "719f6de99b4c811bd73322105a90d1a6fa65cfc2611226213c63c2a49eea0264"),
    ("Bottom", "bottom", "하면 접지", "minihoe_milling_btm_ground.gbr",
     "96cd47f59e3949bebb4f98503c3da4aff0128dc0dca9c51cdd51a559a34036ab"),
)
_WB003_OUTLINE = ("minihoe_outline.gbr", "17bd374ca4843f0f550461402c2a72e8ab56d14f1dcbcb35726262f947d7d21e")
_WB003_HOLE = ("minihoe_via_hole.gbr", "9c6faba35c80de6fe57083098b884d0267d8e456dbc5c013e90d3763994ca2ec")


def _hash(raw):
    """! @brief 검토한 배포 원문만 카드와 연결한다."""
    return hashlib.sha256(raw).hexdigest()


def _member(raw, name, digest):
    """! @brief 고정 ZIP 멤버를 파일 시스템에 추출하지 않고 상한과 해시를 대조한다."""
    with ZipFile(BytesIO(raw)) as archive:
        entry = archive.getinfo(name)
        if entry.file_size > 1024 * 1024:
            raise ProjectError("E_RESOURCE", "공급사 ZIP 멤버가 읽기 상한을 초과했습니다.")
        member = archive.read(entry)
    if _hash(member) != digest:
        raise ProjectError("E_HASH", "공급사 ZIP 멤버가 검토한 원문 해시와 다릅니다.")
    return member


def _areas(shape):
    """! @brief 분할 결과에서 면적이 있는 단순 영역만 재귀적으로 반환한다."""
    if shape.geom_type == "Polygon":
        if not shape.is_empty:
            yield shape
    elif shape.geom_type in ("MultiPolygon", "GeometryCollection"):
        for child in shape.geoms:
            yield from _areas(child)


def _parts(polygon, depth=0):
    """! @brief 편집 정점 상한을 넘는 경계는 면적을 보존하는 직선 절단으로 분할한다."""
    from shapely import box
    loops = [polygon.exterior, *polygon.interiors]
    if (len(polygon.interiors) <= MAX_REGION_HOLES and
            sum(len(loop.coords) - 1 for loop in loops) <= MAX_REGION_POINTS):
        yield [[[float(x), float(y)] for x, y in list(loop.coords)[:-1]] for loop in loops]
        return
    if depth >= 8:
        raise ProjectError("E_RESOURCE", "공급사 동박이 편집 영역 분할 상한을 초과했습니다.")
    x, y, right, top = polygon.bounds
    if right - x >= top - y:
        middle = (x + right) / 2
        boxes = (box(x, y, middle, top), box(middle, y, right, top))
    else:
        middle = (y + top) / 2
        boxes = (box(x, y, right, middle), box(x, middle, right, top))
    for clip in boxes:
        for child in _areas(polygon.intersection(clip)):
            yield from _parts(child, depth + 1)


def _loss(code, message, **details):
    """! @brief 사용자가 원문 보존과 편집 범위 차이를 확인할 수 있게 한다."""
    return {"code": code, "message": message, "raw_preserved": True, **details}


def _wb003(raw):
    """! @brief WB003의 세 동박 원본을 분리하고 기준 외곽·비아 원문 정보도 남긴다."""
    from rfad.adapters.exchange.vendor_gerber import read_wb003
    regions, members, surfaces = [], [], {}
    for layer, side, label, path, digest in _WB003_COPPER:
        copper, closures = read_wb003(_member(raw, path, digest))
        surfaces[label] = copper
        members.append({"path": path, "sha256": digest, "role": label, "implicit_closures": closures})
        regions.extend((layer, side, label, path, polygon) for polygon in _areas(copper))
    outline, _ = read_wb003(_member(raw, *_WB003_OUTLINE))
    members.append({"path": _WB003_OUTLINE[0], "sha256": _WB003_OUTLINE[1], "role": "기준 외곽",
                    "bounds_mm": list(outline.bounds)})
    _member(raw, *_WB003_HOLE)
    members.append({"path": _WB003_HOLE[0], "sha256": _WB003_HOLE[1], "role": "비아 도면"})
    contact = surfaces["안테나"].intersection(surfaces["CPW 접지"])
    return regions, members, contact


def read_pattern(raw, format_name):
    """! @brief 선택한 카드의 정확한 원문과 도체 영역, 생략 조건을 반환한다."""
    card = VENDOR_FORMATS[format_name]
    digest = _hash(raw)
    if digest == card["archive_sha256"]:
        member = _member(raw, card["member"], card["sha256"])
    elif digest == card["sha256"]:
        member = raw
    else:
        raise ProjectError("E_HASH", "선택한 제조사 예제와 원문이 다릅니다. 해당 멤버 또는 공식 ZIP을 선택하십시오.")
    losses = [_loss("vendor_scope", "동박만 가져옵니다. 보드, 급전, 포트, 물성은 기존 값이 유지되며 새 도체의 해석 포함은 꺼져 있습니다.")]
    anchor = [0.0, 0.0]
    members = []
    if format_name == "vendor_qorvo_wb003":
        polygons, members, contact = _wb003(member)
        losses.extend([
            _loss("vendor_qorvo_wb003_outline_drill", "안테나와 두 접지 도체를 적용합니다. 외곽과 via 홀 도면은 원문으로 남기며 드릴, 도금, 층간 연결은 생성하지 않습니다."),
            _loss("vendor_qorvo_wb003_closure", "mm Gerber의 G37에서 열린 직선 윤곽을 시작점까지 닫고 clear 영역을 뺍니다.",
                  overlay_grid_mm=1e-7, source_unit="mm"),
        ])
        if not contact.is_empty:
            losses.append(_loss("vendor_qorvo_wb003_overlap",
                                "WB003 상면의 안테나 스텁과 CPW 접지의 원문 겹침을 유지합니다. 포트·넷이나 층간 연결은 추정하지 않습니다.",
                                overlap_mm2=round(contact.area, 9), bounds_mm=list(contact.bounds)))
    elif format_name.startswith("vendor_ti_"):
        from rfad.adapters.exchange.vendor_gerber import CHORD_MM, read_ti
        copper, macros = read_ti(member)
        anchor = list(copper.bounds[:2])
        polygons = [("Top", "top", "상부 동박", card["member"], region) for region in _areas(copper)]
        losses.extend([
            _loss("vendor_ti_independent_artwork", "SPL에 포함된 독립 상부 패턴만 적용합니다. 회로의 급전, 접지, 나머지 보드·층은 별도입니다."),
            _loss("vendor_gerber_area", "Gerber region과 aperture를 동박 면적으로 결합합니다. 원형 aperture 경계는 최대 현 오차 0.002 mm로 표현합니다.",
                  chord_error_mm=CHORD_MM, overlay_grid_mm=1e-7, source_unit="inch", macro_apertures=macros),
        ])
    else:
        copper, skipped, arcs = read_renesas(member)
        polygons = [(layer, side, layer, card["member"], polygon) for layer, side, polygon in copper]
        losses.append(_loss("vendor_dxf_layers", "패드·비아 블록, 마스크 및 풋프린트 표시 등 도체 경계 외 항목을 원문에 보존합니다.", layers=skipped))
        if arcs:
            losses.append(_loss("vendor_dxf_curves", "DXF 원호 경계를 최대 현 오차 0.002 mm의 직선 경계로 변환합니다.",
                                chord_error_mm=CHORD_ERROR_MM, source_arc_count=arcs))
    regions = []
    split = 0
    redundant = 0
    for index, (layer, side, label, path, polygon) in enumerate(polygons, 1):
        if any(other_path == path and other_layer == layer and other.area > polygon.area and other.covers(polygon)
               for other_layer, _, _, other_path, other in polygons):
            redundant += 1
            continue
        parts = list(_parts(polygon.simplify(0, preserve_topology=True)))
        split += len(parts) - 1
        for part, loops in enumerate(parts, 1):
            regions.append({"source_id": f"{path}:{layer}:{index}:{part}", "layer": layer, "side": side, "label": label,
                            "outer_mm": loops[0], "holes_mm": loops[1:]})
    if redundant:
        losses.append(_loss("vendor_redundant_copper", "같은 층의 넓은 동박에 전부 포함된 폐곡선은 별도 도형을 중복 생성하지 않습니다.",
                            contours_preserved_in_original=redundant))
    if split:
        losses.append(_loss("vendor_bounds_split", "정점이 많은 동박을 면적을 유지하는 여러 편집 영역으로 나눕니다."))
    if len(regions) > 128:
        raise ProjectError("E_RESOURCE", "제조사 안테나 편집 영역 수가 128개를 초과했습니다.")
    return {"schema": SCHEMA, "version": card["revision"], "card": card, "regions": regions,
            "placement_anchor_mm": anchor, "members": members, "losses": losses}
