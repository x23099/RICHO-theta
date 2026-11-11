"""Audit second CUDA upload and compare it with verified first-run artifacts.

No model, environment changes, camera, network, ROS or vehicle control.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01'))
import audit as checker
replay=checker.replay

COMPARISON_FIELDS=('frame','original_distance_available','original_range_m',
    'comparison_distance_available','comparison_range_m','comparison_support_pixel',
    'reason','baseline_reproduced','reference_generation','reference_frame',
    'reference_scope_verified','reference_used_posthoc','main_display_modified',
    'body_review_reason','lower_half_pixel_eligible',*replay.FLAGS)


def cross_run(old_dir,payload,*,expected_sources=None):
    old_summary=replay.parse_json((old_dir/'summary.json').read_bytes())
    new_summary=replay.parse_json(payload['summary.json'])
    require=checker.require
    require(old_summary['weights_sha256']==new_summary['weights_sha256'],'cross-run checkpoint changed')
    require({Path(k).name:v for k,v in old_summary['input_sha256'].items()}==
        {Path(k).name:v for k,v in new_summary['input_sha256'].items()},'cross-run input hashes changed')
    primary_equal=detector_equal=compared=0;comparison_equal=comparison_total=0
    input_hashes={str(old_dir/'summary.json'):replay.hash_regular(old_dir/'summary.json',16*1024*1024)}
    for i,enabled in enumerate((False,True,True,False)):
        label=f'block_{i:02d}_{"on" if enabled else "off"}'
        name=label+'/primary_frames.jsonl';old_path=old_dir/name
        old=checker.rows(old_path.read_bytes());new=checker.rows(payload[name])
        input_hashes[str(old_path)]=replay.hash_regular(old_path,16*1024*1024)
        require(len(old)==len(new)==160,'unpaired cross-run primary rows')
        for a,b in zip(old,new):
            require((a['frame'],a['original_frame'],a['input_pixel_sha256'])==
                (b['frame'],b['original_frame'],b['input_pixel_sha256']),'cross-run frame identity differs')
            primary_equal+=replay.primary_signature(a)==replay.primary_signature(b)
            detector_equal+=replay.detector_values(a['raw_detector_boxes'])==replay.detector_values(b['raw_detector_boxes'])
            compared+=1
        if enabled:
            name=label+'/comparison/comparison_frames.jsonl';old_path=old_dir/name
            old=checker.rows(old_path.read_bytes());new=checker.rows(payload[name])
            input_hashes[str(old_path)]=replay.hash_regular(old_path,16*1024*1024)
            require(len(old)==len(new)==161,'unpaired cross-run comparison rows')
            for a,b in zip(old,new):
                comparison_equal+=all(a.get(k)==b.get(k) for k in COMPARISON_FIELDS)
                comparison_total+=1
    changed=sorted(name for name in set(old_summary['source_sha256'])|set(new_summary['source_sha256'])
        if old_summary['source_sha256'].get(name)!=new_summary['source_sha256'].get(name))
    expected_sources=expected_sources if expected_sources is not None else [
        'src/cone_guarded_stream_comparison.py','src/cone_motion_range.py']
    require(changed==sorted(expected_sources),
        'unexpected cross-run code changes')
    metrics=[]
    def throughput(summary,enabled):
        blocks=[b for b in summary['blocks'] if b['comparison_enabled'] is enabled]
        return sum(b['measured_frames'] for b in blocks)/sum(b['measured_wall_sec'] for b in blocks)
    for condition,enabled in (('off',False),('on',True)):
        for measure in ('predict_ms','primary_ms','primary_log_and_tap_ms','start_interval_ms'):
            for percentile in ('p50','p95'):
                a=old_summary['groups'][condition][measure][percentile]
                b=new_summary['groups'][condition][measure][percentile]
                metrics.append(dict(condition=condition,metric=measure+'_'+percentile,unit='ms',
                    before=a,after=b,change_percent=100*(b/a-1)))
        a,b=throughput(old_summary,enabled),throughput(new_summary,enabled)
        metrics.append(dict(condition=condition,metric='measured_block_throughput',unit='frames/sec',
            before=a,after=b,change_percent=100*(b/a-1)))
        a,b=(s['groups'][condition]['period_overruns'] for s in (old_summary,new_summary))
        metrics.append(dict(condition=condition,metric='primary_over_33p33ms_count',unit='frames/320',
            before=a,after=b,change_percent=100*(b/a-1) if a else None))
    return dict(primary_pairs=compared,primary_equal=primary_equal,detector_equal=detector_equal,
        comparison_pairs=comparison_total,comparison_equal=comparison_equal,
        changed_source_files=changed,same_input_hashes=True,
        gpu_metadata_equal=old_summary['gpu']==new_summary['gpu'],
        runtime_versions_equal=old_summary['runtime_versions']==new_summary['runtime_versions'],
        metrics=metrics,input_sha256=input_hashes,
        NOT_independent_accuracy_or_latency_validation=True),metrics


def main(defaults=None,extra_sources=()):
    defaults={} if defaults is None else defaults
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--archive-root',default=defaults.get('archive_root','guarded_cuda_gpu_r02'))
    parser.add_argument('--previous-dir',type=Path,default=defaults.get('previous_dir',ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r01'))
    parser.add_argument('--previous-audit',type=Path,default=defaults.get('previous_audit',ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01/results_r01/audit.json'))
    parser.add_argument('--expected-source',nargs='+',default=defaults.get('expected_sources'))
    args=parser.parse_args()
    checker.require(not args.intake_dir.exists() and not args.output_dir.exists(),'new output directories required')
    payload=checker.archive_payload(args.archive,prefix=args.archive_root)
    base=ROOT/'recordings/2026-11-10/driver_motion_171250_intake_r01'
    data=replay.load_inputs(base/'driver_motion_live_20261110_171250',base/'motion_withheld_20261110_171250')
    report,primary,comparison=checker.audit(payload,data,expected_source_count=defaults.get('expected_source_count',24))
    previous=args.previous_dir.resolve()
    # Verify all old artifacts that are consumed against the recorded first audit.
    old_report_path=args.previous_audit.resolve()
    old_audit=replay.parse_json(old_report_path.read_bytes())
    cross,metrics=cross_run(previous,payload,expected_sources=args.expected_source)
    for name,digest in cross['input_sha256'].items():
        relative=str(Path(name).relative_to(previous))
        checker.require(digest==old_audit['supplied_files_sha256'][relative],'previous artifact modified')
    report.update(schema=defaults.get('schema','guarded_cuda_gpu_reuse_archive_audit_v1'),
        archive_sha256=replay.hash_regular(args.archive,64*1024*1024),
        source_sha256={str(path.relative_to(ROOT)):replay.hash_regular(path,512*1024)
            for path in (Path(__file__),Path(checker.__file__),*extra_sources)},
        supplied_files_sha256={name:replay.digest_bytes(blob) for name,blob in sorted(payload.items())},
        previous_audit_sha256=replay.hash_regular(old_report_path,512*1024),cross_run=cross,
        performance_decision=('30fps_p95_budget_not_met_in_saved_image_sample'
            if report['groups']['on']['primary_ms']['p95']>1000/30 else
            'p95_budget_met_in_saved_image_sample_NOT_live_validation'))
    for name,blob in payload.items():
        path=args.intake_dir/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(blob)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for name,records in (('primary_timing.csv',primary),('comparison_timing.csv',comparison),('before_after.csv',metrics)):
        with (args.output_dir/name).open('x',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    print(json.dumps({key:report[key] for key in ('state','primary_rows_checked','primary_equal_pairs',
        'comparison_rows_checked','comparison_numeric_rows','performance_decision')},indent=2))
    print(json.dumps({key:cross[key] for key in ('primary_pairs','primary_equal','detector_equal',
        'comparison_pairs','comparison_equal','changed_source_files')},indent=2))


if __name__=='__main__':main()
