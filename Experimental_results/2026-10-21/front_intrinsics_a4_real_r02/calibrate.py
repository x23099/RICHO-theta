"""Execute unchanged calibration tool only after observation and target review gates."""
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256
from prepare_fisheye_calibration import fit


def main():
    output=HERE/'candidate_r01'
    if output.exists():
        raise ValueError('no candidate output overwrite')
    path=HERE/'extraction_r01/observations.json'
    j=json.loads(path.read_text())
    confirmation=json.loads((HERE/'user_confirmation.json').read_text())
    review=json.loads((HERE/'target_review.json').read_text())
    assert confirmation['measured_square_mm']==20.
    assert review['moving_paper_identity_representatives_confirmed']
    source={str(p):sha256(p) for p in (path,HERE/'user_confirmation.json',HERE/'target_review.json',
        HERE/'method.md',HERE/'extract.py',Path(__file__),ROOT/'src/fisheye_intrinsic_calibration.py',
        ROOT/'src/prepare_fisheye_calibration.py',HERE/'raw_samples/raw_f000472.png')}
    # Reference PNG is independently verified against native intake manifest.
    import csv
    with (HERE/'raw_sample_manifest.csv').open(newline='') as f:
        reference=next(r for r in csv.DictReader(f) if r['frame']=='472')
    assert sha256(HERE/reference['file'])==reference['png_sha256']
    output.mkdir()
    summary=dict(prefit_checks=j['prefit_checks'],retained_views=len(j['retained_views']),
        measured_square_mm=20.,intrinsic_solver_attempted=False,physical_output=False,
        original_images_edited=False,production_settings_changed=False,usable_for_ffb=False,
        source_sha256=source,source_reference_matches_native_manifest=True)
    if not all(j['prefit_checks'].values()):
        summary.update(decision='NO_FIT_INSUFFICIENT_OBSERVATIONS')
    else:
        summary['intrinsic_solver_attempted']=True
        try:
            result=fit(path,20.,output)
            summary.update(decision=result['decision'],checks=result['checks'],
                train_frames=[j['retained_views'][i]['frame'] for i in result['train_indices']],
                validation_frames=[j['retained_views'][i]['frame'] for i in result['validation_indices']],
                calibration_rms_px=result['calibration_rms_px'],pose_validation_rms_px=result['pose_validation_rms_px'],
                K=result['K'],D=result['D'],normal_spread_deg=result['normal_spread_deg'])
        except (ValueError,RuntimeError) as error:
            summary.update(decision='SOLVER_REJECTED_NO_APPROVED_INTRINSICS',error_type=type(error).__name__,error=str(error))
        except Exception as error:
            # OpenCV exposes cv2.error outside RuntimeError on some builds.
            import cv2
            if not isinstance(error,cv2.error):
                raise
            summary.update(decision='SOLVER_REJECTED_NO_APPROVED_INTRINSICS',error_type='cv2.error',error=str(error))
    assert all(sha256(Path(p))==digest for p,digest in source.items())
    summary['output_sha256']={p.name:sha256(p) for p in output.iterdir() if p.is_file()}
    (output/'run_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
