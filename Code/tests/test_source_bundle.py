"""! @brief 실행 소스 closure와 별도 프로세스의 봉인 import 경계를 독립 검증한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rfad.application import source_bundle as bundle


class SourceBundleTests(unittest.TestCase):
    """! @brief runtime이나 native 모듈 없이 실제 파일/자식 프로세스 경계를 확인한다."""

    def setUp(self):
        """! @brief 모든 소스와 stage를 시험 소유 임시 폴더 안에 둔다."""
        self.temporary = TemporaryDirectory(prefix="rfad source closure ")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.write("src/rfad/__init__.py", b"")

    def tearDown(self):
        """! @brief 종료된 시험의 임시 산출물만 회수한다."""
        self.temporary.cleanup()

    def write(self, name, raw):
        """! @brief 저장 바이트를 임의 줄바꿈 변환 없이 보존한다."""
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def capture(self, entry=b"import rfad.probe\n"):
        """! @brief custom CAD 진입점은 명시 host 바이트로 제공한다."""
        return bundle.build(self.source, bundle.CAD, overrides={"worker.py": entry})

    def stage(self, captured):
        """! @brief 수집한 정확한 bytes만 새 격리 폴더에 게시한다."""
        root = self.root / "stage"
        root.mkdir(exist_ok=True)
        for relative, text in captured["sources"].items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return root

    def test_transitive_branches_functions_relative_imports_and_parent_initializers(self):
        """! @brief 실행하지 않은 분기/함수와 부모 초기화 의존도 closure에 남긴다."""
        self.write("src/rfad/__init__.py", b"from . import parent_dependency\n")
        self.write("src/rfad/parent_dependency.py", b"VALUE = 1\n")
        self.write("src/rfad/pkg/__init__.py", b"from . import declared\n")
        self.write("src/rfad/pkg/declared.py", b"VALUE = 3\n")
        self.write("src/rfad/pkg/main.py", b"if False:\n    import rfad.branch\ndef value():\n    from .. import delayed\n    from .declared import VALUE\n    return VALUE\n")
        self.write("src/rfad/branch.py", b"VALUE = 2\n")
        self.write("src/rfad/delayed.py", b"VALUE = 4\n")
        self.write("src/rfad/unused.py", b"import rfad.not_present\n")
        captured = self.capture(b"from rfad.pkg import main\n")
        self.assertEqual(set(captured["sources"]), {
            "worker.py", "src/rfad/__init__.py", "src/rfad/parent_dependency.py",
            "src/rfad/pkg/__init__.py", "src/rfad/pkg/declared.py", "src/rfad/pkg/main.py",
            "src/rfad/branch.py", "src/rfad/delayed.py"})
        stage = self.stage(captured)
        self.assertEqual(bundle.verify_stage(stage, captured["source_bundle"], captured["code_files"]), captured)

    def test_missing_function_dependency_is_not_skipped(self):
        """! @brief 지금 호출하지 않는 함수의 누락 import도 포장 시 거절한다."""
        self.write("src/rfad/probe.py", b"def later():\n    import rfad.not_present\n")
        with self.assertRaises(bundle.BundleError):
            self.capture()

    def test_requested_file_budget_cannot_disable_the_global_cap(self):
        """! @brief bool/0/193 입력으로 전역 192개 상한을 우회하지 않는다."""
        for maximum in (True, 0, 193):
            with self.subTest(maximum=maximum), self.assertRaises(bundle.BundleError):
                bundle.build(self.source, bundle.CAD, overrides={"worker.py": b"pass\n"}, max_files=maximum)
        self.assertEqual(len(bundle.build(self.source, bundle.CAD,
            overrides={"worker.py": b"pass\n"}, max_files=1)["code_files"]), 1)

    def test_missing_from_package_attribute_is_rejected(self):
        """! @brief 없는 package export를 설치 패키지에서 보완하지 않는다."""
        with self.assertRaises(bundle.BundleError):
            self.capture(b"from rfad import missing\n")

    def test_unreferenced_modules_do_not_consume_closure_file_budget(self):
        """! @brief 제품 파일 수 대신 실제 전이 실행 의존에만 worker 한도를 적용한다."""
        self.write("src/rfad/probe.py", b"VALUE = 1\n")
        for index in range(200):
            self.write(f"src/rfad/unused_{index}.py", b"UNUSED = True\n")
        self.assertEqual(len(self.capture()["code_files"]), 3)

    def test_file_count_192_boundary_and_aggregate_bytes(self):
        """! @brief 실제 import chain의 192개 경계와 바이트 경계는 각각 거부한다."""
        for index in range(190):
            raw = f"import rfad.part_{index + 1}\n".encode() if index < 189 else b"VALUE = 1\n"
            self.write(f"src/rfad/part_{index}.py", raw)
        self.assertEqual(len(self.capture(b"import rfad.part_0\n")["code_files"]), 192)
        self.write("src/rfad/part_189.py", b"import rfad.extra\n")
        self.write("src/rfad/extra.py", b"VALUE = 2\n")
        with self.assertRaises(bundle.BundleError) as raised:
            self.capture(b"import rfad.part_0\n")
        self.assertEqual(raised.exception.code, "E_RESOURCE")
        self.write("src/rfad/probe.py", b"#" * (2 * 1024**2))
        with self.assertRaises(bundle.BundleError) as raised:
            self.capture()
        self.assertEqual(raised.exception.code, "E_RESOURCE")

    def test_profile_newline_rules_preserve_cad_bytes_and_normalize_solver(self):
        """! @brief CAD 원문과 solver 기존 text 정규화의 차이를 profile별로 고정한다."""
        self.write("src/rfad/probe.py", b"VALUE = 1\r\n")
        cad = self.capture(b"import rfad.probe\r\n")
        self.assertEqual(cad["sources"]["src/rfad/probe.py"], "VALUE = 1\r\n")
        self.write("tools/openems_worker.py", b"import rfad.probe\r\n")
        self.write("tools/wsl_supervisor.py", b"# supervisor raw\r\n")
        first = bundle.build(self.source, bundle.SOLVER)
        self.write("src/rfad/probe.py", b"VALUE = 1\n")
        self.write("tools/openems_worker.py", b"import rfad.probe\n")
        second = bundle.build(self.source, bundle.SOLVER)
        self.assertEqual(first, second)
        self.assertEqual(first["sources"]["tools/wsl_supervisor.py"], "# supervisor raw\r\n")

    def test_dynamic_import_alias_and_unregistered_loader_are_rejected(self):
        """! @brief importlib 별칭/가변 import/일반 모듈 exec를 명시 등록 없이 허용하지 않는다."""
        for raw in (b"import importlib as loader\nloader.import_module('rfad.hidden')\n",
                    b"from importlib import import_module as load\nload('rfad.hidden')\n",
                    b"__import__('rfad.hidden')\n", b"exec('VALUE = 1')\n"):
            with self.subTest(raw=raw):
                self.write("src/rfad/probe.py", raw)
                with self.assertRaises(bundle.BundleError) as raised:
                    self.capture()
                self.assertEqual(raised.exception.code, "E_UNSUPPORTED")

    def test_extra_stage_source_and_changed_bytes_are_rejected(self):
        """! @brief 봉인 뒤 추가된 파일이나 바뀐 바이트를 실행하지 않는다."""
        self.write("src/rfad/probe.py", b"VALUE = 1\n")
        captured = self.capture()
        stage = self.stage(captured)
        extra = stage / "src/rfad/extra.py"
        extra.write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaises(bundle.BundleError):
            bundle.verify_stage(stage, captured["source_bundle"], captured["code_files"])
        extra.unlink()
        (stage / "src/rfad/probe.py").write_bytes(b"VALUE = 2\n")
        with self.assertRaises(bundle.BundleError):
            bundle.verify_stage(stage, captured["source_bundle"], captured["code_files"])

    def test_hardlinks_and_symbolic_links_do_not_escape_source_capture(self):
        """! @brief root 안의 이름이라도 공유 inode나 외부 링크를 독립 소스로 수용하지 않는다."""
        external = self.root / "external.py"
        external.write_bytes(b"VALUE = 1\n")
        linked = self.source / "src/rfad/probe.py"
        os.link(external, linked)
        with self.assertRaises(bundle.BundleError):
            self.capture()
        linked.unlink()
        try:
            linked.symlink_to(external)
        except OSError:
            return
        with self.assertRaises(bundle.BundleError):
            self.capture()

    def test_manifest_duplicate_missing_entry_and_hash_tampering(self):
        """! @brief 목록만 바꿔 파일 봉인이나 필수 진입점을 우회하지 않는다."""
        self.write("src/rfad/probe.py", b"VALUE = 1\n")
        captured = self.capture()
        for change in ("duplicate", "entry", "hash"):
            with self.subTest(change=change):
                records, descriptor = deepcopy(captured["code_files"]), deepcopy(captured["source_bundle"])
                if change == "duplicate":
                    records.append(deepcopy(records[0]))
                elif change == "entry":
                    records = [record for record in records if record["path"] != "worker.py"]
                    descriptor["source_sha256"] = bundle.source_hash(records)
                else:
                    records[0]["sha256"] = "f" * 64
                with self.assertRaises(bundle.BundleError):
                    bundle.validate_descriptor(descriptor, records)

    def test_manifest_aggregate_bytes_are_rejected_before_stage_reads(self):
        """! @brief 파일별 허용 크기여도 전체 bytes 상한을 넘긴 manifest는 즉시 거절한다."""
        self.write("src/rfad/probe.py", b"VALUE = 1\n")
        captured = self.capture()
        records = deepcopy(captured["code_files"])
        for record in records:
            record["bytes"] = bundle.LIMITS[bundle.CAD]
        descriptor = deepcopy(captured["source_bundle"])
        descriptor["source_sha256"] = bundle.source_hash(records)
        with self.assertRaises(bundle.BundleError) as raised:
            bundle.validate_descriptor(descriptor, records)
        self.assertEqual(raised.exception.code, "E_RESOURCE")

    def test_import_after_stage_growth_does_not_read_unbounded_bytes(self):
        """! @brief stage 검증 뒤 파일이 커져도 import의 재읽기는 원래 크기 상한을 유지한다."""
        self.write("src/rfad/probe.py", b"VALUE = 1\n")
        captured = self.capture()
        stage = self.stage(captured)
        bundle.verify_stage(stage, captured["source_bundle"], captured["code_files"])
        (stage / "src/rfad/probe.py").write_bytes(b"#" * (1024 * 1024))
        guard = bundle._SealedImports(stage, captured["code_files"])
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded source read")):
            with self.assertRaises(bundle.BundleError):
                guard.find_spec("rfad.probe")

    def test_subprocess_rejects_already_loaded_product_even_at_same_stage_path(self):
        """! @brief 같은 경로라도 guard 이전에 실행된 제품 모듈을 검증된 실행으로 간주하지 않는다."""
        self.write("src/rfad/probe.py", b"VALUE = 'unsealed early load'\n")
        captured = self.capture()
        stage = self.stage(captured)
        metadata = self.root / "bundle-preload.json"
        metadata.write_text(json.dumps({key: captured[key] for key in ("source_bundle", "code_files")}), encoding="utf-8")
        program = """
import importlib.util,json,pathlib,sys
spec=importlib.util.spec_from_file_location('sealed_bootstrap',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
root=pathlib.Path(sys.argv[2]);saved=json.loads(pathlib.Path(sys.argv[3]).read_text())
sys.path.insert(0,str(root/'src'))
from rfad import probe
try:
    module.install_guard(root,saved['source_bundle'],saved['code_files'])
except module.BundleError:
    print('blocked')
else:
    print('accepted');sys.exit(1)
"""
        run = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(Path(bundle.__file__).resolve()),
                              str(stage), str(metadata)], capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        self.assertEqual(run.stdout.strip(), b"blocked")

    def test_subprocess_guard_rejects_installed_fallback_and_stale_bytecode(self):
        """! @brief 실제 별도 Python은 봉인 소스만 실행하고 설치된 동명 모듈/pyc를 쓰지 않는다."""
        self.write("src/rfad/probe.py", b"VALUE = 'sealed source'\n")
        captured = self.capture()
        stage = self.stage(captured)
        outside = self.root / "installed/rfad"
        outside.mkdir(parents=True)
        (outside / "__init__.py").write_bytes(b"VALUE = 'installed parent'\n")
        (outside / "probe.py").write_bytes(b"VALUE = 'installed attacker'\n")
        (outside / "unlisted.py").write_bytes(b"VALUE = 'fallback attacker'\n")
        metadata = self.root / "bundle.json"
        metadata.write_text(json.dumps({key: captured[key] for key in ("source_bundle", "code_files")}), encoding="utf-8")
        program = """
import importlib.util,json,pathlib,sys
spec=importlib.util.spec_from_file_location('sealed_bootstrap',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
root=pathlib.Path(sys.argv[2]);saved=json.loads(pathlib.Path(sys.argv[3]).read_text())
module.install_guard(root,saved['source_bundle'],saved['code_files'])
sys.path.insert(0,sys.argv[4])
from rfad import probe
try:
    import rfad.unlisted
except ModuleNotFoundError:
    fallback=False
else:
    fallback=True
print(json.dumps({'value':probe.VALUE,'fallback':fallback,'pyc':list(map(str,root.rglob('*.pyc')))}))
"""
        run = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(Path(bundle.__file__).resolve()),
                              str(stage), str(metadata), str(outside.parent)], capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        self.assertEqual(json.loads(run.stdout), {"value": "sealed source", "fallback": False, "pyc": []})
        stale = stage / "src/rfad/probe.pyc"
        stale.write_bytes(b"invalid old bytecode")
        with self.assertRaises(bundle.BundleError):
            bundle.verify_stage(stage, captured["source_bundle"], captured["code_files"])


if __name__ == "__main__":
    unittest.main()
