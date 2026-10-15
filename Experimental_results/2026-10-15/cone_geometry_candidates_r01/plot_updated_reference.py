"""Plot re-scored references without touching original plots or predictions."""
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'src'))
from cone_dataset import read_csv,sha256


def main():
    output=HERE/'reference_plot_r01'
    if output.exists():raise ValueError('new plot output required')
    source=HERE/'reference_update_r01/cone_transfer_summary_updated.csv'
    rows=read_csv(source)
    output.mkdir(exist_ok=False)
    os.environ.setdefault('MPLCONFIGDIR',str(HERE/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    indices=np.arange(len(rows))
    for ax,axis in zip(axes,('z','x')):
        for shift,prefix in ((-.18,'baseline'),(.18,'candidate')):
            ax.bar(indices+shift,[100*float(r[prefix+'_error_'+axis+'_median_m']) for r in rows],width=.36,
                label='Recorded58' if prefix=='baseline' else 'Predeclared centre2')
        ax.axhline(0,color='black',lw=.8)
        ax.set(xticks=indices,xticklabels=[r['condition'] for r in rows],ylabel=axis.upper()+' median error [cm]',
            title='Confirmed front/inner edges; X assumes aligned base')
        ax.tick_params(axis='x',rotation=25);ax.grid(axis='y',alpha=.25);ax.legend(fontsize=8)
    fig.savefig(output/'cone_transfer_updated_reference.png',dpi=150);plt.close(fig)
    (output/'provenance.json').write_text(json.dumps(dict(source_sha256={str(source):sha256(source),str(Path(__file__)):sha256(Path(__file__))},
        interpretation='re-scored coordinates only; no model fit or image edits; X assumes axis-aligned square base',
        physical_output=False,graph_sha256=sha256(output/'cone_transfer_updated_reference.png')),indent=2)+'\n')


if __name__=='__main__':main()
