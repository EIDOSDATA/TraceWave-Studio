"""! @brief PCB/CAM worker의 고정 출력/재검수/원문 parser 진입점을 제공한다."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.domain.vendor_catalog import VENDOR_FORMATS
from rfad.adapters.exchange import cam_reader,cam_writer,kicad_reader,kicad_writer,pcb_verification

PROFILES={"kicad_pcb":"rfad.exchange.kicad-board/0.1","kicad_mod":"rfad.exchange.kicad-footprint/0.1","gerber_job":"rfad.exchange.cam/0.1"}
MAX_FILE_BYTES=16*1024*1024
MAX_PACKAGE_BYTES=64*1024*1024
MAX_FILES=43


def _hash(raw):
    """! @brief 원문 바이트 SHA를 snapshot canonical 내용 해시와 구분한다."""
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    """! @brief 링크/재분석 지점과 과대 파일을 native 읽기 전에 거절한다."""
    stat=path.lstat()
    if path.is_symlink() or getattr(stat,"st_file_attributes",0)&0x400 or not path.is_file() or stat.st_size>MAX_FILE_BYTES:
        raise ProjectError("E_RESOURCE","PCB 교환 파일의 종류 또는 크기가 유효하지 않습니다.")
    with path.open("rb") as stream:
        raw=stream.read(MAX_FILE_BYTES+1)
    if len(raw)>MAX_FILE_BYTES:
        raise ProjectError("E_RESOURCE","PCB 파일이 읽기 상한을 초과했습니다.")
    return raw


def _role(name):
    """! @brief 닫힌 profile의 파일명/역할만 게시하도록 한다."""
    values={"board.kicad_pcb":("pcb_geometry","application/x-kicad-pcb"),"board.kicad_pro":("recipient_settings","application/json"),"footprint.kicad_mod":("pcb_geometry","application/x-kicad-footprint"),"fabrication.gbrjob":("job","application/json"),"validation.json":("verification","application/json"),"sidecar.json":("source","application/json"),"plated.xnc":("drill","application/x-excellon"),"nonplated.xnc":("drill","application/x-excellon")}
    if name in values:
        return values[name]
    if name=="outline.gbr" or re.fullmatch(r"layer-(?:0[1-9]|[12]\d|3[0-6])\.gbr",name):
        return "fabrication_geometry","application/x-gerber"
    raise ProjectError("E_SCHEMA","PCB profile 밖의 출력 파일명입니다.")


def _record(name,raw):
    """! @brief 실제 bytes와 확정 역할을 한 파일 기록으로 묶는다."""
    role,media=_role(name)
    if not 0<len(raw)<=MAX_FILE_BYTES:
        raise ProjectError("E_RESOURCE","PCB 출력 파일이 비어 있거나 16 MiB를 초과했습니다.")
    return {"path":name,"role":role,"media_type":media,"bytes":len(raw),"sha256":_hash(raw)}


def _validate(data):
    """! @brief 기존 도면 profile과 새 PCB profile을 혼용하지 않는다."""
    name=data.get("format")
    if data.get("schema")!="rfad.exchange-input/0.1" or name not in PROFILES or data.get("profile")!=PROFILES[name] or data.get("projection",{}).get("schema")!="rfad.pcb-projection/0.1":
        raise ProjectError("E_SCHEMA","PCB 교환 입력 profile이 유효하지 않습니다.")
    required={"kicad_pcb":set(),"kicad_mod":{"footprint_id"},"gerber_job":{"layer_ids"}}[name]
    if type(data.get("options")) is not dict or set(data["options"])!=required:
        raise ProjectError("E_SCHEMA","PCB 교환 옵션이 선언 profile과 다릅니다.")
    if data["snapshot"]!=data["projection"]["snapshot"]:
        raise ProjectError("E_HASH","PCB 교환 snapshot 식별이 다릅니다.")
    layers=sorted(data["projection"]["layers"],key=lambda item:item["z_min_mm"])
    for previous,current in zip(layers,layers[1:]):
        if abs(current["z_min_mm"]-previous["z_min_mm"]-previous["thickness_mm"])>1e-6:
            raise ProjectError("E_UNSUPPORTED","PCB 교환 profile은 명시적으로 연속한 적층을 요구합니다. 미정 공극을 압축하거나 재료를 발명하지 않습니다.")
    return name


def _report(data,files):
    """! @brief 실제 parser 검사와 아직 수행하지 않은 제조/물리 수용을 구분한다."""
    name=data["format"]
    result=pcb_verification.cam(files,data["projection"],data["options"]) if name=="gerber_job" else pcb_verification.kicad(files["board.kicad_pcb" if name=="kicad_pcb" else "footprint.kicad_mod"],data["projection"],name,data["options"])
    if name=="kicad_pcb" and files["board.kicad_pro"]!=kicad_writer.project_settings():
        raise ProjectError("E_HASH","KiCad geometry-preserving 기술 설정이 다릅니다.")
    return {"schema":"rfad.exchange-verification/0.1","status":"passed_profile","profile":data["profile"],"checks":["원문 snapshot 및 객체/net/layer 대응","실제 parser 재열기","공통 원점과 mm 단위","원호/패드/구멍/슬롯의 기하","유효 구리 경계와 연결 성분","미정 제작/물성/공구 원문 보존"],"reader":result,"kernel_independent":False,"manufacturing_verified":False,"physics_verified":False,"recipient_application_verified":False,"limits":{"coordinate_quantum_mm":1e-6,"polygon_cache_chord_mm":1e-5,"reader_boundary_tolerance_mm":3e-5,"kicad_refill_boundary_tolerance_mm":.001,"kicad_refill_verified_by_this_report":False,"kicad_settings_are_manufacturing_rules":False,"manufacturing_tolerance":None,"tool_diameter_inferred":False,"original_rf_semantics":"sidecar_only","unknown_receiver_material_defaults":"not_authoritative","partial_cam_package":False}}


def generate(data,output,*,font_path=None):
    """! @brief 원본을 변경하지 않고 빈 소유 staging에 패키지를 생성/검사한다."""
    name=_validate(data);output=Path(output)
    if not output.is_dir() or output.is_symlink() or getattr(output.lstat(),"st_file_attributes",0)&0x400 or any(output.iterdir()):
        raise ProjectError("E_CONFLICT","PCB 출력은 빈 소유 staging 폴더가 필요합니다.")
    original=canonical_bytes(data)
    if name=="kicad_pcb":
        files={"board.kicad_pcb":kicad_writer.write_board(data["projection"]),"board.kicad_pro":kicad_writer.project_settings()}
    elif name=="kicad_mod":
        files={"footprint.kicad_mod":kicad_writer.write_footprint(data["projection"],data["options"]["footprint_id"])}
    else:
        files=cam_writer.package(data["projection"],data["options"]["layer_ids"])
    if len(files)+3>MAX_FILES or sum(len(raw) for raw in files.values())>MAX_PACKAGE_BYTES:
        raise ProjectError("E_RESOURCE","PCB 출력 파일 수 또는 총 크기 상한을 초과했습니다.")
    records=[_record(filename,raw) for filename,raw in files.items()]
    report=_report(data,files)
    files["validation.json"]=canonical_bytes(report);records.append(_record("validation.json",files["validation.json"]))
    sidecar={"schema":"rfad.exchange-sidecar/0.1","snapshot":deepcopy(data["snapshot"]),"profile":data["profile"],"run_id":data["run_id"],"input_sha256":_hash(original),"format":name,"source_semantics":deepcopy(data["projection"]["source_semantics"]),"options":deepcopy(data["options"]),"source_bindings":{"names":deepcopy(data["names"]),"dimensions":deepcopy(data["dimensions"])},"files":deepcopy(records),"verification":report}
    files["sidecar.json"]=canonical_bytes(sidecar);records.append(_record("sidecar.json",files["sidecar.json"]))
    manifest={"schema":"rfad.exchange-package/0.1","profile":data["profile"],"source_snapshot":deepcopy(data["snapshot"]),"run_id":data["run_id"],"status":"generated_unverified","format":name,"files":records,"verification":report}
    files["manifest.json"]=canonical_bytes(manifest)
    if sum(len(raw) for raw in files.values())>MAX_PACKAGE_BYTES or canonical_bytes(data)!=original:
        raise ProjectError("E_RESOURCE","PCB 패키지 상한 또는 원본 불변 조건을 위반했습니다.")
    for filename,raw in files.items():
        with (output/filename).open("xb") as stream:
            stream.write(raw)
    return manifest


def verify(data,output,manifest):
    """! @brief 원래 writer 패키지에 새 검수기를 적용하되 원본 파일은 수정하지 않는다."""
    name=_validate(data);output=Path(output)
    require=pcb_verification.require
    require(manifest.get("schema")=="rfad.exchange-package/0.1" and manifest.get("profile")==data["profile"] and manifest.get("run_id")==data["run_id"] and manifest.get("source_snapshot")==data["snapshot"] and manifest.get("format")==name,"PCB 패키지와 원래 입력 소유가 다릅니다.")
    records=manifest.get("files")
    require(type(records) is list and 3<=len(records)<MAX_FILES,"PCB 패키지 파일 수가 유효하지 않습니다.")
    files={}
    for item in records:
        require(type(item) is dict and set(item)=={"path","role","media_type","bytes","sha256"},"PCB 파일 기록 필드가 다릅니다.")
        filename=item["path"]
        require(filename not in files,"PCB 패키지에 중복 파일이 있습니다.")
        _role(filename)
        raw=_read(output/filename)
        require(_record(filename,raw)==item,"PCB 원본 출력 파일이 변경되었습니다.")
        files[filename]=raw
    require(sum(len(raw) for raw in files.values())<=MAX_PACKAGE_BYTES,"PCB 총 파일 크기를 초과했습니다.")
    sidecar=json.loads(files.pop("sidecar.json"));old_report=json.loads(files.pop("validation.json"))
    require(sidecar.get("source_semantics")==data["projection"]["source_semantics"] and sidecar.get("source_bindings")=={"names":data["names"],"dimensions":data["dimensions"]} and sidecar.get("input_sha256")==_hash(canonical_bytes(data)) and sidecar.get("snapshot")==data["snapshot"] and sidecar.get("profile")==data["profile"] and sidecar.get("options")==data["options"] and sidecar.get("run_id")==data["run_id"],"PCB sidecar 원문 또는 출처 hash가 다릅니다.")
    require(sidecar.get("verification")==old_report and manifest.get("verification")==old_report and sidecar.get("files")==[item for item in records if item["path"]!="sidecar.json"],"PCB 원래 검수/파일 참조가 일치하지 않습니다.")
    return _report(data,files)


def parse_package(files,format_name,options):
    """! @brief 원문 저장은 호출자 소유이며 여기서는 닫힌 parser 결과와 손실을 반환한다."""
    if type(files) is not dict or not 1<=len(files)<=40 or type(options) is not dict or options:
        raise ProjectError("E_SCHEMA","PCB 입력 파일 목록이 유효하지 않습니다.")
    if any(type(name) is not str or not 1<=len(name)<=120 or name in (".","..") or any(char in name for char in "/\\:") or any(ord(char)<32 for char in name) for name in files) or len({name.casefold() for name in files})!=len(files):
        raise ProjectError("E_SCHEMA","PCB 원문 파일명은 중복 없는 단일 상대 이름이어야 합니다.")
    if any(type(raw) is not bytes or not 0<len(raw)<=MAX_FILE_BYTES for raw in files.values()) or sum(len(raw) for raw in files.values())>MAX_FILE_BYTES:
        raise ProjectError("E_RESOURCE","PCB 입력 파일 바이트 상한을 초과했습니다.")
    records=[]
    if format_name in ("kicad_pcb","kicad_mod"):
        suffix=".kicad_pcb" if format_name=="kicad_pcb" else ".kicad_mod"
        names=[name for name in files if name.endswith(suffix)]
        if len(names)!=1 or len(files)!=1:
            raise ProjectError("E_UNSUPPORTED","KiCad 입력 profile은 board 또는 footprint 원문 파일 하나만 받습니다. 추가 파일을 조용히 생략하지 않습니다.")
        decoded=kicad_reader.read(files[names[0]])
        for item in decoded["shapes"]:
            if item["kind"]=="planar_region":
                decoded["losses"].append({"code":"zone_rules_not_in_edit_model","owner":item["id"],"original_policy":deepcopy(item.get("fill_settings")),"message":"명시 planar_region은 KiCad 자동 zone 재채움/연결/섬 정책을 계승하지 않습니다. 원문 정책과 cache는 파일에 보존됩니다.","raw_preserved":True})
        records.append({"path":names[0],"data":decoded})
    elif format_name == "ipc2581_revc" and len(files) == 1:
        from rfad.adapters.exchange.ipc2581_reader import read
        name, raw = next(iter(files.items()))
        if not name.lower().endswith(".xml"):
            raise ProjectError("E_UNSUPPORTED", "압축에서 꺼낸 IPC-2581 Rev C XML 원문 하나를 선택하십시오.")
        records.append({"path": name, "data": read(raw)})
    elif format_name in VENDOR_FORMATS and len(files) == 1:
        from rfad.adapters.exchange.vendor_pattern import read_pattern
        name, raw = next(iter(files.items()))
        records.append({"path": name, "data": read_pattern(raw, format_name)})
    elif format_name=="gerber_job":
        names=[name for name in files if name.endswith(".gbrjob")]
        if len(names)!=1:
            raise ProjectError("E_SCHEMA","Gerber Job 원문 파일이 하나 필요합니다.")
        job=cam_reader.read_job(files[names[0]],files)
        if set(files)!={names[0],*[item["Path"] for item in job["job"]["FilesAttributes"]]}:
            raise ProjectError("E_UNSUPPORTED","Job에서 참조하지 않은 첨부 파일을 조용히 생략하지 않습니다.")
        records.append({"path":names[0],"data":job})
        for item in job["job"]["FilesAttributes"]:
            raw=files[item["Path"]]
            value=cam_reader.read_xnc(raw) if raw.lstrip().startswith(b"M48") else cam_reader.read_gerber(raw)
            records.append({"path":item["Path"],"data":value})
    elif format_name in ("gerber_x2","xnc") and len(files)==1:
        name,raw=next(iter(files.items()))
        records.append({"path":name,"data":cam_reader.read_gerber(raw) if format_name=="gerber_x2" else cam_reader.read_xnc(raw)})
    else:
        raise ProjectError("E_UNSUPPORTED","지원하지 않는 PCB 입력 형식입니다.")
    return {"schema":"rfad.pcb-parse/0.1","format":format_name,"records":records,"mapping":[],"losses":[{"path":record["path"],**loss} for record in records for loss in record["data"].get("losses",[])],"raw_preservation_required":True,"manufacturing_verified":False,"physics_verified":False}
