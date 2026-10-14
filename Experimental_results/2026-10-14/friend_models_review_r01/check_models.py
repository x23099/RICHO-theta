"""Restricted checkpoint intake and standalone cone inference, no deployment."""
import argparse
import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256,write_csv
from run_cone_review_frames import infer_frames,load_manifest
from run_cone_yolo import check_cuda

ALLOWED={
 'torch.nn.modules.activation.SiLU','torch.nn.modules.batchnorm.BatchNorm2d',
 'torch.nn.modules.container.ModuleList','torch.nn.modules.container.Sequential',
 'torch.nn.modules.conv.Conv2d','torch.nn.modules.linear.Identity',
 'torch.nn.modules.pooling.MaxPool2d','torch.nn.modules.upsampling.Upsample',
 'ultralytics.nn.modules.block.Attention','ultralytics.nn.modules.block.Bottleneck',
 'ultralytics.nn.modules.block.C2PSA','ultralytics.nn.modules.block.C3k',
 'ultralytics.nn.modules.block.C3k2','ultralytics.nn.modules.block.DFL',
 'ultralytics.nn.modules.block.PSABlock','ultralytics.nn.modules.block.SPPF',
 'ultralytics.nn.modules.conv.Concat','ultralytics.nn.modules.conv.Conv',
 'ultralytics.nn.modules.conv.DWConv','ultralytics.nn.modules.head.Detect',
 'ultralytics.nn.tasks.DetectionModel'}


def inspect(out):
    if (out/'checkpoint_inspection.json').exists():raise ValueError('inspection snapshot exists')
    import torch
    retained=ROOT/'runs/cone/received_friend_models_20261014_r01'
    retained.mkdir(parents=True,exist_ok=False)
    inventory={}
    for name in ('cone.pt','shiho_lane_mask_v2_best.pth'):
        source=Path('/home/robo25/Downloads')/name;target=retained/name
        shutil.copyfile(source,target)
        if sha256(source)!=sha256(target):raise ValueError('checkpoint copy differs')
        inventory[name]=dict(source=str(source),retained=str(target),bytes=source.stat().st_size,
            sha256=sha256(source),unsafe_globals=torch.serialization.get_unsafe_globals_in_checkpoint(target))
    cone=Path(inventory['cone.pt']['retained']);unsafe=inventory['cone.pt']['unsafe_globals']
    if set(unsafe)-ALLOWED:raise ValueError('unknown checkpoint globals; do not perform unsafe loading')
    objects=[getattr(importlib.import_module(n.rsplit('.',1)[0]),n.rsplit('.',1)[1]) for n in unsafe]
    with torch.serialization.safe_globals(objects):ck=torch.load(cone,map_location='cpu',weights_only=True)
    m=ck.get('model') or ck.get('ema')
    if type(m).__name__!='DetectionModel' or m.names!={0:'cone'}:raise ValueError('only inspected single cone detection model supported')
    cfg=copy.deepcopy(m.yaml)
    modules={row[2] for row in cfg['backbone']+cfg['head']}
    if (cfg.get('nc')!=1 or cfg.get('scale')!='n' or cfg.get('yaml_file')!='yolo11n.yaml'
        or not modules<={'Conv','C3k2','C2PSA','SPPF','nn.Upsample','Concat','Detect'}):
        raise ValueError('architecture outside inspected YOLO11n structure')
    state={k:v.detach().cpu().float().clone() if v.is_floating_point() else v.detach().cpu().clone()
           for k,v in m.state_dict().items()}
    if any(v.is_floating_point() and not torch.isfinite(v).all() for v in state.values()):
        raise ValueError('nonfinite weights')
    # A fresh installed model will be reconstructed; serialized module hooks are not reused.
    torch.save(dict(state_dict=state,cfg=cfg,original_names=m.names),retained/'cone_tensor_only.pth')
    lane=torch.load(inventory['shiho_lane_mask_v2_best.pth']['retained'],map_location='cpu',weights_only=True)
    if set(lane)!={'state_dict','epoch','best_iou'}:raise ValueError('unexpected lane checkpoint layout')
    s=lane['state_dict']
    write_csv(out/'lane_tensor_shapes.csv',[dict(key=k,shape=json.dumps(list(v.shape)),dtype=str(v.dtype)) for k,v in s.items()])
    report=dict(status='CHECKPOINT_METADATA_INSPECTED_NOT_DEPLOYED',files=inventory,
        load_policy='weights_only=True; cone permits only listed installed torch/Ultralytics NN classes; reconstruct from tensors',
        cone=dict(architecture='YOLO11n DetectionModel',original_names=m.names,target_mapping={'0 cone':'0 traffic_cone'},
            original_training_version=ck.get('version'),date=ck.get('date'),
            train_args=ck.get('train_args'),reported_training_metrics=ck.get('train_metrics'),
            cfg=cfg,tensor_only_path=str(retained/'cone_tensor_only.pth'),
            tensor_only_sha256=sha256(retained/'cone_tensor_only.pth'),
            training_image_count_verified=False,training_color_coverage_verified=False),
        lane=dict(format='state_dict checkpoint, not standalone YOLO detector',tensor_entries=len(s),
            epoch=lane['epoch'],reported_best_iou=lane['best_iou'],
            final_convolution_shape=list(s['model.42.conv.weight'].shape),
            metadata_keys=list(lane),inference_performed=False,
            missing=['model architecture/forward definition','resize/letterbox/input dimensions',
                     'RGB/BGR and normalization','foreground/background channel mapping and postprocessing'],
            note='2 output channels suggest segmentation, but task/architecture/channel meaning cannot be proven from shape alone'),
        runtime_changed=False,ffb_output=False,script_sha256=sha256(Path(__file__)))
    (out/'checkpoint_inspection.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(cone=report['cone']['architecture'],lane=report['lane']),indent=2))


def infer(out,imgsz):
    run=out/f'cone_inference_{imgsz}'
    run.mkdir(parents=True,exist_ok=False)
    config=run/'ultralytics_config';(config/'Ultralytics').mkdir(parents=True)
    os.environ.update(YOLO_CONFIG_DIR=str(config),YOLO_OFFLINE='true',YOLO_AUTOINSTALL='false')
    import torch
    from ultralytics.nn.tasks import DetectionModel
    from ultralytics.models.yolo.detect.predict import DetectionPredictor
    from ultralytics import settings
    for key in ('wandb','comet','clearml','mlflow','neptune','hub'):
        if key in settings:settings.update({key:False})
    receipt=json.loads((out/'checkpoint_inspection.json').read_text())
    tensor_path=Path(receipt['cone']['tensor_only_path'])
    if sha256(tensor_path)!=receipt['cone']['tensor_only_sha256']:raise ValueError('sanitized weights changed')
    saved=torch.load(tensor_path,map_location='cpu',weights_only=True)
    model=DetectionModel(cfg=saved['cfg'],ch=3,nc=1,verbose=False)
    model.load_state_dict(saved['state_dict'],strict=True)
    model.names={0:'traffic_cone'};model.eval().float()
    gpu=check_cuda(torch,0)
    kwargs=dict(device=0,imgsz=imgsz,conf=.01,iou=.7,max_det=300,rect=False,quantize=32,batch=1,
        augment=False,save=False,save_txt=False,save_crop=False,show=False,visualize=False,verbose=False)
    predictor=DetectionPredictor(overrides=kwargs);predictor.setup_model(model=model,verbose=False)
    class Adapter:
        def predict(self,source,**unused):return predictor(source=source,stream=False)
    manifest=[]
    for key,dataset,split in [('b','datasets/cone/ab_bootstrap_augmented_v03','val'),
        ('d','datasets/cone/de_negative_train_review_v01','train'),('e','datasets/cone/de_evaluation_review_v01','val')]:
        for row in read_csv(ROOT/dataset/'manifest.csv'):
            if row['split']!=split:continue
            manifest.append(dict(row,file=str(Path(dataset)/row['image']),
                reason=f'friend model offline review: {key}; no training',original_image=row['image'],source_set=key))
    write_csv(run/'raw_review_manifest.csv',manifest)
    images=load_manifest(ROOT,run/'raw_review_manifest.csv')
    args=SimpleNamespace(input_dir=ROOT,output_dir=run,device=0,imgsz=imgsz,prediction_floor=.01,nms_iou=.7,max_det=300)
    summary=infer_frames(Adapter(),args,images)
    (run/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (run/'provenance.json').write_text(json.dumps(dict(status=summary['status'],gpu=gpu,
        checkpoint_sha256=receipt['files']['cone.pt']['sha256'],tensor_checkpoint_sha256=sha256(tensor_path),
        prediction_kwargs=kwargs,manifest_sha256=sha256(run/'raw_review_manifest.csv'),
        all_tensors_strictly_loaded=True,original_names=receipt['cone']['original_names'],
        canonical_mapping='class0 cone -> class0 traffic_cone for comparison ONLY',
        architecture_reconstructed=True,training_performed=False,ffb_output=False,
        model_source_data_overlap_unknown=True,script_sha256=sha256(Path(__file__))),indent=2)+'\n')
    print(json.dumps(dict(imgsz=imgsz,images=len(images),predictions=summary['predictions']),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('inspect','infer'))
    parser.add_argument('--imgsz',type=int,choices=(640,960),default=960);args=parser.parse_args()
    root=Path(__file__).resolve().parent
    if args.stage=='inspect':inspect(root)
    else:infer(root,args.imgsz)
