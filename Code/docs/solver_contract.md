# WSL2 openEMS worker 계약

갱신일: 2026-11-11 KST. 승인 기준선 RFAD-D0-3.4의 API-011/012/013/014/015/016을 도파관 참조 `rfad.openems.rect-waveguide/0.1`과 사용자 PCB `rfad.openems.pcb-single-port/0.1` profile로 연결한다. `01_Docs`의 승인 기록은 변경하지 않는다. 사용자 PCB의 상세 입력/근사/제한은 [PCB 해석 계약](pcb_solver_contract.md)을 따른다.

## 현재 지원 범위

별도의 빈 참조 프로젝트를 스냅샷으로 봉인하고, 명시적 진공/PEC 직사각 도파관을 계산한다. 크기는 20 x 10 x 80 mm, TE10 입력과 반대 방향 수동 포트, 측정면 z=15/65 mm, Gaussian 중심 10 GHz, 평가 대역 9.5~10.5 GHz의 31점이다. 격자는 최대 1.0 또는 0.75 mm, 양 끝 PML 8 cells, 최대 20000 steps, 종료 에너지 1e-7, CPU thread 2개로 고정한다.

도파관 profile은 설계 형상/매개변수/재료/포트가 있는 프로젝트를 이 참조 형상으로 조용히 대체하지 않고 접수를 거절한다. 별도의 PCB profile은 사각/원형 기판, 선/원호, 구멍을 가진 접지 polygon, 원형/회전 사각 pad, 중공 도금 관통 PTH via와 명시적 물성을 소비한다. 단일 lumped 포트는 동일 sheet 면의 x/y gap 또는 서로 다른 sheet 사이 z gap을 사용하며 S11/VSWR/입력 임피던스를 계산한다. IFA의 접지/단락부/방사체가 같은 net인 경우도 실제 형상과 열린 gap을 검사한다. 도체/급전의 상세 의미는 [도체와 IFA 확장](copper_features.md)을 따른다.

실행 가능한 IFA 도체 모델과 실물 검증은 구분한다. 실제 SMA launch, 정합 부품/마스크/케이블과 측정 기준면은 아직 완성하지 않았으며 정식 IFA 격자/경계/시간 수렴과 실측 대조도 후속이다. NF2FF, 이득/효율/절대 전력은 현재 결과에 포함하지 않는다. 진공과 PEC는 도파관 사례에서 명시한 조건이며 미정 사용자 물성의 기본값이 아니다.

## 서비스 흐름

모든 요청은 `contract_version=rfad.api/2.0`, `context`, `input`을 사용한다. 변경 요청에는 기존 `request_key`와 `request_key_epoch`가 필요하다. 같은 키는 기존 접수 결과를 반환하고 다른 payload로 재사용하면 거절한다.

| 메서드 | input | 결과 |
| --- | --- | --- |
| solver.plan | snapshot: {snapshot_id, content_hash}, analysis_profile, runtime_profile, 도파관 grid_mm 또는 PCB settings | queued TaskRef. 완료 시 analysis_plan: {plan_id, content_hash, artifact}, model_report, resource_estimate |
| solver.prepare | analysis_plan: {plan_id, content_hash}, budget: {timeout_seconds} | queued TaskRef. 완료 시 prepared_plan: {prepared_plan_id, content_hash, artifact}, preparation_artifact, 실제 mesh_statistics |
| job.submit | task_plan: {kind: em_analysis, prepared_plan: {prepared_plan_id, content_hash}, execution_mode}, budget | queued TaskRef. 완료 시 artifact_id, normalized_result 파일 참조, assessment |
| job.cancel | job_id, 선택적 reason. context는 빈 object | 취소 의도와 현재 상태. 실제 guest 종료 확인 후 cancelled |
| job.status | job_id, 선택적 cursor. context는 빈 object | 영속 state/events 및 게시 완료 artifact 참조 |
| result.open | artifact_id, 선택적 selection: all/normalized/raw | 작은 metadata와 파일 참조. 계산을 시작하지 않음 |
| solver.latest | 빈 input | 최근 완료 해석 참조. 실패/취소 결과로 대체하지 않음 |
| solver.samples | artifact_id | 최대 201점의 주파수/S11 dB/VSWR/복소 임피던스 표시 DTO와 원본 SnapshotRef |

plan/prepare/submit/result.open/solver.latest/solver.samples의 context에는 project_id를 지정한다. analysis_profile은 위 두 profile 중 하나이며 runtime_profile은 공통 `openems-wsl-reference/0.1`이다. timeout_seconds는 0 초 초과 300 초 이하이고 검증 CLI는 120 초를 사용한다. latest/samples는 `rfad.solver-view/0.1` 개발 확장이며 새 정식 API 번호를 만들지 않는다. 조회는 solver 환경 없이 가능하고 계산을 시작하지 않는다.

execution_mode는 `solve_and_postprocess` 또는 `postprocess_only`다. 후처리 전용에는 동일한 PreparedPlan으로 완료된 `raw_result_id`를 추가한다. 원시 파일/manifest가 없거나 봉인이 다르면 실패한다. solver를 자동으로 다시 실행하지 않는다. 변환 규약은 이 profile 버전에 고정하며 임의 conversion profile은 지원하지 않는다.

## 불변 입력과 단계 분리

AnalysisPlan은 원본 스냅샷, 참조 사례, 단위, 포트 방향/기준면, 정규화 규약과 실행 환경 식별을 담는다. runtime에는 Python 설치 명세, native 감사 파일의 hash, worker 진입점과 제품 Python 소스 파일별 hash, WSL supervisor protocol/hash를 포함한다. 접수 시 캡처한 소스만 staging에 복사하고 기존 pycache를 재사용하지 않는다.

prepare는 실제 CSXCAD 격자와 openEMS XML을 만들며 FDTD를 실행하지 않는다. XML, 실제 격자선/통계, 소비한 조건, 단위/정규화, 실제 runtime 관측을 PreparationArtifact에 기록한다. host는 파일 hash와 보고의 일치, 포트 측정면/격자/단위/소스 조건을 검증한 후 별도 UUID/hash의 PreparedPlan을 게시한다. 원래 AnalysisPlan을 수정하지 않는다.

PCB의 polygon은 구멍을 유지하는 면 분할로 전달한다. 동박은 유한 전도도/실제 두께의 conducting sheet이고 via는 유한 전도도와 상대 유전율을 입력받는 중공 체적 도체다. finished bore와 도금 두께를 사용하며 미정 tool bore를 제조 확정값으로 채우지 않는다. CAD의 실제 동박 외면 span과 EM의 유전체 접면 sheet span 차이는 계획/소비 보고서에 남긴다.

native 준비에서는 실제 CSXCAD 재료 우선순위를 Yee 전기 edge 중심에서 평가해 도체/패드/비아의 소실 또는 접속 변화와 급전 gap 침범을 검사한다. `yee_connectivity_checked=true`는 이 격자 표현 검사이고 `operator_coefficients_checked=false`를 유지한다. solver의 최종 계수, 전류 연속성 수렴이나 RF 정확도를 독립 검증했다는 뜻은 아니다.

analysis는 준비 단계의 동일 XML 바이트를 native openEMS CLI에 직접 전달한다. 모델을 다시 생성하지 않는다. 종료 후 도파관은 4개, PCB는 2개 시간 probe를 보존하고 공통으로 2개 native 통계, native.log, 입력 XML과 raw manifest를 보존한다. postprocess_only는 이 원시 파일을 검증하고 DFT만 다시 계산한다.

정규화는 `exp(-j*2*pi*f*t)`, `2*dt*sum(...)` pulse Fourier 규약을 사용하며 RMS 전력으로 변환하지 않는다. 도파관에서는 S11/S21과 U/I를 구하고 기준 임피던스로 주파수별 진공 TE10 모드 임피던스를 사용한다. 한 포트만 여기하므로 완전한 2-port S 행렬을 계산했다고 표시하지 않는다. 자세한 참조 해석식/판정 기준은 [참조 검사](openems_reference.md)를 따른다. PCB에서는 사용자가 명시한 실수 lumped 저항을 기준으로 S11/VSWR와 U/I를 계산한다. 물리 정확도 판정은 `computed_unvalidated`다.

준비 상태는 queued -> preparing -> completed, 해석은 queued -> running -> postprocessing -> completed다. 후처리 전용은 running을 생략한다. 실패/취소가 이전 완료 결과를 덮지 않으며 terminal 상태는 먼저 게시한 결과가 유지된다. NDJSON에는 큰 배열 대신 {uri, sha256, bytes} 파일 참조를 반환한다.

## WSL 소유권과 복구

Windows 서비스는 고정 `TraceWave-Dev`/`tracewave` 설정으로 셸 없는 argv와 제한된 제어 입력만 전달한다. Linux ext4의 `/home/tracewave/rfad-runtime/worker-runs`에 별도 run UUID를 만든다. guest가 입력별 hash를 확인하고 읽기 전용 사본을 만든 뒤 detached supervisor가 worker를 시작한다. stdin의 run UUID/nonce gate가 맞아야 native 모듈을 로딩한다.

guest supervisor가 process group, 로그/파일 제한, sticky cancel, heartbeat lease와 상태 cursor를 소유한다. watchdog는 supervisor가 비정상 종료되어도 nonce/세션/starttime/pidfd로 확인한 해당 실행의 후손만 회수한다. `wsl.exe`가 종료되거나 lease가 만료됐다는 사실만으로 guest 종료를 선언하지 않는다. 실제 그룹과 후손의 종료를 확인한 뒤에만 host로 결과를 회수하고 슬롯을 반환한다.

worker가 nonce 표식을 상속한 후손은 process group 또는 session이 달라져도 종료 확인에 포함한다. 소유권 검사가 실패하면 결과를 공개하지 않는다. 이 계층은 고정한 신뢰 worker의 수명 관리이며 session 변경과 표식 제거를 의도적으로 결합한 임의 적대 코드의 보안 격리를 제공하지 않는다.

서비스가 비정상 종료되면 이전 active 작업은 interrupted/outcome_unknown과 슬롯 예약을 유지한다. 재실행/solver resume/자동 정리를 하지 않는다. 기존 편집/저장/결과 조회는 계속 사용할 수 있다. 동일 supervisor runtime을 사용하는 유지보수 CLI로 재접속해 취소와 종료 확인만 수행할 수 있다. 원래 terminal은 interrupted로 남는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_openems_worker.py --workspace .local/openems-worker-workspace --report .local/unused.json --reconcile-job <job-uuid>
```

다른 소유권, runtime 변경 또는 연결 단절로 종료를 확인하지 못하면 예약을 유지한다. CLI가 termination_confirmed=false를 반환하면 종료 확인을 다시 수행해야 한다. 공개 RPC 수동 조정과 GUI 복구 화면은 후속이다.

workspace당 solver 슬롯 1개와 CAD 슬롯 1개가 별도로 존재한다. 긴 실행/결과 봉인은 journal transaction 밖에서 처리한다. 파일별 64 MiB, 전체 결과 128 MiB, native stdout/stderr 합계 4 MiB와 제한된 tail을 적용한다. supervisor 제어 출력은 stdout 256 KiB/stderr 64 KiB로 제한한다. 파일 감시는 주기적 검사이며 disk quota나 OS 메모리 hard limit이 아니다. plan의 메모리 추정은 초기 추정값이고 앱 성능 예산 검증을 대신하지 않는다. staging/guest run/log는 조사용으로 보존하며 자동 GC는 후속이다.

## 실행과 검증

기존 [Qt 없는 WSL 환경](linux_environment.md)과 `.local/wsl/native-audit.json`이 필요하다. native 감사가 현재 설치와 다르면 실패하며 프로젝트 API로 임의 실행 파일/셸/경로를 지정할 수 없다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m rfad serve --workspace .local/openems-worker-workspace --openems-wsl
.\.venv\Scripts\python.exe -X utf8 tools/verify_openems_worker.py --workspace .local/openems-worker-verification/manual-001 --report .local/openems-worker-verification/manual-001.json --exercise-cancel
```

검증 CLI는 실제 공개 JSON-RPC 경계를 통해 새 프로젝트/스냅샷, 두 격자의 plan/prepare/analysis, raw 후처리 재실행과 결과 조회를 수행한다. 후처리 표본과 raw manifest의 완전 일치, service 재시작 후 조회 일치, 실제 실행 중 취소와 guest 종료 확인도 검사한다. 독립 환경 검사 `check_openems_environment.py`와 구분한다.

`tests/test_solver_plan.py`와 `test_solver_jobs.py`는 계약/수명 검증이다. fake transport와 이상적 표본의 성공을 FDTD 증거로 사용하지 않는다. `test_openems_adapter.py`의 실제 native 시험은 Linux solver 환경에서 실행하고 공식 CalcPort와의 동등성도 확인한다. host 재검사에서 Windows/Linux 복소수 마지막 자릿수 차이만 rel_tol=1e-12/abs_tol=1e-14로 허용하며 물리 합격 상한은 변경하지 않는다.

`test_wsl_guest.py`는 실제 Linux 자식/손자 취소, timeout, 출력 제한, lease 만료, supervisor 사망/watchdog, wrong nonce/입력 변조를 검증한다. `RFAD_TEST_WSL=1`은 Windows transport 시험의 실제 WSL 실행/launcher 단절 및 재접속 시험을 활성화한다. Linux adapter의 실제 계산에는 `RFAD_OPENEMS_NATIVE=1`과 solver 가상환경을 사용한다. 실행 결과와 세부 로그는 [개발 상태](development_status.md)에 기록한다.

```powershell
$env:RFAD_TEST_WSL = '1'
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_wsl_process.py -v
wsl.exe -d TraceWave-Dev -u tracewave --cd '/mnt/c/Users/eidos/GitHub/TraceWave Studio/Code' --exec /usr/bin/env PYTHONPATH=src RFAD_OPENEMS_NATIVE=1 /home/tracewave/rfad-runtime/openems-venv/bin/python -B -m unittest discover -s tests -p test_openems_adapter.py -v
```

GUI의 `해석 입력 검사`는 draft 누락 검사로 유지한다. `-OpenEmsWsl`로 시작한 GUI는 별도의 해석 설정/실행/취소와 S11/VSWR/임피던스 그래프를 제공한다. polygon/pad/via의 생성/속성/표시와 명시적 급전 조건은 같은 원본 명령과 불변 스냅샷을 사용한다. [PCB 실행 검사](pcb_solver_contract.md#검증과-후속-범위)는 원형 선/원호 사례에 더해 별도의 IFA 급전 및 PTH fixture를 선택할 수 있다. fixture의 물성과 도금 치수는 명시적 실행 가정이며 승인된 초기 IFA의 미정 제작 조건을 덮어쓰지 않는다.

다음 단계는 단일 포트 IFA의 정식 수렴, 실제 물성/급전/측정 조건 대조다. 이어 원형 PCB/원호의 물리 검증과 NF2FF/방사 결과를 확장한다. 결과의 `computed_unvalidated` 상태를 유지하고 실행 완료나 시간 에너지 종료만으로 안테나 성능 합격을 주장하지 않는다.
