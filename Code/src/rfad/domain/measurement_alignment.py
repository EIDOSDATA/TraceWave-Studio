"""! @brief 원래 복소 자료를 보존하는 명시 포트 순열/RI 보간과 Z0 정렬을 수행한다."""

from bisect import bisect_left
from copy import deepcopy
from fractions import Fraction
import math

from rfad.application.canonical import canonical_hash
from rfad.domain.design import _fields
from rfad.domain.measurement import _refs, bounded
from rfad.domain.network_data import MAX_SAMPLES, fail, finite, text, validate_dataset
from rfad.domain.network_transform import real_references, require_basis, transform_dataset

SCHEMA = "rfad.measurement-alignment/0.1"
MAX_OPERATIONS = 3
PORT_FIELDS = ("port_ids", "port_names", "reference_planes", "port_modes", "current_orientation")
MATRIX_FIELDS = ("values_ri", "valid_mask", "sample_status")


def _order(order, ports):
    """! @brief 새 축에서 읽을 원래 축 순번을 완전한 순열로 제한한다."""
    if (type(order) is not list or len(order) != ports or any(type(i) is not int for i in order)
            or sorted(order) != list(range(ports))):
        fail("포트 순서는 각 원래 포트가 한 번씩 있는 완전한 순열입니다.", "order")


def _frequencies(values, gap):
    """! @brief 중복/비유한 주파수와 암묵적인 무제한 간격을 거절한다."""
    if type(values) is not list or not 1 <= len(values) <= MAX_SAMPLES:
        fail("정렬 주파수는 1~1001개입니다.", "frequency_hz", "E_RESOURCE")
    previous = -1.0
    for value in values:
        number = finite(value, "frequency_hz")
        if number < 0 or number <= previous:
            fail("정렬 주파수는 중복 없는 비음수 증가 목록입니다.", "frequency_hz")
        previous = number
    if finite(gap, "max_gap_hz") <= 0:
        fail("보간의 최대 간격은 양수여야 합니다.", "max_gap_hz")


def _references(z0, count, ports):
    """! @brief 재정규화의 전체 주파수/포트 Z0를 양의 실수로 명시한다."""
    if type(z0) is not list or len(z0) != count:
        fail("재정규화 Z0의 주파수 축 길이가 다릅니다.", "z0_ohm")
    for row in z0:
        if type(row) is not list or len(row) != ports:
            fail("재정규화 Z0의 포트 축 길이가 다릅니다.", "z0_ohm")
        for value in row:
            if type(value) is not list or len(value) != 2:
                fail("재정규화 Z0는 [실수, 허수]입니다.", "z0_ohm")
            if finite(value[0], "z0_ohm") <= 0 or finite(value[1], "z0_ohm") != 0:
                fail("현재 재정규화는 양의 실수 Z0만 지원합니다.", "z0_ohm", "E_UNSUPPORTED")


def validate_alignment_specification(spec, dataset):
    """! @brief 연산 순서와 실제 중간 축 길이를 검증하며 원문을 재배열하지 않는다."""
    validate_dataset(dataset)
    _fields(spec, {"schema", "operations", "reason", "source_refs"}, "alignment")
    if spec["schema"] != SCHEMA:
        fail("지원하지 않는 정렬 버전입니다.", "alignment.schema", "E_VERSION")
    text(spec["reason"], "alignment.reason")
    _refs(spec["source_refs"], "alignment.source_refs")
    operations = spec["operations"]
    if type(operations) is not list or not 1 <= len(operations) <= MAX_OPERATIONS:
        fail("정렬은 1~3개의 명시 연산입니다.", "alignment.operations", "E_RESOURCE")
    used = set()
    count, ports = len(dataset["frequency_hz"]), len(dataset["port_ids"])
    for operation in operations:
        if type(operation) is not dict or type(operation.get("kind")) is not str:
            fail("정렬 연산 종류가 필요합니다.", "alignment.operations")
        kind = operation["kind"]
        if kind in used:
            fail("같은 정렬 연산을 반복할 수 없습니다.", "alignment.operations", "E_UNSUPPORTED")
        used.add(kind)
        if kind == "permute_ports":
            _fields(operation, {"kind", "order"}, "alignment.operations")
            _order(operation["order"], ports)
        elif kind == "linear_ri":
            _fields(operation, {"kind", "frequency_hz", "max_gap_hz"}, "alignment.operations")
            _frequencies(operation["frequency_hz"], operation["max_gap_hz"])
            count = len(operation["frequency_hz"])
        elif kind == "renormalize":
            _fields(operation, {"kind", "z0_ohm"}, "alignment.operations")
            if dataset["parameter_kind"] != "S":
                fail("Z0 재정규화의 입력은 S 자료입니다.", "alignment.operations", "E_UNSUPPORTED")
            _references(operation["z0_ohm"], count, ports)
        else:
            fail("정의하지 않은 정렬/이동/맞춤 연산은 지원하지 않습니다.", "alignment.operations", "E_UNSUPPORTED")
    bounded(spec, "alignment")
    return deepcopy(spec)


def _record_operation(result, original, lineage):
    """! @brief 원래 provenance를 덮지 않고 별도 유한 연산 이력에 입력 hash를 추가한다."""
    operations = result["provenance"].setdefault("measurement_operations", [])
    if type(operations) is not list or len(operations) >= 32:
        fail("측정 정렬 출처 목록 상한을 초과했습니다.", "provenance.measurement_operations", "E_RESOURCE")
    operations.append({"input_hash": canonical_hash(original), **deepcopy(lineage)})
    validate_dataset(result)


def permute_ports(dataset, order):
    """! @brief 양 행렬 축과 모든 포트별 조건을 같은 순열로 옮기고 표본 출처를 보존한다."""
    validate_dataset(dataset)
    _order(order, len(dataset["port_ids"]))
    result = deepcopy(dataset)
    for field in PORT_FIELDS:
        result[field] = [deepcopy(dataset[field][i]) for i in order]
    for field in MATRIX_FIELDS:
        result[field] = [[[deepcopy(matrix[i][j]) for j in order] for i in order] for matrix in dataset[field]]
    if dataset["z0_ohm"] is not None:
        result["z0_ohm"] = [[deepcopy(row[i]) for i in order] for row in dataset["z0_ohm"]]
    lineage = {"kind": "permute_ports", "order": list(order), "source_port_ids": list(dataset["port_ids"]),
               "source_sample_origin": list(dataset["sample_origin"])}
    _record_operation(result, dataset, lineage)
    return {"dataset": result, "lineage": lineage, "diagnostics": []}


def _lerp(left, right, weight):
    """! @brief 차분 overflow를 피하며 유한 convex RI 합과 영점 underflow를 구분한다."""
    if left == right:
        return left
    try:
        value = math.fsum((left * (1.0 - weight), right * weight))
    except OverflowError:
        fail("보간 결과가 유한 수치 범위를 벗어났습니다.", "values_ri", "E_NUMERIC")
    if not math.isfinite(value):
        fail("보간 결과가 비유한입니다.", "values_ri", "E_NUMERIC")
    if value == 0.0:
        exact = Fraction(left) * (1 - Fraction(weight)) + Fraction(right) * Fraction(weight)
        if exact != 0:
            fail("보간의 비영 결과가 표시 가능한 수치 범위보다 작습니다.", "values_ri", "E_NUMERIC")
    return value


def interpolate_ri(dataset, frequency_hz, max_gap_hz):
    """! @brief 바로 이웃한 유효 RI만 보간하고 정확한 원래 표본은 mask/출처까지 복사한다."""
    validate_dataset(dataset)
    _frequencies(frequency_hz, max_gap_hz)
    source_frequencies = dataset["frequency_hz"]
    if frequency_hz[0] < source_frequencies[0] or frequency_hz[-1] > source_frequencies[-1]:
        fail("원래 주파수 범위 밖으로 외삽할 수 없습니다.", "frequency_hz", "E_UNSUPPORTED")
    interpolating = any(frequency not in source_frequencies for frequency in frequency_hz)
    if interpolating:
        require_basis(dataset, phasor=True)
        reference = real_references(dataset, 0)
        for index in range(1, len(source_frequencies)):
            if real_references(dataset, index) != reference:
                fail("주파수 의존 Z0의 보간은 지원하지 않습니다.", "z0_ohm", "E_UNSUPPORTED")
    result = deepcopy(dataset)
    result["frequency_hz"] = deepcopy(frequency_hz)
    for field in (*MATRIX_FIELDS, "sample_origin"):
        result[field] = []
    if dataset["z0_ohm"] is not None:
        result["z0_ohm"] = []
    samples = []
    ports = len(dataset["port_ids"])
    for frequency in frequency_hz:
        right = bisect_left(source_frequencies, frequency)
        if source_frequencies[right] == frequency:
            for field in (*MATRIX_FIELDS, "sample_origin"):
                result[field].append(deepcopy(dataset[field][right]))
            if dataset["z0_ohm"] is not None:
                result["z0_ohm"].append(deepcopy(dataset["z0_ohm"][right]))
            samples.append([right, right, 0.0])
            continue
        left = right - 1
        gap = source_frequencies[right] - source_frequencies[left]
        if gap > max_gap_hz:
            fail("두 원본 표본의 간격이 명시 최대 간격보다 큽니다.", "max_gap_hz", "E_CONFLICT")
        if any(not valid for index in (left, right) for row in dataset["valid_mask"][index] for valid in row):
            fail("결측/무효 표본을 건너뛰거나 일부 행렬만 보간할 수 없습니다.", "valid_mask", "E_CONFLICT")
        weight = (frequency - source_frequencies[left]) / gap
        if not 0 < weight < 1:
            fail("내부 보간 가중치가 float64 표현 범위를 벗어났습니다.", "frequency_hz", "E_NUMERIC")
        result["values_ri"].append([[[_lerp(dataset["values_ri"][left][i][j][part],
                                          dataset["values_ri"][right][i][j][part], weight)
                                     for part in range(2)] for j in range(ports)] for i in range(ports)])
        result["valid_mask"].append([[True] * ports for _ in range(ports)])
        result["sample_status"].append([["valid"] * ports for _ in range(ports)])
        result["z0_ohm"].append(deepcopy(dataset["z0_ohm"][left]))
        result["sample_origin"].append("interpolated")
        samples.append([left, right, weight])
    lineage = {"kind": "linear_ri", "samples": samples, "max_gap_hz": max_gap_hz,
               "source_frequency_hz": deepcopy(source_frequencies), "source_sample_origin": list(dataset["sample_origin"]),
               "uncertainty_propagation": "not_performed"}
    _record_operation(result, dataset, lineage)
    return {"dataset": result, "lineage": lineage, "diagnostics": []}


def align_dataset(dataset, specification, engine_identity):
    """! @brief 명시 순서대로 별도 자료를 만들고 실제 재정규화 엔진의 검증 경계를 재사용한다."""
    spec = validate_alignment_specification(specification, dataset)
    if type(engine_identity) is not dict or not engine_identity:
        fail("application이 고정한 정렬 엔진 identity가 필요합니다.", "engine_identity")
    bounded(engine_identity, "engine_identity", 16 * 1024)
    result = deepcopy(dataset)
    lineage, diagnostics = [], []
    for operation in spec["operations"]:
        kind = operation["kind"]
        if kind == "permute_ports":
            step = permute_ports(result, operation["order"])
        elif kind == "linear_ri":
            step = interpolate_ri(result, operation["frequency_hz"], operation["max_gap_hz"])
        else:
            step = transform_dataset(result, {"operation": "renormalize", "z0_ohm": operation["z0_ohm"]})
            step["lineage"] = {"kind": "renormalize", "source_sample_origin": list(result["sample_origin"]),
                               "engine": deepcopy(step["engine"]), "input_hash": canonical_hash(result)}
        lineage.append(deepcopy(step["lineage"]))
        diagnostics.extend({"operation_index": len(lineage) - 1, **row} for row in step["diagnostics"])
        result = step["dataset"]
    _record_operation(result, dataset, {"kind": "alignment", "specification": spec, "engine": deepcopy(engine_identity),
                                      "uncertainty_propagation": "not_performed"})
    return {"dataset": result, "lineage": lineage, "diagnostics": diagnostics, "engine": deepcopy(engine_identity)}
