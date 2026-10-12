#!/usr/bin/env python3
"""Local GUI cone annotation. Draw only on screen; save labels, never images."""
import argparse
import json
import math
from pathlib import Path

import cv2

from cone_dataset import label_path, mark_review, parse_label, read_csv, sha256, verify_image


def import_visual_reviews(root, csv_path):
    """Import explicit visual reviews, never infer cones from colour or filenames.

    One CSV row per reviewed image: image,status,boxes_xyxy_json,note.
    Coordinates are pixels in the untouched whole frame. Validate the entire
    batch before writing; identical reruns resume, differing labels are refused.
    This imports annotations, not an independent human quality approval.
    """
    root = Path(root).resolve()
    metadata = json.loads((root / "dataset.json").read_text())
    if metadata.get("schema_version") != 1 or metadata.get("classes") != ["traffic_cone"]:
        raise ValueError("unsupported dataset schema/classes")
    if sha256(root / "manifest.csv") != metadata["manifest_sha256"]:
        raise ValueError("manifest changed since export")
    manifest_rows = read_csv(root / "manifest.csv")
    manifest = {r["image"]: r for r in manifest_rows}
    review_rows = read_csv(root / "reviews.csv")
    reviews = {r["image"]: r for r in review_rows}
    if (len(manifest) != len(manifest_rows) or len(reviews) != len(review_rows)
            or set(manifest) != set(reviews)):
        raise ValueError("review table differs from manifest")
    rows = read_csv(csv_path)
    if not rows or any(set(("image", "status", "boxes_xyxy_json", "note")) - set(r) for r in rows):
        raise ValueError("nonempty explicit visual review CSV required")
    staged, seen = [], set()
    for row in rows:
        name, status, note = row["image"], row["status"], row["note"]
        if name in seen or name not in manifest:
            raise ValueError("duplicate or unknown annotation image")
        seen.add(name)
        if status not in ("positive", "negative") or not note.strip():
            raise ValueError("explicit positive/negative review and note required")
        boxes = json.loads(row["boxes_xyxy_json"])
        if not isinstance(boxes, list) or bool(boxes) != (status == "positive"):
            raise ValueError("boxes and positive/negative review disagree")
        frame = verify_image(root, manifest[name])
        normalized = []
        for box in boxes:
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
                raise ValueError("finite numeric pixel xyxy boxes required")
            x1, y1, x2, y2 = box
            normalized.append(normalized_box((x1, y1, x2-x1, y2-y1), frame.shape[1], frame.shape[0]))
        content = "".join("0 " + " ".join(format(v, '.10f') for v in b) + "\n" for b in normalized)
        path = label_path(root, name)
        if path.is_symlink():
            raise ValueError("label symlinks forbidden")
        if path.exists() and path.read_text() != content:
            raise ValueError("existing label differs; no overwrite")
        old = reviews[name]
        if old["status"] != "pending" and (old["status"] != status or old["note"] != note
                or not path.exists() or old["label_sha256"] != sha256(path)):
            raise ValueError("existing review differs; no overwrite")
        staged.append((name, status, note, path, content))
    for name, status, note, path, content in staged:
        if not path.exists():
            with path.open("x") as stream:
                stream.write(content)
        mark_review(root, name, status, note)
    return {"imported_images": len(staged), "boxes": sum(len(json.loads(r["boxes_xyxy_json"])) for r in rows),
            "remaining_pending": sum(r["status"] == "pending" for r in read_csv(root / "reviews.csv")),
            "source_csv_sha256": sha256(csv_path), "independent_human_review_performed": False}


def normalized_box(rectangle,width,height):
    x,y,w,h=map(float,rectangle)
    if (not all(math.isfinite(v) for v in (x,y,w,h,width,height)) or width<=0 or height<=0
            or w<=0 or h<=0 or x<0 or y<0 or x+w>width or y+h>height):
        raise ValueError("positive box inside whole raw frame required")
    return ((x+w/2)/width,(y+h/2)/height,w/width,h/height)


def label_preview(frame,boxes):
    """Screen-only copy. The saved raw image and caller's pixels stay intact."""
    preview=frame.copy()
    height,width=frame.shape[:2]
    for x,y,w,h in boxes:
        a=(round((x-w/2)*width),round((y-h/2)*height))
        b=(round((x+w/2)*width),round((y+h/2)*height))
        cv2.rectangle(preview,a,b,(0,255,0),2)
    return preview


def wait_choice(allowed):
    while True:
        key=cv2.waitKey(0)&0xff
        if 65<=key<=90: key+=32
        if key in allowed: return key


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--split",choices=("train","val","test"))
    parser.add_argument("--import-csv", type=Path, help="Import explicit full-frame visual reviews without GUI")
    parser.add_argument("--review-existing", action="store_true", help="Also display existing labels for independent human review")
    args=parser.parse_args()
    root=args.dataset.resolve()
    if args.import_csv:
        if args.split or args.review_existing:
            parser.error("--split/--review-existing and --import-csv cannot be combined")
        try:
            print(json.dumps(import_visual_reviews(root, args.import_csv), indent=2))
        except (ValueError, OSError, KeyError) as exc:
            parser.exit(2, f"Annotation import refused: {exc}\n")
        return
    reviews={r["image"]:r for r in read_csv(root/"reviews.csv")}
    pending=[r for r in read_csv(root/"manifest.csv") if (args.review_existing or reviews[r["image"]]["status"]=="pending")
             and (args.split is None or r["split"]==args.split)]
    title="Cone annotation: P=boxes N=no cone S=skip Q=quit"
    try:
        for index,row in enumerate(pending,1):
            frame=verify_image(root,row)
            print(f"[{index}/{len(pending)}] {row['image']}",flush=True)
            cv2.imshow(title,frame)
            key=wait_choice({ord('p'),ord('n'),ord('s'),ord('q'),27})
            if key in (ord('q'),27): break
            if key==ord('s'): continue
            path=label_path(root,row["image"])
            if key==ord('n'):
                print("All visible cones in BOTH lenses must be absent. Y=confirm negative; S/Esc=skip",flush=True)
                if wait_choice({ord('y'),ord('s'),27}) != ord('y'): continue
                mark_review(root,row["image"],"negative","human full-frame review: no visible traffic cone")
            elif key==ord('p'):
                if path.exists():
                    boxes=parse_label(path)
                    cv2.imshow(title,label_preview(frame,boxes))
                    print("Existing label found. Y=accept displayed existing boxes; S/Esc=skip (no overwrite)",flush=True)
                    if wait_choice({ord('y'),ord('s'),27}) != ord('y'): continue
                else:
                    print("Select ALL cones including base, in both lenses. Enter/Space=next box, Esc=finish selection.",flush=True)
                    rectangles=cv2.selectROIs(title,frame,showCrosshair=True,fromCenter=False)
                    if len(rectangles)==0: continue  # never turn cancel into a negative
                    boxes=[normalized_box(r,frame.shape[1],frame.shape[0]) for r in rectangles]
                    print("Y=confirm all visible cones labelled; S/Esc=skip",flush=True)
                    if wait_choice({ord('y'),ord('s'),27}) != ord('y'): continue
                    path.write_text("".join("0 "+" ".join(format(v,'.10f') for v in box)+"\n" for box in boxes))
                mark_review(root,row["image"],"positive","human full-frame review: all visible cone boxes annotated")
        print("Labels/reviews saved. Raw PNG files were not edited.")
    finally:
        cv2.destroyAllWindows()


if __name__=="__main__": main()
