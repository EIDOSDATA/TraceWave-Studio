"""! @brief 공통 작업 공간과 설계, 해석, 결과, 출력의 상세 구현 시안을 정의한다."""

import math

from .primitives import (
    Screen, WHITE, BG, PANEL, LINE, INK, MUTED, BLUE, PALE, GREEN, AMBER,
    RED, COPPER, BOARD, shell, inspector, dialog, board2d, board3d, plot, example_gamma,
)


def page(stem, identity, title, workspace="설계", ui=None, bottom="작업"):
    """! @brief 전체 화면을 공통 프레임으로 시작한다."""
    s=Screen(stem,identity,title,workspace,ui)
    shell(s,active_tree="실행 / 결과" if workspace in ("결과","비교") else "원호 01",bottom=bottom)
    return s


def side(s,title,sections):
    """! @brief 작업 문맥에 맞는 읽기 전용 속성과 근거를 배치한다."""
    s.text(1588,191,title,20,INK,True,width=300)
    y=216
    for heading,rows in sections:
        s.section(1582,y,318,heading);y+=58
        for label,value in rows:
            s.text(1594,y,label,14,MUTED,width=285);y+=25
            s.text(1594,y,value,15,AMBER if '미정' in value or '미평가' in value else INK,width=285);y+=39
        y+=7
    return y


def central(s,title,subtitle=None,tabs=None,active=0):
    """! @brief 중앙 문서의 제목과 하위 탭을 그린다."""
    s.rect(296,122,1266,722,WHITE,LINE)
    if tabs:s.tabs(296,122,1266,tabs,active)
    s.heading(320,201 if tabs else 163,title,subtitle,width=1210)
    return 320,260 if subtitle else 226,1218


def design(endpoint=False):
    """! @brief 2D 도구, 캔버스, 속성이 연결된 정밀 편집 시안을 만든다."""
    s=page("05_끝점과_스냅" if endpoint else "04_이차원_설계","S11.endpoint" if endpoint else "S11","스냅과 끝점 편집" if endpoint else "2D 설계",ui=['UI-01','UI-05'])
    s.tabs(296,122,1266,["2D 편집","3D 형상"],0)
    s.rect(296,164,1266,52,PANEL,LINE)
    for x,w,label,ico in ((308,84,"선택","select"),(402,76,"선","line"),(488,88,"원호","arc"),(588,118,"좌표 입력","target"),(718,124,"전체 보기","fit")):
        s.button(x,173,w,label,primary=label=="선택",icon=ico)
    s.check(876,182,"스냅",True,100)
    s.text(985,196,"끝점 + 격자",14,MUTED,width=150)
    s.button(1294,173,110,"mm",icon="down");s.button(1416,173,130,"100%",icon="down")
    board2d(s,296,216,1266,628)
    inspector(s)
    if endpoint:
        s.notice(320,236,580,"끝점 이동 / X, Y 좌표를 입력하거나 점을 선택")
        s.rect(1115,607,413,196,WHITE,LINE,4)
        s.text(1135,637,"끝점 2",17,INK,True,width=350)
        s.field(1135,651,174,"X","-18.126","mm")
        s.field(1328,651,174,"Y","8.452","mm")
        s.text(1135,744,"끝점에 스냅됨 / 연결 판정은 별도",13,MUTED,width=370)
        s.text(1135,778,"Enter 확정    Esc 취소",14,BLUE,width=370)
    else:
        s.rect(1254,590,282,222,WHITE,LINE,4)
        s.text(1268,615,"3D 미리보기",14,INK,True,width=230)
        board3d(s,1265,628,260,170)
    s.notes=["선택/트리/속성은 안정 ID로 연동한다. 도구와 좌표 값은 표시 상태 모델이 관리한다.","드래그는 미리보기이며 Enter/확정 때 서비스 원자 명령 하나를 요청한다. Esc는 작업 취소가 아닌 현재 제스처 취소다."]
    return s


def startup():
    """! @brief 시작 화면과 생성/복구의 서로 다른 선택을 시각화한다."""
    s=Screen('01_시작과_프로젝트','S00','시작과 프로젝트',ui=['UI-02','UI-23'])
    shell(s);s.rect(8,122,1904,922,WHITE,LINE)
    s.rect(8,122,328,922,"#F1F6FD",LINE)
    s.rect(44,166,44,44,BLUE,"none",6);s.poly([(52,195),(62,177),(70,202),(80,174)],"none",WHITE,2.5)
    s.text(104,195,"TraceWave Studio",23,INK,True,width=224)
    s.text(44,246,"안테나 설계 작업 공간",16,MUTED,width=265)
    s.button(44,304,252,"새 프로젝트",True,'plus',h=42)
    s.button(44,360,252,"프로젝트 열기",icon='folder',h=42)
    s.button(44,416,252,"복구 후보 확인",icon='doc',h=42)
    s.section(36,740,264,"실행 환경")
    for yy,label,status in ((805,'프로젝트 서비스','준비'),(852,'CAD worker','준비'),(899,'WSL2 해석 환경','확인 필요')):
        s.text(48,yy,label,14,MUTED,width=180);s.text(48,yy+23,status,14,GREEN if status=='준비' else AMBER,width=220)
    s.button(44,976,252,"환경 진단 열기",icon='gear')
    s.heading(388,202,"최근 프로젝트","파일을 선택하면 마지막 저장 상태를 확인할 수 있습니다.",width=1400)
    s.rect(388,270,1464,40,PANEL,LINE,3);s.icon('search',403,280,MUTED);s.text(438,297,'프로젝트 이름 또는 경로 검색',15,MUTED,width=1320)
    s.table(388,335,1464,['프로젝트','위치','마지막 저장','상태'],[
        ('원형 안테나','projects/circular-demo','2026-11-16 14:32',('정상',GREEN)),
        ('IFA 치수 검토','projects/ifa-review','2026-11-15 17:40',('정상',GREEN)),
        ('문헌 후보 비교','projects/literature-study','2026-11-14 09:10',('경로 확인 필요',AMBER)),
    ],[3,5,3,2],row_h=62,selected=0)
    s.heading(388,657,'선택한 프로젝트',width=1000)
    s.text(388,700,'원형 안테나  /  개정 12  /  저장됨',18,INK,True,width=1200)
    s.text(388,735,'명시 기하와 출처를 보존한 설계입니다. 제작 및 측정 조건은 미정입니다.',16,MUTED,width=1400)
    s.button(388,778,180,'프로젝트 열기',True,'folder',h=40)
    s.button(584,778,168,'경로 다시 지정',icon='folder',h=40)
    s.notice(388,902,1464,'CAD 또는 해석 환경을 준비하지 않아도 설계 입력과 저장을 시작할 수 있습니다.')
    s.notes=['최근 항목의 선택은 파일 변경을 일으키지 않는다. 열기 실패 시 기존 프로젝트를 유지한다.','시작 화면과 환경 진단은 UI-02/UI-23의 진입점이다.']
    return s


def create_project():
    """! @brief 실제 값이 없는 새 프로젝트를 안전하게 시작하도록 그린다."""
    s=Screen('02_새_프로젝트','S00.new','새 프로젝트',ui=['UI-02'])
    x,y,w,h=dialog(s,'새 프로젝트','새 설계의 이름과 저장 위치를 선택합니다.',width=1080,height=760)
    s.field(x,y,620,'프로젝트 이름','원형 안테나')
    s.field(x,y+92,620,'저장 위치','projects/circular-demo')
    s.button(x+640,y+120,160,'폴더 선택',icon='folder')
    s.field(x,y+184,280,'표시 길이 단위','mm')
    s.field(x+310,y+184,310,'시작 방식','빈 설계')
    s.notice(x,y+292,w,'주파수와 물성은 자동으로 채우지 않습니다.','info','목표, 기판, 형상은 프로젝트를 만든 뒤 각각 입력합니다.')
    s.text(x,y+412,'다른 프로젝트에서 가져오기는 원본을 유지한 별도 복사로 수행합니다.',15,MUTED,width=w)
    s.rect(421,847,1078,72,WHITE,'none');s.text(444,891,'물성 / 주파수의 미정 상태를 유지합니다.',14,MUTED,width=660)
    s.button(1152,866,112,'취소');s.button(1276,866,190,'프로젝트 만들기',True)
    s.notes=['프로젝트 생성은 이름/위치/표시 선호만 확정하며 물리값이나 RF 성능을 추정하지 않는다.']
    return s


def recovery():
    """! @brief 저장본과 복구 후보의 차이를 선택 전에 보여준다."""
    s=Screen('03_저장본과_복구','S00.recovery','저장본과 복구 후보',ui=['UI-02'])
    x,y,w,h=dialog(s,'복구 후보 검토','원형 안테나 / 저장본과 복구 후보의 차이를 확인합니다.')
    s.table(x,y,w,['항목','정상 저장본','복구 후보'],[('저장 시각','2026-11-16 14:32','2026-11-16 14:41'),('입력 개정','개정 12','개정 14'),('원호 01 반지름','20.00 mm','20.50 mm'),('현재 작업','없음','종료 상태 확인 필요'),('제작 / 측정 조건','미정','미정')],[3,4,4],row_h=48)
    s.notice(x,y+320,w,'복구 후보가 최신 정답이라는 뜻은 아닙니다.','warn','원래 저장본을 유지하고 선택한 후보를 새 복구본으로 엽니다.')
    s.text(x,y+438,'원본 저장본과 출처 사본은 항상 유지합니다.',15,GREEN,width=w)
    s.rect(289,877,1342,72,WHITE,'none');s.text(312,921,'원본을 유지하고 선택한 저장 상태를 엽니다.',14,MUTED,width=780)
    s.button(1157,896,126,'취소');s.button(1295,896,140,'원본 열기');s.button(1447,896,155,'복구본 열기',True)
    s.notes=['복구는 원본과 후보를 비교한 명시 선택이다. 작업 상태를 추측하여 재실행하지 않는다.']
    return s


def model(section=False):
    """! @brief CAD 보기와 표시 단면을 독립된 화면으로 그린다."""
    s=page('07_삼차원_단면' if section else '06_삼차원_형상','S12.section' if section else 'S12','3D 단면' if section else '3D 형상',ui=['UI-06','UI-07','UI-11'])
    s.tabs(296,122,1266,['2D 편집','3D 형상'],1)
    s.rect(296,164,1266,52,PANEL,LINE)
    for xx,ww,label,ico in ((309,126,'3D 갱신','cube'),(447,126,'전체 보기','fit'),(585,120,'선택 맞춤','target'),(717,110,'단면','layers')):
        s.button(xx,173,ww,label,primary=section and label=='단면',icon=ico)
    s.text(1080,196,'표시 개정 12  /  현재 개정 12',14,GREEN,width=460)
    board3d(s,296,216,1266,628,section)
    side(s,'기판 조립체',[
        ('표시 상태',[('입력','개정 12 / 현재와 일치'),('보기','정투영 / 선택 바디 1개')]),
        ('포함 범위',[('CAD 표시','기판 + 동박'),('외부 물체','없음')]),
        ('검증 상태',[('STEP 생성','생성됨 / 독립 검수 전'),('제작 / 측정','미정')]),
    ])
    if section:
        s.rect(320,684,660,132,WHITE,LINE,4)
        s.text(340,715,'절단평면 A-A 지정',17,INK,True,width=620)
        s.text(340,746,'평면: XZ    오프셋: 0.00 mm',15,INK,width=620)
        s.check(340,765,'절단 미리보기',False,200)
        s.text(560,780,'보기 설정 / 원본 형상 유지',14,MUTED,width=390)
    s.notes=['OCCT worker의 표시 mesh를 wxGLCanvas에 표시한다. CAD 화면은 3D 방사 결과와 다르다.','현재 설계와 표시 개정이 다르면 이전 입력 표시를 유지하고 갱신 명령을 제공한다.']
    return s


def preflight():
    """! @brief 실행하기 전에 소비 입력과 차단 사유를 확인하는 화면을 만든다."""
    s=page('30_해석_실행전검토','S20','해석 실행 전 검토','해석',['UI-12'])
    central(s,'실행 전 검토','개정 12의 입력과 지원 범위를 확인합니다. 검사만으로 계산을 시작하지 않습니다.',['입력 검사','해석 조건','메시 / 자원','연구'])
    s.table(320,278,1218,['검사 항목','사용 상태','입력 / 이유','동작'],[
        ('기하와 층',('사용 가능',GREEN),'기판 1개 / 도체 3개','설계 보기'),
        ('급전',('확인 필요',AMBER),'신호 / 기준 도체의 기대 연결 미평가','포트 편집'),
        ('재료 모델',('탐색 근사',AMBER),'RO4350B 관측값 / 납품 물성 미정','근거 확인'),
        ('외부 환경','제외','외부 EM 물체 없음','환경 열기'),
        ('해석 조건',('미정',AMBER),'주파수 / 격자 / 종료 조건 필요','조건 입력'),
        ('출력과 예산','설정 필요','저장할 필드 및 실행 예산 검토','예산 검토'),
    ],[2.5,2,5,1.7],row_h=54)
    s.notice(320,676,1218,'실행할 수 없습니다. 필수 입력과 실행 예산을 확인하세요.','warn','목표를 저장해도 해석 설정은 자동으로 변경되지 않습니다.')
    s.button(320,775,150,'현재 입력 검사',icon='check')
    s.button(486,775,180,'해석 조건 입력',True,'gear')
    s.button(1370,775,168,'해석 시작',icon='play',disabled=True)
    side(s,'실행 입력', [('원본',[('프로젝트','원형 안테나'),('입력 개정','개정 12')]),('사용 범위',[('모델','PCB 패턴 / 단일 포트'),('실행 환경','WSL2 / 확인 필요')]),('상태',[('제작과 실측','미정 / 미검증')])])
    s.notes=['명시적 실행에만 snapshot을 고정한다. 입력 검사와 설정 변경은 실행과 분리한다.','차단 항목에서 해당 입력으로 이동하며 사용자가 의도하지 않은 물성 채택은 하지 않는다.']
    return s


def solver_settings():
    """! @brief 해석 설정의 저장과 실행 버튼을 분리한다."""
    s=Screen('31_해석_조건','D20','해석 조건','해석',['UI-12','UI-13'])
    x,y,w,h=dialog(s,'해석 조건','프로젝트 개정 12 / 조건을 적용한 뒤 실행 전 검토로 돌아갑니다.',tabs=['주파수','격자 / 경계','종료 / 출력'])
    s.field(x,y,354,'시작 주파수','미정','GHz')
    s.field(x+386,y,354,'끝 주파수','미정','GHz')
    s.field(x+772,y,354,'결과 표본 수','미정')
    s.notice(x,y+108,w,'선택한 목표에서 대역을 가져올 수 있습니다.','info','목표 원문은 유지하고, 바뀔 설정만 검토한 뒤 채택합니다.')
    s.button(x+944,y+126,312,'목표 대역 변경안 보기',icon='target')
    s.section(x,y+216,w,'격자와 실행 예산')
    for i,(name,unit) in enumerate((('최대 셀 크기','mm'),('공기 여유','mm'),('시간 단계 상한',''))):s.field(x+i*386,y+266,354,name,'미정',unit)
    s.check(x,y+374,'방사 후처리 자료 기록',False,600)
    s.check(x+644,y+374,'전계 / 자계 자료 기록',False,600)
    s.notice(x,y+429,w,'출력 기록은 저장 공간과 후처리 비용에 영향을 줍니다.','warn')
    s.notes=['목표 대역 채택은 명시적 변경 검토다. 설정 적용 후 S20으로 복귀하며 자동 실행하지 않는다.']
    return s


def mesh():
    """! @brief 메시의 공간 배치와 자원 예상 범위를 같은 화면에 둔다."""
    s=page('32_메시와_자원검토','S20.mesh','메시와 자원 검토','해석',['UI-13'])
    central(s,'메시와 자원','기하 표시에 격자선을 겹쳐 보고, 실행 전에 예산을 확인합니다.',['입력 검사','해석 조건','메시 / 자원','연구'],2)
    board2d(s,320,268,805,518,False,False)
    for xx in range(340,1120,28):s.line(xx,268,xx,786,'#879DB9',.7)
    for yy in range(284,786,28):s.line(320,yy,1125,yy,'#879DB9',.7)
    s.section(1145,268,393,'국부 특징')
    for i,(label,text) in enumerate((('원호 선폭','1.20 mm / 명시 기하'),('급전 간극','미정 / 입력 확인'),('최소 두께','적층 조건에서 확인'),('셀 수 / 메모리','준비 계산 후 표시'))):
        s.text(1160,330+i*94,label,14,MUTED,width=360);s.text(1160,357+i*94,text,15,INK,width=360)
    side(s,'메시 검토',[('표시',[('입력 개정','개정 12'),('보기','XY 평면 / 예시 격자')]),('자원',[('예상치','준비 단계 계산 전'),('실측치','실행하지 않음')]),('검증',[('수렴','미평가')])])
    s.notes=['격자 그림은 배치 예시다. 셀 수/메모리를 실제 준비 결과 없이 확정하지 않는다.','예상 자원과 실제 실행 실측을 별도 항목으로 표시한다.']
    return s


def results_base(stem,identity,title,active=0):
    """! @brief 동일한 원본 선택 바를 결과의 모든 상세 보기에 적용한다."""
    s=page(stem,identity,title,'결과',['UI-15'] if active<4 else ['UI-16'])
    central(s,title,None,['네트워크','Smith','전력 / 손실','목표 평가','방사','필드','고급 분석'],active)
    s.text(320,236,'실행: 설명용 결과 A   |   입력 개정 12   |   원본 데이터',14,MUTED,width=920)
    s.button(1335,210,200,'다른 결과 선택',icon='folder')
    side(s,'결과 조건',[('원본',[('자료','설명용 합성 결과 A'),('입력 개정','개정 12')]),('기준',[('포트 / Z0','급전 01 / 50 ohm'),('기준면','포트 단자 / 시안 예시')]),('검증 상태',[('수치 / 물리','미평가 / 미확립'),('제작 / 측정','미정 / 미검증')])])
    s.notes=['곡선/수치는 시안 전용 합성 데이터이며 실제 해석 또는 합격 증거가 아니다.','자료의 원본/변환/입력 개정과 포트/Z0/기준면을 같은 작업 공간에서 확인한다.']
    return s


def network():
    """! @brief 네트워크 곡선과 수치 표를 함께 보여준다."""
    s=results_base('37_네트워크_결과','S30.network','네트워크 결과')
    plot(s,320,266,1218,350)
    rows=[]
    for name,f in [('M1',2.458),('M2',2.600)]:
        g=example_gamma(f)
        rows.append((name,f'{f:.3f}',f'{20*math.log10(abs(g)):.2f}',f'{g.real:+.4f} / {g.imag:+.4f}','합성 예시'))
    s.table(320,638,1218,['마커','주파수 (GHz)','S11 (dB)','실수 / 허수','자료'],rows,[1,2,2,3,2],row_h=43)
    s.button(320,787,146,'마커 추가',icon='plus');s.button(478,787,168,'값 표 내보내기',icon='doc')
    return s


def smith():
    """! @brief 복소 데이터와 정규화 조건이 보이는 Smith 표시를 그린다."""
    s=results_base('38_스미스_차트','S30.smith','Smith 차트',1)
    s.rect(320,266,820,542,WHITE,LINE)
    cx,cy,r=730,535,225
    s.ellipse(cx-r,cy-r,2*r,2*r,WHITE,'#8FA2B8',1.2)
    s.line(cx-r,cy,cx+r,cy,'#C0CEDC')
    for resistance in (.2,.5,1,2,5):
        rr=r/(1+resistance);cc=cx+r*resistance/(1+resistance)
        s.ellipse(cc-rr,cy-rr,2*rr,2*rr,'none','#D2DDE8',1)
    for reactance in (.2,.5,1,2,5):
        for sign in (-1,1):
            points=[]
            for i in range(100):
                real=i*.16;z=complex(real,sign*reactance);g=(z-1)/(z+1)
                points.append((cx+r*g.real,cy-r*g.imag))
            s.poly(points,'none','#D2DDE8',1)
    pts=[]
    for i in range(121):
        g=example_gamma(2.2+i*.005)
        pts.append((cx+r*g.real,cy-r*g.imag))
    s.poly(pts,'none',BLUE,2.7)
    marker=example_gamma(2.458);impedance=50*(1+marker)/(1-marker)
    mx,my=cx+r*marker.real,cy-r*marker.imag
    s.ellipse(mx-5,my-5,10,10,BLUE,WHITE,1.5);s.text(mx+12,my-8,'M1',14,BLUE,True,width=48)
    s.text(340,292,'정규화 임피던스 / Z0 = 50 ohm',14,MUTED,width=710)
    s.text(340,786,'설명용 합성 궤적 / 실제 RF 결과 아님',13,AMBER,width=710)
    s.table(1160,266,378,['항목','선택 값'],[('마커','M1'),('주파수','2.458 GHz'),('저항',f'{impedance.real:.2f} ohm'),('리액턴스',f'{impedance.imag:+.2f} ohm'),('자료','합성 예시')],[1,1.4],row_h=52)
    s.notice(1160,618,378,'Z0 변경은 파생 변환입니다.','info','원본 자료를 유지합니다.')
    return s


def power():
    """! @brief 전력 수지와 개별 손실 정확도의 구분을 표시한다."""
    s=results_base('39_전력과_손실','S30.power','전력과 손실',2)
    reflected=abs(example_gamma(2.458))**2
    radiated=1-reflected-.080-.090-.010
    s.table(320,270,1218,['전력 성분','예시 값 (W)','기록 / 범위','독립 정확도'],[
        ('입사 전력','1.000000','포트 기준','미검증'),('반사 전력',f'{reflected:.6f}','동일 합성 S11에서 계산','미검증'),('방사 전력',f'{radiated:.6f}','합성 예시 / 실제 NF2FF 아님','미검증'),('도체 손실','0.080000','방사 / 급전 도체 구분','미확립'),('유전체 손실','0.090000','재료 모델 의존','미확립'),('전력 잔차','0.010000','총 수지 잔차','개별 손실 합격 아님'),
    ],[3,2,4,3],row_h=51)
    s.notice(320,650,1218,'총 전력 수지가 닫혀도 개별 손실의 물리 정확도는 별도입니다.','warn','RO4350B 국부 도체 손실과 GHz PTH의 기존 미확립 상태를 유지합니다.')
    s.text(320,778,'관측 주파수 2.458 GHz / 값 표는 전력 성분 배치 설명용 합성 데이터입니다.',14,AMBER,width=1218)
    return s


def targets():
    """! @brief 목표의 원래 개정과 미평가 이유가 보이는 판정표를 그린다."""
    s=results_base('40_목표_평가','S30.targets','목표 평가',3)
    s.notice(320,270,1218,'목표 개정과 결과 입력이 일치하는지 먼저 확인합니다.')
    s.table(320,340,1218,['목표 / 지표','기준','평가 범위','상태','이유'],[
        ('설계 목표 01 / 반사','사용자 한계','선택 대역','미평가','실제 결과 미연결'),
        ('설계 목표 01 / 효율','미정','선택 대역','미평가','판정 기준 없음'),
        ('설계 목표 01 / 이득','미정','관측 방향 미정','미평가','방향 / 편파 필요'),
        ('대역별 표본 충분성','목표 표본','현재 결과','미평가','원본 표본 검토 필요'),
    ],[3.6,2,2.6,1.3,3.5],row_h=65)
    s.button(320,690,170,'목표 원문 보기',icon='target');s.button(506,690,206,'다른 목표로 재평가',disabled=True)
    s.text(320,780,'재평가는 새 판정 기록을 만들며 과거 목표와 결과를 덮어쓰지 않습니다.',15,MUTED,width=1218)
    return s


def radiation(three=False):
    """! @brief 2D 방사 절단면과 3D 방사 mesh를 별도 화면으로 그린다."""
    s=results_base('42_삼차원_방사' if three else '41_방사_절단면','S30.radiation3d' if three else 'D22','3D 방사 패턴' if three else '방사 절단면',4)
    s.tabs(320,266,1218,['2D 절단면','3D 패턴','편파 / 수치 표'],1 if three else 0)
    s.rect(320,320,836,488,'#F9FBFE',LINE)
    cx,cy=738,565
    if not three:
        for rr in (45,90,135,180):s.ellipse(cx-rr,cy-rr,rr*2,rr*2,'none','#C5D3E2')
        s.text(340,346,'정규화 진폭 / 선형 0..1',13,MUTED,width=310)
        s.line(776,340,806,340,BLUE,2.5);s.text(816,346,'Phi 0 deg',13,INK,width=140)
        s.line(960,340,990,340,'#C57737',2.5,'6 3');s.text(1000,346,'Phi 90 deg',13,INK,width=145)
        for rr in (45,90,135,180):s.text(cx+8,cy-rr+15,f'{rr/180:.2f}',11,MUTED,width=55)
        for angle in range(0,360,30):
            a=math.radians(angle);s.line(cx,cy,cx+180*math.sin(a),cy-180*math.cos(a),'#D4DFEA')
            s.text(cx+205*math.sin(a),cy-205*math.cos(a)+5,str(angle),12,MUTED,width=40,align='center')
        for n,color in enumerate((BLUE,'#C57737')):
            pts=[]
            for angle in range(361):
                a=math.radians(angle);rr=65+105*abs(math.sin(a+n*.2))**.7
                pts.append((cx+rr*math.sin(a),cy-rr*math.cos(a)))
            s.poly(pts,'none',color,2.5,dash='6 3' if n else None)
    else:
        for v in range(25):
            phi=v*math.pi/24
            points=[]
            for u in range(61):
                a=u*math.tau/60;radius=220*max(.07,math.sin(phi))
                xx=radius*math.cos(a)*math.sin(phi);yy=radius*math.sin(a)*math.sin(phi);zz=radius*math.cos(phi)
                points.append((cx+xx-yy*.25,cy+yy*.35-zz))
            normalized=math.sin(phi)
            color=f'#{int(65+165*normalized):02x}{int(130+40*(1-normalized)):02x}{int(195-130*normalized):02x}'
            s.poly(points,'none',color,1.7)
        for u in range(0,60,5):
            a=u*math.tau/60;points=[]
            for v in range(49):
                phi=v*math.pi/48;rr=220*max(.07,math.sin(phi));xx=rr*math.cos(a)*math.sin(phi);yy=rr*math.sin(a)*math.sin(phi);zz=rr*math.cos(phi)
                points.append((cx+xx-yy*.25,cy+yy*.35-zz))
            s.poly(points,'none','#4E8C9A',1)
        s.text(340,350,'정규화 패턴 / 합성 예시',15,MUTED,width=700)
        ax,ay=380,730
        for dx,dy,label,color in ((46,12,'X',RED),(-24,24,'Y',GREEN),(0,-42,'Z',BLUE)):
            s.line(ax,ay,ax+dx,ay+dy,color,2);s.text(ax+dx+6,ay+dy+3,label,13,color,width=25)
        s.text(1178,719,'반경 / 색: 정규화 진폭 (선형)',13,MUTED,width=336)
        for i in range(12):
            n=i/11;color=f'#{int(65+165*n):02x}{int(130+40*(1-n)):02x}{int(195-130*n):02x}'
            s.rect(1178+i*27,735,27,18,color,'none')
        s.text(1178,778,'0',13,MUTED,width=40);s.text(1502,778,'1',13,MUTED,width=40,align='right')
    s.field(1178,324,336,'기록 주파수','2.458','GHz')
    s.choice(1178,414,336,'관측량','정규화 총 패턴')
    s.choice(1178,504,336,'보기 / 정규화' if three else '절단 평면','정투영 / 최댓값 1' if three else 'Phi = 0 deg')
    s.notice(1178,618,336,'시안용 합성 패턴','warn','실제 NF2FF 결과가 아닙니다.')
    s.text(340,788,'기하 CAD 보기와 다른 결과 자료입니다.',13,MUTED,width=770)
    s.notes.append('방사 view는 실제 기록 주파수/관측량/편파를 사용한다. 없는 자료를 보간하여 만든 척 표시하지 않는다.')
    return s


def field_view():
    """! @brief 공간 필드의 색 범례와 기록 조건을 표시한다."""
    s=results_base('43_필드_단면','S30.field','필드 단면',5)
    s.rect(320,266,870,542,'#F3F7FB',LINE)
    for iy in range(20):
        for ix in range(32):
            d=math.hypot((ix-15.5)/15.5,(iy-9.5)/10);v=max(0,1-d)
            color=f'#{int(226-165*v):02x}{int(237-95*v):02x}{int(248-30*v):02x}'
            s.rect(345+ix*25,290+iy*24,25,24,color,'none')
    s.ellipse(590,420,270,180,'none',WHITE,1.7)
    s.text(340,791,'X: -40..40 mm   /   Y: -24..24 mm   /   시안용 합성 분포',13,AMBER,width=810)
    s.text(346,283,'+Y',12,MUTED,width=40)
    s.text(1148,763,'+X',12,MUTED,width=40,align='right')
    s.field(1214,280,300,'관측량','|E| 상대값')
    s.field(1214,376,300,'주파수','2.458','GHz')
    s.field(1214,472,300,'단면','XY / z = 0 mm')
    s.text(1214,610,'정규화 범례',15,INK,True,width=300)
    for i in range(10):
        v=i/9;color=f'#{int(226-165*v):02x}{int(237-95*v):02x}{int(248-30*v):02x}'
        s.rect(1214+i*27,635,27,24,color,'none')
    s.text(1214,688,'0',13,MUTED,width=30);s.text(1484,688,'1',13,MUTED,width=30,align='right')
    return s


def advanced():
    """! @brief 승인 후속 분야를 현재 지원으로 오인하지 않는 진입을 그린다."""
    s=results_base('44_고급분석_지원범위','S30.advanced','고급 분석 지원 범위',6);s.ui=['UI-17']
    s.notice(320,270,1218,'이 항목은 후속 범위입니다. 현재 R1 실행에 필수 입력으로 요구하지 않습니다.','info')
    s.table(320,344,1218,['분석','필요한 자료','지원 단계','행동'],[
        ('UWB','광대역 복소 응답 / 시간 기준','후속','설명 보기'),('NFC / RFID','근접 결합 / 태그 조건','후속','설명 보기'),('MIMO','다중 포트 / 패턴 상관','후속','설명 보기'),('배열','소자별 위상 / 배치 / 상호 결합','후속','설명 보기'),('일반 3차원 안테나','공간 도체 / 급전 / 환경 모델','장기 로드맵','설명 보기'),
    ],[2,5,2,2],row_h=62)
    s.text(320,780,'지원이 없는 항목은 활성 실행 명령으로 노출하지 않습니다.',15,MUTED,width=1218)
    return s


def compare(measurement=False):
    """! @brief 결과 중첩보다 먼저 조건 일치 여부를 보게 한다."""
    s=page('47_측정_비교' if measurement else '45_결과와_후보비교','S40.measurement' if measurement else 'S40','측정 비교' if measurement else '결과와 후보 비교','비교',['UI-19'] if measurement else ['UI-18'])
    central(s,'측정과 계산 비교' if measurement else '결과와 후보 비교',None,['실행 / 후보','수렴 연구','측정'],2 if measurement else 0)
    s.table(320,232,1218,['자료','입력 / 시료','포트 / 기준면','상태'],[
        ('A / 설명용 계산','개정 12','급전 01 / 포트 단자','합성 예시'),
        ('B / 측정 원본' if measurement else 'B / 설명용 후보','시료 정보 미정' if measurement else '개정 14','기준면 미정' if measurement else '급전 01 / 포트 단자','판정 보류' if measurement else '합성 예시'),
    ],[3,3,4,2],row_h=45)
    plot(s,320,396,1218,330,compare=True)
    s.notice(320,748,1218,'교정과 기준면이 미정이므로 실측 일치 판정을 보류합니다.' if measurement else '후보를 선택해도 현재 설계는 바뀌지 않습니다. 채택할 변경을 별도로 검토하세요.','warn' if measurement else 'info')
    side(s,'측정 조건' if measurement else '비교 조건', [('자료',[('원본','A / B 원본 유지'),('표시','합성 비교 예시')]),('조건',[('기준면','미정' if measurement else '같은 기준면 / 시안'),('교정 / 불확도','미정')]),('판정',[('실측 검증','미검증')])])
    s.notes=['이 그래프는 비교 배치 설명용이다. 실제 자료가 없는 빈 상태에 예시 곡선을 제품이 표시해서는 안 된다.','원본/기준면/시료/불확도 조건을 보존한다. 후보 채택은 별도의 원자 명령이다.']
    return s


def import_measurement():
    """! @brief 파일 열기와 의미 매핑을 나누는 가져오기 화면이다."""
    s=Screen('46_측정자료_가져오기','S40.import','측정 자료 가져오기','비교',['UI-19'])
    x,y,w,h=dialog(s,'측정 자료 가져오기','원본 파일과 변환 조건을 보존합니다.',tabs=['파일과 형식','열 / 포트 대응','시료와 교정','가져오기 검토'])
    s.field(x,y,812,'선택 파일','sample_measurement.s1p')
    s.button(x+836,y+28,180,'파일 선택',icon='folder')
    s.table(x,y+110,w,['파일 항목','읽은 값','사용자 확인'],[('형식','Touchstone / 1 port','지원 subset 검사 필요'),('주파수 단위','GHz','확인 대기'),('복소수 표현','RI','확인 대기'),('참조 임피던스','50 ohm','파일 원문 보존'),('교정 / 기준면','기록 없음','미정 유지')],[3,3,5],row_h=44)
    s.notice(x,y+420,w,'파싱 성공은 측정 신뢰성 또는 안테나 성능 검증이 아닙니다.','warn')
    s.rect(289,877,1342,72,WHITE,'none')
    s.text(312,921,'읽은 값의 단위와 포트 대응을 먼저 검토하세요.',14,MUTED,width=780)
    s.button(1290,896,112,'취소');s.button(1414,896,194,'열 / 포트 대응',True)
    s.notes=['기존 파일을 복사해 원본 hash와 열/단위/포트 대응을 보존한다. 미정 교정값을 자동 보완하지 않는다.']
    return s


def convergence():
    """! @brief 연구의 기준과 판정을 읽기 전용으로 연결한다."""
    s=page('48_수렴_연구보고서','D23','수렴 연구 보고서','비교',['UI-18','UI-22'])
    central(s,'수렴 연구 보고서','저장된 연구 조건과 당시 판정을 읽기 전용으로 표시합니다.',['실행 / 후보','수렴 연구','측정'],1)
    s.table(320,276,1218,['사례','격자 수준','실행 상태','총 수지','개별 손실 / 수렴'],[
        ('기준','원래 기록','완료','기록 보기','당시 판정 유지'),('세분화 1','원래 기록','완료','기록 보기','당시 판정 유지'),('세분화 2','원래 기록','완료','기록 보기','당시 판정 유지'),
    ],[2,2,2,2,4],row_h=65)
    s.notice(320,540,1218,'RO4350B 국부 도체 손실 변화 2.788446% / 초기 2% 기준 미확립','warn','다른 합격 항목을 이 항목의 합격으로 확대하지 않습니다. 원본 보고서 조건을 유지합니다.')
    s.button(320,654,192,'원본 연구 기록',icon='doc');s.button(528,654,180,'관련 실행 열기',icon='folder')
    side(s,'보고서 근거',[('원본',[('상태','저장 당시 판정 / 읽기 전용'),('새 평가','수행하지 않음')]),('미확립',[('GHz PTH','독립 물리 정확도 미확립'),('실측','미검증')])])
    s.notes=['새 시안 작성이 수렴 연구의 재실행 또는 과거 판정 변경을 뜻하지 않는다.']
    return s


def export_page(kind):
    """! @brief 도면, STEP, PCB 교환과 인계의 각 내용을 별도로 그린다."""
    entries=[('49_기술도면_출력','S50.drawing','기술 도면'),('50_스텝_출력과_검수','S50.step','STEP 생성과 검수'),('51_기판_제조파일교환','S50.pcb','PCB / CAM 교환'),('52_보고서와_인계','S50.report','보고서와 인계')]
    stem,identity,title=entries[kind]
    s=page(stem,identity,title,'출력',['UI-20'] if kind<2 else ['UI-21'] if kind==2 else ['UI-22'])
    central(s,title,None,['기술 도면','STEP','PCB / CAM','보고서 / 인계'],kind)
    if kind==0:
        s.rect(320,232,840,580,'#E8EDF4',LINE)
        s.rect(358,250,764,540,WHITE,'#93A3B8')
        s.rect(376,268,728,504,'none','#6F8198')
        board2d(s,491,292,498,340,False,True)
        s.table(376,650,728,['도면명','출력 축척','입력'],[('원형 안테나 / 상단 동박','미지정','개정 12'),('용지에 맞춘 표시 예시','출력 전 지정','초안')],[4,2,2],row_h=38)
        s.field(1184,244,330,'용지','A4 / 가로')
        s.field(1184,344,330,'출력 형식','PDF + SVG')
        s.field(1184,444,330,'표시 층','상단 동박 / 외곽선')
        s.check(1184,558,'치수와 표제란 포함',True,330)
        s.button(1184,724,330,'출력 내용 검토',True,'doc')
    elif kind==1:
        board3d(s,320,232,818,416)
        s.table(320,670,818,['대상','포함','상태'],[('기판 / 상하 동박','포함','명시 기하'),('외부 케이스','제외','원본 유지')],[4,2,3],row_h=43)
        s.field(1162,234,352,'출력 단위','mm')
        s.field(1162,330,352,'기준 좌표','프로젝트 원점')
        s.notice(1162,440,352,'생성과 독립 검수는 별도','warn','현재 STEP은 검수 전 상태입니다.')
        s.button(1162,570,352,'STEP 생성',True,'cube')
        s.button(1162,620,352,'독립 검수 기록',icon='doc')
    elif kind==2:
        s.tabs(320,232,1218,['KiCad','Gerber','드릴','Job / 묶음'],0)
        s.table(320,298,1218,['원본 층 / 객체','교환 층 / 의미','지원 상태','누락 / 변화'],[('상단 동박','F.Cu / copper','검토 필요','net 대응 확인'),('하단 동박','B.Cu / copper','검토 필요','net 대응 확인'),('기판 외곽','Edge.Cuts','검토 필요','닫힌 외곽 확인'),('급전 / port','사용자 메타데이터','전자기 의미 별도','포트 의미 유지 검토')],[3,3,2,4],row_h=56)
        s.notice(320,590,1218,'파일을 생성한 뒤 독립 재입력으로 형상, 층, net과 누락을 검사합니다.','warn','지원하지 않는 객체는 조용히 삭제하지 않고 목록과 이유를 제공합니다.')
        s.button(320,722,190,'교환 내용 검토',True,'doc');s.button(526,722,190,'재입력 검수 보기',icon='check')
    else:
        s.table(320,232,1218,['포함 항목','자료','상태'],[('프로젝트 원본','입력 개정 / 명령 / 출처 사본','보존'),('설계 문서','도면 / 치수 / 이름 대응','검토 필요'),('계산 결과','원본 실행 / 조건 / 후처리','선택 필요'),('검증 상태','수렴 / 물리 / 제조 / 측정','각 상태 별도'),('교환 파일','생성 목록 / 파일 hash / 검수','미완료 표시'),('제한과 미정','납품 조건 / GHz PTH / 손실','누락 없이 포함')],[3,6,3],row_h=55)
        s.notice(320,650,1218,'부분 실패나 미검수 파일을 완성 패키지로 표시하지 않습니다.','warn')
        s.button(320,744,200,'보고서 미리보기',True,'doc');s.button(536,744,220,'인계 파일 목록 검토',icon='folder')
    side(s,'출력 기준',[('입력',[('프로젝트','원형 안테나'),('고정 입력','개정 12')]),('경계',[('화면 표시와 출력','포함 목록을 별도 확인'),('제조 / 실측','미정 / 미검증')]),('파일',[('기록','생성자 / 버전 / hash')])])
    s.notes=['출력은 고정 snapshot과 포함 목록을 명시한다. 화면에서 숨긴 층을 자동으로 제외하지 않는다.','생성 성공/독립 검수/제조 또는 RF 검증을 별도 상태로 남긴다.']
    return s


def panel_page(kind):
    """! @brief 문제, 작업, 로그를 실제 상세 정보가 있는 전체 보기로 펼친다."""
    stems=['53_작업과_취소','54_문제와_위치이동','55_로그와_진단']
    names=['작업과 취소','문제와 위치 이동','로그와 진단']
    ids=['P11','P10','P12']
    s=page(stems[kind],ids[kind],names[kind],'해석',['UI-14'] if kind!=1 else ['UI-05','UI-12'],bottom=['작업','문제','로그'][kind])
    central(s,names[kind],'하단 패널에서 펼친 보기입니다. 현재 설계와 실행 입력을 구분합니다.')
    if kind==0:
        s.table(320,270,1218,['작업','입력','현재 단계','상태','동작'],[('해석 01','개정 12','시간 진행','실행 중','상세 / 취소 요청'),('형상 생성 01','개정 12','게시','완료','3D 보기'),('STEP 출력 01','개정 12','파일 생성','독립 검수 전','출력 폴더')],[3,2,3,3,3],row_h=60)
        s.section(320,528,1218,'선택 작업 / 해석 01')
        s.text(340,590,'진행 비율을 보고하지 않는 작업입니다. 현재 단계와 최근 응답 시각을 표시합니다.',16,MUTED,width=1170)
        s.rect(340,622,1170,8,'#E3EBF5','none',4);s.rect(770,622,180,8,BLUE,'none',4)
        s.text(340,654,'진행률 미제공 / 최근 응답 14:36:02',13,MUTED,width=1170)
        s.text(340,677,'취소 요청 후 실제 종료를 확인할 때까지 상태를 유지합니다.',15,INK,width=1170)
        s.button(340,730,168,'취소 요청',icon='close');s.button(524,730,168,'현재 상태 조회',icon='doc')
    elif kind==1:
        s.table(320,270,1218,['상태','대상','이유','검사 입력','행동'],[('미평가','원호 01 / 급전선','기대 연결이 미지정입니다.','개정 12','연결 설정'),('미정','기판','제조 선폭 한계가 없습니다.','개정 12','규칙 편집'),('차단','해석 조건','주파수 대역이 미정입니다.','개정 12','입력 위치로'),('이전 입력','과거 검사','현재 개정과 다릅니다.','개정 11','재검사')],[1.5,3,5.5,1.6,2],row_h=60)
        s.notice(320,602,1218,'문제 행을 선택한 뒤 Enter 또는 위치로 이동을 누르면 해당 객체 / 입력 필드로 이동합니다.')
        s.button(320,706,190,'위치로 이동',True,'target');s.button(526,706,170,'현재 입력 검사',icon='check')
    else:
        s.rect(320,270,1218,40,PANEL,LINE,3);s.icon('search',334,280,MUTED);s.text(370,297,'작업 또는 메시지 검색',15,MUTED,width=1000)
        s.table(320,332,1218,['시각','범위','단계','설명'],[('14:32:08','프로젝트','저장','개정 12 저장 완료'),('14:32:10','CAD','게시','표시 mesh 생성 완료'),('14:35:18','해석 01','접수','고정 입력 개정 12로 접수'),('14:35:20','해석 01','실행','시간 진행 시작'),('14:36:02','해석 01','상태 조회','실행 중 / 종료 확인 전')],[2,2,2,6],row_h=52)
        s.button(320,690,150,'선택 복사',icon='doc');s.button(486,690,200,'진단 묶음 검토',icon='folder')
        s.text(320,786,'비밀값을 제외한 진단 내용을 확인한 뒤 사용자가 내보냅니다.',15,MUTED,width=1218)
    side(s,'작업 문맥',[('선택',[('원본 입력','개정 12'),('현재 편집','개정 12')]),('조회',[('통신','서비스 응답 확인'),('종료','권위 상태로만 판정')])])
    s.notes=['진행률이 없는 작업에 가짜 백분율을 만들지 않는다. 비율 없는 표시 막대는 불확정 진행 표현이다.','문제와 로그에는 사람이 읽는 이름을 표시하며 내부 식별자는 상세 정보에 둔다.']
    return s


def empty():
    """! @brief 결과가 없을 때 실제 제품에 표시할 빈 상태를 분리한다."""
    s=page('62_결과없음과_미기록','S30.empty','결과 없음','결과',['UI-15','UI-16'])
    central(s,'결과',None,['네트워크','Smith','전력 / 손실','목표 평가','방사','필드','고급 분석'],0)
    s.icon('chart',886,348,'#92A5BF',72)
    s.text(930,482,'아직 조회할 결과가 없습니다',26,INK,True,width=1000,align='center')
    s.text(930,531,'기존 결과를 열거나 해석 입력을 확인하세요.',17,MUTED,width=1000,align='center')
    s.button(728,584,190,'기존 결과 열기',icon='folder',h=40)
    s.button(936,584,198,'해석 입력 확인',True,'play',h=40)
    s.notice(380,738,1098,'기록하지 않은 방사 / 필드 자료는 해당 결과에서 조회할 수 없습니다.')
    side(s,'결과 선택',[('자료',[('선택 결과','없음'),('그래프','자료 연결 전 표시하지 않음')])])
    s.notes=['실제 빈 화면에는 합성 그래프나 합격 수치를 넣지 않는다. 채워진 시안의 예시 데이터는 제품 기본값이 아니다.']
    return s


def compact():
    """! @brief 작은 창에서 명시적 패널 전환으로 필수 동작을 유지한다."""
    s=Screen('63_작은창_편집배치','S11.compact','작은 창 배치',ui=['UI-01','UI-05'])
    s.width,s.height=1366,900
    s.rect(0,0,1366,900,BG,'none')
    s.rect(0,0,1366,32,'#F4F7FC',LINE)
    s.text(16,23,'TraceWave Studio / 원형 안테나',15,INK,True,width=1000)
    s.text(1348,23,'설계 시안',12,MUTED,width=180,align='right')
    s.rect(0,32,1366,30,WHITE,LINE)
    for i,label in enumerate(['파일(F)','편집(E)','보기(V)','설계(D)','도구(T)','창(W)','도움말(H)']):s.text(16+i*83,53,label,14,INK,width=85)
    s.rect(0,62,1366,48,PANEL,LINE)
    s.button(12,69,90,'저장',icon='save');s.button(114,69,144,'실행 전 확인',icon='play')
    for i,label in enumerate(['설계','해석','결과','비교','출력']):s.button(312+i*86,69,78,label,i==0)
    s.button(1182,69,172,'패널 / 기본 배치',icon='layers')
    s.rect(8,118,248,740,WHITE,LINE)
    s.tabs(8,118,248,['탐색','속성'],1)
    s.text(24,195,'원호 01',20,INK,True,width=220)
    for i,(name,value,unit) in enumerate([('반지름','20.00','mm'),('선폭','1.20','mm'),('시작각','25.0','deg'),('끝각','155.0','deg')]):s.field(24,220+i*87,216,name,value,unit)
    s.notice(20,610,224,'제작 조건 미정','warn')
    s.button(24,718,208,'출처와 가정',icon='doc');s.button(24,772,208,'변경 적용',True,disabled=True)
    s.tabs(264,118,1094,['2D 편집','3D 형상'])
    s.rect(264,160,1094,50,PANEL,LINE)
    s.button(276,168,90,'선택',True,'select');s.button(378,168,90,'선',icon='line');s.button(480,168,98,'원호',icon='arc');s.button(590,168,130,'좌표 입력',icon='target');s.button(732,168,136,'전체 보기',icon='fit');s.check(906,178,'스냅',True,120)
    board2d(s,264,210,1094,595)
    s.tabs(264,813,1094,['문제 2','작업 1','로그'])
    s.rect(0,870,1366,30,PANEL,LINE)
    s.text(16,890,'1366 x 900 배치 시안 / 탐색과 속성을 명시적으로 전환',12,MUTED,width=840)
    s.text(1040,890,'mm  |  상단 동박  |  저장됨',12,MUTED,width=310)
    s.notes=['작은 창에서는 탐색/속성을 같은 명시적 notebook으로 전환하고 문제 패널은 펼침 명령을 제공한다.','AUI 자동 숨김으로 가정하지 않는다. 이 배치는 실제 DPI 또는 접근성 수용 증거가 아니다.']
    return s


def build():
    """! @brief 주요 페이지 시안을 고유 번호 순서로 반환한다."""
    return [startup(),create_project(),recovery(),design(),design(True),model(),model(True),
            preflight(),solver_settings(),mesh(),network(),smith(),power(),targets(),radiation(),radiation(True),
            field_view(),advanced(),compare(),import_measurement(),compare(True),convergence(),
            *[export_page(i) for i in range(4)],*[panel_page(i) for i in range(3)],empty(),compact()]
