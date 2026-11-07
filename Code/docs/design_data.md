# 표현식과 설계 데이터 0.2

RFAD-D0-3.4의 단위, 매개변수, 설계 원본과 목적별 입력 검증을 구현하는 초기 profile이다. 서비스가 모든 의미 검증을 소유한다. 현재 CAD B-rep, 제조 출력, 접속 판정이나 openEMS 계산을 수행하지 않는다.

## 저장 형식과 호환성

새 프로젝트는 `rfad.project/0.2`로 생성한다. 기존 `rfad.project/0.1` 원본과 스냅샷은 그대로 읽고 검증한다. 기존 문서에 명령을 적용하면 복제본만 0.2로 바꾸고 새로운 revision을 생성한다. 이전 revision 파일, snapshot 바이트와 hash는 다시 쓰지 않는다. 미래 버전과 알 수 없는 핵심 필드는 거부한다. 범용 migration 또는 독립 프로젝트 import 기능은 아직 없다.

현재 매개변수 128개, 설계 객체 합계 256개 및 프로젝트 32 KiB 제한이 함께 적용된다. 256개는 파일 크기와 무관하게 보장되는 수용량이 아니다. 대형 편집 성능 예산을 검증한 profile이 아니다.

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

현재 계산 캐시는 같은 엔진/런타임에서 정확한 재평가 일치를 요구한다. 다른 OS의 수학 라이브러리까지 bitwise 일치를 검증한 상태는 아니다. Linux 실행과 엔진 변경 시 캐시 호환성 검증이 추가로 필요하다.

## 설계 원본

단위가 있는 설계 필드는 완전한 Quantity 또는 `{"parameter_id": "UUID"}`를 받는다. 서비스가 참조 매개변수의 최종 차원과 값을 검사한다. 매개변수 변경으로 기판 폭이나 원호 반지름이 잘못되면 해당 명령 전체를 거부한다.

| 객체 | 현재 필드와 의미 |
| --- | --- |
| board | id, frame_id, rectangle outline의 width/height, thickness_convention=finished |
| material | id, name, model=isotropic_constant, epsilon_r, tan_delta, conductivity, validity_hz의 min/max, source_refs, assumptions |
| layer | id, name, role, order, z_min, thickness, material_id. z_min+thickness가 물리 위치의 원본 |
| net | id, name. 의도한 접속 그룹이며 실제 접촉을 입증하지 않음 |
| line_path | 공통 속성과 start/end 2D 좌표, width |
| arc_path | 공통 속성과 center 2D 좌표, radius, start_angle, sweep_angle, width |
| lumped port | id, name, positive_geometry_id, reference_geometry_id, resistance, reference_plane, polarity, direction, validity_hz |

형상 공통 속성은 id/kind/role/frame_id/layer_id/net_id/material_ref/source_ref/include_in_em/include_in_export다. 허용 role은 radiator/ground/feed/short/conductor다. 포함 여부는 명시적 bool이다. 현재 오른손 항등 world/board frame만 지원한다.

명령은 `board.set`과 `material/layer/net/geometry/port.set`, 대응하는 `.remove`다. set payload는 `{"material": {...}}`처럼 객체 종류를 key로 사용한다. remove는 `{"id": "UUID"}`다. board=null은 의존 객체가 없을 때만 가능하다. 각 collection은 UUID 순서, 적층은 order 순서로 저장하여 역명령 적용 시 의미 없는 순서 변화가 생기지 않게 한다.

검사 항목은 UUID 충돌, 이름 중복, 존재하지 않는 참조, 참조 중인 객체 삭제, 차원/양수 조건, 적층 순서/겹침, 0 길이 선, 유효하지 않은 원호, 포트 양단 참조와 방향이다. 단일 lumped 포트만 저장한다. 실제 구리 합집합, 패드/비아, 임의 polygon, 기판 밖 형상, 제조 공차, 실제 접속/단락과 급전 갭 위치 검증은 후속이다.

## 목적별 입력 확인

`design.validate`는 API-006의 제한된 draft revision profile이다. context는 project_id, input은 expected_revision/purpose/profile이다. profile은 `rfad.design/0.1`, purpose는 geometry/step/em이다. request key와 epoch로 queued TaskRef를 접수하고 job.status 완료 event에서 보고서를 읽는다. 접수 당시 revision을 고정하므로 이후 편집과 결과를 혼동하지 않는다.

| 목적 | 확인 내용 |
| --- | --- |
| geometry | 기판 크기와 포함할 선/원호의 치수 누락 |
| step | export 포함 형상과 적층 위치/두께 누락 |
| em | EM 포함 형상, net, 명시적 재료, 물성 유효 대역, 단일 포트와 대역 누락 |

물성을 모르는 상태에서도 저장한다. em 검증에서는 미정 물성이나 모델 대역 밖 입력을 차단한다. 모든 입력을 채워도 해석기/연결성/수렴 구현이 없으므로 solver_adapter의 E_UNSUPPORTED를 남긴다. geometry/step의 input_status=valid는 초기 입력 검사 통과이며 CAD 생성이나 STEP export 성공이 아니다. solver_ready는 항상 false다.

보고서는 revision/hash, purpose/profile, input_status, diagnostics와 전체 diagnostic_count를 포함한다. 최대 64개 진단을 반환하며 초과 시 diagnostics_truncated=true다. 작업의 completed는 검사 수행 완료이고 설계 합격 여부는 input_status로 따로 판단한다. snapshot 입력, 보고서 artifact, 전체 제조/해석 profile은 후속이다.

[initial_ifa.json](../fixtures/design/initial_ifa.json)은 초기 입력 기준으로 40 x 60 mm, 완성 두께 1 mm, 35 um 구리 2층, 2.4~2.4835 GHz와 50 ohm 조건을 기록한다. 완성 두께에서 구리 두께를 뺀 값은 mask 등을 분리하기 전 잔여 두께이며 실제 코어 두께 확정값이 아니다. 실제 물성, 세부 안테나 형상과 급전 배치는 미정이다. 해석 가능한 완성 보드로 취급하지 않는다.

## 시험 범위

평가/그래프 전파/순환/역명령, 구형 원본 보존, 설계 참조, 미정 물성, 목적별 차단과 실제 저장소 재시작을 단위/통합 시험으로 확인한다. RF 정확도, CAD 형상 품질, EM 해석과 실제 측정은 포함하지 않는다.
