"""Offline full PNG packet audit on four unchanged saved GPU input images."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SPEC=importlib.util.spec_from_file_location('lossless_preservation',HERE.parent/'frame_packet_preservation_r01/compare.py')
previous=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(previous)
probe=previous.probe

import driver_lossless_frame_packet as packet
import driver_lossless_frame_fragments as transport
from driver_frame_motion import SenderFrameMotion


def metadata(sequence):
    # Offline admission fixture, explicitly NOT recorded odometry/capture times.
    source=SenderFrameMotion(sender_id='a'*32,stream_id='b'*32,capacity=4,
        max_callback_lag_sec=.1,max_progress_lag_sec=.1,max_capture_wait_sec=.2,
        motion_frame_id='base_footprint')
    return source.associate(capture_sequence=sequence,captured_at_sec=float(sequence),
        associated_at_sec=float(sequence),media_pts=(sequence-1)*3000)


def scope():
    return dict(sender_id='a'*32,stream_id='b'*32)


def model(wire, *, rate_mbps, measured_receiver_ms):
    """Ideal serialization, not a link measurement or a sender queue model.

    Arrival time is end-of-message; initial message arrival starts local expiry.
    Receiver CPU work is added separately using this analysis PC's measured work.
    SCTP/DTLS/IP overhead, scheduling, congestion and concurrent video are absent.
    """
    assembler=transport.LosslessReassembler(**scope())
    elapsed,arrival,first=0.,None,None
    for message in transport.fragments(wire):
        elapsed+=len(message)*8/(rate_mbps*1e6)
        if first is None:first=elapsed
        value=assembler.accept(message,elapsed)
        if value is not None:arrival=value
    completion=elapsed+measured_receiver_ms/1000
    retained=arrival is not None and completion <= arrival.deadline_sec
    return dict(ideal_rate_Mbps=rate_mbps,wire_serialization_ms=elapsed*1000,
        first_message_to_last_message_ms=(elapsed-first)*1000,
        assembly_within_first_200ms=arrival is not None,
        after_receiver_work_within_first_200ms=retained,
        receiver_work_from_analysis_PC_ms=measured_receiver_ms,
        first_message_to_postdecode_ms=(completion-first)*1000,
        is_real_network_measurement=False)


def run(output):
    output=Path(output).resolve()
    if output.exists() or HERE not in output.parents:
        raise ValueError('unused experiment output required')
    cases,inputs=previous.load_cases()
    frozen_path=HERE.parent/'frame_packet_preservation_r01/verification_r01/audit.json'
    frozen=json.loads(frozen_path.read_bytes())['unchanged_runtime_source_sha256']
    inputs[str(frozen_path.relative_to(ROOT))]=probe.digest(frozen_path)
    if any(probe.digest(ROOT/n)!=sha for n,sha in frozen.items()):
        raise ValueError('frozen runtime changed')
    sources={str(p.relative_to(ROOT)):probe.digest(p) for p in (Path(__file__),
        ROOT/'src/driver_lossless_frame_packet.py',ROOT/'src/driver_lossless_frame_fragments.py',
        ROOT/'src/driver_frame_packet.py',ROOT/'src/driver_frame_motion.py')}
    settings,camera,_,_=probe.load_config()
    profile,profile_sha=probe.load_motion_profile(probe.PROFILE,settings)
    rows=[]
    for case in cases:
        for repetition in range(5):
            image=case['job']['image'];meta=metadata(repetition+1)
            started=time.perf_counter()
            wire=packet.encode_packet(image,meta)
            encoded=time.perf_counter()
            # Same worker, no physical link. Fragment work included in this stage.
            assembler=transport.LosslessReassembler(**scope());arrival=None
            for message in transport.fragments(wire):
                value=assembler.accept(message,time.perf_counter())
                if value is not None:arrival=value
            assembled=time.perf_counter()
            if arrival is None:raise ValueError('local fragment roundtrip expired or failed')
            receiver=packet.LosslessPacketReceiver(**scope())
            if not receiver.accept(arrival.wire,first_received_at_sec=arrival.first_received_at_sec,now=time.perf_counter):
                raise ValueError('local decode exceeded unchanged first-fragment deadline')
            decoded=receiver.take(time.perf_counter())
            ended=time.perf_counter()
            if (decoded is None or decoded.candidate!=meta or decoded.candidate['local_pair_available']
                    or probe.sha_bytes(decoded.image.tobytes())!=case['job']['pixel_sha256']):
                raise ValueError('pixel/candidate identity not preserved')
            reference=case['records']['original'];seq=reference['sequence']
            engine=probe.MotionRangeEngine(settings,camera,profile,profile_sha,acknowledged=True,
                target_roi=case['roi'],observer=probe.observe_upper_completion)
            measurement=engine.measure(probe.NativeFrame('c'*32,seq,
                reference['measurement']['media_time_sec'],float(seq),decoded.image),
                reference['raw_detector_boxes'],float(seq))
            if not previous.prior.equivalent(measurement,reference['measurement']):
                raise ValueError('unchanged GPU input support/geometry not reproduced')
            count=(len(wire)+transport.BODY_BYTES-1)//transport.BODY_BYTES
            transport_bytes=len(wire)+count*transport.HEADER.size
            row=dict(image=Path(case['job']['path']).name,repetition=repetition,
                original_png_sha256=case['job']['png_sha256'],pixel_sha256=case['job']['pixel_sha256'],
                packet_sha256=probe.sha_bytes(wire),packet_bytes=len(wire),fragment_count=count,
                fragment_header_bytes=count*transport.HEADER.size,fragmented_bytes=transport_bytes,
                exact_pixels=True,exact_candidate=True,original_full_measurement_reproduced=True,
                distance_available=measurement['distance_available'],reason=measurement['reason'],
                support_pixel=measurement['support_pixel'],range_m=measurement['horizontal_camera_foot_range_m'],
                encode_validate_ms=(encoded-started)*1000,
                fragmentation_reassembly_validate_ms=(assembled-encoded)*1000,
                decode_validate_copy_ms=(ended-assembled)*1000,
                local_first_fragment_to_take_ms=(ended-arrival.first_received_at_sec)*1000,
                ideal_fragmented_Mbps_at_5Hz=transport_bytes*8*5/1e6,
                ideal_fragmented_Mbps_at_10Hz=transport_bytes*8*10/1e6,
                new_YOLO_inference=False,**probe.FLAGS)
            # Start at FIRST fragment, excluding the source-side generator's
            # pre-first validation. Add all measured local receiver work as a
            # conservative serial cost, without assuming transfer/CPU overlap.
            row['ideal_models']=[model(wire,rate_mbps=rate,
                measured_receiver_ms=row['local_first_fragment_to_take_ms']) for rate in (15,30,100)]
            rows.append(row)
    probe.assert_originals([c['job'] for c in cases])
    if any(probe.digest(ROOT/n)!=sha for n,sha in {**inputs,**sources,**frozen}.items()):
        raise ValueError('frozen code or original inputs changed')
    keys=('packet_bytes','fragment_count','fragmented_bytes','encode_validate_ms',
        'fragmentation_reassembly_validate_ms','decode_validate_copy_ms','local_first_fragment_to_take_ms',
        'ideal_fragmented_Mbps_at_5Hz','ideal_fragmented_Mbps_at_10Hz')
    audit=dict(schema='offline_lossless_atomic_packet_audit_v1',state='pass',work_date='2026-11-18',
        executed_utc=datetime.now(timezone.utc).isoformat(),images=4,trials=len(rows),
        exact_pixel_trials=sum(r['exact_pixels'] for r in rows),
        exact_candidate_trials=sum(r['exact_candidate'] for r in rows),
        original_measurement_reproduced_trials=sum(r['original_full_measurement_reproduced'] for r in rows),
        statistics={key:probe.describe([r[key] for r in rows]) for key in keys},
        ideal_model_pass_counts={str(rate):dict(assembly=sum(r['ideal_models'][index]['assembly_within_first_200ms'] for r in rows),
            postdecode=sum(r['ideal_models'][index]['after_receiver_work_within_first_200ms'] for r in rows))
            for index,rate in enumerate((15,30,100))},
        candidate_scope='synthetic_replay_admission_NOT_recorded_capture_or_odometry',
        timing_scope='analysis_PC_CPU_full_offline_PNG_packet_NOT_GPU_or_robot',warmup_calls_excluded=0,
        new_GPU_inference=False,real_network_measured=False,live_runtime_connected=False,
        sender_backpressure_verified=False,real_5_or_10Hz_pacing_verified=False,
        source_freshness_verified=False,source_images_modified_or_saved=False,
        first_fragment_deadline_sec=packet.DEADLINE_SEC,fragment_max_bytes=transport.MESSAGE_BYTES,
        payload_max_bytes=packet.MAX_PAYLOAD,header_max_bytes=packet.MAX_HEADER,
        source_code_sha256=sources,input_sha256=inputs,unchanged_runtime_source_sha256=frozen,**probe.FLAGS)
    output.mkdir(parents=True,exist_ok=False)
    with (output/'trials.jsonl').open('xb') as target:
        for row in rows:target.write(probe.json_bytes(row))
    audit['trials_sha256']=probe.digest(output/'trials.jsonl')
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('state','images','trials','statistics','ideal_model_pass_counts')},indent=2))
    return audit


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args().output_dir)
