"""! @brief PCB 0.6 원본, 유한 patch, 실제 서비스 이력과 미정 보존 경계를 검증한다."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from rfad.application import pcb_exchange_service as service_api
from rfad.application.canonical import canonical_hash
from rfad.application.canvas import build_canvas_dto
from rfad.application.editor import build_dto
from rfad.application.pcb_exchange_projection import mechanical_projection, aperture_projection
from rfad.application.projects import ProjectService
from rfad.domain.design_checks import check_design
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_features import COMMAND, REPLAY_COMMAND, empty_pcb, make_patch, apply_pcb_command
from rfad.domain.project import apply_command, validate_project
from rfad.domain.units import Quantity
from test_design import build_design, quantity, unknown, identity


def pcb_document():
    """! @brief 제작 치수나 재료를 가장하지 않는 명시 기계 시험 원본을 만든다."""
    document = build_design(with_port=False)
    document["metadata"]["name"] = "PCB 원본 / 검증 전용"
    document["geometry"][0]["source_ref"] = "explicit-test-source"
    dielectric = {"id": identity(20), "name": "기판 / 물성 미정", "role": "dielectric", "order": 1,
                  "z_min": quantity(.035, "mm"), "thickness": quantity(1, "mm"), "material_id": document["materials"][0]["id"]}
    document["stackup"].append(dielectric)
    validate_project(document)
    return document


def hole_record(document, *, x=5, y=1, diameter=1):
    """! @brief 비도금만 명시하고 공구/출처 미정은 원문으로 유지한다."""
    row = service_api.new_record(document, "hole")
    row["shape"] = {"kind": "circle", "center": [quantity(x, "mm"), quantity(y, "mm")], "diameter": quantity(diameter, "mm")}
    row["plating"]["state"] = "unplated"
    row["source_refs"] = ["형상 시험 입력 / 실제 제작 조건 미확정"]
    row["tool_diameter"]["source_refs"] = ["공구 자료 없음"]
    return row


def footprint_record(document):
    """! @brief 기존 world 도체를 복제하지 않고 명시 그룹만 만든다."""
    row = service_api.new_record(document, "footprint")
    row["placement"] = {"origin": [quantity(0, "mm"), quantity(0, "mm")], "rotation": quantity(0, "deg"), "side": "top"}
    row["members"] = [{"collection": "geometry", "id": document["geometry"][0]["id"]}]
    return row


def candidate(document, operation, values):
    """! @brief 공개 후보 함수의 실제 진단을 시험 실패에 포함한다."""
    data = {"expected_revision": document["revision_id"], "operation": operation, "values": values, "reason": "보존 경계 시험"}
    review, patch = service_api.preview(document, data)
    if not review["can_apply"]:
        raise AssertionError(review["issues"])
    return review, patch, data


class PcbFeatureDomainTests(unittest.TestCase):
    """! @brief 프로젝트 스키마, 소유권, 수량과 정확한 역명령을 검사한다."""

    def test_old_named_schema_query_unchanged_and_first_undo_removes_absent_container(self):
        document = pcb_document()
        document["schema_version"] = "rfad.project/0.5"
        before = deepcopy(document)
        service_api.get(document, {"section": "hole", "record_id": None})
        self.assertEqual(document, before)
        review, patch, _ = candidate(document, "hole.set", {"record": hole_record(document)})
        changed, _, _, inverse = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
        self.assertEqual(changed["schema_version"], "rfad.project/0.6")
        restored, _, _, _ = apply_command(changed, {"command_id": str(uuid4()), **inverse}, changed["revision_id"])
        self.assertNotIn("pcb", restored)
        self.assertEqual(restored["materials"], before["materials"])
        self.assertEqual(document, before)
        self.assertFalse(review["manufacturing_verified"])

    def test_cutout_polygon_and_immutable_projection(self):
        document = pcb_document()
        row = service_api.new_record(document, "cutout", "polygon")
        row["shape"] = {"kind": "polygon", "outer": [[quantity(x, "mm"), quantity(y, "mm")] for x, y in ((2, 6), (4, 6), (4, 8), (2, 8))], "holes": []}
        _, patch, _ = candidate(document, "cutout.set", {"record": row})
        updated, _, _, inverse = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
        self.assertNotIn("pcb", updated)
        self.assertEqual(mechanical_projection(updated)["cutouts"][0]["shape"]["outer_mm"][0], [2, 6])
        restored, _, _, _ = apply_command(updated, {"command_id": str(uuid4()), **inverse}, updated["revision_id"])
        self.assertNotIn("cutouts", restored["board"])

    def test_missing_plating_and_tool_are_saved_but_not_guessed(self):
        document = pcb_document()
        row = service_api.new_record(document, "hole")
        _, patch, _ = candidate(document, "hole.set", {"record": row})
        updated = deepcopy(document)
        apply_pcb_command(updated, patch)
        projected = mechanical_projection(updated)["holes"][0]
        self.assertIsNone(projected["tool_diameter_mm"])
        self.assertIsNone(projected["plating"]["thickness_mm"])
        self.assertEqual(projected["plating"]["state"], "unknown")
        self.assertTrue(build_canvas_dto(updated)["pcb_features"][0]["missing"])

    def test_owned_move_is_one_world_transform_and_undo_exact(self):
        document = pcb_document()
        row = footprint_record(document)
        document["pcb"] = empty_pcb()
        document["pcb"]["footprints"] = [row]
        validate_project(document)
        before = deepcopy(document)
        values = {"id": row["id"], "placement": {"origin": [quantity(10, "mm"), quantity(20, "mm")], "rotation": quantity(90, "deg"), "side": "top"}}
        review, patch, _ = candidate(document, "footprint.place", values)
        updated, _, _, inverse = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
        self.assertAlmostEqual(updated["geometry"][0]["start"][0]["value_si"], .009)
        self.assertAlmostEqual(updated["geometry"][0]["start"][1]["value_si"], .021)
        self.assertEqual(updated["geometry"][0]["source_ref"], before["geometry"][0]["source_ref"])
        restored, _, _, _ = apply_command(updated, {"command_id": str(uuid4()), **inverse}, updated["revision_id"])
        self.assertEqual(restored["geometry"], before["geometry"])
        self.assertEqual(restored["pcb"], before["pcb"])
        self.assertIn("10.0 mm", review["changes"][-1]["after_display"])

    def test_bound_position_move_and_dangling_generic_delete_are_blocked(self):
        document = pcb_document()
        pid = identity(301)
        document["parameters"][pid] = {"id": pid, "name": "고정 위치", "quantity": quantity(1, "mm")}
        document["geometry"][0]["start"][0] = {"parameter_id": pid}
        row = footprint_record(document)
        document["pcb"] = {**empty_pcb(), "footprints": [row]}
        data = {"expected_revision": document["revision_id"], "operation": "footprint.place", "reason": "시험",
                "values": {"id": row["id"], "placement": {"origin": [quantity(1, "mm"), quantity(0, "mm")], "rotation": quantity(0, "deg"), "side": "top"}}}
        review, _ = service_api.preview(document, data)
        self.assertFalse(review["can_apply"])
        with self.assertRaises(ProjectError):
            apply_command(document, {"command_id": str(uuid4()), "type": "geometry.remove", "payload": {"id": document["geometry"][0]["id"]}}, document["revision_id"])

    def test_detach_keeps_world_source_and_undo_restores_owner(self):
        document = pcb_document()
        row = footprint_record(document)
        document["pcb"] = {**empty_pcb(), "footprints": [row]}
        _, patch, _ = candidate(document, "footprint.detach", {"id": row["id"]})
        updated, _, _, inverse = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
        self.assertEqual(updated["geometry"], document["geometry"])
        self.assertEqual(updated["pcb"]["footprints"], [])
        restored, _, _, _ = apply_command(updated, {"command_id": str(uuid4()), **inverse}, updated["revision_id"])
        self.assertEqual(restored["pcb"], document["pcb"])

    def test_cut_bore_changes_real_contact_and_split_is_not_a_single_conductor(self):
        document = pcb_document()
        document["pcb"] = {**empty_pcb(), "holes": [hole_record(document, diameter=1)]}
        before = deepcopy(document)
        report = check_design(document)
        self.assertTrue(any("여러 도체 섬" in row["message"] for row in report["issues"]))
        self.assertEqual(document, before)
        self.assertEqual(report["statistics"]["unresolved_shapes"], 1)

    def test_invalid_patch_presence_cannot_silently_drop_new_record(self):
        document = pcb_document()
        _, patch, _ = candidate(document, "hole.set", {"record": hole_record(document)})
        patch["container_presence"]["replacement"]["pcb"] = False
        patch["provenance"]["patch_hash"] = canonical_hash({key: value for key, value in patch.items() if key != "provenance"})
        with self.assertRaises(ProjectError):
            apply_pcb_command(deepcopy(document), patch)

    def test_form_shape_mode_transition_preserves_original(self):
        document = pcb_document()
        row = hole_record(document)
        document["pcb"] = {**empty_pcb(), "holes": [row]}
        result = service_api.get(document, {"section": "hole", "record_id": row["id"], "shape_kind": "capsule"})
        self.assertEqual(result["form"]["original_record"], row)
        self.assertEqual(result["form"]["record"]["shape"]["kind"], "capsule")
        self.assertIsNone(result["form"]["record"]["shape"]["finished_width"]["value_si"])
        self.assertEqual(document["pcb"]["holes"][0], row)

    def test_aperture_ratio_uses_explicit_values_and_layer_removal_lists_all_losses(self):
        document = pcb_document()
        pad = deepcopy(document["geometry"][0])
        for key in ("start", "end", "width"):
            pad.pop(key)
        pad.update(kind="pad", pad_shape="rectangle", center=[quantity(10, "mm"), quantity(10, "mm")],
                   size=[quantity(2, "mm"), quantity(3, "mm")], rotation=quantity(0, "deg"))
        document["geometry"][0] = pad
        layer = service_api.new_record(document, "artwork_layer")
        layer["use_state"] = "used"
        aperture = service_api.new_record(document, "aperture")
        aperture.update(artwork_layer_id=layer["id"], definition={"mode": "pad_margin", "pad_id": pad["id"],
                        "margin": quantity(.1, "mm"), "size_ratio": quantity(.1, "1")})
        document["pcb"] = {**empty_pcb(), "artwork_layers": [layer], "apertures": [aperture]}
        validate_project(document)
        projected = aperture_projection(document, aperture)
        self.assertAlmostEqual(projected["size_mm"][0], 2.4)
        self.assertAlmostEqual(projected["size_mm"][1], 3.5)
        changed = deepcopy(layer)
        changed["use_state"] = "unknown"
        data = {"expected_revision": document["revision_id"], "operation": "artwork_layer.set", "reason": "사용 상태 미정으로 복귀",
                "values": {"record": changed, "remove_aperture_ids": []}}
        self.assertFalse(service_api.preview(document, data)[0]["can_apply"])
        data["values"]["remove_aperture_ids"] = [aperture["id"]]
        review, patch = service_api.preview(document, data)
        self.assertTrue(review["can_apply"], review.get("issues"))
        self.assertEqual(len(review["changes"]), 2)
        updated, _, _, inverse = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
        self.assertEqual(updated["pcb"]["apertures"], [])
        restored, _, _, _ = apply_command(updated, {"command_id": str(uuid4()), **inverse}, updated["revision_id"])
        self.assertEqual(restored["pcb"], document["pcb"])

    def test_geometric_removal_clears_old_overlap_before_drc_and_keeps_missing_tool(self):
        document = pcb_document()
        # @brief 서로 접하는 넓은 두 사각 도체의 공유 구간을 실제 절삭한다.
        for index, row in enumerate(document["geometry"]):
            for key in ("start", "end", "width"):
                row.pop(key)
            row.update(kind="planar_region", outer=[[quantity(x, "mm"), quantity(y, "mm")] for x, y in
                ((1, 1), (5, 1), (5, 5), (1, 5))] if index == 0 else [[quantity(x, "mm"), quantity(y, "mm")] for x, y in
                ((4, 2), (8, 2), (8, 4), (4, 4))], holes=[])
        self.assertTrue(any(row["rule"] == "different_net_short" for row in check_design(document)["issues"]))
        cutout = service_api.new_record(document, "cutout", "polygon")
        cutout["shape"] = {"kind": "polygon", "outer": [[quantity(x, "mm"), quantity(y, "mm")] for x, y in
                            ((3.5, .5), (5.5, .5), (5.5, 5.5), (3.5, 5.5))], "holes": []}
        document["board"]["cutouts"] = [cutout]
        validate_project(document)
        result = check_design(document)
        self.assertEqual(result["statistics"]["unresolved_shapes"], 0)
        self.assertFalse(any(row["rule"] == "different_net_short" for row in result["issues"]))
        self.assertEqual(len(result["connectivity"]["components"]), 2)

    def test_solver_mechanical_preflight_blocks_before_runtime_and_key_includes_holes(self):
        from rfad.application.pcb_solver import _payload
        from rfad.domain.design_sweep import _evaluation_key
        document = pcb_document()
        spec = {"network": None}
        previous_key = _evaluation_key(document, {}, None, spec)
        document["pcb"] = {**empty_pcb(), "holes": [hole_record(document)]}
        self.assertNotEqual(_evaluation_key(document, {}, None, spec), previous_key)
        with self.assertRaises(ProjectError) as caught:
            _payload(document, {}, {}, {})
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")


class PcbFeatureServiceTests(unittest.TestCase):
    """! @brief 실제 writer transaction, 재전송/재열기 및 이력 원본을 검사한다."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.service = ProjectService(self.workspace, auto_run=False)
        task = self.service.mutate("project.open", self.request({"path": "projects/pcb", "open_mode": "create", "name": "PCB 시험"}, {}))
        self.service.run_next()
        result = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})["events"][-1]["operation_result"]
        self.project = result["project_id"]
        document = pcb_document()
        document["project_id"] = self.project
        def install(state):
            project = state["projects"][self.project]
            reference = self.service._store_document(project["path"], document)
            project.update(current=reference, saved=reference, revisions={document["revision_id"]: reference},
                           history={"undo": [], "redo": [], "head_revision": document["revision_id"]})
        self.service.journal.transaction(install)
        self.revision = document["revision_id"]

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def request(self, data, context=None):
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project} if context is None else context,
                "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def document(self):
        return self.service._load(self.service.journal.read()["projects"][self.project])

    def test_apply_receipt_save_reopen_and_undo_exact_source(self):
        before = self.document()
        review, _, data = candidate(before, "hole.set", {"record": hole_record(before)})
        request = self.request({**data, "review_hash": review["review_hash"], "command_id": str(uuid4())})
        response = self.service.mutate(service_api.MUTATION, request)
        self.assertEqual(response, self.service.mutate(service_api.MUTATION, request))
        stored = self.document()
        self.assertEqual(stored["materials"], before["materials"])
        self.assertEqual(stored["geometry"], before["geometry"])
        receipt = service_api.read(self.service, "pcb.features.receipt", {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project},
                    "input": {key: request[key] for key in ("request_key", "request_key_epoch")}})
        self.assertEqual(receipt["response"], response)
        self.assertTrue(receipt["authoritative"])
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.assertEqual(self.document(), stored)
        result = self.service.mutate("project.undo", self.request({"expected_revision": stored["revision_id"], "command_id": str(uuid4())}))
        self.assertNotIn("pcb", self.document())
        self.service.mutate("project.redo", self.request({"expected_revision": result["new_revision"], "command_id": str(uuid4())}))
        self.assertEqual(self.document()["pcb"], stored["pcb"])

    def test_stale_hash_internal_bypass_and_other_project_receipt_rejected(self):
        document = self.document()
        review, patch, data = candidate(document, "hole.set", {"record": hole_record(document)})
        before = self.service.journal.read()
        for kind in (COMMAND, REPLAY_COMMAND):
            with self.assertRaises(ProjectError):
                self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": kind, "payload": patch}))
        changed = deepcopy(data)
        changed["values"]["record"]["name"] = "변경 이름"
        with self.assertRaises(ProjectError):
            self.service.mutate(service_api.MUTATION, self.request({**changed, "review_hash": review["review_hash"], "command_id": str(uuid4())}))
        self.assertEqual(before, self.service.journal.read())

    def test_imported_member_edit_state_undo_redo_replays_exact_metadata(self):
        document = self.document()
        row = footprint_record(document)
        import_id = identity(500)
        raw = self.service.journal.put_immutable("projects/pcb/imports/original.kicad_mod", b"(footprint test)")
        report = self.service.journal.put_immutable("projects/pcb/imports/report.json", b'{"scope":"test"}')
        row["origin"] = {"import_id": import_id, "source_object_id": "source-footprint"}
        row["edit_state"] = "original"
        document["pcb"] = {**empty_pcb(), "footprints": [row], "imports": [{"id": import_id, "format": "kicad_footprint", "format_version": "test",
            "parser_profile": "test/0.1", "source_files": [raw], "report": report, "bindings": [{"source_object_id": "source-footprint", "collection": "pcb.footprints", "id": row["id"]}], "source_refs": ["source kept"]}]}
        validate_project(document)
        def install(state):
            project = state["projects"][self.project]
            reference = self.service._store_document(project["path"], document)
            project["current"] = reference
            project["revisions"][document["revision_id"]] = reference
        # @brief fixture는 같은 revision의 최초 원본을 교체하지 않도록 별도 개정으로 설치한다.
        document["parent_revision_ids"] = [document["revision_id"]]
        document["revision_id"] = str(uuid4())
        def install_new(state):
            install(state)
            state["projects"][self.project]["history"]["head_revision"] = document["revision_id"]
        self.service.journal.transaction(install_new)
        geometry = deepcopy(document["geometry"][0])
        geometry["width"] = quantity(.7, "mm")
        response = self.service.mutate("project.apply_command", self.request({"expected_revision": document["revision_id"], "command_id": str(uuid4()), "type": "geometry.set", "payload": {"geometry": geometry}}))
        self.assertEqual(self.document()["pcb"]["footprints"][0]["edit_state"], "locally_modified")
        after = self.document()
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        undone = self.service.mutate("project.undo", self.request({"expected_revision": response["new_revision"], "command_id": str(uuid4())}))
        self.assertEqual(self.document()["pcb"], document["pcb"])
        self.assertEqual(self.document()["geometry"], document["geometry"])
        self.service.mutate("project.redo", self.request({"expected_revision": undone["new_revision"], "command_id": str(uuid4())}))
        self.assertEqual(self.document()["pcb"], after["pcb"])
        self.assertEqual(self.service.journal.read_artifact(raw), b"(footprint test)")

    def test_malformed_form_returns_explicit_blocker_without_write(self):
        document = self.document()
        before = self.service.journal.read()
        for values in ({"record": []}, {"record": {"id": "invalid", "shape": []}}, {"record": {"shape": {"kind": "polygon", "outer": 42, "holes": []}}}):
            data = {"expected_revision": document["revision_id"], "operation": "hole.set", "values": values, "reason": "bad input"}
            result = service_api.read(self.service, "pcb.features.preview", {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": data})
            self.assertFalse(result["can_apply"])
            self.assertTrue(result["issues"])
        self.assertEqual(before, self.service.journal.read())
