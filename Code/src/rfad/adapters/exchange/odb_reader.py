"""! @brief ODB++ ZIP에서 보드 프로파일과 원문 제조 구조를 분리해 읽는다."""

import hashlib
from io import BytesIO
import math
import re
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from rfad.domain.errors import ProjectError


MAX_MEMBERS = 4096
MAX_EXPANDED = 64 * 1024 * 1024
MAX_TEXT = 4 * 1024 * 1024
FACTORS = {"MM": 1, "INCH": 25.4}


def _text(archive, name):
    """! @brief ZIP을 풀지 않고 필요한 표준 텍스트 멤버만 제한 크기로 읽는다."""
    member = archive.getinfo(name)
    if member.file_size > MAX_TEXT:
        raise ProjectError("E_RESOURCE", "ODB++ 프로파일 또는 매트릭스의 크기 한도를 초과했습니다.")
    return archive.read(member).decode("utf-8")


def _profile(text, step):
    """! @brief 한 개의 양극성 직선 표면과 내부 섬 제외 경계를 닫힌 mm 좌표로 읽는다."""
    rows = [row.split() for row in text.splitlines() if row.strip() and not row.lstrip().startswith("#")]
    if not rows or len(rows[0]) != 1:
        return None
    unit = rows[0][0].removeprefix("UNITS=")
    if rows[0][0] != "UNITS=" + unit or unit not in FACTORS:
        return None
    rows = rows[1:]
    if rows and rows[0] == ["F", "1"]:
        rows = rows[1:]
    if (len(rows) < 2 or len(rows[0]) != 3 or rows[0][:2] != ["S", "P"]
            or not rows[0][2].isdigit() or rows[-1] != ["SE"]):
        return None
    factor = FACTORS[unit]
    loops = {"I": [], "H": []}
    kind, points = None, []
    for row in rows[1:-1]:
        if row[0] == "OB" and kind is None and len(row) == 4 and row[3] in loops:
            kind = row[3]
        elif row == ["OE"] and kind is not None:
            if (not 4 <= len(points) <= 65 or points[0] != points[-1]
                    or len(set(map(tuple, points[:-1]))) != len(points) - 1):
                return None
            loops[kind].append(points[:-1])
            kind, points = None, []
            continue
        elif row[0] != "OS" or kind is None or len(row) != 3 or len(points) >= 65:
            return None
        try:
            point = [float(value) * factor for value in row[1:3]]
        except ValueError:
            return None
        if any(not math.isfinite(value) or abs(value) > 1e6 for value in point):
            return None
        if not points or points[-1] != point:
            points.append(point)
    if kind is not None or len(loops["I"]) != 1 or len(loops["H"]) > 16:
        return None
    return {"step": step, "units": unit, "outer_mm": loops["I"][0], "cutouts_mm": loops["H"]}


def _matches_step(matrix, step):
    """! @brief 단일 매트릭스 단계와 실제 프로파일 경로가 같은 보드를 가리키는지 확인한다."""
    if matrix.count("STEP {") != 1:
        return False
    start = matrix.index("STEP {") + 1
    stop = next((index for index in range(start, len(matrix)) if matrix[index] == "}"), start)
    names = [line.split("=", 1)[1].strip() for line in matrix[start:stop] if line.startswith("NAME=")]
    return len(names) == 1 and names[0].casefold() == step.casefold()


def _trace_nets(eda, *, planes=False):
    """! @brief 배선 또는 평면 서브넷의 FID C에서 층과 도형 번호가 명시된 넷을 읽는다."""
    names, current, routed = [], None, False
    claimed = set()
    result = {}
    for line in eda.splitlines():
        fields = line.split(";", 1)[0].split()
        if not fields:
            continue
        if fields[0] == "LYR":
            if names:
                return {}
            names = [value.casefold() for value in fields[1:]]
            if len(set(names)) != len(names):
                return {}
        elif fields[0] == "NET":
            current = fields[1] if len(fields) == 2 else None
            routed = False
        elif fields[0] == "SNT":
            routed = fields == (["SNT", "PLN", "S", "E", "0"] if planes else ["SNT", "TRC"])
        elif fields[0] == "PKG":
            break
        elif (routed or planes) and len(fields) == 4 and fields[:2] == ["FID", "C"]:
            if not all(token.isdecimal() and len(token) <= 8 for token in fields[2:]):
                return {}
            layer, number = map(int, fields[2:])
            if layer >= len(names):
                return {}
            key = (names[layer], number)
            if key in claimed:
                return {}
            claimed.add(key)
            if routed and current is not None:
                result[key] = "" if current == "$NONE$" else current
    return result


def _layer_traces(text, layer, nets):
    """! @brief 양극성 도체층에서 둥근 표준 심벌과 직접 연결된 배선만 좌표로 변환한다."""
    from rfad.adapters.exchange.manufacturing_copper import trace

    symbols, feature_number, unit = {}, 0, None
    result = []
    for line in text.splitlines():
        row = line.split(";", 1)[0].split()
        if not row or row[0].startswith(("#", "@", "&")):
            continue
        opcode = row[0]
        if opcode.startswith("UNITS="):
            if unit is not None or opcode[6:] not in FACTORS:
                return []
            unit = FACTORS[opcode[6:]]
        elif opcode.startswith("$"):
            if len(row) == 2 and re.fullmatch(r"r[0-9]+(?:[.][0-9]+)?", row[1]) and unit is not None:
                symbols[opcode[1:]] = float(row[1][1:]) * unit / 1000
        elif opcode in {"L", "A", "P", "S", "T", "B"}:
            number = feature_number
            feature_number += 1
            polarity = {"L": 6, "A": 8, "P": 4, "S": 1, "T": 5, "B": 5}[opcode]
            if len(row) <= polarity or row[polarity] != "P":
                return []
            if opcode not in {"L", "A"} or (layer, number) not in nets or unit is None:
                continue
            if len(row) != (8 if opcode == "L" else 11) or row[polarity + 1] != "0":
                continue
            width = symbols.get(row[polarity - 1])
            if width is None:
                continue
            try:
                start, end = [[float(v) * unit for v in fields] for fields in (row[1:3], row[3:5])]
                center = [float(v) * unit for v in row[5:7]] if opcode == "A" else None
            except ValueError:
                continue
            item = trace(layer, nets[layer, number], f"copper:{layer}:{number}", width, start, end,
                         center, {"Y": True, "N": False}.get(row[-1]) if center is not None else None)
            if item is not None:
                result.append(item)
                if len(result) > 128:
                    return []
        elif opcode not in {"F", "OB", "OS", "OC", "OE", "SE"}:
            return []
    return result


def _editable_traces(archive, names, prefix, step, matrix):
    """! @brief 단일 보드의 명시적 신호층과 EDA 배선 참조가 있는 멤버만 개별로 읽는다."""
    base = prefix + "steps/" + step + "/"
    if base + "eda/data" not in names:
        return []
    nets = _trace_nets(_text(archive, base + "eda/data"))
    if not nets:
        return []
    results = []
    for block in re.findall(r"(?:^|\n)LAYER\s*\{([^{}]*)\}", matrix):
        attrs = dict(line.strip().split("=", 1) for line in block.splitlines() if "=" in line)
        if attrs.get("CONTEXT") != "BOARD" or attrs.get("TYPE") != "SIGNAL" or attrs.get("POLARITY") != "POSITIVE":
            continue
        name = attrs.get("NAME", "").casefold()
        if not name or "/" in name:
            continue
        path = base + "layers/" + name + "/features"
        if path in names:
            results.extend(_layer_traces(_text(archive, path), name, nets))
            if len(results) > 128:
                return []
    return results


def read(raw):
    """! @brief 제조 ZIP의 경계 및 합법 경로와 단일 보드 적용 여부를 검토한다."""
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries if not entry.is_dir()}
            if (len(entries) > MAX_MEMBERS or len(names) != sum(not entry.is_dir() for entry in entries)
                    or sum(entry.file_size for entry in entries) > MAX_EXPANDED
                    or any(name.startswith("/") or ".." in PurePosixPath(name).parts or chr(92) in name
                           or ":" in name for name in names)):
                raise ProjectError("E_RESOURCE", "ODB++ ZIP의 경로, 멤버 수 또는 확장 크기가 유효하지 않습니다.")
            matrix = [name for name in names if name == "matrix/matrix" or name.endswith("/matrix/matrix")]
            if len(matrix) != 1:
                raise ProjectError("E_SCHEMA", "단일 ODB++ matrix/matrix가 필요합니다.")
            prefix = matrix[0].removesuffix("matrix/matrix")
            board_paths = sorted(name for name in names if name.startswith(prefix + "steps/")
                                 and name.endswith("/profile") and len(name.removeprefix(prefix).split("/")) == 3)
            steps = [name.split("/")[-2] for name in board_paths]
            data = _text(archive, matrix[0])
            levels = [row.strip() for row in data.splitlines()]
            if not steps or "STEP {" not in levels or "LAYER {" not in levels:
                raise ProjectError("E_SCHEMA", "ODB++ matrix와 step profile을 확인하십시오.")
            layers = levels.count("LAYER {")
            with_eda = [step for step in steps if f"{prefix}steps/{step}/eda/data" in names]
            features = sum(name.startswith(prefix + "steps/") and name.endswith("/features") for name in names)
            version, info = "unspecified", {}
            if prefix + "misc/info" in names:
                info = dict(line.split("=", 1) for line in _text(archive, prefix + "misc/info").splitlines() if "=" in line)
                major, minor = (info.get(key, "").strip() for key in ("ODB_VERSION_MAJOR", "ODB_VERSION_MINOR"))
                if all(value.isascii() and value.isdigit() and len(value) <= 8 for value in (major, minor)):
                    version = f"{major}.{minor}"
            editable, traces = None, []
            regions, omitted = [], []
            pads, bores, stack, components = [], [], [], []
            if len(steps) == 1 and _matches_step(levels, steps[0]):
                content = _text(archive, board_paths[0])
                header_path = f"{prefix}steps/{steps[0]}/stephdr"
                header = _text(archive, header_path) if header_path in names else ""
                if not any(line.lstrip().startswith("STEP-REPEAT") for line in header.splitlines()):
                    editable = _profile(content, steps[0])
                    if editable:
                        from rfad.adapters.exchange import manufacturing_regions
                        regions, omitted = manufacturing_regions.odb(archive, names, prefix + "steps/" + steps[0] + "/", data)
                        traces = _editable_traces(archive, names, prefix, steps[0], data)
                        from rfad.adapters.exchange.manufacturing_contacts import odb
                        pads, bores, stack = odb(archive, names, prefix, steps[0], data, info)
                        from rfad.adapters.exchange import manufacturing_placements
                        components = manufacturing_placements.odb(archive, names, prefix + "steps/" + steps[0] + "/",
                                                                  data, pads, bores, info.get("SAVE_APP", "").startswith("KiCad EDA "))
    except (BadZipFile, UnicodeError, RuntimeError, NotImplementedError) as error:
        raise ProjectError("E_SCHEMA", "ODB++ ZIP 또는 제조 텍스트를 읽을 수 없습니다.") from error
    loss = {"code": "odbpp_profile_only" if editable else "odbpp_review_only", "raw_preserved": True,
            "message": ("같은 보드 외곽을 확인한 뒤 직선 내부 절삭을 반영합니다. 층·넷·홀·부품은 원문에 보존합니다."
                        if editable else "지원하는 단일 보드 직선 프로파일이 없어 원문을 읽기만 합니다.")}
    if traces:
        loss = {"code": "odbpp_partial_copper", "raw_preserved": True,
                "message": f"외곽과 절삭을 대조합니다. 층과 넷을 지정하면 EDA 배선 참조가 있는 직선 및 원호 {len(traces)}개를 반영합니다. 나머지 제조 정보는 원문에 보존합니다."}
    if pads or bores or stack or components:
        loss = {**loss, "message": loss["message"] + f" 선택 가능한 원형 패드 {len(pads)}개, 원형 홀 {len(bores)}개, 적층 {len(stack)}개, 실장 위치 {len(components)}개."}
    if regions or omitted:
        reasons = sorted({row["reason"] for row in omitted})
        summary = f" 적용 가능한 채움 동박 {len(regions)}개, 제외 {len(omitted)}건."
        loss = {**loss, "message": loss["message"] + summary + (" " + " ".join(reasons) if reasons else "")}
    return {"editable_regions": regions, "region_exclusions": omitted[:128], "region_exclusion_count": len(omitted),
            "editable_components": components, "editable_pads": pads, "editable_holes": bores, "editable_stack": stack,
            "editable_traces": traces, "schema": "rfad.odbpp-read/0.1", "version": version, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "steps": steps, "steps_with_eda": with_eda, "layer_count": layers, "feature_files": features,
            "editable_profile": editable, "losses": [loss]}
