#!/usr/bin/env python3
"""Offline cone dataset preparation and fail-closed annotation validation.

Whole raw frames, no colour-derived pseudo-labels, no ROS or model execution.
Splits are explicit capture groups, not random adjacent video frames.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

import cv2

SPLITS = ("train", "val", "test")
LABEL_CACHES = {f"labels/{split}.cache" for split in SPLITS}
PLAN_FIELDS = ("session_dir", "group_id", "split", "start_frame", "end_frame", "stride_frames", "notes")
REVIEW_FIELDS = ("image", "status", "note", "label_sha256")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, fields=None):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def integer(value, name, minimum=1):
    if not re.fullmatch(r"\d+", str(value).strip()) or int(value) < minimum:
        raise ValueError(f"{name}: integer >= {minimum} required")
    return int(value)


def load_plan(path, *, development_only=False):
    path = Path(path).resolve()
    rows = read_csv(path)
    if not rows or any(set(PLAN_FIELDS)-set(row) for row in rows):
        raise ValueError("nonempty recording plan with required columns needed")
    output, groups, sessions = [], {}, set()
    for row in rows:
        if not row["session_dir"].strip():
            raise ValueError("session_dir is blank; template is not captured data")
        session = Path(row["session_dir"]).expanduser()
        session = (path.parent/session).resolve() if not session.is_absolute() else session.resolve()
        if session in sessions:
            raise ValueError("a session can appear only once in the plan")
        sessions.add(session)
        group, split = row["group_id"].strip(), row["split"].strip()
        if not ID.fullmatch(group) or split not in SPLITS:
            raise ValueError("ASCII group_id and train/val/test split required")
        if group in groups and groups[group] != split:
            raise ValueError("capture group crosses splits; leakage")
        groups[group] = split
        start = integer(row["start_frame"], "start_frame")
        end = integer(row["end_frame"], "end_frame") if row["end_frame"].strip() else None
        stride = integer(row["stride_frames"], "stride_frames")
        if end is not None and end < start:
            raise ValueError("end_frame precedes start_frame")
        output.append(dict(row, session_dir=str(session), group_id=group, split=split,
                           start_frame=start, end_frame=end, stride_frames=stride))
    required=set(SPLITS[:2] if development_only else SPLITS)
    if set(groups.values()) != required:
        raise ValueError("development-only requires train/val only" if development_only
                         else "explicit train, val and untouched test groups required")
    return output


def dataset_yaml(root, *, development_only=False):
    test="" if development_only else "test: images/test\n"
    return (f"path: {json.dumps(str(Path(root).resolve()))}\ntrain: images/train\n"
            f"val: images/val\n{test}names:\n  0: traffic_cone\n")


def available_splits(metadata):
    dev=metadata.get('development_only',False)
    if type(dev) is not bool:
        raise ValueError("development_only must be an explicit boolean")
    expected=SPLITS[:2] if dev else SPLITS
    if metadata.get('available_splits',list(expected))!=list(expected):
        raise ValueError("available_splits and dataset role disagree")
    return expected


def label_path(root, image):
    p = Path(image)
    if len(p.parts) != 3 or p.parts[0] != "images" or p.parts[1] not in SPLITS or p.suffix != ".png":
        raise ValueError("image must be an exact manifest images/SPLIT/FILE.png path")
    root=Path(root).resolve()
    result=root/"labels"/p.parts[1]/(p.stem+".txt")
    if not result.resolve().is_relative_to(root):
        raise ValueError("label path escapes dataset")
    return result


def parse_label(path, *, reject_duplicates=True):
    boxes = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5 or fields[0] != "0":
            raise ValueError(f"{path}: only class 0 traffic_cone, five columns allowed")
        try:
            x,y,w,h = map(float, fields[1:])
        except ValueError as exc:
            raise ValueError(f"{path}: invalid coordinates") from exc
        if not all(math.isfinite(v) for v in (x,y,w,h)) or not (0 < w <= 1 and 0 < h <= 1):
            raise ValueError(f"{path}: finite normalized positive box sizes required")
        if min(x-w/2,y-h/2) < -1e-6 or max(x+w/2,y+h/2) > 1+1e-6:
            raise ValueError(f"{path}: box outside image")
        box=(x,y,w,h)
        if reject_duplicates and box in boxes:
            raise ValueError(f"{path}: duplicate annotation box; explicitly correct/review labels before training")
        boxes.append(box)
    return boxes


def verify_image(root, row):
    root = Path(root).resolve()
    path = root/row["image"]
    label_path(root,row["image"])  # validate relative structure before opening
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("image link or traversal not allowed")
    if sha256(path) != row["png_sha256"]:
        raise ValueError("raw PNG changed after export")
    frame = cv2.imread(str(path))
    if frame is None or list(frame.shape) != [int(row["height"]),int(row["width"]),3]:
        raise ValueError("image cannot be decoded or geometry changed")
    if hashlib.sha256(frame.tobytes()).hexdigest() != row["decoded_bgr_sha256"]:
        raise ValueError("saved pixels differ from exported raw frame")
    return frame


def prepare(plan_path, output, *, development_only=False):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("dataset output already exists; choose a new version (no overwrite)")
    plan = load_plan(plan_path,development_only=development_only)
    active_splits=SPLITS[:2] if development_only else SPLITS
    output.parent.mkdir(parents=True, exist_ok=True)
    sources, exported, skipped = [], [], []
    hashes, video_splits = {}, {}
    with tempfile.TemporaryDirectory(prefix=".cone_prepare_", dir=output.parent) as temporary:
        stage = Path(temporary)/"dataset"
        stage.mkdir()
        for split in active_splits:
            (stage/"images"/split).mkdir(parents=True)
            (stage/"labels"/split).mkdir(parents=True)
        for entry in plan:
            session = Path(entry["session_dir"])
            for name in ("metadata.json","detections.csv","raw.avi"):
                if not (session/name).is_file():
                    raise ValueError(f"missing {session/name}")
            metadata = json.loads((session/"metadata.json").read_text())
            rows = read_csv(session/"detections.csv")
            if not rows or [int(r["frame"]) for r in rows] != list(range(1,len(rows)+1)):
                raise ValueError("CSV requires contiguous one-based frame IDs")
            start, end = entry["start_frame"], entry["end_frame"] or len(rows)
            if end > len(rows) or start > end:
                raise ValueError("requested frames outside CSV")
            video_sha = sha256(session/"raw.avi")
            if video_sha in video_splits and video_splits[video_sha] != entry["split"]:
                raise ValueError("identical source video crosses splits")
            video_splits[video_sha] = entry["split"]
            width,height = int(metadata["requested_camera_width"]),int(metadata["requested_camera_height"])
            selected = set(range(start,end+1,entry["stride_frames"]))
            capture = cv2.VideoCapture(str(session/"raw.avi"))
            if not capture.isOpened():
                raise ValueError("cannot open raw video")
            decoded = 0
            try:
                for number in range(1,len(rows)+1):
                    ok,frame = capture.read()
                    if not ok or frame.shape != (height,width,3):
                        raise ValueError("video shorter than CSV or recorded geometry mismatch")
                    decoded += 1
                    if number not in selected:
                        continue
                    digest = hashlib.sha256(frame.tobytes()).hexdigest()
                    if digest in hashes:
                        if hashes[digest] != entry["split"]:
                            raise ValueError("identical decoded frame crosses splits")
                        skipped.append(dict(session=session.name,frame=number,reason="duplicate_same_split_raw_pixels"))
                        continue
                    hashes[digest] = entry["split"]
                    image = f"images/{entry['split']}/{entry['group_id']}_{video_sha[:16]}_f{number:06d}.png"
                    target = stage/image
                    if target.exists() or not cv2.imwrite(str(target),frame):
                        raise ValueError("image naming collision or PNG export failure")
                    saved = cv2.imread(str(target))
                    if saved is None or hashlib.sha256(saved.tobytes()).hexdigest() != digest:
                        raise ValueError("PNG pixels differ from decoded raw")
                    exported.append(dict(image=image,split=entry["split"],group_id=entry["group_id"],
                        session=session.name,frame=number,time_sec=rows[number-1]["time_sec"],
                        width=width,height=height,decoded_bgr_sha256=digest,png_sha256=sha256(target),
                        source_raw_sha256=video_sha))
                if capture.read()[0]:
                    raise ValueError("video longer than CSV")
            finally:
                capture.release()
            sources.append(dict(**entry,decoded_frames=decoded,
                sha256={name:sha256(session/name) for name in ("raw.avi","metadata.json","detections.csv")}))
        if any(not any(r["split"]==s for r in exported) for s in active_splits):
            raise ValueError("each split needs exported images")
        write_csv(stage/"manifest.csv",exported)
        write_csv(stage/"reviews.csv",[dict(image=r["image"],status="pending",note="",label_sha256="") for r in exported],REVIEW_FIELDS)
        (stage/"dataset.json").write_text(json.dumps(dict(schema_version=1,classes=["traffic_cone"],
            development_only=development_only,available_splits=list(active_splits),
            sources=sources,plan_sha256=sha256(plan_path),manifest_sha256=sha256(stage/"manifest.csv"),
            image_policy="whole raw frame; original resolution; no overlay/crop/resize/colour change",
            duplicate_same_split_skipped=skipped,leakage_limit="Exact-hash and declared-group checks only; similar re-encoded images and undisclosed capture overlap require manual review."),indent=2)+"\n")
        (stage/"data.yaml").write_text(dataset_yaml(output,development_only=development_only))
        # Labels stay absent until an explicit human positive/negative review.
        stage.rename(output)
    return dict(dataset=str(output),images=len(exported),pending_annotations=len(exported))


def mark_review(root, image, status, note):
    if status not in ("positive","negative") or not note.strip():
        raise ValueError("explicit positive/negative review and note required")
    root = Path(root).resolve()
    manifest = read_csv(root/"manifest.csv")
    row = next((r for r in manifest if r["image"]==image),None)
    if row is None:
        raise ValueError("image not in dataset manifest")
    verify_image(root,row)
    reviews=read_csv(root/"reviews.csv")
    if len({r["image"] for r in reviews})!=len(reviews) or {r["image"] for r in reviews}!={r["image"] for r in manifest}:
        raise ValueError("review table differs from manifest")
    label = label_path(root,image)
    if label.is_symlink():
        raise ValueError("label symlinks forbidden")
    boxes = parse_label(label) if label.exists() else []
    if status=="positive" and not boxes:
        raise ValueError("positive review needs manually annotated boxes")
    if status=="negative" and boxes:
        raise ValueError("negative review cannot discard existing boxes")
    if not label.exists():
        label.write_text("")  # only after an explicit negative declaration
    for r in reviews:
        if r["image"]==image:
            r.update(status=status,note=note,label_sha256=sha256(label))
    write_csv(root/"reviews.csv",reviews,REVIEW_FIELDS)


def validate(root, *, require_test=False):
    root=Path(root).resolve()
    metadata=json.loads((root/"dataset.json").read_text())
    if metadata.get("classes")!=["traffic_cone"] or metadata.get("schema_version")!=1:
        raise ValueError("unsupported dataset schema/classes")
    active_splits=available_splits(metadata)
    development_only=metadata.get('development_only',False)
    if require_test and development_only:
        raise ValueError("development-only dataset has no independent test; val is never reused as test")
    if sha256(root/"manifest.csv")!=metadata["manifest_sha256"]:
        raise ValueError("manifest changed since export")
    if (root/"data.yaml").read_text()!=dataset_yaml(root,development_only=development_only):
        raise ValueError("data.yaml changed or dataset moved: regenerate only its path using relocate")
    rows=read_csv(root/"manifest.csv")
    reviews=read_csv(root/"reviews.csv")
    by_image={r["image"]:r for r in reviews}
    if not rows or len(by_image)!=len(reviews) or set(by_image)!={r["image"] for r in rows}:
        raise ValueError("review table mismatch")
    if len({r["image"] for r in rows})!=len(rows):
        raise ValueError("duplicate manifest image")
    groups,video_splits,pixel_splits={}, {}, {}
    counts={s:dict(images=0,positive=0,negative=0,boxes=0) for s in active_splits}
    label_hashes={}
    for r in rows:
        split=r["split"]
        if split not in active_splits or Path(r["image"]).parts[1]!=split:
            raise ValueError("image/split mismatch")
        for key,table in (("group_id",groups),("source_raw_sha256",video_splits),("decoded_bgr_sha256",pixel_splits)):
            value=r[key]
            if value in table and table[value]!=split:
                raise ValueError(f"{key} crosses splits")
            table[value]=split
        verify_image(root,r)
        review=by_image[r["image"]]
        if review["status"] not in ("positive","negative") or not review["note"].strip():
            raise ValueError(f"unreviewed annotation: {r['image']}; never assume background")
        label=label_path(root,r["image"])
        if not label.is_file() or label.is_symlink():
            raise ValueError("explicit label file required even for a reviewed negative")
        boxes=parse_label(label)
        if bool(boxes)!=(review["status"]=="positive"):
            raise ValueError("label and positive/negative review disagree")
        if review.get("label_sha256")!=sha256(label):
            raise ValueError("label changed since human review; explicitly review it again")
        c=counts[split]
        c["images"]+=1; c[review["status"]]+=1; c["boxes"]+=len(boxes)
        label_hashes[str(label.relative_to(root))]=sha256(label)
    expected_images={r["image"] for r in rows}
    actual_images={str(p.relative_to(root)) for p in (root/"images").rglob('*') if p.is_file()}
    expected_labels=set(label_hashes)
    actual_labels={str(p.relative_to(root)) for p in (root/"labels").rglob('*') if p.is_file()
                   and str(p.relative_to(root)) not in LABEL_CACHES}
    if actual_images!=expected_images or actual_labels!=expected_labels:
        raise ValueError("unmanifested image/label files; Ultralytics would see different data")
    if any(c["positive"]==0 for c in counts.values()):
        raise ValueError("at least one positive image required in each split")
    return dict(status="PASS_DATASET_INTEGRITY_NOT_MODEL_ACCURACY",dataset=str(root),counts=counts,
        development_only=development_only,independent_test_available=not development_only,
        manifest_sha256=sha256(root/"manifest.csv"),reviews_sha256=sha256(root/"reviews.csv"),
        data_yaml_sha256=sha256(root/"data.yaml"),labels_sha256=label_hashes,
        warnings=[f"{s}: no reviewed negatives" for s,c in counts.items() if not c["negative"]],
        independent_review_required=True)


def invalidate_label_caches(root):
    """Remove only framework-generated split caches; reviewed .txt stay intact."""
    root=Path(root).resolve()
    removed=[]
    for relative in sorted(LABEL_CACHES):
        path=root/relative
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("label cache must be a regular file")
        if not path.resolve().is_relative_to(root):
            raise ValueError("label cache path escapes dataset")
        if path.exists():
            path.unlink()
            removed.append(relative)
    return removed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="mode",required=True)
    p=sub.add_parser("prepare"); p.add_argument("--plan",type=Path,required=True); p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--development-only",action="store_true",help="explicit train/val prototype; independent test deferred")
    p=sub.add_parser("check"); p.add_argument("--dataset",type=Path,required=True)
    p=sub.add_parser("review"); p.add_argument("--dataset",type=Path,required=True); p.add_argument("--image",required=True)
    p.add_argument("--status",choices=("positive","negative"),required=True); p.add_argument("--note",required=True)
    p=sub.add_parser("relocate"); p.add_argument("--dataset",type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.mode=="prepare": result=prepare(args.plan,args.output_dir,development_only=args.development_only)
        elif args.mode=="check": result=validate(args.dataset)
        elif args.mode=="review":
            mark_review(args.dataset,args.image,args.status,args.note); result=dict(reviewed=args.image)
        else:
            root=args.dataset.resolve()
            if not (root/"dataset.json").is_file(): raise ValueError("not an exported cone dataset")
            metadata=json.loads((root/"dataset.json").read_text())
            available_splits(metadata)
            (root/"data.yaml").write_text(dataset_yaml(root,development_only=metadata.get('development_only',False)))
            result=dict(relocated=str(root))
    except (ValueError,OSError,KeyError) as error:
        parser.exit(2,f"[ERROR] {error}\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__": main()
