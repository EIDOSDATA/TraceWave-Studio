"""! @brief 실제 다중급전 원시 파형의 독립 검산, 재처리와 프로젝트 재열기를 수행한다."""

import argparse
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

from rfad.adapters.solvers.openems import pcb_multiport
from rfad.adapters.solvers.openems.native import file_identity


def verify_columns(root):
    """! @brief 제품의 재처리와 별개로 공급사 CalcPort에서 전체 복소 행렬을 구한다."""
    import CSXCAD
    import numpy as np
    import openEMS

    input_value = json.loads((root / "input.json").read_bytes())
    source = input_value["document"]
    case = json.loads((root / "case.json").read_bytes())
    recorded = json.loads((root / "network.json").read_bytes())
    summary = json.loads((root / "result.json").read_bytes())
    frequency = np.asarray(recorded["frequency_hz"])
    ports = case["ports"]
    count = len(ports)
    incident = np.empty((len(frequency), count, count), dtype=complex)
    outgoing = np.empty_like(incident)
    columns = []
    if len(summary["runs"]) != count:
        raise ValueError("모든 독립 여기의 원시 자료가 필요합니다.")
    for drive, (port, run) in enumerate(zip(ports, summary["runs"])):
        raw = root / f"excitation-{port['number']}"
        if run["termination"]["status"] != "end_criterion_reached":
            raise ValueError("에너지 종료 기준을 만족한 원시 자료를 선택하십시오.")
        if any(file_identity(raw / name) != signature for name, signature in run["artifacts"].items()):
            raise ValueError("실제 여기 원문이 저장한 해시와 다릅니다.")
        columns.append((*pcb_multiport.port_waves(raw, case, frequency), run))
        csx = CSXCAD.ContinuousStructure()
        simulation = openEMS.openEMS()
        simulation.SetCSX(csx)
        for row, terminal in enumerate(ports):
            resistance = terminal["resistance_ohm"]
            probe = simulation.AddLumpedPort(terminal["number"], resistance, terminal["start_mm"], terminal["stop_mm"],
                                              terminal["axis"], excite=int(row == drive))
            probe.CalcPort(str(raw), frequency, ref_impedance=resistance)
            incident[:, row, drive] = probe.uf_inc / np.sqrt(resistance)
            outgoing[:, row, drive] = probe.uf_ref / np.sqrt(resistance)
    reference = outgoing @ np.linalg.inv(incident)
    rebuilt = pcb_multiport.network_dataset(columns, case, source, frequency, recorded["provenance"],
                                             recorded["conditions"]["physical_setup_omissions"])
    if rebuilt != recorded:
        raise ValueError("재처리한 전체 네트워크가 원래 값과 다릅니다.")
    values = np.asarray(recorded["values_ri"])
    native_delta = np.max(abs(values[..., 0] + 1j * values[..., 1] - reference))
    if native_delta > 1e-8:
        raise ValueError("독립 CalcPort의 모든 여기 행렬과 차이가 기준을 넘습니다.")
    return {"ports": count, "frequencies": len(frequency), "complex_coefficients": count**2 * len(frequency),
            "max_official_delta": float(native_delta), "reprocessed_equal": True,
            "wall_seconds": [run["wall_seconds"] for run in summary["runs"]],
            "snapshot_sha256": summary["source_sha256"], "grid_sha256": summary["mesh_sha256"],
            "network_sha256": summary["network"]["sha256"]}


def verify_reopen(root, workspace):
    """! @brief 실제 원문을 프로젝트에 저장하고 새 서비스에서 전체 행렬과 원본을 읽는다."""
    from rfad.application.projects import ProjectService
    from test_cad_worker_process import register_fixture
    from verify_openems_worker import call

    native = json.loads((root / "input.json").read_bytes())["document"]
    dataset = json.loads((root / "network.json").read_bytes())
    count = len(dataset["port_ids"])
    name = f"network.s{count}p"
    original = (root / name).read_bytes()
    if workspace.exists():
        raise FileExistsError(workspace)
    with ProjectService(workspace, auto_run=False) as service:
        project, snapshot = register_fixture(service, native)
        context = {"project_id": project["project_id"]}
        data = {"operation": "import", "expected_revision": project["revision_id"], "parameters": {
            "name": f"실제 PCB {count}포트", "file_name": name, "format": "touchstone",
            "source_base64": base64.b64encode(original).decode("ascii"), "mapping": None,
            "declarations": {key: dataset[key] for key in ("port_ids", "reference_planes",
                "current_orientation", "port_modes", "wave_definition", "phasor_convention")},
        }}
        preview = call(service, "network.preview", data, context)
        if not preview["can_apply"]:
            raise ValueError(str(preview["issues"]))
        result = call(service, "network.apply", {**data, "command_id": str(uuid4()),
                      "review_hash": preview["review_hash"]}, context, mutation=True)
        query = {"expected_revision": result["new_revision"], "dataset_id": result["record_id"]}
        save = call(service, "project.save", {"expected_revision": result["new_revision"]}, context, mutation=True)
        service.run_next()
        if call(service, "job.status", {"job_id": save["job_id"]})["state"] != "completed":
            raise ValueError("검증용 프로젝트가 저장되지 않았습니다.")
    with ProjectService(workspace, auto_run=False) as reopened:
        metadata = call(reopened, "network.library", {"expected_revision": query["expected_revision"]}, context)
        record = next(item for item in metadata["datasets"] if item["id"] == query["dataset_id"])
        if reopened.journal.read_artifact(record["raw"]) != original:
            raise ValueError("재열기에서 Touchstone 원문이 바뀌었습니다.")
        for row in range(count):
            for column in range(count):
                page = call(reopened, "network.get", {**query, "row": row, "column": column,
                            "offset": 0, "limit": len(dataset["frequency_hz"])}, context)["page"]["samples"]
                target = [item[row][column] for item in dataset["values_ri"]]
                if [[item["real"], item["imag"]] for item in page] != target:
                    raise ValueError("재열기한 복소 행렬이 원래 결과와 다릅니다.")
    return {"reopened": True, "ports": count, "source_snapshot_sha256": snapshot["content_hash"],
            "record_id": query["dataset_id"]}


def main():
    """! @brief 기존 원문 검산 또는 새 실제 Windows 여기와 저장 검증을 선택한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--count", type=int)
    parser.add_argument("--reopen-workspace", type=Path)
    args = parser.parse_args()
    if args.reopen_workspace is not None:
        print(json.dumps(verify_reopen(args.root, args.reopen_workspace), ensure_ascii=False))
        return
    if args.executable is None:
        parser.error("Windows openEMS 실행 파일이 필요합니다.")
    exe = args.executable.resolve(strict=True)
    with os.add_dll_directory(str(exe.parent)):
        if args.count is not None:
            from test_pcb_multiport_extended import fixture

            pcb_multiport.EXECUTABLE = exe
            pcb_multiport.run(*fixture(args.count), args.root)
        print(json.dumps(verify_columns(args.root), ensure_ascii=False))


if __name__ == "__main__":
    main()
