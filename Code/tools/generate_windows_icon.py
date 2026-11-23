"""! @brief PCB 급전 패드와 RF 파형으로 Studio의 다중 해상도 ICO를 만든다."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SCALE = 2
EDGE = 256 * SCALE
FEED = (52, 170)
WAVE = (
    (FEED, (70, 170), (75, 106), (97, 106)),
    ((97, 106), (119, 106), (117, 156), (140, 156)),
    ((140, 156), (167, 156), (177, 76), (202, 76)),
)


def bezier(curve, t):
    """! @brief 급전점에서 이어지는 삼차 곡선의 한 점을 출력 좌표로 변환한다."""
    u = 1 - t
    weights = (u**3, 3 * u**2 * t, 3 * u * t**2, t**3)
    return tuple(SCALE * sum(weight * value for weight, value in zip(weights, axis))
                 for axis in zip(*curve))


def frame(size):
    """! @brief 작은 제목 표시줄에서는 파형을 굵게 하고 급전점을 단순화한다."""
    gradient = Image.linear_gradient("L").resize((EDGE, EDGE))
    image = ImageOps.colorize(gradient, "#197BE4", "#07458D").convert("RGBA")
    alpha = Image.new("L", (EDGE, EDGE))
    ImageDraw.Draw(alpha).rounded_rectangle((16, 16, EDGE - 16, EDGE - 16), radius=92, fill=255)
    image.putalpha(alpha)

    draw = ImageDraw.Draw(image)
    stroke = (20 if size <= 24 else 16) * SCALE
    trace = "#F7FBFF"
    path = [bezier(curve, step / 24) for curve in WAVE for step in range(25)]
    draw.line(path, fill=trace, width=stroke, joint="curve")
    x, y = path[-1]
    radius = stroke / 2
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=trace)

    x, y = (coordinate * SCALE for coordinate in FEED)
    radius = 16 * SCALE
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="#FFC184")
    if size >= 32:
        radius = 7 * SCALE
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="#0C51A3")

    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    """! @brief Windows 창과 배포 파일에 사용할 하나의 ICO 자산을 기록한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    images = [frame(size) for size in SIZES]
    images[-1].save(args.output, format="ICO", sizes=[image.size for image in images], append_images=images[:-1])


if __name__ == "__main__":
    main()
