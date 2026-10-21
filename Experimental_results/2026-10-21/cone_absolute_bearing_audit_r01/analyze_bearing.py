"""Explain absolute bearing vs angular size without fitting a new calibration."""
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256
from bearing import (inspect_pixel,central_equidistant_pixels,repeated_pixel_bound,
                     CAMERA_HEIGHT_M,CONE_HEIGHT_M)
from fisheye_floor_geometry import legacy_front_diagnostic_geometry

HEIGHT=HERE.parent/'cone_known_height_pinhole_r01'
PAPER7=ROOT/'Experimental_results/2026-10-15/paper_reference7_r01'
PAPER19=ROOT/'Experimental_results/2026-10-19/paper_cone_2m_validation_r01'
OFFSETS={'vertical_axis_proxy':0.,'axis_aligned_base_half':.375/2,'square_half_diagonal_sensitivity':.375/np.sqrt(2)}


def load_inputs():
    paths={}
    for folder,name,consumed in ((PAPER7/'analysis_r01','provenance.json',('reference_points_primary170.csv',)),
        (PAPER19/'analysis_r01','summary.json',('paper_corner_diagnostics.csv',)),
        (HEIGHT/'results_r01','provenance.json',('observed_pixels.csv',))):
        provenance=json.loads((folder/name).read_text())
        for f in consumed:
            p=folder/f
            assert sha256(p)==provenance['output_sha256'][f],p
            paths[str(p)]=sha256(p)
        paths[str(folder/name)]=sha256(folder/name)
    geometry=json.loads((HEIGHT/'results_r01/provenance.json').read_text())['models']
    seven=read_csv(PAPER7/'analysis_r01/reference_points_primary170.csv')
    paper=read_csv(PAPER19/'analysis_r01/paper_corner_diagnostics.csv')
    tips=[r for r in read_csv(HEIGHT/'results_r01/observed_pixels.csv')
          if r['dataset']=='paper_cone_20261019' and r['condition']=='cone_static']
    assert len(seven)==7 and len(tips)==299 and len(paper)==1733*3
    primary=[r for r in paper if r['threshold']=='170' and r['phase'] in ('paper_before','paper_after') and r['candidate']=='True']
    assert len(primary)==391+240
    anchor=np.median([[float(r['pixel_x']),float(r['pixel_y'])] for r in primary],axis=0)
    a=json.loads((PAPER7/'intake_summary.json').read_text())
    b=json.loads((PAPER19/'intake_summary.json').read_text())
    meta7=Path(a['session'])/'metadata.json'
    meta19=Path(b['session'])/'metadata.json'
    j7,j19=json.loads(meta7.read_text()),json.loads(meta19.read_text())
    metadata=dict(parameters_equal=j7['parameters']==j19['parameters'],
        capture_properties_equal=j7.get('camera_capture_properties')==j19.get('camera_capture_properties'),
        metadata7=str(meta7),metadata19=str(meta19),
        geometry7={k:j7['parameters'][k] for k in ('camera_height','pitch_deg','roll_deg','yaw_deg','radius_scale','front_cx_offset','front_cy_offset')},
        geometry19={k:j19['parameters'][k] for k in ('camera_height','pitch_deg','roll_deg','yaw_deg','radius_scale','front_cx_offset','front_cy_offset')},
        identical_metadata_does_not_prove_identical_physical_geometry=True)
    for p in (meta7,meta19,HERE/'method.md',HERE/'bearing.py',Path(__file__),ROOT/'src/fisheye_floor_geometry.py',ROOT/'src/ground_contact.py'):
        paths[str(p)]=sha256(p)
    return seven,paper,tips,anchor,geometry,metadata,paths


def analyze(seven,paper,tips,anchor,models):
    floor7=[]
    for r in seven:
        for model,p in models.items():
            result=inspect_pixel([float(r['pixel_x']),float(r['pixel_y'])],p,reference_z_m=float(r['reference_z_m']))
            floor7.append(dict(recording='paper7',point_id=r['point_id'],model=model,
                reference_x_m=float(r['reference_x_m']),reference_z_m=float(r['reference_z_m']),
                corner_candidate_frames=int(r['candidate_frames']),total_interval_frames=int(r['frames']),**result))
    all_paper=[]
    for r in paper:
        for model,p in models.items():
            row=dict(recording='paper19',frame=int(r['frame']),phase=r['phase'],threshold=int(r['threshold']),
                model=model,candidate=r['candidate']=='True',reason=r['reason'],
                reference_z_m=2. if r['phase'] in ('paper_before','paper_after') else None,
                pixel_x=None,pixel_y=None,observed_elevation_deg=None,expected_elevation_deg=None,
                required_down_rotation_deg=None,model_floor_z_m=None,implied_camera_height_if_floor_m=None,
                physical_reference_verified=False,calibrated_intrinsics=False,usable_for_ffb=False)
            if row['candidate'] and row['reference_z_m'] is not None:
                row.update(inspect_pixel([float(r['pixel_x']),float(r['pixel_y'])],p,reference_z_m=2.))
            all_paper.append(row)
    pairs=[]
    for r in tips:
        if not r['native_colour_pair_json']:
            raise ValueError('frozen cone tip absent; do not fabricate')
        pixel=json.loads(r['native_colour_pair_json'])[0]
        for model,p in models.items():
            floor=inspect_pixel(anchor,p,reference_z_m=2.)
            for name,offset in OFFSETS.items():
                tip=inspect_pixel(pixel,p,reference_z_m=2.+offset,reference_height_m=CONE_HEIGHT_M)
                observed_gap=tip['observed_elevation_deg']-floor['observed_elevation_deg']
                expected_gap=tip['expected_elevation_deg']-floor['expected_elevation_deg']
                pairs.append(dict(frame=int(r['frame']),time_sec=float(r['time_sec']),model=model,offset_hypothesis=name,
                    offset_m=offset,tip_x=pixel[0],tip_y=pixel[1],anchor_x=float(anchor[0]),anchor_y=float(anchor[1]),
                    floor_observed_elevation_deg=floor['observed_elevation_deg'],floor_expected_elevation_deg=floor['expected_elevation_deg'],
                    tip_observed_elevation_deg=tip['observed_elevation_deg'],tip_expected_elevation_deg=tip['expected_elevation_deg'],
                    floor_rotation_residual_deg=floor['required_down_rotation_deg'],tip_rotation_residual_deg=tip['required_down_rotation_deg'],
                    observed_gap_deg=observed_gap,expected_gap_deg=expected_gap,gap_difference_deg=observed_gap-expected_gap,
                    paper_anchor_is_before_after_not_simultaneous=True,physical_reference_verified=False,
                    calibrated_intrinsics=False,usable_for_ffb=False))
    grouped=defaultdict(list)
    for r in pairs:
        grouped[r['model'],r['offset_hypothesis']].append(r)
    summary=[]
    for (model,hypothesis),group in sorted(grouped.items()):
        fields=('floor_observed_elevation_deg','floor_expected_elevation_deg','tip_observed_elevation_deg','tip_expected_elevation_deg',
                'floor_rotation_residual_deg','tip_rotation_residual_deg','observed_gap_deg','expected_gap_deg','gap_difference_deg')
        row=dict(model=model,offset_hypothesis=hypothesis,frames=len(group),offset_m=group[0]['offset_m'])
        row.update({f+'_median':float(np.median([r[f] for r in group])) for f in fields})
        row['gap_abs_difference_p95_deg']=float(np.percentile([abs(r['gap_difference_deg']) for r in group],95))
        summary.append(row)
    return floor7,all_paper,pairs,summary


def sensitivity(tips,anchor,models):
    tip=np.median([json.loads(r['native_colour_pair_json'])[0] for r in tips],axis=0)
    rows=[]
    for model,p in models.items():
        for hypothesis,offset in OFFSETS.items():
            for floor_dy in (-1.,0.,1.):
                floor=inspect_pixel(anchor+[0,floor_dy],p,reference_z_m=2.)
                for tip_dy in (-1.,0.,1.):
                    point=inspect_pixel(tip+[0,tip_dy],p,reference_z_m=2.+offset,reference_height_m=CONE_HEIGHT_M)
                    rows.append(dict(model=model,offset_hypothesis=hypothesis,floor_dy_px=floor_dy,tip_dy_px=tip_dy,
                        floor_rotation_residual_deg=floor['required_down_rotation_deg'],
                        tip_rotation_residual_deg=point['required_down_rotation_deg'],
                        gap_difference_deg=point['required_down_rotation_deg']-floor['required_down_rotation_deg'],
                        hypothetical_pixel_perturbation_not_new_measurement=True,usable_for_ffb=False))
    return rows


def degeneracy(models):
    camera,_=legacy_front_diagnostic_geometry(models['height_only59'])
    focal=camera.radius/(np.pi/2)
    elevations=np.array([-36.,-25.,-17.,-12.,0.,4.,10.])
    a=central_equidistant_pixels(elevations,focal_px=focal,cy=339.,pitch_deg=1.)
    cy2=339.+focal*np.deg2rad(5.)
    b=central_equidistant_pixels(elevations,focal_px=focal,cy=cy2,pitch_deg=6.)
    J=np.column_stack((np.ones(len(elevations)),np.full(len(elevations),-focal*np.pi/180)))
    singular=np.linalg.svd(J,compute_uv=False)
    return [dict(world_elevation_deg=float(e),cy1_px=339.,pitch1_deg=1.,cy2_px=cy2,pitch2_deg=6.,
                 pixel_y1=float(x),pixel_y2=float(y),difference_px=float(y-x),synthetic_central_meridian_only=True)
            for e,x,y in zip(elevations,a,b)],dict(focal_px=focal,synthetic_meridian_jacobian_rank=int(np.linalg.matrix_rank(J)),
                singular_values=singular.tolist(),max_pixel_difference=float(max(abs(a-b))),
                real_full_image_rank_not_evaluated=True,new_calibration_fit=False)


def plot(floor7,pairs,summary,repeat,output):
    os.environ.setdefault('MPLCONFIGDIR',str(output/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    r=next(r for r in summary if r['model']=='height_only59' and r['offset_hypothesis']=='axis_aligned_base_half')
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    x=np.arange(2)
    axes[0].bar(x-.18,[r['floor_expected_elevation_deg_median'],r['tip_expected_elevation_deg_median']],.36,label='expected from physical assumptions')
    axes[0].bar(x+.18,[r['floor_observed_elevation_deg_median'],r['tip_observed_elevation_deg_median']],.36,label='existing uncalibrated model')
    axes[0].set_xticks(x,['floor at2.00 m','tip at2.1875 m'])
    axes[0].set(ylabel='Forward-vertical elevation [deg]',title='Absolute directions share a large bias')
    axes[1].bar([0,1],[r['expected_gap_deg_median'],r['observed_gap_deg_median']])
    axes[1].set_xticks([0,1],['expected angular separation','observed angular separation'])
    axes[1].set(ylabel='Tip minus floor angle [deg]',title='Relative angular size is a separate constraint')
    axes[0].legend(fontsize=7)
    for ax in axes:
        ax.grid(axis='y',alpha=.2)
    fig.savefig(output/'absolute_vs_relative_bearing.png',dpi=150)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for model in ('height_only59','paper_centre2'):
        r=[q for q in floor7 if q['model']==model]
        values=[q['required_down_rotation_deg'] for q in r]
        p=next(q for q in summary if q['model']==model and q['offset_hypothesis']=='axis_aligned_base_half')
        axes[0].plot(range(8),values+[p['floor_rotation_residual_deg_median']],'o-',label=model)
    axes[0].set_xticks(range(8),[q['point_id'] for q in r]+['new19\n2.00m'],fontsize=8)
    axes[0].set(ylabel='Observed minus expected angle [deg]',title='Required angular residual; NOT an adopted pitch fit')
    a,b=repeat['paper7_native_pixel'],repeat['paper19_native_pixel']
    axes[1].plot([a[0],b[0]],[a[1],b[1]],'o-')
    axes[1].annotate('10/15 C200',a,xytext=(4,8),textcoords='offset points')
    axes[1].annotate('10/19',b,xytext=(4,8),textcoords='offset points')
    axes[1].invert_yaxis()
    axes[1].set(xlabel='Native X [px]',ylabel='Native Y [px]',title='Numerical pixel chart, NOT an edited camera image')
    axes[0].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    fig.savefig(output/'floor_references_and_repeatability.png',dpi=150)
    plt.close(fig)


def main():
    output=HERE/'results_r01'
    if output.exists():
        raise ValueError('no output overwrite')
    seven,paper,tips,anchor,models,metadata,hashes=load_inputs()
    floor7,paper_rows,pairs,summary=analyze(seven,paper,tips,anchor,models)
    perturbed=sensitivity(tips,anchor,models)
    synthetic,identifiability=degeneracy(models)
    old=next(r for r in seven if r['point_id']=='C200')
    old_pixel=[float(old['pixel_x']),float(old['pixel_y'])]
    repeat=dict(paper7_native_pixel=old_pixel,paper19_native_pixel=anchor.tolist(),
                **repeated_pixel_bound(old_pixel,anchor),corner_methods_differ=True,
                one_fixed_model_cannot_make_identical_points_project_to_two_different_pixels=True)
    assert all(sha256(Path(p))==digest for p,digest in hashes.items())
    output.mkdir()
    for name,rows in (('floor7_bearings.csv',floor7),('paper19_all_observations.csv',paper_rows),
                      ('cone19_paired_bearings.csv',pairs),('angle_gap_summary.csv',summary),
                      ('pixel_sensitivity.csv',perturbed),('synthetic_meridian_ambiguity.csv',synthetic)):
        write_csv(output/name,rows)
    for name,value in (('pixel_repeatability.json',repeat),('metadata_comparison.json',metadata),('synthetic_identifiability.json',identifiability)):
        (output/name).write_text(json.dumps(value,indent=2)+'\n')
    plot(floor7,pairs,summary,repeat,output)
    provenance=dict(status='COMPLETED_DIRECTION_CONSISTENCY_DIAGNOSTIC_NOT_CALIBRATION',
        physical_camera_height_m=CAMERA_HEIGHT_M,physical_cone_height_m=CONE_HEIGHT_M,models=models,
        floor7_independent_positions=7,paper19_frames=1733,paper19_primary_before_after_frames=631,
        cone_static_frames=299,paired_rows=len(pairs),new_calibration_fit=False,new_yolo_inference=False,
        original_images_edited=False,physical_output=False,live_tf=False,production_settings_changed=False,
        usable_for_ffb=False,source_sha256=hashes,output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(dict(metadata=metadata,repeat=repeat,synthetic=identifiability,
        primary=[r for r in summary if r['model']=='height_only59']),indent=2))


if __name__=='__main__':
    main()
