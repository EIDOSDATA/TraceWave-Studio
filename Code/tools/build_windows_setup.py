"""! @brief 검증된 Windows 후보 ZIP과 설치 코드를 단일 Setup.exe에 넣는다."""

import argparse
from pathlib import Path
import os
import re
import subprocess
from tempfile import TemporaryDirectory
import zipfile

from build_internal_bundle import verify


def build(archive: Path, output: Path, display_version: str | None = None) -> None:
    """! @brief 같은 Git 개정에서 봉인한 설치 코드와 묶음만 새 실행 파일로 공개한다."""
    archive, output = archive.resolve(), output.resolve()
    identity = verify(archive)
    display_version = display_version or identity["source_revision"][:12]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .-]{0,39}", display_version):
        raise ValueError("설치된 앱에 표시할 버전 이름이 올바르지 않습니다.")
    with zipfile.ZipFile(archive) as payload:
        sources = {}
        for name in ("TraceWaveSetup.cs", "install.ps1", "uninstall.ps1"):
            expected = (Path(__file__).parent / "windows_setup" / name).read_text(encoding="utf-8-sig")
            actual = payload.read("Code/tools/windows_setup/" + name).decode("utf-8-sig")
            if actual.replace("\r\n", "\n") != expected:
                raise ValueError(f"후보 ZIP의 설치 소스가 현재 설치 소스와 다릅니다. {name}")
            sources[name] = actual
        icon = payload.read("Code/ui/wxwidgets/tracewave.ico")
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".tracewave-setup-", dir=output.parent) as directory:
        stage = Path(directory)
        executable = stage / "TraceWave-Setup.exe"
        for name, source in sources.items():
            (stage / name).write_bytes(source.encode("utf-8-sig"))
        (stage / "bundle-sha256.txt").write_text(identity["sha256"] + "\n", encoding="ascii")
        (stage / "display-version.txt").write_text(display_version + "\n", encoding="ascii")
        (stage / "tracewave.ico").write_bytes(icon)
        subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
                        "/codepage:65001", "/win32icon:tracewave.ico", f"/out:{executable}", f"/resource:{archive},studio.zip",
                        "/resource:install.ps1,install.ps1", "/resource:uninstall.ps1,uninstall.ps1",
                        "/resource:bundle-sha256.txt,bundle-sha256.txt", "/resource:display-version.txt,display-version.txt",
                        "TraceWaveSetup.cs"], cwd=stage, check=True)
        os.link(executable, output)


def main() -> None:
    """! @brief 새 설치 실행 파일의 입력과 출력을 명시적으로 받는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--display-version")
    args = parser.parse_args()
    build(args.archive, args.output, args.display_version)


if __name__ == "__main__":
    main()
