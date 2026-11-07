# GUI 선정과 성능 설계

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

## 1. 결정 범위

GUI 후보는 C++ wxWidgets와 C# Avalonia 두 가지다. 사용자 방침에 따라 Qt, PySide, PyQt 및 Qt를 요구하는 GUI 부품을 제품 의존성에서 제외한다. 기존 조사 자료에 등장하는 Qt는 역사적 비교 자료일 뿐 구현 선택지가 아니다.

메모리 오버헤드가 전혀 없는 GUI는 현실적인 목표가 아니다. 최소화할 대상은 빈 앱의 고정 비용, 같은 데이터를 여러 프로세스와 GPU에 복제하는 비용, 작업 종료 후 남는 메모리, UI를 막는 대기 시간이다. 해석 자체에 필요한 모델과 결과 메모리는 이 비용과 따로 측정한다.

wxWidgets를 우선 평가 후보로 제안한다. C++와 native control 중심 구성으로 관리형 GUI 런타임의 고정 비용을 피할 가능성이 있다는 아키텍처 판단이다. 실제 RFAD에서 더 빠르거나 더 적은 메모리를 쓴다는 측정 결과는 아직 없다. Avalonia는 비교 후보로 유지하며 Native AOT도 별도 빌드 구성으로 평가한다. 최종 선정은 사용자 설계 검토 이후 승인된 비교 실험 결과로 결정한다.

## 2. 후보별 확인 사실과 검증할 사항

| 항목 | wxWidgets | Avalonia |
| --- | --- | --- |
| 구현 언어 | C++, native control 중심 | C#/.NET, 자체 control 렌더링 |
| 기본 비용 | C++ runtime, 선택 GUI 모듈, renderer 및 OS 자원 | .NET runtime, UI 객체, renderer 및 OS 자원. AOT도 GC와 런타임 지원 비용이 사라지는 것은 아님 |
| 대량 목록 | virtual model과 필요한 행만 읽는 데이터 공급자 | 가상화 control, compiled binding, 제한된 visual tree |
| 2D/3D 후보 | toolkit 중립 scene, wxGLCanvas 또는 검증된 native renderer | toolkit 중립 scene, OpenGL/native renderer 호스팅의 실제 호환 시험 |
| 도킹 | wxAUI를 후보로 검사 | 기본 패널 조합을 우선. 제3자 docking은 라이선스, 유지보수, GPU 재부착 검증 후 선택 |
| 위험 | C++ 수명 관리, 플랫폼별 control 차이, DPI/IME, native GPU context | 할당/GC, binding 및 layout 비용, trimming/AOT 호환성, control별 라이선스 |
| 선정 근거 | 동일 기능의 전체 프로세스 측정 | 동일 기능의 전체 프로세스 측정 |

wxWidgets의 native control 접근은 [공식 개요](https://wxwidgets.org/about/), virtual list와 OpenGL/AUI API는 [data view](https://github.com/wxWidgets/wxWidgets/blob/master/interface/wx/dataview.h), [GL canvas](https://github.com/wxWidgets/wxWidgets/blob/master/interface/wx/glcanvas.h), [AUI](https://github.com/wxWidgets/wxWidgets/blob/master/interface/wx/aui/framemanager.h)를 근거로 한다. API 존재는 RFAD 통합 시험 통과를 뜻하지 않는다.

Avalonia의 자체 렌더링은 [아키텍처](https://docs.avaloniaui.net/docs/fundamentals/cross-platform-architecture), 가상화와 binding 정책은 [성능 문서](https://docs.avaloniaui.net/troubleshooting/app-performance-issues)를 확인했다. Native AOT의 시작 시간과 메모리 개선 가능성 및 제약은 [Avalonia AOT](https://docs.avaloniaui.net/docs/deployment/native-aot), [Microsoft AOT](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/)를 기준으로 한다. 이 문서의 예산과 선정 순서는 RFAD 설계 제안이며 외부 도구의 보장값이 아니다.

## 3. 라이선스와 배포 구성

wxWidgets는 wxWindows Library Licence의 예외를 포함한다. Avalonia 핵심 프레임워크는 MIT다. 각각 [wxWidgets 원문](https://wxwidgets.org/about/licence/)과 [Avalonia 공식 안내](https://avaloniaui.net/faq/)를 적용하며, GUI 이름 하나로 전체 배포물의 조건을 판단하지 않는다.

특히 Avalonia 공식 성능 문서가 추천하는 TreeDataGrid는 현재 Avalonia Pro 구성이다. 따라서 무료 핵심 프레임워크에 당연히 포함된다고 가정하지 않는다. R1 기본 설계는 별도 유료 control을 전제로 하지 않으며 목록 가상화와 지연 로딩을 구현 가능한 기본 control/모델로 검증한다. 유료 부품이 필요하면 가격과 배포 조건을 별도 설계 변경으로 제시한다.

배포 명세에는 GUI, CRT/.NET, Skia/OpenGL binding, docking/chart 부품, CAD/solver, 폰트, 아이콘 각각의 버전, 출처, LICENSE/NOTICE, 수정 여부, 포함 방식이 필요하다. Qt 제외 여부는 직접 의존성뿐 아니라 전이 의존성에서도 검사한다. 독립 프로세스 구조가 다른 라이브러리의 라이선스 조건을 자동 해소한다고 판단하지 않는다.

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

구체 IPC와 메모리 소유권은 [07](07_RFAD_소프트웨어_아키텍처.md), 파일/배열 계약은 [08](08_RFAD_데이터_모델과_파일_형식.md)에 정의한다.

## 5. 동등 비교 fixture

두 후보는 같은 data hash, 렌더 표시 품질, 화면 크기, 폰트, 열린 패널, backend와 작업 순서를 사용한다. 빈 기본 창만 비교한 수치를 최종 선정 근거로 쓰지 않는다. renderer가 다르면 toolkit 비교와 전체 제품 구성 비교를 별도 실험으로 표시한다.

| fixture | 입력과 행동 | 관찰 |
| --- | --- | --- |
| PERF-F0 | 빈 앱, 도킹 패널과 경량 service, 30초 idle | 시작 시간, idle 메모리/CPU |
| PERF-F1 | 4층, 10,000개 2D primitive, 1,000개 parameter, 100,000개 검색 레코드 | 열기, 표 scroll/filter, 선택, drag, undo, 저장 |
| PERF-F2 | 동일 1,000,000 triangle 표시 데이터, 동일 시점/재질, 1920x1080 | 회전/선택 frame time, GPU 메모리, LOD 품질 |
| PERF-F3 | 1 GiB field artifact, 8개 complex trace 각각 100,000점 | ROI/주파수 이동, 최초 표시, peak 메모리와 파일 IO |
| PERF-F4 | 동일 backend 부하와 초당 1,000행 로그, 저장/취소/재연결 | UI 지연, ACK, 이벤트 누락, 작업 트리 종료 |
| PERF-F5 | F1/F2/F3 열기-닫기 30회, warm 유지 실험과 idle 회수 실험 분리 | 마지막 10회 메모리 추세와 핸들/GPU 자원 회수 |

fixture는 사용자 승인 후 만들며 아직 실행한 데이터가 아니다. baseline host 제안은 Windows 11 x64, 물리 4코어 이상, RAM 16 GiB, SSD, 내장 GPU, 1920x1080이다. 정확한 CPU/GPU/driver/OS build/전원 모드/백신/백그라운드 상태는 측정 manifest에 고정한다. Linux는 지원 대상으로 선택한 배포판과 display backend별로 별도 합격해야 한다.

## 6. 성능 예산 초안

아래 값은 개발 시작 전 사용자가 검토할 예산 제안이다. 실제 성능, 제조 수치 허용오차, 승인된 서비스 보장값이 아니다. 변경 시 이유와 영향 fixture를 기록하고 결과를 본 뒤 조용히 완화하지 않는다. MiB=2^20 bytes, GiB=2^30 bytes다.

| ID | 측정 대상 | 제안 예산 |
| --- | --- | --- |
| PERF-001 | F0 cold / warm launch에서 첫 usable window | cold p95 <= 3초, warm p95 <= 1.5초 |
| PERF-002 | F0 경량 service까지 신규 편집 가능 | cold p95 <= 5초, warm p95 <= 2초 |
| PERF-003 | F0 GUI private commit / GUI+service 합계 | 각각 <= 150 MiB / <= 300 MiB |
| PERF-004 | F1 정상 편집의 GUI+service 합계 private commit | <= 768 MiB. CAD build peak는 별도 기록 |
| PERF-005 | F1 입력부터 화면 반영 | p95 <= 50 ms, p99 <= 100 ms |
| PERF-006 | F2 회전 중 실제 표시 frame time | p95 <= 33.3 ms. FPS 평균만으로 판정하지 않음 |
| PERF-007 | F4 취소 버튼 반응 / coordinator 접수 ACK | 각각 p95 <= 100 ms / <= 200 ms. native 종료는 별도 |
| PERF-008 | F0 idle CPU, 30초 측정 | 전체 앱 CPU time / wall time <= 단일 logical CPU의 1% |
| PERF-009 | F3 조회의 GUI+service+postprocessor 추가 private commit peak | 같은 worker가 준비된 idle baseline 대비 <= 512 MiB. ROI/cache/압축해제/복사 buffer 포함, working set/GPU도 별도 보고 |
| PERF-010 | F5 마지막 10회와 초기 5회 안정화 값의 중앙값 차이 | 전체 앱 private commit 증가 <= max(32 MiB, 초기 중앙값의 5%), 지속 증가 원인 설명 및 handle/GPU 누수 없음 |

cold는 재부팅 후 첫 실행을 최소 5회, warm은 동일 조건 반복 실행을 최소 20회 측정한다. 표본 수, 중앙값, p95, 최대값을 모두 보고한다. cold 5회에서는 p95가 사실상 최대값에 가깝다는 한계도 기록한다. 지연은 각 fixture에서 1,000개 이상의 timestamp 표본을 얻어 p95/p99를 계산하고 원시 측정을 보존한다. profiler를 붙인 진단 실행과 Release 비교 실행은 구분한다.

PERF-009는 F3 열기 직전 같은 worker를 준비한 상태를 baseline으로 하고, 열기부터 10회의 ROI/주파수 변경과 닫기까지 100 ms 간격 표본 및 OS peak를 보존한다. 논리 cache의 byte 수와 process commit 증가를 별도로 기록하여 버퍼/할당 비용을 숨기지 않는다. 파일 크기의 실제 resident 비율도 관찰하되 commit과 혼동하지 않는다.

F5 warm 실험은 worker를 명시적으로 유지하고 매회 닫기 후 30초 값을 기록한다. idle 회수 실험은 기본 120초 timeout과 30초 grace를 지난 뒤 기록한다. 각 실험 30회에서 초기 5회 중앙값과 마지막 10회 중앙값을 비교한다. 두 정책의 결과를 섞지 않으며 warm 기준에는 유지한 worker 메모리도 포함한다.

## 7. 메모리 측정과 작업 예산

Windows private commit과 working set은 다른 값이다. PrivateUsage는 private commit이며 현재 물리 RAM 사용량과 동일하지 않다. [Microsoft 구조체 명세](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex)를 기준으로 지표와 단위를 기록한다.

GUI, application service, CAD, solver, postprocess 각각의 private commit, private/total working set, peak와 GPU dedicated/shared memory를 함께 남긴다. 여러 프로세스의 total working set 합은 shared page를 중복 계산할 수 있으므로 단일 물리 사용량처럼 표시하지 않는다. Linux는 RSS/PSS와 private 메모리를 구분하고 Windows commit과 같은 의미로 비교하지 않는다. WSL은 host VM 사용량과 guest worker 사용량을 따로 측정하고 중복 합산하지 않는다. WSL VM의 다른 작업 비용도 RFAD 비용으로 임의 귀속하지 않는다.

solver 동시 실행은 기본 1개다. admission 시 전체 worker 예상 peak 합, 기존 앱 사용량, OS/다른 앱 여유, 디스크 임시/최종 출력 예산을 확인한다. 최소 예약 여유 제안은 max(4 GiB, 물리 RAM의 25%)이며 미사용 예약을 프로그램이 실제 할당하지는 않는다. CPU thread 수와 수치 라이브러리의 내부 thread 수를 함께 제한해 중첩 병렬화와 UI starvation을 피한다. 예상치의 근거와 보정 오차를 표시한다.

메모리 압박 시 표시 cache/idle worker부터 회수한다. 계산 정밀도나 물리 형상을 몰래 줄이지 않는다. native job를 취소해야 하면 partial 보존과 명시한 종료 정책을 따른다. EmptyWorkingSet, 반복 강제 GC, 파일 cache 삭제로 수치를 좋게 보이게 하지 않는다.

## 8. GUI 비교 시험과 선택 규칙

| 시험 | 필수 내용 | 관련 문서 |
| --- | --- | --- |
| GUI-SPIKE-001 | Release 패키지 시작/idle, 의존성 및 Qt 부재, AOT 후보의 실제 배포 파일 | 01, 07, 15 |
| GUI-SPIKE-002 | F1 표/트리/2D, keyboard, 한국어 IME, undo와 revision | 05, 06 |
| GUI-SPIKE-003 | F2 3D, DPI 100/150/200%, 도킹 재부착, context 복구 | 05, 12 |
| GUI-SPIKE-004 | F3 ROI/대형 파일, hash검증 비동기화, decimation 구분 | 08, 10 |
| GUI-SPIKE-005 | F4 로그 폭주, cancel ACK/실제 종료, crash/reconnect | 04, 11 |
| GUI-SPIKE-006 | F5 반복 수명, GPU/handle/file mapping 회수, 잠금없는 삭제 | 07, 08 |
| GUI-SPIKE-007 | 플랫폼별 배포, 접근성, control/renderer 라이선스, 전체 측정 보고 | 14, 15 |

기능/입력 정확성/라이선스/안정성의 필수 gate를 먼저 적용한다. 통과 후보 사이에서는 F0/F1의 전체 private commit과 idle/peak 비용을 우선 비교하되 PERF 지연 예산을 동시에 만족해야 한다. 10% 미만 차이 또는 반복 변동 범위가 겹치는 결과는 성능상 동률로 보고 유지보수와 통합 비용을 비교한다. 하나가 필수 gate를 실패하면 낮은 메모리만으로 선택하지 않는다. 둘 다 실패하면 문제를 수정해 재측정하고 Qt로 자동 대체하지 않는다.

최종 기록에는 빌드 옵션, runtime/renderer 버전, fixture hash, 원시 표본, OS별 결과, 미통과 항목, 배포 의존성, 선정 이유와 사용자 결정이 필요하다. 현재 상태는 `candidate_pending_gui_spike`다. 문서 검토 승인과 GUI 실험 결과의 최종 선정은 별도 결정이며 [25번](25_RFAD_문서_검토와_승인.md)에서 추적한다.
