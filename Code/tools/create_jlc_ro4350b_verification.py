"""! @brief 출처와 미정 납품 물성을 보존한 JLC RO4350B 탐색 입력 생성 CLI다."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from manufacturing_verification.jlc_ro4350b import CODE_ROOT, run


def main():
    """! @brief 기본값으로 근사를 허용하지 않으며 새 경로에만 결과를 저장한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=CODE_ROOT / ".local/pcb-catalog/catalog.sqlite")
    parser.add_argument("--accept-approximations", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.workspace, args.report, args.database, accept_approximations=args.accept_approximations)
        print(json.dumps({key: result[key] for key in ("status", "workspace", "project_path")}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        if getattr(error, "details", None):
            print(json.dumps(error.details, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
