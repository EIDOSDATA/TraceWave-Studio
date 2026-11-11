# 재부팅 후 개발 재개

최초 기록일: 2026-11-07 KST

상태 갱신일: 2026-11-11 KST

작업 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`, 설계 기준선은 RFAD-D0-3.4다. 이 문서는 이번 구현 다음 작업의 순서와 완료 기준을 정리한다. Windows 재부팅과 Linux 설치를 자동으로 수행하는 문서가 아니다.

2026-11-10에 재부팅 후 전용 배포 설치와 Linux 서비스/표현식 검증을 완료했다. 이어 Qt 없는 openEMS/CSXCAD/VTK 빌드와 작은 도파관의 두 격자 참조 검사도 통과했다. 이후 wxAUI 작업 공간, 기판/미정 도체층/선/원호 생성, 2D 직접 편집과 문제 위치 이동을 연결했다. 2D 경계 보완본의 Windows 전체 227개가 76.152초에 통과했고 Linux는 220개 통과/Windows GUI 7개 스킵으로 30.312초였다. native CTest 1개도 0.13초에 통과했다. 이 수치는 당시 2D 버전의 기록이며 도구막대/DPI 보완 및 최신 전체 결과는 [개발 상태](development_status.md)를 따른다.

다음 단계로 별도 호스트 CAD worker, Open CASCADE 유전체/선/원호 고체와 AP242 STEP/B-rep 출력을 연결했다. 이어 GUI STEP 출력/취소/완료 결과 복원, 유전체층 생성과 wxGLCanvas 3D 보기를 구현했다. 원본 sidecar와 실제 schema/단위/이름/형상 재입력은 같은 kernel이며 내부 기하 profile은 `generated_unverified`다. WSL solver worker의 준비/실행/취소/저장과 도파관 두 격자 검증까지 연결했다. 이어 사각/원형 PCB의 사용자 물성/패턴/동일 평면 단일 급전과 GUI 해석/취소/결과 그래프, 재료/net/포트 생성 UI를 연결했다.

이후 구멍을 가진 접지 polygon, 원형/회전 사각 pad, 명시적 중공 관통 PTH via와 IFA의 접지/급전선/단락부를 원본/GUI/CAD/EM에 연결했다. 단일 포트는 동일 sheet 면의 x/y gap과 층 사이 z gap을 지원한다. 고정 IFA fixture의 격자/경계 거리/시간 종료 연구를 실제 실행했고, 1.6~2.6 GHz의 별도 연구에서 초기 기준의 수치 안정성을 확인했다. 현재 우선 작업은 실제 물성/급전/측정 조건과 2.4 GHz 정합 설계, 국부 특징/곡선/PML의 추가 검증, GUI 수렴 비교, NF2FF와 독립 수신 CAD 검증이다. 실물 SMA launch/정합 부품의 기생 효과는 아직 포함하지 않았다. 2D 스냅/치수/endpoint, 3D LOD와 실제 GPU reset/DPI/도킹 복구 및 성능 실측도 남는다. 아래 첫 작업은 새 PC나 배포 미등록 상태에서의 재개 절차로 유지한다. Linux 근거는 [Linux 환경](linux_environment.md), CAD 범위는 [CAD/STEP 계약](cad_contract.md), 도체 모델은 [도체와 IFA 확장](copper_features.md)에 있다.

코드 구조 정리에서는 주 창 진입점, 화면별 이벤트 연결, 순수 표시/작업 상태와 통합 시험을 분리했다. 프로젝트 서비스와 CAD/solver도 책임별 모듈로 분리했으며 공개 API/저장 schema는 유지한다. 새 기능을 추가할 위치와 검증 규칙은 [코드 구조](code_structure.md)를 먼저 확인한다. 최신 회귀 결과는 [개발 상태](development_status.md)에 기록한다.

2026-11-11 추가 자료 정리: `00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026`의 57,340개 관측과 공식 원문을 정리하고 회사별 엑셀을 제공했다. [PCB 재료 카탈로그 설계](pcb_material_catalog.md)에 직접 입력/소재/제조업체 선택, 구조화 출처와 원자적 적층 적용 순서를 기록했다. 이 작업은 자료와 설계 문서에 한정했으며 제품 코드/프로젝트 schema/solver 입력은 변경하지 않았다. 카탈로그 기능 구현을 시작할 때 이 문서와 자료의 검토 사유를 먼저 확인한다.

PCB 선택 기능의 첫 구현 묶음인 중립 카탈로그 계약, JSONL/원시 적층 자료의 오프라인 변환, 읽기 전용 SQLite 검색/상세 CLI/API를 구현했다. 기존 직접 입력은 유지한다. [카탈로그 조회 계약](pcb_catalog_contract.md)의 명령으로 `.local/pcb-catalog/catalog.sqlite` 상태를 확인한다. 새 checkout에는 DB가 없으므로 원문 패키지로 build를 실행한다. 변환 규칙 버전이 다르면 재구축하며 정상 DB를 매번 다시 만들 필요는 없다. 이어 선택 출처와 사용자 수정값 저장, 원자적 적층 적용/undo, wxWidgets 미리보기, CAD/solver 검증 순으로 진행한다.

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
| 3 | GUI 설계 편집 | wxAUI 탐색/2D/속성/문제/로그, 사각/원형 기판/층/선/원호/재료/net/단일 포트 생성과 영속 undo/redo 연결. polygon/pad/via 생성, 좌표 표와 다중 pad 선택 추가. 최신 시험 근거는 개발 기록 참조. 스냅/치수/endpoint 편집은 후속 |
| 4 | 호스트 CAD와 GUI 연결 | 분리 실행/취소/봉인, 유전체/선/원호/polygon/pad/PTH의 실제 고체와 AP242 출력, GUI STEP/3D 및 완료 결과 복원 구현. 다음은 독립 수신 CAD 검증, 실물 SMA/실장 모델과 표시 LOD/실제 context 복구 수용 |
| 5 | WSL solver와 실제 RF 해석 | guest supervisor와 도파관 준비/실행/취소/원시 후처리 연결 완료. 사용자 사각/원형 PCB 및 IFA 접지/급전/단락부와 PTH를 소비하고 GUI S11/VSWR/임피던스 결과 표시. [IFA study](ifa_convergence.md)는 격자/경계 거리/시간 종료의 고정 행렬과 실행/재개/재판정 도구를 연결. 실제 판정/근거는 개발 상태 참조. 실제 물성/측정 대조, PML cell 수 변화, 원형/원호와 NF2FF/방사/절대 전력은 별도 후속 |
| 6 | 성능과 내부 배포 | 실제 편집 장면으로 60/30 fps 및 전체 프로세스 메모리/시작 시간 측정. 취소/복구, 라이선스 고지, 재현 가능한 내부 검증 패키지 점검 |

순서 1~2의 초기 환경과 작은 참조 검증, 순서 3~4의 편집/CAD/GUI STEP/3D 및 순서 5의 사용자 PCB 실행 경로를 연결했다. CAD 실행은 WSL을 사용하지 않으며 solver는 별도 [WSL guest 구현](solver_contract.md)을 사용한다. 환경이 이미 준비된 PC에서는 설치보다 최신 소스/빌드/검증 상태를 먼저 확인한다. IFA 실행 fixture의 접지/급전 도체 모델은 구현했지만 결과는 `computed_unvalidated`이며 정식 수렴/실측 검증으로 승격하지 않는다. Linux GUI는 후속 범위를 유지한다.

현재 2D 캔버스는 두 번 클릭한 선분, 중심/시작/끝 방향을 지정하는 원호와 Shift CW, 드래그 이동, 삭제, Esc 취소, fit/휠 확대/가운데 버튼 이동을 제공한다. 정확한 좌표/반지름/각도는 `좌표 입력`을 사용한다. 그리드 표시는 마우스 스냅이 아니며 물리 원본을 바꾸지 않는다. [2D 표시/편집 계약](canvas_contract.md)과 [GUI 조작](../ui/wxwidgets/README.md)을 참고한다.

polygon은 첫 loop를 외곽, 빈 줄 이후 loop를 빈 영역으로 입력하고 속성의 coordinate_table에서 숫자/미정/매개변수 결합을 편집한다. 좌표 셀의 unit은 보통 mm이며 환산 overflow가 나는 유한 원본은 m로 표시한다. unit은 읽기 전용이고 선택지는 coordinate_choices에서 공유한다. 바꾸지 않은 셀의 단위/출처/결합은 보존한다. via는 시작/끝 도체층과 연결 pad를 명시하며 pad_ids는 다중 선택한다. 미정 구멍/도금은 저장할 수 있지만 실제 지름을 그리거나 계산에 사용할 때 임의값을 채우지 않는다.

Linux 시험에서는 현재 표현식 캐시의 정확한 재평가 일치가 다른 OS 수학 라이브러리에서도 유지되는지 확인한다. 차이가 발생하면 기존 스냅샷을 조용히 다시 쓰지 않고 엔진/런타임 호환 정책과 명시적 전환 규칙을 먼저 정한다.

초기 IFA의 목표 대역/크기/두께는 승인 기준을 사용한다. 실제 유전율/손실/전도도, 제작 적층과 마스크, 급전/측정 조건은 후속 입력으로 확정한다. 미정 물성을 임의 FR4 상수로 채우지 않으며, 0.93 mm 잔여 두께를 실제 코어 두께 확정값으로 간주하지 않는다.

별도 IFA/PTH 실행 fixture에는 재현을 위한 물성/치수 가정을 명시한다. 이를 승인된 초기 입력의 미정 물성에 복사하거나 기본 제조값으로 사용하지 않는다. 현재 IFA fixture는 이상적인 로컬 안테나 gap을 기준면으로 사용하므로 실물 SMA 접속면, 마스크, 정합 부품/케이블과 측정 디임베딩을 추가로 확정해야 한다.

이번 [IFA 수렴 계약](ifa_convergence.md)은 mesh 최소 3수준, 마지막 복소 S 변화 0.02 이하와 동일 branch 공진 변화 1% 이하를 fixture 전용 acceptance로 사전 채택한다. 최초 study는 2~3 GHz 201점/손실 환산 중심 2.5 GHz를 사용하고, 별도 반사 최소점 study는 1.6~2.6 GHz 201점/중심 2.1 GHz를 사용한다. 두 연구는 서로 다른 입력과 보고서를 유지한다. band 끝의 최소값이나 공진 부재는 공진 수렴으로 판정하지 않는다. 어느 study도 목표 끝 2.4835 GHz를 평가하지 않으므로 이 결과만으로 전 대역 정합 합격을 선언하지 않는다. 두 study의 graded air는 kind=graded_air/air_cell_mm=6/growth_ratio=1.5, 말단 PML8의 두께는 48 mm다. 내부 임계선 전체에 성장률 상한을 강제하지 않으므로 metadata의 실제 축별 비율도 확인한다. matrix/자원 검사와 실제 판정은 해당 계약과 개발 상태를 먼저 확인한다.

이 수렴 비교는 고정 격자 생성 정책의 설정 series를 평가한다. grid_mm을 줄여도 모든 짧은 임계 구간이 함께 세분화되지는 않으므로 국부 최소 특징 전체의 수렴이나 Richardson/점근 정확도를 주장하지 않는다. 현재 study는 CLI/JSON/CSV로 사용하며 GUI의 여러 run 비교/행렬 관리 화면은 후속 작업이다.

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

WSL solver 재검증은 [해석 worker 계약](solver_contract.md)의 `verify_openems_worker.py`를 새 workspace/report 경로로 실행한다. 이전 실행이 interrupted/outcome_unknown이면 동일 runtime의 `--reconcile-job`으로 guest 종료를 확인하며 새 실행으로 대체하지 않는다. 결과는 solver 환경 없이도 등록된 workspace의 `result.open`으로 조회할 수 있다. 사용자 PCB 실행은 [PCB 계약](pcb_solver_contract.md)의 `verify_pcb_worker.py`로 별도 검증하며 `--fixture`로 원형 선/원호, IFA 급전 또는 PTH 사례를 선택한다. GUI 해석은 `launch_gui.ps1 -OpenEmsWsl`로 활성화한다. 현재 고정 IFA study의 완료 근거를 보존한 뒤 실제 물성/급전 조건, 목표 대역 설계와 남은 국부/PML 검증을 진행하고 원형 PCB/원호와 NF2FF로 확장한다. 독립 수신 CAD의 STEP 확인도 병행한다.

IFA study 전용 `tools/verify_ifa_convergence.py`는 기본값으로 [최초 2~3 GHz manifest](../fixtures/ifa_convergence_study.json)를 사용한다. 각 study의 8개 비교 행을 6개 고유 실행으로 처리하며 먼저 모든 plan을 봉인/검증하고 실제 계산을 시작한다. `--resume`은 기존 요청과 완료 자료를 같은 worker identity에서 이어 쓰며 `--reassess-only`는 solver 환경 없이 완료 결과만 재판정한다. 정확한 명령과 종료 코드 0/1/2는 [실행 계약](ifa_convergence.md#실행-재개와-원본-보존)을 따른다. 진행 report와 파생 CSV는 갱신 가능하지만 raw/plan/result 및 `report.assessments/<UUID>.json`의 이전 판정은 immutable이다. 실행 실패/취소와 미평가 공진을 정상 수렴으로 바꾸지 않는다.

공진 대역의 [별도 study](../fixtures/ifa_convergence_resonance_study.json)를 재개할 때는 `--study fixtures/ifa_convergence_resonance_study.json`과 그 연구의 workspace/report를 지정한다. 이 연구는 1.6~2.6 GHz/중심 2.1 GHz의 별도 입력이다. 최초 2~3 GHz/중심 2.5 GHz 연구와 손실 환산/여기가 달라 결과를 섞거나 기존 보고서를 대체하지 않는다. 먼저 각 연구의 완료 상태와 판정 근거를 읽고 남은 작업만 진행한다.

제품 소스 묶음의 판정기만 보완해도 code_files hash가 달라지므로 이전 연구에 현재 checkout의 `--resume`을 적용하면 거절될 수 있다. 완료 자료의 재평가는 `--reassess-only`를 사용하며 실제 FDTD를 추가하지 않는다. 이전 실행의 정확한 재개에는 캡처 당시 소스/설치 identity가 필요하고 현재 소스로 새 native 계산을 하려면 새 workspace/report를 사용한다. 원래 계산 소스와 후속 판정기 소스를 각각 보존한다.

최초 study의 6개 native 실행은 완료했다. 마지막 복소 S11 변화는 격자/경계/종료 세 축 모두 기준 안이지만 2.0 GHz 대역 끝이 표본 최소값이라 내부 반사 최소점 추적은 미평가이며 전체는 `not_established`다. 실제 재판정/재개에서도 결과 참조/CSV가 같고 새 FDTD가 없음을 확인했다. [최초 연구 결과](ifa_convergence.md#최초-2030-ghz-연구의-실제-결과)를 보존하고 별도 공진 대역 연구의 진행 상태를 확인한다. S11 dip과 X=Im(Z)=0의 전기적 공진을 같은 정의로 취급하지 않는다.

별도 1.6~2.6 GHz 연구의 6개 실행도 완료했고 격자/경계/시간 종료의 최종 비교와 전체가 `established`다. 반사 최소점은 표본 1.920 GHz, bracket [1.915, 1.925] GHz이며 보수적 이동 상한이 1% 이하다. 이 결과는 고정 fixture의 수치 안정성이고 2.4 GHz 정합 목표나 실측 합격이 아니다. [별도 연구 결과](ifa_convergence.md#별도-1626-ghz-연구의-실제-결과)와 [runtime 기록](../runtime_profiles/ifa-convergence-wsl.json)을 확인하고, 완료 연구의 자동 재실행보다 남은 실제 입력/목표 설계/GUI 비교를 우선한다.

두 연구는 실제 경계/PML 비교 가드를 추가한 최종 판정기로 다시 평가했고 추가 가드 통과 및 기존 지표/상태 보존을 확인했다. 이 재판정에는 추가 FDTD가 없으며 native 산출물/CSV/이전 판정도 유지했다. 각 폴더의 `post-guard-reassessment-evidence.json`을 확인한다. 판정기 변경으로 현재 worker source identity는 원래 실행과 다를 수 있으므로 완료 자료에는 `--reassess-only`를 사용하고, 새 native 연구는 새 workspace/report로 시작한다.
