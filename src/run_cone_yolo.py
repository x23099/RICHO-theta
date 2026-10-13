#!/usr/bin/env python3
"""Offline YOLO environment/train/validation runner. No camera, ROS or FFB."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from cone_dataset import invalidate_label_caches, sha256, validate
from cone_detection_diagnostics import diagnostic_config, prediction_kwargs, prepare_inputs, run_diagnostics

REPO=Path(__file__).resolve().parents[1]


def build_parser():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("env","train","val","test","diagnose"))
    parser.add_argument("--dataset",type=Path)
    parser.add_argument("--weights",type=Path)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--device",type=int,default=0)
    parser.add_argument("--epochs",type=int,default=50)
    parser.add_argument("--batch",type=int,default=8)
    parser.add_argument("--imgsz",type=int,default=960)
    parser.add_argument("--seed",type=int,default=0)
    parser.add_argument("--diagnostic-split",choices=('val','test'),default='val')
    parser.add_argument("--confidence-thresholds",type=float,nargs='+',default=[.05,.1,.25,.5,.75])
    parser.add_argument("--prediction-floor",type=float,default=.01)
    parser.add_argument("--match-iou",type=float,default=.5)
    parser.add_argument("--nms-iou",type=float,default=.7)
    parser.add_argument("--max-det",type=int,default=300)
    parser.add_argument("--object-attributes",type=Path)
    parser.add_argument("--dry-run",action="store_true")
    return parser


def validated_args(args):
    if args.device<0 or args.epochs<1 or args.batch<1 or args.imgsz<32 or args.imgsz%32:
        raise ValueError("device>=0, epochs/batch>=1, imgsz positive multiple of 32 required")
    args.output_dir=args.output_dir.expanduser().resolve()
    if args.mode in ('env','train') and args.weights is None:
        args.weights=REPO/'src/yolov8n.pt'
    if args.weights is None: raise ValueError("explicit trained --weights required for val/test/diagnose")
    args.weights=args.weights.expanduser().resolve()
    if not args.weights.is_file(): raise ValueError("local trusted checkpoint required; no automatic download")
    if args.mode!='env':
        if args.dataset is None: raise ValueError("dataset required")
        args.dataset=args.dataset.expanduser().resolve()
        if args.output_dir.is_relative_to(args.dataset) or args.dataset.is_relative_to(args.output_dir):
            raise ValueError("run outputs and dataset must not overlap")
    if args.output_dir.exists(): raise ValueError("new output directory required; previous runs are not overwritten")
    if args.mode=='diagnose':
        diagnostic_config(args)
        if args.output_dir.is_relative_to(args.weights.parent):
            raise ValueError('diagnostic output must not overlap the checkpoint directory')
        if args.object_attributes is not None:
            args.object_attributes=args.object_attributes.expanduser().resolve()
            if not args.object_attributes.is_file() or args.object_attributes.is_relative_to(args.output_dir):
                raise ValueError('existing input attribute file outside new output required')
    return args


def model_kwargs(args):
    if args.mode=='diagnose':
        return prediction_kwargs(args)
    common=dict(data=str(args.dataset/'data.yaml'),device=args.device,imgsz=args.imgsz,batch=args.batch,
                project=str(args.output_dir),name='model',exist_ok=False,plots=False,workers=0)
    if args.mode=='train':
        # Test remains excluded. Match inference's fixed camera orientation.
        common.update(epochs=args.epochs,seed=args.seed,deterministic=True,
                      flipud=0.,fliplr=0.,degrees=0.,perspective=0.)
    else:
        common['split']='test' if args.mode=='test' else 'val'
    return common


def check_cuda(torch,device):
    if not torch.cuda.is_available() or device>=torch.cuda.device_count():
        raise ValueError("CUDA GPU unavailable in this Python. Use the GPU PC and a compatible PyTorch build; no CPU fallback.")
    # Real tensor operation, not only an import or device name check.
    torch.ones((2,2),device=f'cuda:{device}').sum().item()
    return dict(name=torch.cuda.get_device_name(device),index=device,torch_version=str(torch.__version__),
                torch_cuda_version=torch.version.cuda)


def main():
    parser=build_parser()
    args=parser.parse_args()
    try:
        args=validated_args(args)
        kwargs=model_kwargs(args) if args.mode!='env' else None
        if args.dry_run:
            print(json.dumps(dict(mode=args.mode,weights=str(args.weights),output=str(args.output_dir),
                kwargs=kwargs,diagnostic_config=diagnostic_config(args) if args.mode=='diagnose' else None,
                status='PREVIEW_ONLY_NO_DATASET_GPU_OR_MODEL_VERIFICATION'),indent=2))
            return
        dataset_check=validate(args.dataset,require_test=args.mode=='test' or
            (args.mode=='diagnose' and args.diagnostic_split=='test')) if args.mode!='env' else None
        diagnostic_inputs=prepare_inputs(args.dataset,args.diagnostic_split,args.object_attributes) \
            if args.mode=='diagnose' else None
        import torch
        gpu=check_cuda(torch,args.device)
        args.output_dir.mkdir(parents=True,exist_ok=False)
        # Create the actual settings root before importing Ultralytics, avoiding /tmp fallback.
        config_dir=args.output_dir/'ultralytics_config'
        (config_dir/'Ultralytics').mkdir(parents=True)
        os.environ['YOLO_CONFIG_DIR']=str(config_dir)
        from ultralytics import YOLO
        # Disable third-party experiment uploads; do not alter user's global settings.
        from ultralytics import settings
        for key in ('wandb','comet','clearml','mlflow','neptune','hub'):
            if key in settings: settings.update({key:False})
        model=YOLO(str(args.weights or REPO/'src/yolov8n.pt'))
        if args.mode!='train' and args.mode!='env' and model.names!={0:'traffic_cone'}:
            raise ValueError("val/test/diagnose require the trained single-class traffic_cone model")
        caches_removed=invalidate_label_caches(args.dataset) if args.mode in ('train','val','test') else []
        provenance=dict(mode=args.mode,gpu=gpu,versions={name:importlib.metadata.version(name)
            for name in ('torch','torchvision','ultralytics','opencv-python')},
            dataset_check=dataset_check,weights_sha256=sha256(args.weights or REPO/'src/yolov8n.pt'),
            kwargs=kwargs,runner_sha256=sha256(Path(__file__)),dataset_tool_sha256=sha256(Path(__file__).with_name('cone_dataset.py')),
            status='STARTED_NOT_MODEL_ACCURACY_PASS',physical_output=False,regenerable_label_caches_removed=caches_removed)
        if args.mode=='diagnose':
            provenance.update(diagnostic_config=diagnostic_config(args),
                diagnostic_tool_sha256=sha256(Path(__file__).with_name('cone_detection_diagnostics.py')),
                object_attributes_sha256=sha256(args.object_attributes) if args.object_attributes else None)
        (args.output_dir/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
        (args.output_dir/'environment_freeze.txt').write_text(subprocess.check_output(
            [sys.executable,'-m','pip','freeze'],text=True))
        if args.mode=='env':
            import numpy as np
            model.predict(source=np.zeros((720,1280,3),dtype=np.uint8),device=args.device,
                          imgsz=args.imgsz,save=False,show=False,verbose=False)
            provenance['synthetic_forward']='PASS_NOT_REAL_DETECTION_ACCURACY'
            print(json.dumps(dict(status='PASS_GPU_MODEL_LOAD_AND_SYNTHETIC_FORWARD',gpu=gpu),indent=2))
        elif args.mode=='diagnose':
            run_diagnostics(model,args,diagnostic_inputs)
            print(f"[INFO] Diagnostics completed: {args.output_dir/'analysis_report.md'}")
        else:
            result=model.train(**kwargs) if args.mode=='train' else model.val(**kwargs)
            (args.output_dir/'metrics.json').write_text(json.dumps(dict(result.results_dict),indent=2)+'\n')
            print(f"[INFO] {args.mode} completed. Metrics: {args.output_dir/'metrics.json'}")
        provenance['status']='COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL'
        (args.output_dir/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    except (ValueError,OSError,ImportError,KeyError) as error:
        parser.exit(2,f"[ERROR] {error}\n")


if __name__=='__main__': main()
