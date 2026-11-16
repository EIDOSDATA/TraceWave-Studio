"""! @brief 고정된 무압축 HDF5 profile로 복소 축과 원본 조건을 함께 보존한다.

@details 일반 HDF5 reader가 아니다. 고정 dataset/자료형/상한을 먼저 검사하고
외부 저장소, 링크, VDS, 필터와 알 수 없는 객체를 거절한 뒤 배열을 읽는다.
"""

from importlib import import_module, metadata
import json
from uuid import uuid4

from rfad.adapters.network_text import MAX_FILE_BYTES, fail
from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import MAX_DATA_BYTES, validate_dataset


PROFILE = "rfad.network-hdf5/0.1"
H5PY_VERSION = "3.16.0"
NUMPY_VERSION = "2.5.4"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
SIGNATURE = b"\x89HDF\r\n\x1a\n"
STATUS_CODES = ("valid", "missing", "singular", "ill_conditioned", "unsupported", "outside_validity", "nonfinite")
ORIGIN_CODES = ("computed", "measured", "imported", "derived", "interpolated", "unknown")
LAYOUT = {"profile": PROFILE, "complex_axis": "real_imag_last", "float_dtype": "<f8", "mask_dtype": "|u1",
          "port_id_dtype": "|S36", "layout": "contiguous", "compression": None, "track_times": False,
          "status_codes": list(STATUS_CODES), "origin_codes": list(ORIGIN_CODES)}


def installation_metadata():
    """! @brief 일반 capabilities는 native HDF5/NumPy를 불러오지 않는다."""
    versions = {}
    for name in ("h5py", "numpy"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    matches = versions == {"h5py": H5PY_VERSION, "numpy": NUMPY_VERSION}
    return {"profile": PROFILE, "versions": versions, "required_versions": {"h5py": H5PY_VERSION, "numpy": NUMPY_VERSION},
            "version_matches": matches, "runtime_checked": False, "available": None if matches else False}


def _runtime():
    """! @brief 교환 작업에서만 고정된 선택 런타임을 불러온다."""
    try:
        h5py, np = import_module("h5py"), import_module("numpy")
    except (ImportError, OSError):
        fail("고정 h5py/NumPy 환경을 설치해야 HDF5 자료를 교환할 수 있습니다.", code="E_CAPABILITY")
    if h5py.__version__ != H5PY_VERSION or np.__version__ != NUMPY_VERSION:
        fail("HDF5 교환에 필요한 고정 라이브러리 버전과 다릅니다.", code="E_CAPABILITY")
    return h5py, np


def _arrays(data, np):
    """! @brief null을 유효 숫자로 채우지 않고 별도 존재 mask와 NaN 저장값으로 표현한다."""
    count, ports = len(data["frequency_hz"]), len(data["port_ids"])
    values = np.full((count, ports, ports, 2), np.nan, dtype="<f8")
    present = np.zeros((count, ports, ports), dtype="u1")
    references = np.full((count, ports, 2), np.nan, dtype="<f8")
    reference_present = np.zeros((count, ports), dtype="u1")
    for index in range(count):
        for row in range(ports):
            for column in range(ports):
                value = data["values_ri"][index][row][column]
                if value is not None:
                    values[index, row, column] = value
                    present[index, row, column] = 1
            if data["z0_ohm"] is not None and data["z0_ohm"][index][row] is not None:
                references[index, row] = data["z0_ohm"][index][row]
                reference_present[index, row] = 1
    return {"profile": np.frombuffer(canonical_bytes(LAYOUT), dtype="u1"),
            "metadata_json": np.frombuffer(canonical_bytes(data), dtype="u1"),
            "frequency_hz": np.asarray(data["frequency_hz"], dtype="<f8"),
            data["parameter_kind"].lower(): values,
            "network_value_present": present,
            "valid_mask": np.asarray(data["valid_mask"], dtype="u1"),
            "sample_status": np.asarray([[[STATUS_CODES.index(cell) for cell in row] for row in matrix] for matrix in data["sample_status"]], dtype="u1"),
            "sample_origin": np.asarray([ORIGIN_CODES.index(value) for value in data["sample_origin"]], dtype="u1"),
            "z0_ohm": references, "z0_value_present": reference_present,
            "port_ids": np.asarray([value.encode("ascii") for value in data["port_ids"]], dtype="S36")}


def encode_network_hdf5(data):
    """! @brief 시간 속성 없는 동일 배열/순서로 재계산 가능한 HDF5 bytes를 생성한다."""
    validate_dataset(data)
    h5py, np = _runtime()
    arrays = _arrays(data, np)
    create = h5py.h5p.create(h5py.h5p.FILE_CREATE)
    create.set_obj_track_times(False)
    access = h5py.h5p.create(h5py.h5p.FILE_ACCESS)
    access.set_fapl_core(64 * 1024, False)
    try:
        identity = h5py.h5f.create(("tracewave-network-" + str(uuid4()) + ".h5").encode("ascii"),
                                  h5py.h5f.ACC_TRUNC, fcpl=create, fapl=access)
        with h5py.File(identity) as handle:
            for name in sorted(arrays):
                handle.create_dataset(name, data=arrays[name], dtype=arrays[name].dtype,
                                      chunks=None, compression=None, track_times=False, track_order=False)
            handle.flush()
            raw = handle.id.get_file_image()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        fail("HDF5 자료를 생성하지 못했습니다: " + type(error).__name__, code="E_IO")
    finally:
        create.close()
        access.close()
    if len(raw) > MAX_ARTIFACT_BYTES:
        fail("HDF5 산출물 8 MiB 상한을 초과했습니다.", code="E_RESOURCE")
    return raw


def _dataset(handle, name, h5py, *, shape=None, dtype=None, max_bytes=None):
    """! @brief 링크/저장 방식/자료형/크기를 확인한 뒤에만 dataset 읽기를 허용한다."""
    if not isinstance(handle.get(name, getlink=True), h5py.HardLink):
        fail("HDF5 soft/external 링크는 지원하지 않습니다.", name, code="E_UNSUPPORTED")
    value = handle[name]
    if not isinstance(value, h5py.Dataset) or len(value.attrs):
        fail("HDF5에는 속성 없는 고정 dataset만 허용합니다.", name, code="E_UNSUPPORTED")
    properties = value.id.get_create_plist()
    try:
        if properties.get_layout() != h5py.h5d.CONTIGUOUS or properties.get_nfilters() or properties.get_external_count():
            fail("HDF5 chunk/압축/필터/VDS/외부 저장소는 지원하지 않습니다.", name, code="E_UNSUPPORTED")
    finally:
        properties.close()
    if shape is not None and value.shape != shape:
        fail("HDF5 배열 모양이 선언된 축과 다릅니다.", name, code="E_RESOURCE")
    expected_metadata = {"h5py_encoding": "ascii"} if dtype == "|S36" else None
    if dtype is not None and (value.dtype.str != dtype or value.dtype.metadata != expected_metadata):
        fail("HDF5 자료형 또는 endian이 profile과 다릅니다.", name, code="E_UNSUPPORTED")
    if max_bytes is not None and (value.ndim != 1 or not 1 <= value.size <= max_bytes):
        fail("HDF5 metadata 배열 상한을 벗어났습니다.", name, code="E_RESOURCE")
    return value


def _unique(pairs):
    """! @brief 중복 JSON 키가 원문 의미를 덮지 못하도록 한다."""
    result = {}
    for key, value in pairs:
        if key in result:
            fail("HDF5 metadata JSON 키가 중복되었습니다.")
        result[key] = value
    return result


def _constant(value):
    """! @brief metadata JSON의 NaN/Infinity 상수를 거절한다."""
    fail("HDF5 metadata에는 비유한 JSON 상수를 저장할 수 없습니다.")


def _read(handle, h5py, np):
    """! @brief 최대 11개 객체와 canonical metadata를 확인한 뒤 정규화 배열을 대조한다."""
    if len(handle) != 11 or len(handle.attrs):
        fail("현재 HDF5 profile은 속성 없는 11개 dataset만 허용합니다.", code="E_UNSUPPORTED")
    names = set(handle.keys())
    fixed = {"profile", "metadata_json", "frequency_hz", "network_value_present", "valid_mask", "sample_status",
             "sample_origin", "z0_ohm", "z0_value_present", "port_ids"}
    if not fixed.issubset(names) or len(names & {"s", "z", "y"}) != 1:
        fail("HDF5 dataset 이름이 현재 profile과 다릅니다.", code="E_UNSUPPORTED")
    profile = _dataset(handle, "profile", h5py, shape=(len(canonical_bytes(LAYOUT)),), dtype="|u1")
    if profile[...].tobytes() != canonical_bytes(LAYOUT):
        fail("알 수 없는 HDF5 profile 또는 레이아웃 버전입니다.", code="E_VERSION")
    metadata_array = _dataset(handle, "metadata_json", h5py, dtype="|u1", max_bytes=MAX_DATA_BYTES)
    metadata_raw = metadata_array[...].tobytes()
    data = json.loads(metadata_raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
    validate_dataset(data)
    if canonical_bytes(data) != metadata_raw:
        fail("HDF5 metadata JSON이 canonical 원본과 다릅니다.", code="E_HASH")
    arrays = _arrays(data, np)
    if set(arrays) != names:
        fail("HDF5 행렬 종류와 metadata가 다릅니다.", code="E_HASH")
    opened = []
    for name, expected in arrays.items():
        dataset = _dataset(handle, name, h5py, shape=expected.shape, dtype=expected.dtype.str)
        if any(dataset.id == previous.id for previous in opened):
            fail("HDF5 dataset의 hard-link 별칭은 지원하지 않습니다.", name, code="E_UNSUPPORTED")
        opened.append(dataset)
        actual = dataset[...]
        equal = np.array_equal(actual, expected, equal_nan=True) if expected.dtype.kind == "f" else np.array_equal(actual, expected)
        if not equal:
            fail("HDF5 정규화 배열이 metadata/유효 mask와 다릅니다.", name, code="E_HASH")
    return data


def decode_network_hdf5(raw):
    """! @brief 원본 bytes 안의 고정 HDF5 자료만 읽고 null/mask/조건을 그대로 복원한다."""
    if type(raw) is not bytes or not raw.startswith(SIGNATURE):
        fail("현재 profile의 HDF5 서명이 아닙니다.")
    if len(raw) > MAX_FILE_BYTES:
        fail("HDF5 원본 4 MiB 상한을 초과했습니다.", code="E_RESOURCE")
    h5py, np = _runtime()
    try:
        with h5py.File.in_memory(raw) as handle:
            return _read(handle, h5py, np)
    except ProjectError:
        raise
    except MemoryError:
        fail("HDF5 읽기 메모리 예산을 확보하지 못했습니다.", code="E_RESOURCE")
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        fail("HDF5 구조 또는 metadata를 읽지 못했습니다: " + type(error).__name__)
