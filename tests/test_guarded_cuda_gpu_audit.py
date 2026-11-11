"""Audit input rejection tests; synthetic JSON/tar only, no CUDA or devices."""
import copy
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01'))
import audit as gpu_audit


class CudaArchiveAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.tar.xz'

    def archive(self,entries):
        with tarfile.open(self.path,'w:xz') as archive:
            for name,kind,blob in entries:
                info=tarfile.TarInfo(name)
                if kind=='symlink':info.type=tarfile.SYMTYPE;info.linkname='/tmp/not_followed'
                elif kind=='fifo':info.type=tarfile.FIFOTYPE
                elif kind=='large':info.size=17*1024*1024
                else:info.size=len(blob)
                archive.addfile(info,io.BytesIO(blob) if kind=='file' else None)

    def test_regular_payload_accepted_without_extracting(self):
        self.archive([('guarded_cuda_gpu_r01/summary.json','file',b'{}')])
        self.assertEqual(gpu_audit.archive_payload(self.path),{'summary.json':b'{}'})
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])

    def test_path_traversal_absolute_and_noncanonical_names_rejected(self):
        for name in ('../summary.json','/summary.json','guarded_cuda_gpu_r01/../summary.json',
                     'guarded_cuda_gpu_r01/./summary.json','other/summary.json',
                     'guarded_cuda_gpu_r01/a\\b'):
            with self.subTest(name=name):
                self.archive([(name,'file',b'{}')])
                with self.assertRaises(ValueError):gpu_audit.archive_payload(self.path)

    def test_links_and_fifo_rejected(self):
        for kind in ('symlink','fifo'):
            with self.subTest(kind=kind):
                self.archive([('guarded_cuda_gpu_r01/summary.json',kind,b'')])
                with self.assertRaisesRegex(ValueError,'links and special'):
                    gpu_audit.archive_payload(self.path)

    def test_duplicate_file_rejected(self):
        self.archive([('guarded_cuda_gpu_r01/summary.json','file',b'{}')]*2)
        with self.assertRaisesRegex(ValueError,'duplicate'):gpu_audit.archive_payload(self.path)

    def test_oversized_member_rejected_before_read(self):
        self.archive([('guarded_cuda_gpu_r01/summary.json','large',b'')])
        with self.assertRaisesRegex(ValueError,'oversized archive entry'):
            gpu_audit.archive_payload(self.path)

    def test_truncated_nonfinite_and_duplicate_json_rejected(self):
        for blob in (b'{}',b'{"a":NaN}\n',b'{"a":1,"a":2}\n'):
            with self.subTest(blob=blob),self.assertRaises(ValueError):gpu_audit.rows(blob)

    @staticmethod
    def primary():
        job=dict(session='a'*32,frame=7,pixel_sha256='b'*64)
        row=dict(schema='cone_motion_range_v1',session='c'*32,frame=2,original_session='a'*32,
            original_frame=7,input_pixel_sha256='b'*64,profile_sha256='d'*64,
            inference_source='cuda_yolo_on_saved_native_png_NOT_live_camera',
            input_source='preloaded_historical_native_png_NOT_camera_or_RTC',
            source_time_kind='synthetic_monotonic_arrival_at_predictor_call',
            frame_age_ms=10.,predict_ms=6.,support_geometry_ms=4.,source_time_sec=1.,completed_time_sec=1.01,
            raw_detector_boxes=[dict(image='c'*32+':2')],**gpu_audit.replay.FLAGS)
        return job,row

    def test_matching_primary_identity_and_timing_accepted(self):
        job,row=self.primary();gpu_audit.checked_primary(row,job,'c'*32,2,'d'*64)

    def test_tampered_primary_identity_timing_or_authority_rejected(self):
        job,row=self.primary()
        for values in (dict(original_frame=8),dict(frame=3),dict(physical_metric_verified=True),
                       dict(completed_time_sec=2.),dict(frame_age_ms=11.),dict(predict_ms=-1.),
                       dict(support_geometry_ms=float('nan')),dict(raw_detector_boxes=[dict(image='wrong')]),
                       dict(inference_source='cached')):
            candidate=copy.deepcopy(row);candidate.update(values)
            with self.subTest(values=values),self.assertRaises(ValueError):
                gpu_audit.checked_primary(candidate,job,'c'*32,2,'d'*64)

    def test_timing_comparison_rejects_nonfinite_or_drift(self):
        for a,b in ((1.,2.),(float('nan'),1.),(float('inf'),float('inf'))):
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):gpu_audit.close(a,b)


if __name__=='__main__':unittest.main()
