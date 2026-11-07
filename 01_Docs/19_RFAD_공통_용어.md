# 공통 용어, 기호, 상태 정의

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

## 1. 모델과 출력

| 용어 | 본 문서의 의미 |
| --- | --- |
| 의미 모델 | entity, parameter, layer, net, material, port의 물리 의미를 가진 설계 원본 |
| physical model | 실제 치수, 동박 두께, 적층, 환경을 나타내는 모델 |
| solver projection | 선택한 수치 방법을 위해 sheet/volume/PEC/등가회로 등으로 표현한 파생물 |
| display mesh | 화면 렌더링용 삼각형. 제조/해석 정확도의 원본이 아님 |
| synthesis / seed | 목표와 template 가정으로 초기 치수/후보 생성. 실제 공진 최적화와 구분 |
| snapshot | 특정 revision을 고정한 불변 설계 입력 |
| artifact | hash, 생성자, 조건, status를 가진 파일/배열 산출물 |
| B-rep STEP | 경계 표현의 유효한 CAD 고체/assembly 교환. STL과 구분 |
| CAM / Gerber | 레이어별 제조 이미지와 관련 명세. RF 의미 전체의 교환과 구분 |
| sidecar | 주요 교환 파일과 hash로 연결한 RF/재료/포트/변환 metadata |
| roundtrip | 내보낸 파일을 재입력해 source 모델과 비교하는 검증 |

## 2. 전자기학과 수치

| 용어, 기호 | 정의와 구분 |
| --- | --- |
| epsilon_r / Dk | 상대유전율. 시험/설계값, 방향, 주파수, 조건이 필요 |
| tan_delta / Df | 손실 탄젠트. conductivity와 같은 손실을 중복 적용하지 않음 |
| epsilon_eff | 특정 전송선/모드 근사의 유효유전율. 모든 PCB 방사체의 epsilon_r 대체값이 아님 |
| PEC | 이상 완전도체 근사. 실제 copper thickness와 loss를 별도로 기록 |
| skin depth delta | 해당 양도체, 주파수, 매질 가정에서의 감쇠 길이 |
| phasor | 시간 규약을 가진 복소 amplitude. RFAD domain은 RMS exp(+j*omega*t) |
| power wave / pseudo wave | 복소 Z0에서 다른 파 정의. 이름, 식, 정규화 보존 |
| reference plane | port V/I/S가 정의되는 위치. 좌표 원점과 다른 개념 |
| renormalization | 같은 네트워크의 reference impedance/파 정의 변환 |
| de-embedding | 알려진 fixture/network 영향을 제거하는 변환. 임의 curve shift가 아님 |
| S11 dB / RL | 각각 20log10\|Gamma\|와 그 부호 반대인 return loss. singular/mask 별도 |
| radiation efficiency | 명시한 accepted power 중 radiated power의 비 |
| total efficiency | 지정 입력전력 기준에 대한 방사 비. multiport/외부회로 기준 필요 |
| directivity | 같은 총 방사전력의 등방 방사와 비교한 방향성 |
| gain / realized gain | radiation/accepted 및 incident reference 차이를 명시한 이득 |
| NF2FF | 기록한 닫힌 surface field에서 far-field로 변환하는 수치 연산 |
| convergence | 수치 조건 변경에 결과가 안정되는지 검사. 실측 정확도와 구분 |
| UWB pair transfer | Tx/Rx, 방향, 거리, 기준면을 포함한 전달 응답 |
| group delay | 유효 구간에서 unwrapped phase의 음의 각주파수 미분 |
| ECC | 환경, 편파 가정과 복소 패턴/근사를 명시한 포락선 상관 지표 |
| L / Q / M / k | 코일 인덕턴스, 품질계수, 상호 인덕턴스, 결합계수. loaded/bare 정의 구별 |
| TARC | specified multiport incident vector에 대한 전체 active reflection 지표 |
| tauCAD / tau2D / taufab | CAD 수치교환, 벡터 근사, 실제 제조의 서로 다른 공차 |

## 3. 상태와 우선순위

M/S/C는 해당 기능 영역의 필수/중요/선택 확장이다. R0는 기반 검증, R1~R3는 출시 단계다. core requirement와 extension clause가 다른 단계를 가질 수 있다.

`completed`는 작업 종료/산출물 생성, `converged`는 정한 수치 비교 통과, `verified_profile`은 지정 fixture/profile 검증, `measured`는 실측 근거 존재를 뜻한다. `pass`에는 항상 target/profile/domain이 따라야 한다. `unsupported`, `not_evaluated`, `inconclusive`, `failed`, `stale`는 서로 바꿔 쓰지 않는다.

## 4. 근거

구체적 수식과 예외는 [수식 명세](09_RFAD_수식과_물리_모델.md), 실제 상태 enum은 [시스템 명세](04_RFAD_시스템_명세.md), 원문 정의는 [출처 목록](18_RFAD_출처와_근거.md)에 연결된다. 이 용어집만으로 수식의 적용 범위를 확장하지 않는다.

## 5. 설계 승인과 성능 용어

| 용어 | 의미 |
| --- | --- |
| D0 | 개발 전 문서 설계와 사용자 검토 단계. 3.4 기준선은 승인 완료이며 실제 제품 개발 착수/검증과 구분 |
| RFAD-D0-3.4 | 2026-11-07 사용자가 승인한 설계 기준선 ID. 문서/원본 B 참조/잔여 gate와 파일 해시를 기록하며 개발 착수 승인은 포함하지 않음 |
| IFA 초기 검증 기준 | 21번에 채택한 첫 보드의 목표 대역/외형/적층 목표/급전 조건. 실제 재료/제작/측정의 확정, 제작 완료나 해석/실측 합격과 별개 |
| 사용자 입력 물성 | 유전율, 손실, 전도도 등 사용자가 직접 지정하거나 근거 자료에서 선택하는 변수. 입력 유효성과 실제 재료의 검증 여부는 별도 |
| 가정값 기반 탐색 | 명시한 가정으로 필요한 물리 입력을 완비한 계산. 원값/출처/적용 범위를 보존하며 실물 검증 결과로 표시하지 않음 |
| 초기 성능 목표 | 24번의 채택된 PERF 예산과 기준 host/fixture. 실측 합격, 최소 사양 또는 서비스 보장값이 아님 |
| R1 우선 출시 환경 | Windows 11 x64 wxMSW GUI와 로컬 WSL2 Linux worker. 초기 배포 대상은 내부 검증 사용자 |
| 후속 Linux GUI | wxGTK 데스크톱의 후속 출시. 버전/일정은 미정이며 Linux native/headless worker의 R0 검증과 별개 |
| 내부 검증용 배포 | 초기 검증 사용자 대상 배포. 외부 공개/상용 배포 및 소스 공개 여부는 별도 결정 |
| selected_pending_validation | GUI가 C++ wxWidgets로 선정되었으며 통합/성능은 미검증. 개발 착수 승인을 뜻하지 않음 |
| 일반 편집 / 대형 장면 | 24번 F1/F2의 사전 고정한 부하 분류. 연속 조작 목표는 각각 60 fps / 30 fps |
| GUI-SPIKE | 선정된 wxWidgets의 통합/성능 검증 ID. 이전 ID를 유지하며 후보 비교 단계로 사용하지 않음 |
| private commit | 프로세스에 commit된 private 가상 메모리. 현재 물리 RAM과 다름 |
| working set / RSS | 현재 resident 메모리. shared page의 중복 합산에 주의 |
| PSS | 공유 resident page를 비례 배분한 Linux 메모리 지표 |
| cold / warm startup | 첫 실행과 cache가 남은 반복 실행. 측정 조건을 함께 기록 |
| input latency | 입력 timestamp부터 사용자가 확인 가능한 화면 반영까지의 시간 |
| p95 / p99 | 표본 지연의 95/99 percentile. 평균 FPS와 다른 지표 |
| virtualization / ROI / LOD | 보이는 행, 필요한 데이터 영역, 표시 상세도만 로딩하는 정책 |
| backpressure | 생산 속도가 소비 속도를 넘을 때 queue를 제한하고 전달 속도를 조절하는 정책 |
| resume_eligibility | checkpoint 재개 가능성. interrupted/completed 등의 JobState와 독립 |
| postprocess_only | 검증된 완결 raw에서 재처리하며 native solve는 수행하지 않는 실행 모드 |
