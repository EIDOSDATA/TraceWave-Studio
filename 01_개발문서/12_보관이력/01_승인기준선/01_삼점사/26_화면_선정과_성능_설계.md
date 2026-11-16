# GUI 선정과 성능 설계

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

## 1. 결정 범위

2026-11-07 사용자 결정으로 제품 GUI는 **C++ wxWidgets로 확정**한다. 일반 편집 화면은 **60 fps**, 대형 장면은 **30 fps**를 목표로 하며, **유료 GUI 부품을 기본 기능의 필수 의존성으로 사용하지 않는다**. 이 세 결정은 설계에 반영한 사용자 방침이며 실제 성능 합격이나 개발 착수 승인이 아니다.

R1 우선 출시는 Windows 11 x64의 wxMSW GUI와 로컬 WSL2 Linux worker를 대상으로 한다. Linux wxGTK GUI는 후속 출시로 두며 정확한 출시 버전은 아직 정하지 않는다. Linux native/headless worker의 R0 기준 검증은 유지한다. Linux worker 검증을 Linux 데스크톱 GUI의 제품 지원 완료로 표시하지 않는다. wxQt, Qt, PySide, PyQt 및 Qt를 요구하는 GUI 부품은 직접/전이 의존성에서 제외한다. Avalonia는 이전 비교 검토 이력으로만 보존하며 현재 개발 후보나 비교 prototype 범위에 포함하지 않는다.

메모리 오버헤드가 전혀 없는 GUI는 현실적인 목표가 아니다. 최소화할 대상은 빈 앱의 고정 비용, 같은 데이터를 여러 프로세스와 GPU에 복제하는 비용, 작업 종료 후 남는 메모리, UI를 막는 대기 시간이다. 해석 자체에 필요한 모델과 결과 메모리는 이 비용과 따로 측정한다.

선정 이유는 C++와 native control 중심으로 GUI의 고정 비용을 줄이고 명시적인 자원 수명을 관리하려는 설계 방향이다. wxWidgets가 실제 RFAD에서 더 빠르거나 더 적은 메모리를 쓴다는 비교 측정 결과는 없다. Python service와 CAD/solver worker 구조는 유지한다. 현재 상태는 `selected_pending_validation`이며, 후속 작업은 선정된 wxWidgets의 통합과 성능 검증이다. 구현과 prototype 제작은 사용자의 별도 개발 착수 지시 후에만 시작한다.

## 2. wxWidgets 구성과 검증할 사항

| 항목 | 설계 기준 | 후속 확인 |
| --- | --- | --- |
| 구현 언어와 플랫폼 | C++ GUI, R1 Windows wxMSW+WSL2 worker, 후속 Linux wxGTK GUI | Linux native/headless worker는 R0 기준 검증 유지. 실제 OS/ABI/compiler/wxWidgets 버전 고정, wxQt 제외 |
| 기본 비용 | C++ runtime, 선택 GUI 모듈, renderer와 OS 자원 | GUI/service/worker 전체 메모리, 시작과 idle 비용 |
| 대량 목록 | virtual model과 필요한 행만 읽는 데이터 공급자 | 표/트리 scroll, 검색, 선택, 편집 중 지연과 메모리 |
| 2D/3D | toolkit 중립 scene, wxGLCanvas 또는 검증된 native renderer | 일반 편집 60 fps, 대형 장면 30 fps, picking과 표시 품질 |
| 도킹 | wxAUI를 우선 통합 대상으로 검토 | DPI 변경, GPU context 재부착, 패널 복원과 keyboard 접근 |
| 수명과 입력 | C++ 자원 소유권 및 해제 경계, 한국어 IME | handle/GPU 누수, focus, undo, 취소와 재연결 |
| 필수 GUI 부품 | 별도 유료 부품을 요구하지 않는 기본 기능 구성 | 라이선스 목록과 유료 부품 없는 배포에서 기능 검수 |

wxWidgets의 native control 및 플랫폼 구성은 [공식 개요](https://wxwidgets.org/about/), virtual list와 OpenGL/AUI API는 [data view](https://github.com/wxWidgets/wxWidgets/blob/master/interface/wx/dataview.h), [GL canvas](https://github.com/wxWidgets/wxWidgets/blob/master/interface/wx/glcanvas.h), [AUI](https://github.com/wxWidgets/wxWidgets/blob/master/interface/wx/aui/framemanager.h)를 근거로 한다. API 존재는 RFAD 통합 시험 통과를 뜻하지 않는다. 이전 Avalonia/.NET 조사 출처는 [18번 출처 기록](18_RFAD_출처와_근거.md)에 역사 자료로 남긴다.

## 3. 라이선스와 배포 구성

초기 배포는 사용자 결정에 따라 내부 검증용으로 한정한다. 외부 공개/상용 배포와 소스 공개 정책은 외부 배포 전에 별도로 확정한다. 내부 검증용이어도 실제 포함 부품의 조건, 버전과 notice는 기록한다. 이 방침은 지금 설치나 배포물을 만드는 지시가 아니다.

wxWidgets는 wxWindows Library Licence의 예외를 포함한다. 채택 버전의 [라이선스 원문](https://wxwidgets.org/about/licence/)과 실제 포함 부품별 조건을 확인하며 GUI 이름 하나로 전체 배포물의 조건을 판단하지 않는다.

사용자 결정에 따라 표/트리, 도킹, 2D/3D 편집, 그래프 등 기본 기능을 사용하기 위해 별도 유료 GUI 부품이나 구독을 구매해야 하는 구성을 만들지 않는다. wxWidgets 기본 control/모델과 조건을 확인한 무상 사용 가능 부품을 우선한다. 대량 데이터의 가상화와 지연 로딩도 이 기본 구성에서 검증한다. 이 방침은 제품 자체의 무료 배포나 모든 선택 유료 확장의 금지를 뜻하지 않는다. 유료 선택 확장을 제안할 경우 기본 기능의 사용 가능성을 유지하고 비용, 배포 조건과 의존성을 별도 설계 변경으로 기록한다.

배포 명세에는 wxWidgets, C++ runtime, Python service, OpenGL/renderer, docking/chart 부품, CAD/solver, 폰트와 아이콘 각각의 버전, 출처, LICENSE/NOTICE, 수정 여부, 포함 방식이 필요하다. Qt 제외 여부는 직접 의존성뿐 아니라 전이 의존성에서도 검사한다. 독립 프로세스 구조가 다른 라이브러리의 라이선스 조건을 자동 해소한다고 판단하지 않는다.

## 4. 체감 성능을 위한 공통 구조

1. GUI는 창, 입력, 선택, 화면용 projection만 소유한다. Python application service는 단위, 명령, revision, hash의 유일한 소유자다. GUI가 전체 프로젝트를 매 프레임 재직렬화하지 않는다.
2. 시작할 때 CAD, solver, 대형 reference DB와 field 데이터를 불러오지 않는다. 경량 service를 먼저 연결하고 CAD/EM/postprocess worker는 해당 작업에 진입할 때 시작한다.
3. 무거운 worker는 종류별 한 개를 기본으로 재사용한다. 작업 완료 후 참조가 해제된 idle worker는 기본 120초 후 종료할 수 있고 다음 실행 시 다시 시작한다. 사용자가 warm 유지 정책을 선택하면 그 메모리를 자원 표시와 예산에 포함한다.
4. 표와 트리는 보이는 행과 확장한 노드만 로딩한다. 검색/정렬은 worker 또는 색인에서 수행하고 결과를 페이지 단위로 반환한다. 전체 HDF5를 UI 객체 목록으로 복제하지 않는다.
5. 2D 이동 중에는 화면용 preview만 갱신한다. 값 확정 시 하나의 command를 보낸다. CAD rebuild는 최신 revision만 게시하며 과거 응답은 캐시 또는 폐기한다. drag 도중 매 이벤트마다 CAD/EM을 실행하지 않는다.
6. 3D는 LOD, view frustum, 제한된 GPU cache와 안정된 entity mapping을 사용한다. 저해상도 표시가 물리 원본이나 STEP 정밀도를 바꾸지 않는다. GPU context 손실 때 파일 저장 기능은 계속 제공한다.
7. 그래프는 화면 해상도에 맞춘 표시 표본을 사용하되 extrema와 좁은 공진을 보존한다. 목표 판정은 원래 유효한 계산점/검증 정책으로 수행한다. 표시용 decimation으로 수용 판정을 내리지 않는다.
8. 진행 이벤트는 job별 최대 10 Hz로 UI에 합쳐 전달한다. UI 로그는 최근 10,000행의 bounded tail을 기본으로 하고 전체 로그는 용량 제한과 회전을 가진 파일로 보존한다. 오류와 terminal event는 누락 없이 우선 전달한다.
9. 입력, 저장, 취소를 solver 로그보다 우선 처리한다. stdout/stderr를 동시에 비우고, 무한 큐 대신 backpressure와 dropped-log-count를 기록한다. 상태 이벤트는 log drop 정책의 대상이 아니다.
10. 연속 조작 중 일반 편집은 60 fps, 대형 장면은 30 fps를 목표로 화면 갱신을 배분한다. 정지 화면은 변경 이벤트가 있을 때 갱신하며 idle 상태에서 60 fps 반복 렌더링을 강제하지 않는다. 10 Hz 작업 진행 이벤트 제한은 렌더 프레임 목표와 별개다.

구체 IPC와 메모리 소유권은 [07](07_RFAD_소프트웨어_아키텍처.md), 파일/배열 계약은 [08](08_RFAD_데이터_모델과_파일_형식.md)에 정의한다.

## 5. 성능 검증 fixture

선정된 wxWidgets의 Release 구성은 data hash, 렌더 표시 품질, 화면 크기, 폰트, 열린 패널, backend와 작업 순서를 고정하여 검증한다. renderer 또는 빌드 설정을 비교할 때도 동일한 fixture와 품질을 유지한다. 빈 기본 창의 수치만으로 실제 편집 성능을 판정하지 않는다. 아래 fixture와 입력 크기는 초기 검증 기준으로 채택했다. 실제 입력 파일, hash와 실행 환경 manifest는 개발 착수 지시 후 준비하며 아직 실행한 결과가 아니다.

| fixture | 입력과 행동 | 관찰 |
| --- | --- | --- |
| PERF-F0 | 빈 앱, 도킹 패널과 경량 service, 30초 idle | 시작 시간, idle 메모리/CPU |
| PERF-F1 | 일반 편집: 4층, 10,000개 2D primitive, 1,000개 parameter, 100,000개 검색 레코드. 일반 3D subcase는 100,000 triangle 표시 데이터 | 열기, 표 scroll/filter, 2D pan/zoom/drag, 일반 3D 회전/선택, undo, 저장. 연속 조작은 60 fps 목표 |
| PERF-F2 | 대형 장면: 1,000,000 triangle 표시 데이터, 고정 시점/재질, 1920x1080 | 연속 회전/이동의 30 fps 목표, 선택, GPU 메모리와 LOD 품질 |
| PERF-F3 | 1 GiB field artifact, 8개 complex trace 각각 100,000점 | ROI/주파수 이동, 최초 표시, peak 메모리와 파일 IO |
| PERF-F4 | 동일 backend 부하와 초당 1,000행 로그, 저장/취소/재연결 | UI 지연, ACK, 이벤트 누락, 작업 트리 종료 |
| PERF-F5 | F1/F2/F3 열기-닫기 30회, warm 유지 실험과 idle 회수 실험 분리 | 마지막 10회 메모리 추세와 핸들/GPU 자원 회수 |

일반/대형 분류는 사전 고정한 F1/F2 입력과 동작으로 구분한다. F1이 느리다는 이유로 F2로 재분류하지 않는다. fixture 범위를 넘는 장면에는 두 목표의 달성을 보장하지 않으며 부하와 적용한 표시 품질을 기록한다.

fixture는 별도 개발 착수 지시 후 만들며 아직 실행한 데이터가 아니다. 초기 성능 기준 host는 Windows 11 x64, 물리 4코어 이상, RAM 16 GiB, SSD, 내장 GPU, 1920x1080으로 채택한다. 이는 모든 크기의 해석을 실행할 수 있다는 최소 사양 보장이 아니다. 정확한 CPU/GPU 모델, driver, OS build, 전원 모드, 백신과 백그라운드 상태는 측정 전에 manifest로 고정한다. 개발 착수 후 기준 사양에 맞는 사용 가능한 장비 한 대를 우선 선정하며 장비 구매를 전체 개발의 선행조건으로 두지 않는다. 기준과 다른 장비의 결과는 별도 실행 조건으로 기록하고 기준 host에서 합격한 것으로 대체하지 않는다. 같은 조건의 변경 전후 비교를 우선하며 판정값을 결과에 맞춰 완화하지 않는다. R1은 Windows GUI+WSL2 경로를 검증하며 Linux native/headless worker 기준군도 유지한다. Linux GUI의 성능/배포/입력 검수는 후속 GUI 출시 전에 해당 배포판과 display backend별로 수행한다.

## 6. 성능 목표와 예산

사용자 결정으로 PERF-001~010 전체 예산, 기준 host와 fixture를 초기 성능 목표 및 검증 기준으로 채택한다. PERF-006의 일반 편집 60 fps와 대형 장면 30 fps를 유지하며 p95 frame time으로 검수한다. 모든 목표의 실제 달성 여부는 미측정이다. 메모리 예산은 상한 목표이며 미사용분을 채우거나 미리 할당하라는 의미가 아니다. 실제 사용을 더 낮출 수 있으면 낮추며 제조 수치 허용오차, 최소 사양 보장이나 서비스 보장값으로 확대하지 않는다. 변경 시 이유와 영향 fixture를 기록하고 결과를 본 뒤 조용히 완화하지 않는다. MiB=2^20 bytes, GiB=2^30 bytes다.

| ID | 측정 대상 | 목표/예산 |
| --- | --- | --- |
| PERF-001 | F0 cold / warm launch에서 첫 usable window | cold p95 <= 3초, warm p95 <= 1.5초 |
| PERF-002 | F0 경량 service까지 신규 편집 가능 | cold p95 <= 5초, warm p95 <= 2초 |
| PERF-003 | F0 GUI private commit / GUI+service 합계 | 각각 <= 150 MiB / <= 300 MiB |
| PERF-004 | F1 정상 편집의 GUI+service 합계 private commit | <= 768 MiB. CAD build peak는 별도 기록 |
| PERF-005 | F1 입력부터 화면 반영 | p95 <= 50 ms, p99 <= 100 ms |
| PERF-006 | F1 일반 편집 / F2 대형 장면의 연속 조작 중 실제 표시 frame time | F1: 60 fps, p95 <= 1000/60 ms (약 16.67 ms). F2: 30 fps, p95 <= 1000/30 ms (약 33.33 ms). 목표 확정, 실측 전. F1의 2D 편집/표 스크롤/일반 3D와 F2 대형 3D를 독립 측정하고 모두 통과 |
| PERF-007 | F4 취소 버튼 반응 / coordinator 접수 ACK | 각각 p95 <= 100 ms / <= 200 ms. native 종료는 별도 |
| PERF-008 | F0 idle CPU, 30초 측정 | 전체 앱 CPU time / wall time <= 단일 logical CPU의 1% |
| PERF-009 | F3 조회의 GUI+service+postprocessor 추가 private commit peak | 같은 worker가 준비된 idle baseline 대비 <= 512 MiB. ROI/cache/압축해제/복사 buffer 포함, working set/GPU도 별도 보고 |
| PERF-010 | F5 마지막 10회와 초기 5회 안정화 값의 중앙값 차이 | 전체 앱 private commit 증가 <= max(32 MiB, 초기 중앙값의 5%), 지속 증가 원인 설명 및 handle/GPU 누수 없음 |

cold는 재부팅 후 첫 실행을 최소 5회, warm은 동일 조건 반복 실행을 최소 20회 측정한다. 표본 수, 중앙값, p95, 최대값을 모두 보고한다. cold 5회에서는 p95가 사실상 최대값에 가깝다는 한계도 기록한다. 지연은 각 fixture에서 1,000개 이상의 timestamp 표본을 얻어 p95/p99를 계산하고 원시 측정을 보존한다. profiler를 붙인 진단 실행과 Release 성능 검증 실행은 구분한다.

PERF-006은 F1의 2D 편집, 표 스크롤, 일반 3D와 F2 대형 3D를 네 동작군으로 구분한다. 각 동작군에서 정지 구간을 제외한 최소 30초의 연속 조작과 1,000개 이상의 실제 화면 갱신 간격 조건을 모두 만족하도록 수집한다. 처음 열기/데이터 준비 시간은 별도로 보고하고 조작 중 발생한 긴 정지나 누락 프레임을 표본에서 제외하지 않는다. p95와 함께 p99, 최대 간격, 목표 간격 초과율을 기록한다. 평균 FPS, 렌더 함수 호출 횟수 또는 입력 ACK만으로 실제 표시 frame time을 대체하지 않는다. 측정 가능한 paint/present/compositor 시점과 한계를 기록하고, 실제 갱신 시점을 확인하지 못한 경우 합격으로 판정하지 않는다. 표시장치 refresh는 최소 60 Hz로 고정하며 실제 refresh, VSync, DPI와 renderer를 함께 기록한다. 사용자 입력 반영 지연(PERF-005)과 프레임 간격(PERF-006)은 각각 만족해야 한다.

PERF-009는 F3 열기 직전 같은 worker를 준비한 상태를 baseline으로 하고, 열기부터 10회의 ROI/주파수 변경과 닫기까지 100 ms 간격 표본 및 OS peak를 보존한다. 논리 cache의 byte 수와 process commit 증가를 별도로 기록하여 버퍼/할당 비용을 숨기지 않는다. 파일 크기의 실제 resident 비율도 관찰하되 commit과 혼동하지 않는다.

F5 warm 실험은 worker를 명시적으로 유지하고 매회 닫기 후 30초 값을 기록한다. idle 회수 실험은 기본 120초 timeout과 30초 grace를 지난 뒤 기록한다. 각 실험 30회에서 초기 5회 중앙값과 마지막 10회 중앙값을 비교한다. 두 정책의 결과를 섞지 않으며 warm 기준에는 유지한 worker 메모리도 포함한다.

## 7. 메모리 측정과 작업 예산

Windows private commit과 working set은 다른 값이다. PrivateUsage는 private commit이며 현재 물리 RAM 사용량과 동일하지 않다. [Microsoft 구조체 명세](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex)를 기준으로 지표와 단위를 기록한다.

GUI, application service, CAD, solver, postprocess 각각의 private commit, private/total working set, peak와 GPU dedicated/shared memory를 함께 남긴다. 여러 프로세스의 total working set 합은 shared page를 중복 계산할 수 있으므로 단일 물리 사용량처럼 표시하지 않는다. Linux는 RSS/PSS와 private 메모리를 구분하고 Windows commit과 같은 의미로 비교하지 않는다. WSL은 host VM 사용량과 guest worker 사용량을 따로 측정하고 중복 합산하지 않는다. WSL VM의 다른 작업 비용도 RFAD 비용으로 임의 귀속하지 않는다.

solver 동시 실행은 기본 1개다. admission 시 전체 worker 예상 peak 합, 기존 앱 사용량, OS/다른 앱 여유, 디스크 임시/최종 출력 예산을 확인한다. 초기 자원 계획의 최소 여유 목표는 max(4 GiB, 물리 RAM의 25%)이며 미사용 예약을 프로그램이 실제 할당하지는 않는다. CPU thread 수와 수치 라이브러리의 내부 thread 수를 함께 제한해 중첩 병렬화와 UI starvation을 피한다. 예상치의 근거와 보정 오차를 표시한다.

메모리 압박 시 표시 cache/idle worker부터 회수한다. 계산 정밀도나 물리 형상을 몰래 줄이지 않는다. native job를 취소해야 하면 partial 보존과 명시한 종료 정책을 따른다. EmptyWorkingSet, 반복 강제 GC, 파일 cache 삭제로 수치를 좋게 보이게 하지 않는다.

## 8. wxWidgets 통합 시험과 수용 규칙

| 시험 | 필수 내용 | 관련 문서 |
| --- | --- | --- |
| GUI-SPIKE-001 | R1 wxMSW+WSL2 내부 검증 패키지의 시작/idle, Qt 부재와 실제 배포 의존성. wxGTK GUI는 후속 출시 검수 | 01, 07, 15 |
| GUI-SPIKE-002 | F1 표/트리/2D 연속 편집 60 fps, keyboard, 한국어 IME, undo와 revision | 05, 06 |
| GUI-SPIKE-003 | F1 일반 3D 60 fps와 F2 대형 3D 30 fps, DPI 100/150/200%, 도킹 재부착, context 복구 | 05, 12 |
| GUI-SPIKE-004 | F3 ROI/대형 파일, hash검증 비동기화, decimation 구분 | 08, 10 |
| GUI-SPIKE-005 | F4 로그 폭주, cancel ACK/실제 종료, crash/reconnect | 04, 11 |
| GUI-SPIKE-006 | F5 반복 수명, GPU/handle/file mapping 회수, 잠금없는 삭제 | 07, 08 |
| GUI-SPIKE-007 | R1 Windows 내부 검증 배포, 접근성, 라이선스, 유료 GUI 부품 없는 기본 기능과 전체 측정 보고. Linux GUI는 후속 별도 검수 | 14, 15 |

GUI-SPIKE-001..007의 기존 ID는 추적을 위해 유지하되 의미는 선정된 wxWidgets의 통합/성능 검증이다. Avalonia 비교 구현이나 toolkit 재선정을 수행하는 단계가 아니다.

기능/입력 정확성/라이선스/안정성의 필수 gate와 해당 성능 기준을 함께 적용한다. F1 일반 편집과 F2 대형 장면의 결과를 합산 평균하여 한쪽 실패를 숨기지 않는다. GUI/service/worker 전체 메모리와 지연을 함께 보고, 유료 GUI 부품 없이 기본 기능을 사용할 수 있는지 검수한다. 미달한 항목은 원인을 수정하고 해당 fixture를 재검증한다. 성능 미달만으로 Avalonia나 Qt로 자동 전환하거나 사용자가 정한 목표를 완화하지 않는다. 기술 방향 또는 목표 변경이 필요하면 근거를 제시하여 별도 설계 결정으로 기록한다.

검증 기록에는 빌드 옵션, wxWidgets/renderer 버전, fixture hash, 원시 표본, OS별 결과, 미통과 항목과 배포 의존성이 필요하다. 현재 상태는 `selected_pending_validation`이다. GUI, 초기 성능 목표, 출시 순서와 내부 배포 방침을 포함한 3.4 전체 문서 기준선은 승인 완료다. 25번의 승인 기록과 별도로 실제 통합 검증은 미실행이며 개발 착수 지시는 남아 있다. 개발은 아직 시작하지 않는다.
