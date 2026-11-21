"""! @brief 해시가 확인된 제조사 원본을 교환 worker에서 읽는다."""

import hashlib
from io import BytesIO
from zipfile import ZipFile

from rfad.adapters.exchange.vendor_dxf import CHORD_ERROR_MM, read_renesas
from rfad.domain.errors import ProjectError
from rfad.domain.planar import MAX_REGION_HOLES, MAX_REGION_POINTS
from rfad.domain.vendor_catalog import VENDOR_FORMATS


SCHEMA = "rfad.vendor-pattern-read/0.1"


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


def read_pattern(raw, format_name):
    """! @brief 선택한 카드의 정확한 원문과 도체 영역, 생략 조건을 반환한다."""
    card = VENDOR_FORMATS[format_name]
    digest = _hash(raw)
    if digest == card["archive_sha256"]:
        member = _member(raw, card["member"], card["sha256"])
    elif digest == card["sha256"]:
        member = raw
    else:
        raise ProjectError("E_HASH", "선택한 제조사 예제와 원문이 다릅니다. 해당 DXF 또는 공식 ZIP을 선택하십시오.")
    polygons, skipped, arcs = read_renesas(member)
    losses = [_loss("vendor_scope", "동박만 가져옵니다. 보드, 급전, 포트, 물성은 기존 값이 유지되며 새 도체의 해석 포함은 꺼져 있습니다."),
              _loss("vendor_dxf_layers", "패드·비아 블록, 마스크 및 풋프린트 표시 등 도체 경계 외 항목을 원문에 보존합니다.", layers=skipped)]
    if arcs:
        losses.append(_loss("vendor_dxf_curves", "DXF 원호 경계를 최대 현 오차 0.002 mm의 직선 경계로 변환합니다.",
                            chord_error_mm=CHORD_ERROR_MM, source_arc_count=arcs))
    regions = []
    split = 0
    redundant = 0
    for index, (layer, side, polygon) in enumerate(polygons, 1):
        if any(other_layer == layer and other.area > polygon.area and other.covers(polygon)
               for other_layer, _, other in polygons):
            redundant += 1
            continue
        parts = list(_parts(polygon.simplify(0, preserve_topology=True)))
        split += len(parts) - 1
        for part, loops in enumerate(parts, 1):
            regions.append({"source_id": f"{card['member']}:{layer}:{index}:{part}", "layer": layer, "side": side,
                            "outer_mm": loops[0], "holes_mm": loops[1:]})
    if redundant:
        losses.append(_loss("vendor_redundant_copper", "같은 층의 넓은 동박에 전부 포함된 폐곡선은 별도 도형을 중복 생성하지 않습니다.",
                            contours_preserved_in_original=redundant))
    if split:
        losses.append(_loss("vendor_bounds_split", "정점이 많은 동박을 면적을 유지하는 여러 편집 영역으로 나눕니다."))
    if len(regions) > 128:
        raise ProjectError("E_RESOURCE", "제조사 안테나 편집 영역 수가 128개를 초과했습니다.")
    return {"schema": SCHEMA, "version": card["revision"], "card": card, "regions": regions, "losses": losses}
