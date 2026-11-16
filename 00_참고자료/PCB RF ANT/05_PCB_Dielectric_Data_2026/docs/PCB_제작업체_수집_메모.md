# PCB 가공업체 공개 유전율, 적층 자료 조사

수집 단계의 상세 기술 메모를 보존한 문서다. 아래 수량과 자체 검사는 당시 담당 범위이며 이번 전수 검토는 [자료 검토 결과](자료_검토_결과.md)를 따른다. 파일 경로는 별도 설명이 없으면 자료 묶음 루트 기준이다. 과거 작업용 스크립트명은 실행 이력이며 현재 실행 파일이 아니다.


조사, 접근일: 2026-11-11. 이 문서는 가공업체 담당 수집 범위의 설명이며, 전 세계 모든 업체 또는 비공개 고객 지정 적층자료의 완전성을 주장하지 않는다.

## 최종 산출물

- `catalog/sources.json`: 공식 출처 240건. 실제 원문/기술 스냅샷이 있는 출처 232건, 직접 다운로드 실패 6건, 사람 확인 페이지로 차단된 출처 2건.
- `data/observations/`: 30,525행. 행은 **자료 출처  x  제품/구성  x  주파수/층/조건** 단위다. 독립 원자재 30,525종 또는 독립 측정 30,525회가 아니다.
- `audit/collection/fab_summary.json`: 가공업체별 행 수, 출처 수, 명명 적층 수와 데이터 종류 집계.
- `audit/collection/fab_extra_files.json`: 최종 ZIP에 원문 manifest의 `local_path` 외에 추가해야 할 파일 37개를 경로, 용도, 크기, SHA256과 함께 명시한다. 특히 JLC API 실제 응답 31개를 누락하면 안 된다. 226개 비물리적 PP 두께 정규화에 대한 audit도 포함한다.
- 원문은 `raw/FAB/`에 있다. 원문 ZIP 내부의 Altium `.stackup`, IPC-2581B `.cvg`, PDF는 원본 ZIP 그대로 보존했다. 별도 압축해제 사본은 불필요하다.

출처의 `local_path`가 있는 항목만 원문 파일로 계산해야 한다. 과거 시도 과정에서 생긴 임시 HTML, 스크립트, 화면 렌더링 파일을 전부 사용자 ZIP에 넣을 필요는 없다. 공식 웹페이지는 출처 추적을 위해 보존했고, PDF 원문은 136개, 공식 ZIP은 18개다. 같은 원자재 문서가 여러 가공업체에 다시 게시되어 있을 수 있다.

## 핵심 적층 데이터

| 업체 | 공개 자료 범위 | 정규화된 유전체 행 | 해석 |
|---|---|---:|---|
| JLCPCB | 일반 PCB API 1,519개, HDI API 1,407개, 합계 2,926개 템플릿. 그중 명명된 템플릿 2,466개 | 26,276 | 익명 공개 계산기 응답의 적층 Dk. 원자재명, 공급사, glass style, RC%, 층별 두께 포함. 시험 주파수, Df, Dk 공차는 없음 |
| PCBWay | 공식 페이지에 실린 4-18층 적층표 298개 전체 | 2,250 | 원문 표의 재료/층별 Dk와 압착 전후 두께. 일부 PP 두께는 여러 ply 묶음 단위 |
| Würth Elektronik | native Altium 원문 175개 항목, 파일명은 169개, SHA256로 다른 내용은 168개 | 1,598 | IPC 재료군 대표값을 사용한 초기 설계용 표준 적층. 특정 공급사 제품 확정값 아님 |
| AISLER | 4층 1.6 mm, 4층 0.8 mm, 6층 1.6 mm, 8층 1.6 mm / 35 um Cu 도면 | 32 | 원문 이미지의 층별 Dk 또는 범위. 주파수 없음 |
| OSH Park | 2층, 4층, 6층 및 대체 4층 EM-528 적층 | 10 | 주파수를 적층별로 구분. 중앙 core Dk 공란은 외측 PP 값으로 채우지 않음 |

Würth 파일 중 FLEX4/6/8 및 HDI4/6/8은 서로 다른 기술 ZIP에서 중복 제공된다. 원문별 provenance는 유지했으며, 175개를 모두 독립 적층이라고 표현하면 안 된다. `fab_we_audit.json`에 각 원본 내용 해시를 넣었다. 정규화 데이터의 `distinct_stackup_ids`는 169개다.

### JLCPCB API

공식 공개 계산기 `https://jlcpcb.com/pcb-impedance-calculator`가 호출하는 공개 POST API에서 일반 PCB(`boardType=1`) 및 HDI(`boardType=3`) 자료를 수집했다. 두 항목 모두 공개 UI에 존재한다. `pageSize=100`, `usePurpose=1`로 각 범위의 마지막 페이지까지 확인했고, 응답 `total`과 실제 수집 건수가 일치한다.

- 일반 PCB: 1,519개 응답 중 명명 템플릿 1,222개, Custom/No requirement/동등한 중국어 항목 297개, 숫자 Dk 층 16,933행.
- HDI: 1,407개 응답 중 명명 템플릿 1,244개, 사용자 정의 항목 163개, 숫자 Dk 층 9,343행.
- 명명된 2,466개 모두에 양의 유전율 값이 있다. 전체 기술 응답에는 사용자 정의 placeholder도 그대로 남겨 구조와 API 범위를 확인할 수 있다.
- `Copper` 행에도 Dk=4.2 같은 필드가 들어 있으므로 그 값은 유전체 데이터로 추출하지 않았다. `Dk=0`도 실제 유전율로 취급하지 않았다.
- 원자재 등급은 주로 Nan Ya NP-155F 및 Shengyi S1000-2M. 데이터베이스 재료 정의 ID, 공급사, Dk, 재료명 조합은 165개다. 서로 다른 층에 같은 조합이 반복되어도 층별 geometry를 보존하기 위해 행을 유지했다.
- `thickness_mm`는 API `basicDataList.dielectricThick`이며 단위는 mm다. 재료명에 "with copper"라고 적힌 nominal 두께와는 별개다. `beforeCountPpDataList`의 조정 전 두께는 별도 필드에 남겼다. 이 값은 계산기의 명목 설계값이며 제작 후 단면 실측이 아니다.
- 일부 API 템플릿은 64층까지 있다. 현재 주문 서비스에서 전부 발주 가능한지 이 응답만으로 보장할 수 없다.
- 공개 응답에는 비기술적인 직원 작성자/수정자 메타데이터가 섞여 있었다. 사용자에게 전달할 기술 스냅샷에서는 `createUserId`, `createUserName`, `updateUserId`, `updateUserName` 4개 필드만 재귀적으로 제거했다. 유전체, 동박, geometry, 공정, 재료, 템플릿 관련 기술 필드는 모두 유지했다. 응답 원본 해시와 기술 스냅샷 해시를 request manifest에 따로 기록했다.

FB240의 `local_path`는 API 요청 manifest다. 실제 페이지 스냅샷 31개는 `additional_local_files`와 `fab_extra_files.json`에 지정되어 있다. 주요 재사용 파일:

- `originals/JLCPCB/JLCPCB__NP-155F_및_S1000-2M__기술자료__FB240.json`
- `data/fabricator_native_metadata/board_type_1_page_001.json`부터 `_016.json`
- `data/fabricator_native_metadata/board_type_3_page_001.json`부터 `_015.json`
- `data/fabricator_native_metadata/fab_jlc_stackup_audit.json`
- `data/fabricator_native_metadata/fab_jlc_material_definitions.json`

공개 단순 파라미터 페이지 FB038과 legacy FB039는 서로 다르다. 현재 7628/3313/1080/2116 Dk는 4.4/4.1/3.91/4.16이며, legacy는 7628=4.6, 3313=4.05, 2116=4.25다. 두 출처를 합쳐 하나의 보장값으로 만들지 않았다. 새 API는 core도 4.38, 4.55 등 구성별로 다르므로 단순 페이지의 core=4.6을 모든 적층에 덮어쓰면 안 된다.

#### JLC API의 음수 ply 두께 226행 처리

통합 검증에서 일반 PCB의 **25개 템플릿, 226개 PP 행**에 `basicDataList.dielectricThick=-0.0185 mm`가 있음을 확인했다. 모두 내층 동박 4 oz, Shengyi S1000-2M의 106 RC72% PP다. 원문 API에 실제로 이 숫자가 있으므로 단위 변환 오류가 아니다. 조정 전 `beforeCountPpDataList` 값은 전부 0.05 mm이고 차이는 0.0685 mm이며, 해당 경계의 동박 두께 0.137 mm의 절반과 같다. **동박을 반영하는 API의 PP 두께 조정 과정에서 생긴 장부상 개별 ply 값으로 해석할 근거가 있으나, 서버 알고리즘과 물리적인 압착 후 ply 두께는 확정하지 않았다.**

각 연속 PP 묶음의 API 두께 합계는 모두 양수(0.09-0.2855 mm)다. 그러나 묶음에 서로 다른 Dk의 ply가 들어 있어 개별 음수 두께를 그대로 물리층에 적용하거나, 임의로 양수 ply들에 재분배하면 잘못된 모델이 된다.

따라서 해당 226행의 정규화 `thickness_mm`를 **null**로 바꾸고 원문은 `source_thickness_mm=-0.0185`에 보존했다. `thickness_status=invalid_nonpositive_source_ply_value`와 다음 `quality_flags`를 부여했다: `nonpositive_source_dielectric_thickness`, `individual_ply_thickness_unresolved`, `requires_fabricator_stackup_confirmation`. 조정 전의 0.05 mm를 물리 두께로 대신 입력하지 않았다. Dk, 수지함량, 제품명, 출처 및 전체 행 수는 유지했다.

`data/fabricator_native_metadata/fab_nonpositive_thickness_audit.json`에 모든 해당 record ID, 원문 위치, 두께 전후값, 인접 동박, PP 묶음과 조치를 기록했다. **원본 source manifest, 원문 파일, API 기술 스냅샷 및 그 해시는 변경하지 않았다.** 수정 후 정규화 `thickness_mm`의 음수, 0 값은 0건이다.

### PCBWay PP 묶음 두께 처리

공식 페이지 `multi-layer-laminated-structure.html`의 298개 적층을 모두 수집했다. 층 수별로 4층 112개, 6층 74개, 8층 49개, 10층 33개, 12층 12개, 14/16/18층 각 6개다.

원문 표에서 압착 후 두께는 `rowspan`으로 여러 PP에 공유될 수 있다. 이를 각 ply 두께로 반복 입력하면 전체 높이가 틀어진다. 묶음의 각 ply 두께를 분리할 근거가 없는 999행은 `thickness_mm=null`로 남기고 `laminated_group_thickness_mm`, 묶음 행 수, 시작 행, 압착 전 ply 두께를 별도로 보존했다. Core의 "with copper" 합계 두께 역시 절연층 두께와 구분했다. 전체 동박 포함 표는 `data/fabricator_native_metadata/fab_pcbway_stackups.json`에서 확인한다.

### Würth 적용 범위

공식 digital standards 페이지 자체가 이 자료를 초기 설계용 IPC 재료군의 대표값이라고 설명한다. 특정 원자재 업체의 제품 전체 데이터베이스와 다르며, 전체 자재 DB는 별도 문의 대상이다. 실제 제어 임피던스 설계는 제작업체 계산으로 다시 확인해야 한다. 표준 BASIC, PUREflex, RIGID.flex, SLIM.flex, SLIM.hdi, HDI / MICROVIA에 대해 공개 Altium/PDF/IPC 자료를 확보했다.

`fab_we_raw_fields.json`은 Altium master layer 필드를 보존한다. 리지드플렉스 지역별 geometry는 native `.stackup`의 region 구조를 확인해야 하며, master layer 행만 사용해 모든 영역을 같은 적층으로 만들면 안 된다.

## 다른 제조사 자료

| 업체 | 포함 범위 | 중요한 조건 |
|---|---|---|
| Epec | 공식 소재 비교표 11개 제조사 그룹 전체, 55개 제품명, 주파수별 66행; 링크된 제조사 PDF 일괄 확보 | 요약표의 1 MHz/1 GHz 헤더를 기록했지만 RF 제품의 원자재 시험 주파수와 맞지 않을 수 있어 검증 플래그 부여 |
| Multi Circuit Boards | rigid/flex/high-frequency/high-Tg 표, default material PDF, 임피던스 계산 가정, 링크된 소재 PDF | 일반값, 대체자재 허용과 실제 지정 제품의 값 구분. 별표가 1 MHz 또는 1.9 GHz로 주파수를 바꿈. 불완전한 ** 각주는 주파수 미지정 |
| NextPCB | high-speed 26행 및 RF 5행 전체, 연결된 PDF 30개 | Gbps 분류를 GHz 측정 주파수로 오인하지 않음. `/`로 나뉜 다중값 5행은 조건이 없어 배열과 원문만 유지 |
| Lab Circuits | 8개 재료 그룹의 원자재 Dk와 제작업체 임피던스 계산용 Dk를 각각 수록 | 두 종류를 `value_type`으로 구분. RO4350B의 제작업체 계산값을 다른 업체의 보편적 Design Dk로 사용하지 않음 |
| Fineline | 공식 HTML 62행, 2022-05 PDF 62행 및 분류범위 5행 | 웹 검색 열람 가능, 직접 다운로드 403으로 원본 파일은 미포함. HTML/PDF 불일치를 따로 보존 |
| Eurocircuits | 공개 RF-pool I-Tera 조건 및 원자재, bondply, soldermask, 방열 paste PDF | 전체 서비스의 고객 지정 적층 데이터가 아님. 원자재 PDF의 비교 제품은 실제 선택 자재를 뜻하지 않음 |
| AdvancedPCB / Advanced Circuits | 2018-08-02 material guide 전체 33행 | 역사적 가이드. Dk와 Df 시험 주파수가 다른 제품은 별도 주파수 필드로 기록 |
| CircuitHub | Kingboard KB-6050 prepreg 4종 | glass style별 값이며 주파수/RC 미기재 |
| NCAB | standard/mid/low/very-low/ultra-low/extremely-low 분류 6개 | 제품별 측정값이 아닌 분류 범위 |
| Seeed Fusion | DFM V1.1 원문, FR4 Tg130 서비스 Dk 범위 4.2-4.7 | 주파수 미기재 범위. 이를 4.5 같은 단일값으로 바꾸지 않음 |
| TTM Technologies | 공식 LTCC design guide 및 DuPont 951/Ferro A6M 전기특성 | LTCC 패키지용 세라믹 자료이며 TTM의 모든 PCB 소재를 대변하지 않음. 주파수별 그림 원본은 PDF에 보존, 곡선에서 정확한 숫자를 창작하지 않음 |

### 불일치와 제한

Fineline HTML/PDF는 TU-872 SLK의 Df를 각각 0.011/0.006, IT150DA를 0.0025/0.0065, VT901을 0.0012/0.012로 게시한다. RO4450F PP의 Df=0.04도 원문 그대로 남겼고 오류 가능성 플래그를 달았다. 확인되지 않은 값을 임의 수정해서 "정답 데이터"로 만들지 않았다.

모든 수치는 단위 없는 상대유전율 Dk/epsilonr 및 손실탄젠트 Df/tandelta다. `frequency_ghz=null`은 DC나 1 GHz를 뜻하지 않고 주파수 미상이다. 범위, 카탈로그 대표값, IPC class 계획값, 계산기 가정값, 실제 공급사 시험값을 같은 수준의 시뮬레이션 입력으로 합치면 안 된다. 이 데이터는 출처 사실 모음이며 각 행의 `simulation_ready=false`는 실제 선택 적층, 주파수, 제작조건을 확인하지 않은 상태를 뜻한다.

원본 PDF의 모든 기계/열/전기 표를 개별 숫자행으로 전사했다는 뜻은 아니다. 표로 읽을 수 있는 주요 Dk/Df 자료와 층별 값을 정규화하고, 나머지 상세 그래프, 제조 지침, 보조 특성은 원문에 보존했다. 전체 주파수 분산 모델, anisotropy tensor, 동박 표면거칠기 모델, 제작 후 두께 공차 등은 공개 자료만으로 완성되지 않는 경우가 있다.

## 국내 및 추가 업체 탐색 기록

다음 범위는 조사한 공식 페이지에서 공개 숫자 Dk/전체 적층 DB를 확보하지 못했다는 뜻이다. 해당 업체가 어디에도 공개하지 않았다는 전수검증 결과는 아니다.

- SamplePCB: 공식 주문/FAQ 검색 결과를 확인했지만 직접 열람은 사람 확인 페이지였다(FB071/FB072). 우회하지 않았다. 확인된 Tg 분류를 Dk로 대체하지 않았다.
- 디바이스마트 PCB 제작 안내: 공식 주문/제작 안내 확보(FB073). 층별 Dk 표를 발견하지 못함.
- 한샘디지텍: 공식 FAQ 검색 확인, 직접 다운로드 503(FB074). 고객 게시판 첨부를 임의 수집하지 않음.
- 이수페타시스: 공식 연구개발 페이지(FB188)에 고주파 측정/해석 역량이 있으나 숫자 Dk/stackup 데이터셋을 발견하지 못함.
- 대덕전자: 공식 제품 자료(FB189)에서 소재 특성 설명 확인, 층별 숫자 Dk 없음.
- 코리아써키트: 공식 제품/회사 정보(FB190) 확인, 적용 가능한 공개 Dk 표 미확보.
- TLB: 공식 제품 정보(FB191) 확인, 적용 가능한 공개 Dk 표 미확보.
- 심텍: 공식 package substrate 제품 페이지(FB075) 확인, 층별 숫자 Dk 미확보.
- Sierra Circuits: 공식 material selector 소개(FB067) 확보. 인터랙티브 selector의 전체 export는 이 작업에서 확보하지 못해 재료별 숫자를 추정하지 않음.
- PCBGOGO: 공식 capability page(FB070) 확보. 숫자 Dk/전체 적층표 미확보.
- PCBCart: 공식 도메인 검색에서 신뢰 가능한 완전한 수치 표를 확보하지 못함. 전 세계 가공업체 전수목록으로 간주할 수 없음.

최종 실설계에 필요한 비공개/주문별 적층은 선택한 업체의 CAM/FAE에게 해당 stackup의 원자재 grade, resin content, 실제 압착두께, 주파수별 design Dk/Df, copper roughness/도금, soldermask 두께, 허용 공차 및 coupon 검증조건을 요청해야 한다. 이 조사 과정에서 이메일이나 타인에게 문의 메시지는 보내지 않았다.

## 주요 공식 출처


- JLCPCB 현재 파라미터: https://jlcpcb.com/impedance
- JLCPCB pressed prepreg 주의: https://jlcpcb.com/help/article/multi-layer-pcb-standard-laminated-structures
- JLCPCB flex Dk: https://jlcpcb.com/capabilities/flex-pcb-capabilities
- PCBWay 전체 298개: https://www.pcbway.com/multi-layer-laminated-structure.html
- Würth 표준값 한계: https://www.we-online.com/en/support/design-tools/digital-pcb-standards
- OSH 4L: https://docs.oshpark.com/services/four-layer/
- OSH 6L: https://docs.oshpark.com/services/six-layer/
- Multi-CB 소재: https://www.multi-circuit-boards.eu/en/pcb-design-aid/layer-buildup/pcb-materials.html
- Eurocircuits 다운로드: https://www.eurocircuits.com/downloads/
- Fineline HTML: https://www.fineline-global.com/pcb-material/
- Fineline 2022 PDF: https://www.fineline-global.com/wp-content/uploads/2022/05/Fineline_Materials_V4.pdf


패키지 경로 안내: 수집 단계의 파일 경로는 catalog/file_path_map.csv에서 최종 경로와 대조할 수 있습니다. 모든 최종 수치 행은 data/observations/의 JSONL과 회사별 Excel, 모든 출처는 catalog/sources.csv 및 .json에 통합되어 있습니다.
