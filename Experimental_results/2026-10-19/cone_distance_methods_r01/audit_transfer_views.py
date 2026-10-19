"""Reuse frozen local template checks; no native image or geometry edits."""
import json
from pathlib import Path
import sys

import cv2

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/"Experimental_results/2026-10-15"
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(OLD/"cone_geometry_candidates_r01"))
from cone_dataset import read_csv,sha256,write_csv
from cone_view_consistency import assess_local_view
from view_registration import REGIONS,match_region

PAPER=OLD/"paper_reference7_r01"
REFERENCE=PAPER/"raw_samples/paper7_f001481.png"


def targets():
    result=[("self",REFERENCE)]
    result.extend((f"paper_control_{i}",PAPER/f"raw_samples/paper7_f{i:06d}.png") for i in (247,987,6169,6909))
    result.append(("previous_paper_2m",OLD/"white_paper_visibility_r01/raw_samples/paper_f000200.png"))
    result.extend((f"static_{condition}",OLD/"cone_static_distance_r01/raw_samples"/f"{condition}_f{frame:06d}.png")
        for condition,frame in (("center_080",241),("center_130",217),("center_200",211),("left_130",210),("right_130",211)))
    result.extend((f"sequence_{i}",OLD/"floor_cone_same_pose_analysis_r01/raw_samples"/f"same_pose_f{i:06d}.png")
        for i in (141,563,1265))
    return result


def verify_native_manifest(path):
    for root in (PAPER,OLD/"white_paper_visibility_r01",OLD/"cone_static_distance_r01",OLD/"floor_cone_same_pose_analysis_r01"):
        if not path.is_relative_to(root):continue
        manifests=[root/"raw_sample_manifest.csv"]
        if (root/"raw_boundary_manifest.csv").exists():manifests.append(root/"raw_boundary_manifest.csv")
        matches=[row for manifest in manifests for row in read_csv(manifest) if root/row["file"]==path]
        if len(matches)!=1 or sha256(path)!=matches[0]["png_sha256"]:
            raise ValueError("native PNG not uniquely matched to its frozen manifest")
        return
    raise ValueError("unexpected native source")


def main():
    output=HERE/"view_audit_r01"
    if output.exists():raise ValueError("no result overwrite")
    images=targets()
    assert len(images)==14
    paths=[Path(__file__),HERE/"transfer_view_method.md",ROOT/"src/cone_view_consistency.py",
           OLD/"cone_geometry_candidates_r01/view_registration.py"]+[p for _,p in images]
    hashes={str(p):sha256(p) for p in paths}
    for _,path in images:verify_native_manifest(path)
    reference=cv2.imread(str(REFERENCE),cv2.IMREAD_GRAYSCALE)
    rows,summary=[],[]
    for identity,path in images:
        current=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        matches=[]
        for region in REGIONS:
            try:
                row=dict(case=identity,file=str(path),reference=str(REFERENCE),evaluated=True,
                         **match_region(reference,current,region,margin=20))
            except ValueError as error:
                if str(error)!="insufficient texture for normalized matching":raise
                name,x,y,w,h=region
                row=dict(case=identity,file=str(path),reference=str(REFERENCE),evaluated=False,region=name,
                    x=x,y=y,width=w,height=h,search_margin_px=20,
                    delta_x_current_minus_reference_px=None,delta_y_current_minus_reference_px=None,
                    ncc=None,zero_offset_ncc=None,second_separated_peak=None,separated_peak_margin=None,
                    reverse_ncc=None,reverse_return_error_px=None,reliable_for_local_feature_comparison=False,
                    reason="insufficient_reference_texture_no_offset_inferred")
            matches.append(row)
        rows.extend(matches)
        summary.append(dict(case=identity,total_fixed_regions=len(matches),
            texture_missing_regions=sum(not r["evaluated"] for r in matches),
            **assess_local_view([r for r in matches if r["evaluated"]])))
    assert all(sha256(Path(p))==digest for p,digest in hashes.items())
    output.mkdir()
    write_csv(output/"local_matches.csv",rows)
    write_csv(output/"summary.csv",summary)
    (output/"provenance.json").write_text(json.dumps(dict(status="LOCAL_IMAGE_AUDIT_NOT_PHYSICAL_POSE_OR_CALIBRATION_APPROVAL",
        source_sha256=hashes,regions=[list(r) for r in REGIONS],pairs=len(summary),matches=len(rows),
        margin=20,images_edited=False,geometry_changed=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()}),indent=2)+"\n")
    for row in summary:print(row["case"],row["state"],row["reliable_regions"],row["max_reliable_local_offset_px"])


if __name__=="__main__":main()
