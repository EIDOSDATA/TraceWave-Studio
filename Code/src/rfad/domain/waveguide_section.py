"""! @brief 공동 삼각 단면에서 균질 PEC 도파관의 TE/TM 모드와 개구 산란을 계산한다."""

from dataclasses import dataclass
from itertools import combinations
import math

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_hash
from rfad.domain.floquet import LIGHT_SPEED
from rfad.domain.network_data import fail, finite
from rfad.domain.planar import _intersect


PROFILE = "rfad.pec-waveguide-section-step/0.1"
COMPARISON_EXTRA = 4
MAX_NODES = 12000
VACUUM_IMPEDANCE_OHM = 1 / (8.8541878128e-12 * LIGHT_SPEED)


@dataclass
class _Section:
    """! @brief 개구와 넓은 단면에서 공통 절점, 모드 컷오프와 접선 전계를 보존한다."""

    nodes: object
    values: object
    k_cut: object
    electric: object
    families: object
    names: list


def _validate(case):
    """! @brief 소스 좌표, 두 반공간, 공통 개구 및 수치 상한을 검사한다."""
    keys = {"nodes_mm", "triangles", "aperture_triangles", "epsilon_r", "frequencies_hz",
            "basis_per_family", "reference_offsets_mm"}
    if type(case) is not dict or set(case) != keys:
        fail("공통 단면 격자, 개구 삼각형, 매질, 기준면과 모드 수를 입력하십시오.", "case")
    nodes = case["nodes_mm"]
    if type(nodes) is not list or not 8 <= len(nodes) <= MAX_NODES:
        fail(f"공통 격자에 8~{MAX_NODES}개 절점이 필요합니다.", "nodes_mm", "E_RESOURCE")
    for point in nodes:
        if type(point) is not list or len(point) != 2 or any(abs(finite(x, "nodes_mm")) > 1000 for x in point):
            fail("절점은 -1000~1000 mm의 [x, y] 좌표입니다.", "nodes_mm")
    if len({tuple(point) for point in nodes}) != len(nodes):
        fail("중복 절점을 병합하십시오.", "nodes_mm", "E_GEOMETRY")
    triangles = case["triangles"]
    if type(triangles) is not list or not 4 <= len(triangles) <= 2 * len(nodes):
        fail("공통 삼각형 목록의 범위를 확인하십시오.", "triangles", "E_GEOMETRY")
    for vertices in triangles:
        if (type(vertices) is not list or len(vertices) != 3
                or any(type(i) is not int or not 0 <= i < len(nodes) for i in vertices)
                or len(set(vertices)) != 3):
            fail("삼각형에 서로 다른 세 절점 번호가 필요합니다.", "triangles", "E_GEOMETRY")
    if len({tuple(sorted(vertices)) for vertices in triangles}) != len(triangles):
        fail("중복 삼각형은 허용하지 않습니다.", "triangles", "E_GEOMETRY")
    aperture = case["aperture_triangles"]
    if (type(aperture) is not list or not 4 <= len(aperture) <= len(triangles)
            or any(type(i) is not int or not 0 <= i < len(triangles) for i in aperture)
            or len(set(aperture)) != len(aperture)):
        fail("좁은 쪽은 넓은 단면 안의 중복 없는 삼각형으로 지정하십시오.", "aperture_triangles", "E_GEOMETRY")
    if not 0.01 <= finite(case["epsilon_r"], "epsilon_r") <= 100:
        fail("두 포트에 동일한 양의 상대 유전율을 지정하십시오.", "epsilon_r")
    if type(case["basis_per_family"]) is not int or not 4 <= case["basis_per_family"] <= 72:
        fail("양쪽 TE/TM 계열의 모드 수는 4~72입니다.", "basis_per_family", "E_RESOURCE")
    offsets = case["reference_offsets_mm"]
    if (type(offsets) is not list or len(offsets) != 2
            or any(not 0 <= finite(value, "reference_offsets_mm") <= 1000 for value in offsets)):
        fail("접합에서 바깥쪽으로 잰 두 기준면 거리를 mm로 입력하십시오.", "reference_offsets_mm")
    frequencies = case["frequencies_hz"]
    if (type(frequencies) is not list or not 1 <= len(frequencies) <= 31
            or any(not 1e6 <= finite(f, "frequencies_hz") <= 1e13 for f in frequencies)
            or any(a >= b for a, b in zip(frequencies, frequencies[1:]))):
        fail("증가하는 주파수를 1~31개 입력하십시오.", "frequencies_hz")


def _boundary(nodes, triangles, field):
    """! @brief 같은 변을 공유하는 단일 단순 PEC 경계를 검사한다."""
    edges = {}
    for a, b, c in triangles.tolist():
        for start, end in ((a, b), (b, c), (c, a)):
            key = (min(start, end), max(start, end))
            previous = edges.get(key, ())
            if previous is None or previous == (start, end):
                fail("겹친 요소 또는 비다양체 모서리가 있습니다.", field, "E_GEOMETRY")
            edges[key] = None if previous else (start, end)
    outline = [edge for edge in edges.values() if edge is not None]
    if len(outline) < 3 or len(outline) > 512:
        fail("단일 PEC 외곽에 3~512개 경계 변이 필요합니다.", field, "E_GEOMETRY")
    successors = dict(outline)
    if len(successors) != len(outline) or set(successors) != set(successors.values()):
        fail("경계는 단일 닫힌 경로여야 합니다.", field, "E_GEOMETRY")
    current = min(successors)
    visited = set()
    while current not in visited:
        visited.add(current)
        current = successors[current]
    if len(visited) != len(outline):
        fail("구멍 또는 분리된 단면은 지원하지 않습니다.", field, "E_UNSUPPORTED")
    tolerance = max(1e-10, (nodes.max() - nodes.min()) * 1e-10)
    points = nodes.tolist()
    for (a, b), (c, d) in combinations(outline, 2):
        if len({a, b, c, d}) == 4 and _intersect(points[a], points[b], points[c], points[d], tolerance):
            fail("단면 외곽이 교차합니다.", field, "E_GEOMETRY")
    return sorted(successors)


def _mesh(np, nodes, triangles):
    """! @brief 반시계 삼각형의 면적과 P1 형상 함수 기울기를 만든다."""
    points = nodes[triangles]
    jacobian = np.swapaxes(points[:, 1:] - points[:, :1], 1, 2)
    determinants = np.linalg.det(jacobian)
    if np.min(abs(determinants)) <= 1e-10:
        fail("퇴화하거나 면적이 너무 작은 삼각형이 있습니다.", "triangles", "E_GEOMETRY")
    reverse = determinants < 0
    triangles[reverse] = triangles[reverse][:, [0, 2, 1]]
    jacobian[reverse] = jacobian[reverse][:, :, ::-1]
    return abs(determinants) / 2, np.array([[-1., -1.], [1., 0.], [0., 1.]]) @ np.linalg.inv(jacobian)


def _section(np, scipy, nodes, triangles, areas, gradients, count, field):
    """! @brief TE의 Neumann과 TM의 Dirichlet 고유값을 같은 단면의 P1 삼각형에서 구한다."""
    boundary = _boundary(nodes, triangles, field)
    selected = np.unique(triangles)
    interior = np.flatnonzero(~np.isin(selected, boundary))
    if len(interior) < count + 2:
        fail("TM 경계 안쪽 절점이 부족합니다. 단면 격자를 세분하십시오.", field, "E_RESOURCE")
    local = np.searchsorted(selected, triangles)
    rows = np.repeat(local, 3, axis=1).reshape(-1)
    cols = np.tile(local, (1, 3)).reshape(-1)

    def assemble(contribution):
        """! @brief 국소 삼각 행렬을 희소 단면 행렬로 합친다."""
        return scipy.sparse.coo_matrix((contribution.reshape(-1), (rows, cols)),
                                       shape=(len(selected), len(selected))).tocsr()

    stiffness = assemble(np.einsum("tiv,tjv,t->tij", gradients, gradients, areas))
    mass = assemble(areas[:, None, None] * (np.ones((3, 3)) + np.eye(3)) / 12)
    indices = np.arange(len(selected))
    shift = -1 / (float(np.max(np.ptp(nodes[selected], axis=0)))**2)
    basis_values, cutoffs, fields, families = [], [], [], []
    for family, active, skip in (("TE", indices, 1), ("TM", interior, 0)):
        lambda2, vectors = scipy.sparse.linalg.eigsh(
            stiffness[active, :][:, active], k=count + skip, M=mass[active, :][:, active],
            sigma=shift, which="LM", v0=np.linspace(1, 2, len(active)))
        order = np.argsort(lambda2)[skip:]
        lambda2, vectors = lambda2[order], vectors[:, order]
        if np.min(lambda2) <= 0:
            fail("단면 해에서 고유값을 분리할 수 없습니다.", field, "E_CONFLICT")
        anchor = np.argmax(abs(vectors), axis=0)
        vectors *= np.sign(vectors[anchor, np.arange(count)])
        nodal = np.zeros((len(selected), count))
        nodal[active] = vectors
        electric = np.einsum("tiv,tim->tvm", gradients, nodal[local]) / np.sqrt(lambda2)
        if family == "TE":
            electric = electric[:, [1, 0], :] * np.array([1, -1])[None, :, None]
        basis_values.append(nodal)
        cutoffs.extend(np.sqrt(lambda2))
        fields.append(electric)
        families.extend([family] * count)
    names = [f"{family}{i + 1}" for family in ("TE", "TM") for i in range(count)]
    return _Section(selected, np.concatenate(basis_values, axis=1), np.array(cutoffs),
                    np.concatenate(fields, axis=2), np.array(families), names)


def _indices(np, section, k0, epsilon, count):
    """! @brief 모든 전파 모드를 포함하는 절단 기저와 복소 어드미턴스를 만든다."""
    q_squared = epsilon - (section.k_cut / k0)**2
    if np.min(abs(q_squared)) <= 1e-10 * epsilon:
        fail("도파관 모드 차단점과 겹치는 주파수입니다.", "frequencies_hz", "E_CONFLICT")
    per_family = len(section.k_cut) // 2
    if q_squared[count] >= 0 or q_squared[per_family + count] >= 0:
        fail("모든 전파 성분을 포함하도록 모드 수를 늘리십시오.", "basis_per_family", "E_RESOURCE")
    basis = np.r_[0:count, per_family:per_family + count]
    q = np.sqrt(q_squared[basis].astype(complex))
    y = np.where(section.families[basis] == "TE", q, epsilon / q)
    return basis, q, y, np.flatnonzero(q.real > 0)


def _scatter(np, frequency, epsilon, offsets, wide, narrow, overlap, count):
    """! @brief 접면에서 TE/TM 접선장을 맞추고 모든 전파 입사 열을 한 번에 푼다."""
    k0 = 2 * math.pi * frequency / (LIGHT_SPEED * 1000)
    left, ql, yl, pl = _indices(np, wide, k0, epsilon, count)
    right, qr, yr, pr = _indices(np, narrow, k0, epsilon, count)
    if not len(pl) + len(pr):
        fail("여기할 전파 모드가 있는 주파수를 선택하십시오.", "frequencies_hz", "E_CONFLICT")
    aperture = overlap[np.ix_(left, right)]
    rhs = 2 * np.column_stack((aperture[pl].T * yl[pl], np.eye(len(right))[:, pr] * yr[pr]))
    matrix = (aperture.T * yl) @ aperture + np.diag(yr)
    electric = np.linalg.solve(matrix, rhs)
    modes = len(pl) + len(pr)
    s = np.vstack((aperture[pl] @ electric, electric[pr])) - np.eye(modes)
    scale = np.sqrt(np.r_[yl[pl].real, yr[pr].real])
    s *= scale[:, None] / scale
    phases = np.exp(1j * k0 * np.r_[ql[pl] * offsets[0], qr[pr] * offsets[1]])
    s *= phases[:, None] * phases
    if not np.isfinite(s).all() or np.max(abs(matrix @ electric - rhs)) > 1e-8 * np.max(abs(rhs)):
        fail("개구 정합의 선형 잔차가 기준을 넘었습니다.", "frequencies_hz", "E_CONFLICT")
    channels = [f"{side}:{section.names[i]}" for side, section, ids in (
        ("wide", wide, left[pl]), ("narrow", narrow, right[pr])) for i in ids]
    return channels, s, {"wide": (left, ql, yl), "narrow": (right, qr, yr)}


def _catalog(section, epsilon, count):
    """! @brief 방향과 편파를 재현할 절점 성분과 차단 주파수를 출력한다."""
    result = []
    per_family = len(section.k_cut) // 2
    for i in list(range(count)) + list(range(per_family, per_family + count)):
        result.append({"mode": section.names[i], "polarization": str(section.families[i]),
                       "cutoff_hz": float(LIGHT_SPEED * 1000 * section.k_cut[i] / (2 * math.pi * math.sqrt(epsilon))),
                       "scalar_nodal_values_per_mm": section.values[:, i].tolist()})
    return {"node_indices": section.nodes.tolist(), "modes": result}


def solve(case):
    """! @brief 공통 삼각형 단면의 두 포트 모드와 단위 전력 산란행렬을 반환한다."""
    _validate(case)
    np, scipy, _, engine = network_backend.runtime()
    nodes = np.asarray(case["nodes_mm"], dtype=float)
    triangles = np.asarray(case["triangles"], dtype=int)
    aperture = np.asarray(sorted(case["aperture_triangles"]))
    if len(np.unique(triangles)) != len(nodes):
        fail("삼각형이 참조하지 않는 절점이 있습니다.", "nodes_mm", "E_GEOMETRY")
    areas, gradients = _mesh(np, nodes, triangles)
    count = case["basis_per_family"]
    compare = count + COMPARISON_EXTRA
    epsilon, offsets = case["epsilon_r"], case["reference_offsets_mm"]
    try:
        wide = _section(np, scipy, nodes, triangles, areas, gradients, compare + 1, "triangles")
        narrow = _section(np, scipy, nodes, triangles[aperture], areas[aperture], gradients[aperture],
                          compare + 1, "aperture_triangles")
        overlap = np.einsum("tvj,tvk,t->jk", wide.electric[aperture], narrow.electric, areas[aperture],
                            optimize=True)
        samples = []
        for frequency in case["frequencies_hz"]:
            channels, s, modes = _scatter(np, frequency, epsilon, offsets, wide, narrow, overlap, count)
            _, refined, _ = _scatter(np, frequency, epsilon, offsets, wide, narrow, overlap, compare)
            mode_samples = {}
            for side, (index, q, y) in modes.items():
                k0 = 2 * math.pi * frequency / LIGHT_SPEED
                section = wide if side == "wide" else narrow
                mode_samples[side] = [{"mode": section.names[i], "type": "propagating" if v.real > 0 else "evanescent",
                                       "beta_ri_per_m": [float((k0 * v).real), float((k0 * v).imag)],
                                       "normalized_admittance_ri": [float(a.real), float(a.imag)],
                                       "modal_voltage_v_per_sqrt_w": math.sqrt(2 * VACUUM_IMPEDANCE_OHM / a.real)
                                       if a.real > 0 else None}
                                      for i, v, a in zip(index, q, y)]
            samples.append({"frequency_hz": frequency, "channels": channels,
                            "s_ri": np.stack((s.real, s.imag), axis=-1).tolist(), "port_modes": mode_samples,
                            "energy_residual_max": float(np.max(abs(s.conj().T @ s - np.eye(len(channels))))),
                            "reciprocity_residual_max": float(np.max(abs(s - s.T))),
                            "next_basis_delta_max": float(np.max(abs(s - refined)))})
    except (np.linalg.LinAlgError, scipy.sparse.linalg.ArpackNoConvergence, RuntimeError):
        fail("단면 고유모드 또는 개구 행렬을 풀 수 없습니다.", "triangles", "E_CONFLICT")
    return {"schema": PROFILE, "input_sha256": canonical_hash(case), "engine": engine,
            "phasor_convention": "exp(-j*omega*t)", "wave_basis": "unit_power_tangential_E",
            "port_inward_directions": {"wide": [0, 0, 1], "narrow": [0, 0, -1]},
            "reference_planes_z_mm": {"wide": -offsets[0], "narrow": offsets[1]},
            "scalar_basis": {"TE": "L2-normalized Hz shape", "TM": "L2-normalized Ez shape"},
            "sections": {"wide": _catalog(wide, epsilon, count), "narrow": _catalog(narrow, epsilon, count)},
            "comparison_basis_per_family": compare, "samples": samples}
