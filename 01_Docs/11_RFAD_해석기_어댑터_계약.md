# 해석기 어댑터, API, 실행 계약

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

관련 문서: [아키텍처](07_RFAD_소프트웨어_아키텍처.md), [수식](09_RFAD_수식과_물리_모델.md), [검증](14_RFAD_검증과_수용_기준.md).

## 1. 범위

이 문서는 application service API와 worker protocol, 최초 openEMS adapter가 주고받을 의미를 정의한다. 함수명은 RFAD 내부 계약이며 아래 이름이 외부 라이브러리에 이미 존재한다고 주장하지 않는다. 외부 openEMS의 확인 API는 7절에 별도로 적는다.

## 2. 공통 message envelope

transport framing은 UTF-8 NDJSON. 각 JSON message는 JSON-RPC 2.0을 따른다. request의 `params`에는 `contract_version`, `context`, `input`을 사용한다. mutation/작업 접수에는 `request_key`를 넣고 같은 key+같은 payload는 같은 결과를 반환한다. 다른 payload로 key를 재사용하면 E_CONFLICT다.

request_key의 authority와 epoch는 capabilities.get의 idempotency_policy에서 받는다. server가 발급한 `request_key_epoch`의 신규 접수 유효기간은 최대 7일이며 client가 연장하지 못한다. 최초 접수 전에 key, method, project/catalog scope, expected revision, canonical payload hash, job/result ref와 receipt `accepted_at/expires_at`을 durable journal에 기록한다. receipt의 보관 기간은 최초 접수부터 7일이다. 기존 receipt가 있으면 epoch의 신규 접수 기간이 끝났어도 해당 expires_at까지 같은 결과를 돌려준다. receipt가 없고 epoch가 만료되었거나 인식되지 않으면 E_IDEMPOTENCY_EXPIRED를 반환한다. 이 순서로 오래된 key가 새 작업으로 잘못 접수되는 것을 막는다. 재접속/재시도는 원 key와 epoch를 그대로 사용하며 timeout을 이유로 key를 교체하지 않는다. 만료 후에는 authoritative 상태/원 작업 결과를 조회하고 사용자 재접수 의사를 확인한 별도 명령만 새 key를 사용한다. 보관 기간과 epoch 정책은 wire handshake에서 고정하는 설계 제안이다.

mutation과 job 접수는 journal 용량 및 recovery record를 먼저 확보하고 commit 후 ACK한다. 용량을 확보하지 못하면 E_RESOURCE로 거부하며 실행부터 시작하지 않는다. key와 receipt는 실제 변경/job 접수와 같은 원자적 commit 경계를 사용한다. 재시작 후에도 동일한 응답을 복구할 수 있어야 한다.

```json
{
  "jsonrpc": "2.0",
  "id": "req-0001",
  "method": "solver.plan",
  "params": {
    "contract_version": "rfad.api/2.0",
    "request_key": "example-request-key",
    "request_key_epoch": "example-server-issued-epoch",
    "context": {"project_id": "example-project", "snapshot_id": "example-snapshot"},
    "input": {"analysis_definition_id": "analysis-01", "runtime_profile_id": "linux-openems-r0"}
  }
}
```

위 ID는 message 구조를 설명하는 예시 문자열이며 실제 project EntityId는 UUID 계약을 따른다. 실패 응답은 `error={code,message,data}`이고 data에 domain_code/diagnostics를 넣는다. 표준 parse/request/method/params error는 JSON-RPC 규격을 따르며 제품 오류는 양의 application code 영역을 사용한다. registry가 numeric 매핑을 한 곳에서 관리해 UI가 한국어 문구로 분기하지 않게 한다.

source: [JSON-RPC 2.0 공식 규격](https://www.jsonrpc.org/specification). framing, request_key, artifact semantics는 본 설계의 추가 계약이다.

문서 개정 3.0과 wire의 `contract_version=rfad.api/2.0`은 서로 다른 버전이다. 구현 전에 schema revision과 capabilities handshake로 지원 필드/limits를 협상한다. 모르는 필수 필드를 무시하거나 의미가 달라진 payload를 같은 계약으로 소비하지 않는다.

metadata frame의 최대 크기는 1 MiB이며 control frame은 64 KiB 이내로 제한하고 우선 처리한다. binary field/mesh/전체 로그를 NDJSON이나 base64로 실어 보내지 않는다. 큰 데이터는 ArtifactRef와 shape/dtype/단위/ROI로 참조하고 08의 무결성 및 파일 수명 계약을 따른다. 길이 제한은 JSON 전체를 메모리에 올리기 전에 적용한다. stdout에는 protocol만, native stdout/stderr에는 별도 로그 채널을 사용한다. UI 로그는 최대 10 Hz로 일괄 전달하고 최근 10000행의 bounded tail을 유지한다. 원 로그는 용량 정책을 가진 파일에 보존하며 tail 생략량을 표시한다. pending response/event queue도 유한하게 두고 읽기 지연 시 backpressure를 적용한다. control 우선순위가 긴 frame 쓰기에 막히지 않도록 별도 control queue/transport 또는 작은 frame 단위의 fair scheduling을 사용한다. 이 수치는 [아키텍처](07_RFAD_소프트웨어_아키텍처.md)의 설계 예산이며 측정 완료값이 아니다.

## 3. operation 목록

API 표의 snapshot은 immutable ID+hash, artifact는 manifest로 검증한 ArtifactRef다. 아래 작업형 method는 항상 접수 시 TaskRef(job_id, state, events_cursor)를 반환하고 완료 event에 operation_result와 아래 표의 최종 output refs를 전달한다. 처리 시간이 짧거나 cache hit이어도 반환형을 바꾸지 않는다. 동기 query/명령은 작은 결과를 직접 반환하며 result.open은 metadata/ROI 조회로 유지한다. 이 비동기 분류도 아직 구현 전인 wire 2.0 설계안이며 설치본 호환 완료를 주장하지 않는다.

| 호출 분류 | API ID | TaskPlan.kind 또는 응답 |
| --- | --- | --- |
| 비동기 자료 처리 | 002, 004, 005, 006, 007, 009, 011, 017, 018, 019, 020, 022 | data_processing, operation_method로 구분 |
| 비동기 CAD 생성 | 008 | cad_build |
| 비동기 EM 준비 | 012 | em_prepare |
| 비동기 출력/검사/패키지 | 023, 024, 025, 026 | export |
| 비동기 정합 탐색 | 030 | study, study_type=matching_synthesis |
| 동기 조회 | 001, 015, 016, 027 | 제한된 metadata 또는 페이지 결과 |
| 동기 원자적 명령 | 003, 010 | revision/변경 참조. 큰 입력은 준비된 artifact로 참조 |
| 동기 작업 접수/재개 | 013, 021, 029 | 실제 계산은 별도 실행; TaskRef 반환 |
| 동기 제어 | 014 | 요청 접수 또는 이미 확정된 terminal 상태 |
| notification | 028 | response 없음 |

API-002의 project handle, API-005의 SnapshotRef 및 API-011의 AnalysisPlan도 작업 완료 결과에서 받는다. API-003/010은 큰 파일 parsing이나 BREP 생성을 transaction 안에서 실행하지 않는다. API-017/018의 계산 결과를 API-016이 읽을 때 작업 상태와 artifact 준비 여부를 먼저 확인한다.

| ID / method | input 주요 필드 | output | 핵심 guard |
| --- | --- | --- | --- |
| API-001 `capabilities.get` | runtime/adapter IDs, optional requested feature set | environment/feature matrix/tested envelopes, idempotency_policy | 프로세스 시작 가능성과 검증 완료를 구별 |
| API-002 `project.open` | path/artifact, open_mode=open/create/copy/recover, create 시 name | document/initial-or-existing revision/diagnostics | 모든 open_mode에 request_key 필수; 기존 경로 덮어쓰기 금지 |
| API-003 `project.apply_command` | expected_revision, command_id/type/payload | new_revision, changed IDs, invalidation set | 단위, cycle, transaction |
| API-004 `project.save` | expected_revision, target | saved_revision, checksum | atomic replace/recovery |
| API-005 `snapshot.create` | expected_revision, description | immutable snapshot ref | unresolved required values에 목적별 상태 |
| API-006 `design.validate` | snapshot/draft, purpose, profile | diagnostics and validation report | 목적별 필수/선택 입력 |
| API-007 `template.synthesize` | target IDs, space/stackup, template IDs, bounds | candidates with assumptions and constraints | 적용조건 밖 추천은 미검증 |
| API-008 `geometry.build` | snapshot, projection kind/profile | planar/B-rep/render artifacts and map | exact-vs-tessellated 구분 |
| API-009 `import.preview` | artifact, declared format/profile | entities/missing fields/mapping proposal | 크기/경로/문법/버전 |
| API-010 `import.commit` | preview ID, target, mapping/decisions, expected target revision | new entities/project-or-catalog revision | preview hash 동일, 대상 저장소 transaction |
| API-011 `solver.plan` | snapshot, analysis/runtime profile | immutable plan+model report+resource estimate | capability, ports/material/observables |
| API-012 `solver.prepare` | AnalysisPlan ref, request_key, resource budget | 접수: em_prepare TaskRef; 완료: PreparedPlan + PreparationArtifact | original plan 불변, 새 preparation hash |
| API-013 `job.submit` | TaskPlan(kind, plan ref, input manifest), budget | TaskRef | kind별 준비 완료 guard, request_key 중복 방지 |
| API-014 `job.cancel` | job ID, reason | 진행 중이면 cancel_requested; terminal이면 확정 상태 | 멱등 취소, 실제 종료 확인, 완료 경합 규칙 |
| API-015 `job.status` | job ID, cursor | state/events/artifacts | 종료 원인/partial 보존 |
| API-016 `result.open` | artifact ID, selection/ROI | metadata + array/file references | 조회는 새 계산을 시작하지 않음; 축/단위/정규화/hash |
| API-017 `network.derive` | raw network, transformation chain/circuit/drive | derived network + field coefficients | wave/Z0/plane/conditioning |
| API-018 `metrics.evaluate` | result refs, metric/target profile | metric records, assessment | 미평가, 미수렴과 pass 구분 |
| API-019 `convergence.compare` | run set, comparison profile | deltas/evidence/status | 동일 물리모델/서로 다른 수치조건 |
| API-020 `optimization.plan` | study_type, snapshot, variables/objectives/constraints/budget | StudyPlan | sweep/adaptive/optimization/tolerance/calibration별 필수입력 |
| API-021 `optimization.submit` | study plan | TaskRef + candidate events | 예산, seed, raw cache |
| API-022 `measurement.align` | raw data, port/plane/transform/fixture | aligned dataset + processing chain | 원본불변, 실제 조건 확인 |
| API-023 `export.preview` | snapshot/results, format/profile | inclusion/omission table + blockers | undefined material/geometry policy |
| API-024 `export.build` | accepted profile, snapshot | generated_unverified artifacts | 입력과 output manifest 연결 |
| API-025 `export.verify` | generated files/source snapshot/profile | roundtrip evidence/status | 독립 reader와 topology 검사 |
| API-026 `package.build` | selected artifact IDs, inclusion policy | archive+manifest+missing refs | hash/license/path checks |
| API-027 `evidence.query` | filters/source IDs/record IDs | source/model/validation records | source version과 value 상태 |
| API-028 `worker.events` | notification의 job_id/seq/state/progress/diagnostics | response 없음 | 중복 seq idempotent 처리 |
| API-029 `job.resume` | job ID, checkpoint ref | 새 run TaskRef + parent relation | backend 보증/입력, version 일치 |
| API-030 `matching.synthesize` | antenna network, topology/part/target/budget | candidate circuits + performance | 네트워크/field/실물 배치 범위 |

### 3.1 생성, snapshot, import의 정확한 의미

`project.open(open_mode=create)`는 작업 완료 결과에 신규 project UUID와 initial revision을 포함한다. 기본값은 단위/좌표/빈 컬렉션뿐이며 유전율, 포트, 결과를 임의 생성하지 않는다. API-003은 그 이후의 expected_revision을 필수로 받는다. copy는 source를 보존한 새 project ID를 생성한다.

SnapshotRef는 별도 snapshot UUID, revision_id, content hash, schema/version과 봉인 시점을 갖는다. snapshot_id를 revision_id의 별칭으로 사용하지 않는다. 같은 revision에서 중복 snapshot 생성은 content hash로 재사용할 수 있다. 결과/sidecar에는 두 ID를 명시한다.

import.commit의 target은 project.geometry/project.measurements/catalog.templates/catalog.materials 중 지원한 목적을 명시한다. project 대상은 expected_revision, catalog 대상은 expected_catalog_revision을 검사한다. catalog 업데이트가 기존 project에 고정된 material/template 버전을 자동 교체하지 않는다.

### 3.2 TaskPlan, StudyPlan과 상태

TaskPlan은 plan_id, kind, input artifact hashes, runtime profile, resource budget, output roles, prerequisites를 가진 공통 계획이다. kind는 data_processing/em_prepare/em_analysis/cad_build/export/study/instrument_acquisition으로 구분한다. data_processing은 operation_method, typed input 또는 원본 artifact, algorithm/schema version을 가지고 import/network/metric/계획 생성을 수행하며 PreparedPlan을 요구하지 않는다. em_prepare는 AnalysisPlan을 입력으로 받아 native model/mesh를 준비한다. em_analysis는 그 결과로 봉인된 PreparedPlan을 필수로 한다. API-012가 내부 공통 scheduler에 em_prepare를 접수하고 API-014/015/028로 취소/상태/event를 제공한다. instrument_acquisition은 R3의 검증된 장비 adapter와 장비 상태/교정/사용자 측정 명령이 필요하며 EM plan을 요구하지 않는다.

em_analysis의 `execution_mode=solve_and_postprocess/postprocess_only`를 구분한다. postprocess_only는 동일 PreparedPlan, 완결된 raw manifest와 변환 profile/version을 참조하고 새 solver 실행을 생략한다. 필요한 raw 채널이 없으면 E_MISSING_ARTIFACT를 반환하며 자동으로 해석을 시작하지 않는다. mode를 명시하지 않은 제출은 solve_and_postprocess다. postprocessing은 명시적 작업이고 result.open의 숨은 부작용이 아니다. 실제 수행 단계, parent raw ID, 생략한 단계와 이유를 새 artifact에 남긴다.

StudyPlan은 study_type=grid_sweep/adaptive_frequency/shape_opt/matching_synthesis/tolerance/model_calibration/inverse_design과 각 입력을 가진다. API-020/021이 해당 type별 실행 coordinator로 전달하며 actual EM solve 횟수와 DFT/보간 횟수를 구별한다.

JobState의 단일 정의와 전이는 [시스템 명세 6절](04_RFAD_시스템_명세.md)에 있다. transport_state=connected/disconnected/reconnecting는 JobState와 독립이다. 연결 끊김만으로 native job가 실패, 완료됐다고 판단하지 않고 상태를 재조회한다. stale은 snapshot과 현재 revision의 관계이며 JobState가 아니다.

em_prepare는 queued -> preparing -> completed, em_analysis는 queued -> running -> postprocessing -> completed의 종류별 전이를 사용한다. postprocess_only는 running을 생략하고 postprocessing으로 간다. 공통 시작/실패/취소 전이는 04를 따른다. interrupted도 terminal이며 재개 여부는 `resume_eligibility=unsupported/eligible/ineligible`로 저장한다. job.resume은 eligible인 checkpoint만 받아 새 run을 생성한다. cancel/완료 경합에서는 먼저 영속 확정한 terminal 상태가 우선이다. worker.events는 job/run ID와 영속 seq를 포함하고 중복/늦은 event를 무해하게 처리한다. 연결 재수립 시 cursor와 authoritative 상태를 대조하며 로그 유실을 완료 event로 대체하지 않는다.

WSL profile은 guest supervisor가 run UUID, nonce, lease와 실제 guest process group을 소유한다. host의 wsl.exe 종료만으로 cancelled를 확정하지 않는다. 취소는 해당 guest group의 종료를 확인한 뒤 terminal 상태를 commit하며, 확인할 수 없으면 transport 단절과 종료 확인 대기 상태를 유지한다. 연결이 끊긴 job의 memory/worker 예약은 실제 guest 종료와 lease 해제를 확인할 때까지 유지한다. 이 확인 전에는 중복 제출, checkpoint 재개, run directory 정리를 허용하지 않는다. fencing은 stale 결과 게시를 차단하지만 publish nonce 변경만으로 기존 process의 RAM이나 쓰기 권한이 회수되지 않는다. lease 만료만으로 프로세스가 사라졌다고 추정하지 않는다. interrupted 상태와 resume_eligibility도 이 실행 소유권 검사를 대체하지 않는다.

data_processing은 queued -> running -> postprocessing -> completed를 사용하며 결과 검사가 running에 포함되는 operation은 postprocessing을 생략할 수 있다. job.status/worker.events의 event retention 범위를 벗어난 cursor는 E_CURSOR_EXPIRED와 현재 전체 상태 및 새 cursor를 반환한다. client는 이를 기준으로 다시 동기화하고 누락 event가 없었다고 표시하지 않는다. notification 자체에는 RPC 응답이 없으므로 복구 요청은 API-015 job.status로 수행한다.

## 4. capability descriptor

필드: `adapter_id/version`, `protocol_versions`, `native_engine/version/build_hash`, `runtime_profile`, `features`, `tested_envelopes`, `license_refs`, `fixture_evidence`, `limitations`.

feature별로 name, supported representations, input domain, native mapping, status, validation test IDs를 가진다. 예: isotropic epsilon_r, sigma, tensor material, dispersion pole, conducting sheet, finite volume metal, roughness, lumped port, transmission-line port, modal port, complex reference processing, NF2FF, checkpoint. 형상 종류가 아니라 실제 native 연산과 결과 채널 단위로 분해한다.

status는 declared/implemented/verified/unsupported/unknown. 첫 openEMS profile의 기본 범위는 Cartesian planar PCB, 검증된 isotropic 물성과 도체 모델, single-port 기본 경로다. 다중 포트, CPW/stripline, ferrite, 회전 anisotropy, roughness 등은 엔진에 관련 기능이 존재하더라도 adapter 계약시험 전 verified로 노출하지 않는다. 원격 실행이나 GPU도 runtime capability로 별도다.

## 5. AnalysisPlan

AnalysisPlan은 의도한 snapshot, geometry/material mapping, unit/frame transform, port basis, frequency/excitation, observables, mesh/boundary/termination 정책, 허용 근사, budget/runtime/validation policy를 가진 불변 계획이다. 아직 생성되지 않은 native 파일 hash와 실제 mesh 값은 이 객체에 나중에 덧쓰지 않는다.

solver.prepare는 별도 PreparationArtifact를 만든다. 여기에는 analysis_plan_id/hash, 실제 native input hashes, 실제 mesh/statistics, 실제 전달 물성/근사, native units, normalization contract, consumption report가 들어간다. PreparedPlan은 AnalysisPlan+PreparationArtifact의 불변 참조와 검증 상태를 연결하며 독립 ID/hash를 가진다. API-013 em_analysis는 이 PreparedPlan을 요구한다. 준비 결과가 허용한 근사를 벗어나면 재계획 진단을 내고 새 AnalysisPlan을 생성해야 한다. 원래 plan hash를 유지한 채 내용을 바꾸지 않는다.

preflight 순서:

1. schema, unit, references, parameter DAG.
2. geometry closedness/overlap/contact/width/gap, layer topology.
3. material validity, loss partition, unknown state.
4. port positive/reference conductor, orientation, termination, frequency support.
5. boundary/NF2FF/air region과 사용 구조의 교차 검사.
6. 준비 전 mesh 정책과 예상 memory/disk 검사. 실제 mesh 생성 후 critical feature 보존과 실측 통계 재검사.
7. capability와 필수 observables 매칭.
8. immutable plan 생성, 선택 근사와 unresolved non-blocking 조건 기록.

mandatory 오류는 실행 차단한다. 단순 missing source provenance는 물리값이 사용자 지정으로 명시된 exploratory run에서 warning일 수 있지만, 검증된 material 상태로 승격하지 않는다.

## 6. mesh와 수치 계획

R1 초기 mesh는 재료 내 wavelength와 최소 gap/선폭/곡률/port/비아를 함께 사용한다. low-loss scalar 매질에서 wavelength 식을 사용하는 경우만 EQ-003의 가정을 적용한다. 복소/이방성/강분산에서는 검증된 k/모드 추정 또는 명시적인 해석기 설정이 필요하다.

초기 mesh profile에 wavelength 당 cell 수, gap당 cell 수, local refinement, growth ratio, conductor-edge alignment를 저장한다. 예시 N=20 또는 gap 3cells 같은 값은 시작값 정책이며 정확도 보증식이 아니다. CAD의 실제 copper thickness가 작을 때 geometry를 두껍게 만들어 계산을 편하게 하지 않는다. 검증된 sheet representation을 선택하거나 volume mesh 비용을 감수하도록 명시한다.

mesh 생성 뒤 port gap, 단락부, slot, via connectivity를 다시 검사한다. optical preview에 선이 보이는 것만으로 discretized mesh의 연결성을 확인하지 않는다. 자동 timestep은 solver의 실제 알고리즘과 출력값을 기록하고 일반 CFL 예제를 native timestep 대신 강제하지 않는다. 최대 시간/step 도달과 에너지 decay 조건 종료를 구별한다. 수렴 검증은 EQ-037/038 및 VT 기준을 따른다.

`simulation_time_limit_s`는 물리 시간, `wall_time_limit_s`는 scheduler의 경과 시간 예산이다. openEMS의 MaxTime은 공개 구현에서 timestep으로 나누어 최대 step 수로 바뀌므로 wall-clock timeout으로 사용하지 않는다. NrTS, MaxTime, EndCriteria의 요청값/실제 적용값과 `termination_reason`을 기록한다. 준비 또는 후처리도 전체 worker 자원 예산에 포함한다. [openEMS MaxTime 처리 소스](https://github.com/thliebig/openEMS/blob/master/openems.cpp).

## 7. openEMS adapter 구현 지점

공식 Python 문서에서 `openEMS`, `SetCSX`, boundary/excitation 설정, port 추가, `Run`, `CalcPort`, NF2FF 경로를 문서 대조했다. 이는 현재 설치본/프로젝트 adapter의 실행 증거가 아니다. 개발 승인 후 버전과 source commit을 고정하고 아래 순서를 검증한다. [engine API](https://docs.openems.de/en/latest/python/openEMS/openEMS.html), [ports](https://docs.openems.de/en/latest/python/openEMS/ports.html), [NF2FF](https://docs.openems.de/en/latest/concepts/nf2ff.html).

adapter는 다음 순서로 구현한다.

1. semantic projection을 CSXCAD material/primitive로 변환하고 priority/overlap rule을 명시한다.
2. drawing unit을 선언하고 SI<->native 변환을 한 곳에서 수행한다.
3. native grid와 포트 probe 위치를 만든 뒤 물리 도체와 실제 격자 대응을 검사한다.
4. 지원되는 여기와 종료 조건, 모든 경계 및 최종 grid를 고정한 뒤 field probe/NF2FF를 구성한다. CreateNF2FFBox가 현재 grid와 경계에 의존하므로 순서를 바꾸지 않는다.
5. 실행 입력과 환경 manifest를 저장하고 worker에서 native engine을 실행한다.
6. native port/field 데이터를 읽어 native convention metadata와 raw 파일을 보존한다.
7. 계약시험으로 확인한 채널만 도메인 RMS/phasor convention으로 변환한다.
8. S, power, field, convergence evidence를 개별 artifact로 생성한다.

NF2FF box는 방사체를 포함하고 사용 구현이 요구하는 매질, 표면, PML 조건을 만족해야 한다. 주파수 domain dump에서 기록하지 않은 주파수를 나중에 임의 생성하지 않는다. time-domain 기록도 source spectrum/SNR/시간 길이의 유효 범위 내에서 후처리한다.

### 7.1 손실 모델의 최소 계약

R1 scalar dielectric은 epsilon_r와 finite conductivity의 의미를 명시한다. PCB tan_delta를 기준 주파수에서 conductivity로 매핑하는 경우 `fit_kind=narrowband_equivalent_conductivity` 및 f_ref, 입력값, 유효 대역, 사용 근사를 기록한다. 이를 일정 tan_delta의 광대역 모델로 표시하지 않는다. wideband dispersion은 검증한 native pole fit 경로로 분리한다. 도체 conducting sheet의 thickness=0은 physical copper가 없다는 뜻으로 사용하지 않으며 실제 behavior와 PEC 전환은 해당 API/profile 시험으로 확인한다.

도메인의 electric sigma[S/m]는 native Kappa와 대응한다. native Sigma[ohm/m]는 자기 손실 항이므로 이름만 보고 연결하지 않는다. CSXCAD의 2D conducting sheet와 실제 CAD 동박 두께를 별개로 보존하며 명시적인 PEC 선택 외에 누락 두께를 0으로 전송하지 않는다. [CSXCAD 물성/시트 정의](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/materials.html). Debye/Lorentz의 문서상 존재와 Python fit helper 존재도 구별한다. [openEMS 분산 문서](https://docs.openems.de/en/latest/concepts/dispersive.html)의 native 모델 파라미터/부호로 원 곡선을 재구성해 확인하기 전에는 fit을 verified로 표시하지 않는다.

## 8. normalization contract

채널마다 native unit, native amplitude/phasor/Fourier convention, domain conversion, normalization reference, evidence ID를 저장한다. `solver_native`가 해결되지 않은 채널은 절대 power/gain metric에 사용하지 않는다. peak_phasor임이 확인된 V/I/E/H만 RMS로 1/sqrt(2) 변환한다. raw S ratio나 time instantaneous 값에는 이 처리를 적용하지 않는다.

port reference impedance가 서로 다르면 전압비를 그대로 일반 power-normalized Sij로 취급하지 않는다. incident/reflected data와 기준 Z0/wave definition에서 정의에 맞는 matrix를 만든다. raw real-Z reference를 complex-Z power-wave로 변환하는 후처리와 native physical source/load를 바꾸는 것을 구별한다. `ref_plane_shift`의 native unit/방향/port 적용범위를 확인해 domain의 signed distance와 매핑한다.

문서 검토 시 공개된 [Port.CalcPort 소스](https://github.com/thliebig/openEMS/blob/master/python/openEMS/ports.py)는 U/I에서 voltage-wave를 분리하고 기준면 이동에 beta의 실수부를 사용하는 경로를 포함한다. 따라서 native complex-Z의 P_inc-P_ref를 무조건 P_acc와 동일시하거나 해당 이동을 손실 fixture de-embedding으로 표시하지 않는다. lumped port에는 transmission-line 기준면 이동을 적용하지 않는다. 원 native V/I와 channel 규약을 보존하고 EQ-011/012의 명시 변환을 거친다. 이 해석은 공개 소스에 대한 것이며 pinned 설치본은 별도 검증 대상이다.

multiport run은 독립 excitation basis를 한 열씩 만들고 포트별 termination을 고정한다. a-vector basis가 충분한 rank인지, frequency별 source amplitude가 유효한지 검사한다. coherent field synthesis에는 각 basis의 위상 중심, DFT/time origin, amplitude 기준이 같아야 한다. magnitude-only field로 phase를 추정하지 않는다.

power ledger의 DUT 경계와 native source/port termination 위치를 명시한다. 수치 여기용 저항, 실제 안테나 도체/유전체 손실, 외부 정합망 손실을 다른 role로 매핑하고 이미 P_acc에서 제외된 전력을 다시 손실로 차감하지 않는다. native probe가 측정하는 전류 경로와 resistor/termination 손실의 포함 범위는 matched load 및 손실 없는 기준 network로 개발 후 검증한다. 이 경계가 확인되지 않았으면 efficiency를 미평가로 남긴다.

## 9. adapter 계약시험과 지원 승격

doctor->analytic port/network fixture->geometry/unit fixture->lossy material fixture->radiating canonical fixture->mesh/boundary convergence->external CAD/measurement 비교 순으로 증거를 쌓는다. 각 시험은 snapshot/native input/hash/toolchain을 남긴다. 특정 port/material 조합이 실패해도 다른 검증 조합을 삭제할 필요는 없지만 전체 backend를 '모든 기능 지원'으로 표시해서는 안 된다.

최초 구현에서 반환 값은 실제 계산 결과 또는 명확한 unsupported/failure다. 유사한 예제 파일의 결과를 복사해 실제 현재 모델의 결과처럼 제공하는 fallback은 허용하지 않는다.

### Pulse spectrum과 정규화 설계 (PHYS-001)

공개 [DFT_time2freq 소스](https://github.com/thliebig/openEMS/blob/master/python/openEMS/utilities.py)의 pulse와 periodic scaling을 문서 수준에서 대조했다. pulse raw U [V*s], I [A*s], 같은 Fourier scale의 E [V*s/m], H [A*s/m]에 대해 `0.5*Re(U*conj(I))`는 W*s^2이다. 이 값을 단순히 sqrt(2)로 나누어 V RMS/W로 기록하면 안 된다. 아래는 차원 분석으로 유도한 제한된 변환 계약이며 현재 설치본 시험 결과가 아니다.

단일 실수 양수 R0, 동일 DFT/위상 원점 및 유효 입사 spectrum q=Uinc에서 prescribed incident power Pset과 위상 0의 phasor는 다음과 같다.

```text
V_rms = (Utot / q) * sqrt(R0 * Pset)
I_rms = (Itot / q) * sqrt(R0 * Pset)
E_rms = (Eraw / q) * sqrt(R0 * Pset)  # 같은 native field scale 검증 후에만
P_W = P_native * 2 * R0 * Pset / abs(q)^2
S11 = Uref / Uinc  # RMS 변환을 적용하지 않음
```

q의 phase를 제거한 incident 기준이라는 사실, Pset, spectrum mask와 변환 근거를 저장한다. P_native는 같은 quadratic Fourier scaling의 채널에만 해당한다. 이미 정규화된 solver power에 계수를 중복 적용하지 않는다. 작은 q 또는 미검증 채널은 absolute metric을 차단한다. 개발 승인 후 실제 source amplitude 1x/2x의 raw 선형/전력 제곱 scaling, 정규화 불변성, known port 방향/전력 및 field 적분을 따로 검증한다. 산술 helper 시험이나 TE10 fixture 하나로 모든 lumped/NF2FF 조합을 승인하지 않는다. 세부 정의는 [RFAD 09의 PHYS-001](09_RFAD_수식과_물리_모델.md)을 기준으로 하고 미확보 실행 증거는 [문서 검토와 승인](25_RFAD_문서_검토와_승인.md)에 남긴다.
