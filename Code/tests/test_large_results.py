"""! @brief 대용량 원문 등록, 실제 부분 조회, 원본 손상 거절과 Windows 재열기를 대조한다."""

import hashlib
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters import large_result_hdf5 as hdf
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from test_cad_worker_process import register_fixture, request


CODE = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE")


def make_field(path, *, large=False):
    """! @brief 고정 분석식이 있는 두 주파수의 합성 자원을 원본 크기로 기록한다."""
    h5py, np = hdf._runtime()
    shape = (256, 256, 342) if large else (64, 64, 16)
    with h5py.File(path, "x") as handle:
        handle.attrs["openEMS_HDF5_version"] = 0.3
        handle.attrs["dual_mesh"] = np.uint8(0)
        handle.attrs["dump_type"] = np.int32(0)
        mesh = handle.create_group("Mesh")
        mesh.attrs["mesh_type"] = np.int32(0)
        mesh.attrs["mesh_scaling"] = 0.001
        for axis, size in zip("xyz", shape):
            mesh.create_dataset(axis, data=np.arange(size, dtype="<f8") * 0.001)
        fd = handle.create_group("FieldData").create_group("FD")
        fd.attrs["frequency"] = [1e9, 2e9]
        for index, frequency in enumerate(fd.attrs["frequency"]):
            data = fd.create_dataset(f"f{index}", shape=(3, *shape), dtype="<c8")
            data.attrs["d_order"] = "NXYZ"
            data.attrs["frequency"] = frequency
            for component in range(3):
                for left in range(0, shape[0], 8):
                    integers = np.arange(left, min(left+8, shape[0]), dtype=np.float32)
                    block = np.broadcast_to(integers[:, None, None] + component*1000 + (2+index)*1j,
                                            (len(integers), *shape[1:]))
                    data[component, left:left+8, :, :] = np.asarray(block, dtype="<c8")
    if large:
        assert 1024**3 <= path.stat().st_size <= hdf.MAX_FIELD_BYTES


def make_curves(path, count=100_000):
    """! @brief 독립 주파수 축, 한글 출처와 끝부분 결측값을 보존한 여덟 곡선을 만든다."""
    h5py, np = hdf._runtime()
    metadata = {"profile": hdf.TRACE_PROFILE, "quantity": "Z", "unit": "ohm", "curves": [
        {"label": f"복소 곡선 {i+1}", "source": f"합성 시험 원본 {i+1}",
         "reference_ohm": None, "measurement": None} for i in range(8)]}
    with h5py.File(path, "x") as handle:
        handle.create_dataset("metadata_json", data=np.frombuffer(canonical_bytes(metadata), dtype="u1"))
        parent = handle.create_group("traces")
        for i in range(8):
            curve = parent.create_group(f"t{i}")
            axis = np.arange(count, dtype="<f8")*10_000 + 1e9+i*5
            values = np.column_stack((i+1 + np.sin(np.linspace(0, 20, count)), np.full(count, -(i+1))))
            mask = np.ones(count, dtype="u1")
            mask[-2] = 0
            values[-2] = np.nan
            curve.create_dataset("frequency_hz", data=axis)
            curve.create_dataset("values_ri", data=values, dtype="<f8")
            curve.create_dataset("valid", data=mask)


def rpc(service, document, method, data, *, mutate=False):
    """! @brief 실제 Studio와 같은 공개 RPC 및 요청 키를 사용한다."""
    identity = document["project_id"]
    params = (request(service, identity, data) if mutate else
              {"contract_version": "rfad.api/2.0", "context": {"project_id": identity}, "input": data})
    reply = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}), service)
    if "error" in reply:
        raise AssertionError(reply)
    return reply["result"]


@unittest.skipUnless(find_spec("h5py"), "고정 HDF5 환경을 설치해야 합니다.")
class LargeResultTests(unittest.TestCase):
    """! @brief 독립 외부 결과의 등록과 부분 검증을 실제 저널에 연결한다."""

    def test_registration_field_and_curves_survive_reopen_and_detect_block_tampering(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            source = root / "한글 필드.h5"
            traces = root / "곡선.h5"
            make_field(source)
            make_curves(traces, count=512)
            with ProjectService(workspace, auto_run=False) as service:
                document, _ = register_fixture(service)
                project = service.journal.read()["projects"][document["project_id"]]
                inbox = workspace / project["path"] / "result-inbox"
                inbox.mkdir()
                for file, kind in ((source, "field"), (traces, "traces")):
                    token = str(uuid4())
                    shutil.copyfile(file, inbox / (token + ".h5"))
                    task = rpc(service, document, "result.large.register", {
                        "revision_id": document["revision_id"], "kind": kind, "token": token,
                        "name": file.stem, "source_name": file.name}, mutate=True)
                    service.run_next()
                    self.assertEqual(service.journal.read()["jobs"][task["job_id"]]["state"], "completed")
                self.assertFalse(list(inbox.iterdir()))
                self.assertEqual(service.repository.load(project), document)
            with ProjectService(workspace, auto_run=False) as service:
                records = rpc(service, document, "result.large.list", {})["records"]
                field = next(row for row in records if row["kind"] == "field")
                curve = next(row for row in records if row["kind"] == "traces")
                self.assertEqual(field["source_name"], source.name)
                self.assertEqual(field["artifact"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertIsNone(field["conditions"]["measurement"])
                query = {"id": field["id"], "selection": {"monitor_id": "external", "component": "x",
                    "frequency_index": 1, "plane": {"normal_axis": "z", "index": 8},
                    "roi": {"u_start": 7, "u_count": 2, "v_start": 8, "v_count": 2}, "stride": 1}}
                page = rpc(service, document, "result.large.slice", query)
                self.assertEqual(page["values_ri"], [[[7, 3], [8, 3]], [[7, 3], [8, 3]]])
                self.assertEqual(page["u_coordinates_mm"], [7.0, 8.0])
                raw = rpc(service, document, "result.large.curves", {"id": curve["id"], "mode": "exact",
                                                                       "offset": 510, "metric": "imag"})
                self.assertEqual(raw["counts"], [512]*8)
                self.assertEqual(raw["pages"][7]["samples"][-1]["imag"], -8)
                self.assertIsNone(raw["pages"][7]["samples"][0]["real"])
                h5py, _ = hdf._runtime()
                path = workspace / field["artifact"]["uri"]
                with h5py.File(path, "r+") as file:
                    file["FieldData/FD/f1"][0, 7, 8, 8] = 234 + 1j
                with self.assertRaisesRegex(AssertionError, "E_HASH"):
                    rpc(service, document, "result.large.slice", query)

    @unittest.skipUnless(sys.platform == "win32" and GUI and os.environ.get("RFAD_TEST_F3_PRODUCT"),
                         "1 GiB 원문과 실제 Windows Studio 계측을 명시적으로 활성화해야 합니다.")
    def test_windows_registered_field_and_eight_curves_save_reopen_and_memory(self):
        from f3_windows_memory import observe

        with TemporaryDirectory(prefix="TraceWave F3 대용량 결과 ") as directory:
            root = Path(directory)
            workspace = root / "작업 영역"
            field, traces = root / "두 주파수 필드.h5", root / "여덟 복소 곡선.h5"
            make_field(field, large=True)
            make_curves(traces)
            with ProjectService(workspace, auto_run=False) as service:
                document, _ = register_fixture(service)
                project = service.journal.read()["projects"][document["project_id"]]
            results = {}
            for mode in ("import", "reopen"):
                phases, evidence = root / f"{mode}-phase.txt", root / f"{mode}-view.json"
                smoke = root / f"{mode}-studio.json"
                (workspace / "large-results-fixture.json").write_bytes(canonical_bytes({
                    "mode": mode, "field": str(field), "traces": str(traces), "phases": str(phases),
                    "evidence": str(evidence)}))
                command = [GUI, "--python", sys.executable, "--source", str(CODE / "src"),
                           "--workspace", str(workspace), "--open-project", project["path"],
                           "--large-results-smoke-test", "--smoke-report", str(smoke)]
                with (root / f"{mode}-stderr.txt").open("w+b") as errors:
                    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=errors, stderr=errors) as process:
                        samples = observe(process, phases, 205)
                        code = process.wait()
                    errors.seek(0)
                    log = errors.read()
                report = json.loads(smoke.read_bytes()) if smoke.exists() else {}
                view = json.loads(evidence.read_bytes()) if evidence.exists() else {}
                self.assertEqual(code, 0, (report, view, log[-2000:]))
                self.assertTrue(view["passed"] and report["passed"])
                self.assertEqual(report["saved_revision"], document["revision_id"])
                self.assertEqual(len(view["slices"]), 10)
                self.assertEqual(view["overview_counts"], [100000]*8)
                ready = [row for row in samples if row["phase"] == "ready" and len(row["processes"]) >= 2]
                self.assertGreaterEqual(len(ready), 5)
                pids = {row["pid"] for row in ready[-1]["processes"]}
                active = [row for row in samples if row["phase"] in ("field-start", "curves-start", "import-start")
                          and {proc["pid"] for proc in row["processes"]} == pids]
                self.assertTrue(active)
                total = lambda row: sum(proc["private_commit_bytes"] for proc in row["processes"])
                baseline, peak = total(ready[-1]), max(total(row) for row in active)
                self.assertLessEqual(peak-baseline, 512*1024**2)
                results[mode] = {"studio": report, "view": view, "samples": samples,
                                 "baseline_bytes": baseline, "peak_bytes": peak}
            self.assertEqual(results["import"]["view"]["records"], results["reopen"]["view"]["records"])
            self.assertEqual(results["import"]["view"]["slices"], results["reopen"]["view"]["slices"])
            self.assertEqual(results["import"]["view"]["tail"], results["reopen"]["view"]["tail"])
            with ProjectService(workspace, auto_run=False) as service:
                self.assertEqual(service.repository.load(service.journal.read()["projects"][document["project_id"]]), document)
                for row in rpc(service, document, "result.large.list", {})["records"]:
                    original = field if row["kind"] == "field" else traces
                    with original.open("rb") as stream:
                        self.assertEqual(row["artifact"]["sha256"], hashlib.file_digest(stream, "sha256").hexdigest())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                (Path(output) / "large-result-f3.json").write_bytes(canonical_bytes(results))
