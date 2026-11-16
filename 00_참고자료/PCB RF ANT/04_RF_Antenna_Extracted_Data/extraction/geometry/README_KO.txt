PCB RF 안테나 형상 데이터 추출 v1 — 2026-11-07

범위
이 데이터는 원문·CAD에서 실제 수치를 읽은 29개 사례와, 수치 없는 ADI 원호 개념/Qorvo UWB 요구조건 2개 레코드를 담습니다.
전체 확보 문헌의 모든 형상을 추출했다는 뜻이 아닙니다. 31개 레코드, 348개 수치 행, 23개 출처입니다.
독립 EM 시뮬레이션/실물 측정은 수행하지 않았습니다. 성능은 모두 source_reported_only입니다.

파일
geometries.json: 기판·접지·급전·매칭·적용 조건·검증 관찰·출처 충돌까지 포함한 원본 구조화 데이터.
geometry_parameters.csv: 수치 한 개당 한 행. UTF-8 BOM. 원단위와 mm 환산값 모두 포함합니다.
geometry_records.csv: 사례별 요약, 치수 개수와 미해결 조건.
evidence_index.csv: 물리 PDF 페이지/그림·표와 선택 도면 렌더링 연결.
qa.json: 파일·숫자형·페이지 범위 점검 및 해소할 충돌 목록.
program_schema_proposals.json: 향후 프로그램 입력 항목 제안. 문헌에서 검증된 수치와 섞지 않습니다.
build_geometry.py: 원문 목록을 참조하여 JSON/CSV/QA를 재생성합니다. 실행 위치와 무관합니다.
source_text/: 추출에 참고한 PDF 텍스트. 그림의 숫자·수식은 원본 PDF/렌더링이 우선입니다.
evidence/: 실제 페이지의 렌더링과 Nordic 중첩 ZIP 인벤토리.

단위·페이지 규칙
physical_pdf_page는 1부터 세는 실제 PDF 페이지입니다. 학술지 인쇄 페이지, 학위논문 내부 페이지와 다를 수 있습니다.
SILABS_AN1088의 원단위는 inch입니다. 정규화에서만 정확히 25.4 mm/inch를 적용합니다.
Newton egg의 s는 원문 스케일 인자로 보존했으며 일반 길이 단위처럼 자동 환산하지 않습니다.
프로그램 생성용 완전한 연결 동박 폴리곤은 아직 없습니다. automatic_cad_generation_ready는 전부 false입니다.
dimensioned_reference는 수치 참조 사례라는 뜻이며 자동 생산 가능한 CAD나 검증 완료 안테나라는 뜻이 아닙니다.

주요 확인 사항
G004/G005 TI DN023: L6 표 값 17 mm, 문맥상 권고 9/1 mm, 측정 도표 11/3 mm를 각각 보존했습니다. 한 값으로 합치지 않습니다.
G020 PAPER-065: 원문 FR4 tanδ=0.018(물리 p.2)와 0.18(물리 p.3)가 충돌합니다. 임의 수정하지 않았습니다.
G021 PAPER-023: 개방 원호 WLAN 논문입니다. W1/L1 및 strip/gap 서술이 앞뒤에서 달라 치수 충돌 검토가 필요합니다.
G029 PAPER-066: CPW disc의 측정 외곽 대역은 2.84–15.17 GHz지만 7 GHz 부근 S11=-9.6 dB의 예외가 있습니다. 연속 -10 dB 대역으로 표시하지 않았습니다.
G030 PAPER-066: CPW elliptical slot의 수치표는 확보했지만 입력 CPW의 W1/g 값은 해당 표에 없어 CAD 재생성에는 추가 확인이 필요합니다.
G031 Nordic PCA20006: rev1.0.0/PCB400059 GTL의 원호 반지름 약9.11993 mm, 폭1.27 mm, CCW sweep112.53463° 등을 실제 Gerber 좌표로 추출했습니다. 원형 본체 약20 mm와 돌출 탭/커넥터를 구분했습니다. 전체 GND·net·stackup 재구성은 남아 있습니다. 사진에서 지름을 추정하지 않았습니다.
G031의 최상위 출처는 ZIP이므로 physical_pdf_page는 null입니다. embedded_source에 내부 PDF 페이지/파일 SHA와 Gerber 줄 범위가 있고, derivation_status는 좌표 원값/계산 결과/내부 PDF 수치를 구분합니다.
G018/G019 Liang closed ring/disc는 G021/G027/G031 open arc와 별도 토폴로지입니다.
G025 NXP NFC는 공식 도구 화면에 게시된 계산 예제이며 측정 결과가 아닙니다.
G024 GNSS patch는 논문 자체가 실험 검증을 미래 과제로 남겼습니다.

활용 순서
1. 원하는 topology를 선택하고 원문 조건과 미해결 필드를 확인합니다.
2. 재질 grade/주파수별 Dk·Df와 실제 PCB stackup, GND, 케이스/배터리를 연결합니다.
3. 참조 도면을 연결된 2D/3D 형상으로 재구성하고 원본 CAD/도면과 대조합니다.
4. EM 모델, 포트/경계/메시, 공차·환경 sweep을 만든 뒤 VNA와 방사 측정으로 확인합니다.
이 파일의 수치와 성능을 주파수 비례나 임의 FR4 상수만으로 일반화하지 마십시오.
