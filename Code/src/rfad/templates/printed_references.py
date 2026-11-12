"""! @brief nWP008 모노폴과 AN1088 IFA의 원문 치수 및 제한된 초기식 계약을 제공한다."""

from rfad.application.canonical import canonical_bytes
from rfad.domain.design import _fail
from rfad.domain.units import Quantity


SCHEMA = "rfad.template-card/0.3"
GENERATOR = "rfad.printed-reference/0.1"
MONOPOLE = "literature.g001_nwp008_monopole"
IFA_62MIL = "literature.g008_an1088_ifa_62mil"
IFA_08MM = "literature.g009_an1088_ifa_08mm"
IDENTITIES = (MONOPOLE, IFA_62MIL, IFA_08MM)
SOURCE_ROOT = "00_REF/PCB RF ANT/01_RF_Antenna_Vendor_Guides_CAD/Printed_antenna_geometry/"
_POSITION = (("offset_x", "배치 기준 X", "length", "mm"), ("offset_y", "배치 기준 Y", "length", "mm"))
_MONOPOLE_FIELDS = _POSITION + (("length", "도체 전체 길이", "length", "mm"), ("width", "선폭", "length", "mm"))
_IFA_FIELDS = _POSITION + tuple((key, label, "length", "mm") for key, label in (
    ("arm_length", "수평 가지 전체 길이"), ("arm_width", "수평 가지 폭"), ("short_width", "단락 가지 폭"),
    ("feed_width", "급전 가지 폭"), ("inner_gap", "단락-급전 내부 간격"), ("arm_clearance", "수평 가지 아래-접지 경계 거리")))


def definitions(identity):
    """! @brief 그림의 사각 도체와 배치 입력을 혼합하지 않고 고정 역할을 반환한다."""
    return _MONOPOLE_FIELDS if identity == MONOPOLE else _IFA_FIELDS


def seed_recipes():
    """! @brief 임의 경험 배율 없이 이상적 기준과 원문 2.45 GHz 조건만 제공한다."""
    return [
        {"id": "ideal_quarter_wave", "label": "이상적 자유공간 1/4 파장 기준", "equation": "EQ-003/EQ-004",
         "formula": "L=c0/(4*f)", "frequency_scope": "f > 0; 이상적 모델의 산술 범위이며 PCB RF 지원 대역이 아님",
         "conditions": ["자유공간의 이상적 얇은 모노폴과 이상적 접지를 가정", "유한 PCB/유전체/급전/외함 효과를 계산하지 않음"],
         "kappa": 1.0, "extension": 0.0},
        *[{"id": identity, "label": label, "equation": "EQ-004/NORDIC_NWP008/section-3",
           "formula": "L=0.75*c0/(4*f)*(1+extension)", "frequency_scope": "f = 2.45 GHz에만 원문 보정 허용",
           "conditions": ["원문: 1.6 mm FR4, 전형 epsilon_r=4.4, 폭 1.5 mm", condition,
                          "현재 PCB/실제 물성과 접지 조건은 이 가정으로 확인된 것이 아님; 조립 상태에서 재튜닝 필요"],
           "kappa": 0.75, "extension": extension}
          for identity, label, extension, condition in (
              ("nwp008_base", "nWP008 2.45 GHz 이론 시작 길이", 0.0, "충분한 접지와 FR4에 균일하게 둘러싸인 trace 가정"),
              ("nwp008_trim20", "nWP008 충분한 접지 / 조정 여유 20%", 0.2, "이상적 크기에 가까운 접지와 균일 FR4; prototype 절단 조정용"),
              ("nwp008_trim30", "nWP008 작은 접지 / 가장자리 / 조정 여유 30%", 0.3, "작은 접지 또는 PCB 가장자리 trace; prototype 절단 조정용"))],
    ]


def reference_inputs(identity):
    """! @brief inch 관측은 정확한 25.4 배율로 변환하며 물성은 생성 입력으로 채우지 않는다."""
    if identity == MONOPOLE:
        values = {"length": 23.0, "width": 1.5}
        source = "NORDIC_NWP008/p.1/section-3"
    else:
        inch = {"arm_length": 0.782 if identity == IFA_62MIL else 0.860, "arm_width": 0.039,
                "short_width": 0.040, "feed_width": 0.040, "inner_gap": 0.109 if identity == IFA_62MIL else 0.115,
                "arm_clearance": 0.327 if identity == IFA_62MIL else 0.311}
        values = {key: value * 25.4 for key, value in inch.items()}
        source = "SILABS_AN1088/rev0.1/p.3/Figure-2.1/" + ("62mil" if identity == IFA_62MIL else "0.8mm")
    return {key: {"display_value": format(value, ".12g"),
                  "quantity": Quantity.from_value(value, "mm", status="estimated" if identity == MONOPOLE and key == "length" else "source_default",
                                                  source_refs=[source]).to_dict()} for key, value in values.items()}


def evidence(identity):
    """! @brief source에서 관측한 조건, 미정과 그림의 불일치를 각각 보존한다."""
    mono = identity == MONOPOLE
    return {
        "geometry_id": "G001" if mono else ("G008" if identity == IFA_62MIL else "G009"),
        "path": SOURCE_ROOT + ("NORDIC_NWP008__nWP008_4_printed_monopole_antenna_for_2.45_GHz.pdf" if mono else
                               "SILABS_AN1088__AN1088_Designing_with_an_Inverted-F_2.4_GHz_PCB_Antenna.pdf"),
        "sha256": "3d096d85e2a57ce999a8f6c489f6b156b66cc03d5f25512ebb59b3465da7ccb5" if mono else
                  "22ee4e51d53b1c73e1a4e58b4b4d5c23bd5a9c81e2e517faf546d8815a24b536",
        "pdf_pages": [1, 2, 3] if mono else [3, 4, 5],
        "locator": "January 2005 / sections 2-4 and Figure 1" if mono else "Rev.0.1 / Figure 2.1,2.2 / section 3.1",
        "scope": "source_initial_monopole_trace" if mono else "three_rectangular_ifa_arms_above_ground_boundary",
        "whole_board_reproduced": False,
        "omitted": ["원본 전체 보드/접지/적층과 도체 아래 전층 keepout", "급전 전송선/정합 회로/포트/실장/외함"] +
                   ([] if mono else ["접지 경계 아래의 단락 패드/비아 및 급전 taper와 microstrip"]),
        "unknown": ["실제 납품 Dk/Df/동박/마스크와 제작/측정 조건", "선택 보드의 실제 접지와 주변 환경에 대한 RF 적합성"],
        "source_reported": (["23 mm는 1.6 mm FR4/전형 Dk 4.4/폭 1.5 mm/2.45 GHz의 반올림한 초기 추정",
                             "0.75*lambda0와 20%/30% prototype 조정 여유는 조건별 관측; production 길이가 아님",
                             "도체 아래 모든 층에 접지 금지; 최종 외함/인체 조건에서 잘라 조정하고 VNA로 확인"] if mono else
                            ["1 inch 폭 보드에 최적화; 접지 크기가 달라지면 정합 재조정 필요",
                             "단락 가지의 실제 접지 연결과 비아, 도체 아래 접지 제외, soldermask 필요",
                             "원문은 4층 적층을 제시하며 범용 FR4 Dk/Df를 제시하지 않음"]),
        "source_conflicts": ([] if identity != IFA_08MM else
                             ["Figure 2.2(b)는 0.8 mm와 0.034 inch(0.8636 mm)를 함께 표기; 실제 두께를 임의 선택/평균하지 않음"]),
    }


def card(identity):
    """! @brief source estimate와 원문 치수 카드의 지원 상태를 RF 실측과 분리한다."""
    mono = identity == MONOPOLE
    return {
        "schema": SCHEMA, "template_id": identity, "version": "0.1",
        "name": "G001 / nWP008 모노폴 초기 형상" if mono else
                ("G008 / AN1088 IFA 62 mil (부분 기하)" if identity == IFA_62MIL else "G009 / AN1088 IFA 0.8 mm (부분 기하)"),
        "description": "기존 보드에 원문 기준의 도체만 생성합니다. 적층/접지/급전과 실제 RF 성능은 별도 검토합니다.",
        "family": "FAM-01" if mono else "FAM-02", "generator_version": GENERATOR, "mode": "explicit_geometry",
        "modes": ["explicit_geometry", "initial_estimate"] if mono else ["explicit_geometry"],
        "seed_recipes": seed_recipes() if mono else [], "board_kinds": ["rectangle", "circle"],
        "input_fields": [{"key": key, "label": label, "dimension": dimension, "display_unit": unit, "required": True}
                         for key, label, dimension, unit in definitions(identity)],
        "reference_inputs": reference_inputs(identity), "evidence": evidence(identity),
        "support": {"geometry_generator": True, "seed_synthesizer": mono, "simulated": False,
                    "converged": False, "measured": False, "manufacturing_verified": False},
        "source": {"source_id": "NORDIC_NWP008" if mono else "SILABS_AN1088", "kind": "document_reference",
                   "references": (["nWP008 January 2005 / p.1-3 / G001", "https://nrfconnectdocs.nordicsemi.com/pdf/nwp_008/nwp_008.pdf"] if mono else
                                  ["AN1088 Rev.0.1 / p.3-5 / " + ("G008" if identity == IFA_62MIL else "G009"),
                                   "https://www.silabs.com/documents/public/application-notes/an1088-designing-with-pcb-antenna.pdf"]),
                   "scope": "원문 일부의 초기 형상/치수 근거; 원본 전체와 RF 성능의 재현 주장이 아님"},
        "assumptions": ["배치 X/Y는 사용자가 명시; 기존 보드/물성/포트는 변경하지 않음",
                        "새 편집 net은 생성한 도체의 묶음이며 원문 전체 netlist 복원이 아님",
                        "모노폴의 배치 기준은 아래 단면 중심, IFA는 단락 왼쪽/원문 접지 경계의 교점"],
        "limitations": ["부분 기하/초기 추정과 해석/수렴/실측/제조 검증을 구분", "원문 조건을 현재 기판의 납품 물성으로 적용하지 않음",
                        "새 포트/접지/비아를 임의 생성하지 않으며 기존 직접 편집으로 이어감"],
    }


def validate_snapshot(value):
    """! @brief 현재 카드 조회나 PDF 없이 고정 버전 source와 치수/초기식 사본을 검사한다."""
    identity = value["template_id"]
    expected = card(identity)
    for key in ("evidence", "reference_inputs", "modes", "seed_recipes", "source"):
        if canonical_bytes(value[key]) != canonical_bytes(expected[key]):
            _fail("E_HASH", "문헌 카드의 고정 원문/치수/초기식 사본이 다릅니다.", "template_origin.card." + key)
