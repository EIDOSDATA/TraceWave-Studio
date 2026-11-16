"""! @brief 같은 벡터 도형으로 구현 시안과 편집 가능한 DrawIO를 생성한다.

@details 수치는 화면 배치용 예시이며 물리 원본이나 해석 결과가 아니다.
"""

import math
import base64
import zlib
from pathlib import Path
import xml.etree.ElementTree as ET

WHITE = "#FFFFFF"
BG = "#EFF2F6"
PANEL = "#F8FAFC"
LINE = "#D0D8E3"
INK = "#192A3D"
MUTED = "#52657B"
BLUE = "#0866D8"
PALE = "#E8F1FE"
GREEN = "#167449"
AMBER = "#985A09"
RED = "#B43434"
COPPER = "#F8A255"
BOARD = "#C7E4CC"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


class Screen:
    """! @brief 화면의 도형, 컨트롤 경계와 문서 메타데이터를 함께 관리한다."""

    def __init__(self, stem, screen_id, title, workspace="설계", ui=None, state="구현 목표"):
        self.stem, self.screen_id, self.title = stem, screen_id, title
        self.workspace, self.ui, self.state = workspace, ui or [], state
        self.width, self.height = 1920, 1080
        self.items = []
        self.notes = []

    def add(self, kind, **attrs):
        """! @brief 기본 도형을 순서대로 추가한다."""
        self.items.append(dict(kind=kind, **attrs))

    def rect(self, x, y, w, h, fill=WHITE, stroke=LINE, radius=0, sw=1):
        """! @brief 창과 native 컨트롤의 경계를 그린다."""
        self.add("rect", x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, radius=radius, sw=sw)

    def line(self, x1, y1, x2, y2, color=LINE, sw=1, dash=None):
        """! @brief 분리선이나 캔버스 보조선을 그린다."""
        self.add("line", points=[(x1, y1), (x2, y2)], fill="none", stroke=color, sw=sw, dash=dash)

    def poly(self, points, fill="none", stroke=INK, sw=1, close=False, dash=None):
        """! @brief 곡선 표본이나 CAD 표시 외곽을 벡터로 유지한다."""
        self.add("poly", points=points, fill=fill, stroke=stroke, sw=sw, close=close, dash=dash)

    def ellipse(self, x, y, w, h, fill=WHITE, stroke=LINE, sw=1):
        """! @brief 원과 타원 도형을 그린다."""
        self.add("ellipse", x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, sw=sw)

    def text(self, x, y, value, size=16, color=INK, bold=False, width=None, align="left"):
        """! @brief 기준선과 검수용 최대 너비를 가진 실제 문자열을 그린다."""
        self.add("text", x=x, y=y, text=str(value), size=size, fill=color,
                 bold=bold, width=width, align=align)

    def icon(self, name, x, y, color=MUTED, size=20):
        """! @brief 외부 아이콘 자산 없이 단순 기능 아이콘을 그린다."""
        k = size / 20
        def p(points, close=False, fill="none"):
            self.poly([(x+a*k, y+b*k) for a,b in points], fill, color, 1.7, close)
        if name == "arc":
            p([(2+i*0.8, 16-12*math.sin(math.pi*i/20)) for i in range(21)])
        elif name == "line":
            p([(3,17),(17,3)])
        elif name == "select":
            p([(4,2),(4,18),(8,13),(12,19),(15,17),(11,11),(18,10)], True, WHITE)
        elif name == "cube":
            p([(10,1),(18,6),(18,15),(10,19),(2,15),(2,6),(10,1)])
            p([(2,6),(10,10),(18,6)]); p([(10,10),(10,19)])
        elif name == "play":
            p([(5,3),(17,10),(5,17)], True, color)
        elif name == "save":
            p([(3,2),(15,2),(18,5),(18,18),(2,18),(2,2),(3,2)], True)
            p([(6,2),(6,8),(14,8),(14,2)]);p([(6,18),(6,12),(14,12),(14,18)])
        elif name == "folder":
            p([(1,5),(8,5),(10,8),(19,8),(17,17),(1,17)], True, "#E5EFFC")
        elif name == "target":
            self.ellipse(x+2*k,y+2*k,16*k,16*k,"none",color,1.5)
            self.ellipse(x+6*k,y+6*k,8*k,8*k,"none",color,1.5)
            self.line(x+10*k,y,x+10*k,y+20*k,color); self.line(x,y+10*k,x+20*k,y+10*k,color)
        elif name == "layers":
            for yy in (3,8,13): p([(1,yy+3),(10,yy-1),(19,yy+3),(10,yy+7),(1,yy+3)])
        elif name == "port":
            self.ellipse(x+6*k,y,8*k,8*k,"none",color,1.7)
            self.line(x+10*k,y+8*k,x+10*k,y+18*k,color,1.7)
            self.line(x+5*k,y+18*k,x+15*k,y+18*k,color,1.7)
        elif name == "search":
            self.ellipse(x+2*k,y+2*k,11*k,11*k,"none",color,1.6)
            self.line(x+12*k,y+12*k,x+18*k,y+18*k,color,1.8)
        elif name == "fit":
            for a,b,c,d in ((2,7,2,2),(2,2,7,2),(13,2,18,2),(18,2,18,7),(2,13,2,18),(2,18,7,18),(13,18,18,18),(18,18,18,13)):
                self.line(x+a*k,y+b*k,x+c*k,y+d*k,color,1.5)
        elif name == "check": p([(3,10),(8,15),(18,4)])
        elif name == "warning":
            p([(10,1),(20,19),(0,19)],True,"#FFF4D6")
            self.line(x+10*k,y+7*k,x+10*k,y+12*k,color,2)
            self.ellipse(x+9*k,y+15*k,2*k,2*k,color,color)
        elif name == "plus":
            self.line(x+3*k,y+10*k,x+17*k,y+10*k,color,1.6)
            self.line(x+10*k,y+3*k,x+10*k,y+17*k,color,1.6)
        elif name == "gear":
            self.ellipse(x+3*k,y+3*k,14*k,14*k,"none",color,1.6)
            self.ellipse(x+7*k,y+7*k,6*k,6*k,"none",color,1.6)
        elif name == "chart": p([(2,2),(2,18),(19,18)]);p([(4,13),(8,8),(12,11),(18,3)])
        elif name == "doc": p([(3,1),(13,1),(18,6),(18,19),(3,19)], True);p([(13,1),(13,6),(18,6)]);p([(6,10),(15,10)]);p([(6,14),(15,14)])
        elif name == "close":p([(4,4),(16,16)]);p([(4,16),(16,4)])
        elif name == "down":p([(5,8),(10,13),(15,8)])
        elif name == "right":p([(7,4),(13,10),(7,16)])
        else:
            self.rect(x+3*k,y+3*k,14*k,14*k,"none",color,2)

    def button(self, x, y, w, label, primary=False, icon=None, disabled=False, h=34):
        """! @brief native 버튼의 텍스트와 활성 상태를 표시한다."""
        fill = "#F0F2F5" if disabled else BLUE if primary else WHITE
        fg = "#778496" if disabled else WHITE if primary else INK
        self.rect(x,y,w,h,fill,BLUE if primary and not disabled else LINE,3)
        if icon:
            self.icon(icon,x+10,y+(h-18)/2,fg,18)
            self.text(x+35,y+h/2+5,label,15,fg,width=w-43)
        else:
            self.text(x+w/2,y+h/2+5,label,15,fg,width=w-16,align="center")

    def field(self,x,y,w,label,value,unit="",state=None):
        """! @brief 필드 이름, 입력, 단위와 미정 상태를 한 행으로 묶는다."""
        self.text(x,y+17,label,15,MUTED,width=w)
        input_w=w-(48 if unit else 0)
        self.rect(x,y+28,input_w,34,WHITE,LINE,2)
        self.text(x+10,y+50,value,16,MUTED if value in ("미정","선택하지 않음") else INK,width=input_w-20)
        if unit:self.text(x+input_w+8,y+50,unit,14,MUTED,width=44)
        if state:self.text(x,y+82,state,13,AMBER,width=w)

    def choice(self,x,y,w,label,value):
        """! @brief 자유 입력과 구분되는 native 목록 선택 필드를 그린다."""
        self.text(x,y+17,label,15,MUTED,width=w)
        self.rect(x,y+28,w,34,WHITE,LINE,2)
        self.text(x+10,y+50,value,16,MUTED if value in ("미정","선택하지 않음") else INK,width=w-42)
        self.icon("down",x+w-27,y+35,MUTED,18)

    def check(self,x,y,label,checked=True,width=400):
        """! @brief 체크 상태와 읽을 수 있는 라벨을 함께 제공한다."""
        self.rect(x,y,16,16,BLUE if checked else WHITE,BLUE if checked else LINE,2)
        if checked:self.icon("check",x+1,y,WHITE,14)
        self.text(x+25,y+14,label,15,INK,width=width-25)

    def tabs(self,x,y,width,labels,active=0):
        """! @brief 같은 작업 내부의 하위 탭을 그린다."""
        self.rect(x,y,width,42,PANEL,LINE)
        cursor=x+10
        for i,label in enumerate(labels):
            w=max(90,len(label)*16+30)
            if i==active:
                self.rect(cursor,y+1,w,40,WHITE,"none")
                self.rect(cursor+8,y+38,w-16,3,BLUE,"none")
            self.text(cursor+w/2,y+27,label,15,BLUE if i==active else MUTED,i==active,w-12,"center")
            cursor+=w

    def heading(self,x,y,label,subtitle=None,width=1000):
        """! @brief 영역 제목과 필요 설명을 구분한다."""
        self.text(x,y,label,21,INK,True,width)
        if subtitle:self.text(x,y+28,subtitle,15,MUTED,width=width)

    def notice(self,x,y,w,label,kind="info",detail=None):
        """! @brief 경고를 색에만 의존하지 않고 설명으로 표시한다."""
        color=AMBER if kind=="warn" else BLUE
        fill="#FFF7E7" if kind=="warn" else PALE
        self.rect(x,y,w,70 if detail else 42,fill,"#ECD6AE" if kind=="warn" else "#C5D9F5",3)
        self.icon("warning" if kind=="warn" else "doc",x+12,y+12,color,18)
        self.text(x+40,y+27,label,15,color,True,w-52)
        if detail:self.text(x+40,y+53,detail,14,MUTED,width=w-52)

    def section(self,x,y,w,label):
        """! @brief 펼쳐진 속성 그룹의 제목을 표시한다."""
        self.rect(x,y,w,34,PANEL,LINE)
        self.icon("down",x+8,y+7,MUTED,18)
        self.text(x+34,y+23,label,15,INK,True,w-45)

    def table(self,x,y,width,headers,rows,widths=None,row_h=39,selected=None):
        """! @brief 실제 표 위젯으로 옮길 수 있는 열과 행을 배치한다."""
        weights=widths or [1]*len(headers)
        cols=[width*v/sum(weights) for v in weights]
        total=38+len(rows)*row_h
        self.rect(x,y,width,total,WHITE,LINE)
        self.rect(x,y,width,38,"#F0F4F9",LINE)
        cursor=x
        for header,w in zip(headers,cols):
            self.text(cursor+12,y+25,header,14,MUTED,True,w-24)
            cursor+=w
        for j,row in enumerate(rows):
            yy=y+38+j*row_h
            if j==selected:self.rect(x+1,yy,width-2,row_h,PALE,"none")
            elif j%2:self.rect(x+1,yy,width-2,row_h,"#FAFBFD","none")
            self.line(x,yy+row_h,x+width,yy+row_h,LINE)
            cursor=x
            for value,w in zip(row,cols):
                color=INK
                if isinstance(value,tuple):value,color=value
                self.text(cursor+12,yy+row_h/2+5,value,14,color,width=w-24)
                cursor+=w
        return y+total

    def save(self,target):
        """! @brief 이미지로 굳히지 않은 SVG와 개별 셀 DrawIO를 기록한다."""
        target=Path(target); target.mkdir(parents=True,exist_ok=True)
        root=ET.Element(f"{{{SVG}}}svg",width=str(self.width),height=str(self.height),
                        viewBox=f"0 0 {self.width} {self.height}",role="img")
        ET.SubElement(root,f"{{{SVG}}}title").text=f"{self.screen_id} {self.title} - 구현 목표 시안"
        ET.SubElement(root,f"{{{SVG}}}desc").text="실제 제품 화면이 아닌 구현 설계. 표시 데이터는 설명용이며 물리 검증 근거가 아니다."
        mx=ET.Element("mxfile",host="app.diagrams.net",type="device")
        diagram=ET.SubElement(mx,"diagram",id=self.screen_id,name=self.title)
        model=ET.SubElement(diagram,"mxGraphModel",page="1",pageScale="1",pageWidth=str(self.width),pageHeight=str(self.height),grid="1",gridSize="8")
        cells=ET.SubElement(model,"root");ET.SubElement(cells,"mxCell",id="0");ET.SubElement(cells,"mxCell",id="1",parent="0")
        for i,item in enumerate(self.items):
            kind=item["kind"];attrs={};style="html=0;whiteSpace=wrap;"
            if kind=="text":
                attrs=dict(x=str(item['x']),y=str(item['y']),fill=item['fill'],
                           attrib={'font-family':"Malgun Gothic, Segoe UI, sans-serif",'font-size':str(item['size']),
                                   'font-weight':"600" if item['bold'] else "400",'text-anchor':{"left":"start","center":"middle","right":"end"}[item['align']]})
                node=ET.SubElement(root,f"{{{SVG}}}text",**attrs);node.text=item['text']
                if item['width'] is not None:node.set('data-max-width',str(item['width']))
                w=item['width'] or max(30,len(item['text'])*item['size']);h=item['size']*1.45
                x=item['x']-(w/2 if item['align']=='center' else w if item['align']=='right' else 0)
                y=item['y']-item['size']
                style+=f"text;strokeColor=none;fillColor=none;align={item['align']};verticalAlign=top;fontFamily=Malgun Gothic;fontSize={item['size']};fontColor={item['fill']};fontStyle={1 if item['bold'] else 0};spacing=0;"
                cell=ET.SubElement(cells,"mxCell",id=f"v{i+2}",value=item['text'],style=style,vertex="1",parent="1")
                ET.SubElement(cell,"mxGeometry",x=str(x),y=str(y),width=str(w),height=str(h),attrib={"as":"geometry"})
                continue
            stroke=item.get('stroke',LINE); fill=item.get('fill','none');sw=item.get('sw',1)
            if kind in ("rect","ellipse"):
                x,y,w,h=(item[v] for v in ('x','y','w','h'))
                if kind=='rect':
                    attrs=dict(x=str(x),y=str(y),width=str(w),height=str(h),rx=str(item.get('radius',0)))
                    style+=f"rounded={1 if item.get('radius') else 0};arcSize=8;"
                else:
                    attrs=dict(cx=str(x+w/2),cy=str(y+h/2),rx=str(w/2),ry=str(h/2));style+='ellipse;'
                node=ET.SubElement(root,f"{{{SVG}}}{kind}",**attrs)
                cell=ET.SubElement(cells,"mxCell",id=f"v{i+2}",style=style+f"fillColor={fill};strokeColor={stroke};strokeWidth={sw};",vertex="1",parent="1")
                ET.SubElement(cell,"mxGeometry",x=str(x),y=str(y),width=str(w),height=str(h),attrib={"as":"geometry"})
            else:
                points=item['points']
                node=ET.SubElement(root,f"{{{SVG}}}{'polygon' if item.get('close') else 'polyline'}",points=" ".join(f"{a:.3f},{b:.3f}" for a,b in points))
                if item.get('close') and fill!='none':
                    left=min(p[0] for p in points);top=min(p[1] for p in points)
                    width=max(p[0] for p in points)-left;height=max(p[1] for p in points)-top
                    stencil=ET.Element('shape',name=f'polygon-{i}',w=str(width),h=str(height),aspect='variable',strokewidth='inherit')
                    foreground=ET.SubElement(stencil,'foreground');shape_path=ET.SubElement(foreground,'path')
                    for j,(px,py) in enumerate(points):ET.SubElement(shape_path,'move' if j==0 else 'line',x=str(px-left),y=str(py-top))
                    ET.SubElement(shape_path,'close');ET.SubElement(foreground,'fillstroke')
                    raw=ET.tostring(stencil,encoding='utf-8')
                    compressor=zlib.compressobj(wbits=-15)
                    encoded=base64.b64encode(compressor.compress(raw)+compressor.flush()).decode('ascii')
                    cell=ET.SubElement(cells,'mxCell',id=f'v{i+2}',style=f'shape=stencil({encoded});fillColor={fill};strokeColor={stroke};strokeWidth={sw};',vertex='1',parent='1')
                    ET.SubElement(cell,'mxGeometry',x=str(left),y=str(top),width=str(width),height=str(height),attrib={'as':'geometry'})
                    node.set('fill',fill);node.set('stroke',stroke);node.set('stroke-width',str(sw))
                    continue
                dash_style=f"dashed=1;dashPattern={item['dash']};" if item.get('dash') else ''
                cell=ET.SubElement(cells,"mxCell",id=f"v{i+2}",style=f"edgeStyle=none;rounded=0;endArrow=none;startArrow=none;strokeColor={stroke};strokeWidth={sw};{dash_style}",edge="1",parent="1")
                geo=ET.SubElement(cell,"mxGeometry",relative="1",attrib={"as":"geometry"})
                for p,role in ((points[0],'sourcePoint'),(points[0] if item.get('close') else points[-1],'targetPoint')):
                    ET.SubElement(geo,"mxPoint",x=str(p[0]),y=str(p[1]),attrib={"as":role})
                arr=ET.SubElement(geo,"Array",attrib={"as":"points"})
                for px,py in points[1:] if item.get('close') else points[1:-1]:ET.SubElement(arr,"mxPoint",x=str(px),y=str(py))
            node.set('fill',fill);node.set('stroke',stroke);node.set('stroke-width',str(sw))
            if item.get('dash'):node.set('stroke-dasharray',str(item['dash']))
        ET.indent(root);ET.indent(mx)
        ET.ElementTree(root).write(target/(self.stem+'.svg'),encoding='utf-8',xml_declaration=True)
        ET.ElementTree(mx).write(target/(self.stem+'.drawio'),encoding='utf-8',xml_declaration=True)


def board2d(s,x,y,w,h,handles=True,dimensions=True):
    """! @brief 명시 기하의 편집 모습을 예시 좌표로 그린다."""
    s.rect(x,y,w,h,"#F9FBFE",LINE)
    for xx in range(int(x+20),int(x+w),24):s.line(xx,y,xx,y+h,"#E6EDF6")
    for yy in range(int(y+20),int(y+h),24):s.line(x,yy,x+w,yy,"#E6EDF6")
    cx,cy=x+w*.5,y+h*.5; r=min(w*.37,h*.42)
    s.ellipse(cx-r,cy-r,2*r,2*r,BOARD,"#678875",1.5)
    ground=[(cx-r*.86,cy+r*.51),(cx+r*.86,cy+r*.51)]+[(cx+r*math.cos(a),cy+r*math.sin(a)) for a in [math.radians(31+i*118/55) for i in range(56)]]
    s.poly(ground,COPPER,"#9E693E",1.2,True)
    pts=[(cx+r*.82*math.cos(math.radians(a)),cy-r*.82*math.sin(math.radians(a))) for a in range(25,156)]
    s.poly(pts,"none","#9F6434",r*.065+2)
    s.poly(pts,"none",COPPER,r*.065)
    s.rect(cx-r*.025,cy,r*.05,r*.52,COPPER,"#9E693E")
    s.ellipse(cx-r*.065,cy-r*.065,r*.13,r*.13,COPPER,"#9E693E",1.2)
    s.ellipse(cx-r*.025,cy-r*.025,r*.05,r*.05,WHITE,"#9E693E")
    s.line(cx-r-28,cy,cx+r+28,cy,"#8597A8",1,"8 4 2 4")
    s.line(cx,cy-r-28,cx,cy+r+28,"#8597A8",1,"8 4 2 4")
    if handles:
        for px,py in (pts[0],pts[-1]):s.rect(px-5,py-5,10,10,BLUE,WHITE,1,1.5)
    if dimensions:
        dx,dy=cx+r*.66,cy-r*.32
        s.line(cx,cy,dx,dy,INK,1.3)
        s.poly([(dx-10,dy+1),(dx,dy),(dx-6,dy+8)],INK,INK,1,True)
        s.rect(cx+30,cy-r*.34-29,122,28,WHITE,LINE,2)
        s.text(cx+91,cy-r*.34-10,"R 20.00 mm",14,INK,width=112,align="center")
    s.text(x+14,y+h-16,"명시 기하 예시 / 전기 연결 미평가",13,MUTED,width=w-28)


def board3d(s,x,y,w,h,section=False,external=False):
    """! @brief OpenGL 표시 mesh로 구현할 수 있는 단순 조명 투영을 그린다."""
    s.rect(x,y,w,h,"#F5F8FC",LINE)
    cx,cy=x+w*.5,y+h*.48;r=min(w*(.31 if external else .35),h*.7)
    def project(px,py,z=0):return (cx+(px-py*.33)*r,cy+(py*.43+px*.12)*r-z)
    def grid_line(start,end):
        """! @brief 미리보기 영역 밖으로 격자가 넘치지 않게 선분을 자른다."""
        ax,ay=start;bx,by=end;dx=bx-ax;dy=by-ay;lo=0;hi=1
        for p,q in ((-dx,ax-x-8),(dx,x+w-8-ax),(-dy,ay-y-8),(dy,y+h-8-ay)):
            if p==0:
                if q<0:return
            elif p<0:lo=max(lo,q/p)
            else:hi=min(hi,q/p)
        if lo<=hi:s.line(ax+lo*dx,ay+lo*dy,ax+hi*dx,ay+hi*dy,"#DFE7F0")
    for a in range(-4,5):
        grid_line(project(-1.3,a/3),project(1.3,a/3))
        grid_line(project(a/3,-1.3),project(a/3,1.3))
    circle=[project(math.cos(a),math.sin(a),0) for a in [i*math.tau/100 for i in range(101)]]
    s.poly([(px,py+15) for px,py in circle],"#91B79C","#688974",1,True)
    s.poly(circle,BOARD,"#688974",1.4,True)
    ground=[project(-.86,.51,1),project(.86,.51,1)]+[project(math.cos(math.radians(a)),math.sin(math.radians(a)),1) for a in range(31,150)]
    s.poly(ground,COPPER,"#9E693E",1,True)
    arc=[project(.82*math.cos(math.radians(a)),-.82*math.sin(math.radians(a)),2) for a in range(25,156)]
    s.poly(arc,"none","#A97546",r*.066+2);s.poly(arc,"none",COPPER,r*.066)
    s.poly([project(-.025,0,2),project(.025,0,2),project(.025,.51,2),project(-.025,.51,2)],COPPER,"#9E693E",1,True)
    p=project(0,0,2);s.ellipse(p[0]-9,p[1]-4,18,8,COPPER,"#9E693E")
    if section:
        pts=[project(-1.2,0,-35),project(1.2,0,-35),project(1.2,0,90),project(-1.2,0,90)]
        s.poly(pts,"none",BLUE,2,True,"7 4")
        s.text(x+20,y+35,"절단평면 지정 / 절단 미리보기 꺼짐",15,BLUE,True,width=w-40)
    if external:
        pts=[project(-1.15,-1.05,-45),project(1.15,-1.05,-45),project(1.15,1.05,-45),project(-1.15,1.05,-45)]
        s.poly(pts,"none","#72869C",2,True,"6 4")
        s.text(x+20,y+35,"외부 케이스 / 표시 포함 / EM 제외",15,MUTED,width=w-40)
    ax,ay=x+55,y+h-60
    for dx,dy,label,color in ((40,10,'X',RED),(-20,27,'Y',GREEN),(0,-40,'Z',BLUE)):
        s.line(ax,ay,ax+dx,ay+dy,color,2);s.text(ax+dx+5,ay+dy,label,13,color)
    s.text(x+w-18,y+h-18,"정투영 / 기하 표시",13,MUTED,width=220,align="right")


def example_gamma(frequency_ghz, variant=0):
    """! @brief 그래프와 표가 함께 사용하는 시안 전용 복소 예시를 반환한다."""
    u=(frequency_ghz-2.2)/.6
    depth=.17+.68*math.exp(-((u-(.43+variant*.09))/.13)**2)
    amplitude=10**(-30*depth/20)
    phase=2.6+2.1*(u-.43)
    return amplitude*complex(math.cos(phase),math.sin(phase))


def plot(s,x,y,w,h,kind="network",compare=False):
    """! @brief 명확히 시안으로 표시한 예시 결과와 축/범례를 그린다."""
    s.rect(x,y,w,h,WHITE,LINE)
    px,py,pw,ph=x+65,y+45,w-95,h-100
    for i in range(6):
        yy=py+ph*i/5;s.line(px,yy,px+pw,yy,"#E3EAF2")
        s.text(px-12,yy+5,str(-i*6 if kind=='network' else 100-i*20),13,MUTED,width=40,align="right")
    for i in range(7):
        xx=px+pw*i/6;s.line(xx,py,xx,py+ph,"#E3EAF2")
        s.text(xx,py+ph+24,f"{2.2+i*.1:.1f}",13,MUTED,width=40,align="center")
    s.text(x+15,y+25,"S11 (dB)" if kind=='network' else "전력 비율 (%)",14,MUTED,width=200)
    s.line(x+155,y+20,x+185,y+20,BLUE,2.5)
    s.text(x+196,y+25,'자료 A',13,INK,width=95)
    if compare:
        s.line(x+310,y+20,x+340,y+20,'#CD702C',2.5,'6 3')
        s.text(x+351,y+25,'자료 B',13,INK,width=95)
    s.text(px+pw,y+h-12,"주파수 (GHz)",13,MUTED,width=180,align="right")
    for n,color in enumerate((BLUE,"#CD702C") if compare else (BLUE,)):
        points=[]
        for i in range(121):
            u=i/120
            val=-20*math.log10(abs(example_gamma(2.2+.6*u,n)))/30 if kind=='network' else .2+.09*math.sin(u*4+n)
            points.append((px+pw*u,py+ph*val))
        s.poly(points,"none",color,2.5,dash='6 3' if n else None)
    mx=px+pw*.43;s.line(mx,py,mx,py+ph,"#8EA2BC",1,"4 4")
    s.rect(mx-5,py+ph*.85-5,10,10,BLUE,WHITE,2)
    s.text(x+w-18,y+24,"시안용 합성 데이터",12,AMBER,width=200,align="right")


def shell(s,active_tree="원호 01",bottom="작업",inspector=True):
    """! @brief wxAuiManager에 대응하는 공통 Studio 작업 프레임을 그린다."""
    s.rect(0,0,1920,1080,BG,"none")
    s.rect(0,0,1920,32,"#F4F7FC",LINE)
    s.rect(12,7,20,20,BLUE,"none",2);s.poly([(15,19),(20,12),(24,23),(29,10)],"none",WHITE,1.5)
    s.text(42,22,"TraceWave Studio  /  원형 안테나",15,INK,True,width=650)
    s.text(1470,21,"화면 설계안  |  예시 프로젝트",12,MUTED,width=310)
    s.line(1797,16,1811,16,MUTED);s.rect(1844,10,12,12,"none",MUTED)
    s.icon("close",1880,7,MUTED,18)
    s.rect(0,32,1920,30,WHITE,LINE)
    for x,label in ((18,"파일(F)"),(99,"편집(E)"),(182,"보기(V)"),(266,"설계(D)"),(351,"도구(T)"),(437,"창(W)"),(514,"도움말(H)")):
        s.text(x,53,label,14,INK,width=83)
    s.rect(0,62,1920,52,"#F5F8FC",LINE)
    s.button(14,71,92,"저장",icon="save")
    s.button(118,71,146,"실행 전 확인",icon="play")
    s.button(276,71,120,"STEP 출력",icon="cube")
    for i,label in enumerate(("설계","해석","결과","비교","출력")):
        x=438+i*94;active=label==s.workspace
        s.rect(x,71,86,34,BLUE if active else "#EAF0F7","none",3)
        s.text(x+43,94,label,16,WHITE if active else MUTED,active,70,"center")
    s.icon("search",1638,79,MUTED,18);s.text(1666,94,"명령 찾기",14,MUTED,width=105)
    s.text(1884,94,"저장됨",14,GREEN,width=100,align="right")
    s.rect(8,122,280,922,WHITE,LINE)
    s.rect(8,122,280,34,"#EAF0F7",LINE)
    s.text(22,145,"프로젝트",15,INK,True,width=200)
    s.text(265,145,"...",18,MUTED,width=25,align="right")
    s.rect(20,167,256,32,PANEL,LINE,3);s.icon("search",30,174,MUTED,18)
    s.text(57,189,"객체 찾기",14,MUTED,width=200)
    s.icon("folder",24,217,BLUE);s.text(52,233,"원형 안테나",16,INK,True,width=213)
    nodes=[("target","설계 목표",0),("layers","기판 / 적층",0),("folder","패턴",0),("arc","원호 01",1),("line","급전선",1),("layers","접지면",1),("port","급전",0),("layers","재료",0),("cube","외부 환경",0),("doc","실행 / 결과",0)]
    for i,(ico,label,depth) in enumerate(nodes):
        yy=252+i*38
        if label==active_tree:s.rect(16,yy,264,34,PALE,"none",3)
        s.icon(ico,36+depth*19,yy+7,BLUE if label==active_tree else MUTED,19)
        s.text(64+depth*19,yy+24,label,15,INK,label==active_tree,202-depth*19)
    s.line(8,715,288,715,LINE)
    s.text(22,742,"레이어",15,INK,True,width=160)
    s.text(267,742,"2D 표시",12,MUTED,width=82,align="right")
    for i,(label,color) in enumerate((("상단 동박",COPPER),("기판",BOARD),("하단 동박",COPPER))):
        yy=761+i*38
        if i==0:s.rect(16,yy,264,34,PALE,"none",3)
        s.check(28,yy+9,"",True,25);s.rect(58,yy+9,23,16,color,"#93A2B2",2)
        s.text(94,yy+24,label,15,INK,width=160)
    s.text(22,908,"활성 층: 상단 동박",14,BLUE,width=245)
    s.text(22,937,"표시 여부와 해석 포함은 별도",13,MUTED,width=246)
    if inspector:
        s.rect(1570,122,342,922,WHITE,LINE)
        s.rect(1570,122,342,34,"#EAF0F7",LINE)
        s.text(1584,145,"속성",15,INK,True,width=230)
        s.text(1895,145,"...",18,MUTED,width=25,align="right")
    s.rect(296,852,1266,192,WHITE,LINE)
    s.tabs(296,852,1266,["문제","작업","로그"],["문제","작업","로그"].index(bottom))
    if bottom=="작업":
        s.table(308,904,1242,["작업","입력 개정","상태","다음 동작"],[("형상 생성","개정 12",("완료",GREEN),"3D 보기"),("해석 준비","개정 12",("입력 확인 필요",AMBER),"누락 입력 보기")],[4,2,3,3],row_h=40)
    elif bottom=="문제":
        s.table(308,904,1242,["분류","대상","내용","해결"],[("미평가","급전","기대 연결이 지정되지 않았습니다","연결 설정"),("미정","제작 조건","납품 물성과 실장 조건이 미정입니다","출처 확인")],[2,2,6,2],row_h=40)
    else:
        s.table(308,904,1242,["시각","범위","메시지"],[("14:32:08","프로젝트","개정 12를 저장했습니다."),("14:32:10","CAD","형상 생성이 끝났습니다. 독립 검수는 대기입니다.")],[2,2,8],row_h=40)
    s.rect(0,1052,1920,28,"#F1F5FA",LINE)
    s.text(16,1071,"설계 예시 / 실제 제작·해석 검증 자료 아님",12,MUTED,width=660)
    s.text(1125,1071,"mm    |    상단 동박    |    스냅 켜짐",13,MUTED,width=400)
    s.text(1540,1071,"서비스 준비  |  CAD 준비  |  해석 확인 필요",12,MUTED,width=365)


def inspector(s,title="원호 01",fields=None,source=True):
    """! @brief 좁은 속성 패널을 기본값과 근거 그룹으로 나눈다."""
    s.icon("arc",1588,175,BLUE,24);s.text(1624,195,title,18,INK,True,width=266)
    s.section(1582,216,318,"형상")
    values=fields or [("반지름","20.00","mm"),("선폭","1.20","mm"),("시작각","25.0","deg"),("끝각","155.0","deg")]
    for i,(label,value,unit) in enumerate(values):
        yy=266+i*55;s.text(1594,yy+21,label,14,MUTED,width=105)
        s.rect(1712,yy,131,32,WHITE,LINE,2);s.text(1722,yy+22,value,15,INK,width=113)
        s.text(1853,yy+22,unit,13,MUTED,width=44)
    yy=280+len(values)*55
    s.section(1582,yy,318,"기판 / 재료")
    s.text(1594,yy+63,"재료",14,MUTED,width=85);s.text(1712,yy+63,"RO4350B",15,INK,width=170)
    s.notice(1582,yy+81,318,"탐색용 근사",'warn')
    s.text(1594,yy+154,"제작 / 측정 조건",14,MUTED,width=185)
    s.text(1884,yy+154,"미정",14,AMBER,True,width=60,align="right")
    s.section(1582,yy+180,318,"출처와 가정")
    s.text(1594,yy+240,"직접 입력 / 명시 기하",14,INK,width=286)
    s.text(1594,yy+269,"초기 추정과 성능 검증은 별도",13,MUTED,width=286)
    s.button(1582,954,150,"되돌리기",disabled=True)
    s.button(1742,954,158,"적용",primary=True,disabled=True)
    s.text(1594,1018,"입력을 바꾸면 적용할 수 있습니다",13,MUTED,width=286)


def dialog(s,title,subtitle="",tabs=None,active=0,width=1344,height=820):
    """! @brief native wxDialog 크기의 독립 설정 창과 하단 명령을 그린다."""
    shell(s);inspector(s)
    s.rect(0,114,1920,938,"#E0E5EC","none")
    x=(1920-width)/2;y=(1080-height)/2
    s.rect(x+7,y+8,width,height,"#CDD5E0","none",5)
    s.rect(x,y,width,height,WHITE,"#9EADC0",4)
    s.rect(x,y,width,44,"#F1F5FA",LINE)
    s.text(x+20,y+29,title,18,INK,True,width-90)
    s.icon("close",x+width-35,y+12,MUTED,20)
    if subtitle:s.text(x+24,y+77,subtitle,15,MUTED,width=width-48)
    if tabs:s.tabs(x+16,y+96,width-32,tabs,active)
    s.line(x,y+height-74,x+width,y+height-74,LINE)
    s.text(x+24,y+height-29,"미적용 입력 / 저장 전 검토",14,MUTED,width=width-440)
    s.button(x+width-378,y+height-54,112,"되돌리기")
    s.button(x+width-254,y+height-54,112,"닫기")
    s.button(x+width-130,y+height-54,106,"적용",True)
    return x+28,y+160,width-56,height-250
