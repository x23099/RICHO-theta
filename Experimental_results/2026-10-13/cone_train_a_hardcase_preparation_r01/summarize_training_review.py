"""Snapshot a pending train-only review queue with byte-identical raw examples."""
from collections import Counter
import json
from pathlib import Path
import shutil
import sys

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'src'))
from cone_dataset import read_csv,sha256,verify_image,write_csv


def main():
    root=Path(__file__).resolve().parent
    queue=REPO/'datasets/cone/a_hardcase_review_v02'
    inference=root.parent/'cone_train_a_pending_inference_r02'
    inventory=json.loads((root/'inventory.json').read_text())
    metadata=json.loads((queue/'dataset.json').read_text())
    provenance=json.loads((inference/'provenance.json').read_text())
    summary=json.loads((inference/'summary.json').read_text())
    original=Path(inventory['dataset'])
    for path,expected in inventory['input_sha256'].items():
        if sha256(Path(path)) != expected:raise ValueError('original datasets changed')
    if metadata['source_pool_manifest_sha256'] != inventory['manifest_sha256'] or provenance['manifest_sha256'] != inventory['manifest_sha256']:
        raise ValueError('queue/inference differs from audited train-only pool')
    if metadata['predictions_sha256'] != sha256(inference/'predictions.csv') or summary['status'] != provenance['status'] or not summary['status'].startswith('COMPLETED_'):
        raise ValueError('completed, intact model inference required')
    images=read_csv(queue/'manifest.csv');reviews=read_csv(queue/'reviews.csv')
    if (sha256(queue/'manifest.csv') != metadata['manifest_sha256'] or len(images) != 16
            or len(reviews) != len(images) or any(r['status'] != 'pending' for r in reviews)
            or list((queue/'labels').rglob('*.txt')) or (queue/'data.yaml').exists()):
        raise ValueError('exact pending-only queue without labels/training YAML required')
    for row in images:
        if row['split'] != 'train':raise ValueError('non-training image in queue')
        verify_image(original,row);verify_image(queue,row)
    features=read_csv(queue/'candidate_features.csv')
    selected=read_csv(queue/'review_queue.csv')
    if len(features) != inventory['images'] or len(selected) != len(images):
        raise ValueError('queue/pool count mismatch')
    for name in ('manifest.csv','reviews.csv','review_queue.csv','candidate_features.csv','advisory_model_candidates.csv'):
        write_csv(root/f'queue_{name}',read_csv(queue/name))
    raw=root/'raw_examples';raw.mkdir(exist_ok=True)
    representatives=[r for r in images if int(r['frame']) in (4261,4651)]
    if len(representatives) != 2:raise ValueError('declared representative frames missing')
    exported=[]
    for row in representatives:
        target=raw/Path(row['image']).name
        if target.exists() and sha256(target) != row['png_sha256']:
            raise ValueError('existing representative differs; no overwrite')
        if not target.exists():shutil.copyfile(queue/row['image'],target)
        if sha256(target) != row['png_sha256']:raise ValueError('exported original PNG differs')
        exported.append(dict(row,file=str(target.relative_to(root)),role='unmodified train-only review example; not accuracy evidence'))
    write_csv(root/'raw_example_manifest.csv',exported)
    report=dict(status='TRAIN_ONLY_REVIEW_QUEUE_READY_NOT_LABELLED_NOT_TRAINED',
        pending_train_pool=inventory['images'],model_candidates=summary['predictions'],
        selected_queue=len(images),advisory_candidates=len(read_csv(queue/'advisory_model_candidates.csv')),
        pool_priority_counts=dict(Counter(r['priority_kind'] for r in features)),
        selected_priority_counts=dict(Counter(r['priority_kind'] for r in selected)),
        minimum_same_session_spacing_sec=metadata['within_session_min_spacing_sec'],
        queue_path=str(queue),queue_metadata=metadata,raw_examples=2,
        originals_and_baseline_unchanged=True,protected_evaluation_overlap=0,
        human_review_performed=False,automatic_labels_created=False,training_performed=False,physical_output=False,
        limitations=['Selection priorities are not verified FP/FN; multiple predictions can be real multiple cones.',
                     'Existing A capture group only; not an independent test or guaranteed cure for B failures.',
                     'All visible yellow/red cones in both lenses need human labels; absence of predictions is not a negative.'],
        input_sha256={str(path.relative_to(REPO)):sha256(path) for path in
            (root/'inventory.json',root/'candidate_manifest.csv',queue/'dataset.json',queue/'manifest.csv',queue/'reviews.csv',
             inference/'summary.json',inference/'provenance.json',inference/'predictions.csv')},
        output_sha256={name:sha256(root/name) for name in
            ('queue_manifest.csv','queue_reviews.csv','queue_review_queue.csv','queue_candidate_features.csv',
             'queue_advisory_model_candidates.csv','raw_example_manifest.csv')},
        script_sha256=sha256(Path(__file__)))
    (root/'preparation_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],pool=report['pending_train_pool'],
                          queue=report['selected_queue'],selection=report['selected_priority_counts']),indent=2))


if __name__=='__main__':main()
