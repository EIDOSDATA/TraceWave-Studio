"""! @brief 사용자가 공급한 단일 모드의 분산 자료로 포트별 정합 이동 계수를 계산한다."""

import cmath
import math

from rfad.domain.network_data import fail, finite, is_named_mode, text


def factors(table, data, port, length, sign):
    """! @brief 모드 이름, 파 정의, 시간 규약, 출처와 모든 실제 주파수를 일대일로 검사한다."""
    field = "options.lines.modal"
    keys = {"mode", "wave_definition", "phasor_convention", "source", "samples"}
    if type(table) is not dict or set(table) != keys:
        fail("모드 이름, 파 정의, 시간 규약, 출처와 분산 표본을 입력하십시오.", field)
    if not is_named_mode(table["mode"]) or data["port_modes"][port] != table["mode"]:
        fail("포트에 등록한 사용자 모드 이름과 분산표의 모드가 다릅니다.", field + ".mode", "E_CONFLICT")
    for key in ("wave_definition", "phasor_convention"):
        if table[key] != data[key] or data[key] == "unknown":
            fail("분산표와 자료의 파 정의 및 시간 위상 규약이 일치해야 합니다.", field + "." + key, "E_CONFLICT")
    text(table["source"], field + ".source", limit=1024)
    samples = table["samples"]
    if type(samples) is not list or len(samples) != len(data["frequency_hz"]):
        fail("분산표에는 보간 없이 모든 원본 주파수의 표본이 있어야 합니다.", field + ".samples", "E_CONFLICT")
    result = []
    for i, (row, frequency) in enumerate(zip(samples, data["frequency_hz"])):
        path = f"{field}.samples.{i}"
        if type(row) is not list or len(row) != 4:
            fail("주파수(Hz), 감쇠(Np/m), 위상 상수(rad/m), 실수 모드 임피던스(ohm)가 필요합니다.", path)
        f, alpha, beta, impedance = [finite(value, path) for value in row]
        if f != frequency or f <= 0:
            fail("원본 주파수와 같은 순서의 양의 주파수가 필요합니다.", path, "E_CONFLICT")
        if alpha < 0 or beta <= 0 or impedance <= 0:
            fail("단일 전파 모드에 음수 감쇠, 0 이하의 위상 상수 또는 임피던스를 사용할 수 없습니다.", path, "E_UNIT")
        gain = -alpha * length
        phase = sign * beta * length
        if abs(gain) > 300 or abs(phase) > 5e7 * math.tau:
            fail("모드 선로의 감쇠 또는 위상이 계산 범위를 넘었습니다.", path, "E_RESOURCE")
        result.append((cmath.exp(complex(gain, math.remainder(phase, math.tau))), impedance))
    return result
