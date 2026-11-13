"""Bind analyst-reviewed current boundary to a verified native PNG and sidecar."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent));sys.path.insert(0,str(ROOT/'src'))
import intake
from cone_self_body_shadow import checked_reference


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--boundary-csv',type=Path)
    args=parser.parse_args();base=Path(__file__).parent
    args.output_dir.mkdir(parents=True,exist_ok=True)
    target=args.output_dir/'reference.json';record=args.output_dir/'reference_validation.json'
    if target.exists() or record.exists():raise ValueError('new reference output files required')
    audit_path=(args.audit or base/'results_r01/audit.json').resolve()
    boundary_path=(args.boundary_csv or base/'reviewed_boundary.csv').resolve()
    audit=json.loads(audit_path.read_bytes())
    intake.require(audit.get('snapshot_requires_repin') is not True,
        'pin witness continuity not established in submitted status; new explicit pin required')
    payload={name:intake.read_regular(args.input_dir/name,4*1024*1024) for name in audit['supplied_files_sha256']}
    for name,digest in audit['supplied_files_sha256'].items():
        intake.require(intake.sha(payload[name])==digest,'verified pin intake changed')
    pin_names=audit.get('pin_files_sha256',audit['supplied_files_sha256'])
    snapshot=intake.check({name:payload[name] for name in pin_names})
    intake.require(snapshot['snapshot_requires_repin'] is False,
        'pin witness continuity not established in submitted status; new explicit pin required')
    points=[[int(row['x_native']),int(row['y_native'])] for row in csv.DictReader(boundary_path.open())]
    reference=checked_reference(dict(schema='offline_self_body_boundary_v1',session=snapshot['session'],
        image_size=[1280,720],layout='dual_fisheye_front_left_unremapped',source_frame=snapshot['source_frame'],
        source_png_sha256=snapshot['source_png_sha256'],boundary_xy=points,
        source='analyst_read_current_pinned_native_platform_edge_NOT_automatic_detection',
        reading_uncertainty_px=2,independent_physical_measurement=False,cross_session_mount_verified=False,
        live_authorized=False,floor_contact_verified=False))
    reference_blob=(json.dumps(reference,indent=2)+'\n').encode()
    paths=[Path(__file__),base/'intake.py',boundary_path,audit_path]
    report=dict(state='pass',session=snapshot['session'],source_frame=snapshot['source_frame'],
        reference_sha256=intake.sha(reference_blob),pin_png_sha256=snapshot['source_png_sha256'],
        pin_pixels_sha256=snapshot['decoded_bgr_sha256'],boundary_scope_native_x=[points[0][0],points[-1][0]],
        source_sha256={str(p.relative_to(ROOT)):intake.sha(p.read_bytes()) for p in paths},
        submitted_file_sha256=audit['supplied_files_sha256'],
        checked_reference_schema=True,current_png_reviewed=True,
        remote_load_performed=False,remote_witness_still_valid_NOT_verified=True,
        floor_pose_or_metric_verified=False,local_camera_started=False,local_cuda_started=False)
    with target.open('xb') as stream:stream.write(reference_blob)
    with record.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({k:report[k] for k in ('state','session','source_frame','reference_sha256')},indent=2))


if __name__=='__main__':main()
