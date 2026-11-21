"""! @brief CAD와 PDF의 실제 작업에 고속 로그를 결합한 Windows 취소를 계측한다."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from measure_windows_f4 import archive_source, patch


_ROW = b"TraceWave F4 native workload sample\n"
_WORKLOAD = '''
def exercise_native_backend(operation):
    """! @brief 기존 계산을 반복하는 동안 소유 worker의 로그 pipe에 행을 쓴다."""
    import msvcrt
    import threading
    import time
    from tempfile import TemporaryDirectory

    row = F4_LOG_ROW
    repetitions = 0
    done = threading.Event()

    def emit():
        msvcrt.setmode(2, os.O_BINARY)
        start = time.perf_counter_ns()
        for batch in range(1, 401):
            delay = (start + batch * 20_000_000 - time.perf_counter_ns()) / 1e9
            if done.wait(max(0, delay)):
                return
            if os.write(2, row * 20) != len(row) * 20:
                return
            if batch >= 100 and repetitions > 0 and not Path("f4-ready.json").exists():
                ready = time.perf_counter_ns()
                Path("f4-ready.tmp").write_text(json.dumps({
                    "pid": os.getpid(), "parent_pid": os.getppid(), "lines": batch * 20,
                    "completed_backend_calls": repetitions,
                    "ready_perf_counter_ns": ready, "elapsed_seconds": (ready - start) / 1e9,
                }), encoding="utf-8")
                os.replace("f4-ready.tmp", "f4-ready.json")
        done.set()

    emitter = threading.Thread(target=emit, name="rfad-f4-diagnostic", daemon=True)
    emitter.start()
    try:
        while not done.is_set():
            with TemporaryDirectory(prefix="f4-", dir=Path.cwd()) as directory:
                operation(Path(directory))
                repetitions += 1
    finally:
        done.set()
        emitter.join()
'''.replace("F4_LOG_ROW", repr(_ROW))


def prepare(source, root, revision):
    """! @brief 격리 복제본에서 이전 STEP 또는 PDF가 게시된 뒤 후속 작업에만 부하를 연결한다."""
    commit, code = archive_source(source, root, revision)
    application = code / "src/rfad/application"
    for owner, selection, previous in (
        ("cad", 'job["operation_method"] == "geometry.build"', '"export.build"'),
        ("exchange", 'job["operation_method"] in {"export.build", "export.verify"}', 'job["operation_method"]'),
    ):
        patch(application / f"{owner}_jobs.py", "        def started(metadata):\n",
              f'        if {selection}:\n'
              '            request["f4_probe"] = any(\n'
              f'                {owner!r} in item and item["operation_method"] == {previous} and item["state"] == "completed"\n'
              '                for item in self.service.journal.read()["jobs"].values())\n'
              "        def started(metadata):\n")
    patch(application / "projects.py",
          '        if any(job.get(owner, {}).get("process") for owner in ("cad", "exchange")):',
          '        if any(job.get(owner, {}).get("process") and\n'
          '               (self.journal.root / (owner + "-staging") / job["run_id"] / "f4-ready.json").is_file()\n'
          '               for owner in ("cad", "exchange")):')
    cad = code / "tools/cad_worker.py"
    drawing = code / "tools/exchange_worker.py"
    for worker, signature in ((cad, "def main() -> int:"), (drawing, "def main():")):
        patch(worker, signature, _WORKLOAD + "\n\n" + signature)
    patch(cad, '            result["package"] = build_package(projection, Path.cwd() / "output")',
          '            if request.get("f4_probe"):\n'
          '                exercise_native_backend(lambda directory: build_package(projection, directory))\n'
          '            result["package"] = build_package(projection, Path.cwd() / "output")')
    patch(drawing, "            output.mkdir()\n            result[\"package\"] = generate(value, output, font_path=font_path)",
          '            if request.get("f4_probe"):\n'
          '                exercise_native_backend(lambda directory: generate(value, directory, font_path=font_path))\n'
          '            output.mkdir()\n            result["package"] = generate(value, output, font_path=font_path)')
    patch(drawing, '            result["verification"] = verify(value, root / "original", json.loads(package_raw))',
          '            manifest = json.loads(package_raw)\n'
          '            if request.get("f4_probe"):\n'
          '                exercise_native_backend(lambda _directory: verify(value, root / "original", manifest))\n'
          '            result["verification"] = verify(value, root / "original", manifest)')
    patch(code / "tests/test_native_process.py", '    test.assertEqual(trace["terminal"]["events_cursor"], len(job["events"]))\n',
          '    test.assertEqual(trace["terminal"]["events_cursor"], len(job["events"]))\n'
          '    from os import environ\n'
          '    ready = json.loads((workspace / f"{owner}-staging" / job["run_id"] / "f4-ready.json").read_bytes())\n'
          '    (Path(environ["RFAD_GUI_TEST_ARTIFACT_DIR"]) / "native-evidence.json").write_text(\n'
          '        json.dumps({"ready": ready, "process": process, "requested": requested}), encoding="utf-8")\n')
    for filename, report, indent in (("cad", "report", "        "), ("output", "report_path", "            ")):
        line = f"{indent}self.assertTrue({report}.is_file(), (process.returncode, process.stderr))"
        patch(code / f"tests/test_gui_{filename}_process.py", line,
              f"{indent}if process.returncode:\n"
              f'{indent}    destination = Path(os.environ["RFAD_GUI_TEST_ARTIFACT_DIR"]) / "failure.json"\n'
              f'{indent}    with ProjectService(workspace, auto_run=False) as service:\n'
              f'{indent}        jobs = service.journal.read()["jobs"]\n'
              f'{indent}    stages = {{str(path.relative_to(workspace)): json.loads(path.read_bytes())\n'
              f'{indent}              for parent in ("cad-staging", "exchange-staging")\n'
              f'{indent}              for name in ("f4-ready.json", "result.json", "process.json")\n'
              f'{indent}              for path in (workspace / parent).glob("*/" + name)}}\n'
              f'{indent}    destination.write_text(json.dumps({{"jobs": jobs, "stages": stages}}), encoding="utf-8")\n'
              + line)
    return commit, code


def measure(code, executable, cad, exchange, owner, index):
    """! @brief 실제 GUI 취소, 파이프 배출, 계산 진행과 운영체제 회수를 같은 PID로 묶는다."""
    location = code.parent / f"{owner}-{index}"
    location.mkdir()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(code / "src"), str(code / "tests"))),
           "RFAD_GUI_EXE": str(executable), "RFAD_CAD_PYTHON": str(cad),
           "RFAD_EXCHANGE_PYTHON": str(exchange), "RFAD_GUI_TEST_ARTIFACT_DIR": str(location)}
    test, report = {
        "cad": ("test_gui_cad_process.GuiCadProcessTests.test_step_mesh_edit_save_cancel_and_restart", "cad.json"),
        "pdf": ("test_gui_output_process.GuiOutputTests.test_native_pdf_generation_cancel_preserves_published_sources",
                "output-build.json"),
        "pdf-verify": ("test_gui_output_process.GuiOutputTests.test_native_snapshot_review_build_verify_save_restart_preserves_sources",
                       "output.json"),
    }[owner]
    run = subprocess.run([sys.executable, "-m", "unittest", "-v", test], cwd=code, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=270, check=False)
    (location / "unittest.log").write_bytes(run.stdout)
    if run.returncode:
        raise RuntimeError(f"GUI 시험 실패: {location / 'unittest.log'}")
    gui = json.loads((location / report).read_bytes())
    raw = json.loads((location / "native-evidence.json").read_bytes())
    ready, process = raw["ready"], raw["process"]
    rate = ready["lines"] / ready["elapsed_seconds"]
    count, remainder = divmod(process["stderr_bytes"], len(_ROW))
    if (not gui["passed"] or gui["service_sessions"] < 2 or process["pid"] not in {ready["pid"], ready["parent_pid"]}
            or not 950 <= rate <= 1050 or ready["completed_backend_calls"] < 1
            or remainder or count < ready["lines"] or _ROW.decode() not in process["stderr_tail"]
            or not ready["ready_perf_counter_ns"] <= raw["requested"] <= process["reaped_perf_counter_ns"]):
        raise RuntimeError(f"같은 작업의 로그, 계산 또는 취소 증거가 일치하지 않습니다: {location}")
    return {"owner": owner, "index": index, "trace": gui["native_cancel_trace"], "owned_pid": process["pid"],
            "native_activity": ready, "measured_lines_per_second": rate, "drained_lines": count,
            "previous_result_reopened": True, "saved_revision": gui["revision_id"]}


def main():
    """! @brief 변경된 시험 소스와 동일 Release 실행 파일의 출처를 보존한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "trial_root", "executable", "cad_python", "exchange_python"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--group", choices=("cad", "pdf", "pdf-verify"), action="append")
    args = parser.parse_args()
    executable, cad, exchange = (path.resolve() for path in (args.executable, args.cad_python, args.exchange_python))
    if sys.platform != "win32" or args.runs < 1 or not all(path.is_file() for path in (executable, cad, exchange)):
        parser.error("Windows Studio와 실제 CAD/PDF 런타임 및 양수 반복 횟수가 필요합니다.")
    root = args.trial_root.resolve()
    commit, code = prepare(args.source.resolve(), root, args.revision)
    evidence = {"schema": "rfad.stage12.native-combined-log-cancellation/0.1", "source_commit": commit,
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "measurement_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "target_lines_per_second": 1000, "planned_runs_per_owner": args.runs, "runs": []}
    groups = args.group or ("cad", "pdf", "pdf-verify")
    evidence["groups"] = list(groups)
    for index in range(1, args.runs + 1):
        for owner in groups:
            result = measure(code, executable, cad, exchange, owner, index)
            evidence["runs"].append(result)
            (root / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
