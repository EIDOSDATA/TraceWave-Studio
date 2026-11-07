"""! @file
@brief 격리 CAD 개발 환경의 의존성과 실제 STEP 왕복을 검사한다.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import platform
from pathlib import Path
import re
import struct
import sys
import tempfile
import time
from urllib.parse import unquote, urlparse


CODE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = CODE_ROOT / "runtime_profiles/python-cad-windows-x64.json"
QT_PACKAGES = re.compile(r"^(?:pyqt|pyside|shiboken|qt|cq-editor)")


def _normalize(name: str) -> str:
    """! @brief 배포 이름을 pip 규칙에 맞춰 정규화한다."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _require(condition: bool, message: str) -> None:
    """! @brief 검사 실패를 명시적인 환경 오류로 바꾼다."""
    if not condition:
        raise RuntimeError(message)


def _read_manifest(path: Path) -> dict:
    """! @brief 개발 환경 manifest를 읽고 검사 범위를 확인한다."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _require(manifest["schema"] == "rfad.runtime.python/0.1", "Unsupported manifest schema.")
    _require(manifest["qt_allowed"] is False, "Qt must remain disabled.")
    return manifest


def check_plan(path: Path, manifest: dict) -> dict:
    """! @brief 설치 전에 wheel 목록과 해시를 manifest에 대조한다."""
    plan = json.loads(path.read_text(encoding="utf-8"))
    expected = {item["name"]: item for item in manifest["packages"]}
    actual = {}
    for item in plan["install"]:
        name = _normalize(item["metadata"]["name"])
        _require(not QT_PACKAGES.match(name), f"Qt package is forbidden: {name}")
        _require(name not in actual, f"Duplicate package: {name}")
        _require(name in expected, f"Unpinned package: {name}")
        download = item["download_info"]
        wheel = unquote(urlparse(download["url"]).path.rsplit("/", 1)[-1])
        locked = expected[name]
        _require(wheel.endswith(".whl"), f"Source installation is forbidden: {name}")
        _require(item["metadata"]["version"] == locked["version"], f"Version drift: {name}")
        _require(wheel == locked["wheel"], f"Wheel drift: {name}")
        _require(download["archive_info"]["hashes"]["sha256"] == locked["sha256"], f"Hash drift: {name}")
        actual[name] = item["metadata"]["version"]
    _require(set(actual) == set(expected), "Installation plan does not cover the complete lock.")
    return {"status": "passed", "mode": "dependency_plan", "package_count": len(actual), "qt_packages": []}


def check_environment(manifest: dict) -> dict:
    """! @brief 설치 격리, 고정 버전, Qt 부재와 B-rep 왕복을 실제 검사한다."""
    _require(sys.prefix != sys.base_prefix, "Run this check in the CAD virtual environment.")
    _require(sys.platform == "win32" and struct.calcsize("P") == 8, "This profile requires Windows x64.")
    _require(platform.machine().upper() == "AMD64", "This profile requires AMD64.")
    _require(sys.version_info[:2] == (3, 12), "This profile requires CPython 3.12.")
    _require(platform.python_implementation() == "CPython", "This profile requires CPython.")
    installed = {
        _normalize(item.metadata["Name"]): item.version
        for item in importlib.metadata.distributions()
    }
    qt_packages = sorted(name for name in installed if QT_PACKAGES.match(name))
    _require(not qt_packages, f"Qt packages are forbidden: {qt_packages}")
    expected = {item["name"]: item["version"] for item in manifest["packages"]}
    for name, version in expected.items():
        _require(installed.get(name) == version, f"Missing or mismatched package: {name}=={version}")
    extra = set(installed) - set(expected) - {"pip", "setuptools", "wheel"}
    _require(not extra, f"Unpinned CAD environment packages: {sorted(extra)}")
    qt_dlls = sorted(
        str(path.relative_to(sys.prefix))
        for path in Path(sys.prefix).rglob("*.dll")
        if re.match(r"qt[456].*\.dll$", path.name, re.IGNORECASE)
    )
    _require(not qt_dlls, f"Qt runtime DLLs are forbidden: {qt_dlls}")

    start = time.perf_counter()
    import cadquery as cq

    import_elapsed = time.perf_counter() - start
    dimensions = [10.0, 20.0, 1.6]
    shape = cq.Workplane("XY").box(*dimensions)
    _require(shape.val().isValid(), "The original box is not a valid B-rep.")
    with tempfile.TemporaryDirectory(prefix="tracewave-cad-smoke-") as directory:
        step_path = Path(directory) / "box.step"
        cq.exporters.export(shape, str(step_path), exportType="STEP")
        step_bytes = step_path.read_bytes()
        step_text = step_bytes.decode("ascii")
        schema_match = re.search(r"FILE_SCHEMA\s*\(\s*\((.*?)\)\s*\)", step_text, re.DOTALL)
        _require(schema_match is not None, "The STEP file has no FILE_SCHEMA header.")
        restored = cq.importers.importStep(str(step_path))
        solids = restored.solids().vals()
        _require(len(solids) == 1, "The STEP round trip must preserve one solid.")
        solid = solids[0]
        _require(solid.isValid(), "The imported STEP is not a valid B-rep.")
        bounds = solid.BoundingBox()
        restored_dimensions = [bounds.xlen, bounds.ylen, bounds.zlen]
        for expected_length, actual_length in zip(dimensions, restored_dimensions):
            _require(math.isclose(expected_length, actual_length, rel_tol=1e-9, abs_tol=1e-6), "STEP size changed.")
        expected_volume = math.prod(dimensions)
        volume = solid.Volume()
        _require(math.isclose(volume, expected_volume, rel_tol=1e-9, abs_tol=1e-6), "STEP volume changed.")
        result = {
            "schema": "rfad.runtime.cad-smoke/0.1",
            "status": "passed",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "profile_id": manifest["profile_id"],
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "architecture": platform.machine(),
            "package_count": len(expected),
            "packages": expected,
            "qt_packages": qt_packages,
            "qt_runtime_dlls": qt_dlls,
            "cad_import_seconds": round(import_elapsed, 6),
            "step": {
                "writer": "CadQuery/OCCT",
                "reader": "CadQuery/OCCT",
                "kernel_independent": False,
                "file_schema": schema_match.group(1).strip().strip("'"),
                "sha256": hashlib.sha256(step_bytes).hexdigest(),
                "bytes": len(step_bytes),
                "unit": "mm",
                "dimensions_mm": restored_dimensions,
                "volume_mm3": volume,
                "solid_count": len(solids),
                "valid_brep": True,
            },
            "product_cad_adapter_verified": False,
            "ap242_verified": False,
        }
    qt_modules = sorted(name for name in sys.modules if name.startswith(("PyQt", "PySide", "qtpy")))
    _require(not qt_modules, f"Qt modules were loaded: {qt_modules}")
    result["qt_modules_loaded"] = qt_modules
    return result


def main() -> int:
    """! @brief 의존성 계획 또는 실제 CAD 환경 검사 결과를 JSON으로 남긴다."""
    parser = argparse.ArgumentParser(description="Check the isolated CadQuery development environment.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--check-plan", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        manifest = _read_manifest(arguments.manifest)
        if arguments.check_plan is not None:
            result = check_plan(arguments.check_plan, manifest)
        else:
            result = check_environment(manifest)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as error:
        result = {"status": "failed", "error": str(error)}
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
