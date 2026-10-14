"""Plot actual fixed-threshold precision/recall; never annotate camera PNGs."""
import json
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'src'))
from cone_dataset import read_csv,sha256


def main():
    root=Path(__file__).resolve().parent
    target=root/'fixed_threshold_tradeoff.png'
    if target.exists():raise ValueError('new graph version required; no overwrite')
    source=root/'threshold_comparison.csv';rows=read_csv(source)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    for name in ('baseline_35','augmented_36'):
        group=sorted((r for r in rows if r['model']==name),key=lambda r:float(r['confidence_threshold']))
        for index,metric in enumerate(('precision','recall')):
            axes[index].plot([float(r['confidence_threshold']) for r in group],[float(r[metric]) for r in group],marker='o',label=name)
    for index,metric in enumerate(('Precision','Recall')):
        axes[index].set(xlabel='Confidence threshold',ylabel=metric,ylim=(-.02,1.04),title=f'{metric}: fixed IoU matching >=0.5')
        axes[index].axvline(.25,color='gray',linestyle=':',linewidth=1)
        axes[index].grid(alpha=.25);axes[index].legend(fontsize=8)
    fig.suptitle('Same 38 development images / 56 GT boxes; no independent negative test',fontsize=10)
    fig.tight_layout();fig.savefig(target,dpi=150);plt.close(fig)
    (root/'tradeoff_graph_verification.json').write_text(json.dumps(dict(source_sha256=sha256(source),
        graph_sha256=sha256(target),script_sha256=sha256(Path(__file__)),physical_output=False),indent=2)+'\n')


if __name__=='__main__':main()
