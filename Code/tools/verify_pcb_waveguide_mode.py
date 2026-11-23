"""! @brief 저장 PCB의 분포 모드 여기 시험 입력과 독립 평판 기준을 제공한다."""

import argparse
import cmath
from copy import deepcopy
import json
import math
from pathlib import Path
from uuid import UUID, uuid5


def fixture(source, destination):
    """! @brief 기존 원형 실험 개정을 보존하고 사각판 및 동박 시험의 별개 개정을 만든다."""
    board = json.loads(source.read_bytes())["document"]
    shape = board["geometry"][0]
    parent = UUID(board["revision_id"])

    def mm(value):
        """! @brief 기존 시험 수량의 선언과 출처를 유지한다."""
        return {**shape["start"][0], "value_si": value * 0.001}

    board["board"]["outline"] = {"kind": "rectangle", "width": mm(20), "height": mm(10)}
    board.update(ports=[], connections=[], geometry=[])
    sheet = deepcopy(board)
    board["stackup"] = [layer for layer in board["stackup"] if layer["role"] == "dielectric"]
    sheet["geometry"] = [{
        **{key: value for key, value in shape.items() if key not in ("start", "end", "width")},
        "kind": "planar_region", "outer": [[mm(x), mm(y)] for x, y in ((4, 3), (8, 3), (8, 7), (4, 7))],
        "holes": [],
    }]
    destination.mkdir()
    for name, case in (("dielectric", board), ("foil", sheet)):
        case["revision_id"] = str(uuid5(parent, "pcb-waveguide-" + name))
        case["parent_revision_ids"] = [str(parent)]
        (destination / (name + ".json")).write_text(json.dumps(case), encoding="utf-8")
    settings = {"frequencies_hz": [10e9, 10.5e9, 11e9], "grid_mm": 0.5, "lead_mm": 20,
                "curve_tolerance_mm": 0.025, "max_timesteps": 48000, "end_criterion": 1e-5, "num_threads": 4}
    (destination / "settings-te.json").write_text(json.dumps(settings), encoding="utf-8")
    settings["frequencies_hz"] = [18e9, 18.5e9, 19e9]
    (destination / "settings-tm.json").write_text(json.dumps(settings), encoding="utf-8")


def compare(path, foil_path):
    """! @brief 손실 유전체판의 두 모드와 양쪽 기준면을 독립 Airy 복소 해로 대조한다."""
    result = json.loads(path.read_bytes())
    family = result["mode"]["polarization"]
    frequencies = result["frequency_hz"]
    center = (frequencies[0] + frequencies[-1]) / 2
    cut = math.pi / 0.020 if family == "TE" else math.pi * math.hypot(1 / 0.020, 1 / 0.010)
    maximum = 0.0
    for frequency, matrix in zip(frequencies, result["s_ri"]):
        k = 2 * math.pi * frequency / 299792458
        epsilon = 2.2 * (1 + 1j * 0.002 * center / frequency)
        q0, q1 = (cmath.sqrt(value - (cut / k)**2) for value in (1, epsilon))
        y0, y1 = (q0, q1) if family == "TE" else (1 / q0, epsilon / q1)
        interface = (y0 - y1) / (y0 + y1)
        prop = cmath.exp(1j * k * q1 * 0.001)
        denom = 1 - interface**2 * prop**2
        plane = cmath.exp(1j * k * q0 * 0.016)
        reflection = (interface * (1 - prop**2) / denom * plane).conjugate()
        transmission = ((1 - interface**2) * prop / denom * plane).conjugate()
        for i, row in enumerate(matrix):
            for j, data in enumerate(row):
                expected = reflection if i == j else transmission
                maximum = max(maximum, abs(complex(*data) - expected))
    if maximum > 0.02:
        raise ValueError(f"독립 유전체판 복소 대조 오차가 기준을 넘었습니다 {maximum}")
    report = {"polarization": family, "complex_max_delta": maximum, "reference_planes_mm": result["reference_planes_z_mm"],
              "source_sha256": result["project_source"]["document_sha256"]}
    if foil_path:
        foil = json.loads(foil_path.read_bytes())
        if foil["frequency_hz"] != frequencies:
            raise ValueError("동박과 균질판의 주파수를 일치시키십시오.")
        report["foil_transmission_change_max"] = max(abs(complex(*a[1][0]) - complex(*b[1][0]))
                                                      for a, b in zip(result["s_ri"], foil["s_ri"]))
        report["foil_reciprocity_residual"] = max(abs(complex(*matrix[1][0]) - complex(*matrix[0][1]))
                                                 for matrix in foil["s_ri"])
        report["foil_source_sha256"] = foil["project_source"]["document_sha256"]
        if report["foil_transmission_change_max"] < 0.003 or report["foil_reciprocity_residual"] > 0.03:
            raise ValueError("동박 영향 또는 상호성 비교가 기준을 벗어났습니다.")
    print(json.dumps(report))


def main():
    """! @brief 새 재현 입력을 만들거나 기존 결과 원문을 독립 검산한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("source", type=Path)
    create.add_argument("destination", type=Path)
    evaluate = commands.add_parser("compare")
    evaluate.add_argument("result", type=Path)
    evaluate.add_argument("--foil", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        fixture(args.source, args.destination)
    else:
        compare(args.result, args.foil)


if __name__ == "__main__":
    main()
