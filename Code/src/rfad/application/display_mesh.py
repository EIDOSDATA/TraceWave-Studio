"""! @brief 물리 원본과 분리된 제한 표시 mesh의 무결성과 객체 대응을 검사한다."""

import math
from uuid import UUID

from rfad.domain.errors import ProjectError


SCHEMA = "rfad.display-mesh/0.1"
MAX_MESH_BYTES = 16 * 1024 * 1024
MAX_TRIANGLES = 100000
MAX_VERTICES = 300000
LINEAR_DEFLECTION_MM = 0.05
ANGULAR_DEFLECTION_RAD = 0.15
MAPPING_KEYS = ("id", "source_entity_ids", "layer_id", "role")


def _require(condition: bool, message: str) -> None:
    """! @brief 표시 경계 위반을 정상 기하 결과와 구분하여 반환한다."""
    if not condition:
        raise ProjectError("E_HASH", message, details={"field_path": "display_mesh"})


def _identity(value: object) -> bool:
    """! @brief 객체 식별자가 정규 UUID인지 외부 참조 없이 확인한다."""
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def validate_display_mesh(mesh: dict, *, snapshot: dict, run_id: str, body_map: list[dict]) -> None:
    """! @brief 실제 소비할 JSON의 입력 결합, 상한, 유한 좌표와 색인을 검증한다.

    @details mesh는 화면 표시 전용이며 STEP 정확도나 solver mesh를 대체하지 않는다.
    """
    _require(type(mesh) is dict and mesh.get("schema") == SCHEMA, "지원하지 않는 표시 mesh 계약입니다.")
    _require(mesh.get("snapshot") == snapshot and mesh.get("run_id") == run_id,
             "표시 mesh가 출력 snapshot 또는 실행에 결합되지 않았습니다.")
    _require(mesh.get("unit") == "mm" and mesh.get("purpose") == "display_only",
             "표시 mesh의 단위 또는 목적이 다릅니다.")
    _require(type(mesh.get("linear_deflection_mm")) is float and mesh["linear_deflection_mm"] == LINEAR_DEFLECTION_MM and
             type(mesh.get("angular_deflection_rad")) is float and mesh["angular_deflection_rad"] == ANGULAR_DEFLECTION_RAD,
             "표시 mesh 허용오차가 고정 profile과 다릅니다.")
    bodies = mesh.get("bodies")
    _require(type(bodies) is list and 0 < len(bodies) <= 256 and type(body_map) is list and len(bodies) == len(body_map),
             "표시 mesh body 개수가 원본 mapping 또는 상한과 다릅니다.")
    _require(all(type(body) is dict and _identity(body.get("id")) for body in body_map),
             "CAD body mapping의 식별자가 유효하지 않습니다.")
    expected = {body.get("id"): {key: body.get(key) for key in MAPPING_KEYS} for body in body_map}
    _require(len(expected) == len(body_map) and all(_identity(identity) for identity in expected),
             "CAD body mapping의 식별자가 중복되거나 유효하지 않습니다.")
    seen = set()
    total_vertices = total_triangles = 0
    for body in bodies:
        _require(type(body) is dict, "표시 body가 객체가 아닙니다.")
        identity = body.get("id")
        _require(_identity(identity) and identity not in seen and identity in expected,
                 "표시 body의 식별자가 원본에 없거나 중복됩니다.")
        seen.add(identity)
        _require({key: body.get(key) for key in MAPPING_KEYS} == expected[identity],
                 "표시 body의 원본 UUID 또는 층/역할 대응이 다릅니다.")
        sources = body.get("source_entity_ids")
        _require(_identity(body.get("layer_id")) and body.get("role") in ("conductor", "dielectric") and
                 type(sources) is list and 0 < len(sources) <= 128 and all(_identity(value) for value in sources) and
                 len(set(sources)) == len(sources), "표시 body의 원본 식별자 대응이 유효하지 않습니다.")
        vertices, triangles = body.get("vertices"), body.get("triangles")
        _require(type(vertices) is list and type(triangles) is list and bool(vertices) and bool(triangles),
                 "표시 body에 정점 또는 삼각형이 없습니다.")
        total_vertices += len(vertices)
        total_triangles += len(triangles)
        if total_vertices > MAX_VERTICES or total_triangles > MAX_TRIANGLES:
            raise ProjectError("E_RESOURCE", "표시 mesh 정점 또는 삼각형 상한을 초과했습니다.")
        for vertex in vertices:
            _require(type(vertex) is list and len(vertex) == 3 and all(type(value) in (int, float) and
                     abs(value) <= 1000001.0 and math.isfinite(value) for value in vertex),
                     "표시 mesh 좌표가 유한한 mm 표시 범위를 벗어났습니다.")
        for triangle in triangles:
            _require(type(triangle) is list and len(triangle) == 3 and all(type(index) is int and
                     0 <= index < len(vertices) for index in triangle) and len(set(triangle)) == 3,
                     "표시 mesh 삼각형 색인이 유효하지 않습니다.")
            a, b, c = (vertices[index] for index in triangle)
            u, v = ([b[index] - a[index] for index in range(3)], [c[index] - a[index] for index in range(3)])
            cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            _require(any(value != 0.0 for value in cross), "표시 mesh에 면적이 없는 삼각형이 있습니다.")
