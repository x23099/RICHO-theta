"""Audit the received standalone val without importing/deserializing a model."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    training = output.with_name('cone_ab_bootstrap_training')
    prefix = 'val_ab_bootstrap_v01_r01'
    expected = {'provenance.json', 'metrics.json', 'environment_freeze.txt'}
    payloads = {}
    seen = set()
    total = 0
    with tarfile.open(args.input, 'r:xz') as archive:
        for index, member in enumerate(archive):
            name = member.name.rstrip('/')
            path = PurePosixPath(name)
            if index >= 100 or path.is_absolute() or '..' in path.parts or name in seen:
                raise ValueError('Unsafe/duplicate archive entry or member limit exceeded')
            seen.add(name)
            if member.isdir() and name in {prefix, prefix + '/best'}:
                continue
            if not member.isfile() or path.parent != PurePosixPath(prefix) or path.name not in expected:
                raise ValueError(f'Unexpected archive entry: {name}')
            total += member.size
            if total > 1024 * 1024 or member.size < 0:
                raise ValueError('Archive payload size limit exceeded')
            with archive.extractfile(member) as stream:
                payloads[path.name] = stream.read()
    if set(payloads) != expected:
        raise ValueError('Required validation artifacts missing')
    provenance = json.loads(payloads['provenance.json'])
    metrics = json.loads(payloads['metrics.json'])
    train_provenance = json.loads((training / 'provenance.json').read_text())
    train_metrics = json.loads((training / 'metrics.json').read_text())
    train_verification = json.loads((training / 'verification.json').read_text())
    dataset_keys = ('manifest_sha256', 'reviews_sha256', 'labels_sha256',
                    'data_yaml_sha256', 'counts')
    checks = {
        'completed_val': provenance['mode'] == 'val' and provenance['status'] ==
            'COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL',
        'physical_output_disabled': provenance['physical_output'] is False,
        'same_best_checkpoint': provenance['weights_sha256'] ==
            train_verification['artifacts']['yolov8n/weights/best.pt']['sha256'],
        'same_dataset_and_labels': all(provenance['dataset_check'][key] ==
            train_provenance['dataset_check'][key] for key in dataset_keys),
        'val_split': provenance['kwargs']['split'] == 'val',
        'gpu_device_zero': provenance['kwargs']['device'] == 0,
        'metrics_finite_and_bounded': all(isinstance(value, (int, float)) and
            math.isfinite(value) and 0 <= value <= 1 for value in metrics.values()),
    }
    if not all(checks.values()):
        raise ValueError(f'Validation receipt failed: {checks}')
    rows = [dict(metric=key, training_reported=train_metrics[key],
                 standalone_val=metrics[key],
                 delta_percentage_points=100 * (metrics[key] - train_metrics[key]))
            for key in ('metrics/precision(B)', 'metrics/recall(B)',
                        'metrics/mAP50(B)', 'metrics/mAP50-95(B)')]
    # Never silently replace a different received run.
    for name, data in payloads.items():
        target = output / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError(f'Conflicting existing artifact: {target}')
    for name, data in payloads.items():
        (output / name).write_bytes(data)
    with (output / 'metric_comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    receipt = dict(date='2026-10-12',
                   decision='PASS_VAL_COMPLETION_NOT_DEPLOYMENT_APPROVAL',
                   archive=str(args.input.resolve()),
                   archive_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                   checks=checks, metrics=metrics, comparison=rows,
                   payload_sha256={name: hashlib.sha256(data).hexdigest()
                                   for name, data in payloads.items()},
                   per_image_predictions_available=False,
                   independent_test_available=False,
                   local_model_inference_performed=False,
                   checkpoints_deserialized=False)
    (output / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(decision=receipt['decision'], checks=checks), indent=2))


if __name__ == '__main__':
    main()
