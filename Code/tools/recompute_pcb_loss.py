"""! @brief 보존된 FDTD 필드를 새 독립 손실 판정기로 재계산하는 명시적 CLI다."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from loss_recalculation import run


def main():
    """! @brief 새 경로에서만 계산하며 원래 solver 결과/정규화는 변경하지 않는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-report", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.producer_report, args.destination.resolve())
        print(result["assessment"]["status"])
        return 0 if result["assessment"]["status"] == "passed" else 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
