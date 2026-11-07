# 데이터 모델, 단위, 저장 형식 명세

개정: 3.0 / 2026-11-07 KST / 상태: 사용자 검토용 설계안

관련 문서: [아키텍처](07_RFAD_소프트웨어_아키텍처.md), [수식](09_RFAD_수식과_물리_모델.md), [검증](14_RFAD_검증과_수용_기준.md).

## 1. 원본과 파생물

원본은 `ProjectDocument`와 그 안의 의미 있는 객체다. CAD B-rep, 표시 삼각형, solver mesh, native solver input, STEP/Gerber, 결과 배열은 원본에서 파생한다. 외부 STEP/Gerber를 가져오면 import source와 mapping을 갖는 새 의미 모델을 만든다. 외부 파일에 없는 net/material/port 의미를 알고 있는 것으로 만들지 않는다.

본 문서의 type과 field는 구현 계약이다. 배열/반복 객체 안에 여러 값을 가지므로 입력 변수 사전의 항목 수와 DB column 수는 일치하지 않는다. [원문 자료 연계](20_RFAD_참고_자료_통합.md)의 136개 A 필드 및 79개 B 입력 묶음 대응표를 함께 사용한다.

## 2. 공통 타입

| 타입 | 필수 필드, 규칙 |
| --- | --- |
| EntityId | UUID 문자열. 저장, export, result에서 stable. 사용자 이름과 별개 |
| Quantity | `value_si`, `dimension`, `display_unit`, `status`, `source_refs`, 선택 `expression`, `uncertainty_ref`, `conditions` |
| ComplexQuantity | `real_si`, `imag_si`, `dimension`, `phasor_convention`, `status`; 소수점 문자열을 복소수로 추측하지 않음 |
| FrequencyTable | 증가하는 `frequency_hz`, value array, unit/complex convention, validity range, interpolation policy, uncertainty |
| Provenance | source ID/version/hash/location, extracted record ID, original value/unit/text, 사용자 변경 및 시각, source vs derived 구분 |
| Transform | 오른손 frame ID, SI translation, 정규 직교 rotation, 선택 explicit reflection. 회전과 scale을 혼용하지 않음 |
| ArtifactRef | ID, project-relative URI, SHA256, bytes, media_type, producer, snapshot/run/profile IDs, status |
| Diagnostic | code/severity/entity IDs/field paths/message/details/remediation |
| ValidationEvidence | test ID/version, fixture/input hash, toolchain, result/artifact refs, metric definition, tolerance/profile, status |

`status`는 `user_entered`, `source_default`, `estimated`, `missing`, `not_applicable`, `unsupported`, `conflicting`이다. null은 숫자 0이 아니다. `missing`에는 value를 채우지 않는다. `conflicting`은 선택 후보와 선택 사유를 보존하며 unresolved일 때 mandatory 계산 입력으로 사용하지 않는다. 계산에 사용했는지는 projection의 `consumption_report`에서 `used`, `approximated`, `omitted`, `not_applicable`, `blocked`로 따로 기록한다.

## 3. 단위와 수치 규약

- 내부 length=m, frequency=Hz, time=s, angle=rad, impedance=ohm, conductivity=S/m, power=W. dB는 선형 물리량과 구분된 표시/metric 타입이다.
- 입력 단위 변경은 동일 물리값을 보존한다. mm->m 변환은 CAD adapter 경계에서 중복 수행하지 않는다. CAD kernel에는 명시한 mm profile을 사용하고 scale factor 1000 및 역변환 0.001을 기록한다.
- 각도는 world +Z 기준 오른손 회전으로 정의한다. PCB 평면은 XY. bottom view 미러링은 view/export transform이며 source geometry를 뒤집지 않는다.
- canonical numeric 값은 float64이다. 단위 없는 정수 turn count/port index는 integer이며 음수/소수를 구별한다. 원문 표기와 원문 grid precision은 provenance에 유지한다.
- 로그나 plot 표시를 위해 임의의 작은 값을 물리값에 덧붙이지 않는다. `-inf`처럼 의미 있는 표시값은 배열 mask/status로 표현하며 JSON에 NaN/Infinity를 쓰지 않는다.
- 도메인의 주파수 phasor는 RMS, 시간 규약은 exp(+j*omega*t). 원시 파일의 규약은 별도 보존하고 검증한 변환만 수행한다. instantaneous 시간 값, 무차원 S행렬에 RMS 변환을 적용하지 않는다.

### 3.1 표현식 문법

지원 노드: 숫자+단위, 변수 참조, 괄호, `+ - * / **`, 허용 함수 `sqrt`, `sin`, `cos`, `tan`, `atan2`, `abs`, `min`, `max`, `clamp`, 명시된 상수 `pi`, `c0`. `sin/cos` 입력은 angle 또는 명시한 dimensionless radian이다. 제곱근과 지수는 차원 유효성을 검사한다. 대입, loop, attribute access, 파일, import, network, shell, 임의 함수 호출은 이 문법에 없다.

파싱->기호해결->차원검사->DAG cycle검사->정의역검사->topological evaluate 순서로 수행한다. 0 나누기, sqrt 음수, 최대 크기 초과, 미정 변수는 field diagnostic이다. 화면 drag로 계산된 치수를 고정 숫자로 만들지, 표현식을 수정할지는 명령에 명시한다. expression text와 마지막 평가값, dependency IDs, engine version을 보존한다.

## 4. ProjectDocument

| 경로 | 내용 | 필수성 |
| --- | --- | --- |
| `schema_version`, `project_id`, `revision_id`, `parent_revision_ids` | 스키마와 개정. snapshot_id는 SnapshotRef의 별도 UUID | 항상 |
| `metadata` | 이름/설명/작성 및 수정/사용자 설정 참조 | 항상 |
| `frames` | world/board/manufacturing/assembly/measurement frames와 변환 | world+board 필수 |
| `parameters` | Quantity/ComplexQuantity/enum 및 표현식 DAG | 항상 |
| `board` | outline, cutouts, region IDs, thickness convention | 기판 설계 필수 |
| `stackup` | ordered layer ID, role, z_min/z_max, thickness, material, finished/base status | EM/STEP 필수 |
| `geometry` | primitive/region/solid instance 및 parameter binding | 항상 |
| `nets`, `connections` | 기대 연결과 실제 검사 대상 | conductive design 필수 |
| `materials` | 프로젝트에 고정한 버전/모델/조건 | EM 필수 |
| `ports` | physical ports, native 역할, 기준 도체, reference plane | EM 필수 |
| `networks` | 외부 회로, load/source, parts, state | 선택 |
| `environment` | battery/case/fixture/body placement와 electrical contact | 사용 시 |
| `targets` | 주파수, metric, 범위, threshold, 규칙 | 설계목표 사용 시 |
| `analysis_definitions` | solver profile, mesh/boundary/termination/observables | 해석 시 |
| `optimization_studies` | 변수, 제약, 목적, budget, scenario, seed | 최적화 시 |
| `measurement_sets` | 원본 파일, 교정, 정렬, 조건 metadata | 측정 시 |
| `manufacturing_profiles`, `export_profiles` | DRC 및 출력 형식/대상 | 제조/출력 시 |
| `source_references`, `assumptions`, `validation_profiles` | 근거, 가정, 검증 기준 | 항상, 빈 경우 상태 명시 |
| `extensions` | adapter namespace의 부가값 | optional; core override 금지 |

필수성이 'EM 필수'인 데이터가 없더라도 geometry-only project 저장과 2D 편집은 가능하다. 실행, 제조, STEP별 preflight가 각 입력을 검사한다. 모든 프로젝트에 불필요한 인체, UWB, NFC 값을 억지로 요구하지 않는다.

## 5. 주요 entity 상세

### 5.1 GeometryEntity와 토폴로지

공통: `id`, `kind`, `role`, `frame_id`, `layer_id`, `net_id`, `parameter_bindings`, `source_ref`, `include_in_em`, `include_in_export`, `material_ref`.

| kind | 세부 필드와 규칙 |
| --- | --- |
| `line_path` | start/end, width profile, cap/join style, physical cross-section |
| `arc_path` | center, centerline radius, start angle, signed sweep, width profile; inner radius와 폭의 자기교차 검사 |
| `polyline_path` | line/arc segments 순서, junction type, width/join, 연결 허용오차 |
| `planar_region` | outer boundary와 holes, winding, Boolean 결과, layer 및 net |
| `via` | start/end layer, finished bore, tool bore, plating thickness/status, pads/antipads, fill/material, stub |
| `pad` | pad shape/size/rotation/layers/net, mask/paste margin, 실제 finished thickness |
| `solid_instance` | source artifact+hash, body selection, transform, material, electrical contacts, simplification |
| `keepout` | shape/layer range, copper/component/mechanical role별 금지, 의도된 예외 |

surface/face ID는 `{entity_id, semantic_role, construction_feature}`로 참조한다. CAD face index와 exporter entity number는 해당 projection의 mapping에만 저장한다. model rebuild 후 포트 face를 찾을 수 없으면 자동으로 '가장 가까운 face'에 붙이지 않고 E_PORT를 반환한다.

### 5.2 Layer와 MaterialModel

Layer는 `role=conductor|dielectric|coating|adhesive|air`, ordering, z bounds, physical thickness, material ID/version, region coverage, manufacturing construction을 갖는다. z bounds와 thickness 둘 다 저장할 경우 한쪽을 authoritative로 지정하고 나머지는 derived로 계산한다. 별도로 입력해 불일치한 값을 동시에 적용하지 않는다.

MaterialModel에는 원본 data와 solver용 evaluated model을 분리한다. 원본: Dk/Df 또는 epsilon*/mu*/sigma, 시험/설계값 구분, frequency/temperature/orientation/lot/measurement method, uncertainty/source. evaluated model: type, coefficients, domain, fitting residual, passivity check, loss partition, adapter version. `tan_delta`에서 `sigma(f_ref)`로 바꾸는 narrowband 모델은 원본 tan_delta의 전체 대역 동일 모델이 아니다. 독립 DC conductivity와 dielectric loss를 합칠 때 의미가 겹치는지 검사한다.

roughness에는 metric type(Ra/Rq/Sq/Rz/모델계수), 적용 면(top/bottom/side), measurement bandwidth/conditions, selected model이 필요하다. 어떤 지표든 '거칠기 um' 한 숫자로 변환하지 않는다. anisotropy tensor는 좌표 frame을 갖고 solver가 실제 지원하는 성분/회전만 허용한다.

### 5.3 Port, Network, Excitation

Port 공통: ID, conductor/reference conductor, geometry/face anchor, outward/inward direction, polarity, type, reference plane, mode, frequency validity, physical resistance/native parameters. `network_reference_z0`는 physical lumped resistor와 별도다.

NetworkData: frequency axis, complex matrix, parameter kind S/Z/Y, port IDs/order, Z0 array shape `[Nf,Nport,2]`, wave definition, current sign, reference planes, reciprocity/passivity applicability, original data artifact. 외부 매칭 회로에는 nodes, ports, component model/value/SRF/Q/S-data, DNP/short state, physical pad 포함 여부, assembly variant와 BOM 대응을 저장한다.

ExcitationSet: 주파수별 incident wave vector 또는 특정 native excitation, port basis order, source/load conditions, 위상/진폭, power normalization, time waveform/phase origin. time-domain waveform과 frequency-domain a-vector 변환 방법도 기록한다.

### 5.4 AnalysisDefinition와 RunRecord

AnalysisDefinition: backend/runtime/capability profile IDs, selected snapshot, material projection, solver units, coordinate mapping, mesh rules, air/PML/symmetry, port basis, excitation band, analysis/evaluation frequencies, probes/NF2FF, stopping rules, resource limits, approximation policy.

RunRecord: run ID, plan ID/hash, snapshot/revision, raw key, job state, times, native exit reason, mesh statistics, actual resource usage, toolchain hashes, native input/output refs, normalization contract, diagnostics, validation evidence. solver exit code와 residual convergence criterion을 각각 기록한다.

### 5.5 MetricRecord와 Assessment

MetricRecord: definition/version/EQ IDs, input artifact hashes, units, axes, reference/normalization, valid masks, interpolation flags, uncertainty, numerical status. Assessment: target/profile/version, metric IDs, evaluated domain, pass/fail/not_evaluated/conditional, missed samples, violated constraints. target 변경 시 MetricRecord가 같아도 Assessment ID는 달라진다.

## 6. 프로젝트 폴더와 archive

| 경로 | 역할 |
| --- | --- |
| `project.json` | 현재 commit된 설계 원본 |
| `snapshots/<revision>/project.json` | 불변 설계와 provenance |
| `sources/`, `materials/`, `imports/` | 허용된 참조 데이터와 source manifest |
| `runs/<run_id>/plan.json` | 실제 실행 계획 |
| `runs/<run_id>/native/` | native 입력, 원시 출력, 로그 |
| `runs/<run_id>/normalized/` | 통일된 network/fields/metadata |
| `derived/<key>/` | 외부 network, metric, assessment 결과 |
| `exports/<export_id>/` | profile, 파일, 검증 보고서 |
| `index.sqlite` | 검색/작업 색인. 원본에서 복원 가능 |
| `manifest.json` | 파일별 hash/bytes/type/version/source 상태 |
| `recovery/` | autosave 및 비정상 종료 회복 자료 |

인계 archive는 `.rfad.zip`을 사용한다. zip 내부에는 absolute path, `..`, symlink escape, 중복 canonical path를 허용하지 않는다. decompressed size/entry count 제한은 명시된 ImportPolicy에서 검사한다. 외부 참조를 복사하지 않은 경우 missing 상태와 재확보 URL/hash를 manifest에 남긴다. archive 내부 스크립트를 프로젝트 열기만으로 실행하지 않는다.

## 7. 결과 배열과 파일 형식

| 파일/데이터 | 기본 저장 계약 |
| --- | --- |
| normalized network | HDF5 frequency_hz[Nf], s[Nf,Np,Np,2]에서 axis1=outgoing i, axis2=incident j, 마지막=re/im. z0[Nf,Np,2], ordered port_ids |
| S-column completeness | excitation별 incident amplitude, valid frequency mask, solve origin. 열이 없는 matrix는 missing으로 보존 |
| near fields | freq/time axis, coordinate grid/points, E/H component labels, complex real/imag or instantaneous values, unit, frame, normalization |
| far-field basis | [Nexc,Nf,Ntheta,Nphi,2,2] (theta/phi polarization, real/imag), angular weights, phase center/radius, basis_a[Nf,Nport,Nexc,2], port/excitation IDs와 reference planes |
| current | surface/volume/line current type에 맞는 A/m, A/m^2, A 단위; shape mapping |
| Touchstone | 지원 profile에 맞는 complex network export. header/option line/port order/reference impedance/unit/version 보존 |
| CSV | UTF-8, 고정 column schema 및 units metadata. 복소 값은 re/im columns; localized comma decimal 금지 |
| VTK 등 viewer 데이터 | 표시용 geometry/field projection이며 physical/solver 원본은 별도 |

basis_a의 각 열은 해당 field excitation에서 실제 입사한 a-vector다. unit power-wave identity basis인지 native basis인지 normalization tag와 amplitude unit을 기록한다. 원하는 입사벡터 a_req에 대해 basis_a*c=a_req를 정의된 조건수/rank 검사 후 풀고, 같은 c로 복소 field를 합성한다. port order와 excitation order를 동일하다고 무조건 가정하지 않는다. rank 불충분한 magnitude-only 자료는 합성에 사용할 수 없다.

HDF5 real/imag axis는 마지막 dimension 2로 고정해 reader 간 complex dtype 차이를 피한다. frequency/angle grid가 다르면 join 전에 명시적 resampling record를 만든다. 평가 가능한 구간 밖을 extrapolate한 값은 mask 없이 유효 데이터로 저장하지 않는다. far-field는 magnitude만 있으면 위상 필요 metric(ECC의 적절한 복소 적분, loaded pattern, array 합성)을 지원한 것으로 보지 않는다.

Touchstone 1.x/2.x 지원은 parser가 실제 검증한 profile로 선언한다. 복소/주파수별 Z0, wave definition, 별도 measurement metadata를 파일 하나가 완전 전달한다고 가정하지 않고 sidecar에 보존한다. official 형식은 [IBIS Touchstone](https://ibis.org/touchstone_ver2.1/touchstone_ver2_1.pdf), library 변환은 [scikit-rf](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.Network.renormalize.html)를 확인한다.

## 8. STEP/CAM sidecar 계약

`schema_version`, `export_id`, `snapshot_id`, `profile_id`, `files[{name,sha256}]`, `units`, `frames/transforms`, `object_mapping`, `stackup`, `material_refs`, `net_mapping`, `physical_thickness`, `omissions`, `simplifications`, `roundtrip_evidence`를 필수로 한다. EM 설정은 reference로 연결한다. STEP material name/density와 주파수 의존 RF material 모델을 구분한다. STEP 재입력 시 해시가 다르면 이전 sidecar를 자동 적용하지 않는다.

## 9. schema와 migration

JSON Schema로 자료형, 필수키, enum, 참조형식을 검증하고, 도메인 validator로 단위, 연결, 주파수 유효성, 층 높이, graph cycle을 검증한다. JSON Schema 통과만으로 전자기학적 모델 유효성을 선언하지 않는다. unknown extension은 보존하되 해당 기능의 실행을 제한한다. 필수 core field가 해석 불가하면 쓰기 모드로 열지 않는다.

schema 변경 시 migration ID/version/input hash/output hash/변경 목록과 미변환 필드를 보존한다. 원본 backup이 성공하기 전에 overwrite하지 않는다. 각 지원 구버전 fixture를 최신 버전으로 변환하고 다시 열어 의미 비교를 수행한다. 새 형식으로 저장한 것을 구버전 앱이 그대로 열 수 있다는 역호환을 자동 약속하지 않는다.

## 10. 출처와 계약 근거

저장 구조, Quantity 타입, hash 의존성은 본 제품의 설계다. STEP semantic 전달 범위는 [OCCT STEP translator](https://occt3d.com/dev/doc/overview/html/occt_user_guides__step.html), PCB 객체 형식은 [KiCad board format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/), 제조 형식은 [Ucamco 공식 Gerber](https://www.ucamco.com/en/gerber)를 기준으로 adapter 지원표를 고정한다.

## 11. 정규 직렬화와 설정 우선순위

canonical encoding의 규범 구현은 application service 하나다. UTF-8, 정렬된 object key, 버전 있는 finite float64 표현, -0.0의 0.0 정규화, ID 문자열, 의미 있는 배열 순서를 사용한다. 층 순서/포트 순서/geometry path 순서는 정렬하지 않는다. 집합으로 정의된 ID 목록만 규정된 정렬을 사용한다. 입력 숫자를 표시 자릿수로 반올림한 결과를 hash하지 않는다. 일반 JSON encoder의 기본 출력이 곧 canonical 규격인 것은 아니다.

integer count/index는 범위가 있는 정수로 저장한다. 언어 사이에서 정확히 보존하지 못하는 큰 정수 식별자는 decimal string으로 표현한다. GUI는 hash를 다시 계산하지 않고 snapshot UUID/revision/hash를 함께 받아 응답이 현재 요청과 일치하는지 검사한다. UTF-8 경로/이름 원문을 임의 정규화해 외부 파일을 같은 것으로 합치지 않는다.

설정의 우선순위는 명시적인 job override > project에 고정한 profile > versioned application default다. 물리값에는 숨은 global default를 적용하지 않는다. 실행 직전 모든 resolved 설정과 출처를 PreparedPlan에 고정하고, UI 개인 설정은 물리 hash에 넣지 않는다. 프로젝트를 다른 PC에서 열어도 기존 물성/version은 자동 갱신되지 않는다.

## 12. 배열의 수명과 부분 읽기

HDF5 dataset에는 dtype/endianness/shape/chunk layout/compression/version을 명시한다. normalized complex numeric 기본형은 float64 real/imag이며 표시용 float32 projection을 만들 경우 그 역할과 오차를 따로 기록한다. UI는 metadata와 요청한 ROI/chunk만 읽고 파일 크기만큼 메모리를 선할당하지 않는다. 실제 read/decompress 비용은 worker budget에 포함한다.

ArtifactRef의 SHA256은 파일 전체와 연결한다. import 직후 검증되지 않은 대용량 파일은 unverified로 두고 hash 계산은 background에서 진행한다. 빠른 미리보기와 계산 입력 승격을 구분한다. 내부 생성 artifact는 producer가 완전히 닫은 후 hash/manifest를 게시하며, 이후 read-only로 취급한다. 외부 수정 가능 파일은 계산 입력 승격 전에 private staging으로 복사해 봉인한다. 실제 소비할 같은 byte 집합의 hash를 계산하고 immutable artifact ID를 부여한다. 검증 후 원본 경로를 다시 열어 소비하지 않아 검사-사용 사이 변경을 막는다. 파일명/mtime만으로 신뢰하지 않는다.

동시에 쓰는 HDF5의 partial 데이터는 정상 완료 결과 경로로 열지 않는다. live preview가 필요하면 명시된 전용 stream/preview artifact를 사용하고 run 완료 시 불변 파일로 봉인한다. 여러 프로세스가 같은 HDF5를 갱신하지 않는다. 결과 정리 시 snapshot/run/export가 참조하는 파일과 active reader lease를 확인한다.

## 13. 저장, 복구, 삭제의 경계

여러 파일로 된 저장은 temp staging에 payload를 기록/flush하고 hash를 확인한 뒤 commit manifest 또는 current-revision pointer를 마지막에 게시한다. 단일 파일 rename의 atomicity를 프로젝트 전체 transaction 보장으로 확장하지 않는다. 같은 volume의 rename, 잠금, 전원/디스크 오류 시 durability는 플랫폼 fixture에서 검증한다. SQLite는 색인이며 journal/manifest에서 재생성한다.

autosave는 recovery draft이고 사용자가 확정한 project revision이나 실행 snapshot을 바꾸지 않는다. undo 이력과 cache는 항목/byte budget을 가지며 저장한 기준점과 현재 편집을 보존한다. disk-full 상태에서는 마지막 정상본을 유지하고 임시 산출물을 완성본으로 publish하지 않는다.

cleanup은 원본/측정/source/파생 artifact를 역할별로 표시하고 삭제 영향 및 회수 크기를 제공한다. 파생물이라도 active lease 또는 보존된 report가 참조하면 직접 삭제하지 않는다. archive/migration은 원본을 보존한 새 destination에 수행한다. 일반 프로젝트 열기는 외부 script 실행이나 plugin 설치를 유발하지 않는다.

## 14. 준비 작업과 native 단위

TaskPlan.kind의 em_prepare는 AnalysisPlan을 입력으로 받고 완료 시 PreparationArtifact와 PreparedPlan을 반환한다. em_analysis는 PreparedPlan을 요구하며 execution_mode는 solve_and_postprocess 또는 postprocess_only다. 후자는 완결 raw manifest가 있어야 하며 raw 누락을 자동 solver 실행으로 숨기지 않는다. 긴 import/변환/측정/metric 처리는 TaskPlan.kind=data_processing과 operation_method/input artifact/version을 사용하며 PreparedPlan을 요구하지 않는다. API별 반환 형태는 11의 분류표를 따르고 cache hit도 동일 TaskRef 완료 경로를 따른다. 상태 전이는 [04번](04_RFAD_시스템_명세.md), wire payload는 [11번](11_RFAD_해석기_어댑터_계약.md)을 따른다.

MaterialModel의 전기 전도도 sigma(S/m)는 native field 이름과 별도로 매핑한다. CSXCAD의 전기 손실 Kappa와 자기 손실 Sigma는 이름만 보고 교환할 수 없다. adapter manifest에는 domain quantity, native parameter, 단위, 변환식, fixture ID를 기록한다. solver에 전달한 실제 값은 consumption_report로 확인한다.
