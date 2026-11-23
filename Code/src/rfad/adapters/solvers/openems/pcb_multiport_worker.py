"""! @brief 감독 WSL 작업에서 포트별 준비 XML과 원시 파형을 봉인하고 전체 S 행렬을 복원한다."""

import json
import math
import shutil

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_multiport_job import PROFILE, raw_names, xml_role
from rfad.adapters.network_touchstone import write_touchstone
from .native import _check_preparation, descriptor, file_identity, require, write_json
from .pcb_multiport import prepare_column, solve_column, port_waves, network_dataset


def prepare(stage, plan, runtime):
    """! @brief 하나의 공통 격자로 각 여기에서 실제 실행할 native XML을 기록한다."""
    case = plan["case"]
    root = stage / "output/prepared"
    root.mkdir()
    lines = mesh_lines(case)
    files, contacts = [], []
    for port in case["ports"]:
        number = port["number"]
        xml = root / f"port-{number}.xml"
        contacts.append(prepare_column(xml, case, lines, number))
        files.append(descriptor(stage, xml, xml_role(number)))
    counts = [len(lines[k]) for k in "xyz"]
    mesh = {"lines_mm": lines, "line_counts": counts, "native_grid_points": math.prod(counts),
            "yee_interval_cells": math.prod(n-1 for n in counts), "fdtd_executed": False}
    consumed = {"consumed_case": case, "contacts_by_excitation": contacts, "fdtd_executed": False}
    preparation = {"schema": "rfad.preparation-artifact/0.1", "analysis_plan_id": plan["plan_id"],
                   "analysis_plan_hash": canonical_hash(plan), "profile": PROFILE, "mesh_statistics": mesh,
                   "consumption_report": consumed, "normalization": plan["normalization"], "runtime_identity": runtime}
    for role, key in (("mesh_statistics", "mesh_statistics"), ("consumption_report", "consumption_report"),
                      ("runtime_provenance", "runtime_identity"), ("normalization", "normalization")):
        path = root / (role + ".json")
        write_json(path, preparation[key])
        files.append(descriptor(stage, path, role))
    preparation["files"] = files
    path = root / "preparation.json"
    write_json(path, preparation)
    return preparation, files + [descriptor(stage, path, "preparation_artifact")]


def solve(stage, request, inputs, runtime):
    """! @brief 준비된 여러 XML을 각자 실행하고 원본 전압, 전류와 종료 증거를 보존한다."""
    _check_preparation(request, inputs)
    plan = request["analysis_plan"]
    case = plan["case"]
    root = stage / "output/raw"
    root.mkdir()
    files, runs = [], []
    for port in case["ports"]:
        number = port["number"]
        raw = root / str(number)
        raw.mkdir()
        xml = raw / "pcb.xml"
        shutil.copyfile(inputs[xml_role(number)], xml)
        runs.append({"excited_port": number, **solve_column(raw, case, runtime.get("executable"))})
        require(file_identity(xml) == file_identity(inputs[xml_role(number)]), "실행한 여기 XML이 바뀌었습니다.", "E_HASH")
        for name in raw_names(len(case["ports"])):
            files.append(descriptor(stage, raw / name, f"raw/{number}/{name}"))
    manifest = {"analysis_plan_hash": canonical_hash(plan), "prepared_plan_hash": canonical_hash(request["prepared_plan"]),
                "runs": runs, "files": files}
    path = stage / "output/raw_manifest.json"
    write_json(path, manifest)
    return manifest, files + [descriptor(stage, path, "raw_manifest")]


def postprocess(stage, request, inputs, runtime, manifest=None):
    """! @brief 저장된 여기별 파형만 사용해 전체 행렬을 계산한다. 후처리 재실행도 FDTD를 시작하지 않는다."""
    import numpy as np

    preparation = _check_preparation(request, inputs)
    plan = request["analysis_plan"]
    case, source = plan["case"], plan["source_semantics"]
    ports = case["ports"]
    files = []
    root = stage / "output/raw"
    if manifest is None:
        require("raw_manifest" in inputs, "다중 포트 원시 manifest가 필요합니다.", "E_MISSING_ARTIFACT")
        manifest = json.loads(inputs["raw_manifest"].read_bytes())
        root.mkdir()
        originals = {r["role"]: r for r in manifest["files"]}
        for port in ports:
            raw = root / str(port["number"])
            raw.mkdir()
            for name in raw_names(len(ports)):
                role = f"raw/{port['number']}/{name}"
                require(role in inputs and role in originals, "원시 포트 파일이 없습니다.", "E_MISSING_ARTIFACT")
                shutil.copyfile(inputs[role], raw / name)
                item = descriptor(stage, raw / name, role)
                require(item == originals[role], "원시 포트 파일의 봉인이 다릅니다.", "E_HASH")
                files.append(item)
        path = stage / "output/raw_manifest.json"
        write_json(path, manifest)
        files.append(descriptor(stage, path, "raw_manifest"))
    require(manifest["analysis_plan_hash"] == canonical_hash(plan)
            and manifest["prepared_plan_hash"] == canonical_hash(request["prepared_plan"]), "원본 계획과 파형이 다릅니다.", "E_HASH")
    band = case["frequency_hz"]
    frequencies = np.asarray(band.get("points", np.linspace(band["start"], band["stop"], band["count"])))
    columns = [port_waves(root / str(p["number"]), case, frequencies) for p in ports]
    identity = {"project_id": source["project_id"], "revision_id": source["revision_id"], "snapshot": plan["snapshot"],
                "source_sha256": canonical_hash(source), "settings_sha256": canonical_hash(case["settings"]),
                "case_sha256": canonical_hash(case), "mesh_sha256": canonical_hash(preparation["mesh_statistics"]["lines_mm"]),
                "runtime_manifest_sha256": runtime["manifest_sha256"], "raw_manifest_sha256": canonical_hash(manifest)}
    data = network_dataset(columns, case, source, frequencies, identity, plan.get("physical_setup_omissions", []))
    result = {"schema": PROFILE, "analysis_plan_id": plan["plan_id"], "prepared_plan_id": request["prepared_plan"]["prepared_plan_id"],
              "snapshot": plan["snapshot"], "network": data, "raw_manifest": manifest,
              "normalization": plan["normalization"], "measurement_validated": False}
    path = stage / "output/normalized.json"
    write_json(path, result)
    exchange = stage / f"output/network.s{len(ports)}p"
    exchange.write_bytes(write_touchstone(data))
    return result, files + [descriptor(stage, path, "normalized_result"), descriptor(stage, exchange, "touchstone")]
