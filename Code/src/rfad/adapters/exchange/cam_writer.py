"""! @brief 해석형 Gerber X2와 완성 치수 XNC, 기본 Job을 같은 world 원점으로 쓴다."""
import hashlib
import json
import math

from rfad.domain.errors import ProjectError
from rfad.domain import drawing_layout as geometry
from rfad.adapters.exchange.sexpr import decimal


def field(value):
    """! @brief Gerber 필드 구분자/제어문자를 명시 Unicode escape로 보존한다."""
    if type(value) is not str or len(value)>8192:
        raise ProjectError("E_RESOURCE","CAM 속성 문자열이 유한 상한을 벗어났습니다.")
    return "".join(("\\u"+format(ord(char),"04X") if ord(char)<=65535 else "\\U"+format(ord(char),"08X")) if char in "%*,\\" or ord(char)<32 else char for char in value)


def coordinate(value):
    """! @brief 6.6 mm 좌표의 1 nm 양자화를 기록한다."""
    if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>=1e6:
        raise ProjectError("E_RESOURCE","Gerber 6.6 좌표 범위를 벗어났습니다.")
    return str(round(value*1e6))


def _xy(point):
    """! @brief bottom도 mirror하지 않고 모든 층을 공통 world 축으로 쓴다."""
    return "X"+coordinate(point[0])+"Y"+coordinate(point[1])


def _end(edge, fraction=1):
    """! @brief 원호의 해석적 점을 명시 단위로 계산한다."""
    if edge["kind"]=="line":
        return edge["end"] if fraction else edge["start"]
    angle=math.radians(edge["start_deg"]+fraction*edge["sweep_deg"])
    return [edge["center"][0]+edge["radius"]*math.cos(angle),edge["center"][1]+edge["radius"]*math.sin(angle)]


def _contours(loops, region=True):
    """! @brief region 내부의 별도 contour로 구멍을 보존하며 기존 다른 객체를 지우지 않는다."""
    output=["G36*"] if region else []
    for loop in loops:
        if not loop:
            continue
        start=_end(loop[0],0)
        output.extend(("G01*",_xy(start)+"D02*"))
        for edge in loop:
            if edge["kind"]=="line":
                output.extend(("G01*",_xy(edge["end"])+"D01*"))
            else:
                pieces=2 if abs(edge["sweep_deg"])>=359.999999 else 1
                for index in range(pieces):
                    a,b=_end(edge,index/pieces),_end(edge,(index+1)/pieces)
                    output.extend(("G03*" if edge["sweep_deg"]>0 else "G02*",_xy(b)+"I"+coordinate(edge["center"][0]-a[0])+"J"+coordinate(edge["center"][1]-a[1])+"D01*"))
        if math.dist(_end(loop[-1]),start)>1e-6:
            raise ProjectError("E_GEOMETRY","CAM region 경계가 닫히지 않았습니다.")
    if region:
        output.append("G37*")
    return output


def _header(function, polarity, project_id, width=.001):
    """! @brief FilePolarity는 mask 개구의 부재 의미이며 LP 이미지 연산과 분리한다."""
    return ["G04 TraceWave Studio explicit geometry; not manufacturing qualification*", "%FSLAX66Y66*%", "%MOMM*%", "%TF.GenerationSoftware,TraceWave,Studio,0.1*%", "%TF.FileFunction,"+function+"*%", "%TF.FilePolarity,"+polarity+"*%", "%TF.SameCoordinates,"+field(project_id)+"*%", "%LPD*%", "%ADD10C,"+decimal(width)+"*%", "D10*", "G75*"]


def _net_name(projection, identity):
    """! @brief 미연결 net과 실제 net 원문을 추정 없이 구분한다."""
    if identity is None:
        return ""
    return next(item["name"] for item in projection["source_semantics"]["nets"] if item["id"]==identity)


def gerber(projection, layer):
    """! @brief 한 층의 원본 객체별 해석 경계와 net/source 속성을 출력한다."""
    copper=sorted((item for item in projection["layers"] if item["role"]=="conductor"),key=lambda item:item["z_min_mm"],reverse=True)
    identity=layer["id"]
    if layer.get("role")=="conductor":
        index=next(i for i,item in enumerate(copper) if item["id"]==identity)
        function="Copper,L"+str(index+1)+","+("Top" if index==0 else "Bot" if index==len(copper)-1 else "Inr")
        polarity="Positive"
    else:
        if layer["use_state"]!="used":
            raise ProjectError("E_UNSUPPORTED","CAM에 선택한 artwork의 사용 상태가 확정되지 않았습니다.")
        function=("Soldermask" if layer["role"]=="solder_mask" else "Paste")+","+("Top" if layer["side"]=="top" else "Bot")
        polarity="Negative" if layer["role"]=="solder_mask" else "Positive"
    output=_header(function,polarity,projection["source_semantics"]["project_id"])
    entities=[]
    if layer.get("role")=="conductor":
        for shape in projection["shapes"]:
            if shape["kind"]=="via":
                z0=next(item["z_min_mm"] for item in projection["layers"] if item["id"]==shape["layer_id"])
                z1=next(item["z_min_mm"] for item in projection["layers"] if item["id"]==shape["end_layer_id"])
                if not min(z0,z1)<=layer["z_min_mm"]<=max(z0,z1):
                    continue
            elif shape["layer_id"]!=identity:
                continue
            loops=geometry.copper_loops(projection,shape)
            native=shape if shape["kind"] in ("line_path","arc_path","pad") and loops==geometry.shape_loops(shape) else None
            entities.append((shape["id"],shape["net_id"],loops,native))
        for hole in projection["mechanical"]["holes"]:
            if hole["plating"]["state"]=="plated":
                entities.append((hole["id"],hole["plating"]["net_id"],geometry.mechanical_shell(hole),None))
    else:
        for aperture in projection["apertures"]:
            if aperture["artwork_layer_id"]==identity:
                entities.append((aperture["id"],None,geometry.mechanical_loops(aperture["shape"]),None))
    next_aperture=11
    for entity,net,loops,native in entities:
        output.extend(("%TOTraceWaveId,"+field(entity)+"*%","%TO.N,"+field(_net_name(projection,net))+"*%"))
        if native is not None and native["kind"] in ("line_path","arc_path"):
            output.extend(("%ADD"+str(next_aperture)+"C,"+decimal(native["width_mm"])+"*%","D"+str(next_aperture)+"*"));next_aperture+=1
            if native["kind"]=="line_path":
                output.extend(("G01*",_xy(native["start_mm"])+"D02*",_xy(native["end_mm"])+"D01*"))
            else:
                edge={"kind":"arc","center":native["center_mm"],"radius":native["radius_mm"],"start_deg":native["start_angle_deg"],"sweep_deg":native["sweep_angle_deg"]}
                a,b=_end(edge,0),_end(edge)
                output.extend(("G01*",_xy(a)+"D02*","G03*" if edge["sweep_deg"]>0 else "G02*",_xy(b)+"I"+coordinate(edge["center"][0]-a[0])+"J"+coordinate(edge["center"][1]-a[1])+"D01*"))
        elif native is not None and native["kind"]=="pad" and (native["pad_shape"]=="circle" or abs(native["rotation_deg"]%180)<1e-10):
            shape="C" if native["pad_shape"]=="circle" else "R"
            size=decimal(native["size_mm"][0])+("X"+decimal(native["size_mm"][1]) if shape=="R" else "")
            output.extend(("%ADD"+str(next_aperture)+shape+","+size+"*%","D"+str(next_aperture)+"*",_xy(native["center_mm"])+"D03*"));next_aperture+=1
        else:
            output.extend(_contours(loops))
        output.append("%TD*%")
    output.append("M02*")
    return ("\n".join(output)+"\n").encode("utf-8"),function,polarity


def outline(projection):
    """! @brief 실제 board 외곽과 cutout을 명시 profile 중심선으로 기록한다."""
    output=_header("Profile,NP","Positive",projection["source_semantics"]["project_id"],.05)
    output.append("%TOTraceWaveId,"+field(projection["board"]["id"])+"*%")
    output.extend(_contours(geometry.board_loops(projection["board"]),False))
    for item in projection["mechanical"]["cutouts"]:
        output.extend(("%TD*%","%TOTraceWaveId,"+field(item["id"])+"*%"))
        output.extend(_contours(geometry.mechanical_loops(item["shape"]),False))
    output.append("M02*")
    return ("\n".join(output)+"\n").encode("utf-8")


def drill(projection, plated):
    """! @brief XNC C는 도금 후 완성 지름이며 실제 공구 지름을 발명하지 않는다."""
    copper=[item for item in projection["layers"] if item["role"]=="conductor"]
    rows=[]
    for hole in projection["mechanical"]["holes"]:
        state=hole["plating"]["state"]
        if state=="unknown":
            raise ProjectError("E_UNSUPPORTED","도금 미정 홀을 PTH/NPTH에 자동 분류하지 않습니다.")
        if (state=="plated")==plated:
            rows.append({"id":hole["id"],"shape":hole["shape"],"net_id":hole["plating"]["net_id"]})
    if plated:
        for shape in projection["shapes"]:
            if shape["kind"]=="via":
                rows.append({"id":shape["id"],"shape":{"kind":"circle","center_mm":shape["center_mm"],"diameter_mm":shape["finished_hole_diameter_mm"]},"net_id":shape["net_id"]})
    if not rows:
        return None
    sizes=sorted({round(row["shape"].get("diameter_mm",row["shape"].get("finished_width_mm")),6) for row in rows})
    if len(sizes)>99 or any(size<=0 for size in sizes):
        raise ProjectError("E_RESOURCE","XNC tool 수 또는 양자화된 완성 폭이 유효하지 않습니다.")
    tools={size:index+1 for index,size in enumerate(sizes)}
    function=("Plated" if plated else "NonPlated")+",1,"+str(len(copper))+","+("PTH" if plated else "NPTH")
    output=["M48","; #@! TF.FileFunction,"+function,"; #@! TF.GenerationSoftware,TraceWave,Studio,0.1","METRIC"]
    output.extend("T"+str(tools[size]).zfill(2)+"C"+format(size,".6f") for size in sizes)
    output.append("%")
    for row in rows:
        shape=row["shape"]
        width=shape.get("diameter_mm",shape.get("finished_width_mm"))
        output.extend(("; #@! TOTraceWaveId,"+field(row["id"]),"T"+str(tools[round(width,6)]).zfill(2)))
        def xy(point):
            """! @brief XNC 명시 decimal mm를 사용해 zero suppression 추정을 피한다."""
            return "X"+format(point[0],".6f")+"Y"+format(point[1],".6f")
        if shape["kind"]=="circle":
            output.extend(("G05",xy(shape["center_mm"])))
        elif shape["kind"]=="capsule":
            angle=math.radians(shape["rotation_deg"])
            half=(shape["finished_length_mm"]-width)/2
            a=[shape["center_mm"][0]-half*math.cos(angle),shape["center_mm"][1]-half*math.sin(angle)]
            b=[shape["center_mm"][0]+half*math.cos(angle),shape["center_mm"][1]+half*math.sin(angle)]
            output.extend(("G00"+xy(a),"M15","G01"+xy(b),"M16"))
        else:
            raise ProjectError("E_UNSUPPORTED","XNC profile은 원형 홀과 직선 캡슐 슬롯만 지원합니다.")
    output.append("M30")
    return ("\n".join(output)+"\n").encode("utf-8"),function


def package(projection, layer_ids):
    """! @brief 명시 층 선택과 항상 포함되는 외곽/드릴을 한 Job으로 묶는다."""
    known={item["id"]:item for item in [*projection["layers"],*projection["artwork_layers"]] if item.get("role") in ("conductor","solder_mask","solder_paste")}
    if type(layer_ids) is not list or not layer_ids or len(layer_ids)!=len(set(layer_ids)) or any(identity not in known for identity in layer_ids):
        raise ProjectError("E_SCHEMA","CAM 층 선택은 중복 없는 알려진 층 목록이어야 합니다.")
    required={item["id"] for item in known.values() if item["role"]=="conductor" or item.get("use_state")=="used"}
    if set(layer_ids)!=required:
        raise ProjectError("E_UNSUPPORTED","이 CAM profile은 모든 실제 구리층과 사용이 확정된 artwork를 포함해야 합니다.")
    files,attributes={},[]
    for index,identity in enumerate(layer_ids):
        raw,function,polarity=gerber(projection,known[identity])
        name="layer-"+str(index+1).zfill(2)+".gbr"
        files[name]=raw
        attributes.append({"Path":name,"FileFunction":function,"FilePolarity":polarity})
    files["outline.gbr"]=outline(projection)
    attributes.append({"Path":"outline.gbr","FileFunction":"Profile,NP","FilePolarity":"Positive"})
    for plated,name in ((True,"plated.xnc"),(False,"nonplated.xnc")):
        result=drill(projection,plated)
        if result is not None:
            files[name],function=result
            attributes.append({"Path":name,"FileFunction":function,"FilePolarity":"Positive"})
    copper=[item for item in projection["layers"] if item["role"]=="conductor"]
    lower=min(item["z_min_mm"] for item in projection["layers"])
    upper=max(item["z_min_mm"]+item["thickness_mm"] for item in projection["layers"])
    stack=[]
    for layer in sorted(projection["layers"],key=lambda item:item["z_min_mm"],reverse=True):
        row={"Type":"Copper" if layer["role"]=="conductor" else "Dielectric","Name":layer["name"],"Thickness":layer["thickness_mm"]}
        material=projection.get("materials",{}).get(layer.get("material_id"))
        if material is not None:
            row["Material"]=material["name"]
            for source,key in (("epsilon_r","DielectricConstant"),("loss_tangent","LossTangent"),("conductivity_s_per_m","Conductivity")):
                if material.get(source) is not None:
                    row[key]=material[source]
        stack.append(row)
    bounds=geometry.board_bounds(projection["board"])
    job={"Header":{"GenerationSoftware":{"Vendor":"TraceWave","Application":"Studio","Version":"0.1"},"Comment":"Source values and unknowns are preserved in sidecar.json; no manufacturing qualification."},"GeneralSpecs":{"LayerNumber":len(copper),"BoardThickness":upper-lower,"Size":{"X":bounds[2]-bounds[0],"Y":bounds[3]-bounds[1]}},"MaterialStackup":stack,"FilesAttributes":attributes}
    files["fabrication.gbrjob"]=(json.dumps(job,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
    return files
