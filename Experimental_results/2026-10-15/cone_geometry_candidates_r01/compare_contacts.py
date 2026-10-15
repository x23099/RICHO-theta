"""Same-frame bbox/manual base candidates under frozen floor-derived geometry."""
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256,write_csv
from geometry_models import PRIMARY,project_floor_to_pixels,project_pixels_to_floor


def main():
    output=HERE/'contact_transfer_r01'
    if output.exists():raise ValueError('new contact comparison required; no overwrite')
    cone=HERE.parent/'cone_static_distance_r01'
    parameters_path=HERE/'results_r01/candidate_parameters.json'
    p=json.loads(parameters_path.read_text())['models'][PRIMARY]['parameters']
    anchors=read_csv(cone/'manual_contact_candidates.csv')
    frames={(r['condition'],int(r['frame'])):r for r in read_csv(cone/'analysis_r01/positions.csv')}
    sources=[Path(__file__),HERE/'geometry_models.py',parameters_path,
        cone/'manual_contact_candidates.csv',cone/'analysis_r01/positions.csv']
    sources.extend(cone/r['file'] for r in anchors)
    before={str(f):sha256(f) for f in sources}
    results=[]
    for anchor in anchors:
        old=frames[(anchor['condition'],int(anchor['frame']))]
        if old['measurement_used']!='True':raise ValueError('unambiguous source frame required')
        ref=[[float(old['reference_x_m']),float(old['reference_z_m'])]]
        expected=project_floor_to_pixels(ref,p)[0]
        bbox=[float(old['bottom_pixel_x']),float(old['bottom_pixel_y'])]
        manual=[float(anchor['pixel_x']),float(anchor['pixel_y'])]
        contacts=project_pixels_to_floor([bbox,manual],p)
        results.append(dict(condition=anchor['condition'],frame=anchor['frame'],file=anchor['file'],
            reference_x_m=ref[0][0],reference_z_m=ref[0][1],
            reference_basis='original cone capture-label coordinates, not floor calibration targets',
            expected_pixel_x_from_reference=float(expected[0]),expected_pixel_y_from_reference=float(expected[1]),
            bbox_pixel_x=bbox[0],bbox_pixel_y=bbox[1],manual_pixel_x=manual[0],manual_pixel_y=manual[1],
            bbox_minus_expected_x_px=float(bbox[0]-expected[0]),bbox_minus_expected_y_px=float(bbox[1]-expected[1]),
            manual_minus_expected_x_px=float(manual[0]-expected[0]),manual_minus_expected_y_px=float(manual[1]-expected[1]),
            candidate_bbox_x_m=float(contacts[0,0]),candidate_bbox_z_m=float(contacts[0,1]),
            candidate_manual_x_m=float(contacts[1,0]),candidate_manual_z_m=float(contacts[1,1]),
            candidate_manual_error_x_m=float(contacts[1,0]-ref[0][0]),candidate_manual_error_z_m=float(contacts[1,1]-ref[0][1]),
            floor_contact_verified=False,usable_for_ffb=False))
    output.mkdir(exist_ok=False)
    write_csv(output/'contact_representatives.csv',results)
    if any(sha256(Path(f))!=digest for f,digest in before.items()):raise ValueError('source changed')
    report=dict(status='COMPLETED_REFERENCE_POINT_COMPARISON_NOT_PHYSICAL_CONTACT_PROOF',
        geometry=PRIMARY,pixel_points_moved=False,parameters_fitted=False,physical_output=False,
        interpretation='predicted pixels from nominal coordinates explain residual direction only; NEVER move actual labels to these pixels',
        limits='different source sessions; cone base endpoint/dimensions pending clarification; assistant manual points nonblind and unverified',
        source_sha256=before,output_sha256={'contact_representatives.csv':sha256(output/'contact_representatives.csv')})
    (output/'provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:
        print(r['condition'],'manual Z',round(r['candidate_manual_z_m'],4),
            'manual minus expected pixel',round(r['manual_minus_expected_x_px'],2),round(r['manual_minus_expected_y_px'],2))


if __name__=='__main__':main()
