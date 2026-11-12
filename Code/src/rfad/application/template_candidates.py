"""! @brief 읽기 전용 명시 기하 후보와 검토 해시를 기존 프로젝트 transaction에 연결한다."""

from copy import deepcopy
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.canvas import build_canvas_dto
from rfad.application.project_contract import MAX_DOCUMENT_BYTES, _fields, _uuid
from rfad.domain.design import preflight_design
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.domain.template_command import apply_template_command
from rfad.domain.template_geometry import generate_geometry, all_ids, object_id
from rfad.domain.template_instance import (EXTENSION_KEY, MAX_INSTANCES, record_hash, instance_status, object_ids)
from rfad.domain.template_ports import generate_port
from rfad.domain.template_seeds import normalize_candidate
from rfad.domain.template_provenance import generation_report
from rfad.templates.cards import list_cards, describe_card, resolve_card


PROFILE = "rfad.template-candidate/0.2"
READ_METHODS = frozenset({"template.list", "template.get", "template.context", "template.synthesize"})
MUTATION_METHODS = frozenset({"template.apply"})
MAX_RESULT_BYTES = 256 * 1024
_CANDIDATE_FIELDS = {"expected_revision", "mode", "template", "instance_id", "target_refs", "binding", "explicit_inputs", "port"}


def _bounded(value):
    """! @brief 큰 후보를 조용히 잘라내지 않고 제한된 DTO 크기를 검사한다."""
    if len(canonical_bytes(value)) > MAX_RESULT_BYTES:
        raise ProjectError("E_RESOURCE", "템플릿 후보 응답이 256 KiB를 초과했습니다.")
    return value


def _read_envelope(params):
    """! @brief 읽기 요청은 receipt나 변경 명령 필드를 받지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    return params["context"], params["input"]


def _targets(document, references):
    """! @brief 명시적으로 선택한 정확한 목표 개정만 후보의 원자료에 복사한다."""
    if type(references) is not list or len(references) > 32:
        raise ProjectError("E_RESOURCE", "템플릿 목표 참조는 최대 32개 목록이어야 합니다.")
    mapping = {item["id"]: item for item in document["targets"]}
    result, seen = [], set()
    for reference in references:
        _fields(reference, {"id", "revision_id"})
        _uuid(reference["id"])
        _uuid(reference["revision_id"])
        current = mapping.get(reference["id"])
        if current is None or current["revision_id"] != reference["revision_id"] or reference["id"] in seen:
            raise ProjectError("E_CONFLICT", "선택한 목표 개정이 없거나 중복/변경되었습니다.", details={"field_path": "target_refs"})
        seen.add(reference["id"])
        result.append(deepcopy(current))
    return result


class TemplateCandidateCoordinator:
    """! @brief 별도 writer 없이 후보 조회, 검토 해시와 원자 적용을 조정한다."""

    def __init__(self, service):
        """! @brief 기존 프로젝트 저장소와 이력 조정자를 재사용한다."""
        self.service = service

    @staticmethod
    def validate_input(method, context, data):
        """! @brief 공개 입력을 닫힌 schema로 제한한다."""
        if method in ("template.list", "template.get"):
            _fields(context, set())
            _fields(data, set() if method == "template.list" else {"template_id", "version"})
            return
        _fields(context, {"project_id"})
        _uuid(context["project_id"])
        if method == "template.context":
            _fields(data, {"expected_revision"})
            _uuid(data["expected_revision"])
            return
        if method not in ("template.synthesize", "template.apply"):
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 템플릿 요청입니다.")
        _fields(data, _CANDIDATE_FIELDS | ({"command_id", "preview_hash"} if method == "template.apply" else set()), {"seed"})
        _uuid(data["expected_revision"])
        _uuid(data["instance_id"])
        if data["mode"] not in ("explicit_geometry", "initial_estimate"):
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 템플릿 후보 방식입니다.")
        if method == "template.apply":
            _uuid(data["command_id"])
            digest = data["preview_hash"]
            if type(digest) is not str or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ProjectError("E_SCHEMA", "적용에는 검토한 preview_hash가 필요합니다.")

    def _document(self, state, context, data):
        """! @brief preview와 적용 모두 같은 현재 개정의 원본을 사용한다."""
        project = self.service.repository.project(state, context)
        document = self.service.repository.load(project)
        if document["revision_id"] != data["expected_revision"]:
            raise ProjectError("E_CONFLICT", "템플릿 요청의 기준 개정이 현재 개정과 다릅니다.")
        return document

    def _context(self, document):
        """! @brief 조회 때만 UUID를 발급하고 프로젝트나 입력 기본값은 만들지 않는다."""
        board = document["board"]
        return _bounded({
            "profile": PROFILE, "project_id": document["project_id"], "expected_revision": document["revision_id"],
            "new_instance_id": str(uuid4()), "cards": list_cards(),
            "board": None if board is None else {"id": board["id"], "kind": board["outline"]["kind"]},
            "frame_id": None if board is None else board["frame_id"],
            "bindings": [{"layer_id": layer["id"], "label": layer["name"], "material_id": layer["material_id"]}
                         for layer in document["stackup"] if layer["role"] == "conductor"],
            "targets": [{key: item[key] for key in ("id", "revision_id", "name")} for item in document["targets"]],
            "instances": [instance_status(document, record) for record in document["extensions"].get(EXTENSION_KEY, {"instances": []})["instances"]],
            "physical_defaults_supplied": False,
        })

    def _preview(self, state, context, data):
        """! @brief 파일 변경 없이 후보를 구성하고 현재 원본/출처/입력의 해시를 묶는다."""
        document = self._document(state, context, data)
        base = {"profile": PROFILE, "project_id": document["project_id"], "expected_revision": document["revision_id"],
                "instance_id": data["instance_id"], "evaluation_status": "not_evaluated", "solver_settings_changed": False}
        try:
            card = resolve_card(data["template"])
            targets = _targets(document, data["target_refs"])
            existing = document["extensions"].get(EXTENSION_KEY, {"instances": []})["instances"]
            if len(existing) >= MAX_INSTANCES or any(item["id"] == data["instance_id"] for item in existing):
                raise ProjectError("E_CONFLICT", "인스턴스가 이미 존재하거나 템플릿 8개 상한에 도달했습니다.")
            inputs, estimate = normalize_candidate(card, data["explicit_inputs"], data["mode"], data.get("seed"))
            additions = generate_geometry(document, data["instance_id"], data["binding"], card, inputs)
            generate_port(document, additions, data["instance_id"], data["binding"], card, data["port"])
            if additions["ports"] and object_id(data["instance_id"], "port") in all_ids(document):
                raise ProjectError("E_CONFLICT", "생성할 포트 UUID가 기존 객체와 충돌합니다.")
            source_document = deepcopy(document)
            source_document["extensions"] = {}
            record = {"id": data["instance_id"], "card": deepcopy(card), "base_revision": document["revision_id"],
                      "base_content_hash": canonical_hash(document), "binding": deepcopy(data["binding"]),
                      "inputs": inputs, "requested_inputs": deepcopy(data["explicit_inputs"]), "port_recipe": deepcopy(data["port"]),
                      "target_snapshots": targets, "objects": additions, "source_document": source_document,
                      "source_document_hash": canonical_hash(source_document)}
            if card["schema"] == "rfad.template-card/0.3":
                record.update(mode=data["mode"], initial_estimate=estimate)
            record["record_hash"] = record_hash(record)
            payload = {"instance_id": data["instance_id"], "expected_instance_hash": None, "replacement": record}
            candidate = deepcopy(document)
            apply_template_command(candidate, payload)
            validate_project(candidate)
            size = len(canonical_bytes(candidate))
            if size > MAX_DOCUMENT_BYTES:
                raise ProjectError("E_RESOURCE", "템플릿 출처를 포함한 프로젝트가 문서 크기 상한을 초과했습니다.")
            digest = canonical_hash({"project_id": document["project_id"], "expected_revision": data["expected_revision"], "payload": payload})
            diagnostics = preflight_design(candidate, "em")
            issues = [] if data["port"] is not None else [{"severity": "warning", "code": "E_PORT_UNKNOWN", "message": "포트 미정의 geometry-only 후보입니다. 저항과 급전 조건을 자동 생성하지 않습니다."}]
            if card["schema"] == "rfad.template-card/0.3":
                issues.append({"severity": "warning", "code": "W_PARTIAL_REFERENCE",
                               "message": "원문 일부 도체만 생성합니다. 접지/비아/급전/적층과 전체 보드 재현은 포함하지 않습니다."})
                for conflict in card["evidence"]["source_conflicts"]:
                    issues.append({"severity": "warning", "code": "W_SOURCE_CONFLICT", "message": conflict})
            if estimate is not None:
                issues.append({"severity": "warning", "code": "W_SEED_ASSUMPTION",
                               "message": "초기식 조건은 사용자 가정입니다. 현재 기판의 물성/접지 조건을 확인하거나 공진/정합을 계산한 결과가 아닙니다."})
            result = {**base, "can_apply": True, "preview_hash": digest, "scene": build_canvas_dto(candidate),
                      "card": card, "generated_ids": object_ids(record), "issues": issues,
                      "generation": generation_report(card, inputs, estimate),
                      "initial_estimate": estimate,
                      "input_checks": {"scope": "input_only", "input_status": "blocked" if diagnostics else "valid", "solver_ready": False,
                                       "diagnostics": diagnostics[:32], "diagnostic_count": len(diagnostics)},
                      "size": {"document_bytes": size, "document_limit_bytes": MAX_DOCUMENT_BYTES}}
            return _bounded(result), payload
        except ProjectError as error:
            return {**base, "can_apply": False, "preview_hash": None, "scene": None, "generated_ids": {},
                    "input_checks": None, "issues": [{"severity": "blocker", "code": error.code, "message": error.message, "details": error.details}]}, None

    def query(self, method, params):
        """! @brief 카드/문맥/후보 조회는 저장소와 영수증을 변경하지 않는다."""
        context, data = _read_envelope(params)
        self.validate_input(method, context, data)
        if method == "template.list":
            return {"profile": PROFILE, "cards": list_cards(), "read_only": True}
        if method == "template.get":
            return {"profile": PROFILE, "card": describe_card(data["template_id"], data["version"]), "new_instance_id": str(uuid4())}
        state = self.service.journal.read()
        if method == "template.context":
            return self._context(self._document(state, context, data))
        return self._preview(state, context, data)[0]

    def apply(self, state, context, data):
        """! @brief 같은 writer transaction에서 재검토한 후보를 한 이력 명령으로 게시한다."""
        self.validate_input("template.apply", context, data)
        preview, payload = self._preview(state, context, data)
        if not preview["can_apply"]:
            raise ProjectError("E_SCHEMA", "템플릿을 적용하기 전에 차단 입력을 해결하십시오.", details={"issues": preview["issues"]})
        if preview["preview_hash"] != data["preview_hash"]:
            raise ProjectError("E_CONFLICT", "검토한 템플릿 후보와 입력이 다릅니다. 다시 미리 보십시오.")
        result = self.service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"],
                                                     "type": "template_instance.apply", "payload": payload})
        return {**result, "instance_id": data["instance_id"], "preview_hash": preview["preview_hash"]}
