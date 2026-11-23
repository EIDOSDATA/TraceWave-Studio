"""! @brief 보존한 후보 목표 표본으로 읽기 전용 다목적 순위를 계산한다."""

from collections import Counter
from fractions import Fraction
from itertools import combinations, product
import math

from rfad.application.process_samples import compare_samples, read_samples
from rfad.application.canonical import canonical_hash, canonical_hash_from_bytes
from rfad.application.design_sweep_store import fail, load_candidate, read_json
from rfad.domain.network_data import finite


def target_score(assessment):
    """! @brief 유효 표본을 전부 가진 목표만 기준별 통과율의 최솟값을 사용한다."""
    criteria = assessment.get("criteria", [])
    if not criteria:
        return None
    scores = []
    for criterion in criteria:
        points = criterion.get("points", [])
        if not points or any(point["status"] not in ("pass", "fail") for point in points):
            return None
        scores.append(Fraction(sum(point["status"] == "pass" for point in points), len(points)))
    return min(scores)


def fronts(vectors):
    """! @brief 모든 목표에서 같거나 우세하고 하나 이상에서 우세한 후보만 지배자로 센다."""
    ids = sorted(vectors)
    successors = {identity: [] for identity in ids}
    incoming = dict.fromkeys(ids, 0)
    for first, left in enumerate(ids):
        for right in ids[first + 1:]:
            delta = [a - b for a, b in zip(vectors[left], vectors[right])]
            if all(value >= 0 for value in delta) and any(value > 0 for value in delta):
                successors[left].append(right)
                incoming[right] += 1
            elif all(value <= 0 for value in delta) and any(value < 0 for value in delta):
                successors[right].append(left)
                incoming[left] += 1
    current = [identity for identity in ids if not incoming[identity]]
    ranking = {}
    level = 1
    while current:
        following = []
        for identity in current:
            ranking[identity] = level
            for other in successors[identity]:
                incoming[other] -= 1
                if not incoming[other]:
                    following.append(other)
        current = sorted(following)
        level += 1
    return ranking


def _weights(identities, raw):
    """! @brief 명시한 가중치만 바꾸며 생략한 목표의 가중치는 1이다."""
    if raw is None:
        return None
    if type(raw) is not dict or not raw or not set(raw) <= set(identities):
        fail("저장한 연구의 목표별 가중치를 지정하십시오.")
    values = [finite(raw.get(identity, 1), "weights." + identity) for identity in identities]
    if any(not 0 <= value <= 1e6 for value in values) or not any(values):
        fail("가중치는 0~1000000이며 최소 한 목표의 가중치는 양수여야 합니다.")
    return [Fraction(str(value)) for value in values]


def tolerance_axes(specification):
    """! @brief 사용자가 세 값을 지정한 설계 또는 소자 축에서 공차 모서리를 읽는다."""
    axes = specification["variables"]
    if specification["combination"] != "cartesian" or specification["type"] == "numerical_study":
        return []
    for axis in axes:
        if axis["kind"] not in {"parameter", "circuit_value"} or len(axis["values"]) != 3:
            return []
        low, nominal, high = (quantity["value_si"] for quantity in axis["values"])
        if None in (low, nominal, high) or not low < nominal < high:
            return []
    return axes


def _s11_trace(assessment, complete):
    """! @brief 봉인 평가의 직접 유한 S11 dB 표본만 주파수에 대응한다."""
    result = {}
    for criterion in assessment["criteria"]:
        if criterion["metric"] == "s11_db":
            points = criterion["points"]
            for point in points:
                frequency, value = point["frequency_hz"], point["value"]
                if point["status"] in {"pass", "fail"} and type(value) in (float, int) and math.isfinite(value):
                    result[frequency] = value
            if complete and len(result) != len(points):
                return {}
            break
    return result


def _pair_contrasts(axes, nominal, base, steps, values):
    """! @brief 두 축을 바꾼 반사에서 각각의 변화와 공칭을 빼 교호 효과를 계산한다."""
    pairs = []
    for (axis_a, step_a), (axis_b, step_b) in combinations(zip(axes, steps), 2):
        conditions = []
        for sign_a, sign_b in product((-1, 1), repeat=2):
            a, b = nominal + sign_a * step_a, nominal + sign_b * step_b
            combined = a + b - nominal
            inputs = (combined, a, b)
            missing = [ordinal for ordinal in inputs if values(ordinal) is None]
            interaction = None if missing else values(combined) - values(a) - values(b) + base
            conditions.append({"levels": ["low" if sign < 0 else "high" for sign in (sign_a, sign_b)],
                               "ordinal": combined, "single_ordinals": [a, b], "missing_ordinals": missing,
                               "interaction_db": interaction})
        complete = all(condition["interaction_db"] is not None for condition in conditions)
        pairs.append({"axes": [{key: axis[key] for key in ("id", "kind")} for axis in (axis_a, axis_b)],
                      "conditions": conditions, "complete": complete,
                      "maximum_abs_db": max(abs(condition["interaction_db"]) for condition in conditions)
                      if complete else None})
    pairs.sort(key=lambda pair: (not pair["complete"], -(pair["maximum_abs_db"] or 0)))
    return pairs


def _s11_response(axes, nominal, nominal_trace, extremes, traces, identity):
    """! @brief 공칭의 가장 높은 S11 dB 주파수에서 축 하나만 바꿨을 때의 차이를 계산한다."""
    if not nominal_trace:
        return None
    frequency, base = max(nominal_trace.items(), key=lambda item: (item[1], -item[0]))
    def at(ordinal):
        """! @brief 공칭에서 정한 동일한 주파수의 직접 표본만 읽는다."""
        return traces.get(ordinal, {}).get(identity, {}).get(frequency)

    rows = []
    for axis, step in zip(axes, extremes):
        low, high = nominal - step, nominal + step
        low_value, high_value = at(low), at(high)
        deltas = [None if value is None else value - base for value in (low_value, high_value)]
        change = None if None in deltas else max(map(abs, deltas))
        rows.append({"id": axis["id"], "kind": axis["kind"], "low_ordinal": low, "high_ordinal": high, "low_delta_db": deltas[0],
                     "high_delta_db": deltas[1], "maximum_abs_delta_db": change})
    rows.sort(key=lambda row: (row["maximum_abs_delta_db"] is None, -(row["maximum_abs_delta_db"] or 0)))
    return {"frequency_hz": frequency, "nominal_db": base, "axes": rows,
            "pair_interactions": _pair_contrasts(axes, nominal, base, extremes, at)}


def _tolerance_report(axes, ids, vectors, traces):
    """! @brief 공칭점과 명시 모서리만 비교하며 누락 구간에서 최악 판정을 유보한다."""
    corners, nominal = [], None
    for ordinal, indices in enumerate(product(range(3), repeat=len(axes))):
        if 1 not in indices:
            corners.append(ordinal)
        elif all(index == 1 for index in indices):
            nominal = ordinal
    steps = [3**exponent for exponent in reversed(range(len(axes)))]
    reported = [ordinal for ordinal in corners if ordinal in vectors]
    missing = [ordinal for ordinal in corners if ordinal not in vectors]
    objectives = []
    for index, identity in enumerate(ids):
        observed = min((vectors[ordinal][index] for ordinal in reported), default=None)
        objectives.append({
            "target_id": identity,
            "nominal_score": float(vectors[nominal][index]) if nominal in vectors else None,
            "observed_min_score": float(observed) if observed is not None else None,
            "complete_corner_score": float(observed) if not missing else None,
            "observed_min_ordinals": [ordinal for ordinal in reported if vectors[ordinal][index] == observed],
            "s11_response": _s11_response(axes, nominal, traces.get(nominal, {}).get(identity, {}),
                                          steps, traces, identity),
        })
    return {"axes": axes, "nominal_ordinal": nominal, "nominal_available": nominal in vectors,
            "corner_ordinals": corners, "missing_corner_ordinals": missing,
            "complete_corners": not missing, "targets": objectives}


def _probability_axes(axes, raw):
    """! @brief 모든 축에서 사용자가 명시한 세 가중치만 정규화한다."""
    if raw is None:
        return None
    if type(raw) is not list or not axes or len(raw) != len(axes):
        fail("공차의 모든 축에 최소, 공칭, 최대 가중치를 지정하십시오.")
    normalized = []
    for index, values in enumerate(raw):
        if type(values) is not list or len(values) != 3:
            fail("각 축에는 최소, 공칭, 최대 가중치가 각각 필요합니다.")
        numbers = [finite(value, f"probabilities.{index}") for value in values]
        if any(not 0 <= number <= 1e6 for number in numbers) or not any(numbers):
            fail("각 축 가중치는 0~1000000이며 적어도 하나는 양수여야 합니다.")
        exact = [Fraction(str(number)) for number in numbers]
        total = sum(exact)
        normalized.append([number / total for number in exact])
    return normalized


def _joint_distribution(axes, raw, total):
    """! @brief 봉인 연구의 명시 후보 번호와 원문 가중치만 결합 분포로 수용한다."""
    if raw is None:
        return None
    if len(axes) < 2:
        fail("후보 조합 분포는 공차 축이 두 개 이상인 연구에 적용합니다.", "E_UNSUPPORTED")
    label = raw["source_label"]
    if type(label) is not str or not 1 <= len(label) <= 120 or label != label.strip() or not label.isprintable():
        fail("후보 조합 가중치의 출처 또는 가정을 한 줄로 입력하십시오.")
    records = raw["weights"]
    if not 1 <= len(records) <= total:
        fail("연구 안의 후보 번호에만 가중치를 지정하십시오.")
    weighted = {}
    for row in records:
        if type(row) is not dict or set(row) != {"ordinal", "weight"}:
            fail("후보 번호와 가중치를 지정하십시오.")
        ordinal = row["ordinal"]
        if type(ordinal) is not int or not 0 <= ordinal < total or ordinal in weighted:
            fail("연구 내 후보 번호를 중복 없이 지정하십시오.")
        weight = finite(row["weight"], "joint_probabilities.weights")
        if not 0 <= weight <= 1e6:
            fail("후보 가중치는 0~1000000이어야 합니다.")
        weighted[ordinal] = Fraction(str(weight))
    summed = sum(weighted.values())
    if not summed:
        fail("후보 가중치는 하나 이상 양수여야 합니다.")
    weighted = dict(sorted(weighted.items()))
    distribution = {ordinal: weight / summed for ordinal, weight in weighted.items()}
    detail = {"scope": "user_assumed_joint_discrete_all_targets", "source_label": label,
              "unlisted_weight": 0, "manufacturing_validation": "not_established",
              "weights": [{"ordinal": ordinal, "weight": float(weight), "probability": float(distribution[ordinal])}
                          for ordinal, weight in weighted.items()]}
    return detail, distribution


def _probability_totals(distribution, outcomes):
    """! @brief 확인된 통과, 실패와 미확인 후보의 질량을 정확한 분수로 합친다."""
    passing, failing = Fraction(0), Fraction(0)
    unresolved = []
    for ordinal, mass in distribution:
        if not mass:
            continue
        outcome = outcomes.get(ordinal)
        if outcome is True:
            passing += mass
        elif outcome is False:
            failing += mass
        else:
            unresolved.append(ordinal)
    unknown = 1 - passing - failing
    return {"passing_mass": float(passing), "failing_mass": float(failing), "unresolved_mass": float(unknown),
            "pass_probability_bounds": [float(passing), float(1 - failing)],
            "unresolved_ordinals": unresolved, "all_positive_mass_evaluated": not unresolved}


def _next_candidate(study, definition, source, rows):
    """! @brief 봉인 평가가 있는 한 축 이웃 사이의 아직 검토하지 않은 점을 제안한다."""
    from bisect import bisect_left
    from copy import deepcopy

    from rfad.domain.design_sweep import _indices, candidate_at
    from rfad.domain.units import Quantity

    specification = definition["specification"]
    variables = specification["variables"]
    total = study["counts"]["total"]
    grid = [[value if type(value) is str else value["value_si"] for value in variable["values"]]
            for variable in variables]
    indices = [_indices(specification, ordinal) for ordinal in range(total)]
    points = [tuple(values[index] for values, index in zip(grid, coordinate)) for coordinate in indices]
    occupied = set(points)
    ranked = {row["ordinal"]: row for row in rows}
    rank_order = {row["ordinal"]: position for position, row in enumerate(rows)}
    numeric = {axis: sorted(set(values)) for axis, values in enumerate(grid)
               if variables[axis]["dimension"] != "state" and all(value is not None for value in values)}
    circuit = None if definition["network"] is None else definition["network"]["circuit"]
    for basis in rows:
        pivot = points[basis["ordinal"]]
        neighbors = []
        for axis, values in numeric.items():
            position = bisect_left(values, pivot[axis])
            for other in values[max(0, position - 1):position] + values[position + 1:position + 2]:
                peer = pivot[:axis] + (other,) + pivot[axis + 1:]
                matches = [ordinal for ordinal in ranked if points[ordinal] == peer]
                if matches:
                    neighbors.append((min(matches, key=rank_order.get), axis))
        for ordinal, axis in sorted(neighbors, key=lambda row: (rank_order[row[0]], row[1])):
            origin, other = pivot[axis], points[ordinal][axis]
            middle = float((Fraction(origin) + Fraction(other)) / 2)
            coordinates = pivot[:axis] + (middle,) + pivot[axis + 1:]
            if coordinates in occupied:
                continue
            original = variables[axis]["values"][indices[basis["ordinal"]][axis]]
            quantity = Quantity(middle, original["dimension"], original["display_unit"], "estimated",
                                [f"TraceWave {study['study_id']} 후보 {basis['ordinal'] + 1}, {ordinal + 1}"]).to_dict()
            proposal = deepcopy(specification)
            proposal.update(name=specification["name"][:245] + " / 후속 후보", combination="cartesian", rows=[])
            for variable, index in zip(proposal["variables"], indices[basis["ordinal"]]):
                variable["values"] = [variable["values"][index]]
            proposal["variables"][axis]["values"] = [quantity]
            candidate = candidate_at(source, proposal, 0, circuit=circuit)
            if candidate["status"] != "valid":
                continue
            return {"status": "proposed", "revision_id": source["revision_id"],
                    "basis_ordinal": basis["ordinal"], "neighbor_ordinal": ordinal,
                    "assessment_sha256": [basis["assessment_sha256"], ranked[ordinal]["assessment_sha256"]],
                    "axis": {"kind": variables[axis]["kind"], "id": variables[axis]["id"]},
                    "text": format(Quantity(**quantity).as_unit(original["display_unit"]), ".15g"),
                    "unit": original["display_unit"], "specification": proposal}
    return {"status": "no_distinct_valid_bracket"}


def read(service, study, definition, source, project, weights=None, tolerance=False, probabilities=None, suggest_next=False,
         *, joint_probabilities=None, process_samples=None):
    """! @brief 현재 설계나 결과를 바꾸지 않고 연구에 소속된 봉인 평가만 사용한다."""
    specification = definition["specification"]
    ids = specification["target_ids"]
    if (probabilities is not None or joint_probabilities is not None) and not tolerance:
        fail("공차 검토를 선택한 경우에만 이산 분포를 적용합니다.")
    axes = tolerance_axes(specification) if tolerance else []
    if tolerance and (not axes or not ids):
        fail("공차 모서리는 목표와 오름차순 최소·공칭·최대값을 가진 카테시안 설계 또는 회로 연구가 필요합니다.",
             "E_UNSUPPORTED")
    weights = _weights(ids, weights)
    probability_axes = _probability_axes(axes, probabilities)
    total = study["counts"]["total"]
    joint = _joint_distribution(axes, joint_probabilities, total)
    samples = read_samples(process_samples, axes) if process_samples is not None else None
    probability_outcomes = {}
    targets = {row["id"]: row["name"] for row in source["targets"]}
    root = project["path"] + "/sweeps/" + study["study_id"] + "/results/"
    vectors, hashes, dataset_hashes, excluded = {}, {}, {}, Counter()
    traces = {}
    sample_cases = set()
    if tolerance:
        nominal = (total - 1) // 2
        steps = [3**index for index in range(len(axes))]
        sample_cases = {nominal, *(nominal + direction * step for step, direction in product(steps, (-1, 1)))}
        sample_cases.update(nominal + sign_a * a + sign_b * b for a, b in combinations(steps, 2)
                            for sign_a, sign_b in product((-1, 1), repeat=2))
    for ordinal in range(total):
        row = load_candidate(service, study, ordinal)
        if row is None or row["state"] != "completed":
            excluded["not_completed"] += 1
            continue
        if not ids:
            excluded["no_targets"] += 1
            continue
        reference = row["results"].get("assessment")
        dataset = row["results"].get("dataset")
        if reference is None or dataset is None:
            excluded["unavailable_assessment"] += 1
            continue
        if not all(item["uri"].startswith(root) for item in (reference, dataset)):
            fail("후보 순위에 사용하려는 자료가 연구 저장 영역에 속하지 않습니다.", "E_HASH")
        record = read_json(service, reference)
        if record.get("schema") != "rfad.sweep-assessments/0.1":
            fail("후보 순위에서 지원하는 평가 원문 버전이 다릅니다.", "E_VERSION")
        indexed = {item["target_id"]: item for item in record["assessments"]}
        if set(indexed) != set(ids) or len(indexed) != len(record["assessments"]):
            fail("봉인한 후보 평가와 연구 목표 목록이 다릅니다.", "E_HASH")
        key = dataset["uri"], dataset["sha256"], dataset["bytes"]
        if key not in dataset_hashes:
            dataset_hashes[key] = canonical_hash_from_bytes(service.journal.read_artifact(dataset))
        if any(item["evidence"]["dataset_hash"] != dataset_hashes[key] for item in indexed.values()):
            fail("봉인한 후보 평가에 대응한 데이터셋 해시가 다릅니다.", "E_HASH")
        if ordinal in sample_cases:
            traces[ordinal] = {identity: _s11_trace(indexed[identity], ordinal == nominal) for identity in ids}
        scores = [target_score(indexed[identity]) for identity in ids]
        if probability_axes is not None or joint is not None or samples is not None:
            failed = any(point["status"] == "fail" for item in indexed.values() for criterion in item["criteria"]
                         for point in criterion["points"])
            if failed or all(score == 1 for score in scores):
                probability_outcomes[ordinal] = not failed
        if None in scores:
            excluded["incomplete_targets"] += 1
            continue
        vectors[ordinal], hashes[ordinal] = scores, reference["sha256"]
    ranks = fronts(vectors)
    rows = [{"ordinal": index, "front": ranks[index],
             "target_scores": [float(value) for value in vectors[index]], "assessment_sha256": hashes[index]}
            for index in sorted(ranks, key=lambda index: (ranks[index], index))]
    report = {"profile": "rfad.sweep-target-ranking/0.1", "study_id": study["study_id"],
              "definition_sha256": study["definition"]["sha256"], "total": total, "ranked": len(rows),
              "scope": "pareto_worst_criterion_sample_pass_fraction", "continuous_band_verified": False,
              "targets": [{"id": identity, "name": targets[identity]} for identity in ids],
              "excluded": dict(sorted(excluded.items())), "items": rows}
    if weights is not None:
        total_weight = sum(weights)
        normalized = [value / total_weight for value in weights]
        scores = {index: sum(a * b for a, b in zip(vector, normalized))
                  for index, vector in vectors.items()}
        rows.sort(key=lambda row: (-scores[row["ordinal"]], row["front"], row["ordinal"]))
        for row in rows:
            row["weighted_score"] = float(scores[row["ordinal"]])
        report["weights"] = [{"id": identity, "weight": float(raw), "normalized_weight": float(value)}
                             for identity, raw, value in zip(ids, weights, normalized)]
        report["scope"] = "weighted_worst_criterion_sample_pass_fraction"
    if tolerance:
        report["tolerance_analysis"] = _tolerance_report(axes, ids, vectors, traces)
        if probability_axes is not None:
            distribution = ((index, math.prod(weights)) for index, weights in enumerate(product(*probability_axes)))
            report["tolerance_analysis"]["discrete_probability"] = {
                "scope": "user_assumed_independent_discrete_all_targets",
                "distributions": [{"kind": axis["kind"], "id": axis["id"], "probability": list(map(float, values))}
                                  for axis, values in zip(axes, probability_axes)],
                **_probability_totals(distribution, probability_outcomes)}
        if joint is not None:
            detail, distribution = joint
            report["tolerance_analysis"]["discrete_probability"] = {
                **detail, **_probability_totals(distribution.items(), probability_outcomes)}
    if samples is not None:
        report["tolerance_analysis"]["process_samples"] = compare_samples(samples, probability_outcomes)
    if suggest_next:
        report["next_candidate"] = _next_candidate(study, definition, source, rows)
    return {**report, "ranking_sha256": canonical_hash(report)}
