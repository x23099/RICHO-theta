"""Generate a scoped working-tree transfer patch WITHOUT commit/push/staging.

Excludes unrelated edits, raw data, models and environments. Checks forward
application against base fixtures and reverse check against current worktree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[3]
BASE='49f5c40'
PREFIX='Experimental_results/2026-11-11/guarded_async_comparison_r01/'
PATHS=['src/driver_guarded_comparison.py','src/manage_guarded_comparison.py',
    'src/cone_guarded_stream_comparison.py','src/driver_motion_bridge.py','src/driver_motion_process.py',
    'tests/test_driver_guarded_comparison.py','tests/test_cone_guarded_stream_comparison.py',
    *[PREFIX+name for name in ('implementation_plan.md','check.py','replay.py','README.md',
                             'live_procedure.md','make_patch.py')]]


def git(*args, cwd=ROOT, data=None):
    return subprocess.run(['git',*args],cwd=cwd,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-prefix',type=Path,required=True)
    args=parser.parse_args()
    prefix=args.output_prefix.resolve()
    if ROOT/'recordings' not in prefix.parents:
        raise ValueError('transfer artifacts belong under recordings/')
    patch=Path(str(prefix)+'.patch');manifest=Path(str(prefix)+'.manifest.json')
    if patch.exists() or manifest.exists():raise ValueError('new patch/manifest prefix required')
    payload=b'';base_files={}
    for name in PATHS:
        old=git('show',BASE+':'+name)
        if old.returncode==0:
            base_files[name]=old.stdout
            diff=git('diff','--no-ext-diff','--binary',BASE,'--',name)
            assert diff.returncode==0,diff.stderr
        else:
            diff=git('diff','--no-ext-diff','--no-index','--binary','--','/dev/null',name)
            assert diff.returncode==1,diff.stderr
        payload+=diff.stdout
    reverse=git('apply','--check','--reverse','--whitespace=error-all','-',data=payload)
    assert reverse.returncode==0,reverse.stderr.decode()
    with tempfile.TemporaryDirectory(prefix='guarded_patch_base_') as temp:
        fixture=Path(temp)
        for name,data in base_files.items():
            target=fixture/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        forward=git('apply','--check','--whitespace=error-all','-',cwd=fixture,data=payload)
        assert forward.returncode==0,forward.stderr.decode()
    prefix.parent.mkdir(parents=True,exist_ok=True)
    with patch.open('xb') as output:output.write(payload)
    report=dict(schema='scoped_worktree_patch_v1',base_commit=git('rev-parse',BASE).stdout.decode().strip(),
        patch_file=patch.name,patch_sha256=hashlib.sha256(payload).hexdigest(),
        forward_base_check=True,reverse_worktree_check=True,files=PATHS,
        source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PATHS},
        unrelated_work_included=False,raw_or_models_included=False,commit_or_push_performed=False)
    with manifest.open('x') as output:json.dump(report,output,indent=2);output.write('\n')
    print(json.dumps(dict(patch=str(patch),sha256=report['patch_sha256'],files=len(PATHS)),indent=2))


if __name__=='__main__':
    main()
