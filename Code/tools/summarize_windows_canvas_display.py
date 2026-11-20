"""! @brief Windows 캔버스 입력, 그리기 및 합성 표본을 같은 프레임 번호로 대조한다."""

import argparse
import json
from pathlib import Path
from statistics import median


def _statistics(values):
    """! @brief 관찰 간격을 보존하고 nearest-rank p95와 p99를 계산한다."""
    if not values:
        return None
    ordered = sorted(values)
    return {
        "samples": len(ordered), "median_ms": median(ordered),
        "p95_ms": ordered[(95 * len(ordered) + 99) // 100 - 1],
        "p99_ms": ordered[(99 * len(ordered) + 99) // 100 - 1], "maximum_ms": ordered[-1],
    }


def summarize(trace):
    """! @brief 표시한 입력만 시각을 연결하고 관찰되지 않은 입력과 누락 가능성을 센다."""
    if trace.get("schema") != "rfad.windows-canvas-display-trace/0.1" or trace.get("ok") is not True:
        raise ValueError("완료된 Windows 캔버스 표시 기록이 필요합니다.")
    frequency, start, end = (trace[key] for key in ("qpc_frequency", "start_qpc", "end_qpc"))
    if any(type(value) is not int for value in (frequency, start, end)) or not (frequency > 0 and 0 < start < end):
        raise ValueError("계측 시각과 주파수가 유효하지 않습니다.")
    scale = 1000 / frequency
    inputs = trace["inputs_qpc"]
    if not inputs or any(type(value) is not int or not start <= value < end for value in inputs):
        raise ValueError("계측 구간을 벗어난 입력 시각입니다.")
    if any(last >= first for last, first in zip(inputs, inputs[1:])):
        raise ValueError("입력 카운터가 증가하지 않습니다.")
    offers = trace.get("offers_qpc")
    if offers is not None and (len(offers) < len(inputs)
            or any(type(value) is not int or not start <= value < end for value in offers)
            or any(last >= first for last, first in zip(offers, offers[1:]))):
        raise ValueError("시험 입력 타이머의 원시 시각이 유효하지 않습니다.")
    # @brief 동일 입력의 재그리기는 첫 기록을 사용하며 같은 번호의 합성 반복도 첫 시각만 사용한다.
    painted = {}
    last_paint, previous_sequence = 0, -1
    for sequence, when in trace["painted"]:
        if (type(sequence) is not int or not previous_sequence < sequence <= len(inputs)
                or type(when) is not int or when <= last_paint
                or (sequence > 0 and when < inputs[sequence - 1])):
            raise ValueError("그리기 번호, 시각 또는 해당 입력이 유효하지 않습니다.")
        painted[sequence] = when
        last_paint, previous_sequence = when, sequence
    if 0 not in painted:
        raise ValueError("시험 시작 전 그린 표식 기록이 없습니다.")
    visible = {}
    last_desktop, previous_sequence = 0, -1
    accumulated = without_marker = active_updates = 0
    saw_initial_marker = False
    for when, frames, sequence in trace["desktop_updates"]:
        if type(when) is not int or when <= last_desktop or type(frames) is not int or frames < 1:
            raise ValueError("Windows 합성 시각 또는 갱신 합계가 유효하지 않습니다.")
        last_desktop = when
        if start <= when <= end:
            active_updates += 1
            accumulated += frames - 1
            without_marker += sequence is None
        if sequence is None:
            continue
        if type(sequence) is not int or sequence < previous_sequence or sequence not in painted:
            raise ValueError("그리기 기록과 합성 화면 표식이 일치하지 않습니다.")
        previous_sequence = sequence
        if when < painted[sequence]:
            raise ValueError("그리기에 앞선 합성 시각을 입력에 연결할 수 없습니다.")
        if sequence == 0:
            saw_initial_marker = True
        else:
            visible.setdefault(sequence, when)
    if not saw_initial_marker or not visible:
        raise ValueError("초기 또는 확대 화면 표식을 관찰하지 못했습니다.")
    times = list(visible.values())
    intervals = [(later - earlier) * scale for earlier, later in zip(times, times[1:])]
    target_fps = trace.get("target_fps", 60)
    if type(target_fps) is not int or target_fps not in (30, 60):
        raise ValueError("현재 Windows 표시 검증은 30 또는 60 fps 목표를 사용합니다.")
    limit = 1000 / target_fps
    return {
        "workload": trace["workload"], "shapes": trace["shapes"], "layers": trace["layers"],
        "triangles": trace.get("triangles", 0), "frame_interval_target_fps": target_fps,
        "frame_interval_target_ms": limit, "renderer": trace.get("renderer"),
        "swap_interval": trace.get("swap_interval"), "vertex_buffer": trace.get("vertex_buffer"),
        "duration_s": (end - start) / frequency, "canvas": trace["canvas"], "display": trace["display"],
        "timer": trace.get("timer", "wx-timer"), "requested_timer_ms": trace["requested_timer_ms"],
        "dpi": trace["dpi"], "refresh_hz": trace["refresh_hz"],
        "timer_offers": len(offers) if offers is not None else None,
        "timer_offers_without_input": len(offers) - len(inputs) if offers is not None else None,
        "timer_interval": _statistics([(later - earlier) * scale for earlier, later in zip(offers, offers[1:])])
        if offers is not None else None,
        "inputs": len(inputs), "painted_inputs": len(painted) - 1, "observed_inputs": len(visible),
        "inputs_without_paint": len(inputs) + 1 - len(painted),
        "paints_without_observed_display": len(painted) - 1 - len(visible),
        "desktop_updates_during_input": active_updates,
        "additional_accumulated_desktop_updates": accumulated,
        "desktop_updates_without_marker": without_marker,
        "input_interval": _statistics([(later - earlier) * scale for earlier, later in zip(inputs, inputs[1:])]),
        "observed_frame_interval": _statistics(intervals),
        "observed_frame_intervals_over_60_fps_budget": sum(value > 1000 / 60 for value in intervals),
        "observed_frame_intervals_over_target": sum(value > limit for value in intervals),
        "observed_input_to_display": _statistics(
            [(when - inputs[sequence - 1]) * scale for sequence, when in visible.items()]),
        "first_observed_after_start_ms": (times[0] - start) * scale,
        "end_after_last_observed_ms": (end - times[-1]) * scale,
        "full_f1_acceptance_measured": False,
        "full_f2_acceptance_measured": False,
    }


def main():
    """! @brief 유한한 파일을 읽고 새 실행 요약을 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    try:
        with args.trace.open("rb") as stream:
            raw = stream.read(8 * 1024**2 + 1)
        if len(raw) > 8 * 1024**2:
            raise ValueError("최대 8 MiB의 시험 파일을 지정하세요.")
        summary = summarize(json.loads(raw))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except (OSError, KeyError, ValueError, TypeError, AttributeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
