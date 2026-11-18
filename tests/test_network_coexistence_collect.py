"""No sockets/hardware: network inventory and counter fixtures only."""
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'Experimental_results/2026-11-18/network_coexistence_r01/collect.py'
SPEC = importlib.util.spec_from_file_location('network_collect_test', SCRIPT)
collect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect)


class CollectionTests(unittest.TestCase):
    def test_peer_is_numeric_and_not_a_local_or_group_target(self):
        for value in ('localhost', 'example.org', '127.0.0.1', '0.0.0.0', '224.0.0.1',
                      '255.255.255.255', '::1', '1.2.3.4; echo unsafe'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                collect.peer_address(value)
        self.assertEqual(collect.peer_address('192.168.1.2'), '192.168.1.2')
        # Campus global addresses are not assumed to be invalid/private.
        self.assertEqual(collect.peer_address('150.89.169.70'), '150.89.169.70')

    def test_interface_path_injection_and_loopback_rejected(self):
        for name in ('../eth0', '/etc/passwd', 'lo', '', '..', 'a' * 16, 'eth0;id'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                collect.interface_name(name)
        self.assertEqual(collect.interface_name('enp1s0'), 'enp1s0')

    def test_missing_tool_is_reported_not_installed(self):
        with patch.object(collect.shutil, 'which', return_value=None), \
                patch.object(collect.subprocess, 'run') as run:
            self.assertEqual(collect.local_command('iperf3', ['--version']), {'state': 'not_installed'})
            run.assert_not_called()

    def test_local_command_uses_argv_timeout_and_no_shell(self):
        result = collect.subprocess.CompletedProcess([], 0, b'version', b'')
        with patch.object(collect.shutil, 'which', return_value='/usr/bin/iperf3'), \
                patch.object(collect.subprocess, 'run', return_value=result) as run:
            self.assertEqual(collect.local_command('iperf3', ['--version'])['state'], 'ok')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/iperf3', '--version'])
            self.assertEqual(run.call_args.kwargs['timeout'], 4)
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_command_error_and_excess_output(self):
        with patch.object(collect.shutil, 'which', return_value='/usr/bin/ip'):
            with patch.object(collect.subprocess, 'run', side_effect=collect.subprocess.TimeoutExpired('ip', 4)):
                self.assertEqual(collect.local_command('ip', [])['state'], 'failed')
            output = collect.subprocess.CompletedProcess([], 0, b'x' * (1024 * 1024 + 1), b'')
            with patch.object(collect.subprocess, 'run', return_value=output):
                self.assertEqual(collect.local_command('ip', [])['state'], 'output_too_large')

    def test_addresses_exclude_mac_ipv6_and_loopback(self):
        rows = [dict(ifname='lo', addr_info=[]),
                dict(ifname='eth0', address='secret-mac', addr_info=[
                    dict(family='inet', scope='global', local='192.168.1.2', prefixlen=24,
                         broadcast='192.168.1.255'),
                    dict(family='inet6', scope='global', local='2001:db8::1', prefixlen=64)])]
        with patch.object(collect, 'local_command', return_value=dict(state='ok', stdout=json.dumps(rows))):
            result = collect.addresses()
        self.assertEqual(result['rows'], [dict(interface='eth0', ipv4=[dict(local='192.168.1.2', prefixlen=24)])])

    def test_ip_unavailable_invalid_and_oversized_rows(self):
        for result, expected in ((dict(state='not_installed'), 'not_installed'),
                                 (dict(state='ok', stdout='not JSON'), 'invalid_output'),
                                 (dict(state='ok', stdout='{}'), 'invalid_output'),
                                 (dict(state='ok', stdout=json.dumps([{}] * 257)), 'invalid_output')):
            with patch.object(collect, 'local_command', return_value=result):
                self.assertEqual(collect.ip_rows([], ())['state'], expected)

    def test_local_permission_failure_is_preserved_not_fabricated(self):
        result = dict(state='failed', returncode=1, stdout='', stderr='Cannot open netlink socket: Operation not permitted')
        with patch.object(collect, 'local_command', return_value=result):
            value = collect.addresses()
        self.assertEqual(value['stderr'], result['stderr'])
        self.assertNotIn('rows', value)

    def test_inventory_calls_only_read_only_commands_and_filters_routes(self):
        calls = []
        def command(name, arguments):
            calls.append((name, arguments))
            if name == 'iperf3':
                return dict(state='ok', stdout='fixture', stderr='')
            if 'address' in arguments:
                return dict(state='ok', stdout='[]')
            return dict(state='ok', stdout=json.dumps([dict(dev='eth0', gateway='192.168.1.1',
                                                           prefsrc='192.168.1.2', uid=1000)]))
        with tempfile.TemporaryDirectory() as directory, patch.object(collect, 'SYS_NET', Path(directory)), \
                patch.object(collect, 'local_command', side_effect=command):
            result = collect.inventory('gpu', '192.168.1.3')
        self.assertEqual([args for name, args in calls if name == 'iperf3'], [['--version'], ['--help']])
        self.assertIn(('ip', ['-j', '-4', 'route', 'get', '192.168.1.3']), calls)
        self.assertNotIn('uid', result['peer_route_local_lookup_only']['rows'][0])
        self.assertFalse(result['active_probe_started'])
        self.assertFalse(result['usable_for_ffb'])

    def test_no_implicit_default_peer_lookup(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collect, 'SYS_NET', Path(directory)), \
                patch.object(collect, 'local_command', return_value=dict(state='not_installed')) as command:
            result = collect.inventory('camera')
        self.assertIsNone(result['peer_route_local_lookup_only'])
        self.assertFalse(any('get' in call.args[1] for call in command.call_args_list))

    def test_counter_fixture_and_unavailable_fields(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collect, 'SYS_NET', Path(directory)):
            base = Path(directory) / 'eth0/statistics'
            base.mkdir(parents=True)
            with self.assertRaises(ValueError):
                collect.counters('eth0')
            for name in ('rx_bytes', 'tx_bytes', 'rx_dropped', 'tx_dropped', 'rx_errors', 'tx_errors'):
                # Test fixtures only, never experiment or user data.
                (base / name).write_text('42\n')
            self.assertEqual(collect.counters('eth0')['rx_bytes'], 42)

    def passive(self, values, times, seconds=2):
        return collect.passive('eth0', seconds, 'normal-video',
                               read=lambda _: next(values), clock=lambda: next(times), sleep=lambda _: None)

    def test_passive_uses_actual_monotonic_intervals_and_total_traffic_labels(self):
        values = iter([dict(rx_bytes=0, tx_bytes=0), dict(rx_bytes=1000000, tx_bytes=2000000),
                       dict(rx_bytes=3000000, tx_bytes=6000000)])
        result = self.passive(values, iter([1000., 1001., 1003.]))
        self.assertEqual(result['elapsed_sec'], 3)
        self.assertEqual(result['rx_total_interface_mbps'], 8.)
        self.assertEqual(result['tx_total_interface_mbps'], 16.)
        self.assertFalse(result['available_capacity_measured'])
        self.assertFalse(result['video_fps_measured'])

    def test_counter_reset_clock_reversal_and_changed_schema_fail_closed(self):
        for values, times in (([dict(rx_bytes=5, tx_bytes=5), dict(rx_bytes=4, tx_bytes=6)], [1., 2.]),
                              ([dict(rx_bytes=0, tx_bytes=0)] * 2, [1., 1.]),
                              ([dict(rx_bytes=0, tx_bytes=0), dict(rx_bytes=1)], [1., 2.])):
            with self.assertRaises(ValueError):
                self.passive(iter(values), iter(times), seconds=1)

    def test_invalid_duration_or_condition_does_not_read_counters(self):
        for duration in (0, 61, True, 1.5):
            with self.assertRaises(ValueError):
                collect.passive('eth0', duration, 'normal-video', read=lambda _: self.fail('read'))
        with self.assertRaises(ValueError):
            collect.passive('eth0', 1, 'unknown', read=lambda _: self.fail('read'))

    def test_saved_archive_has_only_report_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'run'
            archive = collect.save(directory, dict(schema='fixture', **collect.LIMITATIONS))
            before = archive.read_bytes()
            with tarfile.open(archive) as bundle:
                self.assertEqual(bundle.getnames(), ['network_coexistence/report.json'])
                self.assertEqual(json.load(bundle.extractfile(bundle.getmembers()[0]))['schema'], 'fixture')
            with self.assertRaises(FileExistsError):
                collect.save(directory, {})
            self.assertEqual(archive.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
