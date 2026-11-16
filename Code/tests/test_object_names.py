"""! @brief 객체 이름의 읽기 호환, 검토 후보, 출처와 영속 이력 경계를 검증한다."""

from copy import deepcopy
from uuid import uuid4
import unittest

from rfad.application.canvas import build_canvas_dto
from rfad.application.canonical import canonical_bytes
from rfad.application.editor import build_dto, edit_command
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import PROFILE, allocate_name, display_names
from rfad.domain.project import SCHEMA_VERSION, apply_command, new_project, validate_project
from rfad.domain.template_geometry import generate_geometry
from rfad.domain.template_instance import EXTENSION_KEY, record_hash, validate_record
from rfad.domain.units import Quantity
import test_template_candidates as templates
import test_canvas_service as canvas_fixture
from test_design import build_design


def rename(document, kind, identity, name):
    """! @brief GUI와 같은 이름 변경 명령을 순수 도메인까지 적용한다."""
    command = edit_command(document, {"kind": kind, "id": identity}, {"name": name})
    return apply_command(document, {"command_id": str(uuid4()), **command}, document["revision_id"])


class ObjectNameDomainTests(unittest.TestCase):
    """! @brief 이름 표시가 물리 의미와 과거 원본을 변경하지 않는지 확인한다."""

    def test_legacy_read_has_stable_temporary_names_without_mutation(self):
        """! @brief 구버전의 무명 객체는 조회만으로 이름이나 개정을 얻지 않는다."""
        for version in ("0.2", "0.3", "0.4", "0.5"):
            document = build_design()
            document["schema_version"] = "rfad.project/" + version
            validate_project(document)
            original = canonical_bytes(document)
            first = display_names(document)
            reordered = deepcopy(document)
            reordered["geometry"].reverse()
            self.assertEqual(display_names(reordered), first)
            dto = build_dto(document, document["revision_id"], {}, None)
            scene = build_canvas_dto(document)
            for shape in scene["shapes"]:
                item = next(row for row in dto["items"] if row["id"] == shape["id"])
                self.assertEqual(shape["label"], item["label"])
                self.assertEqual(item["name_state"], "temporary")
                self.assertIsNone(item["name"])
                self.assertNotIn(item["id"][:8], item["label"])
            self.assertEqual(canonical_bytes(document), original)
        old = new_project("기존 파일")
        old["schema_version"] = "rfad.project/0.1"
        validate_project(old)

    def test_explicit_legacy_rename_migrates_only_current_object(self):
        """! @brief 이름을 명시 적용할 때만 새 버전을 쓰고 역명령은 무명 원본을 복원한다."""
        document = build_design()
        document["schema_version"] = "rfad.project/0.4"
        target = document["geometry"][0]
        before = canonical_bytes(document)
        changed, _, _, inverse = rename(document, "geometry", target["id"], "방사 도체")
        self.assertEqual(changed["schema_version"], SCHEMA_VERSION)
        self.assertEqual(canonical_bytes(document), before)
        edited = next(row for row in changed["geometry"] if row["id"] == target["id"])
        self.assertEqual({key: value for key, value in edited.items() if key != "name"}, target)
        for key in ("board", "parameters", "materials", "ports", "stackup", "nets", "extensions"):
            self.assertEqual(changed[key], document[key])
        restored = apply_command(changed, {"command_id": str(uuid4()), **inverse}, changed["revision_id"])[0]
        self.assertEqual(restored["geometry"], document["geometry"])
        board = rename(document, "board", document["board"]["id"], "시험 기판")[0]
        self.assertEqual(board["board"]["name"], "시험 기판")
        self.assertEqual({key: value for key, value in board["board"].items() if key != "name"}, document["board"])

    def test_duplicate_and_invalid_names_reject_without_normalization(self):
        """! @brief 모든 도체 층에 같은 이름 범위를 적용하고 새 입력 오류를 숨기지 않는다."""
        document = build_design()
        first, second = document["geometry"][:2]
        layer = deepcopy(document["stackup"][0])
        layer.update(id=str(uuid4()), name="다른 도체층", order=1,
                     z_min=Quantity.missing("length", "mm").to_dict(), thickness=Quantity.missing("length", "mm").to_dict())
        document["stackup"].append(layer)
        second["layer_id"] = layer["id"]
        validate_project(document)
        for value in ("", " ", " 앞공백", "뒷공백 ", "줄\n바꿈", "탭\t문자", "\0", "가" * 257):
            original = canonical_bytes(document)
            with self.subTest(name=value), self.assertRaises(ProjectError):
                rename(document, "geometry", first["id"], value)
            self.assertEqual(canonical_bytes(document), original)
        document = rename(document, "geometry", first["id"], "같은 이름")[0]
        with self.assertRaises(ProjectError) as caught:
            rename(document, "geometry", second["id"], "같은 이름")
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        renamed = rename(document, "geometry", second["id"], "../도체: 이름 / " + "가" * 240)[0]
        self.assertEqual(renamed["ports"], document["ports"])
        accepted = rename(document, "geometry", second["id"], "가" * 256)[0]
        self.assertEqual(next(row for row in accepted["geometry"] if row["id"] == second["id"])["name"], "가" * 256)
        material = document["materials"][0]
        renamed = rename(document, "material", material["id"], "같은 이름")[0]
        self.assertEqual(next(row for row in renamed["materials"] if row["id"] == material["id"])["name"], "같은 이름")

    def test_allocator_uses_current_maximum_and_preserves_user_names(self):
        """! @brief 이름 최대 번호/임시 이름/후보 예약을 피하고 삭제한 번호의 영구 보존을 주장하지 않는다."""
        document = build_design()
        first = document["geometry"][0]
        first.update(kind="line_path", role="conductor", name="선 99")
        document["geometry"] = [first]
        row = {"id": str(uuid4()), "kind": "line_path", "role": "conductor"}
        self.assertEqual(allocate_name(document, row), "선 100")
        self.assertEqual(allocate_name(document, row, reserved=["선 101"]), "선 102")
        document["geometry"] = [item for item in document["geometry"] if item["id"] != first["id"]]
        self.assertNotEqual(allocate_name(document, row), "선 100")
        names = display_names(document)
        self.assertNotIn(allocate_name(document, row), names.values())

    def test_named_template_preview_hash_binds_names_and_preserves_source(self):
        """! @brief 기존 이름을 피한 후보 이름을 검토 해시에 묶고 적용 시 다시 배정하지 않는다."""
        document = templates.base_document(missing=True)
        document["schema_version"] = "rfad.project/0.4"
        data = templates.specification(document)
        first, payload = templates.preview(document, data)
        repeated, duplicate = templates.preview(document, data)
        self.assertTrue(first["can_apply"], first)
        self.assertEqual(first["preview_hash"], repeated["preview_hash"])
        self.assertEqual(payload, duplicate)
        record = payload["replacement"]
        self.assertEqual(record["naming_profile"], PROFILE)
        self.assertEqual(record["source_document"], {**document, "extensions": {}})
        names = [row["name"] for row in record["objects"]["geometry"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(data["instance_id"][:8] not in row["name"] for row in record["objects"]["parameters"].values()))
        current = templates.apply_payload(document, payload)[0]
        self.assertEqual(current["geometry"], record["objects"]["geometry"])
        original_record = canonical_bytes(current["extensions"][EXTENSION_KEY])
        current = rename(current, "geometry", current["geometry"][0]["id"], "검토 이후 이름")[0]
        self.assertEqual(canonical_bytes(current["extensions"][EXTENSION_KEY]), original_record)
        self.assertEqual(current["materials"], document["materials"])
        derived = next(row for row in current["parameters"].values() if "expression" in row)
        renamed_parameter = rename(current, "parameter", derived["id"], "현재 연관 치수 이름")[0]
        self.assertEqual({**renamed_parameter["parameters"][derived["id"]], "name": derived["name"]}, derived)
        self.assertEqual(renamed_parameter["geometry"], current["geometry"])
        self.assertEqual(renamed_parameter["extensions"], current["extensions"])
        tampered = deepcopy(record)
        tampered["objects"]["geometry"][0]["name"] = "검토하지 않은 이름"
        tampered["record_hash"] = record_hash(tampered)
        with self.assertRaises(ProjectError):
            validate_record(tampered)

    def test_legacy_template_origin_still_replays_original_unnamed_objects(self):
        """! @brief 과거 생성 사본을 새 이름으로 소급 변경하거나 새 생성식으로 재해석하지 않는다."""
        document = templates.base_document(missing=True)
        document["schema_version"] = "rfad.project/0.4"
        data = templates.specification(document)
        _, payload = templates.preview(document, data)
        record = payload["replacement"]
        record.pop("naming_profile")
        record["objects"] = generate_geometry(document, record["id"], record["binding"], record["card"], record["inputs"])
        record["record_hash"] = record_hash(record)
        validate_record(record)
        current = templates.apply_payload(document, payload)[0]
        before = canonical_bytes(current["extensions"][EXTENSION_KEY])
        current = rename(current, "geometry", current["geometry"][0]["id"], "현재 사용자 이름")[0]
        self.assertEqual(canonical_bytes(current["extensions"][EXTENSION_KEY]), before)
        self.assertTrue(all("name" not in row for row in record["objects"]["geometry"]))


class ObjectNameServiceTests(templates.TemplateServiceCase):
    """! @brief 실제 서비스 저장/재시작과 snapshot을 이용해 이름의 원자성을 검증한다."""

    def test_template_rename_save_restart_reopen_undo_preserves_snapshot_and_unknowns(self):
        """! @brief 현재 이름만 바뀌며 문헌 사본/수량/표현식과 과거 snapshot은 불변이다."""
        data = templates.specification(self.document(), templates.IFA)
        preview = self.rpc("template.synthesize", self.request(data, mutation=False))
        result = self.rpc("template.apply", self.request({**data, "command_id": str(uuid4()), "preview_hash": preview["preview_hash"]}))
        self.revision = result["new_revision"]
        before = self.document()
        original = before["geometry"][0]
        snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})
        raw_snapshot = self.service.journal.read_artifact(snapshot["artifact"])
        request = self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
                                "selection": {"kind": "geometry", "id": original["id"]}, "values": {"name": "문헌 원호 사용자 이름"}})
        result = self.rpc("editor.apply", request)
        self.revision = result["new_revision"]
        self.assertEqual(self.rpc("editor.apply", request), result)
        changed = self.document()
        for key in ("board", "parameters", "materials", "ports", "stackup", "nets", "extensions"):
            self.assertEqual(changed[key], before[key])
        edited = next(row for row in changed["geometry"] if row["id"] == original["id"])
        self.assertEqual({**edited, "name": original["name"]}, original)
        self.complete("project.save", {"expected_revision": self.revision})
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.assertEqual(self.document(), changed)
        for method, expected in (("project.undo", before["geometry"]), ("project.redo", changed["geometry"])):
            result = self.rpc(method, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
            self.revision = result["new_revision"]
            self.assertEqual(self.document()["geometry"], expected)
        self.assertEqual(self.service.journal.read_artifact(snapshot["artifact"]), raw_snapshot)

    def test_named_candidate_stale_after_rename_and_invalid_name_leave_journal_unchanged(self):
        """! @brief 미리보기 이후 개정 변경을 우회해 이름을 몰래 바꾸거나 중복 생성하지 않는다."""
        data = templates.specification(self.document(), templates.IFA)
        preview = self.rpc("template.synthesize", self.request(data, mutation=False))
        self.command("metadata.rename", {"name": "다음 개정"})
        before = self.service.journal.read()
        with self.assertRaises(ProjectError):
            self.service.mutate("template.apply", self.request({**data, "command_id": str(uuid4()), "preview_hash": preview["preview_hash"]}))
        self.assertEqual(self.service.journal.read(), before)
        with self.assertRaises(ProjectError):
            self.service.mutate("editor.apply", self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
                "selection": {"kind": "board", "id": self.document()["board"]["id"]}, "values": {"name": "   "}}))
        self.assertEqual(self.service.journal.read()["projects"], before["projects"])


class ObjectNameCanvasTests(unittest.TestCase):
    """! @brief 생성/삭제와 원래 UUID를 복원하는 영속 명령의 자동 번호를 검증한다."""

    def test_create_delete_redo_keeps_assigned_names_and_unknown_physics(self):
        """! @brief 재생성과 redo의 이름/UUID를 구별하고 자동 명명에 물성 기본값을 넣지 않는다."""
        case = canvas_fixture.CanvasServiceTests()
        case.setUp()
        try:
            board, layer = case.board_layer()
            first, second = case.line(layer), case.line(layer)
            self.assertEqual(case.shape(first)["name"], "선 01")
            self.assertEqual(case.shape(second)["name"], "선 02")
            case.history("undo")
            case.history("redo")
            self.assertEqual(case.shape(second)["name"], "선 02")
            case.apply("remove", {"id": second})
            third = case.line(layer)
            self.assertNotEqual(third, second)
            self.assertEqual(case.shape(third)["name"], "선 02")
            self.assertEqual(case.document()["board"]["name"], "기판 01")
            self.assertIsNone(case.document()["stackup"][0]["thickness"]["value_si"])
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
