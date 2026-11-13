"""Plot numeric evidence only, never edit camera or screencast images."""
import csv
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE=Path(__file__).resolve().parent
output=BASE/'results_r01'
with (output/'screen_window.csv').open() as stream:rows=list(csv.DictReader(stream))
summary=json.loads((output/'screen_audit.json').read_bytes())
offset=statistics.median(a['pts_sec']*-1+next(float(r['source_time_sec']) for r in rows if r['frame']==a['displayed_frame'])
                         for a in summary['numeric_anchors'])
x=[float(r['source_time_sec'])-offset for r in rows]
raw=[float(r['original_range_m']) if r['original_range_m'] else float('nan') for r in rows]
shown=[float(r['display_range_m']) if r['display_range_m'] else float('nan') for r in rows]
body=[t for t,r in zip(x,rows) if r['display_reason']=='possible_self_body_occlusion']
figure,axis=plt.subplots(figsize=(10,4),layout='constrained')
axis.axvspan(min(body),max(body),color='#df5454',alpha=.14,label='Body-occlusion interval')
axis.plot(x,raw,color='#777777',ls='--',lw=1.3,label='Original raw range (diagnostic)')
axis.plot(x,shown,color='#167a50',lw=1.8,label='Display-permitted range')
axis.scatter([a['pts_sec'] for a in summary['numeric_anchors']],
             [float(a['displayed_range_m']) for a in summary['numeric_anchors']],s=20,color='#222222',zorder=4,label='Read numeric screen samples')
axis.set(xlabel='Screencast time (s), aligned using numeric labels',ylabel='Camera-foot horizontal range (m)',
         title='Forward / reverse: numeric display → WITHHELD → numeric display')
axis.grid(alpha=.25);axis.legend(fontsize=8,loc='lower left');axis.set_ylim(.57,1.65)
target=output/'display_gate_timeline.svg'
if target.exists():raise ValueError('new plot output required')
figure.savefig(target);plt.close(figure)
print(target)
