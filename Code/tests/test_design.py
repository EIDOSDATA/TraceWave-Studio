"""! @brief 설계 의미 모델, 목적별 미정값과 역명령의 불변식을 검증한다."""

from copy import deepcopy
import json
import math
from pathlib import Path
import unittest
from uuid import UUID

from rfad.domain.design import (
    apply_design_command,
    preflight_design,
    resolve_scalar,
    validate_design,
)
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command, new_project, validate_project
from rfad.domain.units import Quantity


def identity(number: int) -> str:
    """! @brief 비교 가능한 검증 전용 UUID를 만든다."""
    return str(UUID(int=number))


def quantity(number: float, unit: str) -> dict:
    """! @brief 검증 입력의 단위를 명시하고 SI 수량으로 변환한다."""
    return Quantity.from_value(number, unit).to_dict()


def unknown(dimension: str, unit: str) -> dict:
    """! @brief 자료가 없는 값을 0과 구분하여 만든다."""
    return Quantity.missing(dimension, unit).to_dict()


def build_design(*, known_material: bool = False, with_port: bool = True) -> dict:
    """! @brief 통합 검증에서도 재사용할 수 있는 작은 설계 원본을 만든다.

    @details 실제 제작 기준과 무관한 검증 전용 한 층, 두 선 패턴이다.
    known_material의 수치는 테스트가 명시적으로 제공한 가상 입력이다.
    """
    document = new_project("설계 의미 모델 검증")
    board = {
        "id": identity(1),
        "frame_id": document["frames"]["board"]["id"],
        "outline": {"kind": "rectangle", "width": quantity(60, "mm"), "height": quantity(40, "mm")},
        "thickness_convention": "finished",
    }
    material = {
        "id": identity(2), "name": "명시적 시험 재료", "model": "isotropic_constant",
        "epsilon_r": quantity(1, "1") if known_material else unknown("dimensionless", "1"),
        "tan_delta": quantity(0, "1") if known_material else unknown("dimensionless", "1"),
        "conductivity": quantity(5.8e7, "S/m") if known_material else unknown("conductivity", "S/m"),
        "validity_hz": {
            "min": quantity(1, "GHz") if known_material else unknown("frequency", "Hz"),
            "max": quantity(6, "GHz") if known_material else unknown("frequency", "Hz"),
        },
        "source_refs": ["test-fixture"], "assumptions": ["실제 제작 물성이 아닌 검증 입력"],
    }
    layer = {
        "id": identity(3), "name": "상부 도체", "role": "conductor", "order": 0,
        "z_min": quantity(0, "mm"), "thickness": quantity(35, "um"), "material_id": material["id"],
    }
    apply_design_command(document, "board.set", {"board": board})
    apply_design_command(document, "material.set", {"material": material})
    apply_design_command(document, "layer.set", {"layer": layer})
    for number, name in ((4, "RF"), (5, "GND")):
        apply_design_command(document, "net.set", {"net": {"id": identity(number), "name": name}})
    for number, net, y, role in ((6, 4, 1, "radiator"), (7, 5, 3, "ground")):
        geometry = {
            "id": identity(number), "kind": "line_path", "role": role,
            "frame_id": board["frame_id"], "layer_id": layer["id"], "net_id": identity(net),
            "material_ref": None, "source_ref": None,
            "include_in_em": True, "include_in_export": True,
            "start": [quantity(1, "mm"), quantity(y, "mm")],
            "end": [quantity(10, "mm"), quantity(y, "mm")], "width": quantity(0.5, "mm"),
        }
        apply_design_command(document, "geometry.set", {"geometry": geometry})
    if with_port:
        port = {
            "id": identity(8), "name": "P1", "kind": "lumped",
            "positive_geometry_id": identity(6), "reference_geometry_id": identity(7),
            "resistance": quantity(50, "ohm"), "reference_plane": "기판 급전 갭",
            "polarity": 1, "direction": [0.0, 1.0, 0.0],
            "validity_hz": {"min": quantity(2.3, "GHz"), "max": quantity(2.6, "GHz")},
        }
        apply_design_command(document, "port.set", {"port": port})
    return document


class DesignTests(unittest.TestCase):
    """! @brief 저장 허용, 실행 차단과 데이터 무결성을 구분한다."""

    def setUp(self) -> None:
        """! @brief 다른 테스트와 공유되지 않는 설계 원본을 준비한다."""
        self.document = build_design()

    def assert_rejected(self, command_type: str, payload: dict, code: str) -> None:
        """! @brief 거부된 명령이 원본을 부분 변경하지 않는지 함께 확인한다."""
        before = deepcopy(self.document)
        with self.assertRaises(ProjectError) as context:
            apply_design_command(self.document, command_type, payload)
        self.assertEqual(context.exception.code, code)
        self.assertEqual(self.document, before)

    def test_unknown_material_is_saved_without_guessed_values(self) -> None:
        """! @brief 미정 물성에 임의 FR4 또는 0을 채우지 않는다."""
        before = deepcopy(self.document)
        validate_design(self.document)
        self.assertEqual(self.document, before)
        for field in ("epsilon_r", "tan_delta", "conductivity"):
            self.assertIsNone(self.document["materials"][0][field]["value_si"])
        self.assertEqual(preflight_design(self.document, "geometry"), [])
        self.assertEqual(preflight_design(self.document, "step"), [])
        diagnostics = preflight_design(self.document, "em")
        self.assertTrue(any(item["code"] == "E_MATERIAL_UNKNOWN" for item in diagnostics))
        self.assertTrue(any(item["code"] == "E_MATERIAL_RANGE" for item in diagnostics))

    def test_complete_input_does_not_claim_solver_or_connectivity_verification(self) -> None:
        """! @brief 입력이 완비되어도 미구현 해석 기능을 합격시키지 않는다."""
        document = build_design(known_material=True)
        diagnostics = preflight_design(document, "em")
        self.assertEqual([item["code"] for item in diagnostics], ["E_UNSUPPORTED"])
        self.assertEqual(diagnostics[0]["field_paths"], ["solver_adapter"])

    def test_material_range_does_not_cover_port_band(self) -> None:
        """! @brief 물성 대역 밖으로 외삽하는 입력은 EM 준비 단계에서 차단한다."""
        document = build_design(known_material=True)
        material = deepcopy(document["materials"][0])
        material["validity_hz"]["min"] = quantity(2.4, "GHz")
        apply_design_command(document, "material.set", {"material": material})
        diagnostics = preflight_design(document, "em")
        self.assertTrue(any(item["code"] == "E_MATERIAL_RANGE" for item in diagnostics))

    def test_referenced_objects_cannot_be_removed(self) -> None:
        """! @brief 참조 중인 재료, 층, net, 도체와 기판 제거를 거부한다."""
        for kind, number in (("material", 2), ("layer", 3), ("net", 4), ("geometry", 6)):
            with self.subTest(kind=kind):
                self.assert_rejected(kind + ".remove", {"id": identity(number)}, "E_SCHEMA")
        self.assert_rejected("board.set", {"board": None}, "E_SCHEMA")

    def test_layer_material_can_remain_explicitly_unknown(self) -> None:
        """! @brief 미지정 재료 참조는 저장 가능하나 EM 입력으로 소비하지 않는다."""
        layer = deepcopy(self.document["stackup"][0])
        layer["material_id"] = None
        apply_design_command(self.document, "layer.set", {"layer": layer})
        apply_design_command(self.document, "material.remove", {"id": identity(2)})
        self.assertEqual(preflight_design(self.document, "step"), [])
        diagnostics = preflight_design(self.document, "em")
        self.assertTrue(any(item["code"] == "E_MATERIAL_UNKNOWN" for item in diagnostics))

    def test_unknown_dimensions_are_saved_but_required_by_purpose(self) -> None:
        """! @brief 미정 형상 치수를 0으로 대신하지 않고 목적별로 차단한다."""
        geometry = deepcopy(self.document["geometry"][0])
        geometry["width"] = unknown("length", "mm")
        apply_design_command(self.document, "geometry.set", {"geometry": geometry})
        validate_design(self.document)
        diagnostics = preflight_design(self.document, "geometry")
        self.assertTrue(any("width" in item["field_paths"][0] for item in diagnostics))

    def test_wrong_dimension_zero_width_and_nonfinite_values_are_rejected(self) -> None:
        """! @brief 길이 필드에 주파수 또는 불가능한 수치를 넣지 못한다."""
        for width, code in ((quantity(2.4, "GHz"), "E_UNIT"), (quantity(0, "mm"), "E_SCHEMA")):
            geometry = deepcopy(self.document["geometry"][0])
            geometry["width"] = width
            self.assert_rejected("geometry.set", {"geometry": geometry}, code)
        for invalid in (math.nan, math.inf, True):
            geometry = deepcopy(self.document["geometry"][0])
            geometry["width"]["value_si"] = invalid
            self.assert_rejected("geometry.set", {"geometry": geometry}, "E_UNIT")

    def test_parameter_reference_is_resolved_and_dimension_checked(self) -> None:
        """! @brief 치수 참조는 최신 parameter SI 값과 차원을 사용한다."""
        parameter_id = identity(20)
        self.document["parameters"][parameter_id] = {
            "id": parameter_id, "name": "선폭", "quantity": quantity(0.8, "mm"),
        }
        geometry = deepcopy(self.document["geometry"][0])
        geometry["width"] = {"parameter_id": parameter_id}
        apply_design_command(self.document, "geometry.set", {"geometry": geometry})
        self.assertEqual(resolve_scalar(self.document, geometry["width"], "length").value_si, 0.0008)
        self.document["parameters"][parameter_id]["quantity"] = quantity(-1, "mm")
        with self.assertRaises(ProjectError):
            validate_design(self.document)
        self.document["parameters"][parameter_id]["quantity"] = quantity(1, "GHz")
        with self.assertRaises(ProjectError) as context:
            validate_design(self.document)
        self.assertEqual(context.exception.code, "E_UNIT")
        self.document["parameters"].clear()
        with self.assertRaises(ProjectError):
            validate_design(self.document)

    def test_uuid_collisions_and_unknown_references_are_rejected(self) -> None:
        """! @brief 객체 종류가 달라도 UUID는 충돌하지 않아야 한다."""
        for invalid_id in (identity(3), self.document["project_id"], "invalid"):
            self.assert_rejected("net.set", {"net": {"id": invalid_id, "name": "추가 net"}}, "E_SCHEMA" if invalid_id == "invalid" else "E_CONFLICT")
        geometry = deepcopy(self.document["geometry"][0])
        geometry["layer_id"] = identity(99)
        self.assert_rejected("geometry.set", {"geometry": geometry}, "E_SCHEMA")

    def test_inverse_restores_collection_order_and_values(self) -> None:
        """! @brief 추가, 수정, 제거의 역명령은 정규 배열 순서를 복구한다."""
        apply_design_command(self.document, "net.set", {"net": {"id": identity(10), "name": "추가 A"}})
        apply_design_command(self.document, "net.set", {"net": {"id": identity(9), "name": "추가 B"}})
        before = deepcopy(self.document)
        changed, invalidation, inverse = apply_design_command(self.document, "net.remove", {"id": identity(9)})
        self.assertEqual(changed, [identity(9)])
        self.assertIn("physics", invalidation)
        apply_design_command(self.document, inverse["type"], inverse["payload"])
        self.assertEqual(self.document, before)
        changed, _, inverse = apply_design_command(self.document, "net.set", {"net": {"id": identity(4), "name": "급전"}})
        apply_design_command(self.document, inverse["type"], inverse["payload"])
        self.assertEqual(self.document, before)
        _, _, inverse = apply_design_command(self.document, "net.set", {"net": {"id": identity(11), "name": "추가 C"}})
        apply_design_command(self.document, inverse["type"], inverse["payload"])
        self.assertEqual(self.document, before)

    def test_noncanonical_stored_collection_is_rejected(self) -> None:
        """! @brief 원본 해시를 달리하는 임의 collection 배열 순서를 거부한다."""
        self.document["nets"].reverse()
        with self.assertRaises(ProjectError) as context:
            validate_design(self.document)
        self.assertEqual(context.exception.code, "E_SCHEMA")

    def test_board_inverse_and_clear_without_dependents(self) -> None:
        """! @brief 빈 설계의 기판 설정과 해제는 역명령으로 복구된다."""
        document = new_project("빈 설계")
        board = deepcopy(self.document["board"])
        board["frame_id"] = document["frames"]["board"]["id"]
        before = deepcopy(document)
        _, _, inverse = apply_design_command(document, "board.set", {"board": board})
        apply_design_command(document, inverse["type"], inverse["payload"])
        self.assertEqual(document, before)

    def test_layers_cannot_overlap_or_redefine_z_max(self) -> None:
        """! @brief z_min과 두께만 authoritative이며 겹침과 중복 order를 거부한다."""
        layer = deepcopy(self.document["stackup"][0])
        layer.update({"id": identity(10), "name": "하부층", "order": 1})
        self.assert_rejected("layer.set", {"layer": layer}, "E_GEOMETRY")
        layer["z_min"] = quantity(35, "um")
        apply_design_command(self.document, "layer.set", {"layer": layer})
        layer["order"] = 0
        self.assert_rejected("layer.set", {"layer": layer}, "E_SCHEMA")
        layer["order"] = 1
        layer["z_max"] = quantity(70, "um")
        self.assert_rejected("layer.set", {"layer": layer}, "E_SCHEMA")

    def test_lines_reject_degenerate_points_and_nonconductive_layers(self) -> None:
        """! @brief 길이가 0인 선과 유전체에 속한 도체를 거부한다."""
        geometry = deepcopy(self.document["geometry"][0])
        geometry["end"] = deepcopy(geometry["start"])
        self.assert_rejected("geometry.set", {"geometry": geometry}, "E_GEOMETRY")
        layer = deepcopy(self.document["stackup"][0])
        layer["role"] = "dielectric"
        self.assert_rejected("layer.set", {"layer": layer}, "E_GEOMETRY")

    def test_arc_has_explicit_angle_units_and_valid_inner_radius(self) -> None:
        """! @brief 원호를 실제 치수와 각도로 저장하고 퇴화된 원호를 거부한다."""
        arc = deepcopy(self.document["geometry"][0])
        arc.pop("start")
        arc.pop("end")
        arc.update({"kind": "arc_path", "center": [quantity(10, "mm"), quantity(10, "mm")], "radius": quantity(5, "mm"), "start_angle": quantity(0, "deg"), "sweep_angle": quantity(180, "deg")})
        apply_design_command(self.document, "geometry.set", {"geometry": arc})
        self.assertEqual(preflight_design(self.document, "geometry"), [])
        for sweep in (0, 361):
            bad = deepcopy(arc)
            bad["sweep_angle"] = quantity(sweep, "deg")
            self.assert_rejected("geometry.set", {"geometry": bad}, "E_GEOMETRY")
        bad = deepcopy(arc)
        bad["width"] = quantity(10, "mm")
        self.assert_rejected("geometry.set", {"geometry": bad}, "E_GEOMETRY")

    def test_port_has_distinct_conductors_and_normalized_direction(self) -> None:
        """! @brief 급전의 두 도체, 방향과 극성을 묵시적으로 보정하지 않는다."""
        for direction in ([0, 0, 0], [0, 2, 0], [True, 0, 0], [math.inf, 0, 0], [10**400, 0, 0]):
            port = deepcopy(self.document["ports"][0])
            port["direction"] = direction
            self.assert_rejected("port.set", {"port": port}, "E_PORT")
        port = deepcopy(self.document["ports"][0])
        port["reference_geometry_id"] = port["positive_geometry_id"]
        self.assert_rejected("port.set", {"port": port}, "E_PORT")
        port = deepcopy(self.document["ports"][0])
        port["polarity"] = True
        self.assert_rejected("port.set", {"port": port}, "E_PORT")

    def test_second_port_and_em_excluded_port_conductor_are_not_supported(self) -> None:
        """! @brief 단일 포트 범위를 지키고 제외된 급전 도체를 진단한다."""
        port = deepcopy(self.document["ports"][0])
        port.update({"id": identity(10), "name": "P2"})
        self.assert_rejected("port.set", {"port": port}, "E_UNSUPPORTED")
        geometry = deepcopy(self.document["geometry"][0])
        geometry["include_in_em"] = False
        apply_design_command(self.document, "geometry.set", {"geometry": geometry})
        diagnostics = preflight_design(self.document, "em")
        self.assertTrue(any(item["code"] == "E_PORT" for item in diagnostics))

    def test_missing_net_and_port_are_explicit_em_diagnostics(self) -> None:
        """! @brief 의도된 net과 급전 미지정 상태는 저장과 실행에서 구분한다."""
        document = build_design(with_port=False)
        geometry = deepcopy(document["geometry"][0])
        geometry["net_id"] = None
        apply_design_command(document, "geometry.set", {"geometry": geometry})
        codes = {item["code"] for item in preflight_design(document, "em")}
        self.assertTrue({"E_PORT", "E_CONNECTIVITY"}.issubset(codes))

    def test_unsupported_geometry_and_material_do_not_silently_downgrade(self) -> None:
        """! @brief 미지원 primitive와 물성 모델을 유사 모델로 대신하지 않는다."""
        geometry = deepcopy(self.document["geometry"][0])
        geometry["kind"] = "via"
        self.assert_rejected("geometry.set", {"geometry": geometry}, "E_UNSUPPORTED")
        material = deepcopy(self.document["materials"][0])
        material["model"] = "anisotropic"
        self.assert_rejected("material.set", {"material": material}, "E_UNSUPPORTED")

    def test_integer_si_is_normalized_only_when_command_is_applied(self) -> None:
        """! @brief 명령의 정수 입력을 float64로 저장하되 재적재 시 수정하지 않는다."""
        material = deepcopy(self.document["materials"][0])
        material["epsilon_r"] = quantity(1, "1")
        material["epsilon_r"]["value_si"] = 2
        apply_design_command(self.document, "material.set", {"material": material})
        self.assertIs(type(self.document["materials"][0]["epsilon_r"]["value_si"]), float)
        self.document["materials"][0]["epsilon_r"]["value_si"] = 2
        with self.assertRaises(ProjectError):
            validate_design(self.document)

    def test_malformed_payload_and_cycle_are_rejected_without_mutation(self) -> None:
        """! @brief 미지원 명령과 과도한 중첩 및 순환 입력을 거부한다."""
        self.assert_rejected("net.set", {"net": {}, "extra": True}, "E_SCHEMA")
        self.assert_rejected("net.remove", {"id": identity(100)}, "E_SCHEMA")
        self.assert_rejected("design.execute", {}, "E_UNSUPPORTED")
        cyclic = {}
        cyclic["self"] = cyclic
        self.assert_rejected("net.set", {"net": cyclic}, "E_SCHEMA")
        nested = {}
        for _ in range(20):
            nested = {"nested": nested}
        self.assert_rejected("net.set", {"net": nested}, "E_RESOURCE")

    def test_initial_ifa_fixture_preserves_incomplete_approved_baseline(self) -> None:
        """! @brief 초기 보드 목표와 파생 적층을 저장하되 미정 물성과 형상을 채우지 않는다."""
        path = Path(__file__).resolve().parents[1] / "fixtures" / "design" / "initial_ifa.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        validate_project(document)
        validate_project(json.loads(json.dumps(document, allow_nan=False)))
        self.assertEqual(resolve_scalar(document, document["board"]["outline"]["width"], "length").value_si, 0.04)
        self.assertEqual(resolve_scalar(document, document["board"]["outline"]["height"], "length").value_si, 0.06)
        parameters = {item["name"]: item for item in document["parameters"].values()}
        self.assertEqual(parameters["nominal_dielectric_residual"]["quantity"]["value_si"], 0.00093)
        self.assertIn("expression", parameters["nominal_dielectric_residual"])
        self.assertEqual(document["geometry"], [])
        self.assertEqual(document["ports"], [])
        for material in document["materials"]:
            for field in ("epsilon_r", "tan_delta", "conductivity"):
                self.assertIsNone(material[field]["value_si"])
        codes = {item["code"] for item in preflight_design(document, "em")}
        self.assertTrue({"E_GEOMETRY", "E_PORT", "E_MATERIAL_UNKNOWN", "E_UNSUPPORTED"}.issubset(codes))
        copper = parameters["copper_thickness"]
        command = {"command_id": identity(9000), "type": "parameter.set", "payload": {"id": copper["id"], "name": copper["name"], "quantity": quantity(40, "um")}}
        updated, changed, _, _ = apply_command(document, command, document["revision_id"])
        self.assertIn(parameters["nominal_dielectric_residual"]["id"], changed)
        self.assertAlmostEqual(resolve_scalar(updated, updated["stackup"][1]["thickness"], "length").value_si, 0.00092)


if __name__ == "__main__":
    unittest.main()
