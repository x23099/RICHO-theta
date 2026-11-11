"""Exact-domain GPU r04 audit; bounded saved artifacts, no local CUDA/device."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('guarded_upload_review',
    ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r02/review.py')
REVIEW=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(REVIEW)
EXPECTED=['src/angular_fisheye_geometry.py','src/cone_distance_core.py',
    'src/cone_colour_support_candidate.py','src/cone_support_completion_candidate.py',
    'src/cone_upper_support_candidate.py',
    'Experimental_results/2026-11-11/guarded_cuda_replay_r01/cuda_replay.py']


if __name__=='__main__':
    REVIEW.main(dict(archive_root='guarded_cuda_gpu_r04',expected_source_count=25,
        previous_dir=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r03',
        previous_audit=ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r03/results_r01/audit.json',
        expected_sources=EXPECTED,schema='guarded_cuda_gpu_domain_archive_audit_v1'),extra_sources=(Path(__file__),))
