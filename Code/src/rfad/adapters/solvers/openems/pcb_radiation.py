"""! @brief 선택한 PCB의 폐곡면 기록과 봉인 원시 필드의 NF2FF 후처리를 담당한다."""

from rfad.application.pcb_radiation import SCHEMA, validate_result, summary
from rfad.application.radiation import spectral_power_metrics
from .native import require, write_json, descriptor
from .pcb_ports import spectra


def create_box(csx, recording):
    """! @brief 계획과 같은 이름/면/주파수로 주파수 영역 기록을 생성한다."""
    from openEMS.nf2ff import nf2ff

    return nf2ff(csx, recording["name"], recording["start_mm"], recording["stop_mm"], frequency=recording["frequency_hz"])


def postprocess(stage, plan, raw):
    """! @brief 원시 E/H와 포트 스펙트럼에서 방사량을 계산하며 FDTD는 시작하지 않는다."""
    import numpy as np
    import CSXCAD

    recording = plan["case"]["radiation_recording"]
    box = create_box(CSXCAD.ContinuousStructure(), recording)
    field = box.CalcNF2FF(str(raw.resolve()), recording["frequency_hz"], recording["theta_deg"], recording["phi_deg"],
                         center=recording["center_m"], radius=recording["radius_m"], read_cached=False)
    voltage, current = spectra(raw, recording["frequency_hz"])
    resistance = plan["case"]["port"]["resistance_ohm"]
    incident = 0.5 * (voltage + resistance * current)
    require(np.all(np.isfinite(incident)) and np.all(np.abs(incident) > 1e-18), "방사 정규화의 포트 여기 크기가 부족합니다.")
    rows = []
    for index, frequency in enumerate(recording["frequency_hz"]):
        accepted = float(0.5 * np.real(voltage[index] * np.conj(current[index])))
        incoming = float(0.5 * abs(incident[index]) ** 2 / resistance)
        metrics = spectral_power_metrics(float(field.Prad[index]), accepted, incoming, float(field.Dmax[index]))
        et, ep = np.asarray(field.E_theta[index]), np.asarray(field.E_phi[index])
        power = np.abs(et) ** 2 + np.abs(ep) ** 2
        peak = float(np.max(power))
        require(np.isfinite(peak) and peak > 0, "방사 패턴의 유한한 최대값이 없습니다.")
        normalized = power / peak
        def complex_matrix(values):
            """! @brief 복소 필드를 실수/허수 쌍으로 저장한다."""
            return [[[float(value.real), float(value.imag)] for value in row] for row in values]
        rows.append({"frequency_hz": frequency, "metrics": metrics, "e_theta": complex_matrix(et),
                     "e_phi": complex_matrix(ep), "normalized_power": normalized.tolist(),
                     "directivity": (normalized * metrics["directivity_linear"]).tolist()})
    result = {"schema": SCHEMA, "analysis_plan_id": plan["plan_id"], "recording": recording, "frequencies": rows,
              "electric_field_unit": "V*s/m", "power_unit": "W*s^2", "absolute_power_w": None,
              "physics_validated": False, "status": "computed_unvalidated"}
    validate_result(plan, result)
    path = stage / "output/radiation.json"
    write_json(path, result)
    return summary(result), [descriptor(stage, path, "radiation_result"),
                             descriptor(stage, raw / (recording["name"] + ".h5"), "radiation_native")]
