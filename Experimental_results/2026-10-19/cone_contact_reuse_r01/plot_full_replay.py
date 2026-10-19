"""Numeric plots of the frozen full-frame results, never image overlays."""
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/"src"))
from cone_dataset import read_csv,sha256


def main():
    output=HERE/"full_plots_r01"
    if output.exists():raise ValueError("no plot overwrite")
    source=HERE/"full_replay_r01"
    rows=read_csv(source/"summary.csv")
    positions=read_csv(source/"occlusion_rows.csv")
    paths=[Path(__file__),source/"summary.csv",source/"occlusion_rows.csv",source/"provenance.json"]
    hashes={str(p):sha256(p) for p in paths}
    os.environ.setdefault("MPLCONFIGDIR","/tmp/cone_contact_reuse_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    models=("recorded58","height_only59","paper_centre2")
    order=[("static",c) for c in ("center_080","center_130","center_200","left_130","right_130")]
    order += [("sequence",c) for c in ("cone_130","cone_200")]
    x=np.arange(len(order))
    fig,axes=plt.subplots(3,1,figsize=(12,9),sharex=True,layout="constrained")
    for ax,model in zip(axes,models):
        group=[next(r for r in rows if (r["dataset"],r["condition"],r["model"],r["v_min"])==(d,c,model,"30")) for d,c in order]
        ax.bar(x-.16,[float(r["bbox_z_error_median_m"]) for r in group],.32,label="YOLO bbox bottom")
        ax.bar(x+.16,[float(r["colour_z_error_median_m"]) for r in group],.32,label="Visible color bottom V>=30")
        ax.axhline(0,color="black",lw=.8);ax.axvline(4.5,color="gray",ls="--");ax.grid(axis="y",alpha=.3)
        ax.set_title(model);ax.set_ylabel("Median Z residual [m]")
    axes[0].legend(fontsize=8)
    axes[-1].set_xticks(x,[d+"\n"+c for d,c in order],fontsize=8)
    fig.suptitle("All 5,143 source frames retained; projection failures reported separately; no calibration refit or FFB approval")
    output.mkdir()
    fig.savefig(output/"all_recordings_contact_comparison.png",dpi=150);plt.close(fig)
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True,layout="constrained")
    for ax,model in zip(axes,models):
        group=[r for r in positions if r["model"]==model and r["v_min"]=="30"]
        for key,label in (("bbox_z_m","YOLO bbox bottom"),("colour_z_m","Color bottom V>=30")):
            ax.plot([int(r["frame"]) for r in group],[float(r[key]) if r[key] else np.nan for r in group],".-",label=label)
        ax.axhline(2,color="black",ls="--",label="Nominal front-edge Z")
        ax.axvspan(1125,1134,color="orange",alpha=.15)
        ax.set_title(model);ax.set_ylabel("Raw Z hypothesis [m]");ax.grid(alpha=.3)
    axes[0].legend(fontsize=8)
    axes[-1].set_xlabel("Original frame; missing or rejected projections remain gaps")
    fig.suptitle("Partial occlusion is NOT solved by a visible color contour")
    fig.savefig(output/"all_frame_occlusion_contact.png",dpi=150);plt.close(fig)
    assert all(sha256(Path(p))==digest for p,digest in hashes.items())
    (output/"provenance.json").write_text(json.dumps(dict(source_sha256=hashes,source_images_edited=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()}),indent=2)+"\n")
    print("Saved two numeric full-replay plots; no camera image edits.")


if __name__=="__main__":main()
