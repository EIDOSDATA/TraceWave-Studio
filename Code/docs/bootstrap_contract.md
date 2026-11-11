# 초기 구현 계약 0.1

이 문서는 승인된 3.4의 일부를 구체화한 첫 개발 기록이다. 전체 schema/API/VT 완료 명세가 아니다. 구현 언어는 Python 3.12이며 stdlib만 사용한다. 분리한 native/CAD 환경은 [Python 환경](python_environment.md)과 [wxWidgets GUI](../ui/wxwidgets/README.md)를 따른다.

이하 읽기 전용 API 설명은 `--workspace` 없는 bootstrap/0.1 profile에 적용한다. 후속 구현한 프로젝트 명령과 영속 저장은 [프로젝트 저장 계약 0.2](project_persistence.md)를 따른다.

2026-11-11 확장: `catalog.status/search/get`과 선택적 `--catalog` 설정은 workspace 유무와 독립된 읽기 전용 기능이다. `capabilities.get.catalog_profile`에 구현 범위/상태를 반환하며 [카탈로그 조회 계약](pcb_catalog_contract.md)을 따른다. 아래 bootstrap의 최초 메서드 범위와 구분한다. 카탈로그 원문 JSON은 큰 정수와 미제공 필드를 보존하기 위한 별도 직렬화를 사용하며 프로젝트 수량/정규 codec으로 자동 변환하지 않는다.

## 단위와 미정값

`Quantity`는 value_si, dimension, display_unit, status, source_refs를 가진 불변 스칼라 타입이다. SI 값과 표시 단위는 별도로 유지한다. 출처 목록은 tuple로 복사한다.

- 길이 m/mm/um, 주파수 Hz/kHz/MHz/GHz, 시간 s/ms/us/ns, 각도 rad/deg를 지원한다.
- ohm, S/m, W/mW 및 무차원 단위 `1`을 지원한다. 각도와 무차원은 구분한다.
- user_entered/source_default/estimated는 명시한 유한 숫자를 요구한다.
- missing/not_applicable/unsupported는 None만 허용한다. 미정값은 0이나 FR-4 대표 상수로 치환하지 않는다.
- bool, 문자열 숫자, NaN/Infinity, 변환 overflow와 0으로 소실되는 underflow를 거부한다. 음의 0은 0.0으로 정규화한다.
- conflicting 후보/선택 근거, ComplexQuantity와 불확도/conditions는 후속이다. 표현식과 초기 물성 모델은 [설계 데이터 0.2](design_data.md)에서 제공한다. 현재 conflicting 생성은 오류다.
- 이 타입은 값의 양수 조건, 실제 재료 유효 대역, 주파수 grid 또는 물리적 타당성 전체를 검사하지 않는다.

## 정규 직렬화

`rfad.canonical/1.0`은 Python 서비스가 소유하는 내부 codec이다. RFC 8785 호환을 주장하지 않는다.

- 내장 None/bool/int/float/str/list/dict만 허용한다.
- UTF-8, BOM 없음, 불필요한 공백 없음, object key는 Unicode code point 순서로 정렬한다.
- float는 유한 float64의 Python repr 기반 round-trip 표현을 사용한다. -0.0은 0.0이며 표시 자릿수 반올림을 하지 않는다.
- integer는 -(2**53-1)..2**53-1 범위다. 더 큰 식별자는 schema에서 문자열로 설계해야 한다.
- 숫자 1과 1.0의 표현은 다르다. 도메인이 수량을 float64로, count/index를 integer로 먼저 정규화해야 한다.
- 배열 순서는 그대로 유지한다. 집합 정렬과 SI 단위 정규화는 호출한 도메인 계층의 책임이다.
- 문자열을 Unicode 정규화하지 않으며 잘못된 surrogate, 비문자열 key, 순환 참조를 거부한다.
- root depth=0, 자식 값마다 depth+1, 최대 depth=64다.
- `canonical_hash`는 `b'rfad.canonical/1.0\n' + canonical_bytes(value)`의 SHA256 소문자 hex다.

이 codec 자체는 snapshot/revision 생성이나 cache key의 물리 subset 선정을 구현하지 않는다. revision과 snapshot 적용은 [프로젝트 저장 계약](project_persistence.md)에 구현했고 물리 cache subset은 후속이다.

## 읽기 전용 API-001

wire 버전은 `rfad.api/2.0`이며 문서 버전 3.4와 구분한다. 현재 제공 profile은 `rfad.bootstrap/0.1`이다. `capabilities.get`의 params는 contract_version/context/input만 허용하며 context/input은 빈 object만 지원한다. runtime/feature 필터는 아직 지원하지 않고 오류로 거부한다.

현재 capabilities는 기초 조회를 implemented로, GUI/CAD/solver/저장을 declared로 표시한다. tested_envelopes는 빈 목록이고 실제 물리 검증 근거를 만들지 않는다. 변경 명령과 작업 접수는 미구현이다. durable journal이 없으므로 request key epoch를 발급하지 않고 idempotency_policy에 mutations_enabled=false를 반환한다.

전송 규칙:

- stdin/stdout의 UTF-8 NDJSON. stdout은 protocol, stderr는 로그다.
- 현재 handshake 전용 profile은 요청/응답 모두 줄 구분자 제외 최대 64 KiB다. 승인된 metadata 최대 1 MiB보다 좁은 초기 지원 범위다.
- LF/CRLF를 받고 EOF의 마지막 개행 없는 JSON도 처리한다. 빈 줄은 parse error다.
- batch 최대 16개, 각 문자열 UTF-8 최대 8192 bytes, JSON 최대 depth 64다.
- 줄을 제한 없이 모은 후 크기를 검사하지 않는다. 초과 입력은 E_RESOURCE 응답 후 남은 줄을 읽어 버리지 않고 서비스를 종료한다.
- batch 응답 전체가 제한을 넘으면 E_RESOURCE를 반환한다. 현재 모든 메서드는 읽기 전용이므로 이때 변경 부작용은 없다.
- 중복 key, 비유한 상수, 잘못된 UTF-8을 거부한다. 1e999 등 수치 overflow와 문자열/depth 한계 위반도 거부한다.
- 정상 envelope의 notification은 메서드/params 오류에도 응답하지 않는다. 파싱/구조/자원 한계 위반은 메서드 dispatch 전 frame 오류로 처리할 수 있다.
- 큰 배열/파일 전송, worker, queue, cancel/control 우선순위 및 durable replay는 아직 구현하지 않았다. job API를 추가하기 전에 별도 계약 시험이 필요하다.

오류 registry는 표준 JSON-RPC 코드와 별도로 E_VERSION=1001, E_RESOURCE=1002, E_SCHEMA=1003을 초기 정의한다. 알 수 없는 메서드는 -32601이다. 사용자 문구 대신 구조화된 코드를 판단 기준으로 사용한다.

공식 근거: [JSON-RPC 2.0](https://www.jsonrpc.org/specification), [Python JSON](https://docs.python.org/3.12/library/json.html). Python 기본 JSON decoder가 비유한 상수를 허용할 수 있으므로 이 구현에서는 별도로 차단한다.

## 환경 진단

doctor는 PATH에서 확인한 도구의 버전, 실행 파일 hash, 현재 Python 배포 메타데이터와 WSL 등록 상태를 기록한다. 등록된 배포판을 시작하지 않는다. 무거운 계산 패키지를 import하지 않으며 패키지 메타데이터 존재를 native 의존성의 실행 성공으로 간주하지 않는다.

질의는 shell 없이 인수 배열로 실행하며 각각 timeout이 있다. WSL UTF-16 출력을 해석하고 missing/failed/timeout을 구분한다. 보고서는 actual_environment 관찰 기록이며 dependency lock과 검증 합격 기록이 아니다. cl의 missing은 현재 PATH에서 찾지 못했다는 뜻이며 전체 PC의 모든 설치 경로를 탐색한 결과가 아니다.
