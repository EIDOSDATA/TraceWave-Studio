"""! @brief 기록된 개정과 객체에서 해석 조건, 작업, 보고서 및 고정 결과를 찾는다."""

from io import BytesIO
import json
import unicodedata

from rfad.application import handoff_archive, rf_validation_records
from rfad.application.editor import editor_items
from rfad.application.project_study_results import read_assessment
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields, _uuid
from rfad.application.result_catalog import page
from rfad.application.result_sources import owned_reference, resolve, revision_document, snapshot_document, solver_labels
from rfad.application.solver_requests import PCB_PROFILE, REFERENCE_PROFILE
from rfad.domain import solver_conditions
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_features import REPLAY_COMMAND
from rfad.domain.physical_setup import setup as physical_setup


METHOD = "result.project_activity"
PROFILE = "rfad.project-activity/0.1"
TYPES = {"condition": "settings", "plan": "settings", "prepare": "run", "run": "run", "result": "run",
         "study_report": "report", "rf_report": "report", "handoff_report": "report"}
PHASES = {"solver.plan": "plan", "solver.prepare": "prepare", "job.submit": "run"}


def _fold(query):
    """! @brief 입력 방식과 영어 대소문자에 관계없이 보존한 문자열에 부분 검색한다."""
    return unicodedata.normalize("NFKC", query).strip().casefold()


def _row(kind, identity, name, state, revision, *, snapshot=None, other_revision=None, timestamp=None):
    """! @brief 목록 표시와 클릭에 필요한 작고 안정적인 식별자만 투영한다."""
    return {"kind": kind, "id": identity, "name": name, "state": state, "revision_id": revision,
            "record_revision_id": other_revision, "snapshot_id": snapshot, "time": timestamp}


class Activity:
    """! @brief 요청 단위로 프로젝트 소유 기록과 실제 보존 입력을 결합한다."""

    def __init__(self, service, context):
        """! @brief 현재 개정은 등록 조건의 발견에만 사용하고 과거 원본 조회는 고정한다."""
        self.service = service
        self.context = context
        self.project_id = context["project_id"]
        self.state = service.journal.read()
        self.project = service._project(self.state, context)
        self.current = service._load(self.project)
        self.results = {key: value for key, value in self.state["solver_results"].items()
                        if value["project_id"] == self.project_id}
        self._plans = {}
        self._documents = {}
        self._names = {}
        self._labels = None

    def label(self, identity):
        """! @brief 공통 결과 탐색의 이름을 그대로 사용한다."""
        if self._labels is None:
            self._labels = solver_labels(self.state, self.project_id)
        return self._labels[identity]["label"]

    def plan(self, identity):
        """! @brief compact 실행도 저장된 계획 해시에서 같은 설정과 개정을 찾는다."""
        if identity not in self._plans:
            registered = self.state["analysis_plans"].get(identity)
            if registered is None or registered["project_id"] != self.project_id:
                raise ProjectError("E_MISSING_ARTIFACT", "해석 기록의 원래 계획을 찾을 수 없습니다.")
            _, plan = self.service.solver._record(self.state, "analysis_plans", registered["reference"],
                                                  "plan_id", self.project_id)
            if plan["plan_id"] != identity or plan["snapshot"]["project_id"] != self.project_id:
                raise ProjectError("E_HASH", "등록된 해석 계획의 식별자 또는 프로젝트가 다릅니다.")
            self._plans[identity] = plan
        return self._plans[identity]

    def job_plan(self, job):
        """! @brief 실행 모드나 최신 결과를 기준으로 삼지 않고 실제 요청의 계획만 읽는다."""
        if job["operation_method"] == "solver.plan":
            plan = job["solver"]["plan"]
            expected = job["input"]["snapshot"]
            if any(plan["snapshot"][key] != expected[key] for key in ("snapshot_id", "content_hash")):
                raise ProjectError("E_HASH", "계획 요청의 스냅샷이 다릅니다.")
            return plan
        if job["operation_method"] == "solver.prepare":
            requested = job["input"]["analysis_plan"]
            identity = requested["plan_id"]
            registered = self.state["analysis_plans"].get(identity)
        else:
            requested = job["input"]["task_plan"]["prepared_plan"]
            registered = self.state["prepared_plans"].get(requested["prepared_plan_id"])
            identity = None if registered is None else registered["analysis_plan_id"]
        if registered is None or registered["project_id"] != self.project_id:
            raise ProjectError("E_MISSING_ARTIFACT", "작업에 사용한 계획을 찾을 수 없습니다.")
        if registered["reference"]["content_hash"] != requested["content_hash"]:
            raise ProjectError("E_HASH", "작업에 봉인된 계획의 요청 해시와 등록 해시가 다릅니다.")
        return self.plan(identity)

    def entry(self, kind, identity, name, status, snapshot, payload, timestamp=None):
        """! @brief 스냅샷이 가리키는 개정에만 실행과 보고서를 연결한다."""
        if snapshot["project_id"] != self.project_id:
            raise ProjectError("E_HASH", "기록의 스냅샷 소유 프로젝트가 다릅니다.")
        return (_row(kind, identity, name, status, snapshot["revision_id"], snapshot=snapshot["snapshot_id"],
                     timestamp=timestamp), snapshot, payload)

    def entries(self, category="all", selected=None):
        """! @brief 기존 목록과 이력을 읽어 실행 없는 개정에 저장한 조건도 검색한다."""
        if category in ("all", "settings"):
            named = {row["id"]: (row, self.current["revision_id"]) for row in solver_conditions.records(self.current)}
            for identity, record in self.state["commands"].items():
                if record["project_id"] != self.project_id:
                    continue
                command = record["command"]
                if command["type"] == REPLAY_COMMAND:
                    command = command["payload"]["command"]
                if command["type"] == solver_conditions.INSERT:
                    condition = command["payload"]["record"]
                    if identity == condition["id"]:
                        named[identity] = (condition, record["new_revision"])
            for condition, stored in named.values():
                if selected is not None and selected != ("condition", condition["id"]):
                    continue
                row = _row("condition", condition["id"], condition["name"], "recorded", condition["revision_id"],
                           other_revision=stored)
                yield row, None, condition
        seen = set()
        if category in ("all", "settings", "run"):
            for job in self.state["jobs"].values():
                phase = PHASES.get(job.get("operation_method"))
                if (job.get("context", {}).get("project_id") != self.project_id or "solver" not in job or phase is None
                        or category != "all" and TYPES[phase] != category):
                    continue
                event = job["events"][-1]
                if phase == "run" and job["state"] == "completed":
                    published_id = event.get("operation_result", {}).get("artifact_id")
                    if published_id in self.results:
                        seen.add(published_id)
                if selected is not None and selected != (phase, job["job_id"]):
                    continue
                plan = self.job_plan(job)
                result_id = event.get("operation_result", {}).get("artifact_id") if phase == "run" else None
                name = self.label(result_id) if result_id in self.results else {
                    "plan": "해석 계획 조건", "prepare": "해석 준비", "run": "해석 실행"}[phase]
                yield self.entry(phase, job["job_id"], name, job["state"], plan["snapshot"], (job, plan),
                                 event["timestamp"])
            if category in ("all", "run"):
                for identity, record in self.results.items():
                    if identity not in seen and (selected is None or selected == ("result", identity)):
                        yield self.entry("result", identity, self.label(identity), "completed", record["snapshot"], record,
                                         record["snapshot"]["sealed_at"])
        if category in ("all", "report"):
            for study in self.state.get("studies", {}).values():
                if (study["project_id"] == self.project_id and "assessment" in study
                        and (selected is None or selected == ("study_report", study["study_id"]))):
                    yield self.entry("study_report", study["study_id"], study["name"], study["state"], study["snapshot"],
                                     study, study["created_at"])
            for record in self.state.get("rf_validations", {}).values():
                if record["project_id"] == self.project_id:
                    for report in record["reports"]:
                        if selected is not None and selected != ("rf_report", report["report_id"]):
                            continue
                        yield self.entry("rf_report", report["report_id"], record["name"], report["status"],
                                         record["snapshot"], (record, report), report["created_at"])
            for package in self.state.get("handoff_packages", {}).values():
                if (package["project_id"] == self.project_id and package["profile"] == handoff_archive.PROFILE
                        and (selected is None or selected == ("handoff_report", package["package_id"]))):
                    snapshot = self.state["snapshots"].get(package["snapshot_id"])
                    if snapshot is None or snapshot["revision_id"] != package["revision_id"]:
                        raise ProjectError("E_HASH", "인계 보고서의 등록 개정과 스냅샷이 다릅니다.")
                    name = "인계 보고서 / " + (snapshot["description"] or package["file_name"])
                    yield self.entry("handoff_report", package["package_id"], name, "recorded", snapshot, package)

    def document(self, row, snapshot):
        """! @brief 복제 조건의 원래 개정이 없으면 현재 개정을 그 자리에서 사용하지 않는다."""
        revision = row["revision_id"]
        key = (revision, row["snapshot_id"])
        if key not in self._documents:
            if snapshot is not None:
                document = snapshot_document(self.service, self.project, self.project_id, snapshot)
            elif revision in self.project["revisions"]:
                document, _ = revision_document(self.service, self.state, self.project, self.project_id, revision)
            else:
                document = None
            self._documents[key] = document
        return self._documents[key]

    def matches(self, row, snapshot, query):
        """! @brief 개체의 이름과 UUID를 당시 개정에서 읽고 현재 이름으로 바꾸지 않는다."""
        key = (row["revision_id"], row["snapshot_id"])
        if key not in self._names:
            source = self.document(row, snapshot)
            names = {}
            if source is not None:
                names = {item["id"]: item["label"] for item in editor_items(source)}
                setup = physical_setup(source)
                for collection in (source.get("targets", []), setup["surfaces"], setup["parts"], setup["scenarios"]):
                    names.update({item["id"]: item["name"] for item in collection})
            self._names[key] = names
        return [{"id": identity, "name": name} for identity, name in self._names[key].items()
                if query in _fold(name) or query in identity.casefold()]

    def search(self, data):
        """! @brief 개정 및 객체를 교차 검색하고 같은 목록 해시의 다음 페이지를 제공한다."""
        revision, obj = _fold(data["revision"]), _fold(data["object"])
        items = []
        for row, snapshot, _ in self.entries(data["category"]):
            if revision and not any(revision in token.casefold() for token in
                                    (row["revision_id"], row["record_revision_id"] or "", row["snapshot_id"] or "")):
                continue
            matching = self.matches(row, snapshot, obj) if obj else []
            if obj and not matching:
                continue
            items.append({**row, "matches": matching[:3], "match_count": len(matching)})
        items.sort(key=lambda row: (row["time"] or 0, row["name"], row["kind"], row["id"]), reverse=True)
        return {"current_revision_id": self.current["revision_id"], **page(items, data)}

    def detail(self, row, snapshot, record):
        """! @brief 선택 자료만 검증해 열고 그 기록이 명시하는 결과를 모은다."""
        kind = row["kind"]
        related = {}
        body = {}
        relation = "recorded"
        if kind == "condition":
            body = record
            relation = "same_saved_settings"
            for identity, result in self.results.items():
                anchor = result["snapshot"]
                if anchor["revision_id"] not in (row["revision_id"], row["record_revision_id"]):
                    continue
                plan = self.plan(result["analysis_plan_id"])
                if (plan["snapshot"] == anchor and plan["case"].get("settings") == record["settings"]
                        and record in solver_conditions.records(plan["source_semantics"])):
                    related[identity] = None
        elif kind in PHASES.values():
            job, plan = record
            last = job["events"][-1]
            body = {"method": job["operation_method"], "plan_id": plan["plan_id"],
                    "settings": plan["case"].get("settings"), "budget": job["input"].get("budget"),
                    "execution_mode": job["input"].get("task_plan", {}).get("execution_mode"),
                    "error": last.get("error"), "execution_cost": last.get("execution_cost"),
                    "events": [{key: event[key] for key in ("seq", "timestamp", "state", "phase") if key in event}
                               for event in job["events"]]}
            if kind == "run":
                if job["state"] == "completed":
                    published = last["operation_result"]
                    identity = published["artifact_id"]
                    if (identity not in self.results or self.results[identity]["snapshot"] != snapshot
                            or self.results[identity]["normalized"] != published["normalized_result"]):
                        raise ProjectError("E_HASH", "해당 실행이 게시한 정규 결과가 목록과 다릅니다.")
                    related[identity] = None
            else:
                prepared = last.get("operation_result", {}).get("prepared_plan", {}).get("prepared_plan_id")
                related = {identity: None for identity, value in self.results.items()
                           if value["snapshot"] == snapshot and value["analysis_plan_id"] == plan["plan_id"]
                           and (kind == "plan" or value["prepared_plan_id"] == prepared)}
        elif kind == "result":
            related[row["id"]] = None
            body = {"plan_id": record["analysis_plan_id"], "metadata": record["metadata"], "normalized": record["normalized"]}
        elif kind == "study_report":
            body = read_assessment(self.service, record)
            related = dict.fromkeys(body["case_result_ids"])
        elif kind == "rf_report":
            campaign, report = record
            body = rf_validation_records.load_json(self.service, owned_reference(self.project, report["artifact"]))
            if (body["report_id"] != row["id"] or body["validation_id"] != campaign["validation_id"]
                    or body["snapshot"] != snapshot or canonical_hash(body) != report["assessment_hash"]):
                raise ProjectError("E_HASH", "RF 보고서의 식별자, 개정 또는 해시가 다릅니다.")
            for case in body["cases"]:
                for item in (case, case.get("postprocess_evidence") or {}):
                    if item.get("source"):
                        related[item["source"]["artifact_id"]] = item["pin"]
        else:
            raw = self.service.journal.read_artifact(owned_reference(self.project, record["artifact"]))
            with handoff_archive.read_archive(BytesIO(raw)) as (archive, manifest):
                if any(manifest[key] != snapshot[key] for key in ("project_id", "revision_id", "snapshot_id", "content_hash")):
                    raise ProjectError("E_HASH", "인계 보고서의 봉인 개정이 등록과 다릅니다.")
                report = handoff_archive.read_canonical(archive, "report.json", len(raw))
            items = report["items"]
            for item in items:
                if item["kind"] == "solver_result":
                    result = self.results.get(item["id"])
                    if result is None or result["normalized"] != item["artifact"]:
                        raise ProjectError("E_HASH", "인계 보고서의 원래 결과 참조가 등록과 다릅니다.")
                    related[item["id"]] = None
            body = {**report, "package": record, "item_count": len(items),
                    "items": [{key: item[key] for key in ("kind", "name", "status", "copy_state")} for item in items[:100]]}
        links = []
        for identity, pin in related.items():
            result = self.results.get(identity)
            if result is None or snapshot is not None and result["snapshot"] != snapshot:
                raise ProjectError("E_HASH", "해당 기록의 결과가 같은 프로젝트 개정에 없습니다.")
            profile = result["metadata"]["profile"]
            if profile in (PCB_PROFILE, REFERENCE_PROFILE):
                links.append({"artifact_id": identity, "name": self.label(identity), "pin": pin,
                              "has_evidence": profile == PCB_PROFILE})
        return {"body": body, "links": links, "relation": relation}

    def select(self, data):
        """! @brief 다시 열린 기록은 임의 결과 ID나 최신 결과로 전환하지 않는다."""
        kind, identity = data["kind"], data["id"]
        selected = next(self.entries(TYPES[kind], (kind, identity)), None)
        if selected is None:
            raise ProjectError("E_MISSING_ARTIFACT", "이 프로젝트에 선택한 기록이 없습니다.")
        row, snapshot, record = selected
        if data["page"] == "origin":
            document = self.document(row, snapshot)
            if document is None:
                raise ProjectError("E_MISSING_ARTIFACT", "기록의 원래 설계 개정이 이 프로젝트에 보존되지 않았습니다.")
            raw = canonical_bytes(document)
            return {"row": row, "snapshot": snapshot, "sha256": canonical_hash(document),
                    "metadata": document["metadata"], "bytes": len(raw),
                    "document": document if len(raw) <= 384 * 1024 else None}
        detail = self.detail(row, snapshot, record)
        if data["page"] == "pin":
            link = next((item for item in detail["links"] if item["artifact_id"] == data["artifact_id"]), None)
            if link is None:
                raise ProjectError("E_MISSING_ARTIFACT", "선택한 기록에 연결된 결과가 아닙니다.")
            source = {"kind": "solver", "artifact_id": link["artifact_id"]}
            result = resolve(self.service, self.context, source, link["pin"])
            return {"source": source, "pin": result["pin"], "has_evidence": link["has_evidence"]}
        return {"row": row, "snapshot": snapshot, **detail}


def read(service, params):
    """! @brief 범위와 선택을 확인한 읽기 요청만 허용하며 상태를 쓰지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    context = _fields(params["context"], {"project_id"})
    _uuid(context["project_id"])
    data = _fields(params["input"], {"page"}, {"category", "revision", "object", "offset", "limit", "catalog_hash",
                                              "kind", "id", "artifact_id"})
    action = data["page"]
    if action == "search":
        _fields(data, {"page", "category", "revision", "object", "offset", "limit", "catalog_hash"})
        if data["category"] not in ("all", "settings", "run", "report") or any(
                not isinstance(data[key], str) or len(data[key]) > 256 for key in ("revision", "object")):
            raise ProjectError("E_SCHEMA", "기록 종류와 256자 이내의 개정 또는 객체 검색어를 확인하세요.")
        result = Activity(service, context).search(data)
    elif action in ("detail", "origin", "pin"):
        _fields(data, {"page", "kind", "id"} | ({"artifact_id"} if action == "pin" else set()))
        _uuid(data["id"])
        if action == "pin":
            _uuid(data["artifact_id"])
        if not isinstance(data["kind"], str) or data["kind"] not in TYPES:
            raise ProjectError("E_SCHEMA", "지원하는 기록 종류가 아닙니다.")
        result = Activity(service, context).select(data)
    else:
        raise ProjectError("E_SCHEMA", "지원하는 기록 조회 페이지가 아닙니다.")
    if len(canonical_bytes(result)) > 512 * 1024:
        raise ProjectError("E_RESOURCE", "프로젝트 기록의 응답이 조회 상한을 초과합니다.")
    return {"profile": PROFILE, **result}
