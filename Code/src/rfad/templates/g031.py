"""! @brief 확인한 PCA20006 원문 일부와 치수 유도 근거를 버전 고정 카드로 제공한다."""

import math

from rfad.application.canonical import canonical_bytes
from rfad.domain.units import Quantity, QuantityError


IDENTITY = "literature.g031_pca20006_arc"
VERSION = "0.1"
SCHEMA = "rfad.template-card/0.2"
GENERATOR = "rfad.literature-geometry/0.1"
SOURCE_ID = "NORDIC_PCA20006_CAD"
ARCHIVE_PATH = ("00_REF/PCB RF ANT/01_RF_Antenna_Vendor_Guides_CAD/Reference_CAD/"
                "NORDIC_PCA20006_CAD__nRF51822_Bluetooth_Smart_Beacon_Kit_PCA20006_PCB400059_hardware_files.zip")
PREFIX = ("nRF51822 Bluetooth Smart Beacon Kit - Hardware files 1_0_0/"
          "PCA20006-nRF51822 Beacon Reference Board 1_0_0/")
FIELDS = (
    ("offset_x", "배치 이동 X", "length", "mm"), ("offset_y", "배치 이동 Y", "length", "mm"),
    ("center_x", "원문 원호 중심 X", "length", "mm"), ("center_y", "원문 원호 중심 Y", "length", "mm"),
    ("radius", "중심선 반지름", "length", "mm"), ("start_angle", "시작각", "angle", "deg"),
    ("sweep_angle", "CCW 전개각", "angle", "deg"), ("width", "원호 선폭", "length", "mm"),
    ("feed_start_x", "stub 시작 X", "length", "mm"), ("feed_start_y", "stub 시작 Y", "length", "mm"),
    ("feed_end_x", "stub 끝 X", "length", "mm"), ("feed_end_y", "stub 끝 Y", "length", "mm"),
    ("feed_width", "stub 선폭", "length", "mm"),
)


def evidence() -> dict:
    """! @brief 중첩 ZIP과 필요한 member 해시, 좌표 원문 및 생략 항목을 보존한다."""
    return {
        "geometry_id": "G031", "hardware_revision": "1.0.0", "pcb": "400059",
        "archive_path": ARCHIVE_PATH,
        "archive_sha256": "de2dbf4b9c8c660efe9c92d716ec161728dde018a801b5ccb1bfdd0d88a55a8a",
        "inner_member": "nRF51822 Bluetooth Smart Beacon Kit - Hardware files 1_0_0.zip",
        "inner_sha256": "de83d749b10f9f77fc493df293c544782d3ad4624bdfe98fac328da6fdf889db",
        "coordinate_format": "FSLAX24Y24; MOIN; G75", "coordinate_step_mm": 0.00254,
        "members": [
            {"role": "top_copper", "path": PREFIX + "Production files/GERBER/400059.GTL",
             "sha256": "1225766196a9608ba1d97deaa6b9dbde399878344e190951474a2e41ce01d292",
             "spans": [{"start": 1, "lines": ["%FSLAX24Y24*%", "%MOIN*%", "G70*", "G01*", "G75*"]},
                       {"start": 8, "lines": ["%ADD10C,0.0500*%"]},
                       {"start": 705, "lines": ["D10*", "X-1042Y3436D02*", "G03*", "X-2774Y-2279I1042J-3436D01*",
                                                "G01*", "X-1274Y-2306D02*", "X-1174Y-2206D01*",
                                                "X-2744Y-2300D02*", "X-1990D01*"]}], "pdf_pages": []},
            {"role": "outline_reference", "path": PREFIX + "Production files/GERBER/400059.GM1",
             "sha256": "ef4045a313aed01197fa205b1a100f91263c42b18d34b065b519155fddfa468b",
             "spans": [{"start": 129, "lines": ["X995Y3809D02*", "G03*", "X-2280Y-3210I-995J-3809D01*"]},
                       {"start": 141, "lines": ["X6120D02*", "Y1340D01*", "X3700D02*", "X6120D01*",
                                                "X3699Y-1350D02*", "X6120D01*"]}], "pdf_pages": []},
            {"role": "schematic_layout", "path": PREFIX + "Schematic_Layout pdf files/PCA20006_Schematic_And_PCB.pdf",
             "sha256": "e328c2c6d9192b326db2289ae6d473780f08fd696e7eb268521bcfa1ab2fb8c9",
             "spans": [], "pdf_pages": [1, 2, 3]},
        ],
        "scope": "partial_arc_and_stub", "whole_board_reproduced": False,
        "derivation": "시작점-중심 반지름, atan2 시작각과 끝점 방향의 CCW sweep; stub의 modal Y 유지",
        "endpoint_radius_difference_mm": abs(math.hypot(-2774, -2279) - math.hypot(-1042, 3436)) * 0.00254,
        "omitted": ["탭/커넥터를 포함한 전체 보드 외곽", "전체 구리/접지/net/비아/패드 및 전층 keepout",
                    "L1/C4/BAL-NRF02D3 정합 회로와 부품 실장", "배터리/외함/급전 기준면/측정 환경"],
        "unknown": ["보드 등급/Dk/Df/두께와 동박/마스크 적층", "실제 제작/납품 물성과 측정 조건"],
        "source_reported": ["회로도 p.1: L1=2.2 nH series, C4=1.2 pF shunt; 이 개정 전용이며 생성하지 않음",
                            "PDF p.2/3의 top/bottom 그림과 원호/stub 방향을 대조; RF 성능 검증 없음"],
    }


def reference_inputs() -> dict:
    """! @brief 원문 정수 좌표와 D10에서 유도한 치수만 source_default로 만든다."""
    step = 0.00254
    start = math.atan2(3436, -1042)
    sweep = (math.atan2(-2279, -2774) - start) % math.tau
    values = {"center_x": 0.0, "center_y": 0.0, "radius": math.hypot(-1042, 3436) * step,
              "start_angle": math.degrees(start), "sweep_angle": math.degrees(sweep), "width": 0.0500 * 25.4,
              "feed_start_x": -2744 * step, "feed_start_y": -2300 * step,
              "feed_end_x": -1990 * step, "feed_end_y": -2300 * step, "feed_width": 0.0500 * 25.4}
    result = {}
    for key, value in values.items():
        unit = "deg" if key in ("start_angle", "sweep_angle") else "mm"
        locator = "GTL:8,705-708,712-713"
        refs = [SOURCE_ID + "/1.0.0/" + locator]
        display = repr(value) if key in ("radius", "start_angle", "sweep_angle") else format(value, ".12g")
        result[key] = {"display_value": display,
                       "quantity": Quantity.from_value(value, unit, status="source_default", source_refs=refs).to_dict()}
    return result


def card() -> dict:
    """! @brief 전체 안테나 재현이나 초기 RF 합성으로 승격하지 않는 문헌 카드를 만든다."""
    return {
        "schema": SCHEMA, "template_id": IDENTITY, "version": VERSION,
        "name": "G031 / PCA20006 원호와 stub (부분 기하)", "family": "FAM-01",
        "description": "PCB400059 rev 1.0.0의 원호/stub 치수입니다. 기존 보드 위에 배치하며 전체 보드 재현은 아닙니다.",
        "generator_version": GENERATOR, "mode": "explicit_geometry", "board_kinds": ["rectangle", "circle"],
        "input_fields": [{"key": key, "label": label, "dimension": dimension, "display_unit": unit, "required": True}
                         for key, label, dimension, unit in FIELDS],
        "reference_inputs": reference_inputs(), "evidence": evidence(),
        "support": {"geometry_generator": True, "seed_synthesizer": False, "simulated": False,
                    "converged": False, "measured": False, "manufacturing_verified": False},
        "source": {"source_id": SOURCE_ID, "kind": "cad_reference",
                   "references": ["PCA20006 / PCB400059 rev 1.0.0 / G031",
                                  "https://devzone.nordicsemi.com/f/nordic-q-a/47638/altium-reference-design-for-nrf51822-beacon-kit/188689",
                                  "GTL D10: lines 8,705-708,712-713; GM1:129-158; embedded PDF:p.1-3"],
                   "scope": "원문 치수의 원호/stub 부분 기하; 원문 성능이나 전체 PCB 재현 주장이 아님"},
        "assumptions": ["사용자가 기존 보드/도체층과 배치 이동 X/Y를 지정; 보드/적층은 생성하거나 변경하지 않음",
                        "Gerber에는 net 이름이 없어 원호/stub용 새 편집 net만 생성; 원본 전체 netlist 복원 아님",
                        "시작 반지름 사용. 원문 끝점 반지름과 약 0.001041 mm 차이를 유지하고 양자화 오차를 명시",
                        "stub은 원호 끝과 폭으로 겹치며 중심선 끝점을 일치시키지 않음"],
        "limitations": ["부분 기하 생성 / 초기 추정 미수행 / 해석 미수행 / 수렴 미확립 / 실측 미검증",
                        "약 19.999016 mm body reference는 탭/커넥터를 포함한 전체 외곽이 아님",
                        "인접 구리의 반지름으로 전역 접지/최소 간격을 추정하지 않음",
                        "포트, 정합 회로, 물성, 제작/측정 조건을 자동 입력하지 않음"],
    }


def validate_snapshot(value: dict) -> None:
    """! @brief 외부 원문이나 현재 카드 조회 없이 고정 버전의 원문/치수 대응을 검사한다."""
    from rfad.domain.design import _fail, _fields

    if canonical_bytes(value["evidence"]) != canonical_bytes(evidence()):
        _fail("E_HASH", "G031 원문 사본과 치수 유도 근거가 고정 버전과 다릅니다.", "template_origin.card.evidence")
    expected = reference_inputs()
    _fields(value["reference_inputs"], set(expected), "template_origin.card.reference_inputs")
    for key, reference in value["reference_inputs"].items():
        _fields(reference, {"display_value", "quantity"}, "template_origin.card.reference_inputs." + key)
        original = expected[key]["quantity"]
        if canonical_bytes(reference["quantity"]) != canonical_bytes(original):
            _fail("E_HASH", "G031 원문 Quantity가 고정 버전과 다릅니다.", "template_origin.card.reference_inputs." + key)
        text = reference["display_value"]
        if type(text) is not str or not 0 < len(text) <= 128:
            _fail("E_SCHEMA", "원문 표시 값은 제한된 숫자 문자열이어야 합니다.", "template_origin.card.reference_inputs." + key)
        try:
            displayed = Quantity.from_value(float(text), original["display_unit"]).value_si
        except (ValueError, OverflowError, QuantityError):
            _fail("E_UNIT", "원문 표시 값의 숫자가 올바르지 않습니다.", "template_origin.card.reference_inputs." + key)
        if not math.isclose(displayed, original["value_si"], rel_tol=1e-14, abs_tol=1e-18):
            _fail("E_HASH", "원문 표시 값과 Quantity가 다릅니다.", "template_origin.card.reference_inputs." + key)
    if value["source"]["source_id"] != SOURCE_ID or value["source"]["kind"] != "cad_reference":
        _fail("E_SCHEMA", "G031 원문 출처 식별이 다릅니다.", "template_origin.card.source")
