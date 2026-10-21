"""Keep every metric row; join prior quality flags without enforcing a new gate."""
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'outlier_audit_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    observation_path=HERE.parent/'cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    metric_path=HERE/'curve_results_r01/cone_all_frames.csv'
    sources={str(p):sha256(p) for p in (observation_path,metric_path,Path(__file__))}
    observed={(r['session'],r['frame']):r for r in read_csv(observation_path)}
    metric=read_csv(metric_path)
    assert len(metric)==len(observed)==6876
    assert {(r['session'],r['frame']) for r in metric}==set(observed)
    joined=[];groups=defaultdict(list)
    for r in metric:
        source=observed[r['session'],r['frame']]
        error=float(r['floor_forward_m'])-float(r['reference_z_m']) if r['estimated']=='True' and r['reference_z_m'] else None
        row=dict(dataset=r['dataset'],session=r['session'],frame=int(r['frame']),time_sec=float(source['time_sec']),
            condition=r['condition'],estimated=r['estimated']=='True',reference_z_m=r['reference_z_m'],
            floor_forward_m=r['floor_forward_m'],error_z_m=error,
            diagnostic_abs_error_over_20cm=abs(error)>.2 if error is not None else None,
            original_quality_accepted=source['quality_accepted']=='True',colour_reason=source['colour_reason'],
            native_colour_pair_json=source['native_colour_pair_json'],removed_from_metrics=False,usable_for_ffb=False)
        joined.append(row)
        if error is not None:groups[r['dataset'],r['condition']].append(row)
    summary=[]
    for (dataset,condition),rows in sorted(groups.items()):
        errors=np.array([r['error_z_m'] for r in rows]);bad=[r for r in rows if r['diagnostic_abs_error_over_20cm']]
        summary.append(dict(dataset=dataset,condition=condition,estimated_reference_frames=len(rows),
            median_bias_m=float(np.median(errors)),abs_error_p95_m=float(np.percentile(abs(errors),95)),
            maximum_abs_error_m=float(abs(errors).max()),over20cm_frames=len(bad),
            outlier_frames_json=json.dumps([r['frame'] for r in bad]),
            outliers_previously_quality_rejected=sum(not r['original_quality_accepted'] for r in bad),
            rows_removed=0,usable_for_ffb=False))
    assert all(sha256(Path(p))==v for p,v in sources.items())
    output.mkdir()
    write_csv(output/'all_frame_quality_join.csv',joined)
    write_csv(output/'condition_summary.csv',summary)
    record=dict(status='COMPLETED_ALL_ROWS_RETAINED_OUTLIER_AUDIT',source_sha256=sources,
        rows=len(joined),rows_removed=0,threshold_is_diagnostic_not_safety_requirement=True,
        production_gate_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
