# 재부팅 후 개발 재개

최초 기록일: 2026-11-07 KST

상태 갱신일: 2026-11-10 KST

작업 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`, 설계 기준선은 RFAD-D0-3.4다. 이 문서는 이번 구현 다음 작업의 순서와 완료 기준을 정리한다. Windows 재부팅과 Linux 설치를 자동으로 수행하는 문서가 아니다.

2026-11-10에 재부팅 후 전용 배포 설치와 Linux 서비스/표현식 검증을 완료했다. 이어 Qt 없는 openEMS/CSXCAD/VTK 빌드와 작은 도파관의 두 격자 참조 검사도 통과했다. 이후 wxAUI 작업 공간, 기판/미정 도체층/선/원호 생성, 2D 직접 편집과 문제 위치 이동을 연결했다. 2D 경계 보완본의 Windows 전체 227개가 76.152초에 통과했고 Linux는 220개 통과/Windows GUI 7개 스킵으로 30.312초였다. native CTest 1개도 0.13초에 통과했다. 이 수치는 당시 2D 버전의 기록이며 도구막대/DPI 보완 및 최신 전체 결과는 [개발 상태](development_status.md)를 따른다.

다음 단계로 별도 호스트 CAD worker, Open CASCADE 유전체/선/원호 고체와 AP242 STEP/B-rep 출력을 연결했다. 이어 GUI STEP 출력/취소/완료 결과 복원, 유전체층 생성과 wxGLCanvas 3D 보기를 구현했다. 원본 sidecar와 실제 schema/단위/이름/형상 재입력은 같은 kernel이며 내부 기하 profile은 `generated_unverified`다. WSL solver worker의 준비/실행/취소/저장과 도파관 두 격자 검증까지 연결했다. 이후 우선 작업은 사용자 안테나 모델 투영, 재료/net/포트 생성 UI와 실제 급전/접속, GUI 해석 작업/결과 화면, 독립 CAD 및 물리 검증이다. 2D 스냅/치수/endpoint, 3D LOD와 실제 GPU reset/DPI/도킹 복구 및 성능 실측도 남는다. 아래 첫 작업은 새 PC나 배포 미등록 상태에서의 재개 절차로 유지한다. Linux 근거는 [Linux 환경](linux_environment.md), CAD 범위는 [CAD/STEP 계약](cad_contract.md)에 있다.

## 최초 재부팅 전 저장한 상태

- 표현식/의존 그래프, 초기 설계 데이터, 프로젝트 명령/저장/스냅샷과 목적별 입력 검사를 구현했다.
- 최소 wxWidgets GUI와 별도 Python 서비스 연결, Windows 빌드/실행 도우미를 구현했다.
- 서비스 `.venv`와 CAD `.venv-cad`를 분리했다. CadQuery/OCCT의 박스 STEP 왕복을 확인했다.
- Windows 전체 시험 166개 통과. 이후 GUI 종료 처리 보완본의 관련 5개 시험도 다시 통과했다.
- 당시 WSL 설치 요청은 Windows 재부팅 필요 응답을 받았고 등록된 Linux 배포가 없었다. 이 과거 상태의 Linux/openEMS 설치는 2026-11-10에 해소했다.

소스, 시험, 의존성 버전/해시, 설치 스크립트와 문서는 Git으로 관리한다. `.venv`, `.venv-cad`, `.local`, `build`는 로컬에 보존되지만 Git에는 포함하지 않는다. 따라서 같은 PC에서는 재부팅 후 기존 환경을 사용할 수 있고, 새 checkout에서는 설치/빌드 스크립트로 다시 구성해야 한다.

## 재부팅 직후 첫 작업

Windows 재부팅을 마친 뒤 PowerShell 7에서 다음으로 시작한다.

```powershell
Set-Location -LiteralPath 'C:\Users\eidos\GitHub\TraceWave Studio\Code'
pwsh -NoProfile -File .\tools\setup_wsl.ps1
```

이 명령은 전용 배포 `TraceWave-Dev`의 등록 여부와 실행 가능 여부를 확인한다. 배포가 없어서 종료 코드 2가 나오면 다음으로 설치를 한 번 재개한다.

```powershell
pwsh -NoProfile -File .\tools\setup_wsl.ps1 -Install
```

관리자 권한이 필요하다는 Windows 응답이 나오면 관리자 PowerShell에서 해당 설치 단계를 수행한다. 설치 경로가 이미 존재하지만 배포가 등록되지 않은 경우에는 경로의 상태를 먼저 확인한다. 스크립트는 기존 디렉터리를 삭제하거나 덮어쓰지 않는다.

완료 기준은 Ubuntu 24.04가 WSL2에서 실제 실행되고 스크립트가 종료 코드 0을 반환하는 것이다. 설치 프로그램의 종료 코드 0만으로 성공을 판단하지 않는다. `.local/wsl/status.json`의 registered/runnable과 상태를 확인한다. 여기까지 완료해도 openEMS 준비 완료는 아니다. 자세한 조건은 [WSL 환경](wsl_environment.md)을 따른다.

## 이어서 진행할 순서

| 순서 | 작업 | 완료 기준 |
| --- | --- | --- |
| 1 | Linux 개발 환경과 서비스 시험 | 전용 배포 안에 Linux용 Python 환경 구성. Windows 가상환경/휠 lock을 재사용하지 않음. 저장/잠금/복구/공백 및 한글 경로/표현식 시험을 실제 실행하고 OS별 스킵을 구분하여 기록 |
| 2 | Qt 없는 headless openEMS 환경 | openEMS/CSXCAD 소스와 의존성 버전 고정, GUI 의존성 제외 확인, 실제 import/실행 및 작은 참조 사례 검사, runtime profile 갱신 |
| 3 | GUI 설계 편집 | wxAUI 탐색/2D/속성/문제/로그, 기판/미정 도체층/선/원호 생성, 선택/이동/삭제와 영속 undo/redo 연결. 전체 회귀 통과, 배치 보완 후 확인 상태는 개발 기록 참조. 재료/포트 생성과 스냅/치수/endpoint 편집은 후속 |
| 4 | 호스트 CAD와 GUI 연결 | 분리 실행/취소/봉인, 유전체/선/원호 고체와 AP242 출력, GUI STEP/3D와 완료 결과 복원 구현. 다음은 재료/net/포트 생성 UI, 실제 접속/급전, 독립 수신 CAD 검증과 표시 LOD/실제 context 복구 수용 |
| 5 | WSL solver와 실제 RF 해석 | guest supervisor와 도파관 준비/실행/취소/원시 후처리 연결 완료. 다음은 사용자 모델과 단일 포트 IFA, 이어 원호 검증. S11/임피던스/전력과 NF2FF 방사 패턴, 수렴/정확도 근거 확보 |
| 6 | 성능과 내부 배포 | 실제 편집 장면으로 60/30 fps 및 전체 프로세스 메모리/시작 시간 측정. 취소/복구, 라이선스 고지, 재현 가능한 내부 검증 패키지 점검 |

순서 1~2의 초기 환경과 작은 참조 검증, 순서 3의 기본 2D 편집과 순서 4의 호스트 CAD/GUI STEP/3D를 연결했다. CAD 실행은 WSL을 사용하지 않으며 solver는 별도 [WSL guest 구현](solver_contract.md)을 사용한다. 환경이 이미 준비된 PC에서는 설치보다 최신 소스/빌드/검증 상태를 먼저 확인한다. 실제 IFA 해석은 참조 계산 및 CAD/급전 모델 검증을 마친 뒤 진행한다. Linux GUI는 후속 범위를 유지한다.

현재 2D 캔버스는 두 번 클릭한 선분, 중심/시작/끝 방향을 지정하는 원호와 Shift CW, 드래그 이동, 삭제, Esc 취소, fit/휠 확대/가운데 버튼 이동을 제공한다. 정확한 좌표/반지름/각도는 `좌표 입력`을 사용한다. 그리드 표시는 마우스 스냅이 아니며 물리 원본을 바꾸지 않는다. [2D 표시/편집 계약](canvas_contract.md)과 [GUI 조작](../ui/wxwidgets/README.md)을 참고한다.

Linux 시험에서는 현재 표현식 캐시의 정확한 재평가 일치가 다른 OS 수학 라이브러리에서도 유지되는지 확인한다. 차이가 발생하면 기존 스냅샷을 조용히 다시 쓰지 않고 엔진/런타임 호환 정책과 명시적 전환 규칙을 먼저 정한다.

초기 IFA의 목표 대역/크기/두께는 승인 기준을 사용한다. 실제 유전율/손실/전도도, 제작 적층과 마스크, 급전/측정 조건은 후속 입력으로 확정한다. 미정 물성을 임의 FR4 상수로 채우지 않으며, 0.93 mm 잔여 두께를 실제 코어 두께 확정값으로 간주하지 않는다.

## 기존 Windows 환경을 확인할 때

GUI 실행:

```powershell
.\tools\launch_gui.ps1
```

설치된 `.venv-cad`는 실행 도우미가 자동으로 연결한다. 다른 CAD Python은 `-CadPython <경로>`로 지정한다. 기본 CAD 환경이 없으면 편집/저장과 기존 완료 mesh 조회는 가능하고 새 STEP/3D 생성은 비활성화된다. 이번 GUI는 wx gl/opengl32/bcrypt를 사용하므로 이전 2D 실행 파일을 새 소스의 빌드 증거로 사용하지 않는다. native 코드를 바꿨다면 [wxWidgets 빌드](../ui/wxwidgets/README.md#개발-환경과-빌드)부터 수행한다.

Windows 코드나 native 환경을 변경한 뒤 전체 시험이 필요할 때:

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_GUI_EXE = (Join-Path (Get-Location).Path 'build/windows-release/bin/tracewave_gui.exe')
$env:RFAD_CAD_PYTHON = (Resolve-Path '.venv-cad/Scripts/python.exe').Path
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv-cad\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_cad_native.py -v
ctest --preset windows-release
```

서비스 가상환경의 전체 시험은 CAD 패키지를 import하지 않으므로 native 기하 시험은 위 두 번째 환경에서 별도로 실행한다. `RFAD_CAD_PYTHON`이 없으면 실제 서비스-CAD 프로세스 통합 시험은 스킵된다. 고정 CadQuery 2.8.0/cadquery-ocp 7.9.3.1.1 환경은 [Python 환경](python_environment.md)을 따른다.

GUI에서 `유전체층`과 도체층을 만들고 속성에서 실제 z 위치/두께를 입력한 뒤 `STEP 출력` 또는 `3D 갱신`을 누른다. 입력은 snapshot으로 고정되며 실행 중 편집/저장을 계속할 수 있다. 하단 `CAD 출력`에서 취소/결과 경로/출력 폴더를 확인한다. 생성된 3D가 현재 개정과 다르면 이전 설계로 표시되며 재열기는 마지막 게시 완료 결과를 복원한다. 출력에는 명시적 유전체 층과 기하 치수가 필요하며 미정 RF 물성은 원본 그대로 보존한다.

자동화용 [개발 CLI](../README.md#현재-실행-방법)의 `tools/export_step.py`도 유지한다. CLI를 별도로 실행할 때는 GUI 입력을 적용/저장하고 같은 workspace의 GUI/서비스를 닫는다. `export.preview`, `geometry.build`, `export.build`는 같은 불변 snapshot을 기준으로 하는 비동기 API다. 접수 때 runtime/소스 묶음을 고정하므로 서비스 실행 중 Python 소스를 바꾸면 새 서비스를 시작하고 새 작업으로 검증한다. 결과 cache를 재사용하지 않는다.

서비스 비정상 종료 후 CAD 작업이 `outcome_unknown`으로 남으면 해당 슬롯 예약을 유지한다. 자동 재실행이나 PID만을 보고 강제 정리하지 않는다. 현재 공개 수동 조정 API는 없으며 기존 편집/저장/조회는 계속 사용할 수 있다. 복구와 미게시 staging의 의미는 [worker 연결 경계](worker_integration.md)를 따른다.

재부팅 자체만으로 기존 가상환경을 삭제하거나 모든 의존성을 재설치할 필요는 없다. 환경을 새로 구성해야 할 때는 [Python 환경](python_environment.md), [wxWidgets 빌드](../ui/wxwidgets/README.md)의 절차를 따른다. 현재 구현과 미검증 범위의 상세 기록은 [개발 상태](development_status.md)에 있다.

WSL solver 재검증은 [해석 worker 계약](solver_contract.md)의 `verify_openems_worker.py`를 새 workspace/report 경로로 실행한다. 이전 실행이 interrupted/outcome_unknown이면 동일 runtime의 `--reconcile-job`으로 guest 종료를 확인하며 새 실행으로 대체하지 않는다. 결과는 solver 환경 없이도 등록된 workspace의 `result.open`으로 조회할 수 있다. 다음 기능은 사용자 형상/물성/급전 투영과 GUI 해석 실행/결과 표시이고, 검증 순서는 단일 포트 IFA 다음 원호를 유지한다.
