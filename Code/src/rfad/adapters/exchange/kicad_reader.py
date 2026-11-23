"""! @brief writer와 독립된 S 식 읽기 경로로 실제 KiCad 객체/층/net을 복원한다."""
import math
from copy import deepcopy

from rfad.domain.errors import ProjectError
from rfad.adapters.exchange.sexpr import Atom, parse, children, one, number


def _integer(value):
    """! @brief net/층의 소수 코드를 잘라 서로 다른 객체를 병합하지 않는다."""
    result=number(value)
    if result!=int(result) or not 0<=result<=2147483647:
        raise ProjectError("E_SCHEMA","KiCad net/층 코드는 유한 비음수 정수여야 합니다.")
    return int(result)


def _value(node, key, default=None):
    """! @brief 선택 필드 누락과 실제 값을 구분한다."""
    value = one(node, key, False)
    return default if value is None else str(value[1])


def _point(node, key, placement=None):
    """! @brief KiCad Y 방향과 footprint 상대좌표를 world mm로 복원한다."""
    value = one(node, key)
    if len(value) < 3:
        raise ProjectError("E_SCHEMA", "KiCad 좌표에 두 성분이 필요합니다.")
    x, y = number(value[1]), -number(value[2])
    if placement is None:
        return [x, y]
    angle = math.radians(placement["rotation_deg"])
    return [placement["origin_mm"][0] + x * math.cos(angle) - y * math.sin(angle), placement["origin_mm"][1] + x * math.sin(angle) + y * math.cos(angle)]


def _scalar(node, key, default=None):
    """! @brief 입력 단위 mm의 수치를 추정 없이 읽는다."""
    field = one(node, key, default is None)
    return default if field is None else number(field[1])


def _points(node, placement=None):
    """! @brief 직선 polygon 꼭짓점의 유한 목록을 읽는다."""
    result = []
    for point in one(node, "pts")[1:]:
        if type(point) is not list or point[0] != "xy" or len(point) != 3:
            raise ProjectError("E_UNSUPPORTED", "곡선 polygon contour는 이 KiCad 읽기 profile 밖입니다.")
        result.append(_point(["point", point], "xy", placement))
    if not 3 <= len(result) <= 32768:
        raise ProjectError("E_RESOURCE", "KiCad polygon 꼭짓점 수가 상한을 벗어났습니다.")
    return result


def _identity(node):
    """! @brief 구형 tstamp와 새 uuid를 모두 읽고 두 값의 충돌은 거절한다."""
    a, b = _value(node, "uuid"), _value(node, "tstamp")
    if a is not None and b is not None and a != b:
        raise ProjectError("E_SCHEMA", "KiCad 객체 ID가 충돌합니다.")
    return a if a is not None else b


def _base(node, nets):
    """! @brief 원문 ID와 실제 net 코드를 누락 상태 그대로 읽는다."""
    net = one(node, "net", False)
    if net is None:
        code=0
    elif type(net[1]) is str:
        code=next((identity for identity,name in nets.items() if name==net[1]),0)
        if net[1] and not code:
            raise ProjectError("E_CONNECTIVITY","KiCad 10 net 이름이 등록되지 않았습니다.")
    else:
        code=_integer(net[1])
    if code and code not in nets:
        raise ProjectError("E_CONNECTIVITY", "KiCad 객체의 net 코드가 정의되지 않았습니다.")
    return {"id": _identity(node), "layer": _value(node, "layer"), "net_code": code, "net_name": nets.get(code)}


def _arc(node, placement=None):
    """! @brief 세 점의 외접원과 진행 방향으로 원호를 독립 복원한다."""
    a, m, b = [_point(node, key, placement) for key in ("start", "mid", "end")]
    d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if abs(d) < 1e-18:
        raise ProjectError("E_GEOMETRY", "KiCad 원호의 세 점이 같은 직선 위에 있습니다.")
    aa, mm, bb = sum(v*v for v in a), sum(v*v for v in m), sum(v*v for v in b)
    center = [(aa*(m[1]-b[1]) + mm*(b[1]-a[1]) + bb*(a[1]-m[1]))/d, (aa*(b[0]-m[0]) + mm*(a[0]-b[0]) + bb*(m[0]-a[0]))/d]
    start, mid, end = [math.degrees(math.atan2(p[1]-center[1], p[0]-center[0])) % 360 for p in (a,m,b)]
    sweep = (end-start) % 360
    if (mid-start) % 360 > sweep:
        sweep -= 360
    return {"center_mm": center, "radius_mm": math.dist(center, a), "start_angle_deg": start, "sweep_angle_deg": sweep, "start_mm": a, "mid_mm": m, "end_mm": b}


def _read_pad(node, nets, placement, owner):
    """! @brief 실제 드릴의 완성 치수와 패드 층 목록을 각각 읽는다."""
    result = _base(node, nets)
    if len(node) < 4:
        raise ProjectError("E_SCHEMA", "KiCad 패드 헤더가 누락되었습니다.")
    kind, shape = str(node[2]), str(node[3])
    if kind not in ("smd", "thru_hole", "np_thru_hole", "connect") or shape not in ("circle", "rect", "oval"):
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 KiCad 패드 형식입니다: " + kind + "/" + shape)
    at, size = one(node, "at"), one(node, "size")
    angle = (number(at[3]) if len(at) > 3 else 0)
    result.update(kind="pad", pad_type=kind, pad_shape=shape, number=str(node[1]), center_mm=_point(node, "at", placement), size_mm=[number(size[1]),number(size[2])], rotation_deg=angle, layers=[str(item) for item in one(node,"layers")[1:]], footprint_id=owner, drill=None)
    stack = one(node, "padstack", False)
    if stack is not None:
        mode = one(stack, "mode")
        if kind != "thru_hole" or mode != ["mode", "custom"]:
            raise ProjectError("E_UNSUPPORTED", "원형 관통 드릴의 층별 custom padstack을 선택하세요.")
        by_layer = {}
        for row in stack[1:]:
            if row[0] == "mode":
                continue
            if row[0] != "layer" or len(row) != 4 or row[1] in by_layer or not row[1].endswith(".Cu"):
                raise ProjectError("E_UNSUPPORTED", "패드스택의 층 또는 추가 형상 규칙을 확인하세요.")
            shape_row, size_row = one(row, "shape"), one(row, "size")
            if (len(shape_row) != 2 or len(size_row) != 3 or shape_row[1] not in ("circle", "rect")
                    or any(number(value) <= 0 for value in size_row[1:])):
                raise ProjectError("E_UNSUPPORTED", "층별 랜드는 양의 원형 및 사각형만 지원합니다.")
            by_layer[row[1]] = {"pad_shape": shape_row[1], "size_mm": list(map(number, size_row[1:]))}
        result["padstack_layers"] = by_layer
    drill = one(node, "drill", False)
    if drill is not None:
        oval = drill[1] == "oval"
        values = drill[2:] if oval else drill[1:]
        scalar = [number(item) for item in values if type(item) is not list]
        if len(scalar) != (2 if oval else 1) or any(value <= 0 for value in scalar):
            raise ProjectError("E_SCHEMA", "KiCad drill 치수가 유효하지 않습니다.")
        offset = one(drill, "offset", False)
        result["drill"] = {"shape":"capsule" if oval else "circle", "size_mm": scalar if oval else scalar*2, "offset_mm":[0,0] if offset is None else [number(offset[1]),-number(offset[2])], "plating":"unplated" if kind=="np_thru_hole" else "plated", "tool_diameter_mm":None}
    for key in ("solder_mask_margin", "solder_paste_margin", "solder_paste_margin_ratio"):
        result[key] = _scalar(node, key, default=None) if one(node, key, False) is not None else None
    return result


def _unconsumed(node, allowed, result):
    """! @brief 소비하지 않은 객체별 규칙을 원문 보존 손실 목록에 명시한다."""
    for child in node[1:]:
        if type(child) is list and child and str(child[0]) not in allowed:
            result["losses"].append({"code":"unsupported_object_field","token":str(child[0]),"owner":_identity(node),"raw_preserved":True})


def read(raw):
    """! @brief 선언 subset의 실제 편집 객체와 누락/미지원 원문 목록을 돌려준다."""
    tree = parse(raw)
    if tree[0] not in ("kicad_pcb", "footprint"):
        raise ProjectError("E_UNSUPPORTED", "KiCad board 또는 footprint 원문이 아닙니다.")
    is_board = tree[0] == "kicad_pcb"
    nets = {0: None}
    for node in children(tree,"net"):
        if len(node)<3 or type(node[1]) is str:
            continue
        code = _integer(node[1])
        if code in nets and code != 0:
            raise ProjectError("E_SCHEMA", "KiCad net 코드가 중복됩니다.")
        nets[code] = str(node[2]) or None
    pending=[tree]
    while pending:
        node=pending.pop()
        if node and node[0]=="net" and len(node)==2 and type(node[1]) is str and node[1] and node[1] not in nets.values():
            nets[max(nets)+1]=node[1]
        pending.extend(item for item in node[1:] if type(item) is list)
    layers = []
    if is_board:
        for node in one(tree,"layers")[1:]:
            if type(node) is not list or len(node) < 3:
                raise ProjectError("E_SCHEMA", "KiCad 층 정의가 유효하지 않습니다.")
            layers.append({"ordinal":_integer(node[0]), "name":str(node[1]), "type":str(node[2]), "user_name":str(node[3]) if len(node)>3 else None})
    result = {"schema":"rfad.kicad-read/0.1", "format":"kicad_pcb" if is_board else "kicad_mod", "version":_value(tree,"version"), "layers":layers, "nets":[{"code":code,"name":name} for code,name in nets.items()], "shapes":[], "edges":[], "footprints":[], "keepouts":[], "artwork":[], "stackup":[], "losses":[], "physical_material_defaults_authoritative":False}
    setup = one(tree,"setup",False)
    stackup = None if setup is None else one(setup,"stackup",False)
    if stackup is not None:
        for layer in children(stackup,"layer"):
            result["stackup"].append({"name":str(layer[1]), "type":_value(layer,"type"), "thickness_mm":_scalar(layer,"thickness",default=0) if one(layer,"thickness",False) else None, "material":_value(layer,"material"), "epsilon_r":_scalar(layer,"epsilon_r",default=0) if one(layer,"epsilon_r",False) else None, "loss_tangent":_scalar(layer,"loss_tangent",default=0) if one(layer,"loss_tangent",False) else None})
    if not is_board:
        properties={str(item[1]):str(item[2]) for item in children(tree,"property")}
        result["footprints"].append({"id":_identity(tree),"library_id":str(tree[1]),"placement":{"origin_mm":[0,0],"rotation_deg":0,"side":"bottom" if _value(tree,"layer")=="B.Cu" else "top"},"properties":properties,"attributes":[str(value) for value in (one(tree,"attr",False) or [])[1:]],"technical_container":properties.get("TraceWaveContainer")=="true"})
    queue = [(tree,None,None)] if is_board else [(tree,{"origin_mm":[0,0],"rotation_deg":0},_identity(tree))]
    while queue:
        parent, placement, owner = queue.pop(0)
        for node in parent[1:]:
            if type(node) is not list:
                continue
            kind = str(node[0])
            if kind == "footprint":
                at = one(node,"at",False)
                place = {"origin_mm":[0,0] if at is None else _point(node,"at"), "rotation_deg":0 if at is None or len(at)<4 else number(at[3]), "side":"bottom" if _value(node,"layer")=="B.Cu" else "top"}
                properties = {str(item[1]):str(item[2]) for item in children(node,"property")}
                result["footprints"].append({"id":_identity(node),"library_id":str(node[1]),"placement":place,"properties":properties,"attributes":[str(value) for value in (one(node,"attr",False) or [])[1:]],"technical_container":properties.get("TraceWaveContainer")=="true"})
                queue.append((node,place,_identity(node)))
            elif kind in ("segment","arc"):
                _unconsumed(node,{"start","mid","end","width","layer","net","uuid","tstamp"},result)
                item = _base(node,nets)
                item.update(kind="line_path" if kind=="segment" else "arc_path",width_mm=_scalar(node,"width"))
                item.update({"start_mm":_point(node,"start",placement),"end_mm":_point(node,"end",placement)} if kind=="segment" else _arc(node,placement))
                result["shapes"].append(item)
            elif kind == "via":
                _unconsumed(node,{"at","size","drill","layers","net","uuid","tstamp"},result)
                item = _base(node,nets)
                item.update(kind="via",center_mm=_point(node,"at"),size_mm=_scalar(node,"size"),finished_hole_diameter_mm=_scalar(node,"drill"),layers=[str(value) for value in one(node,"layers")[1:]],tool_diameter_mm=None)
                result["shapes"].append(item)
            elif kind == "pad":
                _unconsumed(node,{"at","size","layers","net","drill","uuid","tstamp","solder_mask_margin","solder_paste_margin","solder_paste_margin_ratio","padstack"},result)
                result["shapes"].append(_read_pad(node,nets,placement,owner))
            elif kind == "zone":
                _unconsumed(node,{"polygon","filled_polygon","layer","net","uuid","tstamp","name","hatch","connect_pads","min_thickness","fill","keepout"},result)
                polygons = [_points(poly,placement) for poly in children(node,"polygon")]
                if not polygons:
                    raise ProjectError("E_SCHEMA", "KiCad zone 경계가 없습니다.")
                item = _base(node,nets)
                item.update(kind="planar_region",outer_mm=polygons[0],holes_mm=polygons[1:],filled_polygons_mm=[_points(poly,placement) for poly in children(node,"filled_polygon")],footprint_id=owner)
                keepout = one(node,"keepout",False)
                if keepout is not None:
                    item["prohibit"] = {str(value[0]):str(value[1])=="not_allowed" for value in keepout[1:]}
                    result["keepouts"].append(item)
                else:
                    connection=one(node,"connect_pads",False)
                    fill=one(node,"fill",False)
                    item["fill_settings"]={"connect_pads":None if connection is None or len(connection)<2 or type(connection[1]) is list else str(connection[1]),"clearance_mm":None if connection is None else _scalar(connection,"clearance",default=0),"minimum_thickness_mm":_scalar(node,"min_thickness",default=0),"island_removal_mode":None if fill is None else _value(fill,"island_removal_mode"),"thermal_gap_mm":None if fill is None else _scalar(fill,"thermal_gap",default=0)}
                    result["shapes"].append(item)
            elif kind in ("gr_line","gr_arc","gr_circle","gr_rect","gr_poly","fp_line","fp_arc","fp_circle","fp_rect","fp_poly"):
                _unconsumed(node,{"start","mid","end","center","pts","stroke","width","fill","layer","uuid","tstamp"},result)
                item = {"id":_identity(node),"kind":kind.split("_")[1],"layer":_value(node,"layer"),"footprint_id":owner}
                stroke=one(node,"stroke",False)
                item["width_mm"]=_scalar(stroke,"width",default=0) if stroke is not None else _scalar(node,"width",default=0)
                item["fill"]=_value(node,"fill","none")
                if item["kind"]=="arc":
                    item.update(_arc(node,placement))
                elif item["kind"]=="circle":
                    item.update(center_mm=_point(node,"center",placement),radius_mm=math.dist(_point(node,"center",placement),_point(node,"end",placement)))
                elif item["kind"]=="poly":
                    item["outer_mm"]=_points(node,placement)
                else:
                    item.update(start_mm=_point(node,"start",placement),end_mm=_point(node,"end",placement))
                    if item["kind"]=="rect":
                        start,end=one(node,"start"),one(node,"end")
                        item["outer_mm"]=[_point(["p",["xy",x,y]],"xy",placement) for x,y in ((start[1],start[2]),(end[1],start[2]),(end[1],end[2]),(start[1],end[2]))]
                if item["layer"]=="Edge.Cuts":
                    result["edges"].append(item)
                elif item["layer"] in ("F.Mask","B.Mask","F.Paste","B.Paste","F.CrtYd","B.CrtYd"):
                    result["artwork"].append(item)
                else:
                    result["losses"].append({"code":"unsupported_graphic_layer","id":item["id"],"layer":item["layer"],"raw_preserved":True})
            elif kind not in {"version","generator","generator_version","general","paper","title_block","layers","setup","net","property","at","layer","uuid","tstamp","attr","descr","tags","path","sheetname","sheetfile","tedit","embedded_fonts","locked","autoplace_cost90","autoplace_cost180","solder_mask_margin","solder_paste_margin","solder_paste_ratio","clearance","zone_connect","thermal_width","thermal_gap"}:
                result["losses"].append({"code":"unsupported_token","token":kind,"owner":owner,"raw_preserved":True})
    return result
