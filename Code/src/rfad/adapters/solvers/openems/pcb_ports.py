"""! @brief 봉인된 lumped 전압/전류의 펄스 Fourier 스펙트럼을 공통 규약으로 읽는다."""

from .native import require


def spectra(raw, frequencies):
    """! @brief V*s와 A*s를 보존하고 임의 RMS 또는 정현파 전력으로 바꾸지 않는다."""
    import numpy as np

    result = []
    for name in ("port_ut_1", "port_it_1"):
        data = np.loadtxt(raw / name, comments=("#", "%"))
        require(data.ndim == 2 and data.shape[0] >= 3 and data.shape[1] >= 2 and np.all(np.isfinite(data)),
                "포트 원시 데이터가 불완전합니다.", "E_MISSING_ARTIFACT")
        times, values = data[:, 0], data[:, 1]
        steps = np.diff(times)
        require(np.all(steps > 0) and np.allclose(steps, steps[0], rtol=5e-4, atol=0), "포트 시간축이 균일하지 않습니다.")
        result.append(np.asarray([2 * steps[0] * np.sum(values * np.exp(-1j * 2 * np.pi * f * times)) for f in frequencies]))
    return tuple(result)
