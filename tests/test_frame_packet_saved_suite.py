"""Fixed saved-suite orchestration; no CUDA, camera, ROS or driver startup."""
import argparse
from contextlib import ExitStack
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('packet_saved_suite_test', ROOT/
    'Experimental_results/2026-11-18/frame_packet_saved_suite_r01/run_suite.py')
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)


class SavedSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.sources = self.directory/'sources'
        self.sources.mkdir()
        self.paths, self.payloads = [], {}
        for i,name in enumerate(suite.NAMES):
            image = np.full((720,1280,3),i*40,np.uint8)
            data = cv2.imencode('.png',image)[1].tobytes()
            path = self.sources/name
            path.write_bytes(data)
            self.paths.append(path)
            self.payloads[name] = data
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(suite.probe.KNOWN_IMAGES,
            {name:suite.probe.sha_bytes(data) for name,data in self.payloads.items()}))

    def args(self):
        return argparse.Namespace(output_dir=self.directory/'result',archive=self.directory/'result.tar.xz',
            weights=self.directory/'never-opened.pt',input_archive=None,search_root=[self.sources])

    def test_find_all_three_in_fixed_order_ignore_wrong_hash_duplicate(self):
        bad = self.sources/'bad'
        bad.mkdir()
        (bad/suite.NAMES[0]).write_bytes(b'wrong')
        self.assertEqual(suite.find_inputs([self.sources]),self.paths)

    def test_missing_source_or_bounded_search_never_starts_GPU(self):
        self.paths[0].unlink()  # Only this test's generated fixture.
        with patch.object(suite.probe,'main') as gpu,self.assertRaises(FileNotFoundError):
            suite.execute(self.args())
        gpu.assert_not_called()
        with patch.object(suite,'MAX_FILES',1),self.assertRaisesRegex(ValueError,'search limit'):
            suite.find_inputs([self.sources])

    def test_symlink_directory_not_followed(self):
        other = self.directory/'links'
        other.mkdir()
        (other/'link').symlink_to(self.sources,target_is_directory=True)
        with self.assertRaises(FileNotFoundError):
            suite.find_inputs([other])

    def test_pack_roundtrip_keeps_exact_PNG_bytes_and_rejects_overwrite(self):
        archive = self.directory/'input.tar.xz'
        result = suite.prepare_pack(archive,self.paths)
        self.assertEqual(result['image_count'],3)
        target = self.directory/'unpacked'
        target.mkdir()
        paths = suite.unpack_inputs(archive,target)
        self.assertEqual([p.read_bytes() for p in paths],[self.payloads[n] for n in suite.NAMES])
        with self.assertRaises(FileExistsError):
            suite.prepare_pack(archive,self.paths)

    def test_pack_rejects_unknown_member_link_manifest_or_SHA(self):
        for mode in ('path','symlink','manifest','pixels'):
            with self.subTest(mode=mode):
                archive = self.directory/(mode+'.tar.xz')
                contents = {suite.PACK_ROOT+n:d for n,d in self.payloads.items()}
                contents[suite.PACK_ROOT+'manifest.json'] = suite.probe.json_bytes(suite.manifest())
                if mode == 'path':contents['../bad'] = b'bad'
                if mode == 'manifest':contents[suite.PACK_ROOT+'manifest.json'] = b'{}'
                if mode == 'pixels':contents[suite.PACK_ROOT+suite.NAMES[0]] = b'changed'
                with tarfile.open(archive,'w:xz') as bundle:
                    for name,data in contents.items():
                        item = tarfile.TarInfo(name)
                        item.size = len(data)
                        if mode == 'symlink':
                            item.type = tarfile.SYMTYPE
                            item.linkname = '/tmp/not-followed'
                            bundle.addfile(item)
                        else:bundle.addfile(item,io.BytesIO(data))
                target = self.directory/mode
                target.mkdir()
                with self.assertRaises(ValueError):suite.unpack_inputs(archive,target)

    def test_execute_calls_old_runner_once_exact_ROI_no_archive_before_summary(self):
        args = self.args()
        def fake_main(command):
            self.assertEqual(command.count('--image'),3)
            self.assertEqual(command[command.index('--target-roi')+1:command.index('--target-roi')+5],
                             ['270','0','350','720'])
            self.assertNotIn('--archive',command)
            args.output_dir.mkdir()
            suite.probe.save_summary(args.output_dir,dict(state='complete',**suite.probe.FLAGS))
            return 0
        with patch.object(suite.probe,'main',side_effect=fake_main) as gpu, \
                patch.object(suite,'summarize_by_image',return_value=[dict(fixture=True)]), \
                patch('sys.stdout',io.StringIO()):
            self.assertEqual(suite.execute(args),0)
        self.assertEqual(gpu.call_count,1)
        with tarfile.open(args.archive) as bundle:
            self.assertIn('result/per_image_summary.json',bundle.getnames())
        self.assertEqual(json.loads((args.output_dir/'suite_manifest.json').read_bytes())['inputs'],suite.manifest())

    def test_predictor_failure_not_packaged_and_existing_output_preserved(self):
        args = self.args()
        with patch.object(suite.probe,'main',return_value=1):
            self.assertEqual(suite.execute(args),1)
        self.assertFalse(args.archive.exists())
        args.output_dir.mkdir()
        with patch.object(suite.probe,'main') as gpu,self.assertRaises(ValueError):
            suite.execute(args)
        gpu.assert_not_called()

    def test_postprocessing_failure_marks_owned_result_failed_not_complete(self):
        args = self.args()
        def fake_main(command):
            args.output_dir.mkdir()
            suite.probe.save_summary(args.output_dir,dict(state='complete'))
            return 0
        with patch.object(suite.probe,'main',side_effect=fake_main), \
                patch.object(suite,'summarize_by_image',side_effect=ValueError('fixture missing rows')):
            with self.assertRaises(ValueError):suite.execute(args)
        self.assertEqual(json.loads((args.output_dir/'summary.json').read_bytes())['state'],'failed')
        self.assertFalse(args.archive.exists())

    def test_runner_hash_change_is_not_silently_accepted(self):
        with patch.object(suite,'LEGACY_SHA','0'*64),patch.object(suite.probe,'main') as gpu:
            with self.assertRaisesRegex(ValueError,'runner changed'):suite.execute(self.args())
        gpu.assert_not_called()

    def test_per_image_summary_keeps_withheld_cases_and_checks_all_counts(self):
        output = self.directory/'aggregate'
        output.mkdir()
        rows,pairs = [],[]
        # Pure bookkeeping fixtures, not inference results.
        for name in suite.NAMES:
            sha = suite.probe.KNOWN_IMAGES[name]
            rows.extend(dict(source_png_sha256=sha) for _ in range(20))
            pairs.extend(dict(source_png_sha256=sha) for _ in range(10))
        (output/'samples.jsonl').write_bytes(b''.join(suite.probe.json_bytes(r) for r in rows))
        (output/'pairs.jsonl').write_bytes(b''.join(suite.probe.json_bytes(r) for r in pairs))
        with patch.object(suite.probe,'summarize',return_value=dict(numeric=0)) as summarize:
            result = suite.summarize_by_image(output)
        self.assertEqual(len(result),3)
        self.assertEqual(summarize.call_count,3)
        self.assertTrue(all(r['numeric']==0 for r in result))
        (output/'pairs.jsonl').write_bytes(b'{}\n')
        with self.assertRaisesRegex(ValueError,'60 measured'):suite.summarize_by_image(output)


if __name__ == '__main__':unittest.main()
