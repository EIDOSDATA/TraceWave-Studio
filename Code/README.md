# TraceWave Studio 개발 영역

제품 소스, 빌드, 시험과 현재 개발 문서는 이 Code 아래에서 관리한다. 승인 기준선은 RFAD-D0-3.4, 승인 커밋은 `6ebeda156e9d31b893bf69046550f5df9b16dc64`다. Windows 11 + WSL2를 우선하는 R1 내부 검증용 제품을 개발하며 전체 R1 수용은 아직 완료하지 않았다.

## 문서에서 시작하기

- [분야별 문서 안내](docs/README.md): 화면 설계, 기능, 명세, 구조, 분석, 검증, 운영과 계획.
- [Studio 화면설계서](docs/screen_design/README.md): 화면마다 기능/입출력/버튼 이벤트/전환/예외, DrawIO/PNG/SVG, 객체 이름/선택과 접근성.
- [현재 계획](docs/planning/completion_plan.md)과 [개발 상태](docs/planning/development_status.md): 기존 1~13번 순서와 날짜별 실제 증거.
- [공통 계약](docs/specifications/shared_contracts.md), [코드 구조](docs/architecture/code_structure.md), [구현 감사](docs/verification/implementation_audit.md).
- [이번 문서 검토](docs/review/README.md): 현재형 정정, 원문 보존, 남은 설계/증거 의존성과 전수 분류.

승인 01_Docs의 `착수 전`은 당시 기록이다. 현재 설명은 이 개발 문서를 따른다. 초기 제안, 원문 자료와 과거 runtime profile을 현재 구현에 맞춰 소급 변경하지 않는다.

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
| 프로젝트/편집 | core 0.4 쓰기/0.1~0.4 읽기, 명령/undo/redo/저장/불변 snapshot, 표현식과 기본 도형. [프로젝트](docs/features/project/project_persistence.md), [2D](docs/features/design/canvas_contract.md) |
| 목표/후보 | 다중 목표, 원호/IFA 명시 치수, G031/G001/G008/G009 부분 기하 및 조건부 초기 길이. [설계 기능](docs/features/design/README.md) |
| 제약/연결/환경 | 기본 제약/기대 연결/DRC, 적층/표면층/개구, 기본 외부 STEP 배치. [규칙](docs/features/design/design_rules.md), [환경](docs/features/design/physical_setup.md) |
| 재료/출처 | 제조사 자료 조회, 명시 채택/근사/사용자 수정, 미정과 출처 사본 보존. [재료 기능](docs/features/materials/README.md) |
| CAD/해석 | 별도 worker의 STEP/3D, 제한된 단일 포트 PCB 해석/결과/방사 조회, 한 축 프로젝트 수치 연구. [해석](docs/features/analysis/README.md), [CAD](docs/features/exports/cad_contract.md) |
| 검증/연구 | IFA/방사/전력/개별 손실 연구와 원시 결과 재열기. [연구 기록](docs/research/README.md) |

스냅/끝점 편집은 이전 미커밋 작업 트리에 보존되어 있다. 이번 문서 정비는 그 최종 검증/커밋을 대신하지 않는다. 전체 Studio 흐름/정밀 편집/객체 이름 통일, 공통 복소 결과/회로/측정 파일, 다축 스윕/다중 비교/3D 방사, 도면/CAM 및 전체 UX 수용은 해당 계획의 남은 범위다.

실제 납품 물성/제작/급전 실장/시료/교정/측정 조건은 자료 확보 전까지 미정이다. 문헌 부분 기하, 초기 추정, 해석 완료, 수렴, 물리/제조/실측 검증을 별도로 표시한다. RO4350B 국부 방사 도체 손실 변화 2.788446%로 초기 2% 기준 미확립 및 GHz PTH 독립 정확도 미확립을 유지한다.

## 실행

모든 명령의 작업 디렉터리는 Code다. Python 환경 준비는 [Windows 환경](docs/operations/python_environment.md), WSL은 [전용 환경](docs/operations/wsl_environment.md), 빌드는 [wxWidgets 안내](ui/wxwidgets/README.md)를 따른다.

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -X utf8 -m rfad doctor --output .local/runtime-doctor.json
.venv/Scripts/python.exe -X utf8 -m rfad serve --workspace .local/projects-workspace
.\tools\launch_gui.ps1
```

GUI 실행 스크립트는 존재하는 `.venv-cad`와 `.local/pcb-catalog/catalog.sqlite`를 연결한다. `-CadPython <경로>`, `-Catalog <경로>`, `-NoCatalog`로 선택할 수 있다. 해석 환경 구성 후에는 `launch_gui.ps1 -OpenEmsWsl`을 사용한다. CAD/solver가 없어도 가능한 편집/저장과 보존 결과 읽기는 유지한다.

STEP 출력은 필요한 기하 입력과 미적용 폼을 확인한 뒤 snapshot을 고정한다. 기본 모델에는 양수 두께/명시 z/필요 좌표가 있어야 한다. 외부 STEP은 현재 단일 mm 고체 등 명시된 제한이 있으며, 표면층/외부 환경의 EM 포함은 기존 PCB profile에서 지원하지 않는다. [환경 계약](docs/features/design/physical_setup.md)의 저장/CAD/EM 구분을 따른다.

GUI의 파일 저장과 별도 CLI writer를 동시에 같은 workspace에 사용하지 않는다. 서비스는 stdout에 UTF-8 JSON-RPC/NDJSON 응답만 기록한다. workspace 없는 bootstrap과 프로젝트를 연 서비스의 capability는 다르다. [bootstrap](docs/specifications/bootstrap_contract.md), [서비스/worker 경계](docs/architecture/worker_integration.md).

## 시험과 기록

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
ctest --preset windows-release
.venv/Scripts/python.exe -X utf8 tools/build_implementation_audit.py --check
.venv/Scripts/python.exe -X utf8 tools/documentation/check_documents.py
```

실제 GUI 시험은 `RFAD_GUI_EXE`, OCCT 시험은 `RFAD_CAD_PYTHON`, WSL 실제 계산은 시험별 명시 조건을 요구한다. 환경 제외를 통과 수에 합산하지 않는다. 최신 실행 범위/시점은 [개발 상태](docs/planning/development_status.md)와 [runtime_profiles](runtime_profiles/)를 따른다. 문서 검사 성공은 실제 GUI/FDTD/실측 수용이 아니다.

문서 변경 시 계약/화면/현재 상태/요구 연결을 함께 갱신한다. 기능별로 한국어 Doxygen, C++ Allman/4칸/중괄호 필수 규칙을 적용하고 주 창에 계산/영구 명령 로직을 몰지 않는다.
