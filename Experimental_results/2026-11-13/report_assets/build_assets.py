"""Copy four representative assets byte-for-byte; never edit camera pixels."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[3]
BASE=Path(__file__).resolve().parent
INTAKE=ROOT/'recordings/2026-11-13/body_display_occlusion_full_intake_r01'
AUDIT=ROOT/'Experimental_results/2026-11-13/body_display_occlusion_live_audit_r01'


def sha(blob):return hashlib.sha256(blob).hexdigest()


def main():
    provenance=json.loads((INTAKE/'screen_samples_r01/provenance.json').read_bytes())
    frames={r['file']:r for r in provenance['frames']}
    require=lambda v,msg:None if v else (_ for _ in ()).throw(ValueError(msg))
    require(provenance['video_sha256']==sha((INTAKE/'video/screen.webm').read_bytes()),'video changed')
    selections=(('screen_004.png','body_guard_forward_numeric.png',50114,'1.533'),
                ('screen_008.png','body_guard_occluded_withheld.png',None,None),
                ('screen_012.png','body_guard_reverse_numeric.png',51315,'1.538'))
    payload=[]
    for source,target,displayed_frame,displayed_range in selections:
        path=INTAKE/'screen_samples_r01'/source;blob=path.read_bytes();meta=frames[source]
        require(sha(blob)==meta['png_sha256'] and struct.unpack('>II',blob[16:24])==(1920,1200),'native screen mismatch')
        payload.append((target,blob,dict(source=str(path.relative_to(ROOT)),source_sha256=sha(blob),
            original_video_name='Screencast from 2026年11月13日 20時27分27秒.webm',video_sha256=provenance['video_sha256'],
            pts_sec=meta['pts_sec'],video_frame_index=meta['video_frame_index'],width=1920,height=1200,
            displayed_session='24e11462' if displayed_frame is not None else None,
            displayed_frame=displayed_frame,displayed_range_m=displayed_range,
            image_modified=False,withheld_ui_does_not_show_frame=displayed_frame is None)))
    source=AUDIT/'results_r01/display_gate_timeline.svg';blob=source.read_bytes()
    payload.append(('body_guard_display_timeline.svg',blob,dict(source=str(source.relative_to(ROOT)),
        source_sha256=sha(blob),kind='numeric_graph_NOT_camera_image',
        input_csv=str((AUDIT/'results_r01/screen_window.csv').relative_to(ROOT)),
        input_csv_sha256=sha((AUDIT/'results_r01/screen_window.csv').read_bytes()),
        generator=str((AUDIT/'plot.py').relative_to(ROOT)),generator_sha256=sha((AUDIT/'plot.py').read_bytes()))))
    require(not (BASE/'manifest.json').exists() and all(not (BASE/name).exists() for name,_,_ in payload),'new assets required')
    records=[]
    for name,blob,record in payload:
        with (BASE/name).open('xb') as stream:stream.write(blob)
        records.append(dict(file=name,output_sha256=sha(blob),**record))
    manifest=dict(schema='daily_report_assets_v1',report_date='2026-11-13',assets=records,
        source_code_sha256=sha(Path(__file__).read_bytes()),raw_video_tracked_in_git=False)
    with (BASE/'manifest.json').open('x') as stream:json.dump(manifest,stream,indent=2);stream.write('\n')
    print('Four representative assets copied unchanged; provenance saved.')


if __name__=='__main__':main()
