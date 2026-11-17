"""! @brief CAM 해석 경계와 수신 도구의 polygon cache를 명시 오차 안에서 비교한다."""
import math

from rfad.domain.errors import ProjectError

CHORD_MM=1e-5
MAX_POINTS=65536


def polygonize(loops):
    """! @brief 원문을 수정하지 않고 선언 chord 오차의 검수용 polygon을 만든다."""
    from shapely import Polygon, GeometryCollection
    result=GeometryCollection()
    total=0
    for loop in loops:
        points=[]
        for edge in loop:
            if edge["kind"]=="line":
                points.append(list(edge["start"]))
            else:
                radius=edge["radius"]
                angle=2*math.acos(max(-1,min(1,1-CHORD_MM/radius)))
                count=max(1,math.ceil(abs(math.radians(edge["sweep_deg"]))/angle))
                if total+len(points)+count>MAX_POINTS:
                    raise ProjectError("E_RESOURCE","검수 polygon의 유한 꼭짓점 상한을 초과했습니다.")
                for index in range(count):
                    theta=math.radians(edge["start_deg"]+edge["sweep_deg"]*index/count)
                    points.append([edge["center"][0]+radius*math.cos(theta),edge["center"][1]+radius*math.sin(theta)])
        total+=len(points)
        if total>MAX_POINTS:
            raise ProjectError("E_RESOURCE","검수 polygon 꼭짓점 상한을 초과했습니다.")
        if not points:
            continue
        polygon=Polygon(points)
        if not polygon.is_valid or polygon.area<=0:
            raise ProjectError("E_GEOMETRY","검수 polygon이 유효하지 않습니다. 자동 치유하지 않습니다.")
        result=result.symmetric_difference(polygon)
    return result


def filled_cache(loops):
    """! @brief KiCad 초기 fill을 구멍 없는 삼각형들로 저장하되 원래 zone 경계를 유지한다."""
    from shapely import constrained_delaunay_triangles
    polygon=polygonize(loops)
    if polygon.is_empty:
        return []
    triangles=constrained_delaunay_triangles(polygon)
    if len(triangles.geoms)>MAX_POINTS:
        raise ProjectError("E_RESOURCE","KiCad fill cache 삼각형 상한을 초과했습니다.")
    return [list(map(list,triangle.exterior.coords[:-1])) for triangle in triangles.geoms]


def compare_regions(actual,expected,tolerance=3e-5):
    """! @brief 면적만으로 연결/국부 간격 손실을 숨기지 않도록 경계와 위상을 함께 검사한다."""
    def counts(value):
        """! @brief 연결 성분과 hole 개수를 구분한다."""
        parts=[value] if value.geom_type=="Polygon" else list(value.geoms)
        return len(parts),sum(len(part.interiors) for part in parts)
    if actual.is_empty or expected.is_empty:
        if actual.is_empty!=expected.is_empty:
            raise ProjectError("E_HASH","구리 영역의 존재 상태가 달라졌습니다.")
        return {"boundary_error_mm":0,"symmetric_difference_mm2":0,"components":0,"holes":0}
    if counts(actual)!=counts(expected):
        raise ProjectError("E_HASH","구리 영역의 연결 성분 또는 구멍 수가 달라졌습니다.")
    distance=actual.boundary.hausdorff_distance(expected.boundary)
    area=actual.symmetric_difference(expected).area
    limit=(actual.length+expected.length)*tolerance
    if distance>tolerance or area>limit:
        raise ProjectError("E_HASH","구리 경계/국부 간격이 선언 양자화 및 chord 오차를 벗어났습니다.",details={"boundary_error_mm":distance,"symmetric_difference_mm2":area,"tolerance_mm":tolerance})
    components,holes=counts(actual)
    return {"boundary_error_mm":distance,"symmetric_difference_mm2":area,"components":components,"holes":holes}


def native_fill(contours):
    """! @brief KiCad의 명시 중복 꼭짓점 bridge를 hole contour로 복원한다.

    @details self-intersection 치유가 아니라 수신 형식의 zero-width bridge 분해이다.
    반복점으로 분리되지 않는 교차는 polygonize의 유효성 검사에서 거절한다.
    """
    from shapely import GeometryCollection
    result=GeometryCollection()
    for contour in contours:
        if not contour:
            continue
        stack=[];positions={};loops=[]
        for point in [*contour,contour[0]]:
            key=tuple(point)
            if key in positions:
                index=positions[key];cycle=stack[index:]
                if len(cycle)>=3:
                    loops.append([{"kind":"line","start":a,"end":b} for a,b in zip(cycle,cycle[1:]+cycle[:1])])
                for old in stack[index+1:]:
                    positions.pop(tuple(old),None)
                stack=stack[:index+1]
            else:
                positions[key]=len(stack);stack.append(point)
        if len(stack)>1:
            raise ProjectError("E_SCHEMA","KiCad fill bridge contour가 닫히지 않았습니다.")
        result=result.union(polygonize(loops))
    return result
