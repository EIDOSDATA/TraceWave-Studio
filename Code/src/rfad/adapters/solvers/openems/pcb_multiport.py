"""! @brief 사용자 PCB의 공통 격자에서 두 급전을 각각 여기하고 복소 S 행렬을 구한다."""

from pathlib import Path
import subprocess
import time

from rfad.adapters.network_touchstone import write_touchstone
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_compute import limits
from rfad.application.pcb_geometry import fail
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_projection import project_pcb
from rfad.application.pcb_solver import check_pcb_input
from rfad.domain.network_data import make_dataset
from .native import EXECUTABLE, file_identity, require, write_json
from .pcb import add_geometry, statistics_and_termination
from .pcb_mesh import audit_native_mesh
from .pcb_ports import spectra


def scattering(incident, outgoing):
    """! @brief 모든 입력에 대한 a와 b를 열에 놓고 주파수별 S A = B를 푼다."""
    import numpy as np

    require(incident.shape == outgoing.shape and incident.ndim == 3 and incident.shape[1:] == (2, 2),
            "각 주파수에 두 포트, 두 여기의 입사파와 출력파가 필요합니다.")
    require(np.isfinite(incident).all() and np.isfinite(outgoing).all(), "포트파에 비유한 값이 있습니다.")
    drives = np.abs(np.diagonal(incident, axis1=1, axis2=2))
    require(np.all(drives.max(axis=0) > 1e-18) and np.all(drives > drives.max(axis=0) * 1e-4),
            "급전의 유효 대역에 충분한 입사 스펙트럼이 없습니다.")
    scaled = incident / drives[:, None, :]
    condition = np.linalg.cond(scaled)
    require(np.isfinite(condition).all() and np.all(condition <= 1e8), "두 여기의 입사파 행렬이 특이하거나 조건수가 높습니다.")
    matrix = np.linalg.solve(scaled.transpose(0, 2, 1),
                             (outgoing / drives[:, None, :]).transpose(0, 2, 1)).transpose(0, 2, 1)
    require(np.isfinite(matrix).all(), "계산한 S 행렬에 비유한 값이 있습니다.")
    return matrix, float(condition.max())


def run_column(raw, case, lines, driven, frequencies):
    """! @brief 두 실제 lumped 종단을 생성한 다음 한 포트를 여기해 모든 원시 파형을 읽는다."""
    import CSXCAD
    import numpy as np
    import openEMS

    raw.mkdir()
    settings = case["settings"]
    csx = CSXCAD.ContinuousStructure()
    solver = openEMS.openEMS(NrTS=settings["max_timesteps"], EndCriteria=settings["end_criterion"])
    solver.SetCellConstantMaterial(False)
    solver.SetCSX(csx)
    solver.SetGaussExcite(case["excitation"]["center_hz"], case["excitation"]["width_hz"])
    solver.SetBoundaryCond(case["boundary_conditions"])
    grid = csx.GetGrid()
    grid.SetDeltaUnit(case["delta_unit_m"])
    for axis in "xyz":
        grid.AddLine(axis, lines[axis])
    add_geometry(csx, case)
    contacts = [audit_native_mesh(csx, {**case, "port": port}, lines) for port in case["ports"]]
    for port in case["ports"]:
        solver.AddLumpedPort(port["number"], port["resistance_ohm"], port["start_mm"], port["stop_mm"],
                             port["axis"], excite=int(port["number"] == driven), priority=10)
    actual = {axis: [float(value) for value in grid.GetLines(axis)] for axis in "xyz"}
    require(lines == actual, "생성된 native 격자가 공통 설계 격자와 다릅니다.", "E_HASH")
    solver.Write2XML(str(raw / "pcb.xml"))
    command = [str(EXECUTABLE), "pcb.xml", "--engine=multithreaded", f"--numThreads={case['num_threads']}",
               "--dump-statistics", "--exact-endcriteria"]
    started = time.monotonic()
    with (raw / "native.log").open("xb") as log:
        subprocess.run(command, cwd=raw, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=limits(settings)["max_wall_time_seconds"])
    statistics, termination = statistics_and_termination(raw, {"case": case})
    incident, outgoing = [], []
    for port in case["ports"]:
        resistance = port["resistance_ohm"]
        u, i = spectra(raw, frequencies, number=port["number"])
        factor = 2 * np.sqrt(resistance)
        incident.append((u + resistance * i) / factor)
        outgoing.append((u - resistance * i) / factor)
    return incident, outgoing, {
        "excited_port": driven, "mesh_sha256": canonical_hash(actual), "statistics": statistics,
        "termination": termination, "wall_seconds": time.monotonic() - started, "contacts": contacts,
        "artifacts": {p.name: file_identity(p) for p in sorted(raw.iterdir()) if p.is_file()},
    }


def run(document, settings, destination):
    """! @brief 원본 개정과 조건을 보존하고 두 실행의 종료가 확인되면 결과를 발행한다."""
    import CSXCAD
    import numpy as np
    import openEMS

    require(openEMS.__version__ == "0.37.0" and CSXCAD.__version__ == "0.7.0", "고정 WSL2 openEMS 환경을 확인하십시오.")
    executable = file_identity(EXECUTABLE)
    omissions = check_pcb_input(document, settings)
    for option in ("field_probe", "power_balance", "radiation"):
        if option in settings:
            fail("E_UNSUPPORTED", "다중 급전 S 행렬에는 추가 필드 및 전력 기록을 함께 요청할 수 없습니다.", "settings." + option)
    case = project_pcb(document, settings, multiport=True)["case"]
    lines = mesh_lines(case)
    frequency = case["frequency_hz"]
    frequencies = np.asarray(frequency.get("points", np.linspace(frequency["start"], frequency["stop"], frequency["count"])))
    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=False)
    write_json(dest / "input.json", {"document": document, "settings": settings})
    write_json(dest / "case.json", case)
    write_json(dest / "mesh.json", lines)
    columns = []
    for port in case["ports"]:
        number = port["number"]
        columns.append(run_column(dest / f"excitation-{number}", case, lines, number, frequencies))
    incident = np.stack([row[0] for row in columns], axis=-1).transpose(1, 0, 2)
    outgoing = np.stack([row[1] for row in columns], axis=-1).transpose(1, 0, 2)
    matrix, condition = scattering(incident, outgoing)
    impedances = [[p["resistance_ohm"], 0.0] for p in case["ports"]]
    identity = {"project_id": document["project_id"], "revision_id": document["revision_id"],
                "source_sha256": canonical_hash(document), "settings_sha256": canonical_hash(settings),
                "mesh_sha256": canonical_hash(lines), "case_sha256": canonical_hash(case),
                "executable": executable, "openems_version": openEMS.__version__,
                "csxcad_version": CSXCAD.__version__}
    data = make_dataset(parameter_kind="S", frequency_hz=frequencies.tolist(),
                        port_ids=[p["id"] for p in case["ports"]], values_ri=np.stack((matrix.real, matrix.imag), axis=-1).tolist(),
                        port_names=[p["name"] for p in document["ports"]], reference_planes=[p["reference_plane"] for p in case["ports"]],
                        z0_ohm=[impedances for _ in frequencies], port_modes=["single_ended"] * 2, current_orientation=["into_dut"] * 2,
                        wave_definition="power", phasor_convention="exp(+j*omega*t)", sample_origin=["computed"] * len(frequencies),
                        provenance=identity, conditions={"max_incident_matrix_condition": condition, "physical_setup_omissions": omissions})
    (dest / "network.s2p").write_bytes(write_touchstone(data))
    write_json(dest / "network.json", data)
    write_json(dest / "result.json", {"schema": "rfad.openems.pcb-multiport/0.1", **identity,
                                     "runs": [row[2] for row in columns], "network": file_identity(dest / "network.json"),
                                     "touchstone": file_identity(dest / "network.s2p"), "measurement_validated": False})
    return dest / "result.json"
