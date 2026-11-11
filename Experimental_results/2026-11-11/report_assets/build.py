"""Build report plots from audited GPU results and copy one native PNG unchanged."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'Experimental_results/2026-11-11'
NATIVE='decoded_4c34c8c3d6d44949afb2e921e819e563_f014922'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).parent)
    args=parser.parse_args();out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    names=['gpu_primary_p95.png','gpu_throughput.png','gpu_performance.csv',NATIVE+'.png','manifest.json']
    if any((out/name).exists() for name in names):raise ValueError('new report asset outputs required')
    audit_paths=[BASE/f'guarded_cuda_gpu_audit_r{i:02d}/results_r01/audit.json' for i in range(1,5)]
    audits=[json.loads(path.read_bytes()) for path in audit_paths]
    if any(a['state']!='pass' or a['primary_rows_checked']!=640 or a['primary_equal_pairs']!=320
           or a['comparison_rows_checked']!=322 or a['comparison_numeric_rows']!=40 for a in audits):
        raise ValueError('expected verified four GPU runs required')
    if any(a['cross_run']['primary_equal']!=640 or a['cross_run']['comparison_equal']!=322 for a in audits[1:]):
        raise ValueError('cross-run identity must be maintained')
    records=[]
    for i,audit in enumerate(audits,1):
        for enabled in (False,True):
            group=audit['groups']['on' if enabled else 'off']
            blocks=[b for b in audit['blocks'] if b['comparison_enabled'] is enabled]
            records.append(dict(run=f'r{i:02d}',comparison_enabled=enabled,
                measured_frames=group['measured_frames'],primary_p50_ms=group['primary_ms']['p50'],
                primary_p95_ms=group['primary_ms']['p95'],primary_max_ms=group['primary_ms']['max'],
                start_interval_p95_ms=group['start_interval_ms']['p95'],
                throughput_fps=group['measured_frames']/sum(b['measured_wall_sec'] for b in blocks),
                primary_over_33p33ms_count=group['period_overruns'],
                comparison_service_p95_ms=audit['comparison_service_ms']['p95'] if enabled else None,
                comparison_age_p95_ms=audit['comparison_age_ms']['p95'] if enabled else None))
    evidence=ROOT/'recordings/2026-11-10/driver_motion_171250_intake_r01/motion_withheld_20261110_171250'
    image_path=evidence/(NATIVE+'.png');sidecar_path=evidence/(NATIVE+'.json');index_path=evidence/'evidence_index.jsonl'
    meta=json.loads(sidecar_path.read_bytes())
    item=next(json.loads(line) for line in index_path.read_bytes().splitlines() if json.loads(line)['frame']==14922)
    if not (meta['session']=='4c34c8c3d6d44949afb2e921e819e563' and meta['frame']==14922
            and meta['image_modified'] is False and sha(image_path)==meta['png_sha256']==item['png_sha256']
            and sha(sidecar_path)==item['sidecar_sha256']):raise ValueError('native image provenance mismatch')
    import cv2
    decoded=cv2.imread(str(image_path),cv2.IMREAD_COLOR)
    if decoded is None or decoded.shape!=(720,1280,3) or hashlib.sha256(decoded.tobytes()).hexdigest()!=meta['decoded_bgr_sha256']:
        raise ValueError('native pixels mismatch')
    inputs={str(path.relative_to(ROOT)):sha(path) for path in (*audit_paths,image_path,sidecar_path,index_path)}
    with tempfile.TemporaryDirectory(prefix='theta_daily_matplotlib_') as cache:
        os.environ['MPLCONFIGDIR']=cache
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        x=np.arange(4);width=.36
        labels=['r01\nBaseline comparison','r02\nSingle observation','r03\nCompact diagnostics','r04\nDomain only']
        for filename,field,title,ylabel,limit in (
            ('gpu_primary_p95.png','primary_p95_ms','Saved-image CUDA benchmark: primary processing P95','Milliseconds',1000/30),
            ('gpu_throughput.png','throughput_fps','Saved-image CUDA benchmark: measured throughput','Frames / second',30.)):
            fig,ax=plt.subplots(figsize=(10,5.2),layout='constrained')
            for enabled,offset,colour in ((False,-width/2,'#727b86'),(True,width/2,'#007f87')):
                values=[r[field] for r in records if r['comparison_enabled'] is enabled]
                bars=ax.bar(x+offset,values,width,label='Comparison ON' if enabled else 'Comparison OFF',color=colour)
                ax.bar_label(bars,labels=[f'{v:.2f}' for v in values],padding=3,fontsize=9)
            ax.axhline(limit,color='#bc4444',linestyle='--',label='30 fps reference (NOT live certification)')
            ax.set_xticks(x,labels);ax.set_ylabel(ylabel);ax.set_title(title);ax.set_ylim(bottom=0,top=max(limit,max(r[field] for r in records))*1.23)
            ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.legend(loc='upper right',fontsize=8)
            fig.supxlabel('Same eight native images repeated; 320 measured frames per condition. Warmup excluded.',fontsize=9)
            fig.savefig(out/filename,dpi=150);plt.close(fig)
    with (out/'gpu_performance.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]),lineterminator='\n');writer.writeheader();writer.writerows(records)
    shutil.copyfile(image_path,out/(NATIVE+'.png'))
    if sha(out/(NATIVE+'.png'))!=meta['png_sha256']:raise ValueError('native copy changed')
    if any(sha(ROOT/name)!=digest for name,digest in inputs.items()):raise ValueError('report inputs changed')
    report=dict(state='pass',report_date='2026-11-11',representative_assets=3,
        source_sha256={str(Path(__file__).relative_to(ROOT)):sha(Path(__file__))},input_sha256=inputs,
        native=dict(session=meta['session'],frame=14922,width=1280,height=720,
            historical_capture_date='2026-11-10',image_modified=False,byte_identical=True,
            png_sha256=meta['png_sha256'],decoded_bgr_sha256=meta['decoded_bgr_sha256'],
            range_not_drawn=True,NOT_independent_physical_distance_ground_truth=True),
        output_sha256={name:sha(out/name) for name in names if name!='manifest.json'},
        camera_started=False,cuda_started=False,vehicle_operated=False,
        same_repeated_images_NOT_new_accuracy_or_live_latency_experiment=True)
    with (out/'manifest.json').open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(state='pass',representative_assets=3,native_png_byte_identical=True,output_dir=str(out)),indent=2))


if __name__=='__main__':main()
