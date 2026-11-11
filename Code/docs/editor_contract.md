# 선택 속성 편집과 실행 취소

기록일: 2026-11-10 KST

`rfad.editor/0.1`은 승인된 서비스 중심 모델을 연결하는 개발용 확장 profile이다. `editor.get`, `editor.apply`, `project.undo`, `project.redo`를 capabilities에 확장으로 공개하며 정식 API 번호를 새로 부여하지 않는다. 현재 프로젝트 쓰기는 `rfad.project/0.3`이며 0.1/0.2 원본 읽기 호환을 유지한다. 기존 선택 속성의 의미는 유지하고, 0.3의 [목표 입력 API](target_contract.md)는 목표 편집 GUI와 별도 범위다.

## DTO 조회

`editor.get`은 읽기 전용이다. params는 contract_version/context/input이며 context에는 project_id, input에는 expected_revision과 선택적인 selection을 전달한다. selection은 `{"kind":"parameter","id":"UUID"}` 형태다. 선택을 생략하면 프로젝트 속성을 반환한다. 존재하지 않는 객체, 잘못된 종류와 stale revision은 오류다. 조회로 revision이나 명령 접수 이력을 바꾸지 않는다.

응답은 profile/project_id/revision_id/saved_revision, metadata의 이름/설명, history, items와 selection이다. items는 kind/id/label만 포함하고 selection은 해당 객체의 fields만 포함한다. 전체 원본, 모든 매개변수 계산 캐시, CAD 형상과 solver 배열을 반복 전송하지 않는다. 현재 DTO는 UTF-8 JSON 60 KiB 상한을 넘으면 요청 ID를 보존한 E_RESOURCE를 반환한다. 다각형 좌표 표의 길이 매개변수 선택지는 top-level coordinate_choices에서 한 번만 전달한다. 대형 목록 paging은 후속이다.

각 field는 key/label/editor/value/choices/readonly를 가진다. editor는 text/choice/bool/bindings/coordinate_table/multichoice다. choice는 전송 value와 표시 label을 구분하며 이름을 객체 참조 키로 사용하지 않는다. bindings는 표현식 변수 이름과 안정 UUID를 연결하는 사전이고 choices는 참조 가능한 매개변수의 ID와 이름이다. coordinate_table은 outer 또는 holes.N의 고정 행 목록이며 각 x/y 셀은 mode/value/parameter_id/unit 문자열을 가진다. 읽기 전용 unit은 보통 mm, 환산 overflow 시 m다. 변경하지 않은 셀의 원본 Quantity와 결합을 보존한다. multichoice는 중복 없는 pad UUID 목록이며 잘못된 참조는 거절한다.

선택지의 label과 읽기 전용 상태/형식/모델 표시는 한국어 사용자 용어를 사용한다. 읽기 전용 필드의 선택적 display_value는 화면 표시용이고, value 및 choices의 value는 기존 API 원문과 안정 ID를 유지한다. GUI는 display_value를 명령 입력으로 보내지 않는다. id/frame_id에는 advanced=true를 표시해 상세 정보로 분리할 수 있다. 일부 필드의 선택적 help는 입력 방식, 단위 변경, 변수 결합과 미정값의 의미를 설명한다. 이 표시 메타데이터는 편집 권한이나 원본 저장 의미를 바꾸지 않는다.

현재 종류는 project, parameter, board, material, layer, net, geometry, port다. new_parameter/new_material/new_net/new_port와 새 UUID로 생성 폼을 조회한다. 물성/유효 대역/급전 저항과 위치는 미정이며 조회만으로 원본을 생성하지 않는다. 새 포트는 기판과 두 개 이상의 도체 형상이 필요하고 양극/기준 도체를 사용자가 선택해야 한다. 현재 생성 UI는 단일 포트만 지원한다. 생성 적용 후 같은 ID의 실제 종류로 조회한다. 기판/적층/선/원호 생성과 형상 삭제는 [2D 계약](canvas_contract.md)을 따른다.

## 값 편집

`editor.apply`는 기존 mutation envelope의 request_key/request_key_epoch를 요구한다. input은 expected_revision/command_id/selection/values다. values는 변경할 필드 사전이며 명령 적용은 같은 서비스의 도메인 set 명령으로 변환된다. 성공 응답은 project_id/new_revision/revision_hash/changed_ids/invalidation_set/history다. GUI는 성공한 새 revision으로 DTO를 다시 조회한다. 오류 뒤 입력을 임의로 원본에 적용하지 않는다.

프로젝트 이름/설명은 `metadata.set` 한 명령으로 적용하여 둘 중 하나만 게시되는 상태를 만들지 않는다. 이전 metadata.rename/metadata.describe도 계속 지원한다.

- 매개변수는 name, mode, value, unit, dimension, expression, bindings를 제공한다. mode는 value/expression/missing이다. 표현식 파싱, 단위, 차원, 변수/UUID 결합과 의존 재계산은 서비스에서 수행한다.
- 일반 설계 수량은 `outline.width.mode`처럼 경로별 mode/value/unit/parameter_id를 제공한다. mode는 value/missing/parameter다. 매개변수 참조 선택지는 해당 물리 차원으로 제한한다.
- unit만 바꾸면 원본 SI 값과 입력 상태/출처를 유지하고 표시 단위만 바꾼다. value와 unit을 함께 바꾸면 새 숫자와 명시적 단위를 사용한다. 명시적으로 바꾼 숫자는 user_entered다.
- 이름처럼 수량과 무관한 속성 변경은 Quantity의 SI/status/source_refs와 표현식 원문/UUID 결합을 그대로 보존한다. 미정값을 0 또는 FR4 대표값으로 대체하지 않는다.
- 현재 mode에서 사용하지 않는 필드의 변경은 오류다. 예를 들어 value 모드에서 expression을 바꾸거나 parameter 모드의 수량에서 숫자를 바꾸는 요청을 성공으로 처리하지 않는다.
- 객체 ID/형식/좌표계/고정 모델과 출처/가정 목록은 현재 읽기 전용이다. 알 수 없는 필드와 readonly 변경은 거부한다. 출처/가정 기록 편집 전용 UI는 후속이다.
- 표시 단위로의 환산이 float64 표현 범위를 벗어나면 원본을 변경하지 않고 SI 표시와 안내를 제공한다. 이름 변경 등 다른 속성 편집은 계속 가능하다.

기존 객체의 기판 치수와 원형 중심/반지름, 재료 물성/유효 대역, 적층 역할/순서/위치/두께/재료, 네트 이름, 선/원호의 좌표/폭/역할/참조와 포함 여부, 포트의 도체/저항/기준면/방향/대역과 excitation_box 시작/끝 3D 좌표를 편집한다. 방향 벡터는 현재 성분을 정수로 저장했어도 유한 실수 입력을 허용한다. 기존 포트에 excitation_box가 없어도 조회로 원본에 추가하지 않으며 좌표 입력 시에만 명시적으로 생성한다. 도메인 저장 가능성과 특정 solver의 급전 지원은 별개다. 실제 도메인 검증에서 겹친 적층, 잘못된 반지름, 순환 수식, 참조 오류 등을 차단한다. 오류에는 field_path 또는 기존 도메인 진단 위치를 유지한다.

## 영속 실행 취소와 다시 실행

`project.undo`와 `project.redo`는 input에 expected_revision/command_id를 받고 같은 request_key/epoch 계약을 사용한다. 명령, revision 파일, current 참조, 이력 커서와 receipt를 journal 한 transaction으로 게시한다. 원래 revision 포인터로 돌아가지 않고 역명령 또는 원명령을 현재 원본에 검증 적용한 새 revision을 만든다. 기존 스냅샷과 저장 기준점은 바꾸지 않는다.

프로젝트별 이력은 undo/redo를 합쳐 최근 128개의 원명령 ID까지 보관한다. 각 실행 취소/다시 실행도 기존 명령 이력 2048개 및 workspace 8 MiB 상한에 포함된다. 이 상한에 도달하면 실패하며 기존 상태는 보존한다. 이력에서 오래된 ID를 제외해도 기존 revision 파일이나 명령 근거를 자동 삭제하지 않는다. GC는 후속이다.

새 편집은 redo 분기를 비운다. 잘못된 편집, stale 요청, 게시 실패는 undo/redo 상태와 접수 이력을 바꾸지 않는다. 같은 요청 키 재전송은 기존 결과를 반환하므로 undo가 두 번 적용되지 않는다. 서비스 재시작 후에도 커서를 유지한다. 기존 profile에서 history가 없는 workspace는 현재 revision의 선형 명령 연결을 역추적해 최근 128개를 복원하며 원본과 스냅샷 바이트를 다시 쓰지 않는다.

이력은 head_revision을 현재 revision과 함께 기록한다. 구버전 앱 등으로 현재 원본과 이력 head가 어긋나면 조회와 추가 편집/실행 취소를 E_CONFLICT로 차단하며 조용히 이력을 다시 만들지 않는다. history 자체가 없는 기존 profile만 선형 이력을 복원한다. head 키 없이 history만 있는 미출시 편집기 실험 workspace는 E_VERSION으로 거부하므로 원본 보존 후 명시적 이관이 필요하다. 제품 사용 이력이 있는 저장소의 자동 downgrade 복구는 제공하지 않는다.

여러 writer나 여러 사용자 편집, 분기 병합, 임의 이력 이동은 현재 profile의 범위 밖이다.

## 검증 범위

서비스 시험은 미정 입력, 이름 변경 시 원본/출처 보존, 단위만 변경, 값과 단위 동시 변경, inactive/readonly/비유한 입력 거부, 의존 수식 재계산과 순환 실패, 원자적 metadata 편집, undo/redo 재시작/재전송/분기, 저장 기준점 보존, 게시 실패, 구형 이력 복원과 보존 상한을 포함한다. 실제 stdio 프로세스 시험은 서비스 재시작과 불변 스냅샷까지 연결한다.

이 profile은 속성 편집과 명령 이력을 구현한다. 2D 직접 편집, CAD worker와 제한된 사용자 PCB solver는 별도 계약으로 연결되며 이 DTO 자체가 물리 검증 결과는 아니다. 사용자 undo grouping, 실제 IFA/NF2FF 검증과 전체 GUI 성능 예산 수용은 후속이다.
