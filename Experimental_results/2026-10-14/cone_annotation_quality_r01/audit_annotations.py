"""Read-only label/visual-review snapshot; export only byte-identical raw examples."""
import json
from pathlib import Path
import shutil
import sys

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'src'))
from cone_dataset import label_path,parse_label,read_csv,sha256,verify_image,write_csv
from cone_detection_diagnostics import intersection_over_union
from prepare_cone_training_review import apply_selection_policy


def main():
    root=Path(__file__).resolve().parent
    if (root/'quality_summary.json').exists():
        raise ValueError('snapshot already exists; create a new dated audit version after label changes')
    queue=REPO/'datasets/cone/a_hardcase_review_v02'
    images=read_csv(queue/'manifest.csv')
    reviews={r['image']:r for r in read_csv(queue/'reviews.csv')}
    before={str(queue/name):sha256(queue/name) for name in ('manifest.csv','reviews.csv','dataset.json')}
    rows,pairs=[],[]
    for row in images:
        verify_image(queue,row)
        label=label_path(queue,row['image']);before[str(label)]=sha256(label)
        boxes=parse_label(label,reject_duplicates=False)
        width,height=int(row['width']),int(row['height'])
        coords=[]
        for index,(x,y,w,h) in enumerate(boxes):
            box=dict(x1=(x-w/2)*width,y1=(y-h/2)*height,x2=(x+w/2)*width,y2=(y+h/2)*height)
            coords.append(box)
            # Original full-frame visual review: only index3 of frame4651 is the small yellow-region box.
            rows.append(dict(image=row['image'],frame=row['frame'],gt_index=index,
                color_review='yellow' if int(row['frame'])==4651 and index==3 else 'red',
                reviewer='assistant full-original-frame and human-label coordinate review',
                independent_gt_quality_approval=False,**box,label_sha256=sha256(label),png_sha256=row['png_sha256']))
        for i in range(len(boxes)):
            for j in range(i+1,len(boxes)):
                overlap=intersection_over_union(coords[i],coords[j])
                if boxes[i]==boxes[j] or overlap>=.5:
                    pairs.append(dict(image=row['image'],frame=row['frame'],first_index=i,second_index=j,
                        exact_duplicate=int(boxes[i]==boxes[j]),iou=overlap,
                        scope='warning pair; visual object association required for nonidentical overlaps'))
        if reviews[row['image']]['label_sha256']!=sha256(label):raise ValueError('stale human review label hash')
    included,held=apply_selection_policy(queue,images,root/'selection_policy.csv')
    raw=root/'raw_examples';raw.mkdir(exist_ok=True)
    raw_rows=[]
    for row in images:
        if int(row['frame']) not in (4261,4651):continue
        target=raw/Path(row['image']).name
        if target.exists() and sha256(target)!=row['png_sha256']:raise ValueError('raw example changed; no overwrite')
        if not target.exists():shutil.copyfile(queue/row['image'],target)
        if sha256(target)!=row['png_sha256']:raise ValueError('exported PNG changed')
        raw_rows.append(dict(row,file=str(target.relative_to(root))))
    write_csv(root/'label_boxes.csv',rows)
    write_csv(root/'overlapping_annotation_pairs.csv',pairs)
    write_csv(root/'raw_example_manifest.csv',raw_rows)
    if any(sha256(Path(path))!=digest for path,digest in before.items()):raise ValueError('audit modified user annotation data')
    result=dict(date='2026-10-14',status='AUDITED_NOT_APPROVED_FOR_TRAINING',images=len(images),boxes=len(rows),
        red_region_boxes=sum(r['color_review']=='red' for r in rows),yellow_region_boxes=sum(r['color_review']=='yellow' for r in rows),
        exact_duplicate_pairs=sum(r['exact_duplicate'] for r in pairs),
        exact_duplicate_frames=sorted({int(r['frame']) for r in pairs if r['exact_duplicate']}),
        warning_overlap_frames=sorted({int(r['frame']) for r in pairs}),
        proposed_inclusions=len(included),proposed_holds=len(held),
        policy='Maintain red and yellow traffic_cone; defer additions with unresolved annotation scope. Inclusion still requires reannotation.',
        source_queue_sha256=before,selection_policy_sha256=sha256(root/'selection_policy.csv'),
        script_sha256=sha256(Path(__file__)),
        output_sha256={name:sha256(root/name) for name in ('label_boxes.csv','overlapping_annotation_pairs.csv','raw_example_manifest.csv')},
        user_annotations_modified=False,original_images_modified=False,training_performed=False,physical_output=False,
        limitations=['Assistant color/region review is not independent human label quality approval.',
                     'Unlabelled yellow scope is unresolved; do not claim 15 proven false-negative labels.',
                     'Exact duplicate prevention is structural; nonidentical duplicate-object boxes still need human review.'])
    target=root/'quality_summary.json'
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','images','boxes','red_region_boxes','yellow_region_boxes',
        'exact_duplicate_pairs','exact_duplicate_frames','warning_overlap_frames','proposed_inclusions','proposed_holds')},indent=2))


if __name__=='__main__':main()
