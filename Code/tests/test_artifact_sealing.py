"""! @brief 큰 native 산출물의 스트리밍 봉인과 journal 응답성을 확인한다."""

import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from rfad.domain.errors import ProjectError
from rfad.storage.journal import Journal


class ArtifactSealingTests(unittest.TestCase):
    """! @brief 별도 프로세스가 닫은 출력의 실제 파일 무결성 경계를 시험한다."""

    def setUp(self):
        """! @brief 시험 소유 임시 디렉터리와 파일 잠금을 준비한다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="rfad 봉인 ")
        self.root = Path(self.temporary.name)
        self.source = self.root / "worker 닫힌 출력.bin"
        self.payload = b"cad-data" * (1024 * 1024 + 1)
        self.source.write_bytes(self.payload)
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.journal = Journal(self.root / "workspace", {"value": 1})

    def tearDown(self):
        """! @brief 시험이 소유한 writer와 임시 파일을 정리한다."""
        self.journal.close()
        self.temporary.cleanup()

    def seal(self, **kwargs):
        """! @brief 기존 bytes 상한보다 큰 파일을 새 불변 경로로 옮긴다."""
        return self.journal.seal_file("projects/test/artifacts/model.brep", self.source,
            expected_sha256=kwargs.get("digest", self.digest), expected_bytes=kwargs.get("size", len(self.payload)),
            limit=kwargs.get("limit", 64 * 1024 * 1024))

    def test_large_file_seals_without_publishing_or_overwriting(self):
        """! @brief 8 MiB 초과 출력도 봉인하며 원본 상태와 기존 파일을 보존한다."""
        before = self.journal.read()
        reference = self.seal()
        self.assertGreater(reference["bytes"], 8 * 1024 * 1024)
        self.assertEqual((self.journal.root / reference["uri"]).read_bytes(), self.payload)
        self.assertEqual(self.journal.read(), before)
        self.assertEqual(reference["sha256"], self.digest)
        with self.assertRaises(ProjectError):
            self.seal()
        self.assertEqual((self.journal.root / reference["uri"]).read_bytes(), self.payload)

    def test_bad_hash_or_size_never_publishes_a_target(self):
        """! @brief 불일치 또는 상한 초과 출력은 최종 파일 참조를 만들지 않는다."""
        for values in ({"digest": "0" * 64}, {"size": len(self.payload) - 1}, {"size": len(self.payload) + 1}, {"limit": 1024}):
            with self.subTest(values=values):
                with self.assertRaises(ProjectError):
                    self.seal(**values)
                self.assertFalse((self.journal.root / "projects/test/artifacts/model.brep").exists())

    def test_streaming_copy_does_not_hold_the_journal_mutex(self):
        """! @brief 파일 읽기가 대기 중이어도 상태 조회와 편집 transaction이 진행된다."""
        entered, release = threading.Event(), threading.Event()
        original_open = Path.open
        source = self.source
        errors = []

        class SlowRead:
            """! @brief 첫 읽기만 기다리는 시험용 외부 IO 경계다."""

            def __init__(self, stream):
                """! @brief 실제 파일 stream을 감싼다."""
                self.stream = stream

            def __enter__(self):
                """! @brief 실제 stream의 수명을 시작한다."""
                return self

            def __exit__(self, *_):
                """! @brief 실제 파일을 닫는다."""
                self.stream.close()

            def read(self, count):
                """! @brief journal과 독립인 IO 대기를 만든다."""
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release stream")
                return self.stream.read(count)

        def open_file(path, *args, **kwargs):
            """! @brief 봉인 원본 파일만 지연시킨다."""
            stream = original_open(path, *args, **kwargs)
            return SlowRead(stream) if path == source and args == ("rb",) else stream

        def copy():
            """! @brief 다른 스레드에서 native 파일을 봉인한다."""
            try:
                self.seal()
            except Exception as error:
                errors.append(error)

        with patch.object(Path, "open", open_file):
            thread = threading.Thread(target=copy)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.journal.read()["value"], 1)
                self.journal.transaction(lambda state: state.update(value=2))
                self.assertEqual(self.journal.read()["value"], 2)
            finally:
                release.set()
                thread.join(timeout=6)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
