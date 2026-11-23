"""! @brief 삼각화한 유향 곡면을 실제 Yee 보간 셀별로 잘라 전력 흐름을 적분한다."""

from collections import Counter
from itertools import product
import math

from rfad.application.canonical import canonical_hash
from rfad.application.project_contract import _fields
from rfad.domain.errors import ProjectError


MAX_FACES = 4096
MAX_FRAGMENTS = 32768


def _mesh(np, surface, common):
    """! @brief 보간 범위 안의 정점, 인덱스, 면 방향과 모서리 접속을 검사한다."""
    _fields(surface, {"kind", "vertices_mm", "triangles"})
    vertices, triangles = surface["vertices_mm"], surface["triangles"]
    if (type(vertices) is not list or not 3 <= len(vertices) <= MAX_FACES
            or type(triangles) is not list or not 1 <= len(triangles) <= MAX_FACES):
        raise ProjectError("E_RESOURCE", "정점 3~4096개와 삼각형 1~4096개를 지정하십시오.")
    for row in vertices:
        if (type(row) is not list or len(row) != 3
                or any(type(x) not in (int, float) or not lo <= x <= hi for x, (lo, hi) in zip(row, common))):
            raise ProjectError("E_SCHEMA", "정점에 여섯 성분의 공통 범위 안에 있는 XYZ mm 좌표를 입력하십시오.")
    oriented, seen = Counter(), set()
    for row in triangles:
        if (type(row) is not list or len(row) != 3
                or any(type(i) is not int or not 0 <= i < len(vertices) for i in row) or len(set(row)) != 3):
            raise ProjectError("E_SCHEMA", "서로 다른 유효 정점 인덱스 세 개로 삼각형을 지정하십시오.")
        key = tuple(sorted(row))
        if key in seen:
            raise ProjectError("E_SCHEMA", "같은 삼각형을 두 번 적분할 수 없습니다.")
        seen.add(key)
        oriented.update(zip(row, row[1:] + row[:1]))
    if any(n != 1 for n in oriented.values()):
        raise ProjectError("E_GEOMETRY", "둘 이상의 삼각형이 같은 모서리 방향을 사용합니다.")
    closed = all((b, a) in oriented for a, b in oriented)
    data = np.asarray(vertices, dtype=float)[np.asarray(triangles, dtype=int)]
    area_vectors = np.cross(data[:, 1]-data[:, 0], data[:, 2]-data[:, 0])
    if np.any(np.linalg.norm(area_vectors, axis=1) == 0):
        raise ProjectError("E_GEOMETRY", "면적이 0인 삼각형이 있습니다.")
    return data, area_vectors, closed


def _clip(np, polygon, axis, knot, sign):
    """! @brief 평면의 한쪽을 취하고 교점의 축 좌표를 격자선과 정확히 맞춘다."""
    result = []
    a = polygon[-1]
    for b in polygon:
        da, db = a[axis] - knot, b[axis] - knot
        if (da < 0 < db) or (db < 0 < da):
            cut = np.array(a + (b-a) * (da/(da-db)))
            cut[axis] = knot
            result.append(cut)
        if db * sign >= 0:
            result.append(b)
        a = b
    return result


def _pieces(np, data, components):
    """! @brief 여섯 성분의 셀 내부에서 보간 함수가 다항식인 조각으로 분할한다."""
    cuts = [sorted({x for coordinates, _ in components for x in coordinates[axis]}) for axis in "xyz"]
    fragments = []
    for triangle in data:
        polygons = [list(triangle)]
        for axis, knots in enumerate(cuts):
            lo, hi = min(triangle[:, axis]), max(triangle[:, axis])
            for knot in knots:
                if not lo < knot < hi:
                    continue
                divided = []
                for poly in polygons:
                    if min(p[axis] for p in poly) < knot < max(p[axis] for p in poly):
                        divided.extend(_clip(np, poly, axis, knot, sign) for sign in (-1, 1))
                    else:
                        divided.append(poly)
                polygons = divided
                if len(polygons) + len(fragments) > MAX_FRAGMENTS:
                    raise ProjectError("E_RESOURCE", "곡면과 격자의 교차 조각이 32768개를 넘습니다.")
        for polygon in polygons:
            fragments.extend((polygon[0], a, b) for a, b in zip(polygon[1:], polygon[2:]))
            if len(fragments) > MAX_FRAGMENTS:
                raise ProjectError("E_RESOURCE", "곡면의 적분 삼각 조각이 32768개를 넘습니다.")
    return np.asarray(fragments)


def integrate_mesh(np, electric, magnetic, surface, common, interpolate):
    """! @brief 유향 삼각형의 실수 Poynting 성분을 4x4 Duffy-Gauss 규칙으로 적분한다."""
    data, normals, closed = _mesh(np, surface, common)
    pieces = _pieces(np, data, [*electric, *magnetic])
    ab, ac = pieces[:, 1] - pieces[:, 0], pieces[:, 2] - pieces[:, 0]
    cross = np.cross(ab, ac)
    nodes, weights = np.polynomial.legendre.leggauss(4)
    nodes, weights = (nodes + 1) / 2, weights / 2
    flux = []
    for i, j in product(range(4), repeat=2):
        u, v = nodes[i], nodes[j]
        xyz = pieces[:, 0] + u * ab + (1-u) * v * ac
        points = dict(zip("xyz", xyz.T))
        e, h = [np.stack([interpolate(c, points, np) for c in field], axis=-1)
                for field in (electric, magnetic)]
        density = np.cross(e, h.conj()).real
        flux.append(float(np.sum(np.einsum("ij,ij->i", density, cross))) * weights[i]*weights[j]*(1-u)*.5e-6)
    total = math.fsum(flux)
    if not math.isfinite(total):
        raise ProjectError("E_RESOURCE", "곡면 통과량이 유한 복소장의 수치 범위를 넘었습니다.")
    return {"surface": {"kind": "mesh", "sha256": canonical_hash(surface), "triangles": len(data),
                        "indexed_edges_closed": closed, "area_m2": float(np.linalg.norm(normals, axis=1).sum() * .5e-6),
                        "quadrature_points": 16 * len(pieces)},
            "common_bounds_mm": common, "faces": [], "total_flux_w_s2": total, "unit": "W*s^2",
            "quadrature": "piecewise_triangle_duffy_gauss_4x4"}
