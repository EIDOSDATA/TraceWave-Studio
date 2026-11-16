"""! @brief 전체 구현 시안의 누락, 경로, 벡터 편집성 및 렌더 검수 결과를 대조한다."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
import zlib

ROOT=Path(__file__).resolve().parents[3]
DOCS=ROOT/'01_개발문서/04_화면설계'
SVG='{http://www.w3.org/2000/svg}'


def require(condition,message):
    """! @brief 검수 실패를 명시적으로 보고한다."""
    if not condition:
        raise ValueError(message)


def inspect(folder,render_report):
    """! @brief 실제 세 가지 산출물과 Windows 글꼴 검수 입력을 모두 확인한다."""
    manifest=json.loads((folder/'13_전체화면목록.json').read_text(encoding='utf-8'))
    records=manifest['records']
    require(len(records)==manifest['screen_count']==84,'전체 화면 84개가 필요합니다.')
    require([int(row['stem'].split('_')[0]) for row in records]==list(range(1,85)),'그림 번호의 누락/중복')
    require(len({row['id'] for row in records})==84,'화면 ID 중복')
    require({ui for row in records for ui in row['approved_ui']}=={f'UI-{i:02d}' for i in range(1,25)},'승인 UI 대응 누락')
    render_by_name={row['name']:row for row in render_report['records']}
    require(len(render_by_name)==84,'84개 화면의 실제 렌더 결과가 필요합니다.')
    result=[]
    for row in records:
        require(re.fullmatch(r'\d{2}_[가-힣0-9_]+',row['stem']) is not None,'이름 규칙: '+row['stem'])
        paths={key:(folder/value).resolve() for key,value in row['assets'].items()}
        require(set(paths)=={'png','svg','drawio'},'세 종류 산출물 누락')
        require(all(path.is_relative_to(folder.resolve()/'03_구현시안') and path.is_file() for path in paths.values()),'허용 범위 밖 또는 누락 경로')
        svg=ET.parse(paths['svg']).getroot();drawing=ET.parse(paths['drawio']).getroot()
        require(not svg.findall('.//'+SVG+'image') and not svg.findall('.//'+SVG+'foreignObject'),'외부 이미지 또는 HTML 의존성')
        texts=[node.text or '' for node in svg.findall(SVG+'text')]
        cells=drawing.findall('.//mxCell');ids=[node.get('id') for node in cells]
        require(len(ids)==len(set(ids)),'DrawIO 셀 ID 중복')
        require(texts==[node.get('value') for node in cells if node.get('value') is not None],'SVG/DrawIO 문자열 불일치')
        require(drawing.find('diagram').get('id')==row['id'],'DrawIO 화면 ID 불일치')
        stencils=0
        for cell in cells:
            value=cell.get('style','')
            if 'shape=stencil(' in value:
                encoded=value.split('shape=stencil(',1)[1].split(')',1)[0]
                shape=ET.fromstring(zlib.decompress(base64.b64decode(encoded),-15))
                require(shape.tag=='shape' and shape.find('foreground/path') is not None,'편집 가능한 벡터 다각형 손상')
                stencils+=1
        png=paths['png'].read_bytes()
        require(png[:8]==b'\x89PNG\r\n\x1a\n','PNG 형식 오류')
        dimensions=struct.unpack('>II',png[16:24])
        require(dimensions==(row['width'],row['height']),'PNG와 화면 크기 불일치')
        require((int(svg.get('width')),int(svg.get('height')))==dimensions,'SVG와 PNG 크기 불일치')
        rendered=render_by_name[row['stem']+'.svg']
        require(rendered['svgSha256']==hashlib.sha256(paths['svg'].read_bytes()).hexdigest(),'현재 SVG와 다른 렌더 검수 입력')
        require(rendered['pngSha256']==hashlib.sha256(png).hexdigest(),'현재 PNG와 다른 렌더 검수 출력')
        require(not rendered['failures'],'글자 또는 화면 경계 실패: '+row['stem'])
        require((rendered['width'],rendered['height'])==dimensions,'렌더 검수 크기 불일치')
        require(rendered['textCount']==len(texts),'렌더 검수와 현재 SVG 문자열 수 불일치')
        require(row['notes'],'입출력/전환 설명 누락')
        result.append({'id':row['id'],'stem':row['stem'],'size':list(dimensions),'text_count':len(texts),
                       'drawio_cells':len(cells),'editable_polygon_stencils':stencils,
                       'sha256':{key:hashlib.sha256(path.read_bytes()).hexdigest() for key,path in paths.items()}})
    known={path.name for row in records for path in [(folder/value) for value in row['assets'].values()]}
    require({p.name for p in (folder/'03_구현시안').iterdir() if p.is_file()}==known,'미등록 또는 이전 이름 그림 존재')
    return {'schema':'tracewave.screen-visual-verification/0.1','date_kst':'2026-11-17','screens':len(records),
            'approved_ui_coverage':24,'asset_files':len(records)*3,'text_width_or_viewport_failures':0,
            'renderer':'Windows Edge headless / Malgun Gothic / scale 1',
            'scope':'static_screen_design_not_product_gui_or_rf_verification',
            'native_wx_gui_test':'not_run','native_drawio_roundtrip':'not_run',
            'records':result}


def main():
    """! @brief 재현 가능한 정적 화면 검수 기록을 저장한다."""
    parser=argparse.ArgumentParser()
    parser.add_argument('--folder',type=Path,default=DOCS)
    parser.add_argument('--render-report',type=Path,required=True)
    parser.add_argument('--gallery-report',type=Path)
    parser.add_argument('--report',type=Path,default=DOCS/'17_구현시안_검증.json')
    args=parser.parse_args()
    report=inspect(args.folder,json.loads(args.render_report.read_text(encoding='utf-8')))
    if args.gallery_report:
        gallery=json.loads(args.gallery_report.read_text(encoding='utf-8'))
        require(gallery['gallery_sha256']==hashlib.sha256((args.folder/'16_전체화면_둘러보기.html').read_bytes()).hexdigest(),'현재 둘러보기와 다른 동작 검수 입력')
        require(gallery['gallery_screens']==gallery['local_images_loaded']==84,'둘러보기 화면 누락')
        require(all(gallery[name] for name in ('search','workspace_filter','modal_open','next_previous','keyboard_navigation','original_size','escape_close')),'둘러보기 동작 실패')
        require(not gallery['page_errors'] and not gallery['missing_resources'],'둘러보기 자원 실패')
        report['gallery']=gallery
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False))


if __name__=='__main__':
    main()
