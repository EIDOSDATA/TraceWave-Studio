"""! @brief 제어 로딩 pin과 닫힌 실제 계산 worker의 원문/합집합/수명 경계를 검증한다."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import host_calculation_runtime as runtime
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.host_calculation import execute
from test_network_domain import network, component, circuit, target, CONTEXT

ROOT = Path(__file__).resolve().parents[1]


class HostCalculationBoundaryTests(unittest.TestCase):
    """! @brief 계산을 가장하지 않는 source/프로토콜 경계와 단일 writer 구조를 검사한다."""

    def test_gui_module_entry_uses_the_verified_source_loader(self):
        """! @brief Windows GUI와 같은 python -m 진입점에서 실제 프로젝트 API를 조회한다."""
        message = {"jsonrpc": "2.0", "id": 1, "method": "capabilities.get",
                   "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
        with TemporaryDirectory(prefix="TraceWave module entry ") as directory:
            process = subprocess.run([sys.executable, "-X", "utf8", "-m", "rfad", "serve", "--workspace", directory],
                input=canonical_bytes(message) + b"\n", capture_output=True, timeout=45, cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        response = json.loads(process.stdout)["result"]
        self.assertEqual(response["measurement_profile"]["profile"], "rfad.measurement-workspace/0.1")
        self.assertEqual(response["methods"]["measurement.apply"]["status"], "implemented")

    def test_closure_contains_concrete_control_and_math_without_facade(self):
        manifest, control, math, raw = runtime.capture()
        paths = {row["path"] for row in manifest["code_files"]}
        self.assertTrue({"src/rfad/application/host_calculation_context.py", "src/rfad/application/project_history.py",
            "src/rfad/application/project_repository.py", "src/rfad/application/project_operations.py",
            "src/rfad/application/request_ledger.py", "src/rfad/storage/journal.py",
            "src/rfad/application/solver_jobs.py", "src/rfad/application/project_studies.py",
            "src/rfad/domain/network_circuit.py", "src/rfad/domain/network_assessment.py",
            "tools/host_calculation_worker.py", "tools/wsl_supervisor.py"} <= paths)
        self.assertNotIn("src/rfad/application/projects.py", paths)
        self.assertNotIn("src/rfad/application/rpc.py", paths)
        self.assertEqual(len(paths), len(set(control["sources"]) | set(math["sources"])))
        self.assertLessEqual(len(paths), 192)
        self.assertLessEqual(len(raw), 4 * 1024**2)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest["bundle_sha256"])

    def test_union_limit_counts_shared_paths_once_and_rejects_193(self):
        """! @brief 합성 source 집합으로 두 profile의 상한 우회를 직접 검사한다."""
        control = {f"src/rfad/a{index}.py": "value = 1\n" for index in range(171)}
        math = {f"src/rfad/a{index}.py": "value = 1\n" for index in range(150, 192)}
        def bundle(root, profile):
            return {"sources": control if profile == runtime.HOST_CONTROL else math, "source_bundle": {}, "code_files": []}
        with patch.object(runtime, "build", side_effect=bundle):
            self.assertEqual(len(runtime.capture()[0]["code_files"]), 192)
            math["src/rfad/a192.py"] = "value = 1\n"
            with self.assertRaises(ProjectError) as error:
                runtime.capture()
            self.assertEqual(error.exception.code, "E_RESOURCE")
            math.pop("src/rfad/a192.py")
            math["src/rfad/a150.py"] = "value = 2\n"
            with self.assertRaises(ProjectError) as error:
                runtime.capture()
            self.assertEqual(error.exception.code, "E_HASH")
            math.clear()
            control.clear()
            control["src/rfad/a.py"] = "#" * (4 * 1024**2)
            with self.assertRaises(ProjectError) as error:
                runtime.capture()
            self.assertEqual(error.exception.code, "E_RESOURCE")

    def test_closed_entry_rejects_callable_path_or_unlisted_operation(self):
        for operation, data in (("os.system", {}), ("network.circuit", {"dataset": {}, "circuit": {}, "path": "x"}),
                                ("result.compare", {"left": {}, "right": {}, "parameters": {}, "module": "arbitrary"})):
            with self.subTest(operation=operation), self.assertRaises(ProjectError):
                execute(operation, data)

    def test_context_is_concrete_single_writer_and_source_preview_is_read_only(self):
        with TemporaryDirectory() as temporary, ProjectService(Path(temporary), auto_run=False) as service:
            context = service.host_calculation_context
            self.assertIs(service.journal, context.journal)
            self.assertIs(service.requests, context.requests)
            self.assertIs(service.solver.service, context)
            self.assertIs(service.studies.service, context)
            self.assertNotIn(service, vars(context).values())
            before = {str(path.relative_to(temporary)): path.read_bytes() for path in Path(temporary).rglob("*") if path.is_file() and path.name != ".writer.lock"}
            reference, raw = context.calculation_source({"path": "projects/explicit"})
            self.assertEqual(reference["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(len(json.loads(raw)), len(context.calculation_identity()["application_source"]["code_files"]))
            self.assertEqual(before, {str(path.relative_to(temporary)): path.read_bytes() for path in Path(temporary).rglob("*") if path.is_file() and path.name != ".writer.lock"})

    def test_unavailable_calculation_source_keeps_project_save_and_reopen(self):
        with TemporaryDirectory() as temporary:
            with patch.object(runtime, "capture", side_effect=ProjectError("E_VERSION", "합성 source 비가용 시험")):
                with ProjectService(Path(temporary), auto_run=False) as service:
                    def request(data, context):
                        return {"contract_version": "rfad.api/2.0", "context": context, "input": data,
                            "request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"]}
                    task = service.mutate("project.open", request({"path": "projects/readable", "name": "원문 조회", "open_mode": "create"}, {}))
                    service.run_next()
                    opened = service.journal.read()["jobs"][task["job_id"]]["events"][-1]["operation_result"]
                    identity = opened["project_id"]
                    original = service._load(service.journal.read()["projects"][identity])
                    task = service.mutate("project.save", request({"expected_revision": original["revision_id"]}, {"project_id": identity}))
                    service.run_next()
                    self.assertEqual(service.journal.read()["jobs"][task["job_id"]]["state"], "completed")
                    with self.assertRaises(ProjectError):
                        service.host_calculation_context.calculation_identity()
                with ProjectService(Path(temporary), auto_run=False) as service:
                    self.assertEqual(service._load(service.journal.read()["projects"][identity]), original)

    def _copied_process(self, body):
        """! @brief 변경 시험은 제품 원문 대신 별도 source 복사본에서만 실행한다."""
        with TemporaryDirectory(prefix="TraceWave host source probe ") as temporary:
            copied = Path(temporary)
            for base in ("src/rfad", "tools"):
                for source in (ROOT / base).rglob("*.py"):
                    if ".local" in source.parts or "__pycache__" in source.parts:
                        continue
                    target = copied / source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            script = "import sys\nfrom pathlib import Path\nroot=Path(sys.argv[1])\nsys.path.insert(0,str(root/'src'))\n" + body
            completed = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", script, str(copied)], capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            return completed.stdout

    def test_changed_control_source_cannot_be_repinned_in_loaded_session(self):
        result = self._copied_process(r"""
from rfad.application.host_calculation_runtime import HostCalculationRuntime
from rfad.domain.errors import ProjectError
r=HostCalculationRuntime()
before=r.establish()
p=root/'src/rfad/application/project_history.py'
p.write_bytes(p.read_bytes()+b'\n# source change probe\n')
try:
    r.verify()
except ProjectError as error:
    assert error.code=='E_VERSION'
else:
    raise AssertionError('changed control source accepted')
assert r.identity==before
print('pinned-source-rejected')
""")
        self.assertIn("pinned-source-rejected", result)

    def test_already_loaded_source_change_and_stale_pyc_are_detected(self):
        result = self._copied_process(r"""
import os,py_compile
from rfad.application import project_history
from rfad.application.host_calculation_runtime import HostCalculationRuntime
from rfad.domain.errors import ProjectError
p=root/'src/rfad/probe_value.py'
p.write_text('value=1\n',encoding='utf-8')
stamp=p.stat().st_mtime_ns
py_compile.compile(str(p),doraise=True)
p.write_text('value=2\n',encoding='utf-8')
os.utime(p,ns=(stamp,stamp))
from rfad import probe_value
assert probe_value.value==2
p=root/'src/rfad/application/project_history.py'
p.write_bytes(p.read_bytes()+b'\n# before first source pin\n')
try:
    HostCalculationRuntime().establish()
except ProjectError as error:
    assert error.code=='E_VERSION'
else:
    raise AssertionError('already loaded stale control accepted')
print('loaded-code-and-bytecode-checked')
""")
        self.assertIn("loaded-code-and-bytecode-checked", result)

    def test_worker_malformed_or_wrong_owner_result_never_returns_a_value(self):
        engine = runtime.HostCalculationRuntime()
        for fault in ("missing", "json", "nonce", "fields"):
            def broken(*args, **kwargs):
                """! @brief native 계산을 가장하지 않는 응답 파일/소유권 장애 주입이다."""
                output = kwargs["output_directory"]
                output.mkdir()
                request = json.loads(kwargs["request_bytes"])
                if fault == "json":
                    (output / "result.json").write_bytes(b"{")
                elif fault != "missing":
                    result = {key: request[key] for key in ("run_id", "nonce", "input_sha256", "identity_hash")}
                    result.update(schema="rfad.host-worker-result/0.1", operation="network.circuit", value={})
                    if fault == "nonce":
                        result["nonce"] = str(uuid4())
                    else:
                        result["command"] = "forged publication"
                    (output / "result.json").write_bytes(canonical_bytes(result))
                return {"termination": "completed", "returncode": 0}
            with self.subTest(fault=fault), patch.object(runtime, "run_native", side_effect=broken):
                with self.assertRaises(ProjectError) as error:
                    engine.execute("network.circuit", {"dataset": {}, "circuit": {}})
                self.assertEqual(error.exception.code, "E_HASH")


class HostCalculationWorkerTests(unittest.TestCase):
    """! @brief 고정 실제 패키지와 봉인 worker를 사용하며 실물 RF 합격을 주장하지 않는다."""
    def test_actual_rlc_transform_and_deterministic_receipt_preserve_inputs(self):
        engine = runtime.HostCalculationRuntime()
        data = network(values=(0.1 + 0j,))
        original = deepcopy(data)
        inputs = {"dataset": data, "circuit": circuit(component())}
        result, receipt = engine.execute("network.circuit", inputs)
        self.assertAlmostEqual(result["dataset"]["values_ri"][0][0][0][0], 11 / 29)
        repeated, repeated_receipt = engine.execute("network.circuit", inputs)
        self.assertEqual((result, receipt), (repeated, repeated_receipt))
        result, receipt = engine.execute("network.transform", {"dataset": data, "options": {"operation": "convert", "parameter_kind": "Z"}})
        self.assertAlmostEqual(result["dataset"]["values_ri"][0][0][0][0], 550 / 9)
        self.assertEqual(data, original)
        self.assertEqual(receipt["identity_hash"], canonical_hash(engine.identity))

    def test_actual_alignment_and_comparison_keep_unknown_conditions_and_lineage(self):
        """! @brief 합성 RI 독립값으로 worker 계보/조건/실측 미확립을 확인한다."""
        engine = runtime.HostCalculationRuntime()
        data = network(values=(0.1 + 0.2j, 0.3 - 0.2j), frequencies=[1e9, 3e9])
        original = deepcopy(data)
        spec = {"schema": "rfad.measurement-alignment/0.1", "operations": [
            {"kind": "linear_ri", "frequency_hz": [1e9, 2e9, 3e9], "max_gap_hz": 2e9}],
            "reason": "합성 입력의 봉인 계산 경계 시험", "source_refs": ["fixture:host-worker"]}
        result, receipt = engine.execute("measurement.align", {"dataset": data, "specification": spec})
        self.assertAlmostEqual(result["dataset"]["values_ri"][1][0][0][0], 0.2)
        self.assertEqual(result["dataset"]["values_ri"][1][0][0][1], 0.0)
        self.assertEqual(result["lineage"][0]["samples"], [[0, 0, 0.0], [0, 1, 0.5], [1, 1, 0.0]])
        self.assertEqual(result["dataset"]["sample_origin"], ["computed", "interpolated", "computed"])
        self.assertEqual(result["dataset"]["conditions"], data["conditions"])
        self.assertEqual(result["engine"]["identity_hash"], receipt["identity_hash"])
        parameters = {"row": 0, "column": 0, "offset": 0, "limit": 201,
                      "frequency_policy": "exact_only", "right_port_order": [0]}
        compared, _ = engine.execute("result.compare", {"left": result["dataset"], "right": data, "parameters": parameters})
        self.assertEqual(compared["points"][0]["difference_ri"], [0.0, 0.0])
        self.assertEqual(compared["points"][1]["reasons"], ["frequency_missing"])
        self.assertIsNone(compared["points"][1]["difference_ri"])
        self.assertFalse(compared["physics_validated"])
        self.assertEqual(compared["physical_comparability"]["status"], "not_established")
        self.assertEqual(data, original)

    def test_actual_target_and_retained_sweep_assessment_use_same_worker(self):
        """! @brief 원래 목표를 보존하며 보존/캐시 자료도 동일 목표 계산을 통과한다."""
        engine = runtime.HostCalculationRuntime()
        data = network(values=(0.1 + 0j, 0.2 + 0j, 0.1 + 0j))
        goal = target()
        document = {"revision_id": str(uuid4()), "parameters": {}, "targets": [goal]}
        original = deepcopy(document)
        assessed, receipt = engine.execute("network.evaluate", {"document": document, "target": goal,
            "dataset": data, "context": CONTEXT, "metrics": None})
        spec = {"target_ids": [goal["id"]], "target_contexts": [{"target_id": goal["id"], "context": CONTEXT}]}
        retained, _ = engine.execute("sweep.assess", {"document": document, "specification": spec, "dataset": data, "metrics": None})
        repeated = deepcopy(retained["assessments"][0])
        evidence = repeated.pop("evidence")
        self.assertEqual(repeated, assessed)
        self.assertEqual(evidence["target_original"], goal)
        self.assertFalse(retained["continuous_band_verified"])
        self.assertFalse(retained["physics_validated"])
        self.assertEqual(document, original)
        self.assertEqual(receipt["identity_hash"], canonical_hash(engine.identity))

    def test_changed_staged_math_bytes_are_refused_before_calculation(self):
        """! @brief 별도 staging의 실제 원문 변조를 설치 패키지 fallback으로 숨기지 않는다."""
        engine = runtime.HostCalculationRuntime()
        native = runtime.run_native
        def tampered(*args, **kwargs):
            path = kwargs["cwd"] / "src/rfad/domain/network_circuit.py"
            path.write_bytes(path.read_bytes() + b"\n# synthetic staged tamper\n")
            return native(*args, **kwargs)
        with patch.object(runtime, "run_native", side_effect=tampered):
            with self.assertRaises(ProjectError) as raised:
                engine.execute("network.circuit", {"dataset": network(), "circuit": circuit()})
        self.assertEqual(raised.exception.code, "E_RESOURCE")
        self.assertEqual(raised.exception.details["termination"], "completed")
        self.assertIn("source", raised.exception.details["stderr"])


class HostSourceCopyTests(unittest.TestCase):
    """! @brief 원래 dataset bytes와 별도 계산 source closure가 사본/재복사를 통과한다."""
    def setUp(self):
        from test_sweep_selection import SelectionFixture
        from test_network_service import import_parameters
        from rfad.application import network_service
        self.fixture = SelectionFixture()
        self.addCleanup(self.fixture.close)
        f = self.fixture
        data = {"expected_revision": f.document["revision_id"], "operation": "import", "parameters": import_parameters()}
        preview = network_service.read(f.service.host_calculation_context, "network.preview", f.request(data))
        self.assertTrue(preview["can_apply"], preview)
        request = f.request({**data, "review_hash": preview["review_hash"], "command_id": str(uuid4())}, True)
        f.service.mutate("network.apply", request)
        f.seal()

    def test_registered_source_copy_mapping_survives_undo_and_recopy_without_original_file(self):
        from rfad.application.sweep_copy import prepare_artifacts
        f = self.fixture
        before = f.service.journal.read()
        original = f.service._load(before["projects"][f.project])
        entry = original["extensions"]["rfad.network-library"]["datasets"][0]
        raw = f.service.journal.read_artifact(entry["dataset"])
        source = json.loads(raw)["provenance"]["host_source"]
        source_bytes = f.service.journal.read_artifact(source)
        response, request = f.apply(path="projects/source-copy")
        state = f.service.journal.read()
        child_id = response["new_project_id"]
        child = state["projects"][child_id]
        copied = f.service._load(child)
        copied_entry = copied["extensions"]["rfad.network-library"]["datasets"][0]
        self.assertEqual(f.service.journal.read_artifact(copied_entry["dataset"]), raw)
        copies = state["commands"][request["input"]["command_id"]]["source_artifact_copies"]
        mapped = next(item["copy"] for item in copies if item["original_uri"] == source["uri"])
        self.assertEqual(f.service.journal.read_artifact(mapped), source_bytes)
        self.assertEqual(state["projects"][f.project], before["projects"][f.project])
        self.assertEqual(f.service.journal.read_artifact(source), source_bytes)
        for operation in ("undo", "redo"):
            document = f.service._load(f.service.journal.read()["projects"][child_id])
            f.service.mutate("project." + operation, f.request({"expected_revision": document["revision_id"],
                "command_id": str(uuid4())}, True, child_id))
        #! 별도 시험 workspace에서만 원래 파일을 제거해 사본의 등록 mapping 사용을 검증한다.
        (f.workspace / source["uri"]).unlink()
        child = f.service.journal.read()["projects"][child_id]
        _, blobs, references = prepare_artifacts(f.service, child, f.service._load(child), "projects/second-source-copy")
        second = next(item["copy"] for item in references if item["original_uri"] == source["uri"])
        self.assertEqual(blobs[second["uri"]], source_bytes)
        self.assertEqual(blobs[next(item["copy"]["uri"] for item in references if item["original_uri"] == copied_entry["dataset"]["uri"])], raw)

    def test_unregistered_or_wrong_owner_source_does_not_follow_arbitrary_artifact(self):
        from rfad.application.sweep_copy import prepare_artifacts, _registered_host_source
        f = self.fixture
        state = f.service.journal.read()
        project = state["projects"][f.project]
        document = f.service._load(project)
        entry = document["extensions"]["rfad.network-library"]["datasets"][0]
        source = json.loads(f.service.journal.read_artifact(entry["dataset"]))["provenance"]["host_source"]
        with self.assertRaises(ProjectError) as raised:
            _registered_host_source(f.service, {**project, "path": "projects/other"}, f.project, source)
        self.assertEqual(raised.exception.code, "E_HASH")
        def remove_registration(current):
            for command in current["commands"].values():
                command.pop("host_calculation", None)
        f.service.journal.transaction(remove_registration)
        before = f.service.journal.read()
        with self.assertRaises(ProjectError) as raised:
            prepare_artifacts(f.service, project, document, "projects/not-published")
        self.assertEqual(raised.exception.code, "E_HASH")
        self.assertEqual(f.service.journal.read(), before)
        self.assertFalse((f.workspace / "projects/not-published").exists())


if __name__ == "__main__":
    unittest.main()
