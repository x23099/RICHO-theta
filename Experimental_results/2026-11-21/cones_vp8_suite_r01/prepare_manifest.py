"""Build a SHA-pinned manifest from saved 1280x720 decoded PNGs.

Run on the GPU PC where the images live. No camera, ROS or network.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import cv2
import numpy as np

NAME = re.compile(r'decoded_[A-Za-z0-9]+_f([0-9]{6})\.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--roi', type=int, nargs=4, required=True,
                        help='native front ROI x1 y1 x2 y2 used for the whole session')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=40)
    args = parser.parse_args()
    directory = args.input_dir.resolve()
    output = args.output.resolve()
    if not directory.is_dir():
        raise SystemExit('existing input directory required')
    if output.exists():
        raise SystemExit('unused manifest path required')
    x1, y1, x2, y2 = args.roi
    if not (0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 720):
        raise SystemExit('native front ROI x1 y1 x2 y2 required (x2<=640)')
    if type(args.limit) is not int or not 1 <= args.limit <= 200:
        raise SystemExit('bounded image limit required')
    files = sorted((p for p in directory.iterdir() if NAME.fullmatch(p.name)),
                   key=lambda p: int(NAME.fullmatch(p.name)[1]))
    if len(files) < 2:
        raise SystemExit('at least two decoded frames required')
    if len(files) > args.limit:
        files = files[:args.limit]
    images, seen = [], set()
    for path in files:
        data = path.read_bytes()
        if len(data) > 4 * 1024 * 1024:
            raise SystemExit('oversized saved PNG: ' + path.name)
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape != (720, 1280, 3) or image.dtype != np.uint8:
            raise SystemExit('1280x720 uint8 BGR required: ' + path.name)
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            raise SystemExit('duplicate image content: ' + path.name)
        seen.add(digest)
        images.append(dict(name=path.name, path=str(path), sha256=digest))
    manifest = dict(schema='saved_png_manifest_v1', roi_native_xyxy=[x1, y1, x2, y2],
                    image_size=[1280, 720], images=images,
                    images_modified=False, camera_originals=False,
                    physical_metric_verified=False, usable_for_ffb=False)
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(images=len(images), roi=[x1, y1, x2, y2], output=str(output)), indent=2))


if __name__ == '__main__':
    main()
