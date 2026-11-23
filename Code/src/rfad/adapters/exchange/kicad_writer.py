"""! @brief 명시 PCB 기하를 KiCad 10에서 편집할 수 있는 구리 객체로 출력한다."""
import json
import math
from uuid import UUID, uuid5

from rfad.domain.errors import ProjectError
from rfad.adapters.exchange.sexpr import decimal as n, quote as q

VERSION = 20260206


def _id(identity, suffix):
    """! @brief 원본 식별자와 분할 역할에서 결정적인 수신 객체 ID를 만든다."""
    return str(uuid5(UUID(identity), suffix))


def _xy(point):
    """! @brief world Y 위쪽을 KiCad Y 아래쪽으로 명시 변환한다."""
    return n(point[0]) + " " + n(-point[1])


def layer_map(projection):
    """! @brief 실제 z 상부를 F.Cu로 매핑하며 존재하지 않는 구리를 발명하지 않는다."""
    from rfad.domain.drawing_layout import pcb_layer_targets
    ids={item["id"] for item in projection["layers"] if item["role"]=="conductor"}
    return {identity:name for identity,name in pcb_layer_targets(projection,"kicad_pcb").items() if identity in ids}


def net_map(projection):
    """! @brief 이름이 같아도 원본 net ID별로 수신 net 코드를 분리한다."""
    source = projection["source_semantics"]
    nets = source.get("nets", [])
    names=[item.get("name") or "net-"+str(index+1) for index,item in enumerate(nets)]
    if len(set(names))!=len(names):
        raise ProjectError("E_UNSUPPORTED","동일한 net 이름은 KiCad에서 병합될 수 있습니다. 이름을 명시 구분한 뒤 출력하십시오.")
    return {item["id"]: (index + 1,names[index]) for index,item in enumerate(nets)}


def _net(identity, nets, named=False):
    """! @brief 원문 null net은 미연결 0으로 내보내며 sidecar에 null을 유지한다."""
    if identity is None:
        return "(net 0)" if not named else ""
    if identity not in nets:
        raise ProjectError("E_CONNECTIVITY", "형상의 net 참조가 원문에 없습니다.")
    code, name = nets[identity]
    return "(net " + str(code) + (" " + q(name) if named else "") + ")"


def _point_on_arc(shape, fraction):
    """! @brief 원호 중심선의 시작/중간/끝점만 해석적으로 계산한다."""
    angle = math.radians(shape["start_angle_deg"] + fraction * shape["sweep_angle_deg"])
    return [shape["center_mm"][0] + shape["radius_mm"] * math.cos(angle), shape["center_mm"][1] + shape["radius_mm"] * math.sin(angle)]


def _polygon(points):
    """! @brief 직선 경계를 원문 꼭짓점 순서로 기록한다."""
    return "(polygon (pts " + " ".join("(xy " + _xy(point) + ")" for point in points) + "))"


def _filled_loops(outer, holes):
    """! @brief 구멍 있는 polygon의 표시 cache만 정확한 직선 삼각형으로 분리한다."""
    if not holes:
        return [outer]
    from shapely import Polygon, constrained_delaunay_triangles
    polygon = Polygon(outer, holes)
    if not polygon.is_valid:
        raise ProjectError("E_GEOMETRY", "KiCad에 전달할 구멍 영역이 유효하지 않습니다.")
    return [list(map(list, triangle.exterior.coords[:-1])) for triangle in constrained_delaunay_triangles(polygon).geoms]


def _zone(shape, layer, net, *, keepout=None, cache=None):
    """! @brief 구멍을 별도 contour로 보존하고 자동 열완화/섬 제거를 끈다."""
    loops = [shape["outer_mm"], *shape.get("holes_mm", [])]
    body = "(zone " + net + " (layer " + q(layer) + ") (uuid " + q(shape["id"]) + ") (name " + q("TraceWave:" + shape["id"]) + ") (hatch edge 0.5) "
    body += "(connect_pads yes (clearance 0)) (min_thickness 0.001) "
    if keepout is not None:
        names = {"tracks": "tracks", "vias": "vias", "pads": "pads", "copper_pours": "copperpour", "footprints": "footprints"}
        body += "(keepout " + " ".join("(" + names[key] + " " + ("not_allowed" if keepout[key] else "allowed") + ")" for key in names) + ") "
    else:
        body += "(fill yes (thermal_gap 0) (thermal_bridge_width 0.001) (island_removal_mode 1)) "
    body += " ".join(_polygon(loop) for loop in loops)
    if keepout is None:
        body += " " + " ".join("(filled_polygon (layer " + q(layer) + ") (pts " + " ".join("(xy " + _xy(point) + ")" for point in loop) + "))" for loop in (_filled_loops(loops[0], loops[1:]) if cache is None else cache))
    return body + ")"


def _edge(shape, identity):
    """! @brief 외곽/절삭 중심선을 Edge.Cuts 해석형으로 쓴다."""
    common = '(stroke (width 0.05) (type solid)) (layer "Edge.Cuts") '
    kind = shape.get("kind", "rectangle")
    if kind == "circle":
        center = shape["center_mm"]
        radius = shape.get("radius_mm", shape.get("diameter_mm", 0) / 2)
        return ["(gr_circle (center " + _xy(center) + ") (end " + _xy([center[0] + radius, center[1]]) + ") " + common + "(fill none) (uuid " + q(identity) + "))"]
    if kind == "capsule":
        center, width, length, angle = shape["center_mm"], shape["finished_width_mm"], shape["finished_length_mm"], math.radians(shape["rotation_deg"])
        dx, dy = (length - width) / 2 * math.cos(angle), (length - width) / 2 * math.sin(angle)
        ux, uy = -width / 2 * math.sin(angle), width / 2 * math.cos(angle)
        a, b = [center[0] - dx, center[1] - dy], [center[0] + dx, center[1] + dy]
        p = [[a[0] + ux, a[1] + uy], [b[0] + ux, b[1] + uy], [b[0] - ux, b[1] - uy], [a[0] - ux, a[1] - uy]]
        mids = [[b[0] + width / 2 * math.cos(angle), b[1] + width / 2 * math.sin(angle)], [a[0] - width / 2 * math.cos(angle), a[1] - width / 2 * math.sin(angle)]]
        result = []
        for index in (0, 2):
            result.append("(gr_line (start " + _xy(p[index]) + ") (end " + _xy(p[index + 1]) + ") " + common + "(uuid " + q(_id(identity, "line" + str(index))) + "))")
        for index, start, end in ((0, 1, 2), (1, 3, 0)):
            result.append("(gr_arc (start " + _xy(p[start]) + ") (mid " + _xy(mids[index]) + ") (end " + _xy(p[end]) + ") " + common + "(uuid " + q(_id(identity, "arc" + str(index))) + "))")
        return result
    points = shape.get("outer_mm")
    if points is None:
        points = [[0, 0], [shape["width_mm"], 0], [shape["width_mm"], shape["height_mm"]], [0, shape["height_mm"]]]
    return ["(gr_line (start " + _xy(a) + ") (end " + _xy(b) + ") " + common + "(uuid " + q(_id(identity, "edge" + str(index))) + "))" for index, (a, b) in enumerate(zip(points, points[1:] + points[:1]))]


def _pad(shape, layer, net, number="", *, local=None):
    """! @brief 단일층 패드를 mask/paste 자동 확장 없이 실제 구리 패드로 쓴다."""
    center = shape["center_mm"] if local is None else local(shape["center_mm"])
    angle = shape["rotation_deg"]
    if shape["pad_shape"] not in ("circle", "rectangle"):
        raise ProjectError("E_UNSUPPORTED", "KiCad 패드 profile은 원형과 사각형을 지원합니다.")
    kind = "circle" if shape["pad_shape"] == "circle" else "rect"
    return "(pad " + q(number) + " smd " + kind + " (at " + _xy(center) + " " + n(angle) + ") (size " + n(shape["size_mm"][0]) + " " + n(shape["size_mm"][1]) + ") (layers " + q(layer) + ") " + net + " (uuid " + q(shape["id"]) + "))"


def _graphic(shape, identity, layer, local=None, prefix="gr"):
    """! @brief 제조 aperture를 물성 또는 구리 객체로 바꾸지 않고 해당 artwork 층에 쓴다."""
    transform = (lambda point: point) if local is None else local
    kind = shape["kind"]
    common = '(stroke (width 0) (type solid)) (fill solid) (layer ' + q(layer) + ') '
    if kind == "circle":
        center = shape["center_mm"]
        radius = shape.get("diameter_mm", shape.get("radius_mm", 0)*2)/2
        return ["(" + prefix + "_circle (center " + _xy(transform(center)) + ") (end " + _xy(transform([center[0]+radius,center[1]])) + ") " + common + "(uuid " + q(identity) + "))"]
    if kind == "capsule":
        center, length, width = shape["center_mm"], shape["finished_length_mm"], shape["finished_width_mm"]
        angle = math.radians(shape["rotation_deg"])
        dx,dy=(length-width)/2*math.cos(angle),(length-width)/2*math.sin(angle)
        result=[]
        for index, point in enumerate(([center[0]-dx,center[1]-dy],[center[0]+dx,center[1]+dy])):
            result.extend(_graphic({"kind":"circle","center_mm":point,"diameter_mm":width},_id(identity,"cap"+str(index)),layer,local,prefix))
        ux,uy=-width/2*math.sin(angle),width/2*math.cos(angle)
        loops=[[[center[0]-dx+ux,center[1]-dy+uy],[center[0]+dx+ux,center[1]+dy+uy],[center[0]+dx-ux,center[1]+dy-uy],[center[0]-dx-ux,center[1]-dy-uy]]]
    elif kind=="rectangle":
        center,size=shape["center_mm"],shape["size_mm"]
        angle=math.radians(shape.get("rotation_deg",0))
        loops=[[[center[0]+x*math.cos(angle)-y*math.sin(angle),center[1]+x*math.sin(angle)+y*math.cos(angle)] for x,y in ((-size[0]/2,-size[1]/2),(size[0]/2,-size[1]/2),(size[0]/2,size[1]/2),(-size[0]/2,size[1]/2))]]
        result=[]
    elif kind=="polygon":
        loops=_filled_loops(shape["outer_mm"],shape.get("holes_mm",[]))
        result=[]
    else:
        raise ProjectError("E_UNSUPPORTED","지원하지 않는 artwork 경계입니다.")
    for index,loop in enumerate(loops):
        result.append("("+prefix+"_poly (pts "+" ".join("(xy "+_xy(transform(point))+")" for point in loop)+") "+common+"(uuid "+q(identity if len(loops)==1 and kind!="capsule" else _id(identity,"polygon"+str(index)))+"))")
    return result


def _footprint(record, projection, layers, nets, standalone=False):
    """! @brief 세계좌표 원본에서 수신 상대좌표를 한 번만 계산한다."""
    placement=record["placement"]
    origin,angle=placement["origin_mm"],math.radians(placement["rotation_deg"])
    def local(point):
        """! @brief 실제 world 원문에 대한 역배치만 수행한다."""
        x,y=point[0]-origin[0],point[1]-origin[1]
        return [x*math.cos(angle)+y*math.sin(angle),-x*math.sin(angle)+y*math.cos(angle)]
    name=record.get("library_id") or record.get("name") or "TraceWave footprint"
    side="B.Cu" if placement["side"]=="bottom" else "F.Cu"
    header="(footprint "+q(name)+" "+("(version "+str(VERSION)+') (generator "TraceWaveStudio") ' if standalone else "")+"(layer "+q(side)+") (uuid "+q(record["id"])+")"
    if not standalone:
        header+=" (at "+_xy(origin)+" "+n(placement["rotation_deg"])+")"
    result=[header]
    for key,source in (("Reference","reference"),("Value","value")):
        if record.get(source) is not None:
            result.append("(property "+q(key)+" "+q(record[source])+' (at 0 0) (layer '+q("B.Fab" if side=="B.Cu" else "F.Fab")+') (hide yes) (effects (font (size 1 1) (thickness 0.15))))')
    shapes={item["id"]:item for item in projection["shapes"]}
    numbers={pad_id:pin["number"] for pin in record.get("pins",[]) for pad_id in pin["pad_ids"]}
    holes={item["id"]:item for item in projection["mechanical"]["holes"]}
    apertures={item["id"]:item for item in projection.get("apertures",[])}
    keepouts={item["id"]:item for item in projection.get("keepouts",[])}
    for member in record["members"]:
        identity=member["id"]
        if member["collection"]=="geometry":
            shape=shapes.get(identity)
            if shape is None or shape["kind"]!="pad":
                raise ProjectError("E_UNSUPPORTED","첫 KiCad footprint profile은 실제 pad 소유 형상을 지원합니다. 다른 소유 구리는 조용히 분리하지 않습니다.")
            emitted=shape if not standalone else {**shape,"rotation_deg":shape["rotation_deg"]-placement["rotation_deg"]}
            result.append(_pad(emitted,layers[shape["layer_id"]],"" if standalone else _net(shape["net_id"],nets,True),numbers.get(identity,""),local=local))
        elif member["collection"]=="holes":
            from copy import deepcopy
            hole=deepcopy(holes[identity]);hole["shape"]["center_mm"]=local(hole["shape"]["center_mm"])
            if standalone:
                hole["plating"]["net_id"]=None
                hole["shape"]["rotation_deg"]=hole["shape"].get("rotation_deg",0)-placement["rotation_deg"]
            result.append(_hole(hole,nets,next((pin["number"] for pin in record.get("pins",[]) if pin.get("hole_id")==identity),"")))
        elif member["collection"]=="apertures":
            aperture=apertures[identity]
            result.extend(_graphic(aperture["shape"],identity,_artwork_name(projection,aperture["artwork_layer_id"]),local,"fp"))
        elif member["collection"]=="keepouts":
            keepout=keepouts[identity]
            if keepout["shape"]["kind"]!="polygon":
                raise ProjectError("E_UNSUPPORTED","footprint keepout은 직선 polygon profile을 지원합니다.")
            for index,layer_id in enumerate(keepout["layer_ids"]):
                shape={"id":_id(identity,str(index)),"outer_mm":[local(point) for point in keepout["shape"]["outer_mm"]],"holes_mm":[[local(point) for point in loop] for loop in keepout["shape"].get("holes_mm",[])]}
                result.append(_zone(shape,layers[layer_id],"(net 0)",keepout=keepout["prohibit"]))
        else:
            raise ProjectError("E_UNSUPPORTED","지원하지 않는 footprint 소유 객체입니다.")
    if record.get("placement_envelope") is not None:
        from rfad.domain.drawing_layout import mechanical_loops
        for loop_index,loop in enumerate(mechanical_loops(record["placement_envelope"])):
            for index,edge in enumerate(loop):
                common='(stroke (width 0.05) (type solid)) (layer '+q("B.CrtYd" if side=="B.Cu" else "F.CrtYd")+') (uuid '+q(_id(record["id"],"courtyard:"+str(loop_index)+":"+str(index)))+')'
                if edge["kind"]=="line":
                    result.append('(fp_line (start '+_xy(local(edge["start"]))+') (end '+_xy(local(edge["end"]))+') '+common+')')
                else:
                    def on(fraction):
                        """! @brief 실제 envelope 원호에서 세 점만 계산한다."""
                        theta=math.radians(edge["start_deg"]+edge["sweep_deg"]*fraction)
                        return local([edge["center"][0]+edge["radius"]*math.cos(theta),edge["center"][1]+edge["radius"]*math.sin(theta)])
                    if abs(edge["sweep_deg"])>=359.999999:
                        result.append('(fp_circle (center '+_xy(local(edge["center"]))+') (end '+_xy(on(0))+') '+common+' (fill none))')
                    else:
                        result.append('(fp_arc (start '+_xy(on(0))+') (mid '+_xy(on(.5))+') (end '+_xy(on(1))+') '+common+')')
    result.append(")")
    return "\n".join(result)


def _artwork_name(projection, identity):
    """! @brief 실제 사용이 확정된 mask/paste만 수신 층에 연결한다."""
    layer=next((item for item in projection.get("artwork_layers",[]) if item["id"]==identity),None)
    if layer is None or layer["use_state"]!="used":
        raise ProjectError("E_UNSUPPORTED","artwork 사용 상태가 확정되지 않았습니다.")
    return ("F." if layer["side"]=="top" else "B.")+("Mask" if layer["role"]=="solder_mask" else "Paste")


def _hole(hole, nets, number="", pad_diameter=None):
    """! @brief 완성 홀/슬롯과 도금 상태를 실제 drill 패드로 표현한다."""
    shape, plating = hole["shape"], hole["plating"]
    if plating["state"] not in ("plated", "unplated"):
        raise ProjectError("E_UNSUPPORTED", "도금 상태가 미정인 홀은 PTH/NPTH로 임의 분류하지 않습니다.")
    diameter = shape.get("diameter_mm", shape.get("finished_width_mm"))
    length = shape.get("finished_length_mm", diameter)
    thickness = plating["thickness_mm"] if plating["state"] == "plated" else 0
    if thickness is None and pad_diameter is None:
        raise ProjectError("E_UNSUPPORTED", "도금 두께 미정은 구리 외경으로 변환할 수 없습니다.")
    size = [length + 2 * thickness, diameter + 2 * thickness] if pad_diameter is None else [pad_diameter] * 2
    drill = "(drill " + ("oval " if shape["kind"] == "capsule" else "") + n(length) + (" " + n(diameter) if shape["kind"] == "capsule" else "") + ")"
    return "(pad "+q(number)+" " + ("thru_hole" if plating["state"] == "plated" else "np_thru_hole") + " " + ("oval" if shape["kind"] == "capsule" else "circle") + " (at " + _xy(shape["center_mm"]) + " " + n(shape.get("rotation_deg", 0)) + ") (size " + n(size[0]) + " " + n(size[1]) + ") " + drill + ' (layers "*.Cu") ' + _net(plating["net_id"], nets, True) + " (uuid " + q(hole["id"]) + "))"


def _wrapper(identity, contents, name="TraceWave standalone geometry"):
    """! @brief 독립 패드의 기술 컨테이너를 실제 소자 출처와 혼동하지 않게 이름 붙인다."""
    return "(footprint " + q(name) + ' (layer "F.Cu") (at 0 0) (uuid ' + q(identity) + ') (attr board_only exclude_from_pos_files exclude_from_bom) (property "TraceWaveContainer" "true" (at 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15)))) ' + " ".join(contents) + ")"


def write_board(projection):
    """! @brief 알려진 두께만 기록하고 RF 물성 미정은 sidecar에 보존한다."""
    layers, nets = layer_map(projection), net_map(projection)
    copper = list(layers.values())
    layer_ids = [0, *range(4, 4 + 2 * (len(copper) - 2), 2), 2]
    technology = [(1, "F.Mask"), (3, "B.Mask"), (13, "F.Paste"), (15, "B.Paste"), (25, "Edge.Cuts"), (31, "F.CrtYd"), (29, "B.CrtYd"), (35, "F.Fab"), (33, "B.Fab")]
    thickness = max(item["z_min_mm"] + item["thickness_mm"] for item in projection["layers"]) - min(item["z_min_mm"] for item in projection["layers"])
    result = ["(kicad_pcb (version " + str(VERSION) + ') (generator "TraceWaveStudio") (generator_version "0.1")', "(general (thickness " + n(thickness) + ")) (paper \"A4\")", "(layers " + " ".join("(" + str(index) + " " + q(name) + " " + ("signal" if name.endswith(".Cu") else "user") + ")" for index, name in [*zip(layer_ids, copper), *technology]) + ")"]
    stack = []
    dielectric_index = 0
    for layer in sorted(projection["layers"], key=lambda item: item["z_min_mm"], reverse=True):
        if layer["role"] == "conductor":
            name, kind = layers[layer["id"]], "copper"
        else:
            dielectric_index += 1
            name, kind = "dielectric " + str(dielectric_index), "core"
        material=projection.get("materials",{}).get(layer.get("material_id"))
        metadata=""
        if material is not None:
            metadata=" (material "+q(material["name"])+")"
            if layer["role"]=="dielectric":
                for source,key in (("epsilon_r","epsilon_r"),("loss_tangent","loss_tangent")):
                    if material.get(source) is not None:
                        metadata+=" ("+key+" "+n(material[source])+")"
        stack.append("(layer " + q(name) + " (type " + q(kind) + ") (thickness " + n(layer["thickness_mm"]) + ")"+metadata+")")
    result.append("(setup (stackup " + " ".join(stack) + ") (pad_to_mask_clearance 0) (aux_axis_origin 0 0) (grid_origin 0 0))")
    result.extend("(net " + str(code) + " " + q(name) + ")" for code, name in nets.values())
    result.extend(_edge(projection["board"], projection["board"]["id"]))
    for cutout in projection["mechanical"]["cutouts"]:
        result.extend(_edge(cutout["shape"], cutout["id"]))
    footprints=projection.get("footprints",[])
    owned={(member["collection"],member["id"]) for footprint in footprints for member in footprint["members"]}
    from rfad.domain.drawing_layout import explicit_through_pads, kicad_copper_loops
    rings, bundled = explicit_through_pads(projection)
    shapes = projection["shapes"]
    for shape in shapes:
        if ("geometry",shape["id"]) in owned or shape["id"] in bundled:
            continue
        kind = shape["kind"]
        layer = layers.get(shape["layer_id"])
        if layer is None:
            raise ProjectError("E_UNSUPPORTED", "구리 형상이 실제 구리층을 참조하지 않습니다.")
        net = _net(shape["net_id"], nets)
        if kind == "line_path":
            result.append("(segment (start " + _xy(shape["start_mm"]) + ") (end " + _xy(shape["end_mm"]) + ") (width " + n(shape["width_mm"]) + ") (layer " + q(layer) + ") " + net + " (uuid " + q(shape["id"]) + "))")
        elif kind == "arc_path":
            parts = 2 if abs(shape["sweep_angle_deg"]) >= 359.999999 else 1
            for index in range(parts):
                points = [_point_on_arc(shape, (index + fraction) / parts) for fraction in (0, .5, 1)]
                result.append("(arc " + " ".join("(" + key + " " + _xy(point) + ")" for key, point in zip(("start", "mid", "end"), points)) + " (width " + n(shape["width_mm"]) + ") (layer " + q(layer) + ") " + net + " (uuid " + q(shape["id"] if parts == 1 else _id(shape["id"], str(index))) + "))")
        elif kind == "planar_region":
            from rfad.adapters.exchange.pcb_geometry import filled_cache
            zone_net="(net "+q("" if shape["net_id"] is None else nets[shape["net_id"]][1])+")"
            result.append(_zone(shape, layer, zone_net, cache=filled_cache(kicad_copper_loops(projection, shape, rings))))
        elif kind == "pad":
            result.append(_wrapper(_id(shape["id"], "container"), [_pad(shape, layer, _net(shape["net_id"], nets, True))]))
        elif kind == "via":
            if {layer,layers[shape["end_layer_id"]]}!={copper[0],copper[-1]}:
                raise ProjectError("E_UNSUPPORTED","이 KiCad profile은 전체 적층 관통 비아만 지원합니다. blind/buried 비아로 임의 변경하지 않습니다.")
            result.append("(via (at " + _xy(shape["center_mm"]) + ") (size " + n(shape["finished_hole_diameter_mm"] + 2 * shape["plating_thickness_mm"]) + ") (drill " + n(shape["finished_hole_diameter_mm"]) + ") (layers " + q(layer) + " " + q(layers[shape["end_layer_id"]]) + ") " + net + " (uuid " + q(shape["id"]) + "))")
        else:
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 KiCad 구리 객체입니다: " + kind)
    for hole in projection["mechanical"]["holes"]:
        if ("holes",hole["id"]) not in owned:
            result.append(_wrapper(_id(hole["id"], "container"), [_hole(hole, nets, pad_diameter=rings.get(hole["id"]))], "TraceWave mechanical bore"))
    for footprint in footprints:
        result.append(_footprint(footprint,projection,layers,nets))
    for aperture in projection.get("apertures",[]):
        if ("apertures",aperture["id"]) not in owned:
            result.extend(_graphic(aperture["shape"],aperture["id"],_artwork_name(projection,aperture["artwork_layer_id"])))
    for keepout in projection.get("keepouts",[]):
        if ("keepouts",keepout["id"]) in owned:
            continue
        if keepout["shape"]["kind"]!="polygon":
            raise ProjectError("E_UNSUPPORTED","KiCad keepout은 명시 직선 polygon profile을 지원합니다.")
        for index,layer_id in enumerate(keepout["layer_ids"]):
            shape={"id":_id(keepout["id"],str(index)),"outer_mm":keepout["shape"]["outer_mm"],"holes_mm":keepout["shape"].get("holes_mm",[])}
            result.append(_zone(shape,layers[layer_id],"(net 0)",keepout=keepout["prohibit"]))
    result.append(")")
    return ("\n".join(result) + "\n").encode("utf-8")


def write_footprint(projection, identity):
    """! @brief 선택 footprint만 상대좌표 라이브러리로 출력하고 프로젝트 net은 sidecar에 남긴다."""
    record=next((item for item in projection.get("footprints",[]) if item["id"]==identity),None)
    if record is None:
        raise ProjectError("E_SCHEMA","선택 footprint가 원본에 없습니다.")
    return (_footprint(record,projection,layer_map(projection),net_map(projection),True)+"\n").encode("utf-8")


def project_settings():
    """! @brief 형상 보존용 0 여유를 제조 설계 규칙 합격으로 해석하지 않는다."""
    value = {"meta": {"filename": "board.kicad_pro", "version": 3}, "board": {"design_settings": {"meta":{"version":2},"rules": {"min_clearance": 0, "min_copper_edge_clearance": 0, "min_hole_clearance": 0, "min_track_width": 0, "min_via_annular_width": 0,"max_error":0.0001}, "rule_severities": {}}}, "net_settings": {"classes": [{"name": "Default", "clearance": 0}], "meta": {"version": 4}}}
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
