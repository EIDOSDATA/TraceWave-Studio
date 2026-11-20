"""! @brief 파일/기존 계산/파생 회로/목표 평가를 검토용 불변 후보로 구성한다."""

import base64
import binascii
from copy import deepcopy
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields, _uuid
from rfad.application.network_records import assessment_summary, descriptor, find_record, read_dataset, reference, samples
from rfad.domain.design import resolve_scalar
from rfad.domain.network_data import validate_dataset
from rfad.domain.network_library import fail, library, validate_library
from rfad.domain.object_names import validate_name

MAX_IMPORT_BYTES = 512 * 1024
OPERATIONS = {
    "import": {"name", "file_name", "format", "source_base64", "mapping", "declarations"},
    "solver": {"name", "artifact_id"},
    "transform": {"name", "dataset_id", "options"},
    "circuit_save": {"name", "definition"},
    "circuit_apply": {"name", "dataset_id", "circuit_id"},
    "evaluate": {"name", "dataset_id", "target_id", "context"},
    "remove": {"collection", "id"},
}


def imported(parameters, document, identity):
    """! @brief 원문 바이트와 명시 조건 채택을 구분하며 미지 조건을 추정하지 않는다."""
    from rfad.adapters.network_files import parse_csv, parse_touchstone
    from rfad.adapters.network_hdf5 import decode_network_hdf5

    encoded = parameters["source_base64"]
    if type(encoded) is not str or len(encoded) > ((MAX_IMPORT_BYTES + 2) // 3) * 4:
        fail("GUI 가져오기는 원문 512 KiB 이내를 지원합니다.", "source_base64", "E_RESOURCE")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        fail("원문 base64 형식이 유효하지 않습니다.", "source_base64")
    if not 0 < len(raw) <= MAX_IMPORT_BYTES:
        fail("가져올 원문 파일의 크기가 범위를 벗어났습니다.", "source_base64", "E_RESOURCE")
    filename = parameters["file_name"]
    validate_name(filename)
    if any(char in filename for char in "/\\:"):
        fail("파일명에는 경로를 포함하지 마십시오.", "file_name")
    format_name = parameters["format"]
    if format_name == "touchstone":
        if parameters["mapping"] is not None:
            fail("Touchstone에는 CSV 열 대응을 적용하지 않습니다.", "mapping")
        parsed = parse_touchstone(raw, filename)
        data = parsed["network"]
    elif format_name == "csv":
        parsed = parse_csv(raw, parameters["mapping"])
        data = parsed["network"]
    elif format_name == "hdf5":
        if parameters["mapping"] is not None:
            fail("정규 HDF5에는 CSV 열 대응을 적용하지 않습니다.", "mapping")
        data = decode_network_hdf5(raw)
        parsed = {"parser_metadata": {"format": "normalized_hdf5", "profile": "rfad.network-data/0.1"}}
    else:
        fail("지원하지 않는 가져오기 형식입니다.", "format", "E_UNSUPPORTED")
    count = len(data["values_ri"][0])
    declarations = parameters["declarations"]
    allowed = {"port_ids", "port_names", "reference_planes", "port_modes", "current_orientation",
               "wave_definition", "phasor_convention", "conditions", "source_refs"}
    _fields(declarations, set(), allowed)
    original_conditions = {key: deepcopy(data[key]) for key in allowed}
    if not data["port_ids"]:
        data["port_ids"] = [str(uuid5(UUID(identity), "port:" + str(index))) for index in range(count)]
    if "port_ids" in declarations:
        choices = declarations["port_ids"]
        if type(choices) is not list or len(choices) != count:
            fail("원문 순서의 포트 대응이 필요합니다.", "declarations.port_ids")
        valid_ids = {row["id"] for row in document["ports"]}
        for index, choice in enumerate(choices):
            if choice is not None:
                _uuid(choice)
                if choice not in valid_ids:
                    fail("대응할 프로젝트 포트가 없습니다.", "declarations.port_ids", "E_CONFLICT")
                data["port_ids"][index] = choice
    for key, value in declarations.items():
        if key != "port_ids":
            data[key] = deepcopy(value)
    data["provenance"] = {"original": deepcopy(data["provenance"]), "parser": parsed["parser_metadata"],
                          "source_file_name": filename, "source_sha256": reference("source", raw)["sha256"],
                          "original_conditions": original_conditions, "explicit_declarations": deepcopy(declarations)}
    validate_dataset(data)
    return data, raw


def resolved_target(document, target):
    """! @brief 평가 순간의 매개변수 값만 별도 사본에 해석하고 목표 원본은 보존한다."""
    from rfad.domain.host_calculation import resolved_target as resolve
    return resolve(document, target)


def build_candidate(service, state, project, document, request):
    """! @brief 바이트와 명령을 계산하되 writer 게시 전에는 원본/파일을 변경하지 않는다."""
    operation, parameters = request["operation"], request["parameters"]
    service.verify_calculation()
    if type(operation) is not str or operation not in OPERATIONS:
        fail("지원하지 않는 네트워크 작업입니다.", "operation", "E_UNSUPPORTED")
    _fields(parameters, OPERATIONS[operation])
    model = library(document)
    seed = canonical_hash({"base": canonical_hash(document), "operation": operation, "parameters": parameters})
    identity = str(uuid5(UUID(document["project_id"]), "network:" + seed))
    folder = project["path"] + "/network/" + identity
    host_identity = service.calculation_identity()
    source_bytes = service.calculation_runtime.source_bytes
    host_source = reference(project["path"] + "/host-calculation-sources/" + host_identity["application_source"]["bundle_sha256"] + ".json", source_bytes)
    artifacts = {host_source["uri"]: source_bytes}
    output = {"operation": operation, "record_id": identity, "descriptor": None, "page": None,
              "assessment": None, "diagnostics": [], "engine": None}
    if "name" in parameters:
        validate_name(parameters["name"])
    common = {"id": identity, "name": parameters.get("name", ""), "created_revision": document["revision_id"]}
    data = None
    raw = None
    inputs = []
    circuit_id = None
    diagnostics_ref = None
    if operation == "import":
        data, raw = imported(parameters, document, identity)
    elif operation == "solver":
        from rfad.application.network_solver_import import solver_dataset
        data, raw = solver_dataset(service, state, document, parameters["artifact_id"])
    elif operation in ("transform", "circuit_apply"):
        source, source_entry = read_dataset(service, project, model, parameters["dataset_id"])
        inputs = [source_entry["id"]]
        if operation == "transform":
            derived, execution = service.calculate("network.transform", {"dataset": source, "options": parameters["options"]})
        else:
            circuit = find_record(model, "circuits", parameters["circuit_id"])
            circuit_id = circuit["id"]
            derived, execution = service.calculate("network.circuit", {"dataset": source, "circuit": circuit["definition"]})
        data = derived["dataset"]
        diagnostics_payload = canonical_bytes({"schema": "rfad.network-diagnostics/0.1", "samples": derived["diagnostics"]})
        diagnostics_path = folder + "/diagnostics.json"
        artifacts[diagnostics_path] = diagnostics_payload
        diagnostics_ref = reference(diagnostics_path, diagnostics_payload)
        output["diagnostics"] = derived["diagnostics"][:8]
        output["diagnostic_count"] = len(derived["diagnostics"])
        output["diagnostics_artifact"] = diagnostics_ref
        output["diagnostics_preview_limit"] = 8
        output["all_diagnostics_method"] = "network.diagnostics"
        output["engine"] = {**derived["engine"], "host_execution": execution}
        data["provenance"]["host_execution"] = deepcopy(execution)
    elif operation == "circuit_save":
        from rfad.domain.network_circuit import validate_circuit
        from rfad.application.network_forms import circuit_input, circuit_display
        definition = circuit_input(parameters["definition"])
        validate_circuit(definition)
        model["circuits"].append({**common, "definition": definition})
        output["circuit_display"] = circuit_display(definition)
    elif operation == "evaluate":
        source, source_entry = read_dataset(service, project, model, parameters["dataset_id"])
        target = next((row for row in document["targets"] if row["id"] == parameters["target_id"]), None)
        if target is None:
            fail("평가할 목표가 현재 개정에 없습니다.", "target_id", "E_CONFLICT")
        context = deepcopy(parameters["context"])
        _fields(context, {"port_id", "target_port_id", "reference_plane", "frequency_policy"})
        if context["target_port_id"] != target["port_id"]:
            fail("명시한 목표 포트 대응이 현재 목표와 다릅니다.", "context.target_port_id", "E_CONFLICT")
        from rfad.application.network_solver_import import radiation_metrics
        assessment, execution = service.calculate("network.evaluate", {"document": document, "target": target,
            "dataset": source, "context": context, "metrics": radiation_metrics(service, project, source_entry, source)})
        assessment["evidence"] = {"dataset": deepcopy(source_entry["dataset"]), "target_original": deepcopy(target),
                                  "project_revision": document["revision_id"], "context": deepcopy(parameters["context"]),
                                  "host_execution": execution, "host_source": deepcopy(host_source)}
        output["engine"] = {"host_execution": execution}
        payload = canonical_bytes(assessment)
        path = folder + "/assessment.json"
        artifacts[path] = payload
        model["assessments"].append({**common, "dataset_id": source_entry["id"], "target_id": target["id"],
            "target_revision_id": target["revision_id"], "artifact": reference(path, payload), "status": assessment["status"]})
        output["assessment"] = assessment_summary(assessment)
        output["assessment_artifact"] = reference(path, payload)
    else:
        collection = parameters["collection"]
        if collection not in ("datasets", "circuits", "assessments"):
            fail("삭제할 자료 종류가 유효하지 않습니다.", "collection")
        entry = find_record(model, collection, parameters["id"])
        model[collection].remove(entry)
        output["record_id"] = entry["id"]
    if data is not None:
        from rfad.adapters.network_hdf5 import encode_network_hdf5
        data["provenance"]["host_source"] = deepcopy(host_source)
        validate_dataset(data)
        payload = canonical_bytes(data)
        path = folder + "/dataset.json"
        artifacts[path] = payload
        hdf5 = encode_network_hdf5(data)
        hdf5_path = folder + "/normalized.h5"
        artifacts[hdf5_path] = hdf5
        raw_ref = None
        if raw is not None:
            raw_path = folder + "/source.bin"
            artifacts[raw_path] = raw
            raw_ref = reference(raw_path, raw)
        model["datasets"].append({**common, "kind": "imported" if operation == "import" else ("solver" if operation == "solver" else "derived"),
            "dataset": reference(path, payload), "normalized_hdf5": reference(hdf5_path, hdf5),
            "raw": raw_ref, "inputs": inputs, "circuit_id": circuit_id, "diagnostics": diagnostics_ref})
        output["descriptor"] = descriptor(data)
        output["page"] = samples(data)
    service.verify_calculation()
    output["engine"] = {**(output["engine"] or {}), "host_identity_hash": canonical_hash(host_identity), "host_source": host_source}
    for collection in ("datasets", "circuits", "assessments"):
        model[collection].sort(key=lambda row: row["id"])
    validate_library(model)
    return model, artifacts, output
