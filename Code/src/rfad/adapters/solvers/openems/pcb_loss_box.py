"""! @brief 검증된 단일 Cartesian 유전체 box의 QuarterCell 평균을 분리 가능한 배열로 계산한다."""

import math


def box_partition(csx, case, lines, indices, sheet):
    """! @brief native box/물성/좌표계를 확인한 경우에만 같은 네 표본의 면적 평균을 벡터화한다.

    @details 원형/다층/비아/변환/가중 재료는 일반 native 조회로 돌아간다.
    격자나 물리 입력, sheet/source edge 제외 규칙은 바꾸지 않는다.
    """
    import numpy as np

    layers = [item for item in case["layers"] if item["role"] == "dielectric"]
    if (case.get("vias") or case.get("board", {}).get("kind") != "rectangle" or len(layers) != 1
            or not hasattr(csx, "GetAllProperties")):
        return None
    layer = layers[0]
    materials = [prop for prop in csx.GetAllProperties() if prop.GetType() & 0x002]
    if len(materials) != 1:
        return None
    prop = materials[0]
    if (prop.GetType() != 0x002 or prop.GetName() != "dielectric_" + layer["id"] or not prop.GetIsotropy()
            or prop.GetQtyPrimitives() != 1 or prop.GetMaterialWeight("kappa") not in ("", "1", "1.0")
            or prop.GetMaterialProperty("kappa") not in (layer["kappa_s_per_m"], float(format(layer["kappa_s_per_m"], ".7g")))):
        return None
    box = prop.GetPrimitive(0)
    if box.GetTypeName() != "Box" or box.HasTransform() or box.GetCoordinateSystem() not in (None, -1, 0):
        return None
    low, high = np.minimum(box.GetStart(), box.GetStop()), np.maximum(box.GetStart(), box.GetStop())
    expected = [*case["board"]["bounds_mm"], [layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"]]]
    if not np.allclose(np.stack((low, high), axis=1), expected, rtol=0, atol=1e-10):
        return None
    total = np.zeros(sheet.shape, dtype=np.float64)
    for direction in range(3):
        fractions = []
        for axis, name in enumerate("xyz"):
            values, ids = np.asarray(lines[name]), np.asarray(indices[axis])
            center = values[ids]
            if direction == axis:
                point = (center + values[ids + 1]) * 0.5
                fractions.append(((point >= low[axis]) & (point <= high[axis])).astype(float))
            else:
                before, after = center - values[ids - 1], values[ids + 1] - center
                a, b = center - before * 0.25, center + after * 0.25
                fractions.append((((a >= low[axis]) & (a <= high[axis])) * before
                                  + ((b >= low[axis]) & (b <= high[axis])) * after) / (before + after))
        total[direction] = layer["kappa_s_per_m"] * fractions[0][:, None, None] * fractions[1][None, :, None] * fractions[2][None, None, :]
    total[sheet != -1] = 0
    locations = np.flatnonzero(total.ravel())
    return total, [{"kind": "dielectric", "entity_id": layer["id"], "indices": locations, "fraction": np.ones(len(locations))}]
