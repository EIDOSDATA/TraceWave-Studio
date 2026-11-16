# TraceWave Studio 문서 안내

작성/정비일: 2026-11-16 KST. 제품 개발 문서를 목적별로 분류한다. 승인 기준선은 RFAD-D0-3.4이며, 아래 현재 문서의 갱신이 원래 승인 범위나 과거 검증 결과를 다시 쓰지 않는다.

## 목적별 문서

| 찾는 내용 | 폴더 / 시작 문서 | 역할 |
| --- | --- | --- |
| 화면설계서 / UI / UX | [screen_design](screen_design/README.md) | 화면 목록/기능/입출력/이벤트/전환/예외, DrawIO/PNG/SVG, 이름/선택/접근성 |
| 기능별 계약 | [features](features/README.md) | 프로젝트, 설계/편집, 재료, 해석/결과, 출력의 실제 공개 동작과 미지원 범위 |
| 시스템 명세 | [specifications](specifications/README.md) | 원본/데이터/버전/API/오류/공통 상태 및 구현 전 결정 |
| 구조와 책임 | [architecture](architecture/README.md) | GUI/View/표시 상태/service/worker의 책임과 수명 |
| 분석 / 연구 자료 | [research](research/README.md) | 문헌/제조 후보의 적용 판단, RF 참조/수렴/손실과 당시 근거 |
| 검증 / 요구 추적 | [verification](verification/README.md) | 승인 FN/AC/VT와 코드/시험 연결. 실행 기록 및 미확립 상태 |
| 환경 / 운영 | [operations](operations/README.md) | Windows/WSL/Python 설치, 실행과 재개. 과거 설치 기록과 현재 지침 구분 |
| 개발 계획 / 이력 | [planning](planning/README.md) | 기존 1~13번 순서, 현재 위치, 시점별 구현/검증 이력 |
| 최초 제안 / 변경 이력 | [archive](archive/README.md) | 현행 계약으로 대체된 제안. 현재 API 명세로 사용하지 않음 |
| 문서 전수 목록 | [catalog](catalog/README.md) | 승인/개발/원문/추출/검증 파일 분류, 이전 경로, 검토 수준 |
| 이번 검토 / 열린 설계 | [review](review/README.md) | 잘못된 현재형 교정, 중복 정리, 보강 내용과 실제로 남은 증거 의존성 |

## 승인 설계와 외부 근거

[01_Docs 안내](../../01_Docs/00_RFAD_전체_안내.md)는 승인 설계 26개의 원래 번호/ID/내용/해시를 보존한다. [분류 목록](catalog/approved_design.md)에서 화면/기능/시스템/수학/검증별로 접근할 수 있다. 문서의 당시 `착수 전` 표기를 현재 개발 상태로 읽지 않는다.

[00_REF](../../00_REF/)는 외부 원문, 수집 목록, 추출값, 검토 기록의 증거 저장소다. 원문과 추출본은 목적이 다르므로 내용이 비슷하다는 이유로 삭제하지 않는다. 현재 기능에서 채택한 근거와 실제 납품/제작/측정의 확정은 별개다. [참고 자료 분류](catalog/reference_materials.md)를 따른다.

과거 [runtime_profiles](../runtime_profiles/)는 당시 환경/소스/시험을 식별한다. 현재 문서 위치가 바뀌어도 기록 안의 옛 경로/소스 해시는 그대로 보존하며 [이전 경로 대응](catalog/path_map.json)과 당시 Git 개정으로 찾는다. 자동 생성된 [audit](audit/function_matrix.md)는 현재 코드와의 연결 색인이며 전체 수용 합격표가 아니다.

## 읽는 순서와 관리

처음 참여할 때에는 [완료 계획](planning/completion_plan.md), [현재 상태](planning/development_status.md), [공통 계약](specifications/shared_contracts.md), [구조](architecture/code_structure.md), [화면설계서](screen_design/README.md)와 담당 기능 계약을 읽는다. 남은 기능의 설계 결정을 찾을 때에는 [R1 설계 준비표](specifications/r1_design_readiness.md)를 함께 본다.

문서의 단일 소유 위치, 상태 표기, 삭제/보존과 기능 개발 시 갱신 규칙은 [문서 관리 정책](documentation_policy.md)을 따른다. 제품 구현과 문서 검토, 수치/물리/실측 수용을 같은 완료 상태로 합치지 않는다.
