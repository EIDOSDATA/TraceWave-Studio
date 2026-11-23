"""! @brief 원시 네트워크를 바꾸지 않는 명시 변환과 조건 일치 검사를 제공한다."""

import cmath
from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash
from rfad.adapters import network_backend
from rfad.domain.network_data import UNITS, complex_value, fail, finite, is_named_mode, text, validate_dataset


def require_basis(data, *, phasor=False, waveguide=False):
    """! @brief 모르는 파/포트/기준면 조건을 50 ohm 또는 동일 기준으로 치환하지 않는다."""
    modes = {"single_ended", "rectangular_te10"} if waveguide else {"single_ended"}
    if data["wave_definition"] == "unknown" or any(value not in modes and not (waveguide and is_named_mode(value)) for value in data["port_modes"]):
        fail("파 정의와 단일종단 포트 모드를 명시하십시오.", "wave_definition", "E_UNSUPPORTED")
    if any(value != "into_dut" for value in data["current_orientation"]):
        fail("DUT 안쪽을 향하는 전류 규약을 명시하십시오.", "current_orientation", "E_UNSUPPORTED")
    if any(value is None for value in data["reference_planes"]):
        fail("기준면이 미정입니다. 조건을 명시적으로 확인하십시오.", "reference_planes", "E_CONFLICT")
    if phasor and data["phasor_convention"] == "unknown":
        fail("RLC 결합에는 시간/위상 부호 규약이 필요합니다.", "phasor_convention", "E_UNSUPPORTED")


def real_references(data, index):
    """! @brief R1의 양의 실수 기준 임피던스만 계산하며 복소/미정 원본은 보존한다."""
    if data["z0_ohm"] is None:
        fail("기준 임피던스가 미정입니다.", "z0_ohm", "E_CONFLICT")
    result = []
    for value in data["z0_ohm"][index]:
        if value is None:
            fail("기준 임피던스가 미정입니다.", "z0_ohm", "E_CONFLICT")
        impedance = complex_value(value, "z0_ohm")
        if impedance.imag != 0 or impedance.real <= 0:
            fail("현재 변환은 양의 실수 Z0만 지원합니다. 복소 Z0를 버리지 않습니다.", "z0_ohm", "E_UNSUPPORTED")
        result.append(impedance.real)
    return result


def derived(data, values, masks, statuses, options, engine, *, kind=None, z0=None, planes=None):
    """! @brief 입력 해시와 원래 표본 종류를 남기며 별도 결과 사본을 만든다."""
    result = deepcopy(data)
    kind = data["parameter_kind"] if kind is None else kind
    result.update(parameter_kind=kind, unit=UNITS[kind], values_ri=values, valid_mask=masks, sample_status=statuses,
                  sample_origin=["derived"] * len(values))
    if z0 is not None:
        result["z0_ohm"] = deepcopy(z0)
    if planes is not None:
        result["reference_planes"] = list(planes)
    operations = result["provenance"].setdefault("network_operations", [])
    if type(operations) is not list or len(operations) >= 32:
        fail("파생 연산의 출처 상한을 초과했습니다.", "provenance", "E_RESOURCE")
    operations.append({"input_hash": canonical_hash(data), "options": deepcopy(options), "engine": deepcopy(engine),
                       "source_sample_origin": list(data["sample_origin"])})
    validate_dataset(result)
    return result


def _segment_length(segment):
    """! @brief 선로 축의 두 점과 바깥 방향으로부터 부호 있는 mm 거리를 산출한다."""
    field = "options.lines.segment"
    names = ("from_mm", "to_mm", "outward")
    if type(segment) is not dict or set(segment) != set(names):
        fail("현재 점, 새 점과 바깥 방향의 XYZ를 입력하십시오.", field, "E_SCHEMA")
    vectors = []
    for name in names:
        values = segment[name]
        if type(values) is not list or len(values) != 3:
            fail("XYZ 세 수치가 필요합니다.", f"{field}.{name}", "E_SCHEMA")
        vector = [finite(item, f"{field}.{name}") for item in values]
        if max(map(abs, vector)) > 1e6:
            fail("기준면 좌표·방향 성분이 입력 상한을 넘었습니다.", f"{field}.{name}", "E_RESOURCE")
        vectors.append(vector)
    start, stop, direction = vectors
    magnitude = math.hypot(*direction)
    if not magnitude:
        fail("바깥 방향은 영벡터일 수 없습니다.", f"{field}.outward", "E_GEOMETRY")
    unit = [component / magnitude for component in direction]
    displacement = [b - a for a, b in zip(start, stop)]
    distance = math.fsum(value * axis for value, axis in zip(displacement, unit))
    transverse = math.hypot(*(value - distance * axis for value, axis in zip(displacement, unit)))
    if transverse > max(1e-9, 1e-9 * abs(distance)):
        fail("새 기준면의 점은 같은 정합 선로 축 위에 있어야 합니다.", f"{field}.to_mm", "E_GEOMETRY")
    return distance


def _guide_factors(guide, length, frequencies, sign):
    """! @brief 균질 비자성 직사각 도파관의 단일 전파 모드에서 위상과 TE 임피던스를 구한다."""
    if type(guide) is not dict or set(guide) != {"width_mm", "height_mm", "epsilon_r"}:
        fail("TE10 도파관의 내폭, 내높이와 상대 유전율이 필요합니다.", "options.lines.waveguide")
    a, b, epsilon = [finite(guide[k], "options.lines.waveguide." + k) for k in ("width_mm", "height_mm", "epsilon_r")]
    if not 0 < b < a or not 1 <= epsilon <= 100:
        fail("도파관은 양수 내높이보다 큰 내폭과 1~100의 상대 유전율이 필요합니다.", "options.lines.waveguide", "E_UNIT")
    velocity = 299792458.0 / math.sqrt(epsilon)
    cutoff = 500 * velocity / a
    limit = min(2 * cutoff, 500 * velocity / b)
    factors = []
    for f in frequencies:
        if not cutoff < f < limit:
            fail("모든 표본이 TE10 차단 주파수와 다음 모드의 차단 주파수 사이에 있어야 합니다.",
                 "options.lines.waveguide", "E_UNSUPPORTED")
        ratio = cutoff / f
        normal = math.sqrt((1 - ratio) * (1 + ratio))
        cycles = (f / velocity) * normal * length
        if not math.isfinite(cycles) or abs(cycles) > 5e7:
            fail("도파관 기준면의 위상이 계산 범위를 넘었습니다.", "options.lines", "E_RESOURCE")
        impedance = 376.730313668 / (math.sqrt(epsilon) * normal)
        factors.append((cmath.exp(complex(0, sign * math.tau * math.remainder(cycles, 1))), impedance))
    return factors


def _shift_planes(data, options):
    """! @brief 포트별 정합 선로를 더하거나 제거하여 S 파의 기준면을 이동한다."""
    if set(options) != {"operation", "lines"} or data["parameter_kind"] != "S":
        fail("정합 선로 기준면 이동에는 S 자료와 선로 조건이 필요합니다.", "options", "E_UNSUPPORTED")
    require_basis(data, waveguide=True)
    if data["phasor_convention"] == "unknown":
        fail("기준면을 이동하려면 시간/위상 부호 규약이 필요합니다.", "phasor_convention", "E_UNSUPPORTED")
    port_ids = data["port_ids"]
    lines = options["lines"]
    if type(lines) is not list or not 1 <= len(lines) <= len(port_ids):
        fail("이동할 포트마다 하나의 정합 선로를 지정하십시오.", "options.lines")
    planes = list(data["reference_planes"])
    delays, log_gains = [0.0] * len(planes), [0.0] * len(planes)
    guides, tables = {}, {}
    sign = -1.0 if data["phasor_convention"] == "exp(+j*omega*t)" else 1.0
    used = set()
    fields = {"port_id", "phase_velocity_m_per_s", "attenuation_db_per_m", "reference_plane"}
    coordinate_lengths = {}
    for line in lines:
        guide_line = isinstance(line, dict) and "waveguide" in line
        modal_line = isinstance(line, dict) and "modal" in line
        expected = {"port_id", "reference_plane", "waveguide"} if guide_line else fields
        if modal_line:
            expected = {"port_id", "reference_plane", "modal"}
        if type(line) is not dict or set(line) not in (expected | {"length_mm"}, expected | {"segment"}):
            fail("포트, 길이, 전파 속도, 감쇠와 새 기준면을 입력하십시오.", "options.lines")
        identity = line["port_id"]
        if type(identity) is not str or identity not in port_ids or identity in used:
            fail("현재 자료의 서로 다른 포트를 선택하십시오.", "options.lines.port_id")
        used.add(identity)
        index = port_ids.index(identity)
        if "segment" in line:
            length_mm = _segment_length(line["segment"])
            coordinate_lengths[identity] = length_mm
        else:
            length_mm = finite(line["length_mm"], "options.lines.length_mm")
        length = length_mm * 1e-3
        new_plane = line["reference_plane"]
        text(new_plane, "options.lines.reference_plane", limit=256)
        if not length or new_plane == planes[index]:
            fail("0이 아닌 이동 길이와 다른 기준면 이름이 필요합니다.", "options.lines", "E_UNIT")
        if modal_line:
            from rfad.domain.network_modal import factors as modal_factors

            tables[index] = line["modal"]
            guides[index] = modal_factors(line["modal"], data, index, length, sign)
            planes[index] = new_plane
            continue
        if is_named_mode(data["port_modes"][index]):
            fail("이름 있는 단일 전파 모드에는 해당 모드의 분산 표가 필요합니다.", "options.lines.modal", "E_CONFLICT")
        if guide_line:
            if data["port_modes"][index] != "rectangular_te10":
                fail("포트 모드를 직사각 도파관 TE10으로 확인한 자료가 필요합니다.", "port_modes", "E_CONFLICT")
            guides[index] = _guide_factors(line["waveguide"], length, data["frequency_hz"], sign)
            planes[index] = new_plane
            continue
        if data["port_modes"][index] == "rectangular_te10":
            fail("TE10 모드의 기준면에는 도파관 단면을 지정하십시오.", "options.lines.waveguide", "E_UNSUPPORTED")
        velocity = finite(line["phase_velocity_m_per_s"], "options.lines.phase_velocity_m_per_s")
        loss = finite(line["attenuation_db_per_m"], "options.lines.attenuation_db_per_m")
        if velocity <= 0 or loss < 0:
            fail("0 아닌 길이, 양의 위상 속도, 0 이상의 감쇠와 다른 기준면 이름이 필요합니다.", "options.lines", "E_UNIT")
        delay = length / velocity
        gain = -loss * (math.log(10) / 20) * length
        if abs(delay) * max(data["frequency_hz"]) > 5e7 or abs(gain) > 300:
            fail("정합 선로의 위상 또는 감쇠가 계산 범위를 넘었습니다.", "options.lines", "E_RESOURCE")
        planes[index], delays[index], log_gains[index] = new_plane, delay, gain

    values, diagnostics = [], []
    for index, frequency in enumerate(data["frequency_hz"]):
        references = real_references(data, index)
        factors = [cmath.exp(complex(gain, sign * math.tau * math.remainder(frequency * delay, 1.0)))
                   for gain, delay in zip(log_gains, delays)]
        for port, rows in guides.items():
            factor, impedance = rows[index]
            if not math.isclose(references[port], impedance, rel_tol=1e-8 if port in tables else 1e-5):
                fail("주파수별 포트 기준 임피던스가 지정한 정합 모드 임피던스와 다릅니다.",
                     "z0_ohm", "E_CONFLICT")
            factors[port] = factor
        matrix = []
        for i, row in enumerate(data["values_ri"][index]):
            converted = []
            for j, sample in enumerate(row):
                if not data["valid_mask"][index][i][j]:
                    converted.append(None)
                    continue
                value = complex_value(sample, "values_ri") * (factors[i] * factors[j])
                if not (math.isfinite(value.real) and math.isfinite(value.imag)):
                    fail("정합 선로 이동 결과의 복소 크기가 표현 범위를 넘었습니다.", "values_ri", "E_RESOURCE")
                converted.append([value.real, value.imag])
            matrix.append(converted)
        values.append(matrix)
        count = sum(sum(row) for row in data["valid_mask"][index])
        diagnostics.append({"frequency_hz": frequency, "status": "valid" if count == len(planes)**2 else "missing",
                            "valid_channels": count, "operation": "shift_plane"})
        if tables:
            diagnostics[-1]["modal_samples"] = [{"port_id": port_ids[p], "mode": table["mode"],
                "frequency_hz": table["samples"][index][0], "alpha_np_per_m": table["samples"][index][1],
                "beta_rad_per_m": table["samples"][index][2],
                "mode_impedance_ohm": table["samples"][index][3]} for p, table in tables.items()]
    engine = {"name": "rfad.matched-line-reference", "version": "0.1", "available": True}
    evidence = {**options, "source_reference_planes": data["reference_planes"], "matched_to_port_z0": True}
    if tables:
        evidence["lines"] = []
        for line in lines:
            if "modal" not in line:
                evidence["lines"].append(deepcopy(line))
                continue
            table = line["modal"]
            evidence["lines"].append({**line, "modal": {**{k: v for k, v in table.items() if k != "samples"},
                "samples_sha256": canonical_hash(table["samples"]), "sample_count": len(table["samples"]),
                "sample_source": "diagnostics.modal_samples"}})
    if coordinate_lengths:
        evidence["coordinate_lengths_mm"] = coordinate_lengths
    return {"dataset": derived(data, values, data["valid_mask"], data["sample_status"], evidence, engine, planes=planes),
            "diagnostics": diagnostics, "engine": engine}


def _deembed_fixtures(data, options):
    """! @brief 표시된 두 기준면의 치구를 동일 주파수의 결합 S행렬에서 제거한다."""
    if set(options) != {"operation", "left", "right", "fixture_ids"}:
        fail("왼쪽과 오른쪽 치구의 봉인 자료가 필요합니다.", "options", "E_SCHEMA")
    left, right = options["left"], options["right"]
    networks = (left, data, right)
    for item in networks:
        validate_dataset(item)
        require_basis(item)
        if item["parameter_kind"] != "S" or len(item["port_ids"]) != 2:
            fail("결합 자료와 양쪽 치구에 모두 단일종단 2포트 S 자료가 필요합니다.", "options", "E_UNSUPPORTED")
        if item["frequency_hz"] != data["frequency_hz"]:
            fail("세 자료의 주파수 축이 정확히 같아야 합니다.", "frequency_hz", "E_CONFLICT")
        if (item["phasor_convention"] == "unknown" or item["phasor_convention"] != data["phasor_convention"]
                or item["wave_definition"] != data["wave_definition"]):
            fail("세 자료의 파 정의와 시간/위상 규약이 같아야 합니다.", "options", "E_CONFLICT")
    if [left["reference_planes"][0], right["reference_planes"][1]] != data["reference_planes"]:
        fail("왼쪽 치구의 포트 1과 오른쪽 치구의 포트 2를 결합 자료의 바깥 기준면에 맞추십시오.",
             "reference_planes", "E_CONFLICT")
    planes = [left["reference_planes"][1], right["reference_planes"][0]]
    engine = network_backend.runtime()[3]
    values, masks, statuses, diagnostics = [], [], [], []
    for index, frequency in enumerate(data["frequency_hz"]):
        reference, other = real_references(data, index)
        if reference != other or any(real_references(item, index) != [reference, reference] for item in (left, right)):
            fail("각 주파수의 양의 실수 Z0가 세 자료의 모든 포트에서 같아야 합니다.", "z0_ohm", "E_CONFLICT")
        missing = [label for label, item in zip(("left", "combined", "right"), networks)
                   if not all(value for row in item["valid_mask"][index] for value in row)]
        if missing:
            result, diagnostic = None, {"status": "missing", "missing_inputs": missing}
        else:
            matrix = [[[complex_value(sample, "values_ri") for sample in row] for row in item["values_ri"][index]]
                      for item in networks]
            result, diagnostic = network_backend.remove_two_port_fixtures(*matrix)
        valid = result is not None
        values.append([[[float(value.real), float(value.imag)] for value in row] for row in result]
                      if valid else [[None, None], [None, None]])
        masks.append([[valid] * 2 for _ in range(2)])
        statuses.append([[diagnostic["status"]] * 2 for _ in range(2)])
        diagnostics.append({"frequency_hz": frequency, **diagnostic})
    evidence = {"operation": "deembed_fixtures", "fixture_ids": options["fixture_ids"],
                "fixture_sha256": {"left": canonical_hash(left), "right": canonical_hash(right)},
                "source_reference_planes": data["reference_planes"], "reference_planes": planes,
                "port_order": {"left": ["outside", "inside"], "right": ["inside", "outside"]}}
    return {"dataset": derived(data, values, masks, statuses, evidence, engine, planes=planes),
            "diagnostics": diagnostics, "engine": engine}


def _time_gate(data, options):
    """! @brief 균일 복소 대역의 IFFT 지연 표본을 선택해서 같은 주파수로 돌아간다."""
    if set(options) != {"operation", "start_ns", "stop_ns"} or data["parameter_kind"] != "S":
        fail("시간 게이트에는 S 자료와 시작·끝 지연 시간이 필요합니다.", "options", "E_UNSUPPORTED")
    require_basis(data)
    if data["phasor_convention"] == "unknown":
        fail("시간 게이트에는 시간/위상 부호 규약이 필요합니다.", "phasor_convention", "E_UNSUPPORTED")
    frequencies = data["frequency_hz"]
    count = len(frequencies)
    if count < 4:
        fail("시간 게이트에는 균일한 주파수 표본 4개 이상이 필요합니다.", "frequency_hz", "E_CONFLICT")
    start, stop = [finite(options[key], "options." + key) for key in ("start_ns", "stop_ns")]
    step = (frequencies[-1] - frequencies[0]) / (count - 1)
    tolerance = max(4 * math.ulp(frequencies[-1]), step * 1e-10)
    if tolerance >= step / 100 or any(abs(right - left - step) > tolerance for left, right in zip(frequencies, frequencies[1:])):
        fail("시간 게이트에는 균일한 원본 주파수 축이 필요합니다.", "frequency_hz", "E_CONFLICT")
    period_ns = 1e9 / step
    if not math.isfinite(period_ns):
        fail("주파수 간격으로 시간 주기를 표현할 수 없습니다.", "frequency_hz", "E_RESOURCE")
    if not -period_ns / 2 <= start < stop <= period_ns / 2:
        fail(f"게이트 시작과 끝을 {-period_ns / 2:.6g}~{period_ns / 2:.6g} ns 안에서 순서대로 지정하십시오.",
             "options.start_ns", "E_CONFLICT")
    reference = real_references(data, 0)
    for index, mask in enumerate(data["valid_mask"]):
        if not all(value for row in mask for value in row):
            fail("누락 또는 특이 표본을 보간하지 않습니다. 모든 복소 값이 필요합니다.", "valid_mask", "E_CONFLICT")
        if real_references(data, index) != reference:
            fail("시간 게이트에서는 각 포트의 기준 임피던스가 주파수에 따라 일정해야 합니다.", "z0_ohm", "E_CONFLICT")
    np, _, _, engine = network_backend.runtime()
    data_ri = np.asarray(data["values_ri"], dtype=float)
    matrix = data_ri[..., 0] + 1j * data_ri[..., 1]
    offsets = np.fft.fftshift(np.fft.fftfreq(count, d=step)) * 1e9
    selected = (start <= offsets) & (offsets <= stop)
    retained = int(np.count_nonzero(selected))
    if not retained:
        fail(f"선택한 구간에 지연 표본이 없습니다. 표본 간격은 {period_ns / count:.6g} ns입니다.",
             "options.start_ns", "E_CONFLICT")
    positive = data["phasor_convention"] == "exp(+j*omega*t)"
    with np.errstate(over="ignore", invalid="ignore"):
        response = np.fft.ifft(matrix, axis=0) if positive else np.fft.fft(matrix, axis=0) / count
        shifted = np.fft.fftshift(response, axes=0)
        cropped = np.fft.ifftshift(np.where(selected[:, None, None], shifted, 0), axes=0)
        result = np.fft.fft(cropped, axis=0) if positive else np.fft.ifft(cropped, axis=0) * count
    if not np.isfinite(response).all() or not np.isfinite(result).all():
        fail("시간 게이트 결과가 유한한 복소 범위를 넘습니다.", "values_ri", "E_RESOURCE")
    values = np.stack((result.real, result.imag), axis=-1).tolist()
    selected_range = (float(offsets[selected][0]), float(offsets[selected][-1]))
    details = {"method": "complex_bandpass_rectangular_gate", "retained_bins": retained, "total_bins": count,
               "time_step_ns": period_ns / count, "period_ns": period_ns, "selected_bin_range_ns": list(selected_range)}
    evidence = {**options, **details, "frequency_spacing_hz": step, "source_band_start_hz": frequencies[0]}
    return {"dataset": derived(data, values, data["valid_mask"], data["sample_status"], evidence, engine),
            "diagnostics": [{"frequency_hz": f, "status": "valid", **details} for f in frequencies],
            "engine": engine}


def transform_dataset(data, options):
    """! @brief 고정 주파수의 명시 S/Z/Y 변환, Z0 재정규화 또는 정합 선로 기준면 이동을 수행한다."""
    validate_dataset(data)
    if type(options) is dict:
        if options.get("operation") == "shift_plane":
            return _shift_planes(data, options)
        if options.get("operation") == "deembed_fixtures":
            return _deembed_fixtures(data, options)
        if options.get("operation") == "time_gate":
            return _time_gate(data, options)
    if type(options) is not dict or options.get("operation") not in ("convert", "renormalize"):
        fail("지원하지 않는 네트워크 변환입니다.", "options", "E_UNSUPPORTED")
    renormalize = options["operation"] == "renormalize"
    if set(options) != ({"operation", "z0_ohm"} if renormalize else {"operation", "parameter_kind"}):
        fail("변환 입력 필드가 다릅니다.", "options")
    target = "S" if renormalize else options["parameter_kind"]
    if type(target) is not str or target not in UNITS or (renormalize and data["parameter_kind"] != "S"):
        fail("Z0 재정규화 입력은 S이며 변환 종류는 S/Z/Y여야 합니다.", "options", "E_UNSUPPORTED")
    require_basis(data)
    target_data = deepcopy(data)
    if renormalize:
        target_data["z0_ohm"] = deepcopy(options["z0_ohm"])
        validate_dataset(target_data)
    values, masks, statuses, diagnostics = [], [], [], []
    ports = len(data["port_ids"])
    engine = network_backend.runtime()[3]
    for index, frequency in enumerate(data["frequency_hz"]):
        old_z0, new_z0 = real_references(data, index), real_references(target_data, index)
        matrix = data["values_ri"][index]
        if not all(value for row in data["valid_mask"][index] for value in row):
            result, diagnostic = None, {"status": "missing", "condition_number": None, "relative_residual": None}
        else:
            matrix = [[complex_value(value, "values_ri") for value in row] for row in matrix]
            result, diagnostic, _ = network_backend.convert(matrix, data["parameter_kind"], "Z" if renormalize else target, old_z0)
            if renormalize and result is not None:
                result, second, _ = network_backend.convert(result, "Z", "S", new_z0)
                diagnostic = {**second, "first_conversion": diagnostic}
        valid = result is not None
        values.append([[[float(value.real), float(value.imag)] for value in row] for row in result] if valid else [[None] * ports for _ in range(ports)])
        masks.append([[valid] * ports for _ in range(ports)])
        statuses.append([[diagnostic["status"]] * ports for _ in range(ports)])
        diagnostics.append({"frequency_hz": frequency, **diagnostic})
    return {"dataset": derived(data, values, masks, statuses, options, engine, kind=target,
                               z0=options["z0_ohm"] if renormalize else None), "diagnostics": diagnostics, "engine": engine}
