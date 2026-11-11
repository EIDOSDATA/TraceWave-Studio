"""! @brief 검증된 공개 자료에서 읽기 전용 카탈로그를 원자적으로 재생성한다."""

from datetime import datetime, timezone
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile

from rfad.catalog.models import (
    CATALOG_IMPORT_VERSION, CATALOG_SCHEMA, CATALOG_USER_VERSION, CatalogError, ProductIdentity,
    StackupIdentity, canonical_json, stable_id,
)
from rfad.catalog.review import flags, REVIEW_MEANING
from rfad.catalog.properties import property_views
from rfad.catalog.schema import create_indexes, create_schema
from rfad.catalog.source import PackageSource, decode_json, file_digest, validate_observation


OBSERVATION_COLUMNS = (
    "record_id", "product_id", "stackup_id", "source_id", "publisher", "product",
    "dataset_role", "material_form", "value_type", "frequency_ghz", "df_frequency_ghz",
    "frequency_min_ghz", "frequency_max_ghz", "dk", "dk_min", "dk_max", "df",
    "df_min", "df_max", "thickness_mm", "source_file", "raw_json", "raw_sha256", "properties_json",
)


def _encoded(value: object) -> tuple[str, str]:
    """! @brief 상세 JSON과 실제 저장 UTF-8 바이트의 해시를 함께 만든다."""
    raw = canonical_json(value)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _insert(connection: sqlite3.Connection, table: str, values: dict) -> None:
    """! @brief 내부 고정 열의 값을 바인딩해 삽입한다."""
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))


def _sources(connection: sqlite3.Connection, package: PackageSource) -> None:
    """! @brief 실제 원문을 한 경로당 한 번 해시 검사하고 전체 출처 JSON을 보존한다."""
    sources = package.read_json("catalog/sources.json")
    if not isinstance(sources, list):
        raise CatalogError("E_SCHEMA", "출처 목록은 배열이어야 합니다.")
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("source_id"), str) or not source["source_id"]:
            raise CatalogError("E_SCHEMA", "출처에 안정 ID가 없습니다.")
        relative = source.get("local_path")
        if relative:
            package.verify_file(relative)
            entry = package.files[relative]
            if source.get("sha256") not in (None, "", entry["sha256"]):
                raise CatalogError("E_HASH", "출처의 보관 해시와 실제 원문이 다릅니다.")
            if source.get("bytes") is not None and source["bytes"] != entry["bytes"]:
                raise CatalogError("E_HASH", "출처의 보관 크기와 실제 원문이 다릅니다.")
        elif source.get("archived"):
            raise CatalogError("E_PATH", "보관된 출처에 원문 경로가 없습니다.")
        raw, digest = _encoded(source)
        _insert(connection, "sources", {
            "source_id": source["source_id"], "publisher": source.get("organization", ""),
            "title": source.get("title", ""), "url": source.get("url", ""),
            "local_path": relative, "local_available": int(bool(relative)),
            "raw_json": raw, "raw_sha256": digest,
        })


class _ObservationWriter:
    """! @brief 작은 제품/적층 식별 집합만 캐시하며 큰 관측 원문은 SQLite에 기록한다."""

    def __init__(self, connection: sqlite3.Connection, package: PackageSource):
        """! @brief 자료 역할과 공급사별 제품 표기 그룹을 준비한다."""
        self.connection = connection
        self.package = package
        self.products = set()
        self.stackups = {}
        self.product_summaries = {}
        if "catalog/products.json" in package.files:
            summaries = package.read_json("catalog/products.json")
            if not isinstance(summaries, list):
                raise CatalogError("E_SCHEMA", "제품 표기 요약은 배열이어야 합니다.")
            for item in summaries:
                if not isinstance(item, dict):
                    raise CatalogError("E_SCHEMA", "제품 표기 요약의 행은 객체여야 합니다.")
                if any(not isinstance(item.get(field), str) or not item[field] for field in ("organization", "product")):
                    raise CatalogError("E_SCHEMA", "제품 표기 요약에 업체와 제품 문자열이 필요합니다.")
                key = (item["organization"], item["product"])
                self.product_summaries.setdefault(key, []).append(item)
        columns = ",".join(OBSERVATION_COLUMNS)
        placeholders = ",".join("?" for _ in OBSERVATION_COLUMNS)
        self.statement = f"INSERT INTO observations ({columns}) VALUES ({placeholders})"

    def product(self, record: dict) -> str:
        """! @brief 업체의 제품 표기를 실제 원자재 공급사 제품과 자동 병합하지 않는다."""
        identity = ProductIdentity(
            record["manufacturer"], record["product"], record["dataset_role"], record.get("laminate_manufacturer"),
        )
        if identity.product_id not in self.products:
            source = {
                "publisher": identity.publisher, "product": identity.product,
                "dataset_role": identity.dataset_role, "laminate_manufacturer": identity.laminate_manufacturer,
                "identity_semantics": "published_product_label_group_not_verified_unique_material",
                "published_summaries": self.product_summaries.get((identity.publisher, identity.product), []),
            }
            raw, digest = _encoded(source)
            _insert(self.connection, "products", {
                "product_id": identity.product_id, "publisher": identity.publisher,
                "product": identity.product, "dataset_role": identity.dataset_role,
                "laminate_manufacturer": identity.laminate_manufacturer, "raw_json": raw, "raw_sha256": digest,
            })
            self.products.add(identity.product_id)
        return identity.product_id

    def stackup(self, record: dict) -> str | None:
        """! @brief 공개 적층 라벨을 묶고 상충하는 치수는 하나의 값으로 확정하지 않는다."""
        if not record.get("stackup_id"):
            return None
        identity = StackupIdentity(record["manufacturer"], record["stackup_id"])
        if identity.stackup_id not in self.stackups:
            self.stackups[identity.stackup_id] = {
                "publisher": identity.publisher, "source_stackup_id": identity.source_stackup_id,
                "labels": set(), "layer_counts": set(), "nominal_thicknesses_mm": set(), "source_ids": set(),
            }
            raw, digest = _encoded({"publisher": identity.publisher, "source_stackup_id": identity.source_stackup_id})
            _insert(self.connection, "stackups", {
                "stackup_id": identity.stackup_id, "publisher": identity.publisher,
                "source_stackup_id": identity.source_stackup_id, "label": identity.source_stackup_id,
                "raw_json": raw, "raw_sha256": digest,
            })
        summary = self.stackups[identity.stackup_id]
        summary["labels"].add(record.get("stackup_display_name") or record.get("stackup_name") or identity.source_stackup_id)
        summary["source_ids"].add(record["source_id"])
        for field in ("copper_layer_count", "board_layers"):
            if record.get(field) is not None:
                summary["layer_counts"].add(record[field])
        for field in ("nominal_board_thickness_mm", "board_nominal_thickness_mm"):
            if record.get(field) is not None:
                summary["nominal_thicknesses_mm"].add(record[field])
        return identity.stackup_id

    def write(self, record: dict) -> None:
        """! @brief 조회 열과 원문 JSON을 분리하며 숫자 보간과 기본값 채우기를 하지 않는다."""
        values = {column: record.get(column) for column in OBSERVATION_COLUMNS}
        values["publisher"] = record["manufacturer"]
        values["product_id"] = self.product(record)
        values["stackup_id"] = self.stackup(record)
        values["raw_json"], values["raw_sha256"] = _encoded(record)
        values["properties_json"] = canonical_json(property_views(record))
        self.connection.execute(self.statement, tuple(values[column] for column in OBSERVATION_COLUMNS))
        self.connection.executemany(
            "INSERT INTO observation_flags(record_id,flag) VALUES (?,?)",
            ((record["record_id"], flag) for flag in flags(record)),
        )

    def finish(self) -> None:
        """! @brief 여러 관측에서 합의된 치수만 검색 열에 제시하고 모든 후보를 상세에 남긴다."""
        for identity, summary in self.stackups.items():
            source = {key: sorted(value) if isinstance(value, set) else value for key, value in summary.items()}
            source["identity_semantics"] = "published_stackup_label_group_not_verified_physical_stack"
            raw, digest = _encoded(source)
            layers = source["layer_counts"][0] if len(source["layer_counts"]) == 1 else None
            thickness = source["nominal_thicknesses_mm"][0] if len(source["nominal_thicknesses_mm"]) == 1 else None
            self.connection.execute(
                "UPDATE stackups SET label=?,layer_count=?,nominal_thickness_mm=?,raw_json=?,raw_sha256=? WHERE stackup_id=?",
                (source["labels"][0], layers, thickness, raw, digest, identity),
            )


def _observations(connection: sqlite3.Connection, package: PackageSource, index: dict) -> dict:
    """! @brief 모든 관측의 타입, 외래 키, 원문 필드와 정규 해시를 전수 확인한다."""
    schema = package.read_json("catalog/schema.json")
    if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list):
        raise CatalogError("E_SCHEMA", "관측 스키마에는 필드 배열이 필요합니다.")
    definitions = {}
    for item in schema["fields"]:
        if not isinstance(item, dict) or not isinstance(item.get("field"), str) or not item["field"]:
            raise CatalogError("E_SCHEMA", "관측 스키마의 필드 행과 이름이 잘못되었습니다.")
        if not isinstance(item.get("observed_types"), str):
            raise CatalogError("E_SCHEMA", "관측 스키마의 타입 선언은 문자열이어야 합니다.")
        if set(item["observed_types"].split(",")) - {"", "str", "int", "float", "bool", "dict", "list"}:
            raise CatalogError("E_SCHEMA", "관측 스키마에 지원하지 않는 타입이 있습니다.")
        if item["field"] in definitions:
            raise CatalogError("E_SCHEMA", "관측 스키마에 중복 필드가 있습니다.")
        definitions[item["field"]] = item
    writer = _ObservationWriter(connection, package)
    used_fields = set()
    partitions = set()
    count = 0
    for partition in index["partitions"]:
        if not isinstance(partition, dict):
            raise CatalogError("E_SCHEMA", "관측 분할 행은 객체여야 합니다.")
        if not isinstance(partition.get("path"), str) or not isinstance(partition.get("publisher"), str):
            raise CatalogError("E_SCHEMA", "관측 분할에 경로와 공개 업체 문자열이 필요합니다.")
        if type(partition.get("records")) is not int or partition["records"] < 0:
            raise CatalogError("E_SCHEMA", "관측 분할의 행수는 음수가 아닌 정수여야 합니다.")
        if partition["path"] in partitions:
            raise CatalogError("E_SCHEMA", "관측 분할 경로가 중복됩니다.")
        partitions.add(partition["path"])
        for record in package.records(partition):
            validate_observation(record, definitions, package)
            writer.write(record)
            used_fields.update(record)
            count += 1
    if count != index.get("record_count") or used_fields != definitions.keys():
        raise CatalogError("E_SCHEMA", "관측 총수 또는 실제 필드 집합이 선언과 다릅니다.")
    digest = hashlib.sha256()
    for row in connection.execute("SELECT raw_json FROM observations ORDER BY record_id"):
        digest.update(row[0].encode("utf-8") + b"\n")
    if digest.hexdigest() != index.get("canonical_sha256"):
        raise CatalogError("E_HASH", "관측 원문 전체의 정규 SHA-256이 일치하지 않습니다.")
    writer.finish()
    return {"observations": count, "observation_fields": len(definitions), "partitions": len(partitions)}


def _output_path(source_root: Path, output: Path, overwrite: bool) -> tuple[Path, str | None]:
    """! @brief 원문 영역과 임의 기존 문서의 덮어쓰기를 허용하지 않는다."""
    original = Path(output).absolute()
    resolved = original.resolve()
    if original.is_symlink() or resolved.is_relative_to(source_root):
        raise CatalogError("E_PATH", "출력은 원문 패키지 밖의 별도 파일이어야 합니다.")
    if resolved.exists():
        if not overwrite:
            raise CatalogError("E_EXISTS", "기존 카탈로그를 덮어쓰려면 명시적 옵션이 필요합니다.")
        if not resolved.is_file():
            raise CatalogError("E_PATH", "출력 경로가 파일이 아닙니다.")
        try:
            with closing(sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)) as database:
                version = database.execute("PRAGMA user_version").fetchone()[0]
                row = database.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
                if version != CATALOG_USER_VERSION or row is None or decode_json(row[0]) != CATALOG_SCHEMA:
                    raise CatalogError("E_VERSION", "기존 파일은 지원하는 TraceWave 카탈로그가 아닙니다.")
        except sqlite3.Error as error:
            raise CatalogError("E_VERSION", "임의 파일이나 다른 SQLite DB를 덮어쓸 수 없습니다.") from error
        return resolved, file_digest(resolved)
    return resolved, None


def build_catalog(source_root: Path, output: Path, *, overwrite: bool = False) -> dict:
    """! @brief 실패하면 기존 DB를 보존하고 검증된 파생 인덱스만 원자적으로 발행한다.

    @param source_root 읽기 전용 수집 자료 패키지이다.
    @param output 원문 영역 밖에 만들 카탈로그 SQLite 파일이다.
    @param overwrite 지원하는 기존 카탈로그만 명시적으로 교체한다.
    @return 원문 식별자, 처리 수와 검증 결과이다. 해석 가능 판정을 포함하지 않는다.
    """
    source_root = Path(source_root).resolve()
    output, previous_hash = _output_path(source_root, output, overwrite)
    package = PackageSource(source_root)
    if output.exists():
        for relative in package.files:
            path = package.path(relative, must_exist=False)
            if path.is_file() and output.samefile(path):
                raise CatalogError("E_PATH", "출력이 원문 파일과 같은 hardlink입니다.")
    index = package.read_json("data/observations/index.json")
    if not isinstance(index, dict) or index.get("schema") != "rfad.reference.observations/1":
        raise CatalogError("E_VERSION", "지원하지 않는 관측 인덱스입니다.")
    if not isinstance(index.get("partitions"), list):
        raise CatalogError("E_SCHEMA", "관측 인덱스에 분할 배열이 필요합니다.")
    if type(index.get("record_count")) is not int or index["record_count"] < 0:
        raise CatalogError("E_SCHEMA", "관측 총수는 음수가 아닌 정수여야 합니다.")
    if not PackageSource._hash(index.get("canonical_sha256")):
        raise CatalogError("E_SCHEMA", "관측 인덱스의 정규 SHA-256 표현이 잘못되었습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".catalog-", suffix=".sqlite", dir=output.parent)
    os.close(descriptor)
    temporary = Path(name)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA cache_size=-8192")
        connection.execute("PRAGMA temp_store=FILE")
        create_schema(connection)
        _sources(connection, package)
        counts = _observations(connection, package, index)
        from rfad.catalog.native import import_native
        native = import_native(connection, source_root, package)
        create_indexes(connection)
        for table in ("sources", "products", "stackups", "native_templates", "native_components", "native_evidence"):
            counts[table] = connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
        meta = {
            "schema": CATALOG_SCHEMA,
            "import_version": CATALOG_IMPORT_VERSION,
            "catalog_id": stable_id("catalog", CATALOG_SCHEMA, CATALOG_IMPORT_VERSION,
                                    package.manifest_sha256, index["canonical_sha256"]),
            "source_root": str(source_root), "source_index_sha256": package.file_sha256("data/observations/index.json"),
            "source_canonical_sha256": index["canonical_sha256"], "source_manifest_sha256": package.manifest_sha256,
            "created_at": datetime.now(timezone.utc).isoformat(), "counts": counts,
            "readiness": "not_assessed", "review_meaning": REVIEW_MEANING, "native_import": native,
        }
        connection.executemany("INSERT INTO meta(key,value) VALUES (?,?)", ((key, canonical_json(value)) for key, value in meta.items()))
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise CatalogError("E_SCHEMA", "카탈로그 외래 키가 일치하지 않습니다.")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CatalogError("E_SCHEMA", "카탈로그 SQLite 무결성 검사가 실패했습니다.")
        connection.commit()
        connection.close()
        connection = None
        package.verify_unchanged()
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        output_bytes = temporary.stat().st_size
        output_sha256 = file_digest(temporary)
        if previous_hash is None:
            os.link(temporary, output)
            temporary.unlink()
        else:
            if not output.exists() or file_digest(output) != previous_hash:
                raise CatalogError("E_CONFLICT", "구축 중 기존 카탈로그가 변경되었습니다.")
            os.replace(temporary, output)
        return {**meta, "output": str(output), "output_bytes": output_bytes, "output_sha256": output_sha256}
    except sqlite3.Error as error:
        raise CatalogError("E_SCHEMA", "카탈로그 중복 ID, 외래 키 또는 SQLite 계약이 잘못되었습니다.", details={"reason": str(error)}) from error
    except (OSError, OverflowError, TypeError, KeyError) as error:
        raise CatalogError("E_CATALOG", "카탈로그를 만들 수 없습니다. 기존 파일을 보존했습니다.", details={"reason": str(error)}) from error
    finally:
        if connection is not None:
            connection.close()
        for path in (temporary, Path(str(temporary) + "-journal")):
            if path.exists():
                path.unlink()
