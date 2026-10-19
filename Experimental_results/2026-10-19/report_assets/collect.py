"""Byte-identical copies of existing native PNGs and generated graphs."""
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ITEMS=[
    ("distance_method_comparison.png",ROOT/"Experimental_results/2026-10-19/cone_distance_methods_r01/results_r01/distance_method_comparison.png",
     "numeric_graph",None,None),
    ("occlusion_method_comparison.png",ROOT/"Experimental_results/2026-10-19/cone_distance_methods_r01/results_r01/occlusion_method_comparison.png",
     "numeric_graph",None,None),
    ("raw_paper_reference_f001481.png",ROOT/"Experimental_results/2026-10-15/paper_reference7_r01/raw_samples/paper7_f001481.png",
     "unedited_native1280x720","itiawase2_20261015_183552_599",1481),
    ("raw_cone_occlusion_f001134.png",ROOT/"Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/occlusion_diagnosis_r01/occlusion_raw_f001134.png",
     "unedited_native1280x720","floor_cone_same_pose_r01_20261015_160621_378",1134),
]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (HERE/"manifest.json").exists() or any((HERE/name).exists() for name,*_ in ITEMS):
        raise ValueError("no asset overwrite")
    rows=[]
    for name,source,kind,session,frame in ITEMS:
        before=digest(source)
        target=HERE/name
        shutil.copyfile(source,target)
        assert digest(target)==digest(source)==before
        rows.append(dict(file=name,source=str(source.relative_to(ROOT)),sha256=before,
            kind=kind,session=session,frame=frame,source_image_edited=False))
    (HERE/"manifest.json").write_text(json.dumps(dict(date="2026-10-19",assets=rows,
        note="raw images were recorded on 2026-10-15 and reused unchanged for this day's analysis"),indent=2)+"\n")
    print("Saved 4 byte-identical report assets; original camera PNGs unedited.")


if __name__=="__main__":main()
