"""! @brief 재료와 net 및 명시적 급전 위치의 편집 생성 경계를 검사한다."""

from copy import deepcopy
import unittest
from uuid import uuid4

import test_editor_service as fixtures
from test_design import build_design
from rfad.application.editor import edit_command, fields_for
from rfad.domain.design import apply_design_command
from rfad.domain.errors import ProjectError


class EditorCreateTests(unittest.TestCase):
    """! @brief 물성을 추정하지 않는 새 객체와 기존 포트의 호환성을 확인한다."""

    def test_new_material_and_net_persist_through_undo_redo(self):
        """! @brief 이름만 입력한 재료의 물성은 미정이며 생성 자체도 영속 명령이다."""
        fixture = fixtures.EditorServiceTests()
        fixture.setUp()
        try:
            material, net = str(uuid4()), str(uuid4())
            fixture.edit("new_material", material, {"name": "사용자가 입력할 재료"})
            stored = deepcopy(fixture.document()["materials"][0])
            for key in ("epsilon_r", "tan_delta", "conductivity"):
                self.assertEqual(stored[key]["status"], "missing")
                self.assertIsNone(stored[key]["value_si"])
            fixture.history("undo")
            self.assertEqual(fixture.document()["materials"], [])
            fixture.history("redo")
            self.assertEqual(fixture.document()["materials"], [stored])
            fixture.edit("new_net", net, {"name": "RF 입력"})
            self.assertEqual(fixture.document()["nets"], [{"id": net, "name": "RF 입력"}])
        finally:
            fixture.tearDown()

    def test_port_requires_explicit_conductor_choices_and_preserves_missing_properties(self):
        """! @brief 새 포트는 임의 도체나 저항 및 위치를 자동으로 확정하지 않는다."""
        document = build_design(with_port=False)
        selection = {"kind": "new_port", "id": str(uuid4())}
        fields = {f["key"]: f for f in fields_for(document, selection)}
        self.assertEqual(fields["positive_geometry_id"]["value"], "")
        self.assertEqual(fields["resistance.mode"]["value"], "missing")
        command = edit_command(document, selection, {"name": "P1", "positive_geometry_id": document["geometry"][0]["id"], "reference_geometry_id": document["geometry"][1]["id"]})
        apply_design_command(document, command["type"], command["payload"])
        self.assertIsNone(document["ports"][0]["excitation_box"]["start"][0]["value_si"])
        with self.assertRaises(ProjectError):
            fields_for(document, {"kind": "new_port", "id": str(uuid4())})

    def test_existing_port_keeps_absent_box_until_user_edits_it(self):
        """! @brief 구버전 포트 조회나 이름 편집은 새로운 급전 좌표를 삽입하지 않는다."""
        document = build_design()
        port = document["ports"][0]
        selection = {"kind": "port", "id": port["id"]}
        before = deepcopy(document)
        fields = {f["key"]: f for f in fields_for(document, selection)}
        self.assertEqual(fields["excitation_box.start.0.mode"]["value"], "missing")
        self.assertEqual(document, before)
        command = edit_command(document, selection, {"name": "이름만 변경"})
        self.assertNotIn("excitation_box", command["payload"]["port"])
        command = edit_command(document, selection, {"excitation_box.start.0.mode": "value", "excitation_box.start.0.value": "1"})
        self.assertEqual(command["payload"]["port"]["excitation_box"]["start"][0]["value_si"], 0.001)

    def test_creation_cannot_reuse_an_entity_id(self):
        """! @brief 생성 선택지는 기존 객체를 덮어쓰기 위한 우회 경로가 아니다."""
        document = build_design()
        for kind in ("new_material", "new_net", "new_port"):
            with self.subTest(kind=kind), self.assertRaises(ProjectError):
                fields_for(document, {"kind": kind, "id": document["board"]["id"]})


if __name__ == "__main__":
    unittest.main()
