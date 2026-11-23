"""! @brief 제한된 NDJSON 조회와 선택한 프로젝트 서비스를 연결한다."""

import json
import math
import platform
import sys
from typing import BinaryIO, TextIO

from rfad import __version__
from rfad.domain.errors import ProjectError
from rfad.domain.project import COMMANDS, SCHEMA_VERSION, READABLE_SCHEMA_VERSIONS
from rfad.domain.targets import TARGET_PROFILE, MAX_TARGETS, MAX_SAMPLES, METRICS
from rfad.domain.expressions import ENGINE_VERSION
from rfad.application.catalog_api import METHODS as CATALOG_METHODS
from rfad.application.catalog_api import describe as describe_catalog, query as query_catalog
from rfad.application.pcb_selection_contract import READ_METHODS as PCB_SELECTION_READS, MUTATION_METHODS as PCB_SELECTION_MUTATIONS
from rfad.application.project_archive import MAX_ARCHIVE_BYTES
from rfad.application.project_study_contract import READS as STUDY_READS, MUTATIONS as STUDY_MUTATIONS
from rfad.application import project_activity, project_evidence, solver_conditions_service, solver_evidence, solver_preview, target_editor
from rfad.application import edit_view_contract, edit_view_pages
from rfad.application import exchange_service, exchange_contract
from rfad.application import pcb_exchange_service
from rfad.application import pcb_import_service
from rfad.application import measurement_service, measurement_contract
from rfad.application import archive_export_service, archive_receiver, handoff_evidence, handoff_service
from rfad.application import design_rule_service, physical_setup_service, precision_service, network_service, design_sweep_service, result_service, rf_validation_records, sketch_service, smart_dimension_service, sweep_selection
from rfad.application import large_results

from rfad.application.template_candidates import READ_METHODS as TEMPLATE_READS

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
    "E_NUMERIC": 1020,
}
PROJECT_MUTATIONS = {"project.open", "project.apply_command", "editor.apply", "canvas.apply", "project.undo", "project.redo", "project.save", "snapshot.create", "design.validate", "job.cancel", "geometry.build", "export.build", "export.preview"}
PROJECT_MUTATIONS.update({"solver.plan", "solver.prepare", "job.submit", solver_conditions_service.SAVE})
PROJECT_MUTATIONS.add("export.verify")
PROJECT_MUTATIONS.add(pcb_exchange_service.MUTATION)
PROJECT_MUTATIONS.update(pcb_import_service.MUTATIONS | archive_receiver.MUTATIONS)
PROJECT_MUTATIONS.update(measurement_service.MUTATIONS)
PROJECT_MUTATIONS.update({handoff_service.MUTATION, archive_export_service.MUTATION})
PROJECT_MUTATIONS.update(PCB_SELECTION_MUTATIONS)
PROJECT_MUTATIONS.update(STUDY_MUTATIONS)
PROJECT_MUTATIONS.update(design_sweep_service.MUTATIONS)
PROJECT_MUTATIONS.update(rf_validation_records.MUTATIONS)
PROJECT_MUTATIONS.update(sweep_selection.MUTATIONS)
PROJECT_MUTATIONS.update(large_results.MUTATIONS)
PROJECT_MUTATIONS.update({"target.editor.apply", "template.apply", "design.rules.apply", physical_setup_service.MUTATION, precision_service.MUTATION, network_service.MUTATION, smart_dimension_service.MUTATION, sketch_service.MUTATION})


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
        result["methods"][project_evidence.METHOD] = {"status": "implemented", "extension_profile": "rfad.project-evidence/0.1"}
        for method in (solver_conditions_service.READ, solver_conditions_service.SAVE):
            result["methods"][method] = {"status": "implemented", "extension_profile": "rfad.solver-conditions/0.1"}
        result["methods"][project_activity.METHOD] = {"status": "implemented", "extension_profile": project_activity.PROFILE}
        result["methods"][solver_evidence.METHOD] = {"status": "implemented", "extension_profile": "rfad.solver-evidence/0.1"}
        result["methods"][solver_preview.METHOD] = {"status": "implemented", "extension_profile": "rfad.solver-preview/0.1"}
        result["project_profile"] = {
            "schema_version": SCHEMA_VERSION, "readable_schema_versions": list(READABLE_SCHEMA_VERSIONS),
            "expression_engine": ENGINE_VERSION, "open_modes": ["create", "open", "recover"],
            "commands": [name for name in COMMANDS if name != "pcb_stackup.apply" and not name.startswith("template_instance.")],
            "max_document_bytes": MAX_DOCUMENT_BYTES, "open_result_modes": ["summary"], "mutating_batch": False, "mutating_notification": False,
            "scope": "workspace-local versioned projects and optional isolated host CAD worker",
            "design_validation": {"profile": "rfad.design/0.1", "purposes": ["geometry", "step", "em"], "source": "draft_revision", "max_returned_diagnostics": 64},
            "target_input": {"profile": TARGET_PROFILE, "max_targets": MAX_TARGETS, "max_samples_per_target": MAX_SAMPLES,
                             "physical_modes": ["radiating_rf"], "metrics": list(METRICS), "sampling": ["linear", "explicit"],
                             "evaluation_supported": False, "changes_solver_settings": False, "presets_supported": False},
        }
        result["features"][0]["status"] = "implemented"
        result["methods"].update({name: {"status": "implemented", "extension_profile": large_results.PROFILE}
                                  for name in large_results.READS | large_results.MUTATIONS})
        result["methods"][handoff_evidence.METHOD] = {"status": "implemented", "api_id": "API-027",
                                                    "extension_profile": handoff_evidence.PROFILE}
        result["methods"][handoff_service.MUTATION] = {"status": "implemented", "api_id": "API-026",
                                                       "extension_profile": handoff_service.PROFILE}
        result["methods"].update({name: {"status": "implemented", "extension_profile": handoff_service.PROFILE}
                                  for name in handoff_service.READS})
        result["handoff_profile"] = {"profile": handoff_service.PROFILE, "snapshot_required": True,
            "preview_required": True, "max_package_bytes": 8 * 1024 * 1024, "max_files": 512,
            "read_only_handoff": True, "project_restore_supported": False, "physical_validation": False}
        result["methods"].update({name: {"status": "implemented", "extension_profile": archive_export_service.PROFILE}
                                  for name in archive_export_service.READS | {archive_export_service.MUTATION}})
        result["methods"].update({name: {"status": "implemented", "extension_profile": archive_receiver.PROFILE}
                                  for name in archive_receiver.READS | archive_receiver.MUTATIONS})
        result["archive_receive_profile"] = {"profile": archive_receiver.PROFILE, "zip_bytes": MAX_ARCHIVE_BYTES,
            "chunk_bytes": archive_receiver.CHUNK_BYTES, "preview_required": True, "execution_on_restore": False}
        result["methods"].update({name: {"status": "implemented", "extension_profile": pcb_exchange_service.PROFILE}
                                  for name in pcb_exchange_service.READS | {pcb_exchange_service.MUTATION}})
        result["methods"].update({name: {"status": "implemented", "extension_profile": pcb_import_service.PROFILE}
                                  for name in pcb_import_service.READS | pcb_import_service.MUTATIONS})
        result["pcb_import_profile"] = {"profile": pcb_import_service.PROFILE, "formats": sorted(pcb_import_service.FORMATS),
            "runtime_configured": service.exchange.runtime is not None, "max_files": pcb_import_service.MAX_FILES,
            "source_and_report_bytes": pcb_import_service.MAX_BYTES, "chunk_bytes": pcb_import_service.CHUNK_BYTES,
            "preview_required": True, "atomic_apply": True, "manufacturing_verified": False, "physics_verified": False}
        result["pcb_features_profile"] = {"profile": pcb_exchange_service.PROFILE, "project_schema": SCHEMA_VERSION,
            "operations": sorted(pcb_exchange_service.OPERATIONS), "limits": pcb_exchange_service.LIMITS,
            "preview_required": True, "atomic_apply": True, "solver_mechanical_supported": False,
            "manufacturing_verified": False, "measurement_verified": False}
        result["methods"].update({name: {"status": "implemented", "extension_profile": design_rule_service.PROFILE}
                                  for name in design_rule_service.READS | {"design.rules.apply"}})
        result["methods"].update({name: {"status": "implemented", "extension_profile": physical_setup_service.PROFILE}
                                  for name in physical_setup_service.READS | {physical_setup_service.MUTATION}})
        result["methods"].update({name: {"status": "implemented", "extension_profile": precision_service.PROFILE}
                                  for name in precision_service.READS | {precision_service.MUTATION}})
        result["methods"].update({name: {"status": "implemented", "extension_profile": smart_dimension_service.model.PROFILE}
                                  for name in smart_dimension_service.READS | {smart_dimension_service.MUTATION}})
        result["methods"].update({name: {"status": "implemented", "extension_profile": sketch_service.sketch.PROFILE}
                                  for name in sketch_service.READS | {sketch_service.MUTATION}})
        result["methods"].update({name: {"status": "implemented", "extension_profile": network_service.PROFILE}
                                  for name in network_service.READS | {network_service.MUTATION}})
        result["methods"].update({name: {"status": "implemented", "api_id": "API-022", "extension_profile": measurement_service.PROFILE}
                                  for name in measurement_service.READS | measurement_service.MUTATIONS})
        result["measurement_profile"] = {"profile": measurement_service.PROFILE,
            "preview_required": True, "atomic_apply": True, "immutable_record_versions": True,
            "alignment": ["permute_ports", "renormalize", "linear_ri"], "automatic_interpolation": False,
            "uncertainty_propagation": False, "physical_validation": False,
            "attachment_bytes": measurement_contract.MAX_ATTACHMENT_BYTES,
            "attachment_count": measurement_contract.MAX_ATTACHMENTS}
        result["methods"].update({name: {"status": "implemented", "extension_profile": design_sweep_service.PROFILE}
                                  for name in design_sweep_service.READS | design_sweep_service.MUTATIONS})
        result["methods"].update({name: {"status": "implemented", "extension_profile": rf_validation_records.PROFILE}
                                  for name in rf_validation_records.READS | rf_validation_records.MUTATIONS})
        result["methods"].update({name: {"status": "implemented", "extension_profile": sweep_selection.PROFILE}
                                  for name in sweep_selection.READS | sweep_selection.MUTATIONS})
        result["sweep_profile"] = {"profile": design_sweep_service.PROFILE, "max_candidates": 128,
            "page_size": 25, "native_concurrency": 1, "lazy_candidates": True, "preview_required": True,
            "native_checkpoint_resume": False, "physical_validation": False}
        result["methods"].update({name: {"status": "implemented", "extension_profile": result_service.PROFILE}
                                  for name in result_service.READS})
        result["result_profile"] = {"profile": result_service.PROFILE, "sources": ["network", "solver", "sweep"],
            "explicit_historical_revision": True, "pinned_reads": True, "source_mutation": False,
            "catalog_page_size": 25, "sample_page_size": 201, "condition_page_size": 32,
            "max_comparison_series": 8, "frequency_policy": "exact_only", "automatic_interpolation": False,
            "export_formats": ["touchstone", "csv", "hdf5", "source"], "physical_validation": False}
        from rfad.adapters.network_backend import installation_metadata as network_engine_metadata
        from rfad.adapters.network_hdf5 import installation_metadata as hdf5_metadata
        result["network_profile"] = {"profile": network_service.PROFILE, "ports": network_service.MAX_NETWORK_PORTS, "samples": 1001,
                                     "import_bytes": network_service.MAX_IMPORT_BYTES, "preview_required": True,
                                     "formats": ["touchstone", "csv", "hdf5"], "engine": network_engine_metadata(),
                                     "hdf5": hdf5_metadata(), "assessment": "rfad.target-assessment/0.1",
                                     "automatic_interpolation": False, "physical_validation": False}
        result["precision_profile"] = {"profile": precision_service.PROFILE, "preview_required": True, "atomic_apply": True,
                                       "operations": list(precision_service.OPERATIONS), "limits": precision_service.LIMITS,
                                       "planar_engine": precision_service.installation_metadata(), "geometry_solver_supported": True,
                                       "sketch_solver": precision_service.SKETCH_SOLVER}
        result["object_name_profile"] = {"profile": "rfad.object-name/0.1", "project_schema": SCHEMA_VERSION,
                                         "maximum_characters": 256, "legacy_names_persisted_on_read": False,
                                         "rename_method": "editor.apply", "automatic_names": ["board", "geometry", "template_objects"]}
        result["physical_setup_profile"] = {"profile": physical_setup_service.PROFILE, "step_preview_requires_cad": True,
                                           "step_geometry": "single_mm_solid", "em_supported": True,
                                           "em_part_kinds": ["dielectric_case", "isolated_pec_box", "grounded_pec_box"],
                                           "em_surface_kinds": sorted(physical_setup_service.EM_SURFACE_KINDS)}
        result["design_rules_profile"] = {"profile": design_rule_service.PROFILE, "source": "draft_revision",
                                          "report": "rfad.design-checks/0.1", "manufacturing_verified": False}
        result["methods"].update({name: {"status": "implemented", "extension_profile": target_editor.PROFILE}
                                  for name in ("target.editor.get", "target.editor.apply")})
        result["target_editor_profile"] = {"profile": target_editor.PROFILE, "source": "draft_revision",
                                           "partial_edits": True, "preserves_sources": True, "evaluation_supported": False}
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.template-candidate/0.2"}
                                  for name in sorted(TEMPLATE_READS | {"template.apply"})})
        result["methods"]["template.synthesize"]["api_id"] = "API-007"
        result["template_profile"] = {"profile": "rfad.template-candidate/0.2", "modes": ["explicit_geometry", "initial_estimate"],
                                      "preview_required": True, "atomic_apply": True, "source_copies_in_project": True,
                                      "geometry_generator": True, "seed_synthesizer": True,
                                      "seed_scope": "G001: ideal free-space quarter-wave or source-scoped nWP008 at 2.45 GHz; no RF performance solution",
                                      "physics_validated": False, "measurement_validated": False}
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.editor/0.1"} for name in ("editor.get", "editor.apply", "project.undo", "project.redo")})
        result["editor_profile"] = {"profile": "rfad.editor/0.1", "source": "draft_revision", "history_limit": 128, "history_persistent": True, "full_document_returned": False, "max_dto_bytes": 61440}
        result["methods"].update({name: {"status": "implemented", "extension_profile": "rfad.canvas/0.1"} for name in ("canvas.get", "canvas.apply", "canvas.route.review")})
        result["canvas_profile"] = {"profile": "rfad.canvas/0.1", "source": "draft_revision", "unit": "mm", "angle_unit": "deg", "operations": ["create_board", "create_circular_board", "create_layer", "create_dielectric_layer", "create_line", "create_route", "create_arc", "create_polygon", "create_pad", "create_via", "translate", "move_endpoint", "remove"], "full_document_returned": False, "max_dto_bytes": 61440}
        result["edit_view_transport"] = {"profile": edit_view_contract.PROFILE, "max_dto_bytes": MAX_SELECTION_RESULT_BYTES}
        result["edit_view_pages"] = {"profile": edit_view_pages.PROFILE, "max_dto_bytes": edit_view_pages.MAX_PAGE_BYTES,
                                      "max_rows": edit_view_pages.MAX_ROWS}
        result["methods"].update({name: {"status": "implemented", "extension_profile": edit_view_pages.PROFILE}
                                  for name in ("editor.page", "canvas.page")})
        result["project_profile"]["geometry_kinds"] = ["line_path", "arc_path", "planar_region", "pad", "via"]
        result["methods"]["cad.latest"] = {"status": "implemented", "extension_profile": "rfad.cad-view/0.1"}
        result["methods"].update({name: {"status": "implemented", "api_id": api_id, "extension_profile": "rfad.step.mechanical/0.1"} for name, api_id in (("geometry.build", "API-008"), ("export.preview", "API-023"), ("export.build", "API-024"))})
        result["cad_profile"] = {"profile": "rfad.step.mechanical/0.1", "runtime_configured": service.cad.runtime is not None,
            "source": "immutable_snapshot", "native_slots": 1, "execution": "separate_host_process",
            "step_schema": "AP242", "result_status": "generated_unverified", "kernel_independent": False,
            "manufacturing_verified": False, "physics_verified": False, "resume_supported": False,
            "max_file_bytes": 67108864, "max_package_bytes": 134217728}
        result["methods"].update({name: {"status": "implemented", "extension_profile": exchange_contract.PROFILE}
                                  for name in exchange_contract.READS})
        result["methods"]["export.verify"] = {"status": "implemented", "api_id": "API-025", "extension_profile": exchange_contract.PROFILE}
        result["exchange_profile"] = {"profile": exchange_contract.PROFILE, "runtime_configured": service.exchange.runtime is not None,
            "source": "immutable_snapshot", "formats": ["pdf", "svg", "dxf", *exchange_contract.PCB_PROFILES.values()], "preview_required": True,
            "native_slots": 1, "max_file_bytes": exchange_contract.MAX_FILE_BYTES,
            "max_package_bytes": exchange_contract.MAX_PACKAGE_BYTES, "max_files": exchange_contract.MAX_FILES,
            "pcb_max_files": exchange_contract.MAX_PCB_FILES, "pcb_profiles": dict(exchange_contract.PCB_PROFILES),
            "manufacturing_verified": False, "physics_verified": False}
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
        result["solver_profile"]["profiles"] = ["rfad.openems.rect-waveguide/0.1", "rfad.openems.pcb-single-port/0.1",
                                                  "rfad.openems.reference-benchmark/0.1", "rfad.openems.pcb-multiport/0.1"]
        result["solver_profile"]["profile_scopes"] = {
            "rfad.openems.rect-waveguide/0.1": "empty_reference_project_only",
            "rfad.openems.pcb-single-port/0.1": "user_pcb_single_port_computed_unvalidated",
            "rfad.openems.pcb-multiport/0.1": "user_pcb_multiport_computed_unvalidated",
            "rfad.openems.reference-benchmark/0.1": "empty_project_fixed_synthetic_reference_only",
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


def _network_source_paths(message):
    """! @brief 명시 원문 필드별로 기존 파일/청크 상한의 base64 전송만 허용한다."""
    result = {}
    requests = enumerate(message) if type(message) is list else [(None, message)]
    for index, request in requests:
        if type(request) is not dict:
            continue
        method = request.get("method")
        params = request.get("params")
        data = params.get("input") if type(params) is dict else None
        if type(data) is not dict:
            continue
        prefix = (() if index is None else (index,)) + ("params", "input")
        if method == "pcb.import.chunk":
            result[prefix + ("content_base64",)] = pcb_import_service.CHUNK_BYTES
        elif method == "archive.receive.chunk":
            result[prefix + ("content_base64",)] = archive_receiver.CHUNK_BYTES
        elif method == "measurement.attachment.add":
            result[prefix + ("content_base64",)] = measurement_contract.MAX_ATTACHMENT_BYTES
        elif method in ("network.preview", "network.apply") and data.get("operation") == "import":
            result[prefix + ("parameters", "source_base64")] = network_service.MAX_IMPORT_BYTES
        elif method in ("measurement.preview", "measurement.apply") and data.get("operation") == "import_record":
            result[prefix + ("parameters", "network", "source_base64")] = network_service.MAX_IMPORT_BYTES
    return result


def _validate_tree(value: object, depth: int = 0, path=(), source_paths=None) -> None:
    """! @brief 깊이, 문자열과 부동소수점 입력의 경계를 검사한다."""
    if depth > MAX_DEPTH:
        raise ValueError("JSON nesting limit exceeded")
    if isinstance(value, str):
        source_limit = None if source_paths is None else source_paths.get(path)
        limit = ((source_limit + 2) // 3) * 4 if source_limit is not None else MAX_STRING_BYTES
        if len(value.encode("utf-8")) > limit:
            raise ValueError("String limit exceeded")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite number")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_tree(key, depth + 1)
            _validate_tree(item, depth + 1, path + (key,), source_paths)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_tree(item, depth + 1, path + (index,), source_paths)


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
    if service is not None and method in PROJECT_MUTATIONS | archive_receiver.READS | archive_export_service.READS | handoff_service.READS | measurement_service.READS | pcb_import_service.READS | pcb_exchange_service.READS | exchange_contract.READS | PCB_SELECTION_READS | STUDY_READS | TEMPLATE_READS | design_rule_service.READS | physical_setup_service.READS | precision_service.READS | smart_dimension_service.READS | sketch_service.READS | network_service.READS | design_sweep_service.READS | result_service.READS | large_results.READS | rf_validation_records.READS | sweep_selection.READS | {handoff_evidence.METHOD, project_evidence.METHOD, solver_preview.METHOD, solver_conditions_service.READ, solver_evidence.METHOD, project_activity.METHOD, "target.editor.get", "job.status", "editor.get", "canvas.get", "canvas.route.review", "editor.page", "canvas.page", "cad.latest", "result.open", "solver.latest", "solver.samples", "solver.radiation"}:
        if notification and method in PROJECT_MUTATIONS | archive_receiver.READS:
            return None
        try:
            params = request.get("params")
            if method in archive_receiver.READS:
                result = archive_receiver.read(service, method, params)
            elif method in archive_export_service.READS:
                result = archive_export_service.read(service, method, params)
            elif method == handoff_evidence.METHOD:
                result = handoff_evidence.read(service, params)
            elif method in handoff_service.READS:
                result = handoff_service.read(service, method, params)
            elif method in measurement_service.READS:
                result = measurement_service.read(service.host_calculation_context, method, params)
            elif method in pcb_import_service.READS:
                result = pcb_import_service.read(service, method, params)
            elif method in pcb_exchange_service.READS:
                result = pcb_exchange_service.read(service, method, params)
            elif method in exchange_contract.READS:
                result = exchange_service.read(service, method, params)
            elif method in sweep_selection.READS:
                result = sweep_selection.read(service, method, params)
            elif method in rf_validation_records.READS:
                result = rf_validation_records.read(service, method, params)
            elif method in result_service.READS:
                result = result_service.read(service, method, params)
            elif method in large_results.READS:
                result = large_results.read(service, method, params)
            elif method in design_sweep_service.READS:
                result = design_sweep_service.read(service.host_calculation_context, method, params)
            elif method in network_service.READS:
                result = network_service.read(service.host_calculation_context, method, params)
            elif method in precision_service.READS:
                result = precision_service.read(service, method, params)
            elif method in smart_dimension_service.READS:
                result = smart_dimension_service.read(service, method, params)
            elif method in sketch_service.READS:
                result = sketch_service.read(service, method, params)
            elif method in physical_setup_service.READS:
                result = service.physical_setup.read(method, params)
            elif method in design_rule_service.READS:
                result = design_rule_service.read(service, method, params)
            elif method == project_evidence.METHOD:
                result = project_evidence.read(service, params)
            elif method == solver_conditions_service.READ:
                result = solver_conditions_service.read(service, params)
            elif method == project_activity.METHOD:
                result = project_activity.read(service, params)
            elif method == solver_evidence.METHOD:
                result = solver_evidence.read(service, params)
            elif method == solver_preview.METHOD:
                result = solver_preview.read(service, params)
            elif method == "target.editor.get":
                result = target_editor.read(service, params)
            elif method in TEMPLATE_READS:
                result = service.templates.query(method, params)
            elif method in STUDY_READS:
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
            elif method == "canvas.route.review":
                from rfad.application.interactive_route import review
                result = review(service, params)
            elif method == "canvas.get":
                result = service.canvas_state(params)
            elif method in ("editor.page", "canvas.page"):
                result = service.edit_view_pages.read(service, params, canvas=method == "canvas.page")
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
        _validate_tree(message, source_paths=_network_source_paths(message))
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
