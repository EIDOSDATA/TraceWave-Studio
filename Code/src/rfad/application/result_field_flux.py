"""! @brief 같은 급전으로 기록된 비균일 Yee 복소 E/H를 지정 면에서 보간하여 적분한다."""

from copy import deepcopy
from itertools import product
import math

from rfad.adapters import field_hdf5
from rfad.application import result_fields as fields
from rfad.application.project_contract import _fields
from rfad.domain.errors import ProjectError


def common_bounds(coordinates):
    """! @brief 여섯 성분이 각각 실제 이웃 표본을 갖는 공통 체적을 구한다."""
    if len(coordinates) != 6 or any(len(c[a]) < 2 for c in coordinates for a in "xyz"):
        return None
    bounds = [[max(c[a][0] for c in coordinates), min(c[a][-1] for c in coordinates)] for a in "xyz"]
    return bounds if all(lo < hi for lo, hi in bounds) else None


def _volume(service, resolved, monitor, index):
    """! @brief 같은 봉인 원본으로부터 크기를 검증한 4096점 이하 체적을 읽는다."""
    model = fields._model(resolved, monitor)
    if model is None or any(n < 2 for n in model["shape"]):
        raise ProjectError("E_UNSUPPORTED", "지정 영역에 E와 H의 삼차원 체적 기록이 모두 필요합니다.")
    if type(index) is not int or not 0 <= index < len(model["frequency_hz"]):
        raise ProjectError("E_SCHEMA", "기록 주파수 인덱스가 유효하지 않습니다.")
    reference = fields._reference(resolved, monitor)
    with service.journal._mutex:
        service.journal._ensure_open()
        path = service.journal._safe_path(reference["uri"])
    expected = {"shape": model["shape"], "frequency_hz": model["frequency_hz"],
                "primary_coordinates_mm": model["primary_coordinates_mm"],
                "dump_type": fields.MONITORS[monitor][3], "dual_mesh": int(model["magnetic"])}
    with field_hdf5.opened(path, reference) as (handle, h5py, np):
        datasets, primary = field_hdf5.inspect(handle, h5py, np, expected, max_points=4096)
        values = np.array(datasets[index], dtype=np.complex128)
        if not np.isfinite(values).all():
            raise ProjectError("E_HASH", "기록 체적에 유한하지 않은 복소 표본이 있습니다.")
    return ([(fields._coordinates(model, primary, axis), values[i]) for i, axis in enumerate("xyz")],
            model["frequency_hz"], reference)


def _quadrature(axis, lo, hi, components, np):
    """! @brief 모든 성분의 보간 매듭 사이에서 2점 Gauss 위치와 mm 가중치를 만든다."""
    knots = sorted({lo, hi} | {x for coord, _ in components for x in coord[axis] if lo < x < hi})
    half = np.diff(knots) / 2
    middle = np.asarray(knots[:-1]) + half
    delta = half / math.sqrt(3)
    return np.column_stack((middle - delta, middle + delta)).ravel(), np.repeat(half, 2)


def _interpolate(component, points, np):
    """! @brief 각 복소 성분을 그 성분 자신의 비균일 직교 격자에서 삼선형 보간한다."""
    coordinates, values = component
    pairs = []
    for axis in "xyz":
        grid = np.asarray(coordinates[axis])
        p = points[axis]
        index = np.clip(np.searchsorted(grid, p, side="right") - 1, 0, len(grid) - 2)
        t = (p - grid[index]) / (grid[index + 1] - grid[index])
        pairs.append(((index, 1 - t), (index + 1, t)))
    return sum(values[i, j, k] * a * b * c
               for (i, a), (j, b), (k, c) in product(*pairs))


def _face(electric, magnetic, bounds, normal, direction, np):
    """! @brief 선택 면의 접선 성분 외적으로 부호 있는 시간 평균 스펙트럼 면적분을 구한다."""
    u, v = ("xyz"[(normal + offset) % 3] for offset in (1, 2))
    components = [electric["xyz".index(u)], magnetic["xyz".index(v)],
                  electric["xyz".index(v)], magnetic["xyz".index(u)]]
    us, wu = _quadrature(u, *bounds["xyz".index(u)], components, np)
    vs, wv = _quadrature(v, *bounds["xyz".index(v)], components, np)
    points = {u: us[:, None], v: vs[None, :], "xyz"[normal]: bounds[normal][0]}
    eu, hv, ev, hu = (_interpolate(component, points, np) for component in components)
    density = (eu * hv.conjugate() - ev * hu.conjugate()).real * (direction * .5)
    value = float((wu @ density @ wv) * 1e-6)
    area = math.prod(hi - lo for i, (lo, hi) in enumerate(bounds) if i != normal) * 1e-6
    return {"axis": "xyz"[normal], "direction": direction, "bounds_mm": bounds, "area_m2": area,
            "quadrature_points": len(us) * len(vs), "flux_w_s2": value}


def integrate_surface(electric, magnetic, surface):
    """! @brief 공통 체적 안의 유향 직사각면 또는 직육면체 바깥쪽 6면을 적분한다."""
    import numpy as np

    common = common_bounds([c for c, _ in electric + magnetic])
    if common is None:
        raise ProjectError("E_UNSUPPORTED", "여섯 Yee 성분에 공통인 기록 체적이 없습니다.")
    if isinstance(surface, dict) and surface.get("kind") == "mesh":
        from rfad.application.result_mesh_flux import integrate_mesh

        return integrate_mesh(np, electric, magnetic, surface, common, _interpolate)
    closed = isinstance(surface, dict) and surface.get("kind") == "box"
    _fields(surface, {"kind", "bounds_mm"} if closed else {"kind", "bounds_mm", "axis", "direction"})
    if not closed and (surface["kind"] != "rectangle" or surface["axis"] not in ("x", "y", "z")
                       or type(surface["direction"]) is not int or surface["direction"] not in (-1, 1)):
        raise ProjectError("E_SCHEMA", "직사각면의 수직 축과 법선 부호를 지정하십시오.")
    bounds = surface["bounds_mm"]
    if (type(bounds) is not list or len(bounds) != 3 or
            any(type(pair) is not list or len(pair) != 2 or
                any(type(x) not in (int, float) or not math.isfinite(x) for x in pair) for pair in bounds)):
        raise ProjectError("E_SCHEMA", "X/Y/Z의 유한한 mm 경계를 각각 두 개 지정하십시오.")
    normal = None if closed else "xyz".index(surface["axis"])
    for index, ((lo, hi), (lower, upper)) in enumerate(zip(bounds, common)):
        if lo < lower or hi > upper:
            raise ProjectError("E_SCHEMA", "요청한 면이 기록된 여섯 성분의 공통 체적을 벗어납니다.")
        if (index == normal and lo != hi) or (index != normal and lo >= hi):
            raise ProjectError("E_SCHEMA", "면의 수직축은 한 위치이고 나머지 축은 증가 구간이어야 합니다.")
    if closed:
        faces = []
        for index, (lower, upper) in enumerate(bounds):
            for position, sign in ((lower, -1), (upper, 1)):
                side = deepcopy(bounds)
                side[index] = [position, position]
                faces.append(_face(electric, magnetic, side, index, sign, np))
    else:
        faces = [_face(electric, magnetic, bounds, normal, surface["direction"], np)]
    return {"surface": deepcopy(surface), "common_bounds_mm": common, "faces": faces,
            "total_flux_w_s2": math.fsum(face["flux_w_s2"] for face in faces), "unit": "W*s^2"}


def integrate(service, resolved, parameters):
    """! @brief 같은 봉인 급전과 주파수의 체적 복소장만 적분하며 원문을 보존한다."""
    _fields(parameters, {"frequency_index", "surface"})
    response = fields._base(resolved)
    if "drive_reference" not in response:
        raise ProjectError("E_UNSUPPORTED", "단일 급전의 봉인된 E/H 체적 기록이 필요합니다.")
    index = parameters["frequency_index"]
    electric, ef, eref = _volume(service, resolved, "probe_electric", index)
    magnetic, hf, href = _volume(service, resolved, "probe_magnetic", index)
    if ef != hf:
        raise ProjectError("E_HASH", "같은 여기의 두 필드가 서로 다른 주파수로 기록됐습니다.")
    response.update(integrate_surface(electric, magnetic, parameters["surface"]))
    response.update(profile="rfad.pcb-field-flux/0.1", frequency_hz=ef[index],
                    electric_ref=eref, magnetic_ref=href, fourier_convention="exp(-j*2*pi*f*t)",
                    warnings=[fields.WARNINGS[0], "같은 급전의 native E/H 시간 위상과 성분별 Yee 좌표를 사용합니다."],
                    phase_correction="native_dual_sample_times")
    response.setdefault("quadrature", "piecewise_tensor_gauss_2x2")
    return response
