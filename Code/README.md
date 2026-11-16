# TraceWave Studio 개발 영역

Code는 개발 코드 영역이다. 제품 소스, 빌드 설정, 시험, fixtures와 실행/검증 도구를 이 아래에서 관리하며 상세 개발 문서는 모두 `../01_개발문서`에 둔다. 승인 기준선은 RFAD-D0-3.4, 승인 커밋은 `6ebeda156e9d31b893bf69046550f5df9b16dc64`다. Windows 11 + WSL2를 우선하는 R1 내부 검증용 제품을 개발하며 전체 R1 수용은 아직 완료하지 않았다.

## 문서에서 시작하기

- [분야별 문서 안내](../01_개발문서/README.md): 화면 설계, 기능, 명세, 구조, 분석, 검증, 운영과 계획.
- [Studio 화면설계서](../01_개발문서/04_화면설계/README.md): 화면마다 기능/입출력/버튼 이벤트/전환/예외, DrawIO/PNG/SVG, 객체 이름/선택과 접근성.
- [현재 계획](../01_개발문서/09_개발계획/03_개발완료_계획.md)과 [개발 상태](../01_개발문서/09_개발계획/02_개발착수와_현재상태.md): 기존 1~13번 순서와 날짜별 실제 증거.
- [공통 계약](../01_개발문서/02_시스템명세/08_공통구현_계약.md), [코드 구조](../01_개발문서/03_아키텍처/03_코드구조와_유지보수.md), [구현 감사](../01_개발문서/07_검증/06_승인요구와_구현대조.md).
- [이번 문서 검토](../01_개발문서/11_검토기록/README.md): 현재형 정정, 원문 보존, 남은 설계/증거 의존성과 전수 분류.

개발 문서는 모두 `../01_개발문서`에 있으며 폴더와 파일을 `숫자번호_한글명`으로 관리한다. Code의 소스/빌드/시험/fixture/도구 파일은 이 문서 명명 규칙의 대상이 아니다. 이 파일과 하위 `README.md`는 개발 코드의 빌드/실행 진입 안내 예외이고 상세 설계는 문서 영역으로 연결한다.

`../00_참고자료`는 레퍼런스 저장소이며 내부 폴더명/파일명/내용을 변경하지 않는다. 기존 설계의 현재 편집본과 01_개발문서/12_보관이력/01_승인기준선의 승인 당시 원문을 구분한다. 개발 문서의 기존 RFAD 문서/그림/기계 판독 JSON과 승인 보관본도 각 폴더에서 01부터 새 번호와 한글 파일명을 사용한다. 승인 보관본은 파일명만 바꾸고 본문/해시/manifest 기록은 유지하며 이전 경로 대응표로 찾는다. 문서 내부의 안정 ID는 보존한다. 과거 `runtime_profiles`는 당시 실행 증거의 보존 예외로 현재 위치를 유지하며, 이전 경로/소스 해시/수치를 현재 구현에 맞춰 소급 수정하지 않는다.

## 시스템 구성

| 구성 | 책임 / 코드 |
| --- | --- |
| wxWidgets + wxAUI | native 입력/트리/표/메뉴와 도킹, View + 표시 상태 + service 연결. `ui/wxwidgets/` |
| 사용자 정의 DesignCanvas | wxGraphicsContext 기반 2D 표시/편집. 원본 계산/명령은 서비스 소유 |
| wxGLCanvas/OpenGL ModelView | OCCT의 표시 mesh를 읽는 3D 보기. CAD B-rep나 일반 3D 안테나 RF 원본이 아님 |
| Python application service | 원본/단위/표현식/명령/undo/저장/snapshot/작업. `src/rfad/domain/`, `application/`, `storage/` |
| 별도 OCCT worker | 정확 형상, STEP/B-rep, 표시 mesh. `adapters/cad/`, `tools/cad_worker.py` |
| 별도 WSL2 openEMS worker | 해석 계획/준비/실행/취소/결과와 후처리. `adapters/solvers/openems/`, `tools/openems_worker.py` |

Qt와 필수 유료 GUI 부품을 사용하지 않는다. Linux GUI는 별도 후속이다. 일반 60 fps/대형 30 fps와 메모리 예산은 초기 목표이며 전체 앱 실측 합격이 아니다. 현재 CAD 보기와 장기 비평면 3차원 안테나 해석을 구분한다.

## 현재 기능과 범위

| 분야 | 현재 연결한 기능 / 계약 |
| --- | --- |
| 프로젝트/편집 | core 0.4 쓰기/0.1~0.4 읽기, 명령/undo/redo/저장/불변 snapshot, 표현식과 기본 도형. [프로젝트](../01_개발문서/05_기능설계/01_프로젝트/01_프로젝트_명령과_저장.md), [2D](../01_개발문서/05_기능설계/02_설계편집/03_이차원표시와_직접편집.md) |
| 목표/후보 | 다중 목표, 원호/IFA 명시 치수, G031/G001/G008/G009 부분 기하 및 조건부 초기 길이. [설계 기능](../01_개발문서/05_기능설계/02_설계편집/README.md) |
| 제약/연결/환경 | 기본 제약/기대 연결/DRC, 적층/표면층/개구, 기본 외부 STEP 배치. [규칙](../01_개발문서/05_기능설계/02_설계편집/11_목표제약과_연결_설계규칙검사.md), [환경](../01_개발문서/05_기능설계/02_설계편집/12_적층과_외부환경.md) |
| 재료/출처 | 제조사 자료 조회, 명시 채택/근사/사용자 수정, 미정과 출처 사본 보존. [재료 기능](../01_개발문서/05_기능설계/03_재료/README.md) |
| CAD/해석 | 별도 worker의 STEP/3D, 제한된 단일 포트 PCB 해석/결과/방사 조회, 한 축 프로젝트 수치 연구. [해석](../01_개발문서/05_기능설계/04_해석결과/README.md), [CAD](../01_개발문서/05_기능설계/05_출력교환/02_기계형상_입력과_출력계약.md) |
| 검증/연구 | IFA/방사/전력/개별 손실 연구와 원시 결과 재열기. [연구 기록](../01_개발문서/06_분석연구/README.md) |

스냅/끝점 편집은 이전 미커밋 작업 트리에 보존되어 있다. 이번 문서 정비는 그 최종 검증/커밋을 대신하지 않는다. 전체 Studio 흐름/정밀 편집/객체 이름 통일, 공통 복소 결과/회로/측정 파일, 다축 스윕/다중 비교/3D 방사, 도면/CAM 및 전체 UX 수용은 해당 계획의 남은 범위다.

실제 납품 물성/제작/급전 실장/시료/교정/측정 조건은 자료 확보 전까지 미정이다. 문헌 부분 기하, 초기 추정, 해석 완료, 수렴, 물리/제조/실측 검증을 별도로 표시한다. RO4350B 국부 방사 도체 손실 변화 2.788446%로 초기 2% 기준 미확립 및 GHz PTH 독립 정확도 미확립을 유지한다.

## 실행

모든 명령의 작업 디렉터리는 Code다. Python 환경 준비는 [Windows 환경](../01_개발문서/08_운영환경/01_파이썬_개발환경.md), WSL은 [전용 환경](../01_개발문서/08_운영환경/02_리눅스하위시스템_개발환경.md), 빌드는 [wxWidgets 안내](ui/wxwidgets/README.md)를 따른다.

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -X utf8 -m rfad doctor --output .local/runtime-doctor.json
.venv/Scripts/python.exe -X utf8 -m rfad serve --workspace .local/projects-workspace
.\tools\launch_gui.ps1
```

GUI 실행 스크립트는 존재하는 `.venv-cad`와 `.local/pcb-catalog/catalog.sqlite`를 연결한다. `-CadPython <경로>`, `-Catalog <경로>`, `-NoCatalog`로 선택할 수 있다. 해석 환경 구성 후에는 `launch_gui.ps1 -OpenEmsWsl`을 사용한다. CAD/solver가 없어도 가능한 편집/저장과 보존 결과 읽기는 유지한다.

STEP 출력은 필요한 기하 입력과 미적용 폼을 확인한 뒤 snapshot을 고정한다. 기본 모델에는 양수 두께/명시 z/필요 좌표가 있어야 한다. 외부 STEP은 현재 단일 mm 고체 등 명시된 제한이 있으며, 표면층/외부 환경의 EM 포함은 기존 PCB profile에서 지원하지 않는다. [환경 계약](../01_개발문서/05_기능설계/02_설계편집/12_적층과_외부환경.md)의 저장/CAD/EM 구분을 따른다.

GUI의 파일 저장과 별도 CLI writer를 동시에 같은 workspace에 사용하지 않는다. 서비스는 stdout에 UTF-8 JSON-RPC/NDJSON 응답만 기록한다. workspace 없는 bootstrap과 프로젝트를 연 서비스의 capability는 다르다. [bootstrap](../01_개발문서/02_시스템명세/07_초기구현_계약.md), [서비스/worker 경계](../01_개발문서/03_아키텍처/05_형상과_해석작업_연결경계.md).

## 시험과 기록

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
ctest --preset windows-release
.venv/Scripts/python.exe -X utf8 tools/build_implementation_audit.py --check
.venv/Scripts/python.exe -X utf8 tools/documentation/check_documents.py
```

실제 GUI 시험은 `RFAD_GUI_EXE`, OCCT 시험은 `RFAD_CAD_PYTHON`, WSL 실제 계산은 시험별 명시 조건을 요구한다. 환경 제외를 통과 수에 합산하지 않는다. 최신 실행 범위/시점은 [개발 상태](../01_개발문서/09_개발계획/02_개발착수와_현재상태.md)와 [runtime_profiles](runtime_profiles)를 따른다. 문서 검사 성공은 실제 GUI/FDTD/실측 수용이 아니다.

문서 변경 시 계약/화면/현재 상태/요구 연결을 함께 갱신한다. 기능별로 한국어 Doxygen, C++ Allman/4칸/중괄호 필수 규칙을 적용하고 주 창에 계산/영구 명령 로직을 몰지 않는다.
