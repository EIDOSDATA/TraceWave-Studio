"""! @brief 외부 원문을 열지 않고 SQLite 인덱스의 제한된 읽기만 수행한다."""

from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3

from .models import CATALOG_IMPORT_VERSION, CATALOG_SCHEMA, CATALOG_USER_VERSION, CatalogError
from .query import DetailQuery, MAX_TEXT_CHARACTERS, SearchQuery, escape_like


IDS = {
    "observations": "record_id", "products": "product_id", "stackups": "stackup_id", "sources": "source_id",
    "native_templates": "template_id", "native_components": "component_id", "native_evidence": "evidence_id",
}
TEXT_COLUMNS = {
    "observations": ("record_id", "product_id", "stackup_id", "source_id", "publisher", "product",
                     "dataset_role", "material_form", "value_type", "source_file"),
    "products": ("product_id", "publisher", "product", "dataset_role", "laminate_manufacturer"),
    "stackups": ("stackup_id", "publisher", "source_stackup_id", "label"),
    "sources": ("source_id", "publisher", "title", "url", "local_path"),
    "native_templates": ("template_id", "stackup_id", "publisher", "template_key", "kind", "source_id",
                         "source_path", "source_pointer", "source_sha256"),
    "native_components": ("component_id", "template_id", "stackup_id", "publisher", "source_id", "source_path",
                          "source_pointer", "source_sha256", "kind"),
    "native_evidence": ("evidence_id", "kind", "source_path", "source_pointer", "source_sha256"),
}
NUMBER_COLUMNS = {
    "observations": ("frequency_ghz", "frequency_min_ghz", "frequency_max_ghz", "df_frequency_ghz",
                     "dk", "dk_min", "dk_max", "df", "df_min", "df_max", "thickness_mm"),
    "stackups": ("layer_count", "nominal_thickness_mm", "native_available"),
    "sources": ("local_available",), "native_components": ("component_order",),
}
SEARCH_COLUMNS = {
    "observations": ("record_id", "publisher", "product", "material_form"),
    "products": ("publisher", "product", "laminate_manufacturer"),
    "stackups": ("publisher", "source_stackup_id", "label"),
    "sources": ("publisher", "title", "url"),
    "native_templates": ("publisher", "template_key", "kind"),
    "native_components": ("publisher", "kind", "source_pointer"),
    "native_evidence": ("kind", "source_path", "source_pointer"),
}
META_KEYS = ("schema", "import_version", "catalog_id", "source_index_sha256", "source_canonical_sha256",
             "created_at", "counts", "readiness")


class CatalogRepository:
    """! @brief 매 요청의 단일 읽기 트랜잭션 안에서 개정과 결과를 함께 읽는다."""

    def __init__(self, database: Path | None):
        """! @brief 경로는 서버 설정에서만 받으며 요청에는 노출하지 않는다."""
        self.database = None if database is None else Path(database).absolute()

    @contextmanager
    def connection(self):
        """! @brief 읽기 전용 URI, 제한 시간과 안전한 스키마 설정으로 연결한다."""
        if self.database is None:
            raise CatalogError("E_RESOURCE", "카탈로그 인덱스가 설정되지 않았습니다.", details={"state": "unconfigured"})
        connection = None
        try:
            if not self.database.is_file():
                raise CatalogError("E_RESOURCE", "카탈로그 인덱스 파일이 없습니다.", details={"state": "missing"})
            connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=1.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA foreign_keys=ON")
            callbacks = 0

            def limit_steps():
                """! @brief 손상되거나 비정상적으로 큰 인덱스의 무한 실행을 막는다."""
                nonlocal callbacks
                callbacks += 1
                return int(callbacks > 20000)

            connection.set_progress_handler(limit_steps, 1000)
            connection.execute("BEGIN")
            metadata = self._validate(connection)
            yield connection, metadata
        except CatalogError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, RecursionError) as error:
            raise CatalogError("E_SCHEMA", "카탈로그 인덱스를 읽을 수 없거나 형식이 손상되었습니다.",
                               details={"state": "invalid"}) from error
        finally:
            if connection is not None:
                connection.close()

    def _validate(self, connection: sqlite3.Connection) -> dict:
        """! @brief 전체 자료를 읽지 않고 스키마, 필수 열과 작은 메타데이터를 검사한다."""
        if connection.execute("PRAGMA user_version").fetchone()[0] != CATALOG_USER_VERSION:
            raise CatalogError("E_VERSION", "지원하지 않는 카탈로그 DB 버전입니다.")
        tables = {row[0]: row[1] for row in connection.execute(
            "SELECT name,type FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'")}
        required = {"meta": {"key", "value"}, "observation_flags": {"record_id", "flag"},
                    "native_stackup_links": {"template_id", "stackup_id", "relation", "reason"}}
        for entity, columns in TEXT_COLUMNS.items():
            required[entity] = set(columns) | set(NUMBER_COLUMNS.get(entity, ())) | {"raw_json", "raw_sha256"}
        required["native_templates"].add("flags_json")
        required["native_components"].add("flags_json")
        required["observations"].add("properties_json")
        for table, fields in required.items():
            if tables.get(table) != "table":
                raise CatalogError("E_SCHEMA", "카탈로그에 필요한 테이블이 없습니다.", details={"table": table})
            actual = {row[1] for row in connection.execute("PRAGMA table_info(" + table + ")")}
            if not fields <= actual:
                raise CatalogError("E_SCHEMA", "카탈로그에 필요한 열이 없습니다.", details={"table": table})
        placeholders = ",".join("?" for _ in META_KEYS)
        metadata = {}
        for row in connection.execute("SELECT key,substr(value,1,16385),length(value) FROM meta WHERE key IN ("
                                      + placeholders + ")", META_KEYS):
            if row[2] > 16384:
                raise CatalogError("E_SCHEMA", "카탈로그 메타데이터의 크기가 허용 범위를 초과했습니다.")
            metadata[row[0]] = json.loads(row[1])
        if metadata.get("schema") != CATALOG_SCHEMA:
            raise CatalogError("E_VERSION", "지원하지 않는 카탈로그 계약 버전입니다.")
        if metadata.get("import_version") != CATALOG_IMPORT_VERSION:
            raise CatalogError("E_VERSION", "카탈로그 변환 버전이 없거나 지원하지 않는 버전입니다. 인덱스를 다시 구축하십시오.")
        identifier = metadata.get("catalog_id")
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 256:
            raise CatalogError("E_SCHEMA", "카탈로그 개정 식별자가 없습니다.")
        identifier.encode("utf-8")
        counts = metadata.get("counts")
        if type(counts) is not dict or any(type(value) is not int or value < 0 for value in counts.values()):
            raise CatalogError("E_SCHEMA", "카탈로그 개수 메타데이터가 올바르지 않습니다.")
        return metadata

    @staticmethod
    def _check_revision(metadata: dict, expected: str | None):
        """! @brief 다른 개정의 페이지를 이어 붙이지 못하게 한다."""
        if expected is not None and expected != metadata["catalog_id"]:
            raise CatalogError("E_CONFLICT", "카탈로그 개정이 변경되었습니다. 첫 페이지부터 다시 조회하십시오.",
                               details={"catalog_id": metadata["catalog_id"]})

    @staticmethod
    def _selection(entity: str) -> str:
        """! @brief 목록에는 원문 JSON을 제외하고 문자열도 읽기 단계에서 제한한다."""
        columns = ["substr(c." + name + ",1," + str(1025 if name == IDS[entity] else MAX_TEXT_CHARACTERS + 1) + ") AS " + name
                   for name in TEXT_COLUMNS[entity]]
        columns.extend("c." + name for name in NUMBER_COLUMNS.get(entity, ()))
        columns.append("substr(c.raw_sha256,1,65) AS raw_sha256")
        if entity in ("native_templates", "native_components"):
            columns.append("substr(c.flags_json,1,8193) AS flags_json")
        if entity == "native_templates":
            columns.extend(("substr(s.label,1," + str(MAX_TEXT_CHARACTERS + 1) + ") AS stackup_label",
                            "s.layer_count AS layer_count", "s.nominal_thickness_mm AS nominal_thickness_mm"))
        return ",".join(columns)

    @staticmethod
    def _source(entity: str) -> str:
        """! @brief 기존 연결의 작은 공개 표기만 결합하고 연결 없는 원시 적층도 유지한다."""
        source = entity + " c"
        if entity == "native_templates":
            source += " LEFT JOIN stackups s ON s.stackup_id=c.stackup_id"
        return source

    @staticmethod
    def _where(request: SearchQuery) -> tuple[str, list]:
        """! @brief 정적 열명만 조합하고 모든 외부 값은 SQL 매개변수로 바인딩한다."""
        conditions, parameters = [], []
        for name, value in request.filters.items():
            if name in ("frequency_ghz", "frequency_property", "frequency_mode"):
                continue
            if name == "review_flag":
                if request.entity == "observations":
                    conditions.append("EXISTS (SELECT 1 FROM observation_flags f WHERE f.record_id=c.record_id AND f.flag=?)")
                else:
                    conditions.append("EXISTS (SELECT 1 FROM json_each(c.flags_json) f WHERE f.value=?)")
            elif name == "layer_count" and request.entity == "observations":
                conditions.append("EXISTS (SELECT 1 FROM stackups s WHERE s.stackup_id=c.stackup_id AND s.layer_count=?)")
            elif name.endswith("_min_mm"):
                conditions.append("c." + name.replace("_min_mm", "_mm") + ">=?")
            elif name.endswith("_max_mm"):
                conditions.append("c." + name.replace("_max_mm", "_mm") + "<=?")
            else:
                conditions.append("c." + name + "=?")
            parameters.append(value)
        if "frequency_ghz" in request.filters:
            prop = request.filters["frequency_property"]
            frequency = request.filters["frequency_ghz"]
            if prop in ("dk", "df"):
                conditions.append("(c." + prop + " IS NOT NULL OR c." + prop + "_min IS NOT NULL OR c."
                                  + prop + "_max IS NOT NULL)")
            if prop != "df" and request.filters.get("frequency_mode", "exact") == "contains":
                conditions.append("(c.frequency_ghz=? OR (c.frequency_min_ghz<=? AND c.frequency_max_ghz>=?))")
                parameters.extend((frequency, frequency, frequency))
            else:
                conditions.append("c." + ("df_frequency_ghz" if prop == "df" else "frequency_ghz") + "=?")
                parameters.append(frequency)
        if request.query:
            columns = ["c." + column for column in SEARCH_COLUMNS[request.entity]]
            if request.entity == "native_templates":
                columns.append("s.label")
            conditions.append("(" + " OR ".join(column + " LIKE ? ESCAPE '\\'" for column in columns) + ")")
            parameters.extend(["%" + escape_like(request.query) + "%"] * len(columns))
        return (" WHERE " + " AND ".join(conditions) if conditions else ""), parameters

    def _rows(self, connection: sqlite3.Connection, entity: str, rows: list) -> list[dict]:
        """! @brief 표시 길이와 검토 플래그를 제한하며 축약 여부를 함께 남긴다."""
        result = []
        for row in rows:
            item = dict(row)
            item["id"] = item[IDS[entity]]
            if type(item["id"]) is not str or not 1 <= len(item["id"]) <= 1024:
                raise CatalogError("E_SCHEMA", "카탈로그 항목의 식별자가 올바르지 않습니다.")
            item["truncated_fields"] = []
            text_columns = TEXT_COLUMNS[entity] + (("stackup_label",) if entity == "native_templates" else ())
            number_columns = NUMBER_COLUMNS.get(entity, ()) + (
                ("layer_count", "nominal_thickness_mm") if entity == "native_templates" else ())
            for field in text_columns:
                if item[field] is not None and type(item[field]) is not str:
                    raise CatalogError("E_SCHEMA", "카탈로그 문자열 열의 타입이 올바르지 않습니다.", details={"field": field})
                if field != IDS[entity] and isinstance(item[field], str) and len(item[field]) > MAX_TEXT_CHARACTERS:
                    item[field] = item[field][:MAX_TEXT_CHARACTERS]
                    item["truncated_fields"].append(field)
            for field in number_columns:
                value = item[field]
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                    raise CatalogError("E_SCHEMA", "카탈로그 수치 열의 타입이 올바르지 않습니다.", details={"field": field})
            if entity == "observations":
                flags = [entry[0] for entry in connection.execute(
                    "SELECT substr(flag,1,513) FROM observation_flags WHERE record_id=? ORDER BY flag LIMIT 65",
                    (item["record_id"],))]
            elif "flags_json" in item:
                raw_flags = item.pop("flags_json")
                if type(raw_flags) is not str or len(raw_flags) > 8192:
                    raise CatalogError("E_SCHEMA", "카탈로그 검토 플래그가 허용 크기를 초과했습니다.")
                flags = json.loads(raw_flags)
                if type(flags) is not list or any(type(flag) is not str for flag in flags):
                    raise CatalogError("E_SCHEMA", "카탈로그 검토 플래그 형식이 올바르지 않습니다.")
            else:
                flags = []
            if len(flags) > 64 or any(len(flag) > 512 for flag in flags):
                item["truncated_fields"].append("review_flags")
            item["review_flags"] = [flag[:512] for flag in flags[:64]]
            for field in ("native_available", "local_available"):
                if field in item:
                    if type(item[field]) is not int or item[field] not in (0, 1):
                        raise CatalogError("E_SCHEMA", "카탈로그 가용성 열의 타입이 올바르지 않습니다.")
                    item[field] = bool(item[field])
            result.append(item)
        return result

    def status(self) -> dict:
        """! @brief 설정된 DB의 작은 메타데이터만 읽는다."""
        with self.connection() as (_, metadata):
            return metadata

    def search(self, request: SearchQuery) -> tuple[dict, list[dict]]:
        """! @brief 안정 ID 순서로 요청 크기보다 하나 많은 행만 조회한다."""
        with self.connection() as (connection, metadata):
            self._check_revision(metadata, request.catalog_id)
            where, parameters = self._where(request)
            order = "c.template_id,c.component_order,c.component_id" if request.entity == "native_components" else "c." + IDS[request.entity]
            rows = connection.execute("SELECT " + self._selection(request.entity) + " FROM " + self._source(request.entity)
                                      + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                                      parameters + [request.limit + 1, request.offset]).fetchall()
            return metadata, self._rows(connection, request.entity, rows)

    def get(self, request: DetailQuery) -> tuple[dict, dict, dict]:
        """! @brief 원문 JSON을 파싱하지 않고 SQLite에서 필요한 조각만 읽는다."""
        with self.connection() as (connection, metadata):
            self._check_revision(metadata, request.catalog_id)
            properties = ",substr(c.properties_json,1,8193) AS properties_json" if request.entity == "observations" else ""
            row = connection.execute("SELECT " + self._selection(request.entity) + properties
                                     + ",length(c.raw_json) AS raw_length,substr(c.raw_json,?,?) AS raw_fragment FROM "
                                     + self._source(request.entity) + " WHERE c." + IDS[request.entity] + "=?",
                                     (request.raw_offset + 1, request.raw_limit, request.identifier)).fetchone()
            if row is None:
                raise CatalogError("E_RESOURCE", "요청한 카탈로그 항목이 없습니다.")
            item = dict(row)
            length, fragment = item.pop("raw_length"), item.pop("raw_fragment")
            if type(length) is not int or type(fragment) is not str:
                raise CatalogError("E_SCHEMA", "카탈로그 원문 JSON 문자열이 올바르지 않습니다.")
            property_text = item.pop("properties_json", None)
            property_view = None
            if property_text is not None:
                if type(property_text) is not str or len(property_text.encode("utf-8")) > 8192:
                    raise CatalogError("E_SCHEMA", "카탈로그 물성 표시가 허용 크기를 초과했습니다.")
                property_view = json.loads(property_text)
                if type(property_view) is not dict:
                    raise CatalogError("E_SCHEMA", "카탈로그 물성 표시 형식이 올바르지 않습니다.")
            if request.raw_offset > length:
                raise CatalogError("E_SCHEMA", "원문 JSON의 문자 범위를 벗어났습니다.")
            return metadata, self._rows(connection, request.entity, [item])[0], {
                "length": length, "text": fragment, "properties": property_view,
            }
