"""Existing native PNGs: paired bbox/manual/color-bottom diagnosis, not a fix."""
from collections import Counter,defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/"Experimental_results/2026-10-15"
PREVIOUS=HERE.parent/"cone_distance_methods_r01"
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(PREVIOUS))
from cone_dataset import read_csv,sha256,write_csv
from cone_observation import ConeGroundProjector
from diagnose_box_contact_calibration import project_pixel
from contact_pixels import colour_bottom

spec=importlib.util.spec_from_file_location("fixed_distance_comparison",PREVIOUS/"analyze.py")
previous=importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


def sample_manifest():
    result=[]
    for dataset,folder in (("static",OLD/"cone_static_distance_r01"),("sequence",OLD/"floor_cone_same_pose_analysis_r01")):
        manifests=[folder/"raw_sample_manifest.csv"]
        if dataset=="sequence":
            manifests += [folder/"raw_boundary_manifest.csv",folder/"occlusion_diagnosis_r01/raw_manifest.csv"]
        for manifest in manifests:
            for row in read_csv(manifest):
                result.append(dict(dataset=dataset,path=str(manifest.parent/row["file"]),
                    manifest=str(manifest),session=row["session"],frame=int(row["frame"]),
                    time_sec=float(row["time_sec"]),png_sha256=row["png_sha256"],
                    decoded_bgr_sha256=row["decoded_bgr_sha256"]))
    keys=[(r["dataset"],r["session"],r["frame"]) for r in result]
    if len(keys)!=41 or len(set(keys))!=41:raise ValueError("all 41 distinct fixed samples required")
    return result


def images_and_pixels(samples,ledger,selected):
    observations=[]
    by_key={(r["dataset"],r["session"],r["frame"]):r for r in ledger}
    for sample in samples:
        path=Path(sample["path"])
        image=cv2.imread(str(path))
        if (sha256(path)!=sample["png_sha256"] or image is None or image.shape!=(720,1280,3)
                or hashlib.sha256(image.tobytes()).hexdigest()!=sample["decoded_bgr_sha256"]):
            raise ValueError("original native source differs from frozen manifest")
        key=sample["dataset"],sample["session"],sample["frame"]
        source=by_key[key]
        candidates=selected[key]
        for v in (20,30,50):
            result=dict(colour_candidate=False,reason="no_candidate" if not candidates else "ambiguous_candidates",
                pixel_x=None,pixel_y=None,contour_area_px=None,contour_width_px=None,contour_height_px=None,
                contour_max_y=None,bbox_y2=None,contour_max_y_minus_bbox_y2_px=None,significant_contours=0,
                floor_contact_verified=False,usable_for_ffb=False)
            bbox_x=bbox_y=None
            if len(candidates)==1:
                box=candidates[0]
                result=colour_bottom(image,box,v)
                bbox_x=(float(box["x1"])+float(box["x2"]))/2
                bbox_y=float(box["y2"])
            observations.append(dict(dataset=sample["dataset"],session=sample["session"],frame=sample["frame"],
                time_sec=sample["time_sec"],condition=source["condition"],reference_x_m=source["reference_x_m"],
                reference_z_m=source["reference_z_m"],file=sample["path"],v_min=v,candidates=len(candidates),
                bbox_pixel_x=bbox_x,bbox_pixel_y=bbox_y,
                colour_minus_bbox_y_px=result["pixel_y"]-bbox_y if result["colour_candidate"] else None,**result))
    return observations


def projected_rows(observations,geometries):
    output=[]
    for source in observations:
        for model,p in geometries.items():
            bbox=project_pixel((source["bbox_pixel_x"],source["bbox_pixel_y"]),p) if source["bbox_pixel_x"] is not None else None
            colour=project_pixel((source["pixel_x"],source["pixel_y"]),p) if source["colour_candidate"] else None
            ref=source["reference_z_m"]
            output.append(dict(**source,model=model,bbox_z_m=bbox[1] if bbox else None,
                bbox_x_m=bbox[0] if bbox else None,colour_z_m=colour[1] if colour else None,
                colour_x_m=colour[0] if colour else None,
                bbox_error_z_m=bbox[1]-ref if bbox and ref is not None else None,
                colour_error_z_m=colour[1]-ref if colour and ref is not None else None))
    return output


def pair_anchors(ledger,selected,geometries,observations):
    static=OLD/"cone_static_distance_r01"
    sequence=OLD/"floor_cone_same_pose_analysis_r01"
    anchors=[]
    for dataset,path in (("static",static/"manual_contact_candidates.csv"),("sequence",sequence/"contact_candidates.csv")):
        for row in read_csv(path):
            if dataset=="sequence" and row["kind"]!="cone":continue
            condition=row["condition"] if dataset=="static" else "cone_"+row["point_id"][1:]
            source=next(r for r in ledger if r["dataset"]==dataset and r["condition"]==condition and r["frame"]==int(row["frame"]))
            anchors.append((row,source))
    floors={r["point_id"]:r for r in read_csv(sequence/"contact_candidates.csv") if r["kind"]=="floor"}
    output=[]
    for anchor,source in anchors:
        key=source["dataset"],source["session"],source["frame"]
        candidates=selected[key]
        if len(candidates)!=1:raise ValueError("unambiguous same-frame paired anchor required")
        b=candidates[0]
        bxy=((float(b["x1"])+float(b["x2"]))/2,float(b["y2"]))
        mxy=float(anchor["pixel_x"]),float(anchor["pixel_y"])
        colour=next(r for r in observations if (r["dataset"],r["session"],r["frame"],r["v_min"])==(*key,30))
        floor=floors[anchor["point_id"]] if source["dataset"]=="sequence" else None
        for model,p in geometries.items():
            bbox=project_pixel(bxy,p)
            manual=project_pixel(mxy,p)
            f=project_pixel((float(floor["pixel_x"]),float(floor["pixel_y"])),p) if floor else None
            c=project_pixel((colour["pixel_x"],colour["pixel_y"]),p) if colour["colour_candidate"] else None
            if bbox is None or manual is None or (floor and f is None):raise ValueError("anchor projection invalid")
            ref=source["reference_z_m"]
            output.append(dict(dataset=source["dataset"],condition=source["condition"],frame=source["frame"],model=model,
                reference_z_m=ref,bbox_pixel_x=bxy[0],bbox_pixel_y=bxy[1],manual_pixel_x=mxy[0],manual_pixel_y=mxy[1],
                bbox_minus_manual_y_px=bxy[1]-mxy[1],
                colour_pixel_x=colour["pixel_x"],colour_pixel_y=colour["pixel_y"],
                colour_minus_manual_y_px=colour["pixel_y"]-mxy[1] if c else None,
                bbox_z_m=bbox[1],manual_z_m=manual[1],colour_z_m=c[1] if c else None,
                floor_z_m=f[1] if f else None,manual_minus_reference_m=manual[1]-ref,
                bbox_minus_manual_m=bbox[1]-manual[1],total_error_m=bbox[1]-ref,
                two_term_sum_m=(manual[1]-ref)+(bbox[1]-manual[1]),
                floor_minus_reference_m=f[1]-ref if f else None,manual_minus_floor_m=manual[1]-f[1] if f else None,
                three_term_sum_m=(f[1]-ref)+(manual[1]-f[1])+(bbox[1]-manual[1]) if f else None,
                floor_relation="same_recording_different_time_uncertain_V_tip" if floor else "not_identifiable_no_same_recording_floor_reference",
                manual_is_physical_gt=False,floor_contact_verified=False,usable_for_ffb=False))
    return output


def summaries(rows):
    groups=defaultdict(list)
    for row in rows:groups[row["dataset"],row["condition"],row["model"],row["v_min"]].append(row)
    output=[]
    for (dataset,condition,model,v),group in sorted(groups.items()):
        def med(field):
            values=[r[field] for r in group if r[field] is not None]
            return float(np.median(values)) if values else None
        output.append(dict(dataset=dataset,condition=condition,model=model,v_min=v,sample_frames=len(group),
            colour_candidates=sum(r["colour_candidate"] for r in group),
            colour_projected=sum(r["colour_z_m"] is not None for r in group),
            bbox_z_median_m=med("bbox_z_m"),colour_z_median_m=med("colour_z_m"),
            colour_minus_bbox_y_median_px=med("colour_minus_bbox_y_px"),
            colour_z_error_median_m=med("colour_error_z_m"),
            rejected_reasons=json.dumps(dict(Counter(r["reason"] for r in group if not r["colour_candidate"]))),
            manual_gt_or_runtime_approval=False,usable_for_ffb=False))
    return output


def plot(anchors,output):
    os.environ.setdefault("MPLCONFIGDIR","/tmp/cone_contact_reuse_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    chosen=[r for r in anchors if r["model"]=="height_only59"]
    x=np.arange(len(chosen))
    fig,axes=plt.subplots(2,1,figsize=(12,7),layout="constrained")
    axes[0].plot(x,[r["bbox_minus_manual_y_px"] for r in chosen],"o-",label="YOLO bottom - prior manual base candidate")
    axes[0].plot(x,[r["colour_minus_manual_y_px"] if r["colour_minus_manual_y_px"] is not None else np.nan for r in chosen],
                 "o-",label="Visible color bottom V>=30 - prior manual candidate")
    axes[0].axhline(0,color="black",lw=.8)
    axes[0].set_ylabel("Y pixel difference [native px]")
    axes[0].set_title("Same source frame: image differences, NOT surveyed physical contact")
    for field,label in (("bbox_z_m","YOLO bbox"),("manual_z_m","Prior manual base candidate"),("colour_z_m","Color contour bottom")):
        axes[1].plot(x,[r[field]-r["reference_z_m"] if r[field] is not None else np.nan for r in chosen],"o-",label=label)
    axes[1].axhline(0,color="black",lw=.8)
    axes[1].set_ylabel("Z - nominal reference [m], fixed h59")
    for ax in axes:
        ax.set_xticks(x,[r["dataset"]+"\n"+r["condition"] for r in chosen],fontsize=8)
        ax.grid(alpha=.3);ax.legend(fontsize=8)
    fig.savefig(output/"same_frame_contact_comparison.png",dpi=150);plt.close(fig)
    chosen=[r for r in anchors if r["dataset"]=="sequence"]
    fig,ax=plt.subplots(figsize=(11,5),layout="constrained")
    x=np.arange(len(chosen))
    for i,(field,label) in enumerate((("floor_minus_reference_m","V-floor candidate - nominal"),
                                    ("manual_minus_floor_m","Manual base - V-floor candidate"),
                                    ("bbox_minus_manual_m","YOLO bbox - manual base"))):
        ax.bar(x+(i-1)*.23,[100*r[field] for r in chosen],.23,label=label)
    ax.plot(x,[100*r["total_error_m"] for r in chosen],"kD",label="Total bbox Z residual")
    ax.set_xticks(x,[r["condition"]+"\n"+r["model"] for r in chosen],fontsize=8)
    ax.axhline(0,color="black",lw=.8);ax.grid(axis="y",alpha=.3);ax.legend(fontsize=8)
    ax.set(ylabel="Signed Z terms [cm]",title="Same recording algebra only; V-tip remains uncertain; NOT causal contribution")
    fig.savefig(output/"same_recording_residual_terms.png",dpi=150);plt.close(fig)


def main():
    output=HERE/"results_r01"
    if output.exists():raise ValueError("new run required; do not overwrite saved results")
    sources,geometries,refs,conditions,phases,hashes=previous.load_inputs()
    scope=ConeGroundProjector(geometries["recorded58"],width=1280,height=720,front_lens="left",confidence_threshold=.5)
    ledger,selected=previous.make_ledger(sources,scope,refs,conditions,phases)
    samples=sample_manifest()
    paths=[Path(__file__),HERE/"method.md",HERE/"contact_pixels.py",
        OLD/"cone_static_distance_r01/manual_contact_candidates.csv",
        OLD/"floor_cone_same_pose_analysis_r01/contact_candidates.csv"]
    paths.extend(Path(r["manifest"]) for r in samples)
    paths.extend(Path(r["path"]) for r in samples)
    hashes.update({str(p):sha256(p) for p in paths})
    observations=images_and_pixels(samples,ledger,selected)
    projected=projected_rows(observations,geometries)
    anchors=pair_anchors(ledger,selected,geometries,observations)
    assert len(observations)==123 and len(projected)==369 and len(anchors)==21
    output.mkdir()
    write_csv(output/"sample_manifest.csv",samples)
    write_csv(output/"pixel_observations.csv",observations)
    write_csv(output/"projected_observations.csv",projected)
    write_csv(output/"condition_summary.csv",summaries(projected))
    write_csv(output/"paired_anchors.csv",anchors)
    plot(anchors,output)
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    report=dict(status="COMPLETED_EXISTING_IMAGE_CONTACT_DIAGNOSIS_NOT_PHYSICAL_CONTACT_OR_CALIBRATION_APPROVAL",
        native_images=len(samples),pixel_observations=len(observations),projection_rows=len(projected),
        same_frame_manual_anchor_rows=len(anchors),primary_v_min=30,thresholds=[20,30,50],
        colour_reader_uses_reference_or_geometry=False,geometry_refitted=False,physical_output=False,
        production_settings_changed=False,source_images_edited=False,usable_for_ffb=False,
        source_sha256=hashes,output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"provenance.json").write_text(json.dumps(report,indent=2)+"\n")
    for row in anchors:
        if row["model"]=="height_only59":
            print(row["dataset"],row["condition"],"bbox-manual pixels",round(row["bbox_minus_manual_y_px"],3),
                "colour-manual pixels",row["colour_minus_manual_y_px"],"bboxZ",round(row["bbox_z_m"],3),
                "manualZ",round(row["manual_z_m"],3),"colourZ",None if row["colour_z_m"] is None else round(row["colour_z_m"],3),flush=True)
    print("Primary V30:",dict(Counter(r["reason"] for r in observations if r["v_min"]==30)))


if __name__=="__main__":main()
