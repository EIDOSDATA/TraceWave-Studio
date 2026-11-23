"""! @brief 폭이 다른 직사각 PEC 도파관의 TE_m0 모드 결합을 계산한다."""

import math

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_hash
from rfad.domain.floquet import LIGHT_SPEED
from rfad.domain.network_data import fail, finite


PROFILE = "rfad.rectangular-te-m0-step/0.1"


def _configuration(case):
    """! @brief 좌표, 단면, 매질과 유한한 모드 예산을 검사한다."""
    keys = {"wide_mm", "narrow_mm", "offset_mm", "epsilon_r", "frequencies_hz", "modes"}
    if type(case) is not dict or set(case) != keys:
        fail("넓은 쪽, 좁은 쪽, 오프셋, 유전율, 주파수와 모드 수를 입력하세요.", "case")
    width, narrow, offset, epsilon = [finite(case[key], key)
                                      for key in ("wide_mm", "narrow_mm", "offset_mm", "epsilon_r")]
    if not 0 < narrow <= width <= 1e6 or not 0 <= offset <= width - narrow or not 0 < epsilon <= 1e6:
        fail("좁은 단면의 개구를 넓은 단면 내부에 두고 양의 재료값을 입력하세요.", "case", "E_GEOMETRY")
    limit = case["modes"]
    if type(limit) is not int or not 2 <= limit <= 40 or (limit + 4) * width / narrow > 320:
        fail("좁은 쪽 모드 수 2~40개와 넓은 쪽 320개 이하의 계산 예산을 확인하세요.", "modes", "E_RESOURCE")
    frequencies = case["frequencies_hz"]
    if (type(frequencies) is not list or not 1 <= len(frequencies) <= 101
            or any(not 1 <= finite(f, "frequencies_hz") <= 1e15 for f in frequencies)
            or any(left >= right for left, right in zip(frequencies, frequencies[1:]))):
        fail("증가하는 양의 주파수를 1~101개 입력하세요.", "frequencies_hz")
    return width, narrow, offset, epsilon


def _overlap(np, wide, narrow, offset, m, n):
    """! @brief 단위 L2 전계 모드의 개구 겹침을 sinc 적분으로 직접 구한다."""
    a, b = np.pi * m[:, None] / wide, np.pi * n[None, :] / narrow
    def integral(rate):
        """! @brief 주파수 차 또는 합의 코사인을 좁은 개구에서 적분한다."""
        middle = offset * a + rate * narrow / 2
        return np.cos(middle) * np.sinc(rate * narrow / (2 * np.pi))
    return math.sqrt(narrow / wide) * (integral(a - b) - integral(a + b))


def _admittance(np, frequency, epsilon, width, count):
    """! @brief 진행 또는 소멸 모드의 정규화된 접선 어드미턴스를 계산한다."""
    k0 = 2 * np.pi * frequency / LIGHT_SPEED
    all_modes = np.arange(1, count + 2)
    squared = epsilon - (all_modes * np.pi / (width * 1e-3 * k0)) ** 2
    if np.min(abs(squared)) <= 1e-12 * epsilon:
        fail("입력 주파수가 TE 모드 차단점에 있습니다.", "frequencies_hz", "E_CONFLICT")
    if squared[-1] > 0:
        fail("모든 전파 모드를 포함하도록 모드 수를 늘리세요.", "modes", "E_RESOURCE")
    return np.sqrt(squared[:-1].astype(complex))


def _level(np, case, geometry, count):
    """! @brief 개구 경계에서 전계와 자계를 맞춰 양쪽 모든 전파 모드를 여기한다."""
    wide, narrow, offset, epsilon = geometry
    m_count = math.ceil(count * wide / narrow)
    aperture = _overlap(np, wide, narrow, offset, np.arange(1, m_count+1), np.arange(1, count+1))
    results = []
    for frequency in case["frequencies_hz"]:
        yw = _admittance(np, frequency, epsilon, wide, m_count)
        yn = _admittance(np, frequency, epsilon, narrow, count)
        left, right = np.flatnonzero(yw.real > 0), np.flatnonzero(yn.real > 0)
        if not len(left):
            fail("이 주파수에서 여기할 수 있는 TE 전파 모드가 없습니다.", "frequencies_hz", "E_CONFLICT")
        rhs = 2 * np.column_stack((aperture[left, :].T * yw[left],
                                   np.eye(count)[:, right] * yn[right]))
        matrix = (aperture.T * yw) @ aperture + np.diag(yn)
        aperture_e = np.linalg.solve(matrix, rhs)
        amplitudes = np.vstack((aperture[left] @ aperture_e, aperture_e[right])) - np.eye(len(left)+len(right))
        norms = np.sqrt(np.r_[yw[left].real, yn[right].real])
        s = amplitudes * (norms[:, None] / norms[None, :])
        if not np.isfinite(s).all() or np.max(abs(matrix @ aperture_e-rhs)) > 1e-8:
            fail("개구 모드 결합의 수치 잔차가 기준을 넘었습니다.", "frequencies_hz", "E_CONFLICT")
        names = [f"{side}:TE({int(index)+1},0)" for side, indices in (("wide", left), ("narrow", right)) for index in indices]
        results.append((names, s))
    return results


def solve(case):
    """! @brief 모드 이름과 양쪽 기준면을 보존하고 전체 복소 변환 행렬을 계산한다."""
    geometry = _configuration(case)
    np, _, _, engine = network_backend.runtime()
    try:
        results = _level(np, case, geometry, case["modes"])
        comparison = _level(np, case, geometry, case["modes"] + 4)
    except np.linalg.LinAlgError:
        fail("개구 모드 행렬을 풀 수 없습니다.", "frequencies_hz", "E_CONFLICT")
    samples = []
    for f, (names, matrix), (_, refined) in zip(case["frequencies_hz"], results, comparison):
        samples.append({"frequency_hz": f, "channels": names,
                        "s_ri": np.stack((matrix.real, matrix.imag), axis=-1).tolist(),
                        "energy_residual_max": float(np.max(abs(matrix.conj().T @ matrix - np.eye(len(names))))),
                        "reciprocity_residual_max": float(np.max(abs(matrix-matrix.T))),
                        "next_basis_delta_max": float(np.max(abs(matrix-refined)))})
    return {"schema": PROFILE, "input": case, "input_sha256": canonical_hash(case), "engine": engine,
            "phasor_convention": "exp(-j*omega*t)", "basis": "unit_power_TE_m0",
            "reference_planes": {"wide": "wide side of junction", "narrow": "narrow side of junction"},
            "comparison_modes": case["modes"] + 4, "samples": samples}
