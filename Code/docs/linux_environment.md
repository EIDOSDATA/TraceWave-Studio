# Linux 서비스와 openEMS 개발 환경

기록일: 2026-11-10 KST

재부팅 후 전용 `TraceWave-Dev`를 설치하고 Ubuntu 24.04.5 LTS가 WSL2에서 실행되는 것을 확인했다. kernel은 6.18.33.2-microsoft-standard-WSL2, Python은 3.12.3이다. 서비스와 해석기는 일반 사용자 tracewave로 실행한다. 설치 의존성만 전용 배포의 root 권한을 사용한다.

## 경로와 분리

| 위치 | 용도 |
| --- | --- |
| Windows `Code` | 제품 소스, 시험, 고정 버전 기록과 구성 도구 |
| WSL `/mnt/c/Users/eidos/GitHub/TraceWave Studio/Code` | 같은 소스의 명시적 읽기/실행 경로 |
| WSL `/home/tracewave/rfad-runtime/service-venv` | 표준 라이브러리 기반 서비스 시험 |
| WSL `/home/tracewave/rfad-runtime/openems-venv` | 해석기 전용 Python 환경 |
| WSL `/home/tracewave/rfad-runtime/openEMS-Project` | 고정 openEMS/CSXCAD/fparser 원본 |
| WSL `/home/tracewave/rfad-runtime/openems/0.37.0` | 개발용 native 설치 prefix |
| WSL `/home/tracewave/rfad-runtime/vtk/9.3.1` | Qt 없는 VTK 원본/빌드/설치 |
| Windows `Code/.local/wsl` | 설치/시험 로그와 실행 근거. Git 제외 |

Linux 빌드와 solver 실행 산출물은 ext4 경로를 사용한다. Linux runtime은 Code/.local/wsl 아래 설치된 전용 배포의 가상 디스크 안에 있다. Windows 가상환경을 Linux에서 사용하지 않으며 Windows용 wheel lock을 재사용하지 않는다. 서비스나 wxWidgets GUI 시작에 openEMS/VTK/NumPy를 import하지 않는다.

## 서비스 검증

### WSL 설치 단계

WSL 환경을 구성한 시점에 일반 사용자와 service-venv에서 전체 183개 시험을 실행했다. 178개가 통과했고 Windows GUI 시험 5개만 스킵됐다. 실패와 오류는 없고 13.639초가 걸렸다. 같은 변경에서 Windows 전체 183개도 스킵 없이 통과했다(32.002초). 파일 잠금, symlink 거부, 게시 전후 프로세스 종료/복구, JSON-RPC와 한글/공백 경로 시험을 포함한다. 임시 저장소 시험은 Linux ext4의 /tmp를 사용했으므로 Windows 볼륨의 파일시스템 내구성 검증과 구분한다.

이후 설치 도구에 미추적 CMake override 거부와 VTK 재사용 감사 시험 4개를 추가했다. 관련 설치 도구 시험 8개를 Windows/Linux 양쪽에서 다시 실행해 모두 통과했고, 보완된 도구로 실제 설치의 소스/패키지/전체 native 의존성 감사도 통과했다. 전체 183개 실행과 이후 변경 부분 8개 재검증을 구분해 기록한다.

Windows 3.12.10에서 만든 기준을 Linux 3.12.3으로 읽어 다음을 비교했다.

- 표현식 49개와 예상 오류, SI 값과 float.hex 표현.
- UUID 결합과 의존 매개변수의 연쇄 계산.
- 초기 IFA fixture의 저장 캐시, null 물성과 정규 직렬화.

모두 정확히 일치했고 결과 hash는 `0f4dbed713765fce0094011f4850699ecc08d9d9d8aceb7eaf48167fa0838d3b`다. 1 ULP 차이도 실패로 처리하며 원본이나 기준 파일을 다시 쓰지 않는다. 임의의 모든 수식/CPU/libm 조합에서 bitwise 일치한다고 일반화하지 않는다. 다른 엔진/런타임에서는 같은 검사를 다시 수행한다.

### 속성 편집 구현 단계

같은 날 선택 속성 DTO, 매개변수/표현식 편집, 영속 undo/redo와 GUI 연결을 추가한 뒤 Windows 전체 205개 시험이 스킵 없이 통과했다(45.877초). Linux는 전체 205개 중 199개 통과, Windows 전용 GUI 시험 6개 스킵이며 실패와 오류 없이 20.500초였다. 실제 stdio 서비스의 편집/실행 취소/재시작/다시 실행, 불변 스냅샷 보존, history head 불일치 차단과 설치 환경의 기존 시험을 함께 확인했다. 실행 로그는 `.local/editor-windows-tests.log`, `.local/editor-linux-tests.log`다.

이 변경의 Windows 기준 파일 `.local/portability/windows-editor-baseline.json`과 Linux 비교 보고서 `.local/portability/linux-editor-check.json`에서도 표현식 49개, UUID 결합 그래프와 IFA 캐시가 정확히 일치했다. 결과 hash는 WSL 설치 단계와 같은 `0f4dbed713765fce0094011f4850699ecc08d9d9d8aceb7eaf48167fa0838d3b`이고 원본/기준 파일은 비교 중 변경하지 않았다.

205개 기록 이후 한국어 표시와 편집 화면 UX를 보완하며 시험 2개를 추가했다. 해당 버전의 Windows 전체 207개가 스킵 없이 48.800초에 통과했고, Linux는 207개 중 201개 통과/Windows GUI 6개 스킵으로 19.513초에 완료했다. 로그는 `.local/ux-windows-tests.log`, `.local/ux-linux-tests.log`다. 추가 시험은 사용자에게 보이는 한글 표현과 원본 API 값/참조 ID/읽기 전용 규칙의 분리를 검증한다. 이후 단위 초안 안내와 마지막 적용값 라벨의 GUI 보완본은 관련 Windows GUI 6개를 13.780초에 다시 통과했다(`.local/ux-gui-final.log`). 이 후속 변경은 Linux 서비스 소스를 바꾸지 않았다. 선택 속성 계약은 [편집 계약](editor_contract.md), 최신 검증 범위는 [개발 상태](development_status.md)를 따른다.

### 2D 편집 구현 단계

기판/도체층/선/원호의 2D 표시와 직접 편집, 누락 치수/참조/수치 범위 경계를 보완한 뒤 Windows 전체 227개가 스킵 없이 76.152초에 통과했다. Linux는 227개 중 220개 통과, Windows 전용 GUI 7개 스킵으로 30.312초였으며 실패/오류는 없다. 실행 로그는 `.local/canvas-windows-tests.log`, `.local/canvas-linux-tests.log`다. Windows native CTest `canvas_geometry` 1개도 0.13초에 통과했다.

이 검증은 실제 stdio 프로세스의 생성/이동/삭제, 음수 sweep, 참조 좌표와 미정 치수, 실패/stale 요청의 원본 보존, 영속 undo/redo, 저장/스냅샷과 강제 종료 후 재시작을 포함한다. GUI 7개는 Windows에서 실행했으며 Linux GUI를 검증한 결과가 아니다. 이후 실제 Windows 창의 도구막대/DPI 배치 보완은 Linux 서비스 변경과 구분하며 후속 GUI 재검증 상태는 [개발 상태](development_status.md)를 따른다.

2D 서비스 계약은 [표시와 직접 편집](canvas_contract.md)에 있다. 이후 호스트 CAD/GUI 연결과 제한된 [WSL solver worker](solver_contract.md)를 구현했다. headless openEMS 환경과 참조 검증을 제품 GUI의 해석 실행 기능 완료로 간주하지 않는다.

## Qt 없는 해석 의존성

openEMS v0.37.0과 CSXCAD v0.7.0을 meta commit `974294ba7d812ef5a46a4760593057aee7ce6866`의 하위 소스로 고정했다. AppCSXCAD, QCSXCAD, Octave, ParaView는 설치하지 않는다.

Ubuntu의 libvtk9-dev를 포함한 사전 설치 계획에서는 Qt5 패키지 5개가 따라왔다. 이 계획은 적용하지 않았다. 실제 설치에는 VTK 개발 패키지를 빼고 필요한 compiler/Boost/HDF5/CGAL/TinyXML/Python 의존성만 사용했다. 별도 VTK 9.3.1 소스에서 IOGeometry/IOPLY/IOXML/IOLegacy와 필요한 전이 모듈을 빌드했다. Qt, MPI, Python/Java wrapping은 껐다. 전이 의존성에 RenderingCore 등이 있어 모든 렌더링 관련 소스가 제외된다는 의미는 아니다.

Python 의존성 15개는 Linux x86_64/CPython 3.12 wheel 버전과 SHA256으로 고정했다. openEMS 0.37.0 / CSXCAD 0.7.0 native 바인딩은 같은 소스와 설치 prefix로 빌드하고 import와 pip check를 통과했다. native compiler는 GCC 13.3.0, CMake 3.28.3, Ninja 1.11.1이다. Ubuntu 시스템 패키지는 설치한 실제 버전을 기록하며 장기 재현 가능한 패키지 archive lock은 아니다. 외부 배포용 라이선스 고지와 설치 패키지는 후속이다.

고정 기록은 `runtime_profiles/openems-wsl-build.json`, `vtk-headless.json`, `python-openems-linux-x64.json`과 대응 requirements에 있다. [공식 headless 구성](https://docs.openems.de/en/latest/install/clone-build-install.html)과 [의존성 안내](https://docs.openems.de/en/latest/install/requirements.html)를 참고하되, GUI 비활성화만으로 모든 전이 의존성이 Qt 없이 구성됐다고 판단하지 않는다.

## 재현 명령

먼저 [WSL 구성](wsl_environment.md)으로 전용 Ubuntu가 실행되는지 확인한다. 그 다음 Windows Code의 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/setup_openems_wsl.py --install-dependencies --jobs 2
```

이 도구는 전용 일반 사용자를 준비하고 설치 전 Qt 유입을 검사한다. 기존 source commit이나 tracked 파일이 달라졌으면 자동 checkout/덮어쓰기를 수행하지 않는다. CMake가 자동 포함하는 미추적 localConfig.cmake도 거부한다. Python 패키지는 고정 wheel 해시를 사용하고 native C++/Python 바인딩을 빌드한다. 이미 검증한 VTK가 있으면 `--skip-vtk-build`로 재사용하며, 이때도 빌드 보고서의 원본 식별과 실제 전체 공유 라이브러리 해시/의존성을 검사한다. 로그는 `.local/wsl/setup-openems.log`다. 기존 배포를 지우거나 WSL 기본값을 바꾸지 않는다.

빌드 완료와 import 성공은 계산 검증과 별개다. 실제 수치 검사는 [도파관 참조 검사](openems_reference.md)를 따른다. 이후 도파관 제품 solver adapter와 서비스 실행/취소/결과 저장, [사용자 PCB 단일 포트](pcb_solver_contract.md) 및 Windows GUI 해석/결과 화면을 연결했다. NF2FF, 실제 IFA/원형 원호의 정식 수렴/실측 검증과 Linux GUI는 후속이다.

## WSL 설치 단계 실행 기록

- WSL 등록과 Ubuntu 실행: 통과.
- Linux 전체 183개 중 178개 통과. Windows 전용 5개 스킵.
- Windows/Linux 표현식 기준 비교: 통과.
- Linux Python 고정 의존성 설치와 재실행: 통과.
- VTK 9.3.1, fparser, CSXCAD 0.7.0, openEMS 0.37.0 native 빌드와 Python 바인딩 import: 통과.
- VTK 공유 라이브러리 41개와 solver/binding 파일 17개 의존성 검사: Qt와 누락 라이브러리 없음.
- 실제 도파관 검사: 두 격자 모두 사전 기준 통과. 최대 임피던스 상대 오차 0.617% 미만, 군지연 상대 오차 0.108% 미만. 종료 에너지와 로그/통계 일치 확인. 상세 수치와 범위는 [참조 검사](openems_reference.md) 참조.

`.local/wsl/`의 설치 로그, `service-tests-final.log`, `dpkg-installed.tsv`, `vtk-build-report.json`, `native-audit.json`, `openems-reference.json` 및 `.local/portability/linux-check.json`을 해당 단계의 근거로 사용한다. 실제 모델과 원시 probe는 Linux의 보고서에 기록된 고유 실행 디렉터리에 보존했다. 실행 요약과 hash는 `runtime_profiles/wsl-development.json`에 기록한다.
