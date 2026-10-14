"""Save fixed inputs and human review provenance for the D-negative experiment."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import label_path,read_csv,sha256,validate,write_csv


def main():
    output=Path(__file__).resolve().parent
    if (output/'input_receipt.json').exists():raise ValueError('input snapshot already exists')
    dataset=ROOT/'datasets/cone/ab_negative_augmented_v04'
    reference=ROOT/'datasets/cone/ab_bootstrap_augmented_v03'
    queue=ROOT/'datasets/cone/de_negative_train_review_v01'
    evaluation=ROOT/'datasets/cone/de_evaluation_review_v01'
    check=validate(dataset);validate(reference)
    reviews=read_csv(queue/'reviews.csv')
    if len(reviews)!=16 or any(r['status']!='negative' for r in reviews):
        raise ValueError('16 explicitly reviewed D negatives required')
    for row in read_csv(reference/'manifest.csv'):
        for path in (row['image'],str(label_path(reference,row['image']).relative_to(reference))):
            if sha256(reference/path)!=sha256(dataset/path):raise ValueError('reference image/label changed')
    eimages=read_csv(evaluation/'manifest.csv');train=read_csv(dataset/'manifest.csv')
    if ({r['source_raw_sha256'] for r in eimages}&{r['source_raw_sha256'] for r in train}
            or {r['decoded_bgr_sha256'] for r in eimages}&{r['decoded_bgr_sha256'] for r in train}
            or {r['group_id'] for r in eimages}&{r['group_id'] for r in train}):
        raise ValueError('E evaluation source/group/pixels leaked into training dataset')
    write_csv(output/'human_review_snapshot.csv',reviews)
    write_csv(output/'added_negative_manifest.csv',read_csv(queue/'manifest.csv'))
    paths=[root/name for root in (dataset,reference,queue,evaluation)
           for name in ('manifest.csv','reviews.csv','dataset.json')]
    initial=ROOT/'src/yolov8n.pt';paths.append(initial)
    for root in (dataset,reference):paths.append(root/'data.yaml')
    paths.extend(ROOT/'Experimental_results/2026-10-14/cone_de_intake_r01'/name for name in
                 ('assistant_reference_boxes.csv','positive_target_associations.csv','frozen_comparison.json'))
    result=dict(status='FIXED_INPUTS_NOT_TRAINING_OR_MODEL_APPROVAL',counts=check['counts'],
        human_confirmation=dict(user_message='全てコーンを確認できませんでした。進めてください',
            context='preceding instruction: 16 D images, N->Y when both lenses contain no cone',
            original_gui_saved_negative=15,original_gui_pending=1,
            original_reviews_sha256='0f10195e907c4d9877d4e332d02ad3a8b2ad705e4f4a9dac72de2497941804a1',
            completed_by_chat_confirmation_image='images/train/block_d_20261014_b1e739125cc2a88d_f000001.png',
            final_reviews_sha256=sha256(queue/'reviews.csv'),date='2026-10-14'),
        original_reference_images_and_labels_byte_identical=True,e_not_in_training=True,
        input_sha256={str(p):sha256(p) for p in paths},
        recipe=dict(epochs=50,batch=8,imgsz=960,seed=0,amp=False,offline=True,
                    initial_weights_sha256=sha256(initial)),
        frozen_thresholds=[.25,.5],
        limits=['Water bottle D02 samples are now training data; their post-training score is resubstitution, NOT holdout accuracy.',
                'B is repeated development validation used to select best epoch; E is separate capture, never training.',
                'E color reference boxes remain assistant/nonblinded unless explicitly human reviewed.',
                'No automatic runtime deployment or FFB activation.'])
    (output/'input_receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(check['counts'],indent=2))


if __name__=='__main__':main()
