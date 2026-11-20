"""! @brief 인계/편집 복원 묶음의 발행 참조와 소유 조회를 공유한다."""

import base64
from copy import deepcopy
from uuid import UUID, uuid5

from rfad.application import handoff_archive as codec
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.network_records import reference
from rfad.application.project_contract import _fields, _uuid
from rfad.application.result_sources import owned_reference
from rfad.domain.network_library import digest
from rfad.storage.journal import MAX_ARTIFACT_BYTES, MAX_STATE_BYTES
from rfad.storage.sealed_files import MAX_FILE_BYTES


MAX_PACKAGES = 32
CHUNK_BYTES = 128 * 1024


def validate(suffix, data):
    """! @brief 조회 메서드에는 발행 ID와 명시 해시/위치만 허용한다."""
    if suffix == "list":
        _fields(data, set())
    elif suffix == "read":
        _fields(data, {"package_id", "sha256", "offset"})
        _uuid(data["package_id"])
        digest(data["sha256"], "sha256")
        offset = data["offset"]
        if type(offset) is not int or offset < 0 or offset % CHUNK_BYTES:
            codec.fail("인계 파일 읽기는 청크 시작 위치를 사용하십시오.", "E_RESOURCE")
    elif suffix == "receipt":
        _fields(data, {"request_key", "request_key_epoch"})
        _uuid(data["request_key_epoch"])
        key = data["request_key"]
        if type(key) is not str or not 1 <= len(key) <= 128 or any(ord(char) < 32 for char in key):
            codec.fail("원래 요청의 영수증 키를 사용하십시오.")
    else:
        codec.fail("지원하지 않는 발행 메서드입니다.", "E_UNSUPPORTED")


def publish(service, state, plan, review, namespace, file_name, raw_factory):
    """! @brief 소유자/검토별 한 파일을 봉인하고 기존 동일 입력은 재사용한다."""
    identity = str(uuid5(UUID(plan["project_id"]), namespace + ":" + review))
    stored = state.get("handoff_packages", {})
    if identity in stored:
        existing = stored[identity]
        service.journal.verify_file(existing["artifact"])
        return deepcopy(existing)
    if len(stored) >= MAX_PACKAGES:
        codec.fail("인계 묶음 보존 상한 32개에 도달했습니다.", "E_RESOURCE")
    raw = raw_factory()
    limit = MAX_FILE_BYTES if namespace == "archive" else MAX_ARTIFACT_BYTES
    if len(raw) > limit:
        codec.fail(f"인계 ZIP의 실제 크기가 {limit // 1024**2} MiB를 초과했습니다.", "E_RESOURCE")
    path = plan["project_path"] + "/handoff/" + identity + ".rfad.zip"
    result = {"profile": plan["schema"], "project_id": plan["project_id"], "package_id": identity,
              "revision_id": plan["revision_id"], "artifact": reference(path, raw), "review_hash": review,
              "file_name": file_name, "chunk_bytes": CHUNK_BYTES}
    if "snapshot_id" in plan:
        result["snapshot_id"] = plan["snapshot_id"]
    staged = {**state, "handoff_packages": {**stored, identity: result}}
    if len(canonical_bytes(staged)) + len(canonical_bytes(result)) + 4096 > MAX_STATE_BYTES:
        codec.fail("인계 파일의 확정 기록과 영수증 공간이 부족합니다.", "E_RESOURCE")
    put = service.journal.put_archive if namespace == "archive" else service.journal.put_immutable
    if put(path, raw) != result["artifact"]:
        codec.fail("인계 파일 해시가 게시 직전에 달라졌습니다.", "E_HASH")
    state["handoff_packages"] = staged["handoff_packages"]
    return deepcopy(result)


def read(service, state, context, project, suffix, data, profile, mutation):
    """! @brief 기존 발행물/영수증은 현재 프로젝트와 같은 프로파일에서만 읽는다."""
    if suffix == "receipt":
        receipt = state["receipts"].get(canonical_hash([data["request_key_epoch"], data["request_key"]]))
        if receipt is not None and (receipt["scope"] != context or receipt["method"] != mutation):
            codec.fail("다른 프로젝트 또는 기능의 인계 영수증입니다.", "E_CONFLICT")
        found = receipt is not None and receipt["expires_at"] > service._now()
        return {"status": "found" if found else "expired" if receipt else "unresolved", "authoritative": True,
                "may_resubmit": False, "response": deepcopy(receipt["response"]) if found else None}
    items = state.get("handoff_packages", {})
    if suffix == "list":
        return {"profile": profile, "project_id": context["project_id"],
                "items": [deepcopy(row) for _, row in sorted(items.items())
                          if row["project_id"] == context["project_id"] and row["profile"] == profile]}
    stored = items.get(data["package_id"])
    if stored is None or stored["project_id"] != context["project_id"] or stored["profile"] != profile:
        codec.fail("이 프로젝트의 해당 형식에서 보존한 인계 묶음이 없습니다.", "E_CONFLICT")
    artifact = owned_reference(project, stored["artifact"])
    if artifact["sha256"] != data["sha256"]:
        codec.fail("선택한 인계 묶음의 고정 해시가 다릅니다.", "E_HASH")
    offset = data["offset"]
    if offset >= artifact["bytes"]:
        codec.fail("인계 파일의 실제 크기 밖을 읽을 수 없습니다.", "E_RESOURCE")
    total = artifact["bytes"]
    if total > MAX_ARTIFACT_BYTES:
        chunk = service.journal.read_file_chunk(artifact, offset, CHUNK_BYTES)
    else:
        chunk = service.journal.read_artifact(artifact)[offset:offset + CHUNK_BYTES]
    end = offset + len(chunk)
    return {"profile": profile, "project_id": context["project_id"], "package_id": stored["package_id"],
            "sha256": artifact["sha256"], "total": total, "offset": offset, "next_offset": end if end < total else None,
            "content_base64": base64.b64encode(chunk).decode("ascii")}
