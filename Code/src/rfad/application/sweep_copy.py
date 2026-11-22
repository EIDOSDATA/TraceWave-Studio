"""! @brief 새 작업 사본에 필요한 자기완결 원본과 봉인 파일만 유한하게 준비한다."""

from copy import deepcopy
import hashlib
import json

from rfad.application.canonical import canonical_bytes
from rfad.application.project_repository import ProjectRepository
from rfad.domain.errors import ProjectError
from rfad.domain.solver_conditions import KEY as SOLVER_CONDITIONS_KEY
from rfad.domain.smart_dimensions import KEY as SMART_DIMENSIONS_KEY
from rfad.domain.sketch_constraints import KEY as SKETCH_KEY
from rfad.domain.drawing_annotations import KEY as DRAWING_ANNOTATIONS_KEY
from rfad.domain.network_library import KEY as LIBRARY_KEY, validate_library, artifact
from rfad.domain.project import validate_project

MAX_COPY_REFERENCES = 32
MAX_COPY_BYTES = 16 * 1024 * 1024
KNOWN_EXTENSIONS = {"rfad.template-origin", "rfad.precision-origin", "rfad.pcb-selection",
                    "rfad.physical_setup", "rfad.sweep-selection", LIBRARY_KEY, SOLVER_CONDITIONS_KEY, SMART_DIMENSIONS_KEY, SKETCH_KEY, DRAWING_ANNOTATIONS_KEY}


def _registered_host_source(service, project, project_id, reference):
    """! @brief 명령에 등록된 계산 source 또는 이전 사본의 정확한 별도 mapping만 따라간다."""
    artifact(reference, "provenance.host_source")
    if not 0 < reference["bytes"] <= 4 * 1024**2:
        raise ProjectError("E_RESOURCE", "복사할 host 계산 source는 최대 4 MiB입니다.")
    state = service.journal.read()
    owned = state["projects"].get(project_id)
    if owned is None or owned["path"] != project["path"]:
        raise ProjectError("E_HASH", "계산 source를 복사할 원본 프로젝트의 소유자가 다릅니다.")
    resolved = None
    for command in state["commands"].values():
        if command["project_id"] != project_id:
            continue
        registered = command.get("host_calculation", {}).get("host_source")
        if registered == reference:
            if reference["uri"] != project["path"] + "/host-calculation-sources/" + reference["sha256"] + ".json":
                raise ProjectError("E_HASH", "등록한 host 계산 source의 저장 경로가 다릅니다.")
            resolved = reference
        for mapping in command.get("source_artifact_copies", []):
            if mapping["original_uri"] != reference["uri"]:
                continue
            copied = mapping["copy"]
            artifact(copied, "source_artifact_copies.copy")
            if (copied["sha256"] != reference["sha256"] or copied["bytes"] != reference["bytes"]
                    or copied["uri"] != project["path"] + "/copied-artifacts/" + reference["sha256"] + ".bin"):
                raise ProjectError("E_HASH", "과거 사본의 계산 source mapping이 원본과 다릅니다.")
            if resolved is not None and resolved != copied:
                raise ProjectError("E_HASH", "같은 계산 source의 등록 경로가 서로 다릅니다.")
            resolved = copied
    if resolved is None:
        raise ProjectError("E_HASH", "원본 프로젝트 명령에 등록되지 않은 계산 source 참조입니다.")
    raw = service.journal.read_artifact(resolved)
    try:
        sources = json.loads(raw)
        from rfad.application.source_bundle import MAX_FILES, _path
        if (type(sources) is not dict or not 1 <= len(sources) <= MAX_FILES
                or any(type(value) is not str for value in sources.values()) or canonical_bytes(sources) != raw):
            raise ValueError("source union")
        for path in sources:
            _path(path)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError("E_HASH", "등록한 host source 합집합 원문의 구조가 다릅니다.") from error
    return raw


def prepare_artifacts(service, source_project, document, destination):
    """! @brief 역사 사본의 UUID/출처는 그대로 두고 활성 library 참조에만 새 소유 경로를 부여한다."""
    validate_project(document)
    if document.get("pcb", {}).get("imports"):
        raise ProjectError("E_UNSUPPORTED", "PCB 수입 원본의 프로젝트 간 파일 소유권 복사는 아직 지원하지 않습니다. 원문을 보존하고 후보 채택을 차단합니다.",
                           details={"field_path": "pcb.imports"})
    unknown = document["extensions"].keys() - KNOWN_EXTENSIONS
    if unknown:
        raise ProjectError("E_UNSUPPORTED", "미지 확장의 복사 소유권을 확인할 수 없습니다. 원본을 보존하며 사본 생성을 차단합니다.",
                           details={"extensions": sorted(unknown)})
    if "rfad.sweep-selection" in document["extensions"] and document["extensions"]["rfad.sweep-selection"] is None:
        raise ProjectError("E_UNSUPPORTED", "기존 후보 채택 확장이 null인 원문은 의미를 확인할 수 없어 복사하지 않습니다. 원문은 삭제하지 않습니다.")
    result, blobs, mapping = deepcopy(document), {}, {}
    library = result["extensions"].get(LIBRARY_KEY)
    if library is None:
        return result, blobs, []
    validate_library(library)
    if library["assessments"] or any(row["kind"] == "solver" for row in library["datasets"]):
        raise ProjectError("E_UNSUPPORTED", "해석 원문 연결 또는 보존 평가가 있는 자료 목록의 프로젝트 간 이관은 아직 지원하지 않습니다.")
    from rfad.application.network_records import read_dataset

    def retain(reference, raw):
        """! @brief 원문 bytes를 바꾸지 않고 현재 사본의 한도와 파일 참조만 준비한다."""
        original = reference["uri"]
        if original not in mapping:
            if len(mapping) >= MAX_COPY_REFERENCES:
                raise ProjectError("E_RESOURCE", "사본의 자료 참조는 최대 32개입니다.")
            target = destination + "/copied-artifacts/" + reference["sha256"] + ".bin"
            additional = 0 if target in blobs else len(raw)
            if sum(len(item) for item in blobs.values()) + additional > MAX_COPY_BYTES:
                raise ProjectError("E_RESOURCE", "사본의 봉인 자료는 최대 16 MiB입니다.")
            blobs[target] = raw
            mapping[original] = {"uri": target, "sha256": reference["sha256"], "bytes": reference["bytes"]}
        elif mapping[original]["sha256"] != reference["sha256"] or mapping[original]["bytes"] != reference["bytes"]:
            raise ProjectError("E_HASH", "같은 원본 파일의 참조 해시/크기가 서로 다릅니다.")
        return deepcopy(mapping[original])

    for row in library["datasets"]:
        dataset, _ = read_dataset(service, source_project, document["extensions"][LIBRARY_KEY], row["id"])
        host_source = dataset["provenance"].get("host_source")
        if host_source is not None:
            retain(host_source, _registered_host_source(service, source_project, document["project_id"], host_source))
        for key in ("dataset", "normalized_hdf5", "raw", "diagnostics"):
            reference = row[key]
            if reference is None:
                continue
            original = reference["uri"]
            if not original.startswith(source_project["path"] + "/"):
                raise ProjectError("E_HASH", "복사할 자료 파일이 원본 프로젝트 저장 영역 밖에 있습니다.")
            row[key] = retain(reference, service.journal.read_artifact(reference))
    validate_project(result)
    return result, blobs, [{"original_uri": key, "copy": deepcopy(value)} for key, value in mapping.items()]


class BufferedRepository(ProjectRepository):
    """! @brief 기존 단일 명령/이력을 실제 게시 전에 같은 검증으로 메모리에 준비한다."""

    def __init__(self, repository):
        """! @brief 저장소 안전 경계는 재사용하고 신규 바이트만 임시 보관한다."""
        super().__init__(repository.workspace, repository.journal, max_document_bytes=repository.max_document_bytes)
        self.documents = {}
        self.blobs = {}

    def store(self, path, document):
        """! @brief 프로젝트 크기와 계약을 검증하되 파일을 아직 쓰지 않는다."""
        validate_project(document)
        raw = canonical_bytes(document)
        if len(raw) > self.max_document_bytes:
            raise ProjectError("E_RESOURCE", "새 작업 사본이 프로젝트 512 KiB 상한을 초과했습니다.")
        uri = path + "/revisions/" + document["revision_id"] + "/project.json"
        reference = {"uri": uri, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        self.blobs[uri] = raw
        self.documents[uri] = (deepcopy(reference), deepcopy(document))
        return reference

    def read(self, reference):
        """! @brief 준비한 원본도 참조/해시가 같은 경우에만 읽는다."""
        if reference["uri"] in self.documents:
            expected, document = self.documents[reference["uri"]]
            if expected != reference:
                raise ProjectError("E_HASH", "준비 중인 사본 참조가 다릅니다.")
            return self.blobs[reference["uri"]], deepcopy(document)
        return super().read(reference)
