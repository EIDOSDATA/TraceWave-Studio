"""! @brief 실제 접촉 성분과 기대 연결을 비교하며 net 이름이나 근접 허용오차로 접합하지 않는다."""

from rfad.domain.boundary_distance import norm, sub
from rfad.domain.check_geometry import scalar, separation
from rfad.domain.errors import ProjectError


def components(graph):
    """! @brief 안정 UUID 순서의 연결 성분을 계산한다."""
    groups, pending = [], set(graph)
    while pending:
        seen, frontier = set(), {min(pending)}
        while frontier:
            current = frontier.pop()
            if current not in seen:
                seen.add(current)
                frontier.update(graph[current] - seen)
        pending.difference_update(seen)
        groups.append(sorted(seen))
    return groups


def _connect(graph, a, b):
    """! @brief 실제 그래프와 불확실 그래프의 간선을 명시적으로 추가한다."""
    graph[a].add(b)
    graph[b].add(a)


def _same_height(document, a, b):
    """! @brief 같은 층 또는 실제 z/thickness를 사용하며 층 이름/순서로 높이를 추정하지 않는다."""
    if a["layer_id"] == b["layer_id"]:
        return True
    layers = {row["id"]:row for row in document["stackup"]}
    try:
        ranges = [(scalar(document, layers[row["layer_id"]]["z_min"]),
                   scalar(document, layers[row["layer_id"]]["thickness"])) for row in (a,b)]
        return max(z for z, _ in ranges) <= min(z+t for z,t in ranges)
    except ProjectError:
        return None


def check_contacts(document, shapes, unknown, report, clearance, budget):
    """! @brief sweep AABB로 후보를 줄이고 모든 근접 경계를 검사한 성분/쌍을 반환한다."""
    graph = {identity:set() for identity in [*shapes, *unknown]}
    possible = {identity:set() for identity in graph}
    ordered = sorted(shapes.values(), key=lambda shape: (shape.bounds[0],shape.source["id"]))
    vias = [shape for shape in ordered if shape.source["kind"] == "via"]
    pairs, tested = [], 0
    for index, a in enumerate(ordered):
        for b in ordered[index+1:]:
            padding = clearance + max(a.guard, b.guard)
            if b.bounds[0] > a.bounds[2] + padding:
                break
            if max(a.bounds[1],b.bounds[1]) > min(a.bounds[3],b.bounds[3]) + padding:
                continue
            if tested >= 4096:
                raise ProjectError("E_RESOURCE", "기본 DRC 근접쌍 예산 4096개를 초과했습니다.")
            tested += 1
            left, right = a.source, b.source
            ids = [left["id"],right["id"]]
            distance,p,q = separation(a,b,budget)
            location = [(p[axis]+q[axis])/2 for axis in (0,1)]
            same_layer = left["layer_id"] == right["layer_id"]
            via_pair = left["kind"] == "via" or right["kind"] == "via"
            drilled = any(norm(sub(location, via.edges[0].center)) <= via.edges[0].radius for via in vias)
            height = None if via_pair else _same_height(document,left,right)
            uncertain = False
            if distance <= max(a.guard,b.guard) and height is not False:
                if via_pair or drilled or distance > 0 or height is None:
                    uncertain = True
                    _connect(possible,*ids)
                    explicit_pad = (left["kind"] == "via" and right["id"] in left["pad_ids"]) or (right["kind"] == "via" and left["id"] in right["pad_ids"])
                    if not explicit_pad:
                        report.add("contact_uncertain", "not_evaluated", "미정 층 높이/미세 경계/비아 절삭의 접촉은 확정하지 않습니다.",
                                   objects=ids, paths=["geometry."+identity for identity in ids], measured=distance, location=location)
                else:
                    _connect(graph,*ids)
                    _connect(possible,*ids)
                    if left["net_id"] is None or right["net_id"] is None:
                        report.add("net_contact", "not_evaluated", "실제 접촉 도체의 net이 미정입니다.",objects=ids,location=location)
                    elif left["net_id"] != right["net_id"]:
                        report.add("different_net_short", "failed", "다른 net의 도체가 실제로 접합니다.",objects=ids,
                                   paths=["geometry."+identity for identity in ids],measured=0.0,limit=0.0,location=location)
            if same_layer and not via_pair:
                pairs.append((a,b,distance,location,uncertain or drilled))
    for identity in unknown:
        for other in graph:
            if other != identity:
                _connect(possible,identity,other)
    return graph,possible,pairs,{"near_pairs":tested,"boundary_pairs":200000-budget[0],
                                 "broad_phase":"sweep_aabb_with_analytic_extrema", "automatic_snap_tolerance_mm":0.0}


def check_expected(document, graph, possible, unknown, report):
    """! @brief 의도적 분리/기생 도체의 DC 절연과 RF 결합 평가를 구분한다."""
    actual_groups, possible_groups = components(graph), components(possible)
    actual = {identity:index for index,group in enumerate(actual_groups) for identity in group}
    maybe = {identity:index for index,group in enumerate(possible_groups) for identity in group}
    for row in document["connections"]:
        a,b = row["object_ids"]
        status = "not_evaluated"
        message = "객체 참조/포함 범위 또는 접촉 치수가 미정입니다."
        if a in actual and b in actual:
            connected = actual[a] == actual[b]
            uncertain = not connected and maybe[a] == maybe[b]
            if not uncertain:
                expected = row["kind"] == "connected"
                status = "passed" if connected == expected else "failed"
                message = "기대 연결과 실제 도체 성분을 비교했습니다. 기생 도체의 RF 결합은 별도입니다."
        report.add("expected_"+row["kind"],status,message,objects=[identity for identity in (a,b) if identity is not None],
                   paths=["connections."+row["id"]],sources=row["source_refs"],details={"connection_id":row["id"]})
    return {"components":[group for group in actual_groups if any(identity not in unknown for identity in group)],
            "unresolved_object_ids":sorted(unknown), "possible_components":possible_groups,
            "declared_net_is_connection":False,"parasitic_rf_coupling_evaluated":False}
