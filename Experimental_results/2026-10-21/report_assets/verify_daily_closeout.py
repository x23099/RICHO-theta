"""Read-only check of final diagnostic artifacts and report assets, then save log."""
from functools import lru_cache
import json
from pathlib import Path
import re
import sys

import cv2

HERE=Path(__file__).resolve().parent
DAY=HERE.parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256


def main():
    destination=HERE/'daily_closeout_verification.json'
    if destination.exists():raise ValueError('daily closeout verification already saved')
    digest=lru_cache(maxsize=None)(sha256)
    solver=DAY/'front_fisheye_solver_audit_r01'
    snapshots=json.loads((solver/'source_snapshots/manifest.json').read_text())['snapshots']
    archived={(r['original_path'],r['sha256']):Path(r['archived_path']) for r in snapshots}
    manifests=[solver/'results_r01/summary.json',solver/'angular_results_r01/summary.json',
        solver/'angular_results_r01/angular_diagnostic_candidate.json',
        DAY/'angular_metric_validation_r01/results_r01/summary.json',
        DAY/'angular_metric_validation_r01/plots_r01/manifest.json',DAY/'angular_metric_validation_r01/verification.json',
        DAY/'angular_contact_consistency_r01/results_r01/summary.json',
        DAY/'angular_contact_consistency_r01/plots_and_verification_r01/verification.json',
        DAY/'scene_vertical_gravity_r01/results_r01/summary.json',
        DAY/'scene_vertical_gravity_r01/curve_results_r01/summary.json',
        DAY/'scene_vertical_gravity_r01/plots_and_verification_r01/verification.json',
        DAY/'scene_vertical_gravity_r01/outlier_audit_r01/summary.json']
    source_checks=0;output_checks=0;archive_uses=0
    for manifest in manifests:
        data=json.loads(manifest.read_text())
        for name,expected in data.get('source_sha256',{}).items():
            source=Path(name)
            if not source.is_file() or digest(source)!=expected:
                source=archived[(name,expected)];archive_uses+=1
            assert digest(source)==expected,source
            source_checks+=1
        for name,expected in data.get('output_sha256',{}).items():
            assert digest(manifest.parent/name)==expected,(manifest,name)
            output_checks+=1
    representative=json.loads((HERE/'daily_final_manifest.json').read_text())
    assert len(representative['assets'])==4
    for r in representative['assets']:
        assert digest(Path(r['source']))==r['sha256']==digest(HERE/r['file'])
        if r['kind']=='native_camera':assert cv2.imread(str(HERE/r['file'])).shape==(720,1280,3)
    reports=[ROOT/'Daily_reports/2026-10-21_daily_report.md',HERE/'README.md',ROOT/'Daily_reports/README.md']
    links=0
    for report in reports:
        for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):
            if target.startswith(('http://','https://','#')):continue
            target=target.split('#',1)[0]
            assert (report.parent/target).exists(),(report,target)
            links+=1
    record=dict(status='PASS_DAILY_REPORT_AND_FROZEN_ARTIFACTS',manifests=len(manifests),source_hash_checks=source_checks,
        output_hash_checks=output_checks,historical_source_resolutions=archive_uses,representative_assets=4,
        report_local_links_checked=links,original_images_edited=False,physical_output=False,usable_for_ffb=False,
        source_sha256={str(p):digest(p) for p in reports+[Path(__file__),HERE/'collect_daily_final.py',HERE/'daily_final_manifest.json']})
    destination.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':main()
