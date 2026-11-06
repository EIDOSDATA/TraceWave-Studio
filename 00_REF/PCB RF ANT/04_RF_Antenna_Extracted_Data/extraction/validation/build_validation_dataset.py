#!/usr/bin/env python3
"""Rebuild source-grounded applicability, validation and equation extracts.

This is a data builder, not an antenna solver. No network, no catalog mutations.
PDF page numbers below are physical PDF pages, counted from 1.
"""
from pathlib import Path
import csv
import hashlib
import json
import math

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA = "rf-antenna-extraction/1.0"


def src(sid, pages=None, section="", equation=None):
    return {"source_id": sid, "locator_kind": "pdf" if pages else "html_section",
            "physical_pdf_pages": pages, "section": section,
            "equation_or_table": equation}


def threshold(metric, operator, value, unit, scope, role="source_recommendation"):
    return dict(metric=metric, operator=operator, value=value, unit=unit,
                scope=scope, role=role, automatically_enabled=False)


C, V, M = [], [], []


def cond(name, families, statement, inputs, sources, action, limits="", numeric=None,
         evidence="source_prescribed_condition"):
    C.append(dict(condition_id=f"COND-{len(C)+1:03d}", name=name,
        antenna_families=families, statement_ko=statement, required_inputs=inputs,
        sources=sources, evidence_class=evidence, program_action_ko=action,
        limitations_ko=limits, numeric_constraints=numeric or [],
        universal_acceptance_threshold=None))


def method(name, families, inputs, procedure, outputs, sources, acceptance,
           limits="", numeric=None, evidence="source_described_method"):
    V.append(dict(method_id=f"VAL-{len(V)+1:03d}", name=name,
        antenna_families=families, required_inputs=inputs,
        procedure_ko=procedure, output_fields=outputs, sources=sources,
        evidence_class=evidence, acceptance_basis_ko=acceptance,
        source_scoped_targets=numeric or [], default_pass_fail_threshold=None,
        limitations_ko=limits))


def variable(symbol, unit, meaning):
    return dict(symbol=symbol, unit=unit, meaning_ko=meaning)


def model(name, expression, variables, sources, applicable, excluded,
          origin="source_formula", status="extracted_not_solver_validated", notes="", domain=None):
    M.append(dict(model_id=f"MODEL-{len(M)+1:03d}", name=name,
        expression=expression, variables=variables, sources=sources,
        origin=origin, applicability_ko=applicable, exclusions_ko=excluded,
        validity_domain=domain or [], implementation_status=status,
        notes_ko=notes, source_numeric_example=None))


cond("Quarter-wave monopole includes its ground", ["printed_monopole", "open_arc_monopole"],
    "단일 급전 1/4파장 모노폴의 접지판은 방사 구조의 일부이며 크기가 이득·공진·입력 임피던스에 영향을 준다.",
    ["ground_outline", "feed_position", "radiator_geometry"],
    [src("NORDIC_NWP008", [1], "2. Basic properties"), src("TI_AN058_SWRA161", [5], "3.2 Monopole antennas")],
    "안테나 도체만 따로 계산하지 않고 실제 접지 형상과 급전을 모델에 포함한다.",
    "원호의 반지름 또는 PCB 지름 하나로 공진 주파수를 확정할 수 없다.")
cond("Nordic printed-monopole reference scope", ["printed_monopole"],
    "nWP008의 0.75λ0·23 mm 추정은 특정 2.45 GHz FR4 예시의 출발값이다.",
    ["frequency_hz", "substrate_thickness_m", "epsilon_r", "trace_width_m", "ground_outline"],
    [src("NORDIC_NWP008", [1, 2], "3. Determining the length")],
    "서로 다른 재질·적층·보드 외곽에는 해당 단축률을 자동 이식하지 않는다.",
    "해당 문서의 기판은 1.6 mm FR4, εr 전형값 4.4, 선폭 1.5 mm이며 접지/FR4 주변 조건을 함께 요구한다.",
    [threshold("frequency_hz", "=", 2.45e9, "Hz", "nWP008 example"),
     threshold("substrate_thickness_m", "=", 1.6e-3, "m", "nWP008 example")],
    "source_described_applicability")
cond("Monopole keepout across PCB layers", ["printed_monopole", "open_arc_monopole"],
    "nWP008의 모노폴 아래 PCB층에는 접지판을 두지 않고 주변 배선·부품도 비운다.",
    ["copper_by_layer", "component_envelopes", "radiator_keepout"],
    [src("NORDIC_NWP008", [2], "4. Combining the printed quarterwave monopole")],
    "해당 모노폴 템플릿의 전체 층 keepout 위반을 검사한다.",
    "접지면이 필요한 패치·마이크로스트립 급전부·슬롯에 이 규칙을 일괄 적용하지 않는다.")
cond("Nordic bent-monopole tip clearance", ["bent_printed_monopole", "open_arc_monopole"],
    "nWP008의 굽힌 모노폴 예시는 개방단과 접지 사이 거리 d를 크게 유지할 것을 권한다.",
    ["open_tip_to_ground_clearance_m", "frequency_hz"],
    [src("NORDIC_NWP008", [2, 3], "4; Figure 1b")],
    "참조 형상에서만 권장 d를 표시하고, 다른 지름·주파수는 EM 검증 대상으로 보낸다.",
    "10 mm는 문서의 2.45 GHz 배치 권장값이며 모든 원형 PCB의 고정 keepout 값이 아니다.",
    [threshold("open_tip_to_ground_clearance_m", ">=", .010, "m", "nWP008 Figure 1b at 2.45 GHz, preferably")])
cond("Prototype trim allowance is contextual", ["printed_monopole"],
    "nWP008은 절단 튜닝을 위해 이론 추정보다 긴 시제품을 만들고 최적 길이를 양산판에 반영한다.",
    ["initial_trace_length_m", "ground_extent", "board_edge_proximity"],
    [src("NORDIC_NWP008", [2, 3], "3; Figure 1 tuning")],
    "20%·30%는 해당 예시의 시제품 여유 프리셋으로 저장하고 최종 길이로 취급하지 않는다.",
    "주변 FR4·접지 조건에 따라 20% 또는 30%를 제안한 문서이며 임의 재질용 일반식이 아니다.",
    [threshold("prototype_length_multiplier", "=", 1.2, "1", "near-ideal ground and uniform FR4 surroundings"),
     threshold("prototype_length_multiplier", "=", 1.3, "1", "small ground and/or board-edge routing")])
cond("Tune in the final use environment", ["all_radiating_antennas"],
    "케이스, 인체 접촉, 금속 근접, 접지판 변경은 안테나 성능을 바꾸므로 최종 사용 환경에서 튜닝한다.",
    ["enclosure_model", "metal_objects", "body_use_state", "ground_outline"],
    [src("NORDIC_NWP008", [3], "Tuning"), src("NORDIC_NWP017", [4], "2. Why tune the antenna?"),
     src("TI_AN058_SWRA161", [23], "6.2.5 Antenna Matching")],
    "배터리·차폐·하우징 등 실제 금속/유전체 물체를 사용자 환경 모델과 시험 상태에 기록한다.",
    "배터리의 구체적인 간격 기준은 이 추출에서 확보되지 않았으므로 null이다.")
cond("IFA shorting and feed topology", ["IFA"],
    "AN1088의 IFA는 급전 arm과 접지로 단락되는 arm을 별도로 갖고 방사부 아래를 비운다.",
    ["feed_net", "shorting_net", "ground_vias", "feed_impedance_ohm", "radiator_keepout"],
    [src("SILABS_AN1088", [3], "2.1 Key Features")],
    "IFA 템플릿은 접지 단락 연결과 급전을 그래프/DRC로 검사한다.",
    "급전 선폭은 적층별로 계산한다. 문서의 14 mil을 보편 선폭으로 사용하지 않는다.",
    [threshold("feed_impedance_ohm", "=", 50, "ohm", "AN1088 reference IFA")])
cond("IFA mask and thickness belong to the design", ["IFA"],
    "AN1088에는 62 mil 및 0.8 mm 두 두께용 레이아웃이 있으며 솔더마스크 덮임을 설계 조건에 포함한다.",
    ["stackup", "soldermask_thickness_m", "soldermask_epsilon_r"],
    [src("SILABS_AN1088", [3], "2.1 Key Features")],
    "참조 템플릿 선택 시 두께와 마스크 상태를 메타데이터로 고정한다.",
    "이 문서 페이지에는 마스크 εr·두께의 수치가 없으므로 추정값으로 채우지 않는다.")
cond("IFA ground resizing requires reassessment", ["IFA"],
    "AN1088 IFA는 폭 1 inch PCB에서 최적화되었고 접지 가장자리 전류 때문에 보드 크기 변경 시 매칭이 달라진다.",
    ["board_outline", "ground_outline", "template_reference_board"],
    [src("SILABS_AN1088", [5], "3.1 Antenna Placement")],
    "보드 지름/외곽 변경을 검증 상태를 무효화하는 변경으로 기록한다.",
    "1 inch 폭은 참조판 조건이며 최소 원형 PCB 지름 규칙이 아니다.")
cond("Reserve antenna matching footprints", ["IFA", "printed_monopole", "chip_antenna"],
    "실제 커스텀 PCB의 임피던스를 예측하기 어려우므로 급전 근처에 3소자 π 매칭 footprint를 확보한다.",
    ["matching_footprints", "measured_feed_impedance", "component_models"],
    [src("SILABS_AN1088", [6], "3.2 Tuning"), src("SILABS_AN1275", [38], "7.4 Antenna Matching Networks")],
    "구조 튜닝과 외부 매칭값을 독립 변수로 저장한다.",
    "참조판 인덕터 수치를 다른 구현에 그대로 복사하지 않는다. 매칭 개선이 방사 손실을 회복시킨다는 보장은 없다.")
cond("Chip-side matching differs from antenna tuning", ["nRF24xx_radio_frontend"],
    "nRF24xx RF 매칭망은 차동 변환·고조파 억제·LO 누설·DC 경로를 함께 처리한다.",
    ["radio_model", "vendor_rf_layout", "package_models", "tx_power", "harmonics", "rx_lo_leakage"],
    [src("NORDIC_NWP013", [2], "Matching network; 3. Tuning")],
    "칩측 RF 매칭/발룬과 안테나측 임피던스 매칭을 별도 회로 블록으로 관리한다.",
    "nRF24xx 문서의 회로/부품값을 nRF51/nRF54 또는 다른 SoC의 검증된 값으로 간주하지 않는다.")
cond("Matching is complex and frequency dependent", ["all_port_based_antennas"],
    "최대 전력 전달을 위한 켤레 정합은 복소 임피던스와 주파수에 의존한다.",
    ["source_impedance_vs_frequency", "load_impedance_vs_frequency", "matching_band"],
    [src("SILABS_AN1275", [6], "2.3 Impedance Matching")],
    "단일 중심 주파수 정합과 전 대역 성능을 구분하여 계산한다.",
    "안테나가 공진한다고 해서 임의 목표 임피던스로 정합되는 것은 아니다.")
cond("L-network topology and Q limitations", ["lumped_matching_network"],
    "L 매칭망은 부하의 Smith chart 위치에 따라 가능한 토폴로지가 다르고 종단 저항비가 Q를 제한한다.",
    ["source_impedance", "load_impedance", "topology", "required_bandwidth_hz"],
    [src("SILABS_AN1275", [14, 15], "4. Two-Element Matching Network Architecture")],
    "불가능한 L 토폴로지를 거르고 기생 리액턴스 흡수/상쇄 여부를 기록한다.",
    "집중소자 이상회로 출발값이다. 부품 손실·공차·자기공진 주파수는 실제 부품 모델로 검증한다.")
cond("AoA needs phase-pattern and coupling data", ["BLE_AoA_array"],
    "AN1195 참조 배열은 접지 경유 결합이 위상 오차를 만들 수 있어 각 소자의 위상·크기 패턴과 편파를 고려한다.",
    ["embedded_element_patterns", "port_phase_reference", "polarization_basis", "array_coordinates"],
    [src("SILABS_AN1195", [7, 16], "5.2; 5.3; phase-pattern discussion")],
    "배열 모델에 소자별 복소 방사패턴과 manifold compensation 자료를 연결한다.",
    "이 문서의 특정 배열 설계 선택을 모든 모노폴 배열의 원리적 불가능으로 일반화하지 않는다.")
cond("AoA mounting materials influence phase", ["BLE_AoA_array"],
    "AN1195는 후면 금속·콘크리트 및 전면/측면 플라스틱의 영향에 대해 S11뿐 아니라 위상을 검토한다.",
    ["back_material", "front_material", "side_material", "mounting_gaps_m"],
    [src("SILABS_AN1195", [18], "5.7 Effect of Back Metal, Back Concrete and Plastic Case")],
    "장착 간격을 위상 패턴 재검증 변수로 포함한다.",
    "참조 배열의 개별 최소 간격 값은 해당 구조가 동일할 때만 사용한다.")
cond("DW1000 channel set determines antenna bandwidth", ["UWB_DW1000"],
    "DW1000용 안테나는 사용하는 채널 집합에 따라 full-band 또는 channelised 대역을 선택하고 펄스 왜곡을 평가한다.",
    ["radio_channels", "occupied_spectra", "pulse_shape", "orientation_set"],
    [src("QORVO_APH007", [3, 4], "3. DW1000 Operational Channels; 4.4 Absolute Bandwidth")],
    "UWB라는 이름만으로 모든 주파수 범위를 강제하지 않고 실제 채널 합집합을 검증 대역으로 만든다.",
    "DW1000 채널표를 다른 UWB 칩의 채널표로 간주하지 않는다.")
cond("DW1000 suggested RF targets are a profile", ["UWB_DW1000"],
    "APH007의 return loss와 방사 효율 수치는 DW1000 안테나 설계/구매의 출발 권장치다.",
    ["selected_radio_profile", "return_loss_vs_frequency", "radiation_efficiency_vs_frequency"],
    [src("QORVO_APH007", [4], "4.2 Return Loss; 4.3 Antenna Efficiency")],
    "사용자가 DW1000 프로필을 선택한 경우에만 권장치를 제시한다.",
    "수치를 BLE/LoRa/NFC/RFID의 전역 합격 기준으로 활성화하지 않는다.",
    [threshold("return_loss_db", ">=", 10, "dB", "DW1000 band-of-operation target"),
     threshold("radiation_efficiency", ">=", .60, "1", "DW1000 acceptable starting recommendation"),
     threshold("radiation_efficiency", "aim", .90, "1", "DW1000 aspirational aim")])
cond("DW1000 orientation and fidelity targets", ["UWB_DW1000"],
    "APH007은 DW1000용 fidelity factor 및 사용 방향 범위 내 안테나 group delay 변화를 권고한다.",
    ["fidelity_definition", "test_pulse", "useful_orientation_range", "group_delay_measurement_definition"],
    [src("QORVO_APH007", [5], "4.6 Fidelity Factor; 4.8 Group Delay versus antenna orientation")],
    "fidelity 계산 정의와 방향 범위를 수치 옆에 저장한다.",
    "100 ps는 방향에 따른 변화 권고이며 임의 주파수 ripple 규칙으로 바꾸지 않는다. APH007 자체는 fidelity 적분식을 제공하지 않는다.",
    [threshold("fidelity_factor", ">=", .99, "1", "APH007 DW1000 recommendation; definition must be confirmed"),
     threshold("orientation_group_delay_variation_s", "<=", 100e-12, "s", "DW1000 useful orientation range")])
cond("UWB proximity is a system condition", ["UWB_DW1000"],
    "벽·금속·인체·일부 플라스틱 근접은 UWB 성능을 저하시킬 수 있고 고정 anchor/착용 tag는 다른 환경 모델이 필요하다.",
    ["mounting_surface", "body_proximity", "enclosure_model", "anchor_tag_role"],
    [src("QORVO_APH007", [5], "4.7 Proximity Effects")],
    "환경별 방사 패턴·손실·시간 응답을 기록한다.",
    "통합 접지가 벽 뒤 방향으로도 방사하도록 보장하는 것은 아니다.")
cond("DW1000 delay calibration follows actual settings", ["UWB_DW1000"],
    "안테나 delay 교정은 최종 제품에서 쓰는 PRF·채널·power-up mode 조합에서 수행한다.",
    ["prf", "channel", "power_up_mode", "hardware_revision", "calibration_temperature_c"],
    [src("QORVO_APS014", [5, 6], "2. Antenna Delay Calibration; 2.1.3 Temperature Variation")],
    "교정값을 설정과 온도에 종속된 레코드로 저장한다.",
    "한 보드/채널에서 얻은 값이 다른 하드웨어 또는 설정에서 유효하다고 표시하지 않는다.")
cond("DW1000 ranging modes require different delays", ["UWB_DW1000"],
    "TWR은 TX+RX 합산 delay, 유선 동기 TDoA는 RX delay, 무선 동기 TDoA는 TX와 RX delay 정보를 요구한다.",
    ["ranging_mode", "synchronization_mode", "tx_delay_s", "rx_delay_s"],
    [src("QORVO_APS014", [5], "2.1.1; Table 1")],
    "시스템 방식에 맞지 않는 단일 delay 필드를 검출한다.",
    "보정할 필요 여부는 제품 정확도 요구사항과 실제 부품 편차로 결정한다.")
cond("PN5190 coil is a loaded transfer channel", ["NFC_PN5190_reader_coil"],
    "최종 Q는 reader coil만의 값이 아니라 PICC/전화기·환경을 포함한 전달 채널과 파형 요구의 영향을 받는다.",
    ["coil_model", "picc_or_phone_set", "data_rate", "loaded_waveforms", "environment_model"],
    [src("NXP_AN12549", [15], "3.1.2 Q factor")],
    "Q 초기값과 최종 pulse-shape 검증 결과를 분리한다.",
    "문서의 Q=22는 정보가 없을 때 PN5190 튜닝의 출발값이며 모든 NFC 코일의 합격점이 아니다.",
    [threshold("initial_loaded_Q", "=", 22, "1", "PN5190 no-other-input starting value", "source_starting_value")])
cond("NFC coil measurements complement synthesis", ["NFC_PN5190_reader_coil"],
    "AN12549는 합성값만 사용하지 말고 13.56 MHz에서 코일 임피던스를 측정하여 L·R 값을 구하도록 한다.",
    ["measured_impedance_ohm", "coil_equivalent_circuit", "measurement_frequency_hz"],
    [src("NXP_AN12549", [38, 40], "4.2 Antenna tuning calculation Excel sheet")],
    "L·R·기생 C 값을 measured/estimated/synthesized로 각각 태깅한다.",
    "단일 주파수 측정에서 L은 비교적 안정적이나 작은 R은 불확도가 크고 Cpa는 직접 측정되지 않는다.",
    [threshold("measurement_frequency_hz", "=", 13.56e6, "Hz", "PN5190 coil characterization")])
cond("NFC coupling can vanish at some positions", ["NFC_reader_coil"],
    "작은 reader와 작은 PICC 조합은 작동 공간의 일부 위치에서 결합이 거의 0이 되어 통신이 불가능할 수 있다.",
    ["reader_coil_geometry", "test_picc_geometry", "operating_volume", "relative_pose"],
    [src("NXP_AN12549", [11], "Antenna size / interoperability simulation discussion")],
    "단일 중앙 위치의 인식 성공 대신 위치·높이·회전별 통신 맵을 저장한다.",
    "이 문서의 해당 시뮬레이션은 이상 환경이며 PICC loading을 생략했다고 명시한다.", evidence="source_described_applicability")
cond("NFC filter components require operating-condition models", ["NFC_PN5190_reader_frontend"],
    "EMC 필터 인덕터 손실·전류·포화는 전력 전달과 파형에 영향을 주므로 NFC 실제 주파수와 전류에서 평가한다.",
    ["inductor_loss_vs_frequency_current", "current_rating", "saturation_model", "temperature"],
    [src("NXP_AN12549", [15], "3.1.4 EMC filter inductor")],
    "부품 카탈로그의 다른 주파수·낮은 신호 수치를 그대로 적용하지 않는다.",
    "PN5190의 기본 L0 제안값을 다른 NFC IC에 일반화하지 않는다.")
cond("UHF RFID targets assembled-chip conjugate impedance", ["UHF_RFID_tag"],
    "수동 UHF 태그는 chip 및 접합 기생 성분을 포함한 복소 임피던스의 켤레로 안테나를 정합한다.",
    ["chip_impedance_vs_frequency_power", "assembly_parasitics", "antenna_impedance"],
    [src("NXP_AN1715", [20], "2.5 Label Antenna Design", "(34), (35)"),
     src("NXP_AN1629", [21], "3.9 Matching", "(18)-(20)")],
    "태그 목적함수를 일률적인 50 ohm S11 대신 chip 전력 전달 계수로 정의한다.",
    "리더의 50 ohm 포트와 수동 태그의 chip 포트는 별개다.")
cond("UHF chip impedance depends on received power", ["UHF_RFID_tag"],
    "UHF tag IC의 임피던스는 입력 전력에 의존하므로 설계에 사용한 동작점이 필요하다.",
    ["chip_input_power_w", "chip_impedance", "chip_activation_threshold_w"],
    [src("PAPER-043", [2], "2. Methods for Conjugate Impedance Matching", "(1), (2)")],
    "칩 임피던스를 주파수와 입력 전력의 데이터로 저장한다.",
    "논문의 일반적 chip reactance 범위를 최신 특정 칩의 데이터로 대체하지 않는다.", evidence="source_described_applicability")
cond("UHF PCB substrate and carrier alter matching", ["UHF_RFID_PCB", "UHF_RFID_label"],
    "유전체의 실수부는 detuning, 손실 성분은 흡수에 영향을 주며 PCB 두께·동박·층·부품 접합을 모델링해야 한다.",
    ["epsilon_complex_vs_frequency", "stackup", "copper_thickness_m", "carrier_material", "chip_package"],
    [src("NXP_AN1715", [24, 25], "4. PCB; 4.1 Parameters")],
    "FR4라는 재질 이름만 입력되는 경우 정확도 확인이 필요한 상태로 표시한다.",
    "문서의 전형 εr=4.4는 모든 FR4의 보증값이 아니다.")
cond("NXP PCB slot clearance is topology specific", ["UHF_RFID_PCB_slot_AN1715"],
    "AN1715의 PCB 슬롯은 유효 동박 폭 및 슬롯 주변 부품/via 여유를 요구한다.",
    ["slot_width_m", "metal_extent_m", "component_via_clearance_m", "substrate"],
    [src("NXP_AN1715", [46], "Steps before designing slot antenna on a PCB")],
    "AN1715 슬롯 템플릿에서만 폭·주변 간격 규칙을 적용한다.",
    "슬롯을 방사 도체가 없는 구역으로 오해하여 접지를 모두 제거하면 토폴로지가 달라진다.",
    [threshold("effective_metal_width_over_slot_width", ">=", 5, "1", "AN1715 slot, 2W metal on each side"),
     threshold("component_via_clearance_m", ">=", .002, "m", "AN1715 slot surrounding region")])
cond("Gain and efficiency definitions retain the reference plane", ["all_radiating_antennas"],
    "입력 매칭에 의한 반사 손실과 수용된 전력의 방사 효율을 구분해야 한다.",
    ["incident_power_w", "accepted_power_w", "radiated_power_w", "reflection_coefficient", "metric_definition"],
    [src("QORVO_APH007", [4], "4.3 Antenna Efficiency"), src("RS_8GE01_ANTENNA_BASICS", [13, 14], "3.4 Gain; 3.5 Practical Gain"),
     src("TI_AN058_SWRA161", [25, 26], "6.3 OTA; equations 8, 9")],
    "radiation_efficiency, mismatch_efficiency, total_efficiency, gain, realized_gain을 별도 필드로 관리한다.",
    "TI 문서의 gain/efficiency 설명은 mismatch를 포함하므로 정의를 보존한 뒤 정규화한다. S11만으로 radiation efficiency를 알 수 없다.",
    evidence="source_definition_normalized")
cond("VNA reference plane is part of the measurement", ["all_port_based_antennas"],
    "교정 기준면은 표준기를 연결한 위치이며 안테나 임피던스는 실제 급전면으로 기준면을 옮겨 해석해야 한다.",
    ["calibration_plane", "antenna_feed_plane", "fixture_model", "frequency_sweep"],
    [src("KEYSIGHT_IMPEDANCE_HANDBOOK", [70, 86], "4.2 Calibration; 4.7 RF calibration"),
     src("TI_AN058_SWRA161", [20], "6.2.2 Calibration")],
    "측정 파일에 교정 방식·표준기·케이블·feed 위치를 기록한다.",
    "단순히 VNA에 연결한 지점과 원하는 안테나면이 같다고 가정하지 않는다.")
cond("Port extension does not remove all loss", ["all_port_based_antennas"],
    "전기 길이 보상은 위상을 보정하며 전송 손실을 무시하므로 충분히 짧고 저손실인 전송선에만 해당한다.",
    ["fixture_electrical_length_s", "fixture_loss_vs_frequency", "deembedding_method"],
    [src("KEYSIGHT_IMPEDANCE_HANDBOOK", [91], "4.7.7 Electrical length compensation")],
    "손실을 무시할 수 없으면 실제 급전면 교정 또는 fixture 네트워크 제거를 사용한다.",
    "TI AN058 p20의 return-loss 기준면 설명도 무시 가능한 추가 케이블 손실 조건을 확인하여 사용한다.")
cond("Measurement cable perturbs small grounds", ["small_ground_antennas"],
    "측정 케이블의 방향과 외피 전류는 작은 접지를 가진 PCB의 측정 결과를 바꿀 수 있다.",
    ["cable_route", "ferrite_locations", "ground_outline", "mounting_fixture"],
    [src("TI_AN058_SWRA161", [20], "6.2.2 Calibration"), src("NORDIC_NWP017", [25], "7. Equipment needed")],
    "케이블 경로를 고정하고 변화에 대한 민감도를 기록한다.",
    "ferrite 설치 위치도 결과에 영향을 줄 수 있어 하나의 고정값 보정으로 해결되지 않는다.")
cond("Far-field criterion depends on electrical size", ["all_radiating_antennas"],
    "원거리장 시작 거리의 근사는 안테나 전기적 크기에 따라 달라진다.",
    ["largest_dimension_m", "wavelength_m", "test_distance_m", "test_site"],
    [src("RS_8GE01_ANTENNA_BASICS", [7], "2.3 Far Field Conditions"), src("TI_AN058_SWRA161", [24], "6.3 OTA")],
    "2D²/λ를 모든 소형 안테나에 단독 적용하지 않고 측정 방법의 원거리장 요구를 선택한다.",
    "문서의 소형 안테나 약 2λ, 전기적으로 큰 안테나 약 2D²/λ는 근사 조건이며 반사 없는 환경까지 보장하지 않는다.")
cond("Regional channel plan is versioned metadata", ["LoRaWAN", "multi_region_radio"],
    "RP002는 국가/지역별 채널 계획을 제공하는 LoRaWAN 동반 규격이며 안테나 형상 공식이 아니다.",
    ["country_code", "channel_plan", "regional_parameter_version", "selected_channel_centers_hz", "occupied_bandwidths_hz"],
    [src("LORA_ALLIANCE_RP002_1_0_5", [11, 12], "2. Introduction; 2.1 Country Cross Reference Table")],
    "RF 대역 요구를 버전이 있는 프로필로 저장하고 변경 시 대역 검증을 다시 수행한다.",
    "이 자료만으로 특정 국가의 현행 법규 적합성을 자동 확정하지 않는다.")
cond("Microstrip model is for the feed geometry", ["microstrip_feed"],
    "Hammerstad–Jensen 모델은 마이크로스트립의 임피던스와 유효 유전율에 관한 모델이다.",
    ["trace_width_m", "substrate_height_m", "epsilon_r", "conductor_thickness_m", "frequency_hz"],
    [src("PAPER-071", [1], "Single microstrip; Strip thickness correction; Dispersion", "(1)-(12)")],
    "초기 추출 모델은 t→0 준정적 단일 마이크로스트립만 구현 대상으로 지정한다.",
    "원호 방사체, IFA arm, CPW, 유한 접지 PCB 전체의 λ/4 단축률 계산기로 사용하지 않는다.",
    evidence="source_described_applicability")
cond("FDTD units and geometry resolution", ["FDTD_simulation"],
    "mesh 물리 단위·최고 주파수·유전체 내 파장 및 최소 형상을 함께 고려해야 한다.",
    ["mesh_unit_m", "fmax_hz", "material_models", "smallest_feature_m"],
    [src("OPENEMS_MESH", section="Requirements; Mesh Resolution; Unit of Measurement")],
    "단위 스케일을 명시하고 방사부 가장자리·급전 gap·기판 두께의 mesh 표현을 확인한다.",
    "λ/10은 문서의 경험적 시작 해상도이며 정확도 증명이나 자동 합격값이 아니다.",
    [threshold("cell_length_over_shortest_wavelength", "<=", .1, "1", "openEMS mesh rule of thumb, not convergence proof")])
cond("FDTD mesh alignment and grading", ["openEMS_simulation"],
    "0두께 도체는 정확한 mesh 선에 정렬되어야 하고 port도 지원하는 셀 정렬을 충족해야 한다.",
    ["mesh_lines", "zero_thickness_surfaces", "port_extent", "adjacent_cell_ratios"],
    [src("OPENEMS_MESH", section="Requirements; Smoothing")],
    "mesh 평활화 이후 실제 정렬과 인접 셀 간격 비를 검사한다.",
    "SmoothMeshLines의 ratio 인수는 사후조건으로 보장되지 않으므로 결과를 확인한다.",
    [threshold("adjacent_mesh_spacing_ratio", "<=", 1.5, "1", "openEMS documentation recommendation")])
cond("PEC cannot predict conductor dissipation", ["openEMS_simulation"],
    "PEC는 저항 손실이 중요하지 않을 때 쓰는 이상 도체이며 thin conducting sheet는 유한 전도도·두께 모델이다.",
    ["conductor_model", "conductivity_s_per_m", "conductor_thickness_m", "loss_metric_required"],
    [src("OPENEMS_MATERIALS", section="Metal; Thin Conducting Sheet")],
    "효율 예측에서 PEC 가정을 표시하고 누락된 도체 손실을 기록한다.",
    "문서의 구리 예시 전도도는 실물 제조 공정 보증값이 아니다.")
cond("Material API constants and dispersion", ["openEMS_simulation"],
    "openEMS 일반 material의 epsilon·mu·kappa·sigma는 상수이며 주파수 의존 재질에는 별도 분산 모델이 제공된다.",
    ["epsilon_vs_frequency", "conductivity_vs_frequency", "material_fit_model", "fit_band_hz"],
    [src("OPENEMS_MATERIALS", section="General Material; Dispersive Materials")],
    "UWB 재질 데이터를 상수로 근사할 경우 근사 대역과 손실 오차를 기록한다.",
    "openEMS의 kappa는 전기 전도도이며 상대 유전율을 뜻하지 않는다.")
cond("NF2FF phase center and port reference metadata", ["openEMS_simulation"],
    "NF2FF phase center는 기록 box 내부에 있어야 하며 port reference impedance는 명시적 입력이다.",
    ["nf2ff_box", "phase_center_m", "port_reference_impedance_ohm", "theta_phi_sampling"],
    [src("OPENEMS_NF2FF", section="NF2FF: CalcNF2FF parameters"), src("OPENEMS_PORTS", section="Port (Base Class): parameters")],
    "좌표와 길이 단위를 저장하고 phase-center 포함 여부를 사전 검사한다.",
    "이 규칙만으로 모든 NF2FF 경계·매질 조건이 검증되는 것은 아니다.")
cond("Bérenger PML has discretization reflections", ["FDTD_simulation"],
    "연속 PML의 이상적 무반사 성질과 달리 격자 계산에서는 전도도 급변·두께·입사각에 따른 수치 반사가 남는다.",
    ["pml_model", "pml_cells", "conductivity_profile", "boundary_spacing_m"],
    [src("PAPER-070", [7, 10, 11, 13, 16], "2.4; 3. Numerical Experiments; 4. Conclusion")],
    "PML 셀 수/분포와 경계 위치를 기록하고 경계 변화에 대한 결과 민감도를 점검한다.",
    "1994년 split-field 논문의 설정을 모든 현대 PML 구현의 기본값으로 복사하지 않는다.",
    evidence="source_described_applicability")
cond("Yee foundation is not a complete modern solver specification", ["FDTD_simulation"],
    "Yee 논문은 등방성 매질에서 공간·시간이 엇갈린 전자기장 배치를 제시하며 mesh와 시간 간격의 결합을 논의한다.",
    ["solver_name_version", "time_step_rule", "material_model", "mesh"],
    [src("PAPER-068", [1, 2], "Maxwell equations; Grid Size and Stability Criterion"),
     src("OPENEMS_MESH", section="Courant-Friedrichs-Lewy (CFL) Criterion")],
    "실제 solver가 제공하는 검증된 시간 간격 결정 규칙을 사용한다.",
    "물리 PDF p2의 역사적 식 (7)/(8)을 현대 다차원 CFL 식으로 그대로 구현하지 않는다. openEMS는 기본적으로 Rennings2를 사용하므로 일반 CFL 식과 solver 선택도 구분한다.",
    evidence="source_described_applicability_with_editorial_caveat")
cond("RWG surface basis has a bounded model scope", ["MoM_surface_solver"],
    "RWG 논문은 인접 삼각형 쌍의 표면 전류 basis를 사용하여 도체 산란체의 EFIE/MoM 해를 구성한다.",
    ["triangular_surface_mesh", "edge_orientation", "boundary_edges", "medium_green_function"],
    [src("PAPER-069", [1, 3, 4], "Abstract; II. Theory; basis functions")],
    "내부 공통변의 방향·삼각형 연결과 전류 연속성을 검증한다.",
    "이 논문만으로 다층 유전체·유한 도전율 PCB solver 전체가 정의되는 것은 아니다.",
    evidence="source_described_applicability")
cond("Offline network calibration input compatibility", ["VNA_postprocessing"],
    "scikit-rf calibration의 measured/ideal 네트워크는 port 수·주파수 정보가 일치하고 표준기 순서가 대응해야 한다.",
    ["measured_standards", "ideal_standards", "calibration_algorithm", "frequency_grid", "port_count"],
    [src("SKRF_CALIBRATION", section="Creating a Calibration; One-Port Example; Two-port Calibrations; Switch-terms")],
    "입력 순서·단위·주파수·포트를 검사하고 원시 측정도 보존한다.",
    "TRL 등 self-calibration은 미리 정한 모든 ideal response를 요구하지 않는다. 일반 SOL 규칙을 모든 알고리즘에 강제하지 않는다.")
cond("Acceptance policies are product data", ["all"],
    "대역·효율·편파·지향성·거리·시간 정확도 요구는 제품마다 달라서 통합 전역 합격 수치를 만들지 않는다.",
    ["product_requirements", "selected_metric_definitions", "tolerances", "use_case_matrix"],
    [src("TI_AN058_SWRA161", [12, 23, 24], "5. Antenna Performance; 6. Antenna Measurements"),
     src("QORVO_APH007", [4, 5], "4. Antenna Specifications")],
    "요구사항이 비어 있으면 평가 결과는 수치 보고까지만 하고 pass/fail은 unknown으로 둔다.",
    "이 행은 출처의 용도별 논의를 근거로 제안한 소프트웨어 정책이며 제조사 의무 조항이 아니다.",
    evidence="our_proposed_acceptance_policy")
cond("UWB fidelity depends on the selected pulse and antenna pair", ["UWB_antenna_system"],
    "Liang 학위논문의 fidelity 비교는 입력 펄스 종류/폭과 송수신 안테나의 상대 방향을 바꾸면 결과가 달라짐을 보여준다.",
    ["input_pulse_definition", "antenna_pair", "relative_orientation", "system_transfer_function"],
    [src("PAPER-066", [153, 154, 180, 181], "6.1.1; 6.1.2; Tables 6-A, 6-B, 6-C")],
    "fidelity를 형상 자체의 단일 상수로 저장하지 않고 펄스·안테나 쌍·배치에 연결한다.",
    "표의 fidelity 수치는 측정 전달함수로 계산한 특정 파형 결과이며 모든 UWB 사용 사례의 성능 보증치가 아니다.",
    evidence="source_described_applicability")


method("VNA feed-plane impedance and matching sweep", ["all_port_based_antennas"],
    ["frequency_grid", "calibration_standards", "reference_plane", "fixture"],
    ["관심 대역에서 교정한다.", "안테나 급전면까지 fixture를 보상하고 radio 회로와의 연결 상태를 기록한다.",
     "복소 S11/Zin과 return loss, VSWR를 전 대역에서 저장한다."],
    ["s11_complex", "zin_ohm", "return_loss_db", "vswr", "calibration_metadata"],
    [src("TI_AN058_SWRA161", [20], "6.2.2 Calibration"), src("NORDIC_NWP017", [25], "7. Equipment")],
    "선택한 제품/대역 요구사항 및 교정 불확도를 기준으로 판단한다.",
    "좋은 S11 자체가 높은 radiation efficiency를 입증하지 않는다.")
method("Cable perturbation repeatability", ["small_ground_antennas"],
    ["baseline_cable_route", "fixture_state", "reference_s11"],
    ["기준 케이블 위치를 고정하고 측정한다.", "제어한 케이블 경로 또는 ferrite 위치 변화에서 다시 측정한다.",
     "공진·임피던스 변화와 설치 사진/좌표를 기록한다."],
    ["resonance_shift_hz", "delta_s11", "cable_sensitivity_record"],
    [src("TI_AN058_SWRA161", [20], "6.2.2 Calibration")],
    "허용 변화량은 측정 불확도와 제품 허용오차로 별도 정한다.",
    "문서의 민감도 설명을 시험 절차로 구체화한 제안이다.", evidence="our_proposed_validation_procedure")
method("Enclosed and loaded antenna retuning", ["IFA", "monopole", "UWB"],
    ["assembled_enclosure", "battery_or_metal_configuration", "body_use_state", "frequency_band"],
    ["최종 케이스·금속·접지 및 사용 상태로 조립한다.", "형상 길이 또는 매칭 소자를 조정한다.",
     "변경 후 입력 정합과 필요한 방사 성능을 재측정한다."],
    ["environment_configuration", "tuned_geometry", "matching_BOM", "s11", "radiation_metrics"],
    [src("NORDIC_NWP008", [3], "Tuning"), src("SILABS_AN1088", [6], "3.2 Tuning"),
     src("TI_AN058_SWRA161", [23], "6.2.5")],
    "실제 사용 상태별 성능 요구로 판단한다.")
method("OTA 3D pattern and integrated radiated power", ["all_radiating_antennas"],
    ["test_distance", "chamber_calibration", "angular_sampling", "polarization", "input_power_reference"],
    ["반사 영향을 억제한 시험장과 필요한 원거리장 조건을 확인한다.",
     "두 편파의 각도별 방사 전력을 측정한다.", "전 구면 적분과 정규화를 통해 TRP·패턴·이득 및 정의된 효율을 계산한다."],
    ["pattern_complex_or_power", "TRP_w", "peak_EIRP_w", "directivity", "gain", "efficiency_definition"],
    [src("TI_AN058_SWRA161", [24, 25, 26], "6.3 OTA Measurements"), src("RS_8GE01_ANTENNA_BASICS", [13, 14], "3.3-3.5")],
    "사용 방향 범위·편파·링크 예산의 요구사항을 기준으로 판단한다.",
    "패턴 2개 절단면만으로 전 구면 TRP가 측정되었다고 표시하지 않는다.")
method("Radio conducted power with path-loss correction", ["radio_frontend"],
    ["test_firmware", "calibrated_source", "spectrum_analyzer", "cable_loss_vs_frequency"],
    ["시험 carrier를 출력하고 보드 RF 출력에 케이블을 연결한다.",
     "알려진 RF source로 연결 경로 삽입 손실을 측정하여 보정한다.", "동작 대역 여러 주파수와 여러 보드에서 반복한다."],
    ["conducted_power_dbm", "path_loss_db", "frequency", "sample_id"],
    [src("NORDIC_NWP006", [4, 5, 7], "1; 2.1.1; 2.2")],
    "해당 칩·설정의 요구사항으로 비교한다.",
    "conducted power는 안테나 OTA 효율과 다른 측정이다.")
method("Radio matching verifies more than carrier power", ["nRF24xx_radio_frontend"],
    ["matching_BOM", "radio_test_firmware", "spectrum_analyzer"],
    ["매칭 소자 변경 때 TX 출력, 고조파와 RX LO leakage를 모두 측정한다.",
     "대역 내 여러 주파수를 비교하여 한 점의 최적화 부작용을 점검한다."],
    ["tx_power", "harmonic_levels", "rx_lo_leakage", "channel_sweep"],
    [src("NORDIC_NWP013", [2, 3, 4], "3. Tuning")],
    "nRF24xx 해당 제품의 설계 요구와 시험 지침을 적용한다.",
    "논문/가이드에 나온 수신 감도와 출력 관계를 모든 칩의 일반 법칙으로 사용하지 않는다.")
method("AoA custom-array feed impedance check", ["BLE_AoA_array"],
    ["array_port", "feed_disconnect_location", "pigtail_ground_connection", "reference_plane"],
    ["선택 port 가까이 기존 feed line을 분리한다.", "안테나 feed에 케이블 중심도체, 가까운 접지에 shield를 연결한다.",
     "맞춤 PCB에서 입력 임피던스를 확인한다."],
    ["port_zin", "port_s11", "connection_record"],
    [src("SILABS_AN1195", [27], "6.1 Antenna Impedance Measurement")],
    "참조 배열과 사용자 대역/튜닝 요구에 비교한다.",
    "문서는 동일성이 예상되는 참조 배열에서는 한 port 확인을 허용한다. 비대칭 커스텀 배열까지 충분하다는 뜻은 아니다.")
method("AoA manifold and mounting sensitivity", ["BLE_AoA_array"],
    ["complex_element_patterns", "polarizations", "mounting_materials", "angle_truth"],
    ["소자별 크기/위상 패턴과 좌표계를 저장한다.", "장착 재질/간격 조건에서 위상 변화를 비교한다.",
     "알려진 방위·고도 조건으로 알고리즘 출력 오차를 비교한다."],
    ["phase_pattern", "magnitude_pattern", "angle_error_distribution", "mounting_sensitivity"],
    [src("SILABS_AN1195", [16, 18, 31, 36, 37, 39, 40], "5. phase patterns; 5.7; 7. Real Environment Testing")],
    "제품의 각도 정확도 및 유효 시야각 요구에 따른다.",
    "source 사례를 종합해 제안한 검증 flow이며 문서의 특정 측정 결과를 보증치로 삼지 않는다.",
    evidence="our_proposed_validation_procedure")
method("UWB frequency and orientation group-delay characterization", ["UWB"],
    ["transfer_phase", "frequency_grid", "orientation_set", "reference_plane", "free_space_delay"],
    ["실제 사용 채널과 방향을 정의한다.", "보정된 전달 위상과 안테나 지연 정의를 기록한다.",
     "주파수 응답과 방향 변화에 따른 지연을 각각 보고한다."],
    ["group_delay_vs_frequency_s", "orientation_delay_variation_s", "phase_unwrapping_metadata"],
    [src("QORVO_APH007", [4, 5], "4.4; 4.8")],
    "ToF 정확도 예산과 선택한 칩 프로필에 따른다.",
    "두 안테나 전송 측정에는 양쪽 안테나와 전파 경로가 포함되므로 한 안테나 delay로 바로 간주하지 않는다.",
    [threshold("orientation_group_delay_variation_s", "<=", 100e-12, "s", "DW1000 APH007 only")],
    "our_proposed_validation_procedure")
method("UWB pulse correlation, ringing and spreading", ["printed_UWB_monopole"],
    ["excitation_time_series", "received_time_series", "probe_pose", "substrate_model", "time_sampling"],
    ["사용 펄스와 시간 축을 고정한다.", "방향별 전계/수신 신호를 취득한다.",
     "지연 최적화한 정규화 상관과 ringing·pulse spreading을 계산한다."],
    ["normalized_correlation", "pulse_width", "ringing_record", "probe_pose"],
    [src("PAPER-067", [2, 3, 4, 5, 6, 7, 8, 9], "2. Prototype; 3. Parameter Study; 4. Results")],
    "정의한 송신 펄스·용도에 대한 요구사항으로 판단한다.",
    "논문은 특정 CST virtual-probe 계산을 보고한다. 이것을 물리 실측 결과로 표기하거나 APH007 fidelity 정의와 자동 동일시하지 않는다.")
method("DW1000 reference-device delay calibration", ["UWB_DW1000"],
    ["at_least_three_transceivers", "known_pair_distances", "TWR_ranges", "PRF_channel_modes", "temperature"],
    ["동일 설정으로 장치 쌍의 TWR 거리와 실제 거리를 확보한다.",
     "실제 EDM과 측정 EDM의 차이를 줄이는 delay 값을 구한다.", "기준 장치와 교정 온도·설정을 보존한다."],
    ["aggregate_delay_s", "EDM_residuals_m", "reference_device_id", "calibration_settings"],
    [src("QORVO_APS014", [5, 6, 7], "2.1; 2.2.1 Reference Device Generation")],
    "목표 ranging 방식과 제품 정확도 요구에 적합한 delay 항목을 검증한다.",
    "PML/mesh 수치 수렴과 실제 RF chain/antenna delay 교정은 별개의 검증이다.")
method("DW1000 reported calibration population result", ["UWB_DW1000_EVB1000"],
    ["hardware_population", "calibration_method", "variation_statistic"],
    ["이 행은 재현 절차가 아니라 문서가 보고한 EVB1000 2000대 통계의 evidence record다."],
    ["sample_count", "uncalibrated_3sigma_range_equivalent_m", "calibrated_3sigma_range_equivalent_m"],
    [src("QORVO_APS014", [6], "2.1.2 Accuracy; Table 2")],
    "해당 EVB1000 population의 보고 결과이며 새 PCB의 합격 기준은 아니다.",
    "통계 분포·측정환경·실제 제품 편차를 별도 확인해야 한다.",
    [threshold("sample_count", "=", 2000, "count", "reported EVB1000 sample", "source_reported_result"),
     threshold("uncalibrated_3sigma_range_equivalent_m", "=", .30, "m", "reported EVB1000 variation", "source_reported_result"),
     threshold("calibrated_3sigma_range_equivalent_m", "=", .045, "m", "reported EVB1000 variation", "source_reported_result")],
    "source_reported_measured_result")
method("NFC equivalent coil extraction", ["NFC_reader_coil"],
    ["coil_impedance_at_carrier", "equivalent_series_model", "VNA_calibration"],
    ["13.56 MHz에서 코일 복소 임피던스를 측정한다.",
     "사용한 회로 모델에 따라 R과 L을 계산한다.", "Cpa 추정/미측정 여부와 R의 불확도를 기록한다."],
    ["series_L_h", "series_R_ohm", "Cpa_f", "parameter_status", "uncertainty"],
    [src("NXP_AN12549", [38, 40], "4.2")],
    "실물 코일 기반 초기값으로 circuit tuning에 사용하고 최종 파형 측정으로 확인한다.",
    "복잡한 기생공진 근처에서 Z=R+jωL 모델을 무조건 사용하지 않는다.")
method("NFC loaded waveform and operating-volume validation", ["NFC_PN5190_reader"],
    ["test_card_set", "phone_set", "relative_poses", "data_rates", "pulse_waveforms", "power_control_state"],
    ["실제 사용할 PICC/전화기와 위치 범위를 정의한다.",
     "로딩 상태별 파형과 통신 성공을 측정한다.", "Q·damping·matching 및 DPC 설정을 조정하고 재측정한다."],
    ["waveform_metrics", "communication_map", "loaded_impedance", "DPC_profile"],
    [src("NXP_AN12549", [11, 15, 54], "Antenna size; 3.1.2; 5. Dynamic Power Control")],
    "사용하는 규격/기기와 제품 작동 공간의 파형·통신 요구사항에 따른다.",
    "13.56 MHz S11 한 점만으로 NFC interoperability를 판정하지 않는다.", evidence="our_proposed_validation_procedure")
method("UHF assembled-chip power-transfer evaluation", ["UHF_RFID_tag"],
    ["antenna_complex_impedance", "assembled_chip_complex_impedance", "frequency_power_grid"],
    ["chip 접합 기생 성분과 전력 동작점을 포함한다.",
     "복소 켤레 정합 및 전력 전달 계수 τ를 주파수별로 계산한다.", "실제 부착 재질에서 다시 검증한다."],
    ["tau", "complex_match_error", "frequency_power_grid", "carrier_configuration"],
    [src("NXP_AN1715", [20, 25], "2.5; 4.1"), src("PAPER-043", [2], "2", "(2)")],
    "chip 활성화 전력과 시스템 링크 조건에 따른다.",
    "50 ohm VNA S11를 그대로 tag-chip 전력 전달 효율로 해석하지 않는다.")
method("EM mesh-convergence study", ["full_wave_simulation"],
    ["baseline_mesh", "refinement_sequence", "same_geometry_materials", "metric_vector", "project_tolerances"],
    ["mesh를 단계적으로 세분화하면서 형상·재질·포트 조건은 고정한다.",
     "공진, 복소 임피던스, 방사 전력, 방향별 패턴 또는 필요한 시간 지표의 변화를 비교한다.",
     "마지막 두 결과만이 아니라 변화 추세와 자원 사용량을 남긴다."],
    ["mesh_cells", "delta_resonance_hz", "delta_zin", "delta_radiation", "convergence_status"],
    [src("OPENEMS_MESH", section="Requirements; Mesh Resolution"), src("PAPER-068", [2], "Grid Size and Stability Criterion")],
    "사용자가 정한 수치 오차 허용량에 도달해야 pass로 표시한다. 기본 수치 임계값은 없다.",
    "이 절차는 자료의 mesh 의존성을 근거로 제안한 수치 검증 정책이다. 특정 cell 수가 검증 완료를 뜻하지 않는다.",
    evidence="our_proposed_acceptance_policy")
method("Absorbing-boundary sensitivity study", ["FDTD_simulation"],
    ["absorbing_boundary_model", "boundary_distance", "PML_parameters", "result_metrics"],
    ["경계 거리·PML 두께/분포를 제어하여 변경한다.",
     "반사와 관심 대역 결과의 변화를 비교한다.", "물리적 공진과 경계 유발 artifact를 구분한다."],
    ["boundary_configuration", "residual_reflection", "metric_differences", "boundary_convergence_status"],
    [src("PAPER-070", [7, 10, 11, 13, 16], "2.4; 3; 4")],
    "해당 solver·요구 오차에 맞춘 사용자 허용량을 사용한다.",
    "PML 이름 또는 문헌상 이상적 무반사 성질만으로 검증 합격을 부여하지 않는다.",
    evidence="our_proposed_acceptance_policy")
method("openEMS port and NF2FF postprocessing", ["openEMS_simulation"],
    ["port_waveforms", "port_reference_impedance", "nf2ff_recordings", "frequencies", "theta_phi_grid", "phase_center"],
    ["port의 입사/반사파와 총 전압/전류에서 S11와 Zin을 구한다.",
     "선택 주파수·각도·phase center로 NF2FF를 계산한다.",
     "수치 수렴 및 손실 모델의 범위를 함께 기록한다."],
    ["s11", "zin", "farfield_pattern", "radiated_power", "directivity", "simulation_metadata"],
    [src("OPENEMS_PATCH", section="Post-processing and plotting"), src("OPENEMS_NF2FF", section="CalcNF2FF; NF2FF Results")],
    "프로젝트 지표별 요구사항에 따른다.",
    "tutorial의 S11<-10 dB resonance 선택 코드·30k timestep·EndCriteria를 전역 solver 합격 기준으로 복사하지 않는다.")
method("Loss-model sensitivity for material-aware design", ["printed_antennas"],
    ["material_parameter_ranges", "conductor_model", "geometry", "frequency_band"],
    ["εr·손실·기판 두께의 검증된 범위 또는 불확도를 입력한다.",
     "같은 형상에서 각 재질 변동 사례를 해석한다.", "공진·매칭·방사 효율·UWB 펄스 지표의 변화를 저장한다."],
    ["material_scenarios", "metric_sensitivity", "uncertainty_envelope"],
    [src("NXP_AN1715", [25], "4.1"), src("PAPER-067", [5, 6, 7, 8, 9], "Parameter study"),
     src("OPENEMS_MATERIALS", section="General Material; Dispersive Materials")],
    "제조 공차와 제품 요구사항으로 판단하며 임의의 FR4 단일 수치를 보증하지 않는다.",
    "이 행의 자동화 절차는 자료들을 결합한 제안이다.", evidence="our_proposed_validation_procedure")
method("Offline SOL calibration with raw data retention", ["VNA_postprocessing"],
    ["measured_standard_networks", "ideal_standard_networks", "uncalibrated_DUT_network", "algorithm_metadata"],
    ["네트워크의 port/frequency와 표준기 순서를 검증한다.",
     "해당 알고리즘으로 error network를 구하고 DUT에 적용한다.", "raw 및 corrected 데이터와 calibration 파일을 함께 보존한다."],
    ["corrected_network", "calibration_coefficients", "raw_data_paths", "standard_definitions"],
    [src("SKRF_CALIBRATION", section="Creating a Calibration; One-Port Example")],
    "독립 check standard와 측정 오차 요구로 검증하도록 한다.",
    "마지막 독립 check standard 절차는 프로그램에 제안한 검증이며 tutorial 예시가 이를 모두 수행했다는 뜻은 아니다.",
    evidence="source_method_with_engineering_validation_extension")
method("Fixture de-embedding and renormalization metadata", ["VNA_postprocessing"],
    ["measured_network", "fixture_network", "frequency_grid", "z0_by_port"],
    ["Touchstone의 주파수·port 순서·z0를 보존한다.",
     "알려진 fixture 네트워크를 cascade 관계에 맞게 제거한다.", "reference-plane 이동과 z0 재정규화를 서로 다른 처리 이력으로 기록한다."],
    ["deembedded_network", "reference_plane", "z0", "processing_history"],
    [src("SKRF_NETWORKS", section="Basic Properties; Cascading and De-embedding"),
     src("KEYSIGHT_IMPEDANCE_HANDBOOK", [91], "4.7.7")],
    "fixture 모델의 신뢰도·독립 검증·수치 안정성에 따라 유효성을 판단한다.",
    "단순 port-extension은 손실 fixture의 완전한 de-embedding과 동등하지 않다.",
    evidence="source_method_with_engineering_validation_extension")
method("Matching network sweep and parasitic comparison", ["matching_network"],
    ["measured_antenna_network", "component_models", "source_z0", "frequency_grid"],
    ["측정 안테나 network에 후보 매칭 회로를 연결한다.",
     "단일 중심 주파수 값과 전 대역 성능을 모두 저장한다.", "실제 부품/패드 기생 성분을 포함한 결과를 시제품과 비교한다."],
    ["candidate_BOM", "matched_network", "bandwidth_metrics", "component_sensitivity"],
    [src("SKRF_MATCHING", section="Matching with Lumped Elements; Single-Stub Matching"), src("SILABS_AN1275", [14, 38], "4; 7.4"),
     src("NORDIC_NWP017", [22], "Practical components")],
    "회로 손실·동작 대역·부품 공차와 실제 측정을 기준으로 선택한다.",
    "scikit-rf 예제의 특정 impedance/frequency는 계산 예시이며 특정 PCB를 검증한 값이 아니다.",
    evidence="our_proposed_validation_procedure")
method("Antenna measurement uncertainty budget", ["OTA_metrology", "EMC_antenna_factor"],
    ["measurand_definition", "calibration_certificates", "repeatability_data", "setup_geometry", "sensitivity_coefficients"],
    ["receiver·cable·source drift·안테나 위치·편파·반사·noise·repeatability의 기여를 정한다.",
     "각 항의 표준 불확도와 분포, 상관관계를 기록한다.", "결합 및 확장 불확도를 결과와 함께 보고한다."],
    ["uncertainty_components", "combined_standard_uncertainty", "coverage_factor", "expanded_uncertainty"],
    [src("NPL_GUIDE73", [19, 20, 80], "4.1; Table 1; 10. Uncertainties"),
     src("NIST_TN1507", [9, 10, 18, 19], "4. Assessment; 5. Summary")],
    "프로젝트 measurand와 측정법에 맞는 budget을 구성한다.",
    "NPL·NIST의 예제 숫자를 다른 시험장·PCB 안테나의 보증 불확도로 복사하지 않는다.")
method("OATS repeatability and check standards", ["OATS_standard_antenna_method"],
    ["AUT_repeat_measurements", "check_standard_history", "ambient_signal_measurement", "test_signal"],
    ["시험 신호를 꺼서 ambient를 확인한다.", "독립 측정 반복과 check standard 이력을 비교한다.",
     "현장·주파수별 변동을 불확도 항목에 반영한다."],
    ["repeatability", "check_standard_deviation", "ambient_record", "site_uncertainty"],
    [src("NIST_TN1507", [18], "4.9 Measurement Repeatability and E-field Environmental Interaction")],
    "자기 시험장의 반복성과 불확도 요구를 기준으로 판단한다.",
    "문서는 NIST의 특정 OATS/SAM을 다룬다. 이것으로 VNA feed-plane 교정을 대체할 수 없다.")
method("Geometry and model applicability preflight", ["all"],
    ["topology", "material_stackup", "frequency_band", "feed_type", "model_scope", "known_unknown_fields"],
    ["형상이 폐루프/개방 원호/IFA/슬롯/패치 중 무엇인지 연결 관계로 판별한다.",
     "선택 모델의 적층·급전·물리 단위·파라미터 범위와 입력을 대조한다.",
     "적용 범위 밖 또는 필수값 미확보 상태를 명시한 뒤 full-wave 또는 측정 단계로 넘긴다."],
    ["model_eligibility", "missing_inputs", "unsupported_assumptions", "next_validation_stage"],
    [src("NORDIC_NWP008", [1, 2], "2-4"), src("SILABS_AN1088", [3], "2.1"),
     src("NXP_AN1715", [25, 46], "4.1; slot design"), src("PAPER-071", [1], "Single microstrip")],
    "임계 수치가 아니라 입력 적합성 게이트다. 미확보 항목은 추정치로 채우지 않는다.",
    "이 게이트는 제조사/논문을 근거로 제안한 프로그램 정책이다.", evidence="our_proposed_acceptance_policy")
method("Measured UWB antenna-pair transfer function", ["UWB_antenna_system"],
    ["two_antenna_setup", "VNA_calibration", "separation_m", "relative_orientation", "frequency_grid"],
    ["송신 및 수신 안테나의 간격과 face-to-face/side-by-side 등 방향을 정의한다.",
     "반사 영향을 억제한 환경에서 VNA로 전달 크기·위상을 측정한다.",
     "전달함수와 group delay 및 정의된 입력 펄스에 대한 수신 파형을 함께 평가한다."],
    ["transfer_magnitude", "transfer_phase", "system_group_delay_s", "setup_geometry", "pulse_fidelity"],
    [src("PAPER-066", [152, 153, 154, 155, 157, 158, 180, 181], "6.1; 6.1.2; Chapter 6 fidelity tables")],
    "제품의 실제 채널·펄스·방향 요구에 따른다.",
    "논문의 1.2 m는 해당 시험 배치다. 측정에는 두 안테나와 전파 경로가 포함되므로 단일 방사체 고유 delay로 표시하지 않는다.")


model("Exact circular-arc centerline length", "theta_rad = theta_deg*pi/180; L_arc = r_centerline*abs(theta_rad)",
    [variable("r_centerline", "m", "도체 중심선 원호 반지름"), variable("theta_rad", "rad", "원호 중심각"),
     variable("theta_deg", "deg", "입력 각도"), variable("L_arc", "m", "원호 중심선 길이")], [],
    "평면에서 반지름이 일정한 원호의 기하학적 길이 계산", "공진 주파수·유효 유전율·최적 PCB 지름의 경험식이 아니다.",
    "derived_geometric_identity", "exact_geometry_identity", "원호 미소 길이 ds=r dθ를 적분한 항등식. 제조사 설계 규칙으로 출처를 붙이지 않는다.",
    [{"parameter": "r_centerline", "operator": ">", "value": 0, "unit": "m"}])
model("Free-space wavelength", "lambda0 = c0/f_Hz",
    [variable("lambda0", "m", "자유공간 파장"), variable("c0", "m/s", "자유공간 광속"), variable("f_Hz", "Hz", "주파수")],
    [src("TI_AN058_SWRA161", [5], "3.3 Wavelength Calculations", "(1)")],
    "자유공간 파장의 단위 일관 계산", "PCB 방사체 길이가 자동으로 lambda0/4가 된다는 뜻이 아니다.",
    notes="원문 식의 주파수 표기는 GHz이지만 숫자 c는 m/s이므로 실행식에서는 반드시 f_Hz로 정규화한다. 표 수치와 교차확인했다.")
model("Voltage reflection coefficient for real reference impedance", "Gamma = (Zin-Z0)/(Zin+Z0)",
    [variable("Zin", "ohm complex", "급전면 입력 임피던스"), variable("Z0", "ohm real", "양의 실수 기준 임피던스"), variable("Gamma", "1 complex", "반사 계수")],
    [src("SILABS_AN1275", [5], "2.2 Reflection Coefficient")],
    "동일 reference plane의 양의 실수 Z0 전송선 포트", "복소 chip 켤레 정합에서의 power-wave reflection 정의를 이 식과 혼동하지 않는다.")
model("S11 magnitude, return loss and VSWR", "S11_dB=20*log10(abs(Gamma)); return_loss_dB=-S11_dB; VSWR=(1+abs(Gamma))/(1-abs(Gamma))",
    [variable("Gamma", "1 complex", "실수 Z0 포트 반사 계수"), variable("S11_dB", "dB", "반사파 진폭비 dB"),
     variable("return_loss_dB", "dB", "양의 return loss 표기"), variable("VSWR", "1", "전압 정재파비")],
    [src("SILABS_AN1275", [4, 5], "2.1; 2.2"), src("OPENEMS_PATCH", section="Post-processing and plotting")],
    "수동 단일 포트의 |Gamma|<1; |Gamma|=1은 VSWR 무한대", "S11_dB와 양의 return loss를 같은 부호로 저장하지 않는다.",
    notes="Gamma=0에서는 S11=-infinity, return loss=+infinity, VSWR=1. 숫자 저장에 Infinity를 쓰지 않으려면 별도 상태를 둔다.")
model("Mismatch efficiency and mismatch loss", "eta_mismatch=1-abs(Gamma)**2; mismatch_loss_dB=-10*log10(eta_mismatch)",
    [variable("eta_mismatch", "1", "입사 전력 중 포트가 수용하는 비율"), variable("Gamma", "1 complex", "반사 계수"),
     variable("mismatch_loss_dB", "dB", "반사로 인한 전력 전달 손실")],
    [src("SILABS_AN1275", [4], "Table 2.1")],
    "양의 실수 reference impedance의 수동 단일 포트", "도체·유전체 손실 또는 방사 효율을 계산하는 식이 아니다.",
    notes="원문 표의 'Mismatch Loss (%)' 열은 실제로 전달되는 비율(1-|Gamma|²)×100이므로 이 데이터셋은 eta_mismatch로 명명한다.")
model("Radiation and realized-gain bookkeeping", "eta_rad=P_rad/P_accepted; eta_total=eta_rad*eta_mismatch; G=eta_rad*D; G_realized=eta_mismatch*G",
    [variable("P_rad", "W", "방사 전력"), variable("P_accepted", "W", "안테나 포트가 수용한 전력"),
     variable("eta_rad", "1", "방사 효율"), variable("eta_mismatch", "1", "매칭 효율"), variable("eta_total", "1", "총 효율"),
     variable("D", "1", "동일 방향 directivity"), variable("G", "1", "gain"), variable("G_realized", "1", "mismatch 포함 gain")],
    [src("QORVO_APH007", [4], "4.3"), src("RS_8GE01_ANTENNA_BASICS", [13, 14], "3.4; 3.5")],
    "동일 주파수·방향·편파·기준면에 대해 선형 전력비로 계산", "dBi 수치끼리 곱하지 않는다. 급전선 손실의 포함 여부를 따로 정의한다.",
    "derived_combination_of_source_definitions", notes="R&S의 practical gain을 이 데이터셋에서는 mismatch 포함 realized gain에 대응시킨다.")
model("UHF RFID conjugate power-transfer coefficient", "tau=4*real(Z_chip)*real(Z_ant)/abs(Z_chip+Z_ant)**2",
    [variable("Z_chip", "ohm complex", "입력 전력·패키지·접합을 포함한 chip 임피던스"),
     variable("Z_ant", "ohm complex", "같은 포트의 안테나 임피던스"), variable("tau", "1", "수동 chip 전력 전달 계수")],
    [src("PAPER-043", [2], "2. Methods for Conjugate Impedance Matching", "(2)"), src("NXP_AN1715", [20], "2.5", "(35)")],
    "수동 수신 태그 등가회로에서 R_chip>0 및 R_ant>0; tau=1은 Z_ant=conj(Z_chip)",
    "50 ohm 기준 S11의 절댓값만으로는 계산할 수 없다.", notes="사용자 업로드 PDF p2를 시각 확인했다.")
model("UWB normalized waveform correlation", "rho=max_over_tau(integral(s1(t)*s2(t-tau),dt)/sqrt(integral(s1(t)**2,dt)*integral(s2(t)**2,dt)))",
    [variable("s1", "signal amplitude", "입력 실수 펄스 파형"), variable("s2", "signal amplitude", "출력/전계 실수 파형"),
     variable("t", "s", "시간"), variable("tau", "s", "최적화하는 시간 이동"), variable("rho", "1", "정규화된 최대 상관")],
    [src("PAPER-067", [3], "2. Prototype antenna", "(1)")],
    "두 파형 에너지가 0이 아니고 같은 시간 샘플링/윈도 정의가 있는 경우", "모든 fidelity 표준이 이 식을 쓰는 것은 아니다. APH007의 99%와 자동 연결하지 않는다.",
    notes="논문 식은 상관의 절댓값을 취하지 않으므로 부호 반전 허용 여부를 임의로 바꾸지 않는다.")
model("Single-frequency series coil estimate", "R_series=real(Z); L_series=imag(Z)/(2*pi*f)",
    [variable("Z", "ohm complex", "측정 코일 임피던스"), variable("f", "Hz", "측정 주파수"),
     variable("R_series", "ohm", "직렬 등가 저항"), variable("L_series", "H", "직렬 등가 인덕턴스")],
    [src("NXP_AN12549", [38, 40], "4.2")],
    "해당 주파수에서 Z≈R+jωL로 표현되는 코일의 초기 등가값", "기생 C가 강한 자기공진 근처 또는 비선형 구동을 일반화하지 않는다.",
    "derived_from_source_equivalent_circuit", notes="L/R 추출과 Cpa 추정은 다른 상태로 저장한다.")
model("Ideal LC reactances", "X_L=2*pi*f*L; X_C=-1/(2*pi*f*C)",
    [variable("f", "Hz", "주파수"), variable("L", "H", "이상 인덕턴스"), variable("C", "F", "이상 커패시턴스"),
     variable("X_L", "ohm", "유도성 리액턴스"), variable("X_C", "ohm", "용량성 리액턴스")],
    [src("SILABS_AN1275", [12], "4.2 Design Formulas")],
    "이상 집중소자 초기 매칭 계산", "부품 ESR·ESL·자기공진·패드·선로 효과가 큰 경우 실제 모델로 교체한다.",
    notes="문서의 X_C는 양의 크기로 쓰인 식이며 여기서는 jX의 부호 관례에 맞춰 음수를 명시했다.")
model("Uniform microstrip zero-thickness quasi-static model", 
    "u=w/h; F=6+(2*pi-6)*exp(-(30.666/u)**0.7528); Z01=eta0/(2*pi)*ln(F/u+sqrt(1+(2/u)**2)); a=1+ln((u**4+(u/52)**2)/(u**4+0.432))/49+ln(1+(u/18.1)**3)/18.7; b=0.564*((epsilon_r-0.9)/(epsilon_r+3))**0.053; epsilon_eff=(epsilon_r+1)/2+(epsilon_r-1)/2*(1+10/u)**(-a*b); Z0=Z01/sqrt(epsilon_eff)",
    [variable("w", "m", "마이크로스트립 선폭"), variable("h", "m", "기판 위 strip과 접지 사이 높이"), variable("u", "1", "w/h"),
     variable("epsilon_r", "1", "기판 상대 유전율"), variable("epsilon_eff", "1", "준정적 유효 유전율"),
     variable("eta0", "ohm", "공기/진공 파동 임피던스"), variable("Z01", "ohm", "균일 공기 매질 대응 선로 임피던스"),
     variable("Z0", "ohm", "마이크로스트립 특성 임피던스"), variable("F", "1", "보조 함수"), variable("a", "1", "보조 함수"), variable("b", "1", "보조 함수")],
    [src("PAPER-071", [1], "Single microstrip", "(1)-(5); t→0 limit of (8)")],
    "uniform single microstrip, air above, dielectric slab and reference ground, negligible strip thickness, quasi-static initial estimate",
    "finite-ground curved radiator, open-arc monopole, IFA resonance, CPW, coupled lines, soldermask, dispersion and finite copper thickness are not included",
    notes="p1 이미지를 보며 식을 확인했다. 논문이 εeff 모델의 0.2% 정확도를 기술한 범위는 εr≤128, 0.01≤u≤100. 이 수치는 manufactured PCB 최종 정확도 보증이 아니다.",
    domain=[{"parameter":"u","min":.01,"max":100,"unit":"1","role":"source_accuracy_domain"},
            {"parameter":"epsilon_r","min":1,"max":128,"unit":"1","role":"max_source_bound_min_ordinary_dielectric_scope"},
            {"parameter":"conductor_thickness_over_h","value":0,"unit":"1","role":"selected_model_limit"}])
model("Far-field distance approximations", "r_small_approx=2*lambda0; r_large_approx=2*D**2/lambda0",
    [variable("r_small_approx", "m", "문서의 소형 안테나 원거리장 거리 근사"), variable("r_large_approx", "m", "전기적으로 큰 안테나 근사"),
     variable("D", "m", "가장 큰 안테나 치수"), variable("lambda0", "m", "자유공간 파장")],
    [src("RS_8GE01_ANTENNA_BASICS", [7], "2.3 Far Field Conditions"), src("TI_AN058_SWRA161", [24], "6.3", "(7)")],
    "R&S 구분: 작은 안테나와 D≫λ인 큰 안테나를 각각 검토", "이 식만으로 측정장의 반사·편파·불확도 적합성이 검증되지 않는다.",
    notes="단일 universal minimum으로 hard-code하지 않는다.")
model("Effective area and gain", "A_eff=lambda0**2*G/(4*pi); P_received_max=S_incident*A_eff",
    [variable("A_eff", "m^2", "최대 유효 수신 면적"), variable("lambda0", "m", "자유공간 파장"), variable("G", "1", "선형 gain"),
     variable("S_incident", "W/m^2", "입사 평면파 전력 밀도"), variable("P_received_max", "W", "최대 수신 전력")],
    [src("RS_8GE01_ANTENNA_BASICS", [14], "3.6 Effective Area")],
    "문서의 최대 수신 조건 및 matched antenna gain", "기하 면적과 유효 면적은 같지 않다. 편파·정합 손실이 있으면 별도로 반영한다.")
model("Independent uncertainty combination", "u_c=sqrt(sum((c_i*u_i)**2)); U=k*u_c",
    [variable("u_i", "same as measurand", "각 입력의 표준 불확도"), variable("c_i", "conversion sensitivity", "민감도 계수"),
     variable("u_c", "same as measurand", "결합 표준 불확도"), variable("k", "1", "명시한 포함 인자"), variable("U", "same as measurand", "확장 불확도")],
    [src("NIST_TN1507", [10, 18, 19], "4; 5", "(2), (5)"), src("NPL_GUIDE73", [20], "Table 1 notes")],
    "상관이 없는 입력에 대한 선형화된 오차 전파", "상관항이 유의하면 공분산 항이 필요하다. k=2를 모든 분포의 정확한 95%로 고정하지 않는다.",
    notes="문서의 예제는 주로 dB 단위와 단위 민감도 계수이다. 새 실험의 budget 값을 직접 입력해야 한다.")
model("Constant-conductivity approximation to dielectric loss", "kappa=2*pi*f_ref*epsilon0*epsilon_r*tan_delta_ref",
    [variable("kappa", "S/m", "openEMS 전기 전도도"), variable("f_ref", "Hz", "손실 tangent가 지정된 기준 주파수"),
     variable("epsilon0", "F/m", "진공 유전율"), variable("epsilon_r", "1", "상대 유전율"), variable("tan_delta_ref", "1", "기준 주파수의 손실 tangent")],
    [src("OPENEMS_PATCH", section="General parameter setup: substrate_kappa"), src("OPENEMS_MATERIALS", section="General Material; Dispersive Materials")],
    "단일 기준 주파수에서 손실 tangent를 상수 전도도 모델로 대응시키는 예시", "상수 kappa는 전 대역에서 상수 tanδ와 같지 않다. 광대역에는 dispersive fit 또는 근사 오차 확인이 필요하다.",
    "derived_generalization_of_source_example", notes="tutorial의 숫자 1e-3·2.45 GHz·εr=3.38을 새로운 재질의 데이터로 취급하지 않는다.")
model("Yee historical stability expression held for review", None,
    [variable("mesh_spacing", "m", "공간 격자 간격"), variable("time_step", "s", "시간 간격")],
    [src("PAPER-068", [2], "Grid Size and Stability Criterion", "historical (7), (8)")],
    "역사적 근거와 검토 필요 항목 보존", "원문의 식을 현대 solver CFL 구현으로 사용하지 않는다.",
    "source_formula_not_transcribed_due_to_known_scope_issue", "blocked_historical_expression_use_separate_modern_CFL_model",
    "원문 물리 PDF p2의 식은 시각 확인했으나 현대 다차원 CFL bound의 구현식으로 부적절하여 expression=null이다. 아래 별도 modern CFL model은 OPENEMS_MESH의 식을 근거로 한다.")
model("Group delay from the phase of a transfer function", "phi=unwrap(arg(H)); omega=2*pi*f; tau_g=-d(phi)/d(omega)",
    [variable("H", "1 complex", "보정된 전달함수"), variable("phi", "rad", "전달함수의 연속 위상"),
     variable("omega", "rad/s", "각주파수"), variable("f", "Hz", "주파수"), variable("tau_g", "s", "group delay")],
    [src("PAPER-066", [153, 154], "6.1.1 Description of UWB Antenna System", "(6.4) and group-delay discussion")],
    "exp(+j*omega*t) 시간 관례에서 H의 위상 미분; coherent frequency sweep",
    "phase wrap을 먼저 처리해야 한다. deep null/낮은 SNR에서 미분이 불안정할 수 있다. antenna pair 측정은 전파 경로와 양쪽 안테나를 포함한다.",
    "source_definition_normalized", notes="논문은 H=|H|exp(-j*phi_source)로 표기한다. 여기서는 phi=arg(H)로 정의해 tau_g=-dphi/domega로 통일했다. 스무딩/차분 방식은 추출되지 않아 별도 검증이 필요하다.")
model("Ideal series-RL coil Q", "Q_series=abs(X_L)/R_series=2*pi*f*L_series/R_series",
    [variable("Q_series", "1", "직렬 RL 모델의 Q"), variable("X_L", "ohm", "코일 유도성 리액턴스"),
     variable("R_series", "ohm", "직렬 손실 저항"), variable("L_series", "H", "직렬 인덕턴스"), variable("f", "Hz", "주파수")],
    [src("SILABS_AN1275", [12], "4.2 Design Formulas: Qs and XL"), src("NXP_AN12549", [15, 38, 40], "3.1.2; 4.2")],
    "R_series>0의 직렬 RL 등가 모델이 유효한 주파수에서 bare-coil 초기 Q 계산",
    "PICC·matching·loading을 포함하는 NFC 전체 channel Q 또는 공진 근처 기생 C 포함 Q와 동일하지 않다.",
    "derived_combination_of_source_formulas", notes="작은 R의 측정 불확도가 Q에 크게 전파된다. 최종 NFC Q는 파형으로 검증한다.")
model("Conventional rectangular-grid FDTD CFL bound", "dt_max=1/(v*sqrt(1/dx**2+1/dy**2+1/dz**2)); dt<=dt_max",
    [variable("dx", "m", "x 방향 셀 간격"), variable("dy", "m", "y 방향 셀 간격"), variable("dz", "m", "z 방향 셀 간격"),
     variable("v", "m/s", "해당 매질의 파동 속도"), variable("dt", "s", "시간 스텝"), variable("dt_max", "s", "일반 CFL 상한")],
    [src("OPENEMS_MESH", section="Courant-Friedrichs-Lewy (CFL) Criterion")],
    "명시적 일반 FDTD의 직교격자에서 공간 셀 크기와 시간 간격의 안정성 관계",
    "불균일 격자·분산 매질·특수 알고리즘의 전체 안정성 조건을 이 한 식으로 대체하지 않는다. 시간 안정성은 공간/시간 수렴 정확성과 다르다.",
    notes="해당 openEMS 문서는 기본 시간 간격 방법이 CFL이 아니라 비균일 격자용 Rennings2임을 명시한다. SetTimeStepMethod 및 solver 버전을 기록하고 solver의 안전한 자동 계산을 우선한다.")


PARAMETERS = [
    ("frequency_hz", "Hz", "design input", "주파수 및 채널 범위를 명시"),
    ("trace_width_m", "m", "geometry", "PCB 도체 선폭"),
    ("substrate_height_m", "m", "stackup", "전체 PCB 두께와 급전선-접지 거리 구분"),
    ("epsilon_r", "1", "material", "측정 주파수·방법·방향·공차와 함께 보관"),
    ("tan_delta", "1", "material", "주파수와 재질 시험 조건 필수"),
    ("conductivity_s_per_m", "S/m", "material", "도체 또는 openEMS kappa 모델 구분"),
    ("s11_complex", "1 complex", "measurement", "주파수·z0·기준면과 결합"),
    ("radiation_efficiency", "1", "radiation", "P_rad/P_accepted"),
    ("total_efficiency", "1", "radiation", "mismatch 포함 여부와 feed-loss 기준면 명시"),
    ("gain", "1 or dBi", "radiation", "선형 값과 dBi 값 별도 필드"),
    ("group_delay_s", "s", "time domain", "주파수·방향·단일/안테나 쌍 기준 명시"),
    ("coil_L_h", "H", "NFC", "등가회로 및 측정 주파수 명시"),
    ("coil_R_ohm", "ohm", "NFC", "직렬/병렬 등가 및 측정 불확도 명시"),
    ("coil_Q", "1", "NFC", "bare coil/loaded channel Q 구분"),
    ("chip_impedance", "ohm complex", "UHF RFID", "전력·주파수·패키지·접합 의존"),
    ("coverage_factor", "1", "uncertainty", "값 및 해석 근거 별도 입력"),
]


def write_json(name, records, kind):
    data = {"schema_version": SCHEMA, "dataset_kind": kind,
            "source_page_numbering": "1-based physical PDF page; HTML uses named section, no invented page number",
            "source_language": "English", "extraction_language": "Korean",
            "record_count": len(records), "records": records}
    (HERE/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def write_csv(name, records):
    if not records:
        return
    with (HERE/name).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        for row in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, separators=(",", ":")) if isinstance(v, (list, dict)) else ("" if v is None else v) for k, v in row.items()})


for filename, rows, kind in [("conditions", C, "applicability_conditions"),
                             ("validation_methods", V, "validation_methods"),
                             ("model_formulas", M, "model_formulas")]:
    write_json(filename+".json", rows, kind)
    write_csv(filename+".csv", rows)

param_records = [dict(parameter=k, unit=u, group=g, note_ko=n) for k,u,g,n in PARAMETERS]
write_json("parameter_dictionary.json", param_records, "parameter_dictionary")
write_csv("parameter_dictionary.csv", param_records)

catalog_raw = json.loads((ROOT/"package/catalog.json").read_text())
if isinstance(catalog_raw, list):
    catalog_rows = catalog_raw
else:
    catalog_rows = next((v for v in catalog_raw.values() if isinstance(v, list) and v and isinstance(v[0],dict)), [])
catalog = {r.get("id", r.get("source_id")):r for r in catalog_rows}
source_ids = sorted({s["source_id"] for row in C+V+M for s in row["sources"]})
uploaded = {"PAPER-043":"marrocco2008.pdf", "PAPER-068":"kaneyee1966.pdf", "PAPER-069":"rao1982.pdf", "PAPER-070":"berenger1994.pdf", "PAPER-071":"hammerstad1980.pdf"}
coverage=[]
for sid in source_ids:
    locators=[s for row in C+V+M for s in row["sources"] if s["source_id"]==sid]
    pages=sorted({p for s in locators for p in (s["physical_pdf_pages"] or [])})
    sections=sorted({s["section"] for s in locators})
    cr=catalog.get(sid,{})
    record=dict(source_id=sid, title=cr.get("title"), referenced_physical_pdf_pages=pages or None,
                referenced_sections=sections, review_scope="targeted page/section extraction, not full-document exhaustive annotation",
                condition_count=sum(any(s["source_id"]==sid for s in r["sources"]) for r in C),
                validation_method_count=sum(any(s["source_id"]==sid for s in r["sources"]) for r in V),
                model_formula_count=sum(any(s["source_id"]==sid for s in r["sources"]) for r in M))
    path=None
    for key in ("relative_path", "local_path", "file_path", "path", "download_path"):
        if cr.get(key):
            p=Path(cr[key]); candidates=[p,ROOT/"package"/p,ROOT/p]
            path=next((x for x in candidates if x.is_file()), None)
            if path:break
    if path is None and sid in uploaded:
        p=ROOT.parent/"upload"/uploaded[sid]
        if p.is_file():path=p
    if path is None and sid == "PAPER-066":
        p=ROOT/"research/late_recovery/liang_chungbuk.pdf"
        if p.is_file():path=p
    if path is None:
        found=list((ROOT/"package/files").rglob(sid+"__*"))
        path=next((p for p in found if p.is_file()), None)
    record["source_file_name"] = path.name if path else None
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest() if path else None
    if path and path.suffix.lower()==".pdf":
        import fitz
        with fitz.open(path) as pdf:
            record["source_physical_pdf_page_count"]=len(pdf)
            assert all(1<=p<=len(pdf) for p in pages), (sid,pages,len(pdf))
    else: record["source_physical_pdf_page_count"]=None
    coverage.append(record)
write_json("source_coverage.json", coverage, "source_coverage")
write_csv("source_coverage.csv", coverage)

notes=f"""RF PCB 안테나 — 적용 조건·검증 방법·모델 식 추출본

구성
- conditions: {len(C)}개 적용 조건
- validation_methods: {len(V)}개 검증 방법/보고 결과
- model_formulas: {len(M)}개 모델 레코드(보류 expression=null 1개 포함)
- source_coverage: {len(coverage)}개 출처의 실제 인용 페이지/절
- parameter_dictionary: 대표 변수의 단위 및 해석
- build_validation_dataset.py: 원본 catalog를 읽기만 하는 재생성 스크립트

사용법과 근거 등급
1. source_prescribed_condition: 원문이 요구/권고하는 조건.
2. source_described_applicability: 원문의 모델 범위 또는 사례 조건.
3. source_reported_measured_result: 원문이 보고한 특정 실험 결과. 새 PCB의 보증 수치 아님.
4. our_proposed_acceptance_policy / our_proposed_validation_procedure: 출처를 바탕으로 제안한 프로그램 정책/절차. 제조사의 의무 조항으로 표현하지 말 것.
5. source_definition_normalized / derived_*: 정의·단위·수학적 조합을 명시적으로 정리한 레코드.

페이지
모든 PDF 페이지는 파일 첫 페이지를 1로 하는 물리적 페이지 번호다. 논문 인쇄 페이지 번호와 다를 수 있다. HTML에는 페이지를 지어내지 않았으며 section을 기록했다. 추출은 해당 페이지/절의 검토이며 모든 페이지의 수치가 구조화되었다는 뜻이 아니다.

임계값
default_pass_fail_threshold 및 universal_acceptance_threshold는 null이다. DW1000 APH007의 return loss, 방사 효율, fidelity, 방향 group delay 수치는 source_scoped_targets / numeric_constraints에 별도로 보관하며 automatically_enabled=false이다. NFC Q=22, Nordic 길이 여유, openEMS mesh 경험칙도 원문의 특정 시작 조건이지 전역 최적값이 아니다.

중요 정의
- radiation_efficiency=P_rad/P_accepted. S11만으로 알 수 없다.
- total_efficiency는 mismatch를 포함한다. gain/realized gain은 기준면과 포함 손실을 분명히 한다.
- TI AN058은 legacy gain/efficiency 설명에 mismatch를 포함한다. R&S/APH007 정의와 단순 병합하지 않았다.
- S11_dB는 반사 진폭비의 dB이며 return_loss_dB=-S11_dB이다.
- Silicon Labs AN1275 표 2.1의 'Mismatch Loss (%)' 열은 실제 전달 비율이다. 여기서는 eta_mismatch로 정규화했다.
- UHF RFID tag는 assembled chip의 켤레 정합·power transfer를 평가하며 모든 포트를 50 ohm으로 고정하지 않는다.
- NFC coil Q와 PICC가 연결된 loaded channel Q는 구분한다.
- UWB APH007의 방향 group delay 권고를 임의 frequency ripple 한도로 바꾸지 않는다. pulse correlation과 모든 fidelity 정의를 동일시하지 않는다.

모델 한계
- L_arc=r*theta는 정확한 기하학적 항등식이다. RF 공진 길이 예측식 또는 제조사 원형 PCB 설계 규칙이 아니다.
- Hammerstad–Jensen 추출은 zero-thickness quasi-static single microstrip feed 초기 계산용이다. 유한 접지·원호 모노폴·IFA·CPW·soldermask·dispersion은 이 버전에 포함되지 않는다.
- PAPER-068 Yee 물리 p2의 역사적 Eq.(7)/(8)을 현대 다차원 CFL 구현식으로 그대로 쓰지 않도록 보류했다. 모델 expression은 null이다. 실제 solver가 검증한 안정 시간 간격 규칙을 사용해야 한다.
- RWG 논문은 surface-current basis/EFIE의 근거이며 다층 PCB solver 전체 명세가 아니다.
- Bérenger의 연속 PML 이상적 무반사와 이산화 PML의 잔류 반사는 구별한다.
- openEMS tutorial의 timestep/end criterion/S11 예시 기준은 전역 solver 검증 기준이 아니다.
- TI AN058의 wavelength 식은 분모 단위 표기가 혼동될 수 있어 f_Hz로 정상화했다.

미확보/미추출 값
원문에 없는 battery clearance, 모든 재질의 epsilon_r, 보편적 효율 한도, 각 제품의 통과 오차 등은 추정해 넣지 않았다. 원래 형상과 다른 원형 PCB 반지름별 설계 데이터가 확보되었다는 주장도 하지 않는다. API 입력에 필요한 세부 material/geometry 값은 다른 extraction datasets와 source_id로 연결해야 한다.

이 파일은 자료 기반 초기 데이터셋이다. 실제 안테나 solver 실행·시제품 제작·VNA/OTA 측정이 수행되었다는 뜻은 아니다. Numeric equations는 추출 후 solver 단위 시험과 검증 사례를 추가해야 한다. 데이터 파일에는 실행 평가를 위한 eval 코드가 포함되지 않는다.
"""
(HERE/"README_notes.txt").write_text(notes, encoding="utf-8")

qa={"conditions":len(C),"validation_methods":len(V),"model_formulas":len(M),"unique_sources":len(coverage),
    "formula_rows_with_null_expression":sum(r["expression"] is None for r in M),
    "all_default_acceptance_thresholds_null":all(r["default_pass_fail_threshold"] is None for r in V),
    "all_constraints_opt_in":all(not t["automatically_enabled"] for r in C for t in r["numeric_constraints"]),
    "all_source_files_located":all(r["sha256"] for r in coverage),
    "physical_pdf_page_bounds_checked":True,
    "inspection_notes":"Hammerstad p1, Marrocco p2, Yee p2 visually checked. Remaining source extraction used embedded PDF text and saved HTML sections."}
(HERE/"QA_summary.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(qa,ensure_ascii=False,indent=2))
