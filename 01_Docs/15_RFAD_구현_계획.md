# 개발 순서, 작업 분해, 완료 조건

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

## 1. 개발 방식

현재는 D0 문서 설계 단계다. 사용자 검토와 개발 착수 지시 전에는 prototype, dependency 설치, R0 구현과 EM 실행을 시작하지 않는다. 승인 이후에 문서와 수식을 기준으로 smallest end-to-end 사례를 실행한다. 제품 전체 UI를 만든 다음 해석, 출력을 나중에 붙이는 순서로 진행하지 않는다. GUI 없이 같은 domain command로 생성, 저장, STEP, 해석, 결과, 검증을 돌릴 수 있어야 GUI 오류와 물리 오류를 분리할 수 있다.

구현 단계는 R0/R1/R2/R3이고 실제 일정, 인력, 해석 runtime은 이 문서에서 임의로 산정하지 않는다. [통합 요구](03_RFAD_사용자_요구사항.md)의 core stage와 개별 강화 clause의 stage를 함께 따른다.

## 2. 작업 분해

| WBS | 작업과 산출물 | 선행 | 완료 증거 |
| --- | --- | --- | --- |
| WBS-001 | 두 baseline/최종문서/수식/추적표 검토, issue register | 없음 | 128 B mapping/141 canonical 요구/수식 정의역 누락 검사 결과 |
| WBS-002 | runtime doctor와 Linux/Windows-WSL dependency lock | 001 | actual version/binary hashes/한국어 path/worker smoke |
| WBS-003 | canonical unit, expression, entity, snapshot schema | 001 | dimension/cycle/roundtrip/atomic save fixture |
| WBS-004 | 원호/IFA semantic graph와 connectivity | 003 | G031 geometry fixture + intended short/open cases |
| WBS-005 | physical stackup/copper/via CAD projection | 002,004 | thin copper/annular via/slot/body map tests |
| WBS-006 | 2D/PDF/SVG/DXF + STEP writer와 independent reopen | 005 | tauCAD/tau2D, topology, thickness 보고 |
| WBS-007 | openEMS input/mesh/port/normalization adapter | 002,003 | native artifacts + known port/power convention tests |
| WBS-008 | canonical radiation fixture + mesh/boundary/time study | 007 | 실제 해석과 수렴 evidence. geometry-only fixture와 분리 |
| WBS-009 | normalized S/power/field, metric/assessment | 007,008 | EQ reference vectors + raw/derived cache distinction |
| WBS-010 | KiCad/CAM import/export/DRC 및 roundtrip | 004,006 | editable net geometry + independent Gerber comparison |
| WBS-011 | wxWidgets/Avalonia 동등 비교 후 GUI shell/2D/3D/state/error | D0 승인, 003의 계약. 실제 연동은 004~009 | 24번 GUI-SPIKE-001~007/PERF, headless 동등 결과, save/cancel/stale |
| WBS-012 | material/reference importer와 source promotion | 003 | structured snapshot counts/flags/conflicts 유지 |
| WBS-013 | measurement import/basic alignment + explicit sweep | 009 | raw 보존, 조건차이표시, 후보실패처리 |
| WBS-014 | R1 integration/recovery/package/Windows flow | 006~013 | 필수 R1 VT 통과, 미검증 profile 차단 |
| WBS-015 | dispersion/advanced port/multiport field basis | R1 | GAP-004/013 및 n-port 검증 |
| WBS-016 | UWB/MIMO, complex network/loaded field | 015 | GAP-014/015, pair/ECC/phase 기준군 |
| WBS-017 | 자동, Pareto 최적화/공차/정합 합성/BOM | 013,015 | budget/seed/failures/constraints/selected-candidate 재검증 |
| WBS-018 | OTA/uncertainty/independent model calibration | 013,016 | measurement trace, holdout, uncertainty evidence |
| WBS-019 | NFC/RFID/flex/body/array 전문 plugin | R2 해당기반 | 각 물리영역 전용 검증과 capability profile |
| WBS-020 | remote/HPC/추가solver/inverse/AI/장비연결 | 관련 R2/R3 | adapter contract, dataflow, 비지원 처리, 재현성 |

WBS 숫자 순서가 엄격한 직렬 일정은 아니다. 선행이 분리된 CAD writer와 solver adapter는 병행할 수 있다. 단, 공통 unit/frame/phasor/schema 계약을 임의로 다르게 구현하면 안 된다.

## 3. R0 종료 기준

- 의존성 버전을 실제 환경에서 고정하고 doctor가 성공한다. Windows host 지원을 목표로 한다는 사실과 실제 지원 통과를 구별한다.
- 원호의 좌표/width/endpoint/source grid와 units를 재현한다.
- thin copper, via/slot가 STEP에서 재열린다. writer 그림만으로 통과하지 않는다.
- known port/power/field fixture로 native normalization과 domain RMS 변환을 검증한다.
- 최소 방사체에서 실제 openEMS 결과, mesh/boundary/time 변화 데이터를 생성한다.
- source formula와 구현식의 부호, 단위, 가정을 audit하고 차이를 기록한다.

R0의 형상 검증 예제는 G031, 실제 RF 검증은 적층, 급전, 재질, 환경이 완비된 별도의 기준 구조를 쓴다. G031의 미정 물성에 임의값을 넣은 결과를 원본 비콘의 재현 성능으로 명명하지 않는다.

## 4. R1 완료 기준

사용자가 원호 또는 IFA 프로젝트를 만들고 조건을 입력한 뒤 실제 해석과 수렴 상태를 확인하며 같은 revision의 2D/STEP/CAM/결과/보고서를 내보낼 수 있다. 알려진 supported profile에서 반복 가능하고, 실패, 누락, 미지원, 미수렴, stale 결과는 구별된다. 기본 측정 파일과 교정/환경 정보 비교, explicit sweep, 후보/작업 관리가 제공된다.

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

VT-001 geometry, VT-005 단위, VT-006/008 thin copper/via/slot, VT-011 수렴 series, VT-012/021 전력/정규화, VT-020 산술, VT-029 runtime을 포함한다. R0 일부 통과와 R1 전체 제품 수용은 별도다. GUI-SPIKE가 완료되기 전 GUI 기술 선택은 candidate 상태다.

## 8. D0 문서 설계와 개발 착수

D0 산출물은 00~22 및 24~25 설계 문서, 23 원문 B, 요구/AC/설계/VT 추적과 미결 결정표다. 현재 폴더에 없는 과거 JSON registry나 실행 기록을 전제로 개발 완료를 선언하지 않는다. 사용자가 검토할 결정은 GUI 비교 기준, R1 플랫폼/범위, 성능 예산과 시험 자원이다.

개발 착수 후 WBS-003의 최소 protocol/DTO가 생기면 WBS-011 비교 prototype을 CAD/solver 작업과 병행할 수 있다. UI-only 측정과 실제 backend 포함 측정을 분리한다. 선택 전 두 완성 GUI를 중복 개발하지 않으며 선정 후 한쪽을 제품 경로로 고정한다.

WBS별 상태는 planned/active/blocked/done, 증거는 not_run/passed/failed/inconclusive로 분리한다. 이 문서의 모든 WBS는 실행 증거가 첨부되기 전 planned다. 승인 대상과 잔여 gate는 [25번](25_RFAD_문서_검토와_승인.md)을 따른다.
