"""! @brief 다중 급전 계획의 원본 개정, 준비 XML, 실제 여기별 원시 파형을 검증한다."""

import json
import math

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_results import check_termination, read_statistics_values
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import validate_dataset

PROFILE = "rfad.openems.pcb-multiport/0.1"


def require(ok, message):
    """! @brief 불변 입력이나 결과 결합이 다르면 변경 근거를 반환한다."""
    if not ok:
        raise ProjectError("E_HASH", message)


def xml_role(number):
    """! @brief 첫 XML의 기존 준비 입력 역할을 유지하고 이후 여기를 구분한다."""
    return "native_input" if number == 1 else f"native_input_{number}"


def raw_names(count):
    """! @brief 여기마다 실제 실행이 기록해야 하는 포트 파형과 종료 근거다."""
    return ["pcb.xml", "native.log", "openEMS_stats.txt", "openEMS_run_stats.txt", "et", "ht",
            *(f"port_{kind}_{number}" for number in range(1, count + 1) for kind in ("ut", "it"))]


def plan_projection(document, settings):
    """! @brief 개별 방사 필드 요청과 다중 포트 정규화의 지원 범위를 명시한다."""
    from rfad.application.pcb_projection import project_pcb

    for option in ("field_probe", "power_balance", "radiation"):
        if option in settings:
            raise ProjectError("E_UNSUPPORTED", "다중 급전 S 행렬에서는 추가 전계, 방사 또는 손실 기록을 해제하세요.",
                               details={"field_path": "settings." + option})
    result = project_pcb(document, settings, multiport=True)
    ports = result["case"]["ports"]
    result["normalization"] = {"wave_definition": "power", "current_orientation": "into_dut",
                               "excitation": "one_active_port_all_terminated", "matrix": "S A = B",
                               "port_ids": [port["id"] for port in ports],
                               "reference_ohm": [port["resistance_ohm"] for port in ports]}
    result["model_report"]["scope"] = "user_pcb_multiport"
    result["model_report"]["unsupported_observables"].remove("full_s_matrix")
    resource = result["resource_estimate"]
    resource["max_wall_time_seconds"] = min(1800, resource["max_wall_time_seconds"] * len(ports))
    return result


def check_preparation(plan, preparation):
    """! @brief 캐시의 공통 격자, 단자 순서와 독립 여기 XML을 원본 계획에 결합한다."""
    case = plan["case"]
    mesh = preparation["mesh_statistics"]
    lines = mesh_lines(case)
    counts = [len(lines[k]) for k in "xyz"]
    require(mesh["lines_mm"] == lines and mesh["native_grid_points"] == math.prod(counts)
            and mesh["fdtd_executed"] is False and preparation["normalization"] == plan["normalization"]
            and preparation["consumption_report"]["consumed_case"] == case,
            "다중 포트 준비의 공통 격자, 입력 또는 정규화가 다릅니다.")
    contacts = preparation["consumption_report"]["contacts_by_excitation"]
    require(len(contacts) == len(case["ports"]) and all(len(row) == len(case["ports"]) for row in contacts),
            "준비 결과의 native 포트 접합 검사가 누락되었습니다.")


def check_result(journal, job, result, files):
    """! @brief 호스트에서 여기에 사용한 XML과 원시 통계, 전체 S행렬의 모든 포트를 다시 대조한다."""
    cap = job["solver"]
    plan, prep = cap["analysis_plan"], cap["preparation"]
    case, snapshot = plan["case"], plan["snapshot"]
    ports = case["ports"]
    roles = {row["role"]: row for row in files}
    manifest = json.loads(journal.read_artifact(roles["raw_manifest"]["artifact"]))
    require(result["raw_manifest"] == manifest and manifest["analysis_plan_hash"] == canonical_hash(plan)
            and manifest["prepared_plan_hash"] == canonical_hash(cap["prepared_plan"])
            and result["schema"] == PROFILE and result["snapshot"] == snapshot, "다중 포트 실행 원본과 결과가 다릅니다.")
    require(json.loads(journal.read_artifact(snapshot["artifact"])) == plan["source_semantics"],
            "봉인된 설계 스냅샷과 계획 원본이 다릅니다.")
    sources = {row["role"]: row for row in prep["files"]}
    expected = {"raw/" + str(port["number"]) + "/" + name for port in ports for name in raw_names(len(ports))}
    indexed = {row["role"]: row for row in manifest["files"]}
    require(set(roles) == expected | {"raw_manifest", "normalized_result", "touchstone"}
            and set(indexed) == expected and len(manifest["files"]) == len(expected), "여기별 원시 자료가 누락되거나 중복되었습니다.")
    for role, item in indexed.items():
        require(item == {k:v for k,v in roles[role].items() if k != "artifact"}, "원시 자료 파일 봉인이 다릅니다.")
    runs = manifest["runs"]
    require(len(runs) == len(ports), "독립 여기 수가 다릅니다.")
    for port, run in zip(ports, runs):
        number = port["number"]
        prefix = f"raw/{number}/"
        stats = read_statistics_values(journal.read_artifact(roles[prefix + "openEMS_stats.txt"]["artifact"]).decode(),
                                       case["settings"]["max_timesteps"])
        term = check_termination(journal.read_artifact(roles[prefix + "native.log"]["artifact"]).decode(),
                                 stats["iterations"], case["settings"])
        require(run["excited_port"] == number and run["statistics"] == stats and run["termination"] == term
                and stats["native_cells"] == prep["mesh_statistics"]["native_grid_points"]
                and roles[prefix + "pcb.xml"]["sha256"] == sources[xml_role(number)]["sha256"],
                "독립 여기의 XML, 격자 또는 종료 근거가 다릅니다.")
    data = result["network"]
    validate_dataset(data)
    provenance = data["provenance"]
    require(data["parameter_kind"] == "S" and data["port_ids"] == [p["id"] for p in ports]
            and data["reference_planes"] == [p["reference_plane"] for p in ports]
            and data["z0_ohm"] == [[[p["resistance_ohm"], 0.] for p in ports] for _ in data["frequency_hz"]]
            and data["wave_definition"] == "power" and provenance["snapshot"] == snapshot
            and provenance["source_sha256"] == snapshot["content_hash"] and provenance["case_sha256"] == canonical_hash(case)
            and provenance["settings_sha256"] == canonical_hash(case["settings"])
            and provenance["mesh_sha256"] == canonical_hash(prep["mesh_statistics"]["lines_mm"]),
            "정규 네트워크의 급전 순서, 기준 저항 또는 원본 해시가 다릅니다.")
    from rfad.application.pcb_results import frequency_axis_matches
    from rfad.adapters.network_touchstone import write_touchstone

    require(frequency_axis_matches(case["frequency_hz"], [{"frequency_hz": hz} for hz in data["frequency_hz"]])
            and journal.read_artifact(roles["touchstone"]["artifact"]) == write_touchstone(data),
            "Touchstone 값 또는 주파수 축이 계산한 전체 행렬과 다릅니다.")
