"""Audit the two-file GPU result against the locally verified recording result.

No remote metadata path is opened. Inputs are read-only; output must be new.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def normalized(summary, key, repo):
    """Use explicit role roots, rejecting duplicates and unexpected path layouts."""
    roots = [(PurePosixPath(summary['input_dir']), 'source_log'),
             (PurePosixPath(summary['evidence_dir']), 'evidence'),
             (PurePosixPath(repo) / 'src', 'implementation'),
             (PurePosixPath(repo) / 'Experimental_results/2026-11-10/'
              'self_body_boundary_shadow_r01', 'reference')]
    result = {}
    for name, digest in summary[key].items():
        path = PurePosixPath(name)
        assert path.is_absolute() and '..' not in path.parts, name
        matches = [(role, path.relative_to(root)) for root, role in roots
                   if path.is_relative_to(root)]
        assert len(matches) == 1, name
        role, relative = matches[0]
        assert len(relative.parts) == 1, name
        identity = role + '/' + str(relative)
        assert identity not in result, identity
        result[identity] = digest
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--intake-dir', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    baseline_dir = repo / ('Experimental_results/2026-11-10/'
                           'guarded_comparison_log_r01/recorded_run_r01')
    prefix = 'guarded_comparison_171250_r01'
    names = ['comparison_summary.json', 'comparison_frames.jsonl']
    with tarfile.open(args.archive, 'r:xz') as archive:
        members = archive.getmembers()
        assert len(members) == 3
        assert {m.name.rstrip('/') for m in members} == {
            prefix, *(prefix + '/' + name for name in names)}
        payloads = {}
        for member in members:
            assert not member.issym() and not member.islnk()
            if member.name.rstrip('/') == prefix:
                assert member.isdir()
            else:
                assert member.isfile() and 0 < member.size <= 2 * 1024 * 1024
                payloads[PurePosixPath(member.name).name] = archive.extractfile(member).read()
    submitted = json.loads(payloads[names[0]])
    baseline = json.loads((baseline_dir / names[0]).read_bytes())
    remote_repo = '/home/hsr/yopi_ws/RICHO-theta'
    maps = {}
    for key in ('input_sha256', 'source_sha256'):
        local_map = normalized(baseline, key, str(repo))
        remote_map = normalized(submitted, key, remote_repo)
        assert local_map == remote_map, key
        # Independently rehash trusted local paths, never submitted remote paths.
        for name, digest in baseline[key].items():
            path = Path(name)
            assert path.resolve().is_relative_to(repo)
            assert file_sha(path) == digest, name
        maps[key] = local_map
    variable = {'input_dir', 'evidence_dir', 'input_sha256', 'source_sha256'}
    assert {k: v for k, v in submitted.items() if k not in variable} == {
        k: v for k, v in baseline.items() if k not in variable}
    frames = payloads[names[1]]
    assert sha(frames) == submitted['comparison_log_sha256']
    assert frames == (baseline_dir / names[1]).read_bytes()
    rows = [json.loads(line) for line in frames.splitlines()]
    assert len(rows) == submitted['rows_committed'] == 8
    assert len({(row['session'], row['frame']) for row in rows}) == 8
    numeric = [row for row in rows if row['comparison_distance_available']]
    assert len(numeric) == 1 and numeric[0]['frame'] == 14922
    assert numeric[0]['comparison_range_m'] == 1.142471541888944
    report = {
        'schema': 'guarded_gpu_result_audit_v1', 'state': 'pass',
        'archive': str(args.archive.resolve()), 'archive_sha256': file_sha(args.archive),
        'audit_source_sha256': file_sha(Path(__file__)),
        'submitted_summary_sha256': sha(payloads[names[0]]),
        'local_summary_sha256': file_sha(baseline_dir / names[0]),
        'comparison_log_sha256': sha(frames),
        'comparison_log_byte_identical': True,
        'summary_identical_except_machine_paths': True,
        'input_files_local_rehashed_and_reported_hashes_matched': len(maps['input_sha256']),
        'source_files_local_rehashed_and_reported_hashes_matched': len(maps['source_sha256']),
        'remote_files_directly_accessed': False,
        'remote_environment_or_live_deployment_verified': False,
        'evidence_verification_identical': True, 'baseline_reproduced_rows': 8,
        'frames': [row['frame'] for row in rows],
        'numeric_comparison': [{'frame': row['frame'], 'range_m': row['comparison_range_m'],
                                'support_pixel': row['comparison_support_pixel']} for row in numeric],
        'posthoc_reference_rows': sum(row['reference_used_posthoc'] for row in rows),
        'input_sha256_by_role': maps['input_sha256'],
        'source_sha256_by_role': maps['source_sha256'],
        'physical_metric_verified': False, 'floor_contact_verified': False,
        'main_display_modified': False, 'controlling_distance': False,
        'usable_for_ffb': False, 'published_to_ros': False,
    }
    assert not args.intake_dir.exists() and not args.output_dir.exists()
    args.intake_dir.mkdir(parents=True)
    for name, data in payloads.items():
        with (args.intake_dir / name).open('xb') as stream:
            stream.write(data)
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / 'audit.json').open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in (
        'state', 'comparison_log_byte_identical', 'baseline_reproduced_rows',
        'input_files_local_rehashed_and_reported_hashes_matched',
        'source_files_local_rehashed_and_reported_hashes_matched', 'numeric_comparison')},
        ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
