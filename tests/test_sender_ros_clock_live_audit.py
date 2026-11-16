"""Synthetic v3 archive validation, no live ROS or Downloads dependency."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT/relative)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


review = module('sender_clock_live_review',
    'Experimental_results/2026-11-16/sender_ros_clock_live_audit_r01/review.py')
fixtures = module('clock_v2_fixtures', 'tests/test_odometry_metadata_live_audit.py')
from driver_sender_clock_observation import SenderClockObserver, SCHEMA


def fixture():
    rows, md, summary = fixtures.fixture()
    ticks = iter([10_000_000_001, 10_000_000_002, 10_000_000_003, 10_000_000_004])
    observer = SenderClockObserver(sender_id=rows[1]['odometry_observation']['sender_id'],
        read_clock=lambda:dict(ros_now_ns=100, clock_type='ROS_TIME', use_sim_time=False, ros_time_active=False),
        monotonic_ns=ticks.__next__)
    for row in rows[1:]:
        row.update(schema='driver_received_telemetry_v3', sender_clock_observation=observer.snapshot(),
                   sender_clock_metadata_state='versioned_sender_clock_observation')
    md.update(supported_sender_clock_schema=SCHEMA,
        record_schemas=['driver_received_telemetry_v1', 'driver_received_telemetry_v2', 'driver_received_telemetry_v3'])
    md['source_sha256']['driver_sender_clock_observation.py'] = 'f'*64
    return rows, md, summary


def analyze(values):
    return review.analyze(fixtures.fixtures.files_for(*values), values[1]['source_sha256'])


class SenderClockLiveAuditTests(unittest.TestCase):
    def test_valid_clock_preserved_without_certifying_binding(self):
        values = fixture(); result = analyze(values)
        self.assertEqual(result['sampled_clock_records'], 2)
        self.assertEqual(result['clock_status_counts'], {'sampled': 2})
        self.assertFalse(result['receiver_clock_binding_verified'])
        self.assertEqual(values[0][1]['schema'], 'driver_received_telemetry_v3')
        self.assertEqual(result['trailing_unrecorded_offer_count'], 1)

    def test_bad_clock_equations_flags_and_extra_fields_rejected(self):
        for key, value in (('bracket_width_ns', 5), ('usable_for_ffb', True), ('extra', 1),
                           ('ros_now_ns', True), ('ros_minus_mono_lower_ns', 999)):
            values = fixture(); values[0][1]['sender_clock_observation'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analyze(values)

    def test_foreign_sender_rejected(self):
        values = fixture(); c = values[0][1]['sender_clock_observation']
        c.update(sender_id='e'*32, sender_monotonic_clock_id='sender-process/'+'e'*32)
        with self.assertRaises(ValueError):
            analyze(values)

    def test_common_envelope_extra_or_bad_clock_rejected(self):
        for key, value in (('extra', 1), ('schema', 'driver_received_telemetry_v2'),
            ('measurement_valid', True), ('sender_clock_metadata_state', 'invalid_sender_clock_metadata')):
            values = fixture(); values[0][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analyze(values)

    def test_repeated_sample_sequence_rejected(self):
        values = fixture()
        values[0][2]['sender_clock_observation']['sample_sequence'] = 1
        with self.assertRaises(ValueError):
            analyze(values)

    def test_clock_read_before_same_message_odom_snapshot_rejected(self):
        values = fixture(); values[0][1]['odometry_observation']['snapshot_mono_sec'] = 11.
        with self.assertRaises(ValueError):
            analyze(values)

    def test_metadata_schema_and_source_sha_rejected(self):
        values = fixture(); values[1]['supported_sender_clock_schema'] = 'future'
        with self.assertRaises(ValueError):
            analyze(values)
        values = fixture()
        with self.assertRaises(ValueError):
            review.analyze(fixtures.fixtures.files_for(*values), {})

    def test_original_byte_count_checked_before_projection(self):
        values = fixture(); files = fixtures.fixtures.files_for(*values)
        summary = json.loads(files['telemetry_recording_summary.json']); summary['log_bytes'] += 1
        files['telemetry_recording_summary.json'] = json.dumps(summary).encode()
        with self.assertRaises(ValueError):
            review.analyze(files, values[1]['source_sha256'])

    def test_empty_constant_offset_intersection_not_mislabelled_binding(self):
        result = analyze(fixture())
        item = next(iter(result['conditional_constant_offset_intersections_by_sender'].values()))
        self.assertFalse(item['nonempty']); self.assertFalse(item['adopted_binding'])

    def test_archive_rejects_wrong_paths_duplicates_and_links(self):
        payloads = fixtures.fixtures.files_for(*fixture())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'input.tar.xz'
            for kind in ('valid', 'traversal', 'duplicate', 'link'):
                with tarfile.open(path, 'w:xz') as archive:
                    info = tarfile.TarInfo(review.PREFIX); info.type = tarfile.DIRTYPE; archive.addfile(info)
                    for index, (name, payload) in enumerate(payloads.items()):
                        target = review.PREFIX+name
                        if index == 0 and kind == 'traversal': target = '../outside'
                        if index == 0 and kind == 'duplicate': target = review.PREFIX
                        info = tarfile.TarInfo(target)
                        if index == 0 and kind == 'link':
                            info.type = tarfile.SYMTYPE; info.linkname = '/outside'; archive.addfile(info)
                        else:
                            info.size = len(payload); archive.addfile(info, io.BytesIO(payload))
                if kind == 'valid':
                    self.assertEqual(review.checked_archive(path), payloads)
                else:
                    with self.subTest(kind=kind), self.assertRaises(ValueError):
                        review.checked_archive(path)
