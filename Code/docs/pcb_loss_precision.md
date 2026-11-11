# 개별 흡수 손실 정밀도와 PTH 분할

갱신일: 2026-11-12 KST. 설계 기준선 RFAD-D0-3.4를 유지한다. 원본 재료/매개변수/출처와 제조/측정 미정 상태는 변경하지 않는다. 아래 수치 예산은 소프트웨어 계산의 초기 검사 기준이며 제조 공차나 측정 정확도가 아니다.

## 분할과 중복 방지

기존 E/J/rotH 무보간 필드를 사용한다. [공식 dump 계약](https://docs.openems.de/en/latest/python/CSXCAD/CSProperties/CSPropDumpBox.html)의 J는 전도 전류, rotH는 전도와 변위 전류를 포함한다. 필드의 위치/시간과 실제 native 재료 평균을 구분한다.

설치한 openEMS의 [QuarterCell 구현](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/FDTD/operator.cpp), [J/rotH 조회](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/FDTD/engine_interface_fdtd.cpp)와 [conducting sheet 구현](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/FDTD/extensions/operator_ext_conductingsheet.cpp)을 대조했다. 각 전기 edge의 두 접선 방향에서 네 quarter-cell 좌표를 조회하고 비균일 면적에 비례하여 전도도를 평균한다. 체적 평균은 MATERIAL만 조회하고, sheet 점유는 MATERIAL|METAL 우선순위를 사용한다.

conducting sheet의 ADE는 해당 edge의 EC_G/EC_C를 대체한다. 반면 material J dump는 저장된 재료 전도도로 계산되어 sheet edge의 실제 전류를 나타내지 않는다. 따라서 체적 손실에서는 sheet/source edge를 제외하고, sheet에서는 시간 정렬한 E*rotH 전체의 실수 일을 적분한다. sheet에서 material J를 빼거나 그 J를 PTH 손실에 다시 더하지 않는다. 분할 방법은 quarter_cell_volume_and_native_sheet_override/0.1로 식별한다.

```text
kappa_eff = sum(material_kappa * quarter_area) / sum(quarter_area)
Pvolume = 0.5 * Re(E * conj(J_conduction)) * Yee_edge_volume  [non-sheet/source only]
Pmaterial = Pvolume * kappa_material_contribution / kappa_eff
Psheet = 0.5 * Re(E * conj(rotH_aligned)) * Yee_edge_volume  [sheet only]
Pconductor = sum(Psheet) + sum(Pvia)
residual = Paccepted - Pradiated - Pdielectric - Pconductor
```

한 edge를 중심점의 재료 하나에 모두 배정하지 않는다. 유전체/배럴이 함께 기여하는 체적 계면에서도 전류 기여율 합계는 1이다. 패드/배럴 접합에서 sheet가 대체한 edge는 sheet에만 배정하므로 이중 계산하지 않는다. 포트 방향의 소스 저항 edge와 PML은 제외한다. 중공 drill은 우선순위가 높은 무손실 공기로 소비하며 구리로 채우지 않는다. 같은 net의 겹친 평면 형상은 native 점유자 하나에만 배정한다.

각 주파수의 sheet/source가 아닌 edge에서 재구성한 kappa_eff*E와 실제 native J를 대조한다. 원시 Fourier float32 누산을 고려한 혼합 상대 오차 0.005를 넘으면 결과 게시를 차단한다. 계면/좌표/주파수/HDF 계약도 그대로 검사한다. 전체 체적 일과 재료별 합계가 상대 1e-10 안에서 같은지 검사하며 음수 성분은 보존한다.

결과에는 sheet_loss_w_s2, via_loss_w_s2, sheet_components, via_components와 dielectric_components를 기록한다. 도체 합계는 sheet+via이며 유전체 합계에 via를 다시 더하지 않는다. 분할 방법/표본 수/주파수별 전류 대조와 체적 보존 근거를 함께 봉인한다. 단위는 W*s^2이며 절대 W와 제조/측정 검증을 생성하지 않는다.

## 정밀도 연구

초기 개별 손실 기준은 최소 3수준, 상대 변화 2%와 수용 전력 비율의 절대 바닥 0.00001이다. 각 성분을 수용 전력으로 정규화한 뒤 다음을 검사한다.

```text
abs(b - a) <= max(0.00001, 0.02 * max(abs(a), abs(b)))
```

유전체/전체 도체/평면 도체/비아 및 각 원본 성분, 모든 직접 주파수를 각각 확인한다. 음수는 작은 값이라도 합격하지 않는다. 모든 인접 쌍을 보존하고 최소 수준 이후 마지막 쌍을 판정한다. 작은 에너지 잔차나 총 손실의 상쇄를 개별 손실 합격으로 대신하지 않는다. 이 기준을 충족해도 연속체 오차, 표면 거칠기 또는 실물 정확도를 보장하지 않는다.

일반 프로젝트 연구는 선택적 loss_profile을 생성 때 고정한다. GUI의 초기 판정 탭에서 상대 한계/절대 바닥을 지정하고 결과에서 개별 손실 안정성과 별도 PTH 전력을 확인한다. 이전 연구에 없던 기준은 사후 삽입하지 않는다.

추가 설정 feature_subdivisions는 각 기존 임계 구간의 최소 분할 수 1~8이다. 큰 구간은 기존 grid_mm 상한으로 더 나눈다. 구멍/도금/급전의 짧은 구간도 명시적으로 세분할 수 있으며 최소 간격 0.0001 mm를 유지한다. 기본 profile은 1500000 격자점/300초이며 [후속 RO4350B 연구](ro4350b_loss_refinement.md)의 명시적 compute_profile만 표준 2400000/900초, 심화 3000000/1800초를 허용한다. 값이 없으면 기존 격자를 그대로 사용한다. 일반 GUI에서는 공통 국부 조건을 고정하고, 별도 CLI는 격자/임계 구간/종료/곡선 네 축을 하나씩 변경한다.

모든 계획은 첫 실행 전에 고정한다. 동일 snapshot, 물성, 급전, 설치, 실제 외곽/PML/방사 기록 면과 각도를 유지하고 해당 조건 하나만 바꾼다. 같은 설정의 기준 계산은 공유한다. 곡선 축은 실제 polygon 분할이 달라져야 하고, 종료/곡선 축의 Yee 격자는 같아야 한다. 도구가 지원하는 마지막 쌍만으로 Richardson 또는 모든 국부 특징의 점근 수렴을 주장하지 않는다.

## PTH 해상도와 참조 구분

```text
skin_depth = 1 / sqrt(pi * frequency * mu0 * conductivity)
```

현재 비자성 체적 도체의 입력과 주변 실제 x/y 간격으로 skin depth 대비 격자 비를 기록한다. skin depth 안의 최소 3개 cell은 보수적 해상도 진단이며 충분한 RF 정확도 증명이 아니다. GHz 구리의 얇은 skin depth가 미해상도이면 유한 도체 손실을 계산하더라도 skin_depth_loss_validated=false를 유지한다. 더 미세한 고전도 체적 격자의 종료 실패도 보존하며 PEC나 더 두꺼운 도금으로 자동 대체하지 않는다.

별도 균일 축방향 전계 참조는 CSXCAD 중공 shell의 적분을 0.5*sigma*abs(E)^2*pi*(ro^2-ri^2)*L과 대조한다. 이는 독립적인 기하/전류 분할 알고리즘 검사이며 안테나 FDTD 또는 제조 시료가 아니다. 1000 S/m 배럴/접속 도체 fixture도 명시적 수치 시험 재료로만 사용하고 구리 물성이나 제조사 제공값으로 제안하지 않는다.

## 재현과 호환성

```powershell
$env:PYTHONPATH='src;tests;tools'
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_loss_precision.py --workspace .local/new-loss/workspace --report .local/new-loss/report.json --manifest fixtures/pcb_loss_precision_study.json --catalog .local/pcb-catalog/catalog.sqlite
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_loss_precision.py --workspace .local/new-pth/workspace --report .local/new-pth/report.json --manifest fixtures/pth_loss_study.json
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_loss_precision.py --workspace .local/new-reference/workspace --report .local/new-reference/report.json --manifest fixtures/pth_loss_reference_study.json
```

완료 결과에는 --reassess-only를 사용하며 solver/카탈로그 없이 봉인 결과를 재확인한다. --resume은 같은 원본/worker의 완료 단계를 재사용한다. 실패/중단 native 실행을 자동 교체하지 않는다. 불변 판정에는 참조 결과와 판정기 소스/해시를 보존한다. 종료 코드 0은 검사한 손실 설정 안정성 충족, 1은 계산 완료 후 미확립, 2는 입력/실행 오류다.

분할 알고리즘 개발 중 material J를 sheet에서 차감한 이전 방식은 PTH 접합에서 음수 패드 손실을 만들었다. native 연산자 대조 후 위의 edge 배정으로 수정했다. 당시 raw/plan/정규화 결과는 이력으로 보존하고, 그 이전 성분 배정은 최종 검증값으로 사용하지 않는다. 다음 도구는 완료 원시 필드를 읽기만 하여 새 경로에 수정 손실을 계산한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/recompute_pcb_loss.py --producer-report .local/pcb-loss-precision-current/report.json --destination .local/new-loss-recalculation
```

재계산은 원래 FDTD 생산자의 snapshot/설치/소스/plan/raw 해시와 새 계산기 소스 identity를 따로 기록한다. 기존 normalized_result나 판정을 덮어쓰지 않고 FDTD를 실행하지 않는다. 원래 기하/물성/설정과 현재의 결정적 plan을 대조하며, 개발 중 폐기한 PTH 기록 방법 이름 한 개만 비교용 사본에서 허용한다. 원본 plan의 이름은 바꾸지 않는다. 일반 solver의 runtime 일치 검사를 우회하는 재개 기능이 아니다.

기존 실행의 일부 사례가 실패한 경우 --continue-independent를 명시하면 원래 실패를 건너뛰고 아직 실행하지 않은 독립 조건만 진행한다. 원래 job ID/실패/확정 종료와 슬롯 반환을 검사하며 같은 조건의 대체 작업은 만들지 않는다. 누락 수준이 있는 축과 전체는 미확립이고 보고서는 completed_with_blocked_cases다. 종료 미확인/예약 유지 또는 봉인 검증 오류를 이 옵션으로 우회하지 않는다.

기존 planar loss-recording/0.1 계획과 과거 power-balance/0.1 결과는 그대로 조회/검증한다. PTH는 과거에 해당 기록을 허용하지 않았으므로 새 loss-recording/0.2로 식별한다. 새 결과의 추가 재료 분할은 별도 합계와 교차 검증한다. 원본 프로젝트 schema와 직접 입력을 바꾸지 않는다.

정밀 격자의 원시 손실 HDF는 파일 하나가 8 MiB를 넘을 수 있다. JSON/상태 메타데이터의 8 MiB 상한은 유지하고, Journal.verify_file/copy_artifact는 기존 native 파일 한계 64 MiB 안에서 1 MiB 버퍼로 전체 크기/SHA256을 검사한다. 재후처리 입력도 같은 스트리밍 복제를 사용하며 기존 staging을 덮어쓰지 않는다. 기본/표준 손실 필드는 48 MiB, 명시적 심화 profile만 96 MiB이며 전체 패키지 128 MiB는 유지한다. verify_pcb_power_replay.py는 완료한 새 native 결과 중 가장 큰 기록을 선택해 추가 FDTD 없는 재후처리와 해석기 없는 재열기를 검사한다. 검증된 기존 raw 기준을 새 producer의 결과로 취급하지 않는다.

실제 납품 물성/동박/마스크/표면처리, 제작 공차, SMA/케이블/교정 기준면과 측정 불확도는 미정으로 유지한다.

## 실제 실행 결과와 남은 정밀도

[실행 및 소스 기록](../runtime_profiles/pcb-loss-precision.json)에 원래 FDTD와 수정 후처리, 최신 소스의 새 native 실행을 구분했다. RO4350B의 실제 납품 재료 2개에 있는 Dk/Df/전도도 6개 미정값은 그대로 null이다. 출처 기반 탐색 모델과 시험 전용 PTH를 실물 입력으로 채택하지 않는다.

| 연구 | 실행과 최종 판정 |
| --- | --- |
| RO4350B 탐색 IFA | 12개 비교 행/9개 고유 조건 중 8개 완료. 국부 최소 4분할은 300초 제한으로 중단되어 해당 축은 미확립 |
| RO4350B 격자 | 0.45/0.40/0.36 mm. 마지막 쌍의 유전체 합계 최대 상대 변화 0.045334%, 도체 합계 3.430551%. 전체 성분의 2% 기준은 미확립 |
| RO4350B 종료 | 1e-5/1e-6/1e-7. 마지막 쌍에서 유전체 합계 최대 0.001344%, 도체 합계 0.007721%. 검사한 개별 성분 기준 통과 |
| RO4350B 곡선 | 0.025/0.00625/0.0015625 mm. 고정 Yee 격자의 마지막 손실 변화 0. 모든 성분 기준 통과. 연속 기하 정확도 증명은 아님 |
| 명시적 구리 PTH fixture | 수정 후 원시 필드 재계산과 최신 소스의 새 native 3수준 모두 초기 개별 손실/전력 예산 통과. 작은 via 성분은 절대 바닥 기준을 사용할 수 있으며 상대 2% 정확도 또는 skin depth 정확도 합격으로 확대하지 않음 |
| 1000 S/m 수치 PTH fixture | 국부 1/2분할 완료, 3분할은 300초 제한. 최소 3수준 미충족으로 미확립 |
| 균일 축방향 전계의 중공 shell | 실제 CSXCAD 적분과 해석식 상대 차이: 0.1 mm 9.1348%, 0.05 mm 3.4507%, 0.025 mm 1.1771%. 기하/분할 참조 검사이며 안테나 FDTD 정확도 검증은 아님 |

RO4350B 완료 사례의 전체 에너지 잔차는 초기 3% 예산 안이다. 총 수지의 일치로 위의 개별 손실 미수렴을 숨기지 않는다. 새 native PTH의 같은 raw 재후처리/해석기 없는 재열기도 통과했고 원본 봉인 파일 81개와 native 작업 ID를 보존했다.

후속 정밀도 작업은 RO4350B 도체의 추가 격자와 국부 특징 세분화, 고전도 배럴의 표피 깊이 처리 및 독립 solver 대조다. 시간/격자/원시 필드 예산 변경이 필요하면 별도 연구 조건으로 사전 고정하고 이전 실패를 보존한다. 실제 제작/측정 데이터의 확정과 대조는 그 후 별도 검증이다.

## WSL 실행 중 발견한 읽기 경합

첫 RO4350B 실행은 감독기의 control_failed로 안전하게 중단됐다. 이전 버전은 정확한 읽기 예외를 저장하지 않았으므로 이 실행의 직접 원인을 단정하지 않는다. 별도 동시 교체/읽기 시험에서는 정당한 제어 파일에 unsafe control file 오류가 재현됐다.

read_json을 경로 lstat 후 다시 열기에서, O_NOFOLLOW/O_NONBLOCK으로 연 fd의 fstat와 동일 fd 읽기로 바꿨다. [Linux unlink 계약](https://man7.org/linux/man-pages/man2/unlink.2.html)에 따라 원자적 교체로 이름이 사라져도 열린 이전 inode는 마지막 fd가 닫힐 때까지 유효하다. 이때의 nlink=0을 허용하며 심볼릭 링크, 다중 hard link, FIFO와 바이트 상한 위반은 계속 거절한다. 감독기의 이후 제어 오류에는 예외 종류/내용도 보존한다.

fd 직후 교체를 강제하는 결정적 회귀와 기존 guest 수명 시험 14개, 실제 Windows-WSL 연결/launcher 종료/재접속 2개가 통과했다. 별도 20000회 원자적 교체와 1611310회 읽기의 스트레스 시험에서 오류는 0이었다. 최초 중단/이전 소스와 원시 자료를 보존하고 새 supervisor identity로 연구를 새 경로에서 시작했다.
