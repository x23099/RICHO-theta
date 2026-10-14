"""Human-labelled B/E and D negative comparison, with immutable review snapshots."""
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import label_path,parse_label,read_csv,sha256,verify_image,write_csv
from cone_detection_diagnostics import aggregate,prepare_inputs,intersection_over_union


def reviewed(root,expected_images):
    meta=json.loads((root/'dataset.json').read_text())
    if sha256(root/'manifest.csv')!=meta['manifest_sha256']:raise ValueError('changed manifest')
    images=read_csv(root/'manifest.csv');reviews=read_csv(root/'reviews.csv')
    by={r['image']:r for r in reviews}
    if len(images)!=expected_images or len(by)!=len(reviews) or set(by)!={r['image'] for r in images}:
        raise ValueError('complete exact human review required')
    for row in images:
        verify_image(root,row);r=by[row['image']];label=label_path(root,row['image'])
        if (r['status'] not in ('positive','negative') or not r['note'].startswith('human full-frame review:')
                or not label.is_file() or label.is_symlink() or sha256(label)!=r['label_sha256']
                or bool(parse_label(label))!=(r['status']=='positive')):raise ValueError('label/review not current human confirmation')
    return images,reviews


def main():
    out=Path(__file__).resolve().parent
    if (out/'evaluation_summary.json').exists():raise ValueError('evaluation snapshot already exists')
    e=ROOT/'datasets/cone/de_evaluation_review_v01';d=ROOT/'datasets/cone/de_negative_train_review_v01'
    b=ROOT/'datasets/cone/ab_bootstrap_augmented_v03'
    eimages,reviews=reviewed(e,24);dimages,dreviews=reviewed(d,16)
    if sum(r['status']=='positive' for r in reviews)!=16:raise ValueError('expected16 E positive images')
    _,egts=prepare_inputs(e,'val')
    if len(egts)!=32:raise ValueError('expected32 E cone boxes; reconcile explicitly')
    bimages,bgts=prepare_inputs(b,'val',ROOT/'Experimental_results/2026-10-13/cone_ab_visual_review_r01/reviewed_attributes.csv')
    all_inputs={'b':bimages,'e':eimages,'d':dimages};all_gt={'b':bgts,'e':egts,'d':[]}
    # Colors come from prior whole-frame observations, associated to new HUMAN box coordinates.
    references=read_csv(ROOT/'Experimental_results/2026-10-14/cone_de_intake_r01/assistant_reference_boxes.csv')
    for gt in egts:
        candidates=[r for r in references if r['image']==gt['image']]
        for r in candidates:
            for k in ('x1','y1','x2','y2'):r[k]=float(r[k])
        best=max(candidates,key=lambda r:intersection_over_union(gt,r),default=None)
        if best and intersection_over_union(gt,best)>=.5:
            gt['color']=best['color'];gt['attribute_note']='assistant color observation associated to human box; not model output color'
    config=dict(confidence_thresholds=[.25,.5],match_iou=.5)
    rows,colors,matches,conditions=[],[],[],{}
    prior_names=('baseline_35','augmented_36','negative_52')
    bdirs=('cone_baseline_fp32_diagnose_r01','cone_augmented_v03_fp32_diagnose_r01','cone_negative_v04_b_diagnose_r01')
    edirs=('cone_de_e_baseline_diagnose_r01','cone_de_e_augmented_diagnose_r01','cone_negative_v04_e_diagnose_r01')
    ddirs=('cone_de_d_baseline_diagnose_r01','cone_de_d_augmented_diagnose_r01','cone_negative_v04_d_diagnose_r01')
    hashes={}
    for name,bd,ed,dd in zip(prior_names,bdirs,edirs,ddirs):
        for group,directory in [('b',bd),('e',ed),('d',dd)]:
            path=out.parent/directory;p=json.loads((path/'provenance.json').read_text())
            if not p['status'].startswith('COMPLETED_'):raise ValueError('completed original prediction run required')
            for image in all_inputs[group]:
                recorded=next((r for r in p.get('images',[]) if r.get('image',r.get('file'))==image['image']),None)
                # Dataset-wide diagnostics record their input manifest separately.
                if recorded and recorded['png_sha256']!=image['png_sha256']:raise ValueError('original prediction PNG differs')
            predictions=read_csv(path/'predictions.csv')
            for row in predictions:
                row['prediction_index']=int(row['prediction_index'])
                for k in ('confidence','x1','y1','x2','y2'):row[k]=float(row[k])
            _,mm,totals,ss=aggregate(all_inputs[group],all_gt[group],predictions,config)
            for r in totals:rows.append(dict(model=name,imgsz=960,set=group,**r))
            for r in ss:
                if r['dimension']=='color':colors.append(dict(model=name,imgsz=960,set=group,**r))
            matches.extend(dict(model=name,imgsz=960,set=group,**r) for r in mm)
            hashes[str(path/'predictions.csv')]=sha256(path/'predictions.csv')
        conditions[name]=dict(imgsz=960)
    for size in (960,640):
        path=out/f'cone_inference_{size}'
        p=json.loads((path/'provenance.json').read_text())
        if not p['status'].startswith('COMPLETED_') or p['prediction_kwargs']['imgsz']!=size:
            raise ValueError('completed matching friend inference required')
        manifest=read_csv(path/'raw_review_manifest.csv')
        byfile={r['file']:r for r in manifest}
        predictions=read_csv(path/'predictions.csv')
        for group in all_inputs:
            selected=[r for r in manifest if r['source_set']==group]
            if {r['original_image'] for r in selected}!={r['image'] for r in all_inputs[group]}:
                raise ValueError('friend used different evaluation sample set')
            truth_images={r['image']:r for r in all_inputs[group]}
            if any(r['png_sha256']!=truth_images[r['original_image']]['png_sha256'] for r in selected):
                raise ValueError('friend image pixels differ')
            pp=[]
            for row in predictions:
                source=byfile[row['image']]
                if source['source_set']!=group:continue
                converted=dict(row,image=source['original_image'],prediction_index=int(row['prediction_index']))
                for k in ('confidence','x1','y1','x2','y2'):converted[k]=float(converted[k])
                pp.append(converted)
            _,mm,totals,ss=aggregate(all_inputs[group],all_gt[group],pp,config)
            for r in totals:rows.append(dict(model='friend_yolo11n',imgsz=size,set=group,**r))
            for r in ss:
                if r['dimension']=='color':colors.append(dict(model='friend_yolo11n',imgsz=size,set=group,**r))
            matches.extend(dict(model='friend_yolo11n',imgsz=size,set=group,**r) for r in mm)
        hashes[str(path/'predictions.csv')]=sha256(path/'predictions.csv')
        hashes[str(path/'provenance.json')]=sha256(path/'provenance.json')
    write_csv(out/'human_e_ground_truth.csv',egts)
    write_csv(out/'human_e_review_snapshot.csv',reviews)
    write_csv(out/'fixed_threshold_comparison.csv',rows)
    write_csv(out/'color_recall.csv',colors)
    write_csv(out/'matches.csv',matches)
    (out/'human_labels').mkdir(exist_ok=False)
    for image in eimages:shutil.copyfile(label_path(e,image['image']),out/'human_labels'/Path(image['image']).with_suffix('.txt').name)
    os.environ['MPLCONFIGDIR']=str(out/'matplotlib_config')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    names=(*prior_names,'friend_yolo11n');labels=('35','36','52','friend')
    for index,group in enumerate(('b','e')):
        values=[next(r for r in rows if r['model']==name and r['set']==group and r['imgsz']==960
                     and r['confidence_threshold']==.25) for name in names]
        x=list(range(4));axes[index].bar([v-.16 for v in x],[r['fp'] for r in values],.32,label='FP')
        axes[index].bar([v+.16 for v in x],[r['fn'] for r in values],.32,label='FN')
        axes[index].set_xticks(x,labels);axes[index].set_title(f'{group.upper()}: same images / human labels / conf .25')
        axes[index].set_ylabel('Unmatched boxes / missed human boxes');axes[index].legend()
    fig.text(.5,.01,'960px fixed comparison; no model deployed. Friend training data overlap/coverage unknown.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.06,1,1));fig.savefig(out/'human_gt_model_comparison.png',dpi=150);plt.close(fig)
    for root in (e,d):
        for file in ('manifest.csv','reviews.csv','dataset.json'):hashes[str(root/file)]=sha256(root/file)
    summary=dict(status='COMPLETED_HUMAN_E_AND_FRIEND_CONE_OFFLINE_CHECK_NOT_DEPLOYED',
        e_human_images=24,e_positive=16,e_negative=8,e_human_boxes=32,comparisons=rows,
        color_attributes='assistant observation attached to human bbox by IoU; YOLO has only1 class',
        source_sha256=hashes,graph_sha256=sha256(out/'human_gt_model_comparison.png'),script_sha256=sha256(Path(__file__)),
        adopted=False,ffb_output=False,
        limits=['B repeated development validation; E separate capture with related indoor backgrounds.',
                'D is training resubstitution for negative_52, not holdout.',
                'Friend training image count, color coverage and training-data overlap are unknown.',
                '640 is friend training-size supplementary check, not same-size comparison to960 models.',
                'No lane inference without architecture/preprocessing/output definition.'])
    (out/'evaluation_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
