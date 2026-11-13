"""Final report provenance and scoped software tests; no live hardware."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[3]
BASE=Path(__file__).resolve().parent
PYTHON='/home/robo25/theta-env/bin/python3'
TESTS=('test_guarded_current_pin_intake.py','test_body_display_pin_intake.py',
       'test_cone_guarded_stream_comparison.py','test_body_display_occlusion_repin.py',
       'test_body_display_occlusion_procedure.py','test_body_display_occlusion_audit.py',
       'test_body_display_static_live_audit.py','test_driver_body_display_guard.py',
       'test_report_driver_motion_logs.py')


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def require(value,message):
    if not value:raise ValueError(message)


def main():
    out=BASE/'checks_r01';out.mkdir(exist_ok=False)
    manifest=json.loads((BASE/'manifest.json').read_bytes())
    for asset in manifest['assets']:
        require(sha(BASE/asset['file'])==asset['output_sha256']==sha(ROOT/asset['source']),'representative asset changed')
    audit_dir=ROOT/'Experimental_results/2026-11-13/body_display_occlusion_live_audit_r01/results_r01'
    audit=json.loads((audit_dir/'audit.json').read_bytes());screen=json.loads((audit_dir/'screen_audit.json').read_bytes())
    require(audit['state']==screen['state']=='pass','audit not passed')
    require(screen['screen_window']['rows']==1787 and screen['screen_window']['body_numeric_veto']==372
            and screen['screen_window']['display_permitted']==1414,'daily result figures differ')
    for source,digest in {**audit['audit_code_sha256'],**screen['source_sha256']}.items():
        require(sha(ROOT/source)==digest,'audit provenance changed: '+source)
    links=[]
    for document in (ROOT/'Daily_reports/2026-11-13_daily_report.md',ROOT/'Daily_reports/README.md',BASE/'README.md'):
        for target in re.findall(r'\]\(([^)]+)\)',document.read_text()):
            if '://' in target or target.startswith('#'):continue
            path=(document.parent/target.split('#')[0]).resolve()
            require(path.exists(),'broken report link: '+target)
            links.append(dict(document=str(document.relative_to(ROOT)),target=target))
    command=[PYTHON,'-m','pytest','-q',*('tests/'+name for name in TESTS)]
    environment=os.environ.copy();environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    completed=subprocess.run(command,cwd=ROOT,env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (out/'tests.log').write_text(completed.stdout)
    match=re.search(r'(\d+) passed',completed.stdout)
    summary=dict(state='pass' if completed.returncode==0 else 'fail',command=command,
        pytest_disable_plugin_autoload=True,returncode=completed.returncode,
        tests_passed=int(match.group(1)) if match else None,
        representative_assets_verified=len(manifest['assets']),checked_report_links=len(links),
        log_sha256=sha(out/'tests.log'),basis_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in
            (Path(__file__),BASE/'build_assets.py',BASE/'manifest.json',ROOT/'Daily_reports/2026-11-13_daily_report.md',
             *[ROOT/'tests'/name for name in TESTS])},
        live_camera_cuda_ros_or_vehicle_started=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    require(completed.returncode==0,'software tests failed; do not commit as passed')


if __name__=='__main__':main()
