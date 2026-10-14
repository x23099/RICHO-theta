"""Compare same-PC training and fixed val diagnostics; no model adoption or image editing."""
import json
import math
from pathlib import Path
import shutil
import sys

import yaml

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'src'))
from cone_dataset import label_path,read_csv,sha256,validate,write_csv

TRAIN_RUNS={
    'baseline_35':REPO/'runs/cone/train_ab_baseline_local_20261014_r01',
    'augmented_36':REPO/'runs/cone/train_ab_augmented_v03_local_20261014_r01',
}
DATASETS={'baseline_35':REPO/'datasets/cone/ab_bootstrap_v01',
          'augmented_36':REPO/'datasets/cone/ab_bootstrap_augmented_v03'}
DIAGNOSTICS={'baseline_35':REPO/'Experimental_results/2026-10-14/cone_baseline_fp32_diagnose_r01',
             'augmented_36':REPO/'Experimental_results/2026-10-14/cone_augmented_v03_fp32_diagnose_r01'}
METRICS=('metrics/precision(B)','metrics/recall(B)','metrics/mAP50(B)','metrics/mAP50-95(B)')


def completed_training(root):
    provenance=json.loads((root/'provenance.json').read_text())
    metrics=json.loads((root/'metrics.json').read_text())
    paths=list(root.glob('*/results.csv'))
    if provenance['status']!='COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL' or len(paths)!=1:
        raise ValueError('one completed, fully recorded training run required')
    csv_path=paths[0]
    epochs=[{k.strip():v for k,v in row.items()} for row in read_csv(csv_path)]
    if [int(r['epoch']) for r in epochs]!=list(range(1,51)):
        raise ValueError('complete 50-epoch CSV required')
    for row in epochs:
        if not all(math.isfinite(float(v)) for v in row.values()):raise ValueError('nonfinite training CSV')
    if any(not math.isfinite(metrics[k]) or not 0<=metrics[k]<=1 for k in METRICS):
        raise ValueError('finite detection metrics in [0,1] required')
    args=yaml.safe_load((csv_path.parent/'args.yaml').read_text())
    if args['amp'] is not False or args['epochs']!=50 or args['batch']!=8 or args['imgsz']!=960 or args['seed']!=0 or args['plots'] is not False:
        raise ValueError('fixed FP32/50/8/960/seed0/no-plots condition required')
    weights=csv_path.parent/'weights/best.pt'
    if not weights.is_file():raise ValueError('completed best.pt required')
    return dict(provenance=provenance,metrics=metrics,epochs=epochs,args=args,csv_path=csv_path,weights=weights)


def main():
    root=Path(__file__).resolve().parent
    if (root/'comparison_summary.json').exists():raise ValueError('immutable comparison already exists; choose new result version')
    runs={name:completed_training(path) for name,path in TRAIN_RUNS.items()}
    base=runs['baseline_35'];aug=runs['augmented_36']
    arg_differences={key:[base['args'].get(key),aug['args'].get(key)]
        for key in set(base['args'])|set(aug['args']) if base['args'].get(key)!=aug['args'].get(key)}
    if set(arg_differences)-{'data','project','save_dir'}:
        raise ValueError(f'non-data/output hyperparameter differences: {arg_differences}')
    for key in ('gpu','versions','weights_sha256'):
        if base['provenance'][key]!=aug['provenance'][key]:raise ValueError(f'training environment/checkpoint differs: {key}')
    integrity={name:validate(path) for name,path in DATASETS.items()}
    protected=[r for r in read_csv(DATASETS['baseline_35']/'manifest.csv') if r['split']=='val']
    for row in protected:
        for path in (row['image'],str(label_path(DATASETS['baseline_35'],row['image']).relative_to(DATASETS['baseline_35']))):
            if sha256(DATASETS['baseline_35']/path)!=sha256(DATASETS['augmented_36']/path):
                raise ValueError('validation pixels or labels changed')
    aggregate,colors,thresholds=[],[],[]
    diagnostic_provenance={}
    ground_truth=None
    for name,run in runs.items():
        for source,label in ((TRAIN_RUNS[name]/'provenance.json','provenance.json'),
                             (TRAIN_RUNS[name]/'metrics.json','metrics.json'),
                             (run['csv_path'],'results.csv'),(run['csv_path'].parent/'args.yaml','args.yaml')):
            shutil.copyfile(source,root/f'{name}_{label}')
        aggregate.append(dict(model=name,train_images=integrity[name]['counts']['train']['images'],
            train_boxes=integrity[name]['counts']['train']['boxes'],val_images=len(protected),
            precision=run['metrics'][METRICS[0]],recall=run['metrics'][METRICS[1]],
            map50=run['metrics'][METRICS[2]],map50_95=run['metrics'][METRICS[3]],
            epoch_csv_cumulative_sec=float(run['epochs'][-1]['time']),weights_path=str(run['weights']),
            weights_sha256=sha256(run['weights']),scope='training-final best validation; not fixed-threshold recall'))
        d=DIAGNOSTICS[name]
        p=json.loads((d/'provenance.json').read_text())
        if p['status']!='COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL' or p['weights_sha256']!=sha256(run['weights']):
            raise ValueError('completed diagnostics of actual best weights required')
        truths=read_csv(d/'ground_truth.csv')
        if ground_truth is not None and truths!=ground_truth:raise ValueError('diagnostic GT/attributes differ')
        ground_truth=truths
        diagnostic_provenance[name]=p
        colors.extend(dict(r,model=name) for r in read_csv(d/'stratum_recall.csv') if r['dimension']=='color')
        thresholds.extend(dict(r,model=name) for r in read_csv(d/'threshold_summary.csv'))
    if base['provenance']['gpu']!=diagnostic_provenance['baseline_35']['gpu']:
        raise ValueError('training/diagnostic GPU differs')
    for key in ('kwargs','diagnostic_config','object_attributes_sha256'):
        if diagnostic_provenance['baseline_35'][key]!=diagnostic_provenance['augmented_36'][key]:
            raise ValueError(f'diagnostic conditions differ: {key}')
    write_csv(root/'aggregate_comparison.csv',aggregate)
    write_csv(root/'color_recall_comparison.csv',colors)
    write_csv(root/'threshold_comparison.csv',thresholds)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(13,4))
    for name,run in runs.items():
        axes[0].plot([int(r['epoch']) for r in run['epochs']],
                     [float(r['metrics/mAP50-95(B)']) for r in run['epochs']],label=name)
        for index,color in enumerate(('red','yellow'),1):
            selected=sorted((r for r in colors if r['model']==name and r['value']==color),key=lambda r:float(r['confidence_threshold']))
            axes[index].plot([float(r['confidence_threshold']) for r in selected],
                             [float(r['recall']) for r in selected],marker='o',label=name)
    axes[0].set(xlabel='Epoch',ylabel='Development val mAP50-95',title='Same GPU / seed / FP32 training')
    for index,color in enumerate(('Red: 18 annotated boxes','Yellow: 38 annotated boxes'),1):
        axes[index].set(xlabel='Confidence threshold',ylabel='Fixed-threshold recall (IoU >=0.5)',title=color,ylim=(-.02,1.04))
        axes[index].axvline(.25,color='gray',linestyle=':',linewidth=1)
    for axis in axes:axis.grid(alpha=.25);axis.legend(fontsize=8)
    fig.suptitle('35 vs 36 training images; repeated development footage, NOT independent test',fontsize=11)
    fig.tight_layout();graph=root/'retraining_comparison.png';fig.savefig(graph,dpi=150);plt.close(fig)
    result=dict(date='2026-10-14',status='COMPLETED_DEVELOPMENT_COMPARISON_NOT_MODEL_ADOPTION',
        aggregate=aggregate,color_recall_at_0p25=[r for r in colors if float(r['confidence_threshold'])==.25],
        gpu=base['provenance']['gpu'],versions=base['provenance']['versions'],actual_arg_differences=arg_differences,
        identical_validation_images_and_labels=True,initial_weights_sha256=base['provenance']['weights_sha256'],
        single_seed_only=True,independent_test=False,model_adopted=False,physical_output=False,
        sources_sha256={str(path.relative_to(REPO)):sha256(path) for name,run in runs.items() for path in
            (TRAIN_RUNS[name]/'provenance.json',TRAIN_RUNS[name]/'metrics.json',run['csv_path'],run['csv_path'].parent/'args.yaml',
             DIAGNOSTICS[name]/'provenance.json',DIAGNOSTICS[name]/'predictions.csv',DIAGNOSTICS[name]/'matches.csv',
             DIAGNOSTICS[name]/'ground_truth.csv',DIAGNOSTICS[name]/'stratum_recall.csv',DIAGNOSTICS[name]/'threshold_summary.csv')},
        graph_sha256=sha256(graph),script_sha256=sha256(Path(__file__)),
        limitations=['All val images contain cones; no true cone-free negative or independent course test.',
                     'Single seed on a very small dataset: any difference is not proven causal benefit of the added frame.',
                     'Older RTX4070/cu118/AMP training is not the matched baseline for the new frame.',
                     'First baseline setup downloaded an Arial font after the initial font alias was placed one directory too high; no auxiliary model was downloaded. Font lookup fixed and verified for later runs.'])
    (root/'comparison_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','aggregate','color_recall_at_0p25')},indent=2))


if __name__=='__main__':main()
