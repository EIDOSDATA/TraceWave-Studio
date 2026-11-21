"""! @brief Altium 검토용 새 NC 파일의 정확도와 원문 보존을 검사한다."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rfad.cli.altium_drill_copy import make_copy
from rfad.domain.errors import ProjectError


SOURCE = (b"M48\n; #@! TF.FileFunction,NonPlated,1,2,NPTH\nMETRIC\n"
          b"T01C1.000000\n%\nT01\nG05\nX5.000000Y5.000000\nM30\n")
COPY = b"M48\nMETRIC\nFMAT,2\nT01C1.0000\n%\nG90\nT01\nX05000Y05000\nM30\n"


class AltiumDrillCopyTests(unittest.TestCase):
    """! @brief 이미 검증한 비도금 원형 홀 범위만 내보낸다."""

    def test_precise_fixed_coordinates_and_finished_diameter(self):
        """! @brief 좌표를 이동하지 않고 형식을 명시한 동일한 수치의 사본을 만든다."""
        self.assertEqual(make_copy(SOURCE), (COPY, 1))
        multiple = SOURCE.replace(b"T01C1.000000", b"T01C1.000000\nT02C2.130500")
        multiple = multiple.replace(b"M30", b"T02\nX0.001000Y99.999000\nT01\nX0.000000Y0.000000\nM30")
        converted, count = make_copy(multiple)
        self.assertEqual(count, 3)
        self.assertIn(b"T02C2.1305\n", converted)
        self.assertIn(b"T02\nX00001Y99999\nT01\nX00000Y00000\n", converted)

    def test_rejects_unverified_geometry_and_loss_of_precision(self):
        """! @brief 완성 좌표나 지름의 반올림과 지원 범위 밖의 홀을 거절한다."""
        variants = [
            SOURCE.replace(b"X5.000000", b"X5.000001"),
            SOURCE.replace(b"X5.000000", b"X5.000000000000000001"),
            SOURCE.replace(b"Y5.000000", b"Y100.000000"),
            SOURCE.replace(b"Y5.000000", b"Y-0.001000"),
            SOURCE.replace(b"C1.000000", b"C1.000001"),
            SOURCE.replace(b"NonPlated,1,2,NPTH", b"Plated,1,2,PTH"),
            SOURCE.replace(b"NonPlated,1,2,NPTH", b"Drill,1,2,Unknown"),
            SOURCE.replace(b"METRIC", b"INCH"),
            SOURCE.replace(b"G05\nX5.000000Y5.000000",
                           b"G00X5.000000Y5.000000\nM15\nG01X6.000000Y6.000000\nM16"),
        ]
        for invalid in variants:
            with self.subTest(raw=invalid), self.assertRaises(ProjectError):
                make_copy(invalid)

    def test_cli_keeps_source_and_never_replaces_existing_copy(self):
        """! @brief 실제 CLI에서 원본과 기존 사본의 덮어쓰기를 막고 해시를 제공한다."""
        with TemporaryDirectory(prefix="Altium 검토 ") as folder:
            source = Path(folder) / "원문.xnc"
            destination = Path(folder) / "검토.drl"
            source.write_bytes(SOURCE)
            command = [sys.executable, "-m", "rfad", "altium-drill-copy", str(source), str(destination)]
            result = subprocess.run(command, capture_output=True, check=True, timeout=30)
            self.assertEqual(source.read_bytes(), SOURCE)
            self.assertEqual(destination.read_bytes(), COPY)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["source_sha256"], hashlib.sha256(SOURCE).hexdigest())
            self.assertEqual(receipt["copy_sha256"], hashlib.sha256(COPY).hexdigest())
            self.assertIsNone(receipt["actual_tool_diameter"])
            self.assertFalse(receipt["manufacturing_verified"])
            destination.write_bytes(b"previous copy")
            rejected = subprocess.run(command, capture_output=True, check=False, timeout=30)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(source.read_bytes(), SOURCE)
            self.assertEqual(destination.read_bytes(), b"previous copy")
            self.assertEqual(set(Path(folder).iterdir()), {source, destination})
