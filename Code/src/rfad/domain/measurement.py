"""! @brief 시료/교정/불확도 원문과 자기 참조 없는 불변 측정 색인을 검증한다."""

from copy import deepcopy
from datetime import datetime
import hashlib

from rfad.application.canonical import CanonicalEncodingError, canonical_bytes, canonical_hash
from rfad.domain.design import _fields, _uuid
from rfad.domain.network_data import UNITS, _json, fail, finite, text, validate_dataset
from rfad.domain.network_library import artifact, digest

KEY = "rfad.measurement"
SCHEMA = "rfad.measurement-registry/0.1"
RECORD_SCHEMA = "rfad.measurement-record/0.1"
COMMAND = "measurement.registry.replace"
MAX_RECORDS = 32
MAX_BYTES = 64 * 1024
ARTIFACT_LIMITS = {"records": 64 * 1024, "alignments": 256 * 1024, "comparisons": 1024 * 1024}
EVIDENCE = ("planned", "declared", "reported", "unknown")
SECTIONS = {
    "specimen": {"identifier": "text", "serial": "text", "lot": "text", "fabrication_revision": "text",
                 "assembly_revision": "text", "mounting_cycle": "positive_integer", "trim_notes": "text",
                 "design_snapshot": "json", "delivered_materials": "json"},
    "acquisition": {"instrument": "text", "serial": "text", "firmware": "text", "measured_at": "datetime",
                    "timezone": "text", "if_bandwidth_hz": "positive_number", "averages": "positive_integer",
                    "stimulus_power": "power", "setting_artifacts": "artifacts"},
    "calibration": {"method": "text", "performed_at": "datetime", "timezone": "text", "kit_id": "text",
                    "standard_ids": "texts", "certificate_refs": "artifacts", "port_ids": "ports",
                    "frequency_range_hz": "frequency_range", "reference_planes": "port_planes",
                    "verification_notes": "text"},
    "fixture": {"connector": "text", "cable": "text", "fixture_id": "text", "path_notes": "text",
                "mounting_notes": "text", "included_effects": "texts", "corrected_effects": "texts"},
    "environment": {"temperature": "temperature", "humidity": "humidity", "enclosure": "text",
                    "battery": "text", "pose": "text", "nearby_objects": "texts", "physical_setup_snapshot": "json"},
}
RECORD_FIELDS = {"schema", "id", "name", "data_class", "data_anchor", "previous_record_id", "created_at_utc",
                 "author", "reason", "source_refs", "uncertainty", "external_processing", "attachments", "extra", *SECTIONS}


def bounded(value, field, limit=MAX_BYTES):
    """! @brief 비유한/순환/과대 JSON을 원문 변경 없이 차단한다."""
    _json(value, field)
    try:
        raw = canonical_bytes(value)
    except CanonicalEncodingError as error:
        fail(str(error), field)
    if len(raw) > limit:
        fail("측정 기록의 바이트 상한을 초과했습니다.", field, "E_RESOURCE")
    return raw


def _list(value, field, maximum=MAX_RECORDS):
    """! @brief 빈 목록과 미정을 동일시하지 않고 목록 상한만 검사한다."""
    if type(value) is not list or len(value) > maximum:
        fail("측정 기록 목록 상한 또는 형식이 다릅니다.", field, "E_RESOURCE")
    return value


def _refs(value, field):
    """! @brief 제출 출처 문자열의 순서와 중복을 그대로 보존한다."""
    for item in _list(value, field):
        text(item, field)


def _integer(value, field):
    """! @brief 반복 횟수에 bool이나 실수를 허용하지 않는다."""
    if type(value) is not int or not 1 <= value <= 1_000_000:
        fail("횟수는 1~1000000 정수여야 합니다.", field)


def _date(value, field, utc=False):
    """! @brief 명시 시각을 검사하며 시간대가 없는 원문을 로컬 시각으로 채우지 않는다."""
    text(value, field, limit=128)
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("ISO 8601 날짜/시각이 필요합니다.", field)
    if utc and (stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0):
        fail("기록 생성 시각에는 UTC offset을 명시하십시오.", field)
    return stamp


def _frequency_range(value, field):
    """! @brief 명시 주파수 범위를 유한한 비음수 닫힌 구간으로 검사한다."""
    if type(value) is not list or len(value) != 2:
        fail("주파수 범위는 [하한, 상한] 두 값입니다.", field)
    lower, upper = (finite(item, field) for item in value)
    if lower < 0 or upper < lower:
        fail("주파수 범위의 순서 또는 부호가 다릅니다.", field)


def _ports(value, field, dataset=None):
    """! @brief 자료 포트와 프로젝트 급전 포트를 묵시적으로 같은 것으로 취급하지 않는다."""
    _list(value, field, 2)
    for identity in value:
        _uuid(identity, field)
    if len(set(value)) != len(value):
        fail("포트 참조가 중복됩니다.", field, "E_CONFLICT")
    if dataset is not None and any(identity not in dataset["port_ids"] for identity in value):
        fail("선택한 자료에 없는 포트 참조입니다.", field, "E_CONFLICT")


def validate_anchor(value, project_id=None):
    """! @brief 새 기록의 미래 문서 hash 대신 이미 확정된 자료/과거 pin만 받는다."""
    if type(value) is not dict:
        fail("측정 원본 anchor가 필요합니다.", "data_anchor")
    if value.get("kind") == "network_artifact":
        _fields(value, {"kind", "project_id", "dataset_id", "dataset", "raw", "normalized_hdf5"}, "data_anchor")
        for key in ("project_id", "dataset_id"):
            _uuid(value[key], "data_anchor." + key)
        if project_id is not None and value["project_id"] != project_id:
            fail("측정 원본의 소유 프로젝트가 다릅니다.", "data_anchor.project_id", "E_CONFLICT")
        for key in ("dataset", "normalized_hdf5", "raw"):
            if key != "raw" or value[key] is not None:
                artifact(value[key], "data_anchor." + key)
    elif value.get("kind") == "pinned_result":
        _fields(value, {"kind", "source", "pin"}, "data_anchor")
        source = value["source"]
        if type(source) is not dict:
            fail("고정 원본 선택이 필요합니다.", "data_anchor.source")
        kind = source.get("kind")
        fields = {"network": {"kind", "dataset_id", "revision_id", "snapshot_id"},
                  "solver": {"kind", "artifact_id"}, "sweep": {"kind", "study_id", "index"}}
        if type(kind) is not str or kind not in fields:
            fail("지원하지 않는 원본 종류입니다.", "data_anchor.source", "E_UNSUPPORTED")
        _fields(source, fields[kind], "data_anchor.source")
        for key, item in source.items():
            if key.endswith("_id") and not (key == "snapshot_id" and item is None):
                _uuid(item, "data_anchor.source." + key)
        if kind == "sweep" and (type(source["index"]) is not int or not 0 <= source["index"] < 128):
            fail("연구 후보 순번은 0~127 정수입니다.", "data_anchor.source.index")
        _fields(value["pin"], {"identity_hash", "dataset_sha256"}, "data_anchor.pin")
        for key, item in value["pin"].items():
            digest(item, "data_anchor.pin." + key)
    else:
        fail("지원하지 않는 측정 원본 anchor입니다.", "data_anchor", "E_UNSUPPORTED")


def empty_registry():
    """! @brief 미기록 프로젝트에 조회만으로 저장할 확장을 만들지 않는다."""
    return {"schema": SCHEMA, "records": [], "alignments": [], "comparisons": []}


def registry(document):
    """! @brief 현재 색인을 원문과 분리된 사본으로 읽는다."""
    return deepcopy(document["extensions"].get(KEY, empty_registry()))


def validate_registry(value):
    """! @brief 종류별 32개 참조, 단일 이전 기록 사슬과 총 바이트를 검사한다."""
    _fields(value, {"schema", "records", "alignments", "comparisons"}, KEY)
    if value["schema"] != SCHEMA:
        fail("지원하지 않는 측정 색인 버전입니다.", KEY, "E_VERSION")
    used = set()
    for collection in ("records", "alignments", "comparisons"):
        identities = []
        for row in _list(value[collection], collection):
            fields = {"id", "name", "artifact"} | ({"previous_record_id"} if collection == "records" else set())
            _fields(row, fields, collection)
            identity = _uuid(row["id"], collection + ".id")
            if identity in used:
                fail("측정 색인 ID가 중복됩니다.", collection, "E_CONFLICT")
            used.add(identity)
            identities.append(identity)
            text(row["name"], collection + ".name", limit=256)
            artifact(row["artifact"], collection + ".artifact")
            if row["artifact"]["bytes"] > ARTIFACT_LIMITS[collection]:
                fail("측정 기록/정렬/비교 artifact의 종류별 상한을 초과했습니다.", collection, "E_RESOURCE")
            if collection == "records" and row["previous_record_id"] is not None:
                _uuid(row["previous_record_id"], collection + ".previous_record_id")
        if identities != sorted(identities):
            fail("측정 색인은 UUID 순서여야 합니다.", collection)
    graph = {row["id"]: row["previous_record_id"] for row in value["records"]}
    parents = [parent for parent in graph.values() if parent is not None]
    if len(set(parents)) != len(parents):
        fail("하나의 과거 측정 기록에서 두 최신 기록으로 분기할 수 없습니다.", "records", "E_CONFLICT")
    for identity in graph:
        seen = set()
        while identity is not None:
            if identity in seen or identity not in graph:
                fail("이전 측정 기록이 없거나 순환합니다.", "records.previous_record_id", "E_CONFLICT")
            seen.add(identity)
            identity = graph[identity]
    bounded(value, KEY)


def validate_project_registry(document):
    """! @brief 과거 프로젝트는 측정 확장 없이 원문 그대로 유효하다."""
    if KEY in document["extensions"]:
        validate_registry(document["extensions"][KEY])


def record_template(*, identity, name, data_anchor, created_at_utc, reason, previous_record_id=None):
    """! @brief application이 제공한 식별자/시각만 사용하며 실물 조건을 모두 미정으로 둔다."""
    return {"schema": RECORD_SCHEMA, "id": identity, "name": name, "data_class": "unknown",
            "data_anchor": deepcopy(data_anchor), "previous_record_id": previous_record_id,
            "created_at_utc": created_at_utc, "author": None, "reason": reason, "source_refs": [],
            **{section: {**{key: None for key in fields}, "source_refs": []} for section, fields in SECTIONS.items()},
            "uncertainty": [], "external_processing": [], "attachments": [], "extra": {}}


def _issue(field, code, message):
    """! @brief 입력의 미정과 적용 범위를 성공 판정과 분리한 진단으로 만든다."""
    return {"field_path": field, "code": code, "message": message}


def _leaf(leaf, kind, field, dataset, diagnostics):
    """! @brief 알려진 필드의 원문 값과 계획/제출 근거를 분리해 검증한다."""
    if leaf is None:
        return
    _fields(leaf, {"value", "evidence", "source_refs"}, field)
    if type(leaf["evidence"]) is not str or leaf["evidence"] not in EVIDENCE:
        fail("측정 근거 종류가 다릅니다.", field + ".evidence")
    _refs(leaf["source_refs"], field + ".source_refs")
    value = leaf["value"]
    if leaf["evidence"] == "unknown" and value is not None:
        fail("미정 근거에 확정 값을 넣을 수 없습니다.", field)
    if value is None:
        return
    if leaf["evidence"] == "planned":
        diagnostics.append(_issue(field, "planned_only", "계획값이며 수행된 측정/교정의 근거가 아닙니다."))
    if kind == "text":
        text(value, field)
    elif kind == "datetime":
        if _date(value, field).utcoffset() is None:
            diagnostics.append(_issue(field, "timezone_missing", "원문 시각의 UTC offset이 미정입니다."))
    elif kind == "positive_integer":
        _integer(value, field)
    elif kind == "positive_number":
        if finite(value, field) <= 0:
            fail("양의 유한 값이 필요합니다.", field)
    elif kind == "frequency_range":
        _frequency_range(value, field)
    elif kind == "ports":
        _ports(value, field, dataset)
    elif kind == "port_planes":
        _list(value, field, 2)
        for item in value:
            _fields(item, {"port_id", "reference_plane"}, field)
            text(item["reference_plane"], field, nullable=True)
        _ports([item["port_id"] for item in value], field, dataset)
    elif kind == "texts":
        _refs(value, field)
    elif kind == "artifacts":
        for item in _list(value, field):
            artifact(item, field)
    elif kind in ("power", "temperature", "humidity"):
        _fields(value, {"number", "unit"}, field)
        number = finite(value["number"], field)
        units = {"power": ("dBm", "W"), "temperature": ("degC", "K"), "humidity": ("%", "1")}[kind]
        if value["unit"] not in units:
            fail("측정 기록의 단위가 해당 값의 의미와 다릅니다.", field, "E_UNIT")
        if (kind == "power" and value["unit"] == "W" and number < 0
                or kind == "temperature" and number < (0 if value["unit"] == "K" else -273.15)
                or kind == "humidity" and not 0 <= number <= (100 if value["unit"] == "%" else 1)):
            fail("측정 기록 값이 정의역 밖입니다.", field)
    else:
        bounded(value, field, 16 * 1024)


def _value(record, section, field):
    """! @brief null 묶음/leaf의 차이는 원문에 두고 판정에서만 미정을 읽는다."""
    group = record[section]
    leaf = group.get(field) if group is not None else None
    return leaf["value"] if leaf is not None else None


def validate_uncertainty(row, dataset=None):
    """! @brief 제출 불확도를 검증하지만 분포/상관/k나 전파 결과를 가정하지 않는다."""
    if dataset is not None:
        validate_dataset(dataset)
    fields = {"id", "measurand", "scope", "form", "scale", "value", "coverage_factor", "coverage_probability",
              "distribution", "estimation", "degrees_of_freedom", "correlation", "method", "repetitions", "source_refs"}
    _fields(row, fields, "uncertainty")
    _uuid(row["id"], "uncertainty.id")
    _fields(row["measurand"], {"parameter_kind", "row_port_id", "column_port_id", "representation"}, "uncertainty.measurand")
    m = row["measurand"]
    if type(m["parameter_kind"]) is not str or m["parameter_kind"] not in UNITS:
        fail("불확도 대상은 S/Z/Y입니다.", "uncertainty.measurand")
    for key in ("row_port_id", "column_port_id"):
        _ports([m[key]], "uncertainty.measurand." + key, dataset)
    if dataset is not None and m["parameter_kind"] != dataset["parameter_kind"]:
        fail("자료와 불확도 대상의 행렬 종류가 다릅니다.", "uncertainty.measurand", "E_CONFLICT")
    if m["representation"] not in ("real", "imag", "magnitude", "magnitude_db", "phase_deg"):
        fail("불확도 표현 종류가 다릅니다.", "uncertainty.measurand.representation")
    for key, choices in (("form", ("standard", "combined_standard", "expanded", "unspecified")),
                         ("scale", ("absolute", "relative", "unspecified")),
                         ("estimation", ("type_a", "type_b", "unspecified"))):
        if type(row[key]) is not str or row[key] not in choices:
            fail("불확도 분류가 다릅니다.", "uncertainty." + key)
    value = row["value"]
    if value is not None:
        _fields(value, {"number", "unit"}, "uncertainty.value")
        if finite(value["number"], "uncertainty.value.number") < 0:
            fail("불확도 크기는 음수가 될 수 없습니다.", "uncertainty.value")
        expected = {"magnitude_db": "dB", "phase_deg": "deg"}.get(m["representation"], UNITS[m["parameter_kind"]])
        units = ("1", "%") if row["scale"] == "relative" else (expected,)
        if value["unit"] not in units:
            fail("불확도 단위와 대상 표현이 다릅니다.", "uncertainty.value.unit", "E_UNIT")
    for key in ("coverage_factor", "degrees_of_freedom"):
        if row[key] is not None and finite(row[key], "uncertainty." + key) <= 0:
            fail("양의 불확도 계수가 필요합니다.", "uncertainty." + key)
    if row["coverage_probability"] is not None and not 0 < finite(row["coverage_probability"], "uncertainty.coverage_probability") < 1:
        fail("포함 확률은 0과 1 사이여야 합니다.", "uncertainty.coverage_probability")
    for key in ("distribution", "method"):
        text(row[key], "uncertainty." + key, nullable=True)
    if row["repetitions"] is not None:
        _integer(row["repetitions"], "uncertainty.repetitions")
    _fields(row["correlation"], {"state", "reference"}, "uncertainty.correlation")
    if row["correlation"]["state"] not in ("unknown", "declared_independent", "documented"):
        fail("불확도 상관 상태가 다릅니다.", "uncertainty.correlation")
    if row["correlation"]["reference"] is not None:
        artifact(row["correlation"]["reference"], "uncertainty.correlation.reference")
    _refs(row["source_refs"], "uncertainty.source_refs")
    _fields(row["scope"], {"frequency_range_hz", "sample_indices"}, "uncertainty.scope")
    scope = row["scope"]
    if scope["frequency_range_hz"] is not None:
        _frequency_range(scope["frequency_range_hz"], "uncertainty.scope.frequency_range_hz")
    indices = scope["sample_indices"]
    if indices is not None:
        _list(indices, "uncertainty.scope.sample_indices", 1001)
        if any(type(i) is not int or not 0 <= i < 1001 for i in indices) or indices != sorted(set(indices)):
            fail("불확도 표본 순번은 중복 없는 증가 정수입니다.", "uncertainty.scope.sample_indices")
        if dataset is not None and any(i >= len(dataset["frequency_hz"]) for i in indices):
            fail("불확도에 없는 표본 순번을 참조했습니다.", "uncertainty.scope.sample_indices", "E_CONFLICT")
    diagnostics = []
    missing = (value is None or row["form"] == "unspecified" or row["scale"] == "unspecified"
               or scope == {"frequency_range_hz": None, "sample_indices": None} or indices == []
               or row["form"] == "expanded" and row["coverage_factor"] is None
               or row["correlation"]["state"] == "unknown"
               or row["correlation"]["state"] == "documented" and row["correlation"]["reference"] is None)
    if missing:
        diagnostics.append(_issue("uncertainty." + row["id"], "incomplete_uncertainty", "불확도 크기/범위/정의 또는 근거가 미정입니다."))
    if row["form"] in ("standard", "combined_standard") and row["coverage_factor"] is not None:
        diagnostics.append(_issue("uncertainty." + row["id"], "coverage_not_applied", "표준 불확도의 제출 k를 임의 적용하지 않습니다."))
    if dataset is not None and scope["frequency_range_hz"] is not None:
        lo, hi = scope["frequency_range_hz"]
        if not any(lo <= f <= hi for f in dataset["frequency_hz"]):
            diagnostics.append(_issue("uncertainty." + row["id"], "outside_dataset", "불확도 범위 안에 실제 자료 표본이 없습니다."))
        if indices is not None and any(not lo <= dataset["frequency_hz"][i] <= hi for i in indices):
            fail("명시 표본 순번과 불확도 주파수 범위가 서로 다릅니다.", "uncertainty.scope", "E_CONFLICT")
    bounded(row, "uncertainty")
    return diagnostics


def validate_record(record, dataset=None, project_id=None):
    """! @brief 원문을 보정하지 않고 형식/포트/anchor와 불완전한 제출 근거를 구분한다."""
    _fields(record, RECORD_FIELDS, "measurement")
    if record["schema"] != RECORD_SCHEMA:
        fail("지원하지 않는 측정 기록 버전입니다.", "measurement.schema", "E_VERSION")
    _uuid(record["id"], "measurement.id")
    text(record["name"], "measurement.name", limit=256)
    text(record["reason"], "measurement.reason")
    text(record["author"], "measurement.author", nullable=True)
    if record["data_class"] not in ("measurement", "synthetic_fixture", "unknown"):
        fail("원문 자료 분류가 다릅니다.", "measurement.data_class")
    if record["previous_record_id"] is not None:
        _uuid(record["previous_record_id"], "measurement.previous_record_id")
        if record["previous_record_id"] == record["id"]:
            fail("측정 기록이 자신의 과거 기록일 수 없습니다.", "measurement.previous_record_id", "E_CONFLICT")
    _date(record["created_at_utc"], "measurement.created_at_utc", utc=True)
    validate_anchor(record["data_anchor"], project_id)
    if dataset is not None:
        validate_dataset(dataset)
        anchor = record["data_anchor"]
        expected = anchor["dataset"]["sha256"] if anchor["kind"] == "network_artifact" else anchor["pin"]["dataset_sha256"]
        actual = hashlib.sha256(canonical_bytes(dataset)).hexdigest() if anchor["kind"] == "network_artifact" else canonical_hash(dataset)
        if actual != expected:
            fail("측정 기록과 원본 자료의 hash가 다릅니다.", "measurement.data_anchor", "E_HASH")
        if anchor["kind"] == "network_artifact" and anchor["dataset"]["bytes"] != len(canonical_bytes(dataset)):
            fail("측정 원본 바이트 수가 다릅니다.", "measurement.data_anchor", "E_HASH")
    _refs(record["source_refs"], "measurement.source_refs")
    diagnostics = []
    for section, fields in SECTIONS.items():
        group = record[section]
        if group is None:
            continue
        _fields(group, set(fields) | {"source_refs"}, section)
        _refs(group["source_refs"], section + ".source_refs")
        for key, kind in fields.items():
            _leaf(group[key], kind, section + "." + key, dataset, diagnostics)
    seen = set()
    for row in _list(record["uncertainty"], "uncertainty"):
        diagnostics.extend(validate_uncertainty(row, dataset))
        if row["id"] in seen:
            fail("불확도 항목 ID가 중복됩니다.", "uncertainty.id", "E_CONFLICT")
        seen.add(row["id"])
    processing_fields = {"name", "tool", "version", "input_anchor", "output_anchor", "order", "reference_plane_before",
                         "reference_plane_after", "uncertainty_notes", "source_refs"}
    for index, row in enumerate(_list(record["external_processing"], "external_processing")):
        _fields(row, processing_fields, "external_processing")
        for key in ("name", "tool", "version", "reference_plane_before", "reference_plane_after", "uncertainty_notes"):
            text(row[key], "external_processing." + key, nullable=key != "name")
        if type(row["order"]) is not int or row["order"] != index:
            fail("외부 보정 순서는 목록의 명시 0 기반 순번입니다.", "external_processing.order")
        for key in ("input_anchor", "output_anchor"):
            if row[key] is not None:
                validate_anchor(row[key], project_id)
        _refs(row["source_refs"], "external_processing.source_refs")
    attachment_ids = set()
    for item in _list(record["attachments"], "attachments"):
        _fields(item, {"id", "name", "role", "media_type", "artifact"}, "attachments")
        _uuid(item["id"], "attachments.id")
        if item["id"] in attachment_ids:
            fail("첨부 원문 ID가 중복됩니다.", "attachments.id", "E_CONFLICT")
        attachment_ids.add(item["id"])
        text(item["name"], "attachments.name", limit=256)
        text(item["media_type"], "attachments.media_type", limit=128)
        if item["role"] not in ("calibration", "specimen", "environment", "processing", "other"):
            fail("첨부 원문의 역할이 다릅니다.", "attachments.role")
        artifact(item["artifact"], "attachments.artifact")
    if type(record["extra"]) is not dict:
        fail("추가 원문 metadata는 object입니다.", "extra")
    bounded(record["extra"], "extra", 16 * 1024)
    bounded(record, "measurement")
    return diagnostics


def condition_assessment(record, dataset, *, comparison_record=None):
    """! @brief 교정 범위/미정 문맥을 보고하되 실제 측정 수용을 만들어내지 않는다."""
    diagnostics = validate_record(record, dataset)
    for section, key in (("specimen", "identifier"), ("acquisition", "instrument"), ("acquisition", "measured_at"),
                         ("calibration", "method"), ("calibration", "port_ids"), ("calibration", "frequency_range_hz"),
                         ("calibration", "reference_planes"), ("fixture", "mounting_notes")):
        if _value(record, section, key) in (None, []):
            diagnostics.append(_issue(section + "." + key, "missing_context", "시료/취득/교정/장착 근거가 미정입니다."))
    ports = _value(record, "calibration", "port_ids")
    if ports is not None and set(ports) != set(dataset["port_ids"]):
        diagnostics.append(_issue("calibration.port_ids", "uncovered_ports", "일부 자료 포트의 교정 근거가 없습니다."))
    band = _value(record, "calibration", "frequency_range_hz")
    if band is not None and any(not band[0] <= f <= band[1] for f in dataset["frequency_hz"]):
        diagnostics.append(_issue("calibration.frequency_range_hz", "outside_calibration", "교정 범위 밖의 자료 표본이 있습니다."))
    planes = _value(record, "calibration", "reference_planes")
    if planes is not None:
        for item in planes:
            actual = dataset["reference_planes"][dataset["port_ids"].index(item["port_id"])]
            if actual is None or item["reference_plane"] is None:
                diagnostics.append(_issue("calibration.reference_planes", "plane_unknown", "자료 또는 교정 기준면이 미정입니다."))
            elif actual != item["reference_plane"]:
                diagnostics.append(_issue("calibration.reference_planes", "plane_mismatch", "자료와 교정 기준면이 다릅니다."))
            if ports is not None and item["port_id"] not in ports:
                diagnostics.append(_issue("calibration.reference_planes", "uncovered_ports", "기준면의 포트가 명시 교정 포트 목록에 없습니다."))
        if {item["port_id"] for item in planes} != set(dataset["port_ids"]):
            diagnostics.append(_issue("calibration.reference_planes", "uncovered_planes", "일부 포트의 교정 기준면이 미정입니다."))
    if not record["uncertainty"]:
        diagnostics.append(_issue("uncertainty", "missing_uncertainty", "불확도 근거가 미정입니다."))
    differences = []
    if comparison_record is not None:
        validate_record(comparison_record)
        for section, fields in SECTIONS.items():
            for field in fields:
                left, right = _value(record, section, field), _value(comparison_record, section, field)
                left_leaf = record[section][field] if record[section] is not None else None
                right_leaf = comparison_record[section][field] if comparison_record[section] is not None else None
                if left_leaf != right_leaf or left is None or right is None:
                    differences.append({"field_path": section + "." + field, "left": deepcopy(left), "right": deepcopy(right),
                                        "left_evidence": deepcopy(left_leaf), "right_evidence": deepcopy(right_leaf),
                                        "state": "unknown" if left is None or right is None else "different"})
    incompatible = {"outside_calibration", "uncovered_ports", "plane_mismatch"}
    status = "incompatible_scope" if any(item["code"] in incompatible for item in diagnostics) else "incomplete" if diagnostics else "recorded"
    return {"status": status, "diagnostics": diagnostics, "condition_differences": differences,
            "measurement_validated": False, "physical_acceptance": "not_established",
            "uncertainty_propagation": "not_performed", "external_processing_reproduced": False}


def apply_measurement_command(document, payload):
    """! @brief 파일/원문 자료를 다시 계산하지 않는 색인 교체와 정확한 역명령이다."""
    _fields(payload, {"expected_hash", "replacement"}, "command.payload")
    old = document["extensions"].get(KEY)
    if payload["expected_hash"] != canonical_hash(old):
        fail("검토한 측정 색인과 현재 원문이 다릅니다.", "expected_hash", "E_CONFLICT")
    replacement = payload["replacement"]
    if replacement is not None:
        validate_registry(replacement)
    if replacement == old:
        fail("측정 색인의 변경이 없습니다.", "replacement", "E_CONFLICT")
    if replacement is None:
        document["extensions"].pop(KEY, None)
    else:
        document["extensions"][KEY] = deepcopy(replacement)
    changed = sorted({row["id"] for value in (old, replacement) if value is not None
                      for key in ("records", "alignments", "comparisons") for row in value[key]})
    inverse = {"type": COMMAND, "payload": {"expected_hash": canonical_hash(replacement), "replacement": deepcopy(old)}}
    return changed, ["revision", "measurement", "exports"], inverse
