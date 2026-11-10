"""! @brief 실제 제작물과 구분한 IFA/중공 비아 탐색 입력 및 EM 의미 검사를 제공한다."""

from copy import deepcopy
import unittest
from uuid import uuid4

from rfad.application.pcb_solver import build_pcb_plan, shape_polygons
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from test_pcb_solver import SETTINGS, fixture_document, quantity, runtime_identity, snapshot_for


IFA_SETTINGS = {"frequency_hz": {"start": 2.4e9, "stop": 2.4835e9, "count": 51}, "grid_mm": 0.5,
                "air_padding_mm": 8.0, "curve_tolerance_mm": 0.025, "max_timesteps": 50000, "end_criterion": 1e-4}
VIA_SETTINGS = {**SETTINGS, "curve_tolerance_mm": 0.01, "max_timesteps": 100000, "end_criterion": 1e-3}


def ifa_document():
    """! @brief 40x60 mm 초기 외곽의 명시적 가정 IFA를 만들며 SMA/실물 검증을 주장하지 않는다."""
    document = fixture_document()
    document["metadata"]["name"] = "Exploratory planar IFA; explicit assumptions; not SMA or measured baseline"
    document["metadata"]["description"] = "40x60 mm exploratory IFA geometry. epsilon_r=4.2, tan_delta=0.018, 0.93 mm core and 35 um copper are explicit test assumptions. Ideal local gap feed, no SMA/launch/mask or assembly model. Not a tuned or validated antenna."
    document["board"]["outline"].update(width=quantity(40, "mm"), height=quantity(60, "mm"))
    dielectric, top = document["stackup"]
    dielectric.update(order=1, z_min=quantity(0.035, "mm"), thickness=quantity(0.93, "mm"))
    top.update(order=2, z_min=quantity(0.965, "mm"))
    bottom = {**deepcopy(top), "id": str(uuid4()), "name": "Explicit lower copper; no automatic ground fill", "order": 0, "z_min": quantity(0, "mm")}
    document["stackup"] = [bottom, dielectric, top]
    substrate = next(item for item in document["materials"] if item["id"] == dielectric["material_id"])
    substrate.update(epsilon_r=quantity(4.2, "1"), tan_delta=quantity(0.018, "1"))
    net_id = document["nets"][0]["id"]
    document["nets"] = [{"id": net_id, "name": "IFA continuous DC conductor including short and ground"}]
    base = {key: value for key, value in document["geometry"][0].items() if key not in ("id", "start", "end", "width", "kind", "role")}
    base["net_id"] = net_id
    def xy(x, y):
        """! @brief fixture의 명시적 좌표를 SI Quantity로 바꾼다."""
        return [quantity(x, "mm"), quantity(y, "mm")]
    ground_id, radiator_id, feed_id, short_id, pad_id = [str(uuid4()) for _ in range(5)]
    document["geometry"] = [
        {**base, "id": ground_id, "kind": "planar_region", "role": "ground", "outer": [xy(0, 0), xy(40, 0), xy(40, 50), xy(0, 50)],
         "holes": [[xy(30, 10), xy(34, 10), xy(34, 14), xy(30, 14)]]},
        {**base, "id": radiator_id, "kind": "line_path", "role": "radiator", "start": xy(5, 57), "end": xy(31, 57), "width": quantity(1, "mm")},
        {**base, "id": short_id, "kind": "line_path", "role": "short", "start": xy(5, 49.5), "end": xy(5, 57), "width": quantity(1, "mm")},
        {**base, "id": feed_id, "kind": "line_path", "role": "feed", "start": xy(9, 52.5), "end": xy(9, 57), "width": quantity(1, "mm")},
        {**base, "id": pad_id, "kind": "pad", "role": "feed", "pad_shape": "rectangle", "center": xy(9, 53), "size": xy(2, 2), "rotation": quantity(0, "deg")},
    ]
    document["geometry"].sort(key=lambda item: item["id"])
    document["ports"][0].update(positive_geometry_id=pad_id, reference_geometry_id=ground_id, direction=[0, 1, 0],
                               reference_plane="ideal local antenna gap; no SMA or launch deembedding",
                               validity_hz={"min": quantity(2, "GHz"), "max": quantity(3, "GHz")},
                               excitation_box={"start": [*xy(9, 50), quantity(0.965, "mm")], "stop": [*xy(9, 52), quantity(0.965, "mm")]})
    validate_project(document)
    return document


def via_document():
    """! @brief 작은 독립 PTH 실행 입력이며 100 um 도금은 명시적 시험 가정이다."""
    document = fixture_document()
    document["metadata"]["description"] = "Explicit hollow PTH runtime fixture, not manufacturing data. Finished bore 0.6 mm, plating 0.1 mm, drill 0.8 mm. Bulk copper skin-depth loss is not validated."
    dielectric, top = document["stackup"]
    dielectric["order"], top["order"] = 1, 2
    bottom = {**deepcopy(top), "id": str(uuid4()), "name": "Test lower conductor", "order": 0, "z_min": quantity(-0.035, "mm")}
    document["stackup"] = [bottom, dielectric, top]
    ground = next(item for item in document["geometry"] if item["role"] == "ground")
    base = {key: value for key, value in ground.items() if key not in ("id", "start", "end", "width", "kind", "role")}
    top_pad_id, bottom_pad_id, via_id = [str(uuid4()) for _ in range(3)]
    center = [quantity(3, "mm"), quantity(6, "mm")]
    pad = {**base, "kind": "pad", "role": "ground", "pad_shape": "circle", "center": center,
           "size": [quantity(2, "mm"), quantity(2, "mm")], "rotation": quantity(0, "deg")}
    document["geometry"].extend([
        {**pad, "id": top_pad_id}, {**deepcopy(pad), "id": bottom_pad_id, "layer_id": bottom["id"]},
        {**base, "id": via_id, "kind": "via", "role": "conductor", "layer_id": bottom["id"], "end_layer_id": top["id"],
         "center": center, "finished_hole_diameter": quantity(0.6, "mm"), "plating_thickness": quantity(0.1, "mm"),
         "tool_hole_diameter": quantity(0.8, "mm"), "fill": "none", "pad_ids": [bottom_pad_id, top_pad_id]},
    ])
    document["geometry"].sort(key=lambda item: item["id"])
    validate_project(document)
    return document


def vertical_feed_document():
    """! @brief 서로 다른 높이의 두 도체에 명시적으로 부착한 z방향 급전을 만든다."""
    document = fixture_document()
    dielectric, top = document["stackup"]
    dielectric["order"], top["order"] = 1, 2
    bottom = {**deepcopy(top), "id": str(uuid4()), "name": "Vertical feed reference", "order": 0, "z_min": quantity(-0.035, "mm")}
    document["stackup"] = [bottom, dielectric, top]
    reference = next(item for item in document["geometry"] if item["role"] == "ground")
    radiator = next(item for item in document["geometry"] if item["role"] == "radiator")
    reference.update(layer_id=bottom["id"], start=deepcopy(radiator["start"]), end=deepcopy(radiator["end"]))
    document["ports"][0].update(direction=[0, 0, 1], reference_plane="explicit ideal vertical substrate gap",
                               excitation_box={"start": [quantity(11, "mm"), quantity(6, "mm"), quantity(0, "mm")],
                                               "stop": [quantity(11, "mm"), quantity(6, "mm"), quantity(1, "mm")]})
    validate_project(document)
    return document


class IfaPlanTests(unittest.TestCase):
    """! @brief 독립 feed/short/finite ground의 의미 연결과 구멍 보존을 확인한다."""

    def test_same_net_ifa_has_explicit_short_and_void(self):
        """! @brief 포트 양단이 DC 단락된 정상 IFA를 잘못된 net 충돌로 거절하지 않는다."""
        document = ifa_document()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), IFA_SETTINGS)
        self.assertEqual(len(plan["case"]["connectivity"]["components"]), 1)
        self.assertEqual(len(plan["case"]["connectivity"]["short_entity_ids"]), 1)
        self.assertFalse(plan["case"]["connectivity"]["yee_connectivity_checked"])
        ground = next(item for item in plan["case"]["shapes"] if item["kind"] == "planar_region")
        polygons = shape_polygons(ground, 0.025)
        from rfad.domain.planar import point_in_loop, signed_area
        self.assertFalse(any(point_in_loop([32, 12], polygon) for polygon in polygons))
        self.assertAlmostEqual(sum(signed_area(polygon) for polygon in polygons), 1984.0)

    def test_disconnected_short_is_blocked(self):
        """! @brief short가 명시되었지만 ground에 닿지 않으면 탐색 실행도 차단한다."""
        document = ifa_document()
        short = next(item for item in document["geometry"] if item["role"] == "short")
        short["start"][1] = quantity(52, "mm")
        with self.assertRaisesRegex(ProjectError, "short"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), IFA_SETTINGS)

    def test_hollow_via_preserves_finished_bore_and_finite_material(self):
        """! @brief 실제 도금과 중공 배럴을 PEC/충진으로 바꾸지 않는다."""
        document = via_document()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), VIA_SETTINGS)
        via = plan["case"]["vias"][0]
        self.assertAlmostEqual(via["inner_radius_mm"], 0.3)
        self.assertAlmostEqual(via["outer_radius_mm"], 0.4)
        self.assertEqual(via["fill"], "none")
        self.assertEqual(via["native_model"], "finite_conductivity_hollow_volume")
        self.assertEqual(via["conductivity_s_per_m"], 58e6)
        self.assertEqual(len(plan["case"]["connectivity"]["components"]), 2)

    def test_via_missing_bulk_epsilon_is_blocked_without_affecting_sheet_contract(self):
        """! @brief 체적 비아가 실제 소비하는 상대 유전율을 임의 1로 채우지 않는다."""
        from rfad.domain.units import Quantity
        document = via_document()
        via = next(item for item in document["geometry"] if item["kind"] == "via")
        material = next(item for item in document["materials"] if item["id"] == via["material_ref"])
        material["epsilon_r"] = Quantity.missing("dimensionless", "1").to_dict()
        with self.assertRaises(ProjectError):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), VIA_SETTINGS)

    def test_vertical_port_attaches_to_sheet_faces(self):
        """! @brief z포트는 평면 도체의 가장자리 대신 실제 면 내부의 양단에 부착한다."""
        document = vertical_feed_document()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        self.assertEqual(plan["case"]["port"]["axis"], "z")
        self.assertEqual(len(plan["case"]["connectivity"]["components"]), 2)

    def test_tool_bore_is_checked_without_replacing_finished_hole(self):
        """! @brief 알려진 tool bore 모순을 차단하고 미정 제조 치수는 그대로 보존한다."""
        from rfad.domain.units import Quantity
        document = via_document()
        via = next(item for item in document["geometry"] if item["kind"] == "via")
        via["tool_hole_diameter"] = quantity(0.9, "mm")
        with self.assertRaisesRegex(ProjectError, "tool hole"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), VIA_SETTINGS)
        via["tool_hole_diameter"] = Quantity.missing("length", "mm").to_dict()
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), VIA_SETTINGS)
        self.assertIsNone(plan["case"]["vias"][0]["tool_hole_diameter_mm"])
        self.assertFalse(plan["case"]["vias"][0]["tool_hole_used_for_native_geometry"])

    def test_partial_span_is_not_promoted_to_through_pth(self):
        """! @brief 도메인에 저장 가능한 부분 span을 through PTH 해석으로 오인하지 않는다."""
        document = via_document()
        core = next(item for item in document["stackup"] if item["role"] == "dielectric")
        top = document["stackup"][-1]
        document["stackup"].extend([
            {**deepcopy(core), "id": str(uuid4()), "name": "Additional core", "order": 3, "z_min": quantity(2, "mm"), "thickness": quantity(1, "mm")},
            {**deepcopy(top), "id": str(uuid4()), "name": "Actual top conductor", "order": 4, "z_min": quantity(3, "mm")},
        ])
        validate_project(document)
        with self.assertRaisesRegex(ProjectError, "관통 비아"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), VIA_SETTINGS)

    def test_dielectric_outside_physical_conductor_span_is_not_through_pth(self):
        """! @brief 최상 conductor 위의 유전체를 관통하지 않는 배럴은 PTH로 승인하지 않는다."""
        document = via_document()
        core = next(item for item in document["stackup"] if item["role"] == "dielectric")
        document["stackup"].append({**deepcopy(core), "id": str(uuid4()), "name": "Exterior cap", "order": 3,
                                    "z_min": quantity(2, "mm"), "thickness": quantity(1, "mm")})
        validate_project(document)
        with self.assertRaisesRegex(ProjectError, "추가 적층"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), VIA_SETTINGS)


if __name__ == "__main__":
    unittest.main()
