"""! @brief 두 축 Bloch 경계에서 적층 단위셀의 완전 벡터 회절과 흡수를 계산한다."""

from dataclasses import dataclass
import math

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_projection import EPSILON0
from rfad.domain.floquet import LIGHT_SPEED
from rfad.domain.network_data import fail
from rfad.domain.periodic_cell import raster, validate


PROFILE = "rfad.floquet-pcb/0.1"
FIELD_OFFSETS = ((0.75, 0.25), (0.25, 0.75), (0.25, 0.25))


@dataclass
class _Modes:
    """! @brief 동일 평면에 정의된 접선 E와 Z0*(Hy,-Hx)의 진행 모드 기저."""

    q: object
    electric: object
    flux: object


def _wavevectors(np, case, grid, k0):
    """! @brief 표본에서 전파 차수 누락 및 Rayleigh 차단점을 진단한다."""
    period = np.asarray(case["period_mm"]) * 1e-3
    phi, theta = map(math.radians, (case["phi_deg"], case["theta_deg"]))
    azimuth_axis = np.array([math.cos(phi), math.sin(phi)])
    incident = azimuth_axis * (math.sqrt(case["epsilon_left"]) * math.sin(theta))
    spacing = (2 * math.pi / k0) / period
    outer = math.sqrt(max(case["epsilon_left"], case["epsilon_right"]))
    center = abs(incident) / spacing
    nearest = np.rint(center)
    nearest_outside = np.maximum(nearest, np.asarray(grid) // 2 + 1)
    for axis in range(2):
        outer_axis = (nearest_outside[axis] - center[axis]) * spacing[axis]
        other_axis = (nearest[1 - axis] - center[1 - axis]) * spacing[1 - axis]
        if math.hypot(outer_axis, other_axis) > outer:
            continue
        fail("전파 회절 차수를 모두 포함하도록 격자를 늘리십시오.", "grid", "E_RESOURCE")
    orders = np.stack(np.meshgrid(*(np.fft.fftfreq(n, d=1 / n).round().astype(int) for n in grid),
                                  indexing="ij"), axis=-1).reshape(-1, 2)
    transverse = incident + orders * spacing
    if np.max(np.abs(transverse)) > 1e7:
        fail("주기와 주파수 조합이 수치 범위를 넘었습니다.", "period_mm", "E_RESOURCE")
    radial = np.linalg.norm(transverse, axis=1)
    parallel = np.broadcast_to(azimuth_axis, transverse.shape).copy()
    active = radial > 1e-13
    parallel[active] = transverse[active] / radial[active, None]
    return orders, transverse, radial, parallel, incident * (k0 * period)


def _uniform(np, epsilon, radial, parallel, *, exterior=False):
    """! @brief 균일 매질의 TE/TM 접선 전계, 위상 및 어드미턴스를 해석식으로 구한다."""
    values = epsilon - radial**2
    if np.min(np.abs(values)) <= 1e-12 * max(1, abs(epsilon)):
        label = "외부 회절" if exterior else "층 내부"
        fail(label + " 모드가 차단점에 있습니다. 인접 주파수를 사용하십시오.", "frequencies_hz", "E_CONFLICT")
    q = np.sqrt(values.astype(complex))
    px, py = parallel.T
    electric = np.block([[-np.diag(py), np.diag(px)], [np.diag(px), np.diag(py)]])
    admittance = np.concatenate((q, epsilon / q))
    return _Modes(np.tile(q, 2), electric, electric * admittance), admittance


def _basis(np, grid, orders, offsets):
    """! @brief 각 E 성분에 맞춘 어긋난 Fourier 표본 변환을 만든다."""
    axes = [(np.arange(n) + offset) / n for n, offset in zip(grid, offsets)]
    points = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 2)
    return np.exp(2j * math.pi * (points @ orders.T)) / math.sqrt(len(orders))


def _stripe_operators(np, case, layer, orders, materials):
    """! @brief 무손실 일차원 띠의 정확한 Fourier 계수와 경계 연속 규칙을 적용한다."""
    if not layer["regions"]:
        return None
    names = list(case["materials"])
    background = materials[names.index(layer["background"])]
    periods = case["period_mm"]
    for axis in (0, 1):
        spans = []
        for region in layer["regions"]:
            points = region["outer"]
            x = sorted({p[axis] for p in points})
            y = {p[1 - axis] for p in points}
            if (region["holes"] or len(points) != 4 or len(x) != 2 or y != {0, periods[1 - axis]}
                    or {(p[axis], p[1 - axis]) for p in points} != {(i, j) for i in x for j in y}):
                break
            epsilon = materials[names.index(region["material"])]
            spans.append((x[0], x[1], epsilon))
        if len(spans) != len(layer["regions"]) or background.imag != 0 or any(v.imag != 0 for _, _, v in spans):
            continue
        spans.sort()
        if any(b > c for (_, b, _), (c, _, _) in zip(spans, spans[1:])):
            continue
        numbers = orders[:, axis]
        differences = numbers[:, None] - numbers
        same = orders[:, 1 - axis, None] == orders[:, 1 - axis]
        eye = np.eye(len(orders), dtype=complex)
        epsilon = background * eye
        reciprocal = eye / background
        for start, stop, value in spans:
            width = (stop - start) / periods[axis]
            middle = (start + stop) / (2 * periods[axis])
            cell = (same * width * np.sinc(differences * width)
                    * np.exp(-2j * math.pi * differences * middle))
            epsilon += (value - background) * cell
            reciprocal += (1 / value - 1 / background) * cell
        tangential = [epsilon, epsilon]
        tangential[axis] = np.linalg.solve(reciprocal, eye)
        return (*tangential, np.linalg.solve(epsilon, eye))
    return None


def _sample_operators(epsilons, bases):
    """! @brief 이중 주기 층의 엇갈린 표본에서 국소 유전율 행렬을 구성한다."""
    ex, ey, ez = epsilons
    ux, uy, uz = bases
    return (ux.conj().T @ (ex[:, None] * ux), uy.conj().T @ (ey[:, None] * uy),
            uz.conj().T @ (uz / ez[:, None]))


def _modes(np, linalg, operators, transverse):
    """! @brief z 방향 접선 Maxwell 고유 문제에서 양방향 모드 기저를 구한다."""
    dx, dy, reciprocal = operators
    kx, ky = transverse.T

    cross = np.diag(kx * ky)
    p = np.block([[np.eye(len(kx)) - kx[:, None] * reciprocal * kx, -kx[:, None] * reciprocal * ky],
                  [-ky[:, None] * reciprocal * kx, np.eye(len(kx)) - ky[:, None] * reciprocal * ky]])
    q_operator = np.block([[dx - np.diag(ky**2), cross], [cross, dy - np.diag(kx**2)]])
    values, electric = linalg.eig(p @ q_operator, check_finite=False)
    if not np.isfinite(values).all() or np.min(abs(values)) <= 1e-12:
        fail("적층 내부 모드를 분리할 수 없습니다.", "layers", "E_CONFLICT")
    q = np.sqrt(values)
    # @brief 수치 오차 범위의 작은 음의 감쇠는 제거하고 나머지는 감쇠 방향으로 분류한다.
    nearly_real = abs(q.imag) <= 1e-11 * np.maximum(1, abs(q.real))
    q[nearly_real] = q[nearly_real].real
    q[q.imag < 0] *= -1
    flux = (q_operator @ electric) / q
    scale = np.maximum(np.linalg.norm(electric, axis=0), np.linalg.norm(flux, axis=0))
    return _Modes(q, electric / scale, flux / scale)


def _interfaces(np, linalg, modes, decay, incident):
    """! @brief 소멸파 증가 지수 없이 뒤쪽 반사를 합성하고 실제 여기의 층별 진폭을 복원한다."""
    width = len(incident)
    load = np.zeros((width, width), dtype=complex)
    reflection, transmission = [], []
    for left, right in reversed(list(zip(modes[:-1], modes[1:]))):
        electric_load = right.electric + right.electric @ load
        flux_load = right.flux - right.flux @ load
        matrix = np.block([[left.electric, -electric_load], [-left.flux, -flux_load]])
        rhs = -np.vstack((left.electric, left.flux))
        solution = linalg.solve(matrix, rhs, check_finite=False)
        if not np.isfinite(solution).all() or np.max(abs(matrix @ solution - rhs)) > 2e-7 * np.max(abs(rhs)):
            fail("접면의 접선장 연속 잔차가 수치 기준을 넘었습니다.", "layers", "E_CONFLICT")
        reflected, transmitted = np.split(solution, 2)
        reflection.append(reflected)
        transmission.append(transmitted)
        # @brief 앞층 적분에서 사용할 뒷면 반사와 앞면 전달을 그대로 보존한다.
        current_prop = decay[len(decay) - len(reflection) - 1]
        load = current_prop[:, None] * reflected * current_prop
    forward = incident
    amplitudes = []
    for index, (send, prop) in enumerate(zip(reversed(transmission), decay[1:])):
        front = send @ forward
        forward = prop * front
        if index < len(modes) - 2:
            back = reflection[-index - 2] @ forward
            amplitudes.append((front, back))
    return reflection[-1] @ incident, forward, amplitudes


def _exp_integral(np, argument):
    """! @brief 두 감쇠 인자가 일치하는 적분의 제거 가능 특이점을 처리한다."""
    result = np.ones_like(argument)
    nonzero = abs(argument) > 0
    result[nonzero] = np.expm1(argument[nonzero]) / argument[nonzero]
    return result


def _absorption(np, mode, amplitudes, layers, bases, values, transverse, depth):
    """! @brief 층별 복소 전계를 z로 해석 적분하여 재료별 Joule 전력을 구한다."""
    attenuation = -1j * mode.q * depth
    same = _exp_integral(np, -(attenuation.conj()[:, None] + attenuation))
    diff = attenuation.conj()[:, None] - attenuation
    left = diff.real >= 0
    cross = np.where(left, np.exp(-attenuation)[None, :], np.exp(-attenuation.conj())[:, None])
    cross *= _exp_integral(np, np.where(left, -diff, diff))
    front, back = amplitudes
    same *= front.conj()[:, None] * front + back.conj()[:, None] * back
    cross *= 2 * front.conj()[:, None] * back

    width = len(transverse)
    ex, ey = np.split(mode.electric, 2)
    kx, ky = transverse.T
    gx, gy = np.split(mode.flux, 2)
    ez = -(bases[2] @ (kx[:, None] * gx + ky[:, None] * gy)) / values[2][:, None]
    fields = (bases[0] @ ex, bases[1] @ ey, ez)
    absorption = {}
    for label in sorted(set(np.concatenate(layers))):
        if not any(np.any((labels == label) & (eps.imag > 0)) for labels, eps in zip(layers, values)):
            continue
        power = 0.0
        for component, (field, labels, eps) in enumerate(zip(fields, layers, values)):
            mask = labels == label
            samples = field[mask]
            gram = samples.conj().T @ (eps[mask].imag[:, None] * samples)
            power += np.sum(gram * (same + (-cross if component == 2 else cross))).real
        absorption[int(label)] = float(depth * power)
    return absorption


def _ri(value):
    """! @brief 결과 JSON의 복소수 표현을 만든다."""
    return [float(value.real), float(value.imag)]


def _sample(np, linalg, case, frequency, grid, labels):
    """! @brief 입사 전력으로 회절 및 체적 흡수를 정규화하고 수지를 검사한다."""
    k0 = 2 * math.pi * frequency / LIGHT_SPEED
    orders, transverse, radial, parallel, phase = _wavevectors(np, case, grid, k0)
    left, left_y = _uniform(np, case["epsilon_left"], radial, parallel, exterior=True)
    right, right_y = _uniform(np, case["epsilon_right"], radial, parallel, exterior=True)
    materials = [m["epsilon_r"] * (1 + 1j * m["tan_delta"])
                 + 1j * m["conductivity_s_per_m"] / (2 * math.pi * frequency * EPSILON0)
                 for m in case["materials"].values()]
    materials = np.asarray(materials)
    modes = [left]
    bases = tuple(_basis(np, grid, orders, offset) for offset in FIELD_OFFSETS)
    epsilons = [tuple(materials[component] for component in layer) for layer in labels]
    depths = [layer["thickness_mm"] * k0 * 1e-3 for layer in case["layers"]]
    spacing = k0 * np.asarray(case["period_mm"]) * 1e-3 / grid
    staggered_k = 2 * np.sin(0.5 * transverse * spacing) / spacing
    layer_wavevectors = []
    for specification, layer, values in zip(case["layers"], labels, epsilons):
        scalar = layer[0][0]
        if all(np.all(component == scalar) for component in layer):
            modes.append(_uniform(np, materials[scalar], radial, parallel)[0])
            layer_wavevectors.append(transverse)
        else:
            operators = _stripe_operators(np, case, specification, orders, materials)
            wavevectors = transverse
            if operators is None:
                operators = _sample_operators(values, bases)
                wavevectors = staggered_k
            modes.append(_modes(np, linalg, operators, wavevectors))
            layer_wavevectors.append(wavevectors)
    modes.append(right)
    unit = np.ones(len(left.q))
    decay = [unit, *(np.exp(1j * mode.q * depth) for mode, depth in zip(modes[1:-1], depths)), unit]
    incident = np.zeros(len(left.q), dtype=complex)
    source = 0 if case["polarization"] == "TE" else len(orders)
    incident[source] = 1
    incoming = left_y[source].real
    r, t, amplitudes = _interfaces(np, linalg, modes, decay, incident)
    reflected = (abs(r)**2 * (left_y.real / incoming)).reshape(2, -1)
    transmitted = (abs(t)**2 * (right_y.real / incoming)).reshape(2, -1)
    absorption_layers = []
    names = list(case["materials"])
    for mode, fields, grid_layer, values, depth, wavevectors in zip(
            modes[1:-1], amplitudes, labels, epsilons, depths, layer_wavevectors):
        if all(np.all(component.imag == 0) for component in values):
            absorption_layers.append({})
            continue
        layer_loss = _absorption(np, mode, fields, grid_layer, bases, values, wavevectors, depth)
        absorption_layers.append({names[key]: float(value / incoming) for key, value in layer_loss.items()})
    absorption = {name: math.fsum(layer.get(name, 0) for layer in absorption_layers) for name in names}
    totals = {"reflected": float(reflected.sum()), "transmitted": float(transmitted.sum()),
              "absorbed": math.fsum(absorption.values())}
    residual = abs(1 - math.fsum(totals.values()))
    if not math.isfinite(residual) or residual > 2e-6 or min(absorption.values()) < -1e-9:
        fail("회절과 독립 체적 흡수의 전력 수지 오차가 기준을 넘었습니다.", "grid", "E_CONFLICT")
    return {"frequency_hz": frequency, "boundary_factor_ri": [_ri(v) for v in np.exp(1j * phase)],
            "power": totals, "absorption_by_material": absorption, "absorption_by_layer": absorption_layers,
            "energy_balance_residual": residual,
            "orders": [
                {"order": order.tolist(), "kt_per_m": (k * k0).tolist(),
                 "kz_left_ri_per_m": _ri(left.q[i] * k0), "kz_right_ri_per_m": _ri(right.q[i] * k0),
                 "reflection_ri": [_ri(v) for v in r[i::len(orders)]],
                 "transmission_ri": [_ri(v) for v in t[i::len(orders)]],
                 "reflected_power": reflected[:, i].tolist(), "transmitted_power": transmitted[:, i].tolist()}
                for i, (order, k) in enumerate(zip(orders, transverse))]}


def solve(case):
    """! @brief 두 해상도의 회절 및 재료별 흡수 변화를 원문과 함께 저장한다."""
    validate(case)
    np, scipy, _, engine = network_backend.runtime()
    grids = (case["grid"], case["comparison_grid"])
    results = []
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for grid in grids:
                labels = [tuple(raster(np, case, layer, grid, offsets) for offsets in FIELD_OFFSETS)
                          for layer in case["layers"]]
                results.append([_sample(np, scipy.linalg, case, f, grid, labels)
                                for f in case["frequencies_hz"]])
    except (np.linalg.LinAlgError, FloatingPointError):
        fail("적층 Floquet 경계 행렬이 수치 범위를 벗어났습니다.", "grid", "E_CONFLICT")
    for sample, other in zip(*results):
        prior = {tuple(row["order"]): row for row in sample["orders"]}
        delta = [abs(a - b) for row in other["orders"] for field in ("reflected_power", "transmitted_power")
                 for a, b in zip(row[field], prior.get(tuple(row["order"]), {}).get(field, [0, 0]))]
        sample["comparison"] = {
            "max_order_polarization_power_delta": max(delta),
            "absorption_delta_by_material": {key: other["absorption_by_material"][key] - value
                                             for key, value in sample["absorption_by_material"].items()},
            "power": other["power"],
            "absorption_by_material": other["absorption_by_material"],
            "energy_balance_residual": other["energy_balance_residual"],
        }
    return {"schema": PROFILE, "input": case, "input_sha256": canonical_hash(case), "engine": engine,
            "spatial_convention": "exp(+j*k.r), exp(-j*omega*t), incidence from z=0 toward +z",
            "amplitude_basis": ["TE tangential E perpendicular to kt", "TM tangential E parallel to kt"],
            "zero_kt_basis": "TE perpendicular to incidence azimuth, TM parallel to incidence azimuth",
            "reference_planes_mm": [0, math.fsum(layer["thickness_mm"] for layer in case["layers"])],
            "samples": results[0]}
