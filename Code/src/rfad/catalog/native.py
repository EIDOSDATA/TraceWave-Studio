"""! @brief 검증 가능한 제조업체 원문 적층을 조회 카탈로그로 가져온다."""

from pathlib import Path
import sqlite3

from rfad.catalog.models import CatalogError
from rfad.catalog.native_common import NATIVE_DIRECTORY, NativePackage, NativeWriter
from rfad.catalog.native_jlc import import_jlc
from rfad.catalog.native_pcbway import import_pcbway
from rfad.catalog.native_we import import_we


def import_native(
    connection: sqlite3.Connection, source_root: Path, package: NativePackage,
) -> dict:
    """! @brief 원문을 변경하지 않고 세 업체의 구성행과 보조 증거를 원자적으로 저장한다.

    @param connection 출처와 정규화 관측이 먼저 입력된 SQLite 연결이다.
    @param source_root 공개 자료 패키지의 루트이며 검증된 읽기는 package가 수행한다.
    @param package 파일 경로, 크기, 유한 JSON과 해시를 검사하는 읽기 전용 공급자이다.
    @return 파일별 보존 위치, 업체별 개수와 검토 상태를 반환한다.
    """
    if not isinstance(source_root, Path):
        raise CatalogError("catalog_native_path", "자료 패키지 경로가 필요합니다.")
    writer = NativeWriter(connection, package)
    declared_files = {name.replace("\\", "/") for name in package.files
                      if name.replace("\\", "/").startswith(NATIVE_DIRECTORY)}
    if not declared_files:
        if (source_root / "data" / "fabricator_native_metadata").exists():
            raise CatalogError("catalog_native_coverage", "원시 적층 폴더의 파일이 패키지 명세에 없습니다.")
        return {**writer.counts, "publishers": {}, "source_files": {},
                "readiness": "not_assessed", "physical_layers_created": 0}
    connection.execute("SAVEPOINT catalog_native_import")
    try:
        publishers = {
            "JLCPCB": import_jlc(writer),
            "PCBWay": import_pcbway(writer),
            "Wurth Elektronik": import_we(writer),
        }
        for filename, kind in (
            ("fab_jlc_material_definitions.json", "jlc_material_definitions"),
            ("fab_nonpositive_thickness_audit.json", "nonpositive_thickness_audit"),
        ):
            relative, value = writer.read(filename)
            writer.evidence(kind, relative, "", value)
            writer.coverage(relative, "native_evidence:complete_document", 1)
        if declared_files != set(writer.files):
            raise CatalogError("catalog_native_coverage", "명세에 있는 원시 적층 파일이 모두 보존되지 않았습니다.",
                               details={"unread_files": sorted(declared_files - set(writer.files))})
        violations = connection.execute("PRAGMA foreign_key_check").fetchmany(1)
        if violations:
            raise CatalogError("catalog_native_foreign_key", "원시 적층의 출처 연결이 유효하지 않습니다.")
        connection.execute("RELEASE catalog_native_import")
    except Exception:
        connection.execute("ROLLBACK TO catalog_native_import")
        connection.execute("RELEASE catalog_native_import")
        raise
    return {
        **writer.counts, "publishers": publishers, "source_files": writer.files,
        "readiness": "not_assessed", "physical_layers_created": 0,
    }
