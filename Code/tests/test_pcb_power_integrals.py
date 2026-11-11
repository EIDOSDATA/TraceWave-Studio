"""! @brief 실제 numpy 환경에서 독립 적분의 SI 가중치/위상/반응 전류를 검증한다."""

import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

from rfad.adapters.solvers.openems.pcb_absorption import edge_weights, integrate_fields, read_fields, create_dumps
from rfad.domain.errors import ProjectError


@unittest.skipUnless(importlib.util.find_spec("numpy"), "격리 native 또는 CAD 환경의 numpy가 필요합니다.")
class IndependentIntegralTests(unittest.TestCase):
    """! @brief 공간/시간 보정과 반응 성분의 소거를 알려진 합성 필드로 대조한다."""

    def test_nonuniform_edge_volume_in_metres(self):
        """! @brief 비균일 Yee edge 길이/dual 폭과 mm^3 -> m^3를 확인한다."""
        lines = {"x": [0, 1, 3, 7], "y": [0, 2, 6, 12], "z": [0, 3, 9, 18]}
        for direction, expected in ((0, 2 * 3 * 4.5), (1, 1.5 * 4 * 4.5), (2, 1.5 * 3 * 6)):
            self.assertAlmostEqual(edge_weights(lines, [[1], [1], [1]], direction)[0, 0, 0] / 1e-9, expected)

    def test_reactive_current_does_not_become_sheet_heat(self):
        """! @brief 반 time step 위상과 사다리꼴 평균을 보정해 실수 저항 손실만 적분한다."""
        import numpy as np

        shape = (3, 1, 1, 1)
        electric = np.ones(shape, dtype=complex) * (2 + 3j)
        conduction = electric * 0.1
        frequency, timestep = 2.4e9, 1e-12
        angle = math.pi * frequency * timestep
        # @brief 알려진 전도 전류와 큰 반응 전류를 native rotH 시간 라벨로 합성한다.
        total = electric * (0.2 + 10j) * math.cos(angle) * np.exp(1j * angle)
        partition = np.full(shape, -1)
        partition[0] = 0
        weights = [np.ones((1, 1, 1)) * 1e-9] * 3
        result = integrate_fields(electric, conduction, total, weights, partition, frequency, timestep, [{"id": "sheet"}])
        self.assertAlmostEqual(result["dielectric_loss_w_s2"] / 1e-9, 1.3)
        self.assertAlmostEqual(result["conductor_loss_w_s2"] / 1e-9, 1.3)
        lossless = integrate_fields(electric, conduction, electric * 10j * math.cos(angle) * np.exp(1j * angle), weights, partition, frequency, timestep, [{"id": "sheet"}])
        self.assertLess(abs(lossless["conductor_loss_w_s2"]), 1e-20)

    def test_source_edge_and_negative_work_are_preserved(self):
        """! @brief 포트 저항 제외와 음수 실수 일률을 잘라내지 않는 동작을 확인한다."""
        import numpy as np

        electric = np.ones((3, 1, 1, 1), dtype=complex)
        partition = np.full(electric.shape, -2)
        partition[0] = 0
        result = integrate_fields(electric, electric, -electric, [np.ones((1, 1, 1))] * 3, partition, 1e9, 1e-15, [{"id": "sheet"}])
        self.assertEqual(result["dielectric_loss_w_s2"], 0)
        self.assertLess(result["conductor_loss_w_s2"], 0)

    def test_invalid_time_resolution_is_rejected(self):
        """! @brief 시간 보정의 특이점에 가까운 입력은 판정하지 않는다."""
        with self.assertRaises(ProjectError):
            integrate_fields(None, None, None, None, None, 1e9, 1e-9, [])

    @unittest.skipUnless(importlib.util.find_spec("h5py"), "native 환경의 h5py가 필요합니다.")
    def test_native_component_xyz_order_and_hdf_guards(self):
        """! @brief 서로 다른 축 크기로 전치 오류를 잡고 변조된 좌표/주파수/필드를 거절한다."""
        import numpy as np
        import h5py
        from rfad.application.pcb_power import NAMES

        lines = {"x": [0, 1], "y": [0, 1, 3], "z": [0, 1, 3, 6]}
        recording = {"start_indices": [0, 0, 0], "stop_indices": [1, 2, 3], "frequency_hz": [2.4e9]}
        expected = np.arange(72).reshape(3, 2, 3, 4).astype(np.complex64) * (1 + 2j)
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            for name in NAMES:
                with h5py.File(raw / name, "w") as stream:
                    stream.attrs["dual_mesh"] = 0
                    mesh = stream.create_group("Mesh")
                    for axis in "xyz":
                        mesh[axis] = np.asarray(lines[axis]) * 0.001
                    field = stream.create_group("FieldData/FD")
                    field.attrs["frequency"] = [2.4e9]
                    field["f0"] = expected
            observed = read_fields(raw, recording, lines, 0)
            self.assertTrue(all(np.array_equal(value, expected) for value in observed))
            for target in ("coordinate", "frequency", "nonfinite", "dual"):
                with self.subTest(target=target):
                    with h5py.File(raw / NAMES[0], "r+") as stream:
                        stream["Mesh/x"][0] = 0.01 if target == "coordinate" else 0
                        stream["FieldData/FD"].attrs["frequency"] = [1e9 if target == "frequency" else 2.4e9]
                        stream["FieldData/FD/f0"][0, 0, 0, 0] = np.nan if target == "nonfinite" else expected[0, 0, 0, 0]
                        stream.attrs["dual_mesh"] = target == "dual"
                    with self.assertRaises(ProjectError):
                        read_fields(raw, recording, lines, 0)

    def test_dump_box_uses_inward_primitive_for_outward_native_snap(self):
        """! @brief XML 반올림으로 불필요한 인접 격자가 추가되지 않게 안쪽 primitive를 쓴다."""
        calls = []

        class Structure:
            """! @brief 실제 CSXCAD와 같은 dump/box 호출 표면을 기록한다."""

            def AddDump(self, name, **options):
                """! @brief 무보간 주파수 dump 옵션을 수집한다."""
                calls.append((name, options))
                return self

            def AddBox(self, start, stop):
                """! @brief outward snap에 전달하는 내부 좌표를 수집한다."""
                calls.append((start, stop))

        recording = {"dump_types": [10, 12, 13], "frequency_hz": [1e9],
                     "primitive_start_mm": [0.25] * 3, "primitive_stop_mm": [0.75] * 3}
        create_dumps(Structure(), recording)
        self.assertEqual([calls[i][1]["dump_mode"] for i in (0, 2, 4)], [0, 0, 0])
        self.assertEqual(calls[1], ([0.25] * 3, [0.75] * 3))


if __name__ == "__main__":
    unittest.main()
