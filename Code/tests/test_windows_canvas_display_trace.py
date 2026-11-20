"""! @brief 실제 창 계측의 판독에서 중복, 입력 합쳐짐과 시각 오류를 확인한다."""

import unittest

from tools.summarize_windows_canvas_display import summarize, summarize_catalog


class WindowsCanvasDisplayTraceTests(unittest.TestCase):
    """! @brief 사용자 입력 수를 보존하고 실제 합성에 나타난 번호만 수치에 사용한다."""

    def trace(self):
        """! @brief 비표시 입력, 반복 표식, 식별하지 못한 화면과 긴 표시 간격이 있다."""
        return {
            "schema": "rfad.windows-canvas-display-trace/0.1", "ok": True, "qpc_frequency": 1000,
            "start_qpc": 100, "end_qpc": 200, "inputs_qpc": [105, 115, 130, 170],
            "offers_qpc": [104, 110, 114, 129, 169], "requested_timer_ms": 8,
            "painted": [[0, 91], [2, 120], [3, 140], [4, 180]],
            "desktop_updates": [[96, 1, 0], [122, 1, 2], [125, 1, 2], [161, 1, None], [186, 2, 4]],
            "workload": "canvas-wheel-zoom", "shapes": 256, "layers": 4,
            "canvas": [1000, 700], "display": [1920, 1080], "dpi": 96, "refresh_hz": 120,
        }

    def test_observed_intervals_preserve_gaps_and_unobserved_input_counts(self):
        result = summarize(self.trace())
        self.assertEqual(result["timer_offers_without_input"], 1)
        self.assertEqual(result["inputs_without_paint"], 1)
        self.assertEqual(result["paints_without_observed_display"], 1)
        self.assertEqual(result["observed_inputs"], 2)
        self.assertEqual(result["desktop_updates_without_marker"], 1)
        self.assertEqual(result["additional_accumulated_desktop_updates"], 1)
        self.assertEqual(result["observed_frame_interval"]["samples"], 1)
        self.assertEqual(result["observed_frame_interval"]["p95_ms"], 64.0)
        self.assertEqual(result["observed_input_to_display"]["p99_ms"], 16.0)
        self.assertFalse(result["full_f1_acceptance_measured"])

    def test_marker_that_precedes_paint_is_rejected(self):
        trace = self.trace()
        trace["desktop_updates"][1][0] = 119
        with self.assertRaisesRegex(ValueError, "그리기에 앞선"):
            summarize(trace)

    def test_out_of_order_marker_is_rejected(self):
        trace = self.trace()
        trace["desktop_updates"].append([192, 1, 3])
        with self.assertRaisesRegex(ValueError, "표식이 일치하지"):
            summarize(trace)

    def test_native_table_preserves_unmatched_markers_and_display_gaps(self):
        """! @brief 표식의 시각이 뒤섞이면 원시 값을 보존하고 표시 간격을 이어서 계산한다."""
        trace = self.trace()
        trace.update(workload="catalog_scroll", catalog_rows=100000, top_rows_not_yet_loaded=1)
        trace["desktop_updates"].insert(1, [119, 1, 2])
        trace["desktop_updates"].append([192, 1, 3])
        result = summarize_catalog({"passed": True, "pcb_catalog_metrics": {"display_trace": trace}})
        self.assertEqual(result["uncorrelated_markers"], [[119, 1, 2], [192, 1, 3]])
        self.assertEqual(result["desktop_updates_without_marker"], 3)
        self.assertEqual(result["observed_frame_interval"]["p95_ms"], 64.0)
        self.assertEqual(result["catalog_rows"], 100000)
        self.assertEqual(result["top_rows_not_yet_loaded"], 1)

    def test_model_trace_uses_its_30_fps_target(self):
        """! @brief 대형 회전의 표시 간격을 30 fps 기준에서 별도로 센다."""
        trace = self.trace()
        trace.update(workload="model-rotate-pan", shapes=0, triangles=1000000, target_fps=30)
        trace["desktop_updates"].insert(3, [146, 1, 3])
        result = summarize(trace)
        self.assertEqual(result["frame_interval_target_fps"], 30)
        self.assertEqual(result["triangles"], 1000000)
        self.assertEqual(result["observed_frame_intervals_over_target"], 1)
        self.assertEqual(result["observed_frame_intervals_over_60_fps_budget"], 2)
        self.assertFalse(result["full_f2_acceptance_measured"])
