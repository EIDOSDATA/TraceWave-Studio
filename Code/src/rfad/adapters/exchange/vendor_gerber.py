"""! @brief 검토한 공급사 Gerber의 단위와 순서, 도체 합성 범위를 적용한다."""

import math
import re

from rfad.adapters.exchange.cam_reader import read_gerber
from rfad.adapters.exchange.pcb_geometry import polygonize
from rfad.domain.errors import ProjectError

CHORD_MM = 0.002
_MARKER = ".TraceWaveVendorMacro"


def _quad_segments(radius):
    """! @brief 부호 있는 반지름 오류와 최대 현 오차를 확인한다."""
    if radius <= 0:
        raise ProjectError("E_GEOMETRY", "공급사 원형 aperture의 지름이 양수가 아닙니다.")
    ratio = max(-1.0, 1 - CHORD_MM / radius)
    return max(2, math.ceil(math.pi / (4 * math.acos(ratio))))


def _circle(center, radius):
    """! @brief 원형 aperture를 유한 현 오차 안에서 선형 경계로 변환한다."""
    from shapely import Point
    return Point(center).buffer(radius, quad_segs=_quad_segments(radius))


def _macro(source):
    """! @brief 확인한 TI macro의 가산 outline과 원형 primitive만 해석한다."""
    from shapely import Polygon, unary_union
    primitives = []
    for record in source.split("*"):
        if not record.strip():
            continue
        kind, exposure, *values = [item.strip() for item in record.split(",")]
        numbers = [float(item) for item in values]
        if exposure == "1" and kind == "4" and len(numbers) == 12 and numbers[0] == 4 and numbers[-1] == 0:
            points = list(zip(numbers[1:-1:2], numbers[2:-1:2]))
            polygon = Polygon([(x * 25.4, y * 25.4) for x, y in points])
            if points[0] != points[-1] or not polygon.is_valid:
                raise ProjectError("E_GEOMETRY", "TI aperture macro의 outline이 유효하지 않습니다.")
            primitives.append(polygon)
        elif exposure == "1" and kind == "1" and len(numbers) == 3 and numbers[0] > 0:
            diameter, x, y = numbers
            primitives.append(_circle((x * 25.4, y * 25.4), diameter * 12.7))
        else:
            raise ProjectError("E_UNSUPPORTED", "검토한 TI aperture macro의 문법 범위를 벗어났습니다.")
    if not primitives:
        raise ProjectError("E_SCHEMA", "TI aperture macro가 비어 있습니다.")
    return unary_union(primitives)


def _ti_reader(raw):
    """! @brief 원문의 G70과 inline aperture macro를 엄격 CAM reader 입력에 대응한다."""
    source = raw.decode("ascii")
    if not source.startswith("G70*") or "%MO" in source:
        raise ProjectError("E_SCHEMA", "TI 공급사 원문의 inch 선언이 유효하지 않습니다.")
    macros = {}
    def extract(match):
        """! @brief macro 정의를 복사하지 않고 원문 숫자로 도체 범위를 만든다."""
        name, body = match.groups()
        macros[name] = _macro(body)
        return ""
    source = re.sub(r"%AM(USER[0-9]+)\*([^%]+)%", extract, source)
    def aperture(match):
        """! @brief macro 선택을 유형 표시로 보존하고 실제 도체는 후속 단계에서 치환한다."""
        number, name = match.groups()
        if name not in macros:
            raise ProjectError("E_SCHEMA", "TI aperture가 아직 정의되지 않은 macro를 가리킵니다.")
        return f"%TA{_MARKER},{name}*%%ADD{number}C,0*%%TD{_MARKER}*%"
    source = re.sub(r"%ADD([0-9]+)(USER[0-9]+)\*%", aperture, source)
    decoded = read_gerber(("%MOIN*%\nG01*\n" + source[len("G70*"):]).encode("ascii"))
    return decoded, macros


def _flash(item, macros):
    """! @brief 정규 aperture와 확인한 TI macro를 실제 면적 기하로 반환한다."""
    from shapely import box
    from shapely.affinity import translate
    aperture = item["aperture"]
    x, y = item["center_mm"]
    marker = aperture["attributes"].get(_MARKER)
    if marker is not None:
        return translate(macros[marker[0]], xoff=x, yoff=y)
    if aperture["kind"] == "C":
        return _circle((x, y), aperture["size_mm"][0] / 2)
    if aperture["kind"] == "R":
        width, height = aperture["size_mm"]
        return box(x - width / 2, y - height / 2, x + width / 2, y + height / 2)
    raise ProjectError("E_UNSUPPORTED", "제조사 패턴의 지원하지 않는 flash aperture입니다.")


def _effective(decoded, macros):
    """! @brief 실제 순서의 밝은 도체와 clear 영역을 적용해 닫힌 동박을 계산한다."""
    from shapely import GeometryCollection, LineString, set_precision
    result = GeometryCollection()
    for item in decoded["objects"]:
        if item["kind"] == "region":
            shape = polygonize(item["loops"])
        elif item["kind"] == "flash":
            shape = _flash(item, macros)
        else:
            edge, width = item["edge"], item["width_mm"]
            if edge["kind"] != "line" or width <= 0:
                raise ProjectError("E_UNSUPPORTED", "제조사 패턴의 지원하지 않는 선폭 또는 Gerber stroke입니다.")
            radius = width / 2
            shape = LineString([edge["start"], edge["end"]]).buffer(radius, quad_segs=_quad_segments(radius))
        shape = set_precision(shape, 1e-7)
        result = result.union(shape) if item["polarity"] == "dark" else result.difference(shape)
    if result.is_empty or not result.is_valid:
        raise ProjectError("E_GEOMETRY", "Gerber 합성이 유효한 닫힌 동박을 만들지 못했습니다.")
    return result


def read_ti(raw):
    """! @brief TI 독립 SPL 파일의 도체와 변환 근거를 반환한다."""
    data, macros = _ti_reader(raw)
    return _effective(data, macros), bool(macros)
