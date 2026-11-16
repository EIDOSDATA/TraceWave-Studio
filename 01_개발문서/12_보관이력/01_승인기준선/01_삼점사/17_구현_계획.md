# 개발 순서, 작업 분해, 완료 조건

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

## 1. 개발 방식

설계 기준선 3.4의 D0 문서 승인은 완료되었으며 현재는 개발 착수 전이다. 사용자는 C++ wxWidgets, 일반 편집 60 fps/대형 장면 30 fps를 포함한 24번 PERF-001~010과 기준 host/fixture를 초기 목표로 채택했다. R1은 Windows 11 x64 wxMSW GUI와 local WSL2 Linux worker를 먼저 제공하며, 유료 GUI 부품은 필수로 요구하지 않는다. 초기 배포는 내부 검증용이다. 설계 승인은 성능 실측 합격이나 최소사양 보장이 아니며 개발 착수도 별도다. 별도 개발 착수 지시 전에는 prototype, dependency 설치, R0 구현과 EM 실행을 시작하지 않는다. 착수 지시 이후에 문서와 수식을 기준으로 smallest end-to-end 사례를 실행한다. 제품 전체 UI를 만든 다음 해석, 출력을 나중에 붙이는 순서로 진행하지 않는다. GUI 없이 같은 domain command로 생성, 저장, STEP, 해석, 결과, 검증을 돌릴 수 있어야 GUI 오류와 물리 오류를 분리할 수 있다.

미결 항목은 [25번 미결 항목 처리 기준](25_RFAD_문서_검토와_승인.md#remaining-decision-policy)에 따라 처리한다. 실제 CPU/GPU, runtime 버전, IFA 실제 물성과 측정 장비 등은 개발 중 담당자가 구체화하고 해당 시험/제작/측정/배포 전에 고정한다. 모든 실물 조건을 확보해야 데이터/GUI/CAD 개발을 시작할 수 있는 것으로 해석하지 않는다. 채택된 성능/기능 목표 변경이나 외부 배포는 별도 결정으로 관리한다.

구현 단계는 R0/R1/R2/R3이고 실제 일정, 인력, 해석 runtime은 이 문서에서 임의로 산정하지 않는다. [통합 요구](03_RFAD_사용자_요구사항.md)의 core stage와 개별 강화 clause의 stage를 함께 따른다.

## 2. 작업 분해

| WBS | 작업과 산출물 | 선행 | 완료 증거 |
| --- | --- | --- | --- |
| WBS-001 | 현존 원본 B/보존 요구/최종문서/수식/추적표 검토, issue register. 원본 A 원문 감사는 회복 시 병행 | 없음 | 128 B mapping/141 canonical 요구/수식 정의역 누락 검사 결과. 원본 A의 미확인 계보와 영향 범위 별도 기록 |
| WBS-002 | R0 Linux native/headless worker 및 R1 Windows 11 x64/local WSL2 runtime doctor와 dependency lock | 001 | actual version/binary hashes/한국어 path/worker smoke. Linux GUI 수용과 별도 |
| WBS-003 | canonical unit, expression, entity, snapshot schema | 001 | dimension/cycle/roundtrip/atomic save fixture |
| WBS-004 | 원호/IFA semantic graph와 connectivity | 003 | G031 geometry fixture + intended short/open cases |
| WBS-005 | physical stackup/copper/via CAD projection | 002,004 | thin copper/annular via/slot/body map tests |
| WBS-006 | 2D/PDF/SVG/DXF + STEP writer와 independent reopen | 005 | tauCAD/tau2D, topology, thickness 보고 |
| WBS-007 | openEMS input/mesh/port/normalization adapter | 002,003 | native artifacts + known port/power convention tests |
| WBS-008 | 완전한 참조 계산 사례의 전력/방사/수렴 검증 후 21의 초기 기준과 필수 물리 입력을 갖춘 단일포트 IFA, 이어 R1 원호 검증 | 007. 참조 사례 통과 후 첫 제품 사례 진행 | 실제 해석과 mesh/boundary/time evidence. 가정 입력과 실물 근거를 구분하고 IFA/원호를 각각 검증. G031 기하 시험과 분리 |
| WBS-009 | normalized S/power/field, metric/assessment | 007,008 | EQ reference vectors + raw/derived cache distinction |
| WBS-010 | KiCad/CAM import/export/DRC 및 roundtrip | 004,006 | editable net geometry + independent Gerber comparison |
| WBS-011 | R1 C++ wxMSW GUI shell/2D/3D/state/error와 local WSL2 worker 통합 검증 | D0 승인 완료, 별도 개발 착수 지시, 003의 계약. 실제 연동은 004~009 | 24번 GUI-SPIKE-001~007/PERF 초기 목표, 일반 편집 60 fps/대형 장면 30 fps, headless 동등 결과, save/cancel/stale |
| WBS-012 | material/reference importer와 source promotion | 003 | structured snapshot counts/flags/conflicts 유지 |
| WBS-013 | R1 기본 VNA 파일 입력/동일 기준면 비교, 교정/케이블/fixture/환경/반복 조건 기록과 explicit sweep | 009 | raw 보존, 조건 차이, 후보 실패 처리, 비교에 쓴 불확도 근거/판정 규칙. R1 기본 측정 검증을 R2 전문 기능에 의존시키지 않음 |
| WBS-014 | R1 Windows 11 x64 wxMSW/local WSL2 integration/recovery 및 내부 검증용 package | 006~013 | 필수 R1 VT 통과, 원호/IFA 단일포트 및 2D/STEP/CAM 검증, 미검증 profile 차단 |
| WBS-015 | dispersion/advanced port/multiport field basis | R1 | GAP-004/013 및 n-port 검증 |
| WBS-016 | UWB/MIMO, complex network/loaded field | 015 | GAP-014/015, pair/ECC/phase 기준군 |
| WBS-017 | 자동, Pareto 최적화/공차/정합 합성/BOM | 013,015 | budget/seed/failures/constraints/selected-candidate 재검증 |
| WBS-018 | R2 OTA 전문 처리/불확도 분석 기능/독립 모델 보정 | 009,013 및 해당 물리 기능. UWB/MIMO 전용 subcase만 016 추가 | measurement trace, holdout, uncertainty evidence. R1 기본 측정/불확도 근거 기록은 013과 해당 R1 VT에서 수행 |
| WBS-019 | NFC/RFID/flex/body/array 전문 plugin | R2 해당기반 | 각 물리영역 전용 검증과 capability profile |
| WBS-020 | remote/HPC/추가solver/inverse/AI/장비연결 | 관련 R2/R3 | adapter contract, dataflow, 비지원 처리, 재현성 |

WBS 숫자 순서가 엄격한 직렬 일정은 아니다. 원본 A가 현재 없다는 이유만으로 WBS-001 및 모든 후속 작업을 중단하지 않는다. 현존 문서의 요구/AC와 원본 B를 기준으로 검사하고 원본 A의 완전성은 미확인 상태로 추적한다. 선행이 분리된 CAD writer와 solver adapter는 병행할 수 있다. 단, 공통 unit/frame/phasor/schema 계약을 임의로 다르게 구현하면 안 된다.

Linux desktop wxGTK GUI는 후속 출시 범위이며 출시 버전은 아직 정하지 않았다. WBS-002의 Linux worker 기본 계산 검증은 R0에서 유지하고, 후속 wxGTK GUI 통합/배포 수용은 별도 작업 범위로 추적한다. 이를 자동으로 R2에 배정하거나 R1 Windows 완료 조건에 포함하지 않는다.

## 3. R0 종료 기준

- Linux native/headless worker의 의존성 버전을 실제 환경에서 고정하고 doctor와 기본 계산을 검증한다. Windows host/local WSL2 경로도 별도 증거를 남기며, worker 검증을 Linux GUI 제품 수용으로 표시하지 않는다.
- 원호의 좌표/width/endpoint/source grid와 units를 재현한다.
- thin copper, via/slot가 STEP에서 재열린다. writer 그림만으로 통과하지 않는다.
- known port/power/field fixture로 native normalization과 domain RMS 변환을 검증한다.
- 최소 방사체에서 실제 openEMS 결과, mesh/boundary/time 변화 데이터를 생성한다.
- source formula와 구현식의 부호, 단위, 가정을 audit하고 차이를 기록한다.

R0의 형상 검증 예제는 G031이다. 실제 RF 검증은 입력과 독립 기대 근거가 완비된 참조 계산 사례를 먼저 통과시킨 뒤, 물성이 완비된 단일포트 IFA를 첫 제품 사례로 진행한다. R1 원호 검증도 필수이며 IFA 합격으로 대체하지 않는다. 대역/보드 외형/적층 목표/급전은 [21번 IFA 초기 검증 기준](21_RFAD_사례와_계약.md#ifa-initial-baseline)로 채택했으며 실제 재료 물성, 상세 형상 및 제작/측정 조건을 후속 fixture 명세에 채운다. 명시적 가정을 사용하는 탐색 해석은 실제 보드 검증과 구분하고, 비교 시험은 해당 조건, 불확도 산정 방법과 판정 규칙을 실행 전에 고정하고 실제 측정에서 얻는 수치 근거는 합격 판정 전에 확정한다. G031의 미정 물성에 임의값을 넣은 결과를 원본 비콘의 재현 성능으로 명명하지 않는다.

## 4. R1 완료 기준

Windows 11 x64 wxMSW GUI와 local WSL2 Linux worker에서 사용자가 원호/IFA 단일포트 프로젝트를 만들고 물성, 급전, 환경 조건을 입력한 뒤 실제 해석, 전력/방사 검증과 수렴 상태를 확인하며 같은 revision의 실제 2D/STEP/CAM/결과/보고서를 내보낼 수 있다. 두 형상 모두 R1 검증이 필요하다. 알려진 supported profile에서 반복 가능하고, 실패, 누락, 미지원, 미수렴, stale 결과는 구별된다. 기본 측정 파일과 교정/환경 정보 비교, explicit sweep, 후보/작업 관리가 제공된다. 내부 검증용 배포를 먼저 준비하며 외부 공개, 상용 배포와 소스 공개 방침은 별도 결정으로 남긴다.

필수 결과를 fake JSON이나 미리 계산한 demo로 대신하지 않는다. mock은 단위/UI/계약시험이라는 이름과 출처를 붙이고 실제 analysis run과 분리한다. 데모 결과를 사용해도 snapshot hash와 맞지 않으면 현재 설계 결과로 표시하지 않는다.

## 5. 시험 계층

| 계층 | 대상 | 실행 시점 |
| --- | --- | --- |
| 단위, 수식 | units, expressions, EQ vector, transformations | 변경마다 빠르게 |
| 계약, schema | IDs, API payload, migration, cache dependency, error states | core/adapter 변경 |
| CAD, 파일 | critical geometry, solid/region, import/export/roundtrip | geometry/export 변경 |
| 실제 solver smoke | 설치/준비/실행/port/field 기본 결과 | runtime/adapter 변경 |
| 수렴, 독립 physics | mesh/PML/time/material/power/비교기준 | 기능 승격과 릴리스 |
| 측정 상관 | 실제 제작, 교정, OTA, 응용 성능 | 기준 시제품/환경 준비 후 |
| UI, 운영 | selection, worker, save/cancel/recover, platform | 사용자 흐름 변경과 릴리스 |

CI에서 모든 고비용 EM을 매 수정마다 돌리지 않는다. 변경 영향에 맞는 gate를 선택하고 nightly/release 기준군으로 나눈다. raw cache의 binary/software key를 고정해 구버전 결과로 새 solver 시험을 통과시키지 않는다.

## 6. 개발 산출물의 Definition of Done

각 작업은 연결 requirement/FN/API/EQ/VT IDs, 실제 구현, 필요한 사용자 설명, 조건부 기능표, 의미 있는 검증 결과를 가진다. 함수가 존재하거나 UI 버튼이 눌리는 것만으로 물리 기능 완료로 처리하지 않는다. known limitation은 issue와 capability 상태에 남긴다. 지원 범위 변경은 ADR와 matrix를 갱신하며 미실행 시험을 passed로 적지 않는다.

## 7. 변경 관리

Codex가 더 적합한 기술 선택이나 문서 오류를 발견하면 해당 ADR/수식/계약과 영향을 받는 요구, 화면, 시험을 함께 수정한다. 기존 user-required 2D/STEP/material/EM 조건을 편의상 삭제하지 않는다. 이전 데이터 migration과 결과 무효화 영향도 기록한다. 불확실한 성능 숫자를 정당화하기 위해 수용기준을 몰래 느슨하게 바꾸지 않는다.

## R0 최소 subcase의 명시적 포함

VT-001 geometry, VT-005 단위, VT-006/008 thin copper/via/slot, VT-011 수렴 series, VT-012/021 전력/정규화, VT-020 산술, VT-029 runtime을 포함한다. R0 일부 통과와 R1 전체 제품 수용은 별도다. GUI 기술은 C++ wxWidgets로 확정되었으며 상태는 `selected_pending_validation`이다. GUI-SPIKE-001~007은 기술 후보 선정이 아니라 선택한 기술의 통합/성능 검증 gate다.

## 8. D0 문서 설계와 개발 착수

D0 산출물은 00~22 및 24~25 설계 문서, 23 원문 B, 요구/AC/설계/VT 추적과 미결 결정표다. 현재 폴더에 없는 과거 JSON registry나 실행 기록을 전제로 개발 완료를 선언하지 않는다. R1 Windows 우선 범위, 원호/IFA 단일포트, 첫 검증 순서, 내부 검증용 배포 및 24번 PERF-001~010/기준 host/fixture의 초기 목표 채택은 확정 사항이다. 최초 IFA의 대역/외형/적층 목표/급전 초기 기준도 채택했다. 정확한 CPU/GPU와 실행 manifest, IFA 실제 재료 물성과 상세 제작/측정 조건, Linux GUI 출시 버전과 외부 배포/소스 공개 방침은 후속 확정한다. 물성 입력 기능의 설계/구현과 실물 검증용 값의 확보는 별도 작업이다. 전체 문서 검토 승인은 완료되었고 개발 착수 지시만 별도로 남는다.

개발 착수 후 WBS-003의 최소 protocol/DTO가 생기면 WBS-011 wxWidgets 통합 prototype을 CAD/solver 작업과 병행할 수 있다. UI-only 측정과 실제 backend 포함 측정을 분리한다. 일반 편집과 대형 장면의 fixture 및 frame 판정은 24번에서 관리하고 idle 상태의 60 fps 강제 redraw loop는 금지한다. Avalonia 비교 구현은 현재 작업에 포함하지 않으며 Qt로 자동 대체하지 않는다. 유료 GUI 부품을 필수로 요구하지 않는 기본 구성은 유료 부품의 모든 사용 금지나 제품 무료 배포 결정과 구별한다.

WBS별 상태는 planned/active/blocked/done, 증거는 not_run/passed/failed/inconclusive로 분리한다. D0 기준선 승인/문서 정합성 검사는 완료 기록으로 보존한다. WBS-001의 착수 시 실제 저장소/환경 재확인과 WBS-002~020의 제품 구현/시험은 아직 planned다. 문서 승인으로 제품 WBS를 done으로 올리지 않는다. 승인 대상과 잔여 gate는 [25번](25_RFAD_문서_검토와_승인.md)을 따른다.
