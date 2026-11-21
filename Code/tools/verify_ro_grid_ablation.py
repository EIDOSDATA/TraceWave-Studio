"""! @brief 봉인 RO4350B에서 한 번에 한 격자 구간만 교체한 포트 대조를 실행한다."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from xml.etree import ElementTree as ET

from verify_installed_port_band import Trace


AXES = "XYZ"
FREQUENCIES = (2.4e9, 2.44175e9, 2.4835e9)
PORT_NAMES = ("port_ut_1", "port_it_1")
DURATION = 4.210e-9
N7_DT = 1.593972486287773e-13
N8_DT = 1.371922165243796e-13
WORKERS = 3
THREADS = 2
TIMEOUT = 4200
ABLATIONS = {
    "same_grid_shorter_dt": (),
    "transverse_feed_strip": (("X", 8.0, 10.0),),
    "axial_feed_strip": (("Y", 49.0, 54.0),),
    "substrate_z": (("Z", 0.035, 0.797),),
    "feed_strips_and_substrate": (("X", 8.0, 10.0), ("Y", 49.0, 54.0), ("Z", 0.035, 0.797)),
}
COMPLEMENT = "outside_feed_strips_and_substrate"
ALLOWED = {**ABLATIONS, COMPLEMENT: ABLATIONS["feed_strips_and_substrate"]}


def sha(path):
    """! @brief 원본과 새 계산 산출물의 바이트를 식별한다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sealed(path, descriptor):
    """! @brief 보존한 원시 입력을 기록된 바이트 및 SHA256으로 확인한다."""
    if path.stat().st_size != descriptor["bytes"] or sha(path) != descriptor["sha256"]:
        raise ValueError("봉인 원문과 파일이 다릅니다.")
    return path


def source(workspace, entry):
    """! @brief 비교 근거가 된 정확한 XML과 포트 시계열을 읽는다."""
    spec = entry["normalized_result"]
    normalized = (workspace / spec["uri"]).resolve()
    if not normalized.is_relative_to(workspace):
        raise ValueError("보존 결과가 workspace 밖에 있습니다.")
    record = json.loads(sealed(normalized, spec).read_bytes())
    raw = normalized.parent / "raw"
    manifest = {item["role"]: item for item in record["raw_manifest"]["files"]}
    files = {name: sealed(raw / name, manifest["raw/" + name]) for name in ("pcb.xml", *PORT_NAMES)}
    return files, record


def port_points(raw, cutoff):
    """! @brief 같은 시각까지의 복소 전압·전류에서 전력과 입력 임피던스를 산출한다."""
    traces = []
    for name in PORT_NAMES:
        trace = Trace.load((raw / name).read_bytes())
        if -trace.terms[-1][0] / math.tau < cutoff - 4e-12:
            raise ValueError("포트 기록이 공통 시간창을 덮지 않습니다.")
        traces.append(Trace(tuple(term for term in trace.terms if -term[0] / math.tau <= cutoff)))
    rows = []
    for frequency in FREQUENCIES:
        voltage, current = (trace.at(frequency) for trace in traces)
        z = voltage / current
        accepted = 0.5 * (voltage * current.conjugate()).real
        incident = abs(voltage + 50 * current) ** 2 / 400
        if incident <= 0:
            raise ValueError("공통 기준면의 입사 전력은 양수여야 합니다.")
        rows.append({"frequency_hz": frequency, "accepted_w_s2": accepted,
                     "incident_w_s2": incident, "accepted_fraction": accepted / incident,
                     "impedance_ohm": [z.real, z.imag], "voltage_abs_v_s": abs(voltage),
                     "current_abs_a_s": abs(current)})
    return rows


def grid_tokens(tree, axis):
    """! @brief 좌표 원문의 표시 정밀도를 보존한 채 숫자 비교도 가능하게 읽는다."""
    tag = tree.find(f".//RectilinearGrid/{axis}Lines")
    return tag, [item.strip() for item in tag.text.split(",")]


def physical_contract(tree):
    """! @brief 격자 및 출력과 독립된 도체·물성·포트·경계·Gaussian 여기 XML을 대조한다."""
    return [ET.tostring(item) for item in tree.findall(".//Properties/*") if item.tag != "DumpBox"] + [
        ET.tostring(tree.find("FDTD/" + name)) for name in ("Excitation", "BoundaryCond")]


def case_xml(root, fine, changes):
    """! @brief N7의 선택 구간만 N8의 선으로 교체하고 공통 시간 간격을 고정한다."""
    xml = deepcopy(root)
    selection = xml.find("ContinuousStructure/Properties")
    for dump in selection.findall("DumpBox"):
        selection.remove(dump)
    for axis, low, high in changes:
        tag, original = grid_tokens(xml, axis)
        _, reference = grid_tokens(fine, axis)
        if not {low, high} <= set(map(float, original)) & set(map(float, reference)):
            raise ValueError("두 격자의 공통 물리 경계가 필요합니다.")
        new = ([x for x in original if float(x) <= low]
               + [x for x in reference if low < float(x) < high]
               + [x for x in original if float(x) >= high])
        if not all(float(a) < float(b) for a, b in zip(new, new[1:])):
            raise ValueError("교체한 격자 좌표가 단조 증가하지 않습니다.")
        tag.set("Qty", str(len(new)))
        tag.text = ",".join(new)
    if physical_contract(xml) != physical_contract(root):
        raise ValueError("격자 대조 중에 물리 입력이 변경되었습니다.")
    # @brief 진단은 동일한 물리 시간까지 기록하고 제품의 기존 종료 게이트에는 적용하지 않는다.
    fdtd = xml.find("FDTD")
    fdtd.set("TimeStep", format(N8_DT, ".17g"))
    fdtd.set("NumberOfTimesteps", str(math.ceil((DURATION + 0.020e-9) / N8_DT)))
    fdtd.set("endCriteria", "1e-12")
    return ET.tostring(xml, encoding="utf-8", xml_declaration=True)


def planned_xml(name, definition, roots):
    """! @brief 보완 대조는 N8의 세 국부 구간만 N7로 되돌린다."""
    base, replacement = reversed(roots) if name == COMPLEMENT else roots
    return case_xml(base, replacement, definition)


def read_trial(directory, expected_xml, definition):
    """! @brief 지정 XML과 시간 간격을 확인하고 완료된 native 원시 포트만 읽는다."""
    actual = (directory / "pcb.xml").read_bytes()
    if actual != expected_xml:
        raise ValueError("native 격자 입력이 재생성한 통제 조건과 다릅니다.")
    raw_stats = (directory / "openEMS_stats.txt").read_text(encoding="utf-8").splitlines()
    numbers = [line.partition("%")[0].strip() for line in raw_stats]
    keys = ("cells", "timestep_s", "iterations", "numerical_duration_s", "wall_seconds", "cells_per_s")
    statistics = dict(zip(keys, (float(value) for value in numbers if value), strict=True))
    expected_iterations = int(ET.fromstring(actual).find("FDTD").get("NumberOfTimesteps"))
    if (not all(math.isfinite(value) and value > 0 for value in statistics.values())
            or statistics["iterations"] != expected_iterations
            or not math.isclose(statistics["timestep_s"], N8_DT, rel_tol=1e-9)
            or not math.isclose(statistics["numerical_duration_s"], expected_iterations * N8_DT, rel_tol=1e-9)
            or statistics["numerical_duration_s"] < DURATION):
        raise ValueError("고정한 시간 간격과 최종 시간까지의 native 실행을 확인하지 못했습니다.")
    return {"name": directory.name, "changed_intervals_mm": definition,
            "base_grid": "N8" if directory.name == COMPLEMENT else "N7",
            "status": "completed", "input_xml_sha256": hashlib.sha256(actual).hexdigest(),
            "stats": statistics, "points": port_points(directory, DURATION),
            "raw_sha256": {name: sha(directory / name) for name in (*PORT_NAMES, "openEMS_stats.txt", "native.log")}}


def replay_one(name, definition, roots, roots_with_runs):
    """! @brief 한 번 완료된 원시 실행을 덮어쓰지 않고 새 결과로 해석한다."""
    directories = [root / name for root in roots_with_runs if (root / name / "openEMS_stats.txt").is_file()]
    if len(directories) != 1:
        raise ValueError(f"{name} 원시 실행 경로를 한 곳으로 지정하십시오.")
    return read_trial(directories[0], planned_xml(name, definition, roots), definition)


def run_one(executable, directory, definition, root, fine):
    """! @brief 별도 디렉터리에서 하나의 기준면 대조를 실행하고 검증 상태를 고정한다."""
    directory.mkdir()
    path = directory / "pcb.xml"
    expected_xml = planned_xml(directory.name, definition, (root, fine))
    path.write_bytes(expected_xml)
    out = {"name": directory.name, "changed_intervals_mm": definition, "input_xml_sha256": sha(path)}
    started = time.monotonic()
    try:
        with (directory / "native.log").open("wb") as stream:
            proc = subprocess.run([str(executable), "pcb.xml", "--engine=multithreaded",
                                   f"--numThreads={THREADS}", "--dump-statistics", "--exact-endcriteria"],
                                  cwd=directory, stdout=stream, stderr=subprocess.STDOUT, timeout=TIMEOUT, check=False)
        if proc.returncode:
            raise ValueError(f"native가 {proc.returncode}로 종료됐습니다.")
        out = read_trial(directory, expected_xml, definition)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        out.update(status="not_evaluated", error=str(error))
    out["elapsed_seconds"] = time.monotonic() - started
    (directory / "summary.json").write_text(json.dumps(out, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{directory.name} {out['status']} {out['elapsed_seconds']:.1f}s", flush=True)
    return out


def main():
    """! @brief 이전 결과는 읽기만 하고 별도의 비교 결과 디렉터리를 만든다."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "workspace", "destination", "executable"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--case", choices=ALLOWED, action="append", help="선택한 대조만 새 경로에서 실행합니다.")
    parser.add_argument("--replay-from", action="append", type=Path,
                        help="완료된 원시 실행 폴더를 읽기 전용으로 사용합니다.")
    args = parser.parse_args()
    selected = {name: ALLOWED[name] for name in (args.case or ABLATIONS)}
    report = json.loads(args.report.read_bytes())
    entries = {item["settings"]["feature_subdivisions"]: item for item in report["runs"].values()}
    sources = [source(args.workspace.resolve(), entries[level]) for level in (7, 8)]
    roots = [ET.parse(paths["pcb.xml"]).getroot() for paths, _ in sources]
    if (report.get("status") != "completed" or physical_contract(roots[0]) != physical_contract(roots[1])
            or not all(math.isclose(rec["native_statistics"]["timestep_seconds"], dt, rel_tol=1e-9)
                       for (_, rec), dt in zip(sources, (N7_DT, N8_DT), strict=True))):
        raise ValueError("7분할과 8분할의 같은 물리·여기 입력을 확인하지 못했습니다.")
    args.destination.mkdir()
    result = {"schema": "rfad.ro-grid-ablation/0.2", "scope": "native_port_sensitivity_only",
              "mode": "replay" if args.replay_from else "execute",
              "physics_validated": False, "cutoff_seconds": DURATION, "fixed_dt_seconds": N8_DT,
              "native_executable_sha256": sha(args.executable), "settings": selected,
              "original": {f"N{n}": {"sha256": {name: sha(path) for name, path in paths.items()},
                                    "points": port_points(paths["pcb.xml"].parent, DURATION)}
                           for n, (paths, _) in zip((7, 8), sources, strict=True)}}
    (args.destination / "plan.json").write_text(json.dumps(result, allow_nan=False) + "\n", encoding="utf-8")
    if args.replay_from:
        result["runs"] = [replay_one(name, definition, roots, args.replay_from)
                          for name, definition in selected.items()]
    else:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            jobs = [pool.submit(run_one, args.executable, args.destination / name, definition, *roots)
                    for name, definition in selected.items()]
            result["runs"] = [job.result() for job in jobs]
    (args.destination / "report.json").write_text(json.dumps(result, allow_nan=False) + "\n", encoding="utf-8")
    return 0 if all(row["status"] == "completed" for row in result["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
