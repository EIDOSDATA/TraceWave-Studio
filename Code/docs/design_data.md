# 표현식과 설계 데이터 0.2

RFAD-D0-3.4의 단위, 매개변수, 설계 원본과 목적별 입력 검증을 구현하는 초기 profile이다. 서비스가 원본의 의미 검증을 소유한다. 이 문서의 설계 데이터 계층은 CAD B-rep나 openEMS를 직접 실행하지 않으며, 불변 스냅샷을 받는 별도 [CAD worker](cad_contract.md)와 [PCB solver](pcb_solver_contract.md)가 실제 형상/접속/계산을 검사한다. 제조 합격과 RF 정확도 검증은 별도다.

wxWidgets의 선택 속성 폼은 [편집 확장](editor_contract.md)을 통해 아래 원본 명령을 사용한다. [2D 표시/편집 확장](canvas_contract.md)의 `canvas.get`/`canvas.apply`도 같은 revision과 명령 이력을 사용한다. 표시 단위 변환과 표현식 계산은 서비스가 수행하고 GUI가 같은 계산을 중복 구현하지 않는다. 새 객체 생성 UI는 매개변수, 사각/원형 기판, 도체/유전체 층, 선분과 원호, 구멍을 가진 접지 polygon, 원형/회전 사각 pad, 명시적 PTH via, 재료/net/단일 포트를 지원한다. 새 재료의 물성 및 포트 저항/주파수/급전 영역은 미정으로 시작한다. 도체의 상세 의미와 CAD/EM 투영은 [도체와 IFA 확장](copper_features.md)을 따른다.

## 저장 형식과 호환성

새 프로젝트는 `rfad.project/0.2`로 생성한다. 기존 `rfad.project/0.1` 원본과 스냅샷은 그대로 읽고 검증한다. 기존 문서에 명령을 적용하면 복제본만 0.2로 바꾸고 새로운 revision을 생성한다. 이전 revision 파일, snapshot 바이트와 hash는 다시 쓰지 않는다. 미래 버전과 알 수 없는 핵심 필드는 거부한다. 범용 migration 또는 독립 프로젝트 import 기능은 아직 없다.

현재 매개변수 128개, 설계 객체 합계 256개 및 프로젝트 32 KiB 제한이 함께 적용된다. 256개는 파일 크기와 무관하게 보장되는 수용량이 아니다. 대형 편집 성능 예산을 검증한 profile이 아니다.

선택한 제조업체/재료의 구조화 출처는 [PCB 선택 확장](pcb_selection_contract.md) `rfad.pcb-selection/0.1`로 저장한다. 기본 프로젝트 버전을 올리지 않고 알려진 확장만 엄격히 검증한다. 출처 사본의 원래 값과 사용자 override, 미정값, 채택 이유를 구분하며 일반 직접 편집 후에는 원래 선택을 보존하고 차이를 조회한다. PCB 해석은 검증된 이 출처 확장을 비물리 메타데이터로 허용하며 알 수 없는 확장은 계속 거부한다.

## 표현식

`parameter.set`은 기존 id/name/quantity 리터럴 명령이다. 표현식 매개변수에 적용하면 명시적으로 리터럴로 바꾼다. `parameter.set_expression`의 payload는 다음과 같다. UUID는 실제 프로젝트의 값으로 치환한다.

```json
{
  "id": "00000000-0000-0000-0000-000000000002",
  "name": "절반 폭",
  "expression": "width / 2",
  "bindings": {"width": "00000000-0000-0000-0000-000000000001"},
  "dimension": "length",
  "display_unit": "mm"
}
```

- `40 mm`, `2.45 GHz`, `40*mm`처럼 단위를 명시한다. 기존 Quantity의 길이/주파수/시간/각도/임피던스/전도도/전력/무차원을 지원한다.
- 사칙연산, `**`, 괄호, `sqrt`, `sin`, `cos`, `tan`, `atan2`, `abs`, `min`, `max`, `clamp`, `pi`, `c0`를 제공한다. 각도와 무차원은 구분한다. 중간 차원은 분수 지수를 허용하고 마지막 결과는 명시한 Quantity 차원과 일치해야 한다.
- 숫자와 단위가 붙은 항을 거듭제곱하려면 `(2 mm)**2`처럼 괄호로 의도를 표시한다. 면적 등 별도의 최종 Quantity 차원은 아직 없다.
- Python eval/exec, 속성 접근, 인덱싱, 파일 접근과 임의 함수 호출은 제공하지 않는다.
- 원문 4096 UTF-8 bytes, 토큰 512개, 중첩 64단계, 평가 연산 2048회, 함수 인수 32개가 상한이다.
- 변수 이름과 bindings의 이름은 정확히 일치해야 한다. bindings는 표시 이름이 아닌 안정된 UUID를 참조한다. 이름 변경으로 결합이 끊어지지 않는다.
- 원문, bindings, 정렬된 의존 UUID, `rfad.expression/0.1` 엔진 버전과 마지막 계산 Quantity를 함께 저장한다. 저장된 계산값과 의존성은 읽을 때 다시 검증한다.
- 값 변경 후 의존 그래프를 따라 재계산한다. 순환, 누락 참조, 미정 입력, 차원 불일치, 정의역 오류, overflow와 0으로 소실되는 underflow를 거부한다. 명령 전체가 실패하며 원본과 접수 이력은 바뀌지 않는다.
- 사용한 입력의 출처를 합치고 estimated 입력이 있으면 결과도 estimated다. 그 외 계산 결과는 user_entered다. 미정값을 숫자로 채우지 않는다.

현재 계산 캐시는 같은 엔진/런타임에서 정확한 재평가 일치를 요구한다. Windows 3.12.10과 WSL Linux 3.12.3에서 49개 표현식, UUID 그래프와 IFA fixture 캐시가 정확히 일치했다. 임의의 모든 수식/CPU/libm 조합으로 일반화하지 않으며 다른 런타임과 엔진 변경 시 같은 검사를 다시 수행한다. 근거는 [Linux 환경](linux_environment.md)에 있다.

## 설계 원본

단위가 있는 설계 필드는 완전한 Quantity 또는 `{"parameter_id": "UUID"}`를 받는다. 서비스가 참조 매개변수의 최종 차원과 값을 검사한다. 매개변수 변경으로 기판 폭이나 원호 반지름이 잘못되면 해당 명령 전체를 거부한다.

| 객체 | 현재 필드와 의미 |
| --- | --- |
| board | id, frame_id, rectangle width/height 또는 circle center/radius, thickness_convention=finished |
| material | id, name, model=isotropic_constant, epsilon_r, tan_delta, conductivity, validity_hz의 min/max, source_refs, assumptions |
| layer | id, name, role, order, z_min, thickness, material_id. z_min+thickness가 물리 위치의 원본 |
| net | id, name. 의도한 접속 그룹이며 실제 접촉을 입증하지 않음 |
| line_path | 공통 속성과 start/end 2D 좌표, width |
| arc_path | 공통 속성과 center 2D 좌표, radius, start_angle, sweep_angle, width |
| planar_region | 공통 속성과 outer 2D 점 목록, holes의 내부 loop 목록. 외곽과 구멍을 따로 보존 |
| pad | 공통 속성과 pad_shape=circle/rectangle, center, size, rotation. 원형 size는 같은 지름 두 개 |
| via | 공통 속성과 center, end_layer_id, finished_hole_diameter, plating_thickness, tool_hole_diameter, fill=none, pad_ids. layer_id는 시작 도체층 |
| lumped port | id, name, positive_geometry_id, reference_geometry_id, resistance, reference_plane, polarity, direction, validity_hz, 선택적 excitation_box의 start/stop 3D 좌표 |

형상 공통 속성은 id/kind/role/frame_id/layer_id/net_id/material_ref/source_ref/include_in_em/include_in_export다. 허용 role은 radiator/ground/feed/short/conductor다. 포함 여부는 명시적 bool이다. 현재 오른손 항등 world/board frame만 지원한다.

명령은 `board.set`과 `material/layer/net/geometry/port.set`, 대응하는 `.remove`다. set payload는 `{"material": {...}}`처럼 객체 종류를 key로 사용한다. remove는 `{"id": "UUID"}`다. board=null은 의존 객체가 없을 때만 가능하다. 각 collection은 UUID 순서, 적층은 order 순서로 저장하여 역명령 적용 시 의미 없는 순서 변화가 생기지 않게 한다.

검사 항목은 UUID 충돌, 이름 중복, 존재하지 않는 참조, 참조 중인 객체 삭제, 차원/양수 조건, 적층 순서/겹침, 0 길이 선, 유효하지 않은 원호, polygon 경계/구멍, 원형 pad의 같은 지름, via의 도체층 순서와 pad 참조, 포트 양단 참조와 방향이다. 단일 lumped 포트만 저장한다. 매개변수 변경으로 유효하지 않은 형상이 되면 전체 명령을 거절하고 기존 원본/이력을 유지한다. 실제 구리 합집합, 기판 밖 형상, barrel/pad 접속과 급전 gap은 목적별 CAD/EM 계획과 native 단계에서 추가로 검사한다. 제조 공차와 전체 DRC는 후속이다.

planar_region은 각 loop 3점 이상, 외곽과 구멍 합계 64점 이하, 구멍 8개 이하의 직선 경계를 지원한다. 마지막 점에 첫 점을 반복하지 않으며 CW/CCW 원본을 보존한다. 모든 좌표가 확정되면 자기 교차, 중복/되돌아가는 변, 0 면적과 구멍의 접촉/교차/중첩을 거절한다. 미정 좌표가 있으면 초안을 저장하되 실제 형상 계산은 차단한다.

via는 연결할 시작/끝 도체층과 pad_ids를 명시한다. 비어 있는 pad_ids와 미정 구멍/도금 치수도 초안으로 저장할 수 있다. CAD/EM은 양 끝의 명시적 pad와 완성 구멍/도금 두께를 요구하며 초기 실행 범위는 최외측 도체층 사이의 중공 관통 PTH다. tool_hole_diameter 미정은 유지하고 알려진 값은 완성 구멍+2*도금 두께와 일치하는지 확인한다. 패드, 재료나 net을 자동 생성하지 않는다. pad_ids가 참조하는 pad를 바로 삭제할 수 없으며 참조를 먼저 변경해야 한다.

2D 표시 DTO는 현재 revision의 기판, 층과 선/원호/영역/pad/via를 mm/deg로 해석한다. 원호의 양수 sweep은 CCW, 음수는 CW이며 원본을 임의 링으로 닫지 않는다. 미정 또는 환산할 수 없는 치수는 0으로 대체하지 않고 null/omissions로 구분한다. 미정 지름의 via는 실제 원 크기를 추정하지 않고 중심 표식으로 표시한다. 좌표가 매개변수 참조이거나 미정인 형상은 직접 이동을 거절하고 속성에서 결합을 편집한다. 리터럴 좌표의 평행 이동은 polygon의 외곽과 모든 구멍을 함께 옮기며 폭/반지름/각도의 값과 참조를 보존한다.

큰 polygon 속성은 coordinate_table로 편집한다. 각 좌표 셀은 `{mode, value, parameter_id, unit}`이고 매개변수 선택지는 DTO의 coordinate_choices에서 공유한다. unit은 보통 mm이며 환산 overflow가 생기는 유한 원본은 m로 표시한다. unit은 읽기 전용이다. 변경하지 않은 셀의 원본 단위/상태/출처/UUID 결합을 보존하고 변경한 숫자만 표시 단위의 명시적 입력으로 적용한다. 이 표에서 꼭짓점 개수는 변경하지 않는다. via의 pad_ids는 여러 UUID를 선택하는 편집기를 사용한다.

GUI 드래그는 임시 preview 후 한 번의 원본 명령으로 확정한다. 취소는 원본을 바꾸지 않으며 성공 명령은 영속 undo/redo, 저장과 스냅샷에 연결한다. 새 도체층의 z_min/두께는 missing, material_id는 null이다. 그리드/보기/층 표시 상태는 물리 치수나 EM/export 포함 여부와 별개이며 현재 마우스 그리드 스냅은 미구현이다.

## 목적별 입력 확인

`design.validate`는 API-006의 제한된 draft revision profile이다. context는 project_id, input은 expected_revision/purpose/profile이다. profile은 `rfad.design/0.1`, purpose는 geometry/step/em이다. request key와 epoch로 queued TaskRef를 접수하고 job.status 완료 event에서 보고서를 읽는다. 접수 당시 revision을 고정하므로 이후 편집과 결과를 혼동하지 않는다.

| 목적 | 확인 내용 |
| --- | --- |
| geometry | 기판 크기와 포함할 선/원호/영역/pad/via의 치수 누락 |
| step | export 포함 형상과 적층 위치/두께 누락 |
| em | EM 포함 형상, net, 명시적 재료, 물성 유효 대역, 단일 포트와 대역 누락 |

물성을 모르는 상태에서도 저장한다. em 입력 점검은 필요한 물성이나 급전 좌표의 누락과 모델 대역 밖 입력을 차단한다. 도체 sheet만 사용하는 재료의 유전율/손실은 미정이어도 되며 유전체는 두 값이 필요하다. 체적 via 도체에는 전도도와 상대 유전율을 요구한다. 이 필수 물성 목록은 PCB 계획과 공유한다. 단순히 후속 계획 검증이 필요하다는 이유로 E_UNSUPPORTED를 만들지는 않는다. 모든 목적의 input_status=valid는 초기 입력 검사 통과이며 CAD 생성/STEP export/solver 접수나 물리 합격이 아니다. solver_ready는 항상 false이고 validation_scope=input_only, next_validation으로 다음 확인 경계를 명시한다.

보고서는 revision/hash, purpose/profile, input_status, diagnostics와 전체 diagnostic_count를 포함한다. 최대 64개 진단을 반환하며 초과 시 diagnostics_truncated=true다. 작업의 completed는 검사 수행 완료이고 설계 합격 여부는 input_status로 따로 판단한다. snapshot 입력, 보고서 artifact, 전체 제조/해석 profile은 후속이다.

GUI의 `해석 입력 검사`가 purpose=em 검사를 명시적으로 요청한다. 문제 목록은 해당 revision의 객체/필드로 이동하며 편집 후 이전 revision의 진단이면 이동을 거절하고 재검사를 안내한다. 캔버스에 형상이 보이거나 검사 작업이 완료되어도 solver 실행 가능 또는 실제 RF 합격으로 표시하지 않는다.

[initial_ifa.json](../fixtures/design/initial_ifa.json)은 초기 입력 기준으로 40 x 60 mm, 완성 두께 1 mm, 35 um 구리 2층, 2.4~2.4835 GHz와 50 ohm 조건을 기록한다. 완성 두께에서 구리 두께를 뺀 값은 mask 등을 분리하기 전 잔여 두께이며 실제 코어 두께 확정값이 아니다. 실제 물성, 세부 안테나 형상과 급전 배치는 미정이다. 해석 가능한 완성 보드로 취급하지 않는다.

별도의 [IFA 실행 fixture](../fixtures/ifa_feed_smoke.json)는 명시적 시험 가정으로 접지 polygon, 빈 영역, pad, 급전선과 단락부를 구성한다. 승인 초기 입력의 미정 물성은 덮어쓰지 않는다. 같은 net의 IFA도 서로 다른 양단 도체와 실제 열린 gap을 검사하며 동일 평면 x/y 또는 층 사이 z 방향 단일 포트를 사용할 수 있다. 현재 기준면은 이상적인 로컬 gap이고 실물 SMA 접속면/launch/정합 부품의 기생 효과나 측정 기준면을 검증한 상태는 아니다.

## 시험 범위

평가/그래프 전파/순환/역명령, 구형 원본 보존, 설계 참조, 미정 물성, 목적별 차단과 실제 저장소 재시작을 단위/통합 시험으로 확인한다. 2D 서비스/실제 stdio 시험은 생성/이동/삭제, signed sweep, 참조 보존, 실패/stale 불변성, undo/redo와 저장/스냅샷/재시작을 포함한다. `test_copper_design.py`와 `test_copper_editor.py`는 polygon의 구멍/매개변수/원자적 실패, nullable via 치수와 pad 참조, coordinate_table의 공유 선택지/크기 제한/단위 overflow 보존을 검사한다. 이 설계 데이터 시험은 RF 정확도나 실제 측정의 증거가 아니며 native CAD/EM 시험은 별도다.

2D 경계 보완본은 Windows 전체 227개 통과, Linux 220개 통과/GUI 7개 스킵과 native CTest 1개 통과를 확인했다. 이 수치는 당시 버전의 기록이며 이후 GUI 배치와 도체 모델 확장의 최신 실행 근거는 [개발 상태](development_status.md)를 따른다.
