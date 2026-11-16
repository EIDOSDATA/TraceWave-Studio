"""! @brief 고정 source/pin의 이전 조건과 자료를 기존 교환 직렬화로 내보낸다."""

import base64
from copy import deepcopy
import hashlib

from rfad.application.canonical import canonical_bytes
from rfad.application.result_sources import fail, owned_reference, read_solver_artifact
from rfad.domain.errors import ProjectError


def available_formats(resolved):
    """! @brief 원문 유무와 실제 직렬화 범위를 구분하여 선택 가능한 형식만 안내한다."""
    from rfad.adapters.network_files import write_touchstone
    from rfad.adapters.network_hdf5 import installation_metadata

    output = ["csv"]
    try:
        if len(write_touchstone(resolved["dataset"])) <= 512 * 1024:
            output.append("touchstone")
    except ProjectError:
        pass
    entry = resolved["entry"]
    if (entry is not None and entry.get("normalized_hdf5") is not None) or installation_metadata()["version_matches"]:
        output.append("hdf5")
    reference = None if entry is None else entry.get("raw")
    if reference is None and resolved["solver_record"] is not None:
        reference = resolved["solver_record"]["normalized"]
    if reference is not None and reference["bytes"] <= 512 * 1024:
        output.append("source")
    return output


def encode_files(service, project, network, entry, format_name, *, solver_record=None):
    """! @brief 현재/과거 조회가 동일한 직렬화 및 파일 크기 경계를 재사용한다."""
    from rfad.adapters.network_files import write_csv, write_touchstone, csv_export_mapping

    mapping, original_name = None, None
    if format_name == "touchstone":
        raw = write_touchstone(network)
        suffix = ".s" + str(len(network["port_ids"])) + "p"
    elif format_name == "csv":
        raw = write_csv(network)
        mapping = csv_export_mapping(network)
        suffix = ".csv"
    elif format_name == "hdf5":
        if entry is not None and entry.get("normalized_hdf5") is not None:
            raw = service.journal.read_artifact(owned_reference(project, entry["normalized_hdf5"]))
        else:
            from rfad.adapters.network_hdf5 import encode_network_hdf5

            raw = encode_network_hdf5(network)
        suffix = ".h5"
    elif format_name == "source":
        if entry is not None and entry.get("raw") is not None:
            raw = service.journal.read_artifact(owned_reference(project, entry["raw"]))
            suffix = ".json" if entry["kind"] == "solver" else ".bin"
            name = network["provenance"].get("source_file_name")
            if type(name) is str and 0 < len(name) <= 128 and not any(char in name for char in '/\\:<>"|?*') and not name.endswith((".", " ")):
                original_name = name
        elif solver_record is not None:
            raw = read_solver_artifact(service, project, solver_record, solver_record["normalized"])
            suffix = ".json"
        else:
            fail("파생 결과에는 가져온 원문 파일이 없습니다. 정규 CSV 또는 HDF5를 선택하세요.", "E_CONFLICT")
    else:
        fail("지원하지 않는 결과 내보내기 형식입니다.", "E_UNSUPPORTED")
    if len(raw) > 512 * 1024:
        fail("이 전송 profile의 내보내기 상한 512 KiB를 초과했습니다.", "E_RESOURCE")
    return raw, original_name or "network" + suffix, mapping


def exported(service, resolved, format_name):
    """! @brief 조회로 계산/파일을 게시하지 않고 실제 자료와 당시 조건의 전송 바이트만 만든다."""
    network, entry = resolved["dataset"], resolved["entry"]
    raw, file_name, mapping = encode_files(service, resolved["project"], network, entry, format_name,
        solver_record=resolved["solver_record"])
    identity = {"source": deepcopy(resolved["source"]), "pin": deepcopy(resolved["pin"])}
    sidecar = {"schema": "rfad.network-export/0.1", "export_context_schema": "rfad.result-export-context/0.1",
        **identity, "dataset": deepcopy(entry), "dataset_artifact": deepcopy(resolved["dataset_artifact"]),
        "descriptor": deepcopy(resolved["descriptor"]), "provenance": deepcopy(network["provenance"]), "mapping": mapping,
        "source_revision": deepcopy(resolved["source_revision"]), "source_snapshot": deepcopy(resolved["source_snapshot"]),
        "source_document_role": resolved["source_document_role"], "selection_values": deepcopy(resolved["selection_values"]),
        "historical_assessments": deepcopy(resolved["historical_assessments"]), "physical_validation": "not_established",
        "numerical_details": deepcopy(resolved["numerical_details"]),
        "source_unmodified": True}
    response = {"profile": "rfad.network-workspace/0.1", **identity,
        "file_name": file_name, "content_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "sidecar": sidecar}
    if len(canonical_bytes(response)) > 900 * 1024:
        fail("결과와 과거 조건의 내보내기 응답이 900 KiB를 초과했습니다.", "E_RESOURCE")
    return response
