"""Cross-run audit helper tests; minimal synthetic artifacts, no GPU/images."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('guarded_cross_run_review',
    ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r02/review.py')
review=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(review)


class CrossRunAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)

    def fixture(self,changed):
        group={key:dict(p50=1.,p95=2.) for key in
            ('predict_ms','primary_ms','primary_log_and_tap_ms','start_interval_ms')}
        group['period_overruns']=3
        summary=dict(weights_sha256='a'*64,input_sha256={'/not/opened/source.json':'b'*64},
            source_sha256={name:'0'*64 for name in changed},gpu={'name':'synthetic'},runtime_versions={'python':'synthetic'},
            groups={'off':copy.deepcopy(group),'on':copy.deepcopy(group)},
            blocks=[dict(comparison_enabled=enabled,measured_frames=160,measured_wall_sec=1.)
                for enabled in (False,True,True,False)])
        (self.directory/'summary.json').write_text(json.dumps(summary))
        new=copy.deepcopy(summary);new['source_sha256']={name:'1'*64 for name in changed}
        payload={'summary.json':json.dumps(new).encode()}
        for n,enabled in enumerate((False,True,True,False)):
            label=f'block_{n:02d}_{"on" if enabled else "off"}'
            primary=[dict(frame=i+2,original_frame=7,input_pixel_sha256='c'*64,
                raw_detector_boxes=[],selected_detector_boxes=[]) for i in range(160)]
            paths={label+'/primary_frames.jsonl':primary}
            if enabled:paths[label+'/comparison/comparison_frames.jsonl']=[dict(frame=i+1) for i in range(161)]
            for name,rows in paths.items():
                blob=('\n'.join(json.dumps(row) for row in rows)+'\n').encode()
                path=self.directory/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
                payload[name]=blob
        return payload

    def test_default_two_source_change_remains_supported(self):
        payload=self.fixture(['src/cone_guarded_stream_comparison.py','src/cone_motion_range.py'])
        result,metrics=review.cross_run(self.directory,payload)
        self.assertEqual(result['primary_equal'],640)
        self.assertEqual(result['comparison_equal'],322)
        speed=next(row for row in metrics if row['condition']=='on' and row['metric']=='measured_block_throughput')
        self.assertEqual(speed['before'],160.)
        self.assertEqual(speed['change_percent'],0.)

    def test_explicit_four_source_change_supported(self):
        names=['src/a.py','src/b.py','src/c.py','src/d.py']
        payload=self.fixture(names)
        result,_=review.cross_run(self.directory,payload,expected_sources=list(reversed(names)))
        self.assertEqual(result['changed_source_files'],names)

    def test_unexpected_source_change_rejected(self):
        payload=self.fixture(['src/a.py'])
        with self.assertRaisesRegex(ValueError,'unexpected cross-run code changes'):
            review.cross_run(self.directory,payload)

    def test_cross_run_input_mismatch_rejected(self):
        payload=self.fixture(['src/a.py']);summary=json.loads(payload['summary.json'])
        summary['input_sha256']['/not/opened/source.json']='d'*64
        payload['summary.json']=json.dumps(summary).encode()
        with self.assertRaisesRegex(ValueError,'input hashes changed'):
            review.cross_run(self.directory,payload,expected_sources=['src/a.py'])

    def test_shortened_primary_block_rejected(self):
        payload=self.fixture(['src/a.py'])
        name='block_00_off/primary_frames.jsonl'
        payload[name]=b'\n'.join(payload[name].splitlines()[:-1])+b'\n'
        with self.assertRaisesRegex(ValueError,'unpaired cross-run primary'):
            review.cross_run(self.directory,payload,expected_sources=['src/a.py'])

    def test_detection_variation_is_reported_separately(self):
        payload=self.fixture(['src/a.py'])
        name='block_00_off/primary_frames.jsonl';rows=review.checker.rows(payload[name])
        rows[0]['raw_detector_boxes']=[dict(image='new_replay:2',confidence=.9)]
        payload[name]=('\n'.join(json.dumps(row) for row in rows)+'\n').encode()
        result,_=review.cross_run(self.directory,payload,expected_sources=['src/a.py'])
        self.assertEqual(result['primary_equal'],640)
        self.assertEqual(result['detector_equal'],639)


if __name__=='__main__':unittest.main()
