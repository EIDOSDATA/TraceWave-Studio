# 원문, 추출 자료와 분석의 분류

기준일: 2026-11-16 KST. `00_REF`는 근거 저장 위치를 유지한다. 작성 문서의 오래된 현재형을 교정하는 작업과 원문/수집/실행 증거의 내용을 바꾸는 작업은 다르다.

| 기존 자료 위치 | 분류 / 목적 | 사용 시 주의 |
| --- | --- | --- |
| [01_RF_Antenna_Vendor_Guides_CAD](<../../../00_REF/PCB RF ANT/01_RF_Antenna_Vendor_Guides_CAD/>) | 제조사 안테나 가이드/원형 설계/CAD 원문 | 원문 치수/적층/급전 범위를 확인하고 생략값은 미정 유지 |
| [02_RF_Antenna_Papers](<../../../00_REF/PCB RF ANT/02_RF_Antenna_Papers/>) | 논문 원문 | 논문 조건과 실제 프로젝트의 차이를 기록. 논문 결과를 현재 계산 결과로 사용하지 않음 |
| [03_RF_Antenna_Materials_Theory_Tools](<../../../00_REF/PCB RF ANT/03_RF_Antenna_Materials_Theory_Tools/>) | 물성/이론/도구/측정 자료 | 시험법/방향/주파수/모델 및 원문 무결성 확인 |
| [04_RF_Antenna_Extracted_Data](<../../../00_REF/PCB RF ANT/04_RF_Antenna_Extracted_Data/>) | 안테나 수집 출처 색인, 형상/재료/식/검증 방법 추출 | locator와 원문을 함께 확인. 추출값만으로 전체 형상/물리 재현을 선언하지 않음 |
| [05_PCB_Dielectric_Data_2026](<../../../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026/>) | 제조사/제작사 관측값, 적층, 원문, 검색 텍스트, Excel/JSONL | 관측행과 독립 재료 수 구분. null/범위/충돌/Process-Design Dk 보존 |
| [자료 사용 안내](<../../../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026/docs/자료_사용_안내.md>) | 분석된 자료의 적용 지침 | simulation_ready 상태와 실제 납품 보장 구분 |
| [자료 검토 결과](<../../../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026/docs/자료_검토_결과.md>) | 수집/분류/추출의 당시 감사 | 옛 앱 구현 상태와 현재 기능은 별도 |
| [수집 당시 감사](<../../../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026/audit/collection/README.md>) / [정본 감사](<../../../00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026/audit/current/README.md>) | 당시 수량/파일명과 현재 정본 매핑 | 과거 경로/수치를 새 값으로 소급 변경하지 않음 |
| [현재 제품의 연구/분석](../research/README.md) | 실제 채택 조건/탐색 모델/원시 실행/수렴/실패 | 원문 사실, 사용자 가정, 계산/수렴/실측 상태 각각 표시 |

## 이번 확인과 남긴 문제

참고 안내 10개 Markdown과 6개 README 텍스트의 본문을 검토했다. 1,159개 PDF는 파일 목록/출처 연결을 확인한 범위이며 모든 페이지/그림/수식을 재검증하지 않았다. 추출 텍스트의 전체 파일 읽기/구조 목록과 전문 내용의 판정도 구분한다.

보존 출처와의 읽기 전용 비교는 [분석 검토 기록](../review/analysis_review.md)의 정확한 검사 범위를 따른다. 유전 자료의 1,701개 출처 참조/1,682개 고유 파일, 37개 JSONL/57,340 관측행의 정본 digest와 원문 연결을 확인했다. JLC 관측은 별도 API snapshot을 통하는 구조이므로 최상위 manifest와 단순 문자열 비교로 손상 판정하지 않는다.

안테나 원문 HTML 14개는 작업트리 CRLF와 정본 LF 바이트를 구분해야 한다. `KEYSIGHT_NETWORK_ANALYSIS_HTML` 1개는 보존 source hash와 작업트리/HEAD/LF 비교값이 모두 다르다. 해당 자료는 **출처 무결성 검토 대기**로 관리하고 새로운 측정/교정 설계 근거로 채택하기 전에 원인을 확인한다. 기대 해시를 현재 파일 값으로 바꾸어 일치시키지 않는다. 실제 경로와 기대/관찰 hash는 검토 기록에 남겼다.

G004/G005/G020/G021의 충돌, G030의 누락과 G031의 부분 기하도 원문 자료의 열린 조건이다. 문헌 카드와 소프트웨어 편집/저장 작업은 계속할 수 있지만 누락값을 임의로 채워 문헌 재현 완료나 실측 정확도 합격으로 표시하지 않는다.
