# 용량 개선과 후속 개발 검증

기준일: 2026-11-11 KST. 승인 기준선 RFAD-D0-3.4를 사용하며 승인 원문은 변경하지 않는다.

## 출처와 기존 프로젝트

기존 12 KiB 근거 예산으로 거절되던 823개 후보를 포함해 전체 3409개 후보를 다시 조회했다. 초기 재검사에서 용량 거절 0, 새 오류 0이며 DB 해시는 유지됐다. JLC 4층의 5개 유전체/9개 물리 행은 문서 57488 bytes, PCBWay 4층의 3개 유전체/7개 물리 행은 38083 bytes로 전체 제안 적용/저장/snapshot/undo/redo/카탈로그 없는 재열기를 통과했다. 두께/Df/적용 대역의 미정값을 채우지 않았다.

저장 상한은 프로젝트 512 KiB, 현재와 과거 선택의 고유 근거 128 KiB/256개다. 적층 조회/제안 128 KiB, 선택 API 384 KiB, RPC와 GUI 프레임 1 MiB로 경계를 맞췄다. 일반 카탈로그 검색은 48 KiB와 페이지 분할을 유지한다. 원문 한 사본, 읽기 예산, 깊이/객체/층/재료 수와 native 작업 예산은 별개다. 이 변경으로 모든 대형 프로젝트나 다층 해석을 지원한다고 선언하지 않는다.

기존 선택 0.1은 그대로 읽는다. 큰 새 선택에 중복 근거가 있으면 선택 0.2의 프로젝트 내부 공유 풀로 같은 근거를 한 번 저장한다. 원문/사본 해시와 채택값/이력은 검증 후 복원되며, 기존 원자 저장과 역명령을 사용한다. 카탈로그나 별도 sidecar 파일이 없어도 출처가 남는다. 상세 구조는 [선택 계약](pcb_selection_contract.md)을 따른다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_stackup_suggestions.py --database .local/pcb-catalog/catalog.sqlite --report .local/new-all-catalog.json
.\.venv\Scripts\python.exe -X utf8 tools/verify_stackup_application.py --database .local/pcb-catalog/catalog.sqlite --report .local/new-stackup-application.json
```

## WSL과 실제 제작 조건

계산 접수 전에 고정 WSL 배포/사용자와 Python 파일 경로를 확인한다. 준비 대기는 별도 60초 예산을 사용하고 취소를 처리하며 worker를 시작하지 않는다. 준비 실패는 not_started로 기록한다. 기존 start 응답 유실은 같은 run/nonce의 status로 복구하며 solve를 중복 제출하지 않는다. 실제 WSL 실행/결과 회수와 launcher 종료 후 재접속/취소 시험을 수행했다. 이번 시험을 PC 재부팅 직후의 cold boot 검증으로 확대하지 않는다.

제작 후보는 RO4350B 2층을 유지한다. [JLC 공식 고주파 서비스](https://jlcpcb.com/pcb-fabrication/high-frequency-pcb)는 현재도 2층, 두께 선택 0.65/0.9/1.65 mm, 1 oz, 녹색 마스크와 ENIG를 안내한다. 그러나 주문 조합의 승인 적층, 코어와 완성 두께의 대응, 실제 동박/마스크/Ni 두께 및 목표 대역의 납품 물성은 이 표만으로 확정되지 않는다. 기존 [후보 기록](jlc_manufacturing_selection.md)의 미정값과 별도 탐색 근사를 유지한다. 실제 제작 확정에는 제조업체 승인 적층 또는 주문별 사양이, 측정 검증에는 시료와 교정/기준면 자료가 필요하다. 주문이나 외부 연락은 수행하지 않았다.

## RO4350B 수렴과 GUI

[탐색 입력](../fixtures/ro4350b_convergence_input.json)과 [연구 조건](../fixtures/ro4350b_convergence_study.json)은 기존 IFA 기하와 미정 납품 재료를 보존한 별도 입력이다. 공개 관측에 대한 명시적 근사 선택을 실제 프로젝트에 적용한 후 같은 snapshot으로 격자 3수준/경계 3수준/시간 종료 2수준을 비교한다. 각 대역 끝 2.400/2.4835 GHz를 포함한 201개 표본을 사용한다. 중복 설정은 같은 실행으로 공유한다. 이전 FR4 fixture의 수렴 판정을 전용하지 않는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_ifa_convergence.py --workspace .local/new-ro-study --report .local/new-ro-study.json --study fixtures/ro4350b_convergence_study.json --catalog .local/pcb-catalog/catalog.sqlite
```

GUI의 `해석 > 수렴 연구 보고서 비교`는 완료 보고서의 설정 행렬과 판정을 읽기 전용으로 표시한다. 원본 봉인과 비교 수학은 기존 연구 도구가 담당한다. 최종 8개 사례/6개 고유 native 계산은 1363.984초에 완료됐다. 마지막 복소 S11 최대 변화는 격자 0.00127626, 경계 0.000100638, 종료 0.000304725로 0.02 기준을 충족했다. 그러나 목표 대역의 내부 공진이 없어 공진 비교와 전체 수렴은 not_established다. 세밀한 격자의 S11은 대역 내 약 -3.426~-2.400 dB이며 -10 dB 정합 목표에 미달한다. 기준을 낮추거나 미확립을 합격으로 바꾸지 않았다. 이 화면에서 보고서를 읽는 것만으로 검증 상태를 승격하지 않는다. 다중 곡선 중첩, 대화형 연구 편집과 추가 스냅/치수 편집은 후속 구현이다.

## NF2FF 참조

고정 자유공간 PEC 다이폴을 기존 WSL 감독 아래 실제 FDTD로 계산하고, 주파수 영역 NF2FF 기록을 후처리했다. theta/phi 각도는 degree이고 복소 E_theta/E_phi, 정규화 전력 패턴, 방사/수락/입사 전력과 지향성/이득/실현 이득을 별도로 보존한다. 효율이 1을 넘더라도 수치를 잘라 맞추지 않는다.

원문은 [openEMS NF2FF](https://docs.openems.de/en/latest/concepts/nf2ff.html), [Python API](https://docs.openems.de/en/latest/python/openEMS/nf2ff.html), [공식 안테나 예제](https://docs.openems.de/en/latest/python/openEMS/Tutorials/Simple_Patch_Antenna.html)를 사용했다. 이상적 반파장 패턴은 [MIT 6.661 강의의 식 3.2.31](https://ocw.mit.edu/courses/6-661-receivers-antennas-and-signals-spring-2003/10025a78ab17e1e0866126246b751d11_ch3new.pdf)을 기준으로 비교한다. 유한 굵기/유한 격자의 60 mm 모델을 이상적 가는 반파장과 비교하는 초기 참조이며 독립 solver 또는 실측 검증이 아니다.

이번 참조의 Dmax는 약 1.65863, 이상적 값 1.6409와 상대 차이 1.081%다. 정규화 패턴 최대 차이는 0.01333, 방사 효율은 약 0.999807이다. 계산 후 경로/출력 권한 처리 오류를 보완하고 최초 계산의 원시 필드 파일을 해시 검증해 재사용했다. 후처리 재실행을 새 FDTD 실행으로 집계하지 않는다. 실패 보고서도 보존한다. 이 독립 참조 도구를 사용자 PCB worker의 NF2FF 연결 완료로 표시하지 않는다. PCB/원형 기판의 방사 기능에는 기록 상자의 기하/재료/PML 거리 검사와 원시 파일/후처리/GUI 연결이 추가로 필요하다.

## 성능과 내부 검증 묶음

`tracewave_canvas_benchmark`는 제품 2D renderer를 wxMemoryDC의 1000 x 700 픽셀에 사용한다. 같은 조건의 선/원호 200개와 3000개, warmup 5회/측정 60회의 p50/p95를 기록한다. 합성 장면의 그리기 비용이며 입력 지연, compositor FPS, 전체 GUI/서비스/worker 메모리나 GPU reset을 대신하지 않는다. 초기 큰 장면에서 발견한 반복 Clip/Flush를 paint 경계로 이동했다. 최종 p95는 일반 2.951 ms, 3000개 장면 37.597 ms였다. 초기 큰 장면 1089.392 ms보다 크게 감소했지만 33.333 ms 목표는 미충족이다. 초기/최종 실행 때 다른 계산 부하가 달랐으므로 속도 개선 비율을 순수 변경 효과로 단정하지 않는다. 최종 비용과 미충족 예산은 실행 기록에 남긴다. 일반 60 fps/대형 30 fps는 계속 초기 목표다.

```powershell
cmake --build build/windows-release --target tracewave_canvas_benchmark
.\build\windows-release\bin\tracewave_canvas_benchmark.exe .local/new-render-benchmark.json
.\.venv\Scripts\python.exe tools/build_internal_bundle.py --output .local/new-internal-validation.zip
```

내부 묶음은 소스/문서/fixture/실행 기록과 Windows GUI, 파일별 SHA-256 명세를 포함하고 ZIP에서 다시 읽어 검증한다. 서비스 가상환경, CAD/WSL runtime과 원본 PCB 카탈로그는 설치 절차로 준비한다. 완전한 설치 프로그램이나 외부 출시 패키지로 표시하지 않는다. 외부 배포 전 의존성 라이선스 고지와 재배포 범위 검토가 필요하다.

## MCP와 EDA

[MCP 2025-11-25 도구 규격](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)의 stdio 연결을 제공한다. initialize/initialized, tools/list와 tools/call을 처리하며 실제 구현된 공개 API만 노출한다. 현재 구현은 이 프로토콜 버전에 한정한다. 새 MCP 버전 지원이나 특정 외부 EDA 플러그인 인증을 주장하지 않는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/mcp_stdio.py --workspace .local/mcp-workspace --catalog .local/pcb-catalog/catalog.sqlite --cad-python .venv-cad/Scripts/python.exe --openems-wsl
```

도구 이름은 `pcb.selection.preview`, `pcb.selection.apply` 등 공개 메서드명이다. arguments는 context/input 및 변경 요청의 request_key/request_key_epoch다. contract_version은 adapter가 고정하고 expected_revision, selection_id와 preview_hash, 명령 ID 및 영수증은 기존 API가 검사한다. 반복 요청에 새 key를 자동 발급하지 않는다. 장시간 실행은 기존 작업 접수 후 job.status/job.cancel을 사용한다. GUI와 같은 workspace writer 잠금을 사용하므로 같은 workspace를 두 서버가 동시에 쓰지 않는다. 외부 EDA의 단위/좌표/net/port 변환은 각 adapter에서 명시적으로 구현해야 한다.

최종 수치와 소스/보고서 해시는 [실행 기록](../runtime_profiles/capacity-and-followup.json)을 따른다.

## 최종 시험 범위

Windows 서비스 회귀는 716개 수집/649개 통과/67개 조건부 스킵, 382.544초다. 실제 GUI는 16개 수집/13개 통과/3개 스킵, 168.346초다. GUI의 스킵은 별도 CAD 구성 및 실제 WSL GUI 실행 조건에 해당한다. CTest 6개는 0.39초, 실제 WSL transport 2개는 19.306초에 통과했다. 전체 자료의 최종 재검사는 3409개 모두 응답, 제한/오류 0이며 384.687초다. 새 공유 저장과 직접 입력, MCP stdio 프로세스, 오류 및 영수증 재생 시험을 포함한다.

GUI 전체 시험 후 수렴 비교 창의 주파수/판정 표시만 사용자용 요약으로 다듬었다. 최종 창은 실제 RO4350B 완료 보고서로 별도 시각 확인한다. 이전 GUI 바이너리의 시험 수치와 최종 표시 보완본의 시각 확인 범위를 구분한다. 이전 실패 로그/참조 계산의 후처리 실패는 .local/capacity-improvement에 함께 보존한다.
