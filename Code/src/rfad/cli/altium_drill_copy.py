"""! @brief Studio의 비도금 원형 홀 XNC에서 Altium 검토용 NC 사본을 만든다."""

import argparse
import hashlib
import json
import re
from decimal import Decimal
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from rfad.adapters.exchange.cam_reader import MAX_BYTES, read_xnc
from rfad.domain.errors import ProjectError


def _fixed(value, places, field):
    """! @brief 실제 검증된 자릿수로 손실 없이 표시할 수 있는 값만 변환한다."""
    number = Decimal(str(value))
    scaled = number.scaleb(places)
    if not 0 <= number < 100 or scaled != scaled.to_integral_value():
        raise ProjectError("E_UNSUPPORTED", f"{field}의 값이 Altium 검토용 고정 자릿수에 정확히 들어가지 않습니다.")
    return int(scaled)


def make_copy(raw):
    """! @brief mm 절대 좌표를 보존하고 도금 또는 슬롯의 의미를 추정하지 않는다."""
    source = read_xnc(raw)
    attributes = source["file_attributes"]
    holes = source["holes"]
    if (source["unit"] != "mm" or source["plating"] != "unplated"
            or attributes.get(".FileFunction", [])[-1:] != ["NPTH"]
            or not holes or any(hole["kind"] != "circle" for hole in holes)):
        raise ProjectError("E_UNSUPPORTED", "mm로 명시한 비도금 원형 홀 XNC만 Altium 검토 사본으로 변환합니다.")
    # @brief 기존 XNC 파서의 float보다 더 정밀한 원문을 받아 정밀도 소실을 놓치지 않는다.
    if any(re.search(rb"\.[0-9]{7}", line.split(b";", 1)[0]) for line in raw.splitlines()):
        raise ProjectError("E_UNSUPPORTED", "소수점 아래 6자리를 넘는 XNC 수치는 이 검토 사본에서 지원하지 않습니다.")
    rows = [(_fixed(hole["finished_diameter_mm"], 4, "완성 홀 지름"), hole["center_mm"]) for hole in holes]
    widths = sorted({width for width, _ in rows})
    if 0 in widths or len(widths) > 99:
        raise ProjectError("E_UNSUPPORTED", "완성 홀 지름과 공구 식별자 수가 NC 사본 범위를 벗어납니다.")
    tool_number = {width: index for index, width in enumerate(widths, start=1)}
    lines = ["M48", "METRIC", "FMAT,2"]
    lines.extend(f"T{tool_number[width]:02d}C{width // 10000}.{width % 10000:04d}" for width in widths)
    lines.extend(("%", "G90"))
    selected = None
    for width, center in rows:
        if selected != tool_number[width]:
            selected = tool_number[width]
            lines.append(f"T{selected:02d}")
        x, y = (_fixed(value, 3, axis) for value, axis in zip(center, ("X", "Y")))
        lines.append(f"X{x:05d}Y{y:05d}")
    lines.append("M30")
    return ("\n".join(lines) + "\n").encode("ascii"), len(holes)


def main(argv):
    """! @brief 원본을 읽기 전용으로 열고 새 .drl 파일과 해시를 제공한다."""
    parser = argparse.ArgumentParser(prog="rfad altium-drill-copy", description=__doc__)
    parser.add_argument("source", type=Path, help="Studio에서 내보낸 명시 좌표 XNC")
    parser.add_argument("destination", type=Path, help="새 Altium CAM 검토용 .drl 사본")
    args = parser.parse_args(argv)
    if args.source.suffix.lower() != ".xnc" or args.destination.suffix.lower() != ".drl":
        parser.error("원문은 .xnc, 새 사본은 .drl 파일을 지정하세요.")
    try:
        with args.source.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        converted, count = make_copy(raw)
        staged = NamedTemporaryFile(dir=args.destination.parent, delete=False)
        try:
            with staged:
                staged.write(converted)
            os.link(staged.name, args.destination)
        finally:
            Path(staged.name).unlink(missing_ok=True)
    except (OSError, ProjectError) as error:
        parser.error(str(error))
    print(json.dumps({"use": "cam_review", "holes": count, "coordinate_format": "MM/absolute/2.3/none",
                      "source_sha256": hashlib.sha256(raw).hexdigest(),
                      "copy_sha256": hashlib.sha256(converted).hexdigest(),
                      "actual_tool_diameter": None, "manufacturing_verified": False}))
    return 0
