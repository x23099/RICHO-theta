"""Reproduce the 2026-11-18 daily-report tables and figures from saved audits."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
NET = ROOT / 'Experimental_results/2026-11-18/network_coexistence_r01'
PROBE = ROOT / 'Experimental_results/2026-11-18/png_link_probe_r01'

RUNS = [
    ('5 Mbps', 'no-video', NET / 'udp_idle5_audit_r02/audit.json'),
    ('5 Mbps', 'no-video (declared normal-video)', NET / 'udp_video5_audit_r01/audit.json'),
    ('25 Mbps', 'no-video (declared normal-video)', NET / 'udp_video25_audit_r01/audit.json'),
    ('25 Mbps', 'normal-video', NET / 'udp_video25_audit_r02/audit.json'),
    ('50 Mbps', 'normal-video', NET / 'udp_video50_audit_r01/audit.json'),
    ('50 Mbps', 'normal-video', NET / 'udp_video50_audit_r02/audit.json'),
]


def network():
    rows = []
    for rate, condition, path in RUNS:
        value = json.loads(path.read_bytes())
        sent, received = value['sender'], value['receiver_from_intervals']
        rows.append(dict(rate=rate, actual_condition=condition,
                         target_mbps=value['target_mbps'],
                         sender_mbps=round(sent['bits_per_second'] / 1e6, 6),
                         receiver_mbps=round(received['bits_per_second'] / 1e6, 6),
                         sent_bytes=sent['bytes'], received_bytes=received['bytes'],
                         packets=received['packets'], lost=received['lost_packets'],
                         lost_percent=round(100 * received['lost_packets'] / received['packets'], 6),
                         payload_equal=value['sender_and_receiver_payload_bytes_equal'],
                         source=str(path.relative_to(ROOT))))
    with (HERE / 'network_coexistence_rates.csv').open('w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def probe():
    value = json.loads((PROBE / 'transport_audit_r01/audit.json').read_bytes())
    keys = ['frames_offered', 'frames_expired_before_send', 'frames_handed_off',
            'fragments_generated', 'fragments_per_frame', 'payload_bytes_upper_bound',
            'sender_effective_hz', 'receiver_published_hz', 'receiver_frames_completed',
            'receiver_frames_published', 'receiver_packets_replaced_before_completion',
            'delivery_latency_min_sec', 'delivery_latency_mean_sec', 'delivery_latency_max_sec']
    row = {key: value[key] for key in keys}
    row['frame_completion_ratio'] = value['frame_completion_ratio']
    row['frame_publication_ratio'] = value['frame_publication_ratio']
    with (HERE / 'png_transport_probe_r01.csv').open('w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return value


def figures(rows, value):
    labels = [r['rate'] + '\n' + r['actual_condition'].split(' (')[0] for r in rows]
    colors = ['#2b6cb0' if 'declared' not in r['actual_condition'] else '#a0aec0' for r in rows]
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].bar(range(len(rows)), [r['lost_percent'] for r in rows], color=colors)
    axes[0].set_ylabel('lost datagrams (%)')
    axes[0].set_title('UDP probe loss by condition' if False else 'UDP probe loss')
    axes[0].set_xticks(range(len(rows)))
    axes[0].set_xticklabels(labels, fontsize=7, rotation=30, ha='right')
    axes[0].grid(axis='y', alpha=.3)
    for index, row in enumerate(rows):
        axes[0].text(index, row['lost_percent'], f"{row['lost_percent']:.3f}",
                     ha='center', va='bottom', fontsize=7)
    axes[1].bar(range(len(rows)), [r['receiver_mbps'] for r in rows], color=colors)
    axes[1].set_ylabel('received payload (Mbps)')
    axes[1].set_title('Received interval rate')
    axes[1].set_xticks(range(len(rows)))
    axes[1].set_xticklabels(labels, fontsize=7, rotation=30, ha='right')
    axes[1].grid(axis='y', alpha=.3)
    figure.tight_layout()
    figure.savefig(HERE / 'network_coexistence_rates.png', dpi=130)
    plt.close(figure)

    figure, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    axes[0].bar(['handed off', 'completed', 'published'],
                [value['frames_handed_off'], value['receiver_frames_completed'],
                 value['receiver_frames_published']], color=['#2b6cb0', '#38a169', '#805ad5'])
    axes[0].set_ylim(0, max(1, value['frames_handed_off']) * 1.15)
    axes[0].set_title('PNG frames (real SCTP path)')
    for index, count in enumerate([value['frames_handed_off'], value['receiver_frames_completed'],
                                   value['receiver_frames_published']]):
        axes[0].text(index, count, str(count), ha='center', va='bottom', fontsize=8)
    upper = value['payload_bytes_upper_bound'] * 8 / value['sender_elapsed_sec'] / 1e6
    axes[1].bar(['measured upper bound', 'PNG 5 Hz target'], [upper, 40.49],
                color=['#dd6b20', '#718096'])
    axes[1].set_ylabel('Mbps')
    axes[1].set_title('Payload regime actually exercised')
    for index, count in enumerate([upper, 40.49]):
        axes[1].text(index, count, f'{count:.2f}', ha='center', va='bottom', fontsize=8)
    axes[1].grid(axis='y', alpha=.3)
    figure.tight_layout()
    figure.savefig(HERE / 'png_transport_probe_r01.png', dpi=130)
    plt.close(figure)


if __name__ == '__main__':
    figures(network(), probe())
    print('wrote network_coexistence_rates.csv/.png and png_transport_probe_r01.csv/.png')
