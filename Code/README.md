# TraceWave Studio 개발 영역

Code는 개발 코드 영역이다. 제품 소스, 빌드 설정, 시험, fixtures와 실행/검증 도구를 이 아래에서 관리하며 상세 경로와 이름 규칙, 승인 원문과 과거 실행 보존은 [문서 관리 규칙](../01_개발문서/02_문서관리와_변경규칙.md)을 따른다.

## 시스템 구성

| 구성 | 책임 / 코드 |
| --- | --- |
| wxWidgets + wxAUI | native 입력/트리/표/메뉴와 도킹, View + 표시 상태 + service 연결. `ui/wxwidgets/` |
| 사용자 정의 DesignCanvas | wxGraphicsContext 기반 2D 표시/편집. 원본 계산/명령은 서비스 소유 |
| wxGLCanvas/OpenGL ModelView | OCCT의 표시 mesh를 읽는 3D 보기. CAD B-rep나 일반 3D 안테나 RF 원본이 아님 |
| Python application service | 원본/단위/표현식/명령/undo/저장/snapshot/작업. `src/rfad/domain/`, `application/`, `storage/` |
| 별도 OCCT worker | 정확 형상, STEP/B-rep, 표시 mesh. `adapters/cad/`, `tools/cad_worker.py` |
| 별도 출력 worker | 같은 snapshot의 PDF/SVG/DXF 및 PCB/CAM 출력, 파일 재입력과 봉인 원문 parser. `adapters/exchange/`, `tools/exchange_worker.py` |
| 별도 WSL2 openEMS worker | 해석 계획/준비/실행/취소/결과와 후처리. `adapters/solvers/openems/`, `tools/openems_worker.py` |

Windows 11이 주 개발 환경이다. 한글 IME, 스크린리더 오류 안내와 혼합 DPI 창 이동을 실제 Windows에서 확인했다. Linux GUI와 비평면 3차원 안테나 해석은 후속 범위다. [Windows 사용성 검수](../01_개발문서/07_검증/309_윈도우_한글입력과_접근성_검수.md)

## 현재 기능과 범위

| 분야 | 현재 연결한 기능 / 계약 |
| --- | --- |
| 프로젝트/편집 | core 0.6 쓰기/0.1~0.6 읽기, 명령/undo/redo/저장/불변 snapshot, 표현식과 기본 도형. [프로젝트](../01_개발문서/05_기능설계/01_프로젝트/01_프로젝트_명령과_저장.md), [2D](../01_개발문서/05_기능설계/02_설계편집/03_이차원표시와_직접편집.md) |
| 목표/후보 | 다중 목표, 원호/IFA 명시 치수, G031/G001/G008/G009 부분 기하 및 조건부 초기 길이. [설계 기능](../01_개발문서/05_기능설계/02_설계편집/README.md) |
| 제약/연결/환경 | 기본 제약/기대 연결/DRC, 적층/표면층/개구, 기본 외부 STEP 배치. [규칙](../01_개발문서/05_기능설계/02_설계편집/11_목표제약과_연결_설계규칙검사.md), [환경](../01_개발문서/05_기능설계/02_설계편집/12_적층과_외부환경.md) |
| 재료/출처 | 제조사 자료 조회, 명시 채택/근사/사용자 수정, 미정과 출처 사본 보존. [재료 기능](../01_개발문서/05_기능설계/03_재료/README.md) |
| CAD/해석 | 별도 worker에서 STEP 조립과 PCB 단일 급전 및 2~8포트 해석을 실행한다. 국부 격자 반복, 복소 결과, 단일 급전 E/H와 방사 기록을 조회한다. [해석](../01_개발문서/05_기능설계/04_해석결과/README.md), [CAD](../01_개발문서/05_기능설계/05_출력교환/02_기계형상_입력과_출력계약.md) |
| 복소 결과/회로 | 1~8포트 S/Z/Y 자료, 원문과 정규 HDF5, 명시 변환/실수 Z0 재정규화, 1포트 외부 이상 RLC, 정확 표본 목표 평가. [복소 자료 계약](../01_개발문서/05_기능설계/04_해석결과/06_공통복소자료와_회로평가.md), [파일 교환](../01_개발문서/05_기능설계/05_출력교환/03_복소결과_파일교환.md) |
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

모든 명령의 작업 디렉터리는 Code다. Python 환경 준비는 [Windows 환경](../01_개발문서/08_운영환경/01_파이썬_개발환경.md), WSL은 [전용 환경](../01_개발문서/08_운영환경/02_리눅스하위시스템_개발환경.md), 빌드는 [wxWidgets 안내](ui/wxwidgets/README.md)를 따른다.

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -X utf8 -m rfad doctor --output .local/runtime-doctor.json
.venv/Scripts/python.exe -X utf8 -m rfad serve --workspace .local/projects-workspace
.\tools\launch_gui.ps1
```

새 후보는 기능 개발을 완료한 소스 개정으로 만든다. 그 후보와 고정 의존성을 온라인 상태의 별도 클린 Windows/WSL2 PC에서 받아 예제를 검수한다. [배포 절차](../01_개발문서/08_운영환경/05_윈도우_내부검증_배포.md), [이전 공개 후보 수신 기록](../01_개발문서/07_검증/310_공개_검증후보_배포와_독립수신_인계.md)

GUI 실행 스크립트는 존재하는 `.venv-cad`, `.venv-exchange`와 `.local/pcb-catalog/catalog.sqlite`를 연결한다. `-CadPython <경로>`, `-ExchangePython <경로>`, `-Catalog <경로>`, `-NoCatalog`로 선택할 수 있다. 해석 환경 구성 후에는 `launch_gui.ps1 -OpenEmsWsl`을 사용한다. CAD/출력/solver가 없어도 가능한 편집/저장과 보존 결과 읽기는 유지한다.

연관 도면의 별도 환경은 `tools/setup_exchange.ps1 -Python .venv/Scripts/python.exe`로 준비한다. 서비스 직접 실행에는 `--exchange-python .venv-exchange/Scripts/python.exe`를 전달한다. [고정 wheel 목록](runtime_profiles/python-exchange-windows-x64.txt)과 runtime manifest의 글꼴 identity를 확인하며 한글 PDF 글꼴은 Windows의 기존 TTF를 부분 포함한다. 원래 OS 글꼴을 저장소에 복사하지 않는다. 기하/파일 검수와 제조/실측 수용은 별개다.

복소 계산과 HDF5 교환은 Windows x64 CPython 3.12용 [고정 wheel 목록](runtime_profiles/python-network-windows-x64.txt)을 사용한다. `pip install --only-binary=:all: --require-hashes -r runtime_profiles/python-network-windows-x64.txt` 후 `pip check`로 확인한다. 수치 엔진이 없어도 기존 정규 JSON 조회, 프로젝트 저장/재열기 및 이력 복원은 가능하다. 실제 계산과 HDF5 입출력 때만 선택 의존성을 읽는다.

STEP 출력은 필요한 기하 입력과 미적용 폼을 확인한 뒤 snapshot을 고정한다. 기본 모델에는 양수 두께/명시 z/필요 좌표가 있어야 한다. STEP 조립은 혼합 단위, 말단 배치, 평면 및 동축 메이트와 부품 교체를 다루며, 지원하는 표면층, 간이 유전체 케이스와 PEC 상자는 명시 조건에서 해석하며 외부 STEP 고체는 CAD 배치·표시·출력 범위에서 사용한다. [환경 계약](../01_개발문서/05_기능설계/02_설계편집/12_적층과_외부환경.md)의 저장/CAD/EM 구분을 따른다.

GUI의 파일 저장과 별도 CLI writer를 동시에 같은 workspace에 사용하지 않는다. 서비스는 stdout에 UTF-8 JSON-RPC/NDJSON 응답만 기록한다. workspace 없는 bootstrap과 프로젝트를 연 서비스의 capability는 다르다. [bootstrap](../01_개발문서/02_시스템명세/07_초기구현_계약.md), [서비스/worker 경계](../01_개발문서/03_아키텍처/05_형상과_해석작업_연결경계.md).

### 기능별 예제

| Code에서 실행할 명령 | 지원 범위와 근거 |
| --- | --- |
| `python -m rfad floquet fixtures/floquet_dielectric_grating.json` | 일차원 유전체 격자의 TE/TM 회절. [403 검증](../01_개발문서/07_검증/403_유전체_격자의_주기_플로케_경계_검증.md) |
| `python -m rfad pcb-floquet fixtures/pcb_floquet_patch.json` | XY 주기 동박 적층의 비스듬한 입사, TE/TM 회절과 재료별 체적 흡수. [408 검증과 저장 PCB 진입점](../01_개발문서/07_검증/408_동박_피시비의_이중주기_플로케_검증.md) |
| `python -m rfad waveguide-modes fixtures/waveguide_te_step.json` | 같은 높이의 직사각 도파관 폭 단차에서 TE(m,0) 모드 변환. [404 검증](../01_개발문서/07_검증/404_직사각_도파관_폭단차의_다중모드_검증.md) |
| `python -m rfad waveguide-section 단면.json` | 공통 삼각 단면의 TE/TM 고유모드와 두 도파관 단차의 복소 산란. [409 검증과 예제 생성](../01_개발문서/07_검증/409_일반_도파관_단면의_티이_티엠_결합_검증.md) |
| `python -m rfad manufacturing-panel --help` | 단일 보드의 ODB++ 반복 배열 생성 옵션. [407 패드스택과 패널](../01_개발문서/07_검증/407_층별_패드스택과_오디비_반복패널_검증.md) |

## 시험과 기록

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
ctest --preset windows-release
.venv/Scripts/python.exe -X utf8 tools/build_implementation_audit.py --check
.venv/Scripts/python.exe -X utf8 tools/documentation/check_documents.py
```

실제 GUI 시험은 `RFAD_GUI_EXE`, OCCT 시험은 `RFAD_CAD_PYTHON`, WSL 계산은 시험별 실행 조건을 사용한다. 통과와 조건부 제외 건수는 [검증 안내](../01_개발문서/07_검증/README.md)에서 확인한다. [새 채팅 인계](../01_개발문서/09_개발계획/08_새채팅_개발인계.md)에는 새 PC에서 첫 수치 예제를 실행하는 절차가 있다.

문서 변경 시 계약/화면/현재 상태/요구 연결을 함께 갱신한다. 기능별로 한국어 Doxygen, C++ Allman/4칸/중괄호 필수 규칙을 적용하고 주 창에 계산/영구 명령 로직을 몰지 않는다.
