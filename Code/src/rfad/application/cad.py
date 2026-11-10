"""! @brief 불변 설계 스냅샷을 단위와 범위가 명시된 CAD 입력으로 변환한다.

@details 이 모듈은 표준 라이브러리와 순수 도메인 코드만 사용한다. 형상 생성,
접촉/단락 판정, STEP 출력과 재입력 검사는 별도 native worker의 책임이다.
"""

from copy import deepcopy
import math
from uuid import UUID

from rfad.application.canonical import CANONICAL_VERSION, canonical_hash
from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.domain.units import QuantityError


PROFILE = "rfad.step.mechanical/0.1"
INPUT_SCHEMA = "rfad.cad-input/0.1"
TOLERANCE_MM = 1e-6
MIN_FEATURE_MM = 1e-5
MAX_COORDINATE_MM = 1e6
MAX_START_ANGLE_DEG = 1e6
MIN_ABS_SWEEP_DEG = 1e-6
MAX_SHAPES = 128


def profile_definition() -> dict:
    """! @brief 원본이나 공유 상수를 변경할 수 없는 새 profile 설명을 반환한다."""
    return {
        "step_schema": "AP242",
        "end_cap": "round",
        "curve_representation": "analytic",
        "merge_policy": "same_layer_same_nonnull_net_material",
        "max_coordinate_mm": MAX_COORDINATE_MM,
        "max_abs_angle_deg": MAX_START_ANGLE_DEG,
        "min_abs_sweep_deg": MIN_ABS_SWEEP_DEG,
        "min_feature_mm": MIN_FEATURE_MM,
        "max_shapes": MAX_SHAPES,
        "tolerance_mm": TOLERANCE_MM,
        "region_boundary": "straight_segments_with_explicit_holes",
        "pad_shapes": ["circle", "rectangle"],
        "via_model": "through_plated_hollow_barrel_with_explicit_pads",
    }


def _fail(code: str, message: str, field: str) -> None:
    """! @brief 원본 입력 위치를 보존한 CAD 접수 차단 사유를 전달한다."""
    raise ProjectError(code, message, details={"field_path": field})


def _check_snapshot(document: dict, snapshot: dict) -> None:
    """! @brief 서로 다른 개정 또는 내용의 스냅샷을 CAD 입력에 결합하지 않는다."""
    required = {"snapshot_id", "project_id", "revision_id", "schema_version", "canonical_version", "content_hash"}
    if type(snapshot) is not dict or not required <= snapshot.keys():
        _fail("E_SCHEMA", "CAD 입력에 봉인된 SnapshotRef가 필요합니다.", "snapshot")
    try:
        if type(snapshot["snapshot_id"]) is not str or str(UUID(snapshot["snapshot_id"])) != snapshot["snapshot_id"]:
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        _fail("E_SCHEMA", "스냅샷 식별자는 정규 UUID여야 합니다.", "snapshot.snapshot_id")
    if snapshot["snapshot_id"] in (document["project_id"], document["revision_id"]):
        _fail("E_SCHEMA", "스냅샷 식별자는 프로젝트/개정 식별자와 달라야 합니다.", "snapshot.snapshot_id")
    for key in ("project_id", "revision_id", "schema_version"):
        if snapshot[key] != document[key]:
            _fail("E_CONFLICT", "스냅샷과 CAD 원본의 식별자 또는 버전이 다릅니다.", "snapshot." + key)
    if snapshot["canonical_version"] != CANONICAL_VERSION:
        _fail("E_VERSION", "지원하지 않는 스냅샷 정규 직렬화 버전입니다.", "snapshot.canonical_version")
    if snapshot["content_hash"] != canonical_hash(document):
        _fail("E_HASH", "스냅샷 내용 해시와 CAD 원본이 일치하지 않습니다.", "snapshot.content_hash")


def _scalar(document: dict, value: dict, dimension: str, unit: str, field: str) -> float:
    """! @brief 미정 수량을 대신 채우지 않고 참조를 해석하여 출력 단위로 변환한다."""
    quantity = resolve_scalar(document, value, dimension, field)
    if quantity.value_si is None:
        _fail("E_GEOMETRY", "CAD 형상에 필요한 치수 또는 층 위치가 미정입니다.", field)
    try:
        result = quantity.as_unit(unit)
    except QuantityError as error:
        _fail("E_UNIT", "CAD 출력 단위로 변환할 수 없습니다: " + str(error), field)
    if not math.isfinite(result):
        _fail("E_UNIT", "CAD 입력은 유한한 수치여야 합니다.", field)
    return result


def _length(document: dict, value: dict, field: str, *, positive: bool = False) -> float:
    """! @brief kernel의 수치 허용오차보다 충분히 큰 길이만 이 profile에서 소비한다."""
    result = _scalar(document, value, "length", "mm", field)
    if abs(result) > MAX_COORDINATE_MM:
        _fail("E_GEOMETRY", "CAD profile의 좌표/치수 상한을 초과했습니다.", field)
    if positive and result < MIN_FEATURE_MM:
        _fail("E_GEOMETRY", "CAD profile의 최소 형상 치수보다 작습니다.", field)
    return result


def _point(document: dict, values: list[dict], field: str) -> list[float]:
    """! @brief x/y 평면 좌표를 mm로 읽으며 원본 참조와 표시 단위를 보존한다."""
    return [_length(document, value, f"{field}[{index}]") for index, value in enumerate(values)]


def _check_frame(document: dict, frame_id: str, field: str) -> None:
    """! @brief 현재 항등 world/board 좌표계 이외의 암묵적 변환을 차단한다."""
    frames = document["frames"]
    known = {frame["id"] for frame in frames.values()}
    if frame_id not in known:
        _fail("E_UNSUPPORTED", "현재 CAD profile은 항등 world/board 좌표계만 지원합니다.", field)
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    if any(frame["translation_si"] != [0.0, 0.0, 0.0] or frame["rotation"] != identity or frame["handedness"] != "right" for frame in frames.values()):
        _fail("E_UNSUPPORTED", "CAD 출력에 미지원 좌표계 변환을 적용할 수 없습니다.", field)


def build_cad_input(document: dict, snapshot_ref: dict, profile: str = PROFILE) -> dict:
    """! @brief 저장 원본과 분리된 mm/deg CAD worker 입력을 만든다.

    @param document snapshot artifact에서 읽어 해시를 확인할 원본 문서.
    @param snapshot_ref 서비스가 소유하고 검증한 봉인 스냅샷 참조.
    @param profile 현재 지원하는 기계 형상 전용 STEP profile 식별자.
    @return native 모듈이나 경로 실행 명령을 포함하지 않는 새 JSON 입력.
    @throws ProjectError 단위/개정/해시 불일치, 미정 필수 치수 또는 미지원 형상.
    @details 원본 불변성은 여기서도 유지한다. native worker는 이 입력의 해시를
    확인한 뒤 따로 실행한다. RF 물성, 제작 및 측정 조건을 자동 확정하지 않는다.
    """
    if type(profile) is not str or profile != PROFILE:
        _fail("E_UNSUPPORTED", "지원하지 않는 CAD/STEP profile입니다.", "profile")
    validate_project(document)
    _check_snapshot(document, snapshot_ref)
    board = document["board"]
    if board is None:
        _fail("E_GEOMETRY", "CAD 출력에는 명시적 기판 외형이 필요합니다.", "board")
    _check_frame(document, board["frame_id"], "board.frame_id")
    outline = board["outline"]
    if outline["kind"] == "circle":
        projected_board = {"id": board["id"], "kind": "circle",
                           "center_mm": _point(document, outline["center"], "board.outline.center"),
                           "radius_mm": _length(document, outline["radius"], "board.outline.radius", positive=True)}
        if any(abs(coordinate) + projected_board["radius_mm"] > MAX_COORDINATE_MM for coordinate in projected_board["center_mm"]):
            _fail("E_GEOMETRY", "원형 기판 외곽이 CAD 좌표 상한을 벗어났습니다.", "board.outline")
    else:
        projected_board = {"id": board["id"],
                           "width_mm": _length(document, outline["width"], "board.outline.width", positive=True),
                           "height_mm": _length(document, outline["height"], "board.outline.height", positive=True)}
    result = {
        "schema": INPUT_SCHEMA,
        "profile": PROFILE,
        "profile_definition": profile_definition(),
        "project_id": document["project_id"],
        "revision_id": document["revision_id"],
        "source_hash": snapshot_ref["content_hash"],
        "snapshot": deepcopy(snapshot_ref),
        "unit": "mm",
        "angle_unit": "deg",
        "tolerance_mm": TOLERANCE_MM,
        "transform": {
            "source_length_unit": "m", "kernel_length_unit": "mm",
            "scale_to_kernel": 1000.0, "inverse_scale": 0.001,
            "source_frame_id": board["frame_id"], "handedness": "right",
            "translation_mm": [0.0, 0.0, 0.0],
            "rotation": deepcopy(document["frames"]["board"]["rotation"]),
        },
        "board": projected_board,
        "layers": [], "shapes": [], "omissions": [],
        "source_semantics": deepcopy(document),
    }
    for layer in document["stackup"]:
        field = "stackup." + layer["id"]
        if layer["role"] not in ("dielectric", "conductor"):
            _fail("E_UNSUPPORTED", "coverage가 정의되지 않은 coating/adhesive/air 층은 현재 CAD profile에서 지원하지 않습니다.", field + ".role")
        lower = _length(document, layer["z_min"], field + ".z_min")
        thickness = _length(document, layer["thickness"], field + ".thickness", positive=True)
        upper = lower + thickness
        if abs(upper) > MAX_COORDINATE_MM or upper <= lower:
            _fail("E_GEOMETRY", "CAD profile에서 층 상부 위치를 표현할 수 없습니다.", field)
        if result["layers"]:
            previous = result["layers"][-1]
            previous_upper = previous["z_min_mm"] + previous["thickness_mm"]
            arithmetic_tolerance = 8 * max(math.ulp(previous_upper), math.ulp(lower))
            if lower < previous_upper - arithmetic_tolerance:
                _fail("E_GEOMETRY", "CAD 층의 부피가 겹치거나 z 순서가 다릅니다.", field)
            gap = lower - previous_upper
            if arithmetic_tolerance < gap < MIN_FEATURE_MM:
                _fail("E_GEOMETRY", "층 사이 간격이 CAD 최소 형상 치수보다 작습니다.", field + ".z_min")
        result["layers"].append({
            "id": layer["id"], "name": layer["name"], "role": layer["role"],
            "order": layer["order"], "z_min_mm": lower, "thickness_mm": thickness,
            "material_id": layer["material_id"],
        })
    if not any(layer["role"] == "dielectric" for layer in result["layers"]):
        _fail("E_GEOMETRY", "CAD 기판에는 실제 위치와 두께를 입력한 유전체 층이 하나 이상 필요합니다.", "stackup")
    for geometry in document["geometry"]:
        if not geometry["include_in_export"]:
            result["omissions"].append({"id": geometry["id"], "reason": "include_in_export=false"})
            continue
        if len(result["shapes"]) >= MAX_SHAPES:
            _fail("E_RESOURCE", "CAD profile의 최대 형상 수를 초과했습니다.", "geometry")
        field = "geometry." + geometry["id"]
        _check_frame(document, geometry["frame_id"], field + ".frame_id")
        shape = {key: deepcopy(geometry[key]) for key in ("id", "kind", "layer_id", "net_id", "role", "frame_id", "material_ref", "source_ref")}
        if geometry["kind"] in ("line_path", "arc_path"):
            shape["width_mm"] = _length(document, geometry["width"], field + ".width", positive=True)
        if geometry["kind"] == "line_path":
            shape["start_mm"] = _point(document, geometry["start"], field + ".start")
            shape["end_mm"] = _point(document, geometry["end"], field + ".end")
            if math.dist(shape["start_mm"], shape["end_mm"]) < MIN_FEATURE_MM:
                _fail("E_GEOMETRY", "선 중심선 길이가 CAD 최소 형상 치수보다 작습니다.", field)
        elif geometry["kind"] == "arc_path":
            shape["center_mm"] = _point(document, geometry["center"], field + ".center")
            shape["radius_mm"] = _length(document, geometry["radius"], field + ".radius", positive=True)
            shape["start_angle_deg"] = _scalar(document, geometry["start_angle"], "angle", "deg", field + ".start_angle")
            shape["sweep_angle_deg"] = _scalar(document, geometry["sweep_angle"], "angle", "deg", field + ".sweep_angle")
            if abs(shape["start_angle_deg"]) > MAX_START_ANGLE_DEG:
                _fail("E_GEOMETRY", "시작 각도가 CAD profile의 안정적인 삼각함수 평가 범위를 벗어났습니다.", field + ".start_angle")
            if abs(shape["sweep_angle_deg"]) < MIN_ABS_SWEEP_DEG:
                _fail("E_GEOMETRY", "원호 회전량이 CAD profile의 최소 각도보다 작습니다.", field + ".sweep_angle")
            if shape["radius_mm"] - shape["width_mm"] / 2.0 < MIN_FEATURE_MM:
                _fail("E_GEOMETRY", "원호의 내부 반지름이 CAD 최소 형상 치수보다 작습니다.", field + ".width")
            if shape["radius_mm"] * math.radians(abs(shape["sweep_angle_deg"])) < MIN_FEATURE_MM:
                _fail("E_GEOMETRY", "원호 중심선 길이가 CAD 최소 형상 치수보다 작습니다.", field + ".sweep_angle")
        elif geometry["kind"] == "planar_region":
            shape["outer_mm"] = [_point(document, point, field + f".outer[{index}]") for index, point in enumerate(geometry["outer"])]
            shape["holes_mm"] = [[_point(document, point, field + f".holes[{hole_index}][{index}]")
                                   for index, point in enumerate(hole)] for hole_index, hole in enumerate(geometry["holes"])]
            for loop in [shape["outer_mm"], *shape["holes_mm"]]:
                if any(math.dist(a, b) < MIN_FEATURE_MM for a, b in zip(loop, loop[1:] + loop[:1])):
                    _fail("E_GEOMETRY", "영역 경계의 변 길이가 CAD 최소 형상 치수보다 작습니다.", field)
        elif geometry["kind"] == "pad":
            shape.update(pad_shape=geometry["pad_shape"], center_mm=_point(document, geometry["center"], field + ".center"),
                         size_mm=[_length(document, value, field + f".size[{index}]", positive=True) for index, value in enumerate(geometry["size"])],
                         rotation_deg=_scalar(document, geometry["rotation"], "angle", "deg", field + ".rotation"))
            if abs(shape["rotation_deg"]) > MAX_START_ANGLE_DEG:
                _fail("E_GEOMETRY", "패드 회전이 CAD의 안정적인 각도 범위를 벗어났습니다.", field + ".rotation")
        elif geometry["kind"] == "via":
            shape.update(center_mm=_point(document, geometry["center"], field + ".center"), end_layer_id=geometry["end_layer_id"],
                         finished_hole_diameter_mm=_length(document, geometry["finished_hole_diameter"], field + ".finished_hole_diameter", positive=True),
                         plating_thickness_mm=_length(document, geometry["plating_thickness"], field + ".plating_thickness", positive=True),
                         fill=geometry["fill"], pad_ids=deepcopy(geometry["pad_ids"]))
            tool = resolve_scalar(document, geometry["tool_hole_diameter"], "length", field + ".tool_hole_diameter")
            shape["tool_hole_diameter_mm"] = None if tool.value_si is None else _length(document, geometry["tool_hole_diameter"], field + ".tool_hole_diameter", positive=True)
            derived = shape["finished_hole_diameter_mm"] + 2 * shape["plating_thickness_mm"]
            if shape["tool_hole_diameter_mm"] is not None and not math.isclose(shape["tool_hole_diameter_mm"], derived, rel_tol=0, abs_tol=TOLERANCE_MM):
                _fail("E_UNSUPPORTED", "초기 CAD 비아는 tool bore = finished bore + 2 * plating 조건만 지원합니다.", field + ".tool_hole_diameter")
            if len(shape["pad_ids"]) < 2 or geometry["net_id"] is None:
                _fail("E_CONNECTIVITY", "관통 비아에는 명시적 net과 양 끝의 pad 참조가 필요합니다.", field)
        else:
            _fail("E_UNSUPPORTED", "현재 CAD profile이 지원하지 않는 도체 형상입니다.", field + ".kind")
        result["shapes"].append(shape)
    return result
