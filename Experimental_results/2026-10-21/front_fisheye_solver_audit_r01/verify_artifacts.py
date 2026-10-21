"""Verify frozen data/code hashes, resolving exact historical test snapshots."""
from functools import lru_cache
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256


def main():
    output=HERE/'verification.json'
    if output.exists():raise ValueError('no verification overwrite')
    archives=json.loads((HERE/'source_snapshots/manifest.json').read_text())['snapshots']
    mapping={(r['original_path'],r['sha256']):Path(r['archived_path']) for r in archives}
    digest=lru_cache(maxsize=None)(sha256)
    archive_used=set()
    seen=set()
    output_checks=0
    for folder in ('results_r01','angular_results_r01'):
        for path in (HERE/folder).glob('*.json'):
            data=json.loads(path.read_text())
            for original,expected in data.get('source_sha256',{}).items():
                source=Path(original)
                if not source.is_file() or digest(source)!=expected:
                    source=mapping[(original,expected)]
                    archive_used.add(str(source))
                assert digest(source)==expected,(source,expected)
                seen.add((str(source),expected))
            for name,expected in data.get('output_sha256',{}).items():
                assert digest(path.parent/name)==expected
                output_checks+=1
    candidate=json.loads((HERE/'angular_results_r01/angular_diagnostic_candidate.json').read_text())
    original=json.loads((HERE.parent/'front_intrinsics_a4_real_r03/combined_candidate_r01/merged_observations.json').read_text())
    assert candidate['train_indices']==original['train_indices']
    assert candidate['validation_indices']==original['validation_indices']
    assert len(candidate['per_view'])==57
    assert {r['view_index'] for r in candidate['per_view']}==set(range(57))
    assert all(candidate['checks'].values())
    assert not candidate['usable_for_ffb']
    assert not candidate['physical_floor_distance_verified']
    for row in original['selected_views']:
        assert digest(Path(row['source_native_png']))==row['png_sha256']
    record=dict(status='PASS_FROZEN_DIAGNOSTIC_ARTIFACTS_NOT_HARDWARE_APPROVAL',
        verified_unique_sources=len(seen),verified_output_hashes=output_checks,verified_native_pngs=57,
        historical_test_sources_resolved=sorted(archive_used),split_unchanged=True,all_57_views_retained=True,
        angular_quality_screens_passed=True,physical_output=False,usable_for_ffb=False)
    output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
