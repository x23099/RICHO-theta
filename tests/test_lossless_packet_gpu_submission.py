"""Untrusted GPU result audit; fixtures are synthetic, never new GPU claims."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'Experimental_results/2026-11-18/lossless_packet_gpu_r01'
SPEC=importlib.util.spec_from_file_location('lossless_submission_test',HERE/'audit_submission.py')
audit=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(audit)
runner,probe=audit.runner,audit.probe


class LosslessSubmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Committed preparation rows, explicitly synthetic detector/CUDA absent.
        rows=[audit.prior.parse(l) for l in (HERE/'verification_r01/synthetic_samples.jsonl').read_bytes().splitlines()]
        for row in rows:row['pytorch_memory_bytes']=dict(peak_allocated=1,peak_reserved=2)
        pairs=[];images=[]
        for case,name in enumerate(runner.NAMES):
            subset=rows[case*20:(case+1)*20];selected=[]
            for index in range(0,20,4):
                a,b,c,d=subset[index:index+4]
                selected.extend((probe.compare_pair(a,b),probe.compare_pair(d,c)))
            pairs.extend(selected)
            images.append(dict(image=name,target_roi=runner.ROIS[name],**runner.summarize(subset,selected)))
        summary=dict(schema='offline_lossless_GPU_summary_v1',state='complete',actual_cuda_inference=True,
            source_code_sha256=runner.manifest_value()['source_code_sha256'],
            run_manifest_sha256=probe.digest(runner.MANIFEST),image_count=4,measured_samples=80,
            warmup_calls_excluded=24,repetitions=5,
            physical_source_capture_or_odometry_reconstructed=False,live_transport_adopted=False,
            source_images_modified=False,images_written=False,**runner.summarize(rows,pairs))
        cls.values={'summary.json':summary,'samples.jsonl':rows,'pairs.jsonl':pairs,
            'per_image_summary.json':images,'run_manifest.json':runner.manifest_value()}

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name)

    def files(self,values=None):
        values=copy.deepcopy(self.values if values is None else values)
        files={name:(b''.join(probe.json_bytes(r) for r in value) if name.endswith('.jsonl')
               else probe.json_bytes(value)) for name,value in values.items() if name!='summary.json'}
        values['summary.json']['result_sha256']={n:probe.sha_bytes(files[n]) for n in runner.RESULTS}
        files['summary.json']=probe.json_bytes(values['summary.json'])
        return files

    def archive(self,files=None,extras=()):
        path=self.directory/'submitted.tar.xz'
        files=self.files() if files is None else files
        with tarfile.open(path,'w:xz') as bundle:
            for name,data in files.items():
                info=tarfile.TarInfo(audit.PREFIX+name);info.size=len(data)
                bundle.addfile(info,io.BytesIO(data))
            for info,data in extras:bundle.addfile(info,io.BytesIO(data))
        return path

    def test_all_eighty_rows_pairs_and_aggregates_reproduce(self):
        wire,files,values=audit.read_archive(self.archive())
        aggregate,images=audit.checked_results(values)
        self.assertGreater(len(wire),0);self.assertEqual(len(files),5)
        self.assertEqual(aggregate['paired_samples'],40);self.assertEqual(len(images),4)
        self.assertEqual(aggregate['pair_counts']['original_withheld_packet_numeric'],0)

    def test_unknown_path_directory_and_link_are_rejected(self):
        for name,kind in ((audit.PREFIX+'instructions.py',tarfile.REGTYPE),
                          ('/absolute.json',tarfile.REGTYPE),('../summary.json',tarfile.REGTYPE),
                          (audit.PREFIX+'x/',tarfile.DIRTYPE),(audit.PREFIX+'samples.jsonl',tarfile.SYMTYPE)):
            info=tarfile.TarInfo(name);info.type=kind;info.size=0
            path=self.archive(extras=((info,b''),))
            with self.subTest(name=name),self.assertRaises(ValueError):audit.read_archive(path)

    def test_duplicate_and_missing_members_rejected(self):
        info=tarfile.TarInfo(audit.PREFIX+'summary.json');info.size=0
        with self.assertRaises(ValueError):audit.read_archive(self.archive(extras=((info,b''),)))
        files=self.files();del files['pairs.jsonl']
        with self.assertRaises(ValueError):audit.read_archive(self.archive(files))

    def test_changed_file_sha_not_accepted(self):
        # Keep valid JSON so this specifically exercises hash checking, not
        # rejection by the earlier strict JSON parser.
        files=self.files();files['pairs.jsonl']=files['pairs.jsonl'].replace(b'"both_numeric": true',b'"both_numeric": false',1)
        with self.assertRaisesRegex(ValueError,'SHA'):audit.read_archive(self.archive(files))

    def test_nonfinite_overflow_and_duplicate_json_rejected(self):
        for data in (b'{"a":NaN}',b'{"a":1e999}',b'{"a":1,"a":2}'):
            with self.assertRaises(ValueError):audit.prior.parse(data)

    def test_manifest_mismatch_rejected_even_with_new_file_hash(self):
        values=copy.deepcopy(self.values)
        values['run_manifest.json']['images'][0]['target_roi']=[270,0,350,720]
        with self.assertRaisesRegex(ValueError,'manifest'):audit.read_archive(self.archive(self.files(values)))

    def test_roi_scope_and_authority_not_hidden_by_aggregates(self):
        for change in ('roi','authority','pixels','sequence','warmup'):
            values=copy.deepcopy(self.values);row=values['samples.jsonl'][0]
            if change=='roi':row['target_roi_native_xyxy']=[270,0,350,720]
            elif change=='authority':row['usable_for_ffb']=True
            elif change=='pixels':row['inference_pixel_sha256']='0'*64
            elif change=='sequence':row['sequence']+=1
            else:values['summary.json']['warmup_calls_excluded']=0
            with self.subTest(change=change),self.assertRaises(ValueError):audit.checked_results(values)

    def test_pair_or_summary_counts_must_recompute(self):
        for target in ('pairs','per_image','aggregate'):
            values=copy.deepcopy(self.values)
            if target=='pairs':values['pairs.jsonl'][0]['reason_changed']=True
            elif target=='per_image':values['per_image_summary.json'][0]['groups']['packet']['samples']=99
            else:values['summary.json']['groups']['packet']['samples']=99
            with self.subTest(target=target),self.assertRaises(ValueError):audit.checked_results(values)

    def test_packet_timing_candidate_and_fragment_counts_checked(self):
        for key,value in (('receiver_stage_ms',-1),('encode_ms',True),('fragment_count',999),
                          ('full_local_pipeline_ms',0),('receiver_first_to_geometry_within_200ms',False)):
            row=copy.deepcopy(self.values['samples.jsonl'][1]);row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):audit.checked_timing(row)
        row=copy.deepcopy(self.values['samples.jsonl'][1]);row['packet_candidate']['sender_media_pts']+=1
        with self.assertRaises(ValueError):audit.checked_timing(row)

    def test_original_cannot_inherit_packet_or_allocator_lie(self):
        for key,value in (('packet_candidate',{}),('pytorch_memory_bytes',None),('sender_prepare_ms',1)):
            row=copy.deepcopy(self.values['samples.jsonl'][0]);row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):audit.checked_timing(row)

    def test_real_known_input_wire_pixels_and_geometry_reproduce(self):
        job=audit.local_jobs()[0]
        settings,camera,_,_=probe.load_config();profile,sha=probe.load_motion_profile(probe.PROFILE,settings)
        row=self.values['samples.jsonl'][1]
        result=audit.reproduced_row(job,row,settings,camera,profile,sha)
        self.assertTrue(result['packet_wire_reproduced']);self.assertTrue(result['measurement_reproduced'])
        self.assertFalse(result['new_GPU_inference_performed'])
        bad=copy.deepcopy(row);bad['packet_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'wire'):audit.reproduced_row(job,bad,settings,camera,profile,sha)
        bad=copy.deepcopy(self.values['samples.jsonl'][0]);bad['measurement']['support_pixel']=[1,1]
        with self.assertRaisesRegex(ValueError,'geometry'):audit.reproduced_row(job,bad,settings,camera,profile,sha)


if __name__=='__main__':unittest.main()
