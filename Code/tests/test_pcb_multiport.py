"""! @brief 원호와 IFA 파생 개정의 두 급전, 공통 격자와 독립 행렬 계산을 검사한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID, uuid5

from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_projection import check_feed_intersection, project_pcb
from rfad.application.pcb_solver import check_pcb_input
from rfad.domain.errors import ProjectError


def input_pair(name):
    """! @brief 기존 예제를 보존하고 위치와 저항을 명시한 새 검증 개정을 만든다."""
    path = Path(__file__).resolve().parents[1] / "fixtures" / (name + ".json")
    example = json.loads(path.read_text(encoding="utf-8"))
    doc = example["document"]
    parent = UUID(doc["revision_id"])
    doc["revision_id"] = str(uuid5(parent, "two-port-validation"))
    doc["parent_revision_ids"] = [str(parent)]
    second = deepcopy(doc["ports"][0])
    second.update(id="ffff" + str(uuid5(parent, "second-port"))[4:], name="Second test gap")
    second["resistance"]["value_si"] = 75.0
    if name == "pcb_worker_smoke":
        # @brief 원호 아래에 3 mm 떨어진 별도 선분 쌍을 두어 전자기 결합을 확인한다.
        for key in ("reference_geometry_id", "positive_geometry_id"):
            original = next(row for row in doc["geometry"] if row["id"] == second[key])
            copy = deepcopy(original)
            copy["id"] = str(uuid5(parent, key))
            for endpoint in ("start", "end"):
                copy[endpoint][1]["value_si"] -= 0.003
            doc["geometry"].append(copy)
            second[key] = copy["id"]
        doc["geometry"].sort(key=lambda row: row["id"])
        for endpoint in ("start", "stop"):
            second["excitation_box"][endpoint][1]["value_si"] -= 0.003
    else:
        # @brief 기존 IFA의 2 mm 패드 가장자리에서 두 번째 급전의 물리 접점을 지정한다.
        for endpoint in ("start", "stop"):
            second["excitation_box"][endpoint][0]["value_si"] += 0.0005
    doc["ports"].append(second)
    return doc, example["settings"]


class MultiportTests(unittest.TestCase):
    """! @brief 원본의 단일 급전 보존과 두 급전의 독립 위치를 확인한다."""

    def test_project_and_common_mesh(self):
        for name in ("pcb_worker_smoke", "ifa_feed_smoke"):
            with self.subTest(name=name):
                doc, settings = input_pair(name)
                original = deepcopy(doc)
                check_pcb_input(doc, settings)
                case = project_pcb(doc, settings, multiport=True)["case"]
                self.assertEqual([port["number"] for port in case["ports"]], [1, 2])
                self.assertEqual([port["resistance_ohm"] for port in case["ports"]], [50, 75])
                lines = mesh_lines(case)
                for port in case["ports"]:
                    for i, axis in enumerate("xyz"):
                        self.assertIn(round(port["start_mm"][i], 12), lines[axis])
                        self.assertIn(round(port["stop_mm"][i], 12), lines[axis])
                self.assertEqual(doc, original)
                with self.assertRaises(ProjectError):
                    project_pcb(doc, settings)

    def test_overlapping_feeds_are_rejected(self):
        doc, settings = input_pair("ifa_feed_smoke")
        doc["ports"][1]["excitation_box"] = deepcopy(doc["ports"][0]["excitation_box"])
        with self.assertRaises(ProjectError) as caught:
            project_pcb(doc, settings, multiport=True)
        self.assertEqual(caught.exception.code, "E_PORT")

    def test_one_shared_ground_terminal_does_not_overlap_gap(self):
        first = {"id": "p1", "start_mm": [0, 0, 0], "stop_mm": [1, 0, 0],
                 "reference_geometry_id": "ground", "positive_geometry_id": "signal1"}
        second = {**first, "id": "p2", "stop_mm": [0, 1, 0], "positive_geometry_id": "signal2"}
        check_feed_intersection(first, second)
        with self.assertRaises(ProjectError):
            check_feed_intersection(first, {**second, "reference_geometry_id": "other"})

    def test_measured_incident_waves_recover_nonsymmetric_network(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("수치 계산은 numpy가 설치된 solver 환경에서 검사합니다.")
        from rfad.adapters.solvers.openems.pcb_multiport import scattering

        expected = np.array([[[0.1j, 0.22 - 0.1j], [0.65 + 0.4j, 0.31]]])
        incident = np.array([[[0.35 + 0.6j, 0.02], [0.11j, 1.7]]])
        measured, _ = scattering(incident, expected @ incident)
        np.testing.assert_allclose(measured, expected, rtol=1e-12, atol=1e-12)
        with self.assertRaises(ProjectError):
            scattering(np.ones_like(incident), expected)

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1",
                         "고정 WSL2 solver와 RFAD_OPENEMS_NATIVE=1이 필요합니다.")
    def test_native_matrix_and_touchstone(self):
        """! @brief 두 실제 개정의 모든 원시 파형을 공식 CalcPort로 독립 재처리한다."""
        import CSXCAD
        import numpy as np
        import openEMS
        from rfad.adapters.network_touchstone import parse_touchstone
        from rfad.adapters.solvers.openems.native import file_identity
        from rfad.adapters.solvers.openems.pcb_multiport import run
        from rfad.application.canonical import canonical_hash

        with TemporaryDirectory() as temporary:
            for name in ("pcb_worker_smoke", "ifa_feed_smoke"):
                with self.subTest(name=name):
                    doc, settings = input_pair(name)
                    saved = os.environ.get("RFAD_MULTIPORT_RESULTS")
                    result_dir = Path(saved or temporary) / (name + "-result")
                    if saved is None:
                        run(doc, settings, result_dir)
                    summary = json.loads((result_dir / "result.json").read_bytes())
                    dataset = json.loads((result_dir / "network.json").read_bytes())
                    self.assertEqual(summary["source_sha256"], canonical_hash(doc))
                    self.assertEqual(summary["settings_sha256"], canonical_hash(settings))
                    ts = parse_touchstone((result_dir / "network.s2p").read_bytes(), "network.s2p")["network"]
                    self.assertEqual(ts["values_ri"], dataset["values_ri"])
                    self.assertEqual(ts["z0_ohm"], dataset["z0_ohm"])
                    f = np.asarray(dataset["frequency_hz"])
                    reference = project_pcb(doc, settings, multiport=True)["case"]["ports"]
                    a = np.zeros((len(f), 2, 2), dtype=complex)
                    b = np.zeros_like(a)
                    for drive, record in enumerate(summary["runs"]):
                        path = result_dir / f"excitation-{drive + 1}"
                        self.assertEqual(record["mesh_sha256"], summary["mesh_sha256"])
                        for filename, stored in record["artifacts"].items():
                            self.assertEqual(file_identity(path / filename), stored)
                        csx = CSXCAD.ContinuousStructure()
                        fdtd = openEMS.openEMS()
                        fdtd.SetCSX(csx)
                        for row, port in enumerate(reference):
                            resistance = port["resistance_ohm"]
                            native = fdtd.AddLumpedPort(row + 1, resistance, port["start_mm"], port["stop_mm"],
                                                       port["axis"], excite=int(row == drive))
                            native.CalcPort(str(path), f, ref_impedance=resistance)
                            a[:, row, drive] = native.uf_inc / np.sqrt(resistance)
                            b[:, row, drive] = native.uf_ref / np.sqrt(resistance)
                    ri = np.asarray(dataset["values_ri"])
                    actual = ri[..., 0] + 1j * ri[..., 1]
                    np.testing.assert_allclose(actual, b @ np.linalg.inv(a), atol=1e-8, rtol=1e-8)
