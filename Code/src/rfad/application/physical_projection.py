"""! @brief 적층/환경의 목적별 CAD 입력 및 미정 상태를 서비스에서 산출한다."""

from rfad.domain.design import _fail
from rfad.domain.physical_setup import candidates, stack_review, em_exclusions


def check_em(document):
    """! @brief 검증된 PCB 해석 범위 밖의 명시적 요청을 차단한다."""
    for row in em_exclusions(document):
        if row["reason"] == "unsupported_in_profile":
            _fail("E_UNSUPPORTED", "현재 PCB 해석은 이 표면층/외부 물체를 포함할 수 없습니다. 해석 포함 설정을 확인하십시오.",
                  row["section"] + "." + row["id"] + ".include_in_em")


def project_setup(document, mode, length, angle, *, maximum):
    """! @brief 설치 물체는 활성 환경에서만 취하고 표시/출력을 독립 투영한다."""
    surfaces, parts = candidates(document)
    flag = "visible" if mode == "geometry" else "include_in_export"
    review = stack_review(document)
    intervals = {row["id"]: row["interval_si"] for row in review["surfaces"]}
    projected_surfaces, projected_parts, omitted = [], [], []
    for row in surfaces:
        field = "surface." + row["id"]
        if not row[flag]:
            omitted.append({"id": row["id"], "reason": flag + "=false"})
            continue
        interval = intervals[row["id"]]
        if interval is None:
            _fail("E_GEOMETRY", "기준 적층 z 또는 표면층 위치/두께가 미정입니다.", field)
        thickness = length(row["thickness"], field + ".thickness", positive=True)
        z_min = interval[0] * 1000.0
        if abs(z_min) > maximum or abs(z_min + thickness) > maximum or z_min + thickness <= z_min:
            _fail("E_GEOMETRY", "표면층 z 범위가 CAD 형상 프로파일을 벗어났습니다.", field)
        def rectangle(value, path):
            """! @brief 명시한 x/y/폭/높이만 커널 길이로 투영한다."""
            return [length(value[key], path + "." + key, positive=key in ("width", "height"))
                    for key in ("x", "y", "width", "height")]
        projected_surfaces.append({**{key: row[key] for key in ("id", "name", "kind", "coverage", "material_id")},
            "z_min_mm": z_min, "thickness_mm": thickness,
            "rectangle_mm": None if row["coverage"] == "board" else rectangle(row, field),
            "openings_mm": [rectangle(item, field + f".openings[{index}]") for index, item in enumerate(row["openings"])]})
    for row in parts:
        field = "part." + row["id"]
        if not row[flag]:
            omitted.append({"id": row["id"], "reason": flag + "=false"})
            continue
        yaw = angle(row["yaw"], field + ".yaw")
        if abs(yaw) > 360.0:
            _fail("E_GEOMETRY", "외부 배치 yaw는 -360~360 deg 범위로 입력하십시오.", field + ".yaw")
        projected_parts.append({**{key: row[key] for key in ("id", "name", "kind", "material_id")},
            "translation_mm": [length(row[key], field + "." + key) for key in ("x", "y", "z")],
            "yaw_deg": yaw,
            "size_mm": [length(row[key], field + "." + key, positive=True) for key in ("width", "height", "depth")]
                       if row["kind"] != "step" else None})
        for key in ("instance_offsets", "instance_replacements"):
            if row.get(key):
                projected_parts[-1][key] = row[key]
        if row["kind"] == "dielectric_case":
            projected_parts[-1]["wall_mm"] = length(row["case_thickness"], field + ".case_thickness", positive=True)
    return projected_surfaces, projected_parts, omitted
