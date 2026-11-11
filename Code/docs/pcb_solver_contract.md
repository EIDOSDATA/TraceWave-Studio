# 사용자 PCB의 단일 포트 openEMS 해석

갱신일: 2026-11-11 KST. `rfad.openems.pcb-single-port/0.1`은 사용자가 저장한 PCB 입력을 WSL2 openEMS로 전달하는 초기 실행 profile이다. 승인 기준선 RFAD-D0-3.4를 유지한다. 실제 IFA의 정식 수렴/제작/측정 검증을 완료했다는 의미는 아니다.

## 입력과 원형 기판

사각 기판과 중심/반지름이 명시된 원형 기판을 지원한다. 외형은 구리 선/원호와 독립이다. 원형 PCB를 선택했다고 접지 원판, 패드, 동박이나 원호가 자동 생성되지 않는다. 기판 밖의 도체를 잘라 맞추지 않고 거절하며 선의 폭/둥근 끝과 원호 전체 범위를 검사한다.

기판과 도체는 같은 평면 좌표계의 불변 스냅샷에서 mm로 투영한다. 원형 유전체는 CSXCAD Cylinder, 사각 유전체는 Box로 생성한다. CAD의 원형 외곽과 고체는 Open CASCADE의 정확 형상을 사용하고, EM 도체 곡선은 명시한 허용 오차 안에서 polygon으로 근사한다. 이후 Yee 격자 오차가 별도로 존재하므로 CAD 곡선의 정확성과 RF 계산 정확도를 동일시하지 않는다.

유전체와 외측 도체 적층, 선/원호, hole을 가진 접지 polygon, 원형/회전 사각 pad와 명시적 through-PTH via, net/재료와 단일 lumped port를 지원한다. 층 위치/두께, 전도도, 물성 유효 대역과 포트 조건이 필요하다. 상대 유전율과 손실 탄젠트는 유전체에 필수이며, conducting sheet가 소비하지 않는 도체의 두 물성은 미정이어도 된다. 체적 via 도체에는 전도도와 상대 유전율이 필요하다. 미정값을 FR4/구리의 대표 상수로 채우지 않는다. 내부 동박, blind/buried via, 마스크/접착층, 비항등 좌표 변환, 다중 포트와 NF2FF는 이 profile의 지원 범위 밖이다. 형상/도금/급전의 상세 계약은 [도체와 IFA 확장](copper_features.md)을 따른다.

## 물성 및 급전 모델

- 기존 유전체 `isotropic_constant`는 사용자의 독립 전도도에 대역 중심 주파수의 `2*pi*f*epsilon0*epsilon_r*tan_delta`를 더한다. 두 항이 같은 손실을 중복 표현하지 않는다는 입력 가정이 필요하다. 새 `isotropic_constant_total_tan_delta`는 총 Df만 등가 전도도로 변환하며 원본 전도도를 소비하지 않는다. 두 모델 모두 stop/start는 2 이하이고 명시한 적용 대역이 전체 평가 대역을 포함해야 한다. 상수 kappa는 중심에서만 입력 Df와 일치하며 광대역 분산 모델은 후속이다. 상세는 [재료 손실 모델](material_loss_models.md)을 따른다.
- 동박은 인접 유전체 경계면으로 투영한 `AddConductingSheet`다. 사용자가 입력한 전도도와 실제 두께를 모두 전달하며 두께를 0으로 버리거나 PEC로 교체하지 않는다. 기하학적 체적 동박과 동일한 모델은 아니므로 sheet 위치/두께/전도도 및 근사 내용을 계획과 소비 보고서에 기록한다.
- 포트에는 양극/기준 도체 UUID, 저항, 기준면 설명, 유효 대역, 방향/극성 및 `excitation_box.start/stop`의 3D Quantity가 필요하다. 동일 sheet 면의 x/y 또는 서로 다른 sheet 면의 z 축 방향 1차원 gap, 극성 +1을 지원한다. 시작점은 기준 도체, 끝점은 양극 도체에 닿아야 한다. 모든 gap은 실제 Yee edge 두 개 이상으로 표현해야 하며 x/y gap은 설정 grid_mm의 두 배 이상이어야 한다. z gap은 양끝과 중간의 local mesh line을 추가해 검사한다. 임의 위치의 기본 포트를 만들지 않는다. 같은 net인 IFA도 실제 열린 gap과 접지/단락부/방사체의 연결이 맞으면 허용한다.
- native polygon에서도 단자 접촉과 열린 gap의 도체 침범을 검사한다. 다른 net 또는 재료의 접촉과 허용 오차 이내 간격은 보수적으로 거절한다. 이는 초기 형상 검사이며 최종 제조 DRC, 전류 경로 수용이나 일반적인 접속 엔진을 대신하지 않는다.

물성은 사용자가 지정하는 설계 변수이며 제품 기본값이 아니다. 내부 실행 fixture의 수치는 명시적 시험 가정으로만 저장한다. 승인된 최초 IFA의 미정 물성/제작/측정 조건은 그대로 남긴다.

일반 EM 입력 점검도 위 필수 물성 목록을 공유하고 급전 좌표 누락을 안내한다. 도체 sheet의 미사용 유전율/손실을 요구하지 않는다. 입력 문제가 없으면 input_status=valid지만 solver_ready=false이며, 실제 지원 형상/연결/격자 조건은 solver.plan에서 추가 확인한다. 후속 계획 검증이 필요하다는 사실 자체를 입력 오류로 표시하지 않는다.

## API와 실행

공통 준비/실행/취소/봉인/재접속 계약은 [solver worker](solver_contract.md)를 따른다. `solver.plan`에서 analysis_profile을 PCB profile로 지정하고 grid_mm 대신 settings를 전달한다.

```json
{
  "frequency_hz": {"start": 2400000000, "stop": 2483500000, "count": 101},
  "grid_mm": 1,
  "air_padding_mm": 30,
  "curve_tolerance_mm": 0.05,
  "max_timesteps": 30000,
  "end_criterion": 0.00001
}
```

위 값은 GUI 초기 수치 설정이며 특정 설계의 정확도를 보장하지 않는다. 계획에서 최소 도체 폭/급전 간격/파장, 층 수, polygon 점 수와 격자 자원 상한을 검사한다. 주파수는 1 MHz~50 GHz, 표본 수는 3~201, 격자 최대 간격은 0.05~5 mm, air padding은 1~200 mm이면서 10 grid 이상이다. 곡선 허용 오차는 0.001~0.25 mm이면서 grid/2 이하이며 최대 1500000 격자점과 도체 64개로 제한한다. 이 범위의 모든 입력을 검증한 것은 아니다. 수렴 확인에 필요한 격자/경계 거리 선택은 사용자의 후속 검토 대상이다.

수렴용 격자 확장은 optional `mesh_policy={kind: graded_air, air_cell_mm: 6, growth_ratio: 1.5}`로 모델 근처의 grid와 외부 공기의 간격을 구분한다. 기존 필드가 없는 계획은 원래 전역 격자를 유지한다. 말단 PML8은 고정 간격이므로 이 설정에서는 두께가 48 mm다. `air_padding_mm`는 계산영역의 바깥까지 거리이며 PML 시작면까지의 빈 공간이 아니다. padding 90/96/102 mm는 각각 PML 앞 42/48/54 mm 여유에 대응한다. 외부 공기와 계면은 실제 성장률 상한을 검사하지만 기존 내부 임계선은 보존하므로 모든 내부 cell에 1.5 상한을 강제하지 않는다. 실제 비율과 정책 근거를 계획/준비 metadata에 공개한다. 지원 범위와 비교 가드는 [IFA 수렴 계약](ifa_convergence.md#격자와-pml의-독립-제어)을 따른다.

grid_mm을 줄여도 이미 더 짧은 임계 구간은 그대로 남을 수 있다. 실제 cell 수 증가와 설정 series의 안정성을 모든 최소 특징의 국부 세분화 또는 점근 정확도의 증명으로 확대하지 않는다. 이번 비교에는 Richardson 외삽을 사용하지 않는다.

prepare는 실제 CSXCAD와 포트를 만들어 `pcb.xml`, 실제 mesh 통계, 소비 보고서, 정규화와 runtime 출처를 봉인하며 FDTD를 실행하지 않는다. analysis는 같은 XML 바이트를 실행하고 종료 조건을 검사한다. raw 파일은 `port_ut_1`, `port_it_1`, `openEMS_stats.txt`, `openEMS_run_stats.txt`, `native.log`, `pcb.xml`이다. 후처리 전용은 완료 raw를 재사용하고 solver를 다시 실행하지 않는다.

정규 결과는 `rfad.openems-pcb-result/0.1`이며 주파수별 복소 S11과 입력 임피던스, S11 dB와 VSWR를 포함한다. S11 크기가 1 이상이면 VSWR는 null, S11이 0이면 유한 dB가 없어 null이다. 해당 값을 0이나 임의 큰 값으로 치환하지 않는다. GUI도 계산 불가 구간을 이어 그리지 않는다.

assessment의 `status=computed_unvalidated`, `physics_validated=false`를 유지한다. `converged=true`는 요청한 시간영역 에너지 종료 조건을 충족했다는 뜻이다. 격자/경계/모델의 정식 수렴이나 안테나 성능 합격을 뜻하지 않는다. 최대 step 도달, 취소나 종료 조건 미달은 완료된 정상 결과로 게시하지 않는다.

## 검증과 후속 범위

`fixtures/pcb_worker_smoke.json`은 반지름 8 mm의 원형 기판, 선/원호와 2 mm 급전 gap을 사용하는 실행 fixture다. 8~12 GHz의 31점, epsilon_r=2.2, tan_delta=0.002, 도체 전도도 58000000 S/m는 시험 가정이며 FR4 또는 승인 IFA의 확정 조건이 아니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_pcb_worker.py --workspace .local/pcb-worker-verification/manual-001 --report .local/pcb-worker-verification/manual-001.json --exercise-cancel
```

이 도구는 공개 명령으로 설계를 만들고 저장/스냅샷/계획/준비/실행/독립 후처리/표시 조회/재시작을 확인한다. 선택적 취소 시험은 실제 guest 종료와 이전 결과 보존을 확인한다. 단위 시험에서는 누락/변조/외곽/접촉을, 실제 native 시험에서는 공식 LumpedPort.CalcPort와의 후처리 일치를 확인한다. 실제 실행 결과와 로그는 [개발 상태](development_status.md)에 기록한다.

`fixtures/ifa_feed_smoke.json`은 40 x 60 mm의 접지면/빈 영역/패드/급전선/단락부를 가진 IFA 실행 사례이며 `fixtures/pth_worker_smoke.json`은 중공 도금 비아의 별도 실행 사례다. 위 도구의 `--fixture`로 선택한다. 물성과 도금 치수는 명시적 시험 가정이다. 실제 급전 도체는 소비하지만 SMA/실장/케이블/디임베딩은 포함하지 않는다.

단일 포트 IFA의 격자/경계 거리 study는 [별도 수렴 계약](ifa_convergence.md)에서 관리한다. 이번 fixture의 사전 acceptance는 실제 mesh 최소 3수준, 마지막 비교의 max abs(Delta S11_complex) <= 0.02, 동일 공진 branch의 상대 변화 <= 1%다. 최초 study의 모든 run은 2.0~3.0 GHz의 같은 201점과 2.5 GHz 손실 환산 중심을 사용한다. 내부 공진 bracket이 없거나 대응이 불명확하면 해당 지표는 미평가이며 임의 0%로 처리하지 않는다. 임피던스 변화는 진단으로 함께 보존한다.

이 study는 `tools/verify_ifa_convergence.py`와 [고정 manifest](../fixtures/ifa_convergence_study.json)를 사용한다. mesh 0.5/0.45/0.4 mm는 padding 102 mm에서, 경계 90/96/102 mm는 grid 0.4 mm에서, 종료 1e-5/1e-6은 grid 0.4 mm/padding 102 mm에서 비교한다. curve_tolerance=0.025 mm와 max_timesteps=100000을 고정한다. 8개 비교 행은 같은 anchor를 공유하므로 고유 FDTD 실행은 6개다. 모든 공개 solver.plan을 먼저 봉인/검증하고 하나라도 불능이면 FDTD를 시작하지 않는다.

`--resume`은 같은 입력과 현재 worker identity에서 기존 요청/완료 자료를 재사용한다. `--reassess-only`는 solver 환경 없이 완료 결과를 읽어 현재 판정기로 다시 평가한다. 원래 raw/plan/result와 개별 판정 기록은 immutable이며 진행 report와 파생 CSV는 갱신 가능하다. 정확한 CLI와 종료 코드 0/1/2의 의미는 수렴 계약을 따른다. 201점에는 목표 끝 2.4835 GHz가 없고 기준면도 local gap이므로 SMA 기준의 전 대역 -10 dB 목표 합격을 선언하지 않는다.

runtime identity는 제품 소스 묶음 전체를 포함하므로 판정기만 변경해도 이전 `--resume`이 거절될 수 있다. 완료 결과는 현재 판정기의 `--reassess-only`로 별도 평가할 수 있다. 이전 실행의 정확한 재개에는 당시 소스/설치 identity가 필요하고, 현재 소스의 새 native 계산은 새 workspace/report를 사용한다.

study 실행과 비교는 현재 CLI/JSON/CSV 경로다. GUI의 단일 완료 결과 그래프는 제공하지만 study 행렬 관리와 여러 run의 수렴 비교 화면은 후속이다.

공진을 포함하는 [별도 study](../fixtures/ifa_convergence_resonance_study.json)는 1.6~2.6 GHz의 201점과 2.1 GHz 환산 중심을 사용한다. 이상적 port 대역을 명시적 가정으로 바꾼 별도 fixture/snapshot이며 최초 study를 덮어쓰지 않는다. 두 연구의 결과는 손실 환산/여기 조건이 달라 직접 비교하지 않는다. 동일 acceptance와 공간/종료 행렬을 각각 실행하며 실제 판정은 각 보고서로 확인한다.

최초 2.0~3.0 GHz study는 6개 native 실행을 완료했고 마지막 비교의 복소 S11 변화는 세 축 모두 0.02 이하였다. 표본 최소값이 2.0 GHz 대역 끝에 있어 내부 반사 최소점 추적은 미평가이고 전체 상태는 `not_established`다. 이 반사 최소점 정의를 X=Im(Z)=0의 전기적 공진과 동일시하지 않는다. 수치와 재판정/재개 근거는 [실제 결과 기록](ifa_convergence.md#최초-2030-ghz-연구의-실제-결과)을 따른다.

별도 1.6~2.6 GHz study도 6개 native 실행을 완료했다. 마지막 복소 S 변화와 반사 최소점의 보수적 bracket 이동이 기준 안이어서 세 축/전체는 `established`다. 표본 최소점 1.920 GHz는 X=0의 공진을 뜻하지 않으며 이 계산의 2.400 GHz 표본은 -10 dB 정합 목표를 충족하지 않는다. 이는 fixture 전용 수치 안정성으로 제한하고 물리/실측 상태는 그대로 유지한다. [별도 연구의 실제 결과](ifa_convergence.md#별도-1626-ghz-연구의-실제-결과)에 수치와 근거를 기록한다.

최종 판정기는 mesh series의 실제 외곽/PML 시작면 고정과 boundary series의 실제 확대/공통 내부 격자 보존을 검사하고 두 series의 PML cell 수/폭 일치를 확인한다. 두 완료 연구를 이 가드로 재판정해 모두 통과했으며 원래 지표/상태와 native 자료는 그대로 유지됐다. 새 판정 파일만 추가했으며 FDTD는 재실행하지 않았다.

시간 종료 민감도는 별도 series로 비교하고 PML cell 수 변화는 이 study에 포함하지 않는다. 실제 급전/재료/측정 조건의 대조, 원형 PCB/원호, NF2FF/이득/효율은 후속이다. 실행 fixture나 특정 수치 지표의 통과를 실물 정확도 및 전체 검증 순서의 완료로 간주하지 않는다.
