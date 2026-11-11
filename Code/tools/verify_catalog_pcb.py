"""! @brief 저장된 카탈로그 PCB의 입력/CAD/해석과 재열기를 검증하는 CLI다."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.application.cad_runtime import CadRuntime
from rfad.application.solver_jobs import SolverRuntime
from catalog_pcb_verification.runner import run


def main():
    """! @brief 물성이나 수치 조건을 기본값으로 채우지 않고 명시적 실행만 허용한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mode", choices=("inspect", "cad", "full"), default="inspect")
    parser.add_argument("--cad-python", type=Path)
    parser.add_argument("--openems-wsl", action="store_true")
    parser.add_argument("--settings-file", type=Path)
    parser.add_argument("--expected-revision")
    args = parser.parse_args()
    try:
        settings = json.loads(args.settings_file.read_text(encoding="utf-8")) if args.settings_file else None
        report = run(args.workspace, args.project, args.report, mode=args.mode, settings=settings,
                     cad_runtime=CadRuntime(args.cad_python) if args.cad_python else None,
                     solver_runtime=SolverRuntime() if args.openems_wsl else None, expected_revision=args.expected_revision)
        print(json.dumps({"status": report["status"], "report": str(args.report.resolve()),
                          "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))
        return 3 if report["status"] == "needs_inputs" else 2 if report["status"] == "failed" else 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
