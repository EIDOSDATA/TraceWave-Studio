"""! @brief 보존된 복소 결과에서 스크립트 없는 고정 S11 보고서 그림을 작성한다."""

from html import escape
import math


FILE_NAME = "report-s11-v1.svg"


def _panel(item, series, top):
    """! @brief 한 결과의 실제 주파수와 dB 축을 고정하고 누락 구간을 끊는다."""
    frequencies = [frequency for frequency, _ in series]
    values = [value for _, value in series if value is not None]
    x0, x1 = min(frequencies), max(frequencies)
    y0, y1 = math.floor(min(values) / 5) * 5, math.ceil(max(values) / 5) * 5
    if y0 == y1:
        y0, y1 = y0 - 5, y1 + 5
    left, right, bottom = 102, 748, 164
    panel = [f'<g transform="translate(0 {top})">',
             f'<text x="26" y="23">S11 | {escape(item["id"])}</text>',
             '<text x="23" y="53">dB</text>',
             f'<path d="M{left} 43 V{bottom} H{right}" fill="none" stroke="#64748b"/>']
    for index in range(5):
        fraction = index / 4
        y = bottom - (bottom - 43) * fraction
        panel.append(f'<text x="94" y="{y + 4:g}" text-anchor="end">{y0 + (y1 - y0) * fraction:g}</text>')
        panel.append(f'<path d="M{left} {y:g} H{right}" stroke="#cbd5e1"/>')
    for index in range(5 if x0 != x1 else 1):
        fraction = index / 4 if x0 != x1 else 0.5
        x = left + (right - left) * fraction
        frequency_ghz = (x0 + (x1 - x0) * fraction) * 1e-9
        panel.append(f'<text x="{x:g}" y="184" text-anchor="middle">{frequency_ghz:.9g}</text>')
    panel.append('<text x="748" y="205" text-anchor="end">GHz</text>')
    previous = False
    path = []
    samples = []
    for frequency, value in series:
        if value is None:
            previous = False
            continue
        fraction = (frequency - x0) / (x1 - x0) if x0 != x1 else 0.5
        x = left + (right - left) * fraction
        y = bottom - (bottom - 43) * (value - y0) / (y1 - y0)
        path.append(f'{"L" if previous else "M"}{x:.3f} {y:.3f}')
        samples.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="1.6"/>')
        previous = True
    panel.append(f'<path d="{" ".join(path)}" fill="none" stroke="#1d4ed8" stroke-width="2"/>')
    panel.extend(['<g fill="#1d4ed8">', *samples, '</g>', '</g>'])
    return panel


def render(report):
    """! @brief 인계 보고서 수치만 사용하며 유한한 표본이 없는 결과는 그리지 않는다."""
    items = report.get("solver_details", {}).get("items", [])
    if not isinstance(items, list) or len(items) > 12:
        raise ValueError("보고서의 해석 기록 수를 확인하세요.")
    panels = []
    for item in items:
        if item["state"] != "verified":
            continue
        series = item["s11_db_by_frequency_hz"]
        if not isinstance(series, list) or len(series) > 201:
            raise ValueError("보고서의 주파수 표본 수를 확인하세요.")
        last = 0
        for frequency, value in series:
            if not math.isfinite(frequency) or frequency <= last or (value is not None and not math.isfinite(value)):
                raise ValueError("보고서의 주파수 축과 복소 결과 값을 확인하세요.")
            last = frequency
        if any(value is not None for _, value in series):
            panels.append(_panel(item, series, len(panels) * 221))
    if not panels:
        return None
    height = len(panels) * 221
    header = [f'<svg xmlns="http://www.w3.org/2000/svg" width="790" height="{height}" viewBox="0 0 790 {height}" role="img">',
              '<title>S11 by frequency</title>',
              f'<rect width="790" height="{height}" fill="#fff"/>',
              '<g fill="#1e293b" font-family="sans-serif" font-size="13">']
    lines = [*header, *(line for panel in panels for line in panel), '</g>', '</svg>']
    return ("\n".join(lines) + "\n").encode("utf-8")
