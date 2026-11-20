"""! @brief 3D 반복 회수 판독의 표본/시간/비가용 GPU 상태를 독립 검증한다."""
from copy import deepcopy
import unittest

from tools.summarize_windows_model_lifetime import summarize


def fixture():
    """! @brief F5의 결과가 아닌 보고서 검사 전용 가상 resource 표본이다."""
    results = [{"event": "start", "expected_cycles": 30, "canvas": [1920, 1080], "minimum_closed_ms": 30000,
                "elapsed_ms": 1}, {"event": "baseline", "cycle": 0, "elapsed_ms": 2, "vertex_buffer": {"bytes": 0}}]
    for cycle in range(1, 31):
        for event in ("open", "closed"):
            results.append({"event": event, "cycle": cycle,
                "elapsed_ms": cycle * 32000 + (30100 if event == "closed" else 0),
                "vertex_buffer": {"bytes": 72000000 if event == "open" else 0, "uploads": cycle},
                "private_commit_bytes": (100 + cycle) * 1024 * 1024,
                "working_set_bytes": 42, "peak_working_set_bytes": 45, "handles": 10,
                "gpu_usage": [{"ordinal": 0, "node": 0, "local_bytes": None, "nonlocal_bytes": 0}]})
    results.append({"event": "complete", "cycles": 30, "elapsed_ms": 31 * 32000})
    return results


class WindowsModelLifetimeTests(unittest.TestCase):
    def test_compares_only_closed_endpoints_without_inventing_gpu(self):
        """! @brief 마지막 10회와 초기 5회를 비교하고 없던 GPU 사용량은 미정으로 둔다."""
        report = summarize(fixture())
        self.assertEqual(report["closed_resources"]["private_commit_bytes"]["first_5_median"], 103 * 1024 * 1024)
        self.assertEqual(report["closed_resources"]["private_commit_bytes"]["last_10_median"], 125.5 * 1024 * 1024)
        self.assertIsNone(report["gpu_usage"][0]["local_bytes"])
        self.assertTrue(report["model_private_commit_delta_within_limit"])
        self.assertFalse(report["f5_full_acceptance_measured"])

    def test_missing_release_and_wrong_wait_are_rejected(self):
        """! @brief 원시 표본이 빠지거나 대기/업로드/해제가 다르면 수용값을 계산하지 않는다."""
        for change in ("missing", "wait", "uploads", "leaked"):
            values = deepcopy(fixture())
            if change == "missing":
                values.pop(3)
            elif change == "wait":
                values[3]["elapsed_ms"] = 60000
            elif change == "uploads":
                values[3]["vertex_buffer"]["uploads"] = 2
            else:
                values[3]["vertex_buffer"]["bytes"] = 72000000
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize(values)
