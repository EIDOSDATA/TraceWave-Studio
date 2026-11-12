"""! @brief 봉인된 CAD 소스와 실제 격리 프로세스가 실행하는 바이트의 일치를 검증한다."""

import hashlib
import json
import os
from pathlib import Path
import py_compile
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rfad.application.cad_jobs import CadRuntime, CODE_ROOT
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.resource_limits import MAX_WORKER_SOURCE_FILES
from test_cad_jobs import _FAKE_WORKER
from test_cad_worker_process import cad_request, register_fixture, status


_SOURCE_PROBE = '''
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))
from rfad import worker_probe
records = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
           for path in sorted((root / "src/rfad").rglob("*.py"))}
Path("source-probe.json").write_text(json.dumps({
    "entry": str(Path(__file__).resolve()), "entry_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "module": str(Path(worker_probe.__file__).resolve()), "value": worker_probe.VALUE,
    "source_sha256": hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    "dont_write_bytecode": sys.dont_write_bytecode, "pyc_files": [str(path) for path in root.rglob("*.pyc")],
}), encoding="utf-8")
'''


class CadSourceCaptureTests(unittest.TestCase):
    """! @brief 원본 bytecode의 존재와 artifact 손상에 독립적인 worker 실행을 확인한다."""

    def test_modular_source_bundle_keeps_count_and_byte_budgets(self):
        """! @brief 128개보다 많은 모듈도 봉인하되 파일 수/전체 바이트 한도는 별도 검사한다."""
        with TemporaryDirectory(prefix="rfad source budget ") as directory:
            root = Path(directory)
            with patch("rfad.application.cad_runtime.CODE_ROOT", root):
                self.make_runtime(root, False)
                package = root / "src/rfad"
                for index in range(MAX_WORKER_SOURCE_FILES - 2):
                    (package / f"module_{index}.py").write_text("VALUE = 1\n", encoding="utf-8")
                def capture():
                    """! @brief 같은 호스트 설정에서 새 소스 묶음을 확인한다."""
                    return CadRuntime(Path(sys.executable), manifest=CODE_ROOT / "runtime_profiles/python-cad-windows-x64.json",
                                      entry=root / "original worker.py")
                accepted = capture()
                self.assertEqual(len(json.loads(accepted.source_bytes)), MAX_WORKER_SOURCE_FILES)
                accepted.verify(accepted.identity)
                extra = package / "extra.py"
                extra.write_text("VALUE = 2\n", encoding="utf-8")
                with self.assertRaises(ProjectError) as count_error:
                    capture()
                self.assertEqual(count_error.exception.code, "E_RESOURCE")
                extra.unlink()
                (package / "module_0.py").write_text("#" * (2 * 1024 * 1024), encoding="utf-8")
                with self.assertRaises(ProjectError) as bytes_error:
                    capture()
                self.assertEqual(bytes_error.exception.code, "E_RESOURCE")

    def make_runtime(self, root: Path, with_cache: bool) -> CadRuntime:
        """! @brief 원본 소스와 크기/mtime이 일치하는 다른 bytecode를 임시 경로에 준비한다."""
        package = root / "src/rfad"
        package.mkdir(parents=True)
        (package / "__init__.py").write_bytes(b"")
        source = package / "worker_probe.py"
        captured = b"VALUE = 'captured source'\n"
        source.write_bytes(captured)
        if with_cache:
            original_stat = source.stat()
            poison = b"VALUE = 'cached attacker'\n"
            self.assertEqual(len(captured), len(poison))
            source.write_bytes(poison)
            os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            py_compile.compile(str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            source.write_bytes(captured)
            os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        entry = root / "original worker.py"
        worker = _FAKE_WORKER.replace("__MODE__", repr("success"))
        worker = worker.replace("request = json.loads(sys.stdin.buffer.readline())\n",
                                "request = json.loads(sys.stdin.buffer.readline())\n" + _SOURCE_PROBE)
        entry.write_text(worker, encoding="utf-8", newline="")
        return CadRuntime(Path(sys.executable), manifest=CODE_ROOT / "runtime_profiles/python-cad-windows-x64.json",
                          entry=entry, timeout_seconds=10.0)

    def test_sealed_sources_run_in_fresh_stage_even_with_stale_original_bytecode(self):
        """! @brief 실제 자식은 봉인된 entry/source를 실행하고 기존 pyc를 읽거나 새 pyc를 쓰지 않는다."""
        for with_cache in (False, True):
            with self.subTest(with_cache=with_cache), TemporaryDirectory(prefix="rfad 소스 봉인 ") as directory:
                root = Path(directory)
                original = root / "원본 코드"
                with patch("rfad.application.cad_runtime.CODE_ROOT", original):
                    runtime = self.make_runtime(original, with_cache)
                    original_caches = {path: path.read_bytes() for path in original.rglob("*.pyc")}
                    self.assertEqual(bool(original_caches), with_cache)
                    with ProjectService(root / "작업 공간", cad_runtime=runtime, auto_run=False) as service:
                        document, snapshot = register_fixture(service)
                        task = service.mutate("export.build", cad_request(service, document, snapshot))
                        job = service.journal.read()["jobs"][task["job_id"]]
                        source_bytes = service.journal.read_artifact(job["cad"]["source"])
                        entry_bytes = service.journal.read_artifact(job["cad"]["entry"])
                        self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), job["cad"]["source"]["sha256"])
                        self.assertEqual(hashlib.sha256(entry_bytes).hexdigest(), job["cad"]["runtime"]["entry_sha256"])
                        self.assertTrue(service.cad.run_next())
                        completed = status(service, task["job_id"])
                        self.assertEqual(completed["state"], "completed", completed)
                        stage = service.workspace / "cad-staging" / job["run_id"]
                        probe = json.loads((stage / "source-probe.json").read_text(encoding="utf-8"))
                        self.assertEqual(Path(probe["entry"]), stage / "worker.py")
                        self.assertEqual(Path(probe["module"]), stage / "src/rfad/worker_probe.py")
                        self.assertEqual(probe["value"], "captured source")
                        self.assertEqual(probe["entry_sha256"], job["cad"]["runtime"]["entry_sha256"])
                        self.assertEqual(probe["source_sha256"], job["cad"]["runtime"]["source_sha256"])
                        self.assertTrue(probe["dont_write_bytecode"])
                        self.assertEqual(probe["pyc_files"], [])
                        self.assertEqual(list(stage.rglob("__pycache__")), [])
                        self.assertEqual((stage / "worker.py").read_bytes(), entry_bytes)
                        source_files = json.loads(source_bytes)
                        actual_files = {path.relative_to(stage).as_posix(): path.read_bytes().decode("utf-8")
                                        for path in (stage / "src/rfad").rglob("*.py")}
                        self.assertEqual(canonical_bytes(actual_files), canonical_bytes(source_files))
                    self.assertEqual({path: path.read_bytes() for path in original.rglob("*.pyc")}, original_caches)

    def test_tampered_source_artifact_fails_before_native_process_starts(self):
        """! @brief 봉인 source artifact의 byte 변경을 검출하면 native를 시작하거나 결과를 게시하지 않는다."""
        with TemporaryDirectory(prefix="rfad 소스 손상 ") as directory:
            root = Path(directory)
            original = root / "원본 코드"
            with patch("rfad.application.cad_runtime.CODE_ROOT", original):
                runtime = self.make_runtime(original, True)
                with ProjectService(root / "작업 공간", cad_runtime=runtime, auto_run=False) as service:
                    document, snapshot = register_fixture(service)
                    task = service.mutate("export.build", cad_request(service, document, snapshot))
                    job = service.journal.read()["jobs"][task["job_id"]]
                    source = service.workspace / job["cad"]["source"]["uri"]
                    source.write_bytes(source.read_bytes() + b" ")
                    with patch("rfad.application.cad_jobs.run_native") as native:
                        self.assertTrue(service.cad.run_next())
                    native.assert_not_called()
                    failed = status(service, task["job_id"])
                    self.assertEqual(failed["state"], "failed", failed)
                    self.assertEqual(failed["events"][-1]["error"]["code"], "E_HASH")
                    self.assertEqual(failed["artifacts"], [])
                    self.assertFalse(service.journal.read()["jobs"][task["job_id"]]["cad"]["resource_reserved"])
                    stage = service.workspace / "cad-staging" / job["run_id"]
                    self.assertFalse((stage / "started.json").exists())
                    self.assertFalse((stage / "source-probe.json").exists())


if __name__ == "__main__":
    unittest.main()
