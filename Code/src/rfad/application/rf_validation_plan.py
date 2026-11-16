"""! @brief 실행 전에 고정하는 내부 RF 참조 캠페인과 검증 범위를 정의한다."""

from copy import deepcopy
import hashlib
from pathlib import Path

from rfad.application.canonical import canonical_hash
from rfad.application.rf_reference_contract import CASE, GRIDS_MM, case_spec
from rfad.domain.rf_reference import DIPOLE_DIRECTIVITY, DIPOLE_LIMITS, DIPOLE_SOURCE, SHEET_SOURCE


PROFILE = "rfad.rf-validation/0.1"
BUDGET = {"native_solves": 9, "worker_calls": 27, "analysis_seconds": 4500,
          "worker_reserved_seconds": 8280, "wall_seconds": 10800,
          "disk_bytes": 8 * 1024**3, "case_output_bytes": 128 * 1024**2,
          "artifact_bytes": 64 * 1024**2, "memory_estimate_bytes": 1024**3}
ASSUMPTIONS = [
    "합성 PEC/진공 참조이며 사용자의 PCB 형상이나 제조사 물성을 소비하지 않습니다.",
    "실행하지 않은 경계/종료조건 축과 제작/실측 조건은 미확립으로 유지합니다.",
    "준비, 계산 종료, 독립 모델 비교, 수렴, 실측 검증은 별도 상태입니다.",
    "원래 결과의 판정을 바꾸지 않고 별도 불변 보고서에 이번 비교를 기록합니다.",
    "예산은 캠페인 누적 상한입니다. 차단 사례의 예약을 다른 계산으로 전용하지 않습니다.",
]
LIMITATIONS = [
    "RO4350B 국부 방사 도체 손실 변화 2.788446%는 초기 2% 기준 미확립입니다.",
    "GHz PTH의 독립 물리 정확도는 미확립입니다. 저전도도 산술 검증과 구분합니다.",
    "총 전력 수지와 실행 종료를 개별 손실 또는 실측 정확도 합격으로 확대하지 않습니다.",
    "유한 급전의 단면/단자/도체 우선순위가 미정이므로 새 치수를 임의로 입력하지 않습니다.",
    "메모리는 추정 상한이며 OS 강제 한도가 아닙니다. 작업 슬롯은 동일 workspace 안에서 공유합니다.",
]


def assessment_engine():
    """! @brief 별도 판정 구현의 실제 소스를 기록하고 실행 도중 판정식을 바꾸지 않는다."""
    root = Path(__file__).resolve().parents[1]
    paths = ("application/rf_validation_plan.py", "application/rf_validation_assessment.py", "domain/rf_reference.py")
    files = []
    for name in paths:
        raw = (root / name).read_bytes()
        files.append({"path": "src/rfad/" + name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    return {"profile": "rfad.rf-assessment-source/0.1", "files": files, "sha256": canonical_hash(files)}


def definition(document, runtime, name):
    """! @brief 세 개 참조군의 수준과 차단 이유를 결과를 보기 전에 고정한다."""
    cases = []
    for level, grid in enumerate(GRIDS_MM, 1):
        spec = case_spec({"case": CASE, "grid_mm": grid}, document["project_id"])
        cases.append({"case_id": "dipole-" + str(level), "name": "PEC 다이폴 / 격자 수준 " + str(level),
            "group": "dipole", "axis": "interior_grid_mm", "level": level, "grid_mm": grid,
            "blocked_reason": None, "settings": {"case": CASE, "grid_mm": grid},
            "fixture": spec, "fixture_hash": canonical_hash(spec), "analysis_seconds": 300})
    for group, levels, reason, title in (
        ("sheet", (1.0, 0.75, 0.5), "native_excitation_and_boundary_contract_unresolved", "평면 도체 독립 참조"),
        ("finite_feed", (4, 5, 6), "finite_feed_cross_section_and_terminal_contract_unresolved", "유한 급전 손실"),
    ):
        for level, value in enumerate(levels, 1):
            cases.append({"case_id": group + "-" + str(level), "name": title + " / 수준 " + str(level),
                "group": group, "axis": "planned_grid_mm" if group == "sheet" else "planned_refinement",
                "level": level, "grid_mm": value if group == "sheet" else None,
                "planned_level": value, "blocked_reason": reason, "settings": None, "fixture": None,
                "fixture_hash": None, "analysis_seconds": 300 if group == "sheet" else 900})
    return {"schema": PROFILE, "name": name, "project_id": document["project_id"],
        "revision_id": document["revision_id"], "project_hash": canonical_hash(document),
        "runtime_identity": deepcopy(runtime), "assessment_engine": assessment_engine(),
        "cases": cases, "budget": deepcopy(BUDGET),
        "assumptions": list(ASSUMPTIONS), "limitations": list(LIMITATIONS),
        "source_refs": [DIPOLE_SOURCE, SHEET_SOURCE,
            "RO4350B 기존 N8: 2.788446% / 초기 국부 손실 기준 2%", "RFAD-D0-3.4 / VT-011 / VT-030"],
        "criteria": {"dipole": deepcopy(DIPOLE_LIMITS), "reference_directivity": DIPOLE_DIRECTIVITY,
            "dipole_scope": "기존 이상 반파장 비교 초도 기준. 유한 반경 형상의 정확해가 아님.",
            "mesh_relative_change_acceptance": None,
            "mesh_policy": "세 격자의 변화량만 기록. 새 합격 한계를 사후 설정하지 않음.",
            "ro4350b_local_loss_relative_limit": 0.02, "loss_absolute_floor": 1e-5,
            "total_power_balance_limit": 0.03},
        "manufacturing": None, "measurement": None, "finite_feed_cross_section": None,
        "automatic_retry": False, "native_concurrency": 1, "phase_order": ["plan", "prepare", "solve", "postprocess"]}


def display_budget(values):
    """! @brief 저장값을 변경하지 않고 서비스에서 예산의 공학 단위를 표시한다."""
    result = {}
    for name, value in values.items():
        unit = "bytes" if name.endswith("bytes") else "s" if name.endswith("seconds") else "count"
        text = str(value)
        if unit == "bytes":
            divisor, label = (1024**3, "GiB") if value >= 1024**3 else (1024**2, "MiB")
            text = f"{value / divisor:.4g} {label}"
        elif unit == "s":
            text = f"{value / 60:.4g} min" if value >= 60 else f"{value:.4g} s"
        result[name] = {"value": value, "unit": unit, "text": text}
    return result
