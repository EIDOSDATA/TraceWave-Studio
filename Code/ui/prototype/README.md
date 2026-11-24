# TraceWave Studio 창·렌더러 시제품

리팩토링 1단계의 독립 C++20 실행 파일이다. SDL3으로 창과 입력을 처리한다. Dear ImGui docking과 ImPlot의 그리기 명령은 bgfx의 Windows/Linux Vulkan 또는 macOS Metal 렌더러에 제출한다. 빌드와 배치 저장은 기존 Studio와 분리되어 있다. [리팩토링 계획](../../../01_개발문서/09_개발계획/07_현행버전_완료후_리팩토링.md)

## 빌드와 실행

저장소 루트에서 실행한다. CMake 3.24 이상, Ninja, C++20 컴파일러, GitHub 소스 다운로드 연결이 필요하다. Windows에서 확인한 도구는 Kitware CMake 4.4.3, Ninja 1.13.2, WinLibs MinGW-w64 GCC 16.1.0이다. 다운로드는 소스 개정 및 SHA-256을 검사한다.

```powershell
cmake -S Code/ui/prototype -B Code/build/shell-prototype -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build Code/build/shell-prototype --target tracewave_shell_prototype
ctest --test-dir Code/build/shell-prototype --output-on-failure -V
.\Code\build\shell-prototype\tracewave_shell_prototype.exe
```

Linux와 macOS는 같은 CMake 명령과 확장자 없는 실행 파일을 사용한다. Linux의 bgfx 빌드에는 X11, OpenGL, Wayland EGL 개발 헤더가 필요하며, 실행에는 Vulkan 로더와 드라이버가 필요하다. macOS에는 Xcode Command Line Tools와 Metal 지원 기기가 필요하다. 테스트에는 접근 가능한 실제 데스크톱 세션과 한글 글꼴이 필요하다. 다른 글꼴을 선택하려면 실행에 `--font <파일>`을 추가한다. Windows는 Malgun Gothic, macOS는 Apple SD Gothic Neo, Linux는 시스템 Noto CJK나 나눔고딕을 우선 탐색한다.

| 조작 | 방법 |
| --- | --- |
| PCB 보기 | 마우스 휠로 확대하고 드래그로 이동한다. **보기 초기화**로 돌아간다. |
| S11 곡선 | ImPlot에서 확대, 이동, 표본 값 확인을 한다. |
| 입력에 초점 | `F6` |
| S11 패널 닫기·다시 열기 | `F7` 또는 패널의 닫기 버튼과 **창 > S11 결과** |
| 별도 결과 창 | `F8` 또는 **창 > 결과를 별도 창으로**. SDL3 플랫폼과 bgfx가 별도 스왑 체인을 지원할 때 활성화한다. |
| 기본 배치 복원 | `F9` 또는 **창 > 기본 배치 복원** |

패널 위치와 크기는 사용자별 `TraceWave/ShellPrototype/layout.ini`에 저장한다. CTest의 `--smoke` 실행은 메모리에서만 배치를 사용한다. Wayland에서는 ImGui SDL3 백엔드에 따라 기본 창 내부 도킹을 사용한다. Linux와 macOS의 실제 화면 검수 상태는 개발문서에 기록한다.

## 표시 데이터와 의존성

PCB는 확대·이동을 시험하는 원형 예제다. S11은 B0 보존본 `B0-public-api.json`의 `result.page` 응답에서 확보한 8–12 GHz 주파수와 `magnitude_db` 31개를 사용한다. 데이터셋 SHA-256은 `ffdb9e19f126f8a0d4f17a584f88601bf2ad031f41f68689c642d7edb819dd42`다. [B0 고정 기록](../../../01_개발문서/07_검증/430_알원_비제로_기준선_확정.md)

고정 소스는 SDL 3.4.14(zlib), Dear ImGui 1.91.9b docking(MIT), ImPlot 0.16(MIT), bgfx/bx/bimg(BSD-2-Clause), bgfx.cmake(CC0)다. ImGui용 배포 셰이더 바이트코드는 동일 bgfx 소스의 예제 헤더에서 읽는다. 시제품은 시스템 글꼴을 읽으며 자체 글꼴을 포함하지 않는다. [실행 검증](../../../01_개발문서/07_검증/432_창과_렌더러_시제품_검증.md)
