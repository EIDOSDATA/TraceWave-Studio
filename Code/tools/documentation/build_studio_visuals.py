"""! @brief 모든 구현 목표 화면의 벡터 원본, 대응 목록과 둘러보기를 생성한다."""

import argparse
import html
import json
from pathlib import Path

from studio_visuals import main_pages, settings_pages, workflow_pages, detail_pages, workflow_detail_pages

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "01_개발문서/04_화면설계"


def build_screens():
    """! @brief 모듈별 화면을 합치고 누락/중복 번호를 차단한다."""
    screens=sorted(main_pages.build()+settings_pages.build()+workflow_pages.build()+detail_pages.build()+workflow_detail_pages.build(),key=lambda s:s.stem)
    assert len(screens)==84
    assert [int(s.stem.split('_')[0]) for s in screens]==list(range(1,85))
    assert len({s.screen_id for s in screens})==84
    assert all(s.notes for s in screens)
    return screens


def write_gallery(folder, records):
    """! @brief 외부 의존성 없는 전체 화면 탐색 문서를 만든다."""
    cards=[]
    for row in records:
        stem=html.escape(row['stem']);title=html.escape(row['title']);identity=html.escape(row['id'])
        notes=''.join('<li>'+html.escape(note)+'</li>' for note in row['notes'])
        cards.append(f'''<article data-group="{html.escape(row['workspace'])}" data-search="{identity} {title}">
<button class="preview" data-stem="{stem}" aria-label="{title} 크게 보기"><img loading="lazy" src="03_구현시안/{stem}.png" alt="{title}"></button>
<div class="caption"><span>{identity}</span><h2>{stem.split('_',1)[0]}. {title}</h2><p>{html.escape(row['state'])}</p>
<a href="03_구현시안/{stem}.png">PNG</a><a href="03_구현시안/{stem}.svg">SVG</a><a href="03_구현시안/{stem}.drawio">DrawIO</a><details><summary>기능과 전환</summary><ul>{notes}</ul></details></div></article>''')
    page='''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TraceWave Studio 전체 화면 구현 시안</title>
<style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#eff2f6;color:#192a3d;font-family:'Malgun Gothic','Segoe UI',sans-serif}header{background:#fff;border-bottom:1px solid #d0d8e3;padding:28px 40px;position:sticky;top:0;z-index:1}h1{font-size:26px;margin:0 0 10px}header p{margin:0;color:#52657b;font-size:14px}.controls{display:flex;gap:8px;margin-top:20px;align-items:center;flex-wrap:wrap}input{font:inherit;padding:9px 12px;border:1px solid #c3cedd;border-radius:4px;min-width:300px}button{font:inherit;cursor:pointer}button.filter{padding:9px 20px;border:1px solid #ccd7e4;background:#fff;border-radius:4px;color:#192a3d}button.filter[aria-pressed=true]{background:#0866d8;border-color:#0866d8;color:white}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:24px;padding:32px 40px}article{background:white;border:1px solid #d0d8e3;border-radius:6px;overflow:hidden}article[hidden]{display:none}.preview{padding:0;border:0;display:block;width:100%;background:#f4f7fb}.preview img{width:100%;display:block}.caption{padding:18px 20px}.caption span{font-size:12px;color:#0866d8}.caption h2{font-size:18px;margin:6px 0}.caption p{font-size:13px;color:#52657b}.caption a{font-size:13px;color:#0866d8;margin-right:18px}summary{cursor:pointer;margin-top:15px;color:#52657b;font-size:13px}li{font-size:13px;line-height:1.8}dialog{padding:0;border:1px solid #65778f;border-radius:6px;width:96vw;max-width:1960px;height:94vh;max-height:1280px;background:#eff2f6}dialog::backdrop{background:#122136ba}.viewerbar{display:flex;gap:12px;align-items:center;height:52px;padding:8px 18px;background:#fff;border-bottom:1px solid #ccd7e4}.viewerbar strong{flex:1}.viewerbar button{height:34px;padding:4px 16px;background:#fff;border:1px solid #ccd7e4;border-radius:3px}.viewer{height:calc(100% - 52px);display:flex;align-items:center;justify-content:center;overflow:auto}.viewer img{max-width:100%;max-height:100%;object-fit:contain}.viewer.zoom{display:block}.viewer.zoom img{max-width:none;max-height:none;display:block}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #0866d8;outline-offset:3px}@media(max-width:650px){header,main{padding:20px}main{grid-template-columns:1fr}input{min-width:0;width:100%}}
</style></head><body><header><h1>TraceWave Studio / 전체 화면 구현 시안</h1><p>63개 화면 · wxWidgets + wxAUI + 사용자 정의 2D + OpenGL · 실제 앱이 아닌 구현 목표. 수치와 곡선은 별도 표시된 설명 자료입니다.</p>
<div class="controls"><input id="search" aria-label="화면 검색" placeholder="화면 이름 또는 ID 검색"><button class="filter" data-group="전체" aria-pressed="true">전체</button><button class="filter" data-group="설계" aria-pressed="false">설계</button><button class="filter" data-group="해석" aria-pressed="false">해석</button><button class="filter" data-group="결과" aria-pressed="false">결과</button><button class="filter" data-group="비교" aria-pressed="false">비교</button><button class="filter" data-group="출력" aria-pressed="false">출력</button><span id="count" aria-live="polite">63개</span></div></header><main>'''+''.join(cards)+'''</main>
<dialog id="viewerDialog" aria-label="화면 확대 보기"><div class="viewerbar"><strong id="viewerTitle"></strong><button id="previous">이전</button><button id="next">다음</button><button id="zoom">원본 크기</button><button id="close">닫기</button></div><div class="viewer" id="viewer"><img id="largeImage" alt=""></div></dialog>
<script>
const cards=[...document.querySelectorAll('article')],search=document.getElementById('search'),dlg=document.getElementById('viewerDialog');let group='전체',index=0;function filter(){const q=search.value.toLowerCase();cards.forEach(c=>c.hidden=(group!=='전체'&&c.dataset.group!==group)||!c.dataset.search.toLowerCase().includes(q));document.getElementById('count').textContent=cards.filter(c=>!c.hidden).length+'개'}search.addEventListener('input',filter);document.querySelectorAll('.filter').forEach(b=>b.onclick=()=>{group=b.dataset.group;document.querySelectorAll('.filter').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));filter()});function show(i){index=(i+cards.length)%cards.length;const c=cards[index],img=document.getElementById('largeImage');img.src=c.querySelector('img').src;img.alt=c.querySelector('h2').textContent;document.getElementById('viewerTitle').textContent=img.alt;document.getElementById('viewer').classList.remove('zoom');document.getElementById('zoom').textContent='원본 크기';if(!dlg.open)dlg.showModal()}cards.forEach((c,i)=>c.querySelector('.preview').onclick=()=>show(i));document.getElementById('previous').onclick=()=>show(index-1);document.getElementById('next').onclick=()=>show(index+1);document.getElementById('close').onclick=()=>dlg.close();document.getElementById('zoom').onclick=()=>{const zoom=document.getElementById('viewer').classList.toggle('zoom');document.getElementById('zoom').textContent=zoom?'화면에 맞춤':'원본 크기'};dlg.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'){e.preventDefault();show(index-1)}if(e.key==='ArrowRight'){e.preventDefault();show(index+1)}});
</script></body></html>
'''
    page=page.replace('63개 화면',f'{len(records)}개 화면').replace('>63개<',f'>{len(records)}개<')
    (folder/'16_전체화면_둘러보기.html').write_text(page,encoding='utf-8')


def main():
    """! @brief 구현 시안 전체와 동일 원본의 문서 목록을 저장한다."""
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=DOCS)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    screens=build_screens();records=[]
    for screen in screens:
        screen.save(args.output/'03_구현시안')
        records.append({'stem':screen.stem,'id':screen.screen_id,'title':screen.title,'workspace':screen.workspace,
                        'approved_ui':screen.ui,'state':screen.state,'width':screen.width,'height':screen.height,
                        'notes':screen.notes,'assets':{suffix:'03_구현시안/'+screen.stem+'.'+suffix for suffix in ('png','svg','drawio')}})
    manifest={'schema':'tracewave.screen-implementation-views/0.1','date_kst':'2026-11-17','scope':'implementation_design_not_native_gui_acceptance',
              'screen_count':len(records),'shared_screens':{'S10':'모든 주요 화면의 공통 프레임','P13':'S50.step 및 P11의 CAD 출력 상세'},
              'data_policy':'기하/수치/곡선의 배치 예시이며 제조/측정/물리 검증 증거가 아님. 미정과 원문은 별도 보존.',
              'records':records}
    (args.output/'13_전체화면목록.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_gallery(args.output,records)
    print(f'{len(screens)} screens / SVG + editable DrawIO + manifest + gallery')


if __name__=='__main__':
    main()
