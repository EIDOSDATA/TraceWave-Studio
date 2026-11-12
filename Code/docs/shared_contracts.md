# R1 공통 구현 계약

확정일: 2026-11-12 KST. 설계 기준선 RFAD-D0-3.4. 적용 위치는 [개발 완료 계획](completion_plan.md)의 2번이며 아래 계약을 3번 이후 구현에 적용한다.

이 문서는 현재 동작과 후속 구현 결정을 구분한다. 승인 원문 04/06/08/11의 의미를 유지하며 미구현 기능을 capabilities에 등록한 것으로 간주하지 않는다. 공개 API 전체 구현과 R1 수용 완료를 선언하지 않는다.

## 1. 공통 결정과 소유자

| ID | 확정한 계약 | 현재 구현과 후속 적용 |
| --- | --- | --- |
| CC-001 | ProjectDocument의 원본/명령/단위/hash는 domain/application 서비스가 소유한다. GUI/CLI/MCP는 같은 명령을 호출한다. | project.py, projects.py, canonical.py와 기존 명령/이력 재사용. GUI에서 별도 물리값/hash를 생성하지 않음 |
| CC-002 | 입력의 missing, 명시한 가정, 출처 관측과 사용자 채택값을 보존한다. 필요한 연산만 부족 입력을 차단한다. | Quantity와 PCB 선택 계약 유지. 실제 납품 물성과 제작/측정 미정값 자동 보완 금지 |
| CC-003 | 새로운 core collection을 활성화할 때 schema/validator/명령/역명령/migration을 함께 제공한다. | targets는 프로젝트 0.3에서 명시적 대역/지표 한계 입력으로 활성화. 0.1/0.2 원본 보존/읽기와 새 개정 승격을 검사한다. networks/environment/connections 등은 아직 빈 배열만 허용하며 예약 필드가 실행 기능을 의미하지 않음 |
| CC-004 | entity UUID, revision, snapshot, artifact ID를 서로 대체하지 않는다. 표시 선택과 물리 관계는 stable ID로 연결한다. | editor/canvas DTO와 immutable snapshot 유지. 새 template/candidate 적용도 expected_revision을 검사하는 원자 명령 |
| CC-005 | 변경 요청에는 request_key/epoch, 편집에는 expected_revision/command_id를 사용한다. 영수증과 변경을 같은 transaction으로 게시한다. | RequestLedger/ProjectHistory 재사용. 일반 import/copy/archive는 별도 미구현 범위이며 프로젝트 열기 성공으로 대체하지 않음 |
| CC-006 | 준비, 실행, 후처리, 결과 판정은 별도 작업/산출물이다. | AnalysisPlan -> PreparedPlan -> em_analysis/postprocess_only 유지. 새 Study도 동일 작업 조정기에 연결 |
| CC-007 | JobState, 연결 상태, 현재 설계와의 관계, 수렴/물리/실측 검증은 독립 축이다. | 현재 normalized_result.assessment.converged는 시간영역 종료 의미. 공통 화면에서 격자/손실 수렴 통과로 번역하지 않음 |
| CC-008 | raw/파생 network/metric/assessment/export의 입력 의존성과 출처를 각각 유지한다. | 현재 보수적 invalidation은 유지. 같은 값이라는 이유만으로 결과를 무검증 재사용하지 않음. 물리 key 기반 선택적 재사용은 후속 명시 구현 |
| CC-009 | 큰 배열과 B-rep는 worker/artifact 소유다. GUI는 필요한 페이지/ROI/표시 mesh만 받는다. | 기존 제한 DTO 재사용. HDF5 공통 dataset/ROI 계약을 추가할 때 현재 최대 201점 solver.samples와 구분 |
| CC-010 | profile 지원과 runtime 설치, 실제 검증 수준을 각각 표시한다. | capabilities의 implemented/tested_envelopes/runtime_configured는 다른 의미. 공개 검증 근거 연결은 추가 구현 필요 |
| CC-011 | 도면/제조/CAD 출력은 같은 snapshot에서 생성하고 별도 reader 검수 뒤 해당 profile만 승격한다. | 현재 STEP generated_unverified 유지. export.verify와 CAM/도면은 후속 |
| CC-012 | GUI의 화면 상태와 사용자 작업은 작은 모델/Presenter에서, 물리 판단은 서비스에서 처리한다. | 기존 RequestDispatcher/JobTracker/순수 화면 모델을 재사용. 상세 디자인은 studio_gui_design.md |

현재 코드 근거: [프로젝트 validator](../src/rfad/domain/project.py), [요청 계약](../src/rfad/application/project_contract.py), [서비스](../src/rfad/application/projects.py), [capabilities](../src/rfad/application/rpc.py), [작업 상태](../src/rfad/application/job_state.py), [연구 계약](../src/rfad/application/project_study_contract.py), [결과 조회](../src/rfad/application/solver_queries.py).

## 2. 후속 공통 DTO의 필수 의미

아래는 구현할 DTO의 필수 내용과 소유권이다. 현재 wire에 임의 필드를 추가해 사용할 수 있다는 뜻이 아니다. 새 profile/version의 validator와 capability, 기존 fixture의 호환 검사를 함께 제공한다. 현행 rfad.api/2.0과 승인 API ID는 유지하며 새로운 전송 버전이 필요할 때 명시적으로 협상한다.

| DTO | 필수 내용 | 소유자/적용 단계 |
| --- | --- | --- |
| TargetDefinition | ID/version, 주파수 대역/양끝, 선택 metric/단위/비교 규칙, port/Z0/기준면/좌표/편파/환경 조건, 출처와 미정값 | domain, 3/5. target 변경은 기존 raw를 덮어쓰지 않고 새 Assessment를 만듦 |
| TemplateCard/Candidate | ID/version/family, parameters/차원/정의역, topology/기대 short/open, 원문/수식/가정, patch/base_snapshot, 적용 가능 범위 | domain/application, 3. 수치 seed와 검증 설계는 독립 상태 |
| ValidationReport | purpose/profile, 입력 revision/snapshot, 오류 코드/심각도/entity/field 위치/수정 방법, blockers와 미평가 범위 | domain/application, 3/6. geometry/제작/EM 준비를 별도 판정 |
| DatasetDescriptor | artifact/hash, origin, shape/dtype/단위, 주파수/포트 순서/Z0/wave/phasor/기준면, frame/위상중심, 정규화, 유효 mask와 원본/보간 구분 | result service, 5/7. UI는 요청 범위만 조회 |
| MetricRecord | definition/version/EQ, input hashes, axes/units/normalization, valid masks, 불확도/수치 상태 | application, 5. 미계산 값을 0으로 만들지 않음 |
| Assessment | target/profile/version, metric refs, evaluated domain, pass/fail/not_evaluated/conditional, 누락 표본과 제약 위반, evidence | application, 5/7. 기존 수렴 도구의 passed/not_established 상태는 원문과 함께 표시 |
| StudyDefinition | type, base_snapshot, 변수/단위/경계/명시 후보, 고정 조건, 예산/실패 정책, 평가 profile | study coordinator, 6. 수치조건 연구와 설계변수 스윕을 다른 type으로 보존 |
| CandidateRun | candidate ID/patch/snapshot, plan/prepared/run refs, 실제 mesh/비용, 오류/취소/미수렴, metric/assessment refs | study coordinator, 6. 완료 순서로 후보 식별자를 바꾸지 않음 |
| MeasurementContext | raw hash, 시료/설계 개정, Z0/포트/기준면/교정, 케이블/fixture/환경, 단위/불확도 근거, 변환 chain | data service, 5/11. 실측 미확보를 예시 파일로 완료 처리하지 않음 |
| ExportManifest | export/profile/version, snapshot/results, files/hash/bytes, units/frame, object/net/layer mapping, 누락/근사, reader/검수 결과 | export coordinator, 10/12. 실패 파일은 완성 제조 패키지로 게시하지 않음 |

복소수는 명시적 real/imag, 단위와 시간 규약을 갖는다. 화면용 dB/VSWR에서 원래 복소 network를 역으로 추정하지 않는다. 승인된 normalized HDF5의 축/real-imag 규칙은 08번을 따른다. 현재 pulse Fourier 전력 W*s^2를 절대 W나 1 W 여기로 바꾸지 않으며 absolute_power_w=null 상태를 존중한다.

위 TargetDefinition의 첫 입력 부분은 [rfad.target/0.1](target_contract.md)로 구현했다. 대역/주파수 표본/port/Z0와 4개 지표 한계를 저장하고 [목표 편집 GUI](target_template_gui.md)에 연결했다. 기준면/관측/편파/프리셋/평가는 후속이다. 현재 목표 변경은 metric/assessment/export 무효화만 알리고 원시 파일을 보존한다. 새 Assessment 생성이나 개정 간 자동 raw 재사용을 구현 완료로 해석하지 않는다.

명시 치수 [템플릿](template_contract.md)은 core 객체를 생성하고 `rfad.template-origin/0.1` 확장에 카드/최초 입력/선택 목표/생성 사본을 보존한다. source_document는 중첩 확장을 제외한 core 사본이며 원래 전체 base_content_hash와 별도 해시를 가진다. 현재 편집 원본과 과거 출처 사본을 분리하고, 출처가 남아 있다는 이유로 과거 형상을 현재 형상으로 취급하지 않는다. 검토한 후보의 원자 적용/undo는 기존 명령/영수증을 사용한다.

## 3. 상태/작업 계약

문헌 카드의 첫 범위는 [G031 부분 기하](literature_templates.md)다. 원문 bytes/hash/locator와 문헌 치수, 사용자 수정/배치, 생략/미정 항목을 카드 0.2에 보존한다. 후보와 과거 생성 입력의 geometry/initial_estimate/analysis/convergence/measurement/manufacturing 축을 나눠 표시하며 전체 보드 재현 또는 물리 검증 상태를 만들지 않는다. 기존 0.1 내장 카드와 프로젝트/origin의 읽기 의미를 유지한다.

- 현재 접수된 job은 queued부터 시작한다. draft/validating/planned는 계획 준비 단계이며 임의로 현재 journal JobState에 추가하지 않는다.
- preparing/running/postprocessing/cancel_requested와 completed/failed/cancelled/interrupted 전이는 job_state.py를 단일 기준으로 사용한다. terminal job은 다시 실행 중으로 되돌리지 않는다.
- outcome_unknown=true인 interrupted 작업의 resource_reserved는 실제 worker 종료 확인까지 유지한다. 종료 확인을 마친 interrupted와 구분하며 PID만 보고 새 작업을 대신 제출하지 않는다.
- study.resume은 완료 준비/후보를 검증해 다음 시도를 만드는 연구 재개다. solver checkpoint를 이어 계산하는 API-029 job.resume은 현재 미지원이다.
- worker.events push가 없을 때는 현재 job.status cursor 조회를 사용한다. 중복/오래된 응답은 식별자와 seq로 처리하며 사용자에게 확인되지 않은 진척률을 만들지 않는다.
- 새 연구와 GUI는 기본/명시 profile의 예산을 그대로 사용한다. 고급 손실 profile을 선택하면 격자점/필드량/시간/스레드와 예상 비용을 실행 전에 표시한다. 현재 일반 연구 GUI의 300초와 고급 CLI 예산의 차이는 6번에서 연결한다.

## 4. 비교, 재사용과 무효화

| 변경 | 반드시 갱신할 대상 | 보존할 대상 |
| --- | --- | --- |
| 형상/물성/급전/환경/solver 소비값 | 관련 CAD/solver 계획과 raw의 현재 설계 연결 | 과거 snapshot/raw와 원래 판정 |
| mesh/PML/종료/기록 주파수 | 새로운 수치 계획/run | 설계 원본과 이전 비교 결과 |
| EM 밖의 검증된 외부 RLC | derived network와 해당 전력/지표/판정 | 완전한 원시 데이터가 있는 raw. 패드/배선/EM 내부 lumped 변경은 새 EM |
| 목표/대역 mask | 새 Assessment | 계산 입력이 같으면 raw/metric. 미기록 표본을 계산한 것으로 만들지 않음 |
| 색/테마/패널 배치/LOD | 개인 표시 설정/표시 캐시 | 물리 원본/hash/제조 및 solver 입력 |
| 출처 설명 보강 | 새 provenance 연결과 검토 기록 | 소비값/모델이 같은지 검증한 원래 raw; 과거 검증 등급을 소급 승격하지 않음 |

현재 기능의 conservative invalidation과 후속 선택적 cache 정책을 혼동하지 않는다. RO4350B N6 raw의 특별 연구 재사용은 XML/입력/설치/정규화/source 검사를 가진 별도 도구이며 일반 제품 cache 구현 완료가 아니다.

## 5. 구현 순서와 호환성 수용

3번에서는 targets/템플릿/연결/환경의 활성화 범위를 각각 validator/명령/undo와 같이 추가한다. 최소 한 종류를 저장/재열기까지 연결한 후 다음 종류로 확장하며 거대한 단일 schema 변경에 모든 기능을 넣지 않는다. 0.1/0.2 읽기와 직접 입력/카탈로그 출처는 회귀 fixture로 유지한다. 새 core 의미를 기존 reader가 처리할 수 없으면 새 schema를 사용하고 원본 backup/변환 기록을 남긴다.

5/6번에서는 결과 descriptor와 연구 type을 먼저 고정해 GUI/CLI/MCP가 공유하도록 한다. 현재 study.* 확장을 API-020/021 일반 optimization 기능으로 조용히 이름만 바꾸지 않는다. 기존 연구를 같은 조건으로 재열 수 있게 versioned reader를 유지한다.

10/12번에서는 copy/archive/import/export.verify와 검증된 공개 evidence 조회를 추가한다. 배포 도구가 개발 소스를 묶는 것과 사용자의 완전한 프로젝트 archive를 구분한다.

각 추가 기능은 정상 경로 외에 stale revision, 미정 입력, 미지원 profile, 잘못된 단위, 중복 요청, 부분 산출물/취소와 재열기를 해당 경계에서 검사한다. 수용 기준을 충족하지 않은 기능은 부분 구현으로 남긴다. 코드/시험 연결과 미해결 항목은 [구현 대조표](implementation_audit.md)를 따른다.
