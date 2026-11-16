# 계약 예시, 정상 및 실패 시나리오

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

## 1. 예시의 지위

이 문서는 후속 코드/단위/계약 검토를 위한 합성 입력 명세와 최초 IFA 검증 보드의 초기 기준을 정의한다. 여기에 이름을 붙인 example JSON은 현재 제공되지 않으며 구현 단계에서 생성하고 검수할 예정이다. openEMS 실행 결과나 실제 비콘 실측이 아니다. 기존 Nordic G031 geometry source는 별도의 추출 레코드를 사용한다. 목표 주파수와 보드 조건을 채택한 것은 성능 합격을 뜻하지 않는다.

## 2. geometry-only 프로젝트

후속 fixture 이름은 `example_arc_geometry_only.json`으로 예약한다. 입력은 보드 원점 (0,0,0), 오른손 좌표, 원형 보드 반지름 12 mm, 유전체 범위 z=[0,1.530] mm, 상면 도체 z=[1.530,1.565] mm이다. 원호 중심은 (0,0), 중심선 반지름 9 mm, 시작각 0 rad, CCW sweep pi/2 rad, 선폭 1 mm, 끝단은 radial butt cap으로 정의한다. 하부 동박과 GND, feed, port, RF 물성은 없으며 없는 항목을 숨은 값으로 보완하지 않는다.

중심선 길이 L=9*pi/2 mm, inner radius=8.5 mm, outer radius=9.5 mm이다. 원호 도체 면적은 4.5*pi mm^2, 두께 0.035 mm의 부피는 0.1575*pi mm^3이다. 보드 외곽과 원호 외곽의 최소 이격은 2.5 mm이다. 이 산술 기대값은 geometry 생성 코드와 독립 계산하고 비교 허용오차는 해당 CAD profile에서 정한다. 2.4 GHz를 목표 metadata로 저장하더라도 공진 주파수나 정상 해석 결과를 뜻하지 않는다.

| 동작 | 기대 결과 |
| --- | --- |
| 파일 저장, 재열기 | 성공, 미정 field 상태 유지 |
| 2D geometry/3D solid 생성 | 정의한 기하 범위에서 가능, 재질은 unknown metadata |
| EM 실행 계획 | E_MATERIAL_UNKNOWN, E_PORT로 차단 |
| S11/효율 표시 | 결과 없음. 임의 demo 곡선 생성 금지 |
| geometry-only STEP | 해당 profile을 명시한 경우 생성 가능. RF/material omission을 sidecar에 기록 |
| manufacturing 승인 | 제조 profile과 연결/급전 조건이 미완비이므로 완료로 표시하지 않음 |

원호가 보드 안에 들어가는지와 실제 RF 정합이 맞는지는 별도다. 정상 저장 fixture와 의도된 해석 실패 fixture를 같은 파일로 검사할 수 있다.

## 3. 수식 정의 확인 fixture

후속 `example_single_port_power.json` fixture에 명시할 입력은 incident=1 W, reflected=0.25 W, radiated=0.60 W다. accepted=0.75 W, dissipated=0.15 W, radiation efficiency=80%, total efficiency=60%다. directivity=3이면 gain=2.4, realized gain=1.8이며 세 값은 선형 비율이다. |S11|=0.5일 때 S11_dB는 약 -6.0206 dB, return loss는 약 6.0206 dB, VSWR=3이다.

이 값은 단일포트, 수동, 명시된 기준 전력 fixture다. multiport/load/complex wave의 일반 검증을 대신하지 않는다. reference vectors와 단위/특이점 검사는 [수식](09_RFAD_수식과_물리_모델.md) 및 [VT-020](14_RFAD_검증과_수용_기준.md)을 따른다.

## 4. revision과 snapshot 시나리오

아래의 생성/계획/준비 단계는 [11번 API 분류](11_RFAD_해석기_어댑터_계약.md)에 따른 TaskRef의 완료 operation_result를 받은 뒤 다음 단계로 진행한다. 접수 ACK를 최종 SnapshotRef나 PreparedPlan으로 사용하지 않는다.

1. revision A에서 SnapshotRef S1을 생성한다. S1은 별도 UUID와 revision A, content hash를 가진다.
2. S1에서 AnalysisPlan P1을 만들고 prepare로 PreparationArtifact Q1과 PreparedPlan PP1을 생성한다.
3. PP1을 실행해 raw R1을 얻는다. 동시에 사용자가 trace width를 바꾸면 revision B가 된다.
4. R1의 provenance는 S1/A에 유지된다. B의 현재 결과처럼 표시하지 않는다.
5. B에서 폭을 원래 값으로 되돌렸더라도 실제 physics/config/toolchain hash가 일치하는지 확인한 뒤 compatible reuse를 결정한다.

## 5. 외부 정합만 바꾸는 시나리오

raw n-port와 복소 field basis가 충분하고 physical copper/port/lumped boundary가 동일한 상태에서 외부 network L/C 값을 바꾼다. network.derive가 새 네트워크와 port incident vector/field coefficients를 만들고 metrics/field 합성을 다시 계산한다. raw EM은 재사용 가능하다. 실물 pad 배치나 inline native lumped element가 바뀌면 raw 무효화가 필요하다.

field basis가 없으면 network response만 계산하고 loaded radiation은 미평가로 표시한다. 정합이 좋아졌다는 이유만으로 기존 gain에 임의 보정값을 더하지 않는다.

## 6. 주요 실패 fixture 목록

| 입력, 사건 | 기대 처리 |
| --- | --- |
| 원호 r<=0, inner radius<=0, NaN | 단위/정의역/geometry 진단 |
| IFA short 삭제 | topology invalid, 해당 template 유효성 실패 |
| source Dk가 미정/충돌 | 값 선택/가정 기록 전 mandatory 실행 차단 |
| tan_delta-derived sigma와 동일 손실 성분의 중복 입력 | loss partition 검토 필요 오류 |
| um<->mm 중복 변환 | expected thickness/scale fixture 실패 |
| user input expression의 cycle | cycle path와 field IDs 출력 |
| unknown native field scale | 절대 power/gain 평가 차단 |
| singular Z conversion, zero denominator | mask/status/conditioning diagnostic, 0으로 조작하지 않음 |
| GND/금속과 잘못 교차하는 NF2FF 기록 표면/잘못된 경계 | solver-specific preflight 실패. 유한 ground 전체를 유효한 box 내부에 포함하는 정상 구성과 구분 |
| 취소 또는 disk 부족 중간 파일 | partial 격리, 완료 manifest 미발행 |
| bottom layer가 두 번 미러됨 | independent roundtrip axis/topology 실패 |
| STEP에서 filled via/extra pad height 발생 | physical profile 비교 실패 |
| archive path traversal, 중복 경로 | import 거부, 원본 상태 보존 |
| stale snapshot, 동시 편집 충돌 | E_CONFLICT 또는 과거결과 표시 |

## 7. 후속 구현에서 만들 실제 예제

실제 solver fixture에는 완전한 stackup, 재질, ground, port, boundary, excitation, mesh, 종료, normalization, 프로젝트 source를 포함한다. 입력과 독립 기대 근거가 완전한 참조 계산 사례의 정규화/전력/방사/수렴을 먼저 검증한 뒤, 물성이 완비된 단일포트 IFA를 첫 제품 검증 사례로 진행한다. 원호 단일포트도 R1에서 별도로 검증하며 IFA 합격으로 대체하지 않는다. 최초 IFA의 채택된 초기 기준은 아래 절을 단일 상세 원본으로 사용하며, 실제 물성과 제작/측정 세부는 후속 확정한다. G031과 geometry-only JSON은 기하 전용이며 hidden default를 추가해 가짜 verified RF fixture로 승격하지 않는다. 실제 실행 후 native 파일과 결과, 수렴 보고서를 별도 version으로 저장한다.

R0 Linux native/headless worker의 기본 계산 사례와 R1 Windows 11 x64 wxMSW/local WSL2의 GUI 통합 사례는 같은 의미 입력을 쓰더라도 별도 실행 증거를 남긴다. R1에서는 물성/급전/환경, 전력/방사 검증, 실제 2D/STEP/CAM, 기본 측정/스윕을 연결한다. Linux wxGTK GUI는 출시 버전 미정의 후속 수용 사례이며 자동으로 R2에 배정하지 않는다.

<a id="ifa-initial-baseline"></a>

### 7.1. 최초 IFA 검증 보드의 채택된 초기 기준

사용자는 아래 조건을 최초 검증용 보드의 초기 기준으로 채택했다. 이는 독자적인 수동 단일포트 평면 IFA coupon의 설계 입력이며 제조 도면, 물성 완비 모델, 계산/측정 합격 또는 제품의 고정 기본값이 아니다. 사용자가 입력을 바꾸면 해당 revision의 조건과 근거를 보존한다.

| 항목 | 채택된 초기 기준과 남은 조건 |
| --- | --- |
| 목표 대역과 초기 주파수 | 목표 대역 2.400~2.4835 GHz, 치수 탐색의 design seed 2.45 GHz, 초기 해석/측정 sweep 2~3 GHz. 대역 양끝 2.400/2.4835 GHz를 실제 평가점에 포함하고 정확한 frequency grid와 추가 세분화는 후속 확정 |
| 형식과 전체 외곽 | RFIC, 배터리, 케이스가 없는 수동 단일포트 평면 IFA. 전체 보드 W=40 mm, L=60 mm. 방사 가지 길이/폭, short/feed 위치와 간격 등 실제 안테나 도형은 후속 설계 |
| 안테나 영역 | 상단 가장자리의 폭 40 mm x 깊이 10 mm. 전층 copper keepout이며 IFA 방사체와 명시적으로 설계한 feed/short 전이만 예외. 방사 가지 아래 ground, 무관한 copper와 부품을 자동 배치하지 않음 |
| 접지 영역 | 나머지 40 mm x 50 mm는 ground envelope. 이 사각형을 모든 층의 완전한 접지 polygon으로 간주하지 않으며 실제 polygon, 급전 주변 clearance, via와 접속 구조는 후속 확정 |
| 적층과 동박 | 2층 FR4, finished board thickness 1.0 mm와 각 면 finished copper 35 um를 초기 제작 목표로 채택. 완성 보드 두께를 dielectric core 두께로 대입하지 않으며 제조사의 두께 정의, 공차와 실제 core/동박/도금/마스크 적층은 후속 확정 |
| 재료와 표면 | soldermask를 모델에 포함하고 안테나 영역에는 silkscreen을 두지 않음. FR4의 정확한 grade/construction, 주파수별 Dk/Df, core 두께, mask 재료/두께/물성, 도체 conductivity/거칠기 및 제작 공차는 미정 |
| 급전과 선로 | 안테나 반대쪽 보드 가장자리의 SMA로 실수 기준 임피던스 50 ohm인 single-ended port를 구성. feed line의 50 ohm 목표 선폭은 확정된 실제 stackup과 주변 ground 구조에서 산출하며 임의 고정 선폭을 사용하지 않음. SMA footprint/launch, 경로와 접지 연결은 후속 확정 |
| 비교 기준면 | 주 비교 기준면은 SMA mating/calibration plane이며 그 뒤의 launch와 feed line을 해석/측정 비교에 포함. antenna-feed plane 결과는 검증된 de-embedding이 있을 때 별도로 제공하며 두 기준면의 결과를 섞지 않음. R1 기본 비교는 SMA 기준면을 사용하고 고급 보정 기능의 R2 범위를 앞당기지 않음 |
| 정합 자리 | 안테나 급전 근처에 pi 정합 pad를 두고 초기 series는 0 ohm, 두 shunt는 DNP. pad, 배선, 실장된 0 ohm 소자와 미실장 pad의 기생 효과를 포함하며 소자/package와 정확한 배치는 후속 확정 |
| 초기 측정 설정과 수량 | VNA source power 0 dBm을 초기 설정으로 채택하고 동일 설계 보드 3장을 초기 계획으로 사용. 이는 antenna accepted power=1 mW 보장이나 제조 수율의 통계적 증거가 아님. 보드별 식별자와 실제 제작 편차를 기록 |
| 안테나 정합 목표 | 주 비교 기준면에서 목표 대역 전체의 S11_dB<=-10 dB를 초기 설계 목표로 사용. solver 정확도, 수렴, radiation efficiency 또는 realized gain 합격 기준으로 대체하지 않음 |

위 보드/영역 치수는 사용자가 채택한 이 프로젝트의 초기 기준이다. [TI SWRU120D](https://www.ti.com/lit/an/swru120d/swru120d.pdf)의 25.7 mm x 7.5 mm는 ground를 제외한 안테나 영역이고, 원문의 측정 보드는 1 mm FR4 조건이다. 원문 형상은 출발 참고로만 사용한다. 이 coupon은 TI 참조 보드의 재현본이 아니며 원문의 정합/방사 성능이나 측정 결과를 승계하지 않는다. 최종 IFA 치수와 접지/급전 형상은 이 보드와 실제 적층에 대해 별도 설계하고 검증한다.

### 7.2. 미정 조건, 사용자 편집과 검증 승격

정확한 재료 물성 및 제작 도면 외에 측정 장비, calibration 방법과 유효 범위, frequency grid/IFBW, cable와 jig 배치, 환경, 반복성/오차 및 불확도, 방사/효율 측정 방법은 미정이다. 기준면을 확정하고 측정 조건과 결과 비교 기준, 불확도 산정 방법과 합격 판정 규칙을 해당 측정 전에 동결한다. 실제 반복성 등 측정에서 얻는 수치 근거는 합격 판정 전에 확정하며 결과를 보고 판정 규칙을 유리하게 바꾸지 않는다. 유한 주파수 점의 표본만으로 점 사이를 포함한 전 대역 합격을 자동 선언하지 않는다. VNA 정합 측정만으로 절대 방사 성능을 검증했다고 표시하지 않는다.

이 기준은 편집 가능한 프로젝트 입력이다. unknown 물성을 가진 상태에서도 geometry를 편집/저장할 수 있다. 필수 물리 항목을 모두 명시적인 가정으로 채운 완전한 모델은 탐색용 계산 대상으로 삼을 수 있으나 가정과 적용 범위를 표시하며 실물 검증 완료로 승격하지 않는다. 필수 물성, 급전 또는 수치조건이 비어 있으면 해당 계산 계획을 차단하고 누락값을 자동 보완하지 않는다. simulated/converged는 해당 가정/물성 snapshot의 실행/수렴 증거에 연결하고, measured는 실제 제작 상태와 측정 조건이 연결된 증거에만 부여한다. 각 상태는 독립적으로 기록한다.

실제 물성과 제작/측정 조건의 확정 시점은 [25번 미결 항목 처리 기준](25_RFAD_문서_검토와_승인.md#remaining-decision-policy)을 따른다. 지금 미정인 실물 값을 데이터/GUI 구현 전체의 선행조건으로 두지 않으며, 해당 해석은 완전한 명시적 입력을 요구하고 실제 제작/측정 비교 전에는 보드와 측정 조건을 고정한다.

최초 IFA 기준을 포함한 3.4 전체 문서 기준선은 사용자 승인 완료이며 개발 착수와 물리 검증은 별도로 남는다. 제품 구현, 설치, prototype/solver 실행 및 제작/측정은 수행하지 않았으며 별도 착수 지시와 해당 단계의 준비 조건을 필요로 한다.

## 8. 출력 중 변경과 취소의 합성 시나리오

revision A의 snapshot에서 STEP/도면/manifest 패키지를 생성하는 동안 사용자가 revision B를 편집한다. A의 출력은 A의 경로/metadata에 남기고 현재 B의 결과로 표시하지 않는다. 임시 파일 쓰기, reader 검수, manifest 발행의 각 경계에서 취소/디스크 부족/crash를 주입한다. 최종 artifact가 생긴 뒤 늦은 취소가 도착한 경우에도 실제 완료와 취소 상태가 한 번만 확정되어야 한다.

검수 대상은 마지막 정상 저장본 보존, partial 파일의 격리, 작업/프로세스 종료 확인, 재개방 복구, 중복 발행 방지다. 같은 파일시스템의 원자적 rename과 다른 볼륨 복사는 구분한다. VT-018/019의 AC subcase로 연결하며 수행하지 않은 상황은 미실행으로 둔다.

## 9. wxWidgets 통합 및 성능 검증 시나리오

C++ wxWidgets가 사용자 지시로 확정되었으며 현재 상태는 `selected_pending_validation`이다. 통합 prototype은 고정 geometry/result fixture, renderer 품질, worker 경로와 완료 기능으로 검수한다. 빈 창, 일반 2D/표 scroll/100,000 triangle의 일반 3D 편집, 1,000,000 triangle의 대형 장면, 큰 결과 탐색, 반복 프로젝트 열기/닫기, solver/export 동작 중 취소와 worker 재시작을 포함한다. Avalonia 비교 구현은 현재 범위에 포함하지 않고 Qt는 제외한다. 입력 acknowledgment와 실제 화면 반영 및 작업 완료를 구분한다.

전체 process tree의 working set/private commit, GPU memory, peak/steady state와 반복 종료 후 회수, cold/warm startup, p95/p99 입력 지연과 frame time을 [GUI 선정과 성능 설계](24_RFAD_GUI_선정과_성능_설계.md)의 단일 계약으로 기록한다. 일반 편집 60 fps/대형 장면 30 fps를 유지하고 F1/F2의 frame time p95를 PERF-006으로 검수한다. PERF-001~010과 기준 host/fixture는 초기 목표로 채택되었으며 정확한 CPU/GPU와 실행 manifest는 미정이고 모든 측정은 미실행 상태다. 채택된 목표를 최소사양 보장으로 해석하지 않는다. idle 상태에서는 60 fps 강제 redraw loop를 돌리지 않는다. GUI-SPIKE-001..007 ID와 VT-018/028/029의 연결은 wxWidgets 통합/성능 검증에 유지하며 예상 메모리나 기술 명칭을 실측 결과로 표시하지 않는다.

R1 Windows 11 x64 wxMSW/local WSL2 내부 검증용 배포에서 유료 GUI 부품을 필수로 요구하지 않는 기본 구성을 검수한다. 이 방침은 유료 부품의 모든 사용 금지나 제품 무료 배포를 뜻하지 않는다. 외부 공개/상용 배포/소스 공개 방침은 후속 결정이다. 3.4 전체 설계 기준선은 승인 완료이며 prototype 실행은 별도 개발 착수 지시 이후에 수행한다.
