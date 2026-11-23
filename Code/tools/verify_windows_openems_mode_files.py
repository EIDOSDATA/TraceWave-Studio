"""! @brief HDF5 모드 프로필을 단일 직사각 도파관에 실제로 여기한다."""

import argparse
import hashlib
import json
from pathlib import Path
import os
import subprocess



def run(files, executable, output, frequency):
    """! @brief 저장한 모드 원문을 두 native 포트에 적용하고 전파 위상과 결합을 읽는다."""
    import CSXCAD
    import numpy as np
    import openEMS
    from openEMS.ports import WaveguidePort

    metadata = json.loads((files / "mode.json").read_bytes())
    for key in ("electric", "magnetic"):
        entry = metadata[key]
        if hashlib.sha256((files / entry["name"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("내보낸 모드 원문 해시가 다릅니다.")
    if metadata["frequency_hz"] != frequency or metadata["port_inward_direction"] != [0, 0, 1]:
        raise ValueError("이 고정 검증에서 +Z 전파 모드와 해당 주파수가 필요합니다.")
    output.mkdir()
    csx = CSXCAD.ContinuousStructure()
    fdtd = openEMS.openEMS(NrTS=12000, EndCriteria=1e-6)
    fdtd.SetCSX(csx)
    fdtd.SetGaussExcite(frequency, 2e9)
    fdtd.SetBoundaryCond(["PEC", "PEC", "PEC", "PEC", "PML_8", "PML_8"])
    grid = csx.GetGrid()
    grid.SetDeltaUnit(0.001)
    for axis, length in zip("xyz", (20, 10, 60)):
        grid.AddLine(axis, np.linspace(0, length, round(length / 0.5) + 1))
    ports = []
    for index, (source, reference) in enumerate(((12,20),(48,40)), 1):
        ports.append(WaveguidePort(csx, index, [0,0,source], [20,10,reference], "z", None, None,
                                          metadata["cutoff_rad_per_m"], excite=int(index == 1),
                                          E_WG_file=str(files / "electric.h5"),
                                          H_WG_file=str(files / "magnetic.h5")))
    model = output / "mode-guide.xml"
    fdtd.Write2XML(str(model))
    with (output / "native.log").open("xb") as log:
        subprocess.run([str(executable), model.name, "--engine=multithreaded", "--numThreads=4",
                        "--dump-statistics", "--exact-endcriteria"], cwd=output,
                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                       timeout=120, check=True)
    for port in ports:
        port.CalcPort(str(output), np.array([frequency]))
    r = ports[0].uf_ref[0] / ports[0].uf_inc[0]
    t = ports[1].uf_ref[0] / ports[0].uf_inc[0]
    expected = np.exp(-1j * metadata["propagation_rad_per_m"] * 0.02)
    print(json.dumps({"reflected_ri": [r.real, r.imag], "transfer_ri": [t.real, t.imag],
                      "expected_ri": [expected.real, expected.imag], "complex_delta": abs(t - expected), "reference_planes_mm": [20, 40], "source_direction": "+z", "input_sha256": metadata["input_sha256"]}))
    if abs(r) > 0.05 or abs(t - expected) > 0.07:
        raise RuntimeError("모드 포트의 반사 또는 전송의 복소 오차가 기준을 넘었습니다.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("files", type=Path)
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frequency", type=float, default=10.5e9)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    with os.add_dll_directory(str(executable.parent)):
        run(args.files.resolve(), executable, args.output.resolve(), args.frequency)
