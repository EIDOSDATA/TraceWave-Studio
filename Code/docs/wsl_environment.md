# WSL2 개발 환경

기록일: 2026-11-07

## 현재 상태

- Windows의 WSL 2.7.11 실행 파일은 확인했다.
- 전용 배포 이름은 `TraceWave-Dev`, 원본 배포는 `Ubuntu-24.04`다.
- 저장 위치는 `Code/.local/wsl/TraceWave-Dev`다.
- 설치 시 Windows 기능 변경 후 시스템 재시작이 필요하다는 결과가 나왔다.
- 설치 명령은 exit code 0을 반환했지만 `wsl --list --quiet`에 등록된 배포가 없다.
- 따라서 WSL 배포 설치, Linux 명령 실행, openEMS 및 Python binding 준비 완료로 표시하지 않는다.
- 자동 재부팅과 반복 설치는 수행하지 않았다. 기존 배포의 설정과 패키지도 변경하지 않았다.

현재 기록은 `runtime_profiles/wsl-development.json`에 저장한다. 재개 스크립트의 실제 확인 결과는 Git에서 제외한 `.local/wsl/status.json`에 기록한다.

## 재부팅 후 재개

WSL 준비 이후의 Linux 시험, GUI/CAD/해석 구현 순서는 [재부팅 후 개발 재개](reboot_resume.md)에 정리했다.

Windows에서 진행 중인 작업을 저장하고 직접 재부팅한 뒤, `Code` 디렉터리의 PowerShell 7에서 확인한다.

```powershell
pwsh -NoProfile -File .\tools\setup_wsl.ps1
```

이 명령은 등록 여부와 전용 배포의 실행만 확인한다. 배포가 없으면 exit code 2와 함께 미완료 상태를 남긴다. `TraceWave-Dev`가 아직 없으면 다음 명령으로 설치를 한 번 재개한다.

```powershell
pwsh -NoProfile -File .\tools\setup_wsl.ps1 -Install
```

Windows 기능 설치에 관리자 권한이 필요한 경우 관리자 PowerShell에서 실행한다. 스크립트가 권한을 자동으로 올리거나 Windows를 재부팅하지는 않는다. Microsoft의 [WSL 설치 안내](https://learn.microsoft.com/en-us/windows/wsl/install)는 관리자 PowerShell에서 설치한 뒤 재부팅하는 절차를 설명한다.

스크립트는 다음 계약을 따른다.

1. 다른 배포를 기본값으로 바꾸거나 업데이트, 변환, 제거하지 않는다.
2. `TraceWave-Dev`가 이미 있으면 설치 명령을 재실행하지 않고 읽기 명령으로 확인한다.
3. 배포가 없지만 설치 대상 경로가 이미 있으면 덮어쓰지 않고 중단한다.
4. 설치 명령의 exit code만으로 성공을 판단하지 않는다.
5. `wsl --distribution TraceWave-Dev --user root --exec`로 `/etc/os-release`와 커널 버전을 읽고 Ubuntu 24.04 및 WSL2 실행을 확인해야 exit code 0을 반환한다.
6. exit code 0은 WSL 배포 실행만 의미하며 openEMS 설치 성공을 의미하지 않는다.

읽기 확인은 Linux 사용자 초기 설정 창에 의존하지 않도록 `root`로 수행한다. 실제 개발 사용자는 이후 해당 배포에서 별도로 정한다. WSL 명령과 `--no-launch`, `--web-download`의 의미는 Microsoft의 [명령 참조](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)를 따른다.

## openEMS 후속 구성

아래는 아직 실행하거나 검증하지 않은 후속 작업이다. 현재 스크립트는 Linux 패키지나 openEMS를 설치하지 않는다.

1. 실행이 확인된 전용 배포에서 openEMS 릴리스와 commit을 선택하고 고정한다. CSXCAD와 하위 모듈 commit, 컴파일러, CMake 및 Python 버전도 함께 기록한다.
2. 고정한 소스의 의존성 목록과 빌드 옵션을 검토한다. 공식 [의존성 안내](https://docs.openems.de/en/latest/install/requirements.html)는 headless 경로를 제공하며 GUI 의존성을 별도로 설명한다.
3. AppCSXCAD와 QCSXCAD를 비활성화한다. 공식 [소스 빌드 안내](https://docs.openems.de/en/latest/install/clone-build-install.html)의 GUI 비활성화 옵션을 고정한 버전의 스크립트 도움말과 대조한다. 버전별로 다른 옵션 표기를 추정해서 실행하지 않는다.
4. 패키지 설치 계획과 Python 의존성 해결 결과에 Qt, PyQt, PySide 및 Qt 연결 VTK가 없는지 확인한 다음 필요한 의존성만 설치한다. `--disable-GUI` 지정만으로 전체 의존성이 Qt 없이 구성됐다고 판정하지 않는다.
5. Linux 파일시스템 내부의 전용 작업 폴더에서 빌드한다. Windows의 `Code` 소스와 실행 결과 교환 경로는 명시적으로 매핑하고 공백이 있는 Windows 경로를 임의로 셸 문자열에 연결하지 않는다.
6. 실행 파일 버전, Python의 `CSXCAD`/`openEMS` import, 동적 라이브러리 의존성, 작은 참조 사례의 결과를 확인한다.
7. 검증 후 실제 버전, commit, 의존성 목록과 결과 해시로 runtime profile을 갱신한다. 참조 사례를 통과한 뒤 승인된 단일 포트 IFA 검증으로 진행한다.

Windows wxWidgets GUI와 WSL2 해석 작업은 별도 프로세스 경계를 유지한다. Linux GUI 및 유료 GUI 부품을 이 환경의 필수 의존성으로 추가하지 않는다.
