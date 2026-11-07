# 기존 자료, 변수 사전, 원문 근거 연계 설계

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

## 1. 현재 존재하는 기준 자료

현재 저장소에는 00_REF의 원문, 추출 자료와 01_Docs의 Markdown 설계가 있다. A 원본 JSON `00_baseline_A_consolidated.json`과 과거 최종 통합 registry는 현재 없다. A의 요구와 입력 의미는 현존 Markdown에서 추적하며 원본 JSON 전체 보존 또는 원본과의 byte 일치를 주장하지 않는다. [B 원문](23_RFAD_원본_추가_요구사항.md)은 읽기 전용 기준 자료로 보존한다.

아래 경로는 01_Docs에서 접근 가능한 현존 파일이다. 2026-11-07 KST 문서 검토에서 JSON의 실제 배열과 CSV 데이터 행을 읽어 수를 확인했다. 이 집계는 내용의 물리적 정확도, 원문 전체 hash 또는 제품 실행을 검증한 결과가 아니다.

| 현존 파일 | 직접 확인한 내용 |
| --- | --- |
| [geometry/geometries.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/geometry/geometries.json) | geometries 배열 31개 |
| [geometry/geometry_parameters.csv](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/geometry/geometry_parameters.csv) | header를 제외한 추출 파라미터 348행 |
| [materials/materials.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/materials/materials.json) | records 배열 3160개. 제품/구성/시험 조건/주파수별 행 |
| [materials/material_auxiliary.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/materials/material_auxiliary.json) | records 배열 41개 |
| [validation/conditions.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/validation/conditions.json) | records 배열 47개 |
| [validation/validation_methods.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/validation/validation_methods.json) | records 배열 26개. 제품 시험의 실제 실행 결과와 구분 |
| [validation/model_formulas.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/validation/model_formulas.json) | records 배열 19개. RFAD EQ 정의와 자동 동일시하지 않음 |
| [source_coverage.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/source_coverage.json) | 출처 상태 241행. 확보/색인/추출 상태는 각 필드로 구분 |
| [DATASET_SUMMARY.json](../00_REF/PCB%20RF%20ANT/04_RF_Antenna_Extracted_Data/extraction/DATASET_SUMMARY.json) | 추출 당시 요약. 238 원문/8443 PDF쪽 등의 과거 집계를 현재 재검증 결과로 재사용하지 않음 |

전체 텍스트 검색용 SQLite, 페이지 JSONL.gz, geometry evidence 이미지도 extraction 아래에 존재한다. 모든 문헌의 수치가 전수 추출되었다는 뜻은 아니며, source_coverage의 0행은 값의 부재와 미추출을 구별해야 한다. 원문 파일 존재 및 hash 확인은 레코드 집계와 별도다. 이전 workspace의 절대경로는 source ID와 현존 상대경로/URL을 이용해 해석하며 없는 파일을 증거로 표시하지 않는다.

## 2. importer 처리

읽기->schema 식별->원본 hash 기록->source ID namespace 분리->단위/원문표기 보존->중복/충돌 검출->조건/유효 범위 부착->사용자 라이브러리에 저장 순서다. 원본 JSON을 바로 active design default로 적용하지 않는다. material 제품명만으로 3160개 행을 평균하거나 같은 물성으로 축약하지 않는다.

원본 `typical_not_guaranteed`, `requires_review`, 미확인, 누락, 추정, 자료의 조건부 적용 flag를 도메인의 status/provenance로 매핑한다. 원문 mm/inch 반올림 차이는 그대로 보존하고 적용 단위, 선택 근거를 기록한다. Dk의 시험법이 construction 표에서 반복되지 않았으면 일반 datasheet의 시험법을 모든 행에 무조건 채우지 않는다.

유전율, 손실과 전도도 등은 사용자가 직접 입력하거나 조건을 확인한 재료 레코드에서 선택하는 변수다. 최초 IFA 기준의 FR-4 표기는 재료 계열을 선택한 것이며 특정 제품의 Dk/Df를 정한 것이 아니다. 사용자가 선택한 값의 snapshot, 주파수/온도/시험법/출처 및 추정 상태를 유지하고, 자료 갱신 시 기존 실행의 값을 소급 변경하지 않는다. 실제 재료 미확정 상태의 편집/저장과 명시적 가정 모델의 탐색 범위는 [08번 데이터 모델](08_RFAD_데이터_모델과_파일_형식.md)을 따른다.

## 3. 데이터 충돌과 사례

- TI DN023의 L6 등 서로 다른 문맥의 치수는 하나의 정답으로 덮어쓰지 않는다. 원형상/개조/주파수 조건을 붙인다.
- RO4730G3 Df 등 서로 다른 판본/표 값은 revision, 조건, 선택 이유를 유지한다.
- PAPER-065의 소수점 의심 값은 검토 flag가 해결되기 전 기본 물성으로 승격하지 않는다.
- copper Sq와 Ra/Rz, Huray sphere radius는 서로 다른 정의다. 근거 없는 단일 um 변환은 하지 않는다.
- 과거 MODEL record의 역사적 Yee 식은 현재 solver에 바로 입력할 구현식이 아니다. 현행 EQ와 adapter에서 실제 안정성 조건을 검토한다.

위 항목은 이전 추출 레코드의 known issue를 보존하는 정책이다. 더 나은 원문을 확보하면 source version과 수정 이력을 남기고 갱신한다.

## 4. G031 원호의 사용 범위

G031은 Nordic PCA20006 원본 Gerber에서 추출한 원호 geometry fixture다. 중심선 반지름 약 9.119930 mm, 선폭 1.27 mm, 시작각 약106.870431 deg, CCW 전개각 약112.534634 deg, 원호 중심선 길이 약17.912454 mm 등의 값은 해당 원문과 grid precision에 종속한다. 전체 기판 외곽에는 원형 본체 이외의 tab이 있으므로 body reference diameter와 실제 outline을 구분한다.

full stackup/ground/environment가 완비된 RF 성능 재현 프로젝트라고 취급하지 않는다. feed stroke와 원호의 겹침, 끝점 quantization, actual net 연결을 보존한다. 이 fixture의 geometry 변환 검증과 별도 canonical antenna의 EM, 실측 검증을 분리한다. 물성, 배터리 조건을 임의 설정한 예제를 원본 비콘의 성능으로 표시하지 않는다.

R1 검증은 완전한 참조 계산 사례를 먼저 확인한 뒤 물성이 완비된 단일포트 IFA를 첫 제품 사례로 진행하고, 원호 단일포트도 별도로 검증한다. 최초 IFA의 대역/외형/적층 목표/급전은 [21번 IFA 초기 검증 기준](21_RFAD_사례와_계약.md#ifa-initial-baseline)로 채택했다. 실제 재료 물성과 상세 제작/측정 조건은 후속 확정한다. 이 초기 기준은 G031 또는 벤더 원본의 재현 조건이 아니며 모든 프로젝트의 강제 기본값도 아니다. 현존 source나 G031의 치수를 자동 기본값으로 삼아 미정 물성을 채우지 않는다. R1의 Windows 11 x64 wxMSW/local WSL2 내부 검증용 배포에서도 기하 재현과 전력/방사 성능 검증의 증거 수준을 분리한다.

## 5. 템플릿 승격

`source_record -> dimensions_reviewed -> geometry_reproduced -> complete_physical_model -> solver_reproduced -> numerically_converged -> independently_compared -> measured_correlated` 단계를 별도 evidence로 관리한다. 지원 주파수/보드 크기/재질/port/environment envelope를 함께 저장한다. 어느 한 단계가 다른 조건의 검증까지 뜻하지 않는다.

## 6. 최종 입력 사전

A의 136개 의미 항목을 유지하고 B의 세부 제조/출력/스윕 계약을 PAR-137~162로 명시했다. 총162개는 UI 입력칸 수나 모든 프로젝트의 mandatory field 수가 아니다. 반복 layer/port/object와 각 Quantity의 공통 속성은 별도 반복된다. 명세상 상세 구조는 [데이터 모델](08_RFAD_데이터_모델과_파일_형식.md), 화면 노출은 [UI](05_RFAD_화면과_사용자_경험_설계.md)를 따른다.

현재 입력 계약의 기준은 아래 PAR-001~162 표이다. 과거 최종 parameter_dictionary.json은 제공되지 않으며, extraction/validation/parameter_dictionary.json은 이전 추출 단계의 다른 사전이므로 최종 PAR 사전과 혼용하지 않는다. 후속 기계판독 사전은 이 표와 RFAD 08의 상태/단위 계약을 보존하여 생성하고 ID별 대조한다. 일반 필드의 결측 처리: 해당 계산에 필요하면 미정 상태로 차단하고, 근거 없이 임의값을 넣지 않는다. 특정 stage 표시는 해당 전체 계산 지원의 목표이며 값의 저장과 구조 호환성은 먼저 구현할 수 있다.

| ID | key / 항목 | 단위, 자료형 | 의미와 적용 조건 | 연결 요구 |
| --- | --- | --- | --- | --- |
| PAR-001 | `frequency_bands` - 목표 주파수 대역 | Hz; array[min,max] | 서로 떨어진 복수 대역을 허용하고 min<max 검사; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-002 | `frequency_samples` - 주파수 샘플 | Hz; array[number] | 선형, 로그, 사용자 목록과 실제 결과 격자 구분; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-003 | `protocol_profile` - 통신 프로파일 | 1; object | 이름, 지역, 버전, 출처와 사용자 수정값; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-004 | `reference_impedance` - 포트 기준 임피던스 | ohm; complex or frequency table | 실수 50 ohm을 모든 응용에 강제하지 않음; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-005 | `target_impedance_match` - 정합 목표 | dB or ratio; frequency mask | S11 dB, 반사손실 양수, VSWR 표현과 판정식 구분; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-006 | `target_efficiency` - 효율 목표 | 1; frequency mask | radiation과 total 효율 각각 정의; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-007 | `target_realized_gain` - 실현 이득 목표 | dBi; frequency angle mask | 대역과 방향을 함께 지정; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-008 | `target_polarization` - 편파 목표 | 1; enum or ellipse | 선형, 원형, 타원과 기준 축, 손잡이 규약; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-009 | `target_size_envelope` - 설계 공간 제한 | m; geometry | 보드, 안테나, keepout별 허용 공간; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-010 | `target_power` - 입력 전력 조건 | W; number or waveform | field/손실의 정규화와 동작 시나리오; 모든 프로젝트 | PRJ-001, PRJ-002 |
| PAR-011 | `board_outline` - 실제 보드 외곽 | m; closed curves | 원형 본체와 탭을 포함한 폐곡선; 모든 PCB | CAD-001, CAD-002 |
| PAR-012 | `board_reference_diameter` - 원형 본체 지름 | m; number | 실제 외곽과 별개인 선택적 기준 치수; 모든 PCB | CAD-001, CAD-002 |
| PAR-013 | `board_holes_cutouts` - 홀과 컷아웃 | m; geometry array | 도금 여부, 층 범위, 슬롯 포함; 모든 PCB | CAD-001, CAD-002 |
| PAR-014 | `model_origin_axes` - 원점과 축 | m and rad; transform | 오른손 좌표, 상하층 기준, 출력 좌표계; 모든 PCB | CAD-001, CAD-002 |
| PAR-015 | `stackup_order` - 적층 순서 | 1; layer array | 실제 제작 순서와 층 역할; 모든 PCB | CAD-001, CAD-002 |
| PAR-016 | `layer_thickness` - 층 두께 | m; per-layer number | 공칭, 실측, 공차와 압착 전후 상태; 모든 PCB | CAD-001, CAD-002 |
| PAR-017 | `layer_elevation` - 층의 Z 위치 | m; derived number | 적층 두께에서 유도하고 겹침/공극 검사; 모든 PCB | CAD-001, CAD-002 |
| PAR-018 | `ground_polygons` - 층별 접지 형상 | m; polygon array | 비아 접속과 split ground 포함; 모든 PCB | CAD-001, CAD-002 |
| PAR-019 | `keepout_regions` - 층별 금지 영역 | m; region array | 구리, 부품, 배선, 기계 요소별 구분; 모든 PCB | CAD-001, CAD-002 |
| PAR-020 | `edge_clearance` - 보드 외곽 이격 | m; number or rule | 동박 외곽과 milling tolerance 고려; 모든 PCB | CAD-001, CAD-002 |
| PAR-021 | `trace_centerline` - 도체 중심선 | m; curve path | 직선, 원호, 스플라인 연결; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-022 | `trace_width` - 도체 선폭 | m; number or path profile | 위치별 폭, 테이퍼 포함; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-023 | `trace_path_length` - 도체 경로 길이 | m; derived number | 원호 및 직선 구간의 합이며 공진 길이와 구분; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-024 | `trace_gap` - 도체 간극 | m; number or constraint | meander, CPW, slot 등 구조별 간격; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-025 | `open_end_geometry` - 개방단 형상 | m; geometry | 끝단 라운드, 패드, 확장부; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-026 | `bend_corner` - 굽힘과 코너 | m or rad; object | 곡률, miter, 모서리 형상; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-027 | `copper_net` - 도체 넷 | 1; identifier | 연결 의도를 지정하는 전기 넷; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-028 | `via_geometry` - 비아 형상 | m; object array | 드릴 지름, 패드, anti-pad, barrel, 연결 층; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-029 | `plated_barrel_thickness` - 홀 도금 두께 | m; number | 비아 내벽 두께와 벌크 동박 두께 구분; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-030 | `feed_transition` - 급전 전이 | m; geometry | 급전선, 패드, 불연속, 커넥터 접속; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-031 | `curve_tessellation_error` - 곡선 근사 허용오차 | m; number | polyline/mesh 변환의 최대 chord error; 모든 패턴 | CAD-003, CAD-004, CAD-005, CAD-006 |
| PAR-032 | `arc_center` - 원호 중심 | m; xy point | 보드 중심과 독립 지정 가능; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-033 | `arc_centerline_radius` - 원호 중심선 반지름 | m; number | 외곽/내곽 반지름과 구별; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-034 | `arc_start_angle` - 원호 시작각 | rad; number | 기준 축과 회전 방향 명시; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-035 | `arc_sweep_angle` - 원호 진행각 | rad; number | 개방 원호와 닫힌 loop의 topology 구분; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-036 | `arc_tip_ground_clearance` - 개방단과 접지 간격 | m; number or geometry check | 최근접 거리와 해당 접지 층; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-037 | `ifa_radiating_branches` - IFA 방사 가지 | m; path array | 분기, meander와 개방단; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-038 | `ifa_short_branch` - IFA 단락 가지 | m; path and connectivity | 접지에 실제 연결되는 short; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-039 | `ifa_feed_branch` - IFA 급전 가지 | m; path and port | short와 독립인 feed; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-040 | `ifa_feed_short_spacing` - IFA feed와 short 간격 | m; number | 연결 관계를 바꾸지 않고 조정; open arc monopole 및 IFA | CAD-001, CAD-004 |
| PAR-041 | `material_product` - 재질 제품명 | 1; identifier | 제조사, 등급, 개정, 가용성; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-042 | `material_construction` - 재질 구성 | 1; object | core/prepreg, glass style, resin content, ply; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-043 | `epsilon_r_complex` - 복소 상대 유전율 | 1; frequency table or model | 실수부, 허수부와 시간조화 부호 규약; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-044 | `loss_tangent` - 유전 손실 탄젠트 | 1; frequency table | Dk와 주파수, 시험법 조건을 함께 보존; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-045 | `dk_kind_method` - Dk 종류와 시험법 | 1; object | process/design/실측 값 구분; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-046 | `material_frequency_domain` - 재질 유효 주파수 | Hz; range | 보간과 외삽 판정에 사용; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-047 | `dielectric_dispersion` - 분산 모델 | 1; model and coefficients | Debye/Lorentz/표 기반 모델과 fit 오차, 인과성; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-048 | `dielectric_tensor` - 유전율 텐서 | 1; complex matrix | 각 축 값과 좌표 방향 및 solver 지원; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-049 | `material_temperature` - 온도 및 온도 계수 | K and model; object | 원 데이터 온도, 사용 온도, 적용 모델; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-050 | `material_humidity` - 습도와 흡습 상태 | 1; condition object | 측정 조건과 재질 모델 적용 한계; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-051 | `magnetic_material` - 복소 투자율 | 1; frequency table or tensor | ferrite 등 자성체 선택 시 필요; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-052 | `material_uncertainty` - 재질 공차와 불확도 | various; distribution object | typical/guaranteed, 실측 오차, 상관구조; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-053 | `soldermask` - 솔더 마스크 | m and material ref; layer object | 두께, openings, Dk/Df, 주파수 조건; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-054 | `adhesive_bondply` - 접착층과 bondply | m and material ref; layer object | flex, 커버, 케이스 접착층 포함; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-055 | `air_gaps` - 공극 | m; geometry | 기판, 케이스, 부품 사이 빈 공간; 기판 및 주변 유전체 | PRJ-005, DAT-004 |
| PAR-056 | `copper_thickness` - 동박 두께 | m; per-layer number | base foil과 plating 후 두께를 구분; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-057 | `conductivity` - 전기 전도도 | S/m; number or model | 금속 등급, 온도와 손실 모델; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-058 | `surface_roughness_metric` - 거칠기 지표 | m; metric and value | Ra/Rq/Sq/Rz 및 측정면, 시험법 구분; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-059 | `roughness_model` - 거칠기 해석 모델 | 1; model and parameters | Huray 등 실제 필요한 파라미터와 유효 범위; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-060 | `surface_finish` - 표면처리 | m and material ref; layer array | ENIG 등 선택 시 각 금속 두께와 전도도; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-061 | `etch_bias` - 에칭 편차 | m; distribution | 측벽 테이퍼, 선폭 및 간격 편차; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-062 | `registration_error` - 층간 정렬 편차 | m and rad; distribution | 층별 이동/회전과 상관; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-063 | `fabrication_limits` - 제조 가능 범위 | m; rule set | 최소 선폭/간격/홀/환형링과 업체 개정; 동박 및 도체 | PRJ-005, CAD-001 |
| PAR-064 | `port_type` - 포트 유형 | 1; enum | lumped, wave, coax, microstrip, CPW, 차동; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-065 | `port_location_direction` - 포트 위치와 방향 | m; geometry and vector | 전압 적분선, 접지 기준, 정방향; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-066 | `port_reference_plane` - 기준면 | m; point or plane | EM, 회로, VNA 사이 reference plane; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-067 | `port_modes` - 포트 모드 | 1; mode list | TEM/고차모드, cutoff, 정규화; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-068 | `feed_line_impedance` - 급전선 임피던스 | ohm; complex frequency table | 실제 적층에서 계산/추출한 값; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-069 | `balun_model` - 발룬 모델 | various; network | differential/common mode 및 비대칭 손실; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-070 | `matching_topology` - 정합회로 구조 | 1; netlist | series/shunt, pi/T, 배치와 포트 연결; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-071 | `matching_component` - 정합 소자 | H F ohm; part model | 공차, Q, SRF, 기생, vendor S파라미터; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-072 | `chip_impedance` - 칩 임피던스 | ohm; complex table | 주파수 및 동작/전력 의존성; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-073 | `connector_fixture` - 커넥터와 fixture | m or network; geometry or S-parameter | 기준면과 de-embedding 사용 여부; 포트 기반 안테나 | CAD-004, CAD-006, PRJ-001 |
| PAR-074 | `enclosure_geometry` - 케이스와 radome | m; solid array | 두께, 형상, Dk/Df, 위치; 조립 상태 | CAD-007 |
| PAR-075 | `battery_geometry` - 배터리 | m; solid and material | 금속 외형, 접촉, 배선, 간격; 조립 상태 | CAD-007 |
| PAR-076 | `shields_fasteners` - 차폐물과 고정물 | m; solid array | shield can, 나사, 금속 브래킷; 조립 상태 | CAD-007 |
| PAR-077 | `cable_routing` - 케이블 배치 | m; path and model | feed cable 공통모드와 주변 배선; 조립 상태 | CAD-007 |
| PAR-078 | `assembly_tolerance` - 조립 위치 공차 | m and rad; distribution | 부품 이동, 회전, 간격 변화; 조립 상태 | CAD-007 |
| PAR-079 | `environment_state` - 동작 환경 상태 | 1; named configuration | bare PCB, 최종 조립, 사용 상태 비교; 조립 상태 | CAD-007 |
| PAR-080 | `solver_identity` - 해석기와 버전 | 1; identifier | 엔진, 어댑터, 빌드 옵션; 선택 solver | JOB-001, INT-001 |
| PAR-081 | `analysis_domain` - 해석 영역 | m; bounding geometry | 배경 매질 및 최소 영역 거리; 선택 solver | JOB-001, INT-001 |
| PAR-082 | `boundary_conditions` - 경계 조건 | 1; per-face object | PML, 흡수, PEC, PMC, 주기 및 유효 조건; 선택 solver | JOB-001, INT-001 |
| PAR-083 | `mesh_controls` - 메시 제어 | m; global local rules | 파장뿐 아니라 간극, 곡률, 층, 포트 해상도; 선택 solver | JOB-001, INT-001 |
| PAR-084 | `conductor_model` - 도체 근사 | 1; enum and domain | PEC, 유한 전도체, thin sheet, surface impedance; 선택 solver | JOB-001, INT-001 |
| PAR-085 | `time_step_policy` - 시간 간격 정책 | s; model | FDTD 안정성, 안전계수, 실제 engine 기준; 선택 solver | JOB-001, INT-001 |
| PAR-086 | `termination_rule` - 해석 종료 조건 | 1; object | 에너지 감소, 시간, iteration, residual; 선택 solver | JOB-001, INT-001 |
| PAR-087 | `convergence_plan` - 수렴 검증 | various; sequence and tolerances | mesh, 영역, 시간, 포트 변화별 관측량; 선택 solver | JOB-001, INT-001 |
| PAR-088 | `nf2ff_surface` - 원거리장 변환면 | m; closed surface | 구조 포함 및 비균일 매질/경계와의 관계; 선택 solver | JOB-001, INT-001 |
| PAR-089 | `field_sampling` - 전자기장 샘플 | Hz m s; sampling grid | 주파수, 시간, 공간 영역과 저장 용량; 선택 solver | JOB-001, INT-001 |
| PAR-090 | `power_normalization` - 전력 정규화 | W; definition | incident, accepted, radiated, loss 구분; 선택 solver | JOB-001, INT-001 |
| PAR-091 | `solver_capability_override` - 미지원 모델 처리 | 1; policy | 생략 금지, 대체 가정, 사용자 확인 기록; 선택 solver | JOB-001, INT-001 |
| PAR-092 | `optimization_variables` - 최적화 변수 | various; variable bounds | 연속, 이산, 카탈로그 선택과 제약; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-093 | `objective_functions` - 목적함수 | various; expressions | 대역/각도 worst case, 평균, weight 구분; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-094 | `optimization_constraints` - 제약조건 | various; expression list | 제조 가능성, 금지영역, 최소 효율, 다중대역; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-095 | `optimization_budget` - 계산 예산 | s and count; object | 횟수, wall time, 자원, 중단 조건; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-096 | `tolerance_distributions` - 공차 분포 | various; distribution array | 재질, 에칭, 위치, 소자 편차; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-097 | `tolerance_correlation` - 변수 상관 | 1; matrix or model | 독립 가정을 명시하고 유효 행렬 검증; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-098 | `random_seed_samples` - 난수와 표본 | 1; seed and count | 수율 신뢰구간과 재현성; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-099 | `surrogate_domain` - 대리모델 영역 | various; dataset and bounds | 훈련자료, 오차, 외삽, 최종 full-wave 확인; 최적화 실행 | OPT-UI-001, OPT-UI-002 |
| PAR-100 | `uwb_excitation` - UWB 파형 | s V; waveform | 대역, 진폭, window, sampling; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-101 | `uwb_transfer_setup` - UWB 전송 구성 | m and rad; antenna pair configuration | 거리, 정렬, 편파, 전파 지연 제거 조건; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-102 | `group_delay_target` - 군지연 목표 | s; frequency mask | S21 phase unwrap, deep notch 처리; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-103 | `mimo_ports` - 다중 포트 정의 | 1; port list | 포트 순서, 정합 부하, 혼합 모드; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-104 | `ecc_definition` - ECC 계산 정의 | 1; method | 3D 복소장 적분과 S파라미터 근사의 구분; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-105 | `array_layout` - 배열 배치 | m; position array | 간격, 회전, 요소 좌표계; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-106 | `array_excitation` - 배열 급전 | 1 and rad; complex weights | scan angle, amplitude, phase, 주파수; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-107 | `active_impedance` - 능동 임피던스 | ohm; derived array data | 상호결합과 동시 여기 조건; UWB WiFi MIMO 및 배열 | PRJ-001, OUT-007 |
| PAR-108 | `coil_turns` - 코일 권수 | 1; integer | 층과 bridge 연결 포함; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-109 | `coil_target_l_q` - 코일 목표 L과 Q | H and 1; frequency targets | Rac, SRF, 부하 상태 별도 정의; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-110 | `coupling_pair` - 상대 코일과 배치 | m and rad; pair geometry | 거리, 횡이동, 기울기, ferrite; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-111 | `coupling_metrics` - 결합 지표 | H and 1; derived data | M, k, 전달 효율과 포트 부하; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-112 | `rfid_chip_state` - RFID 칩 상태 | W ohm; operating table | 입력 전력, 민감도, 복소 임피던스; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-113 | `rfid_match_objective` - RFID 정합 목표 | 1; power transfer target | 50 ohm S11와 구별되는 공액 정합; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-114 | `flex_deformation` - 기판 변형 | m and rad; deformation map | 곡률, 곡면, 층 변형 전후 좌표; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-115 | `body_phantom` - 인체 모델 | m and material ref; phantom configuration | 거리, 조직 모델, 물성 출처, 지원 solver; NFC HF RFID UHF RFID flex | PRJ-001, CAD-009 |
| PAR-116 | `patch_shape_size` - 패치 형상과 치수 | m; geometry parameters | 사각 L/W, 원형 반지름, 다각형 꼭짓점과 층; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-117 | `patch_feed_inset` - 패치 급전 inset | m; position and geometry | inset 깊이, 간극, probe 위치; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-118 | `slot_geometry` - 슬롯 형상 | m; negative geometry | 동박에 뚫린 aperture와 경계의 연결; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-119 | `dipole_arm_geometry` - 다이폴 각 팔 | m; path or region pair | balanced feed, 대칭/비대칭, 각 팔 길이; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-120 | `parasitic_elements` - 기생 및 분기 소자 | m; geometry array | 부유 소자, gap coupling, 분기 연결 구분; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-121 | `uwb_radiator_outline` - UWB 방사체 외곽 | m; parametric shape | disc, ellipse, polygon, bowtie의 개별 치수; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-122 | `partial_ground_geometry` - 부분 접지 | m; region geometry | 접지 끝단, 길이, slot, feed overlap; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-123 | `band_notch_geometry` - 대역 노치 구조 | m; slot or resonator | 제외 대역과 구조 파라미터 연결; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-124 | `taper_profile` - 테이퍼 프로파일 | m; function and domain | Vivaldi 등 지수/사용자 곡선과 aperture, 길이; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-125 | `spiral_profile` - 스파이럴 프로파일 | m and rad; function and domain | 시작, 끝 반지름, 회전수, arm 수, pitch; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-126 | `log_periodic_scale` - 로그 주기 소자 비율 | 1 and m; scale and spacing | 소자 길이비, 간격비, 전체 크기; patch slot dipole taper spiral log periodic | CAD-009 |
| PAR-127 | `measurement_network` - 실측 네트워크 | Hz complex; Touchstone and metadata | 포트 순서, 기준 임피던스, 원본 보존; 검증 프로젝트 | OUT-007, DAT-005 |
| PAR-128 | `calibration_record` - 교정 기록 | 1; object | 교정법, 표준, 날짜, 장비, 기준면; 검증 프로젝트 | OUT-007, DAT-005 |
| PAR-129 | `deembedding_record` - fixture 보상 | 1; network and method | 적용 전후 값, 추정 오차; 검증 프로젝트 | OUT-007, DAT-005 |
| PAR-130 | `measurement_environment` - 측정 환경 | m K; configuration | 조립, 치구, 케이블, 온도, 방향; 검증 프로젝트 | OUT-007, DAT-005 |
| PAR-131 | `measurement_uncertainty` - 측정 불확도 | various; budget | 교정, 반복성, 시설, 기준 안테나 기여; 검증 프로젝트 | OUT-007, DAT-005 |
| PAR-132 | `comparison_acceptance` - 해석 실측 비교 | various; tolerance rules | 동일 기준면, 환경, 대역의 metric별 판정; 검증 프로젝트 | OUT-007, DAT-005 |
| PAR-133 | `synthesis_template_domain` - 초기 합성의 적용 범위 | various; template and constraints | 대역, 적층, 공간, 유효 모델과 후보 실패 사유; 지원 템플릿 및 선택 확장 | SYN-001, SYN-002, MEAS-001, TUNE-001 |
| PAR-134 | `matching_search_space` - 정합 구조 탐색 범위 | 1; topologies and part catalogue | 부품수, 회로 구조, 시리즈, 허용 손실, 공차; 지원 템플릿 및 선택 확장 | SYN-001, SYN-002, MEAS-001, TUNE-001 |
| PAR-135 | `instrument_connection` - 측정 장비 연결 | 1; adapter and session metadata | 장비 식별, 포트, 교정 상태, sweep와 측정 개정; 지원 템플릿 및 선택 확장 | SYN-001, SYN-002, MEAS-001, TUNE-001 |
| PAR-136 | `reconfigurable_states` - 재구성 제어 상태 | 1; state and control table | RF switch, tuner 코드별 회로, 모델, 성능 및 실측 연결; 지원 템플릿 및 선택 확장 | SYN-001, SYN-002, MEAS-001, TUNE-001 |
| PAR-137 | `cad_exchange_tolerance` - CAD 변환 허용오차 | m; positive number | CAD/STEP의 위치, 경계, 단면 비교 허용치. 물리 제조공차와 분리; 해당 기능 사용 시 | OUT-004, OUT-006 |
| PAR-138 | `vector_exchange_tolerance` - 2D 출력 허용오차 | m; positive number | 곡선 근사/좌표 양자화와 roundtrip tolerance budget; 해당 기능 사용 시 | OUT-001, OUT-006 |
| PAR-139 | `manufacturing_dimensional_tolerance` - 제조 치수 공차 | m or ratio; bounded distribution | 제조사, 공정, lot별 width/height/registration 변동. tauCAD와 구분; 해당 기능 사용 시 | PHY-022, PHY-077 |
| PAR-140 | `export_profile` - 교환 파일 profile | 1; object | format/schema/tool version, units/origin, included bodies/layers, fusion/fill/omissions; 해당 기능 사용 시 | OUT-009, OUT-005 |
| PAR-141 | `drawing_profile` - 도면 용지, 축척, 뷰 | m,ratio; object | 용지/도면scale와1:1제조geometry를 구분. title block/revision/views; 해당 기능 사용 시 | OUT-001 |
| PAR-142 | `board_total_thickness_convention` - 보드 총두께 포함 범위 | m; object | dielectric-only/copper outer faces/mask inclusive 범위와 layer sum; 해당 기능 사용 시 | PHY-023 |
| PAR-143 | `base_copper_thickness` - 도금 전 기본 동박 두께 | m; positive quantity | finished copper와 별도. oz 환산의 provenance를 저장; 해당 기능 사용 시 | PHY-029 |
| PAR-144 | `finished_hole_diameter` - 완성 구멍 직경 | m; positive quantity | PTH/NPTH 완성 bore. drill tool과 자동 동일시하지 않음; 해당 기능 사용 시 | CAD-001, PHY-022 |
| PAR-145 | `drill_tool_diameter` - 드릴 공구 직경 | m; positive quantity | 제조 공정의 tool diameter와 공차/보정 근거; 해당 기능 사용 시 | OUT-002, PHY-022 |
| PAR-146 | `via_fill_model` - 비아 충진과 배럴 모델 | 1; enum/object | hollow/copper/resin/unknown fill과 plating, 물리/해석표현 구분; 해당 기능 사용 시 | CAD-004, OUT-004 |
| PAR-147 | `via_layer_span` - 비아 종류와 층 범위 | 1; object | through/blind/buried/microvia 및 start/end layer. profile별 지원 검사; 해당 기능 사용 시 | CAD-004, PHY-023 |
| PAR-148 | `pad_geometry` - 패드, 환형 링 형상 | m,rad; object | shape/center/size/rotation/layers/net/annular-ring 규칙; 해당 기능 사용 시 | CAD-006, PHY-022 |
| PAR-149 | `via_antipad_and_stub` - 비아 antipad와 stub | m; object | 비연결층 개구 및 미사용 배럴 구간, 생략 시 근거; 해당 기능 사용 시 | CAD-004, PHY-043 |
| PAR-150 | `mask_opening_expansion` - 마스크 개구 확장 | m; quantity/regions | mask coverage, 무마스크 안테나 영역, 개구 geometry; 해당 기능 사용 시 | PHY-032, OUT-002 |
| PAR-151 | `conductor_cross_section` - 동박 단면, 도금 층 | m,rad; object | 사다리꼴/undercut/측벽/finish layers. 미지정은 정밀 공정 형상으로 표시 금지; 해당 기능 사용 시 | PHY-029, PHY-031 |
| PAR-152 | `source_grid_and_output_quantization` - 원본 grid와 출력 분해능 | m; object | 원본 좌표 grid, writer precision, chord error를 따로 보존; 해당 기능 사용 시 | CAD-005, OUT-006 |
| PAR-153 | `assembly_variant_bom` - 정합 BOM, 실장 변형 | 1,m,rad; object | 회로/MPN/footprint/DNP/value와 placement/side/variant 대응; 해당 기능 사용 시 | AUG-004, SYN-002 |
| PAR-154 | `explicit_sweep_plan` - 명시적 파라미터 스윕 | parameter units; object | 변수 ID, 값목록, 조합규칙, seed, budget, candidate 기록; 해당 기능 사용 시 | AUG-001 |
| PAR-155 | `adaptive_frequency_plan` - 적응형 주파수 평가 | Hz; object | 초기grid, 추가점 규칙, 최대gap, error target, 실제solve/DFT/interpolation 구분; 해당 기능 사용 시 | AUG-002 |
| PAR-156 | `inverse_design_representation` - 자유형상 탐색 표현 | m,1; object | polygon/pixel/level-set representation, feature filter, connectivity, verified gradient status; 해당 기능 사용 시 | AUG-003 |
| PAR-157 | `display_precision_policy` - 표시 단위와 정밀도 | 1; object | 입력, 저장 수치와 화면 반올림 분리. 단위 없는 입력의 context 표시; 해당 기능 사용 시 | PRJ-005, PRJ-010 |
| PAR-158 | `expected_connectivity` - 기대 전기 연결 | 1; graph | expected net edges/intentional gaps/floating conductors/contact. 기계 접촉과 구분; 해당 기능 사용 시 | CAD-004, PHY-012 |
| PAR-159 | `material_record_status` - 재질 출처, 사용 상태 | 1; object | 원본값 상태/소비 여부/충돌/version pin. scalar 물성 자체와 별도 metadata; 해당 기능 사용 시 | DAT-003, DAT-004, PHY-036 |
| PAR-160 | `target_beamwidth_direction` - 빔폭, 방향 목표 | rad; object | cut/coordinate/주엽/영역과 sampling을 정의; 해당 기능 사용 시 | PHY-059, PRJ-001 |
| PAR-161 | `target_port_isolation` - 포트 격리 목표 | dB; object | ordered port pair, termination/wave/Z0와 평가 band; 해당 기능 사용 시 | PHY-065, PRJ-001 |
| PAR-162 | `target_bandwidth` - 절대, 비율 대역폭 | Hz,ratio; object | 판정 threshold와 reference frequency/분모, continuous vs sampled domain; 해당 기능 사용 시 | PHY-061, PRJ-001 |

## 7. B의 79개 입력 묶음 대응

표는 각 B 입력 묶음을 최종 semantic entries에 연결한다. B의 상세 검증 규칙은 함께 보존하며 mapping은 일대일 field 합산이 아니다. 원문 전체와 아래 대응표를 함께 확인한다. parameter_crosswalk.json은 후속 생성 대상이며 현재 파일로 가정하지 않는다.

| 원본 B ID | 입력 묶음 | 최종 ID | 보존한 상세 조건 |
| --- | --- | --- | --- |
| B::PAR-TGT-001 | 대역 시작과 종료 및 기준 주파수 | PAR-001 | 시작보다 종료가 커야 하며 기준 주파수의 의미를 설계 주파수 또는 평가 주파수로 구분한다 |
| B::PAR-TGT-002 | 주파수 간격과 샘플 수 | PAR-002, PAR-155 | 고정 간격, 사용자 목록 및 적응형 규칙을 구분하고 실제 계산 주파수 목록을 결과와 저장한다 |
| B::PAR-TGT-003 | S11 또는 Return loss 한계 | PAR-005 | 음수 S11 dB와 양수 Return loss의 부호 규약을 명시한다 |
| B::PAR-TGT-004 | VSWR 한계 | PAR-005 | 포트 기준과 단일 또는 다중포트 의미를 명시하고 입력값 1 미만을 허용하지 않는다 |
| B::PAR-TGT-005 | 절대 및 비율 대역폭 목표 | PAR-162 | 대역폭의 판정 임계값과 비율 분모를 함께 저장한다 |
| B::PAR-TGT-006 | 이득 및 실현 이득 목표 | PAR-007 | 최대값, 지정 방향 또는 영역 평균 및 편파를 선택하고 정합 손실 포함 여부를 명시한다 |
| B::PAR-TGT-007 | 방사 및 전체 효율 목표 | PAR-006 | 두 효율의 분모와 포함 손실을 구분하며 수치 오차 범위를 별도 표시한다 |
| B::PAR-TGT-008 | 관측 방향과 빔폭 | PAR-160, PAR-089 | 좌표계와 각도 정의, 주엽 및 절단면을 저장한다 |
| B::PAR-TGT-009 | 축비와 교차 편파 한계 | PAR-008 | 관측 방향 및 RHCP LHCP의 관측 규약을 기록한다 |
| B::PAR-TGT-010 | 포트 간 격리도 목표 | PAR-161, PAR-103 | 송신 및 수신 포트 순서와 나머지 포트의 종단을 저장한다 |
| B::PAR-TGT-011 | 최대 사용 면적과 높이 | PAR-009 | 안테나 도체, keep out 및 보드 면적을 구분한다 |
| B::PAR-TGT-012 | 목표 가중치와 우선순위 | PAR-093, PAR-094 | 제약조건과 목적함수를 구분하고 가중치 변경을 이력에 저장한다 |
| B::PAR-CAD-001 | 길이 단위와 표시 정밀도 | PAR-014, PAR-157 | 단위 없는 입력의 기본 단위를 표시한다. 표시 자릿수와 저장, 계산 정밀도를 구분하고 단위 변환 후 실제 크기가 보존되어야 한다. |
| B::PAR-CAD-002 | 좌표축, 원점, 상하면 방향 | PAR-014, PAR-140 | 설계, 제조, 조립 원점을 식별하고 변환 관계를 기록한다. 앞뒤 방향과 미러링을 명시하여 출력 중 의도하지 않은 반전을 막는다. |
| B::PAR-CAD-009 | 구간별 도체 선폭과 테이퍼 | PAR-022, PAR-124 | 방사체, 급전선, 정합부에 개별 폭을 지정한다. 선폭은 해당 위치의 도체 양쪽 경계 사이 횡방향 거리로 정의한다. 폭 변경 시 중심선 또는 기준 경계의 고정 여부를 지정하고 최소 선폭을 검사한다. 가변 폭은 최소, 최대 폭과 테이퍼 규칙으로 정의한다. |
| B::PAR-CAD-010 | 구간 길이와 중심선 총길이 | PAR-021, PAR-023 | 직선과 원호의 실제 기하 길이를 계산한다. 중심선 길이, 투영 길이, 전기적 길이를 구별하고 총길이의 집계 대상을 표시한다. |
| B::PAR-CAD-011 | 급전, 선간, 접지 간격 | PAR-024, PAR-036, PAR-040 | 경계 사이 최소 거리인지 중심선 사이 거리인지 정의한다. 0 또는 접촉은 의도한 연결로 지정한 경우에만 허용한다. |
| B::PAR-CAD-012 | 원호, 굽힘, 모서리 형상 | PAR-026, PAR-031, PAR-032, PAR-033, PAR-034, PAR-035 | 내측, 중심선, 외측 반경을 구별한다. fillet, chamfer 및 곡선 근사 시 최소 간격, 도체 연결, 유효 외곽을 다시 검사한다. 시작각, 전개각과 끝점, miter 보정량을 저장한다. |
| B::PAR-CAD-013 | 반복 수, 피치, 배열 변환 | PAR-105, PAR-108, PAR-125, PAR-126 | 반복 수는 유효 정수로 제한하고 반복 후 충돌, 최소 간격, 연결 상태를 확인한다. 원본과 복사 객체의 변수 연동 여부를 저장한다. |
| B::PAR-CAD-014 | 접지 외곽, 슬롯, 분리 영역 | PAR-018, PAR-118, PAR-120, PAR-122 | 실제 구리와 빈 영역을 구분하고 접지 레이어 범위 및 의도한 연결을 지정한다. 구리 채움 재생성 후 중요 형상 변화를 확인한다. 패치와 방사체의 슬롯, 분기 치수도 개별 변수로 지정한다. |
| B::PAR-CAD-015 | 안테나 keepout | PAR-019, PAR-020 | 구리, 배선, 부품, 기계물의 금지 영역을 구분한다. 상면만인지 모든 층인지 지정하고 제조 출력에서의 표현과 보존 여부를 확인한다. |
| B::PAR-CAD-016 | 패드 형상, 위치, 회전 | PAR-148 | 패드 모양과 크기, 중심, 방향, 연결층 및 네트를 보존한다. 화면 표시용 추가 높이가 물리 두께에 섞이지 않도록 한다. |
| B::PAR-CAD-017 | 네트, 기대 연결 관계 | PAR-027, PAR-158 | 실제 연결, 의도적 분리 및 기생 도체를 구별한다. 네트가 없는 입력 형식에서는 미정으로 두고 사용자가 지정할 수 있어야 한다. |
| B::PAR-RF-009 | 안테나 계열과 기준 템플릿 | PAR-133 | 형상 출처 적용 조건 초기식 가정과 검증 범위를 저장한다. |
| B::PAR-CAD-003 | 보드 외곽과 내부 절개 | PAR-011, PAR-012, PAR-013 | 지원하는 폐곡선과 내부 구멍으로 정의한다. 자기 교차, 열린 외곽, 중복 경계를 검출하고 다중 보드 영역의 지원 범위를 명시한다. |
| B::PAR-CAD-004 | 레이어 ID, 순서, 역할 | PAR-015 | 층 이름, 상하면, 도체, 유전체 역할과 순서를 보존한다. 외부 PCB 레이어와의 대응을 저장하며 이름만으로 높이를 추정하지 않는다. |
| B::PAR-CAD-005 | 층별 Z 위치와 기준면 | PAR-017, PAR-016 | 층의 위, 아래 경계 또는 기준면과 두께를 일관되게 정의한다. 의도하지 않은 재료 간 부피 중첩과 층간 공백을 검출한다. |
| B::PAR-CAD-006 | 보드 총두께와 포함 범위 | PAR-142 | 유전체만의 두께인지 동박 외면까지인지, 마스크, 표면처리를 포함하는지 기록한다. 포함한 층의 두께 합과 불일치하면 알려야 한다. |
| B::PAR-CAD-007 | 유전체층 두께 | PAR-016, PAR-052 | 층별 양수 값, 명목값, 실측값, 공차 및 재료 식별자를 저장한다. 제조사 최종 적층과 설계 적층의 확인 상태를 구분한다. |
| B::PAR-CAD-008 | 층별 기본, 완성 동박 두께 | PAR-056, PAR-143 | base copper와 도금 후 finished copper를 구분한다. oz 표기는 보조 정보로 다루며 적용 두께와 환산, 추정 근거를 확인할 수 있어야 한다. |
| B::PAR-CAD-024 | 솔더마스크 두께, 개구 확장 | PAR-053, PAR-150 | 마스크를 단순 색상과 구분하고 실제 두께, 개구 및 물성 연결을 보존한다. 마스크가 없는 안테나 영역을 별도로 지정할 수 있어야 한다. |
| B::PAR-CAD-025 | 표면처리, 에칭 단면 | PAR-060, PAR-061, PAR-151 | 해당 공정 모델을 지원할 때만 도금, 표면처리층 및 사다리꼴 도체 단면을 지정한다. 미지정값을 정밀하게 알려진 물리 형상으로 표현하지 않는다. 에칭 undercut과 선폭 오차의 적용 전후 형상을 구분한다. |
| B::PAR-CAD-035 | 코팅과 접착층의 범위 및 두께 | PAR-054, PAR-053 | 코팅, 접착, 커버레이의 적용 영역, 두께, 유전율과 손실 모델을 정의한다. 기계 형상에 존재하지만 해석에서 생략한 경우 구분해서 표시한다. |
| B::PAR-RF-029 | 재료 식별 출처와 시험 조건 | PAR-041, PAR-042, PAR-045, PAR-159 | 제조사 품명 lot revision 시험법 주파수 온도 방향 및 추정 여부를 보존한다. |
| B::PAR-RF-030 | 상대유전율 | PAR-043, PAR-045 | 벌크 Dk Design Dk Process Dk 및 유효유전율을 구분하며 기준 주파수와 방향을 저장한다. |
| B::PAR-RF-031 | 유전체 손실 | PAR-044, PAR-043, PAR-057 | tan delta 복소유전율 및 전도도 중 입력 의미를 정의하고 같은 손실의 중복 계상을 막는다. |
| B::PAR-RF-032 | 이방성 성분과 재료 축 | PAR-048 | 지원하는 대각 또는 전체 텐서 형태와 좌표 변환 가능성을 검사한다. |
| B::PAR-RF-033 | 도체 전도도와 온도 의존성 | PAR-057, PAR-049 | 수동 도체의 값과 유효 범위를 확인하고 PEC 사용 여부를 분리한다. |
| B::PAR-RF-034 | 도체 면별 표면 거칠기 | PAR-058, PAR-059 | Top bottom side 적용 면과 모델 이름을 저장하고 다른 지표를 근거 없이 환산하지 않는다. |
| B::PAR-RF-035 | 복소투자율과 자기 손실 | PAR-051 | 주파수 의존성과 손실 부호 규약 및 solver 지원 여부를 확인한다. |
| B::PAR-RF-036 | 분산 곡선과 피팅 계수 | PAR-047, PAR-046 | 원본 데이터 피팅 모델 유효 대역 오차와 외삽 상태를 보존한다. |
| B::PAR-CAD-018 | PTH, NPTH와 구멍 역할 | PAR-028, PAR-029 | 도금 여부와 장착 홀, 신호 비아, 접지 비아 역할을 구분한다. 기계적 접촉과 전기적 연결을 같은 속성으로 취급하지 않는다. |
| B::PAR-CAD-019 | 완성 구멍, 공구 직경 | PAR-144, PAR-145 | finished hole과 drill tool diameter를 구분한다. 제조 공정이 미정이면 두 값을 자동으로 동일 확정하지 않고 변환 근거를 기록한다. |
| B::PAR-CAD-020 | 비아 배럴 도금, 충진 | PAR-029, PAR-146 | 중공 도금 배럴, 금속 또는 수지 충진을 구분한다. 실제 솔리드와 해석 근사가 다르면 각 표현 및 재료를 기록한다. |
| B::PAR-CAD-021 | 패드 직경, 환형 링 | PAR-148, PAR-028 | 구멍, 패드 크기와 편심을 고려한 최소 환형 링을 검사한다. 명목값과 제조 허용값을 구별한다. |
| B::PAR-CAD-022 | 비아 종류, 시작층, 끝층 | PAR-147 | 관통, 블라인드, 매립, 마이크로비아 중 제품이 지원하는 종류만 허용한다. 층 범위와 도금 연결이 실제 3D 형상 및 제조 지시에 반영되어야 한다. |
| B::PAR-CAD-023 | 드릴 슬롯 길이, 폭, 방향 | PAR-013, PAR-028, PAR-118 | 완성 슬롯의 경계와 도구 경로 표현을 구분한다. PTH, NPTH 구분과 드릴 출력 형식의 슬롯 지원 범위를 확인한다. |
| B::PAR-CAD-033 | 비아 antipad와 stub | PAR-149, PAR-028 | 비아 주변의 접지 개구와 사용하지 않는 배럴 구간을 지정한다. 연결층과 비연결층을 구분하고 단순화할 경우 남기는 길이와 생략 근거를 기록한다. |
| B::PAR-RF-005 | 기준 임피던스 | PAR-004 | 실수 복소 및 주파수별 모델을 구분하고 정규화 방식과 유효 대역을 보존한다. |
| B::PAR-RF-006 | 입력 신호와 포트 전력 | PAR-010, PAR-090, PAR-100, PAR-106 | 정규화 전력 실제 구동 전력 waveform과 포트별 위상을 분리한다. |
| B::PAR-RF-039 | 정합 소자와 실제 부품 특성 | PAR-070, PAR-071, PAR-134 | RLC Q ESR SRF 공차 Sparameter와 footprint를 저장하고 이상 모델과 구분한다. |
| B::PAR-RF-040 | RF 소스 및 부하 모델 | PAR-072, PAR-112 | IC 또는 종단의 실제 임피던스 데이터 출처와 대역을 저장한다. |
| B::PAR-RF-041 | 포트 종류 방향과 기준 도체 | PAR-064, PAR-065, PAR-066, PAR-067 | 포트 형식에 필요한 단면 방향 극성 reference conductor 및 연결을 검사한다. |
| B::PAR-RF-042 | 기준면과 케이블 보정 | PAR-066, PAR-129, PAR-073 | 원본 기준면 이동 거리 방향 전파 모델과 deembedding 이력을 보존한다. |
| B::PAR-CAD-034 | 급전점과 급전선 기하 | PAR-030, PAR-037, PAR-038, PAR-039, PAR-040, PAR-064, PAR-065, PAR-068, PAR-117 | 급전점 좌표, 급전선 길이, 폭, 포트 갭과 기준 도체를 연결한다. IFA 및 PIFA의 단락선 또는 단락 비아 치수와 전기적 연결도 기록한다. |
| B::PAR-RF-056 | 케이블과 balun 및 공통모드 구조 | PAR-069, PAR-073, PAR-077 | 케이블 길이, 경로, 차폐와 접지 연결, 커넥터 및 balun의 유효 모델을 저장한다. 실제 급전계와 이상 포트의 평가 조건을 구분한다. |
| B::PAR-CAD-026 | 부품, 케이스 위치와 간극 | PAR-074, PAR-075, PAR-076, PAR-077, PAR-078 | 외부 모델의 변환과 최소 간극을 저장한다. 접촉, 관통, 원본 대비 단순화 및 해석, 출력 포함 여부를 구분한다. |
| B::PAR-RF-037 | 온도 습도와 노화 상태 | PAR-049, PAR-050, PAR-079 | 물성 변화식 또는 실측 데이터가 없는 효과는 계산 미반영으로 표시한다. |
| B::PAR-RF-038 | 변수 공차 분포와 상관 | PAR-052, PAR-096, PAR-097, PAR-098 | 최소 최대 표준편차 분포 상관관계 표본 수 및 seed를 저장한다. |
| B::PAR-RF-043 | 케이스와 radome | PAR-074 | 외곽 두께 이격 위치와 재료를 지정하고 상세 모델 또는 간이 모델을 표시한다. |
| B::PAR-RF-044 | 배터리 실드와 주요 부품 | PAR-075, PAR-076 | 금속 또는 유전체 표현과 접지 접촉을 구분하고 부품 모델 수준을 기록한다. |
| B::PAR-RF-045 | 장착 구조와 주변 물체 | PAR-076, PAR-079 | 벽 브래킷 금속판 인접 기판과의 거리 방향 및 전기적 접촉을 저장한다. |
| B::PAR-RF-046 | 인체 팬텀과 자세 | PAR-115 | 조직 물성의 출처 주파수 범위 자세 및 단순화 수준을 기록한다. |
| B::PAR-RF-047 | 유연 기판의 굽힘 | PAR-114 | 굽힘 축 반경 각도와 변형 후 적층 및 재료 축 변환의 유효성을 확인한다. |
| B::PAR-RF-048 | 복수 안테나와 배열 배치 | PAR-103, PAR-105, PAR-106 | 소자 위치 방향 간격 및 구동 종단 조건을 연결하고 상호 결합 계산 여부를 표시한다. |
| B::PAR-RF-049 | 외부 매질 영역과 경계 | PAR-081, PAR-082 | Air box PML 대칭 주기 경계와 모델의 부적절한 중첩을 검사한다. |
| B::PAR-RF-050 | 공간 메시와 국부 세분화 | PAR-083 | 최소 최대 셀 growth gap via feed refinement와 시트의 메시 정렬을 검사한다. |
| B::PAR-RF-051 | 시간 간격 반복과 종료 조건 | PAR-085, PAR-086 | 잔차 에너지 최대 시간 반복 자원 제한과 정상 수렴을 분리한다. |
| B::PAR-RF-052 | 근접장과 전류 관측 영역 | PAR-089, PAR-090 | 관측 면 좌표 성분 주파수 입력 전력과 전류 종류에 따른 단위를 저장한다. |
| B::PAR-RF-053 | NF2FF와 방사 패턴 관측 | PAR-088, PAR-089 | 변환면 위상 중심 관측 각도 좌표 편파와 주파수별 데이터의 유효성을 확인한다. |
| B::PAR-CAD-027 | 제조사 설계 제한값 | PAR-063 | 최소 선폭, 간격, 드릴, 환형 링, 보드 외곽 거리 및 비아 종횡비를 제조사, 프로파일 버전과 함께 기록한다. 미설정 항목은 검사 완료로 표시하지 않는다. |
| B::PAR-CAD-028 | 제조 치수 공차와 변동 | PAR-139, PAR-096, PAR-097, PAR-098 | 명목값, 하한, 상한을 구분하고 선택적으로 분포, 상관관계를 기록한다. taufab는 CAD 변환 허용오차와 별개이며 RF 공차 해석에 연계할 수 있어야 한다. |
| B::PAR-CAD-029 | CAD, 2D 변환 허용오차 | PAR-137, PAR-138 | 지원 형상과 대상 도구를 기준으로 확정한다. 단순 시험 PCB의 tauCAD=0.001 mm는 잠정 제안이며 제조 정확도 보증이 아니다. 좌표 오차 외에 연결과 구멍 보존을 검사한다. |
| B::PAR-CAD-030 | 곡선 근사, 좌표 양자화 | PAR-031, PAR-152 | 화면 메쉬, 해석 메쉬 및 출력 곡선의 근사 설정을 구분한다. Gerber, DXF의 좌표 분해능과 근사가 RF 중요 간격을 소실시키지 않는지 확인한다. |
| B::PAR-CAD-031 | 용지, 축척, 표시 뷰 | PAR-141, PAR-157 | CAD 교환 패턴의 실제 크기 1:1과 문서 도면 축척을 구별한다. PDF의 자동 맞춤 인쇄까지 정확도를 보장하지 않으며 기준 길이와 축척을 표시한다. |
| B::PAR-CAD-032 | 파일 버전, 포함 객체, 대응표 | PAR-140, PAR-014 | STEP 스키마, KiCad 버전, Gerber, 드릴 형식, 원점, 포함 레이어, 바디, 병합, 구멍 채움, 모델 대체 설정과 물성 명세의 대응을 출력 기록에 보존한다. |
| B::PAR-CAD-036 | 정합 BOM과 실장 상태 | PAR-153, PAR-071, PAR-136 | 부품값, 풋프린트, 모델, 제조사 부품번호와 실장 여부를 설계 변형에 연결한다. 정합 해석에서 사용한 회로와 조립 산출물의 대응을 검수한다. |
| B::PAR-RF-054 | 실측 교정과 환경 조건 | PAR-127, PAR-128, PAR-129, PAR-130, PAR-131 | VNA 교정면 fixture 케이블 팬텀 설치 환경과 원본 보정 데이터를 구분한다. |
| B::PAR-RF-055 | 모델 적용 범위와 검증 근거 | PAR-087, PAR-091, PAR-132, PAR-133, PAR-159 | 사용 근사 누락 효과 템플릿 출처 수렴 독립 해석 및 실측 검증 수준을 기록한다. |

## 8. 원문 접근, 재배포, 검증 상태

출처 링크는 발견/확인 시점의 기록이다. 접속 실패, 변경, 문서 판본 차이를 검토 이력에 남긴다. source-backed 수치와 수식이라도 목적 PCB에 적용하기 전에 조건을 확인한다. 원문 PDF나 코드의 재배포 가능 여부는 metadata에서 구분하며 문서 링크와 실제 파일 포함을 같은 것으로 취급하지 않는다.

원문별 locator는 physical PDF page와 printed page가 다를 수 있으므로 기존 레코드의 numbering convention을 유지한다. CAD 근거는 archive hash/member name/line 또는 object 위치를 사용한다. 데이터의 SHA256은 파일 동일성을 증명할 뿐 수치의 물리적 정확도를 자동 증명하지 않는다.

## 9. 입력 사전의 저장 계약과 누락값

PAR ID는 입력 의미를 식별한다. 같은 layer, port, object, environment에 반복되는 값은 소유 객체 UUID와 함께 저장하며 PAR ID만으로 한 값을 덮어쓰지 않는다. `nominal`, `min`, `max`, `unit`, `source`, `status`, `frequency_domain`, `revision`을 수치와 분리하지 않는다. null, 0, 해당 없음, 계산 미지원, 사용자가 승인한 추정값은 다른 상태이며 실제 0인 gap/손실/회전 값도 각 정의역 규칙을 따른다.

단위가 바뀌어도 저장 SI 값은 보존한다. 동일 물리량에 공급된 table/model/scalar 중 실제 소비한 표현을 기록하고, 다른 정의를 자동 우선순위로 골라 숨기지 않는다. 복소 수는 RFAD 08의 명시적 표현을 사용하며 NaN/Inf를 JSON 숫자로 저장하지 않는다. 허용되지 않는 수치와 미계산 지표는 값 없이 상태와 원인을 남긴다. 조건부 필수 입력은 선택 기능의 validation profile이 결정하며 숨겨진 입력창의 기본값으로 채우지 않는다.

GUI 및 실행 자원의 cache 한도, concurrency, IPC payload, 메모리 예산, startup/latency 기준은 안테나 물리 PAR 수에 합산하지 않는 runtime 정책이다. [GUI 성능 계약](24_RFAD_GUI_선정과_성능_설계.md)의 PERF-001~010과 기준 host/fixture는 초기 목표로 채택되었으며 정확한 CPU/GPU와 실행 manifest는 아직 정하지 않았다. 이를 최소사양 보장이나 실측 합격으로 표시하지 않는다. 계약과 실행 manifest에 버전을 기록하고 화면 상태 변경을 raw EM 물리 hash와 분리한다. geometry/material/port가 바뀌면 해당 물리 snapshot과 파생 결과 의존성을 갱신한다.

## 10. 큰 자료의 검색과 가져오기

앱 시작 시 전체 원문/PDF/장 데이터 또는 3160개 재질의 상세 evidence를 모두 메모리에 올리지 않는다. 색인과 가벼운 요약은 페이지 단위로 읽고 상세/미리보기는 선택한 항목만 비동기로 가져온다. SQLite 검색 결과, 썸네일, 원문 보기와 history cache에는 소유자와 상한/퇴거 규칙을 둔다. 중복 source ID와 source version을 구분하며 취소한 검색의 늦은 응답이 최신 검색 결과를 덮어쓰지 않는다.

가져오기는 크기/압축 해제 한도와 schema 검증을 먼저 수행한다. 파일에 적힌 script 또는 외부 경로를 데이터 읽기만으로 실행하지 않는다. 원문과 정규화 파생본은 분리하고 오류 레코드는 이유를 포함해 격리한다. 모든 행을 조용히 성공으로 간주하거나 일부 행 실패를 전체 dataset 손실로 처리하지 않는다. 입력별 총수, 성공/차단/충돌 수, source 연결과 선택 결과를 보고하며 VT-019/027/028에서 저장 의미와 자원/응답을 각각 검사한다.
