"""Extract selected full-resolution screencast frames, without image edits."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--times',type=float,nargs='+',required=True)
    args=parser.parse_args()
    if args.output_dir.exists():raise ValueError('new frame directory required')
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','frame=best_effort_timestamp_time,width,height','-of','json',str(args.video)]))['frames']
    if not data or any((r['width'],r['height'])!=(1920,1200) for r in data):raise ValueError('native screen dimensions changed')
    chosen={min(range(len(data)),key=lambda n:abs(float(data[n]['best_effort_timestamp_time'])-t)) for t in args.times}
    args.output_dir.mkdir(parents=True)
    select='+'.join(f'eq(n,{n})' for n in sorted(chosen))
    command=['ffmpeg','-v','error','-i',str(args.video),'-vf',f'select={select}',
        '-vsync','vfr',str(args.output_dir/'screen_%03d.png')]
    # ffmpeg filter syntax requires escaped commas within expressions.
    command[command.index('-vf')+1]='select='+select.replace(',',r'\,')
    subprocess.run(command,check=True)
    records=[]
    for i,n in enumerate(sorted(chosen),1):
        path=args.output_dir/f'screen_{i:03d}.png'
        records.append(dict(file=path.name,video_frame_index=n,pts_sec=float(data[n]['best_effort_timestamp_time']),
            width=1920,height=1200,png_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    with (args.output_dir/'frames.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    report=dict(video=str(args.video),video_sha256=hashlib.sha256(args.video.read_bytes()).hexdigest(),
        requested_times=args.times,command=command,full_native_resolution=True,image_modified=False,frames=records)
    (args.output_dir/'provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(records,indent=2))


if __name__=='__main__':main()
