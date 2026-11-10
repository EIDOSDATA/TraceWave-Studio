# openEMS 개발 환경 참조 검사

`tools/check_openems_environment.py`는 Linux의 openEMS 0.37.0 / CSXCAD 0.7.0 Python binding과 native 라이브러리를 실제 계산으로 확인한다. 제품 solver adapter, IFA, 방사 패턴 또는 전체 RF 정확도 검증 완료를 뜻하지 않는다.

## 모델과 비교 기준

20 x 10 x 80 mm의 진공 직사각 도파관을 만든다. 측면은 PEC, 양 끝은 PML 8 cells이며, TE10 모드로 10 GHz 중심의 Gaussian pulse를 인가한다. 두 측정면은 z=15 mm, 65 mm이고 간격은 50 mm다. 9.5~10.5 GHz 31개 표본을 계산한다. 이 대역은 TE10 차단 주파수 약 7.495 GHz보다 높고 다음 모드 차단 주파수 약 14.990 GHz보다 낮다.

측정한 복소 전압과 전류에서 반사/전달 계수와 임피던스 U/I를 구한다. 임피던스 기준은 port.ZL을 그대로 복사하지 않고 `Z_TE10 = Z0 / sqrt(1 - (fc/f)^2)`, `fc = c0/(2a)`로 따로 계산한다. 전달 위상 기울기로 구한 군지연도 `L / (c0 * sqrt(1 - (fc/f)^2))`와 대조한다. S 계수의 분리는 openEMS의 모드 포트 후처리를 사용하므로 완전히 독립된 두 solver 비교는 아니다.

고정 버전의 [WaveguidePort 원본](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/python/openEMS/ports.py#L583)은 U/I probe를 start/stop의 중간이 아닌 stop 위치에 배치한다. 입력 포트의 stop=15 mm, 수동 포트의 stop=65 mm이므로 비교 거리는 50 mm다. CalcPort의 ref_plane_shift를 지정하지 않아 추가 위상면 이동도 하지 않는다. Fourier 변환은 exp(-j*2*pi*f*t)이므로 군지연은 위상 기울기의 음수다. 수동 포트는 반대 방향이므로 전달파는 그 포트의 uf_ref로 읽는다.

| 항목 | 사전 설정한 개발 검사 상한 |
| --- | --- |
| 반사 진폭 | 0.15 |
| 전달 진폭의 1 대비 절대 오차 | 0.08 |
| 복소 임피던스의 해석식 대비 상대 오차 | 0.08 |
| 군지연의 해석식 대비 상대 오차 | 0.10 |
| 두 격자 전달 진폭 차이 | 0.03 |
| 두 격자 임피던스 차이 / 해석식 임피던스 | 0.04 |

목표 최대 cell 크기는 1 mm와 0.75 mm다. 모서리와 포트 측정면은 두 격자 모두 같은 좌표에 놓는다. 각 실행은 20,000 time steps 상한과 1e-7 종료 에너지 조건을 요청하며 CPU thread는 2개다. 실제 native 통계의 시간 간격/반복 수/계산 시간을 기록하고 반복 수가 상한에 도달하면 실패로 처리한다. 필드 dump와 GUI 실행은 하지 않는다. 두 격자 확인은 제한된 일관성 검사이며, 점근 수렴 차수나 모든 PML/시간/메시 민감도를 입증하는 정식 수렴 시험은 아니다. 특히 PML의 cell 수는 같고 물리 두께는 격자와 함께 달라진다.

작은 모델은 기본 4초 wall-clock 간격의 종료 조건 평가에 영향을 받을 수 있어 `exact_endcriteria=True`로 격자 시간 간격에 따른 평가를 요청한다. 자식 종료 뒤 로그에서 exact 평가 활성화, -70 dB 목표를 충족한 성공 메시지와 실제 감쇠값, 통계와 같은 반복 수를 확인한다. SIGINT/ABORT 중단 메시지 또는 목표 미충족 경고가 있으면 통계 파일과 수치가 있어도 실패다. 근거는 고정 [RunFDTD 종료 조건 구현](https://github.com/thliebig/openEMS/blob/305df56aa7df4d2f18c687083f484a96f9a22610/openems.cpp#L1458)이다. 로그의 감쇠 수치는 반올림된 출력이며 정식 수렴 증명으로 사용하지 않는다.

## 실행과 산출물

Linux 전용 solver 가상환경의 Python으로 실행한다. 아래 경로는 해당 환경의 실제 경로로 지정한다.

```sh
python tools/check_openems_environment.py --output /absolute/run-directory/openems-reference.json --timeout-seconds 300
```

각 격자는 별도 자식 프로세스에서 실행한다. 기본 제한은 import를 포함하여 격자당 300초다. 시간 초과 시 소유한 자식 프로세스 그룹을 종료하고 실패 보고서를 기록한다. 정상은 종료 코드 0, 검증 또는 실행 실패는 2다.

최종 JSON 옆의 고유 `openems-run-*` 디렉터리에 실제 solver 로그, 모델 XML, probe 원시 파일, 격자별 복소 표본과 보고서를 보존한다. 기존 실행 디렉터리를 지우거나 재사용하지 않는다. 산출물과 로그 SHA256, Python 실행 파일 및 실제 로딩한 openEMS/CSXCAD/fparser/nf2ff native 파일의 SHA256을 기록한다. 설치된 Qt binding, 실제 로딩된 Qt 라이브러리와 모듈도 검사한다. 전체 설치 의존성 검토는 별도 runtime profile의 책임이다.

자식 실행/입력/파일 접근 오류, 비유한 결과, 작은 입사 스펙트럼, 0 전류, 잘못된 주파수 순서, 기준 초과를 성공으로 처리하지 않는다. 보고서의 `ifa_tested`, `nf2ff_tested`, `product_adapter_tested`, `formal_convergence_tested`는 false다.

## 근거와 한계

API 사용은 공식 [Rectangular Waveguide 예제](https://docs.openems.de/en/latest/python/openEMS/Tutorials/Rect_Waveguide.html)와 [모드 포트 계약](https://docs.openems.de/en/latest/python/openEMS/ports.html)을 확인했다. 모델은 별도 치수, 격자, 판정 및 실행 관리로 작성했다. GUI/plot과 원본 tutorial 전체를 복사하지 않는다.

확인한 고정 solver 소스는 [openEMS v0.37.0](https://github.com/thliebig/openEMS/tree/305df56aa7df4d2f18c687083f484a96f9a22610)이다. 실제 설치 commit과 native 의존성은 runtime profile 및 실행 보고서로 대조한다. 임피던스/군지연 식의 c0는 299792458 m/s, 진공 임피던스는 376.730313668 ohm을 사용한다. 유전 재료나 도체 손실 모델의 검증으로 확대하지 않는다.

`tests/test_openems_checker.py`의 이상적 표본은 판정기 자체의 오류 검출을 시험하기 위한 인공 입력이다. 이 단위 시험 통과를 FDTD 실행 증거로 사용하지 않는다. 실제 실행 여부와 수치는 완료한 native 보고서가 있어야 기록한다.

## 실제 실행 기록

2026-11-10 18:10 KST에 전용 WSL2 Ubuntu 24.04의 solver 가상환경에서 처음 실행했고 종료 코드 0으로 통과했다. 해석 시작 전 정한 임계값을 변경하지 않았다. 추가 LD_LIBRARY_PATH 없이 설치된 native 경로로 실행했다. 전체 명령의 벽시계 시간은 약 7.75초였고 아래 시간은 각 자식에서 import 이후 모델 계산과 후처리에 관찰된 값이다. 제품 성능 예산 합격값은 아니다.

| 항목 | 목표 cell 1 mm | 목표 cell 0.75 mm |
| --- | --- | --- |
| 실제 격자 간격 개수 x/y/z | 20/10/80 | 27/14/109 |
| native가 보고한 FDTD cell 수 | 18,711 | 46,200 |
| 실제 반복 수 | 4,305 | 6,003 |
| 시간 간격 | 1.925833194728316e-12 s | 1.391966567353170e-12 s |
| 계산 및 후처리 관찰 시간 | 1.712 s | 2.746 s |
| 최대 반사 진폭 | 0.003071662 | 0.002570359 |
| 최대 전달 진폭 오차 | 0.000019406 | 0.000019911 |
| 최대 임피던스 상대 오차 | 0.6162% | 0.5152% |
| 최대 군지연 상대 오차 | 0.1071% | 0.0651% |
| 정상 종료 로그의 에너지 감쇠 | -71.2401 dB | -71.2774 dB |

두 격자의 최대 전달 진폭 차이는 0.000017404, 임피던스 상대 차이는 0.3113%였다. 두 실행 모두 31개 주파수의 유한 복소 결과, 정상 종료 메시지와 통계의 반복 수 일치, -70 dB 종료 목표 충족을 확인했다. native FDTD cell 수는 solver 자체의 경계 포함 배열 크기 기준이므로 격자 간격 개수의 곱과 다르다.

실제로 로딩한 solver 관련 native 파일 7개의 SHA256이 설치 감사 보고서와 모두 일치했다. 두 실행에서 Qt 패키지, 로딩된 Qt 라이브러리와 Python Qt 모듈은 모두 없었다. native 로그도 openEMS commit `305df56`, CSXCAD commit `c46e320`, VTK 9.3.1을 보고했다. 판정기 단위 시험은 Windows와 Linux에서 각각 7개 통과했다.

최종 보고서 사본은 `Code/.local/wsl/openems-reference.json`, 원본과 실제 solver 산출물은 Linux의 `/home/tracewave/rfad-runtime/verification/` 아래에 있다. 설치 감사 근거는 `Code/.local/wsl/native-audit.json`이다. 상세 로그/원시 probe/XML/실행 파일의 해시는 보고서에 기록했고 Git에는 로컬 실행 산출물을 추가하지 않는다.

이 결과는 2026-11-10의 작은 진공 PEC 도파관 개발 환경 참조 검사다. 이후 2026-11-11에 [제품 서비스의 도파관 worker](solver_contract.md)를 연결해 분리 준비, 봉인 XML 실행, raw 후처리, 취소/저장/재시작 검증을 추가했다. 최신 제품 경로의 수치와 보고서는 [개발 상태](development_status.md)를 따른다. 손실 재료/구리 적층, 단일 포트 IFA, NF2FF 방사 패턴, 정식 메시/경계/시간 수렴 검증과 측정 대조는 후속이다.
