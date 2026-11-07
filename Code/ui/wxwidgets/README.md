# Windows 최소 GUI

이 GUI는 승인된 wxWidgets 구성을 처음 실행해 보는 개발용 진입점이다. C++ 창에서 별도의 Python 프로젝트 서비스에 연결한다. 프로젝트 생성, 열기, 이름과 설명 변경, 저장, 스냅샷을 실제 명령으로 처리한다. 프로젝트 트리에 매개변수와 초기 설계 데이터 목록을 표시한다.

CAD 편집 화면, OCCT viewport, 매개변수 입력 편집기, openEMS 실행과 결과 표시는 후속 구현이다. GUI 이벤트 루프와 저장 흐름의 smoke 통과는 일반 편집 60 fps, 대형 장면 30 fps 또는 메모리 예산 통과를 의미하지 않는다.

## 개발 환경과 빌드

Windows 11 x64, CPython 3.12, CMake, Ninja, MinGW-w64 GCC를 사용한다. 이번에 확인한 버전과 원본 URL, SHA256은 `Code/runtime_profiles/native-windows-x64.json`에 기록한다. `.local` 의존성과 `build` 산출물은 Git에 넣지 않는다.

Code 폴더에서 실행한다.

```powershell
.\tools\setup_native.ps1 -Jobs 4
```

스크립트는 고정한 wxWidgets 3.2.12와 nlohmann/json 3.12.0을 준비하고 SHA256을 검사한다. 이미 추출한 wxWidgets 폴더는 재사용한다. 수정된 의존성 소스까지 검증하는 기능은 없으므로 검증 빌드에서는 새로 추출한 원본 소스를 사용해야 한다. 컴파일러와 CMake는 PATH에서 제공해야 하며 스크립트가 설치하거나 업데이트하지 않는다.

wxWidgets는 core/base를 정적으로 연결하며 webview, media, OpenGL, STC, ribbon은 이 초기 프로필에서 제외한다. MinGW의 C++/thread runtime DLL은 설치된 컴파일러 폴더에서 실행 파일 옆으로 복사한다. Qt와 필수 유료 GUI 부품은 사용하지 않는다.

의존성이 이미 준비된 경우 다음 명령도 사용할 수 있다. 이 방법은 runtime DLL을 복사하지 않으므로 컴파일러의 bin이 PATH에 있어야 한다.

```powershell
cmake --preset windows-release
cmake --build --preset windows-release --parallel 4
```

## 실행

기본 개발 환경에서는 Code 폴더에서 다음 명령으로 실행한다. 창에서 프로젝트를 만들거나 연다.

```powershell
.\tools\launch_gui.ps1
```

Code 폴더를 기준으로 모든 경로를 절대 경로로 전달한다. Python과 source 경로는 GUI와 서비스를 별도로 교체할 수 있도록 명시한다. 개발용 `.venv`는 프로젝트의 Python 환경 설정 절차로 준비한다.

```powershell
$codeRoot = (Get-Location).Path
$guiArguments = @(
    '--python', (Join-Path $codeRoot '.venv/Scripts/python.exe'),
    '--source', (Join-Path $codeRoot 'src'),
    '--workspace', (Join-Path $codeRoot '.local/gui-workspace')
)
& (Join-Path $codeRoot 'build/windows-release/bin/tracewave_gui.exe') @guiArguments
```

`프로젝트` 메뉴에서 새 프로젝트를 만들고 속성을 변경한 뒤 `변경 적용`을 누른다. `저장`은 현재 개정을 저장 기준점으로 지정하고 `스냅샷 만들기`는 불변 프로젝트 사본을 만든다. 열기는 같은 작업 영역에 등록된 `projects/이름` 경로를 받는다. 기존 파일을 임의로 가져오는 가져오기 기능은 아직 없다.

## 연결과 실패 처리

- C++ GUI는 모델 계산이나 프로젝트 파일 저장 규칙을 복제하지 않고 `rfad.api/2.0` 명령을 호출한다.
- 셸 없이 명시한 Python 실행 파일을 시작한다. 공백, 한글과 따옴표를 포함한 경로는 Windows 인수 규칙에 따라 인코딩한다.
- stdin writer와 stdout/stderr reader는 별도 thread다. UI thread는 주기적으로 도착한 응답만 처리하며 pipe read/write를 기다리지 않는다.
- stdout 프레임은 최대 64 KiB, 송신/수신/로그 큐는 각각 최대 64개, GUI pending request는 최대 16개다. stdout 큐 초과와 잘못된 프레임은 연결 오류로 표시한다.
- stderr는 stdout과 별도 큐에서 읽는다. 긴 로그는 약 2 KiB로 자르고 로그 큐 초과는 건너뛴 개수로 표시한다. 화면 기록도 길이를 제한한다.
- 응답 제한 시간은 30초이며 자동 mutation 재전송은 하지 않는다. 오류 뒤에는 작업 영역을 다시 열어 저장된 상태를 확인해야 한다.
- 종료 시 창을 숨긴 뒤 별도 thread에서 자신이 시작한 서비스의 stdin을 닫고 종료를 기다린다. 응답하지 않는 자신 소유의 프로세스만 Windows Job Object로 종료한다. writer 취소 최대 0.5초, 정상 종료 대기 2.5초, 강제 종료 확인 1초를 사용하며 비정상 종료 처리 목표 상한은 5초다. pipe 회수 후 UI 완료 이벤트에서 창을 파괴한다. 일반 편집 명령 중에는 동기 Stop을 호출하지 않는다.
- 현재 서비스의 원본 프로젝트 문서 32 KiB 상한과 전송 프레임 64 KiB 상한이 함께 적용된다. 대형 프로젝트는 향후 artifact/paging 연결로 확장해야 하며 현재 대형 프로젝트 UI가 구현되었다고 간주하지 않는다.

## 실제 프로세스 시험

```powershell
$env:RFAD_GUI_EXE = (Join-Path (Get-Location).Path 'build/windows-release/bin/tracewave_gui.exe')
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_gui_process.py -v
```

시험은 실제 wxWidgets 이벤트 루프와 Python 프로세스를 실행한다. 한글/공백 경로에서 프로젝트 생성, 이름/설명 변경, 저장, 스냅샷, 서비스 종료/재시작, 재열기 후 내용과 저장 개정 일치를 검사한다. stderr 폭주, 과대 stdout 프레임, 서비스 조기 종료, 없는 Python 실행 파일도 검사한다. `RFAD_GUI_EXE`를 지정하지 않은 Python 기본 시험에서는 이 GUI 시험만 건너뛴다.

GUI에 `--smoke-test --smoke-report <절대 JSON 경로>`를 추가하면 같은 정상 흐름을 실행하고 60초 안에 성공/실패 보고서를 남긴다. 정상은 종료 코드 0, 흐름 실패는 2, 보고서 쓰기 실패는 3이다. 보고서는 `physics_tested=false`, `frame_budget_tested=false`를 명시한다.

## 의존성과 배포 범위

현재는 내부 개발 검증용이다. 프로필에 wxWidgets/nlohmann 라이선스 원문 위치와 링크에 들어간 PCRE2, zlib, IJG JPEG, libpng, libtiff 및 NanoSVG의 라이선스 위치를 기록했다. 이 목록은 배포 심사가 끝났다는 의미가 아니다. 외부 배포 전에 최종 실행 파일과 runtime DLL의 실제 포함 목록, 원문 고지, 컴파일러 runtime 조건, 설치 프로그램을 함께 검토해야 한다.
