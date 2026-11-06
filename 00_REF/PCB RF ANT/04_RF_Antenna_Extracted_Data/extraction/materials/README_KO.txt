RF PCB 재질 수치 데이터 추출 — 1차 구조화 릴리스

1. 산출물과 범위
- materials.json / materials.csv: 주파수·조건별 유전특성 레코드 3,160개.
  수치 출처 22건: Isola 실제 construction HTML 2건, Panasonic 데이터시트 9건,
  Rogers·AGC·DuPont·Isola 대표값/이방성 자료 11건.
- material_auxiliary.json / material_auxiliary.csv: 보조 레코드 41개.
  구리 표면 거칠기 35개 행과 표준 두께/패널/클래딩 표 6개.
- material_evidence.json: 출처별 SHA256·판본·원문 표/행, 추출 방법, 처리 이슈,
  31개 재질 원문 전부의 coverage, 검증 결과, 증거 1,025개.
- material_coverage.csv: 재질 원문 31건의 추출 범위와 보류 사유.
- build_materials.py: 실제 확보 파일에서 재생성하는 코드. 원문 파일을 수정하지 않음.

2. construction 추출 결과
- Astra MT77: 코어 9행 + 프리프레그 5행, 각각 5주파수 = 70 레코드.
- FR408HR: 코어 30행 + 프리프레그 14행, 각각 6주파수 = 264 레코드.
- Panasonic: R-579Y, R-5795, R-5785(GN/GE), R-5785(N), R-5775(K/G),
  R-5725S, R-1755V, R-1766(GH), R-5775(N)의 해당 코어·프리프레그
  모든 construction 표에서 2,776 레코드.
- 합계 construction 레코드 3,110개. 같은 조건의 Dk/Df가 모두 쌍으로 존재함.
- 나머지 50개는 조건이 구분된 대표값, process/design Dk, 이방성 실험 시편 값.

3. 사용 단위와 중요한 열
frequency_hz: 실제 표에 적힌 측정/표기 주파수(Hz).
frequency_min_hz / frequency_max_hz: Rogers design Dk처럼 범위 평균으로 제시된 경우.
  이때 frequency_hz는 null이다. 임의의 대표 주파수로 바꾸지 않았다.
dk / df: 무차원 상대 유전율 / loss tangent.
dk_kind: process, design, manufacturer_typical. process와 design을 혼합하지 않는다.
thickness_*: 원문 표의 두께. actual, nominal, typical 구분은 thickness_basis에 있다.
  원문 inch와 mm가 반올림 차이로 일치하지 않아도 원문 그대로 보존했다.
  프리프레그 um -> mm 변환만 단위 변환으로 수행했다.
construction / glass_style / ply_count / resin_content_percent:
  실제 유리섬유 구조, 적층 수, 수지 함량을 보존한다. 혼합 유리섬유 구조의 ply_count는
  단일 숫자로 억지 변환하지 않고 construction과 증거 셀에 원문을 남긴다.
source_locator: PDF의 물리 페이지 번호와 표/행 또는 HTML 표/행. 모두 1부터 센다.
  인쇄된 쪽 번호와 PDF 물리 페이지가 다를 수 있다.
evidence_ids: material_evidence.json의 해당 원문 증거와 연결되는 ID.
requires_review / record_flags: 자동 선정 단계에서 보류할 자료와 이유.

4. 자동 선정 시 보류해야 하는 27개 레코드
- Panasonic R-579Y 및 R-5795: 각 10개(총20개) 레코드의 construction이 해당
  2024년 판본에서 개발 중(*)으로 표시되어 있다. availability와 record_flags에 보존.
- RO4730G3, 2.5GHz Df: 원문 p1 설명은 0.0022, p2 속성표 병합 셀은 0.0028이다.
  데이터는 p2 표값 0.0028을 보존하되 requires_review=true와
  conflicting_source_values_vendor_confirmation_required를 부여했다.
  제조사 확인 전 자동으로 확정값으로 선택하지 않는다.
- RT/duroid 5870 이방성 6개: 생산 재질의 보증된 유전 텐서가 아니라, 얇은 재료로 만든
  실험 블록의 방향별 시편 측정값이다. 약10GHz라는 조건도 별도 플래그에 보존했다.
requires_review=false는 안테나 성능 검증 완료를 뜻하지 않는다.

5. 원문/추출상의 예외
- R-5620S 프리프레그, 1080, RC67%, 1MHz의 Dk는 원문에 '3,56'으로 인쇄되어 있다.
  렌더된 원문을 확인하여 소수점 쉼표로 읽고 3.56을 저장했다. 원문 문자열과 변환 이력을
  evidence 및 record_flags에 보존했다.
- 일부 PDF의 미세한 벡터 선 때문에 숫자 셀이 잘리거나 합쳐졌다. 실제 셀 경계와
  좌표를 이용해 복구하고, 원 추출 셀·복구 문자열·bbox를 기록했다.
- Rogers 구리 거칠기 표의 µm 글리프가 텍스트 추출에서 mm로 나오는 문제가 있었다.
  렌더된 원문을 보고 마이크로미터임을 확인했다. 원문 텍스트도 함께 보존했다.
- Isola construction 표의 시험방법은 표에서 다시 명시하지 않는다. generic 데이터시트의
  방법을 모든 construction/주파수로 자동 전파하지 않아 해당 method 열은 null이다.
- source_revision은 HTML construction 표와 generic PDF 데이터시트를 별개로 취급한다.
- Pyralux 대표값은 Table3의 AP9121에만 연결한다. 모든 AP 제품으로 일반화하지 않는다.

6. 숫자 포인트를 만들지 않은 원문 8건
제작공정 4건(RO47, RO3000/3200, RT/duroid, TLY-5), PIM 가이드 1건,
stripline 폭/설계식 2건, 재질 선택 가이드 1건은 원문과 용도를 유지했다.
각 문서의 공정 레시피·도표·곡선·선택 가이드 전 제품을 수치화했다는 뜻은 아니다.
특히 Rogers 선택 가이드에만 등장하는 추가 grade는 이번 대표값 DB에 아직 정규화하지 않았다.
구리 포일 문서는 materials.csv에 Dk/Df 행이 없지만 보조 데이터에 32개 수치 행이 있다.
재질 원문 미확보 때문에 빠진 문서는 없다.

7. 프로그램 구현 시 적용 원칙
- 주파수만으로 재질을 선택하지 말고 grade, glass style, resin content, 경화 후 두께,
  시험방법, copper 조건, 판본을 함께 고른다.
- FR-4라는 이름에 하나의 유전율을 부여하지 않는다.
- 이 데이터에는 보간·외삽·임의 scaling·누락 값 추정이 없다.
- 누락값은 JSON null / CSV 빈칸이며 0이 아니다.
- 구리 Sq/Sa/Sz/Ra/Rz는 다른 지표다. Sq 숫자를 Huray 구 반경으로 직접 대입하지 않는다.
- 수치의 주파수 범위 밖으로 임의 확대하지 않는다. 재질 파일의 가장 높은 주파수는
  RO3003G2 design Dk의 77GHz이며 모든 재질에 이 범위를 보장하는 것은 아니다.
- 실제 안테나 설계에는 전체 GND·층 구조·솔더마스크·주변 금속과 케이스·급전/매칭을
  포함한 전자기 해석, 제조 시편 측정, 최종 상태 검증이 별도로 필요하다.

8. 재생성
Python 3.12 환경에서 PyMuPDF 1.26.6, lxml 6.1.1로 실행/검증했다.
python build_materials.py --corpus-root /path/to/rf_antenna_corpus
corpus-root에는 package/catalog.json과 원문 package/files/...가 있어야 한다.
초기 수집 환경의 research 대체 경로도 fallback으로 지원한다.
코드는 이번 추출에 사용한 원문 SHA256을 고정한다. 다른 판본으로 파일을 교체하면
자동으로 기존 수치를 재사용하지 않고 중지한다. 판본 변경 시 재검토 후 갱신한다.
검증은 출처 SHA, 표 개수/행 개수, Dk/Df 조건별 짝, 숫자 범위, 증거 연결,
중복 조건의 값 충돌, 31개 문서 coverage를 확인한다.
이는 원문 추출의 검증이며 제조사 물성의 독립 실측 검증은 아니다.
