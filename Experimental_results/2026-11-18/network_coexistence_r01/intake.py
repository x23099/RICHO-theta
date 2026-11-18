"""Strictly read the two submitted inventories; preserve originals without extraction."""
import argparse
import hashlib
import io
import ipaddress
import json
import lzma
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read(path, role):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('compressed inventory too large')
    original = path.read_bytes()
    decoder = lzma.LZMADecompressor(memlimit=64 * 1024 * 1024)
    unpacked = decoder.decompress(original, max_length=1024 * 1024 + 1)
    if len(unpacked) > 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError('expanded inventory exceeds profile or trailing stream')
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode='r:') as bundle:
        member = bundle.next()
        if (member is None or member.name != 'network_coexistence/report.json'
                or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                or not 0 < member.size <= 128 * 1024
                or set(member.pax_headers) - {'mtime', 'atime', 'ctime'}):
            raise ValueError('one regular inventory report required')
        raw = bundle.extractfile(member).read()
        if bundle.next() is not None:
            raise ValueError('extra archive member')
    def reject(_):
        raise ValueError('non-finite JSON')
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    # Inventories contain no fractional measurements; reject overflow too.
    json.dumps(value, allow_nan=False)
    if (value.get('schema') != 'network_coexistence_inventory_v1'
            or value.get('role_operator_reported_NOT_verified') != role):
        raise ValueError('inventory schema/role differs')
    for key in ('active_probe_started', 'video_or_control_modified', 'video_fps_measured',
                'available_capacity_measured', 'source_freshness_verified',
                'physical_metric_verified', 'usable_for_ffb', 'published_to_ros'):
        if value.get(key) is not False:
            raise ValueError('inventory authority/measurement flag differs')
    if value['addresses']['state'] != 'ok' or value['default_routes']['state'] != 'ok':
        raise ValueError('address and default-route inventory required')
    up = {item['interface'] for item in value['interfaces'] if item['operstate'] == 'up'}
    defaults = {item['dev'] for item in value['default_routes']['rows']}
    candidates = []
    for row in value['addresses']['rows']:
        if row['interface'] not in up & defaults:
            continue
        for address in row['ipv4']:
            interface = ipaddress.IPv4Interface(str(address['local']) + '/' + str(address['prefixlen']))
            candidates.append(dict(interface=row['interface'], ipv4=str(interface.ip),
                                   subnet=str(interface.network)))
    if len(candidates) != 1:
        raise ValueError('one unambiguous up/default IPv4 interface required for this submission')
    return original, raw, value, candidates[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=Path, required=True)
    parser.add_argument('--gpu', type=Path, required=True)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    raw_dir, output = args.raw_dir.resolve(), args.output_dir.resolve()
    if (raw_dir.exists() or output.exists() or not raw_dir.is_relative_to(ROOT / 'recordings')
            or not output.is_relative_to(HERE)):
        raise ValueError('unused raw recordings and local result paths required')
    loaded = {role: read(path, role) for role, path in (('camera', args.camera), ('gpu', args.gpu))}
    raw_dir.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    result = dict(schema='network_inventory_submission_audit_v1', state='inventory_verified_NOT_network_test',
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), roles={},
                  same_subnet=loaded['camera'][3]['subnet'] == loaded['gpu'][3]['subnet'],
                  explicit_peer_route_collected=False, peer_connectivity_verified=False,
                  available_capacity_measured=False, usable_for_ffb=False, active_test_started=False)
    for role, (original, raw, value, chosen) in loaded.items():
        with (raw_dir / (role + '.tar.xz')).open('xb') as target:
            target.write(original)
        with (raw_dir / (role + '_report.json')).open('xb') as target:
            target.write(raw)
        result['roles'][role] = dict(**chosen, iperf3_state=value['iperf3_version']['state'],
                                     archive_sha256=hashlib.sha256(original).hexdigest(),
                                     report_sha256=hashlib.sha256(raw).hexdigest())
    with (output / 'audit.json').open('x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
