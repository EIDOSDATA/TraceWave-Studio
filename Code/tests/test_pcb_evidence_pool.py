"""! @brief 공유 출처의 무손실 저장, 구형 호환과 손상 거절을 검사한다."""

from copy import deepcopy
import json
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_evidence_pool import expand_selection, pool_selection, POOL_SCHEMA
from rfad.domain.pcb_selection import EXTENSION_KEY, validate_selection
from rfad.domain.project import apply_command, validate_project
from test_design import build_design, quantity
from test_pcb_selection_domain import command, evidence, selection


class PcbEvidencePoolTests(unittest.TestCase):
    """! @brief 같은 원문을 공유해도 선택별 채택 기록과 해시가 유지되는지 검사한다."""

    def fixture(self):
        """! @brief 실제 제조 사양과 분리한 반복 출처 이력을 만든다."""
        document = build_design(known_material=True)
        current = selection(document, published=True)
        entry = evidence({"dk": document["materials"][0]["epsilon_r"]["value_si"], "payload": "x" * 3000})
        current["evidence"] = [entry]
        current["decisions"][0]["evidence_id"] = entry["id"]
        history = []
        for _ in range(16):
            previous = deepcopy(current)
            previous["id"] = str(uuid4())
            history.append(previous)
        current["history"] = history
        return document, current

    def test_legacy_is_read_without_rewriting_and_small_selection_stays_legacy(self):
        """! @brief 기존 파일을 읽는 것만으로 저장 형식이나 해시를 바꾸지 않는다."""
        document = build_design(known_material=True)
        legacy = selection(document, published=True)
        before = canonical_bytes(legacy)
        self.assertEqual(expand_selection(legacy), legacy)
        self.assertEqual(pool_selection(legacy), legacy)
        validate_selection(legacy)
        self.assertEqual(canonical_bytes(legacy), before)

    def test_shared_history_roundtrip_and_direct_edit_inverse(self):
        """! @brief 큰 이력의 중복을 줄이고 실제 명령/직접 편집/역명령을 왕복한다."""
        document, original = self.fixture()
        validate_selection(original)
        packed = pool_selection(original)
        self.assertEqual(packed["schema"], POOL_SCHEMA)
        self.assertEqual(len(packed["evidence_pool"]), 1)
        self.assertLess(len(canonical_bytes(packed)), len(canonical_bytes(original)) // 2)
        self.assertEqual(expand_selection(packed), original)
        payload = {key: deepcopy(document[key]) for key in ("materials", "stackup", "ports")}
        payload["selection"] = packed
        updated, _, _, inverse = apply_command(document, command("pcb_stackup.apply", payload), document["revision_id"])
        reopened = json.loads(canonical_bytes(updated))
        validate_project(reopened)
        self.assertEqual(expand_selection(reopened["extensions"][EXTENSION_KEY]), original)
        material = deepcopy(reopened["materials"][0])
        material["epsilon_r"] = quantity(4.7, "1")
        edited, _, _, _ = apply_command(reopened, command("material.set", {"material": material}), reopened["revision_id"])
        self.assertEqual(edited["extensions"][EXTENSION_KEY], packed)
        restored, _, _, _ = apply_command(updated, command(inverse["type"], inverse["payload"]), updated["revision_id"])
        self.assertEqual(restored["extensions"], document["extensions"])

    def test_missing_duplicate_extra_and_corrupt_evidence_are_rejected(self):
        """! @brief 공유 저장으로 바뀌어도 없는 참조와 원문 변조를 허용하지 않는다."""
        _, original = self.fixture()
        packed = pool_selection(original)
        cases = []
        missing = deepcopy(packed)
        missing["evidence_pool"] = []
        cases.append(missing)
        duplicate = deepcopy(packed)
        duplicate["evidence_pool"].append(deepcopy(duplicate["evidence_pool"][0]))
        cases.append(duplicate)
        corrupt = deepcopy(packed)
        corrupt["evidence_pool"][0]["raw_json"] = '{}'
        cases.append(corrupt)
        unused = deepcopy(packed)
        unused["evidence_pool"].append(evidence({"dk": 7.0}))
        cases.append(unused)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ProjectError):
                validate_selection(value)
