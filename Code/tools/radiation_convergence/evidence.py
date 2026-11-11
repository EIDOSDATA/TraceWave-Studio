"""! @brief 방사 연구의 봉인된 입력을 재조회하고 불변 판정과 CSV를 보존한다."""

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import validate_pcb_plan
from rfad.application.pcb_radiation import raw_names
from rfad.application.radiation_study import require
from verify_openems_worker import call


CODE_ROOT = Path(__file__).resolve().parents[2]


def reference(item):
    """! @brief 공개 조회의 파일 참조를 정확한 바이트 식별자로 축소한다."""
    return {key: item[key] for key in ("uri", "sha256", "bytes")}


def load_cases(service, report, definitions):
    """! @brief 진행표의 다른 정상 결과 대입과 원시 면의 변경도 재판정 전에 차단한다."""
    cases, cache = [], {}
    for definition in definitions:
        key = definition["settings_hash"]
        entry = report["runs"][key]
        require(entry.get("status") == "completed" and entry["settings"] == definition["settings"], "완료한 동일 수치 설정의 결과가 필요합니다.")
        if key not in cache:
            opened = call(service, "result.open", {"artifact_id": entry["artifact_id"]}, report["subject"]["context"])
            require(opened["artifact_id"] == entry["artifact_id"], "결과 산출물 식별자가 다릅니다.")
            roles = {item["role"]: item for item in opened["files"]}
            require(reference(roles["normalized_result"]) == entry["normalized_result"], "등록한 정규화 결과 참조가 바뀌었습니다.")
            require(reference(roles["radiation_result"]) == entry["radiation_result"], "등록한 방사 필드 참조가 바뀌었습니다.")
            for item in opened["files"]:
                service.journal.read_artifact(reference(item))
            normalized = json.loads(service.journal.read_artifact(entry["normalized_result"]))
            radiation = json.loads(service.journal.read_artifact(entry["radiation_result"]))
            plan = normalized["provenance"]["analysis_plan"]
            validate_pcb_plan(plan)
            require(json.loads(service.journal.read_artifact(entry["analysis_plan"]["artifact"])) == plan, "별도 봉인한 원래 계획과 결과 내부 계획이 다릅니다.")
            require(plan["runtime_identity"] == report["runtime_identity"] and plan["snapshot"] == report["subject"]["snapshot"], "원래 연구의 worker/스냅샷과 다릅니다.")
            require(plan["plan_id"] == entry["analysis_plan"]["plan_id"] and canonical_hash(plan) == entry["analysis_plan"]["content_hash"], "진행표의 원래 계획과 결과가 다릅니다.")
            require(plan["case"]["settings"] == definition["settings"], "방사 결과의 설정이 해당 연구 사례와 다릅니다.")
            raw = normalized["raw_manifest"]
            raw_roles = {"raw/" + name for name in raw_names(plan)}
            require(set(roles) == raw_roles | {"raw_manifest", "normalized_result", "provenance", "radiation_result", "radiation_native"}, "방사 연구 결과의 필수 봉인 파일이 부족하거나 중복되었습니다.")
            require(len(raw["files"]) == len(raw_roles) and {item["role"] for item in raw["files"]} == raw_roles, "원시 manifest에는 포트와 12면 E/H 전체가 필요합니다.")
            require(json.loads(service.journal.read_artifact(reference(roles["raw_manifest"]))) == raw, "별도 봉인한 원시 manifest가 결과와 다릅니다.")
            for item in raw["files"]:
                require(item["sha256"] == roles[item["role"]]["sha256"] and item["bytes"] == roles[item["role"]]["bytes"], "원시 manifest와 봉인된 기록 면이 다릅니다.")
            cache[key] = (normalized, radiation)
        normalized, radiation = cache[key]
        cases.append({**definition, "normalized_result": normalized, "radiation_result": radiation,
                      "artifact": {"artifact_id": entry["artifact_id"], "normalized": entry["normalized_result"], "radiation": entry["radiation_result"]}})
    return cases


def publish_assessment(report_path, report, cases, assessment):
    """! @brief 원본/이전 판정을 변경하지 않고 판정기 사본까지 불변 파일에 남긴다."""
    paths = [CODE_ROOT / ("src/rfad/application/" + name + ".py") for name in
             ("radiation_study", "radiation_study_guards", "radiation_comparison", "radiation_assessment", "pcb_radiation", "convergence")]
    paths.extend([Path(__file__).resolve(), CODE_ROOT / "tools/verify_pcb_radiation_convergence.py"])
    evaluator = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        raw = source.encode("utf-8")
        evaluator.append({"path": path.relative_to(CODE_ROOT).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "source_utf8": source})
    record = {"schema": "rfad.pcb-radiation-assessment/0.1", "created_at": datetime.now(timezone.utc).isoformat(),
              "study_hash": report["study_hash"], "fixture_hash": report["fixture_hash"], "evaluator": evaluator,
              "inputs": [{"label": row["label"], "axis": row["axis"], "artifact": row["artifact"]} for row in cases], "assessment": assessment}
    raw = canonical_bytes(record)
    directory = report_path.with_name(report_path.stem + ".assessments")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (str(uuid4()) + ".json")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    ref = {"path": path.relative_to(report_path.parent).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    report.setdefault("assessment_history", []).append(ref)
    report["assessment_artifact"] = ref


def write_metrics(path, assessment):
    """! @brief 음의 추론 손실과 미평가 흡수 전력을 0이나 합격값으로 바꾸지 않는다."""
    rows = assessment["power_balance"]["cases"]
    keys = ["frequency_hz", "incident_power_w_s2", "reflected_power_w_s2", "accepted_power_w_s2", "radiated_power_w_s2",
            "sphere_power_w_s2", "inferred_loss_w_s2", "independent_absorption_power_w_s2", "port_wave_relative_residual",
            "sphere_relative_error", "passivity_excess_fraction", "strict_passivity_status", "status"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case", "axis", *keys])
        for row in rows:
            for frequency in row["frequencies"]:
                writer.writerow([row["label"], row["axis"], *[frequency[key] for key in keys]])
