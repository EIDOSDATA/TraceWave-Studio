"""! @brief 측정한 공정 치수의 동시 표본과 보존된 후보의 RF 판정을 비교한다."""

import csv
from collections import Counter
import hashlib
import io
import math

from rfad.application.design_sweep_store import fail
from rfad.domain.units import Quantity, units_for_dimension


def _label(value):
    """! @brief 출처와 표본 번호는 줄 바꿈 없는 표시 가능한 값으로 보존한다."""
    return isinstance(value, str) and 0 < len(value) <= 120 and value == value.strip() and value.isprintable()


def read_samples(options, axes):
    """! @brief CSV의 축 UUID 및 단위를 검사하고 계산한 조합에만 표본을 대응한다."""
    if type(options) is not dict or set(options) != {"source", "text", "independent_random_sample"}:
        fail("공정 표본의 출처, CSV 원문과 독립 무작위 표집 여부가 필요합니다.")
    text = options["text"]
    if not _label(options["source"]) or type(options["independent_random_sample"]) is not bool:
        fail("공정 표본의 출처와 표집 조건을 확인하십시오.")
    if type(text) is not str or not text or len(text.encode("utf-8")) > 256 * 1024:
        fail("표본 CSV 원문은 1~262144바이트로 입력하십시오.", "E_RESOURCE")
    reader = csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
    try:
        columns = next(reader)
        if len(set(columns)) != len(columns) or "sample_id" not in columns:
            fail("CSV에는 중복 없는 열과 sample_id가 필요합니다.")
        by_id = {a["id"]: a for a in axes}
        mappings = {}
        for pos, name in enumerate(columns):
            if name in ("sample_id", "observed"):
                continue
            identity, sep, unit = name.partition(":")
            if not sep or identity not in by_id or identity in mappings:
                fail("각 연구 변수 열에 변수 UUID:단위를 한 번씩 지정하십시오.")
            axis = by_id[identity]
            if unit not in units_for_dimension(axis["dimension"]):
                fail("CSV 변수 열의 단위가 연구 변수와 다릅니다.")
            mappings[identity] = (pos, unit)
        if set(mappings) != set(by_id):
            fail("CSV에 모든 연구 변수 열이 필요합니다.")
        sample_col = columns.index("sample_id")
        result_col = columns.index("observed") if "observed" in columns else None
        seen = set()
        counts = Counter()
        for row in reader:
            if len(row) != len(columns) or len(seen) >= 10000:
                fail("표본 행의 열 수가 다르거나 표본이 10000개를 초과합니다.")
            sample = row[sample_col]
            if not _label(sample) or sample in seen:
                fail("각 행에는 중복 없는 시료 번호가 필요합니다.")
            seen.add(sample)
            observed = "" if result_col is None else row[result_col]
            if observed not in ("", "pass", "fail"):
                fail("observed 열에는 pass, fail 또는 빈 값을 입력하십시오.")
            ordinal = 0
            for axis in axes:
                pos, unit = mappings[axis["id"]]
                raw = row[pos]
                value = Quantity.from_value(float(raw), unit).value_si
                choices = [i for i, q in enumerate(axis["values"]) if math.isclose(value, q["value_si"], rel_tol=0., abs_tol=math.ulp(value))]
                if len(choices) == 1 and ordinal is not None:
                    ordinal = 3 * ordinal + choices[0]
                else:
                    ordinal = None
            counts[ordinal, observed] += 1
    except (StopIteration, ValueError, csv.Error, OverflowError) as error:
        fail(f"CSV {reader.line_num}행의 원문 또는 유한 수량을 확인하십시오. {error}")
    if not counts:
        fail("공정 CSV에는 시료 행이 하나 이상 필요합니다.")
    details = {"source": options["source"], "csv_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "sample_count": len(seen), "independent_random_sample": options["independent_random_sample"]}
    return details, counts


def _wilson(passing, count):
    """! @brief 독립 무작위로 추출하고 전수 판정한 표본의 양측 95% Wilson 구간을 계산한다."""
    z = 1.959963984540054
    p = passing / count
    denominator = 1 + z*z / count
    center = (p + z*z / (2*count)) / denominator
    radius = z * math.sqrt((p*(1-p) + z*z / (4*count)) / count) / denominator
    return [0.0 if passing == 0 else center-radius, 1.0 if passing == count else center+radius]


def compare_samples(sample_data, outcomes):
    """! @brief 계산과 실물 판정을 따로 집계하고 미계산 위치를 통과로 간주하지 않는다."""
    details, counts = sample_data
    total = details["sample_count"]
    model, measured, paired = Counter(), Counter(), Counter()
    outside = 0
    for (ordinal, obs), count in counts.items():
        outcome = outcomes.get(ordinal)
        predicted = "unknown" if outcome is None else ("pass" if outcome else "fail")
        outside += count if ordinal is None else 0
        model[predicted] += count
        measured[obs or "unknown"] += count
        if obs and outcome is not None:
            paired[predicted + "_" + obs] += count
    return {**details, "outside_sampled_grid": outside,
            "model_counts": {s: model[s] for s in ("pass", "fail", "unknown")},
            "observed_counts": {s: measured[s] for s in ("pass", "fail", "unknown")},
            "model_pass_fraction_bounds": [model["pass"] / total, (total - model["fail"]) / total],
            "observed_pass_fraction_bounds": [measured["pass"] / total, (total - measured["fail"]) / total],
            "model_vs_observed": {s: paired[s] for s in ("pass_pass", "pass_fail", "fail_pass", "fail_fail")},
            "observed_wilson_95": _wilson(measured["pass"], total)
            if details["independent_random_sample"] and not measured["unknown"] else None}
