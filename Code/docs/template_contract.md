# 원호와 평면 IFA 명시 기하 템플릿 계약

명시 치수 원호/IFA 및 G031 문헌 부분 기하의 카드 조회, 읽기 전용 후보 미리보기와 단일 원자 적용을 구현했다. 이어 [G001/G008/G009와 조건부 초기 길이](printed_templates_and_seeds.md)를 연결했다. 초기식은 G001의 제한된 시작 길이 추정이며 RF 공진/정합 합성, 성능 평가, 제조 또는 측정 검증 완료를 뜻하지 않는다. G031의 원문/치수/생략 범위는 [문헌 카드 계약](literature_templates.md)을 따른다.

기준일: 2026-11-12 KST. 승인 RFAD-D0-3.4 FN-006/007과 API-007의 `explicit_geometry` 및 제한된 `initial_estimate` 범위다. 최초 제안 기록은 [template_design.md](template_design.md), 목표 원본은 [target_contract.md](target_contract.md), GUI 사용 계약은 [target_template_gui.md](target_template_gui.md)를 따른다.

## 1. 지원 범위와 미정값

| 항목 | 구현 범위 |
| --- | --- |
| 후보 profile | `rfad.template-candidate/0.2` |
| 카드 schema | 내장 0.1, G031 0.2, 추가 문헌 `rfad.template-card/0.3` |
| 생성기 | 내장 `rfad.explicit-geometry/0.1`, G031 `rfad.literature-geometry/0.1`, 추가 문헌 `rfad.printed-reference/0.1` |
| 프로젝트 | 현재 `rfad.project/0.3` core 객체에 실제 매개변수, net, 기하, 선택적 포트를 추가 |
| 출처 확장 | `extensions["rfad.template-origin"]`, schema `rfad.template-origin/0.1` |
| 원호 카드 | `template_id="builtin.explicit_arc"`, `version="0.1"`; 기존 원형 또는 직사각 보드 |
| IFA 카드 | `template_id="builtin.explicit_planar_ifa"`, `version="0.1"`; 기존 직사각 보드 |
| 문헌 카드 | `template_id="literature.g031_pca20006_arc"`, `version="0.1"`; 기존 원형/직사각 보드 위 원호/stub 부분 기하 |

사용자가 만든 보드, 적층, 재료, 기존 기하와 목표를 유지한다. 내장 직접 입력 카드 두 종에는 숫자 치수나 RF 물성 기본값이 없다. G031은 원문 치수만 별도로 제공하며 배치 이동량과 물성/포트를 채우지 않는다. 시험용 Dk/Df, 동박 전도도, 두께, 50 ohm 또는 시험 대역을 제품 기본값으로 승격하지 않는다. 필요한 기하 치수가 없으면 후보 생성을 거부한다. 물성이나 포트가 미정이면 가능한 기하를 저장하고 후속 해석의 부족 입력과 구분한다.

카드 `support`는 `geometry_generator=true`이며 G001만 `seed_synthesizer=true`다. `simulated`, `converged`, `measured`, `manufacturing_verified`는 모두 `false`다. 내장 카드의 `source.kind="implementation_recipe"`는 TraceWave 생성기의 설계 근거를 뜻한다. G031의 `cad_reference`와 추가 문헌의 `document_reference`는 확인한 원문 일부의 치수/초기식 근거이며 원본 전체나 문헌 성능의 승계를 주장하지 않는다.

## 2. 공개 API와 요청 수명

공통 읽기 envelope는 `{contract_version:"rfad.api/2.0",context:{...},input:{...}}`다. 읽기 호출은 receipt, journal, history나 프로젝트를 쓰지 않으며 native worker를 실행하지 않는다. `template.synthesize`는 제한된 크기의 동기 후보 조회다.

| 메서드 | context | input | 주요 결과 |
| --- | --- | --- | --- |
| `template.list` | `{}` | `{}` | `profile`, `cards`, `read_only=true` |
| `template.get` | `{}` | `{template_id,version}` | `profile`, `card`, `new_instance_id` |
| `template.context` | `{project_id}` | `{expected_revision}` | 현재 보드/frame, 도체 `bindings`, 목표 ID/개정, 카드, 인스턴스 변경 상태, `new_instance_id` |
| `template.synthesize` | `{project_id}` | 아래 후보 입력 | `can_apply`, `preview_hash`, `scene`, `issues`, `input_checks` |
| `template.apply` | `{project_id}` | 후보 입력 + `command_id`, `preview_hash` | 기존 프로젝트 명령 결과의 `new_revision`, `history`와 `instance_id`, `preview_hash` |

`template.context`도 정확한 `expected_revision`이 필요하다. 조회 중 프로젝트가 바뀌면 stale 상태를 명시적으로 거부한다. `new_instance_id`는 조회 때 발급하는 UUID이며 예약이나 저장을 의미하지 않는다. GUI가 같은 후보를 다시 미리 볼 때는 발급받은 ID를 유지한다.

적용은 기존 mutation envelope에 `request_key`, 현재 policy의 `request_key_epoch`를 추가한다. 검토한 후보 입력 전체와 `preview_hash`를 다시 보낸다. 서비스가 같은 writer transaction 안에서 후보를 재구성하고 검토 해시를 확인한 뒤 내부 `template_instance.apply` 한 번으로 게시한다. 이 내부 명령 및 `template_instance.*`는 외부 `project.apply_command`로 호출할 수 없다.

같은 요청의 재접수는 원래 응답을 돌려주며 새 인스턴스를 만들지 않는다. 다른 요청으로 이미 존재하는 인스턴스를 추가하면 충돌이다. 카드, 입력, 목표 개정, binding 또는 프로젝트 개정이 바뀌면 다시 미리 보아야 한다. 파일 게시 실패도 부분 기하나 일부 출처만 공개하지 않는다.

## 3. 후보 입력

`template.synthesize`의 `input`은 다음 필드만 허용한다.

| 필드 | 의미와 검사 |
| --- | --- |
| `expected_revision` | 읽을 현재 프로젝트 개정 UUID |
| `mode` | `explicit_geometry`; G001만 `initial_estimate` 추가 지원 |
| `template` | 조회한 `{template_id,version,content_hash}` 전체 |
| `instance_id` | 새 인스턴스 UUID; 현재 객체와 충돌 검사 |
| `target_refs` | 명시적으로 선택한 `{id,revision_id}` 목록, 최대 32개; 없으면 `[]` |
| `binding` | 기존 `{board_id,frame_id,layer_id,material_id}`; `material_id`는 null 가능 |
| `explicit_inputs` | 카드 descriptor가 요구하는 모든 기하 필드 |
| `port` | 미정이면 `null`; 명시 포트는 5절의 recipe |
| `seed` | 초기식 모드의 `{recipe_id,frequency,assumption}`; 상세 범위는 추가 문헌 계약 |

`target_refs`의 목표 사본은 생성 당시 출처로 보존한다. 선택한 목표 대역을 solver 주파수 설정으로 자동 복사하거나 길이/재료로 변환하지 않는다. 목표 평가 상태는 계속 `not_evaluated`다. `binding`은 현재 보드/frame과 실제 도체 층을 참조한다. 명시 재료가 있으면 실제 프로젝트 재료 ID여야 하며, null이면 그 상태를 보존한다.

입력 필드는 기존 5필드 Quantity 또는 `{value:string,unit:string}` 표시 입력을 받는다. GUI는 mm/deg 문자열을 그대로 보내고 서비스에서 SI로 변환한다. 표시 입력은 최대 128자이며 숫자로 해석할 수 없는 값, NaN, 무한대, 미정 치수와 미지원 단위를 거부한다. 표시 입력에서 만든 Quantity는 `status="user_entered"`, `source_refs=[]`다. 이미 Quantity로 제공한 상태와 출처는 그대로 보존한다. parameter 참조나 입력 식은 첫 후보 입력에서 지원하지 않는다.

원호 카드의 9개 필드는 다음과 같다.

| 입력 | 단위 | 생성 의미 |
| --- | --- | --- |
| `center_x`, `center_y` | mm | 중심 좌표 |
| `radius` | mm | 중심선 반지름 |
| `start_angle`, `sweep_angle` | deg | 시작각과 부호 있는 전개각 |
| `width` | mm | 원호 선폭 |
| `feed_start_x`, `feed_start_y` | mm | 급전 선 시작점 |
| `feed_width` | mm | 급전 선폭 |

급전 선 끝은 원호의 해석적 시작점이다. 그 좌표는 표현식 매개변수로 기록한다. `0 < abs(sweep) < 360 deg`, `radius > width/2`, 유효 선폭과 길이, 실제 원형/직사각 외곽 안의 도체와 round cap을 검사한다. 원의 bounding rectangle만으로 원 안이라고 판정하지 않는다.

IFA의 14개 입력은 모두 mm다.

| 입력 | 생성 의미 |
| --- | --- |
| `ground_left`, `ground_bottom`, `ground_width`, `ground_height` | 유한 직사각 ground |
| `radiator_start_x`, `radiator_y`, `radiator_length`, `trace_width` | 수평 radiator 및 가지 선폭 |
| `short_x`, `short_start_y` | ground 내부에서 radiator까지 연결할 단락 가지 |
| `feed_x`, `feed_start_y` | 급전 가지 시작점 및 패드 중심 |
| `pad_width`, `pad_height` | 회전하지 않은 직사각 급전 패드 |

ground 위 radiator, ground에 닿는 short, ground와 떨어진 feed/pad, short/feed의 독립 간격, 실제 보드 외곽을 검사한다. 작은 패드보다 굵은 feed의 round cap도 gap 검사에 포함한다. 이 검사는 전층 제조 DRC, 임의 패턴 간 최소 간격, keepout 또는 RF 성능의 합격을 의미하지 않는다.

## 4. 공개 호출 예

아래 JSON은 원형 보드에 명시 치수 원호를 미리 보는 `params` 예다. `<...>`는 `template.context`와 카드 응답에서 얻은 실제 값으로 바꾼다. 숫자는 공개 API 시험용 기하 예시이며 추천 안테나 치수, 제조 조건 또는 RF 성능 근거가 아니다.

```json
{
  "contract_version": "rfad.api/2.0",
  "context": {"project_id": "<project UUID>"},
  "input": {
    "expected_revision": "<current revision UUID>",
    "mode": "explicit_geometry",
    "template": {
      "template_id": "builtin.explicit_arc",
      "version": "0.1",
      "content_hash": "<card content hash>"
    },
    "instance_id": "<context.new_instance_id>",
    "target_refs": [],
    "binding": {
      "board_id": "<context.board.id>",
      "frame_id": "<context.frame_id>",
      "layer_id": "<selected conductor layer UUID>",
      "material_id": null
    },
    "explicit_inputs": {
      "center_x": {"value": "0", "unit": "mm"},
      "center_y": {"value": "0", "unit": "mm"},
      "radius": {"value": "6", "unit": "mm"},
      "start_angle": {"value": "0", "unit": "deg"},
      "sweep_angle": {"value": "90", "unit": "deg"},
      "width": {"value": "0.8", "unit": "mm"},
      "feed_start_x": {"value": "2", "unit": "mm"},
      "feed_start_y": {"value": "0", "unit": "mm"},
      "feed_width": {"value": "0.6", "unit": "mm"}
    },
    "port": null
  }
}
```

`template.synthesize`의 성공 여부는 `can_apply`로 확인한다. 이는 기하와 출처를 저장할 수 있다는 의미다. `input_checks.scope="input_only"`이며 `solver_ready=false`를 유지한다. 미정 물성이나 급전 때문에 `input_status="blocked"`여도 geometry-only 후보는 적용할 수 있다. `diagnostics`는 최대 32개를 표시하고 전체 수는 `diagnostic_count`로 제공한다. 해석 계획은 이후 별도로 생성하고 물성, 대역, 격자 및 접속 검사를 거쳐야 한다.

반환 `scene`은 기존 `build_canvas_dto`와 같은 DTO다. `can_apply=false`이면 `preview_hash=null`, `scene=null`이고 `issues`에 차단 이유를 반환한다. 유효한 후보를 적용하려면 위 `input`에 새 `command_id`와 반환된 `preview_hash`를 추가하고 envelope에 mutation request key/epoch를 붙여 `template.apply`를 호출한다.

## 5. 선택적 명시 포트

GUI 첫 범위는 `port:null`인 geometry-only 선택과 미리보기다. backend는 다음 recipe를 완전히 명시한 경우 실제 lumped 포트도 생성한다.

```text
port = {
    reference_geometry_id: UUID 또는 null,
    resistance: impedance Quantity,
    reference_plane: 문자열,
    polarity: 1,
    direction: [1, 0, 0] 또는 [0, 1, 0],
    validity_hz: {min: frequency Quantity, max: frequency Quantity},
    excitation_box: {start: [length Quantity 3개], stop: [length Quantity 3개]}
}
```

IFA의 `reference_geometry_id=null`은 생성한 ground를 참조한다. 양극은 생성한 pad다. 원호는 기존 ground ID를 지정하고 생성 feed를 양극으로 쓴다. 첫 slice는 기존 포트가 없는 프로젝트, 같은 도체 층, +x/+y 방향의 양의 1차원 gap만 지원한다. 저항, 주파수 범위, 기준면 설명과 좌표를 자동 생성하지 않는다.

포트 끝점은 실제 ground/양극에 접해야 하고 두 도체에 동시에 포함될 수 없다. line_path에 연결하는 끝점은 기존 PCB solver와 동일하게 선의 가장자리에 접해야 한다. z 위치는 도체와 유전체의 유일한 접면을 사용한다. 하부 동박의 경우 동박 윗면이며, 상부 동박은 아래 접면일 수 있다. domain과 PCB 투영이 같은 접면 함수를 공유한다. 단순히 도체 `z_min`으로 고정하지 않는다.

포트 후보가 생성되어도 solver의 최소 gap 격자 수, 설정 대역, 유한 도전율 등의 검사는 별도다. 시험에서 더 작은 명시 격자를 사용한 것은 시험 입력이며 서비스가 사용자 설정을 조정한 것이 아니다. 이상적 gap 포트를 SMA/launch나 측정 기준면 보정으로 표시하지 않는다.

## 6. 저장, 편집과 출처

생성 객체는 기존 core의 `parameters`, `nets`, `geometry`, `ports`에 저장한다. `instance_id`와 고정 역할의 UUID5로 안정 ID를 만들고, 기하는 매개변수 참조를 사용한다. 매개변수 표시 이름은 `원호 <짧은 구분자> / 중심선 반지름` 또는 `IFA <짧은 구분자> / 접지 폭`처럼 구성한다. 안정 ID를 이름에서 역산하지 않는다.

`rfad.template-origin`에는 인스턴스별로 다음을 저장한다.

- 정확한 카드 사본과 `content_hash`, generator version, 출처, 가정과 제한.
- `base_revision`, 확장을 포함한 원 프로젝트의 `base_content_hash`.
- 정확한 binding, 원 요청 `requested_inputs`, 정규화된 Quantity `inputs`, 명시 `port_recipe`.
- 선택한 정확한 목표 ID/개정의 `target_snapshots`.
- 생성 당시 `objects` 사본과 고정 역할 ID 대응, 전체 `record_hash`.
- 확장만 비운 적용 전 core 사본 `source_document`와 별도 `source_document_hash`.

`base_content_hash`와 `source_document_hash`는 서로 다른 원본을 해시한다. 후자는 과거 사본의 전체 domain 의미 검사를 위한 기준이며 원래 PCB 선택 출처를 대체하지 않는다. 실제 프로젝트의 기존 확장은 유지한다. `source_document.extensions={}`를 강제하여 이전 origin을 재귀적으로 복사하지 않는다.

카드 descriptor, 입력 Quantity, 목표 사본, 생성 객체와 포트 recipe는 hash뿐 아니라 닫힌 schema와 기존 전체 domain validator로 검사한다. 해시는 내용 무결성 식별자이며 제조사 서명이나 물리 검증 증거가 아니다. 저장 파일을 열 때 현재 카드 라이브러리를 재조회하지 않으므로 생성 이후 카드 갱신이나 외부 자료 부재가 과거 사본을 바꾸지 않는다.

현재 객체를 직접 편집하거나 삭제해도 과거 origin은 그대로 남는다. `template.context.instances[].changes`는 원래 생성 객체에 대한 `modified`/`removed` 상태를 알려준다. 현재 목표를 수정해도 생성 당시 목표 사본은 바꾸지 않는다. 과거 사본과 현재 객체의 exact-match를 프로젝트 편집 조건으로 강제하지 않는다.

undo/redo는 생성 당시 정확한 사본을 복원하며 현재 라이브러리로 재합성하지 않는다. 내부 inverse는 해당 인스턴스와 생성 객체만 처리한다. 관련 없는 매개변수, 목표, 확장과 과거 sealed artifact를 덮어쓰지 않는다. 생성 객체를 사용자가 변경한 뒤 바로 내부 제거를 시도하면 충돌을 반환하며, 정상 history에서는 먼저 후속 편집을 undo한 뒤 템플릿을 undo한다.

## 7. 비용 한도와 실행 경계

| 한도 | 현재 값 |
| --- | --- |
| origin 인스턴스 | 최대 8개 |
| 전체 origin canonical bytes | 256 KiB |
| 후보/context 응답 canonical bytes | 256 KiB |
| 전체 프로젝트 문서 | 기존 512 KiB |
| 목표 참조 | 최대 32개 |
| 과거 목표의 explicit 주파수 표본 | core와 동일하게 최대 1001개 |
| 카드 기하 입력 | 원호 9개, IFA 14개, G031 13개(배치 이동량 2개 포함) |

8개는 저장 가능 개수를 보장하지 않는 상한이다. 각 인스턴스에 적용 전 core 사본을 저장하므로 기존 프로젝트가 크면 byte 제한에 먼저 도달한다. 초과를 조용히 자르거나 출처를 버리지 않고 거부한다. 후속 최적화는 참조 의존 부분만 정확히 추출하는 방식이며 현재 원본 사본 의미를 임의로 축소하지 않는다.

알려진 `rfad.template-origin` 내부 목록에는 core 목표와 같은 1001개 표본 예산을 허용한다. 닫힌 origin schema가 나머지 필드별 상한을 별도로 검사한다. 미지 extension은 기존 collection 256개 제한을 유지하며, 그 내부에 같은 namespace 문자열을 넣어도 완화되지 않는다. 이 예외는 origin 256 KiB와 전체 문서 512 KiB를 늘리지 않는다. 작은 출처의 1001개 표본과 정확한 선택 목표 사본은 보존할 수 있지만 큰 출처 원문으로 byte 예산을 초과하면 적용을 차단한다.

PCB solver는 검증된 provenance namespace만 추가로 허용한다. 임의 extension은 계속 거부한다. 기하의 CAD 입력과 PCB plan은 실제 생성된 core 객체를 소비하며 원 출처도 보존한다. 후보 조회/적용 자체는 CAD, STEP 또는 FDTD를 실행하지 않는다. 기존 수렴 미확립 손실, GHz PTH 정확도, 제작/납품 물성과 측정 조건을 새로 확정하지 않는다.

## 8. 검증과 남은 범위

`tests/test_template_candidates.py`의 15개 시험은 두 카드의 원본 불변 미리보기, 직접 입력 변환/원문 보존, 원형 경계/원호 범위, IFA 단락과 실제 cap 간격, 정확한 목표/카드/binding/ID, 명시 포트의 실제 PCB plan 연결, 상하부 접면, 현재 편집/삭제와 과거 출처 분리, 재해시된 잘못된 nested origin 거부를 확인한다. 1001개 explicit 표본 보존, 1002개 및 미지 확장 257개 거부, 실제 origin byte 예산도 검사한다. 공개 RPC의 저장/재시작/snapshot/undo/redo/멱등, stale/preview 변조 차단과 디스크 게시 실패 원자성도 포함한다.

이 시험의 RF 물성은 명시된 시험 가정이다. 순수 CAD input 또는 PCB plan 생성 성공은 native 실행, 수렴 또는 제조/측정 성능 합격과 구분한다. 실제 CAD worker/STEP/재열기 확인은 `tests/test_template_native.py`의 별도 환경 의존 검증 범위이며 결과는 실행 기록을 따른다.

FN-006/007 전체 완료로 표시하지 않는다. 일반 템플릿 등록/import, 문헌 전체 보드 및 다른 topology, 원호/IFA RF 합성, 목표 평가/자동 정합, 전층 keepout/제조 DRC, 포트 GUI, 독립 RF 참조 및 제작/측정 검증은 후속 범위다. G031의 `reference_inputs`/`evidence`, 명시 원문 선택 `{"source":"card"}` 및 분리된 `generation` 상태는 [문헌 카드 계약](literature_templates.md)을 따른다. 새 카드/초기식은 [추가 계약](printed_templates_and_seeds.md)을 따른다. 위 최초 내장 카드 검증 수치는 당시 기록이며 문헌 카드의 신규 실행은 별도 기록한다.
