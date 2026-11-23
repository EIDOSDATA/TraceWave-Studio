"""! @brief 단일 포트 FDTD의 자체 생성 체크포인트와 실행 환경을 사용자별로 봉인한다."""

from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import platform
import pwd
import re
import secrets
import stat
from uuid import UUID
from xml.etree import ElementTree


TRACES = ("port_ut_1", "port_it_1")
JOB_ROOT = Path("/var/tmp") / f"tracewave-fdtd-{os.getuid()}"
RUNTIME_ROOT = Path(pwd.getpwuid(os.getuid()).pw_dir) / "rfad-runtime"
DMTCP = RUNTIME_ROOT / "dmtcp/4.2.0"
ENGINE = RUNTIME_ROOT / "openems/0.37.0/bin/openEMS"
ARGS = ("pcb.xml", "--engine=multithreaded", "--numThreads=1", "--dump-statistics", "--exact-endcriteria")


def require(test, message):
    """! @brief 실패 근거를 CLI의 한국어 진단으로 전달한다."""
    if not test:
        raise ValueError(message)


def private_root():
    """! @brief 다른 사용자와 공유하지 않는 고정 WSL 작업 루트와 봉인 키를 준비한다."""
    require(os.getuid() != 0 and platform.system() == "Linux", "일반 WSL Linux 사용자로 실행하십시오.")
    JOB_ROOT.mkdir(mode=0o700, exist_ok=True)
    detail = JOB_ROOT.lstat()
    require(stat.S_ISDIR(detail.st_mode) and detail.st_uid == os.getuid() and detail.st_mode & 0o077 == 0,
            "기존 체크포인트 작업 루트의 소유자와 권한을 확인하십시오.")
    key = JOB_ROOT / ".seal-key"
    # @brief 키가 완성되기 전에 병행 실행이 빈 파일을 읽지 않도록 링크를 원자적으로 게시한다.
    if not key.exists():
        pending = JOB_ROOT / (".key-" + secrets.token_hex(12))
        fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(secrets.token_bytes(32))
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(pending, key)
        except FileExistsError:
            pass
        finally:
            pending.unlink()
    detail = key.lstat()
    require(stat.S_ISREG(detail.st_mode) and detail.st_uid == os.getuid() and detail.st_mode & 0o077 == 0
            and detail.st_size == 32, "체크포인트 봉인 키를 사용할 수 없습니다.")
    return key.read_bytes()


def canonical(value):
    """! @brief JSON 봉인과 확인이 사용하는 같은 UTF-8 표현을 만든다."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def save(job, key, state):
    """! @brief 과거 상태가 온전한 동안 새 상태를 기록한 뒤 원자적으로 바꾼다."""
    envelope = {"value": state, "mac": hmac.digest(key, canonical(state), "sha256").hex()}
    tmp = job / (".state-" + secrets.token_hex(12))
    with tmp.open("xb") as output:
        output.write(canonical(envelope))
        output.flush()
        os.fsync(output.fileno())
    os.replace(tmp, job / "state.json")


def load(job, key):
    """! @brief 이 사용자와 경로에서 봉인한 manifest만 다시 읽는다."""
    file = job / "state.json"
    require(file.is_file() and not file.is_symlink() and file.stat().st_size <= 256 * 1024, "작업 상태가 없습니다.")
    envelope = json.loads(file.read_bytes())
    state = envelope["value"]
    require(hmac.compare_digest(hmac.digest(key, canonical(state), "sha256").hex(), envelope["mac"])
            and state["job"] == job.name and state["directory"] == str(job), "작업 상태의 위치 또는 봉인이 다릅니다.")
    return state


@contextmanager
def locked(job_id, *, writing=True):
    """! @brief 도구가 만든 작업 번호 하나에만 현재 명령의 배타 잠금을 획득한다."""
    key = private_root()
    require(str(UUID(job_id)) == job_id, "경로 대신 생성된 작업 UUID를 입력하십시오.")
    job = JOB_ROOT / job_id
    detail = job.lstat()
    require(stat.S_ISDIR(detail.st_mode) and detail.st_uid == os.getuid() and detail.st_mode & 0o077 == 0,
            "작업 폴더의 소유자와 권한이 변경되었습니다.")
    for name in ("run", "images", "history", "tmp"):
        item = (job / name).lstat()
        require(stat.S_ISDIR(item.st_mode) and item.st_uid == os.getuid() and item.st_mode & 0o077 == 0,
                "작업 하위 폴더의 위치, 소유자 또는 권한이 바뀌었습니다.")
    if not writing:
        yield job, key, load(job, key)
        return
    fd = os.open(job / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield job, key, load(job, key)


def digest(file, *, installed=False):
    """! @brief 이미지 파일도 메모리에 올리지 않고 SHA-256과 크기를 검사한다."""
    info = file.lstat()
    require(stat.S_ISREG(info.st_mode) and (installed or info.st_nlink == 1) and info.st_size <= 8 * 1024**3,
            "체크포인트 파일 종류 또는 크기가 유효하지 않습니다.")
    result = hashlib.sha256()
    with file.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            result.update(data)
    return {"bytes": info.st_size, "sha256": result.hexdigest()}


def loaded_libraries(pid):
    """! @brief 실제 계산 프로세스에 매핑된 공유 라이브러리의 경로와 현재 해시를 고정한다."""
    files = set()
    for line in (Path("/proc") / str(pid) / "maps").read_text().splitlines():
        columns = line.split(maxsplit=5)
        if len(columns) == 6 and columns[5].startswith("/") and ".so" in Path(columns[5]).name:
            path = Path(columns[5]).resolve(strict=True)
            require(path.is_relative_to("/usr/lib") or path.is_relative_to(RUNTIME_ROOT),
                    "고정 런타임 및 시스템 밖의 공유 라이브러리는 재개할 수 없습니다.")
            files.add(path)
    require(files, "엔진의 메모리에 적재된 라이브러리를 식별하지 못했습니다.")
    return {str(path): digest(path, installed=True) for path in sorted(files)}


def runtime():
    """! @brief 고정 위치의 openEMS, DMTCP 실행 파일과 네이티브 라이브러리의 지문을 기록한다."""
    files = [ENGINE, *sorted((DMTCP / "bin").glob("*")), *sorted((DMTCP / "lib/dmtcp").glob("*.so")),
             *sorted((ENGINE.parent.parent / "lib").glob("*.so*"))]
    require(all((DMTCP / "bin" / name).is_file() for name in
                ("dmtcp_launch", "dmtcp_command", "dmtcp_restart", "dmtcp_coordinator", "mtcp_restart"))
            and (DMTCP / "lib/dmtcp/libdmtcp.so").is_file(), "고정 실행 위치에 DMTCP 4.2.0을 설치하십시오.")
    fingerprints = {}
    for file in files:
        real = file.resolve(strict=True)
        require(real.is_relative_to(RUNTIME_ROOT) and real.is_file(), "런타임 파일이 설치 경계 밖에 있습니다.")
        fingerprints[str(file)] = {"path": str(real), **digest(real, installed=True)}
    return {"files": fingerprints, "machine": platform.machine(), "kernel": platform.release(),
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def input_xml(file):
    """! @brief 실제 PCB worker의 수치 전용 단일 포트 형상과 고정 출력을 확인한다."""
    require(file.is_file() and not file.is_symlink() and 0 < file.stat().st_size <= 8 * 1024**2,
            "준비한 단일 포트 pcb.xml을 지정하십시오.")
    raw = file.read_bytes()
    require("<!" not in raw.decode("utf-8") and b"\x00" not in raw, "선언과 외부 XML 참조를 포함한 입력을 열 수 없습니다.")
    root = ElementTree.fromstring(raw)
    allowed = set(("openEMS FDTD Excitation BoundaryCond ContinuousStructure RectilinearGrid XLines YLines ZLines "
                   "BackgroundMaterial ParameterSet Properties Material FillColor EdgeColor Primitives Box P1 P2 "
                   "Property Weight Cylinder ConductingSheet Polygon Vertex LumpedElement ProbeBox").split())
    names = []
    require(root.tag == "openEMS" and len(root.findall("FDTD")) == len(root.findall("ContinuousStructure")) == 1,
            "준비한 PCB FDTD 형식을 확인하십시오.")
    for node in root.iter():
        require(node.tag in allowed, "단일 비방사 PCB 프로필에서 지원하지 않는 XML 요소입니다.")
        for k, value in node.attrib.items():
            if k == "Name":
                require(re.fullmatch("[A-Za-z0-9_-]{1,150}", value), "안전한 PCB 객체 이름이 필요합니다.")
            elif node.tag == "BoundaryCond":
                require(re.fullmatch("PML_[1-9][0-9]?|PEC|PMC|MUR", value), "유효한 경계 조건이 필요합니다.")
            else:
                require(re.fullmatch("[0-9eE+., -]+", value) and all(math.isfinite(float(v)) for v in value.split(",")),
                        "PCB XML 속성은 유한한 수치여야 합니다.")
        if node.tag == "ProbeBox":
            names.append(node.get("Name"))
        if node.text and node.text.strip():
            require(node.tag in {"XLines", "YLines", "ZLines"}, "격자 외 임의 텍스트를 포함할 수 없습니다.")
    require(sorted(names) == sorted(TRACES) and len(root.findall(".//LumpedElement")) == 1
            and len(root.findall("./ContinuousStructure/Properties/Excitation")) == 1, "급전 한 개의 U/I 프로브가 필요합니다.")
    counts = []
    for axis in "XYZ":
        node = root.find("./ContinuousStructure/RectilinearGrid/" + axis + "Lines")
        require(node is not None and node.text, "각 축의 실제 격자선이 필요합니다.")
        vals = [float(v) for v in node.text.split(",")]
        require(2 <= len(vals) <= 10000 and len(vals) == int(node.get("Qty")) and all(math.isfinite(v) for v in vals)
                and all(a < b for a, b in zip(vals, vals[1:])), "격자선이 유한한 증가 순서여야 합니다.")
        counts.append(len(vals))
    steps = int(root.find("FDTD").get("NumberOfTimesteps"))
    require(1 <= steps <= 10000000 and math.prod(counts) <= 4000000, "입력 자원 상한을 초과했습니다.")
    return raw, steps
