"""! @brief 명시 기하 템플릿의 읽기 전용 후보, 원자 적용과 과거 출처 보존을 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.cad import build_cad_input
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.application.template_candidates import TemplateCandidateCoordinator
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command, validate_project
from rfad.domain.template_geometry import object_id
from rfad.domain.template_instance import EXTENSION_KEY, instance_status, record_hash
from rfad.domain.units import Quantity
from rfad.templates.cards import ARC, IFA, describe_card
from test_pcb_solver import fixture_document, runtime_identity, snapshot_for, SETTINGS
from test_targets import target_input


ARC_VALUES = {"center_x": 0, "center_y": 0, "radius": 6, "start_angle": 0, "sweep_angle": 90,
              "width": 0.8, "feed_start_x": 2, "feed_start_y": 0, "feed_width": 0.6}
IFA_VALUES = {"ground_left": 0, "ground_bottom": 0, "ground_width": 40, "ground_height": 50,
              "radiator_start_x": 5, "radiator_y": 57, "radiator_length": 26, "trace_width": 1,
              "short_x": 5, "short_start_y": 49.5, "feed_x": 9, "feed_start_y": 53, "pad_width": 2, "pad_height": 2}
IFA_SETTINGS = {"frequency_hz": {"start": 2.4e9, "stop": 2.4835e9, "count": 51}, "grid_mm": 0.5,
                "air_padding_mm": 8.0, "curve_tolerance_mm": 0.025, "max_timesteps": 50000, "end_criterion": 1e-4}


def quantity(value, unit):
    """! @brief 시험에서 명시적으로 제공한 값이며 제품 기본값이 아님을 기록한다."""
    return Quantity.from_value(value, unit, source_refs=["test-only-explicit-input"]).to_dict()


def base_document(kind=ARC, *, missing=False, keep_ground=False):
    """! @brief 기존 보드/적층을 남기고 템플릿이 새 기하를 추가할 입력을 준비한다."""
    document = fixture_document(circle=kind == ARC)
    document["ports"] = []
    if kind == IFA:
        document["board"]["outline"].update(width=quantity(40, "mm"), height=quantity(60, "mm"))
    document["geometry"] = [item for item in document["geometry"] if keep_ground and item["role"] == "ground"]
    retained = {item["net_id"] for item in document["geometry"]}
    document["nets"] = [item for item in document["nets"] if item["id"] in retained]
    if missing:
        for material in document["materials"]:
            for field, dimension, unit in (("epsilon_r", "dimensionless", "1"), ("tan_delta", "dimensionless", "1"), ("conductivity", "conductivity", "S/m")):
                material[field] = Quantity.missing(dimension, unit).to_dict()
    validate_project(document)
    return document


def specification(document, kind=ARC, *, display=False):
    """! @brief 공개 후보 요청의 카드/바인딩/명시 치수를 만든다."""
    card = describe_card(kind)
    values = ARC_VALUES if kind == ARC else IFA_VALUES
    inputs = {}
    for field in card["input_fields"]:
        key, unit = field["key"], field["display_unit"]
        inputs[key] = {"value": str(values[key]), "unit": unit} if display else quantity(values[key], unit)
    layer = next(item for item in document["stackup"] if item["role"] == "conductor")
    return {"expected_revision": document["revision_id"], "mode": "explicit_geometry",
            "template": {key: card[key] for key in ("template_id", "version", "content_hash")},
            "instance_id": str(uuid4()), "target_refs": [],
            "binding": {"board_id": document["board"]["id"], "frame_id": document["board"]["frame_id"],
                        "layer_id": layer["id"], "material_id": layer["material_id"]},
            "explicit_inputs": inputs, "port": None}


def port_recipe(document, kind, *, z=1.0):
    """! @brief 물리 저항과 gap 좌표를 시험 호출자가 명시한다."""
    start, stop = ([9, 50, z], [9, 52, z]) if kind == IFA else ([-1, 0, z], [1.7, 0, z])
    reference = None if kind == IFA else next(item["id"] for item in document["geometry"] if item["role"] == "ground")
    low, high = (2, 3) if kind == IFA else (8, 12)
    return {"reference_geometry_id": reference, "resistance": quantity(50, "ohm"),
            "reference_plane": "explicit test local gap; no SMA correction", "polarity": 1,
            "direction": [0, 1, 0] if kind == IFA else [1, 0, 0],
            "validity_hz": {"min": quantity(low, "GHz"), "max": quantity(high, "GHz")},
            "excitation_box": {"start": [quantity(value, "mm") for value in start], "stop": [quantity(value, "mm") for value in stop]}}


def preview(document, data):
    """! @brief 파일 저장을 배제한 coordinator의 동일 후보 조립 경로를 실행한다."""
    state = {"document": document}
    service = SimpleNamespace(journal=SimpleNamespace(read=lambda: deepcopy(state)),
                              repository=SimpleNamespace(project=lambda source, context: source["document"], load=deepcopy))
    coordinator = TemplateCandidateCoordinator(service)
    coordinator.validate_input("template.synthesize", {"project_id": document["project_id"]}, data)
    return coordinator._preview(state, {"project_id": document["project_id"]}, data)


def apply_payload(document, payload):
    """! @brief 서비스가 구성한 내부 명령의 순수 도메인 처리를 검증한다."""
    return apply_command(document, {"command_id": str(uuid4()), "type": "template_instance.apply", "payload": payload}, document["revision_id"])


class TemplateDomainTests(unittest.TestCase):
    """! @brief 기하/물성/출처의 경계와 의미 있는 실패 반례를 검사한다."""

    def test_two_cards_preview_is_read_only_repeatable_and_preserves_missing_materials(self):
        """! @brief 후보는 실제 canvas/CAD 입력이며 미정 물성이나 저항을 채우지 않는다."""
        for kind in (ARC, IFA):
            with self.subTest(kind=kind):
                document = base_document(kind, missing=True)
                before = canonical_bytes(document)
                data = specification(document, kind)
                first, payload = preview(document, data)
                repeated, _ = preview(document, data)
                self.assertTrue(first["can_apply"], first)
                self.assertEqual(first, repeated)
                self.assertEqual(canonical_bytes(document), before)
                self.assertEqual(first["input_checks"]["input_status"], "blocked")
                self.assertEqual(first["scene"]["omissions"], [])
                updated, _, invalidation, inverse = apply_payload(document, payload)
                self.assertEqual(updated["materials"], document["materials"])
                self.assertEqual(updated["stackup"], document["stackup"])
                self.assertEqual(updated["ports"], [])
                self.assertIn("physics", invalidation)
                cad = build_cad_input(updated, snapshot_for(updated))
                self.assertEqual(cad["source_semantics"]["extensions"], updated["extensions"])
                with self.assertRaises(ProjectError):
                    build_pcb_plan(updated, snapshot_for(updated), runtime_identity(), IFA_SETTINGS if kind == IFA else SETTINGS)
                restored = apply_payload(updated, inverse["payload"])[0]
                for name in ("board", "materials", "stackup", "parameters", "nets", "geometry", "ports", "extensions"):
                    self.assertEqual(restored[name], document[name])

    def test_display_input_is_converted_on_server_and_original_text_is_preserved(self):
        """! @brief mm/deg 표시 문자열과 정규 Quantity를 모두 기록한다."""
        document = base_document()
        data = specification(document, display=True)
        result, payload = preview(document, data)
        self.assertTrue(result["can_apply"], result)
        record = payload["replacement"]
        self.assertEqual(record["requested_inputs"]["radius"], {"value": "6", "unit": "mm"})
        self.assertEqual(record["inputs"]["radius"]["value_si"], 0.006)
        self.assertEqual(record["inputs"]["radius"]["status"], "user_entered")
        self.assertEqual(record["inputs"]["radius"]["source_refs"], [])
        self.assertTrue(all("원호 " in parameter["name"] for parameter in record["objects"]["parameters"].values()))
        for value in ("", "NaN", "Infinity", "not-a-number"):
            bad = deepcopy(data)
            bad["explicit_inputs"]["radius"]["value"] = value
            self.assertFalse(preview(document, bad)[0]["can_apply"])

    def test_arc_zero_closed_inner_radius_and_circle_outside_are_blocked(self):
        """! @brief 원형 bounding box 안의 점도 실제 원 밖이면 거부한다."""
        document = base_document()
        data = specification(document)
        for key, value, unit in (("sweep_angle", 0, "deg"), ("sweep_angle", 360, "deg"), ("sweep_angle", -360, "deg"),
                                 ("radius", 0.3, "mm"), ("feed_start_x", 7, "mm")):
            bad = deepcopy(data)
            bad["explicit_inputs"][key] = quantity(value, unit)
            if key == "feed_start_x":
                bad["explicit_inputs"]["feed_start_y"] = quantity(7, "mm")
            with self.subTest(key=key, value=value):
                result, payload = preview(document, bad)
                self.assertFalse(result["can_apply"], result)
                self.assertIsNone(payload)
        negative = deepcopy(data)
        negative["explicit_inputs"]["sweep_angle"] = quantity(-90, "deg")
        self.assertTrue(preview(document, negative)[0]["can_apply"])

    def test_ifa_short_and_thick_feed_caps_cannot_silently_touch_ground(self):
        """! @brief 작은 패드보다 굵은 feed의 실제 cap과 short 간격까지 확인한다."""
        document = base_document(IFA)
        data = specification(document, IFA)
        modifications = [
            {"short_start_y": 52}, {"feed_start_y": 51},
            {"pad_height": 0.1, "feed_start_y": 50.4},
            {"pad_width": 0.1, "feed_x": 5.8},
            {"radiator_length": 36}, {"short_x": 3},
        ]
        for changes in modifications:
            bad = deepcopy(data)
            for key, value in changes.items():
                bad["explicit_inputs"][key] = quantity(value, "mm")
            with self.subTest(changes=changes):
                self.assertFalse(preview(document, bad)[0]["can_apply"])

    def test_explicit_ports_reach_real_pcb_plan_for_both_cards(self):
        """! @brief 포트/물성을 명시한 두 카드만 실제 순수 solver 계획을 구성한다."""
        for kind in (ARC, IFA):
            with self.subTest(kind=kind):
                document = base_document(kind, keep_ground=kind == ARC)
                data = specification(document, kind)
                data["port"] = port_recipe(document, kind)
                result, payload = preview(document, data)
                self.assertTrue(result["can_apply"], result)
                updated = apply_payload(document, payload)[0]
                settings = IFA_SETTINGS if kind == IFA else {**SETTINGS, "grid_mm": 0.25}
                plan = build_pcb_plan(updated, snapshot_for(updated), runtime_identity(), settings)
                validate_pcb_plan(plan)
                self.assertEqual(plan["case"]["settings"], settings)
                self.assertEqual(plan["source_semantics"]["materials"], document["materials"])
                self.assertEqual(plan["source_semantics"]["extensions"][EXTENSION_KEY], updated["extensions"][EXTENSION_KEY])
                self.assertFalse(plan["model_report"]["physical_validation_state"] == "validated")
                if kind == ARC:
                    invalid = deepcopy(data)
                    invalid["port"]["excitation_box"]["stop"][0] = quantity(2, "mm")
                    self.assertFalse(preview(document, invalid)[0]["can_apply"])

    def test_lower_copper_port_uses_dielectric_contact_surface(self):
        """! @brief 하부 동박의 z_min이 아닌 상부 접면을 PCB 투영과 공유한다."""
        document = base_document(IFA)
        layer = next(item for item in document["stackup"] if item["role"] == "conductor")
        dielectric = next(item for item in document["stackup"] if item["role"] == "dielectric")
        layer.update(order=0, z_min=quantity(-0.035, "mm"))
        dielectric["order"] = 1
        document["stackup"].sort(key=lambda item: item["order"])
        data = specification(document, IFA)
        data["port"] = port_recipe(document, IFA, z=0.0)
        result, payload = preview(document, data)
        self.assertTrue(result["can_apply"], result)
        updated = apply_payload(document, payload)[0]
        plan = build_pcb_plan(updated, snapshot_for(updated), runtime_identity(), IFA_SETTINGS)
        validate_pcb_plan(plan)
        bad = deepcopy(data)
        bad["port"] = port_recipe(document, IFA, z=-0.035)
        self.assertFalse(preview(document, bad)[0]["can_apply"])

    def test_targets_bindings_ids_and_card_hash_are_exact(self):
        """! @brief 선택한 목표 버전이나 카드/바인딩이 다르면 새 기하를 만들지 않는다."""
        document = base_document()
        target = target_input()
        document = apply_command(document, {"command_id": str(uuid4()), "type": "target.set", "payload": {"target": target}}, document["revision_id"])[0]
        data = specification(document)
        data["target_refs"] = [{key: document["targets"][0][key] for key in ("id", "revision_id")}]
        result, payload = preview(document, data)
        self.assertTrue(result["can_apply"], result)
        self.assertEqual(payload["replacement"]["target_snapshots"], document["targets"])
        cases = [("target_refs", [{"id": target["id"], "revision_id": str(uuid4())}]),
                 ("target_refs", data["target_refs"] * 2), ("instance_id", document["project_id"])]
        for key, value in cases:
            bad = deepcopy(data)
            bad[key] = value
            self.assertFalse(preview(document, bad)[0]["can_apply"])
        bad = deepcopy(data)
        bad["binding"]["layer_id"] = str(uuid4())
        self.assertFalse(preview(document, bad)[0]["can_apply"])
        bad = deepcopy(data)
        bad["template"]["content_hash"] = "0" * 64
        self.assertFalse(preview(document, bad)[0]["can_apply"])

    def test_full_explicit_target_samples_survive_known_origin_only(self):
        """! @brief core가 지원하는 1001개 표본을 원본 사본에 보존하고 미지 확장 예산은 유지한다."""
        document = base_document()
        target = target_input()
        frequencies = [Quantity.from_value(2.4e9 + index * 1e5, "Hz").to_dict() for index in range(1001)]
        target["band"]["sampling"] = {"kind": "explicit", "frequencies": frequencies}
        document = apply_command(document, {"command_id": str(uuid4()), "type": "target.set", "payload": {"target": target}}, document["revision_id"])[0]
        before = canonical_bytes(document)
        data = specification(document)
        self.assertTrue(preview(document, data)[0]["can_apply"])
        data["target_refs"] = [{key: document["targets"][0][key] for key in ("id", "revision_id")}]
        result, payload = preview(document, data)
        self.assertTrue(result["can_apply"], result)
        updated = apply_payload(document, payload)[0]
        original = updated["extensions"][EXTENSION_KEY]["instances"][0]
        source = original["source_document"]
        self.assertEqual(original["target_snapshots"], document["targets"])
        self.assertEqual(source["targets"], document["targets"])
        self.assertEqual(len(source["targets"][0]["band"]["sampling"]["frequencies"]), 1001)
        self.assertEqual(canonical_bytes(document), before)
        validate_project(updated)
        for unknown in ({"values": list(range(257))}, {EXTENSION_KEY: {"values": list(range(257))}}):
            bad = deepcopy(updated)
            bad["extensions"]["example:unknown"] = unknown
            with self.assertRaises(ProjectError) as raised:
                validate_project(bad)
            self.assertEqual(raised.exception.code, "E_RESOURCE")
        bad = deepcopy(updated)
        record = bad["extensions"][EXTENSION_KEY]["instances"][0]
        record["source_document"]["targets"][0]["band"]["sampling"]["frequencies"].append(Quantity.from_value(2.5e9, "Hz").to_dict())
        record["source_document_hash"] = canonical_hash(record["source_document"])
        record["record_hash"] = record_hash(record)
        with self.assertRaises(ProjectError) as raised:
            validate_project(bad)
        self.assertEqual(raised.exception.code, "E_RESOURCE")

    def test_explicit_sample_allowance_does_not_remove_origin_byte_budget(self):
        """! @brief 표본 수가 합법이어도 큰 출처 원문을 잘라내지 않고 256 KiB 한도로 거부한다."""
        document = base_document()
        target = target_input()
        target["band"]["sampling"] = {"kind": "explicit", "frequencies": [
            Quantity.from_value(2.4e9 + index * 1e5, "Hz", source_refs=["s" * 256]).to_dict() for index in range(1001)]}
        document = apply_command(document, {"command_id": str(uuid4()), "type": "target.set", "payload": {"target": target}}, document["revision_id"])[0]
        before = canonical_bytes(document)
        self.assertLess(len(before), 512 * 1024)
        result, payload = preview(document, specification(document))
        self.assertFalse(result["can_apply"], result)
        self.assertIsNone(payload)
        self.assertEqual(result["issues"][0]["code"], "E_RESOURCE")
        self.assertEqual(result["issues"][0]["details"]["field_path"], "template_origin")
        self.assertIn("256 KiB", result["issues"][0]["message"])
        self.assertEqual(canonical_bytes(document), before)

    def test_direct_edits_and_deletions_preserve_frozen_origin(self):
        """! @brief 현재 기하 편집이 과거 원본 exact-match 조건에 막히지 않는다."""
        document = base_document()
        data = specification(document)
        updated = apply_payload(document, preview(document, data)[1])[0]
        frozen = deepcopy(updated["extensions"][EXTENSION_KEY])
        identity = object_id(data["instance_id"], "parameter:radius")
        parameter = deepcopy(updated["parameters"][identity])
        parameter["quantity"] = quantity(6.5, "mm")
        edited = apply_command(updated, {"command_id": str(uuid4()), "type": "parameter.set", "payload": parameter}, updated["revision_id"])[0]
        self.assertEqual(edited["extensions"][EXTENSION_KEY], frozen)
        self.assertTrue(instance_status(edited, frozen["instances"][0])["changes"])
        shape_id = object_id(data["instance_id"], "feed")
        deleted = apply_command(edited, {"command_id": str(uuid4()), "type": "geometry.remove", "payload": {"id": shape_id}}, edited["revision_id"])[0]
        self.assertEqual(deleted["extensions"][EXTENSION_KEY], frozen)
        self.assertIn("removed", [item["status"] for item in instance_status(deleted, frozen["instances"][0])["changes"]])
        validate_project(deleted)

    def test_rehashed_malformed_origin_is_not_an_allowed_execution_extension(self):
        """! @brief hash만 다시 계산한 잘못된 nested source/Quantity/객체/포트를 거부한다."""
        document = base_document()
        data = specification(document)
        updated = apply_payload(document, preview(document, data)[1])[0]
        for mode in ("source", "descriptor", "bool", "quantity", "geometry", "port", "nested_origin", "duplicate_target"):
            changed = deepcopy(updated)
            record = changed["extensions"][EXTENSION_KEY]["instances"][0]
            if mode == "source":
                record["card"]["source"] = []
            elif mode == "descriptor":
                record["card"]["input_fields"][0] = {"key": "wrong"}
            elif mode == "bool":
                record["card"]["support"]["geometry_generator"] = 1
            elif mode == "quantity":
                next(iter(record["objects"]["parameters"].values()))["quantity"]["display_unit"] = "GHz"
            elif mode == "geometry":
                record["objects"]["geometry"][0]["unknown"] = True
            elif mode == "port":
                record["port_recipe"] = []
            elif mode == "nested_origin":
                record["source_document"]["extensions"] = {EXTENSION_KEY: {"schema": "nested"}}
            else:
                record["target_snapshots"] = [{"id": str(uuid4()), "revision_id": str(uuid4())}] * 2
            record["card"]["content_hash"] = canonical_hash({key: value for key, value in record["card"].items() if key != "content_hash"})
            record["source_document_hash"] = canonical_hash(record["source_document"])
            record["record_hash"] = record_hash(record)
            with self.subTest(mode=mode), self.assertRaises(ProjectError):
                validate_project(changed)

    def test_inverse_keeps_unrelated_parameters_targets_and_extensions(self):
        """! @brief 템플릿 제거가 관련 없는 사용자 입력이나 확장을 덮어쓰지 않는다."""
        document = base_document()
        document["extensions"]["vendor.note"] = {"counter": 7, "source": "existing-user-data"}
        data = specification(document)
        updated, _, _, inverse = apply_payload(document, preview(document, data)[1])
        identity = str(uuid4())
        updated = apply_command(updated, {"command_id": str(uuid4()), "type": "parameter.set", "payload": {
            "id": identity, "name": "사용자 독립 입력", "quantity": quantity(3, "mm")}}, updated["revision_id"])[0]
        target = target_input()
        updated = apply_command(updated, {"command_id": str(uuid4()), "type": "target.set", "payload": {"target": target}}, updated["revision_id"])[0]
        restored = apply_payload(updated, inverse["payload"])[0]
        self.assertEqual(restored["parameters"][identity], updated["parameters"][identity])
        self.assertEqual(restored["targets"], updated["targets"])
        self.assertEqual(restored["extensions"], document["extensions"])


class TemplateServiceCase(unittest.TestCase):
    """! @brief 기존 저장소/공개 RPC를 사용하는 템플릿 통합 시험의 준비를 공유한다."""

    def setUp(self):
        """! @brief 실제 프로젝트 저장소를 worker 없이 준비한다."""
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.service = ProjectService(self.workspace, auto_run=False)
        opened = self.complete("project.open", {"path": "projects/template", "open_mode": "create", "name": "템플릿"}, context={})
        self.project_id, self.revision = opened["project_id"], opened["revision_id"]
        source = base_document(IFA, missing=True)
        source["board"]["frame_id"] = opened["document"]["frames"]["board"]["id"]
        self.command("board.set", {"board": source["board"]})
        for kind, collection in (("material", "materials"), ("layer", "stackup")):
            for item in source[collection]:
                self.command(kind + ".set", {kind: item})

    def tearDown(self):
        """! @brief 저장소 잠금과 임시 파일을 해제한다."""
        self.service.close()
        self.temp.cleanup()

    def request(self, data, *, mutation=True, context=None):
        """! @brief GUI/자동화와 동일한 공개 요청 envelope를 만든다."""
        result = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project_id} if context is None else context, "input": data}
        if mutation:
            result.update(request_key=str(uuid4()), request_key_epoch=self.service.policy()["request_key_epoch"])
        return result

    def rpc(self, method, params):
        """! @brief JSON RPC 직렬화와 공개 dispatch를 실제로 통과한다."""
        response = handle_frame(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(), self.service)
        self.assertNotIn("error", response, response)
        return response["result"]

    def complete(self, method, data, context=None):
        """! @brief 자료 처리 작업의 접수와 완료를 구분한다."""
        task = self.rpc(method, self.request(data, context=context))
        self.assertTrue(self.service.run_next())
        status = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def command(self, kind, payload):
        """! @brief 기존 설계 명령으로만 준비 입력을 설치한다."""
        result = self.rpc("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": kind, "payload": payload}))
        self.revision = result["new_revision"]
        return result

    def document(self):
        """! @brief 저장된 현재 문서를 공개 open 경로로 조회한다."""
        return self.complete("project.open", {"open_mode": "open", "path": "projects/template"}, context={})["document"]


class TemplateServiceTests(TemplateServiceCase):
    """! @brief 공개 RPC와 실제 저장소의 이력/멱등/실패 경계를 검사한다."""

    def test_public_preview_apply_save_restart_undo_redo_and_duplicate(self):
        """! @brief 단일 적용/재접수/재시작 후 inverse가 생성 당시 사본을 복원한다."""
        document = self.document()
        data = specification(document, IFA, display=True)
        before = self.service.journal.read()
        context = self.rpc("template.context", self.request({"expected_revision": self.revision}, mutation=False))
        self.assertEqual(context["board"]["id"], document["board"]["id"])
        self.assertTrue({ARC, IFA}.issubset({card["template_id"] for card in context["cards"]}))
        first = self.rpc("template.synthesize", self.request(data, mutation=False))
        self.assertTrue(first["can_apply"], first)
        self.assertEqual(self.service.journal.read(), before)
        apply = self.request({**data, "command_id": str(uuid4()), "preview_hash": first["preview_hash"]})
        result = self.rpc("template.apply", apply)
        self.revision = result["new_revision"]
        self.assertEqual(result["history"]["undo_count"], len(before["projects"][self.project_id]["history"]["undo"]) + 1)
        self.assertEqual(self.rpc("template.apply", apply), result)
        snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})
        raw = self.service.journal.read_artifact(snapshot["artifact"])
        self.complete("project.save", {"expected_revision": self.revision})
        expected = self.document()
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.assertEqual(self.document(), expected)
        self.assertEqual(self.rpc("template.apply", apply), result)
        with patch("rfad.templates.cards.describe_card", side_effect=RuntimeError("라이브러리 조회 금지")):
            for method in ("project.undo", "project.redo"):
                moved = self.rpc(method, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
                self.revision = moved["new_revision"]
        restored = self.document()
        for key in ("parameters", "geometry", "nets", "ports", "extensions", "materials", "stackup"):
            self.assertEqual(restored[key], expected[key])
        self.assertEqual(self.service.journal.read_artifact(snapshot["artifact"]), raw)

    def test_changed_preview_stale_context_and_raw_internal_command_do_not_write(self):
        """! @brief 공개 우회 명령과 검토 후 달라진 입력을 원자 거부한다."""
        data = specification(self.document(), IFA)
        first = self.rpc("template.synthesize", self.request(data, mutation=False))
        before = self.service.journal.read()
        bad = deepcopy(data)
        bad["explicit_inputs"]["radiator_length"] = quantity(25, "mm")
        for method, params in (
            ("template.apply", self.request({**bad, "command_id": str(uuid4()), "preview_hash": first["preview_hash"]})),
            ("template.context", self.request({"expected_revision": str(uuid4())}, mutation=False)),
            ("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": "template_instance.apply", "payload": {}})),
        ):
            response = handle_frame(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(), self.service)
            self.assertIn("error", response)
            self.assertEqual(self.service.journal.read(), before)

    def test_failed_publish_leaves_no_partial_geometry_history_or_receipt(self):
        """! @brief 디스크 게시 실패 후 모든 생성 객체와 근거는 이전 상태로 남는다."""
        data = specification(self.document(), IFA)
        first = self.rpc("template.synthesize", self.request(data, mutation=False))
        params = self.request({**data, "command_id": str(uuid4()), "preview_hash": first["preview_hash"]})
        before = self.service.journal.read()
        def fail(stage):
            """! @brief 원자 pointer 게시 직전에 실제 저장 실패를 주입한다."""
            if stage == "before_publish":
                raise OSError("injected template disk failure")
        self.service.journal.fault_hook = fail
        with self.assertRaises(ProjectError):
            self.service.mutate("template.apply", params)
        self.service.journal.fault_hook = None
        self.assertEqual(self.service.journal.read(), before)
        result = self.rpc("template.apply", params)
        self.assertNotEqual(result["new_revision"], self.revision)
