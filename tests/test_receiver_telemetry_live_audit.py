"""Synthetic fixtures for submitted-log review; no Downloads/live dependency."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
spec = importlib.util.spec_from_file_location('telemetry_live_review', ROOT/
    'Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/review.py')
review = importlib.util.module_from_spec(spec); spec.loader.exec_module(review)
SOURCE = {'driver_telemetry_recording.py':'a'*64, 'webrtc_receive_ui.py':'b'*64}
CLOCK = 'receiver-process/'+'c'*32


def fixture():
    rows = []
    for seq, kind in enumerate(('peer_begin', 'telemetry', 'telemetry'), 1):
        rows.append(dict(schema='driver_received_telemetry_v1', session='d'*32, sequence=seq,
            receiver_clock_id=CLOCK, received_at_sec=float(seq), logged_at_sec=seq+.001,
            event_kind=kind, source_kind='legacy_telemetry' if kind=='telemetry' else None,
            source_clock_id=None, source_stamp_ns=None, motion_frame_id=None, measurement_valid=None,
            source_freshness_verified=False, invalid_fields=[],
            **{key:0. if kind=='telemetry' else None for key in review.NUMBERS.values()}, **review.FALSE_FLAGS))
    metadata = dict(schema='driver_telemetry_recording_metadata_v1', receiver_clock_id=CLOCK,
        source_sha256=dict(SOURCE), clock_basis='time.monotonic_in_receiver_process_shared_with_native_video_receive',
        source_time_basis='unknown_NOT_sender_wall_timestamp', versioned_source_motion_metadata_supported=False,
        values_are_received_not_verified_measurements=True, image_or_arbitrary_message_saved=False, **review.FALSE_FLAGS)
    summary = dict(schema='driver_telemetry_recording_summary_v1', receiver_clock_id=CLOCK,
        state='closed', error=None, stop_requested=True, writer_done=True, shutdown_complete=True,
        offered=4, queued=3, queue_drops=0, busy_drops=0, rejected=1, written=3, log_bytes=0,
        discarded_pending=0, pending=0, in_flight=0, max_records=100, max_bytes=100000,
        queue_capacity=128, max_offer_ms=.1, source_time_or_validity_inferred=False,
        control_channel_modified=False, distance_computation_modified=False, **review.FALSE_FLAGS)
    return rows, metadata, summary


def files_for(rows, metadata, summary):
    log = b''.join(json.dumps(row, allow_nan=False).encode()+b'\n' for row in rows)
    summary = dict(summary, log_bytes=len(log))
    return {'received_telemetry.jsonl':log, 'telemetry_recording_metadata.json':json.dumps(metadata).encode(),
            'telemetry_recording_summary.json':json.dumps(summary).encode()}


class TelemetryLiveReviewTests(unittest.TestCase):
    def test_counts_tail_rejection_and_unknown_motion_preserved(self):
        result = review.analyze(files_for(*fixture()), expected_source_sha256=SOURCE)
        self.assertEqual(result['state'], 'pass')
        self.assertEqual(result['telemetry_records'], 2)
        self.assertEqual(result['recorded_events'], 3)
        self.assertEqual(result['trailing_unrecorded_offer_count'], 1)
        self.assertFalse(result['rejection_cause_established'])
        self.assertFalse(result['zero_values_prove_valid_stationary_odometry'])
        self.assertFalse(result['distance_motion_pairing_verified'])

    def test_bad_row_schema_flag_and_temporal_order_rejected(self):
        for field, value in (('usable_for_ffb', True), ('logged_at_sec', 0.),
                             ('source_stamp_ns', 123), ('source_freshness_verified', True),
                             ('linear_mps', True), ('session', 'bad'), ('receiver_clock_id', 'other'),
                             ('extra_field', 'extra')):
            rows, metadata, summary = fixture(); rows[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                review.analyze(files_for(rows, metadata, summary), expected_source_sha256=SOURCE)

    def test_counter_integrity_and_incomplete_shutdown_rejected(self):
        for field, value in (('offered', 5), ('queued', 4), ('written', 4), ('error', 'failed'),
                             ('pending', 1), ('state', 'limit_reached'), ('writer_done', False),
                             ('max_bytes', 1), ('rejected', True)):
            rows, metadata, summary = fixture(); summary[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                review.analyze(files_for(rows, metadata, summary), expected_source_sha256=SOURCE)

    def test_source_digest_and_clock_identity_mismatch_rejected(self):
        for field, value in (('source_sha256', {}), ('receiver_clock_id', 'other'),
                             ('source_time_basis', 'ROS'), ('versioned_source_motion_metadata_supported', True)):
            rows, metadata, summary = fixture(); metadata[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                review.analyze(files_for(rows, metadata, summary), expected_source_sha256=SOURCE)

    def test_sequence_reversal_and_time_reversal_rejected(self):
        for field, value in (('sequence', 2), ('received_at_sec', 1.), ('logged_at_sec', 2.0001)):
            rows, metadata, summary = fixture(); rows[2][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                review.analyze(files_for(rows, metadata, summary), expected_source_sha256=SOURCE)

    def test_partial_line_rejected_even_when_byte_count_matches(self):
        files = files_for(*fixture())
        files['received_telemetry.jsonl'] = files['received_telemetry.jsonl'][:-1]
        summary = json.loads(files['telemetry_recording_summary.json'])
        summary['log_bytes'] -= 1
        files['telemetry_recording_summary.json'] = json.dumps(summary).encode()
        with self.assertRaises(ValueError):
            review.analyze(files, expected_source_sha256=SOURCE)

    def test_duplicate_and_nonfinite_json_rejected(self):
        for payload in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError):
                review.strict_json(payload)

    def test_statistics_interpolation_is_explicit(self):
        result = review.stats([1., 2., 3.])
        self.assertEqual(result['median'], 2.)
        self.assertAlmostEqual(result['p95'], 2.9)
        self.assertEqual(result['maximum'], 3.)

    def test_archive_accepts_exact_regular_files_without_extracting_links(self):
        def write_archive(path, rename=None, link=False):
            with tarfile.open(path, 'w:xz') as tar:
                directory = tarfile.TarInfo(review.PREFIX); directory.type=tarfile.DIRTYPE; tar.addfile(directory)
                for index, (name, payload) in enumerate(files_for(*fixture()).items()):
                    info = tarfile.TarInfo(review.PREFIX+name if rename is None or index else rename)
                    if link and index == 0:
                        info.type=tarfile.SYMTYPE; info.linkname='/unrelated'; tar.addfile(info)
                    else:
                        info.size=len(payload); tar.addfile(info, io.BytesIO(payload))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'archive.tar.xz'
            write_archive(path)
            self.assertEqual(review.checked_archive(path), files_for(*fixture()))
            for name, link in (('../outside', False), (review.PREFIX+'telemetry_recording_summary.json', False),
                               (None, True)):
                write_archive(path, rename=name, link=link)
                with self.subTest(name=name, link=link), self.assertRaises(ValueError):
                    review.checked_archive(path)


if __name__ == '__main__':
    unittest.main()
