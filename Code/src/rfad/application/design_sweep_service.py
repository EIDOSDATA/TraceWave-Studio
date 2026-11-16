"""! @brief 명시적 설계/수치/외부 회로 스윕의 검토, 저장, 제어와 페이지 조회를 제공한다."""

from copy import deepcopy
import hashlib
from pathlib import Path
import platform
import struct
import sys
from uuid import uuid4

from rfad.adapters.network_backend import installation_metadata
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.design_sweep_store import (
    ACTIVE, DEFINITION_SCHEMA, PAGE_SIZE, PROFILE, baseline, bounded, candidate_source,
    fail, load_candidate, load_definition, read_json, verify_retained,
)
from rfad.application.network_records import descriptor, find_record, read_dataset, samples, assessment_summary
from rfad.application.project_contract import _fields, _uuid
from rfad.application.project_study_contract import initial_specification as mesh_specification
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import library
from rfad.domain.resource_limits import MAX_WORKER_SOURCE_FILES
from rfad.domain.units import Quantity


READS = {"sweep.context", "sweep.preview", "sweep.list", "sweep.get", "sweep.page", "sweep.result", "sweep.quantity"}
MUTATIONS = {"sweep.create", "sweep.start", "sweep.cancel", "sweep.resume"}
MAX_STUDIES = 32
FIELDS = {
    "sweep.context": set(), "sweep.list": set(),
    "sweep.preview": {"expected_revision", "specification"},
    "sweep.create": {"expected_revision", "specification", "review_hash"},
    "sweep.get": {"study_id"}, "sweep.start": {"study_id"},
    "sweep.cancel": {"study_id"}, "sweep.resume": {"study_id"},
    "sweep.page": {"study_id", "offset", "limit"},
    "sweep.result": {"study_id", "index", "offset", "limit", "row", "column"},
    "sweep.quantity": {"expected_revision", "quantity", "display_unit"},
}


def validate_input(method, context, data):
    """! @brief 공개 요청을 닫힌 계약과 프로젝트 소유권으로 제한한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, FIELDS[method])
    for name in ("study_id", "expected_revision"):
        if name in data:
            _uuid(data[name])
    if "review_hash" in data:
        from rfad.domain.network_library import digest
        digest(data["review_hash"], "review_hash")
    if "specification" in data and len(canonical_bytes(data["specification"])) > 64 * 1024:
        fail("연구 입력 원문이 64 KiB를 초과했습니다.", "E_RESOURCE")
    if method in ("sweep.page", "sweep.result"):
        if type(data["offset"]) is not int or data["offset"] < 0:
            fail("조회 시작 순번은 0 이상의 정수여야 합니다.")
        maximum = PAGE_SIZE if method == "sweep.page" else 201
        if type(data["limit"]) is not int or not 1 <= data["limit"] <= maximum:
            fail("조회 페이지 크기가 지원 범위를 벗어났습니다.", "E_RESOURCE")


def owned(service, state, context, identity):
    """! @brief 다른 프로젝트의 연구와 결과를 이름이나 UUID만으로 열지 않는다."""
    service._project(state, context)
    study = state.get("sweeps", {}).get(identity)
    if study is None or study["project_id"] != context["project_id"]:
        fail("현재 프로젝트의 연구를 찾을 수 없습니다.", "E_CONFLICT")
    return study


def _network(service, project, document, specification):
    """! @brief 회로 스윕의 자료와 회로 원본을 현재 개정에서 명시적으로 선택한다."""
    selected = specification.get("network") if type(specification) is dict else None
    if selected is None:
        return None
    _fields(selected, {"dataset_id", "circuit_id"})
    model = library(document)
    data, entry = read_dataset(service, project, model, selected["dataset_id"])
    circuit = find_record(model, "circuits", selected["circuit_id"])
    return {"dataset": deepcopy(entry["dataset"]), "entry": deepcopy(entry),
            "circuit": deepcopy(circuit["definition"]), "descriptor": descriptor(data)}


def application_source_manifest(package_root=None):
    """! @brief 주입 서비스 호출까지 명시한 host 의존 소스를 고정하며 native import를 하지 않는다."""
    if package_root is None:
        from rfad.application.source_bundle import HOST, BundleError, build

        try:
            bundle = build(Path(__file__).resolve().parents[3], HOST, max_files=MAX_WORKER_SOURCE_FILES)
        except BundleError as error:
            fail(str(error), error.code)
        return {"schema": "rfad.host-calculation-source/0.2",
                "bundle_sha256": hashlib.sha256(bundle["source_bytes"]).hexdigest(),
                "bundle_bytes": len(bundle["source_bytes"]), "code_files": bundle["code_files"],
                "source_bundle": bundle["source_bundle"]}
    # @brief 명시한 구형 시험/자료 트리의 전체 소스 manifest 읽기 형식은 유지한다.
    root = (Path(__file__).resolve().parents[1] if package_root is None else Path(package_root)).resolve()
    files = []
    for path in root.rglob("*.py"):
        files.append(path)
        if len(files) > MAX_WORKER_SOURCE_FILES:
            fail("host 계산 소스 파일 수가 공통 worker 상한을 벗어났습니다.", "E_RESOURCE")
    files.sort()
    if not 1 <= len(files) <= MAX_WORKER_SOURCE_FILES:
        fail("host 계산 소스 파일 수가 공통 worker 상한을 벗어났습니다.", "E_RESOURCE")
    sources, total = {}, 0
    try:
        for path in files:
            if not path.resolve().is_relative_to(root) or path.is_symlink():
                fail("host 계산 소스가 지정한 패키지 범위를 벗어났습니다.", "E_HASH")
            # @brief solver 묶음과 동일하게 UTF-8 텍스트의 줄바꿈을 정규화한다.
            with path.open("rb") as stream:
                raw = stream.read(4 * 1024**2 + 1)
            if len(raw) > 4 * 1024**2:
                fail("host 계산 소스 한 파일이 4 MiB 상한을 초과했습니다.", "E_RESOURCE")
            text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            total += len(text.encode("utf-8"))
            if total > 4 * 1024**2:
                fail("host 계산 소스의 4 MiB 상한을 초과했습니다.", "E_RESOURCE")
            sources["src/rfad/" + path.relative_to(root).as_posix()] = text
    except (OSError, UnicodeError) as error:
        fail("host 계산 소스 식별을 읽을 수 없습니다: " + str(error), "E_VERSION")
    bundle = canonical_bytes(sources)
    if len(bundle) > 4 * 1024**2:
        fail("host 계산 소스 묶음의 4 MiB 상한을 초과했습니다.", "E_RESOURCE")
    return {"schema": "rfad.host-calculation-source/0.1", "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
            "bundle_bytes": len(bundle), "code_files": [
                {"path": path, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))}
                for path, text in sources.items()]}


def _host_engine_identity():
    """! @brief 패키지 버전뿐 아니라 계산 구현과 host ABI를 함께 재개 조건에 고정한다."""
    return {**installation_metadata(), "application_source": application_source_manifest(),
            "python": {"implementation": sys.implementation.name, "version": platform.python_version(),
                       "system": platform.system(), "machine": platform.machine(),
                       "pointer_bits": struct.calcsize("P") * 8, "byteorder": sys.byteorder}}


def _environment(service, kind):
    """! @brief 생성 시점의 실제 환경을 고정하며 없는 runtime을 만들지 않는다."""
    return (None if service.solver.runtime is None or kind == "circuit_sweep" else deepcopy(service.solver.runtime.identity),
            _host_engine_identity() if kind == "circuit_sweep" else None)


def _labels(document, circuit):
    """! @brief UUID 대신 기준 원본에서 사용자가 정한 이름을 조회한다."""
    from rfad.domain.sweep_inputs import numerical_fields

    labels = {"parameter:" + key: row["name"] for key, row in document["parameters"].items()}
    labels.update({"solver_setting:" + row["id"]: row["label"] for row in numerical_fields()})
    if circuit is not None:
        for row in circuit["elements"]:
            labels["circuit_value:" + row["id"]] = row["name"] + " 값"
            labels["circuit_state:" + row["id"]] = row["name"] + " 실장 상태"
    return labels


def _display_candidate(candidate, labels):
    """! @brief 봉인 값은 유지하고 화면 전용 이름/단위/숫자만 별도로 투영한다."""
    result = deepcopy(candidate)
    states = {"connected": "연결", "open": "개방", "short": "단락", "dnp": "미실장"}
    for row in result["values"]:
        row["name"] = labels.get(row["kind"] + ":" + row["id"], "원본 변수")
        if type(row["value"]) is dict:
            quantity = Quantity(**row["value"])
            row["unit"] = quantity.display_unit
            row["text"] = "미정" if quantity.value_si is None else format(quantity.as_unit(quantity.display_unit), ".15g")
        else:
            row["text"] = states.get(row["value"], row["value"])
            row["unit"] = ""
    return result


def _candidate_row(candidate):
    """! @brief 대형 원본을 전송하지 않고 실제 후보의 값과 이유만 표시한다."""
    return {"ordinal": candidate["ordinal"], "indices": candidate["indices"],
            "values": deepcopy(candidate["values"]), "evaluation_key": candidate["evaluation_key"],
            "validation_status": candidate["status"], "state": "planned", "outcome": "not_evaluated",
            "diagnostics": deepcopy(candidate["diagnostics"]), "attempts": [], "results": {}}


def preview(service, state, project, document, data):
    """! @brief 유한 후보를 하나씩 검사하며 전체 Cartesian 배열이나 파일을 만들지 않는다."""
    from rfad.domain.design_sweep import validate_specification, candidate_count, candidate_at

    if data["expected_revision"] != document["revision_id"]:
        fail("연구 입력의 기준 개정이 바뀌었습니다. 다시 조회하십시오.", "E_CONFLICT")
    network = _network(service, project, document, data["specification"])
    circuit = None if network is None else network["circuit"]
    specification = validate_specification(data["specification"], document, circuit=circuit)
    count = candidate_count(specification)
    counts = {"total": count, "valid": 0, "invalid": 0, "unsupported": 0, "duplicates": 0}
    first_page, keys = [], {}
    for index in range(count):
        candidate = candidate_at(document, specification, index, circuit=circuit)
        counts[candidate["status"]] += 1
        row = _candidate_row(candidate)
        key = candidate["evaluation_key"]
        if candidate["status"] == "valid":
            if key in keys:
                row["duplicate_of"] = keys[key]
                counts["duplicates"] += 1
            else:
                keys[key] = index
        if index < PAGE_SIZE:
            first_page.append(_display_candidate(row, _labels(document, circuit)))
    runtime, engine = _environment(service, specification["type"])
    fingerprint = canonical_hash({"profile": PROFILE, "base": canonical_hash(document),
        "input": data["specification"], "normalized": specification, "network": network,
        "runtime_identity": runtime, "engine_identity": engine})
    native_count = len(keys) if specification["type"] != "circuit_sweep" else 0
    response = bounded({"profile": PROFILE, "project_id": document["project_id"],
        "revision_id": document["revision_id"], "review_hash": fingerprint, "can_create": True,
        "candidate_count": count, "counts": counts, "candidates": first_page,
        "next_offset": PAGE_SIZE if count > PAGE_SIZE else None, "diagnostics": [],
        "budget_estimate": {"kind": "candidate_count_only_plans_checked_lazily", "native_solves": native_count,
            "native_budget_insufficient": native_count > specification["budget"]["max_native_solves"],
            "ram_bytes": None, "disk_bytes": None,
            "note": "실행 직전 후보별 실제 계획의 자원 추정치를 검사합니다. 전체 RAM/디스크 사용량 예측은 미확립입니다."},
        "source_preserved": True, "physical_validation": "not_established"})
    return response, specification, network, runtime, engine


def _defaults():
    """! @brief 물성을 채우지 않는 비실행 상태의 입력 틀을 제공한다."""
    return {"schema": "rfad.design-sweep-spec/0.1", "name": "새 설계 변수 스윕", "type": "grid_sweep",
        "combination": "cartesian", "variables": [], "rows": [],
        "settings": mesh_specification()["settings"], "network": None, "target_ids": [], "target_contexts": [],
        "budget": {"max_candidates": 128, "max_native_solves": 128, "wall_seconds": 3600,
                   "ram_bytes": 2 * 1024**3, "disk_bytes": 4 * 1024**3, "concurrency": 1},
        "source_refs": []}


def _setting_fields(settings):
    """! @brief 수치 설정의 SI와 표시 단위 원문을 각각 제공한다."""
    from rfad.domain.sweep_inputs import numerical_fields

    fields = numerical_fields()
    for row in fields:
        value = settings
        for key in row["id"].split("."):
            value = value.get(key) if type(value) is dict else None
        if value is None:
            row.update(quantity=None, text="", current=None, eligible=False, reason="기준 설정에 없는 선택 항목입니다.")
        else:
            quantity = Quantity.from_value(value, row["unit"], source_refs=["명시 수치 설정의 초기 제안; 수렴 미검증"])
            display_unit = row["unit"]
            if row["dimension"] == "frequency":
                display_unit = "GHz" if abs(value) >= 1e9 else "MHz" if abs(value) >= 1e6 else "kHz" if abs(value) >= 1e3 else "Hz"
            saved = quantity.to_dict()
            saved["display_unit"] = display_unit
            row.update(quantity=saved, text=format(quantity.as_unit(display_unit), ".15g"),
                       display_unit=display_unit, current=value, eligible=True, reason=None)
    return fields


def context(service, state, project, document):
    """! @brief 사람이 읽는 변수/단위와 저장된 조건을 제공하고 기본값의 지위를 명시한다."""
    from rfad.domain.design_sweep import context_variables
    from rfad.application.network_forms import circuit_display

    initial = _defaults()
    band = initial["settings"]["frequency_hz"]
    frequencies = [band["start"], (band["start"] + band["stop"]) / 2, band["stop"]]
    optional = {"radiation": {"frequency_hz": frequencies, "theta_step_deg": 15,
                             "phi_step_deg": 15, "box_clearance_mm": 30},
                "feature_subdivisions": 1, "power_balance": {"max_relative_residual": 0.03}}
    model = library(document)
    circuits = deepcopy(model["circuits"])
    for row in circuits:
        row["display"] = circuit_display(row["definition"])
    datasets = []
    for row in model["datasets"]:
        dataset, entry = read_dataset(service, project, model, row["id"])
        description = descriptor(dataset)
        overview = {key: description[key] for key in ("parameter_kind", "unit", "port_ids", "port_names",
            "wave_definition", "phasor_convention", "reference_planes", "port_modes", "current_orientation",
            "sample_count", "frequency_min_hz", "frequency_max_hz", "z0_ohm", "z0_frequency_dependent")}
        overview["full_conditions_method"] = "network.get"
        datasets.append({**entry, "descriptor": overview})
    fields = _setting_fields(initial["settings"])
    parameters = context_variables(document)
    for row in parameters:
        row["eligible"] = not row["read_only"]
    targets = [{key: deepcopy(row[key]) for key in ("id", "name", "revision_id", "port_id", "reference_impedance", "criteria")}
               for row in document["targets"]]
    return bounded({"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
        "capabilities": {"types": ["grid_sweep", "numerical_study", "circuit_sweep"],
            "combinations": ["cartesian", "paired", "explicit_rows"],
            "runtime_configured": service.solver.runtime is not None, "network_engine": installation_metadata(),
            "native_checkpoint_resume": False, "physical_validation": "not_established"},
        "parameters": parameters, "numerical_fields": fields,
        "optional_settings_defaults": optional,
        "optional_numerical_fields": [row for row in _setting_fields({**initial["settings"], **optional})
                                      if row["id"].startswith("radiation.") or row["id"] == "feature_subdivisions"],
        "optional_radiation_frequencies": [{"quantity": Quantity(value, "frequency", "GHz", "user_entered",
            ["명시 방사 표본의 초기 제안; 수렴 미검증"]).to_dict(), "text": format(value / 1e9, ".15g"),
            "unit": "GHz"} for value in frequencies],
        "circuits": circuits, "datasets": datasets, "targets": targets,
        "ports": [{"id": row["id"], "name": row["name"], "reference_plane": row["reference_plane"]} for row in document["ports"]],
        "initial_specification": initial,
        "budget_display": {"wall_seconds": {"text": "60", "unit": "min"},
                           "ram_bytes": {"text": "2", "unit": "GiB"}, "disk_bytes": {"text": "4", "unit": "GiB"}},
        "budget_limits": {"max_candidates": 128, "max_native_solves": 128, "concurrency": 1, "max_studies": MAX_STUDIES},
        "material_defaults_supplied": False})


def _environment_reason(service, definition):
    """! @brief 저장 후 환경이 바뀌면 읽기는 유지하고 새 실행/재개만 차단한다."""
    kind = definition["specification"]["type"]
    try:
        runtime, engine = _environment(service, kind)
    except ProjectError as error:
        return "저장된 결과는 읽을 수 있으나 현재 계산 환경을 확인할 수 없습니다: " + error.message
    if kind != "circuit_sweep" and runtime is None:
        return "명시적으로 구성한 openEMS 런타임이 필요합니다."
    if runtime != definition["runtime_identity"] or engine != definition["engine_identity"]:
        return "연구를 고정한 실행 환경과 다릅니다. 기존 근거를 보존하고 새 연구를 검토하십시오."
    if kind == "circuit_sweep" and engine["available"] is False:
        return "고정 네트워크 계산 환경이 필요합니다."
    return None


def actions(service, state, study, definition):
    """! @brief 유효한 동작만 표시하되 실제 명령에서도 같은 조건을 재검사한다."""
    other = any(row["state"] in ACTIVE and row["study_id"] != study["study_id"]
                for collection in ("studies", "sweeps") for row in state.get(collection, {}).values())
    reason = _environment_reason(service, definition)
    exhausted = study["usage"]["wall_seconds"] >= definition["specification"]["budget"]["wall_seconds"]
    return {"start": study["state"] == "ready" and not other and reason is None and not exhausted,
            "cancel": study["state"] in ACTIVE | {"ready"},
            "resume": study["state"] in {"cancelled", "interrupted", "failed", "blocked"}
                      and not other and reason is None and not exhausted}, reason


def _budget_display(values):
    """! @brief 예산 원본을 유지하고 시간/바이트의 짧은 표시 문자열만 만든다."""
    result = {}
    for name, value in values.items():
        if name.endswith("_bytes"):
            scale, unit = next(((scale, unit) for scale, unit in
                ((1024**3, "GiB"), (1024**2, "MiB"), (1024, "KiB"), (1, "B")) if value >= scale), (1, "B"))
        elif name == "wall_seconds":
            scale, unit = (3600, "h") if value >= 3600 else (60, "min") if value >= 60 else (1, "s")
        else:
            scale, unit = 1, "회"
        result[name] = {"text": format(value / scale, ".6g"), "unit": unit}
    return result


def view(service, state, study):
    """! @brief 전체 후보 배열 대신 고정 입력과 요약 상태를 조회한다."""
    definition, source = baseline(service, study)
    current = service._load(state["projects"][study["project_id"]])
    allowed, reason = actions(service, state, study, definition)
    return bounded({"profile": PROFILE, **{key: deepcopy(study[key]) for key in
        ("study_id", "name", "type", "state", "snapshot", "counts", "current_job_id", "created_at", "message")},
        "source_revision_matches_current": current["revision_id"] == study["snapshot"]["revision_id"],
        "specification": definition["specification"], "original_specification": definition["original_specification"],
        "budget_usage": deepcopy(study["usage"]), "current_candidate": study["next_index"],
        "budget_display": _budget_display({key: definition["specification"]["budget"][key]
                                           for key in ("wall_seconds", "ram_bytes", "disk_bytes")}),
        "usage_display": _budget_display(study["usage"]),
        "variable_labels": _labels(source, None if definition["network"] is None else definition["network"]["circuit"]),
        "allowed_actions": allowed, "stop_reason": reason or study.get("stop_reason"),
        "convergence_status": "not_established", "physical_validation": "not_established"})


def read(service, method, params):
    """! @brief 기존 결과는 native runtime 없이도 페이지 단위로 읽을 수 있다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 스윕 API 버전입니다.", "E_VERSION")
    context_data, data = params["context"], params["input"]
    validate_input(method, context_data, data)
    if method == "sweep.quantity":
        from rfad.application.network_service import read as network_read
        return network_read(service, "network.quantity", params)
    state = service.journal.read()
    project = service._project(state, context_data)
    if method in ("sweep.context", "sweep.preview"):
        document = service._load(project)
        if method == "sweep.context":
            return context(service, state, project, document)
        return preview(service, state, project, document, data)[0]
    if method == "sweep.list":
        return bounded({"profile": PROFILE, "studies": [{key: deepcopy(row[key]) for key in
            ("study_id", "name", "type", "state", "created_at", "counts")}
            for row in sorted(state.get("sweeps", {}).values(), key=lambda row: row["created_at"], reverse=True)
            if row["project_id"] == context_data["project_id"]]})
    study = owned(service, state, context_data, data["study_id"])
    if method == "sweep.get":
        return view(service, state, study)
    definition, source = baseline(service, study)
    labels = _labels(source, None if definition["network"] is None else definition["network"]["circuit"])
    if method == "sweep.page":
        total, offset = study["counts"]["total"], data["offset"]
        if offset > total:
            fail("후보 페이지가 범위를 벗어났습니다.")
        rows = []
        for index in range(offset, min(offset + data["limit"], total)):
            candidate = load_candidate(service, study, index)
            row = candidate if candidate is not None else _candidate_row(candidate_source(service, study, index))
            rows.append(_display_candidate(row, labels))
        return bounded({"profile": PROFILE, "study_id": study["study_id"], "offset": offset,
            "total": total, "next_offset": offset + len(rows) if offset + len(rows) < total else None, "candidates": rows})
    candidate = load_candidate(service, study, data["index"])
    if candidate is None or "dataset" not in candidate.get("results", {}):
        fail("선택한 후보에는 보존된 복소 결과가 없습니다.", "E_MISSING_ARTIFACT")
    result = read_json(service, candidate["results"]["dataset"])
    from rfad.domain.network_data import validate_dataset
    validate_dataset(result)
    assessments = []
    if "assessment" in candidate["results"]:
        saved = read_json(service, candidate["results"]["assessment"])
        assessments = [assessment_summary(item) for item in saved["assessments"]]
    return bounded({"profile": PROFILE, "study_id": study["study_id"], "index": data["index"],
        "entry": {"id": str(data["index"]), "name": study["name"] + " / 후보 " + str(data["index"] + 1),
                  "dataset": candidate["results"]["dataset"], "kind": "sweep_candidate"},
        "descriptor": descriptor(result), "page": samples(result, data["offset"], data["limit"], data["row"], data["column"]),
        "assessments": assessments, "snapshot": definition["snapshot"], "candidate": _display_candidate(candidate, labels)})


def admit(service, state, method, context_data, data):
    """! @brief 검토 해시와 영수증을 같은 transaction에서 고정하며 저장과 실행을 분리한다."""
    validate_input(method, context_data, data)
    if method == "sweep.create":
        if len(state.setdefault("sweeps", {})) >= MAX_STUDIES:
            fail("스윕 보존 상한 32개에 도달했습니다.", "E_RESOURCE")
        project = service._project(state, context_data)
        raw, document = service.repository.read(project["current"])
        response, specification, network, runtime, engine = preview(service, state, project, document, data)
        if response["review_hash"] != data["review_hash"]:
            fail("원본/입력/실행 환경이 검토 뒤 바뀌었습니다.", "E_CONFLICT")
        snapshot = service.operations.prepare_snapshot(state, project, document, raw, {"description": "명시적 연구: " + specification["name"]})
        identity = str(uuid4())
        definition = {"schema": DEFINITION_SCHEMA, "study_id": identity, "snapshot": snapshot,
            "original_specification": deepcopy(data["specification"]), "specification": specification,
            "network": network, "runtime_identity": runtime, "engine_identity": engine,
            "candidate_count": response["candidate_count"], "review_hash": data["review_hash"]}
        encoded = canonical_bytes(definition)
        retained_bytes = len(encoded) + len(raw)
        if retained_bytes > specification["budget"]["disk_bytes"]:
            fail("정의와 원본 보존 비용이 지정한 디스크 예산을 초과했습니다.", "E_RESOURCE")
        service.operations.publish_snapshot(state, snapshot, raw)
        reference = service.journal.put_immutable(project["path"] + "/sweeps/" + identity + "/definition.json", encoded)
        count = response["candidate_count"]
        study = {"study_id": identity, "project_id": context_data["project_id"], "name": specification["name"],
            "type": specification["type"], "state": "ready", "created_at": service._now(), "snapshot": snapshot,
            "definition": reference, "runtime_identity_hash": canonical_hash(runtime), "generation": str(uuid4()),
            "next_index": 0, "records": {}, "physical_cache": {}, "current_job_id": None,
            "counts": {"total": count, "completed": 0, "failed": 0, "pending": count, "running": 0, "skipped": 0},
            "usage": {"native_solves": 0, "wall_seconds": 0.0, "disk_bytes": retained_bytes},
            "active_since": None, "message": "원본과 입력을 고정했습니다. 실행을 별도로 선택하십시오.", "stop_reason": None}
        state["sweeps"][identity] = study
        return {"study_id": identity, "state": "ready", "snapshot": snapshot, "review_hash": data["review_hash"]}
    study = owned(service, state, context_data, data["study_id"])
    definition = load_definition(service, study)
    allowed, reason = actions(service, state, study, definition)
    action = method.split(".")[1]
    if not allowed[action]:
        fail(reason or "현재 연구 상태에서 해당 동작을 수행할 수 없습니다.", "E_CONFLICT")
    if action == "cancel":
        study["state"] = "cancel_requested" if study["state"] in ACTIVE else "cancelled"
        job = state["jobs"].get(study["current_job_id"])
        if job is not None:
            service.solver.cancel_job(job, "설계 스윕의 명시적 취소")
        study["message"] = "완료 후보를 보존하고 현재 작업의 실제 종료를 확인합니다."
    else:
        verify_retained(service, study)
        study.update(state="resuming" if action == "resume" else "running", generation=str(uuid4()),
                     active_since=service._now(), stop_reason=None,
                     message="고정한 원본과 누적 예산으로 후보를 진행합니다.")
    return {"study_id": study["study_id"], "state": study["state"]}


def recover(service, state):
    """! @brief 중단 기간도 보수적으로 예산에 포함하고 자동 재실행하지 않는다."""
    for study in state.setdefault("sweeps", {}).values():
        if study["state"] in ACTIVE:
            if study["active_since"] is not None:
                study["usage"]["wall_seconds"] += max(0.0, service._now() - study["active_since"])
            study.update(state="interrupted", active_since=None,
                         message="서비스가 종료되었습니다. 원본/완료 결과와 실제 guest 종료 확인 후 명시적으로 재개하십시오.")
