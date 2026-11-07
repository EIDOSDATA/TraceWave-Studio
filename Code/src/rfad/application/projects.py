"""! @brief 프로젝트 변경과 자료 처리 작업을 하나의 영속 journal로 관리한다."""

from copy import deepcopy
import json
import math
import os
from pathlib import Path, PurePosixPath
import threading
import time
from uuid import UUID, uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command, new_project, validate_project
from rfad.storage.journal import Journal

RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_DOCUMENT_BYTES = 32 * 1024
MAX_RECEIPTS = 2048
MAX_JOBS = 512
MAX_PROJECTS = 32
MAX_SNAPSHOTS = 1024
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
ASYNC_METHODS = {"project.open", "project.save", "snapshot.create"}
MUTATION_METHODS = ASYNC_METHODS | {"project.apply_command", "job.cancel"}


def _uuid(value: object) -> str:
    """! @brief 정규 UUID 문자열을 검증한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise ProjectError("E_SCHEMA", "정규 UUID 문자열이 필요합니다.") from error
    return value


def _fields(value: object, required: set, optional: set | None = None) -> dict:
    """! @brief 필수키와 지원하지 않는 필드를 검사한다."""
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise ProjectError("E_SCHEMA", "필수 필드가 없거나 지원하지 않는 필드가 있습니다.")
    return value


def _path(value: object) -> str:
    """! @brief 서비스 작업 영역의 프로젝트 하위 경로만 허용한다."""
    if type(value) is not str or len(value) > 256 or "\\" in value or ":" in value:
        raise ProjectError("E_SCHEMA", "projects/ 아래의 상대 경로를 사용하십시오.")
    parts = value.split("/")
    if len(parts) != 2 or parts[0] != "projects" or parts[1] in ("", ".", ".."):
        raise ProjectError("E_SCHEMA", "프로젝트 경로는 projects/이름 형식이어야 합니다.")
    name = parts[1]
    if name.endswith((".", " ")) or any(ord(c) < 32 or c in '<>"|?*' for c in name):
        raise ProjectError("E_SCHEMA", "지원하지 않는 프로젝트 경로 문자입니다.")
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ProjectError("E_SCHEMA", "예약된 경로 이름입니다.")
    return str(PurePosixPath(value))


class ProjectService:
    """! @brief 단일 writer와 제한된 자료 처리 worker를 소유한다."""

    def __init__(self, workspace: Path, *, clock=time.time, auto_run: bool = True, fault_hook=None):
        """! @brief 저장소를 열고 이전에 실행 중이던 작업을 명시적으로 중단 처리한다."""
        self.workspace = Path(os.path.abspath(workspace))
        self.clock = clock
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._worker_error = None
        self.journal = Journal(self.workspace, {
            "schema_version": "rfad.workspace/0.1", "epochs": {}, "projects": {},
            "paths": {}, "receipts": {}, "jobs": {}, "snapshots": {}, "commands": {},
        }, fault_hook=fault_hook)
        try:
            self._initialize()
            if auto_run:
                self._thread = threading.Thread(target=self._worker, name="rfad-project-io", daemon=False)
                self._thread.start()
                self._wake.set()
        except BaseException:
            self.journal.close()
            raise

    def __enter__(self):
        """! @brief 서비스 수명 범위를 시작한다."""
        return self

    def __exit__(self, *_):
        """! @brief worker 종료 후 파일 잠금을 해제한다."""
        self.close()

    def close(self) -> None:
        """! @brief 실행 중인 원자적 작업을 마친 뒤 종료한다."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self.journal.close()

    def _now(self) -> float:
        """! @brief 비교 가능한 유한 UTC epoch 초를 구한다."""
        value = float(self.clock())
        if not math.isfinite(value) or value < 0:
            raise ProjectError("E_SCHEMA", "유효하지 않은 서비스 시각입니다.")
        return value

    def _initialize(self, *, recover: bool = True) -> None:
        """! @brief 지원 저장소 버전과 미완료 작업을 확인한다."""
        def initialize(state):
            if state.get("schema_version") != "rfad.workspace/0.1":
                raise ProjectError("E_VERSION", "지원하지 않는 작업 영역 버전입니다.")
            now = self._now()
            if recover:
                for job in state["jobs"].values():
                    if job["state"] == "running":
                        self._event(job, "interrupted", error={"domain_code": "E_CONFLICT", "message": "이전 프로세스가 완료 전에 종료되었습니다."})
            valid = [key for key, epoch in state["epochs"].items() if epoch["expires_at"] > now]
            if not valid:
                if len(state["epochs"]) >= 128:
                    raise ProjectError("E_RESOURCE", "초기 profile의 epoch 보존 상한에 도달했습니다.")
                key = str(uuid4())
                state["epochs"][key] = {"issued_at": now, "expires_at": now + RETENTION_SECONDS}
        self.journal.transaction(initialize)

    def policy(self) -> dict:
        """! @brief 영속 epoch와 접수/보존 제한을 공개한다."""
        state = self.journal.read()
        valid = [(key, epoch) for key, epoch in state["epochs"].items() if epoch["expires_at"] > self._now()]
        if not valid:
            self._initialize(recover=False)
            return self.policy()
        key, epoch = max(valid, key=lambda item: item[1]["issued_at"])
        return {
            "status": "implemented", "mutations_enabled": True,
            "request_key_epoch": key, "epoch_expires_at": epoch["expires_at"],
            "receipt_retention_seconds": RETENTION_SECONDS,
            "authority": "workspace_journal", "max_receipts": MAX_RECEIPTS,
        }

    def _event(self, job: dict, state: str, **extra) -> None:
        """! @brief 작업 상태와 단조 증가 event를 함께 변경한다."""
        seq = len(job["events"]) + 1
        job["state"] = state
        job["events"].append({
            "seq": seq, "run_id": job["run_id"], "timestamp": self._now(),
            "state": state, "phase": state, "progress_basis": "indeterminate", **extra,
        })

    def _load(self, project: dict) -> dict:
        """! @brief 실제로 소비할 불변 파일 바이트와 문서 계약을 검증한다."""
        raw = self.journal.read_artifact(project["current"])
        try:
            document = json.loads(raw.decode("utf-8"))
            validate_project(document)
            if canonical_bytes(document) != raw:
                raise ProjectError("E_HASH", "저장된 문서의 정규 바이트가 다릅니다.")
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ProjectError("E_HASH", "저장된 프로젝트를 해석할 수 없습니다.") from error
        return document

    def _store_document(self, path: str, document: dict) -> dict:
        """! @brief 새 revision을 독립 파일로 기록하고 게시할 참조를 돌려준다."""
        validate_project(document)
        payload = canonical_bytes(document)
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise ProjectError("E_RESOURCE", "초기 profile의 프로젝트 크기 32 KiB를 초과했습니다.")
        return self.journal.put_immutable(f"{path}/revisions/{document['revision_id']}/project.json", payload)

    def _project(self, state: dict, context: dict) -> dict:
        """! @brief 명시한 프로젝트의 영속 상태를 조회한다."""
        _fields(context, {"project_id"})
        project_id = _uuid(context["project_id"])
        if project_id not in state["projects"]:
            raise ProjectError("E_SCHEMA", "등록되지 않은 프로젝트입니다.")
        return state["projects"][project_id]

    def _preflight(self, method: str, context: dict, data: dict) -> None:
        """! @brief 접수 전에 지원 필드와 선택지를 검사한다."""
        if method == "project.open":
            _fields(context, set())
            _fields(data, {"path", "open_mode"}, {"name"})
            _path(data["path"])
            if data["open_mode"] not in {"create", "open", "recover"}:
                raise ProjectError("E_UNSUPPORTED", "현재 open/create/recover만 지원합니다.")
            if data["open_mode"] == "create":
                if "name" not in data:
                    raise ProjectError("E_SCHEMA", "새 프로젝트 이름이 필요합니다.")
                new_project(data["name"])
            elif "name" in data:
                raise ProjectError("E_SCHEMA", "name은 create에서만 지정합니다.")
        elif method == "project.apply_command":
            _fields(context, {"project_id"})
            _uuid(context["project_id"])
            _fields(data, {"expected_revision", "command_id", "type", "payload"})
            _uuid(data["expected_revision"])
            _uuid(data["command_id"])
        elif method in {"project.save", "snapshot.create"}:
            _fields(context, {"project_id"})
            _uuid(context["project_id"])
            _fields(data, {"expected_revision"}, {"target"} if method == "project.save" else {"description"})
            _uuid(data["expected_revision"])
            if "target" in data:
                _path(data["target"])
            if "description" in data and (type(data["description"]) is not str or len(data["description"].encode("utf-8")) > 4096):
                raise ProjectError("E_SCHEMA", "스냅샷 설명은 UTF-8 4096 bytes 이내여야 합니다.")
        elif method == "job.cancel":
            _fields(context, set())
            _fields(data, {"job_id"}, {"reason"})
            _uuid(data["job_id"])
            if "reason" in data and (type(data["reason"]) is not str or len(data["reason"]) > 1024):
                raise ProjectError("E_SCHEMA", "취소 사유가 유효하지 않습니다.")
        else:
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 프로젝트 명령입니다.")

    def mutate(self, method: str, params: dict) -> dict:
        """! @brief 재전송 영수증과 실제 변경 또는 작업 접수를 함께 commit한다."""
        if self._worker_error is not None:
            raise ProjectError("E_RESOURCE", "자료 처리 worker가 중단되었습니다. 서비스를 다시 열고 작업 상태를 확인하십시오.")
        _fields(params, {"contract_version", "context", "input", "request_key", "request_key_epoch"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        key, epoch_id = params["request_key"], params["request_key_epoch"]
        if type(key) is not str or not 1 <= len(key) <= 128 or any(ord(c) < 32 for c in key):
            raise ProjectError("E_SCHEMA", "request_key는 1~128자의 식별자여야 합니다.")
        _uuid(epoch_id)
        canonical = {"method": method, "context": params["context"], "input": params["input"]}
        try:
            digest = canonical_hash(canonical)
        except (ValueError, TypeError, UnicodeError) as error:
            raise ProjectError("E_SCHEMA", "명령 데이터의 정규 표현이 유효하지 않습니다.") from error
        receipt_id = canonical_hash([epoch_id, key])
        def update(state):
            now = self._now()
            receipt = state["receipts"].get(receipt_id)
            if receipt is not None:
                if receipt["expires_at"] <= now:
                    raise ProjectError("E_IDEMPOTENCY_EXPIRED", "접수 기록이 만료되었습니다. 원 작업을 먼저 조회하십시오.")
                if receipt["payload_hash"] != digest:
                    raise ProjectError("E_CONFLICT", "같은 request_key를 다른 명령에 사용할 수 없습니다.")
                return deepcopy(receipt["response"])
            epoch = state["epochs"].get(epoch_id)
            if epoch is None or epoch["expires_at"] <= now:
                raise ProjectError("E_IDEMPOTENCY_EXPIRED", "알 수 없거나 만료된 발급 epoch입니다.")
            if len(state["receipts"]) >= MAX_RECEIPTS:
                raise ProjectError("E_RESOURCE", "접수 기록 보존 상한에 도달했습니다.")
            context, data = params["context"], params["input"]
            self._preflight(method, context, data)
            if method == "project.apply_command":
                response = self._apply(state, context, data)
            elif method == "job.cancel":
                response = self._cancel(state, data)
            else:
                response = self._admit(state, method, context, data)
            state["receipts"][receipt_id] = {
                "request_key": key, "epoch": epoch_id, "method": method,
                "scope": deepcopy(context) or {"path": data.get("path")},
                "expected_revision": data.get("expected_revision"), "payload_hash": digest,
                "accepted_at": now, "expires_at": now + RETENTION_SECONDS, "response": deepcopy(response),
            }
            return response
        result = self.journal.transaction(update)
        self._wake.set()
        return result

    def _apply(self, state: dict, context: dict, data: dict) -> dict:
        """! @brief revision, undo 근거와 영향 목록을 같은 상태 변경에 포함한다."""
        project = self._project(state, context)
        command_id = data["command_id"]
        if command_id in state["commands"]:
            raise ProjectError("E_CONFLICT", "이미 사용한 command_id입니다. 원 request_key로 조회하십시오.")
        if len(state["commands"]) >= 2048:
            raise ProjectError("E_RESOURCE", "초기 명령 이력 상한에 도달했습니다.")
        old = self._load(project)
        command = {key: data[key] for key in ("command_id", "type", "payload")}
        document, changed, invalidation, inverse = apply_command(old, command, data["expected_revision"])
        reference = self._store_document(project["path"], document)
        project["current"] = reference
        state["commands"][command_id] = {
            "project_id": document["project_id"], "old_revision": old["revision_id"],
            "new_revision": document["revision_id"], "inverse_command": inverse,
            "command": command, "previous_artifact": deepcopy(project["revisions"][old["revision_id"]]),
        }
        project["revisions"][document["revision_id"]] = reference
        return {"project_id": document["project_id"], "new_revision": document["revision_id"], "revision_hash": canonical_hash(document), "changed_ids": changed, "invalidation_set": invalidation}

    def _admit(self, state: dict, method: str, context: dict, data: dict) -> dict:
        """! @brief 작은 작업도 queued TaskRef로만 접수한다."""
        if len(state["jobs"]) >= MAX_JOBS or sum(job["state"] == "queued" for job in state["jobs"].values()) >= 32:
            raise ProjectError("E_RESOURCE", "작업 보존 또는 대기열 상한에 도달했습니다.")
        captured = None
        if method != "project.open":
            project = self._project(state, context)
            document = self._load(project)
            if document["revision_id"] != data["expected_revision"]:
                raise ProjectError("E_CONFLICT", "현재 revision과 요청 revision이 다릅니다.")
            if "target" in data and data["target"] != project["path"]:
                raise ProjectError("E_UNSUPPORTED", "다른 경로로 저장은 copy/export 구현 후 지원합니다.")
            captured = deepcopy(project["current"])
        job_id = str(uuid4())
        job = {"job_id": job_id, "run_id": str(uuid4()), "kind": "data_processing", "operation_method": method, "context": deepcopy(context), "input": deepcopy(data), "captured": captured, "events": []}
        self._event(job, "queued")
        state["jobs"][job_id] = job
        return {"job_id": job_id, "state": "queued", "events_cursor": 1}

    def _cancel(self, state: dict, data: dict) -> dict:
        """! @brief 미시작 자료 처리 작업을 제거하고 이미 확정된 terminal은 보존한다."""
        job = state["jobs"].get(data["job_id"])
        if job is None:
            raise ProjectError("E_SCHEMA", "작업을 찾을 수 없습니다.")
        if job["state"] not in TERMINAL:
            self._event(job, "cancel_requested", reason=data.get("reason", ""))
            self._event(job, "cancelled")
        return {"job_id": job["job_id"], "state": job["state"], "events_cursor": len(job["events"])}

    def status(self, params: dict) -> dict:
        """! @brief 영속 상태와 마지막 cursor 이후 event를 반환한다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        _fields(params["context"], set())
        data = _fields(params["input"], {"job_id"}, {"cursor"})
        _uuid(data["job_id"])
        cursor = data.get("cursor", 0)
        if type(cursor) is not int or cursor < 0:
            raise ProjectError("E_SCHEMA", "cursor는 음수가 아닌 정수여야 합니다.")
        state = self.journal.read()
        job = state["jobs"].get(data["job_id"])
        if job is None or cursor > len(job["events"]):
            raise ProjectError("E_SCHEMA", "작업 또는 cursor가 유효하지 않습니다.")
        return {"job_id": job["job_id"], "state": job["state"], "events_cursor": len(job["events"]), "events": deepcopy(job["events"][cursor:]), "artifacts": []}

    def run_next(self) -> bool:
        """! @brief queued 작업 하나를 실제 처리하고 terminal 결과를 영속화한다."""
        def begin(state):
            for job in state["jobs"].values():
                if job["state"] == "queued":
                    self._event(job, "running")
                    return job["job_id"]
            return None
        if not any(job["state"] == "queued" for job in self.journal.read()["jobs"].values()):
            return False
        job_id = self.journal.transaction(begin)
        if job_id is None:
            return False
        try:
            def finish(state):
                job = state["jobs"][job_id]
                if job["state"] != "running":
                    return
                result = self._execute(state, job)
                self._event(job, "completed", operation_result=result)
            self.journal.transaction(finish)
        except (ProjectError, OSError) as error:
            def fail(state):
                job = state["jobs"][job_id]
                if job["state"] not in TERMINAL:
                    diagnostic = error.diagnostic() if isinstance(error, ProjectError) else ProjectError("E_DISK", str(error)).diagnostic()
                    self._event(job, "failed", error=diagnostic)
            self.journal.transaction(fail)
        return True

    def _execute(self, state: dict, job: dict) -> dict:
        """! @brief 불변 산출물을 준비한 뒤 결과 참조만 journal에 게시한다."""
        method, data = job["operation_method"], job["input"]
        if method == "project.open":
            path = _path(data["path"])
            registered = next((existing for existing in state["paths"] if existing.casefold() == path.casefold()), None)
            if data["open_mode"] == "create":
                if registered is not None or (self.workspace / path).exists():
                    raise ProjectError("E_CONFLICT", "기존 프로젝트 경로를 덮어쓸 수 없습니다.")
                if len(state["projects"]) >= MAX_PROJECTS:
                    raise ProjectError("E_RESOURCE", "초기 프로젝트 수 상한에 도달했습니다.")
                document = new_project(data["name"])
                reference = self._store_document(path, document)
                project = {"path": path, "current": reference, "saved": deepcopy(reference), "revisions": {document["revision_id"]: reference}}
                state["projects"][document["project_id"]] = project
                state["paths"][path] = document["project_id"]
            else:
                if registered is None or registered != path:
                    raise ProjectError("E_SCHEMA", "등록된 정확한 프로젝트 경로가 필요합니다.")
                project = state["projects"][state["paths"][path]]
                document = self._load(project)
            return {"project_id": document["project_id"], "revision_id": document["revision_id"], "revision_hash": canonical_hash(document), "document": document, "saved_revision": self._saved_revision(project), "diagnostics": []}
        project = self._project(state, job["context"])
        raw = self.journal.read_artifact(job["captured"])
        document = json.loads(raw.decode("utf-8"))
        validate_project(document)
        if method == "project.save":
            current = self._load(project)
            if current["revision_id"] != document["revision_id"]:
                raise ProjectError("E_CONFLICT", "접수 후 설계가 바뀌어 저장 기준점을 변경하지 않았습니다.")
            project["saved"] = deepcopy(job["captured"])
            return {"saved_revision": document["revision_id"], "checksum": job["captured"]["sha256"], "artifact": deepcopy(job["captured"])}
        if len(state["snapshots"]) >= MAX_SNAPSHOTS:
            raise ProjectError("E_RESOURCE", "스냅샷 보존 상한에 도달했습니다.")
        snapshot_id = str(uuid4())
        reference = self.journal.put_immutable(f"{project['path']}/snapshots/{document['revision_id']}/{snapshot_id}/project.json", raw)
        snapshot = {"snapshot_id": snapshot_id, "project_id": document["project_id"], "revision_id": document["revision_id"], "schema_version": document["schema_version"], "canonical_version": "rfad.canonical/1.0", "content_hash": canonical_hash(document), "sealed_at": self._now(), "description": data.get("description", ""), "artifact": reference, "validation_state": "not_evaluated"}
        state["snapshots"][snapshot_id] = snapshot
        return deepcopy(snapshot)

    def _saved_revision(self, project: dict) -> str:
        """! @brief 저장 기준점 파일의 무결성을 확인한다."""
        return self._load({"current": project["saved"]})["revision_id"]

    def _worker(self) -> None:
        """! @brief 요청이 있을 때만 작은 파일 작업을 순차 처리한다."""
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            try:
                while not self._stop.is_set() and self.run_next():
                    pass
            except Exception as error:
                self._worker_error = error
                return
