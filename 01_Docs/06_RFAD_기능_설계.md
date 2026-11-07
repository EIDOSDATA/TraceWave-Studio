# RFAD 06 - 기능 상세 설계

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

관련 문서: [요구사항](03_RFAD_사용자_요구사항.md), [UI](05_RFAD_화면과_사용자_경험_설계.md), [아키텍처](07_RFAD_소프트웨어_아키텍처.md), [데이터 모델](08_RFAD_데이터_모델과_파일_형식.md), [수학, 물리](09_RFAD_수식과_물리_모델.md), [계산 파이프라인](10_RFAD_연산_파이프라인.md), [solver 계약](11_RFAD_해석기_어댑터_계약.md), [CAD, EDA 출력](12_RFAD_도면과_제조_파일_출력.md), [최적화, 측정](13_RFAD_최적화와_측정.md), [검증](14_RFAD_검증과_수용_기준.md).

이 문서는 46개 기능의 입력, 검사, 처리, 출력, 실패와 무효화 계약을 정의한다. 각 기능은 구현할 서비스 책임이며 실행된 기능이 아니다. API ID의 현 계약은 [RFAD 11](11_RFAD_해석기_어댑터_계약.md), 데이터 형식은 [RFAD 08](08_RFAD_데이터_모델과_파일_형식.md), 식의 적용 조건과 정규화 규약은 [RFAD 09](09_RFAD_수식과_물리_모델.md)가 관리한다. 현재 없는 별도 JSON 레지스트리를 구현 또는 검증 증거로 사용하지 않는다.

## 1. 공통 계약

### 1.1 명령, 조회, 장시간 작업의 경계

1. GUI와 CLI는 동일한 도메인 명령을 호출한다. UI 위젯이나 Python 실행 문자열을 영구 설계 데이터로 저장하지 않는다.
2. 편집 명령은 대상 project, base revision, entity UUID, typed values, source/provenance, command ID를 받는다. 수치 저장은 SI와 rad, 단위와 입력식을 보존한다. 최신 revision과 다르면 충돌을 반환하고 조용히 덮어쓰지 않는다.
3. `project.apply_command`는 검증, 도메인 변경, 의존성 영향 계산, undo 정보 기록을 한 트랜잭션으로 수행한다. CAD build, mesh, 해석, export는 별도 파생 작업이다.
4. 장시간 실행은 불변 snapshot과 계획을 소비한다. 성공 응답은 작업 접수 또는 파일 생성의 성공일 수 있으므로 결과의 수렴, 물리, 목표, 왕복검증을 별도 필드로 반환한다.
5. worker event는 job ID, 순번, 단계, 시각, 실제 진척, 로그 참조를 가진다. 순서가 늦게 도착한 event가 완료된 작업을 실행 중으로 되돌리지 않게 한다. 상세 envelope는 API 계약을 따른다.
6. 파일 생성은 임시 위치에서 완료, 검사한 뒤 manifest와 함께 확정한다. 실패한 파일은 완성된 산출물 목록으로 승격하지 않는다.

각 FN의 **출력**은 도메인 처리의 최종 결과를 설명한다. 호출 시 반환형과 동기/비동기 분류의 규범은 [RFAD 11의 operation 목록](11_RFAD_해석기_어댑터_계약.md#3-operation-목록)이다. 작업형 method는 접수 시 TaskRef를 반환하고, 완료 event의 operation_result와 output refs에서 여기 적힌 결과를 제공한다. 짧은 처리나 cache hit도 동일한 비동기 계약을 유지한다. 동기 조회는 제한된 metadata/페이지 결과를, 동기 원자적 명령은 revision과 변경 참조를 직접 반환한다. 작업 접수/재개는 실제 계산을 기다리지 않고 TaskRef를 반환하며 제어 응답과 notification의 구분도 RFAD 11을 따른다. 한 FN의 여러 API를 모두 같은 반환형으로 해석하지 않는다.

### 1.2 자료와 유효성

논문/제조사 보고값, 계산식 초기값, full-wave raw EM, 파생 네트워크, 대리모델 예측, 실측을 다른 `origin`으로 저장한다. 출처, 파일 hash, 원문 페이지, CAD member, 사용 조건을 추적한다. `미실행`, `미수렴`, `미평가`, `미지원`, `실패`, `해당 없음`은 다른 상태다. 없는 값을 0이나 합격으로 바꾸지 않는다.

모든 결과에는 입력 리비전, 실제 solver definition, 구현/adapter 버전, 주파수, 좌표, port order, Z0, wave definition, 복소/전력 규약과 유효 대역이 필요하다. RMS phasor, 시간 규약 등 내부 표준은 RFAD 09에 따르고 native solver 값은 검증된 변환을 거친다. native 규약이 확인되지 않은 데이터는 추측 변환하지 않는다.

### 1.3 의존성, 캐시 계층

| 계층 | 키를 결정하는 핵심 정보 | 재사용을 깨뜨리는 대표 변경 |
| --- | --- | --- |
| 물리 설계 | semantic graph, 실제 stackup/material snapshot, 환경, 연결 | 치수, 물성, 배치, 물리 부품 |
| CAD/표시 | 물리 설계, CAD profile, tessellation policy | BREP 생성 옵션 또는 표시 mesh 정밀도. 표시 변경은 물리 설계를 바꾸지 않음 |
| solver definition | 실제 변환 형상, 재료, 포트, 경계, excitation basis, monitor, mesh | solver가 소비하는 값 또는 solver/adapter 알고리즘 |
| raw EM | 불변 solver 입력과 실행 환경, 수치 설정 | 위 입력 hash 변경. 파일명, 색, 목표는 포함하지 않음 |
| derived network/field | raw EM IDs, 외부 회로, 부하, 여기, renormalization, 기준면, 처리 버전 | 해당 후처리 조건 |
| metric/판정 | 파생 결과, metric definition, target revision, 수렴/유효성 조건 | 목표, 가중치, 관측 선택, 판정 기준 |
| export/package | 물리 snapshot, 출력 profile, 선택 객체, 도면 설정, 결과/판정 참조 | 포함 범위, 원점, 형식, 검사, 보고서 내용 |

물리 설계가 바뀌었다는 이유만으로 모든 cache를 삭제하지 않는다. 실제 solver 입력이 동일한지와 근사 유효성을 확인해 재사용한다. 반대로 입력 파일의 경로가 같다는 이유로 재사용하지 않는다. 과거 raw EM은 원래 snapshot에 대해 보존한다. 현재 작업 사본에서 `stale`은 연결 상태이며 원본 파일의 손상이 아니다.

**외부 정합 예외:** 고정된 선형 EM 다중포트 모델 바깥의 RLC, 부하, 여기만 변경하고 필요한 복소 basis가 보존되어 있으면 raw EM을 재사용한다. 파생 네트워크와 방사 조합, 전력은 다시 계산한다. 정합 패드, 배선, connector, EM 내부 lumped element, 포트 모델을 바꾸면 별도 solver 입력이며 재해석한다. S만 있으면 impedance/matching은 계산할 수 있어도 임의 새로운 여기의 방사장을 만들어내지 않는다.

### 1.4 실패 계약

각 실패에는 symbolic code, stage, entity/field locator, 사용자 설명, 실제 원인, 가능한 조치, 재시도 가능 여부, 남은 artifact 상태를 담는다. 코드는 [RFAD 04 section 7](04_RFAD_시스템_명세.md)의 단일 사전을 사용하며 예시는 `E_UNIT`, `E_UNSUPPORTED`, `E_GEOMETRY`, `E_CONNECTIVITY`, `E_PORT`, `E_RESOURCE`, `E_SOLVER_EXIT`, `E_NORMALIZATION`, `E_MISSING_ARTIFACT`, `E_ROUNDTRIP`이다. 다음 기능별 문구는 오류 의미를 지정하며 서로 다른 실패를 generic error 한 종류로 축약하지 않는다.

### 1.5 실행, 출력 계약

JobState와 독립 유효성 축은 RFAD 04 section 6을 따른다. `transport_state=connected/disconnected/reconnecting`와 모델 관계 `stale`을 JobState enum으로 저장하지 않는다. 출력 상태는 `ExportStatus=preview_only/generated_unverified/verified_profile/failed`이며 `verified_profile`에는 실제 검증한 profile, reader, 허용오차, 범위가 필요하다.

API-013은 `TaskPlan.kind=em_prepare/em_analysis/cad_build/export/study/instrument_acquisition/data_processing`을 받는다. EM 실행은 의도 설정을 고정한 AnalysisPlan에서 준비를 수행한 후, PreparationArtifact와 실제 native/mesh/consumption을 봉인한 별도 PreparedPlan을 만든다. 새 준비값을 원래 AnalysisPlan에 덧써 hash를 유지하지 않는다. `em_prepare`는 AnalysisPlan을 받아 준비 작업을 수행하고 `em_analysis`만 PreparedPlan을 필수로 받는다. `data_processing`은 import.preview, network.derive, metrics.evaluate, measurement.align 등의 긴 데이터 작업에 사용한다. operation_method와 입력 artifact/version으로 작업을 구분하고 동일 scheduler의 TaskRef, 취소, 상태 계약을 적용한다. EM PreparedPlan은 요구하지 않는다. 다른 작업은 자기 종류의 prerequisites를 검사한다. API 프로토콜 `rfad.api/2.0`과 이 문서의 개정 3.0은 별개 버전이다.

### 1.6 데이터 소유권과 자원 예산

이 절은 DES-URS-004/005의 구현 설계 계약이다. 수치 예산은 RFAD 24의 동일 fixture와 대상 장비에서 사전 고정하며 아래 정책의 존재를 실제 성능 측정으로 보지 않는다.

| 데이터/작업 | 소유권과 전달 | 한도 도달과 해제 |
| --- | --- | --- |
| 편집 명령과 undo | 도메인 서비스가 revision과 명령 기록을 소유한다. GUI는 변경 요약과 필요한 뷰를 유지한다. | undo의 RAM 한도와 디스크 journal/checkpoint 정책을 표시한다. 저장 설계를 캐시처럼 삭제하지 않는다. |
| 물리 BREP와 표시 mesh | CAD worker가 물리 원형을 소유하고 GUI는 revision/hash가 있는 표시 artifact만 받는다. 표시 mesh를 solver나 제조 원본으로 재사용하지 않는다. | 표시 LOD/버퍼 수를 제한하고 오래된 GPU/CPU 버퍼를 해제한다. 차이 검수 전 정밀도를 조용히 낮추지 않는다. |
| S/field/measurement 배열 | 데이터 서비스가 원시 파일과 canonical dataset을 소유한다. GUI에는 dataset ID, shape, dtype, 단위, 축, 유효성, 필요한 slice/chunk만 전달한다. | byte budget과 읽기 범위를 검사한다. JSON에 전체 배열을 싣지 않는다. 미리보기 축소 표본은 수치 판정 원본을 대체하지 않는다. |
| 로그와 진척 이벤트 | 영속 로그와 최종 상태는 worker/coordinator가 소유한다. GUI는 순번을 가진 제한된 창을 조회한다. | 중간 진척은 합칠 수 있으나 최종 상태/오류/취소 확인은 버리지 않는다. 누락 sequence는 snapshot+cursor로 복구한다. |
| 스윕과 병렬 작업 | coordinator가 조합 ID와 입력 hash를 소유하며 후보는 지연 생성한다. | 전체 후보 형상/결과를 RAM에 올리지 않는다. CPU, RAM, 디스크, 출력량 예산과 동시 실행 수를 함께 제한한다. |
| 영속 결과와 재생성 캐시 | 사용자 설계, 측정 원본, 완료 raw 결과는 영속 자산이다. 표시/재생성 캐시에는 별도 key/크기/참조 수를 둔다. | 캐시 제거는 진행 중 작업과 참조 closure를 보호한다. 영속 결과 삭제는 별도 명시 사용자 동작이며 자동 캐시 정리와 합치지 않는다. |

메모리 측정은 GUI만이 아니라 서비스, CAD worker, solver, IPC staging, GPU buffer를 포함한 전체 프로세스 집합을 대상으로 한다. 시작/정상 작업/최대값/작업 종료 후 안정화 값을 구별한다. OOM이나 디스크 부족 시 작은 작업 성공으로 바꿔 표시하지 않고 마지막 저장본과 완료 결과를 보존한다.

### 1.7 요청 취소, 재접속, 오래된 응답

제출 재전송은 동일 request_key와 동일 payload hash일 때 기존 job을 조회한다. 같은 key에 다른 payload가 오면 충돌로 거부한다. request_key의 보존 기간은 job 기록의 유지 정책과 같거나 더 길며 기간이 지난 요청은 자동 재제출하지 않고 사용자에게 새 실행 여부를 보여준다.

조회 응답은 project/revision/dataset/request ID를 포함한다. 사용자가 더 최신 조건으로 이동한 뒤 도착한 응답은 원래 cache에 저장할 수 있으나 현재 뷰를 덮어쓰지 않는다. 화면 조회 취소와 solver 작업 취소를 분리한다. 연결이 끊긴 동안 GUI는 종료를 추정하지 않고 재접속 후 job snapshot과 마지막 수신 sequence 이후 사건을 요청한다.

준비 작업의 기본 전이는 `draft -> validating -> planned -> queued -> preparing -> completed`, EM 실행은 `draft -> validating -> planned -> queued -> running -> postprocessing -> completed`이다. 실패/취소/중단 분기는 RFAD 04의 kind별 전이표를 따른다. 준비 완료와 해석 완료를 같은 결과로 표시하지 않는다. `data_processing`은 공통 접수 검사를 거쳐 `queued -> running -> completed`로 진행하며 필요한 경우 running과 completed 사이에 postprocessing을 둔다.

취소는 접수 확인, cooperative 요청, 정책상 유예, 해당 job이 소유한 프로세스 트리의 종료 확인, 부분 artifact 정리 순서로 진행한다. GUI는 취소 명령을 비동기로 보내며 끝나기 전에 cancelled를 확정하지 않는다. 원격/WSL 경계에서 실제 종료를 확인할 수 없으면 RFAD 04의 interrupted 및 마지막 확인 시각을 보존하고 후속 상태를 조회한다. 실행 여부 미확인을 성공이나 취소로 단정하지 않으며 unknown을 별도 JobState로 추가하지 않는다. 기한과 escalation 정책은 adapter capability 및 사전 합의한 운영 profile에 기록한다.

## 2. 프로젝트, 입력, 자료

<a id="FN-001"></a>
### FN-001 프로젝트 생성, 열기, 마이그레이션

**단계**: R1 - 프로젝트 생성, 열기, 지원 schema migration.

**연결 요구**: `PRJ-006`, `NFR-004`, `NFR-005`, `INT-006`
**B 보강**: `B::PRJ-001`, `B::PRJ-006`, `B::NFR-003`, `B::NFR-007`
**화면**: `UI-02`
**API**: `API-002`, `API-003`, `API-004`, `API-001`
**수식**: 없음 - schema, 참조, 파일 검사
**설계 근거**: `PRJ-006`, `NFR-004`의 GUI 중립 명령/복구 계약

- **입력:** 프로젝트 폴더 또는 안전하게 풀린 archive, `open_mode=open/create/copy/recover`, 신규 생성 name, request_key, 지원 schema, migration graph, 파일 hash와 참조 목록.
- **검사, 처리:** API-002의 mode별 경로, 접근, manifest, schema 검사 -> 소스 백업 -> 지원된 migration을 순서대로 실행 -> entity/단위/참조 불변성 검사 -> 작업 사본과 derived index 생성. create는 새 project UUID와 initial revision을 만들며 단위, 좌표, 빈 컬렉션만 초기화하고 물리 미정값을 유지한다. copy는 원본 보존과 새 project ID를 보장한다. 후속 API-003은 반환된 expected_revision을 사용한다.
- **출력:** project handle, 읽기/쓰기 모드, 현재 revision, 복구 후보, 누락 참조, migration report. 오래된 결과의 solver/자료 버전을 현재 버전으로 덮어쓰지 않는다.
- **실패, 변경영향:** 손상, 최신 미지원 schema, 쓰기 잠금, 외부 참조 누락을 구분한다. 실패 migration은 원본을 그대로 보존하고 열린 것처럼 저장하지 않는다. schema 변경으로 의미가 달라진 파생 데이터는 검증 대기 상태다.

<a id="FN-002"></a>
### FN-002 편집 트랜잭션, undo, 리비전, 저장

**단계**: R1 - 명령, undo/redo, 저장, 고정 리비전, 의존성 판단.

**연결 요구**: `PRJ-006`, `PRJ-007`, `CAD-001`, `JOB-005`, `NFR-004`
**B 보강**: `B::PRJ-002`, `B::PRJ-004`, `B::PRJ-005`, `B::NFR-002`, `B::NFR-003`
**화면**: `UI-01`, `UI-02`, `UI-05`
**API**: `API-003`, `API-004`, `API-005`, `API-006`
**수식**: 없음 - 의존 graph, hash 분류
**설계 근거**: `PRJ-006`, `NFR-004`의 GUI 중립 명령/복구 계약

- **입력:** expected revision, typed domain command, entity UUID, 변경값, 묶음 편집 경계, 저장/스냅샷 요청.
- **검사, 처리:** 낙관적 revision 일치 검사 -> 입력식/참조 검사 -> 변경 전 상태와 inverse command 보존 -> 영향을 받는 파라미터, 기하, solver/derived/export 계층 산정 -> commit. 드래그 연속 이벤트는 완료된 한 조작으로 합치되 서로 다른 사용자 조작을 합치지 않는다.
- **출력:** 새 revision, changed entity 목록, regenerated/stale/unchanged artifact 분류, undo/redo 위치, atomic save 결과. 불변 SnapshotRef는 별도 snapshot UUID, revision_id, content hash, schema/version, 봉인 시각을 가지며 실행/출력 기준이 된다. 두 ID를 같다고 가정하지 않고 결과, sidecar에 모두 저장한다.
- **실패, 변경영향:** 검증 실패는 전부 rollback하고 유효 모델을 유지한다. 디스크 부족은 저장 완료로 표시하지 않는다. undo는 물리 변경을 역적용하며 과거 run을 삭제하지 않는다. 외부 정합, 목표, 시각화는 공통 캐시 표에 따라 raw EM을 보존한다.

<a id="FN-003"></a>
### FN-003 단위, 표현식, 파라미터 의존성 평가

**단계**: R1 - 단위와 제한된 표현식, 기본 파라미터 제약.

**연결 요구**: `PRJ-004`, `PRJ-005`, `CAD-003`, `PHY-068`, `DAT-004`
**B 보강**: `B::PRJ-003`, `B::GEO-001`
**화면**: `UI-03`, `UI-05`, `UI-07`, `UI-08`
**API**: `API-003`, `API-006`
**수식**: 없음 - SI 차원 대수와 명시된 식 평가
**근거**: `OPENEMS_MATERIALS`

- **입력:** field physical dimension, display unit, literal/expression, bound, provenance, parameter dependency IDs.
- **검사, 처리:** 제한 문법 tokenize/parse -> 허용 symbol/function 검사 -> dimension inference -> 의존 graph cycle 검출 -> 위상순 평가 -> finite/range/정수 제약 검사. `eval`, import, 파일/네트워크 호출은 허용하지 않는다.
- **출력:** 원식, SI 값, 표시값, dimension, 적용 상태와 변경 의존 목록. `null`은 계산되지 않은 값이며 0을 뜻하지 않는다. 표시 반올림은 저장값을 바꾸지 않는다.
- **실패, 변경영향:** undefined symbol, dimension mismatch, cycle path, 0나눗셈, overflow를 field locator와 반환한다. 불완전 식은 편집 초안에만 남긴다. 단위 표시만 변경하면 물리/solver hash는 유지한다.

<a id="FN-004"></a>
### FN-004 목표, 프리셋, 평가 마스크 정의

**단계**: R1 - 대역, 목표, 프리셋, 버전 관리; 특수 응용 평가 입력은 R2/R3 요구에 따라 활성화.

**연결 요구**: `PRJ-001`, `PRJ-002`, `PHY-002`, `PHY-017`, `PHY-061`, `PHY-089`, `NFR-009`
**B 보강**: `B::TGT-001`, `B::TGT-002`, `B::TGT-003`, `B::TGT-004`, `B::TGT-005`, `B::TGT-007`, `B::TGT-008`
**화면**: `UI-03`, `UI-15`, `UI-17`
**API**: `API-003`, `API-006`, `API-018`
**수식**: `EQ-035`
**근거**: `LORA_ALLIANCE_RP002_1_0_5`, `QORVO_APH007`

- **입력:** 통신/지역/profile version, physical mode, bands, sample policy, port/direction/polarization, metric definitions, limits, hard manufacturing/spatial constraints.
- **검사, 처리:** 프리셋 원자료/버전을 snapshot -> 주파수, unit, 조건 일관성 검사 -> 각 target에 UUID와 revision 부여 -> metric에 필요한 입력/출력을 도출한다. 선택 모드가 solver 지원을 뜻하지 않으므로 capability 검사를 별도 요청한다.
- **출력:** target set, evaluation mask, 필요한 field, port, scenario 목록, 미정 목표. 주파수 preset은 인증 완료 의미가 없다.
- **실패, 변경영향:** 역전 대역, 무효 임계값, 정의되지 않은 편파/포트는 적용 차단. 목표 변경은 metric/순위/보고서만 stale로 하고, 새로운 주파수/필드가 raw에 없을 때만 추가 해석 필요를 알린다.

<a id="FN-005"></a>
### FN-005 기존 추출 데이터, 근거 파일 통합

**단계**: R1 - 확보 자료, 출처, 추출값 통합; 새로운 schema는 importer 지원표로 관리.

**연결 요구**: `DAT-001`, `DAT-002`, `DAT-003`, `DAT-004`, `DAT-006`, `DAT-007`
**B 보강**: `B::LIB-002`, `B::LIB-006`, `B::MAT-001`
**화면**: `UI-24`
**API**: `API-009`, `API-010`, `API-027`
**수식**: 없음 - 추출 레코드, 출처의 구조 검사
**근거**: `ISOLA_FR408HR_DKDF`, `NORDIC_NWP008`

- **입력:** 추출 자료 JSON/CSV/SQLite의 선언 schema, source index, 원문 hash, locator, geometry/material/condition/validation records와 확인 상태.
- **검사, 처리:** read-only staging -> schema/ID/단위/참조 검사 -> 기존 레코드와 duplicate/conflict 비교 -> 추가, 변경, 미지원 레코드 preview -> 목적별 commit. 템플릿/재료는 API-010의 `target=catalog.templates/catalog.materials`와 `expected_catalog_revision`을 사용하고 preview source hash를 다시 확인한다. source/추출 근거는 해당 레코드에 연결하며 미지원 target을 임의 만들어 호출하지 않는다. 행 수는 자료 manifest와 대조하며 특정 이전 숫자를 영구 상수로 강제하지 않는다.
- **출력:** source/record registry, import report, source page/CAD member links, conflict cases. 원자료 파일과 추출 해석을 구분하고 임의 원문 재배포를 하지 않는다.
- **실패, 변경영향:** 잘못된 locator, hash mismatch, 단위 미해석, 코드 포함 파일은 상태로 기록하고 적용을 보류한다. 자료 갱신은 기존 프로젝트 snapshot을 바꾸지 않는다. 사용자가 새 값을 선택하면 FN-014의 변경 경로를 따른다.

<a id="FN-006"></a>
### FN-006 템플릿 카탈로그, 검색, 사용자 등록

**단계**: R1 - 검색, 레퍼런스, 검증상태; 사용자/외부 실행 템플릿 확장은 R2와 실행 권한 정책 적용.

**연결 요구**: `CAD-009`, `PHY-005`, `DAT-005`, `DAT-007`, `NFR-008`
**B 보강**: `B::LIB-001`, `B::LIB-003`, `B::LIB-004`, `B::LIB-005`, `B::LIB-006`
**화면**: `UI-04`, `UI-24`
**API**: `API-027`, `API-003`, `API-009`, `API-010`
**수식**: 없음 - 조건 필터, 검증 근거 질의
**근거**: `NORDIC_NWP008`, `TI_AN058_SWRA161`

- **입력:** topology/family, parameter schema, constraints, port recipe, material assumptions, source/evidence links, separate edit/synthesis/solver/validation support flags, 검색 조건.
- **검사, 처리:** 필수 role, parameter, source 검사 -> API-009 preview와 API-010의 `target=catalog.templates`, `expected_catalog_revision`으로 버전이 있는 template 저장 -> 명시한 적용 범위로 필터 -> 포함/제외 이유 반환. 프로젝트에 적용할 때는 별도 API-003 transaction을 사용한다. 특정 주파수/보드에서 보고된 원자료 성능을 범위 전체의 성공 예측으로 사용하지 않는다.
- **출력:** template cards, 후보 비교 목록, read-only source revision, 새 작업 사본용 definition. 사용자 템플릿은 원본을 수정하지 않는 새 ID/version이다.
- **실패, 변경영향:** 불완전 source나 검증 근거는 표시하되 `검증됨` 승격을 차단한다. 첨부 script는 import로 자동 실행하지 않는다. template 업데이트는 생성된 설계를 자동 변경하지 않는다.

<a id="FN-007"></a>
### FN-007 초기 합성, 문헌 형상 복제, 후보 생성

**단계**: R1 필수는 원호와 평면 IFA의 초기 형상/출처 기반 후보이다. 직사각 패치 초기식은 정의역을 확인하는 보조 경로이며 R1 전체 패치 합성 또는 EM 검증 완료를 약속하지 않는다. 다른 계열은 RFAD 22의 개별 지원 범위와 요구 단계를 따른다.

**연결 요구**: `SYN-001`, `PHY-005`, `PHY-008`, `PHY-010`, `PHY-011`, `PHY-013`, `PHY-016`, `PHY-089`
**B 보강**: `B::LIB-001`, `B::LIB-003`, `B::TGT-006`, `B::PRJ-008`
**화면**: `UI-04`, `UI-05`
**API**: `API-007`, `API-008`, `API-006`
**수식**: `EQ-001`, `EQ-002`, `EQ-003`, `EQ-004`, `EQ-005`, `EQ-041`
**근거**: `TI_AN058_SWRA161`, `NORDIC_NWP008`, `MATHWORKS_PATCH_SEED`

- **입력:** 목표, 허용영역, stackup, 재료, 선택 template/version, 사용자 고정값, 합성 또는 문헌 복제 모드.
- **검사, 처리:** template의 유효조건 확인 -> 지원된 초기식/명시 파라미터 적용 -> semantic graph 생성 -> geometry build -> topology/제조/space 검사 -> 후보와 미달 조건 반환. 직사각형 TM10 패치 초기 치수는 EQ-041의 균일 얇은 기판, 급전/접지 가정 안에서만 계산한다. 초기식이 없는 family는 수동 파라미터 또는 원자료 복제로 시작한다.
- **출력:** 편집 가능한 후보 graph, 값의 유도 근거, 식 ID, 가정, 원자료, 실제 기하 길이와 초기 전기 추정의 구분. theta, r, width 정의를 유지한다.
- **실패, 변경영향:** 합성 미지원, 공간 부족, source 조건 부족, 형상 생성 실패를 구분한다. 원호 모노폴 전체에 microstrip epsilon_eff와 lambda/4를 보편식으로 적용하지 않는다. 생성 후보는 미해석이며 공진/효율 합격을 부여하지 않는다.

## 3. 형상, 환경, 재료, 급전

<a id="FN-008"></a>
### FN-008 평면 패턴 연산, 파라미터 편집

**단계**: R1 - 자유 평면 기본 요소와 파라미터 편집; 형상을 그릴 수 있어도 NFC/UWB 등의 특수 해석 지원을 뜻하지 않음.

**연결 요구**: `PHY-006`, `CAD-001`, `CAD-002`, `CAD-004`, `CAD-005`, `CAD-006`, `PHY-010`, `PHY-011`, `PHY-012`, `PHY-013`, `PHY-014`, `PHY-015`, `PHY-016`, `PHY-018`, `PHY-019`
**B 보강**: `B::GEO-001`, `B::GEO-002`, `B::GEO-006`
**화면**: `UI-05`
**API**: `API-003`, `API-008`, `API-006`
**수식**: `EQ-001`, `EQ-002`, `EQ-039`
**근거**: `OS-S22`, `OS-S26`, `NORDIC_NWP008`

- **입력:** analytic lines/arcs/circles/polygons, width/offset rule, Boolean operation, layer/role/net, UUID, transform, parameter expressions.
- **검사, 처리:** 식 평가 -> centerline와 물리 도체 영역을 구분 생성 -> line/arc 길이 및 경계 계산 -> 선택 Boolean/offset -> topology validation -> 명령 commit. 슬롯은 빈 영역 연산이며 구리 객체로 바꾸지 않는다.
- **출력:** 안정된 semantic entity mapping, 2D physical regions, 측정 길이, 면적, gap, 변경 graph. 지원 곡선은 analytic 형태를 보존하고 tessellation은 별도 policy로 생성한다.
- **실패, 변경영향:** 자기교차, 뒤집힌 offset, 얇은 조각, 0폭, 잘못된 topology는 위치와 함께 반환하고 자동 성공 처리하지 않는다. source->결과 면 mapping이 불명확하면 새 subentity ID와 관계를 기록한다. commit된 물리 변경은 CAD, solver, manufacturing 의존성을 재평가한다.

<a id="FN-009"></a>
### FN-009 구속, 전기 연결, 제조 규칙 검사

**단계**: R1 - 치수, 연결, 기본 제조 제약; R2 - 완전한 기하 구속 solver와 고급 repair.

**연결 요구**: `CAD-003`, `CAD-004`, `PHY-012`, `PHY-014`, `PHY-022`, `JOB-001`
**B 보강**: `B::GEO-003`, `B::GEO-006`, `B::GEO-007`, `B::TGT-004`, `B::FAB-005`
**화면**: `UI-05`, `UI-21`
**API**: `API-006`, `API-003`
**수식**: `EQ-002`, `EQ-039`
**근거**: `OS-S26`, `NORDIC_NWP008`

- **입력:** physical geometry, expected connectivity/net graph, design constraints, manufacturer rule profile, tolerances, 검사 범위.
- **검사, 처리:** 공간 index로 후보 근접쌍 생성 -> 정확 경계 거리, intersection, via span 검사 -> 실제 connected components와 기대 연결 비교 -> width/gap/edge/hole/annular constraints 평가. R1 파라미터 bound, 고정좌표와 R2 기하 구속 solver를 분리한다.
- **출력:** issue ID, 객체, 위치, 측정값, 허용값, severity, under/over/constrained 상태, 의도적 분리/기생 도체 표시. R2 constraint solver는 충돌 집합과 직전 유효 해를 반환한다.
- **실패, 변경영향:** 제조 profile 미정이면 해당 규칙은 미평가다. 허용오차로 먼 도체를 자동 접합하지 않는다. 자동 repair는 변화량, 연결 diff를 사용자에게 제시하는 별도 명령이며 승인된 경우만 물리 모델을 갱신한다.

<a id="FN-010"></a>
### FN-010 외부 CAD, EDA, 2D 형상 가져오기

**단계**: R1 - 선언된 KiCad/Gerber 및 기본 STEP 기계 입력; R2 - 추가 DXF/SVG entity, 상세 assembly 확장. 실제 profile gate 필요.

**연결 요구**: `CAD-007`, `CAD-010`, `PHY-006`, `PHY-068`, `NFR-006`
**B 보강**: `B::GEO-008`, `B::GEO-009`, `B::FAB-001`, `B::FAB-004`, `B::STP-006`
**화면**: `UI-05`, `UI-06`, `UI-21`
**API**: `API-009`, `API-010`, `API-008`, `API-006`
**수식**: `EQ-002`, `EQ-039`
**근거**: `OS-S22`, `OS-S26`

- **입력:** declared-format file, version/profile, source hash, length unit, layer/role/net/origin mapping, import include/simplify options.
- **검사, 처리:** 파일 크기, 경로, syntax 안전 검사 -> read-only parse -> 지원/미지원 entity inventory -> 단위, 상하면, 층, 역할 preview -> API-010의 `target=project.geometry`, `expected_revision`으로 명시 mapping commit -> 도메인 UUID와 source correspondence 생성. preview source hash가 달라지면 다시 preview한다. 큰/복잡한 파일은 worker에서 제한된 자원으로 읽는다.
- **출력:** 편집 가능한 지원 객체, 외부 부품 참조, 변환/누락 목록, unknown properties. Gerber/DXF/STEP에서 알 수 없는 Dk, 두께, 넷, 포트는 null이다.
- **실패, 변경영향:** 알 수 없는 단위는 사용자 mapping 전 적용하지 않는다. unsupported entity, broken solid, external dependency를 조용히 버리지 않는다. 가져온 mesh를 정확 BREP로 표시하지 않는다. commit은 새 물리 revision이며 관련 결과를 재평가한다.

<a id="FN-011"></a>
### FN-011 실제 적층, 표면층, 패드, 홀, 비아 구성

**단계**: R1 - 기준 2층 PCB와 관통 비아, 표면층; 추가 층, 특수 비아는 선언된 지원표의 검증 후 제공.

**연결 요구**: `PHY-023`, `PHY-029`, `PHY-032`, `CAD-004`, `CAD-006`, `PHY-022`
**B 보강**: `B::GEO-004`, `B::MAT-004`, `B::MAT-006`, `B::MAT-007`, `B::STP-004`, `B::STP-009`
**화면**: `UI-05`, `UI-07`
**API**: `API-003`, `API-006`, `API-008`
**수식**: `EQ-039`
**근거**: `ISOLA_FR408HR_DKDF`, `ROGERS_RO3000_BONDPLY`

- **입력:** ordered layers, thickness/material snapshot, z reference, total thickness definition, surface coverage/openings, pad/net, hole/tool/finished size, plating, fill, span.
- **검사, 처리:** 두께 포함 범위와 층 합 검사 -> 순서에서 실제 z intervals 산출 -> copper/surface/hole 영역 생성 -> via barrel과 pad 접촉, 시작/끝층 검사. finished copper와 base/plating 근거를 별도 유지한다.
- **출력:** physical stackup, copper/dielectric/surface solids recipe, hollow/filled via specification, connectivity update. 명목 총두께에 맞추려고 유전체를 임의 줄이지 않는다.
- **실패, 변경영향:** 음수/0 두께, 의도치 않은 층 overlap/gap, unsupported via, hole diameter 불일치는 검사 실패/미정으로 반환한다. 시트 도체 선택은 본 함수의 실제 두께를 삭제하지 않는다. 물리 두께 변경은 CAD/CAM 갱신과 solver 모델 유효성 재검사를 유발한다.

<a id="FN-012"></a>
### FN-012 물리 BREP, 조립체, 표시 mesh 생성

**단계**: R1 - 실제 동박 BREP, 분리 바디, 표시 mesh, 기본 assembly.

**연결 요구**: `CAD-001`, `CAD-007`, `CAD-008`, `PRJ-008`, `OUT-004`
**B 보강**: `B::STP-001`, `B::STP-002`, `B::STP-003`, `B::STP-004`, `B::STP-005`
**화면**: `UI-06`, `UI-20`
**API**: `API-008`, `API-006`
**수식**: `EQ-002`, `EQ-039`
**근거**: `OS-S22`, `OS-S26`, `VTK_PYTHON`

- **입력:** semantic physical regions, z intervals, holes/vias, assembly transforms, CAD profile, geometric tolerance, display tessellation settings.
- **검사, 처리:** 도메인 단위를 CAD 단위로 명시 변환 -> 실제 두께 extrusion/Boolean -> closed-solid validation -> material/role 기준의 body mapping -> 표시용 tessellation 생성. 같은 도체의 물리 union과 다른 재료의 분리는 명시 정책이다.
- **출력:** 유효 BREP bodies, assembly tree, entity map, bounding/area/volume 검사치, renderer 중립 triangle/index/attribute data와 선택적 VTK adapter 데이터. 화면 선택은 mapping으로 원래 UUID를 찾는다.
- **실패, 변경영향:** CAD tolerance로 얇은 동박이나 gap이 사라지면 오류다. 표시 mesh 생성 성공을 BREP 성공으로 대신하지 않는다. 카메라, 색, display exaggeration은 이 물리 BREP hash를 바꾸지 않는다. 해석 단순화는 별도 파생 모델로 저장한다.

<a id="FN-013"></a>
### FN-013 환경, 설치 시나리오, 배열, 굽힘 변환

**단계**: R1 - 간이 환경, 기본 외부 STEP 배치, 접촉; R2 - 확장 시나리오/배열, R3 - 굽힘, 인체 등 미검증 특수 물리.

**연결 요구**: `PHY-020`, `PHY-021`, `PHY-033`, `PHY-037`, `PHY-038`, `CAD-008`, `PHY-090`
**B 보강**: `B::ENV-001`, `B::ENV-002`, `B::ENV-003`, `B::ENV-004`, `B::ENV-005`, `B::ENV-006`, `B::ENV-007`, `B::ENV-008`
**화면**: `UI-11`, `UI-06`
**API**: `API-003`, `API-008`, `API-006`
**수식**: `EQ-039`
**근거**: `TI_AN058_SWRA161`, `ROGERS_RO4000_DS`

- **입력:** baseline snapshot, scenario deltas, rigid transforms, physical materials, contact graph, display/EM/export inclusion, optional array/flex/phantom/temperature data.
- **검사, 처리:** baseline 복제 없이 불변 참조와 명시 delta 구성 -> transforms/material tensors 반영 -> 간극, 관통, 접촉/연결 검사 -> 선택 scenario의 물리 모델 생성. 굽힘은 평면 제조 모델과 설치 모델의 대응, 중립면, 변형 가정을 보존한다.
- **출력:** scenario snapshot, changed parameter list, 물체별 실제 포함 상태, 물성, 모델 범위, provenance. 배열의 EM geometry와 외부 여기 가중치를 다른 역할로 저장한다.
- **실패, 변경영향:** 미지원 변형, 팬텀 물성, 자기 재료는 실행 차단 또는 명시 미반영이다. 단순 숨김은 EM hash 변화 없음. 위치, 접촉, 포함, 물성이 바뀌면 해당 scenario solver 입력을 새로 만든다.

<a id="FN-014"></a>
### FN-014 재료 선택, 조건 충돌, 프로젝트 snapshot

**단계**: R1 - 출처, construction, 조건별 값 선택, snapshot, 충돌.

**연결 요구**: `PHY-023`, `PHY-024`, `PHY-025`, `PHY-036`, `DAT-003`, `DAT-004`, `DAT-006`
**B 보강**: `B::LIB-002`, `B::MAT-001`, `B::MAT-002`, `B::MAT-004`
**화면**: `UI-07`, `UI-08`, `UI-24`
**API**: `API-027`, `API-003`, `API-006`
**수식**: 없음 - 출처, 물리조건 matching
**근거**: `ISOLA_ASTRA_DKDF`, `ISOLA_FR408HR_DKDF`, `ROGERS_RO4000_DS`

- **입력:** material source/construction, lot/revision, test method/frequency/temperature/direction, Dk type, paired Dk/Df and uncertainty, target layer, frequency, scenario.
- **검사, 처리:** 정확 조건 matching -> 미정/다른 construction/시험법 충돌 분류 -> 사용자 선택 또는 허용 보간 정책 적용 -> project-local immutable material snapshot 생성. bulk/design/process/effective 값은 다른 semantic kind다.
- **출력:** 선택 원자료와 사용값, 출처, 범위, 보간/추정 flag, conflict decision record, 관련 layers. 같은 품명만으로 Dk와 다른 표의 Df를 결합하지 않는다.
- **실패, 변경영향:** 필요한 Df가 없으면 missing이며 자동0이 아니다. 라이브러리 update는 기존 snapshot을 바꾸지 않는다. 사용값 변경을 명시 commit할 때만 solver/material/판정의 의존성이 갱신된다.

<a id="FN-015"></a>
### FN-015 재료 분산, 손실, 텐서, 도체 표현 변환

**단계**: R1 - 손실, PEC/지원 유한도체, 전달값; R2 - 분산 fit, 이방성, 거칠기 등 adapter 검증이 필요한 확장.

**연결 요구**: `PHY-027`, `PHY-028`, `PHY-029`, `PHY-030`, `PHY-031`, `PHY-032`, `PHY-033`, `PHY-034`, `PHY-051`
**B 보강**: `B::MAT-003`, `B::MAT-005`, `B::MAT-008`, `B::MAT-009`, `B::MAT-010`
**화면**: `UI-08`, `UI-12`
**API**: `API-003`, `API-006`, `API-011`, `API-012`
**수식**: `EQ-006`, `EQ-007`, `EQ-008`, `EQ-009`
**근거**: `OPENEMS_MATERIALS`, `ROGERS_COPPER_FOIL`, `ROGERS_ISOTROPY`

- **입력:** selected physical material snapshot, raw curves, frequency weights, model family, fit limits, tensor axes, conductor actual thickness, sigma, roughness model, chosen solver capability.
- **검사, 처리:** 정의, 부호, 단위와 loss components 검사 -> 지원 모델에서 fit/환산 -> 원자료 대역 내 오차, passivity/stability 검토 -> tensor 좌표변환 -> 실제 solver coefficients와 approximation manifest 생성. 일정 sigma 환산과 광대역 tan_delta 모델의 차이를 기록한다.
- **출력:** 원자료, 변환 모델, coefficients, 범위, fit residual, 전달값, 생략 효과. sigma와 tan_delta가 같은 손실의 이중 표현이면 중복 합산하지 않는다.
- **실패, 변경영향:** unsupported tensor/roughness, 비수동 fit, 불안정 pole, 대역 밖, 필수 coefficient 없음은 차단/범위 제한이다. delta/t만으로 모든 sheet validity를 보증하지 않는다. 모델 변경은 실제 solver definition과 그 유효성에 반영한다.

<a id="FN-016"></a>
### FN-016 포트, 급전, 여기, 기준면 정의

**단계**: R1은 단일종단 및 지원하는 두 단자 포트, 기준면과 복소 부하 데이터의 보존이다. R2는 검증된 mixed-mode 변환과 다중 동시 여기이다. 두 단자 데이터를 저장하는 기능을 mixed-mode S 검증 완료와 혼동하지 않는다.

**연결 요구**: `PHY-039`, `PHY-040`, `PHY-041`, `PHY-043`, `PHY-044`, `PHY-052`
**B 보강**: `B::FED-001`, `B::FED-002`, `B::FED-003`, `B::FED-004`, `B::FED-007`, `B::FED-009`
**화면**: `UI-09`, `UI-12`
**API**: `API-003`, `API-006`, `API-011`, `API-012`
**수식**: `EQ-005`, `EQ-010`, `EQ-011`, `EQ-013`, `EQ-014`
**근거**: `OPENEMS_PORTS`, `SKRF_NETWORKS`

- **입력:** port UUID/order/type, signal/reference entity, section/direction/polarity, mode, network Z0 model/wave definition, native physical port resistance와 source/load, physical reference plane, excitation basis, terminations, source/load.
- **검사, 처리:** conductor contact와 geometry 검사 -> type별 필수 field 및 adapter capability 검사 -> native port mapping -> reference-plane/normalization/excitation specification 고정 -> 실행 전 보고서 생성. feedline epsilon_eff 식은 해당 균일 transmission-line 조건에서만 사용한다.
- **출력:** 포트 계약, native mapping, 정규화 metadata, basis solve 계획. 이상 포트와 실제 connector/cable geometry는 별도 객체다.
- **실패, 변경영향:** 잘못된 reference conductor, duplicate order, unsupported mode, 0면적, 불충분 excitation은 실행 불가. 물리 port 변경은 raw EM 재사용 불가. 저장된 결과의 수학적 재정규화/기준면 이동은 FN-024에서 raw를 보존한다.

<a id="FN-017"></a>
### FN-017 외부 정합망, 부하와 raw EM 결합

**단계**: R1 - 기본 외부 RLC 정합 및 raw EM 재사용; R2 - 실제 부품 모델, 복수 network 등 확장.

**연결 요구**: `PHY-039`, `PHY-040`, `PHY-042`, `JOB-005`, `PHY-058`
**B 보강**: `B::FED-005`, `B::FED-006`, `B::PRJ-009`, `B::RES-002`, `B::RES-003`
**화면**: `UI-10`, `UI-15`
**API**: `API-017`, `API-018`, `API-016`
**수식**: `EQ-028`, `EQ-029`, `EQ-030`, `EQ-031`, `EQ-032`, `EQ-017`
**근거**: `SKRF_MATCHING`, `SKRF_NETWORKS`

- **입력:** 유효 raw S/Y/Z와 port/reference contract, 외부 RLC/부품 network graph, source/load, excitation, 선택 복소 field basis, 모델 대역, 실장 state.
- **검사, 처리:** EM 영역 외부 모델인지 확인 -> node 연결, reference, wave, frequency 일치 검사 -> element/network를 공통 정의로 변환 -> stable linear network solve 또는 내부 포트 제거 -> 회로 손실과 원 EM 포트의 실제 V/I 또는 a-vector 산출 -> 파생 Z0/기준면에서 원 EM field 기준면, wave convention으로 되돌린 `a_req` 생성 -> `basis_a*c=a_req`의 rank, condition, 잔차 검사로 field coefficient c 계산 -> 충분한 field basis가 있을 때 FN-026으로 복소 합성한다. 단위 power-wave identity basis인 경우에만 c=a_req를 바로 사용한다.
- **출력:** derived network, node/port 응답, 회로 손실, field coefficients, raw parent IDs, circuit hash와 유효범위. S11, Z 등 network metric은 네트워크 단계에서 제공할 수 있지만 정합 후 gain/efficiency는 FN-026의 복소 합성, Prad 적분과 외부 회로를 포함한 일관된 power ledger가 끝난 뒤 FN-025에서 평가한다. 최종 source 전력 기준의 realized quantity와 antenna 방사효율을 구분한다.
- **실패, 변경영향:** 특이/ill-conditioned 연결, nonlinear/state 모델 미지원, frequency extrapolation, basis 불충분은 대상 출력 미평가다. 외부 소자값 변경은 raw EM을 유지한다. 물리 pad/배선 변경 또는 EM 내부 소자라면 새 solver 실행 경로로 보낸다.

<a id="FN-018"></a>
### FN-018 정합 구조 합성, 부품 후보, tuner 상태

**단계**: R2 - 정합 구조/부품 합성; R3 - tuner/reconfigurable state 전문 기능.

**연결 요구**: `SYN-002`, `TUNE-001`, `PHY-042`, `PHY-076`, `AUG-004`
**B 보강**: `B::FED-005`, `B::FED-006`, `B::FAB-009`
**화면**: `UI-10`, `UI-18`
**API**: `API-030`, `API-017`, `API-020`, `API-021`, `API-003`
**수식**: `EQ-028`, `EQ-029`, `EQ-030`, `EQ-035`
**근거**: `SKRF_MATCHING`, `B-S45`

- **입력:** 측정 또는 raw EM impedance, allowed topology, max part count, value/component library, target/scenarios, part bounds, power limits, tuner state/control codes.
- **검사, 처리:** 데이터 기준면, 대역 확인 -> API-030의 지원 합성 또는 API-020의 `study_type=matching_synthesis` 계획 -> 허용 topology별 초기 후보 -> FN-017로 실제 모델 평가 -> 강제 제약/부품 범위 검사 -> 다목적 후보 순위 -> selected candidate를 독립 circuit revision으로 저장한다. study 실행은 API-021로 제출한다.
- **출력:** 부품/회로 후보, value, package, model revision, DNP/state mapping, 손실, 목표 미달, 탐색 범위와 종료 사유. tuner는 상태마다 별도 회로와 적용 조건을 가진다.
- **실패, 변경영향:** 유효 후보 없음과 solver 실패를 구분한다. 이상 LC 결과를 실제 부품 검증으로 표시하지 않는다. 회로 후보 적용은 raw EM 유지가 기본이며 PCB 실장 형상 변경은 FN-008/011과 새 raw EM 경로로 전환한다.

## 4. 해석 계획, 작업, 결과

<a id="FN-019"></a>
### FN-019 기능 협상, 설치, worker 진단

**단계**: R1 - openEMS, CAD, 기본 worker 진단; R2 이후 추가 solver는 개별 capability gate.

**연결 요구**: `INT-001`, `INT-002`, `INT-003`, `INT-005`, `NFR-001`, `NFR-007`, `PHY-090`
**B 보강**: `B::SIM-001`, `B::NFR-007`, `B::NFR-008`
**화면**: `UI-01`, `UI-12`, `UI-23`
**API**: `API-001`
**수식**: 없음 - capability/버전/실행환경 검사
**근거**: `OPENEMS_MATERIALS`, `OPENEMS_PORTS`, `OS-S27`, `OS-S28`, `OS-S50`

- **입력:** 선택 runtime/worker/adapter, declared support matrix, executable/version/path, license availability, project required capabilities.
- **검사, 처리:** worker transport/version query -> 실행파일/종속 package 확인 -> 실제 adapter capability와 release-tested profile 결합 -> feature status를 `declared/implemented/verified/unsupported/unknown`으로 반환하고, 선택 모델의 실제 소비 상태는 별도의 `used/approximated/omitted/not_applicable/blocked`로 분류한다.
- **출력:** 기능별 지원 조건, 설치 누락, 버전, 환경, 라이선스 링크와 진단시각. 설치되어 있다는 사실과 검증된 조합을 분리한다.
- **실패, 변경영향:** solver 없음, 상용 license 없음, 버전 mismatch, WSL path/IPC 문제는 해당 실행을 차단하되 편집/자료 조회는 유지한다. backend 변경은 매핑 차이보고와 solver definition 재평가를 요구한다. subprocess 사용을 라이선스 면제 근거로 반환하지 않는다.

<a id="FN-020"></a>
### FN-020 실행 전 종합 검사, 불변 계획

**단계**: R1 - 종합 preflight, 불변 실행 계획.

**연결 요구**: `PRJ-003`, `JOB-001`, `JOB-006`, `PHY-051`, `PHY-087`, `PRJ-009`
**B 보강**: `B::PRJ-007`, `B::PRJ-008`, `B::SIM-001`, `B::VAL-008`
**화면**: `UI-01`, `UI-12`
**API**: `API-006`, `API-005`, `API-011`
**수식**: `EQ-003`, `EQ-037`, `EQ-038`
**근거**: `OPENEMS_MATERIALS`, `OPENEMS_PORTS`, `OPENEMS_MESH`

- **입력:** 유효 작업 revision, target/material/scenario, ports, solver config, requested results, resource budget, warning handling policy.
- **검사, 처리:** 필요한 값, 물리 topology, 재료/포트, capability, boundary, monitor, resource 검사 -> 차단/경고와 명시 근사 구분 -> 실행 가능 조건에서 SnapshotRef 생성 -> AnalysisPlan에 의도한 mapping/config/hash/versions와 검증 계획 고정한다. 실제 메시, native 입력, 소비값은 FN-021의 준비 산출물에서 확정한다.
- **출력:** 불변 AnalysisPlan, block/warning issues, 예상 native input preview, 계산 범위, 평가 frequency와 필요한 output. 허용한 경고는 plan에 남는다. 이 단계의 예상값을 준비된 실제 결과로 표시하지 않는다.
- **실패, 변경영향:** 필수값 없는 계획은 job submit 불가. 검사 뒤 작업 사본이 바뀌어도 제출은 고정 snapshot을 사용한다. 물리/solver hash가 다르면 새 plan을 요구한다. zero-solver 상태에서는 유효 full-wave run을 만들지 않는다.

<a id="FN-021"></a>
### FN-021 solver 모델, 메시, 관측면 준비

**단계**: R1 - 기준 모델 mesh, 경계, 관측, 자원, 형상 보존 검사; 고급 모델은 지원 단계 적용.

**연결 요구**: `PHY-047`, `PHY-049`, `PHY-050`, `PHY-051`, `PHY-053`, `JOB-003`
**B 보강**: `B::SIM-002`, `B::SIM-003`, `B::SIM-004`, `B::SIM-005`, `B::SIM-009`
**화면**: `UI-12`, `UI-13`
**API**: `API-011`, `API-012`, `API-008`
**수식**: `EQ-002`, `EQ-003`, `EQ-006`, `EQ-019`, `EQ-038`
**근거**: `OPENEMS_MESH`, `OPENEMS_MATERIALS`, `OPENEMS_NF2FF`

- **입력:** immutable AnalysisPlan, semantic->solver representation mapping, conductor/material approximations, mesh/boundary/excitation/monitor specs, hardware limits.
- **검사, 처리:** API-012 `solver.prepare`는 AnalysisPlan을 동일 scheduler의 `em_prepare` 작업으로 접수하고 TaskRef를 즉시 반환한다. 준비 작업의 worker가 physical geometry를 adapter representation으로 변환 -> layer, sheet, ports, critical gaps에 mesh policy 적용 -> solver geometry와 원형상 연결, 간극 보존 비교 -> domain/PML/NF2FF/monitor 검사 -> 실행 input files와 mesh 생성. 예상 cells/RAM는 모델 근거와 함께 계산하고 actual 값과 분리한다.
- **출력:** 접수 응답은 TaskRef이며 준비 완료 output은 실제 mesh, native material/port mapping, consumption report, input hash, actual timestep을 담은 PreparationArtifact, 이를 참조하는 별도 ID/hash의 불변 PreparedPlan, preservation diagnostics. 원 AnalysisPlan ID/hash와 관계를 보존하며 원 plan을 수정하지 않는다. 관측 데이터 크기도 자원 추정에 포함한다.
- **실패, 변경영향:** gap 폐쇄, trace 소실, sheet 누락, PML 중첩, 지원 매질 불일치, resource limit는 실패/경고 정책으로 처리한다. adapter가 표현하지 못한 물성을 silently drop하지 않는다. 준비 실패는 raw EM 생성 성공이 아니다.

<a id="FN-022"></a>
### FN-022 작업 제출, 큐, 실행, 취소, 재개

**단계**: R1 - 유한 자원 queue, 순서, 취소, 로그; R2 - 고급 병렬/checkpoint, R3 - 선택 원격 실행.

**연결 요구**: `JOB-002`, `JOB-003`, `JOB-004`, `JOB-006`, `JOB-007`, `NFR-003`, `NFR-004`
**B 보강**: `B::SIM-008`, `B::NFR-001`, `B::NFR-002`, `B::NFR-003`, `B::NFR-004`
**화면**: `UI-14`
**API**: `API-013`, `API-014`, `API-015`, `API-028`, `API-029`
**수식**: 없음 - 영속 job state machine, 자원 admission
**근거**: `OPENEMS_MESH`

- **입력:** TaskPlan의 kind, plan ref, input artifact hashes, runtime profile, budget, output roles, prerequisites, worker ID, priority, `request_key`(멱등성 키), cancel/resume request. `em_prepare`의 plan ref는 AnalysisPlan, `em_analysis`의 plan ref는 검증된 PreparedPlan이다. API-012는 준비 접수, API-013은 해당 종류의 작업 제출 계약을 따른다.
- **검사, 처리:** kind별 준비, 입력 파일 검증 -> resource admission -> 영속 queue 접수 -> 격리 worker process 실행 -> progress/log/resource/exit 수집 -> 종류별 결과 검사. 준비는 FN-021의 PreparationArtifact/PreparedPlan 완결성 검사, EM 실행은 FN-023, CAD/출력은 FN-012/FN-043, study는 해당 coordinator, 장비 취득은 FN-036의 검사, data_processing은 operation_method에 대응하는 FN의 입력/출력 검사로 연결한다. UI thread에서 solver를 돌리지 않는다.
- **출력:** job ID, stage/events, 실측 resource, exit reason, run files. 취소 요청은 즉시 접수 상태를 반환하며 종료 확인 전에는 cancelled를 확정하지 않는다. 완료와 취소가 경합하면 실제 먼저 확정된 terminal 결과를 유지하고 늦은 요청으로 덮어쓰지 않는다.
- **실패, 변경영향:** crash/timeout/out-of-memory/disk-full/transport loss를 구별한다. JobState는 RFAD 04 section 6을 사용하며 transport_state는 독립이다. 재시도는 새 run이며 완료된 subjobs는 보존한다. backend checkpoint와 matching version/input이 확인될 때만 resume; 아니면 restart로 안내한다. 연결 끊김만으로 worker 종료를 가정하지 않고 재연결 후 상태를 조회한다. `interrupted`는 종료 상태이며 `resume_eligibility=unsupported/eligible/ineligible`는 독립 속성이다. resumable을 JobState로 저장하지 않는다.

<a id="FN-023"></a>
### FN-023 raw EM 수집, 정규 규약 변환, 물리 진단

**단계**: R1 - raw 수신, 규약, 전력, 유효성; 특수 물리 진단은 해당 model gate.

**연결 요구**: `PHY-050`, `PHY-054`, `PHY-057`, `PHY-087`, `JOB-006`, `OUT-007`
**B 보강**: `B::SIM-008`, `B::RES-002`, `B::VAL-002`, `B::VAL-008`
**화면**: `UI-14`, `UI-15`
**API**: `API-016`, `API-018`, `API-015`
**수식**: `EQ-011`, `EQ-013`, `EQ-014`, `EQ-015`, `EQ-016`
**근거**: `OPENEMS_PORTS`, `OPENEMS_NF2FF`, `SKRF_NETWORKS`

- **입력:** native solver outputs, logs, port/basis metadata, expected output manifest, termination reason and convergence diagnostics.
- **검사, 처리:** 원 native 파일을 불변 보존 -> 완결성, shape/frequency/port order, finite 값 검사 -> 검증된 phasor 부호, Fourier, 전류 방향, 좌표 규약 변환과 확인된 peak phasor 채널의 RMS 변환 -> 별도 canonical dataset 저장 -> power budget/passivity/reciprocity 등 적용 가능한 진단. S, 이미 정규화된 power wave, 순간 시간 샘플, 규약 미확정 FFT에 일괄 sqrt(2) 변환을 하지 않는다. reciprocity는 reciprocal material/설정인 경우에만 검사한다.
- **출력:** native raw dataset ID/hash와 canonical dataset의 별도 ID/변환 이력, validity mask, 종료/수렴/물리 진단. RFAD 08의 S 배열 축은 outgoing i, incident j이며 field basis에는 `basis_a[Nf,Nport,Nexc,2]`, 실제 port/excitation IDs, 원 기준면, amplitude 규약을 보존한다. 저장된 S로 계산한 지표와 직접 solver power/fields를 구분한다.
- **실패, 변경영향:** 부분 파일, 불명확 native convention, 불일치 frequency, 미흡 excitation은 결과 확정을 차단하거나 명시 제한한다. nonphysical 값은 원본을 보존하고 invalid flag; 숫자를 조용히 clamp하지 않는다. exit code 0만으로 수렴 성공을 부여하지 않는다.

<a id="FN-024"></a>
### FN-024 네트워크 재정규화, 기준면, 외부회로 후처리

**단계**: R1 - 원시 보존, 기본 network 변환, 지원 기준면/fixture 보정; R2 - 고급 복소 reference/다중포트 확장.

**연결 요구**: `PHY-041`, `PHY-052`, `PHY-057`, `PHY-080`, `JOB-005`
**B 보강**: `B::PRJ-009`, `B::FED-003`, `B::FED-004`, `B::RES-001`
**화면**: `UI-09`, `UI-10`, `UI-15`, `UI-19`
**API**: `API-017`, `API-016`
**수식**: `EQ-010`, `EQ-011`, `EQ-012`, `EQ-029`, `EQ-030`, `EQ-031`
**근거**: `SKRF_NETWORKS`, `SKRF_CALIBRATION`

- **입력:** immutable raw/measurement network, port order, Z0(f), wave_definition, reference planes, ordered transformations, propagation/fixture models, target frequency grid policy.
- **검사, 처리:** transformation preconditions 검사 -> frequency overlap/port mapping 일치 -> 지원된 S/Z/Y conversion, renormalization, reference-plane correction, fixture 제거 또는 FN-017 회로 결합 -> 결과와 단계별 이력 저장. 무조건 element-wise 역수나 naive matrix inverse로 deembed하지 않는다.
- **출력:** derived ID, parent chain, complex arrays, new Z0/wave_definition/planes, interpolated/invalid masks와 원 EM 포트 기준으로 되돌리는 유효 변환 정보. 원본을 다시 조회할 수 있다. S의 재정규화만으로 field basis가 바뀌었다고 기록하지 않는다.
- **실패, 변경영향:** singular transform, 복소Z0 정의 미지원, 부족한 fixture, 대역 불일치, noise amplification을 진단한다. 변환 실패는 raw를 바꾸지 않는다. 외부 처리옵션만 바뀌면 파생 데이터와 metric만 새로 생성한다.

<a id="FN-025"></a>
### FN-025 RF 지표, 대역 mask, 목표 판정

**단계**: R1 - 기본 RF/방사 지표와 목표 판정; 특수 metric은 R2/R3 및 필요한 원시 데이터가 있을 때만.

**연결 요구**: `PHY-054`, `PHY-057`, `PHY-058`, `PHY-061`, `PHY-087`, `PHY-089`
**B 보강**: `B::TGT-003`, `B::TGT-005`, `B::TGT-008`, `B::RES-001`, `B::RES-002`, `B::RES-003`, `B::RES-006`
**화면**: `UI-03`, `UI-15`, `UI-22`
**API**: `API-018`, `API-016`
**수식**: `EQ-010`, `EQ-013`, `EQ-014`, `EQ-015`, `EQ-016`, `EQ-017`, `EQ-018`, `EQ-035`, `EQ-040`
**근거**: `OPENEMS_PORTS`, `OPENEMS_NF2FF`, `TI_AN058_SWRA161`

- **입력:** raw/derived results, valid bands/points, convergence, power/reference definitions, immutable target mask, direction/polarization/scenario.
- **검사, 처리:** metric별 필요한 데이터/정규화 확인 -> 정의대로 계산 -> 계산점, 보간구간, 미평가 gap 분류 -> 모든 요구 대역/방향/조건의 predicate 적용 -> `pass/fail/not_evaluated/conditional`과 부족 조건 reason을 반환. 단일포트 공식을 다중포트에 그대로 쓰지 않는다.
- **출력:** metric values, units, denominators, source IDs, min/max/worst location, target revision과 판정 근거, unavailable reasons. 링크 버짓을 제공할 때는 EQ-040의 조건부 가정을 표시하며 실제 range 보장으로 사용하지 않는다.
- **실패, 변경영향:** 절대 방사 전력, 입력/수용 전력의 정규화 근거가 없으면 efficiency는 미평가이며, 해당 방향 U 또는 동등하게 검증된 solver gain 출력이 없으면 gain은 미평가다. 원 조건의 검증된 solver Prad만 있는 경우에도 power 계약이 충분하면 원 조건의 efficiency는 계산할 수 있지만 임의 새 여기의 loaded field를 만들 수는 없다. 목표 없으면 미정, 미수렴 결과는 검증 완료 pass로 승격하지 않는다. 목표변경은 raw 재실행 없이 재평가하되 필요한 데이터가 없으면 요청 목록을 반환한다.

<a id="FN-026"></a>
### FN-026 근접장, 전류, NF2FF, 편파 결과

**단계**: R1 - 복소 field, 2D cut/3D pattern, 정규화, 출력; R2 - 전문 편파/축비, 고급 phase center.

**연결 요구**: `PHY-053`, `PHY-059`, `PHY-060`, `OUT-007`, `PRJ-008`
**B 보강**: `B::SIM-009`, `B::RES-004`, `B::RES-005`
**화면**: `UI-16`
**API**: `API-016`, `API-018`, `API-023`, `API-024`
**수식**: `EQ-016`, `EQ-017`, `EQ-018`, `EQ-019`, `EQ-032`
**근거**: `OPENEMS_NF2FF`, `VTK_PYTHON`

- **입력:** stored complex field/monitor data, frequency/time, excitation basis, NF2FF surface/medium, phase center/axes, requested cut/components/angles, 실제 incident basis_a와 선택된 파생 field coefficients, 원 EM 기준 a_req, power ledger 참조.
- **검사, 처리:** 원 관측 데이터와 NF2FF 유효조건 검사 -> 지원 adapter의 near-to-far 처리 -> 원 EM 포트, wave, 기준면으로 정렬한 a_req와 basis_a 검증 -> `basis_a*c=a_req`를 푼 계수 c로 복소 fields 합성 -> complex polarization, Prad 적분 -> 동일 주파수, 여기, 기준면의 power ledger로 gain/efficiency 평가 -> display sampling/cut 생성. field basis 순서와 port 순서를 같다고 가정하지 않는다. 표시 interpolation과 물리 integration sampling을 구분한다.
- **출력:** field dataset, complex farfield, 2D/3D cuts, total power, polarization/axial ratio, 원본 격자, 단위, basis, 정규화, 변환 정책.
- **실패, 변경영향:** surface 조건 불충족, requested frequency 관측 없음, basis 부족/rank 부족, 단위 미확정이면 해당 결과 불가. 크기만 있는 패턴에서 coherent 합성하지 않고 정합 전 Prad를 스케일/손실 확인 없이 새 전력 분모와 결합하지 않는다. 순간 시간 샘플에는 phasor 위상/RMS 변환을 적용하지 않는다. 표면전류 A/m와 체적전류 A/m^2를 혼용하지 않는다. 카메라, colorbar 변경은 raw 해석을 무효화하지 않는다.

<a id="FN-027"></a>
### FN-027 다중포트, MIMO, 배열, AoA 평가

**단계**: R2 - 다중포트/MIMO/배열/AoA의 선언된 지표; 별도 복잡한 scan, 주기/대형 배열 물리는 R3 지원 gate.

**연결 요구**: `PHY-020`, `PHY-044`, `PHY-065`, `PHY-066`, `JOB-005`
**B 보강**: `B::FED-007`, `B::ENV-005`, `B::RES-007`, `B::RES-008`
**화면**: `UI-09`, `UI-11`, `UI-16`, `UI-17`
**API**: `API-017`, `API-018`, `API-016`
**수식**: `EQ-014`, `EQ-023`, `EQ-024`, `EQ-029`, `EQ-030`, `EQ-032`
**근거**: `SKRF_NETWORKS`, `OPENEMS_NF2FF`

- **입력:** full complex S, common-normalized port field basis, excitation/termination state, array transforms/phase calibration, environment angular/polarization statistics.
- **검사, 처리:** full matrix, basis, reference consistency -> network load/excitation solve -> 원 EM port order, wave, plane의 a_req와 basis_a 계수 대응 -> TARC/active reflection, isolation, power -> FN-026의 복소 합성, complex field correlation and coupled pattern/manifold. 전체 a/b 전력은 선언된 power-wave 조건에서 계산하며 다른 포트 유출을 방사/소산으로 합치지 않는다. S-only ECC는 별도 근사 경로와 applicability flag로 계산한다.
- **출력:** state-specific performance, ECC method/assumptions, angular weighting, active/coupled vs isolated patterns, array manifold with coordinates, calibration metadata.
- **실패, 변경영향:** 손실/환경을 무시한 S-only 식을 field-based 결과로 표시하지 않는다. 포트 하나의 데이터로 full matrix를 채우지 않는다. 고정 geometry의 excitation만 변경하면 충분한 basis에서 raw 재사용; element 위치, 연결 변화는 EM 재실행이다. AoA 정확도, 실제 위치 정확도는 자동 보장하지 않는다.

<a id="FN-028"></a>
### FN-028 UWB 전달응답, 군지연, 펄스 충실도

**단계**: R2 - UWB 전달함수, delay, pulse 평가.

**연결 요구**: `PHY-016`, `PHY-027`, `PHY-062`, `PHY-083`
**B 보강**: `B::TGT-007`, `B::RES-009`, `B::SIM-006`
**화면**: `UI-17`, `UI-19`
**API**: `API-018`, `API-016`
**수식**: `EQ-020`, `EQ-021`, `EQ-022`
**근거**: `QORVO_APH007`

- **입력:** 명시된 antenna pair 또는 transmit/receive transfer function, complex samples, frequency band, direction/polarization, distance, reference planes, unwrap/window, pulse, time-origin, delay-removal policy.
- **검사, 처리:** data support/분산 material validity, frequency density 확인 -> 저신호/null 구간을 validity mask -> 일관된 phase unwrap, 미분으로 group delay -> 명시 spectrum/window에서 시간 응답 -> 허용 shift, normalization 규약으로 fidelity 계산.
- **출력:** delay curve, masked segments, time response/fidelity/ringing, 전체 처리 조건. 전파거리 지연을 제거했다면 제거값과 모델을 기록한다.
- **실패, 변경영향:** S11 phase만으로 송수신 group delay/ToF를 생성하지 않는다. 부족한 bandwidth/phase sampling은 미평가, 추가 sampling 요청이다. pulse/window 변경은 파생응답만 재계산하며 원본 EM은 보존한다.

<a id="FN-029"></a>
### FN-029 NFC, LF/HF 코일과 부하 결합

**단계**: R3 - NFC/LF/HF 결합과 loaded/unloaded Q.

**연결 요구**: `PHY-002`, `PHY-018`, `PHY-063`, `PHY-083`
**B 보강**: `B::FED-008`, `B::TGT-007`
**화면**: `UI-17`, `UI-10`
**API**: `API-018`, `API-017`, `API-011`
**수식**: `EQ-025`, `EQ-026`, `EQ-028`
**근거**: `B-S45`, `NXP_AN12549`

- **입력:** coil geometry/ports or measured Z network, operating band, R/L/C model, self resonance, reader/tag load, coil separation/orientation, ferrite/metal conditions, chosen quasi-static/full-wave model.
- **검사, 처리:** lumped/유도결합 model 적용대역 검사 -> R/L/Q 및 self-resonance extraction -> 상대 coil이 있을 때만 M/k와 loading solve -> matching/loaded response 계산. Q 정의를 원 coil과 실제 load에 따라 구분한다.
- **출력:** unloaded/loaded Q, R/L/C, M/k, 부하 전달, 조건별 동작 공간 지표와 근사 범위.
- **실패, 변경영향:** self-resonance 근처에서 상수 L 식을 무조건 사용하지 않는다. ferrite/복소 mu 미지원은 명시하고 모델을 air로 바꾸지 않는다. 상대 coil, load가 없으면 coupling/output power를 만들지 않는다. geometry/material 변경은 새 solver 모델, 외부 load만 바뀌면 network 재사용 가능하다.

<a id="FN-030"></a>
### FN-030 UHF RFID 칩 공액 정합, 전력전달

**단계**: R3 - UHF RFID 칩 공액 전력전달 전문 평가.

**연결 요구**: `PHY-002`, `PHY-019`, `PHY-040`, `PHY-064`, `PHY-083`
**B 보강**: `B::TGT-007`, `B::FED-003`, `B::FED-006`
**화면**: `UI-17`, `UI-10`
**API**: `API-017`, `API-018`
**수식**: `EQ-027`, `EQ-028`, `EQ-040`
**근거**: `NXP_AN1715`, `NXP_AN1629`

- **입력:** antenna impedance/radiation data, packaged chip/strap impedance vs frequency/power/state, assembly reference plane, matching network, polarization/source conditions.
- **검사, 처리:** chip model와 실제 reference plane 일치 -> 허용 operating point 선택 -> complex conjugate power transfer 계산 -> available radiation/polarization 자료와 조건부 연결. chip operating point의 비선형 self-consistency는 지원 모델이 있을 때만 수행한다.
- **출력:** power-transfer coefficient, complex match, chip state/model revision, 불확실한 범위, radiation efficiency와 분리된 전달 지표.
- **실패, 변경영향:** 50 ohm S11을 RFID chip match로 대체하지 않는다. chip impedance 데이터 밖 power/state는 미검증이다. 실측 chip 또는 antenna update는 관련 파생결과만 갱신하고 pad/strap geometry 변경은 EM 재실행이다. read range를 자동 보증하지 않는다.

<a id="FN-031"></a>
### FN-031 메시, 경계, 시간 수렴과 주파수 표본화

**단계**: R1 - 메시, 경계, 시간 수렴; R2 - 적응형 주파수 표본화(AUG-002).

**연결 요구**: `PHY-048`, `PHY-049`, `PHY-050`, `PHY-053`, `PHY-085`, `PHY-087`, `AUG-002`
**B 보강**: `B::SIM-007`, `B::VAL-003`, `B::VAL-009`
**화면**: `UI-13`, `UI-22`
**API**: `API-019`, `API-013`, `API-016`, `API-020`, `API-021`
**수식**: `EQ-037`
**근거**: `OPENEMS_MESH`, `OPENEMS_NF2FF`

- **입력:** 동일 physical snapshot, ports, targets, numerical study plan(mesh/domain/time/angle 변수), run IDs, 비교 grid, metric, threshold provenance.
- **검사, 처리:** 비교에서 바뀌어도 되는 numerical dimensions만 다른지 검사 -> 유효 대역/포트/정규화 정렬 -> complex S, resonance tracking, gain/efficiency/pattern 등의 변화 계산 -> API-019에서 각 축 기준 판정. 추가 numerical run은 각 PreparedPlan을 API-013의 em_analysis 작업으로 제출한다. 다른 mode의 공진점을 단순 최저 S11 순위로 잘못 대응시키지 않는다. R2 적응형 주파수 계획은 API-020의 `study_type=adaptive_frequency`와 API-021을 사용하며 mask 경계, 복소 응답 변화, phase 변화를 선택한 오류 지표와 budget으로 평가해 추가 표본을 제안한다. 추가 실제 해석, 저장 시간자료에서 새로 변환한 표본, 보간 표본의 출처와 횟수를 각각 기록한다.
- **출력:** study table, 변경 수치조건, 비용, 지표별 차이, pass/fail/insufficient evidence, threshold source/project-policy.
- **실패, 변경영향:** 단일 run, 실패 run, 원 물리모델 변경, 기준면 불일치는 적절한 수렴 판정에 사용할 수 없다. 수렴은 측정 정확도의 증명이 아니다. 기준을 바꾸면 비교/판정만 재계산하고 raw run은 보존한다.

## 5. 탐색, 공차, 측정

<a id="FN-032"></a>
### FN-032 명시적 매개변수 스윕

**단계**: R1 - 명시적 스윕(AUG-001), 조합별 상태, 결과 추적.

**연결 요구**: `AUG-001`, `OPT-UI-002`, `PHY-076`, `JOB-004`, `JOB-005`
**B 보강**: `B::OPT-001`, `B::OPT-007`, `B::OPT-008`
**화면**: `UI-18`
**API**: `API-020`, `API-021`, `API-013`, `API-015`
**수식**: `EQ-035`
**근거**: `SKRF_MATCHING`

- **입력:** baseline snapshot, variable paths, units, explicit lists/ranges, Cartesian/paired mode, linked expressions, scenarios, job budget/cache policy.
- **검사, 처리:** API-020의 `study_type=grid_sweep`에서 변수 존재, dimension, 범위 검사 -> 정확 조합 수 계산 -> API-021로 study 제출 -> 각 candidate를 별도 immutable design으로 생성 -> geometry/constraints 검사 -> 필요한 계산 계층을 판별하여 raw EM 또는 외부회로 재사용 -> 작업과 결과 연결.
- **출력:** 모든 candidate ID, 입력, 상태, 실패 사유, run/derived IDs, metrics table. 유효 후보만 선택할 수 있지만 실패 후보는 이력에서 제외하지 않는다.
- **실패, 변경영향:** invalid combination은 이유와 함께 skip, solver failure는 실패 상태다. 취소 후 완료 후보 유지. 중단 후 실행할 미완료 조합을 명시하며 전체를 성공으로 표시하지 않는다.

<a id="FN-033"></a>
### FN-033 제약, 다목적, 다중 시나리오 최적화

**단계**: M/R2 - 기본 제약 자동 최적화; S/R2 - 다목적, Pareto, 고급 다중 시나리오.

**연결 요구**: `PHY-076`, `OPT-UI-001`, `OPT-UI-002`, `SYN-001`, `JOB-005`
**B 보강**: `B::OPT-002`, `B::OPT-003`, `B::OPT-007`, `B::TGT-006`, `B::VAL-007`
**화면**: `UI-18`
**API**: `API-020`, `API-021`, `API-018`
**수식**: `EQ-034`, `EQ-035`
**근거**: `SKRF_MATCHING`

- **입력:** bounded continuous/discrete/integer variables, objectives/normalization, hard constraints, scenarios, target revision, algorithm/version, seed, evaluation/time budget, termination criteria.
- **검사, 처리:** API-020의 `study_type=shape_opt` plan validation -> API-021 제출 -> candidate generation -> FN-009 precheck -> 필요 raw/derived/metric 평가 -> feasible 여부와 objectives를 분리 기록 -> algorithm update -> 예산/목표/중단 기준 평가. 외부 회로 전용 합성은 FN-018의 matching_synthesis 경로를 사용한다. 알고리즘은 R0 이후 검증된 구현으로 고정하며 이름만으로 성능을 약속하지 않는다.
- **출력:** Pareto set 또는 최선 유효 후보, 미달 목표, 실패, 비용, 종료 사유, complete candidate history, selected candidate independent re-evaluation plan.
- **실패, 변경영향:** invalid/failure/미수렴은 유효해로 rank하지 않는다. 모두 실패하면 `유효 후보 없음`이다. penalty는 내부 탐색 수단이며 feasible flag를 바꾸지 않는다. 글로벌 최적 보장이나 예측만으로 최종 승인하지 않는다.

<a id="FN-034"></a>
### FN-034 민감도, 공차, 상관, 수율

**단계**: R2 - 민감도, 공차, 상관, 수율.

**연결 요구**: `PHY-036`, `PHY-077`, `PHY-084`, `OPT-UI-001`
**B 보강**: `B::OPT-004`, `B::VAL-007`
**화면**: `UI-18`, `UI-19`
**API**: `API-020`, `API-021`, `API-018`
**수식**: `EQ-033`, `EQ-034`, `EQ-036`
**근거**: `ROGERS_RO4000_DS`, `ISOLA_FR408HR_DKDF`

- **입력:** nominal design, min/max/tolerance/분포, covariance, joint constraints, seed, sample count, selected metrics/targets, method(corner/local/Monte Carlo).
- **검사, 처리:** 분포 근거, covariance valid/PSD, 단위, 상관 일관성 검사 -> API-020의 `study_type=tolerance`에서 sampling 또는 finite difference 계획 -> API-021 제출 -> 각 sample에서 FN-009/해석 평가 -> sensitivity/uncertainty/yield with interval 계산. 단순 min/max를 근거 없이 Gaussian sigma로 바꾸지 않는다.
- **출력:** 명목, corner, 통계 결과, 실패, 불확실 표본을 포함한 분모 정책, seed, N, confidence method, dominant variables. 모델 불확실도와 제조 변동, 측정 불확실도를 구분한다.
- **실패, 변경영향:** 실패/미수렴 sample을 임의로 버리고 yield를 올리지 않는다. missing distribution은 bounded analysis로 제한하거나 입력을 요구한다. 표본/목표를 바꾸면 통계 결과를 새로 만들고 해당 raw 후보의 재사용을 판단한다.

<a id="FN-035"></a>
### FN-035 대리모델, AI 제안, 자유형상 역설계

**단계**: R3 - 대리모델, AI 제안, 자유형상 역설계(AUG-003).

**연결 요구**: `PHY-078`, `OPT-UI-003`, `AUG-003`, `PHY-089`, `NFR-006`
**B 보강**: `B::OPT-009`, `B::OPT-010`
**화면**: `UI-18`
**API**: `API-020`, `API-021`, `API-007`, `API-008`, `API-006`
**수식**: `EQ-035`
**근거**: `OS-S31`

- **입력:** versioned training runs, features, bounds, validation split, model type, design domain, minimum width/gap, connectivity/allowed layers, suggestion provenance, budget.
- **검사, 처리:** 데이터 누출/상태, 범위 검사 -> surrogate fit와 independent error evaluation -> 자유형상 탐색은 API-020의 `study_type=inverse_design`으로 계획하고 API-021 제출 -> uncertainty/OOD-aware candidate proposal 또는 allowed-shape generator -> editable physical graph 변환 -> topology/DRC -> 원 EM과 제조 출력으로 최종 재검증한다. 학습/예측 artifact와 실제 EM evaluation 횟수를 구분한다.
- **출력:** prediction과 actual result를 구분한 후보, training version, range, error, editable geometry, 근거와 변경안. AI 텍스트는 typed command preview로 변환한 뒤 적용하며 첨부 코드를 자동 실행하지 않는다.
- **실패, 변경영향:** R3 확장으로 support gate 통과 전 비활성. OOD, 미지원 gradient, 불가능한 최소 특징은 검증 결과로 승격하지 않는다. 좋은 S11 예측만으로 efficiency/gain/STEP/CAM 적합을 승인하지 않는다.

<a id="FN-036"></a>
### FN-036 Touchstone, 측정 CSV, 방사 실측 가져오기

**단계**: R1 - Touchstone/측정 CSV와 조건 입력; R2 - 고급 OTA/응용별 데이터 확장.

**연결 요구**: `PHY-079`, `PHY-081`, `PHY-082`, `PHY-083`, `PHY-084`
**B 보강**: `B::VAL-004`, `B::VAL-005`
**화면**: `UI-19`
**API**: `API-009`, `API-010`, `API-016`
**수식**: `EQ-011`, `EQ-012`
**근거**: `SKRF_NETWORKS`, `TI_AN058_SWRA161`

- **입력:** original file(s), format/profile, complex encoding, frequency/unit, Z0/wave definition, port order, sample/assembly revision, calibration/environment, date; optional OTA coordinate/polarization/power metadata.
- **검사, 처리:** parser schema, record size, frequency monotonic/duplicates, matrix shape, unit 검사 -> API-009의 missing metadata mapping preview -> 원본 bytes/hash 보존 -> API-010의 `target=project.measurements`, `expected_revision`과 동일 preview source hash 확인 -> canonical network/field dataset와 measurement metadata 저장한다.
- **출력:** measurement ID, raw dataset, validity mask, missing conditions, sample links. explicit CSV template 밖의 필드는 사용자 mapping 없이 추정하지 않는다.
- **실패, 변경영향:** unknown units/reference, port mismatch, mixed coordinates는 비교 가능 데이터 확정을 보류한다. 측정 수치 자체는 문헌/EM으로 재분류하지 않는다. 새 측정은 기존 EM을 바꾸지 않으며 비교/모델 보정의 입력이 된다.

<a id="FN-037"></a>
### FN-037 교정 기록, fixture 보상, 측정 정렬

**단계**: R1 - 교정/fixture/기준면 기록과 선언된 보정; R2 - 고급 독립 비교, 불확도, 확장 보정.

**연결 요구**: `PHY-080`, `PHY-081`, `PHY-082`, `PHY-083`, `PHY-084`, `PHY-086`
**B 보강**: `B::VAL-005`, `B::PRJ-009`
**화면**: `UI-19`, `UI-15`
**API**: `API-022`, `API-017`, `API-018`
**수식**: `EQ-012`, `EQ-031`, `EQ-033`
**근거**: `SKRF_CALIBRATION`, `SKRF_NETWORKS`

- **입력:** measurement/source networks, standard/fixture/calibration metadata, port permutation, coordinate transforms, Z0/reference planes, comparison run, allowed correction methods.
- **검사, 처리:** physical environment/sample/plane 차이 inventory -> 지원 calibration/deembed/extension의 필수 data 검사 -> immutable derived measurement 생성 -> overlap grid와 coordinates에서 EM/측정 비교 -> residual/uncertainty 보고. 이미 교정된 instrument 결과를 기록하는 작업과 표준 측정으로 교정을 계산하는 작업은 구분한다.
- **출력:** aligned dataset IDs, processing chain, 원본 overlay, 조건 불일치, 주파수별 complex residual, uncertainty record.
- **실패, 변경영향:** fixture 없음, 특이 network, noise 증폭, 사용범위 밖이면 보정 결과를 valid로 표시하지 않는다. 임의 frequency shift/amplitude fitting은 원본 comparison이 아닌 보정된 비교다. 원측정과 raw EM은 보존된다.

<a id="FN-038"></a>
### FN-038 선택 VNA 어댑터의 직접 데이터 수집

**단계**: C/R3 - 검증된 VNA 장비의 선택 직접 취득; 기본 파일 입력은 이 기능에 의존하지 않음.

**연결 요구**: `MEAS-001`, `PHY-079`, `PHY-080`, `NFR-006`, `JOB-002`
**B 보강**: `B::VAL-004`
**화면**: `UI-19`, `UI-23`
**API**: `API-001`, `API-013`, `API-015`, `API-028`, `API-009`, `API-010`
**수식**: 없음 - 장비 데이터와 조건 수집
**근거**: `SKRF_NETWORKS`

- **입력:** 검증된 instrument adapter/model, connection address, acquisition plan, selected sample revision, requested trace, ports, frequency, instrument calibration state where readable.
- **검사, 처리:** adapter capability/transport 검사 -> 장비 식별, 설정 읽기 -> 장비, 교정 상태와 명시적 측정 명령을 가진 `TaskPlan.kind=instrument_acquisition`을 API-013으로 제출 -> 실제 sweep/grid/reference/calibration 상태 수집 -> FN-036의 preview 및 `project.measurements` commit 경로로 원본 보존한다. 장비 취득에 EM AnalysisPlan, PreparedPlan을 요구하지 않는다.
- **출력:** measurement run, 실제 장비 정보, 취득 조건, 원본 network, 로그. 장비가 알려주지 않는 calibration validity는 unknown이다.
- **실패, 변경영향:** 미지원 장비는 파일 import 경로 제공. disconnect/timeout/부분 취득을 완전 measurement로 저장하지 않는다. R1 core를 장비 연결에 종속시키지 않는다. 설정 변경, 교정 수행은 read-only 취득과 구별된 명시 operation을 가진 지원 adapter에서만 제공한다.

<a id="FN-039"></a>
### FN-039 실측 기반 모델 보정과 독립 검증

**단계**: R2 - 변수 보정, 원설계 보존, 독립 검증; 고급 fitting은 모델별 지원 gate.

**연결 요구**: `PHY-086`, `PHY-084`, `PHY-036`, `OPT-UI-001`
**B 보강**: `B::OPT-006`, `B::VAL-005`, `B::VAL-007`
**화면**: `UI-19`, `UI-18`
**API**: `API-022`, `API-020`, `API-021`, `API-003`, `API-018`
**수식**: `EQ-033`, `EQ-034`, `EQ-035`
**근거**: `SKRF_CALIBRATION`, `TI_AN058_SWRA161`

- **입력:** aligned measurement/EM, variable/fixed parameter declarations, prior bounds, uncertainty, training vs independent sample/band set, objective/residual definition.
- **검사, 처리:** 조건 불일치를 먼저 검토 -> 보정 가능한 변수와 식별성, 상관 문제 검사 -> API-020의 `study_type=model_calibration`과 API-021로 제한된 parameter fitting -> 새 candidate revision -> 보정에 쓰지 않은 데이터에서 검증. 자료 오류, fixture 차이를 material fit으로 자동 흡수하지 않는다.
- **출력:** original/fit model, 변경값, 근거, train/test residual, 불확실성, 남은 mismatch, 별도 verification state.
- **실패, 변경영향:** 범위 밖 물성, 비식별 변수, 독립 데이터 없음은 제한을 표시한다. 한 시료 fit은 일반 정확도 보증이 아니다. 보정값은 사용자 선택 전 원설계를 덮어쓰지 않으며 적용 후 해당 solver 입력의 새 run을 요구한다.

## 6. 출력, 검증, 인계, 자동화

<a id="FN-040"></a>
### FN-040 연관 치수 도면, PDF, SVG, DXF

**단계**: R1 - PDF/SVG/DXF, 연관 치수, 실척 형상; R2 - 확장 자동 표와 상세 도면 기능.

**연결 요구**: `OUT-001`, `CAD-005`, `PHY-068`, `OUT-009`
**B 보강**: `B::DRW-001`, `B::DRW-002`, `B::DRW-003`, `B::DRW-004`, `B::DRW-005`
**화면**: `UI-20`
**API**: `API-023`, `API-024`, `API-025`
**수식**: `EQ-001`, `EQ-002`, `EQ-039`
**근거**: `OS-S22`, `OS-S26`

- **입력:** physical snapshot, entities/layers/views, associative dimension definitions, manual note distinction, paper/scale, 1:1 pattern policy, origin, units, tau2D, curve profile, title/stackup data.
- **검사, 처리:** 출력 대상, 단위, 좌표 preview -> semantic geometry에서 도면 뷰/치수 도출 -> 문서 주석과 copper geometry를 다른 channels로 구성 -> 지원 analytic arcs 또는 허용 chord-error approximation -> vector PDF/SVG/DXF 생성 -> FN-043 verification.
- **출력:** 파일, model-linked dimension IDs, export options, revision, inspection manifest. 수동 치수 문구는 측정치와 다른 속성이다. 검정선, 축척, 총두께 정의를 표시한다.
- **실패, 변경영향:** unresolved dimension, 단위없음, 곡선 tolerance 초과, 텍스트 혼입을 실패/경고로 기록한다. 출력 축척은 물리/EM hash 변화 없음. 미해석 설계도 도면 생성 가능하지만 보고서에는 미평가 상태를 유지한다.

<a id="FN-041"></a>
### FN-041 실제 동박 STEP, 바디 대응, RF 동반 명세

**단계**: R1 - 실제 동박 STEP, 바디/층/비아, RF sidecar, 검증된 schema.

**연결 요구**: `OUT-004`, `OUT-005`, `OUT-009`, `CAD-001`, `PHY-029`
**B 보강**: `B::STP-001`, `B::STP-002`, `B::STP-003`, `B::STP-004`, `B::STP-005`, `B::STP-006`, `B::STP-007`, `B::STP-008`, `B::STP-009`, `B::STP-010`
**화면**: `UI-20`, `UI-06`
**API**: `API-008`, `API-023`, `API-024`, `API-025`
**수식**: `EQ-039`
**근거**: `OS-S22`, `OS-S26`

- **입력:** valid physical BREP, stackup/actual copper, via barrels, parts, validated STEP profile/schema, units/origin, body merge/include policy, tauCAD, RF semantic metadata.
- **검사, 처리:** 필수 바디 및 실체 여부 검사 -> body naming/assembly/source UUID mapping -> actual solids export -> 같은 snapshot의 material/net/port/solver semantics를 sidecar에 저장 -> 독립 reader reimport validation. 지원 STEP schema는 실제 CAD adapter 검증 결과로 확정한다.
- **출력:** STEP, RF sidecar, body map, included/omitted/simplified list, model/export hashes, validation result. 시각화 mesh, 보드 외곽만 있는 파일은 필수 STEP 완료가 아니다.
- **실패, 변경영향:** 얇은 copper 소실, 열린 solid, 구멍 메움, pad display offset, 필수 바디 누락은 차단한다. EM sheet approximation을 physical STEP에 사용하지 않는다. output profile 변경은 export만 재생성하며 raw EM은 유지한다.

<a id="FN-042"></a>
### FN-042 KiCad, Gerber, Excellon, Job, BOM 출력

**단계**: R1 - KiCad/Gerber/Excellon/기본 Job, DRC; R2 - matching BOM, 실장 변형/좌표(AUG-004); R3 - 추가 CAM/EDA 형식.

**연결 요구**: `OUT-002`, `OUT-003`, `OUT-009`, `OUT-010`, `PHY-022`, `CAD-010`, `AUG-004`
**B 보강**: `B::FAB-001`, `B::FAB-002`, `B::FAB-003`, `B::FAB-005`, `B::FAB-006`, `B::FAB-007`, `B::FAB-008`, `B::FAB-009`
**화면**: `UI-21`
**API**: `API-023`, `API-024`, `API-025`, `API-006`
**수식**: `EQ-002`, `EQ-039`
**근거**: `OS-S17`, `B-S35`, `B-S36`

- **입력:** physical snapshot, nets/layers/pads/vias/holes/keepouts, selected EDA/CAM profile, units/origin, precision, zone fill policy, manufacturing rules, stackup confirmation, matching circuit/variant, BOM/placement mapping.
- **검사, 처리:** supported entity/format inspection -> DRC와 RF critical feature 검사 -> editable KiCad tracks/pads/zones/vias/net mapping 또는 CAM layer generation -> PTH/NPTH/slots 출력 -> Job/stackup/RF sidecar, file manifest -> FN-043 verification. 회로 부품 ID, 실장 state, PCB pads를 BOM과 대조한다.
- **출력:** declared-profile board/footprint, Gerber/Excellon, Job, 제조 명세, 제한, BOM CSV, placement where supported. 보드와 footprint 용도는 다른 결과물이다.
- **실패, 변경영향:** 지원하지 않는 객체를 삭제하고 전체 왕복 성공으로 표시하지 않는다. export 후 copper fill 재계산이 feed gap/slot/keepout을 바꾸면 검사 실패다. IPC-2581/ODB++ 등은 별도 adapter/reader 검증 전 미지원. variant 변경은 BOM과 해당 물리/회로 계층을 정확히 갱신한다.

<a id="FN-043"></a>
### FN-043 출력 재열기, 형상, 연결, 좌표 검증

**단계**: R1 - 필수 2D/STEP/CAM의 독립 재열기와 의미 검수.

**연결 요구**: `OUT-006`, `OUT-009`, `CAD-005`, `PHY-022`, `PHY-068`
**B 보강**: `B::DRW-002`, `B::STP-008`, `B::FAB-005`, `B::FAB-006`, `B::FAB-007`
**화면**: `UI-20`, `UI-21`, `UI-22`
**API**: `API-025`, `API-009`, `API-006`
**수식**: `EQ-002`, `EQ-039`
**근거**: `OS-S26`, `OS-S22`

- **입력:** frozen model plus exported files/profile/manifest, independent reader implementation or external validation record, tolerances, critical feature IDs, expected topology/body/layer/hole map.
- **검사, 처리:** syntax/file integrity -> independent re-read -> units/origin/top-bottom/rotation 확인 -> local critical dimensions/boundary distance, gap/slot/hole/connectivity 비교 -> body/layer/net preservation, global area/volume/centroid 보조 검사 -> DRC 결과 결합. 거리 상한은 정확 BREP 연산 또는 오차가 유계인 tessellation으로 평가하고, 상한 없는 점 표본 Hausdorff는 추정값으로만 기록한다.
- **출력:** 파일별 written/parseable/geometry/topology/semantic 검사 세부값, actual deltas, issue locations, reader/version, tolerance provenance와 `ExportStatus`. 파일 생성은 generated_unverified, 선언 profile의 필수 검사가 실제 통과한 뒤만 verified_profile이다. 동일 writer 코드를 역으로 호출한 것만으로 독립 reader 검증을 충족하지 않는다.
- **실패, 변경영향:** area/volume 합계가 같아도 feed gap 소실은 실패다. 미지원 reader/schema 또는 상한이 필요한 검사에 추정 오차만 있으면 해당 검증은 미완료다. file write success로 verify를 대체하지 않는다. 검사 정책이 바뀌면 verify/report만 새로 생성한다.

<a id="FN-044"></a>
### FN-044 기준 시험, 근거 승격, 검토 보고서

**단계**: R1 - 기본 benchmark, 상태 분리, 검토 보고서; R2/R3 전문 사례는 해당 기능과 함께 검증.

**연결 요구**: `PHY-085`, `PHY-086`, `PHY-087`, `PHY-088`, `DAT-005`, `PHY-089`, `NFR-008`, `NFR-009`
**B 보강**: `B::LIB-005`, `B::VAL-001`, `B::VAL-002`, `B::VAL-003`, `B::VAL-008`, `B::VAL-009`, `B::PRJ-010`
**화면**: `UI-22`, `UI-24`
**API**: `API-018`, `API-019`, `API-025`, `API-027`, `API-024`
**수식**: `EQ-013`, `EQ-017`, `EQ-037`, `EQ-039`
**근거**: `TI_AN058_SWRA161`, `OPENEMS_PORTS`, `OPENEMS_NF2FF`

- **입력:** benchmark/version, VT plan, required evidence, raw/derived/run/measurement/export reports, target snapshot, tolerance sources, template promotion criteria.
- **검사, 처리:** evidence completeness/source conditions -> 실행/수렴/물리/목표/제조/측정 status separately derive -> 요구, 기능, VT trace join -> 사용 입력, 가정, 누락, 오류, scope를 포함한 report 생성. template promotion은 필요한 증거를 검토하고 특정 범위에만 부여한다.
- **출력:** machine-readable verification report, PDF/편집 가능한 검토 보고서, traceability, 미실행 항목, residual risks, source links. 현재 문서의 시험 계획을 실행 결과로 기록하지 않는다.
- **실패, 변경영향:** 미해석/미수렴, reference mismatch, 독립 데이터 없음은 그대로 남긴다. 동일 solver 반복은 독립 solver 검증이 아니다. 보고서 생성 성공은 인증, 제품 승인 상태를 올리지 않는다. target/analysis/measurement/export 선택 변경은 보고서를 새로 생성한다.

<a id="FN-045"></a>
### FN-045 프로젝트 archive, 전체 인계 묶음

**단계**: R1 - 완전성 검증을 포함한 선택 인계 archive와 복구.

**연결 요구**: `OUT-008`, `DAT-006`, `NFR-004`, `NFR-005`, `NFR-006`, `JOB-006`
**B 보강**: `B::PRJ-006`, `B::FAB-007`, `B::VAL-008`, `B::NFR-002`
**화면**: `UI-02`, `UI-22`
**API**: `API-026`, `API-004`, `API-009`, `API-010`
**수식**: 없음 - manifest, hash, 경로, 참조 검사
**근거**: `OS-S27`, `OS-S28`, `OS-S50`

- **입력:** selected immutable snapshot, project/material/ref subsets, runs/results/exports/reports, license redistribution flags, include/exclude list, package profile.
- **검사, 처리:** 참조 closure와 파일 존재/hash 확인 -> 미포함, 미확보, 배포 제한 자료 목록 -> secret/path 정리 -> staged package/manifest 생성 -> archive safe path, size, symlink policy 검사 -> 새 환경에서 프로젝트 재열기 contract 검증 -> 확정 파일 생성.
- **출력:** portable project package, file manifest/hash, tool versions, schema, missing/limited evidence, verification status. raw field 등 큰 선택 파일 제외는 명시하고 그에 따른 재후처리 불가 범위를 기록한다.
- **실패, 변경영향:** path traversal, 손상, 누락 필수 파일, disk full은 package 확정 실패다. 원자료 포함 권리 불명확은 링크/metadata만 인계할 수 있다. 원본 설계/완료 결과를 삭제하지 않는다. archive import는 FN-001/005/010의 동일 검사 경로를 따른다.

<a id="FN-046"></a>
### FN-046 GUI, CLI 일치, 로컬, WSL, 선택 원격 운영

**단계**: R1 - 공통 명령 경로, Linux 및 Windows+WSL2 출시 게이트, 오프라인; R2 - 공개 batch API/CLI 확장, R3 - 선택 원격/HPC.

**연결 요구**: `PRJ-010`, `INT-004`, `INT-005`, `INT-006`, `JOB-007`, `NFR-001`, `NFR-002`, `NFR-003`, `NFR-006`, `NFR-007`
**B 보강**: `B::OPT-008`, `B::NFR-005`, `B::NFR-006`, `B::NFR-007`, `B::NFR-008`
**화면**: `UI-14`, `UI-23`
**API**: `API-001`, `API-002`, `API-003`, `API-013`, `API-014`, `API-015`, `API-028`, `API-029`, `API-026`
**수식**: 없음 - transport, 명령 라우팅, 실행 정책
**설계 근거**: `DES-URS-003`, `DES-URS-004`, RFAD 24의 GUI 비교 및 RFAD 07의 프로세스 경계

- **GUI 선택 경계:** wxWidgets C++를 우선 평가하고 Avalonia C#과 비교한다. 이는 낮은 메모리 사용 가능성에 대한 가설이며 실제 측정 전 우위를 확정하지 않는다. Qt는 신규 GUI 구현과 배포 경로에서 제외한다. GUI toolkit은 canonical 데이터나 worker 계약에 침투하지 않으며 선택 절차는 RFAD 24/25를 따른다.
- **자원/응답 계약:** 표와 트리의 가상화, 보이는 결과의 범위 조회, 입력 이벤트 합치기, 비동기 작업, 메모리/로그/표시 버퍼 한도를 적용한다. 기능별 상세 정책은 1.6/1.7절을 따른다. CPU-bound 전처리와 전체 파일 parse를 GUI 이벤트 스레드에서 수행하지 않는다.
- **입력:** same typed commands as GUI, project/plan IDs, runtime profile(local Linux/Windows UI+WSL2), worker transport/path mapping, resource limits, optional remote destination/transfer selection.
- **검사, 처리:** capabilities handshake -> schema/version/path/permissions 검사 -> 동일 domain command dispatch -> structured progress/status/error 반환. GUI가 실행한 작업과 CLI가 실행한 작업은 같은 snapshot/hash/validation pipeline을 사용한다. 한국어 UI의 명령, 상태, 오류를 접근 가능한 이름과 키보드 명령으로 노출하고, 포커스, 선택, 숫자와 단위 표시는 UI-01의 계약을 따른다.
- **출력:** batch-readable results, exit mapping, logs, artifacts, runtime/version/transport metadata. offline은 설치된 자료/solver 범위에서 동작하며 external download가 필요한 기능과 구분한다.
- **실패, 변경영향:** 한글/공백 경로, WSL 변환, worker 종료, 취소, 인증정보 누출을 출시 gate에서 검증한다. remote는 전송 대상/파일 manifest와 정책을 명시하며 자동 업로드하지 않는다. plugin/import script를 일반 data open과 함께 실행하지 않는다. 아직 검증하지 않은 OS, GPU, solver를 supported로 광고하지 않는다.

## 7. 기능 간 실행 순서

### 7.1 기본 해석과 산출물

`FN-001/002 -> FN-003/004 -> FN-006/007 또는 FN-008/010 -> FN-011/014/015/016/013 -> FN-009/019/020 -> FN-021/022 -> FN-023/024 -> 필요한 경우 FN-026 -> FN-025 -> FN-031 -> FN-040/041/042/043 -> FN-044/045`. 방사 지표는 필요한 복소 장 합성과 방사 전력 적분이 먼저 끝나야 한다.

이 순서는 대표 흐름이다. 도면, STEP, 제조 출력은 필수 물리 입력이 완비되면 해석 실행 전에도 생성할 수 있다. 다만 해당 파일/보고서의 EM, 실측 미평가 상태는 그대로 남는다. 환경이나 형상 변경은 의존성 graph에서 필요한 단계만 다시 수행한다.

### 7.2 외부 정합/여기 변화

`유효 raw -> FN-017/024 -> 필요한 경우 FN-026/027의 복소 장 및 전력 계산 -> FN-025 목표 판정 -> 보고서`를 사용한다. basis가 충분하지 않은 출력은 새 full-wave 작업이 필요하다. 부품 단순값만 바뀌는 조건과 pad/trace 모델까지 바뀌는 조건을 구별하는 회귀시험을 반드시 포함한다.

### 7.3 적응형 주파수 표본화

`AUG-002`는 FN-031/033이 raw 데이터의 coverage와 phase, resonance 변화에서 추가 표본 요구를 만들고, FN-020/021/022가 필요한 solver 작업 또는 저장 time-domain 데이터의 검증된 추가 변환을 수행하는 경로다. 단순 보간은 raw solve sample로 승격하지 않는다. group delay에는 FN-028의 표본 검사를 함께 적용한다. solver가 제공하지 않는 적응 solve를 메뉴 이름만으로 지원하지 않는다.

## 8. 구현과 검수 시 지켜야 할 경계

- `geometry.build` 성공만으로 STEP, Gerber, EM 결과가 생긴 것으로 처리하지 않는다. 각 export/solver adapter와 검수 결과가 필요하다.
- 물리 두께를 UI, STEP에는 사용하면서 solver가 무엇을 사용했는지 숨기지 않는다. 원 데이터, 선택 모델, 실제 전달값을 나란히 기록한다.
- 도메인 함수에서 물리량, 전력, wave 정의를 결정하고 화면/보고서에서 다른 공식을 중복 구현하지 않는다. EQ ID와 알고리즘 버전을 결과에 연결한다.
- external circuit, 목표, 표시 변경에 대한 cache 재사용과 physical/solver 변경 무효화를 서로 다른 시험으로 확인한다.
- UI error banner만으로 유효성을 관리하지 않는다. 같은 invalid state가 API/CLI, 파일, 보고서에도 나타나야 한다.
- 검증 절차, 성능 목표, 지원 matrix는 [RFAD 14](14_RFAD_검증과_수용_기준.md)의 실제 시험 결과로 갱신한다. 현재 문서는 구현할 계약이며 완료 주장이나 승인 기록이 아니다.

## 9. 근거

본문의 API, FN, UI, cache 경계, 자료 구조는 통합 설계 결정이다. 공개 라이브러리의 기능, 개념 근거는 [openEMS materials](https://docs.openems.de/en/latest/concepts/properties.html), [mesh](https://docs.openems.de/en/latest/concepts/mesh.html), [ports](https://docs.openems.de/en/latest/python/openEMS/ports.html), [NF2FF](https://docs.openems.de/en/latest/python/openEMS/nf2ff.html), [scikit-rf networks](https://scikit-rf.readthedocs.io/en/latest/tutorials/Networks.html), [calibration](https://scikit-rf.readthedocs.io/en/latest/tutorials/Calibration.html), [CadQuery import/export](https://cadquery.readthedocs.io/en/latest/importexport.html), [OCCT STEP](https://www.occt3d.com/dev/doc/overview/html/occt_user_guides__step.html)이다. 공식 문서의 기능 소개는 본 제품의 실행, 정확도, 왕복 검증 기록을 대신하지 않는다. 상세 source ID, 버전, 원문 locator는 [RFAD 18](18_RFAD_출처와_근거.md)과 [RFAD 20](20_RFAD_참고_자료_통합.md)을 따른다.
