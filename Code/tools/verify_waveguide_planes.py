"""! @brief 도파관에 실제 배치한 두 측정면과 분산 기준면 이동의 복소 전달을 비교한다."""

import argparse
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

import numpy as np
from verify_te10_symmetry import solve
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rfad.application.network_forms import transform_input
from rfad.domain.network_data import make_dataset
from rfad.domain.network_transform import transform_dataset


def main():
    """! @brief 같은 구조의 수신 포트를 5 mm 간격으로 옮겨 각각 독립 계산한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--openems", required=True, type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as directory:
        source = Path(directory)
        near, reflection, transmission = solve(source / "near", "full", 1., args.openems, output_plane_mm=60)
        far, _, measured = solve(source / "far", "full", 1., args.openems)
    grid = np.linspace(9.5e9, 10.5e9, len(transmission)).tolist()
    z0 = [376.730313668 / math.sqrt(1 - (299792458. / (.04 * f)) ** 2) for f in grid]
    def pair(value):
        """! @brief 직접 계산한 두 복소 성분만 결과 DTO에 전달한다."""
        return [float(value.real), float(value.imag)]

    values = [[[pair(s11), None], [pair(s21), None]] for s11, s21 in zip(reflection, transmission)]
    data = make_dataset(parameter_kind="S", frequency_hz=grid, port_ids=[str(UUID(int=i)) for i in (1, 2)],
                        values_ri=values, z0_ohm=[[[r, 0.], [r, 0.]] for r in z0],
                        wave_definition="traveling", phasor_convention="exp(+j*omega*t)",
                        reference_planes=["z=15 mm", "z=60 mm"], port_modes=["rectangular_te10"] * 2,
                        current_orientation=["into_dut"] * 2, sample_origin=["computed"] * len(grid),
                        valid_mask=[[[True, False], [True, False]] for _ in grid],
                        sample_status=[[["valid", "missing"], ["valid", "missing"]] for _ in grid])
    options = transform_input(data, {"operation": "shift_plane",
                              "line_table": "2 | 0,0,60 > 0,0,65 > 0,0,1 | TE10(20,10,1) | 0 | z=65 mm"})
    changed = transform_dataset(data, options)["dataset"]
    error = float(max(abs(complex(*row[1][0]) - actual) for row, actual in zip(changed["values_ri"], measured)))
    print(json.dumps({"near_steps": near["iterations"], "far_steps": far["iterations"], "samples": len(grid),
                      "maximum_complex_s21_difference": error, "tolerance": .01}))
    return int(error > .01)


if __name__ == "__main__":
    sys.exit(main())
