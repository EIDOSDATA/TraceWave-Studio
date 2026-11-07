# 문서 타당성 검토와 사용자 승인

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

## 1. 검토 결론과 범위

PCB 안테나의 단일 의미 모델에서 CAD, 제조 출력, solver 입력과 결과를 파생하는 전체 방향은 설계 기준으로 유지할 수 있다. 다만 이전 문서의 현재 자료 상태, 작업/API 경계, 검증 추적, GUI 선정과 성능 계약에는 수정이 필요했다. 이번 개정은 이를 본문에 반영한 개발 전 설계안이다.

실제 대상은 01_Docs의 기존 Markdown 24개와 루트 README다. 00~22를 수정하고, 원본 B인 23은 원문 보존을 위해 그대로 두었다. GUI/성능 24와 이 검토/승인 25를 추가했다. 현재 폴더에 원본 A JSON과 과거 review/src/tests/실행 기록은 없다. 기존 보존된 요구의 의미와 ID는 유지하되 원본 A 파일의 현재 바이트 보존 여부를 확인한 것으로 표시하지 않는다.

이번 작업은 문서 읽기, 구조/ID/링크 대조, 현재 추출 자료의 배열/행 수 확인, 공식 기술 문서와 수식 정의 비교다. 제품 코드, 의존성 설치, GUI prototype, CAD export, native EM 또는 실측 검증을 수행한 작업이 아니다. 문서의 설계 상태와 시험 실행 상태를 분리한다.

## 2. 발견 사항과 반영 내용

| ID | 발견한 문제 | 수정 및 영향 문서 | 상태 |
| --- | --- | --- | --- |
| DOC-001 | 없는 review/실행 기록과 A JSON을 현재 증거처럼 인용 | 00/02/16/18/README의 자료 실재와 역사 기록 구분, 깨진 안내 링크 교정 | 문서 수정 |
| DOC-002 | 문서 검토 후 바로 구현하라는 인계 문장이 사용자 계획과 충돌 | D0 사용자 검토 및 개발 착수 지시를 R0 선행조건으로 명시. 01/15/16 | 문서 수정 |
| DOC-003 | Avalonia 우선 결정이 메모리 우선 기준을 설명하지 못함 | wxWidgets 우선 평가 가설, Avalonia 비교, Qt 제외. 최종 선정은 동등 측정. 01/05/24 | 문서 수정, 성능 미측정 |
| DOC-004 | 성능 목표가 200 ms 한 숫자로만 제시됨 | 시작/입력/frame/ACK/메모리/CPU/수명별 fixture와 예산, 전체 worker/WSL/GPU 측정. 04/07/24 | 설계 명시 |
| DOC-005 | UI/서비스/worker 간 데이터 복제와 cache 수명 상한이 부족 | 지연 import, virtual row, ROI, LOD, bounded IPC/log/cache, worker idle 종료. 05/07/08 | 설계 명시 |
| DOC-006 | 준비가 끝나기 전 AnalysisPlan과 실제 PreparedPlan 계약이 혼재 | em_prepare 접수와 완료 산출물, em_analysis의 PreparedPlan 필수화. 04/06/08/10/11 | 문서 수정 |
| DOC-007 | 결과 조회 API가 정규화 생성까지 맡고 긴 데이터 작업 kind가 없음 | result.open 조회 전용, postprocess_only와 data_processing 작업 정의. 06/10/11 | 문서 수정 |
| DOC-008 | cancelled/완료 경합, interrupted/resumable, reconnect 의미 불명확 | 종류별 JobState, 최초 terminal commit, resume_eligibility 분리, cursor 만료 복구. 04/06/07/11 | 문서 수정 |
| DOC-009 | 요구 수준 VT 연결만으로 AC 전체 검수 완료로 오인 가능 | 404 AC를 단계별 subcase와 판정/필수 증거에 연결, 혼합 AC는 분리 후 AND. 03/14/17 | 추적 보완, 시험 미실행 |
| DOC-010 | 일부 참고 벡터/원문 감사가 실제 실행 증거처럼 서술됨 | 산술 기대값, 출처 검토와 실행 fixture 분리. pulse spectrum/phasor 차원과 채널별 정규화 보강. 09/11/21 | 문서 수정 |
| DOC-011 | 전기 전도도 sigma와 CSXCAD native Sigma 이름 혼동 위험 | domain 전기 전도도와 native Kappa/자기 손실 Sigma의 단위 매핑 명시. 08/09/11 | 설계 명시 |
| DOC-012 | CAD/solver 표현과 물리 두께의 변경 영향이 일괄 취급됨 | 실제 solver projection hash에 따른 raw 재사용 조건과 새 provenance/출력 재생성 구분. 07/10 | 문서 수정 |
| DOC-013 | 같은 OCCT 재열기를 독립 kernel 검증으로 읽을 수 있음 | reader 경로 독립성과 kernel 독립성 분리. KiCad mask face/filled-via 옵션 및 topology 기준 보완. 12/14 | 문서 수정, 왕복 미시험 |
| DOC-014 | 계산 실패 공차 표본에서도 수율/신뢰구간을 단일 값으로 제시할 위험 | 유효 표본의 조건부 통계와 전체 표본의 실패/미평가 및 bounds 분리. 13/14 | 문서 수정 |
| DOC-015 | 과거 data/extracted 경로와 현재 참고자료 배치 불일치 | 실제 00_REF 위치와 수량 연결. 원문/추출/검증 상태 및 lazy 조회 분리. 18/20 | 현 자료 대조 |
| DOC-016 | 실제 없는 예제 JSON을 제공된 파일처럼 설명 | 재현 가능한 입력/기대/실패 조건을 가진 미래 fixture 설계로 정리. 21 | 문서 수정 |
| DOC-017 | GUI core 라이선스와 유료 부품 범위가 섞일 수 있음 | wxWidgets 예외 조항, Avalonia MIT core/Pro TreeDataGrid 구분, 전이 Qt 의존성 제외. 18/24 | 공식 문서 확인 |
| DOC-018 | 중복 상태 안내, 오래된 버전 표기와 특수 문장부호로 가독성 저하 | 공통 개정 머리말, 단일 규범 소유권, 반복 공통 설명 축소, ASCII 문장부호/수식 표기. 원본 B 제외 | 문서 정리 |
| DOC-019 | host WSL launcher 종료와 실제 guest solver 종료를 혼동할 가능성 | guest supervisor/run nonce/lease, 실제 종료 확인 전 자원 반환/중복 실행/정리 차단. fencing의 게시 차단과 종료를 분리. 04/07/11 | 독립 재검토 반영 |
| DOC-020 | 외부 파일 hash 확인 이후 원본이 변경될 수 있음 | 실제 소비할 private staging byte를 봉인하고 검증. 원본 경로 재사용 금지. 08 | 독립 재검토 반영 |
| DOC-021 | 유한 journal/queue와 멱등 응답 보존 정책의 경계 누락 | 용량 예약 후 접수, durable commit 후 ACK, epoch/receipt 만료와 명시적 오류. 04/07/11 | 독립 재검토 반영 |
| DOC-022 | 메모리 budget의 측정량과 worker warm/idle 기준 불일치 | 추가 private commit peak의 baseline, buffer 범위와 관찰 구간, 수명 측정 두 정책을 고정. 24 | 독립 재검토 반영 |

DES-URS-001~005와 DES-ARCH-001~004는 원본 요구를 대신하는 새 사용자 요구가 아니라 이번 검토에서 구체화한 보충 설계조건이다. 기존 요구/AC의 ID를 재번호화하지 않는다. 본문의 특정 수치나 단계가 원문과 다르면 02의 결정 근거와 17의 subcase를 함께 본다.

## 3. 문서군별 확인 범위

| 문서 | 검토한 경계 |
| --- | --- |
| 00/01/02/16/25/README | 현재 자료, 범위, 원문 보존, 설계 승인과 변경 관리 |
| 03/06/17 | canonical 요구/AC, 기능/검증 연결, 단계별 판정과 실패 처리 |
| 04/05/07/08/11/19/24 | 상태/API, 수명, IPC, 단위/schema, UI/성능, 라이선스 |
| 09/10/13/22 | 수식의 가정/단위/부호, 정규화, 캐시, 합성/최적화/측정 |
| 12/14/21 | 출력 geometry/topology, 검증 독립성, acceptance/fixture |
| 18/20/23 | 현재 source/추출자료와 역사 자료의 구분, 원본 B 요구 연결 |

공식 페이지는 이번 선택/수정에 필요한 API, 단위, 라이선스와 출력 계약을 중심으로 확인했다. 과거 250개 source의 모든 URL과 원문 페이지를 이번에 전부 재현 검증했다는 의미는 아니다. 각 출처의 확인 범위는 18번에 남긴다. 외부 master/latest 문서는 구현 시 tag/commit과 설치 버전으로 다시 고정한다.

## 4. 문서 정합성 검사

검사 항목은 문서 집합, Markdown 로컬 링크/명시 anchor, 요구/AC/UI/FN/API/EQ/VT/PAR ID의 중복/누락, 원본 B 보존, AC별 단계 추적, 과거 경로/Qt 채택/상태 표기의 충돌, 수식 표기의 손상, Git 공백 오류다. 외부 source의 과거 ID/URL과 원본 B는 역사 자료로 보존하며 현재 제품 채택이나 실행 합격으로 세지 않는다.

요구 141개, AC 404개, UI 24개, FN 46개, API 30개, EQ 41개, VT 30개, PAR 162개의 안정 ID를 유지한다. 404 AC 중 단계가 혼합된 항목은 독립 subcase로 나누므로 추적 행 수가 AC 개수보다 많을 수 있다. pass는 해당 단계에 필요한 모든 assertion이 실제 실행되어 만족한 경우에만 쓴다. 단순 링크 존재나 정합성 검사 통과는 물리 정확도 증거가 아니다.

마지막 정합성 검사에서 Markdown 26개, 주요 ID와 원문 요구/AC 보존, 로컬 링크와 명시 anchor, 표의 열 수 및 code/math fence를 확인했다. 원본 B는 편집하지 않았고 Git diff가 없다. Git archive의 CRLF와 현재 작업 파일의 LF 차이는 내용 변경과 구분해 검사했다. 검사 개수와 결과는 검토용 package의 검사 기록에도 포함한다. 제품 개발 중에는 같은 검사를 CI의 문서 검사로 편입할 수 있으나 이번 작업에서 제품 코드를 생성하지 않는다.

문서 산술은 별도로 6개 assertion을 확인했다. 복소 Z0 전력파와 pseudo-wave의 전력 수지, network-facing 연결 C와 load 반사계수의 구분, N=100/k=90 Wilson 구간을 대조했으며 모두 지정 오차 안에서 일치했다. 이는 해당 입력의 산술 검산이며 EQ 전체, 설치 adapter, native solver, NF2FF 또는 실측 검증 통과가 아니다. EQ-022의 상관 지연 부호도 정의에서 확인했다.

## 5. 사용자가 검토할 결정

| ID | 결정 대상 | 제안 | 현재 상태 |
| --- | --- | --- | --- |
| DEC-D0-001 | GUI 선정 방식 | wxWidgets C++ 우선 평가, Avalonia C# 비교, Qt 제외. 24의 동등 실험 후 하나 선정 | 검토 대기 |
| DEC-D0-002 | 성능 예산 | 24의 기준 host/fixture/PERF-001~010을 초기 budget으로 사용 | 제안값, 미측정 |
| DEC-D0-003 | R1 사용자 환경 | Windows 11 x64와 Windows-WSL, Linux desktop/native worker를 각각 독립 검증 | 지원 목표 검토 대기 |
| DEC-D0-004 | R1 물리/출력 범위 | 원호/IFA 중심, 물성/포트/환경, 실제 2D/STEP/CAM, 기본 측정/스윕 유지 | 범위 검토 대기 |
| DEC-D0-005 | 최초 검증 제품/보드 | 완전한 synthetic/reference 입력을 먼저 정의. G031은 미정 물성 유지, geometry fixture로 제한 | 실제 적층/시제품 조건 필요 |
| DEC-D0-006 | GUI 부품/배포 | 유료 control을 필수로 하지 않는 기본안, 실제 포함 부품별 notice/조건 고정 | 배포 모델 확정 전 |
| DEC-D0-007 | 개발 착수 | 문서 기준선 검토 후 사용자가 별도로 지시. 이후 15의 WBS와 GUI spike 수행 | 착수 전 |

이 표는 지금 추가 답변을 요구하거나 문서 수정을 보류하기 위한 절차가 아니다. 문서를 읽은 뒤 사용자가 선택할 설계 항목을 한곳에 모은 것이다. 개발을 시작하라는 이전 문서의 자동 지시는 적용하지 않는다.

## 6. 실험 또는 외부 입력이 필요한 잔여 항목

| 항목 | 필요한 입력/증거 | 종료 조건 | 시점 |
| --- | --- | --- | --- |
| 원본 A 완전성 | 원본 A JSON과 출처/해시 | 137개 원문과 현재 요구/AC의 의미 및 바이트 계보 대조 | 회복 시, 현재는 본문 추적 범위만 확인 |
| GUI 우열 | 동등 Release prototype, GPU/OS/빌드 고정 | 24의 기능/성능/수명/라이선스 gate와 선정 이유 | D0 승인 후 R0 |
| runtime/profile | 실제 package/binary/OS/ABI | doctor/경로/취소/배포 fixture, 버전 lock | R0 |
| native 정규화 | 선택된 openEMS 채널/DFT와 known-power fixture | 전압/전류/field/power 단위/scale/위상 검증 | R0, GAP-003 |
| 재료/포트/수렴 | 완전한 물리 입력과 독립 비교 | 손실/전력 보존, mesh/boundary/time 및 각 port/model별 시험 | R0/R1, GAP-004/005/013 |
| STEP/EDA/CAM | 실제 writer/reader와 얇은 동박/비아/slot fixture | 좌표/단면/topology/편집 net의 정한 profile 통과 | R0/R1, GAP-002/008 |
| 시제품/실측 | 제작 조건, VNA/교정/OTA, 불확도와 holdout | 정합과 방사 검증 분리, 불확도 포함 비교 | R1 이후 관련 gate |
| 전문 물리 | UWB pair, complex field basis, NFC/RFID 조건 | 해당 물리영역의 전용 VT subcase 통과 | R2/R3 |

기존 GAP-001~015의 세부 정의는 [01번](01_RFAD_설계_결정과_범위.md)에 있다. 잔여 시험은 문서 수정을 덜 했다는 의미가 아니라 문서만으로 성능/물리 합격을 주장할 수 없는 경계다. 각 기능은 확인된 capability 범위에서만 제공한다.

## 7. 이번 개정 후의 사용법

먼저 00의 안내로 문서군을 확인하고 24의 GUI/성능 제안과 이 문서의 DEC-D0 표를 검토한다. 수정 의견은 관련 requirement/AC/문서 번호와 함께 남기면 영향 문서를 함께 갱신한다. 승인 시 16의 기준선 기록을 남긴 뒤 15의 R0 계획으로 넘어간다. 이번 개정은 개발 착수 지시를 대신하지 않는다.
