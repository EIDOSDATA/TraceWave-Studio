"""! @brief 독립 전력 CLI의 잘못된 연구/진행표/파일 식별 차단을 검사한다."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rfad.domain.errors import ProjectError
import verify_pcb_power_balance as tool


class PowerToolTests(unittest.TestCase):
    """! @brief 잘못된 입력을 새 계산으로 자동 보완하지 않는 경계를 검사한다."""

    def test_invalid_levels_are_rejected_before_runtime_or_fixture_read(self):
        """! @brief 순서/범위/중복/개수 오류를 native 시작 전에 차단한다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            for levels in ([], [0.5, 0.4], [0.5, 0.5, 0.4], [0.4, 0.45, 0.5], [True, 0.4, 0.3], [6, 0.4, 0.3]):
                manifest_path.write_text(json.dumps({"schema": "rfad.pcb-power-study/0.1", "grid_levels_mm": levels}), encoding="utf-8")
                with self.subTest(levels=levels), patch.object(tool, "SolverRuntime") as runtime, self.assertRaises(ValueError):
                    tool.run(root / "workspace", root / "report.json", manifest_path)
                runtime.assert_not_called()
                self.assertFalse((root / "workspace").exists())

    def test_duplicate_roles_and_wrong_result_id_are_rejected(self):
        """! @brief 정상 산출물의 다른 등록 결과 대입과 파일 역할 중복을 차단한다."""
        subject = {"context": {"project_id": "test"}}
        entry = {"artifact_id": "expected"}
        for opened in ({"artifact_id": "wrong", "files": []},
                       {"artifact_id": "expected", "files": [{"role": "normalized_result"}, {"role": "normalized_result"}]}):
            with self.subTest(opened=opened), patch.object(tool, "call", return_value=opened), self.assertRaises(ValueError):
                tool.load_result(None, entry, subject)

    def test_all_registered_files_are_read_before_assessment(self):
        """! @brief 손실 원시 필드의 봉인 실패를 무시하고 결과 합계를 판정하지 않는다."""
        item = {"role": "raw/pcb_loss_E.h5", "uri": "field", "sha256": "changed", "bytes": 10}
        opened = {"artifact_id": "expected", "files": [item]}

        def rejected(reference):
            """! @brief 실제 journal의 바이트/해시 실패를 모사한다."""
            raise ProjectError("E_HASH", "변경된 원시 필드")

        service = SimpleNamespace(journal=SimpleNamespace(read_artifact=rejected))
        with patch.object(tool, "call", return_value=opened), self.assertRaisesRegex(ProjectError, "변경된 원시"):
            tool.load_result(service, {"artifact_id": "expected"}, {"context": {}})


if __name__ == "__main__":
    unittest.main()
