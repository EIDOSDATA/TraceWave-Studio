# 재부팅 후 개발 재개

기록일: 2026-11-07 KST

작업 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`, 설계 기준선은 RFAD-D0-3.4다. 이 문서는 이번 구현 다음 작업의 순서와 완료 기준을 정리한다. Windows 재부팅과 Linux 설치를 자동으로 수행하는 문서가 아니다.

## 저장한 상태

- 표현식/의존 그래프, 초기 설계 데이터, 프로젝트 명령/저장/스냅샷과 목적별 입력 검사를 구현했다.
- 최소 wxWidgets GUI와 별도 Python 서비스 연결, Windows 빌드/실행 도우미를 구현했다.
- 서비스 `.venv`와 CAD `.venv-cad`를 분리했다. CadQuery/OCCT의 박스 STEP 왕복을 확인했다.
- Windows 전체 시험 166개 통과. 이후 GUI 종료 처리 보완본의 관련 5개 시험도 다시 통과했다.
- WSL 설치 요청은 Windows 재부팅 필요 응답을 받았고, 마지막 확인에서 등록된 Linux 배포는 없었다. openEMS 설치/실행은 아직 미완료다.

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
| 3 | GUI 설계 편집 | 매개변수와 표현식, 기판/적층/재료/포트의 속성 편집을 기존 명령 서비스에 연결. 오류 위치 표시, undo/redo, 2D 선/원호 편집 검증 |
| 4 | 격리 CAD worker | 의미 데이터에서 OCCT 형상 생성, 단위/좌표/적층 변환, 접속/급전 검증, STEP 출력과 독립 수신 CAD 재열기 |
| 5 | 실제 RF 해석과 결과 | 완전한 참조 계산 검증 후 단일 포트 IFA, 이어 원호 검증. S11/임피던스/전력과 NF2FF 방사 패턴, 수렴/정확도 근거 확보 |
| 6 | 성능과 내부 배포 | 실제 편집 장면으로 60/30 fps 및 전체 프로세스 메모리/시작 시간 측정. 취소/복구, 라이선스 고지, 재현 가능한 내부 검증 패키지 점검 |

순서 1~2의 환경 구성과 순서 3의 Windows GUI 편집은 병행할 수 있다. 실제 IFA 해석은 참조 계산 및 CAD/급전 모델 검증을 마친 뒤 진행한다. Linux GUI는 후속 범위를 유지한다.

Linux 시험에서는 현재 표현식 캐시의 정확한 재평가 일치가 다른 OS 수학 라이브러리에서도 유지되는지 확인한다. 차이가 발생하면 기존 스냅샷을 조용히 다시 쓰지 않고 엔진/런타임 호환 정책과 명시적 전환 규칙을 먼저 정한다.

초기 IFA의 목표 대역/크기/두께는 승인 기준을 사용한다. 실제 유전율/손실/전도도, 제작 적층과 마스크, 급전/측정 조건은 후속 입력으로 확정한다. 미정 물성을 임의 FR4 상수로 채우지 않으며, 0.93 mm 잔여 두께를 실제 코어 두께 확정값으로 간주하지 않는다.

## 기존 Windows 환경을 확인할 때

GUI 실행:

```powershell
.\tools\launch_gui.ps1
```

Windows 코드나 native 환경을 변경한 뒤 전체 시험이 필요할 때:

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_GUI_EXE = (Join-Path (Get-Location).Path 'build/windows-release/bin/tracewave_gui.exe')
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

재부팅 자체만으로 기존 가상환경을 삭제하거나 모든 의존성을 재설치할 필요는 없다. 환경을 새로 구성해야 할 때는 [Python 환경](python_environment.md), [wxWidgets 빌드](../ui/wxwidgets/README.md)의 절차를 따른다. 현재 구현과 미검증 범위의 상세 기록은 [개발 상태](development_status.md)에 있다.
