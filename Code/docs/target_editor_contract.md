# 목표 편집 GUI 서비스 계약

갱신일: 2026-11-12 KST. 목표 입력 원본은 `rfad.project/0.3`과 `rfad.target/0.1`을 유지하며, 화면 전용 확장은 `rfad.target-editor/0.1`이다. 저장한 목표가 계산 결과나 성능 합격을 뜻하지 않는다.

## 1. 역할과 공개 경로

`target_editor.py`는 조회/변경 접수, `target_editor_fields.py`는 표시 DTO, `target_editor_values.py`는 명시적으로 수정한 입력의 변환을 담당한다. GUI는 이 DTO의 숫자 문자열, 단위 선택지와 오류 위치를 표시한다. SI 변환, 목표 UUID 생성, hash 및 물리 검증은 서비스가 담당한다.

- `target.editor.get`: 현재 개정의 목표 목록과 선택한 목표 또는 신규 입력 폼을 읽는다.
- `target.editor.apply`: 기존 RequestLedger transaction 안에서 `target.set` 또는 `target.remove` 명령을 실행한다.
- 저장, snapshot, undo/redo는 기존 프로젝트 API와 이력을 그대로 사용한다.
- 추가한 각 목표는 한 대역을 표현한다. 서로 떨어진 여러 대역은 여러 목표로 저장한다.

기존 직접 domain 명령도 유지한다. 이 확장은 API-018 목표 평가나 solver 설정 자동 적용을 구현한 것이 아니다.

## 2. 조회와 표시 DTO

조회 요청은 기존 `contract_version=rfad.api/2.0` envelope를 사용한다.

```json
{
  "contract_version": "rfad.api/2.0",
  "context": {"project_id": "프로젝트 UUID"},
  "input": {"expected_revision": "현재 개정 UUID", "target_id": null}
}
```

`target_id=null`은 저장 전 신규 폼이다. 기존 UUID는 해당 프로젝트의 목표를 선택한다. 신규 이름은 빈 문자열이며 주파수/임피던스/포트/성능 한계를 임의로 채우지 않는다. Hz/kHz/MHz/GHz 선택은 표시 단위이고, 신규 등간격 표본 수도 명시적으로 입력해야 한다.

응답은 `profile`, `project_id`, `revision_id`, `saved_revision`, `history`, `items`, `selection`, `input_status`, `limits`, `evaluation_supported=false`, `changes_solver_settings=false`를 가진다.

`items`의 각 행은 `id`, `label`, 문자열 `summary`를 가진다. `selection`은 `id`와 `fields`를 가진다. 필드에는 기존 속성 패널과 같은 `key/label/value/editor/choices/readonly`가 있다. 읽기 전용 상태/출처는 `advanced=true`로 상세 표시할 수 있다. `input_status.summary`는 상세를 접어도 추정 입력, 자료 기본값과 미정 조건을 보여준다. 원래 metric별 `missing_target/not_evaluated`와 `evaluation_status=not_evaluated`도 유지한다.

| 편집 키 | 의미 |
| --- | --- |
| `name` | 사용자가 입력한 목표 이름 |
| `band.start/end/reference.mode` | `value` 또는 `missing`. 저장할 시작/끝은 값이 필수 |
| `band.start/end/reference.value` | 단위를 적용하기 전 숫자 문자열 |
| `band.start/end/reference.unit` | Hz/kHz/MHz/GHz |
| `reference_impedance.mode/value/unit` | 기준 임피던스의 직접 입력/미정. 단위 ohm |
| `port_id` | 기존 포트 UUID 또는 미정인 빈 문자열 |
| `sampling.kind` | `linear` 또는 `explicit` |
| `sampling.count` | 양끝을 포함한 등간격 개수 문자열. 2~1001 |
| `sampling.explicit` | 숫자와 단위를 가진 줄 문자열의 배열. 1~1001개 |
| `criteria.<metric>.mode` | `absent`, `missing`, `value` |
| `criteria.<metric>.value` | 명시적으로 입력한 성능 한계 문자열 |

지표는 `s11_db`, `radiation_efficiency`, `total_efficiency`, `fractional_bandwidth`를 지원한다. S11은 dB/이하, 나머지는 비율 단위 1/이상이다. 효율 70%는 `0.7`로 입력하며 퍼센트 값으로 임의 해석하지 않는다. 지표 단위, 연산자, 입력 상태와 출처는 읽기 전용이다.

여러 줄 필드는 `editor=string_lines`, `multiline=true`, `value=list[str]`를 사용한다. GUI는 textarea와 배열 사이의 join/split만 수행한다. 명시 표본 예시는 `["2400 MHz", "2.45 GHz", "2500000000 Hz"]`이다. 단일 RPC 문자열의 8192-byte 제한을 피하기 위해 전체 표본을 하나의 문자열로 보내지 않는다.

표본의 같은 입력 상태/단위/출처는 표본 번호 범위와 함께 묶어 표시한다. 이 표시는 모든 표본과 출처의 대응을 유지하며 원본 배열을 변경하지 않는다. DTO는 60 KiB를 넘으면 E_RESOURCE를 반환한다. 큰 출처나 표본을 임의로 잘라 표시하거나 저장하지 않는다.

## 3. 변경 요청과 원자성

변경은 기존 `request_key`, `request_key_epoch`와 함께 다음 input을 사용한다.

```json
{
  "expected_revision": "현재 개정 UUID",
  "command_id": "새 명령 UUID",
  "operation": "set",
  "target_id": "기존 목표 UUID 또는 null",
  "values": {"band.start.value": "2410"},
  "reason": "변경 사유"
}
```

실제 신규 요청의 `target_id`에는 문자열 `null`이 아닌 JSON null을 사용한다. `operation=remove`는 기존 목표 UUID와 빈 `values={}`를 요구한다. 추가/수정/제거 모두 비어 있지 않은 변경 사유를 제공한다. 사유는 최대 512자이며 원본 출처와 명령 기록에 보존한다.

`values`는 수정한 필드만 포함하는 patch다. 전체 원본이나 임의 status/source/hash를 전송하지 않는다. 읽기 전용 필드, 미지원 필드 및 현재 선택하지 않은 입력 방식의 변경은 거부한다. 기존 값과 의미가 같은 요청은 불필요한 개정을 만들지 않고 E_CONFLICT로 반환한다.

서비스는 현재 개정 검사 후 단일 기존 명령을 만들고, 전체 목표/프로젝트 검증을 통과한 경우에만 개정, undo/redo, 영수증과 응답을 같은 transaction으로 게시한다. 응답은 기존 명령 응답에 `target_id`를 추가한다. UUID 생성은 신규 접수 안에서만 수행하며 같은 요청의 재전송은 같은 목표 ID와 응답을 반환한다. stale revision, 잘못된 단위/대역/표본, 미정 필수 입력 또는 잘못된 포트는 기존 원본과 영수증을 유지한 채 실패한다.

## 4. 출처와 미정값 보존

- 수정하지 않은 수량, 표본, 지표의 숫자/단위/status/source_refs는 원본 그대로 복사한다.
- 단위만 수정하면 SI 값, 입력 상태와 원래 출처를 유지한다. 변경 사유는 목표와 명령 이력에 남긴다.
- 실제 수치가 바뀌면 `user_entered`로 기록하며 원래 출처를 보존하고 변경 사유를 추가한다.
- 값을 미정으로 바꾸면 value는 null이고 status는 `missing`이다. 0이나 합격으로 바꾸지 않는다.
- 명시 표본의 다른 행을 수정해도 화면에 그대로 표시된 행은 다시 수치화하지 않는다. 단위 표시 환산의 왕복 오차로 원래 값을 바꾸지 않는다.
- 표본 추가/수정 시 대응하는 기존 출처를 유지한다. 삭제된 표본과 목표의 원본은 이전 개정/역명령에 남는다.
- 근사/자료 기본값을 읽거나 이름만 바꾸는 행위는 검증 상태를 승격하지 않는다.

목표 변경의 무효화는 기존 `revision/metrics/assessment/exports` 계약을 사용한다. 형상, 재료, 급전이나 solver 주파수 설정을 자동 변경하지 않는다. 기존 raw 결과를 보존하는 것과 서로 다른 개정의 자동 비교/재평가 완료는 구분한다.

## 5. 검증 범위

`tests/test_target_editor.py`는 실제 RPC와 임시 journal로 추가/수정/제거, 다중 대역, 단위/출처/미정/명시 표본, 1001개 wire 표본, 저장/재열기/재시작/undo/redo, 멱등 재전송과 실패 rollback을 검사한다. native EM 실행이나 실제 제작/측정 검증을 대신하지 않는다.
