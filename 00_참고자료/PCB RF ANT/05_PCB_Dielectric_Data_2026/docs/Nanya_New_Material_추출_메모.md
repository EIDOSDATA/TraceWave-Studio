# Nanya New Material / NOUYA 추가 추출

수집 단계의 상세 기술 메모를 보존한 문서다. 아래 수량과 자체 검사는 당시 담당 범위이며 이번 전수 검토는 [자료 검토 결과](자료_검토_결과.md)를 따른다. 파일 경로는 별도 설명이 없으면 자료 묶음 루트 기준이다. 과거 작업용 스크립트명은 실행 이력이며 현재 실행 파일이 아니다.


최종 추가 데이터: `root_nouya_data.json`, **302행**. 원본 출처 파일 `root_sources.json`은 수정하지 않았다. 업체 식별자는 `Nanya_New_Material`이며 대만 Nan Ya Plastics와 구분한다.

- HTML 일반 제품 표: **188행**. 동일 비교표가 NYHP-220D/255D/265D/300D 네 제품 페이지에 반복되어 각 페이지의 해당 제품 열만 사용했다.
- NY8320 NSF Lineup, RT0660: **92행**. 원문 본문이 `Prepreg NY8320 NSFP`라고 명시하므로 제품은 NY8320 NSFP, material_form은 prepreg다. 23개 RC/직조/두께 조건  x  4개 주파수(1 MHz, 1/5/10 GHz). 문서에는 temporary version 표시와 Updated:20250526이 있다. 시험법은 `IPC`라고만 적혀 있어 구체적 IPC 번호를 보충하지 않았다.
- NY8320 LD Lineup, RT0701: **22행**. Core NY8320 LD 7조건  x  2주파수, Prepreg NY8320 LDP 4조건  x  2주파수(1/10 GHz). low-Dk glass라는 원문을 보존했다. 시험법이 없어 null이다. Updated:20250912.

## 원문 조건 및 오류 처리

1. `\\`는 공란/미제공으로 처리했다. 해당 HTML 속성 셀 78개를 이슈 파일에 기록했으며 0으로 바꾸지 않았다.
2. RC55%/70%처럼 두 조건과 두 숫자가 함께 있을 때만 순서대로 분리했다. NY2600, NY2140L은 RC 두 조건을 적어놓고 scalar 한 개만 제시하므로 RC를 특정하지 않고 `resin_content_pct=null`, `resin_content_text`에 원문을 보존했다.
3. NY-P5Q(RT0600)의 Dk는 RC65%, Df는 RC66%다. **Dk 3.10 행과 Df 0.0007 행은 별도 행**으로 유지했다.
4. NY6666(RT0610) 10 GHz의 Df 셀에는 `3.75\\3.42`가 실려 있다. 정상 손실탄젠트 값으로 수용하지 않고 각 RC 행의 `reported_df`에 원문 숫자를 저장하고 `df=null`로 뒀다. Dk 3.90/3.50는 원문대로 유지한다. 원문 오류로 보이지만 추정한 교정값은 넣지 않았다.
5. 일부 NYHP 표는 열 머리말이 Typical Value인데 행의 qualifier가 Maximum이다. `source_column_qualifier`, `value_type=published_typical_column_with_maximum_label`로 모순을 보존했다. 임의로 공칭값이나 보증 최대값으로 확정하지 않았다.
6. NY1600/NY2150에서 Df 시험법이 비어 있는 경우 Dk의 시험법을 복사하지 않았다. 시험법/conditioning이 다른 Dk, Df를 한 행으로 합치지 않았다.
7. NY3176HF, NY3170HF, NY2140L의 반복 주파수 표기는 원문 그대로 읽었다. 첫 번째 반복 행을 임의로 1 MHz로 고치지 않았다. 동일 조건, 동일 값은 한 행으로 합치고 source_location에 모든 원문 행 위치를 남겼다.
8. NY6600(RT0641) 페이지의 표 머리말에는 NY6600ANT라고 적혀 있다. 제품 동일성을 추정하지 않고 페이지 제품명과 표의 차이를 notes에 남겼다.
9. NY-A3HF(RT0620)의 `3 . 6`, `0.0 084`처럼 숫자 내부에 들어간 공백은 제거해 각각 3.6, 0.0084로 읽었다. 원래 셀 문자열은 source_context와 원시 표에 보존했다.

## 이번 추가 전사에서 빠진 자료

RT0583(NYHP-7300), RT0613(NY6300SL), RT0621(NY-A2)의 지정된 로컬 HTML 파일이 0바이트여서 추출할 수 없었다. 다른 연결 PDF 전부를 추가로 수치화하는 작업은 이번 범위에 포함하지 않았다. 이 자료들의 원본 수집/재다운로드 상태는 루트 출처 관리 파일을 확인해야 한다.

`root_nouya_raw_tables.json`에는 rowspan/colspan을 펼친 원시 HTML 표와 두 PDF의 원시 표가 있다. `root_nouya_issues.json`에는 missing 셀, 빈 HTML 파일, 원문 Df 이상값을 기록했다. 모든 추출 행에 기존 RT 출처 ID, URL, 원문 표/행/열 위치가 연결된다.

패키지 경로 안내: 수집 단계의 파일 경로는 catalog/file_path_map.csv에서 최종 경로와 대조할 수 있습니다. 모든 최종 수치 행은 data/observations/의 JSONL과 회사별 Excel, 모든 출처는 catalog/sources.csv 및 .json에 통합되어 있습니다.
