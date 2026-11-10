"""! @brief 고정 WSL supervisor 명령으로 guest 실행의 소유권과 종료 증거를 관리한다."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import threading
import time
import uuid
from typing import Callable

from rfad.domain.errors import ProjectError


PROTOCOL = "rfad.wsl-supervisor/0.1"
TERMINAL = {"completed", "failed", "cancelled", "timeout", "output_limit"}
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_INPUT_FILES = 1024
# @brief host가 고정한 supervisor 바이트를 검증한 뒤에만 고정 명령을 실행한다.
BOOTSTRAP = (
    "import hashlib,json,pathlib,runpy,sys;"
    "p=pathlib.Path(sys.argv[1]);b=p.read_bytes();"
    "assert len(b)<=262144 and hashlib.sha256(b).hexdigest()==sys.argv[2],'supervisor hash mismatch';"
    "v=sys.stdin.buffer.read(2097153);assert len(v)<=2097152,'payload limit';"
    "sys.argv=[str(p),sys.argv[3],v.decode('ascii')];"
    "exec(compile(b,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})"
)


def _hash(path: Path) -> str:
    """! @brief 큰 입력을 한 번에 메모리에 올리지 않고 SHA-256을 구한다."""
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _regular(metadata) -> bool:
    """! @brief 링크와 Windows 재분석점 및 다중 하드 링크를 거부한다."""
    return (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
            and not bool(getattr(metadata, "st_file_attributes", 0) & 0x400))


def _identity(run_id: str, nonce: str) -> None:
    """! @brief 정규 UUID와 실행별 nonce를 엄격히 검증한다."""
    try:
        valid = type(run_id) is str and str(uuid.UUID(run_id)) == run_id
    except (ValueError, AttributeError):
        valid = False
    if not valid or type(nonce) is not str or not re.fullmatch(r"[a-f0-9]{32,128}", nonce):
        raise ProjectError("E_SCHEMA", "WSL 실행 UUID 또는 nonce 형식이 잘못되었습니다.")


def _run_control(argv: list[str], raw: bytes, timeout: float) -> subprocess.CompletedProcess:
    """! @brief 제어 출력도 실시간 byte 상한을 적용하며 launcher만 유한 시간에 회수한다."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               shell=False, close_fds=True, bufsize=0,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    overflow = threading.Event()
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    errors = []

    def drain(name, limit):
        """! @brief 전체 출력을 누적하지 않고 허용한 첫 바이트만 메모리에 보관한다."""
        try:
            while block := getattr(process, name).read(8192):
                remaining = max(0, limit - len(streams[name]))
                streams[name].extend(block[:remaining])
                if len(block) > remaining:
                    overflow.set()
        except OSError as error:
            errors.append(error)

    def write():
        """! @brief stdin을 읽지 않는 launcher도 감독 루프를 멈추지 못하게 한다."""
        try:
            remaining = memoryview(raw)
            while remaining:
                count = process.stdin.write(remaining)
                if not count:
                    break
                remaining = remaining[count:]
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    threads = [threading.Thread(target=drain, args=(name, limit), daemon=True)
               for name, limit in (("stdout", 256 * 1024), ("stderr", 64 * 1024))]
    threads.append(threading.Thread(target=write, daemon=True))
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    violation = ""
    try:
        while process.poll() is None:
            if overflow.is_set():
                violation = "output_limit"
                break
            if time.monotonic() >= deadline:
                violation = "timeout"
                break
            time.sleep(0.01)
        if violation:
            # @brief 이 종료는 Windows 연결만 닫으며 guest 종료 증거가 아니다.
            process.kill()
        process.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=1)
        if overflow.is_set() or errors or any(thread.is_alive() for thread in threads) or violation:
            raise ProjectError("E_RESOURCE", "WSL 제어 연결이 시간 또는 출력 상한을 넘었습니다.",
                               details={"outcome_unknown": True, "reason": violation or "output_limit"})
        return subprocess.CompletedProcess(argv, process.returncode, bytes(streams["stdout"]), bytes(streams["stderr"]))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


class WslRuntime:
    """! @brief 셸 없는 WSL 제어와 재접속 가능한 guest 감독 계층을 제공한다.

    @details 구성 경로는 서비스가 선택하며 프로젝트나 공개 API의 실행 인수가 아니다.
    Windows launcher 종료와 guest 그룹 종료 확인을 별개의 증거로 취급한다.
    """

    def __init__(self, distribution="TraceWave-Dev", user="tracewave",
                 python="/home/tracewave/rfad-runtime/openems-venv/bin/python",
                 guest_root="/home/tracewave/rfad-runtime/worker-runs", *,
                 lease_seconds=10.0, poll_seconds=0.25, control_timeout_seconds=10.0):
        """! @brief 승인된 실행 구성과 supervisor 소스 바이트를 생성 시점에 고정한다."""
        if (type(distribution) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", distribution)
                or type(user) is not str or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user)):
            raise ProjectError("E_SCHEMA", "WSL 배포판 또는 사용자 식별자가 잘못되었습니다.")
        for value in (python, guest_root):
            if (type(value) is not str or not PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
                    or any(character in value for character in "\0\r\n")):
                raise ProjectError("E_SCHEMA", "WSL 런타임은 고정 Linux 절대 경로여야 합니다.")
        if str(guest_root).startswith("/mnt/"):
            raise ProjectError("E_SCHEMA", "WSL 실행 staging은 Linux 파일시스템에 있어야 합니다.")
        for value in (lease_seconds, poll_seconds, control_timeout_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ProjectError("E_SCHEMA", "WSL 감독 시간은 유한 양수여야 합니다.")
        self.distribution = distribution
        self.user = user
        self.python = python
        self.guest_root = guest_root.rstrip("/")
        self.lease_seconds = float(lease_seconds)
        self.poll_seconds = float(poll_seconds)
        self.control_timeout_seconds = float(control_timeout_seconds)
        self._source = Path(__file__).resolve().parents[3] / "tools" / "wsl_supervisor.py"
        self._supervisor = self._source.read_bytes()
        self._supervisor_sha256 = hashlib.sha256(self._supervisor).hexdigest()

    def identity(self) -> dict:
        """! @brief 외부 실행 없이 계획에 동결할 순수 런타임 descriptor를 반환한다."""
        return {"protocol": PROTOCOL, "distribution": self.distribution, "user": self.user,
                "python": self.python, "guest_root": self.guest_root,
                "supervisor_sha256": self._supervisor_sha256, "lease_seconds": self.lease_seconds}

    @staticmethod
    def _linux_path(path: Path) -> str:
        """! @brief WSL 기본 automount의 로컬 드라이브 경로만 변환한다."""
        text = str(path)
        if os.name != "nt" and path.is_absolute():
            return path.as_posix()
        if not re.match(r"^[A-Za-z]:[\\/]", text):
            raise ProjectError("E_UNSUPPORTED", "WSL staging은 로컬 Windows 드라이브 경로여야 합니다.")
        return "/mnt/" + text[0].lower() + "/" + text[3:].replace("\\", "/")

    def _invoke(self, command: str, payload: dict, *, bootstrap=False) -> dict:
        """! @brief 셸 없는 argv와 한정된 stdin으로 고정 supervisor 명령을 호출한다."""
        if command not in {"start", "status", "heartbeat", "cancel", "export"}:
            raise ProjectError("E_SCHEMA", "지원하지 않는 WSL supervisor 명령입니다.")
        script = self._linux_path(self._source) if bootstrap else self.guest_root + "/supervisor-" + self._supervisor_sha256 + ".py"
        raw = base64.b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if len(raw) > 2 * 1024 * 1024:
            raise ProjectError("E_RESOURCE", "WSL 제어 입력 상한을 넘었습니다.")
        argv = ["wsl.exe", "--distribution", self.distribution, "--user", self.user, "--exec", "/usr/bin/python3",
                "-I", "-B", "-c", BOOTSTRAP, script, self._supervisor_sha256, command]
        try:
            result = _run_control(argv, raw, self.control_timeout_seconds)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProjectError("E_RESOURCE", "WSL 제어 연결의 응답을 확인하지 못했습니다.",
                               details={"outcome_unknown": True, "command": command}) from error
        if len(result.stdout) > 256 * 1024 or len(result.stderr) > 64 * 1024:
            raise ProjectError("E_RESOURCE", "WSL 제어 응답 상한을 넘었습니다.", details={"outcome_unknown": True})
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError) as error:
            raise ProjectError("E_RESOURCE", "WSL 제어 응답이 올바른 JSON이 아닙니다.",
                               details={"outcome_unknown": True, "stderr": result.stderr[-2048:].decode("utf-8", errors="replace")}) from error
        if result.returncode or not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
            raise ProjectError("E_RESOURCE", "WSL supervisor 명령이 실패했습니다.",
                               details={"outcome_unknown": True, "response": value})
        if value.get("run_id") != payload["run_id"] or value.get("nonce") != payload["nonce"]:
            raise ProjectError("E_HASH", "WSL 응답의 실행 소유권이 다릅니다.", details={"outcome_unknown": True})
        return value

    def _control(self, command: str, run_id: str, nonce: str) -> dict:
        """! @brief run UUID와 nonce가 일치하는 기존 실행에만 제어를 보낸다."""
        _identity(run_id, nonce)
        return self._invoke(command, {"guest_root": self.guest_root, "run_id": run_id, "nonce": nonce})

    def inspect(self, run_id: str, nonce: str) -> dict:
        """! @brief 재실행 없이 guest가 저장한 권위 상태와 cursor를 조회한다."""
        return self._control("status", run_id, nonce)

    def cancel(self, run_id: str, nonce: str) -> dict:
        """! @brief sticky 취소를 기록하며 응답만으로 종료를 확정하지 않는다."""
        return self._control("cancel", run_id, nonce)

    def heartbeat(self, run_id: str, nonce: str) -> dict:
        """! @brief 살아 있는 host 소유자의 lease를 갱신한다."""
        return self._control("heartbeat", run_id, nonce)

    @staticmethod
    def _manifest(stage: Path) -> list[dict]:
        """! @brief 고정 입력 allowlist와 크기 및 링크 제한을 확인한 manifest를 만든다."""
        info = stage.lstat()
        if not stat.S_ISDIR(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            raise ProjectError("E_SCHEMA", "WSL staging은 링크가 아닌 디렉터리여야 합니다.")
        result = []
        total = 0
        for path in sorted(stage.rglob("*")):
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode) and not bool(getattr(info, "st_file_attributes", 0) & 0x400):
                continue
            relative = path.relative_to(stage).as_posix()
            allowed = (relative in {"request.json", "runtime.json", "tools/openems_worker.py"}
                       or relative.startswith("src/") and relative.endswith(".py")
                       or relative.startswith("input/"))
            if not allowed or not _regular(info):
                raise ProjectError("E_SCHEMA", "허용하지 않은 WSL 입력 파일입니다: " + relative)
            total += info.st_size
            if total > MAX_INPUT_BYTES or len(result) >= MAX_INPUT_FILES:
                raise ProjectError("E_RESOURCE", "WSL staging 입력 상한을 넘었습니다.")
            result.append({"path": relative, "bytes": info.st_size, "sha256": _hash(path)})
        if not {"request.json", "runtime.json", "tools/openems_worker.py"} <= {item["path"] for item in result}:
            raise ProjectError("E_SCHEMA", "WSL 고정 worker 입력이 누락되었습니다.")
        return result

    def execute(self, stage: Path, *, run_id: str, nonce: str, cancel: threading.Event,
                timeout_seconds: float = 120, on_state: Callable[[dict], None] | None = None,
                max_output_bytes: int = 4 * 1024 * 1024, max_file_bytes: int = 64 * 1024 * 1024,
                max_directory_bytes: int = 128 * 1024 * 1024, max_files: int = 128) -> dict:
        """! @brief 불변 입력으로 한 번 실행하고 실제 guest 종료 확인 뒤에만 출력을 회수한다."""
        try:
            _identity(run_id, nonce)
            if cancel.is_set():
                return {"protocol": PROTOCOL, "run_id": run_id, "nonce": nonce, "state": "cancelled",
                        "termination_confirmed": True, "outcome_unknown": False, "not_started": True}
            if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
                raise ProjectError("E_SCHEMA", "WSL worker 시간 상한은 유한 양수여야 합니다.")
            limits = {"max_output_bytes": max_output_bytes, "max_file_bytes": max_file_bytes,
                      "max_directory_bytes": max_directory_bytes, "max_files": max_files}
            if any(type(value) is not int or value <= 0 for value in limits.values()):
                raise ProjectError("E_SCHEMA", "WSL 출력 상한은 양의 정수여야 합니다.")
            stage = Path(os.path.abspath(stage))
            manifest = self._manifest(stage)
            if self._source.read_bytes() != self._supervisor:
                raise ProjectError("E_VERSION", "동결 후 WSL supervisor 구현이 변경되었습니다.")
            payload = {**self.identity(), "host_stage": self._linux_path(stage), "run_id": run_id, "nonce": nonce,
                       "files": manifest, "timeout_seconds": timeout_seconds, "limits": limits}
        except ProjectError as error:
            error.details.update({"termination_confirmed": True, "outcome_unknown": False, "not_started": True})
            raise
        except OSError as error:
            raise ProjectError("E_RESOURCE", "WSL 시작 전 staging 파일을 확인하지 못했습니다.",
                               details={"termination_confirmed": True, "outcome_unknown": False, "not_started": True}) from error
        status = {"protocol": PROTOCOL, "run_id": run_id, "nonce": nonce, "state": "starting",
                  "termination_confirmed": False, "outcome_unknown": True}
        deadline = time.monotonic() + timeout_seconds + self.lease_seconds + 15
        cursor = -1
        try:
            # @brief start 응답 손실은 재실행하지 않고 같은 소유권의 status 재접속으로 복구한다.
            try:
                status = self._invoke("start", payload, bootstrap=True)
            except ProjectError:
                status = self.inspect(run_id, nonce)
            while True:
                if status.get("cursor", -1) != cursor:
                    cursor = status.get("cursor", -1)
                    if on_state is not None:
                        on_state(dict(status))
                if status.get("state") in TERMINAL:
                    break
                if time.monotonic() >= deadline:
                    self.cancel(run_id, nonce)
                    raise ProjectError("E_RESOURCE", "WSL guest의 종료 확인 기한을 넘었습니다.", details={"outcome_unknown": True})
                if cancel.is_set():
                    status = self.cancel(run_id, nonce)
                else:
                    status = self.heartbeat(run_id, nonce)
                time.sleep(self.poll_seconds)
        except Exception as error:
            try:
                status = self.cancel(run_id, nonce)
                recovery_deadline = time.monotonic() + self.lease_seconds + 6
                while status.get("state") not in TERMINAL and time.monotonic() < recovery_deadline:
                    time.sleep(self.poll_seconds)
                    status = self.inspect(run_id, nonce)
            except ProjectError:
                pass
            if status.get("state") not in TERMINAL:
                status = {**status, "state": "failed", "termination_confirmed": False, "outcome_unknown": True}
            status["transport_error"] = str(error)[:2048]
        if status.get("termination_confirmed") and not status.get("outcome_unknown"):
            if status["state"] in {"completed", "failed"}:
                try:
                    status = self._control("export", run_id, nonce)
                    for item in status["exported_files"]:
                        relative = PurePosixPath(item["path"])
                        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "output":
                            raise ValueError("invalid output relative path")
                        file = stage / relative
                        if not _regular(file.lstat()) or file.stat().st_size != item["bytes"] or _hash(file) != item["sha256"]:
                            raise ValueError("output hash mismatch")
                    status["output_directory"] = str(stage / "output")
                except (ProjectError, OSError, ValueError, KeyError) as error:
                    status = {**status, "state": "failed", "export_error": str(error)[:2048]}
        return status
