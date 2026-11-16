"""! @brief 고정된 선택 GEOS 엔진으로 유한 다각형 연산만 수행한다.

@details 해석형 선/원호를 몰래 다각형화하지 않는다. 자동 정밀도 격자,
자기 교차 복구, 단순화와 작은 조각 삭제는 수행하지 않는다.
"""

from functools import lru_cache
from importlib import metadata
import math

from rfad.domain.errors import ProjectError
from rfad.domain.planar import MAX_REGION_HOLES, MAX_REGION_POINTS, validate_region
from rfad.domain.precision_transform import fail, number


SHAPELY_VERSION = "2.2.0"
GEOS_VERSION = "3.14.1"
MAX_OUTPUTS = 16


def installation_metadata():
    """! @brief 일반 capabilities 조회에서는 native 모듈을 읽지 않고 설치 메타데이터만 보고한다."""
    try:
        version = metadata.version("shapely")
    except metadata.PackageNotFoundError:
        version = None
    matches = version == SHAPELY_VERSION
    reason = ("선택 평면 연산 엔진을 설치해야 합니다." if version is None else
              ("정밀 편집 요청에서 실제 GEOS 엔진과 고정 버전을 확인합니다." if matches else
               "고정된 Shapely 2.2.0/GEOS 3.14.1 환경이 필요합니다."))
    return {"name": "Shapely/GEOS", "version": version, "geos_version": None,
            "required_version": SHAPELY_VERSION, "required_geos_version": GEOS_VERSION,
            "installation_detected": version is not None, "version_matches": matches,
            "runtime_checked": False, "available": None if matches else False, "reason": reason}


@lru_cache(maxsize=1)
def runtime():
    """! @brief 엔진이 없어도 저장/재열기와 순수 기하 편집은 사용할 수 있다."""
    try:
        import shapely
    except (ImportError, OSError) as error:
        return None, {"available": False, "name": "Shapely/GEOS", "version": SHAPELY_VERSION,
                      "geos_version": GEOS_VERSION, "reason": "선택 평면 연산 엔진을 설치해야 합니다.",
                      "diagnostic": type(error).__name__}
    actual = {"version": getattr(shapely, "__version__", "unknown"),
              "geos_version": getattr(shapely, "geos_version_string", "unknown")}
    actual = {key: value if type(value) is str else "unknown" for key, value in actual.items()}
    supported = actual == {"version": SHAPELY_VERSION, "geos_version": GEOS_VERSION}
    return (shapely if supported else None), {"available": supported, "name": "Shapely/GEOS", **actual,
                                            "reason": "" if supported else "고정된 Shapely 2.2.0/GEOS 3.14.1 환경이 필요합니다."}


def _canonical_loop(coordinates, *, clockwise):
    """! @brief 엔진 결과 순서에 의존하지 않도록 시작점과 winding만 정규화한다."""
    from rfad.domain.planar import signed_area

    points = [[0.0 if float(x) == 0 else float(x), 0.0 if float(y) == 0 else float(y)] for x, y in coordinates]
    if points and points[0] == points[-1]:
        points.pop()
    if points and ((signed_area(points) < 0) != clockwise):
        points.reverse()
    if points:
        first = min(range(len(points)), key=lambda index: tuple(points[index]))
        points = points[first:] + points[:first]
    return points


def operate(operands, operation, values):
    """! @brief 같은 평면의 유효 다각형 연산 결과를 저장 profile 안에서 반환한다."""
    shapely, engine = runtime()
    if shapely is None:
        fail(engine["reason"], "operation", "E_UNSUPPORTED")
    if not 1 <= len(operands) <= 16:
        fail("평면 연산은 최대 16개 입력을 지원합니다.", "selection_ids", "E_RESOURCE")
    inputs = []
    for index, operand in enumerate(operands):
        validate_region(operand["outer"], operand["holes"], f"selection_ids.{index}")
        shape = shapely.Polygon(operand["outer"], operand["holes"])
        if not shape.is_valid:
            fail("유효하지 않은 원본은 자동 복구하지 않습니다: " + shapely.is_valid_reason(shape), "selection_ids")
        inputs.append(shape)
    try:
        result = inputs[0]
        if operation == "offset":
            if len(inputs) != 1:
                fail("오프셋에는 한 도체 영역을 선택하십시오.", "selection_ids", "E_SCHEMA")
            distance = number(values["distance_mm"], "distance_mm")
            limit = number(values["mitre_limit"], "mitre_limit")
            if distance == 0 or abs(distance) > 1e6 or not 1 <= limit <= 100:
                fail("오프셋은 0이 아닌 1000000 mm 이내 값, 모서리 한계는 1~100이어야 합니다.", "distance_mm", "E_UNIT")
            if values["join"] not in ("mitre", "bevel"):
                fail("초기 profile은 직선 mitre/bevel 모서리만 지원합니다.", "join", "E_UNSUPPORTED")
            result = shapely.buffer(result, distance, join_style=values["join"], mitre_limit=limit)
        else:
            if len(inputs) < 2:
                fail("집합 연산에는 두 개 이상 영역을 선택하십시오.", "selection_ids", "E_SCHEMA")
            function = {"union": shapely.union, "difference": shapely.difference, "intersection": shapely.intersection}.get(operation)
            if function is None:
                fail("지원하지 않는 평면 연산입니다.", "operation", "E_UNSUPPORTED")
            for operand in inputs[1:]:
                result = function(result, operand, grid_size=0)
    except shapely.errors.GEOSException as error:
        fail("평면 연산을 완료하지 못했습니다. 원본은 유지됩니다: " + str(error), "operation")
    if result.is_empty:
        fail("결과 면적이 없습니다. 전체 원본 삭제로 자동 적용하지 않습니다.", "operation")
    if result.geom_type not in ("Polygon", "MultiPolygon") or not result.is_valid:
        fail("결과가 유효한 도체 영역이 아닙니다. 선/점 잔여를 조용히 버리지 않습니다.", "operation")
    polygons = [result] if result.geom_type == "Polygon" else list(result.geoms)
    if len(polygons) > MAX_OUTPUTS:
        fail("평면 연산 결과가 최대 16개 영역을 초과했습니다.", "operation", "E_RESOURCE")
    outputs = []
    for polygon in polygons:
        count = len(polygon.exterior.coords) - 1 + sum(len(ring.coords) - 1 for ring in polygon.interiors)
        if count > MAX_REGION_POINTS or len(polygon.interiors) > MAX_REGION_HOLES:
            fail("결과 영역이 64점/8구멍 저장 한계를 초과했습니다. 자동 단순화하지 않습니다.", "operation", "E_RESOURCE")
        outer = _canonical_loop(polygon.exterior.coords, clockwise=False)
        holes = sorted((_canonical_loop(ring.coords, clockwise=True) for ring in polygon.interiors), key=lambda loop: tuple(map(tuple, loop)))
        if any(not math.isfinite(value) or abs(value) > 1e6 for loop in [outer, *holes] for point in loop for value in point):
            fail("결과 좌표가 정밀 편집 범위를 초과했습니다.", "operation", "E_RESOURCE")
        validate_region(outer, holes)
        outputs.append({"outer": outer, "holes": holes})
    outputs.sort(key=lambda row: (tuple(map(tuple, row["outer"])), tuple(tuple(map(tuple, loop)) for loop in row["holes"])))
    return outputs, engine
