# 사용자 PCB의 선택적 방사 계산

같은 실행에서 유전체/도체 흡수 손실을 독립 적분하려면 [전체 전력 수지 옵션](pcb_power_balance.md)을 함께 요청한다. 기존 방사 결과의 추론 손실과 독립 적분은 구분하며 과거 결과에 손실값을 임의 보완하지 않는다.

갱신일: 2026-11-11 KST. 설계 기준선 RFAD-D0-3.4를 유지한다. 이 기능은 사용자 PCB 단일 포트 worker의 선택 옵션이며 제작 및 측정 검증 상태를 바꾸지 않는다.

## 입력과 기록 상자

기존 `settings`를 그대로 사용할 수 있다. 방사가 필요할 때만 다음 객체를 추가한다. 주파수는 기존 해석 대역 안의 증가하는 1~3개 수치이고 각도 간격은 각각 5/10/15/30 degree다. GUI에서는 한 주파수를 입력하며 API와 MCP에서는 세 주파수까지 요청할 수 있다.

```json
{"radiation": {"frequency_hz": [2441750000], "theta_step_deg": 15, "phi_step_deg": 15}}
```

계획 생성 시 최종 Yee 격자의 각 축에서 PML 8개 격자와 추가 공기 2개 격자를 제외한 면을 선택한다. 직사각/원형 기판 외곽과 물리 적층 전체가 6면 안에 엄격히 포함되어야 한다. 공기가 부족하면 `E_GEOMETRY`로 거절하며, 사용자 설정을 자동으로 늘리거나 기록 상자를 재료 안으로 옮기지 않는다. 외부 매질은 진공이다. 마스크, 케이블, SMA launch나 주변 물체가 자동 추가되지 않는다.

API에서는 선택적 `box_clearance_mm`로 기판에서 기록 면까지의 최소 거리를 지정할 수도 있다. 기존 격자에 바깥 방향으로 정렬하며 새 격자선을 추가하지 않는다. 실제 거리와 PML 분리를 계획에 기록하고 위상 중심을 물리 기판 중심으로 고정한다. 기존 옵션을 생략한 입력은 위의 자동 상자를 유지한다. 독립 변화와 초기 기준은 [방사 수렴 연구](pcb_radiation_convergence.md)를 따른다.

prepare는 같은 계획의 `radiation_recording.json`과 주파수 영역 E/H dump가 들어간 XML만 만든다. native 실행은 준비된 XML 바이트를 그대로 사용한다. 6면 각각의 E/H HDF5 파일 12개를 기존 포트/통계/XML/로그 6개와 함께 해시 봉인한다. 한 면이라도 없거나 중복되면 완료 결과를 게시하지 않는다.

## 결과와 전력의 의미

`radiation.json`은 별도 산출물이다. theta=0~180, phi=0~360 미만의 각도 축, 복소 E_theta/E_phi의 실수/허수 쌍, 편광 합산 정규화 전력, 방향별 지향성과 주파수별 최대 지향성/이득/실현 이득/방사 효율을 저장한다. 위상 중심은 기존 자동 상자에서는 상자 중심, 명시적 거리 옵션에서는 물리 기판 중심이며 m 단위다. 평가 반지름은 1 m다. theta는 +z 극각이고 phi는 +x에서 +y 방향으로 증가한다. 최종 native NF2FF HDF5도 별도 보존한다.

포트는 `Uinc=(U+R*I)/2`, 수락 스펙트럼은 `0.5*Re(U*conj(I))`, 입사 스펙트럼은 `0.5*abs(Uinc)^2/R`를 사용한다. 방사 효율은 Prad/Paccepted, 이득은 D*효율, 실현 이득은 D*Prad/Pincident다. 각도 표본에서 얻은 최대 지향성이므로 각도 해상도에 따른 오차가 있다. 효율 1 초과나 수락 전력이 입사 전력을 넘는 경우는 `requires_review`로 남기며 100%로 자르지 않는다.

기존 포트와 주파수 영역 필드는 펄스 Fourier 규약 `2*dt*sum(...)`을 공유한다. 따라서 이 구현은 원시 전력 스펙트럼을 `W*s^2`, 복소 E를 `V*s/m`로 명시하고 절대 출력 전력은 `absolute_power_w=null`로 둔다. 공통 s^2 배율은 효율과 이득의 비율에서 상쇄된다. 사용자에게 정현파 RMS 입력 전력을 받거나 1 W 급전으로 재정규화하지 않았다.

이 단위 해석은 [공식 pulse DFT 구현](https://github.com/thliebig/openEMS/blob/master/python/openEMS/utilities.py)과 [주파수 영역 field DFT 구현](https://github.com/thliebig/openEMS/blob/master/Common/processfields_fd.cpp)의 시간 간격 배율에서 도출했다. 일반 [NF2FF 문서](https://docs.openems.de/en/latest/concepts/nf2ff.html)의 전력/필드 표기와 이 제품의 펄스 스펙트럼 표기를 구분한다. 과거 독립 다이폴 참조 산출물의 필드명은 역사적 기록으로 유지한다.

## 재후처리와 읽기 전용 조회

`postprocess_only`는 동일 PreparedPlan의 봉인된 12면과 포트 자료에서 다시 계산한다. FDTD를 재실행하거나 기존 결과를 덮어쓰지 않는다. 기록하지 않은 주파수는 추가할 수 없다. 결과의 큰 배열을 작업 완료 응답이나 journal 메타데이터에 중복하지 않고 `radiation_summary`와 산출물 참조만 게시한다. 기존 `result.open`의 `selection=all`에서 두 방사 산출물을 조회할 수 있다.

`solver.radiation`은 `contract_version=rfad.api/2.0`, `context={project_id}`, `input={artifact_id, frequency_index?, theta_offset?, theta_limit?}`를 받는다. 인덱스/offset 기본값은 0, limit 기본값과 상한은 5다. 응답은 `rfad.radiation-chart/0.1`, 원본 SnapshotRef, 전체 phi 축, 요청한 theta 행, 복소 필드/전력/지향성, 지표 및 `next_offset`을 포함한다. 각 응답은 128 KiB 이하다. 방사 없는 과거 결과나 다른 프로젝트, 범위 밖 요청은 거절한다. 해석기 없는 서비스에서도 봉인 검증 후 조회할 수 있다. MCP 도구도 같은 공개 메서드를 읽기 전용으로 노출한다.

GUI의 `NF2FF 기록`은 기본 해제다. 선택 후 해석 조건과 방사 주파수/각도 간격을 입력한다. 완료 후 `해석 > 방사 패턴 조회`는 주파수, phi 절단면, 정규화 전력/지향성/이득/실현 이득을 전환한다. theta 절단면의 연결선은 시각적 연결이며 새 계산 표본이 아니다. 표시 하한 -40 dB 아래의 원시 값은 그대로 저장한다. 현재 화면은 2D 절단면이며 대화형 3D 방사 곡면은 후속이다. 창을 닫은 뒤 늦게 온 응답은 버리고 조회 시간 초과를 표시한다.

## 검증 범위와 남은 작업

실제 고정 WSL2 런타임에서 원형 기판/원호의 세 주파수 계산, 동일 raw 재후처리, 해석기 없는 재열기, 실행 중 편집의 snapshot 보존과 취소 후 이전 결과 보존을 확인했다. 별도 사각 기판은 3개 주파수와 5 degree 격자에서 주파수당 8개 페이지의 복원 및 재후처리를 통과했다. IFA 실행 fixture도 2.44175 GHz에서 같은 경로를 통과했다. GUI의 실제 페이지 조회, 그래프 paint와 phi/지표 전환, 취소 및 서비스 재시작 시험을 통과했고 원형 사례의 실제 창에서 이전 개정 표시와 전력 균형 경고도 시각 확인했다. 최종 결과와 소스 해시는 [실행 기록](../runtime_profiles/pcb-radiation.json)을 따른다.

이 절은 당시 실행 경로의 검증 기록이다. 추가된 [NF2FF 상자 거리/각도/격자/전력 예산 연구](pcb_radiation_convergence.md)는 별도 수치 판정으로 보존한다. `computed_unvalidated`, `physics_validated=false`는 유지한다. 독립 체적/도체 흡수 적분을 포함한 전체 에너지 수지, 독립 해석기 대조, 실측 검증, 실제 납품 물성 및 SMA/마스크/케이블 조건은 후속이다. 계산 fixture의 명시적 시험 물성을 실제 제조사 값이나 승인 IFA의 미정값으로 복사하지 않는다.
