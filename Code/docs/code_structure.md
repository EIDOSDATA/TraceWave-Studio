# 코드 구조와 유지보수 규칙

갱신일: 2026-11-11 KST

승인 설계 RFAD-D0-3.4를 유지한 구조 정리다. 공개 JSON-RPC, 프로젝트 저장 schema, 도메인 명령과 물리 모델의 의미를 새 GUI 계층에서 복제하지 않는다. 기능을 찾기 쉽게 파일을 분리하면서 상태와 결과의 소유자도 명시한다.

## GUI 구성 방식

wxWidgets View + Presentation Model + Service Gateway 구성을 사용한다. wxWidgets의 위젯과 이벤트는 화면 계층에 두고, 해석 단계/조회/입력 표시 정책은 위젯 없이 검사할 수 있는 객체에 둔다. 원본 도메인 모델은 Python 서비스가 소유한다. 별도 MVVM 프레임워크나 유료 부품을 추가하지 않는다.

```mermaid
flowchart LR
    Entry[main / Options] --> Frame[StudioFrame / wxWidgets View]
    Frame --> Policy[AnalysisWorkflow / JobTracker]
    Frame --> Form[EditorPresentation / EditorPanel]
    Frame --> Canvas[CanvasScene / Viewport / Renderer / GestureState]
    Frame --> Requests[RequestDispatcher]
    Requests --> Transport[ServiceClient / stdio]
    Transport --> Service[ProjectService]
    Tests[StudioSmokeDriver] --> Frame
```

| 경계 | 파일 | 책임 |
| --- | --- | --- |
| 진입점 | `ui/wxwidgets/main.cpp`, `app_options.h` | 실행 옵션 확인과 주 창 생성 |
| 화면 조립 | `studio_frame.*`, `studio_layout.cpp`, `studio_controls.cpp` | 위젯 수명, 화면 배치와 명령 활성화 |
| 기능별 화면 연결 | `studio_project.cpp`, `studio_editing.cpp`, `studio_drawing.cpp`, `studio_geometry_dialogs.cpp`, `studio_validation.cpp` | 프로젝트/편집/그리기/진단의 이벤트 연결과 DTO 표시 |
| CAD/해석 표시 | `studio_cad.cpp`, `studio_solver.cpp` | 서비스 명령 접수와 화면 반영. 도메인 계산은 서비스에 위임 |
| 비동기 통신 | `async_state.*`, `studio_session.cpp`, `service_client.*` | 요청 식별/콜백 회수/대기 상한/timeout, 작업 조회, 프로세스와 파이프 |
| 해석 단계 | `analysis_workflow.*` | Snapshot -> Plan -> Prepare -> Analysis -> Completed의 명시적 전이. 시작 설정 고정 |
| 장면 모델 | `canvas_scene.*`, `canvas_viewport.*`, `canvas_geometry.h` | 표시 DTO 해석, 객체 ID 색인, 경계/hit 검사, 좌표 변환 |
| 화면 그리기/입력 | `canvas_renderer.*`, `canvas_gesture.h`, `design_canvas.*` | paint 단위 renderer, 배타적 입력 상태와 wx 이벤트 변환 |
| 속성 폼 | `editor_presentation.*`, `coordinate_editor_dialog.*`, `editor_panel.*` | 값/모드별 표시 정책, 좌표 표 대화상자, 위젯 생성과 이벤트 |
| PCB 선택 상태 | `pcb_selection_model.*`, `pcb_selection_model_data.*` | 위젯 없는 요청 세대, 초안, 개정 고정, 미리보기와 적용 상태 |
| PCB 선택 화면 | `pcb_selection_dialog.*`, `pcb_selection_view.cpp`, `pcb_selection_layers.cpp`, `pcb_selection_materials.cpp`, `pcb_selection_review.cpp`, `studio_pcb.cpp` | 검색, 층/급전/물성 입력, 단면 검토, 대화상자 수명과 서비스 연결 |
| 실제 GUI 시험 | `studio_smoke.h`, `studio_smoke_*.cpp` | smoke 옵션의 시나리오/검사 상태. 제품 작업 객체에서 시험용 필드 분리 |

StudioFrame은 화면 사이의 연결과 서비스 DTO 캐시를 유지한다. 같은 클래스를 여러 파일로 나눈 부분은 화면 구성과 이벤트 연결이며, 재사용 상태/정책은 RequestDispatcher, JobTracker, AnalysisWorkflow, CanvasScene, EditorPresentation으로 실제 분리했다. StudioSmokeDriver만 시험을 위해 주 창의 private 위젯에 접근한다. 서비스/도메인은 시험 운전자나 wxWidgets를 참조하지 않는다.

`studio_frame.h`는 구체 위젯을 가능한 한 전방 선언한다. `studio_internal.h`는 화면 구현에서만 사용하는 위젯 include와 메뉴 ID를 보관한다. 문자열/UUID 변환은 `studio_support.*`, 공통 JSON/시각 별칭은 `studio_types.h`에 둔다.

## 상태와 응답 처리

- RequestDispatcher는 응답 콜백을 먼저 회수한 뒤 화면으로 넘긴다. 중복 응답과 연결 종료 뒤 과거 응답을 다시 실행하지 않는다. 요청은 최대 16개, 응답 제한은 30초이며 변경 명령을 자동 재전송하지 않는다.
- JobTracker는 일반 작업/CAD/해석의 조회 중 여부와 간격을 공통으로 관리한다. 이전 job의 지연 응답은 새 job의 조회 잠금까지 해제할 수 없다. 큐 거부와 조회 오류도 조회 상태를 회수하여 영구 정지를 피한다.
- AnalysisWorkflow는 시작한 개정과 설정을 고정하고, 올바른 단계의 완료 자료만 다음 명령으로 바꾼다. 취소 의도와 취소 전달 중 상태를 분리한다. 전달 실패 후 재시도할 수 있어도 다음 단계로 자동 진행하지 않는다.
- CAD/WSL 작업의 실제 종료 확인은 서버 coordinator가 맡는다. GUI의 취소 버튼이나 전송 단절을 실제 프로세스 종료로 취급하지 않는다.
- PcbSelectionModel은 검색/초안/미리보기 요청 세대를 비교하여 늦은 응답을 버린다. 입력을 변경하면 기존 미리보기를 무효화하고, 검토한 사양과 해시만 적용한다. 결과가 불명확한 적용 실패는 Stale로 잠가 재조회하도록 한다. 닫힌 대화상자의 응답은 약한 참조와 종료 상태로 폐기한다.
- 서버 `job_state.py`는 허용 전이를 명시하고 완료 상태 역행, 취소 요청 뒤 완료 승격과 event 식별 필드 덮어쓰기를 거절한다. 명시적 사용자 취소는 cancelled, 서비스 종료로 결과를 게시하지 않은 경우는 interrupted로 구분한다. 실제 종료가 확인되면 예약을 해제하고, 불명 상태는 예약을 유지한다. CAD 프로세스 회수와 WSL lease/outcome_unknown 처리는 각 coordinator의 별도 책임으로 남긴다.

## 서비스와 worker 구성

| 경계 | 모듈 | 책임 |
| --- | --- | --- |
| 공개 서비스 facade | `application/projects.py` | 저장소/조정기 수명, 요청 dispatch와 transaction 경계 |
| 카탈로그 facade | `catalog/service.py`, `application/catalog_api.py`, `cli/catalog.py` | 프로젝트 변경과 독립된 읽기 전용 자료 검색/상세, 선택적 DB 설정 |
| 카탈로그 자료 | `catalog/models.py`, `properties.py`, `source.py`, `build.py`, `schema.py`, `review.py` | 안정 ID/물성 조건, 원본 검증과 오프라인 원자적 SQLite 변환 |
| 카탈로그 adapter/조회 | `catalog/native*.py`, `query.py`, `repository.py` | 업체별 원시 자료 보존, 허용 필터와 읽기 트랜잭션/페이지/상한 |
| PCB 선택 근거/물성 | `catalog/selection_reader.py`, `selection_rules.py`, `material_selection.py` | 같은 개정의 제한된 원문 사본, Dk/Df 독립 채택과 사용자 가정 |
| 제조업체 적층 초안 | `catalog/stackup_draft*.py` | JLCPCB/PCBWay/관측별 물리 층 변환, 미정값과 수동 구성 사유 |
| PCB 적용 조정 | `application/pcb_selection*.py` | 요청 계약, 후보 조립, 층/급전 참조 검사, 미리보기 해시와 단일 writer 적용 |
| PCB 저장 계약 | `domain/pcb_selection*.py` | 버전이 있는 출처 확장, 현재 참조에 필요한 이전 출처, 원자 명령과 역명령 |
| 요청 규칙 | `project_contract.py`, `request_ledger.py` | 입력 형태/상한/경로, epoch와 receipt의 멱등성 |
| 프로젝트 데이터 | `project_repository.py`, `project_history.py`, `project_operations.py` | 불변 문서 저장, 명령/undo/redo, 열기/저장/snapshot/검사 |
| 작업 조정 | `solver_jobs.py`, `cad_jobs.py`, `job_state.py` | 작업 접수/실행/취소/게시 및 명시적 상태 전이 |
| 실행 설정 | `solver_runtime.py`, `cad_runtime.py`, `solver_requests.py` | runtime 출처, 실행 입력과 지원 profile |
| 산출물 | `solver_artifacts.py`, `solver_queries.py`, `cad_artifacts.py` | 파일 검증/봉인과 작은 조회 DTO |
| PCB 투영 | `pcb_solver.py`, `pcb_projection.py`, `pcb_geometry.py`, `pcb_results.py` | 계획 조립, 물리 입력/도체 투영, 결과/종료 판정 |
| 격자/접촉 | `pcb_mesh.py`, `pcb_contacts.py`, `adapters/solvers/openems/pcb_mesh.py` | 계획 격자, 물리 접촉과 native 격자 확인 |
| CAD adapter | `adapters/cad/native.py`, `geometry.py`, `bodies.py`, `step_io.py`, `display.py` | 패키지 조립, 고체 생성/집계, STEP 교환과 표시 mesh |

기존 공개 import와 필요한 worker 연결 seam은 명시적 재노출/위임으로 유지한다. 동적 mixin이나 monkeypatch로 구현 파일을 연결하지 않는다. 파일별 상세 책임과 작업 상태도는 [worker 구조](worker_structure.md), 원자적 저장/이력 경계는 [저장 계약](project_persistence.md)을 따른다.

## 재사용과 방어 보강

- CanvasScene의 ID 색인과 이미 해석한 polygon을 hit 검사에서 재사용한다. canvas renderer는 도형마다 graphics context를 만들지 않고 paint 단위로 재사용한다.
- 프로젝트 이력 복원은 명령 색인과 문서 읽기를 재사용한다. 폼 표시 정책은 필요한 mode/value/unit만 읽어 편집 중 bindings나 좌표 초안을 강제로 확정하지 않는다.
- 서비스 시작 도중 실패하면 이미 시작된 thread/coordinator와 journal writer를 회수한다. 시작하지 못한 thread에 join을 시도하지 않는다.
- captured 문서의 정규 바이트를 검사하고 알 수 없는 자료 작업을 snapshot 생성으로 처리하지 않는다.

이 변경은 실제 fps 또는 전체 메모리 예산 합격을 뜻하지 않는다. 성능 수치는 별도의 대표 장면에서 측정한다.

## 추가 변경 규칙

카탈로그 PCB 통합 검증은 제품의 공개 API를 사용하는 `tools/catalog_pcb_verification/`에 둔다. `common.py`는 RPC/대기/봉인 자료 읽기와 원자 보고서 게시, `cad.py`는 형상/STEP/mesh와 재입력, `solver.py`는 계획/준비/계산/후처리/재열기, `runner.py`는 입력 검사와 같은 snapshot의 단계 실행을 담당한다. `tools/verify_catalog_pcb.py`는 CLI만 구성한다. 실제 JLC 입력을 재현하는 도구는 시험 물성을 먼저 제거한 후 출처로 확인한 치수와 Dk만 선택하며, 제품의 재료 기본값을 변경하지 않는다.

1. 새 기능은 원본 domain, application orchestration, 외부 adapter, presentation 중 책임을 먼저 정한다. 여러 책임의 동작을 진입점이나 주 창에 모두 추가하지 않는다.
2. 화면의 입력 정책과 상태 전이는 가능한 한 wx 없는 객체로 두고, 외부 프로세스/파일 I/O는 명시적 경계에 둔다. GUI에 물리 공식/도메인 해시의 별도 구현을 만들지 않는다.
3. 상태 필드를 늘릴 때 허용 조합과 전이를 먼저 정한다. 진행 단계는 enum/명시적 상태표, 독립적인 취소 의도/전송 상태는 별도 값으로 표현한다.
4. 코드 주석은 한국어 Doxygen, C++는 BSD/Allman과 공백 4칸, 제어문 중괄호 필수다. `.clang-format`과 `.editorconfig`를 제공한다. 파일 길이만 줄이는 기계적 분할이나 불필요한 추상 계층은 피한다.
5. 기존 저장소/명령/결과 계약과 취소/복구 의미를 보존하는 회귀를 수행한다. 네이티브 함수 이동 시 입력 계획과 실제 CAD/openEMS 실행을 확인한다.

기존 IFA 수렴과 runtime profile은 당시 소스의 검증 기록으로 유지한다. 소스 분리에 따라 worker source identity가 달라지므로 이전 연구에 현재 소스로 `--resume`을 섞지 않는다. 완료 자료의 `--reassess-only` 또는 새 workspace를 사용한다.
