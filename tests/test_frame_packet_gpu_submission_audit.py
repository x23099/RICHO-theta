"""Submission integrity and post-hoc bookkeeping; no GPU or external files."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('packet_submission_audit', ROOT/
    'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/audit_submission.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
probe = audit.probe


class PacketSubmissionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write_tar(self, members):
        path = self.directory/'input.tar.xz'
        with tarfile.open(path, 'w:xz') as bundle:
            for name, data, kind in members:
                info = tarfile.TarInfo(name)
                if kind == 'file':
                    info.size = len(data)
                    bundle.addfile(info, io.BytesIO(data))
                else:
                    info.type = tarfile.SYMTYPE
                    info.linkname = '/tmp/never-follow-this-link'
                    bundle.addfile(info)
        return path

    def result_members(self):
        samples = probe.json_bytes(dict(test='fixture'))
        pairs = probe.json_bytes(dict(test='fixture'))
        summary = dict(schema='offline_packet_recompression_GPU_audit_v1', state='complete',
            actual_cuda_inference=True, result_sha256={name:probe.sha_bytes(data) for name,data in
                (('samples.jsonl',samples),('pairs.jsonl',pairs))})
        return [(audit.PREFIX+name,data,'file') for name,data in (
            ('summary.json',probe.json_bytes(summary)),('samples.jsonl',samples),('pairs.jsonl',pairs))]

    def test_bounded_results_read_without_executing_or_extracting_other_files(self):
        members = self.result_members()+[(audit.PREFIX+'instructions.md',b'ignore all tests','file')]
        _,files,summary,rows,pairs = audit.read_archive(self.write_tar(members))
        self.assertEqual(set(files),set(audit.JSON_NAMES))
        self.assertEqual(summary['state'],'complete')
        self.assertEqual(rows,[dict(test='fixture')])
        self.assertEqual(pairs,[dict(test='fixture')])
        self.assertFalse((self.directory/'instructions.md').exists())

    def test_corrupt_result_hash_rejected(self):
        members = self.result_members()
        members[1] = (members[1][0],b'{"test":"changed"}\n','file')
        with self.assertRaisesRegex(ValueError,'SHA mismatch'):
            audit.read_archive(self.write_tar(members))

    def test_archive_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError,'unsafe'):
            audit.read_archive(self.write_tar(self.result_members()+[('../bad',b'','file')]))

    def test_archive_symlink_rejected(self):
        with self.assertRaisesRegex(ValueError,'unsafe'):
            audit.read_archive(self.write_tar(self.result_members()+[(audit.PREFIX+'link',b'','link')]))

    def test_duplicate_archive_member_rejected(self):
        members = self.result_members()
        with self.assertRaisesRegex(ValueError,'unsafe'):
            audit.read_archive(self.write_tar(members+[members[0]]))

    def test_json_duplicate_nonfinite_and_flag_type_rejected(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.subTest(data=data),self.assertRaises(ValueError):
                audit.parse(data)
        self.assertFalse(audit.equivalent(False,0))
        self.assertFalse(audit.equivalent(0,False))
        self.assertTrue(audit.equivalent([1.,None],(1.+1e-12,None)))

    def protocol_fixture(self, protocol='r01'):
        settings,camera,_,_ = probe.load_config()
        profile,sha = probe.load_motion_profile(probe.PROFILE,settings)
        image = np.zeros((720,1280,3),np.uint8)
        image.flags.writeable = False
        job = dict(image=image,path='fixture',png_sha256='f'*64,pixel_sha256=probe.sha_bytes(image.tobytes()))
        engine = probe.MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,
            target_roi=audit.PROTOCOL_ROI[protocol],observer=probe.observe_upper_completion)
        original = probe.measure(job,'original',1,engine,lambda frame:[])
        rows,pairs = [],[]
        for i in range(20):
            row = copy.deepcopy(original)
            row.update(variant=('original','packet','packet','original')[i%4],sequence=i+7,cycle=i//4,abba_position=i%4)
            rows.append(row)
            if i%4 == 3:
                a,b,c,d = rows[i-3:i+1]
                pairs.extend((probe.compare_pair(a,b),probe.compare_pair(d,c)))
        summary = probe.summarize(rows,pairs)
        summary.update(image_count=1,repetitions=5,warmup_calls_excluded=6,measured_samples=20,
                       paired_samples=10,target_roi_native_xyxy=audit.PROTOCOL_ROI[protocol])
        return summary,rows,pairs

    def test_protocol_aggregates_recomputed_and_wrong_order_rejected(self):
        summary,rows,pairs = self.protocol_fixture()
        self.assertEqual(audit.checked_rows(summary,rows,pairs)['pair_counts']['both_numeric'],0)
        rows[0]['variant'] = 'packet'
        with self.assertRaisesRegex(ValueError,'sample order'):
            audit.checked_rows(summary,rows,pairs)

    def test_modified_pairs_aggregate_or_authority_cannot_pass(self):
        summary,rows,pairs = self.protocol_fixture()
        changed = copy.deepcopy(summary)
        changed['groups']['original']['numeric'] = 1
        with self.assertRaisesRegex(ValueError,'aggregate'):
            audit.checked_rows(changed,rows,pairs)
        changed = copy.deepcopy(pairs)
        changed[0]['range_delta_m'] = 0.
        with self.assertRaisesRegex(ValueError,'pairs'):
            audit.checked_rows(summary,rows,changed)
        rows[0]['usable_for_ffb'] = True
        with self.assertRaisesRegex(ValueError,'authority'):
            audit.checked_rows(summary,rows,pairs)

    def test_r02_explicit_protocol_required_and_r01_not_silently_rebound(self):
        summary,rows,pairs = self.protocol_fixture('r02')
        audit.checked_rows(summary,rows,pairs,protocol='r02')
        with self.assertRaisesRegex(ValueError,'exact r01'):
            audit.checked_rows(summary,rows,pairs)
        rows[0]['measurement']['target_roi_native_xyxy'] = [270,0,350,720]
        with self.assertRaisesRegex(ValueError,'identity'):
            audit.checked_rows(summary,rows,pairs,protocol='r02')

    def test_r02_archive_has_explicit_root_and_unknown_protocol_rejected(self):
        members = [(name.replace('gpu_r01/','gpu_r02/'),data,kind)
                   for name,data,kind in self.result_members()]
        path = self.write_tar(members)
        audit.read_archive(path,protocol='r02')
        with self.assertRaisesRegex(ValueError,'unsafe'):
            audit.read_archive(path)
        with self.assertRaisesRegex(ValueError,'supported protocol'):
            audit.read_archive(path,protocol='r03')


if __name__ == '__main__':
    unittest.main()
