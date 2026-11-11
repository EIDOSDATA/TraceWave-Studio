"""! @brief 제조업체별 원문 적층 가져오기가 공유하는 검증과 저장 기능이다."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Protocol

from rfad.catalog.models import CatalogError, canonical_json, stable_id


NATIVE_DIRECTORY = "data/fabricator_native_metadata/"
MAX_NATIVE_FILE_BYTES = 8 * 1024 * 1024
REVIEW_FLAGS = ("requires_review", "not_a_verified_physical_stackup")


class NativePackage(Protocol):
    """! @brief 해시와 경로를 검증하는 읽기 전용 자료 패키지 계약이다."""

    files: dict

    def read_json(self, relative: str) -> Any:
        """! @brief 크기가 제한되고 유한 숫자만 포함한 JSON을 읽는다."""
        ...

    def verify_file(self, relative: str) -> Path:
        """! @brief 패키지 안의 원본 해시를 확인하고 경로를 반환한다."""
        ...

    def file_sha256(self, relative: str) -> str:
        """! @brief 검증된 파일의 SHA-256을 반환한다."""
        ...


def mapping(value: Any, location: str) -> dict:
    """! @brief 객체가 필요한 위치에 다른 JSON 자료형이 있으면 거부한다."""
    if not isinstance(value, dict):
        raise CatalogError("catalog_native_shape", "원시 적층 객체가 필요합니다.", details={"location": location})
    return value


def sequence(value: Any, location: str) -> list:
    """! @brief 배열이 필요한 위치의 자료형을 확인한다."""
    if not isinstance(value, list):
        raise CatalogError("catalog_native_shape", "원시 적층 배열이 필요합니다.", details={"location": location})
    return value


def text(value: Any, location: str) -> str:
    """! @brief 공개 식별자의 빈값이나 자료형 변환을 허용하지 않는다."""
    if not isinstance(value, str) or not value:
        raise CatalogError("catalog_native_identity", "비어 있지 않은 원문 식별자가 필요합니다.", details={"location": location})
    return value


def integer(value: Any, location: str) -> int:
    """! @brief 참거짓 값을 정수 순번으로 잘못 취급하지 않는다."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CatalogError("catalog_native_identity", "음수가 아닌 원문 순번이 필요합니다.", details={"location": location})
    return value


@dataclass(frozen=True)
class TemplateReference:
    """! @brief 원시 템플릿과 기존 관측 라벨 사이의 명시적인 연결이다."""

    template_id: str
    stackup_id: str | None
    publisher: str
    source_id: str


class NativeWriter:
    """! @brief 물리층을 추정하지 않고 JSON, 출처 위치와 위험 표시를 저장한다."""

    def __init__(self, connection: sqlite3.Connection, package: NativePackage):
        """! @brief 호출자가 소유하는 트랜잭션과 원문 검증기를 사용한다."""
        self.connection = connection
        self.package = package
        self.files: dict[str, dict] = {}
        self.counts = {"templates": 0, "components": 0, "evidence": 0, "links": 0}

    def read(self, filename: str) -> tuple[str, Any]:
        """! @brief 지정된 메타데이터 파일을 한 번에 하나씩 읽고 증거를 기록한다."""
        if "/" in filename or "\\" in filename or not filename.endswith(".json"):
            raise CatalogError("catalog_native_path", "메타데이터 파일명이 허용된 형식이 아닙니다.")
        relative = NATIVE_DIRECTORY + filename
        path = self.package.verify_file(relative)
        if path.stat().st_size > MAX_NATIVE_FILE_BYTES:
            raise CatalogError("E_RESOURCE", "원시 적층 JSON의 파일별 크기 상한을 초과했습니다.", details={"path": relative})
        digest = self.package.file_sha256(relative)
        self.files[relative] = {"source_sha256": digest, "stored_as": []}
        return relative, self.package.read_json(relative)

    def coverage(self, relative: str, destination: str, count: int) -> None:
        """! @brief 각 원본 파일의 필드가 보존된 저장 영역을 기록한다."""
        self.files[relative]["stored_as"].append({"destination": destination, "records": count})

    def raw(self, value: Any) -> tuple[str, str]:
        """! @brief 원문 타입을 유지한 JSON과 그 표현의 해시를 함께 만든다."""
        raw = canonical_json(value)
        return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def template(
        self, publisher: str, source_id: str, key: str, label: str, kind: str,
        relative: str, pointer: str, value: Any, flags: tuple[str, ...] = (),
    ) -> TemplateReference:
        """! @brief 출처별 원시 템플릿을 저장하고 같은 공개 라벨만 연결한다."""
        template_id = stable_id("native_template", publisher, source_id, key)
        candidate = stable_id("stackup", publisher, label)
        linked = self.connection.execute(
            "SELECT stackup_id FROM stackups WHERE stackup_id=? AND publisher=? AND source_stackup_id=?",
            (candidate, publisher, label),
        ).fetchone()
        stackup_id = linked[0] if linked is not None else None
        raw, digest = self.raw(value)
        self.connection.execute(
            "INSERT INTO native_templates "
            "(template_id,stackup_id,publisher,template_key,kind,source_id,source_path,source_pointer,"
            "source_sha256,raw_json,raw_sha256,flags_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (template_id, stackup_id, publisher, key, kind, source_id, relative, pointer,
             self.files[relative]["source_sha256"], raw, digest, canonical_json(sorted(set(REVIEW_FLAGS + flags)))),
        )
        if stackup_id is not None:
            self.connection.execute(
                "INSERT INTO native_stackup_links VALUES (?,?,?,?)",
                (template_id, stackup_id, "same_published_label",
                 "같은 공개 적층 라벨의 자료 연결입니다. 구성행과 실제 물리층의 동등성을 승인하지 않습니다."),
            )
            self.connection.execute("UPDATE stackups SET native_available=1 WHERE stackup_id=?", (stackup_id,))
            self.counts["links"] += 1
        self.counts["templates"] += 1
        return TemplateReference(template_id, stackup_id, publisher, source_id)

    def component(
        self, template: TemplateReference, order: int, kind: str, relative: str,
        pointer: str, value: Any, flags: tuple[str, ...] = (),
    ) -> None:
        """! @brief 원문 구성행을 저장하며 한 행을 물리층으로 변환하지 않는다."""
        raw, digest = self.raw(value)
        component_id = stable_id("native_component", template.template_id, order)
        common = REVIEW_FLAGS + ("native_component_not_physical_layer",)
        self.connection.execute(
            "INSERT INTO native_components "
            "(component_id,template_id,stackup_id,publisher,source_id,source_path,source_pointer,"
            "source_sha256,component_order,kind,raw_json,raw_sha256,flags_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (component_id, template.template_id, template.stackup_id, template.publisher,
             template.source_id, relative, pointer, self.files[relative]["source_sha256"], order,
             kind, raw, digest, canonical_json(sorted(set(common + flags)))),
        )
        self.counts["components"] += 1

    def evidence(self, kind: str, relative: str, pointer: str, value: Any) -> None:
        """! @brief 템플릿 외의 페이지 정보와 원본 감사 자료를 보존한다."""
        raw, digest = self.raw(value)
        self.connection.execute(
            "INSERT INTO native_evidence VALUES (?,?,?,?,?,?,?)",
            (stable_id("native_evidence", relative, pointer, kind), kind, relative, pointer,
             raw, digest, self.files[relative]["source_sha256"]),
        )
        self.counts["evidence"] += 1

