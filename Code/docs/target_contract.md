# 사용자 정의 대역 목표 입력 계약

작성일: 2026-11-12 KST. 승인 기준선: RFAD-D0-3.4. 구현 profile은 `rfad.target/0.1`, 프로젝트 쓰기 schema는 `rfad.project/0.3`이다. 개발 완료 계획 3번의 첫 구현 범위이며 FN-004 전체나 목표 평가 완료를 뜻하지 않는다.

## 1. 지원 범위

`project.apply_command`의 `target.set`과 `target.remove`로 사용자 정의 목표를 저장한다. 각 목표는 한 대역을 가지며 프로젝트의 복수 목표가 다중 대역을 표현한다. 기존 저장, 재열기, 불변 snapshot, 영속 undo/redo, stale revision 차단과 멱등 재접수 경로를 사용한다.

지원 물리 모드는 `radiating_rf`이다. 대역 입력의 저장 가능 여부와 선택한 해석기의 실행 가능 여부는 별개다. 목표 주파수를 입력해도 기존 `solver.plan`의 주파수, 격자, 포트 저항 또는 물성이 자동 변경되지 않는다. 실제 제작/측정 물성의 미정 상태도 유지한다.

## 2. 목표 원본

`targets`는 UUID 오름차순으로 저장하는 최대 32개 목록이다. 각 항목은 다음 필드만 갖는다.

| 필드 | 의미 |
| --- | --- |
| `id` | 사용자 정의 목표의 안정 UUID |
| `revision_id` | 서비스가 set/undo/redo마다 발급하는 목표 개정 UUID |
| `name` | 사용자 표시 이름 |
| `physical_mode` | 현재 `radiating_rf`만 지원 |
| `band` | 시작, 끝, 기준 주파수 및 샘플 규칙 |
| `port_id` | 존재하는 포트 UUID 또는 미정 `null` |
| `reference_impedance` | 양의 실수 Quantity 또는 `missing` Quantity |
| `criteria` | 지원 지표 중 사용자가 지정한 목표 목록 |
| `source_refs` | 목표 입력 근거의 문자열 목록 |

목표 ID, 목표 개정 ID, 프로젝트/개정, 좌표계, 매개변수, 보드 및 설계 객체 ID의 충돌을 거부한다. 목표가 참조하는 포트를 제거하려면 먼저 목표의 연결을 수정하거나 목표를 제거해야 한다. 기준 임피던스는 평가 조건이며 물리 포트의 저항을 덮어쓰지 않는다. 50 ohm을 자동 입력하지 않는다.

`band`의 `start`, `end`, `reference`는 기존 Quantity 형식을 사용한다. SI Hz 값과 입력 상태, 표시 단위, 출처를 보존하며 `parameter_id` 참조는 아직 지원하지 않는다. 시작/끝은 양수이고 시작보다 끝이 커야 한다. 기준 주파수는 대역 내부의 양수 또는 `status=missing, value_si=null`이다.

샘플 규칙은 아래 두 종류만 지원한다.

- `{"kind":"linear","count":101}`: 양끝을 포함한 등간격 표본 2~1001개.
- `{"kind":"explicit","frequencies":[...]}`: 대역 내부의 Frequency Quantity 1~1001개. 중복 없이 엄격히 증가해야 한다. 명시 표본이 대역 전체를 검증했다는 뜻은 아니다.

## 3. 지표 한계와 미정 상태

각 criterion은 `metric`, `operator`, `limit`만 갖는다. `limit`은 `value`, `unit`, `status`, `source_refs`를 갖는다. 숫자는 유한 float64이며 `user_entered`, `source_default`, `estimated` 중 입력 경로를 기록한다. 미정은 `value=null, status=missing`으로 저장한다. 입력 경로는 계산/제조/측정 검증 합격 상태가 아니다.

| metric | 단위 | 연산자 | 허용 한계 |
| --- | --- | --- | --- |
| `s11_db` | `dB` | `le` | 0 이하 |
| `radiation_efficiency` | `1` | `ge` | 0~1 |
| `total_efficiency` | `1` | `ge` | 0~1 |
| `fractional_bandwidth` | `1` | `ge` | 0~2 |

`s11_db`는 S11 크기의 `20*log10(abs(S11))` 표현값이다. `dB`를 SI 선형 배율로 추가하지 않는다. 반사 손실을 양의 return loss로 입력하는 별도 지표도 아직 지원하지 않는다. 비율 대역폭은 `(f_high-f_low)/((f_high+f_low)/2)` 정의의 입력 한계이며 어떤 정합 조건을 만족하는 연속 구간인지와 실제 달성 판정은 후속 평가 계약에서 명시해야 한다. 한 target에 같은 metric을 중복 지정할 수 없다.

`project.open`은 원본 `document.targets`와 별도로 `target_input_statuses`를 반환한다. 생략되었거나 한계가 미정인 지표는 `missing_target`, 입력된 지표는 `not_evaluated`이다. 조건이 미정이면 `missing_conditions`에 표시한다. 현재 `evaluation_status`는 항상 `not_evaluated`이며 합격 값을 생성하지 않는다.

## 4. 명령과 개정

`target.set` payload는 `{"target": {...}}`이다. target에는 위 표에서 `revision_id`를 제외한 모든 필드를 지정한다. 서비스가 목표 개정 UUID를 생성하며 호출자가 임의로 과거 revision을 주입할 수 없다. `target.remove` payload는 `{"id":"목표 UUID"}`이다. 전체 프로젝트 검증 실패 시 현재 원본/개정/이력/receipt는 변경되지 않는다.

set은 동일 ID의 목표를 완전히 교체한다. 명시적 입력 API이므로 source_refs까지 호출자가 전달한다. UI에서 부분 편집을 연결할 때는 기존 출처와 변경 근거를 보존하는 DTO를 별도로 제공해야 한다. 현재 구현은 근거 문자열을 검증된 외부 자료로 승격하거나 프리셋 원문 사본이라고 표시하지 않는다.

undo/redo는 과거 의미 입력을 새 목표 개정으로 복원한다. 과거의 정확한 target revision은 기존 불변 프로젝트 개정과 snapshot 안에 남는다. 동일 request_key 재접수는 원 응답을 반환하므로 새 목표 개정을 만들지 않는다.

무효화 목록은 기존 vocabulary인 `revision`, `metrics`, `assessment`, `exports`를 사용한다. `geometry`, `physics`, `network`는 추가하지 않는다. 기존 원시 해석 파일은 삭제하지 않지만 목표만 다른 결과 사이의 자동 캐시 재사용이나 자동 수렴 비교까지 구현한 것은 아니다. 필요한 주파수/장 데이터가 부족한지 확인하는 기능은 후속 평가 단계에 남아 있다.

## 5. 기존 파일 호환성

읽기 지원 schema는 `rfad.project/0.1`, `rfad.project/0.2`, `rfad.project/0.3`이다. 0.1의 기존 제한과 0.2의 설계/표현식 지원을 유지한다. 0.1/0.2에 비어 있지 않은 targets를 끼워 넣으면 거부한다.

기존 프로젝트 읽기와 snapshot 생성은 schema, revision, 원본 bytes/hash를 바꾸지 않는다. 첫 변경 명령은 원본을 복제하여 새 0.3 개정을 만들고 기존 artifact를 보존한다. schema가 바뀐 경우에만 응답과 command journal의 `schema_migration`에 `from`, `to`, `original_revision`을 기록한다. 이 metadata는 과거 원본이나 봉인 해시에 삽입하지 않는다.

해석 snapshot guard도 위 읽기 schema 목록을 지원한다. 기존 0.2 CAD/PCB/도파관 계획의 원본과 snapshot을 0.3으로 재작성하지 않는다. 지원 schema라고 해서 입력 해시, 참조, 물성 또는 해석 capability 검사를 생략하지 않는다.

## 6. 시험과 남은 범위

`tests/test_targets.py`는 다중 대역 저장, Hz/GHz SI 동등성, 미정/출처, 오류 rollback, 포트 의존성, 목표별 개정, 저장/재시작/재열기/snapshot/undo/redo/멱등성, 0.1/0.2 불변 읽기와 0.3 승격을 검증한다. 실제 CAD 및 PCB 계획 생성의 순수 경로로 목표가 물리 case와 solver 설정을 바꾸지 않는지도 확인한다. native CAD와 FDTD는 실행하지 않는다.

목표 편집은 [편집 서비스 계약](target_editor_contract.md)과 [wxWidgets 화면](target_template_gui.md)으로 연결했다. 변경한 입력만 적용하고 단위만 바꾼 값과 기존 출처/미정 상태를 보존한다. 후속 범위는 출처/원문/지역/version을 갖는 통신 프리셋, 실현 이득/편파/관측 방향, 크기/제조 제약, parameter 참조, 주파수 데이터 가용성 안내, MetricRecord/Assessment 및 목표 평가이다. 기존 설계 승인과 실제 성능/제작/측정 검증을 구분한다.

## 7. 공개 stdio 요청 예제

Code 폴더에서 `.venv\Scripts\python.exe -m rfad serve --workspace .local\target-example`로 프로젝트 서비스를 실행할 수 있다. stdio는 한 줄에 JSON 한 개를 보내는 NDJSON 형식이다. 다음 예제는 읽기 쉽도록 여러 줄로 표시했다.

먼저 아래 요청으로 `result.idempotency_policy.request_key_epoch`를 조회한다. `project.open` 완료 결과에서 현재 project_id와 revision_id를 얻은 뒤 변경 요청에 사용한다. 아래 변경 예제의 project_id, expected_revision, request_key_epoch는 설명용 UUID이므로 반드시 해당 서비스가 반환한 실제 값으로 바꾼다. command_id와 target.id는 새 UUID로 지정한다.

```json
{"jsonrpc":"2.0","id":1,"method":"capabilities.get","params":{"contract_version":"rfad.api/2.0","context":{},"input":{}}}
```

다음 요청은 2.4~2.5 GHz 대역의 S11 목표를 저장한다. 기준 주파수, 기준 임피던스, 포트와 전체 효율 목표는 미정으로 유지한다. `tests/test_targets.py::target_input`과 같은 실제 필드 구조다.

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "project.apply_command",
  "params": {
    "contract_version": "rfad.api/2.0",
    "context": {"project_id": "00000000-0000-4000-8000-000000000001"},
    "request_key": "user-target-example-01",
    "request_key_epoch": "00000000-0000-4000-8000-000000000010",
    "input": {
      "expected_revision": "00000000-0000-4000-8000-000000000002",
      "command_id": "00000000-0000-4000-8000-000000000003",
      "type": "target.set",
      "payload": {
        "target": {
          "id": "00000000-0000-4000-8000-000000000004",
          "name": "사용자 대역 목표",
          "physical_mode": "radiating_rf",
          "band": {
            "start": {"value_si": 2400000000.0, "dimension": "frequency", "display_unit": "GHz", "status": "user_entered", "source_refs": ["사용자 목표 입력"]},
            "end": {"value_si": 2500000000.0, "dimension": "frequency", "display_unit": "GHz", "status": "user_entered", "source_refs": ["사용자 목표 입력"]},
            "reference": {"value_si": null, "dimension": "frequency", "display_unit": "GHz", "status": "missing", "source_refs": []},
            "sampling": {"kind": "linear", "count": 11}
          },
          "port_id": null,
          "reference_impedance": {"value_si": null, "dimension": "impedance", "display_unit": "ohm", "status": "missing", "source_refs": []},
          "criteria": [
            {"metric": "s11_db", "operator": "le", "limit": {"value": -10.0, "unit": "dB", "status": "user_entered", "source_refs": ["사용자 정합 목표"]}},
            {"metric": "total_efficiency", "operator": "ge", "limit": {"value": null, "unit": "1", "status": "missing", "source_refs": []}}
          ],
          "source_refs": ["인증 또는 측정값이 아닌 사용자 입력"]
        }
      }
    }
  }
}
```

성공 응답의 `new_revision`을 이후 저장/목표 변경/undo 요청에 사용한다. 다른 대역을 추가할 때는 새 target.id를 사용한다. 기존 목표 수정은 같은 target.id와 전체 입력을 다시 전송한다. 제거는 `type=target.remove`, `payload={"id":"제거할 목표 UUID"}`이며 나머지 요청 envelope는 같다. 미정 임피던스를 포함한 목표 저장 성공은 EM 실행 가능 또는 목표 합격을 뜻하지 않는다.
