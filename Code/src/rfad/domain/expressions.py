"""! @brief 제한된 표현식 문법을 직접 파싱하고 물리 차원을 검사한다.

@details Python 코드 실행, 속성/인덱스 접근 및 임의 함수 호출은 제공하지 않는다.
입력 위치 span은 Unicode 문자 index이며 크기 제한은 UTF-8 byte 기준이다.
중간 계산은 분수 지수 차원을 허용하되 결과는 명시한 Quantity 차원이어야 한다.
"""

from dataclasses import dataclass
from fractions import Fraction
import keyword
import math
import re

from rfad.domain.errors import ProjectError
from rfad.domain.units import Dimension, Quantity, QuantityError, QuantityStatus

ENGINE_VERSION = "rfad.expression/0.1"
MAX_TEXT_BYTES = 4096
MAX_TOKENS = 512
MAX_DEPTH = 64
MAX_OPERATIONS = 2048
MAX_ARGUMENTS = 32
_FUNCTIONS = frozenset({"sqrt", "sin", "cos", "tan", "atan2", "abs", "min", "max", "clamp"})
_CONSTANTS = frozenset({"pi", "c0"})
_UNIT_NAMES = frozenset({"m", "mm", "um", "Hz", "kHz", "MHz", "GHz", "s", "ms", "us", "ns", "rad", "deg", "ohm", "S/m", "W", "mW"})
RESERVED_NAMES = frozenset(_FUNCTIONS | _CONSTANTS | _UNIT_NAMES | set(keyword.kwlist))
_NUMBER = re.compile(r"(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?")
_NAME = re.compile(r"[^\W\d]\w*", re.UNICODE)


def _dim(*values: int) -> tuple[Fraction, ...]:
    """! @brief 길이, 시간, 질량, 전류, 각도의 지수 벡터를 만든다."""
    return tuple(Fraction(value) for value in values)


_DIMENSIONS = {
    Dimension.LENGTH: _dim(1, 0, 0, 0, 0),
    Dimension.FREQUENCY: _dim(0, -1, 0, 0, 0),
    Dimension.TIME: _dim(0, 1, 0, 0, 0),
    Dimension.ANGLE: _dim(0, 0, 0, 0, 1),
    Dimension.IMPEDANCE: _dim(2, -3, 1, -2, 0),
    Dimension.CONDUCTIVITY: _dim(-3, 3, -1, 2, 0),
    Dimension.POWER: _dim(2, -3, 1, 0, 0),
    Dimension.DIMENSIONLESS: _dim(0, 0, 0, 0, 0),
}
_SCALAR = _DIMENSIONS[Dimension.DIMENSIONLESS]


def _fail(code: str, message: str, start: int = 0, end: int = 0) -> None:
    """! @brief 표현식 위치를 포함한 구조화된 오류를 반환한다."""
    raise ProjectError(code, message, details={"field_path": "expression", "span": {"start": start, "end": end}})


@dataclass(frozen=True, slots=True)
class _Token:
    """! @brief 원문 위치를 가진 제한 문법의 토큰이다."""

    kind: str
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Node:
    """! @brief 실행 가능한 Python 객체를 포함하지 않는 구문 노드다."""

    kind: str
    text: str
    children: tuple
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Value:
    """! @brief 유한 SI 값과 중간 물리 차원을 보관한다."""

    number: float
    dimension: tuple[Fraction, ...]


def _tokenize(text: str) -> list[_Token]:
    """! @brief 허용 문자와 길이 안에서만 토큰을 만든다."""
    if type(text) is not str:
        _fail("E_SCHEMA", "표현식은 문자열이어야 합니다.")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        _fail("E_SCHEMA", "표현식을 UTF-8로 표현할 수 없습니다.")
    if size > MAX_TEXT_BYTES:
        _fail("E_RESOURCE", "표현식은 UTF-8 4096 bytes 이내여야 합니다.")
    if not text.strip():
        _fail("E_SCHEMA", "표현식이 비어 있습니다.")
    tokens = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        start = position
        if text.startswith("S/m", position) and (position + 3 == len(text) or not (text[position + 3].isalnum() or text[position + 3] == "_")):
            position += 3
            tokens.append(_Token("name", "S/m", start, position))
        elif match := _NUMBER.match(text, position):
            position = match.end()
            tokens.append(_Token("number", match.group(), start, position))
        elif match := _NAME.match(text, position):
            position = match.end()
            tokens.append(_Token("name", match.group(), start, position))
        elif text.startswith("**", position):
            position += 2
            tokens.append(_Token("operator", "**", start, position))
        elif text[position] in "+-*/(),":
            position += 1
            tokens.append(_Token("operator", text[start:position], start, position))
        else:
            _fail("E_SCHEMA", "표현식 문법에서 허용하지 않는 문자입니다.", start, start + 1)
        if len(tokens) > MAX_TOKENS:
            _fail("E_RESOURCE", "표현식 토큰 수가 512개를 초과합니다.", start, position)
    tokens.append(_Token("eof", "", len(text), len(text)))
    return tokens


class _Parser:
    """! @brief 연산 우선순위와 함수 whitelist를 적용하는 재귀 하강 파서다."""

    def __init__(self, text: str):
        """! @brief 검증한 토큰만 파서에 전달한다."""
        self.tokens = _tokenize(text)
        self.index = 0
        self.node_count = 0

    def _node(self, kind, text, children, start, end):
        """! @brief 구문 노드 수를 제한한다."""
        self.node_count += 1
        if self.node_count > MAX_TOKENS:
            _fail("E_RESOURCE", "표현식 구문 노드 수가 512개를 초과합니다.", start, end)
        return _Node(kind, text, tuple(children), start, end)

    def _depth(self, depth):
        """! @brief 괄호/단항/거듭제곱의 중첩 깊이를 제한한다."""
        if depth > MAX_DEPTH:
            token = self.tokens[self.index]
            _fail("E_RESOURCE", "표현식 중첩 깊이가 64를 초과합니다.", token.start, token.end)

    def _take(self, text):
        """! @brief 다음 토큰이 일치할 때만 소비한다."""
        if self.tokens[self.index].text == text:
            self.index += 1
            return True
        return False

    def parse(self) -> _Node:
        """! @brief 표현식 전체와 평가 트리의 깊이를 검사한다."""
        result = self._sum(0)
        token = self.tokens[self.index]
        if token.kind != "eof":
            _fail("E_SCHEMA", "연산자 또는 표현식 끝이 필요합니다.", token.start, token.end)
        pending = [(result, 0)]
        while pending:
            node, depth = pending.pop()
            if depth > MAX_DEPTH:
                _fail("E_RESOURCE", "표현식 평가 트리의 깊이가 64를 초과합니다.", node.start, node.end)
            pending.extend((child, depth + 1) for child in node.children)
        return result

    def _sum(self, depth):
        """! @brief 덧셈과 뺄셈을 파싱한다."""
        left = self._product(depth)
        while self.tokens[self.index].text in ("+", "-"):
            operator = self.tokens[self.index].text
            self.index += 1
            right = self._product(depth)
            left = self._node("binary", operator, (left, right), left.start, right.end)
        return left

    def _product(self, depth):
        """! @brief 곱셈과 나눗셈을 파싱한다."""
        left = self._unary(depth)
        while self.tokens[self.index].text in ("*", "/"):
            operator = self.tokens[self.index].text
            self.index += 1
            right = self._unary(depth)
            left = self._node("binary", operator, (left, right), left.start, right.end)
        return left

    def _unary(self, depth):
        """! @brief 부호는 거듭제곱보다 낮은 우선순위로 적용한다."""
        self._depth(depth)
        token = self.tokens[self.index]
        if token.text in ("+", "-"):
            self.index += 1
            child = self._unary(depth + 1)
            return self._node("unary", token.text, (child,), token.start, child.end)
        return self._power(depth)

    def _power(self, depth):
        """! @brief 오른쪽 결합의 거듭제곱을 파싱한다."""
        left = self._primary(depth)
        if self._take("**"):
            right = self._unary(depth + 1)
            return self._node("binary", "**", (left, right), left.start, right.end)
        return left

    def _primary(self, depth):
        """! @brief 숫자/단위/변수/괄호/허용 함수만 소비한다."""
        self._depth(depth)
        token = self.tokens[self.index]
        if token.text == "(":
            self.index += 1
            result = self._sum(depth + 1)
            if not self._take(")"):
                _fail("E_SCHEMA", "닫는 괄호가 필요합니다.", token.start, token.end)
            return result
        if token.kind == "number":
            self.index += 1
            result = self._node("number", token.text, (), token.start, token.end)
            unit = self.tokens[self.index]
            if unit.kind == "name" and unit.text in _UNIT_NAMES:
                self.index += 1
                unit_node = self._node("unit", unit.text, (), unit.start, unit.end)
                result = self._node("binary", "*", (result, unit_node), token.start, unit.end)
            return result
        if token.kind == "name":
            self.index += 1
            if self._take("("):
                if token.text not in _FUNCTIONS:
                    _fail("E_SCHEMA", "허용하지 않는 함수 호출입니다.", token.start, token.end)
                arguments = []
                if not self._take(")"):
                    while True:
                        arguments.append(self._sum(depth + 1))
                        if len(arguments) > MAX_ARGUMENTS:
                            _fail("E_RESOURCE", "함수 인수는 최대 32개입니다.", token.start, token.end)
                        if self._take(")"):
                            break
                        if not self._take(","):
                            _fail("E_SCHEMA", "함수 인수 구분자 또는 닫는 괄호가 필요합니다.", token.start, token.end)
                count = len(arguments)
                valid = count >= 1 if token.text in ("min", "max") else count == {"atan2": 2, "clamp": 3}.get(token.text, 1)
                if not valid:
                    _fail("E_SCHEMA", "함수 인수 개수가 맞지 않습니다.", token.start, token.end)
                return self._node("call", token.text, arguments, token.start, self.tokens[self.index - 1].end)
            if token.text in _FUNCTIONS or keyword.iskeyword(token.text):
                _fail("E_SCHEMA", "예약 이름을 변수로 사용할 수 없습니다.", token.start, token.end)
            kind = "unit" if token.text in _UNIT_NAMES else "constant" if token.text in _CONSTANTS else "variable"
            return self._node(kind, token.text, (), token.start, token.end)
        _fail("E_SCHEMA", "숫자, 변수 또는 괄호 표현식이 필요합니다.", token.start, token.end)


def dependencies(text: str) -> set[str]:
    """! @brief 문법을 검증하고 실제 참조하는 변수 이름을 반환한다.
    @param text 제한 문법의 표현식 원문.
    @return 단위/상수/함수 이름을 제외한 변수 이름 집합.
    """
    root = _Parser(text).parse()
    result = set()
    pending = [root]
    while pending:
        node = pending.pop()
        if node.kind == "variable":
            result.add(node.text)
        pending.extend(node.children)
    return result


class _Evaluator:
    """! @brief 구문 노드를 직접 순회하며 SI 수치와 물리 차원을 계산한다."""

    def __init__(self, variables: dict[str, Quantity]):
        """! @brief 입력 사전과 실제로 소비한 변수 정보를 구분한다."""
        if type(variables) is not dict:
            _fail("E_SCHEMA", "변수는 이름과 Quantity의 사전이어야 합니다.")
        if any(type(name) is not str or not name.isidentifier() or name in RESERVED_NAMES for name in variables):
            _fail("E_SCHEMA", "변수 이름이 유효하지 않거나 예약 이름과 충돌합니다.")
        self.variables = variables
        self.used = {}
        self.operations = 0

    def _checked(self, value: float, dimension: tuple, node: _Node, *, nonzero: bool = False) -> _Value:
        """! @brief 수치 범위와 중간 차원 크기를 확인한다."""
        if not math.isfinite(value) or nonzero and value == 0.0:
            _fail("E_EXPR_DOMAIN", "계산 결과가 유한 float64 범위를 벗어났습니다.", node.start, node.end)
        if any(abs(power) > 1024 or power.denominator > 1024 for power in dimension):
            _fail("E_RESOURCE", "중간 차원의 지수 크기를 초과했습니다.", node.start, node.end)
        return _Value(0.0 if value == 0.0 else value, dimension)

    def _same(self, values, node):
        """! @brief 같은 차원을 요구하는 연산의 입력을 검사한다."""
        if any(value.dimension != values[0].dimension for value in values[1:]):
            _fail("E_UNIT", "서로 다른 물리 차원을 결합할 수 없습니다.", node.start, node.end)

    def evaluate(self, node: _Node) -> _Value:
        """! @brief 제한된 개수의 구문 노드만 평가한다."""
        self.operations += 1
        if self.operations > MAX_OPERATIONS:
            _fail("E_RESOURCE", "표현식 평가 연산 상한을 초과했습니다.", node.start, node.end)
        if node.kind == "number":
            number = float(node.text)
            mantissa = re.split("[eE]", node.text)[0]
            nonzero = any(character in "123456789" for character in mantissa)
            return self._checked(number, _SCALAR, node, nonzero=nonzero)
        if node.kind == "unit":
            unit = Quantity.from_value(1.0, node.text)
            return _Value(unit.value_si, _DIMENSIONS[unit.dimension])
        if node.kind == "constant":
            return _Value(math.pi, _SCALAR) if node.text == "pi" else _Value(299792458.0, _dim(1, -1, 0, 0, 0))
        if node.kind == "variable":
            quantity = self.variables.get(node.text)
            if type(quantity) is not Quantity or quantity.value_si is None:
                _fail("E_SCHEMA", "참조한 변수가 없거나 값이 미정입니다.", node.start, node.end)
            self.used[node.text] = quantity
            return _Value(quantity.value_si, _DIMENSIONS[quantity.dimension])
        values = [self.evaluate(child) for child in node.children]
        try:
            if node.kind == "unary":
                first = values[0]
                return self._checked(first.number if node.text == "+" else -first.number, first.dimension, node)
            if node.kind == "binary":
                return self._binary(node, values[0], values[1])
            return self._call(node, values)
        except (ValueError, OverflowError, ZeroDivisionError) as error:
            _fail("E_EXPR_DOMAIN", f"실수 계산의 정의역을 벗어났습니다: {type(error).__name__}", node.start, node.end)

    def _binary(self, node, left, right):
        """! @brief 산술 연산마다 필요한 차원과 정의역을 검사한다."""
        operator = node.text
        if operator in ("+", "-"):
            self._same((left, right), node)
            number = left.number + right.number if operator == "+" else left.number - right.number
            return self._checked(number, left.dimension, node)
        if operator == "*":
            dimension = tuple(a + b for a, b in zip(left.dimension, right.dimension))
            return self._checked(left.number * right.number, dimension, node, nonzero=left.number != 0 and right.number != 0)
        if operator == "/":
            dimension = tuple(a - b for a, b in zip(left.dimension, right.dimension))
            return self._checked(left.number / right.number, dimension, node, nonzero=left.number != 0)
        if right.dimension != _SCALAR:
            _fail("E_UNIT", "거듭제곱 지수는 무차원이어야 합니다.", node.start, node.end)
        if abs(right.number) > 1024:
            _fail("E_RESOURCE", "거듭제곱 지수의 절댓값은 1024 이하여야 합니다.", node.start, node.end)
        exponent = Fraction(str(right.number)).limit_denominator(1024)
        if left.dimension != _SCALAR and float(exponent) != right.number:
            _fail("E_UNIT", "차원이 있는 값의 지수는 작은 유리수여야 합니다.", node.start, node.end)
        if left.number == 0 and right.number == 0:
            _fail("E_EXPR_DOMAIN", "0의 0제곱은 지원하지 않습니다.", node.start, node.end)
        dimension = tuple(power * exponent for power in left.dimension)
        number = math.pow(left.number, right.number)
        return self._checked(number, dimension, node, nonzero=left.number != 0)

    def _call(self, node, values):
        """! @brief 승인된 수학 함수만 명시적으로 호출한다."""
        name = node.text
        first = values[0]
        if name == "sqrt":
            return self._checked(math.sqrt(first.number), tuple(power / 2 for power in first.dimension), node, nonzero=first.number != 0)
        if name in ("sin", "cos", "tan"):
            if first.dimension not in (_SCALAR, _DIMENSIONS[Dimension.ANGLE]):
                _fail("E_UNIT", "삼각함수 입력은 각도 또는 무차원 radian이어야 합니다.", node.start, node.end)
            if name == "tan" and abs(math.remainder(first.number, math.pi)) == math.pi / 2:
                _fail("E_EXPR_DOMAIN", "tan의 극점에서는 계산할 수 없습니다.", node.start, node.end)
            function = {"sin": math.sin, "cos": math.cos, "tan": math.tan}[name]
            return self._checked(function(first.number), _SCALAR, node)
        if name == "atan2":
            self._same(values, node)
            if first.number == 0 and values[1].number == 0:
                _fail("E_EXPR_DOMAIN", "atan2의 두 입력이 모두 0입니다.", node.start, node.end)
            return self._checked(math.atan2(first.number, values[1].number), _DIMENSIONS[Dimension.ANGLE], node)
        if name == "abs":
            return self._checked(abs(first.number), first.dimension, node)
        self._same(values, node)
        if name == "clamp":
            if values[1].number > values[2].number:
                _fail("E_EXPR_DOMAIN", "clamp의 최소값이 최대값보다 큽니다.", node.start, node.end)
            number = min(max(first.number, values[1].number), values[2].number)
        else:
            number = (min if name == "min" else max)(value.number for value in values)
        return self._checked(number, first.dimension, node)


def evaluate_expression(text: str, variables: dict[str, Quantity], *, expected_dimension: str, display_unit: str) -> Quantity:
    """! @brief 표현식을 평가하고 요청한 차원과 표시 단위의 Quantity를 만든다.
    @param text 제한 문법의 원문. 숫자 바로 뒤의 알려진 단위만 묵시 곱셈을 허용한다.
    @param variables 이름으로 참조하는 불변 Quantity 입력.
    @param expected_dimension 최종 결과에 필요한 물리 차원.
    @param display_unit 결과를 표시할 동일 차원의 지원 단위.
    @return 유한 SI 값, 실제 사용한 변수의 출처와 추정 상태를 보존한 Quantity.
    @throws ProjectError 문법/미정값/차원/정의역/자원 제한 오류.
    """
    root = _Parser(text).parse()
    evaluator = _Evaluator(variables)
    result = evaluator.evaluate(root)
    try:
        expected = Dimension(expected_dimension)
        Quantity.missing(expected, display_unit)
    except (ValueError, TypeError, QuantityError) as error:
        _fail("E_UNIT", str(error))
    if result.dimension != _DIMENSIONS[expected]:
        _fail("E_UNIT", "표현식 결과의 차원이 지정한 결과 차원과 다릅니다.", root.start, root.end)
    estimated = any(value.status == QuantityStatus.ESTIMATED for value in evaluator.used.values())
    references = tuple(dict.fromkeys(reference for value in evaluator.used.values() for reference in value.source_refs))
    return Quantity(result.number, expected, display_unit, QuantityStatus.ESTIMATED if estimated else QuantityStatus.USER_ENTERED, references)
