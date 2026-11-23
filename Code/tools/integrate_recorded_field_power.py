"""! @brief 보존된 PCB 복소 E/H 체적에서 직사각면, 직육면체 6면 또는 지정 곡면 통과량을 읽는다."""

import argparse
import json
from pathlib import Path

from verify_openems_worker import ProjectService, call


def main():
    """! @brief 프로젝트 결과 UUID와 mm 경계로 읽기 전용 적분 RPC를 호출한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("artifact", help="봉인된 솔버 결과 UUID")
    parser.add_argument("--frequency-index", type=int, default=0)
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--normal", choices=("+x", "-x", "+y", "-y", "+z", "-z"))
    kind.add_argument("--box", action="store_true", help="모든 면의 바깥쪽 통과량과 합")
    kind.add_argument("--surface", type=Path, metavar="JSON", help="mm 유향 삼각 곡면")
    parser.add_argument("--bounds", type=float, nargs=6,
                        metavar=("X0", "X1", "Y0", "Y1", "Z0", "Z1"), help="성분 공통 체적 안의 경계(mm)")
    args = parser.parse_args()
    if (args.surface is None) != (args.bounds is not None):
        parser.error("직사각면과 직육면체에는 --bounds를 지정하고 곡면에는 --surface만 지정하십시오.")
    if args.surface is not None:
        with args.surface.open("rb") as stream:
            raw = stream.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            parser.error("곡면 파일은 512 KiB까지 지원합니다.")
        surface = json.loads(raw)
    else:
        surface = {"kind": "box" if args.box else "rectangle",
                   "bounds_mm": [args.bounds[i:i + 2] for i in (0, 2, 4)]}
        if not args.box:
            surface.update(axis=args.normal[1], direction=1 if args.normal[0] == "+" else -1)
    with ProjectService(args.workspace, auto_run=False) as service:
        record = service.journal.read()["solver_results"][args.artifact]
        context = {"project_id": record["project_id"]}
        source = {"kind": "solver", "artifact_id": args.artifact}
        pin = call(service, "result.describe", {"source": source}, context)["pin"]
        report = call(service, "result.field.flux", {"source": source, "pin": pin, "surface": surface,
                      "frequency_index": args.frequency_index}, context)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
