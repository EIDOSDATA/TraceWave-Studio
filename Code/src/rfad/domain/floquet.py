"""! @brief 일차원 유전체 격자의 Bloch 경계와 회절 차수별 전력을 계산한다."""

import math

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_hash
from rfad.domain.network_data import fail, finite


PROFILE = "rfad.floquet-lamellar/0.1"
LIGHT_SPEED = 299792458


def _inputs(case):
    """! @brief 수동 무손실 유전체 셀과 유한 계산 예산을 확인한다."""
    keys = {"period_mm", "thickness_mm", "epsilon_left", "epsilon_right", "stripes",
            "frequencies_hz", "incidence_deg", "polarization", "orders"}
    if type(case) is not dict or set(case) != keys:
        fail("격자의 주기, 두께, 유전체, 입사 조건과 회절 차수를 지정하세요.", "case")
    for key in ("period_mm", "thickness_mm", "epsilon_left", "epsilon_right"):
        if not 0 < finite(case[key], key) <= 1e6:
            fail("유한한 양의 재료값과 치수가 필요합니다.", key)
    if abs(finite(case["incidence_deg"], "incidence_deg")) >= 90 or case["polarization"] not in ("TE", "TM"):
        fail("입사각은 -90도와 90도 사이이며 편파는 TE 또는 TM입니다.", "incidence_deg")
    frequencies = case["frequencies_hz"]
    if (type(frequencies) is not list or not 1 <= len(frequencies) <= 101
            or any(not 1 <= finite(f, "frequencies_hz") <= 1e15 for f in frequencies)
            or any(b <= a for a, b in zip(frequencies, frequencies[1:]))):
        fail("증가하는 양의 주파수를 1~101개 입력하세요.", "frequencies_hz")
    if type(case["orders"]) is not int or not 1 <= case["orders"] <= 32:
        fail("최대 회절 차수는 1~32입니다.", "orders", "E_RESOURCE")
    stripes = case["stripes"]
    if type(stripes) is not list or not 1 <= len(stripes) <= 64:
        fail("한 셀의 유전체 띠를 1~64개 지정하세요.", "stripes")
    for stripe in stripes:
        if type(stripe) is not dict or set(stripe) != {"fraction", "epsilon_r"}:
            fail("유전체 띠마다 폭의 비와 비유전율이 필요합니다.", "stripes")
        if not 0 < finite(stripe["fraction"], "stripes.fraction") <= 1:
            fail("띠 폭의 비는 0보다 크고 1 이하여야 합니다.", "stripes.fraction")
        if not 0 < finite(stripe["epsilon_r"], "stripes.epsilon_r") <= 1e6:
            fail("띠의 비유전율은 유한한 양수여야 합니다.", "stripes.epsilon_r")
    if abs(math.fsum(stripe["fraction"] for stripe in stripes) - 1) > 1e-12:
        fail("유전체 띠 폭의 합으로 한 셀을 채워야 합니다.", "stripes.fraction")


def _toeplitz(np, harmonics, stripes, reciprocal=False):
    """! @brief x 방향의 정확한 구간 Fourier 계수로 곱셈 연산을 구성한다."""
    differences = harmonics[:, None] - harmonics[None, :]
    result = np.zeros(differences.shape, dtype=complex)
    start = 0.0
    for stripe in stripes:
        width = stripe["fraction"]
        epsilon = stripe["epsilon_r"]
        value = 1 / epsilon if reciprocal else epsilon
        result += (value * width * np.sinc(differences * width)
                   * np.exp(-2j * np.pi * differences * (start + width / 2)))
        start += width
    return result


def _longitudinal(np, eig, scale):
    """! @brief 진행 및 감쇠 방향을 정하고 차단점의 퇴화한 기저를 진단한다."""
    if np.min(np.abs(eig)) <= 1e-12 * scale:
        fail("회절 또는 내부 모드가 차단점에 있습니다. 인접 주파수에서 다시 계산하세요.",
             "frequencies_hz", "E_CONFLICT")
    return np.sqrt(eig.astype(complex))


def _sample(np, case, frequency, orders, epsilon, eta):
    """! @brief 두 면의 접선 장을 연속으로 맞추고 소멸파의 증가 지수를 피한다."""
    left, right = case["epsilon_left"], case["epsilon_right"]
    k0 = 2 * math.pi * frequency / LIGHT_SPEED
    period = case["period_mm"] * 1e-3
    kx = math.sqrt(left) * math.sin(math.radians(case["incidence_deg"]))
    spacing = period * k0
    if not spacing > 1e-10:
        fail("주기와 주파수의 조합이 수치 범위를 넘습니다.", "period_mm", "E_RESOURCE")
    spacing = 2 * math.pi / spacing
    if spacing * (case["orders"] + 1) - abs(kx) <= math.sqrt(max(left, right)):
        fail("전파할 수 있는 회절 차수를 모두 포함하도록 orders를 높이세요.", "orders", "E_RESOURCE")
    transverse = kx + orders * spacing
    if not np.isfinite(transverse).all() or np.max(abs(transverse)) > 1e10:
        fail("주기와 주파수의 조합이 수치 범위를 넘습니다.", "period_mm", "E_RESOURCE")
    tm = eta is not None
    q_left = _longitudinal(np, left - transverse**2, left)
    q_right = _longitudinal(np, right - transverse**2, right)
    y_left, y_right = (q_left / left, q_right / right) if tm else (q_left, q_right)
    identity = np.eye(len(orders))
    if tm:
        # @brief 수직 전속과 접선 전계의 연속성에 따라 유전율과 역유전율 행렬을 분리한다.
        eig_eta, axes = np.linalg.eigh(eta)
        root = (axes / np.sqrt(eig_eta)) @ axes.conj().T
        operator = root @ (identity - transverse[:, None] * np.linalg.inv(epsilon) * transverse) @ root
        values, vectors = np.linalg.eigh(operator)
        field = root @ vectors
        flux = eta @ field
    else:
        values, field = np.linalg.eigh(epsilon - np.diag(transverse**2))
        flux = field
    q = _longitudinal(np, values, max(left, right, 1))
    flux = flux * q
    decay = np.exp(1j * q * (k0 * case["thickness_mm"] * 1e-3))
    incident = identity[:, case["orders"]]
    zero = np.zeros_like(identity)
    matrix = np.block([[field, field * decay, -identity, zero],
                       [flux, -flux * decay, np.diag(y_left), zero],
                       [field * decay, field, zero, -identity],
                       [flux * decay, -flux, zero, -np.diag(y_right)]])
    rhs = np.concatenate((incident, y_left * incident, 0 * incident, 0 * incident))
    solution = np.linalg.solve(matrix, rhs)
    if not np.isfinite(solution).all() or np.max(np.abs(matrix @ solution - rhs)) > 1e-8:
        fail("접선장 연속 조건의 수치 잔차가 기준을 넘었습니다.", "frequencies_hz", "E_CONFLICT")
    reflected, transmitted = np.split(solution, 4)[2:]
    incoming = y_left[case["orders"]].real
    rows = []
    for i, order in enumerate(orders):
        rows.append({"order": int(order), "kx_per_m": float(k0 * transverse[i]),
                     "reflection_ri": [float(reflected[i].real), float(reflected[i].imag)],
                     "transmission_ri": [float(transmitted[i].real), float(transmitted[i].imag)],
                     "reflected_power": float(abs(reflected[i])**2 * y_left[i].real / incoming),
                     "transmitted_power": float(abs(transmitted[i])**2 * y_right[i].real / incoming)})
    phase = k0 * kx * period
    residual = abs(1 - math.fsum(row["reflected_power"] + row["transmitted_power"] for row in rows))
    return {"frequency_hz": frequency, "boundary_factor_ri": [math.cos(phase), math.sin(phase)],
            "energy_balance_residual": residual, "orders": rows}


def _level(np, case):
    """! @brief 하나의 Fourier 절단 수준에서 선언한 모든 주파수를 계산한다."""
    orders = np.arange(-case["orders"], case["orders"] + 1)
    epsilon = _toeplitz(np, orders, case["stripes"])
    eta = _toeplitz(np, orders, case["stripes"], True) if case["polarization"] == "TM" else None
    return [_sample(np, case, f, orders, epsilon, eta) for f in case["frequencies_hz"]]


def solve(case):
    """! @brief 경계 위상과 차수별 복소장을 보존하고 전파 차수의 절단 민감도를 비교한다."""
    _inputs(case)
    np, _, _, engine = network_backend.runtime()
    try:
        results = _level(np, case)
        comparison = _level(np, {**case, "orders": case["orders"] + 2})
    except np.linalg.LinAlgError:
        fail("이 조건의 Floquet 경계 행렬을 풀 수 없습니다.", "frequencies_hz", "E_CONFLICT")
    for sample, other in zip(results, comparison):
        by_order = {row["order"]: row for row in sample["orders"]}
        deltas = [abs(row[key] - by_order.get(row["order"], {}).get(key, 0))
                  for row in other["orders"] for key in ("reflected_power", "transmitted_power")]
        sample["next_order_power_delta_max"] = max(deltas)
    return {"schema": PROFILE, "input": case, "input_sha256": canonical_hash(case), "engine": engine,
            "comparison_orders": case["orders"] + 2,
            "spatial_convention": "exp(+j*kx*x), exp(+j*kz*z) forward; exp(-j*omega*t)",
            "amplitude_basis": "tangential_Hy" if case["polarization"] == "TM" else "tangential_Ey",
            "samples": results}
