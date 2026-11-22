"""! @brief PCB 원문을 유한 청크로 봉인하고 별도 parser와 검토 적용을 연결한다."""
import base64
from copy import deepcopy
import hashlib
import json
import os
import re
from uuid import uuid4

from rfad.application import exchange_contract as contract
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.exchange_artifacts import preflight_publication
from rfad.application.exchange_service import bounded
from rfad.domain.errors import ProjectError
from rfad.domain.vendor_catalog import VENDOR_FORMATS
from rfad.storage.journal import MAX_STATE_BYTES
from rfad.storage.sealed_files import verify

PROFILE = "rfad.pcb-import/0.1"
MAX_FILES, MAX_BYTES, CHUNK_BYTES = 40, 16 * 1024 * 1024, 256 * 1024
FORMATS = {"ipc2581_revc": "ipc2581_revc", "kicad_pcb": "kicad_board", "kicad_mod": "kicad_footprint", "gerber_job": "gerber_job", "gerber_x2": "gerber_x2", "xnc": "xnc",
           **dict.fromkeys(VENDOR_FORMATS, "vendor_antenna")}
READS = {"pcb.import.context", "pcb.import.get", "pcb.import.preview", "pcb.import.receipt"}
MUTATIONS = {"pcb.import.begin", "pcb.import.chunk", "pcb.import.parse", "pcb.import.apply", "pcb.import.abandon"}
FIELDS = {"pcb.import.context": set(), "pcb.import.begin": {"format", "files"}, "pcb.import.chunk": {"upload_id", "path", "offset", "content_base64"},
          "pcb.import.parse": {"upload_id"}, "pcb.import.abandon": {"upload_id"}, "pcb.import.get": {"upload_id"},
          "pcb.import.preview": {"upload_id", "expected_revision", "mapping", "acknowledged_losses", "reason"},
          "pcb.import.apply": {"upload_id", "expected_revision", "mapping", "acknowledged_losses", "reason", "command_id", "review_hash"},
          "pcb.import.receipt": {"request_key", "request_key_epoch"}}


def filename(value):
    """! @brief 원문 파일명은 보존하며 디렉터리/Windows 장치명과 별칭 경로는 거절한다."""
    if (type(value) is not str or not 1 <= len(value) <= 120 or value in (".", "..") or value[-1] in " ."
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in value)
            or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", value.split(".")[0], re.IGNORECASE)):
        raise ProjectError("E_SCHEMA", "가져올 원문은 경로가 아닌 유효한 단일 파일명이어야 합니다.")
    return value


def validate_input(method, context, data):
    """! @brief 전송과 적용의 서로 다른 입력을 닫힌 계약으로 검사한다."""
    contract.fields(context, {"project_id"})
    contract.identity(context["project_id"])
    contract.fields(data, FIELDS[method])
    for key in ("upload_id", "expected_revision", "command_id", "request_key_epoch"):
        if key in data:
            contract.identity(data[key])
    if "review_hash" in data:
        contract.hash_value(data["review_hash"])
    if "reason" in data and (type(data["reason"]) is not str or len(data["reason"]) > 512):
        raise ProjectError("E_SCHEMA", "가져오기 이유는 512자 이하의 문장입니다.")
    if method == "pcb.import.begin":
        if type(data["format"]) is not str or data["format"] not in FORMATS:
            raise ProjectError("E_UNSUPPORTED", "지원하는 PCB 가져오기 형식을 선택하십시오.")
        if type(data["files"]) is not list or not 1 <= len(data["files"]) <= MAX_FILES:
            raise ProjectError("E_RESOURCE", "가져오기 원문은 1~40개 파일입니다.")
        if data["format"] in VENDOR_FORMATS and len(data["files"]) != 1:
            raise ProjectError("E_SCHEMA", "선택한 제조사 예제에 해당하는 원문 또는 ZIP 하나를 선택하십시오.")
        names, total = set(), 0
        for row in data["files"]:
            contract.fields(row, {"path", "bytes", "sha256"})
            name = filename(row["path"]).casefold()
            contract.hash_value(row["sha256"])
            if name in names or type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_BYTES:
                raise ProjectError("E_RESOURCE", "중복 파일명 또는 원문 크기가 유효하지 않습니다.")
            names.add(name)
            total += row["bytes"]
        if total > MAX_BYTES:
            raise ProjectError("E_RESOURCE", "가져올 원문 합계가 16 MiB를 초과했습니다.")
    elif method == "pcb.import.chunk":
        filename(data["path"])
        if type(data["offset"]) is not int or data["offset"] < 0:
            raise ProjectError("E_SCHEMA", "전송 위치는 음수가 아닌 정수입니다.")
        chunk_bytes(data["content_base64"])
    elif method == "pcb.import.receipt":
        if type(data["request_key"]) is not str or not 1 <= len(data["request_key"]) <= 128:
            raise ProjectError("E_SCHEMA", "가져오기 영수증 키가 유효하지 않습니다.")


def chunk_bytes(value):
    """! @brief 원문 바이트를 재인코딩하지 않고 한 청크 256 KiB만 수용한다."""
    try:
        if type(value) is not str or not 0 < len(value) <= ((CHUNK_BYTES + 2) // 3) * 4:
            raise ValueError()
        raw = base64.b64decode(value, validate=True)
        if not 0 < len(raw) <= CHUNK_BYTES or base64.b64encode(raw).decode("ascii") != value:
            raise ValueError()
        return raw
    except (ValueError, UnicodeError) as error:
        raise ProjectError("E_RESOURCE", "원문 청크는 256 KiB 이하의 정규 base64여야 합니다.") from error


def owned(service, state, context, upload_id):
    """! @brief 전송 원문도 소유 프로젝트 외부에서 읽거나 적용할 수 없다."""
    service._project(state, context)
    session = state.get("pcb_imports", {}).get(upload_id)
    if session is None or session["context"] != context:
        raise ProjectError("E_CONFLICT", "이 가져오기 원문이 선택한 프로젝트에 속하지 않습니다.")
    return session


def overview(service, state, context):
    """! @brief 미완료 전송과 적용 대상 목록은 현재 원본에서 권위 조회한다."""
    document = service._load(service._project(state, context))
    return bounded({"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
            "board_id": None if document["board"] is None else document["board"]["id"], "frame_id": document["frames"]["board"]["id"],
            "layers": [{key: row[key] for key in ("id", "name", "role", "order")} for row in document["stackup"]],
            "artwork_layers": [{key: row[key] for key in ("id", "name", "role", "side", "use_state")}
                               for row in document.get("pcb", {}).get("artwork_layers", [])],
            "nets": [{key: row[key] for key in ("id", "name")} for row in document["nets"]],
            "uploads": [{"upload_id": row["id"], "format": row["format"], "status": row["status"], "parse_job_id": row["parse_job_id"],
                         "applied_revision": row.get("applied_revision"), "created_at": row.get("created_at"),
                         "label": row["files"][0]["path"] + (" 외 " + str(len(row["files"]) - 1) + "개" if len(row["files"]) > 1 else "")}
                        for row in state.get("pcb_imports", {}).values() if row["context"] == context],
            "limits": {"files": MAX_FILES, "source_and_report_bytes": MAX_BYTES, "chunk_bytes": CHUNK_BYTES},
            "vendor_patterns": [{key: card[key] for key in ("format", "label", "description", "source_url")}
                                for card in VENDOR_FORMATS.values()],
            "runtime_configured": service.exchange.runtime is not None})


def summary(state, session):
    """! @brief 전송 원문 전체나 청크 문자열 대신 진행과 권위 작업 상태를 반환한다."""
    job = state["jobs"].get(session["parse_job_id"])
    result = None if job is None or job["state"] != "completed" else job["events"][-1].get("operation_result")
    return {"profile": PROFILE, "upload_id": session["id"], "format": session["format"], "status": session["status"],
            "files": [{key: deepcopy(row[key]) for key in ("path", "bytes", "sha256", "received")} for row in session["files"]],
            "parse_job_id": session["parse_job_id"], "parse_state": None if job is None else job["state"],
            "result": deepcopy(result), "applied_revision": session.get("applied_revision"),
            "error": None if job is None else next((deepcopy(row["error"]) for row in reversed(job["events"]) if "error" in row), None)}


def _capacity(state, extra=4096):
    """! @brief 예측 가능한 journal 초과는 원문 파일 게시 전에 차단한다."""
    if len(canonical_bytes(state)) + extra > MAX_STATE_BYTES:
        raise ProjectError("E_RESOURCE", "가져오기 기록이 journal 보존 상한을 초과했습니다.")


def _raw_files(service, project, session):
    """! @brief 접수한 청크를 한 번 조립하고 선언한 전체 SHA256과 대조해 봉인한다."""
    result = []
    base = project["path"] + "/pcb-imports/" + session["id"]
    service.journal._check_space(sum(row["bytes"] for row in session["files"]))
    for index, row in enumerate(session["files"]):
        reference = {"uri": base + "/raw/" + row["path"], "bytes": row["bytes"], "sha256": row["sha256"]}
        destination = service.journal._safe_path(reference["uri"])
        if destination.exists():
            service.journal.verify_file(reference)
        else:
            temporary = service.journal._safe_path(base + "/assembly/" + str(uuid4()) + ".partial")
            temporary.parent.mkdir(parents=True, exist_ok=True)
            try:
                with temporary.open("xb") as outgoing:
                    for chunk in row["chunks"]:
                        outgoing.write(service.journal.read_artifact(chunk))
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                service.journal.seal_file(reference["uri"], temporary, expected_sha256=row["sha256"], expected_bytes=row["bytes"], limit=MAX_BYTES)
            finally:
                if temporary.exists():
                    temporary.unlink()
        result.append({"path": row["path"], "artifact": reference})
    return result


def _parse(service, state, context, session):
    """! @brief 원문 전송 완료와 별도 실행 환경을 확인한 후 같은 출력 슬롯에 접수한다."""
    if session["status"] != "uploading" or session["parse_job_id"] is not None:
        raise ProjectError("E_CONFLICT", "이미 봉인되었거나 폐기된 전송은 다시 접수하지 않습니다.")
    if any(row["received"] != row["bytes"] for row in session["files"]):
        raise ProjectError("E_CONFLICT", "모든 원문 바이트를 전송한 뒤 읽기를 시작하십시오.")
    runtime = service.exchange.runtime
    if runtime is None:
        raise ProjectError("E_UNSUPPORTED", "PCB 원문을 읽을 별도 출력 환경을 연결하십시오.")
    if (len(state["jobs"]) >= 512 or service.exchange.error is not None
            or any(row.get("exchange", {}).get("resource_reserved") for row in state["jobs"].values())):
        raise ProjectError("E_RESOURCE", "출력/가져오기 슬롯 또는 작업 보존 한도를 확인하십시오.")
    runtime.verify(runtime.identity)
    _capacity(state, 65536)
    project = service._project(state, context)
    files = _raw_files(service, project, session)
    run_id, job_id = str(uuid4()), str(uuid4())
    value = {"schema": "rfad.pcb-import-input/0.1", "run_id": run_id, "format": session["format"], "options": {}, "files": files}
    base = project["path"] + "/pcb-imports/" + session["id"] + "/parser/" + run_id
    references = {name: service.journal.put_immutable(base + "/" + name, raw) for name, raw in
                  (("input.json", canonical_bytes(value)), ("runtime.json", runtime.manifest_bytes), ("source.json", runtime.source_bytes))}
    native = {"nonce": str(uuid4()), "runtime": deepcopy(runtime.identity), "input": references["input.json"], "profile": PROFILE,
              "runtime_manifest": references["runtime.json"], "source": references["source.json"], "operation": "parse",
              "timeout_seconds": runtime.timeout_seconds, "resource_reserved": True, "upload_id": session["id"]}
    job = {"job_id": job_id, "run_id": run_id, "kind": "export", "operation_method": "pcb.import.parse", "context": deepcopy(context),
           "input": {"upload_id": session["id"]}, "captured": deepcopy(project["current"]), "exchange": native, "events": []}
    service._event(job, "queued")
    state["jobs"][job_id] = job
    session.update(status="sealed", parse_job_id=job_id, source_files=files)
    _capacity(state)
    return {"job_id": job_id, "state": "queued", "events_cursor": 1, "upload_id": session["id"]}


def seal_parsed(journal, job, returned, output):
    """! @brief parser 결과는 소유 실행과 원문에 묶고 원본 바이트와 함께 불변 보존한다."""
    reference = returned.get("parsed")
    contract.fields(reference, {"path", "bytes", "sha256"})
    if reference["path"] != "parse.json" or type(reference["bytes"]) is not int or not 0 < reference["bytes"] <= contract.MAX_RESPONSE_BYTES:
        raise ProjectError("E_RESOURCE", "PCB 읽기 보고서의 이름/크기가 유효하지 않습니다.")
    contract.hash_value(reference["sha256"])
    if {path.name for path in output.iterdir()} != {"parse.json"}:
        raise ProjectError("E_HASH", "PCB 읽기 결과에 미신고 파일이 있습니다.")
    verify(output / "parse.json", {"uri": reference["path"], "bytes": reference["bytes"], "sha256": reference["sha256"]})
    parsed = json.loads((output / "parse.json").read_bytes())
    value = json.loads(journal.read_artifact(job["exchange"]["input"]))
    if (type(parsed) is not dict or parsed.get("schema") != "rfad.pcb-parse/0.1" or parsed.get("format") != value["format"]
            or parsed.get("raw_preservation_required") is not True or parsed.get("manufacturing_verified") is not False
            or parsed.get("physics_verified") is not False or type(parsed.get("records")) is not list
            or type(parsed.get("losses")) is not list or len(parsed["records"]) != len(value["files"])
            or {row.get("path") for row in parsed["records"]} != {row["path"] for row in value["files"]}):
        raise ProjectError("E_HASH", "PCB 읽기 결과가 원문 목록/형식/적용 범위와 다릅니다.")
    if sum(row["artifact"]["bytes"] for row in value["files"]) + reference["bytes"] > MAX_BYTES:
        raise ProjectError("E_RESOURCE", "원문과 읽기 보고서 합계가 16 MiB를 초과했습니다.")
    session = journal.read()["pcb_imports"][job["exchange"]["upload_id"]]
    if session["parse_job_id"] != job["job_id"] or session["context"] != job["context"] or session["source_files"] != value["files"]:
        raise ProjectError("E_HASH", "PCB 읽기 작업의 원문 소유 대응이 다릅니다.")
    prefix = value["files"][0]["artifact"]["uri"].rsplit("/raw/", 1)[0]
    report = {"uri": prefix + "/parsed/" + job["run_id"] + ".json", "sha256": reference["sha256"], "bytes": reference["bytes"]}
    result = {"profile": PROFILE, "upload_id": session["id"], "format": value["format"], "status": "parsed_unapplied",
            "report": report, "source_files": deepcopy(value["files"]), "runtime": deepcopy(job["exchange"]["runtime"]),
            "loss_count": len(parsed["losses"]), "artifacts": [report] + [row["artifact"] for row in value["files"]],
            "manufacturing_verified": False, "physics_verified": False}
    preflight_publication(journal, job, result, reference["bytes"])
    journal.seal_file(report["uri"], output / "parse.json",
        expected_sha256=reference["sha256"], expected_bytes=reference["bytes"], limit=contract.MAX_RESPONSE_BYTES)
    return result


def reviewed(service, state, context, data):
    """! @brief 같은 고정 parser 결과를 현재 원본에 명시 대응하며 한 개 원자 후보를 만든다."""
    from rfad.application.pcb_import_mapping import import_candidate
    session = owned(service, state, context, data["upload_id"])
    if session["status"] != "sealed" or session.get("applied_revision") is not None:
        raise ProjectError("E_CONFLICT", "이미 적용되었거나 적용 가능한 원문 전송이 아닙니다.")
    result = summary(state, session)["result"]
    if result is None:
        raise ProjectError("E_CONFLICT", "별도 parser가 완료된 원문만 검토할 수 있습니다.")
    project = service._project(state, context)
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != data["expected_revision"]:
        raise ProjectError("E_CONFLICT", "가져오기 기준 개정이 바뀌었습니다. 대응을 다시 검토하십시오.")
    for row in result["source_files"]:
        service.journal.verify_file(row["artifact"])
    parsed = json.loads(service.journal.read_artifact(result["report"]))
    versions = sorted({str(row["data"].get("version", "unspecified")) for row in parsed["records"]})
    record = {"id": session["id"], "format": FORMATS[session["format"]], "format_version": ", ".join(versions),
              "parser_profile": PROFILE, "source_files": [deepcopy(row["artifact"]) for row in result["source_files"]],
              "report": deepcopy(result["report"]), "bindings": [], "source_refs": ["parser-runtime:" + canonical_hash(result["runtime"])]}
    if session["format"] in VENDOR_FORMATS:
        card = VENDOR_FORMATS[session["format"]]
        if parsed["records"][0]["data"].get("card") != card:
            raise ProjectError("E_HASH", "읽은 공급사 카드와 선택한 카드가 다릅니다.")
        record["source_refs"] += [card["source_url"], card["revision"] + " / " + card["member"],
                                  "sha256:" + card["sha256"]]
    review, patch = import_candidate(document, parsed, record, data["mapping"], data["acknowledged_losses"], data["reason"])
    review["review_hash"] = None if not review["can_apply"] else canonical_hash({"candidate": review["review_hash"], "report": result["report"], "runtime": result["runtime"]})
    review.update(upload_id=session["id"], source_files=deepcopy(result["source_files"]), parser_report=deepcopy(result["report"]),
                  manufacturing_verified=False, physics_verified=False)
    return bounded(review), patch


def read(service, method, params):
    """! @brief 전송 재개/불명 영수증/적용 전 후보를 읽으며 원본을 변경하지 않는다."""
    contract.fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 PCB 가져오기 API입니다.")
    context, data = params["context"], params["input"]
    validate_input(method, context, data)
    state = service.journal.read()
    service._project(state, context)
    if method == "pcb.import.context":
        return overview(service, state, context)
    if method == "pcb.import.receipt":
        receipt = state["receipts"].get(canonical_hash([data["request_key_epoch"], data["request_key"]]))
        if receipt is not None and (receipt["scope"] != context or receipt["method"] not in MUTATIONS):
            raise ProjectError("E_CONFLICT", "다른 프로젝트/작업의 가져오기 영수증입니다.")
        found = receipt is not None and receipt["expires_at"] > service._now()
        return {"authoritative": True, "status": "found" if found else "expired" if receipt else "unresolved",
                "response": deepcopy(receipt["response"]) if found else None, "may_resubmit": False}
    if method == "pcb.import.preview":
        return reviewed(service, state, context, data)[0]
    session = owned(service, state, context, data["upload_id"])
    result = summary(state, session)
    if result["result"] is not None:
        from rfad.application.pcb_import_mapping import import_sources
        result["parsed"] = json.loads(service.journal.read_artifact(result["result"]["report"]))
        result["mapping_sources"] = import_sources(result["parsed"])
    return bounded(result)


def admit(service, state, method, context, data):
    """! @brief 전송/봉인/적용은 각각 같은 ledger의 재전송 영수증과 함께 게시한다."""
    validate_input(method, context, data)
    project = service._project(state, context)
    if method == "pcb.import.begin":
        sessions = state.setdefault("pcb_imports", {})
        if len(sessions) >= 64 or sum(row["context"] == context for row in sessions.values()) >= 16:
            raise ProjectError("E_RESOURCE", "가져오기 원문 보존은 작업영역 64개/프로젝트 16개입니다.")
        upload_id = str(uuid4())
        session = {"id": upload_id, "context": deepcopy(context), "format": data["format"], "status": "uploading", "parse_job_id": None, "created_at": service._now(),
                   "files": [{**deepcopy(row), "received": 0, "chunks": []} for row in data["files"]]}
        sessions[upload_id] = session
        _capacity(state)
        return {"upload_id": upload_id, "status": "uploading", "chunk_bytes": CHUNK_BYTES}
    session = owned(service, state, context, data["upload_id"])
    if method == "pcb.import.chunk":
        row = next((row for row in session["files"] if row["path"] == data["path"]), None)
        raw = chunk_bytes(data["content_base64"])
        if session["status"] != "uploading" or row is None or row["received"] != data["offset"] or row["received"] + len(raw) > row["bytes"]:
            raise ProjectError("E_CONFLICT", "원문 전송 위치/파일/상태가 달라졌습니다. 권위 진행 상태를 조회하십시오.")
        base = project["path"] + "/pcb-imports/" + session["id"] + "/chunks/" + str(session["files"].index(row)) + "/"
        reference = {"uri": base + str(data["offset"]) + "-" + hashlib.sha256(raw).hexdigest() + ".bin", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        row["chunks"].append(reference)
        row["received"] += len(raw)
        _capacity(state)
        service.journal.put_immutable(reference["uri"], raw)
        return {"upload_id": session["id"], "path": row["path"], "received": row["received"], "complete": row["received"] == row["bytes"]}
    if method == "pcb.import.parse":
        return _parse(service, state, context, session)
    if method == "pcb.import.abandon":
        if session["status"] != "uploading":
            raise ProjectError("E_CONFLICT", "봉인 후 원문은 보존되며 실행 취소는 해당 작업에서 수행합니다.")
        session["status"] = "abandoned"
        return {"upload_id": session["id"], "status": "abandoned", "raw_preserved": True}
    review, patch = reviewed(service, state, context, data)
    if not review["can_apply"] or review["review_hash"] != data["review_hash"]:
        raise ProjectError("E_CONFLICT", "가져오기 대응/원본/검토가 변경됐거나 적용할 수 없습니다.")
    result = service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"],
        "type": "pcb.features.replace", "payload": patch})
    session["applied_revision"] = result["new_revision"]
    state["commands"][data["command_id"]]["pcb_import"] = {"upload_id": session["id"], "review_hash": data["review_hash"], "mapping": deepcopy(data["mapping"]), "acknowledged_losses": deepcopy(data["acknowledged_losses"]), "reason": data["reason"]}
    return {**result, "upload_id": session["id"], "profile": PROFILE, "review_hash": data["review_hash"], "selection": review.get("selection", [])}
