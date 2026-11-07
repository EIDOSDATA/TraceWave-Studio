"""! @brief 실제 파일과 프로세스로 journal 게시, 손상, 잠금 및 복구 경계를 확인한다."""

from collections import namedtuple
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rfad.domain.errors import ProjectError
from rfad.storage.journal import Journal, MAX_STATE_BYTES


class JournalTests(unittest.TestCase):
    """! @brief 포인터 게시 전후의 실제 저장 상태를 대조한다."""

    def setUp(self):
        """! @brief 한글과 공백을 포함한 격리된 workspace를 준비한다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "작업 영역"

    def new_journal(self):
        """! @brief 초기 상태를 생성하고 시험 종료 시 잠금을 해제한다."""
        journal = Journal(self.root, {"revision": 0, "receipts": {}})
        self.addCleanup(journal.close)
        return journal

    def child(self, source, *args):
        """! @brief 같은 제품 코드를 사용하는 별도 Python 프로세스를 실행한다."""
        code_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(code_root / "src"))
        return subprocess.run([sys.executable, "-X", "utf8", "-c", source, str(self.root), *args], capture_output=True, env=env, cwd=code_root, timeout=15)

    def test_commit_returns_copies_and_reopen_preserves_state(self):
        """! @brief 상태와 결과의 외부 수정이 저장 원본을 바꾸지 않는다."""
        journal = self.new_journal()

        def mutate(state):
            """! @brief revision과 receipt를 같은 commit에서 변경한다."""
            state["revision"] = 1
            state["receipts"]["request-1"] = {"revision": 1}
            return state["receipts"]["request-1"]

        result = journal.transaction(mutate)
        result["revision"] = 99
        state = journal.read()
        state["revision"] = 77
        self.assertEqual(journal.read()["revision"], 1)
        journal.close()
        with Journal(self.root, {"different": "ignored"}) as reopened:
            self.assertEqual(reopened.read(), {"revision": 1, "receipts": {"request-1": {"revision": 1}}})

    def test_invalid_mutator_rolls_back_state_and_receipt(self):
        """! @brief 도메인 검증 실패 시 마지막 포인터와 상태를 보존한다."""
        journal = self.new_journal()
        before = (self.root / "current.json").read_bytes()

        def invalid(state):
            """! @brief 상태를 수정한 뒤 실패를 유도한다."""
            state["revision"] = 2
            raise ProjectError("E_SCHEMA", "검증 실패")

        with self.assertRaises(ProjectError):
            journal.transaction(invalid)
        self.assertEqual((self.root / "current.json").read_bytes(), before)
        self.assertEqual(journal.read()["revision"], 0)

    def test_payload_write_failure_preserves_last_good_pointer(self):
        """! @brief payload 기록 실패를 성공이나 새 revision으로 게시하지 않는다."""
        journal = self.new_journal()
        pointer = (self.root / "current.json").read_bytes()
        with patch.object(journal, "_write_new", side_effect=OSError("disk full")):
            with self.assertRaises(ProjectError) as raised:
                journal.transaction(lambda state: state.update(revision=1))
        self.assertEqual(raised.exception.code, "E_DISK")
        self.assertEqual((self.root / "current.json").read_bytes(), pointer)
        self.assertEqual(journal.read()["revision"], 0)

    def test_fsync_failure_preserves_last_good_pointer(self):
        """! @brief 파일 기록 후 fsync 실패도 게시 전에 중단한다."""
        journal = self.new_journal()
        pointer = (self.root / "current.json").read_bytes()
        with patch("rfad.storage.journal.os.fsync", side_effect=OSError("flush failed")):
            with self.assertRaises(ProjectError) as raised:
                journal.transaction(lambda state: state.update(revision=1))
        self.assertEqual(raised.exception.code, "E_DISK")
        self.assertEqual((self.root / "current.json").read_bytes(), pointer)
        self.assertEqual(journal.read()["revision"], 0)

    def test_noop_replay_does_not_write_a_new_commit(self):
        """! @brief 상태가 같은 조회와 재전송은 새 디스크 generation을 만들지 않는다."""
        journal = self.new_journal()
        pointer = (self.root / "current.json").read_bytes()
        with patch.object(journal, "_write_new", side_effect=AssertionError("unexpected write")):
            result = journal.transaction(lambda state: {"revision": state["revision"]})
        self.assertEqual(result, {"revision": 0})
        self.assertEqual((self.root / "current.json").read_bytes(), pointer)
        self.assertEqual(len(list((self.root / "commits").iterdir())), 1)

    def test_pointer_replace_failure_preserves_last_good_state(self):
        """! @brief 최종 replace가 실패하면 준비된 새 payload가 authority가 되지 않는다."""
        journal = self.new_journal()
        pointer = (self.root / "current.json").read_bytes()
        with patch("rfad.storage.journal.os.replace", side_effect=PermissionError("replace denied")):
            with self.assertRaises(ProjectError) as raised:
                journal.transaction(lambda state: state.update(revision=1))
        self.assertEqual(raised.exception.code, "E_DISK")
        self.assertFalse(raised.exception.details["committed"])
        self.assertEqual((self.root / "current.json").read_bytes(), pointer)
        self.assertEqual(journal.read()["revision"], 0)
        self.assertGreater(len(list((self.root / "commits").iterdir())), 1)

    def test_after_publish_error_reports_committed_state(self):
        """! @brief 게시 뒤 오류는 rollback으로 거짓 보고하지 않는다."""
        journal = self.new_journal()

        def fault(stage):
            """! @brief 새 포인터 게시 이후 오류를 유도한다."""
            if stage == "after_publish":
                raise RuntimeError("lost acknowledgement")

        journal.fault_hook = fault
        with self.assertRaises(ProjectError) as raised:
            journal.transaction(lambda state: state.update(revision=1))
        self.assertTrue(raised.exception.details["committed"])
        self.assertEqual(journal.read()["revision"], 1)
        self.assertEqual(raised.exception.details["commit_id"], json.loads((self.root / "current.json").read_bytes())["commit_id"])

    def test_read_checks_payload_and_manifest_hash_every_time(self):
        """! @brief 메모리 사본을 신뢰하지 않고 실제 파일 손상을 검출한다."""
        journal = self.new_journal()
        pointer = json.loads((self.root / "current.json").read_bytes())
        folder = self.root / "commits" / pointer["commit_id"]
        payload_path = folder / "state.json"
        payload = payload_path.read_bytes()
        payload_path.write_bytes(b'{"receipts":{},"revision":9}')
        with self.assertRaises(ProjectError) as raised:
            journal.read()
        self.assertEqual(raised.exception.code, "E_HASH")
        payload_path.write_bytes(payload)
        self.assertEqual(journal.read()["revision"], 0)
        (folder / "manifest.json").write_bytes(b"{}")
        with self.assertRaises(ProjectError) as raised:
            journal.read()
        self.assertEqual(raised.exception.code, "E_HASH")

    def test_corrupt_or_missing_pointer_is_not_silently_reinitialized(self):
        """! @brief 유효 commit이 있는 저장소의 포인터 분실을 초기 상태로 덮지 않는다."""
        journal = self.new_journal()
        journal.close()
        current = self.root / "current.json"
        current.write_bytes(b"broken")
        with self.assertRaises(ProjectError) as raised:
            Journal(self.root, {"replacement": True})
        self.assertEqual(raised.exception.code, "E_HASH")
        self.assertEqual(current.read_bytes(), b"broken")
        current.unlink()
        with self.assertRaises(ProjectError) as raised:
            Journal(self.root, {"replacement": True})
        self.assertEqual(raised.exception.code, "E_HASH")
        self.assertFalse(current.exists())

    def test_same_process_and_other_process_writer_are_rejected(self):
        """! @brief 동시에 두 writer가 상태를 갱신하지 못한다."""
        journal = self.new_journal()
        with self.assertRaises(ProjectError) as raised:
            Journal(self.root, {})
        self.assertEqual(raised.exception.code, "E_CONFLICT")
        source = "from pathlib import Path\nimport sys\nfrom rfad.storage.journal import Journal\nfrom rfad.domain.errors import ProjectError\ntry:\n    Journal(Path(sys.argv[1]), {})\nexcept ProjectError as error:\n    print(error.code)\n    sys.exit(9)\n"
        result = self.child(source)
        self.assertEqual(result.returncode, 9, result.stderr.decode())
        self.assertEqual(result.stdout.decode().strip(), "E_CONFLICT")
        self.assertEqual(journal.read()["revision"], 0)

    def test_actual_process_crash_before_and_after_publish(self):
        """! @brief 실제 강제 종료 뒤 old/new pointer와 OS 잠금 자동 해제를 확인한다."""
        journal = self.new_journal()
        journal.close()
        source = "from pathlib import Path\nimport os,sys\nfrom rfad.storage.journal import Journal\njournal=Journal(Path(sys.argv[1]), {})\ndef fault(stage):\n    if stage==sys.argv[2]:\n        os._exit(73)\njournal.fault_hook=fault\ndef mutate(state):\n    state['revision']=state['revision']+1\n    state['receipts']['crash']={'revision':state['revision']}\njournal.transaction(mutate)\n"
        for stage, expected_revision in (("after_payload", 0), ("before_publish", 0), ("after_publish", 1)):
            with self.subTest(stage=stage):
                result = self.child(source, stage)
                self.assertEqual(result.returncode, 73, result.stderr.decode())
                with Journal(self.root, {}) as reopened:
                    state = reopened.read()
                    self.assertEqual(state["revision"], expected_revision)
                    if expected_revision == 0:
                        self.assertEqual(state["receipts"], {})
                    else:
                        self.assertEqual(state["receipts"], {"crash": {"revision": 1}})

    def test_disk_reserve_and_state_size_are_enforced(self):
        """! @brief 부족한 공간과 상태 상한을 접수 전에 거부한다."""
        journal = self.new_journal()
        usage = namedtuple("usage", "total used free")(100, 99, 1)
        with patch("rfad.storage.journal.shutil.disk_usage", return_value=usage):
            with self.assertRaises(ProjectError) as raised:
                journal.transaction(lambda state: state.update(revision=1))
        self.assertEqual(raised.exception.code, "E_RESOURCE")
        with self.assertRaises(ProjectError) as raised:
            journal.transaction(lambda state: state.update(large="x" * MAX_STATE_BYTES))
        self.assertEqual(raised.exception.code, "E_RESOURCE")
        self.assertEqual(journal.read()["revision"], 0)

    def test_immutable_artifact_hash_and_write_once_semantics(self):
        """! @brief 불변 파일의 중복 생성은 동일 바이트만 허용하고 손상을 검출한다."""
        journal = self.new_journal()
        uri = "projects/한글 프로젝트/revisions/revision-1/project.json"
        payload = b'{"value":0.0}'
        reference = journal.put_immutable(uri, payload)
        self.assertEqual(reference, {"uri": uri, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        self.assertEqual(journal.put_immutable(uri, payload), reference)
        self.assertEqual(journal.read_artifact(reference), payload)
        with self.assertRaises(ProjectError) as raised:
            journal.put_immutable(uri, b"different")
        self.assertEqual(raised.exception.code, "E_HASH")
        (self.root / uri).write_bytes(b"corrupt")
        with self.assertRaises(ProjectError) as raised:
            journal.read_artifact(reference)
        self.assertEqual(raised.exception.code, "E_HASH")

    def test_artifact_created_in_failed_transaction_stays_unpublished(self):
        """! @brief 미게시 파일이 남아도 journal에서 완료 산출물로 노출하지 않는다."""
        journal = self.new_journal()

        def mutate(state):
            """! @brief 파일 기록 후 도메인 실패를 유도한다."""
            state["artifact"] = journal.put_immutable("projects/a/orphan.json", b"{}")
            raise ProjectError("E_SCHEMA", "rollback")

        with self.assertRaises(ProjectError):
            journal.transaction(mutate)
        self.assertNotIn("artifact", journal.read())
        self.assertTrue((self.root / "projects/a/orphan.json").is_file())

    def test_unsafe_uris_and_internal_paths_are_rejected(self):
        """! @brief 상대 URI의 탈출과 Windows 별칭 경로를 거부한다."""
        journal = self.new_journal()
        for uri in ("", ".", "..", "../escape", "/absolute", "C:/absolute", "a\\b", "a/../b", "a//b", "a/", "current.json", "commits/a", ".writer.lock", "a/name.", "a/name ", "a/NUL", "a/file:stream"):
            with self.subTest(uri=uri), self.assertRaises(ProjectError):
                journal.put_immutable(uri, b"{}")

    def test_symlink_or_junction_traversal_is_rejected(self):
        """! @brief 실제 symlink 또는 Windows junction의 경로 탈출을 차단한다."""
        journal = self.new_journal()
        target = Path(self.temporary.name) / "outside"
        target.mkdir()
        link = self.root / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"현재 계정의 symlink 생성 미지원: {error}")
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        with self.assertRaises(ProjectError) as raised:
            journal.put_immutable("linked/file.json", b"{}")
        self.assertEqual(raised.exception.code, "E_SCHEMA")
        self.assertFalse((target / "file.json").exists())

    def test_nested_transaction_and_closed_writer_are_rejected(self):
        """! @brief 재진입과 닫힌 writer의 사용을 상태 충돌로 처리한다."""
        journal = self.new_journal()
        with self.assertRaises(ProjectError) as raised:
            journal.transaction(lambda state: journal.transaction(lambda nested: None))
        self.assertEqual(raised.exception.code, "E_CONFLICT")
        journal.close()
        with self.assertRaises(ProjectError):
            journal.read()


if __name__ == "__main__":
    unittest.main()
