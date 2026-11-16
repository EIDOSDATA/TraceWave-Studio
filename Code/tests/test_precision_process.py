"""! @brief 실제 stdio 프로세스의 후보/영수증/재시작/원본 출처 보존을 확인한다."""

import json
import unittest
from uuid import uuid4

import test_canvas_process


class PrecisionProcessTests(unittest.TestCase):
    """! @brief GUI와 같은 전송 계약으로 정밀 편집을 실행한다."""

    def setUp(self):
        """! @brief 기존 프로세스 시험의 실제 stdio 클라이언트만 재사용한다."""
        self.fixture = test_canvas_process.CanvasProcessTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_preview_atomic_apply_save_and_reopen_preserve_sources_after_kill(self):
        """! @brief 같은 요청 재수신과 강제 종료 후에도 후보와 과거 사본이 일치한다."""
        fixture, client = self.fixture, self.fixture.client
        _, layer, line, arc = fixture.create_scene()
        before = fixture.shapes(fixture.view())
        data = {"expected_revision": fixture.revision, "selection_ids": [line, arc], "operation": "mirror", "values": {"axis": "x", "offset_mm": 10}}
        params = client.params(data, project=fixture.project_id, mutation=False)
        candidate = client.rpc("precision.preview", params)
        repeated = client.rpc("precision.preview", params)
        self.assertTrue(candidate["can_apply"], candidate["notices"])
        self.assertEqual(candidate, repeated)
        self.assertEqual(fixture.shapes(fixture.view()), before)
        request = client.params({**data, "command_id": str(uuid4()), "review_hash": candidate["review_hash"], "reason": ""}, project=fixture.project_id)
        response = client.rpc("precision.apply", request)
        fixture.revision = response["new_revision"]
        self.assertEqual(client.rpc("precision.apply", request), response)
        self.assertEqual(response["selection_ids"], [line, arc])
        self.assertEqual(fixture.shapes(fixture.view())[arc]["sweep_angle"], 270)
        client.finish(client.rpc("project.save", client.params({"expected_revision": fixture.revision}, project=fixture.project_id)))
        snapshot = client.finish(client.rpc("snapshot.create", client.params({"expected_revision": fixture.revision}, project=fixture.project_id)))
        frozen_path = fixture.workspace / snapshot["artifact"]["uri"]
        frozen = frozen_path.read_bytes()
        source = json.loads(frozen)
        record = source["extensions"]["rfad.precision-origin"]["records"][0]
        self.assertEqual(record["review_hash"], candidate["review_hash"])
        self.assertEqual(record["selection_ids"], [line, arc])
        source_layer = next(row for row in source["stackup"] if row["id"] == layer)
        self.assertIsNone(source_layer["material_id"])
        self.assertEqual(source_layer["thickness"]["status"], "missing")
        fixture.restart()
        opened = client.finish(client.rpc("project.open", client.params({"path": fixture.path, "open_mode": "open"})))
        self.assertEqual(opened["revision_id"], fixture.revision)
        self.assertEqual(client.rpc("precision.apply", request), response)
        fixture.history("project.undo")
        self.assertEqual(fixture.shapes(fixture.view()), before)
        fixture.history("project.redo")
        dims = client.rpc("precision.get", client.params({"expected_revision": fixture.revision, "selection_ids": [arc]}, project=fixture.project_id, mutation=False))
        self.assertEqual(next(row for row in dims["dimensions"] if row["key"] == "arc.sweep_angle")["value"], 270)
        self.assertEqual(frozen_path.read_bytes(), frozen)


if __name__ == "__main__":
    unittest.main()
