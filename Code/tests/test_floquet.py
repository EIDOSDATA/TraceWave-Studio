"""! @brief Floquet 경계의 위상, 복소 계수, 전력 및 적용 범위를 대조한다."""

import cmath
import json
import math
from pathlib import Path
import unittest

from rfad.domain.errors import ProjectError
from rfad.domain.floquet import solve
from test_network_domain import ENGINE_READY


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "floquet_dielectric_grating.json"


@unittest.skipUnless(ENGINE_READY, "고정 RF 수치 엔진이 필요합니다.")
class FloquetTests(unittest.TestCase):
    def setUp(self):
        """! @brief 수정과 계산을 실제 공개 예제의 독립 복사본에서 수행한다."""
        self.case = json.loads(FIXTURE.read_bytes())

    def test_uniform_slab_against_airy_series_with_oblique_incidence(self):
        """! @brief 서로 다른 외부 매질의 균질판을 TE/TM Airy 식과 대조한다."""
        for polarization in ("TE", "TM"):
            case = {**self.case, "epsilon_right": 2.25, "polarization": polarization,
                    "stripes": [{"fraction": 1, "epsilon_r": 4}], "orders": 6}
            report = solve(case)
            kx = math.sin(math.radians(17))
            roots = [math.sqrt(e - kx*kx) for e in (1, 4, 2.25)]
            y0, y1, y2 = roots if polarization == "TE" else [q/e for q, e in zip(roots, (1, 4, 2.25))]
            r01, r12 = (y0-y1)/(y0+y1), (y1-y2)/(y1+y2)
            for sample in report["samples"]:
                k0 = 2 * math.pi * sample["frequency_hz"] / 299792458
                z = cmath.exp(1j * k0 * roots[1] * .004)
                r = (r01 + r12*z*z) / (1 + r01*r12*z*z)
                t = ((1+r01)*(1+r12)*z) / (1 + r01*r12*z*z)
                zero = sample["orders"][case["orders"]]
                self.assertAlmostEqual(complex(*zero["reflection_ri"]), r, places=12)
                self.assertAlmostEqual(complex(*zero["transmission_ri"]), t, places=12)
                self.assertAlmostEqual(complex(*sample["boundary_factor_ri"]), cmath.exp(1j*k0*kx*.038), places=12)
                self.assertLess(sample["energy_balance_residual"], 1e-12)
                self.assertLess(max(row["transmitted_power"] for row in sample["orders"] if row["order"]), 1e-24)

    def test_nonuniform_oblique_grating_cyclic_shift_and_power(self):
        """! @brief 직선 경계의 재배치에 따른 복소 회절 위상과 전력 불변성을 확인한다."""
        for polarization in ("TE", "TM"):
            case = {**self.case, "polarization": polarization}
            base = solve(case)
            shifted = solve({**case, "stripes": list(reversed(case["stripes"]))})
            for first, second in zip(base["samples"], shifted["samples"]):
                self.assertLess(first["energy_balance_residual"], 1e-10)
                self.assertLess(first["next_order_power_delta_max"], .01)
                orders = first["orders"]
                self.assertGreater(sum(row["transmitted_power"] for row in orders if row["order"]), 1e-5)
                for a, b in zip(orders, second["orders"]):
                    phase = cmath.exp(-2j * math.pi * .65 * a["order"])
                    for key in ("reflection_ri", "transmission_ri"):
                        self.assertAlmostEqual(complex(*a[key]) * phase, complex(*b[key]), places=10)

    def test_nonuniform_short_layer_against_independent_transfer_matrix(self):
        """! @brief 직접 Fourier 샘플링 및 전달 행렬로 비균질층의 복소 회절을 대조한다."""
        import numpy as np
        from scipy.linalg import expm

        case = {**self.case, "frequencies_hz": [1e10], "thickness_mm": 0.8, "orders": 4}
        sample, = solve(case)["samples"]
        count = 100_000
        x = (np.arange(count) + .5) / count
        m = np.arange(-4, 5)
        basis = np.exp(2j * np.pi * x[:, None] * m)
        permittivity = np.where(x < .35, 4, 1)
        multiplication = basis.conj().T @ (permittivity[:, None] * basis) / count
        k0 = 2 * np.pi * 1e10 / 299792458
        transverse = np.sin(np.deg2rad(17)) + m * 2 * np.pi / (.038 * k0)
        q = np.sqrt((1 - transverse**2).astype(complex))
        eye, null = np.eye(m.size), np.zeros((m.size, m.size))
        flux = np.diag(q)
        incident = eye[:, 4]
        transfer = expm(1j * k0 * .0008 * np.block([
            [null, eye], [multiplication - np.diag(transverse**2), null],
        ]))
        right = np.vstack((eye, flux))
        left = transfer @ np.vstack((eye, -flux))
        rhs = transfer @ np.concatenate((incident, q * incident))
        waves = np.linalg.solve(np.column_stack((-left, right)), rhs)
        actual = [complex(*row[key]) for key in ("reflection_ri", "transmission_ri") for row in sample["orders"]]
        np.testing.assert_allclose(actual, waves, atol=2e-9, rtol=0)

    def test_missing_diffraction_orders_and_bad_geometry(self):
        """! @brief 빠진 전파 차수와 미완성 주기셀에는 결과를 돌려주지 않는다."""
        for change in ({"period_mm": 1000, "orders": 2}, {"orders": 33}, {"incidence_deg": 90},
                       {"stripes": [{"fraction": .9, "epsilon_r": 2}]}):
            with self.subTest(change=change), self.assertRaises(ProjectError):
                solve({**self.case, **change})
