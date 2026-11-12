# 기능별 구현 대조

자동 생성: tools/build_implementation_audit.py. 근거 경로는 Code 기준이다. 시험 연결은 전체 AC 합격을 뜻하지 않는다.

## FN-001

상태: partial. 담당 단계: 3/12

ProjectOperations.open은 workspace 안 projects/이름의 create/open/recover와 원본 해시 검사, 서비스 재시작 후 재열기를 제공한다. 0.1/0.2/0.3을 읽으며 기존 원본과 snapshot을 보존하고 변경 복제본만 0.3 새 개정으로 승격하여 변환 기록을 남긴다.

남은 범위:

- copy 모드, 외부 프로젝트/archive 가져오기와 새 project ID 발급이 없다.
- recover는 등록된 현재 문서를 여는 경로이며 복구 후보 선택/검사 보고서가 없다.
- 범용 migration graph, 백업/rollback 보고서와 read-only open 정책은 미구현이다.

코드:

- [src/rfad/application/project_contract.py](../../src/rfad/application/project_contract.py)
- [src/rfad/application/project_operations.py](../../src/rfad/application/project_operations.py)
- [src/rfad/application/project_repository.py](../../src/rfad/application/project_repository.py)
- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)

시험:

- [tests/test_project_service.py::ProjectServiceTests.test_create_apply_save_reopen_after_service_restart](../../tests/test_project_service.py)
- [tests/test_parameter_graph.py::ParameterGraphTests.test_old_schema_remains_unchanged_and_upgrades_on_copy](../../tests/test_parameter_graph.py)
- [tests/test_targets.py](../../tests/test_targets.py)

기존 실행/설명 근거:

- [docs/project_persistence.md](../../docs/project_persistence.md)
- [docs/target_contract.md](../../docs/target_contract.md)

계약 확인:

- project_contract.validate_project_request는 create/open/recover만 허용한다. 시험명 upgrades_on_copy의 copy는 Python 원본 복제이며 project.open copy 지원이 아니다.

## FN-002

상태: partial. 담당 단계: 3/12

expected_revision, command_id, 영수증, 역명령과 새 revision을 journal transaction으로 게시한다. 저장 기준점, 독립 snapshot ID/hash와 영속 undo/redo를 보존한다.

남은 범위:

- artifact별 regenerated/stale/unchanged와 물리 입력 동등성에 따른 정밀 무효화가 미완성이다.
- 공통 묶음 편집 및 영속 이력 확장 정책은 현재 제한 명령/128 undo/2048 command 예산을 넘어 별도 정의가 필요하다.

코드:

- [src/rfad/application/project_history.py](../../src/rfad/application/project_history.py)
- [src/rfad/application/project_operations.py](../../src/rfad/application/project_operations.py)
- [src/rfad/storage/journal.py](../../src/rfad/storage/journal.py)
- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)

시험:

- [tests/test_project_service.py::ProjectServiceTests.test_snapshot_stays_sealed_after_edit_and_save](../../tests/test_project_service.py)
- [tests/test_project_service.py::ProjectServiceTests.test_failed_publish_does_not_commit_command_or_receipt](../../tests/test_project_service.py)
- [tests/test_editor_service.py::EditorServiceTests.test_undo_redo_replay_restart_and_branch_preserve_saved_baseline](../../tests/test_editor_service.py)

기존 실행/설명 근거:

- [docs/project_persistence.md](../../docs/project_persistence.md)
- [docs/editor_contract.md](../../docs/editor_contract.md)

계약 확인:

- 현재 invalidation_set은 계층 이름의 보수적 목록이다. parameter.set은 표시 단위/이름 변경에도 geometry/physics 등을 무효화한다. 원시 결과 삭제는 하지 않지만 최적 재사용 구현과 같지 않다.

## FN-003

상태: partial. 담당 단계: 3/6

제한 문법 표현식, SI 차원 검사, UUID 변수 결합, 의존 그래프/순환 검출, 유한 값/정의역 검사와 출처/estimated 전파가 구현됐다.

남은 범위:

- 사용자 설정 bound와 정수/범주형 설계 변수 제약을 저장하는 공통 계약이 없다.
- 표시 단위만 바꿀 때 물리/solver hash가 유지되는 별도 의미 hash와 계층별 무효화 검증이 남는다.

코드:

- [src/rfad/domain/expressions.py](../../src/rfad/domain/expressions.py)
- [src/rfad/domain/parameter_graph.py](../../src/rfad/domain/parameter_graph.py)
- [src/rfad/domain/units.py](../../src/rfad/domain/units.py)
- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)

시험:

- [tests/test_expressions.py](../../tests/test_expressions.py)
- [tests/test_parameter_graph.py](../../tests/test_parameter_graph.py)
- [tests/test_editor_service.py::EditorServiceTests.test_display_unit_only_preserves_si_and_provenance_and_explicit_value_is_converted](../../tests/test_editor_service.py)

기존 실행/설명 근거:

- [docs/design_data.md](../../docs/design_data.md)

계약 확인:

- 표시 단위 시험은 SI 값/출처 보존을 확인한다. 이 시험을 solver 입력 hash 불변이나 cache 재사용 합격으로 확대하지 않는다.

## FN-004

상태: partial. 담당 단계: 3/4/5/7

rfad.target/0.1은 최대32개 사용자 목표의 대역/표본/port/Z0/출처와 S11/방사효율/전체효율/비율대역폭 한계를 target.set/remove로 저장한다. 0.3 개정, 저장/재열기/snapshot/영속 undo/redo를 연결하고 미정 입력과 not_evaluated를 구분한다. target.editor.get/apply와 wxWidgets 다중 목표 편집을 연결하고 변경값만 처리한다. 기존 SI/출처, 미정/근사 상태와 최대1001개 명시 표본을 보존한다.

남은 범위:

- 지역/원문/version을 보존하는 통신 프리셋이 없다.
- 관측 방향/편파/실현 이득/크기 및 제조 제약, parameter 참조와 필요한 데이터 사전 도출은 후속이다.
- MetricRecord/Assessment 실제 평가와 개정 간 자동 raw 재사용은 미구현이다.

코드:

- [src/rfad/domain/targets.py](../../src/rfad/domain/targets.py)
- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)
- [src/rfad/application/project_history.py](../../src/rfad/application/project_history.py)
- [src/rfad/application/project_operations.py](../../src/rfad/application/project_operations.py)
- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/solver.py](../../src/rfad/application/solver.py)
- [src/rfad/application/target_editor.py](../../src/rfad/application/target_editor.py)
- [src/rfad/application/target_editor_fields.py](../../src/rfad/application/target_editor_fields.py)
- [src/rfad/application/target_editor_values.py](../../src/rfad/application/target_editor_values.py)
- [ui/wxwidgets/target_editor_dialog.cpp](../../ui/wxwidgets/target_editor_dialog.cpp)
- [ui/wxwidgets/project_setup_dialog.cpp](../../ui/wxwidgets/project_setup_dialog.cpp)

시험:

- [tests/test_targets.py](../../tests/test_targets.py)
- [tests/test_target_editor.py](../../tests/test_target_editor.py)
- [tests/test_gui_target_template_process.py](../../tests/test_gui_target_template_process.py)

기존 실행/설명 근거:

- [docs/target_contract.md](../../docs/target_contract.md)
- [docs/target_editor_contract.md](../../docs/target_editor_contract.md)
- [docs/target_template_gui.md](../../docs/target_template_gui.md)

계약 확인:

- 0.1/0.2는 비어 있지 않은 targets를 거부하며 기존 봉인 원본은 변경하지 않는다. 목표 입력은 solver 주파수/물성/port 저항을 변경하지 않고 geometry/physics/network 무효화를 추가하지 않는다.
- target_input_statuses는 missing_target/not_evaluated와 누락 조건을 제공하며 합격 판정을 만들지 않는다. 기존 고정 연구 acceptance_profile은 제품 목표와 별개다.

## FN-005

상태: partial. 담당 단계: 3/10

정리한 PCB source package의 manifest/hash/관측 schema를 확인해 SQLite를 원자 구축하고 페이지 조회한다. 선택한 관측은 프로젝트에 원문/출처/결정으로 보존한다.

남은 범위:

- API-009 import.preview/API-010 import.commit의 범용 staging, target와 catalog revision 충돌 처리가 없다.
- PCB 이외 geometry/template 자료의 importer와 변경/중복/상충 preview가 필요하다.

코드:

- [src/rfad/catalog/build.py](../../src/rfad/catalog/build.py)
- [src/rfad/catalog/source.py](../../src/rfad/catalog/source.py)
- [src/rfad/catalog/service.py](../../src/rfad/catalog/service.py)
- [src/rfad/application/catalog_api.py](../../src/rfad/application/catalog_api.py)
- [src/rfad/domain/pcb_selection_evidence.py](../../src/rfad/domain/pcb_selection_evidence.py)

시험:

- [tests/test_catalog_build.py](../../tests/test_catalog_build.py)
- [tests/test_catalog_api.py](../../tests/test_catalog_api.py)
- [tests/test_pcb_selection_service.py](../../tests/test_pcb_selection_service.py)

기존 실행/설명 근거:

- [runtime_profiles/pcb-catalog.json](../../runtime_profiles/pcb-catalog.json)
- [runtime_profiles/pcb-selection.json](../../runtime_profiles/pcb-selection.json)

계약 확인:

- catalog API는 read_only이며 프로젝트 선택 적용은 pcb.selection 확장 경로다. offline catalog build를 승인된 범용 import API로 표시하지 않는다.

## FN-006

상태: partial. 담당 단계: 3/4

내장 명시 치수 원호/평면 IFA 카드2종의 version/hash/입력/출처/지원 플래그와 template.list/get/context를 제공한다. GUI에서 기존 기판/도체층과 목표 개정을 선택하고 입력/2D 후보를 검토한다. 프로젝트는 카드와 생성 객체/원자료 사본을 소유한다. G031 문헌 원호/stub 카드는 원본 중첩 ZIP/Gerber/PDF 식별자와 원문 치수/가정/미정/생략을 보존한다. GUI는 원문 값과 사용자 수정/배치를 구분한다. 추가 G001/G008/G009는 PDF hash/페이지/부분 도체 치수/미정과 AN1088 두께 불일치를 고정 사본으로 보존하며 기존 GUI와 원자 적용을 재사용한다.

남은 범위:

- G031/AN1088 전체 보드 재현, 추가 문헌 topology와 범용 자료별 검증 근거를 보강해야 한다.
- 범용 카드 importer/검색/갱신 관리와 통신 프리셋 기반 선택은 후속이다.

코드:

- [src/rfad/templates/cards.py](../../src/rfad/templates/cards.py)
- [src/rfad/domain/template_instance.py](../../src/rfad/domain/template_instance.py)
- [src/rfad/application/template_candidates.py](../../src/rfad/application/template_candidates.py)
- [ui/wxwidgets/template_dialog.cpp](../../ui/wxwidgets/template_dialog.cpp)
- [src/rfad/templates/g031.py](../../src/rfad/templates/g031.py)
- [src/rfad/templates/printed_references.py](../../src/rfad/templates/printed_references.py)

시험:

- [tests/test_template_candidates.py](../../tests/test_template_candidates.py)
- [tests/test_gui_target_template_process.py](../../tests/test_gui_target_template_process.py)
- [tests/test_literature_templates.py](../../tests/test_literature_templates.py)
- [tests/test_printed_seeds.py](../../tests/test_printed_seeds.py)
- [tests/test_gui_printed_seed_process.py](../../tests/test_gui_printed_seed_process.py)

기존 실행/설명 근거:

- [docs/template_contract.md](../../docs/template_contract.md)
- [docs/target_template_gui.md](../../docs/target_template_gui.md)
- [docs/literature_templates.md](../../docs/literature_templates.md)
- [docs/printed_templates_and_seeds.md](../../docs/printed_templates_and_seeds.md)

계약 확인:

- 재료 카탈로그의 제조업체 stackup template와 안테나 형상 template은 다른 의미다. 사용자 실행 script 확장은 R2다.
- 내장 카드는 로컬 기하 recipe이며 제조사 원본 재현이나 RF 검증 완료 카드가 아니다. 기하/합성/해석/수렴/실측/제조 지원 플래그를 분리한다.

## FN-007

상태: partial. 담당 단계: 3/4/9

API-007 template.synthesize의 explicit_geometry 모드로 명시 치수 후보를 읽기 전용 생성한다. 기판 경계/IFA 접촉과 열린 급전 gap, 안정 UUID/표현식 매개변수, 선택 목표 사본을 검사한다. 검토 hash를 다시 확인한 template.apply는 한 명령으로 적용/undo/redo하며 기존 출처/물성을 유지한다. G031의 원래 stub-원호 끝 겹침과 사용자 배치를 보존하며 원문 수정 필드를 표시한다. 기하 생성/초기 추정/해석/수렴/실측/제조 상태를 분리한다. G001 initial_estimate는 이상적 자유공간 1/4 파장과 원문 2.45 GHz/1.5 mm 조건의 0.75 보정 및 20%/30% 조정 여유만 제공한다. 요청/조건 가정/추정 Quantity와 정확한 산술을 저장하고 범위 밖 요청을 거부한다. 현재 물성/접지 조건은 확인하지 않는다.

남은 범위:

- 목표 주파수/공간/고정 변수를 사용하는 원호/IFA RF 합성과 공진/정합 검증은 미구현이다.
- 추가 문헌 원문 치수와 EQ/가정의 대응 및 실제 정합/공진 검증을 보강해야 한다.

코드:

- [src/rfad/application/template_candidates.py](../../src/rfad/application/template_candidates.py)
- [src/rfad/domain/template_geometry.py](../../src/rfad/domain/template_geometry.py)
- [src/rfad/domain/template_inputs.py](../../src/rfad/domain/template_inputs.py)
- [src/rfad/domain/template_ports.py](../../src/rfad/domain/template_ports.py)
- [src/rfad/domain/template_command.py](../../src/rfad/domain/template_command.py)
- [src/rfad/domain/layer_surface.py](../../src/rfad/domain/layer_surface.py)
- [src/rfad/domain/literature_geometry.py](../../src/rfad/domain/literature_geometry.py)
- [src/rfad/domain/template_provenance.py](../../src/rfad/domain/template_provenance.py)
- [src/rfad/domain/template_seeds.py](../../src/rfad/domain/template_seeds.py)
- [src/rfad/domain/printed_geometry.py](../../src/rfad/domain/printed_geometry.py)
- [ui/wxwidgets/template_seed_view.cpp](../../ui/wxwidgets/template_seed_view.cpp)

시험:

- [tests/test_template_candidates.py](../../tests/test_template_candidates.py)
- [tests/test_template_native.py](../../tests/test_template_native.py)
- [tests/test_gui_target_template_process.py](../../tests/test_gui_target_template_process.py)
- [tests/test_literature_templates.py](../../tests/test_literature_templates.py)
- [tests/test_printed_seeds.py](../../tests/test_printed_seeds.py)
- [tests/test_gui_printed_seed_process.py](../../tests/test_gui_printed_seed_process.py)

기존 실행/설명 근거:

- [docs/template_contract.md](../../docs/template_contract.md)
- [docs/target_template_gui.md](../../docs/target_template_gui.md)
- [docs/literature_templates.md](../../docs/literature_templates.md)
- [docs/printed_templates_and_seeds.md](../../docs/printed_templates_and_seeds.md)

계약 확인:

- tests/test_pcb_ifa.py의 ifa_document는 명시적 시험 가정 fixture다. 실제 납품 입력이나 제품 seed synthesizer로 승격하지 않는다.
- G001의 제한된 추정 길이를 RF 공진/정합 합성으로 표시하지 않는다. port:null과 미정 물성/저항은 유지한다. CAD 성공이나 초기 길이를 FDTD/실측 합격으로 확대하지 않는다.

## FN-008

상태: partial. 담당 단계: 3/4

line_path/arc_path/planar_region(holes)/pad/via 원본과 수량/매개변수 결합, 생성/이동/삭제 및 2D DTO를 제공한다. CAD는 analytic 원호와 같은 net의 물리 union을 지원한다. 공통 라이트 표면/도킹/간격과 좁은 도구 영역의 줄바꿈을 실제 wxWidgets 작업 공간에 적용했다. 목표/템플릿 창은 native 폼과 기존 2D renderer를 재사용하고 비동기 요청 세대/불명 변경 잠금을 공유한다. 시안의 작업 탭 5개/프로젝트와 레이어 분리/세로 도구/실제 작업 상태를 연결했다. 레이어 체크는 원본과 해석 포함 여부를 바꾸지 않는 2D 표시 상태다. 기존 OpenGL 3D와 실제 결과/보고서/STEP 흐름을 유지한다.

남은 범위:

- 사용자 평면 Boolean/offset/회전/미러 명령과 결과 subentity 대응이 없다.
- 스냅/끝점/연관 치수와 영역 길이/면적/최소 gap의 공통 조회를 보강해야 한다.

코드:

- [src/rfad/domain/design.py](../../src/rfad/domain/design.py)
- [src/rfad/domain/planar.py](../../src/rfad/domain/planar.py)
- [src/rfad/application/canvas.py](../../src/rfad/application/canvas.py)
- [src/rfad/adapters/cad/geometry.py](../../src/rfad/adapters/cad/geometry.py)
- [ui/wxwidgets/studio_theme.h](../../ui/wxwidgets/studio_theme.h)
- [ui/wxwidgets/studio_theme.cpp](../../ui/wxwidgets/studio_theme.cpp)
- [ui/wxwidgets/studio_layout.cpp](../../ui/wxwidgets/studio_layout.cpp)
- [ui/wxwidgets/studio_design_setup.cpp](../../ui/wxwidgets/studio_design_setup.cpp)
- [ui/wxwidgets/project_setup_dialog.cpp](../../ui/wxwidgets/project_setup_dialog.cpp)
- [ui/wxwidgets/studio_workspace.cpp](../../ui/wxwidgets/studio_workspace.cpp)
- [ui/wxwidgets/workspace_bar.cpp](../../ui/wxwidgets/workspace_bar.cpp)
- [ui/wxwidgets/drawing_rail.cpp](../../ui/wxwidgets/drawing_rail.cpp)

시험:

- [tests/test_canvas_service.py](../../tests/test_canvas_service.py)
- [tests/test_copper_design.py](../../tests/test_copper_design.py)
- [tests/test_planar.py](../../tests/test_planar.py)
- [tests/test_cad_native.py](../../tests/test_cad_native.py)
- [tests/test_gui_target_template_process.py](../../tests/test_gui_target_template_process.py)
- [tests/test_printed_seeds.py](../../tests/test_printed_seeds.py)
- [tests/test_gui_printed_seed_process.py](../../tests/test_gui_printed_seed_process.py)

기존 실행/설명 근거:

- [docs/canvas_contract.md](../../docs/canvas_contract.md)
- [runtime_profiles/copper-ifa-worker-wsl.json](../../runtime_profiles/copper-ifa-worker-wsl.json)
- [docs/studio_gui_design.md](../../docs/studio_gui_design.md)
- [docs/printed_templates_and_seeds.md](../../docs/printed_templates_and_seeds.md)

계약 확인:

- CAD writer 내부 union은 사용자가 편집 가능한 Boolean graph 명령과 같지 않다. 매개변수 결합된 형상의 직접 이동 거절은 결합 보존 규칙이다.

## FN-009

상태: partial. 담당 단계: 3/4/8/10

기본 양수/참조/자기교차 검사, native polygon의 급전 접촉/단락, sheet/PTH 연결 성분과 IFA short 관계를 검사한다.

남은 범위:

- expected connectivity graph와 제조업체 width/gap/edge/hole/annular profile 검사 서비스가 없다.
- issue별 측정값/허용값/위치와 미평가 규칙, 공간 index와 사용자 제약 모델이 필요하다.

코드:

- [src/rfad/domain/design.py](../../src/rfad/domain/design.py)
- [src/rfad/domain/planar.py](../../src/rfad/domain/planar.py)
- [src/rfad/application/pcb_contacts.py](../../src/rfad/application/pcb_contacts.py)
- [src/rfad/application/pcb_selection_review.py](../../src/rfad/application/pcb_selection_review.py)

시험:

- [tests/test_pcb_contacts.py](../../tests/test_pcb_contacts.py)
- [tests/test_planar.py](../../tests/test_planar.py)
- [tests/test_copper_design.py](../../tests/test_copper_design.py)

기존 실행/설명 근거:

- [docs/copper_features.md](../../docs/copper_features.md)

계약 확인:

- pcb_contacts는 제한된 solver polygon 접촉 검사이며 완전한 제조 DRC가 아니다. connections/manufacturing_profiles는 현재 빈 collection만 허용한다.

## FN-010

상태: not_implemented. 담당 단계: 3/10

CAD worker의 자체 STEP 재입력은 구현됐으나 사용자 외부 CAD/EDA 파일을 편집 가능한 프로젝트로 가져오는 서비스는 없다.

남은 범위:

- KiCad/Gerber와 기본 외부 STEP reader, 지원 entity inventory와 단위/층/net/origin mapping preview가 필요하다.
- source hash 재검사, 손실/미지원 보고와 project.geometry 원자 적용 명령을 연결해야 한다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/adapters/cad/step_io.py](../../src/rfad/adapters/cad/step_io.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- [docs/cad_contract.md](../../docs/cad_contract.md)

계약 확인:

- 자체 STEP 검수용 read_step은 외부 CAD import 서비스가 아니다. import.preview/import.commit은 capabilities에서 제공하지 않는다.

## FN-011

상태: partial. 담당 단계: 3/8/10

정렬된 층의 z/두께/재료와 미정값, polygon hole, 원형/사각 pad 및 명시적 중공 PTH의 도금/홀/패드 참조를 저장하고 CAD/제한 EM에 투영한다.

남은 범위:

- mask/coating coverage/opening, 일반 NPTH/slot과 기본 assembly 형상의 공통 의미가 필요하다.
- 제조 두께/도금/공칭 포함 범위와 허용 공차를 연결하는 제작 profile 및 전 범위 검수가 남는다.

코드:

- [src/rfad/domain/design.py](../../src/rfad/domain/design.py)
- [src/rfad/application/pcb_selection_layers.py](../../src/rfad/application/pcb_selection_layers.py)
- [src/rfad/adapters/cad/bodies.py](../../src/rfad/adapters/cad/bodies.py)
- [src/rfad/application/pcb_projection.py](../../src/rfad/application/pcb_projection.py)

시험:

- [tests/test_copper_design.py](../../tests/test_copper_design.py)
- [tests/test_cad_copper_features.py](../../tests/test_cad_copper_features.py)
- [tests/test_pcb_ifa.py](../../tests/test_pcb_ifa.py)
- [tests/test_pcb_selection_service.py](../../tests/test_pcb_selection_service.py)

기존 실행/설명 근거:

- [runtime_profiles/copper-ifa-worker-wsl.json](../../runtime_profiles/copper-ifa-worker-wsl.json)
- [runtime_profiles/pcb-selection.json](../../runtime_profiles/pcb-selection.json)

계약 확인:

- coating/adhesive/air 역할의 저장 허용과 CAD/EM 투영 지원은 다르다. CAD는 해당 역할을 거절한다. 총두께에서 미정 코어/마스크를 임의 역산하지 않는다.

## FN-012

상태: partial. 담당 단계: 3/4/10/12

불변 snapshot을 mm CAD DTO로 바꿔 OCCT에서 분리 고체/원호/같은 net union/중공 PTH를 생성하고 stable body map과 제한 표시 mesh를 제공한다.

남은 범위:

- 외부 부품 assembly/배치/변환과 표면층/슬롯 등 선언할 R1 physical profile을 확장해야 한다.
- 대형 표시 LOD와 100만 triangle 경로, 전체 topology/조립 독립 검수가 남는다.

코드:

- [src/rfad/application/cad.py](../../src/rfad/application/cad.py)
- [src/rfad/adapters/cad/native.py](../../src/rfad/adapters/cad/native.py)
- [src/rfad/adapters/cad/bodies.py](../../src/rfad/adapters/cad/bodies.py)
- [src/rfad/adapters/cad/display.py](../../src/rfad/adapters/cad/display.py)
- [src/rfad/application/display_mesh.py](../../src/rfad/application/display_mesh.py)

시험:

- [tests/test_cad_native.py](../../tests/test_cad_native.py)
- [tests/test_cad_projection.py](../../tests/test_cad_projection.py)
- [tests/test_display_mesh.py](../../tests/test_display_mesh.py)

기존 실행/설명 근거:

- [runtime_profiles/gui-cad-windows-x64.json](../../runtime_profiles/gui-cad-windows-x64.json)
- [runtime_profiles/cad-worker-windows-x64.json](../../runtime_profiles/cad-worker-windows-x64.json)

계약 확인:

- 물리 BREP/표시 mesh/solver polygon의 tolerance와 의미를 공유하지 않는다. 현재 board transform은 거절되므로 좌표계 필드 존재만으로 assembly 지원을 주장하지 않는다.

## FN-013

상태: not_implemented. 담당 단계: 3/8/9/11

현재 board/shape의 표시/해석/출력 포함 플래그는 있으나 환경 scenario와 외부 STEP 배치 기능은 없다.

남은 범위:

- environment collection의 물체/재료/rigid transform와 baseline+delta schema 및 명령이 필요하다.
- 기본 하우징/배터리/케이블 포함 범위, 접촉과 scenario별 solver 정의를 검증해야 한다.

코드:

- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)
- [src/rfad/application/cad.py](../../src/rfad/application/cad.py)
- [src/rfad/application/pcb_projection.py](../../src/rfad/application/pcb_projection.py)

시험:

- [tests/test_cad_projection.py::CadProjectionTests.test_unsupported_coverage_and_transforms_are_explicitly_rejected](../../tests/test_cad_projection.py)

기존 실행/설명 근거:

- [docs/cad_contract.md](../../docs/cad_contract.md)

계약 확인:

- 환경/assembly는 R1 기본 범위를 유지한다. 팬텀/굽힘/배열 전문 물리를 기본 R1 환경으로 추정하지 않는다.

## FN-014

상태: partial. 담당 단계: 3/4/5

직접 입력과 제조업체 적층/소재 선택, 같은 원문 층 Dk/Df/두께 제안, source/hash/결정 사유/수정값 snapshot과 카탈로그 없는 재열기를 구현했다.

남은 범위:

- lot/방향/온도/시험법/불확도를 소비하는 범용 material condition matching과 충돌 결정 UI를 보강해야 한다.
- 지원 자료의 construction/주파수 조건을 사용 목적에 맞춰 선택하는 계약을 물성 모델/target에 연결해야 한다.

코드:

- [src/rfad/application/pcb_selection.py](../../src/rfad/application/pcb_selection.py)
- [src/rfad/catalog/material_selection.py](../../src/rfad/catalog/material_selection.py)
- [src/rfad/catalog/stackup_match.py](../../src/rfad/catalog/stackup_match.py)
- [src/rfad/catalog/stackup_suggestions.py](../../src/rfad/catalog/stackup_suggestions.py)
- [src/rfad/domain/pcb_selection_evidence.py](../../src/rfad/domain/pcb_selection_evidence.py)

시험:

- [tests/test_pcb_selection_service.py](../../tests/test_pcb_selection_service.py)
- [tests/test_stackup_match.py](../../tests/test_stackup_match.py)
- [tests/test_material_model_selection.py](../../tests/test_material_model_selection.py)

기존 실행/설명 근거:

- [runtime_profiles/pcb-selection-gui.json](../../runtime_profiles/pcb-selection-gui.json)
- [runtime_profiles/stackup-suggestions.json](../../runtime_profiles/stackup-suggestions.json)
- [runtime_profiles/capacity-and-followup.json](../../runtime_profiles/capacity-and-followup.json)

계약 확인:

- 원문 조건 보존과 모든 조건의 자동 적합성 판정은 다르다. 원문 미정값과 실제 납품 물성은 유지하며 가정 모델 선택을 별도 결정으로 기록한다.

## FN-015

상태: partial. 담당 단계: 8

등방 상수 및 total tan_delta 유전체 모델, band-center kappa 환산과 소비/미소비 물성을 기록한다. sheet 도체와 PTH 체적 도체의 독립 손실 계산을 제공한다.

남은 범위:

- R1로 선언할 유한 도체/PEC 범위와 전력/손실 정확도 근거를 확정해야 한다.
- RO4350B 국부 방사 도체 변화 2.788446%와 GHz PTH skin depth의 독립 검증이 남는다.

코드:

- [src/rfad/domain/material_models.py](../../src/rfad/domain/material_models.py)
- [src/rfad/application/pcb_projection.py](../../src/rfad/application/pcb_projection.py)
- [src/rfad/adapters/solvers/openems/pcb_absorption.py](../../src/rfad/adapters/solvers/openems/pcb_absorption.py)

시험:

- [tests/test_material_loss_models.py](../../tests/test_material_loss_models.py)
- [tests/test_material_model_selection.py](../../tests/test_material_model_selection.py)
- [tests/test_pcb_loss_convergence.py](../../tests/test_pcb_loss_convergence.py)

기존 실행/설명 근거:

- [runtime_profiles/jlc-ro4350b-exploratory.json](../../runtime_profiles/jlc-ro4350b-exploratory.json)
- [runtime_profiles/pcb-loss-precision.json](../../runtime_profiles/pcb-loss-precision.json)
- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)

계약 확인:

- 총 Df 모델은 독립 conductivity를 소비하지 않으며 원본 null은 유지한다. 일정 kappa를 광대역 일정 tan_delta로 표시하지 않는다. 분산/텐서/거칠기는 R2 검증 전 미지원이다.

## FN-016

상태: partial. 담당 단계: 3/5/8/9

단일 lumped port의 도체 참조, 양의 실수 저항, 방향/대역/기준면 문자열과 명시적 gap을 저장한다. x/y/z 1D gap의 실제 native 접촉과 정규화를 검사한다.

남은 범위:

- 유한 폭/면적 포트, typed 기준면/좌표 변환, source/load와 복소 부하 데이터 보존이 필요하다.
- SMA/connector/launch 포함 모델과 물리 기준면을 별도 객체/지원 profile로 정의하고 검증해야 한다.

코드:

- [src/rfad/domain/design.py](../../src/rfad/domain/design.py)
- [src/rfad/application/pcb_projection.py](../../src/rfad/application/pcb_projection.py)
- [src/rfad/application/pcb_contacts.py](../../src/rfad/application/pcb_contacts.py)
- [src/rfad/application/pcb_results.py](../../src/rfad/application/pcb_results.py)
- [src/rfad/adapters/solvers/openems/pcb_ports.py](../../src/rfad/adapters/solvers/openems/pcb_ports.py)

시험:

- [tests/test_design.py](../../tests/test_design.py)
- [tests/test_pcb_contacts.py](../../tests/test_pcb_contacts.py)
- [tests/test_pcb_ifa.py](../../tests/test_pcb_ifa.py)

기존 실행/설명 근거:

- [runtime_profiles/copper-ifa-worker-wsl.json](../../runtime_profiles/copper-ifa-worker-wsl.json)
- [docs/ro4350b_loss_refinement.md](../../docs/ro4350b_loss_refinement.md)

계약 확인:

- project_port는 횡방향 폭이 0인 1D gap만 지원하고 유한 box를 거절한다. 현재 reference_plane 문자열만으로 서로 다른 기준면 결과의 동등성을 판단하지 않는다.

## FN-017

상태: not_implemented. 담당 단계: 5/7/8

해석 포트의 S11/임피던스/전력은 계산하지만 외부 RLC network graph와 raw EM 결합 서비스는 없다.

남은 범위:

- networks schema/명령과 API-017 network.derive를 구현해야 한다.
- 주파수/Z0/기준면 검사, 회로 손실/조건수, raw 부모 참조와 파생 결과 identity가 필요하다.
- field basis가 없는 경우 정합 후 방사/효율을 미평가로 반환하는 조건을 정해야 한다.

코드:

- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)
- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/pcb_results.py](../../src/rfad/application/pcb_results.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- [docs/pcb_solver_contract.md](../../docs/pcb_solver_contract.md)

계약 확인:

- 단일 포트 native lumped 저항은 사용자 외부 RLC 정합망이 아니다. networks는 비어 있지 않으면 현재 거절한다.

## FN-018

상태: deferred. 담당 단계: R1 이후

R2 정합 구조/부품 합성과 R3 tuner 상태는 현재 제품에 구현하지 않았다.

남은 범위:

- R1 FN-017 기본 외부 회로 및 이후 검증된 부품/탐색 기반을 선행한다.
- 자동 정합 합성/BOM/실장 상태는 후속 단계의 전용 검증과 함께 구현한다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- R1 기본 RLC는 FN-017에서 먼저 구현하며 FN-018 전체를 R1 필수로 끌어오지 않는다.

## FN-019

상태: partial. 담당 단계: 2/8/12/13

capabilities.get는 실제 등록 메서드, CAD/solver 설정 여부와 유한 profile을 반환한다. doctor는 실행파일/패키지/WSL 관측을 수행하며 native/host worker는 고정 manifest와 소스 hash를 검사한다.

남은 범위:

- declared/implemented와 실제 release 검증 근거를 묶은 지원표 및 프로젝트 필요 capability 비교가 없다. tested_envelopes는 빈 배열이다.
- 기능별 license/diagnostic timestamp와 환경 복구 안내를 통합한 제품 진단 화면의 수용이 남는다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/solver_runtime.py](../../src/rfad/application/solver_runtime.py)
- [src/rfad/application/cad_runtime.py](../../src/rfad/application/cad_runtime.py)
- [src/rfad/cli/doctor.py](../../src/rfad/cli/doctor.py)

시험:

- [tests/test_doctor.py::DoctorTests.test_report_does_not_claim_runtime_validation](../../tests/test_doctor.py)
- [tests/test_solver_jobs.py::SolverJobTests.test_runtime_drift_after_planning_requires_replan](../../tests/test_solver_jobs.py)
- [tests/test_wsl_readiness.py::WslReadinessTests.test_failure_is_known_not_started](../../tests/test_wsl_readiness.py)

기존 실행/설명 근거:

- [runtime_profiles/openems-worker-wsl.json](../../runtime_profiles/openems-worker-wsl.json)
- [runtime_profiles/cad-worker-windows-x64.json](../../runtime_profiles/cad-worker-windows-x64.json)
- [runtime_profiles/wsl-development.json](../../runtime_profiles/wsl-development.json)

계약 확인:

- rpc.py의 method status=implemented, runtime_configured, antenna_physics_validated=false와 native 설치 관측은 각각 다른 축이다. 과거 runtime profile은 해당 실행 identity의 증거이며 현재 모든 조합의 합격이 아니다.

## FN-020

상태: partial. 담당 단계: 3/6/8/12

design.validate의 geometry/step/em 입력 검사와 별도 solver.plan이 전체 snapshot, 원본 의미, 실제 runtime, 수치 설정과 유한 자원 추정을 고정한다. 입력 해시/미정 소비 물성/미지원 확장을 검사하고 편집 후에도 원 계획을 유지한다.

남은 범위:

- 현재 PCB 단일 포트와 고정 도파관 이외의 target/scenario/network, 일반 제조 DRC와 종합 경고 수용 정책은 미구현이다.
- resource_estimate는 초기 계산값이며 실제 최고 RAM/디스크와 GUI 포함 admission의 최종 수용이 필요하다.

코드:

- [src/rfad/application/solver_jobs.py](../../src/rfad/application/solver_jobs.py)
- [src/rfad/application/pcb_solver.py](../../src/rfad/application/pcb_solver.py)
- [src/rfad/application/pcb_projection.py](../../src/rfad/application/pcb_projection.py)
- [src/rfad/application/solver.py](../../src/rfad/application/solver.py)

시험:

- [tests/test_solver_jobs.py::SolverJobTests.test_plan_remains_bound_after_edit](../../tests/test_solver_jobs.py)
- [tests/test_solver_jobs.py::SolverJobTests.test_bad_input_hash_and_unprepared_plan_are_rejected](../../tests/test_solver_jobs.py)
- [tests/test_project_studies.py::ProjectStudyTests.test_missing_material_or_stale_revision_is_rejected_atomically](../../tests/test_project_studies.py)
- [tests/test_solver_plan.py::SolverPlanTests.test_estimates_are_labeled_and_do_not_claim_actual_mesh](../../tests/test_solver_plan.py)

기존 실행/설명 근거:

- [runtime_profiles/project-studies.json](../../runtime_profiles/project-studies.json)
- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)

계약 확인:

- design.validate 입력 유효성과 solver.plan의 해당 runtime 준비 가능성은 다르다. AnalysisPlan resource_estimate를 native 준비 통계나 실측 메모리로 표시하지 않는다.
- 소비되지 않는 실제 납품 물성의 null은 보존하며, 소비되는 필수 물성의 누락은 차단한다.

## FN-021

상태: partial. 담당 단계: 3/6/8

solver.prepare를 em_prepare 작업으로 접수한다. PCB 형상/단일 급전/유한 sheet와 PTH, graded mesh, PML, 선택 NF2FF/손실 기록을 실제 XML과 준비 artifact로 봉인하며 별도 PreparedPlan을 만든다. 준비 결과의 투영/연결/관측/정규화를 계획과 대조한다.

남은 범위:

- 지원되지 않는 assembly/외부 CAD 환경과 포트/재료를 위한 solver 투영 및 검증이 남는다.
- 현재 native 준비는 FDTD 전처리를 실행하지 않아 실제 operator coefficient와 native timestep을 그 시점에 확인하지 않는다. operator_coefficients_checked=false를 유지한다.
- GHz PTH 표피 깊이 정확도와 finite-conductivity sheet의 적용 범위는 독립 검증이 필요하다.

코드:

- [src/rfad/application/pcb_mesh.py](../../src/rfad/application/pcb_mesh.py)
- [src/rfad/application/pcb_results.py](../../src/rfad/application/pcb_results.py)
- [src/rfad/adapters/solvers/openems/pcb_mesh.py](../../src/rfad/adapters/solvers/openems/pcb_mesh.py)
- [src/rfad/adapters/solvers/openems/pcb.py](../../src/rfad/adapters/solvers/openems/pcb.py)
- [src/rfad/application/solver_artifacts.py](../../src/rfad/application/solver_artifacts.py)

시험:

- [tests/test_solver_plan.py::SolverPlanTests.test_prepared_plan_has_independent_identity_and_immutable_references](../../tests/test_solver_plan.py)
- [tests/test_solver_jobs.py::SolverJobTests.test_preparation_semantics_must_match_plan_before_sealing](../../tests/test_solver_jobs.py)
- [tests/test_pcb_radiation.py::PcbRadiationTests.test_insufficient_air_is_blocked_before_native_execution](../../tests/test_pcb_radiation.py)
- [tests/test_pcb_mesh.py](../../tests/test_pcb_mesh.py)

기존 실행/설명 근거:

- [runtime_profiles/copper-ifa-worker-wsl.json](../../runtime_profiles/copper-ifa-worker-wsl.json)
- [runtime_profiles/pcb-radiation.json](../../runtime_profiles/pcb-radiation.json)
- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)

계약 확인:

- PreparedPlan의 존재와 native mesh/consumption 검사는 물리 정확도 또는 timestep 사전 확정과 동의어가 아니다.
- compute_profile 없이 기존 1500000점/300초/2스레드, 명시 손실 profile만 2400000/900초 또는 3000000/1800초를 사용한다. 형상/물성 가정은 예산 확대와 별도다.

## FN-022

상태: partial. 담당 단계: 6/12/13

영속 작업 전이, 요청 영수증, 단일 native 슬롯, 별도 host/WSL 프로세스, 종료 확인 전 예약 유지와 결과 봉인을 구현했다. 일반 격자 연구는 취소 후 명시적 재개에서 완료 준비를 재사용하고 새 시도를 기록한다.

남은 범위:

- API-028 worker.events push와 event retention 범위 밖 cursor의 E_CURSOR_EXPIRED/authoritative 재동기화 계약은 미구현이다. 현재 job.status의 cursor 조회와 내부 사건 목록에 의존하며 잘못된 cursor는 E_SCHEMA로 거부한다.
- 범용 study/data_processing/instrument 작업의 공통 scheduler, 우선순위, 전체 프로세스 RAM/디스크 admission, 실측 resource 표시와 모든 fault 수용은 남는다.
- API-029 job.resume의 backend checkpoint 재개는 미지원이며 공개 개별 job reconcile/재시작 UX를 일반화해야 한다.

코드:

- [src/rfad/application/job_state.py](../../src/rfad/application/job_state.py)
- [src/rfad/application/solver_jobs.py](../../src/rfad/application/solver_jobs.py)
- [src/rfad/application/wsl_process.py](../../src/rfad/application/wsl_process.py)
- [src/rfad/application/project_studies.py](../../src/rfad/application/project_studies.py)
- [src/rfad/application/project_study_commands.py](../../src/rfad/application/project_study_commands.py)

시험:

- [tests/test_solver_jobs.py::SolverJobTests.test_unknown_exit_keeps_reservation_through_restart_until_reconcile](../../tests/test_solver_jobs.py)
- [tests/test_solver_jobs.py::SolverJobTests.test_running_cancel_wins_publish_race](../../tests/test_solver_jobs.py)
- [tests/test_solver_jobs.py::SolverJobTests.test_receipt_replay_and_restart_do_not_repeat_work](../../tests/test_solver_jobs.py)
- [tests/test_project_studies.py::ProjectStudyTests.test_prepared_phase_is_reused_after_cancel](../../tests/test_project_studies.py)
- [tests/test_project_studies.py::ProjectStudyTests.test_restart_requires_explicit_resume_and_can_read_without_runtime](../../tests/test_project_studies.py)

기존 실행/설명 근거:

- [runtime_profiles/project-studies.json](../../runtime_profiles/project-studies.json)
- [runtime_profiles/openems-worker-wsl.json](../../runtime_profiles/openems-worker-wsl.json)
- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)

계약 확인:

- solver_profile.resume_supported=false와 study_profile.resume_supported=true는 충돌이 아니다. 전자는 FDTD checkpoint, 후자는 완료 subjob의 명시적 이어 실행을 뜻한다.
- 현재 JobState는 queued부터 시작하고 draft/validating/planned는 영속 작업 상태로 저장하지 않는다. 결과/전송/개정 관계와 JobState를 합치지 않는다.

## FN-023

상태: partial. 담당 단계: 5/8

raw/normalized/provenance를 별도 파일과 hash로 봉인하고 주파수/복소 표본/종료 로그/출력 역할을 검사한다. PCB 단일 포트와 도파관의 확인된 pulse Fourier 규약, 방사 비율과 독립 유전체/sheet/PTH 손실 계산을 제공하며 postprocess_only는 FDTD 자동 재실행을 하지 않는다.

남은 범위:

- 범용 canonical dataset과 다중 포트/여기 basis 배열 및 변환 이력 API는 아직 없다.
- 일반 reciprocal/passivity/validity-mask와 채널별 RMS 변환 지원표를 확장해야 한다. 실제 절대 W 입력 출력은 현재 미지원이다.
- 개별 도체 손실, GHz PTH와 독립 물리 정확도 검증이 미완료다.

코드:

- [src/rfad/application/pcb_results.py](../../src/rfad/application/pcb_results.py)
- [src/rfad/application/solver_artifacts.py](../../src/rfad/application/solver_artifacts.py)
- [src/rfad/adapters/solvers/openems/pcb.py](../../src/rfad/adapters/solvers/openems/pcb.py)
- [src/rfad/adapters/solvers/openems/pcb_absorption.py](../../src/rfad/adapters/solvers/openems/pcb_absorption.py)
- [src/rfad/application/pcb_power.py](../../src/rfad/application/pcb_power.py)

시험:

- [tests/test_solver_jobs.py::SolverJobTests.test_result_semantics_must_match_raw_and_physics_assessment](../../tests/test_solver_jobs.py)
- [tests/test_openems_adapter.py::OpenemsArtifactTests.test_postprocess_missing_raw_never_runs_solver](../../tests/test_openems_adapter.py)
- [tests/test_pcb_radiation.py::PcbRadiationTests.test_field_and_power_tampering_is_rejected](../../tests/test_pcb_radiation.py)
- [tests/test_pcb_power.py](../../tests/test_pcb_power.py)

기존 실행/설명 근거:

- [runtime_profiles/pcb-power-balance.json](../../runtime_profiles/pcb-power-balance.json)
- [runtime_profiles/pcb-loss-precision.json](../../runtime_profiles/pcb-loss-precision.json)
- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)

계약 확인:

- PCB assessment.converged=true는 native 에너지 종료 근거이며 격자/방사/손실 수렴 합격이 아니다. status=computed_unvalidated와 physics_validated=false를 유지한다.
- pulse Fourier 손실/방사 전력 단위 W*s^2와 absolute_power_w=null을 임의의 W 또는 1 W 입력으로 바꾸지 않는다. 최종 국부 방사 도체 2.788446%는 최초 2% 기준 미확립이다.

## FN-024

상태: not_implemented. 담당 단계: 5/7/8

기존 결과 읽기와 S11/임피던스 표시, 동일 raw의 재후처리는 있다. 일반 network.derive의 S/Z/Y 재정규화, 기준면 변경 또는 외부 회로 변환은 없다.

남은 범위:

- 원본 network와 ordered transformation chain, Z0/wave/기준면/port order를 갖춘 공통 dataset 계약과 API-017 구현이 필요하다.
- 특이 변환/대역 불일치/미지원 복소 Z0 및 보간 validity mask의 검사와 독립 벡터 검증이 필요하다.
- 기본 RLC와 변환 이력을 결과 GUI에 연결하고 raw 보존/변경별 무효화를 시험해야 한다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/solver_queries.py](../../src/rfad/application/solver_queries.py)
- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- solver.samples는 표시 DTO이며 공통 network dataset이 아니다. raw 재후처리 성공을 임의 기준면/회로 변환 지원으로 집계하지 않는다.

## FN-025

상태: partial. 담당 단계: 3/5/7/9

단일 포트 S11/dB/VSWR/임피던스, NF2FF 지향성/이득/실현 이득/효율 비율, 독립 전력 수지와 수치 연구 판정을 계산한다. 정의되지 않은 값은 null/상태로 표시하고 1을 넘는 효율을 조용히 보정하지 않는다.

남은 범위:

- API-018 metrics.evaluate와 버전이 있는 target/mask의 대역/방향/scenario 판정이 없다.
- worst location, 실제/보간/미평가 구간, target 변경만의 재평가와 다중 결과 공통 조회가 필요하다.
- 목표 정합과 수렴/실측 정확도의 독립 상태를 일반 GUI와 보고서에 연결해야 한다.

코드:

- [src/rfad/application/pcb_results.py](../../src/rfad/application/pcb_results.py)
- [src/rfad/application/radiation.py](../../src/rfad/application/radiation.py)
- [src/rfad/application/pcb_power.py](../../src/rfad/application/pcb_power.py)
- [src/rfad/application/convergence.py](../../src/rfad/application/convergence.py)
- [src/rfad/application/solver_queries.py](../../src/rfad/application/solver_queries.py)

시험:

- [tests/test_radiation.py::RadiationTests.test_gain_and_realized_gain_have_different_power_references](../../tests/test_radiation.py)
- [tests/test_radiation.py::RadiationTests.test_power_imbalance_is_reported_without_clipping](../../tests/test_radiation.py)
- [tests/test_solver_view.py::SolverViewTests.test_empty_then_completed_latest_and_chart_are_read_only](../../tests/test_solver_view.py)
- [tests/test_convergence.py::ConvergenceComparisonTests.test_endpoint_multiple_and_flat_minima_are_not_established](../../tests/test_convergence.py)

기존 실행/설명 근거:

- [runtime_profiles/pcb-radiation.json](../../runtime_profiles/pcb-radiation.json)
- [runtime_profiles/pcb-power-balance.json](../../runtime_profiles/pcb-power-balance.json)
- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)

계약 확인:

- 고정 수치 연구의 threshold는 사용자 target acceptance가 아니다. loss 합계 또는 전체 전력 잔차의 합격으로 개별 성분/물리 검증을 승격하지 않는다.

## FN-026

상태: partial. 담당 단계: 5/7/8/12

선택 NF2FF의 6면 E/H raw, 세 주파수 이내 복소 E_theta/E_phi와 방사 비율을 저장한다. solver.radiation은 theta 최대5행씩 원본 각도/좌표/단위/snapshot을 반환하며 실제 wxWidgets 2D cut과 phi/지표 선택을 제공한다.

남은 범위:

- 3D 방사 곡면, 일반 근접장/전류 slice 조회와 field 내보내기 GUI가 없다. 현재 3D 창은 CAD 기하 표시다.
- 일반 복소 excitation basis 합성과 arbitrary requested excitation, 전문 편파/축비는 별도 capability/검증이 필요하다.
- 필드/방사 표시 LOD와 물리 적분 표본의 구분, 큰 결과 메모리와 GUI 수용을 확장해야 한다.

코드:

- [src/rfad/adapters/solvers/openems/pcb_radiation.py](../../src/rfad/adapters/solvers/openems/pcb_radiation.py)
- [src/rfad/application/pcb_radiation.py](../../src/rfad/application/pcb_radiation.py)
- [src/rfad/application/radiation_queries.py](../../src/rfad/application/radiation_queries.py)
- [ui/wxwidgets/radiation_dialog.cpp](../../ui/wxwidgets/radiation_dialog.cpp)
- [ui/wxwidgets/radiation_pattern.h](../../ui/wxwidgets/radiation_pattern.h)

시험:

- [tests/test_pcb_radiation.py::PcbRadiationTests.test_pages_reassemble_exact_fields_without_solver](../../tests/test_pcb_radiation.py)
- [tests/test_pcb_radiation.py::PcbRadiationTests.test_missing_or_duplicate_recording_face_never_becomes_complete](../../tests/test_pcb_radiation.py)
- [tests/test_gui_solver_process.py::GuiSolverProcessTests.test_radiation_pages_display_with_snapshot_and_restart](../../tests/test_gui_solver_process.py)
- [tests/radiation_pattern_test.cpp](../../tests/radiation_pattern_test.cpp)

기존 실행/설명 근거:

- [runtime_profiles/pcb-radiation.json](../../runtime_profiles/pcb-radiation.json)
- [runtime_profiles/pcb-radiation-convergence.json](../../runtime_profiles/pcb-radiation-convergence.json)

계약 확인:

- GUI native 시험은 환경 조건부이며 소스에 test가 있다는 사실만으로 이번 실행 통과로 표시하지 않는다. 역사 profile의 실행 조건을 확인한다.
- 복소 필드의 저장과 다중 excitation field basis 합성은 다른 기능이다.

## FN-027

상태: deferred. 담당 단계: R1 이후

사용자 PCB adapter는 단일 포트로 제한하며 full_s_matrix를 미지원으로 표시한다. 고정 2포트 도파관 참조는 일반 MIMO 구현이 아니다.

남은 범위:

- R2 다중포트 복소 network/embedded field basis, termination/excitation 정렬과 TARC/ECC/배열/AoA 검증이 필요하다.

코드:

- [src/rfad/application/pcb_projection.py](../../src/rfad/application/pcb_projection.py)
- [src/rfad/application/solver.py](../../src/rfad/application/solver.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- R1 단일 포트 또는 도파관 S21 참조 성공을 사용자 다중포트/MIMO 지원으로 표시하지 않는다.

## FN-028

상태: deferred. 담당 단계: R1 이후

도파관 참조에는 TE10 S21 위상/군지연의 기대값 검사가 있다. 사용자 UWB antenna pair transfer와 펄스 평가 경로는 없다.

남은 범위:

- R2 pair/direction/polarization/plane 입력, 유효 phase mask/unwrap/창/표본과 pulse fidelity 검증이 필요하다.

코드:

- [src/rfad/adapters/solvers/openems/reference.py](../../src/rfad/adapters/solvers/openems/reference.py)
- [src/rfad/application/solver.py](../../src/rfad/application/solver.py)

시험:

- [tests/test_openems_checker.py::OpenemsCheckerTests.test_analytic_impedance_and_delay_at_known_cutoff_ratio](../../tests/test_openems_checker.py)

기존 실행/설명 근거:

- [runtime_profiles/openems-worker-wsl.json](../../runtime_profiles/openems-worker-wsl.json)

계약 확인:

- 첨부 시험/근거는 도파관 기준군에 한정된다. S11 위상이나 고정 도파관 지연을 UWB 송수신 검증으로 재분류하지 않는다.

## FN-029

상태: deferred. 담당 단계: R1 이후

NFC/LF/HF 전용 coil/load/복소 mu 모델과 평가 API는 없다.

남은 범위:

- R3 loaded/unloaded Q, L/M/k, ferrite/metal과 상대 coil 조건, 적용대역과 전용 독립 물리 검증이 필요하다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- 원호를 그릴 수 있는 기능을 유도 결합 coil 해석 지원으로 사용하지 않는다.

## FN-030

상태: deferred. 담당 단계: R1 이후

RFID chip/strap의 power/state별 복소 부하와 공액 전력전달 평가 API는 없다.

남은 범위:

- R3 chip/strap 모델과 기준면, 유효 operating point 및 radiation/transfer 지표 분리, 전용 검증이 필요하다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- 50 ohm S11을 RFID chip match 또는 read range 결과로 바꾸지 않는다.

## FN-031

상태: partial. 담당 단계: 6/7/8/9

고정 연구 도구가 격자/경계/종료와 방사 기록 거리/각도/격자, 손실의 격자/국부/곡선/종료 축을 비교한다. 실제 입력/정규화/mesh 독립성을 확인하고 거친 실패를 보존한다. 일반 프로젝트 서비스/GUI는 격자 한 축 연구와 공통 방사/손실 설정을 지원한다.

남은 범위:

- 일반 프로젝트에서 경계/시간/기록 거리/각도/국부 축을 생성하고 관리하는 연구 행렬 GUI 및 API-019 공통 수렴 평가 공개 계약이 없다.
- 공진 branch와 복수 minima 추적은 현재 보수적 미확립 처리보다 확장이 필요하다. 자동 적응 주파수는 R2다.
- RO4350B 국부 개별 손실과 GHz PTH 정확도는 미확립이며 원호/IFA의 지원 범위별 독립 근거가 필요하다.

코드:

- [src/rfad/application/convergence.py](../../src/rfad/application/convergence.py)
- [src/rfad/application/radiation_study_guards.py](../../src/rfad/application/radiation_study_guards.py)
- [src/rfad/application/pcb_loss_convergence.py](../../src/rfad/application/pcb_loss_convergence.py)
- [src/rfad/application/project_study_contract.py](../../src/rfad/application/project_study_contract.py)
- [tools/verify_ifa_convergence.py](../../tools/verify_ifa_convergence.py)
- [tools/verify_ro_loss_followup.py](../../tools/verify_ro_loss_followup.py)

시험:

- [tests/test_convergence.py::ConvergenceStudyTests.test_multiple_changed_settings_cannot_be_attributed_to_one_axis](../../tests/test_convergence.py)
- [tests/test_convergence.py::ConvergenceStudyTests.test_final_pair_decides_but_earlier_failed_pair_is_preserved](../../tests/test_convergence.py)
- [tests/test_pcb_loss_convergence.py](../../tests/test_pcb_loss_convergence.py)
- [tests/test_project_studies.py::ProjectStudyTests.test_loss_recording_indices_are_observations_not_changed_physics](../../tests/test_project_studies.py)

기존 실행/설명 근거:

- [runtime_profiles/ifa-convergence-wsl.json](../../runtime_profiles/ifa-convergence-wsl.json)
- [runtime_profiles/pcb-radiation-convergence.json](../../runtime_profiles/pcb-radiation-convergence.json)
- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)

계약 확인:

- 세 수준 중 마지막 쌍의 설정 안정성은 연속체 정확도/독립 solver/실측 증거가 아니다.
- ro4350b-loss-refinement의 mesh는 passed지만 deep local은 not_established다. 서로 다른 생산자/현재 계산기의 identity를 합치지 않는다.

## FN-032

상태: not_implemented. 담당 단계: 3/5/6/9

기존 study.create/start/cancel/resume는 원본 매개변수를 보존하는 격자 연구다. 설계 parameter patch를 가진 일반 후보 스윕은 아직 없다.

남은 범위:

- API-020/021 grid_sweep의 변수 단위/명시 목록/Cartesian 또는 paired 조합 수와 후보 budget 계약을 구현해야 한다.
- baseline snapshot+candidate patch/ID, 실패 후보 보존, raw/derived 재사용 판단과 후보 선택/적용 경로가 필요하다.
- 기존 실행/재개 모듈을 재사용하여 후보 표/진행/비교 GUI를 연결해야 한다.

코드:

- [src/rfad/application/project_study_contract.py](../../src/rfad/application/project_study_contract.py)
- [src/rfad/application/project_studies.py](../../src/rfad/application/project_studies.py)
- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- [tests/test_project_studies.py::ProjectStudyTests.test_parameter_binding_and_unused_missing_materials_are_preserved](../../tests/test_project_studies.py)

기존 실행/설명 근거:

- [runtime_profiles/project-studies.json](../../runtime_profiles/project-studies.json)

계약 확인:

- 해당 시험과 실행 근거는 원본 보존형 수치 격자 연구의 재사용 기반이며 FN-032 기능의 합격 증거가 아니다. study_profile.scope는 mesh_axis_with_optional_radiation_and_loss다.

## FN-033

상태: deferred. 담당 단계: R1 이후

자동 목적함수 탐색, Pareto 및 shape_opt coordinator는 없다.

남은 범위:

- R2 제약/목적/seed/budget과 후보 이력, 알고리즘 adapter와 최종 독립 재검증이 필요하다.

코드:

- [src/rfad/application/project_study_contract.py](../../src/rfad/application/project_study_contract.py)
- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- optimization_studies는 의미 구현이 없는 예약 컬렉션이며 현재 일반 격자 연구를 자동 최적화로 표시하지 않는다.

## FN-034

상태: deferred. 담당 단계: R1 이후

민감도/공차 분포/상관과 통계 수율 실행 또는 판정 API는 없다.

남은 범위:

- R2 차원/분포/PSD 검사, seed와 sampling, 실패/unknown을 포함한 분모, 명시 신뢰구간과 후보 추적이 필요하다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- 제조사 자료의 범위/미정값을 근거 없는 통계 분포나 생산 수율로 바꾸지 않는다.

## FN-035

상태: deferred. 담당 단계: R1 이후

공개 서비스에 대한 MCP 전달은 있으나 대리모델 학습, AI 형상 제안 또는 inverse_design 실행기는 없다.

남은 범위:

- R3 학습/독립 검증/OOD 범위, typed candidate patch와 기하/제조 제약, 실제 EM 재검증이 필요하다.

코드:

- [src/rfad/application/mcp.py](../../src/rfad/application/mcp.py)
- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- [tests/test_mcp.py::McpTests.test_discovery_and_mutation_replay_use_the_same_receipt](../../tests/test_mcp.py)

기존 실행/설명 근거:

- [runtime_profiles/capacity-and-followup.json](../../runtime_profiles/capacity-and-followup.json)

계약 확인:

- MCP 시험은 API 접근/영수증 재생의 근거이며 AI 설계/최적화의 구현 또는 검증 증거가 아니다.

## FN-036

상태: not_implemented. 담당 단계: 5/7/11

Touchstone/측정 CSV parser와 import.preview/import.commit 측정 경로가 없다. measurement_sets는 현재 비어 있어야 하는 예약 컬렉션이다.

남은 범위:

- 주파수/복소 encoding/단위/Z0/port order 검사와 누락 metadata preview, 원본 파일 봉인 및 measurement dataset 저장이 필요하다.
- sample/assembly revision, 교정/환경/시각/미정 조건과 출처를 유지하는 명령과 GUI가 필요하다.
- 잘못된 단위/중복 주파수/부분 파일/자료 변경을 거절하는 parser와 저장 계약 시험이 필요하다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/domain/project.py](../../src/rfad/domain/project.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- 승인 API의 project.measurements target과 현재 예약 measurement_sets 명칭은 차기 schema/API 매핑에서 명시적으로 해결해야 한다. 현재 구현된 저장 의미로 가정하지 않는다.
- 자료가 없으면 실측값을 생성하지 않으며 fixture 입력 시험과 실제 측정 검증을 구분한다.

## FN-037

상태: not_implemented. 담당 단계: 5/7/11

측정의 교정/fixture/기준면 이력, measurement.align과 계산/측정 complex residual 비교 경로는 없다.

남은 범위:

- 동일 기준면/조립/환경/port 조건 비교, 원본과 변환 결과의 분리 및 supported correction chain이 필요하다.
- 겹치는 주파수 대역, 보간/invalid mask와 불확도 근거를 기록하는 비교 화면/보고서를 구현해야 한다.
- 실제 시료/교정/케이블/반복성 자료가 확보된 범위에서 수용 판정을 수행해야 한다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/pcb_results.py](../../src/rfad/application/pcb_results.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- R1 초기 SMA 기준면 비교를 고급 R2 de-embedding 구현까지 미루지 않는다. 현재 이상적 안테나 gap 결과를 SMA 실측과 같은 기준면으로 표시하지 않는다.

## FN-038

상태: deferred. 담당 단계: R1 이후

instrument_acquisition과 VNA 직접 연결 adapter는 없다.

남은 범위:

- R3 장비 식별/설정/실제 교정 상태와 부분 취득/취소를 다루는 전용 adapter 및 검증이 필요하다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/solver_requests.py](../../src/rfad/application/solver_requests.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- 장비 직접 연결은 R1 측정 파일 입력의 선행이 아니다. 장비 작업에 EM PreparedPlan을 요구하지 않는 별도 task kind를 구현해야 한다.

## FN-039

상태: deferred. 담당 단계: R1 이후

실측 기반 fitting/model_calibration과 학습/독립 검증 분리는 아직 구현하지 않았다.

남은 범위:

- R2 변수 범위/식별성/상관 검사, 원설계 보존 후보와 train/test residual, 독립 시료/조건 검증이 필요하다.

코드:

- [src/rfad/application/project_study_contract.py](../../src/rfad/application/project_study_contract.py)
- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- 해당 제품 기능의 근거 없음.

계약 확인:

- 카탈로그 값 선택이나 명시적 탐색 근사 모델은 실측 fitting의 구현 또는 검증 근거가 아니다.

## FN-040

상태: not_implemented. 담당 단계: 4/10

화면 캔버스와 수치 그래프 도구는 있으나 연관 기술 도면 PDF/SVG/DXF 제품 출력이 없다.

남은 범위:

- snapshot에서 도면 뷰/연관 치수/축척/검정선을 생성하고 drawing/fabrication_geometry 채널을 분리해야 한다.
- 단위/양자화/원호 chord tolerance와 FN-043 reader 검수를 구현해야 한다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/canvas.py](../../src/rfad/application/canvas.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- [docs/canvas_contract.md](../../docs/canvas_contract.md)

계약 확인:

- 검증 그래프를 SVG로 저장하는 개발 도구는 치수 도면/FN-040 출력 기능이 아니다.

## FN-041

상태: partial. 담당 단계: 10

AP242 고체 STEP, 원본 snapshot/재료/net/port sidecar, stable body map과 파일 hash를 생성하고 OCP reader로 다시 확인한다.

남은 범위:

- 실제 수신 CAD/version별 재열기, 선택/측정/조립 검수가 남는다.
- mask/표면층/외부 부품/슬롯 등 지원 profile 확장과 포함/생략 정책의 검수가 필요하다.

코드:

- [src/rfad/adapters/cad/native.py](../../src/rfad/adapters/cad/native.py)
- [src/rfad/adapters/cad/step_io.py](../../src/rfad/adapters/cad/step_io.py)
- [src/rfad/application/cad_artifacts.py](../../src/rfad/application/cad_artifacts.py)
- [src/rfad/application/cad.py](../../src/rfad/application/cad.py)

시험:

- [tests/test_cad_native.py](../../tests/test_cad_native.py)
- [tests/test_cad_copper_features.py](../../tests/test_cad_copper_features.py)
- [tests/test_gui_cad_process.py](../../tests/test_gui_cad_process.py)

기존 실행/설명 근거:

- [runtime_profiles/cad-worker-windows-x64.json](../../runtime_profiles/cad-worker-windows-x64.json)
- [runtime_profiles/gui-cad-windows-x64.json](../../runtime_profiles/gui-cad-windows-x64.json)

계약 확인:

- 현재 status=generated_unverified, kernel_independent=false다. 동일 OCCT reader와 독립 산술 기대값 통과를 수신 CAD 또는 제조 검증으로 승격하지 않는다.

## FN-042

상태: not_implemented. 담당 단계: 10

PCB 기하/net/적층과 STEP 출력 기반은 있으나 KiCad/Gerber/Excellon/Job 제조 교환 경로는 없다.

남은 범위:

- 선언한 보드/footprint/CAM profile과 단위/층/net/PTH/NPTH/slot mapping 및 writer/reader가 필요하다.
- zone refill과 최소 gap/thermal/clearance 변화를 확인하는 DRC/roundtrip을 연결해야 한다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/domain/design.py](../../src/rfad/domain/design.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- [docs/cad_contract.md](../../docs/cad_contract.md)

계약 확인:

- R1 기본 Job/DRC와 R2 정합 BOM/실장 변형, R3 추가 형식은 별도 범위다. 제조 미정 입력이 있는 파일을 verified_profile로 발행하지 않는다.

## FN-043

상태: partial. 담당 단계: 10

STEP의 schema/단위/이름/solid/bbox/중심/체적/단면/홀/두께와 중첩을 같은 kernel reader로 검사한다.

남은 범위:

- 독립 수신 reader 및 2D/CAM 경로, critical gap/연결/net topology와 bounded boundary 차이의 검사가 필요하다.
- 공개 API-025 export.verify와 reader/version/tolerance provenance별 상태를 제공해야 한다.

코드:

- [src/rfad/adapters/cad/step_io.py](../../src/rfad/adapters/cad/step_io.py)
- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)

시험:

- [tests/test_cad_native.py](../../tests/test_cad_native.py)
- [tests/test_cad_copper_features.py](../../tests/test_cad_copper_features.py)

기존 실행/설명 근거:

- [runtime_profiles/cad-worker-windows-x64.json](../../runtime_profiles/cad-worker-windows-x64.json)

계약 확인:

- step_io 비교는 passed_same_kernel이며 not_evaluated에 독립 kernel/제조 DRC/전체 의도 net/슬롯/assembly가 명시돼 있다.

## FN-044

상태: partial. 담당 단계: 7/8/11/12

도파관/PCB/방사/전력/손실 연구의 machine-readable 판정과 runtime evidence가 있고 실행/미확립/실측 미검증을 구분한다.

남은 범위:

- 사용자 프로젝트의 요구-FN-VT evidence join과 통합 검토 보고서/PDF 생성, source promotion을 구현해야 한다.
- 목표/측정/출력 변경에 따라 파생 보고서와 검증 범위를 갱신하는 제품 계약이 필요하다.

코드:

- [src/rfad/application/convergence.py](../../src/rfad/application/convergence.py)
- [src/rfad/application/pcb_loss_convergence.py](../../src/rfad/application/pcb_loss_convergence.py)
- [src/rfad/application/project_study_results.py](../../src/rfad/application/project_study_results.py)
- [tools/verify_ro_loss_followup.py](../../tools/verify_ro_loss_followup.py)

시험:

- [tests/test_convergence.py](../../tests/test_convergence.py)
- [tests/test_pcb_loss_convergence.py](../../tests/test_pcb_loss_convergence.py)
- [tests/test_project_studies.py](../../tests/test_project_studies.py)

기존 실행/설명 근거:

- [runtime_profiles/ro4350b-loss-refinement.json](../../runtime_profiles/ro4350b-loss-refinement.json)
- [runtime_profiles/project-studies.json](../../runtime_profiles/project-studies.json)

계약 확인:

- 현재 개발자가 작성한 runtime_profiles와 고정 CLI 검증 보고서는 범용 제품 보고서/인증 승격 기능이 아니다. 미확립 손실/제작/측정 unknown은 그대로 추적한다.

## FN-045

상태: not_implemented. 담당 단계: 12/13

workspace journal/snapshot/결과 봉인은 있으나 선택 프로젝트를 이동 가능한 archive로 묶고 새 환경에서 복구하는 API-026은 없다.

남은 범위:

- snapshot 기준 참조 closure, 선택 raw 포함/제외, 라이선스/비밀/경로/용량 검사와 패키지 원자 발행이 필요하다.
- safe import/손상/누락/외부 자료 권리 처리와 새 workspace 재열기 검수가 필요하다.

코드:

- [src/rfad/storage/journal.py](../../src/rfad/storage/journal.py)
- [src/rfad/storage/sealed_files.py](../../src/rfad/storage/sealed_files.py)
- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [tools/build_internal_bundle.py](../../tools/build_internal_bundle.py)

시험:

- 해당 제품 기능의 근거 없음.

기존 실행/설명 근거:

- [runtime_profiles/internal-validation-bundle.json](../../runtime_profiles/internal-validation-bundle.json)
- [docs/project_persistence.md](../../docs/project_persistence.md)

계약 확인:

- build_internal_bundle은 src/tools/ui/tests 등 개발 배포 묶음이며 사용자 프로젝트를 명시적으로 제외한다. 이를 FN-045 프로젝트 archive 완료로 계산하지 않는다.

## FN-046

상태: partial. 담당 단계: 4/6/7/10/11/12/13

C++ wxWidgets GUI와 stdio CLI/MCP가 같은 ProjectService, 명령/영수증/worker를 사용한다. host CAD와 local WSL2 solver를 격리하고 한국어/공백 경로 및 결과 재열기/취소를 개별 시험했다. Qt 없는 native build와 내부 검증 묶음 도구가 있다.

남은 범위:

- 실제 F1/F2 조작에서 60/30 fps, 전체 프로세스 메모리/입력 지연과 DPI/도킹/GPU/WSL 복구의 R1 수용이 남는다.
- 명시적 지원표/설치 진단, 새 PC 오프라인 설치/패키지/라이선스, 전체 GUI-CLI workflow와 접근성 검증이 필요하다.
- 특정 EDA의 단위/좌표/net/port 의미 변환과 실제 MCP 상호 운용은 미완료다. Linux GUI와 remote/HPC는 후속이다.

코드:

- [src/rfad/application/rpc.py](../../src/rfad/application/rpc.py)
- [src/rfad/application/mcp.py](../../src/rfad/application/mcp.py)
- [src/rfad/application/wsl_process.py](../../src/rfad/application/wsl_process.py)
- [ui/wxwidgets/service_client.cpp](../../ui/wxwidgets/service_client.cpp)
- [tools/mcp_stdio.py](../../tools/mcp_stdio.py)
- [tools/build_internal_bundle.py](../../tools/build_internal_bundle.py)

시험:

- [tests/test_mcp.py::McpTests.test_real_stdio_discovery_emits_only_protocol](../../tests/test_mcp.py)
- [tests/test_mcp.py::McpTests.test_discovery_and_mutation_replay_use_the_same_receipt](../../tests/test_mcp.py)
- [tests/test_gui_solver_process.py::GuiSolverProcessTests.test_circle_arc_native_results_save_cancel_and_restart](../../tests/test_gui_solver_process.py)
- [tests/test_wsl_readiness.py::WslReadinessTests.test_control_can_cancel_a_real_silent_launcher](../../tests/test_wsl_readiness.py)

기존 실행/설명 근거:

- [runtime_profiles/capacity-and-followup.json](../../runtime_profiles/capacity-and-followup.json)
- [runtime_profiles/pcb-radiation.json](../../runtime_profiles/pcb-radiation.json)
- [runtime_profiles/project-studies.json](../../runtime_profiles/project-studies.json)
- [runtime_profiles/internal-validation-bundle.json](../../runtime_profiles/internal-validation-bundle.json)

계약 확인:

- 조건부 GUI/native test의 현재 스킵을 통과로 집계하지 않는다. 합성 renderer 비용은 실제 앱 FPS/메모리 수용과 다르다.
- GUI 현대화는 공통 서비스/표시 DTO를 소비하는 View/표시모델 책임이며 canonical/worker 계약에 toolkit 또는 테마 값을 넣지 않는다.
