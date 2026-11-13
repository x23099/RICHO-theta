"""Current three-file pin intake tests; synthetic PNG, no model/live devices."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from test_guarded_static_pin_intake import StaticPinIntakeTests

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('current_pin_intake',
    ROOT/'Experimental_results/2026-11-13/guarded_static_reference_r02/intake.py')
intake=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(intake)


class CurrentPinTests(unittest.TestCase):
    def fixture(self):
        data=StaticPinIntakeTests().fixture();rows=[json.loads(line) for line in data.pop('comparison_frames.jsonl').splitlines()]
        data.pop('request.json');status=json.loads(data['comparison_status.json'])
        status.update(state='pinned',writer_done=False,shutdown_complete=False,latest=rows[-1],
            status_time_sec=1.05,ingress=['a'*32,11,1.03])
        data['comparison_status.json']=json.dumps(status).encode()
        return data

    def test_matching_running_snapshot_has_no_claim_of_current_remote_state(self):
        result=intake.check(self.fixture())
        self.assertEqual(result['state'],'pass');self.assertEqual(result['source_frame'],10)
        self.assertTrue(result['remote_worker_still_running_now_NOT_verified'])
        self.assertTrue(result['witness_survival_until_load_NOT_verified'])

    def test_closed_snapshot_rejected(self):
        data=self.fixture();s=json.loads(data['comparison_status.json']);s.update(state='closed',writer_done=True)
        data['comparison_status.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'running pinned status'):intake.check(data)

    def test_repin_count_is_bounded_and_latest_request_still_required(self):
        for count in (2,8):
            data=self.fixture();s=json.loads(data['comparison_status.json']);s['snapshots_saved']=count
            data['comparison_status.json']=json.dumps(s).encode()
            self.assertEqual(intake.check(data)['snapshot_saved_pin_count'],count)
        s['request_id']+=1;data['comparison_status.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'pin request mismatch'):intake.check(data)

    def test_invalid_pin_counts_rejected(self):
        for count in (0,9,True,2.0):
            data=self.fixture();s=json.loads(data['comparison_status.json']);s['snapshots_saved']=count
            data['comparison_status.json']=json.dumps(s).encode()
            with self.subTest(count=count),self.assertRaisesRegex(ValueError,'pin request mismatch'):intake.check(data)

    def test_wrong_session_latest_rejected(self):
        data=self.fixture();s=json.loads(data['comparison_status.json']);s['latest']['session']='b'*32
        data['comparison_status.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'post-pin same-session'):intake.check(data)

    def test_stale_snapshot_at_copy_time_rejected(self):
        data=self.fixture();s=json.loads(data['comparison_status.json']);s['status_time_sec']=2.
        data['comparison_status.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'fresh snapshot'):intake.check(data)

    def test_extra_mutable_log_rejected(self):
        data=self.fixture();data['comparison_frames.jsonl']=b'{}\n'
        with self.assertRaisesRegex(ValueError,'exactly three'):intake.check(data)

    def test_mismatching_sidecar_rejected(self):
        data=self.fixture();name=next(n for n in data if n.startswith('decoded_') and n.endswith('.json'))
        pin=json.loads(data[name]);pin['request_id']+=1;data[name]=json.dumps(pin).encode()
        with self.assertRaisesRegex(ValueError,'status/sidecar mismatch'):intake.check(data)

    def test_unsafe_tar_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.tar.xz'
            for names,link in ((['1113r02/../a.json'],False),(['1113r02/a.json']*2,False),(['1113r02/a.json'],True)):
                with tarfile.open(path,'w:xz') as archive:
                    for name in names:
                        item=tarfile.TarInfo(name)
                        if link:item.type=tarfile.SYMTYPE;item.linkname='/not_opened'
                        else:item.size=2
                        archive.addfile(item,None if link else io.BytesIO(b'{}'))
                with self.subTest(names=names,link=link),self.assertRaises(ValueError):intake.read_archive(path)

    def test_explicit_archive_prefix_and_default_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.tar.xz'
            with tarfile.open(path,'w:xz') as archive:
                item=tarfile.TarInfo('1113motionr01/a.json');item.size=2
                archive.addfile(item,io.BytesIO(b'{}'))
            self.assertEqual(intake.read_archive(path,'1113motionr01'),{'a.json':b'{}'})
            with self.assertRaisesRegex(ValueError,'unsafe archive name'):intake.read_archive(path)
            with self.assertRaisesRegex(ValueError,'invalid archive prefix'):intake.read_archive(path,'../1113motionr01')


if __name__=='__main__':unittest.main()
