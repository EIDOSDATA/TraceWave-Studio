"""! @brief 원본 보존과 유한 자원 계약을 가진 결정적 설계 후보 조합을 생성한다."""

from copy import deepcopy
from fractions import Fraction
import math
from uuid import UUID, uuid5

from rfad.application.canonical import CanonicalEncodingError, canonical_bytes, canonical_hash
from rfad.domain.check_report import blocking_diagnostics
from rfad.domain.design import _fields, _strings, _text, _uuid
from rfad.domain.design_checks import check_design
from rfad.domain.errors import ProjectError
from rfad.domain.network_circuit import DIMENSIONS, validate_circuit
from rfad.domain.parameter_graph import evaluate_parameters
from rfad.domain.project import validate_project
from rfad.domain.sweep_inputs import fail, input_quantity, normalize_budget, normalize_settings, numerical_field, set_setting
from rfad.domain.units import Quantity, units_for_dimension


SCHEMA = "rfad.design-sweep-spec/0.1"
MAX_CANDIDATES = 128
MAX_VARIABLES = 8
MAX_SPEC_BYTES = 128 * 1024
_FIELDS = {"schema", "type", "name", "combination", "variables", "rows", "settings", "network",
           "target_ids", "target_contexts", "budget", "source_refs"}
_KINDS = {"grid_sweep": {"parameter"}, "numerical_study": {"solver_setting"},
          "circuit_sweep": {"circuit_value", "circuit_state"}}
_STATES = ("connected", "open", "short", "dnp")


def _bounded_json(value, field):
    """! @brief 깊이/순환/비유한 입력과 정의 사본 크기를 영구 저장 전에 제한한다."""
    try:
        size = len(canonical_bytes(value))
    except (CanonicalEncodingError, RecursionError, OverflowError) as error:
        fail("유한 JSON 정의가 필요합니다: " + str(error), field)
    if size > MAX_SPEC_BYTES:
        fail("스윕 정의의 128 KiB 상한을 초과했습니다.", field, "E_RESOURCE")


def context_variables(document):
    """! @brief 표현식은 읽기 전용으로 표시하고 원본 Quantity와 지원 단위를 제공한다."""
    validate_project(document)
    return [{"kind": "parameter", "id": identity, "name": parameter["name"],
             "dimension": parameter["quantity"]["dimension"], "quantity": deepcopy(parameter["quantity"]),
             "read_only": "expression" in parameter,
             "reason": "표현식 매개변수는 종속 입력을 변경하십시오." if "expression" in parameter else "",
             "units": list(units_for_dimension(parameter["quantity"]["dimension"]))}
            for identity, parameter in sorted(document["parameters"].items())]


def _dimension(variable, document, circuit, field):
    """! @brief 존재하는 리터럴/수치 설정/회로 소자만 축으로 연결한다."""
    kind, identity = variable["kind"], variable["id"]
    if kind == "solver_setting":
        return numerical_field(identity)["dimension"]
    _uuid(identity, field + ".id")
    if kind == "parameter":
        parameter = document["parameters"].get(identity)
        if parameter is None:
            fail("축 매개변수가 기준 원본에 없습니다.", field + ".id", "E_CONFLICT")
        if "expression" in parameter:
            fail("표현식 매개변수는 직접 스윕할 수 없습니다.", field + ".id", "E_CONFLICT")
        return parameter["quantity"]["dimension"]
    if circuit is None:
        fail("봉인된 기준 회로가 필요합니다.", "network.circuit_id", "E_CONFLICT")
    element = next((item for item in circuit["elements"] if item["id"] == identity), None)
    if element is None:
        fail("축 소자가 기준 회로에 없습니다.", field + ".id", "E_CONFLICT")
    return "state" if kind == "circuit_state" else DIMENSIONS[element["kind"]]


def _range(value, dimension, field):
    """! @brief 두 명시 끝점과 유한 개수로 범위를 펼치며 중복 수치를 제거하지 않는다."""
    _fields(value, {"start", "stop", "count"}, field)
    count = value["count"]
    if type(count) is not int or not 2 <= count <= MAX_CANDIDATES:
        fail("범위 표본 수는 2~128의 정수여야 합니다.", field + ".count", "E_RESOURCE")
    first = input_quantity(value["start"], dimension, field + ".start")
    last = input_quantity(value["stop"], dimension, field + ".stop")
    a, b = first["value_si"], last["value_si"]
    if a is None or b is None:
        fail("범위 양끝에는 명시한 유한 수량이 필요합니다.", field, "E_CONFLICT")
    sources = list(dict.fromkeys([*first["source_refs"], *last["source_refs"]]))
    if count > 2:
        _strings(sources, field + ".source_refs")
    state = "estimated" if "estimated" in (first["status"], last["status"]) else "user_entered"
    values = [first]
    for index in range(1, count - 1):
        fraction = Fraction(index, count - 1)
        exact = Fraction.from_float(a) * (1 - fraction) + Fraction.from_float(b) * fraction
        numeric = float(exact)
        if not math.isfinite(numeric) or (exact != 0 and numeric == 0):
            fail("범위의 중간 수치를 유한하게 표현할 수 없습니다.", field, "E_RESOURCE")
        values.append(Quantity(numeric, dimension, first["display_unit"], state, sources).to_dict())
    return [*values, last]


def _variables(raw, kind, document, circuit):
    """! @brief 원문 축 순서와 값 중복을 보존하면서 종류/차원/개수를 검증한다."""
    if type(raw) is not list or not 1 <= len(raw) <= MAX_VARIABLES:
        fail("스윕 축은 1~8개여야 합니다.", "variables", "E_RESOURCE")
    result, identities = [], set()
    for index, variable in enumerate(raw):
        field = f"variables.{index}"
        base = {"kind", "id", "dimension"}
        if type(variable) is not dict or set(variable) not in (base | {"values"}, base | {"range"}):
            fail("축에는 값 목록 또는 범위 중 하나만 필요합니다.", field)
        if type(variable["kind"]) is not str or variable["kind"] not in _KINDS[kind]:
            fail("연구 종류에 맞지 않는 축을 섞을 수 없습니다.", field + ".kind", "E_UNSUPPORTED")
        dimension = _dimension(variable, document, circuit, field)
        if variable["dimension"] != dimension:
            fail("축과 원본 필드의 차원이 다릅니다.", field + ".dimension", "E_UNIT")
        identity = (variable["kind"], variable["id"])
        if identity in identities:
            fail("같은 종류와 ID의 축을 중복 지정할 수 없습니다.", field + ".id", "E_CONFLICT")
        identities.add(identity)
        if "range" in variable:
            if dimension == "state":
                fail("회로 상태는 명시한 목록으로 지정하십시오.", field + ".range", "E_UNSUPPORTED")
            values = _range(variable["range"], dimension, field + ".range")
        else:
            values = variable["values"]
            if type(values) is not list or not 1 <= len(values) <= MAX_CANDIDATES:
                fail("축의 값 목록은 1~128개여야 합니다.", field + ".values", "E_RESOURCE")
            if dimension == "state":
                if any(type(value) is not str or value not in _STATES for value in values):
                    fail("연결/open/short/dnp 중 명시한 상태가 필요합니다.", field + ".values", "E_UNSUPPORTED")
                values = deepcopy(values)
            else:
                values = [input_quantity(value, dimension, f"{field}.values.{position}")
                          for position, value in enumerate(values)]
        result.append({"kind": variable["kind"], "id": variable["id"], "dimension": dimension, "values": values})
    return result


def _budget(budget):
    """! @brief 후보/해석 횟수와 시간/RAM/디스크를 유한한 명시 예산으로 제한한다."""
    _fields(budget, {"max_candidates", "max_native_solves", "wall_seconds", "ram_bytes", "disk_bytes", "concurrency"}, "budget")
    for key, low, high in (("max_candidates", 1, MAX_CANDIDATES), ("max_native_solves", 0, MAX_CANDIDATES),
                           ("ram_bytes", 1, 2**53 - 1), ("disk_bytes", 1, 2**53 - 1)):
        if type(budget[key]) is not int or not low <= budget[key] <= high:
            fail("자원 예산의 정수 범위를 벗어났습니다.", "budget." + key, "E_RESOURCE")
    wall = budget["wall_seconds"]
    if type(wall) not in (int, float) or not math.isfinite(wall) or not 0 < wall <= 604800:
        fail("전체 실행 시간 예산은 0초 초과, 7일 이하여야 합니다.", "budget.wall_seconds", "E_RESOURCE")
    if type(budget["concurrency"]) is not int or budget["concurrency"] != 1:
        fail("현재 연구는 동시 실행 1개만 지원합니다.", "budget.concurrency", "E_UNSUPPORTED")


def _targets(specification, document):
    """! @brief 선택 목표와 명시 대응만 보존하며 기준면/포트를 자동으로 채우지 않는다."""
    identities = specification["target_ids"]
    known = {target["id"]: target for target in document["targets"]}
    if type(identities) is not list or len(identities) > 32:
        fail("목표 목록은 최대 32개여야 합니다.", "target_ids", "E_RESOURCE")
    for identity in identities:
        _uuid(identity, "target_ids")
    if len(set(identities)) != len(identities) or not set(identities) <= set(known):
        fail("선택 목표가 없거나 중복됩니다.", "target_ids", "E_CONFLICT")
    contexts, seen = specification["target_contexts"], set()
    if type(contexts) is not list or len(contexts) > len(identities):
        fail("명시 목표 대응의 개수가 다릅니다.", "target_contexts")
    for index, item in enumerate(contexts):
        field = f"target_contexts.{index}"
        _fields(item, {"target_id", "context"}, field)
        identity = _uuid(item["target_id"], field + ".target_id")
        if identity not in identities or identity in seen:
            fail("대응 목표가 선택되지 않았거나 중복됩니다.", field, "E_CONFLICT")
        seen.add(identity)
        context = item["context"]
        _fields(context, {"port_id", "target_port_id", "reference_plane", "frequency_policy"}, field + ".context")
        _uuid(context["port_id"], field + ".context.port_id")
        if context["target_port_id"] is not None:
            _uuid(context["target_port_id"], field + ".context.target_port_id")
        if context["target_port_id"] != known[identity]["port_id"]:
            fail("평가 대응의 목표 포트가 선택 목표의 포트와 다릅니다.", field + ".context.target_port_id", "E_CONFLICT")
        if context["reference_plane"] is not None:
            _text(context["reference_plane"], field + ".context.reference_plane")
        if context["frequency_policy"] != "exact_only":
            fail("평가에는 정확한 표본 일치만 지원합니다.", field + ".context.frequency_policy", "E_UNSUPPORTED")


def candidate_count(specification):
    """! @brief 후보를 생성하지 않고 조합의 개수를 검증하여 반환한다."""
    variables = specification["variables"]
    sizes = [len(variable["values"]) for variable in variables]
    combination = specification["combination"]
    if combination == "cartesian":
        count = math.prod(sizes)
    elif combination == "paired":
        if len(set(sizes)) != 1:
            fail("짝지은 축은 값의 개수가 같아야 하며 자동 확장은 하지 않습니다.", "variables", "E_CONFLICT")
        count = sizes[0]
    elif combination == "explicit_rows":
        rows = specification["rows"]
        if type(rows) is not list or not 1 <= len(rows) <= MAX_CANDIDATES:
            fail("명시 후보 행은 1~128개여야 합니다.", "rows", "E_RESOURCE")
        for index, row in enumerate(rows):
            if (type(row) is not list or len(row) != len(sizes)
                    or any(type(value) is not int or not 0 <= value < size for value, size in zip(row, sizes))):
                fail("후보 행에는 각 축의 0기반 값 인덱스가 필요합니다.", f"rows.{index}")
        count = len(rows)
    else:
        fail("지원하는 유한 후보 조합이 아닙니다.", "combination", "E_UNSUPPORTED")
    if combination != "explicit_rows" and specification["rows"] != []:
        fail("명시 행은 explicit_rows 조합에서만 사용합니다.", "rows")
    if not 1 <= count <= min(MAX_CANDIDATES, specification["budget"]["max_candidates"]):
        fail("조합 수가 명시 후보 예산 또는 최대 128개를 초과했습니다.", "budget.max_candidates", "E_RESOURCE")
    return count


def validate_specification(specification, document, circuit=None):
    """! @brief 원문을 바꾸지 않고 축 수량과 설정만 정규화한 고정 필드 사본을 반환한다."""
    _bounded_json(specification, "specification")
    validate_project(document)
    if type(specification) is not dict or not _FIELDS - {"rows", "target_contexts"} <= set(specification) or set(specification) - _FIELDS - {"settings_inputs", "budget_inputs"}:
        fail("설계 스윕 정의의 필드가 다릅니다.")
    if specification["schema"] != SCHEMA:
        fail("지원하지 않는 설계 스윕 정의입니다.", "schema", "E_VERSION")
    if type(specification["type"]) is not str or specification["type"] not in _KINDS:
        fail("지원하지 않는 연구 종류입니다.", "type", "E_UNSUPPORTED")
    _text(specification["name"], "name", limit=256)
    _strings(specification["source_refs"], "source_refs")
    result = deepcopy(specification)
    result.setdefault("rows", [])
    result.setdefault("target_contexts", [])
    network = result["network"]
    if result["type"] == "circuit_sweep":
        _fields(network, {"dataset_id", "circuit_id"}, "network")
        for key in network:
            _uuid(network[key], "network." + key)
        if circuit is None:
            fail("봉인된 기준 회로가 필요합니다.", "network.circuit_id", "E_CONFLICT")
        validate_circuit(circuit)
        if result["settings"] is not None or result.get("settings_inputs"):
            fail("외부 회로 스윕은 EM 설정을 함께 변경하지 않습니다.", "settings", "E_UNSUPPORTED")
    elif network is not None or circuit is not None:
        fail("EM 설계/수치 연구에는 외부 회로를 섞을 수 없습니다.", "network", "E_UNSUPPORTED")
    result["variables"] = _variables(result["variables"], result["type"], document, circuit)
    result["settings"] = normalize_settings(result["settings"], result.pop("settings_inputs", None))
    result["budget"] = normalize_budget(result["budget"], result.pop("budget_inputs", None))
    _budget(result["budget"])
    _targets(result, document)
    candidate_count(result)
    _bounded_json(result, "normalized_specification")
    return result


def _indices(specification, ordinal):
    """! @brief Cartesian 마지막 축부터 증가시키며 명시 행 및 중복 ordinal을 유지한다."""
    count = candidate_count(specification)
    if type(ordinal) is not int or not 0 <= ordinal < count:
        fail("후보 순번이 연구 범위를 벗어났습니다.", "ordinal", "E_CONFLICT")
    if specification["combination"] == "explicit_rows":
        return list(specification["rows"][ordinal])
    if specification["combination"] == "paired":
        return [ordinal] * len(specification["variables"])
    remaining, indices = ordinal, []
    for variable in reversed(specification["variables"]):
        remaining, index = divmod(remaining, len(variable["values"]))
        indices.append(index)
    return list(reversed(indices))


def _physical(value, document):
    """! @brief SI 값과 의미 상태만 정규화하며 단위/출처/이름을 계산 재사용 키에서 제외한다."""
    if type(value) is dict:
        if set(value) == {"parameter_id"}:
            return _physical(document["parameters"][value["parameter_id"]]["quantity"], document)
        if set(value) == {"value_si", "dimension", "display_unit", "status", "source_refs"}:
            return {"dimension": value["dimension"], "value_si": value["value_si"],
                    "state": value["status"] if value["value_si"] is None else "numeric"}
        return {key: _physical(item, document) for key, item in value.items()
                if key not in ("name", "source_ref", "source_refs", "assumptions")}
    if type(value) is list:
        return [_physical(item, document) for item in value]
    return value


def _evaluation_key(document, settings, circuit, specification):
    """! @brief 계산에 필요한 전체 물리 입력을 보존하고 표시/출처 차이만 재사용에서 제외한다."""
    ignored_extensions = {"rfad.network-library", "rfad.precision-origin", "rfad.template-origin", "rfad.pcb-selection", "rfad.sweep-selection"}
    fields = ("schema_version", "frames", "board", "materials", "stackup", "nets", "geometry", "ports", "environment")
    model = {key: _physical(document[key], document) for key in fields}
    model["extensions"] = {key: _physical(value, document) for key, value in document["extensions"].items()
                           if key not in ignored_extensions}
    return canonical_hash({"profile": "rfad.sweep-evaluation/0.1", "model": model,
                           "settings": _numeric_key(settings), "circuit": _physical(circuit, document),
                           "network": specification["network"]})


def _numeric_key(value):
    """! @brief 유효한 solver 숫자의 int/float 표현 차이를 물리 키에서 제거한다."""
    if type(value) in (int, float):
        return float(value)
    if type(value) is dict:
        return {key: _numeric_key(item) for key, item in value.items()}
    if type(value) is list:
        return [_numeric_key(item) for item in value]
    return value


def candidate_at(document, normalized_spec, ordinal, circuit=None):
    """! @brief 기준 사본에 축 값을 일괄 적용하며 실패 후보도 순서와 진단을 반환한다."""
    specification = validate_specification(normalized_spec, document, circuit)
    indices = _indices(specification, ordinal)
    result_document, settings, result_circuit = deepcopy(document), deepcopy(specification["settings"]), deepcopy(circuit)
    values = [{"kind": variable["kind"], "id": variable["id"], "index": index, "value": deepcopy(variable["values"][index])}
              for variable, index in zip(specification["variables"], indices)]
    identity = canonical_hash({"base_hash": canonical_hash(document), "specification_hash": canonical_hash(specification), "ordinal": ordinal})
    result_document["revision_id"] = str(uuid5(UUID(document["project_id"]), "sweep:" + identity))
    result_document["parent_revision_ids"] = [document["revision_id"]]
    result = {"ordinal": ordinal, "indices": indices, "values": values, "status": "valid", "diagnostics": [],
              "document": result_document, "settings": settings, "circuit": result_circuit, "evaluation_key": None}
    try:
        for variable in values:
            kind, identity, value = (variable[key] for key in ("kind", "id", "value"))
            if kind == "parameter":
                result_document["parameters"][identity]["quantity"] = deepcopy(value)
            elif kind == "solver_setting":
                set_setting(settings, identity, value)
            else:
                element = next(item for item in result_circuit["elements"] if item["id"] == identity)
                element["state" if kind == "circuit_state" else "value"] = deepcopy(value)
        # @brief 모든 축을 넣은 다음 파생값을 한 번 갱신하고 검증에서 저장 캐시 일치를 재확인한다.
        evaluate_parameters(result_document["parameters"], update=True)
        validate_project(result_document)
        if result_circuit is not None:
            validate_circuit(result_circuit)
            result["evaluation_key"] = _evaluation_key(result_document, settings, result_circuit, specification)
            return result
        else:
            if settings is None:
                fail("EM 실행을 위한 명시 설정이 미정입니다.", "settings", "E_UNSUPPORTED")
            from rfad.application.pcb_solver import validate_settings

            validate_settings(settings)
        report = check_design(result_document, inclusion="em", target_ids=specification["target_ids"])
        blocking = blocking_diagnostics(report)
        result["diagnostics"] = [*blocking, *[{"code": "W_NOT_EVALUATED", "severity": "warning", "message_ko": row["message"],
                                               "entity_ids": row["object_ids"], "field_paths": row["field_paths"],
                                               "details": row, "suggested_actions": [], "recoverable": True}
                                              for row in report["issues"] if row["status"] == "not_evaluated"]]
        if blocking:
            result["status"] = "invalid"
        else:
            result["evaluation_key"] = _evaluation_key(result_document, settings, result_circuit, specification)
    except ProjectError as error:
        result["status"] = "unsupported" if error.code in ("E_UNSUPPORTED", "E_VERSION") else "invalid"
        result["diagnostics"].append(error.diagnostic())
    return result
