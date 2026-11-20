"""! @brief 격리한 대형 설계와 대기 프로젝트를 실제 Windows Studio에서 반복 전환한다."""

import argparse
import json
from pathlib import Path
from statistics import median
import subprocess
import sys


MIB = 1024**2


def summarize(report):
    """! @brief 동일 GUI와 자식 프로세스의 관찰값을 초기 5회와 마지막 10회로 대조한다."""
    record = report["project_switch"]
    count = len(record["cycles"])
    if report["passed"] is not True or report["service_sessions"] != 1 or count != 30:
        raise ValueError("같은 서비스의 완료된 30회 전환 기록이 필요합니다.")
    pids = {row["pid"] for row in record["baseline"]}
    observed = {"opened": [], "settled_after_switch": []}
    handles = {pid: [] for pid in pids}
    for index, sample in enumerate(record["cycles"], 1):
        if sample["cycle"] != index:
            raise ValueError("반복 전환 회차가 연속하지 않습니다.")
        for phase, values in observed.items():
            rows = sample[phase]
            if len(rows) != len(pids) or {row["pid"] for row in rows} != pids:
                raise ValueError("계측 중 GUI 또는 하위 프로세스 집합이 바뀌었습니다.")
            values.append(sum(row["private_commit_bytes"] for row in rows))
        for row in sample["settled_after_switch"]:
            handles[row["pid"]].append(row["handles"])
    settled = observed["settled_after_switch"]
    first, last = median(settled[:5]), median(settled[-10:])
    return {
        "cycles": count,
        "baseline_private_mib": sum(row["private_commit_bytes"] for row in record["baseline"]) / MIB,
        "opened_peak_private_mib": max(observed["opened"]) / MIB,
        "settled_peak_private_mib": max(settled) / MIB,
        "initial_5_median_private_mib": first / MIB,
        "final_10_median_private_mib": last / MIB,
        "settled_delta_private_mib": (last - first) / MIB,
        "settled_delta_budget_mib": max(32, first / MIB * 0.05),
        "settled_handles": {str(pid): {"first": series[0], "last": series[-1],
                                      "minimum": min(series), "maximum": max(series)}
                            for pid, series in sorted(handles.items())},
    }


def run(executable, location, cycles):
    """! @brief 사용자 저장소와 분리된 새 시험 디렉터리에 두 원본을 등록한다."""
    code = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(code / "src"), str(code / "tests")]
    from rfad.application.projects import ProjectService
    from test_cad_worker_process import register_fixture, request, status
    from test_f1_project import f1_project

    location.mkdir(parents=True, exist_ok=False)
    workspace = location / "프로젝트"
    standby = "projects/F5 대기 프로젝트"
    with ProjectService(workspace, auto_run=False) as service:
        creation = request(service, None, {"open_mode": "create", "name": "F5 대기 프로젝트", "path": standby})
        creation["context"] = {}
        task = service.mutate("project.open", creation)
        service.run_next()
        result = status(service, task["job_id"])
        if result["state"] != "completed":
            raise RuntimeError(result)
        document, _ = register_fixture(service, f1_project())
        large = service.journal.read()["projects"][document["project_id"]]["path"]
    fixture = {"standby_path": standby, "large_path": large, "cycles": cycles}
    (workspace / "project-switch-smoke-fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    report = location / "studio.json"
    command = [str(executable), "--python", sys.executable, "--source", str(code / "src"),
               "--workspace", str(workspace), "--open-project", standby,
               "--project-switch-smoke-test", "--smoke-report", str(report)]
    with (location / "studio-stderr.txt").open("wb") as errors:
        process = subprocess.run(command, stdin=subprocess.DEVNULL, stderr=errors, check=False,
                                 timeout=175 + cycles * 100)
    if process.returncode != 0:
        raise RuntimeError(f"Windows 전환 시험이 실패했습니다. 실행 기록: {location}")
    result = json.loads(report.read_bytes())
    if result["passed"] is not True or len(result["project_switch"]["cycles"]) != cycles:
        raise RuntimeError(f"Windows 전환 표본이 부족합니다. 실행 기록: {report}")
    return result


def main():
    """! @brief 새 표본을 기록하거나 보존한 30회 원시 기록을 읽는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    collect = commands.add_parser("run")
    collect.add_argument("executable", type=Path)
    collect.add_argument("directory", type=Path)
    collect.add_argument("--cycles", type=int, choices=range(1, 31), default=30)
    read = commands.add_parser("summarize")
    read.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.action == "run":
        result = run(args.executable.resolve(strict=True), args.directory.resolve(), args.cycles)
        output = summarize(result) if args.cycles == 30 else {"cycles": args.cycles, "passed": True}
    else:
        output = summarize(json.loads(args.report.read_bytes()))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
