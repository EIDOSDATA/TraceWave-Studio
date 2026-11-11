# RF 원자재 조사 결과 - Rogers / AGC / Arlon

수집 단계의 상세 기술 메모를 보존한 문서다. 아래 수량과 자체 검사는 당시 담당 범위이며 이번 전수 검토는 [자료 검토 결과](자료_검토_결과.md)를 따른다. 파일 경로는 별도 설명이 없으면 자료 묶음 루트 기준이다. 과거 작업용 스크립트명은 실행 이력이며 현재 실행 파일이 아니다.


수집 기준일: 2026-11-11. 이 문서는 전체 ZIP를 구성하는 RF 담당 부분의 범위와 검증 결과다. 최종 통합물의 다른 업체 자료와 합쳐 사용한다.

## 확정 산출물과 수량

| 항목 | 수량 / 위치 |
|---|---:|
| 정규화 조건 레코드 | 2,709 |
| 제품명 문자열 | 171 - 별칭, 부자재, 일반 재질 참고 포함, 독립 소재 171종을 뜻하지 않음 |
| 출처 목록 | 351 |
| 다운로드 성공 원문 | 350 - PDF 229, HTML 121 |
| 요청형 자료 접근 경로 | 1 - AGC ELL 문서 요청 폼 |
| 원문 바이트 합계 | 144,789,936 bytes |
| scalar Dk가 있는 레코드 | 2,653 |
| Df가 있는 레코드 | 1,992 |
| 수치 주파수가 명시된 레코드 | 2,592 |
| 두께를 보존한 레코드 | 2,300 |
| 유리직물 / 구성 레코드 | 2,186 |
| 수지 함량 레코드 | 2,205 |
| 명시적 원문 불일치, 모호성 표시 | 45개 레코드 |

- `data/observations/`: 전체 조건 레코드. 각 행의 `source_id`, `source_url`, `source_location`으로 원문 추적.
- `catalog/sources.json`: 원문 URL, 문서일, 조회일, 로컬 경로, 다운로드 상태, SHA-256, 바이트 크기.
- `audit/collection/rf_coverage.json`: 위 집계, 제조사별 집계, 17개 AGC 구성표별 완전 추출 행수, 공백과 검사 결과.
- `raw/RF/`: 다운로드한 공식 원문 PDF/HTML.
- `work/RF/`: 재현 스크립트, PDF 텍스트 추출본, 검사 이미지. 원문과 데이터가 최종 산출물이며 이미지, OCR는 중간 검토 자료다.

제조사별 데이터 행수는 Rogers 423, AGC 2,251, Arlon Electronic Materials 24다. Arlon 매뉴얼의 일반 재질 참고값은 11개를 별도 제조사명 `Generic material reference (Arlon handbook)` 및 `generic_material_reference` 타입으로 구분했다.

## 수집 범위

### Rogers

공식 Laminate Properties Tool과 Bonding Material Properties Tool의 Dk/Df 표, High Frequency Electronics Product Selector Guide 원문, 제품별 영문 데이터시트와 가공, 설계 자료를 수집했다. RT/duroid, RO3000, RO3200, RO4000, RO4500, RO4700, RO4830/4835/4835T, TMM, AD, CLTE, CuClad, DiClad, IsoClad, Kappa, TC, Anteo, RO1200, IM Series, bonding/prepreg 제품을 포함한다. MAGTREX의 자기적 성질은 비자성 PCB와 혼동하지 않도록 기록했고, Radix는 `3D printable dielectric (not a copper-clad laminate)`로 따로 표시했다.

온라인 선택표에 없는 개별 TDS의 추가 주파수, 두께, 방법 데이터를 보완했다. 특히 RO1200 laminate/bondply의 11개 주파수  x  8개 두께 구성 표를 88행으로, SpeedWave 300P의 11개 직물/RC  x  6개 주파수 표를 66행으로 보존했다. CLTE-MW, CLTE-XT, RO4835T, RO4450T, RT/duroid 6202PR의 두께별 값도 개별 레코드로 기록했다.

공식 원문:

- [Rogers Laminate Properties Tool](https://tools.rogerscorp.com/acs/properties/laminates/index.aspx) - RF001.
- [Rogers Bonding Material Properties Tool](https://tools.rogerscorp.com/acs/properties/bonding/index.aspx) - RF002.
- [High Frequency Electronics Product Selector Guide](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/product-selection-guides/high-frequency-electronics-product-selector-guide.pdf) - RF003.
- [RO4003C / RO4350B TDS](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf) - RF188.
- [RO4830 TDS](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4830-high-frequency-laminates-data-sheet.pdf) - RF339.

### AGC: Taconic 계열 / Meteorwave / Nelco 계열

공식 2026-10 Solutions Guide, RF/마이크로웨이브, PTFE, bondply, thermoset 제품군의 공개 TDS 및 공정자료를 수집했다. RF-10/30A/35TC/35HTC/60TC, NF-30, TLY/TLX/TLE/TLC, TSM-DS3/DS3b/DS3M, fastRise 계열, Meteorwave와 N4000/N5000/N7000/N8000/N9000 계열이 포함된다.

공식 Dk Table 17개는 표의 숫자 행 후보 수와 파서 추출 행수를 대조했다. **696개의 원문 구성 행  ->  2,118개의 주파수별 레코드**, 누락 후보 0개다. 여기서 Dk만 기재한 주파수의 Df는 null로 유지했다.

| 제품 / 출처 | 원문 구성 행 | 정규화 행 |
|---|---:|---:|
| N5000 / RF267 | 73 | 292 |
| N8000 / RF270 | 24 | 96 |
| Meteorwave 1000 / RF297 | 80 | 240 |
| Meteorwave 2000 / RF304 | 78 | 234 |
| Meteorwave 3000 / RF306 | 38 | 114 |
| Meteorwave 3350 / RF308 | 19 | 57 |
| Meteorwave 4000 / RF310 | 66 | 198 |
| Meteorwave 8000 / RF312 | 58 | 232 |
| Meteorwave 8300 / RF314 | 27 | 54 |
| Meteorwave M1 / RF317 | 8 | 16 |
| N4000-13 / RF320 | 32 | 96 |
| N4000-13 EP / RF322 | 35 | 105 |
| N4000-13 EP SI / RF324 | 24 | 72 |
| N4000-13 SI / RF326 | 24 | 72 |
| N4000-29 / RF329 | 40 | 80 |
| N7000-2HT / N7000-3 / RF333 | 48 | 138 |
| N7000-3F / RF336 | 22 | 22 |

미국 AMMA와 싱가포르 AMMS 제조 위치, laminate/prepreg 구분, ply 수를 포함한 직물 구성, 수지 함량, 주문/지정 두께와 명목 두께의 차이를 보존했다. 예를 들어 `construction="2 106 + 1 1080"`을 단일 직물 106이나 1080으로 축약하지 않았다. `thickness_mm` 외에 `specified_thickness_inch`, `nominal_thickness_inch`, `thickness_tolerance_inch`, 원문 행을 함께 남겼다.

공식 원문:

- [AGC Solutions Guide](https://www.agc-multimaterial.com/solutionsguide) - RF008.
- [Meteorwave 8000 Dk Table](https://www.agc-multimaterial.com/agc-downloads/AGC_Meteorwave_8000_Dk_Table.pdf) - RF312.
- [Meteorwave M1 Dk Table](https://www.agc-multimaterial.com/agc-downloads/AGC_Meteorwave_M1_Dk_Table.pdf) - RF317.
- [Meteorwave ELL 제품군 공개 표](https://www.agc-multimaterial.com/meteorwave-ell/) - RF346.
- [ELL202 제품 페이지](https://www.agc-multimaterial.com/solutions/meteorwave-ell-202/) - RF345.

### Arlon Electronic Materials

공식 Resources에 게시된 18종 TDS, Everything You Wanted to Know About Laminates 2023 Edition, 공정 및 Low-Flow 매뉴얼을 수집했다. TDS의 표가 이미지인 경우 p.2를 렌더링하고 육안 검토하여 33N, 35N, 37N, 38N, 44N, 45N, 45NK, 47N, 49N, 51N, 55NT, 84N, 85HP, 85N, 84HP, 86HP, 85NT의 Dk/Df를 추출했다. HF-50에는 확인한 TDS에 Dk/Df가 없으므로 숫자를 만들지 않았다.

- [공식 Resources](https://www.arlonemd.com/resources/) - RF007.
- [Everything Laminate Guide 2023](https://www.arlonemd.com/wp-content/uploads/2023/04/Everything-Laminate-Guide-2023-Edition.pdf) - RF122. 인쇄 p.12의 FR-4 일반 범위는 1 MHz 조건 4.4-5.2이며, 특정 제품, RF 주파수 입력으로 확정된 값이 아니다.

## 시뮬레이션에서 특히 중요한 차이

유전율은 임피던스의 입력 중 하나다. 소재명만으로 유전율이 하나로 정해지지 않는다. 주파수, 시험법, 방향, 수지 함량, 유리직물, 경화 후 두께 및 실제 회로가 보는 조건을 맞춰야 한다. 선폭/선간거리, 동박 두께와 표면, 참조면까지의 거리 등 구조도 함께 필요하다. 이 묶음은 재료 입력 자료이며 제조사가 확정한 최종 stackup을 대신하지 않는다. Arlon RF122의 인쇄 p.12-15와 Rogers RF343/RF344가 이 차이를 설명한다.

Rogers Process Dk와 Design Dk는 다른 목적의 값이다. Design Dk는 회로 측정, 추출 기반 값으로, 마이크로스트립의 effective permittivity 숫자와 그대로 같은 개념이 아니다. 모든 시뮬레이터에 Design Dk를 무조건 넣으라는 규칙도 아니다. 추출 방식과 동박 roughness 모델의 중복 반영 여부를 확인해야 한다. RO4350B에는 공식 TDS에 Process 3.48과 Design 3.66이 각각 존재한다. 각각의 시험 조건을 따로 저장했다.

- [Rogers, Managing PCB Materials Dielectric Constant](https://www.rogerscorp.com/blog/2018/managing-pcb-materials-dielectric-constant-dk) - RF343.
- [Rogers, Test Method / Conductor Profile / Substrate Anisotropy technical paper](https://tools.rogerscorp.com/documents/2441/acm/articles/The-Influence-of-Test-Method-Conductor-Profile-and-Substrate-Anisotropy-on-the-Permittivity-Values-Required-for-Accurate-Modeling-of-High-Frequency-Planar-Circuits.pdf) - RF344.

## 원문 충돌 및 잘못 합치기 쉬운 값

원문의 차이는 평균내거나 임의 수정하지 않았다. `data_conflict`, `conflict_note`, `notes`, `frequency_text`를 함께 읽어야 한다.

- **AD250C / AD350A**: Rogers 온라인 선택표와 AD TDS의 Process/Design 수치 배치가 서로 다르다. TDS 표를 이미지로 확인했다. 각각의 출처를 따로 보존했다.
- **RO3003**: TDS의 8-40 GHz Design 3.00과 온라인 각주 29의 77 GHz Design 3.16은 시험 조건이 다르다. 단순 오타나 동일 조건 충돌로 취급하지 않는다.
- **RO4830**: TDS 상세 표 Design 3.24 @77 GHz와 온라인/소개 문구 3.2가 다르다. TDS 상세 표의 두께 0.0095 inch와 같은 페이지 표준품 0.0094 inch도 그대로 구분했다. Df는 별도 10 GHz SPDR 값이다.
- **CLTE-XT**: Dk가 두께에 따라 2.79/2.89/2.92/2.94로 나온다. 원문 두께 표의 inch와 괄호 mm가 서로 맞지 않는 두 항목은 원문 mm와 inch 환산 mm를 따로 보존했다. Design 선택표 2.94와 TDS 2.93의 차이도 표시했다.
- **RT/duroid 6202 / 6202PR**: 6202의 thin construction 각주를 6202PR로 복제하지 않았다. 6202PR은 자체 TDS의 0.005/0.010/0.020 inch 값 2.90/2.98/2.90을 보존했다.
- **TC600**: Dk 행은 1.8 MHz, Df 행은 1.8 GHz로 쓰여 있다. Dk 수치 주파수는 null로 두고 원문 단위를 `frequency_text`에 남겼다.
- **Meteorwave 8000 Dk Table p.4**: 앞 페이지 마지막 열은 80 GHz인데 p.4 마지막 열은 40 GHz라고 중복 표기되어 있다. 마지막 열의 값은 유지하되 해당 11개 행의 수치 주파수는 null로 보류했다.
- **AGC TLF-35A**: TDS Dk 시험 조건은 10 GHz, selector 각주 조건은 1.9 GHz다. 두 출처를 구분했다.
- **TLX-8 / TLE-95 / TLC-32**: TDS의 Dk는 1 MHz이고 Df는 10 GHz다. 하나의 10 GHz Dk/Df 쌍으로 합치지 않았다.
- **TSM-DS3 / TSM-DS3M**: 개별 TDS 전기물성 표의 주파수 조건이 비어 있다. 시험법 번호 또는 그래프를 근거로 그 빈 칸을 채우지 않았다. selector 10 GHz 값은 별도 출처로 존재한다.
- **N4000-29**: TDS Dk 4.23은 2 GHz, Df 0.015는 2.5 GHz다. 별도 행으로 유지했다.
- **N4000-29NF / Meteorwave 1000NF**: TDS와 selector의 대표값 차이를 보존했다. 구성 정보가 없는 두 명목값을 어느 한쪽으로 덮어쓰지 않았다.
- **Arlon 86HP**: 1 GHz 값은 RC 70%, 5/10 GHz 값은 RC 57% 조건이다. 같은 구성의 주파수 분산 데이터로 이어 붙이지 않는다.
- **Arlon 85HP**: 표에 인쇄된 1 MHz와 IPC-TM-650 2.5.5.9를 그대로 기록하고 검토 필요를 주석 처리했다.
- **MAGTREX 555**: 400 MHz에서 전기, 자기 성질을 별도로 기록했다. 상대 투자율을 일반 PCB처럼 1로 가정하면 안 된다.
- 최대 손실과 전형 손실을 구분했다. 예: RT/duroid 5880LZ Df typical 0.0021 / max 0.0027.

## 공백과 공개 범위

전 세계, 과거 모든 제조사의 모든 문서를 찾았다는 의미는 아니다. 이번 RF 부분은 위 공식 사이트의 공개 선택표, 제품 자료 목록과 추가 공식 검색 결과로 확인한 자료를 모았다.

AGC Meteorwave E2/E3/ELL 202/205/302/305는 공개 nominal Dk/Df 및 Dk range는 수집했다. 상세 Dk Table, TDS, 공정 지침은 공식 ELL202 페이지가 문의 폼으로의 요청을 요구한다. 요청 경로 RF352는 `download_status=request_only`, 원문 경로 null로 표시했다. 폼 제출이나 타인에게의 메시지 전송은 하지 않았다. 이 공백은 다운로드 실패나 누락 숫자 0과 다르다.

Arlon 25N 같은 역사적 제품은 현재 공식 Resources 목록의 개별 TDS를 찾지 못했다. 제조사 외 미러만 발견한 자료는 이번 담당 원문 묶음에 포함하지 않았다. Rogers 92ML도 선택표 값은 있으나 확인한 현재 제품 URL에서 개별 TDS를 확보하지 못했다.

원문 그래프는 PDF에 그대로 포함되어 있다. 그림의 곡선을 디지털화하여 정확한 수치 sweep이라고 제공하지 않았다. 공개된 이산 표와 명시적 수치를 구조화했고, 온도, 주파수 곡선 및 가공 설명은 원문으로 참조할 수 있다. 보간, 외삽, Dk 누락값 채우기, tolerance에서 명목값 만들기, Design/Process 자동변환은 수행하지 않았다.

## 자체 검사

`work/RF/finalize_rf.py` 실행 결과 `PASS`:

- 모든 2,709개 레코드의 `source_id`가 최종 출처 목록에 존재하고 URL이 있음.
- 모든 다운로드 성공 출처에 파일이 존재하며 저장된 SHA-256이 실제 바이트와 일치.
- PDF 229개 모두 `%PDF` 형식 헤더 확인.
- 필수 수치 칼럼에 비수치 문자열, NaN, 무한대 없음.
- Dk 양수, Df 및 RC 범위, Dk min/max 순서 검사 통과.
- 17개 AGC 구성표 696행에 대해 표 행 후보와 추출 행수 대조, 누락 후보 0.
- Arlon 이미지형 TDS 및 주요 Rogers 충돌 표는 렌더링으로 검토.

이 검사는 파일, 형식, 추출 정합성을 검증한 것이며 제조사 시험값 자체의 정확성, 실제 제조 lot 또는 시뮬레이션 결과에 대한 보증이 아니다. 원문 충돌을 숨기지 않고 확인 가능한 형태로 남긴 것이 핵심이다.


패키지 경로 안내: 수집 단계의 파일 경로는 catalog/file_path_map.csv에서 최종 경로와 대조할 수 있습니다. 모든 최종 수치 행은 data/observations/의 JSONL과 회사별 Excel, 모든 출처는 catalog/sources.csv 및 .json에 통합되어 있습니다.
