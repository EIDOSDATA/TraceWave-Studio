# 단일 포트 IFA의 격자와 경계 거리 수렴

갱신일: 2026-11-11 KST. 이 문서는 명시적 가정으로 만든 [IFA 실행 fixture](../fixtures/ifa_feed_smoke.json)의 수치 민감도 검증 계약이다. 승인 기준선 RFAD-D0-3.4의 EQ-037/038, VT-011과 NP-02를 따른다. `01_Docs`의 승인 기록은 수정하지 않는다. 아래 acceptance는 이번 fixture에 한해 실행 전에 고정하는 기준이며 모든 안테나의 보편 정확도 기준이 아니다.

최초 실행 기준은 [study manifest](../fixtures/ifa_convergence_study.json)의 `ifa-local-gap-grid-boundary-2026-11/0.1`이며 반사 최소점을 포함하는 별도 대역 연구도 아래에 구분한다. 격자/거리/종료 series와 완료 자료 재개/재판정 도구를 구현했다. 두 연구의 실제 결과는 아래 절, 실행 근거는 [개발 상태](development_status.md)와 [runtime 기록](../runtime_profiles/ifa-convergence-wsl.json)에 보존한다. 실행하지 않은 행이나 아직 없는 결과를 통과로 표시하지 않는다.

## 목적과 상태의 분리

이번 대상은 40 x 60 mm 보드의 접지 polygon/빈 영역, 방사체, 단락부, 급전선과 pad 및 이상적인 로컬 lumped gap이다. 유전율/손실/전도도와 적층은 fixture에 기록한 시험 가정이다. 실제 SMA mating plane, launch, 정합 소자, 마스크, 케이블, 측정 교정 또는 실물 재료의 재현 모델이 아니다. 별도 PTH fixture의 실행이나 얇은 도금 손실 정확도도 이번 IFA 결과로 대신 검증하지 않는다.

| 상태 | 이번 검증에서의 의미 |
| --- | --- |
| solver 실행 완료 | 정상 native 종료와 원시 파일 봉인을 확인 |
| 시간 에너지 종료 | 요청한 end_criterion 도달. 격자/경계/시간 종료 민감도 합격과 별개 |
| 격자 민감도 | 같은 물리 입력과 경계에서 실제 격자를 세분화한 비교 |
| 경계 거리 민감도 | 같은 모델 내부 격자와 PML 설정에서 외부 거리를 늘린 비교 |
| 공진 미평가 | 동일한 내부 공진 branch를 bracket하지 못했거나 대응이 불명확 |
| 실물/목표 합격 | 이번 계산으로 판정하지 않음 |

기존 result의 `assessment.converged=true`는 시간 에너지 종료에 대한 기록이다. 이 필드를 격자/경계 수렴의 증거로 재해석하지 않는다. 원래 결과의 `computed_unvalidated`와 `physics_validated=false`를 유지하고 별도 study 보고서의 `numerical_stability`에 `established`/`failed`/`not_established`, 지표별 결과, 비교 run과 기준을 기록한다. 이번 matrix는 시간 종료 민감도도 독립 비교한다. PML cell 수 변화나 NF2FF/방사량을 시험하지 않았으면 해당 축은 미평가다. 이번 검증만으로 VT-011 전체나 R1 물리 수용 완료를 선언하지 않는다.

## 공통 입력과 비교 대역

한 study 안의 모든 run은 같은 physical snapshot과 원본 hash, 재료/형상/포트/기준면/정규화, solver/runtime/source hash를 사용한다. 달라질 수 있는 수치 설정은 해당 series에 명시한 항목뿐이다. 도체, gap, 참조면이나 물성을 수정한 run은 동일 수렴 series에서 제외한다.

최초 study의 평가 대역은 모든 run에서 2.0~3.0 GHz, 균일 201점으로 고정한다. 간격은 5 MHz다. 현재 상수 손실 모델의 환산 중심 주파수와 Gaussian 중심은 모두 2.5 GHz로 같게 유지한다. 대역 설정을 바꾸면 손실 전도도와 여기 신호도 바뀌므로 기존 2.400~2.4835 GHz smoke 결과를 이 series의 일부로 재사용하지 않는다. 단순히 주파수 점을 늘린 것을 새 FDTD 계산이나 더 긴 transient 기록으로 표시하지 않는다.

201점은 2.400 GHz를 포함하지만 2.4835 GHz는 포함하지 않는다. 승인 IFA의 목표는 SMA 기준면에서 2.400~2.4835 GHz 전체의 S11_dB <= -10 dB이며 이번 로컬 gap 수렴 대역과 다르다. 이 보고서는 목표 대역 합격을 미평가로 유지한다. 향후 목표 판정에는 정확한 양끝 표본과 미평가 구간/주파수 세분화/불확도 규칙 및 동일한 SMA 기준면이 필요하다.

curve_tolerance, 층의 sheet 근사, gap 위치와 방향, 실수 50 ohm 기준, Fourier 규약과 원시 후처리는 series 안에서 고정한다. 곡선 polygon 근사의 변화와 Yee 격자 변화도 서로 다른 오차 원인이다.

## 공진을 포함하는 별도 대역 연구

내부 반사 최소점을 bracket하지 못한 study는 원래 대역/결과/판정을 보존한다. 공진을 포함하는 대역으로 옮길 때에는 이전 표본을 섞거나 첫 study를 덮어쓰지 않고 별도 입력과 study를 만든다. [별도 study manifest](../fixtures/ifa_convergence_resonance_study.json)의 `ifa-local-gap-reflection-minimum-2026-11/0.1`은 [별도 IFA 입력](../fixtures/ifa_convergence_input.json)의 이상적 lumped port 유효 대역을 명시적 시험 가정으로 1.6~2.6 GHz로 설정한다. 측정된 SMA/커넥터 대역이라는 의미는 아니다.

이 연구의 공통 평가 대역은 1.6~2.6 GHz의 균일 201점이며 손실 환산 중심과 Gaussian 중심은 2.1 GHz다. 아래 격자/거리/종료 행렬과 acceptance는 그대로 유지하지만 2.0~3.0 GHz 연구와 물리 소비 조건/여기가 달라지므로 수렴 지표를 서로 직접 계산하지 않는다. 두 study의 실제 완료/판정은 각 보고서에 별도로 남긴다.

1.6 GHz의 자유공간 lambda/4는 약 46.84 mm다. PML 앞 여유 42 mm인 near 사례는 이 경험칙보다 가깝고 48/54 mm인 middle/far 사례는 더 멀다. 가까운 사례를 포함한 거리 민감도 검사이며 세 거리 모두 경험칙을 만족한다고 주장하지 않는다. 이 연구도 2.4835 GHz를 표본에 포함하지 않고 local gap 기준면을 유지하므로 목표 정합/실측 합격은 미평가다.

## 이번 fixture의 acceptance

승인 문서 [14번의 후보 기준](../../01_Docs/14_RFAD_검증과_수용_기준.md#threshold-profiles)은 보편 합격값으로 승인된 숫자가 아니다. 이번 내부 IFA fixture에서는 그 후보 중 아래 값을 명시적 acceptance로 채택한다. 결과를 본 뒤 문턱을 낮추거나 실패 run을 제거하지 않는다. 기준을 바꾸는 경우 새로운 profile/version과 사유를 남긴다.

| 항목 | 사전 고정 기준 | 계산과 판정 |
| --- | --- | --- |
| 격자 수준 | 최소 3개 | 서로 다른 실제 격자이며 세분화 순서를 확인. 설정 이름만 다른 동일 격자를 반복하지 않음 |
| 복소 S11 변화 | 마지막 비교의 max abs(S_fine-S_coarse) <= 0.02 | 모든 공통 주파수의 복소수 차이. dB 차이 또는 abs(S)의 차이로 대체하지 않음 |
| 동일 공진 branch 변화 | 마지막 비교의 abs(f_fine-f_coarse)/abs(f_fine) <= 0.01 | 같은 정의와 추적 가능한 내부 bracket이 있는 경우만 평가 |
| 경계 거리 비교 | 같은 복소 S/공진 기준 적용 | 별도 series로 기록. 격자 수렴 결과로 경계 검사를 대체하지 않음 |
| 시간 종료 민감도 | 2수준, 같은 복소 S/공진 기준 적용 | 실제 격자와 경계를 유지하고 end_criterion만 1e-5에서 1e-6으로 변경 |
| 입력 임피던스 | 복소 차이와 R/X 변화 기록 | 이번 profile에서 별도 합격 문턱은 추가하지 않음. S11 기준의 대체 지표로 쓰지 않음 |

모든 인접 수준의 변화와 마지막 비교를 함께 보존한다. 공진 후보는 유일한 엄격한 내부 반사 최소점이자 전체 최소점일 때만 선택하고 그 양옆 표본으로 bracket한다. 어떤 branch를 비교했는지 기록한다. 두 bracket에서 가능한 상대 이동의 보수적 상한까지 1% 이하여야 공진 기준을 통과한다. 표본 최소점의 이동 자체가 1%를 넘으면 failed이며, 표본 이동은 작아도 bracket 상한이 크면 주파수 해상도 부족으로 not_established다. band 끝의 최소값, 평탄한 구간, 공진의 부재/소실/교체, 여러 내부 최소점 또는 대응 모호성을 0% 변화로 계산하지 않는다. 반사 최소점과 Im(Z)=0 교차는 같은 정의라고 가정하지 않는다. bracket 폭과 분해능을 기록하며 보간한 추정치를 독립 계산 표본으로 표시하지 않는다.

유한 complex S와 Z, 동일한 주파수 순서/표본 수, 유효한 입사 spectrum, 정상 native 종료가 비교의 전제다. NaN/Inf, 누락 표본, 작은 입사 신호, 0 전류, timeout/취소/최대 step 도달 또는 hash 불일치는 합격 자료가 아니다. dB가 정의되지 않는 S=0이나 특이 VSWR도 임의 유한값으로 바꾸지 않는다.

## 격자와 PML의 독립 제어

기존 `grid_mm` 전역 격자와 짧은 airbox는 실행 smoke를 위한 설정이다. PML_8을 유지한 채 전역 격자를 줄이면 PML의 물리 두께도 바뀌므로 그 결과를 순수한 격자 민감도로 설명할 수 없다. 40 x 60 mm IFA의 넓은 공기 영역을 모두 작은 cell로 채우면 기존 자원 상한에도 빠르게 도달한다.

수렴용 확장은 모델 근처의 격자를 세분화하고 외부 공기에서는 점진적으로 간격을 늘리는 optional `mesh_policy={kind: graded_air, air_cell_mm: 6, growth_ratio: 1.5}`를 사용한다. 말단 8 cells는 각각 고정 6 mm 간격이며 PML 물리 두께는 48 mm다. 기존 mesh_policy 없는 계획은 원래 격자 의미를 유지한다. 정책의 air_cell_mm은 grid_mm 이상 10 mm 이하이며 Gaussian 여기 상한 주파수의 자유공간 파장/10 이하다. growth_ratio는 1.05~1.5이고 padding은 air cell의 정수배이자 최소 12배이며 실제 전이 뒤에 PML8과 공기 cell이 남는지도 검사한다.

`air_padding_mm`는 모델 외곽에서 계산영역의 가장 바깥쪽까지 거리다. PML 시작면까지의 빈 공간과 다르다. 말단 8 cells가 모두 6 mm인 경우 padding 90/96/102 mm는 각각 42/48/54 mm의 PML 앞 여유에 대응한다. 계획값뿐 아니라 실제 mesh line으로 여섯 면의 PML 두께와 모델-PML 간격을 확인한다. 모델 내부의 임계선, sheet, 급전 gap과 연결은 거리 series에서 보존해야 한다. 거리 확장 전후의 보드 내부와 공통 비-PML 구간에 실제로 같은 격자선이 남는지도 비교한다.

판정기는 mesh series에서 실제 계산영역의 외곽과 PML 시작면 좌표가 고정됐는지 확인한다. boundary series에서는 두 면이 실제로 바깥으로 확장됐는지, 보드 내부와 공통 비-PML 격자가 같은지 확인한다. 두 series 모두 PML cell 수와 각 cell 폭도 같아야 한다. 폭 비교의 1e-9 mm 절대 허용치는 native 격자 생성의 부동소수점 후조건을 위한 값이며 RF 오차나 제조 공차가 아니다. 설정 이름만 같고 실제 경계/PML이 다른 비교는 수치 안정성 합격으로 처리하지 않는다.

2 GHz의 자유공간 lambda/4는 약 37.47 mm다. PML 앞 초기 여유 42 mm는 이 경험칙을 고려한 선택이며 충분한 경계 거리의 증명은 실제 확대 비교로 남긴다. 공식 문서는 방사체와 PML의 거리를 확보하고 더 멀리 둔 실행으로 민감도를 확인하도록 안내한다. [openEMS Boundary Conditions](https://docs.openems.de/en/latest/concepts/bc.html)

격자의 최소/최대 간격, 인접 cell 비율, 각 축 실제 line 목록, native cell 수, PML 간격, 실제 timestep과 반복 수/모사 시간을 기록한다. 외부 공기와 내부 계면의 실제 인접 cell 비율은 growth_ratio 이하인지 생성 후 검사한다. 기존 내부 임계선 분할은 보존하므로 내부 전체에 같은 비율 상한을 강제하지 않는다. `interior_growth_postcondition_enforced=false`와 각 축 `axis_max_adjacent_ratio`로 이를 공개한다. 이 fixture의 내부 x축에는 1.5보다 큰 비율이 있으므로 전역 모든 cell이 1.5 이하라고 주장하지 않는다. sheet와 port 정렬, native Yee 표현의 도체 연결 검사도 각 run에서 수행한다. 실제 timestep은 native solver 값을 사용하고 일반 CFL 식으로 강제하지 않는다. [openEMS Mesh](https://docs.openems.de/en/latest/concepts/mesh.html)

`grid_mm`는 모델 내부 임계 구간을 나눌 때 사용하는 최대 간격 설정이며 모든 cell의 실제 크기가 아니다. 이미 그보다 짧은 임계 구간은 설정을 줄여도 그대로 남을 수 있다. 세 수준의 실제 cell 수가 증가한다고 모든 최소 특징/도체 edge/층 방향 간격이 각각 세분화된 것은 아니다. 이번 결과는 이 고정 격자 생성 정책과 설정 series의 민감도 근거이며 모든 국부 오차의 수렴, Richardson 외삽 또는 점근 정확도를 입증하지 않는다.

## 확정 실행 행렬

아래 행렬은 study manifest에 사전 고정한다. 공통 curve_tolerance_mm=0.025, max_timesteps=100000이며 기본 end_criterion=1e-5다. 모든 고유 사례의 공개 solver.plan을 먼저 완료해 봉인하고 실제 격자 수/PML 여유/자원 상한을 검증한 뒤 prepare/FDTD를 시작한다. 하나라도 계획할 수 없으면 FDTD를 시작하지 않는다. 진행표에는 `all_plans_validated_before_execution=true`를 기록한다. 지원 상한 초과를 숨기거나 자동으로 geometry/물성/acceptance를 완화하지 않는다.

| series | 모델 근처 grid_mm | air_padding_mm | end_criterion |
| --- | --- | --- | --- |
| mesh_coarse/medium/fine | 0.5/0.45/0.4 | 102 | 1e-5 |
| boundary_near/middle/far | 0.4 | 90/96/102 | 1e-5 |
| termination_base/tight | 0.4 | 102 | 1e-5/1e-6 |

mesh_fine, boundary_far와 termination_base는 모든 설정이 같은 anchor로 연결된다. 8개 비교 행은 고유 설정 6개와 실제 FDTD 실행 6개로 처리하며 새 계산을 했다고 중복 집계하지 않는다. 실행 전에 세 anchor의 설정이 정확하게 일치하는지 확인한다. PML cell 수 자체의 민감도는 이 거리 matrix에서 바꾸지 않으며 미시험 상태를 남긴다. grid 설정 간 비율만으로 Richardson 차수나 점근 수렴을 주장하지 않는다.

## 실행, 재개와 원본 보존

진입점은 `tools/verify_ifa_convergence.py`다. 공개 프로젝트/스냅샷/solver.plan/prepare/submit 경계를 사용하는 실행과 완료 자료의 resume/reassess 경로를 구분한다. prepare와 analysis의 개별 timeout 예산은 300초다. 최초 실행은 기존 workspace/report를 덮어쓰지 않는다.

수렴 study는 현재 CLI와 JSON/CSV 보고서로 사용한다. wxWidgets GUI의 기존 단일 결과 S11/VSWR/임피던스 그래프와 구분하며, GUI에서 study 행렬을 관리하거나 여러 run을 겹쳐 보는 수렴 비교 화면은 아직 구현하지 않았다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_ifa_convergence.py --workspace .local/ifa-convergence/manual-001/workspace --report .local/ifa-convergence/manual-001/report.json
.\.venv\Scripts\python.exe -X utf8 tools/verify_ifa_convergence.py --workspace .local/ifa-convergence/manual-001/workspace --report .local/ifa-convergence/manual-001/report.json --resume
.\.venv\Scripts\python.exe -X utf8 tools/verify_ifa_convergence.py --workspace .local/ifa-convergence/manual-001/workspace --report .local/ifa-convergence/manual-001/report.json --reassess-only
```

위 명령은 각각 최초 실행, 같은 연구 재개, 완료 자료만 재판정하는 대안이다. 기본 study는 위 manifest이며 별도 사전 정의에는 `--study <경로>`를 사용한다. `--resume`과 `--reassess-only`는 동시에 사용할 수 없다. 종료 코드 0은 수치 안정성 established, 1은 계산 자료가 있지만 기준 미달 또는 미확립, 2는 실행/입력/자료 오류다. report.status=completed는 연구 계산/평가 절차 완료이며 수치 합격을 뜻하지 않는다.

공진 대역의 별도 연구는 새 workspace/report에 `--study fixtures/ifa_convergence_resonance_study.json`을 지정한다. 이후 해당 연구의 resume/reassess에도 같은 study 경로를 명시한다. 최초 연구의 보고서에 다른 study를 연결하면 입력 hash가 달라 거절한다.

각 run은 독립 AnalysisPlan/PreparedPlan과 결과/raw manifest를 유지한다. study에는 profile/version/hash, fixture/snapshot hash, matrix, 변경 변수, runtime/source hash, 실제 실행 여부, 원시/정규 결과 참조와 metric 계산 근거를 남긴다. 원래 raw 파일, native XML, plan과 완료 결과는 immutable이다. `report.json`은 진행 상태와 최신 참조를 원자적으로 교체하는 mutable 진행표다.

각 판정은 `report.assessments/<UUID>.json`의 별도 immutable 파일로 기록하며 입력 artifact 참조, 현재 판정기 소스 hash, study/fixture hash와 평가 결과를 포함한다. 진행표는 이 파일의 SHA256/bytes와 assessment_history를 누적한다. 새 판정은 이전 판정 파일을 덮어쓰지 않는다. `report.samples.csv`는 현재 직접 계산 표본을 보간 없이 내보내는 파생 파일이며 bytes/SHA256을 진행표에 기록한다. 이 CSV와 진행표를 원본 raw나 불변 판정 파일로 취급하지 않는다.

resume은 이전 완료 자료의 hash/설정과 현재 worker runtime/source가 정확히 일치할 때만 이를 재사용한다. 요청 key/epoch를 먼저 저장하고 응답 저장 전에 중단되어도 기존 작업을 다시 조회한다. 실패/취소/불완전 run을 정상 완료로 복구하지 않으며 실행 중 상태를 새 작업으로 조용히 대체하지 않는다. WSL의 interrupted/outcome_unknown 슬롯은 [worker 복구 계약](solver_contract.md#wsl-소유권과-복구)에 따라 실제 종료 확인을 먼저 수행한다.

runtime identity는 worker가 캡처한 제품 소스 묶음 전체를 포함한다. FDTD가 직접 호출하지 않는 판정기 파일만 수정해도 code_files hash가 달라져 이전 연구의 `--resume`은 거절될 수 있다. 이전 실행을 정확히 이어 확인하려면 캡처 당시 소스/설치 identity를 복원해야 한다. 현재 소스로 새 native 계산을 하려면 새 workspace/report의 별도 연구로 시작한다. 변경한 소스를 기존 연구에 조용히 섞지 않는다.

reassess-only는 solver runtime 설치 없이 완료된 immutable 결과를 읽고 현재 판정기로 지표를 다시 계산한다. 모든 사례가 완료되어 있어야 하며 study/fixture/workspace가 다르면 거절한다. FDTD를 실행하거나 없던 주파수/공진을 생성하지 않는다. 이 동작은 raw probe의 DFT 재실행과도 구분한다.

따라서 판정기 보완 후에는 완료 자료에 `--reassess-only`를 적용할 수 있다. 이때 새 immutable 판정 기록은 현재 판정기 hash를 가지며 원래 run의 runtime/source와 원시 자료는 그대로 남는다. FDTD에 사용한 소스와 나중에 결과를 평가한 소스를 구분한다.

결과를 읽을 때 진행표의 normalized_result가 공개 result.open의 봉인된 파일 참조와 정확히 일치하는지 확인한다. 결과가 참조하는 snapshot/plan ID/plan hash/runtime/settings도 해당 study 사례와 대조한다. 같은 runtime으로 계산한 다른 설계의 유효 파일도 현재 study 결과로 끼워 넣을 수 없다.

공식 FAQ는 긴 감쇠 시간, 너무 가까운 흡수 경계와 작은 cell이 실행 시간/정확도에 미치는 영향을 설명한다. 이번 acceptance를 통과시키기 위해 end_criterion을 결과 확인 후 완화하지 않으며, timeout/최대 step 도달은 성공 수렴으로 바꾸지 않는다. [openEMS FAQ](https://docs.openems.de/en/latest/faq.html)

## 최초 2.0~3.0 GHz 연구의 실제 결과

2026-11-11에 최초 study의 모든 고유 계획을 먼저 봉인/검증하고 6개의 WSL native 실행을 완료했다. 8개 비교 행은 같은 anchor를 공유한다. 마지막 인접 쌍의 결과는 아래와 같다. 복소 S11 차이는 선형 복소수 기준이며 dB 차이가 아니다.

| 비교 | 마지막 쌍 | max abs(Delta S11_complex) | 복소 S 기준 0.02 | 내부 반사 최소점 추적 |
| --- | --- | --- | --- | --- |
| 격자 | 0.45 -> 0.4 mm | 0.002126812981639143 | 통과 | 미평가 |
| 경계 거리 | padding 96 -> 102 mm | 0.00017435405712947202 | 통과 | 미평가 |
| 시간 종료 | 1e-5 -> 1e-6 | 0.0006781502202648916 | 통과 | 미평가 |

이 대역에서 표본의 |S11| 최소값은 2.0 GHz의 왼쪽 끝에 있으므로 내부 최소점을 bracket하지 못했다. 동일 branch의 상대 이동은 null/미평가이며 0%로 기록하지 않는다. 세 축과 전체의 `numerical_stability.status`는 `not_established`다. 계산/보고 절차는 completed이고 CLI 종료 코드는 1이다. 이는 실행 오류나 복소 S 기준 실패와 다르다.

현재 보고서의 `resonance` 필드는 |S11|의 내부 반사 최소점 추적을 뜻한다. 입력 리액턴스 X=Im(Z)=0으로 정의하는 전기적 공진과 같은 값이라고 가정하지 않는다. 이번 판정에서 X=0 교차를 독립 검증한 것은 아니다. 반사 최소점을 찾지 못한 이 연구를 물리적 공진이 없다는 증거로 사용하지 않는다.

근거는 `Code/.local/ifa-convergence-final/report.json`, 같은 폴더의 `report.assessments/<UUID>.json`, `report.samples.csv`와 workspace의 봉인 산출물이다. 로컬 원시 자료를 Git 배포 파일과 혼동하지 않는다. 전체 로그는 `Code/.local/ifa-convergence-final-run.log`에 보존한다. 1.6~2.6 GHz의 별도 study 결과는 이 기록을 덮어쓰지 않고 따로 남긴다.

당시 worker identity의 같은 완료 자료에서 실제 `--reassess-only`와 `--resume`을 수행하여 판정, 결과 참조와 CSV가 동일함을 확인했다. 봉인 파일 54개의 hash를 대조했고 journal job 수는 21개로 유지되어 추가 FDTD를 실행하지 않았다. 각 재판정은 이전 파일을 유지한 채 assessment_history에 추가되었다. 근거는 `Code/.local/ifa-convergence-final/reassessment-evidence.json`이다.

## 별도 1.6~2.6 GHz 연구의 실제 결과

별도 입력/대역의 6개 native 실행도 완료했다. 모든 고유 계획을 먼저 봉인/검증했고 마지막 쌍에서 아래 결과를 얻었다. 각 run의 prepare/analysis 관찰시간 합은 1294.141초이며 제품 성능 예산 합격을 뜻하지 않는다.

| 비교 | 마지막 쌍 | max abs(Delta S11_complex) | 복소 S 기준 0.02 | 반사 최소점 이동 기준 |
| --- | --- | --- | --- | --- |
| 격자 | 0.45 -> 0.4 mm | 0.004142448096995212 | 통과 | 통과 |
| 경계 거리 | padding 96 -> 102 mm | 0.00018085721259261466 | 통과 | 통과 |
| 시간 종료 | 1e-5 -> 1e-6 | 0.0008264865944490979 | 통과 | 통과 |

세 마지막 비교에서 내부 반사 최소점은 양쪽 모두 1.920 GHz의 직접 계산 표본이며 양옆 bracket은 [1.915, 1.925] GHz다. 표본 위치의 변화는 0이지만 무한 정밀도의 0% 이동을 주장하지 않는다. bracket으로 계산한 보수적 상대 이동 상한은 0.005221932114882533, 약 0.5222%로 사전 기준 1% 이하다. 격자/경계/종료 세 축과 전체의 `numerical_stability.status`는 `established`이고 CLI 종료 코드는 0이다. 이는 이번 fixture, 고정 격자 정책, 대역과 초기 acceptance에 한정된 수치 안정성이다.

최종 기본 run의 해당 표본은 S11 약 -11.863 dB, Z 약 68.751+j24.620 ohm이다. 리액턴스가 0이 아니므로 이 반사 최소점을 X=Im(Z)=0의 전기적 공진으로 부르지 않는다. 같은 run의 2.400 GHz 표본은 약 -2.177 dB로 -10 dB 조건을 만족하지 않는다. 이 결과를 2.4 GHz 정합 목표 달성으로 표시하지 않으며, 정확한 목표 끝 2.4835 GHz 표본과 실물 SMA 기준면/측정 근거도 없다. 모든 원래 결과는 `computed_unvalidated`, `physics_validated=false`를 유지한다.

근거는 `Code/.local/ifa-resonance-convergence-final/report.json`, 해당 `report.assessments`/CSV/workspace와 [runtime 기록](../runtime_profiles/ifa-convergence-wsl.json)이다. 이 연구에서도 캡처 당시 worker identity로 실제 resume/reassess를 확인했다. 판정/결과 참조/CSV가 유지됐고 봉인 파일 54개의 hash를 대조했으며 journal job 수 21개가 그대로여서 추가 FDTD는 없었다. 근거는 같은 폴더의 `reassessment-evidence.json`이다. 이후 판정기 변경으로 runtime identity가 달라지는 경우에는 앞 절의 재판정/재개 구분을 적용한다.

두 연구의 native 실행 완료 후 실제 경계/PML 비교 가드를 판정기에 추가하고 원래 완료 결과만 재평가했다. 모든 mesh/boundary 비교의 추가 가드가 통과했고 수치 지표와 최종 상태는 각각 `not_established`/`established`로 유지됐다. native run과 CSV, 이전 immutable 판정 파일은 바뀌지 않았으며 각 history에 새 판정만 추가했다. 근거는 두 연구 폴더의 `post-guard-reassessment-evidence.json`이다. 이 과정에서 FDTD를 다시 실행하지 않았다. 최종 판정기의 소스 hash는 원래 worker 소스와 구분해서 기록하며, 현재 소스의 `--resume`에 과거 worker identity를 혼합하지 않는다.

## 후속 검증

격자와 경계 비교가 안정되어도 실제 물성, mask/거칠기, SMA launch/급전선/정합 부품과 측정 기준면이 달라지면 새로운 physical snapshot에서 필요한 검증을 다시 한다. 사용자 입력인 재료 물성을 이 fixture의 가정으로 확정하지 않는다. VNA 교정/케이블/지그/시료와 불확도 자료가 없으면 실측 일치 상태를 부여하지 않는다.

NF2FF, 이득/효율/절대 전력, 방사 측정과 독립 solver 비교는 별도 증거가 필요하다. 이번 S11/임피던스 안정성으로 방사 효율 또는 실물 정합 목표 달성을 대신 평가하지 않는다. 원형 PCB/원호의 별도 검증 순서도 유지한다.
