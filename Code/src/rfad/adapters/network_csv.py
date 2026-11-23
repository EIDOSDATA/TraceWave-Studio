"""! @brief UTF-8 CSV의 명시적 열/단위 대응만 사용하여 복소 네트워크를 교환한다."""

from copy import deepcopy
import csv

from rfad.adapters.network_text import (
    FREQUENCY_UNITS, MAX_COLUMNS, MAX_PORTS, MAX_SAMPLES, complex_pair, decode_text,
    encoded, exportable, fail, frequency, number, parsed_network,
)
from rfad.domain.network_data import UNITS


PROFILE = "rfad.network-csv/0.1"
REQUIRED_MAPPING = {"delimiter", "header", "frequency_column", "frequency_unit", "parameter_kind",
                    "complex_format", "value_unit", "port_count", "pairs", "ignored_columns"}


def _index(value, limit, field):
    """! @brief bool을 정수 인덱스로 받지 않고 유한 열/포트 범위를 검사한다."""
    if type(value) is not int or not 0 <= value < limit:
        fail("인덱스가 현재 열/포트 범위를 벗어납니다.", field)
    return value


def _mapping(value):
    """! @brief 중복 열, 암묵적 단위와 빠진 행렬 원소를 허용하지 않는다."""
    if type(value) is not dict or not REQUIRED_MAPPING.issubset(value) or set(value) - REQUIRED_MAPPING - {"z0_ohm"}:
        fail("CSV 열 대응 필드가 누락되거나 알 수 없는 필드가 있습니다.", "mapping")
    if value["delimiter"] not in (",", ";", "\t") or type(value["header"]) is not bool:
        fail("CSV 구분자와 header 여부를 명시해야 합니다.", "mapping")
    ports = value["port_count"]
    if type(ports) is not int or not 1 <= ports <= MAX_PORTS:
        fail(f"CSV는 1~{MAX_PORTS}포트를 지원합니다.", "mapping.port_count", code="E_RESOURCE")
    kind, form, unit = value["parameter_kind"], value["complex_format"], value["frequency_unit"]
    if type(kind) is not str or kind not in UNITS or value["value_unit"] != UNITS[kind]:
        fail("CSV S/Z/Y와 단위 1/ohm/S가 일치해야 합니다.", "mapping.value_unit", code="E_UNIT")
    if form not in ("RI", "MA", "DB") or type(unit) is not str or unit.lower() not in FREQUENCY_UNITS:
        fail("CSV 복소 표현과 주파수 단위를 명시해야 합니다.", "mapping")
    used = {_index(value["frequency_column"], MAX_COLUMNS, "mapping.frequency_column")}
    pairs = value["pairs"]
    if type(pairs) is not list or len(pairs) != ports * ports:
        fail("포트 행렬의 모든 복소 열 쌍을 명시해야 합니다.", "mapping.pairs")
    cells = set()
    for pair in pairs:
        if type(pair) is not dict or set(pair) != {"row", "column", "first_column", "second_column"}:
            fail("복소 열 쌍의 필드가 잘못되었습니다.", "mapping.pairs")
        cell = (_index(pair["row"], ports, "mapping.pairs.row"), _index(pair["column"], ports, "mapping.pairs.column"))
        if cell in cells:
            fail("행렬 원소가 중복 대응되었습니다.", "mapping.pairs")
        cells.add(cell)
        for key in ("first_column", "second_column"):
            column = _index(pair[key], MAX_COLUMNS, "mapping.pairs." + key)
            if column in used:
                fail("같은 CSV 열을 두 값에 대응할 수 없습니다.", "mapping.pairs")
            used.add(column)
    ignored = value["ignored_columns"]
    if type(ignored) is not list or len(ignored) > MAX_COLUMNS:
        fail("사용하지 않는 CSV 열을 명시해야 합니다.", "mapping.ignored_columns")
    for column in ignored:
        column = _index(column, MAX_COLUMNS, "mapping.ignored_columns")
        if column in used:
            fail("무시 열이 중복되거나 사용하는 열과 겹칩니다.", "mapping.ignored_columns")
        used.add(column)
    z0 = value.get("z0_ohm")
    if z0 is not None:
        if type(z0) is not list or len(z0) != ports:
            fail("CSV Z0 입력은 포트별 실수 목록 또는 미정이어야 합니다.", "mapping.z0_ohm")
        for item in z0:
            if type(item) not in (int, float) or number(str(item)) <= 0:
                fail("CSV에 명시한 Z0는 양수 실수여야 합니다.", "mapping.z0_ohm")
    return ports, used, z0


def parse_csv(raw, mapping):
    """! @brief CSV 원문을 추측하지 않고 사용자가 검토한 열 대응을 적용한다."""
    ports, used, z0 = _mapping(mapping)
    lines, source = decode_text(raw)
    nonempty = [(index, line) for index, line in enumerate(lines, 1) if line.strip()]
    reader = csv.reader((line for _, line in nonempty), delimiter=mapping["delimiter"], strict=True)
    frequencies, matrices, headers = [], [], []
    previous_line, column_count = 0, None
    try:
        for record_index, row in enumerate(reader):
            line = nonempty[previous_line][0]
            if reader.line_num != previous_line + 1:
                fail("현재 CSV profile은 따옴표 안의 여러 줄 필드를 지원하지 않습니다.", line=line, code="E_UNSUPPORTED")
            previous_line = reader.line_num
            if column_count is None:
                column_count = len(row)
                if not 1 <= column_count <= MAX_COLUMNS or used != set(range(column_count)):
                    fail("모든 CSV 열은 값 또는 무시 열로 정확히 한 번 대응해야 합니다.", "mapping", line=line)
            if len(row) != column_count:
                fail("CSV 행의 열 개수가 달라졌습니다.", line=line)
            if mapping["header"] and record_index == 0:
                if any(len(cell) > 256 or any(ord(char) < 32 for char in cell) for cell in row):
                    fail("CSV 헤더의 길이 또는 제어 문자가 지원 범위를 벗어납니다.", line=line)
                headers = row
                continue
            if len(frequencies) == MAX_SAMPLES:
                fail("1001개 CSV 표본 상한을 초과했습니다.", line=line, code="E_RESOURCE")
            previous = frequencies[-1] if frequencies else -1
            frequencies.append(frequency(row[mapping["frequency_column"]].strip(), mapping["frequency_unit"], previous, line=line))
            matrix = [[None] * ports for _ in range(ports)]
            for pair in mapping["pairs"]:
                matrix[pair["row"]][pair["column"]] = complex_pair(
                    row[pair["first_column"]].strip(), row[pair["second_column"]].strip(), mapping["complex_format"], line=line)
            matrices.append(matrix)
    except csv.Error:
        fail("CSV 따옴표 또는 구분자 구문이 잘못되었습니다.", line=reader.line_num)
    stored_mapping = deepcopy(mapping)
    if stored_mapping["delimiter"] == "\t":
        stored_mapping["delimiter"] = "\\t"
    metadata = {**source, "profile": PROFILE, "format": "csv", "mapping": stored_mapping,
                "mapping_encoding": "tab_delimiter_as_backslash_t",
                "column_names": headers, "column_count": column_count, "phase_unit": "deg" if mapping["complex_format"] != "RI" else None,
                "reference_origin": "user_mapping" if z0 is not None else "missing"}
    return parsed_network(mapping["parameter_kind"], frequencies, matrices, ports, metadata, z0=z0)


def csv_export_mapping(data):
    """! @brief 내보낸 고정 CSV 열을 다시 읽을 수 있는 명시 대응표를 제공한다."""
    ports = exportable(data)
    pairs = [{"row": row, "column": column, "first_column": 1 + 2 * (row * ports + column),
              "second_column": 2 + 2 * (row * ports + column)} for row in range(ports) for column in range(ports)]
    return {"delimiter": ",", "header": True, "frequency_column": 0, "frequency_unit": "Hz",
            "parameter_kind": data["parameter_kind"], "complex_format": "RI", "value_unit": data["unit"],
            "port_count": ports, "pairs": pairs, "ignored_columns": [], "z0_ohm": None}


def write_csv(data):
    """! @brief UTF-8 고정 열의 Hz/real-imag 값을 출력하며 조건은 sidecar에 남긴다."""
    ports = exportable(data)
    kind = data["parameter_kind"]
    labels = ["frequency_Hz"] + [f"{kind}{row + 1}{column + 1}_{part}" for row in range(ports) for column in range(ports) for part in ("re", "im")]
    lines = [",".join(labels)]
    for frequency_value, matrix in zip(data["frequency_hz"], data["values_ri"]):
        values = [frequency_value] + [part for row in matrix for cell in row for part in cell]
        lines.append(",".join(format(value, ".17g") for value in values))
    return encoded(lines)
