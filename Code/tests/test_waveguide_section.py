"""! @brief 일반 PEC 단면과 두 축 단차를 해석해 및 직접 경계 정합으로 대조한다."""

import contextlib
import json
import math
from pathlib import Path
import sys
import unittest

from rfad.adapters import network_backend
from rfad.domain import waveguide_modes, waveguide_section
from rfad.domain.errors import ProjectError


C_MM = 299792458000
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def rectangular_step(wide, narrow, offset, pitch, frequency, basis):
    """! @brief 넓은 직사각형에 개구 좌표가 맞는 공통 삼각 격자를 구성한다."""
    def axis(full, start, length):
        """! @brief 재료 경계 위치를 포함하도록 양옆 구간과 개구를 구분한다."""
        bounds = sorted({0, start, start + length, full})
        return [a + (b - a) * i / math.ceil((b - a) / pitch)
                for a, b in zip(bounds, bounds[1:]) for i in range(math.ceil((b - a) / pitch))] + [full]

    x, y = (axis(end, start, length) for end, start, length in zip(wide, offset, narrow))
    nodes = [[a, b] for b in y for a in x]
    triangles, aperture = [], []
    for j, (bottom, top) in enumerate(zip(y, y[1:])):
        for i, (left, right) in enumerate(zip(x, x[1:])):
            ll = i + j * len(x)
            ur = ll + len(x) + 1
            if (offset[0] <= (left + right) / 2 <= offset[0] + narrow[0]
                    and offset[1] <= (bottom + top) / 2 <= offset[1] + narrow[1]):
                aperture.extend((len(triangles), len(triangles) + 1))
            triangles.extend(([ll, ll + 1, ur], [ll, ur, ur - 1]))
    return {"nodes_mm": nodes, "triangles": triangles, "aperture_triangles": aperture, "epsilon_r": 1,
            "frequencies_hz": [frequency], "basis_per_family": basis, "reference_offsets_mm": [0, 0]}


def triangle_guide(width, divisions):
    """! @brief 정사각형을 대각선에서 반으로 나눈 단면의 공통 단일 격자를 만든다."""
    nodes = [[i * width / divisions, j * width / divisions] for i in range(divisions + 1) for j in range(i + 1)]
    points = {(i, j): i * (i + 1) // 2 + j for i in range(divisions + 1) for j in range(i + 1)}
    triangles = []
    for i in range(divisions):
        for j in range(i + 1):
            a, b, c = points[i, j], points[i + 1, j], points[i + 1, j + 1]
            triangles.append([a, b, c])
            if j < i:
                triangles.append([a, c, points[i, j + 1]])
    return {"nodes_mm": nodes, "triangles": triangles, "aperture_triangles": list(range(len(triangles))),
            "epsilon_r": 1, "frequencies_hz": [16e9], "basis_per_family": 12, "reference_offsets_mm": [2, 3]}


def analytic_modes(width, height, maximum):
    """! @brief 직사각형 분리해를 편파별 차단 순서와 함께 반환한다."""
    modes = []
    for family, start in (("TE", 0), ("TM", 1)):
        values = [(family, m, n, math.pi * math.hypot(m / width, n / height))
                  for m in range(start, maximum + 1) for n in range(start, maximum + 1) if m or n]
        modes.extend(sorted(values, key=lambda entry: entry[3])[:maximum])
    return modes


def rectangular_reference(np, wide, narrow, offset, frequency, count):
    """! @brief 직사각형 벡터 해를 개구에서 직접 적분하고 확장 블록을 푼다."""
    root, weights = np.polynomial.legendre.leggauss(72)
    x = (offset[0] + (root + 1) * narrow[0] / 2)[:, None]
    y = (offset[1] + (root + 1) * narrow[1] / 2)[None, :]
    weights = weights[:, None] * weights[None, :] * math.prod(narrow) / 4
    k0 = 2 * math.pi * frequency / C_MM

    def components(section, origin):
        """! @brief 단위 접선 전계 분리해를 개구의 2차원 구적점에서 평가한다."""
        a, b = section
        xs, ys = x - origin[0], y - origin[1]
        fields, modes, admittance = [], analytic_modes(a, b, count), []
        for family, m, n, cutoff in modes:
            u, v = m * math.pi / a, n * math.pi / b
            q = np.sqrt(complex(1 - (cutoff / k0)**2))
            if family == "TE":
                norm = math.sqrt(a * b / ((1 + (m != 0)) * (1 + (n != 0))))
                ex = -v * np.cos(u * xs) * np.sin(v * ys)
                ey = u * np.sin(u * xs) * np.cos(v * ys)
                admittance.append(q)
            else:
                norm = math.sqrt(a * b) / 2
                ex = u * np.cos(u * xs) * np.sin(v * ys)
                ey = v * np.sin(u * xs) * np.cos(v * ys)
                admittance.append(1 / q)
            fields.append(np.stack((ex, ey)) / (norm * cutoff))
        return modes, np.array(admittance), np.array(fields)

    left_modes, yl, left_fields = components(wide, [0, 0])
    right_modes, yr, right_fields = components(narrow, offset)
    overlap = np.einsum("mijk,nijk,jk->mn", left_fields, right_fields, weights, optimize=True)
    left, right = np.flatnonzero(yl.real > 0), np.flatnonzero(yr.real > 0)
    incoming = len(left) + len(right)
    il = np.column_stack((np.eye(len(yl))[:, left], np.zeros((len(yl), len(right)))))
    ir = np.column_stack((np.zeros((len(yr), len(left))), np.eye(len(yr))[:, right]))
    matrix = np.block([[np.eye(len(yl)), -overlap], [-(overlap.T * yl), -np.diag(yr)]])
    rhs = np.vstack((overlap @ ir - il, -(overlap.T * yl) @ il - yr[:, None] * ir))
    output = np.linalg.solve(matrix, rhs)[np.r_[left, len(yl) + right]]
    scale = np.sqrt(np.r_[yl[left].real, yr[right].real])
    channels = [item for table, indices in ((left_modes, left), (right_modes, right)) for i in indices
                for item in (table[i],)]
    return (left, right, channels, output * (scale[:, None] / scale[None, :]))


def align_signs(np, result, input_case, dimensions, positions, modes):
    """! @brief 기록된 절점 함수와 분리해의 부호를 맞춘다."""
    signs = []
    for side, geom, origin, indices in zip(("wide", "narrow"), dimensions, positions, modes[:2]):
        section = result["sections"][side]
        analytic = analytic_modes(*geom, input_case["basis_per_family"])
        nodes = np.asarray(input_case["nodes_mm"])[section["node_indices"]] - origin
        for index in indices:
            family, m, n, _ = analytic[index]
            shape = np.cos if family == "TE" else np.sin
            axis = shape(nodes * (math.pi * np.array([m, n]) / geom)).prod(axis=1)
            reported = section["modes"][index]["scalar_nodal_values_per_mm"]
            score = float(axis @ reported)
            signs.append(math.copysign(1, score))
    return np.array(signs)


@unittest.skipUnless(network_backend.installation_metadata()["installed"] == network_backend.VERSIONS, "고정 수치 환경 필요")
class WaveguideSectionTests(unittest.TestCase):
    """! @brief 차단, 편파 결합, 에너지, 상호성과 거절 조건을 검증한다."""

    def test_triangle_cutoffs_and_reference_planes(self):
        """! @brief 삼각 단면 고유값과 동일 단면의 기준면 위상을 해석해와 대조한다."""
        import numpy as np

        case = triangle_guide(22.5, 24)
        result = waveguide_section.solve(case)
        modes = result["sections"]["wide"]["modes"]
        first = C_MM / (2 * 22.5)
        for i, ratio in ((0, 1), (1, math.sqrt(2)), (12, math.sqrt(5))):
            self.assertLess(abs(modes[i]["cutoff_hz"] / first - ratio), 0.015)
        sample = result["samples"][0]
        matrix = np.asarray(sample["s_ri"])
        matrix = matrix[:, :, 0] + 1j * matrix[:, :, 1]
        beta = [mode["beta_ri_per_m"][0] for mode in sample["port_modes"]["wide"] if mode["type"] == "propagating"]
        n = len(beta)
        phase = np.exp(1j * np.array(beta) * 0.005)
        self.assertLess(np.max(abs(matrix[:n, :n])), 1e-11)
        self.assertLess(np.max(abs(matrix[n:, :n] - np.diag(phase))), 1e-11)
        self.assertEqual(result["reference_planes_z_mm"], {"wide": -2, "narrow": 3})
        for mode in sample["port_modes"]["wide"]:
            if mode["type"] == "evanescent":
                self.assertIsNone(mode["modal_voltage_v_per_sqrt_w"])
                continue
            voltage = mode["modal_voltage_v_per_sqrt_w"]
            admittance = mode["normalized_admittance_ri"][0]
            self.assertAlmostEqual(voltage**2 * admittance / (2 * 376.73031346177), 1, places=8)

    def test_rectangular_width_step(self):
        """! @brief 404 폭 단차의 기존 TE(m,0) 복소 행렬을 일반 단면으로 재현한다."""
        import numpy as np

        original = json.loads((FIXTURES / "waveguide_te_step.json").read_text(encoding="utf-8"))
        original["frequencies_hz"] = [15e9]
        reference = waveguide_modes.solve(original)["samples"][0]
        wide, narrow, offset = [original["wide_mm"], 8], [original["narrow_mm"], 8], [original["offset_mm"], 0]
        case = rectangular_step(wide, narrow, offset, 0.42, 15e9, 62)
        result = waveguide_section.solve(case)
        sample = result["samples"][0]
        indices = [np.array([i for i, mode in enumerate(sample["port_modes"][side])
                             if mode["type"] == "propagating"]) for side in ("wide", "narrow")]
        signs = align_signs(np, result, case, (wide, narrow), ([0, 0], offset), indices)
        expected = np.asarray(reference["s_ri"])
        actual = np.asarray(sample["s_ri"])
        expected = expected[:, :, 0] + 1j * expected[:, :, 1]
        actual = (actual[:, :, 0] + 1j * actual[:, :, 1]) * signs[:, None] * signs
        self.assertEqual(actual.shape, expected.shape)
        self.assertLess(np.max(abs(actual - expected)), 0.008, str(np.max(abs(actual - expected))))

    def test_two_axis_step_te_tm_coupling(self):
        """! @brief 두 축이 달라지는 개구의 TE/TM 전체 반사와 전달을 직교 분리해와 검산한다."""
        import numpy as np

        wide, narrow, offset = [34.5, 20.2], [22.3, 15.8], [3.2, 1.2]
        case = rectangular_step(wide, narrow, offset, 0.54, 14.2e9, 48)
        result = waveguide_section.solve(case)
        sample = result["samples"][0]
        reference = rectangular_reference(np, wide, narrow, offset, 14.2e9, 48)
        signs = align_signs(np, result, case, (wide, narrow), ([0, 0], offset), reference[:2])
        expected = reference[-1]
        actual = np.asarray(sample["s_ri"])
        actual = (actual[:, :, 0] + 1j * actual[:, :, 1]) * signs[:, None] * signs
        self.assertEqual(actual.shape, expected.shape)
        self.assertLess(np.max(abs(actual - expected)), 0.01, str(np.max(abs(actual - expected))))
        families = np.array([family for family, _, _, _ in reference[2]])
        self.assertGreater(np.max(abs(actual[families == "TE", :][:, families == "TM"])), 0.02)
        self.assertLess(sample["energy_residual_max"], 2e-10)
        self.assertLess(sample["reciprocity_residual_max"], 2e-10)

    def test_mode_files_match_independent_te10_profile(self):
        """! @brief 내보낸 전계와 자계 모드가 독립 TE10 분포와 부호 규약을 따르는지 검사한다."""
        import h5py
        import numpy as np
        from tempfile import TemporaryDirectory

        from rfad.cli.waveguide_mode_files import export_mode

        case = rectangular_step([20, 10], [20, 10], [0, 0], 0.45, 10.5e9, 14)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "모드"
            metadata = export_mode(case, "wide", "TE1", 10.5e9, 0.5, destination)
            self.assertAlmostEqual(metadata["cutoff_hz"] / (C_MM / 40), 1, places=3)
            self.assertEqual(metadata["port_inward_direction"], [0, 0, 1])
            with h5py.File(destination / "electric.h5") as e, h5py.File(destination / "magnetic.h5") as h:
                self.assertEqual(e.attrs["Version"], 1.0)
                analytic = np.sin(np.pi * e["x"][...] / 20) / 10
                expected = np.broadcast_to(analytic[:, None], e["Vy"].shape)
                direction = np.sign(np.sum(expected * e["Vy"][...]))
                self.assertLess(np.max(abs(e["Vy"][...] - direction * expected)), 0.004)
                self.assertLess(np.max(abs(e["Vx"][...])), 0.001)
                np.testing.assert_array_equal(h["Vx"][...], -e["Vy"][...])
                np.testing.assert_array_equal(h["Vy"][...], e["Vx"][...])
            original = (destination / "mode.json").read_bytes()
            with self.assertRaises(ProjectError):
                export_mode(case, "wide", "TE1", 10.5e9, 0.5, destination)
            self.assertEqual((destination / "mode.json").read_bytes(), original)

    def test_rejects_repeated_and_nonconforming_mesh(self):
        """! @brief 중복 요소와 두 부분으로 나뉜 개구를 진단한다."""
        original = triangle_guide(20, 12)
        modified = {**original, "triangles": [*original["triangles"], original["triangles"][0]]}
        nonconforming = {**original, "aperture_triangles": [0, 1, 2, 3, 100, 101, 102, 103]}
        for invalid in (modified, nonconforming):
            with self.assertRaises(ProjectError):
                waveguide_section.solve(invalid)
