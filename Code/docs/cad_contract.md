# CAD 입력과 STEP 기계 형상 계약

초기 구현일: 2026-11-10 KST

도체 영역/패드/관통 비아 확장일: 2026-11-11 KST

승인 기준선 RFAD-D0-3.4의 07, 08, 11, 12번을 따른다. GUI/서비스와 native CAD worker를 분리하고 봉인된 snapshot에서 파생 형상을 만든다. 현재 profile은 내부 검증용 기계 형상이며 제조 전달, RF 검증이나 R1 전체 완료를 의미하지 않는다. 원본 기준선 문서는 변경하지 않는다.

## 불변 입력

`application/cad.py`의 `build_cad_input(document, snapshot_ref, profile)`은 표준 라이브러리와 순수 도메인 코드만 사용한다. CadQuery/OCP/NumPy를 서비스 시작 경로에서 import하지 않는다. snapshot artifact의 파일 수명/바이트 hash와 workspace 등록 여부는 서비스가 확인하고, 이 함수도 project_id/revision_id/schema_version/canonical_version/content_hash를 원본과 대조한다. snapshot_id는 project_id나 revision_id의 별칭이 아니다.

원본을 수정하지 않는 새로운 `rfad.cad-input/0.1` JSON을 반환한다. 입력은 `rfad.step.mechanical/0.1` profile, snapshot, source_hash, project_id/revision_id, 명시적 단위/변환, 정규화한 board/layers/shapes와 원본 source_semantics를 가진다. worker는 staging에 고정한 입력과 실제 소비한 입력의 hash를 대조한다. 편집 중인 현재 개정이 바뀌어도 완료 결과의 입력 snapshot은 바뀌지 않는다.

`source_semantics`에는 원본 문서의 Quantity/status/parameter binding, material/net/port와 출처를 보존한다. 이는 STEP가 RF 물성을 자체적으로 보존한다는 주장이 아니다. 제품 adapter의 native 코드나 사용자 Python, 임의 명령 문자열을 프로젝트에서 실행하지 않는다.

## 지원 profile과 기하

| 항목 | 현재 규칙 |
| --- | --- |
| 외형 | board 원점 (0, 0)의 직사각형 또는 명시적 중심/반지름의 원형 |
| 좌표계 | 오른손 world/board의 항등 translation/rotation. 미지원 회전/반사는 차단 |
| 단위 | 원본 m/rad, kernel mm/deg. scale_to_kernel=1000, inverse_scale=0.001 |
| 적층 | order/z 순서, 명시적 z_min과 양수 두께. dielectric 또는 conductor |
| 유전체 | 실제 위치/두께가 있는 층이 최소 하나 필요. 사각 외형의 box 또는 원형 외형의 정확 cylinder solid |
| 도체 | 양수 finished thickness의 line_path/arc_path, planar_region, pad, 명시적 중공 through-PTH via |
| 원호 | 중심선 반지름, 시작 각도, signed sweep 유지. 양수 CCW, 음수 CW, 한 바퀴까지 |
| 영역 | straight-edge outer와 명시적 holes. 비볼록 허용, 원본 winding 보존, 실제 inner wire로 압출 |
| 패드 | circle 또는 회전 rectangle, 실제 소속 동박 층의 두께. 화면용 추가 높이 없음 |
| 비아 | 최하/최상 conductor 사이의 실제 중공 annular barrel과 drill 제거, 명시적 양단 pad/net |
| 포함 | include_in_export=false인 형상은 생략하고 안정 ID와 사유를 기록 |
| 물성 | 실제 RF 물성 미정은 원본 그대로 보존. 기하 계산에 쓰지 않으며 FR4 상수를 채우지 않음 |
| 병합 | 같은 층/같은 명시적 net/같은 유효 재료만 병합 대상. 원본 UUID 대응은 유지 |
| 출력 | AP242를 요청하고 실제 FILE_SCHEMA를 확인. AP214로 조용히 대체하지 않음 |

conductor 층이 있다고 전체 board를 copper로 채우지 않는다. 해당 층의 명시적 패턴만 출력한다. bare board는 유전체 형상만 출력할 수 있다. 기판 두께나 층간 간격을 채우는 임의 코어도 생성하지 않는다. native 생성 후 원형 끝단까지 기판 외형 안에 있는지 확인하며, 밖으로 나온 패턴은 자동으로 자르지 않고 이 profile에서 차단한다. 제조사별 최소 가장자리 간격과 공정 DRC는 별도 검증 대상이다.

coating/adhesive/air는 coverage의 의미가 아직 정의되지 않아 이 profile에서 차단한다. mask를 전체 표면에 임의로 채우거나 유전체 두께에서 역산하지 않는다. blind/buried/microvia, filled via, 독립 NPTH/slot, 변형 기판, 부품/케이스는 현재 이 profile의 지원 범위 밖이다. unsupported를 다른 단순 형상으로 대체하지 않는다.

### 영역, 패드와 PTH 입력

원본 수량과 객체 계약은 [도체 기능 계약](copper_features.md)을 따른다. CAD 투영은 `planar_region.outer_mm/holes_mm`, `pad.center_mm/size_mm/rotation_deg`, `via.center_mm/finished_hole_diameter_mm/plating_thickness_mm/tool_hole_diameter_mm`를 사용한다. 영역은 외곽과 모든 hole을 합해 64점, 최대 8 holes이며 반복 닫힘점을 넣지 않는다. 실제 압출을 위한 wire 방향만 파생하고 원본 점 순서와 Quantity/parameter binding은 바꾸지 않는다. 자기교차, 경계 접촉, 중첩 holes, 최소 변 길이 또는 경계 간격 미달을 조용히 치유하지 않는다.

circle pad의 size 두 값은 같은 지름이다. rectangle은 중심과 width/height, CCW 회전을 사용한다. 각 pad는 한 conductor 층에 속하며 여러 층의 패드는 별도 객체로 만든다. 패드를 만들었다는 이유로 mask/paste, 부품이나 자동 net을 만들지 않는다.

via의 `layer_id`는 시작 conductor, `end_layer_id`는 끝 conductor다. 초기 CAD는 적층의 최하/최상 conductor를 잇는 through-PTH만 지원하며 양끝 conductor 바깥에 추가 적층이 있으면 차단한다. 같은 명시적 net과 같은 유효 material 참조를 가진 pad 2~8개를 참조하고 양 끝에 실제 pad가 있어야 한다. 유효 재료는 원본 material_ref 또는 소속 층의 material_id이며, 미정 RF 물성을 채우지 않는다. pad에는 outer barrel보다 최소 1e-5 mm 큰 연속 annular 접속 여유가 필요하다. 이 수치는 CAD 수치 경계이며 제조사의 annular-ring 설계 규칙을 대신하지 않는다.

finished bore 반지름을 r, 명시 plating 두께를 t로 읽고 outer barrel 반지름 r+t의 drill 공간을 유전체와 해당 도체에서 제거한다. 그 공간에 내부 반지름 r, 외부 반지름 r+t인 중공 barrel만 넣는다. tool bore가 미정이면 null을 보존하고 modeled drill의 산술 근거를 sidecar에 기록한다. 알려진 tool bore가 `finished bore + 2 * plating`과 CAD 허용오차 이내로 맞지 않으면 이 초기 profile에서는 차단한다. 이는 제조 보정/공차 모델을 자동 확정하는 기능이 아니다.

fill은 명시적 `none`만 지원한다. 자동 copper fill, antipad, thermal relief, pad 생성 또는 외곽 clipping은 하지 않는다. 겹치거나 접한 drill, 사라지는 원본 body, 비아 범위/패드 접속 불일치는 실패다. drill로 잘린 다른 net 또는 다른 유효 재료의 도체가 barrel에 닿으면 E_CONNECTIVITY로 차단한다.

## 수치와 자원 경계

이 profile의 수치 제한은 제작 공차가 아닌 초기 adapter 수용 범위다. 원본 저장의 숫자 범위를 변경하지 않는다.

| 값 | 초기 CAD profile |
| --- | --- |
| kernel/재입력 허용오차 | 1e-6 mm |
| 최소 양수 치수/두께/중심선 길이/내부 반지름 | 1e-5 mm |
| 최소 명시적 층간 간격 | 1e-5 mm. float64 산술 오차 범위의 접면은 같은 경계로 취급 |
| 좌표/치수 절댓값 상한 | 1e6 mm |
| 시작 각도 절댓값 상한 | 1e6 deg |
| 원호 회전량 절댓값 하한 | 1e-6 deg |
| 포함 도체 패턴 수 | 최대 128개 |
| region 점/holes | 외곽과 holes 합계 64점, 최대 8 holes |
| via pad 참조 | 최대 8개, 양끝 층의 실제 pad 최소 2개 |

미정 보드 치수, 층 위치와 두께는 접수 전에 차단한다. 도체 폭/좌표/반지름에 대한 UUID 매개변수 참조는 봉인된 원본의 Quantity에서 평가하며 sidecar에서는 원래 binding을 보존한다. 표시 mesh나 선분 근사로 원호를 대체하지 않는다. 접촉/중복/짧은 간격과 Boolean 결과의 topology는 native 단계에서도 확인해야 한다.

고정된 profile_definition과 tolerance_mm을 입력에 함께 기록한다. 동시 실행은 workspace당 CAD 한 개, 기본 실행 제한은 120초다. 출력은 파일별 64 MiB/전체 128 MiB/16개, stdout+stderr는 전체 1 MiB와 각각 마지막 16 KiB를 보존한다. 출력 파일은 0.1초마다 검사하므로 검사 사이 일시적 상한 초과는 가능하다. 최종 봉인에서도 크기/hash를 다시 검사한다. 프로세스 메모리와 시작 시간/편집 fps 예산은 아직 실측 수용하지 않았으며 OS 메모리 hard limit을 구현한 것으로 간주하지 않는다.

부분 원호가 180 deg를 넘고 끝단 간 chord 간격이 선폭과 최소 간격 이하이면 round cap이 자기 중첩할 수 있어 명시적으로 차단한다. 완전한 +360/-360 deg는 cap 없는 ring으로 지원한다. 같은 net이어도 다른 층 또는 다른 유효 재료의 body는 자동 병합하지 않는다. 명시적 via가 drill한 같은 net/같은 재료 도체와 barrel의 실제 접면만 다층 접속으로 허용하며, 그 외 다층 접촉은 미지원으로 차단한다.

## 결과와 검증의 범위

STEP의 body 이름과 sidecar의 안정 UUID mapping, source snapshot/run/profile, 실제 schema/단위, 파일 SHA256을 결합한다. substrate와 copper를 병합해 재료 구분을 없애지 않는다. 파일/sidecar가 같은 basename이라는 이유만으로 대응시키지 않는다.

barrel은 `via_barrel_<UUID>` 별도 body이며 source_entity_ids에 via를 기록한다. display mesh의 기존 단일 layer_id는 start layer anchor로 유지하고 sidecar의 `layer_ids`, `layer_id_semantics`, `vertical_span_mm`, pad_ids가 실제 다층 범위를 명시한다. drilled body의 drill_source_ids와 원본 via를 함께 보존한다. 같은 층의 region/pad가 union되어도 명시적 pad 참조를 잃지 않는다. STEP 생성 전과 재입력 후 모두 annular hole, 양끝 pad 접촉과 다른 body 부피 중첩을 검사한다.

실제 writer/reader와 kernel 버전, shape validity, solid count, bbox/volume/center 및 단위 비교를 기록한다. 같은 Open CASCADE kernel에서 다른 reader 경로로 재열어도 kernel 독립 검증으로 표시하지 않는다. 외부 수신 CAD의 선택/측정/숨김, 제조 공정과 RF 정확도 검증은 후속이다. 초기 기계 형상은 `generated_unverified` 상태를 유지하며 생성/재입력 성공을 `verified_profile` 제조 패키지로 승격하지 않는다.

현재 순수 projection 시험은 snapshot 불일치/원본 변경/미정 필수 치수/unsupported coverage/좌표 변환/작은 두께와 층간 간격/원호 내부 반지름/큰 좌표/형상 수 상한을 차단하고, mm 변환/방향/재료 미정/원본 binding과 포함 제외를 보존하는지 확인한다. worker와 실제 native 출력 검증 결과는 [개발 상태](development_status.md)에 기록한다.

`test_cad_copper_features.py`는 신규 projection 4건과 실제 CAD 9건을 포함한다. 비볼록 영역/holes와 winding, 회전 pad의 실제 두께, 원본 문서부터 STEP까지의 PTH, substrate/pad drill 체적, hollow barrel 단면, 접지 영역과 pad union의 접속, tool 미정 보존, 다른 net 접촉 및 잘못된 기하 거부를 확인한다. 격리 `.venv-cad`에서 13건 모두 통과했으며 같은 OCCT kernel의 교환 검사이다. 제조 또는 RF 정확도 합격으로 승격하지 않는다.

## 표시 mesh와 3D 화면

`mesh.json`은 `rfad.display-mesh/0.1` 표시 전용 artifact다. 정확한 STEP/B-rep를 먼저 저장한 뒤 같은 OCCT body를 삼각화한다. 목적은 `display_only`, 길이 단위는 mm이며 solver mesh 또는 제조 출력으로 사용하지 않는다. 선/원호의 정확한 CAD 형상이나 실제 층 두께를 표시 근사로 바꾸지 않는다.

입력 결합은 전체 SnapshotRef와 run_id를 보존한다. 각 body는 id/source_entity_ids/layer_id/role, 3차원 vertices와 0부터 시작하는 triangles 색인을 가진다. 원본 UUID와 역할은 sidecar의 body_map과 일치해야 한다. 같은 net으로 병합한 body도 모든 원본 source_entity_ids를 유지한다. body 순서나 face 색인을 원본 객체 식별자로 사용하지 않는다.

표시 삼각화는 절대 선형 deflection 0.05 mm, 각도 deflection 0.15 rad로 고정한다. 현재 상한은 합계 100000 triangles, 300000 vertices와 16 MiB 파일이다. native와 host가 비어 있는 면, 유한하지 않은 좌표, 잘못된 색인/퇴화 삼각형, 입력/UUID/hash 불일치를 거부한다. 좌표의 1e6 mm 기하 상한 주변 수치 여유 1 mm는 표시 검사에만 적용하며 기하 입력 범위를 늘리지 않는다. 현재 제한 profile에서 mesh 생성 또는 검사 실패는 전체 패키지를 게시하지 않는 명시적 실패다. 실패해도 이전 정상 결과를 유지한다.

GUI는 게시된 ArtifactRef만 받아 파일 읽기, 같은 byte 집합의 SHA256과 JSON 검사를 background에서 수행한다. B-rep와 Python CAD runtime을 GUI에 적재하지 않는다. `ModelView`는 필요한 때 wxGLCanvas context를 만들고 OpenGL 1.1 호환 API로 장면 중심을 뺀 제한 CPU float 배열을 표시한다. 실제 context 버전은 드라이버에 따라 다르다. float 변환 뒤 퇴화/방향 뒤집힘과 변 길이 오차가 max(1e-9 mm, 원래 길이의 10%)를 넘는 경우 표시를 거부하며, 이는 STEP 기하 허용오차가 아닌 표시 정밀도 방어다. 드래그 회전, Shift 또는 가운데 버튼 이동, 휠 확대, 전체 맞춤과 body 선택을 제공한다. 실제 층 두께를 확대하지 않으며, 선택은 안정 UUID 대응을 통해 속성과 연결한다. OpenGL 실패는 표시 오류로 다루며 프로젝트 저장과 이미 생성한 STEP 상태를 유지한다.

병합된 body를 클릭하면 현재 첫 번째 source_entity_ids를 대표 객체로 선택하고 여러 패턴의 대표 속성이라는 안내를 표시한다. body의 전체 원본 대응은 파일에 보존하지만 여러 원본 중 클릭한 세부 형상을 구분하는 picking은 후속이다. 개별 패턴은 왼쪽 목록에서 선택한다. 현재 개정과 다른 3D 결과의 선택은 현재 설계 속성에 적용하지 않는다.

이 단계는 고정된 100000 triangle 이하 표시 profile이다. 대형 1000000 triangle, LOD, GPU 전용 cache와 전체 성능/DPI 수용은 후속이다. OpenGL 사용이나 frame 렌더링 성공만으로 60/30 fps와 메모리 예산의 합격을 주장하지 않는다.

## 서비스 API와 실행

다음 세 메서드는 작은 결과나 미리보기여도 항상 request_key/request_key_epoch를 가진 비동기 TaskRef를 반환한다. 완료 결과는 job.status의 completed event에 있다. 작업 완료와 기하 교환/제조/물리 검증 상태는 별개다.

| 메서드 | input | 처리 |
| --- | --- | --- |
| export.preview (API-023) | snapshot, profile, format="step" | 고정 snapshot의 포함 수/생략과 profile 범위를 preview_only로 반환 |
| geometry.build (API-008) | snapshot, profile, projection_kind="brep" | 고체 B-rep와 STEP 교환 근거를 같은 고정 입력에서 생성 |
| export.build (API-024) | snapshot, profile, format="step" | AP242 STEP, B-rep, sidecar 및 재입력 근거 생성 |

context는 project_id, snapshot은 `{ "snapshot_id": "...", "content_hash": "..." }`, profile은 `rfad.step.mechanical/0.1`이다. 서비스에 등록된 SnapshotRef와 바이트를 검증한다. 다른 프로젝트/내용 hash를 섞거나 draft expected_revision을 snapshot 대신 전달할 수 없다. export.verify (API-025), 다른 schema fallback, 공개 resume/reconcile API는 아직 지원하지 않는다.

`cad.latest`는 `rfad.cad-view/0.1` 개발용 확장 조회다. 표준 query envelope의 context에는 project_id, input에는 빈 객체를 사용한다. 해당 프로젝트의 마지막 게시 완료 CAD 작업을 profile/result/job_id로 반환하며 없으면 result와 job_id는 null이다. 새 작업, receipt나 snapshot을 만들지 않고 큰 artifact를 읽지 않는다. 진행/실패/취소된 출력은 반환하지 않는다. GUI는 재열기 때 이 작은 참조를 사용하며 파일 무결성은 실제 3D 로딩 때 확인한다. mesh가 없던 과거 출력은 STEP 파일을 보존하고 새로운 3D 갱신으로 표시 자료를 생성한다.

CAD 실행 환경은 프로젝트가 아니라 호스트 설정으로 지정한다. API에서 Python 경로, native 코드나 임의 worker 인수를 선택할 수 없다. 서비스 Python에는 CAD 패키지를 설치하지 않는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m rfad serve --workspace .local/gui-workspace --cad-python .venv-cad/Scripts/python.exe
```

`tools/export_step.py`는 같은 서비스 계약을 사용하는 개발 실행 도구다. 등록된 프로젝트의 현재 영속 개정에서 새 불변 snapshot을 만들거나, `--snapshot-file`로 기존 SnapshotRef를 지정한다. 원본 개정이나 저장 기준점은 변경하지 않는다. 같은 workspace의 GUI/서비스가 실행 중이면 단일 writer 잠금으로 거절하므로 해당 서비스 종료 후 사용한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/export_step.py --workspace .local/gui-workspace --project "projects/내 설계" --cad-python .venv-cad/Scripts/python.exe --report .local/step-result.json
```

기존 report는 덮어쓰지 않는다. GUI의 미정 도체층만으로는 출력할 수 없으며 실제 입력으로 유전체 층, z 위치, 두께와 기판 안의 패턴을 먼저 구성해야 한다. `유전체 층` 생성도 위치/두께/재료를 미정으로 두며 사용자가 속성에서 입력한다. 실제 재료 수치를 시연용 값으로 자동 채우지 않는다.

GUI의 `STEP 출력`은 미적용 입력을 기존 편집 명령으로 적용한 뒤 snapshot.create와 export.build를 연결한다. 잘못된 입력은 적용 또는 출력 단계에서 중단한다. `3D 갱신`은 같은 snapshot 흐름으로 geometry.build를 실행하며 현재 제한 profile에서는 STEP/B-rep/mesh를 함께 생성한다. native 작업 접수 후에는 편집/저장을 계속할 수 있고 CAD 작업 취소를 별도로 요청한다. 완료 패키지 경로와 제조/RF 검증 전 상태를 CAD 출력 패널에 표시하며 `출력 폴더`에서 실제 파일에 접근한다. 외부 파일 선택창으로 STEP 하나만 복사하는 기능은 아니다.

표시 중인 형상의 snapshot revision과 현재 개정이 다르면 이전 설계의 형상과 갱신 필요 상태를 명시한다. 미적용 입력도 아직 포함되지 않았음을 따로 표시한다. 취소/실패 결과로 기존 정상 3D와 출력 패키지를 대체하지 않는다. 최종 GUI 연결 시험의 범위와 결과는 [개발 상태](development_status.md)를 따른다.

## 프로세스, 복구와 게시

접수 transaction은 입력 JSON, snapshot, run UUID/nonce, runtime manifest, 실행 진입점과 제품 Python 소스 묶음을 불변 artifact로 봉인한다. Python 실행 파일, manifest, 진입점 및 소스의 SHA256을 기록한다. 실행할 때 새 staging의 src에 .py만 복사하여 기존 __pycache__를 사용하지 않는다. worker도 실제 소비한 staged source/input/runtime hash 및 Python 구현/minor/OS/CPU와 설치 패키지 버전을 대조한다.

자료 처리 worker와 CAD 조정 스레드를 분리한다. native 실행, 큰 파일 스트리밍과 해시는 journal transaction 밖에서 수행한다. Windows에서는 KILL_ON_JOB_CLOSE Job Object를 할당한 뒤에만 stdin 시작 메시지를 보내며, 시작 전 부모 종료 시 worker는 EOF로 끝난다. POSIX 감독기는 소유 process group을 회수한다. WSL guest solver supervisor와 재접속을 구현한 것은 아니다.

queued 취소는 큐에서 제거한 뒤 cancelled가 된다. 실행 중 취소는 cancel_requested를 기록하고 실제 프로세스 트리와 pipe 회수를 확인한 뒤 cancelled가 된다. 최초 terminal commit을 유지하며 nonce가 달라지거나 취소된 작업의 늦은 성공은 게시하지 않는다. 닫기 시 소유 프로세스를 회수하고 interrupted로 기록한다.

비정상 종료 후 running/cancel_requested였던 CAD 작업은 interrupted/outcome_unknown과 슬롯 예약을 유지한다. PID만으로 살아 있는 다른 프로세스를 종료하거나 성공/취소로 추정하지 않는다. 종료 상태의 수동 조정 API는 후속이며 해당 workspace에서 새로운 CAD 작업은 보수적으로 차단한다. 기존 프로젝트 편집/저장/조회는 가능하고 자동 재실행이나 미게시 산출물 삭제는 하지 않는다.

정상 worker가 종료한 뒤 host는 wrapper schema/run/nonce/input hash, 실제 STEP FILE_SCHEMA, sidecar의 snapshot/원본 의미/hash와 필수 파일 목록을 다시 확인한다. 닫힌 파일은 일정 크기 버퍼로 hash/복사/fsync/재읽기를 수행하며 기존 산출물을 덮어쓰지 않는다. 작은 manifest를 마지막에 봉인하고 artifact 참조와 completed event를 하나의 짧은 transaction으로 게시한다. 완료 전 staging/미게시 파일은 정상 결과가 아니다. 디스크 부족, hash 불일치, native 실패, 취소나 게시 오류 시 과거 정상 결과는 유지한다.

출력 경로는 `projects/<이름>/artifacts/<run_id>/`이며 model.step, model.brep, mesh.json, sidecar.json, validation.json, manifest.json의 총 6개 파일이 있다. 파일 URI는 workspace 기준 상대 경로다. 큰 B-rep/STEP/mesh 바이트는 NDJSON에 넣지 않는다. 실패 staging과 제한된 프로세스 로그는 `cad-staging/<run_id>/`에 보존하며 자동 GC는 후속이다.

## 검증 재현

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_CAD_PYTHON = (Resolve-Path '.venv-cad/Scripts/python.exe').Path
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_cad_worker_process.py -v
.\.venv-cad\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_cad_native.py -v
```

native 시험은 독립 산술 기대 체적과 정확 원호, 부호/완전 원, 얇은 동박, Boolean, 실제 AP242/단위/UUID 이름 및 STEP 재입력의 bbox/중심/체적/두께/단면 면적/경계/구멍과 body 중첩을 확인한다. 서비스 환경에서는 native 시험을 제외하고 별도 CAD 환경에서 실행한다. `RFAD_CAD_PYTHON`을 지정한 실제 프로세스 시험은 서비스-CAD 분리, snapshot 고정, 실패 미게시, 결과 재열기와 서비스 재시작을 확인한다.

표시 mesh 추가 후 native 9개 시험에서 삼각형의 외향 winding에 따른 양수 체적, 정확한 얇은 두께, body 경계와 UUID 대응을 확인했다. 순수 mesh 검사 7개는 입력 결합/유한 좌표/잘못된 색인/퇴화 면/상한을 다루며 coordinator 시험에는 mesh snapshot/run/mapping/hash 변조의 미게시를 추가했다. 이 시험과 GUI 표시/조작, 성능 측정은 서로 구분한다.

공식 API 근거는 [OCCT 7.9.3 STEP translator](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/dox/user_guides/step/step.md), [CadQuery 입출력](https://cadquery.readthedocs.io/en/latest/importexport.html), [CadQuery Shape 구현](https://cadquery.readthedocs.io/en/latest/_modules/cadquery/occ_impl/shapes.html)이다. CadQuery 기본 mesh helper의 상대 deflection과 구분하여 표시 adapter는 OCCT 절대 deflection 설정을 직접 사용한다. 지원 판정은 고정 설치본의 실제 파일/시험을 함께 기준으로 한다.
