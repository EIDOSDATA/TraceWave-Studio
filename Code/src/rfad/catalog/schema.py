"""! @brief 원문 JSON과 조회 열을 분리하는 재생성 전용 SQLite 스키마이다."""

import sqlite3

from rfad.catalog.models import CATALOG_USER_VERSION


TABLES = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY, publisher TEXT NOT NULL, title TEXT NOT NULL,
    url TEXT NOT NULL, local_path TEXT, local_available INTEGER NOT NULL CHECK(local_available IN (0,1)),
    raw_json TEXT NOT NULL, raw_sha256 TEXT NOT NULL
);
CREATE TABLE products (
    product_id TEXT PRIMARY KEY, publisher TEXT NOT NULL, product TEXT NOT NULL,
    dataset_role TEXT NOT NULL, laminate_manufacturer TEXT, raw_json TEXT NOT NULL, raw_sha256 TEXT NOT NULL
);
CREATE TABLE stackups (
    stackup_id TEXT PRIMARY KEY, publisher TEXT NOT NULL, source_stackup_id TEXT NOT NULL,
    label TEXT NOT NULL, layer_count INTEGER, nominal_thickness_mm REAL,
    native_available INTEGER NOT NULL DEFAULT 0 CHECK(native_available IN (0,1)),
    raw_json TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
    UNIQUE(publisher, source_stackup_id)
);
CREATE TABLE observations (
    record_id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(product_id),
    stackup_id TEXT REFERENCES stackups(stackup_id), source_id TEXT NOT NULL REFERENCES sources(source_id),
    publisher TEXT NOT NULL, product TEXT NOT NULL, dataset_role TEXT NOT NULL,
    material_form TEXT, value_type TEXT, frequency_ghz REAL, df_frequency_ghz REAL,
    frequency_min_ghz REAL, frequency_max_ghz REAL,
    dk REAL, dk_min REAL, dk_max REAL, df REAL, df_min REAL, df_max REAL,
    thickness_mm REAL, source_file TEXT, raw_json TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
    properties_json TEXT NOT NULL
);
CREATE TABLE observation_flags (
    record_id TEXT NOT NULL REFERENCES observations(record_id), flag TEXT NOT NULL,
    PRIMARY KEY(record_id, flag)
);
CREATE TABLE native_templates (
    template_id TEXT PRIMARY KEY, stackup_id TEXT REFERENCES stackups(stackup_id),
    publisher TEXT NOT NULL, template_key TEXT NOT NULL, kind TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id), source_path TEXT NOT NULL,
    source_pointer TEXT NOT NULL, source_sha256 TEXT NOT NULL, raw_json TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL, flags_json TEXT NOT NULL
);
CREATE TABLE native_components (
    component_id TEXT PRIMARY KEY, template_id TEXT NOT NULL REFERENCES native_templates(template_id),
    stackup_id TEXT REFERENCES stackups(stackup_id), publisher TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id), source_path TEXT NOT NULL,
    source_pointer TEXT NOT NULL, source_sha256 TEXT NOT NULL, component_order INTEGER NOT NULL, kind TEXT NOT NULL,
    raw_json TEXT NOT NULL, raw_sha256 TEXT NOT NULL, flags_json TEXT NOT NULL
);
CREATE TABLE native_stackup_links (
    template_id TEXT NOT NULL REFERENCES native_templates(template_id),
    stackup_id TEXT NOT NULL REFERENCES stackups(stackup_id), relation TEXT NOT NULL,
    reason TEXT NOT NULL, PRIMARY KEY(template_id, stackup_id)
);
CREATE TABLE native_evidence (
    evidence_id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_path TEXT NOT NULL,
    source_pointer TEXT NOT NULL, raw_json TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);
"""

INDEXES = """
CREATE INDEX observations_publisher ON observations(publisher, record_id);
CREATE INDEX observations_product ON observations(product_id, record_id);
CREATE INDEX observations_stackup ON observations(stackup_id, record_id);
CREATE INDEX observations_frequency ON observations(frequency_ghz, record_id);
CREATE INDEX observations_df_frequency ON observations(df_frequency_ghz, record_id);
CREATE INDEX observations_role ON observations(dataset_role, record_id);
CREATE INDEX observations_source ON observations(source_id, record_id);
CREATE INDEX flags_name ON observation_flags(flag, record_id);
CREATE INDEX products_publisher ON products(publisher, product, product_id);
CREATE INDEX stackups_publisher ON stackups(publisher, layer_count, stackup_id);
CREATE INDEX native_templates_publisher ON native_templates(publisher, template_id);
CREATE INDEX native_components_template ON native_components(template_id, component_order, component_id);
CREATE INDEX native_components_publisher ON native_components(publisher, component_id);
"""


def create_schema(connection: sqlite3.Connection) -> None:
    """! @brief 새 임시 DB에 외래 키가 활성화된 스키마를 만든다."""
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA user_version=" + str(CATALOG_USER_VERSION))
    connection.executescript(TABLES)


def create_indexes(connection: sqlite3.Connection) -> None:
    """! @brief 대량 삽입 후 읽기 전용 조회용 인덱스를 생성한다."""
    connection.executescript(INDEXES)
