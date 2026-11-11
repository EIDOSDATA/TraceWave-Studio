"""! @brief 원래 FDTD 필드를 읽기만 하는 고정 독립 손실 재계산 worker다."""

import json
from pathlib import Path
import sys


def main():
    """! @brief 소유권 gate와 봉인을 확인한 뒤 형상 준비나 FDTD 없이 후처리만 수행한다."""
    stage = Path.cwd()
    gate_raw = sys.stdin.buffer.readline(65537)
    if not gate_raw.endswith(b"\n") or len(gate_raw) > 65536 or sys.argv[1:] != ["--request", "request.json"]:
        raise ValueError("invalid recalculation gate")
    request = json.loads((stage / "request.json").read_bytes())
    gate = json.loads(gate_raw)
    if gate.get("schema") != "rfad.wsl-start/0.1" or any(gate.get(key) != request[key] for key in ("run_id", "nonce")):
        raise ValueError("recalculation ownership mismatch")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from rfad.adapters.solvers.openems.native import input_index, write_json
    from rfad.adapters.solvers.openems.pcb_absorption import postprocess

    inputs = input_index(stage, request["input_files"])
    plan = json.loads(inputs["plan"].read_bytes())
    radiation = json.loads(inputs["radiation"].read_bytes())
    statistics = json.loads(inputs["statistics"].read_bytes())
    power, _ = postprocess(stage, plan, inputs["raw/pcb.xml"].parent, radiation, statistics)
    write_json(stage / "output/recalculation.json", {
        "schema": "rfad.independent-loss-recalculation/0.1", "native_producer": request["native_producer"],
        "calculator_identity": request["calculator_identity"], "power_balance": power,
        "fdtd_executed": False, "original_artifacts_modified": False,
        "physics_validated": False, "fabrication_validated": False, "measurement_validated": False})


if __name__ == "__main__":
    main()
