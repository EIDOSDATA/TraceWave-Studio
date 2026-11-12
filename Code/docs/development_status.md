# 개발 착수와 현재 상태

최초 기록일: 2026-11-07 KST

상태 갱신일: 2026-11-12 KST

전체 제품을 완성하기 위한 현재 작업 순서는 [개발 완료 계획](completion_plan.md)의 1~13단계를 따른다. 과거 7/8단계 권장 목록을 대체하며, 이 문서의 날짜별 기록은 당시 구현/검증의 근거다. 승인 범위와 실제 구현을 대조하여 빠진 기본 회로/측정/도면/CAM도 포함했다.

[개별 손실 정밀도와 PTH 분할](pcb_loss_precision.md)을 추가했다. native QuarterCell 전도도 기여율과 sheet의 재료 계수 대체를 반영하여 유전체/평면 도체/비아를 독립 계산한다. 일반 연구는 개별 손실 기준과 임계 구간 최소 분할을 고정하고 비아 전력을 구분한다. WSL 제어 파일의 원자적 교체 읽기 경합과 8 MiB 초과 원시 필드의 스트리밍 검증/재후처리 전달도 보완했다. 코드 기능, 검사한 설정의 안정성과 실제 skin depth/제조/측정 정확도는 별개로 유지한다.

제품 개발 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`다. 승인 기준선은 RFAD-D0-3.4, 커밋 `6ebeda156e9d31b893bf69046550f5df9b16dc64`다. 01_Docs와 승인 records는 변경하지 않았다. 기준선의 착수 전 표기는 당시 승인 기록이며 현재는 R1 내부 검증 제품을 향한 부분 구현 단계다. 전체 R1 수용은 완료하지 않았다.

## G031 문헌 부분 기하 카드 (2026-11-12)

시작 시 `main`, `dbc2982c5fc8f7bf957e2d4a74fafea39a938b00`과 깨끗한 작업 트리를 확인했다. [문헌 카드 계약](literature_templates.md)에 따라 G031 PCA20006 / PCB400059 hardware 1.0.0의 실제 중첩 ZIP, GTL/GM1 및 embedded PDF 해시를 확인했다. PDF 물리 p.1-3을 렌더해 회로/앞뒷면을 대조했다. 원문 좌표의 CCW 원호와 D10 stub만 생성하며, stub을 기존 내장 원호의 시작점에 붙이지 않는다. 약 0.001041 mm의 끝점 반지름 차이를 명시하고 탭을 포함한 전체 보드를 원으로 바꾸지 않는다.

`literature.g031_pca20006_arc/0.1`은 기존 후보/2D 미리보기/검토 hash/원자 적용/undo/redo/저장/재열기 및 wxWidgets 카드 화면을 사용한다. 카드 0.2에 원문 치수/해시/locator/줄 사본, 생략/미정 및 가정을 보존한다. 사용자 배치와 수정 입력은 원문과 별도로 유지한다. 생성 사본도 원문/입력과 대조하며 과거 직접 편집을 막지 않는다. 기존 내장 카드 두 종의 전체 사본과 content hash가 이전 커밋과 동일함을 별도로 확인했다.

기하 생성, 초기 추정, 해석, 수렴, 실측/제조 상태를 각각 표시한다. 전체 보드/ground/netlist, 물성/포트/정합 회로나 실제 제작/측정 조건을 완성하지 않는다. TI G003 원문도 확인했지만 현재 단순 IFA로 치환한 재현 카드를 등록하지 않았다. 초기 합성식/주파수 기반 추천 치수는 이번에 추가하지 않았다. 개발 순서 3/4번의 일부이며 전체 단계나 R1 수용 완료가 아니다.

| 이번 검증 | 실제 결과와 시점 |
| --- | --- |
| 전체 서비스 회귀 | 870개 수집, 779개 통과/91개 환경 제외, 실패/오류 0, 386.490초. 최종 표시 문자열 호환 시험 1개 추가 전 수집이며 아래 후속 검증과 구분 |
| 관련 서비스 회귀 | template/target/domain/service/source capture/solver plan 106개 통과, 43.399초. 표시 보완 전이며 이후 문헌 시험으로 추가 확인 |
| 최종 문헌 집중 시험 | 10개 통과, 13.714초. 실제 원문 archive/member/줄, 치수/정밀도/연결, 오류 차단, 수정 출처/이력/원자 게시 및 이전 표시 문자열 호환 포함 |
| Release/CTest | Release 빌드 성공, CTest 9개 통과, 1.46초 |
| 전체 GUI 회귀 | 20개 중 18개 통과/실제 WSL 계산 2개 조건부 제외, 292.328초. 실제 CAD GUI 2개 포함. 표시 보완 전 실행 |
| 최종 표시 보완 후 GUI | 실제 목표/내장/문헌 카드의 미리보기/수정/적용/undo/redo/저장/재열기 시나리오 1개 통과, 135.520초 |
| 최종 실제 G031 CAD | 공개 preview/apply/snapshot/STEP와 CAD 환경 없는 재열기 1개 통과, 17.056초. 미정 물성/포트와 원래 봉인 snapshot 보존 |
| Windows -> WSL | Windows에서 만든 G031 문서의 WSL Python validator와 canonical bytes 불변 확인. FDTD 실행이 아님 |
| 요구 추적 | 별도 감사 도구와 손상 검출 시험 12개 통과. 요구/AC의 전체 수용 합격은 선언하지 않음 |

전체 서비스/GUI 수집 중 지원 상태의 표현과 사본 검사를 보강했고, 최종 창 검수에서 발견한 직접 좌표의 float 잔여 자리도 서비스 표시 문자열에서 정리했다. SI Quantity는 유지하며 이전 표시 문자열 사본도 읽는다. 각각의 전체 회귀와 최종 집중/GUI/native 실행 시점 및 소스/로그 해시는 [별도 검증 기록](../runtime_profiles/literature-templates.json)에 보존한다. 기존 runtime profile과 승인 문서/참고 자료는 수정하지 않는다.

실제 Windows 창에서 G031 목록 진입, 빈 배치 좌표와 원문 치수, 부분 재현/출처/가정 안내, 긴 치수의 가독성과 Esc 복귀를 확인했다. 최종 표시 보완본에서 잘림/버튼 겹침을 관찰하지 않았고 검수용 창은 종료했다. 후보의 2D 표시/적용/이력은 실제 GUI 프로세스 시험으로 검증했다. 현재 디스플레이의 부분 검수이며 전체 DPI/IME/접근성, 60/30 fps와 메모리 수용은 후속이다.

새 FDTD나 실물 측정을 수행하지 않았다. RO4350B 국부 방사 도체 2.788446%의 초기 2% 기준 미확립, GHz PTH 독립 정확도 미확립과 제작/납품/측정 미정 상태를 유지한다. 다음 범위는 기존 3번 안의 추가 문헌 카드/적용 범위가 있는 초기 후보, 목표 제약/연결/DRC/적층/환경이며 정밀 편집은 4번에서 이어간다. 번호를 바꾸지 않는다.

## 원호/IFA 템플릿과 목표 편집 (2026-11-12)

요구 대조/목표 원본/Studio 기반까지의 변경은 `1ed9686b8eea5cec3b17931d8655565fbafc72e2`로 커밋하여 origin/main에 푸시했다. 이어 아래 구현을 추가했다. 이번 추가 변경과 앞서 푸시한 커밋을 구분한다.

- [목표 편집 서비스](target_editor_contract.md)와 [wxWidgets 화면](target_template_gui.md): 다중 목표의 추가/수정/삭제, 단위와 미정 선택, 4개 지표 한계와 최대 1001개 명시 주파수 표본. 변경값만 적용하며 단위만 바꾼 입력과 기존 출처/근사를 보존한다. solver 설정과 목표 성능 판정은 생성하지 않는다.
- [명시 기하 템플릿](template_contract.md): 원형/사각 보드의 원호와 사각 보드의 평면 IFA, 현재 도체층과 선택 목표 개정, 한국어 이름의 실제 매개변수/표현식/도형, 읽기 전용 2D 후보와 검토 hash, 한 명령의 적용/undo/redo. GUI의 첫 범위는 포트 미정인 형상 생성이며 기존 급전 편집으로 이어간다.
- 최초 카드/입력/기준 core 원본/생성 사본을 프로젝트 소유 출처로 보존한다. 현재 도형을 직접 수정해도 과거 출처를 덮지 않고 변경 여부를 조회한다. 출처 256 KiB/프로젝트 512 KiB와 기존 객체 예산은 유한하게 유지한다.
- 새 기능을 카드/입력/기하/포트/출처/명령/서비스와 화면/공통 비동기 수명으로 나눴다. worker 소스 파일 수는 공통 192개로 정리하고 CAD 2 MiB/solver 4 MiB 바이트 예산은 유지했다.

실제 OCCT 시험은 원형 원호와 사각 IFA 각각의 공개 preview/apply/snapshot/STEP, 원본/미정 물성 보존, 과거 snapshot 봉인, CAD runtime 없는 재열기를 확인했다. 1001개 목표 표본의 출처 호환 보완 후 최종 소스에서 1개 시험의 두 사례가 24.986초에 통과했다. 같은 최종 소스의 목표/템플릿/저장/미지 확장/worker 예산 관련 97개 시험도 45.320초에 통과했다. 이는 기하/파일/재열기 통합 검사이며 이번 변경으로 FDTD나 제조/실측 검증을 새로 수행한 것은 아니다. 지원하지 않는 물성과 급전은 계속 차단하며 RO4350B 개별 손실과 GHz PTH 정확도의 미확립 상태를 유지한다.

Windows 전체 서비스 회귀는 858개 중 768개 통과, 90개 환경 조건 스킵, 실패/오류 0으로 491.263초에 끝났다. 이 전체 수집은 마지막 1001개 출처 목록 호환 보완 전에 시작했으며, 보완 후 추가한 2개 사례를 포함한 최종 관련 97개 및 실제 CAD 검증을 별도로 수행했다. 스킵한 GUI/native/WSL 조건을 실행 성공에 합산하지 않는다. 새 템플릿 집중 시험은 최종 15개다. unknown 확장의 256개 목록 제한, 1002개 표본 거부와 실제 출처 256 KiB 초과의 원자 차단을 함께 확인했다.

새 GUI는 조회 실패 후 목록/폼의 목표 ID를 다시 맞추고, 생성 성공 후 재조회가 실패하면 추가 적용을 잠근다. 다른 카드에 남긴 초안도 보존하며 닫을 때 미적용 입력의 폐기를 확인한다. 실제 목표/템플릿 프로세스 2개 시나리오는 182.702초에 통과했다. 긴 시나리오의 시험 전용 180초/외부 210초 한도는 제품 요청 timeout이나 성능 예산의 변경이 아니다. 상세 계약은 [화면 문서](target_template_gui.md), 로그/최종 소스와 실행 파일 해시는 [이번 검증 기록](../runtime_profiles/templates-target-editor.json)을 따른다. 이전 runtime profile은 당시 실행 기록으로 그대로 보존한다.

최종 Release 빌드와 CTest 9개(0.38초)를 통과했다. 전체 실제 GUI 회귀는 20개 중 18개 통과/실제 WSL 계산 2개 조건부 제외로 344.431초에 끝났으며 실제 CAD GUI 2개를 포함한다. 현재 디스플레이에서 목표의 기본/출처 상세, 원호/IFA 입력 폼, 도체층 미선택 안내와 Esc 복귀를 시각/키보드로 확인했다. 2D 후보/적용/이력은 실제 GUI smoke로 확인했으며 수동 시각 검수와 구분한다. 모든 시험 창과 프로세스는 종료했다. 전체 DPI/IME/접근성, 실제 60/30 fps와 메모리 예산 수용은 후속이다.

## 요구 대조, 목표 입력과 Studio 기반 (2026-11-12)

직전 RO4350B 후속 연구와 완료 계획은 `47c96c70f7d07cd71a4cacffd3a977ec8c5485fd`로 커밋하여 origin/main에 푸시했다. 이후 완료 계획 2번의 [구현 대조](implementation_audit.md)를 작성했다. 승인 요구 141개, AC 404개, 검수 subcase 407개, FN 46개, VT/API 각 30개 및 추가 설계/성능/GUI 조건 22개를 실제 코드/시험/남은 범위와 연결했다. 기존 단위시험의 성공을 전체 수용 합격으로 확대하지 않으며 승인 원문은 보존한다.

[공통 계약](shared_contracts.md)은 원본/버전/명령/작업/결과/연구/출처/출력의 소유권과 미정 상태를 구분한다. 감사 도구는 파일/시험 심볼/본문 hash 외에도 중복/누락 ID, 요구-AC-VT와 subcase 단계, API capability 연결의 오류를 차단한다. 최초 감사 23개 부분 구현/13개 미구현/10개 후속에서 목표 입력 추가 후 24/12/10으로 갱신했으며 이 숫자는 완료율이 아니다.

3번의 첫 범위인 [목표 입력](target_contract.md)은 여러 대역, 명시 주파수 표본, port/Z0, S11/방사효율/전체효율/비율대역폭 한계를 저장한다. 목표별 UUID/개정/출처와 미정 상태를 보존하며 기존 원자 명령, 영속 undo/redo, 저장/재시작/재열기/snapshot을 재사용한다. 프로젝트 쓰기는 0.3, 읽기는 0.1/0.2/0.3이다. 기존 원본/봉인 hash는 유지하고 첫 편집의 새 개정에만 변환 기록을 남긴다. 목표 입력은 항상 미평가이며 solver 주파수/물성/포트 저항을 자동 변경하지 않는다. 목표 GUI/프리셋/편파/제약/평가와 자동 raw 재사용은 후속이다.

4번의 일부로 [Studio GUI 디자인](studio_gui_design.md)의 라이트 표면/글자/도킹/간격을 `studio_theme.*`로 분리하여 실제 화면에 적용했다. native 입력과 기존 물리 색상을 유지하며 편집/3D/해석 도구는 좁은 영역에서 줄바꿈한다. 활성 층과 선폭/단위는 각각 한 묶음으로 표시한다. 완성 목표 [v2 시안](ui_concept.md)을 별도로 보존하며 시안의 형상/치수/상태를 실제 검증값으로 사용하지 않는다. 전체 작업 탭/아이콘/다크/정밀 편집과 전체 DPI/IME/성능 수용은 아직 남아 있다.

| 이번 확인 | 결과 | 시간 |
| --- | --- | --- |
| Windows 서비스 전체 회귀 | 818개 수집, 731개 통과, 87개 환경 스킵, 실패/오류 0. 새 목표 시험 13개 포함 | 447.493초 |
| 요구 추적 감사 도구 | 위 전체 수집 이후 추가한 별도 12개 시험, 모두 통과. 중복/누락/잘못된 참조와 산출물 변조 차단 | 시험 본문 0.722초, 실행기 포함 1.125초 |
| 현재 공통 계약 집중 확인 | 앞서 수행한 19개 통과. 명령/원자성/작업 상태/연구 복구/실행 중단 계약 | 26.781초 |
| wxWidgets Release/CTest | Release 빌드 성공, CTest 9개 통과 | CTest 1.04초 |
| 실제 GUI 프로세스 | 18개 수집, 14개 통과, CAD/WSL 환경 4개 스킵, 실패/오류 0 | 117.284초 |
| 실제 화면 확인 | 독립 작업 공간 신규 프로젝트, 약 1346 x 853 및 987 x 723 창의 도구 줄바꿈/단위 묶음/해석 탭 확인 후 종료 | 현재 디스플레이 조건의 부분 검수 |

검증 로그/소스/빌드/문서 hash와 범위는 [이번 검증 기록](../runtime_profiles/development-contracts.json)에 남긴다. 전체 회귀와 별도 감사 시험은 수집 시점이 달라 합격 수를 소급 수정하지 않는다. 기존 실제 0.2 계획 9개/준비 3개/정규 결과 3개의 독립 읽기 검토에서도 오류 없이 원본 19개 파일의 hash가 유지됐다. 해당 검토는 새 FDTD/실물 시험이 아니다.

다음 템플릿 구현의 [설계](template_design.md)도 정리했다. 기존 IFA/원형 smoke의 합성 물성을 제품 기본값으로 사용하지 않고, 선택한 보드/적층과 명시 치수를 원본으로 하여 출처가 있는 기하 후보를 한 번의 명령으로 적용하는 방향이다. 이 문서는 후속 설계이며 해당 서비스가 구현됐다는 뜻은 아니다.

RO4350B 방사 도체 2.788446%의 2% 미확립, GHz PTH 물리 정확도 미확립과 실제 제작/측정 미정값은 유지한다. 이번 명령/표시 변경을 위해 새 native FDTD를 실행하거나 기준을 완화하지 않았다.

## RO4350B 도체 손실의 후속 정밀 연구 (2026-11-12)

[후속 연구 계약](ro4350b_loss_refinement.md)에 명시적 확장 예산, 재료 분할 가속과 초기 2% 재검증을 추가했다. 기본 PCB의 1500000 격자점/300초/2스레드는 보존하고, 독립 손실을 기록하는 명시적 profile만 표준 2400000 격자점/900초 또는 심화 3000000/1800초와 지정 스레드를 사용한다. 손실 필드는 기본/표준 48 MiB, 심화 96 MiB이며 단일 파일 64 MiB/패키지 128 MiB는 유지한다. 상위 CLI의 420초 고정 대기도 max(420, 요청 예산+120)으로 보완했다. 기본 계획의 301초 요청 거절, 900초 요청의 접수/취소와 500초 완료 판독을 검증했다.

완료한 0.36/0.32/0.30/0.28 mm 격자 축에서 마지막 유전체 합계 최대 변화는 0.060111%, 도체 합계는 0.262782%이고 모든 성분의 초기 기준을 충족했다. 이전 두 인접 비교의 미충족 상태는 보존했다. 격자 raw 생산자와 XML 가드 보완 뒤의 배열 계산기는 별도 출처로 기록하고, 같은 raw의 손실 행이 동일함을 확인했다. 조정기 중단은 동일 run_id/nonce의 guest 확정 종료와 슬롯 반환을 확인했다.

국부 4/5/6분할은 실행을 모두 완료했고 5/6분할에서 합계 변화 1.370818%와 급전 도체 최대 4.398922%를 구분하여 전체 개별 기준은 미확립으로 남겼다. 이어 별도 고정 6/7/8분할 심화 연구도 완료했다. 6분할은 원래 raw와 새 준비 XML의 바이트/SHA256 및 예산 이외의 물리 case/정규화/설치를 대조한 뒤 현재 계산기로 재계산하여 재사용했다. 기존 power_balance.analysis_plan_id를 새 비교 ID로 바꾸지 않으며 schema/source_kind로 구분한다. 최종 7/8분할의 유전체/도체 합계 변화는 1.031065/1.042424%지만 방사 도체가 최대 2.788446%여서 전체 개별 손실은 not_established다. 최대 전력 잔차 0.213135%의 충족과 구분한다. 최종 판정과 모든 원시/소스 해시는 [최신 실행 기록](../runtime_profiles/ro4350b-loss-refinement.json)에 보존한다.

재료 분할만의 실제 비용은 일반 9.619147초와 배열 경로 중앙값 0.014203초였다. 이는 동시 native 부하가 있는 단계별 비교이며 전체 FDTD의 속도 배율이 아니다. 최신 국부 4/5분할의 native 시간은 387.273601/578.742612초, 손실 후처리는 0.381237/0.513383초였다. 기존 300초/420초 경계를 넘는 실제 완료를 확인했다. 실제 납품 재료 2개의 미정 Dk/Df/전도도 6개, 제작/측정 조건과 승인 원문은 보존한다.

심화 N7/N8의 신규 native는 953.720996/1223.548302초, 손실 후처리 0.605467/0.713162초로 1800초 예산 안에 완료했다. 검증된 기존 N6 raw를 사용하여 약 754초의 동일 FDTD 반복을 피했다. 이번 계산은 N8에서 마무리하며 유한 폭 급전/접합부와 독립 손실 참조의 후속 검토는 개발 완료 계획의 RF 검증 단계에서 추적한다. 원인 확정이나 초기 기준 충족으로 과장하지 않는다.

가장 큰 N8의 후처리 전용 실행과 해석기 없는 재열기도 통과했다. 기존 등록 파일 135개와 native 실행 ID 5개를 유지했으며 포트/방사/독립 손실 결과가 동일했다. 완료한 고정 계산을 자동 재실행하지 않고 미확립 항목과 전체 개발 순서는 개발 완료 계획으로 이어간다.

심화 예산까지 포함한 Windows 전체 805개 중 718개 통과/87개 환경 스킵(392.146초), 최종 GUI 14개 통과/4개 스킵(141.129초), native 적분 15개 통과(2.937초), CTest 9개 통과(0.45초)다. 상위 대기/관련 계약 12개, 심화 입력 동일성/관련 계약 19개와 후속 재열기 도구 계약 7개는 별도 로그로 남겼다. 테스트의 스킵과 실제 native 실행 및 제조/측정 정확도를 구분한다. 자세한 범위와 재현 명령은 후속 연구 문서를 따른다.

## 개별 손실 정밀도와 PTH 검증 (2026-11-12)

세부 수식/수치 조건은 [손실 정밀도 계약](pcb_loss_precision.md), 소스와 원시 파일 해시는 [이번 실행 기록](../runtime_profiles/pcb-loss-precision.json)에 있다. native ADE sheet가 EC_G/EC_C를 대체하는 것을 확인하여 sheet edge의 material J를 제외했다. 유전체/PTH는 나머지 edge의 실제 QuarterCell 기여율로 분리한다. 초기 차감 방식의 음수 패드 오류와 원시 결과는 이력으로 보존하고, 새 후처리 결과에는 원래 FDTD 생산자와 현재 계산기를 따로 기록했다.

RO4350B의 12개 비교 행/9개 고유 조건 중 8개를 완료했다. 마지막 0.40/0.36 mm 비교에서 유전체 합계 최대 상대 변화는 0.045334%, 도체 합계는 3.430551%이므로 개별 손실 전체 기준은 미확립이다. 국부 4분할은 300초 예산에서 종료 확인 후 실패를 보존했다. 종료/곡선 축은 검사한 성분의 초기 기준을 충족했다. 완료 사례의 최대 전체 전력 잔차 0.193263%가 3% 안이라는 이유로 개별 성분 수렴을 합격시키지 않는다.

명시적 구리 PTH fixture의 수정 재계산과 최신 소스의 새 native 실행 3수준은 모두 초기 개별 손실/전력 예산을 충족했고 대응하는 손실 수치가 동일했다. 최대 전력 잔차는 0.747129%다. 작은 via 성분의 절대 바닥 기준과 GHz skin depth 미해상도를 구분하며 물리 정확도는 미검증이다. 1000 S/m 수치 참조의 국부 3분할도 300초 제한으로 미완료여서 해당 연구는 미확립이다. 균일 축방향 전계/실제 CSXCAD 중공 shell의 독립 해석식 대조는 0.025 mm에서 상대 차이 1.1771%였다. 이는 FDTD나 제조 시료의 검증이 아니다.

| 이번 검증 | 결과 | 시간 |
| --- | --- | --- |
| Windows 서비스 전체 회귀 | 794개 수집, 710개 통과, 84개 환경 조건 스킵, 실패/오류 0 | 377.693초 |
| 최종 손실/저장/연구 계약 집중 시험 | 이후 추가한 생산자 설정 hash 검사 포함 53개 수집, 52개 통과, h5py 조건 1개 스킵 | 10.843초 |
| 최종 스타일 정리/재빌드 후 실제 wxWidgets 프로세스 회귀 | 18개 수집, 14개 통과, CAD/명시적 WSL 조건 4개 스킵 | 73.533초 |
| native CSXCAD/적분 | 12개 통과. 실제 중공 shell과 시간 정렬/분할 포함 | 0.954초 |
| 최종 CTest | 9개 통과 | 0.32초 |
| guest 제어와 실제 WSL 연결 | guest 14개, Windows-WSL 2개 통과 | 35.114초 / 23.999초 |

스킵을 통과로 계산하지 않는다. 전체 회귀 뒤 추가한 생산자 보고서 hash 검사와 시험은 위 집중 시험에 포함되며 전체 회귀에 소급 집계하지 않는다. 새 native PTH의 후처리 전용 실행/해석기 없는 재열기는 원본 봉인 파일 81개 및 native ID를 보존했다. 8 MiB 초과 RO4350B 원시 필드도 별도 스트리밍 검사/재후처리로 확인했다. JSON 8 MiB, 단일 raw 64 MiB 및 기존 전체 예산은 확대하지 않았다. 실제 납품 물성/제작/측정 미정값과 승인 원문은 보존했다. GUI 60/30 fps 및 실물 RF 정확도를 이번 시험으로 수용 완료하지 않는다.

## 전체 구현과 이전 실행 범위

wxWidgets, Windows 11+WSL2 우선, Linux GUI 후속, 원호/IFA, 내부 검증 배포와 60/30 fps 초기 목표를 유지한다. WSL 개발 환경과 작은 해석 참조 사례 검증, GUI 선택 속성/영속 undo/redo와 wxAUI 기반 2D 편집 다음으로 별도 호스트 CAD worker와 Open CASCADE 형상/AP242 STEP 출력을 연결했다. 이어 GUI STEP 출력/작업 취소/완료 결과 복원과 wxGLCanvas 3D 형상 보기를 구현했다. WSL2 guest supervisor와 도파관 solver adapter의 준비/실행/취소/결과 저장 및 독립 후처리도 연결했다. 이어 원형 PCB 외형을 저장/편집/CAD/EM에 연결하고 사용자 PCB의 제한된 단일 포트 해석과 GUI 실행/결과 그래프를 추가했다. 접지 polygon/빈 영역, 패드, 중공 도금 비아와 IFA의 실제 급전/단락 도체 모델도 같은 명령/저장/GUI/CAD/EM 경로로 확장했다.

이후 용량 개선 구현을 `4414574`로 커밋/푸시한 뒤, [사용자 PCB 방사 계산](pcb_radiation.md)을 추가했다. 선택적 NF2FF 기록 상자/PML 검사, 12면 E/H 봉인, 별도 복소 필드 산출물과 전력 비율, 같은 raw의 재후처리, 해석기 없는 페이지 조회 및 wxWidgets 2D 절단면을 연결했다. 실제 사각/원형/IFA 사례가 모두 현재 worker 소스 107개의 동일 hash로 실행됐다. 실제 제작/측정 입력과 납품 물성의 미정 상태는 유지했다.

직전 방사 연결 버전의 Windows 회귀는 724개 수집/656개 통과/68개 조건부 스킵, 350.227초다. 별도 실제 GUI 17개는 CAD/WSL 조건을 활성화해 모두 통과했으며 203.437초였다. CTest 7개는 0.20초에 모두 통과했다. 사각 PCB의 3개 주파수/5 degree 방사 격자는 64.625초, 원형/원호의 3개 주파수/15 degree와 취소 검사는 56.328초, IFA의 2.44175 GHz/15 degree는 116.375초에 통과했다. 각각 raw 재후처리와 worker 없는 재열기를 포함하며 물리 정확도 합격으로 집계하지 않는다. 최초 플랫폼 간 수학 함수의 마지막 bit 차이를 허용하는 유한 상대 오차 검사를 보완했고 기존 capability 시험/시험 코드 오류를 고친 최종 결과다. 실패 기록도 보존한다.

같은 paint 안의 연속된 색상/선폭에 native pen을 재사용했다. 최종 합성 renderer p95는 일반 4.237 ms, 3000개 장면 25.060 ms였다. 바로 앞 무캐시 측정도 대형 22.392 ms로 예산 안이었으므로 전후 속도 개선을 단정하지 않는다. 전체 조작 FPS와 GUI/서비스/worker 합산 메모리는 별도 수용 항목이다. 원형 실제 결과의 방사 창에서 이전 개정, 100% 초과 효율의 검토 경고와 절단면을 시각 확인하고 검증 창을 종료했다. 수치/소스/바이너리/보고서 hash는 [이번 실행 기록](../runtime_profiles/pcb-radiation.json)을 따른다. 아래 누적 기록의 수치는 각 당시 버전의 범위다.

## 사용자 PCB 방사 수렴 추가 검증

[방사 수렴 연구](pcb_radiation_convergence.md)의 RO4350B 탐색 IFA에서 기록 거리 18/24/30 mm, 각도 30/15/5 degree와 격자 0.50/0.45/0.40 mm를 독립 비교했다. 9개 행/7개 고유 native 계산에서 마지막 인접 쌍과 최종 기준 전력 예산이 사전 기준을 충족했다. 격자/PML/기록 면/위상 중심의 실제 독립 조건을 먼저 검사했고 HDF5 84면의 실제 좌표/주파수/유한 필드도 확인했다. 이전 거친 격자와 30 degree의 일부 미충족 결과는 보존한다.

최종 구면 적분과 Prad의 차이는 0.490625~0.506502%다. 포트 항등식과 수동성 예산을 검사했지만 독립 도체/체적 흡수 손실과 전체 에너지 수지는 미평가다. 실제 납품 물성/제작/측정 입력은 미정으로 유지했다. 기존 S11 정합 목표 미달도 유지하며 R1 물리 검수 완료로 표시하지 않는다.

완료 연구의 solver 없는 재판정/재개에서 native 작업 7개, 원본 파일 224개, 전력 CSV와 수치 판정을 그대로 보존했다. 이전 판정은 별도 3개 파일이다. 제품 worker 소스 111개가 실제 실행과 일치한다. 전체 Windows 736개 중 668개 통과/68개 조건부 스킵(390.939초), 추가 관련 32개 통과(4.980초), GUI 13개 통과/4개 조건부 스킵(148.661초), 최종 CTest 8개 통과(0.36초)를 기록한다. GUI는 새 방사 연구의 읽기 전용 표/요약을 지원하며 최종 반올림 표시와 미평가 설명을 실제 창에서 확인했다. 상세 hash와 판정은 [별도 실행 기록](../runtime_profiles/pcb-radiation-convergence.json)을 따른다.

## 구현 현황

[일반 프로젝트의 연구 GUI](project_studies.md)를 추가했다. 현재 revision의 원본 바이트로 snapshot을 봉인해 매개변수/표현식/카탈로그 출처를 보존한다. 수치 조건/초기 기준을 고정하고 준비/해석 단계를 순차 실행하며 취소/서비스 중단은 자동 재실행하지 않는다. 명시적 재개에서 완료 단계를 재사용하고 각 시도를 남긴다. wxWidgets는 조건/판정/진행/전력을 표시하고 물리 계산은 기존 worker에 위임한다. 유휴 조정기는 명령 이벤트를 기다리며 journal을 주기적으로 다시 읽지 않는다. 이번 범위는 격자 한 축과 공통 방사/독립 손실 조건이며 기록 거리/각도의 3축 GUI 행렬은 후속이다.

최종 실제 GUI에서 RO4350B 3개 격자/3개 주파수의 계산, 취소 1회와 재개 및 프로그램 재연결을 통과했다. 표현식/출처/6개 납품 미정값을 유지했고 원본 개정과 전력/시도가 복원됐다. 방사 격자와 수지 예산은 충족했으나 포트 공진 수렴은 미확립이다. 최종 Windows 766개 중 691개 통과/75개 조건부 제외, GUI 14개 통과/4개 조건부 제외, 관련 계약 50개와 CTest 9개가 통과했다. 별도 실제 WSL 서비스 중단/재개 1개도 완료 준비를 재사용하며 통과했다. 최종 worker 소스 117개와 실제 GUI/보고서의 hash 및 제한은 [연구 GUI 실행 기록](../runtime_profiles/project-studies.json)을 따른다.

사용자 PCB의 [독립 흡수 손실과 전체 전력 수지](pcb_power_balance.md)를 추가했다. 무보간 Yee E/J/rotH를 원시 결과로 봉인하고 유전체의 체적 전도 손실과 native sheet의 실수 일률을 분리한다. 같은 실행의 수용/방사 전력과 비교하며 부호 있는 잔차/음의 성분을 보존한다. 기존 직접 입력과 손실 옵션 없는 과거 결과는 유지한다. 최초 planar 이후 PTH 분할을 확장했으며 3축 연구 GUI 행렬과 실제 납품 물성/제작/측정 조건은 남는다. 아래의 전력 수지 검증 기록은 당시 별도 실행으로 구분한다.

최종 탐색 IFA의 3개 격자/3개 주파수에서 최대 절대 상대 잔차는 0.191734%로 사전 초기 3% 예산 안이다. 개별 손실의 정밀 수렴이나 실제 제조/실측 합격은 뜻하지 않는다. 실제 재후처리에서 원본 81개 파일, 독립 손실과 native 계산 ID 3개가 유지됐으며 solver 없는 재열기/재판정/완료 재개를 통과했다. Windows 회귀 748개 중 676개 통과/72개 조건부 제외, 최종 호스트 관련 10개와 실제 WSL 적분 6개, CTest 8개를 통과했다. 상세한 범위와 hash는 [전력 수지 실행 기록](../runtime_profiles/pcb-power-balance.json)을 따른다.

| 항목 | 구현과 증거 | 남은 범위 |
| --- | --- | --- |
| 단위와 정규 직렬화 | SI Quantity, 미정 상태, 출처, 제한 JSON codec/hash | 복소수, 불확도, 충돌 후보, 물리 cache subset |
| 표현식 | 전용 parser, 차원/정의역 검사, UUID bindings, 의존 그래프 재계산, 순환 차단. Windows/Linux 49개 수식과 그래프/IFA 캐시 비교 통과 | 다른 CPU/엔진 조합과 추가 수식의 계산 캐시 호환 검증 |
| 실제 설계 데이터 | 사각/원형 기판, 적층, 재료, net, 선/원호/구멍 포함 polygon/패드/비아, 단일 lumped port와 명시적 급전 좌표. 참조 무결성과 역명령 | 일반 접속 엔진과 제조 DRC, blind/buried via |
| 목적별 입력 검사 | API-006 draft revision의 geometry/step/em, 고정 입력 TaskRef, 누락 진단 | snapshot 입력, 제조/물리 profile, solver 지원 검증 |
| 명령/저장/스냅샷 | revision/receipt 원자 게시, 재시작, crash 경계. 0.1/0.2 원본과 봉인 유지, 첫 변경의 새 0.3 개정과 변환 기록. 영속 undo/redo와 history head 보호 | 이력 grouping/임의 이동, 독립 archive/import, GC, 정전 내구성 |
| 목표 대역 입력 | target.set/remove와 wxWidgets 다중 목표 편집, 대역/주파수 표본/port/Z0와 4개 지표 한계, 목표별 개정/출처/미정 및 미평가 표시 | 프리셋/관측/편파/제약, MetricRecord/Assessment 평가와 일반 raw 재사용 |
| 원호/IFA 템플릿 | 명시 치수 카드2종, 현재 기판/도체층/목표 개정 선택, 읽기 전용2D 후보, 검토 hash와 원자 적용/undo, 생성 당시 출처/원본 사본 | 문헌 원본 카드/초기 RF 합성/확장 topology, 제조/실물 정확도, 일반 연결/DRC |
| Python 환경 | 서비스 .venv와 별도 .venv-cad, 44개 CAD 패키지 버전/wheel SHA256 고정 | 배포 패키지와 전체 라이선스 검증 |
| CAD 환경 smoke | CadQuery 2.8.0/cadquery-ocp 7.9.3.1.1 박스 AP214 export/reimport의 초기 호환성 기록 | 배포 환경과 독립 수신 CAD 검증 |
| CAD 기하와 STEP | 불변 snapshot을 mm로 투영, 사각/원형 유전체와 양수 두께 선/원호/영역/패드, 실제 drill과 중공 PTH barrel. 같은 층/net/재료 병합과 UUID mapping, AP242 schema/단위와 별도 OCCT reader 재입력, B-rep/sidecar | 독립 kernel 수신 CAD, 제조 및 RF 검증. 내부 기하 profile은 generated_unverified |
| CAD worker와 API | 호스트 설정의 별도 프로세스, 입력/runtime/소스 묶음 봉인, 실행 중 편집/저장/조회, 취소/timeout/출력 제한, nonce와 파일 streaming 봉인/원자 게시. API-008/023/024 비동기 TaskRef와 STEP CLI, cad.latest 완료 참조 조회 | CAD outcome_unknown 수동 조정 API, 자동 GC/cache |
| GUI 작업 공간 | C++ wxMSW/wxAUI의 탐색/중앙 2D와 3D 탭/속성/문제/로그/CAD 출력 배치, 패널 복원, 안정 ID 선택 동기화, 한글 속성과 입력 상태, 매개변수/표현식/UUID 결합, 영속 Ctrl+Z/Y/Shift+Z, 재료/net/단일 포트 생성 | 결과 비교/제조 출력 작업 공간, DPI/접근성과 전체 앱 성능 측정 |
| GUI STEP와 3D | 적용 후 불변 snapshot 접수, CAD 중 편집/저장, 취소와 출력 폴더, 이전 개정 표시 및 재열기 완료 결과 복원. 실제 OCCT 고체에서 생성한 표시 mesh의 background hash/경계 검사, 지연 wxGLCanvas 생성, 회전/이동/확대/선택, 오류 시 context 재생성 재시도 | LOD, 실제 GPU reset/DPI/도킹 복구 수용, 대형 장면/성능 예산, 독립 CAD와 제조/RF 판정 |
| 2D 직접 편집 | 사각/원형 기판과 미정 도체층/미정 유전체층 생성, 두 점 선분, 중심/시작/끝 방향 원호와 Shift CW, 수치 좌표 생성, 선택/이동/삭제, preview와 단일 명령 commit, fit/zoom/pan | 마우스 스냅, endpoint 편집/회전/미러/구속/Boolean/고급 도면, 정밀도와 최종 시각 수용 |
| GUI 입력 검사 | 명시적 EM 입력 검사, 문제 목록과 객체/필드 이동, 이전 revision 진단 이동 거절 | 일반 접속/제조 DRC와 정식 물리 검증 |
| WSL/openEMS 환경 | Ubuntu 24.04.5 WSL2 실행, Linux 서비스 및 표현식 비교 통과. Qt 없는 openEMS 0.37.0/CSXCAD 0.7.0 빌드와 두 격자 도파관 참조 검사 통과 | 사용자 PCB 방사 수렴, 실측/독립 solver 정확도 검증 |
| WSL solver와 결과 | AnalysisPlan/PreparationArtifact/PreparedPlan, 봉인 XML 실행과 raw/정규화/출처, 독립 후처리. ext4 staging, supervisor/watchdog, nonce/lease/재접속/취소. 사각/원형 PCB 선/원호/접지 polygon/패드/PTH, 유한 도체, x/y/z gap 급전, IFA short 연결과 Yee edge 검사, GUI S11/VSWR/임피던스. 선택적 NF2FF 12면 봉인/재후처리와 GUI 방사 절단면 | 공개 수동 조정, cache/GC, SMA/실장 급전, 방사 수렴과 실측 |
| IFA 수치 안정성 | 명시적 시험 입력의 3단계 격자/3단계 경계/2단계 시간 종료 비교, 고정 물리 PML 두께와 graded air, 공개 API 실행/재개/독립 재판정, JSON/CSV/비교 그림 | 아래 실제 검증 기록의 범위만 수용. GUI 다중 결과 비교, 국부 특징/곡선/PML 셀 수 민감도, 제조/실측 정확도 |
| PCB 카탈로그 | 전체 정리 관측/원시 적층의 중립 모델, 오프라인 SQLite 변환과 검토 사유, 읽기 전용 검색/상세 CLI 및 JSON-RPC, 원문 타입/출처/해시와 페이지 보존 | 카탈로그 갱신/배포 범위와 GUI 페이지 검색 |
| PCB 선택/적층 적용 | 프로젝트 소유 출처와 사용자 수정값, Dk/Df 독립 선택, 업체별 초안/층/급전 대응, wxWidgets 검색/단면/변경 미리보기, 원자 적용/undo. 기존 직접 입력 유지 | 업체 주문/실측 조건 확정. 초안 저장은 제조/RF 승인과 구분 |
| 적층 물성 제안 | 제조업체 적층의 같은 출처/원문 층에 대응하는 두께/Dk/Df 제안, 페이지별 GUI 검토와 명시적 수용, 공개값/미정/충돌/근사 필요 구분 | 제공되지 않은 Df/완성 동박/적용 대역 유지. 823개를 포함한 전체 3409개 후보의 용량 제한은 해소. 더 큰 제품 장면의 별도 계측 필요 |
| 유전체 손실 모델 | 기존 합산 모델 보존, 명시적 총 Df 모델 추가. 독립 전도도 미정/비소비 보존과 중심 주파수 kappa 환산, 실제 native 양성 대조군 통과 | 광대역 분산/방향별 모델, 실제 시료 물성 및 모델 오차 검증 |
| 카탈로그 PCB 통합 | JLC0206의 CAD/STEP/미정 RF 입력 차단 기록 유지. 별도 RO4350B 탐색 모델에서 같은 snapshot의 CAD/STEP/openEMS/재후처리/결과 재열기 통과 | 실제 제작 적층/동박/급전 확인, RO4350B의 복소 S 변화는 충족했으나 내부 공진 비교와 전체 수렴은 미확립. 제조/측정 검증 필요 |

서비스는 rfad.api/2.0, workspace profile은 rfad.projects/0.2, 새 프로젝트 문서는 rfad.project/0.3이다. 0.1/0.2 원본과 snapshot 읽기는 유지한다. 세부 계약은 [저장](project_persistence.md), [설계 데이터](design_data.md), [목표 입력](target_contract.md), [선택 속성](editor_contract.md), [2D 표시/편집](canvas_contract.md), [CAD/STEP](cad_contract.md), [worker 실행](worker_integration.md), [기초 계약](bootstrap_contract.md)을 따른다. 전체 API나 R0/R1 완료를 주장하지 않는다.

## 개발 환경 결과

- Windows 11 AMD64, CPython 3.12.10, Intel Core i7-1365U, 약 32 GiB RAM에서 확인했다.
- CMake 4.3.2, Ninja 1.13.2, MinGW-w64 g++ 16.1.0 UCRT/MCF를 사용한다. MSVC는 현재 PATH에 없다.
- wxWidgets 3.2.12와 nlohmann/json 3.12.0 소스는 공식 배포에서 받아 SHA256을 확인했다. Qt 또는 유료 GUI 부품을 요구하지 않는다.
- GUI 3D 빌드는 기존 core/base/aui에 wx gl을 추가하고 Windows opengl32와 bcrypt를 연결한다. OpenGL 화면은 첫 mesh를 열 때 생성한다. CAD의 기존 44개 고정 Python 패키지 환경은 유지한다.
- 서비스 환경은 pip/setuptools/tracewave-studio이며 CAD/OCP/NumPy/SciPy/VTK/Qt를 import하지 않는다.
- CAD 환경은 전체 고정 의존성 설치와 pip check를 통과했다. Qt 배포/DLL/로딩 모듈이 없다. 박스 10 x 20 x 1.6 mm를 STEP AP214로 저장/재입력하여 유효 solid 1개, 체적 320.0000000000001 mm3를 확인했다. 같은 kernel 왕복이며 독립 CAD 검증은 아니다.
- CAD 첫 import에서 약 30초, 재실행에서 약 5.78초를 관찰했다. 시작 성능 합격 값이 아니며 GUI/서비스와 분리한 worker가 필요하다는 근거다.
- 2026-11-07 WSL 설치는 재부팅 필요 상태였다. 2026-11-10 재부팅 후 전용 TraceWave-Dev에 Ubuntu 24.04.5를 설치하고 실제 WSL2 실행과 Linux 서비스 시험을 완료했다. Qt 없는 VTK/openEMS/CSXCAD와 바인딩을 빌드하고 작은 TE10 도파관의 두 격자 검사를 통과했다. 임피던스 최대 상대 오차는 0.617% 미만, 군지연은 0.108% 미만이며 지정한 종료 에너지 조건도 충족했다. 상세 근거는 [Linux 환경](linux_environment.md), [참조 검사](openems_reference.md)에 있다.

재현 방법과 로컬 보고서는 [Python 환경](python_environment.md), [wxWidgets](../ui/wxwidgets/README.md), [WSL 환경](wsl_environment.md)에 있다. 의존성/빌드/가상환경/호스트 경로가 담긴 보고서는 .local/build/.venv 계열에 두고 Git에서 제외한다. 개발 lock을 제품 배포 manifest로 간주하지 않는다.

## 검증 기록

2026-11-07 Windows 전체 시험 166개가 54.105초에 통과했다. 스킵과 실패는 없다. 기존 109개에 표현식 17개, 그래프 8개, 설계 22개, 저장 통합 5개, 실제 GUI 프로세스 5개를 추가했다. 이후 GUI writer 종료 신호의 mutex 보완본을 재빌드하고 해당 GUI 5개를 다시 실행하여 모두 통과했다(16.342초).

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_GUI_EXE = (Join-Path (Get-Location).Path 'build/windows-release/bin/tracewave_gui.exe')
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

GUI 실행 파일을 지정하지 않으면 Windows 전용 GUI 시험은 스킵된다. 최초 기록 당시 5개, 속성 편집 버전은 6개였으며 현재 2D 시험을 포함해 7개다. 최초 전체 로그는 `.local/all-tests.log`, CAD 근거는 `.local/python/cad-smoke.json`, WSL 상태는 `.local/wsl/status.json`에 있다.

- 단위/유한값/미정 상태, 정규 바이트/.NET SHA256 비교, 손상과 자원 제한.
- 실제 프로세스의 UTF-8 JSON-RPC, 한글/공백 경로, 재전송/epoch, 파일 잠금과 게시 전후 강제 종료.
- 표현식 차원/정의역/임의 코드 문법 거부, UUID 결합, 연쇄 재계산, 순환/삭제 실패의 원본 보존.
- board/material/layer/net/line/arc/port의 검증과 역명령, 미정 물성과 물성 대역 차단.
- 설계/표현식 명령 -> 저장 -> 스냅샷 -> 종료/재시작 -> 재열기, 이전 스냅샷 바이트 보존.
- 목적별 검증의 입력 revision 고정과 멱등 재접수. 검사 작업 완료와 설계 합격을 별도로 표시.
- 초기 IFA fixture의 승인 기준 치수와 미정 물성/미완성 형상 보존.
- GUI 실제 이벤트 루프에서 한글/공백 경로, 저장/스냅샷/서비스 재시작, 로그 폭주, 과대 프레임, 서비스 조기 종료와 실행 파일 누락 처리.
- 실제 창에서 IFA 기준 입력을 열어 14개 매개변수와 한글 이름/설명이 표시되는 것을 확인했다. 실행 도우미 재실행과 정상 닫기 종료 코드 0도 확인했다.
- wxMSW Release 실제 빌드 및 runtime DLL 배치 완료. 소스 경로의 공백으로 발생한 windres include 문제를 재현하고 작업 디렉터리 지정으로 해결했다.

2026-11-10 신규 시험을 포함한 Windows 전체 183개가 32.002초에 통과했다. Linux는 전체 183개 중 178개 통과, Windows 전용 GUI 5개 스킵이며 실패/오류 없이 13.639초였다. Windows/Linux 표현식 49개, UUID 의존 그래프와 IFA 저장 캐시의 정확 일치도 확인했다. 추가 설치 도구는 Qt 전이 의존성 및 기존 계정/소스 변경 차단을 검증한다. 참조 판정기는 조기 중단과 종료 조건 미충족을 실패로 처리하는 시험을 포함한다. 근거는 `.local/windows-tests-final.log`, `.local/wsl/service-tests-final.log`, `.local/portability/linux-check.json`이다.

이후 설치 도구의 미추적 CMake override 거부와 재사용 VTK 감사 시험 4개를 추가했다. 관련 설치 시험 8개를 Windows/Linux 양쪽에서 다시 통과했고, 보완된 도구의 실제 소스/패키지/전체 native 감사도 통과했다. 전체 회귀 시험과 변경 부분의 후속 검증을 구분한다.

같은 날 편집기 구현 후 Windows 전체 205개가 45.877초에 통과했다(스킵 없음). Linux는 전체 205개 중 199개 통과, Windows 전용 GUI 6개 스킵이며 20.500초였다. 로그는 `.local/editor-windows-tests.log`, `.local/editor-linux-tests.log`다. 서비스 편집/이력 15개, 실제 stdio 편집 재시작 2개와 실제 GUI 편집 1개를 추가했고 이전 설치 guard 4개도 전체 실행에 포함했다.

이어 한글 표시와 입력 방식별 속성 화면을 보완한 버전에서 Windows 전체 207개가 스킵 없이 48.800초에 통과했다. Linux는 전체 207개 중 201개 통과, Windows 전용 GUI 6개 스킵이며 19.513초였다. 로그는 `.local/ux-windows-tests.log`, `.local/ux-linux-tests.log`다. 추가 2개 시험은 한국어 표시와 실제 API 값/UUID/원본 및 읽기 전용 규칙의 분리를 검증한다.

이 버전은 미적용 입력/적용 후 저장 필요/저장됨, 프로젝트 이름과 식별자 tooltip, 한글 선택지와 읽기 전용 display_value, ID/좌표계 상세 접기, 입력 방식별 숨김, 값과 단위의 같은 행 배치, 진단의 객체 UUID 대응과 한글 필드 초점, Ctrl+Shift+Z를 포함한다. 이후 단위만 변경한 초안의 환산 안내와 마지막 적용값 라벨을 보완하고 실제 GUI 6개를 13.780초에 다시 통과했다. 단위 변경 안내의 생성/복원까지 포함한 UX assertion 14개를 편집 프로세스 시험에서 확인한다. 최종 로그는 `.local/ux-gui-final.log`, 소스와 실행 파일 hash를 포함한 실행 요약은 `.local/ux-verification.json`이다.

속성 편집 버전의 GUI 시험은 실제 폼 컨트롤을 사용해 매개변수/의존식 생성, 재계산, 잘못된 수식의 입력/개정 보존, undo/redo와 저장/스냅샷/서비스 재시작을 확인했다. 당시 초기 시각 점검에서 발견한 세로 여백과 선택 후 초점 이동을 수정하고 GUI 6개 시험 및 전체 Windows 시험을 통과했다. 해당 작업 차례의 추가 화면 자동화는 사용자의 Esc 입력으로 중단했으며 수정 후 시각 확인은 완료되지 않았다. 이는 아래 2D 작업 공간의 후속 시각 확인과 별개의 과거 기록이다.

그다음 wxAUI 작업 공간과 2D 편집을 연결한 초기 버전의 실제 GUI 7개 시험이 22.337초에 통과했다. 새 2D smoke의 최종 검사 항목 14개는 도킹, Esc 취소, 두 점 선분, 원호 방향과 hit testing, 선택 동기화, 드래그의 단일 명령, undo/redo, 속성의 장면 반영, 거절된 제스처의 선택 복원, 삭제/취소, 표시 제한, 보기의 원본 불변성, 입력 검사와 실제 해석의 구분, 저장/스냅샷/재시작이다. 독립 stdio 통합 시험 4개는 음수 sweep, 실패/stale 불변성, 참조 좌표 재평가, 미정 치수와 물성 보존도 확인했다.

이후 미정 보드 치수, 표시 범위와 큰 좌표의 native 렌더링 정밀도 경계를 보완한 버전에서 Windows 전체 227개가 스킵 없이 76.152초에 통과했다. Linux는 227개 중 220개 통과, Windows GUI 7개 스킵이며 30.312초였다. 로그는 `.local/canvas-windows-tests.log`, `.local/canvas-linux-tests.log`다. native CTest `canvas_geometry`도 1개 통과(0.13초)했으며 `build/windows-release/Testing/Temporary/LastTest.log`에 기록했다. 이전 207개와 초기 GUI 7개는 해당 시점의 검증 기록으로 유지한다.

실제 Windows 시험 창에서 발견한 상단 도구막대 높이의 잘림과 DPI에 따른 초기 창 크기를 보완했다. 입력 검사 진단의 message_ko 본문 연결, 결과가 64개를 넘을 때 전체/표시 건수 구분, 프로젝트를 연 뒤 조작 안내도 수정했다. 최종 Release 빌드 후 GUI 7개가 25.908초에 다시 통과했다. 로그는 `.local/canvas-gui-final.log`이며 한국어 진단 본문이 실제 목록에 전달되는 assertion도 포함한다. 최종 소스/실행 파일 hash와 검증 요약은 `.local/canvas-verification.json`에 기록했다.

별도 작업 영역의 실제 창에서 상단 도구막대와 탐색/캔버스/속성/문제 패널 배치, 40 x 60 mm 기판의 선/원호 표시, 캔버스 선택과 속성/트리 연동, 검사 사유 표시와 재료 오류를 두 번 눌러 해당 속성으로 이동하는 동작을 확인했다. 시험 창은 정상 닫기로 종료했다. 현재 디스플레이에서 수행한 제한된 시각 확인이며 모든 DPI/다중 모니터/IME 조합이나 성능 예산의 수용을 뜻하지 않는다.

승인된 전체 작업 공간과 현재 구현된 2D/속성/문제 화면의 관계는 [GUI UX 구현 방향](../ui/wxwidgets/README.md#ux-구현-방향)에 정리한다. [완성형 UI 시안](ui_concept.md)은 목표 구성을 설명하는 검토 자료이며 실제 GUI 실행 화면이나 해석 결과의 증거로 취급하지 않는다. 현재 그리드는 표시 설정이며 마우스 스냅은 미구현이다. 치수와 좌표를 정확히 지정할 때는 수치 입력을 사용한다.

현재 소스로 새 Windows 표현식 기준을 만들고 Linux에서 다시 비교했다. 49개 수식/UUID 그래프/IFA 캐시는 정확히 일치했고 기존 결과 hash와도 같았다. 근거는 `.local/portability/windows-editor-baseline.json`, `linux-editor-check.json`이다. 이전 기준이나 스냅샷은 덮어쓰지 않았다.

현재 CAD 구현의 시험은 순수 입력 투영, fake native 프로세스의 종료/출력 경계, 실제 서비스-CAD 분리 실행, 얇은 도체와 signed sweep/완전 원환, 같은 net Boolean과 분리 body 충돌, 실제 AP242 파일과 이름 기반 재입력을 포함한다. 원본 snapshot, 미정 물성/UUID 결합, 파일 SHA256과 sidecar 대응을 확인하며 현재 개정을 편집해도 접수한 출력 입력은 바뀌지 않는다. 서비스 환경에는 CAD 패키지를 import하지 않고 native 시험은 별도 `.venv-cad`에서 실행한다. 보존 예제는 `.local/cad-worker-verification/latest.json`이 가리키는 STEP/B-rep/sidecar와 검증 파일이며, 선/원호 기하 교환 예제로서 실제 IFA 보드의 RF 검증 근거가 아니다.

GUI 3D 연결 전 CAD 버전의 Windows 전체 287개는 279개 통과, 별도 CAD 환경용 8개 스킵으로 148.984초에 완료했다. Linux 전체 287개는 269개 통과, native CAD 8개/Windows CAD 프로세스 2개/Windows GUI 7개/Windows Job Object 1개 스킵으로 81.977초에 완료했다. 실패와 오류는 없다. 스킵된 native CAD 8개는 고정된 `.venv-cad` 환경에서 모두 통과했다(3.184초). Windows 전체 시험에는 실제 GUI 7개와 분리 CAD 프로세스 2개가 포함된다. 로그는 `.local/cad-windows-tests.log`, `.local/cad-linux-tests.log`, `.local/cad-native-tests.log`이며 소스/문서 hash와 요약은 `.local/cad-verification.json`, 실행 환경 기록은 `runtime_profiles/cad-worker-windows-x64.json`이다. 실제 worker 예제와 `tools/export_step.py`를 각각 실행하여 AP242 STEP, B-rep, 원본 sidecar, 검증 보고서와 manifest 게시를 확인했다. CLI 결과는 `.local/cad-worker-verification/cli-fafc6d6d-2de3-4934-8f3b-b650345c9b89.json`에 보존했다. 이전 227개 및 GUI/2D 수치는 해당 구현 시점의 이력으로 유지한다.

이후 GUI의 `STEP 출력`/`3D 갱신`과 하단 `CAD 출력` 작업 기록을 연결했다. 스냅샷 생성 전 폼 입력을 적용하고 CAD 실행 중에는 편집/저장과 상태 조회를 분리한다. 취소/실패는 이전 결과를 유지하고, 현재 개정과 다른 형상은 이전 설계로 표시한다. `cad.latest`는 큰 파일을 열지 않고 해당 프로젝트의 최근 완료 참조만 복원한다. 새 유전체층은 실제 z 위치/두께/재료를 미정으로 유지하며 원본 명령/undo/redo를 따른다.

출력 패키지는 mesh.json을 추가한 6개 파일이다. 표시 mesh의 snapshot/run/body/source 대응과 파일 SHA256을 봉인하고 GUI background에서 같은 바이트를 검증한다. 정확 STEP/B-rep와 표시 삼각형의 오차 계약은 분리한다. 초기 상한은 100000 triangles/300000 vertices/16 MiB이며 wxGLCanvas는 첫 로딩 때 생성한다. 표시 float 변환 뒤 퇴화/방향 뒤집힘과 변 길이 왜곡을 검사하며 실패하면 이전 정상 장면과 게시된 STEP를 유지한다. 회전/이동/확대와 안정 ID 선택을 제공한다. context 오류에서 전체 보기는 기존 canvas의 wxGLContext 재생성을 시도하고 최초 생성 실패는 새 3D 갱신으로 재시도한다. 실제 GPU reset/DPI/도킹 복구 수용과 LOD는 후속이다. 표시 실패가 편집/저장이나 완료 STEP 파일의 접근을 막지 않도록 분리했다.

최종 GUI STEP/3D 버전의 Windows 전체 303개는 294개 통과, 별도 CAD 환경 전용 9개 스킵으로 205.771초에 완료했다. Linux 전체 303개는 282개 통과, native CAD 9개/Windows CAD 프로세스 2개/Windows GUI 9개/Windows Job Object 1개 스킵으로 149.587초에 완료했다. 실패와 오류는 없다. 별도 `.venv-cad`의 native CAD/mesh 9개는 모두 통과했다(4.217초). wxGL을 포함한 Release 전체 빌드와 마지막 화면 보완본 재빌드도 성공했다. native CTest는 canvas_geometry/display_mesh 2개 모두 통과했다(합계 0.26초). 로그는 `.local/gui-cad-windows-tests.log`, `.local/gui-cad-linux-tests.log`, `.local/cad-mesh-native-tests.log`, `.local/gui-cad-ctest.log`, `.local/gui-cad-build-tail.log`, `.local/gui-cad-build-final.log`다. 소스/실행 파일 hash와 실행 기록은 `.local/gui-cad-verification.json`, 현재 환경 요약은 `runtime_profiles/gui-cad-windows-x64.json`에 기록한다. 앞의 287개/native 8개와 2D 수치는 이전 구현의 검증 이력이다.

Windows 전체 시험에는 기존 GUI 7개와 새 CAD GUI 통합 2개가 포함된다. 새 시험은 폼 적용 뒤 snapshot 고정, 출력 중 편집/저장, 편집 오류 뒤 다른 응답 보존, 이전 개정 표시, 실제 GL paint/swap, 표시 완료 후 버튼 복구, 취소 후 이전 결과 유지, 서비스 재시작 후 복원과 미정 필수 치수의 출력 차단을 확인했다. 표시 mesh의 파일 hash/경로/하드링크/색인/상한, float 변환 뒤 붕괴, 깊이 선택과 카메라 경계는 별도 C++ 시험으로 확인했다.

시험용 선/원호 workspace의 실제 Windows 창에서 STEP 버튼으로 새 패키지를 생성하고 1512개 표시 삼각형, 위쪽 보기, 휠 확대, 마우스 회전과 body 선택의 속성 연동, 완료 경로를 확인했다. 같은 net의 병합 형상을 선택하면 대표 패턴 속성임을 알리는 안내를 추가하고 중복 조작 안내를 제거했다. 마지막 보완본에서 두 안내의 실제 표시와 정상 창 종료도 확인했다. 보존된 예제 workspace는 `.local/cad-worker-verification/line-arc-80842a72`, 실제 버튼으로 생성한 run은 `06884d0f-521c-4dd4-a605-5c1f244aafa1`이다. 현재 디스플레이에서의 기능/시각 확인이며 모든 GPU/DPI와 성능 예산의 수용을 의미하지 않는다.

60/30 fps, 전체 프로세스 메모리/최초 실행 예산, 제품 IFA/원호 해석, 정식 수렴/정확도와 실측은 아직 검증하지 않았다. 초기 AP214 환경 smoke와 이번 제한된 AP242 제품 adapter 검증을 구분한다. 같은 OCCT kernel의 별도 reader로 재입력했으므로 `kernel_independent=false`이며 결과는 `generated_unverified`다. 제조 전달 합격이나 독립 CAD 검증 완료로 확대하지 않는다.

## WSL solver 연결 검증 (2026-11-11)

`solver.plan`, `solver.prepare`, `job.submit`, `job.cancel/status`, `result.open`을 [도파관 참조 profile](solver_contract.md)로 구현했다. 준비 단계는 실제 CSXCAD XML/격자/소비 보고를 봉인하고 FDTD는 실행하지 않는다. 해석은 그 XML을 native openEMS CLI에 전달하며, raw만 사용하는 후처리 전용 작업은 solver를 다시 실행하지 않는다. GUI 해석 실행과 사용자 안테나 투영은 이 단계의 범위에 포함하지 않는다.

최종 공개 API 검증은 `.local/openems-worker-verification/service-final`과 `report-final.json`에 보존했다. 준비/해석/후처리의 영속 상태 순서, 두 격자의 해석식 대조, 원시 파일/표본을 바꾸지 않은 재후처리, 실행 중 취소와 실제 guest 종료 확인, 서비스 재시작 후 결과 조회 일치를 통과했다. 전체 검증 도구 관찰 시간은 67.953초이며 성능 예산 합격값은 아니다.

| 항목 | 목표 격자 1.0 mm | 목표 격자 0.75 mm |
| --- | --- | --- |
| 실제 native cell 수 | 18711 | 46200 |
| 실제 반복 수 | 4305 | 6003 |
| 최대 반사 진폭 | 0.003071662 | 0.002570359 |
| 최대 전달 진폭 오차 | 0.000019406 | 0.000019911 |
| 최대 임피던스 상대 오차 | 0.6161% | 0.5152% |
| 최대 군지연 상대 오차 | 0.1070% | 0.0651% |
| native 로그의 종료 에너지 감쇠 | -71.24 dB | -71.28 dB |

두 격자의 최대 임피던스 상대 차이는 0.3113%, 전달 진폭 차이는 0.000017404다. 31개 주파수의 복소 결과와 정상 종료 로그/통계/실제 입력 hash를 host에서도 대조했다. 준비/해석은 설치 감사의 native 파일과 Python 패키지, 실제 로딩 경로를 검증했고 Qt는 없었다. 공식 CalcPort와 독립 raw DFT 결과는 rel/abs 1e-9 내에서 일치했다. 독립식의 진공 임피던스 상수와 native 상수의 약 0.55 ppb 차이를 포함한 허용치다.

| 검증 | 통과 / 스킵 | 실행 시간 | 로컬 로그 |
| --- | --- | --- | --- |
| Windows 전체 회귀, GUI/CAD/실제 WSL transport 포함 | 348 / 17 (365개 수집) | 245.580초 | .local/openems-worker-windows-tests.log |
| Linux 서비스 전체 회귀 | 341 / 24 (365개 수집) | 144.747초 | .local/openems-worker-linux-tests.log |
| 최종 Linux guest 프로세스 감독 | 12 / 0 | 19.407초 | .local/openems-worker-guest-final-tests.log |
| 최종 Windows WSL transport, launcher 단절/재접속 포함 | 12 / 0 | 10.122초 | .local/openems-worker-host-final-tests.log |
| 최종 native openEMS adapter | 6 / 0 | 25.210초 | .local/openems-worker-native-final-tests.log |

전체 회귀는 당시 guest 시험 7개를 수집했다. 이후 보완한 새 process group의 정상/취소/timeout 회수, setsid 후손 취소, 소유권 확인 실패의 unknown 유지까지 5개를 추가해 최종 guest 시험 12개를 별도로 통과했다. 독립 검토에서 정상 종료 시 별도 process group 후손이 누락되는 문제를 재현했고, 모든 terminal 경로에서 nonce 소유 후손 회수를 확인하도록 수정했다. 무관한 별도 세션의 Python은 종료하지 않는 것도 실제 검사했다.

Windows 스킵은 별도 CAD 환경의 native 단위 시험 9개, Linux native openEMS 1개와 guest 7개다. Linux 스킵 24개는 Windows GUI/CAD 경로와 native CAD 환경, opt-in native openEMS 및 Windows WSL transport다. 새 native openEMS는 위 별도 환경에서 실제 실행했다. Linux 첫 전체 명령은 PYTHONPATH 누락으로 import에 실패했고 명령을 수정한 전체 재실행이 표의 결과다. 실행 실패 기록도 `.local/openems-worker-linux-invocation-error.log`에 보존했다.

검증한 코드/감독기 hash와 상세 근거는 `runtime_profiles/openems-worker-wsl.json`에 기록한다. 게스트 staging/로그/raw와 미게시 자료는 자동 삭제하지 않는다. 이번 결과는 작은 진공 PEC 도파관의 제한된 제품 경로 검증이며 IFA/NF2FF, 정식 수렴, 손실 재료/급전/제작 및 측정, 임의 코드 보안 격리, 60/30 fps와 전체 메모리 수용을 입증하지 않는다.

## 원형 PCB와 사용자 해석 연결 검증 (2026-11-11)

원형 PCB를 중심/반지름 수량과 UUID 매개변수 참조로 저장하고 생성/속성 편집/undo/redo/저장/스냅샷/2D 표시에 연결했다. 원호 패턴과 외형은 독립이며 접지나 패턴을 자동 생성하지 않는다. Open CASCADE는 정확한 원통 유전체와 기존 선/원호 도체 고체를 만들고 실제 원 외곽 밖의 폭/끝단을 거절한다. STEP 재입력과 표시 mesh에서도 원형을 유지한다. [원형 외곽 계약](circular_board.md)에 상세 의미와 한계를 기록한다.

`rfad.openems.pcb-single-port/0.1`은 사용자 사각/원형 기판, 유전체 물성, 동박 전도도/두께, 선/원호와 동일 sheet 면의 명시적 단일 급전을 소비한다. 곡선 polygon 오차와 sheet/유전체 손실 근사를 계획에 기록하고 native polygon의 단자 접촉, 열린 급전 간극 전체 및 다른 net/재료 도체의 접촉을 검사한다. 상세 범위는 [PCB 해석 계약](pcb_solver_contract.md)을 따른다. 단일 포트 IFA의 검증 완료를 주장하지 않는다.

GUI에 원형 기판, 재료/net/포트 생성, 해석 조건/실행/취소, S11/VSWR/복소 임피던스 그래프를 추가했다. `launch_gui.ps1 -OpenEmsWsl`로 활성화하며, 접수 시 스냅샷 고정, 실행 중 편집/저장, 이전 개정 표시, 취소/실패 후 기존 결과 유지와 재시작 복원을 제공한다. `solver.latest`와 `solver.samples`는 solver 환경 없이 조회하며 계산을 다시 실행하지 않는다.

입력 점검과 계획의 필수 물성 목록을 공유해 금속 sheet가 쓰지 않는 유전율/손실을 요구하지 않는다. 실제 급전 좌표 누락을 안내하고, 일반 입력이 완비되면 `input_status=valid`, `solver_ready=false`, `validation_scope=input_only`를 반환한다. 후속 계획 검증이 필요하다는 이유로 항상 E_UNSUPPORTED를 추가하던 이전 동작을 제거했다. 입력 통과와 물리 수용을 구분한다.

| 최종 검증 | 통과 / 스킵 | 실행 시간 | 로컬 로그 |
| --- | --- | --- | --- |
| Windows 전체 회귀, 실제 GUI/CAD/WSL transport 포함 | 393 / 28 (421개 수집) | 235.575초 | .local/pcb-windows-final-tests.log |
| Linux 서비스 전체 회귀 | 389 / 32 (421개 수집) | 140.609초 | .local/pcb-linux-final-tests.log |
| 실제 PCB 4개와 기존 도파관 adapter 6개 | 10 / 0 | 34.223초 | .local/pcb-and-waveguide-native-current-tests.log |
| 원형 기판/실제 native CAD | 10 / 0 | 4.318초 | .local/circular-board-native-current-tests.log |
| wxWidgets native CTest | 2 / 0 | 0.42초 | .local/pcb-gui-ctest.log |

환경 전용 시험은 해당 환경에서 별도로 실행한다. Windows 스킵은 Linux process group/native openEMS 및 별도 CAD 환경의 단위 시험이며 Linux 스킵은 Windows GUI/CAD/transport와 별도 native 환경의 시험이다. 최종 전체 Windows 시험에는 원형+원호의 실제 GUI 해석과 빈 원형 보드의 필수 입력 차단도 포함된다. Release 빌드 성공 후 같은 바이너리로 실행했다.

공개 JSON-RPC 검증 도구 `tools/verify_pcb_worker.py`는 명시적 시험 fixture를 공개 생성/편집 명령으로 구성하고 계획/준비/실행/독립 후처리/실행 중 편집/취소/재시작을 검증했다. 최종 실행은 33.594초였으며 `.local/pcb-worker-verification/service-final`과 `report-final.json`에 보존했다. 반지름 8 mm 원형 PCB와 원호를 포함한 8~12 GHz의 31점 계산에서 native 격자점 90972개, 1085 step, 종료 에너지 감쇠 40.33 dB를 관측했다. 재후처리 표본/raw의 완전 일치와 실제 guest 종료 확인, 이전 결과 보존, solver 없는 재시작 조회도 통과했다. 시험 속도를 제품 성능 예산 합격으로 간주하지 않는다.

실제 native 시험은 S11/입력 임피던스를 공식 LumpedPort.CalcPort와 rel/abs 1e-10 범위에서 대조했고 종료 조건 미달을 실패로 처리했다. 공개 결과는 `computed_unvalidated`, `physics_validated=false`다. 에너지 종료 조건 충족은 정식 격자 수렴이나 실제 안테나의 정확도를 입증하지 않는다. fixture의 물성은 명시적 시험 가정이며 승인 IFA의 미정 물성을 확정하지 않았다.

초기 전체 회귀에서는 도파관 전용 capability 문자열을 기대하던 시험 1개가 실패해 사용자 PCB 지원 계약에 맞게 갱신했다. 첫 공개 API 취소 검증은 staging 전 guest 조회 시점의 시험 도구 오류를 수정했으며 해당 작업의 취소/슬롯 반환을 확인한 뒤 새 workspace로 다시 실행했다. 실패 로그와 이전 workspace도 보존했다. 당시 소스/GUI 바이너리/로그 hash와 제한은 `runtime_profiles/pcb-worker-wsl.json`에 기록했고 공개 API에서 캡처한 모든 제품 Python 소스 hash가 당시 검증 소스와 같음을 확인했다. 이 hash는 SolverRuntime과 동일하게 UTF-8 텍스트의 줄바꿈을 정규화한 바이트 기준이며 원본 CRLF 파일 바이트 hash와 구분한다.

## 접지 polygon, 패드, 비아와 IFA 급전 확장 (2026-11-11)

planar_region의 outer/holes, 원형/회전 사각 pad, 명시적 패드 참조를 가진 중공 through-PTH via를 도메인과 명령/저장/스냅샷/undo/redo에 추가했다. GUI 생성/선택/이동과 다각형 좌표 표, 비아 패드 다중 선택을 연결했다. 미정 드릴/도금 치수는 null/미정으로 보존한다. 자세한 의미와 한계는 [도체와 IFA 모델](copper_features.md)을 따른다.

CAD는 실제 층 두께와 polygon 빈 영역, 드릴 제거 및 중공 도금 barrel을 생성한다. EM은 polygon 구멍, sheet pad와 finite-conductivity volume via를 소비한다. 실제 IFA의 접지/급전선/패드/단락부를 분리된 원본 객체로 유지하며 같은 net인 급전도 허용한다. x/y/z 축 gap과 형상 연결, 실제 CSXCAD 재료 우선순위에 따른 Yee 전기 edge 연결을 검사한다. 최종 solver 계수와 물리 정확도의 독립 검증을 의미하지 않는다.

독립 검토에서 최대 64점/8holes의 매개변수 선택지 중복으로 DTO 상한을 넘는 문제, 극단 좌표의 mm 환산 실패로 편집이 막히는 문제, 비아가 먼저 검사될 때 잘못된 pad 층 참조가 일반 예외가 되는 문제를 재현하고 수정했다. 공통 coordinate_choices와 셀별 mm/m 표시, 참조 선행 검증을 회귀 시험에 추가했다. CAD와 EM의 알려진 tool bore 관계, 최외측 conductor 관통 조건도 일치시켰다.

| 최종 검증 | 통과 / 스킵 | 실행 시간 | 로컬 로그 |
| --- | --- | --- | --- |
| Windows 전체, 실제 GUI/CAD/WSL transport 포함 | 429 / 41 (470개 수집) | 326.108초 | .local/copper-windows-final-tests.log |
| Linux 서비스 전체 | 423 / 47 (470개 수집) | 237.283초 | .local/copper-linux-final-tests.log |
| 별도 native CAD와 원형/도체 투영 | 47 / 0 | 18.707초 | .local/copper-cad-final-tests.log |
| 실제 PCB/IFA/PTH/z-port 및 도파관, 계획/접촉 | 44 / 0 | 214.828초 | .local/pcb-ifa-pth-final-reviewed.log |
| 최종 좌표 대화상자/신규 도체 GUI | 2 / 0 | 42.817초 | .local/primitives-gui-tests.log |
| wxWidgets native CTest | 2 / 0 | 0.06초 | .local/primitives-gui-ctest.log |

실패/오류는 없다. 전체 회귀의 스킵은 OS 또는 별도 native 환경 전용 시험이다. native CAD/openEMS는 표의 별도 환경에서 실제 실행했고 Windows 전체에는 신규 GUI 시험도 포함했다. Release 빌드가 성공했으며 표의 시간은 병행 검증의 관찰값으로 성능 예산 판정에 사용하지 않는다.

`fixtures/ifa_feed_smoke.json`을 공개 명령으로 생성하고 WSL 준비/실행/결과 조회/후처리/실행 중 편집/취소/재시작을 검증했다. 40 x 60 mm의 접지 polygon/hole/pad/feed/short 모델, 2.4~2.4835 GHz 51점에서 native 격자점 639693개, 4495 step, 종료 에너지 감쇠 41.03 dB를 관측했다. 재후처리의 표본/raw 일치, 실제 취소 종료와 이전 결과 보존, solver 없는 재시작 조회를 모두 통과했다. 전체 도구 실행은 156.250초이며 `.local/ifa-worker-verification/report-final.json`과 해당 workspace에 보존했다.

별도 `fixtures/pth_worker_smoke.json`에서도 같은 공개 서비스 흐름과 실제 취소/복원을 통과했다(90.375초). 근거는 `.local/pth-worker-verification/report-final.json`이다. 작은 PTH 시험의 0.6 mm 완성 구멍/0.1 mm 도금/0.8 mm tool bore는 명시적 시험 가정이다. IFA의 0.93 mm 코어/35 um 동박/유전율 4.2/손실 0.018 역시 실행 가정으로만 사용하며 승인 초기 입력의 미정 물성/제작 조건은 확정하지 않았다.

공개 CAD `export.build -> job.status/cad.latest`에서 PTH/회전 패드와 IFA 접지/hole/pad의 두 사례도 통과했다(33.562초). 6개 파일 해시, snapshot/source mapping, 표시 mesh, 별도 프로세스의 STEP/B-rep 재입력 및 CAD 런타임 없는 재시작을 확인했다. PTH는 4 solids/2048 triangles, IFA는 2 solids/1032 triangles이며 실제 구멍과 두께를 유지했다. 근거는 `.local/cad-copper-public-b456a29e4b/report.json`이다. 재입력 kernel은 같은 OCCT이므로 독립 kernel 수용은 아니다. `result.open`은 현재 solver 전용이며 CAD 조회는 cad.latest를 사용한다.

소스/바이너리/로그/fixture 해시와 두 공개 해석의 runtime 일치를 `runtime_profiles/copper-ifa-worker-wsl.json`에 기록했다. 실행에서 캡처한 39개 Python 소스가 해당 검증 당시 소스와 일치함을 확인했다. 과거 `pcb-worker-wsl.json`은 당시 검증 이력으로 유지한다. 현재 결과는 computed_unvalidated다. SMA/실장/케이블/디임베딩, 정식 격자/경계 수렴, 얇은 비아 도금의 skin-depth 손실, NF2FF/이득/효율/측정 및 60/30 fps 수용은 후속이다.

## 단일 포트 IFA 수치 안정성 검증 (2026-11-11)

[IFA 수렴 연구](ifa_convergence.md)에 격자 0.5/0.45/0.4 mm, 경계 padding 90/96/102 mm와 에너지 종료 1e-5/1e-6을 독립 비교하는 CLI를 추가했다. 8개 비교 행이 6개 고유 계산을 공유하며, 전체 계획을 먼저 검증한다. 기판 내부의 세밀한 격자와 외부 graded air를 분리하고 PML8의 물리 두께를 48 mm로 고정했다. 기존 150만 격자점 상한은 유지했다. 실제 생성 격자에서 외곽/PML 시작면/셀 폭과 공통 비-PML 구간을 검사한다.

동일 스냅샷/물리 입력/주파수/실행 출처에서 복소 S11과 반사 최소점 bracket을 비교한다. 최초 2~3 GHz 연구는 6개 계산을 완료했지만 최소점이 대역 끝에 있어 전체 not_established로 보존했다. 별도 입력과 2.1 GHz 손실 기준을 명시한 1.6~2.6 GHz 연구의 6개 계산은 격자/경계/시간 종료 모두 초기 fixture 기준을 통과했다. 두 연구는 서로 다른 Gaussian/손실 기준을 사용하므로 하나의 비교 계열로 섞지 않았다.

두 번째 연구의 마지막 쌍에서 max abs(Delta S11_complex)는 격자 0.0041424481, 경계 0.0001808572, 시간 종료 0.0008264866이다. 반사 최소점은 1.920 GHz 표본, bracket [1.915, 1.925] GHz이며 보수적 이동 상한 0.5222%가 1% 이하다. 이는 2.4 GHz 정합 목표 달성이나 X=Im(Z)=0 공진/실측 정확도 검증이 아니다. fine 기본 run의 2.4 GHz S11은 약 -2.177 dB다. 모든 원래 결과는 computed_unvalidated를 유지한다.

실제 두 연구에서 재판정/재개 후 각각 봉인 파일 54개와 journal 작업 21개가 유지되고 추가 FDTD가 없음을 확인했다. 독립 검토에서 발견한 PML 위치/폭 변화 누락을 수정하고 기존 자료를 현재 판정기로 재평가했다. 새 검사는 두 연구의 수치와 판정 상태를 바꾸지 않았으며 과거 immutable 판정도 보존했다. native 실행 이후 변경된 제품 소스는 FDTD가 호출하지 않는 순수 비교기 convergence.py뿐이다. 나머지 캡처된 40개 소스는 그대로이며 실행 당시 identity와 최종 판정기 identity를 [검증 기록](../runtime_profiles/ifa-convergence-wsl.json)에 구분한다. 이전 runtime identity의 --resume은 현재 소스를 섞지 않고 거절하며 완료 자료의 --reassess-only는 지원한다.

JSON/CSV와 PNG/SVG 비교 그림을 생성하고 그림을 확인했다. 현재 수렴 연구는 CLI와 재사용 가능한 서비스 계층 비교기로 제공하며 GUI 다중 결과 비교 화면은 후속이다. 국부 특징 전체의 refinement, Richardson 차수, 곡선/PML 셀 수 민감도, NF2FF/전력/이득/효율, 실제 재료/제작/SMA/측정 및 60/30 fps 수용을 이 결과로 대신하지 않는다.

| 최종 검증 | 통과 / 스킵 | 실행 시간 | 로컬 로그 |
| --- | --- | --- | --- |
| Windows 전체, 실제 GUI/CAD/WSL transport 포함 | 472 / 42 (514개 수집) | 317.259초 | .local/ifa-windows-final-tests.log |
| Linux 서비스 전체 | 466 / 48 (514개 수집) | 191.089초 | .local/ifa-linux-final-tests.log |
| 실제 native PCB/IFA/PTH/z-port, 도파관과 graded mesh | 22 / 0 | 172.145초 | .local/ifa-native-final-tests.log |
| 비교기/PML 독립 조건/실행 도구 | 36 / 0 | 1.059초 | .local/ifa-comparison-final-tests.log |

최종 회귀는 실패/오류 없이 통과했다. 스킵은 OS 또는 별도 native 환경 전용 시험이다. 470개 이전 전체 시험에 비교기 24개, 실제 격자를 이용한 경계 독립 조건 5개, graded mesh 8개와 도구 7개를 추가했다. 5개 독립 조건 회귀의 응답은 합성 값이며 FDTD 정확도 증거로 세지 않는다. 이번 단계에서 GUI/CAD 구현 소스는 추가 변경하지 않았고, 같은 GUI 실행 파일을 전체 Windows 시험에서 사용했다. 실행 시간은 병행 검증 관찰값이며 성능 예산 판정이 아니다.

## 코드 구조와 상태 처리 정리 (2026-11-11)

집중된 주 창/서비스/worker를 [코드 구조](code_structure.md)의 책임별 모듈로 분리했다. GUI는 wxWidgets View + Presentation Model + Service Gateway를 사용한다. 진입점은 옵션과 창 생성만 수행하고, 화면 연결, 순수 표시/입력 정책, 요청 관리, 작업 조회, 해석 단계와 실제 GUI 시험 상태를 분리했다. Python 공개 API와 프로젝트 저장 schema는 유지한다.

| 기존 집중 파일 | 정리 전 | 정리 후 | 분리한 책임 |
| --- | --- | --- | --- |
| ui/wxwidgets/main.cpp | 3951줄 | 87줄 | 기능별 화면 연결, 비동기 상태, smoke 시나리오 |
| ui/wxwidgets/design_canvas.cpp | 1275줄 | 689줄 | scene/viewport/renderer/gesture |
| ui/wxwidgets/editor_panel.cpp | 896줄 | 620줄 | 폼 표시 정책과 좌표 대화상자 |
| application/projects.py | 599줄 | 407줄 | 계약/저장소/이력/파일 작업/receipt |
| application/solver_jobs.py | 697줄 | 366줄 | runtime/요청/산출물/조회 |
| application/cad_jobs.py | 393줄 | 271줄 | runtime과 산출물 |
| adapters/cad/native.py | 642줄 | 100줄 | 기하/고체 집계/STEP 교환/표시 |
| application/pcb_solver.py | 632줄 | 86줄 | 투영/도체 기하/격자/결과 검증 |

줄 수는 책임 이동의 관찰값이며 품질의 단독 판정 기준이 아니다. 서비스 원본을 GUI에서 다시 계산하지 않으며, 상태 처리는 위젯 없이 검사한다. 장면 ID 색인과 polygon 좌표, paint 단위 graphics context를 재사용하고 이력 복원의 중복 읽기/색인 생성을 줄였다. `.clang-format`과 `.editorconfig`로 Allman/공백 4칸/UTF-8 편집 규칙을 추가했다.

추가 검토에서 부분 시작 실패 시 thread/writer 회수, captured 문서의 정규 바이트 확인, 알 수 없는 자료 작업의 snapshot fallthrough를 보강했다. GUI 취소 의도와 전달 중 상태를 분리해 전송 실패 후 자동 단계 진행을 차단했고, 이전 job의 지연 응답과 요청 큐 포화가 새 작업/조회 상태를 손상하지 않도록 처리했다. 서버의 명시적 사용자 취소와 서비스 종료를 구분하며, 종료 미확인 작업의 예약과 기존 완료 결과는 보존한다.

CAD의 기존 25개 함수 AST와 PCB 5개 사례의 계획 정규 payload(plan_id 제외)가 정리 전과 같음을 확인했다. 형상/전자기 알고리즘을 변경하거나 과거 IFA 수치 안정성 기록을 새 소스로 재작성하지 않았다. 새 source identity로 과거 native 연구를 조용히 재개하지 않으며, 기존 완료 결과의 재판정 또는 새 workspace를 사용한다. 성능 예산 합격과 실측 정확도는 별도 검증이다.

| 최종 검증 | 통과 / 스킵 | 실행 시간 | 로컬 로그 |
| --- | --- | --- | --- |
| Windows 전체, 재빌드 GUI/CAD/WSL transport 포함 | 488 / 42 (530개 수집) | 323.585초 | .local/refactor-windows-final-tests.log |
| Linux 서비스 전체, 단독 실행 | 482 / 48 (530개 수집) | 156.181초 | .local/refactor-linux-final-tests.log |
| 실제 native CAD | 47 / 0 | 10.240초 | .local/refactor-cad-native-tests.log |
| 실제 native PCB/IFA/PTH/z-port/openEMS | 22 / 0 | 190.013초 | .local/refactor-pcb-native-tests.log |
| 최종 solver 종료/상태/수명 경계 | 31 / 0 | 63.300초 | .local/refactor-solver-lifecycle-final-tests.log |
| 같은 Linux 환경의 guest 독립 검사 | 12 / 0 | 19.254초 | .local/refactor-wsl-guest-service-final-tests.log |
| CTest: 표시 정책/상태/2D 기하/표시 mesh | 4 / 0 | 0.22초 | .local/refactor-ctest-final.log |

최종 표의 실행은 모두 실패/오류 없이 통과했다. Windows/Linux의 스킵은 OS 또는 별도 native 환경 전용 시험이다. 514개에서 작업 상태/부분 시작 실패/프로젝트 경계/종료 경계 회귀 16개를 추가했다. 실제 GUI 입력/2D/3D/CAD/해석/취소/재시작도 Windows 전체에 포함된다. 113개 제품 소스와 GUI 바이너리/로그 hash, 물리 투영 동일성 및 범위는 [구조 정리 검증 기록](../runtime_profiles/structure-refactor.json)에 보존했다. 새 2개 CTest는 wx 없이 표시 정책과 비동기 상태를 검증하며 기존 2개 검사도 유지한다.

중간 Linux 실행에서 기존 결과 검증의 내부 연결 함수 누락을 6개 subtest 오류로 확인해 호환 위임을 복원했다. 독립 검토가 찾은 서비스 종료 전이도 수정 후 전체 검증에 포함했다. 다른 병행 Linux 실행에서는 시간 제한 시험 한 번이 timeout 대신 cancelled를 반환했다. 원래 assertion에 원인이 없어 정확한 원인은 미확정이다. 운영 코드/제한값은 바꾸지 않았고 실패 시 전체 terminal 응답을 남기도록 시험 진단만 추가했다. 같은 timeout/lease 조건 12회와 같은 interpreter의 guest 전체 12개, 이후 Linux 전체 단독 실행은 통과했다. 최초 실패와 반복 진단 로그를 보존했으며 이 현상을 재현 또는 해결했다고 단정하지 않는다.

커밋 직전 신규 Python 파일 6개의 파일 끝 중복 빈 줄만 제거했다. 위치 정보를 포함한 AST가 원 시험 소스와 같음을 확인했고, 나머지 107개 제품 소스는 해시가 일치한다. 검증 기록은 실제 시험 당시 해시를 보존하고 빈 줄 정리 전후의 해시를 별도로 기록한다.

## 다음 구현

추가 자료 정리 (2026-11-11): PCB 유전율/적층 수집 자료 57,340행과 원문 1,682개를 감사하고 회사별 엑셀, 회사/소재 중심 파일명, ZIP 내부 검색과 검토 색인을 정리했다. 수치/미정 상태는 보존하고 파일명에 따른 출처 경로만 갱신했다. [PCB 재료 카탈로그 설계](pcb_material_catalog.md)는 사용자 직접 입력과 제조업체/소재 선택을 연결하는 후속 설계다. 자료 정리 당시에는 검색 UI, 원자적 적층 가져오기, 구조화 provenance 저장이 미구현이었다. 자료 정리만으로 기존 IFA의 가정 물성이나 해석 검증 상태가 바뀌지 않는다.

## PCB 카탈로그 첫 구현과 검증 (2026-11-11)

`Code/src/rfad/catalog`에 중립 ID/물성 조건, 원문 검증/오프라인 builder, 업체별 원시 자료 adapter, 요청 검증/읽기 저장소/서비스를 분리했다. CLI build/status/search/get과 JSON-RPC catalog.status/search/get을 연결했다. 자세한 사용법과 API는 [카탈로그 조회 계약](pcb_catalog_contract.md), 실행 근거와 코드 SHA-256은 [runtime 기록](../runtime_profiles/pcb-catalog.json)을 따른다.

| 실제 전체 자료 | 변환/검증 결과 |
| --- | --- |
| 관측 | 57,340행, 142개 원문 필드, 37개 분할. 원래 키/타입/값과 전역 정규 SHA-256 일치 |
| 출처/표기 그룹 | 출처 1,756개, 제품 표기 그룹 1,058개, 적층 라벨 그룹 2,941개 |
| 원시 적층 | 37개 JSON, template 3,399개, 구성 행 46,971개, 보조 증거 34개. 원문 전체 복원과 부모 연결 검증 오류 0 |
| 공개 검색 | 7개 개체의 전체 페이지를 누락/중복 없이 순회. 각 개체의 최대 원문을 조각으로 복원하고 응답 해시/offset/길이/타입 검사 |
| 위험 사례 | JLC 비양수 226행, PCBWay 그룹 합계 999행, 원문 충돌 49행, Dk/Df 주파수 차이 21행, 자성 1행, Wurth 필드 경계 167행을 그대로 검출 |
| 주파수 조건 | 2.4 GHz 및 2.45 GHz 점 관측 0행, 2.5 GHz 120행. 근접 주파수의 값을 자동 채택하지 않음 |

최종 DB는 `.local/pcb-catalog/catalog.sqlite`, 503,283,712 bytes(약 480 MiB)다. 전체 변환은 67.748초, 변환 프로세스 peak working set은 186.74 MiB였다. 조회 프로세스는 시작 측정 약 21.13 MiB, 시험 중 최대 26.20 MiB였으며 CAD/NumPy/openEMS 모듈을 import하지 않았다. 파일 크기 전체를 시작 메모리로 적재하지 않는다.

로컬 조회 측정은 조건 검색별 반복 20회의 중앙값 약 2.0~27.3 ms, 마지막 관측 페이지 약 6.8 ms, 전체 리터럴 부분 문자열 검색 약 99.3 ms였다. 부분 문자열 검색의 p95는 약 108.7 ms다. OS 디스크 캐시를 초기화하지 않았고 다른 회귀 시험이 병행된 단일 PC의 관측값이다. GUI 전체 메모리/시작 시간이나 60/30 fps 합격 근거가 아니다. 후속 GUI 검색은 기존 비동기 서비스 연결을 사용하고 검색 결과를 화면에 페이지 단위로 전달해야 한다.

전체 원문/검색 검증은 129.926초에 통과했다. 원시 JSON 독립 복원 검증과 추가 상세 응답 메타데이터 검증도 통과했다. 실행 로그와 보고서는 `.local/pcb-catalog`에 두고 runtime 기록에 파일 해시를 남겼다.

카탈로그 시험 51개가 모두 통과했다. API/CLI 5개, builder 15개, native 자료/독립 검증기 12개, 물성 DTO 5개, 조회 14개다. 손상된 카탈로그를 같은 서비스에 연결해도 기존 직접 입력 material.set, 저장, undo/redo, 스냅샷과 재시작이 유지되는 것을 확인했다. 원문이 없거나 자료 개정이 바뀐 경우, 입력/응답 상한, 원문 타입/큰 정수/Unicode, 실패 시 기존 DB 보존도 검사했다.

소스를 고정한 Windows 전체 시험은 581개 수집, 536개 통과, 45개 환경 조건 스킵으로 409.349초에 완료했다. 기존 GUI 실행 파일과 분리 CAD worker 통합을 포함한다. 서비스 환경에서 직접 CAD kernel을 import하는 시험, Linux process group 및 명시적으로 켜야 하는 WSL/openEMS 시험은 이번 실행에서 스킵했다. 실제 RF 계산이나 수렴 연구를 다시 수행한 것은 아니다.

초기 병행 시험은 소스 편집 중 CAD receipt 재전송 항목 1건이 실패했다. 해당 항목의 단독 재실행 및 이후 고정 소스 전체 시험은 통과했다. 최초 실패의 원인을 단정하지 않고 첫 로그도 보존했다.

원본 패키지 전체 검사에서는 manifest의 2,998개 파일과 자료 참조를 확인했고 내용 불일치는 보고되지 않았다. 다만 `Excel/PCB제작업체/~$PCBWay__PCB_적층.xlsx` 소유자 잠금 파일이 manifest 밖의 추가 파일로 검출되어 엄격한 패키지 검사 종료 코드는 1이었다. 이 임시 파일은 삭제하지 않았다. 카탈로그 변환은 manifest에 선언된 자료만 소비했고 전수 대조를 통과했다. 원본 패키지와 승인 01_Docs는 수정하지 않았다.

이후 구현한 프로젝트 소유 출처, 업체별 적층 초안과 원자 적용은 [PCB 선택 계약](pcb_selection_contract.md)을 따른다. wxWidgets 기판 설정의 직접 입력/소재/제조업체 선택과 단면/변경 미리보기의 후속 연결은 아래 GUI 검증 기록을 따른다. 검색 또는 저장 성공을 제작 가능이나 solver 준비 완료로 바꾸지 않는다.

### PCB 선택 출처와 적층 적용 검증

카탈로그 구현을 `e22f29b`로 커밋한 뒤 다음 세 범위를 추가했다. 선택한 자료/개정/조건/원문 해시와 사용자 채택값을 프로젝트에 보존하고, 제조업체별 적층을 명시적 미정값을 가진 초안으로 변환하며, 기존 층/패턴/비아/급전 참조를 검사한 뒤 하나의 명령으로 적용한다. `rfad.project/0.2`와 기존 직접 편집을 유지하며, 선택 계약만 버전이 있는 알려진 확장으로 저장한다.

출처 보존, 변환기, 후보 조립/참조 검토, API 조정과 도메인 명령은 별도 모듈이다. 현재 객체가 참조하는 이전 선택의 출처도 비재귀 history로 보존한다. 과거 출처를 포함한 전체 근거 12 KiB, 프로젝트 32 KiB와 응답 48 KiB 제한은 유지한다. JLC의 원본 필드 사본을 묶어 중복 metadata를 줄였으며 필요한 판단 근거와 원문 타입/포인터/해시는 보존한다.

| 검사 | 결과와 범위 |
| --- | --- |
| 새 기능 회귀 | 55개 통과, 28.874초. 출처/물성 12개, 적층 변환 16개, 도메인 17개, 실제 서비스 10개 |
| 전체 제조업체 초안 | 3,399개를 58.078초에 검사. 초안 생성 2,326개, 수동 구성 필요 250개, 명시적 크기 제한 823개, 예상 밖 오류 0개 |
| 초안 근거의 도메인 검증 | 반환된 2,576개 모두 raw hash/origin/안정 ID/12 KiB 검증 통과. DB 전후 SHA-256 동일 |
| 우선 층수 | JLCPCB 2층 22/22개, JLCPCB 4층 427/427개, PCBWay 4층 112/112개 초안 생성 성공. 저장/제작/해석 가능 수와 구분 |
| 대표 프로젝트 적용 | JLC2/JLC4/PCBWay4/OSH2의 적용, 저장, snapshot, undo/redo, 카탈로그 없는 재열기/영수증 재전송, CAD 입력 변환 통과. WE 유전체 부분집합은 수동 구성 차단 확인 |
| 실제 문서 예제 | 문서에서 추출한 CLI stdio 예제를 실행해 can_apply=true, solver_ready=false, 선택 저장을 확인 |

소스를 고정한 Windows 전체 회귀는 636개 수집, 591개 통과, 45개 환경 조건 스킵으로 432.941초에 완료했다. 기존 GUI 실행 파일과 분리 CAD worker 통합을 포함한다. 서비스 환경 안에서 직접 CAD kernel을 import하는 시험, Linux process group 및 명시적으로 활성화해야 하는 WSL/openEMS 시험은 스킵했다. 이번 변경으로 WSL의 실제 RF 계산이나 IFA 수렴 연구를 다시 실행한 것은 아니다. 전체 로그는 `.local/pcb-selection/full-tests.log`다.

미정 두께 이후 z는 미정으로 전파한다. 알려진 치수는 SI에서 누적하여 mm 왕복 환산이 만드는 가짜 층 중첩을 방지한다. 기존 층을 명시적으로 대응하지 않아 패턴/패드/비아 참조가 끊기면 적용을 차단한다. 층의 z/두께가 바뀌어 영향을 받는 기존 급전 상자는 명시적 좌표와 이유를 요구하며, 알려진 sheet 접면과 다른 z는 차단한다. 좌표가 미정이면 저장 가능 여부와 후속 해석 준비 여부를 구분한다.

대표 사례의 빈 두께에는 검증 도구 전용 가정을 명시했다. 해당 수치는 실제 제작 기준이나 IFA 물성이 아니다. CAD 입력 변환/기존 해석 계획 호환 시험은 이 카탈로그 재료의 새 STEP 왕복 또는 FDTD 계산을 뜻하지 않는다. 원문 00_REF, 승인 01_Docs와 기존 IFA fixture는 변경하지 않았다.

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_stackup_drafts.py --database .local/pcb-catalog/catalog.sqlite --report .local/pcb-selection/stackup-coverage-new.json
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_selection.py --database .local/pcb-catalog/catalog.sqlite --report .local/pcb-selection/representative-new.json
```

두 도구는 기존 보고서를 덮어쓰지 않는다. 최종 보고서와 소스 해시는 `runtime_profiles/pcb-selection.json`에 기록한다. 이 서비스 검증 뒤 GUI 제조업체 선택과 층 단면/변경 미리보기를 연결했다. 선택한 실제 재료의 CAD/solver 실행 검증은 후속이다.

위 PCB 선택 API 구현 시점 이후의 실행/검증은 아래 날짜별 기록을 따른다. 현재 개발 순서와 단계별 완료 조건은 [개발 완료 계획](completion_plan.md), 재부팅 직후 명령은 [재부팅 후 개발 재개](reboot_resume.md)를 따른다. 이전 후속 목록을 현행 계획으로 사용하지 않는다.

GUI와 자동화는 같은 서비스를 공유한다. 이후 추가한 MCP stdio와 특정 EDA의 의미 mapping/상호 운용 수용은 구분한다. 물성은 사용자 입력이며 임의 FR4 대표값으로 대체하지 않는다. 초기 IFA 1 mm 완성 두께에서 구리 두께를 뺀 잔여값을 실제 코어 두께 확정값으로 취급하지 않는다.

## wxWidgets PCB 검색과 선택 화면 (2026-11-11)

선행 API와 출처/적층 적용 작업을 `9030825`로 커밋하고 `origin/main`에 푸시한 뒤 GUI를 연결했다. `설계 > 기판 설정 / 제조업체 자료`와 왼쪽 버튼으로 열며, 검색/층 연결/재료 물성/급전 좌표/변경 검토의 다섯 탭을 제공한다. 기존 직접 입력과 저장/이력은 유지한다. 자세한 조작은 [PCB 선택 화면](pcb_selection_gui.md)을 따른다.

View, 위젯 없는 PcbSelectionModel, StudioFrame 서비스 연결을 분리했다. 검색/초안/미리보기의 늦은 응답을 버리고 미커밋 격자 입력도 미리보기를 무효화한다. 적용 직전에 격자 편집을 확정하여 검토한 사양과 다시 비교한다. 서로 다른 카탈로그 개정의 출처를 혼합하지 않으며 적용 결과가 불명확하면 자동 재시도하지 않는다. 대화상자가 열린 채 부모 종료 요청을 받은 경우에도 스택 소유 뷰가 먼저 반환된 뒤 부모를 종료한다.

`pcb.selection.context`는 서비스가 해석한 mm 치수, 미정값, 기존 ID와 매개변수 연결 여부만 읽기 전용으로 반환한다. GUI는 원래 층을 유지할 때 숫자 표시값을 원본에 다시 쓰지 않는다. 직접 층 편집으로 매개변수 결합을 대체할 때는 명시적 이유를 요구한다. 포트 좌표가 같아도 확인 이유를 적어 변경된 접면을 검토할 수 있다.

실제 카탈로그를 연결한 화면에서 JLCPCB의 해시 위주 표기가 식별하기 어렵다는 점을 확인했다. 검색/상세에 기존 적층 표기의 이름, 층수와 공칭 두께를 한 번의 LEFT JOIN으로 추가하고 공개 이름 검색을 지원했다. DB 재구축이나 개정 변경은 없다. 실제 3,399개를 25개씩 136페이지로 검사하여 누락/중복 없이 원래 ID 순서를 유지했다. 연결 표기 2,939개와 미연결 460개를 보존했고 최대 응답은 22,133 bytes, 조회 전체 시간은 2.524초였다. 이는 페이지 기능 검증이며 일반 편집 fps 예산의 측정이 아니다.

실제 전체 DB의 OSH Park 2층 관측을 GUI에서 검색/선택하고 Dk 관측 연결, 이유가 있는 Df/전도도 직접 입력, 재료와 층 연결, 단면 검토, 적용과 undo/redo, 저장/재열기/출처 보존을 확인했다. 이때 Df/전도도는 명시적인 UI 검증용 가정이며 실제 제작 또는 RF 검증 값으로 채택하지 않는다. 별도 작은 DB 시험은 카탈로그 없음과 0.4초 응답 지연도 포함한다. 원형 외형과 기존 패턴 UUID/층 참조를 유지했다.

실제 창에서 주 화면 진입, 업체 목록, 공개 적층명, OSH Park 관측과 층 초안, 미정 동박을 포함한 단면, 재료 폼 배치를 확인했다. 단면은 두께 비례가 아닌 식별용 도식이고 미정값 이후의 z를 추측하지 않는다. 기판 외형이 없는 상태의 층 적용 차단도 확인하고 기존 계약 문서의 모호한 설명을 수정했다. 현재 디스플레이의 시각 확인이며 전체 DPI/IME/접근성 및 60/30 fps 수용 시험을 대신하지 않는다.

| 검증 | 결과 | 실행 시간 |
| --- | --- | --- |
| 고정 Python 소스의 Windows 전체 | 647개 수집, 601개 통과, 46개 환경 조건 스킵 | 492.940초 |
| 종료/진단 보완 후 최종 GUI 전체 | 16개 수집, 15개 통과, 명시적 WSL 실행 1개 스킵 | 129.882초 |
| native CTest | 선택 모델, 표시 정책, 비동기 상태, 2D 기하, 표시 mesh의 5개 모두 통과 | 0.27초 |
| 실제 전체 DB의 GUI 선택 흐름 | 검색/재료/층 연결/검토/이력/재열기 13개 확인, DB 전후 SHA-256 동일 | 7.813초 |
| 공개 적층명 조회 회귀 | 작은 fixture와 실제 DB 포함 19개 통과 | 4.440초 |

전체 회귀 뒤 추가한 C++ 종료 보호와 세부 진단 표시를 재빌드하여 GUI 전체를 다시 검증했다. 최종 PCB GUI 시험에는 적용 중 부모 닫기 보류, 조회 중 부모 닫기 후 모달 반환/서비스 thread 회수/timer 종료 검사가 포함된다. 전체 회귀 때와 최종 GUI의 실행 파일 해시는 별도로 기록했고 Python 제품 소스 94개는 고정 이후 동일함을 확인했다. 수정한 C++ 27개 파일의 clang-format 검사와 git diff 공백 검사도 통과했다.

로그는 `.local/pcb-selection-gui`에 있으며 소스/실행 파일/로그 해시, 원자료 불변과 시각 확인 범위는 [GUI 검증 기록](../runtime_profiles/pcb-selection-gui.json)에 보존했다. 전체 시험의 스킵은 서비스 환경 안의 CAD kernel, Linux process group, 별도 활성화 WSL/native RF 및 실제 DB 지정 시험이다. 실제 DB 지정 조회는 별도 19개 실행으로 확인했다. 이번에 새 RF 계산, IFA 수렴, 제조/측정 대조와 성능 예산 검증을 수행한 것은 아니다. 원문 자료와 승인 설계 및 기존 IFA fixture는 변경하지 않았다.

## 카탈로그 PCB의 CAD/해석 통합 검증 (2026-11-11)

저장된 선택 PCB를 편집하지 않고 같은 snapshot의 형상/STEP/해석과 결과 재열기를 검증하는 도구를 기능별로 추가했다. API와 저장 schema, wxWidgets 및 제품 worker 코드는 유지한다. 입력 검사, CAD/STEP, 실제 openEMS, 독립 후처리와 카탈로그/worker 없는 재시작은 [통합 검증 문서](catalog_pcb_integration.md)를 따른다.

사용자가 업체 선택을 위임한 JLCPCB에서 순수 코어 두께가 명확한 JLC0206 계산기 후보를 선택했다. 코어 0.500 mm, 공개 2층 1 oz 외층 명목 사양 각 0.035 mm로 모델 합계는 0.570 mm다. 공칭 0.600 mm와 원문 코어 동박 0.030 mm는 보존하고 차이를 자동 배분하지 않았다. 이 계산기 후보의 NP-155F 표기를 현재 주문 재질 보증으로 간주하지 않는다. 실제 CAD 작업 두 개와 STEP/BREP 재입력, mesh/출처/hash 및 재열기를 통과했다. Dk 4.48만 원문에서 채택했고 Df/전도도/재료 및 포트 대역의 미정 9개 입력을 보존하여 실제 JLC EM은 `needs_inputs`로 차단했다.

별도 양성 대조군은 기존 `ifa_feed_smoke.json`의 명시적 물성과 치수를 합성 카탈로그에 보존한다. 두 동박층을 정의한 같은 snapshot으로 실제 CAD/STEP, WSL openEMS와 원시 자료 재후처리, 결과 재열기를 통과했다. 639,693 cells와 4,495 steps에서 에너지 종료 조건을 충족했고 주파수 표본 51개가 재후처리와 일치했다. 두 사례 모두 하부 동박층에 자동 접지면을 만들지 않는다. 제조사 재료나 안테나 정확도 검증으로 표시하지 않으며 `computed_unvalidated`, `physics_validated=false`를 유지한다.

| 검증 | 결과 | 실행 시간 |
| --- | --- | --- |
| 카탈로그/선택/CAD 투영/PCB solver/새 도구 관련 회귀 | 161개 수집, 157개 통과, 4개 조건부 스킵, 실패 0 | 67.453초 |
| 격리 CAD 지정 새 시험 | 3개 통과. 2개 입력/투영 검사와 1개 실제 CAD/STEP/재열기 | 22.579초 |
| 기존 원형 fixture의 실제 solver 양성 대조군 | 1개 통과, 31개 표본, 재후처리/재열기 | 43.968초 |
| 2층 IFA의 실제 CAD와 solver 전체 경로 | 1개 통과, 51개 표본, 같은 snapshot과 원본 불변 | 136.123초 |
| 실제 JLC 후보의 CAD 및 RF 누락 차단 | CAD 작업 2개 통과, 실제 EM 미실행, 재열기 통과 | 17.359초 |

회귀의 스킵은 별도 실제 DB 조회 1개와 위의 native 사례 3개다. 기존 전체 GUI 시험 결과를 이번 변경의 전체 회귀로 재표시하지 않았다. 보고서 원자 게시와 inspect의 native 런타임 배제는 최종 회귀 및 실제 JLC inspect CLI(입력 부족 종료 코드 3)로 확인했다. 원본 프로젝트와 자료 DB, fixture를 변경하지 않았으며 승인 문서도 유지했다. 보고서/소스 해시와 범위는 [검증 기록](../runtime_profiles/catalog-pcb-integration.json)에 있다.

## JLC RO4350B 탐색 모델과 전체 경로 검증 (2026-11-11)

제조사 자료 조사 후 JLCPCB 고주파 서비스의 RO4350B 30 mil 코어를 후속 후보로 기록했다. 사용자가 출처와 근사임을 구분하는 탐색 모델을 허용하여, 원본 카탈로그의 관측과 실제 납품 물성이 미정인 재료 2개를 보존한 새 프로젝트를 만들었다. [제작 후보와 출처](jlc_manufacturing_selection.md), [손실 모델의 의미](material_loss_models.md), [최종 runtime 기록](../runtime_profiles/jlc-ro4350b-exploratory.json)을 함께 확인한다. 위 JLC0206의 `needs_inputs`와 과거 CAD 검증 기록은 이 새 모델로 대체하지 않는다.

탐색 유전체는 Design Dk 3.66의 원문 8~40 GHz 조건과 Df 0.0031의 2.5 GHz/23 C/Z 방향 조건을 각각 보존하고 2.400~2.4835 GHz에 적용하는 등방성 상수 근사다. `isotropic_constant_total_tan_delta`를 명시적으로 선택하여 독립 유전체 전도도는 미정/비소비로 유지한다. 기존 `isotropic_constant`의 합산 의미는 바꾸지 않았다. Df에서 환산한 상수 kappa는 대역 중심에서 입력 Df와 일치하며 광대역 상수 Df 모델이 아니다.

도체는 JLC 측정값과 분리한 `100% IACS / 20 C` 기준 구리 58 MS/m를 사용한다. 코어 0.762 mm와 양면 동박 각 0.035 mm의 명목 합계는 0.832 mm이며 제작 후보 0.9 mm와의 차이를 배분하지 않았다. 솔더마스크, ENIG의 Ni/Au 층, 거칠기, 이방성/분산, SMA/케이블과 제작 공차를 생략한 모델이다. 실제 납품용 미정 재료 2개는 적층/형상에서 소비하지 않으며 해당 물성과 적용 대역의 null을 유지했다.

같은 불변 snapshot의 CAD 형상, AP242 STEP/BREP 재입력, 표시 mesh와 출처를 확인하고 WSL2 openEMS를 실제 실행했다. native 격자점 639,693개, 4,805 steps에서 에너지 감소 42.08 dB로 요청 종료 조건을 충족했고, 51개 주파수 표본의 독립 재후처리와 결과 재열기 및 원본 불변 검사를 통과했다. 전체 통합 경과 시간은 136.734초다. 하부 동박층 정의만으로 자동 접지면을 추가하지 않았으며, CAD 왕복은 같은 Open CASCADE kernel의 확인이다.

| 최종 검증 | 결과 | 실행 시간 |
| --- | --- | --- |
| Windows 서비스 환경 전체 회귀 | 685개 수집, 618개 통과, 67개 조건부 스킵, 실패/오류 0 | 364.510초 |
| wxWidgets PCB 선택 회귀 | 3개 통과, 실패/오류 0 | 33.525초 |
| 총 Df 모델 native 양성 대조군 | 1개 통과, 실제 CAD/openEMS/재후처리/재열기 | 169.218초 |
| RO4350B 탐색 프로젝트 전체 통합 | `passed`, 같은 snapshot의 CAD/STEP/openEMS/재후처리/재열기와 원본 불변 | 136.734초 |

전체 회귀의 스킵을 native 실행 통과로 간주하지 않는다. GUI 선택 및 총 Df native 대조군은 위의 별도 실행이며, 과거 GUI 전체/CTest/다른 OS 결과를 이번 소스의 새 전체 검증으로 표시하지 않는다. 로그는 `.local/manufacturing-source-review/full-tests.log`, `gui-selection-tests.log`, `native-total-loss-warm.log`이고 실제 선택/통합 보고서는 같은 폴더의 `ro4350b-input.json`, `ro4350b-integration.json`이다.

총 Df native 대조군의 첫 준비 시도는 WSL cold boot 과정에서 10초 start control timeout으로 실패했다. 최초 로그 `native-total-loss.log`를 보존했고, WSL 예열과 제한 시간이 있는 keepalive 이후 별도 실행이 통과했다. 이 조치는 이번 실행 환경을 준비한 것이며 자동 시작/복구 문제가 해결됐다는 의미가 아니다. 재부팅 직후 자동 준비와 제한 시간 처리 보강은 다음 작업으로 남긴다.

RO4350B 결과의 `status=computed_unvalidated`, `physics_validated=false`를 유지한다. `converged=true`는 시간영역 에너지 종료 조건 충족만 뜻한다. 이 새 재료/기하의 격자/경계 수렴, 제조 공차와 실측 대조는 아직 검증하지 않았다. 실제 제작 적층/물성/주문 조합도 미확정이며 기존 승인 IFA 및 원문 자료를 이번 탐색 수치로 덮어쓰지 않았다.

## 제조업체 적층과 Dk/Df 함께 제안 (2026-11-11)

`catalog.stackup_suggestions`에서 같은 제조업체 적층의 원문 층과 물성 관측을 정확히 대응하고, wxWidgets에서 두께와 Dk/Df를 함께 검토하도록 연결했다. JLCPCB는 공개 template/구성행/재질/파일/위치/Dk의 일치, PCBWay는 적층/원문 table 행/재질/Dk의 일치, OSH Park은 명시적으로 지원하는 2층 관측 자체를 사용한다. 업체명이나 가까운 주파수만으로 다른 물성을 연결하지 않는다.

제안은 공개값, 미정, 후보 충돌, 근사 입력 필요와 자동 제안 미지원을 구분한다. 원문 범위/한정자의 참고 수치와 적용값을 분리하고, 근사값은 사용자가 직접 입력해야 한다. 미정 Df, 독립 전도도와 모델 적용 대역은 자동 보완하지 않는다. 선택 제안 사용은 새 재료와 미연결 유전체 층의 폼을 준비하며, 프로젝트 변경은 기존 미리보기/원자 적용으로 수행한다. 기존 직접 입력, 수동 두께와 이미 연결된 재료를 보존한다. 상세한 API와 화면은 [선택 계약](pcb_selection_contract.md), [GUI 사용법](pcb_selection_gui.md)을 따른다.

전체 SQLite의 57340개 관측을 포함한 자료에서 모든 native template 3399개와 OSH Park 관측 10개, 총 3409개 후보를 검사했다. 2586개 후보의 5146개 페이지에서 층 순서/누락/중복, 응답 상한과 미정 보존을 확인했다. 이 중 WE 175개와 OSH 관측 9개는 지원하는 전체 물리층이 없어 빈 층 목록과 설명을 반환하며, 응답 성공을 사용 가능한 완성 기판으로 집계하지 않는다. 나머지 823개는 기존 12 KiB 초안 근거 상한으로 거절되었고, 동일 입력의 기존 `catalog.stackup_draft`에서도 같은 제한을 재현했다. 새 제안 API에서만 발생하는 오류는 0개였다. 전체 순회는 73.141초이며 DB 해시는 변경 전후 일치했다.

초기 전체 자료 검토에서 발견한 새 48 KiB 응답 초과 614건은 물성 제안의 페이지 분할로 해결했다. 페이지는 최대 8행이며 실제 바이트 크기에 따라 더 적게 반환할 수 있다. 원본 두께/물성/조건을 잘라서 예산을 우회하지 않는다. 변경 전 기록 `all-catalog-01.json`과 최종 순회 `all-catalog-02.json`은 `.local/stackup-suggestions/`에 보존했다. 후속으로 제거한 사용하지 않는 `previous_offset` 표시는 값/층/페이지 순회 판정을 바꾸지 않는다. GUI는 실제 방문 오프셋으로 이전 페이지를 처리한다.

실제 대표 JLC 2층과 OSH Park 2층의 제안을 기존 공개 API로 적용하고 undo/redo, 저장/snapshot, 카탈로그가 없는 재열기를 통과했다. Df/전도도/모델 대역은 null로 유지했으며 새 소재를 해석 준비 완료로 표시하지 않았다. 문서 크기는 각각 18077/13045 bytes다. 대표 JLC 4층과 PCBWay 4층의 모든 유전체 제안을 한 번에 채택하면 원문 사본 합계가 기존 12 KiB를 초과하여 적용이 거절된다. 제안 조회 성공과 전체 재료 적용 가능 범위를 구분한다. 네 대표 사례 검사는 6.437초였고 `representative-apply.json`에 기록했다. 12 KiB 근거 및 32 KiB 프로젝트 상한 확대는 이번 변경에 포함하지 않는다.

자료에 제공된 JLCPCB/PCBWay의 대응 Df는 모두 미정이었다. 제안한 Dk는 출처의 공개 계획값이며 실제 제작 기판의 측정값이나 해석 대역의 적합성을 보증하지 않는다. 이번 검증은 선택/저장/GUI 경로이며 새로운 CAD/openEMS 실행, 제조 검증 또는 RF 정확도 검증으로 간주하지 않는다. 기존 RO4350B 탐색 계산과 승인 원문은 그대로 보존한다.

| 이번 변경의 검증 | 결과 | 시간 |
| --- | --- | --- |
| Windows 서비스 전체 회귀 | 705개 수집, 638개 통과, 67개 조건부 스킵, 실패/오류 0 | 285.222초 |
| 최종 제안 API/저장 집중 시험 | 13개 통과. 원문 손실 상한의 참고 표시와 실제 미정 입력 분리 포함 | 11.140초 |
| 최종 wxWidgets 선택 프로세스 시험 | 3개 통과. 제안 수용/페이지/직접 입력 보존과 저장/이력/재열기 | 23.429초 |
| 최종 CTest | 6개 통과, 실패 0 | 0.32초 |
| 전체 자료의 모든 제안 페이지 | 3409개 후보, 5146개 페이지. 응답 2586개, 기존 초안 근거 예산 거절 823개, 새 오류 0 | 73.141초 |
| 실제 대표 선택 적용 | JLC 2층/OSH 2층 적용과 재열기 통과. JLC 4층/PCBWay 4층 전체 물성의 기존 근거 예산 제한 확인 | 6.437초 |

전체 회귀 로그는 `.local/stackup-suggestions/windows-regression.log`, 최종 제안 집중 시험은 `focused-tests.log`다. Release 빌드는 성공했고 `gui-build-final.log`에 기록했다. 최종 GUI 및 CTest 로그는 같은 디렉터리의 `gui-tests-final.log`, `ctest.log`다. 전체 자료와 대표 적용 보고서는 `all-catalog-02.json`, `representative-apply.json`이다. 최종 소스/보고서 해시와 GUI 검사 근거는 [적층 제안 검증 기록](../runtime_profiles/stackup-suggestions.json)을 따른다. 자동 GUI 시험의 통과를 모든 화면 크기/DPI에 대한 수동 시각 수용으로 확대하지 않는다. 이전 RO4350B native 실행을 이번 변경의 새로운 해석 시험으로 표시하지 않는다.

별도 테스트 workspace에서 실제 JLC 6층/15행의 제안 조회, 이전/다음 페이지, 공개 두께/Dk와 미정 Df의 구분, 출처 상세 및 제안 수용 후 재료 폼을 시각 확인했다. 주 창 1348 x 854, 대화 상자 1128 x 794에서 표와 하단 조작부의 겹침은 없었으며 긴 상세는 스크롤로 표시했다. 프로젝트에는 적용하지 않고 정상 종료했다. 다른 화면 크기/DPI 및 GUI 성능은 이번 시각 확인 범위가 아니다.


## 용량 개선과 후속 1~9번 진행 (2026-11-11)

기존 823개 적층 조회 거절을 포함한 전체 3409개 후보를 최종 소스로 재검사해 제한/오류 0을 확인했다. JLC 4층/PCBWay 4층의 모든 유전체 제안을 공개 RPC로 적용하고 출처/미정/저장/snapshot/undo/redo/카탈로그 없는 재열기를 통과했다. 프로젝트 512 KiB, 고유 근거 128 KiB와 공유 근거 선택 0.2를 도입했고 기존 0.1 및 직접 입력을 유지했다. 원자 저장 경로와 기존 schema의 읽기 해시는 바꾸지 않는다.

이어서 WSL 준비/취소, RO4350B 출처 기반 연구와 GUI 보고서 비교, 다이폴 NF2FF 참조, renderer 계측과 내부 묶음 생성, MCP stdio adapter를 구현/실행했다. 전체 시험 716개 중 649개 통과/67개 조건부 스킵(382.544초), GUI 13개 통과/3개 스킵(168.346초), CTest 6개 통과(0.39초), 실제 WSL transport 2개 통과(19.306초)다. 마지막 수렴 보고서의 표시 보완은 GUI 전체 시험 이후이며 실제 최종 창으로 별도 시각 확인했다.

RO4350B 연구는 8개 사례/6개 고유 native 계산을 1363.984초에 마쳤다. 마지막 복소 S 변화는 세 축 모두 0.02 이내지만 내부 공진을 찾지 못해 전체 수렴은 미확립이다. S11은 목표 대역에서 약 -3.426~-2.400 dB로 -10 dB 정합 목표에 미달한다. 새 결과를 기존 fixture 수렴 또는 제조/실측 합격으로 표시하지 않는다.

NF2FF 참조의 Dmax 1.65863과 방사 효율 0.999807 및 최대 패턴 차이 0.01333을 확인했다. native 실행 후 발생한 후처리 오류를 보완하고 해시가 보존된 원시 파일만 재사용했으며 추가 FDTD로 집계하지 않았다. 사용자 PCB의 방사 연결은 여전히 후속이다. renderer의 최종 p95는 200개 2.951 ms/3000개 37.597 ms이며 대형 30 fps 예산은 미충족이다. 합성 렌더 비용만으로 실제 GUI FPS나 전체 메모리를 판정하지 않는다.

자세한 실행 명령과 남은 수용 범위는 [후속 검증 문서](capacity_and_followup.md), 소스/보고서 해시는 [실행 기록](../runtime_profiles/capacity-and-followup.json)을 따른다. 기존 823개 제한을 기록한 과거 절과 원래 실패 로그는 당시 근거로 보존한다. 미정 제작/측정 자료, 정합 설계, 추가 GUI 편집/성능 및 특정 EDA 연계가 남아 있으므로 R1 또는 1~9번 전체 수용 완료를 선언하지 않는다.
