"""! @brief 실제 제조 후보와 구분한 유한 원호/IFA 작업 흐름 검증 입력을 구성한다.

@details 명시적인 개발 시험 치수이며 문헌 재현이나 RF 추천 치수가 아니다.
기존 리터럴 fixture와 공개 프로젝트 명령만 재사용한다.
"""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from catalog_pcb_verification.common import call, wait
from rfad.domain.design_sweep import SCHEMA
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from verify_pcb_worker import create_fixture


CODE = Path(__file__).resolve().parents[1]
SOURCE = "fixture:stage9-explicit-software-workflow; not literature, manufacture or measurement"
FREQUENCIES = [2.4e9 + index * (2.4835e9 - 2.4e9) / 50 for index in range(51)]
CASES = ("ifa", "arc")


def quantity(value, unit="mm"):
    """! @brief 개발자가 고정한 시험 입력 출처를 실제 물성 근거와 구분한다."""
    return Quantity.from_value(value, unit, source_refs=[SOURCE]).to_dict()


def literal_case(kind):
    """! @brief 기존 가정 IFA 또는 이상 간극에 연결된 합성 원호를 새 사본으로 만든다."""
    if kind not in CASES:
        raise ValueError("지원하는 명시 검증 사례가 아닙니다.")
    source = CODE / "fixtures/ifa_feed_smoke.json"
    fixture = json.loads(source.read_bytes())
    document = fixture["document"]
    fixture["description"] = ("Finite software tuning workflow with explicit assumptions. "
        "Not the approved SMA/installed/measurement IFA or any nRF beacon reproduction. "
        "Manufacturing, calibration and measurement remain unknown. Source fixture SHA256=" + sha256(source.read_bytes()).hexdigest())
    document["metadata"]["name"] = "명시 " + ("IFA" if kind == "ifa" else "연결 원호") + " / 후보 채택 검증"
    document["metadata"]["description"] += " " + fixture["description"]
    fixture["settings"]["radiation"] = {"frequency_hz": [FREQUENCIES[25]], "theta_step_deg": 15, "phi_step_deg": 15}
    if kind == "arc":
        shapes = document["geometry"]
        ground = deepcopy(next(shape for shape in shapes if shape["role"] == "ground"))
        base = {key: value for key, value in ground.items() if key not in ("id", "kind", "role", "outer", "holes")}
        ground_net = str(uuid4())
        ground["net_id"] = ground_net
        document["nets"] = sorted([{"id": base["net_id"], "name": "명시 원호와 급전"},
                                   {"id": ground_net, "name": "명시 유한 접지"}], key=lambda item: item["id"])
        radiator = {**base, "id": str(uuid4()), "kind": "arc_path", "role": "radiator",
                    "center": [quantity(20), quantity(52)], "radius": quantity(5),
                    "start_angle": quantity(0, "deg"), "sweep_angle": quantity(180, "deg"), "width": quantity(1)}
        feed = {**base, "id": str(uuid4()), "kind": "line_path", "role": "feed",
                "start": [quantity(25), quantity(51.5)], "end": [quantity(25), quantity(52)], "width": quantity(1)}
        pad = {**base, "id": str(uuid4()), "kind": "pad", "role": "feed", "pad_shape": "rectangle",
               "center": [quantity(25), quantity(51.5)], "size": [quantity(1), quantity(1)], "rotation": quantity(0, "deg")}
        document["geometry"] = sorted([ground, radiator, feed, pad], key=lambda item: item["id"])
        document["ports"][0].update(positive_geometry_id=pad["id"], reference_geometry_id=ground["id"],
            reference_plane="explicit ideal local arc gap; no SMA, launch or measurement calibration",
            excitation_box={"start": [quantity(25), quantity(50), quantity(0.965)],
                            "stop": [quantity(25), quantity(51), quantity(0.965)]})
        document["metadata"]["description"] += (" Synthetic semicircle radius 5 mm, centre (20,52) mm, "
            "feed endpoint (25,52) mm and ideal 1 mm gap. Radius candidates 4.5/5/5.5 mm hold the feed endpoint fixed. "
            "These are finite test choices, not an antenna synthesis formula or recommended dimensions.")
    validate_project(document)
    return fixture


def create_case(service, kind):
    """! @brief 리터럴 생성 뒤 명시 매개변수/표현식/목표를 실제 원자 명령으로 연결한다."""
    fixture = literal_case(kind)
    context, path, _ = create_fixture(service, fixture)

    def read():
        """! @brief 검증 도구의 대조용 읽기이며 journal에 직접 쓰지 않는다."""
        return service._load(service.journal.read()["projects"][context["project_id"]])

    def command(kind, payload):
        """! @brief 모든 원본 변경은 서비스의 명령과 영수증 경계를 통과한다."""
        return call(service, "project.apply_command", {"expected_revision": read()["revision_id"],
            "command_id": str(uuid4()), "type": kind, "payload": payload}, context, mutation=True)

    unknown = deepcopy(read()["materials"][0])
    unknown.update(id=str(uuid4()), name="실제 납품 물성 미정 / 개발 시험 가정과 별도")
    for key in ("epsilon_r", "tan_delta", "conductivity"):
        old = unknown[key]
        unknown[key] = Quantity(None, old["dimension"], old["display_unit"], "missing",
                                ["실제 납품 자료 미확보; 시험 물성을 이 항목에 대입하지 않음"]).to_dict()
    command("material.set", {"material": unknown})

    def physical(section, changes):
        """! @brief 설치 치수와 재료를 채우지 않고 해석 제외 사유를 저장한다."""
        return call(service, "physical.setup.apply", {"expected_revision": read()["revision_id"],
            "command_id": str(uuid4()), "section": section, "operation": "set", "record_id": None,
            "reason": "실물 설치/배터리 자료 미확보; 기준 PCB만 계산", "changes": changes,
            "step_token": None}, context, mutation=True)

    scenario = physical("scenario", {"name": "설치 조건 미정 / 기준 PCB만 계산"})
    physical("part", {"name": "실물 배터리·외함 미정", "scenario_id": scenario["record_id"],
                      "visible": False, "include_in_em": False, "include_in_export": False})
    physical("activation", {"active_scenario_id": scenario["record_id"]})

    fixed, axis, derived = str(uuid4()), str(uuid4()), str(uuid4())
    is_ifa = kind == "ifa"
    command("parameter.set", {"id": fixed, "name": "고정 시작 X" if is_ifa else "고정 급전 X",
                              "quantity": quantity(5 if is_ifa else 25)})
    command("parameter.set", {"id": axis, "name": "방사 도체 길이" if is_ifa else "원호 중심선 반지름",
                              "quantity": quantity(26 if is_ifa else 5)})
    command("parameter.set_expression", {"id": derived, "name": "방사 끝 X" if is_ifa else "원호 중심 X",
        "expression": "fixed_x + size" if is_ifa else "fixed_x - size", "bindings": {"fixed_x": fixed, "size": axis},
        "dimension": "length", "display_unit": "mm"})
    shape = deepcopy(next(shape for shape in read()["geometry"] if shape["role"] == "radiator"))
    if is_ifa:
        shape["end"][0] = {"parameter_id": derived}
    else:
        shape["center"][0] = {"parameter_id": derived}
        shape["radius"] = {"parameter_id": axis}
    command("geometry.set", {"geometry": shape})
    document = read()
    port = document["ports"][0]
    target_id = str(uuid4())
    criteria = [{"metric": "s11_db", "operator": "le", "limit":
                 {"value": -10.0, "unit": "dB", "status": "user_entered", "source_refs": [SOURCE]}}]
    criteria += [{"metric": metric, "operator": "ge", "limit":
                  {"value": None, "unit": "1", "status": "missing", "source_refs": []}}
                 for metric in ("radiation_efficiency", "total_efficiency", "fractional_bandwidth")]
    target = {"id": target_id, "name": "2.4~2.4835 GHz 명시 표본 / 이상 간극", "physical_mode": "radiating_rf",
        "band": {"start": quantity(FREQUENCIES[0], "Hz"), "end": quantity(FREQUENCIES[-1], "Hz"),
                 "reference": quantity(FREQUENCIES[25], "Hz"),
                 "sampling": {"kind": "explicit", "frequencies": [quantity(f, "Hz") for f in FREQUENCIES]}},
        "port_id": port["id"], "reference_impedance": quantity(50, "ohm"), "criteria": criteria, "source_refs": [SOURCE]}
    command("target.set", {"target": target})
    values = (24, 26, 28) if is_ifa else (4.5, 5, 5.5)
    spec = {"schema": SCHEMA, "type": "grid_sweep", "name": document["metadata"]["name"], "combination": "cartesian",
        "variables": [{"kind": "parameter", "id": axis, "dimension": "length",
                       "values": [{"text": str(v), "unit": "mm", "source_refs": [SOURCE]} for v in values]}],
        "settings": fixture["settings"], "network": None, "target_ids": [target_id],
        "target_contexts": [{"target_id": target_id, "context": {"port_id": port["id"], "target_port_id": port["id"],
            "reference_plane": port["reference_plane"], "frequency_policy": "exact_only"}}],
        "budget": {"max_candidates": 3, "max_native_solves": 3, "wall_seconds": 2400,
                   "ram_bytes": 1024**3, "disk_bytes": 4 * 1024**3, "concurrency": 1}, "source_refs": [SOURCE]}
    document = read()
    wait(service, call(service, "project.save", {"expected_revision": document["revision_id"]}, context, mutation=True))
    return {"kind": kind, "context": context, "path": path, "document": document, "specification": spec,
            "parameter_id": axis, "target_id": target_id, "manufacturing": None, "measurement": None,
            "sma_model": None, "installed_environment_em": None, "measurement_reference_plane": None}
