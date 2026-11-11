"""Compact-comparison GPU r03 audit; reuse bounded validation, no CUDA here."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('guarded_upload_review',
    ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r02/review.py')
REVIEW=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(REVIEW)
EXPECTED=['src/cone_bbox_boundary_shadow.py','src/cone_guarded_lower_edge_shadow.py',
    'src/cone_guarded_stream_comparison.py','src/cone_self_body_shadow.py']


if __name__=='__main__':
    REVIEW.main(dict(archive_root='guarded_cuda_gpu_r03',
        previous_dir=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r02',
        previous_audit=ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r02/results_r01/audit.json',
        expected_sources=EXPECTED,schema='guarded_cuda_gpu_compact_archive_audit_v1'),extra_sources=(Path(__file__),))
