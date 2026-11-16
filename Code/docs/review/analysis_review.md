# 해석, 결과, CAD 및 참고 자료 문서 검토

검토일: 2026-11-16 KST. 승인 기준선은 RFAD-D0-3.4다. 현재 코드와 문서의 지원 범위, 화면 진입점, 출처 보존 및 수치 판정의 의미를 대조했다. 이 작업은 문서 정비이며 새 FDTD, 실제 GUI 계산, 제작품 측정 또는 독립 CAD 검수를 수행한 기록이 아니다. 승인 원문, `00_REF`의 원본/추출 데이터와 과거 runtime 보고서는 수정하지 않았다.

검토 대상의 본문은 모두 읽었다. 아래 분류는 최종 문서 배치의 기준이며 현재 링크가 가리키는 계약/연구 기록을 대체하는 별도 기능 정의가 아니다. 제품 동작은 현재 기능 계약, 과거 수치는 실행 당시 조건과 immutable artifact를 기준으로 읽는다.

## 1. 검토 범위와 기준

| 기준 문서 | 읽은 범위 | 현재 구현과 대조한 핵심 |
| --- | --- | --- |
| [승인 10 연산 파이프라인](../../../01_Docs/10_RFAD_연산_파이프라인.md) | 본문 전체 | 설계 원본, 불변 snapshot, 파생 해석/출력 및 검증 상태의 분리 |
| [승인 11 해석기 어댑터](../../../01_Docs/11_RFAD_해석기_어댑터_계약.md) | 본문 전체 | plan/prepare/execute/postprocess, 입력 hash와 raw/normalized 결과, 취소와 결과 불명 |
| [승인 12 도면/제조 출력](../../../01_Docs/12_RFAD_도면과_제조_파일_출력.md) | 본문 전체 | preview/build/verify, STEP 정확 형상/표시 mesh 구분, 제조 패키지 수용 조건 |
| [승인 13 최적화/측정](../../../01_Docs/13_RFAD_최적화와_측정.md) | 본문 전체 | 연구 입력/변수/예산/취소/재개, 측정 기준면/교정/불확도 |
| [승인 14 검증/수용](../../../01_Docs/14_RFAD_검증과_수용_기준.md) | 본문 전체 | 계산 성공, 수치 안정성, 독립 RF 정확도, 제작/측정 수용과 초기 임계값 구분 |

코드는 `application/cad.py`, `cad_jobs.py`, `cad_artifacts.py`, `physical_projection.py`, `projects.py`, `wsl_process.py`, CAD native adapter와 `ui/wxwidgets`의 workspace/solver/study/report 표시 경로를 대조했다. 세부 적층/환경 계약은 [physical_setup](../features/design/physical_setup.md), 화면 ID와 이벤트는 [화면 전환 시나리오](../screen_design/screen_scenarios.md)를 따른다. 화면 문서의 제안 동작을 현재 구현 완료로 해석하지 않는다.

## 2. 문서별 검토와 보강

`본문 유지`는 검토 생략을 뜻하지 않는다. 현재 동작과 과거 실행 범위가 이미 구분된 문서는 숫자/판정을 재작성하지 않았다.

| 문서 | 분류 | 본문 검토 결과와 이번 보강 | 열린 설계 의존성 |
| --- | --- | --- | --- |
| [solver_contract](../features/analysis/solver_contract.md) | features/analysis  | 고정 IFA 연구 완료와 일반 실물 검증을 분리. 표면층/외부 환경의 EM 차단, 60초 runtime 준비와 동일 run/nonce 조회 복구를 설명. 이미 구현한 방사/손실/연구 GUI를 전부 후속으로 쓰던 문장 정정 | 서비스 재시작 후 공개 복구 UI, solver checkpoint, 독립 RF 참조, 실제 급전/물성 |
| [pcb_solver_contract](../features/analysis/pcb_solver_contract.md) | features/analysis  | 저장/CAD 가능 항목과 EM 지원을 분리. 고정 3축 CLI, 완료 보고서 GUI, 현재 프로젝트 단일 격자 축 GUI를 구분. NF2FF 전체를 후속으로 쓰던 문장 정정 | 내부 동박/표면층/설치 물체 EM, 다중 포트, 일반 수렴 및 제조 DRC |
| [project_studies](../features/analysis/project_studies.md) | features/analysis  | 현재 1~6개 grid 한 축, immutable 연구 정의/명시적 재개/시도 보존 확인. 일반 프로젝트 입력 지원을 계획 6번 전체 완료로 확대하지 않도록 명시하고 S20/D21/S30/S40 연결 | 임의 설계 변수, 자유 다축, 최적화 예산, checkpoint와 실행 정책 |
| [pcb_radiation](../features/analysis/pcb_radiation.md) | features/analysis  | 기존 2D 절단면/페이징/전력 규약 확인. 나중에 구현된 독립 흡수 적분과 최초 방사 기록을 분리하고 과거 결과에 손실을 채우지 않도록 정정 | 3D 방사/편파/필드 UX, 절대 출력, 독립 solver/실측 대조 |
| [pcb_power_balance](../research/pcb_power_balance.md) | research  | 본문 유지. 최초 planar 적분과 후속 QuarterCell/PTH 계산을 이미 분리하며 과거 표와 독립 수지 제한 확인 | 잔차 통과와 각 성분 정확도의 분리, 손실 성분별 수용 기준 |
| [pcb_loss_precision](../research/pcb_loss_precision.md) | research  | 원래 QuarterCell/sheet/PTH 분할과 판정을 유지. 최초 3.430551%/timeout에서 후속 2.788446%/2% 미확립으로 연결 | GHz PTH 독립 정확도, 국부 격자/도체 손실 기준 충족 |
| [cad_contract](../features/exports/cad_contract.md) | features/exports  | purpose 인수, 표면층/외부 box/STEP의 현재 지원, 표시/출력 포함 분리와 cad.latest의 view_result를 반영. 전체 부품/케이스 미지원이라는 오래된 설명을 실제 제한으로 좁힘 | 일반 assembly/자유 3축 배치, 외부 kernel 검수, 제조 package verify |
| [ifa_convergence](../research/ifa_convergence.md) | research  | 2.0~3.0 GHz와 1.6~2.6 GHz의 원래 표/판정 유지. 완료 IFA 보고서의 읽기 전용 GUI를 반영하고 fixed matrix 실행과 generic study를 구분 | 실제 SMA/급전/측정 기준면, X=0 공진, 실물 정합 목표 |
| [pcb_radiation_convergence](../research/pcb_radiation_convergence.md) | research  | 본문 유지. 3축 고정 manifest와 1축 GUI, 구면 적분/수동성/독립 손실을 이미 구분. 계산/판정의 이전 기록 보존 확인 | 자유 다축 UX, 기록면/위상중심 불변 가드, 독립 방사 정확도 |
| [ro4350b_loss_refinement](../research/ro4350b_loss_refinement.md) | research  | 본문 유지. 사전 예산, N 수준, 실패/최종 쌍, 2.788446%로 2% 미확립인 상태를 확인 | 사전 정의한 새 연구 없이는 추가 세분화/완화 금지. 실제 foil/거칠기/실장 자료 |
| [openems_reference](../research/openems_reference.md) | research  | 2026-11-10 도파관 환경 검사와 이후 제품 연구를 연결. 환경 보고서의 false 플래그를 그대로 보존하고 이를 현재 전체 제품 기능 상태로 읽지 않도록 정정 | 환경 검사 이상의 모델별 정확도, 독립 참조와 측정 |
| [catalog_pcb_integration](../research/catalog_pcb_integration.md) | research  | JLC0206 미정 물성 차단과 합성 카탈로그 양성 대조군을 확인. 기록 시점과 이후 적층/환경 구현을 구분 | 주문별 실제 적층/물성, 표면층, 계측 대조 |
| [jlc_manufacturing_selection](../research/jlc_manufacturing_selection.md) | research  | 2026-11-11 공급 정보/탐색 계산과 현재 기능 분리. 당시 keepalive 우회/실패 로그는 유지하고 이미 추가한 bounded runtime 준비/조회 복구를 반영 | 현재 주문 조합 재확인, 납품 물성/ENIG/마스크/측정 조건, 냉기동 실측 |

## 3. 참고 자료 본문 검토

참고 자료는 수집 당시의 근거다. 문서의 당시 UI 미구현 설명이나 옛 수집 경로를 현재 제품 사양 또는 깨진 원본으로 단정하지 않는다. 최종 경로는 catalog/path map과 source hash를 대조한다. 아래 문서는 원본을 수정하지 않고 읽었다. 검색 텍스트 파일 전체를 문서 본문 검토로 계산하지 않았다.

### 3.1 PCB 유전 자료 Markdown 10개

기준 폴더: `00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026`.

| 문서 | 읽은 결과와 제품 설계 영향 |
| --- | --- |
| `README_ko.md` | 자료의 진입점, 회사별 JSONL/Excel과 원문/감사 분리를 확인. 요약 행 수를 독립 재료 종류나 실측 수로 표시하지 않음 |
| `docs/자료_사용_안내.md` | 57,340 관측행, 누락/범위/대표값과 `simulation_ready=false` 의미를 확인. null을 0/DC/기본 FR4로 변환하지 않음 |
| `docs/자료_검토_결과.md` | 자료 전체 감사, 알려진 원문 미포함, 조건/충돌/타입 보존을 확인. 당시 앱 미구현 설명을 현재 기능 상태로 복사하지 않음 |
| `docs/소재_기타_수집_메모.md` | 자성/접착/코팅/연성 등 특수 자료의 적용 범위를 확인. MAGTREX 같은 자성값을 비자성 등방성 모델로 일반화하지 않음 |
| `docs/소재_RF_수집_메모.md` | Process/Design Dk, 방향/주파수/제품 변형과 자료의 모호한 조건을 확인. RO4350B/LoPro/TICER 및 시험 Dk를 합치지 않음 |
| `docs/소재_FR4_수집_메모.md` | glass style/RC/주파수/시험법별 관측과 누락값을 확인. FR4 전체에 단일 Dk/Df를 부여하지 않음 |
| `docs/Nanya_New_Material_추출_메모.md` | NOUYA와 대만 Nan Ya를 구분. NY6666 비정상 Df와 RC 조건 충돌은 원문과 null/플래그 유지 |
| `docs/PCB_제작업체_수집_메모.md` | JLC 음수 PP 226행, PCBWay 묶음 PP 999행과 공급 옵션의 적용 범위를 확인. 임의 양수 재분배/ply 분할/주문 가능 확정 금지 |
| `audit/current/README.md` | 현재 정본/파일명 변경/해시 감사의 기준을 확인. 이름 변경과 원문 내용 변경을 분리 |
| `audit/collection/README.md` | 수집 당시 감사 기록의 위치/범위를 확인. 현재 정본과 옛 행 수를 혼합하지 않음 |

### 3.2 안테나 추출 및 수집 README 6개

첫 다섯 문서의 기준 폴더는 `00_REF/PCB RF ANT/04_RF_Antenna_Extracted_Data/extraction`이다.

| 문서 | 읽은 결과와 제품 설계 영향 |
| --- | --- |
| `README_EXTRACTION_KO.txt` | 241 출처/238 실제 자료, 31 형상/348 치수 및 정선 추출 범위를 확인. 전체 원문의 모든 수치 검증 완료로 표시하지 않음 |
| `source_index/README_INDEX_KO.txt` | PDF 실제 페이지 번호, 텍스트 색인/FTS와 저텍스트 페이지 제한 확인. 색인 성공과 그림/수식 시각 검증을 구분 |
| `geometry/README_KO.txt` | 치수 있는 예제와 완전한 연결/적층/급전 모델의 차이 확인. G031 ZIP/내부 PDF/Gerber와 부분 형상 근거 보존 |
| `materials/README_KO.txt` | 조건별 물성/보조값과 review 항목 확인. 0과 null, Process/Design 값과 주파수/방향을 유지 |
| `validation/README_notes.txt` | 모델식/실험/조건의 추출 범위와 문헌 기준의 적용성을 확인. 검증 방법의 소개를 실제 수행/합격으로 표시하지 않음 |
| `05_PCB_Dielectric_Data_2026/audit/collection/README_ko_수집당시.txt` | 옛 디렉터리/수집 요약임을 확인. 최종 파일 위치는 현재 catalog/path map 사용 |

문헌 카드의 열린 문제는 G004/G005의 치수 충돌, G020의 손실 표기 충돌, G021 치수명 충돌, G030 CPW 폭/간격 누락 등이다. 근거가 없는 값을 보충해 재현 완료로 바꾸지 않는다. G031의 원호/급전 부분과 보드 몸체 기준 원은 전체 netlist/접지/탭/적층 재현과 다르다. Hammerstad-Jensen 등의 식은 확인된 준정적 무두께 microstrip 범위에서만 읽고 IFA/원호 공진 치수 합성으로 일반화하지 않는다.

### 3.3 목록, 출처, 추출 연결 검사

이번 검사는 로컬 파일과 보존 manifest의 경로/식별자/바이트 hash 및 관측행 연결을 읽기 전용으로 비교한다. 원문 PDF 1,159개의 모든 그림/수식/기술 주장에 대한 RF 재검증은 이 문서 정비와 별도다. 온라인 공급 정보 재조사나 원문 다운로드도 수행하지 않았다.

Python 표준 라이브러리의 CSV/JSON/ZIP 읽기와 SHA256, 읽기 전용 `git show HEAD:<path>`로 다음을 대조했다. HTML blob을 확인한 HEAD는 `80ce6b4972381b86c640ba6ef974770e3dc0bfe2`다. 보존 파일에 쓰기나 줄바꿈 변환을 적용하지 않았다.

| 검사 | 결과 | 해석 |
| --- | --- | --- |
| 파일로 존재하는 PDF | 1,159개 | 전체 페이지/도면의 의미 검증 수가 아님 |
| 안테나 출처 목록 | 241건 중 238건 파일 발견, 3건 원래 local path 없음 | TI_CC1110_IFA_CAD, BOOK_ORFANIDIS_EWA, KEYSIGHT_NETWORK_BASICS의 미포함 상태 보존 |
| 안테나 출처 바이트 hash | 223건 작업트리 바이트 일치, HTML 14건 HEAD blob 일치, HTML 1건 미일치 | 아래 줄바꿈/Keysight 이슈를 분리하여 기록. 전체 무결성 합격으로 표시하지 않음 |
| 추출 record -> source 연결 | 3,869행 모두 source ID/hash/보존 상대 경로 일치 | 원문 목록과 추출 참조의 내부 연결 검사이며 모든 추출 숫자의 재검산은 아님 |
| G031 중첩 ZIP | 내부 ZIP hash와 인용한 4개 member hash 일치 | 내부 PDF/GTL/GBL/GM1 근거를 대조. 전체 netlist/적층 재구성은 아님 |
| 유전자료 출처 | 1,756건 중 local path가 있는 1,701건, 고유 파일 1,682개 모두 바이트 hash 일치 | local path가 없는 출처를 다운로드 성공으로 계산하지 않음 |
| 관측 정본 | 37 JSONL 분할의 bytes/hash/행 수, 57,340행 canonical digest 일치 | 기존 index의 정본을 보존했음을 확인 |
| 관측 출처 연결 | 알려지지 않은 source ID 0건, 명시된 source_file의 실제 누락 0건 | 원래 source_file이 없는 241행은 미포함 상태 유지 |
| JLC API 연결 | 26,276행의 source_manifest_file/31개 기술 스냅샷 연결, 각 스냅샷 bytes/hash 일치 | source_file이 최상위 FB240 manifest와 다른 정상적인 2단계 출처 연결 |

안테나 HTML 14개는 작업트리의 CRLF 바이트가 source hash와 다르지만 HEAD blob 및 CRLF를 LF로만 정규화한 비교 바이트가 원래 hash와 일치한다. 이 결과를 작업트리 원문 바이트 자체의 일치로 바꾸지 않는다. 향후 원문을 직접 hash 검사하는 기능은 정본 보관/체크아웃 정책을 명시해야 하며 화면 설계 문서 작업에서 기존 자료를 덮어쓰지 않는다.

`KEYSIGHT_NETWORK_ANALYSIS_HTML`은 작업트리와 HEAD blob 모두 보존 source hash와 다르며 LF 비교도 일치하지 않았다. 이번 검사로 원인을 확정하거나 내용을 복원하지 않았다. 해당 자료를 새로운 측정/교정 구현 근거로 채택하기 전에 별도 출처 무결성 검토가 필요하다.

- 실제 파일: `00_REF/PCB RF ANT/03_RF_Antenna_Materials_Theory_Tools/measurement/KEYSIGHT_NETWORK_ANALYSIS_HTML__Network_Analysis_Measurement_Fundamentals_official_web_tutorial.html`.
- 기대 hash 위치: `00_REF/PCB RF ANT/04_RF_Antenna_Extracted_Data/extraction/source_coverage.csv`의 `source_id=KEYSIGHT_NETWORK_ANALYSIS_HTML`, `source_sha256` 필드.
- 추출 단계의 상대 경로: `files/measurement/KEYSIGHT_NETWORK_ANALYSIS_HTML__Network_Analysis_Measurement_Fundamentals_official_web_tutorial.html`. 현재 보관 위치와 파일명으로 대응시킨 뒤 hash를 비교했다.

| Keysight HTML 근거 | SHA256 |
| --- | --- |
| 추출 source 목록의 기대 hash | `34a7bc9c03ef2fe5d4dfba6bdaac45b0a10847d5b83df94b1324cdd8ef1dec3f` |
| 작업트리 파일 | `4a94238bd304e0bb1abd6f87f67197fe897f6c6ae7a5f31791f135bd3bcfdbbd` |
| 확인한 HEAD blob | `b79c7cd1f0fdc760f5a735c3631ed4a08e87a74434c1a09757069888f4bc643e` |

최초 단순 검사에서 JLC 관측행의 `source_file`과 FB240 manifest 경로가 다르게 나타났으나, `source_manifest_file`과 `additional_local_files`, 최종 path map을 따라가면 위 26,276행 모두 연결된다. 이를 깨진 참조로 보고 정본 경로를 일괄 변경하지 않았다. 이미 명시된 원문 미포함 관측도 누락을 숨기거나 수치로 채우지 않으며 해당 source ID/URL/상태를 유지한다.

## 4. 현재형 충돌과 중복을 다루는 규칙

| 주제 | 정본과 읽는 순서 | 문서/화면에 남길 구분 |
| --- | --- | --- |
| PCB 해석 지원 | solver_contract -> pcb_solver_contract -> 옵션별 결과 계약 | 입력 검사 valid와 실제 solver plan/prepare 완료는 다름 |
| 적층/외부 환경 | physical_setup -> 목적별 CAD/EM projection | 저장 가능, 3D 표시, STEP 포함, EM 포함은 독립 상태 |
| 수치 연구 | 고정 연구 manifest/과거 보고서 -> project_studies | 고정 검증 도구와 현재 설계 한 축 GUI는 범위가 다름 |
| 손실 계산 | power_balance의 최초 기록 -> loss_precision -> ro4350b 후속 연구 | 과거 raw/판정을 소급 교체하지 않고 다음 연구로 연결 |
| 결과 화면 | S30/D22/D23의 표시 -> 해당 artifact/snapshot | 창을 열거나 보고서 paint에 성공해도 계산/재판정/실측을 새로 수행한 것이 아님 |
| STEP와 3D | cad_contract -> physical_setup | geometry 목적과 step 목적은 포함 항목이 다를 수 있고 mesh는 표시 전용 |
| 제조 자료 | 저장된 관측 -> 별도 사용자 선택/가정 -> 입력 snapshot | 수집 당시 공개값, 탐색 모델, 현재 주문 확정과 실측값을 구분 |

`study_report_model.cpp`의 방사 요약은 원래 `rfad.pcb-radiation-study-run/0.1` 보고서의 수동성/구면 적분 범위를 표시한다. 이 창의 `흡수 적분 미평가` 문구를 제품 전체에 독립 손실 기능이 없다는 뜻으로 확대하지 않는다. 향후 더 많은 schema를 이 창에 연결할 때에는 artifact에 실제 있는 평가 범위로 문구를 선택해야 한다. 이번 정비에서 코드 변경이나 새로운 보고서 schema 지원을 선언하지 않는다.

## 5. 다음 개발 단계에 남기는 설계 의존성

번호는 기존 개발 완료 계획을 유지한다.

| 단계 | 이 검토에서 남기는 의존성과 수용 근거 |
| --- | --- |
| 4 | 원본 객체 이름/선택/개정과 2D/3D 표시를 연결. 목적이 다른 CAD를 현재 설계의 해석 가능한 장면으로 오인하지 않도록 상태/비활성 사유 표시 |
| 5 | 공통 복소 결과/목표 평가의 주파수, 기준면, Z0, null 의미를 통일. 현재 포트 결과와 목표를 저장한 사실만으로 자동 평가 완료 표시 금지 |
| 6 | 현재 한 축 연구를 보존하면서 자유 변수/다축/예산/재개 계약 확장. solver checkpoint와 완료 artifact 재사용의 차이 명시 |
| 7 | 복수 run 비교/Smith/3D 방사/편파/필드 전환에서 snapshot/가정/단위/정규화를 보존. CAD 3D와 방사 3D 구분 |
| 8 | RO4350B 2.788446%로 2% 미확립과 GHz PTH 독립 정확도 미확립 유지. 총 수지 통과를 개별 손실/실측 정확도로 확대하지 않음 |
| 9 | 실제 목표 대역 원호/IFA 튜닝은 별도 입력/급전/환경/수렴 증거 필요. 문헌 부분 재현과 성능 달성 분리 |
| 10 | PDF/SVG/DXF와 EDA 제조 교환 및 외부 kernel STEP 검수. 기존 동일 OCCT 재입력 성공을 독립 수용으로 승격하지 않음 |
| 11 | 교정/기준면/시료/케이블/지그/불확도 확보 후 측정 비교. 자료 확보 전 제작/측정 미정값 유지 |
| 12 | 상태/복구/보고서/접근성/성능 수용과 서비스/MCP 상호 운용. 냉기동/중단 복구와 실제 Windows UX를 별도 실측 |

13번 내부 패키지/설치/라이선스와 R1 최종 검수는 위 근거를 묶는 후속 단계다. Linux GUI와 R2/R3 및 비평면 3차원 안테나 편집/해석은 별도 장기 범위로 유지한다. 현재 외부 STEP 배치와 CAD 3D 표시가 장기 3D 안테나 모델을 완료한 것으로 표시되어서는 안 된다.
