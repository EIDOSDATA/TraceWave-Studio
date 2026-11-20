"""! @brief 격리한 대형 설계와 대기 프로젝트를 실제 Windows Studio에서 반복 전환한다."""

import argparse
import json
from pathlib import Path
import shutil
from statistics import median
import subprocess
import sys
from uuid import uuid4


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
    summary = {
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
    if "baseline_gpu" in record:
        summary["policy"] = record["policy"]
        summary["settle_seconds"] = record["settle_seconds"]
        summary["gpu"] = _gpu_summary(record["cycles"], record["policy"])
    return summary


def _gpu_summary(cycles, policy):
    """! @brief 실제 GPU 표본과 context 상태를 전환 정책별로 보존한다."""
    result = {"all_contexts_match_policy": all(row["context_retained"] == (policy == "warm") for row in cycles)}
    for phase in ("opened_gpu", "settled_gpu"):
        by_adapter = {}
        for row in cycles:
            for entry in row[phase]:
                if entry["local_bytes"] is not None and entry["nonlocal_bytes"] is not None:
                    by_adapter.setdefault(entry["ordinal"], []).append((entry["local_bytes"], entry["nonlocal_bytes"]))
        result[phase] = [{"ordinal": device, "samples": len(values),
                          "peak_local_bytes": max(value[0] for value in values),
                          "peak_nonlocal_bytes": max(value[1] for value in values)}
                         for device, values in sorted(by_adapter.items())]
    return result


def _combined_fixture(service, document, workspace, location, project):
    """! @brief 실제 등록과 표시 로더에 합성 3D·필드·복소 원문을 제공한다."""
    from create_large_display_fixture import write_fixture
    from test_large_results import make_field, make_curves, rpc

    write_fixture(workspace / "combined-display")
    inbox = workspace / project / "result-inbox"
    inbox.mkdir()
    for kind in ("field", "traces"):
        file = location / f"{kind}.h5"
        if kind == "field":
            make_field(file, large=True)
        else:
            make_curves(file)
        token = str(uuid4())
        shutil.move(file, inbox / (token + ".h5"))
        task = rpc(service, document, "result.large.register", {
            "token": token, "kind": kind, "name": kind, "source_name": file.name,
            "revision_id": document["revision_id"]}, mutate=True)
        service.run_next()
        job = service.journal.read()["jobs"][task["job_id"]]
        if job["state"] != "completed":
            raise RuntimeError(job["events"][-1])


def run(executable, location, cycles, *, combined=False, idle=False, profile_3d=False, quality_3d=False, diagnostic=""):
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
        if combined:
            _combined_fixture(service, document, workspace, location, large)
    fixture = {"standby_path": standby, "large_path": large, "cycles": cycles, "combined": combined, "idle": idle,
               "profile_3d": profile_3d, "quality_3d": quality_3d, "diagnostic": diagnostic}
    (workspace / "project-switch-smoke-fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    report = location / "studio.json"
    command = [str(executable), "--python", sys.executable, "--source", str(code / "src"),
               "--workspace", str(workspace), "--open-project", standby,
               "--project-switch-smoke-test", "--smoke-report", str(report)]
    with (location / "studio-stderr.txt").open("wb") as errors:
        process = subprocess.run(command, stdin=subprocess.DEVNULL, stderr=errors, check=False,
                                 timeout=175 + cycles * (250 if idle else 130))
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
    collect.add_argument("--combined", action="store_true")
    collect.add_argument("--idle", action="store_true")
    collect.add_argument("--profile-3d", action="store_true",
                         help="전체 도킹 상태에서 35초 합성과 저해상도 표시를 검증합니다.")
    collect.add_argument("--quality-3d", action="store_true",
                         help="다른 창의 합성 조건과 분리해 저해상도 표시와 원본 복귀를 검증합니다.")
    collect.add_argument("--diagnostic", choices=("display", "results"),
                         help="원인 진단만 수행합니다. 3D 또는 결과를 하나만 열고 1초 후 계측합니다.")
    read = commands.add_parser("summarize")
    read.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.action == "run":
        if (args.profile_3d or args.quality_3d) and (not args.combined or args.cycles != 1):
            parser.error("3D 계측은 --combined --cycles 1을 사용하십시오.")
        if args.diagnostic and (args.idle or args.profile_3d or args.quality_3d or not args.combined or args.cycles == 30):
            parser.error("원인 진단은 --combined 및 30회 미만에서 다른 계측과 분리하십시오.")
        result = run(args.executable.resolve(strict=True), args.directory.resolve(), args.cycles,
                     combined=args.combined, idle=args.idle, profile_3d=args.profile_3d, quality_3d=args.quality_3d,
                     diagnostic=args.diagnostic or "")
        output = summarize(result) if args.cycles == 30 else {"cycles": args.cycles, "passed": True}
        if args.profile_3d:
            from summarize_windows_canvas_display import summarize as display_summary

            output["display"] = display_summary(result["project_switch"]["display_trace"])
        if args.profile_3d or args.quality_3d:
            output["quality"] = result["project_switch"]["display_quality"]
    else:
        output = summarize(json.loads(args.report.read_bytes()))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
