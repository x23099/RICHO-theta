"""Saved-image pixel preservation comparison. No new inference or transport."""
import argparse
import csv
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import struct
import time
import zlib

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


suite=module('preservation_suite',ROOT/'Experimental_results/2026-11-18/frame_packet_saved_suite_r01/run_suite.py')
prior=module('preservation_audit_helpers',ROOT/'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/audit_submission.py')
probe=suite.probe
KINDS=('vp8_current','png_default','png_level3','zlib_level1')
RAW_BYTES=1280*720*3
CAP=2*1024*1024


def encode_lossless(image,kind):
    import cv2
    probe.native_frame(image)
    if kind=='zlib_level1':
        payload=zlib.compress(image.tobytes(),1)
    elif kind in ('png_default','png_level3'):
        params=[] if kind=='png_default' else [cv2.IMWRITE_PNG_COMPRESSION,3]
        ok,value=cv2.imencode('.png',image,params)
        if not ok:raise ValueError('PNG encoding failed')
        payload=value.tobytes()
    else:raise ValueError('explicit lossless candidate required')
    if not 0<len(payload)<=CAP:
        raise ValueError('candidate exceeds existing 2MiB payload cap; no cap expansion')
    return payload


def decode_lossless(payload,kind):
    import cv2
    import numpy as np
    if type(payload) is not bytes or not 0<len(payload)<=CAP:
        raise ValueError('bounded encoded bytes required')
    if kind=='zlib_level1':
        decoder=zlib.decompressobj()
        try:value=decoder.decompress(payload,RAW_BYTES+1)
        except zlib.error as error:raise ValueError('invalid zlib payload') from error
        if len(value)!=RAW_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('exact bounded native zlib image required')
        image=np.frombuffer(value,np.uint8).reshape((720,1280,3)).copy()
    elif kind in ('png_default','png_level3'):
        if (len(payload)<33 or payload[:8]!=b'\x89PNG\r\n\x1a\n'
                or payload[8:16]!=b'\x00\x00\x00\rIHDR'
                or struct.unpack('!IIBBBBB',payload[16:29])!=(1280,720,8,2,0,0,0)):
            raise ValueError('native 8-bit three-channel PNG IHDR required before decode')
        image=cv2.imdecode(np.frombuffer(payload,np.uint8),cv2.IMREAD_COLOR)
    else:raise ValueError('explicit lossless candidate required')
    probe.native_frame(image)
    image.flags.writeable=False
    return image


def load_cases():
    single=ROOT/'recordings/2026-11-18/packet_recompression_gpu_r02_intake_r01'
    multi=ROOT/'recordings/2026-11-18/packet_recompression_multi_gpu_intake_r01'
    evidence=ROOT/'recordings/2026-11-13/guarded_motion_full_intake_r02/logs/evidence'
    pin=ROOT/'recordings/2026-11-16/body_display_full_intake_r02/comparison'/next(
        n for n in probe.KNOWN_IMAGES if n.startswith('decoded_e52'))
    inputs={}
    records={}
    for directory in (single,multi):
        summary_path=directory/'summary.json';sample_path=directory/'samples.jsonl'
        summary=prior.parse(probe.bounded_regular_bytes(summary_path,128*1024))
        raw=probe.bounded_regular_bytes(sample_path,probe.MAX_LOG)
        if (summary.get('state')!='complete' or summary.get('actual_cuda_inference') is not True
                or probe.sha_bytes(raw)!=summary['result_sha256']['samples.jsonl']):
            raise ValueError('verified CUDA originals required')
        for name,sha in summary['source_code_sha256'].items():
            if probe.digest(ROOT/name)!=sha:raise ValueError('GPU measurement code changed: '+name)
        inputs[str(summary_path.relative_to(ROOT))]=probe.digest(summary_path)
        inputs[str(sample_path.relative_to(ROOT))]=probe.sha_bytes(raw)
        for row in (prior.parse(l) for l in raw.splitlines()):
            key=(row['source_png_sha256'],row['variant'])
            records.setdefault(key,row)
    jobs=probe.load_images([pin,*[evidence/n for n in suite.NAMES]])
    cases=[]
    for job in jobs:
        source={v:records[(job['png_sha256'],v)] for v in ('original','packet')}
        if any(r['source_pixel_sha256']!=job['pixel_sha256'] for r in source.values()):
            raise ValueError('stored CUDA original pixels differ')
        cases.append(dict(job=job,records=source,roi=source['original']['measurement']['target_roi_native_xyxy']))
    return cases,inputs


def decisions_equal(value,reference):
    # Same integer points/reasons/observations. Allow only 1e-10 numerical
    # roundoff between the saved GPU-host and analysis-host floor calculation.
    keys=('distance_available','reason','support_pixel','horizontal_camera_foot_range_m','models')
    return prior.equivalent({k:value.get(k) for k in keys},{k:reference.get(k) for k in keys})


def trial(case,kind,repetition,settings,camera,profile,profile_sha):
    image=case['job']['image']
    old=case['records']['packet' if kind=='vp8_current' else 'original']
    started,cpu=time.perf_counter(),time.process_time()
    if kind=='vp8_current':
        decoded,codec=probe.packet_roundtrip(image,old['sequence'])
        encode_ms,decode_ms=codec['encode_ms'],codec['decode_validate_copy_ms']
        encode_cpu,decode_cpu=codec['encode_cpu_ms'],codec['decode_cpu_ms']
        if codec['packet_sha256']!=old['packet_sha256']:
            raise ValueError('saved VP8 GPU wire differs')
        # Existing VP8 timings include packet validation/copy, not codec alone.
        size=codec['packet_bytes']
        timing_scope='existing_full_VP8_packet_path_NOT_same_as_candidate_payload_only'
    else:
        payload=encode_lossless(image,kind)
        middle,mid_cpu=time.perf_counter(),time.process_time()
        decoded=decode_lossless(payload,kind)
        ended,end_cpu=time.perf_counter(),time.process_time()
        encode_ms,decode_ms=(middle-started)*1000,(ended-middle)*1000
        encode_cpu,decode_cpu=(mid_cpu-cpu)*1000,(end_cpu-mid_cpu)*1000
        size=len(payload)
        timing_scope='lossless_candidate_payload_only_NOT_runtime_packet_or_GPU'
    decoded_sha=probe.sha_bytes(decoded.tobytes())
    if decoded_sha!=old['inference_pixel_sha256']:
        raise ValueError('candidate is not the exact image used by saved GPU detections')
    if kind!='vp8_current' and decoded_sha!=case['job']['pixel_sha256']:
        raise ValueError('lossless roundtrip changed source pixels')
    seq=old['sequence']
    engine=probe.MotionRangeEngine(settings,camera,profile,profile_sha,acknowledged=True,
        target_roi=case['roi'],observer=probe.observe_upper_completion)
    value=engine.measure(probe.NativeFrame('c'*32,seq,old['measurement']['media_time_sec'],float(seq),decoded),
                         old['raw_detector_boxes'],float(seq))
    if not prior.equivalent(value,old['measurement']):
        raise ValueError('stored GPU support/geometry does not reproduce')
    original=case['records']['original']['measurement']
    return dict(image=Path(case['job']['path']).name,source_png_sha256=case['job']['png_sha256'],
        kind=kind,repetition=repetition,bytes=size,size_scope='VP8_full_packet' if kind=='vp8_current' else 'candidate_payload_only',
        decoded_pixel_sha256=decoded_sha,pixels_identical_to_original=decoded_sha==case['job']['pixel_sha256'],
        decision_identical_to_original=decisions_equal(value,original),
        support_observation_identical_to_original=prior.equivalent(value.get('support_observation'),original.get('support_observation')),
        distance_available=value['distance_available'],range_m=value['horizontal_camera_foot_range_m'],reason=value['reason'],
        original_distance_available=original['distance_available'],support_pixel=value['support_pixel'],
        encode_ms=encode_ms,decode_ms=decode_ms,encode_cpu_ms=encode_cpu,decode_cpu_ms=decode_cpu,
        timing_scope=timing_scope,payload_or_packet_Mbps_at_5Hz=size*8*5/1e6,
        payload_or_packet_Mbps_at_10Hz=size*8*10/1e6,
        ideal_serialization_ms_at_15Mbps=size*8/15000,
        ideal_serialization_ms_at_30Mbps=size*8/30000,
        ideal_serialization_ms_at_100Mbps=size*8/100000,
        new_YOLO_inference_performed=False,live_packet_format_compatible=kind=='vp8_current',**probe.FLAGS)


def summarize(rows):
    output={}
    for kind in KINDS:
        selected=[r for r in rows if r['kind']==kind]
        output[kind]=dict(trials=len(selected),pixels_preserved_trials=sum(r['pixels_identical_to_original'] for r in selected),
            decisions_preserved_trials=sum(r['decision_identical_to_original'] for r in selected),
            withheld_to_numeric=sum(not r['original_distance_available'] and r['distance_available'] for r in selected),
            numeric_to_withheld=sum(r['original_distance_available'] and not r['distance_available'] for r in selected))
        for key in ('bytes','encode_ms','decode_ms','encode_cpu_ms','decode_cpu_ms',
            'payload_or_packet_Mbps_at_5Hz','payload_or_packet_Mbps_at_10Hz',
            'ideal_serialization_ms_at_15Mbps','ideal_serialization_ms_at_30Mbps','ideal_serialization_ms_at_100Mbps'):
            output[kind][key]=probe.describe([r[key] for r in selected])
    return output


def run(output):
    output=Path(output).resolve()
    if output.exists() or HERE not in output.parents:
        raise ValueError('unused experiment output required')
    cases,inputs=load_cases()
    settings,camera,_,_=probe.load_config()
    profile,sha=probe.load_motion_profile(probe.PROFILE,settings)
    import cv2
    sources={str(Path(__file__).relative_to(ROOT)):probe.digest(__file__)}
    sources.update({'src/'+name:probe.digest(ROOT/'src'/name) for name in probe.CODE})
    rows=[]
    for case in cases:
        for repetition in range(5):
            # Alternate candidate order to avoid a fixed warm-cache advantage.
            order=KINDS if repetition%2==0 else tuple(reversed(KINDS))
            for kind in order:rows.append(trial(case,kind,repetition,settings,camera,profile,sha))
    probe.assert_originals([c['job'] for c in cases])
    if any(probe.digest(ROOT/n)!=sha for n,sha in inputs.items()) or any(probe.digest(ROOT/n)!=sha for n,sha in sources.items()):
        raise ValueError('inputs/code changed during comparison')
    output.mkdir(parents=True,exist_ok=False)
    with (output/'trials.csv').open('x') as target:
        writer=csv.DictWriter(target,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    with (output/'trials.jsonl').open('xb') as target:
        for row in rows:target.write(probe.json_bytes(row))
    audit=dict(schema='saved_pixel_preservation_comparison_v1',state='pass',work_date='2026-11-18',
        executed_utc=datetime.now(timezone.utc).isoformat(),input_GPU_records_sha256=inputs,source_code_sha256=sources,
        original_PNG_sha256={Path(c['job']['path']).name:c['job']['png_sha256'] for c in cases},
        environment=dict(OpenCV=cv2.__version__,zlib=zlib.ZLIB_RUNTIME_VERSION),
        image_count=4,repetitions=5,trials=len(rows),groups=summarize(rows),
        geometry_float_roundoff_tolerance=1e-10,pixel_identity_compared_by_exact_SHA256=True,
        warmup_calls_excluded=0,cold_start_may_be_included=True,
        decision_scope='stored_GPU_boxes_on_SHA_identical_inference_pixels_then_unchanged_support_geometry',
        new_CUDA_or_YOLO_inference=False,network_bandwidth_measured=False,queue_or_live_deadline_verified=False,
        lossless_runtime_packet_implemented=False,source_images_modified_or_derived_images_saved=False,
        GPU_timings_from_this_PC=False,source_freshness_verified=False,**probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(audit))
    print(json.dumps(dict(state='pass',images=4,trials=len(rows),groups={kind:{
        k:value[k] for k in ('pixels_preserved_trials','decisions_preserved_trials','withheld_to_numeric')}
        for kind,value in audit['groups'].items()}),indent=2))
    return audit


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args().output_dir)
