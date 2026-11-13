"""Check published commands without UI, network, ROS, camera or GPU startup."""
import argparse
import ast
import hashlib
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_motion_bridge import add_motion_arguments

DOCUMENT = ROOT/'Experimental_results/2026-11-13/body_display_occlusion_live_r01/README.md'


def blocks():
    return re.findall(r'```bash\n(.*?)```', DOCUMENT.read_text(), re.S)


class BodyOcclusionProcedureTests(unittest.TestCase):
    def test_all_shell_blocks_parse_without_execution(self):
        self.assertEqual(len(blocks()), 7)
        for block in blocks():
            with self.subTest(first_line=block.splitlines()[0]):
                subprocess.run(['bash', '-n'], input=block, text=True, check=True, capture_output=True)
        self.assertTrue(all('load' not in shlex.split(b.replace('\\\n', ' ')) for b in blocks()))

    def test_receiver_uses_real_motion_parser_and_new_separate_paths(self):
        command = re.search(r'bash src/start_theta_receive_rtc.sh (.*?)\nfi', blocks()[0], re.S).group(1)
        parser = argparse.ArgumentParser()
        add_motion_arguments(parser)
        args = parser.parse_args(shlex.split(command.replace('\\\n', ' ')))
        self.assertTrue(args.motion_distance)
        self.assertTrue(args.motion_body_display_guard)
        self.assertTrue(args.motion_experimental_rigid_mount)
        self.assertEqual(args.motion_target_roi, [270, 0, 350, 720])
        self.assertEqual(args.motion_comparison_dir, Path('recordings/2026-11-13/body_guard_occlusion_r01'))
        self.assertEqual(args.motion_output_dir, Path('Experimental_results/2026-11-13/driver_body_guard_occlusion_r01'))
        self.assertIsNone(args.motion_withheld_evidence_dir)

    def test_sender_options_exist_in_source_ast_without_importing_sender(self):
        tree = ast.parse((ROOT/'src/webrtc_stream.py').read_text())
        known = {a.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument'
                 for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        command = re.search(r'bash src/start_theta_stream_rtc.sh (.*)', blocks()[1], re.S).group(1)
        tokens = shlex.split(command.replace('\\\n', ' '))
        self.assertTrue(all(token in known for token in tokens if token.startswith('--')))
        self.assertIn('--motion-native', tokens)

    def test_four_file_copy_tar_preserves_sources_and_rejects_repeat(self):
        block = next(b for b in blocks() if 'mkdir recordings/' in b)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            comparison = root/'recordings/2026-11-13/body_guard_occlusion_r01'
            primary = root/'Experimental_results/2026-11-13/driver_body_guard_occlusion_r01'
            comparison.mkdir(parents=True)
            primary.mkdir(parents=True)
            (root/'Downloads').mkdir()
            payload = {comparison/'decoded_synthetic_f000001.png': b'not-a-real-image-fixture',
                       comparison/'decoded_synthetic_f000001.json': b'{"fixture":"pin"}\n',
                       comparison/'comparison_status.json': b'{"fixture":"status"}\n',
                       primary/'motion_engine_summary.json': b'{"fixture":"engine"}\n'}
            for path, blob in payload.items(): path.write_bytes(blob)
            runnable = block.replace('/home/hsr/yopi_ws/RICHO-theta', str(root)).replace('/home/hsr/Downloads', str(root/'Downloads'))
            subprocess.run(['bash', '-c', runnable], check=True, capture_output=True, text=True)
            archive = root/'Downloads/body_guard_occlusion_pin_r01.tar.xz'
            before = hashlib.sha256(archive.read_bytes()).hexdigest()
            with tarfile.open(archive, 'r:xz') as stream:
                files = [item for item in stream.getmembers() if item.isfile()]
                self.assertEqual(len(files), 4)
                self.assertEqual({Path(item.name).name: stream.extractfile(item).read() for item in files},
                                 {path.name: blob for path, blob in payload.items()})
            repeated = subprocess.run(['bash', '-c', runnable], capture_output=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), before)
            self.assertTrue(all(path.read_bytes() == blob for path, blob in payload.items()))


if __name__ == '__main__': unittest.main()
