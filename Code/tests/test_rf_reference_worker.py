"""! @brief 고정 RF worker의 닫힌 분기와 원시 봉인 경계를 native 실행 없이 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rfad.adapters.solvers.openems import native, reference_benchmark
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.rf_reference_contract import CASE, build_plan, raw_names
from rfad.domain.errors import ProjectError
from rfad.domain.project import new_project
from test_cad_projection import snapshot_for
from test_solver_plan import runtime_fixture


ROOT = Path(__file__).resolve().parents[1]


class ReferenceWorkerTests(unittest.TestCase):
    """! @brief 모의 phase는 호출 수명만 검사하며 FDTD 계산 근거로 사용하지 않는다."""

    def plan(self):
        """! @brief 입력 전체를 검증할 수 있는 빈 합성 참조 계획을 만든다."""
        document = new_project("고정 다이폴 worker 경계")
        return build_plan(document, snapshot_for(document), runtime_fixture(), {"case": CASE, "grid_mm": 3.0})

    def test_closed_prepare_dispatch_does_not_call_solve(self):
        """! @brief 새 profile은 전용 준비 분기로 가며 analysis를 몰래 실행하지 않는다."""
        plan = self.plan()
        request = {"schema": "rfad.openems-worker/0.1", "phase": "prepare", "run_id": "run", "nonce": "nonce",
                   "analysis_plan": plan, "runtime": plan["runtime_identity"], "input_files": []}
        with tempfile.TemporaryDirectory() as directory, patch.object(native, "verify_runtime", return_value={}), \
                patch.object(reference_benchmark, "prepare", return_value=({"mock_phase_only": True}, [])) as prepare, \
                patch.object(reference_benchmark, "solve") as solve:
            result = native.execute(request, Path(directory))
            self.assertEqual(result["phase"], "prepare")
            self.assertEqual(result["preparation"], {"mock_phase_only": True})
            prepare.assert_called_once()
            solve.assert_not_called()

    def test_unknown_or_modified_fixture_fails_before_native_runtime_loading(self):
        """! @brief 임의 사례/치수는 runtime 확인과 solver 호출 전에 거절한다."""
        for mutation in ("profile", "height", "sheet"):
            plan = self.plan()
            if mutation == "profile":
                plan["analysis_profile"] = "rfad.unknown/0.1"
            elif mutation == "height":
                plan["case"]["port"]["stop_mm"][2] = 0.7
            else:
                plan["case"]["reference_case"] = "planar-sheet-canonical"
            request = {"schema": "rfad.openems-worker/0.1", "phase": "prepare", "analysis_plan": plan}
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, \
                    patch.object(native, "verify_runtime") as runtime, patch.object(reference_benchmark, "solve") as solve:
                with self.assertRaises(ProjectError):
                    native.execute(request, Path(directory))
                runtime.assert_not_called()
                solve.assert_not_called()

    def raw_fixture(self, stage):
        """! @brief 파일 봉인 시험 바이트이며 실제 포트/HDF 값을 가장하지 않는다."""
        plan = self.plan()
        request = {"analysis_plan": plan, "prepared_plan": {"fixture_only": "prepared"}}
        inputs, records = {}, []
        (stage / "input").mkdir()
        (stage / "output").mkdir()
        for name in raw_names(plan):
            path = stage / "input" / name
            path.write_bytes(("not_native_test_bytes:" + name).encode())
            role = "raw/" + name
            inputs[role] = path
            records.append({"path": "output/" + role, "role": role, "media_type": "application/octet-stream",
                            **native.file_identity(path)})
        manifest = {"schema": "rfad.openems-raw/0.1", "complete": True,
                    "analysis_plan_hash": canonical_hash(plan), "prepared_plan_hash": canonical_hash(request["prepared_plan"]),
                    "files": records}
        path = stage / "input/manifest.json"
        inputs["raw_manifest"] = path
        return request, inputs, manifest

    def test_restore_preserves_exact_raw_and_manifest_bytes(self):
        """! @brief 등록 원시 사본과 원 manifest의 의미를 유지하고 새 실행을 하지 않는다."""
        with tempfile.TemporaryDirectory() as directory, patch.object(reference_benchmark.subprocess, "Popen") as popen:
            stage = Path(directory)
            request, inputs, manifest = self.raw_fixture(stage)
            inputs["raw_manifest"].write_bytes(canonical_bytes(manifest))
            restored, files = reference_benchmark._restore_raw(stage, request, inputs)
            self.assertEqual(restored, manifest)
            self.assertEqual((stage / "output/raw_manifest.json").read_bytes(), canonical_bytes(manifest))
            for name in raw_names(request["analysis_plan"]):
                self.assertEqual((stage / "output/raw" / name).read_bytes(), inputs["raw/" + name].read_bytes())
            self.assertEqual(len(files), len(raw_names(request["analysis_plan"])) + 1)
            popen.assert_not_called()

    def test_raw_foreign_plan_missing_duplicate_path_and_corruption_are_rejected(self):
        """! @brief 후처리 원문의 소유/목록/바이트 경계 오류에서 계산을 시작하지 않는다."""
        for mode in ("plan", "missing", "duplicate", "role", "path", "bytes"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, \
                    patch.object(reference_benchmark.subprocess, "Popen") as popen:
                stage = Path(directory)
                request, inputs, manifest = self.raw_fixture(stage)
                if mode == "plan":
                    manifest["analysis_plan_hash"] = "a" * 64
                elif mode == "missing":
                    manifest["files"].pop()
                elif mode == "duplicate":
                    manifest["files"][-1] = deepcopy(manifest["files"][0])
                elif mode == "role":
                    manifest["files"][-1]["role"] = "raw/foreign.h5"
                elif mode == "path":
                    manifest["files"][0]["path"] = "output/../foreign"
                else:
                    inputs[manifest["files"][0]["role"]].write_bytes(b"changed")
                inputs["raw_manifest"].write_bytes(canonical_bytes(manifest))
                with self.assertRaises(ProjectError):
                    reference_benchmark._restore_raw(stage, request, inputs)
                self.assertFalse((stage / "output/raw_manifest.json").exists())
                popen.assert_not_called()

    def test_old_direct_worker_is_explicitly_retired(self):
        """! @brief 과거 entry로 현재 봉인/공유 slot을 우회할 수 없다."""
        result = subprocess.run([sys.executable, "-I", str(ROOT / "tools/nf2ff_dipole_worker.py")],
                                input=b"{}\n", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 19)
        self.assertIn(b"verify_nf2ff_reference.py", result.stderr)
