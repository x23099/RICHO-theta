"""Three reported distances: exact frame matching, no metric certification."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('range_audit_test',
    ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/review.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
context = audit.module('range_context_test',
    ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/context.py')


class RangeAuditTests(unittest.TestCase):
    def test_run_normalizes_relative_paths_before_existing_output_check(self):
        args = SimpleNamespace(archive=Path('input.tar.xz'), intake_dir=Path('.'), output_dir=Path('new-output'))
        with self.assertRaisesRegex(ValueError, 'new output paths'):
            audit.run(args)
        self.assertTrue(args.archive.is_absolute())
        self.assertTrue(args.intake_dir.is_absolute())
        self.assertTrue(args.output_dir.is_absolute())

    def test_context_uses_source_time_and_same_session_not_frame_neighbours(self):
        rows = [dict(session=audit.SESSION, frame=str(frame), source_time_sec=str(time),
                     display_permitted='True', display_range_m=str(value), display_reason='numeric')
                for frame, time, value in ((10, 10., 1.), (20, 10.4, 1.01), (21, 12., 2.))]
        rows.append(dict(rows[0], session='a'*32, frame='10', display_range_m='9'))
        result = context.windows(rows, [dict(session=audit.SESSION, frame=10)])[0]
        self.assertEqual(result['rows'], 2)
        self.assertEqual(result['max_m'], 1.01)
        self.assertFalse(result['stationary_or_measured_interval_verified'])

    def test_context_rejects_missing_duplicate_anchor_and_invalid_csv_flag(self):
        row = dict(session=audit.SESSION, frame='10', source_time_sec='10',
                   display_permitted='True', display_range_m='1', display_reason='numeric')
        point = dict(session=audit.SESSION, frame=10)
        for rows in ([], [row, row], [dict(row, display_permitted='yes')]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                context.windows(rows, [point])

    def test_context_keeps_withheld_rows_without_inventing_numeric_value(self):
        row = dict(session=audit.SESSION, frame='10', source_time_sec='10',
                   display_permitted='False', display_range_m='', display_reason='no_candidate')
        result = context.windows([row], [dict(session=audit.SESSION, frame=10)])[0]
        self.assertEqual(result['numeric_rows'], 0)
        self.assertIsNone(result['min_m'])
        self.assertEqual(result['reasons'], {'no_candidate': 1})

    def fixture(self):
        observation = dict(session=audit.SESSION, frame='34957', body_review_generation='1',
            reported_floor_range_m='1.000', displayed_range_m='1.005',
            signed_difference_m='0.005', signed_difference_percent='0.5')
        row = dict(session=audit.SESSION, frame=34957, reference_generation=1,
            source_time_sec=20., display_permitted=True, bridge_accepted=True, original_available=True,
            display_range_m=1.00512, original_range_m=1.00512, raw_age_ms=16.,
            review_age_ms=16.4, raw_to_review_ms=.4, comparison_range_m=1.00512,
            original_reason='experimental', display_reason='experimental')
        return observation, row

    def test_rounded_value_matches_exact_logged_frame(self):
        observation, row = self.fixture()
        result = audit.check_observation(observation, row)
        self.assertTrue(result['rounded_screen_value_matches'])
        self.assertEqual(result['displayed_minus_reported_m'], .005)
        self.assertIsNone(result['measurement_uncertainty_m'])
        self.assertFalse(result['screenshot_original_file_supplied'])

    def test_wrong_identity_generation_permission_and_substitution_rejected(self):
        observation, row = self.fixture()
        for changes in (dict(session='a'*32), dict(frame=34958), dict(reference_generation=2),
                        dict(display_permitted=False), dict(bridge_accepted=False),
                        dict(original_available=False), dict(original_range_m=1.1),
                        dict(display_range_m=1.006, original_range_m=1.006)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                audit.check_observation(observation, dict(row, **changes))

    def test_wrong_measurement_difference_and_percent_rejected(self):
        observation, row = self.fixture()
        for changes in (dict(reported_floor_range_m='0'), dict(signed_difference_m='-0.005'),
                        dict(signed_difference_percent='5')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                audit.check_observation(dict(observation, **changes), row)

    def test_negative_difference_at_two_metres(self):
        observation, row = self.fixture()
        observation.update(reported_floor_range_m='2.000', displayed_range_m='1.960',
            signed_difference_m='-0.040', signed_difference_percent='-2.0')
        row.update(display_range_m=1.9601, original_range_m=1.9601)
        self.assertEqual(audit.check_observation(observation, row)['displayed_minus_reported_m'], -.04)

    def fixture_archive(self, path, *, omit=False, extra=None):
        allowed = {audit.PREFIXES[role]+'/'+name: role+'/'+name
                   for role, names in audit.FILES.items() for name in names}
        with tarfile.open(path, 'w:xz') as stream:
            for name in list(allowed)[:-1] if omit else allowed:
                item = tarfile.TarInfo(name)
                item.size = 2
                stream.addfile(item, io.BytesIO(b'{}'))
            if extra is not None:
                stream.addfile(extra)
        return allowed

    def test_current_day_sixteen_file_mapping_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = self.fixture_archive(root/'in.tar.xz')
            self.assertEqual(len(allowed), 16)
            hashes = audit.intake.extract_checked(root/'in.tar.xz', root/'out', allowed, set())
            self.assertEqual(len(hashes), 16)
            with self.assertRaises(ValueError):
                audit.intake.extract_checked(root/'in.tar.xz', root/'out', allowed, set())

    def test_missing_traversal_duplicate_and_symlink_rejected_before_writing(self):
        duplicate = tarfile.TarInfo(audit.PREFIXES['comparison']+'/reference.json')
        link = tarfile.TarInfo('link')
        link.type, link.linkname = tarfile.SYMTYPE, '/tmp/outside'
        for label, extra, omit in (('missing', None, True), ('traversal', tarfile.TarInfo('../outside'), False),
                                   ('duplicate', duplicate, False), ('link', link, False)):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                allowed = self.fixture_archive(root/'in.tar.xz', omit=omit, extra=extra)
                with self.assertRaises(ValueError):
                    audit.intake.extract_checked(root/'in.tar.xz', root/'out', allowed, set())
                self.assertFalse((root/'out').exists())


if __name__ == '__main__':
    unittest.main()
