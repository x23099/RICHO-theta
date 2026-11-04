"""Check only the new model/input; reuse hash-matched prior software tests."""
import argparse
import json
from pathlib import Path
import sys

import cv2

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"src"))
from cone_distance_core import DEFAULT_CONFIG,digest,load_config
from cone_fixed_floor_live_load import validate_live_payload
from derive_fixed_floor_live_bundle import checkerboard_reference


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    folder=ROOT/"recordings/2026-11-04/floor_reference_b559e424_r01"
    image=folder/"decoded_b559e4240e364166935f9ede9ac3e7ae_f005755.png"
    before=digest(image);pixels=cv2.imread(str(image))
    gray=cv2.cvtColor(pixels[395:445,280:370],cv2.COLOR_BGR2GRAY)
    corners=[]
    for filename,threshold,epsilon in (("references.json",170,.025),("references_control_t190.json",190,.04)):
        components=cv2.findContours(cv2.inRange(gray,threshold,255),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]
        components=[c for c in components if cv2.contourArea(c)>=200]
        if len(components)!=1:raise ValueError("one explicit board-region contour required")
        c=components[0];observed=cv2.approxPolyDP(c,epsilon*cv2.arcLength(c,True),True)[:,0,:]+[280,395]
        expected=json.loads((HERE/filename).read_text())["frames"][0]["corners_native_xy"]
        if sorted(map(tuple,observed))!=sorted(map(tuple,expected)):raise ValueError("observed/reference polygon mismatch")
        corners.append(dict(file=filename,threshold=threshold,epsilon=epsilon,points=observed.tolist()))
    try:checkerboard_reference(image,20,(280,395,90,50));grid="complete grid detected"
    except ValueError as exc:grid=str(exc)
    model=HERE/"prepared_floor_b559e424_f005755.json";payload=model.read_bytes()
    settings=load_config()[0];session="b559e4240e364166935f9ede9ac3e7ae"
    adapter,evidence=validate_live_payload(payload,settings,digest(DEFAULT_CONFIG),folder,session,5755,"support_completion_shadow")
    rejected={}
    for label,s,f,config in (("old_session","df33e833acdf4e7d8b00d1ec37b7bcae",5755,digest(DEFAULT_CONFIG)),
            ("future_reference",session,5754,digest(DEFAULT_CONFIG)),("wrong_config",session,5755,"0"*64)):
        try:validate_live_payload(payload,settings,config,folder,s,f,"support_completion_shadow");rejected[label]=False
        except ValueError:rejected[label]=True
    prior_path=HERE.parent/"upper_support_live_r01/verification_r01/verification.json"
    prior=json.loads(prior_path.read_text())
    hashes={name:value for name,value in prior["source_sha256"].items() if name.startswith("src/")}
    old=json.loads((HERE.parent/"upper_support_comparator_r01/verification_r01/verification.json").read_text())
    hashes["src/cone_upper_support_candidate.py"]=old["source_sha256"]["src/cone_upper_support_candidate.py"]
    same=all(digest(ROOT/name)==value for name,value in hashes.items())
    checks=dict(corners_match_native_observations=len(corners)==2,
        native_source_unchanged=before==digest(image)=="382ccb5992ab80cfb69290ef057d7010d30e9a6392e434832a70a5613404d76b",
        eight_unselected_models=len(adapter.bundle["models"])==8,
        exact_evidence_frame=[r["frame"] for r in evidence["source_frames"]]==[5755],
        distribution_matches_primary=payload==(HERE/"derived_primary_r01/prepared_floor.json").read_bytes(),
        prior_435_software_success_reused_with_matching_runtime=prior["tests"]==435 and prior["failures"]==prior["errors"]==0 and same,
        **{k+"_rejected":v for k,v in rejected.items()})
    report=dict(status="PASS_MODEL_FILE_CHECKS_NOT_LIVE_OR_METRIC_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks,session=session,evidence_frame=5755,distribution_sha256=digest(model),source_image_sha256=before,
        observed_contour_controls=corners,checkerboard_result=grid,reflection_affects_corner_identity=True,
        physical_metric_verified=False,model_selected=False,live_loading_verified=False,usable_for_ffb=False,
        reused_software_tests=435,tests_rerun_for_unchanged_software=False,
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__).resolve(),HERE/"references.json",
            HERE/"references_control_t190.json",model,prior_path)},matched_runtime_sha256=hashes)
    (args.output_dir/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(dict(status=report["status"],checks=checks,distribution_sha256=report["distribution_sha256"]),indent=2))
    return 0 if all(checks.values()) else 1


if __name__=="__main__":raise SystemExit(main())
