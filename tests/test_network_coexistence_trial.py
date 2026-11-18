"""Synthetic archives and mocked subprocesses only; never starts iperf/socket."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'Experimental_results/2026-11-18/network_coexistence_r01'


def module(name):
    spec = importlib.util.spec_from_file_location('network_trial_test_' + name, HERE / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


intake, probe = module('intake'), module('probe')


class TrialTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.value = dict(schema='network_coexistence_inventory_v1', role_operator_reported_NOT_verified='camera',
                          addresses=dict(state='ok', rows=[dict(interface='wlo1', ipv4=[dict(local='192.168.1.2', prefixlen=24)])]),
                          interfaces=[dict(interface='wlo1', operstate='up')],
                          default_routes=dict(state='ok', rows=[dict(dev='wlo1')]),
                          iperf3_version=dict(state='not_installed'), **probe.collect.LIMITATIONS)
        self.route = dict(state='ok', rows=[dict(dev='wlo1', prefsrc='192.168.1.2')])

    def archive(self, value=None, names=('network_coexistence/report.json',), kind=tarfile.REGTYPE, raw=None):
        path = self.directory / 'inventory.tar.xz'
        data = json.dumps(self.value if value is None else value).encode() if raw is None else raw
        with tarfile.open(path, 'w:xz') as target:
            for name in names:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.size = len(data) if kind == tarfile.REGTYPE else 0
                member.pax_headers = {'mtime': '1.234'}
                target.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        return path

    def test_inventory_regular_pax_report_and_single_active_default(self):
        path = self.archive()
        original, raw, value, chosen = intake.read(path, 'camera')
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(json.loads(raw), self.value)
        self.assertEqual(chosen, dict(interface='wlo1', ipv4='192.168.1.2', subnet='192.168.1.0/24'))

    def test_archive_path_links_extras_duplicates_rejected(self):
        for names, kind in ((('../report.json',), tarfile.REGTYPE),
                            (('/network_coexistence/report.json',), tarfile.REGTYPE),
                            (('network_coexistence/report.json',), tarfile.SYMTYPE),
                            (('network_coexistence/report.json', 'instructions.txt'), tarfile.REGTYPE),
                            (('network_coexistence/report.json',) * 2, tarfile.REGTYPE)):
            with self.subTest(names=names, kind=kind), self.assertRaises(ValueError):
                intake.read(self.archive(names=names, kind=kind), 'camera')

    def test_compressed_and_expanded_size_limits(self):
        path = self.directory / 'big.tar.xz'
        path.write_bytes(b'x' * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, 'compressed'):
            intake.read(path, 'camera')
        with self.assertRaisesRegex(ValueError, 'expanded'):
            intake.read(self.archive(raw=b' ' * (1024 * 1024 + 1)), 'camera')

    def test_trailing_xz_stream_rejected(self):
        path = self.archive()
        path.write_bytes(path.read_bytes() + path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'trailing'):
            intake.read(path, 'camera')

    def test_roles_authority_and_incomplete_inventory_rejected(self):
        for field, value in (('role_operator_reported_NOT_verified', 'gpu'), ('schema', 'instruction'),
                             ('usable_for_ffb', True), ('active_probe_started', 0)):
            bad = copy.deepcopy(self.value)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                intake.read(self.archive(bad), 'camera')
        bad = copy.deepcopy(self.value)
        bad['addresses']['state'] = 'failed'
        with self.assertRaises(ValueError):
            intake.read(self.archive(bad), 'camera')

    def test_duplicate_nonfinite_and_overflow_json_rejected(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                intake.read(self.archive(raw=raw), 'camera')

    def test_ambiguous_default_not_guessed(self):
        bad = copy.deepcopy(self.value)
        bad['addresses']['rows'][0]['ipv4'].append(dict(local='192.168.1.3', prefixlen=24))
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            intake.read(self.archive(bad), 'camera')

    def test_client_is_one_finite_capped_udp_stream_not_reverse(self):
        command, timeout = probe.command('/usr/bin/iperf3', 'client', '192.168.1.2', '192.168.1.3', 5)
        for flag, value in (('-b', '5M'), ('-t', '10'), ('-P', '1'), ('-l', '1200'),
                            ('-B', '192.168.1.2'), ('-c', '192.168.1.3'), ('-p', '5208'),
                            ('--connect-timeout', '3000')):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn('-u', command)
        self.assertNotIn('-R', command)
        self.assertEqual(timeout, 25)

    def test_server_one_off_exact_bind_and_finite_timeout(self):
        command, timeout = probe.command('/usr/bin/iperf3', 'server', '192.168.1.3', '192.168.1.2', 5)
        self.assertIn('-s', command)
        self.assertIn('-1', command)
        self.assertNotIn('-D', command)
        self.assertEqual(command[command.index('-B') + 1], '192.168.1.3')
        self.assertEqual(timeout, 45)

    def test_unlimited_unknown_rate_and_action_rejected(self):
        for action, rate in (('client', 0), ('client', 100), ('client', True), ('scan', 5)):
            with self.assertRaises(ValueError):
                probe.command('iperf3', action, '192.168.1.2', '192.168.1.3', rate)

    def test_actual_local_address_and_peer_route_checked_before_traffic(self):
        with patch.object(probe.collect, 'addresses', return_value=self.value['addresses']), \
                patch.object(probe.collect, 'ip_rows', return_value=self.route) as lookup:
            self.assertEqual(probe.checked_addresses('192.168.1.2', '192.168.1.3', 'wlo1'), self.route)
            self.assertEqual(lookup.call_args.args[0], ['route', 'get', '192.168.1.3'])

    def test_wrong_local_peer_scope_source_interface_and_broadcast_route_rejected(self):
        with patch.object(probe.collect, 'addresses', return_value=self.value['addresses']):
            for route in (dict(state='failed'), dict(state='ok', rows=[]),
                          dict(state='ok', rows=[dict(dev='other', prefsrc='192.168.1.2')]),
                          dict(state='ok', rows=[dict(dev='wlo1', prefsrc='192.168.1.9')]),
                          dict(state='ok', rows=[dict(dev='wlo1', prefsrc='192.168.1.2', type='broadcast')])):
                with patch.object(probe.collect, 'ip_rows', return_value=route), self.assertRaises(ValueError):
                    probe.checked_addresses('192.168.1.2', '192.168.1.3', 'wlo1')
            with self.assertRaises(ValueError):
                probe.checked_addresses('192.168.1.9', '192.168.1.3', 'wlo1')
            with self.assertRaises(ValueError):
                probe.checked_addresses('192.168.1.2', '192.168.1.2', 'wlo1')

    def trial(self, path, run):
        help_text = '--one-off --bind --json --udp --bitrate --connect-timeout --get-server-output'
        with patch.object(probe.shutil, 'which', return_value='/usr/bin/iperf3'), \
                patch.object(probe, 'checked_addresses', return_value=self.route), \
                patch.object(probe.collect, 'local_command', return_value=dict(state='ok', stdout=help_text)), \
                patch.object(probe.subprocess, 'run', side_effect=run):
            return probe.trial('client', '192.168.1.2', '192.168.1.3', 'wlo1', 5, 'no-video', path, True)

    def test_success_keeps_raw_logs_metadata_and_unaccepted_outcome(self):
        def run(argv, **kwargs):
            kwargs['stdout'].write(b'{"synthetic":true}\n')
            self.assertEqual(kwargs['timeout'], 25)
            return subprocess.CompletedProcess(argv, 0)
        directory = self.directory / 'run'
        state = self.trial(directory, run)
        self.assertEqual(state, 'process_completed_NEEDS_RESULT_REVIEW')
        outcome = json.loads((directory / 'outcome.json').read_bytes())
        self.assertFalse(outcome['actual_throughput_accepted'])
        self.assertFalse(outcome['usable_for_ffb'])
        with tarfile.open(directory / 'submission.tar.xz') as archive:
            self.assertEqual(archive.getnames(), ['network_bounded_udp/' + name for name in probe.MEMBERS])

    def test_timeout_and_interrupt_preserve_failure_not_measurement_success(self):
        for index, error in enumerate((subprocess.TimeoutExpired('iperf3', 25), KeyboardInterrupt())):
            directory = self.directory / str(index)
            state = self.trial(directory, error)
            self.assertIn(state, ('process_timeout', 'operator_interrupted'))
            self.assertTrue((directory / 'submission.tar.xz').exists())

    def test_confirmation_invalid_condition_and_existing_output_do_not_connect(self):
        with patch.object(probe.subprocess, 'run') as run:
            for confirmed, condition, output in ((False, 'no-video', self.directory / 'a'),
                                                  (True, 'unknown', self.directory / 'a'),
                                                  (True, 'no-video', self.directory)):
                with self.assertRaises(ValueError):
                    probe.trial('client', '192.168.1.2', '192.168.1.3', 'wlo1', 5, condition, output, confirmed)
            run.assert_not_called()

    def test_no_install_or_fallback_when_iperf_absent(self):
        with patch.object(probe.shutil, 'which', return_value=None), \
                patch.object(probe.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'not installed'):
            probe.trial('client', '192.168.1.2', '192.168.1.3', 'wlo1', 5, 'no-video', self.directory / 'a', True)
        run.assert_not_called()

    def test_old_unsupported_help_stops_before_probe(self):
        with patch.object(probe.shutil, 'which', return_value='/usr/bin/iperf3'), \
                patch.object(probe, 'checked_addresses', return_value=self.route), \
                patch.object(probe.collect, 'local_command', return_value=dict(state='ok', stdout='old help')), \
                patch.object(probe.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'lacks required'):
            probe.trial('client', '192.168.1.2', '192.168.1.3', 'wlo1', 5, 'no-video', self.directory / 'a', True)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
