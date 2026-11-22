"""! @brief 프로젝트 소유 원본 두 개에서 급전, 설치와 정합값의 차이를 계산한다."""

from rfad.domain.design import resolve_scalar
from rfad.domain.network_circuit import DIMENSIONS
from rfad.domain.network_library import KEY as NETWORK_KEY
from rfad.domain.physical_setup import candidates, setup


def _values(document):
    """! @brief 부품 식별자와 실제 계산 단위를 사용하고 현재 원본을 수정하지 않는다."""
    values = {}
    physical = setup(document)
    scenario = next((row for row in physical["scenarios"] if row["id"] == physical["active_scenario_id"]), None)

    def add(section, identity, key, name, label, value):
        """! @brief 비교 행의 안정 키와 실제 편집 위치를 보존한다."""
        values[section, identity, key] = {"name": name, "label": label, "value": value}

    def quantity(original, dimension, unit):
        """! @brief 직접값과 식을 같은 단위로 비교하며 미정값은 보존한다."""
        result = resolve_scalar(document, original, dimension)
        return None if result.value_si is None else f"{result.as_unit(unit):.17g} {unit}"

    add("installation", "", "scenario", "설치", "활성 구성", scenario["name"] if scenario else "기판 단독")
    for port in document["ports"]:
        identity, name = port["id"], port["name"]
        for key, label in (("reference_plane", "기준면"), ("direction", "방향"), ("polarity", "극성"),
                           ("positive_geometry_id", "신호 도체"), ("reference_geometry_id", "기준 도체")):
            add("port", identity, key, name, label, port[key])
        add("port", identity, "resistance", name, "저항", quantity(port["resistance"], "impedance", "ohm"))
        for bound, label in (("min", "유효 대역 시작"), ("max", "유효 대역 끝")):
            add("port", identity, "validity_hz." + bound, name, label,
                quantity(port["validity_hz"][bound], "frequency", "Hz"))
        for end, label in (("start", "급전 시작"), ("stop", "급전 끝")):
            coords = port.get("excitation_box", {}).get(end)
            if coords is not None:
                for axis, value in zip("xyz", coords):
                    add("port", identity, f"excitation_box.{end}.{axis}", name, f"{label} {axis.upper()}",
                        quantity(value, "length", "mm"))
    surfaces, parts = candidates(document)
    for row in [*surfaces, *parts]:
        identity, name = row["id"], row["name"]
        for key, label in (("kind", "종류"), ("include_in_em", "해석 포함"), ("material_id", "재료"),
                           ("coverage", "피복"), ("side", "배치 면")):
            if key in row:
                add("installation", identity, key, name, label, row[key])
        for key, label in (("x", "X"), ("y", "Y"), ("z", "Z"), ("width", "폭"), ("height", "길이"),
                           ("depth", "깊이"), ("thickness", "두께"), ("case_thickness", "케이스 두께"),
                           ("offset", "이격")):
            if key in row:
                add("installation", identity, key, name, label, quantity(row[key], "length", "mm"))
        if "yaw" in row:
            add("installation", identity, "yaw", name, "회전", quantity(row["yaw"], "angle", "deg"))
        if row.get("step"):
            add("installation", identity, "step", name, "STEP 원본 해시", row["step"]["sha256"])
    for circuit in document["extensions"].get(NETWORK_KEY, {}).get("circuits", []):
        identity, name = circuit["id"], circuit["name"]
        definition = circuit["definition"]
        for key, label in (("input_reference_plane", "입력 기준면"), ("load_reference_plane", "부하 기준면")):
            add("matching", identity, key, name, label, definition[key])
        for element in definition["elements"]:
            prefix = "elements." + element["id"] + "."
            value = element["value"]
            add("matching", identity, prefix + "value", name, element["name"] + " 값",
                quantity(value, DIMENSIONS[element["kind"]], value["display_unit"]))
            add("matching", identity, prefix + "connection", name, element["name"] + " 연결", element["connection"])
            add("matching", identity, prefix + "state", name, element["name"] + " 상태", element["state"])
    return values


def compare(current, source, *, offset=0):
    """! @brief 미정과 다른 구성에만 있는 값을 구분해 다음 쪽까지 비교할 수 있게 한다."""
    before, after = _values(current), _values(source)
    items = []
    for key in sorted(before.keys() | after.keys()):
        left, right = before.get(key), after.get(key)
        if left == right:
            continue
        row = left if left is not None else right
        items.append({"section": key[0], "id": key[1], "key": key[2], "name": row["name"], "label": row["label"],
                      "current": left["value"] if left is not None else None,
                      "source": right["value"] if right is not None else None,
                      "current_exists": left is not None, "source_exists": right is not None})
    limit = 120
    return {"items": items[offset:offset + limit], "total": len(items),
            "next_offset": offset + limit if offset + limit < len(items) else None}
