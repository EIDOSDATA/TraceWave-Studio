"""! @brief 불변 네트워크 자료 참조와 회로/목표 평가를 프로젝트 명령 이력에 연결한다."""

from copy import deepcopy
import re

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design import _fields, _text, _uuid
from rfad.domain.errors import ProjectError

KEY = "rfad.network-library"
SCHEMA = "rfad.network-library/0.1"
COMMAND = "network.library.replace"
MAX_RECORDS = 32
MAX_LIBRARY_BYTES = 128 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def fail(message, field="network_library", code="E_SCHEMA"):
    """! @brief 저장 계약 위반을 기존 진단 형식으로 반환한다."""
    raise ProjectError(code, message, details={"field": field})


def empty_library():
    """! @brief 자료가 없는 프로젝트에 값이나 결과를 생성하지 않는다."""
    return {"schema": SCHEMA, "datasets": [], "circuits": [], "assessments": []}


def library(document):
    """! @brief 읽기 조회는 원본 확장을 새로 저장하지 않는다."""
    return deepcopy(document["extensions"].get(KEY, empty_library()))


def digest(value, field):
    """! @brief 봉인 자료의 SHA256 형식을 확인한다."""
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        fail("정규 SHA256이 필요합니다.", field, "E_HASH")


def artifact(value, field):
    """! @brief 참조는 workspace 상대 경로/원본 크기/해시를 함께 보존한다."""
    _fields(value, {"uri", "sha256", "bytes"}, field)
    digest(value["sha256"], field + ".sha256")
    _text(value["uri"], field + ".uri", limit=1024)
    parts = value["uri"].split("/")
    if len(parts) < 4 or parts[0] != "projects" or any(item in ("", ".", "..") for item in parts) or any(c in value["uri"] for c in "\\:"):
        fail("자료 참조는 projects 아래의 정규 상대 경로여야 합니다.", field + ".uri")
    if type(value["bytes"]) is not int or not 0 < value["bytes"] <= MAX_ARTIFACT_BYTES:
        fail("자료 바이트 상한을 초과했습니다.", field + ".bytes", "E_RESOURCE")


def validate_library(value):
    """! @brief 수치 엔진 없이 프로젝트의 자료 참조와 보존된 정의를 검사한다."""
    _fields(value, {"schema", "datasets", "circuits", "assessments"}, KEY)
    if value["schema"] != SCHEMA:
        fail("지원하지 않는 네트워크 자료 버전입니다.", code="E_VERSION")
    used = set()
    for collection in ("datasets", "circuits", "assessments"):
        records = value[collection]
        if type(records) is not list or len(records) > MAX_RECORDS:
            fail("자료/회로/평가 목록은 종류별 최대 32개입니다.", collection, "E_RESOURCE")
        identities = []
        for row in records:
            common = {"id", "name", "created_revision"}
            extra = {"datasets": {"kind", "dataset", "normalized_hdf5", "raw", "inputs", "circuit_id", "diagnostics"},
                     "circuits": {"definition"},
                     "assessments": {"dataset_id", "target_id", "target_revision_id", "artifact", "status"}}[collection]
            _fields(row, common | extra, collection)
            identity = _uuid(row["id"], collection + ".id")
            if identity in used:
                fail("자료/회로/평가 식별자가 중복됩니다.", collection, "E_CONFLICT")
            used.add(identity)
            identities.append(identity)
            _text(row["name"], collection + ".name", limit=256)
            _uuid(row["created_revision"], collection + ".created_revision")
            if collection == "datasets":
                if row["kind"] not in ("imported", "solver", "derived"):
                    fail("지원하지 않는 자료 출처 종류입니다.", collection + ".kind")
                artifact(row["dataset"], collection + ".dataset")
                artifact(row["normalized_hdf5"], collection + ".normalized_hdf5")
                if row["raw"] is not None:
                    artifact(row["raw"], collection + ".raw")
                if row["diagnostics"] is not None:
                    artifact(row["diagnostics"], collection + ".diagnostics")
                if type(row["inputs"]) is not list or len(row["inputs"]) > 2:
                    fail("입력 자료 참조 목록이 유효하지 않습니다.", collection + ".inputs")
                for source in row["inputs"]:
                    _uuid(source, collection + ".inputs")
                if len(set(row["inputs"])) != len(row["inputs"]):
                    fail("입력 자료 식별자가 중복됩니다.", collection + ".inputs")
                if row["circuit_id"] is not None:
                    _uuid(row["circuit_id"], collection + ".circuit_id")
            elif collection == "circuits":
                from rfad.domain.network_circuit import validate_circuit
                validate_circuit(row["definition"])
            else:
                for field in ("dataset_id", "target_id", "target_revision_id"):
                    _uuid(row[field], collection + "." + field)
                artifact(row["artifact"], collection + ".artifact")
                if row["status"] not in ("pass", "fail", "not_evaluated", "conditional"):
                    fail("지원하지 않는 평가 상태입니다.", collection + ".status")
        if identities != sorted(identities):
            fail("자료 목록은 UUID 순서여야 합니다.", collection)
    datasets = {row["id"] for row in value["datasets"]}
    circuits = {row["id"] for row in value["circuits"]}
    for row in value["datasets"]:
        if any(identity not in datasets or identity == row["id"] for identity in row["inputs"]):
            fail("파생 자료의 원본 참조가 없습니다.", "datasets.inputs", "E_CONFLICT")
        if row["circuit_id"] is not None and row["circuit_id"] not in circuits:
            fail("파생 자료의 회로 정의가 없습니다.", "datasets.circuit_id", "E_CONFLICT")
    for row in value["assessments"]:
        if row["dataset_id"] not in datasets:
            fail("평가한 자료의 참조가 없습니다.", "assessments.dataset_id", "E_CONFLICT")
    graph = {row["id"]: row["inputs"] for row in value["datasets"]}
    active, completed = set(), set()

    def visit(identity):
        """! @brief 파생 자료 사슬에서 순환된 출처를 유효한 원본으로 해석하지 않는다."""
        if identity in active:
            fail("파생 자료의 출처 참조가 순환합니다.", "datasets.inputs", "E_CONFLICT")
        if identity in completed:
            return
        active.add(identity)
        for source in graph[identity]:
            visit(source)
        active.remove(identity)
        completed.add(identity)

    for identity in graph:
        visit(identity)
    if len(canonical_bytes(value)) > MAX_LIBRARY_BYTES:
        fail("자료 참조가 128 KiB 상한을 초과했습니다. 과거 기록을 지우지 않습니다.", code="E_RESOURCE")


def validate_project_library(document):
    """! @brief 구버전 및 자료가 없는 프로젝트는 읽기만으로 변경하지 않는다."""
    if KEY in document["extensions"]:
        validate_library(document["extensions"][KEY])


def apply_library_command(document, payload):
    """! @brief 정의/참조 교체와 역명령을 한 번에 만들어 undo/redo를 보존한다."""
    _fields(payload, {"expected_hash", "replacement"}, "command.payload")
    old = document["extensions"].get(KEY)
    if payload["expected_hash"] != canonical_hash(old):
        fail("검토한 자료 목록과 현재 원본이 다릅니다.", "expected_hash", "E_CONFLICT")
    replacement = payload["replacement"]
    if replacement is not None:
        validate_library(replacement)
        document["extensions"][KEY] = deepcopy(replacement)
    else:
        document["extensions"].pop(KEY, None)
    changed = sorted({row["id"] for model in (old, replacement) if model is not None
                      for name in ("datasets", "circuits", "assessments") for row in model[name]})
    inverse = {"type": COMMAND, "payload": {"expected_hash": canonical_hash(replacement), "replacement": deepcopy(old)}}
    return changed, ["revision", "network", "metrics", "assessment", "exports"], inverse
