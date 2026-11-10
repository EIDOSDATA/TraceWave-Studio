# 개발 착수와 현재 상태

최초 기록일: 2026-11-07 KST

상태 갱신일: 2026-11-11 KST

제품 개발 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`다. 승인 기준선은 RFAD-D0-3.4, 커밋 `6ebeda156e9d31b893bf69046550f5df9b16dc64`다. 01_Docs와 승인 records는 변경하지 않았다. 기준선의 착수 전 표기는 당시 승인 기록이며 현재 상태는 R0 기초 구현 진행이다.

wxWidgets, Windows 11+WSL2 우선, Linux GUI 후속, 원호/IFA, 내부 검증 배포와 60/30 fps 초기 목표를 유지한다. WSL 개발 환경과 작은 해석 참조 사례 검증, GUI 선택 속성/영속 undo/redo와 wxAUI 기반 2D 편집 다음으로 별도 호스트 CAD worker와 Open CASCADE 형상/AP242 STEP 출력을 연결했다. 이어 GUI STEP 출력/작업 취소/완료 결과 복원과 wxGLCanvas 3D 형상 보기를 구현했다. WSL2 guest supervisor와 도파관 solver adapter의 준비/실행/취소/결과 저장 및 독립 후처리도 연결했다.

## 구현 현황

| 항목 | 구현과 증거 | 남은 범위 |
| --- | --- | --- |
| 단위와 정규 직렬화 | SI Quantity, 미정 상태, 출처, 제한 JSON codec/hash | 복소수, 불확도, 충돌 후보, 물리 cache subset |
| 표현식 | 전용 parser, 차원/정의역 검사, UUID bindings, 의존 그래프 재계산, 순환 차단. Windows/Linux 49개 수식과 그래프/IFA 캐시 비교 통과 | 다른 CPU/엔진 조합과 추가 수식의 계산 캐시 호환 검증 |
| 실제 설계 데이터 | 기판, 적층, 재료, net, 선/원호, 단일 lumped port. 참조 무결성과 역명령 | 패드/비아/polygon, 실제 급전/접속 판정 |
| 목적별 입력 검사 | API-006 draft revision의 geometry/step/em, 고정 입력 TaskRef, 누락 진단 | snapshot 입력, 제조/물리 profile, solver 지원 검증 |
| 명령/저장/스냅샷 | revision/receipt 원자 게시, 재시작, crash 경계. 0.1 읽기 및 새 개정 0.2 전환. 영속 undo/redo와 history head 보호 | 이력 grouping/임의 이동, 독립 archive/import, GC, 정전 내구성 |
| Python 환경 | 서비스 .venv와 별도 .venv-cad, 44개 CAD 패키지 버전/wheel SHA256 고정 | 배포 패키지와 전체 라이선스 검증 |
| CAD 환경 smoke | CadQuery 2.8.0/cadquery-ocp 7.9.3.1.1 박스 AP214 export/reimport의 초기 호환성 기록 | 배포 환경과 독립 수신 CAD 검증 |
| CAD 기하와 STEP | 불변 snapshot을 mm로 투영, 직사각 유전체와 양수 두께 선/원호 고체, 같은 층/net/재료 병합과 원본 UUID mapping, AP242 실제 schema/단위와 별도 OCCT reader 재입력, B-rep/원본 sidecar | 독립 kernel 수신 CAD, pad/via/hole/polygon, 제조 및 RF 검증. 현재 내부 기하 profile은 generated_unverified |
| CAD worker와 API | 호스트 설정의 별도 프로세스, 입력/runtime/소스 묶음 봉인, 실행 중 편집/저장/조회, 취소/timeout/출력 제한, nonce와 파일 streaming 봉인/원자 게시. API-008/023/024 비동기 TaskRef와 STEP CLI, cad.latest 완료 참조 조회 | CAD outcome_unknown 수동 조정 API, 자동 GC/cache |
| GUI 작업 공간 | C++ wxMSW/wxAUI의 탐색/중앙 2D와 3D 탭/속성/문제/로그/CAD 출력 배치, 패널 복원, 안정 ID 선택 동기화, 한글 속성과 입력 상태, 매개변수/표현식/UUID 결합, 영속 Ctrl+Z/Y/Shift+Z | 재료/net/포트 생성 UI, 해석 결과/비교/제조 출력 작업 공간, DPI/접근성과 전체 앱 성능 측정 |
| GUI STEP와 3D | 적용 후 불변 snapshot 접수, CAD 중 편집/저장, 취소와 출력 폴더, 이전 개정 표시 및 재열기 완료 결과 복원. 실제 OCCT 고체에서 생성한 표시 mesh의 background hash/경계 검사, 지연 wxGLCanvas 생성, 회전/이동/확대/선택, 오류 시 context 재생성 재시도 | LOD, 실제 GPU reset/DPI/도킹 복구 수용, 대형 장면/성능 예산, 독립 CAD와 제조/RF 판정 |
| 2D 직접 편집 | 기판/미정 도체층/미정 유전체층 생성, 두 점 선분, 중심/시작/끝 방향 원호와 Shift CW, 수치 좌표 생성, 선택/이동/삭제, preview와 단일 명령 commit, fit/zoom/pan | 마우스 스냅, endpoint 편집/회전/미러/구속/Boolean/고급 도면, 정밀도와 최종 시각 수용 |
| GUI 입력 검사 | 명시적 EM 입력 검사, 문제 목록과 객체/필드 이동, 이전 revision 진단 이동 거절 | 실제 연결/제조/solver 지원 검증과 실행 작업 패널 |
| WSL/openEMS 환경 | Ubuntu 24.04.5 WSL2 실행, Linux 서비스 및 표현식 비교 통과. Qt 없는 openEMS 0.37.0/CSXCAD 0.7.0 빌드와 두 격자 도파관 참조 검사 통과 | IFA/NF2FF와 정식 수렴/정확도 검증 |
| WSL solver와 결과 | AnalysisPlan/PreparationArtifact/PreparedPlan, 준비 XML의 실제 CLI 실행, 종료 확인 뒤 raw/정규화/출처 봉인, 독립 후처리와 result.open. ext4 staging, supervisor/watchdog, nonce/lease/재접속/취소, unknown 예약과 유지보수 CLI | 사용자 형상/물성/급전 투영, GUI 해석 실행/결과, 공개 수동 조정, cache/GC, IFA/NF2FF와 정식 수렴 |

서비스는 rfad.api/2.0, workspace profile은 rfad.projects/0.2, 새 문서는 rfad.project/0.2다. 세부 계약은 [저장](project_persistence.md), [설계 데이터](design_data.md), [선택 속성](editor_contract.md), [2D 표시/편집](canvas_contract.md), [CAD/STEP](cad_contract.md), [worker 실행](worker_integration.md), [기초 계약](bootstrap_contract.md)을 따른다. 전체 API나 R0/R1 완료를 주장하지 않는다.

## 개발 환경 결과

- Windows 11 AMD64, CPython 3.12.10, Intel Core i7-1365U, 약 32 GiB RAM에서 확인했다.
- CMake 4.3.2, Ninja 1.13.2, MinGW-w64 g++ 16.1.0 UCRT/MCF를 사용한다. MSVC는 현재 PATH에 없다.
- wxWidgets 3.2.12와 nlohmann/json 3.12.0 소스는 공식 배포에서 받아 SHA256을 확인했다. Qt 또는 유료 GUI 부품을 요구하지 않는다.
- GUI 3D 빌드는 기존 core/base/aui에 wx gl을 추가하고 Windows opengl32와 bcrypt를 연결한다. OpenGL 화면은 첫 mesh를 열 때 생성한다. CAD의 기존 44개 고정 Python 패키지 환경은 유지한다.
- 서비스 환경은 pip/setuptools/tracewave-studio이며 CAD/OCP/NumPy/SciPy/VTK/Qt를 import하지 않는다.
- CAD 환경은 전체 고정 의존성 설치와 pip check를 통과했다. Qt 배포/DLL/로딩 모듈이 없다. 박스 10 x 20 x 1.6 mm를 STEP AP214로 저장/재입력하여 유효 solid 1개, 체적 320.0000000000001 mm3를 확인했다. 같은 kernel 왕복이며 독립 CAD 검증은 아니다.
- CAD 첫 import에서 약 30초, 재실행에서 약 5.78초를 관찰했다. 시작 성능 합격 값이 아니며 GUI/서비스와 분리한 worker가 필요하다는 근거다.
- 2026-11-07 WSL 설치는 재부팅 필요 상태였다. 2026-11-10 재부팅 후 전용 TraceWave-Dev에 Ubuntu 24.04.5를 설치하고 실제 WSL2 실행과 Linux 서비스 시험을 완료했다. Qt 없는 VTK/openEMS/CSXCAD와 바인딩을 빌드하고 작은 TE10 도파관의 두 격자 검사를 통과했다. 임피던스 최대 상대 오차는 0.617% 미만, 군지연은 0.108% 미만이며 지정한 종료 에너지 조건도 충족했다. 상세 근거는 [Linux 환경](linux_environment.md), [참조 검사](openems_reference.md)에 있다.

재현 방법과 로컬 보고서는 [Python 환경](python_environment.md), [wxWidgets](../ui/wxwidgets/README.md), [WSL 환경](wsl_environment.md)에 있다. 의존성/빌드/가상환경/호스트 경로가 담긴 보고서는 .local/build/.venv 계열에 두고 Git에서 제외한다. 개발 lock을 제품 배포 manifest로 간주하지 않는다.

## 검증 기록

2026-11-07 Windows 전체 시험 166개가 54.105초에 통과했다. 스킵과 실패는 없다. 기존 109개에 표현식 17개, 그래프 8개, 설계 22개, 저장 통합 5개, 실제 GUI 프로세스 5개를 추가했다. 이후 GUI writer 종료 신호의 mutex 보완본을 재빌드하고 해당 GUI 5개를 다시 실행하여 모두 통과했다(16.342초).

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_GUI_EXE = (Join-Path (Get-Location).Path 'build/windows-release/bin/tracewave_gui.exe')
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

GUI 실행 파일을 지정하지 않으면 Windows 전용 GUI 시험은 스킵된다. 최초 기록 당시 5개, 속성 편집 버전은 6개였으며 현재 2D 시험을 포함해 7개다. 최초 전체 로그는 `.local/all-tests.log`, CAD 근거는 `.local/python/cad-smoke.json`, WSL 상태는 `.local/wsl/status.json`에 있다.

- 단위/유한값/미정 상태, 정규 바이트/.NET SHA256 비교, 손상과 자원 제한.
- 실제 프로세스의 UTF-8 JSON-RPC, 한글/공백 경로, 재전송/epoch, 파일 잠금과 게시 전후 강제 종료.
- 표현식 차원/정의역/임의 코드 문법 거부, UUID 결합, 연쇄 재계산, 순환/삭제 실패의 원본 보존.
- board/material/layer/net/line/arc/port의 검증과 역명령, 미정 물성과 물성 대역 차단.
- 설계/표현식 명령 -> 저장 -> 스냅샷 -> 종료/재시작 -> 재열기, 이전 스냅샷 바이트 보존.
- 목적별 검증의 입력 revision 고정과 멱등 재접수. 검사 작업 완료와 설계 합격을 별도로 표시.
- 초기 IFA fixture의 승인 기준 치수와 미정 물성/미완성 형상 보존.
- GUI 실제 이벤트 루프에서 한글/공백 경로, 저장/스냅샷/서비스 재시작, 로그 폭주, 과대 프레임, 서비스 조기 종료와 실행 파일 누락 처리.
- 실제 창에서 IFA 기준 입력을 열어 14개 매개변수와 한글 이름/설명이 표시되는 것을 확인했다. 실행 도우미 재실행과 정상 닫기 종료 코드 0도 확인했다.
- wxMSW Release 실제 빌드 및 runtime DLL 배치 완료. 소스 경로의 공백으로 발생한 windres include 문제를 재현하고 작업 디렉터리 지정으로 해결했다.

2026-11-10 신규 시험을 포함한 Windows 전체 183개가 32.002초에 통과했다. Linux는 전체 183개 중 178개 통과, Windows 전용 GUI 5개 스킵이며 실패/오류 없이 13.639초였다. Windows/Linux 표현식 49개, UUID 의존 그래프와 IFA 저장 캐시의 정확 일치도 확인했다. 추가 설치 도구는 Qt 전이 의존성 및 기존 계정/소스 변경 차단을 검증한다. 참조 판정기는 조기 중단과 종료 조건 미충족을 실패로 처리하는 시험을 포함한다. 근거는 `.local/windows-tests-final.log`, `.local/wsl/service-tests-final.log`, `.local/portability/linux-check.json`이다.

이후 설치 도구의 미추적 CMake override 거부와 재사용 VTK 감사 시험 4개를 추가했다. 관련 설치 시험 8개를 Windows/Linux 양쪽에서 다시 통과했고, 보완된 도구의 실제 소스/패키지/전체 native 감사도 통과했다. 전체 회귀 시험과 변경 부분의 후속 검증을 구분한다.

같은 날 편집기 구현 후 Windows 전체 205개가 45.877초에 통과했다(스킵 없음). Linux는 전체 205개 중 199개 통과, Windows 전용 GUI 6개 스킵이며 20.500초였다. 로그는 `.local/editor-windows-tests.log`, `.local/editor-linux-tests.log`다. 서비스 편집/이력 15개, 실제 stdio 편집 재시작 2개와 실제 GUI 편집 1개를 추가했고 이전 설치 guard 4개도 전체 실행에 포함했다.

이어 한글 표시와 입력 방식별 속성 화면을 보완한 버전에서 Windows 전체 207개가 스킵 없이 48.800초에 통과했다. Linux는 전체 207개 중 201개 통과, Windows 전용 GUI 6개 스킵이며 19.513초였다. 로그는 `.local/ux-windows-tests.log`, `.local/ux-linux-tests.log`다. 추가 2개 시험은 한국어 표시와 실제 API 값/UUID/원본 및 읽기 전용 규칙의 분리를 검증한다.

이 버전은 미적용 입력/적용 후 저장 필요/저장됨, 프로젝트 이름과 식별자 tooltip, 한글 선택지와 읽기 전용 display_value, ID/좌표계 상세 접기, 입력 방식별 숨김, 값과 단위의 같은 행 배치, 진단의 객체 UUID 대응과 한글 필드 초점, Ctrl+Shift+Z를 포함한다. 이후 단위만 변경한 초안의 환산 안내와 마지막 적용값 라벨을 보완하고 실제 GUI 6개를 13.780초에 다시 통과했다. 단위 변경 안내의 생성/복원까지 포함한 UX assertion 14개를 편집 프로세스 시험에서 확인한다. 최종 로그는 `.local/ux-gui-final.log`, 소스와 실행 파일 hash를 포함한 실행 요약은 `.local/ux-verification.json`이다.

속성 편집 버전의 GUI 시험은 실제 폼 컨트롤을 사용해 매개변수/의존식 생성, 재계산, 잘못된 수식의 입력/개정 보존, undo/redo와 저장/스냅샷/서비스 재시작을 확인했다. 당시 초기 시각 점검에서 발견한 세로 여백과 선택 후 초점 이동을 수정하고 GUI 6개 시험 및 전체 Windows 시험을 통과했다. 해당 작업 차례의 추가 화면 자동화는 사용자의 Esc 입력으로 중단했으며 수정 후 시각 확인은 완료되지 않았다. 이는 아래 2D 작업 공간의 후속 시각 확인과 별개의 과거 기록이다.

그다음 wxAUI 작업 공간과 2D 편집을 연결한 초기 버전의 실제 GUI 7개 시험이 22.337초에 통과했다. 새 2D smoke의 최종 검사 항목 14개는 도킹, Esc 취소, 두 점 선분, 원호 방향과 hit testing, 선택 동기화, 드래그의 단일 명령, undo/redo, 속성의 장면 반영, 거절된 제스처의 선택 복원, 삭제/취소, 표시 제한, 보기의 원본 불변성, 입력 검사와 실제 해석의 구분, 저장/스냅샷/재시작이다. 독립 stdio 통합 시험 4개는 음수 sweep, 실패/stale 불변성, 참조 좌표 재평가, 미정 치수와 물성 보존도 확인했다.

이후 미정 보드 치수, 표시 범위와 큰 좌표의 native 렌더링 정밀도 경계를 보완한 버전에서 Windows 전체 227개가 스킵 없이 76.152초에 통과했다. Linux는 227개 중 220개 통과, Windows GUI 7개 스킵이며 30.312초였다. 로그는 `.local/canvas-windows-tests.log`, `.local/canvas-linux-tests.log`다. native CTest `canvas_geometry`도 1개 통과(0.13초)했으며 `build/windows-release/Testing/Temporary/LastTest.log`에 기록했다. 이전 207개와 초기 GUI 7개는 해당 시점의 검증 기록으로 유지한다.

실제 Windows 시험 창에서 발견한 상단 도구막대 높이의 잘림과 DPI에 따른 초기 창 크기를 보완했다. 입력 검사 진단의 message_ko 본문 연결, 결과가 64개를 넘을 때 전체/표시 건수 구분, 프로젝트를 연 뒤 조작 안내도 수정했다. 최종 Release 빌드 후 GUI 7개가 25.908초에 다시 통과했다. 로그는 `.local/canvas-gui-final.log`이며 한국어 진단 본문이 실제 목록에 전달되는 assertion도 포함한다. 최종 소스/실행 파일 hash와 검증 요약은 `.local/canvas-verification.json`에 기록했다.

별도 작업 영역의 실제 창에서 상단 도구막대와 탐색/캔버스/속성/문제 패널 배치, 40 x 60 mm 기판의 선/원호 표시, 캔버스 선택과 속성/트리 연동, 검사 사유 표시와 재료 오류를 두 번 눌러 해당 속성으로 이동하는 동작을 확인했다. 시험 창은 정상 닫기로 종료했다. 현재 디스플레이에서 수행한 제한된 시각 확인이며 모든 DPI/다중 모니터/IME 조합이나 성능 예산의 수용을 뜻하지 않는다.

승인된 전체 작업 공간과 현재 구현된 2D/속성/문제 화면의 관계는 [GUI UX 구현 방향](../ui/wxwidgets/README.md#ux-구현-방향)에 정리한다. [완성형 UI 시안](ui_concept.md)은 목표 구성을 설명하는 검토 자료이며 실제 GUI 실행 화면이나 해석 결과의 증거로 취급하지 않는다. 현재 그리드는 표시 설정이며 마우스 스냅은 미구현이다. 치수와 좌표를 정확히 지정할 때는 수치 입력을 사용한다.

현재 소스로 새 Windows 표현식 기준을 만들고 Linux에서 다시 비교했다. 49개 수식/UUID 그래프/IFA 캐시는 정확히 일치했고 기존 결과 hash와도 같았다. 근거는 `.local/portability/windows-editor-baseline.json`, `linux-editor-check.json`이다. 이전 기준이나 스냅샷은 덮어쓰지 않았다.

현재 CAD 구현의 시험은 순수 입력 투영, fake native 프로세스의 종료/출력 경계, 실제 서비스-CAD 분리 실행, 얇은 도체와 signed sweep/완전 원환, 같은 net Boolean과 분리 body 충돌, 실제 AP242 파일과 이름 기반 재입력을 포함한다. 원본 snapshot, 미정 물성/UUID 결합, 파일 SHA256과 sidecar 대응을 확인하며 현재 개정을 편집해도 접수한 출력 입력은 바뀌지 않는다. 서비스 환경에는 CAD 패키지를 import하지 않고 native 시험은 별도 `.venv-cad`에서 실행한다. 보존 예제는 `.local/cad-worker-verification/latest.json`이 가리키는 STEP/B-rep/sidecar와 검증 파일이며, 선/원호 기하 교환 예제로서 실제 IFA 보드의 RF 검증 근거가 아니다.

GUI 3D 연결 전 CAD 버전의 Windows 전체 287개는 279개 통과, 별도 CAD 환경용 8개 스킵으로 148.984초에 완료했다. Linux 전체 287개는 269개 통과, native CAD 8개/Windows CAD 프로세스 2개/Windows GUI 7개/Windows Job Object 1개 스킵으로 81.977초에 완료했다. 실패와 오류는 없다. 스킵된 native CAD 8개는 고정된 `.venv-cad` 환경에서 모두 통과했다(3.184초). Windows 전체 시험에는 실제 GUI 7개와 분리 CAD 프로세스 2개가 포함된다. 로그는 `.local/cad-windows-tests.log`, `.local/cad-linux-tests.log`, `.local/cad-native-tests.log`이며 소스/문서 hash와 요약은 `.local/cad-verification.json`, 실행 환경 기록은 `runtime_profiles/cad-worker-windows-x64.json`이다. 실제 worker 예제와 `tools/export_step.py`를 각각 실행하여 AP242 STEP, B-rep, 원본 sidecar, 검증 보고서와 manifest 게시를 확인했다. CLI 결과는 `.local/cad-worker-verification/cli-fafc6d6d-2de3-4934-8f3b-b650345c9b89.json`에 보존했다. 이전 227개 및 GUI/2D 수치는 해당 구현 시점의 이력으로 유지한다.

이후 GUI의 `STEP 출력`/`3D 갱신`과 하단 `CAD 출력` 작업 기록을 연결했다. 스냅샷 생성 전 폼 입력을 적용하고 CAD 실행 중에는 편집/저장과 상태 조회를 분리한다. 취소/실패는 이전 결과를 유지하고, 현재 개정과 다른 형상은 이전 설계로 표시한다. `cad.latest`는 큰 파일을 열지 않고 해당 프로젝트의 최근 완료 참조만 복원한다. 새 유전체층은 실제 z 위치/두께/재료를 미정으로 유지하며 원본 명령/undo/redo를 따른다.

출력 패키지는 mesh.json을 추가한 6개 파일이다. 표시 mesh의 snapshot/run/body/source 대응과 파일 SHA256을 봉인하고 GUI background에서 같은 바이트를 검증한다. 정확 STEP/B-rep와 표시 삼각형의 오차 계약은 분리한다. 초기 상한은 100000 triangles/300000 vertices/16 MiB이며 wxGLCanvas는 첫 로딩 때 생성한다. 표시 float 변환 뒤 퇴화/방향 뒤집힘과 변 길이 왜곡을 검사하며 실패하면 이전 정상 장면과 게시된 STEP를 유지한다. 회전/이동/확대와 안정 ID 선택을 제공한다. context 오류에서 전체 보기는 기존 canvas의 wxGLContext 재생성을 시도하고 최초 생성 실패는 새 3D 갱신으로 재시도한다. 실제 GPU reset/DPI/도킹 복구 수용과 LOD는 후속이다. 표시 실패가 편집/저장이나 완료 STEP 파일의 접근을 막지 않도록 분리했다.

최종 GUI STEP/3D 버전의 Windows 전체 303개는 294개 통과, 별도 CAD 환경 전용 9개 스킵으로 205.771초에 완료했다. Linux 전체 303개는 282개 통과, native CAD 9개/Windows CAD 프로세스 2개/Windows GUI 9개/Windows Job Object 1개 스킵으로 149.587초에 완료했다. 실패와 오류는 없다. 별도 `.venv-cad`의 native CAD/mesh 9개는 모두 통과했다(4.217초). wxGL을 포함한 Release 전체 빌드와 마지막 화면 보완본 재빌드도 성공했다. native CTest는 canvas_geometry/display_mesh 2개 모두 통과했다(합계 0.26초). 로그는 `.local/gui-cad-windows-tests.log`, `.local/gui-cad-linux-tests.log`, `.local/cad-mesh-native-tests.log`, `.local/gui-cad-ctest.log`, `.local/gui-cad-build-tail.log`, `.local/gui-cad-build-final.log`다. 소스/실행 파일 hash와 실행 기록은 `.local/gui-cad-verification.json`, 현재 환경 요약은 `runtime_profiles/gui-cad-windows-x64.json`에 기록한다. 앞의 287개/native 8개와 2D 수치는 이전 구현의 검증 이력이다.

Windows 전체 시험에는 기존 GUI 7개와 새 CAD GUI 통합 2개가 포함된다. 새 시험은 폼 적용 뒤 snapshot 고정, 출력 중 편집/저장, 편집 오류 뒤 다른 응답 보존, 이전 개정 표시, 실제 GL paint/swap, 표시 완료 후 버튼 복구, 취소 후 이전 결과 유지, 서비스 재시작 후 복원과 미정 필수 치수의 출력 차단을 확인했다. 표시 mesh의 파일 hash/경로/하드링크/색인/상한, float 변환 뒤 붕괴, 깊이 선택과 카메라 경계는 별도 C++ 시험으로 확인했다.

시험용 선/원호 workspace의 실제 Windows 창에서 STEP 버튼으로 새 패키지를 생성하고 1512개 표시 삼각형, 위쪽 보기, 휠 확대, 마우스 회전과 body 선택의 속성 연동, 완료 경로를 확인했다. 같은 net의 병합 형상을 선택하면 대표 패턴 속성임을 알리는 안내를 추가하고 중복 조작 안내를 제거했다. 마지막 보완본에서 두 안내의 실제 표시와 정상 창 종료도 확인했다. 보존된 예제 workspace는 `.local/cad-worker-verification/line-arc-80842a72`, 실제 버튼으로 생성한 run은 `06884d0f-521c-4dd4-a605-5c1f244aafa1`이다. 현재 디스플레이에서의 기능/시각 확인이며 모든 GPU/DPI와 성능 예산의 수용을 의미하지 않는다.

60/30 fps, 전체 프로세스 메모리/최초 실행 예산, 제품 IFA/원호 해석, 정식 수렴/정확도와 실측은 아직 검증하지 않았다. 초기 AP214 환경 smoke와 이번 제한된 AP242 제품 adapter 검증을 구분한다. 같은 OCCT kernel의 별도 reader로 재입력했으므로 `kernel_independent=false`이며 결과는 `generated_unverified`다. 제조 전달 합격이나 독립 CAD 검증 완료로 확대하지 않는다.

## WSL solver 연결 검증 (2026-11-11)

`solver.plan`, `solver.prepare`, `job.submit`, `job.cancel/status`, `result.open`을 [도파관 참조 profile](solver_contract.md)로 구현했다. 준비 단계는 실제 CSXCAD XML/격자/소비 보고를 봉인하고 FDTD는 실행하지 않는다. 해석은 그 XML을 native openEMS CLI에 전달하며, raw만 사용하는 후처리 전용 작업은 solver를 다시 실행하지 않는다. GUI 해석 실행과 사용자 안테나 투영은 이 단계의 범위에 포함하지 않는다.

최종 공개 API 검증은 `.local/openems-worker-verification/service-final`과 `report-final.json`에 보존했다. 준비/해석/후처리의 영속 상태 순서, 두 격자의 해석식 대조, 원시 파일/표본을 바꾸지 않은 재후처리, 실행 중 취소와 실제 guest 종료 확인, 서비스 재시작 후 결과 조회 일치를 통과했다. 전체 검증 도구 관찰 시간은 67.953초이며 성능 예산 합격값은 아니다.

| 항목 | 목표 격자 1.0 mm | 목표 격자 0.75 mm |
| --- | --- | --- |
| 실제 native cell 수 | 18711 | 46200 |
| 실제 반복 수 | 4305 | 6003 |
| 최대 반사 진폭 | 0.003071662 | 0.002570359 |
| 최대 전달 진폭 오차 | 0.000019406 | 0.000019911 |
| 최대 임피던스 상대 오차 | 0.6161% | 0.5152% |
| 최대 군지연 상대 오차 | 0.1070% | 0.0651% |
| native 로그의 종료 에너지 감쇠 | -71.24 dB | -71.28 dB |

두 격자의 최대 임피던스 상대 차이는 0.3113%, 전달 진폭 차이는 0.000017404다. 31개 주파수의 복소 결과와 정상 종료 로그/통계/실제 입력 hash를 host에서도 대조했다. 준비/해석은 설치 감사의 native 파일과 Python 패키지, 실제 로딩 경로를 검증했고 Qt는 없었다. 공식 CalcPort와 독립 raw DFT 결과는 rel/abs 1e-9 내에서 일치했다. 독립식의 진공 임피던스 상수와 native 상수의 약 0.55 ppb 차이를 포함한 허용치다.

| 검증 | 통과 / 스킵 | 실행 시간 | 로컬 로그 |
| --- | --- | --- | --- |
| Windows 전체 회귀, GUI/CAD/실제 WSL transport 포함 | 348 / 17 (365개 수집) | 245.580초 | .local/openems-worker-windows-tests.log |
| Linux 서비스 전체 회귀 | 341 / 24 (365개 수집) | 144.747초 | .local/openems-worker-linux-tests.log |
| 최종 Linux guest 프로세스 감독 | 12 / 0 | 19.407초 | .local/openems-worker-guest-final-tests.log |
| 최종 Windows WSL transport, launcher 단절/재접속 포함 | 12 / 0 | 10.122초 | .local/openems-worker-host-final-tests.log |
| 최종 native openEMS adapter | 6 / 0 | 25.210초 | .local/openems-worker-native-final-tests.log |

전체 회귀는 당시 guest 시험 7개를 수집했다. 이후 보완한 새 process group의 정상/취소/timeout 회수, setsid 후손 취소, 소유권 확인 실패의 unknown 유지까지 5개를 추가해 최종 guest 시험 12개를 별도로 통과했다. 독립 검토에서 정상 종료 시 별도 process group 후손이 누락되는 문제를 재현했고, 모든 terminal 경로에서 nonce 소유 후손 회수를 확인하도록 수정했다. 무관한 별도 세션의 Python은 종료하지 않는 것도 실제 검사했다.

Windows 스킵은 별도 CAD 환경의 native 단위 시험 9개, Linux native openEMS 1개와 guest 7개다. Linux 스킵 24개는 Windows GUI/CAD 경로와 native CAD 환경, opt-in native openEMS 및 Windows WSL transport다. 새 native openEMS는 위 별도 환경에서 실제 실행했다. Linux 첫 전체 명령은 PYTHONPATH 누락으로 import에 실패했고 명령을 수정한 전체 재실행이 표의 결과다. 실행 실패 기록도 `.local/openems-worker-linux-invocation-error.log`에 보존했다.

검증한 코드/감독기 hash와 상세 근거는 `runtime_profiles/openems-worker-wsl.json`에 기록한다. 게스트 staging/로그/raw와 미게시 자료는 자동 삭제하지 않는다. 이번 결과는 작은 진공 PEC 도파관의 제한된 제품 경로 검증이며 IFA/NF2FF, 정식 수렴, 손실 재료/급전/제작 및 측정, 임의 코드 보안 격리, 60/30 fps와 전체 메모리 수용을 입증하지 않는다.

## 다음 구현

재부팅 직후 실행할 명령과 단계별 완료 기준은 [재부팅 후 개발 재개](reboot_resume.md)를 따른다.

1. [해석 worker 계약](solver_contract.md)의 도파관 검증을 기반으로 사용자 형상/적층/재료/급전의 solver 투영과 단일 포트 IFA 참조 검증을 진행한다. GUI 실행/취소/결과 그래프와 명시적 준비 계획 표시도 연결한다.
2. 재료/net/포트 생성 UI, 실제 급전/접속 검증과 독립 수신 CAD 재열기 증거를 추가한다. 필요한 pad/via/hole/polygon을 명시적 의미 모델과 함께 확장한다.
3. 3D LOD와 실제 GPU reset/DPI/도킹 복구 검증, 마우스 스냅/치수 도구/endpoint 드래그를 확장한다. 결과 작업 공간은 solver adapter와 함께 진행한다.
4. 승인 순서대로 완전한 참조 계산, 단일 포트 IFA, 원호의 openEMS 모델과 NF2FF 결과를 검증한다.
5. 사용자 보드 입력, 실제 재료/제작/측정 조건과 성능 예산을 검증하고 내부 검증 패키지로 묶는다.

GUI와 자동화는 같은 서비스를 공유한다. MCP 서버 자체와 다른 EDA의 의미 mapping은 후속이다. solver 실행은 도파관 참조 profile로 제한하여 연결했다. 물성은 사용자 입력이며 임의 FR4 대표값으로 대체하지 않는다. 초기 IFA 1 mm 완성 두께에서 구리 두께를 뺀 잔여값을 실제 코어 두께 확정값으로 취급하지 않는다.
