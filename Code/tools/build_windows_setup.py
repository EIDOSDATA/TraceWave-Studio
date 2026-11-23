"""! @brief 검증된 Windows 후보 ZIP과 설치 코드를 단일 Setup.exe에 넣는다."""

import argparse
from pathlib import Path
import os
import subprocess
from tempfile import TemporaryDirectory
import zipfile

from build_internal_bundle import verify


def build(archive: Path, output: Path) -> None:
    """! @brief 같은 Git 개정에서 봉인한 설치 코드와 묶음만 새 실행 파일로 공개한다."""
    archive, output = archive.resolve(), output.resolve()
    identity = verify(archive)
    with zipfile.ZipFile(archive) as payload:
        for name in ("TraceWaveSetup.cs", "install.ps1"):
            expected = (Path(__file__).parent / "windows_setup" / name).read_text(encoding="utf-8-sig")
            actual = payload.read("Code/tools/windows_setup/" + name).decode("utf-8-sig")
            if actual.replace("\r\n", "\n") != expected:
                raise ValueError(f"후보 ZIP의 설치 소스가 현재 설치 소스와 다릅니다. {name}")
        source = payload.read("Code/tools/windows_setup/TraceWaveSetup.cs")
        script = payload.read("Code/tools/windows_setup/install.ps1").decode("utf-8-sig")
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".tracewave-setup-", dir=output.parent) as directory:
        stage = Path(directory)
        executable = stage / "TraceWave-Setup.exe"
        (stage / "TraceWaveSetup.cs").write_bytes(source)
        (stage / "install.ps1").write_bytes(script.encode("utf-8-sig"))
        (stage / "bundle-sha256.txt").write_text(identity["sha256"] + "\n", encoding="ascii")
        subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                        "/codepage:65001", f"/out:{executable}", f"/resource:{archive},studio.zip",
                        "/resource:install.ps1,install.ps1", "/resource:bundle-sha256.txt,bundle-sha256.txt",
                        "TraceWaveSetup.cs"], cwd=stage, check=True)
        os.link(executable, output)


def main() -> None:
    """! @brief 새 설치 실행 파일의 입력과 출력을 명시적으로 받는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.archive, args.output)


if __name__ == "__main__":
    main()
