"""! @brief 봉인 KiCad 패키지에서 IPC-2581C와 ODB++ 교환 후보를 만든다."""

import argparse
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from rfad.adapters.exchange import kicad_reader, pcb
from rfad.adapters.exchange.ipc2581_reader import read as read_ipc2581
from rfad.adapters.exchange.odb_reader import read as read_odb
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError


SOURCE = ("board.kicad_pcb", "board.kicad_pro", "sidecar.json", "validation.json")
FORMATS = ("ipc2581", "odb")


def _input_package(folder):
    """! @brief 원본 패키지와 sidecar의 게시 파일/스냅샷/검증 상태를 대조한다."""
    manifest_bytes = pcb._read(folder / "manifest.json")
    manifest = json.loads(manifest_bytes)
    package = manifest.get("worker_package")
    if (manifest.get("schema") != "rfad.exchange-manifest/0.1" or manifest.get("profile") != pcb.PROFILES["kicad_pcb"]
            or type(package) is not dict or package.get("schema") != "rfad.exchange-package/0.1"
            or package.get("format") != "kicad_pcb"):
        raise ValueError("TraceWave Studio가 게시한 KiCad 보드 패키지가 필요합니다.")
    files = {name: pcb._read(folder / name) for name in SOURCE}
    records = [pcb._record(name, files[name]) for name in ("board.kicad_pcb", "board.kicad_pro", "validation.json", "sidecar.json")]
    published = manifest["artifacts"]
    actual = {PurePosixPath(item["uri"]).name: item for item in published}
    if (package["files"] != records or len(published) != len(records) or set(actual) != set(files)
            or any(any(actual[record["path"]].get(key) != record[key] for key in ("sha256", "bytes", "role", "media_type"))
                   for record in records)):
        raise ValueError("게시된 KiCad 패키지의 파일 해시 또는 내용이 변경됐습니다.")
    sidecar = json.loads(files["sidecar.json"])
    validation = json.loads(files["validation.json"])
    snapshot = manifest["snapshot"]
    if (sidecar.get("schema") != "rfad.exchange-sidecar/0.1" or sidecar.get("snapshot") != snapshot
            or package.get("source_snapshot") != snapshot
            or canonical_hash(sidecar["source_semantics"]) != snapshot["content_hash"]
            or any(sidecar.get(key) != package.get(key) for key in ("profile", "run_id", "format", "verification"))
            or any(manifest.get(key) != package.get(key) for key in ("profile", "run_id", "verification"))
            or sidecar.get("files") != records[:-1] or sidecar.get("input_sha256") != manifest["input_sha256"]
            or validation != manifest["verification"] or validation.get("status") != "passed_profile"):
        raise ValueError("PCB 원본 snapshot, sidecar, 검수 파일이 서로 일치해야 합니다.")
    return manifest, {**files, "manifest.json": manifest_bytes}


def _run(exe, arguments, stage):
    """! @brief 사용자 파일명과 인자는 shell을 거치지 않으며 시간 제한을 적용한다."""
    process = subprocess.run([str(exe), *arguments], cwd=stage, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=90, check=False,
                             encoding="utf-8", errors="replace")
    if process.returncode:
        message = (process.stderr or process.stdout).strip()[-2000:]
        raise ValueError(f"KiCad 명령이 종료 코드 {process.returncode}로 실패했습니다. {message}")
    return process.stdout.strip()


def verify_padstacks(source, summary, format_name):
    """! @brief 원문 custom padstack의 층별 형상, 회전 및 도금 홀이 최종 제조 파일에 있는지 검사한다."""
    copper = [row["name"] for row in source["layers"] if row["name"].endswith(".Cu")]
    for pad in source["shapes"]:
        if "padstack_layers" not in pad:
            continue
        center = pad["center_mm"]
        holes = [row for row in summary["editable_holes"]
                 if row["plating"] == "plated" and math.dist(row["center_mm"], center) <= 2e-6
                 and abs(row["diameter_mm"] - pad["drill"]["size_mm"][0]) <= 2e-6]
        if len(holes) != 1:
            raise ValueError(f"{format_name}: 층별 관통 패드의 완성 홀이 누락됐습니다.")
        bound = [row for row in summary["editable_pads"] if row["source_id"] in holes[0]["pads"]]
        for layer in copper:
            expected = pad["padstack_layers"].get(layer, pad)
            matching = [row for row in bound if row["layer"].casefold() == layer.casefold()]
            actual = matching[0] if len(matching) == 1 else {}
            kind = actual.get("pad_shape", "circle")
            size = actual.get("size_mm", [actual.get("diameter_mm")] * 2)
            if ("source_id" not in actual or kind != ("rectangle" if expected["pad_shape"] == "rect" else "circle")
                    or None in size or math.dist(size, expected["size_mm"]) > 2e-6
                    or kind == "rectangle" and abs(math.remainder(actual["rotation_deg"]-pad["rotation_deg"], 180)) > 1e-6):
                raise ValueError(f"{format_name}: 층별 관통 패드의 {layer} 도형이 원문과 다릅니다.")


def export_package(source, destination, executable, formats, *, manifest_sha256=None, workspace=None):
    """! @brief 원본을 재작성하지 않고 두 출력과 추적 기록을 한 ZIP으로 원자 게시한다."""
    if not formats or set(formats) - set(FORMATS) or len(formats) != len(set(formats)):
        raise ValueError("IPC-2581 또는 ODB++를 한 번씩 선택하십시오.")
    source = source.resolve(strict=True)
    exe = executable.resolve(strict=True)
    destination = destination.parent.resolve(strict=True) / destination.name
    if destination.exists() or destination.is_symlink() or destination.suffix.lower() != ".zip":
        raise ValueError("기존 파일과 다른 새 ZIP 출력 경로를 지정하십시오.")
    if destination.is_relative_to(source):
        raise ValueError("게시 원본 패키지 폴더 밖에 새 ZIP을 저장하십시오.")
    if workspace is not None:
        root = workspace.resolve(strict=True)
        if not source.is_relative_to(root) or destination.is_relative_to(root):
            raise ValueError("작업 영역 안의 게시 원본과 작업 영역 밖의 새 ZIP을 지정하십시오.")
    manifest, source_files = _input_package(source)
    if manifest_sha256 is not None and pcb._hash(source_files["manifest.json"]) != manifest_sha256:
        raise ValueError("선택한 게시 기록의 manifest 해시와 현재 원본이 다릅니다.")
    with TemporaryDirectory(prefix=".tracewave-cam-", dir=destination.parent) as folder:
        stage = Path(folder)
        version = _run(exe, ["version"], stage)
        if not 0 < len(version) <= 128:
            raise ValueError("KiCad 버전 문자열을 확인할 수 없습니다.")
        for name in SOURCE[:2]:
            (stage / name).write_bytes(source_files[name])
        board = kicad_reader.read(source_files["board.kicad_pcb"])
        outputs = {}
        for mode in formats:
            name, options = (("board.xml", ["--version", "C"]) if mode == "ipc2581"
                             else ("board-odb.zip", ["--compression", "zip"]))
            output = stage / name
            arguments = ["pcb", "export", mode, "--units", "mm", "--precision", "6",
                         *options, "--output", name, "board.kicad_pcb"]
            _run(exe, arguments, stage)
            raw = pcb._read(output)
            summary = read_ipc2581(raw) if mode == "ipc2581" else read_odb(raw)
            if mode == "ipc2581" and (summary["units"] != "MILLIMETER" or not any(
                    step["profile"] and step["profile"]["outer"] for step in summary["steps"])):
                raise ValueError("IPC-2581C 파일에 mm 단위의 보드 외곽이 필요합니다.")
            if mode == "odb" and summary["steps"] != summary["steps_with_eda"]:
                raise ValueError("ODB++ 보드 프로파일에 대응하는 EDA 자료가 누락됐습니다.")
            verify_padstacks(board, summary, mode)
            outputs[name] = {"bytes": len(raw), "sha256": pcb._hash(raw), "inspection": summary,
                             "arguments": arguments}
        report = {"schema": "rfad.manufacturing-exchange-candidate/0.1",
                  "source_snapshot": manifest["snapshot"], "source_run_id": manifest["run_id"],
                  "source_manifest_sha256": pcb._hash(source_files["manifest.json"]),
                  "kicad_version": version, "outputs": outputs, "recipient_roundtrip": "not_verified",
                  "manufacturing_conditions": "source_sidecar", "manufacturing_verified": False}
        combined = stage / "combined.zip"
        with ZipFile(combined, "x", compression=ZIP_DEFLATED) as archive:
            for name in outputs:
                archive.write(stage / name, name)
            for name, raw in source_files.items():
                archive.writestr("source/" + name, raw)
            archive.writestr("report.json", canonical_bytes(report))
        # @brief 같은 파일시스템에서 완성 ZIP만 게시하고 동시 작업이 만든 기존 파일을 보호한다.
        if os.name == "nt":
            os.rename(combined, destination)
        else:
            os.link(combined, destination)
    return report


def main():
    """! @brief GUI에서 내려받은 KiCad 패키지 폴더를 명시한 출력 경로로 변환한다."""
    parser = argparse.ArgumentParser(description="TraceWave KiCad 패키지에서 IPC-2581C 및 ODB++ 후보 ZIP 생성")
    parser.add_argument("--input", required=True, type=Path, help="압축을 푼 Studio KiCad 보드 패키지 폴더")
    parser.add_argument("--output", required=True, type=Path, help="새 ZIP 파일")
    parser.add_argument("--kicad-cli", required=True, type=Path, help="설치한 KiCad 실행 파일 경로")
    parser.add_argument("--manifest-sha256", help="선택한 게시 기록의 manifest SHA-256")
    parser.add_argument("--workspace", type=Path, help="게시 원본이 속한 작업 영역. ZIP은 이 영역 밖에 저장합니다.")
    parser.add_argument("--quiet", action="store_true", help="성공 시 콘솔 출력을 생략합니다.")
    parser.add_argument("--format", choices=FORMATS, action="append", help="선택 출력. 생략하면 두 형식 생성")
    args = parser.parse_args()
    try:
        result = export_package(args.input, args.output, args.kicad_cli, args.format or FORMATS,
                                manifest_sha256=args.manifest_sha256, workspace=args.workspace)
    except (OSError, ValueError, KeyError, AttributeError, BadZipFile, ProjectError, subprocess.TimeoutExpired) as error:
        message = str(error).encode("utf-8")[-1600:].decode("utf-8", errors="ignore")
        parser.exit(1, message + "\n")
    if args.quiet:
        return
    print(json.dumps({"output": str(args.output), "kicad_version": result["kicad_version"],
                      "files": list(result["outputs"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
