# TraceWave Studio 개발 영역

Code는 개발 코드 영역이다. 제품 소스, 빌드 설정, 시험, fixtures와 실행/검증 도구를 이 아래에서 관리하며 상세 경로와 이름 규칙, 승인 원문과 과거 실행 보존은 [문서 관리 규칙](../01_개발문서/02_문서관리와_변경규칙.md)을 따른다.

## 시스템 구성

| 구성 | 담당 기능과 코드 위치 |
| --- | --- |
| wxWidgets + wxAUI | native 입력/트리/표/메뉴와 도킹, View + 표시 상태 + service 연결. `ui/wxwidgets/` |
| 사용자 정의 DesignCanvas | wxGraphicsContext 기반 2D 표시/편집. 원본 계산/명령은 서비스 소유 |
| wxGLCanvas/OpenGL ModelView | OCCT의 표시 mesh를 읽는 3D 보기. CAD B-rep나 일반 3D 안테나 RF 원본이 아님 |
| Python application service | 원본/단위/표현식/명령/undo/저장/snapshot/작업. `src/rfad/domain/`, `application/`, `storage/` |
| 별도 OCCT worker | 정확 형상, STEP/B-rep, 표시 mesh. `adapters/cad/`, `tools/cad_worker.py` |
| 별도 출력 worker | 같은 snapshot의 PDF/SVG/DXF 및 PCB/CAM 출력, 파일 재입력과 봉인 원문 parser. `adapters/exchange/`, `tools/exchange_worker.py` |
| 별도 openEMS worker | Windows 기본 해석의 계획, 준비, 실행, 취소 및 후처리. 기존 WSL2 환경은 명시적으로 선택한다. `adapters/solvers/openems/`, `tools/openems_worker.py` |

Windows 11이 주 개발 환경이다. 한글 IME, 스크린리더 오류 안내와 혼합 DPI 창 이동을 실제 Windows에서 확인했다. Linux GUI와 비평면 3차원 안테나 해석은 후속 범위다. [Windows 사용성 검수](../01_개발문서/07_검증/309_윈도우_한글입력과_접근성_검수.md)

## 현재 기능과 범위

| 분야 | 구현 범위와 계약 |
| --- | --- |
| 프로젝트/편집 | core 0.6 쓰기/0.1~0.6 읽기, 명령/undo/redo/저장/불변 snapshot, 표현식과 기본 도형. [프로젝트](../01_개발문서/05_기능설계/01_프로젝트/01_프로젝트_명령과_저장.md), [2D](../01_개발문서/05_기능설계/02_설계편집/03_이차원표시와_직접편집.md) |
| 목표/후보 | 다중 목표, 원호/IFA 명시 치수, G031/G001/G008/G009 부분 기하 및 조건부 초기 길이. [설계 기능](../01_개발문서/05_기능설계/02_설계편집/README.md) |
| 제약/연결/환경 | 기본 제약/기대 연결/DRC, 적층/표면층/개구, 기본 외부 STEP 배치. [규칙](../01_개발문서/05_기능설계/02_설계편집/11_목표제약과_연결_설계규칙검사.md), [환경](../01_개발문서/05_기능설계/02_설계편집/12_적층과_외부환경.md) |
| 재료/출처 | 제조사 자료 조회, 명시 채택/근사/사용자 수정, 미정과 출처 사본 보존. [재료 기능](../01_개발문서/05_기능설계/03_재료/README.md) |
| CAD/해석 | 별도 worker에서 STEP 조립과 PCB 단일 급전 및 다중 급전 해석을 실행한다. 설계와 교환은 최대 12포트, Windows 실해석과 원시 재처리 대조는 9포트까지 확인했다. 국부 격자 반복, 복소 결과, 단일 급전 E/H와 방사 기록을 조회한다. [해석](../01_개발문서/05_기능설계/04_해석결과/README.md), [CAD](../01_개발문서/05_기능설계/05_출력교환/02_기계형상_입력과_출력계약.md) |
| 복소 결과/회로 | 1~12포트 S/Z/Y 자료, 원문과 정규 HDF5, 명시 변환/실수 Z0 재정규화, 1포트 외부 이상 RLC, 정확 표본 목표 평가. [복소 자료 계약](../01_개발문서/05_기능설계/04_해석결과/06_공통복소자료와_회로평가.md), [파일 교환](../01_개발문서/05_기능설계/05_출력교환/03_복소결과_파일교환.md) |
| 제조사 안테나 | Renesas AN-B-027 DXF 5종, TI 공식 SPL 2종과 Qorvo WB003을 원본 바이트·출처와 함께 편집 동박으로 가져온다. [라이브러리 계약](../01_개발문서/05_기능설계/05_출력교환/07_제조사_안테나_라이브러리.md) |
| 공통 결과 화면 | 현재/과거 개정과 solver/스윕 원본 고정, 최대 8개 곡선 비교, Smith, 전력/효율, OpenGL 3D 방사/2D cut/편파, 기록 E/J/rotH 단면, 기록 E/H 체적과 삼각 곡면 전력 적분, 당시 조건과 내보내기. [유한 조회 계약](../01_개발문서/05_기능설계/04_해석결과/07_다중결과와_방사표시.md), [화면 계약](../01_개발문서/04_화면설계/21_다중결과와_방사필드_화면.md) |
| 검증/연구 | IFA/방사/전력/개별 손실 연구와 원시 결과 재열기. [연구 기록](../01_개발문서/06_분석연구/README.md) |
| 독립 참조 | 사전 고정한 PEC 다이폴 3수준, 독립 패턴/지향성 비교, 유한 예산과 불변 판정 기록. [계약](../01_개발문서/05_기능설계/04_해석결과/08_독립참조와_유한검증_계약.md), [실행 근거](../01_개발문서/07_검증/19_독립참조와_유한검증.md). 평면 도체/유한 급전 native 6사례는 미확정 조건으로 차단 |
| 설계 스윕 | 리터럴 매개변수/명시 수치 설정/외부 회로의 유한 다축 후보, 목표 기반 원호/IFA 구조와 초기 치수, 이전 결과로 후속 후보를 고르는 반복 탐색, 예산과 실패 원인의 보존. [연구 계약](../01_개발문서/05_기능설계/06_연구/01_명시적스윕과_실행계약.md), [Windows/WSL 검증](../01_개발문서/07_검증/13_설계스윕과_연구_검증.md) |
| 후보 채택 | 완료된 grid_sweep의 리터럴 매개변수 후보를 별도 프로젝트로 채택. 선택 순번의 Quantity/출처와 실제 계산 pin을 구분하며 원본 개정/저장/undo를 보존. [새 사본 계약](../01_개발문서/05_기능설계/06_연구/02_후보채택과_새작업사본.md), [화면과 복구](../01_개발문서/04_화면설계/23_후보채택과_새사본_화면.md) |
| 도면/재검수 | 고정 snapshot의 연관 PDF/SVG/DXF, 검토 hash와 실제 종이 미리보기, 별도 출력 worker. 기존 STEP의 새 reader 검수는 원래 파일을 보존하고 동일 OCCT 범위를 표시. [출력 계약](../01_개발문서/05_기능설계/05_출력교환/04_연관도면과_출력재검수.md), [화면 계약](../01_개발문서/04_화면설계/24_기술도면과_스텝검수_화면.md) |
| PCB 형상/교환 | 기계 홀·슬롯/내부 절삭/풋프린트/마스크·페이스트 개구/금지 영역, 고정 snapshot의 유한 KiCad/Gerber X2/XNC/Job 출력과 별도 재검수. 원문 수입은 청크 전송/명시 층·net 대응/손실 확인/한 명령 적용을 분리. [기능 계약](../01_개발문서/05_기능설계/05_출력교환/05_기판형상과_제조파일_교환.md), [화면과 복구](../01_개발문서/04_화면설계/25_기판교환과_원문수입_화면.md) |

스냅/끝점, 공통 작업 공간, 객체 이름과 검색, 연관 치수/회전/미러/제한된 다각형 평면 연산을 서비스와 GUI에 연결했다. [정밀 편집 계약](../01_개발문서/05_기능설계/02_설계편집/13_정밀편집과_평면연산.md)과 [단계 검증](../01_개발문서/07_검증/08_스튜디오와_정밀편집_검증.md)을 따른다. 평면 연산에는 명시적으로 고정한 Shapely/GEOS 환경이 필요하며, 없으면 해당 작업만 차단한다. 기존 프로젝트 열기/저장과 봉인된 이력의 undo/redo는 이 엔진을 요구하지 않는다. 7번의 공통 결과와 10번의 PCB/CAM 화면은 각 유한 profile로 연결했다. 기계 형상 전용 폼, 출력의 KiCad/Gerber/드릴/Job 탭, 수입의 파일/대응/후보·손실/원문 탭은 공통 Studio와 요청 수명/복구를 재사용한다. 고정 개정의 STEP은 독립 CADability로, 대응하는 도면과 CAM은 실제 KiCad와 보존된 Altium 재출력으로 대조했다. 교환 경로가 바뀌면 영향을 받은 형식을 다시 확인한다. [동일 개정 교환](../01_개발문서/07_검증/276_동일개정_교환수신_재검증.md), [슬롯과 누락 속성](../01_개발문서/07_검증/296_엔씨_슬롯과_원본_대응_검증.md)

결과 조회는 원본 source/pin을 고정하고 정확히 같은 주파수에서만 비교한다. 과거 목표 판정과 실제 수치 종료 기록을 독립 수렴/물리 수용과 구분한다. 외부 회로나 변환 자료에 원래 안테나의 방사/효율을 자동 승계하지 않으며 기록되지 않은 필드를 생성하지 않는다. 오른쪽 조건은 원본/기준/검증 상태 그룹과 접힌 원문으로 나누고 비교 조건은 최대 32개씩 조회한다. 큰 복소 표본은 201개 페이지, 필드는 최대 4096점의 명시 ROI/stride를 사용한다.

납품 물성, 제작, 실장, 시료, 교정과 측정 조건은 미정으로 보존한다. 외부 실측 자료가 있으면 해당 프로젝트에서 비교한다. 손실 비교의 기준과 적용 범위는 [RF 연구 안내](../01_개발문서/06_분석연구/README.md)를 따른다.

## 실행

앱 설치는 [Windows Setup.exe 안내](../01_개발문서/08_운영환경/05_윈도우_내부검증_배포.md)를 따른다. 아래 명령은 소스에서 개발할 때 저장소의 `Code` 폴더에서 실행한다. Windows 11 x64, CPython 3.12 x64와 PATH에서 찾을 수 있는 CMake, Ninja, MinGW-w64 GCC 및 tar가 필요하다. 검증한 도구 버전과 원본 해시는 [네이티브 빌드 프로필](runtime_profiles/native-windows-x64.json)에 있다.

### 편집기 빌드와 첫 실행

```powershell
$serviceBase = py -3.12 -c 'import sys; print(sys.executable)'
.\tools\setup_python.ps1 -Python $serviceBase -SkipCad
.\tools\setup_native.ps1 -Jobs 4
ctest --preset windows-release
.\tools\launch_gui.ps1 -Workspace .local/gui-workspace
```

빌드 결과는 `build/windows-release/bin/tracewave_gui.exe`다. 창에서 **파일 > 새 프로젝트**를 선택하고 이름을 정한 다음 속성을 편집하고 저장한다. 창을 닫고 같은 실행 명령으로 작업 영역을 다시 열어 저장값을 확인한다. 서비스는 GUI가 시작한다. JSON-RPC 클라이언트를 개발할 때는 별도 작업 영역에서 아래 명령을 사용한다. `serve`는 표준 입력의 요청을 기다리며 표준 출력에 한 줄씩 응답한다. [GUI 실행 옵션](ui/wxwidgets/README.md#실행), [서비스 진입점](src/rfad/__main__.py)

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 -m rfad doctor --output .local/runtime-doctor.json
.\.venv\Scripts\python.exe -X utf8 -m rfad serve --workspace .local/service-workspace
```

### 기능별 개발 환경

| 필요한 기능 | Code에서 준비할 항목 |
| --- | --- |
| STEP 생성 및 3D 메시 | `.\tools\setup_python.ps1 -Python $serviceBase`를 실행한다. 서비스와 별도로 `.venv-cad`에 CAD를 구성하고 STEP 시험을 수행한다. [Python 및 CAD 환경](../01_개발문서/08_운영환경/01_파이썬_개발환경.md) |
| PDF, 도면, CAM 출력 | `.\tools\setup_exchange.ps1 -Python $serviceBase`로 `.venv-exchange`를 구성한다. [출력 패키지 목록](runtime_profiles/python-exchange-windows-x64.txt) |
| 복소 연산, HDF5, 수치 예제 | `.\.venv\Scripts\python.exe -m pip install --only-binary=:all: --require-hashes -r runtime_profiles/python-network-windows-x64.txt` 실행 후 같은 Python으로 `-m pip check`를 수행한다. [네트워크 패키지 목록](runtime_profiles/python-network-windows-x64.txt) |
| 정밀 평면 연산 | 서비스 Python에 같은 pip 옵션으로 [평면 연산 패키지 목록](runtime_profiles/python-planar-windows-x64.txt)을 설치한다. |
| Windows 기본 PCB 해석 | `.\.venv\Scripts\python.exe -X utf8 tools/setup_openems_windows.py --cache .local/download-cache`를 실행한다. 별도 CPython과 openEMS를 설치하고 실제 로드된 DLL을 감사한다. 이후 GUI를 다시 열면 서비스가 Windows 환경을 찾는다. [고정 해석기 구성](runtime_profiles/python-openems-windows-x64.json) |
| 기존 WSL2 결과의 실행 환경 재현 | 전용 배포판 및 native 감사가 준비되면 `.\tools\launch_gui.ps1 -OpenEmsWsl`로 선택한다. [WSL2 설정](../01_개발문서/08_운영환경/02_리눅스하위시스템_개발환경.md) |
| 제조사 기판 검색 | 원본 자료로 SQLite를 만들면 GUI가 `.local/pcb-catalog/catalog.sqlite`에 읽기 전용으로 연결한다. [카탈로그 생성과 검증](../01_개발문서/05_기능설계/03_재료/01_기판카탈로그_조회계약.md) |

GUI는 준비된 CAD 및 출력 환경을 자동으로 찾는다. 다른 위치는 `-Python`, `-CadPython`, `-ExchangePython`, `-Catalog`로 선택한다. `-NoCatalog`는 로컬 카탈로그 연결을 생략한다. 해당 작업자가 없어도 편집과 저장, 보존된 결과 조회를 할 수 있다. [실행 스크립트](tools/launch_gui.ps1)

### 기능별 예제

아래 표의 `python`에는 위에서 구성한 서비스 Python을 사용한다. PowerShell에서는 `python`을 `.\.venv\Scripts\python.exe`로 바꿔 같은 환경에서 실행할 수 있다.

| Code에서 실행할 명령 | 지원 범위와 근거 |
| --- | --- |
| `python -m rfad floquet fixtures/floquet_dielectric_grating.json` | 일차원 유전체 격자의 TE/TM 회절. [403 검증](../01_개발문서/07_검증/403_유전체_격자의_주기_플로케_경계_검증.md) |
| `python -m rfad pcb-floquet fixtures/pcb_floquet_patch.json` | XY 주기 동박 적층의 비스듬한 입사, TE/TM 회절과 재료별 체적 흡수. [408 검증과 저장 PCB 진입점](../01_개발문서/07_검증/408_동박_피시비의_이중주기_플로케_검증.md) |
| `python -m rfad waveguide-modes fixtures/waveguide_te_step.json` | 같은 높이의 직사각 도파관 폭 단차에서 TE(m,0) 모드 변환. [404 검증](../01_개발문서/07_검증/404_직사각_도파관_폭단차의_다중모드_검증.md) |
| `python -m rfad waveguide-section 단면.json` | 공통 삼각 단면의 TE/TM 고유모드와 두 도파관 단차의 복소 산란. [409 검증과 예제 생성](../01_개발문서/07_검증/409_일반_도파관_단면의_티이_티엠_결합_검증.md) |
| `python -m rfad waveguide-mode-files --help` | 단면 모드를 openEMS 공간 분포 여기 및 프로브의 HDF5 두 파일로 출력. [410 검증](../01_개발문서/07_검증/410_아홉_급전과_분포_모드_원문_검증.md) |
| `python -m rfad pcb-waveguide --help` | 저장한 직사각 PCB 양쪽의 단일 분포 TE/TM 포트 해석. [413 독립 대조](../01_개발문서/07_검증/413_저장_피시비의_분포_모드_포트_검증.md) |
| `python -m rfad manufacturing-panel --help` | 단일 보드의 ODB++ 및 IPC-2581C 반복 배열. [412 IPC 패널](../01_개발문서/07_검증/412_아이피시_특수_드릴과_반복패널_검증.md) [407 패드스택과 패널](../01_개발문서/07_검증/407_층별_패드스택과_오디비_반복패널_검증.md) |

보존 묶음, 다중 급전, 필드 연구와 후속 스윕, Altium 드릴 사본에 사용하는 명령은 각각 `archive`, `pcb-multiport`, `field-study`, `sweep-refine`, `altium-drill-copy`다. 전체 목록은 `python -m rfad --help`에서 확인한다. 위 수치 및 파일 명령에는 각각 `--help`를 붙여 입력과 출력을 확인한다. `doctor`, `serve`, `catalog`의 도움말은 최상위 목록을 표시하므로 환경 진단과 서비스는 위 예제, 카탈로그는 [카탈로그 명령 안내](../01_개발문서/05_기능설계/03_재료/01_기판카탈로그_조회계약.md)를 따른다. [CLI 구현](src/rfad/__main__.py)

## 시험과 기록

전체 서비스 시험은 위에서 만든 `.venv`의 Python으로 실행한다. 결과 출처와 프로젝트 보존 묶음 시험은 Touchstone을 가져와 정규 HDF5 파일을 실제로 저장한다. 첫 실행에는 서비스 Python에 [네트워크 패키지 목록](runtime_profiles/python-network-windows-x64.txt)을 설치한다. 실행 예제에서 만든 별도 `.local/rf-check`에만 설치한 패키지는 이 환경에서 사용할 수 없다.

```powershell
.venv/Scripts/python.exe -m pip install --only-binary=:all: --require-hashes -r runtime_profiles/python-network-windows-x64.txt
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
ctest --preset windows-release
.venv/Scripts/python.exe -X utf8 tools/build_implementation_audit.py --check
.venv/Scripts/python.exe -X utf8 tools/documentation/check_documents.py
```

실제 GUI 시험은 `RFAD_GUI_EXE`, OCCT 시험은 `RFAD_CAD_PYTHON`, WSL 계산은 시험별 실행 조건을 사용한다. 통과와 조건부 제외 건수는 [검증 안내](../01_개발문서/07_검증/README.md)에서 확인한다. [새 채팅 인계](../01_개발문서/09_개발계획/08_새채팅_개발인계.md)에는 새 PC에서 첫 수치 예제를 실행하는 절차가 있다.

문서 변경 시 계약/화면/현재 상태/요구 연결을 함께 갱신한다. 기능별로 한국어 Doxygen, C++ Allman/4칸/중괄호 필수 규칙을 적용하고 주 창에 계산/영구 명령 로직을 몰지 않는다.
