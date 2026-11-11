"""! @brief 선택한 원문의 제한된 사본을 하나의 읽기 트랜잭션에서 만든다."""

from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath

from rfad.catalog.models import CatalogError, canonical_json, stable_id
from rfad.catalog.repository import CatalogRepository, IDS, TEXT_COLUMNS, NUMBER_COLUMNS
from rfad.catalog.source import decode_json


MAX_RAW_BYTES = 256 * 1024
MAX_READ_BYTES = 1024 * 1024
MAX_READ_ROWS = 512
MAX_COMPONENTS = 256
from rfad.domain.resource_limits import MAX_EVIDENCE_BYTES
ENTITIES = frozenset({"observations", "sources", "native_templates", "native_components"})


def _pointer(value: object, pointer: str) -> tuple[bool, object]:
    """! @brief RFC 6901 경로를 따라가며 미제공 값과 명시적 null을 구분한다."""
    if not isinstance(pointer, str) or len(pointer) > 256 or (pointer and not pointer.startswith("/")):
        raise CatalogError("E_SCHEMA", "근거의 JSON pointer 형식이 잘못되었습니다.")
    if not pointer:
        return True, value
    tokens = []
    for encoded in pointer[1:].split("/"):
        index = 0
        while index < len(encoded):
            if encoded[index] == "~":
                if index + 1 >= len(encoded) or encoded[index + 1] not in "01":
                    raise CatalogError("E_SCHEMA", "JSON pointer의 escape가 잘못되었습니다.")
                index += 1
            index += 1
        tokens.append(encoded.replace("~1", "/").replace("~0", "~"))
    for token in tokens:
        if isinstance(value, dict):
            if token not in value:
                return False, None
            value = value[token]
        elif isinstance(value, list):
            if not token.isascii() or not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False, None
            if len(token) > 10 or int(token) >= len(value):
                return False, None
            value = value[int(token)]
        else:
            return False, None
    return True, value


class SelectionReader:
    """! @brief 선택 개정의 원문과 해시를 검증하고 프로젝트 소유 근거를 중복 없이 수집한다."""

    def __init__(self, database: Path | None, catalog_id: str):
        """! @brief 변경할 수 없는 카탈로그 개정과 읽기 예산을 지정한다."""
        if not isinstance(catalog_id, str) or not 1 <= len(catalog_id) <= 256:
            raise CatalogError("E_SCHEMA", "선택할 카탈로그의 명시적인 개정 ID가 필요합니다.")
        self.repository = CatalogRepository(database)
        self.catalog_id = catalog_id
        self._context = None
        self._connection = None
        self._metadata = {}
        self._records = {}
        self._evidence = {}
        self._read_bytes = 0
        self._used = False

    def __enter__(self):
        """! @brief 전체 선택 과정에 같은 읽기 트랜잭션과 개정을 사용한다."""
        if self._context is not None or self._used:
            raise CatalogError("E_CONFLICT", "선택 reader는 한 번의 선택 트랜잭션에서만 사용합니다.")
        self._used = True
        self._context = self.repository.connection()
        try:
            self._connection, self._metadata = self._context.__enter__()
            self.repository._check_revision(self._metadata, self.catalog_id)
        except Exception as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise
        return self

    def __exit__(self, kind, error, traceback):
        """! @brief 성공이나 실패 모두 읽기 연결을 닫고 DB에는 쓰지 않는다."""
        context = self._context
        self._context = None
        self._connection = None
        if context is not None:
            return context.__exit__(kind, error, traceback)
        return False

    @property
    def metadata(self) -> dict:
        """! @brief 검증된 카탈로그 메타데이터의 변경할 수 있는 독립 사본을 반환한다."""
        return deepcopy(self._metadata)

    @property
    def evidence(self) -> list[dict]:
        """! @brief 내부 캐시를 변경할 수 없는 프로젝트 근거 사본을 반환한다."""
        return self.evidence_items()

    def evidence_items(self) -> list[dict]:
        """! @brief 같은 근거를 한 번만 담은 안정 순서의 목록을 반환한다."""
        return deepcopy(list(self._evidence.values()))

    def catalog(self) -> dict:
        """! @brief 선택 provenance의 최소 카탈로그 식별 계약을 반환한다."""
        fields = ("catalog_id", "import_version", "source_canonical_sha256", "source_index_sha256")
        result = {field: self._metadata.get(field) for field in fields}
        if any(not isinstance(value, str) or not value for value in result.values()):
            raise CatalogError("E_SCHEMA", "카탈로그의 선택 출처 식별자가 불완전합니다.")
        return result

    def _read(self, entity: str, identifier: str) -> dict:
        """! @brief 전체 라이브러리 대신 한 원문의 실제 바이트와 저장 해시를 확인한다."""
        if self._connection is None:
            raise CatalogError("E_CONFLICT", "선택 reader를 context manager 안에서 사용하십시오.")
        if entity not in ENTITIES or not isinstance(identifier, str) or not 1 <= len(identifier) <= 256:
            raise CatalogError("E_SCHEMA", "선택 항목의 종류나 ID가 잘못되었습니다.")
        key = (entity, identifier)
        if key in self._records:
            return deepcopy(self._records[key])
        if len(self._records) >= MAX_READ_ROWS:
            raise CatalogError("E_RESOURCE", "한 선택에서 읽을 원문 행수 상한을 초과했습니다.")
        columns = list(dict.fromkeys((*TEXT_COLUMNS[entity], *NUMBER_COLUMNS.get(entity, ()), "raw_sha256", "raw_json")))
        if entity.startswith("native_"):
            columns.append("flags_json")
        lengths = ",".join("length(CAST(" + field + " AS BLOB))" for field in columns)
        sizes = self._connection.execute("SELECT " + lengths + " FROM " + entity + " WHERE " + IDS[entity] + "=?", (identifier,)).fetchone()
        if sizes is None:
            raise CatalogError("E_RESOURCE", "선택한 카탈로그 항목이 없습니다.", details={"entity": entity, "id": identifier})
        raw_size = sizes[columns.index("raw_json")]
        total = sum(value for value in sizes if type(value) is int)
        if type(raw_size) is not int or raw_size > MAX_RAW_BYTES or total > MAX_RAW_BYTES + 32 * 1024:
            raise CatalogError("E_RESOURCE", "선택한 원문 한 행이 읽기 크기 상한을 초과했습니다.")
        if self._read_bytes + total > MAX_READ_BYTES:
            raise CatalogError("E_RESOURCE", "한 선택에서 읽을 원문 크기 상한을 초과했습니다.")
        row = self._connection.execute("SELECT " + ",".join(columns) + " FROM " + entity + " WHERE " + IDS[entity] + "=?", (identifier,)).fetchone()
        item = dict(row)
        raw = item["raw_json"]
        digest = item["raw_sha256"]
        if not isinstance(raw, str) or not isinstance(digest, str):
            raise CatalogError("E_SCHEMA", "선택 원문의 JSON 문자열 또는 해시가 잘못되었습니다.")
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != digest:
            raise CatalogError("E_HASH", "선택한 원문과 저장된 해시가 일치하지 않습니다.")
        value = decode_json(raw)
        if canonical_json(value) != raw:
            raise CatalogError("E_HASH", "선택한 원문 JSON은 정규 표현이어야 합니다.")
        if entity in ("observations", "sources"):
            if not isinstance(value, dict) or value.get(IDS[entity]) != identifier:
                raise CatalogError("E_HASH", "원문 식별자가 선택한 카탈로그 항목과 다릅니다.")
        if entity == "observations" and value.get("source_id") != item["source_id"]:
            raise CatalogError("E_HASH", "관측 원문과 카탈로그 출처 연결이 다릅니다.")
        item["raw"] = value
        self._read_bytes += total
        self._records[key] = item
        return deepcopy(item)

    def observation(self, record_id: str) -> dict:
        """! @brief 선택한 물성 관측 한 행을 반환한다."""
        return self._read("observations", record_id)

    def stackup_observations(self, stackup_id: str, publisher: str, source_id: str) -> list[dict]:
        """! @brief 같은 적층과 발행자 및 출처의 관측만 제한된 색인 조회로 읽는다.

        @details 전체 행을 검색하거나 이름 유사도로 대체하지 않는다. 원문 해시와
        읽기 예산은 개별 observation 조회와 같은 검사를 거친다.
        """
        if self._connection is None:
            raise CatalogError("E_CONFLICT", "선택 reader를 context manager 안에서 사용하십시오.")
        if any(type(value) is not str or not 1 <= len(value) <= 256
               for value in (stackup_id, publisher, source_id)):
            raise CatalogError("E_SCHEMA", "적층 관측 조회의 명시적인 식별자가 필요합니다.")
        rows = self._connection.execute(
            "SELECT record_id FROM observations INDEXED BY observations_stackup "
            "WHERE stackup_id=? AND publisher=? AND source_id=? ORDER BY record_id LIMIT ?",
            (stackup_id, publisher, source_id, MAX_READ_ROWS + 1),
        ).fetchall()
        if len(rows) > MAX_READ_ROWS:
            raise CatalogError("E_RESOURCE", "선택한 적층의 관측 개수 상한을 초과했습니다.")
        return [self.observation(row[0]) for row in rows]

    def source(self, source_id: str) -> dict:
        """! @brief 원문 파일을 다시 열지 않고 당시 출처 메타데이터를 반환한다."""
        return self._read("sources", source_id)

    def native_template(self, template_id: str) -> dict:
        """! @brief 공개 적층 template의 정확한 원문과 위치를 반환한다."""
        return self._read("native_templates", template_id)

    def native_component(self, component_id: str) -> dict:
        """! @brief 물리층으로 확정하지 않은 원자료 구성행을 반환한다."""
        return self._read("native_components", component_id)

    def native_components(self, template_id: str) -> list[dict]:
        """! @brief template의 구성행을 원래 순서와 명시적인 개수 상한으로 읽는다."""
        self.native_template(template_id)
        rows = self._connection.execute(
            "SELECT component_id FROM native_components WHERE template_id=? ORDER BY component_order,component_id LIMIT ?",
            (template_id, MAX_COMPONENTS + 1),
        ).fetchall()
        if len(rows) > MAX_COMPONENTS:
            raise CatalogError("E_RESOURCE", "선택한 template의 구성행 개수 상한을 초과했습니다.")
        return [self.native_component(row[0]) for row in rows]

    def capture(self, entity: str, identifier: str, pointers: list[str] | None = None) -> dict:
        """! @brief 완전 원문과 명시적인 pointer별 부분사본을 구분해 근거로 봉인한다."""
        item = self._read(entity, identifier)
        if pointers is None:
            if entity.startswith("native_"):
                raise CatalogError("E_SCHEMA", "원시 적층 근거는 사용할 JSON pointer를 명시해야 합니다.")
            scope, pointers, raw = "complete", [], item["raw_json"]
        else:
            if not isinstance(pointers, list) or not 1 <= len(pointers) <= 64 or any(not isinstance(pointer, str) for pointer in pointers):
                raise CatalogError("E_SCHEMA", "부분사본에는 제한된 JSON pointer 목록이 필요합니다.")
            pointers = sorted(set(pointers))
            values, missing = {}, []
            for pointer in pointers:
                exists, value = _pointer(item["raw"], pointer)
                if exists:
                    values[pointer] = value
                else:
                    missing.append(pointer)
            scope, raw = "projection", canonical_json({"values": values, "missing": missing})
        if len(raw) > 4096 or len(raw.encode("utf-8")) > 8192:
            raise CatalogError("E_RESOURCE", "프로젝트 근거 사본 한 개의 크기 상한을 초과했습니다.")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        origin = None
        if entity.startswith("native_"):
            origin = {"source_id": item["source_id"], "path": item["source_path"],
                      "pointer": item["source_pointer"], "sha256": item["source_sha256"]}
            if any(not isinstance(value, str) or len(value) > 1024 for value in origin.values()):
                raise CatalogError("E_SCHEMA", "원시 적층 근거의 원문 위치가 불완전합니다.")
            if not origin["source_id"] or not origin["path"]:
                raise CatalogError("E_SCHEMA", "원시 적층 근거의 출처 ID와 경로가 필요합니다.")
            path = origin["path"]
            if "\\" in path or ":" in path or PurePosixPath(path).is_absolute() or any(part in ("", ".", "..") for part in path.split("/")):
                raise CatalogError("E_PATH", "원시 적층 근거 경로는 패키지 내부 상대 POSIX 경로여야 합니다.")
            _pointer({}, origin["pointer"])
            if len(origin["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in origin["sha256"]):
                raise CatalogError("E_SCHEMA", "원시 적층 원문 파일의 SHA-256이 잘못되었습니다.")
        identity = stable_id("evidence", self.catalog_id, entity, identifier, scope, pointers, digest, origin)
        evidence = {"id": identity, "entity": entity, "item_id": identifier, "scope": scope,
                    "pointers": pointers, "original_sha256": item["raw_sha256"],
                    "snapshot_sha256": digest, "raw_json": raw, "origin": origin}
        if identity not in self._evidence:
            candidate = [*self._evidence.values(), evidence]
            if len(canonical_json(candidate).encode("utf-8")) > MAX_EVIDENCE_BYTES:
                raise CatalogError("E_RESOURCE", "프로젝트 선택 근거의 전체 128 KiB 상한을 초과했습니다.")
            self._evidence[identity] = evidence
        return deepcopy(evidence)

    def source_evidence(self, source_id: str) -> dict:
        """! @brief 선택 자료의 원문 위치와 수집 당시 출처를 완전 사본으로 남긴다."""
        return self.capture("sources", source_id)

    def snapshot_observation(self, record_id: str) -> tuple[dict, dict, dict]:
        """! @brief 원래 관측과 연결된 출처를 함께 복사한다."""
        item = self.observation(record_id)
        evidence = self.capture("observations", record_id)
        source = self.source_evidence(item["source_id"])
        return item, evidence, source
