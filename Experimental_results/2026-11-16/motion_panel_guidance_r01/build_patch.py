"""Create a two-file UI-only patch; no git mutation, network or live startup."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
FILES = ('src/webrtc_receive_ui.py', 'src/driver_motion_presentation.py')


def main():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    parts, records = [], {}
    for name in FILES:
        if name == FILES[0]:
            before = subprocess.check_output(['git', 'show', f'{head}:{name}'], cwd=ROOT)
        else:
            result = subprocess.run(['git', 'cat-file', '-e', f'{head}:{name}'], cwd=ROOT, capture_output=True)
            if result.returncode == 0:
                raise ValueError('presentation module already committed; select a new explicit patch base')
            before = b''
        after = (ROOT/name).read_bytes()
        parts.append('diff --git a/'+name+' b/'+name+'\n')
        if not before:
            parts.append('new file mode 100644\n')
        parts.extend(difflib.unified_diff(before.decode().splitlines(keepends=True),
            after.decode().splitlines(keepends=True), fromfile='a/'+name if before else '/dev/null',
            tofile='b/'+name))
        records[name] = dict(before_sha256=hashlib.sha256(before).hexdigest() if before else None,
                            after_sha256=hashlib.sha256(after).hexdigest())
    blob = ''.join(parts).encode()
    target = BASE/'motion_panel_guidance_update_r01.patch'
    manifest_path = BASE/'patch_manifest.json'
    if target.exists() or manifest_path.exists():
        raise ValueError('new patch outputs required')
    with target.open('xb') as stream:
        stream.write(blob)
    manifest = dict(schema='ui_only_motion_guidance_patch_v1', base_commit=head,
        patch_sha256=hashlib.sha256(blob).hexdigest(), files=records,
        bridge_geometry_guard_protocol_profile_or_control_changed=False,
        pushed_or_remote_applied=False)
    with manifest_path.open('x') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(patch=str(target), patch_sha256=manifest['patch_sha256'], files=len(records))))


if __name__ == '__main__':
    main()
