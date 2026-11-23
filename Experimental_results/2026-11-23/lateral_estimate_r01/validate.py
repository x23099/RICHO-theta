"""Out-of-sample checks for the empirical pixel-to-lateral calibration.

1. Leave-one-out cross-validation of the common k(d) linear fit.
2. Cross-distance prediction (fit on two distances, predict the third).
3. Side-specific k(d) fits (left vs right) vs the common fit.
4. Side-sign accuracy at the 0.05 m deadband.

Only 9 calibration points exist; this is a generalisation check within the
sampled range, not a new field validation.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def fit_k(points):
    x = np.array([p['nominal_m'] for p in points])
    y = np.array([p['k_m_per_px'] for p in points])
    if len(set(x)) > 1 and len(points) >= 2:
        slope, intercept = np.polyfit(x, y, 1)
    else:
        slope, intercept = 0.0, float(y.mean())
    return float(slope), float(intercept)


def predict(point, reference, slope, intercept):
    k = intercept + slope * point['nominal_m']
    return (reference - point['box_center_x']) * k


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    calibration = json.loads(args.calibration.read_bytes())
    references = calibration['references']
    points = [p for p in calibration['points'] if p['box_center_x'] is not None]
    scales = [s for s in calibration['scale_points']]

    # 1) LOOCV over lateral scales, common linear k(d)
    loocv = []
    for held in scales:
        training = [s for s in scales if s is not held]
        slope, intercept = fit_k([dict(nominal_m=s['nominal_m'], k_m_per_px=s['k_m_per_px']) for s in training])
        k = intercept + slope * held['nominal_m']
        estimated = held['offset_px'] * k
        loocv.append(dict(nominal_m=held['nominal_m'], side=held['side'],
                          known=held['known_left_m'], estimated=round(estimated, 4),
                          residual=round(estimated - held['known_left_m'], 4)))

    # 2) cross-distance: fit on two nominal distances, predict the third
    cross = []
    distances = sorted({s['nominal_m'] for s in scales})
    for held_distance in distances:
        training = [s for s in scales if s['nominal_m'] != held_distance]
        testing = [s for s in scales if s['nominal_m'] == held_distance]
        if not training or not testing or len({s['nominal_m'] for s in training}) < 2:
            continue
        slope, intercept = fit_k([dict(nominal_m=s['nominal_m'], k_m_per_px=s['k_m_per_px']) for s in training])
        for held in testing:
            k = intercept + slope * held['nominal_m']
            estimated = held['offset_px'] * k
            cross.append(dict(held_distance_m=held_distance, side=held['side'],
                              known=held['known_left_m'], estimated=round(estimated, 4),
                              residual=round(estimated - held['known_left_m'], 4)))

    # 3) side-specific fits
    side_fits = {}
    for side in ('L', 'R'):
        subset = [s for s in scales if s['side'] == side]
        if len(subset) >= 2:
            slope, intercept = fit_k([dict(nominal_m=s['nominal_m'], k_m_per_px=s['k_m_per_px']) for s in subset])
            side_fits[side] = dict(slope=round(slope, 6), intercept=round(intercept, 6), points=len(subset))
    side_residuals = []
    for held in scales:
        side = held['side']
        if side not in side_fits:
            continue
        fit = side_fits[side]
        k = fit['intercept'] + fit['slope'] * held['nominal_m']
        estimated = held['offset_px'] * k
        side_residuals.append(dict(nominal_m=held['nominal_m'], side=side, known=held['known_left_m'],
                                   estimated=round(estimated, 4),
                                   residual=round(estimated - held['known_left_m'], 4)))

    # 4) side sign accuracy over all measurement points
    sign_checks = []
    common = calibration['fit']
    for point in points:
        reference = references.get(str(point['nominal_m']))
        if reference is None:
            continue
        k = common['intercept'] + common['slope_m_per_px_per_m'] * point['nominal_m']
        estimate = (reference - point['box_center_x']) * k
        known = point['known_left_m']
        if abs(known) <= 0.05:
            continue
        sign_checks.append(dict(known=known, estimated=round(estimate, 4),
                                correct=(np.sign(estimate) == np.sign(known))))

    def summary(values):
        residuals = [abs(v['residual']) for v in values]
        return dict(count=len(residuals), abs_max_m=round(max(residuals), 4) if residuals else None,
                    rms_m=round(float(np.sqrt(np.mean(np.square(residuals)))), 4) if residuals else None)

    report = dict(schema='lateral_calibration_validation_v1',
                  state='in_sample_generalisation_check_NOT_field_validation',
                  loocv=dict(rows=loocv, summary=summary(loocv)),
                  cross_distance=dict(rows=cross, summary=summary(cross)),
                  side_specific=dict(fits=side_fits, rows=side_residuals, summary=summary(side_residuals)),
                  common_fit_residuals=dict(abs_max_m=calibration['residual_abs_max_m'],
                                            rms_m=calibration['residual_rms_m']),
                  side_sign=dict(checks=len(sign_checks),
                                 correct=sum(1 for c in sign_checks if c['correct'])),
                  camera_or_gpu_used=False, physical_metric_verified=False, usable_for_ffb=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('loocv', 'cross_distance', 'side_specific',
                                                   'side_sign')}, indent=2))


if __name__ == '__main__':
    main()
