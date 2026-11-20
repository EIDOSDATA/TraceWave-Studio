"""! @brief 실제 봉인 필드의 읽기 전용 단면 조회를 반복해 RPC 시간과 응답 식별자를 기록한다."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame


def measure(workspace, identity):
    """! @brief 격리한 작업 영역에서 실제 원본을 고정하고 단면을 열 번 변경한다."""
    calls = []
    with ProjectService(workspace, auto_run=False) as service:
        state = service.journal.read()
        record = state["solver_results"][identity]
        source = {"kind": "solver", "artifact_id": identity}
        context = {"project_id": record["project_id"]}

        def invoke(method, values):
            """! @brief 동일 공개 RPC의 응답 시간과 바이트를 기록한다."""
            frame = canonical_bytes({"id": 1, "jsonrpc": "2.0", "method": method, "params": {
                "contract_version": "rfad.api/2.0", "context": context,
                "input": {"source": source, **values}}})
            started = time.perf_counter_ns()
            response = handle_frame(frame, service=service)
            elapsed = (time.perf_counter_ns() - started) / 1e6
            if "error" in response:
                raise ValueError(response["error"])
            payload = canonical_bytes(response["result"])
            calls.append({"method": method, "ms": elapsed, "response_bytes": len(payload),
                          "response_sha256": hashlib.sha256(payload).hexdigest()})
            return response["result"]

        initial = invoke("result.describe", {})
        if any(initial["states"][name] != "unknown" for name in ("manufacturing", "measurement")):
            raise ValueError("기록된 실제 시험 원본의 미정 조건이 예측과 다릅니다.")
        pin = initial["pin"]
        description = invoke("result.field.describe", {"pin": pin})
        monitors = description["monitors"]
        if len(monitors) != 3 or any(len(monitor["frequency_hz"]) < 2 for monitor in monitors):
            raise ValueError("세 실제 필드 모니터와 두 개 이상 주파수가 필요합니다.")
        for step in range(10):
            axis = step % 3
            monitor = monitors[axis]
            component = monitor["components"][axis]
            u_axis, v_axis = (index for index in range(3) if index != axis)
            shape = component["shape"]
            payload = invoke("result.field.page", {"pin": pin, "monitor_id": monitor["monitor_id"],
                "component": component["component"], "frequency_index": step % len(monitor["frequency_hz"]),
                "plane": {"normal_axis": "xyz"[axis], "index": (shape[axis] // 2 + step) % shape[axis]},
                "roi": {"u_start": 0, "v_start": 0, "u_count": min(32, shape[u_axis]),
                        "v_count": min(32, shape[v_axis])}, "stride": 1})
            if payload["pin"] != pin or payload["physics_validated"]:
                raise ValueError("필드 조회의 고정 식별자 또는 검증 상태가 달라졌습니다.")
        if service.journal.read() != state:
            raise ValueError("읽기 전용 계측 중 작업 이력이 바뀌었습니다.")
        return {"source": source, "pin": pin, "raw_artifacts": [item["artifact"] for item in record["raw_files"]
                if "pcb_loss_" in item["role"]], "changes": 10, "calls": calls}


def main():
    """! @brief 동일한 실제 결과의 새 보고서만 작성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("artifact")
    parser.add_argument("output", type=Path)
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.repetitions <= 20:
        parser.error("새 보고서 경로와 1~20개 반복만 허용합니다.")
    samples = [measure(args.workspace, args.artifact) for _ in range(args.repetitions)]
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(samples, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
