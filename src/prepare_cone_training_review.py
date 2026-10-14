#!/usr/bin/env python3
"""Train-only pending-image inventory and advisory review queue; no automatic labels."""
import argparse
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile

from cone_dataset import (dataset_yaml, label_path, parse_label, read_csv, sha256,
                          validate, verify_image, write_csv)


def manifest_tables(root):
    metadata = json.loads((root/'dataset.json').read_text())
    manifest = read_csv(root/'manifest.csv')
    reviews = read_csv(root/'reviews.csv')
    if (not manifest or metadata.get('classes') != ['traffic_cone'] or metadata.get('schema_version') != 1
            or sha256(root/'manifest.csv') != metadata.get('manifest_sha256')):
        raise ValueError('trusted single-class dataset with intact manifest required')
    by_image = {r['image']:r for r in reviews}
    if len({r['image'] for r in manifest}) != len(manifest) or len(by_image) != len(reviews) or set(by_image) != {r['image'] for r in manifest}:
        raise ValueError('complete unique manifest/review table required')
    if any(r['status'] not in ('pending','positive','negative') for r in reviews):
        raise ValueError('unsupported review status')
    groups, videos = {}, {}
    for row in manifest:
        label_path(root,row['image'])  # Validate the exact relative image structure first.
        if row['split'] not in ('train','val','test') or row['split'] != Path(row['image']).parts[1]:
            raise ValueError('manifest split/path mismatch')
        for table,key in ((groups,row['group_id']),(videos,row['source_raw_sha256'])):
            if key in table and table[key] != row['split']:
                raise ValueError('capture group/source video crosses splits')
            table[key] = row['split']
    return metadata, manifest, by_image


def pending_train_inventory(dataset, reference):
    _, rows, reviews = manifest_tables(dataset)
    _, baseline, _ = manifest_tables(reference)
    protected = [r for r in baseline if r['split'] != 'train'] + [r for r in rows if r['split'] != 'train']
    train_groups = {r['group_id'] for r in baseline if r['split'] == 'train'}
    held_groups = {r['group_id'] for r in protected}
    held_videos = {r['source_raw_sha256'] for r in protected}
    held_pixels = {r['decoded_bgr_sha256'] for r in protected}
    prior_pixels = {r['decoded_bgr_sha256'] for r in baseline}
    result = []
    for row in rows:
        if row['split'] != 'train' or reviews[row['image']]['status'] != 'pending':
            continue
        if row['group_id'] not in train_groups or row['group_id'] in held_groups or row['source_raw_sha256'] in held_videos or row['decoded_bgr_sha256'] in held_pixels:
            raise ValueError('pending train candidate overlaps protected evaluation data')
        if row['decoded_bgr_sha256'] in prior_pixels:
            continue
        if label_path(dataset,row['image']).exists():
            raise ValueError('pending candidate has an existing label; manual reconciliation required')
        verify_image(dataset,row)
        result.append(dict(row,file=row['image'],reason='unlabelled train-only candidate; not a GT or accuracy sample'))
    if not result or len({r['decoded_bgr_sha256'] for r in result}) != len(result):
        raise ValueError('nonempty unique-pixel pending train pool required')
    return result


def candidate_features(images, predictions):
    groups = {r['file']:[] for r in images}
    by_file = {r['file']:r for r in images}
    seen = set()
    for row in predictions:
        if row['image'] not in groups:
            raise ValueError('prediction outside pending train manifest')
        values = [float(row[k]) for k in ('confidence','x1','y1','x2','y2')]
        image = by_file[row['image']]
        key = (row['image'],int(row['prediction_index']))
        if key in seen:
            raise ValueError('duplicate prediction index')
        seen.add(key)
        score,x1,y1,x2,y2 = values
        if (not all(math.isfinite(v) for v in values) or not 0 <= score <= 1
                or row['class_id'] != '0' or not (0 <= x1 < x2 <= int(image['width']) and 0 <= y1 < y2 <= int(image['height']))):
            raise ValueError('invalid prediction score/geometry/class')
        groups[row['image']].append(row)
    features = []
    for image in images:
        rows = groups[image['file']]
        scores = [float(r['confidence']) for r in rows]
        high = [r for r in rows if float(r['confidence']) >= .25]
        low = [r for r in rows if .05 <= float(r['confidence']) < .25]
        width = int(image['width'])
        # Edge bands are review priorities, NOT an optical validity mask or ground contact gate.
        edge = [r for r in high if min(abs((float(r['x1'])+float(r['x2']))/2-x)
                                       for x in (0,width/2,width)) <= width*.075]
        features.append(dict(file=image['file'],session=image['session'],frame=int(image['frame']),
            time_sec=float(image['time_sec']),candidate_count=len(rows),max_score=max(scores,default=0),
            high_count=len(high),low_count=len(low),edge_high_count=len(edge),
            priority_kind='zero_at_0p25' if not high else 'multiple_at_0p25' if len(high)>1 else
                          'edge_band_candidate' if edge else 'lowest_single_score'))
    return features


def select_queue(features, limit=16, spacing_sec=2.):
    if limit < 1 or not math.isfinite(spacing_sec) or spacing_sec < 0:
        raise ValueError('positive limit and finite nonnegative spacing required')
    categories = ('zero_at_0p25','multiple_at_0p25','edge_band_candidate','lowest_single_score')
    buckets = {name:sorted((r for r in features if r['priority_kind']==name),key=lambda r:(r['max_score'],r['session'],r['frame'])) for name in categories}
    chosen = []
    while len(chosen)<limit:
        changed = False
        for category in categories:
            if len(chosen)>=limit: break
            while buckets[category]:
                row = buckets[category].pop(0)
                if any(r['session']==row['session'] and abs(r['time_sec']-row['time_sec'])<spacing_sec for r in chosen):
                    continue
                chosen.append(row);changed=True;break
        if not changed: break
    return chosen


def prepare_queue(dataset, pool, inference, output, limit, spacing):
    images = read_csv(pool/'candidate_manifest.csv')
    audit = json.loads((pool/'inventory.json').read_text())
    provenance = json.loads((inference/'provenance.json').read_text())
    summary = json.loads((inference/'summary.json').read_text())
    if (audit['manifest_sha256'] != sha256(pool/'candidate_manifest.csv')
            or provenance['manifest_sha256'] != audit['manifest_sha256']
            or Path(provenance['input_dir']).resolve() != dataset.resolve()
            or not provenance['status'].startswith('COMPLETED_') or summary['status'] != provenance['status']):
        raise ValueError('intact inventory and completed inference of same pool required')
    if any(sha256(Path(path)) != expected for path,expected in audit['input_sha256'].items()):
        raise ValueError('inventory source dataset/reference changed')
    current = pending_train_inventory(dataset,Path(audit['reference_dataset']))
    if images != [{k:str(v) for k,v in r.items()} for r in current]:
        raise ValueError('pending train pool changed since inference')
    predictions = read_csv(inference/'predictions.csv')
    if summary['predictions'] != len(predictions) or summary['images'] != len(images):
        raise ValueError('inference candidate/image counts differ from completed summary')
    features = candidate_features(images,predictions)
    selected = select_queue(features,limit,spacing)
    if not selected: raise ValueError('no eligible review candidates')
    by_file = {r['file']:r for r in images}
    output.mkdir(parents=True,exist_ok=False)
    (output/'images/train').mkdir(parents=True); (output/'labels/train').mkdir(parents=True)
    manifest = []
    for row in selected:
        original = by_file[row['file']]
        target = output/original['image']
        verify_image(dataset,original)
        shutil.copyfile(dataset/original['image'],target)
        verify_image(output,original)
        manifest.append({k:v for k,v in original.items() if k not in ('file','reason')})
    write_csv(output/'manifest.csv',manifest)
    write_csv(output/'reviews.csv',[dict(image=r['image'],status='pending',note='',label_sha256='') for r in manifest])
    write_csv(output/'candidate_features.csv',features)
    write_csv(output/'review_queue.csv',selected)
    keep = set(by_file[r['file']]['file'] for r in selected)
    proposals = [r for r in predictions if r['image'] in keep and float(r['confidence']) >= .05]
    write_csv(output/'advisory_model_candidates.csv',proposals,('image','prediction_index','class_id','confidence','x1','y1','x2','y2'))
    metadata = dict(schema_version=1,classes=['traffic_cone'],purpose='train-only pending annotation queue; NOT trainable dataset',
        available_splits=['train'],development_only=True,manifest_sha256=sha256(output/'manifest.csv'),
        source_dataset=str(dataset),reference_dataset=audit['reference_dataset'],selection_count=len(manifest),
        reference_manifest_sha256=sha256(Path(audit['reference_dataset'])/'manifest.csv'),
        reference_reviews_sha256=sha256(Path(audit['reference_dataset'])/'reviews.csv'),
        source_manifest_sha256=sha256(dataset/'manifest.csv'),
        selection_limit=limit,within_session_min_spacing_sec=spacing,
        source_pool_manifest_sha256=audit['manifest_sha256'],predictions_sha256=sha256(inference/'predictions.csv'),
        model_weights_sha256=provenance['weights_sha256'],script_sha256=sha256(Path(__file__)),
        image_policy='byte-identical whole original PNG; no crop/overlay/resize/colour changes',
        automatic_labels_created=False,data_yaml_created=False,training_performed=False,
        independent_test=False,review_required='All visible cones in BOTH lenses, including yellow; candidates are not labels')
    (output/'dataset.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


def apply_selection_policy(queue, additions, policy):
    decisions=read_csv(policy)
    known={r['image']:r for r in additions}
    by_image={r['image']:r for r in decisions}
    if not decisions or len(by_image)!=len(decisions) or set(by_image)!=set(known):
        raise ValueError('selection policy must cover each queue image exactly once')
    for row in decisions:
        if (row.get('decision') not in ('include','hold') or not row.get('reason','').strip()
                or row.get('png_sha256')!=known[row['image']]['png_sha256']):
            raise ValueError('hash-bound include/hold decisions and reasons required')
    selected=[r for r in additions if by_image[r['image']]['decision']=='include']
    held=[r for r in decisions if r['decision']=='hold']
    if not selected:raise ValueError('all additions held; no augmented training dataset produced')
    return selected,held


def merge_reviewed_queue(queue, reference, output, selection_policy=None):
    """Create a NEW dataset only after explicit human review; preserve val/test bytes."""
    reference_check = validate(reference)
    baseline_meta, baseline, baseline_reviews = manifest_tables(reference)
    queue_meta, additions, queue_reviews = manifest_tables(queue)
    if (queue_meta.get('purpose') != 'train-only pending annotation queue; NOT trainable dataset'
            or Path(queue_meta['reference_dataset']).resolve() != reference.resolve()
            or queue_meta.get('available_splits') != ['train']):
        raise ValueError('queue must originate from this exact train-only reference')
    source = Path(queue_meta['source_dataset']).resolve()
    if (queue_meta.get('reference_manifest_sha256') != sha256(reference/'manifest.csv')
            or queue_meta.get('reference_reviews_sha256') != sha256(reference/'reviews.csv')
            or queue_meta.get('source_manifest_sha256') != sha256(source/'manifest.csv')):
        raise ValueError('reference/source snapshot changed since queue preparation; reconcile explicitly')
    held=[]
    if selection_policy:
        additions,held=apply_selection_policy(queue,additions,selection_policy)
        queue_reviews={r['image']:queue_reviews[r['image']] for r in additions}
    _, source_rows, _ = manifest_tables(source)
    by_source = {r['image']:r for r in source_rows}
    protected = [r for r in baseline if r['split'] != 'train']
    train_groups = {r['group_id'] for r in baseline if r['split'] == 'train'}
    all_images = {r['image'] for r in baseline}
    all_pixels = {r['decoded_bgr_sha256'] for r in baseline}
    for row in additions:
        if row['image'] not in by_source or by_source[row['image']] != row:
            raise ValueError('queue manifest differs from original source provenance')
        if (row['split'] != 'train' or row['group_id'] not in train_groups
                or row['image'] in all_images or row['decoded_bgr_sha256'] in all_pixels):
            raise ValueError('new unique train-only additions required')
        if any(row[key] == r[key] for r in protected for key in ('group_id','source_raw_sha256','decoded_bgr_sha256')):
            raise ValueError('queue overlaps protected val/test group/video/pixels')
        all_images.add(row['image']);all_pixels.add(row['decoded_bgr_sha256'])
        verify_image(source,row);verify_image(queue,row)
        review = queue_reviews[row['image']]
        label = label_path(queue,row['image'])
        if (review['status'] not in ('positive','negative') or not review['note'].startswith('human full-frame review:')
                or not label.is_file() or label.is_symlink() or sha256(label) != review['label_sha256']):
            raise ValueError('all queue images need explicit current human full-frame review and labels')
        if bool(parse_label(label)) != (review['status']=='positive'):
            raise ValueError('review and label disagree')
    if not additions:
        raise ValueError('nonempty reviewed queue required')
    all_queue_rows=read_csv(queue/'manifest.csv')
    expected = {str(label_path(queue,r['image']).relative_to(queue)) for r in all_queue_rows}
    actual_labels={str(p.relative_to(queue)) for p in (queue/'labels').rglob('*') if p.is_file()}
    if not actual_labels.issubset(expected) or (not selection_policy and actual_labels!=expected):
        raise ValueError('unmanifested queue labels forbidden')
    if {str(p.relative_to(queue)) for p in (queue/'images').rglob('*') if p.is_file()} != {r['image'] for r in all_queue_rows}:
        raise ValueError('unmanifested queue images forbidden')
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in (queue,reference,source)):
        raise ValueError('new merged output outside input datasets required')
    output.parent.mkdir(parents=True,exist_ok=True)
    rows = baseline + additions
    reviews = list(baseline_reviews.values()) + list(queue_reviews.values())
    with tempfile.TemporaryDirectory(prefix='.cone_merge_',dir=output.parent) as temporary:
        stage = Path(temporary)/'dataset';stage.mkdir()
        for split in baseline_meta['available_splits']:
            (stage/'images'/split).mkdir(parents=True);(stage/'labels'/split).mkdir(parents=True)
        for root, manifest in ((reference,baseline),(queue,additions)):
            for row in manifest:
                shutil.copyfile(root/row['image'],stage/row['image'])
                shutil.copyfile(label_path(root,row['image']),label_path(stage,row['image']))
        write_csv(stage/'manifest.csv',rows);write_csv(stage/'reviews.csv',reviews)
        metadata = dict(baseline_meta,manifest_sha256=sha256(stage/'manifest.csv'),
            augmentation=dict(reference_dataset=str(reference),queue=str(queue),
                reference_manifest_sha256=sha256(reference/'manifest.csv'),queue_manifest_sha256=sha256(queue/'manifest.csv'),
                queue_reviews_sha256=sha256(queue/'reviews.csv'),train_images_added=len(additions),
                selection_policy_sha256=sha256(selection_policy) if selection_policy else None,held_images=held,
                val_test_unchanged=True,script_sha256=sha256(Path(__file__))))
        (stage/'dataset.json').write_text(json.dumps(metadata,indent=2)+'\n')
        (stage/'data.yaml').write_text(dataset_yaml(stage,development_only=baseline_meta['development_only']))
        validate(stage)
        for row in protected:
            if sha256(stage/row['image']) != sha256(reference/row['image']) or sha256(label_path(stage,row['image'])) != sha256(label_path(reference,row['image'])):
                raise ValueError('protected evaluation content changed')
        (stage/'data.yaml').write_text(dataset_yaml(output,development_only=baseline_meta['development_only']))
        stage.rename(output)
    result = validate(output)
    result.update(train_images_added=len(additions),val_test_unchanged=True,training_performed=False,
                  train_images_held=len(held),
                  original_reference_integrity=reference_check['status'])
    (output/'merge_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('inventory','queue','merge'))
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--reference-dataset',type=Path)
    parser.add_argument('--pool-dir',type=Path)
    parser.add_argument('--inference-dir',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=16)
    parser.add_argument('--spacing-sec',type=float,default=2.)
    parser.add_argument('--selection-policy',type=Path,help='merge only: complete hash-bound include/hold CSV')
    args = parser.parse_args()
    try:
        args.dataset=args.dataset.expanduser().resolve();args.output_dir=args.output_dir.expanduser().resolve()
        if args.selection_policy and args.mode!='merge':raise ValueError('selection-policy applies only to merge')
        if args.selection_policy:
            args.selection_policy=args.selection_policy.expanduser().resolve()
            if not args.selection_policy.is_file() or args.selection_policy.is_relative_to(args.output_dir):
                raise ValueError('existing selection policy outside output required')
        sources=[args.dataset]+[p.expanduser().resolve() for p in (args.reference_dataset,args.pool_dir,args.inference_dir) if p]
        if args.output_dir.exists() or any(args.output_dir.is_relative_to(p) or p.is_relative_to(args.output_dir) for p in sources):
            raise ValueError('new output outside input datasets/analysis required')
        if args.mode=='inventory':
            if not args.reference_dataset: raise ValueError('reference dataset required for train-only inventory')
            args.reference_dataset=args.reference_dataset.expanduser().resolve()
            rows=pending_train_inventory(args.dataset,args.reference_dataset)
            args.output_dir.mkdir(parents=True,exist_ok=False)
            write_csv(args.output_dir/'candidate_manifest.csv',rows)
            result=dict(status='PENDING_TRAIN_POOL_NOT_LABELLED_OR_TRAINABLE',images=len(rows),dataset=str(args.dataset),
                reference_dataset=str(args.reference_dataset),manifest_sha256=sha256(args.output_dir/'candidate_manifest.csv'),
                input_sha256={str(root/name):sha256(root/name) for root in (args.dataset,args.reference_dataset)
                              for name in ('manifest.csv','reviews.csv','dataset.json')},
                script_sha256=sha256(Path(__file__)),protected_evaluation_overlap=0,
                automatic_labels_created=False,training_performed=False)
            (args.output_dir/'inventory.json').write_text(json.dumps(result,indent=2)+'\n')
        elif args.mode=='queue':
            if not args.pool_dir or not args.inference_dir: raise ValueError('pool and inference directories required')
            result=prepare_queue(args.dataset,args.pool_dir.expanduser().resolve(),args.inference_dir.expanduser().resolve(),
                                 args.output_dir,args.limit,args.spacing_sec)
        else:
            if not args.reference_dataset: raise ValueError('reference dataset required for reviewed queue merge')
            result=merge_reviewed_queue(args.dataset,args.reference_dataset.expanduser().resolve(),args.output_dir,args.selection_policy)
        print(json.dumps(result,indent=2))
    except (ValueError,OSError,KeyError,ImportError) as error:
        parser.exit(2,f'[ERROR] {error}\n')


if __name__=='__main__':main()
