"""! @brief 보존 개정과 결과 목록을 작은 페이지로 읽고 선택 중 가변 alias를 고정한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _uuid
from rfad.application.result_sources import fail, revision_document, solver_labels
from rfad.domain.network_library import digest, library


def page(items, data, *, maximum=25):
    """! @brief 순번과 목록 hash를 대조하여 서로 다른 목록의 페이지를 섞지 않는다."""
    offset, limit = data["offset"], data["limit"]
    if type(offset) is not int or offset < 0 or (offset >= len(items) and offset != 0) or type(limit) is not int or not 1 <= limit <= maximum:
        fail("목록 시작 위치 또는 페이지 크기가 유효하지 않습니다.", "E_RESOURCE")
    identity = canonical_hash(items)
    if data["catalog_hash"] is not None:
        digest(data["catalog_hash"], "catalog_hash")
        if data["catalog_hash"] != identity:
            fail("결과 목록이 바뀌었습니다. 첫 페이지부터 다시 조회하십시오.", "E_CONFLICT")
    elif offset != 0:
        fail("후속 목록 페이지에는 첫 페이지의 목록 hash가 필요합니다.")
    selected = items[offset:offset + limit]
    return {"catalog_hash": identity, "items": deepcopy(selected), "offset": offset, "total": len(items),
            "next_offset": offset + len(selected) if offset + len(selected) < len(items) else None}


def _bounded(result):
    """! @brief 목록을 조용히 자르지 않고 작은 응답 예산을 검사한다."""
    if len(canonical_bytes(result)) > 128 * 1024:
        fail("결과 목록이 128 KiB를 초과했습니다. 작은 페이지를 요청하십시오.", "E_RESOURCE")
    return result


def revisions(service, context, data):
    """! @brief 실제 보존 참조만 열거하고 표시 이름과 선택 UUID를 분리한다."""
    state = service.journal.read()
    project = service._project(state, context)
    current = service._load(project)
    anchors = [{"revision_id": identity, "snapshot_id": None, "reference": reference}
               for identity, reference in sorted(project["revisions"].items())]
    anchors.extend({"revision_id": value["revision_id"], "snapshot_id": identity, "reference": value["artifact"]}
                   for identity, value in sorted(state["snapshots"].items()) if value["project_id"] == context["project_id"])
    result = page(anchors, data)
    rows = []
    for index, anchor in enumerate(result["items"], result["offset"]):
        document, snapshot = revision_document(service, state, project, context["project_id"], anchor["revision_id"], anchor["snapshot_id"])
        metadata = document["metadata"]
        rows.append({"revision_id": document["revision_id"], "snapshot_id": anchor["snapshot_id"],
            "revision_hash": canonical_hash(document), "name": metadata["name"],
            "revision_label": metadata["name"] + " / 보존 개정 " + str(index + 1),
            "description": metadata["description"] if snapshot is None else snapshot["description"],
            "modified_at": metadata["modified_at"], "sealed_at": None if snapshot is None else snapshot["sealed_at"],
            "is_current": document["revision_id"] == current["revision_id"], "has_network_library": bool(library(document)["datasets"])})
    return _bounded({"profile": "rfad.result-revisions/0.1", "project_id": context["project_id"], **result, "items": rows})


def sources(service, context, data):
    """! @brief 개정별 자료/봉인 해석/한 연구의 후보를 배열 원문 없이 목록화한다."""
    from rfad.application.design_sweep_store import load_candidate

    state = service.journal.read()
    project = service._project(state, context)
    current = service._load(project)
    kind = data["kind"]
    anchors, revision = [], None
    if kind in ("network", "all"):
        if kind == "all" and any(data[key] is not None for key in ("revision_id", "snapshot_id", "study_id")):
            fail("현재 개정 전체 결과에는 별도 개정이나 연구를 지정할 수 없습니다.")
        if data["study_id"] is not None or data["revision_id"] is None and data["snapshot_id"] is not None:
            fail("자료 목록의 개정/snapshot 선택이 유효하지 않습니다.")
        revision = current["revision_id"] if data["revision_id"] is None else data["revision_id"]
        document, _ = revision_document(service, state, project, context["project_id"], revision, data["snapshot_id"])
        anchors = [{"source": {"kind": "network", "dataset_id": item["id"], "revision_id": revision, "snapshot_id": data["snapshot_id"]},
                    "label": item["name"], "source_kind": item["kind"], "source_revision_id": revision,
                    "source_time": None, "result_state": "recorded", "has_dataset": True,
                    "reference": item["dataset"]} for item in library(document)["datasets"]]
    if kind in ("solver", "all"):
        if any(data[key] is not None for key in ("revision_id", "snapshot_id", "study_id")):
            fail("해석 목록에는 다른 개정/연구 anchor를 지정할 수 없습니다.")
        labels = solver_labels(state, context["project_id"])
        entries = reversed(labels.items()) if kind == "all" else labels.items()
        solver_rows = []
        for identity, display in entries:
            record = state["solver_results"][identity]
            if kind == "all" and record["snapshot"]["revision_id"] != revision:
                continue
            supported = record.get("metadata", {}).get("profile") in ("rfad.openems.pcb-single-port/0.1", "rfad.openems.reference-benchmark/0.1")
            solver_rows.append({"source": {"kind": "solver", "artifact_id": identity},
                **display,
                "source_kind": "solver", "source_revision_id": record["snapshot"]["revision_id"],
                "result_state": "completed", "has_dataset": supported,
                "unavailable_reason": None if supported else "이 profile은 공통 복소 투영을 지원하지 않습니다. 원래 해석 결과 조회를 사용하세요.",
                "reference": record["normalized"]})
        anchors = solver_rows + list(reversed(anchors)) if kind == "all" else solver_rows
    elif kind == "sweep":
        if data["revision_id"] is not None or data["snapshot_id"] is not None:
            fail("후보 목록에는 별도 개정 anchor를 지정할 수 없습니다.")
        _uuid(data["study_id"])
        study = state.get("sweeps", {}).get(data["study_id"])
        if study is None or study["project_id"] != context["project_id"]:
            fail("현재 프로젝트의 연구를 찾을 수 없습니다.", "E_CONFLICT")
        anchors = [{"source": {"kind": kind, "study_id": study["study_id"], "index": index},
                    "label": study["name"] + " / 후보 " + str(index + 1), "source_kind": "sweep",
                    "source_revision_id": study["snapshot"]["revision_id"], "source_time": None,
                    "reference": study["records"].get(str(index))} for index in range(study["counts"]["total"])]
    elif kind != "network":
        fail("지원하지 않는 결과 목록 종류입니다.", "E_UNSUPPORTED")
    result = page(anchors, data)
    for item in result["items"]:
        item.pop("reference")
        if kind == "sweep":
            candidate = load_candidate(service, study, item["source"]["index"])
            item["result_state"] = "planned" if candidate is None else candidate["state"]
            item["has_dataset"] = candidate is not None and "dataset" in candidate["results"]
        item["available_views"] = {"network": item["has_dataset"]}
    current_id = current["revision_id"]
    totals = {"network": len(library(current)["datasets"]),
              "solver": sum(record["project_id"] == context["project_id"] and record["snapshot"]["revision_id"] == current_id
                            for record in state["solver_results"].values())}
    return _bounded({"profile": "rfad.result-source-list/0.1", "project_id": context["project_id"],
                     "resolved_revision_id": revision, "current_totals": totals, **result})
