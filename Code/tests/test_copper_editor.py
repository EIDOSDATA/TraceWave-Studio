"""! @brief 큰 다각형 좌표 편집과 비아 패드 선택의 원본 보존을 검증한다."""

from copy import deepcopy
import math
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.editor import build_dto, edit_command, fields_for
from rfad.application.projects import MAX_DOCUMENT_BYTES
from rfad.domain.design import apply_design_command
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from test_cad_copper_features import copper_document
from test_pcb_solver import fixture_document, quantity


def polygon_document():
    """! @brief 전송 크기 경계를 검사하는 최대 64점의 사용자 다각형을 만든다."""
    document = fixture_document()
    shape = deepcopy(document["geometry"][0])
    for key in ("width", "start", "end"):
        shape.pop(key)
    shape.update(kind="planar_region", holes=[], outer=[
        [quantity(8 + 4 * math.cos(i * math.tau / 64), "mm"), quantity(6 + 4 * math.sin(i * math.tau / 64), "mm")]
        for i in range(64)])
    document["geometry"], document["ports"] = [shape], []
    validate_project(document)
    return document, shape


class CopperEditorTests(unittest.TestCase):
    """! @brief 숨은 물성/좌표 변환 없이 명시적으로 편집한 값만 바뀌는지 확인한다."""

    def test_maximum_polygon_fits_dto_and_preserves_unchanged_quantity(self):
        """! @brief 좌표 64점이 60 KiB 아래이며 부분 변경이 다른 점의 출처를 지우지 않는다."""
        document, shape = polygon_document()
        shape["outer"][0][0] = quantity(0.012, "m")
        selection = {"kind": "geometry", "id": shape["id"]}
        dto = build_dto(document, document["revision_id"], {}, selection)
        self.assertLess(len(canonical_bytes(dto)), 60 * 1024)
        coordinate = next(field for field in dto["selection"]["fields"] if field["key"] == "outer")
        self.assertEqual(coordinate["editor"], "coordinate_table")
        self.assertEqual(float(coordinate["value"][0][0]["value"]), 12)
        changed = deepcopy(coordinate["value"])
        changed[1][0].update(mode="missing", value="")
        before = deepcopy(shape)
        command = edit_command(document, selection, {"outer": changed})
        result = command["payload"]["geometry"]
        self.assertEqual(result["outer"][0], before["outer"][0])
        self.assertEqual(result["outer"][2:], before["outer"][2:])
        self.assertIsNone(result["outer"][1][0]["value_si"])
        self.assertEqual(shape, before)
        apply_design_command(document, command["type"], command["payload"])

    def test_coordinate_table_parameter_binding_is_explicit(self):
        """! @brief 좌표 표에서 매개변수 UUID를 선택하고 다른 점을 바꾸지 않는다."""
        document, shape = polygon_document()
        parameter_id = str(uuid4())
        document["parameters"][parameter_id] = {"id": parameter_id, "name": "첫 꼭짓점 X", "quantity": quantity(12, "mm")}
        selection = {"kind": "geometry", "id": shape["id"]}
        field = next(field for field in fields_for(document, selection) if field["key"] == "outer")
        values = deepcopy(field["value"])
        values[0][0].update(mode="parameter", parameter_id=parameter_id)
        command = edit_command(document, selection, {"outer": values})
        self.assertEqual(command["payload"]["geometry"]["outer"][0][0], {"parameter_id": parameter_id})
        apply_design_command(document, command["type"], command["payload"])
        validate_project(document)
        self.assertEqual(shape["outer"][0][0]["value_si"], 0.012)

    def test_many_holes_share_parameter_choices_within_storage_and_dto_limits(self):
        """! @brief 저장 가능한 64점/8 holes/40 변수의 선택지를 복제해 전송 상한을 넘지 않는다."""
        document = copper_document()
        pad = next(item for item in document["geometry"] if item["kind"] == "pad")
        shape = {key: value for key, value in pad.items() if key not in ("pad_shape", "center", "size", "rotation")}
        loops = [[[1, 1], [30, 1], [30, 30], [1, 30]],
                 [[5 + math.cos(i * math.tau / 32), 5 + math.sin(i * math.tau / 32)] for i in range(32)]]
        for x, y in ((10, 5), (15, 5), (20, 5), (5, 10), (10, 10), (15, 10), (20, 10)):
            loops.append([[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1]])
        quantities = [[[Quantity.from_value(v, "mm").to_dict() for v in point] for point in loop] for loop in loops]
        shape.update(kind="planar_region", outer=quantities[0], holes=quantities[1:])
        document["geometry"] = [shape]
        for index in range(40):
            identity = str(uuid4())
            document["parameters"][identity] = {"id": identity, "name": f"p{index}_" + "x" * 55,
                                                 "quantity": Quantity.from_value(1, "mm").to_dict()}
        validate_project(document)
        self.assertEqual(sum(len(loop) for loop in loops), 64)
        self.assertLess(len(canonical_bytes(document)), MAX_DOCUMENT_BYTES)
        before = deepcopy(document)
        dto = build_dto(document, document["revision_id"], {}, {"kind": "geometry", "id": shape["id"]})
        self.assertLess(len(canonical_bytes(dto)), 60 * 1024)
        self.assertEqual({item["value"] for item in dto["coordinate_choices"]}, set(document["parameters"]))
        tables = [field for field in dto["selection"]["fields"] if field["editor"] == "coordinate_table"]
        self.assertEqual(len(tables), 9)
        self.assertTrue(all(not field.get("choices") for field in tables))
        self.assertEqual(document, before)

    def test_mm_overflow_remains_editable_with_readonly_si_fallback(self):
        """! @brief mm 환산이 넘치는 저장 좌표도 SI 값으로 고칠 수 있고 미정/나머지 원본은 보존한다."""
        document, shape = polygon_document()
        shape["outer"][0][0] = Quantity.from_value(1e308, "m", source_refs=["explicit-extreme-input"]).to_dict()
        shape["outer"][1][0] = Quantity.missing("length", "mm").to_dict()
        validate_project(document)
        self.assertLess(len(canonical_bytes(document)), MAX_DOCUMENT_BYTES)
        before = deepcopy(shape)
        selection = {"kind": "geometry", "id": shape["id"]}
        dto = build_dto(document, document["revision_id"], {}, selection)
        table = next(field["value"] for field in dto["selection"]["fields"] if field["key"] == "outer")
        self.assertEqual(table[0][0]["unit"], "m")
        self.assertEqual(float(table[0][0]["value"]), 1e308)
        self.assertEqual(table[1][0]["mode"], "missing")
        changed = deepcopy(table)
        changed[0][0]["value"] = "0.012"
        command = edit_command(document, selection, {"outer": changed})
        revised = command["payload"]["geometry"]
        self.assertEqual(revised["outer"][0][0]["value_si"], 0.012)
        self.assertEqual(revised["outer"][0][0]["source_refs"], ["explicit-extreme-input"])
        self.assertEqual(revised["outer"][1:], before["outer"][1:])
        self.assertEqual(shape, before)
        apply_design_command(document, command["type"], command["payload"])
        validate_project(document)

    def test_coordinate_table_cannot_change_declared_cell_unit(self):
        """! @brief 읽기 전용 셀 단위를 바꿔 같은 숫자를 다른 물리 좌표로 해석할 수 없다."""
        document, shape = polygon_document()
        selection = {"kind": "geometry", "id": shape["id"]}
        table = next(field["value"] for field in fields_for(document, selection) if field["key"] == "outer")
        before = deepcopy(document)
        table[0][0]["unit"] = "m"
        with self.assertRaises(ProjectError) as caught:
            edit_command(document, selection, {"outer": table})
        self.assertTrue(caught.exception.details["field_path"].endswith(".unit"))
        self.assertEqual(document, before)

    def test_malformed_coordinate_table_cannot_change_topology_or_inject_fields(self):
        """! @brief 행 수 변경/비유한 수치/추가 키를 명령으로 게시하지 않는다."""
        document, shape = polygon_document()
        selection = {"kind": "geometry", "id": shape["id"]}
        values = next(field["value"] for field in fields_for(document, selection) if field["key"] == "outer")
        for mode in ("count", "nan", "unknown"):
            changed = deepcopy(values)
            if mode == "count":
                changed.pop()
            elif mode == "nan":
                changed[0][0]["value"] = "nan"
            else:
                changed[0][0]["execute"] = "command"
            with self.subTest(mode=mode), self.assertRaises(ProjectError):
                edit_command(document, selection, {"outer": changed})

    def test_via_pad_multiselect_rejects_duplicates_and_nonpads(self):
        """! @brief 명시한 패드 참조만 허용하고 선택 변경도 기존 도메인 명령을 따른다."""
        document = copper_document()
        via = next(shape for shape in document["geometry"] if shape["kind"] == "via")
        selection = {"kind": "geometry", "id": via["id"]}
        field = next(field for field in fields_for(document, selection) if field["key"] == "pad_ids")
        self.assertEqual(field["editor"], "multichoice")
        self.assertEqual({item["value"] for item in field["choices"]}, set(via["pad_ids"]))
        for invalid in ([via["id"]], [via["pad_ids"][0]] * 2, "not-a-list"):
            with self.subTest(value=invalid), self.assertRaises(ProjectError):
                edit_command(document, selection, {"pad_ids": invalid})
        command = edit_command(document, selection, {"pad_ids": []})
        self.assertEqual(command["payload"]["geometry"]["pad_ids"], [])
        self.assertEqual(len(via["pad_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
