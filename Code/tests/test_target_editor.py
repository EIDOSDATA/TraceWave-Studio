"""! @brief 목표 편집 GUI 계약의 출처 보존, 원자 변경과 재접수/이력 경계를 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from rfad.application import target_editor
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.units import Quantity
from test_targets import target_input


def creation_values(name="사용자 대역", start="2400", end="2500", unit="MHz"):
    """! @brief 필수 입력을 명시하며 선택 기준 주파수/임피던스/포트는 미정으로 둔다."""
    return {"name": name, "band.start.mode": "value", "band.start.value": start, "band.start.unit": unit,
            "band.end.mode": "value", "band.end.value": end, "band.end.unit": unit, "sampling.count": "11"}


class TargetEditorTests(unittest.TestCase):
    """! @brief 실제 RPC/ledger/저장소를 사용하며 native solver는 실행하지 않는다."""

    def setUp(self):
        """! @brief 독립 임시 workspace에 사용자 프로젝트를 생성한다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.service = ProjectService(self.workspace, auto_run=False)
        self.project_id = None
        result = self.complete("project.open", {"path": "projects/target-editor", "open_mode": "create", "name": "목표 편집"}, {})
        self.project_id, self.revision = result["project_id"], result["revision_id"]

    def tearDown(self):
        """! @brief 파일 잠금과 임시 workspace를 종료한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, data, context=None):
        """! @brief 기존 공개 요청 epoch와 멱등 키를 사용한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project_id} if context is None else context,
                "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def wire(self, method, params):
        """! @brief 배열 표본과 UTF-8 출처도 실제 RPC 전송 제한을 통과시킨다."""
        return handle_frame(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, ensure_ascii=False).encode("utf-8"), self.service)

    def rpc(self, method, params):
        """! @brief 성공 응답을 요구하고 구조화된 오류를 시험 실패에 표시한다."""
        response = self.wire(method, params)
        self.assertNotIn("error", response, response)
        return response["result"]

    def complete(self, method, data, context=None):
        """! @brief 저장/열기 등 기존 자료 작업을 명시적으로 완료한다."""
        task = self.rpc(method, self.request(data, context))
        self.assertTrue(self.service.run_next())
        status = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def document(self):
        """! @brief 읽기 전용 repository로 현재 원본을 확인한다."""
        state = self.service.journal.read()
        return self.service._load(self.service._project(state, {"project_id": self.project_id}))

    def get(self, identity=None):
        """! @brief 현재 개정의 신규/기존 목표를 조회한다."""
        return self.rpc("target.editor.get", {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project_id},
                                               "input": {"expected_revision": self.revision, "target_id": identity}})

    def edit(self, identity=None, values=None, *, operation="set", reason="사용자가 명시한 변경"):
        """! @brief 성공한 목표 편집의 개정을 추적하고 원 요청을 재전송 시험에 돌려준다."""
        params = self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "operation": operation,
                               "target_id": identity, "values": creation_values() if values is None else values, "reason": reason})
        result = self.rpc("target.editor.apply", params)
        self.revision = result["new_revision"]
        return result, params

    def seed(self, value):
        """! @brief 출처/추정 원본 fixture는 기존 domain 명령으로 입력한다."""
        result = self.rpc("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
                                                                  "type": "target.set", "payload": {"target": value}}))
        self.revision = result["new_revision"]
        return value["id"]

    def move_history(self, method):
        """! @brief GUI와 같은 기존 undo/redo 명령을 사용한다."""
        result = self.rpc(method, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
        self.revision = result["new_revision"]

    def test_blank_read_is_read_only_and_does_not_fill_unknown_inputs(self):
        """! @brief 새 목표 조회는 ID/값/이력이나 임의 기본 물성을 만들지 않는다."""
        before = self.service.journal.read()
        dto = self.get()
        fields = {row["key"]: row for row in dto["selection"]["fields"]}
        self.assertIsNone(dto["selection"]["id"])
        for key in ("name", "band.start.value", "band.end.value", "reference_impedance.value", "sampling.count", "port_id"):
            self.assertEqual(fields[key]["value"], "")
        self.assertEqual(fields["band.start.mode"]["value"], "missing")
        self.assertEqual(fields["criteria.total_efficiency.mode"]["value"], "absent")
        self.assertEqual(dto["input_status"]["evaluation_status"], "not_evaluated")
        self.assertFalse(dto["evaluation_supported"])
        self.assertEqual(self.service.journal.read(), before)

    def test_multiple_bands_save_reopen_replay_and_history_preserve_inputs(self):
        """! @brief 추가/변경/제거를 저장/재시작/undo/redo와 같은 영수증 경로로 처리한다."""
        first, request = self.edit()
        identity = first["target_id"]
        state = self.service.journal.read()
        self.assertEqual(self.rpc("target.editor.apply", request), first)
        self.assertEqual(self.service.journal.read(), state)
        second, _ = self.edit(values=creation_values("두 번째 대역", "5700000000", "5900000000", "Hz"))
        self.assertNotEqual(identity, second["target_id"])
        self.assertEqual(len(self.get(identity)["items"]), 2)
        original = self.document()
        self.complete("project.save", {"expected_revision": self.revision})
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        opened = self.complete("project.open", {"path": "projects/target-editor", "open_mode": "open"}, {})
        self.assertEqual(opened["document"], original)
        self.assertEqual(self.rpc("target.editor.apply", request), first)
        removed, _ = self.edit(identity, {}, operation="remove", reason="중복 대역 정리")
        self.assertEqual(removed["target_id"], identity)
        self.assertEqual(len(self.document()["targets"]), 1)
        self.move_history("project.undo")
        self.assertEqual({row["id"] for row in self.document()["targets"]}, {identity, second["target_id"]})
        self.move_history("project.redo")
        self.assertEqual([row["id"] for row in self.document()["targets"]], [second["target_id"]])

    def test_renaming_preserves_all_quantity_status_source_and_explicit_rows(self):
        """! @brief 이름 변경으로 추정/자료 기본값이나 혼합 단위 명시 표본을 덮어쓰지 않는다."""
        value = target_input()
        value["band"]["start"]["status"] = "estimated"
        samples = [Quantity.from_value(2400, "MHz", status="source_default", source_refs=["원자료 A"]).to_dict(),
                   Quantity.from_value(2.45, "GHz", status="estimated", source_refs=["탐색 가정 B"]).to_dict(),
                   Quantity.from_value(2500000000, "Hz", source_refs=["사용자 입력 C"]).to_dict()]
        value["band"]["sampling"] = {"kind": "explicit", "frequencies": samples}
        identity = self.seed(value)
        before = self.document()["targets"][0]
        dto = self.get(identity)
        self.assertTrue(dto["input_status"]["has_estimated_inputs"])
        self.assertTrue(dto["input_status"]["has_source_defaults"])
        self.assertTrue(all(row["advanced"] for row in dto["selection"]["fields"] if row["readonly"]))
        self.edit(identity, {"name": "이름만 변경"})
        after = self.document()["targets"][0]
        for key in ("band", "reference_impedance", "criteria", "port_id"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after["source_refs"][:-1], before["source_refs"])

    def test_physical_changes_mark_user_input_but_unit_only_retains_origin(self):
        """! @brief 수치 수정과 표시 단위 변경의 provenance 의미를 구분한다."""
        value = target_input()
        value["band"]["start"]["status"] = "source_default"
        identity = self.seed(value)
        original = self.document()["targets"][0]["band"]["start"]
        self.edit(identity, {"band.start.unit": "MHz"}, reason="표시 단위만 변경")
        converted = self.document()["targets"][0]["band"]["start"]
        self.assertEqual(converted["value_si"], original["value_si"])
        self.assertEqual(converted["status"], original["status"])
        self.assertEqual(converted["source_refs"], original["source_refs"])
        self.edit(identity, {"band.start.value": "2410"}, reason="새 대역 선택")
        changed = self.document()["targets"][0]["band"]["start"]
        self.assertEqual(changed["value_si"], 2.41e9)
        self.assertEqual(changed["status"], "user_entered")
        self.assertEqual(changed["source_refs"][:-1], original["source_refs"])
        self.assertIn("새 대역 선택", changed["source_refs"][-1])

    def test_explicit_edit_preserves_unchanged_rows_and_changed_row_origin(self):
        """! @brief 재입력하지 않은 표본은 그대로 두고 수정 표본만 변경 사유를 기록한다."""
        value = target_input()
        value["band"]["sampling"] = {"kind": "explicit", "frequencies": [
            Quantity.from_value(v, "GHz", status="source_default", source_refs=["기존 표본 자료"]).to_dict() for v in (2.4, 2.45, 2.5)]}
        identity = self.seed(value)
        self.edit(identity, {"sampling.explicit": ["2.4 GHz", "2.46 GHz", "2.5 GHz"]}, reason="중간 표본 위치 수정")
        samples = self.document()["targets"][0]["band"]["sampling"]["frequencies"]
        self.assertEqual(samples[0], value["band"]["sampling"]["frequencies"][0])
        self.assertEqual(samples[2], value["band"]["sampling"]["frequencies"][2])
        self.assertEqual(samples[1]["status"], "user_entered")
        self.assertEqual(samples[1]["source_refs"][0], "기존 표본 자료")
        self.assertIn("중간 표본 위치 수정", samples[1]["source_refs"][-1])

    def test_unchanged_explicit_row_avoids_display_conversion_roundtrip(self):
        """! @brief 표시 환산의 한 ULP 차이가 다른 표본 편집으로 원본에 반영되지 않는다."""
        value = target_input(start=33, end=35)
        first = Quantity(33856614214.186718, "frequency", "GHz", "source_default", ["원래 SI 값"]).to_dict()
        value["band"]["sampling"] = {"kind": "explicit", "frequencies": [first, Quantity.from_value(34.5, "GHz").to_dict()]}
        identity = self.seed(value)
        dto = self.get(identity)
        lines = next(row["value"] for row in dto["selection"]["fields"] if row["key"] == "sampling.explicit")
        self.assertNotEqual(Quantity.from_value(float(lines[0].split()[0]), "GHz").value_si, first["value_si"])
        lines[1] = "34.6 GHz"
        self.edit(identity, {"sampling.explicit": lines})
        self.assertEqual(self.document()["targets"][0]["band"]["sampling"]["frequencies"][0], first)

    def test_optional_reference_and_impedance_can_return_to_explicit_missing(self):
        """! @brief 기준 주파수/임피던스의 미정을 0으로 바꾸지 않고 변경 출처를 남긴다."""
        result, _ = self.edit()
        identity = result["target_id"]
        self.edit(identity, {"band.reference.mode": "value", "band.reference.value": "2.45",
                             "reference_impedance.mode": "value", "reference_impedance.value": "50"})
        supplied = self.document()["targets"][0]
        self.assertEqual(supplied["band"]["reference"]["value_si"], 2.45e9)
        self.assertEqual(supplied["reference_impedance"]["value_si"], 50.0)
        self.edit(identity, {"band.reference.mode": "missing", "reference_impedance.mode": "missing"}, reason="조건 후속 확정")
        changed = self.document()["targets"][0]
        for quantity in (changed["band"]["reference"], changed["reference_impedance"]):
            self.assertIsNone(quantity["value_si"])
            self.assertEqual(quantity["status"], "missing")
            self.assertIn("조건 후속 확정", quantity["source_refs"][-1])

    def test_all_metrics_missing_conditions_and_explicit_wire_budget(self):
        """! @brief 1001개 표본은 문자열 배열로 전송하며 4개 지표 입력도 합격으로 바꾸지 않는다."""
        values = creation_values(start="2000", end="3000")
        values.pop("sampling.count")
        values.update({"sampling.kind": "explicit", "sampling.explicit": [f"{2000 + index} MHz" for index in range(1001)],
                       "criteria.s11_db.mode": "value", "criteria.s11_db.value": "-10",
                       "criteria.radiation_efficiency.mode": "value", "criteria.radiation_efficiency.value": "0.7",
                       "criteria.total_efficiency.mode": "missing",
                       "criteria.fractional_bandwidth.mode": "value", "criteria.fractional_bandwidth.value": "0.1"})
        result, _ = self.edit(values=values)
        dto = self.get(result["target_id"])
        fields = {row["key"]: row for row in dto["selection"]["fields"]}
        self.assertEqual(len(fields["sampling.explicit"]["value"]), 1001)
        self.assertIn("1-1001", fields["sampling.provenance"]["value"][0])
        self.assertEqual(dto["input_status"]["metrics"]["total_efficiency"], "missing_target")
        self.assertEqual(dto["input_status"]["evaluation_status"], "not_evaluated")
        self.assertEqual(set(dto["input_status"]["missing_conditions"]), {"port_id", "reference_impedance", "band.reference"})
        self.assertLess(len(json.dumps(dto, ensure_ascii=False).encode("utf-8")), target_editor.MAX_DTO_BYTES)

    def test_invalid_stale_readonly_and_noop_edits_leave_journal_unchanged(self):
        """! @brief 오류는 현재 개정뿐 아니라 영수증/명령/undo 전체를 원자적으로 보존한다."""
        created, _ = self.edit()
        identity = created["target_id"]
        cases = [({"band.start.value": "3000"}, "E_SCHEMA"), ({"band.start.value": "nan"}, "E_UNIT"),
                 ({"criteria.radiation_efficiency.mode": "value", "criteria.radiation_efficiency.value": "1.1"}, "E_SCHEMA"),
                 ({"band.start.status": "estimated"}, "E_SCHEMA"), ({"source_refs": ["출처 삭제"]}, "E_SCHEMA"),
                 ({"name": "사용자 대역"}, "E_CONFLICT"), ({"sampling.kind": "explicit", "sampling.explicit": ["2.5 GHz", "2.4 GHz"]}, "E_SCHEMA")]
        for values, code in cases:
            params = self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "operation": "set",
                                   "target_id": identity, "values": values, "reason": "실패 원자성 확인"})
            before = self.service.journal.read()
            response = self.wire("target.editor.apply", params)
            self.assertEqual(response["error"]["data"]["domain_code"], code, response)
            self.assertEqual(self.service.journal.read(), before)
        params["input"].update(expected_revision=str(uuid4()), values={"name": "stale"})
        before = self.service.journal.read()
        self.assertEqual(self.wire("target.editor.apply", params)["error"]["data"]["domain_code"], "E_CONFLICT")
        self.assertEqual(self.service.journal.read(), before)

    def test_same_key_changed_payload_and_missing_reason_are_rejected(self):
        """! @brief 같은 영수증 키의 다른 편집이나 변경 사유 누락을 새 명령으로 접수하지 않는다."""
        result, params = self.edit()
        before = self.service.journal.read()
        changed = deepcopy(params)
        changed["input"]["reason"] = "재사용한 키의 다른 값"
        response = self.wire("target.editor.apply", changed)
        self.assertEqual(response["error"]["data"]["domain_code"], "E_CONFLICT")
        self.assertEqual(self.service.journal.read(), before)
        changed = self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "operation": "remove",
                                "target_id": result["target_id"], "values": {}, "reason": " "})
        self.assertEqual(self.wire("target.editor.apply", changed)["error"]["data"]["domain_code"], "E_SCHEMA")
        self.assertEqual(self.service.journal.read(), before)

    def test_oversize_provenance_reports_error_without_truncating_original(self):
        """! @brief 표시 상한을 넘는 실제 출처는 임의 생략하지 않고 원본 그대로 보존한다."""
        value = target_input()
        value["source_refs"] = [f"{index}: " + "출처" * 400 for index in range(40)]
        identity = self.seed(value)
        before = self.service.journal.read()
        params = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project_id},
                  "input": {"expected_revision": self.revision, "target_id": identity}}
        response = self.wire("target.editor.get", params)
        self.assertEqual(response["error"]["data"]["domain_code"], "E_RESOURCE")
        self.assertEqual(self.service.journal.read(), before)
        self.assertEqual(self.document()["targets"][0]["source_refs"], value["source_refs"])


if __name__ == "__main__":
    unittest.main()
