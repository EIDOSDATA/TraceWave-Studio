"""! @brief 선택 속성 편집과 영속 실행 취소의 값/원자성/호환 경계를 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.editor import fields_for, edit_command, build_dto
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from test_design import build_design


class EditorServiceTests(unittest.TestCase):
    """! @brief 실제 journal에 조회/편집/이력을 적용하여 실패 전후 상태를 비교한다."""

    def setUp(self):
        """! @brief 각 시험에 독립 프로젝트와 workspace를 만든다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "속성 편집"
        self.service = ProjectService(self.path, auto_run=False)
        task = self.service.mutate("project.open", self.request({"open_mode": "create", "path": "projects/editor", "name": "속성 시험"}, {}))
        self.service.run_next()
        result = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})["events"][-1]["operation_result"]
        self.project = result["project_id"]
        self.revision = result["revision_id"]

    def tearDown(self):
        """! @brief 실제 파일 잠금을 해제한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, data, context=None):
        """! @brief mutation의 새 키와 발급 epoch를 지정한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project} if context is None else context, "input": data,
                "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def command(self, kind, payload):
        """! @brief 기존 명령도 편집 이력에 참여하는지 확인한다."""
        result = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": kind, "payload": payload}))
        self.revision = result["new_revision"]
        return result

    def edit(self, kind, identity, values):
        """! @brief 선택 기준을 명시하고 변경 필드만 전송한다."""
        result = self.service.mutate("editor.apply", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "selection": {"kind": kind, "id": identity}, "values": values}))
        self.revision = result["new_revision"]
        return result

    def dto(self, kind="project", identity=None):
        """! @brief 선택 DTO의 조회 전후 journal이 변하지 않는지 확인한다."""
        before = self.service.journal.read()
        result = self.service.editor_state({"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": {"expected_revision": self.revision, "selection": {"kind": kind, "id": identity or self.project}}})
        self.assertEqual(before, self.service.journal.read())
        return result

    def document(self):
        """! @brief 시험에서만 실제 원본을 직접 읽는다."""
        project = self.service.journal.read()["projects"][self.project]
        return self.service._load(project)

    def history(self, action):
        """! @brief undo와 redo 모두 새 개정을 발행하는지 확인한다."""
        previous = self.revision
        result = self.service.mutate("project." + action, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
        self.revision = result["new_revision"]
        self.assertNotEqual(previous, self.revision)
        self.assertEqual(self.document()["parent_revision_ids"], [previous])
        return result

    def test_new_parameter_is_missing_until_explicit_value_and_name_edit_preserves_source(self):
        identity = str(uuid4())
        fields = {item["key"]: item["value"] for item in self.dto("new_parameter", identity)["selection"]["fields"]}
        self.assertEqual(fields["mode"], "missing")
        self.assertEqual(fields["value"], "")
        self.edit("new_parameter", identity, {"name": "유전율", "dimension": "dimensionless", "unit": "1"})
        self.assertIsNone(self.document()["parameters"][identity]["quantity"]["value_si"])
        quantity = Quantity.from_value(4.3, "1", status="estimated", source_refs=("검토용 자료",)).to_dict()
        self.command("parameter.set", {"id": identity, "name": "유전율", "quantity": quantity})
        self.edit("parameter", identity, {"name": "재료 유전율"})
        self.assertEqual(self.document()["parameters"][identity]["quantity"], quantity)

    def test_display_unit_only_preserves_si_and_provenance_and_explicit_value_is_converted(self):
        identity = str(uuid4())
        original = Quantity.from_value(40, "mm", status="estimated", source_refs=("도면",)).to_dict()
        self.command("parameter.set", {"id": identity, "name": "폭", "quantity": original})
        self.edit("parameter", identity, {"unit": "m"})
        displayed = self.document()["parameters"][identity]["quantity"]
        self.assertEqual(displayed, {**original, "display_unit": "m"})
        self.edit("parameter", identity, {"value": "60", "unit": "mm"})
        self.assertEqual(self.document()["parameters"][identity]["quantity"]["value_si"], 0.06)
        self.assertEqual(self.document()["parameters"][identity]["quantity"]["status"], "user_entered")

    def test_inactive_readonly_unknown_and_nonfinite_fields_preserve_entire_journal(self):
        identity = str(uuid4())
        self.edit("new_parameter", identity, {"name": "폭", "mode": "value", "value": "40"})
        for changes in ({"expression": "1 mm"}, {"bindings": {"x": identity}}, {"status": "estimated"}, {"id": str(uuid4())}, {"value": "NaN"}, {"value": "Infinity"}, {"value": ""}, {"unit": "unknown"}):
            with self.subTest(changes=changes):
                before = self.service.journal.read()
                with self.assertRaises(ProjectError) as caught:
                    self.edit("parameter", identity, changes)
                self.assertIn("field_path", caught.exception.details)
                self.assertEqual(before, self.service.journal.read())

    def test_expression_recalculates_then_undo_restores_source_and_dependencies(self):
        width, half = str(uuid4()), str(uuid4())
        self.edit("new_parameter", width, {"name": "폭", "mode": "value", "value": "40"})
        self.edit("new_parameter", half, {"name": "반폭", "mode": "expression", "expression": "w / 2", "bindings": {"w": width}})
        self.edit("parameter", width, {"value": "60"})
        self.assertEqual(self.document()["parameters"][half]["quantity"]["value_si"], 0.03)
        self.history("undo")
        self.assertEqual(self.document()["parameters"][half]["quantity"]["value_si"], 0.02)
        before = self.service.journal.read()
        with self.assertRaises(ProjectError) as caught:
            self.edit("parameter", width, {"mode": "expression", "expression": "h * 2", "bindings": {"h": half}})
        self.assertEqual(caught.exception.code, "E_EXPR_CYCLE")
        self.assertEqual(before, self.service.journal.read())

    def test_undo_redo_replay_restart_and_branch_preserve_saved_baseline(self):
        baseline = self.revision
        self.edit("project", self.project, {"name": "새 이름", "description": "새 설명"})
        edited = self.revision
        params = self.request({"expected_revision": edited, "command_id": str(uuid4())})
        undone = self.service.mutate("project.undo", params)
        self.revision = undone["new_revision"]
        self.assertNotEqual(self.revision, baseline)
        self.assertEqual(self.document()["metadata"]["name"], "속성 시험")
        self.assertEqual(self.document()["metadata"]["description"], "")
        self.assertEqual(self.service.mutate("project.undo", params), undone)
        self.service.close()
        self.service = ProjectService(self.path, auto_run=False)
        self.assertTrue(self.dto()["history"]["can_redo"])
        self.history("redo")
        self.assertEqual(self.document()["metadata"]["description"], "새 설명")
        self.assertEqual(self.dto()["saved_revision"], baseline)
        self.history("undo")
        self.command("metadata.rename", {"name": "다른 분기"})
        self.assertFalse(self.dto()["history"]["can_redo"])
        before = self.service.journal.read()
        with self.assertRaises(ProjectError):
            self.history("redo")
        self.assertEqual(before, self.service.journal.read())

    def test_publish_failure_does_not_move_history_or_commit_receipt(self):
        self.command("metadata.rename", {"name": "이름 변경"})
        before = self.service.journal.read()
        def fault(stage):
            if stage == "before_publish":
                raise OSError("시험 게시 실패")
        self.service.journal.fault_hook = fault
        with self.assertRaises(ProjectError):
            self.history("undo")
        self.service.journal.fault_hook = None
        self.assertEqual(before, self.service.journal.read())
        self.history("undo")
        self.assertEqual(self.document()["metadata"]["name"], "속성 시험")

    def test_old_workspace_history_is_rebuilt_without_rewriting_revisions(self):
        self.command("metadata.rename", {"name": "이전 구현의 변경"})
        before = self.document()
        self.service.journal.transaction(lambda state: state["projects"][self.project].pop("history"))
        self.service.close()
        self.service = ProjectService(self.path, auto_run=False)
        self.assertEqual(self.document(), before)
        self.assertTrue(self.dto()["history"]["can_undo"])
        self.history("undo")
        self.assertEqual(self.document()["metadata"]["name"], "속성 시험")

    def test_history_head_mismatch_blocks_edit_and_undo_without_changing_state(self):
        self.command("metadata.rename", {"name": "변경된 원본"})
        self.service.journal.transaction(lambda state: state["projects"][self.project]["history"].update(head_revision=str(uuid4())))
        before = self.service.journal.read()
        for operation in (lambda: self.history("undo"), lambda: self.command("metadata.rename", {"name": "허용하지 않음"}), self.dto):
            with self.assertRaises(ProjectError) as caught:
                operation()
            self.assertEqual(caught.exception.code, "E_CONFLICT")
            self.assertEqual(self.service.journal.read(), before)

    def test_history_budget_keeps_recent_commands_and_never_changes_saved_revision(self):
        baseline = self.revision
        with patch("rfad.application.projects.MAX_HISTORY", 3):
            for index in range(5):
                self.command("metadata.rename", {"name": str(index)})
            self.assertEqual(self.dto()["history"]["undo_count"], 3)
            for _ in range(3):
                self.history("undo")
            self.assertEqual(self.document()["metadata"]["name"], "1")
            self.assertFalse(self.dto()["history"]["can_undo"])
            self.assertEqual(self.dto()["saved_revision"], baseline)

    def test_rpc_read_only_stale_selection_error_keeps_request_id_and_no_original(self):
        request = {"jsonrpc": "2.0", "id": "조회-1", "method": "editor.get", "params": {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": {"expected_revision": self.revision}}}
        response = handle_frame(json.dumps(request).encode(), self.service)
        self.assertEqual(response["id"], "조회-1")
        self.assertNotIn("document", response["result"])
        self.assertEqual(response["result"]["profile"], "rfad.editor/0.1")
        self.command("metadata.rename", {"name": "다음 버전"})
        stale = handle_frame(json.dumps(request).encode(), self.service)
        self.assertEqual(stale["id"], "조회-1")
        self.assertEqual(stale["error"]["data"]["domain_code"], "E_CONFLICT")


class DesignEditorTests(unittest.TestCase):
    """! @brief 지원 설계 객체의 스칼라/참조 편집에서 수치와 원본 보호를 검증한다."""

    def setUp(self):
        """! @brief 서로 연결된 최소 설계 원본을 만든다."""
        self.document = build_design()

    def selection(self, kind, obj):
        """! @brief 명시적 종류와 안정 ID 선택을 만든다."""
        return {"kind": kind, "id": obj["id"]}

    def test_supported_entity_fields_and_quantity_reference_edits(self):
        for kind, collection in (("material", "materials"), ("layer", "stackup"), ("net", "nets"), ("geometry", "geometry"), ("port", "ports")):
            for obj in self.document[collection]:
                fields = fields_for(self.document, self.selection(kind, obj))
                self.assertTrue(fields)
                self.assertTrue(next(field for field in fields if field["key"] == "id")["readonly"])
        board = self.document["board"]
        selection = self.selection("board", board)
        original = deepcopy(board["outline"]["width"])
        command = edit_command(self.document, selection, {"outline.width.unit": "m"})
        self.assertEqual(command["payload"]["board"]["outline"]["width"], {**original, "display_unit": "m"})
        for changes in ({"outline.width.parameter_id": next(iter(self.document["parameters"]), str(uuid4()))}, {"id": str(uuid4())}):
            with self.assertRaises(ProjectError):
                edit_command(self.document, selection, changes)

    def test_integer_backed_port_vector_accepts_valid_real_direction(self):
        port = self.document["ports"][0]
        port["direction"] = [0, 0, 1]
        validate_project(self.document)
        command = edit_command(self.document, self.selection("port", port), {"direction.0": "0.6", "direction.2": "0.8"})
        self.assertEqual(command["payload"]["port"]["direction"], [0.6, 0, 0.8])

    def test_valid_extreme_quantity_is_displayed_in_si_without_zero_substitution(self):
        identity = str(uuid4())
        quantity = Quantity(5e-324, "frequency", "GHz", "user_entered").to_dict()
        self.document["parameters"][identity] = {"id": identity, "name": "작은 주파수", "quantity": quantity}
        validate_project(self.document)
        selection = {"kind": "parameter", "id": identity}
        fields = {item["key"]: item["value"] for item in fields_for(self.document, selection)}
        self.assertEqual(fields["unit"], "Hz")
        self.assertEqual(fields["value"], "5e-324")
        self.assertTrue(fields["display_note"])
        command = edit_command(self.document, selection, {"name": "다른 이름"})
        self.assertEqual(command["payload"]["quantity"], quantity)

    def test_large_dto_fails_explicitly_before_transport_without_partial_fields(self):
        with patch("rfad.application.editor.MAX_DTO_BYTES", 128):
            with self.assertRaises(ProjectError) as caught:
                build_dto(self.document, self.document["revision_id"], {}, None)
            self.assertEqual(caught.exception.code, "E_RESOURCE")

    def test_explicit_empty_or_wrong_selection_is_not_silently_replaced(self):
        for selection in ({}, [], False, 0, ""):
            with self.subTest(selection=selection):
                with self.assertRaises(ProjectError):
                    build_dto(self.document, self.document["revision_id"], {}, selection)

    def test_korean_display_metadata_preserves_raw_values_and_readonly_contract(self):
        identity = str(uuid4())
        original = Quantity.missing("length", "mm").to_dict()
        self.document["parameters"][identity] = {"id": identity, "name": "보드 폭", "quantity": original}
        selection = {"kind": "parameter", "id": identity}
        fields = {item["key"]: item for item in fields_for(self.document, selection)}
        self.assertEqual(fields["status"]["value"], "missing")
        self.assertEqual(fields["status"]["display_value"], "미정")
        self.assertTrue(fields["status"]["readonly"])
        self.assertTrue(fields["status"]["help"])
        self.assertIn({"value": "length", "label": "길이"}, fields["dimension"]["choices"])
        self.assertIn({"value": "conductivity", "label": "전도도"}, fields["dimension"]["choices"])
        command = edit_command(self.document, selection, {"name": "수정된 이름"})
        self.assertEqual(command["payload"]["quantity"], original)
        for values in ({"status": "미정"}, {"dimension": "길이"}):
            with self.assertRaises(ProjectError):
                edit_command(self.document, selection, values)

    def test_named_objects_and_reference_ids_survive_localized_kind_role_and_frame_labels(self):
        geometry = self.document["geometry"][0]
        fields = {item["key"]: item for item in fields_for(self.document, self.selection("geometry", geometry))}
        self.assertEqual(fields["kind"]["value"], geometry["kind"])
        self.assertIn(fields["kind"]["display_value"], ("선 패턴", "원호 패턴"))
        self.assertTrue(fields["id"]["advanced"])
        self.assertEqual(fields["id"]["value"], geometry["id"])
        self.assertTrue(fields["frame_id"]["advanced"])
        self.assertEqual(fields["frame_id"]["value"], geometry["frame_id"])
        self.assertIn(fields["frame_id"]["display_value"], ("기준 좌표계", "기판 좌표계"))
        self.assertIn({"value": "radiator", "label": "방사체"}, fields["role"]["choices"])
        material = self.document["materials"][0]
        material["name"] = "사용자가 정한 dielectric 이름"
        material_fields = {item["key"]: item for item in fields_for(self.document, self.selection("material", material))}
        self.assertEqual(material_fields["name"]["value"], material["name"])
        self.assertEqual(material_fields["model"]["value"], "isotropic_constant")
        self.assertEqual(material_fields["model"]["display_value"], "등방성 상수 모델")
        dto = build_dto(self.document, self.document["revision_id"], {}, self.selection("port", self.document["ports"][0]))
        self.assertEqual(next(item["label"] for item in dto["items"] if item["id"] == material["id"]), material["name"])
        port_fields = {item["key"]: item for item in dto["selection"]["fields"]}
        choice = next(item for item in port_fields["positive_geometry_id"]["choices"] if item["value"] == geometry["id"])
        self.assertTrue(choice["label"].startswith(("선 패턴 ", "원호 패턴 ")))


if __name__ == "__main__":
    unittest.main()
