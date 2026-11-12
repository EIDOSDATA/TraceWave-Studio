"""! @brief 원문 좌표/출처와 현재 설계, 기하 생성 및 RF 검증 상태의 분리를 검사한다."""

from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.cad import build_cad_input
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command, validate_project
from rfad.domain.template_geometry import object_id
from rfad.domain.template_instance import EXTENSION_KEY, record_hash, instance_status
from rfad.templates import g031
from rfad.templates.cards import describe_card, validate_card_snapshot, list_cards
from test_pcb_solver import snapshot_for
from test_template_candidates import (ARC, IFA, base_document, quantity, preview, apply_payload,
                                      TemplateServiceCase)


def literature_input(document, *, x="15", y="15"):
    """! @brief 원문 치수 선택은 명시 marker로, 배치는 사용자 문자열로 전달한다."""
    card = describe_card(g031.IDENTITY)
    layer = next(item for item in document["stackup"] if item["role"] == "conductor")
    inputs = {key: {"source": "card"} for key in card["reference_inputs"]}
    inputs.update(offset_x={"value": x, "unit": "mm"}, offset_y={"value": y, "unit": "mm"})
    return {"expected_revision": document["revision_id"], "mode": "explicit_geometry",
            "template": {key: card[key] for key in ("template_id", "version", "content_hash")},
            "instance_id": str(uuid4()), "target_refs": [],
            "binding": {"board_id": document["board"]["id"], "frame_id": document["board"]["frame_id"],
                        "layer_id": layer["id"], "material_id": layer["material_id"]},
            "explicit_inputs": inputs, "port": None}


class LiteratureDomainTests(unittest.TestCase):
    """! @brief 독립 원문 수치, 연결 방식과 악성 사본 반례를 검사한다."""

    def test_original_archive_members_and_snippets_match_card(self):
        """! @brief 추출 JSON만 신뢰하지 않고 실제 중첩 ZIP의 원문 bytes를 대조한다."""
        code = Path(__file__).resolve().parents[1]
        path = code / "tools/verify_literature_sources.py"
        spec = importlib.util.spec_from_file_location("literature_source_verifier", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not (code.parent / g031.ARCHIVE_PATH).is_file():
            self.skipTest("G031 원본 archive를 포함한 저장소에서 실행합니다.")
        result = module.verify(code.parent)
        self.assertEqual(len(result["members"]), 3)
        self.assertEqual(result["members"][0]["gerber_spans_checked"], 3)
        self.assertFalse(result["whole_board_reproduced"])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / g031.ARCHIVE_PATH
            source.parent.mkdir(parents=True)
            source.write_bytes(b"different source bytes")
            with self.assertRaisesRegex(ValueError, "archive"):
                module.verify(Path(directory))

    def test_source_card_is_versioned_without_changing_old_cards(self):
        """! @brief 기존 0.1 카드와 신규 출처 카드의 schema 및 검증 주장을 구분한다."""
        self.assertTrue({ARC, IFA, g031.IDENTITY}.issubset({card["template_id"] for card in list_cards()}))
        for identity in (ARC, IFA, g031.IDENTITY):
            card = describe_card(identity)
            validate_card_snapshot(card)
            self.assertEqual(card["schema"], g031.SCHEMA if identity == g031.IDENTITY else "rfad.template-card/0.1")
            self.assertFalse(any(value for key, value in card["support"].items() if key != "geometry_generator"))
        card["reference_inputs"]["radius"]["quantity"]["value_si"] = 0
        self.assertGreater(describe_card(g031.IDENTITY)["reference_inputs"]["radius"]["quantity"]["value_si"], 0)

    def test_readable_coordinate_display_preserves_si_and_older_display_snapshot(self):
        """! @brief 원문 좌표를 읽기 쉽게 표시하되 이전 float 문자열 사본의 재열기를 유지한다."""
        card = describe_card(g031.IDENTITY)
        self.assertEqual(card["reference_inputs"]["feed_start_x"]["display_value"], "-6.96976")
        self.assertEqual(card["reference_inputs"]["feed_start_y"]["display_value"], "-5.842")
        before = deepcopy(card["reference_inputs"]["feed_start_x"]["quantity"])
        card["reference_inputs"]["feed_start_x"]["display_value"] = "-6.969760000000001"
        card["content_hash"] = canonical_hash({k: v for k, v in card.items() if k != "content_hash"})
        validate_card_snapshot(card)
        self.assertEqual(card["reference_inputs"]["feed_start_x"]["quantity"], before)
        card["reference_inputs"]["feed_start_x"]["display_value"] = "-6.96"
        card["content_hash"] = canonical_hash({k: v for k, v in card.items() if k != "content_hash"})
        with self.assertRaises(ProjectError):
            validate_card_snapshot(card)

    def test_reference_geometry_matches_native_commands_not_old_arc_feed_rule(self):
        """! @brief 고정 시험 기대값으로 원호 방향/정밀도와 원래 stub 끝점을 검증한다."""
        document = base_document(IFA, missing=True)
        before = canonical_bytes(document)
        data = literature_input(document)
        result, payload = preview(document, data)
        self.assertTrue(result["can_apply"], result)
        self.assertEqual(canonical_bytes(document), before)
        updated = apply_payload(document, payload)[0]
        shapes = {item["role"]: item for item in updated["geometry"]}
        def scalar(value, dimension="length"):
            """! @brief 제품 기하가 실제 소비하는 매개변수 값을 읽는다."""
            return resolve_scalar(updated, value, dimension, "test").value_si
        arc, feed = shapes["radiator"], shapes["feed"]
        self.assertAlmostEqual(scalar(arc["radius"]) * 1000, 9.119930042275543, places=12)
        self.assertAlmostEqual(math.degrees(scalar(arc["start_angle"], "angle")), 106.87043102934852, places=11)
        self.assertAlmostEqual(math.degrees(scalar(arc["sweep_angle"], "angle")), 112.53463398648967, places=11)
        self.assertEqual([scalar(v) for v in arc["center"]], [0.015, 0.015])
        self.assertAlmostEqual(scalar(feed["start"][0]), 0.00803024, places=14)
        self.assertAlmostEqual(scalar(feed["start"][1]), 0.009158, places=14)
        self.assertAlmostEqual(scalar(feed["end"][0]), 0.0099454, places=14)
        self.assertAlmostEqual(scalar(feed["end"][1]), 0.009158, places=14)
        self.assertAlmostEqual(scalar(feed["width"]), 0.00127, places=14)
        record = payload["replacement"]
        self.assertAlmostEqual(record["card"]["evidence"]["endpoint_radius_difference_mm"], 0.0010410245716876432, places=12)
        self.assertEqual(record["inputs"]["radius"]["status"], "source_default")
        self.assertEqual(record["inputs"]["offset_x"]["status"], "user_entered")
        self.assertEqual(record["requested_inputs"]["radius"], {"source": "card"})
        self.assertEqual(updated["board"], document["board"])
        self.assertEqual(updated["materials"], document["materials"])
        self.assertEqual(updated["stackup"], document["stackup"])
        self.assertEqual(updated["ports"], [])
        self.assertEqual(result["generation"]["geometry"]["source_dimensions"], "reference")
        self.assertEqual(result["generation"]["analysis"], "not_performed")
        self.assertEqual(result["generation"]["measurement"], "not_verified")
        self.assertEqual(build_cad_input(updated, snapshot_for(updated))["source_semantics"], updated)

    def test_modified_dimension_keeps_original_and_provenance_without_claiming_reproduction(self):
        """! @brief source_default 원문을 바꿔 보내도 현재 수정값은 사용자 값으로 구분한다."""
        document = base_document(IFA, missing=True)
        data = literature_input(document)
        value = deepcopy(describe_card(g031.IDENTITY)["reference_inputs"]["width"]["quantity"])
        value["value_si"] = 0.0011
        value["source_refs"].append("사용자 검토 근거")
        data["explicit_inputs"]["width"] = value
        result, payload = preview(document, data)
        self.assertTrue(result["can_apply"], result)
        self.assertEqual(result["generation"]["geometry"]["modified_fields"], ["width"])
        record = payload["replacement"]
        self.assertEqual(record["inputs"]["width"]["status"], "user_entered")
        self.assertIn("사용자 검토 근거", record["inputs"]["width"]["source_refs"])
        self.assertEqual(record["card"]["reference_inputs"]["width"]["quantity"]["value_si"], 0.00127)

    def test_missing_placement_disconnected_stub_outside_board_and_port_are_blocked(self):
        """! @brief 미정값/원문 불일치를 clamp하거나 숨은 포트/보드로 보완하지 않는다."""
        document = base_document(IFA, missing=True)
        data = literature_input(document)
        variants = []
        for key, value in (("offset_x", {"value": "", "unit": "mm"}), ("offset_y", {"source": "card"}),
                           ("offset_x", {"value": "0", "unit": "mm"}),
                           ("feed_start_y", {"value": "5", "unit": "mm"}),
                           ("feed_end_x", {"source": "card", "extra": True})):
            bad = deepcopy(data)
            bad["explicit_inputs"][key] = value
            variants.append(bad)
        bad = deepcopy(data)
        bad["port"] = {}
        variants.append(bad)
        for bad in variants:
            with self.subTest(input=bad["explicit_inputs"], port=bad["port"]):
                result, payload = preview(document, bad)
                self.assertFalse(result["can_apply"], result)
                self.assertIsNone(payload)
        circular = base_document(ARC, missing=True)
        circular["board"]["outline"]["radius"] = quantity(10, "mm")
        self.assertTrue(preview(circular, literature_input(circular, x="0", y="0"))[0]["can_apply"])
        self.assertFalse(preview(circular, literature_input(circular, x="-3", y="0"))[0]["can_apply"])

    def test_rehashed_wrong_source_or_generated_copy_is_rejected(self):
        """! @brief 해시만 다시 계산해도 원문 치수/객체 대응 검사를 우회할 수 없다."""
        document = base_document(IFA)
        result, payload = preview(document, literature_input(document))
        self.assertTrue(result["can_apply"], result)
        for variant in ("source", "reference", "object", "status"):
            bad = deepcopy(payload)
            record = bad["replacement"]
            if variant == "source":
                record["card"]["evidence"]["members"][0]["sha256"] = "0" * 64
            elif variant == "reference":
                record["card"]["reference_inputs"]["width"]["quantity"]["value_si"] = 0.001
            elif variant == "status":
                record["card"]["support"]["measured"] = True
            else:
                identity = object_id(record["id"], "parameter:width")
                record["objects"]["parameters"][identity]["quantity"]["value_si"] = 0.001
            card = record["card"]
            card["content_hash"] = canonical_hash({k: v for k, v in card.items() if k != "content_hash"})
            record["record_hash"] = record_hash(record)
            with self.subTest(variant=variant), self.assertRaises(ProjectError):
                apply_payload(document, bad)

    def test_direct_edit_preserves_original_and_runtime_free_validation(self):
        """! @brief 후속 직접 편집은 최초 치수를 바꾸지 않으며 외부 자료 없이 재열 수 있다."""
        document = base_document(IFA)
        _, payload = preview(document, literature_input(document))
        updated = apply_payload(document, payload)[0]
        record = deepcopy(updated["extensions"][EXTENSION_KEY]["instances"][0])
        identity = object_id(record["id"], "parameter:width")
        parameter = deepcopy(updated["parameters"][identity])
        parameter["quantity"] = quantity(1.1, "mm")
        changed = apply_command(updated, {"command_id": str(uuid4()), "type": "parameter.set", "payload": parameter}, updated["revision_id"])[0]
        with patch("rfad.templates.cards.describe_card", side_effect=RuntimeError("현재 카드 조회 금지")):
            validate_project(changed)
        self.assertEqual(changed["extensions"][EXTENSION_KEY]["instances"][0], record)
        self.assertEqual(instance_status(changed, record)["changes"][0]["status"], "modified")


class LiteratureServiceTests(TemplateServiceCase):
    """! @brief 기존 RPC transaction과 저장/멱등/이력 경로에 문헌 후보를 연결한다."""

    def test_literature_apply_restart_history_and_stale_review(self):
        """! @brief 원문/사용자값과 과거 봉인 결과는 재시작/undo/redo 뒤에도 그대로 남는다."""
        original = self.document()
        data = literature_input(original)
        before = self.service.journal.read()
        result = self.rpc("template.synthesize", self.request(data, mutation=False))
        self.assertTrue(result["can_apply"], result)
        self.assertEqual(self.service.journal.read(), before)
        params = self.request({**data, "command_id": str(uuid4()), "preview_hash": result["preview_hash"]})
        bad = deepcopy(params)
        bad["input"]["explicit_inputs"]["offset_x"]["value"] = "16"
        with self.assertRaises(ProjectError):
            self.service.mutate("template.apply", bad)
        self.assertEqual(self.service.journal.read(), before)
        applied = self.rpc("template.apply", params)
        self.revision = applied["new_revision"]
        self.assertEqual(self.rpc("template.apply", params), applied)
        expected = self.document()
        snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})
        sealed = self.service.journal.read_artifact(snapshot["artifact"])
        self.complete("project.save", {"expected_revision": self.revision})
        self.service.close()
        from rfad.application.projects import ProjectService
        self.service = ProjectService(self.workspace, auto_run=False)
        with patch("rfad.templates.cards.describe_card", side_effect=RuntimeError("현재 카드 조회 금지")):
            self.assertEqual(self.document(), expected)
            for method in ("project.undo", "project.redo"):
                moved = self.rpc(method, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
                self.revision = moved["new_revision"]
                document = self.document()
                source = original if method == "project.undo" else expected
                for key in ("board", "materials", "stackup", "geometry", "parameters", "nets", "ports", "extensions"):
                    self.assertEqual(document[key], source[key])
        self.assertEqual(self.service.journal.read_artifact(snapshot["artifact"]), sealed)

    def test_failed_publish_does_not_publish_partial_literature(self):
        """! @brief 원문 사본과 형상 중 일부만 디스크에 게시되는 경로를 차단한다."""
        data = literature_input(self.document())
        previewed = self.rpc("template.synthesize", self.request(data, mutation=False))
        self.assertTrue(previewed["can_apply"], previewed)
        before = self.service.journal.read()
        def fail(stage):
            """! @brief 최종 pointer 게시 직전 실패를 주입한다."""
            if stage == "before_publish":
                raise OSError("문헌 카드 원자 게시 시험")
        self.service.journal.fault_hook = fail
        with self.assertRaises(ProjectError):
            self.service.mutate("template.apply", self.request({**data, "command_id": str(uuid4()), "preview_hash": previewed["preview_hash"]}))
        self.service.journal.fault_hook = None
        self.assertEqual(self.service.journal.read(), before)


if __name__ == "__main__":
    unittest.main()
