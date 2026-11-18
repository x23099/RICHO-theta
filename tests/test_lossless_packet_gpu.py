"""Preparation only: real PNG/native geometry, synthetic predictor, NOT CUDA."""
import argparse
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('png_gpu_test',ROOT/'Experimental_results/2026-11-18/lossless_packet_gpu_r01/run.py')
runner=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(runner)
probe=runner.probe
BOX=dict(x1=290.,y1=300.,x2=350.,y2=405.,confidence=.95,class_id=0)


class LosslessGPUTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name)
        self.path=self.directory/runner.NAMES[1]
        image=np.full((720,1280,3),180,np.uint8)
        cv2.fillPoly(image,[np.array([[320,310],[298,399],[342,399]],np.int32)],(0,0,255))
        image.flags.writeable=False
        data=cv2.imencode('.png',image)[1].tobytes();self.path.write_bytes(data)
        self.job=dict(image=image,path=str(self.path),png_sha256=probe.sha_bytes(data),pixel_sha256=probe.sha_bytes(image.tobytes()))
        self.settings,self.camera,_,_=probe.load_config()
        self.profile,self.sha=probe.load_motion_profile(probe.PROFILE,self.settings)

    def engine(self,job=None):
        return probe.MotionRangeEngine(self.settings,self.camera,self.profile,self.sha,
            acknowledged=True,target_roi=[270,0,350,720],observer=probe.observe_upper_completion)

    def predictor(self,frame):return [dict(BOX,image=f'{frame.session}:{frame.sequence}')]

    def test_actual_png_pixels_exact_candidate_native_readonly(self):
        image,codec=runner.roundtrip(self.job['image'],1)
        np.testing.assert_array_equal(image,self.job['image'])
        self.assertFalse(image.flags.writeable)
        self.assertFalse(codec['packet_candidate']['local_pair_available'])
        self.assertIsNone(codec['packet_candidate']['odometry_observation'])
        self.assertGreater(codec['encode_ms'],0.)
        self.assertLessEqual(codec['codec_receiver_stage_ms'],200.)
        self.assertEqual(codec['fragmented_bytes'],codec['packet_bytes']+codec['fragment_count']*runner.flow.HEADER.size)

    def test_original_and_png_call_predictor_on_same_pixels(self):
        seen=[]
        def predict(frame):seen.append(probe.sha_bytes(frame.image.tobytes()));return self.predictor(frame)
        original=runner.measure(self.job,'original',1,self.engine(),predict)
        encoded=runner.measure(self.job,'packet',2,self.engine(),predict)
        self.assertEqual(seen,[self.job['pixel_sha256']]*2)
        self.assertTrue(original['measurement']['distance_available'])
        self.assertEqual(original['measurement']['support_pixel'],encoded['measurement']['support_pixel'])
        self.assertEqual(probe.compare_pair(original,encoded)['range_delta_m'],0.)
        self.assertTrue(all(encoded[k] is False for k in probe.FLAGS))
        self.assertEqual(encoded['packet_codec'],'PNG_RGB8_LOSSLESS')
        self.assertGreater(encoded['full_local_pipeline_ms'],encoded['receiver_stage_ms'])

    def test_abba_warmup_excluded_with_exact_pairs(self):
        rows,pairs=runner.benchmark([self.job],self.predictor,self.engine,repetitions=1,warmup=1,output=self.directory)
        self.assertEqual([r['variant'] for r in rows],['original','packet','packet','original'])
        self.assertEqual([r['sequence'] for r in rows],[3,4,5,6])
        self.assertEqual(len(pairs),2)
        summary=runner.summarize(rows,pairs)
        self.assertEqual(summary['groups']['packet']['samples'],2)
        self.assertEqual(summary['pair_counts']['support_pixel_changed'],0)
        self.assertFalse(summary['live_rate_or_deadline_verified'])

    def test_empty_detection_is_still_withheld(self):
        row=runner.measure(self.job,'packet',1,self.engine(),lambda frame:[])
        self.assertFalse(row['measurement']['distance_available'])
        self.assertEqual(row['measurement']['reason'],'no_candidate')

    def test_diagnostic_over200_does_not_claim_deadline(self):
        actual=runner.roundtrip
        def old_first(image,sequence):
            decoded,codec=actual(image,sequence)
            codec['first_received_at_sec']-=.25
            return decoded,codec
        with patch.object(runner,'roundtrip',side_effect=old_first):
            row=runner.measure(self.job,'packet',1,self.engine(),self.predictor)
        self.assertGreater(row['receiver_stage_ms'],200)
        self.assertFalse(row['receiver_first_to_geometry_within_200ms'])
        self.assertFalse(row['usable_for_ffb'])

    def test_cuda_unavailable_has_no_cpu_fallback(self):
        from types import SimpleNamespace
        fake=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False))
        with patch.dict(sys.modules,{'torch':fake}):
            with self.assertRaisesRegex(ValueError,'no CPU fallback'):runner.cuda_environment(0)

    def test_mutating_predictor_rejected(self):
        def corrupt(frame):
            frame.image.flags.writeable=True;frame.image[0,0]=0;frame.image.flags.writeable=False
            return []
        with self.assertRaisesRegex(ValueError,'modified inference'):
            runner.measure(self.job,'packet',1,self.engine(),corrupt)

    def test_late_decoder_does_not_gain_diagnostic_fallback(self):
        with patch.object(runner.packet.LosslessPacketReceiver,'accept',return_value=False):
            with self.assertRaisesRegex(ValueError,'expired'):
                runner.roundtrip(self.job['image'],1)

    def test_missing_fragment_assembly_rejected(self):
        with patch.object(runner.flow.LosslessReassembler,'accept',return_value=None):
            with self.assertRaisesRegex(ValueError,'reassembly'):
                runner.roundtrip(self.job['image'],1)

    def test_runtime_authority_not_inherited_from_modified_engine(self):
        engine=self.engine();original=engine.measure
        def bad(*args):value=original(*args);value['usable_for_ffb']=True;return value
        engine.measure=bad
        with self.assertRaisesRegex(ValueError,'authority'):
            runner.measure(self.job,'original',1,engine,self.predictor)

    def test_roi_is_fixed_per_image_and_not_detector_selected(self):
        self.assertEqual(runner.ROIS[runner.NAMES[0]],[200,0,280,720])
        for name in runner.NAMES[1:]:self.assertEqual(runner.ROIS[name],[270,0,350,720])

    def test_find_inputs_exact_four_hashes(self):
        paths=[];known={}
        for name in runner.NAMES:
            path=self.directory/name;path.write_bytes(self.path.read_bytes())
            known[name]=probe.sha_bytes(path.read_bytes());paths.append(path)
        with patch.dict(probe.KNOWN_IMAGES,known,clear=True):
            self.assertEqual(runner.find_inputs([self.directory]),paths)
            paths[-1].write_bytes(b'changed')
            with self.assertRaisesRegex(FileNotFoundError,runner.NAMES[-1]):runner.find_inputs([self.directory])

    def test_symlink_input_does_not_satisfy_missing_original(self):
        source=self.directory/'source';source.write_bytes(self.path.read_bytes())
        target=self.directory/runner.NAMES[-1];target.symlink_to(source)
        with patch.dict(probe.KNOWN_IMAGES,{n:probe.sha_bytes(source.read_bytes()) for n in runner.NAMES},clear=True):
            with self.assertRaises(FileNotFoundError):runner.find_inputs([self.directory])

    def test_manifest_diff_rejects_code_mismatch(self):
        manifest=runner.manifest_value();path=self.directory/'manifest.json'
        path.write_bytes(probe.json_bytes(manifest));self.assertEqual(runner.checked_manifest(path),manifest)
        manifest['source_code_sha256'][runner.SOURCE_PATHS[0]]='0'*64
        path.write_bytes(probe.json_bytes(manifest))
        with self.assertRaisesRegex(ValueError,'manifest'):runner.checked_manifest(path)

    def test_wrong_weights_rejected_before_cuda(self):
        path=self.directory/'weights.pt';path.write_bytes(b'not trusted')
        args=argparse.Namespace(manifest=self.directory/'manifest.json',search_root=[self.directory],weights=path,device=0)
        with patch.object(runner,'checked_manifest',return_value=runner.manifest_value()),patch.object(runner,'find_inputs',return_value=[self.path]),patch.object(probe,'load_images',return_value=[self.job]):
            with self.assertRaisesRegex(ValueError,'weights SHA'):runner.inspect(args)

    def test_run_needs_ack_no_output_before_failure(self):
        output=self.directory/'run'
        with patch('sys.stderr',io.StringIO()),patch.object(runner,'cuda_environment',side_effect=AssertionError('must not reach CUDA')):
            status=runner.main(['run','--weights',str(self.directory/'none.pt'),'--output-dir',str(output)])
        self.assertEqual(status,1);self.assertFalse(output.exists())

    def test_missing_images_does_not_start_cuda_or_create_output(self):
        manifest=self.directory/'manifest.json';manifest.write_bytes(probe.json_bytes(runner.manifest_value()))
        with patch('sys.stderr',io.StringIO()),patch.object(runner,'cuda_environment',side_effect=AssertionError('must not reach CUDA')):
            status=runner.main(['check','--weights',str(self.directory/'none.pt'),'--manifest',str(manifest),'--search-root',str(self.directory)])
        self.assertEqual(status,1)

    def test_no_existing_samples_overwrite_and_bounded_arguments(self):
        (self.directory/'samples.jsonl').write_text('untouched')
        with self.assertRaises(FileExistsError):runner.benchmark([self.job],self.predictor,self.engine,repetitions=1,warmup=1,output=self.directory)
        self.assertEqual((self.directory/'samples.jsonl').read_text(),'untouched')
        for options in (dict(repetitions=0),dict(repetitions=True),dict(warmup=0)):
            with self.assertRaises(ValueError):runner.benchmark([self.job],self.predictor,self.engine,**options)

    def test_sample_log_size_limit_does_not_append_partial_record(self):
        with patch.object(probe,'MAX_LOG',10):
            with self.assertRaisesRegex(ValueError,'log exceeded'):
                runner.benchmark([self.job],self.predictor,self.engine,repetitions=1,warmup=1,output=self.directory)
        self.assertEqual((self.directory/'samples.jsonl').read_bytes(),b'')

    def result_fixture(self,state='complete'):
        output=self.directory/'result';output.mkdir()
        for name in runner.RESULTS:(output/name).write_bytes(b'{}\n')
        summary=dict(schema='offline_lossless_GPU_summary_v1',state=state,actual_cuda_inference=True,
            result_sha256={n:probe.digest(output/n) for n in runner.RESULTS})
        (output/'summary.json').write_bytes(probe.json_bytes(summary))
        return output

    def test_result_pack_allowlist_excludes_originals_model_and_config(self):
        output=self.result_fixture();(output/'forbidden.png').write_bytes(b'not included')
        (output/'weights.pt').write_bytes(b'not included')
        archive=self.directory/'out.tar.xz';runner.package(output,archive)
        with tarfile.open(archive) as bundle:
            self.assertEqual(set(bundle.getnames()),{'result/'+n for n in (*runner.RESULTS,'summary.json')})
        with self.assertRaises(ValueError):runner.package(output,archive)

    def test_failed_or_modified_result_not_packaged(self):
        output=self.result_fixture(state='failed');archive=self.directory/'out.tar.xz'
        with self.assertRaisesRegex(ValueError,'complete'):runner.package(output,archive)
        self.assertFalse(archive.exists())
        summary=json.loads((output/'summary.json').read_bytes());summary['state']='complete'
        (output/'summary.json').write_bytes(probe.json_bytes(summary));(output/'pairs.jsonl').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hashes'):runner.package(output,archive)
        self.assertFalse(archive.exists())


if __name__=='__main__':unittest.main()
