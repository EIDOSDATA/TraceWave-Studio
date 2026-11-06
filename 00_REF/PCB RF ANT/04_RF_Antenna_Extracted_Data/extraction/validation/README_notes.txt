RF PCB 안테나 — 적용 조건·검증 방법·모델 식 추출본

구성
- conditions: 47개 적용 조건
- validation_methods: 26개 검증 방법/보고 결과
- model_formulas: 19개 모델 레코드(보류 expression=null 1개 포함)
- source_coverage: 33개 출처의 실제 인용 페이지/절
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
