# 안테나 계열별 형상 생성, 초기 합성, 검증 계약

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

## 1. 세 가지 서로 다른 기능

각 계열에서 `geometry_generator`(주어진 치수로 형상 생성), `seed_synthesizer`(목표에서 초기 치수 추천), `verified_design`(지정 조건의 계산, 실측 근거)을 구분한다. 사용자 임의 형상을 그릴 수 있다고 그 형상의 자동 주파수 합성식이 있다고 가정하지 않는다. 모든 실제 RF 성능은 적층, 유한 접지, 급전, 주변 환경, 수치조건과 연결한다.

이 장은 SYN-001, CAD-009, PHY-010~021, AUG-003을 구현하기 위한 model-card 계약이다. 수식의 정확한 정의와 출처는 [EQ 레지스트리](09_RFAD_수식과_물리_모델.md), 초기 치수/원문은 [추출 자료](20_RFAD_참고_자료_통합.md)에 있다.

## 2. TemplateCard 공통 스키마

| 속성 | 내용 |
| --- | --- |
| template_id/version/family | 안정된 ID, 형상 계열, 설계 개정 |
| topology | conductor/ground/short/feed/slot/net/port 관계와 기대 연결 |
| generator | primitive/Boolean/transform graph와 parameter bindings |
| inputs | 필수, 선택 값, 단위, default의 source/조건, domain |
| seeds | 사용 수식 EQ, 문헌/CAD record, 가정, seed 범위/오차/미확인 항목 |
| constraints | 공간, layer keepout, minimum width/gap, connectivity, curvature |
| validation_envelope | frequency/material/size/port/environment/solver 조합 및 evidence |
| outputs | source design patch, geometry preview, source/assumption/constraint report |
| status | geometry_only/seed_available/complete_physical/simulated/converged/measured 등을 독립 기록 |

빈 환경, ground, material을 고정된 숨은 기본값으로 채워 verified template를 만들지 않는다. 합성 결과는 원본을 변경하지 않는 candidate patch이며 사용자가 선택한 뒤 project command로 commit한다.

위 status 단어들은 하나의 순차 enum이 아니다. geometry/seed 지원 여부, 입력 완비, 실행, 수렴 및 측정 증거를 별도 필드로 저장하고 각 필드에 snapshot, 적용 범위와 evidence ID를 연결한다. 문헌에서 측정된 원본과 사용자가 재료/크기를 변경한 파생 candidate가 같은 measured 배지를 공유하지 않는다. generator/seed가 현재 구현되었다는 뜻도 아니며 개발 승인 전에는 모두 설계 계약이다.

## 3. 계열별 계약

| ID / 계열 | 생성 파라미터와 topology | 초기 치수 경로 | RF 검증과 단계 |
| --- | --- | --- | --- |
| FAM-01 원호 모노폴 | board outline, center/r/start/sweep/width, feed, open end, finite ground/keepout | G031 등 원문 geometry 또는 EQ-003/004의 제한된 길이 seed, EQ-001/002 exact geometry | R1 원호 기준군. 원호 radius나 board diameter 하나로 공진 보증 금지 |
| FAM-02 IFA/MIFA | 방사 가지, short, feed의 별도 path/net, feed-short spacing, meander width/gap | 조건 일치한 TI/Nordic 등의 reference card + 길이 seed | R1. short 접촉, feed topology, 전층 keepout, ground size, coupling 검사 |
| FAM-03 PIFA | radiating plate height, short pin/plate, feed, finite ground, dielectric supports | verified reference card와 parameter sweep | 3D생성/급전, 높이효과 검증 후 R2; PCB 평면 IFA와 다른 모델 |
| FAM-04 printed dipole | 두 arm, feed gap, balance/balun/cable model, nearby PCB | 제한된 반파 seed와 원문 보정 범위 | geometry/seed와 환경 포함 검증 구분. differential/common-mode GAP-013 |
| FAM-05 patch | rectangle/circle 등 patch outline, ground, h/epsilon_r, inset/probe/feed | rectangular TM10은 EQ-041. circular/CP/multimode는 별도 source-backed card | rectangular 기준 fixture는 R0/R1, 다른 mode/형상 검증은 개별 승격 |
| FAM-06 slot | ground cutout path/width/length, feed crossing/CPW/slot transition | 검증된 slot reference와 mode-specific model | 단순 도체 모노폴 길이 공식을 slot에 그대로 적용하지 않음 |
| FAM-07 UWB planar monopole | disk/ellipse/rect/taper radiator, neck/feed gap, partial ground, notch | 원문 치수, design space + broadband optimization | R2, S11와 Tx/Rx pulse/group-delay 검증 분리 |
| FAM-08 tapered slot/Vivaldi | flare curve, aperture, throat, transition, cavity, substrate | geometric taper + reference transition, 주파수 target은 EM/검증 template에서 탐색 | R2 이상; taper 그리기만으로 broadband impedance/패턴 보증 금지 |
| FAM-09 log-periodic | element lengths/positions/spacing, feed topology, scale ratio | 검증된 reference의 scale/spacing rule | 주기 치수 생성과 active-region/급전모드 성능은 별도 |
| FAM-10 spiral | arm count, inner/outer radius, angular range, pitch/width/gap, feed/balun | exact polar geometry + 검증된 frequency envelope의 reference | finite substrate/cavity/feed 포함 해석이 필요 |
| FAM-11 NFC/inductive loop | turns, outer/inner size, width/spacing, layer/via, ferrite, tuning/load | NXP 등 source model을 조건에 맞게 사용; 실제 L/R/Q는 EQ-025/026의 정의로 추출 | R3, self-resonance, loaded Q, M/k/거리/금속효과 검증 |
| FAM-12 UHF RFID | chip terminals, dipole/meander/T-match/loop, package/strap | chip의 frequency/power state에 맞춘 reference와 EQ-027 목적 | R3, 50ohm S11 최적화와 conjugate power-transfer를 구분 |
| FAM-13 MIMO/array/AoA | component instance transforms, shared ground, element ports, drive weights | 개별 model-card 배치 + coupling-aware EM | R2/R3. independent element pattern 합산과 coupled field basis를 구분 |
| FAM-14 flex/conformal | 평면 원본, bend axis/radius/angle, neutral layer, layer thickness/material axes | 기하 변환, 제조 strain 가정과 reference | R3. undeformed planar 물성/두께를 자동 유지하는 근사 명시 |
| FAM-15 user-defined/inverse | allowed primitives/polygons, graph constraints, material region/topology | 사용자가 준 reference 또는 검증된 optimization representation | 임의 drawing은 R1 editor; inverse search는 AUG-003/R3 |

위 단계는 generator/seed/검증 범위를 구분한 계획이다. 신규 해석 기능은 [통합 요구](03_RFAD_사용자_요구사항.md)의 clause 단계와 [support gate](01_RFAD_설계_결정과_범위.md)를 함께 적용한다.

## 4. 원호 생성 알고리즘

1. source frame와 centerline radius를 SI로 정규화한다. radius와 width는 별도 parameter다.
2. signed sweep를 보존해 시작/끝 좌표를 계산한다. 열린 원호는 `0 < abs(sweep) < 2*pi`이고 닫힌 원은 별도 topology다. 끝점이 같더라도 0도와 360도를 구별하고 여러 회전의 겹친 stroke는 별도 지원 모델 없이 허용하지 않는다.
3. width/2 offset으로 양쪽 경계를 만든다. inner radius<=0 또는 자기교차가 생기는 path는 지원한 특별 region 모델이 없으면 거부한다.
4. feed/neck/short 등의 path를 각각 만들고 의도한 join/cap/Boolean으로 연결한다.
5. 실제 board outline과 ground/keepout/other copper/environment 사이의 clearances를 검사한다.
6. layer thickness로 physical copper를 생성한다. EM sheet, surface/volume 선택은 이후 projection 단계다.
7. geometry preview에 arc-only centerline length, feed path length, union region area, 최소 gap을 따로 표시한다.

board diameter가 바뀌면 `radius=board_radius-edge_clearance-width/2`처럼 명시한 식이 있는 변수만 자동 재계산한다. 독립 radius를 무조건 보드에 맞춰 강제로 바꾸지 않는다. 서로 독립인 target f와 actual geometry를 보존하고 목표 미달은 EM 결과로 판정한다.

## 5. IFA/MIFA 초기화

IFA는 open radiator뿐 아니라 feed와 ground short가 있는 topology로 정의한다. 템플릿은 short branch ID와 feed port/reference conductor를 필수로 갖는다. IFA 모양이지만 short가 끊긴 모델을 같은 템플릿의 유효 결과로 평가하지 않는다.

초기 길이 계산은 EQ-004의 seed이며 meander 인접 구간의 결합, finite ground, battery, substrate 때문에 actual resonance와 다를 수 있다. reference template를 크기 비율로 변경할 때 copper width/gap/ground/stackup도 함께 scale할지 각 parameter별로 명시한다. 전부 고정된 재질에서 길이 하나를 scale하는 사례와 완전 기하학적 scaling은 같은 조건이 아니다.

## 6. 직사각형 patch 초기화

EQ-041의 기본 rectangular TM10 근사를 이용할 때 f, epsilon_r, h, ground와 feed 가정을 기록한다. W->epsilon_eff->fringing DeltaL->effective length->physical L 순서로 초기값을 만든다. 실제 feed 위치/inset/connector와 유한 ground, soldermask, 손실, enclosure는 후속 모델에 포함해 정합을 조정한다. 이 초기식만으로 circular/dualband/CP/corner-trim patch를 자동 생성하지 않는다.

output은 dimension candidate와 approximation status다. 물리 L<=0, 비현실적인 h/W, 재료 유효대역 이탈 등은 template guard에서 진단하고 무조건 양수로 clamp해 숨기지 않는다.

## 7. taper, spiral의 기하와 RF 의미

Vivaldi 등의 flare에 사용할 수 있는 기하 예는 y(x)=c1 exp(a x)+c2이다. x=0,L에서 y0,y1을 맞출 때 c1=(y1-y0)/(exp(aL)-1), c2=y0-c1이며 a는 1/m 단위를 갖는다. a->0에서는 cancellation을 피하는 선형 limit 또는 안정적인 expm1 연산을 사용한다. 이 식은 경계곡선 정의이며 bandwidth/gain 식이 아니다. transition과 cavity의 RF model은 template source가 따로 필요하다.

실제 평가는 `y(x)=y0+(y1-y0)*expm1(a*x)/expm1(a*L)`로 endpoint를 보존하며 `a=0`이면 `y0+(y1-y0)*x/L`을 사용한다. domain은 `L>0`, `0<=x<=L`, 유한 a이며 expm1도 overflow할 수 있으므로 지원 수치 범위 밖을 진단한다. y가 슬롯의 반폭인지 도체 경계 좌표인지 card에서 선언하고 상하 경계, aperture, throat와 급전 transition의 실제 최소 gap을 검사한다. 식 자체가 슬롯/도체 의미를 결정하지 않는다.

Archimedean spiral의 기하 예는 r(theta)=r0+b*theta이고 같은 arm의 한 회전 radial pitch는 2*pi*b다. 다중 arm의 실제 최소 gap은 arm 수, phase, width를 포함해 계산한다. pitch를 곧바로 도체 간 gap이라고 부르지 않는다. 로그주기 generator의 연속 길이 비 L_(n+1)=tau*L_n도 기하 규칙이며 feed/spacing/방사 성능의 전체 설계식이 아니다.

이러한 순수 기하식은 수학적으로 유도한 identity다. 출처가 없는 RF 경험식을 추가한 것이 아니다. RF seed, 목표 결정에는 출처가 있는 ModelCard와 EM 검증을 사용한다.

## 8. 합성 실패와 추천 표시

candidate에 source/template version, EQ IDs, 입력, default provenance, assumptions, violated constraints, unsupported models, predicted-vs-simulated status를 넣는다. 후보 없음, 공간 부족, 미지원 source model, 수치 실패를 분리한다. initial candidate preview에 S11/효율의 그래프를 임의로 채우지 않는다.

template 자체의 지원 범위를 넘는 scale/재질/board shape는 unverified extrapolation으로 표시하고 실제 해석을 요구한다. 자동 최적화가 목표를 못 맞추면 가장 작은 violation의 후보와 한계를 보여주되 목표 충족으로 바꾸지 않는다.

## 9. 원문과 회귀 기준

source-backed geometry는 현재 확보된 원본과 [자료 통합](20_RFAD_참고_자료_통합.md)의 source/parameter/location을 대조한다. 과거 `data/extracted/geometry/geometries.json` 경로는 현재 저장소에 없는 산출물이므로 실행 입력으로 가정하지 않는다. 개발 승인 후 importer가 확보된 자료와 누락 자료를 구별해 registry를 생성해야 한다. template별 runtime regression에는 parameter inputs, expected topology, analytic dimension checks, generated region/solid checks, source envelope, full-wave evidence를 구분한다. field/efficiency 비교에 필요한 물리 정보가 빠진 레코드는 geometry-only로 유지한다. 형상 library가 많다는 이유만으로 모든 계열의 성능을 검증했다고 발표하지 않는다.

계열별 최소 반례는 원호 0/전체 회전과 끝단 gap, IFA short 제거, patch의 무효 L/재료 범위, slot의 구리/빈 영역 반전, spiral의 arm 간 단락, flex의 층 교차, 배열의 port permutation이다. 이는 기존 VT에 연결할 시험 설계이며 수행 기록이 아니다. 사용자 승인 뒤 각 card의 지원 envelope와 반례를 검증한 범위만 승격한다.
