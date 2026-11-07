# 개발 착수와 현재 상태

기록일: 2026-11-07 KST

사용자는 설계 기준선 3.4 승인과 문서 커밋/푸시 완료 후 "이제 작업을 착수하자"라고 지시했다. 제품 작업 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`다. GUI도 이 경로 아래에 작성한다. 현재 상태는 개발 착수, R0 기초 구현 진행이다.

## 기준선과 현재 변경

- 승인 기준선: RFAD-D0-3.4, 커밋 `6ebeda156e9d31b893bf69046550f5df9b16dc64`.
- 01_Docs의 승인 문서와 records는 변경하지 않았다. 승인 당시 '착수 전' 표기를 현재 WBS 상태로 오해하지 않는다.
- 루트 README는 개발 영역으로 연결하는 현재 안내로 갱신했다. 승인 manifest의 README 해시는 승인 커밋의 README에 적용된다.
- 제품 방향, wxWidgets, 60/30 fps 초기 목표, Windows+WSL2 우선, 원호/IFA와 내부 배포 범위는 유지한다.

## 이번 구현과 근거

| 항목 | 실제 구현 | 연결 설계 | 상태와 한계 |
| --- | --- | --- | --- |
| 환경 진단 | Python/OS/도구/WSL/패키지 메타데이터, 실행 파일 SHA256, JSON 보고서 | WBS-002, VT-029 일부 | active. 조회 성공과 runtime lock/worker smoke를 구분 |
| 단위와 미정값 | 불변 Quantity, SI 변환, 차원/유한값/입력 상태/출처 | WBS-003, SYS-001, VT-005 일부, 08의 2/3/5.2절 | active. 표현식/복소수/충돌 후보/물성 모델은 미구현 |
| 정규 직렬화 | 버전 있는 UTF-8 codec과 SHA256 | WBS-003, 07의 6절, 08의 11절 | active. snapshot에 적용, 물리 cache subset 선정은 후속 |
| 프로젝트 명령 | 생성/재열기, 이름/설명/스칼라 parameter, expected_revision, 역명령 기록 | API-002/003, FN-001/002, WBS-003 | implemented subset. 실제 형상/재료 편집, expression와 undo UI는 후속 |
| 저장/스냅샷 | 단일 writer, immutable revision, saved 기준점, 별도 snapshot UUID/hash | API-004/005, SYS-036, PRJ-006/007, NFR-004, VT-018 일부 | implemented subset. versioned workspace profile; 독립 archive/copy/migration/GC는 후속 |
| 프로젝트 서비스 | NDJSON, durable receipt, 7일 epoch, 자료 처리 TaskRef/events/status/cancel | API-001~005/014/015, 07/11의 계약 일부 | 실제 background 자료 처리와 재시작 시험 완료. native/WSL worker, API-028 push, 전체 계약은 후속 |
| GUI 영역 | `ui/wxwidgets/` 위치와 책임 기록 | WBS-011, 24 | planned. C++ GUI 소스, dependency 구성, 빌드와 성능 시험은 아직 없음 |

현재 API는 workspace 없는 bootstrap/0.1 및 workspace를 지정한 projects/0.2 profile이다. 후자는 영속 epoch와 프로젝트 명령을 제공하며, 전체 API-001 입력 필터와 실제 CAD/solver adapter matrix까지 완료한 것으로 표시하지 않는다. 저장/명령의 정확한 필드와 지원 한계는 [프로젝트 저장 계약](project_persistence.md)에 있다.

## 확인한 개발 환경

실제 Windows host에서 `python -X utf8 -m rfad doctor --output .local/runtime-doctor.json`을 실행했다. 도구의 경로와 binary hash는 로컬 보고서에 남기고 Git에서 제외했다.

| 항목 | 실제 조회 결과 |
| --- | --- |
| OS / Python | Windows 11 AMD64 / CPython 3.12.10 64 bit |
| CMake / Ninja | 4.3.2 / 1.13.2 |
| MinGW g++ | 16.1.0, 현재 PATH에서 버전 조회 성공 |
| MSVC cl | 현재 PATH에서 찾지 못함 |
| WSL | 2.7.11.0 조회 성공, 등록된 Linux 배포판 없음 |
| 현재 Python 패키지 | NumPy/CadQuery/openEMS/scikit-rf 배포 메타데이터 없음 |

이 결과는 탐지한 환경 기록이며 위 조합을 GUI/CAD/EM 배포용으로 검증하거나 잠근 것이 아니다. 현재 코드는 표준 라이브러리만 사용한다. OS/WSL 배포판/외부 패키지 설치는 이번 단계에서 수행하지 않았다.

## 검증 기록

Windows의 위 Python에서 아래 시험을 실행했다.

```powershell
$env:PYTHONPATH = 'src'
python -X utf8 -m unittest discover -s tests -v
```

현재 총 109개 시험 통과: 기존 기반 58개, 프로젝트 도메인 19개, journal 17개, 서비스 통합 14개, 실제 프로젝트 서비스 프로세스 1개. 스킵 없음. 기존 58개는 첫 착수 단계의 기록이며 현재 프로젝트 기능을 포함해 재검증했다.

- 단위 변환 보존, missing과 0, 차원 오류, bool/비유한/overflow/underflow를 확인했다.
- 정규 바이트와 독립 .NET SHA256 기준 벡터, 인접 float64, Unicode와 배열 순서, 순환/깊이 경계를 확인했다.
- 환경 진단의 모의 timeout/오류/UTF-16/한글 및 공백 경로/무거운 모듈 미로딩을 확인했다. 실제 host 진단도 별도로 실행했다.
- 실제 Python 자식 프로세스에서 한국어 요청 ID와 stdout 전용 JSON 응답을 확인했다. 프레임/문자열/batch 제한, 알림, 미구현 명령 거부도 시험했다.
- 실제 파일에서 생성 -> 명령 -> 저장 -> 종료/재시작 -> 재열기와 동일 명령 replay를 확인했다. 단위/출처/ID와 스냅샷 바이트가 보존되었다.
- stale revision과 잘못된 명령, 중복 키의 다른 payload, command_id 재사용, epoch/receipt 만료 경계를 검사했다.
- 쓰기/fsync/replace/공간 부족, checksum 손상, 기존 경로 덮어쓰기와 중복 writer를 검사했다. 실제 자식 프로세스를 게시 전/후에 강제 종료하여 old/new 상태와 receipt가 함께 복원되는 것을 확인했다.
- live epoch 갱신이 실행 중인 작업을 중단하지 않는지, 잘못된 batch method가 구조화된 오류가 되는지 회귀 시험을 추가했다.

이 기록은 기반과 프로젝트 저장 profile의 시험이다. 정전/하드웨어 쓰기 cache 내구성, Linux 실행, C++/wxWidgets 빌드, GUI 통합/프레임/메모리, CAD 재열기, openEMS 실행, 수렴/정확도, 실측은 not_run이다. R0 또는 R1 완료를 주장하지 않는다.

## 다음 구현

1. WBS-003의 표현식/DAG, 실제 형상/물성 entity, 사용자 undo/redo, 독립 프로젝트/archive profile을 확장한다. 현재 승인된 기본 명령과 journal/snapshot 계약을 유지한다.
2. WBS-002의 격리 Python/native 의존성, wxWidgets/CMake 빌드 조합과 Linux/WSL worker 환경을 구성하고 실제 호환성을 확인한 뒤 lock한다.
3. 최소 명령/표시 DTO 이후 wxWidgets shell과 편집 흐름을 연결한다. mock UI와 실제 backend 연동의 증거를 구분한다.
4. 원호/IFA 의미 형상과 CAD/solver adapter를 연결한다. 완전한 참조 계산, IFA, 원호 순의 검증 계획을 유지한다.

실제 IFA Dk/Df, 상세 적층/제작/측정 조건은 해당 검증 전에 확정할 입력이다. 이를 기초 데이터/GUI 구현의 선행조건으로 두지 않으며 임의 대표값으로 채우지 않는다.

## 작업 중 확인한 제품 방향

CAD는 CadQuery를 통해 OCCT를 사용하고, 사용자 설계 안테나의 실제 openEMS 해석과 NF2FF 기반 패턴을 연결한다. 현재는 해당 adapter/화면이 미구현이다. GUI와 CLI가 공유하는 서비스는 후속 MCP adapter에서도 사용할 수 있지만 현재 내부 JSON-RPC가 MCP 서버를 구현한 것은 아니다. 여러 EDA 도구와의 통합에는 별도의 데이터 의미 mapping이 필요하다. 이 질의 응답을 기존 R1 범위의 임의 확장이나 MCP 구현 완료로 기록하지 않는다.
