"""! @brief 8 MiB를 넘는 native 필드의 검증/재후처리 복제와 기존 메타데이터 한계를 검사한다."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from rfad.domain.errors import ProjectError
from rfad.storage.journal import Journal, MAX_ARTIFACT_BYTES
from rfad.storage.sealed_files import MAX_FILE_BYTES


class SealedFileStreamingTests(unittest.TestCase):
    """! @brief 큰 파일 지원을 무제한 메모리 읽기나 기존 산출물 덮어쓰기로 구현하지 않는다."""

    def setUp(self):
        """! @brief 실제 9 MiB 필드를 한 블록씩 만들고 기존 봉인 경로로 게시한다."""
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.journal = Journal(root / "workspace", {"test": True})
        source = root / "field.h5"
        digest = hashlib.sha256()
        with source.open("xb") as stream:
            for index in range(9):
                block = bytes([index]) * (1024 * 1024)
                stream.write(block)
                digest.update(block)
        self.reference = self.journal.seal_file("solver-artifacts/large-field.h5", source, expected_sha256=digest.hexdigest(), expected_bytes=source.stat().st_size)

    def tearDown(self):
        """! @brief 시험이 소유한 저장소 잠금과 임시 파일만 회수한다."""
        self.journal.close()
        self.temporary.cleanup()

    def test_large_native_field_verifies_and_copies_without_raising_metadata_limit(self):
        """! @brief 기존 8 MiB JSON 경로는 거절하고 9 MiB raw는 64 MiB 계약 안에서 처리한다."""
        self.assertEqual(MAX_ARTIFACT_BYTES, 8 * 1024 * 1024)
        with self.assertRaises(ProjectError):
            self.journal.read_artifact(self.reference)
        self.journal.verify_file(self.reference)
        self.journal.copy_artifact(self.reference, "solver-staging/new/input/field.h5")
        copied = self.journal.root / "solver-staging/new/input/field.h5"
        self.assertEqual(copied.stat().st_size, self.reference["bytes"])
        with copied.open("rb") as stream:
            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), self.reference["sha256"])

    def test_tampered_field_never_publishes_copy(self):
        """! @brief 봉인 hash가 다르면 부분 복사만 회수하고 원본/정상 대상으로 교체하지 않는다."""
        wrong = {**self.reference, "sha256": "0" * 64}
        with self.assertRaises(ProjectError):
            self.journal.verify_file(wrong)
        with self.assertRaises(ProjectError):
            self.journal.copy_artifact(wrong, "solver-staging/new/input/field.h5")
        folder = self.journal.root / "solver-staging/new/input"
        self.assertEqual(list(folder.iterdir()), [])
        self.journal.verify_file(self.reference)

    def test_file_cap_path_escape_and_existing_target_remain_blocked(self):
        """! @brief 64 MiB 초과/상위 경로 탈출/기존 파일 덮어쓰기를 허용하지 않는다."""
        with self.assertRaises(ProjectError):
            self.journal.verify_file({**self.reference, "bytes": MAX_FILE_BYTES + 1})
        with self.assertRaises(ProjectError):
            self.journal.copy_artifact(self.reference, "../escaped.h5")
        path = self.journal.root / "existing.bin"
        path.write_bytes(b"original")
        with self.assertRaises(ProjectError):
            self.journal.copy_artifact(self.reference, "existing.bin")
        self.assertEqual(path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
