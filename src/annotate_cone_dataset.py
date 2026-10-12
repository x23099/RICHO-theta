#!/usr/bin/env python3
"""Local GUI cone annotation. Draw only on screen; save labels, never images."""
import argparse
from pathlib import Path

import cv2

from cone_dataset import label_path, mark_review, parse_label, read_csv, verify_image


def normalized_box(rectangle,width,height):
    x,y,w,h=map(float,rectangle)
    if w<=0 or h<=0 or x<0 or y<0 or x+w>width or y+h>height:
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
    args=parser.parse_args()
    root=args.dataset.resolve()
    reviews={r["image"]:r for r in read_csv(root/"reviews.csv")}
    pending=[r for r in read_csv(root/"manifest.csv") if reviews[r["image"]]["status"]=="pending"
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
