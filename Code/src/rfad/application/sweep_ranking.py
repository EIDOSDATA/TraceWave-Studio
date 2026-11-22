"""! @brief 보존한 후보 목표 표본으로 읽기 전용 다목적 순위를 계산한다."""

from collections import Counter
from fractions import Fraction

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


def read(service, study, definition, source, project, weights=None):
    """! @brief 현재 설계나 결과를 바꾸지 않고 연구에 소속된 봉인 평가만 사용한다."""
    ids = definition["specification"]["target_ids"]
    weights = _weights(ids, weights)
    targets = {row["id"]: row["name"] for row in source["targets"]}
    root = project["path"] + "/sweeps/" + study["study_id"] + "/results/"
    vectors, hashes, dataset_hashes, excluded = {}, {}, {}, Counter()
    total = study["counts"]["total"]
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
        scores = [target_score(indexed[identity]) for identity in ids]
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
    return {**report, "ranking_sha256": canonical_hash(report)}
