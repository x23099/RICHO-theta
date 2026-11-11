"""Local comparison requests/status ONLY; never camera, driving, ROS or FFB."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

from cone_fixed_floor_live_load import bounded_regular_bytes
from driver_guarded_comparison import parse_json


def issue(directory, action):
    directory = Path(directory)
    if action not in ('pin', 'load', 'invalidate') or not directory.is_dir():
        raise ValueError('existing comparison directory and known action required')
    status = parse_json(bounded_regular_bytes(directory/'comparison_status.json', 16384))
    if status.get('writer_done') is not False:
        raise ValueError('comparison worker not running; do not recreate a retired session')
    previous = 0
    try:
        prior = parse_json(bounded_regular_bytes(directory/'request.json', 16384))
        previous = prior.get('request_id', 0)
        if type(previous) is not int:
            raise ValueError('invalid existing request id')
    except FileNotFoundError:
        pass
    request = dict(schema='driver_guarded_request_v1',
        request_id=max(time.time_ns(), previous+1), action=action)
    if request['request_id'] >= 2**63:
        raise ValueError('request id exhausted')
    temporary = directory/('request.'+uuid.uuid4().hex+'.part')
    with temporary.open('xb') as stream:
        stream.write((json.dumps(request)+'\n').encode())
    os.replace(temporary, directory/'request.json')
    return request


def status(directory):
    value = parse_json(bounded_regular_bytes(Path(directory)/'comparison_status.json', 16384))
    row = value.get('latest')
    now = time.monotonic()
    if (value.get('writer_done') is not False or row is None
            or not 0 <= now-value.get('status_time_sec', -1) <= 2.
            or not 0 <= now-row.get('source_time_sec', -1) <= .5):
        value['latest'] = None
        value['consumer_note'] = 'NO current comparison value; historical rows remain in JSONL'
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('action', choices=('pin', 'load', 'invalidate', 'status'))
    args = parser.parse_args(argv)
    try:
        result = status(args.directory) if args.action == 'status' else issue(args.directory, args.action)
    except Exception as error:
        print(f'[ERROR] comparison only: {type(error).__name__}: {error}')
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
