"""Copy three native evidence PNGs and one data plot, without pixel editing."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
EVIDENCE = ROOT / ('recordings/2026-11-10/driver_motion_171250_intake_r01/'
                   'motion_withheld_20261110_171250')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    index = [json.loads(line) for line in (EVIDENCE/'evidence_index.jsonl').read_text().splitlines()]
    items = []
    for sequence in (14203, 14604, 14922):
        item, = [entry for entry in index if entry['frame'] == sequence]
        source = EVIDENCE / item['image_file']
        assert sha(source) == item['png_sha256']
        items.append((source, dict(kind='unmodified_native_png', session=item['session'],
            frame=sequence, png_sha256=item['png_sha256'], image_size=[1280, 720],
            source_archive='motion_withheld_20261110_171250.tar.xz')))
    plot = ROOT / ('Experimental_results/2026-11-10/motion_boundary_timeline_r01/'
                   'results_r01/distance_timeline.svg')
    items.append((plot, dict(kind='data_derived_svg_NOT_camera_overlay',
        source_csv='Experimental_results/2026-11-10/motion_boundary_timeline_r01/results_r01/local_window.csv',
        generator='Experimental_results/2026-11-10/motion_boundary_timeline_r01/plot_timeline.py')))
    manifest = []
    for source, metadata in items:
        destination = OUT / source.name
        if destination.exists():
            assert sha(destination) == sha(source), 'refuse to overwrite different asset'
        else:
            shutil.copyfile(source, destination)
        assert sha(source) == sha(destination)
        manifest.append(dict(file=destination.name, source=str(source.relative_to(ROOT)),
            sha256=sha(source), **metadata))
    payload = dict(schema='daily_report_assets_v1', date='2026-11-10',
        script_sha256=sha(Path(__file__)), camera_pixels_modified=False, assets=manifest)
    target = OUT/'provenance.json'
    text = json.dumps(payload, ensure_ascii=False, indent=2)+'\n'
    if target.exists():
        assert target.read_text() == text
    else:
        target.write_text(text)
    print('4 assets copied byte-for-byte; camera pixels unchanged')


if __name__ == '__main__':
    main()
