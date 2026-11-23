"""! @brief 실제 3/4포트 PCB의 모든 여기, 독립 CalcPort 검산과 행렬 교환을 확인한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID, uuid5

from rfad.adapters.network_touchstone import parse_touchstone
from rfad.application.pcb_solver import check_pcb_input
from rfad.application.pcb_projection import project_pcb
from test_pcb_multiport import input_pair


def fixture(count):
    """! @brief 원형 기판 원호 개정에 서로 떨어진 선분 쌍과 객체별 접촉 단자를 추가한다."""
    doc, settings = input_pair("pcb_worker_smoke")
    parent = UUID(doc["revision_id"])
    doc["revision_id"] = str(uuid5(parent, f"{count}-port-coupled-board"))
    doc["parent_revision_ids"] = [str(parent)]
    doc["board"]["outline"]["radius"]["value_si"] = 0.013
    template = doc["ports"][1]
    for index in range(3, count + 1):
        delta = (index - 2) * -0.003
        port = deepcopy(template)
        port.update(id=str(uuid5(parent, f"port-{index}")), name=f"P{index}")
        port["resistance"]["value_si"] = 50.0 + 5.0 * index
        for endpoint in ("start", "stop"):
            port["excitation_box"][endpoint][1]["value_si"] += delta
        for key in ("reference_geometry_id", "positive_geometry_id"):
            shape = deepcopy(next(g for g in doc["geometry"] if g["id"] == template[key]))
            shape["id"] = str(uuid5(parent, f"{index}-{key}"))
            for endpoint in ("start", "end"):
                shape[endpoint][1]["value_si"] += delta
            port[key] = shape["id"]
            doc["geometry"].append(shape)
        doc["ports"].append(port)
    for group in ("ports", "geometry"):
        doc[group].sort(key=lambda item: item["id"])
    return doc, settings


class ExtendedPorts(unittest.TestCase):
    """! @brief 서로 다른 종단, 비대칭 입력 행렬 및 주파수별 실제 응답 순서를 확인한다."""

    def test_design_projects_every_feed_and_v1_row_order(self):
        for n in (3, 4):
            doc, settings = fixture(n)
            check_pcb_input(doc, settings)
            case = project_pcb(doc, settings, multiport=True)["case"]
            self.assertEqual([p["number"] for p in case["ports"]], list(range(1, n+1)))
            self.assertEqual([p["id"] for p in case["ports"]], [p["id"] for p in doc["ports"]])
            raw = "# GHz S RI R 50\n"
            for r in range(n):
                raw += ("1 " if r == 0 else "") + " ".join(f"{10*r+c} {r-c}" for c in range(n)) + "\n"
            dataset = parse_touchstone(raw.encode(), f"order.s{n}p")["network"]
            for r in range(n):
                for c in range(n):
                    self.assertEqual(dataset["values_ri"][0][r][c], [10*r+c, r-c])

    def test_exchange_quality_and_restricted_operations(self):
        """! @brief 비대칭 행렬 모든 원소의 CSV/HDF와 치구/RLC 거절을 점검한다."""
        import numpy as np
        from rfad.adapters.network_files import parse_csv, csv_export_mapping, write_csv, write_touchstone
        from rfad.adapters.network_hdf5 import encode_network_hdf5, decode_network_hdf5
        from rfad.application.network_records import samples
        from rfad.domain.network_data import make_dataset
        from rfad.domain.network_transform import transform_dataset
        from rfad.domain.network_circuit import apply_circuit
        from rfad.domain.errors import ProjectError
        from test_network_domain import circuit

        for n in (3, 4):
            doc, _ = fixture(n)
            matrix = [[[(r+1)/(c+2), (r-c)*0.01] for c in range(n)] for r in range(n)]
            data = make_dataset(parameter_kind="S", frequency_hz=[1e9], port_ids=[p["id"] for p in doc["ports"]],
                                values_ri=[matrix], z0_ohm=[[[50, 0] for _ in range(n)]],
                                port_modes=["single_ended"]*n, current_orientation=["into_dut"]*n,
                                reference_planes=["physical gap"]*n, phasor_convention="exp(+j*omega*t)", wave_definition="power")
            self.assertEqual(decode_network_hdf5(encode_network_hdf5(data)), data)
            self.assertEqual(parse_csv(write_csv(data), csv_export_mapping(data))["network"]["values_ri"], [matrix])
            self.assertEqual(parse_touchstone(write_touchstone(data), f"test.s{n}p")["network"]["values_ri"], [matrix])
            row = samples(data, row=n-1, column=n-2)["samples"][0]
            z = np.asarray(matrix)[...,0] + 1j*np.asarray(matrix)[...,1]
            self.assertAlmostEqual(row["sigma_max"], np.linalg.svd(z, compute_uv=False)[0])
            self.assertAlmostEqual(row["reciprocity_residual"], np.max(np.abs(z-z.T)))
            with self.assertRaises(ProjectError) as fixture_error:
                transform_dataset(data, {"operation": "deembed_fixtures", "left": data, "right": data, "fixture_ids": []})
            self.assertEqual(fixture_error.exception.code, "E_UNSUPPORTED")
            with self.assertRaises(ProjectError) as circuit_error:
                apply_circuit(data, circuit())
            self.assertEqual(circuit_error.exception.code, "E_UNSUPPORTED")

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 Linux openEMS 필요")
    def test_all_excitations_and_official_complex_port_waves(self):
        """! @brief 모든 실제 종단 U/I를 공식 도구로 재계산하고 N*N개의 S를 별도로 검증한다."""
        import CSXCAD
        import numpy as np
        import openEMS
        from rfad.adapters.solvers.openems.pcb_multiport import run
        from rfad.application.canonical import canonical_hash

        with TemporaryDirectory() as tmp:
            for n in (3, 4):
                doc, settings = fixture(n)
                root = Path(os.environ.get("RFAD_EXTENDED_RESULTS", tmp)) / f"board-{n}"
                summary = json.loads(run(doc, settings, root).read_bytes())
                dataset = json.loads((root / "network.json").read_bytes())
                case = json.loads((root / "case.json").read_bytes())
                self.assertEqual(len(summary["runs"]), n)
                self.assertEqual(summary["mesh_sha256"], canonical_hash(json.loads((root / "mesh.json").read_bytes())))
                freqs = np.asarray(dataset["frequency_hz"])
                reference = np.empty((len(freqs), n, n), dtype=np.complex128)
                output = np.empty_like(reference)
                for drive, record in enumerate(summary["runs"]):
                    self.assertEqual(record["termination"]["status"], "end_criterion_reached")
                    self.assertEqual(record["mesh_sha256"], summary["mesh_sha256"])
                    self.assertEqual(len(record["contacts"]), n)
                    csx = CSXCAD.ContinuousStructure()
                    solver = openEMS.openEMS()
                    solver.SetCSX(csx)
                    for row, p in enumerate(case["ports"]):
                        native = solver.AddLumpedPort(row+1, p["resistance_ohm"], p["start_mm"], p["stop_mm"],
                                                      p["axis"], excite=int(row == drive))
                        native.CalcPort(str(root / f"excitation-{drive+1}"), freqs, ref_impedance=p["resistance_ohm"])
                        reference[:,row,drive] = native.uf_inc / np.sqrt(p["resistance_ohm"])
                        output[:,row,drive] = native.uf_ref / np.sqrt(p["resistance_ohm"])
                values = np.asarray(dataset["values_ri"])
                actual = values[...,0] + 1j*values[...,1]
                np.testing.assert_allclose(actual, output @ np.linalg.inv(reference), atol=1e-8, rtol=1e-8)
                touchstone = root / f"network.s{n}p"
                reread = parse_touchstone(touchstone.read_bytes(), touchstone.name)["network"]
                self.assertEqual(reread["values_ri"], dataset["values_ri"])
                print(json.dumps({"ports": n, "samples": len(freqs), "max_official_difference":
                      float(np.max(np.abs(actual - output @ np.linalg.inv(reference))))}), flush=True)
