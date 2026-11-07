# RFAD 14 - 검증과 사용자 수용시험

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안
역할: 구현 이후 수행할 시험 명세, A/B 인수 시나리오 대응, 검증 단계와 출시에 필요한 증거
상태: **design baseline with open verification gates** - 구현, EM 실행, 실측 합격을 뜻하지 않는다.

관련 문서: [요구사항](03_RFAD_사용자_요구사항.md), [수식](09_RFAD_수식과_물리_모델.md), [파이프라인](10_RFAD_연산_파이프라인.md), [추적표](17_RFAD_요구사항_추적표.md), [GUI 성능 계약](24_RFAD_GUI_선정과_성능_설계.md).

## 1. 상태와 검증의 의미

이 문서는 **시험 명세**이다. VT-001~030 전체의 제품 수용 합격은 아직 없다. 현재 저장소에는 RFAD 제품의 실행 증거와 시험 결과가 없으며, 과거 문서의 R0 상태나 테스트 개수를 현재 합격으로 인용하지 않는다. A의 137개 요구와 신규 AUG 4개, A의 인수 시나리오 12개와 B의 18개를 검사 항목에 연결했으며, 이는 구현 완료, 합격, full-wave 정확도 검증을 뜻하지 않는다. 각 요구의 실제 assertion과 적용 단계는 AC ID별 evidence로 보존해야 한다. 현재 없는 파생 registry의 requirement_checks를 실행 증거로 간주하지 않는다. 문서의 모든 현재 상태는 `specified_not_executed`이다.

### 1.0 요구별 assertion과 suite 판정

[요구사항 추적표](17_RFAD_요구사항_추적표.md)의 AC ID별 검수대상, 적용 단계, 주 VT와 필수 증거를 시험의 최소 단위로 사용한다. 고유 subcase는 `VT-nnn/AC-ID.Rn` 형식이며 하나의 AC에 여러 단계가 연결되면 단계별로 독립 실행하고 원래 요구의 완료 판정에는 해당 범위의 결과를 AND로 결합한다. 같은 suite의 다른 AC 또는 R0 최소 fixture가 통과해도 미실행 AC를 통과로 전이하지 않는다.

각 assertion은 입력/fixture 버전, 요구와 AC ID, 적용 capability, 독립 expected 근거, actual, 단위, 비교식, 허용오차 profile 버전, 실행 시각, 도구 버전, 증거 경로와 hash, 상태를 가진다. 상태는 `specified_not_executed`, `passed`, `failed`, `blocked`, `not_applicable`로 구분한다. `not_applicable`에는 해당 릴리스의 명시적 범위와 근거를 기록하며 기능 합격 수에 포함하지 않는다. 필수 assertion이 미실행/차단/실패이면 suite 전체를 passed로 표시하지 않는다. 범위를 줄여 출시하는 경우 새로운 범위 선언과 제외 이유가 필요하며 원 요구의 전체 완료 상태는 유지하지 않는다.

같은 suite에 R1과 R2/R3의 subcase가 섞여 있을 수 있다. R1에서는 약속된 실제 기능과 미래 기능의 unsupported/unknown 표시를 검사한다. **미지원 표시 검사를 통과한 사실은 R2/R3 실제 기능의 수용조건을 충족하지 않는다.** 선행 suite도 동일 release/capability의 subcase에 한정해 적용한다.

### 1.1 독립된 검증 층

| 층 | 질문 | 필요한 증거 | 여기서 증명되지 않는 것 |
|---|---|---|---|
| 자료, 출처 | 이 값이 어느 문서/개정/조건에서 왔는가? | 원문 hash, page/member, 단위, 충돌 상태 | 현재 제품에서의 성능 |
| 순수 산술 | 정의식, 부호, 단위, 행렬순서가 맞는가? | 독립 expected vector, domain error | Maxwell 해의 정확도 |
| CAD/교환 | 같은 물리 형상을 출력, 재입력했는가? | 독립 reader, 거리, 면적, 연결, 단위 | 실제 제조 공정 정밀도 |
| Adapter | native와 domain 의미가 같은가? | 채널별 power/phase/normalization fixture | 모든 형상/재료의 accuracy |
| 수치 수렴 | 선택한 수치 설정에서 값이 안정되는가? | mesh/경계/시간 series | 모델이 실물을 잘 나타내는지 |
| 물리 일관성 | 전력, 손실, 파, 조건이 모순되지 않는가? | power ledger, 수동성, known cases | 유한대역 밖 전역 인과성 증명 |
| 독립 EM/실측 | 실제 현상을 허용오차 안에서 예측하는가? | 분석해/다른 solver/교정 실측, 불확실성 | 모든 제품/환경의 성능 보증 |
| 제품 승인 | 특정 목표와 시험/제조 조건을 충족했는가? | 승인된 target, 외부 시험, 제조/측정 증거 | 자동 KC/FCC/SAR 인증 |

한 층의 합격이 위의 모든 층을 자동 통과시키지 않는다. 구조화된 상태는 [RFAD 04](04_RFAD_시스템_명세.md), 근거 승격 규칙은 [RFAD 20](20_RFAD_참고_자료_통합.md)에 따른다.

## 2. fixture와 oracle 원칙

Expected 값은 production 구현의 출력을 그대로 저장해 만든 것이어서는 안 된다. 기하, 산술은 독립 analytic/manual 계산, network는 독립 MNA/SPICE 또는 다른 검증 구현, EM은 공식 benchmark, 분석해, 완전한 제조사 reference, 다른 solver, 실측 중 목적에 맞는 oracle를 정한다. 서로 다른 oracle 등급을 같은 이름으로 취급하지 않는다.

Fixture manifest에는 최소한 다음을 넣는다.

- fixture ID/version, 목적, 요구/VT/EQ IDs, source, 원본 hash, 권리, 입력/expected/적용 band.
- physical snapshot, material, port, wave, reference plane, coordinates, units, time/amplitude convention.
- solver/adapter/CAD/network library, OS/CPU 버전, 실행 명령과 비밀값을 제외한 환경, random seed.
- 전제 조건, 단계, negative cases, 허용오차, 그 기준의 출처/합의 상태.
- generated files/raw/derived results/logs/validation evidence 및 비교 방법.
- 실제 실행 status, 실행 시각, reviewer, unresolved diagnostics. 미실행은 빈 결과 또는 `specified_not_executed`로 둔다.

코드 변경 후 반복할 회귀시험은 의미 있는 남은 위험과 required gate에 맞춰 선택한다. 단순 문구 편집마다 EM을 재실행하지 않는다. native 버전, normalization, mesh/material mapping이 바뀌면 관련 adapter/physics fixture를 다시 실행한다.

<a id="threshold-profiles"></a>

## 3. 수치 허용값을 세 종류로 분리

### 3.1 정의로 정해지는 합성 fixture

다음은 원자료 또는 정의식에서 정해진 입력/기대값이며 RF 성능 합격선이 아니다.

| fixture | 기대값 | 근거, 제한 |
|---|---|---|
| 50 mm calibration line | 0.05 m | B::AT06; 파일 길이와 printer scale은 별도 |
| 35 um + 1.530 mm + 35 um | 1.600 mm 총 적층 | B::STP-004; 실제 측정 PCB가 아닌 합성 fixture |
| Pinc=1 W, Pref=.25 W, Prad=.60 W | Pacc=.75 W, etarad=.80, etatotal=.60 | B::VAL-002, section 8.4; 단일포트 정의 fixture |
| complex Z0=50+j25 ohm, ZL=50-j25 ohm | power Gamma=0, voltage Gamma=-j.5 | EQ-011의 정의 비교 |
| pure-delay H(f)=exp(-j*2*pi*f*5 ns) | taug=5 ns | 시간 규약 검사; UWB 실물 calibration 아님 |
| L1=1 uH, L2=4 uH, M=.5 uH | k=.25 | 수동 coupled-inductor 산술 |
| IID sample 90/100 pass, 95% Wilson | 약 [.8256343385,.9447708629] | EQ-036, [NIST Wilson 설명](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/propconf.htm) |

G031의 좌표는 원본 Gerber의 정밀도와 residual을 가진다. 계산된 r, theta, L의 소수 자릿수를 그대로 제조 정밀도로 해석하지 않는다. 전체 ground, stackup, 환경이 미완비이므로 G031은 원호 형상 재현 fixture이며 방사 성능 golden benchmark가 아니다.

### 3.2 B 문서의 잠정 benchmark profile

아래 값은 B section 8.3의 **초기 제안**을 보존한 것이다. RFAD는 삭제하지도 보편 필수치로 승격하지도 않는다. R0에서 구체적인 fixture, 비교 domain, hardware, 목표에 맞는 profile을 승인해야 실제 pass/fail에 사용한다.

| profile | 후보 값 | 의미와 미확정 사항 |
|---|---|---|
| BP-CAD-CANDIDATE | 길이/위치 오차 <=0.001 mm | 선택 synthetic CAD fixture의 왕복 수치오차. source precision, 제조공차, EM 오차와 별개 |
| BP-CONVERGENCE-CANDIDATE | mesh >=3단계 | 단계 수 자체는 수렴 증명이 아님 |
| 같은 profile | 마지막 공진 변화 <=1% | 공진 정의/branch, 분모, band가 동일해야 함 |
| 같은 profile | max complex S 변화 <=0.02 | linear complex 차이. dB 차이 또는 \|S\| 차이로 대체하지 않음 |
| 같은 profile | gain 변화 <=0.5 dB | gain/realized gain 종류, angle/f grid, normalization을 고정 |
| 같은 profile | 효율 변화 <=2 percentage points | 절대 0.02. 상대 2%와 다름 |
| BP-UI-CANDIDATE | 원문 B의 200 ms 후보를 이력으로 보존 | 현재 측정 항목과 설계 예산은 [GUI 성능 계약](24_RFAD_GUI_선정과_성능_설계.md)에서 단일 관리. 실행 완료시간과 구분 |

CAD의 tauCAD, 2D export의 tau2D, 제조 공정의 taufab는 별도 변수이다. gain/efficiency/field의 물리 정확도 기준은 EM, 측정 uncertainty와 target에서 정한다. 부동소수점 산술의 절대/상대오차 기준은 그보다 하위의 계산 검사이며 동일 숫자를 재사용하지 않는다. 식 레지스트리의 산술 tolerance도 fixture별 조정이 가능한 설계 제안이다.

### 3.3 프로젝트, 측정 목표

S11 threshold, band coverage, gain/efficiency/axial-ratio/ECC mask, range, delay, Q, coupling 목표는 사용자가 선택한 제품 목적과 근거를 갖는다. 모든 BLE=-10 dB, 모든 UWB=특정 delay ripple처럼 프로토콜 이름으로 임의 고정하지 않는다. 제조/측정 uncertainty를 포함한 합격 판정은 profile version과 decision rule을 보존한다. 참조: [JCGM 100:2008 section 5.2/section 7](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf).

## 4. 기존 인수 시나리오의 통합 매핑

A/B ID의 이름 충돌을 막기 위해 A::AT-001와 B::AT01을 구분한다. 하나의 기존 시나리오가 여러 최종 suite로 나뉜 경우 모두 실행해야 해당 범위의 원 수용조건을 충족한다.

| 기존 ID | 최종 VT |
|---|---|
| A::AT-001 | [VT-001](#VT-001) |
| A::AT-002 | [VT-002](#VT-002) |
| A::AT-003 | [VT-003](#VT-003) |
| A::AT-004 | [VT-004](#VT-004) |
| A::AT-005 | [VT-007](#VT-007), [VT-008](#VT-008), [VT-009](#VT-009) |
| A::AT-006 | [VT-010](#VT-010) |
| A::AT-007 | [VT-011](#VT-011) |
| A::AT-008 | [VT-012](#VT-012) |
| A::AT-009 | [VT-013](#VT-013) |
| A::AT-010 | [VT-014](#VT-014) |
| A::AT-011 | [VT-015](#VT-015) |
| A::AT-012 | [VT-016](#VT-016) |
| B::AT01 | [VT-005](#VT-005) |
| B::AT02 | [VT-002](#VT-002) |
| B::AT03 | [VT-006](#VT-006) |
| B::AT04 | [VT-004](#VT-004) |
| B::AT05 | [VT-003](#VT-003) |
| B::AT06 | [VT-007](#VT-007) |
| B::AT07 | [VT-008](#VT-008) |
| B::AT08 | [VT-009](#VT-009) |
| B::AT09 | [VT-010](#VT-010), [VT-012](#VT-012) |
| B::AT10 | [VT-011](#VT-011) |
| B::AT11 | [VT-017](#VT-017) |
| B::AT12 | [VT-016](#VT-016) |
| B::AT13 | [VT-010](#VT-010) |
| B::AT14 | [VT-015](#VT-015) |
| B::AT15 | [VT-013](#VT-013) |
| B::AT16 | [VT-018](#VT-018) |
| B::AT17 | [VT-012](#VT-012) |
| B::AT18 | [VT-019](#VT-019) |

AUG-001 -> [VT-024](#VT-024), AUG-002 -> [VT-023](#VT-023), AUG-003 -> [VT-025](#VT-025), AUG-004 -> [VT-026](#VT-026). 전체 요구별 매핑은 [RFAD 17](17_RFAD_요구사항_추적표.md)에 있다.

## 5. 최종 시험 suite

<a id="VT-001"></a>

### VT-001 - G031 원본 CAD 재현

**단계:** R0 최소 원호 fixture / R1 전체 수용. **현재 상태:** 시험 명세, 미실행.

**설정:** G031 원본 ZIP와 멤버 hash, Gerber 원호 좌표, 내장 PDF를 읽기 전용 보관; 좌표 양자화 0.00254 mm와 호 끝점 반경 잔차를 원자료 품질로 기록.

**절차**

1. G031의 원호, 선폭, 급전 stub, 보드 본체 기준 원호를 독립 Gerber parser로 읽는다.
2. 동일 원점/단위로 의미 모델을 생성하고 원본 overlay를 만든다.
3. 완전한 ground, stackup, 환경을 비워 두고 초기 상태와 solve 가능 여부를 검사한다.

**합격 판정**

- r=9.119930042 mm, sweep=112.534633986 deg, width=1.27 mm, Larc=17.912453553 mm를 소스 양자화와 선언된 재현 정책에 맞춰 비교한다.
- 몸체 기준 D=19.999016107 mm를 탭을 포함한 전체 외곽 지름으로 잘못 표시하지 않는다.
- 1.91516 mm stub를 겹침 보정 없이 원호 길이에 더해 전기 길이로 만들지 않는다.
- 문헌/CAD 형상 재현으로 상태를 제한하며 공진, 효율 실측 검증으로 승격하지 않는다.

**실패 유도:** ZIP 멤버 교체, 원호 방향 반전, 단위 누락을 검출한다.; 필수 포트/재질/GND가 없는 모델에 검증 완료 안테나 표시를 금지한다..

**필수 증거:** G031 원본 provenance, 원호 좌표 residual, overlay, evidence-state log.

**요구:** `DAT-001`, `PRJ-009`, `CAD-002`, `PHY-010`, `PHY-011`, `PHY-012`, `PHY-068`, `OUT-006`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-002](09_RFAD_수식과_물리_모델.md#EQ-002), [EQ-004](09_RFAD_수식과_물리_모델.md#EQ-004), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-009`, `API-010`, `API-006`, `API-008`, `API-027`.

**연결 gate:** [GAP-006](01_RFAD_설계_결정과_범위.md#GAP-006).

<a id="VT-002"></a>

### VT-002 - 원호, 보드 지름과 제약 갱신

**단계:** R1. **현재 상태:** 시험 명세, 미실행.

**설정:** 원호 지름, 반경, 선폭, 외곽 이격, 급전 위치의 constraint fixture; 반경 고정/호각 고정/길이 고정의 서로 다른 variant.

**절차**

1. 지름을 바꾸고 어떤 제약을 고정했는지 기록한다.
2. 원호 방향과 0 deg 통과, 큰 sweep, 열린 끝, taper/선폭 offset을 검사한다.
3. 2D, 3D, EM 파생 모델을 같은 snapshot에서 재생성한다.

**합격 판정**

- 각 variant의 L=r|theta|와 외곽 이격이 독립 기하 oracle에 일치한다.
- 동시에 만족할 수 없는 지름, 길이, 끝점 제약은 식과 객체 UUID를 제시하며 실패한다.
- 지름 변경만으로 주파수 유지나 공진 정확성을 보증하지 않는다.
- analytic arc 지원 export에서는 arc가 유지되고 tessellation export에서는 실제 chord error, 선분 수가 기록된다.

**실패 유도:** r<=0, width>=2r의 단순 annulus 적용, self-intersection, 접촉, 최소 간격 위반을 검사한다..

**필수 증거:** constraint solution, variant diff, 3-way revision manifest, curve tolerance report.

**요구:** `PRJ-007`, `CAD-001`, `CAD-002`, `CAD-003`, `CAD-005`, `CAD-006`, `PHY-005`, `PHY-010`, `PHY-011`, `PHY-015`, `PHY-022`, `JOB-006`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-002](09_RFAD_수식과_물리_모델.md#EQ-002), [EQ-003](09_RFAD_수식과_물리_모델.md#EQ-003), [EQ-004](09_RFAD_수식과_물리_모델.md#EQ-004), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-003`, `API-005`, `API-006`, `API-008`, `API-025`.

**수치 기준:** `BP-CAD-CANDIDATE`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-003"></a>

### VT-003 - IFA topology, 유한 GND, keepout

**단계:** R1. **현재 상태:** 시험 명세, 미실행.

**설정:** IFA 정상 fixture와 short 제거/단선/층별 keepout 위반 fixture; 원호 모노폴, 폐환 loop, ground slot의 동일 시각 형상 대비 사례.

**절차**

1. 전기 연결 graph와 실제 도체 union을 비교한다.
2. 급전, short, 비아를 변경하고 유형과 재검증 상태를 확인한다.
3. ground slot, stitching via, 여러 층 keepout, 제조 규칙을 검사한다.

**합격 판정**

- 도형의 외관이 아니라 연결 관계로 열린 원호/IFA/loop/slot을 구별한다.
- short/feed/ground 역할과 층별 연결이 보존된다.
- DRC 위반이 좌표, 객체, 규칙 근거로 보고되며 불법 geometry를 최적안으로 선택하지 않는다.

**실패 유도:** short 삭제 후 검증된 IFA 유지; 접지 plane에 떠 있는 비아; 음수 gap, 국부 self-contact.

**필수 증거:** topology truth table, DRC overlay, net/layer mapping, blocked-run reasons.

**요구:** `CAD-004`, `CAD-009`, `PHY-012`, `PHY-013`, `PHY-014`, `PHY-015`, `PHY-022`, `JOB-001`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-002](09_RFAD_수식과_물리_모델.md#EQ-002), [EQ-004](09_RFAD_수식과_물리_모델.md#EQ-004). **API:** `API-006`, `API-008`, `API-011`.

<a id="VT-004"></a>

### VT-004 - 재료 조건, 분산, 출처, stale

**단계:** R1; 분산, 텐서 모델별 R2 capability gate. **현재 상태:** 시험 명세, 미실행.

**설정:** construction별 Dk/Df 원자료, process/design Dk, 결측 Df; 단축 anisotropy 회전 fixture, passive Debye 곡선과 의도적 active/noncausal fit; 서로 다른 재료, 두께, 마스크, 접착층 variant.

**절차**

1. 같은 조건의 Dk/Df 쌍을 고르고 범위 내/외 f를 요청한다.
2. 상수 kappa 모델과 수동 분산 fit을 만들고 실제 backend 입력을 덤프한다.
3. 재질, 좌표축, 두께를 바꿔 raw EM 의존성과 오래된 결과 표시를 검사한다.

**합격 판정**

- 결측 Df를 0으로 채우지 않고 제품/시험법/방향/f/T가 다른 값을 자동 결합하지 않는다.
- kappa 고정 시 tan_delta가 기준 f에서만 일치함을 표시한다.
- 텐서 변환과 손실 PSD 조건, model fit residual, 유효대역, 가정이 남는다.
- 미지원 분산/거칠기/복합층은 조용히 PEC 또는 상수 epsilon로 대체되지 않는다.

**실패 유도:** 손실 중복 계산; epsilon 부호 반전; 범위 밖 extrapolation의 measured 표기; 단위만 같은 Sq를 roughness-model parameter로 대입.

**필수 증거:** material selection manifest, fit residual, solver material dump, stale dependency diff.

**요구:** `PHY-023`, `PHY-024`, `PHY-025`, `PHY-027`, `PHY-028`, `PHY-030`, `PHY-032`, `PHY-033`, `PHY-034`, `PHY-036`, `PHY-051`, `DAT-004`. **식:** [EQ-005](09_RFAD_수식과_물리_모델.md#EQ-005), [EQ-006](09_RFAD_수식과_물리_모델.md#EQ-006), [EQ-007](09_RFAD_수식과_물리_모델.md#EQ-007), [EQ-008](09_RFAD_수식과_물리_모델.md#EQ-008), [EQ-009](09_RFAD_수식과_물리_모델.md#EQ-009). **API:** `API-006`, `API-011`, `API-012`, `API-016`.

**연결 gate:** [GAP-004](01_RFAD_설계_결정과_범위.md#GAP-004).

<a id="VT-005"></a>

### VT-005 - SI, 좌표, 포트 단위 왕복

**단계:** R0/R1. **현재 상태:** 시험 명세, 미실행.

**설정:** 같은 형상의 m/mm/um와 rad/deg 입력; 비대칭 fiducial과 top/bottom 관측 fixture; 명시적 파라미터 수식 DAG.

**절차**

1. 단위를 바꿔 입력하고 저장, 재개방, snapshot을 비교한다.
2. bottom view mirror와 실제 board rotation을 각각 적용한다.
3. 차원 불일치와 순환 수식을 입력한다.

**합격 판정**

- SI canonical 값, rad 각도, entity UUID, layer z와 전기 연결이 변하지 않는다.
- display-unit 변경으로 raw EM hash가 바뀌지 않는다.
- 차원 불일치, 순환 참조는 실행 전에 진단된다.

**실패 유도:** inch 해석 오류; 180 deg 반사/회전 혼동; 동박 thickness를 mm로 오입력.

**필수 증거:** canonical JSON diff, transform matrices, unit-validation report.

**요구:** `PRJ-005`, `PHY-068`, `CAD-001`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-002`, `API-003`, `API-004`, `API-005`.

<a id="VT-006"></a>

### VT-006 - 18/35/70um 동박, 적층, 손실

**단계:** R0/R1; 고급 도체 모델 R2. **현재 상태:** 시험 명세, 미실행.

**설정:** 동일 stackup에 copper 18/35/70 um variant; PEC/finite sigma/검증된 conducting sheet 각각의 model declaration; 35 um+1.530 mm+35 um의 합성 적층 fixture.

**절차**

1. 실제 3D copper 두께와 stackup z를 계산한다.
2. skin depth와 선택된 도체 모델을 비교해 적용 이유를 남긴다.
3. 동일 물리 모델을 지원 backend로 풀고 conductor loss ledger를 검사한다.

**합격 판정**

- 합성 stackup 총 두께는 1.600 mm이다.
- 18/35/70 um가 STEP/physical model에 각각 정확히 반영된다.
- PEC와 finite sigma의 손실 포함 여부가 명시되며 RF 손실이 반드시 두께에 비례한다고 가정하지 않는다.
- sheet/volume/PEC 차이와 검증 범위를 출력하며 미지원 모델은 차단된다.

**실패 유도:** thickness=0을 우연히 PEC로 보내기; sheet를 3D primitive에 적용; 높은 f에서 DC Rsheet를 RF 정확값으로 표기.

**필수 증거:** layer z and volume checks, native material files, power ledger, model comparison.

**요구:** `PHY-029`, `PHY-031`, `PHY-032`, `PHY-051`, `OUT-004`. **식:** [EQ-006](09_RFAD_수식과_물리_모델.md#EQ-006), [EQ-007](09_RFAD_수식과_물리_모델.md#EQ-007), [EQ-008](09_RFAD_수식과_물리_모델.md#EQ-008), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-008`, `API-011`, `API-012`, `API-024`, `API-025`.

**연결 gate:** [GAP-004](01_RFAD_설계_결정과_범위.md#GAP-004).

**수치 기준:** `BP-EXACT-FIXTURES`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-007"></a>

### VT-007 - 2D 치수, 50mm 검정선

**단계:** R1. **현재 상태:** 시험 명세, 미실행.

**설정:** analytic arc, 홀이 포함된 층별 2D 도면; 실제 geometry length 50 mm인 calibration line; PDF/SVG/DXF independent reader.

**절차**

1. top/bottom/stackup 도면을 생성한다.
2. 파일 좌표와 단위를 독립 reader로 비교한다.
3. 실제 프린터 출력은 별도 print-scale fixture로 검사한다.

**합격 판정**

- 50 mm calibration line은 파일 단위 해석 후 0.05 m이다.
- 개정, 단위, 축척, 공차, 미러 방향, 층 이름과 누락 의미가 명확하다.
- 프린터 페이지 맞춤으로 바뀐 길이를 CAD 오류와 혼동하지 않는다.

**실패 유도:** mm header에 inch geometry; arc chord error 누락; bottom 도면 중복 mirror.

**필수 증거:** 2D files, independent-reader measurements, export preview, round-trip diff.

**요구:** `CAD-005`, `PHY-068`, `OUT-001`, `OUT-006`, `OUT-009`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-002](09_RFAD_수식과_물리_모델.md#EQ-002), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-023`, `API-024`, `API-025`.

**수치 기준:** `BP-CAD-CANDIDATE`, `BP-EXACT-FIXTURES`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-008"></a>

### VT-008 - STEP B-rep, 층 높이, sidecar

**단계:** R0 thin copper/via/slot 최소 fixture / R1 확장; flex R3. **현재 상태:** 시험 명세, 미실행.

**설정:** 기판, 동박, 비아, connector 분리 고체와 STEP sidecar; 원호/slot/through-hole/복수 물성 layer fixture; R3: 평면 flex와 두 굽힘 scenario.

**절차**

1. STEP을 출력하고 writer와 별도 reader에서 reimport한다. reader/kernel 독립성 등급과 수신 CAD/version을 기록한다.
2. solid validity, volume, bounding box, layer z, 객체명, 좌표계를 비교한다.
3. sidecar RF semantics와 STEP geometry hash를 교차 확인한다.
4. R3에 중립면, strain 가정을 고정한 굽힘 scenario의 EM/STEP을 비교한다.

**합격 판정**

- 동박이 단순 edge/surface가 아닌 유효한 실제 두께 B-rep solid로 출력된다.
- 의도하지 않은 fusion/누락/잘못된 z와 port/mesh 정보를 STEP만으로 복구했다는 허위 주장을 검출한다.
- sidecar 없는 STEP은 geometry-only import임을 표시한다.
- 요청 schema와 실제 FILE_SCHEMA, assembly transform, object 대응, 닫힌 B-rep와 국부 gap/배럴 단면을 검사한다. 같은 OCCT 기반 reader끼리의 일치를 kernel 독립성으로 표시하지 않는다.
- KiCad의 평면 mask face나 filled-via 옵션을 실제 마스크 두께 또는 금속 충진 공정의 검증으로 취급하지 않는다. physical profile에 필요한 부피와 재료가 없으면 미지원 또는 실패로 남긴다.
- R3 flex 시험은 제조 평면과 동작 3D의 개정 연결 및 길이/변형 가정을 검증한다.

**실패 유도:** thin copper 누락; STEP단위누락; 허용오차보다 가까운 두 net이 fusion; 평면 원호를 굽힘 flex로 오분류.

**필수 증거:** STEP, sidecar, independent B-rep report, Hausdorff/volume/connectivity diff.

**요구:** `CAD-001`, `CAD-008`, `PHY-021`, `OUT-004`, `OUT-005`, `OUT-006`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-002](09_RFAD_수식과_물리_모델.md#EQ-002), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-008`, `API-023`, `API-024`, `API-025`.

**수치 기준:** `BP-CAD-CANDIDATE`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-009"></a>

### VT-009 - CAM, EDA 도체/넷/드릴 왕복

**단계:** R1; 추가 포맷 R3. **현재 상태:** 시험 명세, 미실행.

**설정:** Gerber, drill, KiCad board/footprint fixture; net, pad, via, zone, outline, stackup 원본; 미지원 확장 format sample.

**절차**

1. 미리보기에서 누락 의미를 확인하고 export한다.
2. 독립 viewer와 EDA에서 읽어 층, drill, net, unit을 비교한다.
3. import한 Gerber에 없는 material/port/net 의미를 사람이 지정하는 절차를 시험한다.

**합격 판정**

- 그림용 graphic을 전기 track으로 위장하지 않는다.
- board와 footprint의 요구 객체 차이가 보존된다.
- 모든 추가 adapter는 지원/누락 객체, 단위, 검증 fixture를 선언한다.
- 미지원 format은 성공으로 저장되지 않는다.

**실패 유도:** net없는 선을 전기연결 완료로 표시; drill tool단위혼동; 미지원 객체 silent drop.

**필수 증거:** EDA/CAM files, independent viewer evidence, layer mapping, semantic loss report.

**요구:** `CAD-010`, `PHY-022`, `OUT-002`, `OUT-003`, `OUT-006`, `OUT-010`. **식:** [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-009`, `API-010`, `API-023`, `API-024`, `API-025`.

<a id="VT-010"></a>

### VT-010 - VNA 기준면, 포트, 보정

**단계:** R1; 복소/modal ports R2. **현재 상태:** 시험 명세, 미실행.

**설정:** 포트 순서, Z0, reference plane이 다른 두 Touchstone와 원시 측정 CSV; known line/fixture, calibration metadata; 선택 장비 adapter의 기록 재생 fixture.

**절차**

1. 원시 파일을 불변 보관하고 문법, 복소 형식, 단위, 포트 수를 검증한다.
2. port reorder/renormalize/plane shift/deembedding을 각각 독립 파생 연산으로 실행한다.
3. 측정 기준면과 simulation plane을 맞추기 전, 후 비교를 만든다.

**합격 판정**

- 정합 회로, IC plane, antenna plane을 구별한다.
- 원시 값은 보존되고 변환식, reference impedance, s_def, calibration/fixture가 추적된다.
- 동일 물리 Z의 renormalization 불변성과 known line의 위상 변환을 확인한다.
- 차동, CPW, complex Z0는 adapter gate 이전에 일반 lumped 50 ohm 포트로 조용히 대체되지 않는다.

**실패 유도:** Z0 미정; 포트 중복, reorder 누락; 측정 f grid 외삽; 노이즈로 ill-conditioned deembedding.

**필수 증거:** raw hashes, calibration/plane manifest, derived Touchstone, transform log.

**요구:** `MEAS-001`, `PHY-039`, `PHY-040`, `PHY-041`, `PHY-043`, `PHY-052`, `PHY-057`, `PHY-079`, `PHY-080`, `PHY-086`. **식:** [EQ-010](09_RFAD_수식과_물리_모델.md#EQ-010), [EQ-011](09_RFAD_수식과_물리_모델.md#EQ-011), [EQ-012](09_RFAD_수식과_물리_모델.md#EQ-012), [EQ-020](09_RFAD_수식과_물리_모델.md#EQ-020), [EQ-028](09_RFAD_수식과_물리_모델.md#EQ-028), [EQ-031](09_RFAD_수식과_물리_모델.md#EQ-031). **API:** `API-009`, `API-010`, `API-017`, `API-022`.

**연결 gate:** [GAP-013](01_RFAD_설계_결정과_범위.md#GAP-013).

**선행:** [VT-020](#VT-020), [VT-021](#VT-021), [VT-022](#VT-022)의 동일 stage/capability subcase.

<a id="VT-011"></a>

### VT-011 - mesh, 경계, 시간 종료 수렴

**단계:** R0/R1. **현재 상태:** 시험 명세, 미실행.

**설정:** 공식 reference fixture와 mesh level series; PML/airbox만 변경한 series와 time/endcriteria만 변경한 series; NF2FF surface 위치/phase center/주파수 metadata.

**절차**

1. 같은 물리 snapshot으로 메시, 경계, 종료 series를 각각 실행한다.
2. 실제 min cells/gradation/time step/time method/resources를 수집한다.
3. 같은 f, port, normalization에서 complex S, resonance branch, eta, G, field를 비교한다.

**합격 판정**

- 수렴 여부가 지표, 기준, 비교 run들과 함께 표시된다.
- mesh 수렴, boundary 수렴, transient termination을 서로 대체하지 않는다.
- 수렴 미확인, resonance branch 미추적, divergence 상태는 명확하다.
- 기록된 native timestep을 사용하며 역사적 Yee식의 OCR값으로 강제 설정하지 않는다.
- NF2FF 면의 완전 포위, 매질, PML, field 저장 주파수 조건을 확인한다.

**실패 유도:** coarse/fine S magnitude만 비교; 공진 사라짐을 zero change로 계산; unsupported PML/media NF2FF; peak gain 관측 grid 불일치.

**필수 증거:** mesh/native solver inputs, logs/resources, convergence tables, boundary/time sensitivity.

**요구:** `PHY-047`, `PHY-048`, `PHY-049`, `PHY-050`, `PHY-053`, `PHY-054`, `JOB-001`, `JOB-002`, `JOB-003`, `JOB-006`, `INT-001`, `INT-002`. **식:** [EQ-015](09_RFAD_수식과_물리_모델.md#EQ-015), [EQ-019](09_RFAD_수식과_물리_모델.md#EQ-019), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037), [EQ-038](09_RFAD_수식과_물리_모델.md#EQ-038). **API:** `API-011`, `API-012`, `API-013`, `API-015`, `API-019`.

**연결 gate:** [GAP-012](01_RFAD_설계_결정과_범위.md#GAP-012).

**선행:** [VT-021](#VT-021), [VT-029](#VT-029)의 동일 stage/capability subcase.

**수치 기준:** `BP-CONVERGENCE-CANDIDATE`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-012"></a>

### VT-012 - 전력, 정합, 효율, 손실 수지

**단계:** R0/R1. **현재 상태:** 시험 명세, 미실행.

**설정:** 1 W incident,0.25 W reflected,0.60 W radiated 합성 fixture; matched absorbing load, PEC antenna, finite-loss antenna; 다중포트 fixture와 orthogonal polarization/AR vectors.

**절차**

1. one-port 전력 및 efficiency를 독립 계산한다.
2. S11이 약 0인 matched loss와 효율 좋은 방사체를 비교한다.
3. 복소 E/H에서 Poynting, Prad, gain을 계산하고 solver-native output과 비교한다.
4. finite sigma/dielectric loss ledger와 다중 여기 ledger를 검사한다.

**합격 판정**

- 합성 fixture는 Pacc=0.75 W,etarad=0.8,etatotal=0.6이다.
- gain/directivity/realized gain의 분모와 plane이 표시된다.
- field export에 amplitude/time convention, units, coords, phase가 포함된다.
- 에너지 residual이나 eta>1을 clipping해 통과시키지 않는다.
- 일부 미계산 대역을 연속대역 성능 충족으로 판정하지 않는다.

**실패 유도:** 모든 native output에 일괄sqrt(2) 적용; S 변환sqrt(2); 다른 포트 출력 전력을 방사로 분류; RMS Poynting에추가1/2.

**필수 증거:** power ledger, normalization proof, field/metrics files, spectral masks.

**요구:** `PHY-027`, `PHY-029`, `PHY-044`, `PHY-054`, `PHY-057`, `PHY-058`, `PHY-059`, `PHY-060`, `PHY-061`, `OUT-007`. **식:** [EQ-008](09_RFAD_수식과_물리_모델.md#EQ-008), [EQ-010](09_RFAD_수식과_물리_모델.md#EQ-010), [EQ-013](09_RFAD_수식과_물리_모델.md#EQ-013), [EQ-014](09_RFAD_수식과_물리_모델.md#EQ-014), [EQ-015](09_RFAD_수식과_물리_모델.md#EQ-015), [EQ-016](09_RFAD_수식과_물리_모델.md#EQ-016), [EQ-017](09_RFAD_수식과_물리_모델.md#EQ-017), [EQ-018](09_RFAD_수식과_물리_모델.md#EQ-018), [EQ-040](09_RFAD_수식과_물리_모델.md#EQ-040). **API:** `API-016`, `API-018`, `API-024`.

**연결 gate:** [GAP-003](01_RFAD_설계_결정과_범위.md#GAP-003).

**선행:** [VT-020](#VT-020), [VT-021](#VT-021)의 동일 stage/capability subcase.

**수치 기준:** `BP-EXACT-FIXTURES`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-013"></a>

### VT-013 - UWB pair transfer, time origin

**단계:** R2. **현재 상태:** 시험 명세, 미실행.

**설정:** UWB planar radiator/partial ground/feed/노치 fixture; 거리, 지향, 편파, reference planes가 고정된 antenna pair; pure delay H(f)=exp(-j*2*pi*f*tau), pulse spectral weighting fixture; 절대 amplitude fixture: N=4, Delta_f=1 Hz, FFT-order f=[0,1,-2,-1] Hz, Y=[0,.5,0,.5] V*s, t0=0, carrier=0.

**절차**

1. pair H의 phase unwrap과 null masking 후 group delay를 구한다.
2. 실수 passband/complex baseband를 명시해 pulse response를 복원한다.
3. time origin, band weight, window, zero padding, grid를 바꾼 기록을 비교한다.
4. 측정 delay calibration을 별도 dataset으로 연결한다.
5. backward/ortho/forward norm별 continuous inverse scaling과 bin order를 적용하고 waveform absolute amplitude 및 Parseval을 비교한다.
6. 불균일 f grid에서 직접 IFFT 요청이 거부되는지 확인하고 별도 resampling 경로의 provenance를 검사한다.

**합격 판정**

- pure delay tau=5 ns fixture는 정의된 미분 오차 안에서 5 ns를 회복한다.
- fidelity=1인 scaled/shifted pulse가 전력효율100% 또는 absolute ranging정확성을 뜻하지 않는다.
- pair delay에서 r/c를 빼거나 2로 나누는 작업은 별도 모델, plane 가정 없이 자동 적용되지 않는다.
- 노치/진폭null 주변 delay는 무효 또는 불확실 상태로 표시된다.
- backward norm에서는 N*Delta_f*ifft(Y)=[1,0,-1,0] V, Delta_t=0.25 s이며 시간, 주파수 신호 제곱 적분이 각각 0.5 V^2*s이다. norm 변경 뒤에도 같은 physical waveform을 얻는다.
- N scale 누락의 amplitude 1/N 및 energy 1/N^2 오류를 검출한다. instantaneous waveform에 sqrt(2)를 자동 적용하지 않는다. carrier/bin/time-origin convention이 없거나 불균일 grid이면 해당 역변환을 통과시키지 않는다.

**실패 유도:** S11 phase로 propagation delay 주장; negative-frequency 미러 규약 누락; nonuniform grid에 직접 IFFT 적용; finite band로 무한대역 충실도 주장; fidelity=1만으로 IFFT absolute scaling 승인; default ifft에 Delta_f만 곱하기; FFT-order 또는 carrier 복원 누락.

**필수 증거:** pair setup, complex H, weighted spectrum, time traces, null mask, calibration uncertainty, absolute amplitude and Parseval assertion report, norm/bin/carrier/time-origin metadata.

**요구:** `PHY-002`, `PHY-016`, `PHY-038`, `PHY-050`, `PHY-061`, `PHY-062`, `PHY-083`. **식:** [EQ-020](09_RFAD_수식과_물리_모델.md#EQ-020), [EQ-021](09_RFAD_수식과_물리_모델.md#EQ-021), [EQ-022](09_RFAD_수식과_물리_모델.md#EQ-022). **API:** `API-011`, `API-016`, `API-018`, `API-022`.

**연결 gate:** [GAP-014](01_RFAD_설계_결정과_범위.md#GAP-014).

**선행:** [VT-020](#VT-020), [VT-021](#VT-021), [VT-030](#VT-030)의 동일 stage/capability subcase.

<a id="VT-014"></a>

### VT-014 - NFC L/Q/M/k와 RFID 공액 전달

**단계:** R0/R2 산술 및 회로 선행 / R3 전문 NFC/RFID 물리 검증. **현재 상태:** 시험 명세, 미실행.

**설정:** NFC coil의 geometry/ferrite/shield와 bare/loaded network; coupled L1=1uH,L2=4uH,M=.5uH fixture; UHF RFID Za=20+j100ohm,Zc=20-j100ohm fixture.

**절차**

1. NFC 모드에서 turn/layer/crossover와 R/L/Q/M/k 및 loaded transfer를 평가한다.
2. RFID 모드에서 chip power/frequency/assembly Z와 tau를 평가한다.
3. 두 모드의 metric과 data model을 비교한다.

**합격 판정**

- NFC k=.25, RFID conjugate tau=1의 합성 기대값이 맞는다.
- NFC bare-coil Q와 loaded system Q를 구별하며 self-resonance 위 L-fit를 inductive로 오인하지 않는다.
- RFID conjugate match를 50ohm S11 최소화와 동일시하지 않는다.
- 선형 chip 모델의 유효 power/f 범위를 기록한다.

**실패 유도:** |k|>1의수동inductance matrix; R<=0수동match; 공진위negativeL을무조건positive화; RFID tau로실제range보증.

**필수 증거:** coil graph, Z/Q/M/k curves, chip source/model, transfer and operating-volume evidence.

**요구:** `PHY-002`, `PHY-018`, `PHY-019`, `PHY-040`, `PHY-063`, `PHY-064`, `PHY-083`. **식:** [EQ-025](09_RFAD_수식과_물리_모델.md#EQ-025), [EQ-026](09_RFAD_수식과_물리_모델.md#EQ-026), [EQ-027](09_RFAD_수식과_물리_모델.md#EQ-027), [EQ-028](09_RFAD_수식과_물리_모델.md#EQ-028), [EQ-029](09_RFAD_수식과_물리_모델.md#EQ-029), [EQ-040](09_RFAD_수식과_물리_모델.md#EQ-040). **API:** `API-006`, `API-017`, `API-018`, `API-022`.

**선행:** [VT-020](#VT-020), [VT-022](#VT-022), [VT-030](#VT-030)의 동일 stage/capability subcase.

<a id="VT-015"></a>

### VT-015 - MIMO, 포트 permutation, ECC

**단계:** R2. **현재 상태:** 시험 명세, 미실행.

**설정:** 2-port coupled antenna의 복소 S와 coherent embedded far fields; isotropic W와 명시적 angular/polarization PSD weighting; array/AoA 환경별 manifold fixture.

**절차**

1. 단일포트, 동시여기, 위상반전과 unmatched termination을 평가한다.
2. TARC, accepted power, pattern ECC와 S-only shortcut를 비교한다.
3. lossy fixture에 scalar efficiency만 주고 정확 ECC 요청을 시험한다.
4. array origin/phase/calibration과 환경별 manifold를 비교한다.

**합격 판정**

- 다중포트 전력은 전체 a,b로 계산한다.
- 손실 있는 경우 S-only ECC는 lossless approximation으로 표시되거나 차단된다.
- embedded-pattern 부하, reference plane, normalization이 모두 기록된다.
- array manifold의 위치, 방향, 채널 보정, 공통 위상 기준이 보존된다.

**실패 유도:** 독립normalized plot만으로coherent합성; scalar loss로off-diagonal loss추측; 패턴위상삭제; S11-only Pacc.

**필수 증거:** full S, embedded fields, excitation/load matrices, ECC assumptions, AoA manifold files.

**요구:** `PHY-020`, `PHY-041`, `PHY-044`, `PHY-053`, `PHY-057`, `PHY-059`, `PHY-065`, `PHY-066`. **식:** [EQ-011](09_RFAD_수식과_물리_모델.md#EQ-011), [EQ-014](09_RFAD_수식과_물리_모델.md#EQ-014), [EQ-017](09_RFAD_수식과_물리_모델.md#EQ-017), [EQ-018](09_RFAD_수식과_물리_모델.md#EQ-018), [EQ-023](09_RFAD_수식과_물리_모델.md#EQ-023), [EQ-024](09_RFAD_수식과_물리_모델.md#EQ-024), [EQ-030](09_RFAD_수식과_물리_모델.md#EQ-030), [EQ-032](09_RFAD_수식과_물리_모델.md#EQ-032). **API:** `API-017`, `API-018`, `API-024`.

**연결 gate:** [GAP-015](01_RFAD_설계_결정과_범위.md#GAP-015).

**선행:** [VT-020](#VT-020), [VT-021](#VT-021), [VT-022](#VT-022), [VT-030](#VT-030)의 동일 stage/capability subcase.

<a id="VT-016"></a>

### VT-016 - 공차, 제약, Pareto, 수율

**단계:** R2. **현재 상태:** 시험 명세, 미실행.

**설정:** 공차 distribution과 correlation matrix, fixed seed; multi-band/environment objectives와 제조제약; mode-switch, solver-failure, Pareto dominance synthetic cases.

**절차**

1. 단위, 상관관계, 분포 범위를 검증하고 sample vectors를 저장한다.
2. 민감도 perturbation을 solver noise와 비교하고 resonance branch를 추적한다.
3. budget 제한 아래 Pareto/robust 후보를 계산하고 실패, 중단 시 최선의 검증 후보를 남긴다.
4. 물리 oracle 또는 재해석으로 최종 후보를 재검증한다.

**합격 판정**

- 불법 geometry, 단선, 미지원 재질 후보는 성능으로 채택되지 않는다.
- 수율의 분모, 실패샘플, confidence method가 명확하다.
- IID Bernoulli인 90/100 fixture의 95% Wilson CI는 약[0.8256343385,0.9447708629]이다.
- surrogate prediction/solver result/measurement가 별도 상태로 보존된다.
- 모델 보정 데이터와 독립 validation 데이터가 분리된다.

**실패 유도:** failed run제외로yield상향; 상관무시; AI추천을실측등급화; worstcase목표를nominal만으로통과.

**필수 증거:** samples/seeds, constraint masks, Pareto set, yield interval, budget logs, validation holdout.

**요구:** `PHY-036`, `OPT-UI-001`, `OPT-UI-002`, `OPT-UI-003`, `PHY-076`, `PHY-077`, `PHY-078`, `PHY-084`, `PHY-085`, `PHY-086`, `PHY-087`, `PHY-088`, `PHY-089`, `JOB-002`, `JOB-006`. **식:** [EQ-033](09_RFAD_수식과_물리_모델.md#EQ-033), [EQ-034](09_RFAD_수식과_물리_모델.md#EQ-034), [EQ-035](09_RFAD_수식과_물리_모델.md#EQ-035), [EQ-036](09_RFAD_수식과_물리_모델.md#EQ-036), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037). **API:** `API-020`, `API-021`, `API-018`, `API-022`.

**선행:** [VT-011](#VT-011), [VT-020](#VT-020), [VT-030](#VT-030)의 동일 stage/capability subcase.

<a id="VT-017"></a>

### VT-017 - 하우징, 배터리, 케이블 scenario

**단계:** R1; flex/body 등 모델별 R2/R3. **현재 상태:** 시험 명세, 미실행.

**설정:** bare PCB와 case/battery/cable/hand 또는대체환경 geometry; 각 scenario 좌표, 재질, 거리, 온도, 부하 정의; 제조시료와 조립시료의 measurement metadata.

**절차**

1. external CAD 단위, 배치, 물성을 import한다.
2. scenario별 immutable snapshots와 간소화 model diff를 만든다.
3. 같은 목표/기준면으로 EM, 측정을 비교한다.

**합격 판정**

- 각 환경 객체가 physical revision/hash에 반영된다.
- 손/온도/습도 모델의 데이터가 없으면 수치 효과를 임의 생성하지 않는다.
- 케이블, connector 교란, 하우징, 시료 반복성이 기록된다.
- scenario 간 편파, 대역, 지향 목표가 독립적으로 평가된다.

**실패 유도:** 보이지않는배터리미포함; 기하변경에raw EM 재사용; 검증안된인체모델로SAR합격표시.

**필수 증거:** scenario manifests, CAD simplification diff, aligned results, measurement context.

**요구:** `CAD-007`, `CAD-008`, `PHY-017`, `PHY-033`, `PHY-037`, `PHY-038`, `PHY-081`, `PHY-082`, `PHY-084`. **식:** [EQ-003](09_RFAD_수식과_물리_모델.md#EQ-003), [EQ-017](09_RFAD_수식과_물리_모델.md#EQ-017), [EQ-018](09_RFAD_수식과_물리_모델.md#EQ-018), [EQ-033](09_RFAD_수식과_물리_모델.md#EQ-033), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037), [EQ-040](09_RFAD_수식과_물리_모델.md#EQ-040). **API:** `API-009`, `API-010`, `API-005`, `API-013`, `API-022`.

**연결 gate:** [GAP-009](01_RFAD_설계_결정과_범위.md#GAP-009).

<a id="VT-018"></a>

### VT-018 - 취소, 실패, 디스크 부족, 복구

**단계:** R1; 실제 remote/HPC R3. **현재 상태:** 시험 명세, 미실행.

**설정:** queued/preparing/meshing/running/postprocessing 각 상태; 의도적 process crash/disk-full/network-loss/write failure; backend checkpoint capability true/false fixture.

**절차**

1. 작업 우선순위, 취소, 재시작, 복구를 각 상태에서 수행한다.
2. 저장 도중 강제 종료 후 프로젝트와 불변 snapshot을 연다.
3. checkpoint 미지원 job에 resume를 요청한다.
4. 원격 모드에서는 선택 전후 네트워크 전송 목록을 검사한다.
5. 구버전 프로젝트 migration과 저장 중단, 참조 손상 fixture를 연다.

**합격 판정**

- 부분 파일이 final result로 등록되지 않는다.
- 취소 요청 수신과 실제 프로세스 종료 상태를 분리하며 실패 원인이 남는다.
- 원본, 마지막 완전 저장본과 재현 inputs가 유지된다.
- 취소 acknowledgment, worker 및 자식 프로세스의 실제 종료, 임시 artifact 정리, 메모리 회수는 각각 확인한다. 진행 중 취소와 완료 통지가 경합해도 같은 작업이 중복 완료되거나 partial 결과가 성공으로 발행되지 않는다.
- 반복 열기/닫기, large export, worker crash, IPC 단절의 UI 응답과 복구는 [GUI 성능 계약](24_RFAD_GUI_선정과_성능_설계.md)의 동일 workload로 검사한다. 오래된 응답이 현재 revision의 화면과 파일을 덮어쓰지 않는다.
- checkpoint 미지원 시 fresh restart로 명시하고 resume 성공으로 위장하지 않는다.
- 명시적 원격 선택 전 데이터가 전송되지 않는다; 실제 R3 구현 검사는 별도 gate이다.
- 값, 단위, 출처를 보존한 backup/migration log가 생성되며 지원 불가 schema는 원본을 보존하고 중단한다.

**실패 유도:** 중단파일을완료로캐시; stale resultoverwrite; queue항목중복실행; unsupportedcheckpoint재개.

**필수 증거:** job event journal, recovery report, file hashes, queue state, transfer manifest.

**요구:** `PRJ-006`, `JOB-002`, `JOB-004`, `JOB-006`, `JOB-007`, `NFR-004`, `NFR-005`. **식:** 별도 수식 없음. **API:** `API-004`, `API-013`, `API-014`, `API-015`, `API-028`, `API-029`.

**선행:** [VT-029](#VT-029)의 동일 stage/capability subcase.

<a id="VT-019"></a>

### VT-019 - 전체 패키지 revision/hash 전달

**단계:** R1. **현재 상태:** 시험 명세, 미실행.

**설정:** 해석, 측정, 공차, 문헌, 2D/STEP/CAM을 가진 동일 snapshot; 배포 허용/권한미확인 원문 각각; 같은 설계의 stale export와 valid export.

**절차**

1. 내보낼 내용과 빠질 의미를 preview한다.
2. report와 handoff package를 만든다.
3. 독립 환경에서 safe unpack 후 manifest/hash/link를 검사한다.
4. 데이터 파일, 사용자 script, plugin을 구분해 import하고 배포 SBOM/license notice를 검토한다.

**합격 판정**

- 모든 산출물은 정확한 snapshot, material, solver, network, metric revision을 가리킨다.
- 가정, 미해결 이슈, 출처, 검증 상태와 실측 조건이 보고서에서 읽힌다.
- 권한미확인 원문은 기본 배포에서 제외되고 citation metadata/사용자 로컬 연결은 유지된다.
- 보유 원문과 재배포 권리를 혼동하지 않는다.
- 자료 파일을 여는 것만으로 임의 코드가 실행되지 않으며 실행할 사용자 script 경로와 대상을 별도로 표시한다.
- solver를 별도 프로세스로 분리했다는 이유만으로 라이선스 의무 면제를 선언하지 않는다.

**실패 유도:** zip path traversal; 해시불일치; 타revision결과삽입; 권리미확인PDF묵시복제.

**필수 증거:** package manifest, report, export verification, rights decision log.

**요구:** `PHY-088`, `OUT-008`, `OUT-009`, `DAT-006`, `NFR-004`, `NFR-006`, `NFR-007`. **식:** [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-023`, `API-024`, `API-025`, `API-026`, `API-027`.

**선행:** [VT-007](#VT-007), [VT-008](#VT-008), [VT-009](#VT-009), [VT-027](#VT-027)의 동일 stage/capability subcase.

<a id="VT-020"></a>

### VT-020 - 수식 정의, 단위, 검증 벡터

**단계:** R0 and every mathematical change. **현재 상태:** 시험 명세, 미실행.

**설정:** [수식 문서](09_RFAD_수식과_물리_모델.md)의 EQ ID별로 구현 전에 마련할 arithmetic vectors; 현재 equation_registry.json은 제공되지 않음; domain/zero/NaN/Inf/ill-conditioned negative fixtures; 독립 고정 expected 값과 production function.

**절차**

1. SI와 complex/time convention을 적용한 입력을 각 function에 전달한다.
2. 숫자/상태/단위/적용범위 결과를 기대값과 비교한다.
3. production 함수로 expected 값을 생성하지 않은 독립 oracle provenance를 확인한다.

**합격 판정**

- 58개 이상의 초기 vector를 작성하고 모든 vector에 독립 expected와 assertion을 부여한다. 숫자 채우기를 위해 같은 사례를 복제하지 않으며 각 EQ의 정의역, 부호, 단위 및 특이점 coverage를 확인한다. tolerance는 scalar scale별로 정한다.
- f<=0,denominator0,invalidPSD,unsupportedwave 상태가 명시적 에러/undefined로 반환된다.
- 이 suite 통과는 산술, 계약 검증이고 전체파, 측정 통과로 보고되지 않는다.
- EQ-021의 N=4 spectrum fixture에서 absolute waveform [1,0,-1,0] V와 두 Parseval 적분 0.5 V^2*s를 검사한다. 정규화된 fidelity 또는 group delay만으로 대체하지 않는다.

**실패 유도:** expected를implementation출력으로갱신; 0/0을0으로표기; infinity를finite성능으로처리.

**필수 증거:** equation assertion report, oracle provenance, negative case log.

**요구:** `PHY-008`, `SYN-001`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-002](09_RFAD_수식과_물리_모델.md#EQ-002), [EQ-003](09_RFAD_수식과_물리_모델.md#EQ-003), [EQ-004](09_RFAD_수식과_물리_모델.md#EQ-004), [EQ-005](09_RFAD_수식과_물리_모델.md#EQ-005), [EQ-006](09_RFAD_수식과_물리_모델.md#EQ-006), [EQ-007](09_RFAD_수식과_물리_모델.md#EQ-007), [EQ-008](09_RFAD_수식과_물리_모델.md#EQ-008), [EQ-009](09_RFAD_수식과_물리_모델.md#EQ-009), [EQ-010](09_RFAD_수식과_물리_모델.md#EQ-010), [EQ-011](09_RFAD_수식과_물리_모델.md#EQ-011), [EQ-012](09_RFAD_수식과_물리_모델.md#EQ-012), [EQ-013](09_RFAD_수식과_물리_모델.md#EQ-013), [EQ-014](09_RFAD_수식과_물리_모델.md#EQ-014), [EQ-015](09_RFAD_수식과_물리_모델.md#EQ-015), [EQ-016](09_RFAD_수식과_물리_모델.md#EQ-016), [EQ-017](09_RFAD_수식과_물리_모델.md#EQ-017), [EQ-018](09_RFAD_수식과_물리_모델.md#EQ-018), [EQ-019](09_RFAD_수식과_물리_모델.md#EQ-019), [EQ-020](09_RFAD_수식과_물리_모델.md#EQ-020), [EQ-021](09_RFAD_수식과_물리_모델.md#EQ-021), [EQ-022](09_RFAD_수식과_물리_모델.md#EQ-022), [EQ-023](09_RFAD_수식과_물리_모델.md#EQ-023), [EQ-024](09_RFAD_수식과_물리_모델.md#EQ-024), [EQ-025](09_RFAD_수식과_물리_모델.md#EQ-025), [EQ-026](09_RFAD_수식과_물리_모델.md#EQ-026), [EQ-027](09_RFAD_수식과_물리_모델.md#EQ-027), [EQ-028](09_RFAD_수식과_물리_모델.md#EQ-028), [EQ-029](09_RFAD_수식과_물리_모델.md#EQ-029), [EQ-030](09_RFAD_수식과_물리_모델.md#EQ-030), [EQ-031](09_RFAD_수식과_물리_모델.md#EQ-031), [EQ-032](09_RFAD_수식과_물리_모델.md#EQ-032), [EQ-033](09_RFAD_수식과_물리_모델.md#EQ-033), [EQ-034](09_RFAD_수식과_물리_모델.md#EQ-034), [EQ-035](09_RFAD_수식과_물리_모델.md#EQ-035), [EQ-036](09_RFAD_수식과_물리_모델.md#EQ-036), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037), [EQ-038](09_RFAD_수식과_물리_모델.md#EQ-038), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039), [EQ-040](09_RFAD_수식과_물리_모델.md#EQ-040), [EQ-041](09_RFAD_수식과_물리_모델.md#EQ-041). **API:** `API-007`, `API-017`, `API-018`, `API-019`.

**수치 기준:** `BP-ARITHMETIC`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-021"></a>

### VT-021 - solver native 진폭, 위상 규약

**단계:** R0; each native adapter/channel version change. **현재 상태:** 시험 명세, 미실행.

**설정:** known-power matched port, plane wave 또는적합한analytic field fixture; native instantaneous signal/FFT/V/I/E/H/S/Prad 채널별 정의; scikit-rf Circuit V/I peak 규약과 pinned version.

**절차**

1. raw channel의 native amplitude, phasor, Fourier, units를 기록한다.
2. 확인된 peak phasor 채널만 RMS 변환한다.
3. input power scaling, phase-delay, E/H impedance, Poynting를 독립 fixture로 비교한다.

**합격 판정**

- S와 instantaneous samples에 sqrt(2) 변환을 적용하지 않는다.
- solver_native 상태를 보존하고 규약 미확정 채널에 절대 power/gain을 계산하지 않는다.
- field FFT scaling을 두 번 적용하지 않고 port/channel 간 에너지 수지가 일치한다.
- native raw와 canonical derived가 분리 저장된다.

**실패 유도:** 전채널blanket1/sqrt(2); Fourier부호반전; field반경정규화누락; peak CircuitV를RMS로사용.

**필수 증거:** channel mapping table, known-power evidence, raw/canonical hashes, adapter regression.

**요구:** `PHY-044`, `PHY-052`, `PHY-054`, `PHY-058`, `PHY-059`, `PHY-060`, `INT-001`. **식:** [EQ-008](09_RFAD_수식과_물리_모델.md#EQ-008), [EQ-011](09_RFAD_수식과_물리_모델.md#EQ-011), [EQ-013](09_RFAD_수식과_물리_모델.md#EQ-013), [EQ-014](09_RFAD_수식과_물리_모델.md#EQ-014), [EQ-016](09_RFAD_수식과_물리_모델.md#EQ-016), [EQ-017](09_RFAD_수식과_물리_모델.md#EQ-017), [EQ-020](09_RFAD_수식과_물리_모델.md#EQ-020), [EQ-021](09_RFAD_수식과_물리_모델.md#EQ-021). **API:** `API-001`, `API-011`, `API-012`, `API-016`, `API-018`.

**연결 gate:** [GAP-003](01_RFAD_설계_결정과_범위.md#GAP-003).

<a id="VT-022"></a>

### VT-022 - 복소 Z0, 회로 연결, loaded field

**단계:** R0/R2. **현재 상태:** 시험 명세, 미실행.

**설정:** complex Z0 with Re>0 네트워크와 low-loss/losing load cases; 독립 MNA/SPICE 또는analytic interconnect oracle; fixed EM geometry의 embedded field basis; 비단위 native basis A_basis=[[2,0],[0,1]], a_req=[2,1]; port/excitation permutation과 rank-deficient variant; complex network-side load: Z0=50+j25 ohm, ZL=50-j25 ohm, I_into_network=-V/ZL.

**절차**

1. power/pseudo wave definitions과 S<->Z round trip을 시험한다.
2. Schur load reduction, internal S interconnect, cascade/deembed를 oracle와 비교한다.
3. external matching망과 실제 copper geometry 변경을 구분한다.
4. 종단/여기변경 후 총 복소field, power를 재계산한다.
5. 요청 a를 원 EM plane/wave로 복원한 뒤 A_basis c=a_req를 풀고 c로 raw complex fields를 합성한다.
6. V/I continuity 또는 검증된 공통 real-Zref renormalization 경로로 C를 구성하고 load 자체의 Gamma와 비교한다.

**합격 판정**

- Z0=50+j25ohm,ZL=50-j25ohm이면 power Gamma=0, voltageGamma=-j0.5를 구별한다.
- ill-conditioned matrix는 진단하며 explicit inverse로 불안정 수치를 숨기지 않는다.
- S renormalization만으로 embedded field basis를 변환했다고 주장하지 않는다.
- 동일 EM model에 외부 lumped 망만 바꾸면 raw reuse 가능하나 pads/traces/material 변화는 raw stale이다.
- 비단위 fixture의 c=[1,1]이 독립 기대값과 일치한다. port/excitation 순서 permutation 뒤에도 동일 physical field를 얻으며 rank/conditioning/residual을 기록한다.
- 복소 반례에서 load Gamma=0이지만 network-facing C=.2-j.4임을 독립 기대값으로 확인한다. 서로 다른 전류 방향/파 기준을 구별하고 C에 EQ-011 load Gamma를 직접 재사용하지 않는다.

**실패 유도:** ReZ0<=0에미소양수주입후통과; 복소Z0연결을단순port swap으로대체; coupledantenna배열단일portshortcut; rank 부족 basis를 전체 N-port basis로 승인; a_req를 비단위 raw field coefficient로 직접 사용; 복소 load의 Gamma=0을 ai=Cbi에서 C=0으로 재사용.

**필수 증거:** network oracle comparisons, condition estimates, load/excitation solution, field basis transforms, cache decision log, V/I continuity and C-constructor assertion report.

**요구:** `PHY-039`, `PHY-040`, `PHY-041`, `PHY-042`, `PHY-043`, `PHY-044`, `PHY-052`, `JOB-005`. **식:** [EQ-010](09_RFAD_수식과_물리_모델.md#EQ-010), [EQ-011](09_RFAD_수식과_물리_모델.md#EQ-011), [EQ-012](09_RFAD_수식과_물리_모델.md#EQ-012), [EQ-014](09_RFAD_수식과_물리_모델.md#EQ-014), [EQ-028](09_RFAD_수식과_물리_모델.md#EQ-028), [EQ-029](09_RFAD_수식과_물리_모델.md#EQ-029), [EQ-030](09_RFAD_수식과_물리_모델.md#EQ-030), [EQ-031](09_RFAD_수식과_물리_모델.md#EQ-031), [EQ-032](09_RFAD_수식과_물리_모델.md#EQ-032). **API:** `API-017`, `API-018`, `API-030`.

**연결 gate:** [GAP-013](01_RFAD_설계_결정과_범위.md#GAP-013), [GAP-015](01_RFAD_설계_결정과_범위.md#GAP-015).

**선행:** [VT-020](#VT-020), [VT-021](#VT-021)의 동일 stage/capability subcase.

<a id="VT-023"></a>

### VT-023 - 적응형 주파수와 숨은 high-Q

**단계:** R2. **현재 상태:** 시험 명세, 미실행.

**설정:** 초기 sample 사이의 좁은 resonance/notch를 가진 합성 high-Q oracle; frequency-domain point solver와 broadband-transient backend의 capability declarations; budget/holdout points/quality metric 설정.

**절차**

1. 명시적 initial grid와 adaptive plan으로 구간을 refine한다.
2. 추가 실제 solves/native transient 재평가/보간을 각각 태그한다.
3. holdout 또는 known-pole dense reference와 비교한다.
4. budget을 의도적으로 소진하고 좁은 feature가 남는 경우를 검사한다.

**합격 판정**

- 보간, rational fit, surrogate 점을 actual solve point로 표시하지 않는다.
- 추가 FFT 표본이 transient 시간 길이/해상도를 향상시켰다고 주장하지 않는다.
- NF2FF FD recording에 없는 frequency를 미보유 field로 계산하지 않는다.
- 검증된 fixture에서 feature를 찾거나 품질 미확인 상태를 남기며 보편 hidden high-Q 부재를 보증하지 않는다.

**실패 유도:** fixeddenseplot을adaptive라고표시; fitresidual만으로대역전체통과; transienttruncation링잉을실제공진으로채택.

**필수 증거:** sample provenance, refinement decisions, heldout residual, budget/quality report.

**요구:** `AUG-002`, `PHY-061`, `PHY-050`. **식:** [EQ-009](09_RFAD_수식과_물리_모델.md#EQ-009), [EQ-020](09_RFAD_수식과_물리_모델.md#EQ-020), [EQ-021](09_RFAD_수식과_물리_모델.md#EQ-021), [EQ-035](09_RFAD_수식과_물리_모델.md#EQ-035), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037). **API:** `API-011`, `API-013`, `API-018`, `API-020`, `API-021`.

**선행:** [VT-011](#VT-011), [VT-020](#VT-020)의 동일 stage/capability subcase.

<a id="VT-024"></a>

### VT-024 - 명시적 parameter sweep

**단계:** R1. **현재 상태:** 시험 명세, 미실행.

**설정:** 치수, 재질, 부하, 환경의 명시적 list/grid sweep; factorial budget와 duplicate parameter tuples; 개별 invalid point와 중단, 재개 case.

**절차**

1. 사용자가 sweep values를 입력하고 generated sample table을 검토한다.
2. 각 point의 constraint validation, dependency classification, execution을 기록한다.
3. table/curve를 공통 목표, normalization으로 비교하고 best candidate를 선택한다.

**합격 판정**

- 각 sample은 정확한 변수, 단위, snapshot, seed, run ID를 가지며 비적응 grid/list 계획이 재현된다.
- 결과 없는 지점을 임의보간한 valid candidate로 취급하지 않는다.
- 형상 변화와 외부회로 변화의 raw reuse 정책이 다르게 적용된다.

**실패 유도:** 공통변수단위혼동; duplicate jobs; 중단후누락point조용한삭제.

**필수 증거:** sweep plan, point table, cache decisions, comparison report.

**요구:** `AUG-001`, `PRJ-007`, `OPT-UI-002`, `JOB-005`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-035](09_RFAD_수식과_물리_모델.md#EQ-035), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037). **API:** `API-020`, `API-021`, `API-017`, `API-018`.

**선행:** [VT-018](#VT-018), [VT-022](#VT-022)의 동일 stage/capability subcase.

<a id="VT-025"></a>

### VT-025 - 자유형상, 대리모델, 역설계

**단계:** R3. **현재 상태:** 시험 명세, 미실행.

**설정:** 허용 design space, 제조규칙, 초기 template 외 freeform candidate; inverse design/AI model의 training provenance/domain/holdout; 동일 목표로 독립 full-wave 재검증할 최종 후보.

**절차**

1. freeform conductor/slot topology를 가져오거나 생성한다.
2. AI 제안의 변경 diff, 근거, 불확실성, 학습범위를 표시한다.
3. geometric feasibility와 solver capability를 통과한 후보만 평가한다.
4. 최종 선택 후보를 독립 full-wave 또는측정으로 확인한다.

**합격 판정**

- 자유 형상 및 topology 결과가 parametrized source model로 보존된다.
- surrogate 예측과 실제 해석/실측 상태가 섞이지 않는다.
- OOD, 권리불명 학습자료, 재현불가 생성 seed가 명시된다.
- 이 검사는 R3 capability이며 R1 저장지원만으로 구현완료를 주장하지 않는다.

**실패 유도:** minimumgap무시; 불연속net최적; trainingset재사용으로independentvalidation주장.

**필수 증거:** candidate geometry, proposal diff, model card, holdout report, revalidation results.

**요구:** `AUG-003`, `PHY-006`, `CAD-009`, `OPT-UI-003`, `PHY-078`. **식:** [EQ-034](09_RFAD_수식과_물리_모델.md#EQ-034), [EQ-035](09_RFAD_수식과_물리_모델.md#EQ-035), [EQ-036](09_RFAD_수식과_물리_모델.md#EQ-036), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037). **API:** `API-007`, `API-020`, `API-021`.

**선행:** [VT-003](#VT-003), [VT-016](#VT-016), [VT-030](#VT-030)의 동일 stage/capability subcase.

<a id="VT-026"></a>

### VT-026 - 정합 BOM, 실장변형, 좌표

**단계:** R2. **현재 상태:** 시험 명세, 미실행.

**설정:** L/pi/T matching network와 ideal/real component models; BOM supplier/MPN/package/Q/ESR/SRF/tolerance metadata; DNP, 0ohm, value change, rotation/position variants.

**절차**

1. 안테나 plane/IC plane과 network topology를 기록한다.
2. 부품값변경, DNP, 실장좌표, 동박pad변경을 각각 변경한다.
3. matching solution과 assembly/BOM export를 비교한다.
4. R2에서 topology 구조 탐색과 고정 network 값 조정을 비교하고 R3에서 tuner state/control code별 모델, 측정을 연결한다.

**합격 판정**

- BOM, 실장변형, 좌표, net과 snapshot이 연결된다.
- 실제 부품 loss/SRF/공차가 ideal L/C와 분리된다.
- 부품 전력/전압/유효 주파수 한계를 초과한 후보가 명시된다.
- 외부 equivalent change와 EM geometry change의 재해석 경계가 지켜진다.
- 회로 구조 후보와 소자값 후보가 별도로 기록되고 실제 소자 loss/tolerance/BOM가 연결된다.
- R3 tuner state 변경은 회로, 제어 코드, 적용대역, 측정 dataset을 함께 바꾸며 선형 상태 모델의 유효 범위를 밝힌다.

**실패 유도:** DNP를short로해석; 0ohm를idealzeroac손실로간주; MPN값과netlist값불일치.

**필수 증거:** network netlist, BOM variants, placement coordinates, power checks, dependency hashes.

**요구:** `AUG-004`, `SYN-002`, `TUNE-001`, `PHY-039`, `PHY-042`. **식:** [EQ-027](09_RFAD_수식과_물리_모델.md#EQ-027), [EQ-028](09_RFAD_수식과_물리_모델.md#EQ-028), [EQ-029](09_RFAD_수식과_물리_모델.md#EQ-029), [EQ-030](09_RFAD_수식과_물리_모델.md#EQ-030), [EQ-032](09_RFAD_수식과_물리_모델.md#EQ-032), [EQ-036](09_RFAD_수식과_물리_모델.md#EQ-036). **API:** `API-017`, `API-020`, `API-030`, `API-024`.

**선행:** [VT-022](#VT-022)의 동일 stage/capability subcase.

<a id="VT-027"></a>

### VT-027 - 자료 상충, 추정, 검증등급

**단계:** R1. **현재 상태:** 시험 명세, 미실행.

**설정:** corpus IDs:31형상, 3160재질, 41보조, 47조건, 26검증; RO4730G3 상충 Df .0022/.0028 등 원자료 충돌; 문헌, 추정, 보간, 외삽, CAD재현, 실측의 상태별 record; 권리허용/불명 자료와 fulltext/search index.

**절차**

1. 레코드를 import하고 checksum, revision, page/CAD member jump를 검사한다.
2. conflict/missing/not-applicable states를 선택, 수정하고 audit trail을 확인한다.
3. band/geometry/material/board size/evidence stage/source 조합으로 검색한다.
4. 권리 상태를 바꿔 검색과 원문 배포 정책을 각각 확인한다.
5. 지역, 프로파일, 표준개정, 외부시험보고서의 승인 상태를 확인한다.

**합격 판정**

- 서로 다른 조건의 값을 자동 평균/덮어쓰지 않는다.
- 문헌 존재, 형상복원, solver계산, 실측 상태의 승격에 요구 증거가 필요하다.
- 검색 결과가 사용된 필터와 상태를 정확히 반영한다.
- 원문 열기와 재배포 권리는 별개로 기록한다.
- EM 결과만으로 KC/FCC 등 공식 인증 완료 상태를 만들 수 없다.

**실패 유도:** 미확인값을0; 없는페이지링크; 오래된버전출처를최신으로표기; 측정값없음에도검증badge.

**필수 증거:** import counts, query assertions, source jumps, evidence transition log, rights manifest.

**요구:** `DAT-001`, `DAT-002`, `DAT-003`, `DAT-004`, `DAT-005`, `DAT-006`, `DAT-007`, `PRJ-009`, `PHY-005`, `PHY-087`, `PHY-089`, `NFR-009`. **식:** 별도 수식 없음. **API:** `API-009`, `API-010`, `API-027`, `API-026`.

<a id="VT-028"></a>

### VT-028 - UI 응답, 취소 feedback

**단계:** R1. **현재 상태:** 시험 명세, 미실행.

**설정:** 한국어/영문 technical label UI와 keyboard-only session; 복수 대역, 프로파일, 목표, 포트, 크기 제한 project; 2D/3D/parameter linked selection, quick/advanced modes; fixed hardware/model benchmark profile.

**절차**

1. 키보드만으로 open->edit->validate->run->export 핵심흐름을 수행한다.
2. 보드/물성/급전/solver 누락을 만들고 단계 안내와 오류 focus를 확인한다.
3. 동일 entity를2D/3D/table에서 선택하고 거리/각도를 측정한다.
4. [GUI 성능 계약](24_RFAD_GUI_선정과_성능_설계.md)의 동등 기능 release prototype과 workload로 입력 p95/p99 latency, frame time, cold/warm startup, 전체 프로세스 working set/private commit 및 GPU memory를 측정한다. acknowledgment, 화면 반영, 계산 완료를 각각 기록한다.
5. 원호, IFA, UWB 예제를 새 사용자 역할로 따라가고 실패 사례, 출력 검사를 확인한다.

**합격 판정**

- 색상 없이 오류/경고/미실행/해석/실측/예측 상태를 구별할 수 있다.
- quick default의 출처, 적용조건을 보고 advanced 값과 같은 canonical model로 연결된다.
- 단순 프로토콜 이름이 재료, 공진, 최적 성능을 자동 결정하지 않는다.
- 한국어 UI와 영문 기술명, 단위가 잘리거나 모순되지 않는다.
- wxWidgets와 Avalonia 후보는 [GUI 성능 계약](24_RFAD_GUI_선정과_성능_설계.md)의 같은 입력/renderer/worker 조건으로 비교한다. Qt는 후보에서 제외한다. 성능 예산은 사용자 검토용 제안이며 측정값과 승인값을 구분한다.
- 각 예제의 기대 형상, 입력조건, evidence state, 실패 이유가 재현 가능하게 제공된다.

**실패 유도:** keyboardtrap; hover/color-only error; quickmode가숨겨진값덮어쓰기; render화면에잘못된unit.

**필수 증거:** interaction script, accessibility review, linked-selection assertions, latency/frame/startup distributions, 전체 process tree와 GPU memory trace, hardware/OS/build profile, 반복 열기/닫기 및 취소/복구 결과. 구체적 필드와 예산은 RFAD 24를 따른다.

**요구:** `PRJ-001`, `PRJ-002`, `PRJ-003`, `PRJ-004`, `PRJ-008`, `PRJ-010`, `SYN-001`, `NFR-003`, `NFR-008`. **식:** [EQ-001](09_RFAD_수식과_물리_모델.md#EQ-001), [EQ-039](09_RFAD_수식과_물리_모델.md#EQ-039). **API:** `API-002`, `API-003`, `API-006`, `API-008`, `API-014`, `API-024`.

**연결 gate:** [GAP-012](01_RFAD_설계_결정과_범위.md#GAP-012).

**수치 기준:** `BP-UI-CANDIDATE`; 합성 기대값과 잠정 제안치를 구별한다.

<a id="VT-029"></a>

### VT-029 - 실행환경, RMS 변환, 재현

**단계:** R0/R1; additional solvers/API automation R2; remote R3. **현재 상태:** 시험 명세, 미실행.

**설정:** Linux native와 Windows11+WSL2 지원대상 environment manifests; solver/CAD/library absent, wrongversion, capability mismatch fixtures; GUI/CLI 동일 canonical project+seed; wxWidgets/Avalonia 중 선정한 GUI와 worker를 포함한 실제 배포; 교체 adapter와 중립 schema open/save.

**절차**

1. dependency discovery와 pinned-version report를 검사한다.
2. 같은 project를 GUI와 batch에서 생성/해석/출력한다.
3. 다른 backend로 import할 때 material/port/mesh/normalization mapping 차이를 비교한다.
4. 중립 schema migration, immutable snapshots, cache keys를 검사한다.
5. 네트워크를 차단한 설치 완료 환경에서 편집, 로컬 해석, 출력을 실행하고 SBOM와 버전별 license 원문을 검사한다.

**합격 판정**

- 미설치 solver에서도 가능한 편집/출력 범위와 불가능한 계산을 명확히 보여준다.
- zero solver 상태에 valid computed result를 생성하지 않는다.
- Linux/WindowsWSL 배포 각각 capability와 재현 gate를 통과해야 R1 지원표시를 한다.
- 두 solver 비교는 지원 시 R2 별도 fixture를 실제 실행하며 단순 adapter interface만으로 완료되지 않는다.
- 물리 변경, external network 변경, display 변경의 cache 범위가 계약대로 분리된다.
- 문서화된 중립 프로젝트가 특정 GUI/상용solver 전용 format 없이 열린다.
- 온라인 프로파일/자료 갱신을 제외한 약속된 핵심 기능이 offline으로 실행된다.
- 실제 배포별 라이선스 의무 검토와 지원 platform별 benchmark evidence가 기록된다.

**실패 유도:** missingbackend자동성공; 미지원재질silentfallback; OS제외로그누락; displayunit으로rawhash변경; 용량예측을보장메모리로표시.

**필수 증거:** version locks, capability matrix, GUI/CLI snapshot diff, platform reports, cache invalidation table.

**요구:** `INT-001`, `INT-002`, `INT-003`, `INT-004`, `INT-005`, `INT-006`, `JOB-003`, `JOB-005`, `JOB-006`, `PHY-090`, `NFR-001`, `NFR-002`, `NFR-005`, `NFR-006`, `NFR-007`. **식:** [EQ-008](09_RFAD_수식과_물리_모델.md#EQ-008), [EQ-011](09_RFAD_수식과_물리_모델.md#EQ-011), [EQ-012](09_RFAD_수식과_물리_모델.md#EQ-012), [EQ-038](09_RFAD_수식과_물리_모델.md#EQ-038). **API:** `API-001`, `API-002`, `API-004`, `API-005`, `API-011`, `API-012`, `API-013`, `API-017`, `API-026`.

**연결 gate:** [GAP-003](01_RFAD_설계_결정과_범위.md#GAP-003), [GAP-004](01_RFAD_설계_결정과_범위.md#GAP-004), [GAP-013](01_RFAD_설계_결정과_범위.md#GAP-013).

<a id="VT-030"></a>

### VT-030 - 독립 benchmark, 측정 정확도

**단계:** R0 baseline selection; each supported physical mode at its release. **현재 상태:** 시험 명세, 미실행.

**설정:** 분석해/공식solver example/제조사 complete reference/측정시료의 구별된 benchmark set; 회로, EM, OTA, NFC, RFID, UWB, MIMO 영역별 independent oracle; 측정 calibration, fixture, environment, uncertainty budget; 보정 데이터와 분리된 holdout cases.

**절차**

1. benchmark마다 geometry, material, port, boundary, normalization, error budget을 고정한다.
2. mesh/boundary/time convergence를 먼저 확인한다.
3. 분석/타solver/측정과 비교하고 model inadequacy와 measurement uncertainty를 분리한다.
4. 독립 holdout에 결과를 재검증하고 capability 범위를 갱신한다.

**합격 판정**

- 수식 arithmetic 통과나 numerical convergence만으로 physical accuracy를 승인하지 않는다.
- 완전하지 않은 G031 reference로 방사성능 재현 pass를 만들지 않는다.
- 기능별 허용오차는 출처, benchmark, measurement uncertainty, 사용목표에서 승인된다.
- lossyMIMO, UWB timing, NFC operatingvolume, RFID chip-transfer의 검증을 singleS11로 대체하지 않는다.
- 기능확장(SAR, EMC, nonlinear, thermal 등)은 별도 입력/solver/검증이 없으면 미지원 상태다.

**실패 유도:** 문헌그림눈대중일치로accuracy보증; 한시료fit데이터재사용; 측정환경불일치; 역사Yee식단독stability인증.

**필수 증거:** benchmark registry, independent-oracle comparison, measurement uncertainty, holdout report, capability approval.

**요구:** `PHY-008`, `PHY-081`, `PHY-082`, `PHY-083`, `PHY-084`, `PHY-085`, `PHY-086`, `PHY-087`, `PHY-089`, `PHY-090`. **식:** [EQ-005](09_RFAD_수식과_물리_모델.md#EQ-005), [EQ-007](09_RFAD_수식과_물리_모델.md#EQ-007), [EQ-009](09_RFAD_수식과_물리_모델.md#EQ-009), [EQ-015](09_RFAD_수식과_물리_모델.md#EQ-015), [EQ-017](09_RFAD_수식과_물리_모델.md#EQ-017), [EQ-019](09_RFAD_수식과_물리_모델.md#EQ-019), [EQ-020](09_RFAD_수식과_물리_모델.md#EQ-020), [EQ-023](09_RFAD_수식과_물리_모델.md#EQ-023), [EQ-025](09_RFAD_수식과_물리_모델.md#EQ-025), [EQ-027](09_RFAD_수식과_물리_모델.md#EQ-027), [EQ-033](09_RFAD_수식과_물리_모델.md#EQ-033), [EQ-037](09_RFAD_수식과_물리_모델.md#EQ-037), [EQ-040](09_RFAD_수식과_물리_모델.md#EQ-040). **API:** `API-019`, `API-022`, `API-018`, `API-027`.

**연결 gate:** [GAP-003](01_RFAD_설계_결정과_범위.md#GAP-003), [GAP-004](01_RFAD_설계_결정과_범위.md#GAP-004), [GAP-006](01_RFAD_설계_결정과_범위.md#GAP-006), [GAP-009](01_RFAD_설계_결정과_범위.md#GAP-009), [GAP-012](01_RFAD_설계_결정과_범위.md#GAP-012), [GAP-013](01_RFAD_설계_결정과_범위.md#GAP-013), [GAP-014](01_RFAD_설계_결정과_범위.md#GAP-014), [GAP-015](01_RFAD_설계_결정과_범위.md#GAP-015).

**선행:** [VT-011](#VT-011), [VT-020](#VT-020), [VT-021](#VT-021), [VT-022](#VT-022)의 동일 stage/capability subcase.

## 6. 실행 결과와 출시에 필요한 기록

각 실행 결과는 test ID/version, AC/subcase ID, actual runtime, fixture/input hash, expected/actual, metric별 tolerance와 판정, 실패 원인, evidence artifact, 검토 상태를 저장한다. 테스트 runner가 통과했다는 사실과 사용자가 제품 설계를 승인했다는 사실을 분리한다. pass는 선언한 범위의 필수 assertion을 모두 실제 실행하여 충족했을 때만 기록한다. 제외한 assertion은 not_applicable 사유와 축소된 출시 범위에 남기며 원 suite 전체 또는 원 요구 전체를 통과한 것으로 합산하지 않는다.

R0는 versions, 단위, CAD, 포트, native normalization, 재료 mapping, known circuit, 공식 EM benchmark의 재현 envelope를 먼저 고정한다. Linux worker 검증을 Windows 11+WSL2 배포 시험으로 대신하지 않으며 각 지원 runtime의 evidence가 필요하다. R1 범위의 기능은 그 범위에서 실제 동작, 실패 복구, 교환, 현실적 benchmark를 확인한 뒤 출시한다. R2/R3는 해당 물리 모드/adapter의 실검증을 추가한다.

### 6.1 unresolved gate와 최소 폐쇄 증거

| GAP | 폐쇄에 필요한 구체적 증거 | 연결 suite |
|---|---|---|
| GAP-003 native normalization | 실제 pinned native 채널별 amplitude/FFT/time/r 규약, known-power/phase fixture | VT-021/012/029 |
| GAP-004 material, 도체 | native epsilon(f)/mu(f) mapping, sheet/volume/PEC/roughness의 적용 envelope와 손실 비교 | VT-004/006/030 |
| GAP-006 G031 환경 | 완전한 ground, stackup, ports, 실장환경 원본과 필요한 별도 성능 benchmark | VT-001/030 |
| GAP-009 실측 | 교정, fixture, 환경, 시료 반복성과 uncertainty를 갖춘 독립 측정 | VT-010/017/030 |
| GAP-012 잠정 threshold | fixture/metric/domain/hardware별 승인된 tolerance/profile | VT-011/028/030 |
| GAP-013 복합 급전/파 정의 | CPW, stripline, differential/modal, complex Z0의 adapter와 interconnect oracle 비교 | VT-010/022/029 |
| GAP-014 UWB | pair H, time origin, pulse weighting, delay calibration의 독립 비교 | VT-013/030 |
| GAP-015 lossy MIMO | coherent embedded-field basis, loaded termination, loss/ECC의 독립 power/pattern 비교 | VT-015/022/030 |

이 문서의 시험 계획은 이 GAP들을 해소했다고 주장하지 않는다. 또한 모든 RF 구조, 주파수, 재료의 성능, 인증 통과, 생산 수율, 실제 통신거리를 자동 보증하는 합격 배지를 정의하지 않는다.

## 7. 원천 자료와 수용기준의 우선순위

사용자 명시 요구와 [병합된 요구](03_RFAD_사용자_요구사항.md)가 기능 목적이다. A/B 인수 문서는 검수 시나리오의 근거이며 B의 잠정 숫자는 별도 profile이다. 물리식, API 정의는 primary source와 고정 버전 contract fixture로 확인한다. 제조사 예제의 mesh/종료값, 실측 수치를 범용 합격선으로 확대하지 않는다.

본 문서의 추가 시험 VT-020~030과 부정 입력 시험은 설계자가 제안한 검증 정책이다. 현재 기준은 [수식](09_RFAD_수식과_물리_모델.md), [요구별 AC 추적표](17_RFAD_요구사항_추적표.md), 본문의 suite 계약이다. 기계판독 수식/시험 registry는 후속 구현에서 이 문서의 ID와 의미를 보존하여 만들 산출물이며 현재 파일이나 실행 증거로 간주하지 않는다.

## GUI 후보 선택 시험

GUI-SPIKE-001..007은 [GUI 선정과 성능 설계](24_RFAD_GUI_선정과_성능_설계.md)의 동등 기능 비교와 자원/응답 계약을 따른다. VT-028은 사용자 조작과 응답성, VT-018은 취소와 복구, VT-029는 실제 OS/runtime 배포 재현을 담당한다. SPIKE 결과에는 관련 VT와 AC subcase를 연결하고 같은 측정 artifact의 재사용 범위를 명시한다. 단일 창 표시, 설치 성공, 빈 화면의 메모리 수치만으로 어느 suite도 전체 통과시키지 않는다.
