"""! @brief 시료/교정 기록과 정렬/비교의 검토, 원자 적용과 과거 조회를 연결한다."""

import base64
from copy import deepcopy
import hashlib
import re
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application import measurement_contract as contract
from rfad.application import measurement_forms as forms, measurement_records as records
from rfad.application.network_records import reference
from rfad.application.project_contract import MAX_HISTORY
from rfad.application.project_history import ProjectHistory
from rfad.application.result_sources import read_json, revision_document, owned_reference
from rfad.application.sweep_copy import BufferedRepository
from rfad.domain import measurement
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import validate_name
from rfad.storage.journal import MAX_STATE_BYTES

PROFILE, READS, MUTATIONS = contract.PROFILE, contract.READS, contract.MUTATIONS


def _context(service, state, project, context, data):
    """! @brief 현재 또는 명시 과거 개정의 기록 목록을 읽으며 빈 확장을 만들지 않는다."""
    current = service._load(project)
    revision = current["revision_id"] if data["revision_id"] is None else data["revision_id"]
    document, _ = revision_document(service, state, project, context["project_id"], revision)
    model = measurement.registry(document)
    previous = {row["previous_record_id"] for row in model["records"]}
    if data["offset"] > len(model["records"]):
        contract.fail("측정 기록 목록의 시작 순번이 범위를 벗어났습니다.")
    items = []
    for entry in model["records"][data["offset"]:data["offset"] + data["limit"]]:
        ref = records.creation_reference(state, context["project_id"], entry)
        loaded = records.load_record(service, state, project, ref)
        items.append({"record_ref": ref, "name": entry["name"], "previous_record_id": entry["previous_record_id"],
            "is_latest": entry["id"] not in previous, "data_class": loaded["record"]["data_class"],
            "summary": records.summary(loaded["record"], loaded["source"]["dataset"])})
    offset = data["offset"] + len(items)
    snapshots = [{"id": key, "revision_id": value["revision_id"], "content_hash": value["content_hash"],
                  "description": value.get("description", "")} for key, value in state["snapshots"].items()
                 if value["project_id"] == context["project_id"]]
    return contract.bounded({"profile": PROFILE, "project_id": context["project_id"], "revision_id": revision,
        "current_revision_id": current["revision_id"], "items": items, "offset": data["offset"], "total": len(model["records"]),
        "next_offset": offset if offset < len(model["records"]) else None,
        **{collection: [{"record_ref": records.creation_reference(state, context["project_id"], row), "name": row["name"]} for row in model[collection]]
           for collection in ("alignments", "comparisons")},
        "attachments": records.attachments(state, context["project_id"]), "snapshots": snapshots,
        "form": forms.form(None, contract.now_text(service)),
        "limits": {"records_per_kind": measurement.MAX_RECORDS, "record_bytes": measurement.MAX_BYTES,
            "registry_bytes": measurement.MAX_BYTES, "samples": 1001, "page_size": 201,
            "attachment_bytes": contract.MAX_ATTACHMENT_BYTES, "attachments_per_project": contract.MAX_ATTACHMENTS,
            "attachment_total_bytes": contract.MAX_ATTACHMENT_TOTAL},
        "capabilities": {"record": True, "import_record": True, "align": ["permute_ports", "renormalize", "linear_ri"],
                         "compare_record": True, "advanced_deembedding": False, "uncertainty_propagation": False},
        "physical_acceptance": "not_established"})


def _preflight_files(service, staged, files, response):
    """! @brief 실제 명령/역명령을 준비한 뒤 저장 상한과 모든 기존 파일 충돌을 먼저 검사한다."""
    state_bytes = len(canonical_bytes(staged)) + len(canonical_bytes(response)) + 4096
    if state_bytes > MAX_STATE_BYTES:
        contract.fail("측정 기록과 요청 영수증이 journal 보존 상한을 초과했습니다.", "E_RESOURCE")
    total = 0
    for path, raw in files.items():
        if type(raw) is not bytes or not 0 < len(raw) <= 8 * 1024 * 1024:
            contract.fail("측정 산출물이 기존 artifact 상한을 초과했습니다.", "E_RESOURCE")
        existing = service.journal._safe_path(path)
        if existing.exists():
            service.journal.verify_file(reference(path, raw))
        else:
            total += len(raw)
    service.journal._check_space(total + state_bytes + 4096)


def _prepare(service, state, context, data, command_id):
    """! @brief 미리보기/적용 모두 같은 명령 이력을 메모리에서 검증해 원자 게시를 준비한다."""
    from rfad.application import measurement_candidates as candidates

    project, document = records.current(service, state, context, data["expected_revision"])
    output, payload, files, fingerprint = candidates.build(service, state, project, document, data)
    repository = BufferedRepository(service.repository)
    staged = deepcopy(state)
    applied = ProjectHistory(repository).apply(staged, context,
        {"command_id": command_id, "expected_revision": data["expected_revision"], "type": contract.WORKSPACE_COMMAND, "payload": payload},
        limit=MAX_HISTORY)
    files.update(repository.blobs)
    staged["commands"][command_id]["measurement"] = {"operation": data["operation"], "review_hash": fingerprint,
        "record_id": output["record_id"], "record_artifact": deepcopy(output["record_artifact"]),
        "draft_time_utc": data["draft_time_utc"], "engine": deepcopy(output["engine"])}
    response = {**applied, "operation": data["operation"], "record_id": output["record_id"], "dataset_id": output["dataset_id"],
                "record_artifact": deepcopy(output["record_artifact"]), "review_hash": fingerprint,
                "record_ref": {"id": output["record_id"], "sha256": output["record_artifact"]["sha256"], "revision_id": applied["new_revision"]}}
    _preflight_files(service, staged, files, response)
    preview = {"profile": PROFILE, "project_id": context["project_id"], "revision_id": document["revision_id"],
        **output, "can_apply": True, "review_hash": fingerprint,
        "record_ref": {"id": output["record_id"], "sha256": output["record_artifact"]["sha256"], "revision_id": None},
        "artifact_count": len(files), "artifact_bytes": sum(len(raw) for raw in files.values())}
    return contract.bounded(preview), staged, files, contract.bounded(response)


def _receipt(service, state, context, data):
    """! @brief 영수증 미발견/만료를 미생성 증거로 바꾸지 않는다."""
    receipt = state["receipts"].get(canonical_hash([data["request_key_epoch"], data["request_key"]]))
    if receipt is not None and (receipt["scope"] != context or receipt["method"] not in MUTATIONS):
        contract.fail("다른 프로젝트 또는 기능의 측정 영수증입니다.", "E_CONFLICT")
    found = receipt is not None and receipt["expires_at"] > service._now()
    return {"profile": PROFILE, "project_id": context["project_id"], "authoritative": True,
        "status": "found" if found else "expired" if receipt is not None else "unresolved",
        "response": deepcopy(receipt["response"]) if found else None, "may_resubmit": False}


def _attachment_add(service, state, context, data):
    """! @brief 원문 첨부를 실행하지 않고 제한된 불변 자료로 보관한다."""
    project = service._project(state, context)
    validate_name(data["name"])
    if data["role"] not in contract.ATTACHMENT_ROLES or type(data["media_type"]) is not str or re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", data["media_type"]) is None:
        contract.fail("첨부 원문의 역할 또는 명시 media type이 유효하지 않습니다.")
    encoded = data["content_base64"]
    if type(encoded) is not str or not 0 < len(encoded) <= ((contract.MAX_ATTACHMENT_BYTES + 2) // 3) * 4:
        contract.fail("측정 첨부 원문은 파일당 512 KiB 이하입니다.", "E_RESOURCE")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeError) as error:
        raise ProjectError("E_SCHEMA", "첨부 원문의 base64를 읽을 수 없습니다.") from error
    if not raw or len(raw) > contract.MAX_ATTACHMENT_BYTES or base64.b64encode(raw).decode("ascii") != encoded:
        contract.fail("첨부 원문이 유한 정규 base64 계약과 다릅니다.", "E_RESOURCE")
    if data["sha256"] != hashlib.sha256(raw).hexdigest():
        contract.fail("첨부 원문의 선언 hash와 실제 바이트가 다릅니다.", "E_HASH")
    identity = str(uuid5(UUID(context["project_id"]), "measurement-attachment:" + canonical_hash({key: data[key] for key in ("name", "role", "media_type", "sha256")})))
    existing = state.get("measurement_attachments", {}).get(identity)
    if existing is not None:
        if existing["project_id"] != context["project_id"]:
            contract.fail("첨부 원문의 소유 프로젝트가 다릅니다.", "E_CONFLICT")
        service.journal.verify_file(owned_reference(project, existing["descriptor"]["artifact"]))
        return {"project_id": context["project_id"], "attachment_id": identity, **deepcopy(existing["descriptor"])}
    current = records.attachments(state, context["project_id"])
    if len(current) >= contract.MAX_ATTACHMENTS or sum(row["artifact"]["bytes"] for row in current) + len(raw) > contract.MAX_ATTACHMENT_TOTAL:
        contract.fail("측정 첨부는 프로젝트당 16개/합계 8 MiB 이내입니다. 기존 원문을 지우지 않습니다.", "E_RESOURCE")
    path = project["path"] + "/measurement-attachments/" + identity + "/source.bin"
    descriptor = {"id": identity, "name": data["name"], "role": data["role"], "media_type": data["media_type"], "artifact": reference(path, raw)}
    staged = deepcopy(state)
    staged.setdefault("measurement_attachments", {})[identity] = {"project_id": context["project_id"], "descriptor": descriptor}
    response = {"project_id": context["project_id"], "attachment_id": identity, **deepcopy(descriptor)}
    _preflight_files(service, staged, {path: raw}, response)
    service.verify_calculation()
    service.journal.put_immutable(path, raw)
    state["measurement_attachments"] = staged["measurement_attachments"]
    return response


def _lineage_rows(report):
    """! @brief 봉인 계보에서 주파수, 원본 순번과 가중치의 조회 행을 구성한다."""
    rows = []
    operations = report["normalized_specification"]["operations"]
    for index, (operation, lineage) in enumerate(zip(operations, report["lineage"], strict=True), 1):
        kind = operation["kind"]
        if kind == "linear_ri":
            values = zip(operation["frequency_hz"], lineage["samples"], strict=True)
            for frequency, (left, right, weight) in values:
                rows.append({"operation": index, "frequency_hz": frequency, "source_indices": [left, right],
                    "weight": weight, "kind": "정확 원문" if left == right else "선형 RI 보간",
                    "reason": "보존된 원래 표본 순번과 오른쪽 표본 가중치입니다."})
        elif kind == "permute_ports":
            rows.append({"operation": index, "source_indices": operation["order"], "kind": "포트 순열",
                         "reason": "같은 표본에서 양쪽 행렬 축과 포트 조건을 재배열했습니다."})
        else:
            rows.append({"operation": index, "kind": "Z0 재정규화",
                         "reason": "명시 기준 임피던스로 변환한 표본의 실제 입력은 원문과 적용 범위에 보존합니다."})
    return rows


def _history(service, state, project, context, data):
    """! @brief 이전 정렬/비교 보고서는 오늘의 엔진으로 재계산하지 않고 고정 페이지로 읽는다."""
    collection, selected, section = data["collection"], data["record"], data["section"]
    if collection not in ("alignments", "comparisons") or section not in ("summary", "points", "conditions", "lineage"):
        contract.fail("지원하지 않는 측정 이력 조회입니다.")
    document, _ = revision_document(service, state, project, context["project_id"], selected["revision_id"])
    entry = next((row for row in measurement.registry(document)[collection] if row["id"] == selected["id"]), None)
    if entry is None or entry["artifact"]["sha256"] != selected["sha256"]:
        contract.fail("선택한 측정 이력의 개정 또는 hash가 다릅니다.", "E_HASH")
    selected = records.creation_reference(state, context["project_id"], entry)
    created, _ = revision_document(service, state, project, context["project_id"], selected["revision_id"])
    if entry not in measurement.registry(created)[collection]:
        contract.fail("측정 이력의 생성 개정에 같은 원문 참조가 없습니다.", "E_HASH")
    report = read_json(service, project, entry["artifact"])
    schema = "rfad.measurement-alignment-record/0.1" if collection == "alignments" else "rfad.measurement-comparison-record/0.1"
    if report.get("schema") != schema or report.get("id") != entry["id"] or report.get("name") != entry["name"]:
        contract.fail("측정 이력의 내용과 색인이 다릅니다.", "E_HASH")
    result = {"profile": PROFILE, "project_id": context["project_id"], "record_ref": deepcopy(selected),
              "collection": collection, "section": section, "name": report["name"], "physics_validated": False}
    if section == "summary":
        if collection == "alignments":
            result.update({key: deepcopy(report[key]) for key in ("draft_time_utc", "input", "normalized_specification", "dataset_id", "dataset", "execution", "host_source", "original_record", "uncertainty_propagation")})
            result["source"] = {"kind": "network", "dataset_id": report["dataset_id"], "revision_id": selected["revision_id"], "snapshot_id": None}
        else:
            result.update({key: deepcopy(report[key]) for key in ("draft_time_utc", "input", "source_revision", "executions", "host_source")})
            result["comparison"] = {key: deepcopy(value) for key, value in report["comparison"].items() if key not in ("points", "condition_differences")}
        return contract.bounded(result)
    if collection == "alignments" and section == "lineage":
        values = _lineage_rows(report)
    elif collection == "comparisons" and section in ("points", "conditions"):
        values = report["comparison"]["points" if section == "points" else "condition_differences"]
    else:
        contract.fail("해당 측정 이력에는 요청한 부분이 없습니다.", "E_UNSUPPORTED")
    if data["offset"] > len(values):
        contract.fail("측정 이력의 시작 순번이 범위를 벗어났습니다.")
    limit = min(data["limit"], 32 if section == "conditions" else 201)
    items = values[data["offset"]:data["offset"] + limit]
    end = data["offset"] + len(items)
    return contract.bounded({**result, "items": items, "offset": data["offset"], "total": len(values),
                             "next_offset": end if end < len(values) else None})


def read(service, method, params):
    """! @brief 원문 조회/검토는 새 프로젝트 개정과 영수증을 만들지 않는다."""
    context, data = contract.validate_read(method, params)
    state = service.journal.read()
    project = service._project(state, context)
    if method == "measurement.context":
        return _context(service, state, project, context, data)
    if method == "measurement.get":
        return records.get(service, state, project, data["record"])
    if method == "measurement.history":
        return _history(service, state, project, context, data)
    if method == "measurement.quantity":
        return contract.bounded({"profile": PROFILE, **forms.quantity(data)})
    if method == "measurement.receipt":
        return _receipt(service, state, context, data)
    if method == "measurement.attachment.read":
        entry = state.get("measurement_attachments", {}).get(data["attachment_id"])
        if entry is None or entry["project_id"] != context["project_id"]:
            contract.fail("현재 프로젝트에 보관한 측정 첨부가 없습니다.", "E_CONFLICT")
        raw = service.journal.read_artifact(owned_reference(project, entry["descriptor"]["artifact"]))
        if data["offset"] > len(raw):
            contract.fail("첨부 조회 시작 위치가 원문 범위를 벗어났습니다.")
        chunk = raw[data["offset"]:data["offset"] + data["limit"]]
        end = data["offset"] + len(chunk)
        return contract.bounded({"profile": PROFILE, **deepcopy(entry["descriptor"]), "offset": data["offset"], "total": len(raw),
            "content_base64": base64.b64encode(chunk).decode("ascii"), "next_offset": end if end < len(raw) else None})
    if method in ("measurement.compare", "measurement.conditions"):
        return contract.bounded(candidates.comparison(service, state, project, context, data, conditions_only=method == "measurement.conditions"))
    try:
        identity = str(uuid5(UUID(context["project_id"]), "measurement-preview:" + canonical_hash(data)))
        return _prepare(service, state, context, data, identity)[0]
    except ProjectError as error:
        return {"profile": PROFILE, "project_id": context["project_id"], "revision_id": service._load(project)["revision_id"],
            "operation": data["operation"], "can_apply": False, "review_hash": None, "record_id": None,
            "record_ref": None, "record": None, "descriptor": None, "page": None, "summary": None,
            "issues": [{"code": error.code, "message": error.message, "details": error.details}]}


def admit(service, state, method, context, data):
    """! @brief 전체 파일과 하나의 명령/역명령을 준비한 뒤 같은 영수증 transaction에 게시한다."""
    contract.validate_input(method, context, data)
    if method == "measurement.attachment.add":
        return _attachment_add(service, state, context, data)
    preview, staged, files, response = _prepare(service, state, context, data, data["command_id"])
    if preview["review_hash"] != data["review_hash"]:
        contract.fail("원본/측정 입력/계산 환경 또는 검토 결과가 바뀌었습니다. 다시 검토하십시오.", "E_CONFLICT")
    service.verify_calculation()
    for path, raw in files.items():
        service.journal.put_immutable(path, raw)
    for key in ("projects", "commands"):
        state[key] = staged[key]
    return response
