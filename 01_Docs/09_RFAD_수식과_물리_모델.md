# RFAD 09 - 수식과 물리 모델

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전
역할: 계산 규약, 수식의 정의역, 출력, 한계, 구현 위임과 검증 벡터의 기준
상태: **design baseline with open verification gates** - 구현, EM 실행, 실측 합격을 뜻하지 않는다.

관련 문서: [계산 파이프라인](10_RFAD_연산_파이프라인.md) ,  [solver 계약](11_RFAD_해석기_어댑터_계약.md) ,  [수용시험](14_RFAD_검증과_수용_기준.md) ,  [형상별 합성](22_RFAD_안테나_형상별_합성.md) ,  기계 판독 레지스트리는 개발 승인 후 생성할 산출물

## 1. 계산이 보장하는 범위

이 프로그램은 **정확한 기하 생성**, **조건이 있는 초기 치수 추정**, **외부 solver의 Maxwell 해**, **검증된 결과의 후처리**, **측정과의 비교**를 별도 계산으로 취급한다. 원호 길이 계산이 정확해도 그 길이에서 실제 공진하거나 방사효율이 좋다는 결론은 나오지 않는다. 반대로 수치 solver가 종료되었어도 메시, 경계, 전력, 물성 검사가 끝나지 않으면 검증된 설계가 아니다.

| 물리 영역 | 필수 계산 객체 | 대표 출력 | 대신 사용할 수 없는 단순화 |
|---|---|---|---|
| BLE, Wi-Fi, Sub-GHz, LoRa 등 방사형 | 유한 보드/GND, 급전, 환경, 유전/도체 손실 | S/Z, 방사효율, 패턴, gain | 프로토콜 이름만으로 안테나 치수 확정 |
| UWB | 광대역 재료, 위상, 안테나쌍, 시간 기준 | Hpair, group delay, 펄스, fidelity | 단일 S11의 phase로 거리 지연 계산 |
| NFC, LF/HF | coil, ferrite, shield, reader/tag 부하 | R/L/Q/M/k, loaded transfer, 동작 공간 | far-field gain 또는 Friis만으로 결합 평가 |
| UHF RFID | antenna+assembled chip의 복소 Z와 동작 power | 공액 전력전달, 방사/편파, 전력 의존성 | 항상 50 ohm 정합으로 대체 |
| MIMO, 배열, AoA | 전체 S와 coherent embedded fields, 종단, 여기, 좌표 | TARC, pattern ECC, beam/manifold | 개별 S11 또는 magnitude-only pattern 합성 |
| Flex, 실장환경 | 평면 제조 형상과 변형 후 3D, 실제 층별 위치 | scenario별 EM/STEP | 평면 원호를 물리적으로 굽힌 기판으로 간주 |

이 분리는 [A의 PHY-002, 008, 089, 090](03_RFAD_사용자_요구사항.md), NFC의 [NXP AN12549](https://www.nxp.com/docs/en/application-note/AN12549.pdf), RFID의 [NXP AN171530](https://www.nxp.com/docs/en/application-note/AN171530.pdf), UWB의 [Liang 학위논문](http://ael.chungbuk.ac.kr/lectures/undergraduate/%EC%A2%85%ED%95%A9%EC%84%A4%EA%B3%84-1/2018-2/%EC%9D%B4%EC%88%98%ED%98%B8/liang(06-thesis).pdf), 네트워크 파 정의의 [NIST Marks-Williams](https://www.nist.gov/publications/general-waveguide-circuit-theory)를 기준으로 한다. 프로토콜의 실제 채널, 법규 업데이트는 프로젝트 프로파일이며 물리식 상수가 아니다.

## 2. 모든 계산이 공유하는 규약

### 2.1 SI, 복소수, 시간, 주파수

Canonical 값은 m, Hz, s, S/m, F/m, H/m, ohm, W이며 각도는 rad이다. mm, um, GHz, deg는 입출력 표현이다. 복소수는 schema가 정한 실수부/허수부로 저장하며 NaN/Inf는 숫자 대신 명시적 `undefined`/`infinite` 상태와 원인을 갖는다. 수식의 상첨자 별표(^*)와 ASCII conj(z)는 complex conjugate, ^H는 conjugate transpose이다. ASCII 식의 두 항 사이 *는 곱셈이다.

$$
 x(t)=\sqrt{2}\,\operatorname{Re}\{X_{\mathrm{rms}}e^{+j\omega t}\},\qquad
 X(f)=\int_{-\infty}^{\infty}x(t)e^{-j2\pi ft}\,dt.
$$

V/I/E/H의 canonical phasor는 **RMS**이다. 따라서 평균 유효전력은 $\operatorname{Re}(VI^*)$, 평균 Poynting 벡터는 $\operatorname{Re}(\mathbf E\times\mathbf H^*)$이며 추가 1/2가 없다. 같은 exp(+j*omega*t) convention에서 수동 등방성 유전율은 $\epsilon=\epsilon'-j\epsilon''$이고 $\epsilon''\ge0$이다. tensor는 원소별 부호 대신 손실 연산자의 PSD를 검사한다. 출처 [BOOK_MIT_STAELIN](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf)의 물리 PDF 59-60쪽은 peak convention이므로 1/2 계수를 그대로 복사하지 않는다.

c0=299792458 m/s는 SI 정의값이다. mu0를 현대 SI에서 정확히 4*pi*10^(-7)로 취급하지 않는다. production은 고정한 CODATA 버전의 constants를 기록한다. 일부 참고 벡터의 mu0=4*pi*10^(-7), epsilon0=1/(mu0*c0^2)는 **서로 일관된 이상화 입력 fixture**이며 최신 정밀 상수 주장과 구별한다.

### 2.2 native 채널을 변환하는 규칙

각 raw 채널은 `quantity`, 단위, `amplitude_convention`, phasor 부호, FFT scaling, 시간/위상 원점, 주파수 grid, 기준면, field의 r 정규화 및 solver/adapter 버전을 갖는다. 확인 전에는 `solver_native`로 보존한다. unknown convention 때문에 절대 power/gain을 계산할 수 없으면 그 metric을 차단한다.

- **확인된 peak phasor V/I/E/H만** RMS로 바꿀 때 1/sqrt(2)를 곱한다.
- instantaneous time sample, S-parameter, 이미 power-normalized인 wave 값에 일괄 sqrt(2) 변환을 하지 않는다.
- FFT 배열은 계산식의 적분 계수, sample 간격, native scaling이 확인된 뒤 변환한다. field FFT와 port power의 계수를 두 번 적용하지 않는다.
- rE, E(r), 단순 normalized pattern은 서로 다른 quantity이다. 한 종류로 선언되지 않은 채널에서 절대 Prad를 계산하지 않는다.
- [scikit-rf Circuit의 V/I 예제](https://scikit-rf.readthedocs.io/en/latest/examples/circuit/Voltages%20and%20Currents%20in%20Circuits.html)는 peak 값을 설명한다. 고정 버전에서 확인한 뒤 채널별로 변환하며 external/internal current 방향을 검사한다.

[GAP-003](01_RFAD_설계_결정과_범위.md#GAP-003), [VT-021](14_RFAD_검증과_수용_기준.md#VT-021)이 이 변환의 출시 gate이다. openEMS 출력 전체가 peak라는 가정은 채택하지 않는다.

### 2.3 공진, 대역, 정규화 정의

`resonance`는 최소 |S11|, Im(Z)=0, 특정 eigenmode 등 선택한 정의를 기록한다. 서로 다른 정의의 주파수를 자동으로 같은 공진으로 비교하지 않는다. 다중 공진은 branch identity와 추적 방법을 가진다. 대역 mask는 실제 계산점, 저장 transient에서 재평가한 점, 보간점, 대리모델 점을 구별한다. sparse points의 통과만으로 연속대역을 통과시키지 않는다.

`S`에는 `s_def`, 포트별, 주파수별 Z0, 포트 순서, 모드, 기준면과 current orientation이 필수이다. 실수 Z0에서 겹치는 파 정의가 복소 Z0에서도 같다고 가정하지 않는다. 수동성, 전력, renormalization은 이 metadata가 확인된 뒤 계산한다. 근거: [scikit-rf complex characteristic impedance 문서](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html).

## 3. 구현과 위임의 경계

| 담당 | 직접 구현할 논리 | 위임할 핵심 수치/물리 작업 |
|---|---|---|
| Domain | 단위, parameter graph, analytic arc, 가정, 상태, 제약, 의존성 | 복잡한 Boolean/offset/B-rep는 OCCT/CadQuery |
| 초기 합성 | EQ-004/005/041 범위 검사와 seed 산출 | 실제 antenna 공진, 효율, 패턴은 full-wave |
| EM adapter | capability 검증, geometry/material/port 매핑, 불변 manifest | mesh/native time-step, Maxwell solve, native NF2FF는 openEMS 등 |
| Network | plane/파 정의/연결 계약, 조건수, 오류, provenance | scikit-rf의 S/Z/Y 변환, renormalize, network interconnect, 검증된 linear algebra |
| Material | 조건별 선택, 단위, fit 범위, 잔차, passivity 검토 | 검증된 optimizer/수동 rational fit 및 backend model 매핑 |
| Metrics | RMS power ledger, 명시된 효율/편파/ECC/UWB 정의 | 검증된 NumPy/SciPy FFT, quadrature, 선형대수, raw EM field |
| 검증 | 기준/독립 oracle, fixture, 판정, 불확실성 | 실제 solver 실행과 독립 측정 장비, 교정 |

어떤 라이브러리를 썼다는 사실만으로 gate를 통과하지 않는다. scikit-rf의 `s_def_old`, complex Z0 연결, conditioning 및 Circuit V/I 규약을 pinned version으로 시험한다. openEMS의 [분산 모델](https://docs.openems.de/en/latest/concepts/dispersive.html)은 Python/Octave 노출 API가 같지 않으며, 일부 fitting helpers를 Python에 존재한다고 가정하지 않는다. 개발자가 별도 Maxwell solver, NF2FF, 일반 B-rep kernel을 새로 작성하는 범위는 아니다.

## 4. 수식 레지스트리 읽기

각 산술 참고 벡터는 입력과 기대값을 정의한 검증 설계다. 벡터와 본문 오류 조건의 전체 실행은 개발 승인 후 수행하며, 나열된 기대값 자체를 실행 증거로 보지 않는다. 이번 개정의 제한된 문서 산술 검산 6건은 [25번 검토 기록](25_RFAD_문서_검토와_승인.md)에 별도로 구분한다.

아래 EQ-001~041은 계산 계약의 현재 기준이다. 입력/출력 단위, 정의역, 실패 조건, 근사 등급, 출처, 단계 및 참고값을 이 본문에서 확인한다. 과거 `equation_registry.json`은 현재 저장소에 없는 산출물이므로 구현 의존성이나 완료 근거로 삼지 않는다. 개발 승인 후 기계 판독 registry를 만들 때 기존 EQ와 reference vector ID를 보존하고 본문과 대조해야 한다. 산술 허용오차는 계산 검사용 값이며 antenna 성능 정확도가 아니다. 원문 페이지는 별도 표기가 없으면 물리 PDF의 1-based 페이지다.

<a id="EQ-001"></a>

### EQ-001 - 원호 좌표, 길이, 방향

$$
\mathbf p(\alpha)=(c_x+r\cos\alpha,\ c_y+r\sin\alpha),\quad L_{\rm arc}=r|\theta|,\quad \theta_{\rm rad}=\theta_{\rm deg}\pi/180
$$

**적용:** 정확한 평면 원호의 기하학이다. 중심선 반경 r>0, 시작각과 부호 있는 sweep를 입력한다.

**한계, 예외:** 두 끝점만으로 긴 호/짧은 호 및 방향을 추정하지 않는다. theta=0과 theta=2*pi를 구별하며 겹침과 닫힘은 전기 topology에서 검사한다.

**입력:** `cx,cy,r` [m] - 원호 중심과 중심선 반경; `alpha0,theta` [rad] - 시작각과 signed sweep.

**출력:** `p` [m] - 중심선 좌표; `L` [m] - 원호만의 중심선 길이.

**근사 등급, 단계:** `exact_geometry_derived` ,  R0. **구현/위임:** domain analytic geometry; exact CAD arc representation.

**근거:** [NORDIC_PCA20006_CAD](https://devzone.nordicsemi.com/cfs-file/__key/support-attachments/beef5d1b77644c448dabff31668f3a47-1f949ef4dfa645c8b62851b8ead3970f/nRF51822-Bluetooth-Smart-Beacon-kit-hardware-files.zip) - G031 archive GTL lines 705-708; GM1 lines129-131; member hashes in G031.

**후속 계산:** [EQ-002](#EQ-002), [EQ-004](#EQ-004), [EQ-039](#EQ-039).

**산술 참고 벡터:** `{"r_m":0.01,"theta_rad":1.5707963267948966,"cx_m":0.0,"cy_m":0.0,"alpha0_rad":0.0}` -> `{"L_m":0.015707963267948967,"end_m":[0,0.01]}`.

<a id="EQ-002"></a>

### EQ-002 - 선폭 offset, 곡선 tessellation 오차

$$
r_{\rm in}=r-w/2,\quad r_{\rm out}=r+w/2,\quad e=r_b[1-\cos(\Delta\theta/2)],\quad N\ge\left\lceil\frac{|\theta|}{2\arccos(1-e/r_b)}\right\rceil
$$

**적용:** 단순 annular segment는 0<w<2r에서 적용한다. chord 허용값은 0<e<r_bound이며 실제 외곽의 최대 반경을 사용한다.

**한계, 예외:** end cap, join, taper와 Boolean union은 별도 CAD 연산이다. self-intersection, gap 소실은 허용하지 않는다.

**입력:** `r,w` [m] - 중심선 반경과 선폭; `theta` [rad] - sweep; `e` [m] - 허용 chord deviation.

float64 구현은 `delta_theta=4*asin(sqrt(e/(2*r_bound)))`의 안정적인 동치식을 권장한다. 외곽 반경에 bound를 적용하고 segment budget 초과 시 E_RESOURCE를 반환한다. 요구 tolerance를 몰래 크게 바꾸지 않는다. (PHYS-006)

theta=0은 길이 0의 편집 초안이고 유효 방사 도체가 아니다. 닫힌 원과 열린 원호는 별도 topology로 저장한다. 열린 원호의 기본 domain은 `0 < abs(theta) < 2*pi`이며 여러 회전의 중첩은 별도 지원 모델 없이 허용하지 않는다. 분할 개수가 0인 경우 각도 간격 계산을 수행하지 않는다. 실제 cap/join과 최대 반경을 포함한 경계 오차를 검증한다.

**출력:** `rin,rout` [m] - 원호 구간 경계 반경; `N` [1] - 분할 수 하한.

**근사 등급, 단계:** `exact_geometry_plus_export_policy` ,  R0. **구현/위임:** CadQuery/OCCT offset/boolean; analytical chord bound.

**근거:** [NORDIC_PCA20006_CAD](https://devzone.nordicsemi.com/cfs-file/__key/support-attachments/beef5d1b77644c448dabff31668f3a47-1f949ef4dfa645c8b62851b8ead3970f/nRF51822-Bluetooth-Smart-Beacon-kit-hardware-files.zip) - G031 archive GTL lines 705-708; GM1 lines129-131; member hashes in G031.

**후속 계산:** [EQ-039](#EQ-039).

**산술 참고 벡터:** `{"r_m":0.01,"w_m":0.001}` -> `{"rin_m":0.0095,"rout_m":0.0105}`.

<a id="EQ-003"></a>

### EQ-003 - 파장과 전기적 크기

$$
\omega=2\pi f,\quad \lambda_0=c_0/f,\quad k_0=\omega/c_0,\quad D_e=D/\lambda_0,\quad \lambda_m\approx\lambda_0/\sqrt{\epsilon_r\mu_r}
$$

**적용:** 자유공간 파장은 f>0에서 정확한 SI c0로 계산한다. lambdamedium 근사는 균질, 등방성, 무손실이고 실수 양의 epsilon_r,mur인 평면파에 한정한다.

**한계, 예외:** 분산, 손실, 이방성 매질은 실제 propagation constant 또는 solver mode를 사용한다. f=0의 파장은 유한값으로 반환하지 않는다.

**입력:** `f` [Hz] - 주파수; `D` [m] - 관심 구조의 크기; `epsilon_r,mur` [1] - 실수 양의 균질 매질값; 근사에만 사용.

**출력:** `lambda0,lambdamedium` [m] - 파장; `k0` [rad/m] - 자유공간 파수; `size_ratio` [1] - 전기적 크기.

**근사 등급, 단계:** `exact_free_space_and_scoped_medium_approximation` ,  R0. **구현/위임:** domain constants with pinned CODATA provenance.

**근거:** [RS_8GE01_ANTENNA_BASICS](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/premiumdownloads/premium_dl_brochures_and_datasheets/premium_dl_whitepaper/Antenna_Basics_8GE01_1e.pdf) 물리 p.7,13,14 - Far-field, directivity/gain, effective area.

**후속 계산:** [EQ-004](#EQ-004), [EQ-005](#EQ-005), [EQ-019](#EQ-019), [EQ-038](#EQ-038), [EQ-040](#EQ-040).

**산술 참고 벡터:** `{"f_Hz":2400000000.0}` -> `{"lambda0_m":0.12491352416666666}`.

<a id="EQ-004"></a>

### EQ-004 - 모노폴, IFA 초기 길이 제안

$$
L_{\rm seed,mono}=\kappa_{\rm seed}\lambda_0/4,\qquad L_{\rm seed,dipole/slot}\approx\lambda_0/2
$$

**적용:** lambda0/4와 lambda0/2는 각각 이상적 monopole 및 thin dipole/좁은 slot의 탐색 초기값이다. 보정 kappa는 출처와 geometry/material/ground 범위가 있는 경우에만 사용한다.

**한계, 예외:** 원호, IFA, 미앤더의 전체 공진이나 정합은 이 식의 출력이 아니다. finite ground, 급전, balun, short, dielectric와 환경의 영향은 실제 geometry 해석으로 계산한다.

**입력:** `f` [Hz] - 목표 주파수; `kappaseed` [1] - 출처, 조건을 갖는 초기 배율; `template` [structured] - feed/short/ground/topology constraints.

**출력:** `Lseed` [m] - 탐색 시작 치수; `evidence_state` [enum] - estimated_seed.

**근사 등급, 단계:** `initial_estimate_not_resonance_solution` ,  R1. **구현/위임:** template.synthesize then fullwave solver.

**근거:** [NORDIC_NWP008](https://nrfconnectdocs.nordicsemi.com/pdf/nwp_008/nwp_008.pdf) 물리 p.1,2,3 - section 2-4 and tuning; geometry is initial reference only; [SILABS_AN1088](https://www.silabs.com/documents/public/application-notes/an1088-designing-with-pcb-antenna.pdf) 물리 p.3,5,6 - IFA topology, placement and tuning; [TI_AN058_SWRA161](https://www.ti.com/lit/pdf/swra161) 물리 p.4,5,6,20,23,24,25,26 - section 3.1-3.4 initial lengths and wave conventions; calibration/matching/OTA; [ANSYS_SLOT_SEED](https://innovationspace.ansys.com/courses/wp-content/uploads/sites/5/2022/07/antenna_types_slot.pdf) 물리 p.3,6 - Slot Antennas: half-wavelength planar slot; finite ground caveat.

**후속 계산:** [EQ-001](#EQ-001), [EQ-005](#EQ-005), [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"f_Hz":2400000000.0,"kappa_seed":1}` -> `{"ideal_quarter_lambda_m":0.031228381041666666,"status":"estimated_seed"}`.

<a id="EQ-005"></a>

### EQ-005 - 균일 microstrip epsilon_eff와 Z0

$$
\begin{aligned}u&=w/h,&F&=6+(2\pi-6)e^{-(30.666/u)^{0.7528}},\\ Z_{01}&=\frac{\eta_0}{2\pi}\ln\left[F/u+\sqrt{1+(2/u)^2}\right],\\a&=1+\frac1{49}\ln\frac{u^4+(u/52)^2}{u^4+0.432}+\frac1{18.7}\ln[1+(u/18.1)^3],\\b&=0.564\left(\frac{\epsilon_r-0.9}{\epsilon_r+3}\right)^{0.053},\\\epsilon_{\rm eff}&=\frac{\epsilon_r+1}{2}+\frac{\epsilon_r-1}{2}(1+10/u)^{-ab},\qquad Z_0=Z_{01}/\sqrt{\epsilon_{\rm eff}}.\end{aligned}
$$

**적용:** 공기 위쪽, 균일 단층 기판, 연속 ground, zero-thickness strip의 quasi-static 모델이다. 채택 계산영역은 1<=epsilon_r<=128, 0.01<=w/h<=100이다.

**한계, 예외:** CPW, stripline, slot, finite ground, 두꺼운 금속, 전체 antenna 모델로 확장하지 않는다. 동박 두께, 분산, 거칠기 보정은 별도 검증된 모델이 필요하다.

**입력:** `w,h` [m] - 균일 strip 폭과 ground까지 substrate height; `epsilon_r` [1] - 균질 isotropic dielectric; `eta0` [ohm] - 일관된 vacuum constants에서 산출.

**출력:** `epsilon_eff` [1] - quasi-static 유효값; `Z0` [ohm] - 손실 없는 초기 임피던스.

**근사 등급, 단계:** `empirical_quasi_static_model` ,  R1. **구현/위임:** scikit-rf transmission-line model only after version/model parity spike; formula oracle retained.

**근거:** [PAPER-071](https://doi.org/10.1109/MWSYM.1980.1124303) 물리 p.1 - Single microstrip, equations (1)-(5); printed p407.

**후속 계산:** [EQ-004](#EQ-004), [EQ-012](#EQ-012), [EQ-028](#EQ-028).

**산술 참고 벡터:** `{"w_m":0.001,"h_m":0.001,"epsilon_r":4.4,"eta0_ohm":376.73031346177066}` -> `{"epsilon_eff":3.1678227977495026,"Z0_ohm":71.03111366420649}`.

<a id="EQ-006"></a>

### EQ-006 - 양도체 표피 깊이

$$
\delta=\sqrt{\frac{2}{\omega\mu\sigma}}
$$

**적용:** sigma >> omega*epsilon인 양도체, f>0 및 실수 양의 mu,sigma를 전제로 한 표피 깊이 근사이다.

**한계, 예외:** 자성체의 복소 mu, 박막의 크기 효과, superconductivity, proximity, edge 효과를 자동 포함하지 않는다. 조건을 벗어나면 solver/material 모델로 넘긴다.

**입력:** `f` [Hz] - 주파수; `mu` [H/m] - 실수 양의 투자율; `sigma` [S/m] - 양도체 전도도.

**출력:** `delta` [m] - 1/e field penetration depth.

**근사 등급, 단계:** `good_conductor_approximation` ,  R1. **구현/위임:** domain diagnostic; solver conductor model selected separately.

**근거:** [BOOK_MIT_STAELIN](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf) 물리 p.56,59,60,82 - section 2.6-2.7; equations 2.7.15-2.7.24; mutual-inductance matrix 3.2.35-3.2.37.

**후속 계산:** [EQ-007](#EQ-007).

**산술 참고 벡터:** `{"f_Hz":1000000000.0,"mu_H_per_m":1.2566370614359173e-06,"sigma_S_per_m":58000000.0}` -> `{"delta_m":2.089806784938892e-06}`.

<a id="EQ-007"></a>

### EQ-007 - 표면 임피던스, 동박 손실

$$
Z_s\approx\frac{1+j}{\sigma\delta},\quad P_{\rm cond}=\int R_s|H_{t,\rm rms}|^2dA,\quad R_{\rm sheet,uniform}\approx\frac1{\sigma t}
$$

**적용:** Zs 식은 국소적으로 평탄하고 충분히 두꺼운 양도체에, Rsheet=1/(sigma*t)는 t<<delta이고 전류가 거의 균일한 별도 한계에 적용한다.

**한계, 예외:** 유한 두께의 양면 결합, edge, proximity, roughness를 동시에 해결하는 식이 아니다. PEC에는 도체 손실이 없다. thickness=0의 backend fallback을 실제 0 두께 구리로 해석하지 않는다.

**입력:** `delta,t` [m] - skin depth와 실제 동박 두께; `sigma` [S/m] - 전도도; `Ht` [A/m RMS] - 접선 자기장; `E,J` [V/m RMS; A/m^2 RMS] - 체적 field/current.

**출력:** `Zs,Rsheet` [ohm] - surface impedance/ohms per square; `Pcond` [W] - 도체 손실.

**근사 등급, 단계:** `asymptotic_conductor_model` ,  R1. **구현/위임:** openEMS conductor/sheet adapter; no homegrown general thin-sheet solver.

**근거:** [BOOK_MIT_STAELIN](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf) 물리 p.56,59,60,82 - section 2.6-2.7; equations 2.7.15-2.7.24; mutual-inductance matrix 3.2.35-3.2.37; [B-S02](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/materials.html) - AddConductingSheet: 2D primitives, conductivity/thickness; [ROGERS_COPPER_FOIL](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/properties---detailed-characteristics/copper-foils-for-high-frequency-circuit-materials.pdf) 물리 p.4 - Table 1 surface roughness Sq; copper types.

**후속 계산:** [EQ-015](#EQ-015), [EQ-017](#EQ-017).

**산술 참고 벡터:** `{"sigma_S_per_m":58000000.0,"delta_m":2.089806784938892e-06}` -> `{"Zs_ohm_re_im":[0.008250226496823715,0.008250226496823715]}`.

<a id="EQ-008"></a>

### EQ-008 - 복소 epsilon/mu, sigma와 손실밀도

$$
\epsilon_{r,\rm eff}=\epsilon_r^\prime-j\left(\epsilon_{r,\rm bound}^{\prime\prime}+\frac{\sigma}{\omega\epsilon_0}\right),\quad\kappa_{\rm ref}=\omega_{\rm ref}\epsilon_0\epsilon_r^\prime\tan\delta_{\rm ref},\quad q=\mathbf E^\dagger[\omega L_\epsilon+\operatorname{Herm}\sigma]\mathbf E+\omega\mathbf H^\dagger L_\mu\mathbf H
$$

**적용:** exp(+j*omega*t), RMS 규약이다. epsilon와 mu의 tensor는 손실 연산자가 Hermitian PSD인지 검사한다. conductivity가 epsilon_eff에 이미 흡수되었으면 별도 손실로 다시 더하지 않는다.

**한계, 예외:** 복소 부호 규약을 모르는 native 값을 능동/수동으로 판정하지 않는다. f=0에서 conductivity pole은 별도 처리한다. tensor의 원소별 부호만으로 수동성을 판정하지 않는다.

**입력:** `epsilon,mu` [F/m; H/m] - absolute complex tensors, bound loss와sigma중복 제외; `sigma` [S/m] - 전도도 tensor; `E,H` [V/m; A/m RMS] - field; `f,fref` [Hz] - 해석/환산 기준.

**출력:** `epsilon_r,eff` [1 complex] - 유효 상대유전율; `qloss` [W/m^3] - 시간평균 소모 밀도; `kapparef` [S/m] - 단일주파수 상수전도 근사.

**근사 등급, 단계:** `constitutive_definition_and_scoped_loss_mapping` ,  R1. **구현/위임:** material adapter + constrained linear algebra.

**근거:** [BOOK_MIT_STAELIN](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf) 물리 p.56,59,60,82 - section 2.6-2.7; equations 2.7.15-2.7.24; mutual-inductance matrix 3.2.35-3.2.37; [B-S01](https://docs.openems.de/en/latest/concepts/dispersive.html) - Debye/Drude/Lorentz; Python availability and model mapping; [OPENEMS_PATCH](https://docs.openems.de/en/latest/python/openEMS/Tutorials/Simple_Patch_Antenna.html) - substate_kappa; port.CalcPort; NF2FF tutorial; [ROGERS_ISOTROPY](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/properties---detailed-characteristics/the-advantage-of-nearly-isotropic-dielectric-constant-of-rt-duroid-5870-5880-glass-microfiber-ptfe.pdf) 물리 p.1,2 - Table1 and test-specimen preparation.

**후속 계산:** [EQ-009](#EQ-009), [EQ-015](#EQ-015), [EQ-017](#EQ-017).

**산술 참고 벡터:** `{"fref_Hz":1000000000.0,"epsilon_r_real":4,"tan_delta_ref":0.02,"eps0_F_per_m":8.854187817620389e-12}` -> `{"kappa_S_per_m":0.004450600224214473}`.

손실 연산자는 $L_\epsilon=-(\epsilon-\epsilon^\dagger)/(2j)$이며 여기의 epsilon,mu는 절대 단위 tensor이다. sigma를 별도 항으로 넣는 경우 epsilon에는 그 conduction loss가 중복 포함되지 않아야 한다.

native 속성 이름과 도메인 기호가 같다는 이유로 매핑하지 않는다. CSXCAD 문서의 `Kappa`는 전기 전도도 S/m, `Sigma`는 자기 손실용 전도도 ohm/m이다. 도메인의 전기 `sigma`를 native `Sigma`로 전달하면 차원과 물리가 달라진다. adapter는 명시적인 필드 매핑과 단위 검사를 사용한다. [CSXCAD 물성 정의](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/materials.html).

<a id="EQ-009"></a>

### EQ-009 - 수동 분산 모델과 데이터 fit

$$
\epsilon_r(s)=\epsilon_\infty+\sum_k\frac{\Delta\epsilon_k}{1+s\tau_k}+\frac{\sigma_{dc}}{\epsilon_0s}+\sum_k\frac{A_k}{s^2+\gamma_ks+\omega_{0k}^2},\quad s=j\omega
$$

**적용:** 단순 등방성 fixture에서는 epsiloninfinity>0, Deltaepsilon>=0, tau>0, A>=0, gamma>=0, omega0>0, sigmadc>=0를 충분조건으로 사용한다. 입력 물성의 주파수, 시험조건을 보존하고 fit 오차를 기록한다.

**한계, 예외:** 안정한 pole만으로 모든 주파수의 수동성을 보증하지 않는다. 몇 개의 Dk/Df 표 값으로 유일한 광대역 모델을 만들었다고 주장하지 않는다. tensor와 native model 매핑은 별도 gate이다.

**입력:** `fi` [Hz] - 측정주파수; `epsilondata` [1 complex] - 동일조건 데이터; `Deltaepsilon,tau,gamma,omega0,A` [1;s;1/s;rad/s;1/s^2] - Debye/Lorentz parameters; `wi` [declared] - 단위, uncertainty를 고려한 가중.

**출력:** `model` [structured] - parameters,range,residual,covariance; `epsilonmodel` [1 complex] - 적합 응답.

**근사 등급, 단계:** `constrained_phenomenological_fit` ,  R2. **구현/위임:** scipy constrained fit; native openEMS Debye/Lorentz mapping verified by fixture.

**근거:** [B-S01](https://docs.openems.de/en/latest/concepts/dispersive.html) - Debye/Drude/Lorentz; Python availability and model mapping; [ROGERS_RO4000_DS](https://rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf) 물리 p.3 - Process/design dielectric data.

**후속 계산:** [EQ-008](#EQ-008), [EQ-021](#EQ-021), [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"epsilon_inf":2,"delta_epsilon":2,"omega_tau":1,"sigma":0}` -> `{"epsilon_r_re_im":[3,-1]}`.

무감쇠 Lorentz 항에서 gamma=0, omega=omega0, A>0이면 finite evaluator의 분모가 0이다. pole 및 근접 조건수를 진단하고 singular 상태를 반환한다. 임의 작은 damping을 넣어 유한값으로 바꾸지 않는다. A=0 항과 DC conductivity pole도 별도 검사한다. (PHYS-004)

<a id="EQ-010"></a>

### EQ-010 - 실수 기준 임피던스 Gamma, RL, VSWR

$$
\Gamma_V=\frac{Z-R_0}{Z+R_0},\quad S_{11,\rm dB}=20\log_{10}|\Gamma|,\quad RL=-20\log_{10}|\Gamma|,\quad VSWR=\frac{1+|\Gamma|}{1-|\Gamma|}
$$

**적용:** R0>0의 실수 기준 임피던스, 전압 반사계수의 단일 propagating mode를 전제로 한다.

**한계, 예외:** Gamma=0이면 RL=+infinity, |Gamma|=1이면 VSWR=infinity이다. |Gamma|>1 또는 Z+R0=0을 clipping하지 않는다. 복소 Z0에는 EQ-011의 파 정의가 필요하다.

**입력:** `Z` [ohm complex] - same-plane input impedance; `R0` [ohm] - real positive reference.

**출력:** `Gamma` [1 complex] - reflection; `S11dB,RL` [dB] - opposite-signed log labels; `VSWR` [1] - voltage standing-wave ratio.

**근사 등급, 단계:** `established_network_definition` ,  R1. **구현/위임:** scikit-rf plus domain label handling.

**근거:** [SILABS_AN1275](https://www.silabs.com/documents/public/application-notes/an1275-imp-match-for-network-arch.pdf) 물리 p.4,5,12,14,15 - Reflection, mismatch, ideal reactances and matching; [SCIKIT_RF_WAVES](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html) - Power/pseudo/traveling waves and complex reference impedance.

**후속 계산:** [EQ-011](#EQ-011), [EQ-012](#EQ-012), [EQ-013](#EQ-013).

**산술 참고 벡터:** `{"Z_ohm_re_im":[100,0],"R0_ohm":50}` -> `{"gamma_re_im":[0.3333333333333333,0],"return_loss_dB":9.54242509439325,"VSWR":2}`.

<a id="EQ-011"></a>

### EQ-011 - 복소 기준 임피던스 power/pseudo waves

$$
\begin{aligned}a&=\frac{V+Z_0I}{2\sqrt{\operatorname{Re}Z_0}},&b&=\frac{V-Z_0^*I}{2\sqrt{\operatorname{Re}Z_0}},&P&=|a|^2-|b|^2,\\a_p&=\frac{\sqrt{\operatorname{Re}Z_0}}{2|Z_0|}(V+Z_0I),&b_p&=\frac{\sqrt{\operatorname{Re}Z_0}}{2|Z_0|}(V-Z_0I),\\P&=|a_p|^2-|b_p|^2+2\operatorname{Im}(a_pb_p^*)\frac{\operatorname{Im}Z_0}{\operatorname{Re}Z_0}.\end{aligned}
$$

**적용:** 외부 전류는 DUT 안쪽이 양수이고 Re(Z0)>0이다. power waves의 제곱이 W이며 net power는 |a|^2-|b|^2이다. pseudo waves에는 복소 Z0의 교차항이 추가된다.

**한계, 예외:** 순허수, 음의 실수 Z0와 evanescent mode는 이 정규화로 자동 처리하지 않는다. 라이브러리의 미소 실수 보정을 물리 검증으로 간주하지 않는다. power Gamma를 전압 Smith-chart Gamma로 혼동하지 않는다.

**입력:** `V,I` [V RMS; A RMS] - current into DUT; `Z0,ZL` [ohm complex] - reference/load, ReZ0>0.

**출력:** `a,b` [sqrt(W)] - power waves; `ap,bp` [sqrt(W)] - pseudo waves; `Pnet` [W] - net accepted at plane.

**근사 등급, 단계:** `established_wave_conventions` ,  R1. **구현/위임:** scikit-rf s_def explicit; native V/I amplitude mapping gate.

**근거:** [SCIKIT_RF_WAVES](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html) - Power/pseudo/traveling waves and complex reference impedance; [NIST_MARKS_1992](https://www.nist.gov/publications/general-waveguide-circuit-theory) - Marks/Williams DOI10.6028/jres.097.024; general waveguide circuit theory; [SCIKIT_RF_VI](https://scikit-rf.readthedocs.io/en/latest/examples/circuit/Voltages%20and%20Currents%20in%20Circuits.html) - External/internal current direction; returned V/I peak values.

**후속 계산:** [EQ-012](#EQ-012), [EQ-014](#EQ-014), [EQ-015](#EQ-015).

**산술 참고 벡터:** `{"Z0_ohm_re_im":[50,25],"ZL_ohm_re_im":[50,-25]}` -> `{"gamma_power_re_im":[0,0],"gamma_voltage_re_im":[0,-0.5]}`.

<a id="EQ-012"></a>

### EQ-012 - S<->Z 변환과 S renormalization

표시 행렬식은 `s_def=power`, 각 포트 `Re(Z0)>0`인 경우에 한정한다. pseudo/traveling은 해당 파 정의의 별도 변환과 독립 V/I oracle를 사용한다. (PHYS-003)

$$
\begin{aligned}G&=\operatorname{diag}(Z_0),\quad F=\operatorname{diag}\left(\frac1{2\sqrt{\operatorname{Re}Z_0}}\right),\\S&=F(Z-G^*)(Z+G)^{-1}F^{-1},\\Z&=F^{-1}(I-S)^{-1}(SG+G^*)F.\end{aligned}
$$

**적용:** 입력과 출력의 s_def, Z0(f), 포트 순서와 기준면이 알려져 있어야 한다. 행렬 곱의 순서를 보존하고 선형계 풀이를 사용한다.

**한계, 예외:** singular/ill-conditioned (I-S) 또는 (Z+G)는 진단한다. renormalization은 reference-plane 이동이나 fixture 제거가 아니다. unknown s_def를 라이브러리 기본값으로 숨기지 않는다.

**입력:** `S` [1 complex[N,N]] - raw matrix withport order; `Zold,Znew` [ohm complex[N]] - frequency-dependent reference; `s_def` [enum] - power/pseudo/traveling.

**출력:** `Snew` [1 complex[N,N]] - renormalizedmatrix; `Z` [ohm complex[N,N]] - circuitimpedance.

**근사 등급, 단계:** `established_matrix_conversion` ,  R1. **구현/위임:** scikit-rf Network.renormalize / renormalize_s; no handwritten production inverse.

**근거:** [SCIKIT_RF_S2Z](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.s2z.html) - Power-wave formula with F and G; Kurokawa / Marks references; [SCIKIT_RF_Z2S](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.z2s.html) - Power/pseudo-wave transformation; [SCIKIT_RF_RENORM](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.renormalize_s.html) - s_def, s_def_old; old/new reference impedance.

**후속 계산:** [EQ-014](#EQ-014), [EQ-029](#EQ-029), [EQ-030](#EQ-030), [EQ-031](#EQ-031).

**산술 참고 벡터:** `{"Z_ohm":50,"old_R0_ohm":50,"new_R0_ohm":25}` -> `{"old_S11":0,"new_S11":0.3333333333333333,"restored_Z_ohm":50}`.

수학 표기의 역행렬은 구현 명령이 아니다. factorization/linear solve를 쓰고 조건수, 잔차, singularity를 기록한다.

EQ-012의 power-wave 행렬 순서는 공식 [s2z](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.s2z.html)와 [z2s](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.z2s.html)의 정의와 일치한다. 이것은 문서 대조 결과이며 설치본 검증이 아니다. 포트마다 다른 complex Z0를 사용하는 비대각 Z fixture로 곱 순서와 V/I 전력 보존을 개발 후 확인한다. scalar 또는 동일 Z0의 대각 fixture만으로 이 조건을 검증하지 않는다.

<a id="EQ-013"></a>

### EQ-013 - 단일 포트 전력, mismatch

$$
P_{\rm acc}=P_{\rm inc}-P_{\rm ref},\quad\eta_{\rm match}=1-|\Gamma|^2,\quad\eta_{\rm rad}=P_{\rm rad}/P_{\rm acc},\quad\eta_{\rm total}=P_{\rm rad}/P_{\rm inc}
$$

**적용:** 단일 외부 포트와 검증된 power normalization에서, 같은 plane의 입사, 반사, 방사 전력을 사용한다.

**한계, 예외:** 다른 포트로 나간 전력이 있으면 단일 S11 shortcut을 적용하지 않는다. Pinc 또는 Pacc가 0이면 해당 효율은 undefined이다. S11이 약 0이라는 사실만으로 방사효율을 알 수 없다.

**입력:** `Pinc,Pref,Prad` [W] - single-port same-planepowers.

**출력:** `Pacc` [W] - acceptedpower; `etamatch,etarad,etatotal` [1] - separatedefficiencies.

**근사 등급, 단계:** `established_power_bookkeeping` ,  R1. **구현/위임:** domainpowerledger.

**근거:** [QORVO_APH007](https://www.qorvo.com/products/r/ra007022) 물리 p.4,5 - DW1000 antenna requirements, efficiency and group delay; scoped recommendations; [TI_AN058_SWRA161](https://www.ti.com/lit/pdf/swra161) 물리 p.4,5,6,20,23,24,25,26 - section 3.1-3.4 initial lengths and wave conventions; calibration/matching/OTA.

**후속 계산:** [EQ-014](#EQ-014), [EQ-015](#EQ-015), [EQ-017](#EQ-017).

**산술 참고 벡터:** `{"Pinc_W":1,"Pref_W":0.25,"Prad_W":0.6}` -> `{"Pacc_W":0.75,"eta_rad":0.8,"eta_total":0.6,"Pdiss_W":0.15}`.

<a id="EQ-014"></a>

### EQ-014 - 다중 포트 전력, TARC

$$
\mathbf b=S\mathbf a,\quad P_{\rm inc}=\mathbf a^\dagger\mathbf a,\quad P_{\rm out}=\mathbf b^\dagger\mathbf b,\quad P_{\rm acc}=\mathbf a^\dagger(I-S^\dagger S)\mathbf a,\quad TARC=\sqrt{P_{\rm out}/P_{\rm inc}}
$$

**적용:** 모든 접근 가능한 포트를 포함한 power-wave S와 여기 벡터 a를 사용한다. 부하, 위상, 주파수가 동일한 상태에서 계산한다.

**한계, 예외:** 다른 포트로 나간 전력은 방사 전력이 아니다. 외부 정합망이 포함되면 입력 plane과 내부 안테나 plane을 구별한다. pseudo/traveling S에는 유효 power metric 확인 없이 이 식을 적용하지 않는다.

**입력:** `S` [1 complex[N,N]] - samepowerwavenorm; `a` [sqrt(W) complex[N]] - simultaneousincidentwaves.

**출력:** `Pinc,Pout,Pacc` [W] - allaccessibleportsbookkeeping; `TARC,etaaccepted` [1] - excitationdependent.

**근사 등급, 단계:** `established_multiport_power` ,  R2. **구현/위임:** scikit-rf network data + Hermitianproducts.

**근거:** [SCIKIT_RF_WAVES](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html) - Power/pseudo/traveling waves and complex reference impedance; [B-S48](https://onlinelibrary.wiley.com/doi/10.1155/2011/421691) - Dama et al. section 2-3, equations1-15; intrinsic-loss matrix.

**후속 계산:** [EQ-015](#EQ-015), [EQ-017](#EQ-017), [EQ-024](#EQ-024), [EQ-032](#EQ-032).

**산술 참고 벡터:** `{"S_re":[[0,0.5],[0.5,0]],"a_re":[1,0]}` -> `{"Pinc_W":1,"Pout_W":0.25,"Pacc_W":0.75,"TARC":0.5,"S11_only_wrong_Pacc_W":1}`.

<a id="EQ-015"></a>

### EQ-015 - 에너지 수지, 수동성 진단

$$
R_P=P_{\rm acc}-P_{\rm rad}-P_{\rm cond}-P_{\rm diel}-P_{\rm other},\quad\rho_P=|R_P|/\max(P_{\rm inc},P_{\rm floor}),\quad I-S^\dagger S\succeq0
$$

**적용:** 정상상태이며 모든 관련 손실, 유출 경로를 포함한 전력 수지를 검사한다. I-S^HS PSD 검사는 유효한 power-wave 기저의 수동 선형 network에 적용한다.

**한계, 예외:** PML 흡수 전력 전체를 자동으로 Prad로 놓지 않는다. 수동성이 상호성을 뜻하지 않는다. 복소 기준 임피던스에서 단순 S=S^T 검사는 별도 reciprocity 정의 확인이 필요하다. 유한대역 진단은 전역 인과성 증명이 아니다.

**입력:** `P*` [W] - same domain/ref planes; `Pfloor` [W] - declared numerical normalizationfloor; `S` [1] - power-normalizedmatrix.

**출력:** `Rpower` [W] - residual; `rhopower` [1] - normalizedresidual; `lambdamin` [1] - passivitydiagnostic.

**근사 등급, 단계:** `established_balance_plus_diagnostic_policy` ,  R1. **구현/위임:** domainledger + validated librarydiagnostics.

**근거:** [BOOK_MIT_STAELIN](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf) 물리 p.56,59,60,82 - section 2.6-2.7; equations 2.7.15-2.7.24; mutual-inductance matrix 3.2.35-3.2.37; [SKRF_MANUAL_PDF](https://scikit-rf.readthedocs.io/_/downloads/en/latest/pdf/) 물리 p.184,185,199,200 - Passivity/reciprocity/causality diagnostics; informative not universal proof; [B-S48](https://onlinelibrary.wiley.com/doi/10.1155/2011/421691) - Dama et al. section 2-3, equations1-15; intrinsic-loss matrix.

**후속 계산:** [EQ-017](#EQ-017), [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"Pacc_W":0.75,"Prad_W":0.6,"Pcond_W":0.1,"Pdiel_W":0.05,"Pinc_W":1}` -> `{"Rpower_W":0,"rho_power":0}`.

<a id="EQ-016"></a>

### EQ-016 - Poynting, 방사 세기, 방사 전력

$$
\mathbf S_{\rm avg}=\operatorname{Re}(\mathbf E\times\mathbf H^*),\quad U=r^2\mathbf S_{\rm avg}\cdot\hat{\mathbf r},\quad P_{\rm rad}=\int_{4\pi}U\,d\Omega,\quad U=\frac{r^2(|E_\theta|^2+|E_\phi|^2)}{\eta}
$$

**적용:** RMS E/H의 평균 Poynting 벡터를 적분한다. E만 쓰는 식은 outgoing far field와 실수 eta의 균질 무손실 매질을 전제로 한다.

**한계, 예외:** native rE 또는 r-normalized field를 실제 E[V/m]로 착각하지 않는다. 구면 quadrature는 sin(theta), 극점과 phi=0과 phi=2*pi의 중복을 처리한다. RMS에 추가 1/2를 곱하지 않는다. 전체 구면 coverage가 없고 대칭 복원도 검증되지 않았다면 부분각 적분을 총 Prad로 표시하지 않는다. 각도별 invalid mask와 누락 coverage를 보존하며 임의 0 채움으로 총 전력을 산출하지 않는다.

**입력:** `E,H` [V/m; A/m RMS] - phasorfields; `r` [m] - farfieldsphereradius; `theta,phi` [rad] - thetafrom+z,phifrom+x toward+y; `eta` [ohm] - realpositivewaveimpedance.

**출력:** `Savg` [W/m^2] - timeaverageflux; `U` [W/sr] - radiationintensity; `Prad` [W] - sphereintegral.

**근사 등급, 단계:** `established_Poynting_definition` ,  R1. **구현/위임:** solver NF2FF then domainconsistentquadrature.

**근거:** [BOOK_MIT_STAELIN](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf) 물리 p.56,59,60,82 - section 2.6-2.7; equations 2.7.15-2.7.24; mutual-inductance matrix 3.2.35-3.2.37; [OPENEMS_NF2FF](https://docs.openems.de/en/latest/concepts/nf2ff.html) - Surfaces; phase center; angle/radius/medium; Fourier recording; [B-S03](https://www.mathworks.com/help/antenna/ug/field-calculation-in-antennas.html) - Field parameters, directivity/gain definitions.

**후속 계산:** [EQ-017](#EQ-017), [EQ-018](#EQ-018), [EQ-019](#EQ-019), [EQ-023](#EQ-023), [EQ-032](#EQ-032).

**산술 참고 벡터:** `{"Etheta_V_per_m":1,"Ephi":0,"Hphi_A_per_m":0.0026544187294380724,"r_m":2,"eta_ohm":376.73031346177066}` -> `{"Savg_W_per_m2":0.0026544187294380724,"U_W_per_sr":0.01061767491775229}`.

<a id="EQ-017"></a>

### EQ-017 - 효율, directivity, gain, realized gain

$$
D=4\pi U/P_{\rm rad},\quad G=4\pi U/P_{\rm acc}=\eta_{\rm rad}D,\quad G_{\rm realized}=4\pi U/P_{\rm inc}=\eta_{\rm total}D
$$

**적용:** 모든 분모가 양수이고 field와 power가 동일한 주파수, 여기, 좌표, normalization을 가진다. 포함한 network loss와 reference plane을 표시한다.

**한계, 예외:** Prad=0이면 D는 undefined이다. gain과 realized gain을 같은 이름으로 표시하지 않는다. 선형 gain에10log10, field amplitude에20log10을 사용한다.

**입력:** `U` [W/sr] - selecteddirection/polarization; `Prad,Pacc,Pinc` [W] - sameexcitationandplane.

**출력:** `D,G,Grealized` [1] - linear ratios; `etarad,etatotal` [1] - efficiencies.

**근사 등급, 단계:** `established_antenna_definitions` ,  R1. **구현/위임:** domain withsolverNF2FF.

**근거:** [RS_8GE01_ANTENNA_BASICS](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/premiumdownloads/premium_dl_brochures_and_datasheets/premium_dl_whitepaper/Antenna_Basics_8GE01_1e.pdf) 물리 p.7,13,14 - Far-field, directivity/gain, effective area; [QORVO_APH007](https://www.qorvo.com/products/r/ra007022) 물리 p.4,5 - DW1000 antenna requirements, efficiency and group delay; scoped recommendations; [TI_AN058_SWRA161](https://www.ti.com/lit/pdf/swra161) 물리 p.4,5,6,20,23,24,25,26 - section 3.1-3.4 initial lengths and wave conventions; calibration/matching/OTA.

**후속 계산:** [EQ-023](#EQ-023), [EQ-035](#EQ-035), [EQ-040](#EQ-040).

**산술 참고 벡터:** `{"U_W_per_sr":0.0477464829275686,"Prad_W":0.6,"Pacc_W":0.75,"Pinc_W":1}` -> `{"D":1,"G":0.8,"Grealized":0.6,"eta_rad":0.8,"eta_total":0.6}`.

<a id="EQ-018"></a>

### EQ-018 - 편파 성분과 축비

$$
C=\operatorname{Re}(\mathbf e\mathbf e^\dagger),\quad\mathbf e=[E_\theta,E_\phi]^T,\quad AR=\sqrt{\lambda_{\max}(C)/\lambda_{\min}(C)},\quad E_{c\pm}=(E_\theta\pm jE_\phi)/\sqrt2
$$

**적용:** 같은 구면기저와 phasor convention의 Etheta,Ephi로 polarization ellipse를 계산한다. LHCP/RHCP 이름은 진행방향, 관찰방향 fixture가 확인된 뒤 붙인다.

**한계, 예외:** 작은 고유값이 0이면 선형 편파 AR=infinity, 전체 field가 0이면 AR는 undefined이다. sign 하나만으로 손잡이를 정하지 않는다.

**입력:** `Etheta,Ephi` [V/m RMS complex] - transverse coherentcomponents.

**출력:** `AR` [1] - ellipsemajor/minor; `Ec+/-` [V/m RMS] - declaredcircularbasiscomponents.

**근사 등급, 단계:** `polarization_algebra_definition` ,  R2. **구현/위임:** numpy Hermitian/eigenvalue operations; conventionfixture.

**근거:** [RS_8GE01_ANTENNA_BASICS](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/premiumdownloads/premium_dl_brochures_and_datasheets/premium_dl_whitepaper/Antenna_Basics_8GE01_1e.pdf) 물리 p.7,13,14 - Far-field, directivity/gain, effective area.

**후속 계산:** [EQ-023](#EQ-023), [EQ-035](#EQ-035).

**산술 참고 벡터:** `{"Etheta":[1,0],"Ephi":[0,1]}` -> `{"AR":1,"AR_dB":0}`.

<a id="EQ-019"></a>

### EQ-019 - NF2FF, 원거리 근사 조건

$$
r_F\approx2D^2/\lambda_0\quad\text{(large-aperture reference only)}
$$

**적용:** 2D^2/lambda는 전기적으로 큰 aperture의 원거리 phase 오차를 위한 참고 근사다. native NF2FF는 radiator를 감싼 표면과 매질, PML, field-recording 조건을 충족해야 한다.

**한계, 예외:** 이 거리 하나로 모든 작은 안테나의 far-field 조건을 판정하지 않는다. 변환면이 금속, 손실 영역, PML을 잘못 가로지르면 unsupported이다. 원거리 field는 r 치환만으로 얻지 않는다.

**입력:** `D,lambda0,r` [m] - structureextent,wavelength,observationdistance; `surface` [geometry] - NF2FFrecording surface.

**출력:** `distance_checks` [structured] - scopedapproximations; `Efar` [V/m complex] - solverderivedfarfield.

**근사 등급, 단계:** `scoped_farfield_approximation_and_solver_transform` ,  R1. **구현/위임:** openEMS NF2FF; no homemade universal transform.

**근거:** [RS_8GE01_ANTENNA_BASICS](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/premiumdownloads/premium_dl_brochures_and_datasheets/premium_dl_whitepaper/Antenna_Basics_8GE01_1e.pdf) 물리 p.7,13,14 - Far-field, directivity/gain, effective area; [OPENEMS_NF2FF](https://docs.openems.de/en/latest/concepts/nf2ff.html) - Surfaces; phase center; angle/radius/medium; Fourier recording.

**후속 계산:** [EQ-016](#EQ-016), [EQ-017](#EQ-017), [EQ-023](#EQ-023).

**산술 참고 벡터:** `{"D_m":1,"lambda0_m":0.1}` -> `{"large_aperture_rF_m":20}`.

<a id="EQ-020"></a>

### EQ-020 - 전달함수 group delay

$$
\tau_g=-\frac{d\arg H}{d\omega}=-\frac1{2\pi}\frac{d\arg H}{df},\quad H_{\rm delay}=e^{-j2\pi f\tau},\quad\tau_{\rm excess}=\tau_{\rm pair}-r/c_0
$$

**적용:** 일관된 plane, phase origin을 가진 Hpair(f)를 충분히 샘플링한 대역에서 위상 미분한다. 자유공간 거리 보정은 해당 경로와 plane 정의가 확인될 때만 한다.

**한계, 예외:** 진폭 null과 불확실한 phase 구간을 마스킹한다. S11의 group delay를 전파 지연으로 보지 않는다. pair delay를 근거 없이 두 안테나에 절반씩 나누지 않는다.

**입력:** `f` [Hz] - coherentfrequencygrid; `H` [complex] - pair/chaintransfer; `r` [m] - declaredpropagationdistance.

**출력:** `taug` [s] - groupdelay; `tauexcess` [s] - conditionalexcessdelay.

**근사 등급, 단계:** `transfer_function_definition` ,  R2. **구현/위임:** numpy/scipy phase/derivative withdeclaredsmoothing.

**근거:** [PAPER-066](http://ael.chungbuk.ac.kr/lectures/undergraduate/%EC%A2%85%ED%95%A9%EC%84%A4%EA%B3%84-1/2018-2/%EC%9D%B4%EC%88%98%ED%98%B8/liang(06-thesis).pdf) 물리 p.152,153,154,155,157,158,180,181 - Liang thesis chapter6 antenna pair/time-domain fidelity; [QORVO_APH007](https://www.qorvo.com/products/r/ra007022) 물리 p.4,5 - DW1000 antenna requirements, efficiency and group delay; scoped recommendations; [QORVO_APS014](https://www.qorvo.com/products/r/ra007040) 물리 p.5,6,7 - Device/configuration-dependent delay calibration.

**후속 계산:** [EQ-021](#EQ-021), [EQ-022](#EQ-022).

**산술 참고 벡터:** `{"H_definition":"exp(-j2*pi*f*5e-9)"}` -> `{"tau_group_s":5e-09}`.

<a id="EQ-021"></a>

### EQ-021 - 대역 가중 시간응답

$$
\begin{aligned}Y(f)&=W(f)H_{\rm pair}(f)X(f),&y(t)&=\int Y(f)e^{+j2\pi ft}df,\\y_n&=\Delta f\sum_kY_ke^{+j2\pi kn/N}=N\Delta f\operatorname{IFFT}_{\rm backward}(Y)_n,\\\Delta t&=1/(N\Delta f),&\sum_n|y_n|^2\Delta t&=\sum_k|Y_k|^2\Delta f.\end{aligned}
$$

**적용:** 실수 passband 또는 complex baseband, 균일 FFT bin 순서, Delta_f, N, carrier, time origin을 명시한다. continuous spectrum 샘플은 backward IFFT에 N*Delta_f, ortho에 sqrt(N)*Delta_f, forward에 Delta_f를 곱한다. 절대 waveform amplitude와 Parseval을 검사한다.

**한계, 예외:** 불균일 grid 직접 IFFT는 거부하고 별도 resampling/NUFFT 변환을 요구한다. bin 순서, carrier/time origin, missing DC를 임의 추정하지 않는다. instantaneous waveform에 RMS 변환 sqrt(2)를 자동 추가하지 않으며 zero padding은 정보량을 늘리지 않는다. 이 식의 Y는 완전한 양면 spectrum 또는 명시된 complex-baseband spectrum이다. native 단측 spectrum을 그대로 양면 IFFT 배열로 넣지 않는다. 실수 waveform 재구성 시 DC/Nyquist와 양의 주파수의 2배 계수를 구분하고 Hermitian completion 규칙을 기록한다.

**입력:** `f` [Hz] - frequencygrid; `W,Hpair` [1 complex] - bandweightandtransfer; `X` [V*s or declared] - inputwaveformspectrum; `FFT normalization and bin_order` [enum/metadata] - backward(default)/ortho/forward, standard FFT order 또는 명시된 ifftshift mapping; Delta_f, N, t0, carrier offset와 spectrum amplitude 단위를 기록; `Y_k` [signal_unit*s; fixture V*s] - 적용된 H*X*W를 포함하는 continuous Fourier spectrum의 균일 bin 샘플. raw FFT coefficients와 구별한다.

**출력:** `y` [V or declared] - timewaveform; `t` [s] - explicit timeorigin/shift; `time/frequency signal-energy integrals` [signal_unit^2*s; fixture V^2*s] - Parseval 검사. 전압 제곱 적분은 load/reference 없이 전기 에너지 J로 부르지 않는다..

**근사 등급, 단계:** `Fourier_transform_and_signal_processing_policy` ,  R2. **구현/위임:** numpy/scipy FFT, testednormalization; no inventedunmeasuredspectrum.

**근거:** [PAPER-066](http://ael.chungbuk.ac.kr/lectures/undergraduate/%EC%A2%85%ED%95%A9%EC%84%A4%EA%B3%84-1/2018-2/%EC%9D%B4%EC%88%98%ED%98%B8/liang(06-thesis).pdf) 물리 p.152,153,154,155,157,158,180,181 - Liang thesis chapter6 antenna pair/time-domain fidelity; [PAPER-067](https://www.jpier.org/ac_api/download.php?id=07092004) 물리 p.2,3,4,5,6,7,8,9 - Pulse-preserving antenna comparison and normalized correlation; [NUMPY_FFT_NORMALIZATION](https://numpy.org/doc/stable/reference/routines.fft.html) - Implementation details: inverse DFT 1/N; Normalization: backward/ortho/forward; standard FFT frequency ordering.

**후속 계산:** [EQ-022](#EQ-022), [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"N":1024,"delta_f_Hz":1000000.0}` -> `{"delta_t_s":9.765625e-10,"window_s":1e-06}`.

균일 주파수의 inverse Riemann sum을 IFFT로 구현하면 library의 1/N 정규화와 Delta_f를 반영한다. zero-centered spectrum 정렬, carrier offset 및 실제 시간 원점을 독립 fixture로 확인한다.

<a id="EQ-022"></a>

### EQ-022 - 정규화 pulse fidelity

$$
\rho(\tau)=\frac{\int x^*(t)y(t-\tau)dt}{\sqrt{\int|x|^2dt\int|y|^2dt}},\qquad F=\max_\tau|\rho(\tau)|
$$

**적용:** 두 신호의 에너지가 양수이고 비교 대역, 시간 창, 상관 정의가 같을 때 정규화 상관을 계산한다. 복소 correlation magnitude와 signed real correlation을 구별한다.

**한계, 예외:** fidelity는 전송 전력효율도 absolute ranging 정확도도 아니다. zero-energy 입력은 undefined이다. 최대값을 얻기 위해 이동한 tau를 함께 보고한다.

**입력:** `x,y` [samewaveformunits] - coherentlysampledpulses; `taurange` [s] - allowedalignmentrange; `window` [s] - integrationwindow.

**출력:** `fidelity` [1] - amplitude-normalizedcorrelation; `taupeak` [s] - bestalignment.

**근사 등급, 단계:** `normalized_correlation_definition` ,  R2. **구현/위임:** scipy correlate afterexplicitresampling.

**근거:** [PAPER-067](https://www.jpier.org/ac_api/download.php?id=07092004) 물리 p.2,3,4,5,6,7,8,9 - Pulse-preserving antenna comparison and normalized correlation; [PAPER-066](http://ael.chungbuk.ac.kr/lectures/undergraduate/%EC%A2%85%ED%95%A9%EC%84%A4%EA%B3%84-1/2018-2/%EC%9D%B4%EC%88%98%ED%98%B8/liang(06-thesis).pdf) 물리 p.152,153,154,155,157,158,180,181 - Liang thesis chapter6 antenna pair/time-domain fidelity.

**후속 계산:** [EQ-020](#EQ-020), [EQ-035](#EQ-035).

**산술 참고 벡터:** `{"x":[1,2,1],"y":[2,4,2],"alignment":"zero"}` -> `{"fidelity":1}`.

위 식의 shift 부호를 그대로 따르면 `y(t)=x(t-tau0)`의 정렬 최대점은 `tau_peak=-tau0`다. tau_peak는 y에 적용할 정렬 이동량이고, 이 조건에서 물리적 지연은 `-tau_peak`다. EQ-020의 양의 전달 지연과 같은 부호로 표시하려면 이 변환을 명시한다. scipy correlate의 인자 순서와 lag 정의를 독립 순수 지연 fixture로 확인하고 최대 상관값만 맞았다는 이유로 지연 부호를 검증했다고 판단하지 않는다.

<a id="EQ-023"></a>

### EQ-023 - 복소 far-field ECC

$$
B_{ij}=\int_\Omega\mathbf F_i^\dagger(\Omega)W(\Omega)\mathbf F_j(\Omega)\,d\Omega,\quad ECC_{ij}=|B_{ij}|^2/(B_{ii}B_{jj})
$$

**적용:** 복소 embedded field와 Hermitian PSD angular/polarization weighting W를 사용한다. 공통 주파수, 부하, plane, 위상 중심, 관측 좌표가 필요하다.

**한계, 예외:** Bii 또는 Bjj가 0이면 ECC는 undefined이다. 실제 field에 손실이 반영된 경우는 사용 가능하나 scalar efficiency만으로 모르는 pattern/loss cross term을 복구하지 않는다.

**입력:** `Fi,Fj` [declaredcomplexfieldunits] - theta/phicomponents incommoncoordinates/phasecenter; `W` [nonnegativeangularpower weighting] - 2*2polarizationcovariancematrix.

**출력:** `ECC` [1] - channel-conditionedcorrelation.

**근사 등급, 단계:** `farfield_channel_correlation` ,  R2. **구현/위임:** domain angularquadrature on solver/measurementcomplexpatterns.

**근거:** [B-S48](https://onlinelibrary.wiley.com/doi/10.1155/2011/421691) - Dama et al. section 2-3, equations1-15; intrinsic-loss matrix; [PAPER-031](https://www.mdpi.com/2079-9292/13/13/2430/pdf) 물리 p.6 - ECC from radiation patterns; element position dependence.

**후속 계산:** [EQ-024](#EQ-024), [EQ-035](#EQ-035).

**산술 참고 벡터:** `{"Fi":[1,0],"Fj":[0,1],"W":"I","angularshape":"identicalconstant"}` -> `{"ECC":0}`.

<a id="EQ-024"></a>

### EQ-024 - S-only ECC 근사와 손실 한계

$$
B_{\rm lossless}=I-S^\dagger S,\qquad B_{\rm rad}=I-S^\dagger S-L_{\rm loss},\qquad ECC_{ij}=|B_{ij}|^2/(B_{ii}B_{jj})
$$

**적용:** S-only shortcut은 본질적으로 무손실인 수동 배열과 명시된 isotropic diffuse 환경, 포트 기저를 전제로 한다. lossy case에는 검증된 전체 loss matrix가 필요하다.

**한계, 예외:** 효율 스칼라들은 loss matrix의 대각성분 정보만 제공할 수 있다. off-diagonal loss를 임의 생성하지 않으며 손실 있는 안테나의 S-only ECC를 정확값으로 표시하지 않는다.

**입력:** `S` [1 complex[N,N]] - powerwaves; `Lloss` [1 Hermitian[N,N]] - lossquadraticformincludingcross terms.

**출력:** `ECCapprox` [1] - restrictedS-onlyestimate; `Brad` [1 Hermitian] - radiationmatrix.

**근사 등급, 단계:** `restricted_lossless_shortcut_or_loss_matrix_model` ,  R2. **구현/위임:** preferEQ023; librarymatrix algebra.

**근거:** [B-S48](https://onlinelibrary.wiley.com/doi/10.1155/2011/421691) - Dama et al. section 2-3, equations1-15; intrinsic-loss matrix; [SCIKIT_RF_WAVES](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html) - Power/pseudo/traveling waves and complex reference impedance.

**후속 계산:** [EQ-023](#EQ-023), [EQ-035](#EQ-035).

**산술 참고 벡터:** `{"S_re":[[0,0],[0,0]],"lossless_assumed":true}` -> `{"B":[[1,0],[0,1]],"ECC12":0}`.

<a id="EQ-025"></a>

### EQ-025 - NFC coil R/L/Q 및 self resonance

$$
R=\operatorname{Re}Z,\quad L=\operatorname{Im}Z/\omega,\quad Q_{\rm series}=\omega L/R,\quad f_{\rm SR,ideal}=1/(2\pi\sqrt{LC_p})
$$

**적용:** 수동, 유도성이고 등가 series RL이 타당한 band에서 R=Re(Z), L=Im(Z)/omega, Q=omega*L/R를 정의한다. self-resonance 근사는 이상 L과 Cp에만 적용한다.

**한계, 예외:** loaded Q는 전체 network/transfer function에서 정의한다. 공진을 넘어 negative reactance인 구간을 양의 inductance로 강제 변환하지 않는다. R=0의 Q는 유한값이 아니다.

**입력:** `Z` [ohm complex] - deembeddedcoilimpedance; `f` [Hz] - testfrequency; `Cp` [F] - specifiedlumpedparasitic.

**출력:** `R` [ohm] - seriesresistance; `L` [H] - singlefrequencyestimate; `Q` [1] - barecoil estimate; `fSR` [Hz] - idealLCseed.

**근사 등급, 단계:** `equivalent_circuit_estimate` ,  R3. **구현/위임:** NFC circuit/quasistatic adapter; measuredZ extraction.

**근거:** [NXP_AN12549](https://www.nxp.com/docs/en/application-note/AN12549.pdf) 물리 p.11,15,38,40,54 - Coil/loaded Q; measurement/tuning; position/operating volume; [SILABS_AN1275](https://www.silabs.com/documents/public/application-notes/an1275-imp-match-for-network-arch.pdf) 물리 p.4,5,12,14,15 - Reflection, mismatch, ideal reactances and matching.

**후속 계산:** [EQ-026](#EQ-026), [EQ-028](#EQ-028).

**산술 참고 벡터:** `{"f_Hz":13560000.0,"R_ohm":2,"X_ohm":85.19999276535518}` -> `{"L_H":1e-06,"Q":42.59999638267759}`.

<a id="EQ-026"></a>

### EQ-026 - 상호 인덕턴스와 결합계수

$$
\begin{bmatrix}V_1\\V_2\end{bmatrix}=j\omega\begin{bmatrix}L_1&M\\M&L_2\end{bmatrix}\begin{bmatrix}I_1\\I_2\end{bmatrix},\quad k=M/\sqrt{L_1L_2},\quad W_m=\tfrac12\mathbf i^TL\mathbf i
$$

**적용:** 선형 quasi-static 두 코일의 reciprocal inductance matrix를 쓴다. 실수 L1,L2>0, PSD matrix에서 |k|<=1이다. M과 k의 부호는 dot/current 방향으로 정한다.

**한계, 예외:** 복잡한 RF 결합을 순수 inductance 하나로 모두 표현하지 않는다. 손실과 주파수 의존성은 별도 network에 포함한다. 에너지식의 i는 RMS phasor가 아닌 순간 실수 전류이다.

**입력:** `L1,L2,M` [H] - linearreciprocalmagnetoquasistaticinductancematrix; `omega` [rad/s] - frequency.

**출력:** `k` [1 signed] - couplingwithdotconvention.

**근사 등급, 단계:** `linear_coupled_inductor_definition` ,  R3. **구현/위임:** quasistatic/EM solver pluscircuit extraction.

**근거:** [BOOK_MIT_STAELIN](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf) 물리 p.56,59,60,82 - section 2.6-2.7; equations 2.7.15-2.7.24; mutual-inductance matrix 3.2.35-3.2.37; [NXP_AN12549](https://www.nxp.com/docs/en/application-note/AN12549.pdf) 물리 p.11,15,38,40,54 - Coil/loaded Q; measurement/tuning; position/operating volume.

**후속 계산:** [EQ-025](#EQ-025), [EQ-029](#EQ-029).

**산술 참고 벡터:** `{"L1_H":1e-06,"L2_H":4e-06,"M_H":5e-07}` -> `{"k":0.25}`.

<a id="EQ-027"></a>

### EQ-027 - UHF RFID 공액 전력전달

$$
\tau=\frac{4R_aR_c}{|Z_a+Z_c|^2},\qquad\tau=1\ \text{if }Z_a=Z_c^*,\ R_a,R_c>0
$$

**적용:** Ra,Rc>0의 안테나 Thevenin impedance와 수동 chip impedance를 같은 plane, frequency, power operating point에서 비교한다.

**한계, 예외:** 비선형 chip 정류, 감도, 변조 상태는 고정 선형 Z만으로 모두 설명하지 않는다. tau=1은 방사효율 또는 보장 read range를 뜻하지 않는다.

**입력:** `Za,Zc` [ohm complex] - antennaThevenin andassembledchip impedance atdeclaredfrequency/power.

**출력:** `tau` [1] - availableantenna-to-chip powertransferfactor.

**근사 등급, 단계:** `Thevenin_conjugate_matching_definition` ,  R3. **구현/위임:** domainnetwork; RFchipfixture.

**근거:** [PAPER-043](https://art.torvergata.it/bitstream/2108/31667/44089/AP-Magaz_tag_Tutorial_2008.pdf) 물리 p.2 - Power-transfer coefficient and complex power-dependent chip impedance; [NXP_AN1715](https://www.nxp.com/docs/en/application-note/AN171530.pdf) 물리 p.20,24,25 - Assembled-chip conjugate match; substrate and geometry.

**후속 계산:** [EQ-028](#EQ-028), [EQ-040](#EQ-040).

**산술 참고 벡터:** `{"Za_ohm_re_im":[20,100],"Zc_ohm_re_im":[20,-100]}` -> `{"tau":1}`.

<a id="EQ-028"></a>

### EQ-028 - 이상 LC와 실제 정합망

$$
Z_L=j\omega L,\quad Z_C=1/(j\omega C),\quad Z_R=R,\quad Z_{\rm real}=Z(f,T,P,\text{package})
$$

**적용:** 이상 R/L/C는 선형 회로의 기준이며 실제 부품은 Q/ESR/ESL/SRF, 주파수, 온도, 전력, 패키지를 가진 모델로 대체한다.

**한계, 예외:** f=0의 open/short는 topology로 처리하며 무한, 거대 숫자로 우회하지 않는다. 능동소자를 선언하지 않은 수동 합성에서 음의 R/L/C를 만들지 않는다.

**입력:** `L,C,R` [H;F;ohm] - idealcomponentvalues; `f` [Hz] - evaluationfreq; `model` [structured] - realcomponentparasiticsandvalidity.

**출력:** `Z` [ohm complex] - componentimpedance.

**근사 등급, 단계:** `ideal_lumped_model_or_measured_component` ,  R1. **구현/위임:** scikit-rf Circuit/Network; componentmodels.

**근거:** [SILABS_AN1275](https://www.silabs.com/documents/public/application-notes/an1275-imp-match-for-network-arch.pdf) 물리 p.4,5,12,14,15 - Reflection, mismatch, ideal reactances and matching.

**후속 계산:** [EQ-029](#EQ-029), [EQ-030](#EQ-030), [EQ-031](#EQ-031).

**산술 참고 벡터:** `{"f_Hz":1000000000.0,"L_H":1e-09,"C_F":1e-12}` -> `{"XL_ohm":6.283185307179586,"XC_ohm":-159.15494309189532}`.

<a id="EQ-029"></a>

### EQ-029 - Y 행렬의 부하 Schur complement

$$
\mathbf I_i=-Y_L\mathbf V_i,\quad\mathbf V_i=-(Y_{ii}+Y_L)^{-1}Y_{ie}\mathbf V_e,\quad Y_{\rm eff}=Y_{ee}-Y_{ei}(Y_{ii}+Y_L)^{-1}Y_{ie}
$$

**적용:** 모든 전류가 원래 DUT 안쪽을 향하는 Y partition이다. 부하 전류 방향 때문에 Ii=-YLVi이며 해당 선형계를 안정하게 풀어야 한다.

**한계, 예외:** floating node, 이상 open/short, 공진 singularity를 진단한다. 실제 내부 geometry 변경을 외부 load 변경으로 간주하지 않는다. 명시적 inverse 대신 factorization/solve를 쓴다.

**입력:** `Yblocks,YL` [S complex] - samefrequency/reference/node basis; `Ve` [V RMS] - externalvoltage.

**출력:** `Yeff` [S complex] - loadedexternalnetwork; `Vi` [V RMS] - internalvoltages.

**근사 등급, 단계:** `exact_linear_algebra_given_network` ,  R2. **구현/위임:** scikit-rf Circuit; scipy.linalg.solve forindependentreference.

**근거:** [SCIKIT_RF_CIRCUIT](https://scikit-rf.readthedocs.io/en/latest/tutorials/Circuit.html) - Arbitrary N-port circuit; unique Network/port connections; [SCIKIT_RF_VI](https://scikit-rf.readthedocs.io/en/latest/examples/circuit/Voltages%20and%20Currents%20in%20Circuits.html) - External/internal current direction; returned V/I peak values.

**후속 계산:** [EQ-030](#EQ-030), [EQ-032](#EQ-032).

**산술 참고 벡터:** `{"Yee_S":0.02,"Yei_S":-0.01,"Yie_S":-0.01,"Yii_S":0.02,"YL_S":0.01}` -> `{"Yeff_S":0.016666666666666666}`.

수학 표기의 역행렬은 구현 명령이 아니다. factorization/linear solve를 쓰고 조건수, 잔차, singularity를 기록한다.

<a id="EQ-030"></a>

### EQ-030 - S 행렬 내부 연결, 종단

$$
\mathbf a_i=C\mathbf b_i,\quad C_{\rm load,network}=\frac{Z_L-Z_0}{Z_L+Z_0^*},\quad\mathbf a_i=(I-CS_{ii})^{-1}CS_{ie}\mathbf a_e,\quad S_{\rm eff}=S_{ee}+S_{ei}(I-CS_{ii})^{-1}CS_{ie}
$$

**적용:** ai=Cbi의 C는 network 쪽 전류 방향과 V/I continuity에서 구성한다. scalar load는 C=(ZL-Z0)/(ZL+Z0*)이다. EQ-011의 load 쪽 Gamma와 다르다. 대안은 검증된 공통 real-positive Zref의 명시 renormalization 경로이다.

**한계, 예외:** 복소 Z0에서 load Gamma를 C로 복사하거나 단순 port swap으로 연결하지 않는다. V/I와 전류 방향을 검증한다. I-CSii의 conditioning이 나쁘면 pole, 잘못된 연결, 능동 발진 가능성을 진단하고 clamp하지 않는다.

**입력:** `S` [1 complex] - samewavebasisnetwork; `C` [1 complex] - internalconnection/terminationoperator; `ae` [sqrt(W)] - externalexcitation; `Z0,ZL and connection_current_direction` [ohm complex; orientation metadata] - 같은 network-side port에서 정의한 ReZ0>0 기준과 외부 종단. network 전류는 DUT 안쪽 양수이며 load에 전달될 때 I_into_network=-V/ZL이다..

**출력:** `Seff` [1 complex] - connectednetwork; `ai` [sqrt(W)] - internalincidentwaves.

**근사 등급, 단계:** `exact_scattering_interconnection` ,  R2. **구현/위임:** scikit-rf Circuit/connect; independentblock-solveoracle.

**근거:** [SCIKIT_RF_CIRCUIT](https://scikit-rf.readthedocs.io/en/latest/tutorials/Circuit.html) - Arbitrary N-port circuit; unique Network/port connections; [SCIKIT_RF_WAVES](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html) - Power/pseudo/traveling waves and complex reference impedance; [SCIKIT_RF_WAVES](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html) - Power/pseudo/traveling waves and complex reference impedance; [SCIKIT_RF_VI](https://scikit-rf.readthedocs.io/en/latest/examples/circuit/Voltages%20and%20Currents%20in%20Circuits.html) - External/internal current direction; returned V/I peak values.

**후속 계산:** [EQ-014](#EQ-014), [EQ-031](#EQ-031), [EQ-032](#EQ-032).

**산술 참고 벡터:** `{"See":0.1,"Sei":0.5,"Sie":0.5,"Sii":0.2,"C":0.3}` -> `{"Seff":0.1797872340425532}`.

수학 표기의 역행렬은 구현 명령이 아니다. factorization/linear solve를 쓰고 조건수, 잔차, singularity를 기록한다.

network 쪽 current가 안쪽 양수이면 외부 load 연결에서 I=-V/ZL이다. EQ-011 정의를 역으로 풀면 V=(conj(Z0)*a+Z0*b)/sqrt(Re(Z0)), I=(a-b)/sqrt(Re(Z0))이므로 ai/bi=(ZL-Z0)/(ZL+conj(Z0))가 된다. load 자체를 바라본 b/a=(ZL-conj(Z0))/(ZL+Z0)와 혼동하지 않는다. Z0=50+j25 ohm, ZL=50-j25 ohm이면 load Gamma=0이지만 C=.2-j.4이다. 일반 접속은 전압 연속/KCL로 C를 구성하거나 검증된 공통 실수 양수 Zref로 변환 후 연결하며 변환 chain을 보존한다.

여기의 C는 독립 전원이 없는 선형 종단/연결 연산자다. 내부 연결 위치에 별도 전원을 넣는다면 `a_i = C*b_i + d_i`의 source 항과 그 전력 기준이 필요하다. 기존 동차식의 C에 전원 진폭을 섞지 않는다. R1/R2 지원 profile이 해당 source 연결을 정의하지 않으면 명시적으로 미지원 처리한다.

<a id="EQ-031"></a>

### EQ-031 - cascade, fixture de-embedding

$$
T_{\rm total}=T_AT_{\rm DUT}T_B,\quad T_{\rm DUT}=T_A^{-1}T_{\rm total}T_B^{-1},\quad H_{\rm line}=e^{-\gamma l}
$$

**적용:** 확인된 두 fixture와 같은 mode, plane, Z0, 방향의 chain matrix를 사용한다. ABCD 전류 부호를 먼저 선언한다.

**한계, 예외:** S21이 약 0인 chain 변환은 불안정할 수 있다. port extension은 지정 propagation만 제거하고 알 수 없는 connector discontinuity를 제거하지 않는다. de-embedding은 VNA 교정 자체를 대신하지 않는다.

**입력:** `T` [structured complex2*2] - declaredABCD/chainwave convention; `gamma` [1/m complex] - knownpropagation; `l` [m] - line length.

**출력:** `S_DUT` [1 complex] - deembeddednetwork; `transform_log` [structured] - orderedoperations.

**근사 등급, 단계:** `exact_network_operation_given_fixture` ,  R1은 기본 네트워크 정의와 검증된 단순 변환, 고급 fixture de-embedding/calibration은 R2. **구현/위임:** 해당 단계에서 검증된 scikit-rf cascade/inv/calibration과 conditioning check. 최초 IFA의 R1 기본 비교는 동일 SMA 기준면을 사용한다.

**근거:** [SKRF_NETWORKS](https://scikit-rf.readthedocs.io/en/latest/tutorials/Networks.html) - Cascading and De-embedding; [SCIKIT_RF_CIRCUIT](https://scikit-rf.readthedocs.io/en/latest/tutorials/Circuit.html) - Arbitrary N-port circuit; unique Network/port connections; [TI_AN058_SWRA161](https://www.ti.com/lit/pdf/swra161) 물리 p.4,5,6,20,23,24,25,26 - section 3.1-3.4 initial lengths and wave conventions; calibration/matching/OTA.

**후속 계산:** [EQ-012](#EQ-012), [EQ-017](#EQ-017), [EQ-020](#EQ-020).

**산술 참고 벡터:** `{"TA":"identity","TB":"identity","Ttotal":[[1,50],[0,1]]}` -> `{"TDUT":[[1,50],[0,1]]}`.

수학 표기의 역행렬은 구현 명령이 아니다. factorization/linear solve를 쓰고 조건수, 잔차, singularity를 기록한다.

<a id="EQ-032"></a>

### EQ-032 - 부하와 여기별 far-field 합성

$$
\mathbf F_{\rm total}=\sum_na_n\mathbf F_n\ (A_{\rm basis}=I);\quad A_{\rm basis}\mathbf c=\mathbf a_{\rm req},\quad\mathbf F_{\rm total}=\sum_kc_k\mathbf F_{\rm raw,k},\quad P_{\rm rad}=\mathbf a^\dagger R_{\rm rad}\mathbf a
$$

**적용:** geometry/material/port EM 경계가 고정된 선형 모델이다. 단위 incident basis에는 실제 a를 사용한다. 일반 raw basis에는 원 EM plane/wave에서 A_basis c=a_req를 풀어 c로 field를 합성한다.

**한계, 예외:** full row rank, conditioning, residual과 port/excitation 순서를 검사한다. 패드, 급전선, 재료 변화는 raw EM을 무효화한다. S renormalization만으로 field basis가 변했다고 가정하지 않으며 matching loss도 수지에 포함한다.

**입력:** `Fn` [V/m per sqrt(W)] - unit-incident power-wave basis의 복소 embedded pattern. 실제 RMS field를 해당 unit wave amplitude로 정규화한 V/m/sqrt(W)이며 F_raw,k[V/m]와 구별한다. 같은 관측 반경, 좌표, 위상 기준을 사용한다.; `a` [sqrt(W)] - 검증된 unit-incident basis를 사용할 때의 원 EM port 입사 진폭. 일반 raw basis의 합성계수 c와 구별한다.; `externalnetwork` [structured] - matching/termination solution; `A_basis` [sqrt(W), complex [Nport,Nexc]] - 실제 원 EM plane/wave에서 기록된 각 excitation의 incident-wave 열; `a_req` [sqrt(W), complex [Nport]] - 원 EM plane/wave로 복원한 요청 입사파; `c` [1, complex [Nexc]] - rank/conditioning을 확인한 A_basis c=a_req 풀이의 합성계수; `F_raw,k` [V/m, complex RMS] - 각 실제 excitation에서 기록하고 RMS/channel convention을 검증한 복소 far field. 개념 shape [Nexc,Nf,Ntheta,Nphi,Npol=2]; HDF5 serialization [Nexc,Nf,Ntheta,Nphi,2,2]의 마지막 축은 re/im. A_basis의 동일 excitation 열, 원 EM plane/wave, phase/time origin, observation radius와 연결. incident-wave amplitude로 나누지 않은 field이며 dimensionless c로 합성한다..

**출력:** `Ftotal` [V/m RMS] - actualexcitationfield; `Prad` [W] - quadraticradiationpower.

**근사 등급, 단계:** `linear_superposition_with_fixed_EM_boundary` ,  R2. **구현/위임:** network library + solverembeddedbasis.

**근거:** [SCIKIT_RF_CIRCUIT](https://scikit-rf.readthedocs.io/en/latest/tutorials/Circuit.html) - Arbitrary N-port circuit; unique Network/port connections; [B-S48](https://onlinelibrary.wiley.com/doi/10.1155/2011/421691) - Dama et al. section 2-3, equations1-15; intrinsic-loss matrix; [OPENEMS_NF2FF](https://docs.openems.de/en/latest/concepts/nf2ff.html) - Surfaces; phase center; angle/radius/medium; Fourier recording.

**후속 계산:** [EQ-014](#EQ-014), [EQ-016](#EQ-016), [EQ-017](#EQ-017), [EQ-023](#EQ-023).

**산술 참고 벡터:** `{"F1":[1,0],"F2":[1,0],"a1":1,"a2":-1}` -> `{"Ftotal":[0,0]}`.

외부 정합망의 부품값만 변하고 그 pad/trace가 EM 영역 밖에 있는 경우 raw field basis를 재사용할 수 있다. 내부 전류와 실제 입사파를 다시 풀며 네트워크 정규화가 달라졌다면 basis transformation도 명시적으로 적용한다.

`A_basis=I`는 각 열이 해당 포트의 `1 sqrt(W)` 입사이고 나머지는 0인 정규화의 수치 표기다. raw field에 곱하는 c는 무차원이며, 단위 입사로 나눈 F_n에는 sqrt(W) 단위의 a를 곱한다. 모든 radiating drive가 선언한 포트 기저에 포함되어야 한다. `Nexc > Nport`이면 A의 null-space 성분이 field에도 수치오차 이내의 0을 만드는지 확인한다. 동일한 a_req의 서로 다른 계수 해가 다른 field를 만든다면 source/위상/기준면 불일치로 합성을 차단한다. 부족한 basis의 일반 합성은 차단하되 원래 계산한 excitation의 결과는 그 원 조건으로 보존한다.

<a id="EQ-033"></a>

### EQ-033 - 공분산을 포함한 불확도 전파

$$
C_y\approx JC_xJ^T,\quad J_{ij}=\partial f_i/\partial x_j,\quad u_i=\sqrt{(C_y)_{ii}},\quad U_i=k_{\rm coverage}u_i
$$

**적용:** 미분 가능하고 작은 불확실성에서 covariance를 포함하는 1차 전파식이다. coverage factor와 분포, 상관, coverage 가정을 기록한다.

**한계, 예외:** 큰 비선형, mode switch, 비정규분포는 Monte Carlo 등 다른 방법이 필요하다. 제조 공차, 측정 불확실성, 모델 불완전성을 임의 합성하지 않는다.

**입력:** `Cx` [mixed-unit covariance] - inputuncertainty/correlation; `J` [output/input units] - sensitivityJacobian; `kcoverage` [1] - coveragefactor withbasis.

**출력:** `Cy` [output^2 covariance] - linearizedoutputcovariance; `u,U` [outputunit] - standard/expandeduncertainty.

**근사 등급, 단계:** `first_order_uncertainty_propagation` ,  R2. **구현/위임:** numpy/scipy covariance; uncertaintybudget.

**근거:** [JCGM100_2008](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf) - section 5.1-5.2; Eq16 correlated uncertainty; section 7 reporting.

**후속 계산:** [EQ-034](#EQ-034), [EQ-036](#EQ-036).

**산술 참고 벡터:** `{"y":"x1+x2","u1":1,"u2":1,"corr":0.5}` -> `{"variance_y":3,"u_y":1.7320508075688772}`.

<a id="EQ-034"></a>

### EQ-034 - 민감도와 정규화

$$
\frac{\partial y}{\partial x_i}\approx\frac{y(x+h_ie_i)-y(x-h_ie_i)}{2h_i},\qquad S_i=\frac{x_i}{y}\frac{\partial y}{\partial x_i}
$$

**적용:** 같은 물리적 resonance branch와 안정한 solver 조건에서 perturbation h를 고른다. solver noise와 h 변화에 따른 미분 안정성을 검사한다.

**한계, 예외:** x 또는 y가 0일 때 정규화 민감도를 쓰지 않는다. 모드 전환의 불연속을 매끄러운 gradient로 보고하지 않는다. 제한경계에는 적절한 일방 미분 또는 다른 방법이 필요하다.

**입력:** `x,h` [parameterunits] - physicallyvalidperturbation; `y` [metricunits] - computedresponse.

**출력:** `J` [metric/parameter] - sensitivity; `Jnorm` [1] - optionalrelative derivative.

**근사 등급, 단계:** `numerical_derivative_approximation` ,  R2. **구현/위임:** scipy/explicit finite differences; adjoint delegatedwhenbackendverified.

**근거:** [JCGM100_2008](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf) - section 5.1-5.2; Eq16 correlated uncertainty; section 7 reporting.

**후속 계산:** [EQ-033](#EQ-033), [EQ-035](#EQ-035), [EQ-036](#EQ-036).

**산술 참고 벡터:** `{"function":"x^2","x":3,"h":0.01}` -> `{"central_difference":6,"normalized_sensitivity":2}`.

<a id="EQ-035"></a>

### EQ-035 - 제약, 성능 mask, Pareto

$$
g_j(x)\le0,\quad V(x)=\sum_jw_j\max(0,g_j/s_j)^p,\quad x\prec y\iff[\forall k:F_k(x)\le F_k(y)]\land[\exists k:F_k(x)<F_k(y)]
$$

**적용:** 목표 방향, 정규화 scale, 가중치, 제약, 대역/환경 mask를 사전 선언한다. Pareto 우월성은 모든 목적과 적어도 하나의 엄격한 개선으로 판정한다.

**한계, 예외:** 가중점수는 설계 정책이며 물리 법칙이 아니다. 계산하지 않은 대역을 자동 pass시키지 않는다. 보간, surrogate 예상점을 실제 검증된 지점으로 처리하지 않는다.

**입력:** `Fk` [declarednormalized metrics] - minimizationobjective vector; `gj,sj` [sameconstraintunits] - constraintandscale; `wj,p` [1] - explicitpolicy. 정규화와 penalty의 정의역은 s_j>0, w_j>=0, p>0이며 유한값을 요구한다.

**출력:** `feasible` [bool] - geometry/material/numericandgoalconstraints; `Pareto_set` [candidateids] - nondominatedvalidcandidates.

**근사 등급, 단계:** `design_policy_and_optimization_definition` ,  R2. **구현/위임:** optimizer library selectedatR0/R2; robustdomainconstraints.

**근거:** [DEB_NSGA2_2002](https://doi.org/10.1109/4235.996017) 물리 p.3,11 - section III nondominated sorting; section V.A constrained-domination, printed pp184/192; reviewed paper copy https://web.njit.edu/~horacio/Math451H/download/2002-6-2-DEB-NSGA-II.pdf.

**후속 계산:** [EQ-034](#EQ-034), [EQ-036](#EQ-036), [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"F_A":[1,2],"F_B":[2,3],"F_C":[0.5,4]}` -> `{"A_dominates_B":true,"A_dominates_C":false}`.

<a id="EQ-036"></a>

### EQ-036 - Monte Carlo 수율, 신뢰구간

$$
\hat p=k/N,\quad CI_W=\frac{\hat p+z^2/(2N)\ \pm\ z\sqrt{\hat p(1-\hat p)/N+z^2/(4N^2)}}{1+z^2/N}
$$

**적용:** Wilson 구간은 IID Bernoulli outcomes에 적용한다. 각 독립 sample 내부의 물리 변수는 joint distribution으로 상관되어 있어도 된다.

**한계, 예외:** LHS/quasi-MC/importance/adaptive sampling에는 그대로 Wilson을 적용하지 않는다. solver 실패를 분모에서 삭제하지 않는다. all-pass도 생산 수율100%의 보증이 아니다.

**입력:** `N,k` [integer] - 사전에 정한 전체 IID Bernoulli 표본 수와 pass 수. 모든 N개의 결과가 판정 가능해야 하며 실패 계산을 제외한 수를 N으로 다시 정의하지 않는다.; `joint_distribution` [structured] - parameterdistributionsandcorrelations; `z` [1] - selectednormalquantile.

**출력:** `p_hat` [1] - estimatedyield; `CI` [1 interval] - specifiedconfidence method.

**근사 등급, 단계:** `statistical_estimation_with_sampling_assumptions` ,  R2. **구현/위임:** scipy.stats appropriateCI; sampler seed/versionrecorded.

**근거:** [NIST_BINOMIAL_CI](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/propconf.htm) - Wilson interval for binomial proportion; [SCIPY_BINOMIAL_CI](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html) - proportion_ci; exact and Wilson alternatives.

**후속 계산:** [EQ-035](#EQ-035).

**산술 참고 벡터:** `{"N":100,"k":90,"confidence":0.95,"z":1.959963984540054}` -> `{"p_hat":0.9,"wilson_lower":0.8256343384950865,"wilson_upper":0.9447708629393249}`.

<a id="EQ-037"></a>

### EQ-037 - 메시, 경계, 종료 수렴 지표

$$
e_S=\max|S_f-S_c|,\quad e_f=|f_{r,f}-f_{r,c}|/|f_{r,f}|,\quad e_\eta=\max|\eta_f-\eta_c|,\quad e_G=\max|G_{f,\rm dB}-G_{c,\rm dB}|
$$

**적용:** 동일 physical revision, frequency, port, normalization, scenario와 추적 가능한 공진 branch에서 비교한다. 메시, 경계, 시간종료 변화는 별도 series로 검사한다.

**한계, 예외:** 두 coarse run이 비슷하다고 물리 정확성을 보장하지 않는다. 공진 소실/교체는 indeterminate이며 0 변화가 아니다. 보간 grid 차이와 angular sampling 오차를 구별한다.

**입력:** `runs` [immutable resultrefs] - onecontrolledmeshorboundary/timevariation; `thresholdprofile` [structured] - proposed/project/source scoped.

**출력:** `errors` [named metric units] - comparisonvector; `convergence_state` [enum] - pass/fail/indeterminate.

**근사 등급, 단계:** `numerical_validation_policy` ,  R1. **구현/위임:** domainconvergence service plusactualsolverruns.

**근거:** [OPENEMS_MESH](https://docs.openems.de/en/latest/concepts/mesh.html) - CFL; mesh grading; actual algorithm configuration; [OPENEMS_NF2FF](https://docs.openems.de/en/latest/concepts/nf2ff.html) - Surfaces; phase center; angle/radius/medium; Fourier recording.

**후속 계산:** [EQ-035](#EQ-035).

**산술 참고 벡터:** `{"Sfine_re_im":[0.1,0.2],"Scoarse_re_im":[0.11,0.18],"fres_fine_Hz":1000000000.0,"fres_coarse_Hz":990000000.0}` -> `{"eS":0.022360679774997897,"ef":0.01}`.

eG는 profile에 `peak_gain_over_declared_sphere`, `gain_at_declared_angles`, `linear_complex_field_norm` 중 무엇인지 명시한다. 동일 frequency/angle/polarization domain과 사전 null mask/coverage를 저장한다. 정확한 null의 -inf 차이를 epsilon으로 숨기지 않는다. peak 비교에도 별도 각도 refinement가 필요하다. 공진 branch 부재/교체는 indeterminate다. (PHYS-005)

<a id="EQ-038"></a>

### EQ-038 - 일반 CFL와 solver 실제 시간 간격

$$
\Delta t_{\rm CFL}\le\left[v_{\max}\sqrt{\Delta x^{-2}+\Delta y^{-2}+\Delta z^{-2}}\right]^{-1}
$$

**적용:** 명시적 표준 Cartesian Yee의 균일 격자식은 참고용이다. 실제 time step은 고정 버전 solver의 검증된 algorithm, mesh, material 조건으로 선택한다.

**한계, 예외:** nonuniform/cylindrical/분산/ADE/PML/수정 scheme의 추가 제약을 무시하지 않는다. 역사적 MODEL-016 OCR식은 실행용으로 차용하지 않는다.

**입력:** `Deltax,Deltay,Deltaz` [m] - uniformcell dimensionsforreference; `vmax` [m/s] - supportedmaximumwavespeed assumption.

**출력:** `Deltat_bound` [s] - referenceconditionalbound; `Deltat_actual` [s] - solverreportedstep.

**근사 등급, 단계:** `conditional_stability_reference_not_backend_policy` ,  R1. **구현/위임:** openEMSnative timestep selection; report algorithm actualvalue.

**근거:** [OPENEMS_MESH](https://docs.openems.de/en/latest/concepts/mesh.html) - CFL; mesh grading; actual algorithm configuration.

**후속 계산:** [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"dx_m":0.001,"dy_m":0.001,"dz_m":0.001,"vmax_m_per_s":299792458.0}` -> `{"cartesian_CFL_s":1.9258332015464706e-12}`.

<a id="EQ-039"></a>

### EQ-039 - CAD 왕복 형상 오차

$$
d_H(A,B)=\max\{\sup_{a\in A}\inf_{b\in B}\|a-b\|,\sup_{b\in B}\inf_{a\in A}\|b-a\|\},\quad\Delta A=\operatorname{area}(A\triangle B),\quad\Delta V=\operatorname{vol}(A\triangle B)
$$

**적용:** 정확 B-rep 또는 error bound가 있는 tessellation의 geometry 차이와 전기 connectivity를 따로 검사한다. tauCAD, tau2D, taufab는 서로 다른 의미이다.

**한계, 예외:** 샘플 기반 Hausdorff는 증명된 bound가 없으면 추정값이다. 작은 gap/net short는 전체 volume 오차가 작아도 실패이다. G031 좌표 해상도 .00254 mm에서 원 제조 정밀도 .001 mm를 주장하지 않는다.

**입력:** `A,B` [m geometry] - source/exportvalidentities; `tauCAD,tau2D,taufab` [m] - distincttolerances.

**출력:** `dH,layer_error` [m] - geometrydifference; `DeltaA,DeltaV` [m^2;m^3] - symmetricdifference; `connectivity_equal` [bool] - net/topologycheck.

**근사 등급, 단계:** `geometry_metric_and_validation_policy` ,  R1. **구현/위임:** OCCT/CAD geometry validation; independentreadercomparison.

**근거:** [NORDIC_PCA20006_CAD](https://devzone.nordicsemi.com/cfs-file/__key/support-attachments/beef5d1b77644c448dabff31668f3a47-1f949ef4dfa645c8b62851b8ead3970f/nRF51822-Bluetooth-Smart-Beacon-kit-hardware-files.zip) - G031 archive GTL lines 705-708; GM1 lines129-131; member hashes in G031.

**후속 계산:** [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"zlayers_m":[3.5e-05,0.00153,3.5e-05]}` -> `{"total_thickness_m":0.0016}`.

<a id="EQ-040"></a>

### EQ-040 - 유효면적, 조건부 Friis link

$$
A_e=\lambda_0^2G/(4\pi),\qquad P_r=P_tG_tG_r\left(\frac{\lambda_0}{4\pi r}\right)^2L_{\rm pol}L_{\rm other}
$$

**적용:** far-field free-space LOS에서 같은 전력 기준, gain, 편파를 가진 조건부 link budget이다. realized gain을 쓰면 mismatch factor를 중복 적용하지 않는다.

**한계, 예외:** NFC near-field, 실내 multipath, 사람, receiver sensitivity 변화를 포함한 실제 거리 보증식이 아니다. 인증, EIRP 한도는 별도 프로젝트 근거가 필요하다.

**입력:** `Pt` [W] - transmitpoweratstatedplane; `Gt,Gr` [1] - gainnotdBiandmatchingdefinitionsconsistent; `r,lambda0` [m] - free-spaceseparation/wavelength; `Lpol,Lother` [1] - explicit<=1factors.

**출력:** `Ae` [m^2] - matchedreceivingeffectivearea; `Pr` [W] - conditionalreceivedpower.

**근사 등급, 단계:** `scoped_link_budget_approximation` ,  R3. **구현/위임:** domainoptional linkbudget; notEMsolver.

**근거:** [RS_8GE01_ANTENNA_BASICS](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/premiumdownloads/premium_dl_brochures_and_datasheets/premium_dl_whitepaper/Antenna_Basics_8GE01_1e.pdf) 물리 p.7,13,14 - Far-field, directivity/gain, effective area; [PAPER-043](https://art.torvergata.it/bitstream/2108/31667/44089/AP-Magaz_tag_Tutorial_2008.pdf) 물리 p.2 - Power-transfer coefficient and complex power-dependent chip impedance.

**후속 계산:** [EQ-027](#EQ-027).

**산술 참고 벡터:** `{"lambda0_m":0.1,"G":1}` -> `{"Ae_m2":0.0007957747154594768}`.

<a id="EQ-041"></a>

### EQ-041 - 직사각형 TM10 patch 초기 치수

$$
\begin{aligned}W_s&=\frac{c_0}{2f_0}\sqrt{\frac2{\epsilon_r+1}},\\\epsilon_{e,p}&=\frac{\epsilon_r+1}{2}+\frac{\epsilon_r-1}{2\sqrt{1+12h/W_s}},\\\Delta L&=0.412h\frac{(\epsilon_{e,p}+0.3)(W_s/h+0.264)}{(\epsilon_{e,p}-0.258)(W_s/h+0.8)},\\L_s&=\frac{c_0}{2f_0\sqrt{\epsilon_{e,p}}}-2\Delta L.\end{aligned}
$$

**적용:** dominant TM10 rectangular patch의 얇은 균일 등방성 단층 기판, 연속 ground, thin metal 초기 모델이다. f0>0,h>0,epsilon_r>=1,Lseed>0이며 검증된 geometry envelope를 별도로 적용한다.

**한계, 예외:** feed 위치, inset, 50 ohm 정합, CP 축비, 대역폭, 효율을 산출하지 않는다. 원형, 슬롯, stacked, notched patch로 일반화하지 않는다. epsilon_eff,patch는 EQ-005와 별도 모델이다.

**입력:** `f0` [Hz] - 목표 중심 주파수; `epsilon_r` [1] - 지정 f에서 실수 등방성 균일 기판 유전율; `h` [m] - patch와 연속 ground 사이 균일 dielectric 높이.

**출력:** `Wseed,Lseed,DeltaL` [m] - 직사각형 초기 폭, 길이와 가장자리 연장 근사; `epsilon_eff,patch` [1] - 이 초기 모델의 유효 유전율; `evidence_state` [enum] - estimated_seed.

**근사 등급, 단계:** `scoped_transmission_line_initial_synthesis` ,  R1. **구현/위임:** domain seed calculation; 실제 공진/임피던스/패턴은 full-wave solver에 위임.

**근거:** [MATHWORKS_PATCH_SEED](https://www.mathworks.com/help/antenna/ug/impedance-analysis-of-2-by-2-patch-array.html) - Calculate Patch Dimensions; equations W, epsilonEff, deltaL, L (lines37-45 in retrieved page); [PAPER-071](https://doi.org/10.1109/MWSYM.1980.1124303) 물리 p.1 - Single microstrip, equations (1)-(5); printed p407.

**후속 계산:** [EQ-005](#EQ-005), [EQ-017](#EQ-017), [EQ-035](#EQ-035), [EQ-037](#EQ-037).

**산술 참고 벡터:** `{"f0_Hz":2400000000.0,"epsilon_r":4.3,"h_m":0.0016}` -> `{"W_m":0.03836688396105154,"epsilon_eff":3.997025593581728,"delta_L_m":0.0007411897490142516,"L_m":0.029757618760100718,"status":"estimated_seed"}`.

공식 MathWorks 예제는 초기 식 이후 square/모서리 절단 배열을 별도로 구성한다. 여기서는 rectangle의 W와 L을 각각 보존한다. 그 예제의 feed 위치나 corner trim 비율을 범용 합성값으로 복사하지 않는다.

## 5. 원문과 추출식의 교정, 차용 제한

| 근거 | 검토 결과 | 실행 계약 |
|---|---|---|
| G031 Nordic CAD | 일부 원호, 급전, 몸체 외곽만 복원되었고 전체 ground, stackup, 제품 환경이 완비되지 않았다. 좌표 양자화는 0.00254 mm이다. | 기하 재현 등급. [GAP-006](01_RFAD_설계_결정과_범위.md#GAP-006) 해소 전 성능 golden antenna로 사용하지 않는다. |
| TI AN058 SWRA161B 물리 p5 | c[m/s]와 f(GHz)의 인쇄 표기가 차원상 맞지 않는다. | EQ-003에서 f[Hz] 고정. 표기 자체를 실행식으로 전사하지 않는다. |
| TI AN058 물리 p6 | 전압 반사계수 식과 복소 공액 전력정합 설명을 구분해야 한다. | EQ-010/011/012의 explicit wave convention을 적용한다. |
| B-S03 MathWorks field 문면 | E를 실제 V/m로 취급할 때 radiation intensity는 r^2*Poynting이다. 검토 문면의 단일 R 인자를 그대로 채택하지 않는다. | EQ-016은 단위와 Poynting으로 검증. native r-normalized E면 별도 변환한다. |
| MODEL-016 역사적 Yee 추출식 | 추출식이 실행 가능한 검증 식으로 확정되지 않았다. | 비활성화 유지. EQ-038의 조건부 참고식과 native solver time-step을 구별한다. |
| B-S40 AddConductingSheet URL | 별도 URL에서 404가 확인되었다. | [공식 통합 materials 문서](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/materials.html)의 해당 API, 2D primitive 조건을 참조한다. |
| 분산 material 문서 | backend의 sign, pole parameter, Python과 Octave helper 노출이 다를 수 있다. | 적합 모델과 native 곡선의 수치 비교 전 capability를 승인하지 않는다. |
| 손실 포함 ECC | S와 효율 대각정보만으로 일반 loss cross-matrix가 정해지지 않는다. | 복소 field 우선. S-only shortcut의 범위를 명시한다. |

여기서 교정은 원본 파일을 수정한다는 뜻이 아니다. 원문, 추출값, 선택한 수식, 교정 근거를 병렬 보존한다. 출처 locator와 URL은 본문 및 [출처와 근거](18_RFAD_출처와_근거.md)를 따른다. 과거 physics_source_updates.json은 현재 제공되지 않아 원문 검토 완료 근거로 사용하지 않는다.

## 6. 남은 검증 gate

채널 정규화 GAP-003, 도체/분산/거칠기 GAP-004, G031 환경 GAP-006, 실측 기준 GAP-009, 잠정 threshold GAP-012, CPW/stripline/differential/complex-Z0 GAP-013, UWB timing GAP-014, lossy MIMO/loaded fields GAP-015를 남긴다. 이들은 해당 계산 기능을 출시할 때의 검증 gate이며, 자료 저장, 형상 편집 기능 자체를 모두 금지하는 항목은 아니다. 정확한 폐쇄 증거는 [VT 명세](14_RFAD_검증과_수용_기준.md)에 정의한다.

### Pulse spectrum과 정규화 설계 (PHYS-001)

2026-11-07 문서 검토 시 공개된 [openEMS DFT_time2freq 소스](https://github.com/thliebig/openEMS/blob/master/python/openEMS/utilities.py)의 pulse 경로는 sample 간격을 곱하고 periodic 경로는 표본 수로 나눈 뒤 단측 계수를 적용한다. 아래 수식은 그 정의에서 차원 분석으로 유도한 계약이다. 현재 설치본을 고정하거나 실행한 결과가 아니며 개발 시 선택한 tag/commit과 채널별 경로를 다시 확인해야 한다. pulse raw U [V*s], I [A*s], 같은 Fourier scale의 E [V*s/m], H [A*s/m]에 대해 `0.5*Re(U*conj(I))`는 W*s^2이다. 이 값을 단순히 sqrt(2)로 나누어 V RMS/W로 기록하면 안 된다.

단일 실수 양수 R0, 동일 DFT/위상 원점 및 유효 입사 spectrum q=Uinc에서 prescribed incident power Pset과 위상 0의 phasor는 다음과 같다.

```text
V_rms = (Utot / q) * sqrt(R0 * Pset)
I_rms = (Itot / q) * sqrt(R0 * Pset)
E_rms = (Eraw / q) * sqrt(R0 * Pset)  # 같은 native field scale 검증 후에만
P_W = P_native * 2 * R0 * Pset / abs(q)^2
S11 = Uref / Uinc  # RMS 변환을 적용하지 않음
```

q의 phase를 제거한 incident 기준이라는 사실, Pset, spectrum mask와 변환 근거를 저장한다. q의 최소 진폭/SNR 기준은 profile에서 정하고 작은 q 또는 미검증 채널의 absolute metric을 차단한다. P_native는 같은 quadratic Fourier scaling을 가진 채널일 때만 위 power 식에 넣는다. solver가 이미 정규화한 Prad나 서로 다른 dump scaling에는 이 계수를 다시 적용하지 않는다. 개발 승인 후 source amplitude 1x/2x의 raw 선형/전력 제곱 scaling, 정규화 불변성, known port 방향/전력 및 field 적분을 따로 검증한다. 산술 helper 시험이나 TE10 fixture 하나로 모든 lumped/NF2FF 조합을 승인하지 않는다. 현재 실행 증거는 미확보이며 [문서 검토와 승인](25_RFAD_문서_검토와_승인.md)의 개발 전 미결 항목으로 남긴다.
