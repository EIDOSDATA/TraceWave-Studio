# 재부팅 후 개발 재개

최초 기록일: 2026-11-07 KST

상태 갱신일: 2026-11-12 KST

작업 영역은 `C:/Users/eidos/GitHub/TraceWave Studio/Code`, 설계 기준선은 RFAD-D0-3.4다. 이 문서는 이번 구현 다음 작업의 순서와 완료 기준을 정리한다. Windows 재부팅과 Linux 설치를 자동으로 수행하는 문서가 아니다.

2026-11-10에 재부팅 후 전용 배포 설치와 Linux 서비스/표현식 검증을 완료했다. 이어 Qt 없는 openEMS/CSXCAD/VTK 빌드와 작은 도파관의 두 격자 참조 검사도 통과했다. 이후 wxAUI 작업 공간, 기판/미정 도체층/선/원호 생성, 2D 직접 편집과 문제 위치 이동을 연결했다. 2D 경계 보완본의 Windows 전체 227개가 76.152초에 통과했고 Linux는 220개 통과/Windows GUI 7개 스킵으로 30.312초였다. native CTest 1개도 0.13초에 통과했다. 이 수치는 당시 2D 버전의 기록이며 도구막대/DPI 보완 및 최신 전체 결과는 [개발 상태](development_status.md)를 따른다.

다음 단계로 별도 호스트 CAD worker, Open CASCADE 유전체/선/원호 고체와 AP242 STEP/B-rep 출력을 연결했다. 이어 GUI STEP 출력/취소/완료 결과 복원, 유전체층 생성과 wxGLCanvas 3D 보기를 구현했다. 원본 sidecar와 실제 schema/단위/이름/형상 재입력은 같은 kernel이며 내부 기하 profile은 `generated_unverified`다. WSL solver worker의 준비/실행/취소/저장과 도파관 두 격자 검증까지 연결했다. 이어 사각/원형 PCB의 사용자 물성/패턴/동일 평면 단일 급전과 GUI 해석/취소/결과 그래프, 재료/net/포트 생성 UI를 연결했다.

이후 구멍을 가진 접지 polygon, 원형/회전 사각 pad, 명시적 중공 관통 PTH via와 IFA의 접지/급전선/단락부를 원본/GUI/CAD/EM에 연결했다. 단일 포트는 동일 sheet 면의 x/y gap과 층 사이 z gap을 지원한다. 고정 IFA fixture의 격자/경계 거리/시간 종료 연구를 실제 실행했고, 1.6~2.6 GHz의 별도 연구에서 초기 기준의 수치 안정성을 확인했다. 현재 우선 작업은 실제 물성/급전/측정 조건과 2.4 GHz 정합 설계, 국부 특징/곡선/PML 및 사용자 PCB 방사의 수렴, GUI 다중 곡선 비교와 독립 수신 CAD 검증이다. NF2FF 기록/후처리/2D 조회는 연결했다. 실물 SMA launch/정합 부품의 기생 효과는 아직 포함하지 않았다. 2D 스냅/치수/endpoint, 3D LOD와 실제 GPU reset/DPI/도킹 복구 및 성능 실측도 남는다. 아래 첫 작업은 새 PC나 배포 미등록 상태에서의 재개 절차로 유지한다. Linux 근거는 [Linux 환경](linux_environment.md), CAD 범위는 [CAD/STEP 계약](cad_contract.md), 도체 모델은 [도체와 IFA 확장](copper_features.md)에 있다.

코드 구조 정리에서는 주 창 진입점, 화면별 이벤트 연결, 순수 표시/작업 상태와 통합 시험을 분리했다. 프로젝트 서비스와 CAD/solver도 책임별 모듈로 분리했으며 공개 API/저장 schema는 유지한다. 새 기능을 추가할 위치와 검증 규칙은 [코드 구조](code_structure.md)를 먼저 확인한다. 최신 회귀 결과는 [개발 상태](development_status.md)에 기록한다.

2026-11-11 추가 자료 정리: `00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026`의 57,340개 관측과 공식 원문을 정리하고 회사별 엑셀을 제공했다. [PCB 재료 카탈로그 설계](pcb_material_catalog.md)에 직접 입력/소재/제조업체 선택, 구조화 출처와 원자적 적층 적용 순서를 기록했다. 이 작업은 자료와 설계 문서에 한정했으며 제품 코드/프로젝트 schema/solver 입력은 변경하지 않았다. 카탈로그 기능 구현을 시작할 때 이 문서와 자료의 검토 사유를 먼저 확인한다.

PCB 선택 기능은 카탈로그 SQLite 조회에 이어 선택 출처/사용자 수정값 저장, 업체별 적층 초안과 원자적 적용/undo까지 서비스 API로 구현했다. [PCB 선택 계약](pcb_selection_contract.md)의 stdio 예제와 `tools/verify_pcb_selection.py`로 확인할 수 있다. [카탈로그 조회 계약](pcb_catalog_contract.md)의 명령으로 `.local/pcb-catalog/catalog.sqlite` 상태를 확인한다. 새 checkout에는 DB가 없으므로 원문 패키지로 build를 실행한다. 이번 선택 API 추가는 DB schema/import 버전을 변경하지 않으므로 정상 DB는 재구축할 필요가 없다. wxWidgets의 직접 입력/소재/제조업체 선택과 단면/변경 미리보기를 연결했다. [화면 사용법](pcb_selection_gui.md)에 따라 GUI를 재빌드하고 실행한다. CAD/solver 통합 검증의 현재 결과와 JLC 미정 입력은 아래 추가 기록을 따른다.

2026-11-11의 이전 카탈로그 통합에서는 JLC0206 계산기 후보의 CAD/STEP/mesh와 worker 없는 재열기를 통과했고, 실제 RF 물성의 미정 9개 입력은 보존하여 EM을 `needs_inputs`로 차단했다. 이 과거 기록과 별도 시험 물성 IFA의 양성 대조군은 그대로 유지한다. 재현 방법과 증거 구분은 [카탈로그 PCB 통합 검증](catalog_pcb_integration.md)을 따른다.

이후 [JLC RO4350B 제작 후보](jlc_manufacturing_selection.md)를 조사하고 사용자가 허용한 별도 탐색 모델로 CAD/STEP/openEMS/재후처리/결과 재열기 전체 경로를 통과했다. Design Dk 3.66과 Df 0.0031은 원문 주파수가 다른 근사 입력이고, 58 MS/m는 JLC 실측값이 아닌 20 C IACS 기준 구리다. 실제 납품 재료 2개의 물성과 대역은 미정으로 보존한다. [손실 모델](material_loss_models.md)과 [실행 기록](../runtime_profiles/jlc-ro4350b-exploratory.json)을 먼저 읽고 다음 작업을 시작한다. 완료한 통합 경로를 다시 최초 구현하는 단계가 아니다.

RO4350B 구현 시점의 Windows 전체 회귀는 685개 수집/618개 통과/67개 스킵/실패 0, 364.510초다. GUI 선택 3개는 33.525초, 총 Df native 대조군 1개는 169.218초에 별도로 통과했다. RO4350B 전체 통합은 136.734초, native 격자점 639,693개/4,805 steps/에너지 감소 42.08 dB/51개 표본이며 원본 불변을 확인했다. 제조/측정 및 이 새 모델의 격자/경계 수렴은 미검증이다. 상세 범위와 로그는 [개발 상태](development_status.md#jlc-ro4350b-탐색-모델과-전체-경로-검증-2026-11-11)를 따른다.

이후 제조업체 적층을 선택하면 같은 원문 층의 두께/Dk/Df를 함께 제안하는 서비스와 GUI를 추가했다. [화면 사용법](pcb_selection_gui.md)의 `선택 적층과 물성 제안 보기` 및 `선택 제안 사용`을 사용한다. 제안은 페이지별로 검토하며 기존 직접 입력과 연결된 재료를 덮어쓰지 않는다. JLCPCB/PCBWay의 미제공 Df는 미정으로 표시하고, 범위/한정자와 실제 입력값을 구분한다. 모델 적용 대역은 사용자가 명시한다. 전체 자료 3409개 후보의 5146개 페이지 검사와 대표 JLC 2층/OSH 2층의 적용/재열기를 확인했다. 기존 근거 예산으로 조회가 거절되는 823개 및 대표 다층의 전체 물성 동시 채택 제한을 보존하며, 최신 시험/범위는 [개발 상태](development_status.md#제조업체-적층과-dkdf-함께-제안-2026-11-11)를 따른다.

적층 물성 제안 구현 후 최신 Windows 전체 회귀는 705개 수집/638개 통과/67개 스킵/실패 0, 285.222초다. 최종 제안 API/저장 집중 시험 13개는 11.140초에 통과했다. 최종 Release 빌드 후 wxWidgets 선택 프로세스 시험 3개는 23.429초, CTest 6개는 0.32초에 통과했다. 스킵된 native/GUI 시험을 실행 성공으로 합산하지 않으며 별도 실제 GUI 근거와 정확한 소스/로그는 [적층 제안 검증 기록](../runtime_profiles/stackup-suggestions.json)을 확인한다. 자동 시험 통과와 수동 시각 수용 범위는 구분한다.

## 최초 재부팅 전 저장한 상태

- 표현식/의존 그래프, 초기 설계 데이터, 프로젝트 명령/저장/스냅샷과 목적별 입력 검사를 구현했다.
- 최소 wxWidgets GUI와 별도 Python 서비스 연결, Windows 빌드/실행 도우미를 구현했다.
- 서비스 `.venv`와 CAD `.venv-cad`를 분리했다. CadQuery/OCCT의 박스 STEP 왕복을 확인했다.
- Windows 전체 시험 166개 통과. 이후 GUI 종료 처리 보완본의 관련 5개 시험도 다시 통과했다.
- 당시 WSL 설치 요청은 Windows 재부팅 필요 응답을 받았고 등록된 Linux 배포가 없었다. 이 과거 상태의 Linux/openEMS 설치는 2026-11-10에 해소했다.

소스, 시험, 의존성 버전/해시, 설치 스크립트와 문서는 Git으로 관리한다. `.venv`, `.venv-cad`, `.local`, `build`는 로컬에 보존되지만 Git에는 포함하지 않는다. 따라서 같은 PC에서는 재부팅 후 기존 환경을 사용할 수 있고, 새 checkout에서는 설치/빌드 스크립트로 다시 구성해야 한다.

## 재부팅 직후 첫 작업

Windows 재부팅을 마친 뒤 PowerShell 7에서 다음으로 시작한다.

```powershell
Set-Location -LiteralPath 'C:\Users\eidos\GitHub\TraceWave Studio\Code'
pwsh -NoProfile -File .\tools\setup_wsl.ps1
```

이 명령은 전용 배포 `TraceWave-Dev`의 등록 여부와 실행 가능 여부를 확인한다. 배포가 없어서 종료 코드 2가 나오면 다음으로 설치를 한 번 재개한다.

```powershell
pwsh -NoProfile -File .\tools\setup_wsl.ps1 -Install
```

관리자 권한이 필요하다는 Windows 응답이 나오면 관리자 PowerShell에서 해당 설치 단계를 수행한다. 설치 경로가 이미 존재하지만 배포가 등록되지 않은 경우에는 경로의 상태를 먼저 확인한다. 스크립트는 기존 디렉터리를 삭제하거나 덮어쓰지 않는다.

완료 기준은 Ubuntu 24.04가 WSL2에서 실제 실행되고 스크립트가 종료 코드 0을 반환하는 것이다. 설치 프로그램의 종료 코드 0만으로 성공을 판단하지 않는다. `.local/wsl/status.json`의 registered/runnable과 상태를 확인한다. 여기까지 완료해도 openEMS 준비 완료는 아니다. 자세한 조건은 [WSL 환경](wsl_environment.md)을 따른다.

이번 총 Df native 대조군의 최초 준비는 WSL cold boot의 10초 start control timeout으로 실패했다. WSL 예열과 제한 시간이 있는 keepalive 뒤 재실행은 통과했지만 자동 복구는 아직 구현하지 않았다. 재부팅 후 solver를 실행하기 전 배포가 실제 응답하는지 확인하고, 같은 실패가 발생하면 원래 실패/작업 상태를 보존한다. 단순 재시도로 이전 작업의 실행 여부를 덮어쓰지 않는다. 이후 접수 전 60초 준비/취소와 not_started 구분을 보강했다. 아래 최신 표의 실제 PC cold boot 수용 항목을 따른다.

## 이어서 진행할 순서

전체 제품의 작업 순서는 [개발 완료 계획](completion_plan.md)의 1~13단계를 단일 기준으로 사용한다. 이전 7/8단계 권장 목록은 그 문서로 대체했다. 이 문서는 재부팅/환경 확인과 과거 실행 근거를 제공하며 별도의 후속 순서를 정하지 않는다. 원본 매개변수/출처의 연구 GUI에 이어 중복 없는 체적/sheet/PTH 손실, 개별 성분 기준과 네 수치 축 연구를 추가했다. WSL 제어 읽기 경합과 큰 raw 필드 검증/재후처리 전달도 보완했다. 완료된 고정 CLI 연구는 보존하고 단순 확인에는 `--reassess-only`를 사용한다. 과거 필드가 없는 연구에 손실을 보완하지 않는다.

직전 [손실 실행 기록](../runtime_profiles/pcb-loss-precision.json)에서 RO4350B는 9개 고유 조건 중 8개 완료, 도체의 마지막 격자 변화 3.430551%와 국부 4분할의 300초 중단으로 전체 미확립이었다. 구리 PTH fixture의 3수준은 초기 성분/전력 예산을 통과했으나 GHz skin depth 정확도는 미확립이다. 개발 중 폐기한 sheet 차감 방식의 원본 결과와 수정 재계산은 별개이며, 새 계산기 identity가 원래 FDTD identity와 같다고 표시하지 않는다. 재계산 CLI는 새 출력 경로만 허용한다.

이후 [RO4350B 후속 손실 연구](ro4350b_loss_refinement.md)에서 표준 2400000 격자점/900초와 심화 3000000/1800초의 명시적 profile, 상위 대기와 단일 Box 배열 가속을 추가했다. 기본 1500000/300초/2스레드는 유지한다. 0.30/0.28 mm의 마지막 도체 합계 변화 0.262782%와 격자 축의 모든 개별 성분이 초기 기준을 충족했다. 국부 4/5/6분할은 개별 기준 미확립이며 심화 6/7/8분할도 실행 완료 뒤 방사 도체 최대 2.788446%로 전체 미확립이다. 7/8분할 도체 합계 1.042424%나 최대 전력 잔차 0.213135%만으로 개별 손실을 합격시키지 않는다. 최종 판정/소스/원시 해시는 [최신 실행 기록](../runtime_profiles/ro4350b-loss-refinement.json)을 먼저 확인한다. 6분할 raw 재사용에는 source/snapshot/물리 case/설치와 실제 준비 XML 바이트의 같음을 검증했고 원래 생산자 ID를 보존한다. 실제 제작/측정 미정값도 유지한다.

완료 계획 2번의 [구현 대조](implementation_audit.md)와 [공통 계약](shared_contracts.md)을 정리했다. 3번의 첫 범위인 [목표 대역 입력](target_contract.md)의 저장/명령/0.3 쓰기와 0.1/0.2 원본 보존을 구현했다. 4번은 공통 라이트 스타일/도킹/간격/도구 줄바꿈을 먼저 적용했으며 [GUI 설계](studio_gui_design.md)의 v2 시안 전체를 구현한 것은 아니다. 목표/출처 계약과 Studio 기반까지 1ed9686b8eea5cec3b17931d8655565fbafc72e2로 커밋/푸시한 뒤 [명시 치수 템플릿](template_contract.md)과 [다중 목표 편집 GUI](target_template_gui.md)를 연결했다. 이후 문헌 원본 카드/초기 합성/설계 의미/정밀 편집, 공통 결과/기본 회로/측정 파일, 연구/스윕, 결과 GUI, RF 검증과 목표 설계, 도면/CAM/측정, 전체 UX/성능/복구와 배포를 같은 순서로 연결한다. 미확립 손실과 GHz PTH 검증은 8번의 집중 검증에서 추적하며, 실제 제작/측정 데이터는 임의로 채우지 않는다.

실제 제조업체 승인 적층/납품 물성/동박/마스크/표면처리와 SMA/케이블/교정 기준면, 시료 및 측정 불확도는 자료 확보 후 별도 확정한다. 위 소프트웨어 개발을 위해 미정 항목을 임의 제조값으로 채우지 않는다.

아래 번호는 과거에 지시받아 수행한 용량 개선 1~9번의 기록이며 앞으로의 개발 순서가 아니다.

| 과거 작업 번호 | 현재 구현과 검증 | 남은 수용 항목 |
| --- | --- | --- |
| 1 | 출처 공유 풀, 구형 0.1 읽기, 512 KiB 프로젝트/128 KiB 고유 근거 및 GUI 전송 경계 구현 | 바이트 상한은 유한하게 유지. 더 큰 제품 장면은 별도 계측 |
| 2 | 823개를 포함한 3409개 조회 제한/오류 0, JLC/PCBWay 4층의 전체 제안 적용/저장/재열기 통과 | 다층 CAD/EM의 개별 물리 지원을 자동 확대하지 않음 |
| 3 | WSL 접수 전 60초 준비/취소, not_started 구분 및 실제 접속/종료/재접속 시험 통과 | 실제 PC cold boot와 자동 복구의 추가 수용 시험 |
| 4 | RO4350B 공식 제작 표 재확인, 근사와 미정 납품 입력 구분 | 제조업체 승인 적층, 주문별 물성/동박/마스크, SMA 및 실제 시료/교정 자료 필요 |
| 5 | RO4350B 목표 대역의 8개 사례/6개 고유 계산과 판정 완료 | 복소 S 변화는 충족했으나 내부 공진 없어 전체 수렴 미확립. 정합 조정/공진 추적과 실측 대조 필요 |
| 6 | 완료 수렴 보고서 비교와 일반 프로젝트의 격자/방사/손실 연구 GUI, 취소/명시적 재개와 전력 표시 | 3축 행렬 편집, 다중 곡선 중첩, 추가 스냅/치수/endpoint, 3D LOD/GPU reset/DPI/도킹 복구 수용 |
| 7 | NF2FF/고정 방사 연구, QuarterCell 유전체/PTH/sheet 독립 손실과 개별 성분 비교, 원본 매개변수/출처 보존 | 미확립 손실 축의 국부 정밀도/비용, GHz PTH skin depth, 3D 방사 곡면, 독립 solver/실측 대조 |
| 8 | 제품 2D renderer 계측/Clip/Flush와 연속 pen 재사용, 내부 소스/GUI 검증 묶음 생성 도구. 최신 3000개 합성 장면 p95 25.060 ms | 실제 조작 시 60/30 fps와 전체 GUI/서비스/worker 메모리 수용, 배포/라이선스 점검. 단일 합성 측정을 제품 FPS 합격으로 확대하지 않음 |
| 9 | MCP 2025-11-25 stdio 도구 발견/공개 API 전달/영수증 재생/실제 프로세스 시험 | 특정 EDA의 단위/좌표/net/port 변환 및 실제 상호 운용 시험 |

이번 결과와 실행 명령, 한계는 [용량 개선과 후속 검증](capacity_and_followup.md)을 따른다. 기존 823개 거절과 대표 4층 적용 제한은 해소했으며, 1번을 미구현 과제로 다시 시작하지 않는다. 공유 형식은 원문을 축약하거나 외부 카탈로그에 의존하지 않는다.

추가 구현한 [PCB 방사 계산](pcb_radiation.md)과 [독립 전력 수지](pcb_power_balance.md)의 고정 기록은 당시 결과로 보존한다. 이후 [일반 프로젝트 연구 GUI](project_studies.md)는 최종 worker 117개 소스와 실제 RO4350B 3개 격자/3개 주파수, 취소/재개/프로그램 재연결을 통과했다. 현재 Windows 회귀는 766개 중 691개 통과/75개 조건부 제외이며 GUI 회귀 14개 통과/4개 조건부 제외, 관련 계약 50개와 CTest 9개도 통과했다. 별도 실제 WSL 실행 중 서비스 종료/명시적 재개 1개도 완료 준비를 재사용했다. 최대 에너지 잔차는 0.191734%이고 포트 공진 수렴은 미확립이다. 후속은 손실 정밀도/PTH, 3축 연구 GUI 행렬과 정합 설계 순서다. 실제 납품 적층/물성/제작/측정 자료가 필요한 항목은 계속 미정이며 계산 fixture로 대체하지 않는다.

위 표는 1~9번의 구현 결과와 남은 수용 범위다. Linux 환경과 작은 참조 사례, 편집/CAD/GUI STEP/3D, 사용자 PCB 실행 및 RO4350B 탐색 모델의 전체 연결은 이미 확인했다. CAD 실행은 WSL을 사용하지 않으며 solver는 별도 [WSL guest 구현](solver_contract.md)을 사용한다. 환경이 준비된 PC에서는 설치보다 최신 소스/빌드/검증 상태를 먼저 확인한다. 탐색 결과는 `computed_unvalidated`이며 시간영역 종료를 정식 격자/경계 수렴이나 제조/실측 검증으로 승격하지 않는다. Linux GUI는 후속 범위를 유지한다.

현재 2D 캔버스는 두 번 클릭한 선분, 중심/시작/끝 방향을 지정하는 원호와 Shift CW, 드래그 이동, 삭제, Esc 취소, fit/휠 확대/가운데 버튼 이동을 제공한다. 정확한 좌표/반지름/각도는 `좌표 입력`을 사용한다. 그리드 표시는 마우스 스냅이 아니며 물리 원본을 바꾸지 않는다. [2D 표시/편집 계약](canvas_contract.md)과 [GUI 조작](../ui/wxwidgets/README.md)을 참고한다.

polygon은 첫 loop를 외곽, 빈 줄 이후 loop를 빈 영역으로 입력하고 속성의 coordinate_table에서 숫자/미정/매개변수 결합을 편집한다. 좌표 셀의 unit은 보통 mm이며 환산 overflow가 나는 유한 원본은 m로 표시한다. unit은 읽기 전용이고 선택지는 coordinate_choices에서 공유한다. 바꾸지 않은 셀의 단위/출처/결합은 보존한다. via는 시작/끝 도체층과 연결 pad를 명시하며 pad_ids는 다중 선택한다. 미정 구멍/도금은 저장할 수 있지만 실제 지름을 그리거나 계산에 사용할 때 임의값을 채우지 않는다.

Linux 시험에서는 현재 표현식 캐시의 정확한 재평가 일치가 다른 OS 수학 라이브러리에서도 유지되는지 확인한다. 차이가 발생하면 기존 스냅샷을 조용히 다시 쓰지 않고 엔진/런타임 호환 정책과 명시적 전환 규칙을 먼저 정한다.

초기 IFA의 목표 대역/크기/두께는 승인 기준을 사용한다. 실제 유전율/손실/전도도, 제작 적층과 마스크, 급전/측정 조건은 후속 입력으로 확정한다. 미정 물성을 임의 FR4 상수로 채우지 않으며, 0.93 mm 잔여 두께를 실제 코어 두께 확정값으로 간주하지 않는다.

별도 IFA/PTH 실행 fixture에는 재현을 위한 물성/치수 가정을 명시한다. 이를 승인된 초기 입력의 미정 물성에 복사하거나 기본 제조값으로 사용하지 않는다. 현재 IFA fixture는 이상적인 로컬 안테나 gap을 기준면으로 사용하므로 실물 SMA 접속면, 마스크, 정합 부품/케이블과 측정 디임베딩을 추가로 확정해야 한다.

이번 [IFA 수렴 계약](ifa_convergence.md)은 mesh 최소 3수준, 마지막 복소 S 변화 0.02 이하와 동일 branch 공진 변화 1% 이하를 fixture 전용 acceptance로 사전 채택한다. 최초 study는 2~3 GHz 201점/손실 환산 중심 2.5 GHz를 사용하고, 별도 반사 최소점 study는 1.6~2.6 GHz 201점/중심 2.1 GHz를 사용한다. 두 연구는 서로 다른 입력과 보고서를 유지한다. band 끝의 최소값이나 공진 부재는 공진 수렴으로 판정하지 않는다. 어느 study도 목표 끝 2.4835 GHz를 평가하지 않으므로 이 결과만으로 전 대역 정합 합격을 선언하지 않는다. 두 study의 graded air는 kind=graded_air/air_cell_mm=6/growth_ratio=1.5, 말단 PML8의 두께는 48 mm다. 내부 임계선 전체에 성장률 상한을 강제하지 않으므로 metadata의 실제 축별 비율도 확인한다. matrix/자원 검사와 실제 판정은 해당 계약과 개발 상태를 먼저 확인한다.

이 수렴 비교는 고정 격자 생성 정책의 설정 series를 평가한다. grid_mm을 줄여도 모든 짧은 임계 구간이 함께 세분화되지는 않으므로 국부 최소 특징 전체의 수렴이나 Richardson/점근 정확도를 주장하지 않는다. 현재 study는 CLI/JSON/CSV로 사용하며 GUI의 여러 run 비교/행렬 관리 화면은 후속 작업이다.

## 기존 Windows 환경을 확인할 때

GUI 실행:

```powershell
.\tools\launch_gui.ps1
```

설치된 `.venv-cad`는 실행 도우미가 자동으로 연결한다. 다른 CAD Python은 `-CadPython <경로>`로 지정한다. 기본 CAD 환경이 없으면 편집/저장과 기존 완료 mesh 조회는 가능하고 새 STEP/3D 생성은 비활성화된다. 이번 GUI는 wx gl/opengl32/bcrypt를 사용하므로 이전 2D 실행 파일을 새 소스의 빌드 증거로 사용하지 않는다. native 코드를 바꿨다면 [wxWidgets 빌드](../ui/wxwidgets/README.md#개발-환경과-빌드)부터 수행한다.

Windows 코드나 native 환경을 변경한 뒤 전체 시험이 필요할 때:

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_GUI_EXE = (Join-Path (Get-Location).Path 'build/windows-release/bin/tracewave_gui.exe')
$env:RFAD_CAD_PYTHON = (Resolve-Path '.venv-cad/Scripts/python.exe').Path
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv-cad\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_cad_native.py -v
ctest --preset windows-release
```

서비스 가상환경의 전체 시험은 CAD 패키지를 import하지 않으므로 native 기하 시험은 위 두 번째 환경에서 별도로 실행한다. `RFAD_CAD_PYTHON`이 없으면 실제 서비스-CAD 프로세스 통합 시험은 스킵된다. 고정 CadQuery 2.8.0/cadquery-ocp 7.9.3.1.1 환경은 [Python 환경](python_environment.md)을 따른다.

GUI에서 `유전체층`과 도체층을 만들고 속성에서 실제 z 위치/두께를 입력한 뒤 `STEP 출력` 또는 `3D 갱신`을 누른다. 입력은 snapshot으로 고정되며 실행 중 편집/저장을 계속할 수 있다. 하단 `CAD 출력`에서 취소/결과 경로/출력 폴더를 확인한다. 생성된 3D가 현재 개정과 다르면 이전 설계로 표시되며 재열기는 마지막 게시 완료 결과를 복원한다. 출력에는 명시적 유전체 층과 기하 치수가 필요하며 미정 RF 물성은 원본 그대로 보존한다.

자동화용 [개발 CLI](../README.md#현재-실행-방법)의 `tools/export_step.py`도 유지한다. CLI를 별도로 실행할 때는 GUI 입력을 적용/저장하고 같은 workspace의 GUI/서비스를 닫는다. `export.preview`, `geometry.build`, `export.build`는 같은 불변 snapshot을 기준으로 하는 비동기 API다. 접수 때 runtime/소스 묶음을 고정하므로 서비스 실행 중 Python 소스를 바꾸면 새 서비스를 시작하고 새 작업으로 검증한다. 결과 cache를 재사용하지 않는다.

서비스 비정상 종료 후 CAD 작업이 `outcome_unknown`으로 남으면 해당 슬롯 예약을 유지한다. 자동 재실행이나 PID만을 보고 강제 정리하지 않는다. 현재 공개 수동 조정 API는 없으며 기존 편집/저장/조회는 계속 사용할 수 있다. 복구와 미게시 staging의 의미는 [worker 연결 경계](worker_integration.md)를 따른다.

재부팅 자체만으로 기존 가상환경을 삭제하거나 모든 의존성을 재설치할 필요는 없다. 환경을 새로 구성해야 할 때는 [Python 환경](python_environment.md), [wxWidgets 빌드](../ui/wxwidgets/README.md)의 절차를 따른다. 현재 구현과 미검증 범위의 상세 기록은 [개발 상태](development_status.md)에 있다.

WSL solver 재검증은 [해석 worker 계약](solver_contract.md)의 `verify_openems_worker.py`를 새 workspace/report 경로로 실행한다. 이전 실행이 interrupted/outcome_unknown이면 동일 runtime의 `--reconcile-job`으로 guest 종료를 확인하며 새 실행으로 대체하지 않는다. 결과는 solver 환경 없이도 등록된 workspace의 `result.open`으로 조회할 수 있다. 사용자 PCB 실행은 [PCB 계약](pcb_solver_contract.md)의 `verify_pcb_worker.py`로 별도 검증하며 `--fixture`로 원형 선/원호, IFA 급전 또는 PTH 사례를 선택한다. GUI 해석은 `launch_gui.ps1 -OpenEmsWsl`로 활성화한다. 현재 고정 IFA study의 완료 근거를 보존한 뒤 실제 물성/급전 조건, 목표 대역 설계와 남은 국부/PML 검증을 진행하고 원형 PCB/원호와 NF2FF로 확장한다. 독립 수신 CAD의 STEP 확인도 병행한다.

IFA study 전용 `tools/verify_ifa_convergence.py`는 기본값으로 [최초 2~3 GHz manifest](../fixtures/ifa_convergence_study.json)를 사용한다. 각 study의 8개 비교 행을 6개 고유 실행으로 처리하며 먼저 모든 plan을 봉인/검증하고 실제 계산을 시작한다. `--resume`은 기존 요청과 완료 자료를 같은 worker identity에서 이어 쓰며 `--reassess-only`는 solver 환경 없이 완료 결과만 재판정한다. 정확한 명령과 종료 코드 0/1/2는 [실행 계약](ifa_convergence.md#실행-재개와-원본-보존)을 따른다. 진행 report와 파생 CSV는 갱신 가능하지만 raw/plan/result 및 `report.assessments/<UUID>.json`의 이전 판정은 immutable이다. 실행 실패/취소와 미평가 공진을 정상 수렴으로 바꾸지 않는다.

공진 대역의 [별도 study](../fixtures/ifa_convergence_resonance_study.json)를 재개할 때는 `--study fixtures/ifa_convergence_resonance_study.json`과 그 연구의 workspace/report를 지정한다. 이 연구는 1.6~2.6 GHz/중심 2.1 GHz의 별도 입력이다. 최초 2~3 GHz/중심 2.5 GHz 연구와 손실 환산/여기가 달라 결과를 섞거나 기존 보고서를 대체하지 않는다. 먼저 각 연구의 완료 상태와 판정 근거를 읽고 남은 작업만 진행한다.

제품 소스 묶음의 판정기만 보완해도 code_files hash가 달라지므로 이전 연구에 현재 checkout의 `--resume`을 적용하면 거절될 수 있다. 완료 자료의 재평가는 `--reassess-only`를 사용하며 실제 FDTD를 추가하지 않는다. 이전 실행의 정확한 재개에는 캡처 당시 소스/설치 identity가 필요하고 현재 소스로 새 native 계산을 하려면 새 workspace/report를 사용한다. 원래 계산 소스와 후속 판정기 소스를 각각 보존한다.

최초 study의 6개 native 실행은 완료했다. 마지막 복소 S11 변화는 격자/경계/종료 세 축 모두 기준 안이지만 2.0 GHz 대역 끝이 표본 최소값이라 내부 반사 최소점 추적은 미평가이며 전체는 `not_established`다. 실제 재판정/재개에서도 결과 참조/CSV가 같고 새 FDTD가 없음을 확인했다. [최초 연구 결과](ifa_convergence.md#최초-2030-ghz-연구의-실제-결과)를 보존하고 별도 공진 대역 연구의 진행 상태를 확인한다. S11 dip과 X=Im(Z)=0의 전기적 공진을 같은 정의로 취급하지 않는다.

별도 1.6~2.6 GHz 연구의 6개 실행도 완료했고 격자/경계/시간 종료의 최종 비교와 전체가 `established`다. 반사 최소점은 표본 1.920 GHz, bracket [1.915, 1.925] GHz이며 보수적 이동 상한이 1% 이하다. 이 결과는 고정 fixture의 수치 안정성이고 2.4 GHz 정합 목표나 실측 합격이 아니다. [별도 연구 결과](ifa_convergence.md#별도-1626-ghz-연구의-실제-결과)와 [runtime 기록](../runtime_profiles/ifa-convergence-wsl.json)을 확인하고, 완료 연구의 자동 재실행보다 남은 실제 입력/목표 설계/GUI 비교를 우선한다.

두 연구는 실제 경계/PML 비교 가드를 추가한 최종 판정기로 다시 평가했고 추가 가드 통과 및 기존 지표/상태 보존을 확인했다. 이 재판정에는 추가 FDTD가 없으며 native 산출물/CSV/이전 판정도 유지했다. 각 폴더의 `post-guard-reassessment-evidence.json`을 확인한다. 판정기 변경으로 현재 worker source identity는 원래 실행과 다를 수 있으므로 완료 자료에는 `--reassess-only`를 사용하고, 새 native 연구는 새 workspace/report로 시작한다.

최신 [PCB 방사 수렴 연구](pcb_radiation_convergence.md)는 9개 행/7개 고유 계산에서 초기 기준의 마지막 비교가 충족됐다. 거친 설정의 실패는 유지한다. 전체 에너지 수지와 제조/측정 검증을 완료한 것은 아니다. 이 고정 연구를 자동 재실행하지 말고 완료 보고서에는 --reassess-only를 우선한다.
