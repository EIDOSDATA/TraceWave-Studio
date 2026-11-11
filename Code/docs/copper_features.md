# 접지 영역, 패드, 비아와 IFA 급전 모델

갱신일: 2026-11-11 KST. 승인 기준선 RFAD-D0-3.4의 도체 의미 모델과 단일 포트 IFA 범위를 구현하는 초기 확장이다. 제품 소스와 시험은 Code 안에서 관리하고 01_Docs의 승인 기록과 최초 IFA의 미정 물성/제작 조건은 유지한다.

## 원본 의미와 편집

신규 객체도 geometry 컬렉션과 기존 안정 UUID/명령/저장/스냅샷/undo/redo를 사용한다. 공통 layer_id/net_id/material_ref/source_ref/include_in_em/include_in_export를 유지하며 CAD나 해석 때문에 원본을 다시 쓰지 않는다. 길이와 각도는 기존 Quantity 또는 매개변수 UUID 참조이며 미정값을 저장할 수 있다.

| kind | 추가 필드 | 의미 |
| --- | --- | --- |
| planar_region | outer, holes | outer는 외곽 점 목록, holes는 내부의 빈 loop 목록. 각 점은 x/y 길이 수량 |
| pad | pad_shape, center, size, rotation | circle 또는 rectangle. size는 두 길이 수량이며 원형은 같은 지름 두 개. 실제 두께는 소속 도체층에서 사용 |
| via | center, end_layer_id, finished_hole_diameter, plating_thickness, tool_hole_diameter, fill, pad_ids | layer_id는 아래 시작층, end_layer_id는 위 도착층. fill=none인 중공 도금 관통 비아. pad_ids는 명시적 연결 패드 UUID 목록 |

다각형은 각 loop 3점 이상, 전체 최대 64점과 구멍 8개를 지원한다. 마지막에 첫 점을 반복하지 않는다. CW/CCW 원본을 보존하고 자기 교차, 중복/되돌아가는 변, 0 면적, 외곽에 접하는 구멍, 교차/중첩된 구멍을 거절한다. 미정 좌표가 있으면 저장은 허용하되 실제 형상 계산은 차단한다. 접지 영역의 빈 곳을 구리로 채우거나 잘못된 경계를 자동 보정하지 않는다.

패드에는 화면용 추가 높이를 만들지 않는다. 원형과 회전 사각 패드를 지원하며 mask/paste margin과 부품 실장 모델은 후속이다. 비아에는 패드를 자동 생성하지 않는다. 드릴/도금이 미정인 비아는 2D에서 중심 표식으로 구분하며 실제 지름을 추정하지 않는다. 연결할 두 도체층은 명시하고 패드 참조가 부족한 초안은 저장 가능하지만 CAD/EM 전에 보완해야 한다.

GUI는 polygon 수치 입력에서 첫 loop를 외곽, 빈 줄로 나눈 다음 loop들을 빈 영역으로 받는다. 큰 다각형의 속성은 작은 coordinate_table DTO로 전달하며 x/y 입력 방식, 숫자와 길이 매개변수를 편집한다. 선택지는 DTO의 coordinate_choices에서 공유한다. 각 셀의 읽기 전용 unit은 보통 mm이며 mm 환산이 넘치는 극단값은 m로 표시해 수정 가능성을 유지한다. 이 표는 기존 꼭짓점 개수를 유지한다. 변경하지 않은 좌표의 단위/출처/매개변수 참조를 그대로 보존하고 변경한 숫자만 표시 단위의 명시적 입력으로 적용한다. 비아 연결 패드는 목록에서 여러 개를 선택한다. 구멍 내부는 면 선택 대상에서 제외하고 비아는 연결 범위의 도체층 표시 설정을 따른다.

## CAD와 실제 관통 형상

Open CASCADE가 다각형 outer/holes를 정확한 면으로 구성해 실제 층 두께로 압출한다. 사각/원형 패드도 같은 실제 두께를 사용한다. 비아의 내부 반지름은 finished_hole_diameter/2, 외부 반지름은 내부 반지름+plating_thickness다. 외부 반지름으로 substrate와 관통 도체를 drill한 뒤 별도의 중공 도금 barrel을 구성한다. 구멍을 충진 원통으로 대체하지 않는다.

초기 CAD profile은 최외측 도체층 사이의 관통 PTH를 지원한다. blind/buried via와 외부에 추가 적층이 있는 불명확한 span은 거절한다. tool bore가 미정이면 원본을 미정으로 유지하고 finished bore+2*plating의 모델 drill 근거를 sidecar에 기록한다. 알려진 tool bore가 이 모델과 다르면 자동 보정하지 않고 거절한다. 실제 제조 드릴 공차/도금 공정의 확정값을 생성했다는 의미는 아니다.

양 끝에 명시한 pad가 실제 annulus로 연결되는지 검사한다. 동일 net/유효 재료의 접촉만 허용하고 다른 net의 도체와 barrel 접촉은 차단한다. 같은 층의 도체는 기존 규칙으로 합치며 barrel은 별도 body로 유지해 층 의미를 보존한다. sidecar에는 start layer anchor, span, pad 및 drill 원본 대응을 기록한다. STEP 재입력에서도 구멍/체적/단면/양끝 접속을 확인한다. 이 재입력은 동일 OCCT kernel이며 독립 수신 CAD나 제조 합격은 후속이다.

## openEMS와 IFA 급전

[독립 손실 분할](pcb_loss_precision.md)은 sheet가 대체하지 않은 edge에서 실제 QuarterCell 전도도 기여율로 유전체와 PTH를 나눈다. sheet edge의 전체 일은 평면 도체에만 배정한다. 원본 비아/패드별 전력과 중복 없는 합계를 보존하며 GHz 구리의 skin depth 정밀도는 미확립 상태로 구분한다.

다각형 구멍은 모든 꼭짓점 높이의 정확한 경계 교차로 면을 분할하여 빈 영역을 보존한다. 임의 간격 샘플링으로 hole을 채우지 않는다. 선/원호와 원형 pad의 곡선은 명시적 polygon 오차를 사용하고, 동박 sheet에는 입력한 유한 전도도와 실제 두께를 전달한다.

비아는 유한 전도도의 중공 체적 모델을 사용한다. 곡면 Cylinder를 conducting sheet에 넣는 잘못된 경로를 사용하지 않는다. 체적 도체에는 상대 유전율도 실제로 필요하므로 사용자 입력을 요구하고 임의 1로 채우지 않는다. sheet에서 소비하지 않는 금속 유전율/손실과 구분한다. 비아 구멍과 도금, pad 접속의 격자 표현 및 실제 CSXCAD 우선순위를 확인하며 연결이 사라지면 준비를 차단한다. 매우 얇은 도금의 skin-depth 손실 정확도와 격자 수렴은 별도 검증 대상이다.

CAD barrel은 실제 동박 외면까지이고 EM barrel은 두 동박 sheet가 위치한 유전체 접면 사이로 투영한다. 원본 적층/두께와 이 z_range_mm 근사를 계획/소비 보고서에서 구분한다. 연결 검사는 CSXCAD 재료 우선순위를 실제 Yee 전기 edge 중심에서 평가하며 operator_coefficients_checked=false다. solver의 최종 계수나 전류 연속성 수렴을 독립 검증했다는 의미가 아니다.

IFA에서는 ground, short, radiator와 feed가 DC에서 같은 net으로 연결될 수 있다. 포트 양단의 서로 다른 geometry UUID와 실제 열린 급전 gap을 사용하고, net 이름만으로 잘못된 단락이라고 거절하지 않는다. 반대로 role=short라고 쓰는 것만으로 접속을 인정하지 않는다. 명시적 형상 연결 그래프와 native 격자의 연결을 확인한다.

포트는 동일 sheet 면의 x/y 방향 gap과 다른 sheet 사이 z 방향 gap을 지원한다. 급전선과 pad는 실제 구리 형상으로 소비하고 포트 위치/방향/저항/기준면은 사용자 입력을 유지한다. 지름/두께/재료 또는 접속을 추정해 맞추지 않는다. 상세 수치 제한은 [PCB 해석 계약](pcb_solver_contract.md)을 따른다.

## 초기 IFA와 실행 fixture의 구분

IFA 실행 fixture는 승인 초기 외형인 40 x 60 mm, 40 x 10 mm 안테나 영역과 2.4~2.4835 GHz를 사용한다. 독립된 급전선, 패드, 단락부, 유한 접지 polygon과 빈 영역을 명시한다. 0.93 mm core, 동박 각 35 um와 epsilon_r=4.2/tan_delta=0.018/전도도 58000000 S/m는 실행 시험을 위한 가정이며 제조사 데이터가 아니다. 초기 승인 fixture의 미정 물성을 덮어쓰지 않는다.

현재 실행 fixture의 기준면은 이상적인 로컬 안테나 gap이다. 승인된 실물 보드의 SMA 접속면, SMA launch, 마스크, pi 정합의 0 ohm 부품과 DNP pad 기생 효과, 실제 재료/제작 공차를 모두 검증한 상태는 아니다. 이 차이는 모델/fixture에 기록하며 S11 목표 충족이나 측정 일치를 주장하지 않는다. 상세 제작 모델은 사용자가 확정한 조건으로 후속 확장한다.

비아는 작은 별도 PTH fixture로 준비/실행을 확인한다. 이 fixture의 완성 구멍 0.6 mm, 도금 0.1 mm, drill 0.8 mm는 명시적 시험 가정이며 기본 제조값이 아니다. 40 x 60 mm IFA에 얇은 실제 도금까지 함께 넣었을 때의 비용/수렴 검증은 별도다.

현재 결과 상태는 computed_unvalidated이며 정식 IFA 수렴/방사/실측 검증으로 승격하지 않는다. 테스트와 재현 결과는 [개발 상태](development_status.md)에 기록한다.
