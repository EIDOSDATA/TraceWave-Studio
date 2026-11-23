"""! @brief Windows 제품의 고정 WSL2 엔진에 프로젝트에서 봉인한 준비 XML과 작업 번호만 전달한다."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def mounted(path):
    """! @brief 로컬 드라이브의 실제 파일만 WSL의 기본 마운트 경로로 옮긴다."""
    path = Path(path).resolve(strict=True)
    if not path.is_file() or len(path.drive) != 2 or not path.drive[0].isalpha() or path.drive[1] != ":":
        raise ValueError("로컬 Windows 드라이브에 있는 설치 및 준비 XML을 사용하십시오.")
    return "/mnt/" + path.drive[0].lower() + "/" + "/".join(path.parts[1:])


def main():
    """! @brief 셸을 거치지 않고 설치에 포함한 체크포인트 도구 하나만 실행한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "suspend", "resume", "status", "list"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--xml", type=Path)
    parser.add_argument("--job")
    args = parser.parse_args()
    if (args.action in ("start", "list")) != bool(args.xml) or (args.action in ("status", "resume", "suspend")) != bool(args.job):
        raise ValueError("선택한 작업과 입력이 일치하지 않습니다.")
    wsl = Path(os.environ["SystemRoot"]) / "System32" / "wsl.exe"
    cli = Path(__file__).resolve().parents[3] / "tools/pcb_fdtd_checkpoint.py"
    command = [wsl, "--distribution", "TraceWave-Dev", "--user", "tracewave", "--exec",
               "/usr/bin/python3", "-E", "-s", "-B", mounted(cli), args.action,
               "--project", args.project, "--plan", args.plan, "--sha256", args.sha256, "--engine", args.engine]
    if args.xml:
        command.extend(("--xml", mounted(args.xml)))
    if args.job:
        command.append(args.job)
    done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if done.returncode:
        detail = (done.stderr or done.stdout)
        encoding = "utf-16-le" if b"\\x00" in detail[:100] else "utf-8"
        raise ValueError(detail.decode(encoding, "replace").strip()[-1400:] or "WSL 실행 실패")
    message = json.loads(done.stdout)
    if args.action == "list":
        message = {"jobs": [{"job": item["job"], "status": item["status"]} for item in message["jobs"][:24]]}
    else:
        details = message.get("result") or message
        message = {k: message.get(k) for k in ("job", "status", "directory", "reason", "can_resume")}
        message.update(iterations=details.get("iterations"), samples=details.get("samples"))
    print(json.dumps(message, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exception:
        message = str(exception).encode("utf-8")[-1700:].decode("utf-8", "ignore")
        print(message, file=sys.stderr)
        sys.exit(1)
