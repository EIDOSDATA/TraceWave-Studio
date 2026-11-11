"""! @brief 원자적 제어 파일 교체 중 unlink된 열린 inode의 정상 읽기와 경계를 검사한다."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("rfad_control_read_test", Path(__file__).resolve().parents[1] / "tools/wsl_supervisor.py")
SUPERVISOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPERVISOR)


@unittest.skipUnless(sys.platform.startswith("linux"), "실제 ext4 inode/link와 O_NOFOLLOW가 필요합니다.")
class ControlReadRaceTests(unittest.TestCase):
    """! @brief 보안 경계는 유지하며 정당한 atomic rename을 실패로 처리하지 않는다."""

    def test_replace_after_open_reads_original_unlinked_inode(self):
        """! @brief fd를 연 직후 교체해 nlink=0을 결정적으로 만들고 원래 완전한 JSON을 읽는다."""
        with tempfile.TemporaryDirectory() as directory:
            path, replacement = Path(directory) / "control.json", Path(directory) / "replacement.json"
            path.write_text(json.dumps({"heartbeat": 1}))
            replacement.write_text(json.dumps({"heartbeat": 2}))
            real_open = os.open

            def raced_open(target, flags):
                """! @brief 정상 파일 교체는 이미 연 fd의 바이트나 유형을 바꾸지 않는다."""
                descriptor = real_open(target, flags)
                os.replace(replacement, path)
                self.assertEqual(os.fstat(descriptor).st_nlink, 0)
                return descriptor

            with patch.object(SUPERVISOR.os, "open", side_effect=raced_open):
                self.assertEqual(SUPERVISOR.read_json(path), {"heartbeat": 1})
            self.assertEqual(SUPERVISOR.read_json(path), {"heartbeat": 2})

    def test_symlink_multiple_links_fifo_and_oversize_are_rejected(self):
        """! @brief fd 기반 읽기도 링크/특수 파일/바이트 상한을 통과시키지 않는다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.json"
            original.write_text('{"value":1}')
            link = root / "symlink"
            link.symlink_to(original)
            with self.assertRaises(OSError):
                SUPERVISOR.read_json(link)
            hardlink = root / "hardlink"
            os.link(original, hardlink)
            with self.assertRaises(ValueError):
                SUPERVISOR.read_json(original)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(ValueError):
                SUPERVISOR.read_json(fifo)
            single = root / "single.json"
            single.write_text('{"value":1}')
            with self.assertRaises(ValueError):
                SUPERVISOR.read_json(single, 1)


if __name__ == "__main__":
    unittest.main()
