# 문헌 기반 부분 기하 카드

기준일: 2026-11-12 KST. 개발 완료 계획 3번과 관련 GUI인 4번의 일부다. 최초 문헌 카드는 `literature.g031_pca20006_arc/0.1`이다. 기존 직접 입력 원호/IFA, 목표, 기판, 재료 카탈로그와 명령/저장 구조를 재사용한다. 승인 원문과 과거 검증 기록은 수정하지 않는다.

## 확인한 원문과 적용 범위

G031은 Nordic PCA20006 / PCB400059 hardware 1.0.0의 원호와 급전 stub이다. 저장소의 실제 원본 ZIP, 그 안의 ZIP, GTL/GM1 및 embedded PDF bytes를 대조했다. 과거 추출 레코드의 `files/Reference_CAD/...`를 현재 경로로 사용하지 않는다.

| 자료 | 확인한 SHA256 또는 locator |
| --- | --- |
| 외부 ZIP | `de2dbf4b9c8c660efe9c92d716ec161728dde018a801b5ccb1bfdd0d88a55a8a` |
| 내부 `nRF51822 Bluetooth Smart Beacon Kit - Hardware files 1_0_0.zip` | `de83d749b10f9f77fc493df293c544782d3ad4624bdfe98fac328da6fdf889db` |
| `400059.GTL` | `1225766196a9608ba1d97deaa6b9dbde399878344e190951474a2e41ce01d292`; 1-5, 8, 705-713 |
| `400059.GM1` | `ef4045a313aed01197fa205b1a100f91263c42b18d34b065b519155fddfa468b`; 129-131, 141-146 및 원문 후속 탭 선 |
| `PCA20006_Schematic_And_PCB.pdf` | `e328c2c6d9192b326db2289ae6d473780f08fd696e7eb268521bcfa1ab2fb8c9`; 물리 p.1 회로, p.2 top, p.3 bottom |

현재 경로는 `00_REF/PCB RF ANT/01_RF_Antenna_Vendor_Guides_CAD/Reference_CAD/NORDIC_PCA20006_CAD__nRF51822_Bluetooth_Smart_Beacon_Kit_PCA20006_PCB400059_hardware_files.zip`이다. 전체 member 경로, 각 해시와 사용한 Gerber 줄 사본은 카드 `evidence`에 보존한다. 원문 출처 URL은 [Nordic reference design 안내](https://devzone.nordicsemi.com/f/nordic-q-a/47638/altium-reference-design-for-nrf51822-beacon-kit/188689)다. 이번 검토는 저장소의 원문 bytes를 사용했으며 웹의 최신 개정으로 바꾸지 않았다.

`FSLAX24Y24`, `MOIN`, `G75`와 원형 D10 aperture `0.0500 inch`를 확인했다. 원문 정수 좌표의 간격은 0.00254 mm다. GTL 705-708의 CCW 원호와 712-713의 수평 stub만 생성한다.

| 치수 | 원문 또는 유도값 |
| --- | --- |
| 원호 중심 | (0, 0) mm |
| 원문 시작점 | (-2.64668, 8.72744) mm |
| 원문 끝점 | (-7.04596, -5.78866) mm |
| 시작점-중심 반지름 | 9.119930042275543 mm |
| 시작각 / CCW sweep | 106.87043102934852 / 112.53463398648967 deg |
| 원호와 stub 선폭 | 1.27 mm |
| stub 시작 / 끝 | (-6.96976, -5.842) / (-5.0546, -5.842) mm |

원호의 radius는 시작점-중심 거리를 사용하고 끝점 방향까지의 CCW 각도를 계산한다. 따라서 analytic 끝점과 원문 양자화 끝점의 반지름 차이 약 0.001041024572 mm를 카드에 명시한다. 원문 좌표를 숨기거나 양 끝점이 정확히 같은 원 위에 있다고 표시하지 않는다. stub은 원호 끝의 도체와 폭으로 겹친다. 기존 내장 원호 카드처럼 stub을 원호 시작점에 붙이거나 중심선 끝점을 이동시키지 않는다.

GM1의 body reference diameter 약 19.999016107 mm는 탭/커넥터를 포함한 전체 보드 외곽이 아니다. 기존 보드를 유지하며 새 원형 보드나 접지판을 만들지 않는다. 인접 구리의 한 원호/꼭짓점을 전역 접지 반지름이나 최소 keepout으로 해석하지 않는다.

## 미정값과 별도 상태

생성 범위는 `partial_arc_and_stub`이며 `whole_board_reproduced=false`다. 전체 구리/net/접지/비아/패드, 탭 외곽과 정합 부품, 배터리/외함은 생략한다. Gerber에 net 이름이 없어 생성하는 net은 편집용 묶음이며 원본 netlist를 복원했다는 뜻이 아니다.

PDF p.1에서 L1=2.2 nH series와 C4=1.2 pF shunt 및 앞단 BAL-NRF02D3를 확인했다. 이는 해당 개정의 회로 관측으로만 보존하고 기본 RLC나 포트를 생성하지 않는다. 보드 등급/Dk/Df/두께와 동박/마스크, 실제 납품/실장/측정 조건도 임의로 보완하지 않는다.

후보 `generation` 및 생성 이력의 표시 DTO는 다음 상태를 각각 반환한다.

| 축 | 현재 상태 |
| --- | --- |
| 명시 기하 | `generated_partial`; 원문 치수 사용 또는 수정 필드 목록 |
| 초기 추정 | `not_performed` |
| 해석 | `not_performed` |
| 수렴 | `not_established` |
| 실측 / 제조 | 각각 `not_verified` |

이는 생성 입력에 대한 기록(`applies_to=creation_inputs`)이다. 이후 현재 객체의 직접 편집/삭제는 기존 `instances[].changes`로 별도 표시한다. 과거 생성 사본의 원문 치수 일치를 현재 형상의 검증으로 확대하지 않는다. CAD/STEP는 기존 `generated_unverified` 계약을 사용하며 RF 합격을 만들지 않는다.

G003 TI DN007/SWRU120D도 원문 p.2 Figure 1-1/Table 1-1과 본문을 확인했다. H/W/L 치수, 1 mm FR-4 및 기준 보드의 50 ohm 관측이 있지만, 실제 전체 ground/board와 적층은 companion CC2430DB CAD가 필요하다. 현재 단순 평면 IFA의 일정 선폭/직선 가지로 그 도면을 치환해 G003 재현 완료로 등록하지 않았다. 이 검토를 추가 문헌 카드의 구현/수용 증거로 합산하지 않는다.

초기 합성식이나 주파수 기반 추천 치수는 이번에 추가하지 않았다. G031의 원문 기하 유도식은 공진/정합의 초기 합성식이 아니다. 목표 주파수로 스케일하거나 미정 유효 유전율을 채우지 않는다. 식별 EQ와 적용 범위, 필요한 물성/환경 입력 및 별도 검증이 갖춰진 후 3번의 후속 범위로 추가한다.

## 입력과 저장 계약

기존 `template.list/get/context/synthesize/apply`를 그대로 사용한다. 새 card schema는 `rfad.template-card/0.2`, generator는 `rfad.literature-geometry/0.1`이다. 기존 내장 카드 0.1과 hash는 그대로다. project/origin/candidate profile은 각각 기존 0.3/0.1/0.1을 유지한다.

0.2는 닫힌 `reference_inputs`와 `evidence`를 추가한다. G031 0.1의 고정 원문/치수 대응을 validator에서 검사한다. 재열기와 undo/redo는 원문 파일이나 현재 카드 조회를 필요로 하지 않는다. 출처 해시는 내용 식별/무결성 기준이며 제조사 서명이나 독립 물리 검증 증거가 아니다.

- `offset_x`, `offset_y`: mm 숫자 문자열 또는 기존 Quantity. 두 필드는 기본값 없이 사용자가 배치 이동량을 지정한다. 0 이동도 명시해야 한다. 기존 board frame 안에서 평행 이동만 지원한다.
- 나머지 11개 치수: `{"source":"card"}`는 해당 카드 원문 Quantity의 명시 선택이다. 저장 상태는 `source_default`이며 source refs를 가진다.
- 숫자 문자열/Quantity로 수정할 수도 있다. 기존 원문 refs와 사용자 refs를 유지하고 원문과 다른 `source_default`는 `user_entered`로 구분한다. `requested_inputs`에는 실제 요청 원문을 보존한다.
- GUI는 서비스의 `display_value`를 보여주고 그 문자열이 그대로이면 source marker를 전달한다. 단위 환산/수치 비교는 서비스가 수행한다. 배치 필드를 source marker로 채울 수 없다.
- 직접 좌표의 표시에는 원문 정밀도를 유지하면서 float 잔여 자리를 제거한다. SI Quantity를 다시 쓰지 않으며, 같은 Quantity를 나타내는 이전 표시 문자열 사본도 읽을 수 있다. 원문과 다른 표시값이나 Quantity는 검증에서 거부한다.
- 원문 치수, 해시/원문 줄, 수정 입력, 정규 Quantity, 배치/기하식과 생성 사본을 프로젝트 소유 origin에 보존한다. 신규 문헌 사본은 입력에서 다시 생성한 객체와도 일치해야 한다.
- 실제 보드 경계, round cap, 양의 inner radius, CCW sweep 및 stub-원호 끝 도체의 접촉을 검사한다. 전층 제조 DRC나 임의 기존 패턴과의 간격 검사는 아니다.
- 현재 문헌 카드는 `port:null`만 지원한다. 생성 후 기존 급전 편집으로 이어간다.

검토 hash는 카드/원문/입력/배치/현재 개정/선택 목표를 함께 묶는다. 입력을 바꾸면 다시 미리 보아야 하며 한 명령의 적용/undo/redo와 멱등 receipt를 사용한다. 다른 객체/출처와 과거 snapshot/raw를 지우지 않는다. 출처 256 KiB, 프로젝트 512 KiB와 기존 source-file/byte 예산도 유지한다. 초과 시 차단하며 출처를 조용히 제거하지 않는다.

## GUI와 재현

`원호 / IFA` 화면의 카드 목록에서 `G031 / PCA20006 원호와 stub (부분 기하)`를 고른다. `/ 원문` 입력과 출처/가정/생략 항목을 확인하고 도체층 및 배치 이동 X/Y를 지정한다. 읽기 전용 2D 후보에는 서비스가 생성한 실제 도형을 표시한다. 원문 치수를 수정하면 수정 필드와 각각의 미검증 상태를 보여준다. 적용 뒤 기존 속성/2D/3D/급전 편집과 저장을 사용한다.

```powershell
.venv/Scripts/python.exe -X utf8 tools/verify_literature_sources.py --report .local/literature-sources.json
$env:PYTHONPATH = 'src;tests'
.venv/Scripts/python.exe -X utf8 -m unittest test_literature_templates test_template_candidates -v
$env:RFAD_CAD_PYTHON = (Resolve-Path '.venv-cad/Scripts/python.exe').Path
.venv/Scripts/python.exe -X utf8 -m unittest test_template_native.TemplateNativeTests.test_g031_sources_survive_real_step_and_runtime_free_reopen -v
```

원본 검증 도구는 source/member 크기를 먼저 제한하고 해시/해당 줄을 검사한다. PDF의 페이지 번호는 참조 위치이며 도구가 시각 검수를 수행했다는 뜻이 아니다. 이번 검토는 같은 해시의 p.1-3을 PNG로 렌더해 직접 확인했다. 정상 제품 후보 생성은 원본 ZIP이나 PDF runtime을 읽지 않는다.

실행 결과와 최종 범위는 [개발 상태](development_status.md) 및 별도 `runtime_profiles/literature-templates.json`에 기록한다. RO4350B 국부 방사 도체 2.788446%의 2% 기준 미확립, GHz PTH 독립 정확도 미확립과 제작/측정 미정 상태를 유지한다. Linux GUI, R2/R3와 전체 R1 수용은 후속이다.
