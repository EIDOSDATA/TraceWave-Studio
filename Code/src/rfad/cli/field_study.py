"""! @brief 보존 전계에서 국부 격자 연구를 생성하거나 중단한 연구를 이어서 실행한다."""

import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError


def run(service, project, args):
    """! @brief 공개 연구 API를 사용해 매 회차 실제 작업을 기다리고 동일 주파수의 표본을 반환한다."""
    def call(method, data, *, mutation=False):
        """! @brief 공개 API의 개정과 변경 영수증 계약을 따른다."""
        params = {"contract_version": "rfad.api/2.0", "context": {"project_id": project}, "input": data}
        if mutation:
            params.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
        response = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}), service)
        if "error" in response:
            raise ValueError(response["error"]["message"] + " " + str(response["error"].get("data", "")))
        return response["result"]
    if args.resume:
        identity = args.resume
        study = call("study.get", {"study_id": identity})
        if "field_adaptive" not in study["specification"]:
            raise ValueError("전계 기반 국부 격자 연구를 선택하십시오.")
        state = study["state"]
    else:
        source = {"kind": "solver", "artifact_id": args.artifact}
        description = call("result.describe", {"source": source})
        context = call("study.context", {})
        selection = {"monitor_id": args.monitor, "component": args.component, "frequency_index": args.frequency_index,
                     "plane": {"normal_axis": args.normal, "index": args.index},
                     "roi": dict(zip(("u_start", "u_count", "v_start", "v_count"), args.roi))}
        limits = {"threshold_fraction": args.threshold, "max_rules": args.max_rules, "memory_limit_mib": args.memory_mib,
                  "max_rounds": args.rounds, "max_s11_complex_delta": args.tolerance}
        saved = call("study.create_field", {"expected_revision": context["revision_id"], "source": source, "pin": description["pin"],
                     "name": args.name, "selection": selection, "limits": limits}, mutation=True)
        identity, state = saved["study_id"], "ready"
    print("전계 연구 " + identity, file=sys.stderr, flush=True)
    if state == "ready":
        call("study.start", {"study_id": identity}, mutation=True)
    elif state in {"cancelled", "interrupted", "failed", "blocked"}:
        call("study.resume", {"study_id": identity}, mutation=True)
    while True:
        # @brief 주기 조회에서는 큰 봉인 필드와 전력 원문을 다시 읽지 않는다.
        rows = call("study.list", {})["studies"]
        state = next(row["state"] for row in rows if row["study_id"] == identity)
        if state not in {"running", "resuming", "cancel_requested"}:
            break
        time.sleep(1)
    result = call("study.get", {"study_id": identity})
    result["frequency_comparisons"] = [call("study.sample_comparison", {"study_id": identity, "right_case": case["index"]})
                                       for case in result["cases"] if "sample_evidence" in case]
    return result


def main(argv=None):
    """! @brief 연구 식별자나 새 연구의 필수 조건을 확인하고 같은 작업 영역에 원문을 보존한다."""
    parser = argparse.ArgumentParser(prog="rfad field-study")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--project", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--resume", metavar="STUDY_ID")
    group.add_argument("--artifact", metavar="SOLVER_RESULT_ID")
    parser.add_argument("--name", default="전계 기반 국부 격자 연구")
    parser.add_argument("--monitor", choices=("electric", "probe_electric"))
    parser.add_argument("--component", choices=tuple("xyz"))
    parser.add_argument("--frequency-index", type=int)
    parser.add_argument("--normal", choices=tuple("xyz"))
    parser.add_argument("--index", type=int)
    parser.add_argument("--roi", nargs=4, type=int, metavar=("U_START", "U_COUNT", "V_START", "V_COUNT"))
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--max-rules", type=int)
    parser.add_argument("--memory-mib", type=int)
    parser.add_argument("--rounds", type=int)
    parser.add_argument("--tolerance", type=float, help="공통 주파수마다 허용하는 복소 S11의 절대 차")
    args = parser.parse_args(argv)
    required = ("monitor", "component", "frequency_index", "normal", "index", "roi", "threshold", "max_rules", "memory_mib", "rounds", "tolerance")
    supplied = [getattr(args, key) is not None for key in required]
    if args.artifact and not all(supplied) or args.resume and any(supplied):
        parser.error("새 연구에는 모든 단면과 상한을 지정하고 재개에는 원래 연구 식별자를 사용하십시오.")
    from rfad.application.projects import ProjectService
    from rfad.application.solver_runtime import SolverRuntime

    try:
        with ProjectService(args.workspace, solver_runtime=SolverRuntime()) as service:
            report = run(service, args.project, args)
    except (OSError, ProjectError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return int(report["state"] != "completed")
