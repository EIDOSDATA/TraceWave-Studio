"""! @brief 교환 worker의 고정 기술도면 출력과 읽기 전용 재검수 진입점을 제공한다."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from rfad.application.canonical import canonical_bytes
from rfad.domain.drawing_layout import PROFILE, fail, layout
from rfad.adapters.exchange.drawing_readers import read_dxf, read_pdf, read_svg, require
from rfad.adapters.exchange.drawing_writers import write_dxf, write_pdf, write_svg


MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
REPORT_SCHEMA = "rfad.exchange-verification/0.1"


def _hash(raw):
    """! @brief 파일 바이트 해시를 스냅샷 canonical 내용 해시와 구분한다."""
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    """! @brief 크기와 재분석 지점을 확인하고 유한 파일 바이트만 읽는다."""
    stat = path.lstat()
    if path.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400 or not path.is_file() or stat.st_size > MAX_FILE_BYTES:
        fail("출력 파일의 종류 또는 크기가 교환 profile 밖입니다.", "exchange.files", "E_RESOURCE")
    with path.open("rb") as stream:
        result = stream.read(MAX_FILE_BYTES + 1)
    if len(result) > MAX_FILE_BYTES:
        fail("출력 파일이 읽기 상한을 초과했습니다.", "exchange.files", "E_RESOURCE")
    return result


def _record(path, role, media):
    """! @brief 확정된 출력 파일의 크기와 바이트 해시를 만든다."""
    raw = _read(path)
    return {"path": path.name, "role": role, "media_type": media, "bytes": len(raw), "sha256": _hash(raw)}


def _names(format_name, pages):
    """! @brief 임의 경로 입력 없이 쪽 번호에 따른 닫힌 파일명을 만든다."""
    if format_name == "pdf":
        return ["drawing.pdf"]
    if format_name not in ("svg", "dxf"):
        fail("지원하지 않는 기술도면 파일 형식입니다.", "format")
    return ["drawing-" + str(index + 1).zfill(2) + "." + format_name for index in range(len(pages))]


def _geometry_report(data, output, pages):
    """! @brief writer 경로와 분리된 실제 파일 parser를 실행한다."""
    names = _names(data["format"], pages)
    readers = []
    if data["format"] == "pdf":
        readers.append(read_pdf(output / names[0], pages))
    else:
        reader = read_svg if data["format"] == "svg" else read_dxf
        for name, page in zip(names, pages):
            readers.append(reader(output / name, page))
    annotation_review = next((page["annotation_review"] for page in pages if "annotation_review" in page), None)
    return {"schema": REPORT_SCHEMA, "status": "passed_profile", "profile": PROFILE,
            **({"annotation_review": annotation_review} if annotation_review is not None else {}),
            "checks": ["파일 parser 재열기", "mm와 용지 크기", "실제 선/원호 경계", "구멍과 채움 규칙",
                       "연관 치수 원문과 고정 개정", "객체/net/layer 추적", "뒤면 방향과 상세 영역"],
            "reader": {"formats": readers, "separate_writer_and_reader_paths": True},
            "kernel_independent": False, "manufacturing_verified": False, "physics_verified": False,
            "recipient_application_verified": False,
            "limits": {"svg_font_embedded": False, "dxf_font_embedded": False,
                       "pdf_is_fabrication_geometry": False, "manufacturing_tolerance": None,
                       "independent_kernel_acceptance": "not_performed",
                       "external_environment_projection": "not_in_2d_profile_source_preserved",
                       "section": "실제 기판 중앙 Y 절단면; 두께 과장 없음",
                       "board_outline": "외형 중심선; stroke를 절삭 공차로 해석하지 않음"}}


def generate(data, output, *, font_path=None):
    """! @brief 검토와 같은 배치로 생성/검수하고 manifest를 마지막에 기록한다.

    @param data 서비스가 봉인한 rfad.exchange-input/0.1 원본.
    @param output worker가 소유하는 비어 있는 staging 출력 폴더.
    @param font_path worker runtime이 검증한 로컬 TTF 파일; 임의 입력 경로가 아니다.
    @return 게시 전 파일 목록과 명시적 제한을 포함하는 manifest.
    """
    output = Path(output)
    if not output.is_dir() or output.is_symlink() or getattr(output.lstat(), "st_file_attributes", 0) & 0x400:
        fail("worker의 안전한 staging 출력 폴더가 필요합니다.", "exchange.output", "E_IO")
    if any(output.iterdir()):
        fail("출력 staging은 비어 있어야 합니다. 기존 파일을 덮어쓰지 않습니다.", "exchange.output", "E_CONFLICT")
    original = canonical_bytes(data)
    pages = layout(data)
    names = _names(data["format"], pages)
    if data["format"] == "pdf":
        write_pdf(pages, output / names[0], font_path)
    else:
        writer = write_svg if data["format"] == "svg" else write_dxf
        for name, page in zip(names, pages):
            writer(page, output / name)
    report = _geometry_report(data, output, pages)
    require(canonical_bytes(data) == original, "출력 중 원본 입력이 변경되었습니다.")
    media = {"pdf": "application/pdf", "svg": "image/svg+xml", "dxf": "image/vnd.dxf"}[data["format"]]
    records = [_record(output / name, "drawing" if data["options"]["mode"] == "drawing" else "fabrication_geometry", media) for name in names]
    (output / "validation.json").write_bytes(canonical_bytes(report))
    records.append(_record(output / "validation.json", "verification", "application/json"))
    sidecar = {"schema": "rfad.exchange-sidecar/0.1", "snapshot": deepcopy(data["snapshot"]), "profile": PROFILE,
               "run_id": data["run_id"], "input_sha256": _hash(original), "format": data["format"],
               "source_semantics": deepcopy(data["projection"]["source_semantics"]), "options": deepcopy(data["options"]),
               "source_bindings": {"names": deepcopy(data["names"]), "dimensions": deepcopy(data["dimensions"])},
               "files": deepcopy(records), "verification": report}
    (output / "sidecar.json").write_bytes(canonical_bytes(sidecar))
    records.append(_record(output / "sidecar.json", "source", "application/json"))
    if sum(item["bytes"] for item in records) > MAX_PACKAGE_BYTES:
        fail("전체 출력 패키지의 유한 바이트 상한을 초과했습니다.", "exchange.files", "E_RESOURCE")
    manifest = {"schema": "rfad.exchange-package/0.1", "profile": PROFILE,
                "source_snapshot": deepcopy(data["snapshot"]), "run_id": data["run_id"],
                "status": "generated_unverified", "format": data["format"], "files": records, "verification": report}
    (output / "manifest.json").write_bytes(canonical_bytes(manifest))
    return manifest


def verify(data, output, manifest):
    """! @brief 이미 게시된 패키지를 변경하지 않고 전체 원문/바이트/실제 형상을 재검수한다."""
    output = Path(output)
    require(manifest.get("schema") == "rfad.exchange-package/0.1" and manifest.get("profile") == PROFILE,
            "출력 패키지 profile이 다릅니다.")
    require(manifest.get("source_snapshot") == data["snapshot"] and manifest.get("run_id") == data["run_id"] and manifest.get("format") == data["format"],
            "출력 패키지의 원본 소유권 또는 실행 ID가 다릅니다.")
    pages = layout(data)
    names = _names(data["format"], pages)
    records = manifest.get("files")
    require(type(records) is list and [record.get("path") for record in records] == names + ["validation.json", "sidecar.json"],
            "파일 목록에 누락, 추가 또는 경로 변경이 있습니다.")
    require(sum(record["bytes"] for record in records) <= MAX_PACKAGE_BYTES, "출력 패키지의 바이트 상한이 다릅니다.")
    for record in records:
        raw = _read(output / record["path"])
        require(len(raw) == record["bytes"] and _hash(raw) == record["sha256"], "출력 파일의 크기 또는 바이트 해시가 다릅니다.")
    source = json.loads(_read(output / "sidecar.json"))
    require(source.get("schema") == "rfad.exchange-sidecar/0.1" and source.get("profile") == PROFILE
            and source.get("snapshot") == data["snapshot"] and source.get("run_id") == data["run_id"]
            and source.get("input_sha256") == _hash(canonical_bytes(data)) and source.get("format") == data["format"]
            and source.get("source_semantics") == data["projection"]["source_semantics"] and source.get("options") == data["options"]
            and source.get("source_bindings") == {"names": data["names"], "dimensions": data["dimensions"]}
            and source.get("files") == records[:-1], "출처/미정값/객체 바인딩 원문이 고정 입력과 다릅니다.")
    previous = json.loads(_read(output / "validation.json"))
    require(previous == manifest.get("verification") == source.get("verification"), "패키지의 검증 기록들이 서로 다릅니다.")
    return _geometry_report(data, output, pages)
