"""! @brief 합성 저장 fixture로 후보 채택의 게시 경계와 출처 연결을 독립 검사한다. FDTD 시험이 아니다."""

from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import sweep_selection
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command
from rfad.domain.sweep_selection import COMMAND, KEY
from rfad.storage.journal import MAX_STATE_BYTES
import test_sweep_selection as fixtures


class SweepSelectionReviewTests(unittest.TestCase):
    """! @brief 실제 journal을 사용하되 합성 표본을 물리 계산 결과로 주장하지 않는다."""

    def setUp(self):
        """! @brief 각 시험에 독립적인 원본/연구/계산 재사용 기록을 만든다."""
        self.fixture = fixtures.SelectionFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.seal()

    def files(self):
        """! @brief 잠금 파일 외의 불변 저장 바이트를 전후 해시로 대조한다."""
        root = Path(self.fixture.workspace)
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*") if path.is_file() and path.name != ".writer.lock"}

    def reviewed_request(self, path=None):
        """! @brief 실제 검토 응답에서 접수할 요청을 준비한다."""
        data, preview = self.fixture.preview(path=path)
        self.assertTrue(preview["can_apply"], preview)
        return self.fixture.request({**data, "review_hash": preview["review_hash"], "command_id": str(uuid4())}, True)

    def test_near_full_journal_rejects_before_creating_copy_files(self):
        """! @brief journal 8 MiB 직전의 상태는 사본 파일을 쓰기 전에 명시 거절한다."""
        f = self.fixture
        request = self.reviewed_request()
        def fill(state):
            """! @brief 저장소 크기 경계만 검사하는 합성 여백이며 제품 기록으로 게시하지 않는다."""
            state["test_only_capacity_padding"] = ""
            remaining = MAX_STATE_BYTES - 2048 - len(canonical_bytes(state))
            self.assertGreater(remaining, 0)
            state["test_only_capacity_padding"] = "x" * remaining
        f.service.journal.transaction(fill)
        before, files = f.service.journal.read(), self.files()
        with self.assertRaises(ProjectError) as caught:
            f.service.mutate("sweep.selection.apply", request)
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(self.files(), files)
        self.assertFalse((f.workspace / request["input"]["path"]).exists())

    def test_total_space_rejection_does_not_publish_an_artifact(self):
        """! @brief 초기 총 디스크 예약 실패가 새 프로젝트 파일을 남기지 않는다."""
        f = self.fixture
        request = self.reviewed_request()
        before, files = f.service.journal.read(), self.files()
        with patch.object(f.service.journal, "_check_space", side_effect=ProjectError("E_RESOURCE", "합성 여유 공간 부족")):
            with self.assertRaises(ProjectError) as caught:
                f.service.mutate("sweep.selection.apply", request)
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(self.files(), files)

    def test_existing_unregistered_path_is_preserved(self):
        """! @brief journal에 없는 사용자 폴더도 사본 대상으로 덮어쓰지 않는다."""
        f = self.fixture
        request = self.reviewed_request(path="projects/사용자기존폴더")
        destination = f.workspace / request["input"]["path"]
        destination.mkdir()
        original = destination / "원문.txt"
        original.write_bytes("사용자 원문 보존".encode("utf-8"))
        before, files = f.service.journal.read(), self.files()
        with self.assertRaises(ProjectError) as caught:
            f.service.mutate("sweep.selection.apply", request)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(self.files(), files)

    def test_rehashed_origin_cannot_claim_different_parameter_change(self):
        """! @brief 해시가 유효해도 출처의 전후 값이 실제 명령과 다르면 거절한다."""
        f = self.fixture
        response, request = f.apply()
        state = f.service.journal.read()
        command = deepcopy(state["commands"][request["input"]["command_id"]])
        baseline = f.service.repository.read(command["previous_artifact"])[1]
        forged = deepcopy(command["command"])
        record = forged["payload"]["origin"]["records"][-1]
        record["values"][0]["after"]["source_refs"] = ["test:다른 출처를 거짓으로 연결"]
        record["record_hash"] = canonical_hash({key: value for key, value in record.items() if key != "record_hash"})
        before = canonical_bytes(baseline)
        with self.assertRaises(ProjectError) as caught:
            apply_command(baseline, forged, baseline["revision_id"])
        self.assertEqual(caught.exception.code, "E_HASH")
        self.assertEqual(canonical_bytes(baseline), before)
        self.assertEqual(f.service.journal.read(), state)
        self.assertNotEqual(response["new_project_id"], f.project)

    def test_rehashed_snapshot_cannot_change_origin_owner(self):
        """! @brief 출처 자체를 재해시해도 snapshot의 소유 프로젝트 불일치를 거절한다."""
        f = self.fixture
        _, request = f.apply()
        state = f.service.journal.read()
        command = deepcopy(state["commands"][request["input"]["command_id"]])
        baseline = f.service.repository.read(command["previous_artifact"])[1]
        forged = deepcopy(command["command"])
        record = forged["payload"]["origin"]["records"][-1]
        record["snapshot"]["project_id"] = str(uuid4())
        record["record_hash"] = canonical_hash({key: value for key, value in record.items() if key != "record_hash"})
        with self.assertRaises(ProjectError):
            apply_command(baseline, forged, baseline["revision_id"])
        self.assertEqual(f.service.journal.read(), state)

    def test_internal_command_cannot_bypass_public_review(self):
        """! @brief 정상 내부 명령조차 일반 프로젝트 명령으로 재접수할 수 없다."""
        f = self.fixture
        _, request = f.apply()
        before, files = f.service.journal.read(), self.files()
        original_command = before["commands"][request["input"]["command_id"]]["command"]
        bypass = f.request({"expected_revision": f.document["revision_id"], "command_id": str(uuid4()),
                            "type": COMMAND, "payload": deepcopy(original_command["payload"])}, True)
        with self.assertRaises(ProjectError) as caught:
            f.service.mutate("project.apply_command", bypass)
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(self.files(), files)

    def test_prior_origin_cannot_be_rewritten_when_appending_new_record(self):
        """! @brief 재채택 출처를 추가하면서 과거 기록을 재해시해 바꿀 수 없다."""
        f = self.fixture
        response, _ = f.apply()
        state = f.service.journal.read()
        document = f.service._load(state["projects"][response["new_project_id"]])
        origin = deepcopy(document["extensions"][KEY])
        previous = deepcopy(origin)
        origin["records"][0]["reason"] = "과거에 남기지 않았던 사유로 변경"
        origin["records"][0]["record_hash"] = canonical_hash(
            {key: value for key, value in origin["records"][0].items() if key != "record_hash"})
        added = deepcopy(previous["records"][0])
        added["id"] = str(uuid4())
        before = deepcopy(document["parameters"][f.axis_id]["quantity"])
        after = {**before, "value_si": before["value_si"] * 2}
        added["values"] = [{"id": f.axis_id, "before": before, "after": after}]
        added["record_hash"] = canonical_hash({key: value for key, value in added.items() if key != "record_hash"})
        origin["records"].append(added)
        command = {"command_id": added["id"], "type": COMMAND, "payload": {
            "parameters": [{"id": f.axis_id, "expected": before, "replacement": after}],
            "expected_origin_hash": canonical_hash(previous), "origin": origin}}
        raw = canonical_bytes(document)
        with self.assertRaises(ProjectError) as caught:
            apply_command(document, command, document["revision_id"])
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(canonical_bytes(document), raw)

    def test_reopened_copy_undo_redo_needs_neither_solver_nor_candidate_engine(self):
        """! @brief runtime 없는 재열기의 undo/redo가 과거 후보/결과를 다시 계산하지 않는다."""
        f = self.fixture
        response, _ = f.apply()
        identity = response["new_project_id"]
        before = f.service.journal.read()
        adopted = f.service._load(before["projects"][identity])
        f.service.close()
        f.service = ProjectService(f.workspace, auto_run=False, clock=lambda: 2000000000.0)
        self.assertIsNone(f.service.solver.runtime)
        with patch("rfad.domain.design_sweep.candidate_at", side_effect=AssertionError("과거 생성기 실행 금지")), \
                patch("rfad.application.sweep_selection.resolve", side_effect=AssertionError("과거 결과 재조회 금지")):
            for operation in ("undo", "redo"):
                document = f.service._load(f.service.journal.read()["projects"][identity])
                f.service.mutate("project." + operation, f.request(
                    {"expected_revision": document["revision_id"], "command_id": str(uuid4())}, True, identity))
                actual = f.service._load(f.service.journal.read()["projects"][identity])
                expected = f.document if operation == "undo" else adopted
                self.assertEqual(actual["parameters"], expected["parameters"])
                self.assertEqual(actual["extensions"], expected["extensions"])
        final = f.service.journal.read()
        self.assertEqual(final["projects"][f.project], before["projects"][f.project])
        self.assertEqual(final["solver_results"], before["solver_results"])
        self.assertEqual(final["sweeps"], before["sweeps"])

    def test_failure_before_publish_keeps_original_authority(self):
        """! @brief 파일 게시 중 장애는 orphan과 권위 상태를 구분하고 원본을 그대로 둔다."""
        f = self.fixture
        request = self.reviewed_request()
        before = f.service.journal.read()
        def fail(stage):
            """! @brief current pointer 게시 직전의 실제 journal 경계를 중단한다."""
            if stage == "before_publish":
                raise OSError("합성 게시 직전 장애")
        with patch.object(f.service.journal, "fault_hook", fail):
            with self.assertRaises(ProjectError) as caught:
                f.service.mutate("sweep.selection.apply", request)
        self.assertEqual(caught.exception.code, "E_DISK")
        self.assertFalse(caught.exception.details["committed"])
        self.assertEqual(f.service.journal.read(), before)
        receipt = sweep_selection.read(f.service, "sweep.selection.receipt", f.request(
            {key: request[key] for key in ("request_key", "request_key_epoch")}))
        self.assertEqual(receipt["status"], "unresolved")
        self.assertTrue((f.workspace / request["input"]["path"]).exists())

    def test_failure_after_publish_recovers_exact_receipt_without_duplicate(self):
        """! @brief ACK 전 장애 후 원래 영수증과 재전송은 이미 생성된 사본 한 개만 반환한다."""
        f = self.fixture
        request = self.reviewed_request()
        initial = f.service.journal.read()
        original = deepcopy(initial["projects"][f.project])
        def fail(stage):
            """! @brief current pointer 게시 직후 사용자 응답 전에 장애를 주입한다."""
            if stage == "after_publish":
                raise OSError("합성 응답 전 장애")
        with patch.object(f.service.journal, "fault_hook", fail):
            with self.assertRaises(ProjectError) as caught:
                f.service.mutate("sweep.selection.apply", request)
        self.assertTrue(caught.exception.details["committed"])
        receipt = sweep_selection.read(f.service, "sweep.selection.receipt", f.request(
            {key: request[key] for key in ("request_key", "request_key_epoch")}))
        self.assertEqual(receipt["status"], "found")
        before, files = f.service.journal.read(), self.files()
        replay = f.service.mutate("sweep.selection.apply", request)
        self.assertEqual(replay, receipt["response"])
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(self.files(), files)
        self.assertEqual(before["projects"][f.project], original)
        self.assertEqual(len(before["projects"]), len(initial["projects"]) + 1)


if __name__ == "__main__":
    unittest.main()
