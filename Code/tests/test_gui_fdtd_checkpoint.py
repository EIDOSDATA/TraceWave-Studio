"""! @brief Windows 준비 화면에서 봉인한 IFA 입력을 별도 엔진으로 재개하고 직접 계산과 대조한다."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest

from rfad.application import solver_checkpoint_source
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request
from test_gui_solver_process import GUI, HAS_RUNTIME, ROOT
from test_pcb_ifa import IFA_SETTINGS, ifa_document


class CheckpointScopeTests(unittest.TestCase):
    """! @brief 보존할 수 있는 엔진 상태와 추가 출력을 요청한 프로필의 경계를 확인한다."""

    def test_recording_and_thread_scope(self):
        """! @brief 원래의 급전 수, 계산 예산 및 기록 종류를 바꾸지 않고 판정한다."""
        case = {"port": {"id": "one"}, "num_threads": 1, "settings": {}}
        plan = {"analysis_profile": solver_checkpoint_source.PROFILE, "case": case}
        self.assertEqual(solver_checkpoint_source.eligibility(plan), "")
        for change in ({"num_threads": 2}, {"ports": [1, 2]}, {"radiation_recording": {}}, {"field_recording": {}},
                       {"settings": {"power_balance": {}}}):
            with self.subTest(change=change):
                self.assertTrue(solver_checkpoint_source.eligibility({**plan, "case": {**case, **change}}))


@unittest.skipUnless(sys.platform == "win32" and GUI and HAS_RUNTIME
                     and os.environ.get("RFAD_CHECKPOINT_GUI") == "1", "Windows GUI와 WSL2 openEMS 및 DMTCP 4.2.0이 필요합니다.")
class GuiFDTDCheckpointTests(unittest.TestCase):
    """! @brief 실제 Studio의 준비, 시작, 상태, 정지, 재개와 독립 파형을 검증한다."""

    def test_prepared_ifa_controls_and_waveforms(self):
        """! @brief 원래 설계 결과를 게시하지 않는 별도 작업의 전압/전류를 연속 실행과 대조한다."""
        with TemporaryDirectory(prefix="TraceWave 체크포인트 ") as temporary:
            folder = Path(temporary)
            workspace = folder / "workspace"
            with ProjectService(workspace, auto_run=False) as service:
                document, _ = register_fixture(service, ifa_document())
            settings = {**IFA_SETTINGS, "max_timesteps": 4000, "end_criterion": 1e-9,
                        "compute_profile": {"kind": "tuning_refinement/0.1", "num_threads": 1}}
            config = folder / "checkpoint-ui-smoke.json"
            config.write_text(json.dumps(settings), encoding="utf-8")
            report = folder / "report.json"
            completed = subprocess.run([GUI, "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--openems-wsl", "--solver-smoke-test", "--solver-settings", str(config), "--smoke-report", str(report)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=630)
            self.assertTrue(report.exists(), (completed.returncode, completed.stderr))
            result = json.loads(report.read_bytes())
            self.assertTrue(result["passed"], result.get("error"))
            self.assertEqual(completed.returncode, 0)
            self.assertIn("solver.review.request", result["solver_checks"])
            self.assertIn("solver.review.checkpoint", result["solver_checks"])
            with ProjectService(workspace, auto_run=False) as service:
                ctx = {"project_id": document["project_id"]}
                req = {"contract_version": "rfad.api/2.0", "context": ctx, "input": {}}
                ids = solver_checkpoint_source.read(service, req)["plans"]
                self.assertEqual(len(ids), 1)
                data = solver_checkpoint_source.read(service, {**req, "input": {"prepared_plan_id": ids[0]}})["sources"][0]
                self.assertFalse(service.journal.read()["solver_results"])
                self.assertEqual(data["reason"], "")
                self.assertEqual(hashlib.sha256((workspace / data["xml"]["uri"]).read_bytes()).hexdigest(), data["xml"]["sha256"])
                self.assertEqual(data["revision_id"], document["revision_id"])
                changed = service.mutate("project.apply_command", request(service, ctx["project_id"], {
                    "expected_revision": document["revision_id"], "command_id": str(uuid4()),
                    "type": "metadata.rename", "payload": {"name": "체크포인트 이후의 IFA"}}))
                self.assertNotEqual(changed["new_revision"], document["revision_id"])
                self.assertEqual(solver_checkpoint_source.read(service, {**req, "input": {"prepared_plan_id": ids[0]}})["sources"][0], data)
                path = workspace / data["xml"]["uri"]
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b" ")
                    with self.assertRaises(ProjectError) as caught:
                        solver_checkpoint_source.read(service, {**req, "input": {"prepared_plan_id": ids[0]}})
                    self.assertIn(caught.exception.code, ("E_HASH", "E_RESOURCE"))
                finally:
                    path.write_bytes(original)
            argv = [sys.executable, "-X", "utf8", "-m", "rfad.cli.pcb_checkpoint"]
            scope = ["--project", ctx["project_id"], "--plan", ids[0], "--sha256", data["xml"]["sha256"], "--engine", data["engine"]]
            def bridge(action, *rest):
                """! @brief 앱과 동일한 고정 Windows-WSL 연결에서 하나의 자체 작업을 다시 조회한다."""
                output = subprocess.run([*argv, action, *scope, *rest], capture_output=True, check=True, timeout=90)
                return json.loads(output.stdout)
            job, = bridge("list", "--xml", str(workspace / data["xml"]["uri"]))["jobs"]
            status = bridge("status", "--job", job["job"])
            self.assertEqual(status["status"], "completed")
            self.assertGreater(status["samples"]["port_ut_1"], 2)
            from rfad.cli.pcb_checkpoint import mounted
            script = ROOT / "tests" / "test_gui_fdtd_checkpoint.py"
            independent = subprocess.run(["wsl.exe", "--distribution", "TraceWave-Dev", "--user", "tracewave",
                "--exec", "/usr/bin/python3", "-I", "-c", BASELINE, mounted(script),
                mounted(workspace / data["xml"]["uri"]), status["directory"]], capture_output=True, timeout=440)
            self.assertEqual(independent.returncode, 0, independent.stderr.decode("utf-8", "replace"))
            self.assertEqual(json.loads(independent.stdout), status["samples"])


BASELINE = """
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parents[1] / 'tools'))
from pcb_checkpoint_store import ARGS, ENGINE, TRACES
def samples(path):
    return [line for line in path.read_bytes().splitlines() if line and not line.startswith(b'%')]
with tempfile.TemporaryDirectory() as temporary:
    baseline = pathlib.Path(temporary)
    (baseline / 'pcb.xml').write_bytes(pathlib.Path(sys.argv[2]).read_bytes())
    with (baseline / 'native.log').open('wb') as log:
        subprocess.run([str(ENGINE), *ARGS], cwd=baseline, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=400)
    counts = {}
    for name in TRACES:
        direct = samples(baseline / name)
        assert direct == samples(pathlib.Path(sys.argv[3]) / 'run' / name), name
        counts[name] = len(direct)
    print(json.dumps(counts))
"""
