"""Three fixed saved images, one existing CUDA runner. No live/control setup."""
import argparse
from contextlib import nullcontext
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LEGACY = ROOT/'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py'
SPEC = importlib.util.spec_from_file_location('packet_saved_suite_probe', LEGACY)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
LEGACY_SHA = '00111723b8149310573432d77ffac0499d5326c0f8f044412d2e1122cba2a78b'
FRAMES = ('028980', '037696', '044793')
NAMES = tuple('decoded_24aad0a8d31d46eeb33ef252b0d18475_f'+n+'.png' for n in FRAMES)
ROI = [270, 0, 350, 720]
MAX_FILES = 100000
MAX_DIRS = 20000
PACK_ROOT = 'packet_saved_suite_inputs_r01/'


def manifest():
    return dict(schema='packet_saved_suite_inputs_v1', image_size=[1280,720],
        images=[dict(name=name, png_sha256=probe.KNOWN_IMAGES[name], target_roi=ROI) for name in NAMES],
        images_modified=False, physical_metric_verified=False, usable_for_ffb=False)


def find_inputs(roots):
    """Bounded name lookup, no symlink following, deterministic hash selection."""
    found, scanned, directories = {}, 0, 0
    for root in roots:
        root = Path(root).absolute()
        if not root.is_dir() or root.is_symlink():
            continue
        for directory, children, filenames in os.walk(root, followlinks=False):
            children[:] = sorted(n for n in children if n not in ('.git', '__pycache__', 'ultralytics_config')
                                 and not (Path(directory)/n).is_symlink())
            directories += 1
            scanned += len(filenames)
            if directories > MAX_DIRS or scanned > MAX_FILES:
                raise ValueError('saved input search limit exceeded; use --input-archive')
            for name in sorted(set(filenames).intersection(NAMES)):
                path = Path(directory)/name
                try:
                    data = probe.bounded_regular_bytes(path, 4*1024*1024)
                except (ValueError, OSError):
                    continue
                if probe.sha_bytes(data) == probe.KNOWN_IMAGES[name] and name not in found:
                    found[name] = path
    missing = [name for name in NAMES if name not in found]
    if missing:
        raise FileNotFoundError('known saved images missing (no GPU started): '+', '.join(missing)+
            '; copy the prepared input pack to GPU Downloads and use --input-archive')
    return [found[name] for name in NAMES]


def prepare_pack(archive, paths):
    jobs = probe.load_images(paths)
    by_name = {Path(j['path']).name:j for j in jobs}
    if set(by_name) != set(NAMES):
        raise ValueError('all three exact saved sources required')
    payload = {name:probe.bounded_regular_bytes(by_name[name]['path'],4*1024*1024) for name in NAMES}
    payload['manifest.json'] = probe.json_bytes(manifest())
    with Path(archive).open('xb') as target:
        with tarfile.open(fileobj=target,mode='w:xz') as bundle:
            for name,data in payload.items():
                member = tarfile.TarInfo(PACK_ROOT+name)
                member.size, member.mode, member.mtime = len(data), 0o644, 0
                bundle.addfile(member,io.BytesIO(data))
    probe.assert_originals(jobs)
    return dict(archive=str(archive),sha256=probe.digest(archive),bytes=Path(archive).stat().st_size,
                image_count=3, original_PNG_bytes_preserved=True)


def unpack_inputs(archive, directory):
    # Exact allowlist, no tar extract()/extractall(), no instructions execution.
    wire = probe.bounded_regular_bytes(archive,16*1024*1024)
    entries = {}
    with tarfile.open(fileobj=io.BytesIO(wire),mode='r:xz') as bundle:
        for member in bundle:
            expected = {PACK_ROOT+n for n in (*NAMES,'manifest.json')}
            if (not member.isfile() or member.name not in expected or member.name in entries
                    or not 0 < member.size <= 4*1024*1024):
                raise ValueError('exact regular saved image pack required')
            entries[member.name] = bundle.extractfile(member).read(4*1024*1024+1)
    if set(entries) != {PACK_ROOT+n for n in (*NAMES,'manifest.json')}:
        raise ValueError('incomplete saved image pack')
    if entries[PACK_ROOT+'manifest.json'] != probe.json_bytes(manifest()):
        raise ValueError('saved image manifest differs from fixed suite')
    paths = []
    for name in NAMES:
        data = entries[PACK_ROOT+name]
        if probe.sha_bytes(data) != probe.KNOWN_IMAGES[name]:
            raise ValueError('saved PNG SHA mismatch')
        path = Path(directory)/name
        with path.open('xb') as target:
            target.write(data)
        paths.append(path)
    probe.load_images(paths)
    return paths


def summarize_by_image(output):
    output = Path(output)
    rows = [json.loads(line) for line in probe.bounded_regular_bytes(output/'samples.jsonl',probe.MAX_LOG).splitlines()]
    pairs = [json.loads(line) for line in probe.bounded_regular_bytes(output/'pairs.jsonl',probe.MAX_LOG).splitlines()]
    if len(rows) != 60 or len(pairs) != 30:
        raise ValueError('all 60 measured samples / 30 pairs required')
    result = []
    for name in NAMES:
        sha = probe.KNOWN_IMAGES[name]
        image_rows = [r for r in rows if r['source_png_sha256'] == sha]
        image_pairs = [p for p in pairs if p['source_png_sha256'] == sha]
        if len(image_rows) != 20 or len(image_pairs) != 10:
            raise ValueError('each image must retain 20 samples / 10 pairs')
        result.append(dict(image=name,png_sha256=sha,target_roi_native_xyxy=ROI,
                           **probe.summarize(image_rows,image_pairs)))
    return result


def execute(args):
    output, archive = args.output_dir.resolve(), args.archive.absolute()
    if (output.exists() or archive.exists() or not archive.parent.is_dir()
            or output == archive or output in archive.resolve().parents):
        raise ValueError('unused result and archive with existing parent required')
    if probe.digest(LEGACY) != LEGACY_SHA:
        raise ValueError('previous verified runner changed; do not silently mix versions')
    context = tempfile.TemporaryDirectory(prefix='theta-packet-saved-suite-') if args.input_archive else nullcontext(None)
    with context as temporary:
        paths = unpack_inputs(args.input_archive,temporary) if args.input_archive else find_inputs(
            args.search_root or [ROOT/'recordings',ROOT/'Experimental_results'])
        probe.load_images(paths)  # Validate all originals before CUDA/model setup.
        command = ['--weights',str(args.weights),'--experimental-rigid-mount','--output-dir',str(output),
                   '--target-roi',*map(str,ROI)]
        for path in paths:
            command.extend(('--image',str(path)))
        status = probe.main(command)  # Existing one CUDA predictor, no repeated model startup.
        if status != 0:
            return status
        try:
            values = summarize_by_image(output)
            with (output/'per_image_summary.json').open('xb') as target:
                target.write(probe.json_bytes(values))
            with (output/'suite_manifest.json').open('xb') as target:
                target.write(probe.json_bytes(dict(schema='packet_saved_suite_GPU_v1',
                    inputs=manifest(), resolved_input_paths=list(map(str,paths)),
                    input_pack_sha256=probe.digest(args.input_archive) if args.input_archive else None,
                    runner_sha256=LEGACY_SHA, suite_runner_sha256=probe.digest(__file__),
                    per_image_summary_sha256=probe.digest(output/'per_image_summary.json'),
                    old_single_image_repeated=False, source_images_modified=False,
                    live_transport_adopted=False, **probe.FLAGS)))
            probe.pack_result(output,archive)
        except BaseException as error:
            summary = json.loads((output/'summary.json').read_bytes())
            summary.update(state='failed',suite_error=f'{type(error).__name__}: {error}'[:2000])
            probe.save_summary(output,summary)
            raise
        print(json.dumps(dict(state='complete',images=3,measured_samples=60,paired_samples=30,
                              archive=str(archive)),indent=2))
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action',required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--archive',type=Path,required=True)
    prepare.add_argument('--search-root',type=Path,action='append')
    run = sub.add_parser('run')
    run.add_argument('--weights',type=Path,required=True)
    run.add_argument('--output-dir',type=Path,required=True)
    run.add_argument('--archive',type=Path,required=True)
    run.add_argument('--input-archive',type=Path)
    run.add_argument('--search-root',type=Path,action='append')
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            paths = find_inputs(args.search_root or [ROOT/'recordings',ROOT/'Experimental_results'])
            print(json.dumps(prepare_pack(args.archive,paths),indent=2))
            return 0
        if args.input_archive and args.search_root:
            raise ValueError('choose input archive OR search roots, not both')
        return execute(args)
    except (Exception,KeyboardInterrupt) as error:
        print(f'[ERROR] saved suite incomplete: {type(error).__name__}: {error}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
