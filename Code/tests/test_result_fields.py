"""! @brief 고정 HDF5 격자/단면/손실 원문과 읽기 전용 결과 경계를 검증한다."""

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.adapters import field_hdf5
from rfad.application import result_fields
from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError


def reference(path, uri=None):
    """! @brief 명시 시험 원문의 바이트/해시를 봉인한다."""
    raw = path.read_bytes()
    return {"uri": uri or path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def expected():
    """! @brief 단위/축이 독립적으로 알려진 작은 비등간 격자를 정의한다."""
    return {"shape": [4, 3, 2], "frequency_hz": [1e9, 2e9], "dump_type": 0,
            "primary_coordinates_mm": {"x": [0., 1., 3., 6.], "y": [10., 12., 16.], "z": [-2., 0.]}}


def create(path, declaration=None):
    """! @brief 실제 h5py 엔진에 단순 복소 표본을 기록하되 RF 물리 자료로 표시하지 않는다."""
    import h5py
    import numpy as np
    declaration = declaration or expected()
    shape = declaration["shape"]
    data = np.empty((3, *shape), dtype="<c8")
    for c in range(3):
        for x in range(shape[0]):
            for y in range(shape[1]):
                for z in range(shape[2]):
                    v = c*1000+x*100+y*10+z
                    data[c, x, y, z] = complex(v, -v)
    data[0, 0, 0, 0] = 3+4j
    data[0, 1, 0, 0] = 0
    with h5py.File(path, "w") as f:
        f.attrs["openEMS_HDF5_version"] = 0.3
        f.attrs["dual_mesh"] = np.uint8(0)
        f.attrs["dump_type"] = np.int32(declaration["dump_type"])
        mesh = f.create_group("Mesh")
        mesh.attrs["mesh_type"] = np.int32(0)
        mesh.attrs["mesh_scaling"] = 0.001
        for axis in "xyz":
            mesh.create_dataset(axis, data=np.array(declaration["primary_coordinates_mm"][axis], dtype="<f8")*0.001)
        fd = f.create_group("FieldData").create_group("FD")
        fd.attrs["frequency"] = declaration["frequency_hz"]
        for i, frequency in enumerate(declaration["frequency_hz"]):
            ds = fd.create_dataset("f"+str(i), data=data, dtype="<c8")
            ds.attrs["d_order"] = "NXYZ"
            ds.attrs["frequency"] = frequency
    return data


@unittest.skipUnless(importlib.util.find_spec("h5py"), "고정 h5py 환경이 필요합니다.")
class FieldHdf5Tests(unittest.TestCase):
    """! @brief 외부 참조/필터와 무제한 배열 읽기를 제한하는 실제 HDF5 시험이다."""

    def setUp(self):
        """! @brief 다른 시험/원본과 분리된 임시 파일을 만든다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)/"field.h5"
        self.data = create(self.path)

    def test_hyperslab_orientation_and_no_full_field_read(self):
        """! @brief 원본 NXYZ의 선택만 읽고 반환 행을 v/열을 u로 검증한다."""
        import h5py
        original = h5py.Dataset.__getitem__
        reads = []
        def traced(dataset, value, *args, **kwargs):
            reads.append((dataset.name, value))
            return original(dataset, value, *args, **kwargs)
        selection = {"component_index": 2, "frequency_index": 1, "x": slice(1, 4, 2), "y": 1, "z": slice(0, 2, 1)}
        with patch.object(h5py.Dataset, "__getitem__", traced):
            description = field_hdf5.read(self.path, reference(self.path), expected())
            self.assertIsNone(description["values"])
            self.assertFalse(any(name.startswith("/FieldData/") for name, _ in reads))
            observed = field_hdf5.read(self.path, reference(self.path), expected(), selection)
        self.assertEqual(observed["values"].tolist(), self.data[2, 1:4:2, 1, 0:2].T.tolist())
        field_reads = [key for name, key in reads if name.startswith("/FieldData/")]
        self.assertEqual(field_reads, [(2, slice(1, 4, 2), 1, slice(0, 2, 1))])

    def test_sealed_hash_checked_before_native_open(self):
        """! @brief 전체 파일 hash가 다르면 HDF5 객체를 열지 않는다."""
        import h5py
        ref = reference(self.path)
        with self.path.open("ab") as f:
            f.write(b"changed")
        with patch.object(h5py, "File", side_effect=AssertionError("must not open")):
            with self.assertRaises(ProjectError) as raised:
                field_hdf5.read(self.path, ref, expected())
        self.assertEqual(raised.exception.code, "E_HASH")

    def test_links_filters_external_storage_and_alias_are_rejected(self):
        """! @brief 다른 파일/필터/별칭으로 본문을 대체하는 모든 경로를 선행 차단한다."""
        import h5py
        import numpy as np
        def replace(f, mode):
            if mode == "soft":
                del f["Mesh/x"]; f["Mesh/x"] = h5py.SoftLink("/Mesh/y")
            elif mode == "external_link":
                del f["Mesh/x"]; f["Mesh/x"] = h5py.ExternalLink("not-to-read.h5", "/secret")
            elif mode == "alias":
                del f["FieldData/FD/f1"]; f["FieldData/FD/f1"] = f["FieldData/FD/f0"]
            else:
                del f["FieldData/FD/f0"]
                if mode == "filter":
                    f["FieldData/FD"].create_dataset("f0", data=self.data, compression="gzip")
                elif mode == "external_storage":
                    f["FieldData/FD"].create_dataset("f0", shape=self.data.shape, dtype="<c8", external=[("not-to-read.bin", 0, h5py.h5f.UNLIMITED)])
                elif mode == "virtual":
                    layout = h5py.VirtualLayout(shape=self.data.shape, dtype="<c8")
                    layout[:] = h5py.VirtualSource("not-to-read.h5", "secret", shape=self.data.shape)
                    f["FieldData/FD"].create_virtual_dataset("f0", layout)
                else:
                    f["FieldData/FD"].create_dataset("f0", shape=(3, 1000000000, 3, 2), dtype="<c8")
                f["FieldData/FD/f0"].attrs["d_order"] = "NXYZ"
                f["FieldData/FD/f0"].attrs["frequency"] = 1e9
        for mode in ("soft", "external_link", "alias", "filter", "external_storage", "virtual", "huge_shape"):
            with self.subTest(mode=mode):
                create(self.path)
                with h5py.File(self.path, "r+") as f:
                    replace(f, mode)
                with self.assertRaises(ProjectError):
                    field_hdf5.read(self.path, reference(self.path), expected())

    def test_coordinate_frequency_dtype_and_dual_mesh_mismatch(self):
        """! @brief 비슷한 주파수/격자나 다른 성분 저장 형식으로 묵시 대체하지 않는다."""
        import h5py
        def alter(f, mode):
            if mode == "frequency": f["FieldData/FD"].attrs["frequency"] = [1e9, 2e9+1]
            elif mode == "coordinate": f["Mesh/x"][2] += 0.0001
            elif mode == "dual": f.attrs["dual_mesh"] = .5
            elif mode == "order": f["FieldData/FD/f0"].attrs["d_order"] = "NZYX"
            elif mode == "dtype":
                del f["FieldData/FD/f0"]
                ds = f["FieldData/FD"].create_dataset("f0", data=self.data.astype("<c16"))
                ds.attrs["d_order"] = "NXYZ"; ds.attrs["frequency"] = 1e9
            else: f.attrs["legacy_fmt"] = True
        for mode in ("frequency", "coordinate", "dual", "order", "dtype", "legacy"):
            with self.subTest(mode=mode):
                create(self.path)
                with h5py.File(self.path, "r+") as f: alter(f, mode)
                with self.assertRaises(ProjectError): field_hdf5.read(self.path, reference(self.path), expected())

    def test_large_raw_file_uses_slice_without_metadata_read_limit(self):
        """! @brief 48 MiB를 넘는 실제 파일은 작은 단면만 읽고 과대 ROI는 차단한다."""
        import h5py
        import numpy as np
        declaration = {"shape": [512, 192, 28], "frequency_hz": [1e9], "dump_type": 0,
            "primary_coordinates_mm": {axis: list(range(count)) for axis, count in zip("xyz", (512, 192, 28))}}
        with h5py.File(self.path, "r+") as f:
            for axis in "xyz":
                del f["Mesh/"+axis]
                f["Mesh"].create_dataset(axis, data=np.array(declaration["primary_coordinates_mm"][axis], dtype="<f8")*.001)
            del f["FieldData/FD/f0"]; del f["FieldData/FD/f1"]
            f["FieldData/FD"].attrs["frequency"] = [1e9]
            ds = f["FieldData/FD"].create_dataset("f0", data=np.full((3, *declaration["shape"]), 3+4j, dtype="<c8"))
            ds.attrs["d_order"] = "NXYZ"; ds.attrs["frequency"] = 1e9
        ref = reference(self.path)
        self.assertGreater(ref["bytes"], 48 * 1024 * 1024)
        selection = {"component_index": 0, "frequency_index": 0, "x": slice(0, 2), "y": slice(10, 12), "z": 1}
        result = field_hdf5.read(self.path, ref, declaration, selection)
        self.assertEqual(result["values"].tolist(), [[3+4j,3+4j],[3+4j,3+4j]])
        oversized = selection | {"x": slice(0, 512), "y": slice(0, 192)}
        with self.assertRaises(ProjectError) as error:
            field_hdf5.read(self.path, ref, declaration, oversized)
        self.assertEqual(error.exception.code, "E_RESOURCE")


@unittest.skipUnless(importlib.util.find_spec("h5py"), "고정 h5py 환경이 필요합니다.")
class ResultFieldTests(unittest.TestCase):
    """! @brief source와 미정 상태를 보존하며 원본 ROI/성분/표시값을 독립 검증한다."""

    def setUp(self):
        """! @brief 모델 생성기와 독립인 작은 명시 격자를 결과 기록에 연결한다."""
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.model = expected()
        self.lines = {"x": [0., 1., 3., 6., 10.], "y": [10., 12., 16., 22.], "z": [-2., 0., 4.]}
        self.resolved = {"source": {"kind": "solver", "artifact_id": str(uuid4())},
            "pin": {"identity_hash": "a"*64, "dataset_sha256": "b"*64}, "project": {"path": "projects/demo"},
            "source_document": {"source_refs": ["합성 시험 원문"], "manufacturing": None, "measurement": None}}
        recording = {"schema": "rfad.pcb-loss-recording/0.1", "dump_mode": 0, "dump_types": [10, 12, 13],
                     "start_indices": [0, 0, 0], "stop_indices": [3, 2, 1], "frequency_hz": [1e9, 2e9],
                     "start_mm": [0., 10., -2.], "stop_mm": [6., 16., 0.]}
        normalized = {"provenance": {"analysis_plan": {"case": {"loss_recording": recording}}},
            "power_balance": {"recording": deepcopy(recording)}, "raw_manifest": {"complete": True, "files": []},
            "mesh_statistics": {"native_length_unit": "mm", "delta_unit_m": .001, "lines_mm": deepcopy(self.lines)},
            "normalization": {"fourier_convention": "exp(-j*2*pi*f*t)", "native_fourier_scale": "2*dt*sum(value*exp(-j*2*pi*f*t))"}}
        self.resolved["normalized"] = normalized
        self.resolved["solver_record"] = {"normalized": {"uri": "projects/demo/result.json"}, "raw_files": []}
        for _, (name, _, _, dump_type, _) in result_fields.MONITORS.items():
            path = self.root/name
            declaration = deepcopy(self.model); declaration["dump_type"] = dump_type
            create(path, declaration)
            ref = reference(path, "projects/demo/"+name)
            item = {"path": "output/raw/"+name, "role": "raw/"+name, "sha256": ref["sha256"], "bytes": ref["bytes"]}
            normalized["raw_manifest"]["files"].append(item)
            self.resolved["solver_record"]["raw_files"].append({**item, "artifact": ref})
        self.service = SimpleNamespace(journal=SimpleNamespace(_mutex=RLock(), _ensure_open=lambda: None,
            _safe_path=lambda uri: self.root/uri.split("/")[-1]))
        self.parameters = {"monitor_id": "electric", "frequency_index": 0, "component": "x",
            "plane": {"normal_axis": "z", "index": 0}, "roi": {"u_start": 0, "u_count": 4, "v_start": 0, "v_count": 3}, "stride": 1}

    def test_description_and_marker_keep_staggered_coordinates_and_source(self):
        """! @brief 성분 edge의 중점과 외곽 다음 격자를 독립 계산하며 원문 null은 바꾸지 않는다."""
        before = deepcopy(self.resolved)
        desc = result_fields.describe(self.service, self.resolved)
        self.assertEqual(len(desc["monitors"]), 3)
        e = desc["monitors"][0]
        self.assertEqual(e["components"][0]["coordinates_mm"]["x"], [.5, 2., 4.5, 8.])
        self.assertEqual(e["components"][1]["coordinates_mm"]["y"], [11., 14., 19.])
        self.assertEqual(e["components"][1]["coordinates_mm"]["x"], [0., 1., 3., 6.])
        page = result_fields.page(self.service, self.resolved, self.parameters)
        self.assertEqual(page["values_ri"][0][0], [3., 4.])
        self.assertEqual(page["magnitude"][0][0], 5.)
        self.assertAlmostEqual(page["phase_deg"][0][0], 53.13010235415598)
        self.assertIsNone(page["phase_deg"][0][1])
        self.assertEqual(page["state"][0][1], "zero_magnitude_phase_undefined")
        self.assertEqual(page["normal_position_mm"], -2.)
        self.assertEqual(page["selection"], self.parameters)
        self.assertEqual(page["color_scope"], "returned_page_magnitude")
        self.assertEqual(self.resolved, before)

    def test_roi_stride_transposition_and_phase_are_raw(self):
        """! @brief stride는 원본 인덱스를 남기고 rotH 위상을 임의 보정하지 않는다."""
        p = deepcopy(self.parameters)
        p.update(monitor_id="total_current", component="z", frequency_index=1, stride=2)
        p["plane"] = {"normal_axis": "y", "index": 1}
        p["roi"] = {"u_start": 1, "u_count": 3, "v_start": 0, "v_count": 2}
        result = result_fields.page(self.service, self.resolved, p)
        self.assertEqual(result["u_indices"], [1, 3]); self.assertEqual(result["v_indices"], [0])
        self.assertEqual(result["values_ri"], [[[2110., -2110.], [2310., -2310.]]])
        self.assertEqual(result["phase_deg"], [[-45., -45.]])
        self.assertEqual(result["phase_correction"], "none_raw_time_location")
        self.assertEqual(result["unit"], "A*s/m^2")

    def test_missing_field_does_not_invent_data(self):
        """! @brief imported/회로/미기록 자료에는 빈 설명만 반환한다."""
        r = deepcopy(self.resolved); r["normalized"] = None; r["solver_record"] = None
        self.assertEqual(result_fields.describe(self.service, r)["monitors"], [])
        with self.assertRaises(ProjectError): result_fields.page(self.service, r, self.parameters)

    def test_missing_recorded_mesh_or_wrong_units_never_regenerates_past_grid(self):
        """! @brief 실제 격자 없는 과거 기록은 현재 생성기로 조용히 복원하지 않는다."""
        for kind in ("missing", "unit", "endpoint"):
            r = deepcopy(self.resolved)
            if kind == "missing": del r["normalized"]["mesh_statistics"]["lines_mm"]
            elif kind == "unit": r["normalized"]["mesh_statistics"]["native_length_unit"] = "m"
            else:
                r["normalized"]["provenance"]["analysis_plan"]["case"]["loss_recording"]["stop_mm"][0] = 7.
                r["normalized"]["power_balance"]["recording"]["stop_mm"][0] = 7.
            with self.subTest(kind=kind), self.assertRaises(ProjectError): result_fields.describe(self.service, r)

    def test_selection_bounds_and_response_budget_are_explicit(self):
        """! @brief bool/음수/없는성분/넘친ROI를 거절하고 큰 응답은 자르지 않는다."""
        for field, value in (("monitor_id", {}), ("component", "abs_e"), ("frequency_index", True), ("stride", 0)):
            p = deepcopy(self.parameters); p[field] = value
            with self.subTest(field=field), self.assertRaises(ProjectError): result_fields.page(self.service, self.resolved, p)
        p = deepcopy(self.parameters); p["roi"]["u_count"] = 5
        with self.assertRaises(ProjectError): result_fields.page(self.service, self.resolved, p)
        with patch.object(result_fields, "MAX_RESPONSE", 100), self.assertRaises(ProjectError) as error:
            result_fields.page(self.service, self.resolved, self.parameters)
        self.assertEqual(error.exception.code, "E_RESOURCE")

    def test_source_manifest_mismatch_blocks_read(self):
        """! @brief 소유record만 바꿔 다른 hash의 HDF를 연결할 수 없다."""
        self.resolved["solver_record"]["raw_files"][0]["artifact"]["sha256"] = "c"*64
        with self.assertRaises(ProjectError) as raised: result_fields.describe(self.service, self.resolved)
        self.assertEqual(raised.exception.code, "E_HASH")

    def test_nonfinite_raw_point_is_preserved_as_unavailable_not_zero(self):
        """! @brief 비유한 원문 점은 값/색/위상을 null로 하고 명시 상태를 남긴다."""
        import h5py
        path = self.root/"pcb_loss_E.h5"
        with h5py.File(path, "r+") as f:
            f["FieldData/FD/f0"][0, 0, 0, 0] = complex(float("nan"), 0)
        ref = reference(path, "projects/demo/pcb_loss_E.h5")
        item = self.resolved["solver_record"]["raw_files"][0]
        item["artifact"] = ref
        for key in ("bytes", "sha256"):
            item[key] = ref[key]
            self.resolved["normalized"]["raw_manifest"]["files"][0][key] = ref[key]
        result = result_fields.page(self.service, self.resolved, self.parameters)
        self.assertEqual(result["state"][0][0], "nonfinite")
        for key in ("values_ri", "magnitude", "phase_deg", "color"):
            self.assertIsNone(result[key][0][0])
        self.assertFalse(result["physics_validated"])

    def test_output_point_limit_is_applied_after_explicit_stride(self):
        """! @brief 원문 ROI와 반환 표본 수를 구분하되 4096개 초과는 계산 전에 막는다."""
        model = {"shape": [100, 100, 1], "frequency_hz": [1e9]}
        p = deepcopy(self.parameters); p["roi"] = {"u_start":0,"u_count":100,"v_start":0,"v_count":100}
        with self.assertRaises(ProjectError) as error: result_fields._selection(model, p)
        self.assertEqual(error.exception.code, "E_RESOURCE")
        p["stride"] = 2
        _, _, indices = result_fields._selection(model, p)
        self.assertEqual(len(indices[0])*len(indices[1]), 2500)
        self.assertEqual(indices[0][-1], 98)


@unittest.skipUnless(os.environ.get("RFAD_TEST_FIELD_WORKSPACE"), "실제 필드 원문의 격리 복사 workspace가 필요합니다.")
class ActualRecordedFieldTests(unittest.TestCase):
    """! @brief 보존한 실제 openEMS 원문을 새 계산 없이 RPC로 읽고 재열기를 검증한다."""

    def test_real_recorded_components_all_planes_and_runtime_free_reopen(self):
        """! @brief 세 실제 필드의 모든 성분/단면을 원문 hyperslab과 독립 대조한다."""
        import h5py
        from rfad.application.projects import ProjectService
        from rfad.application.rpc import handle_frame
        workspace = Path(os.environ["RFAD_TEST_FIELD_WORKSPACE"])
        artifact_id = os.environ.get("RFAD_TEST_FIELD_ARTIFACT", "a73812c0-9c38-4b82-bd9b-99f7066752dc")
        service = ProjectService(workspace, auto_run=False)
        try:
            state = service.journal.read()
            record = state["solver_results"][artifact_id]
            project_id = record["project_id"]
            source = {"kind": "solver", "artifact_id": artifact_id}
            def rpc(method, data):
                response = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": method,
                    "params": {"contract_version": "rfad.api/2.0", "context": {"project_id": project_id}, "input": data}}), service=service)
                self.assertNotIn("error", response, response)
                return response["result"]
            description = rpc("result.describe", {"source": source})
            pin = description["pin"]
            original = deepcopy(service.journal.read())
            normalized = service.journal.read_artifact(record["normalized"])
            raw_refs = [item["artifact"] for item in record["raw_files"] if "pcb_loss_" in item["role"]]
            raw_before = {ref["uri"]: reference(workspace/ref["uri"]) for ref in raw_refs}
            fields = rpc("result.field.describe", {"source": source, "pin": pin})
            self.assertEqual(fields["status"], "available")
            self.assertEqual(len(fields["monitors"]), 3)
            checked = []
            for monitor in fields["monitors"]:
                for c, component in enumerate(monitor["components"]):
                    for normal in "xyz":
                        axis = "xyz".index(normal)
                        index = component["shape"][axis]//2
                        other = [a for a in "xyz" if a != normal]
                        request = {"monitor_id": monitor["monitor_id"], "frequency_index": 1, "component": component["component"],
                            "plane": {"normal_axis": normal, "index": index}, "roi": {
                                "u_start": 0, "u_count": min(6, component["shape"]["xyz".index(other[0])]),
                                "v_start": 0, "v_count": min(5, component["shape"]["xyz".index(other[1])])}, "stride": 2}
                        result = rpc("result.field.page", {"source": source, "pin": pin, **request})
                        slices = [c]
                        for a in "xyz":
                            if a == normal: slices.append(index)
                            else:
                                prefix = "u" if a == other[0] else "v"
                                slices.append(slice(0, request["roi"][prefix+"_count"], 2))
                        with h5py.File(workspace/monitor["source_ref"]["uri"], "r") as f:
                            values = f["FieldData/FD/f1"][tuple(slices)].T
                        wanted = [[[float(v.real), float(v.imag)] for v in row] for row in values]
                        self.assertEqual(result["values_ri"], wanted)
                        self.assertEqual(result["normal_position_mm"], component["coordinates_mm"][normal][index])
                        self.assertLessEqual(len(canonical_bytes(result)), 256*1024)
                        self.assertFalse(result["physics_validated"])
                        checked.append({"monitor": monitor["monitor_id"], "component": component["component"], "normal_axis": normal,
                                        "source_sha256": monitor["source_ref"]["sha256"], "response_sha256": hashlib.sha256(canonical_bytes(result)).hexdigest()})
            self.assertEqual(len(checked), 27)
            self.assertEqual(service.journal.read(), original)
            self.assertEqual(service.journal.read_artifact(record["normalized"]), normalized)
            for ref in raw_refs:
                self.assertEqual(reference(workspace/ref["uri"]), raw_before[ref["uri"]])
            service.close()
            service = ProjectService(workspace, auto_run=False)
            self.assertEqual(rpc("result.field.describe", {"source": source, "pin": pin}), fields)
            output = os.environ.get("RFAD_TEST_FIELD_REPORT")
            if output:
                Path(output).write_text(json.dumps({"status": "passed", "workspace": str(workspace), "source": source, "pin": pin,
                    "monitors": [{k:v for k,v in item.items() if k != "components"} for item in fields["monitors"]],
                    "checked_hyperslabs": checked, "normalized_unchanged": True, "raw_unchanged": True,
                    "journal_unchanged_during_reads": True, "runtime_free_reopen": True, "new_fdtd_executed": False,
                    "physics_validated": False}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
