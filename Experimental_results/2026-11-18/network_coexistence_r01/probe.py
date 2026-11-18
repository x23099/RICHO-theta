"""Explicit operator-run finite iperf3 UDP trial. Not a live video/control hook."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('network_passive_helpers', HERE / 'collect.py')
collect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect)
PORT = 5208
MEMBERS = ('metadata.json', 'iperf.json', 'stderr.txt', 'outcome.json')


def checked_addresses(local, peer, interface):
    local, peer = collect.peer_address(local), collect.peer_address(peer)
    interface = collect.interface_name(interface)
    if local == peer:
        raise ValueError('local and peer must be different PCs')
    addresses = collect.addresses()
    if addresses['state'] != 'ok' or not any(
            row['interface'] == interface and any(a['local'] == local for a in row['ipv4'])
            for row in addresses['rows']):
        raise ValueError('specified local IPv4 is not assigned to the specified interface; inspect again')
    route = collect.ip_rows(['route', 'get', peer], ('dst', 'gateway', 'dev', 'prefsrc', 'type'))
    if (route['state'] != 'ok' or len(route['rows']) != 1
            or route['rows'][0].get('dev') != interface
            or route['rows'][0].get('prefsrc') != local
            or route['rows'][0].get('type', 'unicast') != 'unicast'):
        raise ValueError('peer route/source differs; no network trial started')
    return route


def command(executable, action, local, peer, rate):
    if action not in ('server', 'client') or type(rate) is not int or rate not in (5, 25, 50):
        raise ValueError('explicit single finite trial required')
    local, peer = collect.peer_address(local), collect.peer_address(peer)
    base = [executable, '-4', '-B', local, '-p', str(PORT), '-J']
    if action == 'server':
        return [*base, '-s', '-1'], 45
    return [*base, '-c', peer, '-u', '-b', str(rate) + 'M', '-l', '1200',
            '-P', '1', '-t', '10', '--connect-timeout', '3000', '--get-server-output'], 25


def write_json(path, value):
    with path.open('x') as target:
        json.dump(value, target, indent=2, allow_nan=False)
        target.write('\n')


def trial(action, local, peer, interface, rate, condition, output, confirmed):
    output = Path(output)
    if not confirmed:
        raise ValueError('explicit confirmation that both endpoints are your test PCs is required')
    if condition not in ('no-video', 'normal-video'):
        raise ValueError('explicit video condition required')
    if output.exists() or output.is_symlink():
        raise ValueError('output already exists; use a new run name')
    executable = shutil.which('iperf3')
    if executable is None:
        raise ValueError('iperf3 is not installed; no trial started')
    argv, timeout = command(executable, action, local, peer, rate)
    route = checked_addresses(local, peer, interface)
    version = collect.local_command('iperf3', ['--version'])
    help_result = collect.local_command('iperf3', ['--help'])
    required = ('--one-off', '--bind', '--json') if action == 'server' else (
        '--udp', '--bitrate', '--connect-timeout', '--get-server-output')
    help_text = help_result.get('stdout', '') + help_result.get('stderr', '')
    if version['state'] != 'ok' or help_result['state'] != 'ok' or any(s not in help_text for s in required):
        raise ValueError('iperf3 version/help lacks required options; no trial started')
    metadata = dict(schema='network_bounded_udp_metadata_v1', action=action, command=argv,
                    process_timeout_sec=timeout, local_ipv4=local, peer_ipv4_operator_confirmed=peer,
                    interface=interface, local_peer_route=route, rate_mbps_client_requested=rate,
                    server_enforces_client_rate=False, udp_seconds_client_requested=10,
                    condition_operator_reported_NOT_verified=condition, iperf3_version=version,
                    probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    collect_sha256=hashlib.sha256((HERE / 'collect.py').read_bytes()).hexdigest(),
                    video_or_control_modified=False, source_freshness_verified=False,
                    physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'metadata.json', metadata)
    message = ('Waiting up to 45 seconds for ONE client on ' + local if action == 'server'
               else 'Sending a finite UDP test to ' + peer)
    print(message, flush=True)
    code, state = None, 'not_started'
    with (output / 'iperf.json').open('xb') as stdout, (output / 'stderr.txt').open('xb') as stderr:
        try:
            process = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
            code = process.returncode
            state = 'process_completed_NEEDS_RESULT_REVIEW' if code == 0 else 'process_failed'
        except subprocess.TimeoutExpired:
            state = 'process_timeout'
        except KeyboardInterrupt:
            state = 'operator_interrupted'
        except OSError as error:
            state = 'start_failed_' + type(error).__name__
    write_json(output / 'outcome.json', dict(schema='network_bounded_udp_outcome_v1', state=state,
                                            returncode=code, actual_throughput_accepted=False,
                                            available_capacity_verified=False, usable_for_ffb=False))
    archive = output / 'submission.tar.xz'
    with tarfile.open(archive, 'x:xz') as target:
        for name in MEMBERS:
            target.add(output / name, arcname='network_bounded_udp/' + name, recursive=False)
    print('State: ' + state)
    print('Saved: ' + str(archive.resolve()))
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('server', 'client'))
    parser.add_argument('--local-ip', required=True)
    parser.add_argument('--peer', required=True)
    parser.add_argument('--interface', required=True)
    parser.add_argument('--rate-mbps', type=int, choices=(5, 25, 50), default=5)
    parser.add_argument('--condition', choices=('no-video', 'normal-video'), required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--confirm-owned-peers', action='store_true')
    args = parser.parse_args()
    try:
        state = trial(args.action, args.local_ip, args.peer, args.interface, args.rate_mbps,
                      args.condition, args.output_dir, args.confirm_owned_peers)
    except (OSError, ValueError) as error:
        parser.exit(1, 'ERROR: ' + str(error) + '\n')
    if state != 'process_completed_NEEDS_RESULT_REVIEW':
        parser.exit(1)


if __name__ == '__main__':
    main()
