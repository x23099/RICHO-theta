"""Hash-bound, point-wise candidate review; never compute recall from manual regions."""
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO/'src'))
from cone_dataset import read_csv, sha256, write_csv
from run_cone_review_frames import load_manifest

RED_ROLES = {'red_region','red_incomplete','mixed_person_red','red_fragment'}
ROLES = RED_ROLES | {'yellow','noncone_hand'}


def review_candidates(manifest, predictions, catalog):
    images = {row['file']:row for row in manifest}
    groups = {int(row['frame']):[] for row in manifest}
    if len(groups) != len(manifest):
        raise ValueError('this dated review expects one session and unique frame numbers')
    if len({row['session'] for row in manifest}) != 1:
        raise ValueError('one-session review required')
    for row in predictions:
        if row['image'] not in images:
            raise ValueError('unknown prediction image')
        groups[int(images[row['image']]['frame'])].append(row)
    decisions = {row['frame']:row for row in catalog['frames']}
    if len(decisions) != len(catalog['frames']) or set(decisions) != set(groups):
        raise ValueError('complete unique review decisions required')
    reviewed, point_rows = [], []
    for frame, group in groups.items():
        decision = decisions[frame]
        by_index = {int(row['prediction_index']):row for row in group}
        if len(by_index) != len(group):
            raise ValueError('duplicate candidate index')
        roles = {int(key):value for key,value in decision['roles'].items()}
        retained = {index for index,row in by_index.items() if float(row['confidence']) >= catalog['review_floor']}
        if set(roles) != retained or any(value not in ROLES for value in roles.values()):
            raise ValueError('all candidates above review floor must have an explicit valid review')
        selected = decision['red_candidate_index']
        if selected is not None and (selected not in by_index or roles.get(selected) not in RED_ROLES):
            raise ValueError('selected red-region candidate must exist and be reviewed as overlapping red')
        for index, role in roles.items():
            row = by_index[index]
            reviewed.append(dict(row, frame=frame, prediction_index=index, role=role))
        meta = next(row for row in manifest if int(row['frame']) == frame)
        point_rows.append(dict(session=meta['session'],frame=frame, time_sec=meta['time_sec'], image=meta['file'],
            category=decision['category'], zero_output_example=int(meta['reason'].startswith('zero-output')),
            selected_red_candidate_index=selected if selected is not None else '',
            selected_red_score=float(by_index[selected]['confidence']) if selected is not None else '',
            geometry_accuracy='unmeasured', ground_contact_validated=False, note=decision['note']))
    summaries = []
    for threshold in (.05,.10,.25):
        kept = [row for row in reviewed if float(row['confidence']) >= threshold]
        red = [row for row in kept if row['role'] in RED_ROLES]
        red_frames = {row['frame'] for row in red}
        zero_frames = {row['frame'] for row in point_rows if row['zero_output_example']}
        summaries.append(dict(confidence_threshold=threshold, selected_images=len(manifest),
            candidates=len(kept), red_overlap_candidates=len(red), yellow_candidates=sum(r['role']=='yellow' for r in kept),
            noncone_hand_candidates=sum(r['role']=='noncone_hand' for r in kept),
            selected_images_with_red_overlap=len(red_frames), zero_examples_with_red_overlap=len(zero_frames & red_frames),
            total_zero_examples=len(zero_frames),
            scope='assistant point-wise region review; NOT TP/FP counts, recall or independent accuracy'))
    return reviewed, point_rows, summaries


def main():
    root = Path(__file__).resolve().parent
    source = root.parent/'cone_video_b_r01'
    catalog = json.loads((root/'review_catalog.json').read_text())
    for path, key in [(root/'predictions.csv','predictions_sha256'),
                      (source/'raw_review_manifest.csv','manifest_sha256'),
                      (source/'visibility_review.csv','visibility_sha256')]:
        if sha256(path) != catalog[key]:
            raise ValueError('stale review source hash')
    provenance = json.loads((root/'provenance.json').read_text())
    video_provenance = json.loads((source/'provenance.json').read_text())
    if not provenance['status'].startswith('COMPLETED_') or provenance['weights_sha256'] != video_provenance['weights_sha256']:
        raise ValueError('completed same-checkpoint run required')
    manifest = load_manifest(source)  # Verify every original PNG and decoded pixel hash again.
    predictions = read_csv(root/'predictions.csv')
    reviewed, points, summaries = review_candidates(manifest, predictions, catalog)
    write_csv(root/'reviewed_candidates.csv', reviewed)
    write_csv(root/'gap_point_diagnosis.csv', points)
    write_csv(root/'review_threshold_summary.csv', summaries)
    images = {r['image']:(r['session'],int(r['frame'])) for r in points}
    selected_keys = set(images.values())
    old = [r for r in read_csv(source/'predictions.csv') if (r['session'],int(r['frame'])) in selected_keys]
    new = [dict(r,session=images[r['image']][0],frame=images[r['image']][1])
           for r in predictions if float(r['confidence']) >= .25]
    key = lambda r:(r['session'],int(r['frame']),-float(r['confidence']))
    old, new = sorted(old,key=key), sorted(new,key=key)
    if len(old) != len(new) or [key(r)[:2] for r in old] != [key(r)[:2] for r in new]:
        raise ValueError('0.25 candidate counts differ from full-video analysis')
    delta = max((abs(float(a[k])-float(b[k])) for a,b in zip(old,new)
                 for k in ('confidence','x1','y1','x2','y2')),default=0)
    if delta > .001:
        raise ValueError('0.25 candidates differ from full-video analysis beyond .001')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    zero = [r for r in points if r['zero_output_example']]
    figure, axis = plt.subplots(figsize=(10,4.5))
    x = list(range(len(zero)))
    scores = [r['selected_red_score'] if r['selected_red_score'] != '' else 0 for r in zero]
    axis.bar(x,scores,color=['#555555' if 'fisheye' in r['category'] else '#c95543' for r in zero])
    for pos,score in enumerate(scores):
        axis.text(pos,score+.008,f'{score:.3f}' if score else 'None >=0.01',ha='center',fontsize=8)
    axis.axhline(.25,color='black',linestyle='--',label='Existing candidate threshold 0.25')
    axis.axhline(.10,color='blue',linestyle=':',label='Diagnostic threshold 0.10 (NOT adopted)')
    axis.set_xticks(x,[str(r['frame']) for r in zero])
    axis.set(xlabel='Selected zero-output frame (NOT all frames)',ylabel='Reviewed red-region candidate score',
             ylim=(0,.31),title='9/10 sampled gaps have a red-region candidate; box accuracy is unmeasured')
    axis.legend(fontsize=8,loc='upper right'); axis.grid(axis='y',alpha=.2)
    figure.tight_layout(); figure.savefig(root/'gap_candidate_confidence.png',dpi=150); plt.close(figure)
    verification = dict(status='COMPLETED_POINT_REVIEW_NOT_ACCURACY_APPROVAL', selected_frames=len(points),
        zero_point_examples=len(zero),zero_points_with_red_region_candidate=sum(score>0 for score in scores),
        original_images_unchanged=True, same_checkpoint_as_video=True,
        high_confidence_reproduced_count=len(new), high_confidence_max_absolute_delta=delta,
        input_sha256={str(path.relative_to(root.parent)):sha256(path) for path in
            (root/'predictions.csv',root/'provenance.json',root/'review_catalog.json',
             source/'raw_review_manifest.csv',source/'visibility_review.csv',source/'predictions.csv',source/'provenance.json')},
        output_sha256={name:sha256(root/name) for name in ('gap_point_diagnosis.csv','reviewed_candidates.csv',
            'review_threshold_summary.csv','gap_candidate_confidence.png')}, script_sha256=sha256(Path(__file__)),
        physical_output=False,training_performed=False,threshold_adopted=False,precision_recall_computed=False)
    (root/'review_verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps(dict(summaries=summaries,verification=verification),indent=2))


if __name__=='__main__':main()
