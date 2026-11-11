"""! @brief 표현식 그래프와 명령의 원자성 및 구형 문서 호환성을 확인한다."""

from copy import deepcopy
import unittest
from uuid import uuid4

from rfad.domain.errors import ProjectError
from rfad.domain.project import SCHEMA_VERSION, apply_command, new_project, validate_project
from rfad.domain.units import Quantity


def apply(document: dict, kind: str, payload: dict):
    """! @brief 현재 개정을 기준으로 독립 명령을 실행한다."""
    return apply_command(document, {"command_id": str(uuid4()), "type": kind, "payload": payload}, document["revision_id"])


def literal(identity: str, value: float, name: str = "폭") -> dict:
    """! @brief 출처가 있는 길이 매개변수를 생성한다."""
    return {"id": identity, "name": name, "quantity": Quantity.from_value(value, "mm", source_refs=("사용자",)).to_dict()}


def formula(identity: str, text: str, bindings: dict, name: str = "파생 길이") -> dict:
    """! @brief UUID 변수 결합을 명시하는 표현식 명령을 생성한다."""
    return {"id": identity, "name": name, "expression": text, "bindings": bindings, "dimension": "length", "display_unit": "mm"}


class ParameterGraphTests(unittest.TestCase):
    """! @brief 리터럴, 파생 값과 설계 참조를 같은 개정에서 검사한다."""

    def setUp(self):
        """! @brief 선행 매개변수와 두 단계 파생 그래프를 생성한다."""
        self.a, self.b, self.c = [str(uuid4()) for _ in range(3)]
        self.document = apply(new_project("표현식"), "parameter.set", literal(self.a, 40))[0]
        self.document = apply(self.document, "parameter.set_expression", formula(self.b, "w / 2", {"w": self.a}))[0]
        self.document = apply(self.document, "parameter.set_expression", formula(self.c, "half + 5 mm", {"half": self.b}, "안테나 길이"))[0]

    def test_dependency_change_recalculates_transitively_with_sources(self):
        updated, changed, _, _ = apply(self.document, "parameter.set", literal(self.a, 60))
        self.assertEqual(set(changed), {self.a, self.b, self.c})
        self.assertAlmostEqual(updated["parameters"][self.c]["quantity"]["value_si"], 0.035)
        self.assertEqual(updated["parameters"][self.c]["quantity"]["source_refs"], ["사용자"])
        self.assertAlmostEqual(self.document["parameters"][self.c]["quantity"]["value_si"], 0.025)

    def test_renaming_literal_keeps_uuid_binding_and_inverse_restores_expression(self):
        updated = apply(self.document, "parameter.set", literal(self.a, 40, "새 폭"))[0]
        self.assertEqual(updated["parameters"][self.b]["expression"]["bindings"], {"w": self.a})
        replaced, _, _, inverse = apply(updated, "parameter.set", literal(self.b, 11, "파생 길이"))
        restored = apply(replaced, inverse["type"], inverse["payload"])[0]
        self.assertEqual(restored["parameters"], updated["parameters"])

    def test_cycles_missing_references_bad_units_and_deleted_dependency_are_atomic(self):
        cases = [
            ("parameter.set_expression", formula(self.a, "tail", {"tail": self.c}, "폭"), "E_EXPR_CYCLE"),
            ("parameter.set_expression", formula(str(uuid4()), "lost", {"lost": str(uuid4())}, "누락"), "E_CONFLICT"),
            ("parameter.set_expression", formula(str(uuid4()), "2 GHz", {}, "단위"), "E_UNIT"),
            ("parameter.remove", {"id": self.a}, "E_CONFLICT"),
        ]
        before = deepcopy(self.document)
        for kind, payload, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(ProjectError) as caught:
                    apply(self.document, kind, payload)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(self.document, before)

    def test_stored_cache_dependencies_and_engine_version_are_verified(self):
        for field, value, code in (("quantity", {**self.document["parameters"][self.b]["quantity"], "value_si": 99.0}, "E_SCHEMA"), ("dependencies", [], "E_SCHEMA"), ("engine_version", "future", "E_VERSION")):
            document = deepcopy(self.document)
            target = document["parameters"][self.b]
            if field == "quantity":
                target[field] = value
            else:
                target["expression"][field] = value
            with self.assertRaises(ProjectError) as caught:
                validate_project(document)
            self.assertEqual(caught.exception.code, code)

    def test_old_schema_remains_unchanged_and_upgrades_on_copy(self):
        legacy = new_project("기존 파일")
        legacy["schema_version"] = "rfad.project/0.1"
        before = deepcopy(legacy)
        validate_project(legacy)
        updated = apply(legacy, "metadata.rename", {"name": "새 개정"})[0]
        self.assertEqual(legacy, before)
        self.assertEqual(updated["schema_version"], SCHEMA_VERSION)
        self.assertEqual(updated["parent_revision_ids"], [legacy["revision_id"]])

    def test_parameter_reference_controls_board_and_blocks_invalid_size(self):
        board = {"id": str(uuid4()), "frame_id": self.document["frames"]["board"]["id"], "outline": {"kind": "rectangle", "width": {"parameter_id": self.c}, "height": Quantity.from_value(60, "mm").to_dict()}, "thickness_convention": "finished"}
        document = apply(self.document, "board.set", {"board": board})[0]
        before = deepcopy(document)
        with self.assertRaises(ProjectError):
            apply(document, "parameter.set", literal(self.a, -40))
        self.assertEqual(document, before)
        with self.assertRaises(ProjectError):
            apply(document, "parameter.remove", {"id": self.c})

    def test_bindings_must_match_exactly_and_referenced_missing_quantity_fails(self):
        for bindings in ({}, {"w": self.a, "unused": self.b}, {"w": "invalid"}):
            with self.assertRaises(ProjectError):
                apply(self.document, "parameter.set_expression", formula(str(uuid4()), "w", bindings, "bad"))
        missing = literal(self.a, 0)
        missing["quantity"] = Quantity.missing("length", "mm").to_dict()
        with self.assertRaises(ProjectError):
            apply(self.document, "parameter.set", missing)

    def test_constant_expression_and_estimated_dependency(self):
        constant = apply(self.document, "parameter.set_expression", formula(str(uuid4()), "c0 / (4 * 2.45 GHz)", {}, "자유공간 길이"))[0]
        validate_project(constant)
        estimated = literal(self.a, 40)
        estimated["quantity"] = Quantity.from_value(40, "mm", status="estimated").to_dict()
        updated = apply(self.document, "parameter.set", estimated)[0]
        self.assertEqual(updated["parameters"][self.c]["quantity"]["status"], "estimated")


if __name__ == "__main__":
    unittest.main()
