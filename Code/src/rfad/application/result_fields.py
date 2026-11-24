"""! @brief 보존된 전기장 및 손실 필드의 실제 좌표와 유한 단면을 제공한다."""

from copy import deepcopy
import math

from rfad.adapters import field_hdf5
from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields
from rfad.application.pcb_field_probe import MAGNETIC_NAME, NAME as PROBE_NAME, REGION_SCHEMA, SCHEMA as PROBE_SCHEMA
from rfad.application.result_sources import validate_solver_artifact
from rfad.domain.errors import ProjectError


PROFILE = "rfad.result-field/0.1"
MAX_RESPONSE = 256 * 1024
MAX_PAGE = field_hdf5.MAX_ROI_POINTS
MONITORS = {
    "electric": ("pcb_loss_E.h5", "기록된 전기장 E 성분", "E", 0, "V*s/m"),
    "material_current": ("pcb_loss_J.h5", "기록된 재료 전류 J 성분", "J", 2, "A*s/m^2"),
    "total_current": ("pcb_loss_rotH.h5", "총 전류 rotH (원문 시간 위치)", "rotH", 3, "A*s/m^2"),
    "probe_electric": (PROBE_NAME, "지정 영역의 전기장 E", "E", 0, "V*s/m"),
    "probe_magnetic": (MAGNETIC_NAME, "지정 영역의 자기장 H", "H", 1, "A*s/m"),
}
WARNINGS = [
    "펄스 Fourier 원문 단위이며 연속파/실측 절대 전계가 아닙니다.",
    "원본 단면과 표본 마커는 각 성분의 실제 Yee 위치와 복소값을 표시합니다.",
    "재료 J는 native 재료 전류이며 sheet 경계의 전체 실제 전류를 뜻하지 않습니다.",
    "rotH의 원문 시간 위치를 유지합니다. 손실 적분의 시간/위상 보정은 적용하지 않았습니다.",
    "제작과 측정 조건 및 독립 물리 정확도는 미확립 상태입니다.",
]


def fail(message, code="E_SCHEMA"):
    """! @brief 조회 오류로 보고하고 새 계산이나 원문 보정을 수행하지 않는다."""
    raise ProjectError(code, message)


def _bounded(value):
    """! @brief 응답을 자르지 않고 유한 JSON 예산을 명시 검사한다."""
    if len(canonical_bytes(value)) > MAX_RESPONSE:
        fail("필드 응답 256 KiB 상한을 초과했습니다. ROI 또는 반환 점 수를 줄이십시오.", "E_RESOURCE")
    return value


def _base(resolved):
    """! @brief 계산하지 않고 선택한 source/pin과 원문 미검증 상태를 전달한다."""
    response = {"profile": PROFILE, "source": deepcopy(resolved["source"]), "pin": deepcopy(resolved["pin"]),
                "warnings": list(WARNINGS), "physics_validated": False}
    result = resolved.get("normalized") or {}
    plan = result.get("provenance", {}).get("analysis_plan", {})
    case = plan.get("case", {})
    probe = case.get("settings", {}).get("field_probe")
    if isinstance(probe, dict):
        response["requested_region_mm"] = {axis: deepcopy(probe[axis + "_mm"]) for axis in "xyz"
                                           if axis + "_mm" in probe}
    if "field_recording" in case and "port" in case:
        port = case["port"]
        response["drive_reference"] = {"analysis_plan_id": plan["plan_id"], "port_id": port["id"],
            "port_number": port["number"], "reference_plane": port["reference_plane"],
            "reference_impedance_ohm": port["resistance_ohm"], "excitation": deepcopy(case["excitation"]),
            "positive_geometry_id": port["positive_geometry_id"], "reference_geometry_id": port["reference_geometry_id"]}
    return response


def _model(resolved, monitor_id):
    """! @brief 선택한 모니터의 봉인 계획과 정규화 근거가 있을 때만 제공한다."""
    result, record = resolved.get("normalized"), resolved.get("solver_record")
    if result is None or record is None:
        return None
    plan = result.get("provenance", {}).get("analysis_plan", {})
    case = plan.get("case", {})
    magnetic = monitor_id == "probe_magnetic"
    if monitor_id in {"probe_electric", "probe_magnetic"}:
        recording = case.get("field_recording", {}).get("magnetic") if magnetic else case.get("field_recording")
        if recording is None:
            return None
        if (recording.get("schema") not in ((REGION_SCHEMA,) if magnetic else (REGION_SCHEMA, PROBE_SCHEMA)) or recording.get("dump_mode") != 0
                or recording.get("dump_type") != (11 if magnetic else 10)):
            fail("지정 E/H 필드와 봉인한 기록 계획이 다릅니다.", "E_UNSUPPORTED")
    else:
        recording = case.get("loss_recording")
        if recording is None:
            return None
        if (recording.get("schema") not in ("rfad.pcb-loss-recording/0.1", "rfad.pcb-loss-recording/0.2")
                or recording.get("dump_mode") != 0 or recording.get("dump_types") != [10, 12, 13]
                or result.get("power_balance", {}).get("recording") != recording):
            fail("필드 기록 계획과 원래 손실 기록 profile이 다릅니다.", "E_UNSUPPORTED")
    normalization = result.get("normalization", {})
    if (normalization.get("fourier_convention") != "exp(-j*2*pi*f*t)"
            or normalization.get("native_fourier_scale") != "2*dt*sum(value*exp(-j*2*pi*f*t))"):
        fail("필드의 원문 Fourier 단위/정규화 근거가 지원 profile과 다릅니다.", "E_UNSUPPORTED")
    # @brief 과거 격자를 현재 생성기로 재계산하지 않고 실제 보존된 전체 격자선을 읽는다.
    mesh = result.get("mesh_statistics", {})
    lines = mesh.get("lines_mm")
    if (mesh.get("native_length_unit") != "mm" or mesh.get("delta_unit_m") != 0.001
            or type(lines) is not dict or set(lines) != set("xyz")):
        fail("필드의 실제 전체 격자선/mm 단위가 보존되지 않아 좌표를 복원하지 않습니다.", "E_UNSUPPORTED")
    for axis in "xyz":
        values = lines[axis]
        if (type(values) is not list or not 2 <= len(values) <= 100000
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                or any(a >= b for a, b in zip(values, values[1:]))):
            fail("필드의 보존 격자선이 유한 증가 축이 아닙니다.", "E_HASH")
    starts, stops = recording.get("start_indices"), recording.get("stop_indices")
    frequencies = recording.get("frequency_hz")
    if (type(starts) is not list or type(stops) is not list or len(starts) != 3 or len(stops) != 3
            or type(frequencies) is not list or not 1 <= len(frequencies) <= 3
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in frequencies)
            or any(a >= b for a, b in zip(frequencies, frequencies[1:]))):
        fail("필드 기록의 유한 격자/주파수 선언이 유효하지 않습니다.", "E_HASH")
    mesh_axes, electric_nodes, shape, next_nodes = {}, {}, [], {}
    for axis, start, stop in zip("xyz", starts, stops):
        if type(start) is not int or type(stop) is not int or not 0 <= start <= stop < len(lines[axis])-1:
            fail("필드 기록의 성분 edge 범위가 계획 격자를 벗어납니다.", "E_HASH")
        source_axis = lines[axis]
        electric_nodes[axis] = source_axis[start:stop + 1]
        mesh_axes[axis] = ([(source_axis[i] + source_axis[i + 1]) * .5 for i in range(start, stop + 1)]
                           if magnetic else electric_nodes[axis])
        next_nodes[axis] = lines[axis][stop+1]
        shape.append(stop-start+1)
    for endpoint, index in (("start_mm", 0), ("stop_mm", -1)):
        recorded = recording.get(endpoint)
        if (type(recorded) is not list or len(recorded) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in recorded)
                or any(not math.isclose(value, mesh_axes[axis][index], rel_tol=0, abs_tol=1e-9)
                       for axis, value in zip("xyz", recorded))):
            fail("필드 기록 영역의 끝점이 실제 전체 격자와 다릅니다.", "E_HASH")
    return {"recording": recording, "shape": shape, "primary_coordinates_mm": mesh_axes,
            "magnetic": magnetic, "electric_nodes_mm": electric_nodes,
            "next_nodes_mm": next_nodes, "frequency_hz": frequencies, "normalization": normalization}


def _reference(resolved, monitor_id):
    """! @brief 해당 결과의 raw 목록과 manifest 양쪽에 동일하게 봉인된 모니터만 읽는다."""
    name = MONITORS[monitor_id][0]
    role = "raw/" + name
    record = resolved["solver_record"]
    matches = [item for item in record.get("raw_files", []) if item.get("role") == role]
    manifest = resolved["normalized"].get("raw_manifest", {})
    originals = [item for item in manifest.get("files", []) if item.get("role") == role]
    if len(matches) != 1 or len(originals) != 1 or manifest.get("complete") is not True:
        fail("해석 원문에 선택한 필드의 단일 봉인 파일이 없습니다.", "E_MISSING_ARTIFACT")
    item, original = matches[0], originals[0]
    reference = validate_solver_artifact(resolved["project"], record, item["artifact"])
    if (item["path"] != "output/" + role or reference["uri"].split("/")[-1] != name
            or any(item.get(key) != original.get(key) for key in ("path", "role", "sha256", "bytes"))
            or any(item.get(key) != reference.get(key) for key in ("sha256", "bytes"))):
        fail("필드 원문의 역할/이름/바이트/hash가 봉인 manifest와 다릅니다.", "E_HASH")
    return reference


def _read(service, resolved, model, monitor_id, selection=None):
    """! @brief 검증된 소유 reference와 journal 경로를 같은 파일 handle의 reader로 연결한다."""
    reference = _reference(resolved, monitor_id)
    with service.journal._mutex:
        service.journal._ensure_open()
        path = service.journal._safe_path(reference["uri"])
    expected = {"shape": model["shape"], "frequency_hz": model["frequency_hz"],
                "primary_coordinates_mm": model["primary_coordinates_mm"], "dump_type": MONITORS[monitor_id][3],
                "dual_mesh": int(model["magnetic"])}
    return field_hdf5.read(path, reference, expected, selection), reference


def _coordinates(model, primary, component):
    """! @brief 원문 primary 축과 봉인된 다음 격자선으로 실제 전기 edge 중심을 표시한다."""
    result = deepcopy(primary)
    if model.get("magnetic"):
        result[component] = list(model["electric_nodes_mm"][component])
        return result
    values = primary[component]
    following = values[1:] + [model["next_nodes_mm"][component]]
    result[component] = [(a+b)*0.5 for a, b in zip(values, following)]
    return result


def _coordinate(model, primary, axis, component, index):
    """! @brief 반환 ROI에 들어가는 원본 좌표만 성분의 실제 edge 위치로 변환한다."""
    values = primary[axis]
    position = values[index]
    if model.get("magnetic"):
        return model["electric_nodes_mm"][axis][index] if axis == component else position
    if axis == component and "next_nodes_mm" in model:
        following = values[index + 1] if index + 1 < len(values) else model["next_nodes_mm"][axis]
        return (position + following) * 0.5
    return position


def _basis(model):
    """! @brief 각 성분을 실제 전기 edge 또는 자기 dual edge에 배치한다."""
    return "dual_Yee_magnetic_edges" if model.get("magnetic") else "primary_Yee_electric_edge_midpoints"


def describe(service, resolved):
    """! @brief 실제 기록한 성분과 좌표만 열거하며 없는 모니터를 생성하지 않는다."""
    response = _base(resolved)
    response.update(status="unavailable", monitors=[])
    for monitor_id, (_, label, prefix, _, unit) in MONITORS.items():
        model = _model(resolved, monitor_id)
        if model is None:
            continue
        observed, reference = _read(service, resolved, model, monitor_id)
        components = [{"component": axis, "label": prefix + axis,
                       "coordinates_mm": _coordinates(model, observed["primary_coordinates_mm"], axis),
                       "shape": list(model["shape"])} for axis in "xyz"]
        response["monitors"].append({"monitor_id": monitor_id, "label": label, "unit": unit,
            "normalization": "pulse_fourier_spectrum_native_2dt", "frequency_hz": deepcopy(model["frequency_hz"]),
            "components": components, "source_ref": deepcopy(reference),
            "coordinate_basis": _basis(model), "phase_correction": "none_raw_time_location"})
    volume = [m for m in response["monitors"] if m["monitor_id"] in ("probe_electric", "probe_magnetic")]
    if len(volume) == 2 and volume[0]["frequency_hz"] == volume[1]["frequency_hz"]:
        from rfad.application.result_field_flux import common_bounds

        bounds = common_bounds([c["coordinates_mm"] for m in volume for c in m["components"]])
        if bounds is not None:
            response["flux_bounds_mm"] = bounds
    if response["monitors"]:
        response["status"] = "available"
        if all(item["monitor_id"].startswith("probe_") for item in response["monitors"]):
            response["warnings"] = [WARNINGS[index] for index in (0, 1, 4)]
        if any(item["monitor_id"] == "probe_magnetic" for item in response["monitors"]):
            response["warnings"].append("자기장 H는 같은 급전에서 기록한 dual Yee 성분의 원래 시간 위상을 사용합니다.")
    else:
        response["warnings"].insert(0, "선택한 원본에는 지원하는 내부 복소 필드가 기록되지 않았습니다.")
    return _bounded(response)


def _selection(model, parameters, monitors=MONITORS):
    """! @brief 원본 구간과 stride를 명시하고 최대4096표본을 계산 전에 제한한다."""
    _fields(parameters, {"monitor_id", "frequency_index", "component", "plane", "roi", "stride"})
    if (type(parameters["monitor_id"]) is not str or parameters["monitor_id"] not in monitors
            or parameters["component"] not in ("x", "y", "z")):
        fail("지원하지 않는 필드 모니터 또는 성분입니다.")
    _fields(parameters["plane"], {"normal_axis", "index"})
    _fields(parameters["roi"], {"u_start", "u_count", "v_start", "v_count"})
    normal = parameters["plane"]["normal_axis"]
    index, frequency, stride = parameters["plane"]["index"], parameters["frequency_index"], parameters["stride"]
    if (normal not in ("x", "y", "z") or type(index) is not int or index < 0
            or type(frequency) is not int or not 0 <= frequency < len(model["frequency_hz"])
            or type(stride) is not int or not 1 <= stride <= 100000):
        fail("필드 단면/주파수/stride 인덱스가 유효하지 않습니다.")
    if index >= model["shape"]["xyz".index(normal)]:
        fail("필드 단면 인덱스가 실제 기록 범위를 벗어났습니다.")
    axes = [axis for axis in "xyz" if axis != normal]
    selection = {"component_index": "xyz".index(parameters["component"]), "frequency_index": frequency, normal: index}
    indices = []
    for label, axis in zip("uv", axes):
        start, count = parameters["roi"][label+"_start"], parameters["roi"][label+"_count"]
        if (type(start) is not int or type(count) is not int or start < 0 or count < 1
                or start+count > model["shape"]["xyz".index(axis)]):
            fail("필드 ROI가 실제 원문 격자를 벗어났습니다.")
        selection[axis] = slice(start, start+count, stride)
        indices.append(range(start, start+count, stride))
    if len(indices[0])*len(indices[1]) > MAX_PAGE:
        fail("필드 한 응답의 최대4096표본을 초과했습니다.", "E_RESOURCE")
    return axes, selection, [list(axis) for axis in indices]


def page(service, resolved, parameters):
    """! @brief 실제 단면의 복소값/크기/위상을 보존하고 색만 현재 반환 타일에 대응한다."""
    monitor = parameters.get("monitor_id")
    if type(monitor) is not str or monitor not in MONITORS:
        fail("지원하지 않는 필드 모니터입니다.")
    model = _model(resolved, monitor)
    if model is None:
        fail("선택한 원본에 표시할 복소 필드가 없습니다.", "E_MISSING_ARTIFACT")
    axes, selection, indices = _selection(model, parameters)
    observed, reference = _read(service, resolved, model, parameters["monitor_id"], selection)
    response = _base(resolved)
    if monitor.startswith("probe_"):
        response["warnings"] = [WARNINGS[index] for index in (0, 1, 4)]
    return present_page(response, model, observed["primary_coordinates_mm"], observed["values"],
                        reference, parameters, axes, indices, unit=MONITORS[parameters["monitor_id"]][4],
                        normalization="pulse_fourier_spectrum_native_2dt",
                        coordinate_basis=_basis(model))


def present_page(response, model, coordinates, raw_values, reference, parameters, axes, indices, *,
                 unit, normalization, coordinate_basis):
    """! @brief 외부 원문과 계산 기록은 각자의 좌표 및 단위 선언을 사용한다."""
    component = parameters["component"]
    normal = parameters["plane"]["normal_axis"]
    values, magnitudes, phases, states = [], [], [], []
    maximum = 0.0
    for row in raw_values:
        vr, mr, pr, sr = [], [], [], []
        for value in row:
            real, imag = float(value.real), float(value.imag)
            if not math.isfinite(real) or not math.isfinite(imag):
                vr.append(None); mr.append(None); pr.append(None); sr.append("nonfinite")
                continue
            magnitude = math.hypot(real, imag)
            maximum = max(maximum, magnitude)
            vr.append([real, imag]); mr.append(magnitude)
            pr.append(math.degrees(math.atan2(imag, real)) if magnitude else None)
            sr.append("valid" if magnitude else "zero_magnitude_phase_undefined")
        values.append(vr); magnitudes.append(mr); phases.append(pr); states.append(sr)
    response.update(selection=deepcopy(parameters), u_axis=axes[0], v_axis=axes[1],
        normal_position_mm=_coordinate(model, coordinates, normal, component, parameters["plane"]["index"]),
        u_indices=indices[0], v_indices=indices[1],
        u_coordinates_mm=[_coordinate(model, coordinates, axes[0], component, i) for i in indices[0]],
        v_coordinates_mm=[_coordinate(model, coordinates, axes[1], component, i) for i in indices[1]],
        values_ri=values, magnitude=magnitudes,
        phase_deg=phases, state=states, color=deepcopy(magnitudes), color_range=[0.0, maximum],
        color_scope="returned_page_magnitude", unit=unit,
        normalization=normalization, phase_correction="none_raw_time_location",
        frequency_hz=model["frequency_hz"][parameters["frequency_index"]], source_ref=deepcopy(reference),
        coordinate_basis=coordinate_basis, interpolation="none")
    return _bounded(response)
