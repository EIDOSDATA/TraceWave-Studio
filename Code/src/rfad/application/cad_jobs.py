"""! @brief CAD 작업의 접수, 격리 실행과 취소/게시 수명을 조정한다."""

from copy import deepcopy
import json
from pathlib import Path
import threading
from uuid import UUID, uuid4

from rfad.application.cad import PROFILE, build_cad_input
from rfad.application.canonical import canonical_bytes
from rfad.application.cad_runtime import CODE_ROOT, CadRuntime, file_hash
from rfad.application.cad_artifacts import MAX_FILE_BYTES, MAX_PACKAGE_BYTES, seal_cad_outputs
from rfad.application.native_process import run_native
from rfad.domain.errors import ProjectError

CAD_METHODS = {"geometry.build", "export.build"}
MAX_RESULT_BYTES = 256 * 1024


class CadCoordinator:
    """! @brief 자료 처리 스레드와 독립된 단일 CAD 슬롯을 관리한다."""

    def __init__(self, service, runtime: CadRuntime | None):
        """! @brief native 의존성을 import하지 않고 실행 설정만 보관한다."""
        self.service = service
        self.runtime = runtime
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.thread = None
        self.error = None
        self._run_lock = threading.Lock()

    def start(self) -> None:
        """! @brief 구성된 CAD 환경만 별도 조정 스레드로 연결한다."""
        if self.runtime is not None:
            self.thread = threading.Thread(target=self._loop, name="rfad-cad-coordinator", daemon=False)
            self.thread.start()
            self.wake.set()

    def close(self) -> None:
        """! @brief 소유 worker의 종료와 결과 상태 처리를 마친 뒤 반환한다."""
        self.stop.set()
        self.cancel.set()
        self.wake.set()
        if self.thread is not None:
            if self.thread.ident is not None:
                self.thread.join()
            self.thread = None

    @staticmethod
    def validate_input(method: str, context: dict, data: dict) -> None:
        """! @brief 명시적 snapshot와 지원하는 출력 profile만 접수한다."""
        keys = {"snapshot", "profile", "projection_kind" if method == "geometry.build" else "format"}
        if type(context) is not dict or set(context) != {"project_id"} or type(data) is not dict or set(data) != keys:
            raise ProjectError("E_SCHEMA", "CAD 요청의 필드가 유효하지 않습니다.")
        try:
            if str(UUID(context["project_id"])) != context["project_id"]:
                raise ValueError()
            snapshot = data["snapshot"]
            if type(snapshot) is not dict or set(snapshot) != {"snapshot_id", "content_hash"} or str(UUID(snapshot["snapshot_id"])) != snapshot["snapshot_id"]:
                raise ValueError()
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise ProjectError("E_SCHEMA", "정규 프로젝트 및 스냅샷 참조가 필요합니다.") from error
        digest = snapshot["content_hash"]
        if type(digest) is not str or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ProjectError("E_HASH", "스냅샷 SHA256 참조가 유효하지 않습니다.")
        if data["profile"] != PROFILE or data.get("projection_kind", "brep") != "brep" or data.get("format", "step") != "step":
            raise ProjectError("E_UNSUPPORTED", "현재 CAD profile은 B-rep와 AP242 STEP 기하 출력만 지원합니다.")

    def _input(self, state: dict, context: dict, data: dict) -> tuple[dict, dict]:
        """! @brief 등록된 불변 스냅샷 바이트를 재검증하고 mm 입력을 만든다."""
        self.service._project(state, context)
        snapshot = state["snapshots"].get(data["snapshot"]["snapshot_id"])
        if snapshot is None or snapshot["project_id"] != context["project_id"] or snapshot["content_hash"] != data["snapshot"]["content_hash"]:
            raise ProjectError("E_HASH", "등록된 스냅샷과 요청한 프로젝트 또는 hash가 다릅니다.")
        document = self.service._load({"current": snapshot["artifact"]})
        return deepcopy(snapshot), build_cad_input(document, snapshot, data["profile"])

    def preview(self, params: dict) -> dict:
        """! @brief 출력에 소비할 범위와 지원 제한을 저장 변경 없이 공개한다."""
        if type(params) is not dict or set(params) != {"contract_version", "context", "input"} or params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_SCHEMA", "출력 미리보기 요청이 유효하지 않습니다.")
        self.validate_input("export.build", params["context"], params["input"])
        snapshot, projection = self._input(self.service.journal.read(), params["context"], params["input"])
        return {"profile": PROFILE, "status": "preview_only", "snapshot": snapshot,
                "layer_count": len(projection["layers"]), "shape_count": len(projection["shapes"]),
                "omissions": projection.get("omissions", []), "runtime_configured": self.runtime is not None,
                "manufacturing_verified": False, "physics_verified": False}

    def admit(self, state: dict, method: str, context: dict, data: dict) -> dict:
        """! @brief 입력과 실행 식별을 봉인하고 하나의 native 예약을 원자 접수한다."""
        if self.runtime is None:
            raise ProjectError("E_UNSUPPORTED", "서비스 실행 시 --cad-python으로 격리 CAD 환경을 지정하십시오.")
        if self.error is not None or any(job.get("cad", {}).get("resource_reserved") for job in state["jobs"].values()):
            raise ProjectError("E_RESOURCE", "CAD 슬롯이 사용 중이거나 이전 실행의 종료 확인이 필요합니다.")
        if len(state["jobs"]) >= 512:
            raise ProjectError("E_RESOURCE", "작업 보존 상한에 도달했습니다.")
        snapshot, projection = self._input(state, context, data)
        job_id, run_id, nonce = str(uuid4()), str(uuid4()), str(uuid4())
        projection["run_id"] = run_id
        payload = canonical_bytes(projection)
        if len(payload) > 128 * 1024:
            raise ProjectError("E_RESOURCE", "CAD 입력은 최대 128 KiB입니다.")
        base = state["projects"][context["project_id"]]["path"] + "/cad-inputs/" + run_id
        reference = self.service.journal.put_immutable(base + "/input.json", payload)
        runtime_ref = self.service.journal.put_immutable(base + "/runtime.json", self.runtime.manifest_bytes)
        source_ref = self.service.journal.put_immutable(base + "/source.json", self.runtime.source_bytes)
        entry_ref = self.service.journal.put_immutable(base + "/worker.py", self.runtime.entry_bytes)
        job = {"job_id": job_id, "run_id": run_id, "kind": "cad_build" if method == "geometry.build" else "export",
               "operation_method": method, "context": deepcopy(context), "input": deepcopy(data), "events": [],
               "captured": deepcopy(snapshot["artifact"]), "snapshot": snapshot,
               "cad": {"nonce": nonce, "input": reference, "runtime_manifest": runtime_ref,
                       "source": source_ref, "entry": entry_ref, "timeout_seconds": self.runtime.timeout_seconds,
                       "runtime": deepcopy(self.runtime.identity), "resource_reserved": True}}
        self.service._event(job, "queued")
        state["jobs"][job_id] = job
        return {"job_id": job_id, "state": "queued", "events_cursor": 1}

    def admit_preview(self, state: dict, context: dict, data: dict) -> dict:
        """! @brief 짧은 출력 미리보기도 승인 API의 비동기 TaskRef로 접수한다."""
        snapshot, projection = self._input(state, context, data)
        job_id = str(uuid4())
        result = {"profile": PROFILE, "status": "preview_only", "snapshot": snapshot,
                  "layer_count": len(projection["layers"]), "shape_count": len(projection["shapes"]),
                  "omissions": projection.get("omissions", []), "runtime_configured": self.runtime is not None,
                  "manufacturing_verified": False, "physics_verified": False}
        job = {"job_id": job_id, "run_id": str(uuid4()), "kind": "export", "operation_method": "export.preview",
               "context": deepcopy(context), "input": deepcopy(data), "captured": deepcopy(snapshot["artifact"]),
               "preview_result": result, "events": []}
        self.service._event(job, "queued")
        state["jobs"][job_id] = job
        return {"job_id": job_id, "state": "queued", "events_cursor": 1}

    def cancel_job(self, job: dict, reason: str) -> None:
        """! @brief 실행 작업은 취소 의도만 기록하고 종료 확인을 기다린다."""
        if job["state"] == "queued":
            self.service._event(job, "cancel_requested", reason=reason)
            job["cad"]["resource_reserved"] = False
            self.service._event(job, "cancelled")
        elif job["state"] == "running":
            self.service._event(job, "cancel_requested", reason=reason)
            self.cancel.set()

    def run_next(self) -> bool:
        """! @brief 긴 native 계산과 파일 봉인을 journal transaction 밖에서 수행한다."""
        if self.runtime is None or not self._run_lock.acquire(blocking=False):
            return False
        try:
            return self._run_one()
        finally:
            self._run_lock.release()

    def _run_one(self) -> bool:
        """! @brief 실행 nonce를 통해 접수, 프로세스 시작 및 게시를 연결한다."""
        self.cancel.clear()
        def begin(state):
            for job in state["jobs"].values():
                if "cad" in job and job["state"] == "queued":
                    self.service._event(job, "running")
                    return deepcopy(job)
            return None
        if not any("cad" in job and job["state"] == "queued" for job in self.service.journal.read()["jobs"].values()):
            return False
        job = self.service.journal.transaction(begin)
        if job is None:
            return False
        try:
            package, process, output = self._execute(job)
            if process["termination"] != "completed":
                self._finish(job, process=process)
                return True
            if process["returncode"] != 0:
                error = package.get("error", {})
                raise ProjectError(error.get("code", "E_GEOMETRY"), str(error.get("message_ko", "CAD worker가 실패했습니다."))[:2048], details=error.get("details", {}))
            artifacts = self._seal(job, package, output)
            self._finish(job, artifacts=artifacts, package=package, process=process)
        except Exception as error:
            diagnostic = error if isinstance(error, ProjectError) else ProjectError("E_DISK" if isinstance(error, OSError) else "E_GEOMETRY", str(error)[:2048])
            self._finish(job, error=diagnostic)
        return True

    def _execute(self, job: dict) -> tuple[dict, dict, Path]:
        """! @brief 호스트가 정한 진입점에 입력 확인용 작은 시작 메시지만 보낸다."""
        self.runtime.verify(job["cad"]["runtime"])
        stage = self.service.journal._safe_path("cad-staging/" + job["run_id"])
        stage.mkdir(parents=True, exist_ok=False)
        (stage / "input.json").write_bytes(self.service.journal.read_artifact(job["cad"]["input"]))
        (stage / "runtime.json").write_bytes(self.service.journal.read_artifact(job["cad"]["runtime_manifest"]))
        (stage / "worker.py").write_bytes(self.service.journal.read_artifact(job["cad"]["entry"]))
        sources = json.loads(self.service.journal.read_artifact(job["cad"]["source"]))
        for relative, source in sources.items():
            if not relative.startswith("src/rfad/") or not relative.endswith(".py"):
                raise ProjectError("E_HASH", "CAD 소스 묶음의 경로가 유효하지 않습니다.")
            target = self.service.journal._safe_path("cad-staging/" + job["run_id"] + "/" + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8", newline="")
        request = {"schema": "rfad.cad-worker/0.1", "run_id": job["run_id"], "nonce": job["cad"]["nonce"],
                   "input_sha256": job["cad"]["input"]["sha256"], "runtime": job["cad"]["runtime"]}
        def started(metadata):
            def update(state):
                active = state["jobs"][job["job_id"]]
                if active["cad"]["nonce"] != job["cad"]["nonce"] or active["state"] not in {"running", "cancel_requested"}:
                    raise ProjectError("E_CONFLICT", "CAD 실행의 소유권 또는 상태가 바뀌었습니다.")
                active["cad"]["process"] = metadata
                if active["state"] == "cancel_requested" or self.stop.is_set():
                    self.cancel.set()
            self.service.journal.transaction(update)
        process = run_native([str(self.runtime.python), "-I", "-B", "-X", "utf8", str(stage / "worker.py")],
                             cwd=stage, request_bytes=canonical_bytes(request) + b"\n", cancel=self.cancel,
                             timeout_seconds=job["cad"]["timeout_seconds"], max_output_bytes=1024 * 1024, on_started=started,
                             output_directory=stage / "output", max_file_bytes=MAX_FILE_BYTES,
                             max_directory_bytes=MAX_PACKAGE_BYTES)
        (stage / "process.json").write_bytes(canonical_bytes(process))
        output = stage / "output"
        if process["termination"] != "completed":
            return {}, process, output
        path = self.service.journal._safe_path("cad-staging/" + job["run_id"] + "/result.json")
        with path.open("rb") as stream:
            raw = stream.read(MAX_RESULT_BYTES + 1)
        if len(raw) > MAX_RESULT_BYTES:
            raise ProjectError("E_RESOURCE", "CAD 결과 메타데이터가 상한을 초과했습니다.")
        result = json.loads(raw)
        if result.get("schema") != "rfad.cad-worker-result/0.1" or result.get("run_id") != job["run_id"] or result.get("nonce") != job["cad"]["nonce"] or result.get("input_sha256") != request["input_sha256"]:
            raise ProjectError("E_HASH", "CAD 결과가 현재 실행 nonce 또는 입력 hash와 다릅니다.")
        return result.get("package", result), process, output

    def _seal(self, job: dict, package: dict, output: Path) -> list[dict]:
        """! @brief 검증된 CAD 파일을 게시 전 불변 저장소로 봉인한다."""
        return seal_cad_outputs(self.service.journal, job, package, output)


    def _finish(self, original: dict, *, artifacts=None, package=None, process=None, error=None) -> None:
        """! @brief 늦은 실행 결과를 거부하고 상태와 artifact 참조를 함께 게시한다."""
        def publish(state):
            job = state["jobs"][original["job_id"]]
            if job["cad"]["nonce"] != original["cad"]["nonce"] or job["state"] not in {"running", "cancel_requested"}:
                return
            unknown = error is not None and error.details.get("outcome_unknown") is True
            job["cad"]["resource_reserved"] = unknown
            if unknown:
                self.service._event(job, "interrupted", error=error.diagnostic(), outcome_unknown=True)
            elif job["state"] == "cancel_requested":
                self.service._event(job, "cancelled")
            elif self.stop.is_set():
                self.service._event(job, "interrupted", outcome_unknown=False, reason="서비스가 소유 worker를 종료했습니다.")
            elif error is not None:
                self.service._event(job, "failed", error=error.diagnostic())
            elif process["termination"] != "completed":
                message = "CAD 시간 제한을 초과했습니다." if process["termination"] == "timeout" else "CAD 출력 제한 또는 실행 취소로 종료했습니다."
                self.service._event(job, "failed", error=ProjectError("E_RESOURCE", message).diagnostic())
            else:
                result = {"snapshot": job["snapshot"], "profile": PROFILE, "status": "generated_unverified",
                          "artifacts": artifacts, "step_schema": package["step_schema"],
                          "body_count": package["body_count"], "solid_count": package["solid_count"],
                          "kernel_independent": False, "physics_verified": False, "manufacturing_verified": False}
                job["artifacts"] = artifacts
                self.service._event(job, "completed", operation_result=result)
        self.service.journal.transaction(publish)

    def _loop(self) -> None:
        """! @brief CAD 대기만 소비하여 저장 및 편집 worker와 잠금을 공유하지 않는다."""
        while not self.stop.is_set():
            self.wake.wait()
            self.wake.clear()
            try:
                while not self.stop.is_set() and self.run_next():
                    pass
            except Exception as error:
                self.error = error
                return
