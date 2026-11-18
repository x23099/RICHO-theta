"""Synthetic transport-probe pairing tests; no RTC, camera or network."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'Experimental_results/2026-11-18/png_link_probe_r01'
SPEC = importlib.util.spec_from_file_location('png_link_probe_audit_test', HERE / 'audit_probe.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

PROFILE = dict(sender_id='a' * 32, stream_id='b' * 32, rate_hz=5)


def summary(role, *, activated=True, handed=100, completed=90, published=80, closed=True, gaps=10):
    return dict(schema=audit.SCHEMA, role=role, profile=dict(PROFILE), elapsed_sec=30.,
                closed=closed, error=None,
                counters=dict(frames_published=published, image_bytes=published * 1000,
                              sequence_gaps=gaps, out_of_order=0,
                              delivery_latency_min_sec=.01, delivery_latency_max_sec=.2,
                              delivery_latency_mean_sec=.05),
                channel=dict(activated=activated, messages_sent=handed * 62,
                             scheduler=dict(offered=handed, expired=0, pending_replaced=0,
                                            chunks_handed_off=handed * 62, packets_handed_off=handed),
                             encoder_replaced=0, peak_retained_bytes=1 << 20,
                             channel_error=None, binding_error=None, source_error=None)
                if role == 'sender' else
                dict(configured=True, assembler=dict(completed=completed, delivered=completed,
                                                    replaced=0, expired=0, duplicates=0,
                                                    invalid=0, conflicts=0),
                     inbox_replaced=0, inbox_peak_queued=1, worker_error=None, binding_error=None),
                inference_started=False, ros_published=False, usable_for_ffb=False)


class ProbeAuditTests(unittest.TestCase):
    def test_pairing_reports_frame_level_outcomes(self):
        result = audit.paired(summary('sender'), summary('receiver'))
        self.assertEqual(result['frames_handed_off'], 100)
        self.assertEqual(result['receiver_frames_completed'], 90)
        self.assertEqual(result['receiver_frames_published'], 80)
        self.assertAlmostEqual(result['frame_completion_ratio'], .9)
        self.assertAlmostEqual(result['frame_publication_ratio'], .8)
        self.assertFalse(result['usable_for_ffb'])
        self.assertFalse(result['video_fps_measured'])

    def test_scope_mismatch_and_reversed_roles_are_rejected(self):
        other = summary('receiver')
        other['profile']['stream_id'] = 'c' * 32
        with self.assertRaises(ValueError):
            audit.paired(summary('sender'), other)
        with self.assertRaises(ValueError):
            audit.paired(summary('receiver'), summary('sender'))

    def test_unactivated_or_configured_channel_is_rejected(self):
        with self.assertRaises(ValueError):
            audit.paired(summary('sender', activated=False), summary('receiver'))
        receiver = summary('receiver')
        receiver['channel']['configured'] = False
        with self.assertRaises(ValueError):
            audit.paired(summary('sender'), receiver)

    def test_authority_flags_on_load_are_rejected(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'receiver_probe.json'
        value = summary('receiver')
        value['usable_for_ffb'] = True
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            audit.load(path)

    def test_zero_handoff_is_rejected(self):
        with self.assertRaises(ValueError):
            audit.paired(summary('sender', handed=0), summary('receiver'))


if __name__ == '__main__':
    unittest.main()
