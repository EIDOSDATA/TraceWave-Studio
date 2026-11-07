# 최적화, 정합, 공차, 실측 연계 설계

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

## 1. 기능 경계

연결 요구: AUG-001~004, SYN-001/002, PHY-076~086, OPT-UI-001~003, TUNE-001, MEAS-001. 세부 계산은 EQ-020~038, 사용자 흐름은 FN-017/018/028/032~039를 참조한다. 초기 합성, 고정 변수 스윕, 자동 형상 탐색, 외부 정합 합성, 모델 보정은 서로 다른 study type이다.

## 2. StudyDefinition

| 필드 | 의미와 규칙 |
| --- | --- |
| type | `grid_sweep`, `adaptive_frequency`, `shape_opt`, `matching_synthesis`, `tolerance`, `model_calibration`, `inverse_design` |
| base_snapshot | 모든 후보의 시작점. 실행 중 원본을 편집해도 바뀌지 않음 |
| variables | parameter IDs, dimensions, continuous/integer/categorical, bounds, discretization, allowed values, dependent expressions |
| constraints | geometry/manufacturing/material validity/resource 및 성능 hard constraints |
| objectives | metric IDs, direction/minimize-or-maximize, domain, normalization, weights 또는 Pareto policy |
| scenarios | frequency bands, environment states, load/drive states, tolerance model |
| algorithm | adapter/version/settings/seed, stopping rules, sampling scheme |
| budget | max candidates, max native solves, wall-clock, RAM/disk, concurrency |
| evidence | template/source, approximate model status, validation and acceptance profile |
| failure_policy | invalid geometry, unsupported, timeout, nonconverged를 구별한 처리 |

값과 dimension을 고정한 bounds가 필요하다. design 변수와 공차 random 변수를 같은 인자로 덮어쓰지 않는다. 모든 shape parameter를 동시에 풀지 않고 사용자가 고정한 값과 의존식은 유지한다.

## 3. R1 명시적 스윕

1D/2D와 명시한 Cartesian product를 기본으로 한다. 후보 수를 계산하고 budget 초과를 실행 전에 알린다. 각 후보는 base snapshot+변경 patch+candidate ID로 만들어 재현한다. 동일 물리값은 canonical key로 중복 해석을 피하되 생성 순서와 사용자 지정 grid는 결과 표에 남긴다.

조합 수는 정수 overflow를 검사하고 전체 Cartesian 배열을 RAM에 미리 만들지 않는다. deterministic index에서 후보 patch를 순차 생성하고 bounded queue에 넣는다. 후보 표/이력은 영속 저장소에서 페이지 단위로 조회한다. 기본 worker 동시성은 1이며 추가 병렬 실행은 UI 예약 메모리와 전체 프로세스 예산을 통과한 경우에만 허용한다. EM worker 안의 thread 수까지 포함해 중첩 병렬화를 제한한다.

candidate별 `invalid_geometry`, `unsupported`, `solver_failed`, `nonconverged`, `evaluated`를 저장한다. invalid 후보는 최선 후보 경쟁에서 제외한다. 취소해도 완료 후보와 원본은 보존한다. sweep 결과를 같은 식으로 interpolation해 표시할 수 있으나 실제 계산점과 보간 영역을 구분한다.

## 4. 자동 최적화 전략

R2 단일 목적/가중 목적은 SciPy differential evolution adapter를 우선 검증 대상으로 한다. global optimum 보증으로 표현하지 않는다. 다중 목적은 비지배 archive와 pymoo NSGA-II adapter를 후보로 고정하고 동일 budget, feasibility 계약을 적용한다. 설치/버전/라이선스와 알고리즘 fixture를 통과한 것만 활성화한다. 공식 근거: [SciPy differential_evolution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html), [pymoo NSGA-II](https://pymoo.org/algorithms/moo/nsga2.html).

현재 공개 SciPy API의 rng/seed 호환, updating, workers, integrality와 polish 옵션을 선택 버전에 고정한다. 정수와 범주형 변수는 다르므로 부품명/category를 임의 연속 숫자로 바꾸어 거리를 해석하지 않는다. 지원한 열거 또는 mixed-variable adapter를 사용한다. 초기 population, polishing, 재시도 및 최종 재검증도 evaluation/time 예산에 포함하고 예산 소진 시 추가 실행을 제출하지 않는다. 기본 polishing은 비활성 제안이며 필요 시 계획에서 비용을 따로 예약한다. 비동기 완료 순서가 탐색을 바꾸므로 seed 외에 candidate 생성/반영 순서와 RNG 상태를 저장한다. 같은 seed만으로 병렬 solver의 bitwise 결과를 보장하지 않는다.

optimizer는 후보 생성만 맡고 실제 evaluation은 공통 pipeline을 호출한다. geometry validity->manufacturing constraints->capability->raw cache->EM->network/field->metrics->target 순서다. raw mesh/PML 설정을 후보마다 자동 변경해 결과 비교 조건을 섞지 않는다. 설계 크기 변화로 mesh 정책을 다시 평가한 경우 실제 cell 수와 convergence 수준을 후보에 남긴다.

목적은 deep S11 null 한 점만 최소화하지 않는다. 지정 대역, 환경에서의 violation, efficiency/gain/area/part count 등 사용자가 선택한 지표를 EQ-035 방식으로 무차원화한다. 미평가 metric은 0 penalty가 아니며 해당 후보는 feasibility 미확정이다. 여러 band의 weights와 hard constraints를 보고서에 포함한다.

Pareto에서는 실제 평가한 후보들의 비지배 관계를 제시한다. 가중합 하나를 최적화한 결과를 전체 Pareto front로 부르지 않는다. 최고 점수 후보라도 독립 mesh/경계/시간 재검증과 manufacturability 검사를 거친 뒤 설계 후보를 확정한다.

## 5. 적응형 주파수 표본화

AUG-002는 actual-solve/evaluated-DFT/interpolated-point를 구분한다. frequency-domain solver의 추가 solve, broadband time-domain 기록의 추가 DFT, 저장 안 된 field frequency의 추가 관측/실행을 같은 작업으로 취급하지 않는다.

초기 grid에는 band edge, 사용자 지정 channel, 알려진 resonance 주변을 넣는다. complex S의 보간 잔차/곡률, phase 변화, threshold crossing, input source의 SNR 및 bandwidth를 사용해 새 점을 선택한다. 고Q 공진을 거친 grid가 놓칠 수 있으므로 max gap/verification probes를 두고 보간만으로 목표 전체대역 통과를 확정하지 않는다. 선택 규칙, 예산, 실제 평가 주파수, 미평가 구간을 남긴다. adaptive sampling이 mesh/시간 종료 수렴을 대신하지 않는다.

## 6. 정합회로 구조 합성

입력은 검증한 antenna network, source/load impedance/전력 조건, topology 후보(L/pi/T/사용자 graph), 허용 부품 수, 부품 catalog와 모델, footprint/공차/정격, 목표 대역과 환경이다. 다음 순서로 수행한다.

1. 네트워크의 port order, wave/Z0/reference plane을 정렬한다.
2. 지원 topology를 열거하고 open/short/DNP 상태를 명시한다.
3. 이상 부품으로 탐색할 경우 ideal-seed 상태로 저장한다.
4. 실제 부품 Q/ESR/ESL/SRF/S-parameter 또는 검증한 모델로 재평가한다.
5. EQ-028~032의 연결/termination 계산으로 network response, power partition, 가능한 경우 loaded field를 계산한다.
6. physical pad/trace가 바뀌는 후보는 새 EM snapshot으로 전달한다.
7. 부품 선택, 회로 상태, BOM/assembly variant를 같은 candidate ID에 연결한다.

안테나의 원래 radiation efficiency를 matching network 손실과 부정합이 달라진 이후의 total efficiency로 그대로 복사하지 않는다. S-only antenna network에는 field basis가 없을 수 있으므로 realized gain 변화는 계산 가능한 정보와 가정을 먼저 확인한다. 부품 정격과 비선형 power dependence가 필요한 경우 linear small-signal 모델의 범위를 표시한다.

## 7. 공차와 강건성

각 분포의 단위, 상하한, nominal, sigma/shape parameter, source를 저장한다. correlation matrix는 symmetric/positive semidefinite 여부를 검사한다. 같은 glass/resin/lot 조건의 Dk와 두께 상관 등을 독립 random 변수라고 자동 가정하지 않는다. distribution을 모르면 exploratory scenario로 명시하고 통계적 수율 보증으로 표시하지 않는다.

R2 기본 경로는 명시적 corner set, independent distributions, 검증된 correlated normal sampling이다. 다른 marginals, copula는 해당 adapter의 검증 후 활성화한다. 물리 bounds 밖 sample 처리(reject/truncate/resample) 정책이 통계 분포를 바꾸므로 기록한다.

각 sample은 nominal candidate와 trial ID, seed/substream, parameter values를 가진다. 사전에 고정한 전체 N에 대해 pass/fail/unknown을 분리한다. 물리 형상이 제조 제약을 위반한 것이 확인되면 해당 요구에 대한 fail이고, solver 실패/미수렴으로 성능을 알 수 없으면 unknown이다. unknown을 삭제하거나 재시도 성공 표본으로 임의 교체해 분모를 바꾸지 않는다. unknown이 있으면 pass/N부터 (pass+unknown)/N까지의 가능한 관측 범위와 실패율을 표시하며 이 범위를 통계 신뢰구간이라고 부르지 않는다. 모든 IID Bernoulli 표본의 판정이 확보된 경우에만 EQ-036의 명시한 Wilson 신뢰구간을 제공한다. LHS/quasi-MC, 적응 표본 및 결과에 따른 조기 중단에는 별도 정당화된 추정법이 필요하다. [SciPy의 신뢰구간 방법](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html)의 기본값은 exact이므로 Wilson을 의도할 때 method를 명시한다.

## 8. 측정 가져오기와 정렬

필수 정보는 raw 파일, port order, Z0/파 정의, frequency unit, calibration type/date/reference plane, fixture/cable, device revision/serial, assembly/environment이다. 누락값을 표시하고 사용자가 아는 조건을 추가할 수 있게 한다. raw 파일은 immutable로 보존한다.

정렬 chain은 파일 해석->포트 순열/극성->정규화 변환->검증된 fixture de-embedding/plane shift->좌표/위상 중심 정렬->주파수 grid 비교 순으로 명시한다. 이 순서는 데이터의 native definition에 따라 달라질 수 있으므로 실제 적용 연산 순서를 artifact에 기록한다. 단순 curve shift로 좋은 일치를 만들고 fixture 보정으로 표시하지 않는다.

주파수 interpolation은 complex 데이터에 수행하고 magnitude/phase 처리법, unwrap mask, 유효 대역을 남긴다. off-grid 비교에서는 원시 계산점/측정점과 보간점을 구분한다. model과 measurement의 케이블/배터리/케이스 조건이 다르면 차이를 먼저 보여준다.

## 9. 모델 보정과 독립 검증

보정 변수는 측정 가능한 공차/물성 범위로 제한한다. Dk, 기판두께, feed de-embedding, 케이스 거리 등을 동시에 풀면 식별성이 낮아질 수 있으므로 sensitivity와 parameter correlation을 보고한다. 별도 holdout frequency/assembly/시제품/방향 데이터를 지정한다. 학습/보정에 사용한 데이터의 오차 감소를 독립 예측 정확도라고 표기하지 않는다.

목적함수는 complex residual의 실수/허수, 단위, noise floor와 weighting을 선언한다. 깊은 S11 null에서 dB 차이가 발산하거나 phase가 미정인 구간은 사전 mask로 처리하고 사후에 좋은 구간만 골라내지 않는다. 측정 공분산을 쓰는 경우 단위와 PSD를 검사하며 특이 행렬을 무조건 역행렬로 바꾸지 않는다. 같은 시료의 인접 주파수는 상관될 수 있으므로 holdout frequency만 분리한 결과를 독립 시제품 검증과 같은 수준으로 표시하지 않는다. 가능하면 시료/조립/환경 단위로 훈련과 검증을 분리하고 선택에 사용한 데이터를 최종 독립 검증에 재사용하지 않는다.

VNA S11 비교는 정합 관련 검증이다. 방사 효율, 패턴, 절대 이득에 필요한 OTA/기준안테나/전력 교정 조건을 별도로 저장한다. UWB는 Tx/Rx pair와 propagation/reference plane, NFC는 loaded coil/position, RFID는 chip state/power, AoA는 phase/manifold 조건의 전용 검증을 사용한다.

## 10. surrogate, 역설계, AI

surrogate는 학습 데이터의 입력 영역, solver/version, mesh quality, 측정 여부, validation split, 오차를 보존한다. 범위 밖 결과는 추정으로 표시하며 후보 선정 후 full-wave로 재검증한다. inverse design은 임의 polygon/level-set/pixel 등의 representation, 최소 feature/filter, connectivity constraint, manufacturing projection을 명시해야 한다. 현재 openEMS adapter에 adjoint가 자동 제공된다고 가정하지 않는다. 검증된 gradient가 없는 경우 derivative-free 탐색과 별도 비용 예산을 사용한다.

AI 보조는 근거와 변경 patch를 제안할 수 있지만 실제 해석/실측이 없는 결과를 생산하지 않는다. 외부 AI 호출은 데이터 이동 설정과 요청 내용을 명시하고 offline core를 대체하지 않는다.

## 11. 각 study의 완료 산출물

plan/settings, 후보별 parameter patch, constraints/diagnostics, actual run/artifact refs, objective/metric definitions, seed/budget consumption, Pareto/선정 이유, 재검증 상태, BOM/assembly 연결, 미완료 항목을 묶는다. 그래프만 내보내지 않는다. 주요 검수 연결은 최적화 VT-016/023/024/025, 정합 VT-012/022/026, 측정 VT-010/030, 재현 VT-019/029이며 각 상세 조건은 [검증 명세](14_RFAD_검증과_수용_기준.md)를 따른다.
