"""! @brief 명시적 도파관 참조 해석의 불변 계획과 준비 참조를 정의한다.

@details 사용자 안테나를 이 참조 형상으로 대체하지 않는다. 이 모듈에는 native
import, 파일 IO, solver 실행 또는 미정 물성의 추론이 없으며 실제 준비 통계와
결과는 별도 worker artifact에 기록한다.
"""

from copy import deepcopy
import math
from uuid import UUID, uuid4

from rfad.application.canonical import (
    CANONICAL_VERSION,
    CanonicalEncodingError,
    canonical_bytes,
    canonical_hash,
)
from rfad.domain.errors import ProjectError
from rfad.domain.project import READABLE_SCHEMA_VERSIONS, validate_project


PROFILE = "rfad.openems.rect-waveguide/0.1"
RUNTIME_PROFILE = "openems-wsl-reference/0.1"
PLAN_SCHEMA = "rfad.analysis-plan/0.1"
PREPARED_PLAN_SCHEMA = "rfad.prepared-plan/0.1"
CASE_VERSION = "rfad.reference.rect-waveguide/0.1"
SUPPORTED_GRIDS_MM = (1.0, 0.75)
MAX_WALL_TIME_SECONDS = 300.0
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
_SOURCE_METADATA = {
    "schema_version", "project_id", "revision_id", "parent_revision_ids", "metadata", "frames",
}


def _fail(code: str, message: str, field: str) -> None:
    """! @brief 입력 위치를 포함한 구조화된 접수 차단 사유를 반환한다."""
    raise ProjectError(code, message, details={"field_path": field})


def _json(value: object, field: str, limit: int = 256 * 1024) -> None:
    """! @brief 순환, 비유한 값, 비JSON 타입과 과도한 입력을 차단한다."""
    try:
        encoded = canonical_bytes(value)
    except (CanonicalEncodingError, ValueError, TypeError, RecursionError):
        _fail("E_SCHEMA", "계획에는 유효한 JSON 값만 사용할 수 있습니다.", field)
    if len(encoded) > limit:
        _fail("E_RESOURCE", "계획 입력의 허용 크기를 초과했습니다.", field)


def _uuid(value: object, field: str) -> None:
    """! @brief 정규 UUID 식별자를 검사한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        _fail("E_SCHEMA", "식별자는 정규 UUID여야 합니다.", field)


def _hash(value: object, field: str) -> None:
    """! @brief 소문자 SHA256 문자열을 검사한다."""
    if type(value) is not str or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        _fail("E_SCHEMA", "해시는 소문자 SHA256 문자열이어야 합니다.", field)


def _artifact(value: object, field: str) -> None:
    """! @brief 파일 접근 없이 상대 artifact 참조의 형식과 크기를 검사한다."""
    if type(value) is not dict or set(value) != {"uri", "sha256", "bytes"}:
        _fail("E_SCHEMA", "완전한 artifact 참조가 필요합니다.", field)
    uri = value["uri"]
    if type(uri) is not str or not uri or len(uri) > 1024 or "\\" in uri or ":" in uri or "\x00" in uri:
        _fail("E_SCHEMA", "artifact URI는 저장소 상대 경로여야 합니다.", field + ".uri")
    if any(part in ("", ".", "..") for part in uri.split("/")):
        _fail("E_SCHEMA", "artifact URI에 빈 경로나 상위 경로를 사용할 수 없습니다.", field + ".uri")
    _hash(value["sha256"], field + ".sha256")
    if type(value["bytes"]) is not int or not 0 < value["bytes"] <= MAX_ARTIFACT_BYTES:
        _fail("E_RESOURCE", "artifact 크기는 0보다 크고 64 MiB 이하여야 합니다.", field + ".bytes")


def _snapshot(snapshot: object) -> None:
    """! @brief 축약 참조를 허용하지 않고 봉인된 SnapshotRef 전체를 검사한다."""
    required = {
        "snapshot_id", "project_id", "revision_id", "schema_version", "canonical_version",
        "content_hash", "sealed_at", "description", "validation_state", "artifact",
    }
    if type(snapshot) is not dict or set(snapshot) != required:
        _fail("E_SCHEMA", "봉인된 전체 SnapshotRef가 필요합니다.", "snapshot")
    _json(snapshot, "snapshot", 16 * 1024)
    for key in ("snapshot_id", "project_id", "revision_id"):
        _uuid(snapshot[key], "snapshot." + key)
    if len({snapshot[key] for key in ("snapshot_id", "project_id", "revision_id")}) != 3:
        _fail("E_SCHEMA", "스냅샷/프로젝트/개정 식별자는 서로 달라야 합니다.", "snapshot.snapshot_id")
    if snapshot["schema_version"] not in READABLE_SCHEMA_VERSIONS:
        _fail("E_VERSION", "지원하지 않는 프로젝트 스키마입니다.", "snapshot.schema_version")
    if snapshot["canonical_version"] != CANONICAL_VERSION:
        _fail("E_VERSION", "지원하지 않는 정규 직렬화 버전입니다.", "snapshot.canonical_version")
    _hash(snapshot["content_hash"], "snapshot.content_hash")
    if type(snapshot["sealed_at"]) not in (int, float) or not math.isfinite(snapshot["sealed_at"]) or snapshot["sealed_at"] <= 0:
        _fail("E_SCHEMA", "스냅샷 봉인 시각은 양의 epoch 초여야 합니다.", "snapshot.sealed_at")
    if type(snapshot["description"]) is not str or type(snapshot["validation_state"]) is not str or not snapshot["validation_state"]:
        _fail("E_SCHEMA", "스냅샷 설명과 검증 상태가 필요합니다.", "snapshot")
    _artifact(snapshot["artifact"], "snapshot.artifact")


def _reference_source(document: dict, snapshot: dict) -> None:
    """! @brief 빈 참조 프로젝트만 허용하고 실제 설계를 조용히 무시하지 않는다."""
    validate_project(document)
    _snapshot(snapshot)
    for key in ("project_id", "revision_id", "schema_version"):
        if snapshot[key] != document[key]:
            _fail("E_CONFLICT", "계획 원본과 스냅샷의 식별자 또는 버전이 다릅니다.", "snapshot." + key)
    if snapshot["content_hash"] != canonical_hash(document):
        _fail("E_HASH", "봉인된 스냅샷 해시와 계획 원본이 다릅니다.", "snapshot.content_hash")
    for field, value in document.items():
        if field in _SOURCE_METADATA:
            continue
        if field == "board":
            empty = value is None
        else:
            empty = value == {} or value == []
        if not empty:
            _fail("E_UNSUPPORTED", "도파관 참조 해석에는 설계 데이터가 없는 별도 프로젝트가 필요합니다.", field)
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for role, frame in document["frames"].items():
        if frame["rotation"] != identity or frame["translation_si"] != [0.0, 0.0, 0.0] or frame["handedness"] != "right":
            _fail("E_UNSUPPORTED", "참조 해석은 항등 오른손 좌표계만 사용합니다.", "frames." + role)


def _runtime(identity: object) -> None:
    """! @brief host가 관측한 runtime 증거를 추정 없이 보존할 수 있는지 확인한다."""
    required = {"runtime_profile", "manifest_sha256", "code_files", "transport"}
    if type(identity) is not dict or set(identity) != required:
        _fail("E_SCHEMA", "host에서 확인한 runtime 식별 정보가 필요합니다.", "runtime_identity")
    _json(identity, "runtime_identity", 64 * 1024)
    if identity["runtime_profile"] != RUNTIME_PROFILE:
        _fail("E_VERSION", "해석 runtime profile이 일치하지 않습니다.", "runtime_identity.runtime_profile")
    _hash(identity["manifest_sha256"], "runtime_identity.manifest_sha256")
    files = identity["code_files"]
    if type(files) is not list or not 1 <= len(files) <= 192:
        _fail("E_RESOURCE", "runtime 소스 목록은 1개 이상 192개 이하여야 합니다.", "runtime_identity.code_files")
    seen = set()
    for index, item in enumerate(files):
        field = f"runtime_identity.code_files[{index}]"
        if type(item) is not dict or set(item) != {"path", "sha256", "bytes"}:
            _fail("E_SCHEMA", "runtime 소스의 경로/해시/크기가 필요합니다.", field)
        _artifact({"uri": item["path"], "sha256": item["sha256"], "bytes": item["bytes"]}, field)
        if not item["path"].endswith(".py") or item["path"] in seen:
            _fail("E_SCHEMA", "runtime 소스는 중복 없는 Python 상대 경로여야 합니다.", field + ".path")
        seen.add(item["path"])
    if type(identity["transport"]) is not dict or not identity["transport"]:
        _fail("E_SCHEMA", "WSL runtime 소유 설정이 필요합니다.", "runtime_identity.transport")


def case_spec(grid_mm: float) -> dict:
    """! @brief 사용자 물성을 대체하지 않는 고정 참조 사례의 명시적 조건을 반환한다."""
    if type(grid_mm) not in (int, float) or grid_mm not in SUPPORTED_GRIDS_MM:
        _fail("E_UNSUPPORTED", "참조 해석 격자는 1.0 또는 0.75 mm를 명시해야 합니다.", "grid_mm")
    return {
        "case_id": CASE_VERSION,
        "source": "explicit_reference_case",
        "native_length_unit": "mm",
        "delta_unit_m": 0.001,
        "dimensions_mm": [20.0, 10.0, 80.0],
        "medium": {"kind": "vacuum", "epsilon_r": 1.0, "mu_r": 1.0, "electric_conductivity_s_per_m": 0.0},
        "boundary_conditions": ["PEC", "PEC", "PEC", "PEC", "PML_8", "PML_8"],
        "mesh": {"grid_mm": float(grid_mm), "critical_z_mm": [0.0, 10.0, 15.0, 65.0, 70.0, 80.0], "method": "segment_linspace_ceil"},
        "frequency_hz": {"start": 9.5e9, "stop": 10.5e9, "count": 31},
        "excitation": {"kind": "gaussian", "center_hz": 1.0e10, "width_hz": 2.0e9},
        "ports": [
            {"number": 1, "start_mm": [0.0, 0.0, 10.0], "stop_mm": [20.0, 10.0, 15.0], "direction": "z", "mode": "TE10", "excite": 1},
            {"number": 2, "start_mm": [0.0, 0.0, 70.0], "stop_mm": [20.0, 10.0, 65.0], "direction": "z", "mode": "TE10", "excite": 0},
        ],
        "stop_criteria": {"max_timesteps": 20000, "energy_decay": 1e-7, "simulation_time_limit_s": None, "exact_end_criteria": True},
        "num_threads": 2,
    }


def normalization_contract() -> dict:
    """! @brief pulse Fourier 채널의 비율만 사용하며 절대 power/gain으로 승격하지 않는다."""
    return {
        "schema": "rfad.normalization.rect-waveguide/0.1",
        "fourier_convention": "exp(-j*2*pi*f*t)",
        "native_fourier_scale": "2*dt*sum(value*exp(-j*2*pi*f*t))",
        "native_time_unit": "s",
        "native_voltage_unit": "V*s",
        "native_current_unit": "A*s",
        "native_amplitude": "pulse_fourier_spectrum",
        "native_to_rms_conversion": "none",
        "wave_definition": "voltage_wave_real_te10_impedance",
        "reference_impedance": "frequency_dependent_vacuum_TE10_same_at_both_ports",
        "reference_planes_mm": [15.0, 65.0],
        "reference_plane_convention": "port_stop",
        "reference_plane_shift_mm": 0.0,
        "port_2_orientation": "negative_z_into_device",
        "probe_separation_m": 0.05,
        "channels": {
            "s11": {"formula": "port1.uf_ref/port1.uf_inc", "unit": "1", "normalization": "port1_incident_voltage_wave"},
            "s21": {"formula": "port2.uf_ref/port1.uf_inc", "unit": "1", "normalization": "port1_incident_voltage_wave"},
            "port1_impedance": {"formula": "port1.uf_tot/port1.if_tot", "unit": "ohm", "normalization": "voltage_current_ratio"},
            "group_delay": {"formula": "-d(unwrap(arg(s21)))/d(2*pi*f)", "unit": "s", "normalization": "phase_derivative"},
        },
        "absolute_power_gain_efficiency": "not_evaluated",
        "evidence_scope": "reference_case_only_requires_actual_run",
    }


def _plan_payload(document: dict, snapshot_ref: dict, runtime_identity: dict, grid_mm: float) -> dict:
    """! @brief 아직 관측하지 않은 native 통계를 만들지 않고 결정적 계획 내용을 만든다."""
    _reference_source(document, snapshot_ref)
    _runtime(runtime_identity)
    case = case_spec(grid_mm)
    counts = [math.ceil(20.0 / grid_mm), math.ceil(10.0 / grid_mm)]
    z = case["mesh"]["critical_z_mm"]
    counts.append(sum(math.ceil((stop - start) / grid_mm) for start, stop in zip(z, z[1:])))
    cells = math.prod(counts)
    return {
        "schema": PLAN_SCHEMA,
        "analysis_profile": PROFILE,
        "runtime_profile": RUNTIME_PROFILE,
        "snapshot": deepcopy(snapshot_ref),
        "source_semantics": deepcopy(document),
        "runtime_identity": deepcopy(runtime_identity),
        "case": case,
        "normalization": normalization_contract(),
        "model_report": {
            "scope": "explicit_reference_case",
            "user_geometry_consumed": False,
            "user_materials_consumed": False,
            "source_project_required": "empty_reference_project",
            "material_origin": "profile_explicit_vacuum_and_PEC",
            "physical_validation_state": "not_evaluated",
            "unsupported_observables": ["antenna_radiation", "nf2ff", "gain", "efficiency", "absolute_power", "full_s_matrix"],
        },
        "resource_estimate": {
            "kind": "initial_estimate_not_actual_mesh",
            "estimated_cells_xyz": counts,
            "estimated_cell_count": cells,
            "estimated_memory_bytes": 64 * 1024 * 1024 + cells * 128,
            "memory_estimate_basis": "64_MiB_process_allowance_plus_128_bytes_per_cell_not_measured",
            "max_wall_time_seconds": MAX_WALL_TIME_SECONDS,
            "max_output_bytes": MAX_OUTPUT_BYTES,
            "max_artifact_bytes": MAX_ARTIFACT_BYTES,
            "num_threads": 2,
        },
        "outputs": ["preparation_manifest", "native_input", "raw_solver", "s_parameters", "reference_metrics", "result_metadata"],
        "assumptions": [
            "The empty project anchors a separate explicit reference case, not a user antenna simulation.",
            "Vacuum and PEC are explicit reference definitions, not inferred user material values.",
            "One excited TE10 port produces S11 and S21 only, not a complete two-port S matrix.",
            "Two grid sizes provide a regression comparison, not formal mesh convergence qualification.",
            "No IFA, radiation, NF2FF, absolute power, gain, efficiency or fabrication validation is claimed.",
        ],
        "validation_policy": {
            "profile": "reference_analytic_TE10",
            "limits": {
                "max_reflection_amplitude": 0.15,
                "max_transmission_amplitude_error": 0.08,
                "max_impedance_relative_error": 0.08,
                "max_group_delay_relative_error": 0.10,
                "max_grid_transmission_amplitude_delta": 0.03,
                "max_grid_impedance_relative_delta": 0.04,
            },
            "energy_decay_required": True,
            "timesteps_exhausted_is_converged": False,
        },
    }


def build_analysis_plan(document: dict, snapshot_ref: dict, runtime_identity: dict, grid_mm: float) -> dict:
    """! @brief 전체 봉인 참조를 묶은 새 AnalysisPlan을 만들며 원본을 변경하지 않는다.

    @param document 등록된 snapshot artifact에서 읽은 프로젝트 원본.
    @param snapshot_ref 서비스가 소유권/파일 hash를 확인한 전체 SnapshotRef.
    @param runtime_identity host가 고정한 runtime 출처와 설치 식별 정보.
    @param grid_mm 명시적으로 선택한 1.0 또는 0.75 mm 참조 격자.
    @return 자체 UUID를 가진 불변 저장 대상. canonical hash와 artifact는 host가 만든다.
    @throws ProjectError 미지원 설계/격자, 스냅샷 불일치 또는 JSON 형식 오류.
    """
    result = _plan_payload(document, snapshot_ref, runtime_identity, grid_mm)
    result["plan_id"] = str(uuid4())
    return result


def validate_reference_plan(plan: dict) -> None:
    """! @brief worker에 전달된 계획의 전체 참조와 고정 참조 조건을 재검증한다."""
    _json(plan, "analysis_plan")
    if type(plan) is not dict or plan.get("schema") != PLAN_SCHEMA:
        _fail("E_VERSION", "지원하지 않는 AnalysisPlan 스키마입니다.", "analysis_plan.schema")
    _uuid(plan.get("plan_id"), "analysis_plan.plan_id")
    if type(plan.get("source_semantics")) is not dict or type(plan.get("case")) is not dict or type(plan["case"].get("mesh")) is not dict:
        _fail("E_SCHEMA", "참조 계획에 원본과 사례/격자 조건이 필요합니다.", "analysis_plan")
    expected = _plan_payload(plan["source_semantics"], plan.get("snapshot"), plan.get("runtime_identity"), plan["case"]["mesh"].get("grid_mm"))
    expected["plan_id"] = plan["plan_id"]
    if plan["plan_id"] in {plan["snapshot"][key] for key in ("snapshot_id", "project_id", "revision_id")}:
        _fail("E_SCHEMA", "계획은 스냅샷/프로젝트/개정과 독립된 식별자가 필요합니다.", "analysis_plan.plan_id")
    if canonical_bytes(plan) != canonical_bytes(expected):
        _fail("E_UNSUPPORTED", "고정 참조 profile의 조건 또는 계획 내용을 변경할 수 없습니다.", "analysis_plan")


def make_prepared_plan(analysis_plan_ref: dict, snapshot: dict, preparation_artifact_ref: dict, runtime_identity: dict) -> dict:
    """! @brief 준비 검증을 마친 host가 독립 ID를 가진 PreparedPlan을 봉인하게 한다.

    @details 이 함수는 artifact 파일이나 native 준비 결과를 읽지 않는다. 호출자는
    실제 native input hash, 소비 보고와 mesh 검증을 먼저 완료해야 한다. AnalysisPlan에
    준비 결과를 덧쓰지 않고 두 artifact의 참조를 새 객체에 연결한다.
    """
    if type(analysis_plan_ref) is not dict or set(analysis_plan_ref) != {"plan_id", "content_hash", "artifact"}:
        _fail("E_SCHEMA", "AnalysisPlan 전체 불변 참조가 필요합니다.", "analysis_plan")
    _uuid(analysis_plan_ref["plan_id"], "analysis_plan.plan_id")
    _hash(analysis_plan_ref["content_hash"], "analysis_plan.content_hash")
    _artifact(analysis_plan_ref["artifact"], "analysis_plan.artifact")
    _snapshot(snapshot)
    _artifact(preparation_artifact_ref, "preparation_artifact")
    _runtime(runtime_identity)
    return {
        "schema": PREPARED_PLAN_SCHEMA,
        "prepared_plan_id": str(uuid4()),
        "analysis_plan": deepcopy(analysis_plan_ref),
        "snapshot": deepcopy(snapshot),
        "preparation_artifact": deepcopy(preparation_artifact_ref),
        "runtime_profile": RUNTIME_PROFILE,
        "runtime_identity": deepcopy(runtime_identity),
        "validation_state": "prepared",
    }
