"""Audit user reference update and local-feature diagnostics without refitting."""
import json
from pathlib import Path
import statistics
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'src'))
from cone_dataset import read_csv,sha256


def main():
    target=HERE/'followup_verification.json'
    if target.exists():raise ValueError('no verification overwrite')
    for folder in ('results_r01','contact_transfer_r01','view_audit_r01','reference_update_r01'):
        root=HERE/folder
        report=json.loads((root/'provenance.json').read_text())
        for file,digest in report['source_sha256'].items():assert sha256(Path(file))==digest,file
        for name,digest in report.get('output_sha256',{}).items():assert sha256(root/name)==digest,name
    plot=HERE/'reference_plot_r01'
    provenance=json.loads((plot/'provenance.json').read_text())
    for file,digest in provenance['source_sha256'].items():assert sha256(Path(file))==digest,file
    assert sha256(plot/'cone_transfer_updated_reference.png')==provenance['graph_sha256']
    old=read_csv(HERE/'results_r01/cone_transfer_frames.csv')
    new=read_csv(HERE/'reference_update_r01/cone_transfer_frames_updated.csv')
    assert len(old)==len(new)==3596
    for a,b in zip(old,new):
        for key in ('condition','session','frame','baseline_x_m','baseline_z_m','candidate_x_m','candidate_z_m','baseline_used','candidate_used','usable_for_ffb'):
            assert a[key]==b[key],(key,a['frame'])
        assert float(a['reference_z_m'])==float(b['reference_z_m']) if a['reference_z_m'] else b['reference_z_m']==''
        if b['condition']=='left_130':assert float(b['reference_x_m'])==-.5875
        if b['condition']=='right_130':assert float(b['reference_x_m'])==.5875
    summaries=read_csv(HERE/'reference_update_r01/cone_transfer_summary_updated.csv')
    assert len(summaries)==5
    for summary in summaries:
        group=[r for r in new if r['condition']==summary['condition']]
        for prefix,flag in (('baseline','baseline_used'),('candidate','candidate_used')):
            selected=[r for r in group if r[flag]=='True']
            assert len(selected)==int(summary[prefix+'_used'])
            for axis in ('x','z'):
                truth=float(summary['reference_'+axis+'_m'])
                independent=statistics.median(float(r[prefix+'_'+axis+'_m'])-truth for r in selected)
                assert abs(independent-float(summary[prefix+'_error_'+axis+'_median_m']))<1e-12
    matches=read_csv(HERE/'view_audit_r01/local_feature_matches.csv')
    assert len(matches)==55
    accepted=[r for r in matches if r['reliable_for_local_feature_comparison']=='True']
    for r in accepted:
        assert float(r['ncc'])>=.8 and float(r['separated_peak_margin'])>=.02
        assert float(r['reverse_return_error_px'])<=1
        if r['group'] in ('within_floor','within_cone'):
            assert r['delta_x_current_minus_reference_px']=='0' and r['delta_y_current_minus_reference_px']=='0'
    result=dict(status='PASS_FOLLOWUP_HASH_REFERENCE_AND_LOCAL_DIAGNOSTIC_CHECKS_NOT_CALIBRATION_APPROVAL',
        predicted_cone_coordinates_unchanged=3596,updated_reference_summaries_verified=5,
        forward_edge_distances_unchanged=True,side_reference_centre_abs_x_m=.5875,
        side_reference_orientation_assumption_preserved=True,local_comparisons_retained=55,
        local_comparisons_accepted=len(accepted),production_settings_changed=False,physical_output=False,
        verification_script_sha256=sha256(Path(__file__)))
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
