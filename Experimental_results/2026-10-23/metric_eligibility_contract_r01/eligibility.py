"""Strict stateless evidence contract for offline diagnostics, never hardware."""
from dataclasses import dataclass,fields
import math


DIAGNOSTIC_CHECKS=(
    ('source_provenance_verified','source_provenance_unverified'),
    ('same_frame_inputs','frame_or_time_binding_unverified'),
    ('native_coordinate_contract','native_coordinate_contract_unverified'),
    ('calibration_candidate_checked','calibration_candidate_unchecked'),
    ('own_session_pose_candidate','no_own_session_temporally_checked_pose'),
    ('current_frame_observation','no_current_frame_observation'),
    ('image_support_quality','image_support_withheld'),
    ('floor_intersection_valid','floor_intersection_unavailable'),
)
PHYSICAL_CHECKS=(
    ('operational_intrinsics_verified','operational_intrinsics_acceptance_unverified'),
    ('recording_extrinsics_verified','recording_specific_extrinsics_unverified'),
    ('floor_contact_verified','physical_floor_contact_unverified'),
    ('distance_uncertainty_verified','distance_uncertainty_budget_unverified'),
)


@dataclass(frozen=True)
class Evidence:
    source_provenance_verified: bool
    same_frame_inputs: bool
    native_coordinate_contract: bool
    calibration_candidate_checked: bool
    own_session_pose_candidate: bool
    current_frame_observation: bool
    image_support_quality: bool
    floor_intersection_valid: bool
    raw_forward_m: float | None
    operational_intrinsics_verified: bool=False
    recording_extrinsics_verified: bool=False
    floor_contact_verified: bool=False
    distance_uncertainty_verified: bool=False

    def __post_init__(self):
        for f in fields(self):
            value=getattr(self,f.name)
            if f.name=='raw_forward_m':
                if value is not None and type(value) not in (int,float):
                    raise ValueError('raw distance must be a real number or None; no implicit coercion')
            elif type(value) is not bool:
                raise ValueError('explicit boolean evidence required: '+f.name)


def decide(evidence):
    if not isinstance(evidence,Evidence):raise TypeError('typed offline Evidence required')
    raw=evidence.raw_forward_m
    finite=raw is not None and math.isfinite(raw)
    positive=finite and raw>0
    diagnostic_blockers=[reason for field,reason in DIAGNOSTIC_CHECKS if not getattr(evidence,field)]
    if not positive:diagnostic_blockers.append('forward_distance_missing_nonfinite_or_nonpositive')
    physical_blockers=[reason for field,reason in PHYSICAL_CHECKS if not getattr(evidence,field)]
    diagnostic=not diagnostic_blockers
    verified=diagnostic and not physical_blockers
    return dict(
        numerical_candidate_available=bool(positive and evidence.floor_intersection_valid),
        audited_raw_forward_m=float(raw) if finite else None,
        offline_diagnostic_available=diagnostic,
        offline_diagnostic_distance_m=float(raw) if diagnostic else None,
        physical_metric_checks_satisfied=verified,
        physically_supported_distance_m=float(raw) if verified else None,
        state='PHYSICAL_CHECKS_SATISFIED_OFFLINE_ONLY' if verified else 'OFFLINE_DIAGNOSTIC_ONLY' if diagnostic else 'HOLD',
        diagnostic_blockers=tuple(diagnostic_blockers),physical_blockers=tuple(physical_blockers),
        all_blockers=tuple(diagnostic_blockers+physical_blockers),
        distance_imputed=False,clear_path_inferred=False,realtime_ready=False,usable_for_ffb=False)
