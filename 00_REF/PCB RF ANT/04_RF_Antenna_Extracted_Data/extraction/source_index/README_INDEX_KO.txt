원문 검색 색인
================
../rf_antenna_data.sqlite: sources(서지·해시), evidence_pages(페이지 본문), pages_fts(전문 검색), archive_members(CAD ZIP 내용 목록).
evidence_pages.jsonl.gz: SQLite 없이 사용할 수 있는 같은 페이지별 UTF-8 텍스트의 압축 JSON Lines.
source_index_coverage.csv: 원문별 색인 범위와 낮은 텍스트량 플래그.
archive_members.csv: 원본 및 정적으로 추출한 Qorvo ZIP의 내부 파일명·크기·CRC 목록.
low_text_pages.json: 텍스트층이 없거나 매우 짧은 페이지. 도면/이미지는 원문에서 확인할 것.

물리 PDF 페이지는 1부터 시작하며 책/논문에 인쇄된 페이지 번호와 다를 수 있습니다.
PDF 텍스트 순서는 자동 추출 결과입니다. 다단 편집, 수식 및 도면에서 읽는 순서나 기호가 달라질 수 있습니다.
색인 완료는 모든 수치를 사람이 추출·검증했다는 뜻이 아닙니다. curated 자료의 source locator 및 원문을 함께 사용하세요.

조회 예시 (Python 표준 라이브러리 sqlite3)
SELECT source_id, location, snippet(pages_fts, 2, '[', ']', ' ... ', 24)
FROM pages_fts WHERE pages_fts MATCH 'monopole AND ground' LIMIT 20;

SELECT pdf_page, text FROM evidence_pages WHERE source_id='TI_DN023_SWRA228' ORDER BY pdf_page;
