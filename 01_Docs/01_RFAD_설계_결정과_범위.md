# 제품 범위와 설계 결정

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

## 1. 승인된 설계 기준선의 의미

설계 기준선 3.4는 현존 문서에 보존된 A의 137개 요구와 원본 B의 128개 요구를 병합한 승인된 구현 기준이다. 원본 A JSON 부재와 미실행 검증 조건은 그대로 기록한다. 프로젝트명은 TraceWave Studio이며 문서 식별자와 내부 namespace는 RFAD를 유지한다. 기능 요구, 구현 방침, 물리 수식, 외부 도구의 확인 사실을 서로 다른 근거로 기록한다. A/B의 범위를 전부 첫 릴리스에 구현했다거나 모든 형상에서 정확도가 검증됐다는 뜻으로 해석하지 않는다.

사용자가 채택한 R1 초기 범위는 원호/IFA 중심의 단일 포트 설계, 기판 물성/선폭/길이/동박 두께와 급전/환경의 반영, 실제 2D/STEP/CAM 출력, 기본 측정 비교와 명시적 스윕이다. EM 해석과 전력 수지/방사 검증도 R1 완료 조건으로 유지한다. UWB와 다중 포트, NFC/RFID 및 전문 모델은 데이터 구조에서 처음부터 구분하고 해당 영역의 검증을 마친 단계에 출시한다. 3.4 전체 설계 기준선은 사용자 승인 완료다. 성능/물리 정확도의 합격과 개발 착수는 별도이며 현재 제품 시험은 미실행이다.

## 2. 기준 기술 구성

| 계층 | 기준 선택 | 선택 이유와 검증 책임 |
| --- | --- | --- |
| 사용자 앱 | 사용자 선택으로 확정한 C++ wxWidgets, selected_pending_validation | R1은 Windows wxMSW, Linux wxGTK GUI는 후속 출시. wxQt를 포함한 Qt 계열 제외. 파라미터 표, 도킹 패널, 2D 편집, 작업 상태를 한 앱으로 구성. 정확한 GUI/renderer 버전과 성능은 통합 검증 후 고정 |
| 2D 편집 | 의미 있는 선, 원호, 영역 모델 + toolkit 중립 2D scene | 화면 픽셀, 삼각형 메시가 원본 도체 정의를 대신하지 않음 |
| 3D 표시 | 검증할 OpenGL/native renderer 어댑터 | 테셀레이션은 표시용 파생 데이터. 원형/곡선과 STEP의 정확도는 별도 관리 |
| CAD 생성 | CadQuery/OCCT 어댑터 | 평면 영역, extrusion, hole, assembly, STEP. 직접 OCCT 호출은 이 어댑터 안에 한정 |
| 최초 EM | openEMS + CSXCAD, 격리된 worker | 파라미터 입력에서 실행 가능한 원본 입력과 실제 결과를 남기는 경로를 우선 검증 |
| 최초 EDA | KiCad 10 계열을 초기 파일/CLI 호환 검증 대상으로 제안 | 버전별 파일/CLI profile을 고정. 이전 문서의 KiCad 9 검토 결과는 역사 근거로 보존 |
| 네트워크 처리 | NumPy/SciPy + scikit-rf 어댑터 | 복소 데이터, 정규화, 회로 연결. 라이브러리의 파 정의를 도메인 규약으로 검증해 매핑 |
| 프로젝트 원본 | 명세된 JSON + 불변 snapshot + 해시 참조 | UI, 솔버 전용 파일이 설계의 유일한 원본이 되지 않도록 함 |
| 대용량 결과 | HDF5/Touchstone + manifest | 배열, 축, 단위, 정규화, 상태 보존. SQLite는 재생성 가능한 색인과 작업 상태 용도 |
| 프로세스 간 계약 | JSON-RPC 2.0 + 버전 있는 도메인 payload | GUI, CAD worker, solver worker의 장애 격리. 대용량 값은 파일 참조로 전달 |

공식 기술 근거: [wxWidgets 구성과 성능 검증](24_RFAD_GUI_선정과_성능_설계.md), [CadQuery 소개](https://cadquery.readthedocs.io/en/latest/intro.html), [openEMS Python API](https://docs.openems.de/en/latest/python/openEMS/openEMS.html), [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html), [scikit-rf renormalize](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.Network.renormalize.html), [JSON-RPC 2.0](https://www.jsonrpc.org/specification). GUI 선택은 사용자가 확정했고, 나머지 구성은 본 설계의 판단이다. 이 조합의 설치, 호환성을 실행 검증했다는 주장은 아니다.

유료 GUI 부품을 필수 의존성으로 사용하지 않는다. 배포는 우선 내부 검증용으로 한정하고 외부 공개, 상용 배포, 소스 공개는 나중에 별도로 결정한다. 이 조건은 제품 자체의 무료 배포 결정이나 모든 유료 도구의 사용 금지를 뜻하지 않는다. 설계 기준선 3.4는 사용자 승인 완료이며 개발 착수 지시는 별도로 남는다.

## 3. 운영체제 방침

R1 첫 사용자 환경은 **Windows 11 x64 wxMSW 데스크톱 + 로컬 WSL2 Linux worker**로 확정한다. **Linux wxGTK GUI는 후속 출시**하며 출시 버전은 미정이다. Linux native/headless worker의 R0 검증은 유지하고 Windows 사용자 흐름, 한국어 경로, WSL 파일 이동, 취소, 재열기를 R1에서 검증한다. Linux GUI의 동시 출시는 R1 필수 조건이 아니다. Windows 사용자가 별도 클라우드 계정을 만들도록 하지 않는다.

Windows native openEMS 실행, macOS, GPU, 원격/HPC는 각 조합의 계약시험 후 활성화한다. OS 이름만 맞으면 지원된 것으로 표시하지 않는다. UI와 CAD worker를 host에 두고 solver만 WSL에 둘 수 있으나, 이 경우 host<->worker는 경로 문자열을 공유하는 대신 artifact ID, hash, 명시적인 경로 매핑을 사용한다. 개인 PC에 WSL이나 도구를 설치하는 행위는 별도 개발 착수 지시 이후에 다룬다.

## 4. ADR 결정 목록

| ID | 결정 | 이유, 대안, 변경 조건 |
| --- | --- | --- |
| ADR-001 | 독립 데스크톱 앱을 기준으로 하고 headless core를 분리 | 웹/FreeCAD workbench 단독 방식은 확장 후보. 오프라인, 2D/3D 동시 편집, 작업 관리 요구를 한 앱으로 충족 |
| ADR-002 | Python domain/application + 별도 C++ wxWidgets GUI client | 사용자 선택을 반영. 여러 과학/CAD 도구 연결 구조를 유지하며 계산이 UI thread를 점유하지 않게 worker 분리 |
| ADR-003 | 단일 의미 모델에서 모든 projection 생성 | STEP, Gerber, mesh를 각각 편집해 서로 다른 설계를 만드는 문제를 방지 |
| ADR-004 | SI 단위, 라디안, 오른손 좌표를 내부 기준으로 사용 | 외부 도구의 mm, mil, 축 방향 변환은 adapter 경계에서 한 번만 수행 |
| ADR-005 | RMS phasor, exp(+j*omega*t), Fourier forward exp(-j*2*pi*f*t) | peak/native 값을 무조건 나누지 않고 채널별 검증 후 변환. [수식](09_RFAD_수식과_물리_모델.md) 참조 |
| ADR-006 | 실제 물리 두께와 solver 근사를 별도 보존 | 제조용 STEP을 PEC sheet나 표시용 패드 높이로 변형하지 않음 |
| ADR-007 | openEMS 첫 backend, capability 협상 필수 | 새 solver는 같은 물리 입력과 별도 근사, 수치 오차를 보고해야 함 |
| ADR-008 | CadQuery/OCCT가 주 STEP writer | KiCad STEP는 외부 비교/선택적 export 경로. 안테나 동박, 적층 의미는 RFAD가 검수 |
| ADR-009 | KiCad 10을 첫 파일/CLI profile 후보로 고정 | 정식 lock은 실제 CLI, 파일 재열기, 동박 시험 후 생성. nightly 자동 추종 금지 |
| ADR-010 | snapshot, raw EM, network, metric, assessment, export 해시 분리 | 표적/표시 변경에 raw EM을 다시 돌리지 않고 물리 변경은 놓치지 않음 |
| ADR-011 | 안정된 UUID + semantic ID, CAD face index 의존 금지 | Boolean 재생성 시 face 번호가 달라도 포트, 재료 연결이 유지되어야 함 |
| ADR-012 | 제한된 표현식 문법 사용 | 단위 검사, 순환 검출, 재현성을 보장. 임의 Python eval은 프로젝트 입력 계약이 아님 |
| ADR-013 | 사용 가능한 값과 사용 여부를 분리 | 미지원, 추정, 누락, 충돌 데이터를 숨기지 않고 계산에 들어간 값을 보고 |
| ADR-014 | 지원 선언은 형상 편집/합성/실행/수렴/실측의 여러 축 | 예제가 열리는 것만으로 검증된 안테나로 승격하지 않음 |
| ADR-015 | 완전한 참조 계산 사례 검증 후 물성 완비 단일 포트 IFA 검증, R1 원호 검증 유지 | 패치/전송선 등 기준 fixture의 입력과 비교 기준을 완비. IFA의 대역/외형/적층 목표/급전 초기 기준은 21에서 채택, 실제 물성/제작/측정값은 후속 확정. G031은 기하 전용 |
| ADR-016 | 외부 정합의 네트워크 재사용을 허용 | 실제 패드, 동박, 내장 lumped boundary가 바뀌는 경우는 EM 입력 변경 |
| ADR-017 | 공통 수치 합격값 대신 benchmark/프로젝트별 AcceptanceProfile | B의 잠정 값은 검증 출발점으로 남기고 제조 공차와 해석 정확도를 혼동하지 않음 |
| ADR-018 | 측정 데이터 입력, 조건 비교는 R1, 고급 보정은 R2 | 기본 제품에서 해석과 실제 제작의 관계를 확인할 수 있어야 함 |
| ADR-019 | 우선 내부 검증용 배포, 외부 공개/상용 배포/소스 공개는 후속 별도 결정 | 구성요소별 코드/원문 배포 조건 기록. 외부 프로세스 실행만으로 GPL 의무가 사라진다고 가정하지 않음. 실제 패키지의 license review 필요 |
| ADR-020 | 프로젝트 archive는 일반 데이터, 실행 스크립트는 명시적 기능 | 원문/사용자 입력의 문자열로 임의 shell 명령이나 설치를 실행하지 않음 |

## 5. 릴리스별 물리 지원 범위

| 영역 | R1 계약 | R2/R3 확장 |
| --- | --- | --- |
| 목표 | 양수 실수 주파수, 여러 목표 대역 저장, 대역별 판정 | adaptive sampling, 복수 시나리오 최적화 |
| 기본 방사체 | 원호, IFA 기준군, 직선, 원호, polygon 임의 편집, 유한 ground | 검증된 추가 topology와 inverse design |
| 재료 | 실제 두께, isotropic scalar material과 검증된 손실 표현 | dispersion fit, anisotropy, ferrite, temperature 등 각 capability별 승격 |
| 포트 | 검증된 단일 포트, 데이터 구조는 n-port | multiport full-wave basis, 차동, 동시 여기, 배열 |
| 결과 | 복소 S, 임피던스, 정합, 필요한 field/방사/전력 검증 | UWB, ECC, 배열, 근거리 결합 특수 평가 |
| 환경 | 단순 배터리/케이스/금속 body와 변환/재질 | 복합 인체/flex 및 전문 사용 환경 |
| 출력 | PDF/SVG/DXF, 실제 동박 STEP, KiCad/Gerber/drill, 결과, 보고서 | BOM/assembly 고도화와 추가 EDA/산업 형식 |

R1에서도 여러 입력을 저장할 수 있다. 현재 backend가 계산하지 못하는 선택값은 `unsupported`이며 값을 지우거나 일반 모델로 자동 치환하지 않는다. 데이터 구조 지원과 계산 지원은 독립이다.

별도 개발 착수 지시 후에는 기하, 물성, 급전, 환경, 수치조건과 비교 기준이 완비된 참조 계산 사례를 먼저 검증하고, 이어서 물성이 완비된 단일 포트 IFA를 검증한다. 이 순서에서도 R1 원호의 전력/방사 및 출력 검증을 유지한다. G031은 기하 재현 전용이며 미정 물성을 채운 RF 기준 사례로 간주하지 않는다. 최초 IFA의 2.400~2.4835 GHz, 폭 40 x 길이 60 mm, 2층 FR-4, 완성 보드 두께 목표 1.0 mm, 양면 완성 동박 두께 목표 각 35 um, 50 ohm SMA 급전은 [21번 IFA 초기 검증 기준](21_RFAD_사례와_계약.md#ifa-initial-baseline)로 채택했다. 실제 재료 물성, 층별 두께와 공차, 상세 형상 및 제작/측정 조건은 후속 확정한다. 유전율/손실/전도도 등은 사용자가 입력하거나 자료에서 선택하는 변수이며 제품 상수로 고정하지 않는다. 물성 미정 상태의 저장과 기하 편집, 명시한 가정으로 입력을 완비한 탐색 해석, 실제 제작 보드와의 검증은 [08번 데이터 모델](08_RFAD_데이터_모델과_파일_형식.md)의 상태 계약으로 구분한다. 실물 물성 확보를 데이터 모델이나 GUI 설계 완성의 선행조건으로 두지 않는다.

## 6. 미해결 검증 gate

| ID | 남은 판단/위험 | 담당과 종료 조건 | 실패 시 동작 |
| --- | --- | --- | --- |
| <a id="GAP-001"></a>GAP-001 | C++ wxWidgets/renderer/Python/CAD/openEMS 상호 호환 버전 | Codex: R0 Linux native/headless worker와 R1 wxMSW/Windows-WSL 환경 lock, doctor, smoke. wxGTK GUI는 후속 출시 gate | 설치 profile을 수정하고 해당 환경의 호환성 상태를 미완료로 유지 |
| <a id="GAP-002"></a>GAP-002 | 실제 STEP의 얇은 동박, 중공 비아 안정성 | CAD 담당: 대표 최소 특징/다층/slot 재열기, 체적, 단면 비교 | 해당 객체/profile을 차단; 단순화는 별도 승인된 export 옵션 |
| <a id="GAP-003"></a>GAP-003 | solver-native V/I/E/H의 Fourier/amplitude 정의 | RF 담당: known-power, 전송선, far-field 기준군으로 scale, phase 검증 | 절대 전력, 효율 metric 계산 차단 |
| <a id="GAP-004"></a>GAP-004 | 각 material model의 solver 전달과 손실 중복 | RF 담당: PEC/유한도체/유전체 손실, dispersion 비교 | 미검증 모델을 실험 상태로 제한 |
| <a id="GAP-005"></a>GAP-005 | boundary/mesh/종료가 충분한 조건 | RF 담당: VT 수렴연구 및 개별 AcceptanceProfile | 숫자 결과는 보존하되 converged로 승격 금지 |
| <a id="GAP-006"></a>GAP-006 | 원본 원호 CAD의 미확정 전체 적층/배터리 조건 | 데이터 담당: 원문 증거 또는 별도 시험보드 조건 확정 | G031은 geometry fixture이며 RF 성능 benchmark로 오용 금지 |
| <a id="GAP-007"></a>GAP-007 | Windows<->WSL 파일, process 종료, 한국어 경로 | SW 담당: 실제 host fixture의 save/cancel/recover/hash 통과 | Windows 지원 완료 발표 금지 |
| <a id="GAP-008"></a>GAP-008 | EDA/net, Gerber 재해석 독립성 | CAD 담당: KiCad reopen/DRC + 별도 Gerber viewer 및 numerical compare | export를 generated_unverified로 유지 |
| <a id="GAP-009"></a>GAP-009 | 실측 정확도와 측정 불확도 | RF/측정 담당: 기준 시제품, 교정, 조립 상태, OTA 경로 확정 | 시뮬레이션 수렴과 실제 정확도를 별도 표시 |
| <a id="GAP-010"></a>GAP-010 | 제3자 및 원문 배포 범위 | 제품 담당: 선택 binary/source/data의 notice, license 명세 | 원문 bundle 재배포를 기본 활성화하지 않음 |
| <a id="GAP-011"></a>GAP-011 | 조합별 지원 주파수, 최소 형상, 최대 규모 | Codex/RF: 실제 benchmark 결과로 support-envelope 발행 | 입력 범위는 넓게 저장, verified 범위로 표시하지 않음 |
| <a id="GAP-012"></a>GAP-012 | B 잠정 임계값의 프로젝트 적합성 | RF/QA: 단위, 변환, 수렴, 실측 각각 별도 profile 확정 | 검증되지 않은 공통 합격값 자동 적용 금지 |
| <a id="GAP-013"></a>GAP-013 | CPW/stripline, 차동/modal 포트, complex Z0의 실제 경로 | RF/Codex: 해당 전송선, mode, 정규화 기준 fixture 통과 | 미검증 port/model 조합 차단 |
| <a id="GAP-014"></a>GAP-014 | UWB pair, timing, 복소 field 독립 기준 | RF/측정: 방향, 거리, 기준면이 있는 transfer 및 pulse benchmark | S11 기반으로 시간 성능을 대신 산출하지 않음 |
| <a id="GAP-015"></a>GAP-015 | 손실 MIMO ECC와 외부회로 결합 field | RF: 동일 위상 기준의 field basis, 공액 결합, power/패턴 비교 | S-only 결과에서 loss-aware ECC나 loaded radiation 생성 금지 |

현재 단계에서는 gate별 시험의 입력, 판정과 필요한 증거를 설계한다. 미결 사항의 결정 시점과 채택한 추천 처리 방향은 [25번 미결 항목 처리 기준](25_RFAD_문서_검토와_승인.md#remaining-decision-policy)을 따른다. 기준선 승인은 완료되었고 개발 착수는 별도 사용자 지시로 남긴다. 이후 범위 안의 기술 세부는 담당자가 개발 중 선정하여 해당 시험/제작/측정/배포 전에 고정한다. 미확정 실물 입력이나 원본 A 복구를 모든 개발의 선행조건으로 두지 않되 해당 검증의 합격 조건은 유지한다. 실제 구현, wxWidgets 통합 prototype, 설치와 EM 실행은 승인된 3.4 기준선에 따라 별도 개발 착수 지시 이후에 수행한다. 외부 시험장비와 시제품이 필요한 항목은 구현 완료와 분리한다. 이번 개정에서 확인한 문서 결함과 남은 결정은 [25번](25_RFAD_문서_검토와_승인.md)에 모은다.

## 7. 이번 개정의 우선순위와 설계 경계

DES-ARCH-001: 하나의 물리 의미 모델과 실제 2D/STEP/EM 요구를 유지하면서, 상주 GUI 비용과 반복 계산을 줄이는 구조를 우선한다. 성능을 위해 도체 두께, 물성, 포트 또는 검증 조건을 생략하지 않는다.

DES-ARCH-002: GUI는 C++ wxWidgets로 확정하고 상태는 `selected_pending_validation`으로 기록한다. R1은 wxMSW, 후속 Linux GUI는 wxGTK를 사용하고 wxQt 및 Qt를 요구하는 viewer는 제외한다. GUI-SPIKE-001..007은 toolkit 재선정이 아니라 wxWidgets 통합, 호환성과 성능을 검증하는 계획으로 유지한다. [24번](24_RFAD_GUI_선정과_성능_설계.md)의 PERF-001..010, 현재 기준 host와 fixture를 초기 목표로 채택한다. 기준 host는 Windows 11 x64, 물리 4코어 이상, RAM 16 GiB, SSD, 내장 GPU, 1920x1080이며 정확한 CPU/GPU/driver 등은 실행 manifest에서 고정할 미결 항목이다. 이는 실측 합격이나 최소 사양 보장이 아니다. F1 일반 편집 60 fps, F2 대형 장면 30 fps는 연속 조작 중에 적용하고 idle에서 60 fps redraw를 강제하지 않는다. Python/CAD/solver 비용도 합산하며 실제 메모리와 성능은 별도 개발 착수 지시 후 측정한다.

DES-ARCH-003: 문서 승인 D0, 구현 검증 R0, 제품 수용 R1을 분리한다. D0 완료는 API/데이터/화면/물리/검증 설계의 연결과 미결 결정의 명시를 뜻한다. 실험이 필요한 성능 및 물리 정확도를 문서 검토만으로 합격 처리하지 않는다.

DES-ARCH-004: R1은 로컬 단일 writer 프로젝트를 기본으로 한다. 공유 NAS, 동기화 폴더, 협업 서버의 동시 쓰기는 별도 파일 잠금/복구 시험 전 지원으로 선언하지 않는다. 복사 가능한 인계 archive와 실시간 공동 편집은 다른 범위다.
