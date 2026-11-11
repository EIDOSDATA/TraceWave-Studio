"""! @brief WSL ext4에서 실행 소유권과 lease 및 확정 종료 증거를 보존한다."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid


PROTOCOL = "rfad.wsl-supervisor/0.1"
TERMINAL = {"completed", "failed", "cancelled", "timeout", "output_limit"}
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_INPUT_FILES = 1024


def encoded(value):
    """! @brief 내부 제어 파일의 정규 UTF-8 바이트를 반환한다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(path):
    """! @brief 파일 바이트의 SHA-256을 계산한다."""
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def atomic(path, value):
    """! @brief 동일 디렉터리 임시 파일과 fsync로 상태를 원자적으로 저장한다."""
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_json(path, maximum=256 * 1024):
    """! @brief 경로 교체와 경합하지 않게 열린 inode의 유형/크기를 검사하고 읽는다."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(descriptor)
        # @brief atomic replace가 이전 inode를 unlink한 경우 nlink=0은 정상이다. 다중 링크는 거절한다.
        if not stat.S_ISREG(info.st_mode) or info.st_nlink not in (0, 1) or info.st_size > maximum:
            raise ValueError("unsafe control file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
    finally:
        os.close(descriptor)
    if len(raw) > maximum:
        raise ValueError("control file limit")
    return json.loads(raw)


@contextlib.contextmanager
def locked(path):
    """! @brief 상태와 sticky 취소를 flock으로 순서화한다."""
    import fcntl
    with Path(path).open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def validate_identity(run_id, nonce):
    """! @brief 디렉터리 경로에 UUID와 충분한 길이의 실행 nonce만 허용한다."""
    if type(run_id) is not str or str(uuid.UUID(run_id)) != run_id:
        raise ValueError("invalid run UUID")
    if type(nonce) is not str or not re.fullmatch(r"[a-f0-9]{32,128}", nonce):
        raise ValueError("invalid run nonce")


def safe_directory(path, create=False):
    """! @brief 링크 경유 없이 현재 사용자가 소유한 private 디렉터리를 사용한다."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute directory required")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for current in [*reversed(path.parents), path]:
        metadata = current.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise ValueError("unsafe directory")
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("directory must be owned and private")
    return path


def run_path(payload):
    """! @brief 저장된 실행 nonce를 확인한 뒤 해당 실행 경로를 반환한다."""
    validate_identity(payload["run_id"], payload["nonce"])
    root = safe_directory(payload["guest_root"])
    path = safe_directory(root / payload["run_id"])
    specification = read_json(path / "supervisor.json", 1024 * 1024)
    if specification["nonce"] != payload["nonce"]:
        raise ValueError("run ownership rejected")
    return path, specification


def publish(path, **updates):
    """! @brief 최초 terminal을 유지하면서 최신 상태의 단조 증가 cursor를 기록한다."""
    with locked(path / "status.lock"):
        status_path = path / "status.json"
        current = read_json(status_path) if status_path.exists() else {"cursor": 0}
        if current.get("state") in TERMINAL and current.get("termination_confirmed"):
            return current
        current.update(updates)
        current["cursor"] += 1
        current["updated_at"] = time.time()
        atomic(status_path, current)
        return current


def _input_path(value):
    """! @brief 고정 worker와 소스 및 데이터 경로만 staging 입력으로 허용한다."""
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or str(path) != value:
        raise ValueError("invalid staged relative path")
    if value in {"request.json", "runtime.json", "tools/openems_worker.py"}:
        return path
    if path.parts[0] == "src" and value.endswith(".py"):
        return path
    if path.parts[0] == "input" and len(path.parts) > 1:
        return path
    raise ValueError("unexpected staged input")


def start(payload):
    """! @brief 검증된 불변 입력을 ext4에 복사한 뒤 독립 supervisor를 시작한다."""
    validate_identity(payload["run_id"], payload["nonce"])
    root = safe_directory(payload["guest_root"], create=True)
    if str(root).startswith("/mnt/"):
        raise ValueError("guest runtime requires Linux filesystem")
    manifest = payload["files"]
    if type(manifest) is not list or not 3 <= len(manifest) <= MAX_INPUT_FILES:
        raise ValueError("input file count limit")
    paths = [_input_path(item["path"]) for item in manifest]
    if len(set(paths)) != len(paths) or not {"request.json", "runtime.json", "tools/openems_worker.py"} <= {str(item) for item in paths}:
        raise ValueError("missing or duplicate staged files")
    if sum(item["bytes"] for item in manifest) > MAX_INPUT_BYTES:
        raise ValueError("input byte limit")
    for field in ("timeout_seconds", "lease_seconds"):
        if type(payload[field]) not in (int, float) or not math.isfinite(payload[field]) or payload[field] <= 0:
            raise ValueError("invalid time budget")
    if not Path(payload["python"]).is_absolute():
        raise ValueError("fixed Python absolute path required")
    path = root / payload["run_id"]
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        existing, specification = run_path(payload)
        if specification["files"] != manifest or specification["python"] != payload["python"]:
            raise ValueError("existing run immutable inputs differ")
        return read_json(existing / "status.json")
    specification = {**payload, "protocol": PROTOCOL}
    atomic(path / "supervisor.json", specification)
    publish(path, protocol=PROTOCOL, run_id=payload["run_id"], nonce=payload["nonce"], state="starting",
            phase="preparing", termination_confirmed=False, outcome_unknown=True)
    try:
        stage = Path(payload["host_stage"])
        if not stage.is_absolute() or ".." in stage.parts:
            raise ValueError("absolute host staging required")
        for item in manifest:
            relative = _input_path(item["path"])
            source = stage / relative
            for current in [stage, *[stage / parent for parent in reversed(relative.parents) if str(parent) != "."]]:
                if not stat.S_ISDIR(current.lstat().st_mode):
                    raise ValueError("staging directory link")
            metadata = source.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size != item["bytes"]:
                raise ValueError("staging file identity")
            destination = path / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with source.open("rb") as reader, destination.open("xb") as writer:
                copied = 0
                while block := reader.read(min(1024 * 1024, item["bytes"] + 1 - copied)):
                    copied += len(block)
                    if copied > item["bytes"]:
                        raise ValueError("staging changed during copy")
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            if destination.stat().st_size != item["bytes"] or digest(destination) != item["sha256"]:
                raise ValueError("staging content hash mismatch")
            destination.chmod(0o400)
        for directory in (path / "src", path / "tools", path / "input"):
            if directory.exists():
                for current in directory.rglob("*"):
                    if current.is_dir():
                        current.chmod(0o500)
                directory.chmod(0o500)
        request = read_json(path / "request.json")
        if request.get("run_id") != payload["run_id"] or request.get("nonce") != payload["nonce"]:
            raise ValueError("worker request ownership mismatch")
        (path / "output").mkdir(mode=0o700)
        atomic(path / "control.json", {"nonce": payload["nonce"], "heartbeat": 0, "cancel": False})
        supervisor_hash = digest(__file__)
        if supervisor_hash != payload["supervisor_sha256"]:
            raise ValueError("supervisor hash mismatch")
        installed = root / ("supervisor-" + supervisor_hash + ".py")
        if not installed.exists():
            temporary = root / ("supervisor-" + uuid.uuid4().hex + ".partial")
            shutil.copyfile(__file__, temporary)
            temporary.chmod(0o400)
            os.replace(temporary, installed)
        if digest(installed) != supervisor_hash:
            raise ValueError("installed supervisor hash mismatch")
        child = subprocess.Popen([sys.executable, "-I", "-B", str(installed), "daemon",
                                  base64.b64encode(encoded({key: payload[key] for key in ("guest_root", "run_id", "nonce")})).decode("ascii")],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True, close_fds=True,
                                 env={key: value for key, value in os.environ.items() if key != "RFAD_WSL_RUN_TOKEN"})
        threading.Thread(target=child.wait, daemon=True, name="rfad-supervisor-reap").start()
        # @brief ACK는 worker 종료 증거가 아니며 이후 독립 status 조회가 권위 상태다.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = read_json(path / "status.json")
            if status["state"] != "starting":
                return status
            if child.poll() is not None:
                raise RuntimeError("supervisor exited before acknowledgement")
            time.sleep(0.02)
        return read_json(path / "status.json")
    except Exception as error:
        status = read_json(path / "status.json")
        if status["state"] == "starting" and "child" not in locals():
            return publish(path, state="failed", termination_confirmed=True, outcome_unknown=False,
                           error=str(error)[:2048])
        raise


def control(payload, command):
    """! @brief nonce 검증 뒤 heartbeat 또는 취소를 누적하고 현재 상태를 반환한다."""
    path, specification = run_path(payload)
    if command in {"heartbeat", "cancel"}:
        with locked(path / "control.lock"):
            value = read_json(path / "control.json")
            value["heartbeat"] += 1
            value["cancel"] = value["cancel"] or command == "cancel"
            atomic(path / "control.json", value)
    return read_json(path / "status.json")


def _owned_members(group, nonce):
    """! @brief 실행 nonce로 새 process group/session으로 이동한 후손까지 식별한다.

    @details 고정 worker와 후손은 nonce 환경표식을 상속한다. supervisor/watchdog에는
    이 표식을 상속하지 않는다. 원래 세션에서 표식을 확인할 수 없으면 종료를 추측하지
    않는다. 세션 변경과 표식 제거를 조합한 적대 코드의 격리는 이 계층의 범위가 아니다.
    """
    members = []
    token = ("RFAD_WSL_RUN_TOKEN=" + nonce).encode("ascii")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] in {"Z", "X"}:
                continue
            in_session = int(fields[3]) == group
            if entry.stat().st_uid != os.getuid():
                if in_session:
                    raise RuntimeError("owned session user identity changed")
                continue
            try:
                marked = token in (entry / "environ").read_bytes().split(b"\0")
            except PermissionError:
                if in_session:
                    raise RuntimeError("owned session identity could not be read")
                continue
            if marked:
                members.append((int(entry.name), fields[19]))
            elif in_session:
                raise RuntimeError("owned session identity could not be confirmed")
        except (FileNotFoundError, ProcessLookupError):
            continue
    return members


def _terminate_owned(group, nonce):
    """! @brief 재사용 PID에 신호를 보내지 않도록 pidfd와 시작 시각을 함께 확인한다."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        members = _owned_members(group, nonce)
        if not members:
            return True
        for pid, started in members:
            try:
                descriptor = os.pidfd_open(pid)
                try:
                    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                    if fields[19] == started:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                finally:
                    os.close(descriptor)
            except (ProcessLookupError, FileNotFoundError):
                pass
        time.sleep(0.02)
    return not _owned_members(group, nonce)


def watchdog(payload):
    """! @brief supervisor 사망에도 해당 실행 후손만 종료하고 종료 확인 상태를 남긴다."""
    path, specification = run_path(payload)
    descriptor = os.pidfd_open(payload["supervisor_pid"])
    try:
        actual = Path(f"/proc/{payload['supervisor_pid']}/stat").read_text().rsplit(")", 1)[1].split()[19]
        if actual != payload["supervisor_started"]:
            raise RuntimeError("supervisor identity changed")
        poller = select.poll()
        poller.register(descriptor, select.POLLIN)
        atomic(path / "watchdog-ready.json", {"nonce": payload["nonce"], "pid": os.getpid()})
        while True:
            status = read_json(path / "status.json")
            if status.get("state") in TERMINAL and status.get("termination_confirmed"):
                return
            if poller.poll(100):
                break
        confirmed = _terminate_owned(payload["worker_pid"], payload["nonce"])
        publish(path, state="failed", termination_confirmed=confirmed, outcome_unknown=not confirmed,
                error="guest supervisor exited unexpectedly", reason="supervisor_lost")
    except Exception as error:
        publish(path, state="failed", termination_confirmed=False, outcome_unknown=True,
                error=str(error)[:2048], reason="watchdog_failed")
    finally:
        os.close(descriptor)


def daemon(payload):
    """! @brief 별도 세션에서 lease와 worker 그룹 및 유한 출력의 수명을 소유한다."""
    path, specification = run_path(payload)
    sys.path.insert(0, str(path / "src"))
    from rfad.application.native_process import run_native
    os.environ["RFAD_WSL_RUN_TOKEN"] = payload["nonce"]
    cancel = threading.Event()
    finished = threading.Event()
    reason = {"value": "", "control_error": ""}
    watchdog_process = None
    worker_pid = None
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, lambda *unused: cancel.set())
    publish(path, state="active", phase="preparing", supervisor_pid=os.getpid())

    def monitor():
        """! @brief host 시계 대신 guest monotonic 시계로 heartbeat lease를 검사한다."""
        last = -1
        deadline = time.monotonic() + specification["lease_seconds"]
        phase = "preparing"
        try:
            while not finished.wait(0.05):
                value = read_json(path / "control.json")
                if value["heartbeat"] != last:
                    last = value["heartbeat"]
                    deadline = time.monotonic() + specification["lease_seconds"]
                if value["cancel"]:
                    cancel.set()
                if time.monotonic() >= deadline:
                    reason["value"] = "lease_expired"
                    cancel.set()
                if watchdog_process is not None and watchdog_process.poll() is not None:
                    reason["value"] = "watchdog_lost"
                    cancel.set()
                try:
                    progress = read_json(path / "progress.json", 4096)
                    current = progress.get("phase")
                    if current in {"preparing", "running", "postprocessing"} and current != phase:
                        phase = current
                        publish(path, phase=phase)
                except FileNotFoundError:
                    pass
        except Exception as error:
            reason["value"] = "control_failed"
            reason["control_error"] = type(error).__name__ + ": " + str(error)[:1024]
            cancel.set()

    def started(information):
        """! @brief worker gate를 열기 전에 소유 PID와 독립 watchdog 준비를 확인한다."""
        nonlocal watchdog_process, worker_pid
        worker_pid = information["pid"]
        publish(path, worker_pid=information["pid"])
        identity = {**payload, "supervisor_pid": os.getpid(), "worker_pid": information["pid"],
                    "supervisor_started": Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]}
        watchdog_process = subprocess.Popen([sys.executable, "-I", "-B", __file__, "watchdog",
                                             base64.b64encode(encoded(identity)).decode("ascii")],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                                            env={key: value for key, value in os.environ.items() if key != "RFAD_WSL_RUN_TOKEN"})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                ready = read_json(path / "watchdog-ready.json")
                if ready["nonce"] == payload["nonce"] and ready["pid"] == watchdog_process.pid:
                    return
            except FileNotFoundError:
                pass
            if watchdog_process.poll() is not None:
                break
            time.sleep(0.01)
        raise RuntimeError("watchdog acknowledgement missing")

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        result = run_native([specification["python"], "-I", "-B", "tools/openems_worker.py", "--request", "request.json"],
                            path, encoded({"schema": "rfad.wsl-start/0.1", "run_id": payload["run_id"], "nonce": payload["nonce"]}) + b"\n",
                            cancel, timeout_seconds=specification["timeout_seconds"], on_started=started,
                            output_directory=path / "output", **specification["limits"])
        state = result["termination"]
        if state == "completed" and result["returncode"] != 0:
            state = "failed"
        # @brief run_native는 원래 process group을 회수하며 전체 실행 후손은 별도로 확인한다.
        confirmed = _terminate_owned(worker_pid, payload["nonce"])
        publish(path, state=state if confirmed else "failed", termination_confirmed=confirmed, outcome_unknown=not confirmed,
                native=result, reason=reason["value"], control_error=reason["control_error"])
    except Exception as error:
        unknown = bool(getattr(error, "details", {}).get("outcome_unknown"))
        confirmed = not unknown and worker_pid is None
        recovery_error = ""
        if worker_pid is not None:
            try:
                confirmed = _terminate_owned(worker_pid, payload["nonce"])
            except Exception as cleanup_error:
                recovery_error = str(cleanup_error)[:2048]
        publish(path, state="failed", termination_confirmed=confirmed, outcome_unknown=not confirmed,
                error=str(error)[:2048], recovery_error=recovery_error, reason=reason["value"], control_error=reason["control_error"])
    finally:
        finished.set()
        thread.join(timeout=1)
        if watchdog_process is not None:
            try:
                watchdog_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # @brief 확인 불가 watchdog를 임의로 죽이지 않고 독립 회수 책임을 유지한다.
                pass


def export(payload):
    """! @brief 실제 종료가 확인된 출력만 사전 등록한 host staging 경로로 복사한다."""
    path, specification = run_path(payload)
    status = read_json(path / "status.json")
    if status["state"] not in TERMINAL or not status["termination_confirmed"] or status["outcome_unknown"]:
        raise ValueError("guest termination is not confirmed")
    sys.path.insert(0, str(path / "src"))
    from rfad.application.native_process import _scan_output
    limits = specification["limits"]
    observation = _scan_output(path / "output", path, limits["max_file_bytes"], limits["max_directory_bytes"], limits["max_files"])
    if observation["reason"]:
        raise ValueError("unsafe or excessive output: " + observation["reason"])
    destination = Path(specification["host_stage"]) / "output"
    if destination.exists():
        raise ValueError("host output already exists")
    destination.mkdir(mode=0o700)
    files = []
    for source in sorted((path / "output").rglob("*")):
        if source.is_file():
            relative = source.relative_to(path / "output")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            files.append({"path": "output/" + relative.as_posix(), "bytes": source.stat().st_size, "sha256": digest(source)})
    return {**status, "exported_files": files}


def main():
    """! @brief 고정 프로토콜 명령만 접수하고 셸이나 임의 실행 인수를 노출하지 않는다."""
    if len(sys.argv) != 3:
        raise ValueError("command and bounded payload required")
    command = sys.argv[1]
    if len(sys.argv[2]) > 2 * 1024 * 1024:
        raise ValueError("payload limit")
    payload = json.loads(base64.b64decode(sys.argv[2], validate=True))
    if command == "start":
        result = start(payload)
    elif command in {"status", "heartbeat", "cancel"}:
        result = control(payload, command)
    elif command == "export":
        result = export(payload)
    elif command == "daemon":
        daemon(payload)
        return
    elif command == "watchdog":
        watchdog(payload)
        return
    else:
        raise ValueError("unsupported command")
    print(encoded(result).decode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(encoded({"protocol": PROTOCOL, "error": str(error)[:2048]}).decode("utf-8"))
        raise SystemExit(2)
