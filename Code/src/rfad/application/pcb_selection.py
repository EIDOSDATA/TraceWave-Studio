"""! @brief PCB 선택의 미리보기, 출처 조회와 단일 원자 명령을 조정한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_selection_build import compose
from rfad.application.pcb_selection_contract import PROFILE, bounded, read_envelope, validate_input
from rfad.application.pcb_selection_context import context_for, layer_rows
from rfad.application.pcb_selection_review import describe_changes, input_checks, issue, review_references
from rfad.application.project_contract import MAX_DOCUMENT_BYTES
from rfad.catalog.models import CatalogError, canonical_json
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_selection import EXTENSION_KEY, state_hash
from rfad.domain.project import validate_project


class PcbSelectionCoordinator:
    """! @brief 기존 writer/영수증/이력을 재사용하고 별도 프로젝트 저장 경로를 만들지 않는다."""

    def __init__(self, service, database=None):
        """! @brief 카탈로그 경로만 선택적으로 보관하고 시작 시 DB를 읽지 않는다."""
        self.service = service
        self.database = database

    @staticmethod
    def validate_input(method, context, data):
        """! @brief 적용 접수와 조회가 같은 요청 계약을 사용한다."""
        validate_input(method, context, data)

    def _preview(self, state, context, data):
        """! @brief 현재 개정을 고정해 파일 변경 없이 후보와 검토 해시를 만든다."""
        project = self.service.repository.project(state, context)
        document = self.service.repository.load(project)
        if document["revision_id"] != data["expected_revision"]:
            raise ProjectError("E_CONFLICT", "PCB 선택의 기준 개정이 현재 개정과 다릅니다.")
        try:
            built = compose(document, data, self.database)
        except CatalogError as error:
            raise ProjectError(error.code, error.message, details=error.details) from error
        candidate, payload, issues = built["candidate"], built["payload"], built["issues"]
        moved = []
        checks = None
        try:
            validate_project(candidate)
            additional, moved = review_references(document, candidate, built["updated_ports"])
            issues.extend(additional)
            checks = input_checks(candidate)
        except ProjectError as error:
            issues.append(issue(error.code, error.message, blocker=True, details=error.details))
        size = len(canonical_bytes(candidate))
        if size > MAX_DOCUMENT_BYTES:
            issues.append(issue("E_RESOURCE", "출처를 포함한 프로젝트가 32 KiB를 초과합니다. 선택 범위를 줄이십시오.", blocker=True))
        thicknesses = [item["thickness"]["value_si"] if "value_si" in item["thickness"] else None
                       for item in candidate["stackup"]]
        total = sum(thicknesses) * 1000 if thicknesses and None not in thicknesses else None
        draft = built["source_draft"]
        nominal = None if draft is None else draft.get("nominal_thickness_mm")
        if nominal is not None and total is not None:
            issues.append(issue("nominal_thickness_scope_requires_review", "공칭 두께와 모델 층 합계의 포함 범위/공차는 별도로 확인해야 합니다. 차이를 층에 자동 배분하지 않습니다.",
                                nominal_mm=nominal, modeled_mm=total, difference_mm=total - nominal))
        digest = canonical_hash({"project_id": document["project_id"], "expected_revision": data["expected_revision"],
                                 "selection_id": data["selection_id"], "specification": data["specification"], "payload": payload})
        result = {"profile": PROFILE, "project_id": document["project_id"], "expected_revision": data["expected_revision"],
                  "selection_id": data["selection_id"], "preview_hash": digest,
                  "can_apply": not any(item["severity"] == "blocker" for item in issues), "readiness": "not_assessed",
                  "candidate": {key: candidate[key] for key in ("materials", "stackup", "ports")},
                  "candidate_layers": layer_rows(candidate),
                  "changes": describe_changes(document, candidate, moved), "source_draft": draft,
                  "catalog": payload["selection"]["catalog"], "decisions": payload["selection"]["decisions"],
                  "evidence_ids": [entry["id"] for entry in payload["selection"]["evidence"]],
                  "retained_selections": [{"selection_id": entry["id"], "catalog": entry["catalog"],
                                           "evidence_ids": [item["id"] for item in entry["evidence"]]}
                                          for entry in payload["selection"].get("history", [])],
                  "issues": issues, "input_checks": checks,
                  "size": {"document_bytes": size, "document_limit_bytes": MAX_DOCUMENT_BYTES},
                  "modeled_total_thickness_mm": total}
        return bounded(result), payload

    def preview(self, params):
        """! @brief 조회 요청만으로 프로젝트 journal이나 영수증을 변경하지 않는다."""
        context, data = read_envelope(params)
        validate_input("pcb.selection.preview", context, data)
        return self._preview(self.service.journal.read(), context, data)[0]

    def context(self, params):
        """! @brief 화면의 명시적 UUID 대응과 단면 표시용 현재 개정을 읽는다."""
        context, data = read_envelope(params)
        validate_input("pcb.selection.context", context, data)
        project = self.service.repository.project(self.service.journal.read(), context)
        return context_for(self.service.repository.load(project))

    def apply(self, state, context, data):
        """! @brief 같은 영수증 transaction에서 미리보기를 재검증하고 한 명령을 게시한다."""
        preview, payload = self._preview(state, context, data)
        if preview["preview_hash"] != data["preview_hash"]:
            raise ProjectError("E_CONFLICT", "검토한 미리보기와 적용 입력이 다릅니다. 다시 검토하십시오.")
        if not preview["can_apply"]:
            raise ProjectError("E_SCHEMA", "PCB 적층을 적용하기 전에 차단 사유를 해결하십시오.",
                               details={"issues": [item for item in preview["issues"] if item["severity"] == "blocker"][:16]})
        result = self.service._apply(state, context, {"expected_revision": data["expected_revision"],
                                    "command_id": data["command_id"], "type": "pcb_stackup.apply", "payload": payload})
        return {**result, "selection_id": data["selection_id"], "preview_hash": preview["preview_hash"]}

    def get(self, params):
        """! @brief 카탈로그 없이 저장한 출처와 이후 직접 편집의 차이를 조회한다."""
        context, data = read_envelope(params)
        validate_input("pcb.selection.get", context, data)
        project = self.service.repository.project(self.service.journal.read(), context)
        document = self.service.repository.load(project)
        selection = document["extensions"].get(EXTENSION_KEY)
        changes = []
        if selection is not None:
            for entry in selection["decisions"]:
                target = entry["target"]
                current = next((item for item in document[target["collection"]] if item["id"] == target["id"]), None)
                present = current is not None
                for part in target["field"].split("."):
                    if type(current) is not dict or part not in current:
                        present, current = False, None
                        break
                    current = current[part]
                if not present or canonical_json(current) != entry["value_json"]:
                    changes.append({"target": target, "exists": present, "current_value": current,
                                    "selected_value_json": entry["value_json"]})
        return bounded({"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
                        "selection": deepcopy(selection), "modified_since_selection": selection is not None
                        and selection["applied_state_sha256"] != state_hash(document),
                        "changed_selected_fields": changes, "readiness": "not_assessed"})
