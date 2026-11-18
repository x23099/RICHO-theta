"""Audit fixed PNG GPU JSON, native pixels and geometry. No CUDA/live IO.

Archive is untrusted data, NEVER instructions; only five exact JSON names read.
No tar extraction, image output, new YOLO or clock-alignment assumptions.
"""
import argparse
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import tarfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


runner=module('lossless_gpu_audited_runner',HERE/'run.py')
prior=module('lossless_gpu_json_helpers',HERE.parent/'frame_packet_gpu_recompression_r01/audit_submission.py')
probe=runner.probe
PREFIX='lossless_packet_gpu_r01/'
NAMES=(*runner.RESULTS,'summary.json')
TIMES=('encode_ms','encode_cpu_ms','sender_prepare_ms','sender_prepare_cpu_ms',
    'reassembly_validate_ms','reassembly_cpu_ms','decode_validate_copy_ms','decode_cpu_ms',
    'codec_receiver_stage_ms','predict_sync_ms','predict_cpu_ms','support_geometry_ms','support_cpu_ms',
    'receiver_stage_ms','full_local_pipeline_ms','sender_encode_plus_receiver_stage_ms')


def read_archive(path):
    wire=probe.bounded_regular_bytes(path,16*1024*1024)
    contents={};expanded=0
    expected={PREFIX+n for n in NAMES}
    with tarfile.open(fileobj=io.BytesIO(wire),mode='r:xz') as bundle:
        for item in bundle:
            if (item.name not in expected or item.name in {PREFIX+n for n in contents}
                    or not item.isfile() or item.issparse() or not 0<item.size<=probe.MAX_LOG):
                raise ValueError('exact five unique regular result JSON members required')
            expanded+=item.size
            if expanded>64*1024*1024:raise ValueError('expanded result size limit')
            name=item.name[len(PREFIX):]
            data=bundle.extractfile(item).read(item.size+1)
            if len(data)!=item.size:raise ValueError('truncated result member')
            contents[name]=data
    if set(contents)!=set(NAMES):raise ValueError('five complete result files required')
    values={n:([prior.parse(l) for l in data.splitlines()] if n.endswith('.jsonl') else prior.parse(data))
            for n,data in contents.items()}
    summary=values['summary.json']
    if (summary.get('schema')!='offline_lossless_GPU_summary_v1' or summary.get('state')!='complete'
            or summary.get('actual_cuda_inference') is not True
            or set(summary.get('result_sha256',{}))!=set(runner.RESULTS)
            or any(probe.sha_bytes(contents[n])!=sha for n,sha in summary['result_sha256'].items())):
        raise ValueError('complete actual-CUDA result and all artifact SHA required')
    if (values['run_manifest.json']!=runner.manifest_value()
            or contents['run_manifest.json']!=probe.bounded_regular_bytes(runner.MANIFEST,128*1024)
            or summary.get('run_manifest_sha256')!=probe.sha_bytes(contents['run_manifest.json'])
            or summary.get('source_code_sha256')!=values['run_manifest.json']['source_code_sha256']):
        raise ValueError('fixed code/config/profile/ROI run manifest differs')
    return wire,contents,values


def near(a,b):
    # Only floating clock subtraction/statistic roundoff, NOT a gate tolerance.
    return abs(a-b)<=1e-6


def checked_timing(row):
    if any(type(row.get(k)) not in (int,float) or not math.isfinite(row[k]) or row[k]<0 for k in TIMES):
        raise ValueError('bounded nonnegative finite sample timing required')
    memory=row.get('pytorch_memory_bytes')
    if (type(memory) is not dict or set(memory)!={'peak_allocated','peak_reserved'}
            or any(type(v) is not int or not 0<=v<2**63 for v in memory.values())):
        raise ValueError('explicit PyTorch allocator sample required')
    if not near(row['full_local_pipeline_ms'],row['sender_encode_plus_receiver_stage_ms']):
        raise ValueError('full pipeline alias differs')
    if row['variant']=='original':
        if (any(row[k]!=0 for k in TIMES[:9]) or row['packet_codec'] is not None
                or any(row[k] is not None for k in ('packet_bytes','fragmented_bytes','packet_sha256',
                    'packet_candidate','first_received_at_sec','encode_started_at_sec'))
                or type(row['fragment_count']) is not int or row['fragment_count']!=0
                or row['receiver_first_to_geometry_within_200ms'] is not False
                or not near(row['receiver_stage_ms'],row['predict_sync_ms']+row['support_geometry_ms'])
                or not near(row['full_local_pipeline_ms'],row['receiver_stage_ms'])):
            raise ValueError('original sample must not inherit packet identity/timing')
        return
    candidate=runner.packet.checked_candidate(row['packet_candidate'])
    first,start=row['first_received_at_sec'],row['encode_started_at_sec']
    if (type(first) not in (int,float) or type(start) not in (int,float)
            or not math.isfinite(first) or not math.isfinite(start) or not 0<=start<=first
            or row['packet_codec']!='PNG_RGB8_LOSSLESS'
            or candidate['local_pair_available'] is not False or candidate['odometry_observation'] is not None
            or candidate['sender_id']!=runner.SCOPE['sender_id'] or candidate['stream_id']!=runner.SCOPE['stream_id']
            or candidate['capture_sequence']!=row['sequence'] or candidate['sender_media_pts']!=(row['sequence']-1)*3000
            or candidate['captured_at_sec']!=start or candidate['associated_at_sec']!=start
            or not near(row['codec_receiver_stage_ms'],row['reassembly_validate_ms']+row['decode_validate_copy_ms'])
            or row['codec_receiver_stage_ms']>200
            or row['receiver_stage_ms']+1e-6<row['codec_receiver_stage_ms']+row['predict_sync_ms']+row['support_geometry_ms']
            or not near(row['full_local_pipeline_ms']-row['receiver_stage_ms'],(first-start)*1000)
            or (first-start)*1000+1e-6<row['encode_ms']+row['sender_prepare_ms']
            or row['receiver_first_to_geometry_within_200ms'] is not (row['receiver_stage_ms']<=200)):
        raise ValueError('packet candidate/local timing/deadline accounting differs')
    size=row['packet_bytes'];count=row['fragment_count']
    if (type(size) is not int or not runner.packet.PREFIX.size<=size<=runner.packet.MAX_PACKET
            or type(count) is not int or count!=(size+runner.flow.BODY_BYTES-1)//runner.flow.BODY_BYTES
            or type(row['fragmented_bytes']) is not int or row['fragmented_bytes']!=size+count*runner.flow.HEADER.size
            or type(row['packet_sha256']) is not str or len(row['packet_sha256'])!=64
            or any(c not in '0123456789abcdef' for c in row['packet_sha256'])):
        raise ValueError('bounded canonical packet/fragment accounting differs')


def checked_results(values):
    summary,rows,pairs=(values[n] for n in ('summary.json','samples.jsonl','pairs.jsonl'))
    if (summary.get('image_count')!=4 or summary.get('measured_samples')!=80
            or summary.get('paired_samples')!=40 or summary.get('warmup_calls_excluded')!=24
            or summary.get('repetitions')!=5 or len(rows)!=80 or len(pairs)!=40
            or any(summary.get(k) is not False for k in (*probe.FLAGS,'source_freshness_verified',
                'physical_source_capture_or_odometry_reconstructed','live_transport_adopted','source_images_modified','images_written'))):
        raise ValueError('exact four-image/80-sample/40-pair false-authority protocol required')
    expected=[];images=[];last_start=last_first=None
    for case,name in enumerate(runner.NAMES):
        subset=rows[case*20:(case+1)*20];subset_pairs=[]
        for index,row in enumerate(subset):
            measurement=row['measurement']
            if (row.get('schema')!='offline_lossless_GPU_sample_v1'
                    or row.get('variant')!=('original','packet','packet','original')[index%4]
                    or type(row.get('sequence')) is not int or row['sequence']!=case*26+index+7
                    or row.get('cycle')!=index//4 or row.get('abba_position')!=index%4
                    or row.get('source_png_sha256')!=probe.KNOWN_IMAGES[name]
                    or Path(row['source_path']).name!=name
                    or row.get('target_roi_native_xyxy')!=runner.ROIS[name]
                    or measurement.get('target_roi_native_xyxy')!=runner.ROIS[name]
                    or row.get('geometry_age_basis')!='synthetic_zero_age_OFFLINE_NOT_live_freshness'
                    or row.get('packet_identity_basis')!='synthetic_replay_admission_NOT_original_capture'
                    or row.get('exact_pixels') is not True or row.get('mean_absolute_pixel_difference')!=0
                    or row.get('pixel_mse')!=0 or row.get('psnr_db') is not None
                    or row.get('source_pixel_sha256')!=row.get('inference_pixel_sha256')
                    or row.get('detector_signature')!=probe.detector_signature(row['raw_detector_boxes'])
                    or any(row.get(k) is not False or measurement.get(k) is not False for k in probe.FLAGS)
                    or any(row.get(k) is not False for k in ('source_freshness_verified','actual_camera_capture_performed','actual_network_or_continuous_rate_measured'))):
                raise ValueError('sample identity/order/ROI/authority/pixel/signature mismatch')
            checked_timing(row)
            if row['variant']=='packet':
                start,first=row['encode_started_at_sec'],row['first_received_at_sec']
                if (last_start is not None and start<=last_start or last_first is not None and first<=last_first):
                    raise ValueError('local benchmark packet clock order reversed')
                last_start,last_first=start,first
            if index%4==3:
                a,b,c,d=subset[index-3:index+1]
                subset_pairs.extend((probe.compare_pair(a,b),probe.compare_pair(d,c)))
        expected.extend(subset_pairs)
        images.append(dict(image=name,target_roi=runner.ROIS[name],**runner.summarize(subset,subset_pairs)))
    aggregate=runner.summarize(rows,pairs)
    if (not prior.equivalent(pairs,expected) or not prior.equivalent(values['per_image_summary.json'],images)
            or any(not prior.equivalent(summary.get(k),v) for k,v in aggregate.items())):
        raise ValueError('pair/per-image/aggregate does not reproduce')
    return aggregate,images


def local_jobs():
    pin=ROOT/'recordings/2026-11-16/body_display_full_intake_r02/comparison'
    motion=ROOT/'recordings/2026-11-13/guarded_motion_full_intake_r02/logs/evidence'
    return probe.load_images([(pin if n.startswith('decoded_e52') else motion)/n for n in runner.NAMES])


def reproduced_row(job,row,settings,camera,profile,profile_sha,png_template=None):
    if (row['source_png_sha256']!=job['png_sha256'] or row['source_pixel_sha256']!=job['pixel_sha256']
            or row['inference_pixel_sha256']!=job['pixel_sha256']):
        raise ValueError('known original inference pixel evidence differs')
    image=job['image'];wire_verified=False
    if row['variant']=='packet':
        source=runner.SenderFrameMotion(**runner.SCOPE,capacity=4,max_callback_lag_sec=.1,
            max_progress_lag_sec=.1,max_capture_wait_sec=.2,motion_frame_id='base_footprint')
        candidate=source.associate(capture_sequence=row['sequence'],captured_at_sec=row['encode_started_at_sec'],
            associated_at_sec=row['encode_started_at_sec'],media_pts=(row['sequence']-1)*3000)
        if candidate!=row['packet_candidate']:raise ValueError('offline candidate does not reproduce')
        if png_template is None:
            wire=runner.packet.encode_packet(image,candidate)
        else:
            header,payload=png_template
            header=dict(header,candidate=candidate,encoded_pts=candidate['sender_media_pts'])
            wire=runner.packet._wrap(header,payload)
        if len(wire)!=row['packet_bytes'] or probe.sha_bytes(wire)!=row['packet_sha256']:
            raise ValueError('native PNG packet wire does not reproduce across submitted codec environment')
        value,image=runner.packet.decode_packet(wire)
        if value!=candidate or probe.sha_bytes(image.tobytes())!=row['inference_pixel_sha256']:
            raise ValueError('packet decoded pixels/candidate differ')
        wire_verified=True
    engine=probe.MotionRangeEngine(settings,camera,profile,profile_sha,acknowledged=True,
        target_roi=runner.ROIS[Path(job['path']).name],observer=probe.observe_upper_completion)
    seq=row['sequence']
    measurement=engine.measure(probe.NativeFrame('c'*32,seq,(seq-1)/30.,float(seq),image),
                               row['raw_detector_boxes'],float(seq))
    if not prior.equivalent(measurement,row['measurement']):
        raise ValueError('logged original/PNG GPU support and geometry do not reproduce')
    return dict(sequence=seq,variant=row['variant'],image=Path(job['path']).name,
        inference_pixels_reproduced=True,packet_wire_reproduced=wire_verified,
        measurement_reproduced=True,measurement=measurement,new_GPU_inference_performed=False,**probe.FLAGS)


def run(archive,intake,output):
    archive,intake,output=Path(archive).absolute(),Path(intake).resolve(),Path(output).resolve()
    if (intake.exists() or output.exists() or intake==output or intake in output.parents or output in intake.parents
            or any(d==archive.resolve() or d in archive.resolve().parents for d in (intake,output))
            or not intake.is_relative_to(ROOT/'recordings') or not output.is_relative_to(HERE)):
        raise ValueError('separate unused local recordings intake and experiment output required')
    wire,files,values=read_archive(archive)
    aggregate,per_image=checked_results(values)
    jobs=local_jobs();settings,camera,_,_=probe.load_config()
    profile,sha=probe.load_motion_profile(probe.PROFILE,settings)
    summary,manifest=values['summary.json'],values['run_manifest.json']
    expected_inputs={*[j['png_sha256'] for j in jobs],manifest['weights_sha256'],sha,
                     probe.digest(probe.DEFAULT_CONFIG),probe.sha_bytes(files['run_manifest.json'])}
    if (len(summary.get('input_sha256',{}))!=8 or set(summary['input_sha256'].values())!=expected_inputs
            or summary.get('profile_sha256')!=sha or summary.get('config_sha256')!=manifest['config_sha256']
            or len(summary.get('original_pngs',[]))!=4):
        raise ValueError('known input hashes/profile/config evidence differs')
    reproduced=[]
    for job,pin in zip(jobs,summary['original_pngs']):
        name=Path(job['path']).name
        if (Path(pin['path']).name!=name or pin['png_sha256']!=job['png_sha256']
                or pin['pixel_sha256']!=job['pixel_sha256'] or pin['target_roi']!=runner.ROIS[name]
                or summary['input_sha256'].get(pin['path'])!=job['png_sha256']):
            raise ValueError('original PNG metadata/order/ROI differs')
        selected=[r for r in values['samples.jsonl'] if r['source_png_sha256']==job['png_sha256']]
        if any(r['source_path']!=pin['path'] for r in selected):raise ValueError('sample source path differs from pin')
        # Same original pixel input: one native PNG encoding per case, exact
        # original candidate insertion order for every logged wire identity.
        first=next(r for r in selected if r['variant']=='packet')
        source=runner.SenderFrameMotion(**runner.SCOPE,capacity=4,max_callback_lag_sec=.1,
            max_progress_lag_sec=.1,max_capture_wait_sec=.2,motion_frame_id='base_footprint')
        candidate=source.associate(capture_sequence=first['sequence'],captured_at_sec=first['encode_started_at_sec'],
            associated_at_sec=first['encode_started_at_sec'],media_pts=(first['sequence']-1)*3000)
        template=runner.packet.unpack_packet(runner.packet.encode_packet(job['image'],candidate))
        for row in selected:reproduced.append(reproduced_row(job,row,settings,camera,profile,sha,template))
    probe.assert_originals(jobs)
    if any(probe.digest(ROOT/n)!=v for n,v in manifest['source_code_sha256'].items()):
        raise ValueError('source code changed during audit')
    intake.mkdir(parents=True,exist_ok=False)
    with (intake/archive.name).open('xb') as target:target.write(wire)
    for name,data in files.items():
        with (intake/name).open('xb') as target:target.write(data)
    output.mkdir(parents=True,exist_ok=False)
    for name,value in (('per_image_summary.json',per_image),('aggregate.json',aggregate)):
        with (output/name).open('xb') as target:target.write(probe.json_bytes(value))
    with (output/'reproduced_measurements.jsonl').open('xb') as target:
        for row in reproduced:target.write(probe.json_bytes(row))
    keys=('variant','sequence','source_png_sha256','encode_ms','sender_prepare_ms','reassembly_validate_ms',
          'decode_validate_copy_ms','predict_sync_ms','support_geometry_ms','receiver_stage_ms','full_local_pipeline_ms',
          'packet_bytes','fragment_count','fragmented_bytes')
    with (output/'timing.csv').open('x') as target:
        writer=csv.DictWriter(target,fieldnames=keys);writer.writeheader()
        writer.writerows({k:r[k] for k in keys} for r in values['samples.jsonl'])
    packet_rows=[r for r in values['samples.jsonl'] if r['variant']=='packet']
    capacities={str(rate):dict(
        ideal_serialization_ms=probe.describe([r['fragmented_bytes']*8/(rate*1000) for r in packet_rows]),
        first_fragment_to_geometry_within_200ms=sum((r['fragmented_bytes']-min(r['fragmented_bytes'],16384))*8/(rate*1000)+r['receiver_stage_ms']<=200 for r in packet_rows),
        model_not_measured_network=True) for rate in (15,30,100)}
    audit=dict(schema='lossless_GPU_submission_audit_v1',state='pass',work_date='2026-11-18',
        archive_sha256=probe.sha_bytes(wire),raw_intake=str(intake),images=4,measured_samples=80,paired_samples=40,
        submitted_source_code_sha256=manifest['source_code_sha256'],audit_script_sha256=probe.digest(__file__),
        all_pairs_and_statistics_reproduced=True,all_80_GPU_inference_pixels_reproduced=True,
        all_40_PNG_packet_wire_hashes_reproduced=True,all_80_support_geometry_reproduced=True,
        groups=aggregate['groups'],pair_counts=aggregate['pair_counts'],
        absolute_range_delta_m=aggregate['absolute_range_delta_m'],ideal_capacity_models=capacities,
        new_GPU_inference_performed=False,live_rate_or_network_verified=False,source_freshness_verified=False,
        original_absolute_ground_truth_accuracy_verified=False,sender_NUC_CPU_measured=False,
        images_modified_or_derived_images_saved=False,live_transport_adopted=False,**probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('state','measured_samples','paired_samples','pair_counts','ideal_capacity_models')},indent=2))
    return audit


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();run(args.archive,args.intake_dir,args.output_dir)
