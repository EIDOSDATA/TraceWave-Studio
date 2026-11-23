"""! @brief 실제 도파관 모드의 상호 변환과 독립 개구 적분을 확인한다."""

import json
import math
from pathlib import Path
import unittest

from rfad.domain.errors import ProjectError
from rfad.domain.waveguide_modes import solve
from test_network_domain import ENGINE_READY


CASE = json.loads((Path(__file__).resolve().parents[1] / "fixtures/waveguide_te_step.json").read_bytes())


@unittest.skipUnless(ENGINE_READY, "고정 RF 수치 엔진이 필요합니다.")
class WaveguideModeTests(unittest.TestCase):
    def test_uniform_and_centered_aperture(self):
        """! @brief 균일 단면의 같은 모드 전달과 중앙 개구의 반대 패리티 차단을 확인한다."""
        import numpy as np

        report = solve({**CASE, "offset_mm": 0, "narrow_mm": 35})
        for sample in report["samples"]:
            value = np.asarray(sample["s_ri"])
            size = len(value) // 2
            eye, null = np.eye(size), np.zeros((size, size))
            np.testing.assert_allclose(value[..., 0], np.block([[null, eye], [eye, null]]), atol=5e-13, rtol=0)
            np.testing.assert_allclose(value[..., 1], 0, atol=5e-13, rtol=0)
        center = solve({**CASE, "offset_mm": 6})
        asym = solve(CASE)
        for symmetric, shifted in zip(center["samples"], asym["samples"]):
            self.assertLess(abs(complex(*symmetric["s_ri"][1][0])), 1e-12)
            self.assertGreater(abs(complex(*shifted["s_ri"][1][0])), .01)
            self.assertLess(shifted["energy_residual_max"], 1e-10)
            self.assertLess(shifted["reciprocity_residual_max"], 1e-10)
            self.assertLess(shifted["next_basis_delta_max"], .02)

    def test_step_against_independent_aperture_quadrature(self):
        """! @brief 직접 적분한 모드 겹침과 양쪽 블록 경계식으로 복소 행렬을 대조한다."""
        import numpy as np
        from scipy.integrate import quad

        case = {**CASE, "frequencies_hz": [15e9], "modes": 8}
        wide, narrow, d = .035, .023, .002
        right_n, left_n = 8, 13
        c = np.array([[quad(lambda x: 2 / math.sqrt(wide*narrow) * math.sin(i*math.pi*(x+d)/wide)
                            * math.sin(j*math.pi*x/narrow), 0, narrow, epsabs=1e-12)[0]
                       for j in range(1, right_n+1)] for i in range(1, left_n+1)])
        k = 2*math.pi*15e9/299792458
        a = np.sqrt((1-(np.arange(1, left_n+1)*math.pi/(wide*k))**2).astype(complex))
        b = np.sqrt((1-(np.arange(1, right_n+1)*math.pi/(narrow*k))**2).astype(complex))
        interface = np.block([[np.eye(left_n), -c], [c.T*a, np.diag(b)]])
        names = list(np.flatnonzero(a.real > 0)) + [left_n+i for i in np.flatnonzero(b.real > 0)]
        incident = np.eye(left_n+right_n)[:, names]
        aw, bn = incident[:left_n], incident[left_n:]
        rhs = np.vstack((-aw+c@bn, c.T@(a[:, None]*aw)+b[:, None]*bn))
        output = np.linalg.solve(interface, rhs)[names]
        power = np.sqrt(np.r_[a.real, b.real][names])
        output *= power[:, None] / power
        actual = np.asarray(solve(case)["samples"][0]["s_ri"])
        np.testing.assert_allclose(actual[..., 0]+1j*actual[..., 1], output, atol=1e-11, rtol=0)

    def test_invalid_overlap_and_cutoff(self):
        """! @brief 개구 밖 배치, 차단점과 전파 모드 누락을 차단한다."""
        for change in ({"offset_mm": 20}, {"frequencies_hz": [299792458/.07]},
                       {"modes": 2, "frequencies_hz": [50e9]}):
            with self.subTest(change=change), self.assertRaises(ProjectError):
                solve({**CASE, **change})
