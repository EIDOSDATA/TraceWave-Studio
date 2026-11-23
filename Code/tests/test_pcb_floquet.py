"""! @brief PCB 이중 주기 해석의 기준면, 위상, 에너지와 개정 보존을 대조한다."""

import cmath
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rfad.adapters import network_backend
from rfad.application.canonical import canonical_hash
from rfad.domain import floquet, pcb_floquet
from rfad.domain.errors import ProjectError


CODE = Path(__file__).resolve().parents[1]
FIXTURES = CODE / "fixtures"


def fixture(name):
    """! @brief 추적된 입력의 원본 표현을 읽는다."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def material(epsilon, loss=0.0, conductivity=0.0):
    """! @brief 시험의 손실과 전도도 가정을 명시한다."""
    return {"epsilon_r": epsilon, "tan_delta": loss, "conductivity_s_per_m": conductivity}


@unittest.skipUnless(network_backend.installation_metadata()["installed"] == network_backend.VERSIONS, "고정 수치 환경 필요")
class PcbFloquetTests(unittest.TestCase):
    """! @brief 독립 해, 전파 차수, 사용자 프로젝트 진입점을 검증한다."""

    def test_uniform_airy(self):
        """! @brief 손실판과 두꺼운 동박을 감쇠형 Airy 복소 반사 및 투과와 대조한다."""
        case = fixture("pcb_floquet_patch.json")
        case.update(period_mm=[4, 4], grid=[1, 1], comparison_grid=[3, 3],
                    epsilon_right=2.2, frequencies_hz=[10.5e9])
        for name, depth in (("substrate", 1.6), ("copper", 0.035)):
            case["layers"] = [{"background": name, "thickness_mm": depth, "regions": []}]
            theta = math.radians(case["theta_deg"])
            frequency = case["frequencies_hz"][0]
            m = case["materials"][name]
            epsilon = m["epsilon_r"] * (1 + 1j * m["tan_delta"])
            epsilon += 1j * m["conductivity_s_per_m"] / (2 * math.pi * frequency * 8.8541878128e-12)
            media = (1, epsilon, case["epsilon_right"])
            q = [cmath.sqrt(e - math.sin(theta)**2) for e in media]
            prop = cmath.exp(1j * q[1] * 2 * math.pi * frequency * depth / 299792458000)
            for index, pol in enumerate(("TE", "TM")):
                with self.subTest(material=name, polarization=pol):
                    case["polarization"] = pol
                    ys = q if pol == "TE" else [e / k for e, k in zip(media, q)]
                    a, b, c = ys
                    r01, r12 = (a - b) / (a + b), (b - c) / (b + c)
                    den = 1 + r01 * r12 * prop**2
                    r = (r01 + r12 * prop**2) / den
                    t = (1 + r01) * (1 + r12) * prop / den
                    sample = pcb_floquet.solve(case)["samples"][0]
                    row = sample["orders"][0]
                    self.assertLess(abs(complex(*row["reflection_ri"][index]) - r), 2e-13)
                    self.assertLess(abs(complex(*row["transmission_ri"][index]) - t), 2e-13)
                    loss = 1 - abs(r)**2 - (c / a).real * abs(t)**2
                    self.assertAlmostEqual(sample["absorption_by_material"][name], loss, places=12)
                    self.assertGreater(sample["absorption_by_material"][name], 0)

    def test_legacy_stripes(self):
        """! @brief 기존 403의 세 주파수와 모든 차수의 TE/TM 복소 계수를 재현한다."""
        original = fixture("floquet_dielectric_grating.json")
        period = original["period_mm"]
        border = period * original["stripes"][0]["fraction"]
        case = {"period_mm": [period, 1], "epsilon_left": original["epsilon_left"],
                "epsilon_right": original["epsilon_right"], "grid": [25, 1], "comparison_grid": [29, 1],
                "theta_deg": original["incidence_deg"], "phi_deg": 0, "frequencies_hz": original["frequencies_hz"],
                "materials": {"one": material(original["stripes"][0]["epsilon_r"]),
                              "two": material(original["stripes"][1]["epsilon_r"])},
                "layers": [{"thickness_mm": original["thickness_mm"], "background": "two",
                            "regions": [{"material": "one", "holes": [],
                                         "outer": [[0, 0], [border, 0], [border, 1], [0, 1]]}]}]}
        for pol_index, pol in enumerate(("TE", "TM")):
            old = floquet.solve({**original, "polarization": pol})["samples"]
            new = pcb_floquet.solve({**case, "polarization": pol})["samples"]
            for reference, result in zip(old, new):
                rows = {row["order"][0]: row for row in result["orders"]}
                for target in reference["orders"]:
                    row = rows[target["order"]]
                    sign = math.copysign(1, row["kt_per_m"][0])
                    for field, power, direction, kz in (
                        ("reflection_ri", "reflected_power", -1, "kz_left_ri_per_m"),
                        ("transmission_ri", "transmitted_power", 1, "kz_right_ri_per_m"),
                    ):
                        coefficient = sign * complex(*row[field][pol_index])
                        if pol == "TM":
                            # @brief 403의 기준 Hy를 접선 E에서 복원하고 후진파 자계의 방향을 적용한다.
                            incident = complex(*rows[0]["kz_left_ri_per_m"])
                            exterior = case["epsilon_left"] if direction < 0 else case["epsilon_right"]
                            coefficient *= direction * incident * exterior / (case["epsilon_left"] * complex(*row[kz]))
                        self.assertLess(abs(coefficient - complex(*target[field])), 5e-11)
                        self.assertAlmostEqual(row[power][pol_index], target[power], places=11)
                        self.assertAlmostEqual(row[power][1 - pol_index], 0, places=11)

    def test_pcb_phases_and_energy(self):
        """! @brief 35 um 동박 셀의 두 Bloch 인자와 편파 결합, 흡수 및 전력을 확인한다."""
        case = fixture("pcb_floquet_patch.json")
        result = pcb_floquet.solve(case)
        sample = result["samples"][0]
        k0 = 2 * math.pi * case["frequencies_hz"][0] / 299792458000
        theta, phi = map(math.radians, (case["theta_deg"], case["phi_deg"]))
        for axis, direction in enumerate((math.cos(phi), math.sin(phi))):
            phase = k0 * math.sin(theta) * direction * case["period_mm"][axis]
            self.assertLess(abs(complex(*sample["boundary_factor_ri"][axis]) - cmath.exp(1j * phase)), 1e-14)
        by_order = {tuple(row["order"]): row for row in sample["orders"]}
        for order in ((-1, 0), (0, -1)):
            self.assertGreater(sum(by_order[order]["transmitted_power"]), 5e-5)
        self.assertGreater(by_order[-1, -1]["transmitted_power"][1], 1e-6)
        self.assertGreater(sample["absorption_by_material"]["copper"], 1e-7)
        self.assertGreater(sample["absorption_by_material"]["substrate"], 0.02)
        self.assertLess(sample["energy_balance_residual"], 2e-8)
        self.assertLess(sample["comparison"]["max_order_polarization_power_delta"], 0.005)
        reference = fixture("pcb_floquet_fem_reference.json")
        self.assertEqual(result["input_sha256"], canonical_hash(case))
        self.assertEqual(result["input_sha256"], reference["input_sha256"])
        for observed, expected in zip(sample["boundary_factor_ri"], reference["boundary_factor_ri"]):
            self.assertLess(abs(complex(*observed) - complex(*expected)), 2e-14)
        self.assertLess(reference["residual"], 0.001)
        for key, expected in reference["orders"].items():
            nx, ny, pol, side = key.split(",")
            row = by_order[int(nx), int(ny)]
            ri, power = ("reflection_ri", "reflected_power") if side == "front" else (
                "transmission_ri", "transmitted_power")
            self.assertLess(abs(row[power][int(pol)] - expected["power"]), 0.006)
            self.assertLess(abs(complex(*row[ri][int(pol)]) - complex(*expected["amplitude_ri"])), 0.025)
        self.assertLess(abs(sample["absorption_by_material"]["substrate"] - reference["absorption"]["substrate"]), 0.004)
        self.assertLess(abs(sample["absorption_by_material"]["copper"] - reference["absorption"]["copper"]), 5e-6)

    def test_periodic_translation_changes_order_phase(self):
        """! @brief 격자와 함께 이동한 동박의 두 축 회절 위상과 전력 불변성을 대조한다."""
        case = fixture("pcb_floquet_patch.json")
        case.update(grid=[5, 5], comparison_grid=[15, 15])
        original = pcb_floquet.solve(case)["samples"][0]
        outline = case["layers"][0]["regions"][0]["outer"]
        case["layers"][0]["regions"][0]["outer"] = [[x + 8, y + 7] for x, y in outline]
        shifted = pcb_floquet.solve(case)["samples"][0]
        for before, after in zip(original["orders"], shifted["orders"]):
            phase = cmath.exp(-2j * math.pi * (sum(before["order"]) / 5))
            for key in ("reflection_ri", "transmission_ri"):
                for a, b in zip(before[key], after[key]):
                    self.assertLess(abs(phase * complex(*a) - complex(*b)), 2e-7)

    def test_entry_point_keeps_project_bytes(self):
        """! @brief 저장 개정에서 읽은 재료와 형상 출처를 반환하며 원본을 바꾸지 않는다."""
        original = fixture("pcb_worker_smoke.json")["document"]
        first = original["geometry"][0]

        def mm(value):
            """! @brief 저장 개정의 출처가 있는 길이 수량을 만든다."""
            return {**first["start"][0], "value_si": value * 0.001}

        original["board"]["outline"] = {"kind": "rectangle", "width": mm(40), "height": mm(35)}
        xy = [[16, 14], [24, 14], [24, 21], [16, 21]]
        original["ports"] = []
        original["geometry"] = [
            {**{key: val for key, val in first.items() if key not in ("start", "end", "width")},
             "kind": "planar_region", "outer": [[mm(x), mm(y)] for x, y in xy], "holes": []}
        ]
        settings = fixture("pcb_floquet_patch.json")
        settings = {key: val for key, val in settings.items() if key not in ("period_mm", "layers", "materials")}
        settings.update(grid=[5, 5], comparison_grid=[15, 15], curve_tolerance_mm=0.01)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "보존된 개정.json"
            config = Path(folder) / "해석 조건.json"
            raw = json.dumps(original, ensure_ascii=False, indent=2).encode()
            source.write_bytes(raw)
            config.write_text(json.dumps(settings), encoding="utf-8")
            run = subprocess.run([sys.executable, "-m", "rfad", "pcb-floquet", str(source), "--settings", str(config)],
                                 cwd=CODE, env={**os.environ, "PYTHONPATH": str(CODE / "src"), "PYTHONIOENCODING": "utf-8"},
                                 capture_output=True, check=False, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8"))
            result = json.loads(run.stdout)
            provenance = result["project_source"]
            self.assertEqual(provenance["document_sha256"], canonical_hash(original))
            self.assertEqual(provenance["geometry_regions"][0]["source_ref"], first["source_ref"])
            self.assertEqual(source.read_bytes(), raw)

    def test_rejects_missing_orders_and_erased_pattern(self):
        """! @brief 격자가 피복을 놓치거나 전파 차수를 자르면 결과를 내지 않는다."""
        original = fixture("pcb_floquet_patch.json")
        erased = deepcopy(original)
        erased["layers"][0]["regions"][0]["outer"] = [[1, 1], [1.01, 1], [1.01, 1.01], [1, 1.01]]
        for invalid in ({**original, "period_mm": [900, 900]}, erased):
            with self.assertRaises(ProjectError):
                pcb_floquet.solve(invalid)
