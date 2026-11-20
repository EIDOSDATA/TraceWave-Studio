"""! @brief 등록 결과의 고정 HDF5 프로필과 유한 단면/곡선 조회를 제공한다."""

from contextlib import contextmanager
import json
import math

from rfad.adapters import field_hdf5
from rfad.adapters.network_hdf5 import SIGNATURE, _constant, _dataset, _runtime, _unique
from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields
from rfad.domain.errors import ProjectError
from rfad.storage.indexed_result_file import IndexedReader, regular_file


TRACE_PROFILE = "rfad.large-complex-traces/0.1"
MAX_FIELD_BYTES = 1056 * 1024**2
MAX_AXIS_POINTS = 4096
MAX_TRACE_BYTES = 32 * 1024**2
MAX_TRACES = 8
MAX_SAMPLES = 100_000
MAX_TRACE_PAGE = 201
MAX_BUCKETS = 64


@contextmanager
def opened(path, index):
    """! @brief 봉인한 파일의 검증된 구간만 고정 HDF5 런타임에 노출한다."""
    h5py, np = _runtime()
    try:
        with regular_file(path) as (stream, size), IndexedReader(stream, size, index) as reader:
            if reader.read(8) != SIGNATURE:
                raise ProjectError("E_UNSUPPORTED", "대용량 결과의 HDF5 파일 서명이 다릅니다.")
            reader.seek(0)
            with h5py.File(reader, "r", rdcc_nbytes=1024**2) as handle:
                if handle.userblock_size:
                    raise ProjectError("E_UNSUPPORTED", "HDF5 user block을 지원하지 않습니다.")
                yield handle, h5py, np
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, OverflowError, RecursionError) as error:
        raise ProjectError("E_HASH", "대용량 HDF5의 구조 또는 읽기 구간을 확인할 수 없습니다.") from error


def field_layout(handle, h5py, np):
    """! @brief 외부 필드 축의 존재와 크기를 확인한 뒤 원문 좌표로 검증 선언을 구성한다."""
    child = field_hdf5._child
    if len(handle) != 2 or set(handle) != {"Mesh", "FieldData"}:
        field_hdf5.fail("외부 필드는 primary Yee openEMS 복소 HDF5 형식이어야 합니다.")
    seen = [handle.id]
    mesh = child(handle, "Mesh", h5py, seen, True)
    if len(mesh) != 3 or set(mesh) != set("xyz"):
        field_hdf5.fail("외부 필드의 직교 격자 축이 다릅니다.")
    axes = {axis: child(mesh, axis, h5py, seen) for axis in "xyz"}
    if (any(values.ndim != 1 or values.dtype.str != "<f8" or values.dtype.metadata
            or values.size < 1 for values in axes.values())
            or sum(values.size for values in axes.values()) > MAX_AXIS_POINTS):
        field_hdf5.fail("외부 필드의 좌표는 float64이며 합계 최대 4096개입니다.", "E_RESOURCE")
    fields = child(handle, "FieldData", h5py, seen, True)
    fd = child(fields, "FD", h5py, seen, True)
    if not 1 <= len(fd) <= 3:
        field_hdf5.fail("외부 필드는 1~3개 기록 주파수를 지원합니다.", "E_RESOURCE")
    frequencies = field_hdf5._attribute(fd, "frequency", np, (len(fd),)).tolist()
    if any(freq <= 0 for freq in frequencies) or any(x >= y for x, y in zip(frequencies, frequencies[1:])):
        field_hdf5.fail("기록 주파수는 유한 양수이며 증가해야 합니다.")
    dump_type = field_hdf5._attribute(handle, "dump_type", np).item()
    if dump_type not in (0, 2, 3):
        field_hdf5.fail("외부 필드는 E, J, rotH 기록을 지원합니다.")
    if any(not np.all(np.isfinite(values[...])) for values in axes.values()):
        field_hdf5.fail("외부 필드에 유한하지 않은 격자 좌표가 있습니다.", "E_HASH")
    return {"shape": [value.size for value in axes.values()], "frequency_hz": frequencies,
            "dump_type": dump_type, "primary_coordinates_mm": {
                axis: (values[...] * 1000).tolist() for axis, values in axes.items()}}


def field_data(handle, h5py, np, layout):
    """! @brief 대용량 외부 역할에만 확장한 바이트 예산을 적용한다."""
    return field_hdf5.inspect(handle, h5py, np, layout,
                              max_points=MAX_FIELD_BYTES // 24, max_bytes=MAX_FIELD_BYTES)[0]


def traces(handle, h5py, np, *, verify_samples=False):
    """! @brief 배열을 한 번에 펼치지 않고 고정 레이아웃과 유효 마스크를 검사한다."""
    if len(handle) != 2 or set(handle) != {"metadata_json", "traces"} or len(handle.attrs):
        raise ProjectError("E_UNSUPPORTED", "복소 곡선 파일의 HDF5 레이아웃이 다릅니다.")
    metadata = _dataset(handle, "metadata_json", h5py, dtype="|u1", max_bytes=16 * 1024)
    raw = metadata[...].tobytes()
    declaration = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
    _fields(declaration, {"profile", "quantity", "unit", "curves"})
    if declaration["profile"] != TRACE_PROFILE or declaration["quantity"] not in ("S", "Z", "Y", None):
        raise ProjectError("E_VERSION", "복소 곡선 프로필 또는 물리량 선언이 다릅니다.")
    if declaration["unit"] != {"S": "1", "Z": "ohm", "Y": "S", None: None}[declaration["quantity"]]:
        raise ProjectError("E_UNIT", "복소 곡선의 물리량과 단위 선언이 다릅니다.")
    entries = declaration["curves"]
    if type(entries) is not list or not 1 <= len(entries) <= MAX_TRACES or canonical_bytes(declaration) != raw:
        raise ProjectError("E_SCHEMA", "복소 곡선은 최대 여덟 개의 정규 메타데이터를 지원합니다.")
    seen = [handle.id, metadata.id]
    group = field_hdf5._child(handle, "traces", h5py, seen, True)
    names = [f"t{index}" for index in range(len(entries))]
    if len(group.attrs) or len(group) != len(names) or set(group) != set(names):
        raise ProjectError("E_SCHEMA", "복소 곡선 식별자와 배열 목록이 다릅니다.")
    arrays = []
    for name, entry in zip(names, entries):
        _fields(entry, {"label", "source", "reference_ohm", "measurement"})
        for key in ("label", "source", "measurement"):
            text = entry[key]
            if key != "label" and text is None:
                continue
            if type(text) is not str or not text.strip() or len(text.encode("utf-8")) > 512:
                raise ProjectError("E_SCHEMA", "복소 곡선의 이름 또는 출처가 유효하지 않습니다.")
        z0 = entry["reference_ohm"]
        if z0 is not None and (type(z0) not in (int, float) or not math.isfinite(z0) or z0 <= 0):
            raise ProjectError("E_SCHEMA", "기준 임피던스는 양수 또는 미정이어야 합니다.")
        curve = field_hdf5._child(group, name, h5py, seen, True)
        if len(curve.attrs) or len(curve) != 3 or set(curve) != {"frequency_hz", "values_ri", "valid"}:
            raise ProjectError("E_SCHEMA", "복소 곡선에 주파수, 실수/허수와 유효 마스크가 필요합니다.")
        frequency = _dataset(curve, "frequency_hz", h5py, dtype="<f8", max_bytes=MAX_SAMPLES)
        count = frequency.size
        values = _dataset(curve, "values_ri", h5py, dtype="<f8", shape=(count, 2))
        valid = _dataset(curve, "valid", h5py, dtype="|u1", shape=(count,))
        for dataset in (frequency, values, valid):
            if any(dataset.id == previous for previous in seen):
                raise ProjectError("E_UNSUPPORTED", "복소 곡선에 HDF5 hard-link 별칭이 있습니다.")
            seen.append(dataset.id)
        if verify_samples:
            _verify_samples(frequency, values, valid, np)
        arrays.append((frequency, values, valid))
    return declaration, arrays


def _verify_samples(frequency, values, valid, np):
    """! @brief 한 번에 4096표본만 검사하며 주파수 단조성 및 결측 마스크를 보존한다."""
    last = 0.0
    for start in range(0, frequency.size, 4096):
        section = slice(start, start + 4096)
        axis, ri, mask = frequency[section], values[section], valid[section]
        if (not np.isfinite(axis).all() or axis[0] <= last or (np.diff(axis) <= 0).any()
                or (mask > 1).any() or not np.isfinite(ri[mask == 1]).all()
                or (np.abs(ri[mask == 1]) > 1e100).any()):
            raise ProjectError("E_SCHEMA", "주파수와 유효 복소 표본/마스크를 확인하십시오.")
        last = axis[-1]
