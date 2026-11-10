# 2D 표시와 직접 편집 계약

기록일: 2026-11-10 KST

`rfad.canvas/0.1`은 승인된 [05 화면 설계](../../01_Docs/05_RFAD_화면과_사용자_경험_설계.md)의 2D 편집을 기존 프로젝트 명령에 연결하는 개발용 확장이다. `canvas.get`과 `canvas.apply`를 capabilities에 공개하며 정식 API 번호를 추가하지 않는다. GUI는 표시 DTO와 안정 ID를 사용하고 SI 변환, 매개변수 참조 해석, 검증과 원본 변경은 서비스가 소유한다.

## 표시 조회

`canvas.get`의 params는 contract_version/context/input이다. context에는 project_id, input에는 expected_revision만 전달한다. 다른 개정이면 E_CONFLICT를 반환한다. 조회는 원본, receipt와 undo/redo 이력을 바꾸지 않는다.

응답 필드는 다음과 같다.

| 필드 | 의미 |
| --- | --- |
| profile/project_id/revision_id | 표시 계약과 원본 식별 |
| unit/angle_unit | 각각 mm/deg로 고정 |
| ranges | 표시 상한/하한: max_coordinate_mm, min_line_length_mm, min_abs_sweep_deg |
| board | 기판이 없으면 null. 사각형은 기존 id/width/height, 원형은 id/kind: circle/center/radius. 미정 또는 표시할 수 없는 치수는 null |
| layers | id/label/role의 층 목록. 실제 order 순서 유지 |
| shapes | 지원하는 선/원호/영역/패드/비아의 2D 표시 수량 |
| omissions | 표시하지 못한 객체 id와 message |

선과 원호의 공통 필드는 id/kind/label/layer_id/role/width/movable이다. 선의 kind는 line_path이며 start/end를 `[x, y]` mm로 전달한다. 원호의 kind는 arc_path이며 center/radius/start_angle/sweep_angle을 mm/deg로 전달한다. 양의 sweep은 오른손 x/y 좌표계에서 반시계, 음수는 시계 방향이다. 원본의 부호와 시작 각도를 임의 정규화하지 않는다. 각도 0은 +x 방향이다.

planar_region은 outer/holes 좌표 목록을 전달한다. pad는 pad_shape/center/size/rotation을 전달하고 via는 center, finished_hole_diameter/plating_thickness/tool_hole_diameter 및 span_layer_ids를 전달한다. 비아의 미정 치수는 null이며 연결 범위의 conductor 층만 span_layer_ids에 포함한다. 이 세 종류에는 선폭 width를 요구하지 않는다. 구멍은 면 채움/선택 대상에서 제외하며 치수가 미정인 비아는 중심 표식으로 표시한다.

좌표/폭/반지름/각도의 매개변수 참조는 현재 개정의 계산된 Quantity로 해석한다. 원본 binding은 바꾸지 않는다. 표시할 치수가 없거나 mm/deg 환산이 float64 범위를 벗어나면 해당 shape를 생략하고 omissions에 원인을 기록한다. 0이나 기본 치수를 만들어 대신 표시하지 않는다. 기판 치수는 width/height를 각각 평가하므로 한쪽만 null일 수 있다. omissions는 표시 차단 근거이며 제조/접속/해석 검증 보고서가 아니다.

이 표시 profile은 좌표 절댓값과 치수를 최대 1e9 mm까지 표시한다. 선 길이는 1e-9 mm보다 크고 원호 회전량 절댓값은 1e-10 deg보다 커야 한다. 폭/반지름에는 기존 양수 조건 외의 최소 표시 치수를 추가하지 않는다. 범위를 벗어난 객체만 생략하고 다른 정상 객체는 유지하며, 기판의 범위 밖 치수만 null로 돌려준다. ranges에 이 기준을 명시한다. 이는 화면 표시의 한계이며 원본 저장이나 도메인 편집 명령의 물리값 범위를 좁히지 않는다. 생략된 값도 속성 편집과 저장에서 그대로 보존한다.

movable은 선의 start/end 또는 원호의 center가 모두 수치가 있는 리터럴일 때만 true다. 좌표 매개변수 참조가 있는 형상은 표시할 수 있어도 직접 이동은 제한한다. 폭/반지름/각도의 참조는 평행 이동과 무관하므로 유지한다.

전체 원본, 적층의 실제 물성, CAD B-rep나 solver 배열은 DTO에 넣지 않는다. 응답은 UTF-8 JSON 60 KiB 상한을 넘으면 E_RESOURCE를 반환한다. 페이지 분할과 대형 장면 LOD는 후속이다.

## 직접 편집 명령

`canvas.apply`는 기존 mutation envelope의 request_key/request_key_epoch와 project_id context를 요구한다. input은 expected_revision/command_id/operation/values다. values는 작업별로 다음 필드만 허용한다.

| operation | values | 기존 도메인 명령 |
| --- | --- | --- |
| create_board | id, width_mm, height_mm | board.set |
| create_circular_board | id, center_x_mm, center_y_mm, radius_mm | board.set |
| create_layer | id, name | layer.set |
| create_dielectric_layer | id, name | layer.set |
| create_line | id, layer_id, width_mm, start, end | geometry.set |
| create_arc | id, layer_id, width_mm, center, radius_mm, start_angle_deg, sweep_angle_deg | geometry.set |
| create_polygon | id, layer_id, outer, holes | geometry.set |
| create_pad | id, layer_id, pad_shape, center, width_mm, height_mm, rotation_deg | geometry.set |
| create_via | id, layer_id, end_layer_id, center, finished_hole_diameter_mm, plating_thickness_mm, tool_hole_diameter_mm, pad_ids | geometry.set |
| translate | id, dx_mm, dy_mm | geometry.set |
| remove | id | geometry.remove |

start/end/center는 유한 숫자 2개의 목록이다. 숫자는 int/float만 받으며 bool, 문자열, NaN/Infinity를 숫자로 해석하지 않는다. 서버가 단위를 SI로 한 번 변환한다. 0으로 소실되는 변환도 거부한다. UUID는 정규 문자열이어야 한다.

생성 ID가 기판, 매개변수, 층, 재료, 네트, 형상, 포트, 현재 프로젝트/개정/좌표계와 충돌하면 E_CONFLICT로 거부한다. 기판이 이미 있을 때 create_board/create_circular_board로 덮어쓰지 않는다. 기존 기판의 크기와 원형의 중심/반지름은 속성 편집으로 변경한다. 외형과 구리 패턴은 독립이며 원형 기판 생성으로 접지면이나 원호 패턴을 자동 생성하지 않는다. 원형의 저장/CAD 경계는 [원형 기판](circular_board.md)을 따른다.

기판과 각 층은 각각 독립 명령이며 undo도 별개다. create_layer는 conductor, create_dielectric_layer는 dielectric 역할과 다음 order를 사용한다. 두 경우 모두 z_min/두께는 명시적 missing, material_id는 null이다. 두께 표시 단위는 도체 um, 유전체 mm이며 실제 층 위치나 35 um/FR4 같은 물리값을 자동 확정하지 않는다. 사용자는 적층 속성에서 실제 값을 입력해야 한다. 유전체 층 생성은 CAD의 명시적 적층 입력을 구성하는 경로이며 층이 추가되었다고 STEP/EM 준비가 끝나는 것은 아니다.

새 선/원호는 기판의 좌표계와 선택한 conductor 층에 속한다. role은 conductor, net/material/source 참조는 null이며 include_in_em/include_in_export는 true다. 이 포함 표시는 해석 준비 완료나 실제 도체 접속을 뜻하지 않는다. 급전/접지 역할과 net 등은 기존 속성 편집으로 지정한다.

translate는 선/원호와 영역/패드/비아를 처리한다. 영역은 outer와 모든 holes를 함께 이동한다. 좌표가 parameter 참조 또는 미정이면 E_CONFLICT로 차단하여 binding을 리터럴로 바꾸지 않는다. 리터럴 좌표에만 SI 이동량을 더하며 폭/반지름/각도/드릴/도금과 그 참조는 그대로 유지한다. 0 이동이나 현재 float64 좌표에서 표현할 수 없는 작은 이동량도 성공으로 처리하지 않는다. remove도 기존 geometry만 받으며 포트/비아 등이 참조하는 형상 삭제는 기존 도메인 검증에서 거부한다. 생성 세부와 미정 드릴 치수는 [도체 확장](copper_features.md)을 따른다.

성공 응답은 기존 명령과 같은 project_id/new_revision/revision_hash/changed_ids/invalidation_set/history다. 새 revision과 command, 이력 커서, receipt를 같은 journal transaction으로 게시한다. 동일 요청 재전송은 같은 결과를 반환하고 저장 후 재시작에서도 영속 undo/redo를 사용한다. 실패하거나 stale 요청이면 원본과 접수/이력을 유지한다. 상세 이력 규칙은 [선택 속성 편집 계약](editor_contract.md)을 따른다.

## 범위와 검증

서비스 시험은 실제 journal의 생성/이동/삭제, 재전송과 재시작, undo/redo, 기판/층의 별도 이력, 미정 물성 보존, 좌표 참조 해석 및 직접 이동 차단, 폭/반지름 참조 보존, signed sweep, ID 충돌, stale 및 잘못된 입력/게시 실패의 원자성, 표시 범위와 float64 이동 정밀도를 확인한다. 실제 stdio 프로세스 시험은 저장/스냅샷 및 서비스 재시작까지 연결한다.

표시 DTO는 기판 x/y 평면의 의미 모델이다. 실제 구리 Boolean, 3D 적층, 형상 밖 경계/제조 공차, 접촉/단락 판정, 포트 급전 위치 검증과 solver 실행은 포함하지 않는다. 모든 치수가 그려져도 CAD/제조/EM 합격을 주장하지 않는다. 마우스 드래그/줌/선택의 GUI 검증과 60/30 fps 수용은 이 서비스 계약과 별도다.

GUI의 3D 탭은 이 2D DTO를 임의 두께로 extrude하지 않는다. 별도 CAD 작업의 고정 snapshot에서 생성한 표시 mesh를 읽으며 실제 도체/유전체 두께와 원본 UUID를 유지한다. 현재 2D 개정과 3D 입력 개정이 다르면 이전 형상임을 명시한다. 유전체 입력, STEP 버튼, 작업 취소와 3D 표시의 계약은 [CAD/STEP](cad_contract.md)을 따른다.
