"""! @brief 요구 추적 감사가 개수만 같은 잘못된 연결을 성공 처리하지 않는지 검사한다."""

from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_implementation_audit.py"
_SPEC = importlib.util.spec_from_file_location("build_implementation_audit", _PATH)
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


class ImplementationAuditTests(unittest.TestCase):
    """! @brief 실제 정상 감사를 한 번 만들고 독립적인 메모리 손상 사례를 검사한다."""

    @classmethod
    def setUpClass(cls):
        """! @brief native worker 없이 실제 승인 문서/코드에서 정상 근거를 한 번 구성한다."""
        cls.profile = audit.build()

    def records(self):
        """! @brief 사례 사이의 변경이 섞이지 않도록 추적 관계만 복제한다."""
        return deepcopy({
            "requirements": self.profile["requirements"],
            "acs": {row["id"]: row for row in self.profile["acceptance_criteria"]},
            "cases": self.profile["acceptance_subcases"],
            "verification_groups": self.profile["verification_groups"],
            "apis": self.profile["public_api"],
            "supplemental": self.profile["supplemental_design_conditions"],
        })

    def test_real_document_closure_preserves_open_acceptance(self):
        """! @brief 실제 원문 연결을 검사해도 출시/물리 수용 합격을 생성하지 않는다."""
        audit.validate_trace_links(**self.records())
        for category, count in (("functions", 46), ("requirements", 141), ("acceptance_criteria", 404),
                                ("acceptance_subcases", 407), ("verification_groups", 30),
                                ("public_api", 30), ("supplemental_design_conditions", 22)):
            self.assertEqual(len(self.profile[category]), count)
        for category in ("requirements", "acceptance_subcases", "verification_groups", "supplemental_design_conditions"):
            self.assertTrue(all(row["acceptance_status"] == "open" for row in self.profile[category]))
        self.assertTrue(all(row["full_contract_accepted"] is False for row in self.profile["public_api"]))
        self.assertFalse(self.profile["physics_validated"])

    def test_unknown_requirement_verification_group_is_rejected(self):
        """! @brief 존재하지 않는 주 검수 연결을 개수가 같다는 이유로 수용하지 않는다."""
        records = self.records()
        records["requirements"][0]["verification_groups"] = ["VT-999"]
        with self.assertRaisesRegex(ValueError, "요구의 VT 연결"):
            audit.validate_trace_links(**records)

    def test_unrelated_subcase_ac_and_unknown_group_are_rejected(self):
        """! @brief 다른 AC 이름을 붙인 고유 subcase도 올바른 귀속으로 인정하지 않는다."""
        records = self.records()
        records["cases"][0]["subcase"] = "VT-999/UNRELATED.R1"
        with self.assertRaisesRegex(ValueError, "subcase의 AC 귀속"):
            audit.validate_trace_links(**records)

    def test_duplicate_verification_group_cannot_hide_missing_group(self):
        """! @brief VT 30행을 유지하면서 VT-002를 VT-001로 바꾼 손상을 검출한다."""
        records = self.records()
        records["verification_groups"][1]["id"] = records["verification_groups"][0]["id"]
        with self.assertRaisesRegex(ValueError, "VT 식별자"):
            audit.validate_trace_links(**records)

    def test_duplicate_api_cannot_hide_missing_api(self):
        """! @brief project.open의 ID만 API-001로 바꾸어도 승인 API 30개로 간주하지 않는다."""
        records = self.records()
        records["apis"][1]["id"] = records["apis"][0]["id"]
        with self.assertRaisesRegex(ValueError, "API 식별자"):
            audit.validate_trace_links(**records)

    def test_duplicate_supplemental_cannot_hide_missing_performance_condition(self):
        """! @brief 22행 중 PERF-002가 사라지고 PERF-001이 반복된 경우 실패한다."""
        records = self.records()
        row = next(item for item in records["supplemental"] if item["id"] == "PERF-002")
        row["id"] = "PERF-001"
        with self.assertRaisesRegex(ValueError, "보충 조건 식별자"):
            audit.validate_trace_links(**records)

    def test_known_group_must_belong_to_subcase_requirement(self):
        """! @brief 존재하는 VT라도 해당 요구에 연결되지 않은 검수로 옮기지 못한다."""
        records = self.records()
        case = records["cases"][0]
        owner = next(row for row in records["requirements"] if case["ac_id"] in row["acceptance_criteria"])
        other = next(row["id"] for row in records["verification_groups"] if row["id"] not in owner["verification_groups"])
        case["subcase"] = other + "/" + case["subcase"].split("/", 1)[1]
        with self.assertRaisesRegex(ValueError, "subcase의 VT가 요구 연결"):
            audit.validate_trace_links(**records)

    def test_subcase_stage_and_requirement_ac_ownership_are_checked(self):
        """! @brief 후속 단계 조건을 R1로 바꾸거나 다른 요구의 AC를 연결하지 못한다."""
        records = self.records()
        records["cases"][0]["stage"] = "M/R2; R1"
        with self.assertRaisesRegex(ValueError, "subcase 단계"):
            audit.validate_trace_links(**records)
        records = self.records()
        records["requirements"][0]["acceptance_criteria"][0] = records["requirements"][1]["acceptance_criteria"][0]
        with self.assertRaisesRegex(ValueError, "요구의 AC 연결"):
            audit.validate_trace_links(**records)

    def test_registered_api_descriptor_must_match_approved_id(self):
        """! @brief 고유 API 행이어도 capability의 다른 ID와 연결된 구현을 표시하지 않는다."""
        records = self.records()
        row = next(item for item in records["apis"] if item["advertised"])
        row["descriptor"]["api_id"] = "API-999"
        with self.assertRaisesRegex(ValueError, "API ID와 capability"):
            audit.validate_trace_links(**records)

    def test_group_summary_cannot_omit_a_subcase(self):
        """! @brief 상세 행은 남았지만 VT 색인에서 누락된 검수도 검출한다."""
        records = self.records()
        group = next(row for row in records["verification_groups"] if row["subcases"])
        group["subcases"].pop()
        with self.assertRaisesRegex(ValueError, "VT의 subcase 연결"):
            audit.validate_trace_links(**records)

    def test_evidence_symbols_and_text_hash_are_verified(self):
        """! @brief 없는 시험 심볼을 거부하고 개행 차이를 제외한 본문 변경을 감지한다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "evidence.py"
            original = b"class Evidence:\n    def test_existing(self):\n        pass\n"
            source.write_bytes(original)
            with patch.object(audit, "CODE", root):
                self.assertEqual(audit.check_reference("evidence.py::Evidence.test_existing"), source)
                with self.assertRaisesRegex(ValueError, "시험 심볼 없음"):
                    audit.check_reference("evidence.py::Evidence.test_missing")
                first = audit.reference(source)
                source.write_bytes(original.replace(b"\n", b"\r\n"))
                self.assertEqual(audit.reference(source), first)
                source.write_bytes(original.replace(b"pass", b"return 1"))
                self.assertNotEqual(audit.reference(source)["text_sha256"], first["text_sha256"])

    def test_check_mode_is_repeatable_and_detects_both_artifact_changes(self):
        """! @brief 같은 검토 입력의 반복 검사와 JSON/문서 변조 검출을 실제 main에서 확인한다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "docs/audit"
            output.mkdir(parents=True)
            with patch.object(audit, "CODE", root), patch.object(audit, "build", return_value=self.profile), redirect_stdout(io.StringIO()):
                with patch.object(audit.sys, "argv", ["audit"]):
                    audit.main()
                saved = {path.name: path.read_bytes() for path in output.iterdir()}
                with patch.object(audit.sys, "argv", ["audit", "--check"]):
                    audit.main()
                    audit.main()
                    self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, saved)
                    for name in ("implementation_matrix.json", "function_matrix.md"):
                        with self.subTest(artifact=name):
                            path = output / name
                            path.write_bytes(saved[name] + b"changed\n")
                            with self.assertRaises(ValueError):
                                audit.main()
                            path.write_bytes(saved[name])
                self.assertEqual(json.loads((output / "implementation_matrix.json").read_text(encoding="utf-8")), self.profile)


if __name__ == "__main__":
    unittest.main()
