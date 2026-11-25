# TraceWave Studio 창·렌더러 시제품

리팩토링 1단계의 독립 C++20 실행 파일이다. SDL3으로 창과 입력을 처리하고 Dear ImGui docking과 ImPlot의 그리기 명령을 bgfx에 제출한다. Windows Vulkan에서 예제 기판과 B0 S11 곡선을 확인했다. Windows UI Automation과 실제 내레이터 검수, 두벌식 조합과 확정 및 취소를 확인했다. 본창과 분리 입력 창의 한자 후보창 위치와 첫 후보 확정을 확인했다. 이동한 분리 창에서 실제 후보창이 캐럿을 따라가는 것도 확인했다. [Windows 1단계 수용 기록](../../../01_개발문서/07_검증/432_창과_렌더러_시제품_검증.md) [리팩토링 계획](../../../01_개발문서/09_개발계획/07_현행버전_완료후_리팩토링.md)

## 빌드와 실행

저장소 루트에서 실행한다. CMake 3.24 이상, Ninja, C++20 컴파일러, GitHub 소스 다운로드 연결이 필요하다. Windows에서 확인한 도구는 Kitware CMake 4.4.3, Ninja 1.13.2, WinLibs MinGW-w64 GCC 16.1.0이다. 다운로드는 소스 개정 및 SHA-256을 검사한다.

```powershell
cmake -S Code/ui/prototype -B Code/build/shell-prototype -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build Code/build/shell-prototype --target tracewave_shell_prototype
ctest --test-dir Code/build/shell-prototype --output-on-failure -V
.\Code\build\shell-prototype\tracewave_shell_prototype.exe
```

현재 개발과 검수는 Windows에서 먼저 진행한다. 후속 Linux·macOS 검수에서는 같은 CMake 명령과 확장자 없는 실행 파일을 사용한다. Linux의 bgfx 빌드에는 X11, OpenGL, Wayland EGL 개발 헤더가 필요하며, 실행에는 Vulkan 로더와 드라이버가 필요하다. macOS에는 Xcode Command Line Tools와 Metal 지원 기기가 필요하다. 테스트에는 접근 가능한 실제 데스크톱 세션과 한글 글꼴이 필요하다. 다른 글꼴을 선택하려면 실행에 `--font <파일>`을 추가한다. Windows는 Malgun Gothic, macOS는 Apple SD Gothic Neo, Linux는 시스템 Noto CJK나 나눔고딕을 우선 탐색한다.

| 조작 | 방법 |
| --- | --- |
| PCB 보기 | 마우스 휠로 확대하고 드래그로 이동한다. **보기 초기화**로 돌아간다. |
| S11 곡선 | ImPlot에서 확대, 이동, 표본 값 확인을 한다. |
| 입력에 초점 | `F6` |
| 입력을 별도 창으로 | `Shift+F8` 또는 **창 > 입력을 별도 창으로**. 같은 메모를 편집한다. 분리 창을 닫으면 본창 메모에 초점이 돌아온다. |
| S11 패널 닫기·다시 열기 | `F7` 또는 패널의 닫기 버튼과 **창 > S11 결과** |
| 별도 결과 창 | `F8` 또는 **창 > 결과를 별도 창으로**. SDL3 플랫폼과 bgfx가 별도 스왑 체인을 지원할 때 활성화한다. |
| 기본 배치 복원 | `F9` 또는 **창 > 기본 배치 복원** |
| 메뉴와 입력 탐색 | `F10`으로 창 메뉴를 열고 방향키와 `Enter`로 조작한다. `Esc`로 닫는다. 메모와 지우기 버튼 사이를 `Tab`과 `Shift+Tab`으로 이동한다. |

패널 위치와 크기는 사용자별 `TraceWave/ShellPrototype/layout.ini`에 저장한다. CTest의 `--smoke` 실행은 메모리에서만 배치를 사용한다. Wayland에서는 ImGui SDL3 백엔드에 따라 기본 창 내부 도킹을 사용한다. Linux와 macOS의 실제 화면 검수 상태는 개발문서에 기록한다.

## Windows 한글 입력과 화면 읽기

1. 본창에서 `F6`으로 메모를 선택한다. 작업 표시줄에서 Microsoft 입력기의 한글 모드를 확인한다. `g k s r m f`를 누르면 끝 글자 `글`이 조합 중인지 확인한다. `Enter`로 확정한 메모의 값은 `한글`이어야 한다.
2. `r k`로 `가`를 조합한 뒤 `Esc`를 누른다. 조합 표시가 사라지고 앞서 확정한 `한글`이 유지되는지 확인한다.
3. 검수 메모를 비우고 `g k s`를 누른다. `Enter`를 누르기 전에 한자 키 또는 작업 표시줄 Microsoft 입력기 메뉴의 한자 변환을 사용한다. 후보창이 조합 중인 `한`의 캐럿 가까이에 표시되는지 확인하고 창과 후보창의 위치를 기록한다. [Microsoft 한국어 IME 사용법](https://learn.microsoft.com/globalization/input/korean-ime)
4. `Shift+F8`로 분리 입력 창을 열고 같은 절차를 반복한다. 분리 창의 빈 제목 영역을 클릭한 뒤 가로로 드래그한다. 이동한 창에서 `F6`으로 메모에 다시 초점을 주고 후보창 위치를 확인한다.

UI Automation에서 메모의 편집 역할과 값, 창 메뉴의 펼치기와 각 항목의 상태 및 실행, 기판과 S11 및 입력 패널의 이름을 확인한다. Windows 내레이터를 켠 상태에서 `F10`과 방향키, `F6`과 `Tab`을 사용하고, 분리 창에서 `Alt+F4`를 누른 뒤 본창의 메모가 다시 읽히는지 확인한다. 운영체제 IME와 내레이터 확인은 CTest의 합성 SDL 이벤트 시험과 별도로 기록한다.

내레이터는 화면 읽기 호환성을 검수할 때 켠다. 시제품과 CTest는 내레이터를 끈 상태에서도 실행할 수 있다. 실제 발화는 내레이터의 음성 요약 창에서도 확인할 수 있다. [Windows 내레이터 키 명령](https://support.microsoft.com/en-gb/accessibility/windows/narrator/appendix-b-narrator-keyboard-commands-and-touch-gestures)

Windows의 `--smoke`는 분리 입력 창을 같은 모니터에서 옮기고, 이동 전후와 본창 초점 복귀 뒤 메모 캐럿의 SDL IME 위치를 대조한다. 실제 한자 후보창의 화면 위치는 위 절차로 검수한다. [자동 시험 관찰값](../../../01_개발문서/07_검증/432_창과_렌더러_시제품_검증.md#windows-분리-입력-창-이동과-ime-좌표-자동-시험)

## 표시 데이터와 의존성

PCB는 확대·이동을 시험하는 원형 예제다. S11은 B0 보존본 `B0-public-api.json`의 `result.page` 응답에서 확보한 8–12 GHz 주파수와 `magnitude_db` 31개를 사용한다. 데이터셋 SHA-256은 `ffdb9e19f126f8a0d4f17a584f88601bf2ad031f41f68689c642d7edb819dd42`다. [B0 고정 기록](../../../01_개발문서/07_검증/430_알원_비제로_기준선_확정.md)

고정 소스는 SDL 3.4.14(zlib), Dear ImGui 1.91.9b docking(MIT), ImPlot 0.16(MIT), bgfx/bx/bimg(BSD-2-Clause), bgfx.cmake(CC0)다. ImGui용 배포 셰이더 바이트코드는 동일 bgfx 소스의 예제 헤더에서 읽는다. 시제품은 시스템 글꼴을 읽으며 자체 글꼴을 포함하지 않는다. [실행 검증](../../../01_개발문서/07_검증/432_창과_렌더러_시제품_검증.md)
