#!/usr/bin/env python3
"""Snapshot candidate provenance/prediction counts; never confirm human labels."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from cone_dataset import read_csv, sha256, verify_image, write_csv
from run_cone_review_frames import load_manifest


def main():
    output = Path(__file__).resolve().parent
    if (output / 'candidate_summary.json').exists():
        raise ValueError('snapshot already exists; choose a new result directory')
    queue = ROOT / 'datasets/cone/legacy_background_review_v01'
    metadata = json.loads((queue / 'dataset.json').read_text())
    if sha256(queue / 'manifest.csv') != metadata['manifest_sha256']:
        raise ValueError('candidate manifest changed')
    images = load_manifest(queue)
    reviews = read_csv(queue / 'reviews.csv')
    if len(reviews) != len(images) or any(row['status'] != 'pending' for row in reviews):
        raise ValueError('this snapshot requires original unreviewed candidates')
    for path, digest in metadata['reference_input_sha256'].items():
        if sha256(path) != digest:
            raise ValueError('reference snapshot changed')
    paths, counts, models = {}, [], {}
    for name, directory in [('baseline_35', 'cone_negative_baseline_diagnose_r01'),
                             ('augmented_36', 'cone_negative_augmented_diagnose_r01')]:
        result = output.parent / directory
        provenance = json.loads((result / 'provenance.json').read_text())
        summary = json.loads((result / 'summary.json').read_text())
        if (not provenance['status'].startswith('COMPLETED_') or summary['status'] != provenance['status']
                or provenance['manifest_sha256'] != sha256(queue / 'raw_review_manifest.csv')
                or Path(provenance['input_dir']).resolve() != queue.resolve()
                or sha256(provenance['weights']) != provenance['weights_sha256']):
            raise ValueError('completed same-input inference with intact model required')
        predictions = read_csv(result / 'predictions.csv')
        if len(predictions) != summary['predictions'] or summary['images'] != len(images):
            raise ValueError('prediction/image counts differ')
        if any(row['image'] not in {r['file'] for r in images} for row in predictions):
            raise ValueError('prediction outside queue')
        models[name] = dict(weights_sha256=provenance['weights_sha256'],
            prediction_kwargs=provenance['prediction_kwargs'], versions=provenance['versions'])
        paths[str(result / 'predictions.csv')] = sha256(result / 'predictions.csv')
        paths[str(result / 'provenance.json')] = sha256(result / 'provenance.json')
        for image in images:
            rows = [r for r in predictions if r['image'] == image['file']]
            for threshold in (.01, .05, .25, .5):
                scores = [float(r['confidence']) for r in rows if float(r['confidence']) >= threshold]
                counts.append(dict(model=name, image=image['file'], session=image['session'],
                    frame=image['frame'], png_sha256=image['png_sha256'], confidence=threshold,
                    prediction_boxes=len(scores), max_score=max(scores, default=0),
                    human_status='pending', interpretation='candidate predictions; not human-confirmed FP'))
    if models['baseline_35']['prediction_kwargs'] != models['augmented_36']['prediction_kwargs']:
        raise ValueError('prediction conditions differ')
    write_csv(output / 'candidate_predictions_by_threshold.csv', counts)
    write_csv(output / 'assistant_visual_review.csv', [dict(image=r['file'], png_sha256=r['png_sha256'],
        review_actor='assistant', observation='no red/yellow traffic cone identified in either lens',
        decision='negative_candidate_only', human_confirmation='pending', training_included='0') for r in images])
    # These are byte copies of already verified whole-frame PNGs, not edited illustrations.
    (output / 'raw_examples').mkdir(exist_ok=False)
    selected = [images[4], images[10]]
    for row in selected:
        verify_image(queue, row)
        target = output / 'raw_examples' / Path(row['file']).name
        shutil.copyfile(queue / row['file'], target)
        if sha256(target) != row['png_sha256']:
            raise ValueError('raw example changed')
    write_csv(output / 'raw_example_manifest.csv', selected)
    write_csv(output / 'candidate_manifest.csv', images)
    result = dict(status='PREPARED_UNLABELLED_BACKGROUND_CANDIDATES_NOT_TRAINED_OR_ADOPTED',
        candidate_images=len(images), source_sessions=len(metadata['sources']),
        human_confirmed_negative_images=0, independent_test=False,
        model_results={name:dict(boxes_at_0p01=sum(int(r['prediction_boxes']) for r in counts
            if r['model']==name and r['confidence']==.01),
            boxes_at_0p25=sum(int(r['prediction_boxes']) for r in counts
            if r['model']==name and r['confidence']==.25),
            max_score=max(float(r['max_score']) for r in counts if r['model']==name)) for name in models},
        queue_metadata=metadata, models=models, input_sha256=paths,
        queue_manifest_sha256=sha256(queue / 'manifest.csv'),
        queue_reviews_sha256=sha256(queue / 'reviews.csv'),
        analysis_script_sha256=sha256(Path(__file__)),
        limits=['Only 12 time-sampled images reviewed, not every source frame.',
            'Mostly wall/floor legacy scenery, not current shelf/equipment false-positive backgrounds.',
            'Assistant review is not explicit human annotation approval.',
            'Same room and temporal similarity mean these are not 12 independent scenes.',
            'Do not add B validation images or re-encoded/cropped copies to training.'])
    (output / 'candidate_summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['model_results'], indent=2))


if __name__ == '__main__':
    main()
