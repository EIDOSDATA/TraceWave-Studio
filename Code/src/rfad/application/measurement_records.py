"""! @brief 과거 측정 기록과 원문 자료를 소유권/hash로 대조하고 읽기 전용 표시를 만든다."""

from copy import deepcopy

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application import measurement_contract as contract, measurement_forms
from rfad.application.network_records import descriptor, samples
from rfad.application.result_sources import read_json, resolve, revision_document, owned_reference, snapshot_document
from rfad.application.result_complex import condition_differences, _display
from rfad.application.project_contract import _fields
from rfad.domain import measurement
from rfad.domain.network_library import library
from rfad.domain.network_library import digest


def current(service, state, context, expected_revision):
    """! @brief 입력 개정과 undo head가 같은 원본에서만 새 기록을 검토한다."""
    project = service._project(state, context)
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != expected_revision:
        contract.fail("측정 기록의 기준 개정이 바뀌었습니다. 원본을 다시 조회하십시오.", "E_CONFLICT")
    return project, document


def reference(entry, revision_id):
    """! @brief artifact hash와 그 기록을 보유한 명시 개정을 함께 전달한다."""
    return {"id": entry["id"], "sha256": entry["artifact"]["sha256"], "revision_id": revision_id}


def creation_revision(state, project_id, entry):
    """! @brief 원래 게시 명령의 실제 산출물 참조로 생성 개정을 찾고 현재 개정으로 대체하지 않는다."""
    revisions = set()
    for command in state.get("commands", {}).values():
        item = command.get("measurement")
        if (command.get("project_id") == project_id and type(item) is dict
                and item.get("record_id") == entry["id"] and item.get("record_artifact") == entry["artifact"]):
            revision = command.get("new_revision")
            from rfad.application.project_contract import _uuid
            _uuid(revision)
            revisions.add(revision)
    if not revisions:
        contract.fail("측정 기록의 원래 게시 명령을 찾을 수 없습니다. 현재 개정으로 대체하지 않습니다.", "E_MISSING_ARTIFACT")
    if len(revisions) != 1:
        contract.fail("측정 기록의 생성 개정이 모호합니다. 출처를 임의 선택하지 않습니다.", "E_HASH")
    revision = next(iter(revisions))
    project = state.get("projects", {}).get(project_id)
    if project is None or revision not in project.get("revisions", {}):
        contract.fail("측정 기록의 원래 프로젝트 개정을 찾을 수 없습니다.", "E_MISSING_ARTIFACT")
    return revision


def creation_reference(state, project_id, entry):
    """! @brief 현재 목록에서도 동일 기록의 최초 게시 개정/hash를 고정한다."""
    return reference(entry, creation_revision(state, project_id, entry))


def attachments(state, project_id):
    """! @brief 다른 프로젝트에서 보관한 첨부 원문을 목록에 섞지 않는다."""
    return [deepcopy(row["descriptor"]) for row in state.get("measurement_attachments", {}).values()
            if row["project_id"] == project_id]


def _source_for_anchor(service, state, project, document, anchor):
    """! @brief 한 명시 개정의 자료 참조 또는 과거 pin을 실제 봉인 원문과 대조한다."""
    project_id = document["project_id"]
    measurement.validate_anchor(anchor, project_id)
    if anchor["kind"] == "pinned_result":
        result = resolve(service, {"project_id": project_id}, anchor["source"], anchor["pin"])
        if result["entry"] is not None:
            for key in ("dataset", "raw", "normalized_hdf5"):
                if result["entry"][key] is not None:
                    service.journal.verify_file(owned_reference(project, result["entry"][key]))
        return result
    network = next((row for row in library(document)["datasets"] if row["id"] == anchor["dataset_id"]), None)
    if network is None or any(network[key] != anchor[key] for key in ("dataset", "raw", "normalized_hdf5")):
        contract.fail("측정 원본의 자료 참조가 기록을 보유한 개정과 다릅니다.", "E_HASH")
    for key in ("dataset", "raw", "normalized_hdf5"):
        if anchor[key] is not None:
            service.journal.verify_file(owned_reference(project, anchor[key]))
    return resolve(service, {"project_id": project_id},
                   {"kind": "network", "dataset_id": network["id"], "revision_id": document["revision_id"], "snapshot_id": None})


def validate_evidence(service, state, project, record, document=None):
    """! @brief 기록 안의 파일 참조는 현재 프로젝트에 등록된 실제 불변 원문이어야 한다."""
    document = service._load(project) if document is None else document
    project_id = document["project_id"]
    measurement.validate_record(record, project_id=project_id)
    known = attachments(state, project_id)
    by_id = {row["id"]: row for row in known}
    allowed = [row["artifact"] for row in known]
    for row in record["attachments"]:
        if by_id.get(row["id"]) != row:
            contract.fail("측정 첨부 원문이 현재 프로젝트의 보관 기록과 다릅니다.", "E_HASH")
    def scan(value):
        """! @brief 중첩된 교정/설정/상관 근거도 임의 파일 경로로 읽지 않는다."""
        if type(value) is dict:
            if {"uri", "sha256", "bytes"} <= set(value):
                if value not in allowed:
                    contract.fail("먼저 보관한 측정 첨부 원문만 근거로 연결할 수 있습니다.", "E_HASH")
                service.journal.verify_file(owned_reference(project, value))
            else:
                for item in value.values():
                    scan(item)
        elif type(value) is list:
            for item in value:
                scan(item)
    for key in ("specimen", "acquisition", "calibration", "fixture", "environment", "uncertainty", "attachments"):
        scan(record[key])
    specimen = record["specimen"]
    snapshot_leaf = specimen["design_snapshot"] if specimen is not None else None
    snapshot_value = snapshot_leaf["value"] if snapshot_leaf is not None else None
    if type(snapshot_value) is dict and set(snapshot_value) == {"snapshot_id", "content_hash"}:
        from rfad.application.project_contract import _uuid
        _uuid(snapshot_value["snapshot_id"])
        digest(snapshot_value["content_hash"], "specimen.design_snapshot.content_hash")
        snapshot = state.get("snapshots", {}).get(snapshot_value["snapshot_id"])
        if snapshot is None or snapshot.get("content_hash") != snapshot_value["content_hash"]:
            contract.fail("선택한 설계 snapshot의 고정 hash가 다릅니다.", "E_HASH")
        snapshot_document(service, project, project_id, snapshot)
    for item in record["external_processing"]:
        for key in ("input_anchor", "output_anchor"):
            if item[key] is not None:
                _source_for_anchor(service, state, project, document, item[key])


def _validate_wrapper(stored):
    """! @brief 원문 입력과 선택적 실행 영수증을 포함한 불변 wrapper의 크기/형식을 확인한다."""
    _fields(stored, {"schema", "record", "input", "execution"})
    if stored["schema"] != "rfad.measurement-document/0.1":
        contract.fail("지원하지 않는 측정 기록 파일입니다.", "E_VERSION")
    if type(stored["input"]) is not dict:
        contract.fail("보존한 측정 입력은 object여야 합니다.")
    if stored["execution"] is not None:
        execution = stored["execution"]
        _fields(execution, {"schema", "operation", "input_sha256", "identity_hash", "result_hash"})
        if execution["schema"] != "rfad.host-execution/0.1" or type(execution["operation"]) is not str or not execution["operation"]:
            contract.fail("보존한 실행 영수증 형식이 다릅니다.", "E_VERSION")
        for key in ("input_sha256", "identity_hash", "result_hash"):
            digest(execution[key], "execution." + key)
    measurement.bounded(stored, "measurement_document")


def load_record(service, state, project, selected):
    """! @brief 현재 목록이 아닌 사용자가 고정한 과거 개정에서 기록을 찾는다."""
    contract.record_ref(selected)
    project_id = service._load(project)["project_id"]
    document, _ = revision_document(service, state, project, project_id, selected["revision_id"])
    registry = measurement.registry(document)
    measurement.validate_registry(registry)
    entry = next((row for row in registry["records"] if row["id"] == selected["id"]), None)
    if entry is None:
        contract.fail("선택한 개정에 측정 기록이 없습니다.", "E_MISSING_ARTIFACT")
    if entry["artifact"]["sha256"] != selected["sha256"]:
        contract.fail("측정 기록의 고정 hash가 다릅니다.", "E_HASH")
    created = creation_reference(state, project_id, entry)
    original, _ = revision_document(service, state, project, project_id, created["revision_id"])
    original_registry = measurement.registry(original)
    measurement.validate_registry(original_registry)
    if entry not in original_registry["records"]:
        contract.fail("측정 기록의 실제 생성 개정에 같은 색인이 없습니다.", "E_HASH")
    stored = read_json(service, project, entry["artifact"])
    _validate_wrapper(stored)
    record = stored["record"]
    measurement.validate_record(record, project_id=project_id)
    if any(record[key] != entry[key] for key in ("id", "name", "previous_record_id")):
        contract.fail("측정 색인과 실제 기록이 다릅니다.", "E_HASH")
    anchor = record["data_anchor"]
    source = _source_for_anchor(service, state, project, original, anchor)
    diagnostics = measurement.validate_record(record, source["dataset"], project_id)
    validate_evidence(service, state, project, record, original)
    return {"entry": entry, "record": record, "stored": stored, "source": source,
            "record_ref": created, "diagnostics": diagnostics}


def selected_source(service, state, project, context, selected):
    """! @brief 원본과 시료 기록이 다른데 단지 곡선이 같다는 이유로 연결하지 않는다."""
    contract.selection(selected)
    source = resolve(service, context, selected["source"], selected["pin"])
    recorded = None
    if selected["record"] is not None:
        recorded = load_record(service, state, project, selected["record"])
        original = recorded["source"]
        if source["source"] != original["source"] or source["pin"] != original["pin"]:
            contract.fail("선택한 측정 기록에 고정한 원본과 비교 자료가 다릅니다.", "E_CONFLICT")
    return source, recorded


def _leaf(record, group, key):
    """! @brief 표시에서만 leaf를 읽고 null 묶음/빈 목록의 원문은 유지한다."""
    section = None if record is None else record[group]
    return None if section is None else section[key]


def leaf_display(path, leaf, dataset=None):
    """! @brief 수치 단위와 짧은 원문은 읽을 수 있게 표시하고 파일 객체는 펼치지 않는다."""
    value = None if leaf is None else leaf.get("value")
    if value is None:
        return "미정"
    evidence = {"planned": "계획", "declared": "명시", "reported": "제출 근거", "unknown": "미정"}.get(leaf.get("evidence"), "미정")
    suffix = " (" + evidence + ")"
    if path.endswith("if_bandwidth_hz") or path.endswith("frequency_range_hz"):
        values = value if type(value) is list else [value]
        peak = max(abs(item) for item in values)
        unit, scale = ("GHz", 1e9) if peak >= 1e9 else ("MHz", 1e6) if peak >= 1e6 else ("kHz", 1e3) if peak >= 1e3 else ("Hz", 1.0)
        return " ~ ".join(format(item / scale, ".15g") for item in values) + " " + unit + suffix
    if type(value) is dict and set(value) == {"number", "unit"}:
        return format(value["number"], ".15g") + " " + value["unit"] + suffix
    if path in ("calibration.port_ids", "calibration.reference_planes") and dataset is not None:
        labels = {identity: dataset["port_names"][index] or "자료 포트 " + str(index + 1) + " (이름 미정)"
                  for index, identity in enumerate(dataset["port_ids"])}
        parts = [labels[item] if type(item) is str else labels[item["port_id"]] + ": " + (item["reference_plane"] or "미정") for item in value]
        return ("; ".join(parts) if parts else "기록 없음") + suffix
    return _display(value) + suffix


def _collection_display(key, value):
    """! @brief 기본 조건 표에 외부 처리 순서/도구/기준면을 읽을 수 있는 문장으로 제시한다."""
    if value in (None, "unknown", []):
        return "미정"
    if key == "data_class":
        return {"measurement": "사용자 제출 측정 분류", "synthetic_fixture": "합성 검증 자료", "unknown": "미정"}[value]
    if key == "external_processing":
        lines = []
        for row in value:
            tool = (row["tool"] or "도구 미정") + " / " + (row["version"] or "버전 미정")
            planes = (row["reference_plane_before"] or "기준면 미정") + " -> " + (row["reference_plane_after"] or "기준면 미정")
            lines.append(str(row["order"] + 1) + ". " + row["name"] + ": " + tool + "; " + planes)
        return " | ".join(lines)
    if key == "uncertainty":
        return str(len(value)) + "개 제출 기록 (전파/합격 판정 미수행)"
    return _display(value)


def summary(record, dataset):
    """! @brief 사용자 제출 분류와 미정 조건을 실측 합격으로 바꾸지 않는다."""
    if record is None:
        return {"name": "측정 기록 없음", "data_class": "unknown", "specimen": "미정", "calibration": "미정",
                "reference_planes": "미정", "uncertainty": "미정", "measurement_validated": False}
    return {"name": record["name"], "data_class": record["data_class"],
            "specimen": leaf_display("specimen.identifier", _leaf(record, "specimen", "identifier")),
            "calibration": leaf_display("calibration.method", _leaf(record, "calibration", "method")),
            "reference_planes": leaf_display("calibration.reference_planes", _leaf(record, "calibration", "reference_planes"), dataset),
            "uncertainty": "미정" if not record["uncertainty"] else str(len(record["uncertainty"])) + "개 제출 기록",
            "measurement_validated": False, "context_status": measurement.condition_assessment(record, dataset)["status"]}


def metadata_conditions(left, right, left_record, right_record):
    """! @brief 수학 전제와 교정/시료 원문 차이를 서로 다른 행으로 보존한다."""
    rows = condition_differences(left, right)
    for group, definitions in measurement.SECTIONS.items():
        for key in definitions:
            a, b = _leaf(left_record, group, key), _leaf(right_record, group, key)
            av, bv = (None if item is None else item["value"] for item in (a, b))
            difference = "both_unknown" if av is None and bv is None else "one_unknown" if av is None or bv is None else "equal" if a == b else "different"
            path = group + "." + key
            rows.append({"field": "measurement." + path, "label": measurement_forms.LABELS[key],
                "left_display": leaf_display(path, a, left["dataset"]), "right_display": leaf_display(path, b, right["dataset"]),
                "left_state": "missing" if av is None else "recorded", "right_state": "missing" if bv is None else "recorded",
                "left_evidence": None if a is None else a["evidence"], "right_evidence": None if b is None else b["evidence"],
                "unit": None, "difference": difference, "affects_math": False,
                "reason": "제출 기록의 일치 여부입니다. 교정 또는 실측 정확도 합격을 뜻하지 않습니다."})
    for key, label in (("data_class", "자료 분류"), ("uncertainty", "불확도 기록"), ("external_processing", "외부 처리 이력")):
        a, b = (None if record is None else record[key] for record in (left_record, right_record))
        unknown_a, unknown_b = a in (None, "unknown", []), b in (None, "unknown", [])
        difference = "both_unknown" if unknown_a and unknown_b else "one_unknown" if unknown_a or unknown_b else "equal" if a == b else "different"
        rows.append({"field": "measurement." + key, "label": label, "left_display": _collection_display(key, a),
            "right_display": _collection_display(key, b), "left_state": "missing" if unknown_a else "recorded",
            "right_state": "missing" if unknown_b else "recorded", "unit": None, "difference": difference,
            "affects_math": False, "reason": "외부 처리와 불확도 기록을 보존하며 보정 실행/전파/실측 합격으로 승격하지 않습니다."})
    return rows


def get(service, state, project, selected):
    """! @brief runtime 없이도 불변 기록과 원래 복소 표본을 조회한다."""
    value = load_record(service, state, project, selected)
    record, source = value["record"], value["source"]
    return contract.bounded({"profile": contract.PROFILE, "project_id": source["current_document"]["project_id"],
        "revision_id": source["current_document"]["revision_id"], "source_revision": deepcopy(source["source_revision"]),
        "record_ref": deepcopy(value["record_ref"]), "record": deepcopy(record), "source": deepcopy(source["source"]), "pin": deepcopy(source["pin"]),
        "descriptor": descriptor(source["dataset"]), "page": samples(source["dataset"]),
        "summary": summary(record, source["dataset"]), "context_assessment": measurement.condition_assessment(record, source["dataset"]),
        "form": measurement_forms.form(record, contract.now_text(service)), "original_input": deepcopy(value["stored"]["input"]),
        "execution": deepcopy(value["stored"]["execution"]),
        "evidence_scope": {"physical_setup_snapshot": "제출 원문/첨부 근거 보존; 환경 개정의 자동 연결은 수행하지 않음",
                           "external_processing": "입출력 자료의 소유/hash 확인; 보정 실행/재현 또는 물리 정확도 합격 아님"}})
