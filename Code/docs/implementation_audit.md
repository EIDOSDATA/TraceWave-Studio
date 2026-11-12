# 승인 요구와 실제 구현의 대조

검토일: 2026-11-12 KST. 기준선 RFAD-D0-3.4. 최초 감사 시작 코드는 47c96c70f7d07cd71a4cacffd3a977ec8c5485fd이며, 최신 후속 검토 기준은 1ed9686b8eea5cec3b17931d8655565fbafc72e2와 현재 작업 트리다. [개발 완료 계획](completion_plan.md) 2번의 산출물이다.

## 1. 검토 범위와 읽는 방법

승인 03/06/11/14/17의 실제 요구/기능/API/시험 전문과 Code의 domain/application/adapter/GUI 및 시험 본문을 대조했다. 현재 기능과 구체적인 누락을 [기능별 구현 대조](audit/function_matrix.md)에 기록했다. 각 FN 아래에는 코드, 시험 메서드, 기존 실행 근거와 담당 단계가 있다.

[기계 판독 대조표](audit/implementation_matrix.json)는 141개 요구, 404개 AC, 407개 검수 subcase, 46개 FN, 30개 VT와 30개 승인 API를 연결한다. DES-URS 5개, PERF 10개와 GUI-SPIKE 7개도 별도 보충 조건으로 보존한다. R1/R2/R3가 나뉜 subcase를 합쳐서 R1 완료로 바꾸지 않는다.

기능 상태는 partial(부분 구현), not_implemented(제품 기능 미구현), deferred(승인된 후속 범위)로 구분했다. 최초 대조는 부분 구현 23개, 미구현 13개, 후속 10개였다. 이 수치는 출시 완료율이 아니다. 이후 구현은 해당 FN과 근거를 갱신하고 기존 감사 기준 commit을 함께 남긴다.

목표 저장/명령/호환성 추가 때 부분 구현 24개, 미구현 12개, 후속 10개였다. 이후 목표 편집 GUI와 명시 치수 템플릿을 FN-004/006/007/008에 반영하여 현재 부분 구현 26개, 미구현 10개, 후속 10개다. [목표 편집](target_editor_contract.md)과 [템플릿](template_contract.md)의 실제 범위만 반영했으며 전체 기능 수용이나 목표 성능 합격이 아니다.

기존 단위/계약/native 시험의 통과는 연결한 범위의 증거다. 각 AC의 전체 조건과 필요한 실측/교환/성능 근거가 갖춰졌다는 정식 수용 판정을 이번에 새로 하지 않았으므로 acceptance_status=open으로 유지한다. 이는 이미 통과한 단위시험을 실패로 바꾼다는 뜻이 아니다. AC별 연결은 검수 대상을 찾는 색인이며 연결 FN의 시험을 모든 AC의 직접 검증으로 주장하지 않는다.

## 2. 확정한 주요 간극과 처리

| ID | 현재 확인한 간극 | 처리 계약/단계 |
| --- | --- | --- |
| IG-001 | 최초 감사의 예약 컬렉션 중 targets 입력은 0.3으로 추가했으며 networks/environment/connections 등은 아직 빈 배열만 허용 | CC-003. collection별 validator/명령/이력/schema를 함께 구현. 목표 GUI는 연결했으며 평가/프리셋은 후속 |
| IG-002 | 내장 원호/IFA와 G031 원문 원호/stub 부분 기하를 연결했으며 추가 문헌 카드와 초기 RF 합성은 미구현 | 3/4번. 기하 생성/초기 RF 추천/실측의 출처와 지원 상태를 분리 |
| IG-003 | 현재 접촉 검사는 제한 polygon/port 검사이며 범용 연결/제조 DRC가 아님 | 3/8/10번. 기본 연결/치수/간극과 의도한 short/open부터 확장 |
| IG-004 | 연구 GUI는 격자축 1~6수준이며 일반 설계변수 스윕이나 전체 수치 행렬이 아님 | 6번. 기존 study.*와 API-020/021 지원을 명시적으로 연결 |
| IG-005 | 결과 차트 DTO는 제한 201점 표시용이며 공통 복소 dataset/network 변환/목표 평가가 없음 | 5/7번. 원시 복소수/정규화/기준면/유효 mask를 갖춘 공통 조회/평가 |
| IG-006 | 기본 외부 RLC, Touchstone/측정 CSV 및 기준면/교정 정렬이 없음 | 5/11번. 기본 파일 비교를 고급 R2 보정이나 직접 VNA 연결 뒤로 미루지 않음 |
| IG-007 | 외부 STEP 환경/배치, 도면 PDF/SVG/DXF와 KiCad/Gerber/드릴 입출력이 없음 | 3/10번. geometry와 제조 profile을 따로 검수 |
| IG-008 | STEP은 같은 kernel 검사이며 API-025 독립 수신 검수와 verified_profile이 없음 | 10번. 수신 도구/version별 검수와 누락 범위를 기록 |
| IG-009 | project.open copy/이동 가능한 archive/일반 migration/복구 후보 선택이 없음 | 3/12번. 기존 정상본/영수증/봉인과 호환되는 단계적 확장 |
| IG-010 | capabilities implemented, runtime_configured와 물리 검증은 서로 다르며 tested_envelopes는 비어 있음 | 8/13번. 실제 profile별 근거를 공개 지원표에 연결 |
| IG-011 | 연구 재개는 완료 단계 재사용이며 solver checkpoint 재개는 없음 | 6/12번. study.resume과 API-029 job.resume을 구분 |
| IG-012 | 기존 converged=true는 시간영역 종료, W*s^2는 pulse Fourier 전력 | CC-007/공통 결과 DTO. 전체 수렴 또는 절대 W로 표시하지 않음 |
| IG-013 | RO4350B 국부 방사 도체 2.788446%로 2% 미확립, GHz PTH 독립 물리 정확도도 미확립 | 8번. 고정한 오차 기준과 원시 근거를 유지하여 후속 모델/참조 검증 |
| IG-014 | 기존 프로젝트 128 parameter/전체 설계 entity 256, 표시 mesh 100000 triangle와 60 KiB DTO 한도는 승인 F1/F2 크기를 수용하지 못함 | 3/4/7/12번. 페이지/분할/LOD/원본 저장 구조 계측과 유한 예산을 먼저 설계. 상한 숫자만 무조건 확대하지 않음 |
| IG-015 | 실제 전체 프레임/메모리/IME/접근성/DPI/도킹/GPU/WSL cold boot 수용이 남음 | 4/12번. synthetic renderer 통과를 전체 UX 합격으로 사용하지 않음 |
| IG-016 | 내부 개발 파일 ZIP과 사용자 프로젝트 인계 archive는 다른 산출물 | 12/13번. 참조 closure/실제 재열기/권리/파일 누락 검사 |

제작/측정 미정값은 기능 미구현과 다른 열린 조건이다. 납품 물성/마스크/동박/표면처리, SMA/케이블/지그, 시료/교정/불확도는 자료 확보 후 해당 검수 전에 고정한다. 이 조건은 가능한 편집/저장/GUI 개발을 막지 않지만 실물 정확도 합격을 허용하지 않는다.

## 3. 공통 계약과 GUI 결정

[R1 공통 구현 계약](shared_contracts.md)에 원본 소유권, 버전/호환, 요청 멱등성, 작업/판정 상태, 결과/연구 DTO, cache/무효화와 출력 계약을 확정했다. 구현에서 필요한 최소 확장만 하며 승인 요구를 현재 코드의 제한에 맞춰 축소하지 않는다.

[Studio GUI 설계](studio_gui_design.md)는 가독성/편의성, native 입력과 Studio 작업 공간, 테마/아이콘/DPI/키보드/오류 안내를 정한다. 기존 조사 도구와 개발 환경의 적용 요소를 비교하고 실제 기능/성능 검수와 구분한다. 기능을 구현할 때 화면을 함께 연결하고 12번에서 전체 사용 흐름을 다시 검수한다.

## 4. 검증과 재현

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/build_implementation_audit.py --check
```

도구는 요구/AC/subcase 수와 고유성, 정확한 VT/API/보충 조건 ID 집합, 요구-AC-VT 연결, subcase의 AC/단계 귀속과 API capability ID를 검사한다. FN별 코드/시험/근거 파일, 지정한 Python 시험 심볼, 생성기/검토 입력 및 UTF-8 본문 hash도 기록한다. 임시 workspace에서 worker를 시작하지 않고 실제 capabilities를 읽어 승인 API 30개의 등록 상태를 비교한다. 원문 문서나 사용자 프로젝트를 변경하지 않는다.

검토된 JSON 입력을 변경한 뒤 산출물 갱신은 --check 없이 실행한다. 생성/검사 성공은 문서 추적의 무결성이고 물리/성능 수용시험 통과가 아니다. 기존 runtime_profiles는 당시 실행의 증거로 보존하며 문서 변경으로 다시 작성하지 않는다.

생성/재현 검사는 통과했다. `tests/test_implementation_audit.py`의 12개 시험은 잘못 연결된 동일 개수 자료, 누락 심볼, 본문/산출물 변조를 차단하는지 확인했다. 이번 제품/GUI 검증 범위와 별도 실행 시점은 [개발 상태](development_status.md)의 최신 기록을 따른다.

3번 설계 모델 보강의 첫 구현으로 여러 목표 대역과 명시한 성능 한계를 기존 명령/undo/영수증/저장/재열기에 연결했다. 목표 입력은 미평가 상태이며 자동 solver 설정이나 물리 성능 판정과 혼동하지 않는다. 후속 구현한 [원호/IFA 템플릿 계약](template_contract.md)과 [목표/템플릿 화면](target_template_gui.md)도 같은 명령/원본 위에 연결했다. 문헌 원본 카드/초기 합성, 연결/검사와 정밀 편집은 남은 범위다. 최초 [제안 문서](template_design.md)는 이력으로 보존한다.

G031 문헌 카드의 원문 archive/member/좌표 및 가정, 수정값/배치/부분 기하와 검증 축을 기존 후보/원자 적용/GUI에 연결했다. [문헌 카드 계약](literature_templates.md)의 실제 지원만 FN-006/007에 반영한다. 전체 보드 재현, 초기 RF 합성, 해석/실측 합격이나 3/4번 전체 완료로 확대하지 않는다.
