"""! @brief CAD 입력의 불변 스냅샷, 단위 변환과 미정 상태 경계를 검증한다."""

from copy import deepcopy
import math
import unittest
from uuid import uuid4

from rfad.application.cad import (
    MAX_SHAPES,
    MIN_FEATURE_MM,
    PROFILE,
    build_cad_input,
    profile_definition,
)
from rfad.application.canonical import CANONICAL_VERSION, canonical_hash
from rfad.domain.design import apply_design_command
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command
from test_design import build_design, identity, quantity, unknown


def cad_fixture() -> dict:
    """! @brief 실제 보드 기준과 구분한 유전체/양수 동박 두께의 시험 모델을 만든다."""
    document = build_design(with_port=True)
    document["stackup"][0]["order"] = 1
    dielectric = {
        "id": identity(20), "name": "검증용 유전체", "role": "dielectric", "order": 0,
        "z_min": quantity(-1.0, "mm"), "thickness": quantity(1.0, "mm"),
        "material_id": identity(2),
    }
    apply_design_command(document, "layer.set", {"layer": dielectric})
    return document


def snapshot_for(document: dict) -> dict:
    """! @brief 저장소 파일 IO를 제외한 스냅샷 내용 결합 시험용 참조를 만든다."""
    return {
        "snapshot_id": str(uuid4()), "project_id": document["project_id"],
        "revision_id": document["revision_id"], "schema_version": document["schema_version"],
        "canonical_version": CANONICAL_VERSION, "content_hash": canonical_hash(document),
        "sealed_at": 1794270000.0, "description": "CAD 기계 형상 시험 입력",
        "validation_state": "not_evaluated",
        "artifact": {"uri": "projects/test/snapshot/project.json", "sha256": "0" * 64, "bytes": 1},
    }


class CadProjectionTests(unittest.TestCase):
    """! @brief native import 없이 CAD 실행 전 의미 검증을 수행한다."""

    def setUp(self):
        """! @brief 시험마다 고유 프로젝트와 스냅샷 참조를 만든다."""
        self.document = cad_fixture()
        self.snapshot = snapshot_for(self.document)

    def assert_blocked(self, document: dict, code: str, field: str, *, snapshot: dict | None = None):
        """! @brief 실패의 원본/스냅샷 불변성과 사용자 수정 위치를 함께 확인한다."""
        before = deepcopy(document)
        reference = snapshot_for(document) if snapshot is None else snapshot
        original_reference = deepcopy(reference)
        with self.assertRaises(ProjectError) as raised:
            build_cad_input(document, reference)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.details["field_path"], field)
        self.assertEqual(document, before)
        self.assertEqual(reference, original_reference)

    def test_mm_conversion_and_original_semantics_remain_separate(self):
        """! @brief SI를 한 번만 mm로 바꾸고 물성/포트 원본을 출력 의미에 보존한다."""
        before = deepcopy(self.document)
        result = build_cad_input(self.document, self.snapshot)
        self.assertEqual(result["board"]["width_mm"], 60.0)
        self.assertEqual(result["board"]["height_mm"], 40.0)
        self.assertEqual(result["layers"][0]["z_min_mm"], -1.0)
        self.assertEqual(result["layers"][0]["thickness_mm"], 1.0)
        self.assertAlmostEqual(result["layers"][1]["thickness_mm"], 0.035)
        self.assertEqual(result["shapes"][0]["start_mm"], [1.0, 1.0])
        self.assertEqual(result["source_semantics"], self.document)
        self.assertEqual(result["source_hash"], self.snapshot["content_hash"])
        self.assertEqual(result["transform"]["scale_to_kernel"], 1000.0)
        self.assertEqual(self.document, before)
        result["source_semantics"]["materials"][0]["name"] = "출력 사본"
        result["snapshot"]["description"] = "출력 사본"
        self.assertEqual(self.document, before)
        self.assertEqual(self.snapshot["description"], "CAD 기계 형상 시험 입력")

    def test_material_unknowns_are_preserved_without_fr4_assumptions(self):
        """! @brief 기계 형상에 불필요한 RF 물성의 미정값을 임의로 채우지 않는다."""
        for layer in self.document["stackup"]:
            layer["material_id"] = None
        result = build_cad_input(self.document, snapshot_for(self.document))
        material = result["source_semantics"]["materials"][0]
        self.assertIsNone(material["epsilon_r"]["value_si"])
        self.assertEqual(material["epsilon_r"]["status"], "missing")
        self.assertTrue(all(layer["material_id"] is None for layer in result["layers"]))
        self.assertEqual(material["source_refs"], ["test-fixture"])
        self.assertEqual(result["source_semantics"]["ports"], self.document["ports"])

    def test_profile_and_snapshot_identity_or_hash_cannot_be_substituted(self):
        """! @brief 다른 개정/내용 및 미지원 STEP profile의 묵시적 대체를 차단한다."""
        with self.assertRaises(ProjectError) as raised:
            build_cad_input(self.document, self.snapshot, "AP214")
        self.assertEqual(raised.exception.code, "E_UNSUPPORTED")
        for key, replacement, code in (
            ("project_id", str(uuid4()), "E_CONFLICT"),
            ("revision_id", str(uuid4()), "E_CONFLICT"),
            ("schema_version", "rfad.project/9.0", "E_CONFLICT"),
            ("content_hash", "f" * 64, "E_HASH"),
            ("canonical_version", "rfad.canonical/9.0", "E_VERSION"),
            ("snapshot_id", self.document["revision_id"], "E_SCHEMA"),
        ):
            with self.subTest(key=key):
                changed = deepcopy(self.snapshot)
                changed[key] = replacement
                self.assert_blocked(self.document, code, "snapshot." + key, snapshot=changed)

    def test_mutated_content_is_rejected_without_changing_frozen_reference(self):
        """! @brief 스냅샷 생성 뒤 수정한 현재 설계를 과거 입력으로 소비하지 않는다."""
        self.document["metadata"]["description"] = "편집 중인 별도 원본"
        self.assert_blocked(self.document, "E_HASH", "snapshot.content_hash", snapshot=self.snapshot)

    def test_required_layer_dimensions_and_dielectric_are_not_inferred(self):
        """! @brief 도체 두께나 코어 두께를 보드 명목값에서 자동 역산하지 않는다."""
        for key in ("z_min", "thickness"):
            with self.subTest(key=key):
                changed = deepcopy(self.document)
                changed["stackup"][1][key] = unknown("length", "mm")
                self.assert_blocked(changed, "E_GEOMETRY", "stackup." + identity(3) + "." + key)
        changed = deepcopy(self.document)
        changed["stackup"].pop(0)
        self.assert_blocked(changed, "E_GEOMETRY", "stackup")

    def test_missing_board_dimension_does_not_become_zero(self):
        """! @brief 미정 외형 치수는 빈 고체나 기본 치수로 바뀌지 않는다."""
        self.document["board"]["outline"]["width"] = unknown("length", "mm")
        self.assert_blocked(self.document, "E_GEOMETRY", "board.outline.width")

    def test_unsupported_coverage_and_transforms_are_explicitly_rejected(self):
        """! @brief coating의 임의 전체 채움과 묵시적 미러/회전을 거절한다."""
        for role in ("coating", "adhesive", "air"):
            with self.subTest(role=role):
                changed = deepcopy(self.document)
                changed["stackup"][0]["role"] = role
                self.assert_blocked(changed, "E_UNSUPPORTED", "stackup." + identity(20) + ".role")
        changed = deepcopy(self.document)
        changed["frames"]["board"]["translation_si"] = [0.001, 0.0, 0.0]
        self.assert_blocked(changed, "E_UNSUPPORTED", "frames.board")

    def test_excluded_geometry_keeps_explicit_omission_and_original_binding(self):
        """! @brief 출력 제외 형상의 미정 치수를 소비하거나 원본에서 제거하지 않는다."""
        geometry = self.document["geometry"][0]
        geometry["include_in_export"] = False
        geometry["width"] = unknown("length", "mm")
        result = build_cad_input(self.document, snapshot_for(self.document))
        self.assertEqual([shape["id"] for shape in result["shapes"]], [identity(7)])
        self.assertEqual(result["omissions"], [{"id": identity(6), "reason": "include_in_export=false"}])
        self.assertIsNone(result["source_semantics"]["geometry"][0]["width"]["value_si"])

    def test_parameter_coordinate_is_resolved_without_flattening_source(self):
        """! @brief UUID 결합 좌표는 native 숫자와 원본 매개변수 참조를 함께 보존한다."""
        identifier = identity(30)
        command = {"command_id": str(uuid4()), "type": "parameter.set", "payload": {
            "id": identifier, "name": "선 시작점", "quantity": quantity(2.5, "mm"),
        }}
        document, *_ = apply_command(self.document, command, self.document["revision_id"])
        document["geometry"][0]["start"][0] = {"parameter_id": identifier}
        result = build_cad_input(document, snapshot_for(document))
        self.assertEqual(result["shapes"][0]["start_mm"][0], 2.5)
        self.assertEqual(result["source_semantics"]["geometry"][0]["start"][0], {"parameter_id": identifier})

    def test_signed_arcs_and_full_turn_keep_their_physical_direction(self):
        """! @brief 양/음 sweep과 한 바퀴 원호를 같은 부호의 각도로 전달한다."""
        for sweep in (math.pi * 1.5, -math.pi * 1.5, 2.0 * math.pi, -2.0 * math.pi):
            with self.subTest(sweep=sweep):
                document = deepcopy(self.document)
                arc = deepcopy(document["geometry"][0])
                arc.pop("start")
                arc.pop("end")
                arc.update(kind="arc_path", center=[quantity(20, "mm"), quantity(20, "mm")],
                           radius=quantity(5, "mm"), start_angle=quantity(20, "deg"), sweep_angle=quantity(sweep, "rad"))
                apply_design_command(document, "geometry.set", {"geometry": arc})
                result = build_cad_input(document, snapshot_for(document))["shapes"][0]
                self.assertAlmostEqual(result["start_angle_deg"], 20.0)
                self.assertAlmostEqual(result["sweep_angle_deg"], math.degrees(sweep))
                self.assertEqual(result["radius_mm"], 5.0)

    def test_tiny_thickness_or_subresolution_layer_gap_is_blocked(self):
        """! @brief CAD 허용오차가 층 두께/간격을 소실시킬 입력을 차단한다."""
        changed = deepcopy(self.document)
        changed["stackup"][1]["thickness"] = quantity(MIN_FEATURE_MM / 2, "mm")
        self.assert_blocked(changed, "E_GEOMETRY", "stackup." + identity(3) + ".thickness")
        changed = deepcopy(self.document)
        changed["stackup"][1]["z_min"] = quantity(MIN_FEATURE_MM / 2, "mm")
        self.assert_blocked(changed, "E_GEOMETRY", "stackup." + identity(3) + ".z_min")

    def test_minute_inner_arc_radius_and_large_coordinates_are_blocked(self):
        """! @brief 내부 반지름 소실과 profile 밖 좌표를 명시적으로 거부한다."""
        self.document["geometry"][0]["start"][0] = quantity(1e6 + 1, "mm")
        self.assert_blocked(self.document, "E_GEOMETRY", "geometry." + identity(6) + ".start[0]")
        changed = cad_fixture()
        arc = changed["geometry"][0]
        arc.pop("start")
        arc.pop("end")
        arc.update(kind="arc_path", center=[quantity(20, "mm"), quantity(20, "mm")],
                   radius=quantity(0.250001, "mm"), start_angle=quantity(0, "deg"), sweep_angle=quantity(90, "deg"))
        self.assert_blocked(changed, "E_GEOMETRY", "geometry." + identity(6) + ".width")

    def test_snapshot_and_profile_definition_are_owned_copies(self):
        """! @brief 외부 호출자가 이전 입력이나 이후 profile 상수를 변경하지 못한다."""
        result = build_cad_input(self.document, self.snapshot)
        result["profile_definition"]["step_schema"] = "AP214"
        result["layers"][0]["name"] = "변경"
        self.assertEqual(profile_definition()["step_schema"], "AP242")
        later = build_cad_input(self.document, self.snapshot)
        self.assertEqual(later["profile"], PROFILE)
        self.assertEqual(later["layers"][0]["name"], "검증용 유전체")

    def test_native_arc_angle_resolution_is_checked_before_execution(self):
        """! @brief native 제한보다 작은 회전량과 과도한 시작 각도를 접수 전에 거부한다."""
        for start, sweep, suffix in ((0.0, 1e-7, "sweep_angle"), (1e6 + 1, 90.0, "start_angle")):
            with self.subTest(start=start, sweep=sweep):
                changed = deepcopy(self.document)
                arc = changed["geometry"][0]
                arc.pop("start")
                arc.pop("end")
                arc.update(kind="arc_path", center=[quantity(20, "mm"), quantity(20, "mm")],
                           radius=quantity(5, "mm"), start_angle=quantity(start, "deg"), sweep_angle=quantity(sweep, "deg"))
                self.assert_blocked(changed, "E_GEOMETRY", "geometry." + identity(6) + "." + suffix)

    def test_shape_limit_is_independent_of_storage_collection_limit(self):
        """! @brief 저장할 수 있어도 native CAD 자원 상한을 넘는 모델은 접수하지 않는다."""
        template = deepcopy(self.document["geometry"][0])
        self.document["geometry"] = []
        self.document["ports"] = []
        for number in range(MAX_SHAPES + 1):
            geometry = deepcopy(template)
            geometry["id"] = identity(1000 + number)
            self.document["geometry"].append(geometry)
        self.assert_blocked(self.document, "E_RESOURCE", "geometry")


if __name__ == "__main__":
    unittest.main()
