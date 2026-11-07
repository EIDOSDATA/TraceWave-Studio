# wxWidgets GUI 소스 영역

이 경로에 Windows wxMSW 기반 C++ GUI와 GUI 빌드 설정을 작성한다. 현재는 위치와 책임만 확정했으며 C++ GUI 소스/의존성 구성/빌드/성능 검증은 아직 수행하지 않았다.

Python 서비스의 최소 명령/표시 DTO 계약 이후 창, 프로젝트 트리, 속성 편집, 2D/3D 표시와 작업 상태를 연결한다. 서비스 연결은 UTF-8 JSON-RPC/NDJSON이며 domain 원본, 단위/물리식/정규 hash를 GUI에서 재구현하지 않는다. Python embedding과 Qt 계열 의존성은 사용하지 않는다.

CMake 기반 빌드를 구성할 예정이며 실제 compiler/wxWidgets 버전과 모듈 조합은 빌드/통합 시험 후 고정한다. wxAUI와 wxGLCanvas 등 기본 부품을 우선 검토한다. 유료 부품은 기본 기능에 필수로 요구하지 않는다.

일반 편집 60 fps/대형 장면 30 fps 목표를 유지하며 idle에서 강제 redraw를 돌리지 않는다. GUI뿐 아니라 서비스, CAD/solver worker와 GPU 비용까지 24번 기준으로 측정한다.

C++ 코드는 한국어 Doxygen 주석, BSD/Allman 중괄호, 공백 4칸 들여쓰기와 제어문 중괄호 필수 규칙을 적용한다.
