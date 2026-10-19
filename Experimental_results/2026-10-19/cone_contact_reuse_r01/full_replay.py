"""All native frames under unchanged color-bottom diagnostic; no inference/ROS."""
from collections import Counter,defaultdict
import json
from pathlib import Path

import cv2
import numpy as np

import analyze as contact
from contact_pixels import colour_bottom
from cone_dataset import read_csv,sha256,write_csv
from cone_observation import ConeGroundProjector
from diagnose_box_contact_calibration import project_pixel

HERE=Path(__file__).resolve().parent


def original_sessions():
    static=json.loads((contact.OLD/"cone_static_distance_r01/intake_summary.json").read_text())
    sequence=json.loads((contact.OLD/"floor_cone_same_pose_analysis_r01/intake_summary.json").read_text())
    paths=[("static",Path(r["path"])) for r in static["inputs"]]
    paths.append(("sequence",Path(sequence["session"])))
    return paths


def stats(rows,common_only=False):
    groups=defaultdict(list)
    for r in rows:
        if common_only and (r["bbox_z_m"] is None or r["colour_z_m"] is None):continue
        groups[r["dataset"],r["condition"],r["model"],r["v_min"]].append(r)
    output=[]
    for (dataset,condition,model,v),group in sorted(groups.items()):
        ref=group[0]["reference_z_m"]
        result=dict(dataset=dataset,condition=condition,model=model,v_min=v,common_only=common_only,
            frames=len(group),reference_z_m=ref,colour_candidate_frames=sum(r["colour_candidate"] for r in group),
            colour_failures=json.dumps(dict(Counter(r["colour_reason"] for r in group if not r["colour_candidate"]))),
            usable_for_ffb=False)
        for prefix in ("bbox","colour"):
            values=[r[prefix+"_z_m"] for r in group if r[prefix+"_z_m"] is not None]
            difference=np.asarray(values)-ref if values and ref is not None else None
            result.update({prefix+"_projected_frames":len(values),prefix+"_z_median_m":float(np.median(values)) if values else None,
                prefix+"_z_error_median_m":float(np.median(difference)) if difference is not None else None,
                prefix+"_abs_z_error_p95_m":float(np.percentile(abs(difference),95)) if difference is not None else None,
                prefix+"_max_abs_z_error_m":float(max(abs(difference))) if difference is not None else None})
        output.append(result)
    return output


def main():
    output=HERE/"full_replay_r01"
    if output.exists():raise ValueError("new output required; do not overwrite frozen results")
    sources,models,refs,conditions,phases,hashes=contact.previous.load_inputs()
    scope=ConeGroundProjector(models["recorded58"],width=1280,height=720,front_lens="left",confidence_threshold=.5)
    ledger,selected=contact.previous.make_ledger(sources,scope,refs,conditions,phases)
    paths=[Path(__file__),HERE/"full_replay_method.md",HERE/"contact_pixels.py",
        contact.OLD/"cone_static_distance_r01/intake_summary.json",
        contact.OLD/"floor_cone_same_pose_analysis_r01/intake_summary.json"]
    sessions=original_sessions()
    paths.extend(directory/name for _,directory in sessions for name in ("raw.avi","metadata.json","detections.csv"))
    hashes.update({str(p):sha256(p) for p in paths})
    by_session=defaultdict(list)
    for row in ledger:by_session[row["dataset"],row["session"]].append(row)
    pixels,projected=[],[]
    for dataset,directory in sessions:
        frames=by_session[dataset,directory.name]
        original=read_csv(directory/"detections.csv")
        if len(frames)!=len(original):raise ValueError("original and frozen inference frame counts differ")
        cap=cv2.VideoCapture(str(directory/"raw.avi"))
        if not cap.isOpened():raise ValueError("raw video not readable")
        try:
            for frame,raw_row in zip(frames,original):
                ok,image=cap.read()
                if not ok or image.shape!=(720,1280,3):raise ValueError("raw/native frame mismatch")
                if int(raw_row["frame"])!=frame["frame"] or float(raw_row["time_sec"])!=frame["time_sec"]:
                    raise ValueError("raw CSV/time differs from frozen source")
                candidates=selected[dataset,directory.name,frame["frame"]]
                bxy=None if len(candidates)!=1 else ((float(candidates[0]["x1"])+float(candidates[0]["x2"]))/2,float(candidates[0]["y2"]))
                for v in (20,30,50):
                    r=colour_bottom(image,candidates[0],v) if len(candidates)==1 else dict(
                        colour_candidate=False,reason="no_candidate" if not candidates else "ambiguous_candidates",pixel_x=None,pixel_y=None)
                    pixel=dict(dataset=dataset,session=directory.name,frame=frame["frame"],time_sec=frame["time_sec"],
                        condition=frame["condition"],reference_z_m=frame["reference_z_m"],v_min=v,candidates=len(candidates),
                        colour_candidate=r["colour_candidate"],colour_reason=r["reason"],pixel_x=r["pixel_x"],pixel_y=r["pixel_y"],
                        bbox_pixel_x=bxy[0] if bxy else None,bbox_pixel_y=bxy[1] if bxy else None,
                        floor_contact_verified=False,usable_for_ffb=False)
                    pixels.append(pixel)
                    for model,p in models.items():
                        bbox=project_pixel(bxy,p) if bxy else None
                        colour=project_pixel((r["pixel_x"],r["pixel_y"]),p) if r["colour_candidate"] else None
                        projected.append(dict(**pixel,model=model,bbox_z_m=bbox[1] if bbox else None,
                            colour_z_m=colour[1] if colour else None,bbox_x_m=bbox[0] if bbox else None,
                            colour_x_m=colour[0] if colour else None))
            if cap.read()[0]:raise ValueError("extra raw frames beyond source CSV")
        finally:cap.release()
        print(f"Decoded {dataset}/{directory.name}: {len(frames)} frames",flush=True)
    assert len(pixels)==5143*3 and len(projected)==5143*9
    assert all(sha256(Path(p))==digest for p,digest in hashes.items())
    output.mkdir()
    write_csv(output/"pixels.csv",pixels)
    write_csv(output/"positions.csv",projected)
    summary=stats(projected)
    write_csv(output/"summary.csv",summary)
    write_csv(output/"common_frames.csv",stats(projected,True))
    write_csv(output/"occlusion_rows.csv",[r for r in projected if r["dataset"]=="sequence" and 1110<=r["frame"]<=1155])
    (output/"provenance.json").write_text(json.dumps(dict(status="COMPLETED_FULL_COLOUR_DIAGNOSTIC_NOT_RUNTIME_OR_FFB_APPROVAL",
        original_frames=5143,pixel_rows=len(pixels),projection_rows=len(projected),models=models,source_sha256=hashes,
        parameters_fitted=False,thresholds_changed=False,new_inference=False,new_camera_images_saved=False,
        runtime_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()}),indent=2)+"\n")
    for row in summary:
        if row["v_min"]==30 and row["model"]=="height_only59" and row["reference_z_m"] is not None:
            print(row["dataset"],row["condition"],"N",row["frames"],"colour",row["colour_projected_frames"],
                "bboxZ",row["bbox_z_median_m"],"colourZ",row["colour_z_median_m"],
                "colour p95",row["colour_abs_z_error_p95_m"],flush=True)


if __name__=="__main__":main()
