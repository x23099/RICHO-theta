"""Audit paired operator-run UDP logs, v2: iperf 3.9 receiver-stream loss percent.

Version 1 (audit_udp.py) stays unchanged so previously saved audits remain
reproducible. The only behavioural difference is the receiver's per-stream
``lost_percent``: iperf 3.9 derives it from ``peer_packet_count`` (see
``iperf_print_summary`` in src/iperf_api.c of iperf 3.9), so a receiving
endpoint that has not received the sender's packet count yet reports 0 while
still reporting a non-zero ``lost_packets``. That value is kept raw and the
loss is taken from the receiver interval rows, which agree with ``end.sum``.
No submitted command is executed.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load('audit_udp', 'udp_audit_base')
require, near, number, integer, sha = base.require, base.near, base.number, base.integer, base.sha
parse, archive, intervals, probe, intake = base.parse, base.archive, base.intervals, base.probe, base.intake


def paired(client, server, condition, rate):
    require(condition in ('no-video', 'normal-video') and type(rate) is int and rate in (5, 25, 50),
            'explicit finite trial profile required')
    profile = parse((HERE / 'inventory_audit_r01/audit.json').read_bytes())['roles']
    for role, action, values in (('camera', 'client', client), ('gpu', 'server', server)):
        meta, outcome, log = (values[name] for name in ('metadata.json', 'outcome.json', 'iperf.json'))
        local, remote = profile[role], profile['gpu' if role == 'camera' else 'camera']
        require(meta['schema'] == 'network_bounded_udp_metadata_v1' and meta['action'] == action,
                'metadata role differs')
        require(meta['local_ipv4'] == local['ipv4'] and meta['interface'] == local['interface']
                and meta['peer_ipv4_operator_confirmed'] == remote['ipv4'], 'declared endpoints differ')
        require(meta['probe_sha256'] == sha((HERE / 'probe.py').read_bytes())
                and meta['collect_sha256'] == sha((HERE / 'collect.py').read_bytes()), 'source hash differs')
        for flag in ('server_enforces_client_rate', 'video_or_control_modified', 'source_freshness_verified',
                     'physical_metric_verified', 'usable_for_ffb', 'published_to_ros'):
            require(meta[flag] is False, 'metadata authority differs')
        require(meta['condition_operator_reported_NOT_verified'] == condition
                and meta['rate_mbps_client_requested'] == rate and meta['udp_seconds_client_requested'] == 10,
                'operator-reported test condition differs')
        command = meta['command']
        require(isinstance(command, list) and command and Path(command[0]).name == 'iperf3', 'iperf command required')
        expected, timeout = probe.command(command[0], action, local['ipv4'], remote['ipv4'], rate)
        require(command == expected and meta['process_timeout_sec'] == timeout, 'finite command differs')
        route, = meta['local_peer_route']['rows']
        require(meta['local_peer_route']['state'] == 'ok' and route['dst'] == remote['ipv4']
                and route['dev'] == local['interface'] and route['prefsrc'] == local['ipv4'], 'local route differs')
        require(outcome['schema'] == 'network_bounded_udp_outcome_v1'
                and outcome['state'] == 'process_completed_NEEDS_RESULT_REVIEW' and outcome['returncode'] == 0
                and all(outcome[k] is False for k in ('actual_throughput_accepted', 'available_capacity_verified', 'usable_for_ffb')),
                'trial did not complete or claims authority')
        require('error' not in log and log['start']['version'] == 'iperf 3.9', 'iperf error or unsupported JSON version')
        start = log['start']['test_start']
        expected_start = dict(protocol='UDP', num_streams=1, blksize=1200, omit=0, duration=10,
                              bytes=0, blocks=0, reverse=0, tos=0)
        require(start == expected_start, 'actual protocol/duration/stream parameters differ')
        connection, = log['start']['connected']
        require(connection['local_host'] == local['ipv4'] and connection['remote_host'] == remote['ipv4'],
                'actual connection peer differs')
    tx, rx = client['iperf.json'], server['iperf.json']
    tx_connection, = tx['start']['connected']
    rx_connection, = rx['start']['connected']
    require(tx_connection['remote_port'] == rx_connection['local_port'] == probe.PORT
            and tx_connection['local_port'] == rx_connection['remote_port'], 'actual UDP ports do not pair')
    require(isinstance(tx['start']['cookie'], str) and 0 < len(tx['start']['cookie']) <= 128
            and tx['start']['cookie'] == rx['start']['cookie'], 'iperf session cookies differ')
    require(tx['server_output_json'] == rx, 'embedded server output and separate server log differ')
    require(rx['start']['target_bitrate'] == rate * 1000000, 'negotiated target rate differs')
    sent, received = intervals(tx, True), intervals(rx, False)
    require(sent['packets'] > 0 and received['packets'] > 0, 'nonempty packet counts required')
    sent_stream, = tx['end']['streams']
    sent_end = sent_stream['udp']
    require(sent_end['sender'] is True and sent_end['bytes'] == sent['bytes']
            and sent_end['packets'] == sent['packets'] and near(sent_end['seconds'], sent['seconds'])
            and near(sent_end['bits_per_second'], sent['bits_per_second']), 'sender interval/end totals differ')
    rx_stream, = rx['end']['streams']
    require(rx_stream['udp']['sender'] is False and rx['end']['sum']['sender'] is False, 'receiver role differs')
    expected_lost_percent = 100 * received['lost_packets'] / received['packets']
    stream_loss_percent_unavailable = False
    for name, item in (('stream', rx_stream['udp']), ('sum', rx['end']['sum'])):
        for key in ('bytes', 'packets', 'lost_packets'):
            integer(item[key])
        require(item['packets'] == received['packets'] and item['lost_packets'] == received['lost_packets']
                and near(item['seconds'], received['seconds']), 'receiver interval/end counts differ')
        number(item['jitter_ms'])
        number(item['lost_percent'])
        if name == 'sum':
            require(near(item['lost_percent'], expected_lost_percent),
                    'receiver end loss percentage differs')
        elif received['lost_packets'] > 0 and item['lost_percent'] == 0:
            # iperf 3.9 per-stream value needs peer_packet_count; keep raw and flag it.
            stream_loss_percent_unavailable = True
        else:
            require(near(item['lost_percent'], expected_lost_percent),
                    'receiver stream loss percentage differs')
        # iperf 3.9 emits sender totals in UDP end JSON on a receiving server.
        # Keep that raw value, and independently aggregate actual receiver intervals.
        require(item['bytes'] in (0, received['bytes']), 'unexplained receiver end byte total')
        require((item['bits_per_second'] == 0 if item['bytes'] == 0 else
                 near(item['bits_per_second'], received['bits_per_second'])),
                'receiver end rate does not match its supported summary profile')
    require(sent['bytes'] > 0 and received['bytes'] > 0 and received['bytes'] <= sent['bytes'],
            'nonempty finite transfer required; duplicates need separate review')
    return dict(schema='paired_iperf39_udp_audit_v1', state='paired_trial_verified_NOT_capacity_or_video_acceptance',
                condition_operator_reported_NOT_verified=condition, target_mbps=rate,
                sender=sent, receiver_from_intervals=received,
                receiver_payload_datagrams_from_bytes=received['bytes'] // 1200,
                receiver_end_sum_raw=rx['end']['sum'],
                receiver_stream_raw=rx_stream['udp'],
                receiver_stream_loss_percent_unavailable=stream_loss_percent_unavailable,
                receiver_summary_byte_discrepancy=rx['end']['sum']['bytes'] != received['bytes'],
                receiver_last_reported_jitter_ms=rx['end']['sum']['jitter_ms'],
                sender_and_receiver_payload_bytes_equal=sent['bytes'] == received['bytes'],
                separate_and_embedded_server_output_identical=True, endpoints_ports_cookie_and_udp_profile_matched=True,
                cookies_are_not_authentication=True, cross_pc_clock_alignment_used=False,
                video_fps_or_freezes_measured=False, maximum_capacity_measured=False,
                source_freshness_verified=False, physical_metric_verified=False, usable_for_ffb=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--condition', choices=('no-video', 'normal-video'), required=True)
    parser.add_argument('--rate-mbps', type=int, choices=(5, 25, 50), required=True)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    raw_dir, output = args.raw_dir.resolve(), args.output_dir.resolve()
    require(not raw_dir.exists() and not output.exists() and raw_dir.is_relative_to(ROOT / 'recordings')
            and output.is_relative_to(HERE), 'unused raw/result paths required')
    loaded = {role: archive(path) for role, path in (('client', args.client), ('server', args.server))}
    result = paired(loaded['client'][2], loaded['server'][2], args.condition, args.rate_mbps)
    result['audit_script_sha256'] = sha(Path(__file__).read_bytes())
    result['base_audit_sha256'] = sha((HERE / 'audit_udp.py').read_bytes())
    result['archives'] = {}
    raw_dir.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    for role, (original, files, _) in loaded.items():
        directory = raw_dir / role
        directory.mkdir()
        with (directory / 'original.tar.xz').open('xb') as target:
            target.write(original)
        for name, data in files.items():
            with (directory / name).open('xb') as target:
                target.write(data)
        result['archives'][role] = dict(sha256=sha(original), files_sha256={k: sha(v) for k, v in files.items()})
    with (output / 'audit.json').open('x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
