"""Compare support correspondence only; no raw image editing, fit, or live I/O."""
from collections import defaultdict,Counter
import argparse
import json
import os
from pathlib import Path
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
HEIGHT=HERE.parent/'cone_known_height_pinhole_r01'
sys.path.insert(0,str(HEIGHT))
import analyze_height as previous
from known_height import height_position,empty,HEIGHT_M,BASE_HALF_M
from known_width import VIRTUAL_K
from fisheye_floor_geometry import legacy_front_diagnostic_geometry
from cone_dataset import read_csv,write_csv,sha256
from plumb_support import select_base

METHODS={'plumb_vertical':('colour_vertical_proxy',0.),
         'plumb_near_edge_assumption':('colour_near_edge_offset_assumption',BASE_HALF_M)}


def key(r):
    return r['dataset'],r['session'],int(r['frame'])


def load_inputs():
    hashes={}
    for folder in (HEIGHT,previous.WIDTH):
        p=json.loads((folder/'results_r01/provenance.json').read_text())
        for path,digest in p['source_sha256'].items():
            assert sha256(Path(path))==digest,path
        for name,digest in p['output_sha256'].items():
            assert sha256(folder/'results_r01'/name)==digest,name
        hashes[str(folder/'results_r01/provenance.json')]=sha256(folder/'results_r01/provenance.json')
    provenance=json.loads((HEIGHT/'results_r01/provenance.json').read_text())
    paths=[HEIGHT/'results_r01/observed_pixels.csv',HEIGHT/'results_r01/all_frame_estimates.csv',
           previous.DAY19/'cone_support_extent_r01/results_r01/lower_envelopes.csv',
           previous.WIDTH/'results_r01/additional_full_envelopes.csv',HERE/'method.md',
           Path(__file__),HERE/'plumb_support.py',HEIGHT/'known_height.py',
           ROOT/'src/fisheye_floor_geometry.py']
    hashes.update({str(p):sha256(p) for p in paths})
    pixels=read_csv(paths[0])
    assert len(pixels)==6876 and len({key(r) for r in pixels})==6876
    baseline={(key(r),r['model'],r['method']):r for r in read_csv(paths[1]) if r['method']!='bbox_vertical_control'}
    envelopes=defaultdict(list)
    for path in paths[2:4]:
        for r in read_csv(path):
            envelopes[key(r)].append([float(r['x']),float(r['y'])])
    return pixels,baseline,{k:np.asarray(v) for k,v in envelopes.items()},provenance['models'],hashes


def replay(pixels,baseline,envelopes,models):
    rows=[]
    for source in pixels:
        oldpair=json.loads(source['native_colour_pair_json']) if source['native_colour_pair_json'] else None
        env=envelopes.get(key(source))
        for model,parameters in models.items():
            camera,T=legacy_front_diagnostic_geometry(parameters)
            for method,(old_method,offset) in METHODS.items():
                prior=baseline[key(source),model,old_method]
                row=dict(dataset=source['dataset'],session=source['session'],frame=int(source['frame']),
                    time_sec=float(source['time_sec']),condition=source['condition'],
                    reference_z_m=float(source['reference_z_m']) if source['reference_z_m'] else None,
                    quality_accepted=source['quality_accepted']=='True',model=model,method=method,
                    tip_forward_offset_m=offset,native_tip_json=json.dumps(oldpair[0]) if oldpair else '',
                    old_base_json=json.dumps(oldpair[1]) if oldpair else '',native_base_json='',
                    old_height_z_m=float(prior['z_forward_m']) if prior['estimated']=='True' else None,
                    old_height_residual_m=float(prior['residual_m']) if prior['residual_m'] else None,
                    old_height_base_height_m=float(prior['base_height_m']) if prior['base_height_m'] else None,
                    old_width_z_m=float(source['previous_width_z_m']) if source['previous_width_z_m'] else None,
                    base_shift_x_px=None,base_shift_y_px=None,line_distance_px=None,
                    pixel_consistent=False,support_columns=None,root_groups=None,
                    projected_line_json='',rectified_pair_json='',selected=False)
                if oldpair is None or env is None:
                    row.update(empty('no_observed_tip_or_envelope'))
                else:
                    selection=select_base(oldpair[0],env,camera,VIRTUAL_K,T,height_m=HEIGHT_M,offset_m=offset)
                    row.update(selected=selection['selected'],support_columns=selection.get('support_columns'),
                               root_groups=selection.get('root_groups'))
                    row['projected_line_json']=json.dumps(selection['projected_line_json']) if 'projected_line_json' in selection else ''
                    if not selection['selected']:
                        row.update(empty(selection['reason']))
                    else:
                        uv=np.array([selection['tip_rectified'],selection['point_rectified']])
                        row.update(height_position(uv,VIRTUAL_K,T,height_m=HEIGHT_M,tip_forward_offset_m=offset),
                            rectified_pair_json=json.dumps(uv.tolist()),native_base_json=json.dumps(selection['point_native']),
                            base_shift_x_px=float(selection['point_native'][0]-oldpair[1][0]),
                            base_shift_y_px=float(selection['point_native'][1]-oldpair[1][1]),
                            line_distance_px=selection['line_distance_px'],pixel_consistent=selection['pixel_consistent'])
                rows.append(row)
    return rows


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[r['dataset'],r['condition'],r['model'],r['method']].append(r)
    output=[]
    for (dataset,condition,model,method),group in sorted(groups.items()):
        for population in ('all_estimates','matched_previous_height','matched_width','support_time_accepted'):
            selected=[r for r in group if r['estimated'] and (population=='all_estimates'
                or population=='matched_previous_height' and r['old_height_z_m'] is not None
                or population=='matched_width' and r['old_width_z_m'] is not None
                or population=='support_time_accepted' and r['quality_accepted'])]
            ref=group[0]['reference_z_m']
            med=lambda field:float(np.median([r[field] for r in selected])) if selected else None
            vals=lambda field:np.array([r[field] for r in selected])
            errors=vals('z_forward_m')-ref if ref is not None else None
            old=vals('old_height_z_m')-ref if ref is not None and population=='matched_previous_height' else None
            output.append(dict(dataset=dataset,condition=condition,model=model,method=method,population=population,
                frames=len(group),estimated_frames=len(selected),estimated_fraction=len(selected)/len(group),
                reference_z_m=ref,z_median_m=med('z_forward_m'),
                z_bias_m=float(np.median(errors)) if errors is not None and len(errors) else None,
                z_abs_error_p95_m=float(np.percentile(abs(errors),95)) if errors is not None and len(errors) else None,
                z_abs_error_max_m=float(max(abs(errors))) if errors is not None and len(errors) else None,
                old_height_z_median_m=med('old_height_z_m') if population=='matched_previous_height' else None,
                old_height_p95_m=float(np.percentile(abs(old),95)) if old is not None and len(old) else None,
                old_width_z_median_m=med('old_width_z_m') if population=='matched_width' else None,
                base_height_median_m=med('base_height_m'),residual_median_m=med('residual_m'),
                old_residual_median_m=med('old_height_residual_m') if population=='matched_previous_height' else None,
                old_base_height_median_m=med('old_height_base_height_m') if population=='matched_previous_height' else None,
                base_shift_x_median_px=med('base_shift_x_px'),base_shift_y_median_px=med('base_shift_y_px'),
                line_distance_median_px=med('line_distance_px'),consistent_frames=sum(r['segment_consistent'] for r in selected),
                outside_range_frames=sum(not r['in_diagnostic_range'] for r in selected),
                missing_reasons=json.dumps(dict(Counter(r['reason'] for r in group if not r['estimated']))),
                physical_endpoint_correspondence_verified=False,usable_for_ffb=False))
    return output


def plot(summary,rows,output):
    os.environ.setdefault('MPLCONFIGDIR',str(output/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    methods=list(METHODS)
    fig,axes=plt.subplots(3,1,figsize=(11,9),layout='constrained')
    for i,method in enumerate(methods):
        chosen=[r for r in summary if r['model']=='height_only59' and r['method']==method and r['population']=='matched_previous_height' and r['reference_z_m'] is not None]
        x=np.arange(len(chosen))
        axes[0].plot(x,[r['z_median_m'] for r in chosen],'o-',label=method)
        axes[0].plot(x,[r['old_height_z_median_m'] for r in chosen],'x--',label='old same-X / '+method)
        axes[1].plot(x,[r['base_height_median_m'] for r in chosen],'o-',label=method)
        axes[2].bar(x+(i-.5)*.35,[r['estimated_fraction'] for r in chosen],.34,label=method)
    axes[0].plot(x,[r['reference_z_m'] for r in chosen],'k_',ms=20,label='nominal near-edge Z')
    axes[0].set(ylabel='Forward Z [m]',title='Same frames: selection uses projection, NOT nominal Z')
    axes[1].axhline(0,c='k',ls='--')
    axes[1].set(ylabel='Base height [m]',title='Floor inconsistency retained; low segment residual is NOT independent proof')
    axes[2].set(ylabel='Estimated / ALL frames',ylim=(0,1.05),title='Missing support is rejected, not extrapolated')
    for ax in axes:
        ax.set_xticks(x,[r['dataset'].replace('paper_cone_20261019','new19')+'\n'+r['condition'] for r in chosen],fontsize=8)
        ax.legend(fontsize=7)
        ax.grid(axis='y',alpha=.2)
    fig.savefig(output/'plumb_support_comparison.png',dpi=150)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for method in methods:
        group=[r for r in rows if r['dataset']=='sequence' and r['model']=='height_only59' and r['method']==method and 1100<=r['frame']<=1160]
        axes[0].plot([r['frame'] for r in group],[r['z_forward_m'] if r['estimated'] else np.nan for r in group],'.-',label=method)
        chosen=[r for r in summary if r['model']=='height_only59' and r['method']==method and r['population']=='matched_previous_height' and r['reference_z_m'] is not None]
        axes[1].plot(range(len(chosen)),[r['base_shift_x_median_px'] for r in chosen],'o-',label=method)
    axes[0].axhline(2.,c='k',ls='--')
    axes[0].set(xlabel='Original frame',ylabel='Forward Z [m]',title='Occlusion / recovery; missing stays missing')
    axes[1].set(xlabel='Conditions in comparison order',ylabel='Native X column change [px]',title='Actual observed columns only; no image editing')
    for ax in axes:
        ax.legend(fontsize=7)
        ax.grid(alpha=.2)
    fig.savefig(output/'plumb_support_occlusion_and_shifts.png',dpi=150)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=HERE/'results_r02')
    output=parser.parse_args().output_dir
    if output.exists():
        raise ValueError('new output required; no overwrite')
    pixels,baseline,envelopes,models,hashes=load_inputs()
    rows=replay(pixels,baseline,envelopes,models)
    summary=summarize(rows)
    assert len(rows)==6876*6 and all(not r['usable_for_ffb'] for r in rows)
    assert all(sha256(Path(p))==v for p,v in hashes.items())
    screen={}
    for method in METHODS:
        selected=[r for r in summary if r['model']=='height_only59' and r['method']==method and r['population']=='all_estimates' and r['reference_z_m'] is not None]
        failures=[dict(dataset=r['dataset'],condition=r['condition'],bias=r['z_bias_m'],p95=r['z_abs_error_p95_m']) for r in selected
                  if r['z_bias_m'] is None or abs(r['z_bias_m'])>.1 or r['z_abs_error_p95_m']>.2]
        screen[method]=dict(evaluation_conditions=len(selected),failures=failures,
            decision='DEFER_PHYSICAL_CORRESPONDENCE_AND_CALIBRATION',distance_screen_passes=len(selected)-len(failures))
    output.mkdir()
    write_csv(output/'all_frame_estimates.csv',rows)
    write_csv(output/'summary.csv',summary)
    (output/'screen.json').write_text(json.dumps(screen,indent=2)+'\n')
    plot(summary,rows,output)
    (output/'provenance.json').write_text(json.dumps(dict(frames=len(pixels),rows=len(rows),models=models,
        methods=METHODS,height_m=HEIGHT_M,geometry_or_size_fit=False,new_yolo_inference=False,raw_images_edited=False,
        physical_output=False,live_tf=False,production_settings_changed=False,usable_for_ffb=False,
        source_sha256=hashes,output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()}),indent=2)+'\n')
    print(json.dumps(dict(screen=screen,primary=[r for r in summary if r['model']=='height_only59' and r['population']=='matched_previous_height' and r['reference_z_m'] is not None]),indent=2))


if __name__=='__main__':
    main()
