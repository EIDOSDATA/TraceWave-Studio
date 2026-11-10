# CAD worker 구현과 해석 worker 연결 경계

검토일: 2026-11-11 KST

별도 호스트 CAD worker와 제품 서비스의 접수/실행/게시를 연결했다. WSL의 고정 openEMS 환경에는 guest supervisor와 제한된 도파관 adapter를 연결했으며 [해석 worker 계약](solver_contract.md)에서 범위를 구분한다. 승인 기준선 RFAD-D0-3.4의 04, 07, 11, 12번을 유지하며 현재 CAD profile의 상세 범위는 [CAD/STEP 계약](cad_contract.md)에 있다.

## 현재 실행 구조

짧은 프로젝트 자료 처리는 `ProjectService`의 기존 worker가 담당한다. CAD는 `CadCoordinator`의 별도 조정 스레드와 `tools/cad_worker.py`의 native 프로세스를 사용한다. 긴 형상 생성이나 파일 해시를 journal transaction 안에서 실행하지 않으므로 작업 중 편집/저장/상태 조회/취소를 계속 처리할 수 있다. GUI와 서비스에는 CadQuery/OCP/NumPy를 import하지 않는다.

현재 Windows CAD는 `.venv-cad`의 고정 CadQuery 2.8.0/cadquery-ocp 7.9.3.1.1을 사용하며 WSL에서 실행하지 않는다. 실행 파일 경로는 호스트가 지정하고 프로젝트/API에서 사용자 Python이나 임의 명령을 선택하지 않는다. POSIX 프로세스 감독 경로도 시험하지만 Windows wheel profile로 Linux CAD 배포가 검증되었다고 간주하지 않는다.

`export.preview` (API-023), `geometry.build` (API-008), `export.build` (API-024)는 모두 request key/epoch를 가진 비동기 TaskRef를 반환한다. 미리보기는 native 실행 없이 고정 snapshot의 포함 수/생략/profile 범위를 반환한다. 실제 형상과 출력은 CAD 슬롯을 사용하며 결과는 `job.status`의 completed event에서 조회한다. `export.verify`와 공개 resume/reconcile API는 후속이다.

GUI의 STEP 출력/3D 갱신은 편집 입력 적용, 불변 snapshot 접수, CAD TaskRef를 연결한다. CAD는 편집/저장 작업과 별도로 추적하고 진행 상태/취소/완료 경로를 표시한다. `cad.latest`는 해당 프로젝트의 마지막 게시 완료 참조만 동기 조회하는 `rfad.cad-view/0.1` 확장이다. 재열기 시 이전 결과를 복원하며 현재 개정과 다른 결과를 새 형상으로 표시하지 않는다. 큰 mesh는 파일 참조로만 전달하고 GUI background loader가 실제 소비 byte의 SHA256을 확인한다.

## 접수, 실행과 게시

1. 접수 transaction에서 등록된 SnapshotRef와 원본 hash를 대조한다. 정규 기하 입력, runtime manifest, worker 진입점과 제품 Python 소스 묶음을 불변 artifact로 봉인하고 run UUID/nonce, CAD 슬롯 예약, queued event를 함께 확정한다.
2. journal 잠금 밖에서 실행 식별을 재검증하고 새 staging에 입력/runtime/소스를 복사한다. worker는 실제 소비한 staged 입력과 소스 hash, Python/운영체제/CPU와 설치 패키지 버전을 확인한다. 기존 `__pycache__`와 출력 cache를 재사용하지 않는다.
3. native 감독기가 자신이 시작한 프로세스와 출력 stream을 소유한다. Windows에서는 KILL_ON_JOB_CLOSE Job Object를 연결한 후 stdin 시작 메시지를 전달한다. POSIX에서는 소유 process group을 회수한다. 입력은 봉인된 정규 JSON이며 원본 프로젝트 파일을 native worker가 직접 열지 않는다.
4. native 작업은 명시적 mm/deg 변환으로 유전체와 선/원호 도체를 생성한다. 실제 AP242 schema/단위, stable body 이름과 원본 UUID 대응, validity/체적/외곽/중심/두께/단면을 별도 OCCT reader로 확인한다. substrate와 copper는 서로 병합하지 않는다. STEP/B-rep 저장 뒤 동일 body에서 별도 표시 mesh를 만든다.
5. 프로세스 종료와 출력 닫힘을 확인한 뒤 host가 wrapper schema/run/nonce/input hash, 필수 파일, 실제 STEP header와 sidecar의 snapshot/원본 의미/hash를 다시 검증한다. mesh의 입력/원본 UUID 대응, 유한 좌표와 색인/상한도 확인한다. 닫힌 파일을 streaming hash/복사/fsync/재읽기로 봉인하고 작은 manifest를 마지막에 생성한다.
6. 짧은 게시 transaction에서 실행 nonce와 현재 상태를 다시 확인한다. artifact 참조와 completed event를 함께 확정하며 원본 프로젝트를 변경하지 않는다. 완료 전 staging/미게시 파일을 정상 결과로 노출하지 않는다.

결과는 `projects/<이름>/artifacts/<run_id>/`의 model.step, model.brep, mesh.json, sidecar.json, validation.json, manifest.json이다. NDJSON은 파일 바이트 대신 workspace 상대 artifact 참조를 전달한다. 새 request key로 접수하면 같은 입력이어도 새 실행을 만들며 결과 cache 적중으로 검증을 생략하지 않는다. 같은 request key의 재전송은 기존 receipt/작업을 반환한다. 소스나 runtime이 접수 후 변경되면 기존 작업을 새 구현으로 조용히 실행하지 않고 오류로 끝낸다.

## 취소, 재시작과 자원 경계

workspace당 CAD 실행은 하나다. queued 취소는 실행 전에 cancelled로 확정하며 running 취소는 먼저 cancel_requested를 기록한다. 자신이 소유한 실제 프로세스 트리와 pipe 회수를 확인한 뒤 cancelled와 자원 반환을 확정한다. 완료/취소 경합에서는 최초 terminal commit을 유지하고 다른 nonce나 취소된 실행의 늦은 성공을 게시하지 않는다.

정상 서비스 닫기는 소유 native 프로세스를 회수하고 작업을 interrupted로 기록한다. 비정상 종료 뒤 running/cancel_requested였던 CAD 작업은 interrupted/outcome_unknown과 슬롯 예약을 유지하며 자동 재실행하지 않는다. PID나 lease 만료만으로 다른 프로세스를 종료하거나 자원을 반환하지 않는다. 공개 수동 조정 API는 아직 없으므로 해당 workspace의 새 CAD 접수는 차단되지만 기존 편집/저장/조회는 가능하다.

기본 실행 시간은 120초, 출력은 파일별 64 MiB/전체 128 MiB/최대 16개, stdout+stderr는 합계 1 MiB와 각 마지막 16 KiB다. 출력 디렉터리를 주기적으로 검사하고 최종 봉인에서 크기/hash를 다시 검증한다. 검사 사이 일시적인 파일 상한 초과는 가능하며 OS 메모리 hard limit을 제공하는 것은 아니다. 소스 묶음/정규 입력/result에도 별도 크기 상한을 둔다. 취소 중 파일, disk-full, 손상 파일과 게시 실패는 성공으로 처리하지 않고 과거 정상 결과를 유지한다.

기존 `Journal.put_immutable`은 작은 입력/manifest용 단일 bytes 상한 8 MiB를 유지한다. CAD 파일은 별도 `Journal.seal_file`의 streaming 봉인을 사용하므로 큰 STEP/B-rep를 통째로 Python 메모리에 적재하지 않는다. staging과 제한된 로그는 실패 조사용으로 보존하며 자동 GC는 후속이다.

표시 mesh에는 별도로 16 MiB/100000 triangles/300000 vertices 상한을 둔다. host와 GUI는 이 제한 JSON을 읽어 검증하며 STEP/B-rep의 무제한 메모리 복사를 피하는 규칙과 구분한다. 현재 고정 표시 profile의 생성/검사 실패 시 전체 패키지를 게시하지 않는다. GUI의 GL 표시 실패는 이미 게시한 파일의 성공 상태를 바꾸지 않는다. 표시 LOD와 1000000 triangle profile, 프레임/전체 메모리 수용은 후속이다.

## 검증 상태와 한계

시험은 fake worker의 정상/실패/timeout/출력 폭주/취소/프로세스 회수, 장시간 실행 중 편집/저장 응답, nonce/취소 경합/재시작 예약, 봉인 오류와 미완성 산출물 비공개를 다룬다. 실제 서비스-CAD 프로세스 시험은 한글/공백 경로, snapshot 고정, 실제 AP242/B-rep 재열기와 원본 sidecar/hash를 확인한다. native 기하 시험은 signed sweep/완전 원환, 얇은 도체, 같은 net Boolean과 별도 body 중첩, 큰 좌표/작은 원호 및 거의 닫힌 cap의 지원 경계를 포함한다. 최신 실행 수치와 근거는 [개발 상태](development_status.md), 재현 명령은 [CAD/STEP 계약](cad_contract.md#검증-재현)에 기록한다.

같은 Open CASCADE kernel의 별도 reader이므로 `kernel_independent=false`이며 결과는 내부 기하 profile의 `generated_unverified`다. 미정 RF 물성과 원래 parameter binding은 sidecar에 보존한다. 미정 기하 치수/층 위치/두께는 출력 전에 차단하고 임의 FR4나 코어 두께를 채우지 않는다. 제조 전달, 독립 수신 CAD, 실제 급전/접속과 RF 정확도는 별도 검증이 필요하다.

## WSL solver 연결

WSL guest supervisor와 도파관 adapter는 별도 [해석 worker 계약](solver_contract.md)으로 구현했다. SnapshotRef, 불변 AnalysisPlan, 실제 준비 XML/격자/소비 보고와 독립 PreparedPlan을 연결한다. 준비는 FDTD를 실행하지 않고 analysis는 준비 XML을 그대로 사용한다. 완료한 raw만 사용하는 후처리 전용 모드도 있다.

Linux ext4 staging, run UUID/nonce/heartbeat, detached supervisor/watchdog와 실제 guest 종료 확인을 사용한다. wsl.exe launcher 종료를 guest 종료로 추정하지 않는다. 접속 단절/lease 만료/감독기 사망, 취소/timeout/출력 상한과 재접속을 실제 프로세스로 시험했다. 결과 파일 hash/종료 로그/통계/정규화/출처를 검증한 뒤 journal에 게시한다. 유지보수 CLI는 이전 interrupted 실행의 취소/종료만 확인하고 원시 해석을 재개하지 않는다.

작은 진공 PEC 도파관 참조 검증을 기반으로 단일 포트 IFA와 원호로 확장한다. 사용자 형상/물성/급전 모델, NF2FF, 정식 mesh/경계/시간 수렴 및 실측, 전체 앱 메모리와 60/30 fps 예산은 후속 검증이다.
