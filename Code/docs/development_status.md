# 개발 착수와 현재 상태

기록일: 2026-11-07 KST

제품 개발 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`다. 승인 기준선은 RFAD-D0-3.4, 커밋 `6ebeda156e9d31b893bf69046550f5df9b16dc64`다. 01_Docs와 승인 records는 변경하지 않았다. 기준선의 착수 전 표기는 당시 승인 기록이며 현재 상태는 R0 기초 구현 진행이다.

wxWidgets, Windows 11+WSL2 우선, Linux GUI 후속, 원호/IFA, 내부 검증 배포와 60/30 fps 초기 목표를 유지한다. 이번 작업은 표현식/실제 설계 데이터, 개발 환경 구성과 최소 GUI를 병행하는 범위다.

## 구현 현황

| 항목 | 구현과 증거 | 남은 범위 |
| --- | --- | --- |
| 단위와 정규 직렬화 | SI Quantity, 미정 상태, 출처, 제한 JSON codec/hash | 복소수, 불확도, 충돌 후보, 물리 cache subset |
| 표현식 | 전용 parser, 차원/정의역 검사, UUID bindings, 의존 그래프 재계산, 순환 차단 | 다른 OS 수학 라이브러리의 계산 캐시 호환 검증 |
| 실제 설계 데이터 | 기판, 적층, 재료, net, 선/원호, 단일 lumped port. 참조 무결성과 역명령 | 패드/비아/polygon, 실제 접속 판정, CAD 형상 |
| 목적별 입력 검사 | API-006 draft revision의 geometry/step/em, 고정 입력 TaskRef, 누락 진단 | snapshot 입력, 제조/물리 profile, solver 지원 검증 |
| 명령/저장/스냅샷 | revision/receipt 원자 게시, 재시작, crash 경계. 0.1 읽기 및 새 개정 0.2 전환 | 사용자 undo/redo, 독립 archive/import, GC, 정전 내구성 |
| Python 환경 | 서비스 .venv와 별도 .venv-cad, 44개 CAD 패키지 버전/wheel SHA256 고정 | 배포 패키지와 전체 라이선스 검증 |
| CAD 환경 smoke | CadQuery 2.8.0/OCP 7.9.3.1.1 박스 STEP export/reimport 통과 | 제품 CAD adapter, AP242, 독립 수신 CAD, IFA/원호 |
| 최소 GUI | C++ wxMSW, 트리/이름/설명, 생성/열기/저장/스냅샷, 별도 서비스 통신 | 설계 속성 편집, 2D/3D viewport, 전체 앱 성능 측정 |
| WSL/openEMS 환경 | WSL 2.7.11.0 탐지, 재개 스크립트와 미완료 상태 기록 | 재부팅 후 전용 배포, Qt 없는 headless 의존성, solver smoke |

서비스는 rfad.api/2.0, workspace profile은 rfad.projects/0.2, 새 문서는 rfad.project/0.2다. 세부 계약은 [저장](project_persistence.md), [설계 데이터](design_data.md), [기초 계약](bootstrap_contract.md)을 따른다. 전체 API나 R0/R1 완료를 주장하지 않는다.

## 개발 환경 결과

- Windows 11 AMD64, CPython 3.12.10, Intel Core i7-1365U, 약 32 GiB RAM에서 확인했다.
- CMake 4.3.2, Ninja 1.13.2, MinGW-w64 g++ 16.1.0 UCRT/MCF를 사용한다. MSVC는 현재 PATH에 없다.
- wxWidgets 3.2.12와 nlohmann/json 3.12.0 소스는 공식 배포에서 받아 SHA256을 확인했다. Qt 또는 유료 GUI 부품을 요구하지 않는다.
- 서비스 환경은 pip/setuptools/tracewave-studio이며 CAD/OCP/NumPy/SciPy/VTK/Qt를 import하지 않는다.
- CAD 환경은 전체 고정 의존성 설치와 pip check를 통과했다. Qt 배포/DLL/로딩 모듈이 없다. 박스 10 x 20 x 1.6 mm를 STEP AP214로 저장/재입력하여 유효 solid 1개, 체적 320.0000000000001 mm3를 확인했다. 같은 kernel 왕복이며 독립 CAD 검증은 아니다.
- CAD 첫 import에서 약 30초, 재실행에서 약 5.78초를 관찰했다. 시작 성능 합격 값이 아니며 GUI/서비스와 분리한 worker가 필요하다는 근거다.
- WSL 설치 요청은 Windows의 재부팅 필요 응답을 받았다. 이후 조회에서도 등록 배포가 없어 Linux 테스트와 openEMS 설치/실행은 not_run이다. 자동 재부팅이나 기존 배포 변경은 수행하지 않았다.

재현 방법과 로컬 보고서는 [Python 환경](python_environment.md), [wxWidgets](../ui/wxwidgets/README.md), [WSL 환경](wsl_environment.md)에 있다. 의존성/빌드/가상환경/호스트 경로가 담긴 보고서는 .local/build/.venv 계열에 두고 Git에서 제외한다. 개발 lock을 제품 배포 manifest로 간주하지 않는다.

## 검증 기록

Windows 전체 시험 166개가 54.105초에 통과했다. 스킵과 실패는 없다. 기존 109개에 표현식 17개, 그래프 8개, 설계 22개, 저장 통합 5개, 실제 GUI 프로세스 5개를 추가했다. 이후 GUI writer 종료 신호의 mutex 보완본을 재빌드하고 해당 GUI 5개를 다시 실행하여 모두 통과했다(16.342초).

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_GUI_EXE = (Join-Path (Get-Location).Path 'build/windows-release/bin/tracewave_gui.exe')
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

GUI 실행 파일을 지정하지 않으면 GUI 시험 5개는 스킵된다. 전체 로그는 `.local/all-tests.log`, CAD 근거는 `.local/python/cad-smoke.json`, WSL 상태는 `.local/wsl/status.json`에 있다.

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

60/30 fps, 전체 프로세스 메모리/최초 실행 예산, Linux, openEMS 계산, 수렴/정확도, 실측은 아직 검증하지 않았다. CAD 환경 smoke를 제품 CAD adapter 구현 완료로 확대하지 않는다.

## 다음 구현

재부팅 직후 실행할 명령과 단계별 완료 기준은 [재부팅 후 개발 재개](reboot_resume.md)를 따른다.

1. 재부팅 후 WSL 전용 개발 배포를 준비하고 Linux 서비스 회귀 시험 및 headless openEMS 환경 smoke를 수행한다.
2. 설계 데이터를 표시/편집하는 GUI DTO와 속성 입력, 사용자 undo/redo, 2D 선/원호 편집을 연결한다.
3. 격리 CAD worker, 명시적 단위/좌표/적층 변환, 구리 형상과 STEP 출력을 연결한다. 급전/접속 검증과 독립 재열기 증거를 추가한다.
4. 승인 순서대로 완전한 참조 계산, 단일 포트 IFA, 원호의 openEMS 모델과 NF2FF 결과를 검증한다.
5. 사용자 보드 입력, 실제 재료/제작/측정 조건과 성능 예산을 검증하고 내부 검증 패키지로 묶는다.

GUI와 자동화는 같은 서비스를 공유한다. MCP 서버 자체, 다른 EDA의 의미 mapping과 실제 solver 실행은 후속이다. 물성은 사용자 입력이며 임의 FR4 대표값으로 대체하지 않는다. 초기 IFA 1 mm 완성 두께에서 구리 두께를 뺀 잔여값을 실제 코어 두께 확정값으로 취급하지 않는다.
