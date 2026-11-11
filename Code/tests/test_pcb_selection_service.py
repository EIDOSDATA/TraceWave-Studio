"""! @brief PCB 선택의 공개 미리보기, 원자 적용과 실제 저장소 재시작을 검증한다."""

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.rpc import handle_frame, serve
from rfad.catalog.build import build_catalog
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_selection import EXTENSION_KEY
from test_catalog_build import make_package
from test_design import quantity
from test_pcb_solver import fixture_document, snapshot_for, runtime_identity, SETTINGS


def manual_material(key="core", *, catalog=False):
    """! @brief 실제 재료 기본값이 아닌 시험 전용 명시적 입력이다."""
    return {"key": key, "name": "시험 " + key, "properties": {
        "epsilon_r": {"mode": "catalog", "record_id": "PCB000002", "reason": "시험 원문 선택"} if catalog
        else {"mode": "user", "value": 4.2, "reason": "시험 가정"},
        "tan_delta": {"mode": "missing", "reason": "시험 입력에서 손실을 모름"},
        "conductivity": {"mode": "user", "value": 0, "reason": "시험 가정: 추가 도전 손실 없음"}},
        "validity_hz": {"min": None, "max": None, "reason": "모델 적용 대역 미정"}}


def manual_specification():
    """! @brief 세 물리 층과 원형 기판을 다루는 작은 시험 사양이다."""
    return {"source": None, "materials": [manual_material()], "layers": [
        {"key": "bottom", "name": "아래 동박", "role": "conductor", "thickness_mm": 0.035},
        {"key": "core", "name": "코어", "role": "dielectric", "thickness_mm": 1.0},
        {"key": "top", "name": "위 동박", "role": "conductor", "thickness_mm": 0.035}],
        "layout_reason": "제작 사양이 아닌 시험용 명시 적층", "material_assignments": {"core": "core"}}


class PcbSelectionServiceTests(unittest.TestCase):
    """! @brief 한 번의 writer transaction과 출처 독립 재현성을 확인한다."""

    def setUp(self):
        """! @brief 작은 실제 카탈로그와 별도 임시 프로젝트 저장소를 만든다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "catalog.sqlite"
        make_package(self.root / "source")
        self.catalog_id = build_catalog(self.root / "source", self.database)["catalog_id"]
        self.workspace = self.root / "작업 공간"
        self.service = ProjectService(self.workspace, auto_run=False, catalog_database=self.database)
        opened = self.complete("project.open", self.request({"path": "projects/test", "open_mode": "create", "name": "기판 선택"}))
        self.project_id = opened["project_id"]
        board = {"id": str(uuid4()), "frame_id": opened["document"]["frames"]["board"]["id"],
                 "outline": {"kind": "circle", "center": [quantity(0, "mm"), quantity(0, "mm")], "radius": quantity(30, "mm")},
                 "thickness_convention": "finished"}
        self.command("board.set", {"board": board})

    def tearDown(self):
        """! @brief 임시 저장소 소유 잠금과 파일을 회수한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, value, *, read=False, global_context=False):
        """! @brief 같은 공개 envelope로 조회와 변경을 구분한다."""
        context = {} if global_context or not hasattr(self, "project_id") else {"project_id": self.project_id}
        params = {"contract_version": "rfad.api/2.0", "context": context, "input": value}
        if not read:
            params.update(request_key=str(uuid4()), request_key_epoch=self.service.policy()["request_key_epoch"])
        return params

    def complete(self, method, params):
        """! @brief 기존 자료 처리 작업을 실제 journal에서 완료한다."""
        job = self.service.mutate(method, params)
        self.assertTrue(self.service.run_next())
        status = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": job["job_id"]}})
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def document(self):
        """! @brief 공개 저장소가 검증한 현재 불변 원본을 읽는다."""
        return self.service.repository.load(self.service.journal.read()["projects"][self.project_id])

    def command(self, kind, payload):
        """! @brief 기존 직접 편집 명령도 같은 영속 경계로 보낸다."""
        return self.service.mutate("project.apply_command", self.request({"expected_revision": self.document()["revision_id"],
                                   "command_id": str(uuid4()), "type": kind, "payload": payload}))

    def selection(self, spec=None):
        """! @brief 새 선택 ID와 현재 기준 개정을 함께 고정한다."""
        return {"expected_revision": self.document()["revision_id"], "selection_id": str(uuid4()),
                "specification": manual_specification() if spec is None else spec}

    def preview(self, data):
        """! @brief 공개 읽기 API의 결과를 확인한다."""
        return self.service.pcb_selection.preview(self.request(data, read=True))

    def apply(self, data):
        """! @brief 검토한 해시를 같은 변경 요청에 명시한다."""
        preview = self.preview(data)
        self.assertTrue(preview["can_apply"], preview["issues"])
        params = self.request({**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())})
        return self.service.mutate("pcb.selection.apply", params), params

    def test_preview_is_pure_and_one_apply_undo_redo_preserves_outline(self):
        before = self.document()
        journal = self.service.journal.read()
        data = self.selection()
        preview = self.preview(data)
        self.assertEqual(self.service.journal.read(), journal)
        self.assertEqual(self.document(), before)
        self.assertAlmostEqual(preview["modeled_total_thickness_mm"], 1.07)
        changed, params = self.apply(data)
        after = self.document()
        self.assertEqual(after["board"], before["board"])
        self.assertIn(EXTENSION_KEY, after["extensions"])
        self.assertEqual(changed["history"]["undo_count"], 2)
        self.assertEqual(self.service.mutate("pcb.selection.apply", params), changed)
        undone = self.service.mutate("project.undo", self.request({"expected_revision": after["revision_id"], "command_id": str(uuid4())}))
        self.assertEqual(self.document()["stackup"], before["stackup"])
        self.assertNotIn(EXTENSION_KEY, self.document()["extensions"])
        self.service.mutate("project.redo", self.request({"expected_revision": undone["new_revision"], "command_id": str(uuid4())}))
        for field in ("materials", "stackup", "ports", "extensions"):
            self.assertEqual(self.document()[field], after[field])

    def test_catalog_copy_survives_database_removal_save_snapshot_and_restart(self):
        spec = manual_specification()
        spec.update(catalog_id=self.catalog_id)
        spec["materials"] = [manual_material(catalog=True)]
        changed, params = self.apply(self.selection(spec))
        original = self.document()
        self.complete("project.save", self.request({"expected_revision": changed["new_revision"]}))
        snapshot = self.complete("snapshot.create", self.request({"expected_revision": changed["new_revision"]}))
        captured = json.loads(self.service.journal.read_artifact(snapshot["artifact"]))
        self.assertEqual(captured, original)
        self.service.close()
        self.database.unlink()
        self.service = ProjectService(self.workspace, auto_run=False, catalog_database=self.database)
        selected = self.service.pcb_selection.get(self.request({}, read=True))
        self.assertFalse(selected["modified_since_selection"])
        self.assertEqual(selected["selection"], original["extensions"][EXTENSION_KEY])
        self.assertEqual(self.service.mutate("pcb.selection.apply", params), changed)
        material = deepcopy(original["materials"][0])
        material["epsilon_r"] = quantity(3.8, "1")
        self.command("material.set", {"material": material})
        selected = self.service.pcb_selection.get(self.request({}, read=True))
        self.assertTrue(selected["modified_since_selection"])
        self.assertEqual(selected["selection"], original["extensions"][EXTENSION_KEY])
        self.assertTrue(any(item["target"]["field"] == "epsilon_r" for item in selected["changed_selected_fields"]))

    def test_stale_hash_revision_and_unknown_mapping_never_publish(self):
        data = self.selection()
        preview = self.preview(data)
        before = self.service.journal.read()
        bad = self.request({**data, "preview_hash": "0" * 64, "command_id": str(uuid4())})
        with self.assertRaises(ProjectError):
            self.service.mutate("pcb.selection.apply", bad)
        self.assertEqual(self.service.journal.read(), before)
        data["specification"]["layer_ids"] = {"top": str(uuid4())}
        with self.assertRaises(ProjectError):
            self.preview(data)
        self.assertEqual(self.service.journal.read(), before)
        data["specification"].pop("layer_ids")
        self.command("metadata.rename", {"name": "새 개정"})
        with self.assertRaises(ProjectError) as error:
            self.service.mutate("pcb.selection.apply", self.request({**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())}))
        self.assertEqual(error.exception.code, "E_CONFLICT")

    def test_missing_thickness_stops_z_inference_and_keeps_direct_input(self):
        data = self.selection()
        data["specification"]["layers"][1]["thickness_mm"] = None
        preview = self.preview(data)
        self.assertTrue(preview["can_apply"], preview["issues"])
        self.assertIsNone(preview["candidate"]["stackup"][2]["z_min"]["value_si"])
        self.assertFalse(preview["input_checks"]["solver_ready"])
        self.apply(data)
        layer = deepcopy(self.document()["stackup"][1])
        layer["thickness"] = quantity(1.2, "mm")
        self.command("layer.set", {"layer": layer})
        self.assertTrue(self.service.pcb_selection.get(self.request({}, read=True))["modified_since_selection"])

    def test_notification_batch_and_raw_internal_command_do_not_mutate(self):
        data = self.selection()
        preview = self.preview(data)
        params = self.request({**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())})
        request = {"jsonrpc": "2.0", "method": "pcb.selection.apply", "params": params}
        before = self.service.journal.read()
        self.assertIsNone(handle_frame(json.dumps(request).encode(), self.service))
        request["id"] = "apply"
        self.assertIn("error", handle_frame(json.dumps([request]).encode(), self.service))
        self.assertEqual(self.service.journal.read(), before)
        with self.assertRaises(ProjectError):
            self.command("pcb_stackup.apply", {"materials": [], "stackup": [], "ports": [], "selection": None})
        self.assertEqual(self.service.journal.read(), before)
        source = io.BytesIO((json.dumps({"jsonrpc": "2.0", "id": "x" * 8192, "method": "pcb.selection.preview",
                                         "params": self.request(data, read=True)}) + "\n").encode())
        output = io.BytesIO()
        self.assertEqual(serve(source, output, io.StringIO(), self.service), 0)
        self.assertLessEqual(len(output.getvalue()), 65537)
        self.assertTrue(json.loads(output.getvalue())["result"]["can_apply"])

    def install_design(self, document):
        """! @brief 기존 공개 편집 명령으로 시험 설계를 현재 프로젝트에 입력한다."""
        frame_id = self.document()["frames"]["board"]["id"]
        for collection, kind, field in (("materials", "material.set", "material"),
                                         ("stackup", "layer.set", "layer"), ("nets", "net.set", "net"),
                                         ("geometry", "geometry.set", "geometry"), ("ports", "port.set", "port")):
            for original in sorted(document[collection], key=lambda item: item.get("kind") == "via"):
                item = deepcopy(original)
                if "frame_id" in item:
                    item["frame_id"] = frame_id
                self.command(kind, {field: item})

    def mapped_specification(self, document):
        """! @brief 층 ID와 재료를 보존하는 전체 물리 층 목록을 만든다."""
        ordered = sorted(document["stackup"], key=lambda layer: layer["order"])
        return {"source": None, "materials": [], "layers": [
            {"key": layer["id"], "name": layer["name"], "role": layer["role"],
             "thickness_mm": layer["thickness"]["value_si"] * 1000} for layer in ordered],
            "layer_ids": {layer["id"]: layer["id"] for layer in document["stackup"]},
            "z_origin_mm": ordered[0]["z_min"]["value_si"] * 1000,
            "layout_reason": "시험에서 명시한 층 대응과 두께 변경"}

    def test_mapped_patterns_and_port_review_reach_solver_without_changing_outline(self):
        self.install_design(fixture_document(circle=True, arc=True))
        before = self.document()
        baseline = build_pcb_plan(before, snapshot_for(before), runtime_identity(), SETTINGS)
        spec = self.mapped_specification(before)
        spec["layers"][0]["thickness_mm"] = 1.2
        data = self.selection(spec)
        preview = self.preview(data)
        self.assertFalse(preview["can_apply"])
        self.assertTrue(any(item["code"] == "port_coordinates_require_review" for item in preview["issues"]))
        port = before["ports"][0]
        spec["port_updates"] = [{"id": port["id"], "start_mm": [-1, 0, 1], "stop_mm": [1, 0, 1], "reason": "기존 급전 좌표 검토"}]
        self.assertTrue(any(item["code"] == "port_not_on_selected_layer" for item in self.preview(data)["issues"]))
        spec["port_updates"][0].update(start_mm=[-1, 0, 1.2], stop_mm=[1, 0, 1.2])
        changed, _ = self.apply(data)
        after = self.document()
        for field in ("board", "geometry", "nets"):
            self.assertEqual(after[field], before[field])
        self.assertEqual([item["id"] for item in after["stackup"]], [item["id"] for item in before["stackup"]])
        plan = build_pcb_plan(after, snapshot_for(after), runtime_identity(), SETTINGS)
        self.assertNotEqual(plan["case"], baseline["case"])
        unknown = deepcopy(after)
        unknown["extensions"]["unknown.physics"] = {"enabled": True}
        with self.assertRaises(ProjectError):
            build_pcb_plan(unknown, snapshot_for(unknown), runtime_identity(), SETTINGS)
        self.service.mutate("project.undo", self.request({"expected_revision": changed["new_revision"], "command_id": str(uuid4())}))
        for field in ("materials", "stackup", "ports", "extensions"):
            self.assertEqual(self.document()[field], before[field])

    def test_unmapped_referenced_layers_are_blocked_and_via_span_remains_explicit(self):
        document = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pth_worker_smoke.json").read_text(encoding="utf-8"))["document"]
        self.install_design(document)
        before = self.document()
        spec = self.mapped_specification(before)
        spec["layer_ids"] = {}
        data = self.selection(spec)
        self.assertFalse(self.preview(data)["can_apply"])
        spec["layer_ids"] = {layer["id"]: layer["id"] for layer in before["stackup"]}
        dielectric = next(layer for layer in spec["layers"] if layer["role"] == "dielectric")
        dielectric["thickness_mm"] += 0.1
        preview = self.preview(data)
        self.assertTrue(any(item["code"] == "via_span_changed" for item in preview["issues"]))
        self.assertEqual(self.document(), before)
        self.assertTrue(preview["changes"]["geometry_preserved"])

    def test_selection_commit_failure_and_lost_ack_replay_are_atomic(self):
        data = self.selection()
        preview = self.preview(data)
        params = self.request({**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())})
        before = self.service.journal.read()

        def fail_before(stage):
            """! @brief payload가 있어도 포인터 게시 전에는 이전 설계가 유지된다."""
            if stage == "before_publish":
                raise OSError("시험 저장 실패")

        self.service.journal.fault_hook = fail_before
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("pcb.selection.apply", params)
        self.assertFalse(caught.exception.details["committed"])
        self.assertEqual(self.service.journal.read(), before)

        def fail_after(stage):
            """! @brief 게시 뒤 응답 유실은 같은 영수증의 재전송으로 복구한다."""
            if stage == "after_publish":
                raise OSError("시험 응답 유실")

        self.service.journal.fault_hook = fail_after
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("pcb.selection.apply", params)
        self.assertTrue(caught.exception.details["committed"])
        self.service.journal.fault_hook = None
        committed = self.document()
        result = self.service.mutate("pcb.selection.apply", params)
        self.assertEqual(result["new_revision"], committed["revision_id"])
        self.assertEqual(self.document(), committed)
        self.assertEqual(result["history"]["undo_count"], 2)

    def test_changed_catalog_and_project_byte_budget_do_not_publish(self):
        spec = manual_specification()
        spec.update(catalog_id=self.catalog_id)
        spec["materials"] = [manual_material(catalog=True)]
        data = self.selection(spec)
        preview = self.preview(data)
        before = self.service.journal.read()
        self.database.unlink()
        with self.assertRaises(ProjectError):
            self.service.mutate("pcb.selection.apply", self.request({**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())}))
        self.assertEqual(self.service.journal.read(), before)
        data = self.selection()
        data["specification"]["notes"] = ["큰 출처 설명 " + "가" * 990 for _ in range(12)]
        preview = self.preview(data)
        self.assertFalse(preview["can_apply"])
        self.assertGreater(preview["size"]["document_bytes"], 32768)
        self.assertTrue(any(item["code"] == "E_RESOURCE" for item in preview["issues"]))
        with self.assertRaises(ProjectError):
            self.service.mutate("pcb.selection.apply", self.request({**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())}))
        self.assertEqual(self.service.journal.read(), before)

    def test_reselection_retains_referenced_source_in_latest_snapshot(self):
        spec = manual_specification()
        spec.update(catalog_id=self.catalog_id)
        spec["materials"] = [manual_material(catalog=True)]
        self.apply(self.selection(spec))
        first = self.document()["extensions"][EXTENSION_KEY]
        layer = next(item for item in self.document()["stackup"] if item["role"] == "dielectric")
        data = self.selection({"source": None, "materials": [], "material_assignments": {layer["id"]: None}})
        preview = self.preview(data)
        self.assertTrue(preview["can_apply"], preview["issues"])
        self.assertEqual(preview["retained_selections"][0]["selection_id"], first["id"])
        self.apply(data)
        second = self.document()
        self.assertEqual(second["extensions"][EXTENSION_KEY]["history"], [first])
        self.assertIsNone(next(item for item in second["stackup"] if item["id"] == layer["id"])["material_id"])
        snapshot = self.complete("snapshot.create", self.request({"expected_revision": second["revision_id"]}))
        saved = json.loads(self.service.journal.read_artifact(snapshot["artifact"]))
        self.assertEqual(saved["extensions"][EXTENSION_KEY]["history"][0]["evidence"], first["evidence"])
        self.service.close()
        self.database.unlink()
        self.service = ProjectService(self.workspace, auto_run=False, catalog_database=self.database)
        self.assertEqual(self.service.pcb_selection.get(self.request({}, read=True))["selection"], second["extensions"][EXTENSION_KEY])


if __name__ == "__main__":
    unittest.main()
