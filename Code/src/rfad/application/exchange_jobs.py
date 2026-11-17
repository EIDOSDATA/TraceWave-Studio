"""! @brief 별도 도면 worker의 단일 슬롯, 취소와 원자 완료 게시를 관리한다."""
from copy import deepcopy
import hashlib
import json
import threading

from rfad.application import exchange_contract as contract
from rfad.application.canonical import canonical_bytes
from rfad.application.exchange_artifacts import seal
from rfad.application.native_process import run_native
from rfad.application.source_bundle import verify_stage
from rfad.domain.errors import ProjectError
from rfad.storage.sealed_files import copy as copy_sealed


class ExchangeCoordinator:
    """! @brief 호스트 저장/편집 worker와 분리하여 유한 출력 작업만 실행한다."""
    def __init__(self, service, runtime):
        """! @brief 실행 설정과 소유 스레드 상태를 초기화한다."""
        self.service, self.runtime = service, runtime
        self.wake, self.stop, self.cancel = threading.Event(), threading.Event(), threading.Event()
        self.thread, self.error = None, None
        self.lock = threading.Lock()

    def start(self):
        """! @brief 구성된 별도 Python이 있을 때만 실행 스레드를 시작한다."""
        if self.runtime is not None:
            self.thread = threading.Thread(target=self._loop, name="rfad-exchange", daemon=False)
            self.thread.start()
            self.wake.set()

    def close(self):
        """! @brief 소유 프로세스 종료를 확인한 뒤 저장소를 해제할 수 있게 한다."""
        self.stop.set()
        self.cancel.set()
        self.wake.set()
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join()
        self.thread = None

    def cancel_job(self, job, reason):
        """! @brief 실제 종료 전에 실행 중 작업을 취소 완료로 표시하지 않는다."""
        if job["state"] == "queued":
            self.service._event(job, "cancel_requested", reason=reason)
            job["exchange"]["resource_reserved"] = False
            self.service._event(job, "cancelled")
        elif job["state"] == "running":
            self.service._event(job, "cancel_requested", reason=reason)
            self.cancel.set()

    def run_next(self):
        """! @brief journal 잠금 밖에서 하나의 소유 작업만 계산한다."""
        if self.runtime is None or not self.lock.acquire(blocking=False):
            return False
        try:
            if not any("exchange" in job and job["state"] == "queued" for job in self.service.journal.read()["jobs"].values()):
                return False
            self.cancel.clear()
            def begin(state):
                for job in state["jobs"].values():
                    if "exchange" in job and job["state"] == "queued":
                        self.service._event(job, "running")
                        return deepcopy(job)
                return None
            job = self.service.journal.transaction(begin)
            if job is None:
                return False
            try:
                returned, process, output = self._execute(job)
                if process["termination"] != "completed":
                    self._finish(job, process=process)
                elif process["returncode"] != 0:
                    error = returned.get("error", {})
                    raise ProjectError(error.get("code", "E_GEOMETRY"), error.get("message_ko", "출력 worker가 실패했습니다."), details=error.get("details", {}))
                elif self.cancel.is_set() or self.stop.is_set():
                    self._finish(job, process=process)
                else:
                    value = seal(self.service.journal, job, returned.get("package", returned), output)
                    self._finish(job, process=process, result=value)
            except Exception as error:
                diagnostic = error if isinstance(error, ProjectError) else ProjectError("E_DISK" if isinstance(error, OSError) else "E_GEOMETRY", str(error)[:2048])
                self._finish(job, error=diagnostic)
            return True
        finally:
            self.lock.release()

    def _execute(self, job):
        """! @brief 봉인된 소스/입력/글꼴을 복제하고 소유 Windows Job으로 실행한다."""
        native = job["exchange"]
        self.runtime.verify(native["runtime"])
        journal = self.service.journal
        stage = journal._safe_path("exchange-staging/" + job["run_id"])
        stage.mkdir(parents=True, exist_ok=False)
        for name, key in (("input.json", "input"), ("runtime.json", "runtime_manifest")):
            (stage / name).write_bytes(journal.read_artifact(native[key]))
        sources = json.loads(journal.read_artifact(native["source"]))
        for relative, text in sources.items():
            if not (relative.startswith("src/rfad/") or relative == "tools/exchange_worker.py") or not relative.endswith(".py"):
                raise ProjectError("E_HASH", "출력 소스의 고정 경로가 유효하지 않습니다.")
            target = journal._safe_path("exchange-staging/" + job["run_id"] + "/" + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(text.encode("utf-8"))
        verify_stage(stage, native["runtime"]["source_bundle"], native["runtime"]["code_files"])
        if self.runtime.font_bytes is not None:
            (stage / "fonts").mkdir()
            (stage / "fonts/primary.ttf").write_bytes(self.runtime.font_bytes)
        request = {"schema": "rfad.exchange-worker/0.1", "run_id": job["run_id"], "nonce": native["nonce"],
                   "input_sha256": native["input"]["sha256"], "runtime": native["runtime"], "operation": native["operation"]}
        if native["operation"] == "verify":
            from rfad.application.exchange_service import manifest_reference
            original = journal.read()["jobs"][native["original_job_id"]]
            reference = manifest_reference(original)
            if reference["sha256"] != job["input"]["manifest_sha256"] or original["context"] != job["context"]:
                raise ProjectError("E_HASH", "재검수 원본의 소유권/hash가 변경되었습니다.")
            manifest = json.loads(journal.read_artifact(reference))
            if manifest["snapshot"] != job["snapshot"] or manifest["runtime"] != original["exchange"]["runtime"]:
                raise ProjectError("E_HASH", "재검수 원본의 스냅샷/환경이 다릅니다.")
            package_raw = canonical_bytes(manifest["worker_package"])
            (stage / "verification-package.json").write_bytes(package_raw)
            request["package_sha256"] = hashlib.sha256(package_raw).hexdigest()
            target = stage / "original"
            target.mkdir()
            for item in manifest["worker_package"]["files"]:
                refs = [ref for ref in manifest["artifacts"] if ref["uri"].endswith("/" + item["path"])]
                if len(refs) != 1 or refs[0]["sha256"] != item["sha256"] or refs[0]["bytes"] != item["bytes"]:
                    raise ProjectError("E_HASH", "재검수 원본 파일 대응이 다릅니다.")
                copy_sealed(journal._safe_path(refs[0]["uri"]), target / item["path"], refs[0])
        def started(metadata):
            def remember(state):
                current = state["jobs"][job["job_id"]]
                if current["exchange"]["nonce"] != native["nonce"] or current["state"] not in ("running", "cancel_requested"):
                    raise ProjectError("E_CONFLICT", "출력 프로세스의 소유 상태가 변경되었습니다.")
                current["exchange"]["process"] = metadata
                if current["state"] == "cancel_requested" or self.stop.is_set():
                    self.cancel.set()
            journal.transaction(remember)
        process = run_native([str(self.runtime.python), "-I", "-B", "-X", "utf8", str(stage / "tools/exchange_worker.py")],
            cwd=stage, request_bytes=canonical_bytes(request) + b"\n", cancel=self.cancel, timeout_seconds=native["timeout_seconds"],
            max_output_bytes=1024 * 1024, on_started=started, output_directory=stage / "output",
            max_file_bytes=contract.MAX_FILE_BYTES, max_directory_bytes=contract.MAX_PACKAGE_BYTES, max_files=contract.MAX_FILES)
        (stage / "process.json").write_bytes(canonical_bytes(process))
        if process["termination"] != "completed":
            return {}, process, stage / "output"
        with (stage / "result.json").open("rb") as stream:
            raw = stream.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ProjectError("E_RESOURCE", "출력 worker 응답 상한을 초과했습니다.")
        returned = json.loads(raw)
        if (returned.get("schema"), returned.get("run_id"), returned.get("nonce"), returned.get("input_sha256")) != (
                "rfad.exchange-worker-result/0.1", job["run_id"], native["nonce"], native["input"]["sha256"]):
            raise ProjectError("E_HASH", "출력 worker 응답이 소유한 실행과 다릅니다.")
        return returned, process, stage / "output"

    def _finish(self, original, *, result=None, process=None, error=None):
        """! @brief 완료 근거 없이 취소/중단 상태를 성공으로 승격하지 않는다."""
        def publish(state):
            job = state["jobs"][original["job_id"]]
            if job["exchange"]["nonce"] != original["exchange"]["nonce"] or job["state"] not in ("running", "cancel_requested"):
                return
            unknown = error is not None and error.details.get("outcome_unknown") is True
            job["exchange"]["resource_reserved"] = unknown
            if unknown:
                self.service._event(job, "interrupted", outcome_unknown=True, error=error.diagnostic())
            elif job["state"] == "cancel_requested":
                self.service._event(job, "cancelled")
            elif self.stop.is_set():
                self.service._event(job, "interrupted", outcome_unknown=False, reason="서비스 종료로 출력 worker를 회수했습니다.")
            elif error is not None:
                self.service._event(job, "failed", error=error.diagnostic())
            elif result is None:
                self.service._event(job, "failed", error=ProjectError("E_RESOURCE", "출력 시간/파일 상한으로 중단됐습니다.", details={"termination": process["termination"]}).diagnostic())
            else:
                job["artifacts"] = result["artifacts"]
                self.service._event(job, "completed", operation_result=result)
        self.service.journal.transaction(publish)

    def _loop(self):
        """! @brief 출력 대기만 소비하고 예외 발생 시 자동 재접수를 멈춘다."""
        while not self.stop.is_set():
            self.wake.wait()
            self.wake.clear()
            try:
                while not self.stop.is_set() and self.run_next():
                    pass
            except Exception as error:
                self.error = error
                return
