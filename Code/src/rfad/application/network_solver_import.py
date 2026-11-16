"""! @brief 봉인된 PCB 계산의 복소 원본과 NF2FF 비율을 공통 자료로 투영한다."""

from copy import deepcopy
import json
import math

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_results import validate_result
from rfad.application.project_contract import _uuid
from rfad.domain.network_data import make_dataset
from rfad.domain.network_library import fail


def solver_dataset(service, state, document, identity):
    """! @brief 기존 S11 복소수만 재사용하고 dB에서 원래 위상을 역추정하지 않는다."""
    _uuid(identity)
    record = state["solver_results"].get(identity)
    if record is None or record["project_id"] != document["project_id"]:
        fail("현재 프로젝트의 봉인된 계산 결과가 없습니다.", "artifact_id", "E_MISSING_ARTIFACT")
    raw = service.journal.read_artifact(record["normalized"])
    original = json.loads(raw)
    if original.get("schema") != "rfad.openems-pcb-result/0.1":
        fail("이 투영 profile은 기존 단일 포트 PCB 결과를 지원합니다.", "artifact_id", "E_UNSUPPORTED")
    plan = original.get("provenance", {}).get("analysis_plan")
    if type(plan) is not dict or plan.get("snapshot", {}).get("project_id") != document["project_id"]:
        fail("기존 계산의 프로젝트 입력 사본을 확인할 수 없습니다.", "artifact_id", "E_HASH")
    validate_result(plan, original)
    norm = original["normalization"]
    if norm.get("wave_definition") != "voltage_wave_real_lumped_resistance" or norm.get("fourier_convention") != "exp(-j*2*pi*f*t)":
        fail("명시적으로 대응하지 않은 기존 파/시간 규약입니다.", "normalization", "E_UNSUPPORTED")
    rows = original["samples"]
    frequencies = [row["frequency_hz"] for row in rows]
    resistance = norm["reference_impedance_ohm"]
    port = plan["case"]["port"]
    dataset = make_dataset(parameter_kind="S", frequency_hz=frequencies, port_ids=[port["id"]],
        values_ri=[[[deepcopy(row["s11"])]] for row in rows],
        z0_ohm=[[[float(resistance), 0.0]] for _ in rows], port_names=[None],
        reference_planes=[norm["reference_plane"]], port_modes=["single_ended"], current_orientation=["into_dut"],
        wave_definition="traveling", phasor_convention="exp(+j*omega*t)", sample_origin=["computed"] * len(rows),
        source_refs=["solver artifact: " + identity],
        provenance={"adapter": "rfad.network-pcb-projection/0.1", "normalized_source": deepcopy(record["normalized"]),
                    "snapshot": deepcopy(plan["snapshot"]), "normalization_original": deepcopy(norm),
                    "solver_assessment_original": deepcopy(original["assessment"]),
                    "basis_mapping": "실수 lumped Z0의 전압파 반사 비와 exp(-jwt) Fourier 계수를 exp(+jwt) phasor로 표현"},
        conditions={"manufacturing": None, "measurement": None, "physics_validated": False,
                    "absolute_power_w": None, "power_normalization": "pulse_fourier_ratio_only"})
    return dataset, raw


def radiation_metrics(service, project, entry, dataset):
    """! @brief 원본 PCB 결과와 같은 자료에만 저장된 방사 비율 근거를 연결한다."""
    if entry["kind"] != "solver" or entry["raw"] is None:
        return None
    if not entry["raw"]["uri"].startswith(project["path"] + "/"):
        fail("계산 원문이 현재 프로젝트에 속하지 않습니다.", "raw", "E_HASH")
    original = json.loads(service.journal.read_artifact(entry["raw"]))
    summary = original.get("radiation_summary")
    if summary is None:
        return None
    if summary.get("physics_validated") is not False or summary.get("absolute_power_w") is not None or summary.get("power_unit") != "W*s^2":
        fail("원본 방사 비율의 정규화 조건이 다릅니다.", "radiation_summary", "E_HASH")
    rows = summary.get("metrics")
    if type(rows) is not list or len(rows) > 1001:
        fail("원본 방사 표본이 유효하지 않습니다.", "radiation_summary", "E_HASH")
    values = {"dataset_hash": canonical_hash(dataset), "source_refs": [entry["raw"]["sha256"]],
              "physics_validated": False, "frequency_hz": [], "radiation_efficiency": [], "total_efficiency": []}
    for row in rows:
        incident, radiated = row.get("incident_power_w_s2"), row.get("radiated_power_w_s2")
        total = None
        if all(type(value) in (float, int) and math.isfinite(value) for value in (incident, radiated)) and incident > 0:
            total = radiated / incident
            if not math.isfinite(total):
                total = None
        values["frequency_hz"].append(row["frequency_hz"])
        values["radiation_efficiency"].append(row.get("radiation_efficiency"))
        values["total_efficiency"].append(total)
    return values
