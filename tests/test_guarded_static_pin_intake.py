"""Static pin archive rejection checks; synthetic pixels, no camera/ROS/CUDA."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('static_pin_intake',
    ROOT/'Experimental_results/2026-11-13/guarded_static_pin_review_r01/intake.py')
intake=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(intake)


class StaticPinIntakeTests(unittest.TestCase):
    def fixture(self):
        image=np.zeros((720,1280,3),np.uint8);png=cv2.imencode('.png',image)[1].tobytes()
        pin=dict(schema='driver_guarded_pin_v1',session='a'*32,frame=10,request_id=1,source_time_sec=1.,
            image_size=[1280,720],image_file='decoded_'+('a'*32)+'_f000010.png',image_modified=False,
            png_sha256=intake.digest(png),decoded_bgr_sha256=intake.digest(image.tobytes()),
            source_log_line_sha256='b'*64,physical_metric_verified=False,floor_contact_verified=False,usable_for_ffb=False)
        rows=[dict(schema='guarded_stream_comparison_v1',session='a'*32,frame=n,source_time_sec=1+(n-10)*.03,
            completed_time_sec=1.01+(n-10)*.03,comparison_service_ms=.01,
            original_distance_available=(n==10),comparison_distance_available=False,comparison_range_m=None,
            reference_scope_verified=False,reference_used_posthoc=False,main_display_modified=False,
            reason='comparison_pin_requested',**{name:False for name in intake.FLAGS}) for n in (10,11)]
        log=b''.join(json.dumps(row).encode()+b'\n' for row in rows)
        status=dict(schema='driver_guarded_comparison_status_v1',state='closed',pin=pin,error=None,
            snapshots_saved=1,request_id=1,request_action='pin',processed=2,offered=3,log_bytes=len(log),
            latest_slot_overwrites=0,tap_busy_drops=0,writer_done=True,shutdown_complete=True,
            main_display_modified=False,source_sha256={n:intake.digest((ROOT/'src'/n).read_bytes()) for n in intake.SOURCES},
            **{name:False for name in intake.FLAGS})
        return {pin['image_file']:png,pin['image_file'][:-4]+'.json':json.dumps(pin).encode(),
            'comparison_status.json':json.dumps(status).encode(),'comparison_frames.jsonl':log,
            'request.json':json.dumps(dict(schema='driver_guarded_request_v1',request_id=1,action='pin')).encode()}

    def test_matching_closed_pin_is_valid_evidence_but_not_active_reference(self):
        data=self.fixture();old=copy.deepcopy(data);result=intake.review(data)
        self.assertEqual(result['state'],'pass');self.assertTrue(result['worker_closed'])
        self.assertFalse(result['old_pin_loadable_after_restart'])
        self.assertFalse(result['exact_main_log_line_sha_independently_verified'])
        self.assertEqual(result['original_numeric_rows_reported'],1)
        self.assertEqual(data,old)

    def test_changed_png_rejected(self):
        data=self.fixture();name=next(n for n in data if n.endswith('.png'));data[name]+=b'changed'
        with self.assertRaisesRegex(ValueError,'PNG/hash mismatch'):intake.review(data)

    def test_changed_sidecar_rejected(self):
        data=self.fixture();name=next(n for n in data if n.startswith('decoded_') and n.endswith('.json'))
        pin=json.loads(data[name]);pin['frame']=12;data[name]=json.dumps(pin).encode()
        with self.assertRaisesRegex(ValueError,'pin/sidecar mismatch'):intake.review(data)

    def test_extra_archive_payload_rejected(self):
        data=self.fixture();data['extra.json']=b'{}'
        with self.assertRaisesRegex(ValueError,'unexpected archive file set'):intake.review(data)

    def test_source_hash_mismatch_rejected(self):
        data=self.fixture();status=json.loads(data['comparison_status.json'])
        status['source_sha256']['cone_motion_range.py']='0'*64
        data['comparison_status.json']=json.dumps(status).encode()
        with self.assertRaisesRegex(ValueError,'local code differs'):intake.review(data)

    def test_incomplete_log_rejected(self):
        data=self.fixture();data['comparison_frames.jsonl']=data['comparison_frames.jsonl'].rstrip(b'\n')
        with self.assertRaisesRegex(ValueError,'incomplete comparison log tail'):intake.review(data)

    def test_pin_and_log_frame_mismatch_rejected(self):
        data=self.fixture();rows=[json.loads(line) for line in data['comparison_frames.jsonl'].splitlines()]
        rows[0]['source_time_sec']=.999
        data['comparison_frames.jsonl']=b''.join(json.dumps(row).encode()+b'\n' for row in rows)
        status=json.loads(data['comparison_status.json']);status['log_bytes']=len(data['comparison_frames.jsonl'])
        data['comparison_status.json']=json.dumps(status).encode()
        with self.assertRaisesRegex(ValueError,'pin frame absent/different'):intake.review(data)

    def test_status_control_authority_rejected(self):
        data=self.fixture();status=json.loads(data['comparison_status.json']);status['usable_for_ffb']=True
        data['comparison_status.json']=json.dumps(status).encode()
        with self.assertRaisesRegex(ValueError,'invalid physical/control authority'):intake.review(data)

    def test_bad_tar_paths_links_and_duplicates_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.tar.xz'
            for names,link in ((['guarded_static_r01/a.json']*2,False),
                (['guarded_static_r01/../a.json'],False),(['guarded_static_r01/a.json'],True)):
                with tarfile.open(path,'w:xz') as archive:
                    for name in names:
                        item=tarfile.TarInfo(name)
                        if link:item.type=tarfile.SYMTYPE;item.linkname='/not_opened'
                        else:item.size=2
                        archive.addfile(item,None if link else io.BytesIO(b'{}'))
                with self.subTest(names=names,link=link),self.assertRaises(ValueError):intake.payloads(path)


if __name__=='__main__':unittest.main()
