"""! @brief 출력기를 호출하지 않고 Gerber/XNC/Job 원문의 유한 문법과 실제 기하를 읽는다."""
from copy import deepcopy
import json
import math
import re
from pathlib import PurePosixPath

from rfad.domain.errors import ProjectError

MAX_BYTES=16*1024*1024
MAX_OPERATIONS=65536


def _error(message,code="E_UNSUPPORTED"):
    """! @brief 미지원 문법과 모호한 단위를 성공으로 넘기지 않는다."""
    raise ProjectError(code,message)


def _text(raw):
    """! @brief 압축/외부 참조 없이 유한 UTF-8 원문만 읽는다."""
    if type(raw) is not bytes or not 0<len(raw)<=MAX_BYTES:
        _error("CAM 원문 바이트 상한을 벗어났습니다.","E_RESOURCE")
    try:
        return raw.decode("utf-8-sig",errors="strict")
    except UnicodeError as error:
        raise ProjectError("E_SCHEMA","CAM 원문 인코딩이 유효하지 않습니다.") from error


def _decimal(text):
    """! @brief 지수/비유한 수치와 과도한 좌표를 명시 거절한다."""
    if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)",text):
        _error("CAM decimal 문법이 유효하지 않습니다.","E_SCHEMA")
    value=float(text)
    if not math.isfinite(value) or abs(value)>1e6:
        _error("CAM 수치가 유한 상한을 벗어났습니다.","E_RESOURCE")
    return value


def _unescape(value):
    """! @brief Gerber 지정 Unicode escape를 해석하고 임의 escape는 거절한다."""
    def replace(match):
        """! @brief 예약문자를 원문 codepoint로 돌린다."""
        code=int(match.group(1) or match.group(2),16)
        if code>0x10ffff or 0xd800<=code<=0xdfff:
            _error("Gerber Unicode codepoint가 유효하지 않습니다.","E_SCHEMA")
        return chr(code)
    residue=re.sub(r"\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}","",value)
    if "\\" in residue:
        _error("지원하지 않는 Gerber escape입니다.")
    return re.sub(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})",replace,value)


def _attribute(command,dictionaries):
    """! @brief 파일/aperture/객체 속성의 소유 범위를 분리한다."""
    kind=command[:2]
    if kind=="TD":
        key=command[2:]
        for values in (dictionaries["TA"],dictionaries["TO"]):
            if key:
                values.pop(key,None)
            else:
                values.clear()
        return
    fields=command[2:].split(",")
    if not fields[0] or len(fields)>32 or any(len(item)>8192 for item in fields):
        _error("Gerber 속성이 유한 범위를 벗어났습니다.","E_RESOURCE")
    dictionaries[kind][fields[0]]=[_unescape(value) for value in fields[1:]]


def read_gerber(raw):
    """! @brief 절대좌표 line/arc/region/표준 flash와 X2 속성을 읽는다."""
    source=_text(raw)
    tokens=[]
    position=0
    while position<len(source):
        if source[position].isspace():
            position+=1
            continue
        extended=source[position]=="%"
        end=source.find("%" if extended else "*",position+1)
        if end<0:
            _error("Gerber 명령 구분자가 닫히지 않았습니다.","E_SCHEMA")
        body=source[position+1:end] if extended else source[position:end]
        for command in body.split("*") if extended else [body]:
            if command.strip():
                tokens.append((extended,command.strip()))
        position=end+1
        if len(tokens)>MAX_OPERATIONS*4:
            _error("Gerber 명령 수 상한을 초과했습니다.","E_RESOURCE")
    attributes={"TF":{},"TA":{},"TO":{}}
    apertures,objects={},[]
    format_spec,unit,scale=None,None,None
    current=None
    selected=None
    interpolation=None
    polarity="dark"
    region=None
    contour=[]
    ended=False
    modal=None
    quadrant=False
    def finish_contour():
        """! @brief 열린 영역을 자동 닫아 원문 손실을 숨기지 않는다."""
        nonlocal contour
        if contour:
            if math.dist(contour[0]["start"],contour[-1]["end"])>3e-6:
                _error("Gerber region contour가 닫히지 않았습니다.","E_GEOMETRY")
            region.append(contour)
            contour=[]
    for extended,command in tokens:
        if ended:
            _error("Gerber 종료 뒤 데이터가 있습니다.","E_SCHEMA")
        if command.startswith("G04"):
            continue
        if extended:
            if command[:2] in attributes or command.startswith("TD"):
                _attribute(command,attributes)
            elif command.startswith("FS"):
                match=re.fullmatch(r"FS([LT])AX([1-6])([1-6])Y([1-6])([1-6])",command)
                if not match or format_spec is not None:
                    _error("Gerber 좌표는 한 번 선언한 절대 1~6자리 형식이어야 합니다.")
                format_spec=match.groups()
            elif command in ("MOMM","MOIN"):
                if unit is not None:
                    _error("Gerber 단위를 중간에 바꿀 수 없습니다.")
                unit="mm" if command=="MOMM" else "inch"
                scale=1 if unit=="mm" else 25.4
            elif command.startswith("ADD"):
                match=re.fullmatch(r"ADD(\d+)([CRO]),(.+)",command)
                if not match or scale is None:
                    _error("표준 원/사각/oval aperture 이외의 Gerber aperture는 미지원입니다.")
                identity=int(match[1]);values=[_decimal(item)*scale for item in match[3].split("X")]
                expected=1 if match[2]=="C" else 2
                if identity<10 or identity in apertures or len(values)!=expected or any(value<0 or value==0 and match[2]!="C" for value in values):
                    _error("Gerber aperture 정의가 유효하지 않습니다.","E_SCHEMA")
                apertures[identity]={"kind":match[2],"size_mm":values,"attributes":deepcopy(attributes["TA"])}
            elif command in ("LPD","LPC"):
                if region is not None:
                    _error("region 중간 polarity 변경은 허용하지 않습니다.")
                polarity="dark" if command=="LPD" else "clear"
            elif command in ("LMN","LR0","LS1"):
                pass
            else:
                _error("지원하지 않는 Gerber 확장 명령입니다: "+command[:40])
            continue
        if command in ("G01","G1","G02","G2","G03","G3"):
            interpolation={1:"line",2:"cw",3:"ccw"}[int(command[1:])]
            continue
        if command=="G75":
            quadrant=True
            continue
        if command=="G36":
            if region is not None:
                _error("Gerber region이 중첩되었습니다.","E_SCHEMA")
            region=[];contour=[]
            continue
        if command=="G37":
            if region is None:
                _error("시작 없는 Gerber region 종료입니다.","E_SCHEMA")
            finish_contour()
            if not region:
                _error("빈 Gerber region은 미지원입니다.")
            objects.append({"kind":"region","loops":region,"polarity":polarity,"attributes":deepcopy(attributes["TO"])})
            region=None
            continue
        if command=="M02":
            if region is not None:
                _error("Gerber region이 열린 채 종료되었습니다.","E_SCHEMA")
            ended=True
            continue
        match=re.fullmatch(r"D(\d+)",command)
        if match and int(match[1])>=10:
            selected=int(match[1])
            if selected not in apertures:
                _error("선택한 Gerber aperture가 없습니다.","E_SCHEMA")
            continue
        inline=re.match(r"^G0?([123])(?=[XYIJ])",command)
        if inline:
            interpolation={1:"line",2:"cw",3:"ccw"}[int(inline[1])]
            command=command[inline.end():]
        fields=re.findall(r"([XYIJD])([-+]?\d+)",command)
        if "".join(key+value for key,value in fields)!=command or len({key for key,_ in fields})!=len(fields) or format_spec is None or scale is None:
            _error("Gerber 좌표 또는 단위 선언이 유효하지 않습니다.","E_SCHEMA")
        fields=dict(fields)
        operation=int(fields.pop("D",modal or "0"));modal=str(operation)
        if operation not in (1,2,3):
            _error("Gerber D 명령이 유효하지 않습니다.","E_SCHEMA")
        def coord(key,axis):
            """! @brief 선언 zero suppression/단위만 적용한다."""
            token=fields.get(key)
            if token is None:
                return None
            integer,fraction=int(format_spec[1+2*axis]),int(format_spec[2+2*axis])
            sign=-1 if token.startswith("-") else 1
            digits=token.lstrip("+-")
            if len(digits)>integer+fraction:
                _error("Gerber 좌표가 선언 자리수를 초과했습니다.","E_RESOURCE")
            digits=digits.ljust(integer+fraction,"0") if format_spec[0]=="T" else digits
            return sign*int(digits)*10**(-fraction)*scale
        coordinates=[coord(key,axis) for axis,key in enumerate(("X","Y"))]
        if current is None and (operation==1 or any(value is None for value in coordinates)):
            _error("초기 Gerber 현재점은 미정입니다. 첫 이동/flash의 X/Y를 명시해야 합니다.","E_SCHEMA")
        target=[current[axis] if value is None else value for axis,value in enumerate(coordinates)]
        if operation==2:
            if region is not None:
                finish_contour()
        elif operation==3:
            if region is not None or selected is None:
                _error("Gerber flash의 region/aperture 상태가 유효하지 않습니다.","E_SCHEMA")
            objects.append({"kind":"flash","center_mm":target,"aperture":deepcopy(apertures[selected]),"polarity":polarity,"attributes":deepcopy(attributes["TO"])})
        else:
            if interpolation is None:
                _error("Gerber 보간 모드는 미정입니다. 그리기 전에 G01/G02/G03을 명시해야 합니다.","E_SCHEMA")
            edge={"kind":"line","start":list(current),"end":target}
            if interpolation!="line":
                if not quadrant:
                    _error("단일 quadrant 원호는 초기 Gerber 읽기 profile 밖입니다.")
                center=[current[0]+(coord("I",0) or 0),current[1]+(coord("J",1) or 0)]
                radius=math.dist(center,current)
                if radius<=0 or abs(radius-math.dist(center,target))>5e-6:
                    _error("Gerber 원호 중심과 끝 반지름이 일치하지 않습니다.","E_GEOMETRY")
                start=math.degrees(math.atan2(current[1]-center[1],current[0]-center[0]))
                end=math.degrees(math.atan2(target[1]-center[1],target[0]-center[0]))
                sweep=(end-start)%360 if interpolation=="ccw" else -((start-end)%360)
                if abs(sweep)<1e-12:
                    sweep=360 if interpolation=="ccw" else -360
                edge.update(kind="arc",center=center,radius=radius,start_deg=start,sweep_deg=sweep)
            if region is not None:
                contour.append(edge)
            else:
                if selected is None or apertures[selected]["kind"]!="C":
                    _error("영역 밖 draw는 원형 aperture만 지원합니다.")
                objects.append({"kind":"stroke","edge":edge,"width_mm":apertures[selected]["size_mm"][0],"polarity":polarity,"attributes":deepcopy(attributes["TO"])})
        current=target
        if len(objects)+sum(len(loop) for loop in region or [])+len(contour)>MAX_OPERATIONS:
            _error("Gerber 기하 수가 상한을 초과했습니다.","E_RESOURCE")
    if not ended or scale is None or format_spec is None:
        _error("Gerber 단위/형식/종료가 누락되었습니다.","E_SCHEMA")
    return {"schema":"rfad.gerber-read/0.1","unit":unit,"coordinate_format":list(format_spec),"file_attributes":attributes["TF"],"objects":objects,"losses":[]}


def read_xnc(raw):
    """! @brief 명시 decimal mm/inch와 직선 slot만 읽고 실제 공구 지름은 미정으로 둔다."""
    lines=[line.strip() for line in _text(raw).splitlines() if line.strip()]
    if not lines or lines[0]!="M48":
        _error("XNC M48 header가 없습니다.","E_SCHEMA")
    attributes={"TF":{},"TA":{},"TO":{}}
    tools,holes={},[]
    scale=None;unit=None;header=True;selected=None;mode=None;down=False;current=None;ended=False
    for line in lines[1:]:
        if ended:
            _error("XNC M30 뒤 데이터가 있습니다.","E_SCHEMA")
        if line.startswith(";"):
            if line.startswith("; #@! "):
                _attribute(line[6:].strip(),attributes)
            continue
        if header:
            if line in ("METRIC","INCH","METRIC,TZ","INCH,TZ","METRIC,LZ","INCH,LZ"):
                if scale is not None:
                    _error("XNC 단위가 중복 선언되었습니다.")
                unit="mm" if line.startswith("METRIC") else "inch";scale=1 if unit=="mm" else 25.4
            elif line=="%":
                header=False
            elif line=="FMAT,2":
                pass
            else:
                match=re.fullmatch(r"T(\d{1,2})C(.+)",line)
                if not match or scale is None:
                    _error("지원하지 않는 XNC header입니다: "+line[:40])
                identity=int(match[1]);diameter=_decimal(match[2])*scale
                if identity==0 or identity in tools or diameter<=0:
                    _error("XNC tool 정의가 유효하지 않습니다.","E_SCHEMA")
                tools[identity]=diameter
            continue
        if scale is None:
            _error("XNC 단위를 추정하지 않습니다.","E_SCHEMA")
        if line in ("G90","M71","M72"):
            if line=="M71" and unit!="mm" or line=="M72" and unit!="inch":
                _error("XNC 본문 단위가 header와 다릅니다.","E_SCHEMA")
            continue
        if line=="M30":
            if down:
                _error("XNC tool이 내려간 채 종료되었습니다.","E_SCHEMA")
            ended=True
            continue
        if line=="G05":
            if down:
                _error("rout 중 drill 전환입니다.","E_SCHEMA")
            mode="drill"
            continue
        if line in ("M15","M16"):
            if mode!="rout" or current is None or down==(line=="M15"):
                _error("XNC tool 상하 상태가 유효하지 않습니다.","E_SCHEMA")
            down=line=="M15"
            continue
        match=re.fullmatch(r"T(\d{1,2})",line)
        if match:
            if down or int(match[1]) not in tools:
                _error("XNC tool 선택이 유효하지 않습니다.","E_SCHEMA")
            selected=int(match[1])
            continue
        match=re.fullmatch(r"(G00|G01)?X([-+]?\d+(?:\.\d*)?)Y([-+]?\d+(?:\.\d*)?)",line)
        if not match or selected is None:
            _error("XNC profile은 명시 decimal 좌표의 drill/직선 rout만 지원합니다.")
        target=[_decimal(match[2])*scale,_decimal(match[3])*scale]
        if match[1]=="G00":
            if down:
                _error("XNC tool이 내려간 채 급속 이동했습니다.","E_SCHEMA")
            mode="rout"
        elif match[1]=="G01":
            if not down or mode!="rout" or current is None or math.dist(current,target)<=0:
                _error("XNC 직선 rout 상태가 유효하지 않습니다.","E_SCHEMA")
            holes.append({"kind":"slot","start_mm":list(current),"end_mm":target,"finished_width_mm":tools[selected],"tool_diameter_mm":None,"attributes":deepcopy(attributes["TO"])})
        elif mode=="drill":
            holes.append({"kind":"circle","center_mm":target,"finished_diameter_mm":tools[selected],"tool_diameter_mm":None,"attributes":deepcopy(attributes["TO"])})
        else:
            _error("drill mode 없이 drill 좌표가 나타났습니다.","E_SCHEMA")
        current=target
        if len(holes)>MAX_OPERATIONS:
            _error("XNC 홀 수가 상한을 초과했습니다.","E_RESOURCE")
    if not ended:
        _error("XNC 종료가 누락되었습니다.","E_SCHEMA")
    function=attributes["TF"].get(".FileFunction",[])
    plating="plated" if function and function[0]=="Plated" else "unplated" if function and function[0]=="NonPlated" else "unknown"
    return {"schema":"rfad.xnc-read/0.1","unit":unit,"file_attributes":attributes["TF"],"plating":plating,"holes":holes,"losses":[]}


def read_job(raw,files=None):
    """! @brief Job의 로컬 상대 파일만 읽고 이름으로 층/도금을 추정하지 않는다."""
    text=_text(raw);depth=0;quoted=False;escaped=False
    for char in text:
        if quoted:
            if escaped:
                escaped=False
            elif char=="\\":
                escaped=True
            elif char=='"':
                quoted=False
        elif char=='"':
            quoted=True
        elif char in "[{":
            depth+=1
            if depth>32:
                _error("Job 중첩 깊이가 상한을 초과했습니다.","E_RESOURCE")
        elif char in "]}":
            depth-=1
    def pairs(items):
        """! @brief 중복 JSON 키로 앞선 원문 의미를 숨기지 못하게 한다."""
        result={}
        for key,value in items:
            if key in result:
                _error("Job JSON 키가 중복됩니다.","E_SCHEMA")
            result[key]=value
        return result
    def constant(value):
        """! @brief JSON 밖 비유한 상수를 허용하지 않는다."""
        _error("Job 비유한 수치는 지원하지 않습니다.","E_SCHEMA")
    try:
        value=json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    except ValueError as error:
        raise ProjectError("E_SCHEMA","Gerber Job JSON 문법이 유효하지 않습니다.") from error
    pending=[value];count=0
    while pending:
        item=pending.pop();count+=1
        if count>200000 or type(item) is str and len(item)>8192:
            _error("Job 문자열/항목 수가 상한을 초과했습니다.","E_RESOURCE")
        if type(item) is float and not math.isfinite(item):
            _error("Job 비유한 수치는 지원하지 않습니다.","E_SCHEMA")
        if type(item) is dict:
            pending.extend(item.keys());pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    if type(value) is not dict or type(value.get("FilesAttributes")) is not list or not 1<=len(value["FilesAttributes"])<=40:
        _error("Gerber Job 파일 목록이 유효하지 않습니다.","E_SCHEMA")
    seen=set()
    for item in value["FilesAttributes"]:
        if type(item) is not dict or type(item.get("Path")) is not str:
            _error("Job 파일 항목이 유효하지 않습니다.","E_SCHEMA")
        name=item["Path"];path=PurePosixPath(name)
        if not 1<=len(name)<=120 or any(ord(char)<32 for char in name) or path.is_absolute() or len(path.parts)!=1 or name in (".","..") or ":" in name or "\\" in name or name.casefold() in seen:
            _error("Job 외부 경로/중복 파일은 허용하지 않습니다.","E_SCHEMA")
        seen.add(name.casefold())
        if files is not None and name not in files:
            _error("Job이 참조하는 원문 파일이 없습니다.","E_SCHEMA")
    return {"schema":"rfad.gerber-job-read/0.1","job":value,"losses":[],"manufacturing_values_inferred":False}
