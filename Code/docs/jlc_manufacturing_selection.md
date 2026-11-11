# JLCPCB 제작 후보와 물성 채택 경계

조사일: 2026-11-11 KST. 승인 기준선 RFAD-D0-3.4와 기존 직접 입력 기능을 유지한다. 이 문서는 공개 제조사 자료를 비교한 후속 검증 후보 기록이다. 실제 주문 확정, 제작 실측 또는 안테나 성능 합격 기록이 아니다.

추천 후보는 JLCPCB 고주파 서비스의 Rogers RO4350B, 2층, 30 mil 코어다. 명목 코어 0.762 mm와 양면 각 0.035 mm 동박으로 CAD 검증용 기하를 정의할 수 있다. 공개 자료만으로 목표 대역의 모든 RF 입력과 마스크/표면처리 모델을 확정할 수 없어 실제 제작 재료의 해석 물성 채택값은 `null`로 남긴다. 관측과 설계 선택의 원본은 [후보 JSON](../fixtures/manufacturing/jlc_ro4350b_candidate.json)이다.

사용자는 제조사 자료를 근거로 한 탐색용 근사 모델을 허용했다. 가정과 생략 항목을 명시하고 제조/측정 검증과 구분하는 조건이다. 따라서 실제 제작 물성이 미정인 후보 기록과 별도로 근사 프로필을 만들어 통합 경로를 계산할 수 있다. 근사 결과가 후보의 실제 물성 `null`을 확정값으로 바꾸지는 않는다.

## 후보 비교와 추천 이유

| 후보 | 확인한 근거 | 판단 |
| --- | --- | --- |
| 기존 JLC0206 / NP-155F 계산기 템플릿 | 코어 0.500 mm와 Dk 4.48. 목표 대역 Df와 실제 주문 소재 대응 미정 | 기존 CAD 연결 검증 기록으로 유지 |
| RO4350B 30 mil | JLC 공개 고주파 서비스와 Rogers 원본 데이터시트가 연결됨 | 후속 제작/해석 모델 선정의 우선 후보 |
| RO4350B 60 mil | 같은 소재의 두꺼운 표준 코어 | 별도 기구 요구가 생길 때 비교할 후보 |
| JLC ZYF 계열 PTFE | 고주파 서비스에 등급별 옵션 존재 | 이번 우선 후보에서 제외. 등급별 물성과 제작/모델 조건을 별도로 확인해야 함 |

JLC는 RO4350B와 ZYF 계열을 2층 고주파 서비스로 안내한다. 일반 FR4 주문의 재질 표기도 여러 등급이므로, 계산기의 NP-155F 명칭을 실제 주문 재질 보장으로 해석하지 않는다. [JLC 고주파 서비스](https://jlcpcb.com/pcb-fabrication/high-frequency-pcb), [JLC UL 재질 표기](https://jlcpcb.com/help/article/ul-certification).

승인 초기 IFA 입력은 40 x 60 mm, 완성 두께 1.0 mm 목표다. [초기 IFA fixture](../fixtures/design/initial_ifa.json)의 0.93 mm 유전체 잔여값은 실제 코어가 아니다. 공개 0.9 mm 완성 두께 후보가 1.65 mm 후보보다 이 목표에 가까워 30 mil 코어를 추천한다. 이 판단은 설계 선택이며 기존 승인 fixture를 수정하거나 1.0 mm 제작 목표를 달성했다고 표시하지 않는다.

## 코어, 완성 두께와 공정 옵션

| 항목 | 후보 또는 관측 | 해석 경계 |
| --- | --- | --- |
| 순수 코어 표준 | 0.030 inch, 원문 반올림 0.76 mm | 정확 단위 환산 0.762 mm |
| 코어 표준 허용차 | +/-0.0020 inch | 환산 +/-0.0508 mm. 실제 JLC 납품 허용차 확정 아님 |
| 60 mil 대안 | 0.060 inch, 원문 1.52 mm, +/-0.0040 inch | 환산 1.524 mm, +/-0.1016 mm |
| 동박 | JLC 1 oz, Rogers 표준 ED cladding 35 um | JLC 실제 foil 등급, 도금 후 분포와 전도도는 미정 |
| CAD 층 합계 | 0.035 + 0.762 + 0.035 = 0.832 mm | 코어와 구리만 포함 |
| 완성 두께 후보 | 0.9 mm | 30 mil과의 현재 주문 대응은 제작사 확인 필요 |
| 공정 후보 | 녹색 마스크, 흰색 실크, ENIG, 금 1 microinch | 실제 주문 조합과 Ni/마스크 상세는 미확정 |

표준 코어와 cladding 수치는 [Rogers 표준 데이터시트 4쪽](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf)에 근거한다. 특정 JLC 주문품의 보증값으로 바꾸지 않는다.

현재 [JLC 고주파 서비스 표](https://jlcpcb.com/pcb-fabrication/high-frequency-pcb)는 두께를 0.65/0.9/1.65 mm로 적지만 해당 열에서 코어/완성 기준을 설명하지 않는다. [2023-03-09 출시 안내](https://jlcpcb.com/news/rogers-ptfe-high-frequency-pcb-available)는 0.51/0.76/1.52 mm와 별도로 완성 두께 0.6/0.9/1.65 mm를 명시한다. [현재 RF 설계 안내](https://jlcpcb.com/blog/rf-pcb-design)는 앞의 코어 규격을 20/30/60 mil로 설명한다. 0.9 mm는 두 완성/서비스 목록에 공통이지만, 첫 규격 0.6/0.65 mm 차이는 해소되지 않았다.

0.832 mm와 0.9 mm의 차이를 코어, 구리, 마스크 또는 도금에 자동 배분하지 않는다. 금 1 microinch의 0.0254 um 환산은 가능하지만 니켈 두께나 실제 도금 전도도를 알게 되는 것은 아니다. [일반 능력표](https://jlcpcb.com/capabilities/pcb-capabilities/)의 1 mm 미만 완성 두께 허용차 +/-0.1 mm도 코어 허용차와 다른 항목이다.

전용 고주파 표는 최소 드릴 0.2 mm, 선폭/간격 0.10/0.10 mm를 제공한다. 실제 급전/단락 via의 pad, annular ring, 도금, 완성 홀과 위치 허용차는 최종 DFM 조건과 함께 확인해야 한다. 이상 포트를 물리적 제작 급전으로 취급하지 않는다. [JLC 고주파 제작 능력](https://jlcpcb.com/pcb-fabrication/high-frequency-pcb).

## RF 관측값과 모델 입력의 구분

| RO4350B 관측 | 원문 조건 | 현재 채택 상태 |
| --- | --- | --- |
| Process Dk 3.48 +/-0.05 | Z, 10 GHz, 23 C, clamped stripline, IPC-TM-650 2.5.5.5 | 목표 대역 값으로 자동 사용하지 않음 |
| Design Dk 3.66 | Z, 8-40 GHz, Differential Phase Length Method | 2.4 GHz 상수 모델 채택에는 근거/근사 선택 필요 |
| Df 0.0031 | Z, 2.5 GHz, 23 C, IPC-TM-650 2.5.5.5 | 가장 가까운 관측. 목표 대역 보증 아님 |
| Df 0.0037 | Z, 10 GHz, 23 C, 같은 시험법 | 2.5 GHz 관측과 분리 보존 |
| 체적저항률 1.2e10 MOhm.cm | COND A, IPC-TM-650 2.5.17.1 | 추가 RF 전도도로 자동 채택하지 않음 |

관측은 [Rogers 원본 표준 데이터시트 3쪽](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf)의 조건과 함께 보존한다. 원문은 대표값을 모집단 평균으로 설명한다. 설계 Dk, 공정 Dk 및 서로 다른 주파수의 Df를 동일한 시험값으로 합치지 않는다. 표의 Z 방향을 X/Y 또는 검증된 등방성으로 확대하지 않는다.

설계 대역 2.4000-2.4835 GHz와 이상 lumped 50 ohm 포트는 승인 기준에서 가져오는 설계 선택이다. 이 선택으로 재료의 적용 대역이 확정되지는 않는다. 현재 [PCB solver 계약](pcb_solver_contract.md)의 등방성 상수 모델에 연결하려면 별도 채택 기록이 필요하다. 후보 JSON의 `material_model`은 실제 제작 재료에 한정되므로 `relative_permittivity`, `loss_tangent`, 추가 유전체 전도도, 도체 전도도와 재료 적용 대역을 `null`로 유지한다.

허용된 탐색 근사는 별도 프로필에 Design Dk 3.66과 Df 0.0031의 원문 조건을 남기고, 목표 대역의 등방성 상수로 사용하는 외삽을 명시하는 방식이다. 기준 구리 전도도를 사용한다면 JLC 실측값과 분리해 원출처와 온도 조건을 기록한다. Df 전체 손실 모델에서 별도 추가 전도도를 사용하지 않는 선택도 물성이 0이라고 확인한 것과 구분한다. 마스크, ENIG, 거칠기와 실제 급전 구조의 생략을 실행 결과까지 전달해야 한다.

체적저항률의 역수를 RF 손실항으로 넣거나, 관측이 없다는 이유로 유전체 전도도 0 및 일반 구리 전도도를 채우지 않는다. Df가 나타내는 손실과 별도 전도도를 어떤 방식으로 분리할지 명확해야 한다. JLC도 해당 RF 소재의 foil profile이 능력표에 명시되지 않았음을 설명한다. [JLC 표면 손실 안내](https://jlcpcb.com/blog/managing-pcb-skin-effect-loss).

## 현재 모델과 제조 형상의 차이

| 항목 | 공개 정보 또는 부족 입력 | 현재 처리 |
| --- | --- | --- |
| 솔더마스크 | 색만으로 수지 등급, 목표 대역 Dk/Df, 두께, 개구 형상 확정 불가 | 현 PCB 투영/해석 모델에서 별도 층 미지원 |
| ENIG | Ni/Au 적층 물성, Ni 두께와 RF 표면 손실 미확정 | 구리 단층으로 무조건 대체하지 않음 |
| OSP 대안 | 일반 능력표에는 존재하나 RF 전용 표는 ENIG만 표기 | RO4350B+OSP 주문 가능으로 표시하지 않음 |
| 재료 방향/분산 | 원문 조건이 방향과 주파수별로 나뉨 | 현재 상수/등방성 모델과 동일하다고 표시하지 않음 |
| 동박 거칠기 | 실제 foil과 표면 모델 미정 | 매끈한 일반 구리 모델을 제조 확정값으로 표시하지 않음 |

ENIG와 마스크 조건은 [전용 고주파 서비스](https://jlcpcb.com/pcb-fabrication/high-frequency-pcb), OSP와 일반 조건은 [일반 능력표](https://jlcpcb.com/capabilities/pcb-capabilities/)에서 확인했다. 이 두 페이지의 옵션을 임의 조합하지 않는다. 견적 화면 조합을 확인할 연결된 브라우저가 없어 주문 조합은 검증하지 못했다. 주문, Gerber 업로드, 제조사 연락과 결제는 수행하지 않았다.

JLC가 링크한 [RO4350B 이름의 PDF](https://rs.jlcpcb.com/static/file/rogers-ro4350b-datasheet.pdf)는 TICER TCR 저항박 변형 자료다. 이를 일반 RO4350B 동박 등급이나 현재 JLC 공급 foil의 증거로 사용하지 않는다. 표준 RO4350B와 LoPro, TICER를 구분해 보존한다.

## 통합 검증에 연결하는 순서

1. 후보 JSON의 원문 관측과 별도 기하 선택을 보존해 새 프로젝트를 만든다. 기존 JLC0206 기록과 승인 초기 IFA 입력을 덮어쓰지 않는다.
2. 코어/동박 명목값으로 CAD와 STEP을 검증하되 결과를 코어/구리만의 기하 모델로 표시한다. 실제 마스크/ENIG 포함 완성 PCB 검증으로 표현하지 않는다.
3. 미정 물성과 미지원 제작 층을 사전 진단한다. 관측값만 있어도 실행 허용값이 자동 완성되도록 하지 않는다.
4. 목표 대역과 방향에 맞는 물성 근거, 실제 동박/적층 정보를 확보하거나 사용자가 허용한 탐색 근사 모델을 별도 개정으로 저장한다. 근사 해석에서 생략한 공정 층, 출처, 적용 범위와 제한을 결과에 보존한다.
5. 허용되는 모델로 같은 스냅샷의 CAD/STEP/openEMS/결과 재열기를 수행한다. 계산 성공, 격자/경계 수렴, 제작 공차, 측정 일치를 각각 구분한다.

탐색 근사의 사용자 허용은 실제 주문 확정이나 제조/측정 검증 승인과 다르다. 구체적 근사값과 실행 근거는 별도 프로필, [통합 검증 문서](catalog_pcb_integration.md) 및 해당 실행 보고서에 남긴다. 이 후보 기록은 원본 자료 디렉터리와 승인 문서를 변경하지 않는다.

## 탐색 근사 통합 검증 결과

2026-11-11에 별도 탐색 모델의 CAD 생성, AP242 STEP 출력/재입력, 실제 WSL openEMS, 독립 후처리와 결과 재열기를 완료했다. 전체 보고서는 `passed`이며 물리 평가 상태는 `computed_unvalidated`다. 실제 납품 재료의 미정값은 그대로 남겼다. 실행 파일과 결과 해시는 [탐색 검증 실행 기록](../runtime_profiles/jlc-ro4350b-exploratory.json)을 따른다.

| 구분 | 실제 실행 기록 |
| --- | --- |
| 입력 보고서 | `.local/manufacturing-source-review/ro4350b-input.json` |
| 통합 보고서 | `.local/manufacturing-source-review/ro4350b-integration.json` |
| 모델 물성 | Design Dk 3.66, 총 손실 Df 0.0031, 기준 구리 58 MS/m; 모두 별도 탐색 선택 |
| 기하 | 40 x 60 mm IFA의 기존 XY, 코어 0.762 mm, 양면 동박층 각 0.035 mm 정의 |
| CAD/STEP | 2개 body, STEP/BREP 재입력과 출처/hash 확인 통과. 같은 OCCT 커널 사용 |
| 평가 설정 | 2.4000-2.4835 GHz 51점, grid 0.5 mm, air padding 8 mm, 곡선 허용오차 0.025 mm |
| 종료 설정 | 최대 50000 step, 에너지 비 0.0001 |
| 실제 계산 | 격자점 639693개, Yee 구간 셀 612864개, 4805 step, 에너지 감소 42.08 dB로 종료 기준 도달 |
| 후처리/재열기 | 독립 후처리의 51개 표본 일치, 카탈로그 및 worker 없는 서비스 재시작에서 결과 복원 |

두 동박층이 정의되어 있어도 하부 접지면은 자동 생성하지 않는다. 이번 fixture에는 상부 도체 형상과 코어가 있어 CAD body는 2개다. 모델 층 높이 0.832 mm와 실제 완성 명목 0.9 mm의 차이를 기하에 배분하지 않았다.

프로젝트에는 탐색 모델 2개와 실제 납품 물성이 미정인 재료 2개를 분리했다. 후자의 Dk/Df/전도도/적용 대역은 `null`이고 해석 층에 연결하지 않았다. 탐색 유전체는 Df 전체 손실 모델을 선택하여 독립 전도도를 미정으로 보존하고 추가 가산하지 않는다. 기준 구리 58 MS/m는 20 C의 100% IACS 기준이며 JLC 실측값이 아니다. 근거는 [NBS Copper Wire Tables](https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e2.pdf)이며 선택 이유와 URL을 프로젝트에 보존했다.

42.08 dB는 시간영역 에너지 감소이며 S11 또는 안테나 성능 합격 수치가 아니다. `formal_convergence_tested=false`, `manufacturing_validated=false`, `physics_validated=false`를 유지한다. 이 실행은 새 소재의 격자/경계 거리 수렴, 제작 공차 검증, 방사 효율/이득 또는 측정 일치를 입증하지 않는다.

그대로 재사용한 형상의 S11은 2.4000 GHz에서 약 -3.877 dB, 2.4835 GHz에서 약 -2.740 dB이며 각각 이번 표본의 최저/최고값이다. 이 결과는 계산 경로가 연결되었다는 증거이고, 목표 대역에 정합을 마친 안테나 설계가 아니다.

## 탐색 입력과 실행 재현

Windows PowerShell의 현재 디렉터리는 `C:\Users\eidos\GitHub\TraceWave Studio\Code`로 둔다. 서비스 `.venv`, 격리 `.venv-cad`, 전체 자료를 가져온 `.local/pcb-catalog/catalog.sqlite`와 Qt 없는 `TraceWave-Dev` WSL openEMS 환경이 필요하다. 생성기는 근사 수용 옵션을 생략하면 실행을 거절하며 기존 workspace와 보고서를 덮어쓰지 않는다.

```powershell
$caseRoot = Join-Path (Get-Location).Path ('.local/manufacturing-source-review/ro4350b-' + [guid]::NewGuid().ToString('N'))
$inputReport = Join-Path $caseRoot 'input.json'
.\.venv\Scripts\python.exe -X utf8 tools/create_jlc_ro4350b_verification.py `
  --workspace (Join-Path $caseRoot 'workspace') `
  --report $inputReport `
  --database '.local/pcb-catalog/catalog.sqlite' `
  --accept-approximations
if ($LASTEXITCODE -ne 0)
{
    throw 'RO4350B 탐색 입력 생성 실패'
}
$case = Get-Content -LiteralPath $inputReport -Raw -Encoding utf8 | ConvertFrom-Json
$settingsPath = Join-Path $caseRoot 'settings.json'
[System.IO.File]::WriteAllText(
    $settingsPath,
    ($case.settings | ConvertTo-Json -Depth 10),
    [System.Text.UTF8Encoding]::new($false)
)
```

설정 JSON은 UTF-8 BOM 없이 기록한다. `settings`는 생성 보고서에 보존된 명시 주파수/격자/종료 조건이며 제조 물성을 채우는 옵션이 아니다.

WSL은 단발 `/bin/true` 뒤 종료될 수 있어 검증 동안 별도 stdin 연결로 유지한다. 다음 명령은 기존에 사용한 Python keepalive 방식을 `full` 명령 주위에 묶는다. 새 실행별 marker를 사용하고, 성공/실패 모두 `finally`에서 marker를 만들고 stdin을 닫는다. `full`의 900초 제한과 준비 메시지 대기의 120초 제한을 분리했다. GUI나 제품의 자동 복구 코드가 아니다.

```powershell
@'
import json
import subprocess
import sys
import threading
from pathlib import Path

input_report = Path(sys.argv[1])
settings_file = Path(sys.argv[2])
case = json.loads(input_report.read_text(encoding='utf-8'))
release = input_report.parent / 'wsl-keepalive.release'
if release.exists():
    raise RuntimeError('Choose a fresh execution directory')
keeper = subprocess.Popen(
    ['wsl.exe', '--distribution', 'TraceWave-Dev', '--user', 'tracewave',
     '--exec', '/usr/bin/python3', '-u', '-c',
     "import sys; print('ready', flush=True); sys.stdin.read()"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NO_WINDOW,
)
ready = []
reader = threading.Thread(
    target=lambda: ready.append(keeper.stdout.readline().strip()), daemon=True
)
try:
    reader.start()
    reader.join(timeout=120)
    if reader.is_alive() or ready != [b'ready']:
        raise RuntimeError('WSL keepalive did not become ready')
    result = subprocess.run(
        [sys.executable, '-X', 'utf8', 'tools/verify_catalog_pcb.py',
         '--workspace', case['workspace'], '--project', case['project_path'],
         '--expected-revision', case['snapshot']['revision_id'],
         '--mode', 'full', '--cad-python', '.venv-cad/Scripts/python.exe',
         '--openems-wsl', '--settings-file', str(settings_file),
         '--report', str(input_report.parent / 'integration.json')],
        timeout=900, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError('Inspect integration.json for failure or missing inputs')
finally:
    release.write_text('done', encoding='utf-8')
    keeper.stdin.close()
    try:
        keeper.wait(timeout=15)
    except subprocess.TimeoutExpired:
        keeper.terminate()
        keeper.wait(timeout=10)
'@ | & '.\.venv\Scripts\python.exe' -X utf8 - $inputReport $settingsPath
if ($LASTEXITCODE -ne 0)
{
    throw 'WSL 준비 상태와 통합 검증 보고서를 확인하십시오.'
}
```

별도 native 대조군의 첫 실행에서는 WSL cold start 중 10초 control timeout으로 중단되었다. 실패 기록은 `.local/manufacturing-source-review/native-total-loss.log`, 준비 후 성공 기록은 `native-total-loss-warm.log`에 보존했다. 실제 성공 시에는 별도 keepalive 프로세스가 준비 후 최대 900초 또는 release marker 생성까지 stdin 연결을 유지했다. 해당 helper의 준비 대기에는 별도 제한이 없었다. 위 재현 wrapper는 같은 유지 방식을 사용하되 준비 대기 상한을 추가했으며, 문서 구문만 검사하고 추가 native 실행은 하지 않았다.

이 준비 절차는 검증 환경의 우회 방법이다. 제품의 cold-start 대기, 중단 상태 확인과 자동 복구 개선은 아직 해결되지 않았다. 성공한 물성 모델 계산과 이 런타임 제한을 별도 항목으로 추적한다. `.local` 보고서와 산출물은 로컬 검증 증거이며 Git에는 실행 요약과 해시를 기록한다.
