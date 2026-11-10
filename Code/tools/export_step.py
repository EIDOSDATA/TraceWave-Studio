"""! @brief 등록된 프로젝트의 불변 스냅샷에서 CAD/STEP 작업을 실행한다."""

import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4


def main() -> int:
    """! @brief GUI와 동일한 서비스 API로 접수하고 실제 artifact 참조를 출력한다."""
    parser = argparse.ArgumentParser(description="Build a geometry-only AP242 STEP package from an immutable snapshot.")
    parser.add_argument("--workspace", type=Path, required=True, help="서비스가 사용 중이지 않은 프로젝트 작업 영역")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--project", help="현재 영속 개정에서 새 스냅샷을 만들 등록 경로: projects/이름")
    source.add_argument("--snapshot-file", type=Path, help="snapshot.create가 반환한 SnapshotRef JSON")
    parser.add_argument("--cad-python", type=Path, required=True, help="격리 CAD 가상환경의 Python 실행 파일")
    parser.add_argument("--report", type=Path, help="새 결과 JSON 경로. 기존 파일은 덮어쓰지 않는다.")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from rfad.application.cad import PROFILE
    from rfad.application.cad_jobs import CadRuntime
    from rfad.application.projects import ProjectService
    from rfad.domain.errors import ProjectError

    def query(service, job_id):
        """! @brief 처리 중 상태와 terminal 이벤트를 읽는다."""
        return service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": job_id}})

    def request(service, data, project_id=None):
        """! @brief 현재 발급 epoch로 각 명령을 한 번만 접수한다."""
        return {"contract_version": "rfad.api/2.0", "context": {} if project_id is None else {"project_id": project_id},
                "input": data, "request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"]}

    def wait(service, task):
        """! @brief 상태를 기다리되 Ctrl+C는 소유 CAD 작업의 취소로 연결한다."""
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                status = query(service, task["job_id"])
                if status["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                    if status["state"] != "completed":
                        error = status["events"][-1].get("error", {})
                        raise ProjectError(error.get("code", "E_GEOMETRY"), error.get("message_ko", "출력 작업이 완료되지 않았습니다: " + status["state"]))
                    return status["events"][-1]["operation_result"]
                time.sleep(0.05)
            raise ProjectError("E_RESOURCE", "출력 작업의 완료 대기 시간을 초과했습니다.")
        except (KeyboardInterrupt, ProjectError):
            service.mutate("job.cancel", request(service, {"job_id": task["job_id"], "reason": "CLI 대기 중단"}))
            raise

    try:
        if options.report is not None and options.report.exists():
            raise ProjectError("E_CONFLICT", "기존 보고서를 덮어쓸 수 없습니다. 새 경로를 지정하십시오.")
        runtime = CadRuntime(options.cad_python)
        with ProjectService(options.workspace, cad_runtime=runtime) as service:
            if options.project is not None:
                opened = wait(service, service.mutate("project.open", request(service, {"path": options.project, "open_mode": "open"})))
                snapshot = wait(service, service.mutate("snapshot.create", request(service,
                    {"expected_revision": opened["revision_id"], "description": "STEP 기하 출력용 불변 입력"}, opened["project_id"])))
            else:
                with options.snapshot_file.open("rb") as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ProjectError("E_RESOURCE", "SnapshotRef JSON은 64 KiB 이내여야 합니다.")
                snapshot = json.loads(raw)
            data = {"snapshot": {"snapshot_id": snapshot["snapshot_id"], "content_hash": snapshot["content_hash"]},
                    "format": "step", "profile": PROFILE}
            result = wait(service, service.mutate("export.build", request(service, data, snapshot["project_id"])))
            result["workspace"] = str(service.workspace)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if options.report is not None:
            options.report.parent.mkdir(parents=True, exist_ok=True)
            with options.report.open("x", encoding="utf-8") as stream:
                stream.write(text)
        print(text, end="")
        return 0
    except (OSError, ValueError, KeyError, ProjectError) as error:
        print(json.dumps({"status": "failed", "code": getattr(error, "code", "E_SCHEMA"), "message_ko": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("출력 작업을 취소했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
