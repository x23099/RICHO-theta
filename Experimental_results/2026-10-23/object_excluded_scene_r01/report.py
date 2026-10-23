"""Matched detector stream coverage and support-exclusion comparison."""
from collections import Counter
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from analyze import HERE,ROOT,BANDS,SUPPORT,UNIFORM,MODES,load_saved_boxes
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import angle_degrees


def main():
    output=HERE/'report_r01'
    if output.exists():raise ValueError('new report output required')
    results=HERE/'results_r01';manifest=json.loads((results/'summary.json').read_text())
    for name,h in manifest['output_sha256'].items():assert sha256(results/name)==h
    samples=read_csv(UNIFORM/'intake_r01/native_sample_manifest.csv')
    frame_index,predictions,_,box_sources=load_saved_boxes(samples)
    sources={str(p):sha256(p) for p in (HERE/'report.py',results/'summary.json',results/'image_diagnostics.csv',
        results/'session_hypotheses.csv',results/'line_object_overlap.csv',results/'bbox_coverage.csv',
        SUPPORT/'results_r01/actual_lower_support.csv',SUPPORT/'results_r01/lower_inlier_support.csv',
        UNIFORM/'intake_r01/native_sample_manifest.csv')}
    sources.update(box_sources)
    frames=read_csv(results/'image_diagnostics.csv');sessions=read_csv(results/'session_hypotheses.csv')
    masks=read_csv(results/'line_object_overlap.csv')
    mask_index={(r['session'],r['frame'],r['band'],r['line_index'],r['part']):r for r in masks}
    actual={(r['session'],r['frame'],r['fusion_index']):r for r in read_csv(SUPPORT/'results_r01/actual_lower_support.csv')}
    suspect_rows=[]
    for r in read_csv(SUPPORT/'results_r01/lower_inlier_support.csv'):
        if r['newly_accepted_image']!='True':continue
        pixels=actual[r['session'],r['frame'],r['fusion_index']]
        mask=mask_index[r['session'],r['frame'],'lower',pixels['line_index'],pixels['part']]
        suspect_rows.append(dict(session=r['session'],frame=r['frame'],fusion_index=r['fusion_index'],
            original_seam_continuation_possible=r['seam_continuation_possible'],
            lower_first_native_json=r['lower_first_native_json'],lower_last_native_json=r['lower_last_native_json'],
            overlap_pixels=mask['overlap_pixels'],support_pixels=mask['support_pixels'],overlap_fraction=mask['overlap_fraction'],
            object_overlap=mask['object_overlap'],matched_prediction_indices_json=mask['matched_prediction_indices_json'],
            semantic_surface_label_human_verified=False,usable_for_ffb=False))
    comparison=[]
    for mode in MODES:
        group=[r for r in frames if r['mode']==mode];common=[r for r in group if r['bbox_stream_available']=='True']
        comparison.append(dict(mode=mode,total_images=len(group),images_with_saved_bbox_stream=len(common),
            accepted_all_images=sum(r['accepted']=='True' for r in group),
            accepted_common_176_images=sum(r['accepted']=='True' for r in common),
            temporal_candidate_sessions=sum(r['temporal_candidate_eligible']=='True' for r in sessions if r['mode']==mode),
            bbox_stream_unsupported_images=sum(r['bbox_stream_available']=='False' for r in group),usable_for_ffb=False))
    index={(r['session'],r['frame'],r['mode']):r for r in frames}
    paired=[]
    for r in (x for x in frames if x['mode']=='original_fusion'):
        row=dict(session=r['session'],frame=r['frame'],bbox_stream_available=r['bbox_stream_available'])
        for mode in MODES:row[mode+'_accepted']=index[r['session'],r['frame'],mode]['accepted']
        screened=index[r['session'],r['frame'],'object_screen']
        row['original_to_object_direction_delta_deg']=angle_degrees(json.loads(r['up_optical_json']),json.loads(screened['up_optical_json'])) if r['accepted']=='True' and screened['accepted']=='True' else None
        paired.append(row)
    output.mkdir();write_csv(output/'mode_comparison.csv',comparison)
    write_csv(output/'previous_new_lower_support_screen.csv',suspect_rows);write_csv(output/'paired_images.csv',paired)
    # Record exact same-frame native boxes; no rectified/model-size coordinate inference.
    box_rows=[]
    for sample in samples:
        key=sample['session'],int(sample['frame'])
        if key in frame_index:
            box_rows.extend(dict(session=key[0],frame=key[1],prediction_index=p['prediction_index'],confidence=p['confidence'],
                x1=p['x1'],y1=p['y1'],x2=p['x2'],y2=p['y2'],native_width=1280,native_height=720) for p in predictions[key])
    write_csv(output/'sampled_native_boxes.csv',box_rows)
    labels=['Original fusion','Object bbox only','Old duplicate\nreferences only','Both screens']
    fig,axes=plt.subplots(1,2,figsize=(11,4.8))
    axes[0].bar(range(4),[r['accepted_common_176_images'] for r in comparison],color=['#888888','#2980b9','#c49a38','#2a9d8f'])
    axes[0].set_ylabel('Accepted pose hypotheses / common 176 images')
    axes[1].bar(range(4),[r['temporal_candidate_sessions'] for r in comparison],color=['#888888','#2980b9','#c49a38','#2a9d8f'])
    axes[1].set_ylabel('Temporally checked sessions (NOT metric accuracy)')
    for ax in axes:
        ax.set_xticks(range(4));ax.set_xticklabels(labels,rotation=18,ha='right',fontsize=8);ax.grid(axis='y',alpha=.2)
    fig.suptitle('Saved native cone detections, no new inference or distance labels\n316 images lack this detector stream; object-screen modes explicitly withhold them')
    fig.tight_layout();fig.savefig(output/'object_and_reference_exclusion.png',dpi=150);plt.close(fig)
    record=dict(status='COMPLETED_OBJECT_SUPPORT_EXCLUSION_REPORT_NOT_GATE_ADOPTION',work_date='2026-10-23',source_sha256=sources,
        reviewed_new_lower_supports=len(suspect_rows),new_supports_overlapping_saved_boxes=sum(r['object_overlap']=='True' for r in suspect_rows),
        source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    assert all(sha256(__import__('pathlib').Path(p))==h for p,h in sources.items())
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
