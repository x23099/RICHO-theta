"""Compare 35/36/52-frame offline models; no automatic model deployment."""
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256,validate,write_csv
from cone_detection_diagnostics import intersection_over_union

NAMES=('baseline_35','augmented_36','negative_52')
RUNS=('train_ab_baseline_local_20261014_r01','train_ab_augmented_v03_local_20261014_r01',
      'train_ab_negative_v04_local_20261014_r01')
DATA=('ab_bootstrap_v01','ab_bootstrap_augmented_v03','ab_negative_augmented_v04')
BDIAG=('cone_baseline_fp32_diagnose_r01','cone_augmented_v03_fp32_diagnose_r01','cone_negative_v04_b_diagnose_r01')
DDIAG=('cone_de_d_baseline_diagnose_r01','cone_de_d_augmented_diagnose_r01','cone_negative_v04_d_diagnose_r01')
EDIAG=('cone_de_e_baseline_diagnose_r01','cone_de_e_augmented_diagnose_r01','cone_negative_v04_e_diagnose_r01')


def main():
    out=Path(__file__).resolve().parent
    if (out/'comparison_summary.json').exists():raise ValueError('completed snapshot already exists')
    receipt=json.loads((out/'input_receipt.json').read_text())
    for path,digest in receipt['input_sha256'].items():
        if sha256(path)!=digest:raise ValueError(f'fixed input changed: {path}')
    original=ROOT/'Experimental_results/2026-10-14/cone_ab_retraining_comparison_r01/analyze_comparison.py'
    spec=importlib.util.spec_from_file_location('prior_training_checks',original)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    runs={name:module.completed_training(ROOT/'runs/cone'/directory) for name,directory in zip(NAMES,RUNS)}
    base=runs['augmented_36'];args_differences={}
    for name,run in runs.items():
        differences={k:[base['args'].get(k),run['args'].get(k)] for k in set(base['args'])|set(run['args'])
                     if base['args'].get(k)!=run['args'].get(k)}
        if set(differences)-{'data','project','save_dir'}:raise ValueError('non-data hyperparameters changed')
        for key in ('gpu','versions','weights_sha256'):
            if run['provenance'][key]!=base['provenance'][key]:raise ValueError('environment/initial weights changed')
        args_differences[name]=differences
    training,bcounts,bcolors,bottle,eassociations,ecolors,negative_counts=[],[],[],[],[],[],[]
    hashes={str(original):sha256(original)}
    prior_truths=None
    references=read_csv(ROOT/'Experimental_results/2026-10-14/cone_de_intake_r01/assistant_reference_boxes.csv')
    eval_manifest=read_csv(ROOT/'datasets/cone/de_evaluation_review_v01/manifest.csv')
    d_manifest=read_csv(ROOT/'datasets/cone/de_negative_train_review_v01/manifest.csv')
    def predictions(directory,run,review=None):
        path=ROOT/'Experimental_results/2026-10-14'/directory
        p=json.loads((path/'provenance.json').read_text())
        if not p['status'].startswith('COMPLETED_') or p['weights_sha256']!=sha256(run['weights']):
            raise ValueError('completed diagnostics of actual frozen best weights required')
        if review is not None and p['manifest_sha256']!=sha256(review/'raw_review_manifest.csv'):
            raise ValueError('diagnostic images differ')
        result=read_csv(path/'predictions.csv')
        for row in result:
            for key in ('confidence','x1','y1','x2','y2'):row[key]=float(row[key])
        for file in ('predictions.csv','provenance.json'):
            hashes[str(path/file)]=sha256(path/file)
        return path,result
    for name,dataset,bd,dd,ed in zip(NAMES,DATA,BDIAG,DDIAG,EDIAG):
        run=runs[name];counts=validate(ROOT/'datasets/cone'/dataset)['counts']
        training.append(dict(model=name,train_images=counts['train']['images'],train_negatives=counts['train']['negative'],
            precision=run['metrics'][module.METRICS[0]],recall=run['metrics'][module.METRICS[1]],
            map50=run['metrics'][module.METRICS[2]],map50_95=run['metrics'][module.METRICS[3]],
            epoch_csv_cumulative_sec=float(run['epochs'][-1]['time']),best_weights_sha256=sha256(run['weights'])))
        for source,target in ((ROOT/'runs/cone'/RUNS[NAMES.index(name)]/'metrics.json','metrics.json'),
            (ROOT/'runs/cone'/RUNS[NAMES.index(name)]/'provenance.json','provenance.json'),
            (run['csv_path'],'results.csv'),(run['csv_path'].parent/'args.yaml','args.yaml')):
            shutil.copyfile(source,out/f'{name}_{target}');hashes[str(source)]=sha256(source)
        path,_=predictions(bd,run)
        truths=read_csv(path/'ground_truth.csv')
        if prior_truths is None:prior_truths=truths
        elif truths!=prior_truths:raise ValueError('B ground truth/attributes changed')
        for row in read_csv(path/'threshold_summary.csv'):
            if float(row['confidence_threshold']) in (.25,.5):bcounts.append(dict(model=name,**row))
        for row in read_csv(path/'stratum_recall.csv'):
            if row['dimension']=='color' and float(row['confidence_threshold']) in (.25,.5):
                bcolors.append(dict(model=name,**row))
        _,dp=predictions(dd,run,ROOT/'datasets/cone/de_negative_train_review_v01')
        _,ep=predictions(ed,run,ROOT/'datasets/cone/de_evaluation_review_v01')
        bottle_region=dict(x1=180,y1=376,x2=203,y2=407)
        d02_names={r['image'] for r in d_manifest if '_d02_' in r['session']}
        for threshold in (.25,.5):
            kept=[r for r in dp if r['image'] in d02_names and r['confidence']>=threshold
                  and intersection_over_union(bottle_region,r)>=.5]
            bottle.append(dict(model=name,confidence=threshold,images_with_bottle_prediction=len({r['image'] for r in kept}),
                sampled_images=8,scope='D02 is training resubstitution for negative_52; NOT independent generalization'))
            for session in sorted({r['session'] for r in eval_manifest}):
                if '_e01_' not in session:continue
                names={r['image'] for r in eval_manifest if r['session']==session}
                p=[r for r in ep if r['image'] in names and r['confidence']>=threshold]
                negative_counts.append(dict(model=name,confidence=threshold,key='e01',sampled_images=len(names),
                    images_with_prediction=len({r['image'] for r in p}),prediction_boxes=len(p),human_GT='pending'))
        for ref in references:
            region={k:float(ref[k]) for k in ('x1','y1','x2','y2')}
            candidates=[r for r in ep if r['image']==ref['image'] and intersection_over_union(region,r)>=.5]
            best=max(candidates,key=lambda r:r['confidence'],default=None)
            image=next(r for r in eval_manifest if r['image']==ref['image'])
            key='e02' if '_e02_' in image['session'] else 'e03'
            eassociations.append(dict(model=name,key=key,image=ref['image'],frame=image['frame'],color=ref['color'],
                best_score=best['confidence'] if best else '',
                present_at_0p25=int(best is not None and best['confidence']>=.25),
                present_at_0p50=int(best is not None and best['confidence']>=.5),
                reference_actor='same assistant reference, NOT human GT'))
        for key in ('e02','e03'):
            for color in ('red','yellow'):
                rows=[r for r in eassociations if r['model']==name and r['key']==key and r['color']==color]
                ecolors.append(dict(model=name,key=key,color=color,references=len(rows),
                    associated_at_0p25=sum(r['present_at_0p25'] for r in rows),
                    associated_at_0p50=sum(r['present_at_0p50'] for r in rows),human_GT='pending'))
    for file,rows in [('training_metrics.csv',training),('b_fixed_thresholds.csv',bcounts),('b_color_recall.csv',bcolors),
        ('d_water_bottle_resubstitution.csv',bottle),('e_target_associations.csv',eassociations),
        ('e_color_reference_summary.csv',ecolors),('e01_prediction_counts.csv',negative_counts)]:write_csv(out/file,rows)
    os.environ['MPLCONFIGDIR']=str(out/'matplotlib_config')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    for i,name in enumerate(NAMES):
        b=[r for r in bcounts if r['model']==name]
        axes[0].bar([j+i*.23 for j in range(2)],[int(r['fp']) for r in b],width=.23,label=name)
        d=[r for r in bottle if r['model']==name]
        axes[1].bar([j+i*.23 for j in range(2)],[r['images_with_bottle_prediction'] for r in d],width=.23,label=name)
        e=next(r for r in ecolors if r['model']==name and r['key']=='e03' and r['color']=='yellow')
        axes[2].bar([j+i*.23 for j in range(2)],[e['associated_at_0p25'],e['associated_at_0p50']],width=.23,label=name)
    for ax in axes:
        ax.set_xticks([.23,1.23],['conf .25','conf .50']);ax.legend(fontsize=7)
    axes[0].set(title='B: unmatched prediction boxes',ylabel='FP boxes (human-reviewed B labels)')
    axes[1].set(title='D02: bottle prediction',ylabel='Images out of 8 (52: TRAIN data)',ylim=(0,9))
    axes[2].set(title='E03: yellow association',ylabel='Images out of 8 (assistant reference)',ylim=(0,9))
    fig.text(.5,.01,'Same seed/GPU/FP32; development comparison, NOT independent safety or deployment approval.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.06,1,1));fig.savefig(out/'negative_retraining_comparison.png',dpi=150);plt.close(fig)
    summary=dict(status='COMPLETED_OFFLINE_NEGATIVE_AUGMENTATION_COMPARISON_NOT_DEPLOYED',
        training=training,b_fixed_thresholds=bcounts,b_color_recall=bcolors,d_water_bottle=bottle,
        e_colors=ecolors,e01_predictions=negative_counts,hyperparameter_differences=args_differences,
        dataset_input_receipt_sha256=sha256(out/'input_receipt.json'),
        sources_sha256=hashes,analysis_script_sha256=sha256(Path(__file__)),
        graph_sha256=sha256(out/'negative_retraining_comparison.png'),
        training_complete=True,model_adopted=False,physical_output=False,single_seed=True,
        limits=receipt['limits'])
    (out/'comparison_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(dict(training=training,B=bcounts,D=bottle,E=ecolors,E01=negative_counts),indent=2))


if __name__=='__main__':main()
