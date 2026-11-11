"""Scoped compact-comparison patch against verified GPU r02 code; no push."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[3]
BASE='882c6ae'
PREFIX='Experimental_results/2026-11-11/guarded_compact_compute_r01/'
PATHS=['src/cone_bbox_boundary_shadow.py','src/cone_self_body_shadow.py',
    'src/cone_guarded_lower_edge_shadow.py','src/cone_guarded_stream_comparison.py',
    'tests/test_guarded_compact_compute.py',
    *[PREFIX+name for name in ('README.md','implementation_plan.md','make_patch.py')]]


def git(*args,cwd=ROOT,data=None):
    return subprocess.run(['git',*args],cwd=cwd,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-prefix',type=Path,required=True)
    args=parser.parse_args();prefix=args.output_prefix.resolve()
    if ROOT/'recordings' not in prefix.parents:raise ValueError('recordings prefix required')
    patch=Path(str(prefix)+'.patch');manifest=Path(str(prefix)+'.manifest.json')
    if patch.exists() or manifest.exists():raise ValueError('new transfer prefix required')
    payload=b'';base_files={}
    for name in PATHS:
        old=git('show',BASE+':'+name)
        if old.returncode==0:
            base_files[name]=old.stdout
            diff=git('diff','--no-ext-diff','--binary',BASE,'--',name)
            if diff.returncode:raise RuntimeError(diff.stderr.decode())
        else:
            diff=git('diff','--no-ext-diff','--binary','--no-index','--','/dev/null',name)
            if diff.returncode!=1:raise RuntimeError(diff.stderr.decode())
        payload+=diff.stdout
    reverse=git('apply','--check','--reverse','--whitespace=error-all','-',data=payload)
    if reverse.returncode:raise RuntimeError(reverse.stderr.decode())
    with tempfile.TemporaryDirectory(prefix='guarded_compact_base_') as temp:
        fixture=Path(temp)
        for name,blob in base_files.items():
            path=fixture/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
        forward=git('apply','--check','--whitespace=error-all','-',cwd=fixture,data=payload)
        if forward.returncode:raise RuntimeError(forward.stderr.decode())
    prefix.parent.mkdir(parents=True,exist_ok=True)
    with patch.open('xb') as stream:stream.write(payload)
    report=dict(schema='guarded_compact_transfer_v1',base_commit=git('rev-parse',BASE).stdout.decode().strip(),
        patch_file=patch.name,patch_sha256=hashlib.sha256(payload).hexdigest(),files=PATHS,
        source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PATHS},
        forward_base_check=True,reverse_worktree_check=True,
        raw_or_models_included=False,unrelated_work_included=False,commit_or_push_performed=False)
    with manifest.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(patch=str(patch),files=len(PATHS),sha256=report['patch_sha256']),indent=2))


if __name__=='__main__':main()
