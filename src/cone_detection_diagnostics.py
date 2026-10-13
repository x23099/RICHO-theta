"""Offline, fixed-threshold cone diagnostics; no training, ROS or image overlays."""
import math
from pathlib import Path
import shutil
import time
import json

from cone_dataset import label_path, parse_label, read_csv, sha256, write_csv

BOX_FIELDS = ('x1', 'y1', 'x2', 'y2')
PRED_FIELDS = ('image', 'prediction_index', 'class_id', 'confidence', *BOX_FIELDS)
GT_FIELDS = ('image', 'gt_index', 'class_id', *BOX_FIELDS, 'height_px',
             'size_band', 'image_half', 'label_sha256', 'color', 'lens', 'occlusion', 'attribute_note')
ATTR_FIELDS = ('image', 'gt_index', 'label_sha256', 'color', 'lens', 'occlusion', 'note')
ATTRIBUTE_VALUES = dict(color={'unknown', 'red', 'yellow', 'other'},
                        lens={'unknown', 'front', 'rear'},
                        occlusion={'unknown', 'none', 'partial'})


def prediction_kwargs(args):
    return dict(device=args.device, imgsz=args.imgsz, conf=args.prediction_floor,
                iou=args.nms_iou, max_det=args.max_det, rect=False, quantize=32,
                batch=1, augment=False, save=False, save_txt=False, save_crop=False, show=False,
                visualize=False, verbose=False, stream=False)


def diagnostic_config(args):
    thresholds = args.confidence_thresholds
    values = [args.prediction_floor, args.nms_iou, args.match_iou, *thresholds]
    if not thresholds or not all(math.isfinite(v) and 0 < v <= 1 for v in values):
        raise ValueError('finite confidence/IoU values in (0,1] required')
    if len(set(thresholds)) != len(thresholds):
        raise ValueError('duplicate confidence thresholds')
    if min(thresholds) < args.prediction_floor or args.max_det < 1:
        raise ValueError('thresholds must be >= prediction floor; max_det >= 1')
    return dict(split=args.diagnostic_split, confidence_thresholds=sorted(thresholds),
                prediction_floor=args.prediction_floor, match_iou=args.match_iou,
                nms_iou=args.nms_iou, max_det=args.max_det,
                matching='confidence-descending greedy; best unmatched GT IoU; one-to-one',
                size_bands='GT height in original pixels: small <32; medium <96; large >=96',
                image_half='GT centre relative to width/2; NOT a front/rear assignment',
                precision_recall_scope='fixed-threshold diagnostics, NOT Ultralytics val/mAP reproduction')


def load_attributes(path, truths):
    """Optional human attributes; keyed to the exact reviewed label content."""
    if path is None:
        return {}
    known = {(row['image'], row['gt_index']): row for row in truths}
    result = {}
    for row in read_csv(path):
        if set(ATTR_FIELDS) - set(row):
            raise ValueError('attribute CSV columns missing')
        key = (row['image'], int(row['gt_index']))
        if key not in known or key in result or row['label_sha256'] != known[key]['label_sha256']:
            raise ValueError('unknown/duplicate GT or stale label hash in attributes')
        if any(row[name] not in allowed for name, allowed in ATTRIBUTE_VALUES.items()):
            raise ValueError('unsupported human attribute value')
        if any(row[name] != 'unknown' for name in ATTRIBUTE_VALUES) and not row['note'].strip():
            raise ValueError('human attribute assignment needs a review note')
        result[key] = dict((name, row[name]) for name in ATTRIBUTE_VALUES)
        result[key]['attribute_note'] = row['note']
    return result


def prepare_inputs(dataset, split, attributes=None):
    images = [row for row in read_csv(dataset / 'manifest.csv') if row['split'] == split]
    if not images:
        raise ValueError('selected diagnostic split unavailable; val is never reused as test')
    truths = []
    for row in images:
        width, height = int(row['width']), int(row['height'])
        label = label_path(dataset, row['image'])
        for index, (x, y, w, h) in enumerate(parse_label(label)):
            height_px = h * height
            truths.append(dict(image=row['image'], gt_index=index, class_id=0,
                x1=(x-w/2)*width, y1=(y-h/2)*height,
                x2=(x+w/2)*width, y2=(y+h/2)*height, height_px=height_px,
                size_band='small' if height_px < 32 else 'medium' if height_px < 96 else 'large',
                image_half='left' if x < .5 else 'right', label_sha256=sha256(label),
                color='unknown', lens='unknown', occlusion='unknown', attribute_note=''))
    reviewed = load_attributes(attributes, truths)
    for row in truths:
        row.update(reviewed.get((row['image'], row['gt_index']), {}))
    return images, truths


def intersection_over_union(a, b):
    intersection = max(0., min(a['x2'], b['x2']) - max(a['x1'], b['x1'])) * \
                   max(0., min(a['y2'], b['y2']) - max(a['y1'], b['y1']))
    area = lambda box: (box['x2']-box['x1']) * (box['y2']-box['y1'])
    union = area(a) + area(b) - intersection
    return intersection / union if union > 0 else 0.


def extract_predictions(result, image):
    if tuple(result.orig_shape) != (int(image['height']), int(image['width'])):
        raise ValueError('prediction geometry differs from original image')
    if result.boxes is None:
        raise ValueError('detector Boxes result required, not classification/segmentation-only')
    coords = result.boxes.xyxy.detach().cpu().tolist()
    scores = result.boxes.conf.detach().cpu().tolist()
    classes = result.boxes.cls.detach().cpu().tolist()
    if not len(coords) == len(scores) == len(classes):
        raise ValueError('inconsistent prediction arrays')
    rows = []
    for index, (box, score, class_id) in enumerate(zip(coords, scores, classes)):
        if len(box) != 4 or not all(math.isfinite(v) for v in [*box, score, class_id]):
            raise ValueError('nonfinite or malformed model prediction')
        x1, y1, x2, y2 = box
        if class_id != 0 or not 0 <= score <= 1 or not (
                0 <= x1 < x2 <= int(image['width']) and 0 <= y1 < y2 <= int(image['height'])):
            raise ValueError('out-of-image/degenerate prediction or wrong model class')
        rows.append(dict(image=image['image'], prediction_index=index, class_id=0,
                         confidence=score, **dict(zip(BOX_FIELDS, box))))
    return rows


def match_image(truths, predictions, threshold, match_iou):
    remaining = {row['gt_index']: row for row in truths}
    matches = []
    kept = sorted((row for row in predictions if row['confidence'] >= threshold),
                  key=lambda row: (-row['confidence'], row['prediction_index']))
    for prediction in kept:
        best = max(remaining, key=lambda key: (intersection_over_union(remaining[key], prediction), -key),
                   default=None)
        overlap = intersection_over_union(remaining[best], prediction) if best is not None else 0.
        accepted = best is not None and overlap >= match_iou
        matches.append(dict(confidence_threshold=threshold, image=prediction['image'],
                            outcome='TP' if accepted else 'FP',
                            gt_index=best if accepted else '',
                            prediction_index=prediction['prediction_index'],
                            confidence=prediction['confidence'], iou=overlap))
        if accepted:
            del remaining[best]
    for truth in remaining.values():
        matches.append(dict(confidence_threshold=threshold, image=truth['image'], outcome='FN',
                            gt_index=truth['gt_index'], prediction_index='', confidence='', iou=''))
    return matches


def aggregate(images, truths, predictions, config):
    by_gt = {row['image']: [] for row in images}
    by_pred = {row['image']: [] for row in images}
    for row in truths:
        by_gt[row['image']].append(row)
    for row in predictions:
        by_pred[row['image']].append(row)
    image_rows, matches, totals, strata = [], [], [], []
    for threshold in config['confidence_thresholds']:
        threshold_matches = []
        for image in images:
            rows = match_image(by_gt[image['image']], by_pred[image['image']], threshold, config['match_iou'])
            threshold_matches.extend(rows)
            counts = {outcome.lower(): sum(row['outcome'] == outcome for row in rows)
                      for outcome in ('TP', 'FP', 'FN')}
            image_rows.append(dict(confidence_threshold=threshold, image=image['image'],
                                   session=image['session'], frame=image['frame'], time_sec=image['time_sec'],
                                   gt_count=len(by_gt[image['image']]), **counts))
        matches.extend(threshold_matches)
        tp, fp, fn = (sum(row['outcome'] == outcome for row in threshold_matches)
                      for outcome in ('TP', 'FP', 'FN'))
        totals.append(dict(confidence_threshold=threshold, images=len(images), gt_count=len(truths),
                           tp=tp, fp=fp, fn=fn, precision=tp/(tp+fp) if tp+fp else '',
                           recall=tp/(tp+fn) if tp+fn else ''))
        matched_gt = {(row['image'], row['gt_index']) for row in threshold_matches if row['outcome'] == 'TP'}
        for dimension in ('size_band', 'image_half', 'color', 'lens', 'occlusion'):
            for value in sorted({row[dimension] for row in truths}):
                members = [row for row in truths if row[dimension] == value]
                found = sum((row['image'], row['gt_index']) in matched_gt for row in members)
                strata.append(dict(confidence_threshold=threshold, dimension=dimension, value=value,
                                   gt_count=len(members), detected=found, missed=len(members)-found,
                                   recall=found/len(members)))
    return image_rows, matches, totals, strata


def run_diagnostics(model, args, inputs):
    images, truths = inputs
    config = diagnostic_config(args)
    kwargs = prediction_kwargs(args)
    predictions, timings = [], []
    for index, image in enumerate(images):
        started = time.perf_counter()
        results = model.predict(source=str(args.dataset / image['image']), **kwargs)
        if len(results) != 1:
            raise ValueError('one original image must yield exactly one result')
        rows = extract_predictions(results[0], image)
        if len(rows) > args.max_det or any(row['confidence'] < args.prediction_floor - 1e-7 for row in rows):
            raise ValueError('prediction floor/max_det contract violated')
        predictions.extend(rows)
        elapsed = time.perf_counter() - started
        speed = results[0].speed
        values = [speed[name] for name in ('preprocess', 'inference', 'postprocess')]
        if not all(isinstance(v, (float, int)) and math.isfinite(v) and v >= 0 for v in values):
            raise ValueError('invalid per-image framework timing')
        timings.append(dict(image=image['image'], first_call=int(index == 0), predict_and_export_sec=elapsed,
                            preprocess_ms=values[0], inference_ms=values[1], postprocess_ms=values[2],
                            predictions=len(rows), max_det_reached=int(len(rows) == args.max_det)))
        print(f'[INFO] Diagnose {index+1}/{len(images)}: {len(rows)} predictions')
    image_rows, matches, totals, strata = aggregate(images, truths, predictions, config)
    output = args.output_dir
    write_csv(output / 'predictions.csv', predictions, PRED_FIELDS)
    write_csv(output / 'ground_truth.csv', truths, GT_FIELDS)
    write_csv(output / 'image_manifest.csv', images)
    write_csv(output / 'per_image.csv', image_rows)
    write_csv(output / 'matches.csv', matches,
              ('confidence_threshold', 'image', 'outcome', 'gt_index', 'prediction_index', 'confidence', 'iou'))
    write_csv(output / 'threshold_summary.csv', totals)
    write_csv(output / 'stratum_recall.csv', strata,
              ('confidence_threshold', 'dimension', 'value', 'gt_count', 'detected', 'missed', 'recall'))
    write_csv(output / 'timing.csv', timings)
    write_csv(output / 'attributes_template.csv', [dict(image=row['image'], gt_index=row['gt_index'],
              label_sha256=row['label_sha256'], color=row['color'], lens=row['lens'],
              occlusion=row['occlusion'], note=row['attribute_note']) for row in truths], ATTR_FIELDS)
    # Copy a bounded set of original PNGs byte-for-byte; never draw predicted/GT boxes.
    reference = min(config['confidence_thresholds'], key=lambda value: (abs(value-.25), value))
    candidates = sorted((row for row in image_rows if row['confidence_threshold'] == reference),
                        key=lambda row: (-(row['fn']+row['fp']), row['image']))[:3]
    assets = output / 'raw_examples'
    assets.mkdir()
    asset_rows = []
    for candidate in candidates:
        original = args.dataset / candidate['image']
        copied = assets / original.name
        shutil.copyfile(original, copied)
        if sha256(original) != sha256(copied):
            raise ValueError('raw representative copy differs from input')
        asset_rows.append(dict(**candidate, file=str(copied.relative_to(output)), png_sha256=sha256(copied)))
    write_csv(output / 'raw_example_manifest.csv', asset_rows)
    report = dict(status='COMPLETED_DIAGNOSTICS_NOT_DEPLOYMENT_APPROVAL', config=config,
                  image_count=len(images), gt_count=len(truths), prediction_count=len(predictions),
                  threshold_summary=totals, physical_output=False,
                  max_det_reached_images=sum(row['max_det_reached'] for row in timings),
                  limitations=['Post-NMS predictions only; scores below prediction floor are unavailable.',
                               'No independent test approval or Ultralytics mAP reproduction.',
                               'Unknown color/lens/occlusion are not inferred from filenames or HSV.',
                               'Timing includes first call; not live camera throughput or FFB latency.'])
    (output / 'diagnostic_summary.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# コーン画像別診断', '', 'オフライン診断完了。実用精度や実機安全性の合格ではない。', '',
             '| confidence | TP | FP | FN | Precision | Recall |', '|---|---:|---:|---:|---:|---:|']
    for row in totals:
        display = lambda value: f'{value:.4f}' if isinstance(value, (int, float)) else '未定義'
        lines.append(f"| {row['confidence_threshold']} | {row['tp']} | {row['fp']} | {row['fn']} | "
                     f"{display(row['precision'])} | {display(row['recall'])} |")
    lines.extend(['', 'IoUを満たす未使用正解枠へconfidence降順で一対一対応する診断値。',
                  'Ultralytics valの集計RecallやmAPと同一条件・同一値とは扱わない。',
                  'NMSのIoUと正解対応のIoUは別設定。色・前後・遮蔽は確認情報がなければunknown。',
                  'raw_examplesは原PNGのbyte一致コピーで、枠・注釈・補正なし。',
                  'matches.csvでFNのimage/gt_indexを探し、ground_truth.csvの枠座標と原画像を照合する。',
                  'attributes_template.csvは人の属性確認用。datasetの正解ラベルを変更するものではない。',
                  'timing.csvの最初の呼出しは準備時間を含み得る。実カメラFPSの証明ではない。', ''])
    (output / 'analysis_report.md').write_text('\n'.join(lines))
    return report
