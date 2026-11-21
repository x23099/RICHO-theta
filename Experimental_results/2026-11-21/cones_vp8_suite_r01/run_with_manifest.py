"""Run the pinned saved-image VP8/original comparison from a SHA-pinned manifest.

Keeps the pinned runner and src byte-identical: only the in-memory allowlist is
extended from the manifest, and optionally the bottom-contact fallback wrapper
is applied. No camera, ROS, FFB or network.

Usage:
    ./yolo-env/bin/python3 run_with_manifest.py --manifest m.json [--bottom-fallback] -- \
        --weights ... --experimental-rigid-mount --target-roi 270 0 350 720 \
        --output-dir ... --archive ...
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py'
BOTTOM = ROOT / 'Experimental_results/2026-11-10/bottom_extension_probe_r01/probe.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_manifest(path):
    value = json.loads(Path(path).read_bytes())
    if value.get('schema') != 'saved_png_manifest_v1':
        raise SystemExit('saved_png_manifest_v1 required')
    images = value.get('images')
    if type(images) is not list or not 2 <= len(images) <= 200:
        raise SystemExit('bounded image list required')
    paths, seen = [], set()
    for item in images:
        path = Path(item['path'])
        if not path.is_file():
            raise SystemExit('missing image: ' + str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item['sha256'] or digest in seen:
            raise SystemExit('changed/duplicate image: ' + str(path))
        seen.add(digest)
        paths.append((str(path), path.name, digest))
    roi = value.get('roi_native_xyxy')
    if type(roi) is not list or len(roi) != 4:
        raise SystemExit('manifest ROI required')
    return paths, roi, value


def bottom_fallback(runner, probe):
    original = runner.observe_upper_completion

    def observe(image, box, camera):
        base = original(image, box, camera)
        if base.get('point') is not None or base.get('reason') != 'colour_contour_reaches_roi_edge':
            return base
        result = probe.probe_bottom_extension(image, box, camera)
        if not result.get('guarded_candidate'):
            return base
        accepted = copy.deepcopy(result['guarded_observation'])
        accepted.update(bottom_fallback_applied=True,
                        bottom_fallback_reason=result.get('reason'),
                        controlling_distance=False, floor_contact_verified=False,
                        physical_metric_verified=False, usable_for_ffb=False)
        return accepted

    return observe


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--bottom-fallback', action='store_true')
    parser.add_argument('--provenance', type=Path)
    parser.add_argument('--yellow-s-min', type=int, default=80,
                        help='experimental yellow saturation floor; 80 preserves the old behaviour')
    parser.add_argument('--max-images', type=int, default=200)
    parser.add_argument('--max-timeout-sec', type=float, default=900.0)
    args, rest = parser.parse_known_args(argv)
    if '--' in rest:
        rest = rest[rest.index('--') + 1:]
    if rest[:1] == ['--']:
        rest = rest[1:]
    if args.max_images < 1 or args.max_timeout_sec <= 0:
        raise SystemExit('positive max-images and max-timeout-sec required')
    paths, roi, manifest = read_manifest(args.manifest)
    if len(paths) > args.max_images:
        raise SystemExit(
            f'manifest has {len(paths)} images; --max-images={args.max_images}'
        )
    runner = load(RUNNER, 'pinned_gpu_runner')
    import cone_colour_support_candidate as colour_support
    colour_support.YELLOW_SATURATION_MIN = colour_support.checked_yellow_saturation_min(args.yellow_s_min)
    runner.MAX_IMAGES = args.max_images
    runner.MAX_TIMEOUT_SEC = args.max_timeout_sec
    for path, name, digest in paths:
        runner.KNOWN_IMAGES[name] = digest
    probe = None
    if args.bottom_fallback:
        probe = load(BOTTOM, 'bottom_extension_probe')
        runner.observe_upper_completion = bottom_fallback(runner, probe)
    if '--target-roi' not in rest:
        rest += ['--target-roi', *map(str, roi)]
    for path, _, _ in paths:
        rest += ['--image', path]
    code = runner.main(rest)
    if '--output-dir' in rest:
        output = Path(rest[rest.index('--output-dir') + 1])
        if output.is_dir():
            record = dict(schema='manifest_run_v1', harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          runner_sha256=hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
                          manifest_sha256=hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest(),
                          images=len(paths), bottom_fallback=bool(args.bottom_fallback),
                          roi_native_xyxy=roi, runner_args=rest,
                          yellow_saturation_min=args.yellow_s_min,
                          max_images=args.max_images,
                          max_timeout_sec=args.max_timeout_sec,
                          runner_and_src_unchanged=True, usable_for_ffb=False, published_to_ros=False)
            (output / 'manifest_run.json').write_text(json.dumps(record, indent=2) + '\n')
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
