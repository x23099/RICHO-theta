"""Analytical availability-only control: no new geometry or physical output."""
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/'src'),str(HERE.parent/'causal_pose_replay_r01')]
from cone_dataset import read_csv,write_csv,sha256


def hold_for_newer_input(latest_released_frame,latest_completed_frame):
    if type(latest_released_frame) is not int or type(latest_completed_frame) is not int or min(latest_released_frame,latest_completed_frame)<0:
        raise ValueError('explicit nonnegative frame counters required')
    if latest_completed_frame>latest_released_frame:raise ValueError('completion cannot precede its release')
    return latest_released_frame>latest_completed_frame


def main():
    output=HERE/'pending_control_r01'
    if output.exists():raise ValueError('new control output required')
    results=HERE/'results_r01';proof=json.loads((results/'summary.json').read_text())
    for name,h in proof['output_sha256'].items():assert sha256(results/name)==h
    paths=[Path(__file__),HERE/'pending_hold_method.md',results/'summary.json',results/'completion_frame_metrics.csv',results/'scene_job_schedule.csv']
    sources={str(p):sha256(p) for p in paths};inputs=read_csv(paths[3]);jobs=read_csv(paths[4])
    output_rows=[];summary=[]
    for scenario in sorted({r['scenario'] for r in inputs}):
        scheduled=[r for r in jobs if r['scenario']==scenario];cursor=0;latest=0;rows=[]
        for r in (r for r in inputs if r['scenario']==scenario):
            t=float(r['time_sec'])
            while cursor<len(scheduled) and float(scheduled[cursor]['release_sec'])<=t:
                latest=int(scheduled[cursor]['frame']);cursor+=1
            pending=hold_for_newer_input(latest,int(r['latest_completed_scene_frame']))
            was_available=r['diagnostic_available']=='True';available=was_available and not pending
            row=dict(r,latest_released_scene_frame=latest,newer_scene_input_pending=pending,
                before_control_diagnostic_available=was_available,before_control_diagnostic_z_m=r['diagnostic_z_m'],
                diagnostic_available=available,diagnostic_z_m=r['diagnostic_z_m'] if available else '',
                control_reason='newer_scene_input_not_finished' if pending else 'original_diagnostic_conditions_unchanged')
            rows.append(row);output_rows.append(row)
        summary.append(dict(scenario=scenario,frames=len(rows),before_control_diagnostic_frames=sum(r['before_control_diagnostic_available'] for r in rows),
            after_control_diagnostic_frames=sum(r['diagnostic_available'] for r in rows),
            diagnostic_frames_removed=sum(r['before_control_diagnostic_available'] and not r['diagnostic_available'] for r in rows),
            outputs_with_newer_unfinished_rejection=sum(r['diagnostic_available'] and r['newer_unfinished_rejection_posthoc']=='True' for r in rows),
            new_values_computed=False,physical_output=False,usable_for_ffb=False))
    output.mkdir();write_csv(output/'pending_control_frame_metrics.csv',output_rows);write_csv(output/'pending_control_summary.csv',summary)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    record=dict(status='COMPLETED_PENDING_INPUT_HOLD_CONTROL_NOT_PRODUCTION_GATE',work_date='2026-10-23',source_sha256=sources,
        summaries=summary,source_images_edited=False,new_geometry_computed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
