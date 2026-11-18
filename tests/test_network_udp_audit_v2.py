"""Synthetic iperf3.9 fixtures for audit_udp_v2; no actual packets, clocks or GPU."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'Experimental_results/2026-11-18/network_coexistence_r01'


def load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('audit_udp_v2', 'network_udp_audit_v2_test')
base = load('audit_udp', 'network_udp_audit_v1_base')


class UdpAuditV2Tests(unittest.TestCase):
    def setUp(self):
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

    def introduce_loss(self):
        row = self.server['iperf.json']['intervals'][0]
        for item in (row['sum'], row['streams'][0]):
            item.update(bytes=2998800, bits_per_second=2998800*8/5, lost_packets=1, lost_percent=.04)
        for item in (self.server['iperf.json']['end']['sum'],
                     self.server['iperf.json']['end']['streams'][0]['udp']):
            item.update(lost_packets=1, lost_percent=.02)
        self.sync()

    def test_receiver_stream_zero_loss_percent_is_kept_raw_and_flagged(self):
        self.introduce_loss()
        stream = self.server['iperf.json']['end']['streams'][0]['udp']
        stream['lost_percent'] = 0
        self.sync()
        result = self.run_pair()
        self.assertTrue(result['receiver_stream_loss_percent_unavailable'])
        self.assertEqual(result['receiver_stream_raw']['lost_percent'], 0)
        self.assertEqual(result['receiver_end_sum_raw']['lost_percent'], .02)
        self.assertEqual(result['receiver_from_intervals']['lost_packets'], 1)
        self.assertFalse(result['sender_and_receiver_payload_bytes_equal'])

    def test_matching_receiver_stream_loss_percent_is_not_flagged(self):
        self.introduce_loss()
        self.assertFalse(self.run_pair()['receiver_stream_loss_percent_unavailable'])

    def test_receiver_sum_loss_percent_must_still_match_intervals(self):
        self.introduce_loss()
        self.server['iperf.json']['end']['sum']['lost_percent'] = 0
        self.sync()
        with self.assertRaisesRegex(ValueError, 'end loss percentage'):
            self.run_pair()

    def test_wrong_nonzero_receiver_stream_loss_percent_rejected(self):
        self.introduce_loss()
        self.server['iperf.json']['end']['streams'][0]['udp']['lost_percent'] = .5
        self.sync()
        with self.assertRaisesRegex(ValueError, 'stream loss percentage'):
            self.run_pair()

    def test_version_one_still_rejects_the_zero_stream_percentage(self):
        self.introduce_loss()
        self.server['iperf.json']['end']['streams'][0]['udp']['lost_percent'] = 0
        self.sync()
        loaded = {role: (None, None, value) for role, value in (('camera', self.client), ('gpu', self.server))}
        with self.assertRaisesRegex(ValueError, 'end loss percentage'):
            base.paired(loaded['camera'][2], loaded['gpu'][2], 'no-video', 5)

    def test_unchanged_acceptance_flags(self):
        result = self.run_pair()
        self.assertFalse(result['maximum_capacity_measured'])
        self.assertFalse(result['cross_pc_clock_alignment_used'])
        self.assertFalse(result['usable_for_ffb'])
        self.assertFalse(result['video_fps_or_freezes_measured'])


if __name__ == '__main__':
    unittest.main()
