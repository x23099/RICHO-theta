"""New-files-only transfer patch; no staging, commit, push or runtime changes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[3]
PREFIX='Experimental_results/2026-11-11/guarded_cuda_replay_r01/'
PATHS=[PREFIX+name for name in ('implementation_plan.md','cuda_replay.py','check.py','README.md','make_patch.py')]
PATHS.append('tests/test_guarded_cuda_replay.py')


def git(*args,cwd=ROOT,data=None):
    return subprocess.run(['git',*args],cwd=cwd,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-prefix',type=Path,required=True)
    args=parser.parse_args();prefix=args.output_prefix.resolve()
    if ROOT/'recordings' not in prefix.parents:raise ValueError('recordings output prefix required')
    patch=Path(str(prefix)+'.patch');manifest=Path(str(prefix)+'.manifest.json')
    if patch.exists() or manifest.exists():raise ValueError('new patch/manifest prefix required')
    payload=b''
    for name in PATHS:
        if git('cat-file','-e','8e5172b:'+name).returncode==0:
            raise ValueError('new files only; no existing GPU runtime replacement')
        diff=git('diff','--no-ext-diff','--no-index','--binary','--','/dev/null',name)
        if diff.returncode!=1:raise RuntimeError(diff.stderr.decode())
        payload+=diff.stdout
    reverse=git('apply','--check','--reverse','--whitespace=error-all','-',data=payload)
    if reverse.returncode:raise RuntimeError(reverse.stderr.decode())
    with tempfile.TemporaryDirectory(prefix='guarded_cuda_patch_') as temp:
        forward=git('apply','--check','--whitespace=error-all','-',cwd=Path(temp),data=payload)
        if forward.returncode:raise RuntimeError(forward.stderr.decode())
    prefix.parent.mkdir(parents=True,exist_ok=True)
    with patch.open('xb') as stream:stream.write(payload)
    report=dict(schema='guarded_cuda_new_files_transfer_v1',patch_file=patch.name,
        patch_sha256=hashlib.sha256(payload).hexdigest(),files=PATHS,
        source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in PATHS},
        prerequisite='GPU cached replay already verified; existing runtime from 8e5172b',
        forward_empty_check=True,reverse_worktree_check=True,
        runtime_files_changed=False,raw_or_models_included=False,commit_or_push_performed=False)
    with manifest.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(patch=str(patch),files=len(PATHS),sha256=report['patch_sha256']),indent=2))


if __name__=='__main__':main()
