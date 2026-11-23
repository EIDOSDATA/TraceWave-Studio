"""! @brief 명시한 Touchstone 1.0/2.0/2.1 단일종단 S Full profile을 읽고 쓴다."""

import re

from rfad.adapters.network_text import (
    FREQUENCY_UNITS, MAX_PORTS, MAX_SAMPLES, complex_pair, decode_text, encoded,
    exportable, fail, frequency, number, parsed_network,
)


PROFILE = "rfad.touchstone-s/0.1"
SPECIFICATION = "https://www.ibis.org/touchstone_ver2.1/touchstone_ver2_1.pdf"
KEYWORD = re.compile(r"\[([^\[\]]+)\](?:[ \t]+(.*))?\Z")


def _option(text, line):
    """! @brief 옵션 순서와 기본값 출처를 구분하고 중복/미지원 옵션을 거절한다."""
    result = {"frequency_unit": "GHz", "parameter_kind": "S", "complex_format": "MA", "reference_ohm": 50.0}
    explicit = set()
    tokens = text[1:].split()
    index = 0
    while index < len(tokens):
        token = tokens[index].upper()
        if token.lower() in FREQUENCY_UNITS:
            key, value = "frequency_unit", token
        elif token in ("RI", "MA", "DB"):
            key, value = "complex_format", token
        elif token in ("S", "Y", "Z", "H", "G"):
            if token != "S":
                fail("이 Touchstone profile은 S만 지원합니다. Z/Y의 버전별 정규화는 추정하지 않습니다.", line=line, code="E_UNSUPPORTED")
            key, value = "parameter_kind", token
        elif token == "R":
            index += 1
            if index == len(tokens):
                fail("R 뒤에 양수 기준 저항이 필요합니다.", line=line)
            key, value = "reference_ohm", number(tokens[index], line=line)
            if value <= 0:
                fail("기준 저항은 양수여야 합니다.", line=line)
        else:
            fail("미지원 옵션입니다. 1.1의 포트별 R 구문은 현재 지원하지 않습니다.", line=line, code="E_UNSUPPORTED")
        if key in explicit:
            fail("Touchstone 옵션이 중복되었습니다.", line=line)
        explicit.add(key)
        result[key] = value
        index += 1
    result["defaulted_options"] = sorted(set(result) - explicit)
    return result


def _keyword(text, raw, line):
    """! @brief 키워드의 열/공백과 이름을 엄격히 검사한다."""
    match = KEYWORD.fullmatch(text)
    if not raw.startswith("[") or match is None or match[1] != match[1].strip():
        fail("Touchstone 키워드의 열 또는 괄호 구문이 잘못되었습니다.", line=line)
    return match[1].lower(), (match[2] or "").strip()


def _positive_integer(value, limit, line):
    """! @brief 선언 수가 실제 자료와 예산을 앞서 제한하도록 한다."""
    if re.fullmatch(r"[0-9]+", value) is None or len(value) > 9:
        fail("양의 정수 개수가 필요합니다.", line=line)
    count = int(value)
    if count < 1 or count > limit:
        fail("선언 개수가 현재 profile의 상한을 벗어납니다.", line=line, code="E_RESOURCE")
    return count


def parse_touchstone(raw, file_name):
    """! @brief 파일 원문을 보존할 수 있도록 순수 bytes를 읽고 ID 없는 DTO를 반환한다."""
    if type(file_name) is not str or not file_name or len(file_name) > 256 or any(c in file_name for c in "/\\\r\n"):
        fail("Touchstone 원본의 파일 이름만 전달해야 합니다.", "file_name")
    lines, source = decode_text(raw)
    content, utf8_comments = [], False
    for line, original in enumerate(lines, 1):
        body, _, comment = original.partition("!")
        utf8_comments |= not comment.isascii()
        if not body.isascii():
            fail("Touchstone 데이터/키워드는 ASCII여야 합니다. UTF-8 확장은 주석에만 허용합니다.", line=line)
        if body.strip():
            content.append((line, body.strip(), body))
    if not content:
        fail("Touchstone 옵션과 자료가 없습니다.")
    version, cursor = "1.0", 0
    if content[0][1].startswith("["):
        line, text, body = content[0]
        key, value = _keyword(text, body, line)
        if key != "version" or value not in ("2.0", "2.1"):
            fail("지원하는 첫 선언은 [Version] 2.0 또는 2.1입니다.", line=line, code="E_UNSUPPORTED")
        version, cursor = value, 1
    if cursor == len(content) or not content[cursor][1].startswith("#"):
        fail("Touchstone 옵션 행이 필요합니다.")
    option_line, option_text, _ = content[cursor]
    options = _option(option_text, option_line)
    cursor += 1
    suffix = re.search(r"\.s([0-9]+)p$", file_name, re.IGNORECASE)
    ports, declared, order, reference = None, None, "21_12", None
    reference_origin = "option_line" if "reference_ohm" not in options["defaulted_options"] else "spec_default"
    seen = set()
    if version == "1.0":
        if suffix is None:
            fail("1.0 profile은 포트 수가 명시된 .sNp 파일 이름이 필요합니다.", "file_name", code="E_UNSUPPORTED")
        ports = _positive_integer(suffix[1], MAX_PORTS, option_line)
    else:
        while cursor < len(content):
            line, text, body = content[cursor]
            key, value = _keyword(text, body, line)
            cursor += 1
            if key in seen:
                fail("Touchstone 키워드가 중복되었습니다.", line=line)
            if not seen and key != "number of ports":
                fail("옵션 다음에는 [Number of Ports]가 필요합니다.", line=line)
            seen.add(key)
            if key == "number of ports":
                ports = _positive_integer(value, MAX_PORTS, line)
            elif key == "number of frequencies":
                declared = _positive_integer(value, MAX_SAMPLES, line)
            elif key == "two-port data order":
                if ports != 2 or value.lower() not in ("21_12", "12_21"):
                    fail("2포트의 21_12 또는 12_21 순서가 필요합니다.", line=line)
                order = value.lower()
            elif key == "matrix format":
                if value.lower() != "full":
                    fail("현재 Touchstone profile은 Full 행렬만 지원합니다.", line=line, code="E_UNSUPPORTED")
            elif key == "reference":
                tokens = value.split()
                while len(tokens) < ports and cursor < len(content) and not content[cursor][1].startswith(("[", "#")):
                    tokens += content[cursor][1].split()
                    cursor += 1
                if len(tokens) != ports:
                    fail("[Reference]는 포트마다 하나의 양수 실수여야 합니다.", line=line)
                reference = [number(token, line=line) for token in tokens]
                if any(value <= 0 for value in reference):
                    fail("기준 저항은 양수여야 합니다.", line=line)
                reference_origin = "reference_keyword"
            elif key == "network data":
                if value or declared is None or (ports == 2 and "two-port data order" not in seen):
                    fail("Network Data 전에 표본 수와 2포트 순서 선언이 필요합니다.", line=line)
                break
            else:
                fail("미지원 Touchstone 키워드입니다. noise/mixed-mode/information은 읽지 않습니다.", line=line, code="E_UNSUPPORTED")
        if "network data" not in seen:
            fail("[Network Data]가 없습니다.")
        if suffix and int(suffix[1]) != ports:
            fail("파일 이름의 포트 수와 [Number of Ports]가 다릅니다.", "file_name")
    frequencies, matrices, pending = [], [], []
    width, ended = 1 + 2 * ports * ports, False
    indices = [(row, column) for row in range(ports) for column in range(ports)]
    if ports == 2 and order == "21_12":
        indices = [(0, 0), (1, 0), (0, 1), (1, 1)]
    for line, text, body in content[cursor:]:
        if ended:
            fail("[End] 뒤에 데이터가 있습니다.", line=line)
        if text.startswith("["):
            key, value = _keyword(text, body, line)
            if version != "1.0" and key == "end" and not value and not pending:
                ended = True
                continue
            fail("미지원 구간 또는 불완전한 데이터입니다.", line=line, code="E_UNSUPPORTED")
        if text.startswith("#"):
            fail("현재 profile은 중복 옵션 행을 조용히 무시하지 않습니다.", line=line, code="E_UNSUPPORTED")
        tokens = text.split()
        if version == "1.0":
            row_width = width if ports <= 2 else 2 * ports + int(not pending)
            if len(tokens) != row_width:
                fail("Touchstone 1.0의 주파수 및 포트별 행 길이가 다릅니다.", line=line, code="E_UNSUPPORTED")
        pending += tokens
        if len(pending) > width:
            fail("한 행에 다음 주파수 또는 초과 값이 있습니다.", line=line)
        if len(pending) < width:
            continue
        if len(frequencies) == MAX_SAMPLES:
            fail("1001개 표본 상한을 초과했습니다.", line=line, code="E_RESOURCE")
        frequencies.append(frequency(pending[0], options["frequency_unit"], frequencies[-1] if frequencies else -1, line=line))
        matrix = [[None] * ports for _ in range(ports)]
        for index, (row, column) in enumerate(indices):
            matrix[row][column] = complex_pair(pending[1 + 2 * index], pending[2 + 2 * index], options["complex_format"], line=line)
        matrices.append(matrix)
        pending = []
    if pending or (version != "1.0" and (not ended or len(frequencies) != declared)):
        fail("표본 수, 불완전한 행 또는 [End]가 실제 데이터와 일치하지 않습니다.")
    metadata = {**source, "profile": PROFILE, "format": "touchstone", "file_name": file_name,
                "format_version": version, "options": options, "two_port_order": order if ports == 2 else None,
                "reference_origin": reference_origin, "reference_ohm": reference or [options["reference_ohm"]] * ports,
                "specification": SPECIFICATION, "utf8_comment_extension": utf8_comments}
    return parsed_network("S", frequencies, matrices, ports, metadata, z0=metadata["reference_ohm"], single_ended=True)


def write_touchstone(data):
    """! @brief 표현 가능한 원본 S 행렬을 순서대로 2.1/Hz/RI로 출력한다."""
    ports = exportable(data)
    if data["parameter_kind"] != "S" or data["z0_ohm"] is None:
        fail("Touchstone 출력에는 S와 명시된 실수 기준 저항이 필요합니다.", code="E_UNSUPPORTED")
    references = data["z0_ohm"][0]
    if any(value is None or value[1] != 0 or value[0] <= 0 for value in references) or any(row != references for row in data["z0_ohm"]):
        fail("Touchstone 출력은 포트별 양수 실수의 주파수 불변 Z0만 지원합니다.", "z0_ohm", code="E_UNSUPPORTED")
    if any(mode != "single_ended" for mode in data["port_modes"]):
        fail("Touchstone 출력에는 단일종단 포트 선언이 필요합니다.", "port_modes", code="E_UNSUPPORTED")
    lines = ["! TraceWave Studio S Full profile; context is preserved in the accompanying metadata.",
             "[Version] 2.1", "# Hz S RI R " + format(references[0][0], ".17g"), "[Number of Ports] " + str(ports)]
    if ports == 2:
        lines.append("[Two-Port Data Order] 12_21")
    lines += ["[Number of Frequencies] " + str(len(data["frequency_hz"])),
              "[Reference] " + " ".join(format(value[0], ".17g") for value in references),
              "[Matrix Format] Full", "[Network Data]"]
    for frequency_value, matrix in zip(data["frequency_hz"], data["values_ri"]):
        values = [frequency_value] + [part for row in matrix for cell in row for part in cell]
        lines.append(" ".join(format(value, ".17g") for value in values))
    return encoded(lines + ["[End]"])
