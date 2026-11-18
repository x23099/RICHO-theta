"""Suite submission integrity + diagnostic bookkeeping, no CUDA/ROS/network."""
import copy
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('suite_submission_audit_test',ROOT/
    'Experimental_results/2026-11-18/frame_packet_saved_suite_r01/audit_submission.py')
audit=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
probe,suite=audit.probe,audit.suite


class SavedSuiteAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)

    def fixture(self,changed=False):
        settings,camera,_,_=probe.load_config()
        profile,sha=probe.load_motion_profile(probe.PROFILE,settings)
        image=np.zeros((720,1280,3),np.uint8);image.flags.writeable=False
        job=dict(path='fixture',image=image,pixel_sha256=probe.sha_bytes(image.tobytes()),png_sha256='f'*64)
        engine=probe.MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,
            target_roi=suite.ROI,observer=probe.observe_upper_completion)
        first=audit.prior.parse(probe.json_bytes(probe.measure(job,'original',1,engine,lambda frame:[])))
        rows,pairs,by_image=[],[],[]
        for case,name in enumerate(suite.NAMES):
            chunk,image_pairs=[],[]
            for i in range(20):
                row=copy.deepcopy(first)
                row.update(source_png_sha256=probe.KNOWN_IMAGES[name],sequence=case*26+i+7,
                    variant=('original','packet','packet','original')[i%4],cycle=i//4,abba_position=i%4)
                if changed and row['variant']=='packet' and case==0:
                    row['measurement'].update(distance_available=True,horizontal_camera_foot_range_m=1.2,
                                               reason='EXPERIMENTAL_FIXED_MOUNT_NOT_VERIFIED_CONTACT')
                chunk.append(row)
                if i%4==3:
                    a,b,c,d=chunk[i-3:i+1]
                    image_pairs.extend((probe.compare_pair(a,b),probe.compare_pair(d,c)))
            rows.extend(chunk);pairs.extend(image_pairs)
            by_image.append(dict(image=name,png_sha256=probe.KNOWN_IMAGES[name],target_roi_native_xyxy=suite.ROI,
                                 **probe.summarize(chunk,image_pairs)))
        summary=probe.summarize(rows,pairs)
        summary.update(schema='offline_packet_recompression_GPU_audit_v1',state='complete',actual_cuda_inference=True,
            image_count=3,measured_samples=60,paired_samples=30,warmup_calls_excluded=18,repetitions=5,
            target_roi_native_xyxy=suite.ROI)
        manifest=dict(schema='packet_saved_suite_GPU_v1',inputs=suite.manifest(),runner_sha256=suite.LEGACY_SHA,
            suite_runner_sha256=probe.digest(audit.HERE/'run_suite.py'),**probe.FLAGS)
        return {'summary.json':summary,'samples.jsonl':rows,'pairs.jsonl':pairs,
                'per_image_summary.json':by_image,'suite_manifest.json':manifest}

    def files(self,values):
        result={n:(b''.join(probe.json_bytes(row) for row in v) if n.endswith('.jsonl') else probe.json_bytes(v))
                for n,v in values.items()}
        summary=copy.deepcopy(values['summary.json'])
        summary['result_sha256']={n:probe.sha_bytes(result[n]) for n in ('samples.jsonl','pairs.jsonl')}
        result['summary.json']=probe.json_bytes(summary)
        manifest=copy.deepcopy(values['suite_manifest.json'])
        manifest['per_image_summary_sha256']=probe.sha_bytes(result['per_image_summary.json'])
        result['suite_manifest.json']=probe.json_bytes(manifest)
        return result

    def archive(self,files,extra=None):
        path=self.directory/'result.tar.xz'
        with tarfile.open(path,'w:xz') as target:
            for name,data in files.items():
                item=tarfile.TarInfo(audit.PREFIX+name);item.size=len(data)
                target.addfile(item,io.BytesIO(data))
            if extra:
                item=tarfile.TarInfo(extra)
                item.type=tarfile.SYMTYPE;item.linkname='/tmp/never-follow'
                target.addfile(item)
        return path

    def test_full_protocol_and_per_image_totals_reproduce(self):
        values=self.fixture()
        result=audit.read_archive(self.archive(self.files(values)))[2]
        aggregate,by_image=audit.checked_results(result)
        self.assertEqual(aggregate['pair_counts']['both_numeric'],0)
        self.assertEqual(len(by_image),3)

    def test_new_numeric_is_not_called_zero_distance_error(self):
        values=self.fixture(changed=True)
        aggregate,by_image=audit.checked_results(values)
        self.assertEqual(aggregate['pair_counts']['original_withheld_packet_numeric'],10)
        self.assertEqual(aggregate['absolute_range_delta_m']['count'],0)
        self.assertIsNone(aggregate['absolute_range_delta_m']['median'])
        self.assertEqual(by_image[0]['groups']['original']['numeric'],0)
        self.assertEqual(by_image[0]['groups']['packet']['numeric'],10)

    def test_per_image_tampering_rejected_even_when_global_total_unchanged(self):
        values=self.fixture()
        values['per_image_summary.json'][0]['groups']['original']['numeric']=1
        with self.assertRaisesRegex(ValueError,'aggregate'):audit.checked_results(values)

    def test_wrong_source_order_or_authority_rejected(self):
        for change in ('sequence','source_png_sha256','usable_for_ffb'):
            values=self.fixture()
            values['samples.jsonl'][0][change]=True if change=='usable_for_ffb' else 'wrong'
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'identity'):
                audit.checked_results(values)

    def test_bad_member_and_corrupt_log_SHA_rejected(self):
        files=self.files(self.fixture())
        with self.assertRaisesRegex(ValueError,'unsafe'):
            audit.read_archive(self.archive(files,'../escape'))
        files['samples.jsonl']+=b'{}\n'
        with self.assertRaisesRegex(ValueError,'SHA mismatch'):
            audit.read_archive(self.archive(files))

    def test_missing_files_and_failed_run_are_not_complete(self):
        values=self.fixture();values['summary.json']['state']='failed'
        with self.assertRaisesRegex(ValueError,'completed CUDA'):
            audit.read_archive(self.archive(self.files(values)))
        files=self.files(self.fixture());files.pop('suite_manifest.json')
        with self.assertRaisesRegex(ValueError,'five suite'):
            audit.read_archive(self.archive(files))

    def test_pixel_box_swap_is_explicit_four_combinations_not_new_inference(self):
        images={v:np.full((720,1280,3),i,np.uint8) for i,v in enumerate(('original','packet'))}
        records={v:dict(raw_detector_boxes=[dict(marker=v)]) for v in images}
        calls=[]
        class FakeEngine:
            def __init__(self,*args,**kwargs):pass
            def measure(self,frame,boxes,now):
                calls.append((int(frame.image[0,0,0]),boxes[0]['marker']))
                return dict(selected_detector_boxes=[],distance_available=False,reason='fixture',
                            horizontal_camera_foot_range_m=None,support_pixel=None)
        with patch.object(probe,'MotionRangeEngine',FakeEngine):
            result=audit.pixel_box_matrix(images,records,None,None,None,None)
        self.assertEqual(calls,[(0,'original'),(0,'packet'),(1,'original'),(1,'packet')])
        self.assertTrue(all(r['result_kind'].startswith('posthoc_') and not r['usable_for_ffb'] for r in result))

    def test_contour_edge_diagnostic_uses_existing_thresholds_without_input_change(self):
        image=np.full((720,1280,3),180,np.uint8)
        box=dict(x1=280.,y1=300.,x2=330.,y2=400.)
        image[310:380,276:310]=[0,0,255]
        image.flags.writeable=False
        before=probe.sha_bytes(image.tobytes())
        value=audit.contour_diagnostic(image,box,'red')
        self.assertIn('left',value['touching_edges'])
        self.assertEqual(value['reason'],'colour_contour_reaches_roi_edge')
        self.assertEqual(before,probe.sha_bytes(image.tobytes()))
        self.assertFalse(image.flags.writeable)


if __name__=='__main__':unittest.main()
