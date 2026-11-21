"""! @brief 경계 거리, 실제/기대 연결, 규칙 편집 원자성과 미정 보존을 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.design_rule_service import read
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.design_checks import check_design
from rfad.domain.boundary_distance import Arc, Segment, boundary_distance
from rfad.domain.check_geometry import footprint, board_clearance, separation
from rfad.domain.design_rules import RULES
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.domain.pcb_features import empty_pcb
from rfad.domain.target_constraints import empty_constraints
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture, request
from test_pcb_ifa import ifa_document, via_document
from test_pcb_features import hole_record
from test_pcb_solver import fixture_document, quantity, snapshot_for, runtime_identity, SETTINGS
from test_targets import command, set_target, target_input


def profile(**limits):
    """! @brief 규칙은 명시적으로 입력하고 생략한 값은 미정 상태로 둔다."""
    return {"id": str(uuid4()), "name": "시험 카탈로그 규칙", "version": "시험 v1",
            "source_refs": ["시험 카탈로그 원문 식별자"],
            "rules": {key: Quantity.from_value(limits[key], "mm" if dimension == "length" else "1",
                                                status="source_default", source_refs=["시험 카탈로그 규칙"]).to_dict()
                      if key in limits else Quantity(None, dimension, "mm" if dimension == "length" else "1",
                                                     "missing", ["공개값 미정"]).to_dict()
                      for key, (_, dimension) in RULES.items()}}


def scenario():
    """! @brief 도체 간격 2 mm, 16 mm 기판, 미정 규칙을 가진 실제 GUI 입력이다."""
    document = set_target(fixture_document(), target_input())[0]
    rule = profile(minimum_clearance=2.5, minimum_width=0.8)
    document["manufacturing_profiles"] = [rule]
    constraints = empty_constraints()
    constraints["board_width_max"] = Quantity.from_value(15, "mm", status="estimated", source_refs=["외함 초안 추정"]).to_dict()
    constraints["board_thickness_max"] = Quantity(None, "length", "mm", "missing", ["외함 두께 미정"]).to_dict()
    constraints["manufacturing_profile_id"] = rule["id"]
    constraints["source_refs"] = ["시험 대상 공간 사본"]
    document["targets"][0]["constraints"] = constraints
    document["connections"] = [{"id":str(uuid4()),"name":"두 도체 연결 의도","kind":"isolated",
                                 "object_ids":[row["id"] for row in document["geometry"]],
                                 "source_refs":["원래 분리 의도 사본"]}]
    validate_project(document)
    return document


def inspect_rows(report, rule):
    """! @brief 판정 종류 전체에서 같은 규칙의 결과를 찾는다."""
    return [row for row in report["checks"] if row["rule"] == rule]


class DesignChecksTests(unittest.TestCase):
    def test_only_copper_cut_by_a_mechanical_hole_loses_nominal_width(self):
        """! @brief 실제로 맞닿은 절삭의 국부 폭만 미평가이며 다른 도체의 폭과 출처를 보존한다."""
        document = scenario()
        document["pcb"] = empty_pcb()
        far = hole_record(document, x=3, y=2)
        document["pcb"]["holes"] = [far]
        validate_project(document)
        before = deepcopy(document)
        widths = inspect_rows(check_design(document), "minimum_width")
        self.assertEqual(len(widths), 2)
        self.assertTrue(all(row["status"] == "passed" and row["measured"] == 1.0 for row in widths))
        self.assertTrue(all("시험 카탈로그 규칙" in row["source_refs"] for row in widths))
        self.assertEqual(document, before)
        near = hole_record(document, x=3, y=6.55, diameter=.45)
        document["pcb"]["holes"] = [near]
        validate_project(document)
        widths = inspect_rows(check_design(document), "minimum_width")
        self.assertCountEqual([(row["status"], row["measured"]) for row in widths], [("passed", 1.0), ("not_evaluated", None)])
        self.assertIsNone(near["tool_diameter"]["value_si"])

    def test_arc_cardinal_extrema_caps_and_intersections(self):
        """! @brief 음의 sweep 원호의 내부 극점과 실제 원호 범위를 독립 기대값과 비교한다."""
        document = fixture_document(circle=True)
        shape = deepcopy(document["geometry"][0])
        for key in ("start", "end"):
            del shape[key]
        shape.update(kind="arc_path", center=[quantity(0,"mm"),quantity(0,"mm")], radius=quantity(4,"mm"),
                     start_angle=quantity(180,"deg"), sweep_angle=quantity(-180,"deg"))
        arc = footprint(document, shape)
        self.assertAlmostEqual(board_clearance(document, arc)[0], 3.5)
        shape.update(kind="pad", pad_shape="rectangle", center=[quantity(0,"mm"),quantity(6,"mm")],
                     size=[quantity(1,"mm"),quantity(1,"mm")], rotation=quantity(45,"deg"))
        for key in ("radius","start_angle","sweep_angle","width"):
            del shape[key]
        self.assertAlmostEqual(separation(arc, footprint(document,shape), [100])[0], 1.5 - 2**-0.5)
        self.assertEqual(boundary_distance(Segment((0, -2), (0, 2)), Arc((0,0), 1))[0], 0)
        self.assertAlmostEqual(boundary_distance(Arc((0,0),1), Arc((3,0),1))[0], 1.0)

    def test_real_minimum_gap_and_target_limit_with_unknowns(self):
        """! @brief round cap까지 포함한 2 mm 간격과 목표 위반을 실제 위치로 반환한다."""
        document = scenario()
        before = canonical_bytes(document)
        report = check_design(document)
        gap = inspect_rows(report, "minimum_clearance")[0]
        self.assertEqual(gap["status"], "failed")
        self.assertAlmostEqual(gap["measured"], 2.0)
        self.assertAlmostEqual(gap["location_mm"][0], 8.0)
        self.assertEqual(inspect_rows(report, "board_width_max")[0]["status"], "failed")
        self.assertEqual(inspect_rows(report, "minimum_tool_hole")[0]["status"], "not_evaluated")
        self.assertEqual(inspect_rows(report, "expected_isolated")[0]["status"], "passed")
        self.assertEqual(len(report["connectivity"]["components"]), 2)
        self.assertFalse(report["manufacturing_verified"])
        self.assertEqual(canonical_bytes(document), before)
        with self.assertRaises(ProjectError) as caught:
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        self.assertEqual(caught.exception.code, "E_DESIGN_CONSTRAINT")

    def test_contact_not_inferred_from_same_net_or_short_tolerance(self):
        """! @brief 같은 net의 미세 양수 간격을 연결하지 않고 실제 교차만 연결한다."""
        document = scenario()
        first, second = document["geometry"]
        first.update(start=[quantity(3,"mm"),quantity(6,"mm")], end=[quantity(6,"mm"),quantity(6,"mm")])
        second.update(start=[quantity(7.000000001,"mm"),quantity(6,"mm")], end=[quantity(12,"mm"),quantity(6,"mm")])
        second["net_id"] = first["net_id"]
        document["connections"][0]["kind"] = "connected"
        self.assertEqual(inspect_rows(check_design(document),"expected_connected")[0]["status"],"failed")
        second["start"][0] = quantity(6.9,"mm")
        self.assertEqual(inspect_rows(check_design(document),"expected_connected")[0]["status"],"passed")
        second["net_id"] = next(row["id"] for row in document["nets"] if row["id"] != first["net_id"])
        self.assertEqual(inspect_rows(check_design(document),"different_net_short")[0]["status"],"failed")

    def test_ifa_ground_path_and_polygon_void_are_respected(self):
        """! @brief IFA 접지 경로는 정상 성분이며 구멍 안의 별도 도체는 절연 상태다."""
        document = ifa_document()
        port = document["ports"][0]
        document["connections"] = [{"id":str(uuid4()),"name":"IFA 실제 접지 경로","kind":"connected",
                                    "object_ids":[port["positive_geometry_id"],port["reference_geometry_id"]],"source_refs":[]}]
        self.assertEqual(inspect_rows(check_design(document),"expected_connected")[0]["status"],"passed")
        document = scenario()
        a,b = document["geometry"]
        coordinates = lambda values: [[quantity(x,"mm"),quantity(y,"mm")] for x,y in values]
        for row in (a,b):
            for name in ("start","end","width"):
                del row[name]
        a.update(kind="planar_region",outer=coordinates([(1,1),(15,1),(15,11),(1,11)]),
                 holes=[coordinates([(5,3),(11,3),(11,9),(5,9)])])
        b.update(kind="pad",pad_shape="circle",center=coordinates([(8,6)])[0],
                 size=[quantity(2,"mm"),quantity(2,"mm")],rotation=quantity(0,"deg"))
        rule = document["manufacturing_profiles"][0]
        rule["rules"]["minimum_clearance"] = quantity(2.1,"mm")
        validate_project(document)
        report = check_design(document)
        self.assertEqual(inspect_rows(report,"expected_isolated")[0]["status"],"passed")
        self.assertAlmostEqual(inspect_rows(report,"minimum_clearance")[0]["measured"],2.0)

    def test_via_pad_span_tool_and_ring_unknowns(self):
        """! @brief 비아의 실제 pad 피복과 공구 드릴 기준 환형 링을 따로 확인한다."""
        document = via_document()
        via = next(row for row in document["geometry"] if row["kind"] == "via")
        rule = profile(minimum_tool_hole=0.9,minimum_annular_ring=0.7,maximum_via_aspect_ratio=1.2)
        document["manufacturing_profiles"] = [rule]
        report = check_design(document,manufacturing_profile_id=rule["id"])
        self.assertEqual(inspect_rows(report,"via_endpoint_pads")[0]["status"],"passed")
        self.assertAlmostEqual(inspect_rows(report,"minimum_annular_ring")[0]["measured"],0.6)
        self.assertEqual(inspect_rows(report,"maximum_via_aspect_ratio")[0]["status"],"failed")
        via["tool_hole_diameter"] = Quantity.missing("length","mm").to_dict()
        report = check_design(document,manufacturing_profile_id=rule["id"])
        self.assertEqual(inspect_rows(report,"minimum_tool_hole")[0]["status"],"not_evaluated")
        self.assertEqual(inspect_rows(report,"via_endpoint_pads")[0]["status"],"passed")
        pad = next(row for row in document["geometry"] if row["id"] == via["pad_ids"][0])
        pad["center"] = [quantity(7,"mm"),quantity(6,"mm")]
        self.assertIn("failed", [row["status"] for row in inspect_rows(check_design(document),"via_pad_attachment")])

    def test_parameter_constraints_migration_and_reference_rejection(self):
        """! @brief 0.3 목표 원본을 보존하며 정수 위반과 참조 삭제를 확인한다."""
        document = set_target(fixture_document(),target_input())[0]
        document["schema_version"] = "rfad.project/0.3"
        before = canonical_bytes(document)
        parameter = {"id":str(uuid4()),"name":"반복 수","quantity":quantity(2.5,"1")}
        updated = command(document,"parameter.set",parameter)[0]
        constraints = empty_constraints()
        constraints["parameter_bounds"] = [{"parameter_id":parameter["id"],"minimum":quantity(1,"1"),"maximum":quantity(4,"1"),
                                             "integer":True,"source_refs":["시험 범위"]}]
        target = updated["targets"][0]["id"]
        updated = command(updated,"target.constraints.set",{"target_id":target,"constraints":constraints})[0]
        self.assertEqual(canonical_bytes(document),before)
        self.assertEqual(inspect_rows(check_design(updated),"parameter_integer")[0]["status"],"failed")
        with self.assertRaises(ProjectError):
            command(updated,"parameter.remove",{"id":parameter["id"]})
        updated["schema_version"] = "rfad.project/0.3"
        with self.assertRaises(ProjectError):
            validate_project(updated)

    def test_rpc_stale_read_retry_undo_and_sources(self):
        """! @brief 실제 서비스 요청의 영수증, stale 차단 및 상한 보존을 검사한다."""
        document = scenario()
        with TemporaryDirectory() as temp, ProjectService(Path(temp),auto_run=False) as service:
            register_fixture(service,document)
            identity, revision = document["project_id"], document["revision_id"]
            state_before_read = service.journal.read()
            report = read(service, "design.rules.check", {
                "contract_version": "rfad.api/2.0", "context": {"project_id": identity},
                "input": {"expected_revision": revision, "inclusion": "all", "target_ids": None,
                          "manufacturing_profile_id": None},
            })
            self.assertGreater(report["counts"]["failed"], 0)
            self.assertEqual(service.journal.read(), state_before_read)
            selection = {"section":"target","target_id":document["targets"][0]["id"],"record_id":None,"parameter_id":None}
            data = {"expected_revision":revision,"selection":selection,"command_id":str(uuid4()),
                    "operation":"set","values":{"board_width_max.unit":"um"},"reason":"표시 단위만 변경"}
            envelope = request(service,identity,data)
            reply = handle_frame(json.dumps({"jsonrpc":"2.0","id":1,"method":"design.rules.apply","params":envelope}).encode(),service)
            self.assertIn("result",reply,reply)
            updated = reply["result"]
            self.assertEqual(service.mutate("design.rules.apply",envelope),updated)
            before = service.journal.read()
            with self.assertRaises(ProjectError):
                read(service,"design.rules.get",{"contract_version":"rfad.api/2.0","context":{"project_id":identity},
                                               "input":{"expected_revision":revision,"selection":selection}})
            self.assertEqual(service.journal.read(),before)
            stored = service._load(before["projects"][identity])
            raw = stored["targets"][0]["constraints"]["board_width_max"]
            expected = document["targets"][0]["constraints"]["board_width_max"]
            self.assertEqual(raw,{**expected,"display_unit":"um"})
            service.mutate("project.undo",request(service,identity,{"expected_revision":updated["new_revision"],"command_id":str(uuid4())}))
            restored = service._load(service.journal.read()["projects"][identity])
            self.assertEqual(restored["targets"][0]["constraints"],document["targets"][0]["constraints"])
