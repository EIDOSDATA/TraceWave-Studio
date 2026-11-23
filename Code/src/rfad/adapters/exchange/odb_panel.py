"""! @brief ODB++의 단일 보드 재사용과 다중 배열 패널의 제조 원문을 검증한다."""

from io import BytesIO
import math
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from rfad.domain.errors import ProjectError


NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.+-]{0,63}\Z")
REPEAT_FIELDS = {"NAME", "X", "Y", "DX", "DY", "NX", "NY", "ANGLE", "FLIP", "MIRROR"}


def _fields(text):
    """! @brief 같은 키가 여러 번 나오거나 잘못된 구조면 묵시적 덮어쓰기를 막는다."""
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, equals, value = line.strip().partition("=")
        if not equals or not name or name in result:
            raise ProjectError("E_SCHEMA", "ODB++ 패널 헤더의 중복 또는 알 수 없는 항목이 있습니다.")
        result[name] = value.strip()
    return result


def _dimension(data, key, factor):
    """! @brief 제조 배치를 유한한 mm 또는 각도 범위의 원문으로 읽는다."""
    try:
        value = float(data[key]) * factor
    except (KeyError, ValueError):
        raise ProjectError("E_SCHEMA", "ODB++ 패널의 원점, 간격 또는 각도가 누락됐습니다.") from None
    if not math.isfinite(value) or abs(value) > 1e6:
        raise ProjectError("E_RESOURCE", "ODB++ 패널 치수의 유한 범위를 확인하십시오.")
    return value


def header(text):
    """! @brief stephdr의 datum과 STEP-REPEAT 배치를 원래 단위의 명세로 대응한다."""
    from rfad.adapters.exchange.odb_reader import FACTORS

    regex = re.compile(r"(?m)^\s*STEP-REPEAT\s*\{([^{}]*)\}")
    blocks = regex.findall(text)
    attrs = _fields(regex.sub("", text))
    factor = FACTORS.get(attrs.get("UNITS"))
    if factor is None:
        raise ProjectError("E_SCHEMA", "ODB++ step header의 단위를 확인하십시오.")
    datum = [_dimension(attrs, axis + "_DATUM", factor) for axis in "XY"]
    if len(blocks) > 64:
        raise ProjectError("E_RESOURCE", "한 패널의 반복 배치 기록은 64개까지 지원합니다.")
    repeats = []
    for block in blocks:
        row = _fields(block)
        if (set(row) != REPEAT_FIELDS or not NAME.fullmatch(row["NAME"])
                or any(row[key] not in ("YES", "NO") for key in ("FLIP", "MIRROR"))):
            raise ProjectError("E_SCHEMA", "ODB++ 반복 배치의 형식과 방향을 확인하십시오.")
        if any(not row[key].isascii() or not row[key].isdigit() or not 1 <= len(row[key]) <= 3 for key in ("NX", "NY")):
            raise ProjectError("E_SCHEMA", "ODB++ 패널 반복 횟수는 양의 정수여야 합니다.")
        counts = [int(row[key]) for key in ("NX", "NY")]
        if min(counts) < 1 or math.prod(counts) > 256:
            raise ProjectError("E_RESOURCE", "한 배열의 패널 반복 횟수는 1~256개입니다.")
        repeats.append({"source_step": row["NAME"].casefold(), "origin_mm": [_dimension(row, a, factor) for a in "XY"],
                        "pitch_mm": [_dimension(row, "D" + a, factor) for a in "XY"], "count": counts,
                        "angle_deg": _dimension(row, "ANGLE", 1), "flip": row["FLIP"] == "YES",
                        "mirror": row["MIRROR"] == "YES"})
    if sum(math.prod(row["count"]) for row in repeats) > 256:
        raise ProjectError("E_RESOURCE", "한 패널의 반복 보드는 256개까지 지원합니다.")
    return datum, repeats


def inspect(archive, names, prefix, profiles):
    """! @brief 제조 패널의 보드 참조와 명시적 배치를 조용히 평탄화하지 않는다."""
    from rfad.adapters.exchange.odb_reader import _text

    panels, errors = {}, []
    children = {name.casefold() for name in profiles}
    repeated = set()
    for step in profiles:
        location = f"{prefix}steps/{step}/stephdr"
        if location not in names:
            continue
        text = _text(archive, location)
        if "STEP-REPEAT" not in text:
            continue
        repeated.add(step.casefold())
        try:
            datum, rows = header(text)
            if not rows:
                raise ProjectError("E_SCHEMA", "반복 step 목록이 비어 있습니다.")
            if any(row["source_step"] not in children for row in rows):
                raise ProjectError("E_CONFLICT", "패널이 참조하는 보드 step이 원문에 없습니다.")
            panels[step.casefold()] = {"step": step, "datum_mm": datum, "repeats": rows}
        except ProjectError as error:
            errors.append({"step": step, "code": error.code, "message": error.message})
    result = []
    for item in panels.values():
        if any(row["source_step"] in repeated for row in item["repeats"]):
            errors.append({"step": item["step"], "code": "E_UNSUPPORTED",
                           "message": "중첩되거나 순환하는 반복 패널은 원문에서만 확인할 수 있습니다."})
        else:
            result.append(item)
    return result, errors


def _decimal(value):
    """! @brief 패널 경계를 ODB++ 밀리미터 고정 소수 표기로 쓴다."""
    return f"{value:.12f}".rstrip("0").rstrip(".") if value else "0"


def build(raw, count, pitch, margin):
    """! @brief 단일 보드 원문을 복사하고 겹치지 않는 평행 반복의 패널 step을 만든다."""
    from rfad.adapters.exchange.odb_reader import MAX_EXPANDED, MAX_MEMBERS, MAX_TEXT, _text, read

    check = read(raw)
    if check["editable_profile"] is None or len(check["steps"]) != 1:
        raise ProjectError("E_UNSUPPORTED", "편집 가능한 단일 보드 직선 프로파일이 있는 ODB++ 원문을 사용하세요.")
    if (len(count) != 2 or any(type(number) is not int or number < 1 for number in count) or math.prod(count) > 256
            or len(pitch) != 2 or any(type(value) not in (float, int) or not 1e-6 <= value <= 1e4 for value in (*pitch, margin))):
        raise ProjectError("E_RESOURCE", "2축 반복 횟수, 양의 간격과 패널 여백을 지정하세요.")
    with ZipFile(BytesIO(raw)) as origin:
        matrix = next(path for path in origin.namelist() if path == "matrix/matrix" or path.endswith("/matrix/matrix"))
        prefix = matrix.removesuffix("matrix/matrix")
        src_step, = check["steps"]
        if src_step.casefold() == "tw_panel" or not NAME.fullmatch(src_step):
            raise ProjectError("E_CONFLICT", "기판 step 이름이 패널 이름과 중복되거나 유효하지 않습니다.")
        child = f"{prefix}steps/{src_step}/"
        datum, repeats = header(_text(origin, child + "stephdr"))
        if repeats:
            raise ProjectError("E_CONFLICT", "이미 반복 배치가 있는 step을 중첩할 수 없습니다.")
        xs, ys = zip(*check["editable_profile"]["outer_mm"])
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if any(n > 1 and step <= size for n, step, size in zip(count, pitch, (x1-x0, y1-y0))):
            raise ProjectError("E_GEOMETRY", "보드 외곽이 겹치거나 닿지 않도록 반복 간격을 설정하세요.")
        loc = [datum[0] - x0 + margin, datum[1] - y0 + margin]
        high_x = x1-x0 + (count[0]-1)*pitch[0] + 2*margin
        high_y = y1-y0 + (count[1]-1)*pitch[1] + 2*margin
        if max(high_x, high_y) > 1e6:
            raise ProjectError("E_RESOURCE", "패널 외곽이 유한 좌표 범위를 벗어났습니다.")
        text = ("UNITS=MM\nX_DATUM=0\nY_DATUM=0\nX_ORIGIN=0\nY_ORIGIN=0\nSTEP-REPEAT {\n"
                f"NAME={src_step.upper()}\nX={_decimal(loc[0])}\nY={_decimal(loc[1])}\n"
                f"DX={_decimal(pitch[0])}\nDY={_decimal(pitch[1])}\n"
                f"NX={count[0]}\nNY={count[1]}\nANGLE=0\nFLIP=NO\nMIRROR=NO\n}}\n")
        contour = f"UNITS=MM\nF 1\nS P 0\nOB 0 0 I\nOS {_decimal(high_x)} 0\n"
        contour += f"OS {_decimal(high_x)} {_decimal(high_y)}\nOS 0 {_decimal(high_y)}\nOS 0 0\nOE\nSE\n"
        step_line = "STEP {\n    COL=2\n    NAME=TW_PANEL\n}\n\n"
        layout = _text(origin, matrix)
        if not re.search(r"(?m)^\s*COL\s*=\s*1\s*$", layout):
            raise ProjectError("E_UNSUPPORTED", "단일 보드가 matrix의 첫 번째 위치에 있어야 합니다.")
        layers = re.search(r"(?m)^\s*LAYER\s*\{", layout)
        modified = (layout[:layers.start()].rstrip() + "\n\n" + step_line + layout[layers.start():].lstrip()).encode("utf8")
        files = {matrix: modified, f"{prefix}steps/tw_panel/stephdr": text.encode(),
                 f"{prefix}steps/tw_panel/profile": contour.encode()}
        entries = origin.infolist()
        growth = sum(map(len, files.values())) - origin.getinfo(matrix).file_size
        if (len(entries) + 2 > MAX_MEMBERS or len(modified) > MAX_TEXT
                or sum(entry.file_size for entry in entries) + growth > MAX_EXPANDED
                or any(entry.filename in files and entry.filename != matrix for entry in entries)):
            raise ProjectError("E_RESOURCE", "패널을 추가할 때의 아카이브 상한 또는 파일 중복을 확인하세요.")
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as writer:
            for member in entries:
                if member.filename != matrix:
                    writer.writestr(member, origin.read(member))
            for path, content in files.items():
                writer.writestr(ZipInfo(path), content, compress_type=ZIP_DEFLATED)
    result = output.getvalue()
    verified = read(result)["panels"]
    expected = {"source_step": src_step.casefold(), "origin_mm": list(map(float, map(_decimal, loc))),
                "pitch_mm": list(map(float, map(_decimal, pitch))), "count": list(count),
                "angle_deg": 0, "flip": False, "mirror": False}
    if len(verified) != 1 or verified[0]["repeats"] != [expected]:
        raise ProjectError("E_HASH", "패널을 다시 읽은 반복 배치가 입력과 다릅니다.")
    return result
