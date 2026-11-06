#!/usr/bin/env python3
"""Rebuild a provenance-preserving RF PCB dielectric dataset from the acquired corpus.
Dependencies: PyMuPDF (fitz), lxml. Run: python build_materials.py [--corpus-root ROOT]
No interpolation, grade substitution or generic FR-4 dielectric constant is performed.
"""
from pathlib import Path
import argparse, collections, csv, hashlib, json, re, unicodedata
import fitz
from lxml import html

P=argparse.ArgumentParser();P.add_argument('--corpus-root',type=Path,default=Path(__file__).resolve().parents[2]);args=P.parse_args()
ROOT=args.corpus_root; OUT=Path(__file__).resolve().parent
CAT={x['id']:x for x in json.loads((ROOT/'package/catalog.json').read_text())['records']}
OVERRIDES={
 'ISOLA_ASTRA_DKDF':('research/material_substitute_astra-mt77-laminate-and-prepreg.html','https://www.isola-group.com/pcb-laminates-prepreg/astra-mt77-laminate-and-prepreg/','C; May 2024 (construction table)'),
 'ISOLA_FR408HR_DKDF':('research/material_substitute_fr408hr-laminate-and-prepreg.html','https://www.isola-group.com/pcb-laminates-prepreg/fr408hr-laminate-and-prepreg/','G; January 2026 (construction table)'),
 'PANASONIC_R_5785_G__new':('research/material_substitute_ast-ind-232633.pdf','https://industrial.panasonic.com/cdbs/www-data/pdf/EMB0000/ast-ind-232633.pdf','April 2022; No.22040128')}
PINNED_SOURCE_SHA256={'ROGERS_RO47_DS': '83cf55d8bf0bb6441391c34d3594d38b327a6898c63b4e00a88e4086dccb3eff', 'ROGERS_RO47_FAB': '56f6b975fdd90994aaa4bed31bedcf5d0074d3700d49587bc7fc9145c0e7dbf1', 'ROGERS_PIM_ANTENNAS': '3febcc4151c00c66aa9e44f6f59e88ef3bbcf0351d7c810584ba4d1e341db82e', 'ROGERS_COPPER_FOIL': 'efb862793ca3262e88e6fa447a9b7af6c91b7aecbd5ae89363f2a4436e89fc66', 'ROGERS_MATERIAL_SELECTOR': 'b8fc9ba18cb1bdb250528519ee576799645b360d8492bf2df0daa36deffba978', 'ROGERS_RO3000_DS': '4ef4798ee3440c0ed4cf25ac9fa23f75f5907784f2ebff306350b3870eaf1f3e', 'ROGERS_RO3000_BONDPLY': 'a237b2a9c2302c713686dd39a26959c0752c7964b55e43d8fa54ecc39c9579be', 'ROGERS_RO3000_FAB': '6f239906ced3fceece9cf602ec0c910fe65a208c2e481cc3994f9a856695de47', 'ROGERS_RO3003G2_DS': '6d8347600907de06459848197889793f908697275267212424a263622c5cf7ff', 'ROGERS_DUROID_DS': '65928dde6b9630eca447b59a73f70aeb11618ae630a93bfc4c5e0a64a495d1cf', 'ROGERS_DUROID_FAB': '27fd781320cd6376b4806a391f72a4301a1b601cd4e167ff0a9a7d1baa0a4a32', 'ROGERS_STRIPLINE_WIDTH': 'f624762ee88cc9ea428c0b42788ad407fd3903a2a5a0d31acd515961c07a741e', 'ROGERS_STRIPLINE_EQ': '32af96d38a6b8dd00cfb823eb96b346cb50a3f34669aa22f37c2219fc59a198c', 'ROGERS_ISOTROPY': 'addb0492d273cfbf6a88418d0d9ec55372498d3cd98cf06f47dab0b47ff830f0', 'ROGERS_RO4000_DS': '51b920d81356884d6924e608ead6f8555ce1bd2ac635ebd255102d040e6afd0d', 'ISOLA_ASTRA_DS': 'b272094b0ea1c54a037b0ed1ac873f0811d2861085c6f7cff3f280a19a77e56e', 'ISOLA_ASTRA_DKDF': '6de3d6f5ea1f2e55ba9a34ee0b2d29c774e146390d2d6fc9fe1151890afa6eb9', 'ISOLA_FR408HR_DS': '981522185955712f010d6ded6e95429d64b95b2689cb6892322ad6b2c14b5b55', 'ISOLA_FR408HR_DKDF': '3bdab198dd45f51186396fc613ee6c97d24dcd07de12b0712b05bad4c84829d6', 'PANASONIC_R_579Y': 'c603ad383f6b66aae5f26c8cb3ca448924c4ec983381f6645e9372cfb1b3d150', 'PANASONIC_R_5795': '619ecbbc86389e2d4cdf8cf667fc2a70833d80c43178eed24b9cc3d49cf364d9', 'PANASONIC_R_5785_G__new': '76eb4805acb1ebc148b3e16876aa11f4abf2c7df337634f75ef1ddbc46dbb505', 'PANASONIC_R_5785_N__new': 'fb857e413b8e12c6265aad0267cd939cd0c02fd7879ff99fdfb2af5cd7e29b9e', 'PANASONIC_R_5775__50GHz_new': '0a34e86726cd5ba76dcbb687c2bfbcd93f4d2bf78421f7ea606f7dced5e3089c', 'PANASONIC_R_5725S': 'c4064a98e522bc2475d944d737349c4167c9ece8c3010fd51940bdc72a23c8d1', 'PANASONIC_R_1755V': '630aae6db1a4e81cda083bd8b8db9fa02ec4a4d27ec5146e6d735aef1b862cba', 'PANASONIC_R_1766_GH_': 'f04154a1e7a55ce13984db909f44b4c018809c3a5476da944119bf3c07168923', 'AGC_TLY5_DS': '654ed96035c5e7ac629fa68552310b01754b1ac36c1f37fb8daf86ce68ba4275', 'AGC_TLY5_FAB': '6df7df77e07f4bd63397627ec029701a54c10a2c2028402f6c6ece8567e8b25d', 'DUPONT_PYRALUX_AP': '732d48eb012d4fcac96d67e7e45b860b6e8c2c788c2c22326b9b13538fc948d0', 'PANASONIC_R_5775_N__new': 'd5eaecc0464b356cf2b51a4853f56d6ecf6539c02021d29b28bfe9f67163d3d3'}
SOURCE={}; ROWS=[]; EVIDENCE=[]; ISSUES=[]; TABLES=[]
FIELDS=['record_id','source_id','manufacturer','material','material_form','data_scope','construction','glass_style','glass_type','ply_count','resin_content_percent','availability','core_type','core_label','prepreg_label','thickness_mm','thickness_inch','thickness_mil','thickness_um','thickness_basis','nominal_thickness_mm','nominal_thickness_mil','frequency_hz','frequency_min_hz','frequency_max_hz','dk','dk_tolerance_abs','dk_kind','df','dk_test_method','df_test_method','direction','test_condition','temperature_c','copper_condition','source_revision','source_sha256','source_filename','source_url','source_locator','evidence_ids','value_status','requires_review','record_flags','notes']

def norm(x):return ' '.join(unicodedata.normalize('NFKC',x or '').split())
def num(x):
 if x is None or not str(x).strip():return None
 v=norm(str(x)).replace('%','').replace(',','.')
 v=re.sub(r'(?:um|μm|µm)$','',v).rstrip('*')
 if not re.fullmatch(r'[-+]?\d*\.?\d+',v):raise ValueError('not a scalar: '+repr(x))
 return float(v)
def frequency(x):
 m=re.fullmatch(r'([0-9.]+)\s*(MHz|GHz|kHz|Hz)',norm(x),re.I)
 return float(m[1])*{'hz':1,'khz':1e3,'mhz':1e6,'ghz':1e9}[m[2].lower()] if m else None

def src(sid):
 if sid in SOURCE:return SOURCE[sid]
 c=CAT[sid]; p=ROOT/'package'/c['relative_path'] if c.get('relative_path') else None
 if (not p or not p.exists()) and sid in OVERRIDES:p=ROOT/OVERRIDES[sid][0]
 if not p or not p.exists():return None
 sha=hashlib.sha256(p.read_bytes()).hexdigest()
 if PINNED_SOURCE_SHA256.get(sid) and PINNED_SOURCE_SHA256[sid]!=sha:raise ValueError('Source differs from the curated extraction release: '+sid)
 s={'source_id':sid,'source_title':c['title'],'manufacturer':c.get('organization'),'source_url':OVERRIDES[sid][1] if sid in OVERRIDES else c.get('download_url') or c.get('source_url'),'source_filename':p.name,'source_sha256':sha,'source_revision':OVERRIDES[sid][2] if sid in OVERRIDES else c.get('year_or_revision'),'path':str(p),'coverage_status':'not_yet_extracted','coverage_note':None}
 if c.get('sha256') and c['sha256']!=sha:raise ValueError('SHA mismatch '+sid)
 SOURCE[sid]=s;return s

def evidence(sid,locator,raw,method='pdf_table_coordinate_extraction',**kw):
 eid=f'ME-{len(EVIDENCE)+1:05d}';EVIDENCE.append({'evidence_id':eid,'source_id':sid,'source_sha256':src(sid)['source_sha256'],'locator':locator,'extraction_method':method,'raw_cells_or_short_excerpt':raw,**kw});return eid

def add(sid,**kw):
 s=src(sid);r={f:None for f in FIELDS};r.update({k:s[k] for k in ['source_id','manufacturer','source_revision','source_sha256','source_filename','source_url']});r.update({'data_scope':'construction_specific','dk_kind':'manufacturer_typical','value_status':'typical_not_guaranteed'});r.update(kw);ROWS.append(r);return r

def mark(sid,status,note):src(sid).update(coverage_status=status,coverage_note=note)

def extract_isola(sid,material,expected):
 s=src(sid);d=html.fromstring(Path(s['path']).read_bytes());ts=d.xpath('//table'); counts=[]
 for ti,form in [(2,'core'),(3,'prepreg')]:
  a=[[norm(' '.join(v.itertext())) for v in tr.xpath('./th|./td')] for tr in ts[ti].xpath('.//tr')]
  fs=[frequency(v) for v in a[1]];assert all(fs)
  count=0
  for ri,row in enumerate(a[2:],start=3):
   if material=='Astra MT77':
    if form=='core':availability,inch,mm=row[:3]; style=rc=None;n=3;construction=None
    else:style,rc,inch,mm=row[:4];n=4;availability=None;construction=style
   else:
    construction,rc,availability,inch,mm=row[:5];n=5;style=construction if form=='prepreg' else None
   assert len(row)-n==len(fs),(sid,ti,ri,row)
   loc=f'HTML table {ti+1} (1-based), {form.title()} Data, source row {ri} including 2 header rows'
   eid=evidence(sid,loc,row,'html_table_dom')
   for f,pair in zip(fs,row[n:]):
    vals=pair.split();assert len(vals)==2
    add(sid,material=material,material_form=form,construction=construction,glass_style=style,resin_content_percent=num(rc),availability=availability,thickness_inch=num(inch),thickness_mm=num(mm),thickness_basis='manufacturer table; printed rounded inch and mm preserved',frequency_hz=f,dk=num(vals[0]),df=num(vals[1]),source_locator=loc,evidence_ids=[eid],glass_type='spread weave, both directions' if material=='FR408HR' else None,notes='Construction table does not restate the dielectric test method. Do not assign generic datasheet methods to every frequency without verification.')
    count+=1
  counts.append(count);TABLES.append({'source_id':sid,'section':form,'data_rows':len(a)-2,'frequency_count':len(fs),'records':count,'html_table_1based':ti+1})
 assert sum(counts)==expected,(sid,counts)
 mark(sid,'complete_construction_dk_df_tables','All core and prepreg construction rows and all published frequency columns extracted from official HTML; original PDF link was unavailable.')

REV={
'PANASONIC_R_579Y':'July 2024; No.240724','PANASONIC_R_5795':'July 2024; No.240724','PANASONIC_R_5785_N__new':'July 2024; No.240724','PANASONIC_R_5775__50GHz_new':'Cover prints April 2021; No.22040129 (preserved as printed)','PANASONIC_R_5725S':'October 2021; No.21101248','PANASONIC_R_1755V':'July 2019; No.19070536','PANASONIC_R_1766_GH_':'July 2019; No.19070546','PANASONIC_R_5775_N__new':'April 2022; No.22040130'}

def split_rows(a):
 # A missing PDF ruling sometimes puts two physical rows in one extracted cell.
 # Expand only when populated columns have compatible line counts; never join values.
 out=[]
 for ri,row in enumerate(a[2:],3):
  cells=[v.split('\n') if v else [] for v in row]; n=max(map(len,cells),default=1)
  if n>1 and all(len(c) in [0,1,n] for c in cells):
   for k in range(n):out.append((ri,k+1,[c[k] if len(c)==n else (c[0] if c else None) for c in cells]))
  elif n>1:raise ValueError('ambiguous PDF multiline row '+repr(row))
  else:out.append((ri,None,row))
 return out

def meta_headers(a):
 # Retain subheaders (mil/mm); merged meta headings are not ffilled globally.
 h=[]
 for top,sub in zip(a[0],a[1]):h.append(norm(sub) if norm(sub) in ['mil','mm'] else norm(top))
 return h

def panasonic_table_rows(sid,pageno,tindex,a,title,revision,methodnote):
 headers=meta_headers(a);freqcols=[];kind=None
 for j,(h0,h1) in enumerate(zip(a[0],a[1])):
  if 'Dk' in (h0 or ''):kind='dk'
  if 'Df' in (h0 or ''):kind='df'
  f=frequency(h1)
  if f and kind:freqcols.append((j,kind,f))
 if not freqcols:return 0
 form='prepreg' if re.search('Prepreg',title,re.I) else 'core'
 m=re.search(r'(R-\d+[A-Za-z]*(?:\([A-Za-z]+\))?)',title);assert m,(sid,pageno,title)
 material=m[1]; glass=title.split(':',1)[1].strip() if ':' in title else None
 last={}; bycondition=collections.OrderedDict(); nrows=0
 for ri,split_i,row in split_rows(a):
  vals={};metadata={};raw=list(row)
  for j,h in enumerate(headers):
   if j>=min(z[0] for z in freqcols):break
   v=norm(row[j]) or None
   if form=='prepreg' and ('Cloth' in h or 'Nominal' in h or 'label' in h.lower()):
    if v is not None:last[j]=v
    else:v=last.get(j)
   metadata[h or f'empty_column_{j}']=v
  # Reject blank/spurious rows, not data rows with numeric omissions.
  try:
   if form=='core':
    mm=num(metadata.get('mm'));mil=num(metadata.get('mil'))
    if mm is None or mil is None:continue
    ct=metadata.get('Core Type');cloth=next((v for h,v in metadata.items() if 'Cloth' in h),None)
    rc=next((v for h,v in metadata.items() if 'Resin' in h),None)
    ply=next((v for h,v in metadata.items() if norm(h).lower()=='ply'),None)
    basis='nominal' if 'Nominal' in norm(a[0][0]) else 'actual'
    kw={'core_type':ct,'core_label':next((v for h,v in metadata.items() if 'Core Label' in h),None),'construction':cloth if ply is None else f'{cloth} x {ply}','glass_style':cloth,'resin_content_percent':num(rc),'ply_count':num(ply) if ply is None or '/' not in ply else None,'thickness_mm':mm,'thickness_mil':mil,'thickness_basis':basis}
    if basis=='nominal':kw.update(nominal_thickness_mm=mm,nominal_thickness_mil=mil)
   else:
    cloth=next((v for h,v in metadata.items() if 'Cloth' in h),None);rc=next((v for h,v in metadata.items() if 'Resin' in h),None)
    th=next((v for h,v in metadata.items() if 'Typical' in h and 'Thickness' in h),None)
    if th is None:raise ValueError('missing typical thickness')
    um=num(th);nom=next((v for h,v in metadata.items() if 'Nominal' in h),None)
    kw={'construction':cloth,'glass_style':cloth,'resin_content_percent':num(rc),'thickness_um':um,'thickness_mm':um/1000,'thickness_basis':'typical prepreg thickness in micrometres; mm converted exactly','nominal_thickness_mm':num(nom),'prepreg_label':next((v for h,v in metadata.items() if 'label' in h.lower()),None)}
   assert cloth is not None
   for j,k,f in freqcols:
    if ',' in (row[j] or ''):ISSUES.append({'source_id':sid,'pdf_physical_page':pageno,'table':tindex,'source_row':ri,'property':k,'frequency_hz':f,'raw_value':row[j],'action':'Decimal comma interpreted as decimal separator; raw value retained in evidence.'})
    vals[(k,f)]=num(row[j])
  except Exception as e:raise ValueError(f'{sid} p{pageno} table{tindex} row{ri}: {e}; {row}; metadata {metadata}')
  loc=f'PDF physical page {pageno}, table {tindex}, data row {nrows+1} (extracted source row {ri}'+(f', split line {split_i}' if split_i else '')+')'
  eid=evidence(sid,loc,raw,pdf_physical_page=pageno,table=tindex,data_row=nrows+1,metadata=metadata)
  nrows+=1
  for f in sorted(set(f for k,f in vals)):
   method='IPC-TM-650 2.5.5.9' if f<=1e9 else ('Balanced-type Circular Disk Resonance; IEC 63185 (2020)' if 'Circular' in methodnote else 'IPC-TM-650 2.5.5.5')
   dk=vals.get(('dk',f));df=vals.get(('df',f))
   if dk is None and df is None:continue
   add(sid,material=material,material_form=form,glass_type=glass,availability='under_development_as_of_source_revision' if any('*' in (v or '') for v in row) and 'under development' in methodnote else None,frequency_hz=f,dk=dk,df=df,dk_test_method=method if dk is not None else None,df_test_method=method if df is not None else None,source_revision=revision,source_locator=loc,evidence_ids=[eid],notes='Printed core/prepreg construction values. Sample conditioning is not restated on this construction table; representative-property-table conditioning is not automatically transferred.',**kw)
 TABLES.append({'source_id':sid,'pdf_physical_page':pageno,'table':tindex,'material':material,'form':form,'physical_data_rows':nrows,'frequency_columns':[{'property':k,'hz':f} for _,k,f in freqcols]})
 return nrows


def special_r5775(sid,pageno,page):
 # Pages 8–10 have defective vector grid rulings. Numeric blocks preserve the rows.
 # Values are read from PDF text positions, with explicit source-specific layout.
 blocks=page.get_text('blocks'); fs=[1e9,13e9,24e9,35e9,46e9,56e9]
 if pageno==8:
  block=next(b for b in blocks if 'mil\nmm\n' in b[4] and len(b[4])>1000)
  toks=block[4].splitlines();idx=next(i for i,x in enumerate(toks) if '56' in x and 'GHz' in x)+1;data=toks[idx:]
  assert len(data)==24*12,(pageno,len(data))
  a=[['Core Type','Actual Thickness',None,'Cloth Style','ply','Typical Resin Content (%)','Typical Df',None,None,None,None,None],[None,'mil','mm',None,None,None]+['1GHz','13GHz','24GHz','35GHz','46GHz','56GHz']]+[data[i:i+12] for i in range(0,len(data),12)]
  return panasonic_table_rows(sid,pageno,1,a,'Laminate R-5775(G)',REV[sid],'Circular')
 else:
  # Each data block contains resin content, thickness and six RF values.
  # Glass style cells are vertically merged; their spans are verified from PDF layout.
  rows=[]
  for b in blocks:
   if 145<b[1]<480 and b[0]>150:
    ss=b[4].splitlines()
    if len(ss)==8 and all(re.fullmatch(r'[\d.]+',v) for v in ss):rows.append((b[1],ss))
   elif 145<b[1]<160 and b[0]<100:
    ss=b[4].splitlines()
    if len(ss)==9 and ss[0]=='1027':rows.append((b[1],ss[1:]))
  rows.sort();assert len(rows)==17,(pageno,len(rows))
  styles=['1027']+['1035']*3+['1067']*3+['1080']*2+['1078']*4+['3313']*2+['2116']*2
  prop='Dk' if pageno==9 else 'Df'
  a=[['Cloth Style','Resin Content (%)','Typical Thickness (um)','Typical '+prop,None,None,None,None,None],[None,None,None]+['1GHz','13GHz','24GHz','35GHz','46GHz','56GHz']]+[[st]+rr for st,(_,rr) in zip(styles,rows)]
  return panasonic_table_rows(sid,pageno,1,a,'Prepreg R-5670(G)',REV[sid],'Circular')


def repair_spurious_columns(page,t,a,sid,pageno):
 # Some PDF drawing fragments create phantom columns. Read the full physical
 # frequency cell using the header boundary, preserving original-vs-repaired evidence.
 fs=[j for j,v in enumerate(a[1]) if frequency(v)]
 for fi,j in enumerate(fs):
  end=fs[fi+1] if fi+1<len(fs) else len(a[0])
  if end-j<=1:continue
  header=t.rows[1].cells[j]
  if header is None:raise ValueError('missing frequency header box')
  x0=header[0];x1=t.rows[1].cells[end][0] if end<len(a[0]) and t.rows[1].cells[end] else header[2]
  for ri in range(2,len(a)):
   cells=[c for c in t.rows[ri].cells[:fs[0]] if c]
   if not cells:continue
   ycell=min(cells,key=lambda c:c[3]-c[1]);box=(x0,ycell[1],x1,ycell[3])
   val=page.get_text(clip=fitz.Rect(box)).strip()
   if val and val!=a[ri][j]:
    ISSUES.append({'source_id':sid,'pdf_physical_page':pageno,'source_row':ri+1,'issue':'PDF vector fragments split a frequency column','action':'Recovered original printed value from full physical cell bounding box','original_extracted_cells':a[ri][j:end],'recovered_text':val,'bbox':list(box)})
    a[ri][j]=val
   for k in range(j+1,end):a[ri][k]=None
 return a

def extract_panasonic(sid):
 s=src(sid);revision=OVERRIDES[sid][2] if sid in OVERRIDES else REV[sid];s['source_revision']=revision
 d=fitz.open(s['path']);pages=[];table_n=0
 for i,p in enumerate(d):
  if i<2:continue
  text=p.get_text();title=re.search(r'(?:Specification|Dielectric Properties)\s*/\s*(?:Laminate|Prepreg)[^\n]*',text)
  if not title:continue
  if sid=='PANASONIC_R_5775__50GHz_new' and i+1 in [8,9,10]:special_r5775(sid,i+1,p);pages.append(i+1);continue
  for ti,t in enumerate(p.find_tables().tables,1):
   a=t.extract()
   if len(a)<3 or len(a[0])<6:continue
   if not any('Dk' in (v or '') or 'Df' in (v or '') for v in a[0]):continue
   a=repair_spurious_columns(p,t,a,sid,i+1)
   n=panasonic_table_rows(sid,i+1,ti,a,title[0],revision,text)
   if n:table_n+=1;pages.append(i+1)
 mark(sid,'complete_construction_dk_df_tables','Published construction tables parsed by physical page, including merged glass-style cells and all frequency columns. Representative property p2 values are redundant and not duplicated. Pages: '+', '.join(map(str,sorted(set(pages)))))
 return d

# Run construction tables before manually verified representative points.
extract_isola('ISOLA_ASTRA_DKDF','Astra MT77',70)
extract_isola('ISOLA_FR408HR_DKDF','FR408HR',264)
for sid in [x for x in CAT if x.startswith('PANASONIC_')]:
 if src(sid):extract_panasonic(sid)

# Additional verified representative property entries are seeded below. The numerical
# seed is a curated transcription, tied to the actual acquired bytes and physical pages.
def typical(sid,material,page,revision,dk=None,df=None,f=None,fmin=None,fmax=None,kind='manufacturer_typical',tol=None,method=None,dfmethod=None,condition=None,direction=None,temp=None,notes=None,copper=None,raw=None,**kw):
 src(sid)['source_revision']=revision
 loc=f'PDF physical page {page}, representative dielectric property table'
 eid=evidence(sid,loc,raw or {'material':material,'dk':dk,'df':df,'frequency_hz':f,'frequency_range_hz':[fmin,fmax]},'manual_transcription_verified_against_pdf_table',pdf_physical_page=page)
 add(sid,material=material,material_form=kw.pop('material_form','laminate'),data_scope='representative_property',dk=dk,df=df,frequency_hz=f,frequency_min_hz=fmin,frequency_max_hz=fmax,dk_kind=kind,dk_tolerance_abs=tol,dk_test_method=method,df_test_method=dfmethod or (method if df is not None else None),test_condition=condition,direction=direction,temperature_c=temp,source_revision=revision,source_locator=loc,evidence_ids=[eid],notes=notes,copper_condition=copper,**kw)

# Process and design Dk are intentionally distinct records.
for material,dk,tol,df,design in [('RO3003',3.00,.04,.0010,3.00),('RO3035',3.50,.05,.0015,3.60),('RO3006',6.15,.15,.0020,6.50),('RO3010',10.2,.30,.0022,11.20)]:
 sid='ROGERS_RO3000_DS';rev='Revised 1687 013024; Publication 92-130; 2024'
 typical(sid,material,2,rev,dk=dk,df=df,f=10e9,kind='process',tol=tol,method='IPC-TM-650 2.5.5.5',temp=23,notes='Family property table; grade-specific. Thickness and construction are not specified in this dielectric row.')
 typical(sid,material,2,rev,dk=design,fmin=8e9,fmax=40e9,kind='design',method='Differential Phase Length',notes='Design Dk is an average over tested lots and common thicknesses; not a measured continuous dielectric dispersion curve.')
mark('ROGERS_RO3000_DS','representative_dielectric_points_complete','Process Dk, tolerance, 10 GHz Df and frequency-range design Dk for all four grades; standard construction/cladding options are retained separately.')
for material,dk,tol,df,design in [('RO3003',3.00,.04,.0010,3.00),('RO3006',6.15,.15,.0020,6.50),('RO3010',10.2,.30,.0022,11.20)]:
 sid='ROGERS_RO3000_BONDPLY';rev='Revised 1258 121216; Publication 92-147'
 typical(sid,material+' bondply',4,rev,dk=dk,df=df,f=10e9,kind='process',tol=tol,method='IPC-TM-650 2.5.5.5; Clamped Stripline',dfmethod='IPC-TM-650 2.5.5.5',temp=23,direction='Z',material_form='bondply',notes='Property table in bondply processing guide. Bonded thickness depends on lamination conditions; do not apply unbonded thickness as cured stackup thickness.')
 typical(sid,material+' bondply',4,rev,dk=design,fmin=8e9,fmax=40e9,kind='design',method='Differential Phase Length',direction='Z',material_form='bondply',notes='Frequency range average; not a dispersion model.')
mark('ROGERS_RO3000_BONDPLY','representative_dielectric_points_complete','All three bondply grades; process/design values kept distinct; thickness-pressure curves not digitized.')
for material,dk,df10,df25,design in [('RO4003C',3.38,.0027,.0021,3.55),('RO4350B',3.48,.0037,.0031,3.66)]:
 sid='ROGERS_RO4000_DS';rev='Revised 1592 080322; Publication 92-004; 2022'
 typical(sid,material,3,rev,dk=dk,df=df10,f=10e9,kind='process',tol=.05,method='IPC-TM-650 2.5.5.5; Clamped Stripline',dfmethod='IPC-TM-650 2.5.5.5',direction='Z',temp=23,notes='Family property table, no single construction specified.')
 typical(sid,material,3,rev,df=df25,f=2.5e9,method='IPC-TM-650 2.5.5.5',direction='Z',temp=23,notes='Only loss tangent is tabulated at 2.5 GHz; Dk is null.')
 typical(sid,material,3,rev,dk=design,fmin=8e9,fmax=40e9,kind='design',method='Differential Phase Length',direction='Z',notes='Average design Dk over frequency range and tested common constructions.')
mark('ROGERS_RO4000_DS','representative_dielectric_points_complete','RO4003C/RO4350B process and design Dk, tolerances and 2.5/10 GHz loss tangent extracted separately.')
sid='ROGERS_RO3003G2_DS';rev='Revised 1625 102522; Publication 92-547; 2022'
typical(sid,'RO3003G2',3,rev,dk=3.00,df=.0011,f=10e9,kind='process',tol=.04,method='IPC-TM-650 2.5.5.5; Clamped Stripline',dfmethod='IPC-TM-650 2.5.5.5',direction='Z',temp=23,copper='VLP ED copper product; see separate foil roughness table')
typical(sid,'RO3003G2',3,rev,dk=3.07,f=77e9,kind='design',method='Differential Phase Length',direction='Z',notes='77 GHz design value, not equal to 10 GHz process Dk.')
mark(sid,'representative_dielectric_points_complete','10 GHz process and 77 GHz design Dk; foil roughness table included in construction options/evidence.')
for material,dk,df1,df10 in [('RT/duroid 5870',2.33,.0005,.0012),('RT/duroid 5880',2.20,.0004,.0009)]:
 sid='ROGERS_DUROID_DS';rev='Revised 1603 080822; Publication 92-101; 2022'
 typical(sid,material,2,rev,dk=dk,df=df1,f=1e6,kind='process',method='IPC-TM-650 2.5.5.3',condition='C24/23/50',direction='Z',notes='No tolerance is printed with the 1 MHz typical value; the 10 GHz specification tolerance is not transferred.')
 typical(sid,material,2,rev,dk=dk,df=df10,f=10e9,kind='process',tol=.02,method='IPC-TM-650 2.5.5.5',condition='C24/23/50',direction='Z',notes='Dk ±0.02 is marked spec. in the source; Df remains typical.')
 typical(sid,material,2,rev,dk=dk,fmin=8e9,fmax=40e9,kind='design',method='Differential Phase Length',direction='Z',notes='Design Dk average over the indicated range.')
mark(sid,'representative_dielectric_points_complete','1 MHz / 10 GHz process Dk and loss plus 8–40 GHz design Dk for RT/duroid 5870 and 5880. Printed standard thicknesses remain original values.')
for material,dk,df10,df25,design in [('RO4725JXR',2.55,.0026,.0022,2.64),('RO4730G3',3.00,.0028,.0028,2.98)]:
 sid='ROGERS_RO47_DS';rev='Revised 1619 092322; Publication 92-168; 2021 copyright'
 typical(sid,material,2,rev,dk=dk,df=df10,f=10e9,kind='process',tol=.05,method='IPC-TM-650 2.5.5.5',direction='Z',temp=23,copper='Df: LoPro Reverse Treated EDC Foil',notes='Table values; source prose at p1 differs for RO4730G3 2.5 GHz loss tangent.')
 typical(sid,material,2,rev,df=df25,f=2.5e9,method='IPC-TM-650 2.5.5.5',direction='Z',copper='LoPro Reverse Treated EDC Foil',notes='RO4730G3 value 0.0028 occupies a merged table cell across both frequency rows; p1 prose says 0.0022 at 2.5 GHz. Treat as source inconsistency requiring vendor confirmation before use.' if material=='RO4730G3' else None)
 typical(sid,material,2,rev,dk=design,fmin=1.7e9,fmax=5e9,kind='design',method='Differential Phase Length',direction='Z',notes='Design Dk averages tested lots and common thicknesses.')
mark(sid,'representative_dielectric_points_complete_with_source_conflict','All dielectric table entries transcribed. RO4730G3 2.5 GHz Df conflict between p1 prose and merged p2 cell is retained and flagged.')
ISSUES.append({'source_id':'ROGERS_RO47_DS','issue':'RO4730G3 2.5 GHz Df source inconsistency','pdf_physical_pages':[1,2],'prose_p1_df':.0022,'table_p2_merged_cell_df':.0028,'action':'Dataset uses the explicit property table and marks the record for vendor confirmation. No silent reconciliation.'})
sid='AGC_TLY5_DS';rev='No explicit issue date found on acquired 2-page data sheet'
typical(sid,'TLY-5',2,rev,dk=2.20,df=.0009,f=10e9,tol=.02,method='IPC-650 2.5.5.5 (source notation)',notes='This is the p2 typical-value row. P1 offers Dk 2.17–2.40 selectable for most thicknesses; those options are not assumed to have the same Df or tolerances without ordering data.')
mark(sid,'representative_dielectric_points_complete','10 GHz typical Dk/Df/tolerance extracted; selectable Dk range retained as a qualification, not a list of measured points.')
sid='DUPONT_PYRALUX_AP';rev='EI-10124 (2/25); copyright 2025'
for f,dk,df,method in [(1e6,3.4,.002,'IPC-TM-650 2.5.5.3'),(10e9,3.2,.003,'ASTM D2520')]:
 typical(sid,'Pyralux AP9121',2,rev,dk=dk,df=df,f=f,method=method,material_form='flex laminate',construction='AP9121',notes='Table 3 explicitly says AP9121 Typical Value. Do not transfer these points to every Pyralux AP construction.')
mark(sid,'representative_dielectric_points_complete','AP9121-only Table 3 points at 1 MHz and 10 GHz; other AP offerings are geometry options, not measured RF points.')
sid='ISOLA_ASTRA_DS';rev='Revision D; updated September 17, 2025'
for f in [2e9,10e9]:typical(sid,'Astra MT77',3,rev,dk=3.0,df=.0017,f=f,method='IPC-TM-650 2.5.5.5',dfmethod='Bereskin Stripline',notes='Generic representative table, distinct from construction-specific HTML revision C. No individual construction is specified.')
mark(sid,'representative_dielectric_points_complete','Generic 2/10 GHz values; construction-specific data are separately sourced to ISOLA_ASTRA_DKDF.')
sid='ISOLA_FR408HR_DS';rev='Revision F; updated March 24, 2026'
for f,dk,df,method in [(1e8,3.72,.0072,'IPC-TM-650 2.5.5.3'),(1e9,3.69,.0091,'IPC-TM-650 2.5.5.9'),(2e9,3.68,.0092,'Bereskin Stripline'),(5e9,3.64,.0098,'Bereskin Stripline'),(10e9,3.65,.0095,'Bereskin Stripline')]:
 typical(sid,'FR408HR',3,rev,dk=dk,df=df,f=f,method=method,notes='Generic representative table; no construction given. Construction-specific HTML is a separate revision G and must be preferred when selecting a real stackup.')
mark(sid,'representative_dielectric_points_complete','Five exact frequencies from generic table; not conflated with HTML construction values.')
ISSUES.append({'source_id':'PAPER-065','issue':'Cross-reference supplied by geometry extraction: source paper reports tan delta 0.018 on physical p2 but 0.18 at 1 GHz in Djordjevic-Sarkar description on p3.','action':'No paper-derived generic FR-4 point is imported into this manufacturer dataset. Preserve the paper conflict in geometry evidence.'})



# Anisotropy experiment: these samples are not interchangeable with production Z-Dk.
sid='ROGERS_ISOTROPY';rev='Revised 1614 081122; Publication 92-607; 2022'
for direction,mm,inch,dk1,dk10,df1,df10 in [('X',1.58,.0622,2.428,2.452,.0014,.0023),('Y',1.53,.0604,2.430,2.432,.0009,.0024),('Z',1.60,.0631,2.330,2.347,.0005,.0016)]:
 for f,dk,df,method in [(1e6,dk1,df1,'ASTM D1531'),(10e9,dk10,df10,'ASTM D3380; stripline resonator (approximately 10 GHz)')]:
  rr=typical(sid,'RT/duroid 5870 experimental laminated block',1,rev,dk=dk,df=df,f=f,method=method,direction=direction,thickness_mm=mm,thickness_inch=inch,thickness_basis='orientation-specific test slice',construction='Block built from thin laminating stock; slices ground perpendicular to the test field axis',notes='Measured experimental block, not a production-grade dielectric tensor guarantee. 10 GHz is approximate per p2 methods discussion. Frequency and method are kept separately for each axis.')
  ROWS[-1]['data_scope']='experimental_anisotropy_sample';ROWS[-1]['value_status']='reported_experimental_sample'
mark(sid,'experimental_anisotropy_points_extracted','Table 1: X/Y/Z block specimen Dk/Df at 1 MHz and approximately 10 GHz, including specimen thickness. Figure 1 curves are not digitized.')

AUXILIARY=[]
def aux(sid,kind,page,data,note,locator=None):
 ss=src(sid);loc=locator or f'PDF physical page {page}'
 eid=evidence(sid,loc,data,'pdf_table_coordinate_extraction',pdf_physical_page=page)
 AUXILIARY.append({'source_id':sid,'source_sha256':ss['source_sha256'],'source_revision':ss['source_revision'],'source_filename':ss['source_filename'],'source_url':ss['source_url'],'kind':kind,'source_locator':loc,'evidence_id':eid,'data':data,'notes':note})

sid='ROGERS_COPPER_FOIL';src(sid)['source_revision']='Revised 1530 081826; Publication 92-243; copyright 2021 (as printed)'
doc=fitz.open(src(sid)['path']);a=doc[3].find_tables().tables[0].extract();lasttype=products=None
for ri,row in enumerate(a[2:],3):
 if row[0]:lasttype=norm(row[0])
 if row[4]:products=norm(row[4])
 weight=norm(row[1]);m=re.search(r'\((\d+)\s*mm\)',weight)
 data={'foil_type':lasttype,'weight_and_thickness_original_text':weight,'copper_thickness_um':int(m[1]) if m else None,'sq_dielectric_side_um':num(row[2]) if row[2]!='-' else None,'sq_top_side_um':num(row[3]) if row[3]!='-' else None,'applicable_products_original':products}
 aux(sid,'copper_surface_roughness',4,data,'The rendered original prints micrometres (µm); PDF text maps the glyph to mm. Units were visually verified. Sq is RMS areal roughness, not Ra/Rz and not directly a Huray sphere radius. Dash means unreported, not zero. Products column contains explicit product/foil limitations and must be read before selecting.',f'PDF physical page 4, Table 1, data row {ri-2}')
mark(sid,'copper_roughness_table_extracted','All 32 Table 1 foil/weight/product-group rows stored in material_auxiliary.json. No dielectric-point rows because this is a conductor surface data source; model figures and peel-strength Table 2 not numerically transcribed.')

sid='ROGERS_RO3003G2_DS';doc=fitz.open(src(sid)['path'])
for ti,t in enumerate(doc[2].find_tables().tables,1):
 a=t.extract()
 if a and 'Foil' in (a[0][0] or ''):
  for ri,row in enumerate(a[1:],2):
   data={'foil_weight_original':row[0],'sa_um':num(row[1]),'sz_um':num(row[2]),'sq_um':num(row[3]),'surface_area_index':num(row[4])}
   aux(sid,'copper_surface_roughness',3,data,'Use the product-specific VLP ED foil table. These metrics are not interchangeable; the source does not provide a full Huray model.',f'PDF physical page 3, foil roughness table {ti}, data row {ri-1}')

for sid in ['ROGERS_RO3000_DS','ROGERS_RO4000_DS','ROGERS_DUROID_DS','ROGERS_RO47_DS','ROGERS_RO3003G2_DS','ROGERS_RO3000_BONDPLY']:
 doc=fitz.open(src(sid)['path'])
 for i,page in enumerate(doc):
  for ti,t in enumerate(page.find_tables().tables,1):
   a=t.extract();header=' '.join(v or '' for v in a[0])
   if 'Standard Thickness' in header:
    aux(sid,'standard_construction_and_cladding_options',i+1,{'headers':a[0],'rows':a[1:]},'Original text and tolerances retained. These are ordering options, not a guarantee that one representative Dk/Df applies unchanged to every thickness. PDF font extraction can map micro symbols to m; consult the original for ambiguous unit glyphs.',f'PDF physical page {i+1}, standard thickness/panel/cladding table {ti}')

SUPPORT_NOTES={
'ROGERS_RO47_FAB':('fabrication_guidance_retained','Fabrication process guide for RO47xx laminates. Relevant to drilling, copper preparation and lamination; not an independent frequency/construction Dk/Df data table. No process-temperature/rate rows transcribed into the dielectric-point schema in this release.'),
'ROGERS_PIM_ANTENNAS':('pim_validation_guidance_retained','Passive-intermodulation guidance for PCB antennas. Relevant to conductor/finish/assembly and PIM verification; PIM response cannot be encoded as substrate Dk/Df. No graph digitization performed.'),
'ROGERS_MATERIAL_SELECTOR':('selection_guide_retained_not_fully_transcribed','13-page broad material selection guide. Product-family comparison data overlap dedicated sheets; only the dedicated grade sheets are normalized in this release. Other selector-only products and auxiliary thermal/mechanical comparisons remain in the source and are not claimed extracted.'),
'ROGERS_RO3000_FAB':('fabrication_guidance_retained','RO3000/RO3200 fabrication guide. Use for processing and surface preparation; dielectric numeric catalog is sourced to grade data sheets. Fabrication process recipes have not been converted to a machine-executable manufacturing specification.'),
'ROGERS_DUROID_FAB':('fabrication_guidance_retained','RT/duroid fabrication guide. Relevant to soft PTFE laminate handling and processing; dielectric values are taken from the dedicated RT/duroid data sheet. Process recipes are retained in original form.'),
'ROGERS_STRIPLINE_WIDTH':('transmission_line_guidance_retained','Centered-stripline impedance/width reference. Describes feed-line geometry rather than material-specific measured dispersion; not imported as antenna radiator dimensions or dielectric measurements.'),
'ROGERS_STRIPLINE_EQ':('transmission_line_guidance_retained','Broadside/edgewise stripline equations. Relevant to feed/coupling models; no measured manufacturer material points extracted. Formula-domain validation belongs to the geometry/model stage.'),
'AGC_TLY5_FAB':('fabrication_guidance_retained','12-page TLY-5 processing guide. Original process recommendations retained; frequency-dependent permittivity/loss is taken from the technical data sheet. No automatic transfer of fabrication recipes to arbitrary PCB shops.')}
for sid,(status,note) in SUPPORT_NOTES.items():mark(sid,status,note)

def finish():
 # Join Dk and Df only when source, exact grade, geometry and frequency match.
 # Include data_scope and dk_kind so process and design Dk are never collapsed.
 merged=collections.OrderedDict()
 idfields=['source_id','material','material_form','data_scope','construction','glass_style','glass_type','ply_count','resin_content_percent','core_type','core_label','prepreg_label','thickness_mm','thickness_inch','thickness_mil','thickness_um','thickness_basis','nominal_thickness_mm','nominal_thickness_mil','frequency_hz','frequency_min_hz','frequency_max_hz','dk_kind','direction','test_condition','temperature_c','copper_condition']
 for r in ROWS:
  key=tuple(r[k] for k in idfields)
  if key not in merged:merged[key]=r;continue
  old=merged[key]
  for prop in ['dk','df','dk_tolerance_abs','dk_test_method','df_test_method']:
   if old[prop] is not None and r[prop] is not None and old[prop]!=r[prop]:raise ValueError('conflicting same-condition point '+str(key)+' '+prop)
   if old[prop] is None:old[prop]=r[prop]
  old['evidence_ids']=list(dict.fromkeys(old['evidence_ids']+r['evidence_ids']))
  if r['source_locator'] not in old['source_locator']:old['source_locator']+='; '+r['source_locator']
 rows=list(merged.values())
 for i,r in enumerate(rows,1):
  r['record_id']=f'MAT-{i:05d}'
  flags=[];review=False
  if r['data_scope']=='representative_property':flags.append('representative_value_not_construction_specific')
  if r['dk_kind']=='design':flags.append('design_dk_not_process_dk')
  if r['frequency_hz'] is None:flags.append('frequency_range_average_not_sampled_dispersion')
  if r['source_id'].startswith('ISOLA_') and r['data_scope']=='construction_specific':flags.append('measurement_method_not_restated_in_construction_table')
  if r['availability']=='under_development_as_of_source_revision':flags.append('manufacturer_marks_construction_under_development');review=True
  if r['source_id']=='ROGERS_RO47_DS' and r['material']=='RO4730G3' and r['frequency_hz']==2.5e9:flags.append('conflicting_source_values_vendor_confirmation_required');review=True
  if r['data_scope']=='experimental_anisotropy_sample':flags.append('experimental_block_sample_not_production_tensor');review=True
  if r['data_scope']=='experimental_anisotropy_sample' and r['frequency_hz']==10e9:flags.append('frequency_approximately_10GHz')
  if r['source_id']=='PANASONIC_R_5725S' and r['material']=='R-5620S' and r['glass_style']=='1080' and r['resin_content_percent']==67 and r['frequency_hz']==1e6:flags.append('source_decimal_comma_normalized_3comma56_to_3point56')
  r['record_flags']=flags;r['requires_review']=review
  assert r['dk'] is not None or r['df'] is not None
  assert r['source_sha256'] and r['evidence_ids']
  if r['dk'] is not None:assert 1<r['dk']<100, r
  if r['df'] is not None:assert 0<=r['df']<1
  if r['frequency_hz'] is not None:assert r['frequency_hz']>0
  if r['frequency_hz'] is None:assert r['frequency_min_hz'] and r['frequency_max_hz']
 for c in CAT.values():
  if c.get('collection_group')=='materials':src(c['id'])
 counts=collections.Counter(r['source_id'] for r in rows)
 auxcounts=collections.Counter(r['source_id'] for r in AUXILIARY)
 for sid,s in SOURCE.items():
  s['numeric_record_count']=counts[sid]
  s['auxiliary_record_count']=auxcounts[sid]
  if s['coverage_status']=='not_yet_extracted':
   s['coverage_status']='supporting_document_no_numeric_points_extracted'
   s['coverage_note']='Retained in corpus for fabrication, anisotropy, copper, impedance or selection guidance. No condition-specific dielectric point transcribed in this release.'
  s.pop('path',None)
 expected_counts={'ISOLA_ASTRA_DKDF':70,'ISOLA_FR408HR_DKDF':264,'PANASONIC_R_579Y':270,'PANASONIC_R_5795':270,'PANASONIC_R_5785_G__new':372,'PANASONIC_R_5785_N__new':222,'PANASONIC_R_5775__50GHz_new':450,'PANASONIC_R_5725S':528,'PANASONIC_R_1755V':312,'PANASONIC_R_1766_GH_':184,'PANASONIC_R_5775_N__new':168}
 for sid,expected in expected_counts.items():assert counts[sid]==expected,(sid,counts[sid],expected)
 assert all(r['dk'] is not None and r['df'] is not None for r in rows if r['data_scope']=='construction_specific'), 'Unpaired construction Dk/Df indicates a missing table cell or condition-key mismatch'
 assert len(AUXILIARY)==41
 assert len(SOURCE)==31
 # Scope checksum: this detects incomplete table parsing after library/layout changes.
 assert sum(1 for r in rows if r['requires_review'])==27
 metadata={'schema_version':'1.0.0','row_semantics':'One exact material construction and condition per frequency; Dk/Df combined only when conditions match. Frequency-range design Dk uses min/max and a null point frequency.','unit_policy':'Hz, mm and dimensionless relative permittivity/loss tangent; printed original thickness units preserved; only explicit um-to-mm conversion is performed.','review_flag_policy':'requires_review marks source conflict, development-only availability or experimental-block transfer. False does not validate an antenna design or make representative values construction-specific. record_flags preserve other qualifications.','missing_value_policy':'JSON null / blank CSV is unknown or not applicable. It is not zero.','scientific_limitations':['Manufacturer typical values are not guaranteed stackup properties.','No interpolation, extrapolation or material/grade substitution is performed.','The material must be selected by exact construction, resin content and test method; FR-4 is not assigned a universal permittivity.','Copper roughness, anisotropy, cured thickness and solder mask need separate models or measurements where not specified.','Design Dk and process Dk are separate records.','Original PDF physical page numbers are 1-based; HTML table indices in locators are 1-based.'],'record_count':len(rows),'source_count_with_dielectric_points':sum(v>0 for v in counts.values()),'records':rows}
 auxflat=[]
 for r in AUXILIARY:
  flat={k:v for k,v in r.items() if k!='data'};flat.update(r['data']);auxflat.append(flat)
 auxfields=list(dict.fromkeys(k for r in auxflat for k in r))
 with (OUT/'material_auxiliary.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=auxfields);w.writeheader()
  for r in auxflat:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})
 with (OUT/'material_coverage.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(next(iter(SOURCE.values())).keys()));w.writeheader();w.writerows(SOURCE.values())
 (OUT/'material_auxiliary.json').write_text(json.dumps({'schema_version':'1.0.0','records':AUXILIARY},ensure_ascii=False,indent=2)+'\n')
 (OUT/'materials.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
 with (OUT/'materials.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader()
  for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})
 ev={'schema_version':'1.0.0','source_coverage':list(SOURCE.values()),'auxiliary_record_count':len(AUXILIARY),'table_coverage':TABLES,'issues':ISSUES,'quality_checks':{'source_hashes_checked_against_catalog_when_available':True,'isola_construction_counts':{'Astra':70,'FR408HR':264},'point_ranges_and_nonmissing_provenance_checked':True,'conflicting_same_condition_points_rejected':True,'no_interpolation_or_extrapolation':True,'all_31_material_sources_accounted_for':True,'all_construction_points_have_paired_dk_df':True,'source_revisions_pinned_by_sha256':True,'panasonic_isola_expected_record_counts':expected_counts,'review_required_records':sum(r['requires_review'] for r in rows)},'evidence':EVIDENCE}
 (OUT/'material_evidence.json').write_text(json.dumps(ev,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'records':len(rows),'sources':sum(v>0 for v in counts.values()),'per_source':counts,'tables':len(TABLES),'evidence':len(EVIDENCE)},ensure_ascii=False,indent=2))

if __name__=='__main__':finish()
