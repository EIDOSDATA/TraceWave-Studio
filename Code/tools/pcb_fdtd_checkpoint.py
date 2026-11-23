"""! @brief WSL2 단일 포트 PCB openEMS를 전용 폴더에서 실행하고 DMTCP 상태를 보존 및 복구한다."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from uuid import UUID, uuid4
from xml.etree.ElementTree import ParseError

from pcb_checkpoint_store import ARGS, DMTCP, ENGINE, JOB_ROOT, TRACES, digest, input_xml, loaded_libraries, locked, private_root, require, runtime, save


def environment(job):
    """! @brief 외부 플러그인 및 실행 명령 상속 없이 제품 런타임 환경을 구성한다."""
    return {"HOME": str(ENGINE.parents[4]), "PATH": "/usr/bin:/bin", "LANG": "C",
            "TMPDIR": str(job / "tmp"), "DMTCP_TMPDIR": str(job / "tmp")}


def launch(job, args):
    """! @brief 독립 프로세스 그룹에 고정 실행 명령을 시작하고 같은 작업 로그에 이어 쓴다."""
    with (job / "run/native.log").open("ab") as log:
        return subprocess.Popen([str(arg) for arg in args], cwd=job / "run", env=environment(job),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def process_start(pid):
    """! @brief 재사용된 프로세스 번호를 제외할 수 있도록 커널 시작 시각을 읽는다."""
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except FileNotFoundError:
        return None


def alive(state):
    """! @brief 이 도구가 생성한 동일 프로세스의 생존 여부를 검사한다."""
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return (state.get("pid") is not None and state.get("started") is not None
            and state.get("process_boot", state["runtime"]["boot"]) == boot and process_start(state["pid"]) == state["started"])


def job_has_solver(job):
    """! @brief CLI가 갑자기 종료됐더라도 같은 작업 폴더에서 복원 중인 엔진을 보호한다."""
    commands = {str(path.resolve()) for path in (ENGINE, DMTCP / "bin/mtcp_restart", DMTCP / "bin/dmtcp_restart")}
    for path in Path("/proc").iterdir():
        if path.name.isdecimal():
            try:
                if os.readlink(path / "cwd") == str(job / "run") and os.readlink(path / "exe") in commands:
                    return True
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
    return False


def start_witness(job, args):
    """! @brief CLI가 끝난 뒤에도 실제 자식의 종료 코드를 파일에 원자적으로 기록한다."""
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(reader)
        try:
            os.setsid()
            with open(os.devnull, "r+b", buffering=0) as devnull:
                for fd in range(3):
                    os.dup2(devnull.fileno(), fd)
            proc = launch(job, args)
            os.write(writer, str(proc.pid).encode("ascii"))
            os.close(writer)
            code = proc.wait()
            temporary = job / "tmp" / "initial-exit"
            temporary.write_text(str(code), encoding="ascii")
            os.replace(temporary, job / "initial-exit")
        finally:
            os._exit(0)
    os.close(writer)
    with os.fdopen(reader, "rb") as pipe:
        pid = pipe.read(20)
    require(pid.isdigit(), "고정 엔진의 실행을 시작하지 못했습니다.")
    return int(pid)


def start(file, binding=None):
    """! @brief 입력과 계산 환경을 봉인한 뒤 단일 포트 계산을 시작한다."""
    raw, steps = input_xml(file)
    if binding is not None:
        require(hashlib.sha256(raw).hexdigest() == binding["sha256"], "준비한 XML의 예상 SHA256이 실제 입력과 다릅니다.")
    key = private_root()
    identity = runtime()
    if binding and binding.get("engine"):
        require(identity["files"][str(ENGINE)]["sha256"] == binding["engine"], "준비 당시 openEMS와 현재 고정 엔진의 SHA256이 다릅니다.")
    job = JOB_ROOT / str(uuid4())
    job.mkdir(mode=0o700)
    for folder in ("run", "images", "tmp", "history"):
        (job / folder).mkdir(mode=0o700)
    xml = job / "run/pcb.xml"
    xml.write_bytes(raw)
    state = {"schema": 1, "job": job.name, "directory": str(job), "status": "starting", "steps": steps,
             "runtime": identity, "xml": digest(xml), "attempt": 0, "binding": binding}
    save(job, key, state)
    pid = start_witness(job, [DMTCP / "bin/dmtcp_launch", "--new-coordinator", "--coord-host", "localhost", "--coord-port", "0",
                        "--port-file", job / "port", "--ckptdir", job / "images", "--ckpt-open-files", ENGINE, *ARGS])
    state.update(pid=pid, started=process_start(pid), status="running")
    port_file = job / "port"
    deadline = time.monotonic() + 30
    while not port_file.exists() and alive(state) and time.monotonic() < deadline:
        time.sleep(.05)
    port = port_file.read_text().strip() if port_file.exists() else ""
    if not (port.isdecimal() and 0 < int(port) <= 65535):
        if alive(state):
            os.killpg(pid, signal.SIGTERM)
        state["status"] = "failed"
        save(job, key, state)
        raise ValueError("이 작업의 조정기를 시작하지 못했습니다.")
    state["port"] = port
    save(job, key, state)
    return {"job": job.name, "status": "running", "directory": str(job)}


def coord(job, state, command):
    """! @brief 검증한 현재 openEMS 프로세스를 소유한 작업의 전용 로컬 조정기에만 명령한다."""
    require(alive(state) and (Path("/proc") / str(state["pid"]) / "exe").resolve() == ENGINE.resolve()
            and (Path("/proc") / str(state["pid"]) / "cwd").resolve() == job / "run", "실행 중인 원본 엔진을 찾을 수 없습니다.")
    port_file = job / "port"
    require(port_file.is_file() and not port_file.is_symlink(), "이 작업의 조정기 포트가 없습니다.")
    port = port_file.read_text().strip()
    require(port == state["port"], "실행할 때 기록한 조정기 포트가 다릅니다.")
    subprocess.run([str(DMTCP / "bin/dmtcp_command"), "--coord-host", "localhost", "--coord-port", port, command],
                   cwd=job / "run", env=environment(job), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   timeout=120, check=True)


def snapshot_files(job):
    """! @brief 전용 폴더에서 만든 단일 openEMS 이미지와 정확한 U/I 파일 대응을 봉인한다."""
    images = job / "images"
    require(not images.is_symlink(), "이미지 폴더 경계가 변경되었습니다.")
    candidates = list(images.glob("*.dmtcp"))
    require(len(candidates) == 1 and re.fullmatch(r"ckpt_openEMS_[A-Za-z0-9_-]+[.]dmtcp", candidates[0].name),
            "이 작업에서 만든 단일 openEMS 체크포인트를 찾을 수 없습니다.")
    image = candidates[0]
    aux = image.with_name(image.stem + "_files")
    require(aux.is_dir() and not aux.is_symlink(), "체크포인트 보조 폴더가 유효하지 않습니다.")
    table = aux / "fd-info.txt"
    require(table.is_file() and not table.is_symlink() and table.stat().st_size <= 8192, "프로브 파일 대응표를 확인하십시오.")
    files = [image, table]
    names = set()
    for line in table.read_text().splitlines():
        name, target = line.split(":", 1)
        matches = re.fullmatch(r"(port_[ui]t_1)_[0-9]+", name)
        require(matches and matches[1] not in names and Path(target) == job / "run" / matches[1],
                "체크포인트 보조 파일이 현재 작업의 U/I 프로브와 다릅니다.")
        names.add(matches[1])
        files.append(aux / name)
    require(names == set(TRACES) and {p.name for p in aux.iterdir()} == {p.name for p in files[1:]},
            "재개에 필요한 U/I 보조 파일이 다릅니다.")
    return image, {str(path.relative_to(job)): digest(path) for path in files}


def verify(job, state):
    """! @brief 재개 장소, 런타임과 준비 입력의 현재 지문을 시작 당시 값과 대조한다."""
    current = runtime()
    previous = dict(state["runtime"])
    previous.pop("boot")
    current.pop("boot")
    require(previous == current and state["xml"] == digest(job / "run/pcb.xml"),
            "준비 입력, 실행 파일, 라이브러리 또는 커널이 달라졌습니다.")


def suspend(job, key, state):
    """! @brief 실제 파형이 기록된 시점에 체크포인트를 완성하고 엔진을 중단한다."""
    if state["status"] == "suspended":
        return {"job": job.name, "status": "suspended"}
    require(state["status"] in {"running", "checkpointing", "stopping", "completed"}, "중단할 실행 상태가 아닙니다.")
    verify(job, state)

    def completed():
        """! @brief 정지 요청보다 먼저 끝난 정상 해석을 확인된 출력과 함께 보존한다."""
        observed = status(job, state)
        require(observed["status"] == "completed", "실행 종료 또는 정상 종료 코드를 확인하지 못했습니다.")
        state.update(result=observed["result"], status="completed")
        save(job, key, state)
        return {"job": job.name, "status": "completed", **state["result"]}

    if state["status"] == "completed" or (state["status"] in ("running", "checkpointing") and not alive(state)):
        return completed()
    if state["status"] == "running":
        def ready(name):
            """! @brief 두 프로브가 실제 수치 표본을 각각 두 개 이상 기록했는지 확인한다."""
            file = job / "run" / name
            if not file.is_file():
                return False
            with file.open("rb") as stream:
                return sum(bool(line.strip()) and not line.startswith(b"%") for line in stream.read(8192).splitlines()) >= 2

        limit = time.monotonic() + 120
        while alive(state) and not all(ready(name) for name in TRACES):
            require(time.monotonic() < limit, "중단할 U/I 표본을 아직 얻지 못했습니다.")
            time.sleep(.05)
        if not alive(state):
            return completed()
        state["status"] = "checkpointing"
        save(job, key, state)
    if state["status"] == "checkpointing":
        if "libraries" not in state:
            state["libraries"] = loaded_libraries(state["pid"])
            save(job, key, state)
        if not list((job / "images").glob("*.dmtcp")):
            coord(job, state, "-bc")
        deadline = time.monotonic() + 120
        while not list((job / "images").glob("*.dmtcp")):
            require(alive(state) and time.monotonic() < deadline, "엔진 체크포인트를 기록하지 못했습니다.")
            time.sleep(.05)
        _, state["checkpoint"] = snapshot_files(job)
        state["auxiliary"] = {name: digest(job / "run" / name) for name in ("et", "ht") if (job / "run" / name).exists()}
        state["status"] = "stopping"
        save(job, key, state)
    if alive(state):
        coord(job, state, "-k")
        deadline = time.monotonic() + 30
        while alive(state):
            require(time.monotonic() < deadline, "엔진 종료를 확인할 수 없습니다.")
            time.sleep(.05)
    state["status"] = "suspended"
    save(job, key, state)
    return {"job": job.name, "status": state["status"], "files": state["checkpoint"]}


def finish(job, state):
    """! @brief 종료 통계와 두 프로브의 유한 순차 표본을 검사한다."""
    directory = job / "run"
    stats = (directory / "openEMS_stats.txt").read_text()
    match = re.search(r"(?m)^([0-9]+)\s+% number of iterations", stats)
    require(match and 0 < int(match[1]) <= state["steps"], "해석 종료 스텝을 확인할 수 없습니다.")
    counts = {}
    for name in TRACES:
        count, last = 0, -math.inf
        with (directory / name).open("rb") as stream:
            for line in stream:
                if line.strip() and not line.startswith(b"%"):
                    t, v = map(float, line.split())
                    require(math.isfinite(t) and t > last and math.isfinite(v), "시간 파형에 중복 또는 유효하지 않은 표본이 있습니다.")
                    count += 1
                    last = t
        require(count >= 2, "두 개 이상의 유효한 프로브 표본이 필요합니다.")
        if "checkpoint" in state:
            prefix, = [path for path in state["checkpoint"] if Path(path).name.startswith(name + "_")]
            with (job / prefix).open("rb") as earlier, (directory / name).open("rb") as later:
                while block := earlier.read(1024 * 1024):
                    require(later.read(len(block)) == block, "중단 시점까지 기록한 U/I 파형과 재개 결과가 다릅니다.")
        counts[name] = count
    return {"iterations": int(match[1]), "samples": counts, "files": {n: digest(directory / n) for n in (*TRACES, "openEMS_stats.txt")}}


def resume(job, key, state):
    """! @brief 변경 없는 봉인 이미지만 복원하고 실패한 시도의 파형도 덮지 않는다."""
    verify(job, state)
    if state["status"] == "completed":
        require(finish(job, state) == state["result"], "완료 후 저장 결과가 달라졌습니다.")
        return {"job": job.name, "status": "completed", **state["result"]}
    require(state["status"] in ("suspended", "resuming"), "중단된 작업의 UUID를 지정하십시오.")
    require(not job_has_solver(job), "이 작업의 엔진이 이미 실행 중입니다.")
    require(all(digest(Path(path), installed=True) == expected for path, expected in state["libraries"].items()),
            "엔진이 적재한 공유 라이브러리가 바뀌었습니다.")
    image, files = snapshot_files(job)
    require(files == state["checkpoint"] and all(digest(job / "run" / n) == v for n, v in state["auxiliary"].items()),
            "체크포인트 이미지나 보조 자료의 해시가 다릅니다.")
    if state["status"] == "resuming":
        require(not alive(state), "이미 재개한 동일 엔진이 아직 실행 중입니다.")
    state["attempt"] += 1
    prior = job / "history" / str(state["attempt"])
    while prior.exists():
        state["attempt"] += 1
        prior = job / "history" / str(state["attempt"])
    prior.mkdir(mode=0o700)
    for name in (*TRACES, "openEMS_stats.txt", "openEMS_run_stats.txt"):
        file = job / "run" / name
        if file.exists():
            require(file.is_file() and not file.is_symlink(), "이전 출력 파일이 올바르지 않습니다.")
            file.rename(prior / name)
    proc = launch(job, [DMTCP / "bin/dmtcp_restart", "--new-coordinator", "--coord-host", "localhost",
                        "--coord-port", "0", image])
    state.update(status="resuming", pid=proc.pid, started=process_start(proc.pid),
                 process_boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip())
    save(job, key, state)
    try:
        require(proc.wait() == 0, "체크포인트 복원 실행이 실패했습니다. 보존된 자료로 다시 시도할 수 있습니다.")
        state.update(result=finish(job, state), status="completed")
    except BaseException:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=30)
        state["status"] = "suspended"
        save(job, key, state)
        raise
    save(job, key, state)
    return {"job": job.name, "status": "completed", **state["result"]}


def binding_from(args):
    """! @brief 사용자 프로젝트, 준비 계획과 XML 해시를 하나의 실행 범위로 검증한다."""
    values = (args.project, args.plan, args.sha256)
    if all(value is None for value in values) and args.engine is None:
        return None
    require(all(values) and all(str(UUID(value)) == value for value in values[:2])
            and re.fullmatch("[a-f0-9]{64}", args.sha256), "프로젝트, 준비 계획 UUID와 XML SHA256을 모두 지정하십시오.")
    require(args.engine is None or re.fullmatch("[a-f0-9]{64}", args.engine), "엔진 SHA256이 유효하지 않습니다.")
    return {**dict(zip(("project", "plan", "sha256"), values)), "engine": args.engine}


def status(job, state):
    """! @brief 비정상 또는 미확인 종료는 파형이 남아 있어도 성공으로 표시하지 않는다."""
    active = alive(state)
    result = {"job": job.name, "status": state["status"], "alive": active, "directory": str(job),
              "can_resume": "checkpoint" in state and state["status"] in ("resuming", "suspended")}
    if state["status"] in ("running", "checkpointing") and not active:
        marker = job / "initial-exit"
        if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != b"0":
            return {**result, "status": "interrupted", "reason": "엔진의 정상 종료를 확인하지 못했습니다."}
        return {**result, "status": "completed", "result": finish(job, state)}
    if state["status"] == "resuming" and not active:
        result.update(status="interrupted", reason="재개 감독 종료를 확인 중입니다. 보존한 체크포인트에서 재시도할 수 있습니다.")
    if state.get("result"):
        require(state["result"] == finish(job, state), "완료 결과의 파일 또는 샘플이 바뀌었습니다.")
        result["result"] = state["result"]
    return result


def main():
    """! @brief 입력 XML과 자체 작업 ID로 시작, 중단, 재개, 상태 조회를 제공한다."""
    parser = argparse.ArgumentParser(description="단일 포트 PCB openEMS 체크포인트")
    commands = parser.add_subparsers(dest="command", required=True)
    for action in ("start", "suspend", "resume", "status", "list"):
        command = commands.add_parser(action)
        for field in ("project", "plan", "sha256", "engine"):
            command.add_argument("--" + field)
        if action in ("start", "list"):
            command.add_argument("--xml", type=Path, required=action == "start")
        elif action != "list":
            command.add_argument("job")
    args = parser.parse_args()
    os.umask(0o077)
    binding = binding_from(args)
    if args.command == "start":
        result = start(args.xml, binding)
    elif args.command == "list":
        require(binding is not None, "조회할 프로젝트와 준비 입력이 필요합니다.")
        if args.xml:
            raw, _ = input_xml(args.xml)
            require(hashlib.sha256(raw).hexdigest() == binding["sha256"], "준비 XML의 SHA256이 다릅니다.")
            identity = runtime()
            require(not binding.get("engine") or binding["engine"] == identity["files"][str(ENGINE)]["sha256"],
                    "고정 설치 엔진이 준비 당시 SHA256과 다릅니다.")
        private_root()
        jobs = []
        for folder in JOB_ROOT.iterdir():
            if re.fullmatch("[0-9a-f-]{36}", folder.name) and (folder / "state.json").exists():
                with locked(folder.name, writing=False) as (job, key, state):
                    if state.get("binding") == binding:
                        jobs.append({"job": job.name, "status": state["status"], "created_ns": (job / "run/pcb.xml").stat().st_mtime_ns})
        result = {"jobs": sorted(jobs, key=lambda row: row["created_ns"], reverse=True)[:64]}
    else:
        with locked(args.job, writing=args.command != "status") as (job, key, state):
            require(binding is None or state.get("binding") == binding, "다른 프로젝트 또는 준비 입력에 속한 작업입니다.")
            if args.command == "suspend":
                result = suspend(job, key, state)
            elif args.command == "resume":
                result = resume(job, key, state)
            else:
                result = status(job, state)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, ParseError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
