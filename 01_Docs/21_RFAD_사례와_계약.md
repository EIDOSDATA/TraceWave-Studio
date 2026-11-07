# 계약 예시, 정상 및 실패 시나리오

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

## 1. 예시의 지위

이 문서는 후속 코드/단위/계약 검토를 위한 합성 입력 명세다. 여기에 이름을 붙인 example JSON은 현재 제공되지 않으며 구현 단계에서 생성하고 검수할 예정이다. openEMS 실행 결과나 실제 비콘 실측이 아니다. 기존 Nordic G031 geometry source는 별도의 추출 레코드를 사용한다. 이 예시의 2.4GHz target은 성능을 보장하는 설계값이 아니다.

## 2. geometry-only 프로젝트

후속 fixture 이름은 `example_arc_geometry_only.json`으로 예약한다. 입력은 보드 원점 (0,0,0), 오른손 좌표, 원형 보드 반지름 12 mm, 유전체 범위 z=[0,1.530] mm, 상면 도체 z=[1.530,1.565] mm이다. 원호 중심은 (0,0), 중심선 반지름 9 mm, 시작각 0 rad, CCW sweep pi/2 rad, 선폭 1 mm, 끝단은 radial butt cap으로 정의한다. 하부 동박과 GND, feed, port, RF 물성은 없으며 없는 항목을 숨은 값으로 보완하지 않는다.

중심선 길이 L=9*pi/2 mm, inner radius=8.5 mm, outer radius=9.5 mm이다. 원호 도체 면적은 4.5*pi mm^2, 두께 0.035 mm의 부피는 0.1575*pi mm^3이다. 보드 외곽과 원호 외곽의 최소 이격은 2.5 mm이다. 이 산술 기대값은 geometry 생성 코드와 독립 계산하고 비교 허용오차는 해당 CAD profile에서 정한다. 2.4 GHz를 목표 metadata로 저장하더라도 공진 주파수나 정상 해석 결과를 뜻하지 않는다.

| 동작 | 기대 결과 |
| --- | --- |
| 파일 저장, 재열기 | 성공, 미정 field 상태 유지 |
| 2D geometry/3D solid 생성 | 정의한 기하 범위에서 가능, 재질은 unknown metadata |
| EM 실행 계획 | E_MATERIAL_UNKNOWN, E_PORT로 차단 |
| S11/효율 표시 | 결과 없음. 임의 demo 곡선 생성 금지 |
| geometry-only STEP | 해당 profile을 명시한 경우 생성 가능. RF/material omission을 sidecar에 기록 |
| manufacturing 승인 | 제조 profile과 연결/급전 조건이 미완비이므로 완료로 표시하지 않음 |

원호가 보드 안에 들어가는지와 실제 RF 정합이 맞는지는 별도다. 정상 저장 fixture와 의도된 해석 실패 fixture를 같은 파일로 검사할 수 있다.

## 3. 수식 정의 확인 fixture

후속 `example_single_port_power.json` fixture에 명시할 입력은 incident=1 W, reflected=0.25 W, radiated=0.60 W다. accepted=0.75 W, dissipated=0.15 W, radiation efficiency=80%, total efficiency=60%다. directivity=3이면 gain=2.4, realized gain=1.8이며 세 값은 선형 비율이다. |S11|=0.5일 때 S11_dB는 약 -6.0206 dB, return loss는 약 6.0206 dB, VSWR=3이다.

이 값은 단일포트, 수동, 명시된 기준 전력 fixture다. multiport/load/complex wave의 일반 검증을 대신하지 않는다. reference vectors와 단위/특이점 검사는 [수식](09_RFAD_수식과_물리_모델.md) 및 [VT-020](14_RFAD_검증과_수용_기준.md)을 따른다.

## 4. revision과 snapshot 시나리오

아래의 생성/계획/준비 단계는 [11번 API 분류](11_RFAD_해석기_어댑터_계약.md)에 따른 TaskRef의 완료 operation_result를 받은 뒤 다음 단계로 진행한다. 접수 ACK를 최종 SnapshotRef나 PreparedPlan으로 사용하지 않는다.

1. revision A에서 SnapshotRef S1을 생성한다. S1은 별도 UUID와 revision A, content hash를 가진다.
2. S1에서 AnalysisPlan P1을 만들고 prepare로 PreparationArtifact Q1과 PreparedPlan PP1을 생성한다.
3. PP1을 실행해 raw R1을 얻는다. 동시에 사용자가 trace width를 바꾸면 revision B가 된다.
4. R1의 provenance는 S1/A에 유지된다. B의 현재 결과처럼 표시하지 않는다.
5. B에서 폭을 원래 값으로 되돌렸더라도 실제 physics/config/toolchain hash가 일치하는지 확인한 뒤 compatible reuse를 결정한다.

## 5. 외부 정합만 바꾸는 시나리오

raw n-port와 복소 field basis가 충분하고 physical copper/port/lumped boundary가 동일한 상태에서 외부 network L/C 값을 바꾼다. network.derive가 새 네트워크와 port incident vector/field coefficients를 만들고 metrics/field 합성을 다시 계산한다. raw EM은 재사용 가능하다. 실물 pad 배치나 inline native lumped element가 바뀌면 raw 무효화가 필요하다.

field basis가 없으면 network response만 계산하고 loaded radiation은 미평가로 표시한다. 정합이 좋아졌다는 이유만으로 기존 gain에 임의 보정값을 더하지 않는다.

## 6. 주요 실패 fixture 목록

| 입력, 사건 | 기대 처리 |
| --- | --- |
| 원호 r<=0, inner radius<=0, NaN | 단위/정의역/geometry 진단 |
| IFA short 삭제 | topology invalid, 해당 template 유효성 실패 |
| source Dk가 미정/충돌 | 값 선택/가정 기록 전 mandatory 실행 차단 |
| tan_delta-derived sigma와 동일 손실 성분의 중복 입력 | loss partition 검토 필요 오류 |
| um<->mm 중복 변환 | expected thickness/scale fixture 실패 |
| user input expression의 cycle | cycle path와 field IDs 출력 |
| unknown native field scale | 절대 power/gain 평가 차단 |
| singular Z conversion, zero denominator | mask/status/conditioning diagnostic, 0으로 조작하지 않음 |
| GND 포함 NF2FF 표면/잘못된 경계 | solver-specific preflight 실패 |
| 취소 또는 disk 부족 중간 파일 | partial 격리, 완료 manifest 미발행 |
| bottom layer가 두 번 미러됨 | independent roundtrip axis/topology 실패 |
| STEP에서 filled via/extra pad height 발생 | physical profile 비교 실패 |
| archive path traversal, 중복 경로 | import 거부, 원본 상태 보존 |
| stale snapshot, 동시 편집 충돌 | E_CONFLICT 또는 과거결과 표시 |

## 7. 후속 구현에서 만들 실제 예제

실제 solver fixture에는 완전한 stackup, 재질, ground, port, boundary, excitation, mesh, 종료, normalization, 프로젝트 source를 포함한다. 패치/전송선/원호/IFA를 각각 선정하고 reference expectation의 근거를 구분한다. geometry-only JSON에 hidden default를 추가해 가짜 verified fixture로 승격하지 않는다. 실제 실행 후 native 파일과 결과, 수렴 보고서를 별도 version으로 저장한다.

## 8. 출력 중 변경과 취소의 합성 시나리오

revision A의 snapshot에서 STEP/도면/manifest 패키지를 생성하는 동안 사용자가 revision B를 편집한다. A의 출력은 A의 경로/metadata에 남기고 현재 B의 결과로 표시하지 않는다. 임시 파일 쓰기, reader 검수, manifest 발행의 각 경계에서 취소/디스크 부족/crash를 주입한다. 최종 artifact가 생긴 뒤 늦은 취소가 도착한 경우에도 실제 완료와 취소 상태가 한 번만 확정되어야 한다.

검수 대상은 마지막 정상 저장본 보존, partial 파일의 격리, 작업/프로세스 종료 확인, 재개방 복구, 중복 발행 방지다. 같은 파일시스템의 원자적 rename과 다른 볼륨 복사는 구분한다. VT-018/019의 AC subcase로 연결하며 수행하지 않은 상황은 미실행으로 둔다.

## 9. GUI 후보의 동일 입력 시나리오

wxWidgets와 Avalonia 후보는 같은 geometry/result fixture, renderer 품질, worker 경로와 완료 기능으로 비교한다. 빈 창, 대표 2D/3D 편집, 큰 결과 탐색, 반복 프로젝트 열기/닫기, solver/export 동작 중 취소와 worker 재시작을 포함한다. Qt는 후보에서 제외한다. 입력 acknowledgment와 실제 화면 반영 및 작업 완료를 구분한다.

전체 process tree의 working set/private commit, GPU memory, peak/steady state와 반복 종료 후 회수, cold/warm startup, p95/p99 입력 지연과 frame time을 [GUI 선정과 성능 설계](24_RFAD_GUI_선정과_성능_설계.md)의 단일 계약으로 기록한다. 이 문서는 새 수치 합격선을 별도로 정의하지 않는다. GUI-SPIKE-001..007과 VT-018/028/029의 검수 근거를 연결하고, 예상 메모리나 프레임워크 명칭을 실제 성능 측정으로 표시하지 않는다.
