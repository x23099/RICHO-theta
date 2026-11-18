"""Audit the fixed three-image GPU suite; diagnose pixels vs boxes offline.

No CUDA/YOLO, image writes, live permission, or archive-provided instructions.
"""
import argparse
import csv
import importlib.util
import io
import json
import math
from pathlib import Path, PurePosixPath
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def module(name,path):
    spec = importlib.util.spec_from_file_location(name,path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


suite = module('suite_under_audit',HERE/'run_suite.py')
prior = module('packet_audit_helpers',ROOT/'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/audit_submission.py')
probe = suite.probe
PREFIX = 'packet_recompression_multi_gpu_r01/'
JSON_NAMES = ('summary.json','samples.jsonl','pairs.jsonl','suite_manifest.json','per_image_summary.json')


def read_archive(path):
    wire = probe.bounded_regular_bytes(path,16*1024*1024)
    selected,seen,size = {},set(),0
    with tarfile.open(fileobj=io.BytesIO(wire),mode='r:xz') as bundle:
        for n,item in enumerate(bundle):
            name = PurePosixPath(item.name)
            if (n >= 64 or name.is_absolute() or '..' in name.parts or item.name in seen
                    or not (item.isfile() or item.isdir()) or item.size < 0
                    or not name.parts or name.parts[0] != PREFIX.rstrip('/')):
                raise ValueError('unsafe/unexpected suite archive member')
            seen.add(item.name)
            size += item.size
            if size > 64*1024*1024:
                raise ValueError('expanded suite size limit')
            if item.name in {PREFIX+n for n in JSON_NAMES}:
                if not item.isfile() or not 0 < item.size <= probe.MAX_LOG:
                    raise ValueError('bounded regular result JSON required')
                selected[item.name[len(PREFIX):]] = bundle.extractfile(item).read(probe.MAX_LOG+1)
    if set(selected) != set(JSON_NAMES):
        raise ValueError('five suite JSON files required')
    values = {name:([prior.parse(l) for l in data.splitlines()] if name.endswith('.jsonl') else prior.parse(data))
              for name,data in selected.items()}
    summary,manifest = values['summary.json'],values['suite_manifest.json']
    if (summary.get('state') != 'complete' or summary.get('schema') != 'offline_packet_recompression_GPU_audit_v1'
            or summary.get('actual_cuda_inference') is not True
            or manifest.get('schema') != 'packet_saved_suite_GPU_v1'):
        raise ValueError('completed CUDA saved suite required')
    for name in ('samples.jsonl','pairs.jsonl'):
        if probe.sha_bytes(selected[name]) != summary['result_sha256'][name]:
            raise ValueError('suite result SHA mismatch')
    if (probe.sha_bytes(selected['per_image_summary.json']) != manifest['per_image_summary_sha256']
            or manifest['inputs'] != suite.manifest() or manifest['runner_sha256'] != suite.LEGACY_SHA
            or manifest['suite_runner_sha256'] != probe.digest(HERE/'run_suite.py')
            or any(manifest.get(k) is not False for k in probe.FLAGS)):
        raise ValueError('fixed input/runner/authority manifest mismatch')
    return wire,selected,values


def checked_results(values):
    summary,rows,pairs = (values[n] for n in ('summary.json','samples.jsonl','pairs.jsonl'))
    if (summary.get('image_count') != 3 or summary.get('measured_samples') != 60
            or summary.get('paired_samples') != 30 or summary.get('warmup_calls_excluded') != 18
            or summary.get('repetitions') != 5 or summary.get('target_roi_native_xyxy') != suite.ROI
            or len(rows) != 60 or len(pairs) != 30 or any(summary.get(k) is not False for k in probe.FLAGS)):
        raise ValueError('exact three-image suite protocol required')
    expected_pairs,by_image = [],[]
    for case,name in enumerate(suite.NAMES):
        sha = probe.KNOWN_IMAGES[name]
        chunk = rows[case*20:(case+1)*20]
        image_pairs = []
        for i,row in enumerate(chunk):
            if (row.get('source_png_sha256') != sha or row.get('sequence') != case*26+i+7
                    or row.get('variant') != ('original','packet','packet','original')[i%4]
                    or row.get('cycle') != i//4 or row.get('abba_position') != i%4
                    or row.get('detector_signature') != probe.detector_signature(row['raw_detector_boxes'])
                    or row.get('geometry_age_basis') != 'synthetic_zero_age_OFFLINE_NOT_live_freshness'
                    or row.get('source_freshness_verified') is not False
                    or row['measurement'].get('target_roi_native_xyxy') != suite.ROI
                    or any(row.get(k) is not False or row['measurement'].get(k) is not False for k in probe.FLAGS)):
                raise ValueError('suite sample order/identity/authority/signature mismatch')
            if i%4 == 3:
                a,b,c,d = chunk[i-3:i+1]
                image_pairs.extend((probe.compare_pair(a,b),probe.compare_pair(d,c)))
        expected_pairs.extend(image_pairs)
        by_image.append(dict(image=name,png_sha256=sha,target_roi_native_xyxy=suite.ROI,
                             **probe.summarize(chunk,image_pairs)))
    aggregate = probe.summarize(rows,pairs)
    if (not prior.equivalent(pairs,expected_pairs) or not prior.equivalent(values['per_image_summary.json'],by_image)
            or any(not prior.equivalent(summary.get(k),v) for k,v in aggregate.items())):
        raise ValueError('suite pair/per-image/aggregate does not reproduce')
    return aggregate,by_image


def contour_diagnostic(image,box,colour):
    """Same frozen mask, only JSON facts; never save mask/crop images."""
    import cv2
    from cone_distance_core import support_from_colour_mask
    left,top = math.floor(box['x1'])-4,math.floor(box['y1'])-4
    right,bottom = math.ceil(box['x2'])+4,math.ceil(box['y2'])+4
    hsv = cv2.cvtColor(image[top:bottom,left:right],cv2.COLOR_BGR2HSV)
    if colour == 'red':
        mask = cv2.inRange(hsv,(0,80,30),(10,255,255)) | cv2.inRange(hsv,(170,80,30),(179,255,255))
    elif colour == 'yellow':
        mask = cv2.inRange(hsv,(15,80,30),(40,255,255))
    else:
        raise ValueError('explicit already selected colour required')
    value = support_from_colour_mask(mask,left,top,evidence=True)
    return {k:value.get(k) for k in ('reason','point','crop_bounds','selected_contour_bounds',
                                    'touching_edges','contour_areas','qualifying_contour_count')}


def pixel_box_matrix(images,records,settings,camera,profile,profile_sha):
    result = []
    for image_kind,image in images.items():
        for box_kind,record in records.items():
            engine = probe.MotionRangeEngine(settings,camera,profile,profile_sha,acknowledged=True,
                target_roi=suite.ROI,observer=probe.observe_upper_completion)
            value = engine.measure(probe.NativeFrame('c'*32,1,0.,1.,image),record['raw_detector_boxes'],1.)
            selected = value['selected_detector_boxes']
            diagnostic = contour_diagnostic(image,selected[0],value['support_observation']['selected_colour']) if len(selected)==1 else None
            result.append(dict(image_variant=image_kind,boxes_variant=box_kind,
                result_kind='posthoc_cross_input_geometry_NOT_new_GPU_inference',
                distance_available=value['distance_available'],reason=value['reason'],
                range_m=value['horizontal_camera_foot_range_m'],support_pixel=value['support_pixel'],
                fixed_mask_diagnostic=diagnostic,**probe.FLAGS))
    return result


def run(archive,source_dir,intake,output):
    archive,source_dir = Path(archive).absolute(),Path(source_dir).resolve()
    intake,output = Path(intake).resolve(),Path(output).resolve()
    if (intake.exists() or output.exists() or intake==output or intake in output.parents or output in intake.parents
            or any(d==archive.resolve() or d in archive.resolve().parents or d==source_dir or d in source_dir.parents
                   for d in (intake,output))):
        raise ValueError('separate unused intake/output outside inputs required')
    wire,files,values = read_archive(archive)
    aggregate,by_image = checked_results(values)
    summary,rows = values['summary.json'],values['samples.jsonl']
    code = summary['source_code_sha256']
    expected = {'src/'+n for n in probe.CODE} | {str(suite.LEGACY.relative_to(ROOT))}
    if set(code)!=expected or any(probe.digest(ROOT/n)!=sha for n,sha in code.items()):
        raise ValueError('GPU measurement code version differs')
    jobs = probe.load_images([source_dir/name for name in suite.NAMES])
    settings,camera,_,_ = probe.load_config()
    profile,profile_sha = probe.load_motion_profile(probe.PROFILE,settings)
    expected_inputs = {settings['weights_sha256'],profile_sha,probe.digest(probe.DEFAULT_CONFIG),
                       *[j['png_sha256'] for j in jobs]}
    if (set(summary['input_sha256'].values()) != expected_inputs or summary['profile_sha256']!=profile_sha
            or summary['config_sha256']!=probe.digest(probe.DEFAULT_CONFIG)):
        raise ValueError('weights/profile/config/PNG input evidence differs')
    matrices,representatives = [],[]
    for job in jobs:
        selected = [r for r in rows if r['source_png_sha256']==job['png_sha256']]
        images,records = {},{}
        for row in selected:
            image = job['image']
            if row['variant']=='packet':
                image,codec = probe.packet_roundtrip(image,row['sequence'])
                if any(codec[k]!=row[k] for k in ('packet_bytes','packet_sha256','packet_candidate')):
                    raise ValueError('GPU packet wire cannot be reproduced')
            if (probe.sha_bytes(image.tobytes())!=row['inference_pixel_sha256']
                    or job['pixel_sha256']!=row['source_pixel_sha256']):
                raise ValueError('GPU inference pixels differ')
            engine = probe.MotionRangeEngine(settings,camera,profile,profile_sha,acknowledged=True,
                target_roi=suite.ROI,observer=probe.observe_upper_completion)
            seq = row['sequence']
            value = engine.measure(probe.NativeFrame('c'*32,seq,row['measurement']['media_time_sec'],float(seq),image),
                                   row['raw_detector_boxes'],float(seq))
            if not prior.equivalent(value,row['measurement']):
                raise ValueError('GPU logged support/geometry cannot be reproduced')
            images.setdefault(row['variant'],image)
            records.setdefault(row['variant'],row)
        matrix = pixel_box_matrix(images,records,settings,camera,profile,profile_sha)
        matrices.append(dict(image=Path(job['path']).name,source_png_sha256=job['png_sha256'],matrix=matrix))
        representatives.append(dict(image=Path(job['path']).name,
            measurements={v:r['measurement'] for v,r in records.items()}))
    probe.assert_originals(jobs)
    intake.mkdir(parents=True,exist_ok=False)
    with (intake/archive.name).open('xb') as target:target.write(wire)
    for name,data in files.items():
        with (intake/name).open('xb') as target:target.write(data)
    output.mkdir(parents=True,exist_ok=False)
    for name,value in (('per_image_summary.json',by_image),('pixel_box_matrix.json',matrices),
                       ('representative_measurements.json',representatives)):
        with (output/name).open('xb') as target:target.write(probe.json_bytes(value))
    with (output/'timing.csv').open('x') as target:
        keys=['source_png_sha256','variant','sequence','encode_ms','decode_validate_copy_ms',
              'predict_sync_ms','support_geometry_ms','receiver_stage_ms']
        writer=csv.DictWriter(target,fieldnames=keys);writer.writeheader()
        writer.writerows({k:r[k] for k in keys} for r in rows)
    audit = dict(schema='packet_saved_suite_submission_audit_v1',state='pass',
        archive_sha256=probe.sha_bytes(wire),raw_intake=str(intake),source_code_sha256=code,
        suite_runner_sha256=values['suite_manifest.json']['suite_runner_sha256'],
        audit_script_sha256=probe.digest(__file__),images=3,measured_samples=60,paired_samples=30,
        all_submitted_pairs_and_aggregates_reproduced=True,all_GPU_inference_pixels_reproduced=True,
        all_GPU_packet_wire_hashes_reproduced=True,all_GPU_support_and_geometry_reproduced=True,
        groups=aggregate['groups'],pair_counts=aggregate['pair_counts'],
        common_numeric_distance_pairs=aggregate['pair_counts']['both_numeric'],
        posthoc_pixel_box_swap_performed=True,new_GPU_inference_performed=False,
        source_images_modified_or_derived_images_written=False,
        compression_changes_withheld_to_numeric=aggregate['pair_counts']['original_withheld_packet_numeric']>0,
        absolute_accuracy_improvement_verified=False,live_transport_adopted=False,
        source_freshness_verified=False,**probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('state','measured_samples','common_numeric_distance_pairs',
        'pair_counts','compression_changes_withheld_to_numeric')},indent=2))
    return audit


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    run(args.archive,args.source_dir,args.intake_dir,args.output_dir)
