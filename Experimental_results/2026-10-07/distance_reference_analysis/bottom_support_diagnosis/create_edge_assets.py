"""Graph saved numeric support points; no camera image editing."""
import csv
import hashlib
import json
from pathlib import Path

import cv2

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent


def main():
    normal=HERE/'representative_column_points.csv'
    event=HERE/'edge_event_column_points.csv'
    with normal.open(newline='') as f:
        a=[r for r in csv.DictReader(f) if r['condition']=='z1p10']
    with event.open(newline='') as f:
        b=list(csv.DictReader(f))
    if len({r['frame'] for r in a})!=1 or len({r['frame'] for r in b})!=1:
        raise ValueError('one comparison frame per group required')
    fig,axes=plt.subplots(1,2,figsize=(11,4.5))
    for rows,color in ((a,'tab:blue'),(b,'tab:orange')):
        xs=[float(r['pixel_x']) for r in rows]
        axes[0].plot(xs,[float(r['pixel_y']) for r in rows],'.-',color=color,label='frame '+rows[0]['frame'])
        axes[1].plot(xs,[float(r['z_m']) for r in rows],'.-',color=color,label='frame '+rows[0]['frame'])
    axes[0].invert_yaxis()
    axes[0].set(ylabel='Selected bottom y (px), downwards',title='Right-edge mask support changes')
    axes[1].axhline(1.1,color='red',linestyle='--',label='Reported Z = 1.10 m')
    axes[1].set(ylabel='Projected Z (m)',title='One high-distance point is not a correct median')
    for ax in axes:
        ax.set_xlabel('Raw image column x (px)')
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
    fig.suptitle('Frozen mask / geometry; selected edge example is diagnostic, not blind ground truth',fontsize=10)
    fig.tight_layout();fig.savefig(HERE/'right_edge_support_comparison.png',dpi=150);plt.close(fig)
    manifest=HERE.parents[1]/'report_assets/distance_reference_z1p10_right_edge_export_manifest.csv'
    with manifest.open(newline='') as f:
        raw=list(csv.DictReader(f))
    if len(raw)!=1 or int(raw[0]['frame_one_based'])!=int(b[0]['frame']):
        raise ValueError('raw asset not the selected edge frame')
    if raw[0]['decoded_bgr_pixels_sha256']!=b[0]['decoded_bgr_pixels_sha256']:
        raise ValueError('raw pixels not equal to selected diagnostic frame')
    raw_path=manifest.parent/Path(raw[0]['raw_png']).name
    image=cv2.imread(str(raw_path))
    if image is None or image.shape!=(720,1280,3) or hashlib.sha256(image.tobytes()).hexdigest()!=b[0]['decoded_bgr_pixels_sha256']:
        raise ValueError('saved PNG pixels changed')
    inputs=(normal,event,manifest,raw_path,Path(__file__))
    (HERE/'edge_assets_verification.json').write_text(json.dumps(dict(
        decision='PASS_NUMERIC_GRAPH_AND_RAW_SOURCE_JOIN',
        inputs_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        raw_frame=int(b[0]['frame']),raw_pixels_match=True,camera_image_edited=False),indent=2)+'\n')


if __name__=='__main__':
    main()
