#!/usr/bin/env python3
"""Fixed-model, selected-frame pilot analysis; reference boxes are NOT human GT."""
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / 'src'))
from cone_dataset import read_csv, sha256, verify_image, write_csv
from cone_detection_diagnostics import intersection_over_union

# Assistant whole-image visual references; not generated from detector boxes,
# not blinded human labels, never imported into train/evaluation label folders.
def visual_regions(key, frame):
    if key == 'e02':
        return [('yellow',(340,315,376,379)),('red',(1023,296,1078,390))]
    if key != 'e03':
        return []
    if frame == 1:
        return [('red',(363,303,425,438)),('yellow',(895,280,975,436))]
    if frame <= 471:
        return [('red',(363,303,440,438)),('yellow',(895,280,975,436))]
    if frame == 627:
        return [('red',(320,285,386,410)),('yellow',(895,280,975,436))]
    if frame == 784:
        return [('red',(238,312,294,410)),('yellow',(883,276,965,419))]
    return [('red',(238,312,294,410)),('yellow',(864,292,915,386))]


def main():
    output = Path(__file__).resolve().parent
    if (output / 'analysis_summary.json').exists():
        raise ValueError('completed analysis snapshot already exists; choose new output/version')
    inventory = json.loads((output / 'input_inventory.json').read_text())
    frozen = json.loads((output / 'frozen_comparison.json').read_text())
    if sha256(output / 'frozen_comparison.json') != inventory['frozen_comparison_sha256']:
        raise ValueError('fixed comparison contract changed')
    images = read_csv(output / 'selected_manifest.csv')
    key_by_session = {r['session_dir'].split('/')[-1]:r['key'] for r in inventory['inputs']}
    observed, reference_boxes, all_predictions, hashes = [], [], {}, {}
    for row in images:
        key = key_by_session[row['session']]
        queue = Path(inventory['train_queue'] if row['split']=='train' else inventory['evaluation_queue'])
        verify_image(queue,row)
        regions = visual_regions(key,int(row['frame']))
        observed.append(dict(image=row['image'],session=row['session'],frame=row['frame'],key=key,
            png_sha256=row['png_sha256'],review_actor='assistant',human_annotation_status='pending',
            observation='red water bottle present; no traffic cone identified' if key=='d02' else
                'no traffic cone identified in either lens' if not regions else 'one visible red and one visible yellow cone',
            visible_red_cones=int(bool(regions)),visible_yellow_cones=int(bool(regions)),
            note='D02 object identity confirmed by user: red water bottle, NOT cone' if key=='d02' else
                 'E03 frame627/784 includes repositioning; do not treat lifted/handled cone as floor contact' if key=='e03' and int(row['frame']) in (627,784) else
                 'fixed-placement repetition, not independent objects' if key=='e02' else 'whole-frame visual observation only'))
        for color,box in regions:
            reference_boxes.append(dict(image=row['image'],png_sha256=row['png_sha256'],color=color,
                **dict(zip(('x1','y1','x2','y2'),box)),actor='assistant_nonblinded_visual_reference_NOT_human_GT'))
    for case in ('d','e'):
        for name in ('baseline','augmented'):
            path = output.parent / f'cone_de_{case}_{name}_diagnose_r01'
            provenance = json.loads((path / 'provenance.json').read_text())
            summary = json.loads((path / 'summary.json').read_text())
            expected = frozen['models'][name+'_35' if name=='baseline' else name+'_36']
            queue = Path(inventory['train_queue'] if case=='d' else inventory['evaluation_queue'])
            if (not provenance['status'].startswith('COMPLETED_') or summary['status']!=provenance['status']
                    or Path(provenance['input_dir']).resolve()!=queue
                    or provenance['manifest_sha256']!=sha256(queue / 'raw_review_manifest.csv')
                    or provenance['weights_sha256']!=expected['sha256']
                    or sha256(expected['path'])!=expected['sha256']):
                raise ValueError('completed fixed-model/fixed-input inference required')
            kwargs = provenance['prediction_kwargs']
            if kwargs['conf']!=.01 or kwargs['imgsz']!=960 or kwargs['iou']!=.7 or kwargs['rect']:
                raise ValueError('prediction settings differ from frozen conditions')
            predictions = read_csv(path / 'predictions.csv')
            if len(predictions)!=summary['predictions']:
                raise ValueError('candidate count differs')
            eligible = {r['image'] for r in images if (r['split']=='train')==(case=='d')}
            if any(r['image'] not in eligible for r in predictions):
                raise ValueError('prediction outside registered samples')
            for p in predictions:
                for field in ('confidence','x1','y1','x2','y2'):p[field]=float(p[field])
            all_predictions[case,name] = predictions
            for file in ('predictions.csv','provenance.json','summary.json'):
                hashes[str(path / file)] = sha256(path / file)
    counts, matches, bottle_rows, color_counts, bottle_counts = [], [], [], [], []
    for name in ('baseline','augmented'):
        for item in inventory['inputs']:
            key,session = item['key'],Path(item['session_dir']).name
            selected = [r for r in images if r['session']==session]
            predictions = all_predictions['d' if item['split']=='train' else 'e',name]
            predictions = [p for p in predictions if p['image'] in {r['image'] for r in selected}]
            for threshold in frozen['confidence_thresholds']:
                kept = [p for p in predictions if p['confidence']>=threshold]
                counts.append(dict(model=name,key=key,confidence=threshold,sampled_images=len(selected),
                    images_with_prediction=len({p['image'] for p in kept}),prediction_boxes=len(kept),
                    max_score=max((p['confidence'] for p in predictions),default=0),
                    human_GT='pending',scope='candidate counts NOT accuracy'))
            if key=='d02':
                bottle = dict(x1=180,y1=376,x2=203,y2=407)
                for p in predictions:
                    overlap = intersection_over_union(bottle,p)
                    if overlap>=.5:
                        bottle_rows.append(dict(model=name,image=p['image'],confidence=p['confidence'],
                            iou_to_visual_bottle_region=overlap,object_identity='red water bottle: user confirmed NOT cone'))
                for threshold in frozen['confidence_thresholds']:
                    r = [p for p in bottle_rows if p['model']==name and p['confidence']>=threshold]
                    bottle_counts.append(dict(model=name,confidence=threshold,sampled_images=8,
                        images_with_bottle_false_prediction=len({p['image'] for p in r}),
                        false_prediction_boxes=len(r),distinct_physical_bottles=1))
            for row in selected:
                for color,box in visual_regions(key,int(row['frame'])):
                    region = dict(zip(('x1','y1','x2','y2'),box))
                    candidates = [p for p in predictions if p['image']==row['image'] and intersection_over_union(region,p)>=.5]
                    best = max(candidates,key=lambda p:p['confidence'],default=None)
                    matches.append(dict(model=name,key=key,image=row['image'],frame=row['frame'],color=color,
                        best_overlap_score=best['confidence'] if best else '',
                        iou_to_assistant_reference=intersection_over_union(region,best) if best else 0,
                        present_at_0p25=int(best is not None and best['confidence']>=.25),
                        present_at_0p50=int(best is not None and best['confidence']>=.5),
                        scope='assistant visual target association; NOT human-confirmed precision/recall'))
        for key in ('e02','e03'):
            for color in ('red','yellow'):
                r = [m for m in matches if m['model']==name and m['key']==key and m['color']==color]
                color_counts.append(dict(model=name,key=key,color=color,visible_reference_instances=len(r),
                    associated_at_0p25=sum(m['present_at_0p25'] for m in r),
                    associated_at_0p50=sum(m['present_at_0p50'] for m in r),
                    reference_actor='assistant_nonblinded_NOT_human_GT'))
    for file,rows in [('assistant_visual_review.csv',observed),('assistant_reference_boxes.csv',reference_boxes),
        ('prediction_counts.csv',counts),('positive_target_associations.csv',matches),
        ('color_reference_summary.csv',color_counts),('water_bottle_false_predictions.csv',bottle_rows),
        ('water_bottle_threshold_summary.csv',bottle_counts)]:
        write_csv(output / file,rows)
    (output / 'raw_examples').mkdir(exist_ok=False)
    examples=[]
    for key,frame in [('d02',1),('e02',661),('e03',940)]:
        row = next(r for r in images if key_by_session[r['session']]==key and int(r['frame'])==frame)
        queue = Path(inventory['train_queue'] if row['split']=='train' else inventory['evaluation_queue'])
        target = output / 'raw_examples' / Path(row['image']).name
        shutil.copyfile(queue / row['image'],target)
        if sha256(target)!=row['png_sha256']:raise ValueError('raw example changed')
        examples.append(dict(row,file=str(target.relative_to(output))))
    write_csv(output / 'raw_example_manifest.csv',examples)
    os.environ['MPLCONFIGDIR']=str(output / 'matplotlib_config')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    for index,name in enumerate(('baseline','augmented')):
        b=[r for r in bottle_counts if r['model']==name]
        axes[0].bar([i+index*.34 for i in range(2)],
            [r['images_with_bottle_false_prediction'] for r in b],width=.34,label=name)
        c=next(r for r in color_counts if r['model']==name and r['key']=='e03' and r['color']=='yellow')
        axes[1].bar([i+index*.34 for i in range(2)],
            [c['associated_at_0p25'],c['associated_at_0p50']],width=.34,label=name)
    for ax in axes:
        ax.set_xticks([.17,1.17],['conf 0.25','conf 0.50']);ax.set_ylim(0,9)
        ax.set_yticks(range(0,9,2));ax.legend(fontsize=8)
    axes[0].set_title('D02: confirmed bottle mistaken as cone');axes[0].set_ylabel('Sampled images (out of 8)')
    axes[1].set_title('E03: yellow target association');axes[1].set_ylabel('Visual references associated (out of 8)')
    fig.text(.5,.01,'Fixed models, sparse time samples. E03 references: assistant, not human GT. No model adopted.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.06,1,1));fig.savefig(output / 'selected_frame_comparison.png',dpi=150);plt.close(fig)
    summary=dict(status='COMPLETED_SPARSE_OFFLINE_DIAGNOSIS_NOT_MODEL_ADOPTION',
        recording_sessions=5,total_recorded_frames=sum(int(r['frames']) for r in read_csv(output / 'session_integrity.csv')),
        sampled_images=len(images),human_confirmed_image_labels=0,
        training_performed=False,models_adopted=False,ffb_output=False,
        water_bottle_identity_confirmation='User: 赤色の水筒です。コーンではないです',
        prediction_counts=counts,color_reference_summary=color_counts,water_bottle_threshold_summary=bottle_counts,
        frozen_comparison_sha256=sha256(output / 'frozen_comparison.json'),source_inference_sha256=hashes,
        analysis_script_sha256=sha256(Path(__file__)),graph_sha256=sha256(output / 'selected_frame_comparison.png'),
        limits=['Only 8 selected frames per video were visually reviewed and inferred, not every video frame.',
            'E02 fixed-position repetition is not independent objects; E03 includes partial occlusion/repositioning.',
            'E reference boxes are assistant/nonblinded pilot references, not independent human annotation.',
            'D/E were separated; E remains evaluation-only and must not be merged into training.',
            'An earlier frozen note assumed same-room capture; observed D/E01/E02/E03 show different indoor views. No unseen-site claim.',
            'No threshold or runtime setting was changed.'])
    (output / 'analysis_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(dict(bottle=bottle_counts,colors=color_counts),indent=2))


if __name__=='__main__':main()
