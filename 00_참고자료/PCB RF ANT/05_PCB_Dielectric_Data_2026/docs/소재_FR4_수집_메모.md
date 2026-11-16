# FR-4, 고속재, 저손실재 공개 자료 수집 메모

수집 단계의 상세 기술 메모를 보존한 문서다. 아래 수량과 자체 검사는 당시 담당 범위이며 이번 전수 검토는 [자료 검토 결과](자료_검토_결과.md)를 따른다. 파일 경로는 별도 설명이 없으면 자료 묶음 루트 기준이다. 과거 작업용 스크립트명은 실행 이력이며 현재 실행 파일이 아니다.


확인일: 2026-11-11. 담당 범위: Isola, Panasonic, Shengyi Technology, ITEQ.

## 최종 파일과 범위

`fr4_data.json`과 `fr4_sources.json`은 **네 업체를 모두 합친 최종 파일**이다. `iteq_data.json`, `shengyi_data.json` 등은 중간 산출물이므로 다시 합치면 중복된다.

| 업체 | 수치 레코드 | 데이터에 등장하는 제품 코드/명칭 | 원본 PDF 파일 | 수집 범위 |
|---|---:|---:|---:|---|
| Isola | 3,329 | 19 | 69 | 공개 제품 카탈로그의 정상 접근 가능한 24개 제품 페이지, 연결된 데이터시트, Dk/Df 표, 가공/설계 가이드 |
| Panasonic | 6,886 | 62 | 28 | 회로기판 재료 기술지원 페이지의 데이터시트, 2026년 R-5785(G) 정상 대체 링크, IPC-4101 대응표 |
| Shengyi Technology | 8,639 | 97 | 200 | 전체 제품 목록 11페이지의 105개 제품 페이지와 연결된 TDS, Lineup, Processing Guideline |
| ITEQ | 112 | 20 | 0 | 공식 2026 데이터시트 20종을 웹 도구로 열람, 전사. 직접 파일 다운로드는 HTTP 403 |
| 합계 | **18,966** | **198** | **297** | 출처, 카탈로그, 접근 실패 기록 총 **463개** |

레코드는 제품 하나당 한 개의 상수가 아니다. 제조사, 제품, core/prepreg, glass style, resin content, 두께, 주파수, 시험법 등의 조건별 관측값이다. 주파수별 여러 행은 서로 다른 조건을 보존하기 위해 구분했다. 동일 제품이라도 core와 prepreg, E-glass와 low-Dk glass, 수지 함량 및 시험법이 다르면 직접 대체하지 않는다.

이 수집 범위가 전 세계 모든 제조사, 과거 개정판, 비공개 적층 조건까지 완전하다는 뜻은 아니다. PDF에 포함된 기계, 열, 가공 수치 전체를 관계형 데이터로 전사한 것도 아니다. 수치 파일은 유전 특성과 관련 적층 메타데이터에 집중하며, 그 밖의 내용은 원본 PDF로 제공한다. PCB 제조사의 최종 pressed stackup 및 생산 로트와 일치하는지는 별도 확인이 필요하다.

## 수치화 및 검증

Isola는 공식 HTML의 구성별 Dk/Df 표를 읽었다. 19개 제품명의 주파수별 데이터와 core/prepreg 명칭, construction, RC, mm/inch 두께, Standard/Non-standard offering을 보존했다. HTML 표에 시험법이 기재되어 있지 않아 **3,329행의 method는 null**이다. 다른 데이터시트의 시험법을 무조건 가져다 붙이지 않았다. 관련 원본 Dk/Df PDF도 함께 저장했다.

Panasonic은 6,886행 모두 Dk, 주파수, 표에 연결된 시험법, 두께, glass style, RC를 확보했다. 서로 다른 PDF 추출기의 결괏값을 비교했고, 표의 병합 셀이 두 개의 물리 행을 한 셀에 넣은 경우 각 행으로 나눴다. XPEDION 자료 일부의 표 윤곽 검출 실패는 원문의 완전한 숫자 행과 헤더를 대조하여 보완했다. Dk/Df를 두 페이지에 나누어 실은 자료는 source_id, 제품, 형태, glass, RC, 두께, ply, 주파수, 시험법이 일치하는 경우만 연결했다. Df가 비어 있는 25행은 R-1650E/R-1650M의 해당 구성, 주파수 자료이며, 다른 구성의 값을 임의 대입하지 않았다.

Shengyi의 Lineup 45종 중 44종에서 구성별 수치를 추출했다. Autolad3 Lineup(FRS183)은 이미지/윤곽선 글자 원문이어서 구성표 수치를 추정 전사하지 않았고 원본을 보존했다. PDF의 불필요한 세부 구획선과 병합 셀 때문에 열이 잘게 나뉜 Autolad1G, S1190G, Autolad3G는 원문의 4개 메타데이터 열 + 4개 Dk 열 + 4개 Df 열 구조로 복원했으며 인접 mm/mil 두께도 교차 확인했다. 일반 제품 페이지 값은 `typical_datasheet`, 명시된 RF design/process 값은 `design_dk`/`process_dk`로 구분했다.

최종 검증은 출처 ID 유일성, 모든 행의 출처 연결, 297개 원본 PDF의 `%PDF` 서명, 수치 범위, 단위/메타데이터 누락, 동일 조건, 동일 값의 중복 여부를 확인했다. 동일 조건, 동일 값의 중복 행은 발견되지 않았다. 이 검증은 모든 PDF 페이지를 사람이 한 셀씩 대조했다는 의미가 아니다. 원문, 감사용 원시 표, 파서와 누락 정보를 함께 남겼다.

## 시뮬레이션에 영향을 주는 원문 주의사항

1. **Panasonic R-1755E 두께 기준:** 원문 각주에 nominal thickness가 0.8 mm 미만이면 동박 제외, 0.8 mm 이상이면 동박 포함이라고 명시되어 있다. `thickness_basis`에 이 차이를 기록했다. 동박 포함 두께를 신호선과 기준면 사이 dielectric separation으로 곧바로 사용하면 안 된다. 원문의 `0.8 1/1` 등은 숫자 mm와 foil code를 분리하여 보존했다. 출처 FR101.

2. **Panasonic 낮은 주파수의 시험법 범위:** 120행은 표에 1 MHz 또는 100 MHz 열이 있으나 시험법 머리말에는 명시적으로 `1GHz ; IPC TM650-2.5.5.9`라고만 적혀 있다. `method_source_text`에 원문 문구를, `method_scope_note`에 적용 범위의 불명확성을 기록했다. 해당 주파수에서 별도로 확인된 시험법으로 오해하지 않는다.

3. **Panasonic XPEDION prepreg 명칭:** R-5515/R-5515X 문서의 R-5410/R-5410X 구성표 캡션은 Laminate라고 되어 있지만 표지에서 이 제품을 Prepreg로 명시한다. `material_form=prepreg`는 표지 기준이며 notes에 원문 모순을 기록했다. 출처 FR105, FR106.

4. **Shengyi SP168GN 두께 단위 오류:** 표 제목은 mm인데 수치는 25-100이고 인접 mil 열은 0.98-4.00이다. 원본을 화면으로도 확인했다. 단위를 추정 보정하지 않고 30행의 `thickness_mm=null`로 두었다. Dk/Df, glass, RC, 주파수, 원문 수치는 그대로 남겼다. 출처 FRS080.

5. **Shengyi S1150GH 빈 두께 셀:** 구성표의 한 행에서 mm 셀이 비어 있고 mil 열에는 14.00이 있다. 이에 해당하는 4개 주파수 행은 mm=null이다. 변환으로 채우지 않았다. 출처 FRS153.

6. **Shengyi S1141 150 보조 두께 열:** core 표의 보조 두께 열이 mil로 표시되지만 일부 수치의 크기는 inch에 해당한다. 데이터의 thickness_mm는 명시된 mm 열만 사용한다. 수지, 직조 조건과 숫자는 원문 그대로이다. 출처 FRS002.

7. **시험법 이름을 동일시하지 않음:** IPC-TM-650 2.5.5.13과 SPDR를 같은 시험법으로 치환하지 않았다. Shengyi는 여러 시험법/주파수 조건을 각주 한 문단에 함께 적는 경우가 있어 `method`에 원문 조건 문구를 보존하고 `method_is_multi_clause=true`로 표시했다. 정규화된 단일 시험법 이름이라고 가정하지 않는다.

8. **ITEQ IT-988GL/IT-988GLSE 방향/시험법 주석:** 원문 IPC 번호 옆에 Note*로 perpendicular dielectric constant by disk resonator를 붙인 열이 있다. 해당 열의 방향과 주석을 별도 기록했다. 이를 IPC 2.5.5.13의 통상 측정 방향과 무조건 같다고 해석하지 않았다.

9. **ITEQ RC와 개정판 차이:** 일반 웹 페이지의 RC와 최신 2026 PDF의 RC가 다른 예가 있다. 예를 들어 IT-999GSE2의 2026 PDF는 70%/83%, IT-150G는 75% 조건이다. 최신 PDF에 명시된 실제 각 열의 RC를 사용했고, 웹 대표표의 RC와 섞지 않았다.

10. **null의 의미:** 값이 0이라는 뜻이 아니다. Shengyi 일반 페이지에는 Df만 확인되거나 특정 속성의 상한/하한만 제시된 행, 주파수 범위만 제시된 design Dk가 있다. `dk_min`, `dk_max`, `df_min`, `df_max`, `frequency_text`, `source_context`를 함께 확인해야 한다. scalar가 없는 행은 EM 입력용 단일 유전율로 곧바로 가져가지 않는다.

## 접근 실패와 미완료 범위

ITEQ의 20종 공식 PDF는 웹 열람은 가능했지만 파일 직접 다운로드가 HTTP 403으로 거부되었다. 해당 출처는 `web_read_only_http403`, `local_path=null`로 표시한다. 숫자와 공식 URL은 있으나 원본 PDF 바이트가 ZIP에 들어 있다고 설명해서는 안 된다.

Panasonic 기술지원 페이지의 `ipcdatasheet_R-5785(G)_new.pdf` 링크는 HTTP 404였다. 정상 공식 대체 링크 `ipcdatasheet_R-5785(G).pdf`의 2026년 3월 개정 원본을 확보하여 포함했다. 실패한 링크도 기록했다. Isola 카탈로그의 오래된 TerraGreen copy URL 두 개도 HTTP 404 기록으로 남겼다.

일반 FR-4를 하나의 유전율로 정의할 수 없다는 점은 자료 자체에서 확인된다. 이 파일의 여러 RC/직조/주파수별 행을 재료 후보 탐색에 사용하고, 실제 제조 stackup의 정확한 core/prepreg 코드, pressed thickness, copper thickness/roughness, solder mask, 주파수, 허용오차와 맞추어 선택한다. Dk의 대표값, 설계값, 공정검사값, 유효 유전율은 서로 다른 입력이다.

## 공식 출처 진입점

- Isola: https://www.isola-group.com/pcb-laminates-prepreg/
- Isola 370HR 구성표: https://www.isola-group.com/pcb-laminates-prepreg/370hr-laminate-prepreg/
- Isola FR408HR: https://www.isola-group.com/pcb-laminates-prepreg/fr408hr-laminate-and-prepreg/
- Panasonic 기술지원: https://industrial.panasonic.com/ww/electronic-materials/products/sp_cbm/support
- Panasonic R-5785(G), 2026년 개정: https://industrial.panasonic.com/content/data/EM/PDF/ipcdatasheet_R-5785(G).pdf
- Panasonic R-1755E: https://industrial.panasonic.com/content/data/EM/PDF/ipcdatasheet_R-1755E.pdf
- Shengyi 전체 카탈로그: https://www.syst.com.cn/en/Product/list_257.aspx?parentid=0
- 각 ITEQ 공식 PDF URL과 열람 기록: 최종 `fr4_sources.json`의 FRI001-FRI020.

전체 URL, 원본 파일 경로, 다운로드 상태, SHA-256, 문서 날짜(확인 가능한 경우), 행별 원문 위치는 JSON 출처 파일에 연결되어 있다. 상세 누락 통계는 `fr4_validation.json`에 있다.

패키지 경로 안내: 수집 단계의 파일 경로는 catalog/file_path_map.csv에서 최종 경로와 대조할 수 있습니다. 모든 최종 수치 행은 data/observations/의 JSONL과 회사별 Excel, 모든 출처는 catalog/sources.csv 및 .json에 통합되어 있습니다.
