"""! @brief 제한된 NDJSON 조회와 선택한 프로젝트 서비스를 연결한다."""

import json
import math
import platform
import sys
from typing import BinaryIO, TextIO

from rfad import __version__
from rfad.domain.errors import ProjectError
from rfad.domain.project import COMMANDS, SCHEMA_VERSION, LEGACY_SCHEMA_VERSION
from rfad.domain.expressions import ENGINE_VERSION
from rfad.application.catalog_api import METHODS as CATALOG_METHODS
from rfad.application.catalog_api import describe as describe_catalog, query as query_catalog
from rfad.application.pcb_selection_contract import READ_METHODS as PCB_SELECTION_READS, MUTATION_METHODS as PCB_SELECTION_MUTATIONS
from rfad.application.project_study_contract import READS as STUDY_READS, MUTATIONS as STUDY_MUTATIONS

CONTRACT_VERSION = "rfad.api/2.0"
from rfad.domain.resource_limits import MAX_FRAME_BYTES, MAX_DOCUMENT_BYTES, MAX_SELECTION_RESULT_BYTES
MAX_BATCH_ITEMS = 16
MAX_STRING_BYTES = 8192
MAX_DEPTH = 64
APPLICATION_ERRORS = {
    "E_VERSION": 1001, "E_RESOURCE": 1002, "E_SCHEMA": 1003,
    "E_CONFLICT": 1004, "E_IDEMPOTENCY_EXPIRED": 1005, "E_DISK": 1006,
    "E_HASH": 1007, "E_UNSUPPORTED": 1008, "E_UNIT": 1009,
    "E_EXPR_DOMAIN": 1010, "E_EXPR_CYCLE": 1011,
    "E_GEOMETRY": 1012, "E_PORT": 1013, "E_CONNECTIVITY": 1014,
    "E_MATERIAL_UNKNOWN": 1015, "E_MATERIAL_RANGE": 1016,
    "E_SOLVER": 1017, "E_MISSING_ARTIFACT": 1018,
}
PROJECT_MUTATIONS = {"project.open", "project.apply_command", "editor.apply", "canvas.apply", "project.undo", "project.redo", "project.save", "snapshot.create", "design.validate", "job.cancel", "geometry.build", "export.build", "export.preview"}
PROJECT_MUTATIONS.update({"solver.plan", "solver.prepare", "job.submit"})
PROJECT_MUTATIONS.update(PCB_SELECTION_MUTATIONS)
PROJECT_MUTATIONS.update(STUDY_MUTATIONS)


def capabilities(service=None, catalog=None) -> dict:
    """! @brief 구현한 조회 기능과 아직 구현하지 않은 제품 기능을 구분한다."""
    result = {
        "contract_version": CONTRACT_VERSION,
        "service_version": __version__,
        "profile": "rfad.bootstrap/0.1",
        "runtime": {"python": platform.python_version(), "os": sys.platform},
        "methods": {"capabilities.get": {"status": "implemented", "api_id": "API-001"}},
        "features": [
            {"name": name, "status": "declared", "evidence": []}
            for name in ("project.persistence", "cad.step", "solver.openems", "gui.wxwidgets")
        ],
        "tested_envelopes": [],
        "idempotency_policy": {
            "status": "unsupported",
            "mutations_enabled": False,
            "request_key_epoch": None,
            "reason": "Durable command journal is not implemented in this bootstrap profile.",
        },
        "transport": {
            "framing": "ndjson",
            "encoding": "utf-8",
            "max_frame_bytes": MAX_FRAME_BYTES,
            "max_batch_items": MAX_BATCH_ITEMS,
            "max_string_bytes": MAX_STRING_BYTES,
            "max_depth": MAX_DEPTH,
            "stdout": "protocol_only",
            "bulk_artifacts": False,
        },
    }
    if service is not None:
        result["profile"] = "rfad.projects/0.2"
        result["idempotency_policy"] = service.policy()
        result["methods"].update({name: {"status": "implemented", "api_id": api_id} for name, api_id in (
            ("project.open", "API-002"), ("project.apply_command", "API-003"),
            ("project.save", "API-004"), ("snapshot.create", "API-005"),
            ("design.validate", "API-006"),
            ("job.status", "API-015"), ("job.cancel", "API-014"),
        )})
        result["project_profile"] = {
            "schema_version": SCHEMA_VERSION, "readable_schema_versions": [LEGACY_SCHEMA_VERSION, SCHEMA_VERSION],
            "expression_engine": ENGINE_VERSION, "open_modes": ["create", "open", "recover"],
            "commands": [name for name in COMMANDS if name != "pcb_stackup.apply"],
            "max_document_bytes": MAX_DOCUMENT_BYTES, "mutating_batch": False, "mutating_notification": False,
            "scope": "workspace-local versioned projects and optional isolated host CAD worker",
            "design_validation": {"profile": "rfad.design/0.1", "purposes": ["geometry", "step", "em"], "source": "draft_revision", "max_returned_diagnostics": 64},
        }
        result["features"][0]["status"] = "implemented"
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.editor/0.1"} for name in ("editor.get", "editor.apply", "project.undo", "project.redo")})
        result["editor_profile"] = {"profile": "rfad.editor/0.1", "source": "draft_revision", "history_limit": 128, "history_persistent": True, "full_document_returned": False, "max_dto_bytes": 61440}
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.canvas/0.1"} for name in ("canvas.get", "canvas.apply")})
        result["canvas_profile"] = {"profile": "rfad.canvas/0.1", "source": "draft_revision", "unit": "mm", "angle_unit": "deg", "operations": ["create_board", "create_circular_board", "create_layer", "create_dielectric_layer", "create_line", "create_arc", "create_polygon", "create_pad", "create_via", "translate", "remove"], "full_document_returned": False, "max_dto_bytes": 61440}
        result["project_profile"]["geometry_kinds"] = ["line_path", "arc_path", "planar_region", "pad", "via"]
        result["methods"]["cad.latest"] = {"status": "implemented", "extension_profile": "rfad.cad-view/0.1"}
        result["methods"].update({name: {"status": "implemented", "api_id": api_id, "extension_profile": "rfad.step.mechanical/0.1"} for name, api_id in (("geometry.build", "API-008"), ("export.preview", "API-023"), ("export.build", "API-024"))})
        result["cad_profile"] = {"profile": "rfad.step.mechanical/0.1", "runtime_configured": service.cad.runtime is not None,
            "source": "immutable_snapshot", "native_slots": 1, "execution": "separate_host_process",
            "step_schema": "AP242", "result_status": "generated_unverified", "kernel_independent": False,
            "manufacturing_verified": False, "physics_verified": False, "resume_supported": False,
            "max_file_bytes": 67108864, "max_package_bytes": 134217728}
        result["project_profile"]["job_kinds"] = ["data_processing", "cad_build", "export"]
        result["features"][1]["status"] = "implemented"
        result["methods"].update({name: {"status": "implemented", "api_id": api_id, "extension_profile": "rfad.openems.rect-waveguide/0.1"} for name, api_id in (("solver.plan", "API-011"), ("solver.prepare", "API-012"), ("job.submit", "API-013"), ("result.open", "API-016"))})
        result["solver_profile"] = {"profile": "rfad.openems.rect-waveguide/0.1", "runtime_configured": service.solver.runtime is not None,
            "source": "immutable_snapshot", "native_slots": 1, "execution": "wsl2_guest_supervisor",
            "execution_modes": ["solve_and_postprocess", "postprocess_only"], "resume_supported": False,
            "antenna_supported": True, "antenna_profile": "rfad.openems.pcb-single-port/0.1", "antenna_physics_validated": False,
            "board_outlines": ["rectangle", "circle"], "nf2ff_supported": True,
            "nf2ff": {"profile": "rfad.pcb-radiation/0.1", "opt_in": True, "max_frequencies": 3,
                      "angle_steps_deg": [5, 10, 15, 30], "physics_validated": False, "absolute_power_supported": False},
            "max_file_bytes": 67108864, "max_package_bytes": 134217728}
        result["solver_profile"]["profiles"] = ["rfad.openems.rect-waveguide/0.1", "rfad.openems.pcb-single-port/0.1"]
        result["solver_profile"]["profile_scopes"] = {
            "rfad.openems.rect-waveguide/0.1": "empty_reference_project_only",
            "rfad.openems.pcb-single-port/0.1": "user_pcb_single_port_computed_unvalidated",
        }
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.solver-view/0.1"} for name in ("solver.latest", "solver.samples")})
        result["methods"]["solver.radiation"] = {"status": "implemented", "extension_profile": "rfad.radiation-chart/0.1"}
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.project-study/0.1"} for name in STUDY_READS | STUDY_MUTATIONS})
        result["study_profile"] = {"profile": "rfad.project-study/0.1", "source": "immutable_original_project_snapshot",
                                   "max_studies": 32, "max_cases": 6, "resume_supported": True,
                                   "automatic_restart": False, "scope": "mesh_axis_with_optional_radiation_and_loss"}
        result["editor_profile"]["create_selections"] = ["new_parameter", "new_material", "new_net", "new_port"]
        result["project_profile"]["job_kinds"].extend(["em_prepare", "em_analysis"])
        result["features"][2]["status"] = "implemented"
    if service is not None:
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.pcb-selection/0.1"}
                                  for name in sorted(PCB_SELECTION_READS | PCB_SELECTION_MUTATIONS)})
        result["pcb_selection_profile"] = {"profile": "rfad.pcb-selection/0.1", "preview_required": True,
                                            "atomic_apply": True, "source_copies_in_project": True,
                                            "project_schema": SCHEMA_VERSION, "max_result_bytes": MAX_SELECTION_RESULT_BYTES,
                                            "readable_selection_schemas": ["rfad.pcb-selection/0.1", "rfad.pcb-selection/0.2"],
                                            "shared_evidence_supported": True}
    result["catalog_profile"] = describe_catalog(catalog)
    result["methods"].update({
        name: {"status": "implemented", "extension_profile": "rfad.catalog/0.1"}
        for name in sorted(CATALOG_METHODS)
    })
    return result


def _error(request_id: object, code: int, message: str, domain_code: str | None = None) -> dict:
    """! @brief 표준 오류와 제품 오류의 응답 형식을 한 곳에서 구성한다."""
    error = {"code": code, "message": message}
    if domain_code is not None:
        error["data"] = {"domain_code": domain_code, "diagnostics": []}
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    """! @brief 중복 키를 조용히 덮어쓰지 않고 거부한다."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """! @brief JSON에 허용되지 않는 비유한 상수를 거부한다."""
    raise ValueError(f"Non-finite constant: {value}")


def _validate_tree(value: object, depth: int = 0) -> None:
    """! @brief 깊이, 문자열과 부동소수점 입력의 경계를 검사한다."""
    if depth > MAX_DEPTH:
        raise ValueError("JSON nesting limit exceeded")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ValueError("String limit exceeded")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite number")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_tree(key, depth + 1)
            _validate_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_tree(item, depth + 1)


def _dispatch(request: object, service=None, catalog=None) -> dict | None:
    """! @brief 읽기 전용 조회만 허용하며 알림에는 응답하지 않는다."""
    if not isinstance(request, dict):
        return _error(None, -32600, "Invalid Request")
    request_id = request.get("id")
    valid_id = request_id is None or type(request_id) in (str, int, float)
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str) or not valid_id:
        return _error(None, -32600, "Invalid Request")
    notification = "id" not in request
    method = request["method"]
    if service is not None and method in PROJECT_MUTATIONS | PCB_SELECTION_READS | STUDY_READS | {"job.status", "editor.get", "canvas.get", "cad.latest", "result.open", "solver.latest", "solver.samples", "solver.radiation"}:
        if notification and method in PROJECT_MUTATIONS:
            return None
        try:
            params = request.get("params")
            if method in STUDY_READS:
                result = service.studies.read(method, params)
            elif method == "pcb.selection.context":
                result = service.pcb_selection.context(params)
            elif method == "pcb.selection.preview":
                result = service.pcb_selection.preview(params)
            elif method == "pcb.selection.get":
                result = service.pcb_selection.get(params)
            elif method == "job.status":
                result = service.status(params)
            elif method == "editor.get":
                result = service.editor_state(params)
            elif method == "canvas.get":
                result = service.canvas_state(params)
            elif method == "cad.latest":
                result = service.cad_latest(params)
            elif method == "result.open":
                result = service.solver.result_open(params)
            elif method == "solver.latest":
                result = service.solver.latest(params)
            elif method == "solver.samples":
                result = service.solver.samples(params)
            elif method == "solver.radiation":
                result = service.solver.radiation(params)
            else:
                result = service.mutate(method, params)
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ProjectError as error:
            response = _error(request_id, APPLICATION_ERRORS.get(error.code, 1099), error.message, error.code)
            response["error"]["data"]["diagnostics"] = [error.diagnostic()]
        except (ValueError, TypeError, UnicodeError):
            response = _error(request_id, APPLICATION_ERRORS["E_SCHEMA"], "Invalid project input", "E_SCHEMA")
    elif method in CATALOG_METHODS:
        try:
            response = {
                "jsonrpc": "2.0", "id": request_id,
                "result": query_catalog(method, request.get("params"), catalog),
            }
        except ProjectError as error:
            response = _error(request_id, APPLICATION_ERRORS.get(error.code, 1099), error.message, error.code)
            response["error"]["data"]["diagnostics"] = [error.diagnostic()]
    elif method != "capabilities.get":
        response = _error(request_id, -32601, "Method not found")
    else:
        params = request.get("params")
        if not isinstance(params, dict) or set(params) != {"contract_version", "context", "input"}:
            response = _error(request_id, -32602, "Expected contract_version, context and input")
        elif not isinstance(params["context"], dict) or not isinstance(params["input"], dict):
            response = _error(request_id, -32602, "Context and input must be objects")
        elif params["contract_version"] != CONTRACT_VERSION:
            response = _error(request_id, APPLICATION_ERRORS["E_VERSION"], "Unsupported contract version", "E_VERSION")
        elif params["context"] or params["input"]:
            response = _error(request_id, -32602, "Bootstrap capabilities requires empty context and input")
        else:
            try:
                response = {"jsonrpc": "2.0", "id": request_id, "result": capabilities(service, catalog)}
            except ProjectError as error:
                response = _error(request_id, APPLICATION_ERRORS.get(error.code, 1099), error.message, error.code)
    if notification:
        return None
    return response


def handle_frame(frame: bytes, service=None, catalog=None) -> dict | list | None:
    """! @brief 하나의 크기가 제한된 UTF-8 JSON-RPC 메시지를 처리한다.
    @param frame 줄바꿈을 제외한 한 메시지.
    @return 응답 객체이며 알림만 있으면 None.
    """
    if len(frame) > MAX_FRAME_BYTES:
        return _error(None, APPLICATION_ERRORS["E_RESOURCE"], "Frame limit exceeded", "E_RESOURCE")
    try:
        message = json.loads(frame.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        return _error(None, -32700, "Parse error")
    try:
        _validate_tree(message)
    except (ValueError, UnicodeError, RecursionError):
        return _error(None, APPLICATION_ERRORS["E_SCHEMA"], "Input limits or numeric rules violated", "E_SCHEMA")
    if isinstance(message, list):
        if not message:
            return _error(None, -32600, "Invalid Request")
        if len(message) > MAX_BATCH_ITEMS:
            return _error(None, APPLICATION_ERRORS["E_RESOURCE"], "Batch limit exceeded", "E_RESOURCE")
        if service is not None and any(isinstance(item, dict) and isinstance(item.get("method"), str) and item["method"] in PROJECT_MUTATIONS for item in message):
            return _error(None, APPLICATION_ERRORS["E_UNSUPPORTED"], "Mutating batch is not supported", "E_UNSUPPORTED")
        responses = []
        for request in message:
            response = _dispatch(request, service, catalog)
            if response is not None:
                responses.append(response)
        return responses or None
    return _dispatch(message, service, catalog)


def serve(source: BinaryIO, sink: BinaryIO, log: TextIO, service=None, catalog=None) -> int:
    """! @brief 제한된 줄 읽기로 서비스하며 큰 프레임 수신 시 종료한다.
    @param source UTF-8 NDJSON 입력 스트림.
    @param sink 프로토콜 전용 출력 스트림.
    @param log 진단 전용 로그 스트림.
    @return 정상 EOF는 0, 프레임 초과 또는 출력 단절은 2.
    """
    while True:
        line = source.readline(MAX_FRAME_BYTES + 2)
        if not line:
            return 0
        frame = line
        if frame.endswith(b"\n"):
            frame = frame[:-1]
            if frame.endswith(b"\r"):
                frame = frame[:-1]
        oversized = len(frame) > MAX_FRAME_BYTES
        response = handle_frame(frame, service, catalog)
        if response is not None:
            payload = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
            if len(payload) - 1 > MAX_FRAME_BYTES:
                response = _error(None, APPLICATION_ERRORS["E_RESOURCE"], "Response frame limit exceeded", "E_RESOURCE")
                payload = json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
            try:
                sink.write(payload)
                sink.flush()
            except (BrokenPipeError, OSError):
                log.write("Protocol output disconnected.\n")
                return 2
        if oversized:
            log.write("Frame limit exceeded; input closed without draining.\n")
            return 2
