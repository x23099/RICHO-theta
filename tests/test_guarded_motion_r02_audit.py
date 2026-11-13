"""Offline archive/phase audit regressions; synthetic bytes, no devices/models."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'Experimental_results/2026-11-13/guarded_motion_live_audit_r02'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


review=module('motion_r02_review',BASE/'review.py')
screen=module('motion_r02_screen',BASE/'screen_audit.py')


class MotionAuditTests(unittest.TestCase):
    def archive(self,path,names,link=False):
        with tarfile.open(path,'w:xz') as archive:
            for name in names:
                item=tarfile.TarInfo(name)
                if link:item.type=tarfile.SYMTYPE;item.linkname='/not_read'
                else:item.size=2
                archive.addfile(item,None if link else io.BytesIO(b'{}'))

    def test_exact_current_session_evidence_name(self):
        name=review.PREFIXES['evidence']+'/decoded_'+review.SESSION+'_f044302.png'
        self.assertEqual(review.classified(name),('evidence',name.rsplit('/',1)[1]))

    def test_unsafe_paths_and_foreign_session_rejected(self):
        for name in ('/tmp/a','../a','recordings/../a','recordings\\a',
            review.PREFIXES['evidence']+'/decoded_'+('f'*32)+'_f044302.png'):
            with self.subTest(name=name),self.assertRaises(ValueError):review.classified(name)

    def test_duplicate_link_and_missing_files_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.tar.xz'
            for n,(names,link) in enumerate((([review.VIDEO]*2,False),([review.VIDEO],True),([],False))):
                self.archive(path,names,link);target=Path(directory)/str(n)
                with self.assertRaises(ValueError):review.extract(path,target,video=True)
                self.assertFalse(target.exists())

    def test_video_intake_preserves_exact_bytes_and_rejects_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.tar.xz';target=Path(directory)/'intake'
            self.archive(path,[review.VIDEO]);report=review.extract(path,target,video=True)
            self.assertEqual((target/'screen'/review.VIDEO).read_bytes(),b'{}')
            self.assertEqual(len(report['files_sha256']),1)
            with self.assertRaises(ValueError):review.extract(path,target,video=True)

    def test_unpaired_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.tar.xz';target=Path(directory)/'intake'
            names=[review.PREFIXES[role]+'/'+name for role,items in review.BASE_FILES.items() for name in items]
            names.append(review.PREFIXES['evidence']+'/decoded_'+review.SESSION+'_f044302.png')
            self.archive(path,names)
            with self.assertRaisesRegex(ValueError,'unpaired evidence'):review.extract(path,target)
            self.assertFalse(target.exists())

    def test_prior_test_and_post_screen_rows_not_selected(self):
        rows=[dict(frame=n) for n in (43801,44062,44063,45275,45276)]
        self.assertEqual([r['frame'] for r in screen.select_phase(rows,44063,45275)],[44063,45275])
        with self.assertRaises(ValueError):screen.select_phase(rows,45275,44063)

    def test_statistics_keep_main_numeric_and_comparison_withheld_separate(self):
        common=dict(reference_active=True,bridge_accepted=True,main_available=True,main_range_m=.65,
            comparison_available=False,comparison_range_m=None,main_reason='experimental',
            comparison_reason='possible_self_body_occlusion',main_age_ms=15.,comparison_service_ms=3.,comparison_age_ms=19.)
        result=screen.stats([dict(common,frame=10,source_time_sec=1.),dict(common,frame=12,source_time_sec=1.1)])
        self.assertEqual((result['main_numeric'],result['comparison_numeric']),(2,0))
        self.assertEqual(result['source_sequence_ids_without_paired_result'],1)
        self.assertEqual(result['both_numeric_exact_equal'],0)


if __name__=='__main__':unittest.main()
