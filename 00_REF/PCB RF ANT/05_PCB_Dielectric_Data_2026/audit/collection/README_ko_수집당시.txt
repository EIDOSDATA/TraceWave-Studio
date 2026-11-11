PCB 공개 유전율 / 손실탄젠트 자료 수집본
수집 기준일: 2026-11-11

먼저 START_HERE_ko.html을 여십시오. 인터넷 연결 없이 안내와 출처 검색을 볼 수 있습니다.

조건별 수치 행: 57,340
원자재 공개 수치 행: 26,815
PCB 제조사 공개 수치 행: 30,525
수치가 있는 기관/제조사 명칭: 37
출처 URL/접근 기록: 1,756
실제 보관한 고유 원문 파일: 1,682
그중 고유 PDF: 949

행 수는 제품 수가 아닙니다. 주파수, 직물, RC, 두께, 시험법, 적층의 층, 출처가 다른 관측 행입니다.
자료가 공개된 모든 회사의 모든 과거 개정판까지 완전히 모았다는 보장은 없습니다.
로그인/문의형 문서, 서버 차단, 삭제 URL과 일부 이미지 표의 미추출 상태를 기록했습니다.

파일 안내
  data/pcb_dielectric_all.csv : 전체 데이터, UTF-8 BOM, 모든 필드 보존
  data/pcb_dielectric_all.json : 전체 데이터, 숫자와 null의 타입 보존
  data/materials.csv : 원자재 제조사/부자재 공개 물성
  data/fabricators.csv : PCB 제조사 적층/계산기/소재 목록 수치
  data/by_organization/ : 공개한 기관별 CSV
  data/fabricator_native_metadata/ : JLC API 기술 응답, 적층 감사표 등
  catalog/Dataset_Index.xlsx : 기관/제품/출처/필드의 엑셀 색인 (전체 수치는 CSV/JSON)
  catalog/sources.csv 또는 .json : 원문 URL, 파일 경로, 상태, SHA-256
  catalog/products.csv : 제품명별 관측 행/주파수/출처 색인
  catalog/coverage.csv : 기관별 실제 확보 범위
  catalog/unavailable_or_request_only.csv : 원문 미확보/문의형/리다이렉트 기록
  catalog/data_dictionary.csv 및 schema.json : 필드/단위/결측 의미
  originals/ : 공개 원본 PDF, HTML, ZIP, 도면/기술 스냅샷
  search_text/ : PDF 자동 텍스트 추출본 (검색 보조; 원문 대조 필요)
  docs/ : 작업군별 조사·검증·주의 사항
  scripts/filter_records.py : 추정/보간 없이 원하는 행을 추출
  scripts/verify_package.py : SHA-256 무결성 검사

사용 원칙
1) 먼저 실제 제조 업체, 적층, 원자재 등급, 층을 정합니다.
2) 주파수/시험법/방향, core와 prepreg, RC, 직물 구성, 압착 후 두께를 맞춥니다.
3) dk와 df는 무차원, frequency_ghz는 GHz, thickness_mm는 mm입니다.
4) 빈 CSV 칸/JSON null은 미기재·불명확입니다. 0으로 바꾸면 안 됩니다.
5) dk_min/max 또는 부등호는 nominal 값이 아닙니다. 중간값을 자동 생성하지 않았습니다.
6) value_type, review_flags, source_location, notes를 확인한 뒤 원문으로 검토합니다.
7) 재질 εr와 전송선 εeff, Design Dk와 Process Dk를 구분합니다.
8) TDR/실측 coupon 및 실제 단면 치수와 대조하면 제조 편차를 검증할 수 있습니다.

예시
python scripts/filter_records.py --manufacturer Rogers --product RO4350B --frequency-ghz 10 --output ro4350b_10GHz.csv
python scripts/filter_records.py --manufacturer JLCPCB --output jlc_all.csv
python scripts/verify_package.py

원문 문서의 저작권과 상표는 각 제작자에게 있습니다. 출처/개정 조건을 보존하십시오.
