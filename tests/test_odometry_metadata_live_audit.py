"""Synthetic audit regression tests; no ROS/Downloads dependency."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


review = module('odom_live_review',
    'Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/review.py')
fixtures = module('old_live_fixtures', 'tests/test_receiver_telemetry_live_audit.py')
from driver_odometry_observation import OdometryObserver, SCHEMA


def fixture():
    rows, md, summary = fixtures.fixture()
    observer = OdometryObserver(clock=lambda: 10.)
    for row in rows[1:]:
        row.update(schema='driver_received_telemetry_v2',
            odometry_metadata_state='versioned_odometry_observation',
            odometry_observation=observer.snapshot())
    md.update(versioned_source_motion_metadata_supported=True, supported_odometry_schema=SCHEMA,
        record_schemas=['driver_received_telemetry_v1', 'driver_received_telemetry_v2'])
    md['source_sha256']['driver_odometry_observation.py'] = 'e'*64
    return rows, md, summary


class OdometryLiveAuditTests(unittest.TestCase):
    def analyze(self, values):
        return review.analyze(fixtures.files_for(*values), values[1]['source_sha256'])

    def test_initial_zero_not_promoted_to_measured_zero(self):
        values = fixture()
        result = self.analyze(values)
        self.assertEqual(result['telemetry_records'], 2)
        self.assertEqual(result['callback_received_counts'], {'False': 2})
        self.assertEqual(result['callback_sequence_bounds'], [0, 0])
        self.assertEqual(result['observed_callback_records'], 0)
        self.assertEqual(result['trailing_unrecorded_offer_count'], 1)
        self.assertFalse(result['usable_for_ffb'])
        self.assertEqual(values[0][1]['schema'], 'driver_received_telemetry_v2')
        self.assertTrue(values[1]['versioned_source_motion_metadata_supported'])

    def test_invalid_observation_rejected(self):
        for key, value in (('callback_received', True), ('linear_mps', 0.), ('usable_for_ffb', True),
                           ('schema', 'unknown'), ('extra_field', 1)):
            values = fixture(); values[0][1]['odometry_observation'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze(values)

    def test_unknown_version_and_extra_envelope_rejected(self):
        for key, value in (('schema', 'driver_received_telemetry_v1'),
                           ('odometry_metadata_state', 'unsupported_odometry_schema'), ('extra', 1)):
            values = fixture(); values[0][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze(values)

    def test_mismatched_original_log_bytes_rejected(self):
        values = fixture(); files = fixtures.files_for(*values)
        summary = review.base.strict_json(files['telemetry_recording_summary.json'])
        summary['log_bytes'] += 1
        import json
        files['telemetry_recording_summary.json'] = json.dumps(summary).encode()
        with self.assertRaises(ValueError):
            review.analyze(files, values[1]['source_sha256'])

    def test_legacy_false_authority_and_bad_order_rejected(self):
        for key, value in (('sequence', 1), ('usable_for_ffb', True),
                           ('logged_at_sec', 0.), ('measurement_valid', True)):
            values = fixture(); values[0][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze(values)

    def test_missing_v2_declaration_rejected(self):
        values = fixture(); values[1]['versioned_source_motion_metadata_supported'] = False
        with self.assertRaises(ValueError):
            self.analyze(values)

    def test_sender_snapshot_reversal_rejected(self):
        values = fixture(); values[0][2]['odometry_observation']['snapshot_mono_sec'] = 9.
        with self.assertRaises(ValueError):
            self.analyze(values)

    def test_source_sha_mismatch_rejected(self):
        values = fixture()
        with self.assertRaises(ValueError):
            review.analyze(fixtures.files_for(*values), {})

    def test_unknown_callback_state_is_not_claimed_never_received(self):
        values = fixture()
        for row in values[0][1:]:
            o = row['odometry_observation']
            o.update(stamp_status='observer_busy', callback_received=None, callback_sequence=None)
        result = self.analyze(values)
        self.assertEqual(result['odometry_finding'], 'callback_state_unknown')
        self.assertIsNone(result['callback_sequence_bounds'])

    def test_received_zero_and_actual_stamp_progress_are_distinguished(self):
        values = fixture()
        observer = OdometryObserver(clock=lambda: 10.)
        for index, row in enumerate(values[0][1:], 1):
            observer.observe(NS(header=NS(stamp=NS(sec=index, nanosec=0), frame_id='odom'),
                child_frame_id='base_footprint',
                twist=NS(twist=NS(linear=NS(x=0.), angular=NS(z=0.)))))
            row['odometry_observation'] = observer.snapshot()
        result = self.analyze(values)
        self.assertEqual(result['callback_received_counts'], {'True': 2})
        self.assertEqual(result['sampled_header_stamp_steps'], {'advanced': 1})
        self.assertEqual(result['sampled_callback_sequence_steps'], {'advanced': 1})
        self.assertEqual(result['unique_sampled_header_stamps'], 2)
        self.assertEqual(result['observed_linear_mps']['maximum'], 0.)
        self.assertFalse(result['source_freshness_verified'])

    def test_repeated_stamp_not_inferred_advanced_from_callback_count(self):
        values = fixture()
        observer = OdometryObserver(clock=lambda: 10.)
        for row in values[0][1:]:
            observer.observe(NS(header=NS(stamp=NS(sec=1, nanosec=0), frame_id='odom'),
                child_frame_id='base_footprint',
                twist=NS(twist=NS(linear=NS(x=0.), angular=NS(z=0.)))))
            row['odometry_observation'] = observer.snapshot()
        result = self.analyze(values)
        self.assertEqual(result['sampled_header_stamp_steps'], {'repeated': 1})
        self.assertEqual(result['sampled_callback_sequence_steps'], {'advanced': 1})

    def test_explicit_archive_prefix_and_path_safety(self):
        prefix = 'received_telemetry_odom_r03/'
        payloads = fixtures.files_for(*fixture())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'archive.tar.xz'
            with tarfile.open(path, 'w:xz') as archive:
                item = tarfile.TarInfo(prefix); item.type = tarfile.DIRTYPE; archive.addfile(item)
                for name, payload in payloads.items():
                    item = tarfile.TarInfo(prefix+name); item.size = len(payload)
                    archive.addfile(item, io.BytesIO(payload))
            self.assertEqual(review.checked_archive(path, prefix), payloads)
            with self.assertRaises(ValueError):
                review.checked_archive(path)
            for bad in ('../', 'received_telemetry_odom_r03/../', '/received_telemetry_odom_r03/'):
                with self.subTest(prefix=bad), self.assertRaises(ValueError):
                    review.checked_archive(path, bad)
