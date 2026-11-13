"""Scalar audit and bounded archive intake, synthetic data only."""
import copy
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('body_static_audit',
    ROOT/'Experimental_results/2026-11-13/body_display_static_live_audit_r01/review.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class BodyStaticAuditTests(unittest.TestCase):
    def fixture(self):
        main = dict(session='a'*32, frame=20, source_time_sec=10., completed_time_sec=10.01,
                    distance_available=True, horizontal_camera_foot_range_m=1.2, reason='experimental')
        reference = dict(source_frame=1, source_png_sha256='b'*64)
        review = dict(schema='driver_body_display_review_v1', session=main['session'], frame=20,
            source_time_sec=10., original_available=True, original_range_m=1.2,
            display_available=True, display_range_m=1.2, reason=main['reason'], body_review_reason=audit.CLEAR,
            reference_generation=1, reference_frame=1, reference_png_sha256='b'*64,
            reference_scope_verified=True, completed_time_sec=10.011, **{k: False for k in audit.FLAGS})
        return main, review, {'display_review': copy.deepcopy(review)}, reference

    def test_exact_raw_review_bridge_pair(self):
        m, r, e, ref = self.fixture()
        self.assertAlmostEqual(audit.matched_review(r, m, e, ref), 11.)

    def test_different_bridge_copy_or_reference_rejected(self):
        m, r, e, ref = self.fixture()
        e['display_review']['reason'] = 'different'
        with self.assertRaisesRegex(ValueError, 'bridge/display'): audit.matched_review(r, m, e, ref)
        e['display_review'] = copy.deepcopy(r)
        ref['source_png_sha256'] = 'c'*64
        with self.assertRaisesRegex(ValueError, 'reference binding'): audit.matched_review(r, m, e, ref)

    def test_changed_value_rescue_or_control_flag_rejected(self):
        for change in ('range', 'rescue', 'authority'):
            m, r, e, ref = self.fixture()
            if change == 'range': r['display_range_m'] = 1.3
            elif change == 'rescue': m.update(distance_available=False, horizontal_camera_foot_range_m=None)
            else: r['usable_for_ffb'] = True
            with self.subTest(change=change), self.assertRaises(ValueError): audit.matched_review(r, m, e, ref)

    def test_stale_numeric_or_review_before_raw_completion_rejected(self):
        for completion in (10.009, 10.6):
            m, r, e, ref = self.fixture()
            r['completed_time_sec'] = completion
            e['display_review'] = copy.deepcopy(r)
            with self.subTest(completion=completion), self.assertRaises(ValueError): audit.matched_review(r, m, e, ref)

    def test_phase_uses_first_activation_not_numeric_cherry_picking(self):
        frames = [dict(frame=i, source_time_sec=float(i)) for i in (1, 40, 41, 80)]
        phases = audit.phase_rows(frames, 41)
        self.assertEqual([r['frame'] for r in phases['pre_reference']], [1, 40])
        self.assertEqual([r['frame'] for r in phases['post_load']], [41, 80])
        self.assertEqual([r['frame'] for r in phases['final_30_seconds']], [80])

    def archive(self, path, *, extra=None, omit=False):
        names = [audit.PREFIXES[role]+'/'+name for role, files in audit.FILES.items() for name in files]
        with tarfile.open(path, 'w:xz') as stream:
            for name in names[:-1] if omit else names:
                info = tarfile.TarInfo(name)
                info.size = 2
                stream.addfile(info, io.BytesIO(b'{}'))
            if extra is not None: stream.addfile(extra)

    def test_exact_16_files_preserved_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.archive(root/'fixture.tar.xz')
            hashes = audit.extract_archive(root/'fixture.tar.xz', root/'raw')
            self.assertEqual(len(hashes), 16)
            self.assertTrue(all(audit.file_sha(root/'raw'/name) == digest for name, digest in hashes.items()))
            with self.assertRaises(ValueError): audit.extract_archive(root/'fixture.tar.xz', root/'raw')

    def test_missing_duplicate_traversal_or_link_rejected_before_write(self):
        cases = [('missing', None, True), ('duplicate', tarfile.TarInfo(audit.PREFIXES['comparison']+'/request.json'), False),
                 ('traversal', tarfile.TarInfo('../outside'), False), ('link', tarfile.TarInfo('outside'), False)]
        cases[-1][1].type = tarfile.SYMTYPE
        cases[-1][1].linkname = '/tmp/outside'
        for label, extra, omit in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.archive(root/'fixture.tar.xz', extra=extra, omit=omit)
                with self.assertRaises(ValueError): audit.extract_archive(root/'fixture.tar.xz', root/'raw')
                self.assertFalse((root/'raw').exists())


if __name__ == '__main__': unittest.main()
