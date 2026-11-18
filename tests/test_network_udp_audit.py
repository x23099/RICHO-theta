"""Synthetic iperf3.9 fixtures only; no actual packets, clocks or GPU."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'Experimental_results/2026-11-18/network_coexistence_r01'
SPEC = importlib.util.spec_from_file_location('network_udp_audit_test', HERE / 'audit_udp.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class UdpAuditTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        profile = json.loads((HERE / 'inventory_audit_r01/audit.json').read_bytes())['roles']
        self.client, self.server = {}, {}
        for role, action, result, sender in (('camera', 'client', self.client, True),
                                             ('gpu', 'server', self.server, False)):
            local, remote = profile[role], profile['gpu' if role == 'camera' else 'camera']
            command, timeout = audit.probe.command('/usr/bin/iperf3', action, local['ipv4'], remote['ipv4'], 5)
            result['metadata.json'] = dict(schema='network_bounded_udp_metadata_v1', action=action,
                local_ipv4=local['ipv4'], interface=local['interface'], peer_ipv4_operator_confirmed=remote['ipv4'],
                probe_sha256=audit.sha((HERE / 'probe.py').read_bytes()),
                collect_sha256=audit.sha((HERE / 'collect.py').read_bytes()), command=command,
                process_timeout_sec=timeout, rate_mbps_client_requested=5, udp_seconds_client_requested=10,
                condition_operator_reported_NOT_verified='no-video', server_enforces_client_rate=False,
                video_or_control_modified=False, source_freshness_verified=False, physical_metric_verified=False,
                usable_for_ffb=False, published_to_ros=False,
                local_peer_route=dict(state='ok', rows=[dict(dst=remote['ipv4'], dev=local['interface'], prefsrc=local['ipv4'])]))
            result['outcome.json'] = dict(schema='network_bounded_udp_outcome_v1',
                state='process_completed_NEEDS_RESULT_REVIEW', returncode=0, actual_throughput_accepted=False,
                available_capacity_verified=False, usable_for_ffb=False)
            elapsed = 10. if sender else 10.04
            end = dict(sender=sender, start=0, end=elapsed, seconds=elapsed, bytes=6000000 if sender else 0,
                       bits_per_second=4800000 if sender else 0, packets=5000, lost_packets=0, lost_percent=0,
                       jitter_ms=.5)
            rows = []
            for start, stop in ((0, 5), (5, elapsed)):
                item = dict(sender=sender, omitted=False, start=start, end=stop, seconds=stop-start,
                            bytes=3000000, bits_per_second=3000000*8/(stop-start), packets=2500)
                if not sender:
                    item.update(lost_packets=0, lost_percent=0, jitter_ms=.5)
                rows.append(dict(streams=[copy.deepcopy(item)], sum=item))
            result['iperf.json'] = dict(start=dict(version='iperf 3.9', cookie='synthetic-not-authentication',
                connected=[dict(local_host=local['ipv4'], remote_host=remote['ipv4'],
                                local_port=40000 if sender else 5208, remote_port=5208 if sender else 40000)],
                test_start=dict(protocol='UDP', num_streams=1, blksize=1200, omit=0, duration=10,
                                bytes=0, blocks=0, reverse=0, tos=0)), intervals=rows,
                end=dict(streams=[dict(udp=copy.deepcopy(end))], sum=end))
        self.server['iperf.json']['start']['target_bitrate'] = 5000000
        self.sync()

    def sync(self):
        self.client['iperf.json']['server_output_json'] = copy.deepcopy(self.server['iperf.json'])

    def run_pair(self):
        return audit.paired(self.client, self.server, 'no-video', 5)

    def archive(self, extras=(), omitted=()):
        path = self.directory / 'submitted.tar.xz'
        with tarfile.open(path, 'w:xz') as target:
            for name in audit.probe.MEMBERS:
                if name in omitted:
                    continue
                raw = b'' if name == 'stderr.txt' else json.dumps(self.client[name]).encode()
                info = tarfile.TarInfo('network_bounded_udp/' + name)
                info.size = len(raw)
                info.pax_headers = dict(mtime='1.25')
                target.addfile(info, io.BytesIO(raw))
            for name, kind in extras:
                info = tarfile.TarInfo(name)
                info.type = kind
                target.addfile(info)
        return path

    def test_zero_end_summary_is_preserved_but_receiver_bytes_recomputed(self):
        result = self.run_pair()
        self.assertEqual(result['receiver_end_sum_raw']['bytes'], 0)
        self.assertTrue(result['receiver_summary_byte_discrepancy'])
        self.assertEqual(result['receiver_from_intervals']['bytes'], 6000000)
        self.assertAlmostEqual(result['receiver_from_intervals']['bits_per_second'], 6000000*8/10.04)
        self.assertFalse(result['maximum_capacity_measured'])
        self.assertFalse(result['cross_pc_clock_alignment_used'])
        self.assertFalse(result['usable_for_ffb'])

    def test_matching_nonzero_summary_is_also_audited_not_required_zero(self):
        for item in (self.server['iperf.json']['end']['sum'], self.server['iperf.json']['end']['streams'][0]['udp']):
            item['bytes'] = 6000000
            item['bits_per_second'] = 6000000*8/10.04
        self.sync()
        self.assertFalse(self.run_pair()['receiver_summary_byte_discrepancy'])

    def test_losses_are_reported_without_claiming_equal_payloads(self):
        row = self.server['iperf.json']['intervals'][0]
        for item in (row['sum'], row['streams'][0]):
            item.update(bytes=2998800, bits_per_second=2998800*8/5, lost_packets=1, lost_percent=.04)
        for item in (self.server['iperf.json']['end']['sum'], self.server['iperf.json']['end']['streams'][0]['udp']):
            item.update(lost_packets=1, lost_percent=.02)
        self.sync()
        result = self.run_pair()
        self.assertEqual(result['receiver_from_intervals']['lost_packets'], 1)
        self.assertEqual(result['receiver_payload_datagrams_from_bytes'], 4999)
        self.assertFalse(result['sender_and_receiver_payload_bytes_equal'])

    def test_embedded_and_separate_receiver_log_must_match(self):
        self.server['iperf.json']['end']['sum']['jitter_ms'] = .8
        with self.assertRaisesRegex(ValueError, 'embedded'):
            self.run_pair()

    def test_actual_peer_port_and_cookie_mismatch_rejected(self):
        original = copy.deepcopy(self.server)
        for field, value in (('remote_host', '192.0.2.77'), ('remote_port', 40001)):
            self.server = copy.deepcopy(original)
            self.server['iperf.json']['start']['connected'][0][field] = value
            self.sync()
            with self.assertRaises(ValueError):
                self.run_pair()
        self.server = copy.deepcopy(original)
        self.server['iperf.json']['start']['cookie'] = 'other-run'
        self.sync()
        with self.assertRaisesRegex(ValueError, 'cookie'):
            self.run_pair()

    def test_reverse_protocol_duration_and_stream_changes_rejected(self):
        for field, value in (('protocol', 'TCP'), ('reverse', 1), ('duration', 60), ('num_streams', 2)):
            original = copy.deepcopy(self.client)
            self.client['iperf.json']['start']['test_start'][field] = value
            with self.assertRaisesRegex(ValueError, 'actual protocol'):
                self.run_pair()
            self.client = original

    def test_old_source_wrong_condition_failed_outcome_and_authority_rejected(self):
        for field, value in (('probe_sha256', '0'*64), ('condition_operator_reported_NOT_verified', 'normal-video'),
                             ('usable_for_ffb', True), ('process_timeout_sec', 600)):
            original = copy.deepcopy(self.client)
            self.client['metadata.json'][field] = value
            with self.assertRaises(ValueError):
                self.run_pair()
            self.client = original
        self.client['outcome.json']['state'] = 'process_timeout'
        with self.assertRaises(ValueError):
            self.run_pair()

    def test_clock_gaps_rate_bytes_and_sender_role_changes_rejected(self):
        original = copy.deepcopy(self.server)
        for field, value in (('start', 1), ('bits_per_second', 0), ('bytes', 2999999), ('sender', True)):
            self.server = copy.deepcopy(original)
            self.server['iperf.json']['intervals'][0]['sum'][field] = value
            self.sync()
            with self.assertRaises(ValueError):
                self.run_pair()

    def test_end_loss_and_unexplained_total_changes_rejected(self):
        original = copy.deepcopy(self.server)
        for field, value in (('lost_packets', 3), ('bytes', 123456), ('bits_per_second', 2)):
            self.server = copy.deepcopy(original)
            self.server['iperf.json']['end']['sum'][field] = value
            self.sync()
            with self.assertRaises(ValueError):
                self.run_pair()

    def test_unbounded_rate_and_unknown_condition_rejected(self):
        for rate, condition in ((0, 'no-video'), (100, 'no-video'), (5, 'unknown')):
            with self.assertRaises(ValueError):
                audit.paired(self.client, self.server, condition, rate)

    def test_four_regular_pax_members_load_without_extraction(self):
        original, files, values = audit.archive(self.archive())
        self.assertTrue(original)
        self.assertEqual(set(files), set(audit.probe.MEMBERS))
        self.assertEqual(values['iperf.json'], self.client['iperf.json'])

    def test_unknown_duplicate_link_and_missing_members_rejected(self):
        for name, kind in (('../report.json', tarfile.REGTYPE),
                           ('network_bounded_udp/iperf.json', tarfile.REGTYPE),
                           ('network_bounded_udp/other', tarfile.SYMTYPE)):
            with self.assertRaises(ValueError):
                audit.archive(self.archive(extras=((name, kind),)))
        with self.assertRaises(ValueError):
            audit.archive(self.archive(omitted=('metadata.json',)))

    def test_duplicate_nonfinite_and_overflow_json_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]'):
            with self.assertRaises(ValueError):
                audit.parse(raw)


if __name__ == '__main__':
    unittest.main()
