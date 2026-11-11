# 이번 정리의 검사 근거

검토일: 2026-11-11.

- data_audit.json: 수집 당시 전체 관측과 CSV의 전 필드 대조. 비교한 옛 경로는 검사 당시 대상이다.
- missing_local_sources.json: 원문 미보관 23출처와 241개 관측의 관계.
- source_audit.json 및 source_audit_summary.json: 최초 원본/검색 텍스트/ZIP의 검사 범위와 결과.
- source_archive_publication_summary.json: ZIP 내부 검색 자료 추가 결과.
- source_rename_report.json: 원문 이름 변경, 원본 해시 보존과 관측 경로 역변환 검사.
- cleanup_report.json: 반복 데이터 사본의 격리 경로, 백업 해시와 원 관측의 보존 근거.
- typed_data_preservation.json: 파일명 및 오래된 요청 manifest 참조를 역변환한 뒤 최초 57,340행의 전체 값/타입 해시와 일치하는지 확인한 결과.
- search_text_rename_report.json: 검색 TXT 1,115개의 파일명 변경과 바이트 보존 근거.
- review_script_verification.json: 검토 색인 재생성 및 오류 입력 거부 검사.
- dataset_tools_verification.json 및 filter_verification.json: 필터 CLI, 타입 보존, 잘못된 입력 거부와 원본 경로 보호 검사.
- content_verification.json: 최종 엑셀 발행 전 데이터/원문/검색 색인의 검사 기록. 최종 파일 목록은 현재 manifest로 다시 검사한다.
- excel_verification.json: 새 엑셀 38개, 전체 관측 57,340행과 저장된 데이터 셀/원문 JSON/로컬 링크의 최종 대조 결과.
- excel_render_verification.json: 엑셀 86개 시트의 대표 화면 생성/시각 확인 범위.
- excel_native_data_verification.json: JLCPCB/PCBWay/Wurth 적층 원자료의 행, 값과 타입 보존 검사.
- excel_export_verification.json: 공개 XLSX 저장 경로의 숫자/문자열/빈칸 보존 사전 검사.
- excel_jlc_assembly.json: JLCPCB의 검증된 소형 XLSX 조각을 4개 시트로 조립한 결과. 여기에 기록한 조립 단계 SHA와 링크 삽입까지 마친 최종 파일 SHA를 구분한다.
- excel_assembly_fixture_verification.json 및 excel_assembly_read_verification.json: 조립 시험본의 값/타입/스타일/내부 참조 및 독립 라이브러리 읽기 검사. Excel GUI에서 직접 연 시험은 아니다.
- excel_assembly_metadata_verification.json: 85개 조각 중 체크박스 메타데이터가 있는 78개는 내용이 같고, 없는 7개는 관련 참조도 없음을 확인한 결과. boolean 값과 표시를 보존했다.
- excel_visual_review.json: 독립 검토에서 확인한 표시 문제와 수정 확인 기록. 상단 화면 검토이며 모든 행/열의 육안 검토는 아니다.

이력 자료에 기록된 과거 파일 경로는 현재 열기 링크가 아니다. 현재 원문 경로는 ../../catalog/sources.json, 파일명 변경은 ../../catalog/source_filename_map.json, JLC의 오래된 요청 manifest 참조 수정은 ../../catalog/legacy_reference_path_map.json을 따른다.

현재 패키지 전체 바이트의 무결성은 ../../catalog/file_manifest.json과 ../../scripts/verify_package.py로 검사한다. manifest와 관측 정규 해시는 서로 다른 목적이다. 전자는 파일 변경을, 후자는 관측의 값/타입/출처 필드 변경을 검출한다.

최종 엑셀의 해시와 저장된 셀 대조 결과는 ../../Excel/workbook_index.json 및 excel_verification.json을 따른다. 원자료 타입 보존, 중간 조립, 최종 파일 검사와 대표 화면의 시각 검토는 서로 다른 검사 단계다.
