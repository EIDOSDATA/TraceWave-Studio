"""! @brief 명시 케이스에서 IFA와 원호 후보를 비교하고 채택 사본을 다시 계산한다."""

import argparse
from copy import deepcopy
from pathlib import Path
from time import monotonic
from uuid import uuid4

from verify_tuning_workflow import document, run_study, candidate_results
from catalog_pcb_verification.common import VerificationError, call, wait, require, publish_report
from rfad.application.pcb_compute import limits
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from verify_tuning_adoption import adopt, files
from tuning_workflow_cases import FREQUENCIES, create_case, quantity


FINAL_GRID_MM = 0.45
IFA_FINAL_TIMESTEPS = 36000
ARC_TIMESTEPS = 28000
SOURCE = "합성 설치 검증용 명시 물성과 치수. 실제 제작, 측정 및 외함 자료 미확보."


def add_installation(service, case):
    """! @brief 실제 부품의 미정값을 보존하고 독립 시험 시나리오만 명시한다."""
    context = case["context"]

    def apply(method, data):
        """! @brief 시험 입력도 일반 개정 및 영수증 경로로 기록한다."""
        return call(service, method, {**data, "expected_revision": document(service, context)["revision_id"],
                                     "command_id": str(uuid4())}, context, mutation=True)

    material_id = str(uuid4())
    apply("project.apply_command", {"type": "material.set", "payload": {"material": {
        "id": material_id, "name": "검증용 외함 유전체", "model": "isotropic_constant",
        "epsilon_r": quantity(3.5, "1"), "tan_delta": quantity(0.01, "1"), "conductivity": quantity(0, "S/m"),
        "validity_hz": {"min": quantity(2.4, "GHz"), "max": quantity(2.4835, "GHz")},
        "source_refs": [SOURCE], "assumptions": [SOURCE]}}})

    def physical(section, changes):
        """! @brief 명시 설치 입력과 적용 사유를 기존 화면과 같은 서비스에 보낸다."""
        return apply("physical.setup.apply", {"section": section, "operation": "set", "record_id": None,
                                            "reason": SOURCE, "changes": changes, "step_token": None})

    scenario = physical("scenario", {"name": "하부 개방 합성 케이스"})["record_id"]
    part = physical("part", {"name": "1 mm 합성 케이스", "kind": "dielectric_case", "scenario_id": scenario,
        "x": "-2", "y": "-2", "z": "0", "yaw": "0", "width": "44", "height": "64", "depth": "3.5",
        "case_thickness": "1", "material_id": material_id, "visible": True, "include_in_em": True,
        "include_in_export": False})["record_id"]
    physical("activation", {"active_scenario_id": scenario})
    case["document"] = document(service, context)
    case["installed_environment_em"] = {"scenario_id": scenario, "part_id": part}
    wait(service, call(service, "project.save", {"expected_revision": case["document"]["revision_id"]},
                       context, mutation=True))


def compare_case(service, kind, report, path, compute_profile):
    """! @brief 미리 지정한 두 값과 거친 조건에서 선택한 뒤 더 작은 격자로 다시 실행한다."""
    case = create_case(service, kind)
    add_installation(service, case)
    specification = deepcopy(case["specification"])
    specification["name"] += " / 합성 외함 후보"
    axes = specification["variables"][0]["values"]
    specification["variables"][0]["values"] = axes[:2] if kind == "ifa" else axes[1:]
    if compute_profile is not None:
        specification["settings"]["compute_profile"] = compute_profile
    budget_seconds = 2 * limits(specification["settings"])["max_wall_time_seconds"] + 600
    specification["budget"].update(max_candidates=2, max_native_solves=2, wall_seconds=budget_seconds)
    specification["settings"]["radiation"]["box_clearance_mm"] = 1
    if kind == "arc":
        specification["settings"]["max_timesteps"] = ARC_TIMESTEPS
    case["specification"] = specification
    entry = {"kind": kind, "case": case, "status": "running"}
    report["cases"].append(entry)
    publish_report(path, report)
    print(kind + ": installed candidate matrix", flush=True)

    try:
        study = run_study(service, case["context"], specification, timeout=budget_seconds + 20, keep_incomplete=True)
    except VerificationError as error:
        entry.update(status="not_evaluated", initial_error=str(error))
        publish_report(path, report)
        return
    results, selected = candidate_results(service, case["context"], study)
    entry.update(study=study, results=results, selected_index=selected)
    publish_report(path, report)
    if study["view"]["state"] != "completed" or selected is None:
        entry["status"] = "not_evaluated"
        publish_report(path, report)
        return
    original_files = files(service.workspace / case["path"])
    copied = adopt(service, entry)
    entry["copy"] = copied
    publish_report(path, report)
    verify_copy(service, entry)
    if compute_profile is not None or (kind == "ifa" and entry["status"] != "computed"):
        verify_copy(service, entry, boundary=True)
    require(document(service, case["context"]) == case["document"] and files(service.workspace / case["path"]) == original_files,
            "채택과 재계산 뒤 원본 설계 또는 파일이 달라졌습니다.")
    entry["unchanged_source_file_count"] = len(original_files)
    publish_report(path, report)


def verify_copy(service, entry, *, boundary=False):
    """! @brief 채택 개정의 격자 또는 공기 경계 대조를 각각 새 연구로 봉인한다."""
    copied = entry["copy"]
    specification = deepcopy(entry["case"]["specification"])
    axis = specification["variables"][0]
    axis["values"] = [axis["values"][entry["selected_index"]]]
    settings = specification["settings"]
    budget_seconds = limits(settings)["max_wall_time_seconds"] + 400
    specification["budget"].update(max_candidates=1, max_native_solves=1, wall_seconds=budget_seconds)
    if boundary:
        prefix = "boundary"
        specification["name"] += " / 11.2 mm 공기 경계 대조"
        settings.update(air_padding_mm=11.2, mesh_policy={"kind": "graded_air", "air_cell_mm": 0.8, "growth_ratio": 1.5})
    else:
        prefix = "final"
        specification["name"] += " / 채택 사본의 최종 계산"
        settings["grid_mm"] = FINAL_GRID_MM
        if entry["kind"] == "ifa" and "compute_profile" not in settings:
            settings["max_timesteps"] = IFA_FINAL_TIMESTEPS

    print(entry["kind"] + ": selected copy, " + prefix, flush=True)
    try:
        study = run_study(service, copied["context"], specification, timeout=budget_seconds + 20, keep_incomplete=True)
    except VerificationError as error:
        entry[prefix + "_error"] = str(error)
        if not boundary:
            entry["status"] = "not_evaluated"
    else:
        results, found = candidate_results(service, copied["context"], study)
        entry.update({prefix + "_study": study, prefix + "_results": results})
        if not boundary:
            entry["status"] = "computed" if study["view"]["state"] == "completed" and found == 0 else "not_evaluated"


def run(destination, kinds, refinement_threads=None):
    """! @brief 고정 예산과 선택 기준을 먼저 기록하고 단계별 결과를 보존한다."""
    destination.mkdir(parents=True)
    path = destination / "report.json"
    runtime = SolverRuntime()
    started = monotonic()
    compute_profile = None if refinement_threads is None else {"kind": "tuning_refinement/0.1", "num_threads": refinement_threads}
    report = {"status": "running", "runtime_identity": runtime.identity, "frequency_hz": FREQUENCIES,
        "candidates_mm": {"ifa": [24, 26], "arc": [5, 5.5]}, "candidate_grid_mm": 0.5, "final_grid_mm": FINAL_GRID_MM,
        "max_timesteps": {"ifa": [50000, IFA_FINAL_TIMESTEPS if compute_profile is None else 50000],
                          "arc": [ARC_TIMESTEPS, ARC_TIMESTEPS]},
        "compute_profile": compute_profile,
        "native_solve_limit": 4 * len(kinds) if compute_profile is not None else 3 * len(kinds) + ("ifa" in kinds), "selection": "lowest_worst_valid_sample_s11_then_ordinal", "s11_limit_db": -10,
        "manufacturing": None, "measurement": None, "sma_model": None, "formal_convergence": "not_established", "cases": []}
    publish_report(path, report)
    try:
        with ProjectService(destination / "workspace", solver_runtime=runtime) as service:
            for kind in kinds:
                compare_case(service, kind, report, path, compute_profile)
        with ProjectService(destination / "workspace", auto_run=False) as service:
            for entry in report["cases"]:
                case = entry["case"]
                if "study" in entry:
                    reopened, selected = candidate_results(service, case["context"], entry["study"])
                    require(reopened == entry["results"] and selected == entry["selected_index"], "재열린 초기 표본과 선택 순번이 다릅니다.")
                if "copy" not in entry:
                    continue
                copied = entry["copy"]
                context = copied["context"]
                require(document(service, context) == copied["document"], "저장한 채택 사본이 달라졌습니다.")
                for prefix in ("final", "boundary"):
                    if prefix + "_study" in entry:
                        reopened, _ = candidate_results(service, context, entry[prefix + "_study"])
                        require(reopened == entry[prefix + "_results"], "런타임 없는 재열기의 실제 표본이 다릅니다.")
        status = "completed" if all(entry["status"] == "computed" for entry in report["cases"]) else "partial"
        report.update(status=status, reopened_without_runtime=True)
    except Exception as error:
        report.update(status="failed", error={"message": str(error), "details": getattr(error, "details", None)})
        raise
    finally:
        report["elapsed_seconds"] = monotonic() - started
        publish_report(path, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=("ifa", "arc"))
    parser.add_argument("--refinement-threads", type=int, choices=range(1, 9))
    options = parser.parse_args()
    kinds = list(dict.fromkeys(options.case)) if options.case else ("ifa", "arc")
    run(options.destination.resolve(), kinds, options.refinement_threads)
