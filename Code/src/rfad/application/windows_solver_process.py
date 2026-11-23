"""! @brief Windows openEMS 작업을 서비스 소유 Job Object 안에서 실행한다."""

import json
from pathlib import Path
import re
from uuid import UUID

from rfad.application.canonical import canonical_bytes
from rfad.application.native_process import _WindowsJob, run_native
from rfad.domain.errors import ProjectError


PROTOCOL = "rfad.windows-openems-process/0.1"


class WindowsSolverProcess:
    """! @brief 봉인된 worker만 시작하고 실제 자식 프로세스 종료를 확인한다."""

    def __init__(self, python):
        self.python = Path(python).resolve(strict=True)

    def identity(self):
        """! @brief 서비스가 고른 고정 Python과 감독 방식을 작업에 기록한다."""
        return {"protocol": PROTOCOL, "python": str(self.python), "ownership": "windows_kill_on_job_close"}

    @staticmethod
    def _name(run_id, nonce):
        """! @brief 세션이 바뀌어도 실행 ID와 비밀 nonce가 일치하는 Job을 찾는다."""
        if str(UUID(run_id)) != run_id or not re.fullmatch(r"[0-9a-f]{32,128}", nonce):
            raise ProjectError("E_SCHEMA", "Windows 해석 실행 식별자가 올바르지 않습니다.")
        return "Global\\TraceWaveStudio-openEMS-" + run_id + "-" + nonce

    def _control(self, run_id, nonce, terminate):
        """! @brief 재실행 없이 이전에 봉인한 실행의 커널 Job만 검사한다."""
        name = self._name(run_id, nonce)
        try:
            job = _WindowsJob(name, existing=True)
        except OSError as error:
            if error.winerror == 2:
                return {"state": "cancelled", "termination_confirmed": True, "outcome_unknown": False}
            raise ProjectError("E_RESOURCE", "Windows 해석 Job의 종료를 확인할 수 없습니다.") from error
        try:
            active = job.active()
            if active and terminate:
                job.terminate()
                active = job.active()
            return {"state": "active" if active else "cancelled", "termination_confirmed": not active,
                    "outcome_unknown": active}
        finally:
            job.close()

    def inspect(self, run_id, nonce):
        return self._control(run_id, nonce, False)

    def cancel(self, run_id, nonce):
        return self._control(run_id, nonce, True)

    def execute(self, stage, *, run_id, nonce, cancel, timeout_seconds, on_state=None,
                max_output_bytes=4 * 1024 * 1024, max_file_bytes=64 * 1024 * 1024,
                max_directory_bytes=128 * 1024 * 1024, max_files=128):
        """! @brief worker gate 앞에서 소유권을 고정하고 단 한 번 실행한다."""
        if cancel.is_set():
            return {"state": "cancelled", "termination_confirmed": True, "outcome_unknown": False, "not_started": True}
        worker_pid = None
        last_progress = None

        def started(value):
            nonlocal worker_pid
            worker_pid = value["pid"]

        def progress():
            nonlocal last_progress
            if on_state is None:
                return
            try:
                with (stage / "progress.json").open("rb") as stream:
                    data = stream.read(8193)
            except (FileNotFoundError, PermissionError):
                return
            if len(data) > 8192:
                raise ProjectError("E_RESOURCE", "Windows 해석 진행 기록이 상한을 넘었습니다.")
            if data != last_progress:
                last_progress = data
                on_state({**json.loads(data), "state": "active", "worker_pid": worker_pid})

        # @brief 같은 worker의 기존 gate 스키마를 양쪽 플랫폼에서 읽는다.
        gate = canonical_bytes({"schema": "rfad.wsl-start/0.1", "run_id": run_id, "nonce": nonce}) + b"\n"
        process = run_native([str(self.python), "-I", "-B", "-X", "utf8", "tools/openems_worker.py",
                              "--request", "request.json"], stage, gate, cancel, timeout_seconds,
                             max_output_bytes, started, output_directory=stage / "output",
                             max_file_bytes=max_file_bytes, max_directory_bytes=max_directory_bytes,
                             max_files=max_files, windows_job_name=self._name(run_id, nonce), on_poll=progress)
        state = process["termination"]
        if state == "completed" and process["returncode"]:
            state = "failed"
        return {**process, "protocol": PROTOCOL, "run_id": run_id, "nonce": nonce, "state": state,
                "termination_confirmed": True, "outcome_unknown": False}
