"""! @brief Windows에서 합성 1 GiB 복소 필드의 어댑터 읽기 비용을 따로 진단한다."""

import argparse
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
from pathlib import Path
import sys
from threading import Event, Thread
from time import perf_counter
from unittest.mock import patch

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.adapters import field_hdf5
from rfad.domain.errors import ProjectError
from rfad.storage import sealed_files


SHAPE = (256, 256, 683)
FREQUENCY = 1e9
COORDINATES = {axis: list(range(length)) for axis, length in zip("xyz", SHAPE)}
EXPECTED = {"shape": SHAPE, "frequency_hz": [FREQUENCY], "dump_type": 0,
            "primary_coordinates_mm": COORDINATES}
FILE_BUDGET = 1025 * 1024**2


def prepare(path):
    """! @brief 새 시험 디렉터리에 작은 쓰기 블록으로 고정 NXYZ 자료와 봉인을 만든다."""
    seal = path.with_suffix(".seal.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if seal.exists():
        raise FileExistsError(seal)
    with h5py.File(path, "x") as handle:
        handle.attrs["openEMS_HDF5_version"] = 0.3
        handle.attrs["dual_mesh"] = np.uint8(0)
        handle.attrs["dump_type"] = np.int32(0)
        mesh = handle.create_group("Mesh")
        mesh.attrs["mesh_type"] = np.int32(0)
        mesh.attrs["mesh_scaling"] = 0.001
        for axis in "xyz":
            mesh.create_dataset(axis, data=np.asarray(COORDINATES[axis], dtype="<f8") * 0.001)
        fd = handle.create_group("FieldData").create_group("FD")
        fd.attrs["frequency"] = [FREQUENCY]
        dataset = fd.create_dataset("f0", shape=(3, *SHAPE), dtype="<c8")
        dataset.attrs["d_order"] = "NXYZ"
        dataset.attrs["frequency"] = FREQUENCY
        for component in range(3):
            for first in range(0, SHAPE[0], 4):
                block = np.broadcast_to(
                    np.arange(first, first+4, dtype=np.float32)[:, None, None] + 1000 * component + 2j,
                    (4, *SHAPE[1:]))
                dataset[component, first:first+4, :, :] = np.asarray(block, dtype="<c8")
    with path.open("rb") as stream:
        reference = {"uri": path.name, "bytes": path.stat().st_size,
                     "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    assert 1024**3 < reference["bytes"] <= FILE_BUDGET
    with seal.open("x", encoding="utf-8") as stream:
        json.dump(reference, stream)


class Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (key, ctypes.c_size_t) for key in ("peak_working", "working", "peak_paged", "paged",
                                          "peak_nonpaged", "nonpaged", "commit", "peak_commit", "private")]


def memory(process, get_info):
    """! @brief 실제 Windows 프로세스의 private commit과 working set을 따로 읽는다."""
    counter = Counters(cb=ctypes.sizeof(Counters))
    if not get_info(process, ctypes.byref(counter), counter.cb):
        raise ctypes.WinError()
    return {"private_commit_bytes": counter.private, "working_set_bytes": counter.working}


def measure(path):
    """! @brief 제품 상한 거절과 캡을 바꾼 격리 시험의 원문 확인 비용을 구분한다."""
    current_process = ctypes.windll.kernel32.GetCurrentProcess
    current_process.restype = wintypes.HANDLE
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    process = current_process()
    reference = json.loads(path.with_suffix(".seal.json").read_bytes())
    try:
        field_hdf5.read(path, reference, EXPECTED)
    except ProjectError as error:
        product_limit = error.code
    else:
        raise RuntimeError("현재 제품 상한이 합성 필드를 허용했습니다. 이 격리 계측은 지원 경로를 다시 확인해야 합니다.")
    baseline = memory(process, get_info)
    samples, elapsed = [], []
    finished = Event()
    start = perf_counter()

    def sampling():
        while not finished.is_set():
            samples.append({"seconds": perf_counter() - start, **memory(process, get_info)})
            finished.wait(0.1)

    sampler = Thread(target=sampling)
    sampler.start()
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sealed_files, "MAX_FILE_BYTES", FILE_BUDGET))
            stack.enter_context(patch.object(field_hdf5, "MAX_FILE_BYTES", FILE_BUDGET))
            stack.enter_context(patch.object(field_hdf5, "MAX_POINTS", math.prod(SHAPE)))
            before = perf_counter()
            descriptor = field_hdf5.read(path, reference, EXPECTED)
            assert descriptor["values"] is None
            elapsed.append({"operation": "describe", "seconds": perf_counter() - before})
            for index in range(10):
                component, first = index % 3, index * 7
                selection = {"component_index": component, "frequency_index": 0,
                             "x": slice(first, first + 64), "y": slice(index, index + 64), "z": 5 + index}
                before = perf_counter()
                result = field_hdf5.read(path, reference, EXPECTED, selection)
                elapsed.append({"operation": "roi", "index": index, "seconds": perf_counter() - before})
                wanted = np.broadcast_to(np.arange(first, first + 64) + 1000 * component + 2j, (64, 64))
                np.testing.assert_array_equal(result["values"], wanted)
    finally:
        finished.set()
        sampler.join()
    output = {"profile": "synthetic isolated cap feasibility", "product_cap_rejection": product_limit,
              "file": reference, "baseline": baseline,
              "peak": max(sample["private_commit_bytes"] for sample in samples), "memory_samples": samples,
              "reads": elapsed, "native_fdtd": False, "gui": False}
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    """! @brief 원본이 없는 격리 경로를 준비하거나 기존 합성 봉인을 측정한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "measure"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows에서만 이 자원 계측을 지원합니다.")
    (prepare if args.action == "prepare" else measure)(args.directory / "field.h5")


if __name__ == "__main__":
    main()
