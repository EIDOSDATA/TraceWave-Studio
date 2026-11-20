"""! @brief 봉인된 primary Yee 복소 필드에서 검증한 유한 단면만 읽는다.

@details 일반 HDF5 importer가 아니다. 고정 openEMS 0.3 NXYZ 복소64 형식과
계획의 실제 격자를 대조하고 외부 저장소/링크/필터를 열기 전에 거부한다.
"""

from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import stat

from rfad.adapters.network_hdf5 import _runtime
from rfad.domain.errors import ProjectError
from rfad.storage.sealed_files import validate_reference, CHUNK_BYTES


PROFILE = "rfad.primary-yee-field-hdf5/0.1"
AXES = "xyz"
MAX_POINTS = 1500000
MAX_FIELD_BYTES = 48 * 1024 * 1024


def fail(message, code="E_UNSUPPORTED"):
    """! @brief 미지원 형식과 변조/자원 실패를 제품 진단으로 구분한다."""
    raise ProjectError(code, message)


@contextmanager
def opened(path, reference):
    """! @brief 같은 열린 일반 파일을 유한 버퍼로 봉인 확인한 뒤 HDF5에 전달한다."""
    validate_reference(reference)
    h5py, np = _runtime()
    path = Path(path)
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400):
            fail("필드 원문은 링크가 아닌 독립 일반 파일이어야 합니다.", "E_HASH")
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != reference["bytes"]:
                fail("필드 원문의 실제 유형 또는 길이가 봉인과 다릅니다.", "E_HASH")
            digest, count = hashlib.sha256(), 0
            while block := stream.read(CHUNK_BYTES):
                count += len(block)
                if count > reference["bytes"]:
                    fail("필드 원문이 선언한 길이를 초과했습니다.", "E_HASH")
                digest.update(block)
            if count != reference["bytes"] or digest.hexdigest() != reference["sha256"]:
                fail("필드 원문의 SHA256이 봉인과 다릅니다.", "E_HASH")
            stream.seek(0)
            if stream.read(8) != b"\x89HDF\r\n\x1a\n":
                fail("필드 원문의 HDF5 signature가 다릅니다.")
            stream.seek(0)
            # @brief h5py를 먼저 닫아 fileobj 수명 이후의 native 접근을 막는다.
            with h5py.File(stream, "r") as handle:
                if handle.userblock_size:
                    fail("필드 profile은 HDF5 user block을 지원하지 않습니다.")
                yield handle, h5py, np
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, OverflowError) as error:
        raise ProjectError("E_HASH", "봉인된 필드 HDF5를 읽을 수 없습니다: " + type(error).__name__) from error


def _attributes(value, required, optional=()):
    """! @brief 알려진 소수 속성만 허용하며 임의 metadata를 따라가지 않는다."""
    if len(value.attrs) > len(required) + len(optional):
        fail("필드 HDF5에 지원하지 않는 속성이 있습니다.")
    keys = set(value.attrs.keys())
    if not set(required) <= keys or not keys <= set(required) | set(optional):
        fail("필드 HDF5 필수 속성 또는 profile이 다릅니다.")


def _attribute(value, name, np, shape=(), string=False):
    """! @brief scalar/최대3주파수만 읽고 문자열도 고정8바이트 버퍼로 읽는다."""
    identity = value.attrs.get_id(name)
    try:
        if identity.shape != shape:
            fail("필드 HDF5 속성 배열 크기가 다릅니다.", "E_RESOURCE")
        if string:
            if identity.dtype.kind not in ("S", "O"):
                fail("필드 배열 순서 속성이 문자열이 아닙니다.")
            data = np.empty(shape, dtype="S8")
            identity.read(data)
            return data.item().decode("ascii")
        if identity.dtype.kind not in ("f", "i", "u", "b") or identity.dtype.itemsize > 8:
            fail("필드 HDF5 숫자 속성의 자료형이 다릅니다.")
        data = value.attrs[name]
        if not np.all(np.isfinite(data)):
            fail("필드 HDF5 속성에 유한하지 않은 숫자가 있습니다.", "E_HASH")
        return data
    finally:
        identity.close()


def _child(parent, name, h5py, seen, group=False):
    """! @brief 외부/soft 링크와 hard-link 별칭을 데이터 접근 전에 거부한다."""
    if not isinstance(parent.get(name, getlink=True), h5py.HardLink):
        fail("필드 HDF5의 외부/soft 링크는 지원하지 않습니다.")
    value = parent[name]
    if not isinstance(value, h5py.Group if group else h5py.Dataset):
        fail("필드 HDF5 객체 종류가 다릅니다.")
    if any(value.id == previous for previous in seen):
        fail("필드 HDF5 hard-link 별칭은 지원하지 않습니다.")
    seen.append(value.id)
    if not group:
        props = value.id.get_create_plist()
        try:
            if (props.get_layout() != h5py.h5d.CONTIGUOUS or props.get_nfilters()
                    or props.get_external_count()):
                fail("필드 HDF5의 필터/압축/외부 저장소/VDS는 지원하지 않습니다.")
        finally:
            props.close()
    return value


def inspect(handle, h5py, np, expected):
    """! @brief 배열 본문을 읽기 전에 계획/축/shape/dtype/속성/저장방식을 대조한다."""
    shape = expected["shape"]
    frequencies = expected["frequency_hz"]
    if (len(shape) != 3 or any(type(n) is not int or n < 1 for n in shape)
            or math.prod(shape) > MAX_POINTS or not 1 <= len(frequencies) <= 3
            or math.prod(shape) * 3 * 8 * len(frequencies) > MAX_FIELD_BYTES):
        fail("필드 배열의 명시 크기/주파수 예산을 초과했습니다.", "E_RESOURCE")
    if len(handle) != 2 or set(handle.keys()) != {"Mesh", "FieldData"}:
        fail("필드 HDF5 root 객체가 지원 profile과 다릅니다.")
    _attributes(handle, {"openEMS_HDF5_version", "dual_mesh", "dump_type"}, {"legacy_fmt"})
    if (float(_attribute(handle, "openEMS_HDF5_version", np)) != 0.3
            or _attribute(handle, "dual_mesh", np) != 0
            or _attribute(handle, "dump_type", np) != expected["dump_type"]
            or "legacy_fmt" in handle.attrs and _attribute(handle, "legacy_fmt", np) != 0):
        fail("현재 primary Yee openEMS 0.3 필드만 지원합니다.", "E_VERSION")
    seen = [handle.id]
    mesh = _child(handle, "Mesh", h5py, seen, True)
    _attributes(mesh, {"mesh_scaling", "mesh_type"})
    if float(_attribute(mesh, "mesh_scaling", np)) != 0.001 or _attribute(mesh, "mesh_type", np) != 0:
        fail("필드 원문의 직교 좌표/mm 길이 기준이 다릅니다.")
    if len(mesh) != 3 or set(mesh.keys()) != set(AXES):
        fail("필드 원문의 격자 축이 다릅니다.")
    primary = {}
    for index, axis in enumerate(AXES):
        values = _child(mesh, axis, h5py, seen)
        _attributes(values, set())
        if values.shape != (shape[index],) or values.dtype.str != "<f8" or values.dtype.metadata:
            fail("필드 원문의 좌표 shape/dtype가 다릅니다.")
        actual = values[...]
        wanted = np.asarray(expected["primary_coordinates_mm"][axis], dtype="<f8") * 0.001
        if (not np.all(np.isfinite(actual)) or np.any(np.diff(actual) <= 0)
                or not np.allclose(actual, wanted, rtol=0, atol=1e-12)):
            fail("필드 원문의 실제 primary 좌표가 봉인 계획과 다릅니다.", "E_HASH")
        primary[axis] = (actual * 1000).tolist()
    fields = _child(handle, "FieldData", h5py, seen, True)
    _attributes(fields, set())
    if len(fields) != 1 or set(fields.keys()) != {"FD"}:
        fail("현재 복소 주파수 필드만 지원합니다.")
    fd = _child(fields, "FD", h5py, seen, True)
    _attributes(fd, {"frequency"})
    frequency = _attribute(fd, "frequency", np, (len(frequencies),))
    if frequency.tolist() != frequencies:
        fail("필드의 기록 주파수가 봉인 계획과 정확히 일치하지 않습니다.", "E_HASH")
    if len(fd) != len(frequencies) or set(fd.keys()) != {"f" + str(i) for i in range(len(frequencies))}:
        fail("필드의 주파수 배열 목록이 다릅니다.")
    datasets = []
    for index, frequency in enumerate(frequencies):
        data = _child(fd, "f" + str(index), h5py, seen)
        _attributes(data, {"d_order", "frequency"})
        if (data.shape != (3, *shape) or data.dtype.str != "<c8" or data.dtype.metadata
                or _attribute(data, "d_order", np, string=True) != "NXYZ"
                or float(_attribute(data, "frequency", np)) != frequency):
            fail("필드의 NXYZ 복소64 배열과 실제 주파수 선언이 다릅니다.", "E_HASH")
        datasets.append(data)
    return datasets, primary


def read(path, reference, expected, selection=None):
    """! @brief 설명 조회는 배열 본문을 읽지 않고 단면 조회만 해당 hyperslab을 읽는다."""
    with opened(path, reference) as (handle, h5py, np):
        datasets, primary = inspect(handle, h5py, np, expected)
        if selection is None:
            return {"primary_coordinates_mm": primary, "values": None}
        slices = [selection["component_index"]]
        for axis in AXES:
            slices.append(selection[axis])
        # @brief 남은 축은 항상 x/y/z 순서의 u,v이므로 반환 행/열은 v,u로 전치한다.
        data = datasets[selection["frequency_index"]][tuple(slices)]
        return {"primary_coordinates_mm": primary, "values": data.T}
