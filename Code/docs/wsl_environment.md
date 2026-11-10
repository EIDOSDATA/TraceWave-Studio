# WSL2 개발 환경

기록일: 2026-11-10 KST

## 현재 상태

- 2026-11-07 설치 요청은 Windows 재부팅을 요구했고 당시 배포는 등록되지 않았다.
- 2026-11-10 재부팅 후 설치를 재개하여 `TraceWave-Dev` 등록과 실제 WSL2 실행을 확인했다.
- 배포는 Ubuntu 24.04.5 LTS, kernel은 6.18.33.2-microsoft-standard-WSL2다. WSL은 2.7.11.0이다.
- 가상 디스크 저장 위치는 `Code/.local/wsl/TraceWave-Dev`다.
- 개발/시험은 일반 사용자 tracewave와 별도 서비스/해석기 가상환경을 사용한다.
- Linux 서비스 시험과 Windows/Linux 표현식 비교가 통과했다. Qt 없는 openEMS/CSXCAD/VTK 빌드와 두 격자 도파관 참조 계산도 통과했다. 자세한 범위와 해석 환경 상태는 [Linux 환경](linux_environment.md)을 따른다.

현재 기록은 `runtime_profiles/wsl-development.json`, 배포 확인 결과는 `.local/wsl/status.json`에 저장한다. 등록 여부와 실제 실행을 확인하며 설치 종료 코드만으로 성공을 판단하지 않는다.

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

읽기 확인은 Linux 사용자 초기 설정 창에 의존하지 않도록 `root`로 수행한다. 실제 개발은 setup_openems_wsl.py가 구성한 일반 사용자 tracewave로 수행한다. WSL 명령과 `--no-launch`, `--web-download`의 의미는 Microsoft의 [명령 참조](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)를 따른다.

## openEMS 구성과 후속 검증

setup_wsl.ps1은 배포 준비만 담당한다. 이번에 별도 [Linux 환경 구성](linux_environment.md)과 setup_openems_wsl.py를 추가했으며, 아래 원칙으로 실제 빌드/검사를 진행한다. 전체 제품 solver adapter나 IFA 검증 완료를 뜻하지 않는다.

이후 [WSL2 도파관 worker](solver_contract.md)를 서비스에 연결했다. `--openems-wsl`은 이미 감사한 고정 환경을 선택하며 설치나 빌드를 자동 수행하지 않는다. 새로운 PC는 먼저 이 문서의 환경 구성과 native 감사를 완료한다. 제품 준비/해석/취소/저장 검증은 환경 검사와 별도 명령으로 실행한다.

1. 실행이 확인된 전용 배포에서 고정한 openEMS v0.37.0과 meta commit을 사용한다. CSXCAD와 하위 모듈 commit, 컴파일러, CMake 및 Python 버전도 함께 기록한다.
2. 고정한 소스의 의존성 목록과 빌드 옵션을 검토한다. 공식 [의존성 안내](https://docs.openems.de/en/latest/install/requirements.html)는 headless 경로를 제공하며 GUI 의존성을 별도로 설명한다.
3. AppCSXCAD와 QCSXCAD를 비활성화한다. 공식 [소스 빌드 안내](https://docs.openems.de/en/latest/install/clone-build-install.html)의 GUI 비활성화 옵션을 고정한 버전의 스크립트 도움말과 대조한다. 버전별로 다른 옵션 표기를 추정해서 실행하지 않는다.
4. 패키지 설치 계획과 Python 의존성 해결 결과에 Qt, PyQt, PySide 및 Qt 연결 VTK가 없는지 확인한 다음 필요한 의존성만 설치한다. `--disable-GUI` 지정만으로 전체 의존성이 Qt 없이 구성됐다고 판정하지 않는다.
5. Linux 파일시스템 내부의 전용 작업 폴더에서 빌드한다. Windows의 `Code` 소스와 실행 결과 교환 경로는 명시적으로 매핑하고 공백이 있는 Windows 경로를 임의로 셸 문자열에 연결하지 않는다.
6. 실행 파일 버전, Python의 `CSXCAD`/`openEMS` import, 동적 라이브러리 의존성, 작은 참조 사례의 결과를 확인한다.
7. 검증 후 실제 버전, commit, 의존성 목록과 결과 해시로 runtime profile을 갱신한다. 참조 사례를 통과한 뒤 승인된 단일 포트 IFA 검증으로 진행한다.

Windows wxWidgets GUI와 WSL2 해석 작업은 별도 프로세스 경계를 유지한다. Linux GUI 및 유료 GUI 부품을 이 환경의 필수 의존성으로 추가하지 않는다.
