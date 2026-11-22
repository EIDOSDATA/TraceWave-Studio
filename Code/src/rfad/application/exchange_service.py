"""! @brief 도면의 고정 입력 검토, 작업 접수와 보존된 패키지 조회를 연결한다."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from rfad.application import exchange_contract as contract
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from rfad.domain import drawing_annotations
from rfad.domain.drawing_layout import layout
from rfad.domain.object_names import display_names, name_dto, object_label
from rfad.storage.journal import MAX_STATE_BYTES


def bounded(value):
    """! @brief 페이지/원문이 응답 한도를 넘으면 잘라 성공으로 표시하지 않는다."""
    if len(canonical_bytes(value)) > contract.MAX_RESPONSE_BYTES:
        raise ProjectError("E_RESOURCE", "출력 조회 응답이 유한 상한을 초과했습니다.")
    return value


def owned_job(service, state, context, job_id):
    """! @brief 출력의 소유 프로젝트와 실제 작업 종류를 대조한다."""
    service._project(state, context)
    contract.identity(job_id)
    job = state["jobs"].get(job_id)
    if job is None or job.get("context") != context or job.get("operation_method") not in ("geometry.build", "export.build", "export.verify"):
        raise ProjectError("E_CONFLICT", "출력 작업이 선택한 프로젝트에 속하지 않습니다.")
    return job


def result(job):
    """! @brief 완료 event의 보존된 결과만 반환한다."""
    if job["state"] == "completed":
        return next((deepcopy(event["operation_result"]) for event in reversed(job["events"]) if "operation_result" in event), None)
    return None


def manifest_reference(job):
    """! @brief 게시 완료 패키지의 명시적인 manifest만 고른다."""
    value = result(job)
    if value is None:
        raise ProjectError("E_CONFLICT", "완료된 출력만 다시 검수할 수 있습니다.")
    matches = [item for item in value.get("artifacts", []) if item.get("role") == "manifest"]
    if len(matches) != 1:
        raise ProjectError("E_HASH", "출력 manifest 참조가 누락되거나 중복되었습니다.")
    return matches[0]


def source(service, state, context, data, run_id):
    """! @brief 현재 편집 내용 대신 명시적으로 등록된 스냅샷을 읽는다."""
    service._project(state, context)
    snapshot = state["snapshots"].get(data["snapshot"]["snapshot_id"])
    if snapshot is None or snapshot["project_id"] != context["project_id"] or snapshot["content_hash"] != data["snapshot"]["content_hash"]:
        raise ProjectError("E_HASH", "출력 스냅샷의 소유권 또는 내용 hash가 다릅니다.")
    document = service._load({"current": snapshot["artifact"]})
    return document, snapshot, contract.build_input(document, snapshot, data, run_id)


def display_omissions(document, omissions):
    """! @brief 누락 사유/식별자는 보존하고 당시 원본의 이름만 조회용으로 덧붙인다."""
    labels = display_names(document)
    names = {row["id"]: name_dto(document, row, labels=labels) for row in document["geometry"]}
    if document.get("board"):
        names[document["board"]["id"]] = name_dto(document, document["board"], "board")
    names.update({row["id"]: {"name": row["name"], "name_state": "stored", "label": row["name"]} for row in document["ports"]})
    physical = document["extensions"].get("rfad.physical_setup", {})
    names.update({row["id"]: {"name": row["name"], "name_state": "stored", "label": row["name"]}
                  for key in ("surfaces", "parts") for row in physical.get(key, [])})
    names.update({row["id"]: {"name": row["name"], "name_state": "stored", "label": row["name"]}
                  for key in ("holes", "footprints", "artwork_layers", "apertures", "keepouts") for row in document.get("pcb", {}).get(key, [])})
    names.update({row["id"]: {"name": row["name"], "name_state": "stored", "label": row["name"]}
                  for row in (document.get("board") or {}).get("cutouts", [])})
    descriptions = {"outside_selected_footprint": "선택한 부품 밖의 객체로 파일에서 제외; 원문은 sidecar에 보존",
                    "sidecar_only_rf_port": "RF 포트와 기준면 의미는 원문 sidecar에 보존",
                    "sidecar_only_footprint_ownership": "패턴 기하는 출력; 부품 소유와 핀 편집 의미는 원문 sidecar에 보존",
                    "sidecar_only_keepout_rule": "배치/배선 금지 규칙은 원문 sidecar에 보존; CAM 기하로 변환하지 않음",
                    "artwork_use_state=unknown": "제조 이미지 사용 여부 미정으로 파일에서 제외",
                    "artwork_use_state=not_used": "사용 안 함으로 명시한 제조 이미지 층"}
    return [{**deepcopy(row), "reason_label": descriptions.get(row.get("reason"), row.get("reason", "")), **names.get(row.get("id"),
            {"name": None, "name_state": "unresolved", "label": "원본 항목 (이름 확인 불가)"})}
            for row in omissions]


def _job_omissions(service, state, context, job, value):
    """! @brief 완료 패키지의 봉인 입력을 읽으며 현재 편집 이름이나 새 투영으로 대체하지 않는다."""
    original = job
    if job["operation_method"] == "export.verify":
        original = owned_job(service, state, context, value["original_job_id"])
        if manifest_reference(original)["sha256"] != value["source_manifest_sha256"] or original["snapshot"] != job["snapshot"]:
            raise ProjectError("E_HASH", "누락 목록의 원래 출력 결합이 다릅니다.")
    if "exchange" in original:
        reference = original["exchange"]["input"]
        if not 0 < reference["bytes"] <= contract.MAX_INPUT_BYTES:
            raise ProjectError("E_RESOURCE", "출력 누락 목록의 원본 입력이 상한을 초과했습니다.")
        raw = json.loads(service.journal.read_artifact(reference))
        projection = raw["projection"]
    else:
        references = [row for row in result(original).get("artifacts", []) if row.get("role") == "sidecar"]
        if len(references) != 1 or not 0 < references[0]["bytes"] <= 1024 * 1024:
            raise ProjectError("E_HASH", "STEP 누락 목록의 원본 sidecar 참조가 유효하지 않습니다.")
        raw = projection = json.loads(service.journal.read_artifact(references[0]))
    snapshot = original["snapshot"]
    document = service._load({"current": snapshot["artifact"]})
    if (raw.get("snapshot") != snapshot or projection.get("source_semantics") != document
            or canonical_hash(document) != snapshot["content_hash"]):
        raise ProjectError("E_HASH", "누락 목록의 원문과 고정 스냅샷 결합이 다릅니다.")
    return display_omissions(document, projection.get("omissions", []))


def preview(service, state, context, data):
    """! @brief writer와 공유하는 실제 용지 배치를 계산하고 검토 hash를 반환한다."""
    document, snapshot, value = source(service, state, context, data, "00000000-0000-4000-8000-000000000000")
    runtime = service.exchange.runtime
    pcb = contract.pcb_preview(value, data.get("view_layer_id")) if value["profile"] in contract.PCB_PROFILES else None
    pages = layout(value) if pcb is None else pcb["pages"]
    return bounded({"project_id": context["project_id"], "revision_id": snapshot["revision_id"],
        "snapshot": deepcopy(snapshot), "profile": value["profile"], "status": "preview_only",
        "format": data["format"], "options": deepcopy(data["options"]), "can_build": runtime is not None,
        "review_hash": contract.review_hash(value, None if runtime is None else runtime.identity),
        "runtime_configured": runtime is not None, "pages": pages,
        "summary": {"project_name": document["metadata"]["name"], "page_count": len(pages),
                    "shape_count": len(value["projection"]["shapes"]), "layer_count": len(value["projection"]["layers"])},
        "omissions": display_omissions(document, value["projection"]["omissions"]),
        "issues": [] if runtime is not None else [ProjectError("E_UNSUPPORTED", "별도 출력 실행 환경을 연결하십시오.").diagnostic()],
        "manufacturing_verified": False, "physics_verified": False,
        "notice": "고정 스냅샷의 출력 검토입니다. 제작 조건과 실측 정확도의 합격을 뜻하지 않습니다.",
        **({"pcb_preview": pcb["pcb_preview"]} if pcb is not None else {}),
        **({"annotation_review": next(page["annotation_review"] for page in pages if "annotation_review" in page)}
           if "annotations" in value["options"] else {})})


def _item(job):
    """! @brief 큰 원문 대신 실제 보존 상태와 사람이 읽는 출력 이름을 제공한다."""
    value = result(job)
    manifest = None if value is None else next((row for row in value.get("artifacts", []) if row.get("role") == "manifest"), None)
    format_name = job.get("input", {}).get("format", "step" if "cad" in job else "verification")
    return {"job_id": job["job_id"], "operation_method": job["operation_method"], "state": job["state"],
        "label": ("재검수" if job["operation_method"] == "export.verify" else format_name.upper() + " 출력"),
        "format": format_name, "profile": job.get("input", {}).get("profile", value.get("profile") if value else None),
        "snapshot": deepcopy(job.get("snapshot")), "manifest_sha256": None if manifest is None else manifest["sha256"],
        "status": None if value is None else value.get("status"),
        "created_at": job["events"][0].get("timestamp") if job["events"] else None,
        "can_verify": manifest is not None and job["operation_method"] in ("geometry.build", "export.build")}


def _step_report(service, state, context, job, value):
    """! @brief 봉인된 STEP 검수 본문을 읽고 안정 이름과 분리된 원본 객체 표시 이름을 붙인다."""
    if value.get("profile") != "rfad.step.mechanical/0.1":
        return deepcopy(value.get("verification"))
    role = "verification" if job["operation_method"] == "export.verify" else "validation"
    matches = [item for item in value.get("artifacts", []) if item.get("role") == role]
    if len(matches) != 1 or not 0 < matches[0]["bytes"] <= 256 * 1024:
        raise ProjectError("E_HASH", "STEP 검수 원문의 참조/유한 크기가 유효하지 않습니다.")
    report = json.loads(service.journal.read_artifact(matches[0]))
    validation = report.get("verification", report)
    bodies = validation.get("bodies")
    if type(bodies) is not list or not 0 < len(bodies) <= 256:
        raise ProjectError("E_HASH", "STEP 검수 원문의 body 목록이 유효하지 않습니다.")
    original = job
    if job["operation_method"] == "export.verify":
        original = owned_job(service, state, context, value["original_job_id"])
        if manifest_reference(original)["sha256"] != value["source_manifest_sha256"] or original["snapshot"] != job["snapshot"]:
            raise ProjectError("E_HASH", "STEP 검수의 원래 출력 결합이 다릅니다.")
    source_refs = [item for item in result(original).get("artifacts", []) if item.get("role") == "sidecar"]
    if len(source_refs) != 1 or not 0 < source_refs[0]["bytes"] <= 1024 * 1024:
        raise ProjectError("E_HASH", "STEP 원본 sidecar 참조가 유효하지 않습니다.")
    sidecar = json.loads(service.journal.read_artifact(source_refs[0]))
    document = service._load({"current": job["snapshot"]["artifact"]})
    if sidecar.get("source_semantics") != document or sidecar.get("snapshot") != job["snapshot"]:
        raise ProjectError("E_HASH", "STEP body 이름의 원본 snapshot 결합이 다릅니다.")
    names = display_names(document)
    names.update({row["id"]: row["name"] for row in document["stackup"]})
    if document.get("board"):
        names[document["board"]["id"]] = object_label(document, document["board"], "board")
    physical = document["extensions"].get("rfad.physical_setup", {})
    names.update({row["id"]: row["name"] for key in ("surfaces", "parts") for row in physical.get(key, [])})
    names.update({row["id"]: row["name"] for row in document.get("pcb", {}).get("holes", [])})
    names.update({row["id"]: row["name"] for row in (document.get("board") or {}).get("cutouts", [])})
    mapped = {row["name"]: row for row in sidecar.get("body_map", [])}
    if len(mapped) != len(bodies) or set(mapped) != {body.get("name") for body in bodies}:
        raise ProjectError("E_HASH", "STEP 검수 body와 원본 표시 연결이 다릅니다.")
    for index, body in enumerate(bodies):
        original_body = mapped[body["name"]]
        ids = original_body.get("source_entity_ids", [])
        labels = list(dict.fromkeys(names[identity] for identity in ids if identity in names))
        body["label"] = " / ".join(labels) if labels else "출력 바디 " + str(index + 1)
        body["source_entity_ids"] = deepcopy(ids)
    return report


def read(service, method, params):
    """! @brief 조회와 영수증 확인으로 새 파일/새 계산을 만들지 않는다."""
    contract.fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 출력 API 버전입니다.")
    context, data = params["context"], params["input"]
    contract.fields(context, {"project_id"})
    contract.identity(context["project_id"])
    state = service.journal.read()
    project = service._project(state, context)
    if method == "export.receipt":
        contract.fields(data, {"request_key", "request_key_epoch"})
        contract.identity(data["request_key_epoch"])
        if type(data["request_key"]) is not str or not 1 <= len(data["request_key"]) <= 128:
            raise ProjectError("E_SCHEMA", "출력 요청 키가 유효하지 않습니다.")
        receipt = state["receipts"].get(canonical_hash([data["request_key_epoch"], data["request_key"]]))
        if receipt is not None:
            if receipt["scope"] != context or receipt["method"] not in ("snapshot.create", "export.preview", "export.build", "export.verify"):
                raise ProjectError("E_CONFLICT", "출력 영수증의 소유 프로젝트/작업이 다릅니다.")
            if receipt["expires_at"] > service._now():
                return {"status": "found", "authoritative": True, "response": deepcopy(receipt["response"])}
        expired = receipt is not None or state["epochs"].get(data["request_key_epoch"], {}).get("expires_at", 0) <= service._now()
        return {"status": "expired" if expired else "unresolved", "authoritative": True, "response": None,
                "reason": "영수증 미발견은 미접수의 증거가 아닙니다. 새 키로 자동 반복하지 마십시오."}
    if method == "export.context":
        contract.fields(data, set(), {"snapshot_offset", "snapshot"})
        offset = data.get("snapshot_offset", 0)
        if type(offset) is not int or not 0 <= offset <= 1024:
            raise ProjectError("E_SCHEMA", "스냅샷 목록 offset이 유효하지 않습니다.")
        document = service._load(project)
        source_document = document
        selected_snapshot = None
        if "snapshot" in data:
            contract.fields(data["snapshot"], {"snapshot_id", "content_hash"})
            contract.identity(data["snapshot"]["snapshot_id"])
            contract.hash_value(data["snapshot"]["content_hash"])
            selected_snapshot = state["snapshots"].get(data["snapshot"]["snapshot_id"])
            if (selected_snapshot is None or selected_snapshot["project_id"] != context["project_id"]
                    or selected_snapshot["content_hash"] != data["snapshot"]["content_hash"]):
                raise ProjectError("E_HASH", "출력 문맥의 스냅샷 소유권/hash가 다릅니다.")
            source_document = service._load({"current": selected_snapshot["artifact"]})
        snapshots = sorted((row for row in state["snapshots"].values() if row["project_id"] == context["project_id"]),
                           key=lambda row: (row["sealed_at"], row["snapshot_id"]), reverse=True)
        layers = [{key: row[key] for key in ("id", "name", "role")} for row in source_document["stackup"]]
        chosen = next((row["id"] for row in reversed(layers) if row["role"] == "conductor"), None)
        views = [{"kind": "outline"}] if chosen is None else [{"kind": "layer", "layer_id": chosen}, {"kind": "stackup"}]
        pcb = source_document.get("pcb", {})
        artwork = [{key: row[key] for key in ("id", "name", "role", "side", "use_state")}
                   for row in pcb.get("artwork_layers", [])]
        footprints = [{key: row[key] for key in ("id", "name")} for row in pcb.get("footprints", [])]
        return bounded({"project_id": context["project_id"], "revision_id": document["revision_id"],
            "project_name": document["metadata"]["name"], "revision_label": "현재 편집 개정", "layers": layers,
            "source_snapshot": deepcopy(selected_snapshot), "source_name": source_document["metadata"]["name"],
            "source_revision_id": source_document["revision_id"],
            "source_revision_label": "현재 편집 개정" if selected_snapshot is None else selected_snapshot["description"] or "보존된 출력 스냅샷",
            "profiles": [{"id": contract.PROFILE, "label": "연관 기술 도면", "formats": ["pdf", "svg", "dxf"], "supported": True},
                         {"id": "rfad.step.mechanical/0.1", "label": "STEP 기계 형상", "formats": ["step"], "supported": True},
                         {"id": "rfad.exchange.kicad-board/0.1", "label": "KiCad 보드", "formats": ["kicad_pcb"], "supported": True},
                         {"id": "rfad.exchange.kicad-footprint/0.1", "label": "KiCad 풋프린트", "formats": ["kicad_mod"], "supported": True},
                         {"id": "rfad.exchange.cam/0.1", "label": "Gerber / XNC / Job", "formats": ["gerber_job"], "supported": True}],
            "pcb": {"artwork_layers": artwork, "footprints": footprints,
                    "default_cam_layer_ids": [row["id"] for row in layers if row["role"] == "conductor"]
                                             + [row["id"] for row in artwork if row["use_state"] == "used"]},
            "runtime_configured": service.exchange.runtime is not None, "cad_runtime_configured": service.cad.runtime is not None,
            "snapshots": deepcopy(snapshots[offset:offset + 25]), "snapshot_offset": offset,
            "snapshot_total": len(snapshots), "snapshot_next_offset": offset + 25 if offset + 25 < len(snapshots) else None,
            "drawing_annotations": {**contract.annotation_catalog(source_document),
                                    "saved": deepcopy(drawing_annotations.recipe(document))},
            "default_options": {"mode": "drawing", "sheet": "A4", "orientation": "landscape", "scale": 1,
                                "views": views, "dimensions": True, "notes": True},
            "limits": {"views": 8, "file_bytes": contract.MAX_FILE_BYTES, "package_bytes": contract.MAX_PACKAGE_BYTES,
                       "response_bytes": contract.MAX_RESPONSE_BYTES, "concurrency": 1}})
    if method == "export.list":
        contract.fields(data, set(), {"offset"})
        offset = data.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= 512:
            raise ProjectError("E_SCHEMA", "출력 목록 offset이 유효하지 않습니다.")
        jobs = [job for job in state["jobs"].values() if job.get("context") == context and job.get("operation_method") in ("geometry.build", "export.build", "export.verify")]
        jobs.reverse()
        return bounded({"project_id": context["project_id"], "items": [_item(job) for job in jobs[offset:offset + 25]],
                        "offset": offset, "total": len(jobs), "next_offset": offset + 25 if offset + 25 < len(jobs) else None})
    if method == "export.get":
        contract.fields(data, {"job_id"})
        job = owned_job(service, state, context, data["job_id"])
        value = result(job)
        manifest = json.loads(service.journal.read_artifact(manifest_reference(job))) if value is not None else None
        return bounded({**_item(job), "project_id": context["project_id"], "result": value, "manifest": manifest,
            "omissions": [] if value is None else _job_omissions(service, state, context, job, value),
            "verification": None if value is None else value.get("verification"),
            "report": None if value is None else _step_report(service, state, context, job, value),
            "error": next((deepcopy(event["error"]) for event in reversed(job["events"]) if "error" in event), None)})
    raise ProjectError("E_UNSUPPORTED", "지원하지 않는 출력 조회입니다.")


def admit(service, state, method, context, data):
    """! @brief 모든 결정 가능한 검사를 먼저 끝낸 뒤 고정 원본과 접수 영수증을 게시한다."""
    contract.validate_request(method, context, data)
    if len(state["jobs"]) >= 512:
        raise ProjectError("E_RESOURCE", "출력 작업 보존 상한에 도달했습니다.")
    job_id, run_id = str(uuid4()), str(uuid4())
    if method == "export.preview":
        try:
            value = preview(service, state, context, data)
        except ProjectError as error:
            snapshot = state["snapshots"].get(data["snapshot"]["snapshot_id"])
            if snapshot is None or snapshot["project_id"] != context["project_id"] or snapshot["content_hash"] != data["snapshot"]["content_hash"]:
                raise
            value = {"project_id": context["project_id"], "snapshot": deepcopy(snapshot), "profile": data["profile"],
                "revision_id": snapshot["revision_id"], "format": data["format"], "options": deepcopy(data["options"]),
                "status": "preview_only", "can_build": False, "review_hash": None, "pages": [], "issues": [error.diagnostic()]}
        job = {"job_id": job_id, "run_id": run_id, "kind": "export", "operation_method": method,
            "context": deepcopy(context), "input": deepcopy(data), "snapshot": value["snapshot"],
            "captured": deepcopy(value["snapshot"]["artifact"]), "preview_result": value, "events": []}
        service._event(job, "queued")
        if len(canonical_bytes({**state, "jobs": {**state["jobs"], job_id: job}})) + 4096 > MAX_STATE_BYTES:
            raise ProjectError("E_RESOURCE", "출력 검토가 journal 보존 상한을 초과했습니다.")
        state["jobs"][job_id] = job
        return {"job_id": job_id, "state": "queued", "events_cursor": 1}
    runtime = service.exchange.runtime
    if runtime is None:
        raise ProjectError("E_UNSUPPORTED", "별도 출력 Python 실행 환경을 연결하십시오.")
    if service.exchange.error is not None or any(job.get("exchange", {}).get("resource_reserved") for job in state["jobs"].values()):
        raise ProjectError("E_RESOURCE", "출력 슬롯의 이전 실행 종료를 확인해야 합니다.")
    runtime.verify(runtime.identity)
    original = None
    if method == "export.build":
        _, snapshot, value = source(service, state, context, data, run_id)
        if contract.review_hash(value, runtime.identity) != data["review_hash"]:
            raise ProjectError("E_CONFLICT", "검토한 원본/옵션/실행 환경이 변경되었습니다.")
        if value["profile"] in contract.PCB_PROFILES:
            contract.pcb_preview(value)
        else:
            layout(value)
    else:
        original = owned_job(service, state, context, data["job_id"])
        if original["operation_method"] != "export.build" or "exchange" not in original:
            raise ProjectError("E_UNSUPPORTED", "이 경로는 완료된 도면/PCB 교환 패키지만 재검수합니다.")
        reference = manifest_reference(original)
        if reference["sha256"] != data["manifest_sha256"]:
            raise ProjectError("E_HASH", "재검수할 원본 manifest hash가 다릅니다.")
        snapshot = original["snapshot"]
        value = json.loads(service.journal.read_artifact(original["exchange"]["input"]))
    base = service._project(state, context)["path"] + "/exchange-inputs/" + run_id
    blobs = {"input.json": canonical_bytes(value), "runtime.json": runtime.manifest_bytes, "source.json": runtime.source_bytes}
    refs = {name: {"uri": base + "/" + name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in blobs.items()}
    native = {"nonce": str(uuid4()), "runtime": deepcopy(runtime.identity), "input": refs["input.json"], "profile": value["profile"],
              "runtime_manifest": refs["runtime.json"], "source": refs["source.json"],
              "timeout_seconds": runtime.timeout_seconds, "resource_reserved": True,
              "operation": "generate" if original is None else "verify", "original_job_id": None if original is None else original["job_id"]}
    job = {"job_id": job_id, "run_id": run_id, "kind": "export", "operation_method": method, "context": deepcopy(context),
           "input": deepcopy(data), "captured": deepcopy(snapshot["artifact"]), "snapshot": deepcopy(snapshot), "exchange": native, "events": []}
    service._event(job, "queued")
    size = len(canonical_bytes({**state, "jobs": {**state["jobs"], job_id: job}})) + 4096
    if size > MAX_STATE_BYTES:
        raise ProjectError("E_RESOURCE", "출력 접수와 영수증이 journal 보존 상한을 초과했습니다.")
    service.journal._check_space(sum(len(raw) for raw in blobs.values()) + size)
    for name, raw in blobs.items():
        stored = service.journal.put_immutable(base + "/" + name, raw)
        if stored != refs[name]:
            raise ProjectError("E_HASH", "출력 입력의 게시 참조가 검토한 원본과 다릅니다.")
    state["jobs"][job_id] = job
    return {"job_id": job_id, "state": "queued", "events_cursor": 1}
