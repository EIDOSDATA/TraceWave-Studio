"""! @brief 기록된 Altium NC 재출력의 바이트, 유한 슬롯, 좌표 차이와 누락 속성을 대조한다."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.adapters.exchange.cam_reader import read_xnc


def inspect(row, digits, precision_mm):
    """! @brief 봉인 CRLF 원문에서 좌표·도금·객체 ID를 직접 다시 읽는다."""
    raw = ("\r\n".join(row["export_lines"]) + "\r\n").encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != row["export_sha256"]:
        raise ValueError("재출력 행에서 복원한 파일의 SHA256이 기록과 다릅니다.")
    data = read_xnc(raw, metric_fixed_digits=digits)
    round_hole, slot = data["holes"]
    old_hole, old_slot = row["source"]["holes"]
    if (round_hole["kind"], slot["kind"]) != ("circle", "slot"):
        raise ValueError("같은 원형 홀과 직선 슬롯이 필요합니다.")
    if not math.isclose(round_hole["finished_diameter_mm"], old_hole["finished_diameter_mm"], abs_tol=1e-12):
        raise ValueError("재출력의 원형 홀 완성 지름이 다릅니다.")
    if not math.isclose(slot["finished_width_mm"], old_slot["finished_width_mm"], abs_tol=1e-12):
        raise ValueError("재출력의 슬롯 완성 폭이 다릅니다.")
    length = math.dist(slot["start_mm"], slot["end_mm"]) + slot["finished_width_mm"]
    if not math.isclose(length, row["finished_slot_length_mm"], abs_tol=1e-12):
        raise ValueError("재출력의 슬롯 총 길이가 다릅니다.")
    pairs = [(round_hole, old_hole, "center_mm"), (slot, old_slot, "start_mm"), (slot, old_slot, "end_mm")]
    offsets = [[a - b for a, b in zip(new[key], old[key], strict=True)] for new, old, key in pairs]
    common = all(abs(a - b) < 1e-9 for offset in offsets for a, b in zip(offset, offsets[0], strict=True))
    if not common or any(abs(d) > precision_mm + 1e-9 for delta in offsets for d in delta):
        raise ValueError("출력의 한 좌표 단위 안에서 일관된 관측 위치 차이를 확인하지 못했습니다.")
    if data["plating"] != "unknown" or any(item["attributes"] for item in data["holes"]):
        raise ValueError("원문에 담긴 도금 또는 객체 속성이 이전 기록과 다릅니다.")
    return {"export_sha256": digest, "source_sha256": row["source_sha256"], "export_bytes": len(raw),
            "offsets_mm": offsets, "consistent_translation_within_export_unit": common,
            "finished_slot_length_mm": length, "plating": data["plating"], "losses": data["losses"],
            "object_identity_preserved": False, "origin_correction_applied": False}


def main():
    """! @brief 이전 물리 설정과 두 재출력 파일의 증거를 함께 읽는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    record = json.loads(args.report.read_bytes())
    settings = record["settings"]
    if (settings["units"], settings["coordinates"], settings["zero_suppression"]) != ("mm", "absolute", "none"):
        raise ValueError("원본 검토의 mm 절대좌표와 생략 없음 선언이 필요합니다.")
    digits = (settings["integer_digits"], settings["decimal_digits"])
    result = {"schema": "rfad.altium-nc-reexport-review/0.1",
              "original_report_sha256": hashlib.sha256(args.report.read_bytes()).hexdigest(),
              "scope": "recorded_altium_reexport_only", "settings": settings, "files": {
                  name: inspect(record[name], digits, 10**(-digits[1])) for name in ("plated", "unplated")}}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
