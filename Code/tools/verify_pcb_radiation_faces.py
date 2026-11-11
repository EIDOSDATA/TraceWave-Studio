"""! @brief 봉인한 12면 HDF5의 실제 좌표/주파수/유한 필드를 읽기 전용으로 확인한다."""

import argparse
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath


def workspace_path(value):
    """! @brief WSL 감사에서는 보고서의 Windows 절대 경로를 같은 C 드라이브 mount로 읽는다."""
    path = PureWindowsPath(value)
    if path.drive and Path("/mnt").exists():
        return Path("/mnt") / path.drive[0].lower() / Path(*path.parts[1:])
    return Path(value)


def coordinates_match(expected, observed):
    """! @brief mm 계획과 m HDF5 좌표를 절대 1e-12 m 안에서 직접 비교한다."""
    return len(expected) == len(observed) and all(math.isfinite(value) and math.isclose(a * 0.001, value, rel_tol=0, abs_tol=1e-12) for a, value in zip(expected, observed))


def read_sealed(workspace, ref):
    """! @brief 저장소 바깥 경로와 바이트 변조를 거절한다."""
    path = (workspace / ref["uri"]).resolve()
    if not path.is_relative_to(workspace.resolve()) or not 0 < ref["bytes"] <= 64 * 1024 * 1024:
        raise ValueError("유한한 workspace 내부 산출물이 필요합니다.")
    data = path.read_bytes()
    if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
        raise ValueError("파일의 실제 봉인이 다릅니다.")
    return path, data


def audit(report_path, output):
    """! @brief solver 실행 없이 각 표면의 법선/접선 격자와 주파수 영역 자료를 확인한다."""
    import h5py
    import numpy as np

    if output.exists():
        raise ValueError("새 감사 출력 경로가 필요합니다.")
    report = json.loads(report_path.read_bytes())
    if report["schema"] != "rfad.pcb-radiation-study-run/0.1" or report["status"] != "completed":
        raise ValueError("완료한 방사 연구가 필요합니다.")
    workspace = workspace_path(report["workspace"])
    cases = []
    for entry in report["runs"].values():
        _, raw = read_sealed(workspace, entry["normalized_result"])
        normalized = json.loads(raw)
        plan = normalized["provenance"]["analysis_plan"]
        if plan["plan_id"] != entry["analysis_plan"]["plan_id"]:
            raise ValueError("원래 계획과 정규화 결과가 다릅니다.")
        recording = plan["case"]["radiation_recording"]
        lines = normalized["mesh_statistics"]["lines_mm"]
        files = {item["role"]: item for item in normalized["raw_manifest"]["files"]}
        observed = []
        for component in ("E", "H"):
            for face in range(6):
                role = f"raw/{recording['name']}_{component}_{face}.h5"
                item = files[role]
                ref = {"uri": str(Path(entry["normalized_result"]["uri"]).parent / role), "bytes": item["bytes"], "sha256": item["sha256"]}
                path, _ = read_sealed(workspace, ref)
                actual = {}
                with h5py.File(path, "r") as field:
                    for axis, key in enumerate("xyz"):
                        if axis == face // 2:
                            expected = [recording["start_mm" if face % 2 == 0 else "stop_mm"][axis]]
                        else:
                            expected = [x for x in lines[key] if recording["start_mm"][axis] <= x <= recording["stop_mm"][axis]]
                        values = [float(x) for x in field["Mesh"][key]]
                        if not coordinates_match(expected, values):
                            raise ValueError("HDF5의 실제 기록 면/격자 좌표가 계획과 다릅니다: " + role + "/" + key)
                        actual[key] = {"minimum_m": values[0], "maximum_m": values[-1], "count": len(values)}
                    group = field["FieldData/FD"]
                    frequency = [float(value) for value in group.attrs["frequency"]]
                    expected = recording["frequency_hz"]
                    if len(frequency) != len(expected) or any(not math.isfinite(x) or not math.isclose(x, y, rel_tol=1e-6, abs_tol=0) for x, y in zip(frequency, expected)):
                        raise ValueError("실제 기록 주파수가 요청과 다릅니다.")
                    if set(group) != {"f" + str(i) for i in range(len(expected))}:
                        raise ValueError("실제 기록 주파수 dataset이 불완전합니다.")
                    for dataset in group.values():
                        values = np.asarray(dataset)
                        valid = all(np.all(np.isfinite(values[key])) for key in values.dtype.names) if values.dtype.names else np.all(np.isfinite(values))
                        if not valid:
                            raise ValueError("원시 E/H에 비유한 필드가 있습니다.")
                read_sealed(workspace, ref)
                observed.append({"role": role, "sha256": item["sha256"], "mesh": actual, "frequency_hz": frequency, "fields_finite": True})
        cases.append({"artifact_id": entry["artifact_id"], "recording": recording, "faces": observed})
    result = {"schema": "rfad.pcb-radiation-face-audit/0.1", "status": "passed", "study_hash": report["study_hash"],
              "coordinate_absolute_tolerance_m": 1e-12, "frequency_relative_tolerance": 1e-6, "fdtd_executed": False,
              "physics_validated": False, "cases": cases}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return {"status": "passed", "cases": len(cases), "faces": sum(len(case["faces"]) for case in cases)}


def main():
    """! @brief 기존 openEMS 환경의 h5py/numpy만 사용하는 읽기 전용 감사를 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.report, args.output)))
        return 0
    except Exception as error:
        print(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
