"""! @brief 목표 제약/기대 연결/기본 제조 검사를 불변 원본의 제한된 파생 보고서로 조립한다."""

from rfad.domain.check_geometry import footprint, board_clearance
from rfad.domain.check_connections import check_contacts, check_expected
from rfad.domain.check_constraints import check_constraints
from rfad.domain.check_manufacturing import check_vias, check_manufacturing
from rfad.domain.check_report import Report, blocking_diagnostics
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity


def check_design(document, *, inclusion="all", target_ids=None, manufacturing_profile_id=None):
    """! @brief 현재 원본을 변경하지 않고 선언한 범위를 검사한다. CAD/solver는 실행하지 않는다."""
    if inclusion not in ("all","em","export"):
        raise ProjectError("E_UNSUPPORTED", "기본 DRC의 포함 범위를 지원하지 않습니다.")
    known_targets = {row["id"] for row in document["targets"]}
    target_ids = sorted(known_targets if target_ids is None else target_ids)
    if len(set(target_ids)) != len(target_ids) or not set(target_ids) <= known_targets:
        raise ProjectError("E_CONFLICT", "검사 목표가 없거나 중복됩니다.")
    profiles = {row["id"]:row for row in document["manufacturing_profiles"]}
    if manufacturing_profile_id is not None and manufacturing_profile_id not in profiles:
        raise ProjectError("E_CONFLICT", "선택한 제조 규칙이 없습니다.")
    scope = {"inclusion":inclusion,"target_ids":target_ids,"manufacturing_profile_id":manufacturing_profile_id}
    report = Report(document,scope)
    selected_profiles = check_constraints(document,[row for row in document["targets"] if row["id"] in target_ids],report)
    if manufacturing_profile_id is not None:
        selected_profiles.add(manufacturing_profile_id)
    shapes, unknown = {}, {}
    rows = [row for row in document["geometry"] if inclusion == "all" or row["include_in_"+inclusion]]
    if not rows:
        report.add("geometry_coverage","not_evaluated","검사 범위에 도체 형상이 없습니다.",paths=["geometry"])
    for row in rows:
        try:
            shape = footprint(document,row)
            if document.get("pcb", {}).get("holes") or (document.get("board") or {}).get("cutouts"):
                from rfad.application.pcb_exchange_projection import effective_footprint
                shape = effective_footprint(document, row, shape)
            shapes[row["id"]] = shape
            try:
                margin, location = board_clearance(document,shape)
            except ProjectError:
                margin, location = None, None
            report.bound("board_containment",margin,Quantity.from_value(0,"mm",source_refs=["RFAD-D0-3.4/FN-009"]).to_dict(),
                         guard=shape.guard,objects=[row["id"]],paths=["geometry."+row["id"],"board.outline"],
                         location=location)
        except ProjectError as error:
            unknown[row["id"]] = row
            report.add("geometry_coverage","not_evaluated",error.message,objects=[row["id"]],paths=["geometry."+row["id"]])
    thresholds = [profiles[identity]["rules"]["minimum_clearance"]["value_si"] for identity in selected_profiles]
    clearance = max((value * 1000 for value in thresholds if value is not None and value <= 2000), default=0)
    graph,possible,pairs,statistics = check_contacts(document,shapes,unknown,report,clearance,[200000])
    via_measures = check_vias(document,shapes,graph,possible,report)
    connectivity = check_expected(document,graph,possible,unknown,report)
    for identity in sorted(selected_profiles):
        check_manufacturing(document,profiles[identity],shapes,pairs,via_measures,report)
        if unknown:
            report.add("manufacturing_coverage","not_evaluated","치수 미정/미지원 도체가 있어 전체 제조 규칙 합격을 확정하지 않습니다.",
                       objects=sorted(unknown),paths=["manufacturing_profiles."+identity])
    if not selected_profiles:
        report.add("manufacturing_profile","not_evaluated","검사에 적용할 제조 규칙이 지정되지 않았습니다.",paths=["manufacturing_profiles"])
    if "pcb" in document:
        from rfad.application.pcb_exchange_projection import extra_diagnostics
        extra_diagnostics(document, shapes, report)
    return report.result(connectivity,{**statistics,"resolved_shapes":len(shapes),"unresolved_shapes":len(unknown),
                                       "omitted_by_inclusion":len(document["geometry"])-len(rows)})


def declared_diagnostics(document, purpose):
    """! @brief 선언된 강제 제약의 확인된 위반을 기존 입력 차단 경로에 연결한다."""
    declared = document["connections"] or any("constraints" in target for target in document["targets"])
    if not declared and not document.get("pcb", {}).get("keepouts"):
        return []
    report = check_design(document,inclusion={"geometry":"all","em":"em","step":"export"}[purpose])
    failures = blocking_diagnostics(report)
    return failures if declared else [row for row in failures if row["details"]["rule"] == "pcb_keepout"]
