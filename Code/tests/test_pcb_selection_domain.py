"""! @brief PCB 선택 출처의 보존, 원자 적용과 기존 직접 편집의 호환성을 검증한다."""

from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.catalog.models import stable_id
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_selection import EXTENSION_KEY, SELECTION_SCHEMA, state_hash, validate_selection
from rfad.domain.pcb_selection_command import apply_stackup_command
from rfad.domain.pcb_selection_evidence import encoded
from rfad.domain.pcb_selection_history import preserve_selection_history
from rfad.domain.project import apply_command, new_project, validate_project
from test_design import build_design, identity, quantity, unknown


CATALOG = {"catalog_id": "catalog:" + "a" * 64, "import_version": "rfad.catalog.import/1",
           "source_canonical_sha256": "b" * 64, "source_index_sha256": "c" * 64}


def command(kind: str, payload: dict) -> dict:
    """! @brief 실제 명령 진입점이 검사하는 새 명령 ID를 발급한다."""
    return {"command_id": str(uuid4()), "type": kind, "payload": payload}


def evidence(value: dict, *, scope: str = "complete", pointers: list | None = None, entity: str = "observations") -> dict:
    """! @brief 카탈로그 생성기와 같은 안정 ID를 가진 작은 출처 사본을 만든다."""
    if scope == "complete" and entity == "observations":
        value = {"record_id": "PCB000001", **value}
    raw = encoded(value)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    locations = [] if pointers is None else pointers
    origin = None if entity == "observations" else {
        "source_id": "SRC001", "path": "data/fabricator_native_metadata/source.json",
        "pointer": "/body/list/0", "sha256": "e" * 64,
    }
    entry = {"entity": entity, "item_id": "PCB000001", "scope": scope, "pointers": locations,
             "original_sha256": digest if scope == "complete" else "d" * 64,
             "snapshot_sha256": digest, "raw_json": raw, "origin": origin}
    entry["id"] = stable_id("evidence", CATALOG["catalog_id"], entry["entity"], entry["item_id"], scope, locations, digest, origin)
    return entry


def selection(document: dict, *, published: bool = False) -> dict:
    """! @brief 적용 당시의 상태 해시와 작은 사용자 채택 기록을 구성한다."""
    material = document["materials"][0] if document["materials"] else None
    result = {"schema": SELECTION_SCHEMA, "id": str(uuid4()), "catalog": deepcopy(CATALOG) if published else None,
              "evidence": [], "decisions": [], "applied_state_sha256": state_hash(document), "notes": ["시험용 선택"]}
    if material is not None:
        entry = evidence({"dk": material["epsilon_r"]["value_si"], "large_id": 4200000000000000001, "missing": None}) if published else None
        result["evidence"] = [entry] if entry else []
        result["decisions"] = [{
            "target": {"collection": "materials", "id": material["id"], "field": "epsilon_r"},
            "basis": "published" if published else "user_assumption", "evidence_id": entry["id"] if entry else None,
            "source_pointer": "/dk" if entry else None, "value_json": encoded(material["epsilon_r"]),
            "reason": "시험 출처를 명시적으로 채택" if published else "시험 입력으로 명시한 사용자 가정",
        }]
    return result


class PcbSelectionDomainTests(unittest.TestCase):
    """! @brief 파일과 카탈로그 없이도 선택이 저장되고 검증되는지 검사한다."""

    def setUp(self):
        """! @brief 원형 외곽과 기존 패턴/포트를 가진 작은 독립 원본을 만든다."""
        self.document = build_design(known_material=True)
        self.document["board"]["outline"] = {"kind": "circle", "center": [quantity(0, "mm"), quantity(0, "mm")],
                                                 "radius": quantity(30, "mm")}
        self.document["extensions"]["example.future"] = {"preserved": [1, None, "값"]}
        validate_project(self.document)

    def payload(self, *, published=True):
        """! @brief 완성 후보만 바꾸며 기존 설계 ID를 그대로 재사용한다."""
        value = {key: deepcopy(self.document[key]) for key in ("materials", "stackup", "ports")}
        value["materials"][0]["epsilon_r"] = quantity(4.2, "1")
        value["stackup"][0]["thickness"] = quantity(36, "um")
        value["selection"] = selection(value, published=published)
        return value

    def test_atomic_apply_inverse_and_roundtrip_preserve_unrelated_design(self):
        """! @brief 출처와 재료/층을 하나의 개정으로 적용하고 정확한 역명령으로 복구한다."""
        original = deepcopy(self.document)
        payload = self.payload()
        updated, changed, invalidation, inverse = apply_command(
            self.document, command("pcb_stackup.apply", payload), self.document["revision_id"])
        self.assertEqual(self.document, original)
        for field in ("board", "geometry", "nets", "parameters", "frames"):
            self.assertEqual(updated[field], original[field])
        self.assertEqual(updated["extensions"]["example.future"], original["extensions"]["example.future"])
        self.assertEqual(updated["extensions"][EXTENSION_KEY], payload["selection"])
        self.assertEqual(state_hash(updated), payload["selection"]["applied_state_sha256"])
        self.assertIn(identity(2), changed)
        self.assertIn("physics", invalidation)
        restored, _, _, redo = apply_command(updated, command(inverse["type"], inverse["payload"]), updated["revision_id"])
        for field in ("materials", "stackup", "ports", "extensions"):
            self.assertEqual(restored[field], original[field])
        replayed, _, _, _ = apply_command(restored, command(redo["type"], redo["payload"]), restored["revision_id"])
        self.assertEqual(replayed["extensions"], updated["extensions"])
        saved = json.loads(canonical_bytes(replayed))
        validate_project(saved)
        large = json.loads(saved["extensions"][EXTENSION_KEY]["evidence"][0]["raw_json"])["large_id"]
        self.assertEqual(large, 4200000000000000001)
        self.assertIs(type(large), int)

    def test_direct_edit_keeps_applied_values_and_stale_selection_undo(self):
        """! @brief 후속 직접 수정은 가능하며 예전 채택값을 현재값으로 덮어쓰지 않는다."""
        selected, _, _, _ = apply_command(self.document, command("pcb_stackup.apply", self.payload()), self.document["revision_id"])
        historical = deepcopy(selected["extensions"][EXTENSION_KEY])
        material = deepcopy(selected["materials"][0])
        material["epsilon_r"] = quantity(4.4, "1")
        edited, _, _, _ = apply_command(selected, command("material.set", {"material": material}), selected["revision_id"])
        self.assertEqual(edited["extensions"][EXTENSION_KEY], historical)
        self.assertNotEqual(state_hash(edited), historical["applied_state_sha256"])
        self.assertEqual(json.loads(historical["decisions"][0]["value_json"])["value_si"], 4.2)
        replacement = {key: deepcopy(edited[key]) for key in ("materials", "stackup", "ports")}
        replacement["selection"] = selection(replacement)
        second, _, _, inverse = apply_command(edited, command("pcb_stackup.apply", replacement), edited["revision_id"])
        undone, _, _, _ = apply_command(second, command(inverse["type"], inverse["payload"]), second["revision_id"])
        self.assertEqual(undone["extensions"][EXTENSION_KEY], historical)
        self.assertEqual(undone["materials"], edited["materials"])
        validate_project(undone)

    def test_invalid_reference_or_overlapping_layer_never_changes_input(self):
        """! @brief 층/재료 참조와 겹침 오류가 출처나 설계를 부분 변경하지 않는다."""
        cases = []
        missing_layer = self.payload()
        missing_layer["stackup"][0]["id"] = str(uuid4())
        cases.append(missing_layer)
        missing_material = self.payload()
        missing_material["materials"] = []
        cases.append(missing_material)
        overlapping = self.payload()
        extra = deepcopy(overlapping["stackup"][0])
        extra.update(id=str(uuid4()), name="겹치는 층", order=1)
        overlapping["stackup"].append(extra)
        cases.append(overlapping)
        for payload in cases:
            with self.subTest(payload=payload):
                before = deepcopy(self.document)
                with self.assertRaises(ProjectError):
                    apply_stackup_command(self.document, payload)
                self.assertEqual(self.document, before)

    def test_port_coordinates_only_and_inverse_can_remove_added_box(self):
        """! @brief 포트 의미를 유지한 좌표 추가/수정/제거만 원자 명령에서 허용한다."""
        payload = self.payload()
        payload["ports"][0]["excitation_box"] = {
            "start": [quantity(1, "mm"), quantity(1, "mm"), quantity(0.018, "mm")],
            "stop": [quantity(1, "mm"), quantity(3, "mm"), quantity(0.018, "mm")],
        }
        payload["selection"]["applied_state_sha256"] = state_hash(payload)
        updated, _, _, inverse = apply_command(self.document, command("pcb_stackup.apply", payload), self.document["revision_id"])
        restored, _, _, _ = apply_command(updated, command(inverse["type"], inverse["payload"]), updated["revision_id"])
        self.assertNotIn("excitation_box", restored["ports"][0])
        for field, value in (("direction", [1.0, 0.0, 0.0]), ("direction", [0, 1, 0]),
                             ("name", "이름 변경"), ("id", str(uuid4()))):
            invalid = deepcopy(payload)
            invalid["ports"][0][field] = value
            before = deepcopy(self.document)
            with self.subTest(field=field), self.assertRaises(ProjectError):
                apply_stackup_command(self.document, invalid)
            self.assertEqual(self.document, before)
        invalid = deepcopy(payload)
        invalid["ports"] = []
        with self.assertRaises(ProjectError):
            apply_stackup_command(self.document, invalid)

    def test_legacy_read_is_unchanged_and_command_promotes_to_current_schema(self):
        """! @brief 0.1 원본을 암묵 변경하지 않고 새 명령 개정만 0.2로 승격한다."""
        legacy = new_project("과거 프로젝트")
        legacy["schema_version"] = "rfad.project/0.1"
        before = deepcopy(legacy)
        validate_project(legacy)
        self.assertEqual(legacy, before)
        payload = {"materials": [], "stackup": [], "ports": [], "selection": selection(legacy)}
        updated, _, _, inverse = apply_command(legacy, command("pcb_stackup.apply", payload), legacy["revision_id"])
        self.assertEqual(legacy, before)
        self.assertEqual(updated["schema_version"], "rfad.project/0.2")
        self.assertEqual(inverse["payload"]["selection"], None)

    def test_published_evidence_hash_pointer_and_value_are_checked(self):
        """! @brief 직접 채택값을 변경하거나 출처/포인터를 바꾼 위조 기록을 거부한다."""
        valid = self.payload()["selection"]
        validate_selection(valid)
        cases = []
        for field, value in (("original_sha256", "0" * 64), ("snapshot_sha256", "0" * 64), ("id", "evidence:" + "0" * 64)):
            invalid = deepcopy(valid)
            invalid["evidence"][0][field] = value
            cases.append(invalid)
        changed = deepcopy(valid)
        changed["decisions"][0]["value_json"] = encoded(quantity(4.3, "1"))
        cases.append(changed)
        for location in ("/absent", "/missing", "/bad~escape"):
            changed = deepcopy(valid)
            changed["decisions"][0]["source_pointer"] = location
            cases.append(changed)
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ProjectError):
                validate_selection(invalid)

    def test_projection_keeps_missing_and_nested_typed_values(self):
        """! @brief 부분 사본은 null/미제공을 구분하고 포함된 상위 객체의 포인터도 해석한다."""
        copied = evidence({"values": {"/group": {"dk": 4.2, "null": None}}, "missing": ["/absent"]},
                          scope="projection", pointers=["/absent", "/group"])
        valid = self.payload()["selection"]
        valid["evidence"] = [copied]
        valid["decisions"][0].update(evidence_id=copied["id"], source_pointer="/group/dk")
        validate_selection(valid)
        invalid = deepcopy(valid)
        invalid["evidence"][0]["pointers"] = ["/group"]
        with self.assertRaises(ProjectError):
            validate_selection(invalid)

    def test_named_numeric_millimetres_are_checked_in_si(self):
        """! @brief 출처의 명시 mm를 한 번만 SI로 바꾸며 임의 단위 추정을 거부한다."""
        copied = evidence({"dielectricThick": 0.1}, entity="native_components")
        valid = self.payload()["selection"]
        valid["evidence"] = [copied]
        valid["decisions"] = [{"target": {"collection": "stackup", "id": identity(3), "field": "thickness"},
                               "basis": "published", "evidence_id": copied["id"], "source_pointer": "/dielectricThick",
                               "value_json": encoded(quantity(0.1, "mm")), "reason": "명목 mm 출처"}]
        validate_selection(valid)
        valid["decisions"][0]["value_json"] = encoded(quantity(0.1, "m"))
        with self.assertRaises(ProjectError):
            validate_selection(valid)

    def test_jlc_template_projection_allows_only_declared_component_thickness_path(self):
        """! @brief 묶음 template 출처의 명시 행 번호와 두께 필드만 mm로 해석한다."""
        for location, supported in (("/basicDataList/0/dielectricThick", True),
                                    ("/basicDataList/12/dielectricThick", True),
                                    ("/basicDataList/01/dielectricThick", False),
                                    ("/basicDataList/-1/dielectricThick", False),
                                    ("/other/0/dielectricThick", False)):
            with self.subTest(location=location):
                copied = evidence({"values": {location: 0.1}, "missing": []}, scope="projection",
                                  pointers=[location], entity="native_templates")
                valid = self.payload()["selection"]
                valid["evidence"] = [copied]
                valid["decisions"] = [{"target": {"collection": "stackup", "id": identity(3), "field": "thickness"},
                                       "basis": "published", "evidence_id": copied["id"], "source_pointer": location,
                                       "value_json": encoded(quantity(0.1, "mm")), "reason": "JLC 명목 mm 출처"}]
                if supported:
                    validate_selection(valid)
                else:
                    with self.assertRaises(ProjectError):
                        validate_selection(valid)

    def test_native_origin_is_required_bound_to_identity_and_package_relative(self):
        """! @brief 원시 출처의 파일 해시와 포인터를 보존하고 위치 변경을 검출한다."""
        valid = self.payload()["selection"]
        copied = evidence({"dielectricThick": 0.1})
        copied.update(entity="native_components", item_id="native_component:" + "f" * 64,
                      origin={"source_id": "SRC001", "path": "data/fabricator_native_metadata/source.json",
                              "pointer": "/body/list/0/basicDataList/1", "sha256": "e" * 64})
        copied["id"] = stable_id("evidence", CATALOG["catalog_id"], copied["entity"], copied["item_id"],
                                 copied["scope"], copied["pointers"], copied["snapshot_sha256"], copied["origin"])
        valid["evidence"], valid["decisions"] = [copied], []
        validate_selection(valid)
        for origin in (None, copied["origin"] | {"path": "../outside.json"},
                       copied["origin"] | {"pointer": "/body/list/1"}, copied["origin"] | {"sha256": "0" * 64}):
            invalid = deepcopy(valid)
            invalid["evidence"][0]["origin"] = origin
            with self.subTest(origin=origin), self.assertRaises(ProjectError):
                validate_selection(invalid)

    def test_missing_and_override_require_truthful_state_and_reason(self):
        """! @brief 미정값을 숫자로 채택하거나 수정 이유를 누락할 수 없다."""
        valid = self.payload()["selection"]
        decision = valid["decisions"][0]
        decision.update(basis="missing", evidence_id=None, source_pointer=None, value_json=encoded(unknown("dimensionless", "1")), reason="")
        validate_selection(valid)
        decision["value_json"] = encoded(quantity(4.2, "1"))
        with self.assertRaises(ProjectError):
            validate_selection(valid)
        decision.update(basis="user_override", reason="", source_pointer=None)
        with self.assertRaises(ProjectError):
            validate_selection(valid)
        decision["reason"] = "사용자가 별도로 지정한 시험값"
        validate_selection(valid)

    def test_extension_version_types_budgets_and_unknown_extensions(self):
        """! @brief 알려진 확장은 엄격히 검사하고 다른 확장은 기존 정책으로 보존한다."""
        valid = self.payload()["selection"]
        for field, value in (("schema", "rfad.pcb-selection/99"), ("catalog", {}), ("evidence", {}),
                             ("decisions", {}), ("notes", [False]), ("applied_state_sha256", "bad")):
            invalid = deepcopy(valid)
            invalid[field] = value
            with self.subTest(field=field), self.assertRaises(ProjectError):
                validate_selection(invalid)
        oversized = deepcopy(valid)
        oversized["evidence"][0]["raw_json"] = encoded({"long": "a" * 4100})
        with self.assertRaises(ProjectError) as caught:
            validate_selection(oversized)
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        document = deepcopy(self.document)
        document["extensions"][EXTENSION_KEY] = valid
        validate_project(document)
        self.assertIn("example.future", document["extensions"])

    def test_stale_revision_and_unsupported_payload_do_not_mutate(self):
        """! @brief 원자 적용도 기존 개정 보호와 정확한 payload 필드 계약을 따른다."""
        before = deepcopy(self.document)
        with self.assertRaises(ProjectError) as caught:
            apply_command(self.document, command("pcb_stackup.apply", self.payload()), str(uuid4()))
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        invalid = self.payload()
        invalid["board"] = deepcopy(self.document["board"])
        with self.assertRaises(ProjectError):
            apply_stackup_command(self.document, invalid)
        self.assertEqual(self.document, before)

    def test_history_keeps_live_evidence_and_flattens_only_needed_prior_choices(self):
        """! @brief 재선택해도 살아 있는 출처를 잃지 않고 불필요한 과거 선택은 제거한다."""
        first = deepcopy(self.document)
        first_choice = selection(first, published=True)
        source_id = first_choice["evidence"][0]["id"]
        first["materials"][0]["source_refs"] = [source_id]
        first["extensions"][EXTENSION_KEY] = first_choice
        candidate = deepcopy(first)
        next_choice = selection(candidate)
        before = deepcopy((first, candidate, next_choice))
        saved = preserve_selection_history(first, candidate, next_choice)
        self.assertEqual(saved["history"], [first_choice])
        self.assertEqual((first, candidate, next_choice), before)
        candidate["extensions"][EXTENSION_KEY] = saved
        validate_project(candidate)
        third_choice = selection(candidate)
        third = preserve_selection_history(candidate, candidate, third_choice)
        self.assertEqual(third["history"], [first_choice])
        self.assertNotIn("history", third["history"][0])
        cleaned = deepcopy(candidate)
        cleaned["materials"][0]["source_refs"] = []
        self.assertNotIn("history", preserve_selection_history(candidate, cleaned, selection(cleaned)))
        repeated = deepcopy(first_choice)
        repeated["id"] = str(uuid4())
        self.assertNotIn("history", preserve_selection_history(first, first, repeated))

    def test_history_preserves_own_catalog_revision_and_roundtrip_inverse(self):
        """! @brief 다른 카탈로그 개정의 출처도 각 개정으로 검증하며 원자 실행취소로 복원한다."""
        original = deepcopy(self.document)
        old_choice = selection(original, published=True)
        original["materials"][0]["epsilon_r"]["source_refs"] = [old_choice["evidence"][0]["id"]]
        original["extensions"][EXTENSION_KEY] = old_choice
        next_choice = selection(original, published=True)
        next_choice["catalog"]["catalog_id"] = "catalog:" + "f" * 64
        entry = next_choice["evidence"][0]
        entry["id"] = stable_id("evidence", next_choice["catalog"]["catalog_id"], entry["entity"], entry["item_id"],
                                 entry["scope"], entry["pointers"], entry["snapshot_sha256"], entry["origin"])
        next_choice["decisions"][0]["evidence_id"] = entry["id"]
        next_choice = preserve_selection_history(original, original, next_choice)
        self.assertEqual(next_choice["history"][0]["catalog"], CATALOG)
        payload = {key: deepcopy(original[key]) for key in ("materials", "stackup", "ports")}
        payload["selection"] = next_choice
        updated, _, _, inverse = apply_command(original, command("pcb_stackup.apply", payload), original["revision_id"])
        restored, _, _, redo = apply_command(updated, command(inverse["type"], inverse["payload"]), updated["revision_id"])
        self.assertEqual(restored["extensions"], original["extensions"])
        replayed, _, _, _ = apply_command(restored, command(redo["type"], redo["payload"]), restored["revision_id"])
        self.assertEqual(replayed["extensions"][EXTENSION_KEY], next_choice)
        validate_project(json.loads(canonical_bytes(replayed)))

    def test_history_rejects_nested_duplicate_or_damaged_evidence(self):
        """! @brief 과거 기록도 현재와 같은 엄격한 계약과 해시 검사를 적용한다."""
        current = selection(self.document)
        past = selection(self.document, published=True)
        for history in (None, [past | {"history": []}], [past, past], [current],
                        [past | {"evidence": [past["evidence"][0] | {"snapshot_sha256": "0" * 64}]}]):
            with self.subTest(history=history), self.assertRaises(ProjectError):
                validate_selection(current | {"history": history})

    def test_history_aggregate_evidence_limit_and_missing_reference_are_explicit(self):
        """! @brief 여러 과거 선택의 합계 예산을 지키고 출처 단절을 축약으로 숨기지 않는다."""
        histories = []
        for index in range(5):
            item = selection(self.document, published=True)
            item["evidence"] = [evidence({"dk": self.document["materials"][0]["epsilon_r"]["value_si"],
                                          "note": str(index) + "x" * 2300})]
            item["decisions"][0]["evidence_id"] = item["evidence"][0]["id"]
            validate_selection(item)
            histories.append(item)
        current = selection(self.document)
        with patch("rfad.domain.pcb_selection.MAX_EVIDENCE_BYTES", 12 * 1024), self.assertRaises(ProjectError) as caught:
            validate_selection(current | {"history": histories})
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        candidate = deepcopy(self.document)
        candidate["materials"][0]["source_refs"] = ["evidence:" + "0" * 64]
        before = deepcopy(candidate)
        with self.assertRaises(ProjectError) as caught:
            preserve_selection_history(self.document, candidate, current)
        self.assertEqual(caught.exception.code, "E_SCHEMA")
        self.assertEqual(candidate, before)


if __name__ == "__main__":
    unittest.main()
