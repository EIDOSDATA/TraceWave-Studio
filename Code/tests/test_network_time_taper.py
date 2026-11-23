"""! @brief 두 위상 규약의 지연 테이퍼와 명시 군속도의 반사 및 전송 거리 환산을 검사한다."""

from copy import deepcopy
import cmath
import math
import unittest

from rfad.application.network_forms import transform_input
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import make_dataset
from rfad.domain.network_transform import transform_dataset
from test_network_domain import ENGINE_READY, identity


@unittest.skipUnless(ENGINE_READY, "고정 RF 수치 엔진이 필요합니다.")
class TimeTaperTests(unittest.TestCase):
    def sample(self, sign):
        """! @brief 16점 복소 대역에 서로 다른 지연과 독립 채널 이득을 합성한다."""
        count = 16
        channels = ((0.12, 0.03), (-0.08, 0.22))
        signals = [(0, 0.23j), (1, 0.3 + 0.1j), (2, -0.3j), (4, 0.15 - 0.19j), (-1, 0.26)]
        values = []
        expected = []
        for index in range(count):
            parts = [amplitude * cmath.exp(sign * 1j * math.tau * index * delay / count)
                     for delay, amplitude in signals]
            # @brief 0~4 ns Hann 창에서 1 ns는 절반, 2 ns는 그대로 남는다.
            expected.append([[gain * (parts[1] / 2 + parts[2]) for gain in row] for row in channels])
            values.append([[[sample.real, sample.imag] for sample in (gain * sum(parts) for gain in row)]
                           for row in channels])
        network = make_dataset(parameter_kind="S", frequency_hz=[1.11e9 + i * 62.5e6 for i in range(count)],
            port_ids=[identity(1), identity(2)], values_ri=values, z0_ohm=[[[50, 0], [75, 0]]] * count,
            wave_definition="traveling", phasor_convention="exp(+j*omega*t)" if sign < 0 else "exp(-j*omega*t)",
            reference_planes=["입력", "출력"], port_names=["급전 1", "급전 2"],
            port_modes=["single_ended"] * 2, current_orientation=["into_dut"] * 2,
            sample_origin=["computed"] * count, conditions={"manufacture": None}, source_refs=["fixture:delays"])
        return network, expected

    def test_known_echo_weights_and_path_convention(self):
        """! @brief 두 시간 부호에서 게이트 안쪽의 복소 크기와 좌표의 왕복 계수를 대조한다."""
        for sign in (-1, 1):
            data, expected = self.sample(sign)
            original = deepcopy(data)
            options = transform_input(data, {"operation": "time_gate", "start_ns": "0", "stop_ns": "4",
                                      "taper_fraction": "1", "velocity_factor": "0.6"})
            result = transform_dataset(data, options)
            self.assertEqual(original, data)
            details = result["diagnostics"][0]
            self.assertEqual((details["retained_bins"], details["nonzero_bins"]), (5, 3))
            self.assertAlmostEqual(details["reflection_distance_mm"][1], 359.7509496)
            self.assertAlmostEqual(details["transmission_path_mm"][1], 719.5018992)
            for found, want in zip(result["dataset"]["values_ri"], expected):
                for row, reference in zip(found, want):
                    for pair, sample in zip(row, reference):
                        self.assertAlmostEqual(complex(*pair), sample, places=13)
            backward = transform_dataset(data, {"operation": "time_gate", "start_ns": -2, "stop_ns": 0,
                                                 "velocity_factor": 0.5})
            self.assertAlmostEqual(backward["diagnostics"][0]["reflection_distance_mm"][0], -149.896229)
            self.assertNotIn("transmission_path_mm", transform_dataset(data, {"operation": "time_gate",
                             "start_ns": 0, "stop_ns": 4})["diagnostics"][0])

    def test_degenerate_taper_and_missing_speed(self):
        """! @brief 표본 소거와 잘못된 속도나 비율을 진단한다."""
        data, _ = self.sample(-1)
        options = {"operation": "time_gate", "start_ns": 0, "stop_ns": 1}
        for extra in ({"taper_fraction": 1}, {"taper_fraction": 1.1}, {"velocity_factor": 0},
                      {"velocity_factor": -0.1}, {"velocity_factor": 1.2}):
            with self.subTest(extra=extra), self.assertRaises(ProjectError):
                transform_dataset(data, {**options, **extra})
