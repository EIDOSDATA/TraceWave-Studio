"""! @brief 실제 stdio 편집 API의 재시작, 이력과 스냅샷 보존을 검증한다."""

from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import test_project_process


class EditorProcessTests(unittest.TestCase):
    """! @brief GUI와 같은 DTO/변경 요청을 독립 서비스 프로세스에서 실행한다."""

    def setUp(self):
        """! @brief 한글 작업 영역과 프로젝트를 만들고 서비스 epoch를 받는다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="rfad 편집 프로세스 ")
        self.workspace = Path(self.temporary.name) / "한글 작업 영역"
        self.client = test_project_process.ProjectProcessTests()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.client.stop)
        self.client.start(self.workspace)
        capability = self.client.rpc("capabilities.get", self.client.params({}, mutation=False))
        self.client.epoch = capability["idempotency_policy"]["request_key_epoch"]
        created = self.client.finish(self.client.rpc("project.open", self.client.params({
            "open_mode": "create", "path": "projects/편집 검증", "name": "편집 검증",
        })))
        self.project_id = created["project_id"]
        self.revision = created["revision_id"]

    def edit(self, kind, identifier, values):
        """! @brief 표시 단위의 입력을 보내고 서버가 확정한 revision만 사용한다."""
        response = self.client.rpc("editor.apply", self.client.params({
            "expected_revision": self.revision, "command_id": str(uuid4()),
            "selection": {"kind": kind, "id": identifier}, "values": values,
        }, project=self.project_id))
        self.revision = response["new_revision"]
        return response

    def view(self, kind, identifier):
        """! @brief 선택한 객체의 표시 DTO만 요청한다."""
        return self.client.rpc("editor.get", self.client.params({
            "expected_revision": self.revision,
            "selection": {"kind": kind, "id": identifier},
        }, project=self.project_id, mutation=False))

    def history(self, method):
        """! @brief 실행 취소와 다시 실행도 새 command/revision 요청으로 처리한다."""
        response = self.client.rpc(method, self.client.params({
            "expected_revision": self.revision, "command_id": str(uuid4()),
        }, project=self.project_id))
        old_revision = self.revision
        self.revision = response["new_revision"]
        self.assertNotEqual(self.revision, old_revision)
        return response

    def fields(self, identifier):
        """! @brief UI 폼의 key와 값만 편의상 추출한다."""
        return {field["key"]: field["value"] for field in self.view("parameter", identifier)["selection"]["fields"]}

    def test_expression_history_replay_after_process_kill_preserves_snapshot(self):
        """! @brief 의존식 재계산/취소/재실행과 불변 스냅샷을 프로세스 경계에서 확인한다."""
        width, half = str(uuid4()), str(uuid4())
        self.edit("new_parameter", width, {"name": "기판 폭", "mode": "value", "value": "40", "unit": "mm", "dimension": "length"})
        self.edit("new_parameter", half, {"name": "절반 폭", "mode": "expression", "expression": "w / 2", "bindings": {"w": width}, "dimension": "length", "unit": "mm"})
        self.assertAlmostEqual(float(self.fields(half)["value"]), 20)
        snapshot = self.client.finish(self.client.rpc("snapshot.create", self.client.params({"expected_revision": self.revision}, project=self.project_id)))
        frozen_path = self.workspace / snapshot["artifact"]["uri"]
        frozen = frozen_path.read_bytes()
        self.edit("parameter", width, {"value": "60"})
        self.assertAlmostEqual(float(self.fields(half)["value"]), 30)
        self.history("project.undo")
        undone = self.revision
        self.assertAlmostEqual(float(self.fields(half)["value"]), 20)
        self.client.stop(kill=True)
        self.client.start(self.workspace)
        capability = self.client.rpc("capabilities.get", self.client.params({}, mutation=False))
        self.assertEqual(capability["idempotency_policy"]["request_key_epoch"], self.client.epoch)
        current = self.view("parameter", width)
        self.assertEqual(current["revision_id"], undone)
        self.assertTrue(current["history"]["can_redo"])
        replay = self.client.params({"expected_revision": self.revision, "command_id": str(uuid4())}, project=self.project_id)
        redone = self.client.rpc("project.redo", replay)
        self.revision = redone["new_revision"]
        self.assertEqual(self.client.rpc("project.redo", replay), redone)
        self.assertAlmostEqual(float(self.fields(half)["value"]), 30)
        self.assertEqual(frozen_path.read_bytes(), frozen)

    def test_selection_dto_and_property_changes_keep_input_units_and_redo_branch(self):
        """! @brief 원본 전체 대신 선택 DTO를 받고 단위 변경과 새 편집 분기를 검증한다."""
        width = str(uuid4())
        self.edit("new_parameter", width, {"name": "폭", "mode": "value", "value": "40", "unit": "mm", "dimension": "length"})
        dto = self.view("parameter", width)
        self.assertNotIn("document", dto)
        self.assertNotIn("parameters", dto)
        self.assertEqual(dto["selection"]["id"], width)
        self.assertTrue(any(item["id"] == width for item in dto["items"]))
        self.edit("parameter", width, {"value": "0.05", "unit": "m"})
        self.assertEqual(self.fields(width)["unit"], "m")
        self.assertAlmostEqual(float(self.fields(width)["value"]), 0.05)
        self.history("project.undo")
        self.assertEqual(self.fields(width)["unit"], "mm")
        self.assertAlmostEqual(float(self.fields(width)["value"]), 40)
        self.edit("parameter", width, {"name": "변경된 폭"})
        self.assertFalse(self.view("parameter", width)["history"]["can_redo"])
        self.assertAlmostEqual(float(self.fields(width)["value"]), 40)


if __name__ == "__main__":
    unittest.main()
