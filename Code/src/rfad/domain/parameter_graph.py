"""! @brief UUID 결합과 의존 그래프로 파생 매개변수를 안전하게 재계산한다."""

from copy import deepcopy
from uuid import UUID

from rfad.domain.errors import ProjectError
from rfad.domain.expressions import ENGINE_VERSION, RESERVED_NAMES, dependencies, evaluate_expression
from rfad.domain.units import Quantity


def _fail(code: str, message: str, parameter_id: str) -> None:
    """! @brief 문제가 있는 매개변수를 구조화된 진단에 포함한다."""
    raise ProjectError(code, message, details={"field_path": "parameters." + parameter_id + ".expression"})


def expression_record(text: str, bindings: dict) -> dict:
    """! @brief 표현식 원문과 명시적 UUID 결합으로 저장 레코드를 만든다."""
    names = dependencies(text)
    if type(bindings) is not dict or set(bindings) != names:
        _fail("E_SCHEMA", "표현식 변수와 bindings의 이름이 정확히 일치해야 합니다.", "input")
    for name, target in bindings.items():
        if type(name) is not str or not name.isidentifier() or name in RESERVED_NAMES:
            _fail("E_SCHEMA", "사용할 수 없는 표현식 변수 이름입니다.", "input")
        try:
            valid = type(target) is str and str(UUID(target)) == target
        except ValueError:
            valid = False
        if not valid:
            _fail("E_SCHEMA", "표현식 결합은 표준 UUID여야 합니다.", "input")
    return {"text": text, "bindings": deepcopy(bindings), "dependencies": sorted(set(bindings.values())), "engine_version": ENGINE_VERSION}


def evaluate_parameters(parameters: dict, *, update: bool = False) -> list[str]:
    """! @brief 순환과 누락 참조를 검사하고 위상 순서로 파생 값을 평가한다.

    @param parameters 검증된 매개변수 사전. update=True일 때만 값을 바꾼다.
    @param update False이면 저장된 파생 값이 재계산 결과와 같은지 확인한다.
    @return 재계산으로 값이나 출처 상태가 바뀐 매개변수 UUID 목록.
    @throws ProjectError 순환, 누락 참조, 단위 오류 또는 잘못된 저장 캐시.
    """
    if len(parameters) > 128:
        _fail("E_RESOURCE", "표현식 그래프는 최대 128개 매개변수를 지원합니다.", "input")
    records = {}
    for parameter_id, parameter in parameters.items():
        if "expression" not in parameter:
            continue
        record = parameter["expression"]
        fields = {"text", "bindings", "dependencies", "engine_version"}
        if type(record) is not dict or set(record) != fields:
            _fail("E_SCHEMA", "표현식 저장 필드가 올바르지 않습니다.", parameter_id)
        if record["engine_version"] != ENGINE_VERSION:
            _fail("E_VERSION", "지원하지 않는 표현식 엔진 버전입니다.", parameter_id)
        expected = expression_record(record["text"], record["bindings"])
        if record != expected:
            _fail("E_SCHEMA", "표현식 의존성 기록이 원문과 일치하지 않습니다.", parameter_id)
        if any(target not in parameters for target in record["dependencies"]):
            _fail("E_CONFLICT", "표현식이 참조하는 매개변수가 없습니다.", parameter_id)
        records[parameter_id] = record
    state = {}
    values = {}
    changed = []

    def visit(parameter_id: str) -> Quantity:
        """! @brief 계산 중 표시를 사용하여 순환을 차단하고 각 노드를 한 번 평가한다."""
        if state.get(parameter_id) == "visiting":
            _fail("E_EXPR_CYCLE", "매개변수 표현식에 순환 참조가 있습니다.", parameter_id)
        if parameter_id in values:
            return values[parameter_id]
        state[parameter_id] = "visiting"
        parameter = parameters[parameter_id]
        stored = Quantity(**parameter["quantity"])
        if parameter_id in records:
            record = records[parameter_id]
            variables = {name: visit(target) for name, target in record["bindings"].items()}
            value = evaluate_expression(record["text"], variables, expected_dimension=stored.dimension, display_unit=stored.display_unit)
            if value.to_dict() != parameter["quantity"]:
                if not update:
                    _fail("E_SCHEMA", "저장된 파생 값이 표현식 계산 결과와 다릅니다.", parameter_id)
                parameter["quantity"] = value.to_dict()
                changed.append(parameter_id)
        else:
            value = stored
        values[parameter_id] = value
        state[parameter_id] = "done"
        return value

    for parameter_id in sorted(parameters):
        visit(parameter_id)
    return changed


def restore_parameter_command(parameter: dict) -> dict:
    """! @brief 리터럴과 표현식의 종류를 보존하는 역명령을 생성한다."""
    if "expression" not in parameter:
        return {"type": "parameter.set", "payload": deepcopy(parameter)}
    record = parameter["expression"]
    return {"type": "parameter.set_expression", "payload": {
        "id": parameter["id"], "name": parameter["name"],
        "expression": record["text"], "bindings": deepcopy(record["bindings"]),
        "dimension": parameter["quantity"]["dimension"], "display_unit": parameter["quantity"]["display_unit"],
    }}
