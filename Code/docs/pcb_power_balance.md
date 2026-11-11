# 사용자 PCB의 독립 흡수 손실과 전체 전력 수지

일반 프로젝트에서 이 기록/전력을 설정하고 조회하는 [연구 GUI](project_studies.md)를 연결했다. 아래 고정 CLI 검증은 당시 원본으로 유지하며 GUI는 현재 프로젝트의 매개변수/출처를 보존한 별도 연구를 만든다.

설계 기준선 RFAD-D0-3.4의 PHY-054, EQ-015, EQ-016을 따른다. 승인 원문과 실제 납품 물성/제작/측정 조건은 변경하지 않는다. 기존에 사용자가 허용한 RO4350B 탐색 모델에서 소프트웨어와 수치 경로를 검증한다. 계산의 독립 적분, 선택한 잔차 한계의 충족, 실제 제품 정확도는 별개 상태다.

## 선택적 입력과 호환성

PCB worker 설정에 `power_balance: {"max_relative_residual": 0.03}`을 명시한다. 방사 설정이 함께 있어야 하고 방사 주파수는 같은 실행의 직접 포트 표본이어야 한다. 보간으로 전력 수지를 채우지 않는다. 잔차 기준은 계산 전 정하며 지원 범위는 0.0001~0.1이다. 이 기능을 생략한 기존 계획의 구조, 원시 파일 목록과 직접 입력 동작은 유지한다.

최초 지원은 planar 유한 전도 sheet와 상수 등가 전도도 유전체였다. 이후 [개별 손실 정밀도와 PTH 분할](pcb_loss_precision.md)을 추가했다. 새 계산은 sheet가 대체하지 않은 edge의 native QuarterCell 체적 기여율로 유전체/PTH를 나누고, sheet edge는 정렬한 E*rotH 전체를 배정하여 중복을 막는다. 사각/원형 외형과 기존 선/원호/pad/polygon의 native 우선순위를 따르며 PEC로 대체하거나 via 손실을 0으로 게시하지 않는다. 아래 실제 고정 검증은 최초 planar 버전의 역사적 기록이다.

## 독립 적분

이 절은 최초 planar 검증의 기록 방식이다. 현재 계산의 QuarterCell 재료 분할, native sheet의 재료 계수 대체와 PTH 합계는 [후속 정밀도 계약](pcb_loss_precision.md)을 따른다. 아래의 원래 검증 표/실행 기록은 재작성하지 않는다.

기판/적층의 경계를 감싸는 작은 영역에 무보간 `dump_mode=0`의 FD E(10), 전도 J(12), 전체 전류 rotH(13)를 기록한다. [공식 dump 계약](https://docs.openems.de/en/latest/python/CSXCAD/CSProperties/CSPropDumpBox.html)을 따른다. 유전체 경계에서 node 보간한 필드를 사용하면 불연속 성분이 섞일 수 있으므로 원래 Yee 전기 edge를 사용한다. PML은 포함하지 않는다.

native J는 solver가 저장한 유효 kappa와 같은 edge의 E를 곱한 전도 전류다. 유전체 손실은 아래 식으로 계산한다. 물성 입력의 Df를 다시 환산하거나 별도 미정 전도도를 0으로 채우지 않는다.

```text
Pdiel = 0.5 * sum(Re(E_edge * conj(J_conduction_edge)) * V_edge)
V_edge = edge_length * dual_width_1 * dual_width_2
```

edge 길이와 dual 폭은 실제 비균일 격자에서 m로 계산한다. 계면의 유효 전도도와 필드도 native 값을 그대로 소비한다. 같은 edge의 도체 손실과 중복 합산하지 않는다. 이는 연속체의 정확한 체적 적분을 주장하는 값이 아니라 실행한 Yee 모델의 독립 이산 적분이다.

유한 두께 sheet는 단순한 DC 체적 저항이나 임의의 `surface_resistance`로 바꾸지 않는다. 실제 native sheet edge의 E와 rotH 실수 일률을 사용한다. [설치 소스와 대조한 engine 구현](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/FDTD/engine_interface_fdtd.cpp)에서 rotH는 H 전류의 순환을 dual 면적으로 나눈 값이다. [sheet 구현](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/FDTD/extensions/operator_ext_conductingsheet.cpp)의 주파수 의존 손실과 반응 전류를 함께 포함한다.

```text
a = pi * f * dt
J_sheet_aligned = rotH_dump * exp(-j*a) / cos(a)
Pcond = 0.5 * sum_sheet(Re(E_edge * conj(J_sheet_aligned)) * V_edge)
```

rotH dump는 전기 시간 라벨을 쓰지만 H는 반 time step 뒤에 있다. [engine의 시간 정의](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/FDTD/engine_interface_fdtd.h)와 설치 소스를 대조해 위상을 보정한다. `cos(a)`는 사다리꼴 평균 전도 전류의 보정이다. 완료된 Fourier 스펙트럼에서 변위/저장 전류는 반응 성분이며 실수 손실을 만들지 않는다. 유한 기록 종료와 반올림의 오차는 잔차에 남는다. 이 보정을 생략한 E*rotH를 열 손실로 취급하지 않는다.

native XML에서 ContinuousStructure를 따로 읽어 같은 MATERIAL|METAL 우선순위로 sheet edge를 배정한다. 같은 net의 선/pad/polygon 중첩은 점유 원본 하나로 배정하여 이중 적분하지 않는다. 포트의 방향별 저항 edge는 재료 손실에서 제외한다. 원본 도체별 합계와 점유 edge 수도 기록한다.

## 합계와 판정

```text
residual = Paccepted - Prad - Pdiel - Pcond
relative_residual = residual / Paccepted
```

같은 실행/주파수/기준면/여기에서 얻은 수용 전력과 native NF2FF Prad를 비교한다. 입사/반사/수용/방사/유전체/도체/잔차를 보존한다. `Paccepted-Prad`는 여전히 추론 손실로 별도 남기며 독립 적분값으로 사용하지 않는다. 음의 성분이나 잔차를 자르지 않는다. 허용치 초과 또는 음의 손실은 `requires_review`다. 범위 안이면 `within_initial_numerical_budget`이며 PHY-054 전체 수용이나 제조 성능 합격으로 승격하지 않는다.

현재 펄스 peak Fourier 필드의 전력 단위는 `W*s^2`, 전계는 `V*s/m`, 전류 밀도는 `A*s/m^2`다. 0.5는 이 peak Fourier 규약에 속한다. RMS 필드 식에 추가 계수를 곱하거나 W로 표시하지 않는다. `absolute_power_w=null`과 실제 제작/실측 검증 false를 유지한다.

## 모듈과 산출물

- `application/pcb_power.py`: 선택 설정/기록 계획, 원시 파일 계약과 순수 전력 합계/검증.
- `adapters/solvers/openems/pcb_absorption.py`: dump 생성, native XML 분할, HDF 검사와 독립 필드 적분.
- `solver_artifacts.py`: 원시 파일과 별도 `power_balance_result`의 봉인/계획 연결 검증.
- `tools/verify_pcb_power_balance.py`: 공개 snapshot/plan/prepare/submit/result.open 경로의 고정 검증 CLI와 CSV.

요청한 실행만 `pcb_loss_E.h5`, `pcb_loss_J.h5`, `pcb_loss_rotH.h5`를 원시 manifest에 추가한다. 별도 `power_balance.json`과 정규화 결과의 `power_balance`는 동일해야 한다. 후처리 전용 실행도 봉인된 세 필드를 사용하며 FDTD를 다시 시작하지 않는다. 해석기 없는 서비스에서도 `result.open`으로 조회할 수 있다. 일반 프로젝트의 손실 설정과 전력 표시는 [연구 GUI](project_studies.md)에서 제공하며 이 고정 CLI 보고서의 원본은 유지한다.

HDF의 primary 격자, 좌표(1e-12 m), 주파수(상대 1e-6), component/x/y/z 크기와 유한성을 확인한다. native dump의 outward snap과 XML 좌표 반올림을 고려해 primitive는 목표 격자의 안쪽에 놓고 실제 HDF가 계획한 격자와 일치하는지 검사한다. 손실 필드의 초기 기록 예산은 48 MiB이며 기존 64 MiB 파일/128 MiB 패키지 상한도 유지한다. 예상 worker 메모리에 필드 누산/후처리 비용을 추가한다.

## 실행

[고정 manifest](../fixtures/pcb_power_balance_study.json)는 이전 탐색 fixture의 미정 납품 재료와 출처를 유지한다. 주파수 2.400/2.44175/2.4835 GHz, 격자 0.50/0.45/0.40 mm, NF2FF 기록 거리 30 mm, 각도 5 degree, 같은 PML8/공기 여백/종료 조건을 사용한다. 상대 잔차 3%는 새 실행 전에 정한 초기 수치 예산이다.

```powershell
$env:PYTHONPATH='src;tests;tools'
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_power_balance.py --workspace .local/new-power-study/workspace --report .local/new-power-study/report.json --catalog .local/pcb-catalog/catalog.sqlite
```

기존 완료 계산은 같은 입력/worker에서 `--resume`으로 이어 읽는다. `--reassess-only`는 solver/카탈로그 없이 모든 등록 파일을 읽어 봉인과 전력 합계를 재확인한다. 실패/취소/중단 계산을 자동으로 새 실행으로 바꾸지 않는다. worker가 바뀌면 새 경로를 사용한다. report와 CSV는 파생물이며 원래 native 산출물은 덮어쓰지 않는다.

## 남은 범위

PTH의 GHz skin depth 정밀도, 기록 거리/각도 수준을 포함한 3축 연구 GUI 행렬, 독립 solver 대조와 실제 제조/측정 자료 대조는 남는다. 후속 분할/수치 축 연구는 [손실 정밀도](pcb_loss_precision.md)를 따른다. 국부 skin depth/곡선 및 기록 종료 오차를 이 초기 수지 확인으로 모두 검증한 것으로 취급하지 않는다. 실제 납품 유전율/손실/전도도, 마스크/표면처리, SMA/케이블/교정 기준면과 측정 불확도는 미정으로 유지한다.

## 실제 검증 기록

2026-11-11 KST의 최종 고정 연구는 3개 격자/3개 주파수의 native 계산을 완료했다. 동일 snapshot과 실제 worker 소스 113개를 사용했고 현재 소스와 각 실행의 hash가 일치한다. 세 사례의 기록된 작업 시간 합계는 566.016초다. 0.40 mm의 실제 native 격자점은 1224210, 7254 time steps에서 -51.40 dB로 종료했다. 세 손실 필드의 finest 예상 원시 데이터는 18599760 bytes이며 실제 supervisor의 전체 디렉터리 peak는 29712202 bytes로 기존 상한 안이었다.

세 격자의 중심 주파수 2.44175 GHz 결과를 수용 전력 100%에 대한 비율로 정리하면 다음과 같다. 절대 W 값이 아니다.

| 격자 mm | 방사 % | 유전체 손실 % | 도체 손실 % | 부호 있는 잔차 % |
| --- | --- | --- | --- | --- |
| 0.50 | 98.874679 | 0.651971 | 0.663505 | -0.190154 |
| 0.45 | 98.747247 | 0.658872 | 0.775193 | -0.181312 |
| 0.40 | 98.725889 | 0.662449 | 0.803396 | -0.191734 |

finest 격자의 세 직접 주파수도 보존한다.

| 주파수 GHz | 방사 % | 유전체 손실 % | 도체 손실 % | 부호 있는 잔차 % |
| --- | --- | --- | --- | --- |
| 2.40000 | 98.793850 | 0.645297 | 0.739909 | -0.179055 |
| 2.44175 | 98.725889 | 0.662449 | 0.803396 | -0.191734 |
| 2.48350 | 98.542925 | 0.681184 | 0.874426 | -0.098535 |

9개 조합의 최대 절대 상대 잔차는 0.001917337872630457, 즉 0.1917337872630457%다. 모든 성분은 음수가 아니며 초기 3% 수지 기준을 충족했다. 잔차가 작아도 각각의 손실이 정밀 수렴했다고 단정하지 않는다. 중심 주파수의 정규화 도체 손실은 0.45 -> 0.40 mm에서 약 3.51% 상대 변화가 남는다. 이는 수용 전력 기준 약 0.0282%p 변화다. 더 정밀한 손실 예측에는 국부 격자/시간 종료/독립 대조가 필요하다.

`verify_pcb_power_replay.py`로 실제 `postprocess_only`를 실행했다. 동일 raw manifest/포트 표본/방사 요약/독립 손실이 완전히 같았고 원본 파일 81개의 봉인이 유지됐다. 전후 native 계산 작업 ID 3개도 동일했다. 해석기 없는 서비스의 재열기/전체 파일 조회와 CLI의 solver/카탈로그 없는 재판정, 완료 연구 재개가 통과했다. CSV는 manifest 순서로 고정하고 재판정/재개 사이 동일 바이트를 확인했다. 판정은 별도 내용 hash 파일로 보존하고 source 사본/입력 참조를 기록한다.

Windows 전체 회귀는 748개 중 676개 통과/72개 조건부 스킵, 387.587초다. 이 수집 후 추가한 HDF/CLI 시험은 최종 별도 검증으로 구분했다. 최종 호스트 계약/CLI 10개와 실제 WSL numpy/h5py 적분 6개가 모두 통과했다. CTest 8개도 0.38초에 통과했다. 호스트에 numpy를 추가하지 않았으며 Windows의 조건부 제외를 실제 WSL 적분 검증으로 대체 집계하지 않는다. GUI 소스/화면은 이번 단계에서 변경하지 않았다.

개발 중 최초 0.50 mm 실행은 후처리에서 실패했고 원본을 보존했다. CSXCAD의 openEMS wrapper 읽기 반환 오류, outward snap/좌표 반올림과 native HDF의 component/x/y/z 순서를 확인해 수정했다. 진단용으로 잘라 읽은 필드는 최종 수용 근거로 사용하지 않았다. 위 최종 3개 실행은 보정된 worker로 새 경로에서 원시 필드까지 다시 생성한 결과다. 실제 납품 JLC 동박과 RO4350B의 epsilon_r/tan_delta/conductivity 6개 미정값은 모두 null로 유지됐다. 별도 탐색 재료에서 소비하지 않는 물성도 미정이다.

수치/소스/시험/원시 출처와 제한은 [실행 기록](../runtime_profiles/pcb-power-balance.json)을 따른다. 이전 방사 수렴 연구의 원본 및 당시 미평가 상태는 변경하지 않았다.
