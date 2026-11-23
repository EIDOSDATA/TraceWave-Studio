"""! @brief 독립 parser 결과를 고정 원본의 실제 객체/구리/드릴과 대조한다."""
import math
from uuid import UUID,uuid5

from rfad.domain.errors import ProjectError
from rfad.domain import drawing_layout as geometry
from rfad.adapters.exchange import cam_reader,kicad_reader
from rfad.adapters.exchange.pcb_geometry import polygonize,compare_regions


def require(condition,message):
    """! @brief 손실 또는 불일치를 형식 검수 성공으로 넘기지 않는다."""
    if not condition:
        raise ProjectError("E_HASH",message)


def _close(a,b,tolerance=3e-6):
    """! @brief JSON 배열과 유한 수치의 선언 양자화 범위를 대조한다."""
    if type(a) is list and type(b) is list:
        return len(a)==len(b) and all(_close(x,y,tolerance) for x,y in zip(a,b))
    return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tolerance


def _net_names(projection):
    """! @brief 실제 원문 net명만 조회한다."""
    return {item["id"]:item["name"] for item in projection["source_semantics"]["nets"]}


def _boundaries(actual,loops):
    """! @brief 외곽/절삭/요소의 해석형 경계를 직접 대조한다."""
    expected=[edge for loop in loops for edge in loop]
    require(len(actual)==len(expected),"외곽/절삭의 경계 개수가 다릅니다.")
    remaining=list(expected)
    for item in actual:
        matched=None
        for index,edge in enumerate(remaining):
            if item["kind"]=="line" and edge["kind"]=="line":
                if (_close(item["start_mm"],edge["start"]) and _close(item["end_mm"],edge["end"])) or (_close(item["start_mm"],edge["end"]) and _close(item["end_mm"],edge["start"])):
                    matched=index;break
            elif item["kind"] in ("circle","arc") and edge["kind"]=="arc":
                if not _close(item["center_mm"],edge["center"],3e-5) or not _close(item["radius_mm"],edge["radius"],3e-5):
                    continue
                sweep=360 if item["kind"]=="circle" else abs(item["sweep_angle_deg"])
                if not _close(sweep,abs(edge["sweep_deg"]),1e-4):
                    continue
                if item["kind"]=="arc":
                    a=geometry.polar(edge["center"],edge["radius"],edge["start_deg"])
                    b=geometry.polar(edge["center"],edge["radius"],edge["start_deg"]+edge["sweep_deg"])
                    if not ((_close(item["start_mm"],a) and _close(item["end_mm"],b)) or (_close(item["start_mm"],b) and _close(item["end_mm"],a))):
                        continue
                matched=index;break
        require(matched is not None,"외곽/절삭의 실제 위치/원호가 원본과 다릅니다.")
        remaining.pop(matched)


def _graphic_region(item):
    """! @brief 수신 artwork의 실제 fill을 별도 planar 영역으로 만든다."""
    require(item["fill"]=="solid","제조 aperture의 채움이 사라졌습니다.")
    if item["kind"]=="circle":
        loops=[[geometry.arc(item["center_mm"],item["radius_mm"])]]
    elif item["kind"] in ("poly","rect"):
        loops=[geometry.polygon(item["outer_mm"])]
    else:
        raise ProjectError("E_HASH","제조 aperture의 종류가 달라졌습니다.")
    return polygonize(loops)


def _auxiliary(actual,projection,selected):
    """! @brief footprint/pin/keepout/artwork 누락도 실제 형식 검수 실패로 처리한다."""
    from shapely import GeometryCollection
    source_footprints=projection["footprints"] if selected is None else [selected]
    actual_footprints={row["id"]:row for row in actual["footprints"] if not row["technical_container"]}
    require(set(actual_footprints)=={row["id"] for row in source_footprints},"실제 footprint 목록이 원문과 다릅니다.")
    require(all(row["footprint_id"] in actual_footprints for row in actual["artwork"] if row["layer"].endswith(".CrtYd")),"소유 footprint가 없는 courtyard가 추가되었습니다.")
    for source in source_footprints:
        item=actual_footprints[source["id"]];placement=source["placement"]
        expected_origin=placement["origin_mm"] if selected is None else [0,0]
        expected_rotation=placement["rotation_deg"] if selected is None else 0
        require(_close(item["placement"]["origin_mm"],expected_origin) and _close(item["placement"]["rotation_deg"],expected_rotation) and item["placement"]["side"]==placement["side"],"footprint 배치/면 방향이 달라졌습니다.")
        for key,label in (("reference","Reference"),("value","Value")):
            require(item["properties"].get(label)==source.get(key),"footprint 원문 속성의 미정/값이 달라졌습니다.")
        members={row["id"]:row for row in actual["shapes"] if row.get("footprint_id")==source["id"]}
        for pin in source["pins"]:
            for identity in pin["pad_ids"]+([pin["hole_id"]] if pin.get("hole_id") is not None else []):
                require(identity in members and members[identity].get("number")==pin["number"],"footprint 핀 번호와 실제 패드/홀 소유가 다릅니다.")
        courtyard=[row for row in actual["artwork"] if row["footprint_id"]==source["id"] and row["layer"].endswith(".CrtYd")]
        loops=[] if source.get("placement_envelope") is None else geometry.mechanical_loops(source["placement_envelope"])
        if selected is not None:
            loops=_local_loops(loops,selected)
        require(all(row["layer"]==("B.CrtYd" if placement["side"]=="bottom" else "F.CrtYd") and row["fill"]=="none" and _close(row["width_mm"],.05) for row in courtyard),"footprint courtyard의 층/선 의미가 달라졌습니다.")
        _boundaries(courtyard,loops)
    if selected is not None:
        member_ids={row["id"] for row in selected["members"]}
        apertures=[row for row in projection["apertures"] if row["id"] in member_ids]
        keepouts=[row for row in projection["keepouts"] if row["id"] in member_ids]
    else:
        apertures=projection["apertures"];keepouts=projection["keepouts"]
    expected_art={};actual_art={}
    for aperture in apertures:
        layer=next(row for row in projection["artwork_layers"] if row["id"]==aperture["artwork_layer_id"])
        name=("F." if layer["side"]=="top" else "B.")+("Mask" if layer["role"]=="solder_mask" else "Paste")
        expected_art[name]=expected_art.get(name,GeometryCollection()).union(polygonize(geometry.mechanical_loops(aperture["shape"])))
    if selected is not None:
        from shapely.affinity import translate,rotate
        for name,value in expected_art.items():
            expected_art[name]=rotate(translate(value,xoff=-selected["placement"]["origin_mm"][0],yoff=-selected["placement"]["origin_mm"][1]),-selected["placement"]["rotation_deg"],origin=(0,0))
    for item in actual["artwork"]:
        if item["layer"].endswith(".CrtYd"):
            continue
        actual_art[item["layer"]]=actual_art.get(item["layer"],GeometryCollection()).union(_graphic_region(item))
    require(set(expected_art)==set(actual_art),"mask/paste 실제 층 목록이 다릅니다.")
    for name in expected_art:
        compare_regions(actual_art[name],expected_art[name])
    require(len(actual["keepouts"])==sum(len(item["layer_ids"]) for item in keepouts),"keepout 층별 영역이 누락되거나 추가되었습니다.")
    for source in keepouts:
        expected={"tracks":source["prohibit"]["tracks"],"vias":source["prohibit"]["vias"],"pads":source["prohibit"]["pads"],"copperpour":source["prohibit"]["copper_pours"],"footprints":source["prohibit"]["footprints"]}
        for index,_ in enumerate(source["layer_ids"]):
            identity=str(uuid5(UUID(source["id"]),str(index)))
            item=next((row for row in actual["keepouts"] if row["id"]==identity),None)
            require(item is not None and item["prohibit"]==expected,"keepout 종류별 금지 조건이 달라졌습니다.")
            layers=geometry.pcb_layer_targets(projection,"kicad_pcb")
            require(item["layer"]==layers[source["layer_ids"][index]],"keepout의 대상 구리층이 달라졌습니다.")
            loops=geometry.mechanical_loops(source["shape"])
            if selected is not None:
                loops=_local_loops(loops,selected)
            compare_regions(polygonize([geometry.polygon(item["outer_mm"]),*[geometry.polygon(loop) for loop in item["holes_mm"]]]),polygonize(loops))


def _local_loops(loops,footprint):
    """! @brief standalone 사본의 기대 경계만 원본 world 배치에서 역변환한다."""
    from copy import deepcopy
    result=deepcopy(loops);place=footprint["placement"];angle=math.radians(place["rotation_deg"])
    for loop in result:
        for edge in loop:
            for key in (("start","end") if edge["kind"]=="line" else ("center",)):
                x,y=edge[key][0]-place["origin_mm"][0],edge[key][1]-place["origin_mm"][1]
                edge[key]=[x*math.cos(angle)+y*math.sin(angle),-x*math.sin(angle)+y*math.cos(angle)]
            if edge["kind"]=="arc":
                edge["start_deg"]-=place["rotation_deg"]
    return result


def kicad(raw,projection,format_name,options):
    """! @brief native 객체와 region fill cache를 원본 도체/절삭과 검사한다."""
    actual=kicad_reader.read(raw)
    require(not actual["losses"],"새 KiCad 출력에 미지원 또는 누락된 필드가 있습니다.")
    items={item["id"]:item for item in actual["shapes"]}
    require(len(items)==len(actual["shapes"]),"KiCad 출력 객체 ID가 중복됩니다.")
    copper=sorted((item for item in projection["layers"] if item["role"]=="conductor"),key=lambda item:item["z_min_mm"],reverse=True)
    names=["F.Cu",*["In"+str(index)+".Cu" for index in range(1,len(copper)-1)],"B.Cu"]
    layers={item["id"]:name for item,name in zip(copper,names)}
    nets=_net_names(projection)
    selected=None
    if format_name=="kicad_mod":
        selected=next(item for item in projection["footprints"] if item["id"]==options["footprint_id"])
        member_ids={member["id"] for member in selected["members"]}
        source_shapes=[item for item in projection["shapes"] if item["id"] in member_ids]
    else:
        source_shapes=projection["shapes"]
        require([item["name"] for item in actual["layers"] if item["name"].endswith(".Cu")]==names,"KiCad 구리층 순서가 원문 z 순서와 다릅니다.")
        actual_copper={item["name"]:item for item in actual["stackup"] if item["type"]=="copper"}
        for layer in copper:
            require(layer["id"] in layers and layers[layer["id"]] in actual_copper,"KiCad 실제 적층에 구리층이 없습니다.")
            require(_close(actual_copper[layers[layer["id"]]]["thickness_mm"],layer["thickness_mm"]),"KiCad 구리 두께가 달라졌습니다.")
        source_stack=sorted(projection["layers"],key=lambda row:row["z_min_mm"],reverse=True)
        require(len(actual["stackup"])==len(source_stack),"KiCad 적층 수가 달라졌습니다.")
        dielectric_index=0
        for source,row in zip(source_stack,actual["stackup"]):
            if source["role"]=="conductor":
                expected_name=layers[source["id"]];expected_type="copper"
            else:
                dielectric_index+=1;expected_name="dielectric "+str(dielectric_index);expected_type="core"
            require(row["name"]==expected_name and row["type"]==expected_type and _close(row["thickness_mm"],source["thickness_mm"]),"KiCad 적층 순서/두께/역할이 원문과 다릅니다.")
            material=projection.get("materials",{}).get(source.get("material_id"))
            require(row["material"]==(None if material is None else material["name"]),"KiCad 재료 이름의 미정/원문이 달라졌습니다.")
            for key in ("epsilon_r","loss_tangent"):
                expected=None if material is None or source["role"]!="dielectric" else material.get(key)
                require(row[key] is None if expected is None else _close(row[key],expected),"KiCad 물성의 미정/원문이 달라졌습니다.")
    checks=[];consumed=set()
    through_pads = {pad_id: hole["id"] for hole in projection["mechanical"]["holes"]
                    for pad_id in hole["plating"]["pad_ids"] if selected is None
                    and hole["id"] in items and pad_id not in items}
    for shape in source_shapes:
        identity=shape["id"]
        if identity in through_pads:
            pad = items[through_pads[identity]]
            require(shape["kind"] == "pad" and shape["pad_shape"] == "circle" and pad["pad_type"] == "thru_hole"
                    and pad["pad_shape"] == "circle" and pad["layers"] == ["*.Cu"]
                    and pad["net_name"] == nets.get(shape["net_id"]) and _close(pad["center_mm"], shape["center_mm"])
                    and _close(pad["size_mm"], shape["size_mm"]), "관통 홀의 실제 구리 패드가 원본과 다릅니다.")
            continue
        if shape["kind"]=="arc_path" and abs(shape["sweep_angle_deg"])>=359.999999:
            ids=[str(uuid5(UUID(identity),str(index))) for index in (0,1)]
            require(all(key in items for key in ids),"완전 원호의 실제 track 분할 객체가 없습니다.")
            rows=[items[key] for key in ids];consumed.update(ids)
            require(_close(sum(item["sweep_angle_deg"] for item in rows),shape["sweep_angle_deg"],1e-4),"완전 원호 회전량이 달라졌습니다.")
        else:
            require(identity in items,"원문 객체가 KiCad 실제 구리에 없습니다: "+identity)
            rows=[items[identity]];consumed.add(identity)
        for item in rows:
            expected_net=None if selected is not None else nets.get(shape["net_id"])
            require(item["net_name"]==expected_net,"KiCad net 연결이 원문과 다릅니다.")
            if shape["kind"] not in ("pad","via"):
                require(item["layer"]==layers[shape["layer_id"]],"KiCad 객체의 층이 다릅니다.")
            if shape["kind"]=="line_path":
                require(item["kind"]=="line_path" and _close(item["start_mm"],shape["start_mm"]) and _close(item["end_mm"],shape["end_mm"]) and _close(item["width_mm"],shape["width_mm"]),"KiCad 선의 원점/끝점/폭이 다릅니다.")
            elif shape["kind"]=="arc_path":
                require(item["kind"]=="arc_path" and _close(item["center_mm"],shape["center_mm"],3e-5) and _close(item["radius_mm"],shape["radius_mm"],3e-5) and _close(item["width_mm"],shape["width_mm"]),"KiCad 원호의 해석형 반지름/중심/폭이 다릅니다.")
                if len(rows)==1:
                    require(_close(item["sweep_angle_deg"],shape["sweep_angle_deg"],1e-4),"KiCad 원호 방향 또는 회전량이 다릅니다.")
                part=rows.index(item);start=shape["start_angle_deg"]+shape["sweep_angle_deg"]*part/len(rows)
                end=start+shape["sweep_angle_deg"]/len(rows)
                require(_close(item["start_mm"],geometry.polar(shape["center_mm"],shape["radius_mm"],start)) and _close(item["end_mm"],geometry.polar(shape["center_mm"],shape["radius_mm"],end)),"KiCad 원호 시작/끝 위치가 달라졌습니다.")
            elif shape["kind"]=="planar_region":
                require(_close(item["outer_mm"],shape["outer_mm"]) and _close(item["holes_mm"],shape["holes_mm"]),"KiCad 영역 원본 경계와 구멍이 다릅니다.")
                policy=item["fill_settings"]
                require(policy["connect_pads"]=="yes" and policy["island_removal_mode"]=="1" and _close(policy["clearance_mm"],0) and _close(policy["minimum_thickness_mm"],.001) and _close(policy["thermal_gap_mm"],0),"KiCad zone의 명시 접촉/섬 보존 설정이 달라졌습니다.")
                from shapely import Polygon,unary_union
                filled=unary_union([Polygon(points) for points in item["filled_polygons_mm"]])
                checks.append(compare_regions(filled,polygonize(geometry.kicad_copper_loops(projection, shape, set(through_pads.values())))))
            elif shape["kind"]=="pad":
                center=shape["center_mm"]
                rotation=shape["rotation_deg"]
                if selected is not None:
                    placement=selected["placement"];theta=math.radians(placement["rotation_deg"])
                    x,y=center[0]-placement["origin_mm"][0],center[1]-placement["origin_mm"][1]
                    center=[x*math.cos(theta)+y*math.sin(theta),-x*math.sin(theta)+y*math.cos(theta)]
                    rotation-=placement["rotation_deg"]
                require(item["kind"]=="pad" and item["pad_type"]=="smd" and item["pad_shape"]==("circle" if shape["pad_shape"]=="circle" else "rect") and _close(item["center_mm"],center) and _close(item["size_mm"],shape["size_mm"]) and _close(item["rotation_deg"],rotation),"KiCad 패드 크기/배치/방향이 다릅니다.")
                require(item["layers"]==[layers[shape["layer_id"]]],"KiCad 패드가 자동 mask/paste 또는 다른 구리층으로 확장됐습니다.")
                require(item["drill"] is None,"원문 평면 패드에 없던 drill이 추가되었습니다.")
            elif shape["kind"]=="via":
                require(item["kind"]=="via" and _close(item["center_mm"],shape["center_mm"]) and _close(item["finished_hole_diameter_mm"],shape["finished_hole_diameter_mm"]) and _close(item["size_mm"],shape["finished_hole_diameter_mm"]+2*shape["plating_thickness_mm"]),"KiCad 비아 완성 홀/도금 외경이 다릅니다.")
                require(item["layers"]==[layers[shape["layer_id"]],layers[shape["end_layer_id"]]],"KiCad 비아의 관통 층이 달라졌습니다.")
    for hole in projection["mechanical"]["holes"]:
        if selected is not None and hole["id"] not in member_ids:
            continue
        require(hole["id"] in items,"KiCad 기계 홀 객체가 없습니다.")
        item=items[hole["id"]];consumed.add(hole["id"])
        width=hole["shape"].get("diameter_mm",hole["shape"].get("finished_width_mm"));length=hole["shape"].get("finished_length_mm",width)
        require(item.get("drill") is not None and _close(item["drill"]["size_mm"],[length,width]) and item["drill"]["plating"]==hole["plating"]["state"],"KiCad drill 완성 치수/도금 구분이 다릅니다.")
        center=hole["shape"]["center_mm"]
        if selected is not None:
            theta=math.radians(selected["placement"]["rotation_deg"]);x,y=center[0]-selected["placement"]["origin_mm"][0],center[1]-selected["placement"]["origin_mm"][1]
            center=[x*math.cos(theta)+y*math.sin(theta),-x*math.sin(theta)+y*math.cos(theta)]
        require(_close(item["center_mm"],center) and _close(item["drill"]["offset_mm"],[0,0]),"KiCad drill 중심이 달라졌습니다.")
        rotation=hole["shape"].get("rotation_deg",0)-(selected["placement"]["rotation_deg"] if selected is not None else 0)
        thickness=hole["plating"]["thickness_mm"] if hole["plating"]["state"]=="plated" else 0
        tied = [row for row in source_shapes if through_pads.get(row["id"]) == hole["id"]]
        if tied:
            require(len(tied) == len(copper) and {r["layer_id"] for r in tied} == {r["id"] for r in copper},
                    "관통 패드와 원문 도체층의 수 또는 위치가 다릅니다.")
            size = tied[0]["size_mm"]
        else:
            require(thickness is not None, "원본 패드 또는 도금 두께에 구리 외경의 근거가 없습니다.")
            size = [length + 2 * thickness, width + 2 * thickness]
        require(_close(item["rotation_deg"],rotation) and _close(item["size_mm"],size) and item["layers"]==["*.Cu"],"KiCad 홀/슬롯의 방향 또는 구리 외경/층이 달라졌습니다.")
        require(item["net_name"]==(None if selected is not None else nets.get(hole["plating"]["net_id"])),"KiCad 도금 홀의 net이 원문과 다릅니다.")
    require(consumed==set(items),"예상하지 않은 KiCad 구리/홀 객체가 추가되었습니다.")
    if selected is None:
        loops=geometry.board_loops(projection["board"])
        for cutout in projection["mechanical"]["cutouts"]:
            loops+=geometry.mechanical_loops(cutout["shape"])
        _boundaries(actual["edges"],loops)
    _auxiliary(actual,projection,selected)
    return {"reader":"bounded S-expression parser","shapes":len(items),"edge_segments":len(actual["edges"]),"footprints":len(actual["footprints"]),"regions":checks}


def _cam_entities(projection,identity):
    """! @brief reader 대조의 기대 기하는 원문 snapshot의 공통 해석형 투영에서 얻는다."""
    result={}
    layer=next((item for item in projection["layers"] if item["id"]==identity),None)
    if layer is not None:
        for shape in projection["shapes"]:
            if shape["kind"]=="via":
                positions=[next(row["z_min_mm"] for row in projection["layers"] if row["id"]==shape[key]) for key in ("layer_id","end_layer_id")]
                include=min(positions)<=layer["z_min_mm"]<=max(positions)
            else:
                include=shape["layer_id"]==identity
            if include:
                result[shape["id"]]=(shape["net_id"],geometry.copper_loops(projection,shape))
        for hole in projection["mechanical"]["holes"]:
            if hole["plating"]["state"]=="plated":
                result[hole["id"]]=(hole["plating"]["net_id"],geometry.mechanical_shell(hole))
    else:
        for aperture in projection["apertures"]:
            if aperture["artwork_layer_id"]==identity:
                result[aperture["id"]]=(None,geometry.mechanical_loops(aperture["shape"]))
    return result


def gerber_region(item):
    """! @brief parser의 실제 draw/flash/region을 검수용 구리 영역으로 해석한다."""
    if item["kind"]=="region":
        return polygonize(item["loops"])
    if item["kind"]=="stroke":
        edge=item["edge"]
        if edge["kind"]=="line":
            shape={"kind":"line_path","start_mm":edge["start"],"end_mm":edge["end"],"width_mm":item["width_mm"]}
        else:
            shape={"kind":"arc_path","center_mm":edge["center"],"radius_mm":edge["radius"],"start_angle_deg":edge["start_deg"],"sweep_angle_deg":edge["sweep_deg"],"width_mm":item["width_mm"]}
        return polygonize(geometry.shape_loops(shape))
    aperture=item["aperture"]
    if aperture["kind"] in ("C","R"):
        shape={"kind":"pad","pad_shape":"circle" if aperture["kind"]=="C" else "rectangle","center_mm":item["center_mm"],"size_mm":aperture["size_mm"]*2 if aperture["kind"]=="C" else aperture["size_mm"],"rotation_deg":0}
        return polygonize(geometry.shape_loops(shape))
    size=aperture["size_mm"]
    shape={"kind":"capsule","center_mm":item["center_mm"],"finished_length_mm":max(size),"finished_width_mm":min(size),"rotation_deg":0 if size[0]>=size[1] else 90}
    return polygonize(geometry.mechanical_loops(shape))


def cam(files,projection,options):
    """! @brief Job 메타데이터와 실제 Gerber/XNC 기하를 파일별 대조한다."""
    job=cam_reader.read_job(files["fabrication.gbrjob"],files)["job"]
    expected_files=set(files)-{"fabrication.gbrjob"}
    require({item["Path"] for item in job["FilesAttributes"]}==expected_files,"Job 목록과 실제 CAM 파일 목록이 다릅니다.")
    parsed={};checks=[];nets=_net_names(projection)
    copper=sorted((row for row in projection["layers"] if row["role"]=="conductor"),key=lambda row:row["z_min_mm"],reverse=True)
    functions={}
    for index,identity in enumerate(options["layer_ids"]):
        layer=next(row for row in [*projection["layers"],*projection["artwork_layers"]] if row["id"]==identity)
        if layer["role"]=="conductor":
            ordinal=next(i for i,row in enumerate(copper) if row["id"]==identity)
            function="Copper,L"+str(ordinal+1)+","+("Top" if ordinal==0 else "Bot" if ordinal==len(copper)-1 else "Inr")
            polarity="Positive"
        else:
            function=("Soldermask" if layer["role"]=="solder_mask" else "Paste")+","+("Top" if layer["side"]=="top" else "Bot")
            polarity="Negative" if layer["role"]=="solder_mask" else "Positive"
        functions["layer-"+str(index+1).zfill(2)+".gbr"]=(function,polarity)
    functions["outline.gbr"]=("Profile,NP","Positive")
    for name,state,kind in (("plated.xnc","Plated","PTH"),("nonplated.xnc","NonPlated","NPTH")):
        if name in files:
            functions[name]=(state+",1,"+str(len(copper))+","+kind,"Positive")
    bounds=geometry.board_bounds(projection["board"])
    thickness=max(row["z_min_mm"]+row["thickness_mm"] for row in projection["layers"])-min(row["z_min_mm"] for row in projection["layers"])
    require(job.get("GeneralSpecs")=={"LayerNumber":len(copper),"BoardThickness":thickness,"Size":{"X":bounds[2]-bounds[0],"Y":bounds[3]-bounds[1]}},"Job의 실제 구리층 수/기판 치수가 원문과 다릅니다.")
    stack=[]
    for layer in sorted(projection["layers"],key=lambda row:row["z_min_mm"],reverse=True):
        row={"Type":"Copper" if layer["role"]=="conductor" else "Dielectric","Name":layer["name"],"Thickness":layer["thickness_mm"]}
        material=projection.get("materials",{}).get(layer.get("material_id"))
        if material is not None:
            row["Material"]=material["name"]
            for source,key in (("epsilon_r","DielectricConstant"),("loss_tangent","LossTangent"),("conductivity_s_per_m","Conductivity")):
                if material.get(source) is not None:
                    row[key]=material[source]
        stack.append(row)
    require(job.get("MaterialStackup")==stack,"Job 적층의 순서/물성/미정이 원문과 다릅니다.")
    for item in job["FilesAttributes"]:
        name=item["Path"]
        require(name in functions and (item.get("FileFunction"),item.get("FilePolarity"))==functions[name],"Job 층/드릴 역할이 원본 선택과 다릅니다.")
        value=cam_reader.read_xnc(files[name]) if name.endswith(".xnc") else cam_reader.read_gerber(files[name])
        parsed[name]=value
        require(",".join(value["file_attributes"].get(".FileFunction",[]))==item["FileFunction"],"Job과 파일의 층/드릴 역할이 다릅니다.")
        if name.endswith(".gbr"):
            require(value["file_attributes"].get(".FilePolarity")==[item["FilePolarity"]],"Job과 Gerber material polarity가 다릅니다.")
            require(value["file_attributes"].get(".SameCoordinates")==[projection["source_semantics"]["project_id"]],"Gerber 공통 원점 출처가 다릅니다.")
    outline_sources={projection["board"]["id"]:geometry.board_loops(projection["board"])}
    outline_sources.update({row["id"]:geometry.mechanical_loops(row["shape"]) for row in projection["mechanical"]["cutouts"]})
    outline_items={identity:[] for identity in outline_sources}
    for item in parsed["outline.gbr"]["objects"]:
        ids=item["attributes"].get("TraceWaveId",[])
        require(len(ids)==1 and ids[0] in outline_items and item["kind"]=="stroke" and item["polarity"]=="dark" and _close(item["width_mm"],.05),"Gerber 외곽/절삭 객체 의미가 다릅니다.")
        edge=item["edge"]
        actual={"kind":edge["kind"],"start_mm":edge["start"],"end_mm":edge["end"]}
        if edge["kind"]=="arc":
            actual.update(center_mm=edge["center"],radius_mm=edge["radius"],sweep_angle_deg=edge["sweep_deg"])
        outline_items[ids[0]].append(actual)
    for identity,loops in outline_sources.items():
        split=[]
        for loop in loops:
            edges=[]
            for edge in loop:
                if edge["kind"]=="arc" and abs(edge["sweep_deg"])>=359.999999:
                    edges.extend([{**edge,"start_deg":edge["start_deg"]+index*edge["sweep_deg"]/2,"sweep_deg":edge["sweep_deg"]/2} for index in (0,1)])
                else:
                    edges.append(edge)
            split.append(edges)
        _boundaries(outline_items[identity],split)
    for index,identity in enumerate(options["layer_ids"]):
        value=parsed["layer-"+str(index+1).zfill(2)+".gbr"]
        expected=_cam_entities(projection,identity)
        actual={}
        for item in value["objects"]:
            source=item["attributes"].get("TraceWaveId",[])
            require(len(source)==1 and source[0] not in actual,"CAM 원본 객체 대응이 누락되거나 중복됐습니다.")
            actual[source[0]]=item
        require(set(actual)==set(expected),"CAM 실제 객체와 원문 객체 목록이 다릅니다.")
        for source,(net,loops) in expected.items():
            item=actual[source]
            require(item["polarity"]=="dark" and item["attributes"].get(".N")==[nets.get(net,"")],"CAM 객체의 net/이미지 polarity가 다릅니다.")
            checks.append(compare_regions(gerber_region(item),polygonize(loops)))
    expected_holes={item["id"]:item for item in projection["mechanical"]["holes"]}
    for shape in projection["shapes"]:
        if shape["kind"]=="via":
            expected_holes[shape["id"]]={"shape":{"kind":"circle","center_mm":shape["center_mm"],"diameter_mm":shape["finished_hole_diameter_mm"]},"plating":{"state":"plated"}}
    found=set()
    for name,value in parsed.items():
        if not name.endswith(".xnc"):
            continue
        for hole in value["holes"]:
            ids=hole["attributes"].get("TraceWaveId",[])
            require(len(ids)==1 and ids[0] in expected_holes and ids[0] not in found,"XNC 원본 홀 대응이 다릅니다.")
            found.add(ids[0]);expected=expected_holes[ids[0]];shape=expected["shape"]
            require(value["plating"]==expected["plating"]["state"],"XNC 도금 분류가 다릅니다.")
            if shape["kind"]=="circle":
                require(hole["kind"]=="circle" and _close(hole["center_mm"],shape["center_mm"]) and _close(hole["finished_diameter_mm"],shape["diameter_mm"]),"XNC 원형 홀의 완성 치수가 다릅니다.")
            else:
                require(hole["kind"]=="slot" and _close(hole["finished_width_mm"],shape["finished_width_mm"]),"XNC 슬롯 폭이 다릅니다.")
                center=[(a+b)/2 for a,b in zip(hole["start_mm"],hole["end_mm"])]
                require(_close(center,shape["center_mm"]) and _close(math.dist(hole["start_mm"],hole["end_mm"])+hole["finished_width_mm"],shape["finished_length_mm"]),"XNC 슬롯의 중심/전체 길이가 다릅니다.")
                theta=math.radians(shape["rotation_deg"]);half=(shape["finished_length_mm"]-shape["finished_width_mm"])/2
                a=[shape["center_mm"][0]-half*math.cos(theta),shape["center_mm"][1]-half*math.sin(theta)]
                b=[shape["center_mm"][0]+half*math.cos(theta),shape["center_mm"][1]+half*math.sin(theta)]
                require((_close(hole["start_mm"],a) and _close(hole["end_mm"],b)) or (_close(hole["start_mm"],b) and _close(hole["end_mm"],a)),"XNC 슬롯 방향이 원문과 다릅니다.")
    require(found==set(expected_holes),"XNC에 실제 홀 일부가 빠졌습니다.")
    return {"reader":"bounded Gerber/XNC/Job parsers","files":len(files),"holes":len(found),"regions":checks}
