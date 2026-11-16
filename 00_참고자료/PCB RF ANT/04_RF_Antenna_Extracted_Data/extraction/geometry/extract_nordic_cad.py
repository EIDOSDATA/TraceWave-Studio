#!/usr/bin/env python3
"""Extract a small, auditable subset of PCA20006 1.0.0 Gerber geometry.

Not a general Gerber renderer. Exact drawing commands are retained and checked.
No electrical net connectivity or stackup is inferred from Gerber colours.
"""
import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def extract():
    catalog={r['id']:r for r in json.loads((ROOT/'package/catalog.json').read_text())['records']}
    source=catalog['NORDIC_PCA20006_CAD']
    outer=zipfile.ZipFile(ROOT/'package'/source['relative_path'])
    inner_name=outer.namelist()[0]
    inner=zipfile.ZipFile(io.BytesIO(outer.read(inner_name)))
    selected={}
    for name in inner.namelist():
        short=Path(name).name
        if short in ['400059.GTL','400059.GBL','400059.GM1','PCA20006_Schematic_And_PCB.pdf']:
            selected[short]={'archive_member':name,'sha256':hashlib.sha256(inner.read(name)).hexdigest(),'bytes':inner.read(name)}
    lines={k:v['bytes'].decode().splitlines() for k,v in selected.items() if k.endswith(('.GTL','.GBL','.GM1'))}
    for k in lines:
        assert '%FSLAX24Y24*%' in lines[k] and '%MOIN*%' in lines[k] and 'G75*' in lines[k]
    gtl=lines['400059.GTL']
    assert '%ADD10C,0.0500*%' in gtl
    command='X-2774Y-2279I1042J-3436D01*'
    index=gtl.index(command)
    assert gtl[index-1]=='G03*' and gtl[index-2]=='X-1042Y3436D02*' and gtl[index-3]=='D10*'
    assert 'X-2744Y-2300D02*' in gtl and 'X-1990D01*' in gtl
    gm=lines['400059.GM1']
    assert 'X995Y3809D02*' in gm and 'X-2280Y-3210I-995J-3809D01*' in gm
    # FSLAX24 and MOIN: signed integer coordinates in 1e-4 inch units.
    unit=25.4/10000
    start=(-1042*unit,3436*unit);end=(-2774*unit,-2279*unit)
    center=(0.,0.)
    radius=math.hypot(*start);endradius=math.hypot(*end)
    a0=math.degrees(math.atan2(start[1],start[0]));a1=math.degrees(math.atan2(end[1],end[0]))
    sweep=(a1-a0)%360
    board_radius=math.hypot(995*unit,3809*unit)
    stub_start=(-2744*unit,-2300*unit);stub_end=(-1990*unit,-2300*unit)
    loc=lambda name,first,last:{'archive_member':selected[name]['archive_member'],'member_sha256':selected[name]['sha256'],
                               'gerber_line_start':first,'gerber_line_end':last,'coordinate_format':'FSLAX24Y24; MOIN; G75'}
    evidence_arc=loc('400059.GTL',index-2,index+1)
    evidence_width=loc('400059.GTL',gtl.index('%ADD10C,0.0500*%')+1,gtl.index('%ADD10C,0.0500*%')+1)
    stub_i=gtl.index('X-2744Y-2300D02*')
    evidence_stub=loc('400059.GTL',stub_i+1,stub_i+2)
    bm=gm.index('X995Y3809D02*')
    evidence_board=loc('400059.GM1',bm+1,bm+3)
    inner_i=gtl.index('X0Y2343D02*')
    evidence_inner=loc('400059.GTL',inner_i,inner_i+3)
    gb=lines['400059.GBL'];gb_i=gb.index('X-2351Y0D01*')
    evidence_bottom=loc('400059.GBL',gb_i+1,gb_i+1)
    facts=[]
    def q(name,value,unit,symbol,evidence,derived=False,condition=''):
        facts.append({'name':name,'value':value,'unit':unit,'source_symbol':symbol,'cad_evidence':evidence,
                      'derivation_status':'computed_from_exact_cad_coordinates' if derived else 'exact_cad_coordinate_or_aperture',
                      'condition':condition})
    q('arc_center_x',0,'mm','Xstart+I',evidence_arc,True)
    q('arc_center_y',0,'mm','Ystart+J',evidence_arc,True)
    q('arc_start_x',start[0],'mm','X-1042',evidence_arc)
    q('arc_start_y',start[1],'mm','Y3436',evidence_arc)
    q('arc_end_x',end[0],'mm','X-2774',evidence_arc)
    q('arc_end_y',end[1],'mm','Y-2279',evidence_arc)
    q('arc_trace_width',1.27,'mm','ADD10C,0.0500 inch',evidence_width)
    q('arc_centerline_radius',radius,'mm','hypot(I=1042,J=-3436)*0.00254',evidence_arc,True,'Use start-center radius; endpoint quantization produces 0.001041 mm discrepancy.')
    q('arc_start_angle',a0,'degree','atan2(3436,-1042)',evidence_arc,True,'Measured CCW from +X in native Gerber coordinates.')
    q('arc_ccw_sweep',sweep,'degree','G03 start/end/center',evidence_arc,True)
    q('arc_centerline_length_only',radius*math.radians(sweep),'mm','r*sweep_radians',evidence_arc,True,'Arc only; not total electrical path or full radiator including feed stub/pads.')
    q('feed_stub_start_x',stub_start[0],'mm','X-2744',evidence_stub)
    q('feed_stub_start_y',stub_start[1],'mm','Y-2300',evidence_stub)
    q('feed_stub_end_x',stub_end[0],'mm','X-1990',evidence_stub)
    q('feed_stub_end_y',stub_end[1],'mm','modal Y-2300',evidence_stub)
    q('feed_stub_centerline_length',abs(stub_end[0]-stub_start[0]),'mm','abs(-1990+2744)*0.00254',evidence_stub,True,'Stroke overlaps the arc end; centerline endpoints are not coincident.')
    q('body_reference_arc_radius',board_radius,'mm','hypot(995,3809)*0.00254',evidence_board,True,'One GM1 outline arc. Whole outline includes tabs and connector extension.')
    q('body_reference_circle_diameter',2*board_radius,'mm','2*body_reference_arc_radius',evidence_board,True,'Approximately 20 mm body; not the full board bounding box.')
    q('adjacent_top_copper_arc_centerline_radius',2343*unit,'mm','GTL D11 start X0Y2343',evidence_inner,True,'Copper arc only; Gerber has no electrical net labels, so its net is not independently reconstructed.')
    q('adjacent_top_copper_arc_width',.006*25.4,'mm','ADD11C,0.0060 inch',loc('400059.GTL',gtl.index('%ADD11C,0.0060*%')+1,gtl.index('%ADD11C,0.0060*%')+1))
    q('bottom_copper_boundary_point_x',-2351*unit,'mm','X-2351Y0D01',evidence_bottom,False,'Single exact polygon vertex, not a fitted global ground radius.')
    q('bottom_copper_boundary_point_y',0,'mm','X-2351Y0D01',evidence_bottom)
    q('gerber_coordinate_step',unit,'mm','4 fractional inch digits',loc('400059.GTL',1,2))
    # Native PDF electrical evidence is nested in the same ZIP.
    pd=selected['PCA20006_Schematic_And_PCB.pdf']
    import fitz
    doc=fitz.open(stream=pd['bytes'],filetype='pdf')
    pdf_ev={'archive_member':pd['archive_member'],'member_sha256':pd['sha256'],'embedded_physical_pdf_page':1,'embedded_pdf_page_count':len(doc)}
    assert '1.0.0' in doc[0].get_text() and '2.2nH' in doc[0].get_text() and '1.2pF' in doc[0].get_text()
    facts.extend([
        {'name':'series_matching_inductance','value':2.2,'unit':'nH','source_symbol':'L1','cad_evidence':pdf_ev,'derivation_status':'embedded_pdf_reported','condition':'Series from RF node to ANT in this revision only; not a universal value.'},
        {'name':'shunt_matching_capacitance','value':1.2,'unit':'pF','source_symbol':'C4','cad_evidence':pdf_ev,'derivation_status':'embedded_pdf_reported','condition':'RF node to ground before L1; BAL-NRF02D3 balun is upstream.'},
    ])
    report={'source_id':'NORDIC_PCA20006_CAD','hardware_revision':'1.0.0','pcb':'400059','inner_zip_member':inner_name,
            'arc':{'center_mm':center,'start_mm':start,'end_mm':end,'radius_mm':radius,'trace_width_mm':1.27,'start_angle_deg':a0,'ccw_sweep_deg':sweep},
            'numeric_facts':facts,
            'qa':{'command_checks_passed':True,'arc_endpoint_radius_difference_mm':abs(radius-endradius),'coordinate_step_mm':unit,
                  'endpoint_radius_difference_less_than_one_coordinate_step':abs(radius-endradius)<unit,
                  'reference_pdf_visual_crosscheck':'Physical p.2 top copper shows arc open at top and connected to L1-side stub at bottom; p.3 shows bottom copper keepout.',
                  'electrical_or_em_validation':False},
            'embedded_reference_pdf':{'archive_member':pd['archive_member'],'sha256':pd['sha256'],'page_count':len(doc),'pages_used':[1,2,3]},
            'limitations':['Partial CAD extraction, not a whole-board netlist reconstruction.','No board thickness/Dk/Df/copper thickness claimed from these Gerbers.',
                           'GM1 has tabs and connector protrusion; only one body reference radius is reported.','No global minimum copper clearance is inferred from one inner arc or polygon vertex.']}
    dest=HERE/'evidence/nordic_cad';dest.mkdir(exist_ok=True)
    (dest/'nordic_cad_geometry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    # Dimensionally exact subset illustration, not a full Gerber view.
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    fig,ax=plt.subplots(figsize=(8,8));ax.set_aspect('equal');ax.grid(alpha=.15)
    th=np.linspace(math.radians(a0),math.radians(a0+sweep),500)
    # Use filled annular sector with circular stroke caps at native endpoints.
    ri=radius-.635;ro=radius+.635
    xs=np.r_[ro*np.cos(th),ri*np.cos(th[::-1])];ys=np.r_[ro*np.sin(th),ri*np.sin(th[::-1])]
    ax.fill(xs,ys,color='#b94823',label='Top radiator copper (GTL D10)')
    for pt in [start,end,stub_start,stub_end]:ax.add_patch(Circle(pt,.635,color='#b94823'))
    ax.fill([stub_start[0],stub_end[0],stub_end[0],stub_start[0]],[-5.842-.635,-5.842-.635,-5.842+.635,-5.842+.635],color='#b94823')
    ax.add_patch(Circle((0,0),board_radius,fill=False,ls='--',color='#4b5f82',label='~20 mm body reference circle (tabs omitted)'))
    th2=np.linspace(math.pi/2,math.atan2(-860,-2179)%(2*math.pi),220)
    ax.plot(2343*unit*np.cos(th2),2343*unit*np.sin(th2),color='#16867a',lw=2,label='Adjacent top copper arc; net not reconstructed')
    ax.plot([0,start[0]],[0,start[1]],':',color='#b94823');ax.plot(0,0,'+',color='black')
    ax.annotate('Open tip',xy=start,xytext=(-.3,9),arrowprops={'arrowstyle':'->'})
    ax.annotate('Feed stub toward L1',xy=stub_end,xytext=(-2,-7.4),arrowprops={'arrowstyle':'->'})
    ax.text(.9,4.8,f'Arc radius: {radius:.5f} mm\nWidth: 1.270 mm\nCCW sweep: {sweep:.5f}°\nArc-only length: {radius*math.radians(sweep):.5f} mm',fontsize=10)
    ax.set(xlim=(-11,11),ylim=(-11,11),xlabel='Native Gerber X (mm)',ylabel='Native Gerber Y (mm)',title='Nordic PCA20006 / PCB400059 rev 1.0.0\nAudited geometry subset — no photo scaling')
    ax.legend(loc='lower center',fontsize=7.7);fig.tight_layout()
    fig.savefig(dest/'nordic_arc_dimensions.png',dpi=160);fig.savefig(dest/'nordic_arc_dimensions.svg');plt.close(fig)
    return report


if __name__=='__main__':
    r=extract();print(json.dumps({'numeric_facts':len(r['numeric_facts']),'arc':r['arc'],'qa':r['qa']},ensure_ascii=False))
