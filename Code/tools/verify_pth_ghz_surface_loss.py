"""! @brief 봉인 합성 관통홀의 영역별 GHz 손실을 닫힌 표면 임피던스 적분으로 대조한다."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path


MU0 = 4e-7 * math.pi
REGIONS = ("barrel", "joint", "pad", "feed_pad")
METHODS = ("volume", "elements")


def surface_resistance(frequency, conductivity):
    """! @brief 좋은 도체의 표면 저항과 표피 깊이를 구한다."""
    depth = math.sqrt(1 / (math.pi * frequency * MU0 * conductivity))
    return 1 / (conductivity * depth), depth


def feed_square_integral(profile, height, delta):
    """! @brief 외곽 원통에서 지정 전류 분포의 제곱을 패드 두께로 적분한다."""
    if profile == "spread":
        return height * 3 / 8
    if profile != "surface_concentrated":
        raise ValueError("지원하는 지정 급전 분포가 아닙니다.")
    exponent = math.exp(-height / delta)
    one_minus = -math.expm1(-height / delta)
    square = delta / 2 * -math.expm1(-2 * height / delta)
    return (square - 2 * delta * exponent * one_minus + height * exponent**2) / one_minus**2


def surface(fixture, frequency, ratio, profile):
    """! @brief q가 지정된 매끈한 각 표면의 국부 Joule 손실을 독립 적분한다."""
    geometry = fixture["geometry_m"]
    barrel, pad, feed = (geometry[k] for k in ("barrel_outer", "pad_outer", "feed_region_start_r"))
    pad_depth, joint_depth = (geometry[k] for k in ("pad_thickness", "joint_thickness"))
    barrel_height = geometry["height"] - 2 * (pad_depth + joint_depth)
    current = fixture["peak_current_a"]
    area_factor = current**2 / (4 * math.pi)
    sigma = fixture["conductivity_s_per_m"]
    copper, delta = surface_resistance(frequency, sigma)
    joint, _ = surface_resistance(frequency, sigma * ratio)
    radial_feed = math.log(pad / feed)
    outer_face = feed_square_integral(profile, pad_depth, delta) / pad
    return {
        "barrel": area_factor * copper * barrel_height / barrel,
        "joint": area_factor * joint * 2 * joint_depth / barrel,
        "pad": area_factor * copper * 2 * math.log(feed / barrel),
        "feed_pad": area_factor * copper * 2 * (radial_feed + outer_face),
    }


def compare_sealed(path):
    """! @brief 보존된 마지막 두 수치 풀이와 표면 근사의 영역별 편차를 기록한다."""
    raw = path.read_bytes()
    fixture = json.loads(raw)["pth_ghz"]
    rows = []
    for case in fixture["cases"]:
        ratio, profile = case["joint_conductivity_ratio"], case["terminal_profile"]
        for result in case["frequencies"]:
            if not result["fixture_gate_passed"]:
                raise ValueError("수치 풀이의 합성 검수를 통과한 기록이 필요합니다.")
            frequency = result["frequency_hz"]
            predicted = surface(fixture, frequency, ratio, profile)
            last = result["levels"][-1]
            actual = {method: last[method]["loss_w_at_1a_peak"] for method in METHODS}
            relative = {method: {name: predicted[name] / actual[method][name] - 1 for name in REGIONS}
                        for method in METHODS}
            rows.append({"frequency_hz": frequency, "joint_conductivity_ratio": ratio,
                         "terminal_profile": profile, "surface_loss_w": predicted,
                         "numerical_loss_w": actual, "surface_minus_numerical_relative": relative})
    maxima = {name: max(abs(row["surface_minus_numerical_relative"][method][name])
                        for row in rows for method in METHODS) for name in REGIONS}
    return {
        "schema": "rfad.pth-ghz-surface-comparison/0.1",
        "scope": "asymptotic_surface_loss_in_prescribed_current_fixture",
        "native_or_measurement_validated": False,
        "record_sha256": sha256(raw).hexdigest(),
        "maximum_relative_difference": maxima,
        "cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verification_record", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare_sealed(args.verification_record), allow_nan=False))
