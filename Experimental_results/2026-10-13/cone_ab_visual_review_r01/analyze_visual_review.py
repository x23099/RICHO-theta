"""Reaggregate existing predictions with explicit visual reviews; never infer/train."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
from cone_dataset import label_path, parse_label, read_csv, sha256, write_csv, verify_image
from cone_detection_diagnostics import (ATTR_FIELDS, BOX_FIELDS, GT_FIELDS, aggregate,
                                        intersection_over_union, load_attributes)


def numeric_rows(rows, index):
    for row in rows:
        row[index] = int(row[index])
        for key in BOX_FIELDS:
            row[key] = float(row[key])
        if not all(math.isfinite(row[key]) for key in BOX_FIELDS):
            raise ValueError('nonfinite coordinates')
        if row['x2'] <= row['x1'] or row['y2'] <= row['y1']:
            raise ValueError('invalid bbox')
        if str(row['class_id']) != '0':
            raise ValueError('unexpected class')
        if 'confidence' in row:
            row['confidence'] = float(row['confidence'])
            if not math.isfinite(row['confidence']) or not 0 <= row['confidence'] <= 1:
                raise ValueError('invalid confidence')
    return rows


def review_attributes(catalog, images, truths):
    reviewed = {}
    for group in catalog['groups']:
        for frame in group['frames']:
            name = f"images/val/{group['prefix']}{frame:06d}.png"
            if name in reviewed:
                raise ValueError('duplicate reviewed image')
            reviewed[name] = group['gt_colors_in_existing_label_order']
    if set(reviewed) != {row['image'] for row in images}:
        raise ValueError('visual review must cover exactly the received image set')
    known = {(row['image'], row['gt_index']): row for row in truths}
    assignments = []
    for name, colors in reviewed.items():
        if set(key[1] for key in known if key[0] == name) != set(range(len(colors))):
            raise ValueError('review GT order/count differs from saved labels')
        for index, color in enumerate(colors):
            if color not in ('red', 'yellow'):
                raise ValueError('explicit reviewed red/yellow color required')
            assignments.append(dict(image=name, gt_index=index,
                label_sha256=known[(name,index)]['label_sha256'], color=color,
                lens='unknown', occlusion='unknown',
                note=f"assistant full-frame original PNG visual review {catalog['date']}; color only; physical lens orientation/occlusion not certified"))
    return assignments


def case_rows(catalog, images, truths, predictions, config):
    _, matches, _, _ = aggregate(images, truths, predictions, dict(config, confidence_thresholds=[.05]))
    gt = {(row['image'], row['gt_index']): row for row in truths}
    pred = {(row['image'], row['prediction_index']): row for row in predictions}
    expected_fp = {(row['image'], row['prediction_index']) for row in matches if row['outcome']=='FP'}
    expected_fn = {(row['image'], row['gt_index']) for row in matches if row['outcome']=='FN'}
    reviewed_fp = catalog['fp_review_at_confidence_0p05']
    reviewed_fn = catalog['fn_review_at_confidence_0p05']
    if len(reviewed_fp) != len(expected_fp) or {(row['image'],row['prediction_index']) for row in reviewed_fp} != expected_fp:
        raise ValueError('FP review differs from recorded matching')
    if len(reviewed_fn) != len(expected_fn) or {(row['image'],row['gt_index']) for row in reviewed_fn} != expected_fn:
        raise ValueError('FN review differs from recorded matching')
    cases = []
    for review in reviewed_fp:
        p = pred[(review['image'],review['prediction_index'])]
        candidates = [row for row in truths if row['image']==review['image']]
        best = max(candidates, key=lambda row: intersection_over_union(row,p))
        cases.append(dict(outcome='FP', **review, gt_index='',
            confidence=p['confidence'], **{key:p[key] for key in BOX_FIELDS},
            best_any_gt_index=best['gt_index'], best_any_gt_iou=intersection_over_union(best,p)))
    for review in reviewed_fn:
        g = gt[(review['image'],review['gt_index'])]
        candidates = [row for row in predictions if row['image']==review['image'] and
                      intersection_over_union(row,g) >= config['match_iou']]
        best = max(candidates, key=lambda row: row['confidence'], default=None)
        cases.append(dict(outcome='FN', **review,
            prediction_index=best['prediction_index'] if best else '',
            confidence=best['confidence'] if best else '', **{key:g[key] for key in BOX_FIELDS},
            best_any_gt_index=g['gt_index'], best_any_gt_iou=intersection_over_union(g,best) if best else ''))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    args = parser.parse_args()
    source, dataset = args.input_dir.resolve(), args.dataset.resolve()
    output = Path(__file__).resolve().parent
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('source and analysis output must not overlap')
    catalog_path = output / 'review_catalog.json'
    catalog = json.loads(catalog_path.read_text())
    provenance = json.loads((source/'provenance.json').read_text())
    original = json.loads((source/'diagnostic_summary.json').read_text())
    if provenance['mode'] != 'diagnose' or provenance['status'] != 'COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL':
        raise ValueError('completed diagnostic run required')
    config = original['config']
    images = read_csv(source/'image_manifest.csv')
    truths = numeric_rows(read_csv(source/'ground_truth.csv'), 'gt_index')
    predictions = numeric_rows(read_csv(source/'predictions.csv'), 'prediction_index')
    if len(images) != original['image_count'] or len(truths) != original['gt_count'] or len(predictions) != original['prediction_count']:
        raise ValueError('source row counts differ from run summary')
    _, _, baseline, _ = aggregate(images, truths, predictions, config)
    if baseline != original['threshold_summary']:
        raise ValueError('source CSV reaggregation differs from original summary')
    # Check the exact original PNG and current label contents against the recorded run.
    for image in images:
        verify_image(dataset, image)
    for truth in truths:
        label = dataset/'labels'/Path(truth['image']).parts[1]/(Path(truth['image']).stem+'.txt')
        if sha256(label) != truth['label_sha256']:
            raise ValueError('reviewed label changed since inference')
    assignments = review_attributes(catalog, images, truths)
    attribute_path = output/'reviewed_attributes.csv'
    write_csv(attribute_path, assignments, ATTR_FIELDS)
    attributes = load_attributes(attribute_path, truths)
    for truth in truths:
        truth.update(attributes[(truth['image'],truth['gt_index'])])
    per_image, matches, totals, strata = aggregate(images, truths, predictions, config)
    write_csv(output/'ground_truth_with_color.csv', truths, GT_FIELDS)
    write_csv(output/'stratum_recall.csv', strata)
    write_csv(output/'threshold_summary.csv', totals)
    write_csv(output/'per_image.csv', per_image)
    write_csv(output/'matches.csv', matches)
    cases = case_rows(catalog, images, truths, predictions, config)
    write_csv(output/'reviewed_error_cases.csv', cases)
    candidate_rows = []
    for truth in truths:
        candidates = [row for row in predictions if row['image']==truth['image'] and
                      intersection_over_union(row,truth) >= config['match_iou']]
        best = max(candidates, key=lambda row: row['confidence'], default=None)
        candidate_rows.append(dict(image=truth['image'],gt_index=truth['gt_index'],color=truth['color'],
            prediction_index=best['prediction_index'] if best else '',
            confidence=best['confidence'] if best else '',
            iou=intersection_over_union(truth,best) if best else '',
            scope='highest-confidence candidate with IoU>=0.5; not a fresh inference or one-to-one match'))
    write_csv(output/'gt_candidate_confidence.csv', candidate_rows)
    # Prior reviewed A annotations identify two fixed yellow-reference footprints.
    # This is a geometry audit of that existing record, NOT an HSV-derived color label.
    prior_path = REPO/'Experimental_results/2026-10-12/cone_ab_intake/visual_annotations.csv'
    reference_counts = Counter()
    dataset_images = {row['image']:row for row in read_csv(dataset/'manifest.csv')}
    for entry in read_csv(prior_path):
        if not entry['image'].startswith('images/train/'):
            continue
        image = dataset_images[entry['image']]
        width,height = int(image['width']),int(image['height'])
        current = [((x-w/2)*width,(y-h/2)*height,(x+w/2)*width,(y+h/2)*height)
                   for x,y,w,h in parse_label(label_path(dataset,entry['image']))]
        for box in json.loads(entry['boxes_xyxy_json']):
            if box in catalog['prior_train_yellow_reference_boxes']:
                if not any(all(abs(a-b)<1e-5 for a,b in zip(box,values)) for values in current):
                    raise ValueError('prior yellow-reference bbox no longer agrees with dataset')
                reference_counts[tuple(box)] += 1
    scale_rows = [dict(scope='train_A_prior_yellow_reference',gt_count=count,
                       width_px=box[2]-box[0],height_px=box[3]-box[1])
                  for box,count in sorted(reference_counts.items())]
    val_sizes = Counter((round(row['x2']-row['x1'],5),round(row['y2']-row['y1'],5))
                        for row in truths if row['color']=='yellow')
    scale_rows.extend(dict(scope='val_B_reviewed_yellow',gt_count=count,width_px=size[0],height_px=size[1])
                      for size,count in sorted(val_sizes.items()))
    write_csv(output/'yellow_reference_scale.csv',scale_rows)
    source_files = ('provenance.json','diagnostic_summary.json','ground_truth.csv',
                    'predictions.csv','image_manifest.csv')
    verification = dict(date=catalog['date'], decision='PASS_OFFLINE_VISUAL_REVIEW_NOT_DEPLOYMENT_APPROVAL',
        reviewed_images=len(images),reviewed_gt=len(truths),
        color_counts=dict(Counter(row['color'] for row in truths)),
        fp_categories=dict(Counter(row['category'] for row in cases if row['outcome']=='FP')),
        model_inference_performed=False, training_performed=False, physical_output=False,
        original_png_hash_and_pixels='PASS_ALL_38', original_label_hash='PASS_ALL_56_GT',
        original_global_metrics_reproduced=True,
        source_sha256={name:sha256(source/name) for name in source_files},
        review_catalog_sha256=sha256(catalog_path), script_sha256=sha256(Path(__file__)),
        attributes_sha256=sha256(attribute_path), reviewer=catalog['reviewer'])
    verification['prior_train_reference_source_sha256']=sha256(prior_path)
    (output/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    # Three raw image examples and a numeric chart, with all source paths/hashes preserved.
    assets = output.parent/'report_assets'
    assets.mkdir(exist_ok=True)
    selected = [('block_b_d2f1899d1f1cec88_f003301.png','cone_adjacent_red_yellow_raw.png'),
                ('block_b_e4aaba18ded89e95_f000451.png','cone_yellow_low_confidence_raw.png'),
                ('block_b_d2f1899d1f1cec88_f002101.png','cone_red_duplicate_raw.png')]
    asset_rows = []
    by_image = {row['image']:row for row in images}
    for filename, name in selected:
        key = 'images/val/'+filename
        original_png, target = dataset/key, assets/name
        if target.exists() and sha256(target) != sha256(original_png):
            raise ValueError('existing raw asset differs; no overwrite')
        if not target.exists():
            shutil.copyfile(original_png,target)
        if sha256(target) != by_image[key]['png_sha256']:
            raise ValueError('representative PNG differs from the recorded source hash')
        asset_rows.append(dict(file=name,**by_image[key]))
    write_csv(assets/'cone_visual_review_raw_manifest.csv',asset_rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(figsize=(8,4.5))
    for color, label, paint in (('red','Red cone GT (18)','firebrick'),('yellow','Yellow cone GT (38)','#b38b00')):
        rows = [row for row in strata if row['dimension']=='color' and row['value']==color]
        axes.plot([row['confidence_threshold'] for row in rows],[100*row['recall'] for row in rows],
                  marker='o',label=label,color=paint)
    axes.set(xlabel='Confidence threshold',ylabel='Fixed-threshold GT recall (%)',ylim=(-3,103),
             title='Development B: same saved predictions, IoU >= 0.50')
    axes.grid(alpha=.3)
    axes.legend()
    figure.tight_layout()
    graph=assets/'cone_color_recall_by_confidence.png'
    figure.savefig(graph,dpi=150)
    plt.close(figure)
    verification['graph'] = dict(path=str(graph.relative_to(output.parent)), sha256=sha256(graph),
                                source_csv_sha256=sha256(output/'stratum_recall.csv'))
    (output/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps(dict(color_counts=verification['color_counts'],fp_categories=verification['fp_categories'],
                         color_recall=[row for row in strata if row['dimension']=='color']),indent=2))


if __name__ == '__main__':
    main()
