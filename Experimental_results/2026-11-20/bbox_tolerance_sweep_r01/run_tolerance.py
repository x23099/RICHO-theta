"""Experiment harness: apply an explicit completion bbox tolerance post hoc.

The pinned runner and src files stay byte-identical, so previous GPU manifests
and their regression guards keep matching. This wrapper calls the original
observer; when the lateral completion already passed every pixel/support check
and failed ONLY at "point outside the original bbox", it re-applies that one
comparison with a bounded tolerance. Nothing else is relaxed.

Usage:
    ./yolo-env/bin/python3 run_tolerance.py --tolerance-px 1 -- <run.py args...>
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py'
SPEC = importlib.util.spec_from_file_location('pinned_gpu_runner', RUNNER)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

from cone_observation import checked_bbox

ORIGINAL = runner.observe_upper_completion
REASON = 'completed_point_outside_original_bbox'


def checked_tolerance(value):
    if type(value) is not int or not 0 <= value <= 8:
        raise ValueError('tolerance must be an integer in [0,8] pixels')
    return value


def tolerant_observer(tolerance):
    checked_tolerance(tolerance)

    def observe(image, box, camera):
        result = ORIGINAL(image, box, camera)
        if tolerance == 0 or result.get('point') is not None or result.get('completion_granted'):
            return result
        if result.get('completion_reason') != REASON:
            return result
        contexts = result.get('contexts') or []
        if len(contexts) < 2:
            return result
        observation = contexts[-1].get('observation') or {}
        point = observation.get('point')
        if type(point) is not list or len(point) != 2 or any(type(v) is not int for v in point):
            return result
        x1, y1, x2, y2 = checked_bbox(box, 1280, 720)
        if not (x1 - tolerance <= point[0] <= x2 + tolerance
                and y1 - tolerance <= point[1] <= y2 + tolerance):
            return result
        accepted = copy.deepcopy(result)
        accepted.update(point=point, support=observation.get('support'),
                        reason='unverified_lateral_completed_colour_support',
                        completion_granted=True, completion_reason='experiment_bbox_tolerance_applied',
                        bbox_tolerance_px=tolerance, controlling_distance=False,
                        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False)
        return accepted

    return observe


def provenance(tolerance, argv):
    return dict(schema='completion_bbox_tolerance_harness_v1',
                tolerance_px=tolerance,
                policy=('post-hoc only when the pinned observer failed with ' + REASON +
                        ' after all pixel/support checks'),
                pinned_runner=str(RUNNER.relative_to(ROOT)),
                pinned_runner_sha256=hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
                harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                runner_args=list(argv),
                pixel_support_or_geometry_changed=False,
                controlling_distance=False, physical_metric_verified=False,
                floor_contact_verified=False, usable_for_ffb=False)


def main(argv):
    if len(argv) < 4 or argv[0] != '--tolerance-px' or argv[2] != '--':
        raise SystemExit(__doc__)
    tolerance = checked_tolerance(int(argv[1]))
    rest = argv[3:]
    runner.observe_upper_completion = tolerant_observer(tolerance)
    code = runner.main(rest)
    if '--output-dir' in rest:
        output = Path(rest[rest.index('--output-dir') + 1])
        if output.is_dir():
            (output / 'tolerance_harness.json').write_text(
                json.dumps(provenance(tolerance, rest), indent=2) + '\n')
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
