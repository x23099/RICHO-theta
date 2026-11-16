"""Check UI-only patch in an isolated fixture and replay no live hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import os

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
TESTS = ('tests/test_driver_motion_presentation.py', 'tests/test_driver_motion_integration.py',
         'tests/test_driver_body_display_guard.py', 'tests/test_driver_motion_bridge.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError('new check output directory required')
    manifest = json.loads((BASE/'patch_manifest.json').read_bytes())
    patch = BASE/'motion_panel_guidance_update_r01.patch'
    assert sha(patch) == manifest['patch_sha256']
    assert all(sha(ROOT/name) == record['after_sha256'] for name, record in manifest['files'].items())
    # The 12 original computation/reference/protocol/bridge sources recorded in
    # the completed live audit must remain byte-identical, not merely equivalent.
    audit = json.loads((BASE.parent/'body_display_range_audit_r01/results_r01/audit.json').read_bytes())
    assert all(sha(ROOT/'src'/name) == digest for name, digest in audit['source_code_sha256'].items())
    with tempfile.TemporaryDirectory(prefix='theta_panel_patch_') as temporary:
        fixture = Path(temporary)
        for name, record in manifest['files'].items():
            if record['before_sha256'] is not None:
                blob = subprocess.check_output(['git', 'show', manifest['base_commit']+':'+name], cwd=ROOT)
                assert hashlib.sha256(blob).hexdigest() == record['before_sha256']
                target = fixture/name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(blob)
        subprocess.run(['git', 'apply', '--check', str(patch)], cwd=fixture, check=True, capture_output=True)
        subprocess.run(['git', 'apply', str(patch)], cwd=fixture, check=True, capture_output=True)
        assert all(sha(fixture/name) == record['after_sha256'] for name, record in manifest['files'].items())
        for name in manifest['files']:
            compile((fixture/name).read_text(), name, 'exec')
        subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=fixture, check=True, capture_output=True)
        repeat = subprocess.run(['git', 'apply', '--check', str(patch)], cwd=fixture, capture_output=True)
        assert repeat.returncode != 0  # already-applied must not be applied again
    command = [sys.executable, '-m', 'pytest', '-q', *TESTS]
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'),
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout+result.stderr)
        raise RuntimeError('presentation/control regression suite failed')
    preview = json.loads((BASE/'previews_r01/manifest.json').read_bytes())
    assert all(sha(BASE/'previews_r01'/item['file']) == item['sha256']
               and item['plain_text'] is True and item['label_height'] >= item['required_height']
               for item in preview['previews'].values())
    assert all(sha(ROOT/name) == digest for name, digest in preview['code_sha256'].items())
    summary = dict(state='pass', tests=TESTS, test_command=command, pytest_output=result.stdout.strip(),
        isolated_patch_forward_and_reverse_check_passed=True,
        repeated_forward_application_rejected=True, protected_live_audit_code_files_unchanged=12,
        patch_sha256=manifest['patch_sha256'], previews_verified=3,
        source_sha256={str(path.relative_to(ROOT)): sha(path) for path in
            (Path(__file__), BASE/'preview.py', BASE/'build_patch.py', ROOT/'src/driver_motion_presentation.py',
             ROOT/'src/webrtc_receive_ui.py', ROOT/'tests/test_driver_motion_presentation.py')},
        preview_is_synthetic_only=True, live_driver_ui_or_gpu_not_verified=True,
        camera_ros_rtc_network_or_vehicle_started=False, gpu_pc_applied=False,
        profile_thresholds_or_control_changed=False)
    output.mkdir(parents=True)
    with (output/'tests.log').open('x') as stream:
        stream.write(result.stdout+result.stderr)
    with (output/'summary.json').open('x') as stream:
        json.dump(summary, stream, indent=2)
        stream.write('\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
