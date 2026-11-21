"""! @brief 실제 Windows 출력 화면과 별도 형식 worker의 생성/재검수/재열기를 연결한다."""
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
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.exchange_service import read
from rfad.application.projects import ProjectService
import test_exchange_service as fixtures
from test_native_process import assert_native_cancel_trace

ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")
EXCHANGE = os.environ.get("RFAD_EXCHANGE_PYTHON", "")


def fixture(workspace, cancel_operation="export.verify"):
    """! @brief 물리 합격을 만들지 않고 실제 형상과 미정 재료의 고정 입력만 저장한다."""
    f = fixtures.ExchangeFixture(ExchangeRuntime(Path(EXCHANGE)))
    try:
        excluded = deepcopy(f.document["geometry"][0])
        excluded.update(id=str(uuid4()), name="출력 제외 검토 도형", include_in_export=False, include_in_em=False)
        f.command("geometry.set", {"geometry": excluded})
        f.document = f.service._load(f.service.journal.read()["projects"][f.project])
        f.snapshot = f.complete("snapshot.create", {"expected_revision": f.revision, "description": "이름 있는 제외 도형 검토"})
        f.complete("project.save", {"expected_revision": f.revision})
        document = deepcopy(f.document)
        request = f.data("pdf")
        preview = f.complete("export.preview", request)
        context = f.read("export.context", {"snapshot": request["snapshot"]})
        state = f.service.journal.read()
        data = {"project_id": f.project, "revision_id": f.revision, "snapshot": f.snapshot,
                "context": context, "preview": preview, "input": request, "omitted_name": excluded["name"],
                "cancel_operation": cancel_operation,
                "fixture_scope": "actual drawing geometry; no FDTD or manufacturing validation"}
        original = {path.relative_to(f.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in f.workspace.rglob("*") if path.is_file() and path.name != ".writer.lock"
                    and path.relative_to(f.workspace).parts[0] == "projects"}
        f.service.close()
        shutil.copytree(f.workspace, workspace)
        (workspace / "output-smoke-fixture.json").write_bytes(canonical_bytes(data))
        return document, state, original, data
    finally:
        f.close()


@unittest.skipUnless(sys.platform == "win32" and GUI and EXCHANGE,
                     "RFAD_GUI_EXE와 RFAD_EXCHANGE_PYTHON으로 Windows 화면/실제 출력 환경을 지정합니다.")
class GuiOutputTests(unittest.TestCase):
    """! @brief 검토 hash 무효화와 실제 파일 생성 및 명시 재검수를 분리해 검사한다."""

    def test_native_snapshot_review_build_verify_save_restart_preserves_sources(self):
        """! @brief 원래 도면과 재검수 결과를 보존한 채 새 재검수의 실행을 취소한다."""
        self.check_native_cancellation("export.verify", "output.json")

    def test_native_pdf_generation_cancel_preserves_published_sources(self):
        """! @brief 실제 PDF 생성 worker를 취소하고 이미 게시된 파일과 원문을 다시 연다."""
        self.check_native_cancellation("export.build", "output-build.json")

    def check_native_cancellation(self, operation, filename):
        """! @brief native 회수와 runtime 없는 재열기를 같은 원본으로 대조한다."""
        with TemporaryDirectory(prefix="TraceWave 출력 화면 ") as directory:
            workspace = Path(directory) / "작업 영역"
            document, before, files, inputs = fixture(workspace, operation)
            report_path = Path(directory) / "출력 화면 시험.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable,
                "--source", str(ROOT / "src"), "--workspace", str(workspace),
                "--exchange-python", str(Path(EXCHANGE).resolve()), "--open-project", "projects/원본 도면",
                "--output-smoke-test", "--smoke-report", str(report_path)], stdin=subprocess.DEVNULL,
                capture_output=True, startupinfo=startup, timeout=240, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                target = Path(output) / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2)
            self.assertEqual(set(report["setup_checks"]), {
                "output_late_context_disconnect_destroy_safe", "output_uncertain_stable_receipt_no_duplicate",
                "output_snapshot_explicit_native", "output_actual_paper_and_bounded_pages",
                "output_options_invalidate_review", "output_review_confirmation_cancel_and_accept",
                "output_actual_build_generated_not_manufacturing", "output_fresh_verify_keeps_original",
                "output_history_clears_current_paper", "output_running_cancel_reaps_worker_and_keeps_record",
                "output_saved_restart_exact_record"})
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                project = document["project_id"]
                self.assertEqual(service._load(state["projects"][project]), document)
                self.assertEqual(state["projects"][project], before["projects"][project])
                self.assertEqual(state["solver_results"], before["solver_results"])
                jobs = [job for job in state["jobs"].values() if "exchange" in job]
                self.assertEqual(len(jobs), 3)
                trace = report["native_cancel_trace"]
                cancelled = state["jobs"][trace["job_id"]]
                assert_native_cancel_trace(self, workspace, trace, cancelled, "exchange", operation)
                completed = [job for job in jobs if job["state"] == "completed"]
                self.assertEqual(len(completed), 2)
                build = next(job for job in completed if job["operation_method"] == "export.build")
                verify = next(job for job in completed if job["operation_method"] == "export.verify")
                self.assertEqual(verify["exchange"]["original_job_id"], build["job_id"])
                if operation == "export.verify":
                    self.assertEqual(cancelled["exchange"]["original_job_id"], build["job_id"])
                else:
                    self.assertEqual(cancelled["snapshot"], build["snapshot"])
                    self.assertIsNone(cancelled["exchange"]["original_job_id"])
                for job in completed:
                    value = read(service, "export.get", {"contract_version": "rfad.api/2.0",
                        "context": {"project_id": project}, "input": {"job_id": job["job_id"]}})
                    self.assertFalse(value["result"]["manufacturing_verified"])
                    self.assertFalse(value["result"]["physics_verified"])
                    self.assertEqual([item["label"] for item in value["omissions"]], [inputs["omitted_name"]])
                    for ref in value["result"]["artifacts"]:
                        self.assertEqual(hashlib.sha256((workspace / ref["uri"]).read_bytes()).hexdigest(), ref["sha256"])
                    if job is build:
                        source = next(ref for ref in value["result"]["artifacts"] if ref["uri"].endswith("/sidecar.json"))
                        self.assertEqual(json.loads(service.journal.read_artifact(source))["source_semantics"], document)
                for uri, digest in files.items():
                    self.assertEqual(hashlib.sha256((workspace / uri).read_bytes()).hexdigest(), digest, uri)


if __name__ == "__main__":
    unittest.main()
