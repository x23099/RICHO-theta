"""Validate the published repin submittal script using dummy bytes only."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
DOCUMENT=ROOT/'Experimental_results/2026-11-13/body_display_reference_occlusion_r01/README.md'


class RepinSubmissionTests(unittest.TestCase):
    def fixture(self,root,reason='comparison_pin_requested'):
        base=root/'recordings/2026-11-13/body_guard_occlusion_r01';base.mkdir(parents=True)
        pin=dict(session='24e1146277d043fa8c01d36e2ebe0651',frame=2000,image_file='decoded_current_f002000.png')
        status=dict(state='pinned',writer_done=False,error=None,pin=pin,latest=dict(reason=reason))
        payload={'comparison_status.json':json.dumps(status).encode(),pin['image_file']:b'current dummy image bytes',
            'decoded_current_f002000.json':json.dumps(pin).encode()}
        for name,blob in payload.items():(base/name).write_bytes(blob)
        (base/'decoded_old_f001677.png').write_bytes(b'old must not be submitted')
        primary=root/'Experimental_results/2026-11-13/driver_body_guard_occlusion_r01';primary.mkdir(parents=True)
        engine=b'{"fixture":"engine"}'
        (primary/'motion_engine_summary.json').write_bytes(engine)
        (root/'Downloads').mkdir()
        payload['motion_engine_summary.json']=engine
        return base,payload

    def run_script(self,root):
        text=DOCUMENT.read_text()
        code=re.search(r"<<'PY'\n(.*?)\nPY",text,re.S).group(1)
        code=code.replace('/home/hsr/Downloads',str(root/'Downloads'))
        return subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True,text=True)

    def test_latest_pin_only_four_unchanged_payloads_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base,payload=self.fixture(root)
            done=self.run_script(root);self.assertEqual(done.returncode,0,done.stderr)
            output=root/'Downloads/body_guard_occlusion_repin_r01.tar.xz';before=output.read_bytes()
            with tarfile.open(output,'r:xz') as archive:
                items=archive.getmembers();self.assertEqual(len(items),4)
                self.assertEqual({Path(item.name).name:archive.extractfile(item).read() for item in items},payload)
            self.assertEqual((base/'decoded_old_f001677.png').read_bytes(),b'old must not be submitted')
            repeated=self.run_script(root);self.assertNotEqual(repeated.returncode,0)
            self.assertEqual(output.read_bytes(),before)

    def test_gap_refused_before_archive_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);self.fixture(root,'comparison_input_gap')
            result=self.run_script(root);self.assertNotEqual(result.returncode,0)
            self.assertIn('pin continuity uncertain',result.stderr)
            self.assertFalse((root/'Downloads/body_guard_occlusion_repin_r01.tar.xz').exists())

    def test_document_shell_blocks_parse_without_hardware_execution(self):
        blocks=re.findall(r'```bash\n(.*?)```',DOCUMENT.read_text(),re.S)
        self.assertEqual(len(blocks),3)
        for block in blocks:
            subprocess.run(['bash','-n'],input=block,text=True,check=True,capture_output=True)


if __name__=='__main__':unittest.main()
