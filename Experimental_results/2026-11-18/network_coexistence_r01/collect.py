"""Read-only network inventory / passive NIC counters; no traffic generator."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

SYS_NET = Path('/sys/class/net')
LIMITATIONS = {
    'active_probe_started': False,
    'video_or_control_modified': False,
    'video_fps_measured': False,
    'available_capacity_measured': False,
    'source_freshness_verified': False,
    'physical_metric_verified': False,
    'usable_for_ffb': False,
    'published_to_ros': False,
}


def peer_address(value):
    address = ipaddress.IPv4Address(value)
    if (address.is_unspecified or address.is_loopback or address.is_multicast
            or int(address) == 0xffffffff):
        raise ValueError('an explicitly identified remote IPv4 address is required')
    return str(address)


def interface_name(value):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', value) or value in ('.', '..', 'lo'):
        raise ValueError('non-loopback Linux interface name required')
    return value


def local_command(name, arguments):
    """Only internal callers supply arguments: never a shell, network client or server."""
    executable = shutil.which(name)
    if executable is None:
        return {'state': 'not_installed'}
    try:
        result = subprocess.run([executable, *arguments], capture_output=True,
                                timeout=4, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'state': 'failed', 'error_type': type(error).__name__}
    if len(result.stdout) + len(result.stderr) > 1024 * 1024:
        return {'state': 'output_too_large'}
    return {'state': 'ok' if result.returncode == 0 else 'failed',
            'returncode': result.returncode,
            'stdout': result.stdout.decode('utf-8', errors='replace'),
            'stderr': result.stderr.decode('utf-8', errors='replace')}


def ip_rows(arguments, keys):
    result = local_command('ip', ['-j', '-4', *arguments])
    if result['state'] != 'ok':
        return {key: result[key] for key in ('state', 'returncode', 'stderr', 'error_type') if key in result}
    try:
        rows = json.loads(result['stdout'])
        if not isinstance(rows, list) or len(rows) > 256:
            raise ValueError('bounded list required')
        return {'state': 'ok', 'rows': [{k: row[k] for k in keys if k in row}
                                       for row in rows]}
    except (ValueError, TypeError, KeyError):
        return {'state': 'invalid_output'}


def addresses():
    result = ip_rows(['address', 'show'], ('ifname', 'addr_info'))
    if result['state'] != 'ok':
        return result
    filtered = []
    try:
        for row in result['rows']:
            if row['ifname'] == 'lo':
                continue
            entries = [{'local': item['local'], 'prefixlen': item['prefixlen']}
                       for item in row.get('addr_info', [])
                       if item.get('family') == 'inet' and item.get('scope') == 'global']
            filtered.append({'interface': row['ifname'], 'ipv4': entries})
    except (TypeError, KeyError):
        return {'state': 'invalid_output'}
    return {'state': 'ok', 'rows': filtered}


def text_file(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def counters(interface):
    directory = SYS_NET / interface_name(interface) / 'statistics'
    result = {}
    for name in ('rx_bytes', 'tx_bytes', 'rx_dropped', 'tx_dropped', 'rx_errors', 'tx_errors'):
        value = text_file(directory / name)
        if value is None or not value.isdecimal():
            raise ValueError('interface counters unavailable: ' + interface)
        result[name] = int(value)
    return result


def inventory(role, peer=None):
    if peer is not None:
        peer = peer_address(peer)
    interfaces = []
    names = sorted(p.name for p in SYS_NET.iterdir())
    if len(names) > 64:
        raise ValueError('too many interfaces; inspect manually')
    for name in names:
        if name == 'lo':
            continue
        directory = SYS_NET / interface_name(name)
        interfaces.append({'interface': name, 'operstate': text_file(directory / 'operstate'),
                           'nominal_link_speed_mbps_NOT_available_capacity': text_file(directory / 'speed')})
    iperf = local_command('iperf3', ['--version'])
    help_result = local_command('iperf3', ['--help']) if iperf['state'] == 'ok' else None
    return {
        'schema': 'network_coexistence_inventory_v1', 'role_operator_reported_NOT_verified': role,
        'addresses': addresses(), 'interfaces': interfaces,
        'default_routes': ip_rows(['route', 'show', 'default'], ('dst', 'gateway', 'dev', 'prefsrc', 'metric')),
        'peer_ipv4_operator_supplied_NOT_verified': peer,
        'peer_route_local_lookup_only': (ip_rows(['route', 'get', peer], ('dst', 'gateway', 'dev', 'prefsrc'))
                                         if peer else None),
        'iperf3_version': iperf, 'iperf3_help': help_result,
        'note': 'No camera, ROS, remote connection, listener, ping, throughput test, install or clock synchronization. ip uses local kernel netlink queries.',
        **LIMITATIONS,
    }


def passive(interface, seconds, condition, *, read=counters, clock=time.monotonic, sleep=time.sleep):
    interface_name(interface)
    if type(seconds) is not int or not 1 <= seconds <= 60:
        raise ValueError('duration must be an integer in 1..60 seconds')
    if condition not in ('no-video', 'normal-video'):
        raise ValueError('explicit operator-reported video condition required')
    start = clock()
    previous_time, previous = start, read(interface)
    samples = []
    initial = previous.copy()
    for _ in range(seconds):
        sleep(1)
        current_time, current = clock(), read(interface)
        elapsed = current_time - previous_time
        if elapsed <= 0 or current.keys() != previous.keys():
            raise ValueError('clock/counter schema changed')
        delta = {k: current[k] - previous[k] for k in previous}
        if any(value < 0 for value in delta.values()):
            raise ValueError('counter reset/interface changed; no valid comparison')
        samples.append({'elapsed_sec': current_time - start, 'interval_sec': elapsed,
                        'delta': delta, 'rx_total_interface_mbps': delta['rx_bytes'] * 8 / elapsed / 1e6,
                        'tx_total_interface_mbps': delta['tx_bytes'] * 8 / elapsed / 1e6})
        previous_time, previous = current_time, current
    elapsed = previous_time - start
    return {'schema': 'network_coexistence_passive_v1', 'interface': interface,
            'condition_operator_reported_NOT_verified': condition, 'requested_seconds': seconds,
            'elapsed_sec': elapsed, 'samples': samples,
            'rx_total_interface_mbps': (previous['rx_bytes'] - initial['rx_bytes']) * 8 / elapsed / 1e6,
            'tx_total_interface_mbps': (previous['tx_bytes'] - initial['tx_bytes']) * 8 / elapsed / 1e6,
            'note': 'All interface traffic, not video-only bitrate, free capacity, fps or packet-path latency.',
            **LIMITATIONS}


def save(directory, value):
    directory = Path(directory)
    # Exclusive creation: failed or previous runs must not be overwritten.
    directory.mkdir(parents=True, exist_ok=False)
    report = directory / 'report.json'
    with report.open('x', encoding='utf-8') as target:
        json.dump(value, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write('\n')
    archive = directory / 'submission.tar.xz'
    with tarfile.open(archive, 'x:xz') as target:
        target.add(report, arcname='network_coexistence/report.json', recursive=False)
    return archive.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    inspect = commands.add_parser('inspect', help='local read-only inventory; no test traffic')
    inspect.add_argument('--role', required=True, choices=('gpu', 'camera', 'analysis'))
    inspect.add_argument('--peer', help='optional known peer IPv4; local route lookup only')
    observe = commands.add_parser('observe', help='passive total interface counters, 1..60 seconds')
    observe.add_argument('--interface', required=True)
    observe.add_argument('--seconds', type=int, default=30)
    observe.add_argument('--condition', choices=('no-video', 'normal-video'), required=True)
    for command in (inspect, observe):
        command.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or args.output_dir.is_symlink():
        parser.error('output directory already exists; use a new run name')
    try:
        result = (inventory(args.role, args.peer) if args.action == 'inspect'
                  else passive(args.interface, args.seconds, args.condition))
        archive = save(args.output_dir, result)
    except (OSError, ValueError) as error:
        parser.exit(1, 'ERROR: ' + str(error) + '\n')
    print('Saved: ' + str(archive))
    print('No active network test or video/control change performed.')


if __name__ == '__main__':
    main()
