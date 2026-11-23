"""! @brief 명명된 단일 전파 모드 표의 기준면 이동을 독립 네트워크 회로와 대조한다."""

from copy import deepcopy
import importlib.util
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.network_forms import transform_input
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import make_dataset
from rfad.domain.network_transform import transform_dataset


def setup(ports, negative=False):
    """! @brief 서로 다른 실수 Z0, 분산, 감쇠 및 비대칭 복소행렬을 갖는 시험 입력을 만든다."""
    frequencies = [8e9, 9.75e9, 11e9]
    ids = [str(uuid4()) for _ in range(ports)]
    refs = [[[45 + p * 3 + k, 0] for p in range(ports)] for k in range(len(frequencies))]
    modes = ["mode:모드 " + str(p + 1) for p in range(ports)]
    values = [[[[.03 * (i + 1) + .011 * (k + 1), .02 * (j + 1) - .003 * i] for j in range(ports)]
               for i in range(ports)] for k in range(len(frequencies))]
    data = make_dataset(parameter_kind="S", frequency_hz=frequencies, port_ids=ids, values_ri=values, z0_ohm=refs,
        wave_definition="power", phasor_convention="exp(-j*omega*t)" if negative else "exp(+j*omega*t)",
        reference_planes=["시작" + str(p) for p in range(ports)], port_modes=modes,
        current_orientation=["into_dut"] * ports, sample_origin=["computed"] * len(frequencies))
    lines = []
    for p, identity in enumerate(ids):
        samples = [[f, .35 + p * .12 + k * .05, 120 + 3 * k ** 2 + p * 9, refs[k][p][0]]
                   for k, f in enumerate(frequencies)]
        length = 5 + p
        position = {"length_mm": length} if p else {"segment": {"from_mm": [0, 0, 1], "to_mm": [3, 4, 1], "outward": [3, 4, 0]}}
        lines.append({"port_id": identity, "reference_plane": "새 면" + str(p), **position,
            "modal": {"mode": modes[p], "wave_definition": data["wave_definition"], "phasor_convention": data["phasor_convention"],
                      "source": "합성 단면의 명시 모드 표 " + str(p + 1), "samples": samples}})
    return data, {"operation": "shift_plane", "lines": lines}


class NamedModalTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("skrf"), "고정 scikit-rf 필요")
    def test_independent_multiport_circuit_and_inverse(self):
        """! @brief 각 포트에 scikit-rf 독립 분산 선로를 붙인 회로, 두 위상 규약과 이동 역연산을 대조한다."""
        import numpy as np
        import skrf as rf
        from skrf.circuit import Circuit

        peak, inverse_peak = 0.0, 0.0
        for n in range(1, 5):
            for negative in (False, True):
                data, options = setup(n, negative)
                original = deepcopy(data)
                calculation = transform_dataset(data, options)
                values = np.array(data["values_ri"])
                original_s = values[..., 0] + 1j * values[..., 1]
                freq = rf.Frequency.from_f(data["frequency_hz"], unit="hz")
                z0 = np.array(data["z0_ohm"])[..., 0]
                dut = rf.Network(name="DUT", frequency=freq, s=original_s.conj() if negative else original_s, z0=z0)
                connections = []
                for p, line in enumerate(options["lines"]):
                    samples = np.array(line["modal"]["samples"])
                    medium = rf.media.DefinedGammaZ0(freq, z0=samples[:, 3], gamma=samples[:, 1] + 1j * samples[:, 2])
                    segment = medium.line(5 + p, unit="mm", name="L" + str(p))
                    external = Circuit.Port(freq, "P" + str(p), z0=samples[:, 3])
                    connections.extend([[(external, 0), (segment, 0)], [(segment, 1), (dut, p)]])
                expected = Circuit(connections).network.s
                after = np.array(calculation["dataset"]["values_ri"])
                actual = after[..., 0] + 1j * after[..., 1]
                peak = max(peak, float(np.max(abs(actual - (expected.conj() if negative else expected)))))
                inverse_options = deepcopy(options)
                for p, line in enumerate(inverse_options["lines"]):
                    line["reference_plane"] = data["reference_planes"][p]
                    if "segment" in line:
                        segment = line["segment"]
                        segment["from_mm"], segment["to_mm"] = segment["to_mm"], segment["from_mm"]
                    else:
                        line["length_mm"] *= -1
                restored = transform_dataset(calculation["dataset"], inverse_options)["dataset"]
                back = np.array(restored["values_ri"])
                inverse_peak = max(inverse_peak, float(np.max(abs(back[..., 0] + 1j * back[..., 1] - original_s))))
                self.assertEqual(data, original)
                self.assertEqual(restored["reference_planes"], data["reference_planes"])
                for k, row in enumerate(calculation["diagnostics"]):
                    for p, sample in enumerate(row["modal_samples"]):
                        self.assertEqual(sample["beta_rad_per_m"], options["lines"][p]["modal"]["samples"][k][2])
        print("1~4포트 / 두 위상 규약 scikit-rf 최대 복소 차이", peak, "역변환", inverse_peak, flush=True)
        self.assertLess(peak, 1e-12)
        self.assertLess(inverse_peak, 1e-12)

    @unittest.skipUnless(importlib.util.find_spec("skrf"), "고정 scikit-rf 필요")
    def test_tabulated_rectangular_mode_matches_existing_te10(self):
        """! @brief 독립 도파관 모드표의 분산으로 기존 직사각형 TE10 기준면 이동을 재현한다."""
        import numpy as np
        import skrf as rf

        original, options = setup(1)
        frequency = rf.Frequency.from_f(original["frequency_hz"], unit="hz")
        guide = rf.media.RectangularWaveguide(frequency, a=.02, b=.01, m=1, n=0, mode_type="te", rho=None)
        np.testing.assert_allclose(guide.z0.imag, 0, atol=1e-9)
        z = guide.z0.real.astype(float).tolist()
        original["z0_ohm"] = [[[x, 0]] for x in z]
        line = options["lines"][0]
        line["modal"]["samples"] = [[f, 0, float(beta), impedance]
            for f, beta, impedance in zip(original["frequency_hz"], guide.beta, z)]
        supplied = transform_dataset(original, options)["dataset"]["values_ri"]
        older = deepcopy(original)
        older["port_modes"] = ["rectangular_te10"]
        old_line = {k: v for k, v in line.items() if k != "modal"}
        old_line["waveguide"] = {"width_mm": 20, "height_mm": 10, "epsilon_r": 1}
        native = transform_dataset(older, {"operation": "shift_plane", "lines": [old_line]})["dataset"]["values_ri"]
        delta = np.max(np.abs(np.array(supplied) - np.array(native)))
        print("직사각 TE10 경로와 독립 분산표 실수/허수 최대 차이", delta, flush=True)
        self.assertLess(delta, 1e-8)

    def test_missing_basis_or_unmatched_table_and_source(self):
        """! @brief 단면 출처, 감쇠, 주파수, Z0 또는 규약이 다르면 원본 표본을 유추하지 않는다."""
        data, options = setup(2)
        edits = [{"source": ""}, {"wave_definition": "traveling"}, {"phasor_convention": "exp(-j*omega*t)"},
                 {"mode": "mode:다른 모드"}, {"samples": []}]
        for key, value in ((0, 8.001e9), (1, -.1), (2, 0), (3, 0), (3, 50)):
            samples = deepcopy(options["lines"][0]["modal"]["samples"])
            samples[0][key] = value
            edits.append({"samples": samples})
        for edit in edits:
            bad = deepcopy(options)
            bad["lines"][0]["modal"].update(edit)
            with self.subTest(edit=edit), self.assertRaises(ProjectError):
                transform_dataset(data, bad)
        data["values_ri"][1][0][1] = None
        data["valid_mask"][1][0][1] = False
        data["sample_status"][1][0][1] = "missing"
        r = transform_dataset(data, options)
        self.assertIsNone(r["dataset"]["values_ri"][1][0][1])
        self.assertEqual(r["dataset"]["sample_status"][1][0][1], "missing")
        self.assertEqual(r["diagnostics"][1]["valid_channels"], 3)
        subset = transform_dataset(data, {"operation": "shift_plane", "lines": options["lines"][:1]})["dataset"]
        self.assertEqual(subset["reference_planes"][1], data["reference_planes"][1])
        self.assertEqual(subset["values_ri"][0][1][1], data["values_ri"][0][1][1])
        with self.assertRaises(ProjectError):
            transform_input(data, {"operation": "shift_plane", "line_table": "1 | 5 | MODE(모드 1) | - | 외부면"})

    def test_four_port_full_frequency_budget_preserves_each_modal_row(self):
        """! @brief 네 포트의 최대 1001점 분산표도 단일 진단 원문과 작은 출처 정보로 되찾는다."""
        base, spec = setup(4)
        count = 1001
        freqs = [int(8e9) + i * 1_000_000 for i in range(count)]
        ids = base["port_ids"]
        data = make_dataset(parameter_kind="S", frequency_hz=freqs, port_ids=ids,
            values_ri=[base["values_ri"][0]] * count, z0_ohm=[base["z0_ohm"][0]] * count,
            wave_definition="power", phasor_convention=base["phasor_convention"], reference_planes=base["reference_planes"],
            port_modes=base["port_modes"], current_orientation=["into_dut"] * 4)
        text, modal = [], []
        for p, line in enumerate(spec["lines"], 1):
            text.append(f"{p} | 5 | MODE(모드 {p}) | - | 새 면{p}")
            modal.append(f"{p} | power | + | 명시 자료 {p}")
            modal.extend(f"{p} | {f} | 0.2 | {122.0 + i * .001} | {base['z0_ohm'][0][p - 1][0]}" for i, f in enumerate(freqs))
        options = transform_input(data, {"operation": "shift_plane", "line_table": "\n".join(text),
                                         "mode_table": "\n".join(modal)})
        result = transform_dataset(data, options)
        self.assertEqual(len(result["diagnostics"]), count)
        saved = result["dataset"]["provenance"]["network_operations"][0]["options"]["lines"]
        for p, line in enumerate(saved):
            samples = [row["modal_samples"][p] for row in result["diagnostics"]]
            values = [[row[k] for k in ("frequency_hz", "alpha_np_per_m", "beta_rad_per_m", "mode_impedance_ohm")] for row in samples]
            self.assertEqual(canonical_hash(values), line["modal"]["samples_sha256"])
            self.assertEqual(line["modal"]["sample_count"], count)

    def test_import_review_apply_and_diagnostics_reopen(self):
        """! @brief 폼에서 모드를 등록하고 분산표로 이동한 실제 서비스 개정과 진단을 재열어 대조한다."""
        import test_network_service as fixtures

        f = fixtures.NetworkServiceTests()
        f.setUp()
        self.addCleanup(f.tearDown)
        params = fixtures.import_parameters()
        params["declarations"]["port_modes"] = ["mode:slot A"]
        original = f.apply("import", params)
        before = f.read("network.get", dataset_id=original, offset=0, limit=201, row=0, column=0)
        options = {"operation": "shift_plane", "line_table": "1 | 0,0,0 > 3,4,0 > 3,4,0 | MODE(slot A) | - | 새 면",
                   "mode_table": "1 | traveling | + | 별도 단면 표 A\n1 | 1e9 | 0.1 | 31 | 50\n1 | 1.5e9 | 0.2 | 45 | 50\n1 | 2e9 | 0.3 | 58 | 50"}
        result = f.apply("transform", {"name": "모드면 이동", "dataset_id": original, "options": options})
        f.save_reopen()
        read = f.read("network.get", dataset_id=result, offset=0, limit=201, row=0, column=0)
        self.assertEqual(read["descriptor"]["reference_planes"], ["새 면"])
        self.assertEqual(read["descriptor"]["port_modes"], ["mode:slot A"])
        rows = f.read("network.diagnostics", dataset_id=result, offset=0, limit=32)
        self.assertEqual([r["modal_samples"][0]["beta_rad_per_m"] for r in rows["diagnostics"]], [31, 45, 58])
        import json
        saved = json.loads(f.service.journal.read_artifact(read["entry"]["dataset"]))
        evidence = saved["provenance"]["network_operations"][-1]["options"]["lines"][0]["modal"]
        self.assertEqual(evidence["source"], "별도 단면 표 A")
        reconstructed = [[sample["frequency_hz"], sample["alpha_np_per_m"], sample["beta_rad_per_m"], sample["mode_impedance_ohm"]]
                         for r in rows["diagnostics"] for sample in r["modal_samples"]]
        self.assertEqual(canonical_hash(reconstructed), evidence["samples_sha256"])
        again = f.read("network.get", dataset_id=original, offset=0, limit=201, row=0, column=0)
        self.assertEqual(again["page"], before["page"])
