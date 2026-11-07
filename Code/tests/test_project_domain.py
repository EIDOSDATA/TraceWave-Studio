"""! @brief 프로젝트 개정, 명령 실패 보존과 명시적 입력 계약을 검증한다."""

from copy import deepcopy
import json
import math
import unittest
from uuid import UUID, uuid4

from rfad.domain.errors import ProjectError
from rfad.domain.project import MAX_PARAMETERS, SCHEMA_VERSION, apply_command, new_project, validate_project
from rfad.domain.units import Dimension, Quantity


def command(command_type: str, payload: dict) -> dict:
    """! @brief 고유 명령 ID를 가진 시험 명령을 생성한다."""
    return {"command_id": str(uuid4()), "type": command_type, "payload": payload}


def parameter(name: str = "보드 폭", value: float = 40.0) -> dict:
    """! @brief 명시적 길이 값을 가진 매개변수 fixture를 만든다."""
    return {"id": str(uuid4()), "name": name, "quantity": Quantity.from_value(value, "mm").to_dict()}


class ProjectDomainTests(unittest.TestCase):
    """! @brief 저장 계층과 무관한 순수 프로젝트 변경 규칙을 검증한다."""

    def test_new_project_has_distinct_ids_identity_frames_and_no_physics_defaults(self):
        """! @brief 신규 원본은 좌표와 빈 컬렉션만 가지며 물성을 만들지 않는다."""
        document = new_project("초기 IFA")
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        identifiers = [document["project_id"], document["revision_id"], document["frames"]["world"]["id"], document["frames"]["board"]["id"]]
        self.assertEqual(len(set(identifiers)), 4)
        for value in identifiers:
            self.assertEqual(str(UUID(value)), value)
        self.assertEqual(document["frames"]["world"]["handedness"], "right")
        self.assertEqual(document["frames"]["board"]["parent_frame_id"], document["frames"]["world"]["id"])
        self.assertEqual(document["parameters"], {})
        self.assertIsNone(document["board"])
        self.assertEqual(document["materials"], [])
        self.assertEqual(document["ports"], [])
        validate_project(json.loads(json.dumps(document, ensure_ascii=False)))

    def test_explicit_ids_and_noop_command_create_a_new_revision(self):
        """! @brief 같은 이름 명령도 새 개정을 만들고 사용자 제공 프로젝트 ID를 유지한다."""
        project_id, revision_id = str(uuid4()), str(uuid4())
        document = new_project("이름", project_id, revision_id)
        updated, changed, invalidation, inverse = apply_command(document, command("metadata.rename", {"name": "이름"}), revision_id)
        self.assertEqual(updated["project_id"], project_id)
        self.assertNotEqual(updated["revision_id"], revision_id)
        self.assertEqual(updated["parent_revision_ids"], [revision_id])
        self.assertEqual(changed, [project_id])
        self.assertEqual(invalidation, ["revision", "exports.metadata"])
        self.assertEqual(inverse, {"type": "metadata.rename", "payload": {"name": "이름"}})

    def test_metadata_command_preserves_original_and_frame_ids(self):
        """! @brief 이름과 설명 변경은 원본과 안정된 좌표계 ID를 바꾸지 않는다."""
        original = new_project("원본")
        before = deepcopy(original)
        renamed, _, _, _ = apply_command(original, command("metadata.rename", {"name": "새 이름"}), original["revision_id"])
        updated, _, _, inverse = apply_command(renamed, command("metadata.describe", {"description": "첫 줄\n둘째 줄"}), renamed["revision_id"])
        self.assertEqual(original, before)
        self.assertEqual(updated["frames"], before["frames"])
        self.assertEqual(updated["metadata"]["created_at"], before["metadata"]["created_at"])
        self.assertEqual(updated["metadata"]["description"], "첫 줄\n둘째 줄")
        self.assertEqual(inverse, {"type": "metadata.describe", "payload": {"description": ""}})

    def test_stale_revision_is_rejected_without_any_change(self):
        """! @brief 이전 개정에서 보낸 변경은 현재 원본에 덮어쓰지 않는다."""
        original = new_project("원본")
        updated, _, _, _ = apply_command(original, command("metadata.rename", {"name": "수정"}), original["revision_id"])
        before = deepcopy(updated)
        with self.assertRaises(ProjectError) as caught:
            apply_command(updated, command("metadata.rename", {"name": "stale"}), original["revision_id"])
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(updated, before)

    def test_parameter_set_does_not_convert_si_twice_and_preserves_source(self):
        """! @brief mm 표시값의 저장 SI를 재변환하지 않고 입력 출처를 보존한다."""
        original = new_project("원본")
        payload = parameter()
        payload["quantity"]["status"] = "estimated"
        payload["quantity"]["source_refs"] = ["source-21-initial"]
        updated, changed, invalidation, inverse = apply_command(original, command("parameter.set", payload), original["revision_id"])
        stored = updated["parameters"][payload["id"]]["quantity"]
        self.assertEqual(stored["value_si"], 0.04)
        self.assertEqual(stored["display_unit"], "mm")
        self.assertEqual(stored["source_refs"], ["source-21-initial"])
        self.assertEqual(stored["status"], "estimated")
        self.assertEqual(changed, [payload["id"]])
        self.assertIn("physics", invalidation)
        self.assertEqual(inverse, {"type": "parameter.remove", "payload": {"id": payload["id"]}})
        payload["quantity"]["source_refs"].append("external-mutation")
        self.assertEqual(stored["source_refs"], ["source-21-initial"])
        self.assertEqual(original["parameters"], {})

    def test_missing_and_explicit_zero_can_be_saved_as_distinct_inputs(self):
        """! @brief 미정 유전율과 명시적 0을 서로 다른 상태로 저장한다."""
        document = new_project("물성 입력")
        missing = {"id": str(uuid4()), "name": "epsilon_r", "quantity": Quantity.missing(Dimension.DIMENSIONLESS, "1").to_dict()}
        zero = {"id": str(uuid4()), "name": "loss", "quantity": Quantity.from_value(0, "1").to_dict()}
        document, _, _, _ = apply_command(document, command("parameter.set", missing), document["revision_id"])
        document, _, _, _ = apply_command(document, command("parameter.set", zero), document["revision_id"])
        self.assertIsNone(document["parameters"][missing["id"]]["quantity"]["value_si"])
        self.assertEqual(document["parameters"][zero["id"]]["quantity"]["value_si"], 0.0)
        self.assertEqual(document["materials"], [])

    def test_parameter_replace_and_remove_inverse_restore_previous_value(self):
        """! @brief 역명령이 이전 수량과 출처를 복원하고 과거 원본은 유지한다."""
        original = new_project("원본")
        first = parameter()
        added, _, _, _ = apply_command(original, command("parameter.set", first), original["revision_id"])
        replacement = deepcopy(first)
        replacement["quantity"] = Quantity.from_value(55, "mm").to_dict()
        replaced, _, _, inverse = apply_command(added, command("parameter.set", replacement), added["revision_id"])
        self.assertEqual(inverse, {"type": "parameter.set", "payload": first})
        restored, _, _, _ = apply_command(replaced, command(inverse["type"], inverse["payload"]), replaced["revision_id"])
        self.assertEqual(restored["parameters"], added["parameters"])
        removed, _, _, inverse = apply_command(restored, command("parameter.remove", {"id": first["id"]}), restored["revision_id"])
        self.assertEqual(removed["parameters"], {})
        self.assertEqual(inverse["payload"], first)
        self.assertEqual(added["parameters"][first["id"]]["quantity"]["value_si"], 0.04)

    def test_invalid_parameter_values_do_not_modify_original(self):
        """! @brief 비유한 숫자, 불리언, 차원 오류와 표현식 주입을 차단한다."""
        original = new_project("원본")
        before = deepcopy(original)
        quantities = []
        for value in (True, "0.04", math.nan, math.inf):
            quantity = Quantity.from_value(40, "mm").to_dict()
            quantity["value_si"] = value
            quantities.append(quantity)
        mismatch = Quantity.from_value(40, "mm").to_dict()
        mismatch["dimension"] = "frequency"
        quantities.append(mismatch)
        expression = Quantity.from_value(40, "mm").to_dict()
        expression["expression"] = "import os"
        quantities.append(expression)
        for quantity in quantities:
            with self.subTest(quantity=quantity), self.assertRaises(ProjectError):
                apply_command(original, command("parameter.set", {"id": str(uuid4()), "name": "width", "quantity": quantity}), original["revision_id"])
            self.assertEqual(original, before)

    def test_duplicate_parameter_name_is_rejected(self):
        """! @brief 다른 ID에 같은 변수 이름을 덮어쓰지 않는다."""
        document = new_project("원본")
        document, _, _, _ = apply_command(document, command("parameter.set", parameter()), document["revision_id"])
        before = deepcopy(document)
        with self.assertRaises(ProjectError) as caught:
            apply_command(document, command("parameter.set", parameter()), document["revision_id"])
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(document, before)

    def test_parameter_limit_allows_replacement_but_not_new_item(self):
        """! @brief 128개 경계에서 기존 항목 수정과 새 항목 추가를 구분한다."""
        document = new_project("원본")
        for index in range(MAX_PARAMETERS):
            item = parameter(f"p{index}")
            document["parameters"][item["id"]] = item
        validate_project(document)
        last = deepcopy(item)
        last["quantity"] = Quantity.from_value(45, "mm").to_dict()
        replaced, _, _, _ = apply_command(document, command("parameter.set", last), document["revision_id"])
        self.assertEqual(len(replaced["parameters"]), MAX_PARAMETERS)
        with self.assertRaises(ProjectError) as caught:
            apply_command(document, command("parameter.set", parameter("overflow")), document["revision_id"])
        self.assertEqual(caught.exception.code, "E_RESOURCE")

    def test_unsupported_schema_unknown_fields_and_geometry_are_rejected(self):
        """! @brief 미래 schema나 미구현 물리 원본을 현재 계약으로 쓰지 않는다."""
        original = new_project("원본")
        cases = (("schema_version", "rfad.project/9", "E_VERSION"), ("unexpected", True, "E_SCHEMA"), ("geometry", [{"kind": "arc"}], "E_SCHEMA"), ("board", {}, "E_SCHEMA"))
        for field, value, error_code in cases:
            modified = deepcopy(original)
            modified[field] = value
            with self.subTest(field=field), self.assertRaises(ProjectError) as caught:
                validate_project(modified)
            self.assertEqual(caught.exception.code, error_code)

    def test_required_fields_and_parameter_identity_are_validated(self):
        """! @brief 필수 필드와 map key/ID의 일치를 검사한다."""
        document = new_project("원본")
        del document["metadata"]["description"]
        with self.assertRaises(ProjectError):
            validate_project(document)
        document = new_project("원본")
        item = parameter()
        document["parameters"][str(uuid4())] = item
        with self.assertRaises(ProjectError):
            validate_project(document)

    def test_invalid_uuid_and_command_shapes_are_rejected(self):
        """! @brief 임의 문자열, 대문자 UUID와 누락된 명령 ID를 거부한다."""
        document = new_project("원본")
        for revision in (True, "revision-1", str(uuid4()).upper()):
            with self.subTest(revision=revision), self.assertRaises(ProjectError):
                apply_command(document, command("metadata.rename", {"name": "수정"}), revision)
        invalid = command("metadata.rename", {"name": "수정"})
        del invalid["command_id"]
        with self.assertRaises(ProjectError):
            apply_command(document, invalid, document["revision_id"])
        with self.assertRaises(ProjectError):
            new_project("원본", project_id="project-1")

    def test_identifier_collision_is_rejected(self):
        """! @brief 프로젝트, 개정과 좌표계의 ID를 매개변수에 재사용하지 않는다."""
        document = new_project("원본")
        for identifier in (document["project_id"], document["revision_id"], document["frames"]["world"]["id"]):
            item = parameter()
            item["id"] = identifier
            with self.subTest(identifier=identifier), self.assertRaises(ProjectError):
                apply_command(document, command("parameter.set", item), document["revision_id"])

    def test_unknown_command_and_missing_remove_are_rejected(self):
        """! @brief 범용 field 쓰기나 존재하지 않는 항목 제거를 성공 처리하지 않는다."""
        document = new_project("원본")
        with self.assertRaises(ProjectError) as caught:
            apply_command(document, command("project.set_field", {"path": "materials", "value": []}), document["revision_id"])
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
        with self.assertRaises(ProjectError):
            apply_command(document, command("parameter.remove", {"id": str(uuid4())}), document["revision_id"])

    def test_name_description_and_unicode_limits(self):
        """! @brief 이름 문자 수와 설명 UTF-8 byte 상한을 각각 확인한다."""
        validate_project(new_project("가" * 256))
        for name in ("", "  ", "a" * 257, "\ud800", "abc\x00def"):
            with self.subTest(name=repr(name)), self.assertRaises(ProjectError):
                new_project(name)
        document = new_project("원본")
        valid, _, _, _ = apply_command(document, command("metadata.describe", {"description": "a" * 4096}), document["revision_id"])
        validate_project(valid)
        with self.assertRaises(ProjectError):
            apply_command(document, command("metadata.describe", {"description": "가" * 1366}), document["revision_id"])

    def test_frames_and_timestamps_reject_corruption(self):
        """! @brief 좌표 규약과 UTC 시각 손상을 조용히 수용하지 않는다."""
        original = new_project("원본")
        for mutate in (
            lambda d: d["frames"]["world"].update(handedness="left"),
            lambda d: d["frames"]["board"].update(parent_frame_id=None),
            lambda d: d["frames"]["board"].update(translation_si=[True, 0.0, 0.0]),
            lambda d: d["metadata"].update(created_at="2026-11-07T00:00:00"),
            lambda d: d["metadata"].update(modified_at="2000-01-01T00:00:00+00:00"),
        ):
            corrupted = deepcopy(original)
            mutate(corrupted)
            with self.assertRaises(ProjectError):
                validate_project(corrupted)

    def test_unknown_extensions_are_preserved_without_execution(self):
        """! @brief 미지 extension의 JSON 원문은 유지하고 핵심 필드를 덮어쓰지 않는다."""
        document = new_project("원본")
        document["extensions"] = {"future.adapter": {"script": "raise Exception('never execute')", "items": [True, None, 0.1]}}
        before = deepcopy(document)
        updated, _, _, _ = apply_command(document, command("metadata.rename", {"name": "수정"}), document["revision_id"])
        self.assertEqual(updated["extensions"], before["extensions"])
        self.assertEqual(document, before)

    def test_invalid_extension_json_and_cycles_are_rejected(self):
        """! @brief extension 안의 비유한 값과 순환 구조를 거부한다."""
        for value in (math.inf, 2**53, b"bytes", "\ud800"):
            document = new_project("원본")
            document["extensions"] = {"future.adapter": value}
            with self.subTest(value=repr(value)), self.assertRaises(ProjectError):
                validate_project(document)
        document = new_project("원본")
        document["extensions"]["self"] = document["extensions"]
        with self.assertRaises(ProjectError):
            validate_project(document)


if __name__ == "__main__":
    unittest.main()
