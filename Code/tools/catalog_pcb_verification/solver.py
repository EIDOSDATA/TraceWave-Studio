"""! @brief 선택 PCB의 공개 해석 수명과 봉인 결과 복원을 검증한다.

@details 물성이나 수치 설정을 보정하지 않는다. 실제 준비와 실행은 호출자가
명시적으로 구성한 서비스에 맡기며 계산 완료와 물리 검증 합격을 구분한다.
"""

from copy import deepcopy

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import PROFILE, validate_pcb_plan, validate_preparation, validate_result
from rfad.application.solver import RUNTIME_PROFILE

from .common import call, read_json_artifact, require, wait


def _read_plan(service, reference, identifier):
    """! @brief 공개 계획 참조의 ID와 canonical 해시를 실제 봉인 파일과 대조한다."""
    plan = read_json_artifact(service, reference["artifact"])
    require(plan[identifier] == reference[identifier] and canonical_hash(plan) == reference["content_hash"],
            "해석 계획의 ID 또는 canonical 해시가 봉인 참조와 다릅니다.")
    return plan


def _check_runtime(observed, expected):
    """! @brief 실제 worker의 소스와 설치 식별 및 Qt 부재를 확인한다."""
    require(observed.get("qt_found") is False
            and observed.get("manifest_sha256") == expected["manifest_sha256"]
            and observed.get("code_files") == expected["code_files"],
            "해석 worker의 소스/설치 식별 또는 Qt 조건이 다릅니다.")


def _check_result(result, plan, prepared_plan, preparation):
    """! @brief 결과의 물성 소비와 원시 입력이 동일한 봉인 계획을 따르는지 확인한다."""
    validate_result(plan, result, prepared_plan)
    provenance = result["provenance"]
    require(provenance["analysis_plan"] == plan and provenance["prepared_plan"] == prepared_plan
            and provenance["preparation"] == preparation,
            "해석 결과의 원본 또는 준비 출처가 변경되었습니다.")
    _check_runtime(provenance["runtime"], plan["runtime_identity"])
    manifest = result["raw_manifest"]
    require(provenance["raw_manifest"] == manifest and manifest.get("complete") is True
            and manifest.get("analysis_plan_hash") == canonical_hash(plan)
            and manifest.get("prepared_plan_hash") == canonical_hash(prepared_plan),
            "해석 원시 자료가 동일한 계획의 완료 결과가 아닙니다.")
    native = next(item for item in preparation["files"] if item["role"] == "native_input")
    raw_input = next(item for item in manifest["files"] if item["role"] == "raw/pcb.xml")
    require(raw_input["sha256"] == native["sha256"] and raw_input["bytes"] == native["bytes"]
            and manifest["execution"]["native_input_sha256"] == native["sha256"],
            "해석에 소비한 XML이 준비한 PCB와 다릅니다.")


def _view(service, context, artifact_id, snapshot):
    """! @brief 공개 결과와 차트를 읽고 모든 반환 파일의 저장 바이트 봉인을 검사한다."""
    view = call(service, "result.open", {"artifact_id": artifact_id}, context)
    chart = call(service, "solver.samples", {"artifact_id": artifact_id}, context)
    require(chart["snapshot"] == snapshot, "해석 차트의 원본 스냅샷이 다릅니다.")
    for item in view["files"]:
        descriptor = {key: item[key] for key in ("uri", "sha256", "bytes")}
        service.journal.read_artifact(descriptor)
    return view, chart


def verify_solver(service, context, snapshot, settings):
    """! @brief 같은 선택 PCB를 준비/계산/독립 후처리하고 재열기 비교 증거를 반환한다."""
    original = read_json_artifact(service, snapshot["artifact"])
    requested_settings = deepcopy(settings)
    require(canonical_hash(original) == snapshot["content_hash"], "해석 원본 스냅샷 해시가 다릅니다.")
    planned, _ = wait(service, call(service, "solver.plan", {
        "snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
        "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": requested_settings,
    }, context, mutation=True))
    plan = _read_plan(service, planned["analysis_plan"], "plan_id")
    validate_pcb_plan(plan)
    require(plan["snapshot"] == snapshot and plan["source_semantics"] == original
            and plan["case"]["settings"] == requested_settings,
            "해석 계획의 스냅샷/선택 출처/명시 설정이 원본과 다릅니다.")
    prepared, prepare_status = wait(service, call(service, "solver.prepare", {
        "analysis_plan": {key: planned["analysis_plan"][key] for key in ("plan_id", "content_hash")},
        "budget": {"timeout_seconds": 120},
    }, context, mutation=True))
    prepared_plan = _read_plan(service, prepared["prepared_plan"], "prepared_plan_id")
    preparation = read_json_artifact(service, prepared["preparation_artifact"])
    require(prepared_plan["analysis_plan"] == planned["analysis_plan"] and prepared_plan["snapshot"] == snapshot
            and prepared_plan["runtime_identity"] == plan["runtime_identity"]
            and prepared_plan["preparation_artifact"] == prepared["preparation_artifact"],
            "준비 계획이 원본 계획/스냅샷/worker를 보존하지 않았습니다.")
    validate_preparation(plan, preparation)
    _check_runtime(preparation["runtime_identity"], plan["runtime_identity"])
    task_plan = {"kind": "em_analysis", "prepared_plan": {
        key: prepared["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")},
        "execution_mode": "solve_and_postprocess"}
    solved, solve_status = wait(service, call(service, "job.submit", {
        "task_plan": task_plan, "budget": {"timeout_seconds": 120},
    }, context, mutation=True))
    result = read_json_artifact(service, solved["normalized_result"])
    _check_result(result, plan, prepared_plan, preparation)
    view, chart = _view(service, context, solved["artifact_id"], snapshot)
    repeated, repeat_status = wait(service, call(service, "job.submit", {
        "task_plan": {**task_plan, "execution_mode": "postprocess_only", "raw_result_id": solved["artifact_id"]},
        "budget": {"timeout_seconds": 120},
    }, context, mutation=True))
    repeated_result = read_json_artifact(service, repeated["normalized_result"])
    _check_result(repeated_result, plan, prepared_plan, preparation)
    require(result["samples"] == repeated_result["samples"] and result["raw_manifest"] == repeated_result["raw_manifest"],
            "독립 후처리에서 원시 자료 또는 해석 표본이 변경되었습니다.")
    repeated_view, repeated_chart = _view(service, context, repeated["artifact_id"], snapshot)
    require(chart["samples"] == repeated_chart["samples"], "독립 후처리 차트가 원래 결과와 다릅니다.")
    latest = call(service, "solver.latest", {}, context)
    require(latest["result"]["artifact_id"] == repeated["artifact_id"], "최근 결과가 마지막 완료 후처리와 다릅니다.")
    require(read_json_artifact(service, snapshot["artifact"]) == original and settings == requested_settings,
            "해석 중 원본 스냅샷 또는 명시 설정이 변경되었습니다.")
    return {
        "snapshot": deepcopy(snapshot), "analysis_plan": planned["analysis_plan"], "prepared_plan": prepared["prepared_plan"],
        "preparation_artifact": prepared["preparation_artifact"], "artifact_id": solved["artifact_id"],
        "result": solved["normalized_result"], "postprocess_artifact_id": repeated["artifact_id"],
        "postprocess_result": repeated["normalized_result"], "assessment": result["assessment"],
        "native_statistics": result["native_statistics"], "mesh_statistics": result["mesh_statistics"],
        "termination": result["termination"], "sample_count": len(chart["samples"]),
        "consumed_materials": plan["case"]["materials"], "postprocess_samples_identical": True,
        "source_semantics_preserved": True, "qt_found": False,
        "states": {name: [event["state"] for event in status["events"]]
                   for name, status in (("prepare", prepare_status), ("analysis", solve_status), ("postprocess_only", repeat_status))},
        "restoration": {"view": view, "chart": chart, "latest": latest,
                        "postprocess_view": repeated_view, "postprocess_chart": repeated_chart,
                        "result_hash": canonical_hash(result), "postprocess_result_hash": canonical_hash(repeated_result)},
    }


def restore_solver(service, context, snapshot, expected):
    """! @brief 카탈로그와 해석기 없이 저장 결과/출처/원시 자료/차트를 동일하게 복원한다."""
    require(expected["snapshot"] == snapshot, "재열기할 해석의 스냅샷이 다릅니다.")
    original = read_json_artifact(service, snapshot["artifact"])
    require(canonical_hash(original) == snapshot["content_hash"], "재열기 원본 스냅샷 해시가 다릅니다.")
    plan = _read_plan(service, expected["analysis_plan"], "plan_id")
    prepared_plan = _read_plan(service, expected["prepared_plan"], "prepared_plan_id")
    preparation = read_json_artifact(service, expected["preparation_artifact"])
    require(plan["source_semantics"] == original and plan["snapshot"] == snapshot,
            "재열기한 계획이 카탈로그 선택 출처와 원본을 보존하지 않았습니다.")
    validate_pcb_plan(plan)
    validate_preparation(plan, preparation)
    for prefix, artifact_key, result_key in (("", "artifact_id", "result"),
                                            ("postprocess_", "postprocess_artifact_id", "postprocess_result")):
        result = read_json_artifact(service, expected[result_key])
        _check_result(result, plan, prepared_plan, preparation)
        require(canonical_hash(result) == expected["restoration"][prefix + "result_hash"],
                "재시작 후 정규화 결과 또는 전체 출처가 변경되었습니다.")
        view, chart = _view(service, context, expected[artifact_key], snapshot)
        require(view == expected["restoration"][prefix + "view"]
                and chart == expected["restoration"][prefix + "chart"],
                "해석기 없는 재시작 후 공개 결과 또는 차트가 변경되었습니다.")
    require(call(service, "solver.latest", {}, context) == expected["restoration"]["latest"],
            "해석기 없는 재시작 후 최근 결과가 변경되었습니다.")
