"""! @brief 추가 문헌의 치수, 초기식 적용 범위와 원자 보존 및 실패 반례를 검사한다."""

from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.cad import build_cad_input
from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.domain.template_instance import EXTENSION_KEY, record_hash, instance_status
from rfad.templates.cards import describe_card, validate_card_snapshot
from rfad.templates import printed_references as printed
from test_pcb_solver import snapshot_for
from test_template_candidates import base_document, IFA, preview, apply_payload, TemplateServiceCase


def printed_input(document, identity=printed.MONOPOLE, *, recipe=None):
    """! @brief 원문 치수와 사용자 배치, 초기식 입력을 각각 명시한다."""
    card = describe_card(identity)
    layer = next(item for item in document["stackup"] if item["role"] == "conductor")
    inputs = {key: {"source": "card"} for key in card["reference_inputs"]}
    inputs.update(offset_x={"value": "10", "unit": "mm"}, offset_y={"value": "10", "unit": "mm"})
    data = {"expected_revision": document["revision_id"], "mode": "explicit_geometry",
            "template": {key: card[key] for key in ("template_id", "version", "content_hash")},
            "instance_id": str(uuid4()), "target_refs": [], "binding": {
                "board_id": document["board"]["id"], "frame_id": document["board"]["frame_id"],
                "layer_id": layer["id"], "material_id": layer["material_id"]}, "explicit_inputs": inputs, "port": None}
    if recipe is not None:
        data["mode"] = "initial_estimate"
        data["explicit_inputs"]["length"] = {"source": "initial_estimate"}
        data["seed"] = {"recipe_id": recipe, "frequency": {"value": "2.45", "unit": "GHz"},
                        "assumption": "시험: 선택한 source 조건을 가정하며 실제 납품 물성은 미정"}
    return data


class PrintedReferenceTests(unittest.TestCase):
    """! @brief 원문 일부와 초기 추정을 계산/실측 재현으로 승격하지 않는 경계를 확인한다."""

    def test_original_pdf_hashes_and_closed_card_snapshots(self):
        """! @brief 실제 PDF bytes를 확인하고 변조한 초기식과 source 사본을 차단한다."""
        repository = Path(__file__).resolve().parents[2]
        for identity in printed.IDENTITIES:
            card = describe_card(identity)
            validate_card_snapshot(card)
            source = card["evidence"]
            if (repository / source["path"]).is_file():
                self.assertEqual(hashlib.sha256((repository / source["path"]).read_bytes()).hexdigest(), source["sha256"])
            bad = deepcopy(card)
            bad["evidence"]["whole_board_reproduced"] = True
            bad["content_hash"] = canonical_hash({key: value for key, value in bad.items() if key != "content_hash"})
            with self.assertRaises(ProjectError):
                validate_card_snapshot(bad)

    def test_three_cards_preserve_source_and_unknown_materials_on_real_geometry(self):
        """! @brief source 값은 부분 사각 도체가 되며 보드/적층/미정 물성과 포트를 유지한다."""
        for identity in printed.IDENTITIES:
            document = base_document(IFA, missing=True)
            before = canonical_bytes(document)
            result, payload = preview(document, printed_input(document, identity))
            self.assertTrue(result["can_apply"], result)
            self.assertEqual(canonical_bytes(document), before)
            self.assertEqual(result["generation"]["analysis"], "not_performed")
            updated = apply_payload(document, payload)[0]
            for name in ("board", "stackup", "materials", "ports"):
                self.assertEqual(updated[name], document[name])
            self.assertEqual(len(updated["geometry"]), 1 if identity == printed.MONOPOLE else 3)
            self.assertTrue(all(item["kind"] == "planar_region" for item in updated["geometry"]))
            self.assertEqual(build_cad_input(updated, snapshot_for(updated))["source_semantics"], updated)
            with patch("rfad.templates.cards.describe_card", side_effect=RuntimeError("현재 카드 조회 금지")):
                validate_project(updated)

    def test_an1088_dimensions_and_variant_conflict_are_preserved(self):
        """! @brief 도면의 inch 배율, 내부 gap과 0.8 mm/0.034 inch 불일치를 독립 기대값으로 확인한다."""
        for identity, length, gap, clearance in ((printed.IFA_62MIL, 19.8628, 2.7686, 8.3058),
                                                  (printed.IFA_08MM, 21.844, 2.921, 7.8994)):
            document = base_document(IFA)
            result, payload = preview(document, printed_input(document, identity))
            self.assertTrue(result["can_apply"], result)
            updated = apply_payload(document, payload)[0]
            record = payload["replacement"]
            for key, expected in (("arm_length", length), ("inner_gap", gap), ("arm_clearance", clearance), ("arm_width", 0.9906)):
                self.assertAlmostEqual(record["inputs"][key]["value_si"] * 1000, expected, places=10)
            shapes = {item["role"]: item for item in updated["geometry"]}
            def x(shape, index):
                """! @brief 생성 도체의 실제 좌표 참조를 소비한다."""
                return resolve_scalar(updated, shape["outer"][index][0], "length", "test").value_si * 1000
            self.assertAlmostEqual(x(shapes["feed"], 0) - x(shapes["short"], 1), gap, places=10)
            self.assertEqual(bool(record["card"]["evidence"]["source_conflicts"]), identity == printed.IFA_08MM)

    def test_source_23mm_estimate_is_distinct_from_c0_formula_and_trim_allowance(self):
        """! @brief 원문 반올림 23 mm와 정확한 SI c0 산술의 시작/20%/30% 값을 섞지 않는다."""
        document = base_document(IFA, missing=True)
        for recipe, expected in (("ideal_quarter_wave", 0.030591067142857142), ("nwp008_base", 0.022943300357142857),
                                  ("nwp008_trim20", 0.027531960428571426), ("nwp008_trim30", 0.029826290464285716)):
            result, payload = preview(document, printed_input(document, recipe=recipe))
            self.assertTrue(result["can_apply"], result)
            estimate = result["initial_estimate"]
            self.assertAlmostEqual(estimate["length"]["value_si"], expected, places=15)
            self.assertEqual(estimate["length"]["status"], "estimated")
            self.assertFalse(estimate["conditions_verified"])
            self.assertEqual(result["generation"]["geometry"]["source_dimensions"], "estimated")
            self.assertEqual(estimate["source_rounded_length_mm"], 23)
            self.assertEqual(payload["replacement"]["inputs"]["length"], estimate["length"])
            self.assertEqual(payload["replacement"]["card"]["reference_inputs"]["length"]["quantity"]["value_si"], 0.023)
            validate_project(apply_payload(document, payload)[0])

    def test_frequency_units_limits_and_source_scope_are_enforced(self):
        """! @brief 일반 f>0 산술과 원문 한 점의 배율을 구분하고 범위를 임의 확대하지 않는다."""
        document = base_document(IFA)
        data = printed_input(document, recipe="nwp008_base")
        first = preview(document, data)[0]
        equivalent = deepcopy(data)
        equivalent["seed"]["frequency"] = {"value": "2450", "unit": "MHz"}
        self.assertEqual(first["initial_estimate"]["length"], preview(document, equivalent)[0]["initial_estimate"]["length"])
        for value in ("0", "-1", "NaN", "2.4", "5.8"):
            bad = deepcopy(data)
            bad["seed"]["frequency"]["value"] = value
            self.assertFalse(preview(document, bad)[0]["can_apply"])
        ideal = printed_input(document, recipe="ideal_quarter_wave")
        ideal["seed"]["frequency"] = {"value": "5.8", "unit": "GHz"}
        self.assertTrue(preview(document, ideal)[0]["can_apply"])

    def test_round_board_checks_all_sharp_rectangle_corners(self):
        """! @brief 세 부분 기하가 원형 보드에서도 실제 사각 모서리의 경계를 검사한다."""
        document = base_document()
        document["board"]["outline"]["radius"]["value_si"] = 0.03
        original = deepcopy(document)
        for identity in printed.IDENTITIES:
            data = printed_input(document, identity)
            data["explicit_inputs"].update(offset_x={"value": "0", "unit": "mm"},
                                           offset_y={"value": "0", "unit": "mm"})
            result, payload = preview(document, data)
            self.assertTrue(result["can_apply"], result)
            validate_project(apply_payload(document, payload)[0])
            data["explicit_inputs"]["offset_x"] = {"value": "29", "unit": "mm"}
            self.assertFalse(preview(document, data)[0]["can_apply"])
        self.assertEqual(document, original)

    def test_unreviewed_assumptions_recipe_dimension_and_invalid_connections_block(self):
        """! @brief 가정 누락/미지원식/숫자 덮어쓰기 및 source 선폭 위반을 조용히 무시하지 않는다."""
        document = base_document(IFA)
        data = printed_input(document, recipe="nwp008_trim20")
        variants = []
        for key, value in (("assumption", ""), ("recipe_id", "arbitrary_model"), ("assumption", "x" * 513)):
            bad = deepcopy(data)
            bad["seed"][key] = value
            variants.append(bad)
        for key, value in (("length", {"source": "card"}), ("width", {"value": "2", "unit": "mm"})):
            bad = deepcopy(data)
            bad["explicit_inputs"][key] = value
            variants.append(bad)
        bad = printed_input(document, printed.IFA_62MIL)
        bad["explicit_inputs"]["inner_gap"] = {"value": "100", "unit": "mm"}
        variants.append(bad)
        for bad in variants:
            self.assertFalse(preview(document, bad)[0]["can_apply"])

    def test_rehashed_estimate_or_object_tamper_is_rejected(self):
        """! @brief 해시 재작성으로 잘못된 계산이나 검증 상태를 주입할 수 없다."""
        document = base_document(IFA)
        _, payload = preview(document, printed_input(document, recipe="nwp008_base"))
        for field, value in (("conditions_verified", True), ("base_length_m", 0.03), ("c0_m_per_s", 3e8)):
            bad = deepcopy(payload)
            record = bad["replacement"]
            record["initial_estimate"][field] = value
            record["record_hash"] = record_hash(record)
            with self.assertRaises(ProjectError):
                apply_payload(document, bad)


class PrintedSeedServiceTests(TemplateServiceCase):
    """! @brief 실제 RPC와 저장소의 검토 hash/멱등/과거 사본/실행 취소를 확인한다."""

    def test_estimate_atomic_apply_restart_and_history_preserve_unknowns(self):
        """! @brief 현재 카드/PDF 없이 과거 source/계산/입력을 정확히 재열고 undo/redo한다."""
        document = self.document()
        data = printed_input(document, recipe="nwp008_trim30")
        before = self.service.journal.read()
        result = self.rpc("template.synthesize", self.request(data, mutation=False))
        self.assertTrue(result["can_apply"], result)
        self.assertEqual(self.service.journal.read(), before)
        request = self.request({**data, "command_id": str(uuid4()), "preview_hash": result["preview_hash"]})
        changed = deepcopy(request)
        changed["input"]["seed"]["recipe_id"] = "nwp008_base"
        with self.assertRaises(ProjectError):
            self.service.mutate("template.apply", changed)
        self.assertEqual(self.service.journal.read(), before)
        applied = self.rpc("template.apply", request)
        self.revision = applied["new_revision"]
        self.assertEqual(self.rpc("template.apply", request), applied)
        expected = self.document()
        self.complete("project.save", {"expected_revision": self.revision})
        self.service.close()
        from rfad.application.projects import ProjectService
        self.service = ProjectService(self.workspace, auto_run=False)
        with patch("rfad.templates.cards.describe_card", side_effect=RuntimeError("현재 카드 조회 금지")):
            self.assertEqual(self.document(), expected)
            for method in ("project.undo", "project.redo"):
                result = self.rpc(method, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
                self.revision = result["new_revision"]
                source = document if method == "project.undo" else expected
                for name in ("geometry", "parameters", "nets", "materials", "stackup", "ports", "extensions"):
                    self.assertEqual(self.document()[name], source[name])


if __name__ == "__main__":
    unittest.main()
