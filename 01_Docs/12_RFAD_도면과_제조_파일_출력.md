# 2D, STEP, EDA, 제조 출력 상세 설계

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

관련 문서: [아키텍처](07_RFAD_소프트웨어_아키텍처.md), [수식](09_RFAD_수식과_물리_모델.md), [검증](14_RFAD_검증과_수용_기준.md).

## 1. 공통 생성 순서

snapshot 고정 -> 표현식 평가 -> analytic primitive -> planar region/Boolean -> 연결, DRC -> physical layer solid -> format projection -> 임시 파일 생성 -> 별도 reader 재입력 -> 비교, manifest 발행 순으로 처리한다. 표시 mesh, solver mesh, DXF/Gerber chord approximation은 서로 다른 허용오차다.

원호는 중심선 반지름, signed sweep, width로 정의하고 양쪽 offset을 계산한다(EQ-001/002). join/cap과 겹치는 feed segment는 Boolean union 후 도체 영역과 connectivity를 계산한다. 원호 길이+급전선 길이를 겹침 고려 없이 물리적 전기 길이로 단정하지 않는다. undercut/측벽/도금은 실제로 선택한 fabrication model만 반영한다.

## 2. tolerance 세 종류와 budget

| 값 | 의미 | 소유하는 profile |
| --- | --- | --- |
| tauCAD | 고체/좌표/기하 교환의 수치 허용오차 | kernel/STEP profile |
| tau2D | 벡터 좌표 양자화와 곡선 근사 허용오차 | DXF/SVG/Gerber profile |
| taufab | 실제 PCB 제작 치수 변동 | 제조사/공정 profile |

tauCAD=0.001 mm 등 B의 값은 기준 PCB에서 검증할 초기 후보다. kernel tolerance, source grid, 최소 gap, 동박 thickness, writer precision을 함께 검토한다. import된 G031은 원본 grid와 endpoint quantization이 있으므로 원문 재현 허용오차와 writer왕복 오차를 한 값으로 덮지 않는다. tauCAD가 gap이나 copper thickness를 소실시킬 정도이면 export를 차단하거나 사용자가 명시한 더 높은 정밀도 profile을 적용한다.

곡선 chord error, coordinate quantization, Boolean tolerance가 누적되는 budget을 남긴다. 단순 모든 오차를 무조건 더하는 conservative check와 실제 roundtrip 측정 결과를 구분한다. topology 보존은 작은 좌표 오차 여부와 별도로 검사한다.

## 3. 2D 기술 도면

PDF는 용지/축척을 갖는 기술 도면, SVG/DXF는 `drawing`과 `fabrication_geometry` profile을 구분한다. 1:1 패턴 파일에 표제란, 글자를 구리 영역으로 포함하지 않는다.

필수 view: top pattern/outline, bottom 및 내층 선택, stackup section, 필요한 feed/short/gap 상세. 원호 반지름, 각도, 폭, PCB 외곽, critical gap, via/slot, 원점/축, 단위, 공차, 개정, scale bar를 표현한다. 치수는 원본 parameter/geometry에 연결하고 사용자가 도면의 숫자만 독립 수정하지 않게 한다. annotation override는 실제 치수와 구분해 표시한다.

PDF 인쇄의 '페이지에 맞춤' 결과는 프로그램이 제어하지 않으므로 축척과 기준 길이를 표시한다. SVG에는 물리 width/height와 viewBox를 명시한다. DXF에는 INSUNITS/profile, layer names, polyline width/region 규칙, 지원 entity types를 선언한다. arc를 line segment로 내보내면 chord tolerance와 segmentation report를 남긴다.

## 4. STEP physical profile

### 4.1 객체와 적층

1. dielectric/core/prepreg/coating은 physical coverage와 z bounds를 이용해 solid를 만든다.
2. layer의 conductor region은 지정한 finished copper thickness로 extrusion한다. 같은 layer의 접속 도체는 net별로 union할 수 있지만 객체 mapping은 보존한다.
3. pad의 화면 구분을 위한 추가 높이를 physical thickness에 더하지 않는다.
4. hole은 해당 board/layer/body에서 제거한다. plated barrel은 실제 범위의 annular solid로 만들며 unknown plating은 추정/미정 상태를 표시한다.
5. 비아 fill은 원래 fill/material 조건이 있을 때만 생성한다. 중공 via를 단순 solid cylinder로 채우지 않는다.
6. mask/coating, 부품, 배터리/케이스의 포함은 export preview와 assembly hierarchy에 표시한다.

별도 body 이름은 stable ID와 역할을 포함하고 assembly 이름 변경과 의미 mapping이 독립적이어야 한다. copper body를 substrate와 fusion해 재질 구분을 잃는 옵션은 RF physical profile에서 허용하지 않는다. 여러 net body의 fusion도 connectivity 보고와 별개 선택이며 기본은 분리다.

### 4.2 STEP schema

기준 writer는 CadQuery/OCCT이며 AP242를 우선 검증 대상으로 한다. 설치한 binding/writer에서 해당 profile이 실제 지원되는지 R0에서 확인한다. AP214 등 fallback은 지원 profile과 data-loss report가 있는 경우만 제공한다. writer 설정, 단위, assembly names/colors, validation properties의 실제 보존 범위를 파일을 다시 열어 확인한다. 표준 이름을 적는 것만으로 AP242 모든 의미가 구현됐다는 뜻이 아니다.

STEP는 mesh가 아닌 B-rep solid를 내보내야 하며 shape validity, solid count, bbox, volume, center, section, hole, layer thickness를 비교한다. body order만으로 source entity를 매핑하지 않는다. RF 물성/port/net/analysis 의미는 [sidecar](08_RFAD_데이터_모델과_파일_형식.md)에 남긴다.

공식 근거: [CadQuery 입출력](https://cadquery.readthedocs.io/en/latest/importexport.html), [OCCT STEP translator](https://occt3d.com/dev/doc/overview/html/occt_user_guides__step.html). writer 선택과 검수 항목은 본 제품의 설계 결정이다.

### 4.3 수신 도구와 독립성의 범위

출시 profile에는 writer와 reader의 제품, 버전, CAD kernel, 지원 schema, 단위와 검수할 속성을 각각 기록한다. 같은 writer로 재입력한 결과, 다른 프로그램이 같은 OCCT kernel로 읽은 결과, 다른 kernel을 사용하는 수신 CAD의 결과를 구분한다. Gmsh의 OCC 경로는 OCCT를 사용하므로 CadQuery/OCCT와의 비교를 kernel 독립 검증으로 표시하지 않는다. 근거: [Gmsh OCC API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fmodel_002focc).

R0에서는 별도 reader와 독립 산술 기대값을 갖춘 작은 fixture로 교환 계약을 확인한다. R1에서는 지원을 선언할 수신 CAD/version별 재열기와 실제 선택, 측정, 숨김, 조립 배치를 확인한다. 다른 kernel을 사용할 수 없으면 그 한계를 기록하고, 시험한 수신 도구 범위의 호환성으로만 결과를 제한한다. 커널 독립성 자체를 충족하지 못한 상태를 독립 물리 정확도 합격으로 바꾸지 않는다.

STEP의 `FILE_SCHEMA`와 실제 표현을 검사하며 파일 확장자나 요청한 옵션만으로 schema를 판정하지 않는다. B-rep의 외면 방향, 닫힘, 빈 고체, 자기 교차, 중복 바디, 유전체와 동박의 부피 중첩을 검사한다. CAD가 자동 치유한 경우 치유 전후 차이를 별도 기록한다. 파일 순서와 face index는 의미 ID가 아니므로 source UUID와 output body의 대응은 sidecar와 검수 결과로 유지한다.

## 5. KiCad 교환 계약

KiCad 10 계열 profile을 우선 검증한다. file parser/writer는 [공식 S-expression board format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/)의 버전과 실제 reopen 결과를 함께 사용한다. 최소 지원 subset은 outline/cutout, layer stack mapping, net, line/arc track 또는 검증된 copper region, pad, through-via, mask/paste 설정, footprint placement다. board와 footprint 출력은 다른 profile이다.

안테나 copper를 F.SilkS나 단순 graphic line으로만 내보내지 않는다. arbitrary polygon은 net이 있는 지원 copper 객체로 매핑하고 실제 fill 결과를 검수한다. RF 패턴의 thermal relief/zone smoothing/clearance가 원본 형상을 바꾸지 않게 export profile을 명시한다. KiCad의 zone refill 전후를 비교하고 의도하지 않은 branch/gap 변화는 실패다.

complex curve를 여러 arc/line으로 근사하면 길이, area, 최소간격, 연결을 비교한다. unknown external object는 import report에 보존/생략/변환 여부와 편집 제한을 표시한다. 지원하지 않는 blind/microvia 등을 through-via로 조용히 치환하지 않는다.

### 5.1 KiCad STEP을 사용하는 경우

KiCad 10 CLI 문서에는 conductor 포함 옵션과 추가 pad 높이를 비활성화하는 설정이 명시돼 있다. 이 외부 경로를 쓸 때도 physical profile은 copper, 내층, holes, 실제 두께를 다시 검사해야 한다. [KiCad CLI](https://docs.kicad.org/10.0/en/cli/cli.html).

특히 표시를 위해 추가되는 pad 높이, via fill, net filter, point-merge tolerance, origin, shape fusion 선택은 고정 profile에 저장한다. 기본값을 그대로 쓰면 RF critical geometry가 바뀔 수 있으므로 CLI 문서만으로 검수 완료로 처리하지 않는다. native RFAD STEP writer와 KiCad 경유 STEP을 별도 경로로 비교하는 fixture를 둔다. 같은 OCCT 기반 경로이면 kernel 독립성은 주장하지 않는다.

KiCad CLI의 `--include-soldermask`와 `--include-silkscreen`은 평면 face 출력으로 문서화되어 있다. 따라서 해당 옵션만으로 실제 두께를 가진 coating/mask solid 요구를 충족했다고 판정하지 않는다. 마스크 부피가 필요한 physical profile은 별도 solid 생성 경로를 사용하거나 해당 항목을 미지원으로 표시한다. `--fill-all-vias`는 도체층에서 비아 구멍을 절개하지 않는 옵션이므로 실제 금속 충진 공정의 재료 및 배럴 형상 증거로 사용하지 않는다. `--no-extra-pad-thickness`, 병합 거리, copper 포함 옵션은 명시적으로 저장하고 설치 버전의 도움말과 재입력 결과로 확인한다. 근거: [KiCad STEP 출력 옵션](https://docs.kicad.org/10.0/en/cli/cli.html).

## 6. Gerber, 드릴, Gerber Job

Gerber X2 copper/mask/outline와 Excellon drill을 기본 CAM profile로 한다. 실제 채택한 format revision과 reader/writer version을 manifest에 저장한다. [Ucamco 공식 형식](https://www.ucamco.com/en/gerber), B-S35/S36의 Layer/Job 명세를 근거로 검사한다.

Gerber는 층별 제조 이미지이고 모든 RF semantics를 담는 해석 포맷이 아니다. X2 attributes와 Gerber Job의 material stackup/design rules는 가능한 범위에서 기록하되 주파수 의존 모델, ports는 sidecar로 유지한다. 제조사별 필요 profile이 있으면 versioned configuration으로 둔다.

| 항목 | 처리 규칙 |
| --- | --- |
| unit/format | 명시적 unit, coordinate format/precision/zero suppression, origin 기록 |
| polarity | dark/clear operations를 실제 planar region으로 재파싱해 비교 |
| arc | 지원 원호 명령 또는 기록된 tolerance의 segmentation; endpoint/center 일관성 검사 |
| layers | file function/side/order, copper/mask/outline 역할 대응 |
| drill | PTH/NPTH 분리, tool와 finished-hole 의미 구분, slot route 계약 |
| net 정보 | 보존 가능한 attribute를 사용하되 CAM 이미지에서 net 의미가 부족하면 원본 mapping을 유지 |
| holes | bore가 없는 filled via로 바뀌지 않게 CAD/drill/STEP 대응 검사 |
| quantization | 최소 gap, width가 파일 grid 때문에 사라지지 않는지 계산 |

## 7. 정합 BOM과 assembly variant

AUG-004의 R2 기능은 part ID, manufacturer part number, value/unit, package/footprint, model revision, DNP/short/installed state, tolerance, xy/rotation/side/assembly origin을 같은 circuit revision에 연결한다. 튜닝에서 선택한 회로와 출력 BOM이 달라지면 export를 invalidated로 표시한다. pad/copper 배치가 바뀌면 raw EM 재계산 여부를 판정한다. 부품 값만 바뀌어 external network로 표현된 경우에는 raw를 재사용할 수 있다.

## 8. roundtrip 검증 알고리즘

1. source snapshot에서 expected regions/bodies/holes/net graph와 critical dimensions를 추출한다.
2. 생성 파일을 writer와 별도 경로의 reader로 다시 읽는다. 같은 kernel 재열기는 문법, geometry 경로 시험이지 완전한 독립 solver 검증이 아님을 표시한다.
3. unit/frame/origin/side transform을 복구하고 비교 좌표계로 정렬한다. 최적 정렬로 잘못된 축척/미러링을 숨기지 않는다.
4. bbox/area/volume/center, symmetric difference, boundary distance, 층 두께와 hole/VIA 단면을 측정한다(EQ-039).
5. connected component, net adjacency, critical gap, expected short/open을 비교한다. Hausdorff 오차가 작아도 topology가 바뀌면 실패다.
6. tauCAD/tau2D와 profile의 topology 규칙으로 판정하고 누락 body/material/속성은 별도 보고한다.
7. 실패한 파일은 preview/debug artifact로 보존하고 verified manufacturing package에 넣지 않는다.

## 9. 출력 status와 완료 조건

`preview_only`, `generated_unverified`, `verified_profile`, `failed`를 구분한다. 유효한 geometry-only STEP을 얻었더라도 RF 효율이나 제작업체 공정 합격을 의미하지 않는다. 검증 완료에는 source/export hashes, reader/version, comparison profile, numerical differences, 미평가 항목을 포함한다.

R1 완료 fixture는 원호, IFA short/feed gap, 서로 다른 copper thickness, 최소 gap, 다층 inner copper, PTH/NPTH, via barrel, slot, bottom mirroring, mm<->mil, 한국어 path를 포함한다. 실제 제조 업체에 파일을 발주하는 것은 소프트웨어 roundtrip 시험과 별도다.

## 10. 큰 출력의 자원 한도와 원자적 발행

내보내기는 고정 snapshot을 읽는 작업으로 실행하며 UI thread에서 Boolean, STEP 직렬화, PDF 생성 또는 재입력을 수행하지 않는다. 미리보기와 결과 파일의 소유자를 분리하고 동일 geometry의 B-rep, tessellation, IPC 복사본을 무제한 중복 유지하지 않는다. 파일별 또는 body별 처리와 임시 디스크 사용, 메모리 예측, 취소 경계, 종료 후 자원 회수는 [GUI 및 성능 계약](24_RFAD_GUI_선정과_성능_설계.md)에 따른다. 병합은 연결 의미에 필요할 때만 수행하며 모든 body를 한 번에 fusion하는 동작을 기본으로 두지 않는다.

패키지는 임시 디렉터리에서 생성하고 파일별 hash, 필수 파일 존재, 상대 경로, 재입력 판정과 snapshot 일치를 확인한 뒤 최종 manifest를 마지막에 발행한다. 같은 파일시스템의 atomic rename 지원 여부를 확인하며 다른 볼륨 복사를 원자적 이동으로 가정하지 않는다. 취소, 디스크 부족, 쓰기 실패 또는 crash 때 마지막 정상 패키지는 유지한다. 진행 중 파일은 `partial`로 표시하고 복구 검사 전 완성본으로 열지 않는다.

정상 geometry 생성과 제조 전달 승인은 구분한다. 실패한 필수 검수, 미정 필수 두께/단위, 누락된 필수 body가 있는 패키지는 `verified_profile`을 가질 수 없다. 보고서에 미평가 범위를 기록하는 것만으로 필수 검수 실패가 면제되지 않는다. VT-007/008/009/018/019에서 이 동작을 검수한다.
