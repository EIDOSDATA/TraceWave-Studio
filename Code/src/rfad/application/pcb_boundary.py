"""! @brief 사용자 PCB의 여섯 외벽과 실제 흡수층 좌표를 관리한다."""

from rfad.application.pcb_geometry import fail


DEFAULT = ("PML_8",) * 6
MODES = {"PML_8", "MUR", "PEC", "PMC"}


def conditions(settings):
    """! @brief xmin, xmax, ymin, ymax, zmin, zmax 순서의 외벽 조건을 확인한다."""
    value = settings.get("boundary_conditions", list(DEFAULT))
    field = "settings.boundary_conditions"
    if type(value) is not list or len(value) != len(DEFAULT) or any(type(mode) is not str or mode not in MODES for mode in value):
        fail("E_SCHEMA", "X, Y, Z의 최소·최대 면마다 PML_8, MUR, PEC, PMC 중 하나를 지정하세요.", field)
    if tuple(value) != DEFAULT:
        if "radiation" in settings or "power_balance" in settings:
            fail("E_UNSUPPORTED", "방사 기록과 전력·손실 수지에는 여섯 면의 PML_8이 필요합니다.", field)
    return list(value)


def pml_cells(modes):
    """! @brief 흡수층이 있는 면의 실제 격자 구간 수를 반환한다."""
    return [8 if mode == "PML_8" else 0 for mode in modes]


def axis_info(modes, index, values):
    """! @brief PML 시작점과 흡수층이 없는 외곽면의 경계점을 반환한다."""
    pair = modes[index * 2:index * 2 + 2]
    low, high = pml_cells(pair)
    return pair, (low, high), [values[low], values[-1 - high]]
