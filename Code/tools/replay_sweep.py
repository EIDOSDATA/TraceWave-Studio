"""! @brief 보존 묶음과 계산 명세로 별도 작업 공간에서 연구를 다시 검토하고 선택 실행한다."""

import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application import design_sweep_service as sweep, project_archive
from rfad.application.canonical import canonical_hash
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from rfad.domain.errors import ProjectError


def _read_bytes(path, maximum):
    """! @brief 증거와 묶음의 입력 크기를 읽는 동안 제한한다."""
    with Path(path).open("rb") as stream:
        data = stream.read(maximum + 1)
    if not 0 < len(data) <= maximum:
        raise ProjectError("E_RESOURCE", "계산 명세 또는 복원 묶음의 크기를 확인하십시오.")
    return data


def _verify_recipe(recipe, backup):
    """! @brief 읽기 전용 결과를 복원하기 전에 정확히 같은 원본 스냅샷을 확인한다."""
    if type(recipe) is not dict or recipe.get("schema") != "rfad.sweep-recipe/0.1":
        raise ProjectError("E_VERSION", "지원하는 연구 계산 명세가 필요합니다.")
    if recipe.get("recipe_sha256") != canonical_hash({key: value for key, value in recipe.items() if key != "recipe_sha256"}):
        raise ProjectError("E_HASH", "계산 명세의 SHA256이 일치하지 않습니다.")
    with project_archive.read_verified(backup) as (_, manifest, _):
        expected = (recipe["project_id"], recipe["design_revision_id"], recipe["snapshot"]["content_hash"])
        actual = (manifest["project_id"], manifest["revision_id"], manifest["content_hash"])
        if actual != expected or recipe["snapshot"]["revision_id"] != manifest["revision_id"]:
            raise ProjectError("E_HASH", "복원 묶음의 현재 개정과 계산 명세의 설계 스냅샷이 다릅니다.")


def replay(recipe, backup, workspace, *, runtime=None, run=False):
    """! @brief 새 작업 공간에서 같은 원본, 후보, 계산 엔진을 확인하고 필요할 때만 실행한다."""
    _verify_recipe(recipe, backup)
    workspace = Path(workspace)
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        raise ProjectError("E_CONFLICT", "독립 검토에는 비어 있는 작업 공간을 선택하십시오.")
    with ProjectService(workspace, solver_runtime=runtime, auto_run=run) as service:
        context = {"project_id": recipe["project_id"]}
        reviewed = project_archive.preview_restore(service, backup)
        project_archive.restore(service, backup, reviewed["review_hash"])
        state = service.journal.read()
        project = state["projects"][context["project_id"]]
        source = service._load(project)
        inputs = {"expected_revision": source["revision_id"], "specification": recipe["original_specification"]}
        api = service.host_calculation_context
        preview, specification, network, actual_runtime, engine = sweep.preview(api, state, project, source, inputs)
        checks = {
            "source_snapshot": canonical_hash(source) == recipe["snapshot"]["content_hash"],
            "candidate_count": preview["candidate_count"] == recipe["candidate_count"],
            "specification": specification == recipe["specification"],
            "solver_runtime": actual_runtime == recipe["runtime_identity"],
            "calculation_engine": engine == recipe["engine_identity"],
            "network_dataset": (None if network is None else network["dataset"]["sha256"]) == recipe["network_dataset_sha256"],
            "network_circuit": (None if network is None else canonical_hash(network["circuit"])) == recipe["network_circuit_sha256"],
        }
        if "review_sha256" in recipe:
            checks["review_sha256"] = preview["review_hash"] == recipe["review_sha256"]
        report = {"schema": "rfad.sweep-independent-replay/0.1", "source_study_id": recipe["study_id"],
                  "source_revision_id": source["revision_id"], "review_sha256": preview["review_hash"],
                  "checks": checks, "counts": preview["counts"], "matches": all(checks.values()),
                  "replayed_study_id": None, "state": "reviewed", "performed_calculation": False}
        if not run or not report["matches"]:
            return report

        def request(data):
            """! @brief 새 작업 공간의 쓰기 정책과 영수증을 사용한다."""
            return {"contract_version": "rfad.api/2.0", "context": context, "input": data,
                    "request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"]}

        created = service.mutate("sweep.create", request({**inputs, "review_hash": preview["review_hash"]}))
        study_id = created["study_id"]
        service.mutate("sweep.start", request({"study_id": study_id}))
        terminal = {"completed", "failed", "interrupted", "cancelled", "blocked"}
        deadline = time.monotonic() + float(specification["budget"]["wall_seconds"]) + 30
        while time.monotonic() <= deadline:
            study = service.journal.read()["sweeps"][study_id]
            if study["state"] in terminal:
                report.update(replayed_study_id=study_id, state=study["state"], result_counts=study["counts"],
                              performed_calculation=bool(study["physical_cache"] or study["usage"]["native_solves"]))
                return report
            time.sleep(0.2)
        service.mutate("sweep.cancel", request({"study_id": study_id}))
        raise ProjectError("E_RESOURCE", "명세의 작업 시간 예산에 도달했습니다.")


def main():
    """! @brief 보존 ZIP과 명세, 사용자가 선택한 새 작업 공간을 받는다."""
    parser = argparse.ArgumentParser(description="보존된 연구를 별도 작업 공간에서 검토하거나 다시 실행합니다.")
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--openems-wsl", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    try:
        recipe = json.loads(_read_bytes(args.recipe, 512 * 1024))
        backup = _read_bytes(args.archive, project_archive.MAX_ARCHIVE_BYTES)
        runtime = SolverRuntime() if args.openems_wsl else None
        report = replay(recipe, backup, args.workspace, runtime=runtime, run=args.run)
    except (ProjectError, KeyError, ValueError, TypeError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["matches"] and (not args.run or report["state"] == "completed") else 1


if __name__ == "__main__":
    sys.exit(main())
