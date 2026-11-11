# PCB 선택 출처, 적층 미리보기와 원자적 적용 계약

작성일: 2026-11-11 KST. 호환 정보 갱신: 2026-11-12 KST. 승인 기준선: RFAD-D0-3.4. API profile은 `rfad.pcb-selection/0.1`이며 프로젝트 선택 저장은 0.1 및 공유 근거 0.2를 지원한다. 현재 프로젝트 본체 쓰기는 `rfad.project/0.3`이며 기존 0.1/0.2 원본 읽기와 PCB 선택 확장은 유지한다. 공개 RPC envelope는 `rfad.api/2.0`이다.

이 구현은 [PCB 재료 카탈로그 설계](pcb_material_catalog.md)의 선택 근거 저장, 적층 초안, 변경 미리보기와 일괄 적용을 연결한다. [읽기 전용 카탈로그](pcb_catalog_contract.md)를 사용해도 프로젝트 변경은 별도의 명시적 적용 요청으로 수행한다. wxWidgets 화면 조작은 [PCB 선택 화면](pcb_selection_gui.md)을 따른다. 범용 EDA 가져오기와 새 CAD/solver 물리 모델은 이 변경 범위에 포함하지 않는다.

## 모듈과 적용 경계

| 모듈 | 책임 |
| --- | --- |
| `catalog/selection_reader.py` | 같은 카탈로그 개정의 제한된 읽기, 실제 원문 해시 검사, 출처 사본과 부분사본 수집 |
| `catalog/material_selection.py`, `selection_rules.py` | Dk/Df 독립 선택, 명시적 사용자 입력과 미정값, 조건 및 근사 이유 보존 |
| `catalog/stackup_draft*.py` | 업체별 원시 구성에서 검토 가능한 층 초안과 미정/차단 사유 생성 |
| `catalog/stackup_match.py` | 같은 적층/출처/원문 층의 관측만 정확하게 대응. 이름 또는 가까운 주파수만으로 연결하지 않음 |
| `catalog/stackup_suggestions.py`, `suggested_properties.py` | 두께와 Dk/Df의 페이지별 제안, 공개값/미정/모호성/근사 필요 구분 및 명시적 수용용 재료 입력 |
| `application/pcb_selection*.py` | 요청 계약, UUID 대응, 후보 구성, 포트/참조 검토, 미리보기 해시와 공개 API |
| `domain/pcb_selection*.py` | 알려진 프로젝트 확장 검증, 채택 당시 기록, 원자 명령과 역명령 |

기판 외형, 패턴 geometry와 nets는 보존한다. 선택 기능은 기판 자체나 안테나, 접지면, 비아, 포트를 생성하지 않는다. 층을 적용하려면 먼저 기존 `board.set` 명령 또는 GUI 기판 생성으로 외형을 정의한다. 기판이 없는 프로젝트에서도 자료 조회와 후보 미리보기는 가능하지만 층을 포함한 적용은 기존 문서 검사에서 차단한다. 자료의 Dk 변경만으로 패턴 치수를 합성하거나 목표 주파수에 정합하지 않는다.

`can_apply: true`는 프로젝트에 이 후보를 저장할 수 있다는 뜻이다. 미정 두께나 물성을 포함한 설계 초안도 저장할 수 있다. `readiness`는 `not_assessed`, `input_checks.solver_ready`는 `false`를 유지한다. CAD 생성, STEP 출력과 해석 계획/실행은 기존의 별도 검사를 거친다.

## 공개 API

서비스는 `--workspace`로 시작한다. 카탈로그를 사용할 때만 `--catalog`를 추가한다. `capabilities.get.pcb_selection_profile`에서 확장 지원과 응답 상한을 확인한다.

| 메서드 | `input` | 결과 |
| --- | --- | --- |
| `pcb.selection.preview` | `expected_revision`, `selection_id`, `specification` | 후보, 변경 ID, 출처 초안, 검토 사유, `preview_hash`, `can_apply` |
| `pcb.selection.apply` | preview 입력 전체와 `preview_hash`, `command_id` | 동기 명령 결과, `new_revision`, `revision_hash`, `history`, `selection_id`, `preview_hash` |
| `pcb.selection.get` | 빈 객체 | 저장된 선택/출처, 현재 개정, 적용 이후 변경 여부와 달라진 선택 필드 |
| `pcb.selection.context` | 빈 객체 | 현재 개정, 층/재료/포트의 작은 표시 목록, mm 치수와 매개변수 연결 여부 |

네 요청 모두 `context: {"project_id": "현재 프로젝트 UUID"}`를 사용한다. preview/get/context의 params는 정확히 `contract_version`, `context`, `input`이다. apply는 여기에 `request_key`와 `request_key_epoch`를 포함하는 기존 mutation envelope를 사용한다. JSON-RPC 요청에는 응답 ID도 필요하다.

`context`는 카탈로그 없이 현재 문서만 읽고 저장이나 이력을 변경하지 않는다. 치수는 서비스에서 단위를 해석하여 mm로 반환하며 미정값은 null을 유지한다. `parameter_bound`는 값이 매개변수에 연결되어 있음을 알린다. 기존 층 유지 경로는 표시 숫자를 다시 원본 값으로 쓰지 않는다. preview의 `candidate_layers`도 같은 표시 DTO를 사용하며 GUI에서 별도로 z를 누적하지 않는다. 원문 전체나 geometry를 context에 복사하지 않으며 기존 응답 상한을 적용한다.

preview는 프로젝트 revision, journal과 receipt를 변경하지 않는다. apply는 미리보기를 다시 계산한 뒤 기존 writer transaction에서 하나의 `pcb_stackup.apply` 명령으로 적용한다. 이 내부 명령을 `project.apply_command`로 직접 보내 우회할 수 없다. 한 번의 undo/redo는 재료, 적층, 포트 좌표와 선택 확장을 함께 복원한다.

apply는 별도 job이 아닌 동기 변경 명령이다. `project.open`, `project.save`, `snapshot.create`의 기존 queued job 계약과 구분한다. mutation notification과 mutation batch는 실행하지 않는다.

## 제조업체 적층과 물성의 함께 제안

`catalog.stackup_suggestions`는 `context: {}`인 읽기 전용 카탈로그 API다. `input`은 `{source: {catalog_id, entity, id}, offset?, limit?}`이며 `entity`는 `native_templates` 또는 `observations`다. `offset`은 0부터 시작하고 `limit`은 기본 8, 허용 범위 1~8이다. 부울/문자열을 페이지 수치로 변환하지 않는다. 카탈로그 개정, 선택 원문과 층 관계를 다시 검사하고 응답은 128 KiB 이내로 제한한다. 숫자나 원문을 줄여 예산을 맞추지 않으며 필요한 경우 반환 행수를 줄이고 실제 `next_offset`을 알려준다.

응답 schema는 `rfad.pcb-stackup-suggestions/0.1`이다. `source`, 전체 `draft`, 현재 페이지의 `layers`, `issues`, `readiness: not_assessed`, `offset`, `total_count`, `returned_count`, `next_offset`, `limited_by_bytes`를 반환한다. `next_offset`이 null이면 마지막 페이지다. GUI의 이전 페이지는 실제 방문한 오프셋 이력으로 이동한다. 조회나 페이지 이동만으로 프로젝트, 사용자 폼 또는 기존 적용 미리보기를 변경하지 않는다.

각 제안 행은 `layer_key`, `name`, `role`, `thickness_mm`, `thickness_state`, `thickness_basis`, `properties`, `material_spec`, `notes`를 가진다. 두께는 기존 적층 초안의 값과 범위를 그대로 사용하며 `source_value`와 `unresolved`로 구분한다. 코어에 동박이 포함되는지 불명확한 값이나 압착 후 여러 층의 합계를 개별 두께로 만들지 않는다. 완성 동박 두께와 기판 공칭 두께의 미정 상태도 유지한다.

| Dk/Df 제안 상태 | 의미와 수용 동작 |
| --- | --- |
| `published` | 해당 적층의 같은 층과 연결된 단일 공개값. 시험 조건을 별도로 표시하며 사용자가 제안을 수용하면 기존 `catalog` 선택으로 전달 |
| `missing` | 해당 물성이 없거나 수치로 쓸 수 없음. 값과 입력을 미정으로 유지 |
| `ambiguous` | 복수 관측 또는 원문 충돌. 첫 후보를 자동 선택하지 않고 사용자 검토 필요 |
| `approximation_required` | 범위/최대값/한정자 또는 모델 조건 때문에 직접적인 상수 채택이 부적절함. `value`는 null이고 `reported_value`/`reported_limits`는 원문 참고 표시만 제공. 근사값과 이유를 직접 입력해야 함 |
| `unsupported` | 자동 대응을 지원하지 않거나 원문 관계가 맞지 않음. 다른 제품의 값을 대체하지 않음 |

JLCPCB는 카탈로그 적층/출처, 공개 template ID, 구성행 순번, 재질 형식/이름, 원문 파일과 위치, native Dk를 함께 확인한다. PCBWay는 같은 적층/출처와 원문 table 행 및 재질 형식/Dk를 확인한다. 명시적으로 지원하는 OSH Park 2층 관측은 그 관측 자체만 사용한다. 사용자 정의 JLC template과 불완전한 WE 적층은 다른 공개 적층의 물성을 빌리지 않는다. 같은 업체, 비슷한 재질 이름, 가까운 주파수라는 이유로 자동 연결하는 규칙은 없다.

유전체의 `material_spec`은 새 재료를 위한 기존 선택 입력이다. 공개 Df를 총 전기 손실로 쓰는 `isotropic_constant_total_tan_delta`와 이유를 명시하고, 독립 전도도와 모델 적용 대역은 미정으로 둔다. Dk/Df의 주파수, 방법, 방향은 독립 표시하며 원문 시험 주파수를 적용 대역으로 자동 확장하지 않는다. 원래 전체 관측과 출처는 제안을 수용한 뒤 기존 preview/apply 경로에서 프로젝트 소유 근거로 저장한다. 제안 응답 자체는 제조나 해석 승인이 아니다.

현재 전체 자료의 JLCPCB/PCBWay 대응 관측은 Dk가 있어도 Df가 미정이다. 따라서 이 자료를 선택하면 Dk 공개값과 Df 미정이 함께 표시된다. RO4350B 탐색 모델처럼 다른 자료에 근거한 명시적 근사는 별도 사용자 입력으로 유지하고, 업체명이나 제품명만으로 기존 탐색 가정을 기본값에 복사하지 않는다.

조회 가능한 제안과 프로젝트에 적용 가능한 물리 범위를 구분한다. 출처 128 KiB/프로젝트 512 KiB 상한으로 기존 823개 조회 거절을 해소하고, 대표 JLC 4층/PCBWay 4층의 모든 유전체 제안 적용과 저장/재열기를 확인했다. 원문이나 미정값을 축약하지 않는다. 바이트 상한 개선이 solver의 층수/재료 지원 확대를 뜻하지는 않는다. [용량 개선과 후속 검증](capacity_and_followup.md)을 따른다.

전체 카탈로그의 모든 native template과 OSH Park 관측 기반 적층 후보를 검사하는 명령은 다음과 같다. 모든 제안 페이지를 이어 층 순서/누락/중복과 미정값을 확인하고, 자원 한계는 기존 초안 API에서도 같은 입력으로 재현되는지 분리한다. 보고서는 새 경로만 허용하며 DB는 읽기 전용으로 열고 변경 전후 해시를 비교한다.

```powershell
$reportPath = Join-Path (Get-Location).Path ('.local/stackup-suggestions/all-catalog-' + [guid]::NewGuid().ToString('N') + '.json')
.\.venv\Scripts\python.exe -X utf8 tools/verify_stackup_suggestions.py `
  --database '.local/pcb-catalog/catalog.sqlite' --report $reportPath
```

시험과 자료 한계를 포함한 실행 요약은 [적층 제안 검증 기록](../runtime_profiles/stackup-suggestions.json)에 보존한다.

## specification 입력

필수 필드는 `source`, `materials`다. 아래에 없는 추가 필드는 거부한다.

| 필드 | 형식과 의미 |
| --- | --- |
| `source` | 완전 수동이면 `null`. 출처 초안이면 `{catalog_id, entity, id}`이며 entity는 `native_templates` 또는 `observations` |
| `catalog_id` | source가 null이고 재료만 카탈로그에서 고를 때 사용하는 개정. source와 함께 지정하면 두 개정이 같아야 함 |
| `materials` | 아래 재료 spec의 목록, 최대 16개. 빈 목록도 허용 |
| `layers` | 선택적 전체 층 목록. 지정하면 출처 초안 대신 이 목록을 사용 |
| `layout_reason` | 직접 `layers`를 지정할 때 필수인 구성 이유 |
| `thickness_overrides` | `{layer_key: {value_mm, reason}}`. 값은 양수 또는 `null` |
| `material_assignments` | `{layer_key: material_key 또는 기존 material UUID 또는 null}` |
| `layer_ids` | `{layer_key: 기존 layer UUID}`. 기존 패턴과의 연결을 유지하기 위한 명시적 대응 |
| `material_ids` | `{material_key: 기존 material UUID}`. 명시한 기존 재료만 변경 |
| `z_origin_mm` | 첫 층의 아래쪽 원점. 생략하면 좌표 기준으로 0 mm 사용 |
| `port_updates` | 아래 포트 좌표 변경 목록, 최대 8개 |
| `notes` | 사용자의 추가 설명 목록, 최대 16개 |

카탈로그 출처의 ID는 [검색 결과](pcb_catalog_contract.md)에서 얻는다. 모든 카탈로그 재료와 적층은 하나의 명시적 `catalog_id`에서 선택한다. GUI가 받은 큰 원문 JSON이나 자체 추정한 source metadata를 apply 입력에 주입하는 방식은 지원하지 않는다.

## 재료 선택과 독립된 물성 조건

각 `materials` 항목은 `{key, name, properties, validity_hz}`다. 외부 spec에는 재료 UUID를 직접 넣지 않는다. `properties`에는 `epsilon_r`, `tan_delta`, `conductivity`를 모두 명시한다.

손실 모델을 명시하려면 선택 항목에 `model`과 `model_reason`을 함께 추가한다. 지원 값은 기존 `isotropic_constant`와 유전체 전용 `isotropic_constant_total_tan_delta`다. 모델과 이유는 채택 결정 및 가정에 보존하고 undo/redo와 재열기에 포함한다. 생략한 기존 요청은 이전과 같은 모델/결과를 유지한다. 이미 총 Df 모델인 재료를 기존 ID에 대응하여 수정할 때는 모델을 생략할 수 없다. 구형 GUI 입력으로 손실 모델이 암묵적으로 초기화되는 것을 막기 위한 조건이다. 현재 모델 선택은 공개 API에서 지원하며 GUI 속성은 모델 이름을 표시한다.

| 선택 | 정확한 형식 | 결과 |
| --- | --- | --- |
| 공개값 | `{mode: "catalog", record_id, reason}` | Dk는 원문의 `dk`, Df는 `df`에서만 선택. Quantity 상태는 `source_default` |
| 직접 입력 | `{mode: "user", value, reason}` | 명시한 유한값. 상태는 `user_entered` |
| 출처를 수정한 값 | `{mode: "user", value, reason, record_id}` | 원문을 남기고 사용자값을 별도로 보존 |
| 미정 | `{mode: "missing", reason}` 또는 여기에 `record_id` 추가 | `value_si: null`, 상태 `missing` |

`epsilon_r`와 `tan_delta`의 값은 무차원이고 전도도는 S/m다. 전도도는 이번 카탈로그 관측에서 자동 채택하지 않으므로 user/missing만 사용한다. Dk는 양수, Df/전도도는 음수가 아닌 값이어야 한다. 숫자처럼 보이는 문자열이나 boolean은 수치로 변환하지 않는다.

`validity_hz`는 `{min, max, reason}`이며 값은 명시적 양수 Hz 또는 `null`이다. 두 값이 있으면 min이 max보다 클 수 없다. 보고된 측정 주파수에서 이 대역을 자동 생성하지 않는다. 적용 대역은 사용자의 상수 모델 가정으로 남고 제조사 보증 대역으로 표시하지 않는다.

Dk record를 고르는 것만으로 Df를 채우지 않는다. 서로 다른 Dk/Df 관측을 사용자가 각각 선택한 경우 원문 주파수, 시험법과 구성 조건을 독립 보존하고 차이를 경고한다. Df 전용 주파수/시험법이 없으면 공통 record 조건을 대신 복사하지 않는다.

범위, 상한/하한, 충돌, 모호한 process/design 병기, effective permittivity, 명시적 이방성/자성 자료를 상수로 직접 채택하려 하면 거부한다. 필요한 근사는 `mode: user`, `record_id`, `reason`으로 명시해야 하며 원래 자료는 함께 남는다. 이 명시적 근사가 RF 정확도나 solver 지원을 승인하지는 않는다.

원문이 없거나 미정이라는 이유로 Df를 0, 전도도를 구리 대표값, Dk를 FR-4 대표값으로 대체하지 않는다. 사용자가 전도도 0이나 손실 0을 직접 지정하는 것과 미정 상태는 구분한다.

## 층 초안과 사용자 치수

출처 초안은 `rfad.pcb-stackup-draft/0.1`이다. `publisher`, 원래 template/record ID, `evidence_ids`, 공칭 두께와 그 해석 한계, `layers`, `issues`를 반환한다. 원자료의 위에서 아래 순서를 검토한 뒤 프로젝트 층은 아래에서 위 순서로 구성한다.

JLCPCB, PCBWay의 서로 다른 core/PP/동박 두께 의미를 업체별 adapter에서 처리한다. Wurth 원자료의 유전체 부분집합과 숫자 접두 혼입은 완전한 물리 적층으로 자동 변환하지 않는다. 관측 하나에서 2층 초안을 만드는 경로는 명시적으로 확인한 OSH Park `OSH_2L_1.6` core 관측으로 제한한다. 이 관측에 없는 완성 동박 두께는 미정으로 둔다.

지원되지 않거나 불완전한 원문에는 차단 사유를 반환한다. 사용자가 전체 `layers`와 `layout_reason`을 명시하면 해당 출처 초안의 구조 차단 사유를 사용자 구성으로 해결한 경고로 남긴다. 자료 사본/읽기 예산이나 프로젝트 스키마 검사를 우회하는 것은 아니다.

직접 층 목록의 각 항목은 `{key, name, role, thickness_mm}`이고 1~32개를 허용한다. role은 `conductor`, `dielectric`, `coating`, `adhesive`, `air`다. 이는 저장 가능한 역할이며 현재 CAD/EM 지원 범위를 뜻하지 않는다. 두께는 양수 mm 또는 `null`이며 key는 목록 안에서 유일해야 한다.

`z_min`은 명시한 원점과 아래 층 두께의 누적 합으로 계산한다. 어느 층 두께가 미정이면 그 층의 시작 위치는 이전 값에서 알 수 있어도 이후 층의 z는 미정으로 전파한다. 이후 두께가 알려져 있어도 미정 구간을 건너뛰어 좌표를 확정하지 않는다. `modeled_total_thickness_mm`도 전체 층 두께가 알려졌을 때만 반환한다.

공개 공칭 기판 두께와 모델 층 합계는 포함 범위/공차 확인이 필요하다. 차이를 코어에 몰아 넣거나 목표 완성 두께에서 동박을 임의로 빼지 않는다. `thickness_overrides`의 사용자값은 원문 채택값과 분리해서 기록한다.

## UUID 대응과 기존 객체 보존

새 재료 ID는 `uuid5(selection_id, "material:" + key)`, 새 층 ID는 `uuid5(selection_id, "layer:" + key)`다. 같은 미리보기 입력에서 안정된 ID를 만들며, 이미 적용한 selection_id를 새 선택처럼 재사용해 기존 객체와 충돌하면 거부한다.

기존 재료는 기본적으로 유지한다. `material_ids`로 선택한 key를 기존 UUID에 대응한 경우에만 해당 재료를 바꾼다. 하나의 기존 UUID를 여러 key에 대응하거나 존재하지 않는 UUID를 지정할 수 없다.

`layers` 또는 출처 초안으로 층을 구성하면 적층 목록을 교체한다. 기존 층 ID를 유지하려면 `layer_ids`로 명시하고 역할도 같아야 한다. 이름이나 가까운 z 위치만 보고 기존 층을 추정하지 않는다. 기존 geometry/layer/material/port 참조가 끊어지면 후보 검증에서 차단한다.

source가 null이고 `layers`도 없으면 기존 적층을 유지한다. 이 경우 `material_assignments`의 key는 기존 층 UUID다. 전체 층 목록 없이 `thickness_overrides`, `layer_ids`, `z_origin_mm`만 지정해 치수나 위치를 바꿀 수 없다. `material_assignments`에 없는 기존 층의 재료 참조는 보존하고, 새 층의 미지정 재료는 `null`이다.

기판 외형과 패턴 UUID는 그대로이므로 원형 PCB도 같은 외곽을 유지한다. 층 위치 변경으로 비아 span이 달라지면 후속 CAD 접촉 검사가 필요하다는 경고를 남긴다.

## 포트 좌표 변경

`port_updates`의 항목은 `{id, start_mm, stop_mm, reason}`이다. start/stop은 각각 길이 3의 명시적 mm 값 또는 `null` 배열이다. 기존 포트 UUID를 한 번만 지정할 수 있다.

이 경로는 기존 `excitation_box`만 바꾼다. 포트 생성/삭제, 양단 geometry 참조, 방향, 극성, 저항과 기준면을 바꾸지 않는다. 급전 도체가 연결된 층의 z/두께가 변경되고 기존 excitation_box가 있으면 좌표를 `port_updates`에 명시해야 한다.

새 층에서 유일한 유전체/도체 sheet 접면을 알 수 있을 때 명시한 포트 z가 그 접면과 다르면 적용을 차단한다. 접면이나 좌표가 미정이면 그 사실을 경고하며 해석 유효성이 확인되었다고 표시하지 않는다. 이 검사만으로 x/y 접촉, 완전한 급전 물리 모델이나 정합을 승인하지 않는다.

## 미리보기, 적용과 재전송

preview 결과에는 다음 정보가 들어간다.

- `candidate`: 적용할 materials/stackup/ports. 전체 프로젝트나 원문 자료를 반복 반환하지 않는다.
- `changes`: 컬렉션별 added/removed/changed UUID, moved_layers, board/geometry/nets 보존 여부.
- `source_draft`, `catalog`, `decisions`, `evidence_ids`: 이번 선택 근거와 출처 초안. 완전 근거 사본은 적용 후 get에서 조회한다.
- `retained_selections`: 보존할 이전 선택의 `{selection_id, catalog, evidence_ids}` 목록. 현재 객체의 출처 참조를 유지하기 위해 필요한 사본을 확인한다.
- `issues`: warning과 blocker. 입력 자체의 잘못된 형식이나 불가능한 물성 채택은 RPC 오류로 반환할 수도 있다.
- `input_checks`: geometry/step/em의 기존 입력 검사. 각 진단은 최대 16개와 축약 여부를 표시한다.
- `size`: 후보 프로젝트 바이트 수와 512 KiB 상한.

`preview_hash`는 project_id, expected_revision, selection_id, specification과 생성한 적용 payload를 해시한다. apply는 같은 입력을 다시 검증하고 해시가 같을 때만 적용한다. 미리보기 후 원문 개정, 입력 또는 현재 프로젝트 revision이 달라지면 다시 검토해야 한다. preview_hash 자체는 변경 권한이나 물리 검증 승인이 아니다.

request_key_epoch는 미리보기 해시와 다른 계약이다. `capabilities.get.idempotency_policy.request_key_epoch`에서 현재 영속 epoch를 얻어 apply의 mutation envelope에 넣는다. 같은 요청 재전송에는 같은 epoch/request_key와 같은 입력을 사용한다. 이미 게시한 요청은 receipt 결과를 재사용하므로 원문 카탈로그가 이후 없어져도 같은 확정 결과를 조회할 수 있다. 다른 입력을 같은 key로 보내거나 만료/다른 epoch를 사용하면 기존 정책에 따라 거부한다.

한 번의 적용은 재료, 전체 적층, 허용한 포트 좌표, 선택 출처와 undo 이력을 같이 게시한다. 실패 시 일부 층만 적용하지 않는다. 저장 pointer 게시 뒤 ACK 실패와 같은 공통 복구 경계는 [프로젝트 저장 계약](project_persistence.md)을 따른다. 새 변경은 revision으로 영속화되지만 사용자 저장 기준점은 별도 `project.save`, 실행용 고정 사본은 별도 `snapshot.create`로 만든다.

## 프로젝트 소유 출처와 역사적 선택

알려진 확장 키는 `extensions["rfad.pcb-selection"]`다. 선택에는 `schema`, `id`, `catalog`, `evidence`, `decisions`, `applied_state_sha256`, `notes`를 보관하며 필요한 경우에만 `history`를 추가한다. 이번 선택이 직접 입력만 사용하면 현재 catalog는 null이고 현재 evidence는 빈 목록이다. 보존한 기존 객체가 출처를 참조하면 그 근거는 history에 남을 수 있다.

catalog에는 `catalog_id`, `import_version`, `source_canonical_sha256`, `source_index_sha256`를 보관한다. 원문 관측/출처는 작은 완전 사본으로, native template/component는 선택한 pointer의 부분사본으로 저장한다. 기본 카탈로그가 업데이트되거나 삭제되어도 이미 저장한 값과 근거를 읽는 데 재접속하지 않는다.

| evidence 필드 | 의미 |
| --- | --- |
| `id`, `entity`, `item_id` | 안정 근거 ID와 원래 카탈로그 항목 |
| `scope` | `complete` 또는 `projection`. 부분사본을 원문 전체로 표시하지 않음 |
| `pointers` | 부분사본의 정렬된 RFC 6901 경로. complete이면 빈 목록 |
| `original_sha256` | 원래 전체 원문 JSON의 해시 |
| `snapshot_sha256`, `raw_json` | 실제 프로젝트에 복사한 정규 JSON 문자열과 그 UTF-8 해시 |
| `origin` | native는 `{source_id, path, pointer, sha256}`. 원문 파일의 상대 경로/위치/파일 해시. 관측/출처는 null |

projection의 raw_json은 `{"values": {"/path": "해당 원문값"}, "missing": ["/absent"]}` 형식이다. null과 미제공은 구분한다. native origin과 사본 해시도 evidence ID 계산에 포함한다. 공개 URL과 수집 당시 출처 metadata의 사본도 따로 보관한다.

안전 정수 범위 밖 원시 ID는 raw_json 문자열 안에 유지한다. 이를 프로젝트의 일반 숫자나 JavaScript Number로 변환하지 않는다. 원문 전체 또는 필요한 근거가 예산을 초과하면 잘라내지 않고 명시적으로 거부한다.

각 decision은 `{target: {collection, id, field}, basis, evidence_id, source_pointer, value_json, reason}`이다. basis는 `published`, `user_override`, `user_assumption`, `missing`이고 value_json은 채택 당시 값의 정규 JSON 문자열이다. 공개값에는 실제 원문 pointer와 값의 일치 검사가 적용된다. 사용자 수정의 이전 값/조건은 evidence에, 채택한 값과 이유는 decision에 남는다.

이후 기존 material.set/layer.set/속성 편집으로 값을 바꿔도 적용 당시 기록을 현재값으로 덮어쓰지 않는다. get은 `modified_since_selection`과 `changed_selected_fields`를 통해 차이를 보여 준다. 객체를 나중에 삭제한 경우에도 과거 기록을 원래 UUID에 연결해 보존하고 현재 객체가 존재하지 않음을 표시한다. 적용 당시 상태 해시는 materials/stackup/ports를 대상으로 한다.

다른 선택을 다시 적용할 때는 새 후보의 materials/stackup/ports에 남아 있는 `source_refs`를 확인한다. 새 evidence가 제공하지 않는 `evidence:` 참조는 이전 선택과 기존 history에서 찾고, 필요한 이전 선택의 완전 사본만 history에 보존한다. history는 최대 32개의 비재귀 목록이며 각 사본은 자신의 catalog, evidence, decisions와 적용 당시 해시를 가진다. 사용자가 history를 apply 입력으로 주입하지 않는다. 현재 참조에 대응하는 사본이 없거나 합산 예산을 넘으면 적용을 거부한다.

history는 모든 편집을 무한히 모으는 journal이 아니다. 다음 선택에서 현재 객체가 더 이상 참조하지 않는 과거 선택은 이 목록에서 제외할 수 있다. 원래 undo/redo 이력은 별도 프로젝트 저장 계약을 따른다. get은 저장된 history도 그대로 반환한다. `changed_selected_fields`는 최신 선택의 decisions만 비교한다. `modified_since_selection`은 마지막 적용 당시의 전체 materials/stackup/ports 해시와 비교하므로 history에 출처가 있는 보존 재료의 후속 변경도 감지한다.

알려진 선택 확장은 schema/필드/해시/수량/출처를 검증한다. 다른 이름의 미지 extension은 기존 프로젝트 규칙에 따라 JSON으로 보존하며 실행하거나 이 선택 모델로 해석하지 않는다. 프로젝트 본체 schema를 올리거나 모든 과거 자료를 자동 migration한 구현은 아니다.

## 크기와 실행 범위

| 제한 | 값 |
| --- | --- |
| 저장할 프로젝트 전체 | 정규 UTF-8 JSON 512 KiB |
| 선택 API 결과 | 384 KiB. 적층 조회/제안 128 KiB, 일반 검색/상세 48 KiB |
| JSON-RPC 프레임 | 1 MiB |
| 프로젝트 선택 근거 목록 | 현재와 history의 고유 evidence 합산 정규 JSON UTF-8 크기 128 KiB, 최대 256개. 문자열 escape와 metadata 포함 |
| 과거 선택 사본 | 최대 32개 비재귀 목록. 프로젝트 512 KiB와 고유 근거 합산 128 KiB도 동시에 적용 |
| 근거 raw_json 한 개 | 4,096자 및 8,192 bytes |
| 한 선택의 카탈로그 읽기 | 원문 한 행 256 KiB, 전체 1 MiB, 최대 512개 캐시 행 |
| 한 native template의 구성행 조회 | 최대 256개 |

GUI나 자동화는 source 전체를 로딩하지 않고 이미 구축한 읽기 전용 SQLite에서 선택한 항목만 읽는다. 원문 PDF/HTML을 실행하거나 CAD/solver native 모듈을 선택 경로에 추가하지 않는다. 위 숫자는 초기 자원 상한이며 60/30 fps나 RF 성능의 측정 결과가 아니다.

적층을 저장하는 기능과 현재 CAD/PCB solver가 소비 가능한 물리는 구분한다. 내부 동박, 마스크/접착층, 분산/이방성, 다중 포트 등은 해당 adapter의 별도 구현/검증 없이 자동 축약하거나 삭제하지 않는다. 구체적인 지원 범위는 [CAD](cad_contract.md), [PCB solver](pcb_solver_contract.md), [도체/IFA](copper_features.md) 계약을 따른다.

## CLI stdio 예제

`Code`에서 다음과 같이 서비스를 시작한다. stdin/stdout은 한 줄에 하나의 UTF-8 JSON-RPC 프레임을 사용한다. 카탈로그를 생략해도 완전 수동 입력과 기존 선택 조회는 사용할 수 있다.

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 -m rfad serve `
  --workspace '.local/selection-workspace' `
  --catalog '.local/pcb-catalog/catalog.sqlite'
```

다음 Python 예제는 별도의 임시 workspace에서 capabilities, 생성, 기판 설정, preview/apply/get/save를 실제 CLI stdio로 호출한다. 원형 외곽 반지름은 예제를 위한 명시적 입력이며 제품 기본값이 아니다. 물성, 동박/유전체 두께와 적용 대역은 모두 미정으로 남겨 저장 가능과 해석 가능의 차이를 확인한다. 코드 종료 시 임시 예제 workspace를 정리한다.

```python
"""! @brief 임시 workspace에서 실제 CLI stdio 선택 흐름을 확인한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import uuid4


def quantity(value, dimension="length", unit="mm"):
    """! @brief 예제에서 명시한 길이를 기존 SI 수량 계약으로 표현한다."""
    return {"value_si": value / 1000, "dimension": dimension, "display_unit": unit,
            "status": "user_entered", "source_refs": []}


with TemporaryDirectory(prefix="tracewave-pcb-selection-") as workspace:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path("src").resolve())
    process = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "rfad", "serve", "--workspace", workspace],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=environment,
    )
    epoch = None

    def call(method, value, context=None, *, mutation=False):
        """! @brief 한 줄 JSON-RPC를 보내고 해당 응답의 오류를 확인한다."""
        params = {"contract_version": "rfad.api/2.0", "context": context or {}, "input": value}
        if mutation:
            params.update(request_key=str(uuid4()), request_key_epoch=epoch)
        request = {"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}
        process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    def finish(task):
        """! @brief project.open/save의 작업 완료 결과를 조회한다."""
        deadline = monotonic() + 10
        while monotonic() < deadline:
            status = call("job.status", {"job_id": task["job_id"]})
            if status["state"] == "completed":
                return status["events"][-1]["operation_result"]
            if status["state"] in ("failed", "cancelled", "interrupted"):
                raise RuntimeError(status)
            sleep(0.02)
        raise TimeoutError("예제 작업이 제한 시간 안에 완료되지 않았습니다.")

    try:
        epoch = call("capabilities.get", {})["idempotency_policy"]["request_key_epoch"]
        opened = finish(call("project.open", {
            "path": "projects/selection-example", "open_mode": "create", "name": "선택 계약 예제",
        }, mutation=True))
        context = {"project_id": opened["project_id"]}
        board = {
            "id": str(uuid4()), "frame_id": opened["document"]["frames"]["board"]["id"],
            "outline": {"kind": "circle", "center": [quantity(0), quantity(0)], "radius": quantity(20)},
            "thickness_convention": "finished",
        }
        changed = call("project.apply_command", {
            "expected_revision": opened["document"]["revision_id"], "command_id": str(uuid4()),
            "type": "board.set", "payload": {"board": board},
        }, context, mutation=True)
        missing = {"mode": "missing", "reason": "실제 재료와 제작 조건을 아직 정하지 않음"}
        specification = {
            "source": None,
            "materials": [{
                "key": "core", "name": "미정 유전체",
                "properties": {"epsilon_r": dict(missing), "tan_delta": dict(missing), "conductivity": dict(missing)},
                "validity_hz": {"min": None, "max": None, "reason": "적용 대역 미정"},
            }],
            "layers": [
                {"key": "bottom", "name": "아래 동박", "role": "conductor", "thickness_mm": None},
                {"key": "core", "name": "유전체", "role": "dielectric", "thickness_mm": None},
                {"key": "top", "name": "위 동박", "role": "conductor", "thickness_mm": None},
            ],
            "layout_reason": "공개 API의 미정 입력 보존을 확인하는 예제",
            "material_assignments": {"core": "core"},
        }
        selection = {"expected_revision": changed["new_revision"], "selection_id": str(uuid4()),
                     "specification": specification}
        preview = call("pcb.selection.preview", selection, context)
        assert preview["can_apply"] and preview["input_checks"]["solver_ready"] is False
        applied = call("pcb.selection.apply", {
            **selection, "preview_hash": preview["preview_hash"], "command_id": str(uuid4()),
        }, context, mutation=True)
        saved = finish(call("project.save", {"expected_revision": applied["new_revision"]}, context, mutation=True))
        stored = call("pcb.selection.get", {}, context)
        assert stored["selection"]["id"] == selection["selection_id"]
        assert stored["modified_since_selection"] is False
        print(json.dumps({"profile": preview["profile"], "can_apply": preview["can_apply"],
                          "solver_ready": preview["input_checks"]["solver_ready"],
                          "readiness": stored["readiness"], "selection_saved": bool(saved),
                          "document_bytes": preview["size"]["document_bytes"]}, ensure_ascii=False))
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        errors = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
        if process.returncode:
            raise RuntimeError(errors)
```

검증 시 `can_apply: true`, `solver_ready: false`, `readiness: not_assessed`, `selection_saved: true`를 확인했다. 실행마다 UUID와 revision은 달라지므로 이를 고정된 문서값으로 복사하지 않는다. 실제 클라이언트의 재전송에서는 예제처럼 새 request_key를 만들지 말고 해당 mutation의 원래 envelope를 보관해 재사용한다.

## 검증과 후속 작업

`tests/test_catalog_selection.py`는 독립 물성 선택과 사본/해시/예산, `test_pcb_selection_domain.py`는 알려진 확장과 원자 명령, `test_pcb_selection_service.py`는 공개 API/재전송/저장/재시작/undo/redo를 검증한다. 제조업체 초안은 `test_catalog_stackup_draft.py`와 실제 카탈로그 검토로 확인한다.

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_*selection*.py' -v
```

실제 카탈로그의 대표 JLC 2층/4층, PCBWay 4층, OSH Park 2층을 적용하고 저장, snapshot, undo/redo, 카탈로그 DB 없는 재열기와 CAD 입력 변환까지 검사하는 재현 명령은 다음과 같다. WE는 자동 적층을 확정하지 않고 명시적 수동 구성을 확인한다. 이 검사는 CAD 입력 계약을 확인하며 형상 생성이나 EM 실행의 검증을 대신하지 않는다.

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_selection.py `
  --database '.local/pcb-catalog/catalog.sqlite' `
  --report '.local/pcb-selection/representative-new.json'
```

현재 단계의 적용 성공은 RF 물성의 측정 검증, 제조 가능성 보증 또는 IFA 성능 합격이 아니다. 다음 화면 연결에서는 이 API의 미정값/차단 사유/출처/사용자 변경을 그대로 보여 주고, 사용자가 검토한 입력만 apply해야 한다. 실제 개발 상태와 전체 회귀 결과는 [개발 상태](development_status.md)를 따른다.

## 공유 근거 저장 형식 0.2

기존 `rfad.pcb-selection/0.1` 문서는 그대로 읽고, 조회만으로 원본 또는 해시를 변경하지 않는다. 새 적용에서 선택의 정규 표현이 32 KiB를 넘고 실제 중복 저장을 줄일 수 있으면 `rfad.pcb-selection/0.2`를 사용한다. 프로젝트 본체는 0.2, API profile은 0.1을 유지한다. 새 선택 형식의 지원은 capabilities에서 별도로 알린다. 이전 실행 파일이 새 대용량 문서를 읽는 역방향 호환을 보장하지 않는다.

0.2는 최상위 `evidence_pool`에 고유 출처 사본을 한 번 저장하고 현재 선택과 비재귀 history의 `evidence`에는 순서가 있는 ID 목록을 저장한다. 사본의 raw_json, 원문/사본 SHA-256, 포인터, origin과 ID는 변경하지 않는다. 검증 시 독립된 0.1 사본으로 복원한 뒤 각 catalog/채택값/해시를 재검증한다. 없는/중복/미사용 사본, 서로 다른 같은 ID와 변조된 원문은 거절한다. 고유 근거에 합계 예산을 적용한다. 저장, 스냅샷과 역명령은 기존 원자 경로를 사용하며 외부 파일이나 설치 카탈로그에 출처를 의존하지 않는다.
