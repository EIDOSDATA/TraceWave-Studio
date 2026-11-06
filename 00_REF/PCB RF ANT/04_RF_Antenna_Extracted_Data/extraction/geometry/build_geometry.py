#!/usr/bin/env python3
"""Rebuild the manually verified first-pass geometry extraction.

The numeric facts below were read from the cited physical PDF pages. This
script does not calculate an antenna solution, digitize unlabelled graphics,
or certify any published performance. Source documents remain authoritative.
"""
from __future__ import annotations

import csv
import hashlib
import json
import io
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CATALOG = {r['id']: r for r in json.loads((ROOT / 'package/catalog.json').read_text())['records']}
UPLOADS = {'PAPER-059': 'liang2005.pdf', 'PAPER-063': 'jianxinliang2005.pdf', 'PAPER-065': 'verma2014.pdf'}
GEOMETRIES = []


def ev(page, locator, note=''):
    return {'physical_pdf_page': page, 'locator': locator, 'note': note}


def p(name, symbol, value, unit, page, locator, category='geometry', condition='', method='text_or_table'):
    return {'name': name, 'source_symbol': symbol, 'value': value, 'unit': unit,
            'category': category, 'physical_pdf_page': page, 'locator': locator,
            'condition': condition, 'extraction_method': method,
            'evidence_status': 'source_reported'}


def dims(items, page, locator, condition='', method='text_or_table'):
    """Raw source symbols preserve the drawing's own parameter naming."""
    return [p(k, k, v, 'mm', page, locator, condition=condition, method=method) for k, v in items.items()]


def fact(value, page, locator, note=''):
    return {'value': value, 'evidence': ev(page, locator, note)}


def add(gid, sid, title, topology, pages, params, *, target=None, bands=None,
        substrate=None, ground=None, feed=None, keepout=None, applicability=None,
        validation=None, status='dimensioned_reference', missing=None, conflicts=None,
        equations=None, notes=None):
    r = CATALOG[sid]
    rel = r.get('relative_path')
    path = ROOT / 'package' / rel if rel else ROOT.parent / 'upload' / UPLOADS[sid]
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    image_evidence = [f'evidence/{sid}_p{q:03}.png' for q in sorted(set(e['physical_pdf_page'] for e in pages))
                      if (HERE / f'evidence/{sid}_p{q:03}.png').exists()]
    GEOMETRIES.append({
        'geometry_id': gid, 'source_id': sid, 'source_title': r['title'],
        'variant_title': title, 'topology': topology,
        'source_relative_path': rel or f'USER_UPLOAD_PENDING_INTEGRATION/{UPLOADS[sid]}',
        'source_sha256': checksum, 'source_doi': r.get('doi'),
        'source_url': r.get('source_url'), 'source_evidence': pages,
        'target_frequency_hz': target, 'target_bands_hz': bands or [],
        'parameters': params, 'substrate': substrate or {}, 'ground': ground or {},
        'feed_and_matching': feed or [], 'keepout': keepout or [],
        'applicability': applicability or [], 'source_reported_validation': validation or [],
        'extraction_status': status, 'performance_verification': 'source_reported_only',
        'independent_em_or_measurement_performed': False,
        'automatic_cad_generation_ready': False,
        'missing_information': missing or [], 'source_conflicts': conflicts or [],
        'equations': equations or [], 'notes': notes or [], 'rendered_evidence': image_evidence,
    })


# Nordic: a theoretical starting length, explicitly not a tuned production layout.
add('G001', 'NORDIC_NWP008', '2.45 GHz quarter-wave printed monopole starting geometry',
    'straight_monopole', [ev(1, '§3'), ev(2, '§3–4'), ev(3, 'Figure 1 / tuning')],
    [p('trace_length_estimate', 'L', 23, 'mm', 1, '§3', condition='Approximate initial estimate; retune in final assembly'),
     p('trace_width', 'W', 1.5, 'mm', 1, '§3'),
     p('substrate_thickness', '1.6mm', 1.6, 'mm', 1, '§3', 'substrate'),
     p('relative_permittivity', 'εr', 4.4, '1', 1, '§3', 'substrate', 'Typical at 2.45 GHz'),
     p('prototype_length_extension_near_ideal_ground', 'about 20%', 20, '%', 2, '§3', 'tuning'),
     p('prototype_length_extension_small_ground_or_edge', 'about 30%', 30, '%', 2, '§3', 'tuning'),
     p('open_tip_ground_clearance_preferred', 'd', 10, 'mm', 2, '§4', 'keepout', 'Preferably >=10 mm for bent trace')],
    target=2.45e9, substrate={'material': fact('FR4', 1, '§3')},
    ground={'dependency': fact('Ground-plane dependent; ideal plane extends at least a quarter wavelength around feed.', 1, '§2')},
    feed=[fact('Single-ended feed; nRF24xx differential ANT1/ANT2 requires device-specific differential-to-single-ended matching.', 2, '§4')],
    keepout=[fact('No ground under trace on any PCB layer; keep components and other traces away.', 2, '§4')],
    applicability=[fact('Case material, ground size, trace width/thickness and body loading change tuning; length is not a universal FR4 constant.', 1, '§2')],
    validation=[fact('Trim prototype; tune inside final case and handheld/body-worn state. Use VNA impedance/SWR for accurate tuning.', 3, 'tuning')],
    status='analytical_starting_point', missing=['Exact ground outline and tuned production length.'])

add('G002', 'TI_AN043_SWRA117', 'CC2511 USB meandered IFA', 'meandered_ifa',
    [ev(1, 'Introduction'), ev(3, '§4'), ev(4, 'Figure 3 / Table 1'), ev(5, '§5.1')],
    dims({'L1':3.94,'L2':2.70,'L3':5.00,'L4':2.64,'L5':2.00,'L6':4.90,
          'W1':0.90,'W2':0.50,'D1':0.50,'D2':0.30,'D3':0.30,'D4':0.50,'D5':1.40,'D6':1.70},4,'Figure 3 / Table 1')+
    [p('footprint_width','15.2 x 5.7 mm',15.2,'mm',1,'Introduction'),p('footprint_height','15.2 x 5.7 mm',5.7,'mm',1,'Introduction')],
    target=2.45e9, substrate={'material_and_thickness':fact('Must use associated reference-design readme; this note does not give a numerical stackup.',4,'§4.3')},
    feed=[fact('Designed to present 50 Ω at 2.45 GHz with no additional matching in the reference.',3,'§4')],
    applicability=[fact('Copy reference Gerber/DXF and compare overlay; thickness changes can require length adjustment.',4,'§4.3')],
    validation=[fact('IE3D simulation compared with measured reflection.',3,'Figure 2'),fact('Semi-rigid measurement cable placement shifted resonance 5–10 MHz and reflection 3–4 dB on the small ground plane.',5,'§5.1')],
    missing=['Associated CC2511 reference stackup must be linked before automated reproduction.'])

add('G003','TI_DN007_SWRU120','CC2430DB 2.4 GHz IFA','ifa',
    [ev(2,'Figure 1-1 / Table 1-1 / §1'),ev(3,'§2')],
    dims({'H1':5.70,'H2':0.74,'H3':1.29,'H4':2.21,'H5':0.66,'H6':1.21,'H7':0.80,'H8':1.80,'H9':0.61,
          'W1':1.21,'W2':0.46,'L1':25.58,'L2':16.40,'L3':2.18,'L4':4.80,'L5':1.00,'L6':1.00,'L7':3.20,'L8':0.45},2,'Figure 1-1 / Table 1-1')+
    [p('substrate_thickness','1-mm thickness',1,'mm',2,'§1','substrate')],
    target=2.4e9, substrate={'material':fact('Standard FR-4; epsilon_r not specified in this section.',2,'§1')},
    feed=[fact('50 Ω on reference board; provision pi network near feed because surroundings and stackup change impedance.',2,'§1')],
    keepout=[fact('Keep ground and components away from antenna ends when PCB is wider.',2,'§1')],
    validation=[fact('Radiation measurements on CC2430DB, CC2430 programmed to 0 dBm.',3,'§2.1')],
    missing=['Exact board/ground outline and full stackup require companion CC2430DB CAD.'])

# DN023 supplies a table stock length, a guidance length, and different measured
# example captions. Preserve all three; do not silently choose a universal L6.
dn23base={'L1':20,'L2':5,'L3':4,'L4':10,'L5':6,'L7':43,'X':31,'Y':45,'W':1,'W2':2}
for gid,freq,guide,measured,page,fig in [('G004',868e6,9,11,10,'Figure 12'),('G005',915e6,1,3,11,'Figure 13')]:
    add(gid,'TI_DN023_SWRA228',f'{freq/1e6:g} MHz IFA — preserve tuning-context alternatives','ifa',
        [ev(3,'§3.1'),ev(4,'Figure 2 / Table 1 and paragraph'),ev(page,fig),ev(10,'§4.2')],
        dims(dn23base,4,'Figure 2 / Table 1')+
        [p('L6_table_value','L6',17,'mm',4,'Table 1',condition='Published layout table; frequency-specific guidance and measurement captions separately preserved'),
         p('L6_guidance','L6',guide,'mm',4,'Paragraph after Table 1',condition=f'Approximate {freq/1e6:g} MHz recommendation for 31×45 mm GND'),
         p('L6_measured_example','L6',measured,'mm',page,fig,condition='Caption of radiated-bandwidth measurement'),
         p('substrate_thickness','0.8 mm',0.8,'mm',3,'§3.1','substrate'),
         p('side_clearance_layout_min','minimum 5 mm',5,'mm',3,'§3.1','keepout','PCB wider than antenna'),
         p('side_ground_clearance_measurement_recommendation','15 mm',15,'mm',10,'§4.2','keepout','Ground planes added beside antenna')],
        target=freq,substrate={'material':fact('FR-4',3,'§3.1')},ground={'dimensions_mm':fact([31,45],4,'Figure 2 and paragraph'),'under_antenna':fact('No ground plane beneath antenna.',3,'§3.1')},
        feed=[fact('Approximately 50 Ω; option for one series and two shunt matching components.',3,'§3')],
        applicability=[fact('Ground size/shape changes impedance and pattern; 955 MHz needs further shortening without a precise supplied L6.',4,'paragraph after Table 1')],
        validation=[fact('Radiated-bandwidth example uses stepping CW, spectrum-analyzer max-hold, XY horizontal board, vertically polarized receiving antenna.',10,'§4.3')],
        status='source_conflict_requires_review',
        conflicts=[{'field':'L6','values_mm':[17,guide,measured],'evidence':[ev(4,'Table 1'),ev(4,'paragraph after Table 1'),ev(page,fig)],
                    'resolution':'Not resolved here. Table value, guidance and measurement caption are retained as distinct conditions; do not label any one value universally correct.'}],
        missing=['Reconcile actual prototype trimming and board/ground conditions before selecting a production L6.'])

add('G006','TI_DN024_SWRA227','Board 6 meandering monopole, untrimmed dual-band geometry','meandered_monopole',
    [ev(3,'§3–3.1'),ev(4,'Figure 2 / Table 1'),ev(5,'§4')],
    dims({'L1':9,'L2':18,'L3':3,'L4':38,'L5':1,'Y':43,'X1':63,'X2':25,'W':2},4,'Figure 2 / Table 1')+
    [p('substrate_thickness','1.6 mm',1.6,'mm',3,'§3.1','substrate')],
    bands=[[868e6,868e6],[2.44e9,2.44e9]],substrate={'material':fact('FR4',3,'§3.1'),'metal_layers_used':fact('Antenna on both top and bottom.',3,'§3')},
    ground={'under_antenna':fact('No ground beneath antenna.',3,'§3.1')},
    feed=[fact('Pi matching network recommended; changing substrate or GND requires matching retune.',3,'§3')],
    applicability=[fact('Untrimmed L4 benefits 868/2440 MHz dual band; trim to silk mark for sub-GHz single band. This record does not invent the trim-mark length.',3,'§3'),fact('915/920 MHz possible with retuning.',4,'paragraph after Table 1')],
    validation=[fact('Source contains CTIA OTA/radiation measurements for standalone and EM/EB configurations.',5,'§4.1')],
    missing=['Numerical L4 for single-band silk trim; full via/paired-layer reconstruction from Board 6 CAD.'])

add('G007','TI_DN004_SWRA118','CC2500/CC25xx folded dipole','folded_dipole',
    [ev(1,'Introduction'),ev(3,'Figure 2 / Table 1 / §3'),ev(13,'Table 3')],
    dims({'L1':44.7,'L2':21,'D1':1.5,'D2':0.9,'H1':2.4,'H2':3.1,'H3':6,'H4':2.8},3,'Figure 2 / Table 1')+
    [p('required_footprint_width','46 x 9 mm',46,'mm',1,'Introduction'),p('required_footprint_height','46 x 9 mm',9,'mm',1,'Introduction')],
    target=2.4e9,
    feed=[fact('Direct differential match to listed CC25xx radio impedance; not an interchangeable 50 Ω monopole.',3,'§3'),fact('Keep same chip-to-antenna distance if feed routing changed for CC251x pinout.',3,'§3.1')],
    keepout=[fact('No components/ground near endpoints when board extends beyond antenna.',3,'§3.1')],
    validation=[fact('Source reports gain/range and measured output/harmonics; results apply to source reference configuration.',13,'Tables 2–3')],
    missing=['Stackup and detailed differential radio feed geometry from companion reference CAD.'])

# AN1088 dimensions are inches in the source drawing. Keep native units and an
# explicit conversion in exported CSV, avoiding a mistaken inch/mm import.
for gid,thick,length,gap,height in [('G008',1.5748,.782,.109,.327),('G009',.8,.860,.115,.311)]:
    label='0.062-inch' if gid=='G008' else '0.8-mm'
    a={'horizontal_arm_length':length,'arm_width':.039,'shorting_arm_width':.040,'feed_arm_width':.040,
       'inner_short_feed_gap':gap,'arm_bottom_to_ground':height,'edge_to_shorting_arm':.040,
       'edge_to_radiator':.020,'ground_via_spacing':.050}
    pars=[p(k,k.replace('_',' '),v,'inch',3,'Figure 2.1 '+label+' variant',method='rendered_figure') for k,v in a.items()]
    pars += [p('substrate_thickness','0.062 inch' if gid=='G008' else '0.8 mm',.062 if gid=='G008' else .8,'inch' if gid=='G008' else 'mm',3,'Figure 2.1','substrate'),p('reference_board_width','1-inch-wide',1,'inch',5,'§3.1','ground')]
    add(gid,'SILABS_AN1088',f'2.4 GHz IFA — {label} FR4 variant','ifa',
        [ev(3,'Figure 2.1 / §2.1'),ev(4,'Figure 2.2'),ev(5,'§3.1')],pars,
        target=2.4e9,substrate={'material':fact('FR4; use variant-specific stackup in Figure 2.2.',3,'Figure 2.1'),'soldermask':fact('Antenna should be covered by soldermask.',3,'§2.1')},
        feed=[fact('50 Ω microstrip feed; shorting arm grounded preferably by vias.',3,'§2.1')],
        ground={'under_antenna':fact('No ground below antenna; stitch edge vias (50 mil drawing spacing).',3,'§2.1 / Figure 2.1')},
        applicability=[fact('Optimized for 1-inch board width; other ground dimensions detune match.',5,'§3.1')],
        validation=[fact('Document gives design/simulation/tuning considerations; this extraction did not measure prototype.',3,'§2.1')],
        missing=['Precise multilayer stackup from Figure 2.2 must be imported into EM model; no generic epsilon_r supplied here.'])

add('G010','ST_AN5129','2.4 GHz meander reference Rev 5','meandered_monopole',
    [ev(4,'Figure 2'),ev(5,'Figure 3 / Table 1'),ev(6,'Figures 4–5'),ev(7,'Figures 6–7')],
    [p('antenna_area_substrate_width','19',19,'mm',4,'Figure 2',method='rendered_figure'),
     p('antenna_area_above_ground_height','11',11,'mm',4,'Figure 2',method='rendered_figure'),
     p('trace_width','0,4',.4,'mm',4,'Figure 2',method='rendered_figure'),
     p('meander_clear_gap','0,8',.8,'mm',4,'Figure 2',method='rendered_figure'),
     p('top_open_end_to_right_outer_edge','6,6',6.6,'mm',4,'Figure 2',method='rendered_figure'),
     p('radiator_top_to_ground_edge','6,3',6.3,'mm',4,'Figure 2',method='rendered_figure'),
     p('left_board_edge_to_feed_axis','3,5',3.5,'mm',4,'Figure 2',method='rendered_figure'),
     p('left_outer_meander_edge_to_feed_axis','2,7',2.7,'mm',4,'Figure 2',method='rendered_figure'),
     p('lower_long_meander_bottom_to_ground','2,3',2.3,'mm',4,'Figure 2',method='rendered_figure'),
     p('core_thickness','C',711.2,'um',5,'Table 1','substrate'),
     p('copper_thickness','T',40.64,'um',5,'Table 1','substrate'),
     p('top_soldermask_thickness','S1',17.78,'um',5,'Table 1','substrate'),
     p('bottom_soldermask_thickness','S2',17.78,'um',5,'Table 1','substrate'),
     p('core_and_mask_epsilon_r','ƐR',4.4,'1',5,'Table 1','substrate')],
    target=2.4e9,substrate={'stackup':fact('Core and both masks epsilon_r 4.4 in recommended source table; copper has no dielectric constant entry.',5,'Table 1')},
    feed=[fact('Impedance-matching area shown in Figure 2; direct RF measurement bypasses circuitry in Figure 5.',6,'Figures 4–5')],
    validation=[fact('Source shows complex impedance, S11 and SWR plus radiation patterns.',7,'Figures 6–7')],
    missing=['Absolute ground outline not specified by the antenna-area crop.'])

# ST AN5434 contains overall and principal radiator dimensions, not complete
# coordinates for every bend. These are explicitly partial reconstructions.
for gid,title,topology,page,fig,ant_h,armdims in [
    ('G011','T-shaped monopole','t_monopole',5,'Figure 3',23,{'top_arm_span':27,'vertical_arm':17}),
    ('G012','L-shaped monopole','bent_monopole',8,'Figure 8',23,{'horizontal_arm':14,'vertical_arm':15}),
    ('G013','Meander monopole','meandered_monopole',11,'Figure 13',20,{'radiator_span':10.5,'radiator_height':16.95}),
    ('G014','Printed IFA','ifa',13,'Figure 18',12,{'main_arm_span':16.8})]:
    pars=[p(k,k,v,'mm',page,fig,method='rendered_figure') for k,v in armdims.items()]
    pars += [p('antenna_board_height','antenna PCB',ant_h,'mm',page,fig,method='rendered_figure'),
             p('host_board_height','40 mm',40,'mm',2,'§1','ground'),p('host_board_width','30 mm',30,'mm',2,'§1','ground'),
             p('substrate_thickness','h',1.6,'mm',5,'§3.2.1','substrate'),
             p('model_epsilon_r','εr',4.4,'1',5,'§3.2.1','substrate'),p('model_loss_tangent','tanδ',.02,'1',5,'§3.2.1','substrate'),
             p('prototype_copper_thickness','35 µm',35,'um',21,'§4','substrate'),
             p('prototype_soldermask_thickness','20 µm',20,'um',21,'§4','substrate')]
    add(gid,'ST_AN5434',title+' with MB1623 host board',topology,
        [ev(page,fig),ev(2,'§1'),ev(3,'§2'),ev(5,'§3.2.1'),ev(21,'§4'),ev(36,'Conclusion / Table 2')],pars,
        target=2.45e9,bands=[[2.402e9,2.480e9]],substrate={'material':fact('FR4; initial model parameters from §3.2.1.',5,'§3.2.1')},
        ground={'host_context':fact('MB1623 plus battery, USB connector, MMCX and stitching vias included in complete model.',5,'Figure 3 / §3.2.1')},
        feed=[fact('50 Ω MMCX connection to antenna PCB; exact feed/ground pattern must follow source layout.',5,'§3.2.1')],
        applicability=[fact('Full host structure contributes to radiation; cannot apply principal arm lengths alone to arbitrary host.',3,'§2')],
        validation=[fact('CST Microwave Studio and ANSYS HFSS used for antenna simulations.',3,'§2'),fact('Prototypes measured with optical-link radiation setup to reduce cable effects.',21,'§4'),fact('Source notes frequency shifts caused by actual substrate permittivity; IFA and other narrow-band designs needed retuning.',36,'Conclusion')],
        status='partial_numeric_dimensions',missing=['Complete bend dimensions, trace widths, via coordinates and reference stackup CAD reconstruction.'])

add('G015','RENESAS_AN_B027','Full-size printed IFA on 1 mm substrate','ifa',
    [ev(6,'§4'),ev(7,'Figure 3 / legend'),ev(8,'Figure 4 / §4.1.1'),ev(9,'Figures 6–7')],
    [p(n,s,v,'mm',7,'Figure 3 / legend',category=c,method='rendered_figure') for n,s,v,c in [
        ('left_clearance','a',5,'keepout'),('right_clearance','b',5,'keepout'),('arm_ground_clearance','c',5.2,'keepout'),
        ('minimum_ground_depth','d',6,'ground'),('antenna_width','e',20.2,'geometry'),('trace_width','f',.6,'geometry'),('feed_position','g',5.4,'geometry')]]+
    [p('substrate_thickness','1 mm',1,'mm',7,'§4.1','substrate'),p('matching_C1','C1',2.4,'pF',8,'§4.1.1','matching'),p('matching_L1','L1',1.8,'nH',8,'§4.1.1','matching'),p('matching_C2','C2',2.7,'pF',8,'§4.1.1','matching')],
    target=2.4e9,substrate={'material':fact('FR4; two or more metal layers.',6,'§4')},
    ground={'minimum_depth':fact('d = 6.0 mm marks the minimum depth in Figure 3; it is not a complete ground-area specification.',7,'Figure 3')},
    feed=[fact('Radiator on top and bottom stitched with vias; feed only on top. Matching depends on substrate/enclosure. Radio RFIOp inductor is separate.',7,'Figure 3 / legend'),fact('3.3 or 3.9 nH near RFIOp depends on package; do not merge with antenna L1.',8,'§4.1.1')],
    validation=[fact('Measured S11 and two PCB orientations of radiation pattern supplied.',8,'Figure 5 / §4.1.2')],
    missing=['Complete via and curved feed coordinates from DXF.'])

add('G016','RENESAS_AN_B027','Reduced-size printed IFA variant 1','meandered_ifa',
    [ev(6,'§4'),ev(10,'Figure 8 / legend'),ev(11,'Figure 9 / §4.2.1'),ev(12,'Figures 11–12')],
    [p(n,s,v,'mm',10,'Figure 8 / legend',category=c,method='rendered_figure') for n,s,v,c in [
        ('left_clearance','a',5,'keepout'),('right_clearance','b',5,'keepout'),('arm_ground_clearance','c',6.8,'keepout'),
        ('minimum_ground_depth','d',7,'ground'),('antenna_width','e',16.3,'geometry'),
        ('main_arm_width','f',.8,'geometry'),('main_arm_length','f length',24.4,'geometry'),
        ('meander_arm_width','g width',.153,'geometry'),('meander_arm_length','g length',21.22,'geometry')]]+
    [p('substrate_thickness','1 mm',1,'mm',10,'§4.2','substrate'),p('matching_C2','C2',10,'pF',11,'§4.2.1','matching'),p('matching_L1','L1',10,'nH',11,'§4.2.1','matching')],
    target=2.4e9,substrate={'material':fact('FR4 on multilayer PCB; antenna copper on top only.',10,'Figure 8 legend')},
    feed=[fact('C1 DNP; L1 and C2 refer only to this source implementation. RFIOp package coil remains separate.',11,'§4.2.1')],
    validation=[fact('Measured S11 and radiation patterns shown.',11,'Figure 10')],
    status='partial_numeric_dimensions',missing=['Meander pitch/individual bends and main-arm curvature require DXF.'])

add('G017','RENESAS_AN_B027','ZOR antenna on 1.6 mm substrate','zeroth_order_resonator',
    [ev(16,'Figure 18 / §4.4'),ev(17,'Figure 19 / §4.4.1'),ev(18,'Figures 21–22')],
    [p('right_clearance','a',4,'mm',16,'Figure 18 legend','keepout'),p('lower_ground_clearance','b',1,'mm',16,'Figure 18 legend','keepout'),
     p('antenna_length','c',9,'mm',16,'Figure 18 legend'),p('antenna_width','d',5.8,'mm',16,'Figure 18 legend'),
     p('substrate_thickness','1.6 mm',1.6,'mm',16,'§4.4','substrate'),p('matching_L1','L1',1.5,'nH',17,'§4.4.1','matching'),p('matching_C1','C1',2.2,'pF',17,'§4.4.1','matching')],
    target=2.4e9,substrate={'material':fact('FR4; at least two layers, top and bottom used.',16,'§4.4')},
    feed=[fact('Package-dependent RFIOp 3.3/3.9 nH separate from antenna match.',17,'§4.4.1')],
    validation=[fact('Measured S11 and horizontal/vertical DUT radiation patterns.',17,'Figure 20')],
    status='partial_numeric_dimensions',missing=['Internal ZOR pattern, vias and entire GND outline require DXF.'])

add('G018','PAPER-059','Liang circular ring monopole optimum r=4 mm','closed_ring_monopole',
    [ev(2,'Antenna design / Figure 1'),ev(2,'Analysis and discussion'),ev(3,'Figures 3–5')],
    dims({'R':10,'r':4,'W':42,'L':50,'W1':2.6,'L1':20,'h':.3},2,'Antenna design / optimal design paragraph')+
    [p('substrate_thickness','1.5 mm',1.5,'mm',2,'Antenna design','substrate'),p('relative_permittivity','4.7',4.7,'1',2,'Antenna design','substrate')],
    bands=[[3.1e9,10.6e9]],substrate={'material':fact('FR4',2,'Antenna design')},
    ground={'back_plane':fact('L1=20 mm, width W=42 mm, covers feed section only.',2,'Antenna design')},
    feed=[fact('50 Ω microstrip; feed gap h is radiator-feedpoint to ground edge, not substrate height.',2,'Antenna design')],
    applicability=[fact('Ring has a closed annular current path, not the open arc running along a circular beacon PCB.',2,'Figure 1')],
    validation=[fact({'method':'CST FIT plus HP8720ES VNA and chamber patterns','measured_S11_below_minus10dB_hz':[2.75e9,9.84e9],'simulated_S11_below_minus10dB_hz':[2.71e9,10.04e9]},2,'Analysis and discussion')],
    notes=['Target UWB allocation is an application context; measured reference does not cover the entire 10.6 GHz upper edge at -10 dB.','PDF page 1 begins with the tail of a previous paper. Extracted target paper begins with its title and DOI mid-page.'])

add('G019','PAPER-063','Liang circular disc monopole optimum','disc_monopole',
    [ev(1,'Figure 1 / §II'),ev(2,'Figure 2 / §II–III')],
    dims({'r':10,'W':42,'L':50,'L1':20,'h':.3},2,'Figure 2 caption and §II')+
    [p('W1','W1',2.6,'mm',1,'§II',method='rendered_figure')]+
    [p('substrate_thickness','1.5 mm',1.5,'mm',1,'§II','substrate'),p('relative_permittivity','4.7',4.7,'1',1,'§II','substrate')],
    bands=[[3.1e9,10.6e9]],substrate={'material':fact('FR4',1,'§II')},
    ground={'back_plane':fact('Only feed region backed by GND; width W and length L1.',1,'Figure 1 / §II')},
    feed=[fact('50 Ω microstrip W1=2.6 mm; h=0.3 mm is feed gap, not laminate thickness.',1,'Figure 1 / §II')],
    validation=[fact({'method':'CST FIT, prototype HP8720ES VNA','measured_S11_below_minus10dB_hz':[2.78e9,9.78e9],'simulated_S11_below_minus10dB_hz':[2.69e9,10.16e9]},2,'§II / Figure 2')],
    notes=['Solid disc radiator is not open arc; perimeter-dominant current does not make their geometry interchangeable.','W1 is read from rendered physical p.1 because math text extraction omitted the number.'])

add('G020','PAPER-065','Verma NECMA II Newton egg curved monopole','egg_monopole',
    [ev(2,'§2 / Figures 1–2'),ev(3,'§2.1 / Equation 1'),ev(4,'Equations 3–5 / Tables 1–2')],
    dims({'Ws':40,'Ls':40,'Wf':3,'Wg':40,'Lg':9,'d':.15},3,'§2 and Figure 4 caption')+
    [p('curve_scale','s',12,'source_scale',4,'Table 2 / §3.1',condition='Source scaling factor; use Lp=2s and Wp=1.72s in mm for b=2,c=.35'),
     p('curve_parameter_b','b',2,'1',4,'Table 2'),p('curve_parameter_c','c',.35,'1',4,'Table 2'),
     p('substrate_thickness','h',1.6,'mm',2,'§2','substrate'),p('relative_permittivity','εr',4.4,'1',2,'§2','substrate'),
     p('loss_tangent_geometry_section','tanδ',.018,'1',2,'§2','substrate','Conflicts with model-input paragraph on p.3'),
     p('loss_tangent_model_input_paragraph','tanδ',.18,'1',3,'§3','substrate','Printed source value at 1 GHz; not silently corrected')],
    bands=[[3.1e9,10.6e9]],substrate={'material':fact('Double-sided FR4; Djordjević–Sarkar causal dielectric model used for broadband simulation.',3,'§3')},
    feed=[fact('50 Ω SMA and Wf=3 mm microstrip; ground on back; Lf=Lg+d.',3,'§2')],
    validation=[fact('HFSS 13, finite-conductivity copper and frequency-dependent dielectric model.',3,'§3'),fact({'prototype':'NECMA II','measured_S11_below_minus10dB_hz':[2.9e9,11e9],'simulated_S11_below_minus10dB_hz':[2.85e9,11e9]},4,'Table 2')],
    equations=[{'expression':'y = sqrt(c*(x*x-1)*(x-b)), -1 <= x <= 1','evidence':ev(3,'Equation 1'),'notes':'Closed egg perimeter requires both mirrored branches and source Figure 3 rotation/origin convention; no open-arc interpretation.'},
               {'expression':'Lp=2*s; Wp=1.72*s for b=2,c=0.35','evidence':ev(4,'paragraph after Equation 3'),'notes':'Source approximation; not an exact general curve bounding-box solver.'}],
    status='source_conflict_requires_review',conflicts=[{'field':'FR4 loss tangent','values':[.018,.18],'evidence':[ev(2,'§2'),ev(3,'§3')],'resolution':'Keep both reported values; clarify before EM baseline reproduction.'}],
    missing=['Resolve dielectric-loss value and explicitly implement source coordinate transform.'])

# Directly relevant open-ended curved monopole, but its own final dimensions
# contradict its earlier prose. Retaining the contradiction is essential.
add('G021','PAPER-023','Open-ended circular-ring monopole with strips for WLAN','open_arc_monopole_with_strips',
    [ev(2,'§II / Figure 1b'),ev(3,'§II.C–D / final parameter paragraph'),ev(1,'Abstract')],
    dims({'R1':8,'R2':10,'W1':25,'W2':11.5,'W3':2,'W4':1.5,'W5':2,'L1':40,'L2':5,'L3':4,'L4':2.2,'L5':2.8,'L6':18.2,'h':1},3,'Final parameter paragraph',condition='Final list as printed; internally inconsistent with earlier prose')+
    [p('earlier_substrate_width','W1',21,'mm',2,'§II','source_conflict','Earlier prose; final list says 25'),
     p('earlier_substrate_length','L1',45,'mm',2,'§II','source_conflict','Earlier prose; final list says 40'),
     p('relative_permittivity','4.4',4.4,'1',2,'§II','substrate')],
    bands=[[2.4e9,2.484e9],[5.15e9,5.95e9]],substrate={'material':fact('FR4, thickness 1.0 mm.',2,'§II')},
    feed=[fact('Microstrip feed W3=2 mm, nominal 50 Ω; two strip features alter matching.',2,'§II')],
    ground={'description':fact('Partial GND on back. Prose labels its 18.2 mm length L5, but final list uses L6=18.2 mm.',2,'§II')},
    validation=[fact({'method':'HFSS plus fabricated prototype; values are authors reports','measured_S11_below_minus10dB_hz':[[1.99e9,3.04e9],[5.08e9,6.1e9]]},1,'Abstract')],
    status='source_conflict_requires_review',conflicts=[
        {'field':'board dimensions W1/L1','values_mm':[[21,45],[25,40]],'evidence':[ev(2,'§II'),ev(3,'final parameter paragraph')],'resolution':'Unresolved; retain both.'},
        {'field':'L4/L5 gap and W4/L3 strip nomenclature','evidence':[ev(2,'§II'),ev(3,'§II.C–D')],'resolution':'Prose and final parameter names/optima conflict. Do not generate CAD from one paragraph alone.'}],
    missing=['Author CAD or independent reconciliation of figure, prose and final dimensional list.'],
    notes=['Open arc/ring cut, not Liang closed ring. This is rectangular-board WLAN geometry, not the original round Nordic beacon.'])

add('G022','PAPER-030','Wi-Fi 2.4/5/6 GHz asymmetric T monopole and grounded meander sleeve','t_monopole_with_sleeve_loop',
    [ev(4,'§2.1 / Table 1'),ev(5,'Table 1 continued / Figure 1'),ev(1,'Abstract')],
    dims({'L1':15,'L2':8,'L3':4.5},4,'Table 1')+dims({'L4':2,'W1':2.5,'W2':1,'W3':.5,'W4':6.5,'W5':1,'GL1':10},5,'Table 1 continued')+
    [p('board_total_length','18 mm',18,'mm',4,'§2.1'),p('board_width','15 mm',15,'mm',4,'§2.1'),
     p('substrate_thickness','1.0 mm',1,'mm',4,'§2.1','substrate'),p('relative_permittivity','4.3',4.3,'1',4,'§2.1','substrate'),p('loss_tangent','0.023',.023,'1',4,'§2.1','substrate')],
    bands=[[2.4e9,2.5e9],[5.15e9,5.85e9],[5.925e9,7.125e9]],substrate={'material':fact('FR4, single-sided metal layout on top.',4,'§2.1')},
    ground={'system_ground_mm':fact([10,15],4,'§2.1'),'loop_connection':fact('Meander sleeve starts and ends at ground.',5,'§2.2')},
    feed=[fact('Feeding point marked by red circle in Figure 1b; no added matching circuits in claimed design.',5,'Figure 1 / §2.2')],
    applicability=[fact('Representative finite host-ground experiments; no assertion of complete ground independence or validated multi-port Wi-Fi system.',3,'scope discussion')],
    validation=[fact('Fabricated and measured representative host configurations, according to authors.',1,'Abstract')],
    missing=['Translate Figure 1 topology/loop bends into explicit CAD coordinates before generation.'])

add('G023','PAPER-031','Wi-Fi 2.4/5/6 GHz closed slot with asymmetric T feed','closed_slot_t_coupled',
    [ev(3,'Figure 1'),ev(4,'Figure 2 / antenna description'),ev(5,'measured results discussion')],
    [p('slot_length','44 × 2 mm²',44,'mm',4,'Figure 2 / prose'),p('slot_width','44 × 2 mm²',2,'mm',4,'Figure 2 / prose'),
     p('feed_pcb_length','10 × 6 mm²',10,'mm',4,'Figure 2 / prose'),p('feed_pcb_width','10 × 6 mm²',6,'mm',4,'Figure 2 / prose'),
     p('feed_pcb_thickness','0.4 mm',.4,'mm',4,'Figure 2 / prose','substrate'),p('relative_permittivity','4.4',4.4,'1',4,'Figure 2 / prose','substrate'),
     p('loss_tangent','0.02',.02,'1',4,'Figure 2 / prose','substrate'),p('feed_offset_from_slot_left','13 mm',13,'mm',4,'Figure 2 / prose'),
     p('coupling_strip_length','9 mm',9,'mm',4,'Figure 2 / prose'),p('coupling_strip_width','0.5 mm',.5,'mm',4,'Figure 2 / prose'),
     p('coupling_gap_to_upper_ground_pad','0.3 mm',.3,'mm',4,'Figure 2 / prose'),
     p('six_element_array_span','284 × 2 mm²',284,'mm',3,'Figure 1 / prose','array'),p('adjacent_element_gap','4-mm intervals',4,'mm',3,'Figure 1 / prose','array')],
    bands=[[2.4e9,2.5e9],[5.15e9,7.125e9]],substrate={'material':fact('FR4 feed PCB attached to laptop display ground; slot is in chassis ground.',4,'Figure 2 / prose')},
    feed=[fact('50 Ω mini coax: inner to A, outer to G; asymmetric T couples to closed slot.',4,'Figure 2')],
    applicability=[fact('Host display ground and six-element arrangement belong to reference; isolated tiny PCB is not equivalent.',3,'Figure 1')],
    validation=[fact('HFSS v18 plus measured six-antenna reflection/transmission data; source text has inconsistent threshold inequalities, so no numerical pass claim extracted here.',5,'measured results discussion')],
    status='partial_numeric_dimensions',missing=['Full laptop host-ground/chassis geometry and complete feed outline required.'])

add('G024','PAPER-050','GNSS corner-truncated square patch, simulated reference','corner_truncated_patch',
    [ev(12,'Table 3'),ev(13,'Figure 4 / §4'),ev(3,'future validation discussion')],
    dims({'L':62.6,'W':62.6,'Lx':6.31,'Wx':4.05},12,'Table 3')+
    [p('substrate_thickness','1.575 mm',1.575,'mm',13,'§4','substrate'),p('relative_permittivity','εr',2.2,'1',13,'§4','substrate'),
     p('source_model_loss_tangent','tgδ',.0004,'1',13,'§4','substrate'),p('approx_corner_chamfer_fraction','approximately 8%',8,'%',13,'§4',condition='Approximate source description; not exact chamfer CAD')],
    target=1.575e9,bands=[[1.559e9,1.591e9]],substrate={'material':fact('RT Duroid 5880 as modelled by paper; use manufacturer Dk/Df separately.',13,'§4')},
    ground={'location':fact('Copper ground on opposite substrate face.',13,'§4')},
    feed=[fact('Single coaxial feed, 50 Ω RG-142. Feed coordinate measured relative to antenna center per prose.',13,'§4')],
    validation=[fact('This paper is simulation/theoretical modeling; experimental validation is explicitly future work.',3,'future validation discussion')],
    status='partial_numeric_dimensions',missing=['Exact substrate/GND lateral outline and corner chamfer coordinates; no measured prototype result.'])

add('G025','NXP_UM11232','NFC reader coil calculator screenshot example','rectangular_nfc_coil',
    [ev(3,'Figure 1, coil geometry panel'),ev(14,'Table 1'),ev(15,'Table 1 continued')],
    [p('outer_length','amax',53,'mm',3,'Figure 1',method='rendered_figure'),p('outer_width','bmax',26,'mm',3,'Figure 1',method='rendered_figure'),
     p('trace_width','w',250,'um',3,'Figure 1',method='rendered_figure'),p('trace_gap','g',300,'um',3,'Figure 1',method='rendered_figure'),
     p('additional_overlap_area','A',0,'mm2',3,'Figure 1',method='rendered_figure'),p('turns','N',3,'turn',3,'Figure 1',method='rendered_figure'),
     p('copper_thickness','Track Thickness',35,'um',3,'Figure 1','substrate',method='rendered_figure'),
     p('pcb_thickness','PCB Thickness',1.59,'mm',3,'Figure 1','substrate',method='rendered_figure'),p('relative_permittivity','Er',4.3,'1',3,'Figure 1','substrate',method='rendered_figure'),
     p('empirical_turn_exponent','E',1.66,'1',3,'Figure 1','model',method='rendered_figure')],
    target=13.56e6,substrate={'material':fact('FR4 CL4 selected in screenshot.',3,'Figure 1')},
    feed=[fact('Reader-specific resonant/matching network required; not a 50 Ω quarter-wave radiator.',3,'Figure 1')],
    validation=[fact({'status':'tool calculated screenshot, not a measured antenna','Lant_nH':959,'Lant_min_nH':898,'Lant_max_nH':1182,'self_resonance_MHz':129},3,'Figure 1'),fact('Manual states final inductance/tuning must be measured; extra metal influence omitted.',15,'Table 1 continued')],
    status='published_tool_example',missing=['Exact corner rounding and bridge geometry; verify tuning with final reader, loading and enclosure.'])

add('G026','NXP_AN11180','UCODE I2C large ground-integrated UHF slot reference','uhf_rfid_ground_slot',
    [ev(11,'§4.1 / Figure 8'),ev(12,'Figure 9'),ev(13,'§4.2')],
    [p('board_width','80x45mm',80,'mm',11,'§4.1'),p('board_height','80x45mm',45,'mm',11,'§4.1'),
     p('antenna_slot_envelope_height','18 mm',18,'mm',12,'Figure 9',method='rendered_figure'),
     p('antenna_slot_envelope_width','12.5 mm',12.5,'mm',11,'§4.1'),
     p('slot_inner_vertical_opening','10 mm',10,'mm',12,'Figure 9',method='rendered_figure'),
     p('slot_lateral_arm_span','9.5 mm',9.5,'mm',12,'Figure 9',method='rendered_figure'),
     p('slot_side_offset','3 mm',3,'mm',12,'Figure 9',method='rendered_figure'),
     p('copper_thickness','35µm',35,'um',11,'§4.1','substrate'),p('substrate_thickness','0.5mm',.5,'mm',11,'§4.1','substrate')],
    bands=[[840e6,960e6]],substrate={'material':fact('FR4',11,'§4.1')},
    ground={'description':fact('Antenna uses entire board ground plane; dotted boundary in Figure 8 denotes minimum ground, so slot size alone is insufficient.',11,'§4.1')},
    feed=[fact('RFID chip/slot impedance matching, not a generic 50 Ω port; I2C pads are part of structure.',11,'§4.1')],
    applicability=[fact('Components occupying ground plane can reduce read/write performance versus bare reference.',11,'§4.1')],
    validation=[fact('Source characterizes reading distance over 840–960 MHz, with maximum/minimum copper ground and with/without powered I2C adapter. This is a measured sweep domain, not a guaranteed band-wide read-distance minimum.',13,'§4.2')],
    status='partial_numeric_dimensions',missing=['Chip-pad/slot-neck radii and full reference design polygon; exact chip impedance and loading conditions.'])

# Two evidence-only entries prevent the absence of dimensions from being hidden.
add('G027','ADI_AN4302','Open-ended perimeter trace monopole concept','open_arc_monopole',
    [ev(1,'Printed Circuit Board Loop or Whip Antenna'),ev(2,'Figure 1 / opening paragraph'),ev(5,'matching section')],[],
    bands=[[300e6,450e6]],
    feed=[fact('Feed end goes to PA directly or through matching; far end open makes it monopole/whip. Grounding the far end instead creates the loop.',2,'Figure 1 / opening paragraph')],
    keepout=[fact('On two-sided PCB, opposite face beneath antenna must be bare; matching components sit over ground ending near feed.',1,'Printed Circuit Board Loop or Whip Antenna')],
    applicability=[fact('Trace may follow a portion of circle, ellipse, square or rectangle. Source is 300–450 MHz electrically small transmitter context.',2,'opening paragraph')],
    status='topology_only_no_dimensioned_design',missing=['No board radius, arc angle, trace width or exact ground dimensions in this note.','Do not convert generic 2–5 cm handheld examples into this specific geometry.'])

add('G028','QORVO_APH007','DW1000 antenna selection requirements, no published pattern','uwb_requirement_only',
    [ev(3,'Table 1'),ev(5,'§4.6–4.8')],[],
    feed=[fact('Choose antenna for selected DW1000 channels; this is selection guidance, not a dimensioned printed-radiator drawing.',3,'§1–3')],
    validation=[fact({'fidelity_factor_recommended_min_percent':99,'orientation_group_delay_variation_recommended_max_ps':100},5,'§4.6 / §4.8')],
    status='requirements_only_no_geometry',missing=['WB001/WB002/WB003 CAD dimensions require separate archive extraction.'],
    notes=['Channel center frequencies/BWs belong in applicability dataset; do not infer antenna dimensions from APH007.'])

add('G029','PAPER-066','Liang thesis CPW-fed circular disc optimum','cpw_disc_monopole',
    [ev(98,'§4.2.1'),ev(99,'Figure 4.20 / optimal design paragraph'),ev(100,'Figure 4.22'),ev(101,'§4.2.1 results')],
    dims({'r':12.5,'h':.3,'L':10,'W':47,'Wf':4,'g':.33},99,'Figure 4.20 / §4.2.1')+
    [p('substrate_thickness','H',1.6,'mm',99,'§4.2.1','substrate'),p('relative_permittivity','εr',3,'1',99,'§4.2.1','substrate')],
    bands=[[3.1e9,10.6e9]],substrate={'material':fact('Dielectric with epsilon_r=3; material trade name not stated here. Do not call this generic FR4.',99,'§4.2.1'),'metal_layers':fact('Single metallic layer: disc, CPW and GND on same face.',98,'§4.2.1')},
    ground={'dimensions':fact('W=47 mm is total lateral ground width; L=10 mm is ground length. These are not full substrate dimensions.',99,'§4.2.1 / Figure 4.20')},
    feed=[fact('50 Ω CPW: Wf=4 mm, g=0.33 mm; SMA included in simulation because planar geometry exposes its fields.',99,'§4.2.1')],
    validation=[fact('CST FIT simulation includes SMA port.',99,'§4.2.1'),fact('HP8720ES prototype measurements.',100,'§4.2.1'),fact({'simulated_minus10dB_edges_hz':[2.69e9,15.95e9],
                     'measured_outer_edges_hz':[2.84e9,15.17e9],
                     'exception':'Measured S11 reaches -9.6 dB around 7 GHz; do not label the entire outer-edge span as continuous <-10 dB.'},101,'§4.2.1')],
    missing=['Full substrate border, exact SMA construction and material trade name before numerical reproduction.'])

add('G030','PAPER-066','Liang thesis CPW-fed elliptical slot with U-shaped stub','cpw_elliptical_slot',
    [ev(133,'§5.2'),ev(134,'Figure 5.2'),ev(136,'Table 5-A'),ev(139,'Table 5-B')],
    dims({'A':14.5,'B':10,'S':.4,'R':5.5,'r':2.5,'H':2.5,'W':3,'L':3},136,'Table 5-A, CPW-fed elliptical-slot column')+
    [p('substrate_extent_1','Substrate Size 40×38',40,'mm',136,'Table 5-A'),p('substrate_extent_2','Substrate Size 40×38',38,'mm',136,'Table 5-A'),
     p('substrate_thickness','t',1.5,'mm',133,'§5.2','substrate'),p('relative_permittivity','εr',4.7,'1',133,'§5.2','substrate'),
     p('feed_taper_angle','θ',15,'degree',133,'§5.2')],
    bands=[[3.1e9,10.6e9]],substrate={'material':fact('FR4, radiating slot and CPW feed on same face.',133,'§5.2')},
    ground={'description':fact('Elliptical aperture cut in rectangular metal plane; A/B are ellipse semi-axes. R/r define U-stub ring radii, not board radius.',134,'Figure 5.2')},
    feed=[fact('50 Ω CPW tapered by 15 degrees into a U-shaped tuning stub; W1 and g appear in figure but have no numeric entry in Table 5-A.',134,'Figure 5.2')],
    validation=[fact('Fabricated antenna samples; HP8720ES VNA measurements.',136,'§5.3.1'),fact({'measured_S11_below_minus10dB_hz':[3.1e9,10.6e9],
                     'simulated_S11_below_minus10dB_hz':[3.0e9,11.4e9]},139,'Table 5-B')],
    status='partial_numeric_dimensions',missing=['Numeric CPW input W1 and g plus exact aperture placement within substrate; do not infer from image scale.'])

add('G031','NORDIC_PCA20006_CAD','PCA20006 / PCB400059 round beacon open perimeter radiator — CAD pending','open_arc_monopole',
    [],[],target=2.4e9,status='cad_acquired_geometry_reconstruction_pending',
    missing=['Arc center/radius/start/sweep angles; trace width and endpoints; feed transition; board outline; per-layer ground cutback; stackup; matching-network extraction.'],
    notes=['Nested official ZIP inventory verified: 20 inner archive entries, including 400059.PcbDoc, 400059.GTL, 400059.GBL, 400059.GM1 and PCA20006_Schematic_And_PCB.pdf.',
           'Target CAD layers to inspect next: GTL (top copper), GBL (bottom copper), GM1 (mechanical drawing; confirm board-outline semantics), GTS/GBS (mask).',
           'No dimensional value has been inferred from the user photograph, the PCB image, or a presumed board diameter.',
           'Copper connectivity and layer role still need CAD reconstruction; source catalog topology is a working classification until that is checked.'])

# Promoted from CAD-pending after exact Gerber commands and the embedded PCB PDF
# were checked. Archive-member provenance is separate from top-level PDF pages.
from extract_nordic_cad import extract as extract_nordic
NORDIC_CAD = extract_nordic()
g31=GEOMETRIES[-1]
g31['variant_title']='PCA20006 / PCB400059 rev 1.0.0 — open arc and feed stub from Gerber'
g31['extraction_status']='partial_cad_geometry_extracted'
g31['parameters']=[]
for q in NORDIC_CAD['numeric_facts']:
    e=q['cad_evidence']
    locator=e['archive_member']
    if 'gerber_line_start' in e:
        locator+=f" : Gerber lines {e['gerber_line_start']}–{e['gerber_line_end']}"
    else:
        locator+=f" : embedded physical PDF page {e['embedded_physical_pdf_page']}"
    z=p(q['name'],q['source_symbol'],q['value'],q['unit'],None,locator,
        category='matching' if q['unit'] in ['nH','pF'] else 'cad_geometry',
        condition=q['condition'],method=q['derivation_status'])
    z['derivation_status']=q['derivation_status']
    z['embedded_source']=e
    z['evidence_status']='source_reported' if q['derivation_status']=='embedded_pdf_reported' else 'cad_coordinate_extraction'
    g31['parameters'].append(z)
pdf_info=NORDIC_CAD['embedded_reference_pdf']
g31['source_evidence']=[{'physical_pdf_page':None,'locator':pdf_info['archive_member']+' : embedded physical PDF pages 1–3',
                        'note':'Top-level source is ZIP. Pages refer only to the embedded four-page PDF.',
                        'embedded_source':pdf_info},
                       {'physical_pdf_page':None,'locator':'GTL D10 arc / feed stub and GM1 body reference arc',
                        'note':'See per-parameter Gerber line ranges and member hashes; dimensions are computed from 2.4-format inch coordinates.'}]
g31['embedded_sources']=[pdf_info]
g31['cad_geometry_evidence']='evidence/nordic_cad/nordic_cad_geometry.json'
g31['rendered_evidence']=['evidence/nordic_cad/reference_p1.png','evidence/nordic_cad/reference_p2.png','evidence/nordic_cad/reference_p3.png','evidence/nordic_cad/nordic_arc_dimensions.png']
g31['ground']={'status':'Partial copper-edge coordinates extracted. Exact ground-net polygons and global minimum antenna clearance are not reconstructed.'}
g31['feed_and_matching']=[{'value':'BAL-NRF02D3 balun to RF node; C4=1.2 pF shunt to GND then L1=2.2 nH series to ANT.',
                          'physical_pdf_page':None,'embedded_source':{**pdf_info,'embedded_physical_pdf_page':1}}]
g31['source_reported_validation']=[{'value':'Copper arc/stub cross-checked against the original top PCB drawing; no EM or antenna-performance measurement.',
                                  'physical_pdf_page':None,'embedded_source':{**pdf_info,'embedded_physical_pdf_page':2}}]
g31['missing_information']=['PCB thickness, grade/Dk/Df, copper thickness and mask stackup.','Complete copper net connectivity and ground polygon reconstruction, battery/enclosure models, production verification.','Actual board outline includes tabs/connector extension; the body reference circle alone is not the whole outline.']
g31['notes']=['Arc radius/angle/width come from exact original GTL G03/D10 commands, not image scaling.',
              'Hardware 1.0.0 / PCB400059 only. Gerber coordinate step is 0.00254 mm; start/end radius differs by 0.001041 mm due to endpoint quantization.',
              'Partial CAD geometry only: automatic_cad_generation_ready remains false for whole-antenna/board reconstruction.',
              'Adjacent copper arc/vertex values are not a verified global ground radius or minimum keepout.',
              'Matching values are source-specific. No antenna performance verified by this extraction.']


def normalized(parameter):
    factors={'mm':1,'um':.001,'inch':25.4}
    if parameter['unit'] in factors:
        return round(parameter['value']*factors[parameter['unit']],9),'mm'
    return parameter['value'],parameter['unit']


def write_outputs():
    # Populate source IDs on every parameter, allowing flat imports without
    # guessing its parent. Physical page numbering is one-based everywhere.
    for g in GEOMETRIES:
        for q in g['parameters']:
            q['source_id']=g['source_id']
            q['geometry_id']=g['geometry_id']
            q['normalized_value'],q['normalized_unit']=normalized(q)
    counts=Counter(g['extraction_status'] for g in GEOMETRIES)
    obj={
        'schema_version':'rf_geometry_extraction_v1.0',
        'extracted_date_asia_seoul':'2026-11-07',
        'language':'English parameter keys; source symbols preserved',
        'page_convention':'Physical PDF page, one-based; never infer from journal/printed page numbers.',
        'scope':'First-pass source-reported numeric examples and critical topology-only references; not exhaustive extraction of the full source corpus.',
        'summary':{'geometry_records':len(GEOMETRIES),'numeric_parameter_rows':sum(len(g['parameters']) for g in GEOMETRIES),
                   'distinct_sources':len(set(g['source_id'] for g in GEOMETRIES)),
                   'status_counts':dict(counts),'machine_ready_cad_layouts':0,'independently_validated_antennas':0},
        'important_limits':[
            'Published numeric parameters do not equal a complete connected copper polygon or validated design.',
            'All automatic_cad_generation_ready fields are false until topology, layer stackup, feed and ground coordinates are represented and checked.',
            'Do not scale a layout by frequency alone or assign one universal epsilon_r to FR4.',
            'S11 bandwidth is not radiation efficiency, link range, UWB pulse fidelity or regulatory compliance.',
            'Source values and proposed software input names are separated: program schema proposals are in program_schema_proposals.json.',
        ],
        'geometries':GEOMETRIES,
    }
    (HERE/'geometries.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    cols=['geometry_id','source_id','variant_title','topology','extraction_status','name','source_symbol','value','unit',
          'normalized_value','normalized_unit','category','physical_pdf_page','locator','condition','extraction_method','evidence_status','derivation_status','embedded_source','source_relative_path','source_sha256']
    with (HERE/'geometry_parameters.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for g in GEOMETRIES:
            for q in g['parameters']:
                row={k:g.get(k,'') for k in cols};row.update({k:q[k] for k in cols if k in q})
                if row.get('embedded_source'):row['embedded_source']=json.dumps(row['embedded_source'],ensure_ascii=False)
                w.writerow(row)
    with (HERE/'geometry_records.csv').open('w',encoding='utf-8-sig',newline='') as f:
        columns=['geometry_id','source_id','variant_title','topology','numeric_parameter_count','extraction_status','source_pages','missing_information','source_conflicts','automatic_cad_generation_ready']
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for g in GEOMETRIES:
            w.writerow({'geometry_id':g['geometry_id'],'source_id':g['source_id'],'variant_title':g['variant_title'],'topology':g['topology'],
                'numeric_parameter_count':len(g['parameters']),'extraction_status':g['extraction_status'],
                'source_pages':';'.join(str(x) for x in sorted(set(e['physical_pdf_page'] for e in g['source_evidence'] if e['physical_pdf_page'] is not None))),
                'missing_information':' | '.join(g['missing_information']),
                'source_conflicts':json.dumps(g['source_conflicts'],ensure_ascii=False),
                'automatic_cad_generation_ready':False})
    with (HERE/'evidence_index.csv').open('w',encoding='utf-8-sig',newline='') as f:
        columns=['geometry_id','source_id','physical_pdf_page','locator','note','embedded_source','rendered_page_image','source_relative_path']
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for g in GEOMETRIES:
            for e in g['source_evidence']:
                im=f"evidence/{g['source_id']}_p{e['physical_pdf_page']:03}.png" if e['physical_pdf_page'] is not None else ''
                row={'geometry_id':g['geometry_id'],'source_id':g['source_id'],**e,
                    'rendered_page_image':im if im and (HERE/im).exists() else '', 'source_relative_path':g['source_relative_path']}
                if row.get('embedded_source'):row['embedded_source']=json.dumps(row['embedded_source'],ensure_ascii=False)
                w.writerow(row)
    r=CATALOG['NORDIC_PCA20006_CAD']
    outer=zipfile.ZipFile(ROOT/'package'/r['relative_path'])
    inner_name=outer.namelist()[0]
    inner_bytes=outer.read(inner_name)
    inner=zipfile.ZipFile(io.BytesIO(inner_bytes))
    inv={'source_id':'NORDIC_PCA20006_CAD','source_relative_path':r['relative_path'],
         'outer_sha256':hashlib.sha256((ROOT/'package'/r['relative_path']).read_bytes()).hexdigest(),
         'inner_archive_name':inner_name,'inner_archive_sha256':hashlib.sha256(inner_bytes).hexdigest(),
         'geometry_extraction_status':'partial_cad_geometry_extracted_no_photo_dimensions',
         'entries':[{'path':n,'bytes':len(inner.read(n)),'sha256':hashlib.sha256(inner.read(n)).hexdigest()} for n in inner.namelist() if not n.endswith('/')]}
    (HERE/'evidence/nordic_pca20006_archive_inventory.json').write_text(json.dumps(inv,ensure_ascii=False,indent=2)+'\n')
    proposals={
        'status':'PROPOSED_PROGRAM_SCHEMA_NOT_PUBLISHED_REFERENCE_DIMENSIONS',
        'common_inputs':['frequency_bands_hz','substrate_stackup','frequency_dependent_epsilon_complex','copper_thickness_and_roughness','board_outline_xy','ground_polygons_per_layer','feed_port_and_reference_plane','matching_components','soldermask','enclosure_and_battery_geometry','manufacturing_tolerances'],
        'open_arc_monopole_inputs':['board_radius_mm','trace_centerline_radius_mm','start_angle_deg','sweep_angle_deg','trace_width_mm','open_tip_geometry','feed_transition_geometry','ground_cutback_polygon','ground_tip_clearance_mm'],
        'ifa_inputs':['radiating_branch_segments','shorting_branch_geometry','feed_branch_geometry','feed_short_spacing','ground_edge','layer_connections'],
        'nfc_inputs':['outer_width_mm','outer_length_mm','turn_count','track_width_mm','track_gap_mm','corner_radius_mm','layer_count','interlayer_bridge_and_overlap_area','target_inductance_h','reader_or_tag_chip_model'],
        'uwb_extra_outputs':['complex_S11_over_band','efficiency_over_band','realized_gain_3d','group_delay_vs_orientation','impulse_response','fidelity_factor'],
        'blocked_shortcuts':['Inferring Nordic beacon radius from image','Treating a closed ring/disc as an open arc','Selecting contradictory source values without resolving conditions','Claiming matching alone verifies radiation efficiency'],
    }
    (HERE/'program_schema_proposals.json').write_text(json.dumps(proposals,ensure_ascii=False,indent=2)+'\n')
    errors=[]
    seen=set()
    import fitz
    for g in GEOMETRIES:
        if g['geometry_id'] in seen:errors.append('duplicate geometry ID '+g['geometry_id'])
        seen.add(g['geometry_id'])
        r=CATALOG[g['source_id']]
        file=ROOT/'package'/r['relative_path'] if r.get('relative_path') else ROOT.parent/'upload'/UPLOADS[g['source_id']]
        if file.suffix.lower() != '.pdf':
            if g['geometry_id']=='G031':
                if not NORDIC_CAD['qa']['command_checks_passed']:errors.append('Nordic Gerber source-command check failed')
                for q in g['parameters']:
                    if q['physical_pdf_page'] is not None:errors.append('Top-level ZIP must not have PDF page '+q['name'])
                    if not q.get('embedded_source'):errors.append('Missing archive-member provenance '+q['name'])
            elif g['parameters']:errors.append('numeric non-PDF geometry requires CAD-specific QA '+g['geometry_id'])
            continue
        with fitz.open(file) as d:
            for q in g['parameters']:
                if not 1<=q['physical_pdf_page']<=len(d):errors.append('out-of-range page '+g['geometry_id'])
                if not isinstance(q['value'],(int,float)):errors.append('non-numeric parameter '+g['geometry_id'])
                if not q['unit'] or not q['source_symbol']:errors.append('missing unit or symbol '+g['geometry_id'])
            for e in g['source_evidence']:
                if not 1<=e['physical_pdf_page']<=len(d):errors.append('out-of-range evidence '+g['geometry_id'])
    qa={'checks':'Source file opens, SHA256, unique geometry IDs, numeric parameter type, unit/symbol presence, physical page bounds; selected figure labels visually checked.',
        'errors':errors,'source_performance_reproduced':False,'summary':obj['summary'],
        'review_required_geometry_ids':[g['geometry_id'] for g in GEOMETRIES if g['source_conflicts']],
        'additional_cad_pending':[
            {'source_id':'NORDIC_PCA20006_CAD','geometry_id':'G031','status':'partial_cad_geometry_extracted','reason':'Arc/stub/selected copper-edge and body-circle geometry extracted; full net/ground/stackup reconstruction remains.'},
            {'source_id':'QORVO_WB001_002_003_CAD','status':'cad_acquired_geometry_reconstruction_pending','reason':'CAD packages exist but dimensions/topology not reconstructed in this extraction pass.'},
        ]}
    (HERE/'qa.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n')
    guide='''PCB RF 안테나 형상 데이터 추출 v1 — 2026-11-07

범위
이 데이터는 원문·CAD에서 실제 수치를 읽은 29개 사례와, 수치 없는 ADI 원호 개념/Qorvo UWB 요구조건 2개 레코드를 담습니다.
전체 확보 문헌의 모든 형상을 추출했다는 뜻이 아닙니다. 31개 레코드, 348개 수치 행, 23개 출처입니다.
독립 EM 시뮬레이션/실물 측정은 수행하지 않았습니다. 성능은 모두 source_reported_only입니다.

파일
geometries.json: 기판·접지·급전·매칭·적용 조건·검증 관찰·출처 충돌까지 포함한 원본 구조화 데이터.
geometry_parameters.csv: 수치 한 개당 한 행. UTF-8 BOM. 원단위와 mm 환산값 모두 포함합니다.
geometry_records.csv: 사례별 요약, 치수 개수와 미해결 조건.
evidence_index.csv: 물리 PDF 페이지/그림·표와 선택 도면 렌더링 연결.
qa.json: 파일·숫자형·페이지 범위 점검 및 해소할 충돌 목록.
program_schema_proposals.json: 향후 프로그램 입력 항목 제안. 문헌에서 검증된 수치와 섞지 않습니다.
build_geometry.py: 원문 목록을 참조하여 JSON/CSV/QA를 재생성합니다. 실행 위치와 무관합니다.
source_text/: 추출에 참고한 PDF 텍스트. 그림의 숫자·수식은 원본 PDF/렌더링이 우선입니다.
evidence/: 실제 페이지의 렌더링과 Nordic 중첩 ZIP 인벤토리.

단위·페이지 규칙
physical_pdf_page는 1부터 세는 실제 PDF 페이지입니다. 학술지 인쇄 페이지, 학위논문 내부 페이지와 다를 수 있습니다.
SILABS_AN1088의 원단위는 inch입니다. 정규화에서만 정확히 25.4 mm/inch를 적용합니다.
Newton egg의 s는 원문 스케일 인자로 보존했으며 일반 길이 단위처럼 자동 환산하지 않습니다.
프로그램 생성용 완전한 연결 동박 폴리곤은 아직 없습니다. automatic_cad_generation_ready는 전부 false입니다.
dimensioned_reference는 수치 참조 사례라는 뜻이며 자동 생산 가능한 CAD나 검증 완료 안테나라는 뜻이 아닙니다.

주요 확인 사항
G004/G005 TI DN023: L6 표 값 17 mm, 문맥상 권고 9/1 mm, 측정 도표 11/3 mm를 각각 보존했습니다. 한 값으로 합치지 않습니다.
G020 PAPER-065: 원문 FR4 tanδ=0.018(물리 p.2)와 0.18(물리 p.3)가 충돌합니다. 임의 수정하지 않았습니다.
G021 PAPER-023: 개방 원호 WLAN 논문입니다. W1/L1 및 strip/gap 서술이 앞뒤에서 달라 치수 충돌 검토가 필요합니다.
G029 PAPER-066: CPW disc의 측정 외곽 대역은 2.84–15.17 GHz지만 7 GHz 부근 S11=-9.6 dB의 예외가 있습니다. 연속 -10 dB 대역으로 표시하지 않았습니다.
G030 PAPER-066: CPW elliptical slot의 수치표는 확보했지만 입력 CPW의 W1/g 값은 해당 표에 없어 CAD 재생성에는 추가 확인이 필요합니다.
G031 Nordic PCA20006: rev1.0.0/PCB400059 GTL의 원호 반지름 약9.11993 mm, 폭1.27 mm, CCW sweep112.53463° 등을 실제 Gerber 좌표로 추출했습니다. 원형 본체 약20 mm와 돌출 탭/커넥터를 구분했습니다. 전체 GND·net·stackup 재구성은 남아 있습니다. 사진에서 지름을 추정하지 않았습니다.
G031의 최상위 출처는 ZIP이므로 physical_pdf_page는 null입니다. embedded_source에 내부 PDF 페이지/파일 SHA와 Gerber 줄 범위가 있고, derivation_status는 좌표 원값/계산 결과/내부 PDF 수치를 구분합니다.
G018/G019 Liang closed ring/disc는 G021/G027/G031 open arc와 별도 토폴로지입니다.
G025 NXP NFC는 공식 도구 화면에 게시된 계산 예제이며 측정 결과가 아닙니다.
G024 GNSS patch는 논문 자체가 실험 검증을 미래 과제로 남겼습니다.

활용 순서
1. 원하는 topology를 선택하고 원문 조건과 미해결 필드를 확인합니다.
2. 재질 grade/주파수별 Dk·Df와 실제 PCB stackup, GND, 케이스/배터리를 연결합니다.
3. 참조 도면을 연결된 2D/3D 형상으로 재구성하고 원본 CAD/도면과 대조합니다.
4. EM 모델, 포트/경계/메시, 공차·환경 sweep을 만든 뒤 VNA와 방사 측정으로 확인합니다.
이 파일의 수치와 성능을 주파수 비례나 임의 FR4 상수만으로 일반화하지 마십시오.
'''
    (HERE/'README_KO.txt').write_text(guide,encoding='utf-8')
    print(json.dumps(qa['summary'],ensure_ascii=False))
    if errors:raise RuntimeError(errors)


if __name__=='__main__':
    write_outputs()
