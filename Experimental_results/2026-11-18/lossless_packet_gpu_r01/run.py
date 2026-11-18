"""Fixed four-image CUDA original/PNG-packet benchmark; no live/network IO."""
import argparse
import copy
from datetime import datetime,timezone
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import resource
import sys
import tarfile
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
LEGACY=ROOT/'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py'
SPEC=importlib.util.spec_from_file_location('lossless_gpu_common',LEGACY)
probe=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(probe)
import driver_lossless_frame_packet as packet
import driver_lossless_frame_fragments as flow
from driver_frame_motion import SenderFrameMotion

NAMES=tuple(probe.KNOWN_IMAGES)
ROIS={name:([200,0,280,720] if name.startswith('decoded_e52') else [270,0,350,720]) for name in NAMES}
SOURCE_PATHS=tuple(dict.fromkeys([
    str(Path(__file__).relative_to(ROOT)),str(LEGACY.relative_to(ROOT)),
    *['src/'+n for n in probe.CODE],
    'src/driver_lossless_frame_packet.py','src/driver_lossless_frame_fragments.py']))
MANIFEST=HERE/'verification_r01/run_manifest.json'
RESULTS=('samples.jsonl','pairs.jsonl','per_image_summary.json','run_manifest.json')
SCOPE=dict(sender_id='a'*32,stream_id='b'*32)


def find_inputs(roots):
    """Finite fixed-name search; do not follow directory or file symlinks."""
    found={};files=directories=0
    for root in roots:
        root=Path(root).absolute()
        if not root.is_dir() or root.is_symlink():continue
        for directory,children,names in os.walk(root,followlinks=False):
            children[:]=sorted(n for n in children if n not in ('.git','__pycache__','ultralytics_config')
                and not (Path(directory)/n).is_symlink())
            directories+=1;files+=len(names)
            if directories>20000 or files>100000:
                raise ValueError('input search bound exceeded; specify narrower --search-root')
            for name in sorted(set(names).intersection(NAMES)):
                path=Path(directory)/name
                try:data=probe.bounded_regular_bytes(path,4*1024*1024)
                except (OSError,ValueError):continue
                if name not in found and probe.sha_bytes(data)==probe.KNOWN_IMAGES[name]:found[name]=path
    missing=[name for name in NAMES if name not in found]
    if missing:raise FileNotFoundError('missing exact saved PNGs (CUDA/model not started): '+', '.join(missing))
    return [found[name] for name in NAMES]


def manifest_value():
    settings,_,_,_=probe.load_config()
    return dict(schema='lossless_GPU_fixed_protocol_v1',
        source_code_sha256={n:probe.digest(ROOT/n) for n in SOURCE_PATHS},
        config_sha256=probe.digest(probe.DEFAULT_CONFIG),profile_sha256=probe.digest(probe.PROFILE),
        weights_sha256=settings['weights_sha256'],
        images=[dict(name=n,png_sha256=probe.KNOWN_IMAGES[n],target_roi=ROIS[n]) for n in NAMES],
        repetitions=5,warmup_pairs_per_image=3,codec='PNG_RGB8_LOSSLESS',
        actual_GPU_validation_performed=False,physical_metric_verified=False,usable_for_ffb=False)


def checked_manifest(path):
    data=json.loads(probe.bounded_regular_bytes(path,128*1024))
    if data!=manifest_value():
        raise ValueError('fixed run manifest/source/config differs; reflect the complete Git update first')
    return data


def inspect(args):
    manifest=checked_manifest(args.manifest)
    jobs=probe.load_images(find_inputs(args.search_root or [ROOT/'recordings',ROOT/'Experimental_results']))
    settings,camera,_,_=probe.load_config()
    profile,profile_sha=probe.load_motion_profile(probe.PROFILE,settings)
    weights=args.weights.absolute()
    if not weights.is_file() or weights.is_symlink() or probe.digest(weights)!=manifest['weights_sha256']:
        raise ValueError('trusted local weights SHA mismatch; no download/CPU fallback')
    if type(args.device) is not int or args.device<0:raise ValueError('explicit nonnegative CUDA device required')
    inputs={str(Path(j['path']).absolute()):j['png_sha256'] for j in jobs}
    inputs.update({str(p.absolute()):probe.digest(p) for p in (weights,probe.DEFAULT_CONFIG,probe.PROFILE,args.manifest)})
    return jobs,settings,camera,profile,profile_sha,manifest,inputs


def cuda_environment(device):
    import torch
    from run_cone_yolo import check_cuda
    gpu=check_cuda(torch,device)
    runtime=dict(python=sys.version,platform=platform.platform(),OpenCV=probe.cv2.__version__,
        torch=str(torch.__version__),ultralytics=importlib.metadata.version('ultralytics'))
    return torch,gpu,runtime


def roundtrip(image,sequence):
    start,cpu=time.perf_counter(),time.process_time()
    source=SenderFrameMotion(**SCOPE,capacity=4,max_callback_lag_sec=.1,
        max_progress_lag_sec=.1,max_capture_wait_sec=.2,motion_frame_id='base_footprint')
    candidate=source.associate(capture_sequence=sequence,captured_at_sec=start,
        associated_at_sec=start,media_pts=(sequence-1)*3000)
    wire=packet.encode_packet(image,candidate)
    encoded,enc_cpu=time.perf_counter(),time.process_time()
    fragments=flow.fragments(wire)
    first=next(fragments)
    prepared,prep_cpu=time.perf_counter(),time.process_time()
    assembler=flow.LosslessReassembler(**SCOPE)
    receiver=packet.LosslessPacketReceiver(**SCOPE)
    first_received=time.perf_counter()
    count=1;fragmented_bytes=len(first)
    try:
        arrival=assembler.accept(first,first_received)
        for message in fragments:
            count+=1;fragmented_bytes+=len(message)
            value=assembler.accept(message,time.perf_counter())
            if value is not None:arrival=value
        assembled,assembled_cpu=time.perf_counter(),time.process_time()
        if arrival is None:raise ValueError('PNG local reassembly failed/expired; deadline not extended')
        if not receiver.accept(arrival.wire,first_received_at_sec=arrival.first_received_at_sec,now=time.perf_counter):
            raise ValueError('PNG local decode expired; deadline not extended')
        pair=receiver.take(time.perf_counter())
        decoded,decoded_cpu=time.perf_counter(),time.process_time()
        if pair is None or pair.candidate!=candidate or pair.candidate['local_pair_available']:
            raise ValueError('PNG exact one-shot candidate delivery failed')
        if probe.sha_bytes(pair.image.tobytes())!=probe.sha_bytes(image.tobytes()):
            raise ValueError('PNG changed original inference pixels')
        return pair.image,dict(encode_ms=(encoded-start)*1000,encode_cpu_ms=(enc_cpu-cpu)*1000,
            sender_prepare_ms=(prepared-encoded)*1000,sender_prepare_cpu_ms=(prep_cpu-enc_cpu)*1000,
            reassembly_validate_ms=(assembled-first_received)*1000,
            reassembly_cpu_ms=(assembled_cpu-prep_cpu)*1000,
            decode_validate_copy_ms=(decoded-assembled)*1000,decode_cpu_ms=(decoded_cpu-assembled_cpu)*1000,
            codec_receiver_stage_ms=(decoded-first_received)*1000,
            packet_bytes=len(wire),fragment_count=count,fragmented_bytes=fragmented_bytes,
            packet_sha256=pair.packet_sha256,packet_candidate=candidate,
            first_received_at_sec=first_received,encode_started_at_sec=start)
    finally:
        receiver.close();assembler.close()


def measure(job,variant,sequence,engine,predictor,sync=lambda:None,memory=None):
    if variant not in ('original','packet'):raise ValueError('exact original or PNG packet variant required')
    original=job['image'];before=probe.sha_bytes(original.tobytes())
    if original.flags.writeable or before!=job['pixel_sha256']:raise ValueError('modified source image')
    image=original
    codec=dict(encode_ms=0.,encode_cpu_ms=0.,sender_prepare_ms=0.,sender_prepare_cpu_ms=0.,
        reassembly_validate_ms=0.,reassembly_cpu_ms=0.,decode_validate_copy_ms=0.,decode_cpu_ms=0.,
        codec_receiver_stage_ms=0.,packet_bytes=None,fragment_count=0,fragmented_bytes=None,
        packet_sha256=None,packet_candidate=None,first_received_at_sec=None,encode_started_at_sec=None)
    if variant=='packet':image,codec=roundtrip(original,sequence)
    pixel=probe.sha_bytes(image.tobytes())
    if pixel!=before or image.flags.writeable:raise ValueError('exact readonly inference pixels required')
    frame=probe.NativeFrame('c'*32,sequence,(sequence-1)/30.,float(sequence),image)
    sync()
    if memory is not None:memory('reset')
    start,cpu=time.perf_counter(),time.process_time()
    boxes=predictor(frame);sync()
    inferred,inferred_cpu=time.perf_counter(),time.process_time()
    value=engine.measure(frame,boxes,float(sequence))
    done,done_cpu=time.perf_counter(),time.process_time()
    if any(value.get(k) is not False for k in probe.FLAGS):raise ValueError('unexpected measurement authority')
    if image.flags.writeable or probe.sha_bytes(image.tobytes())!=pixel:
        raise ValueError('predictor modified inference pixels')
    if original.flags.writeable or probe.sha_bytes(original.tobytes())!=before:
        raise ValueError('predictor modified original pixels')
    receiver_ms=(done-codec['first_received_at_sec'])*1000 if variant=='packet' else (done-start)*1000
    full_ms=(done-codec['encode_started_at_sec'])*1000 if variant=='packet' else receiver_ms
    return dict(schema='offline_lossless_GPU_sample_v1',variant=variant,sequence=sequence,
        packet_codec='PNG_RGB8_LOSSLESS' if variant=='packet' else None,
        source_path=job['path'],source_png_sha256=job['png_sha256'],source_pixel_sha256=before,
        inference_pixel_sha256=pixel,raw_detector_boxes=copy.deepcopy(boxes),
        detector_signature=probe.detector_signature(boxes),measurement=value,
        target_roi_native_xyxy=ROIS.get(Path(job['path']).name),
        geometry_age_basis='synthetic_zero_age_OFFLINE_NOT_live_freshness',
        packet_identity_basis='synthetic_replay_admission_NOT_original_capture',
        exact_pixels=True,mean_absolute_pixel_difference=0.,pixel_mse=0.,psnr_db=None,
        predict_sync_ms=(inferred-start)*1000,predict_cpu_ms=(inferred_cpu-cpu)*1000,
        support_geometry_ms=(done-inferred)*1000,support_cpu_ms=(done_cpu-inferred_cpu)*1000,
        receiver_stage_ms=receiver_ms,full_local_pipeline_ms=full_ms,
        sender_encode_plus_receiver_stage_ms=full_ms,
        receiver_first_to_geometry_within_200ms=variant=='packet' and receiver_ms<=200.,
        pytorch_memory_bytes=None if memory is None else memory('read'),
        source_freshness_verified=False,actual_camera_capture_performed=False,
        actual_network_or_continuous_rate_measured=False,**codec,**probe.FLAGS)


def benchmark(jobs,predictor,factory,*,repetitions=5,warmup=3,sync=lambda:None,memory=None,output=None):
    if (type(repetitions) is not int or not 1<=repetitions<=20 or type(warmup) is not int
            or not 1<=warmup<=10 or not 1<=len(jobs)<=4):raise ValueError('bounded benchmark required')
    rows=[];pairs=[];sequence=used=0;deadline=time.monotonic()+180.
    stream=(Path(output)/'samples.jsonl').open('xb') if output is not None else None
    try:
        for job in jobs:
            engines={v:factory(job) for v in ('original','packet')}
            for index in range(2*warmup+4*repetitions):
                if time.monotonic()>deadline:raise TimeoutError('180-second measurement budget exceeded')
                measured=index>=2*warmup;position=(index-2*warmup)%4
                variant=('original','packet','packet','original')[position] if measured else ('original','packet')[index%2]
                sequence+=1
                row=measure(job,variant,sequence,engines[variant],predictor,sync,memory)
                if not measured:continue
                row.update(cycle=(index-2*warmup)//4,abba_position=position)
                line=probe.json_bytes(row);used+=len(line)
                if used>probe.MAX_LOG:raise ValueError('bounded measurement log exceeded')
                if stream is not None:stream.write(line);stream.flush()
                rows.append(row)
                if position==3:
                    a,b,c,d=rows[-4:];pairs.extend((probe.compare_pair(a,b),probe.compare_pair(d,c)))
            probe.assert_originals([job])
    finally:
        if stream is not None:stream.close()
    return rows,pairs


def summarize(rows,pairs):
    value=probe.summarize(rows,pairs)
    for variant in ('original','packet'):
        selected=[r for r in rows if r['variant']==variant]
        for key in ('sender_prepare_ms','sender_prepare_cpu_ms','reassembly_validate_ms','reassembly_cpu_ms',
                    'codec_receiver_stage_ms','full_local_pipeline_ms'):
            value['groups'][variant][key]=probe.describe([r[key] for r in selected])
        value['groups'][variant]['fragmented_bytes']=probe.describe([r['fragmented_bytes'] for r in selected if r['fragmented_bytes'] is not None])
    value.update(packet_codec='PNG_RGB8_LOSSLESS',
        timing_scope='GPUPC_local_full_PNG_then_CUDA_NOT_camera_network_display',
        live_deadline_eligibility_transferred=False,source_freshness_verified=False)
    return value


def package(output,archive):
    output,archive=Path(output),Path(archive)
    summary=json.loads(probe.bounded_regular_bytes(output/'summary.json',512*1024))
    if summary.get('state')!='complete' or summary.get('schema')!='offline_lossless_GPU_summary_v1':
        raise ValueError('only complete PNG GPU results may be packaged')
    contents={n:probe.bounded_regular_bytes(output/n,probe.MAX_LOG) for n in (*RESULTS,'summary.json')}
    if (summary.get('actual_cuda_inference') is not True
            or set(summary.get('result_sha256',{}))!=set(RESULTS)
            or any(probe.sha_bytes(contents[n])!=sha for n,sha in summary['result_sha256'].items())):
        raise ValueError('complete actual-CUDA result hashes required')
    if sum(map(len,contents.values()))>64*1024*1024:raise ValueError('bounded result-only pack required')
    if archive.exists() or archive.is_symlink() or not archive.parent.is_dir() or output.resolve() in archive.resolve().parents:
        raise ValueError('unused archive outside output with existing parent required')
    with archive.open('xb') as target:
        with tarfile.open(fileobj=target,mode='w:xz') as bundle:
            for name,data in sorted(contents.items()):
                member=tarfile.TarInfo(output.name+'/'+name);member.size=len(data);member.mode=0o644;member.mtime=0
                bundle.addfile(member,io.BytesIO(data))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','run'))
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,default=MANIFEST)
    parser.add_argument('--search-root',type=Path,action='append')
    parser.add_argument('--device',type=int,default=0)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--experimental-rigid-mount',action='store_true')
    args=parser.parse_args(argv);created=False;summary={}
    try:
        if args.action=='run' and (not args.experimental_rigid_mount or args.output_dir is None or args.archive is None):
            raise ValueError('run requires explicit experimental acknowledgement, output and archive')
        jobs,settings,camera,profile,sha,manifest,inputs=inspect(args)
        if args.action=='run':
            output=args.output_dir.absolute();archive=args.archive.absolute()
            if (output.exists() or output.is_symlink() or archive.exists() or archive.is_symlink()
                    or not archive.parent.is_dir() or output.resolve()==archive.resolve()
                    or output.resolve() in archive.resolve().parents
                    or any(output.resolve()==Path(p).resolve() or output.resolve() in Path(p).resolve().parents for p in inputs)):
                raise ValueError('unused output/archive outside all inputs required; do not overwrite older runs')
        torch,gpu,runtime=cuda_environment(args.device)
        if args.action=='check':
            print(json.dumps(dict(state='READY_NOT_MEASURED',gpu=gpu,runtime=runtime,
                manifest_sha256=probe.digest(args.manifest),images=[dict(path=j['path'],png_sha256=j['png_sha256'],
                target_roi=ROIS[Path(j['path']).name]) for j in jobs],CUDA_tensor_test_passed=True,
                model_loaded=False,output_created=False),ensure_ascii=False,indent=2))
            return 0
        output.mkdir(parents=True,exist_ok=False);created=True
        summary=dict(schema='offline_lossless_GPU_summary_v1',state='initializing',work_date='2026-11-18',
            executed_utc=datetime.now(timezone.utc).isoformat(),gpu=gpu,runtime=runtime,
            actual_cuda_inference=False,source_code_sha256=manifest['source_code_sha256'],input_sha256=inputs,
            run_manifest_sha256=probe.digest(args.manifest),config_sha256=manifest['config_sha256'],profile_sha256=sha,
            original_pngs=[dict(path=j['path'],png_sha256=j['png_sha256'],pixel_sha256=j['pixel_sha256'],
                target_roi=ROIS[Path(j['path']).name]) for j in jobs],image_count=4,repetitions=5,
            warmup_calls_excluded=24,order='original/PNG/PNG/original',source_freshness_verified=False,
            physical_source_capture_or_odometry_reconstructed=False,live_transport_adopted=False,
            source_images_modified=False,images_written=False,**probe.FLAGS)
        probe.save_summary(output,summary)
        from cone_distance_worker import YoloConePredictor
        predictor=YoloConePredictor(args.weights,settings,output,args.device)
        def factory(job):
            return probe.MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,
                target_roi=ROIS[Path(job['path']).name],observer=probe.observe_upper_completion)
        def memory(action):
            if action=='reset':torch.cuda.reset_peak_memory_stats(args.device);return None
            return dict(peak_allocated=torch.cuda.max_memory_allocated(args.device),peak_reserved=torch.cuda.max_memory_reserved(args.device))
        start,cpu=time.perf_counter(),time.process_time()
        rows,pairs=benchmark(jobs,predictor,factory,sync=lambda:torch.cuda.synchronize(args.device),memory=memory,output=output)
        wall,process_cpu=time.perf_counter()-start,time.process_time()-cpu
        if len(rows)!=80 or len(pairs)!=40:raise ValueError('all 80 samples / 40 pairs required')
        probe.assert_originals(jobs)
        if any(probe.digest(p)!=v for p,v in inputs.items()) or any(probe.digest(ROOT/n)!=v for n,v in manifest['source_code_sha256'].items()):
            raise ValueError('input/code changed during GPU benchmark')
        per_image=[]
        for job in jobs:
            selected=[r for r in rows if r['source_png_sha256']==job['png_sha256']]
            selected_pairs=[p for p in pairs if p['source_png_sha256']==job['png_sha256']]
            per_image.append(dict(image=Path(job['path']).name,target_roi=ROIS[Path(job['path']).name],**summarize(selected,selected_pairs)))
        for name,value in (('per_image_summary.json',per_image),('run_manifest.json',manifest)):
            with (output/name).open('xb') as target:target.write(probe.json_bytes(value))
        with (output/'pairs.jsonl').open('xb') as target:
            for pair in pairs:target.write(probe.json_bytes(pair))
        summary.update(summarize(rows,pairs),state='complete',actual_cuda_inference=True,measured_samples=80,
            paired_samples=40,probe_wall_sec_including_warmup=wall,probe_process_CPU_sec_including_warmup=process_cpu,
            process_max_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            result_sha256={n:probe.digest(output/n) for n in RESULTS})
        probe.save_summary(output,summary);package(output,archive)
        print(json.dumps(dict(state='complete',images=4,measured_samples=80,paired_samples=40,
            pair_counts=summary['pair_counts'],archive=str(archive)),ensure_ascii=False,indent=2))
        return 0
    except (Exception,KeyboardInterrupt) as error:
        if created:
            summary.update(state='failed',error=f'{type(error).__name__}: {error}'[:2000]);probe.save_summary(output,summary)
        print(f'[ERROR] PNG GPU trial incomplete: {type(error).__name__}: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
