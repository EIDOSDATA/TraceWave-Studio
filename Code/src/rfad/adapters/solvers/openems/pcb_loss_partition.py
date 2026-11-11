"""! @brief native QuarterCell 전도도 기여율로 유전체와 중공 PTH의 Yee 손실을 분할한다."""

import itertools
import math

from .native import require


PARTITION_METHOD = "quarter_cell_volume_and_native_sheet_override/0.1"


def material_partition(csx, case, lines, indices, sheet):
    """! @brief 증명 가능한 box만 벡터화하고 나머지는 native 표본 경로로 계산한다."""
    from .pcb_loss_box import box_partition

    accelerated = box_partition(csx, case, lines, indices, sheet)
    return accelerated if accelerated is not None else sampled_material_partition(csx, case, lines, indices, sheet)


def sampled_material_partition(csx, case, lines, indices, sheet):
    """! @brief solver와 같은 네 quarter-cell 표본/면적 가중치로 재료 기여율을 만든다.

    @details 체적 평균은 MATERIAL만 조회하며 sheet 점유 검사는 별도의 MATERIAL|METAL
    우선순위를 사용한다. 하나의 전기 edge에 섞인 유전체와 비아를 중심점으로 나누지 않는다.
    """
    import numpy as np

    shape = (3, *(len(axis) for axis in indices))
    total = np.zeros(shape, dtype=np.float64)
    materials = {"dielectric_" + item["id"]: ("dielectric", item["id"], item["kappa_s_per_m"])
                 for item in case["layers"] if item["role"] == "dielectric"}
    materials.update({"via_" + item["id"]: ("via", item["id"], item["conductivity_s_per_m"])
                      for item in case.get("vias", [])})
    pieces = {name: {"kind": kind, "entity_id": identity, "indices": [], "coefficient": []}
              for name, (kind, identity, _) in materials.items()}
    for direction in range(3):
        transverse = [(direction + offset) % 3 for offset in (1, 2)]
        for position in itertools.product(*(range(size) for size in shape[1:])):
            key = (direction, *position)
            if sheet[key] != -1:
                continue
            global_index = [indices[axis][position[axis]] for axis in range(3)]
            point = [lines[axis][index] for axis, index in zip("xyz", global_index)]
            point[direction] = (point[direction] + lines["xyz"[direction]][global_index[direction] + 1]) * 0.5
            local = {}
            area = 0.0
            for signs in itertools.product((-1, 1), repeat=2):
                sample = point.copy()
                weight = 1.0
                for axis, sign in zip(transverse, signs):
                    values, index = lines["xyz"[axis]], global_index[axis]
                    width = abs(values[index + sign] - values[index])
                    sample[axis] += sign * width * 0.25
                    weight *= width
                area += weight
                prop = csx.GetPropertyByCoordPriority(sample, prop_type=0x002)
                if prop is None or prop.GetName().startswith("drill_"):
                    continue
                name = prop.GetName()
                require(name in materials, "손실 분할에 알 수 없는 체적 재료가 있습니다.", "E_HASH")
                local[name] = local.get(name, 0.0) + weight * materials[name][2]
            flat = np.ravel_multi_index(key, shape)
            for name, value in local.items():
                coefficient = value / area
                if coefficient != 0:
                    pieces[name]["indices"].append(flat)
                    pieces[name]["coefficient"].append(coefficient)
                    total[key] += coefficient
    flat_total = total.ravel()
    for piece in pieces.values():
        piece["indices"] = np.asarray(piece["indices"], dtype=np.int64)
        coefficient = np.asarray(piece.pop("coefficient"), dtype=np.float64)
        piece["fraction"] = coefficient / flat_total[piece["indices"]]
        if piece["kind"] == "via":
            require(len(piece["indices"]) > 0, "비아의 체적 손실 표본이 격자에서 사라졌습니다.", "E_GEOMETRY")
    return total, list(pieces.values())


def partition_work(electric, conduction, total_current, weights, sheet, frequency, timestep, shapes, material):
    """! @brief sheet가 대체한 edge의 재료 J를 제외하고 native sheet 전체 일만 rotH로 계산한다."""
    import numpy as np

    angle = math.pi * frequency * timestep
    require(0 <= angle < math.pi / 4, "손실 적분의 시간 해상도가 지원 범위를 벗어났습니다.")
    coefficient, pieces = material
    # @brief native ADE sheet는 EC_G/EC_C를 덮어쓴다. 남아 있는 material J dump는 그 edge의 실제 전류가 아니다.
    active = sheet == -1
    expected = electric * coefficient.astype(np.float32)
    difference = np.abs(conduction - expected)[active]
    scale = np.maximum(np.abs(conduction), np.abs(expected))[active]
    peak = float(np.max(scale, initial=0.0))
    error = float(np.max(difference / np.maximum(scale, max(peak * 1e-7, 1e-300)), initial=0.0))
    require(error <= 0.005, "native J와 QuarterCell 재료 분할의 유효 전도도가 다릅니다.", "E_HASH")
    volume = 0.5 * np.real(electric * np.conj(conduction)) * np.asarray(weights)
    volume[~active] = 0.0
    require(not np.any((coefficient == 0) & active & (np.abs(conduction) > peak * 1e-7)),
            "재료에 배정되지 않은 전도 전류가 있습니다.", "E_HASH")
    dielectric, vias = [], []
    for piece in pieces:
        value = float(np.sum(volume.ravel()[piece["indices"]] * piece["fraction"], dtype=np.float64))
        (dielectric if piece["kind"] == "dielectric" else vias).append({"entity_id": piece["entity_id"], "loss_w_s2": value})
    correction = np.exp(-1j * angle) / math.cos(angle)
    sheet_power = 0.5 * np.real(electric * np.conj(total_current * correction)) * np.asarray(weights)
    sheets = [{"entity_id": shape["id"], "loss_w_s2": float(np.sum(sheet_power[sheet == index], dtype=np.float64))}
              for index, shape in enumerate(shapes)]
    planar = math.fsum(item["loss_w_s2"] for item in sheets)
    via = math.fsum(item["loss_w_s2"] for item in vias)
    result = {"dielectric_loss_w_s2": math.fsum(item["loss_w_s2"] for item in dielectric),
              "conductor_loss_w_s2": planar + via, "sheet_loss_w_s2": planar, "via_loss_w_s2": via,
              "sheet_components": sheets, "via_components": vias, "dielectric_components": dielectric}
    actual_volume = float(np.sum(volume, dtype=np.float64))
    require(math.isclose(actual_volume, result["dielectric_loss_w_s2"] + via, rel_tol=1e-10, abs_tol=1e-300),
            "체적 전도 일이 재료별 합계에 한 번씩 배정되지 않았습니다.", "E_HASH")
    return result, {"material_current_max_mixed_relative_error": error,
                    "volume_work_w_s2": actual_volume,
                    "assigned_volume_work_w_s2": result["dielectric_loss_w_s2"] + via}
