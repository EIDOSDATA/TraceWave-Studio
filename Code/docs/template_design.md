# 원호와 평면 IFA 템플릿의 최초 구현 설계 기록

이 문서는 구현 전 제안 기록이다. 명시 치수 원호/IFA 후보와 원자 적용을 이후 구현했으며, 현재 공개 API/저장 계약과 제한은 [템플릿 계약](template_contract.md), 실제 화면은 [목표/템플릿 GUI](target_template_gui.md)를 따른다. 아래 제안에서 달라진 필드나 상한은 현재 계약을 우선한다. 초기 합성식과 문헌 원본 재현은 여전히 후속 범위다.

작성일: 2026-11-12 KST. 기준은 승인 RFAD-D0-3.4의 FN-006/007과 RFAD 22다. 목표 원본은 [목표 계약](target_contract.md), 편집 서비스는 [목표 편집 계약](target_editor_contract.md)을 따른다.

## 1. 먼저 제공할 기능

사용자가 이미 만든 보드와 선택한 적층에, 명시적으로 입력한 치수의 원호 또는 평면 IFA 후보를 미리 보고 한 번의 명령으로 적용하는 기능을 제안한다. 적용 결과는 기존 2D 편집, 저장, snapshot 및 CAD 경로가 소비하는 실제 도메인 객체다. 목표 주파수를 자동으로 치수나 재료 기본값으로 바꾸지 않는다.

첫 slice의 읽기 전용 카드는 다음 두 종류로 한정한다. 일반 템플릿 importer, 사용자 등록, 임의 script 실행, RF 초기 합성식과 최적화는 후속이다.

| 제안 카드 | 입력과 결과 | 지원하지 않는 주장 |
| --- | --- | --- |
| `builtin.explicit_arc/0.1` | 명시 중심, 중심선 반지름, 시작각, signed sweep, 선폭과 feed path. 기존 원형 또는 직사각 보드에 적용 | 반지름/보드 지름/목표 주파수만으로 공진이나 효율을 보장하지 않음 |
| `builtin.explicit_planar_ifa/0.1` | 명시된 유한 직사각 ground, radiator, short, feed/pad의 위치와 폭. 첫 slice는 직사각 보드만 지원 | TI/Nordic 원본 재현, 자동 정합, 실물 SMA/launch 또는 검증 완료 IFA가 아님 |

카드의 출처는 TraceWave의 해당 생성기 버전과 설계 근거다. 원래 업체의 기하를 그대로 재현한 카드와 구분한다. 숫자 치수, 물성, 포트 저항을 숨은 기본값으로 채우지 않는다. 사용자가 필요한 값을 제공하지 않으면 후보 생성에 필요한 치수 부족과 후속 해석 입력 부족을 구분한다.

지원 상태는 `geometry_generator=true`, `seed_synthesizer=false`, `simulated=false`, `converged=false`, `measured=false`처럼 독립 필드로 기록한다. 이 필드들은 제안 계약이며 아직 제품 capability에 게시하지 않는다.

## 2. 기존 자료에서 재사용할 부분

| 현재 자료 | 확인된 의미 | 재사용 방식 |
| --- | --- | --- |
| `fixtures/design/initial_ifa.json` | 40 x 60 mm 초기 외곽과 표현식, 미정 물성. 안테나 형상과 포트 없음 | 보드/수량/미정 보존 회귀 입력으로 사용. 완성된 IFA 카드로 취급하지 않음 |
| `tests/test_pcb_ifa.py::ifa_document`, `fixtures/ifa_feed_smoke.json` | Dk 4.2, Df 0.018, 코어 0.93 mm, 구리 58 MS/m와 이상적 gap 급전을 명시한 시험 가정 | ground/short/feed의 의미 분리 및 연결 반례 시험을 재사용. 해당 물성을 제품 기본값으로 복사하지 않음 |
| `fixtures/pcb_worker_smoke.json`, `tests/test_pcb_solver.py::fixture_document(circle=True, arc=True)` | 반지름 8 mm 원형 보드와 선/원호, 8~12 GHz 범위의 합성 인터페이스 시험 | 원형 외곽 포함 여부, 원호 방향/단위와 CAD/해석 투영 보존 시험을 재사용. G031 또는 검증된 원형 안테나로 표시하지 않음 |
| `tools/verify_pcb_worker.py::create_fixture` | 여러 공개 명령으로 시험 모델을 순서대로 생성 | 제품 템플릿 적용 함수로 재사용하지 않음. 중간 실패 시 일부 객체만 적용될 수 있으므로 원자 명령이 필요 |
| `application/pcb_selection.py::PcbSelectionCoordinator` | 읽기 전용 preview, 입력/출처 해시 재검사, 단일 이력 명령 | 템플릿 후보의 서비스 조정 패턴으로 재사용 |

G031 자료는 `00_REF/PCB RF ANT/04_RF_Antenna_Extracted_Data/extraction/geometry/geometries.json`에 있다. 원문 ZIP은 `00_REF/PCB RF ANT/01_RF_Antenna_Vendor_Guides_CAD/Reference_CAD`에 있으며, 레코드의 과거 `files/Reference_CAD/...` 상대 경로를 현재 경로라고 가정하면 안 된다. 실제 manifest의 파일 및 archive member 해시를 확인해 연결해야 한다.

G031의 원호와 feed stub은 원자료 기하 재현용이다. 반지름 약 9.119930 mm, 선폭 1.27 mm, 시작각 약 106.870431 deg, CCW sweep 약 112.534634 deg의 원문 정밀도와 추출 근거를 보존해야 한다. 실제 보드에는 tab이 있으므로 body reference diameter를 완전한 원형 보드 외곽으로 바꾸면 원본 재현이 아니다. 시작 중심 반지름과 원문 끝점 사이 약 0.001041 mm 양자화 차이도 숨기지 않는다. G031은 위 두 내장 생성기가 아니라 후속 출처 카드로 별도 등록하는 것을 권장한다.

## 3. 입력과 안정 ID

제안 `template.synthesize`는 API-007의 제한된 `mode=explicit_geometry`만 지원한다. 아래 필드는 닫힌 schema로 검사하고 임의 추가 필드는 거부한다.

| 입력 | 검사와 보존 |
| --- | --- |
| `expected_revision` | preview가 읽을 현재 프로젝트 개정. 적용 시에도 동일 개정이어야 함 |
| `template` | `template_id`, `version`, `content_hash`를 모두 지정. 등록 카드의 정확한 사본과 대조 |
| `instance_id` | 새 템플릿 인스턴스 UUID. 기존 인스턴스와 충돌하면 거부 |
| `target_refs` | 사용자가 선택한 `{id, revision_id}` 목록. 현재 프로젝트의 정확한 목표 사본과 대조하며 없으면 빈 목록. 첫 목표를 자동 선택하지 않음 |
| `binding` | 현재 `board_id`, `frame_id`, `layer_id`, `material_id`. 보드/frame 일치, 실제 도체 층, 재료 참조를 검사. 층에서 재료가 미정이면 그 상태를 보존 |
| `explicit_inputs` | 카드별로 정의한 Quantity와 명시 기하 조건. 단위/미정/출처를 보존하며 미지원 표현은 거부 |

`target_refs`는 설계 의도 추적용이다. 목표 대역을 선택했다고 solver 설정을 자동 변경하거나 주파수에서 길이를 추정하지 않는다. 다른 목표 버전으로 다시 생성한 후보는 다른 입력 해시를 가진다.

생성 객체의 ID는 `instance_id`와 `radiator`, `short`, `feed`, `ground`, `port` 등 고정 semantic role로 결정적으로 도출한다. source의 UUID를 여러 프로젝트에 그대로 복사하지 않는다. 매개변수도 같은 규칙의 ID를 가지며 geometry는 해당 parameter reference를 사용한다. 좌표 유도는 명시적인 기하식과 표현식 DAG로 기록한다. 기존 프로젝트/개정/frame/parameter/design/target 및 target revision ID와의 충돌을 전부 검사한다.

IFA의 포트 recipe는 양극/기준 도체, gap 좌표, 방향, 기준면 설명, 저항 및 유효 대역을 사용자가 명시한 경우에만 실제 port로 만든다. 없으면 후보는 geometry-only이며 포트 입력을 미정으로 보고한다. IFA의 DC 연속 net과 RF 급전 gap을 혼동하지 않는다. 이상적 포트 recipe를 SMA/launch 측정 기준면 보정으로 표시하지 않는다.

## 4. 후보와 프로젝트 소유 출처

preview는 현재 프로젝트와 원자료를 변경하지 않는다. 결과에는 후보 ID, base project/revision/hash, card version/hash, generator version, target 사본, binding, 입력과 생성 객체 대응, geometry preview, 미정 입력, 제약 진단 및 `preview_hash`를 포함한다. S11, 효율, 공진 예측 그래프나 합격 상태를 생성하지 않는다.

현재 core `source_references`는 비어 있는 목록만 지원하므로 첫 slice에서 임의 활성화하지 않는다. 실제 설계 객체는 기존 core 필드에 저장하고, 출처 사본은 제안하는 typed extension `rfad.template-origin/0.1`에 둔다. 이 확장은 card snapshot/hash, 원자료 locator/hash, generator version, 입력 Quantity/source_refs, target 사본, ID mapping, assumptions 및 지원 범위만 보존한다. core 기하나 물성을 덮어쓸 수 없다.

템플릿 라이브러리 갱신은 이미 생성한 프로젝트를 변경하지 않는다. 이후 직접 편집한 값과 초기 채택값의 차이를 조회할 수 있도록 원 적용 사본을 유지한다. source snapshot을 저장했다는 사실을 문헌 측정 성능의 승계나 실제 소재 검증으로 취급하지 않는다.

현재 PCB solver는 알려진 PCB 선택 확장 이외의 확장을 거부한다. 따라서 이 후속 기능을 구현할 때는 프로젝트 validator에서 새 origin 확장을 검증한 뒤, solver에서 해당 provenance 전용 namespace만 허용하는 변경도 필요하다. 임의 extension 전체를 허용하거나 target/core 의미를 우회하는 확장을 만들면 안 된다. 저장 core 형식은 0.3을 유지하는 제안이지만, 상세 구현에서 새로운 core 의미가 필요해지면 별도 schema/migration 검토를 먼저 한다.

## 5. 원자 적용과 undo

공개 적용은 제안 `template.apply` 확장으로 전달한다. 이는 승인 API-003의 프로젝트 명령과 동일한 writer, receipt, expected_revision, command_id 및 영속 history를 사용해야 하며 별도 저장소를 만들지 않는다. 서비스가 preview를 재계산하고 해시와 card/source version을 대조한 뒤 내부 `template_instance.apply` 한 번을 게시한다. 이 이름들도 현재는 미구현 제안이다.

전체 후보를 복제본에 구성한 후 ID/단위/표현식 cycle/참조/출처/예산 및 전체 설계 검증에 성공한 경우에만 새 개정을 기록한다. generated 객체 일부를 먼저 공개하거나 사용자 명령을 여러 개로 나누어 순차 게시하지 않는다. 적용 이후 자료가 부족해 EM이 차단되는 것과 저장 자체의 실패를 구분한다.

원자성 규칙은 다음과 같다.

- source/card/input/target/binding/현재 개정 중 하나라도 preview와 다르면 적용을 거부한다.
- 같은 request_key의 재접수는 원 응답을 돌려준다. 새 request_key로 같은 instance를 중복 생성하면 충돌을 반환한다.
- 외부 caller의 임의 프로젝트 patch는 받지 않는다. 허용된 객체와 명시 생성 recipe만 서비스가 구성한다.
- inverse는 이전의 정확한 객체와 출처 사본을 보존한다. undo/redo가 현재 라이브러리나 새 generator를 다시 실행하지 않는다.
- inverse 적용도 현재 참조 무결성을 검사한다. 관련 없는 사용자 입력, target, 카탈로그 출처 및 과거 raw 결과를 삭제하지 않는다.
- 물리 형상이 달라지므로 기존 `revision`, `geometry`, `physics`, `network`, `metrics`, `assessment`, `exports` 무효화 vocabulary를 사용한다.

## 6. 기하 검사와 증거 한계

원호는 `0 < abs(sweep) < 2*pi`, 중심선 반지름과 폭의 관계, inner radius, 실제 시작/끝 및 feed 연결을 검사한다. 0도, 360도, 여러 회전을 같은 열린 원호로 처리하지 않는다. circle bounding rectangle 안에 있다는 이유만으로 실제 원형 보드 내부라고 판단하지 않는다.

IFA는 finite ground와 radiator/short/feed의 명시 관계, short의 실제 평면 접촉, 급전 gap, 허용 공간 및 층을 검사한다. 전층 copper keepout 전체를 검증하는 제조 DRC가 준비되기 전에는 해당 항목을 `not_evaluated`로 남긴다. 최소 폭/간격의 제조 합격은 제조 profile과 근거가 있을 때만 판단한다.

현재 `pcb_contacts.validate_native_contacts`는 도전율/두께를 포함한 native 투영 입력을 요구한다. 미정 물성의 geometry-only preview에 그대로 호출하지 않는다. 평면 기하 검사를 별도로 분리하고 물리 입력이 완비된 뒤 기존 PCB plan의 실제 접속 검사를 사용한다. CAD plan 생성 성공도 native STEP 출력이나 독립 제조 검증 성공과 구분한다.

## 7. 대상 파일과 검증 사례

제안 모듈은 `templates/cards.py`, `domain/template_geometry.py`, `domain/template_instance.py`, `domain/template_command.py`, `application/template_candidates.py`다. 기존 프로젝트 명령/검증, RPC capability, PCB solver의 알려진 확장 경계에 필요한 연결만 추가한다. 출처 카드가 많아지기 전부터 PCB 재료 SQLite와 같은 의미인 것처럼 섞지 않는다.

`tests/test_template_candidates.py`에서 다음을 확인하는 것을 첫 종료 조건으로 제안한다.

| 사례 | 기대 결과 |
| --- | --- |
| 두 프로젝트에서 같은 카드/입력으로 preview | 의미 기하는 동일하고 인스턴스/프로젝트 ID는 독립. 원본 및 journal 불변 |
| 원형 보드 원호와 직사각 IFA 적용 | 실제 객체가 기존 2D DTO/저장/재열기/CAD plan에 연결. 카드 지원 범위를 벗어난 보드 종류는 명시 거부 |
| 물성/동박/포트가 미정인 입력 | 가능한 geometry 저장. EM 부족 입력 차단. 4.2/0.018/58 MS/m/50 ohm 자동 삽입 없음 |
| 0/360도 원호, inner radius<=0, 원 밖 패턴 | 잘못된 기하를 clamp하거나 축소하지 않고 구체 진단 |
| IFA short 단절 또는 feed gap 접촉 오류 | 해당 topology 실패. 외형이 비슷하다는 이유로 유효 IFA 표시 금지 |
| target ID/revision, binding 또는 preview hash 불일치 | 적용 거부와 원본/receipt/history 불변 |
| 적용 중 한 객체 오류 또는 디스크 실패 주입 | 일부 객체/출처만 공개되지 않음 |
| 저장/재시작/undo/redo/중복 재접수 | 원본/출처와 정확한 생성 사본 보존. 업데이트된 카드로 재합성하지 않음 |
| 카드 변경 또는 출처 hash 위조 | 기존 프로젝트는 그대로 유지하고 새 적용은 다시 검토 |
| 완비된 명시 시험 입력의 PCB/CAD plan | 출처 사본 유지, 설정과 실제 미정 소재 변조 없음. native/제조/측정 합격 주장 없음 |

FN-006 전체 카탈로그 등록/import, G031 원문 재현, 주파수 기반 seed, RF 목표 평가, full DRC와 물리 성능 검증은 이 첫 slice의 완료 범위 밖이다.
