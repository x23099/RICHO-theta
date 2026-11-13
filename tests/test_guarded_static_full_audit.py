"""Full-run audit pairing/rejection tests; no camera, model or remote paths."""
import copy
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('static_full_audit',
    ROOT/'Experimental_results/2026-11-13/guarded_static_live_audit_r02/review.py')
review=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(review)


class StaticFullAuditTests(unittest.TestCase):
    def fixture(self):
        main=dict(session='a'*32,frame=101,source_time_sec=1.,completed_time_sec=1.01,
            distance_available=True,horizontal_camera_foot_range_m=1.69,reason='experimental',frame_age_ms=10.)
        row=dict(session='a'*32,frame=101,source_time_sec=1.,completed_time_sec=1.012,
            original_distance_available=True,original_range_m=1.69,comparison_distance_available=True,
            comparison_range_m=1.69,reason='experimental',reference_generation=1,reference_frame=50,
            baseline_reproduced=True,reference_scope_verified=True,comparison_service_ms=1.,
            reference_used_posthoc=False,main_display_modified=False,**{k:False for k in review.FLAGS})
        return row,main,dict(source_frame=50)

    def test_matching_numeric_pair_and_age(self):
        row,main,reference=self.fixture();old=copy.deepcopy((row,main,reference))
        self.assertAlmostEqual(review.matched_comparison(row,main,reference),12.)
        self.assertEqual((row,main,reference),old)

    def test_identity_and_original_value_tamper_rejected(self):
        row,main,reference=self.fixture()
        for values in (dict(session='b'*32),dict(frame=102),dict(source_time_sec=2.),dict(original_range_m=1.7)):
            candidate=dict(row,**values)
            with self.subTest(values=values),self.assertRaises(ValueError):review.matched_comparison(candidate,main,reference)

    def test_numeric_without_scope_or_baseline_rejected(self):
        row,main,reference=self.fixture()
        for values in (dict(reference_scope_verified=False),dict(baseline_reproduced=False),dict(comparison_range_m=-1.)):
            with self.subTest(values=values),self.assertRaises(ValueError):
                review.matched_comparison(dict(row,**values),main,reference)

    def test_authority_or_future_reference_rejected(self):
        row,main,reference=self.fixture()
        for values in (dict(usable_for_ffb=True),dict(reference_frame=100),dict(reference_generation=2)):
            with self.subTest(values=values),self.assertRaises(ValueError):
                review.matched_comparison(dict(row,**values),main,reference)

    def test_causality_staleness_and_negative_service_rejected(self):
        row,main,reference=self.fixture()
        for values in (dict(completed_time_sec=1.001),dict(completed_time_sec=1.6),dict(comparison_service_ms=-1.)):
            with self.subTest(values=values),self.assertRaises(ValueError):
                review.matched_comparison(dict(row,**values),main,reference)

    def test_paired_aggregation_keeps_numeric_and_withheld_separate(self):
        row,main,_=self.fixture();other=dict(row,frame=102,source_time_sec=1.03,completed_time_sec=1.042,
            original_distance_available=False,original_range_m=None,comparison_distance_available=False,
            comparison_range_m=None,reason='no_candidate')
        second=dict(main,frame=102,source_time_sec=1.03,distance_available=False,horizontal_camera_foot_range_m=None,reason='no_candidate')
        report=review.paired_stats([row,other],{('a'*32,101):main,('a'*32,102):second})
        self.assertEqual(report['rows'],2);self.assertEqual(report['comparison_numeric'],1)
        self.assertEqual(report['both_numeric_exact_equal'],1)
        self.assertEqual(report['comparison_numeric_range_m']['count'],1)
        self.assertEqual(report['comparison_reason_counts'],{'experimental':1,'no_candidate':1})
        self.assertEqual(review.paired_stats([],{} )['rows'],0)

    def test_missing_or_unsafe_archive_rejected_before_target_creation(self):
        valid=review.PREFIXES['primary']+'/motion_profile_used.json'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.tar.xz';target=Path(directory)/'intake'
            for names,link in (([valid],False),([valid,valid],False),(['../outside'],False),([valid],True)):
                with tarfile.open(path,'w:xz') as archive:
                    for name in names:
                        item=tarfile.TarInfo(name)
                        if link:item.type=tarfile.SYMTYPE;item.linkname='/not_opened'
                        else:item.size=2
                        archive.addfile(item,None if link else io.BytesIO(b'{}'))
                with self.subTest(names=names,link=link),self.assertRaises(ValueError):review.extract_archive(path,target)
                self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
