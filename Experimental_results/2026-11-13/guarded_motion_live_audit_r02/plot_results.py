"""Plot scalar paired-log values only; never edits camera/screencast images."""
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE=Path(__file__).resolve().parent
INPUT=BASE/'results_r01/screen_window.csv'
rows=list(csv.DictReader(INPUT.open()))
start=float(rows[0]['source_time_sec'])
x=[float(r['source_time_sec'])-start for r in rows]
main=[float(r['main_range_m']) if r['main_available']=='True' else float('nan') for r in rows]
comparison=[float(r['comparison_range_m']) if r['comparison_available']=='True' else float('nan') for r in rows]
held=[i for i,r in enumerate(rows) if r['main_available']=='True' and r['comparison_reason']=='possible_self_body_occlusion']
fig,ax=plt.subplots(figsize=(10,4.5))
ax.plot(x,main,color='#808080',linewidth=1.5,label='Main logged diagnostic range')
ax.plot(x,comparison,color='#087f8c',linewidth=1.8,label='Separate comparison: available')
ax.scatter([x[i] for i in held],[main[i] for i in held],color='#d06418',s=8,
    label='Main numeric, comparison withheld: possible body occlusion',zorder=3)
ax.set(xlabel='Seconds from logged source frame 44063 (approximately screencast time)',
    ylabel='Diagnostic horizontal range [m]',
    title='2026-11-13 motion r02: recorded screen scope only; no distance ground truth')
ax.grid(alpha=.25);ax.legend(loc='upper center',fontsize=8)
fig.tight_layout()
for ext in ('png','svg'):fig.savefig(BASE/'results_r01'/('screen_range_comparison.'+ext),dpi=150)
plt.close(fig)
report=dict(source_csv_sha256=hashlib.sha256(INPUT.read_bytes()).hexdigest(),
    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    physical_metric_verified=False,camera_images_modified=False)
(BASE/'results_r01/plot_provenance.json').write_text(json.dumps(report,indent=2)+'\n')
