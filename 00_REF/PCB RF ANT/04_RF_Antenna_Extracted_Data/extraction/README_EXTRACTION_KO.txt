RF 패턴 안테나 구조화 추출 데이터 v1 | 2026-11-07 KST
====================================================

원문 목록 241건 / 실제 원문 238건.
학술 원문 74건, 독립 PDF 208개 8,443쪽, HTML 15개.

이번 실제 추출 결과
------------------
형상 사례 31개, 수치 파라미터 348행, 출처 23개.
숫자가 있는 형상 사례 29개. 부분 치수·초기값·원문 충돌 사례도 별도 상태로 포함합니다.
재질 Dk/Df 3,160행(정확한 구성·시험 조건·주파수별 레코드), 수치 출처 22개.
재질 보조 데이터 41행(구리 거칠기 및 표준 두께·클래딩 등), 재질 원문 31건 모두 처리 범위 기록.
적용 조건 47개 / 검증 방법 26개 / 모델 레코드 19개.
모델 18개에는 식을 수록했고 1개는 잘못 구현할 위험이 있어 식 사용을 명시적으로 보류했습니다.
수치 또는 조건을 선별 추출한 출처 75개.

확인 수준
---------
원문 전체 다운로드와 텍스트 색인, 선별한 원문 수치의 추출은 서로 다른 작업입니다.
source_coverage.csv에서 각 원문별로 geometry/material/condition/validation/model 행 수를 확인할 수 있습니다.
0행은 해당 문서에 값이 없다는 단정이 아니라 이번 정밀 추출 범위에 들어가지 않았다는 뜻일 수 있습니다.
material_review_note에는 재질 자료 31건의 구체적 처리 사유가 있습니다.
모든 source_sha256은 원문 catalog.json과 일치합니다. PDF 페이지는 첫 페이지를 1로 세는 물리 페이지입니다.
도면·스캔·표지 등 106쪽은 텍스트층이 짧거나 없습니다. 원문을 직접 확인하세요.
독립 EM 해석, PCB 제작, VNA/OTA 측정 및 생산용 자동 CAD 검증은 이번 자료 추출에서 수행하지 않았습니다.

사용할 파일
-----------
상위 폴더 RF_Antenna_Extracted_Data.xlsx : 필터 가능한 전체 구조화 데이터와 출처 범위.
rf_antenna_dataset.json : 프로그램 입력용 통합 구조. 원문 값과 적용 범위·출처가 함께 있습니다.
rf_antenna_data.sqlite : sources, evidence_pages, pages_fts 전문 검색과 구조화 데이터 테이블을 한 DB에 포함.
materials/ : 재질별 레코드, 표 행 근거, 원문 충돌, 보조 재질 데이터.
geometry/ : 형상별 치수·GND·급전·keepout·원문 충돌·부족한 정보·CAD 준비 상태.
validation/ : 적용 조건, 검증 절차, 모델식, 프로그래밍 입력 필드 제안.
source_index/ : 페이지별 JSONL.gz, ZIP 내부 파일 목록, 텍스트층 점검 결과.
source_coverage.csv : 모든 원문 항목의 확보·색인·정밀 추출 상태.
record_sources.csv : 레코드에서 source ID, 물리 페이지, 해시로 연결하는 표.
DATA_DICTIONARY.csv : 필드·자료형·고정 단위·누락값 개수.
QA_SUMMARY.json : 출처 연결, 수치형, 페이지 범위, DB 일관성 검증 결과.

프로그램에 연결할 때
-------------------
1. topology와 target band로 형상 사례를 고릅니다. 개방 원호·폐쇄 링·원판·슬롯·IFA·NFC 코일을 혼합하지 않습니다.
2. geometry extraction_status 및 missing_information/source_conflicts를 읽습니다. 수치가 있어도 자동 생산 CAD를 보장하지 않습니다.
3. 재질명뿐 아니라 정확한 grade, glass/construction, resin content, thickness, frequency, method, process/design Dk를 선택합니다.
4. material Dk/Df와 형상 논문에서 가정한 FR4 값을 자동으로 같은 재질로 매칭하지 않습니다.
5. conditions와 validation_methods에서 해당 토폴로지에 필요한 GND/급전/케이스/배터리/지연/효율 조건을 가져옵니다.
6. 원문이 제시한 목표값은 해당 문서/기기 범위에만 적용합니다. 보편적인 -10 dB 또는 효율 기준은 넣지 않았습니다.
7. 원문 충돌·개발 중 값·시험법 미기재는 검토 상태를 유지합니다. null은 0이 아니며 보간/외삽은 별도 모델 없이는 수행하지 않습니다.
8. 형상 생성·EM 모델·공차 분석·VNA/OTA 비교를 구현한 뒤 시뮬레이션과 실측을 독립적으로 검증합니다.

데이터베이스 조회 예시
---------------------
SELECT material, material_form, frequency_hz, dk, df, source_locator
FROM materials WHERE material LIKE '%FR408HR%' AND frequency_hz=2000000000;

SELECT geometry_id, name, value, unit, physical_pdf_page, locator
FROM geometry_parameters WHERE source_id='TI_DN023_SWRA228';

SELECT source_id, location, snippet(pages_fts, 2, '[', ']', ' ... ', 24)
FROM pages_fts WHERE pages_fts MATCH 'monopole AND ground' LIMIT 20;

재현·갱신
---------
각 domain의 build_*.py는 추출 규칙과 출처를 남긴 코드입니다. 원문과 catalog를 입력으로 사용합니다.
Python 3, PyMuPDF 및 각 스크립트의 명시된 의존성이 필요합니다. 실행 전 별도 작업 폴더에서 입력 경로를 확인하세요.
tools/REPRODUCE_KO.txt에 코드·입력·작업 폴더의 대응을 기록합니다.
원문의 권리·라이선스는 그대로 유지되며 프로그램 자산으로의 상업적 재배포 허가를 새로 부여하지 않습니다.
