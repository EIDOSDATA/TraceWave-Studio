"""! @brief 로컬 GUI로 받은 유한 ZIP 바이트를 목적지 검토와 복원 영수증에 연결한다."""

import base64
from copy import deepcopy
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from rfad.application import handoff_archive as codec, project_archive
from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.network_library import digest
from rfad.storage.journal import MAX_STATE_BYTES


PROFILE = "rfad.archive-receive/0.1"
CHUNK_BYTES = 128 * 1024
RECEIVE_TTL = 600
READS = {"archive.receive.begin", "archive.receive.chunk", "archive.receive.review", "archive.receive.drop",
         "archive.receive.status"}
MUTATIONS = {"archive.receive.reserve", "archive.receive.apply"}
FIELDS = {
    "archive.receive.begin": {"bytes", "archive_sha256"},
    "archive.receive.chunk": {"upload_id", "offset", "content_base64"},
    "archive.receive.review": {"upload_id"},
    "archive.receive.drop": {"upload_id"},
    "archive.receive.status": {"archive_sha256"},
    "archive.receive.reserve": {"upload_id", "archive_sha256", "review_hash"},
    "archive.receive.apply": {"upload_id", "archive_sha256", "review_hash"},
}


def validate_input(method, context, data):
    """! @brief 복원 대상은 현재 목적지 작업 영역이며 외부 파일 경로를 입력으로 받지 않는다."""
    _fields(context, set())
    _fields(data, FIELDS[method])
    if "upload_id" in data:
        _uuid(data["upload_id"])
    for key in ("archive_sha256", "review_hash"):
        if key in data:
            digest(data[key], key)
    if method == "archive.receive.begin" and (type(data["bytes"]) is not int or not 0 < data["bytes"] <= project_archive.MAX_ARCHIVE_BYTES):
        codec.fail("복원 ZIP을 1 B~64 MiB 범위에서 선택하십시오.", "E_RESOURCE")
    if method == "archive.receive.chunk":
        offset = data["offset"]
        if type(offset) is not int or not 0 <= offset < project_archive.MAX_ARCHIVE_BYTES or offset % CHUNK_BYTES:
            codec.fail("정상적인 복원 청크 위치가 필요합니다.")
        if type(data["content_base64"]) is not str or not 0 < len(data["content_base64"]) <= ((CHUNK_BYTES + 2) // 3) * 4:
            codec.fail("복원 청크 크기의 상한은 128 KiB입니다.", "E_RESOURCE")


def _summary(result):
    """! @brief 화면 표시와 영수증에는 전체 파일 참조나 전송 버퍼를 포함하지 않는다."""
    return {**{key: deepcopy(value) for key, value in result.items() if key != "omitted"},
            "omitted_preview": deepcopy(result.get("omitted", [])[:16])}


class ArchiveReceiver:
    """! @brief 서비스 한 연결에서 한 파일의 원문만 임시 보관한다."""

    def __init__(self, now):
        """! @brief 명시 세션 수명, 원문 크기 및 전송 잠금을 분리한다."""
        self.now = now
        self.lock = RLock()
        self.session = None

    def _current(self):
        """! @brief 읽기 중단이나 종료 뒤 남은 임시 버퍼를 유효 기간 안에서만 유지한다."""
        if self.session is not None and self.session["expires_at"] <= self.now():
            self.session = None
        return self.session

    def _session(self, identity):
        """! @brief 다른 전송 또는 만료된 버퍼를 새 묶음으로 자동 대체하지 않는다."""
        row = self._current()
        if row is None or row["upload_id"] != identity:
            codec.fail("선택한 ZIP의 전송 버퍼가 없습니다. 같은 파일을 다시 선택하십시오.", "E_CONFLICT")
        row["expires_at"] = self.now() + RECEIVE_TTL
        return row

    @staticmethod
    def _progress(row):
        return {"profile": PROFILE, "upload_id": row["upload_id"], "archive_sha256": row["archive_sha256"],
                "bytes": row["bytes"], "received": len(row["content"]), "chunk_bytes": CHUNK_BYTES}

    def begin(self, data):
        """! @brief 같은 원문을 이어 읽되 다른 파일의 버퍼를 묵시적으로 교체하지 않는다."""
        with self.lock:
            row = self._current()
            if row is None:
                row = {**data, "upload_id": str(uuid4()), "content": bytearray(), "expires_at": self.now() + RECEIVE_TTL}
                self.session = row
            elif row["bytes"] != data["bytes"] or row["archive_sha256"] != data["archive_sha256"]:
                codec.fail("다른 원문 전송이 준비되어 있습니다. 현재 전송을 닫은 뒤 선택하십시오.", "E_CONFLICT")
            row["expires_at"] = self.now() + RECEIVE_TTL
            return self._progress(row)

    def chunk(self, data):
        """! @brief 같은 청크 재전송은 허용하며 비정규 표현, 빈 구간과 변경을 거절한다."""
        encoded = data["content_base64"]
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError):
            codec.fail("복원 청크가 정규 base64가 아닙니다.", "E_SCHEMA")
        if base64.b64encode(raw).decode("ascii") != encoded:
            codec.fail("복원 청크가 정규 base64가 아닙니다.")
        with self.lock:
            row = self._session(data["upload_id"])
            offset = data["offset"]
            current = len(row["content"])
            if not 0 < len(raw) == min(CHUNK_BYTES, row["bytes"] - offset) or offset > current:
                codec.fail("복원 청크가 현재 위치 또는 선언 길이와 다릅니다.", "E_CONFLICT")
            if offset < current:
                if row["content"][offset:offset + len(raw)] != raw:
                    codec.fail("이미 받은 복원 청크의 바이트가 바뀌었습니다.", "E_HASH")
            else:
                row["content"].extend(raw)
            return self._progress(row)

    def payload(self, upload_id, archive_sha256=None):
        """! @brief 완전히 읽고 같은 SHA256이 확인된 한 묶음만 복원에 넘긴다."""
        with self.lock:
            row = self._session(upload_id)
            if len(row["content"]) != row["bytes"]:
                codec.fail("전체 ZIP을 아직 받지 못했습니다.", "E_CONFLICT")
            actual = sha256(row["content"]).hexdigest()
            if actual != row["archive_sha256"] or (archive_sha256 is not None and actual != archive_sha256):
                codec.fail("받은 ZIP의 실제 SHA256이 검토 요청과 다릅니다.", "E_HASH")
            return bytes(row["content"])

    def drop(self, identity):
        """! @brief 이전 적용은 유지하고 그 전송의 임시 원문만 회수한다."""
        with self.lock:
            self._session(identity)
            self.session = None
        return {"profile": PROFILE, "dropped": True, "upload_id": identity}


def read(service, method, params):
    """! @brief 요청 바이트와 검토 또는 대상의 실제 영수증을 조회한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        codec.fail("지원하지 않는 복원 수신 API 버전입니다.", "E_VERSION")
    data = params["input"]
    validate_input(method, params["context"], data)
    receiver = service.archive_receiver
    if method == "archive.receive.begin":
        return receiver.begin(data)
    if method == "archive.receive.chunk":
        return receiver.chunk(data)
    if method == "archive.receive.drop":
        return receiver.drop(data["upload_id"])
    if method == "archive.receive.review":
        result = project_archive.preview_restore(service, receiver.payload(data["upload_id"]))
        return {**_summary(result), "upload_id": data["upload_id"]}
    archive_sha = data["archive_sha256"]
    row = service.journal.read().get("archive_restores", {}).get(archive_sha)
    return {"profile": PROFILE, "archive_sha256": archive_sha, "authoritative": True,
            "status": "not_registered" if row is None else row["status"],
            "result": None if row is None else _summary(row)}


def admit(service, state, method, data):
    """! @brief 동일한 제한 검토로 예약 및 원자 등록을 각각 원래 요청의 영수증에 게시한다."""
    raw = service.archive_receiver.payload(data["upload_id"], data["archive_sha256"])
    with project_archive.verified_review(service, raw, data["review_hash"]) as (archive, plan, index, details):
        if method == "archive.receive.reserve":
            result = project_archive.reserve_state(service, state, details, index)
        else:
            result = project_archive.publish_state(service, state, raw, archive, plan, index, details)
        summary = _summary(result)
        if len(canonical_bytes(state)) + len(canonical_bytes(summary)) + 2048 > MAX_STATE_BYTES:
            codec.fail("복원 영수증을 보존할 여유가 없습니다.", "E_RESOURCE")
        return summary
