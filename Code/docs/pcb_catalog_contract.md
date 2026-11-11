# PCB 카탈로그 모델과 SQLite 조회 계약

작성일: 2026-11-11 KST. 승인 기준선: RFAD-D0-3.4. 구현 profile: `rfad.catalog/0.1`, 변환 규칙: `rfad.catalog.import/1`.

이 문서는 [PCB 재료 카탈로그 설계](pcb_material_catalog.md)의 중립 모델, 오프라인 변환, 읽기 전용 검색과 상세 조회를 정의한다. 기존 사용자 직접 입력과 프로젝트 schema `rfad.project/0.2`는 유지한다. 후속으로 구현한 프로젝트 소유 출처 사본, 적층 초안/미리보기와 원자적 적용은 [PCB 선택 계약](pcb_selection_contract.md)을 따른다. GUI 제조업체 선택 화면은 아직 연결하지 않았다.

## 모듈과 데이터 경계

| 모듈 | 책임 |
| --- | --- |
| `catalog/models.py`, `properties.py` | 안정 ID, 출처, 제품 표기 그룹, 적층 표기 그룹, 물성값/조건의 제한된 표시 모델 |
| `catalog/source.py`, `build.py`, `schema.py` | 자료 계약/해시 검사, 스트리밍 변환, SQLite 스키마/인덱스, 원자적 발행 |
| `catalog/review.py` | 누락/상충/그룹 두께/자성 등 자료 검토 사유. 실행 가능 판정과 분리 |
| `catalog/native*.py` | JLCPCB/PCBWay/Wurth의 서로 다른 원시 자료 형식, 출처와 배열 순서 보존 |
| `catalog/query.py`, `repository.py`, `service.py` | 허용 필터, SQLite 읽기 트랜잭션, 응답 상한/페이지/상세 DTO |
| `application/catalog_api.py`, `cli/catalog.py` | 같은 조회 서비스를 JSON-RPC와 CLI에 연결 |

런타임은 오프라인 생성한 SQLite만 읽는다. 전체 JSONL, 엑셀, PDF/HTML이나 CAD/NumPy/openEMS를 시작 시 로딩하지 않는다. 원문 문서의 해시 확인과 JSONL/원시 적층 변환은 명시적 build 명령에서 수행한다. 원문 PDF/HTML의 새로운 추출이나 외부 URL 재수집은 이 단계에 포함하지 않는다.

| 검색 개체 | 의미와 ID |
| --- | --- |
| `sources` | 원래 `source_id`, 공개 주체, URL, 제목, 보관 경로와 상태 |
| `products` | 공개 주체/제품명/자료 역할/명시적 소재 공급사를 구분한 제품 표기 그룹 |
| `observations` | 원래 `record_id`, 출처, 전체 원문 필드/타입, 검색 열과 검토 사유 |
| `stackups` | 공개 주체와 원래 적층 ID의 표기 그룹. 치수가 상충하면 검색용 단일값을 확정하지 않음 |
| `native_templates` | 출처와 원시 template ID/파일 식별자를 포함한 원시 적층 후보 |
| `native_components` | template에 속한 순서 있는 원시 구성 행. 검증된 물리 층과 구분 |
| `native_evidence` | 페이지 envelope, audit 등 복원과 검토에 필요한 보조 원문 |

제품명/적층명 그룹 수는 고유 소재 수나 제작 가능한 기판 수가 아니다. 원시 template와 정규 적층의 연결도 공개 라벨 관계이며 실물 구조의 동등성을 승인하지 않는다. JLC custom/placeholder 460개도 원시 template로 보존한다.

원래 필드의 미제공, `null`, boolean, 정수, 실수, 문자열, 배열을 `raw_json`과 SHA-256으로 보존한다. JavaScript의 안전 정수 범위를 넘는 원시 ID도 JSON 문자열 조각 안에 유지한다. 클라이언트가 숫자 정밀도를 잃는 파서로 이를 다시 해석하지 않도록 해야 한다. 검색용 숫자 열과 표시 DTO는 파생 자료이며 원문을 대체하지 않는다.

`catalog_id`는 스키마, 변환 규칙 버전, 원본 manifest 및 전체 관측 정규 해시를 포함한다. 변환/검토 의미가 바뀌면 변환 규칙 버전을 올린다. 제품/적층의 안정 ID는 설치 경로나 엑셀 파일명에 의존하지 않는다. build 시각은 개정 ID에 포함하지 않는다.

## 물성 조건과 검토 규칙

관측 상세의 `properties`는 Dk/Df 각각의 단일값/범위/한정자/원문 문자열과 주파수/시험법을 제공한다. 값 종류는 `scalar`, `range`, `scalar_and_range`, `qualified`, `text_only`, `missing`이다. 무차원 값의 단위는 `1`이고 주파수는 보고된 GHz 및 단순 환산 Hz를 함께 제공한다.

공통 `frequency_ghz`와 `method`는 record 조건으로 보존한다. Df 전용 조건은 `df_frequency_ghz`, `df_method`가 있을 때만 채운다. 공통 조건을 Df의 별도 시험 조건으로 복사하지 않는다. 별도 Df 조건이 없는 행도 원문과 record 조건을 확인할 수 있다. 선택 API는 Dk/Df를 각각 지정하고 서로 다른 조건과 미정 조건을 검토 사유로 반환한다.

범위의 중간값, 다른 주파수의 보간값, 누락된 손실의 0, 기본 FR-4 상수나 실제 제조 두께를 생성하지 않는다. 검색과 상세는 항상 `readiness: not_assessed`를 반환한다. 자료의 원래 `simulation_ready` 표기도 원문 메타데이터일 뿐 현재 solver 승인으로 사용하지 않는다.

JLC 비양수 ply, PCBWay 여러 ply의 합계, Wurth 층 접두가 겹치는 원시 필드는 원문과 검토 사유를 함께 보관한다. 제조업체 원시 구성 행을 곧바로 프로젝트의 층으로 만들지 않는다. 이방성/자성/내부 동박 등의 검색 가능 여부도 현재 CAD/solver 지원 여부와 분리한다.

## 오프라인 구축과 실행

다음 명령은 `Code`에서 서비스 Python 환경으로 실행한다. 생성 DB와 보고서는 Git에서 제외한 `.local`에 둔다.

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 -m rfad catalog build `
  --source '../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026' `
  --output '.local/pcb-catalog/catalog.sqlite'

.\.venv\Scripts\python.exe -X utf8 -m rfad catalog status `
  --database '.local/pcb-catalog/catalog.sqlite'

.\.venv\Scripts\python.exe -X utf8 -m rfad serve `
  --workspace '.local/workspace' --catalog '.local/pcb-catalog/catalog.sqlite'
```

기존 DB를 갱신할 때만 build에 `--replace`를 붙인다. 원문 패키지 내부 경로, 원문과 같은 hardlink, 임의 기존 문서나 다른 SQLite DB 덮어쓰기를 거부한다. 새 임시 DB에 전체 변환/FK/무결성/해시 검사를 완료하고 입력이 변경되지 않았는지 확인한 뒤 원자적으로 발행한다. 실패하면 기존 DB를 보존한다. 원문 폴더를 편집하거나 정리 엑셀을 다시 저장하지 않는다.

`--catalog`를 생략해도 기존 프로젝트 서비스를 사용할 수 있다. 카탈로그가 미설정/누락/손상되면 `catalog.status`에 이유를 반환하고 카탈로그 검색만 실패한다. 읽기 전용 연결은 `mode=ro`, `query_only=ON`, `trusted_schema=OFF`를 사용하며 임의 SQL과 요청별 파일 경로를 받지 않는다. 검색 진행 중 DB가 교체되어도 각 요청은 단일 읽기 트랜잭션의 개정과 결과를 사용한다.

CLI 검색 입력은 JSON 파일로 전달할 수 있다.

```powershell
'{"entity":"observations","filters":{"publisher":"Rogers","frequency_property":"dk","frequency_ghz":10},"limit":25}' |
  Set-Content -LiteralPath '.local/pcb-catalog/query.json' -Encoding utf8
.\.venv\Scripts\python.exe -X utf8 -m rfad catalog search `
  --database '.local/pcb-catalog/catalog.sqlite' --query-file '.local/pcb-catalog/query.json'
```

상세는 검색 결과의 `entity`, `id`, `catalog_id`를 `catalog get --entity ... --id ... --catalog-id ...`로 전달한다. CLI 성공은 stdout JSON과 종료 코드 0, 오류는 stderr JSON과 종료 코드 1이다. 상태 조회의 성공은 DB 준비 완료와 별개이므로 `state`/`available`을 확인한다.

## API와 페이지 계약

기존 `rfad.api/2.0`에 `catalog.status`, `catalog.search`, `catalog.get` 확장 메서드를 추가했다. `capabilities.get.catalog_profile`에서 지원 범위와 현재 상태를 읽는다. 모두 읽기 전용이고 프로젝트 context, request_key, job, revision을 만들지 않는다. 별도 MCP 서버 자체를 추가한 것은 아니며 자동화/향후 MCP adapter가 같은 조회 경계를 사용할 수 있다.

```json
{
  "jsonrpc": "2.0",
  "id": "pcb-search-1",
  "method": "catalog.search",
  "params": {
    "contract_version": "rfad.api/2.0",
    "context": {},
    "input": {
      "entity": "observations",
      "filters": {"publisher": "Rogers", "frequency_property": "dk", "frequency_ghz": 10},
      "limit": 25
    }
  }
}
```

`catalog.status`의 input은 빈 객체다. `catalog.search`는 `entity`, 선택적 `filters`, `query`, `limit`, `offset`, `catalog_id`를 받는다. 기본 limit 25, 최대 100이다. 문자열 filters는 정확 일치이며 `query`는 허용된 표시 필드의 리터럴 부분 문자열 검색이다. `%`, `_`, 역슬래시는 SQL wildcard로 해석하지 않는다. SQL 값은 바인딩하고 허용되지 않은 개체/필터를 거부한다.

| 개체 | 주요 filters |
| --- | --- |
| observations | publisher, product, product_id, stackup_id, source_id, dataset_role, material_form, value_type, review_flag, frequency_ghz, frequency_property, frequency_mode, thickness_mm/min/max, layer_count |
| products | publisher, product, dataset_role, laminate_manufacturer |
| stackups | publisher, source_stackup_id, layer_count, nominal_thickness_mm/min/max, native_available |
| sources | publisher, local_available |
| native_templates | publisher, template_key, stackup_id, source_id, kind, review_flag |
| native_components | publisher, template_id, stackup_id, source_id, kind, review_flag, component_order |
| native_evidence | kind |

두께 범위 필드의 실제 이름은 `thickness_min_mm`, `thickness_max_mm`, `nominal_thickness_min_mm`, `nominal_thickness_max_mm`다. 주파수를 지정하면 `frequency_property`도 필수다. `record`는 공통 조건만, `dk`는 Dk 수치/범위가 있는 관측의 공통 조건, `df`는 Df 수치/범위가 있는 관측의 전용 `df_frequency_ghz`만 조회한다. 기본 `frequency_mode: exact`는 점 일치, `contains`는 record/Dk에서 명시적 점 또는 발표된 주파수 범위를 포함한다. Df에 공통 범위를 대신 적용하지 않는다. 모두 값 보간이나 대역 유효성 승인을 하지 않는다.

결과의 `items`, `returned_count`, `has_more`, `next_offset`, `catalog_id`를 사용한다. UTF-8 응답 상한 때문에 limit보다 적게 반환할 수 있으므로 요청 limit을 offset에 더하지 않는다. offset이 0보다 크면 이전 응답의 `catalog_id`가 필수이며 개정 불일치는 `E_CONFLICT`다. 개정이 바뀌면 첫 페이지부터 다시 검색한다. 합계 계산을 매번 강제하지 않으며 실제 반환 행과 다음 페이지 여부를 제공한다.

`catalog.get`은 `entity`, `id`, 선택적 `catalog_id`, `raw_offset`, `raw_limit`을 받는다. `raw_offset > 0`인 후속 조각에는 이전 응답의 `catalog_id`가 필수다. 원문 조각 offset은 UTF-8 바이트가 아닌 Unicode code point 기준이다. 기본 4,096자, 최대 8,192자이며 응답 바이트 상한 때문에 더 짧아질 수 있다. `raw.next_offset`을 그대로 사용하고 마지막 `complete: true`까지 조합한 UTF-8 문자열을 `raw.sha256`과 비교한다. `complete`는 해당 조각으로 원문 끝에 도달했다는 뜻이다. offset 0부터 한 번에 전체가 들어오는 경우 서비스도 해시를 확인한다.

검색 요약에는 전체 원문을 넣지 않는다. 긴 요약/물성 설명은 `truncated_fields`로 축약을 알리고 상세 원문에 전체를 보존한다. 결과 상한은 48 KiB이며 기존 RPC 프레임 64 KiB 및 최대 요청 ID 공간을 남긴다. 기존 batch 전체 응답 상한도 유지되므로 큰 조회 여러 개는 개별 프레임으로 요청한다. SQLite VM 실행량과 대기 시간도 제한한다.

## 전체 자료 검증

단위/통합 시험은 `tests/test_catalog_*.py`, 실제 자료 검증은 다음 도구로 재실행한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_catalog*.py' -v
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_catalog.py `
  --source '../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026' `
  --database '.local/pcb-catalog/catalog.sqlite' --report '.local/pcb-catalog/verification.json'
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_catalog_native.py `
  --source '../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026' `
  --database '.local/pcb-catalog/catalog.sqlite'
```

첫 도구는 모든 JSONL 관측의 키/타입/값과 SHA-256, SQLite 무결성/FK, 모든 개체의 전체 페이지, 위험 사례, 최대 상세 JSON의 조각 복원과 독립 프로세스 조회 성능을 확인한다. 둘째 도구는 37개 원시 적층 JSON의 포인터/순서/값/타입 및 전체 문서 복원을 대조한다. 조회 성능 도구는 `pcb_catalog_performance.py`로 분리했고 OS 디스크 캐시는 제어하지 않는다. 그 수치를 GUI 시작 메모리, 60/30 fps, build 메모리나 RF 정확도로 해석하지 않는다.

실측 결과와 코드 식별자는 [개발 상태](development_status.md) 및 `runtime_profiles/pcb-catalog.json`에 기록한다. 원문 패키지의 모든 문서를 재배포해도 된다는 권리 승인을 포함하지 않는다. 현재는 내부 검증용 자료 경로와 파생 DB를 사용한다.

## 다음 연결 단계

`catalog.stackup_draft`와 `pcb.selection.preview/get/apply`를 추가했다. 전자는 기존 빈 context의 읽기 전용 카탈로그 API이고, 후자는 workspace의 프로젝트 개정/영수증/undo를 사용한다. `rfad.pcb-stackup-draft/0.1`과 프로젝트 확장 `rfad.pcb-selection/0.1`의 필드, 제한과 실행 예시는 [PCB 선택 계약](pcb_selection_contract.md)에 있다. 다음 단계는 wxWidgets 기판 설정의 직접 입력/소재/제조업체 선택과 미리보기 화면, 선택된 실제 2층 재료의 CAD/solver 통합 검증이다.
