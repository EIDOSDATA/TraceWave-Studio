# 원형 PCB 외곽 계약

갱신일: 2026-11-11 KST. 원형 기판은 안테나 원호 패턴과 별개의 원본 객체다. 기판의 중심/반지름을 바꾸어도 접지나 도체를 자동 생성, 이동, 절단하지 않는다. 기존 직사각형 외곽과 함께 지원하며 승인 문서의 초기 IFA 40 x 60 mm 기준을 원형으로 바꾸는 변경은 아니다.

## 저장과 편집

프로젝트의 `board.outline`은 다음 중 하나다. 길이는 기존 Quantity 또는 UUID 매개변수 참조이며 미정값도 저장할 수 있다.

```text
rectangle: {kind: rectangle, width: Quantity, height: Quantity}
circle: {kind: circle, center: [Quantity, Quantity], radius: Quantity}
```

원의 중심은 기판 좌표계의 x/y다. 좌표계 원점과 같다고 추정하지 않으며 음수 중심도 허용한다. 반지름은 알려진 경우 양수여야 한다. 원형 외곽에 사각형 width/height를 함께 넣거나 서로 다른 외곽 의미를 혼합하지 않는다. `board.set`으로 외곽을 변경할 수 있으며 변경 전 외곽은 기존 명령 이력의 undo/redo에 보존된다.

`canvas.apply`의 `create_circular_board`는 `{id, center_x_mm, center_y_mm, radius_mm}`를 받는다. 기존 기판이 있거나 ID가 충돌하면 덮어쓰지 않고 거절한다. 새 기판에는 재료, 접지, 급전 또는 층이 자동으로 추가되지 않는다. 기존 `create_board`와 직사각 DTO 형식은 그대로 유지한다.

원형 표시 DTO의 board는 `{id, kind: circle, center: [x_mm, y_mm], radius: mm}`다. 중심의 한 좌표라도 미정이면 center가 null이고 반지름 미정은 radius=null이다. 생략 사유를 omissions로 전달하며 0으로 치환하지 않는다. 표시 범위를 벗어나는 외곽이나 부동소수점에서 원의 두 경계가 구분되지 않는 경우도 표시를 생략한다. 원본 수량은 변경하지 않는다.

속성 폼은 중심 x/y와 반지름을 기존 Quantity 편집기로 표시한다. 단위 변경과 UUID 매개변수 결합을 보존하며 스냅샷 생성, 저장, 재시작에서도 동일한 외곽 의미를 유지한다.

원형 기판에도 선/원호, 구멍을 가진 접지 polygon, 원형/회전 사각 pad와 명시적 중공 PTH via를 배치할 수 있다. 이 객체들은 기판 외곽과 별도의 geometry UUID이며 원형 외곽 선택만으로 접지/패드/비아를 생성하지 않는다. polygon의 빈 영역과 via의 drill/도금/pad 참조, GUI 좌표 표와 다중 pad 선택은 [도체와 IFA 확장](copper_features.md)을 따른다.

## CAD와 STEP

CAD 입력의 원형 board는 `{id, kind: circle, center_mm: [x,y], radius_mm}`다. 정확한 유전체 고체는 Open CASCADE의 analytic cylinder로 생성한다. STEP/B-rep의 원통을 다각형으로 대체하지 않으며 표시용 삼각형만 별도 생성한다. 유전체 층의 실제 z 위치와 두께는 기존 적층 입력을 그대로 사용한다.

도체의 중심선만 원 안에 있다고 합격시키지 않는다. 선폭과 원형 끝단, polygon/pad를 포함한 실제 도체 고체에서 원형 기판 coverage를 차감해 외부 고체가 남는지 확인하며 via의 drill/barrel 외곽도 검사한다. CAD 허용오차 1e-6 mm를 외곽 비교에 적용하며, 원 밖인 패턴을 자동으로 잘라내지 않는다. 직사각 bounding box 안에 있지만 원 외곽 밖인 선 끝단과 치우친 원호도 차단한다. 이는 기하 포함 검사이며 제조사의 최소 가장자리 간격 DRC를 대신하지 않는다.

반지름/중심, 매개변수 결합과 미정 RF 물성은 source_semantics에 보존한다. CAD 출력 때문에 유전율이나 전도도를 추정하지 않는다. CAD 최소 치수/좌표 상한과 출력의 `generated_unverified` 상태, 같은 kernel 재입력의 한계는 [CAD 계약](cad_contract.md)을 따른다.

## 명시적 급전 영역

기존 lumped 포트에는 선택적으로 `excitation_box: {start: [Quantity,Quantity,Quantity], stop: [Quantity,Quantity,Quantity]}`를 저장할 수 있다. 세 좌표는 길이 수량이며 미정 또는 매개변수 결합을 유지한다. 알려진 두 끝점이 완전히 같으면 거절한다. 기존 포트에 위치가 없다는 이유로 임의 영역을 생성하지 않는다.

도메인의 저장 허용은 해석 실행 가능 판정이 아니다. 실제 solver 계획/준비에서는 급전 영역의 완비, 방향, 크기, 양극/기준 도체 접촉과 해석 profile의 제약을 별도로 검사한다. 명시적으로 생성한 pad/via/급전선과 접지/단락부를 CAD/EM에서 소비하지만 excitation_box만으로 주변 도체가 자동 생성되지 않는다. 동일 sheet 면의 x/y gap과 서로 다른 sheet 사이 z gap을 지원하며 같은 net의 IFA도 실제 열린 gap과 의도한 도체 연결을 확인한다. 실제 SMA launch/실장 부품과 측정 기준면은 후속이다.

원형 유전체의 EM 모델은 CSXCAD Cylinder이고 도체의 원/원호는 명시적 오차로 polygon 근사한다. polygon 구멍, 유한 전도도 sheet와 중공 PTH, native 격자의 접속 표현을 확인하더라도 CAD의 정확 원통과 RF 수렴을 동일시하지 않는다. [PCB 해석 계약](pcb_solver_contract.md)의 `computed_unvalidated` 상태를 유지한다. 물리 검증 순서는 단일 포트 IFA의 수렴/물성/실측 대조 이후 원형 PCB/원호와 NF2FF로 확장한다.

## 검증

`tests/test_circular_board.py`는 직사각 호환, 미정/잘못된 외곽, 표현 범위, UUID 매개변수 보존, 속성 편집, 원형 생성 undo/redo, 스냅샷 불변성과 재시작을 검증한다. optional 급전 영역의 저장과 0 길이/잘못된 좌표도 검사한다.

native 시험은 실제 STEP를 다시 읽어 원통의 체적 `pi*r*r*h`, 중심, 외곽, 단면 면적과 표시 mesh를 확인한다. 사각 bbox 내부에 있는 원 외부 round cap 및 offset arc가 출력되지 않는 것도 검사한다. 기하 시험 성공을 원형 PCB 안테나의 RF 성능이나 제조 가능성 검증으로 확대하지 않는다.

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_circular_board.py -v
.\.venv-cad\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_circular_board.py -v
```

Windows 서비스 환경에서 순수 8개 통과와 native 2개 스킵, 별도 CAD 환경에서 10개 모두 통과했다. native 실행 로그는 `.local/circular-board-native-tests.log`다. 기존 설계 의미 모델 22개와 CAD projection 15개도 통과했다. GUI와 PCB solver 연결의 통합 검증은 [개발 상태](development_status.md)의 해당 변경 기록을 따른다.
