"""! @brief 별도 프로세스에서 전체 카탈로그 조회의 시간과 메모리를 측정한다."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

from rfad.catalog.service import CatalogService


def memory_sample() -> dict:
    """! @brief Windows working set과 프로세스 최고치를 바이트로 반환한다."""
    if os.name != "nt":
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"peak_resident_bytes": peak if sys.platform == "darwin" else peak * 1024}

    from ctypes import wintypes

    class Counters(ctypes.Structure):
        """! @brief Windows PROCESS_MEMORY_COUNTERS 구조를 정의한다."""

        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (field, ctypes.c_size_t) for field in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            )]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"resident_bytes": counters.WorkingSetSize, "peak_resident_bytes": counters.PeakWorkingSetSize}


def measure(database: Path) -> dict:
    """! @brief 디스크 캐시를 조작하지 않고 첫 조회와 반복 조회를 분리해 측정한다."""
    baseline = memory_sample()
    started = time.perf_counter()
    service = CatalogService(database)
    constructed_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    status = service.status()
    status_ms = (time.perf_counter() - started) * 1000
    if not status["available"]:
        raise ValueError(status)
    queries = {
        "first_observations": {"entity": "observations", "limit": 25},
        "rogers_10ghz": {"entity": "observations", "filters": {
            "publisher": "Rogers", "frequency_property": "dk", "frequency_ghz": 10}},
        "pcbway_stackups": {"entity": "stackups", "filters": {"publisher": "PCBWay", "layer_count": 4}},
        "missing_df": {"entity": "observations", "filters": {"review_flag": "scalar_df_missing"}},
        "substring": {"entity": "observations", "query": "RO4350"},
        "last_observations": {"entity": "observations", "offset": max(0, status["counts"]["observations"] - 25),
                              "catalog_id": status["catalog_id"]},
        "we_components": {"entity": "native_components", "filters": {"publisher": "Wurth Elektronik"}},
    }
    results = {}
    for name, query in queries.items():
        timings = []
        sizes = []
        for _ in range(21):
            started = time.perf_counter()
            response = service.search(query)
            timings.append((time.perf_counter() - started) * 1000)
            sizes.append(len(json.dumps(response, ensure_ascii=False).encode("utf-8")))
        repeated = sorted(timings[1:])
        results[name] = {
            "first_ms": timings[0], "repeat_count": len(repeated), "median_ms": statistics.median(repeated),
            "p95_ms": repeated[18], "max_ms": max(repeated), "maximum_serialized_bytes": max(sizes),
        }
    memory = memory_sample()
    heavy = sorted(name for name in sys.modules if name.split(".")[0] in {"cadquery", "OCP", "vtk", "numpy", "openEMS"})
    if heavy:
        raise ValueError("조회가 CAD/해석 모듈을 import했습니다: " + str(heavy))
    return {
        "schema": "rfad.catalog.performance/1", "platform": platform.platform(), "python": platform.python_version(),
        "database_bytes": database.stat().st_size, "catalog_id": status["catalog_id"],
        "scope": "standalone Python read-only service; OS disk cache uncontrolled; GUI/FPS/build excluded",
        "constructor_ms": constructed_ms, "first_status_ms": status_ms,
        "baseline_memory": baseline, "after_queries_memory": memory, "heavy_modules": heavy, "queries": results,
    }


def main() -> int:
    """! @brief 검증 도구가 호출하는 독립 측정 결과를 JSON으로 출력한다."""
    parser = argparse.ArgumentParser(description="PCB 카탈로그 조회 성능 측정")
    parser.add_argument("--database", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(measure(arguments.database.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
