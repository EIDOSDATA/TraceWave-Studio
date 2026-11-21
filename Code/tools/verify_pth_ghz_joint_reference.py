"""! @brief 축대칭 GHz 중공 관통홀의 접합과 유한 급전 손실을 두 독립 방법으로 대조한다."""
import argparse
import json
import math
import sys

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import spsolve
from scipy.special import ive, kve

from verify_pth_joint_reference import BARREL, CONDUCTIVITY, HEIGHT, INNER, JOINT_THICKNESS, PAD, PAD_THICKNESS


MU = 4e-7 * math.pi
NAME = ("barrel", "joint", "pad", "feed_pad")
FEED_BEGIN = PAD - 30e-6
FREQUENCIES = (8e9, 10e9, 12e9)
LEVELS = (2, 4, 8)


def skin(frequency, conductivity=CONDUCTIVITY):
    """! @brief 자성률이 진공과 같은 도체의 표피 깊이를 구한다."""
    return math.sqrt(1 / (math.pi * frequency * MU * conductivity))


def axis(points, level):
    """! @brief 표면과 접합 양쪽에서 표피 깊이 내부를 균일하게 나누고 중심부로 전이한다."""
    delta = skin(FREQUENCIES[-1])
    segments = []
    for low, high in zip(points, points[1:]):
        half = (high - low) / 2
        depth = min(half, 7 * delta)
        offset = list(np.linspace(0.0, depth, math.ceil(depth / delta * level) + 1))
        step = offset[-1] - offset[-2]
        while offset[-1] < half:
            step *= 1.5
            if offset[-1] + 1.5 * step >= half:
                offset.append(half)
                break
            offset.append(offset[-1] + step)
        segments.extend([*(low + value for value in offset), *(high - value for value in offset[-2:0:-1])])
    return np.unique([*segments, points[-1]])


def structure(level, ratio):
    """! @brief 같은 도체 형상을 유한체적 셀과 유한요소 삼각형에 제공한다."""
    r = axis((INNER, BARREL, FEED_BEGIN, PAD), level)
    z = axis((0, PAD_THICKNESS, PAD_THICKNESS + JOINT_THICKNESS,
              HEIGHT - PAD_THICKNESS - JOINT_THICKNESS, HEIGHT - PAD_THICKNESS, HEIGHT), level)
    rc = (r[:-1] + r[1:]) / 2
    zc = (z[:-1] + z[1:]) / 2
    depth = np.minimum(zc, HEIGHT - zc)
    in_pad = depth < PAD_THICKNESS
    regions = np.where(in_pad[None, :], np.where(rc[:, None] > FEED_BEGIN, 3, 2),
                       np.where(rc[:, None] < BARREL, (depth < PAD_THICKNESS + JOINT_THICKNESS)[None, :], -1))
    sigma = np.where(regions == 1, CONDUCTIVITY * ratio, CONDUCTIVITY)
    return r, z, regions, sigma


def feed_boundary(r, z, frequency, profile):
    """! @brief q=2πrH_phi의 경계차로 단자마다 1 A의 지정 전류를 부여한다."""
    depth = np.minimum(z, HEIGHT - z)
    phase = np.clip(depth / PAD_THICKNESS, 0, 1)
    if profile == "spread":
        curve = 0.5 * (1 - np.cos(math.pi * phase))
    else:
        delta = skin(frequency)
        distance = phase * PAD_THICKNESS
        curve = (np.exp(-(PAD_THICKNESS - distance) / delta) * (-np.expm1(-distance / delta))
                 / (-math.expm1(-PAD_THICKNESS / delta)))
    return np.where(np.isclose(r, INNER, rtol=0, atol=1e-12) | (depth < 1e-12), 0, curve)


def cylinder(frequency):
    """! @brief 안쪽 자계 0, 바깥 1 A인 직선 배럴의 Bessel 해와 단자 임피던스를 구한다."""
    rate = np.sqrt(1j * (math.tau * frequency) * MU * CONDUCTIVITY)

    def increasing(r):
        """! @brief 큰 복소 인자의 수정 Bessel I를 바깥 반경으로 스케일한다."""
        return r / BARREL * ive(1, rate * r) / ive(1, rate * BARREL) * np.exp(rate.real * (r - BARREL))

    def decreasing(r):
        """! @brief 수정 Bessel K를 안쪽 반경으로 스케일한다."""
        return r / INNER * kve(1, rate * r) / kve(1, rate * INNER) * np.exp(-rate * (r - INNER))

    a = 1 / (1 - increasing(INNER) * decreasing(BARREL))
    b = -a * increasing(INNER)
    deriv_i = rate * ive(0, rate * BARREL) / ive(1, rate * BARREL)
    deriv_k = -rate * BARREL / INNER * kve(0, rate * BARREL) / kve(1, rate * INNER) * np.exp(-rate * (BARREL - INNER))
    impedance = 0.2e-3 * (a * deriv_i + b * deriv_k) / (math.tau * BARREL * CONDUCTIVITY)
    return lambda r, z: a * increasing(r) + b * decreasing(r), impedance


def solve_positive_gradient(matrix, load):
    """! @brief 복소 확산을 풀고 유한성 및 이산 방정식의 잔차를 확인한다."""
    solution = spsolve(matrix, load)
    scale = max(np.linalg.norm(load), np.finfo(float).tiny)
    residual = np.linalg.norm(matrix @ solution - load) / scale
    if not np.all(np.isfinite(solution)) or residual > 1e-8:
        raise ValueError("축대칭 확산의 이산 방정식 잔차가 큽니다.")
    return solution, float(residual)


def volume(grid, frequency, boundary):
    """! @brief 셀 중심 플럭스의 직렬 재료와 반 셀 단자를 써 전력과 단자 반력을 구한다."""
    r, z, region, sigma = grid
    active = region >= 0
    ids = np.full(active.shape, -1, dtype=int)
    ids[active] = np.arange(active.sum())
    rc = (r[1:] + r[:-1]) / 2
    zc = (z[1:] + z[:-1]) / 2
    dr, dz = np.diff(r), np.diff(z)
    mass = (math.tau * frequency * MU * (dr / rc)[:, None] * dz[None, :])[active]
    diagonal = 1j * mass
    load = np.zeros(len(mass), dtype=complex)
    rows, cols, entries, links, terminals = [], [], [], [], []
    for axis_index in (0, 1):
        # @brief 좌표축을 바꾸면 같은 플럭스 조립으로 양방향 면을 방문한다.
        on = active if axis_index == 0 else active.T
        cells = ids if axis_index == 0 else ids.T
        material = region if axis_index == 0 else region.T
        conduct = sigma if axis_index == 0 else sigma.T
        positions, transverse = (r, zc) if axis_index == 0 else (z, rc)
        normal_steps, tangent_steps = (dr, dz) if axis_index == 0 else (dz, dr)
        i, j = np.nonzero(on[1:] & on[:-1])
        left, right = cells[i, j], cells[i + 1, j]
        ls = normal_steps[i] * conduct[i, j]
        rs = normal_steps[i + 1] * conduct[i + 1, j]
        radius = positions[i + 1] if axis_index == 0 else transverse[j]
        link = 2 * tangent_steps[j] / (radius * (ls + rs))
        np.add.at(diagonal, left, link)
        np.add.at(diagonal, right, link)
        rows.extend((left, right))
        cols.extend((right, left))
        entries.extend((-link, -link))
        links.append((left, right, link, ls / (ls + rs), material[i, j], material[i + 1, j]))
        for sign in (-1, 1):
            neighbor = np.zeros_like(on)
            if sign == -1:
                neighbor[1:] = on[:-1]
            else:
                neighbor[:-1] = on[1:]
            i, j = np.nonzero(on & ~neighbor)
            face = positions[i + (sign == 1)]
            radius, height = (face, transverse[j]) if axis_index == 0 else (transverse[j], face)
            value = boundary(radius, height)
            node = cells[i, j]
            link = 2 * tangent_steps[j] / (radius * normal_steps[i] * conduct[i, j])
            np.add.at(diagonal, node, link)
            np.add.at(load, node, link * value)
            terminals.append((node, link, value, material[i, j]))

    matrix = coo_matrix((np.concatenate(entries), (np.concatenate(rows), np.concatenate(cols))),
                        shape=(len(diagonal), len(diagonal))).tocsr() + diags(diagonal)
    q, residual = solve_positive_gradient(matrix, load)
    heat = np.zeros(len(NAME))
    for left, right, link, left_share, region_left, region_right in links:
        part = link * abs(q[left] - q[right])**2
        np.add.at(heat, region_left, part * left_share)
        np.add.at(heat, region_right, part * (1 - left_share))
    source = 0j
    for node, link, value, material in terminals:
        np.add.at(heat, material, link * abs(q[node] - value)**2)
        source += np.vdot(value, link * (value - q[node]))
    return summarize(heat, np.sum(mass * abs(q)**2), source, residual, len(q))


QUADRATURE = (np.ones((3, 3)) + 3 * np.eye(3)) / 6


def elements(grid, frequency, boundary):
    """! @brief 독립 삼각형의 기울기와 질량 약형을 적분해 전력과 경계 반력을 구한다."""
    r, z, region, sigma = grid
    active = region >= 0
    i, j = np.nonzero(active)
    participation = np.zeros((len(r), len(z)), dtype=np.uint8)
    for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
        participation[i + a, j + b] += 1
    ni, nj = np.nonzero(participation)
    ids = np.full(participation.shape, -1, dtype=int)
    ids[ni, nj] = np.arange(len(ni))
    ids4 = np.column_stack((ids[i, j], ids[i + 1, j], ids[i + 1, j + 1], ids[i, j + 1]))
    triangles = np.concatenate((ids4[:, [0, 1, 2]], ids4[:, [0, 2, 3]]))
    vertex = np.column_stack((r[ni], z[nj]))[triangles]
    u, v = vertex[:, 1] - vertex[:, 0], vertex[:, 2] - vertex[:, 0]
    twice = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    opposite = np.roll(vertex, -1, axis=1) - np.roll(vertex, 1, axis=1)
    gradients = np.stack((opposite[:, :, 1], -opposite[:, :, 0]), axis=-1) / twice[:, None, None]
    integral = (twice[:, None] / 6) / (vertex[:, :, 0] @ QUADRATURE.T)
    stiffness = (gradients @ gradients.transpose((0, 2, 1))
                 * (integral.sum(axis=1) / np.tile(sigma[active], 2))[:, None, None])
    mass = math.tau * frequency * MU * np.einsum("ek,ki,kj->eij", integral, QUADRATURE, QUADRATURE)
    matrix = coo_matrix(((stiffness + 1j * mass).ravel(),
                         (np.repeat(triangles, 3, axis=1).ravel(), np.tile(triangles, (1, 3)).ravel())),
                        shape=(len(ni), len(ni))).tocsr()
    fixed = participation[ni, nj] != 4
    free = np.flatnonzero(~fixed)
    q = np.zeros(len(ni), dtype=complex)
    q[fixed] = boundary(r[ni[fixed]], z[nj[fixed]])
    q[free], residual = solve_positive_gradient(matrix[free, :][:, free], -(matrix @ q)[free])
    values = q[triangles]
    heat = np.bincount(np.tile(region[active], 2), minlength=len(NAME),
                       weights=np.einsum("ei,eij,ej->e", values.conj(), stiffness, values).real)
    reactive = np.einsum("ei,eij,ej->", values.conj(), mass, values).real
    source = np.vdot(q[fixed], (matrix @ q)[fixed])
    return summarize(heat, reactive, source, residual, len(q))


def summarize(heat, reactive, source, residual, unknowns):
    """! @brief 1 A peak의 복소 입력과 체적 열에 대한 보존 검사를 수행한다."""
    impedance = complex(float(np.sum(heat)), float(reactive)) / math.tau
    closure = abs(source / math.tau / impedance - 1)
    if impedance.real <= 0 or impedance.imag <= 0 or closure > 1e-7:
        raise ValueError("복소 입력과 적분 전력 수지가 일치하지 않습니다.")
    return {"impedance_ohm": [impedance.real, impedance.imag], "source_impedance_ohm": [source.real / math.tau, source.imag / math.tau],
            "loss_w_at_1a_peak": {name: float(value / (2 * math.tau)) for name, value in zip(NAME, heat, strict=True)},
            "linear_residual": residual, "complex_power_relative_residual": closure, "unknowns": int(unknowns)}


def comparisons(grid, frequency, boundary):
    """! @brief 두 풀이가 독립적으로 보고한 복소 입력 및 영역별 열을 비교한다."""
    fvm, fem = (method(grid, frequency, boundary) for method in (volume, elements))
    difference = abs(complex(*fvm["impedance_ohm"]) / complex(*fem["impedance_ohm"]) - 1)
    return {"volume": fvm, "elements": fem, "complex_impedance_relative_difference": difference}


def run():
    """! @brief 각각의 GHz 표본에서 해석 배럴 대조와 유한 접합/급전 수렴을 기록한다."""
    references = []
    for frequency in FREQUENCIES:
        boundary, exact = cylinder(frequency)
        r = axis((INNER, BARREL), LEVELS[-1])
        z = np.linspace(0, 0.2e-3, 9)
        shape = (len(r) - 1, len(z) - 1)
        reference = comparisons((r, z, np.zeros(shape, dtype=int), np.full(shape, CONDUCTIVITY)), frequency, boundary)
        errors = {name: abs(complex(*reference[name]["impedance_ohm"]) / exact - 1) for name in ("volume", "elements")}
        if max(errors.values()) > 0.005:
            raise ValueError(f"직선 배럴의 해석 기준 오차가 0.5%를 넘었습니다: {errors}")
        references.append({"frequency_hz": frequency, "analytic_impedance_ohm": [exact.real, exact.imag],
                           "relative_errors": errors, **reference})
    cases = []
    for ratio, profile in ((1.0, "spread"), (0.1, "spread"), (0.1, "surface_concentrated")):
        settings = {"joint_conductivity_ratio": ratio, "terminal_profile": profile}
        rows = []
        for frequency in FREQUENCIES:
            def boundary(r, z):
                return feed_boundary(r, z, frequency, profile)

            levels = []
            for level in LEVELS:
                results = comparisons(structure(level, ratio), frequency, boundary)
                levels.append({"cells_per_skin_depth_in_surface_band_at_12ghz": level, **results})
            final = levels[-1]
            previous = levels[-2]
            finer = max(abs(complex(*final[name]["impedance_ohm"]) / complex(*previous[name]["impedance_ohm"]) - 1)
                        for name in ("volume", "elements"))
            changes = {
                name: abs(final["volume"]["loss_w_at_1a_peak"][name] / final["elements"]["loss_w_at_1a_peak"][name] - 1)
                for name in NAME
            }
            rows.append({"frequency_hz": frequency, "refinement_relative_difference": finer,
                         "final_component_loss_relative_differences": changes,
                         "fixture_gate_passed": max(final["complex_impedance_relative_difference"], finer) < 0.02
                         and max(changes.values()) < 0.02, "levels": levels})
            print(f"{ratio} {profile} {frequency:g} refined {finer:.6f}", file=sys.stderr, flush=True)
        cases.append({**settings, "frequencies": rows})
    return {"schema": "rfad.axisymmetric-ghz-pth-junction-reference/0.1", "scope": "synthetic_conductor_magnetic_diffusion",
            "peak_current_a": 1.0, "geometry_m": {"inner": INNER, "barrel_outer": BARREL, "pad_outer": PAD,
                                                 "height": HEIGHT, "pad_thickness": PAD_THICKNESS,
                                                 "joint_thickness": JOINT_THICKNESS, "feed_region_start_r": FEED_BEGIN},
            "conductivity_s_per_m": CONDUCTIVITY, "native_or_measurement_validated": False,
            "straight_barrel_checks": references, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run()
    print(json.dumps(report, allow_nan=False))
    raise SystemExit(0 if all(row["fixture_gate_passed"] for case in report["cases"] for row in case["frequencies"]) else 1)
