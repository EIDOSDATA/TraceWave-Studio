"""! @brief 진공 PEC TE10 참조 사례를 순수 해석식으로 검증한다.

@details 환경 검증 도구에서 검토한 규약을 제품 adapter에 고정한다.
"""

import cmath
import math
import re


CASE_VERSION = "rfad.reference.rect-waveguide/0.1"
C0 = 299792458.0
Z0 = 376.730313668
WIDTH_M = 0.020
HEIGHT_M = 0.010
LENGTH_M = 0.080
PROBE_SEPARATION_M = 0.050
END_CRITERION = 1e-7
LIMITS = {
    "max_reflection_amplitude": 0.15,
    "max_transmission_amplitude_error": 0.08,
    "max_impedance_relative_error": 0.08,
    "max_group_delay_relative_error": 0.10,
    "max_grid_transmission_amplitude_delta": 0.03,
    "max_grid_impedance_relative_delta": 0.04,
}


def require(condition: bool, message: str) -> None:
    """! @brief 검사 실패를 성공 결과와 구분할 수 있는 오류로 만든다."""
    if not condition:
        raise RuntimeError(message)


def analytic_te10(frequency_hz: float) -> tuple[float, float]:
    """! @brief 진공 PEC 도파관의 독립 TE10 임피던스와 군지연을 계산한다."""
    cutoff = C0 / (2 * WIDTH_M)
    require(math.isfinite(frequency_hz) and frequency_hz > cutoff, "Frequency must be finite and above TE10 cutoff.")
    factor = math.sqrt(1 - (cutoff / frequency_hz) ** 2)
    return Z0 / factor, PROBE_SEPARATION_M / (C0 * factor)


def assess_samples(samples: list[dict]) -> dict:
    """! @brief 실제 복소 포트 결과를 유한성, 진폭, 임피던스와 군지연으로 판정한다."""
    require(len(samples) >= 3, "At least three frequency samples are required.")
    frequencies, transmissions, impedances, reflections = [], [], [], []
    for sample in samples:
        values = [sample["frequency_hz"], *sample["s11"], *sample["s21"], *sample["impedance_ohm"]]
        require(all(type(value) in (float, int) and math.isfinite(value) for value in values), "Port data contains non-finite values.")
        frequency = sample["frequency_hz"]
        require(not frequencies or frequency > frequencies[-1], "Frequency samples must be strictly increasing.")
        require(frequency < min(C0 / WIDTH_M, C0 / (2 * HEIGHT_M)), "Frequency must be below the next propagating mode.")
        analytic_te10(frequency)
        frequencies.append(frequency)
        reflections.append(complex(*sample["s11"]))
        transmissions.append(complex(*sample["s21"]))
        impedances.append(complex(*sample["impedance_ohm"]))
    delays = []
    for index in range(len(samples) - 1):
        require(abs(transmissions[index]) > 1e-12 and abs(transmissions[index + 1]) > 1e-12, "Transmission is too small for a phase slope.")
        difference = frequencies[index + 1] - frequencies[index]
        phase_change = cmath.phase(transmissions[index + 1] / transmissions[index])
        delay = -phase_change / (2 * math.pi * difference)
        _, reference = analytic_te10(0.5 * (frequencies[index + 1] + frequencies[index]))
        require(reference * difference < 0.25, "Frequency spacing cannot resolve the expected phase slope.")
        delays.append(abs(delay / reference - 1))
    metrics = {
        "max_reflection_amplitude": max(map(abs, reflections)),
        "max_transmission_amplitude_error": max(abs(abs(value) - 1) for value in transmissions),
        "max_impedance_relative_error": max(abs(value / analytic_te10(frequency)[0] - 1) for value, frequency in zip(impedances, frequencies)),
        "max_group_delay_relative_error": max(delays),
    }
    return {"passed": all(value <= LIMITS[name] for name, value in metrics.items()), "metrics": metrics}


def compare_grids(coarse: list[dict], fine: list[dict]) -> dict:
    """! @brief 같은 주파수에서 두 격자의 결과가 크게 달라지지 않는지 검사한다."""
    require(len(coarse) == len(fine) and len(coarse) >= 3, "Grid sample counts differ.")
    for left, right in zip(coarse, fine):
        require(left["frequency_hz"] == right["frequency_hz"], "Grid frequency values differ.")
    metrics = {
        "max_grid_transmission_amplitude_delta": max(abs(abs(complex(*a["s21"])) - abs(complex(*b["s21"]))) for a, b in zip(coarse, fine)),
        "max_grid_impedance_relative_delta": max(abs(complex(*a["impedance_ohm"]) - complex(*b["impedance_ohm"])) / analytic_te10(a["frequency_hz"])[0] for a, b in zip(coarse, fine)),
    }
    require(all(math.isfinite(value) for value in metrics.values()), "Grid comparison is non-finite.")
    return {"passed": all(value <= LIMITS[name] for name, value in metrics.items()), "metrics": metrics}


def check_termination(log_text: str, iterations: int) -> dict:
    """! @brief 조기 중단과 step 상한을 거부하고 native 종료 에너지 근거를 확인한다.

    @details 고정 openEMS 0.37.0의 완료 메시지와 실제 통계가 모두 일치해야 한다.
    로그의 반올림된 감쇠값을 임계값보다 더 정밀한 에너지 측정으로 표현하지 않는다.
    """
    lowered = log_text.lower()
    require("checkabortcond" not in lowered and "aborting simulation" not in lowered, "Native solver reported an aborted simulation.")
    require("max. number of timesteps was reached" not in lowered, "Native solver reported an unmet end criterion.")
    require("Exact-endcriteria: evaluating the end criteria every " in log_text, "Native exact end-criterion evaluation was not confirmed.")
    number = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
    pattern = rf"RunFDTD: end-criteria of -({number})dB reached after ([0-9]+) timesteps \(-({number}|inf)dB\)"
    matches = re.findall(pattern, log_text)
    require(len(matches) == 1, "Exactly one successful native end-criterion message is required.")
    target_text, iteration_text, decay_text = matches[0]
    target_db = float(target_text)
    decay_db = float(decay_text)
    expected_db = -10 * math.log10(END_CRITERION)
    require(math.isfinite(target_db) and abs(target_db - expected_db) < 1e-8, "Native termination target differs from the requested criterion.")
    require(int(iteration_text) == iterations and 0 < iterations < 20000, "Native log and run-statistics iteration counts differ.")
    require(decay_db >= expected_db, "Native termination energy did not meet the requested criterion.")
    return {"status": "end_criterion_reached", "iterations": iterations, "target_energy_ratio": END_CRITERION, "reported_decay_db": decay_db if math.isfinite(decay_db) else None, "reported_zero_energy": math.isinf(decay_db), "evidence": list(matches[0]), "exact_endcriterion_schedule": True}


