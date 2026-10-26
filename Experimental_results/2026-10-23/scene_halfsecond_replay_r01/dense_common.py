"""Explicit frozen dependencies for the offline half-second comparison."""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
UNIFORM = ROOT / 'Experimental_results/2026-10-22/scene_uniform_validation_r01'
REUSE = HERE.parent / 'scene_ray_reuse_r01'
LATENCY = HERE.parent / 'causal_availability_latency_r01'
CAUSAL = HERE.parent / 'causal_pose_replay_r01'
GEO = ROOT / 'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0] = [str(ROOT / 'src'), str(REUSE), str(GEO), str(CAUSAL), str(LATENCY)]
from cone_dataset import read_csv, write_csv, sha256
from run_comparison import CAMERA, FLOOR, canonical, compute
from replay_paired_costs import apply_pending
from replay_completion import replay
from finish_aware import FinishAwarePose, schedule

spec = importlib.util.spec_from_file_location('frozen_uniform_prepare', UNIFORM / 'prepare.py')
frozen_prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frozen_prepare)
time_grid = frozen_prepare.time_grid


def check_manifest(path):
    data = json.loads(path.read_text())
    for p, h in data.get('source_sha256', {}).items():
        if sha256(Path(p)) != h:
            raise ValueError(('changed frozen source', p))
    for name, h in data.get('output_sha256', {}).items():
        if sha256(path.parent / name) != h:
            raise ValueError(('changed frozen output', name))
    return data


def check_hashes(sources):
    for p, h in sources.items():
        if sha256(Path(p)) != h:
            raise ValueError(('changed source', p))
