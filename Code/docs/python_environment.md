# Python 개발 환경

승인 기준선 RFAD-D0-3.4의 서비스/CAD worker 경계를 유지한다. 대상은 Windows x64 CPython 3.12이며 실제 설치 검증은 3.12.10에서 수행한다. 이 구성은 개발 환경용이다. 제품 배포 manifest, 라이선스 고지 묶음, solver 환경 완료를 뜻하지 않는다.

## 분리와 재현

| 경로 | 용도 | 설치 범위 |
| --- | --- | --- |
| `.venv` | 프로젝트 서비스와 도메인 시험 | 표준 라이브러리 기반 제품 코드, editable 설치를 위한 setuptools |
| `.venv-cad` | 별도 호스트 CAD worker, native 기하 시험과 개발 smoke | CadQuery 2.8.0/cadquery-ocp 7.9.3.1.1 및 해결된 전체 기본 의존성 44개 |
| `runtime_profiles/python-service-build.*` | 서비스 빌드 도구 고정 | setuptools 80.9.0 wheel 버전과 SHA256 |
| `runtime_profiles/python-cad-windows-x64.*` | CAD 설치 고정 | 전체 전이 의존성 버전, Windows x64/Python 3.12 wheel과 SHA256 |
| `.local/python/` | 각 머신의 설치 및 smoke 근거 | pip 계획/실제 설치 보고서와 검사 결과. Git 제외 |

Code 디렉터리에서 PowerShell로 실행한다.

```powershell
.\tools\setup_python.ps1
```

Python 실행 파일을 지정하려면 `-Python 'C:/path/to/python.exe'`를 사용한다. 서비스만 준비하려면 `-SkipCad`를 지정한다. 스크립트는 Code 안에 가상 환경을 만들고 기존 환경의 Python 버전, 운영체제, 아키텍처, 격리 상태를 확인한다. 호환되지 않는 환경은 오류로 중단하며 지우거나 전역 패키지를 변경하지 않는다.

CAD 설치는 먼저 `pip --dry-run --ignore-installed --report`로 전체 계획을 생성한다. 버전, wheel 파일명, SHA256을 manifest에 대조하고 Qt 관련 배포가 없는지 확인한 후 `--require-hashes --only-binary=:all:`로 설치한다. 따라서 다른 운영체제나 Python minor 버전에는 이 lock을 재사용하지 않는다. 실제 설치 후 `pip check`와 STEP smoke를 실행한다.

설치 파일의 해시는 배포 archive 재현을 위한 것이다. 설치 후 검사는 패키지 버전과 Qt runtime DLL 부재를 확인하며 모든 설치 파일의 변조를 탐지하는 보안 검사는 아니다. pip 자체는 Python 가상 환경에 포함된 버전을 사용하고 실제 resolver 버전은 manifest에 기록했다.

## Qt와 시작 비용

CQ-editor, PyQt, PySide는 설치하지 않는다. CadQuery 2.8.0의 기본 의존성을 임의로 누락시키지 않고 전체 패키지를 별도 CAD 환경에 설치한다. 이 조합에는 VTK, trame, NumPy, SciPy, Numba 등이 포함된다. 이들은 CAD 환경에 저장되는 의존성이며 서비스/GUI가 시작할 때 함께 import하지 않는다.

검사 스크립트는 Qt binding 배포, Qt runtime DLL과 실제 로딩한 Qt 모듈이 없는지 확인한다. VTK 등의 wheel에 포함된 선택적 Qt 연동용 Python 소스는 Qt runtime 설치나 사용과 구분한다. GUI는 별도 C++ wxWidgets 구성이다.

## 실제 CAD 검사

```powershell
.\.venv-cad\Scripts\python.exe -I -X utf8 tools/check_cad_environment.py --output .local/python/cad-smoke.json
```

검사는 아래 순서를 실행한다.

1. 설치된 모든 CAD 의존성의 버전을 고정 manifest와 대조한다.
2. 10 x 20 x 1.6 mm 박스를 만들고 유효한 B-rep인지 확인한다.
3. 임시 STEP 파일로 출력하고 같은 CadQuery/OCCT reader로 재입력한다.
4. FILE_SCHEMA, 유효 B-rep, solid 1개, 각 변 길이와 320 mm3 체적을 확인한다.
5. 실제 버전, 결과 치수, FILE_SCHEMA, 파일 SHA256과 import 시간을 JSON에 기록한다.

치수 절대 허용차는 1e-6 mm, 체적 절대 허용차는 1e-6 mm3, 상대 허용차는 각각 1e-9다. import 시간은 단일 실행의 환경 관찰값이며 승인된 시작 시간/메모리 예산 합격 판정으로 사용하지 않는다. STEP 임시 파일은 검사 후 삭제한다.

2026-11-07 Windows 11 AMD64/CPython 3.12.10에서 전체 설치 스크립트 재실행, 두 환경의 `pip check`, 실제 STEP 왕복 검사가 통과했다. CadQuery 2.8.0과 cadquery-ocp 7.9.3.1.1의 기본 출력은 AP214의 `AUTOMOTIVE_DESIGN` schema였다. 재입력 결과는 10 x 20 x 1.6 mm, 320.0000000000001 mm3, 유효 solid 1개였으며 Qt 패키지/DLL/로딩 모듈은 모두 없었다. 설치 계획에서 Qt 추가, 버전 변경, SHA256 변경, 패키지 누락을 각각 넣었을 때 설치 전 검사에서 거부되는 것도 확인했다.

서비스 환경에는 pip, setuptools, tracewave-studio만 설치되었고 서비스 모듈 import 후 CadQuery/OCP/NumPy/SciPy/VTK/Qt는 로딩되지 않았다. CAD 최초 import는 이 머신에서 약 30초가 관찰되었다. 현재 제품 CAD 연결도 이 분리를 유지하며 무거운 import는 별도로 시작하는 CAD 프로세스 안에서만 수행한다. 단일 smoke의 import 시간과 제품 전체 시작/메모리 성능 수용은 구분한다.

위 박스 검사는 같은 OCCT 기반 writer/reader의 초기 개발 환경 호환성 기록이다. 이후 제품 adapter에서 직사각 유전체, 양수 두께 선/원호와 완전 원환, 명시적 층 위치, 안정 body 이름과 원본 RF 의미 sidecar를 구현했다. AP242를 명시적으로 요청하고 실제 FILE_SCHEMA와 mm 단위, 별도 OCCT reader의 형상/이름 재입력을 확인한다. 같은 kernel이므로 독립 수신 CAD 검증은 아니며 결과는 내부 기하 profile의 `generated_unverified`다. 실제 IFA RF 검증, via/pad/hole, 제조 및 독립 kernel 검증은 후속이다.

## 제품 CAD worker 실행

호스트가 서비스 시작 시 `--cad-python .venv-cad/Scripts/python.exe`를 지정한다. 프로젝트/API 입력이 Python 경로, 사용자 코드나 셸 명령을 정하지 않는다. 서비스는 Python 실행 파일과 고정 runtime manifest, worker 진입점, 제품 Python 소스의 hash를 기록하고 작업별 입력/runtime/소스 묶음을 봉인한다. 새 staging의 `.py`에서 실행하므로 기존 `__pycache__`를 가져오지 않으며 결과 cache도 재사용하지 않는다. worker는 실제 소비한 입력/소스 hash와 Python/운영체제/CPU 및 설치 패키지 버전을 다시 확인한다. 설치 파일 전체의 보안 검증이나 OS sandbox를 제공한다는 의미는 아니다.

CAD 작업 중 서비스의 편집/저장/상태 조회는 별도 자료 처리 경로를 사용한다. Windows Job Object가 소유 프로세스를 회수하며 결과는 닫힌 파일의 streaming hash/봉인 후 게시한다. 서비스 재시작 시 종료를 확인할 수 없는 실행은 `outcome_unknown`과 예약을 유지한다. WSL solver 실행 환경은 이 Windows CAD 환경과 별개다.

CAD worker는 STEP/B-rep 저장 후 실제 OCCT body에서 표시 전용 mesh.json도 생성한다. 표시 허용오차는 절대 0.05 mm/0.15 rad이며 파일은 최대 16 MiB, 삼각형은 최대 100000개다. GUI에는 이 파일의 제한 좌표/삼각형만 전달하고 Python CAD/VTK/NumPy를 GUI에 적재하지 않는다. C++ wxGLCanvas/OpenGL 1.1과 Windows SHA256을 사용하므로 3D 연결을 위해 Python GUI 또는 Qt 패키지를 추가 설치하지 않는다.

```powershell
$env:PYTHONPATH = 'src'
$env:RFAD_CAD_PYTHON = (Resolve-Path '.venv-cad/Scripts/python.exe').Path
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_cad_worker_process.py -v
.\.venv-cad\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_cad_native.py -v
```

전체 개발 실행 명령은 [README](../README.md#현재-실행-방법), profile/API/출력 제한은 [CAD/STEP 계약](cad_contract.md), 최종 시험 결과는 [개발 상태](development_status.md)를 따른다. `tools/export_step.py`는 같은 서비스를 통해 등록된 프로젝트 또는 불변 SnapshotRef를 출력하는 개발 도구다. GUI의 STEP 출력/3D 갱신도 같은 서비스와 CAD 프로세스를 사용한다.

`tools/launch_gui.ps1`은 Code의 `.venv-cad/Scripts/python.exe`가 있으면 서비스의 CAD 환경으로 전달한다. 다른 고정 설치 위치는 `-CadPython`으로 지정한다. CAD 환경이 없으면 편집용 GUI를 시작하고 CAD 미연결 상태를 표시한다. 유효한 CAD 환경 지정이 실제 기하 입력이나 출력 검증을 생략하지는 않는다. 이전 성공 결과 조회는 `cad.latest`, 실제 표시 파일 읽기와 SHA256 검사는 GUI background loader에서 수행한다.

## 확인한 공식 자료

- [CadQuery 2.8.0 배포와 GUI 없는 라이브러리 사용](https://pypi.org/project/cadquery/2.8.0/)
- [CadQuery 2.8.0의 고정 태그 의존성 선언](https://github.com/CadQuery/cadquery/blob/v2.8.0/setup.py)
- [CadQuery STEP import/export](https://cadquery.readthedocs.io/en/latest/importexport.html)

공식 문서는 API 사용 근거다. 실제 호환성 결과는 이 저장소의 고정 wheel 조합과 로컬 smoke 기록을 기준으로 판단한다.
