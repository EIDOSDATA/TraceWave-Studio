"""! @brief 프로젝트에 독립 외부 결과를 등록하고 부분 읽기를 제공한다."""

from copy import deepcopy
import json
import stat
from uuid import uuid4

from rfad.adapters import field_hdf5, large_result_hdf5 as hdf
from rfad.application import result_fields
from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import MAX_JOBS, _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.storage import large_result_package as package
from rfad.storage.indexed_result_file import index_file


PROFILE = "rfad.large-result-library/0.1"
REGISTER = "result.large.register"
TRANSFER = "result.large.transfer"
MUTATIONS = {REGISTER, TRANSFER}
READS = {"result.large.list", "result.large.runtime", "result.large.field", "result.large.slice", "result.large.curves"}
LIMITS = {"field": hdf.MAX_FIELD_BYTES, "traces": hdf.MAX_TRACE_BYTES}
PACKAGE_LIMIT = hdf.MAX_FIELD_BYTES + package.MAX_OVERHEAD
MAX_RECORDS = 16
MAX_PROJECT_BYTES = 8 * 1024**3
WARNINGS = ["외부 결과 원문입니다. 설계/해석 실행, 제작·측정 및 독립 물리 검증이 확립되지 않았습니다.",
            "기록한 격자 좌표와 복소값을 표시합니다. Yee 성분 위치나 절대 단위를 추정하지 않습니다."]


def validate(method, context, data):
    """! @brief 임의 경로 대신 소유 프로젝트와 생성한 수신 토큰만 받는다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    if method == TRANSFER:
        _fields(data, {"id"})
        _uuid(data["id"])
        return
    _fields(data, {"revision_id", "token", "kind", "name", "source_name"})
    _uuid(data["revision_id"])
    _uuid(data["token"])
    if data["kind"] not in ("field", "traces", "package"):
        raise ProjectError("E_SCHEMA", "필드, 복소 곡선 또는 결과 이관 파일을 선택하십시오.")
    if any(type(data[key]) is not str or not data[key].strip() or len(data[key].encode("utf-8")) > 512
           for key in ("name", "source_name")):
        raise ProjectError("E_SCHEMA", "결과 이름과 원본 파일명이 필요합니다.")


def _job(service, state, method, context, project, data):
    """! @brief 원문 스트리밍을 같은 프로젝트의 유한 비동기 작업으로 접수한다."""
    if len(state["jobs"]) >= MAX_JOBS:
        raise ProjectError("E_RESOURCE", "작업 목록이 가득 찼습니다.")
    if any(job.get("operation_method") in MUTATIONS and job.get("context") == context
           and job["state"] in ("queued", "running") for job in state["jobs"].values()):
        raise ProjectError("E_CONFLICT", "이 프로젝트에 등록 또는 이관 중인 대용량 결과가 있습니다.")
    job_id = str(uuid4())
    job = {"job_id": job_id, "run_id": str(uuid4()), "kind": "data_processing", "operation_method": method,
           "context": deepcopy(context), "input": deepcopy(data), "project_path": project["path"], "events": []}
    service._event(job, "queued")
    state["jobs"][job_id] = job
    return {"job_id": job_id, "state": "queued", "events_cursor": 1}


def _owned(state, context, identity):
    """! @brief 현재 프로젝트가 소유한 공개 결과만 찾는다."""
    records = state.get("large_results", {}).get(context["project_id"], {})
    record = next((row for row in records.values() if row["id"] == identity), None)
    if record is None:
        raise ProjectError("E_MISSING_ARTIFACT", "이 프로젝트에 등록된 대용량 결과가 없습니다.")
    return record


def admit(service, state, method, context, data):
    """! @brief 현재 개정의 등록 또는 소유해 공개한 원문의 이관을 접수한다."""
    project = service._project(state, context)
    if method == TRANSFER:
        return _job(service, state, method, context, project, _owned(state, context, data["id"]))
    if service._load(project)["revision_id"] != data["revision_id"]:
        raise ProjectError("E_CONFLICT", "등록하기 전에 프로젝트 개정이 바뀌었습니다.")
    project_id = context["project_id"]
    records = state.setdefault("large_results", {}).get(project_id, {})
    if data["token"] in records:
        raise ProjectError("E_CONFLICT", "이미 등록한 수신 토큰입니다.")
    if len(records) >= MAX_RECORDS:
        raise ProjectError("E_RESOURCE", "대용량 결과 목록이 가득 찼습니다.")
    path = service.journal._safe_path(project["path"] + "/result-inbox/" + data["token"] + ".h5")
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ProjectError("E_MISSING_ARTIFACT", "수신한 대용량 결과 원문이 없습니다.") from error
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProjectError("E_HASH", "대용량 결과 원문이 독립 일반 파일이 아닙니다.")
    remaining = MAX_PROJECT_BYTES - sum(row["artifact"]["bytes"] for row in records.values())
    limit = LIMITS.get(data["kind"], PACKAGE_LIMIT)
    if not 8 <= info.st_size <= limit or data["kind"] != "package" and info.st_size > remaining:
        raise ProjectError("E_RESOURCE", "대용량 결과의 파일 또는 프로젝트 용량 상한을 초과했습니다.")
    return _job(service, state, method, context, project, {**data, "bytes": info.st_size, "remaining": remaining})


def prepare(service, job):
    """! @brief 큰 파일 처리 중 저널 잠금을 점유하지 않고 원문과 블록 해시를 검증한다."""
    data = job["input"]
    base = job["project_path"]
    if job["operation_method"] == TRANSFER:
        return _transfer(service, job)
    incoming = service.journal._safe_path(base + "/result-inbox/" + data["token"] + ".h5")
    target = base + "/large-results/" + job["job_id"]
    extracted = incoming.with_name(job["job_id"] + ".extracted.partial")
    origin = None
    artifact = None
    try:
        if data["kind"] == "package":
            header, index = package.extract(incoming, extracted, data["bytes"], LIMITS)
            origin = header["origin"]
            data = {**data, **{key: header[key] for key in ("name", "kind", "source_name")}}
            source = extracted
            if index["bytes"] > data["remaining"]:
                raise ProjectError("E_RESOURCE", "복원한 원문이 프로젝트 결과 용량 상한을 초과했습니다.")
        else:
            index = index_file(incoming, data["bytes"])
            source = incoming
            if index["bytes"] != data["bytes"]:
                raise ProjectError("E_HASH", "접수한 원문의 크기가 달라졌습니다.")
        with hdf.opened(source, index) as (handle, h5py, np):
            if data["kind"] == "field":
                layout = hdf.field_layout(handle, h5py, np)
                hdf.field_data(handle, h5py, np, layout)
                details = {"frequency_hz": layout["frequency_hz"], "shape": layout["shape"]}
            else:
                declaration, arrays = hdf.traces(handle, h5py, np, verify_samples=True)
                details = {"curves": [{**entry, "count": len(curve[0])}
                                      for entry, curve in zip(declaration["curves"], arrays)],
                           "quantity": declaration["quantity"], "unit": declaration["unit"]}
        artifact = service.journal.seal_file(target + "/source.h5", source, expected_sha256=index["sha256"],
                                             expected_bytes=index["bytes"], limit=LIMITS[data["kind"]])
        seal = service.journal.put_immutable(target + "/index.json", canonical_bytes(index))
        return {key: data[key] for key in ("token", "kind", "name", "source_name", "revision_id")} | {
            "id": job["job_id"], "artifact": artifact, "seal": seal, "details": details, "origin": origin,
            "conditions": {"manufacturing": None, "measurement": None, "physics_validated": False}}
    except (ProjectError, OSError):
        if artifact is not None:
            service.journal._safe_path(artifact["uri"]).unlink(missing_ok=True)
        raise
    finally:
        incoming.unlink(missing_ok=True)
        extracted.unlink(missing_ok=True)


def _transfer(service, job):
    """! @brief 등록 원문과 출처를 검증해 결과당 한 이관 파일로 게시한다."""
    data = job["input"]
    base = job["project_path"] + "/large-results/" + data["id"]
    artifact = data["artifact"]
    if artifact["uri"] != base + "/source.h5":
        raise ProjectError("E_HASH", "이관할 원문 경로가 프로젝트 결과와 다릅니다.")
    source = service.journal._safe_path(artifact["uri"])
    relative = base + "/transfer.rfadres"
    destination = service.journal._safe_path(relative)
    temporary = destination.with_name(job["job_id"] + ".transfer.partial")
    header = {key: data[key] for key in ("kind", "name", "source_name")}
    header["origin"] = data.get("origin") or {"project_id": job["context"]["project_id"],
                                              "revision_id": data["revision_id"]}
    header["payload"] = {key: artifact[key] for key in ("bytes", "sha256")}
    service.journal._check_space(artifact["bytes"] + package.MAX_OVERHEAD)
    try:
        reference = package.write(source, temporary, header, LIMITS)
        temporary.replace(destination)
        service.journal._flush_directory(destination.parent)
        return {"kind": "transfer", "id": data["id"], "artifact": {**reference, "uri": relative}}
    finally:
        temporary.unlink(missing_ok=True)


def publish(state, job, record):
    """! @brief 완료 작업 이벤트와 함께 검증한 결과 참조를 공개한다."""
    if job["operation_method"] == TRANSFER:
        return record
    records = state.setdefault("large_results", {}).setdefault(job["context"]["project_id"], {})
    records[record["token"]] = record
    return _summary(record)


def discard(service, record):
    """! @brief 게시되지 않은 작업의 소유 파일만 회수한다."""
    if record["kind"] == "transfer":
        return
    for key in ("seal", "artifact"):
        try:
            service.journal._safe_path(record[key]["uri"]).unlink(missing_ok=True)
        except (OSError, ProjectError):
            # @brief 알려진 불변 경로의 잔여 사본은 다른 등록 파일에 영향을 주지 않는다.
            pass


def _summary(record):
    """! @brief 블록 해시와 내부 인덱스 경로는 표시 DTO에서 제외한다."""
    result = {key: record[key] for key in ("id", "kind", "name", "source_name", "revision_id",
                                          "artifact", "details", "conditions")}
    if record.get("origin") is not None:
        result["origin"] = record["origin"]
    return result


def _samples(axis, values, mask, indices, offset):
    """! @brief 원래 인덱스와 복소값 및 결측 상태를 표시 배열로 전달한다."""
    return [{"index": offset+index, "frequency_hz": float(axis[index]),
             "real": float(values[index, 0]) if mask[index] else None,
             "imag": float(values[index, 1]) if mask[index] else None,
             "valid": bool(mask[index])} for index in indices]


def _curve_pages(handle, h5py, np, data):
    """! @brief 개별 주파수 축을 유지하고 보간 없이 원본 표본 또는 구간 극값을 반환한다."""
    offset, mode, metric = data["offset"], data["mode"], data["metric"]
    if (type(offset) is not int or not 0 <= offset < hdf.MAX_SAMPLES or mode not in ("exact", "overview")
            or metric not in ("real", "imag") or mode == "overview" and offset != 0):
        raise ProjectError("E_SCHEMA", "복소 곡선의 조회 범위 또는 표시 항목이 올바르지 않습니다.")
    declaration, arrays = hdf.traces(handle, h5py, np)
    pages, counts = [], []
    for axis, ri, valid in arrays:
        count = len(axis)
        counts.append(count)
        if mode == "exact":
            section = slice(offset, offset + 101)
            stop = min(count, offset+101)
            samples = _samples(axis[section], ri[section], valid[section], range(max(0, stop-offset)), offset)
        else:
            samples = []
            width = (count + hdf.MAX_BUCKETS - 1) // hdf.MAX_BUCKETS
            for start in range(0, count, width):
                section = slice(start, start+width)
                values, flags = ri[section], valid[section]
                indices = np.flatnonzero(flags)
                if indices.size == 0:
                    continue
                column = values[indices, 0 if metric == "real" else 1]
                low, high = int(indices[np.argmin(column)]), int(indices[np.argmax(column)])
                samples.extend(_samples(axis[section], values, flags, sorted({low, high}), start))
        pages.append({"samples": samples, "parameter_kind": declaration["quantity"] or "unspecified"})
    return {"pages": pages, "counts": counts, "offset": offset, "mode": mode, "metric": metric,
            "next_offset": offset+101 if mode == "exact" and offset+101 < max(counts) else None}


def _field(handle, h5py, np, record, parameters=None):
    """! @brief 선언한 원문 좌표를 사용하여 기존 필드 View의 응답 형식을 제공한다."""
    layout = hdf.field_layout(handle, h5py, np)
    sources = hdf.field_data(handle, h5py, np, layout)
    coordinates = layout["primary_coordinates_mm"]
    prefix = {0: "E", 2: "J", 3: "rotH"}[layout["dump_type"]]
    reference = record["artifact"]
    response = {"profile": result_fields.PROFILE, "warnings": WARNINGS, "physics_validated": False}
    if parameters is None:
        response.update(status="available", monitors=[{"monitor_id": "external", "label": prefix + " (외부 원문)",
            "unit": "미정", "frequency_hz": layout["frequency_hz"], "source_ref": reference,
            "components": [{"component": axis, "label": prefix+axis, "shape": layout["shape"],
                            "coordinates_mm": coordinates} for axis in "xyz"]}])
        return response
    axes, selection, indices = result_fields._selection(layout, parameters, ("external",))
    frequency, slices = field_hdf5._hyperslab(selection, layout)
    return result_fields.present_page(response, layout, coordinates, sources[frequency][slices].T, reference,
                                      parameters, axes, indices, unit="미정", normalization=None,
                                      coordinate_basis="recorded_primary_coordinates")


def read(service, method, params):
    """! @brief 등록 소유권을 확인하고 실제 요청 블록만 반환한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "대용량 결과 API 버전이 다릅니다.")
    context, data = params["context"], params["input"]
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    state = service.journal.read()
    project = service._project(state, context)
    if method == "result.large.runtime":
        _fields(data, set())
        h5py, np = hdf._runtime()
        return {"profile": PROFILE, "h5py": h5py.__version__, "numpy": np.__version__}
    if method == "result.large.list":
        _fields(data, set())
        records = state.get("large_results", {}).get(context["project_id"], {})
        return result_fields._bounded({"profile": PROFILE, "records": [_summary(row) for row in records.values()]})
    extra = {"selection"} if method == "result.large.slice" else (
        {"offset", "mode", "metric"} if method == "result.large.curves" else set())
    _fields(data, {"id", *extra})
    identity = _uuid(data["id"])
    record = _owned(state, context, identity)
    base = project["path"] + "/large-results/" + identity
    artifact, seal = record["artifact"], record["seal"]
    if artifact["uri"] != base + "/source.h5" or seal["uri"] != base + "/index.json":
        raise ProjectError("E_HASH", "등록 파일이 프로젝트의 결과 저장 경로와 다릅니다.")
    index = json.loads(service.journal.read_artifact(seal))
    if any(index[key] != artifact[key] for key in ("bytes", "sha256")):
        raise ProjectError("E_HASH", "블록 인덱스와 원문 식별이 다릅니다.")
    path = service.journal._safe_path(artifact["uri"])
    with hdf.opened(path, index) as (handle, h5py, np):
        if method == "result.large.curves" and record["kind"] == "traces":
            result = _curve_pages(handle, h5py, np, data)
        elif method in ("result.large.field", "result.large.slice") and record["kind"] == "field":
            result = _field(handle, h5py, np, record, data.get("selection"))
        else:
            raise ProjectError("E_SCHEMA", "선택한 결과 유형에서 지원하지 않는 조회입니다.")
    return result_fields._bounded({"id": identity, **result})
