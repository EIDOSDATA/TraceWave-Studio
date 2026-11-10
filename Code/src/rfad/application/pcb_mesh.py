"""! @brief PCB 내부 격자를 보존하고 경계 확장에 불변인 외부 공기 격자를 생성한다."""

from functools import lru_cache
import math

from rfad.domain.errors import ProjectError


def _fail(message, field="settings.mesh_policy"):
    """! @brief 지원하지 않는 수치 정책을 자동으로 바꾸지 않고 차단한다."""
    raise ProjectError("E_GEOMETRY", message, details={"field_path": field})


def validate_policy(settings):
    """! @brief 명시적 공기 cell/성장률과 정수 coarse-cell 경계 조건을 검사한다."""
    policy = settings["mesh_policy"]
    if type(policy) is not dict or set(policy) != {"kind", "air_cell_mm", "growth_ratio"} or policy["kind"] != "graded_air":
        _fail("mesh_policy는 graded_air와 air_cell_mm/growth_ratio가 필요합니다.")
    air, growth = policy["air_cell_mm"], policy["growth_ratio"]
    if type(air) not in (int, float) or not settings["grid_mm"] <= air <= 10:
        _fail("공기 cell은 grid_mm 이상 10 mm 이하여야 합니다.", "settings.mesh_policy.air_cell_mm")
    if type(growth) not in (int, float) or not 1.05 <= growth <= 1.5:
        _fail("공기 성장률은 1.05~1.5 범위여야 합니다.", "settings.mesh_policy.growth_ratio")
    count = settings["air_padding_mm"] / air
    if not math.isclose(count, round(count), rel_tol=0, abs_tol=1e-10) or count < 12:
        _fail("graded air padding은 공기 cell의 정수배이며 최소 12배여야 합니다.", "settings.air_padding_mm")
    frequency = settings["frequency_hz"]
    highest_excitation = 1.5 * (frequency["start"] + frequency["stop"]) / 2
    if air > 299792458.0 / highest_excitation * 1000 / 10:
        _fail("공기 cell은 Gaussian 여기 상한 주파수의 진공 파장/10 이하여야 합니다.", "settings.mesh_policy.air_cell_mm")


@lru_cache(maxsize=512)
def _transition(adjacent, offset, air, growth):
    """! @brief 마지막 cell이 air인 최소 개수의 bounded-growth 전이를 결정적으로 고른다.

    @details 각 cell의 성장률 제약은 선형 부등식이다. 가능한 최소/최대 수열의
    convex blend로 정확한 coarse lattice 접점까지 채우며 padding에는 의존하지 않는다.
    """
    best = None
    for coarse_cells in range(1, 33):
        distance = coarse_cells * air + offset
        for count in range(coarse_cells, 257):
            if best is not None and count - coarse_cells > best[0]:
                break
            minimum = [max(adjacent / growth, air / growth ** (count - 1 - i)) for i in range(count)]
            maximum = [min(air, adjacent * growth ** (i + 1)) for i in range(count)]
            if maximum[-1] != air or any(a > b + 1e-12 for a, b in zip(minimum, maximum)):
                continue
            low, high = math.fsum(minimum), math.fsum(maximum)
            if low > distance + 1e-12:
                break
            if high < distance - 1e-12:
                continue
            blend = (distance - low) / (high - low) if high > low else 0.0
            blend = min(1.0, max(0.0, blend))
            steps = tuple(a + blend * (b - a) for a, b in zip(minimum, maximum))
            candidate = (count - coarse_cells, coarse_cells, count, steps)
            if best is None or candidate[:3] < best[:3]:
                best = candidate
            break
    if best is None:
        _fail("공기 성장률과 계면 cell을 만족하는 유한 전이 격자를 만들 수 없습니다.")
    return best[1], best[3]


def graded_axis(interior, physical_bounds, padding, air, growth):
    """! @brief 기존 내부선과 실제 외면 기준 coarse lattice를 연결하고 고정 PML8을 보존한다."""
    if len(interior) < 2:
        _fail("graded air에는 두 개 이상의 내부 격자선이 필요합니다.")
    count = round(padding / air)
    additions = []
    for side, sign in ((0, -1), (1, 1)):
        anchor = interior[0] if side == 0 else interior[-1]
        adjacent = interior[1] - interior[0] if side == 0 else interior[-1] - interior[-2]
        physical = physical_bounds[side]
        offset = (physical - anchor) * sign
        if offset < -1e-9 or adjacent < 1e-4:
            _fail("공기 전이의 실제 외면 또는 최소 내부 cell이 유효하지 않습니다.")
        coarse_cells, steps = _transition(adjacent, max(0.0, offset), air, growth)
        if count < coarse_cells + 9:
            _fail("공기 전이 뒤에 고정 PML8과 한 개의 공기 cell이 필요합니다.", "settings.air_padding_mm")
        points = [round(anchor + sign * math.fsum(steps[:i]), 12) for i in range(1, len(steps) + 1)]
        # @brief 말단을 물리 외면 기준 lattice에 정확히 붙여 padding 변경에 좌표가 흔들리지 않게 한다.
        points[-1] = round(physical + sign * coarse_cells * air, 12)
        points.extend(round(physical + sign * i * air, 12) for i in range(coarse_cells + 1, count + 1))
        distances = [abs(points[0] - anchor)] + [abs(b - a) for a, b in zip(points, points[1:])]
        adjacent_steps = [adjacent, *distances]
        if (any(value <= 0 or value > air + 1e-9 for value in distances)
                or any(max(a / b, b / a) > growth + 1e-8 for a, b in zip(adjacent_steps, adjacent_steps[1:]))
                or any(not math.isclose(value, air, rel_tol=0, abs_tol=1e-9) for value in distances[-8:])):
            _fail("생성한 공기 격자의 실제 성장률 또는 PML cell 크기가 정책과 다릅니다.")
        additions.append(points)
    result = list(reversed(additions[0])) + interior + additions[1]
    if any(a >= b for a, b in zip(result, result[1:])):
        _fail("graded air 격자선이 엄격하게 증가하지 않습니다.")
    return result


def policy_report(case, lines):
    """! @brief 설정값과 실제 PML 위치/성장률을 별도로 기록한다."""
    settings = case["settings"]
    policy = settings["mesh_policy"]
    z = [value for layer in case["layers"] for value in (layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"])]
    physical = [*case["board"]["bounds_mm"], [min(z), max(z)]]
    dielectric_z = [value for layer in case["layers"] if layer["role"] == "dielectric"
                    for value in (layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"])]
    model_bounds = [*case["board"]["bounds_mm"], [min(dielectric_z), max(dielectric_z)]]
    axes = {}
    for axis, bounds, model in zip("xyz", physical, model_bounds):
        values = lines[axis]
        steps = [b - a for a, b in zip(values, values[1:])]
        lower = min(range(len(values)), key=lambda i: abs(values[i] - model[0]))
        upper = min(range(len(values)), key=lambda i: abs(values[i] - model[1]))
        air_pairs = list(zip(steps[:lower + 1], steps[1:lower + 1])) + list(zip(steps[upper - 1:], steps[upper:]))
        axes[axis] = {"physical_bounds_mm": bounds, "outer_boundary_mm": [values[0], values[-1]],
                      "pml_inner_boundary_mm": [values[8], values[-9]],
                      "pml_clearance_mm": [bounds[0] - values[8], values[-9] - bounds[1]],
                      "pml_cell_widths_mm": [steps[:8], steps[-8:]],
                      "axis_min_cell_mm": min(steps), "axis_max_cell_mm": max(steps),
                      "air_and_interface_max_adjacent_ratio": max(max(a / b, b / a) for a, b in air_pairs),
                      "axis_max_adjacent_ratio": max(max(a / b, b / a) for a, b in zip(steps, steps[1:]))}
    highest_excitation = case["excitation"]["center_hz"] + case["excitation"]["width_hz"]
    return {"schema": "rfad.pcb-mesh-policy/0.1", **policy, "padding_reference": "physical_board_outer_face_to_outer_boundary",
            "pml_cells_per_end": 8, "pml_thickness_mm": 8 * policy["air_cell_mm"], "padding_extension_preserves_common_lines": True,
            "air_growth_postcondition_checked": True, "interior_critical_intervals_unchanged": True,
            "interior_growth_postcondition_enforced": False,
            "highest_excitation_frequency_hz": highest_excitation, "vacuum_wavelength_mm": 299792458.0 / highest_excitation * 1000,
            "air_cells_per_minimum_wavelength": 299792458.0 / highest_excitation * 1000 / policy["air_cell_mm"], "axes": axes}
