# 카탈로그 PCB의 CAD 및 해석 통합 검증

기록일: 2026-11-11 KST. 승인 기준선 RFAD-D0-3.4와 기존 사용자 직접 입력을 유지한다. 이 문서는 `Code`의 검증 도구와 실행 근거를 설명하며 승인 문서나 최초 제작용 IFA의 물성을 변경하지 않는다.

현재 JLCPCB JLC0206 후보의 저장, CAD 형상, AP242 STEP, 표시 mesh와 재열기는 통과했다. 해당 후보의 RF 물성과 적용 대역은 미정이므로 실제 openEMS 계산은 차단했다. 별도의 합성 카탈로그에 기존 IFA 시험 가정을 담은 양성 대조군에서는 CAD부터 실제 WSL openEMS, 독립 후처리와 재열기까지 통과했다. 두 결과를 실제 제조 PCB의 전자기 성능 검증으로 합쳐 해석하지 않는다.

## 선택한 JLCPCB 후보

원본은 `00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026`의 정리된 전체 자료에서 조회한다. 선택 식별자는 다음과 같다.

| 항목 | 선택 또는 보존 값 |
| --- | --- |
| PCB 제작업체와 후보 | JLCPCB, JLC0206 |
| 공개 템플릿 ID | `a9bcabb350514c418b7c33541ef9ecfa` |
| 카탈로그 native template | `native_template:3945cd94afe2d81e4bc7fe9d41c52b96bb1cc133fe0f5f6fdfae3081c53ef2a8` |
| Dk 관측 | `PCB040237` |
| 원본 위치 | `data/fabricator_native_metadata/board_type_1_page_012.json`, `/body/list/65` |
| 재질 표기 | 계산기 응답의 Nan Ya NP-155F |
| 순수 유전체 두께 | 0.500 mm, 원문 `without copper` |
| 공칭 완성 기판 두께 | 0.600 mm, 별도 원본 값으로 보존 |
| 적용한 외층 동박 | 위/아래 각 0.035 mm, 공개 2층 1 oz 명목 사양을 명시 선택 |
| 모델 층 합계 | `0.035 + 0.500 + 0.035 = 0.570 mm` |
| 원본 코어 동박 필드 | `topConductorThick=0.03`, `botConductorThick=0.03`, 변경 없이 보존 |
| Dk | 4.48, 제조업체 계산기 공개값이며 측정 주파수는 미제공 |
| 미정 입력 | Df, 유전체 추가 전도도, 동박 전도도, 재료 및 포트의 적용 대역 |

0.035 mm는 JLCPCB의 [완성 외층 동박 2층 1 oz 옵션](https://jlcpcb.com/capabilities/pcb-capabilities), [2층 기판의 각 동박 1 oz = 35 um 설명](https://jlcpcb.com/resources/custom-pcb), [동박 중량과 두께 안내](https://jlcpcb.com/help/article/jlcpcb-copper-weight)를 근거로 채택했다. 적용 기록에 값, 이유와 URL을 남긴다. 이 값은 특정 제작품의 실측 두께 또는 보증값이 아니다.

원본의 0.030 mm 필드를 0.035 mm로 고쳐 저장하지 않는다. 별도 선택값과 원본 사본을 함께 보존한다. 모델 합계 0.570 mm와 공칭 0.600 mm의 차이를 코어 또는 동박에 자동 배분하지 않는다. 솔더마스크, 실크와 표면처리층은 이번 기하 모델에 포함하지 않는다.

NP-155F는 해당 계산기 후보의 재질 표기다. 일반 2층 주문에 이 소재가 보장되거나 이 템플릿이 현재 주문 가능한 제작 사양이라는 뜻은 아니다. [공식 계산기 안내](https://jlcpcb.com/help/article/user-guide-to-the-jlcpcb-impedance-calculator)도 계산기 재질 가정과 주문 시 소재 선택을 구분한다.

JLC 사례는 `fixtures/pcb_worker_smoke.json`의 원형 외곽, 선, 원호와 50 ohm 포트를 연결 시험용으로 재사용한다. 원래 fixture의 물성과 주파수 범위는 제거한다. 하부 동박층은 정의하지만 그 층에 접지면이나 패턴을 자동 생성하지 않는다. 급전 XY와 객체 UUID를 보존하고 상부 접면 높이 `0.035 + 0.500 = 0.535 mm`만 명시적으로 갱신한다. 이는 제조용 안테나 설계 또는 승인 IFA의 성능 모델이 아니다.

## 도구와 불변 경계

`tools/create_jlc_catalog_verification.py`는 새 workspace에만 후보를 만든다. 전체 카탈로그의 템플릿과 관측 대응, 원본 파일 SHA-256과 JSON 위치를 검사한 뒤 공개 `pcb.selection.preview`와 `pcb.selection.apply`를 사용한다. 프로젝트를 저장하고 스냅샷을 봉인하며 원본 DB와 fixture의 SHA-256이 바뀌지 않았는지 확인한다. 이 도구 자체는 CAD나 해석을 실행하지 않는다.

`tools/verify_catalog_pcb.py`는 이미 저장된 프로젝트를 대상으로 한다. PCB 선택 출처와 두 동박층 정의가 있어야 하며, 저장하지 않은 개정이나 지정한 개정과 다른 입력은 거절한다. 원본을 자동 저장하거나 물성, 두께와 해석 설정을 보완하지 않는다.

검증 실행은 다음 모듈로 나뉜다.

| 모듈 | 책임 |
| --- | --- |
| `tools/catalog_pcb_verification/common.py` | 공개 JSON-RPC 호출, 제한된 작업 대기, 봉인 자료 읽기, 보고서 원자 게시 |
| `tools/catalog_pcb_verification/runner.py` | 입력 점검, 단일 스냅샷 생성, 모드별 실행, 원본 보존과 재시작 확인 |
| `tools/catalog_pcb_verification/cad.py` | 실제 geometry/STEP 작업, 출처와 body 대응, 파일 hash, STEP/BREP 재입력 |
| `tools/catalog_pcb_verification/solver.py` | 계획/준비/실행/후처리, 원시 XML과 소비 물성 결합, 결과 및 차트 재열기 |

CAD와 해석은 동일한 `snapshot_id`와 `content_hash`를 사용한다. `source_semantics`에 프로젝트 원본 전체와 `rfad.pcb-selection`의 출처, 채택 이유, 미정값을 보존한다. 검증 종료 후 현재 프로젝트가 입력과 동일한지도 확인한다.

CAD는 `geometry.build`와 `export.build`를 각각 실제 격리 OCCT 프로세스로 수행한다. STEP, BREP, 표시 mesh, sidecar, validation과 manifest의 크기/hash, 층/재료/net/원본 객체 대응을 검사한다. 게시된 STEP/BREP는 별도 CAD 프로세스로 다시 읽고 치수, 부피, 연결 성분과 단면 위상을 비교한다. 같은 OCCT 커널을 사용하므로 `kernel_independent=false`를 유지한다.

서비스를 닫은 뒤 카탈로그 DB와 CAD/openEMS 런타임을 연결하지 않고 다시 연다. 프로젝트, 스냅샷, 선택 출처, `cad.latest`, 파일 참조와 hash를 비교한다. 해석을 수행한 사례는 `result.open`, `solver.samples`, `solver.latest`와 독립 후처리 결과도 복원한다. 이 재열기는 프로젝트에 보존된 출처 사본을 사용하므로 외부 원본 자료 디렉터리의 재조회가 필요하지 않다. workspace와 봉인 산출물 파일은 필요하다.

`result.open`은 해석 결과 조회다. CAD 표시는 `cad.latest`가 반환한 `display_mesh` 참조를 사용한다. 별도 `geometry.display` RPC는 없으며 표시 mesh를 정확한 STEP 기하나 openEMS 격자로 사용하지 않는다.

## 실행 모드와 보고서

| 모드 | 수행 내용 | 정상적으로 반환할 상태 |
| --- | --- | --- |
| `inspect` | 입력 점검, 스냅샷과 출처 재열기. native 런타임을 연결하지 않음 | `inputs_ready` 또는 `needs_inputs` |
| `cad` | 입력 점검과 실제 CAD/STEP, 재열기. solver 런타임을 연결하지 않음 | `cad_verified` 또는 `needs_inputs` |
| `full` | CAD/STEP과 EM 입력이 허용되면 실제 openEMS 및 독립 후처리, 재열기 | `passed` 또는 `needs_inputs` |

실행 오류, hash 불일치 또는 재열기 실패는 `failed`다. CLI 종료 코드는 정상 모드 완료 0, 오류 2, 입력 부족 3이다. `cad_verified`는 RF 입력이 완성되었다는 뜻이 아니며, `inputs_ready`도 실제 solver의 연결/격자 검사 합격을 뜻하지 않는다.

`full`에서 EM 입력이 미정이어도 CAD 입력이 유효하면 CAD 검증은 수행하고 결과를 보고서에 남긴다. 전체 상태는 `needs_inputs`이고 `solver` 결과를 만들지 않는다. JLC0206 사례가 이 경로에 해당한다. 전도도나 Df를 0으로 넣거나 기본 FR4/구리 값으로 채우지 않는다.

기존 보고서 경로는 덮어쓰지 않는다. 새 보고서에 `running` 상태를 예약하고, 완성된 JSON을 같은 디렉터리의 임시 파일에 기록한 뒤 flush/fsync와 원자 교체로 게시한다. 최종 기록 실패 시 이전 JSON은 남는다. 타임아웃은 취소 요청과 마지막 작업 상태를 기록하며 취소 요청 자체를 worker 종료 확인으로 취급하지 않는다.

## JLC 사례 재현

다음은 Windows PowerShell에서 `C:\Users\eidos\GitHub\TraceWave Studio\Code`를 현재 디렉터리로 사용한다. 서비스 `.venv`, 격리 `.venv-cad`와 `.local/pcb-catalog/catalog.sqlite`가 필요하다. DB가 아직 없으면 [카탈로그 오프라인 구축](pcb_catalog_contract.md)의 명령으로 전체 정리 자료를 먼저 가져온다.

새 경로를 만들어 JLC 후보를 저장한다. 동일한 생성 명령의 workspace와 report는 재사용할 수 없다.

```powershell
$caseRoot = Join-Path '.local/catalog-pcb-integration' ('jlc0206-' + [guid]::NewGuid().ToString('N'))
$inputReport = Join-Path $caseRoot 'input.json'
.\.venv\Scripts\python.exe -X utf8 tools/create_jlc_catalog_verification.py `
  --workspace (Join-Path $caseRoot 'workspace') `
  --report $inputReport `
  --database '.local/pcb-catalog/catalog.sqlite'
$case = Get-Content -LiteralPath $inputReport -Raw | ConvertFrom-Json
```

원본 경로를 바꿨다면 생성기에 `--reference-root`를 전달한다. 다른 fixture는 `--fixture`로 지정할 수 있지만 도구가 요구하는 기하/층 구성과 원본 검사를 만족해야 한다. 기본 입력은 `fixtures/pcb_worker_smoke.json`이다.

미정 물성과 원본 보존을 검사한다. 아래 명령은 현재 JLC 입력에서 종료 코드 3과 `needs_inputs`가 예상된다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_catalog_pcb.py `
  --workspace $case.workspace --project $case.project_path `
  --expected-revision $case.snapshot.revision_id `
  --mode inspect --report (Join-Path $caseRoot 'inspect.json')
```

실제 형상과 STEP만 검사하려면 `cad` 모드를 사용한다. 현재 사례의 예상 결과는 종료 코드 0과 `cad_verified`다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_catalog_pcb.py `
  --workspace $case.workspace --project $case.project_path `
  --expected-revision $case.snapshot.revision_id `
  --mode cad --cad-python '.venv-cad/Scripts/python.exe' `
  --report (Join-Path $caseRoot 'cad.json')
```

같은 입력을 `full`로 검사하면 CAD 완료 후 RF 누락 때문에 `needs_inputs`가 된다. 아래는 부족 입력의 차단을 재현하는 명령이며 solver를 실행하는 명령이 아니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_catalog_pcb.py `
  --workspace $case.workspace --project $case.project_path `
  --expected-revision $case.snapshot.revision_id `
  --mode full --cad-python '.venv-cad/Scripts/python.exe' `
  --report (Join-Path $caseRoot 'full-needs-inputs.json')
```

## 합성 IFA 양성 대조군과 실제 해석 재현

`tests/test_catalog_pcb_solver_native.py`의 IFA 시험은 `fixtures/ifa_feed_smoke.json`의 기존 물성, 두께, 포트와 격자 설정을 그대로 사용한다. 합성 카탈로그는 그 값의 시험 출처를 보존하며 JLCPCB나 다른 제조업체 관측으로 표시하지 않는다. 이 fixture도 하부 동박층에 자동 접지면을 만들지 않는다.

Qt 없는 `TraceWave-Dev` WSL openEMS와 `.venv-cad`가 준비된 환경에서 다음 특정 시험을 실행하면 양성 대조군 입력, 보고서와 workspace를 새 디렉터리에 보존할 수 있다. 지정한 출력 루트 아래 `full-<UUID>` 하위 디렉터리를 만들어 기존 결과를 보존한다. WSL 활성화와 CAD 실행 파일 명시가 모두 있어야 이 시험이 실행된다.

```powershell
$env:PYTHONPATH = 'src;tests'
$env:RFAD_TEST_WSL = '1'
$env:RFAD_CAD_PYTHON = (Resolve-Path -LiteralPath '.venv-cad/Scripts/python.exe').Path
$nativeRoot = Join-Path (Get-Location).Path ('.local/catalog-pcb-integration/synthetic-full-' + [guid]::NewGuid().ToString('N'))
$env:RFAD_CATALOG_NATIVE_OUTPUT = $nativeRoot
.\.venv\Scripts\python.exe -X utf8 -m unittest `
  test_catalog_pcb_solver_native.CatalogPcbSolverNativeTests.test_two_copper_ifa_fixture_full_cad_solver_chain -v
Remove-Item Env:RFAD_CATALOG_NATIVE_OUTPUT -ErrorAction SilentlyContinue
Remove-Item Env:RFAD_TEST_WSL -ErrorAction SilentlyContinue
Remove-Item Env:RFAD_CAD_PYTHON -ErrorAction SilentlyContinue
```

이미 생성한 양성 대조군을 CLI `full` 모드로 다시 실행하려면 보고서에 보존된 명시 설정을 사용한다. 이 설정을 JLC 미정 물성에 적용해 차단을 우회하지 않는다.

```powershell
$nativeRun = Get-ChildItem -LiteralPath $nativeRoot -Directory -Filter 'full-*' | Select-Object -First 1
$positive = Get-Content -LiteralPath (Join-Path $nativeRun.FullName 'report.json') -Raw | ConvertFrom-Json
$settingsPath = Join-Path $nativeRoot 'settings.json'
[System.IO.File]::WriteAllText($settingsPath, ($positive.settings | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
.\.venv\Scripts\python.exe -X utf8 tools/verify_catalog_pcb.py `
  --workspace $positive.workspace --project $positive.project_path `
  --expected-revision $positive.revision_id `
  --mode full --cad-python '.venv-cad/Scripts/python.exe' --openems-wsl `
  --settings-file $settingsPath --report (Join-Path $nativeRoot 'rerun.json')
```

실제 제조 후보의 `full` 실행도 같은 CLI를 사용하지만, 먼저 저장된 프로젝트에 근거 있는 RF 물성/적용 대역/급전 조건이 있어야 한다. `--settings-file`은 주파수, 격자와 종료 조건을 지정하며 재료 물성을 채우지 않는다.

## 현재 실행 근거와 검증 범위

로컬 산출물 경로는 `Code` 기준이며 `.local`은 Git에 포함하지 않는다. 전체 시험 상태의 최신 집계는 [개발 상태](development_status.md), 보고서와 최종 도구/시험 파일의 해시는 [통합 검증 기록](../runtime_profiles/catalog-pcb-integration.json)을 따른다.

| 실행 | 보고서 | 확인한 결과 |
| --- | --- | --- |
| JLC 입력 생성 | `.local/catalog-pcb-integration/jlc0206-input.json` | 전체 실제 카탈로그 선택, 원문/DB/fixture 보존, 미정값 유지 |
| JLC CAD 및 전체 입력 검사 | `.local/catalog-pcb-integration/jlc0206-integration.json` | CAD 2개 작업 통과, 3개 body, EM 9개 누락 진단, 전체 `needs_inputs`, 재열기 통과 |
| 합성 IFA 전체 연결 | `.local/catalog-pcb-integration/synthetic-full-2768a74b063846f8ae5e890fde019288/report.json` | 동일 스냅샷의 CAD/STEP, 실제 WSL 계산, 독립 후처리와 재열기 `passed` |

JLC workspace는 `.local/catalog-pcb-integration/jlc0206-workspace-03`이다. 각 보고서의 `workspace`, `project_path`, `snapshot`과 artifact의 `uri`가 정확한 프로젝트와 파일을 식별한다. STEP, BREP와 표시 mesh는 `cad.latest.result.artifacts`에서 역할별로 찾는다.

합성 IFA 실행은 2.4000~2.4835 GHz 51점, grid 0.5 mm, air padding 8 mm, 곡선 허용오차 0.025 mm, 최대 50000 step, 에너지 종료 기준 0.0001을 사용했다. 실제 계산은 4495회에서 종료 기준에 도달했고 원시 결과와 독립 후처리 표본이 동일했다. `assessment.status=computed_unvalidated`, `physics_validated=false`를 유지한다. 이 한 설정의 시간영역 종료는 격자/경계 거리 수렴, 제작 적합성, 측정 일치나 방사 패턴 정확도의 검증이 아니다.

회귀 시험은 다음처럼 실행한다. CAD 환경 변수가 설정되면 실제 CAD 시험도 포함하며 WSL native 시험은 위의 별도 명령으로 실행한다.

```powershell
$env:PYTHONPATH = 'src;tests'
$env:RFAD_CAD_PYTHON = (Resolve-Path -LiteralPath '.venv-cad/Scripts/python.exe').Path
.\.venv\Scripts\python.exe -X utf8 -m unittest `
  test_catalog_pcb_cad test_catalog_pcb_solver test_catalog_pcb_integration -v
```

시험은 미정 RF 물성과 필수 형상 두께의 분리, 출처 및 물성 소비 보존, 변경된 worker/XML 거절, 원시 자료와 후처리 표본 비교, 저장 파일 손상, 재열기, 미저장 개정/개정 충돌, 기존 보고서 보호와 원자 기록 실패를 다룬다. 순수 계약 시험과 실제 native 실행을 구분하며 기존 제조업체 전체 자료가 모두 해석 가능한 입력이라는 뜻으로 확대하지 않는다.

## 다음 물성 및 제작 조건 확정

1. 선택할 실제 JLC 제작 서비스의 소재 등급, 순수 코어와 완성 동박 두께, 허용차 및 표면처리를 확인한다. 계산기 후보와 주문 가능한 사양의 대응을 남긴다.
2. 선택한 코어의 Dk/Df 관측에 주파수, 시험법, 방향, 시편 두께와 재질 조건을 결합한다. 다른 NP-155F 계열 등급이나 1 GHz/10 GHz 값을 2.4 GHz 값으로 자동 대입하지 않는다.
3. 유전체 추가 전도도와 동박 전도도를 근거와 함께 채택한다. 현재 solver가 소비하는 항목은 [PCB solver 계약](pcb_solver_contract.md)을 따르며 미정 추가 전도도를 묵시적으로 0으로 바꾸지 않는다.
4. 재료와 포트 적용 대역, 실제 급전 기준면/좌표, 평가 대역 및 격자/경계 조건을 명시하고 프로젝트의 새 개정으로 저장한다. 이전 스냅샷과 결과는 유지한다.
5. 완성된 입력으로 `full`을 실행한 뒤 새 선택 조건의 격자/경계 거리 수렴과 제작/측정 비교를 수행한다. 제조용 IFA 및 방사 결과의 물리 검증은 별도 단계다.
