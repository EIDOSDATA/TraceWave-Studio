"""! @brief 사용자가 완전히 명시한 평면 gap 포트만 템플릿 후보에 연결한다."""

from copy import deepcopy
import math

from rfad.domain.design import _fail, _fields, _text, resolve_scalar
from rfad.domain.planar import point_in_loop
from rfad.domain.layer_surface import single_dielectric_contact
from rfad.domain.template_geometry import literal, object_id
from rfad.templates.cards import IFA
from rfad.templates.g031 import IDENTITY as G031


def _point(document, value, field):
    """! @brief 포트 끝점은 명시적 세 길이 Quantity만 허용한다."""
    if type(value) is not list or len(value) != 3:
        _fail("E_SCHEMA", "급전 끝점에는 길이 수량 3개가 필요합니다.", field)
    return [literal(document, item, "length", field + f"[{index}]") for index, item in enumerate(value)]


def _inside(document, shape, point, *, boundary=False):
    """! @brief 지원하는 평면 도체에 포트 끝점이 실제 포함되는지 확인한다."""
    def value(item):
        """! @brief 이미 검사한 좌표를 SI로 해석한다."""
        number = resolve_scalar(document, item, "length", "port.geometry").value_si
        if number is None:
            _fail("E_PORT", "포트가 연결될 도체 치수가 미정입니다.", "port.reference_geometry_id")
        return number
    if shape["kind"] == "planar_region":
        loop = [[value(item) for item in vertex] for vertex in shape["outer"]]
        return point_in_loop(point, loop) and not any(point_in_loop(point, [[value(item) for item in vertex] for vertex in hole]) for hole in shape["holes"])
    if shape["kind"] == "line_path":
        a, b = ([value(item) for item in shape[key]] for key in ("start", "end"))
        delta = [b[index] - a[index] for index in (0, 1)]
        denominator = sum(item * item for item in delta)
        fraction = max(0.0, min(1.0, sum((point[index] - a[index]) * delta[index] for index in (0, 1)) / denominator))
        distance = math.hypot(*(point[index] - a[index] - fraction * delta[index] for index in (0, 1)))
        radius = value(shape["width"]) / 2
        if boundary:
            return math.isclose(distance, radius, rel_tol=0, abs_tol=1e-9)
        return distance <= radius + 1e-12
    if shape["kind"] == "pad":
        center = [value(item) for item in shape["center"]]
        size = [value(item) for item in shape["size"]]
        rotation = resolve_scalar(document, shape["rotation"], "angle", "port.geometry.rotation").value_si
        if rotation is None:
            _fail("E_PORT", "포트 패드의 회전각이 미정입니다.", "port.reference_geometry_id")
        dx, dy = point[0] - center[0], point[1] - center[1]
        local = [dx * math.cos(rotation) + dy * math.sin(rotation), -dx * math.sin(rotation) + dy * math.cos(rotation)]
        if shape["pad_shape"] == "circle":
            return sum((2 * local[index] / size[index]) ** 2 for index in (0, 1)) <= 1 + 1e-12
        return all(abs(local[index]) <= size[index] / 2 + 1e-12 for index in (0, 1))
    _fail("E_UNSUPPORTED", "첫 템플릿 포트의 기준 도체는 면/선/패드여야 합니다.", "port.reference_geometry_id")


def generate_port(document: dict, additions: dict, instance_id: str, binding: dict, card: dict, recipe: object) -> None:
    """! @brief 포트 생성을 명시한 경우만 연결하고 누락을 50 ohm 등으로 보완하지 않는다."""
    if recipe is None:
        return
    if card["template_id"] == G031:
        _fail("E_UNSUPPORTED", "G031 부분 기하 카드는 port:null만 지원합니다. 급전은 생성 후 별도로 검토하십시오.", "port")
    _fields(recipe, {"reference_geometry_id", "resistance", "reference_plane", "polarity", "direction", "validity_hz", "excitation_box"}, "port")
    if document["ports"]:
        _fail("E_UNSUPPORTED", "첫 템플릿 급전은 기존 포트가 없는 단일 포트 프로젝트만 지원합니다.", "ports")
    direction = recipe["direction"]
    if (recipe["polarity"] != 1 or type(recipe["polarity"]) is not int or type(direction) is not list
            or any(type(value) not in (int, float) for value in direction) or direction not in ([1, 0, 0], [0, 1, 0])):
        _fail("E_PORT", "첫 템플릿 급전은 +x 또는 +y의 명시적 단일 gap을 지원합니다.", "port.direction")
    _text(recipe["reference_plane"], "port.reference_plane")
    if literal(document, recipe["resistance"], "impedance", "port.resistance") <= 0:
        _fail("E_PORT", "물리 포트 저항을 양수로 지정하십시오.", "port.resistance")
    _fields(recipe["validity_hz"], {"min", "max"}, "port.validity_hz")
    low, high = (literal(document, recipe["validity_hz"][key], "frequency", "port.validity_hz." + key) for key in ("min", "max"))
    if not 0 < low < high:
        _fail("E_PORT", "물리 포트의 양수 유효 대역이 필요합니다.", "port.validity_hz")
    _fields(recipe["excitation_box"], {"start", "stop"}, "port.excitation_box")
    start, stop = (_point(document, recipe["excitation_box"][key], "port.excitation_box." + key) for key in ("start", "stop"))
    axis = recipe["direction"].index(1)
    if stop[axis] <= start[axis] or any(start[index] != stop[index] for index in range(3) if index != axis):
        _fail("E_PORT", "급전 방향의 양의 1차원 gap이 필요합니다.", "port.excitation_box")
    probe = deepcopy(document)
    probe["parameters"].update(additions["parameters"])
    probe["geometry"].extend(additions["geometry"])
    if card["template_id"] == IFA:
        if recipe["reference_geometry_id"] is not None:
            _fail("E_PORT", "IFA recipe는 생성된 ground를 사용하므로 reference_geometry_id는 null이어야 합니다.", "port.reference_geometry_id")
        reference_id, positive_id = object_id(instance_id, "ground"), object_id(instance_id, "pad")
    else:
        reference_id, positive_id = recipe["reference_geometry_id"], object_id(instance_id, "feed")
    shapes = {item["id"]: item for item in probe["geometry"]}
    if type(reference_id) is not str or reference_id not in shapes or shapes[reference_id]["role"] != "ground":
        _fail("E_PORT", "원호 급전에 연결할 기존 ground를 명시하십시오.", "port.reference_geometry_id")
    reference, positive = shapes[reference_id], shapes[positive_id]
    if reference["layer_id"] != binding["layer_id"]:
        _fail("E_UNSUPPORTED", "첫 템플릿 급전은 같은 도체 층의 gap만 지원합니다.", "port.reference_geometry_id")
    layer = next(item for item in document["stackup"] if item["id"] == binding["layer_id"])
    def interval(source):
        """! @brief 물성을 소비하지 않고 명시된 층 구간만 읽는다."""
        values = [resolve_scalar(document, source[key], "length", "stackup." + key).value_si for key in ("z_min", "thickness")]
        if None in values:
            _fail("E_PORT", "명시 포트에는 인접 적층의 높이/두께가 필요합니다.", "port.excitation_box")
        return values
    lower, thickness = interval(layer)
    dielectrics = [interval(item) for item in document["stackup"] if item["role"] == "dielectric"]
    z = single_dielectric_contact(lower, thickness, dielectrics, tolerance=1e-11, field="port.excitation_box")
    if not math.isclose(start[2], z, abs_tol=1e-11):
        _fail("E_PORT", "도체/유전체 접면과 명시 급전 높이가 같아야 합니다.", "port.excitation_box")
    if not _inside(probe, reference, start[:2], boundary=True) or not _inside(probe, positive, stop[:2], boundary=True):
        _fail("E_PORT", "급전 gap의 시작/끝이 기준 도체와 생성 급전 도체에 연결되지 않습니다.", "port.excitation_box")
    if _inside(probe, positive, start[:2]) or _inside(probe, reference, stop[:2]):
        _fail("E_PORT", "급전 gap이 두 도체에 동시에 닿습니다.", "port.excitation_box")
    additions["ports"] = [{"id": object_id(instance_id, "port"), "name": "template port " + instance_id, "kind": "lumped",
                           "positive_geometry_id": positive_id, "reference_geometry_id": reference_id,
                           **{key: deepcopy(recipe[key]) for key in recipe if key != "reference_geometry_id"}}]
