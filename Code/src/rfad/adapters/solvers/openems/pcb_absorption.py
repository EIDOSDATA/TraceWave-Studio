"""! @brief 실제 Yee E/J/rotH 필드로 유전체와 유한 sheet 흡수 손실을 독립 적분한다."""

import itertools
import math
from pathlib import Path
import tempfile
from xml.etree import ElementTree

from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_power import SCHEMA, NAMES, balance_rows, validate_result
from rfad.application.pcb_loss_components import via_resolution
from .native import require, write_json, descriptor
from .pcb_loss_partition import PARTITION_METHOD, material_partition, partition_work


def create_dumps(csx, recording):
    """! @brief 경계에서 필드를 섞지 않는 원래 전기 edge의 복소 스펙트럼을 기록한다."""
    for name, kind in zip(NAMES, recording["dump_types"]):
        prop = csx.AddDump(name[:-3], dump_type=kind, dump_mode=0, file_type=1, frequency=recording["frequency_hz"])
        # @brief native dump는 밖으로 snap한다. XML의 7자리 좌표 반올림에도 계획 면이 유지되게 안쪽에 둔다.
        prop.AddBox(recording["primitive_start_mm"], recording["primitive_stop_mm"])


def edge_weights(lines, indices, direction):
    """! @brief 실제 edge 길이와 두 접선 dual 폭으로 전기 edge의 SI 체적을 계산한다."""
    import numpy as np

    widths = []
    for axis, positions in enumerate(indices):
        values = np.asarray(lines["xyz"[axis]]) * 0.001
        ids = np.asarray(positions)
        width = values[ids + 1] - values[ids] if axis == direction else (values[ids + 1] - values[ids - 1]) * 0.5
        widths.append(width)
    return widths[0][:, None, None] * widths[1][None, :, None] * widths[2][None, None, :]


def sheet_partition(csx, case, lines, indices):
    """! @brief solver와 같은 MATERIAL|METAL 우선순위를 실제 전기 edge 중심에서 조회한다."""
    import numpy as np

    shape = tuple(len(axis) for axis in indices)
    result = np.full((3, *shape), -1, dtype=np.int16)
    entities = {"conductor_" + item["id"]: index for index, item in enumerate(case["shapes"])}
    elevations = {item["sheet_z_mm"] for item in case["shapes"]}
    for k, z in enumerate(indices[2]):
        if not any(math.isclose(lines["z"][z], value, rel_tol=0, abs_tol=1e-10) for value in elevations):
            continue
        for direction in (0, 1):
            for i, j in itertools.product(range(shape[0]), range(shape[1])):
                position = [indices[0][i], indices[1][j], z]
                point = [lines[axis][n] for axis, n in zip("xyz", position)]
                point[direction] = (point[direction] + lines["xyz"[direction]][position[direction] + 1]) * 0.5
                prop = csx.GetPropertyByCoordPriority(point, prop_type=0x002 | 0x004)
                if prop is not None and prop.GetName() in entities:
                    result[direction, i, j, k] = entities[prop.GetName()]
    counts = [int(np.count_nonzero(result == index)) for index in range(len(entities))]
    # @brief 같은 net의 겹친 원본은 native 우선순위에 따라 하나만 점유하며 중복 적분하지 않는다.
    require(sum(counts) > 0, "독립 손실 적분에 실제 sheet Yee edge가 없습니다.")
    port = case["port"]
    direction = "xyz".index(port["axis"]) if isinstance(port["axis"], str) else port["axis"]
    for position in itertools.product(*(range(size) for size in shape)):
        point = [lines[axis][indices[n][position[n]]] for n, axis in enumerate("xyz")]
        point[direction] = (point[direction] + lines["xyz"[direction]][indices[direction][position[direction]] + 1]) * 0.5
        if all(min(a, b) - 1e-10 <= value <= max(a, b) + 1e-10 for value, a, b in zip(point, port["start_mm"], port["stop_mm"])):
            require(result[(direction, *position)] == -1, "포트 저항과 sheet 손실 영역이 겹칩니다.")
            result[(direction, *position)] = -2
    return result, counts


def read_fields(raw, recording, lines, index):
    """! @brief HDF 좌표/주파수/벡터 순서를 확인하고 복소 float64로 읽는다."""
    import h5py
    import numpy as np

    arrays = []
    for name in NAMES:
        with h5py.File(raw / name, "r") as stream:
            require(not stream.attrs.get("legacy_fmt", False) and not stream.attrs.get("dual_mesh", True), "손실 적분은 현재 primary Yee HDF 형식이 필요합니다.", "E_VERSION")
            for axis, first, last in zip("xyz", recording["start_indices"], recording["stop_indices"]):
                expected = np.asarray(lines[axis][first:last + 1]) * 0.001
                observed = np.asarray(stream["Mesh"][axis])
                require(observed.shape == expected.shape and np.allclose(observed, expected, rtol=0, atol=1e-12), "손실 필드의 실제 Yee 격자가 계획과 다릅니다.", "E_HASH")
            group = stream["FieldData/FD"]
            frequencies = np.asarray(group.attrs["frequency"])
            require(frequencies.shape == (len(recording["frequency_hz"]),) and np.allclose(frequencies, recording["frequency_hz"], rtol=1e-6, atol=0), "손실 필드의 주파수가 다릅니다.", "E_HASH")
            data = np.asarray(group["f" + str(index)])
            if data.dtype.names:
                require(set(data.dtype.names) == {"real", "imag"}, "지원하지 않는 복소 HDF 손실 필드입니다.")
                data = data["real"].astype(np.float64) + 1j * data["imag"].astype(np.float64)
            else:
                data = data.astype(np.complex128)
            # @brief pinned 0.37 writer의 현재 HDF 저장 순서는 component,x,y,z다.
            expected_shape = (3, *(last - first + 1 for first, last in zip(recording["start_indices"], recording["stop_indices"])))
            require(data.shape == expected_shape and np.all(np.isfinite(data)), "손실 필드의 벡터 크기 또는 유한성이 다릅니다.")
            arrays.append(data)
    return arrays


def integrate_fields(electric, conduction, total_current, weights, partition, frequency, timestep, entities):
    """! @brief 체적 E*J와 sheet E*rotH를 독립 합산하며 음수도 그대로 보존한다.

    @details rotH dump는 H의 반 time step을 전기 시간으로 기록하므로 위상을 보정한다.
    사다리꼴 손실 전류의 cos(omega*dt/2)도 보정한다. 변위 전류는 실수 일률에 기여하지 않는다.
    """
    import numpy as np

    angle = math.pi * frequency * timestep
    require(0 <= angle < math.pi / 4, "손실 전력의 시간 이산화가 지원 범위를 벗어났습니다.")
    correction = np.exp(-1j * angle) / math.cos(angle)
    dielectric = 0.0
    sheet = np.zeros(len(entities), dtype=np.float64)
    for direction in range(3):
        volume_power = 0.5 * np.real(electric[direction] * np.conj(conduction[direction])) * weights[direction]
        dielectric += float(np.sum(volume_power[partition[direction] == -1], dtype=np.float64))
        local = 0.5 * np.real(electric[direction] * np.conj(total_current[direction] * correction)) * weights[direction]
        for index in range(len(entities)):
            sheet[index] += np.sum(local[partition[direction] == index], dtype=np.float64)
    return {"dielectric_loss_w_s2": dielectric, "conductor_loss_w_s2": math.fsum(float(value) for value in sheet),
            "sheet_components": [{"entity_id": item["id"], "loss_w_s2": float(value)} for item, value in zip(entities, sheet)]}


def postprocess(stage, plan, raw, radiation, statistics):
    """! @brief 봉인한 손실 원시 필드를 적분하고 같은 실행의 방사/수용 전력과 비교한다."""
    import CSXCAD

    case = plan["case"]
    recording = case["loss_recording"]
    lines = mesh_lines(case)
    indices = [list(range(first, last + 1)) for first, last in zip(recording["start_indices"], recording["stop_indices"])]
    csx = CSXCAD.ContinuousStructure()
    # @brief CSXCAD reader는 openEMS wrapper를 읽지 않으므로 봉인 XML의 해당 자식만 추출한다.
    structure = ElementTree.parse(raw / "pcb.xml").getroot().find("ContinuousStructure")
    require(structure is not None, "봉인 XML에 ContinuousStructure가 없습니다.")
    with tempfile.TemporaryDirectory(prefix="rfad-loss-") as temporary:
        geometry = Path(temporary) / "geometry.xml"
        ElementTree.ElementTree(structure).write(geometry, encoding="utf-8", xml_declaration=True)
        require(not csx.ReadFromXML(str(geometry)), "봉인한 native 기하를 손실 분할에 읽을 수 없습니다.")
    partition, counts = sheet_partition(csx, case, lines, indices)
    weights = [edge_weights(lines, indices, direction) for direction in range(3)]
    material = material_partition(csx, case, lines, indices, partition)
    calculated = [partition_work(*read_fields(raw, recording, lines, index), weights, partition, frequency,
                                 statistics["timestep_seconds"], case["shapes"], material)
                  for index, frequency in enumerate(recording["frequency_hz"])]
    losses = [item[0] for item in calculated]
    threshold = case["settings"]["power_balance"]["max_relative_residual"]
    rows = balance_rows(recording, radiation, losses, threshold)
    result = {"schema": SCHEMA, "analysis_plan_id": plan["plan_id"], "recording": recording,
              "frequencies": rows, "max_relative_residual": threshold,
              "full_energy_closure": "within_initial_numerical_budget" if all(row["status"] == "within_initial_numerical_budget" for row in rows) else "requires_review",
              "integration": {"method": recording["method"], "sheet_edge_counts": counts,
                              "partition_method": PARTITION_METHOD,
                              "volume_material_averaging": "native_quarter_cell_material_only",
                              "sheet_material_current_excluded": True,
                              "sheet_coefficient_model": "native_ade_overrides_ec_g_c",
                              "frequency_audits": [item[1] for item in calculated],
                              "via_edge_counts": [{"entity_id": piece["entity_id"], "count": len(piece["indices"])} for piece in material[1] if piece["kind"] == "via"],
                              "via_resolution": via_resolution(case, lines),
                              "rotH_timestamp_correction": "exp(-j*pi*f*dt)/cos(pi*f*dt)",
                              "displacement_current": "reactive_real_work_zero_for_completed_fourier_spectrum",
                              "source_resistor_excluded": True, "pml_excluded": True},
              "power_unit": "W*s^2", "absolute_power_w": None, "physics_validated": False,
              "fabrication_validated": False, "measurement_validated": False}
    validate_result(plan, result, radiation)
    path = stage / "output/power_balance.json"
    write_json(path, result)
    return result, descriptor(stage, path, "power_balance_result")
