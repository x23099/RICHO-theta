"""Closed-run intake and screen/log pairing tests; synthetic fixtures only."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'Experimental_results/2026-11-13/body_display_occlusion_live_audit_r01'
SPEC=importlib.util.spec_from_file_location('occlusion_screen_test',BASE/'screen_review.py')
screen=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(screen)
audit=screen.audit


class OcclusionAuditTests(unittest.TestCase):
    def test_numeric_requires_matching_frame_original_and_display_permission(self):
        reading=dict(displayed_frame='20',displayed_range_m='1.200')
        row=dict(frame=20,session=audit.SESSION,bridge_accepted=True,display_permitted=True,
                 reference_generation='1',display_range_m=1.2,original_range_m=1.2)
        screen.check_numeric(reading,row)
        for change in (dict(frame=21),dict(display_permitted=False),dict(original_range_m=1.3),dict(reference_generation='2')):
            with self.subTest(change=change),self.assertRaises(ValueError):screen.check_numeric(reading,dict(row,**change))

    def test_withheld_has_interval_not_invented_exact_frame(self):
        reading=dict(displayed_reason='possible_self_body_occlusion')
        rows=[dict(frame=i,source_time_sec=t,display_permitted=False,bridge_accepted=True,
                   display_reason='possible_self_body_occlusion') for i,t in ((10,101.02),(11,101.05))]
        result=screen.check_withheld(reading,1.,rows,[100.,100.1])
        self.assertFalse(result['exact_same_frame_identity_verified'])
        self.assertEqual(result['candidate_rows'],2)
        rows[1]['display_permitted']=True
        with self.assertRaises(ValueError):screen.check_withheld(reading,1.,rows,[100.,100.1])

    def test_withheld_empty_candidate_interval_rejected(self):
        with self.assertRaises(ValueError):screen.check_withheld(dict(displayed_reason='possible_self_body_occlusion'),1.,[],[100.,100.1])

    def test_csv_booleans_are_strict(self):
        with self.assertRaisesRegex(ValueError,'CSV bool'):screen.parse_row(dict(frame='1',original_available='perhaps'))

    def test_reason_runs_preserve_single_original_withheld_interruption(self):
        rows=[dict(frame=n,display_reason=reason,source_time_sec=float(n)) for n,reason in
              ((1,'possible_self_body_occlusion'),(2,'colour_contour_reaches_roi_edge'),(3,'possible_self_body_occlusion'))]
        runs=audit.reason_runs(rows)
        self.assertEqual(len(runs),3)
        self.assertEqual([r['rows'] for r in runs],[1,1,1])

    def fixture_archive(self,path,extra=None,omit=False):
        allowed={audit.PREFIXES[role]+'/'+name:role+'/'+name for role,names in audit.FILES.items() for name in names}
        with tarfile.open(path,'w:xz') as stream:
            for name in list(allowed)[:-1] if omit else allowed:
                item=tarfile.TarInfo(name);item.size=2;stream.addfile(item,io.BytesIO(b'{}'))
            if extra is not None:stream.addfile(extra)
        return allowed

    def test_eighteen_files_preserved_and_repeated_target_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);allowed=self.fixture_archive(root/'in.tar.xz')
            self.assertEqual(len(allowed),18)
            hashes=audit.extract_checked(root/'in.tar.xz',root/'raw',allowed,set())
            self.assertEqual(len(hashes),18)
            self.assertTrue(all(audit.file_sha(root/'raw'/name)==digest for name,digest in hashes.items()))
            with self.assertRaises(ValueError):audit.extract_checked(root/'in.tar.xz',root/'raw',allowed,set())

    def test_missing_duplicate_traversal_and_links_rejected_before_writing(self):
        duplicate=tarfile.TarInfo(audit.PREFIXES['comparison']+'/request.json')
        link=tarfile.TarInfo('link');link.type=tarfile.SYMTYPE;link.linkname='/tmp/outside'
        for label,extra,omit in (('missing',None,True),('duplicate',duplicate,False),
                                 ('traversal',tarfile.TarInfo('../outside'),False),('link',link,False)):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);allowed=self.fixture_archive(root/'in.tar.xz',extra,omit)
                with self.assertRaises(ValueError):audit.extract_checked(root/'in.tar.xz',root/'raw',allowed,set())
                self.assertFalse((root/'raw').exists())


if __name__=='__main__':unittest.main()
