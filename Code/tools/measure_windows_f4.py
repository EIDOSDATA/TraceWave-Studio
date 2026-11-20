"""! @brief 격리한 소스로 실제 WSL openEMS와 합성 로그의 Windows 취소를 관찰한다."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile


def patch(path, before, after):
    """! @brief 검증한 시험용 사본 한 곳만 변경한다."""
    text = path.read_text(encoding="utf-8")
    assert text.count(before) == 1, path
    path.write_text(text.replace(before, after), encoding="utf-8")


def prepare(source, case, revision):
    """! @brief 추적한 Code 사본에만 계측기와 로그 부하를 연결한다."""
    commit = subprocess.check_output(["git", "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"],
                                     cwd=source.parent, text=True).strip()
    packed = subprocess.check_output(["git", "archive", "--format=zip", commit, "Code"], cwd=source.parent)
    case.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(packed)) as archive:
        archive.extractall(case)
    code = case / "Code"
    audit = code / ".local/wsl/native-audit.json"
    audit.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(source / ".local/wsl/native-audit.json", audit)
    module = code / "src/rfad/adapters/solvers/openems/native.py"
    patch(module, "            write_json(stage / 'progress.json', {'phase': 'running'})",
          "            if not pcb_profile:\n                write_json(stage / 'progress.json', {'phase': 'running'})")
    pcb = code / "src/rfad/adapters/solvers/openems/pcb.py"
    patch(pcb, "import math\n", "import math\nimport os\nimport threading\n")
    patch(pcb, "        try:\n            while child.poll() is None:",
          """        def emit():
            started = time.monotonic()
            row = b"F4 supervised output sample\\n"
            for index in range(1, 8001):
                if child.poll() is not None:
                    return
                os.write(1, row * 10)
                delay = started + index / 100 - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                if index == 200 and child.poll() is None:
                    ready = {"f4_probe": True, "lines": index * 10, "row_bytes": len(row),
                             "elapsed_seconds": time.monotonic() - started,
                             "native_pid": child.pid, "native_mapped": any(
                                 "libopenEMS" in path.name for path in _mapped_files(child.pid))}
                    if ready["native_mapped"]:
                        os.write(2, json.dumps(ready).encode() + b"\\n")
                        write_json(stage / "progress.json", {"phase": "running"})

        threading.Thread(target=emit, name="rfad-f4-diagnostic", daemon=True).start()
        try:
            while child.poll() is None:""")
    jobs = code / "src/rfad/application/solver_jobs.py"
    patch(jobs, 'worker_attached = value.get("state") == "active" and type(pid) is int and pid > 0',
          'worker_attached = (value.get("state") == "active" and type(pid) is int and pid > 0\n'
          '                           and (job["kind"] != "em_analysis" or phase == "running"))')
    rpc = code / "src/rfad/application/rpc.py"
    patch(rpc, "import platform\n", "import platform\nimport time\n")
    patch(rpc, "        response = handle_frame(frame, service, catalog)",
          """        received_ns = time.perf_counter_ns()
        response = handle_frame(frame, service, catalog)""")
    patch(rpc, "                sink.flush()\n",
          """                sink.flush()
                sent_ns = time.perf_counter_ns()
                if b'"job.cancel"' in frame and service is not None:
                    request = json.loads(frame)
                    if request["method"] == "job.cancel":
                        measured = {"job_id": request["params"]["input"]["job_id"],
                                    "received_ns": received_ns, "sent_ns": sent_ns,
                                    "elapsed_ms": (sent_ns - received_ns) / 1e6}
                        with (service.journal.root / "f4-rpc-timing.jsonl").open("a", encoding="utf-8") as timing:
                            timing.write(json.dumps(measured) + "\\n")
""")
    (case / "source-commit.txt").write_text(commit + "\n", encoding="ascii")


def run(root, executable, index):
    """! @brief 실제 GUI 실행과 guest 종료의 독립 증거를 같은 작업 ID로 대조한다."""
    package = root / "Code"
    source_commit = (root / "source-commit.txt").read_text(encoding="ascii").strip()
    sys.path[:0] = [str(package / "src"), str(package / "tests")]
    from rfad.application.projects import ProjectService
    from rfad.application.wsl_process import WslRuntime
    from test_cad_worker_process import register_fixture
    from test_pcb_solver import fixture_document, SETTINGS

    assert Path(sys.modules["rfad"].__file__).is_relative_to(package / "src")
    location = root / ("sample-" + str(index))
    location.mkdir()
    workspace = location / "프로젝트"
    with ProjectService(workspace, auto_run=False) as service:
        register_fixture(service, fixture_document(circle=True, arc=True))
    settings = location / "settings.json"
    settings.write_text(json.dumps({**SETTINGS, "air_padding_mm": 12.0, "max_timesteps": 55000,
                                    "end_criterion": 1e-9}), encoding="utf-8")
    report = location / "studio.json"
    started = time.monotonic()
    process = subprocess.run([str(executable), "--python", sys.executable, "--source", str(package / "src"),
        "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
        "--openems-wsl", "--solver-active-cancel-smoke-test", "--solver-settings", str(settings),
        "--smoke-report", str(report)], stdin=subprocess.DEVNULL, capture_output=True, timeout=630, check=False)
    elapsed = time.monotonic() - started
    (location / "studio-stderr.txt").write_bytes(process.stderr)
    result = json.loads(report.read_bytes()) if report.is_file() else {}
    assert process.returncode == 0 and result.get("passed") is True, (process.returncode, result.get("error"), elapsed)
    trace = result["solver_cancel_trace"]
    assert trace["guest_worker_attached"] and trace["terminal"]["termination_confirmed"]
    assert trace["terminal"]["state"] == "cancelled" and result["service_sessions"] == 2
    assert result["saved_revision"] == result["revision_id"] and "restart_restores_result" in result["solver_checks"]
    with ProjectService(workspace, auto_run=False) as service:
        state = service.journal.read()
        job = state["jobs"][trace["job_id"]]
        assert job["state"] == "cancelled" and job["kind"] == "em_analysis"
        assert list(state["solver_results"]) == [result["solver_result"]["artifact_id"]]
        assert [event["seq"] for event in job["events"]] == list(range(1, trace["terminal"]["events_cursor"] + 1))
    guest = WslRuntime().inspect(job["run_id"], job["solver"]["nonce"])
    assert guest["state"] == "cancelled" and guest["termination_confirmed"] and not guest["outcome_unknown"]
    assert guest["native"]["output_limit_reason"] == ""
    ready = next(row for line in guest["native"]["stderr_tail"].splitlines() if line.startswith('{"f4_probe":')
                 for row in [json.loads(line)])
    assert ready["native_mapped"] and ready["lines"] == 2000
    assert 950 <= ready["lines"] / ready["elapsed_seconds"] <= 1050
    count, remainder = divmod(guest["native"]["stdout_bytes"], ready["row_bytes"])
    assert remainder == 0 and count > ready["lines"]
    timing, = [row for line in (workspace / "f4-rpc-timing.jsonl").read_text(encoding="utf-8").splitlines()
               for row in [json.loads(line)] if row["job_id"] == job["job_id"]]
    assert 0 < timing["elapsed_ms"] <= trace["receipt"]["elapsed_ms"]
    data = {"index": index, "source_commit": source_commit, "wall_seconds": elapsed,
            "studio_trace": trace, "rpc_timing": timing,
            "native_activity": {**ready, "stdout_lines_before_termination": count, "guest_cursor": guest["cursor"]},
            "previous_result_preserved": True, "saved_revision": result["saved_revision"],
            "canonical_module_sha256": hashlib.sha256((package / "src/rfad/application/canonical.py").read_bytes()).hexdigest(),
            "journal_module_sha256": hashlib.sha256((package / "src/rfad/storage/journal.py").read_bytes()).hexdigest(),
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
    (location / "evidence.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("root", type=Path)
    ap.add_argument("executable", type=Path)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--revision", default="HEAD")
    ap.add_argument("--index", type=int, default=1)
    args = ap.parse_args()
    if sys.platform != "win32":
        ap.error("Windows Studio와 WSL2 해석 작업이 필요합니다.")
    if args.prepare:
        prepare(args.source.resolve(), args.root.resolve(), args.revision)
    else:
        run(args.root.resolve(), args.executable.resolve(), args.index)
