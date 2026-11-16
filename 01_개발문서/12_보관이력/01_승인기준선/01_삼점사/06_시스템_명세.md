# 시스템 명세와 동작 계약

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

## 1. 경계와 규범

입력은 사용자 목표, 파라미터 그래프, PCB 적층/동박, 재질, 급전, 정합, 환경, 수치 조건, 원문/실측 데이터다. 출력은 버전 있는 설계, 2D 기술 도면/벡터, STEP, EDA/CAM, 원시/파생 해석 결과, 검증 기록과 인계 package다. 사용자의 RF 칩 내부 설계나 전체 회로 CAD, 무선 인증 자동 판정은 본 제품의 완료 기준이 아니다.

아래 `SYS-*`는 제품 요구를 구현하기 위한 계약이다. 사용자 요구의 기준 ID는 [통합 요구사항](03_RFAD_사용자_요구사항.md)에 있고 연결은 [추적표](17_RFAD_요구사항_추적표.md)에서 관리한다.

## 2. 입력, 설계 계약

| ID | 시스템 동작 | 성공, 실패 조건 |
| --- | --- | --- |
| SYS-001 | 입력값을 단위가 있는 값/표현식/열거형/참조로 해석 | 차원 오류, 미정 변수, 순환 참조에 오류 위치를 반환. 입력 중 임시 문자열과 저장 가능한 확정값을 구분 |
| SYS-002 | 모든 도체, 층, 포트, source에 stable ID 부여 | 이름 변경이나 CAD 재생성으로 의미 연결이 바뀌지 않음 |
| SYS-003 | 편집 명령을 transaction으로 적용 | 검증된 patch를 한 번 commit하거나 전체 rollback. undo/redo는 같은 도메인 명령 이력 사용 |
| SYS-004 | 원호, line, polygon 원본과 physical cross-section 유지 | 중심선, 경계, 투영, 전기적 길이를 다른 값으로 표시. 합집합된 도체의 경로 길이를 임의 단순 합하지 않음 |
| SYS-005 | 도체 연결과 expected net graph를 비교 | 의도적 gap, floating conductor와 끊어진 feed를 구분. cross-layer 연결에는 유효 via/contact 필요 |
| SYS-006 | 층별 위/아래 경계와 두께 정의 | 물리 stackup과 z-coordinate 일치. base/finished copper, mask, plating을 분리 |
| SYS-007 | material version을 프로젝트에 고정 | library update가 기존 설계의 수치를 자동 변경하지 않음. 변경 선택 시 영향을 보고 |
| SYS-008 | 근사, 생략 목록을 별도 projection metadata에 기록 | physical model을 변경해 solver 지원한 것처럼 표시하지 않음 |
| SYS-009 | import를 preview와 commit으로 분리 | 누락 layer/net/unit/port/material을 보완하기 전 의미가 필요한 연산은 차단 |
| SYS-010 | geometry constraint와 제조 constraint를 별도 검사 | 유효한 CAD라고 제조 가능한 것이 아님. 최소 갭/선폭 설정이 없으면 해당 DRC는 미평가 |

## 3. 실행 계약

| ID | 시스템 동작 | 성공, 실패 조건 |
| --- | --- | --- |
| SYS-011 | solver별 capability와 tested envelope 조회 | `declared`, `implemented`, `verified`, `unsupported`, `unknown`을 구분. 문서 출처와 fixture evidence는 별도 필드. library 입력란 존재만으로 지원 표시 금지 |
| SYS-012 | 저장한 snapshot에서만 계산 | 편집 중인 상태가 실행 입력에 섞이지 않음. 현재 revision과 job snapshot은 항상 별도 표시 |
| SYS-013 | plan에서 모델/mesh/observables/resource를 확정 | mesh cell 수, 예상 RAM/disk는 추정식과 calibration 상태를 표시 |
| SYS-014 | solver input과 environment manifest를 보존 | 실행 명령은 허용 executable과 argv로 구성. secret은 로그에 기록하지 않음 |
| SYS-015 | 실제 solver/adapter 종료 이유를 기록 | exit code 0과 수렴/정확도/목표 충족을 동일 상태로 사용하지 않음 |
| SYS-016 | 원시 결과를 atomic publish | partial 파일을 final manifest에 올리지 않음. 완료 후 파일 hash/shape/축/단위 검사 |
| SYS-017 | 취소를 요청/확인 상태로 구분 | cancel_requested를 즉시 UI에 표시, worker 확인 후 cancelled. 미지원 checkpoint 재개 버튼 비활성 |
| SYS-018 | 실패, 재시작 시 원설계와 완료결과 유지 | 중단된 디렉터리는 격리, 재실행은 새 run ID. 자동 덮어쓰기 금지 |
| SYS-019 | raw EM 결과와 파생 계산 캐시 분리 | 외부 네트워크, 목표 변경별 최소 재계산. 미충분한 원시 관측값에서 field를 조작 생성하지 않음 |
| SYS-020 | 계산 실패를 최적화 penalty와 별도 기록 | invalid_geometry, unsupported, numerical_failure, timeout 구별; 실패 후보는 feasible 최적해가 아님 |

## 4. 결과 계약

| ID | 시스템 동작 | 성공, 실패 조건 |
| --- | --- | --- |
| SYS-021 | S, Z, Y 데이터에 파 정의, Z0, 포트 순서 저장 | 복소 Z0와 real Z0 공식을 혼용하지 않음. 변환 singular면 status와 masked samples 반환 |
| SYS-022 | field에는 크기, 위상, 좌표, 편파, 여기, 정규화 저장 | 절대 scale 검증 전 power/gain 추정 완료 표시 금지 |
| SYS-023 | 성능 평가와 target 판정을 분리 | 목표 미입력/미평가 주파수/미수렴을 pass로 표시하지 않음 |
| SYS-024 | band crossing을 표시할 때 보간 정보를 보존 | sampled pass와 entire-band certified 같은 표현을 구분. 좁은 공진을 놓칠 가능성은 adaptive verification으로 검사 |
| SYS-025 | multiport에서는 종료 조건과 구동벡터를 포함 | 서로 다른 Z0/종단/여기/field basis를 조용히 결합하지 않음 |
| SYS-026 | UWB 전달 평가는 Tx/Rx와 reference plane을 요구 | S11만으로 group delay, fidelity, 거리 정확도를 생성하지 않음 |
| SYS-027 | 실측은 원본과 처리본을 분리 | 교정/port extension/de-embedding/renormalization/축 변환 이력 순서 보존 |
| SYS-028 | 모델 보정에 사용한 데이터와 검증 데이터 분리 | fitting 오차를 독립 정확도 증거로 재사용하지 않음 |

## 5. 출력, 저장 계약

| ID | 시스템 동작 | 성공, 실패 조건 |
| --- | --- | --- |
| SYS-029 | output profile을 실행 전에 고정 | layer/body/net/hole/단위/원점/정밀도/생략/merge 조건을 공개 |
| SYS-030 | drawing와 fabrication vector를 별도 생성 | 용지 축척과 1:1 CAD 형상 구분. 도면 치수는 편집 모델에서 계산 |
| SYS-031 | STEP에는 positive-thickness copper와 substrate를 사용 | 제조 profile에서 표시용 부풀림, 임의 via fill 금지. unsupported feature를 보고 |
| SYS-032 | STEP sidecar와 파일 자체를 hash로 결합 | 같은 basename만으로 물성을 잘못 붙이지 않음. 객체 UUID<->assembly/body mapping 보존 |
| SYS-033 | EDA 도체에는 net/layer/편집 의미를 보존 | decorative graphic으로만 그린 패턴은 editable-copper 요구 미충족 |
| SYS-034 | CAM 파일을 재파싱해 RF critical geometry 비교 | 미러링, 양자화, 원호 근사, hole, net connectivity 검사 |
| SYS-035 | archive의 manifest와 실제 파일 집합 일치 | 상대경로, 크기, hash, 라이선스, 미포함 자료 참조 확인 |
| SYS-036 | project save는 temp+검증+atomic replace | 실패 시 기존 파일 유지, recovery copy 기록. Windows filesystem semantics는 실제 시험 |
| SYS-037 | schema migration은 copy-on-write | 구버전 원본, 변환기 버전, 차이보고서 보존. 최신 변환이 실패하면 읽기 전용으로 열기 |

## 6. 상태 머신

### 6.1 JobState

작업 종류마다 실제 수행하는 단계를 사용한다. 다음 표는 성공 경로이며 해당하지 않는 단계를 가짜 진행률로 표시하지 않는다.

| 종류 | 성공 경로 |
| --- | --- |
| em_prepare | draft -> validating -> planned -> queued -> preparing -> completed |
| em_analysis, solve_and_postprocess | draft -> validating -> planned -> queued -> running -> postprocessing -> completed |
| em_analysis, postprocess_only | draft -> validating -> planned -> queued -> postprocessing -> completed |
| cad_build/export/study/data_processing | draft -> validating -> planned -> queued -> running -> completed. 실제 후처리 시 postprocessing 추가 |

API-012는 AnalysisPlan에서 em_prepare TaskRef를 만들고, 완료 산출물로 PreparationArtifact와 PreparedPlan을 게시한다. API-013의 em_analysis에는 PreparedPlan이 필요하다. 준비 완료와 EM 완료는 서로 다른 job 및 artifact type이다.

활성 상태에서 failed로 종료할 수 있다. queued를 포함한 취소 가능 상태에서는 cancel_requested를 즉시 저장하고, 실제 native 자식 프로세스 트리의 종료 또는 미시작 queue 제거 확인 후 cancelled로 끝낸다. completed/failed/cancelled/interrupted는 terminal이다. 프로세스 사망이나 재접속 실패로 실행 여부를 확인하지 못하면 interrupted와 마지막 확인 시각을 보존하며 임의 성공/취소를 만들지 않는다. interrupted의 outcome_unknown인 native job는 자원 예약과 lease를 유지한다. fencing은 stale 결과 게시를 막을 뿐 실제 실행 종료를 뜻하지 않는다. 실제 guest process group 종료와 reader lease 해제 확인 전에는 자원 예약 반환, 중복 재실행, 재개와 artifact 정리를 허용하지 않는다.

취소 요청과 완료가 경합하면 coordinator가 최초로 durable commit한 terminal 상태를 유지하고 늦은 요청에 그 상태를 반환한다. 진행 알림은 terminal 상태를 되돌릴 수 없다. 재개 가능성은 별도 resume_eligibility=unsupported/eligible/ineligible로 기록한다. 유효한 checkpoint가 있어도 원래 run을 수정하지 않고 새 run과 parent_run_id를 생성한다.

completed는 요구된 산출물의 게시 완료다. 수렴, 물리 정확도, 목표 합격은 아래 독립 상태로 판단한다. transport 연결 끊김과 결과 stale도 JobState가 아니다.

### 6.2 독립된 결과 상태

| 축 | 값 예시 | 다른 축과 독립인 이유 |
| --- | --- | --- |
| 실행 | completed/failed/cancelled/interrupted | solver가 끝나도 목표가 맞는 것은 아님 |
| 모델 대응 | current/stale/compatible_reuse/orphaned | 과거 결과를 삭제하지 않고 현재 적용 가능성만 판단 |
| 수치 검증 | untested/passed/failed/inconclusive | mesh, boundary, termination 비교가 별도 필요 |
| 물리 진단 | untested/passed/failed/inconclusive | power balance, passivity, convention 검증 |
| 목표 판정 | pass/fail/not_evaluated/conditional | 선택 target profile과 평가 범위에 종속 |
| 근거 수준 | seed/literature/simulated/converged/measured | 각 승격에 증거가 필요 |
| 출력 검사 | preview_only/generated_unverified/verified_profile/failed | 파일 생성과 독립 재열기를 구분 |

### 6.3 입력 상태

`user_entered`, `source_default`, `estimated`, `missing`, `not_applicable`, `unsupported`, `conflicting`를 사용한다. 상태는 값이 사용되는지와 별도다. 예를 들어 추정값으로 실행한 결과는 `estimated` 흔적이 유지되며, 미지원 tensor를 저장해도 scalar 계산에 몰래 반영하지 않는다. 잠정 값 사용은 프로젝트 내 명시적 선택과 provenance를 남기고 매번 대화형 승인을 요구하는 기능으로 만들지 않는다.

## 7. 오류 계약

모든 오류는 `{code, severity, message_ko, entity_ids, field_paths, details, suggested_actions, recoverable}`를 갖는다. 문자열 로그만 반환하지 않는다. `blocking`, `warning`, `info`를 구분한다. 아래 symbolic code는 RPC `error.data.domain_code`에 들어간다.

| 코드 | 의미 | 기본 복구 |
| --- | --- | --- |
| E_SCHEMA / E_VERSION | 구조 또는 호환 버전 불일치 | 읽기 전용 열기/지원 migration 안내 |
| E_UNIT / E_EXPR_CYCLE | 차원/표현식 오류 | 해당 필드 위치와 참조 cycle 반환 |
| E_GEOMETRY / E_CONNECTIVITY | 무효 shape/단선/단락 | 객체 선택, 오류 경계 표시 |
| E_MATERIAL_UNKNOWN / E_MATERIAL_RANGE | 해당 계산의 필수 물성 미정/유효대역 이탈 | 사용자 명시 입력/자료 선택 또는 지원 범위의 모델로 수정. 명시적 가정은 실제 재료 검증과 구분 |
| E_UNSUPPORTED | adapter 미지원 | 지원 alternative와 변경 영향 제시 |
| E_PORT / E_REFERENCE_PLANE | 급전/기준면 정의 오류 | 매핑 보완 또는 profile 변경 |
| E_RESOURCE / E_DISK | 자원 부족 | 추정과 사용량 비교, 실행 예산 수정 |
| E_SOLVER_EXIT / E_DIVERGED | process 실패/수치 발산 | 원본 로그와 실행 입력 보존 |
| E_NORMALIZATION / E_SINGULAR | 규약 미확정/특이 계산 | 값 masking, 원인, 대체 검증 |
| E_MISSING_ARTIFACT / E_HASH | 누락/파일 손상 | 참조 복원; fake result 생성 금지 |
| E_EXPORT_LOSS / E_ROUNDTRIP | 출력 정보 유실/형상 불일치 | profile 수정 후 새 export |
| E_CURSOR_EXPIRED | 보존 범위를 지난 event cursor | 전체 job state와 새 cursor로 재동기화 |
| E_IDEMPOTENCY_EXPIRED | 만료된 request_key | 이전 작업 조회 후 새 명령 여부 결정, 자동 중복 접수 금지 |
| E_CONFLICT | 낙관적 revision 충돌 | 최신 revision 재읽기 후 명령 재적용 |

## 8. 성능과 자원

성능 예산의 단일 기준은 [24번](24_RFAD_GUI_선정과_성능_설계.md)이며 PERF-001..010과 현재 기준 host/fixture를 초기 목표로 채택했다. 기준 host는 Windows 11 x64, 물리 4코어 이상, RAM 16 GiB, SSD, 내장 GPU, 1920x1080이다. 정확한 CPU/GPU/driver 등은 실행 manifest에서 고정하며 초기 목표 채택은 실측 합격이나 최소 사양 보장이 아니다. UI 입력 반응, 작업 접수 ACK, native 완료, cold/warm 시작, private commit/working set/GPU를 따로 측정한다. B의 200 ms는 전체 해석시간이나 모든 이벤트의 일괄 보장값이 아니다.

확정한 C++ wxWidgets GUI의 PERF-006은 연속 조작 중 F1 일반 2D 편집/표 스크롤/일반 3D 100000 triangle에서 60 fps, F2 대형 3D 1000000 triangle에서 30 fps를 목표로 한다. 프레임 시간 p95는 각각 `<=1000/60 ms`, `<=1000/30 ms`이며 fixture와 측정 조건은 24를 따른다. idle redraw를 60 fps로 강제하지 않는다. 자원/지연 예산을 포함한 3.4 설계 기준선은 승인되었으며 실제 성능 검증과 개발 착수는 별도다.

| ID | 계약 | 실패 또는 한계 처리 |
| --- | --- | --- |
| SYS-038 | 모든 긴 IO/CAD/해석/검증/검색은 UI thread 밖에서 수행 | placeholder/progress/cancel 표시. 확정 퍼센트를 모르면 진행 상태만 표시 |
| SYS-039 | 전 프로세스 RAM/CPU/disk admission과 bounded queue | 예산 미충족 작업은 대기 또는 E_RESOURCE. 숨은 병렬 실행 금지 |
| SYS-040 | cache/worker/GPU 수명과 메모리 회수 | LRU/idle 종료, 고정된 peak 예산. 물리 정확도를 몰래 축소하지 않음 |
| SYS-041 | 상태 event seq와 terminal 결과의 재조회 | cursor가 retention 밖이면 full state+새 cursor, stale GUI는 재동기화 |
| SYS-042 | 자동저장/복구와 사용자 확정 저장의 구분 | autosave로 immutable snapshot/run을 덮어쓰지 않음 |
| SYS-043 | 프로젝트 및 결과 삭제는 참조 graph와 active lease 검사 | 사용 중 artifact 삭제 차단. 정리 대상/크기 표시 후 명시적 명령으로 수행 |

모델별 solver 메모리 추정은 calibration 여부와 오차를 표시한다. 실행 예상보다 메모리가 커지면 미리 정한 취소/정리 정책을 적용한다. CPU/GPU/플랫폼 결과는 물리량별 허용오차로 검증하고 bit-identical 여부는 별도다.

## 9. 규범 문서 연결

- 세부 사용자 작업: [UI 설계](05_RFAD_화면과_사용자_경험_설계.md), [기능 설계](06_RFAD_기능_설계.md).
- 저장과 계약: [데이터 명세](08_RFAD_데이터_모델과_파일_형식.md), [solver 계약](11_RFAD_해석기_어댑터_계약.md).
- 연산: [수식](09_RFAD_수식과_물리_모델.md), [파이프라인](10_RFAD_연산_파이프라인.md).
- 검증: [수용시험](14_RFAD_검증과_수용_기준.md).

이 장의 상태, 오류, transaction, cache 방침은 본 제품의 설계 결정이다. 외부 표준의 요구와 동일하다고 주장하지 않는다. JSON-RPC message envelope만 [공식 2.0 규격](https://www.jsonrpc.org/specification)을 따른다.

## 물성 입력과 최초 IFA 기준의 상태

물성 미정은 프로젝트 저장과 기하 편집 자체의 오류가 아니다. 해당 계산에 필요한 값이 빠졌을 때 준비/실행을 차단하며, FR-4 명칭이나 최초 IFA 치수로 유전율/손실을 자동 생성하지 않는다. 사용자가 명시한 가정값으로 필수 입력을 완비하면 지원 범위에서 탐색할 수 있으나 실물과 일치하거나 measured라고 표시하지 않는다. 상세 상태와 provenance는 [08번 데이터 모델](08_RFAD_데이터_모델과_파일_형식.md), 사용자 채택 초기 조건과 남은 실물 입력은 [21번 IFA 초기 검증 기준](21_RFAD_사례와_계약.md#ifa-initial-baseline)을 따른다.
