"""Reuse frozen all-frame inference implementation, redirecting only run paths."""
import importlib.util
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
SOURCE=HERE.parent/'cone_static_distance_r01/infer.py'
spec=importlib.util.spec_from_file_location('frozen_static_cone_inference',SOURCE)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.HERE=HERE


if __name__=='__main__':module.main()
