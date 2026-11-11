# 재료 손실 모델과 제조사 물성의 구분

갱신일: 2026-11-11 KST. 승인 기준선 RFAD-D0-3.4를 유지한다. 이 문서는 재료 출처, 해석에서 소비하는 손실 표현, 사용자가 허용한 근사와 검증 범위를 구분한다. JLCPCB 납품 기판의 물성이 모두 측정되었거나 제조 검증을 통과했다는 문서가 아니다.

## 원본 물성과 해석 모델

제조사의 관측값에는 시험 주파수, 방법, 방향, 온도와 재료 구분이 붙는다. 프로젝트의 `validity_hz`는 사용자가 그 해석 모델을 적용하기로 한 대역이다. 시험 주파수 한 점을 모델 유효 대역으로 자동 확장하거나, 근사 적용 대역을 제조사가 보증한 대역으로 기록하지 않는다.

원본 카탈로그의 미정값은 미정으로 보존한다. 사용자가 승인한 근사는 별도 모델의 이름, `source_refs`, `assumptions`와 적용 대역으로 기록한다. 승인된 근사로 계산에 필요한 값을 정하더라도 원본 카탈로그의 JLCPCB 실제 물성이나 제조사 확정값으로 승격하지 않는다. 원본 선택과 프로젝트 적용값의 추적은 [PCB 선택 계약](pcb_selection_contract.md)을 따른다.

`tan_delta` 또는 Df는 시험에서 얻은 손실 표현이다. 원본이 이를 별도의 DC 전도도와 독립인 분극 손실로 분리했다고 설명하지 않으면, 두 값을 자동 합산하는 근거가 없다. 특히 체적 저항률에서 환산한 DC 전도도는 조건이 다른 관측값이며, RF Df와 독립인 추가 손실 성분이라고 간주하지 않는다.

## 명시적인 두 유전체 모델

모델 이름과 목적별 필수 입력은 [material_models.py](../src/rfad/domain/material_models.py), solver 투영은 [pcb_projection.py](../src/rfad/application/pcb_projection.py)에서 정의한다.

| 모델 | 유전체에서 소비하는 값 | 상수 손실 전도도 계산 | 사용 조건 |
| --- | --- | --- | --- |
| `isotropic_constant` | `epsilon_r`, `tan_delta`, `conductivity` | `kappa = conductivity + 2*pi*f_ref*epsilon0*epsilon_r*tan_delta` | 기존 합산 의미를 유지한다. 전도도와 Df를 독립 손실 성분으로 사용하는 모델이라는 명시적 근거가 필요하다. |
| `isotropic_constant_total_tan_delta` | `epsilon_r`, `tan_delta` | `kappa = 2*pi*f_ref*epsilon0*epsilon_r*tan_delta` | 입력 Df를 해당 모델의 전체 전기적 유전체 손실 표현으로 선택한다. 별도 전도도는 소비하지 않는다. |

기존 프로젝트의 `isotropic_constant`를 읽으면서 새 모델로 자동 변경하지 않는다. 저장된 의미와 기존 합산 경로를 유지한다. 새 모델은 명시적으로 선택하며, 알 수 없는 모델 이름도 기존 모델로 대체하지 않는다.

새 모델에서 원본 `conductivity`가 미정이어도 유전체 계획을 만들 수 있다. 이것은 전도도가 실제 0 S/m라는 선언이 아니다. 알려진 값이 있더라도 별도 항으로 더하지 않고 `unconsumed_properties`에 남긴다. 소비 보고서에는 `consumed_properties`, `unconsumed_properties`, `loss_partition`을 기록해 두 모델의 의미를 구분한다.

도체는 이 유전체 전용 모델을 사용할 수 없다. 외측 conducting sheet에는 유한 전도도와 두께가 필요하고, 체적 PTH 도체에는 전도도와 상대 유전율이 필요하다. 유전체의 미사용 전도도를 허용한다고 구리의 필요한 전도도를 생략하거나 PEC로 바꾸지 않는다.

## openEMS 변환과 대역 제한

현재 투영의 `f_ref`는 평가 대역의 산술 중심인 `(start_hz + stop_hz) / 2`이다. 출처 Df의 시험 주파수와 별개의 값이다. 두 주파수가 다르면 Df를 모델 중심에 적용한 근사 사실을 보존해야 한다.

openEMS의 상수 `Kappa`는 전기적 손실 전도도이며, 공식 재료 설명에서 복소 유전율의 손실항은 `kappa / (2*pi*f)`로 표현된다. 공식 CRLH 예제도 Df와 기준 주파수로부터 `Kappa`를 계산한다. 따라서 Df에서 등가 전도도를 만드는 경로 자체에 별도의 미정 DC 전도도를 0으로 채울 필요는 없다. [openEMS 재료 설명](https://wiki.openems.de/index.php/Material_Property.html), [공식 CRLH 예제](https://docs.openems.de/en/latest/octave/Tutorials/CRLH_LeakyWaveAnt.html)

상수 `epsilon_r`와 상수 `kappa`를 사용하면 모델이 나타내는 유전체 손실 탄젠트는 다음과 같다.

```text
tan_delta_model(f) = kappa / (2*pi*f*epsilon0*epsilon_r)

total-tan-delta model:
tan_delta_model(f) = tan_delta_input * f_ref / f
```

즉 입력 Df와 일치하는 곳은 `f_ref`이며, 대역 전체에서 Df가 일정한 광대역 모델은 아니다. 투영에는 `loss_reference_frequency_hz`와 새 모델의 `loss_approximation`을 기록한다. 평가 대역을 바꾸면 환산 `kappa`도 바뀔 수 있으므로 서로 다른 대역의 결과를 동일한 재료 전달함수의 결과로 바로 비교하지 않는다. 광대역 정확도가 필요하면 다중 주파수 관측과 적합한 분산 모델을 별도로 검증해야 한다. [openEMS 분산 모델](https://docs.openems.de/en/latest/concepts/dispersive.html)

## RO4350B의 이번 근사 선택

사용자는 2026-11-11에 제조사 출처와 근사임을 구분하는 초기 검증 모델을 허용했다. 선택 근거가 되는 Rogers 공식 표는 다음과 같다. 자료의 숫자는 재료군의 조건부 특성이며 특정 JLCPCB 납품 로트의 측정값이 아니다. [Rogers RO4000 데이터시트, 물성 표](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf)

| 출처 항목 | 출처 조건 | 이번 모델에서의 의미 |
| --- | --- | --- |
| RO4350B Process Dk 3.48 +/- 0.05 | 10 GHz, 23 C, Z 방향, IPC-TM-650 2.5.5.5 | 공정 시험값으로 보존한다. 이번 Design Dk 선택과 혼합하지 않는다. |
| RO4350B Design Dk 3.66 | 8~40 GHz, Differential Phase Length Method | 초기 회로 해석용 상수 `epsilon_r`의 출발값으로 명시적으로 선택한다. 2.4 GHz 직접 측정값은 아니다. |
| RO4350B Df 0.0031 | 2.5 GHz, 23 C, Z 방향, IPC-TM-650 2.5.5.5 | 전체 손실 Df 모델의 입력으로 선택하고 2.400~2.4835 GHz에 좁은 대역 근사로 적용한다. |
| RO4350B Df 0.0037 | 10 GHz, 23 C, 같은 시험 계열 | 별도 출처 관측으로 보존한다. 근거 없는 2.4 GHz 보간식 생성에 사용하지 않는다. |
| RO4350B 체적 저항률 1.2e10 MOhm*cm | COND A, IPC-TM-650 2.5.17.1 | DC 관측이다. 새 전체 Df 모델의 별도 RF 손실항으로 더하지 않는다. |
| 표준 ED 동박 18 um 또는 35 um | 반 온스 또는 1 온스 cladding | 원재료 선택 정보이다. JLCPCB 완성 외층 두께와 전도도가 모두 확정된다는 뜻은 아니다. |

체적 저항률의 단순 단위 환산은 `1.2e14 ohm*m`, 역수는 약 `8.333333e-15 S/m`이다. 이 계산은 DC 시험 조건의 표현 변환일 뿐이며, 이를 RF 전체 Df와 더해야 한다는 결론을 주지 않는다.

이번 Design Dk 3.66의 2.4 GHz 적용은 출처 범위 8~40 GHz 밖의 사용이다. Df 0.0031도 2.5 GHz 관측을 다른 중심 주파수에 적용한다. 두 수치를 동일 주파수에서 측정한 한 쌍이라고 표기하지 않는다. 선택한 2.400~2.4835 GHz 대역은 초기 검증용 모델 적용 범위이며, 제조사가 보증한 해당 대역의 실측 정확도나 오차 상한이 아니다. 스칼라 등방성 표현도 이 재료의 방향별 특성이 같다는 증명이 아니다.

이 선택은 통합 실행과 후속 민감도 검토를 위한 출발점이다. 실제 제작 성능을 예측한다고 주장하려면 동일 적층/두께/동박/가공 조건에서의 재료 또는 시험 쿠폰 측정과 비교해야 한다. 다른 RO4000 재료, 4 mil 특수 조건, LoPro cladding의 값을 이 모델로 자동 대체하지 않는다.

## 별도의 IACS 기준 구리 모델

이번 유한 전도도 입력은 별도 이름인 `IACS reference copper model, 20 C`로 기록한다. 선택값은 `58000000 S/m`이고, 의미는 표준 소둔 구리의 기준 전도도다. NIST가 제공하는 Bureau of Standards Circular 31의 국제 정의는 20 C, 길이 1 m, 단면적 1 mm^2의 표준 소둔 구리 저항을 `1/58 ohm`으로 정한다. `rho = R*A/L`을 적용하면 `sigma = 58e6 S/m`가 된다. NPL도 `58.0 MS/m = 100.0 %IACS`를 명시한다. [NIST Circular 31, PDF 18쪽 / 인쇄 14쪽](https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e2.pdf), [NPL 전도도 표준](https://www.npl.co.uk/products-services/magnetics/ac-and-dc-conductivity)

이 값은 JLCPCB가 제공한 실제 동박 또는 도금층의 전도도가 아니다. 원본 JLCPCB의 미정 전도도를 덮어쓰지 않는다. 이번 모델은 균일한 전도도와 평활한 구리를 선택한 근사이며, 실제 foil 등급, 열 이력, 도금, 표면 처리 및 거칠기까지 보증하지 않는다. Rogers 공식 계산 도구도 표준 전도도 또는 사용자 전도도를 선택하고 거칠기를 별도로 입력하는 구조를 설명한다. [Rogers MWI 모델 설명](https://www.rogerscorp.com/blog/2018/calculate-microwave-impedance-with-transmission-line-modeling-tool)

참고로 실제 foil 제조사 JX는 압연 구리 제품별 대표 전도도를 98~101 %IACS로 구분하며 보증값이 아니라고 명시한다. 이 자료는 foil 종류별 차이가 존재한다는 근거이며, Rogers 표준 ED 동박이나 JLCPCB 납품 전도도를 대신하는 자료로 쓰지 않는다. 이번에 확인한 Rogers 표준 ED cladding 정보에서 특정 JLCPCB 납품 전도도를 확정할 수 있는 수치는 확인하지 못했다. [JX 압연 동박 대표 특성](https://www.jx-nmm.com/products/copper_foil_and_alloy/rolled_copper_foil/)

## 생략 항목과 결과의 사용 범위

이번 초기 모델에는 다음 제한을 입력 가정 및 결과 설명과 함께 남긴다.

- ENIG: 제작 조건에 ENIG가 있더라도 현재 전기 모델은 구리와 니켈/금의 다층 표면 구조를 직접 표현하지 않는다. Rogers의 RO4350B 전송선 비교에서는 ENIG의 추가 손실과 공정/니켈 두께 의존성이 확인된다. 해당 그래프의 특정 주파수 손실 차이를 이 2.4 GHz 안테나의 오차 수치로 가져오지 않는다. [Rogers 회로 재료와 고주파 손실, PDF 5쪽](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/articles/english/advanced-connectivity-solutions/circuit-materials-and-high-frequency-losses-of-pcbs.pdf)
- 솔더 마스크: 생략 모델은 전기적으로 마스크가 없는 구조를 계산한다. 실제 RF 영역에 마스크가 있으면 유효 Dk와 손실이 달라질 수 있다. 최종 제작에서는 RF 영역 개구 조건을 확인하거나 실제 잉크/두께/물성 모델을 추가해야 한다. Rogers가 예로 든 일반 마스크 상수를 JLCPCB 마스크 값으로 채우지 않는다. [Rogers 솔더 마스크 영향](https://www.rogerscorp.com/blog/2020/finding-the-right-solder-mask-for-rfmicrowave-pcbs)
- 동박 거칠기: 현재 평활 도체 근사는 거칠기로 인한 손실과 위상 변화를 교정하지 않는다. 다른 foil이나 LoPro의 거칠기 수치를 이번 납품 조건으로 전용하지 않는다.
- 급전과 조립: 이상적 단일 lumped gap의 기준면과 실제 SMA, 납땜, 케이블, 조립체의 기준면은 구분한다. 해당 부품과 디임베딩을 검증하기 전에는 측정 S11과 같은 조건이라고 주장하지 않는다.

생략 영향은 이득/효율뿐 아니라 입력 임피던스와 S11에도 영향을 줄 수 있으므로, 한 방향으로 보수적이거나 오차가 정해졌다고 가정하지 않는다. 현재 PCB profile은 NF2FF, 이득과 효율을 제공하지 않는다. 지원되지 않는 지표를 이 근사 계산으로 보완한 것처럼 게시하지 않는다.

계산 결과의 `status=computed_unvalidated`, `physics_validated=false`와 계획의 `physical_validation_state=not_validated`를 유지한다. 제조 및 실측 검증도 미완료다. 시간영역 에너지 종료, 파일 재열기, CAD/STEP 성공은 각각 실행/통합 경로의 확인이며 재료 모델 정확도나 제조 일치의 증명이 아니다. 격자와 경계 거리 비교도 사용한 재료 모델 안의 수치 안정성으로 한정한다. 실제 결과와 검증 범위는 [PCB solver 계약](pcb_solver_contract.md), [카탈로그 통합 검증](catalog_pcb_integration.md) 및 각 실행 보고서를 따른다.

## 구현 검증에서 확인할 계약

새 손실 모델의 시험은 미정 전도도 보존, 미소비 값의 누락 허용, 기존 합산 의미 유지, 유전체 전용 사용 제한, 유효 대역 검사와 중심 주파수 환산을 확인한다. native 소비 보고서와 봉인 결과에도 선택한 모델/가정이 추적되어야 한다. 이 문서는 특정 시험 실행의 통과 기록을 대신하지 않으며 실행 결과는 [개발 상태](development_status.md)에 별도로 기록한다.

출처 PDF 검토 사본 `Code/.local/manufacturing-source-review/Rogers_RO4000.pdf`의 SHA-256은 `51b920d81356884d6924e608ead6f8555ce1bd2ac635ebd255102d040e6afd0d`이다. 표와 주석을 시각적으로 확인했으며, 이 로컬 사본 경로를 제품의 영구 출처 식별자로 사용하지 않는다. 위 제조사 URL과 기록한 출처 식별 정보를 함께 보존한다.
