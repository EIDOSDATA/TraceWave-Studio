"""! @brief 화면 설계의 편집 가능한 DrawIO 원본과 동일 좌표의 SVG 그림을 생성한다.

@details 제품 GUI나 RF 데이터를 생성하지 않는 문서 도구다. 모든 그림의 값은
화면 설명용이며 구현 상태와 물리 검증을 나타내지 않는다.
"""

from pathlib import Path
import argparse
import math
import xml.etree.ElementTree as ET

DESTINATION = Path(__file__).resolve().parents[2] / "docs/screen_design"
BLUE = "#175CD3"
INK = "#243247"
MUTED = "#536174"
LINE = "#D3DBE6"
PALE = "#EDF4FF"
AMBER = "#FFF3D6"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


class Sheet:
    """! @brief 한 화면의 도형/문자/연결선을 두 파일 형식에서 공유한다."""

    def __init__(self, slug, title, width=1600, height=1000):
        self.slug, self.title = slug, title
        self.width, self.height = width, height
        self.items = []

    def box(self, x, y, w, h, text="", fill="white", size=18,
            color=INK, stroke=LINE, bold=False, shape="rect", align="left"):
        """! @brief 편집 가능한 단일 도형과 줄바꿈 라벨을 추가한다."""
        identity = f"item-{len(self.items) + 2}"
        self.items.append(dict(id=identity, kind=shape, x=x, y=y, w=w, h=h,
                               text=text, fill=fill, size=size, color=color,
                               stroke=stroke, bold=bold, align=align))
        return identity

    def label(self, x, y, w, h, text, size=18, color=INK, bold=False):
        """! @brief 배경이 없는 설명을 추가한다."""
        return self.box(x, y, w, h, text, "none", size, color, "none", bold)

    def edge(self, points, text="", arrow=True, color=MUTED, width=2):
        """! @brief SVG와 DrawIO에서 같은 경로를 사용하는 연결선을 추가한다."""
        self.items.append(dict(id=f"item-{len(self.items)+2}", kind="edge",
                               points=points, text=text, arrow=arrow,
                               color=color, width=width))

    def write(self, target):
        """! @brief 임베드 그림 대신 실제 도형 셀을 가진 비압축 DrawIO를 기록한다."""
        mxfile = ET.Element("mxfile", host="app.diagrams.net", type="device")
        diagram = ET.SubElement(mxfile, "diagram", id=self.slug, name=self.title)
        model = ET.SubElement(diagram, "mxGraphModel", dx=str(self.width), dy=str(self.height),
                              grid="1", gridSize="10", guides="1", tooltips="1", connect="1",
                              arrows="1", fold="1", page="1", pageScale="1",
                              pageWidth=str(self.width), pageHeight=str(self.height), math="0", shadow="0")
        root = ET.SubElement(model, "root")
        ET.SubElement(root, "mxCell", id="0")
        ET.SubElement(root, "mxCell", id="1", parent="0")
        svg = ET.Element(f"{{{SVG}}}svg", width=str(self.width), height=str(self.height),
                         viewBox=f"0 0 {self.width} {self.height}", role="img",
                         attrib={"aria-labelledby": "title desc"})
        ET.SubElement(svg, f"{{{SVG}}}title", id="title").text = self.title
        ET.SubElement(svg, f"{{{SVG}}}desc", id="desc").text = (
            "TraceWave Studio 화면 설계안. 기능별 번호는 화면 명세 표와 연결된다. "
            "실제 실행 화면 또는 검증 결과가 아니다.")
        ET.SubElement(svg, f"{{{SVG}}}rect", width="100%", height="100%", fill="#F3F5F8")
        defs = ET.SubElement(svg, f"{{{SVG}}}defs")
        marker = ET.SubElement(defs, f"{{{SVG}}}marker", id="arrow", markerWidth="10",
                               markerHeight="10", refX="9", refY="5", orient="auto",
                               markerUnits="userSpaceOnUse")
        ET.SubElement(marker, f"{{{SVG}}}path", d="M 0 0 L 10 5 L 0 10 z", fill=MUTED)
        for item in self.items:
            if item["kind"] == "edge":
                points = item["points"]
                style = (f"edgeStyle=none;html=0;rounded=0;strokeColor={item['color']};"
                         f"strokeWidth={item['width']};endArrow={'block' if item['arrow'] else 'none'};")
                cell = ET.SubElement(root, "mxCell", id=item["id"], value=item["text"],
                                     style=style, edge="1", parent="1")
                geo = ET.SubElement(cell, "mxGeometry", relative="1", attrib={"as": "geometry"})
                for point, role in ((points[0], "sourcePoint"), (points[-1], "targetPoint")):
                    ET.SubElement(geo, "mxPoint", x=str(point[0]), y=str(point[1]), attrib={"as": role})
                middle = ET.SubElement(geo, "Array", attrib={"as": "points"})
                for x, y in points[1:-1]:
                    ET.SubElement(middle, "mxPoint", x=str(x), y=str(y))
                attributes = dict(points=" ".join(f"{x},{y}" for x, y in points), fill="none",
                                  stroke=item["color"], attrib={"stroke-width": str(item["width"])})
                path = ET.SubElement(svg, f"{{{SVG}}}polyline", **attributes)
                if item["arrow"]:
                    path.set("marker-end", "url(#arrow)")
                continue
            x, y, w, h = (item[key] for key in ("x", "y", "w", "h"))
            style = (f"{'ellipse' if item['kind']=='ellipse' else 'rounded=1;arcSize=8'};"
                     f"whiteSpace=wrap;html=0;fillColor={item['fill']};strokeColor={item['stroke']};"
                     f"fontFamily=Malgun Gothic;fontSize={item['size']};fontColor={item['color']};"
                     f"fontStyle={1 if item['bold'] else 0};align={item['align']};verticalAlign=middle;spacing=12;")
            cell = ET.SubElement(root, "mxCell", id=item["id"], value=item["text"], style=style,
                                 vertex="1", parent="1")
            ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h),
                          attrib={"as": "geometry"})
            if item["kind"] == "ellipse":
                ET.SubElement(svg, f"{{{SVG}}}ellipse", cx=str(x+w/2), cy=str(y+h/2),
                              rx=str(w/2), ry=str(h/2), fill=item["fill"], stroke=item["stroke"])
            else:
                ET.SubElement(svg, f"{{{SVG}}}rect", x=str(x), y=str(y), width=str(w), height=str(h),
                              rx="6", fill=item["fill"], stroke=item["stroke"])
            lines = item["text"].splitlines()
            for index, line in enumerate(lines):
                if not line:
                    continue
                tx = x + w / 2 if item["align"] == "center" else x + 12
                ty = y + h/2 - (len(lines)-1)*item["size"]*0.7 + index*item["size"]*1.4
                element = ET.SubElement(svg, f"{{{SVG}}}text", x=str(tx), y=str(ty), fill=item["color"],
                                        attrib={"font-family": "Malgun Gothic, Segoe UI, sans-serif",
                                                "font-size": str(item["size"]), "dominant-baseline": "central",
                                                "font-weight": "700" if item["bold"] else "400",
                                                "{http://www.w3.org/XML/1998/namespace}space": "preserve",
                                                "text-anchor": "middle" if item["align"]=="center" else "start"})
                element.text = line
        for folder, suffix, document in (("diagrams", ".drawio", mxfile), ("assets", ".svg", svg)):
            path = target / folder / (self.slug + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            ET.indent(document, space="  ")
            ET.ElementTree(document).write(path, encoding="utf-8", xml_declaration=True)


def header(sheet, title, subtitle):
    """! @brief 도면마다 설계 상태와 설명을 일관되게 표시한다."""
    sheet.label(32, 20, 1536, 44, title, 27, bold=True)
    sheet.label(32, 64, 1536, 42, subtitle, 17, MUTED)
    sheet.label(32, 950, 1536, 32, "화면 설계안 v0.1 / 2026-11-16 KST / 구현 및 사용성 수용과 별도 / 치수와 성능 예시 없음", 15, MUTED)


def shell(slug, title, tab, center_title):
    """! @brief 번호가 있는 Studio 공통 프레임을 구성한다."""
    s = Sheet(slug, title)
    header(s, title, "번호는 화면 명세의 요소 ID 끝 두 자리와 대응합니다. 물리 미정값과 과거 결과를 유지합니다.")
    s.box(32, 120, 1536, 44, "01  TraceWave Studio  /  안테나 설계  /  저장 필요", bold=True)
    s.box(32, 170, 1536, 48, "02  저장      실행 전 확인      STEP 출력            설계      해석      결과      비교      출력", fill=PALE)
    s.label(1240, 170, 290, 48, f"현재 작업: {tab}", 17, BLUE, True)
    s.box(32, 230, 280, 530, "", "white")
    s.label(40, 236, 260, 40, "03  프로젝트 / 객체", 20, bold=True)
    s.box(48, 284, 248, 40, "객체 찾기...", "#F8FAFC", 16, MUTED)
    for i, text in enumerate(["안테나 설계", "  목표", "  PCB / 적층", "  패턴", "    원호 01", "    접지면 01", "  급전", "  재료", "  외부 환경", "  실행 / 결과"]):
        s.box(48, 338+i*36, 248, 34, text, PALE if i==4 else "none", 17,
              BLUE if i==4 else INK, "none", i==4)
    s.box(32, 770, 280, 154, "04  레이어 / 표시\n표시      활성 층\n[x]      Top Copper\n[x]      Substrate", size=17)
    s.box(324, 230, 910, 530, "")
    s.box(336, 238, 886, 42, f"05  {center_title}", "#F8FAFC", 19, bold=True)
    s.box(1246, 230, 322, 694, "")
    s.label(1260, 238, 290, 42, "08  선택 속성", 20, bold=True)
    s.box(324, 770, 910, 154, "")
    s.label(338, 778, 880, 35, "09  문제   /   작업   /   로그", 18, bold=True)
    s.label(338, 816, 880, 82, "진행률은 worker가 제공한 범위만 표시\n취소 요청과 실제 종료 확인을 구분", 17, MUTED)
    s.box(32, 930, 1536, 22, "10  단위 mm    |    활성 층 Top Copper    |    스냅 끔    |    worker 상태 별도 표시", "#E8EEF6", 14)
    return s


def design():
    """! @brief 도구 레일과 탐색 공간을 개선한 설계 화면을 그린다."""
    s = shell("studio-design", "S11 / 설계 - 2D 편집", "설계", "2D 편집   |   3D 형상")
    s.box(336, 292, 886, 40, "06  선택  /  선  /  원호    |    좌표 입력    |    스냅 설정    |    전체 맞춤", PALE, 17)
    s.box(336, 342, 886, 402, "", "#F6FAFF")
    for x in range(356, 1220, 24):
        s.edge([(x, 344), (x, 742)], arrow=False, color="#E6EDF5", width=1)
    for y in range(352, 743, 24):
        s.edge([(338, y), (1220, y)], arrow=False, color="#E6EDF5", width=1)
    s.box(622, 362, 354, 354, "", "#DDF0DC", stroke="#6B8C70", shape="ellipse")
    points = [(round(799+143*math.cos(t), 2), round(539-143*math.sin(t), 2))
              for t in [math.radians(25+i*130/40) for i in range(41)]]
    s.edge(points, arrow=False, color="#E29042", width=12)
    for x,y in (points[0], points[-1]):
        s.box(x-5, y-5, 10, 10, "", BLUE, stroke=BLUE)
    s.label(736, 540, 240, 50, "07  原形: 원호 01".replace("原形", "선택"), 19, BLUE, True)
    s.box(1280, 292, 264, 46, "이름: 원호 01     [변경]", PALE, 17)
    s.label(1270, 354, 280, 182, "형상\n반지름   [현재 값] mm\n선폭       [현재 값] mm\n시작각   [현재 값] deg\n끝각       [현재 값] deg", 17)
    s.box(1270, 560, 280, 78, "출처 / 가정 열기\n생성 당시 입력 보존", "#F8FAFC", 17)
    s.box(1270, 650, 280, 80, "제작 / 측정 조건 미정\n입력 완료와 검증은 별도", AMBER, 17)
    s.box(1280, 838, 118, 46, "적용", BLUE, 18, "white", BLUE, align="center")
    s.box(1410, 838, 128, 46, "되돌리기", align="center")
    return s


def analysis():
    """! @brief 실행 전 검토 및 실행 상태의 화면을 그린다."""
    s=shell("studio-analysis", "S20 / 해석 - 입력 확인과 실행", "해석", "입력 검사   |   해석 조건   |   연구 계획")
    s.box(350, 300, 856, 70, "06  현재 입력 개정과 실행할 snapshot을 확인합니다.\n표면층 / 외부 환경의 EM 포함은 지원 여부 확인 필요", AMBER, 18)
    rows=[("기판 / 도체 / 급전", "입력 검사 결과"), ("재료 / 출처 / 가정", "미정 또는 채택 근거"), ("경계 / 격자 / 종료", "사용자 설정"), ("시간 / 메모리 예산", "계획값 / 실제값 구분"), ("목표 대역", "solver 설정과 비교")]
    for i,(a,b) in enumerate(rows):
        s.box(350, 390+i*48, 420, 44, a, "#F8FAFC", 17)
        s.box(780, 390+i*48, 426, 44, b, size=17)
    s.box(350, 656, 260, 52, "07  검사 다시 실행", PALE, 18)
    s.box(626, 656, 580, 52, "해석 시작 - 차단 문제가 없을 때 활성화", "#E9EEF5", 18, MUTED)
    s.label(1270, 292, 280, 230, "실행 검토\n입력 개정: 현재 개정\n지원 profile: 선택값\n재료 모델: 근거 열기\n생략 항목: 확인 필요\n실제 제작 조건: 미정", 17)
    s.box(1270, 590, 280, 120, "실행 후 탐색 가능\n완료 알림에서 결과 열기\n편집 화면을 강제 이동하지 않음", PALE, 16)
    return s


def results():
    """! @brief 실데이터가 없는 결과 화면의 빈 상태를 그린다."""
    s=shell("studio-results", "S30 / 결과 - 원본과 판정", "결과", "네트워크   |   전력 / 손실   |   방사 / 필드")
    s.box(350, 300, 856, 52, "06  실행 선택  [아직 없음]    /    기준면  [미정]    /    Z0  [미정]", PALE, 17)
    s.box(350, 368, 856, 230, "07  표시할 계산 결과가 없습니다.\n해석을 실행하거나 저장된 완료 결과를 여세요.\n곡선을 임의로 그리지 않습니다.", "#F8FAFC", 21, MUTED, align="center")
    s.box(350, 614, 856, 94, "수치 표  /  주파수  /  실수  /  허수  /  단위  /  유효 상태\n결과가 선택되면 실제 표본을 조회합니다.", size=17)
    s.label(1270, 292, 280, 260, "결과 근거\n실행 / 입력 snapshot\n생성 / 원문 hash\n현재 설계와의 관계\n수치 수렴: 미평가\n물리 정확도: 미평가\n目標: 미평가".replace("目標", "목표"), 17)
    s.box(1270, 610, 280, 94, "3D 형상과 3D 방사는\n서로 다른 보기입니다.\n미지원 결과는 사유 표시", AMBER, 17)
    return s


def compare():
    """! @brief 비교 전 정렬과 실측 미확보 상태를 그린다."""
    s=shell("studio-comparison", "S40 / 비교 - 조건과 근거", "비교", "계산 결과   |   수렴 연구   |   측정 비교")
    s.box(350, 300, 856, 54, "06  비교 자료 추가    |    주파수 / 포트 / 기준면 / Z0 확인", PALE, 17)
    s.box(350, 370, 856, 104, "자료 A: 선택 필요       자료 B: 선택 필요\n조건이 다르면 일치 항목 / 변환 필요 / 비교 불가를 구분", size=18)
    s.box(350, 490, 856, 110, "07  비교 준비 전\n보간과 기준면 변환은 명시적 검토 뒤 파생 자료로 보존", "#F8FAFC", 20, MUTED, align="center")
    s.box(350, 616, 856, 92, "측정 자료 미확보\n교정 / 시료 / 케이블 / 지그 / 환경 / 불확도는 미정 유지", AMBER, 18)
    s.label(1270, 292, 280, 260, "비교 설정\n자료의 원본과 개정\n변환 이력 / 보간 범위\n관측량과 단위\n목표 판정 근거\n조건 불일치 안내", 17)
    s.box(1270, 610, 280, 94, "현재 구현: 연구 보고서\n일반 곡선 / 측정 비교:\n5 / 7 / 11번 후속", PALE, 17)
    return s


def output():
    """! @brief 동일 개정의 출력과 검수를 구분해 그린다."""
    s=shell("studio-output", "S50 / 출력 - 생성과 검수", "출력", "도면   |   STEP   |   PCB 교환   |   보고서 / 인계")
    s.box(350, 300, 856, 54, "06  출력 입력 snapshot 고정    |    출력 형식 / profile 선택", PALE, 17)
    for i,text in enumerate(["STEP: 현재 기본 출력 지원", "PDF / SVG / DXF 도면: 10번 후속", "KiCad / Gerber / 드릴 / Job: 10번 후속", "프로젝트 인계 / 검수 보고서: 12번 후속"]):
        s.box(350, 372+i*54, 856, 48, text, "#F8FAFC", 18)
    s.box(350, 604, 856, 104, "07  미리보기 -> 생성 -> 파일 확인 -> 지원 profile 검수\n생성 성공을 RF / 제조 / 독립 교환 합격으로 표시하지 않습니다.", AMBER, 18)
    s.label(1270, 292, 280, 240, "출력 계획\n입력 개정 / 범위\n단위 / 좌표계\n객체 / net / layer 대응\n생략 및 미지원 항목\n파일 경로 / 해시", 17)
    s.box(1270, 610, 280, 90, "독립 검수: 미평가\n현재 STEP 상태:\ngenerated_unverified", PALE, 16)
    return s


def startup():
    """! @brief 시작 및 복구 화면의 제안 배치를 그린다."""
    s=Sheet("studio-start", "S00 / 시작 - 프로젝트와 복구")
    header(s, s.title, "신규 시작 화면의 제안입니다. 현재 GUI의 생성 / 열기 명령을 단계적으로 연결합니다.")
    s.box(60, 160, 1480, 80, "TraceWave Studio        새 프로젝트        프로젝트 열기        환경 진단", PALE, 24, bold=True)
    s.box(60, 270, 880, 600, "")
    s.label(90, 294, 800, 50, "01  최근 프로젝트", 25, bold=True)
    s.box(90, 370, 800, 210, "아직 등록된 최근 프로젝트가 없습니다.\n프로젝트 이름과 저장 위치부터 지정하세요.\n물성 / 주파수 / 포트 값은 자동으로 채우지 않습니다.", "#F8FAFC", 22, MUTED, align="center")
    s.box(90, 630, 380, 68, "02  빈 프로젝트 만들기", BLUE, 20, "white", BLUE)
    s.box(490, 630, 400, 68, "03  기존 프로젝트 열기", PALE, 20)
    s.box(970, 270, 570, 600, "")
    s.label(1000, 294, 510, 50, "04  복구 / 환경 상태", 25, bold=True)
    s.box(1000, 370, 510, 160, "복구 후보가 있으면\n정식 저장본 / 후보의 시각과 차이를 표시\n원본을 덮기 전에 선택", AMBER, 20)
    s.box(1000, 560, 510, 170, "05  CAD / WSL 환경 확인\n환경 미구성 시 편집과 저장 가능\n실행에 필요한 항목만 안내", PALE, 20)
    return s


def dialogs():
    """! @brief 입력과 검토 두 단계 대화상자의 번호를 그린다."""
    s=Sheet("studio-settings", "D10-D15 / 설정과 이름 변경")
    header(s, s.title, "대화상자 별 세부 필드는 화면 명세 표를 따릅니다. 미적용 입력 / 적용됨 / 저장됨을 구분합니다.")
    s.box(50, 150, 730, 740, "")
    s.label(70, 172, 690, 50, "01  설정 제목 / 현재 대상", 25, bold=True)
    s.box(70, 240, 190, 500, "02  대상 목록\n\n현재 선택\n추가\n복제 (후속)\n삭제", "#F8FAFC", 20)
    s.box(280, 240, 480, 100, "03  기본 입력\n필드명 / 값 또는 식 / 단위", PALE, 20)
    s.box(280, 360, 480, 100, "04  출처 / 가정 / 미정\n현재 값과 최초 원본을 분리", AMBER, 20)
    s.box(280, 480, 480, 160, "05  검토 / 미리보기\n변경 대상과 생략 범위\n오류는 해당 필드와 연결\n새 입력이면 기존 검토 무효화", size=20)
    s.box(280, 660, 480, 80, "06  미적용 입력 있음", "#F8FAFC", 20)
    s.box(70, 788, 210, 60, "07  적용", BLUE, 20, "white", BLUE)
    s.box(300, 788, 210, 60, "08  닫기", size=20)
    s.box(530, 788, 230, 60, "도움말 / 출처", size=20)
    s.box(820, 150, 730, 740, "")
    s.label(840, 172, 690, 50, "D15 / 이름 변경", 25, bold=True)
    s.box(850, 252, 670, 100, "01  현재 객체: 원호 01\n현재 도체층: Top Copper", PALE, 22)
    s.box(850, 380, 670, 70, "02  표시 이름  [주 방사 원호]", size=22)
    s.box(850, 478, 670, 130, "03  같은 종류 이름과 중복이면 안내\n내부 ID와 수식 변수는 바뀌지 않음\n최초 문헌 / 생성 사본을 덮어쓰지 않음", AMBER, 20)
    s.box(850, 640, 670, 68, "04  상세 식별자  [펼치기 / 복사]", "#F8FAFC", 20)
    s.box(850, 788, 320, 60, "05  변경", BLUE, 20, "white", BLUE)
    s.box(1190, 788, 330, 60, "06  취소", size=20)
    return s


def navigation():
    """! @brief 선택과 초안을 보존하는 Studio 화면 전환을 그린다."""
    s=Sheet("studio-navigation", "Studio 화면 전환도")
    header(s, s.title, "실선은 사용자 동작입니다. 화면 이동만으로 적용 / 계산 / 취소를 실행하지 않는 목표 계약입니다.")
    s.box(40, 150, 280, 100, "S00 시작 / 복구\n새 프로젝트 또는 열기", PALE, 22)
    s.box(410, 150, 1140, 100, "공통 프레임: 프로젝트 / 저장 상태 / 선택 / 작업 알림\n설계 - 해석 - 결과 - 비교 - 출력 탭은 언제든 이동 가능", PALE, 24)
    s.edge([(320,200),(410,200)])
    nodes=[("S10 설계\nS11 2D / S12 3D", 40), ("S20 해석\n입력 검사 / 실행", 350), ("S30 결과\n실행 선택 / 근거", 660), ("S40 비교\n조건 정렬 / 측정", 970), ("S50 출력\n계획 / 생성 / 검수",1280)]
    for text,x in nodes:
        s.box(x, 360, 270, 120, text, "white", 23)
        s.edge([(x+135,250),(x+135,360)]) if x>40 else s.edge([(520,250),(520,300),(175,300),(175,360)])
    s.box(40, 550, 580, 160, "D10 목표 / D11 문헌과 후보\nD12 기판과 재료 / D13 적층과 환경\nD14 제약과 DRC / D15 이름 변경", PALE, 21)
    s.edge([(175,480),(175,550)])
    s.box(660, 550, 890, 160, "P10 문제 -> 해당 객체 / 필드로 이동\nP11 작업 -> 실행 개정 / 취소 요청 / 결과 열기\n완료와 실패는 알림으로 전달, 현재 편집 문맥 유지", AMBER, 22)
    s.box(40, 780, 1510, 110, "공통 전환 규칙\n미적용 초안이 영향받으면 적용 / 버리기 / 머무르기. 결과 불명은 재조회 후 해제. Esc는 해석 취소가 아님.", "white", 21)
    return s


def lifecycle():
    """! @brief 미적용 입력과 적용, 저장, 불명 응답의 전이를 그린다."""
    s=Sheet("edit-lifecycle", "편집 / 적용 / 저장 / 재열기 상태도")
    header(s, s.title, "화면 상태와 원본 상태는 별개입니다. 적용 성공을 디스크 저장 완료로 표시하지 않습니다.")
    boxes=[(40,180,"저장됨\n권위 원본 조회"),(430,180,"미적용 입력\n화면 초안만 변경"),(820,180,"적용 중\n중복 적용 잠금"),(1210,180,"적용됨 / 저장 필요\n새 개정 + undo 한 번")]
    for x,y,t in boxes:s.box(x,y,340,120,t,PALE,22)
    for a,b in [(380,430),(770,820),(1160,1210)]:s.edge([(a,240),(b,240)])
    s.label(430,130,340,40,"입력",18,MUTED)
    s.label(820,130,340,40,"적용 명령",18,MUTED)
    s.label(1210,130,340,40,"성공 영수증",18,MUTED)
    s.box(430,420,340,130,"검증 오류\n초안과 오류 위치 유지",AMBER,22)
    s.box(820,420,340,130,"응답 결과 불명\n자동 재전송 금지",AMBER,22)
    s.box(1210,420,340,130,"저장 요청\n실패 시 저장 필요 유지",PALE,22)
    s.edge([(910,300),(910,360),(600,360),(600,420)])
    s.edge([(1010,300),(1010,420)])
    s.edge([(1380,300),(1380,420)])
    s.box(430,670,730,100,"권위 상태 / 영수증 재조회\n개정과 현재 객체 확인 후 초안 대조", "white",22)
    s.edge([(990,550),(990,670)])
    s.box(1210,670,340,100,"저장 완료 / 재열기\n이름 / 출처 / 미정 확인",PALE,20)
    s.edge([(1380,550),(1380,670)])
    s.box(40,820,1510,80,"화면 이동 / 창 닫기: 영향받는 초안에 한해 적용 / 버리기 / 머무르기. 장시간 작업의 실제 취소는 별도 명령.", "white",20)
    return s


def identity():
    """! @brief 이름, ID, 원본 출처와 과거 결과의 분리를 그린다."""
    s=Sheet("object-identity", "객체 이름과 안정 ID / 선택 연결")
    header(s,s.title,"표시 이름은 사람이 읽고 수정합니다. 내부 ID는 참조와 이력을 연결하며 기본 화면에서 접습니다.")
    s.box(50,170,450,160,"현재 객체\n표시 이름: 주 방사 원호\n불변 ID: 내부 상세에서 확인",PALE,25)
    s.box(570,170,450,160,"이름 변경 명령\n원호 01 -> 주 방사 원호\n한 개정 / 실행 취소 / 저장", "white",24)
    s.edge([(500,250),(570,250)])
    s.box(1090,170,460,160,"변하지 않는 관계\n레이어 / net / 포트 참조\n수식 변수와 형상 치수",AMBER,24)
    s.edge([(1020,250),(1090,250)])
    for x,t in [(50,"프로젝트 트리"),(440,"2D / 3D 보기"),(830,"선택 속성"),(1220,"문제 위치")]:
        s.box(x,450,330,100,t,"white",24)
    s.box(50,610,1500,90,"선택 문맥 = 프로젝트 + 개정 + 객체 ID + 부분 역할 / 동일 문맥만 동기화",PALE,23)
    for x in (215,605,995,1385):s.edge([(x,550),(x,610)])
    s.box(50,780,710,110,"문헌 / 생성 당시 사본\n원문 이름과 원래 입력을 그대로 보존",AMBER,23)
    s.box(810,780,740,110,"과거 snapshot / 완료 결과\n당시 이름으로 표시하고 현재 개정과 구분",AMBER,23)
    return s


def main():
    """! @brief 모든 화면과 흐름을 같은 도형 정의에서 다시 만든다."""
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=DESTINATION)
    args=parser.parse_args()
    sheets=[design(),analysis(),results(),compare(),output(),startup(),dialogs(),navigation(),lifecycle(),identity()]
    for sheet in sheets:
        sheet.write(args.output)
    print(f"{len(sheets)} DrawIO + {len(sheets)} SVG generated")


if __name__ == "__main__":
    main()
