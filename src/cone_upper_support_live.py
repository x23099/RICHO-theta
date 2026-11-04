"""Opt-in independent upper-support log. Never changes the original row/GUI.

Uses the already accepted same-session model bytes, a separate image-quality
gate, and the existing range/freshness limits. Raw evidence is finite and
rate-limited. This module does not start a receiver, GPU, ROS, or FFB.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re

import cv2

from cone_fixed_floor_candidate import measure_support
from cone_fixed_floor_shadow import enforce_freshness
from cone_support_quality import ConeSupportQualityGate
from cone_upper_support_candidate import observe_upper_completion
from summarize_cone_distance_live import (number, text, _pixel_point, _sha256_text,
    validate_fixed_floor_shadow, validate_fixed_floor_load, reject_constant)
from theta_rtc_frames import native_frame

FLAGS=("controlling_distance","physical_metric_verified","floor_contact_verified","usable_for_ffb")
SCHEMA="cone_upper_support_live_comparison_v1"


def validate_record(row):
    if not isinstance(row,dict) or row.get("schema")!=SCHEMA:
        raise ValueError("upper comparison schema required")
    text(row.get("session"),"upper session")
    if type(row.get("frame")) is not int or row["frame"]<1:
        raise ValueError("positive upper frame required")
    source=number(row.get("source_time_sec"),"upper source",0)
    completed=number(row.get("completed_time_sec"),"upper completion",source)
    age=number(row.get("frame_age_ms"),"upper age",0)
    if abs(age-1000*(completed-source))>1e-6 or any(row.get(k) is not False for k in FLAGS):
        raise ValueError("upper time/authority mismatch")
    text(row.get("reason"),"upper reason")
    _sha256_text(row.get("config_sha256"),"upper config")
    candidate=row.get("upper_candidate")
    legacy=row.get("legacy_candidate")
    if legacy is not None and (not isinstance(legacy,dict) or any(legacy.get(k) is not False for k in FLAGS)):
        raise ValueError("unverified same-frame legacy candidate required")
    if candidate is not None:
        if not isinstance(candidate,dict) or any(candidate.get(k) is not False for k in FLAGS):
            raise ValueError("unapproved upper candidate required")
        point=_pixel_point(candidate.get("point"),"upper support")
        if point is not None and (not isinstance(candidate.get("support"),list) or point not in candidate["support"]):
            raise ValueError("upper point must be observed")
        if candidate.get("original_comparison")!=legacy:
            raise ValueError("upper candidate must use the same-frame legacy observation")
        for k in ("upper_completion_attempted","upper_completion_granted"):
            if type(candidate.get(k)) is not bool:raise ValueError("explicit upper completion verdict required")
        if candidate["upper_completion_granted"] and (point is None
                or not candidate["upper_completion_attempted"]
                or candidate.get("reason")!="unverified_upper_completed_colour_support"):
            raise ValueError("upper grant requires an attempted observed point")
    quality=row.get("upper_quality")
    if not isinstance(quality,dict) or type(quality.get("quality_accepted")) is not bool:
        raise ValueError("explicit separate image quality verdict required")
    if any(quality.get(k) is not False for k in ("floor_contact_verified","usable_for_ffb")):
        raise ValueError("image quality cannot approve contact or FFB")
    if quality["quality_accepted"] and (candidate is None or candidate.get("point") is None
            or [list(p) for p in (quality.get("observed_support") or [])]!=candidate["support"]):
        raise ValueError("quality must confirm the same observed upper support")
    legacy_shadow=row.get("legacy_fixed_floor_shadow")
    # Reuse the established result validator with explicit field aliases only.
    # The persisted new source remains 'upper_support_shadow', never mislabeled
    # as the original source. No acceptance condition is weakened here.
    view=dict(session=row["session"],frame=row["frame"],frame_age_ms=age,
        support_completion_shadow=dict(candidate=legacy),fixed_floor_shadow=legacy_shadow,
        fixed_floor_load=row.get("fixed_floor_load"),source_time_sec=source,completed_time_sec=completed)
    validate_fixed_floor_shadow(view)
    validate_fixed_floor_load(view)
    shadow=row.get("upper_fixed_floor_shadow")
    if shadow is not None:
        if not isinstance(shadow,dict) or shadow.get("support_source")!="upper_support_shadow":
            raise ValueError("explicit independent upper source required")
        if legacy_shadow is None or shadow.get("model_bundle_sha256")!=legacy_shadow.get("model_bundle_sha256"):
            raise ValueError("upper model must match current legacy model")
        if shadow.get("image_quality_accepted")!=quality["quality_accepted"]:
            raise ValueError("upper quality disagrees with comparison")
        geometric_view=dict(view,support_completion_shadow=dict(candidate=candidate),
            fixed_floor_shadow=dict(shadow,support_source="support_completion_shadow"))
        validate_fixed_floor_shadow(geometric_view)
    evidence=row.get("evidence")
    if not isinstance(evidence,dict):raise ValueError("explicit upper evidence state required")
    if evidence.get("status") not in ("not_requested","attempt_limit_reached","rate_limited","saved","save_error"):
        raise ValueError("known evidence status required")
    if evidence.get("status")=="saved":
        expected=f"upper_support_evidence/decoded_{row['session']}_f{row['frame']:06d}.png"
        if evidence.get("file")!=expected or evidence.get("pixels_unmodified") is not True:
            raise ValueError("same-frame unmodified evidence filename required")
        _sha256_text(evidence.get("sha256"),"upper evidence")
    available=shadow is not None and any(m["range_available"] for m in shadow["models"])
    if row.get("status")!=("UNVERIFIED_UPPER_COMPARISON" if available else "WITHHELD"):
        raise ValueError("upper status inconsistent with numeric values")


class UpperSupportLiveComparison:
    def __init__(self, settings, config_sha256, output_dir):
        self.settings=copy.deepcopy(settings)
        self.config_sha256=config_sha256
        self.output_dir=Path(output_dir)
        self.quality=ConeSupportQualityGate()
        self.owner=None
        self.evidence_attempts=0
        self.last_evidence_attempt=None

    def invalidate(self):
        self.owner=None
        self.quality.reset()

    def _evidence(self, frame, row, active):
        candidate=row["upper_candidate"]
        legacy=row["legacy_candidate"]
        eligible=(active and candidate is not None and legacy is not None
            and (legacy.get("point") is None or candidate.get("upper_completion_granted")))
        if not eligible:return dict(status="not_requested")
        now=frame.received_at
        if self.evidence_attempts>=20:return dict(status="attempt_limit_reached")
        if self.last_evidence_attempt is not None and now-self.last_evidence_attempt<1.:
            return dict(status="rate_limited")
        self.last_evidence_attempt=now;self.evidence_attempts+=1
        try:
            if re.fullmatch(r"[A-Za-z0-9_-]{1,128}",frame.session) is None:
                raise ValueError("safe evidence session basename required")
            folder=self.output_dir/"upper_support_evidence"
            if folder.is_symlink():raise ValueError("evidence folder must not be a symlink")
            folder.mkdir(exist_ok=True)
            path=folder/f"decoded_{frame.session}_f{frame.sequence:06d}.png"
            ok,encoded=cv2.imencode(".png",frame.image)
            if not ok or encoded.nbytes>4*1024*1024:raise ValueError("bounded native PNG encoding required")
            payload=encoded.tobytes()
            with path.open("xb") as stream:stream.write(payload)
            return dict(status="saved",file=str(path.relative_to(self.output_dir)),
                sha256=hashlib.sha256(payload).hexdigest(),pixels_unmodified=True)
        except Exception as exc:
            return dict(status="save_error",error=f"{type(exc).__name__}: {exc}")

    def observe(self, frame, baseline, adapter, camera, heading):
        native_frame(frame.image)
        if (baseline["session"],baseline["frame"],baseline["source_time_sec"])!=(frame.session,frame.sequence,frame.received_at):
            raise ValueError("upper observation requires the exact baseline frame")
        if baseline.get("frame_evidence",{}).get("floor_model",{}).get("config_sha256")!=self.config_sha256:
            raise ValueError("upper config must match the same-frame evidence")
        load=baseline.get("fixed_floor_load")
        validate_fixed_floor_load(baseline)
        active=adapter is not None and (load is None or load["state"]=="active")
        if active:
            legacy_shadow=baseline.get("fixed_floor_shadow")
            if (legacy_shadow is None or adapter.bundle_sha256!=legacy_shadow["model_bundle_sha256"]
                    or adapter.camera_sha256!=self.settings["camera_sha256"]):
                raise ValueError("current accepted model/legacy output required")
            owner=(frame.session,adapter.bundle_sha256,load.get("generation") if load else "startup",id(adapter))
        else:owner=None
        if owner!=self.owner or not active:
            self.quality.reset();self.owner=owner
        boxes=baseline.get("selected_detector_boxes",[])
        candidate=None
        error=None
        if len(boxes)==1:
            try:
                candidate=observe_upper_completion(frame.image,boxes[0],camera)
                if candidate["original_comparison"]!=baseline["support_completion_shadow"]["candidate"]:
                    raise ValueError("same-frame legacy candidate mismatch")
            except Exception as exc:
                candidate=None;error=f"{type(exc).__name__}: {exc}"
        point=(candidate or {}).get("point")
        observation=dict(support=(candidate or {}).get("support") if point is not None else None,
            unavailable_reason=(candidate or {}).get("reason","upper_observation_error" if error else "no_selected_support"))
        quality=self.quality.update(frame.received_at,[observation] if len(boxes)==1 else [{} for _ in boxes])
        result=dict(schema=SCHEMA,session=frame.session,frame=frame.sequence,
            source_time_sec=frame.received_at,completed_time_sec=baseline["completed_time_sec"],
            frame_age_ms=baseline["frame_age_ms"],config_sha256=self.config_sha256,
            legacy_candidate=copy.deepcopy((baseline.get("support_completion_shadow") or {}).get("candidate")),
            legacy_fixed_floor_shadow=copy.deepcopy(baseline.get("fixed_floor_shadow")),
            legacy_reason=baseline["reason"],selected_detector_boxes=copy.deepcopy(boxes),
            upper_candidate=candidate,upper_quality=quality,fixed_floor_load=copy.deepcopy(load),
            upper_fixed_floor_shadow=None,evidence=dict(status="not_requested"),
            reason="model_not_active",status="WITHHELD",**{k:False for k in FLAGS})
        if error:result["observation_error"]=error
        if active:
            reason=("model_session_mismatch" if adapter.bundle["session"]!=frame.session else
                "support_point_unavailable" if point is None else
                "image_support_quality_not_confirmed" if not quality["quality_accepted"] else None)
            shadow=dict(schema="fixed_floor_shadow_v1",session=frame.session,frame=frame.sequence,
                model_session=adapter.bundle["session"],model_bundle_sha256=adapter.bundle_sha256,
                camera_candidate_sha256=adapter.camera_sha256,heading_reference_sha256=adapter.bundle["heading_reference"]["sha256"],
                coordinate_frame="paper7_heading_carryover_camera_foot",support_source="upper_support_shadow",
                support_pixel=copy.deepcopy(point),image_quality_accepted=quality["quality_accepted"],
                image_quality_reason=quality["reason"],frame_age_limit_ms=500.,models=[],
                status="WITHHELD",reason=reason or "fixed_floor_intersection_unavailable",yaw_measured=False,
                **{k:False for k in FLAGS})
            for model in adapter.bundle["models"]:
                item=dict(model_name=model["name"],range_available=False,horizontal_camera_foot_range_m=None,reason=reason)
                if reason is None:
                    try:
                        measured=measure_support(point,model,camera,heading,session=frame.session,
                            diagnostic_range_m=self.settings["diagnostic_range_m"])
                        item.update(range_available=measured["range_available"],reason=measured["reason"],
                            horizontal_camera_foot_range_m=measured["horizontal_camera_foot_range_m"] if measured["range_available"] else None)
                    except Exception as exc:
                        item.update(reason="upper_geometry_error",error=f"{type(exc).__name__}: {exc}")
                shadow["models"].append(item)
            if any(m["range_available"] for m in shadow["models"]):
                shadow.update(status="CONDITIONAL_FIXED_FLOOR_SHADOW",reason="unverified_comparison_only")
            result["upper_fixed_floor_shadow"]=shadow
            result["reason"]=shadow["reason"]
        result["evidence"]=self._evidence(frame,result,active and adapter.bundle["session"]==frame.session)
        return result

    def finish(self, row, completed, *, baseline=None):
        if baseline is not None:
            if (baseline["session"],baseline["frame"])!=(row["session"],row["frame"]):
                raise ValueError("final legacy stamp must match upper frame")
            row["legacy_reason"]=baseline["reason"]
            row["legacy_fixed_floor_shadow"]=copy.deepcopy(baseline.get("fixed_floor_shadow"))
            row["inference_source"]=baseline.get("inference_source","injected_or_unverified_predictor")
        else:
            row.setdefault("inference_source","injected_or_unverified_predictor")
        row.update(completed_time_sec=completed,frame_age_ms=1000*(completed-row["source_time_sec"]))
        if row["legacy_fixed_floor_shadow"] is not None:
            enforce_freshness(row["legacy_fixed_floor_shadow"],row["frame_age_ms"])
        shadow=row["upper_fixed_floor_shadow"]
        if shadow is not None:
            enforce_freshness(shadow,row["frame_age_ms"])
            row["reason"]=shadow["reason"]
        if row["frame_age_ms"]>500.:
            self.quality.reset()
            row["reason"]="frame_processing_too_old"
        available=shadow is not None and any(m["range_available"] for m in shadow["models"])
        row["status"]="UNVERIFIED_UPPER_COMPARISON" if available else "WITHHELD"
        validate_record(row)
        return row


def summarize(input_dir, output_dir):
    root=Path(input_dir);output=Path(output_dir)
    if output.exists():raise ValueError("new upper report output required")
    source=root/"upper_support_comparison.jsonl"
    count=numeric=legacy_numeric=granted=0
    reasons=Counter();evidence=Counter();inference=Counter()
    sessions=set();last=None;config=None;hashed=hashlib.sha256()
    model_values={}
    with source.open("rb") as stream:
        for line in stream:
            hashed.update(line)
            row=json.loads(line,parse_constant=reject_constant);validate_record(row)
            if last is not None and (row["source_time_sec"]<=last["source_time_sec"]
                    or row["completed_time_sec"]<last["completed_time_sec"]
                    or row["session"]==last["session"] and row["frame"]<=last["frame"]
                    or row["session"]!=last["session"] and row["session"] in sessions):
                raise ValueError("upper log must preserve source order and session retirement")
            if config is not None and config!=row["config_sha256"]:
                raise ValueError("upper config changed within one run")
            config=row["config_sha256"];sessions.add(row["session"])
            count+=1;numeric+=row["status"]=="UNVERIFIED_UPPER_COMPARISON"
            legacy_numeric+=any(m["range_available"] for m in (row["legacy_fixed_floor_shadow"] or {}).get("models",[]))
            granted+=(row["upper_candidate"] or {}).get("upper_completion_granted",False)
            reasons[row["reason"]]+=1;evidence[row["evidence"]["status"]]+=1
            inference[row.get("inference_source","not_recorded")]+=1
            shadow=row["upper_fixed_floor_shadow"]
            for model in (shadow or {}).get("models",[]):
                if not model["range_available"]:continue
                key=shadow["model_bundle_sha256"]+"/"+model["model_name"]
                value=model["horizontal_camera_foot_range_m"]
                record=model_values.setdefault(key,dict(count=0,minimum_m=value,maximum_m=value,total_m=0.))
                record.update(count=record["count"]+1,minimum_m=min(record["minimum_m"],value),
                    maximum_m=max(record["maximum_m"],value),total_m=record["total_m"]+value)
            last={k:row[k] for k in ("session","frame","source_time_sec","completed_time_sec")}
    if not count:raise ValueError("no upper comparison rows")
    for record in model_values.values():record["mean_m"]=record.pop("total_m")/record["count"]
    summary=dict(schema="upper_support_log_summary_v1",status="UNVERIFIED_COMPARISON_LOG_NOT_RUN_OR_METRIC_APPROVAL",
        processed_rows=count,reasons=dict(reasons),upper_numeric_rows=numeric,legacy_numeric_rows=legacy_numeric,
        upper_granted_rows=granted,evidence_states=dict(evidence),model_values=model_values,
        sessions=sorted(sessions),input_sha256=hashed.hexdigest(),inference_sources=dict(inference),
        contains_injected_or_unverified_predictor=any(k!="live_cuda_yolo" for k in inference),
        evidence_files_externally_verified=False,run_finalization_checked=False,
        physical_metric_verified=False,usable_for_ffb=False,display_availability_measured=False)
    output.mkdir(parents=True,exist_ok=False)
    (output/"upper_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Summarize separate upper comparison JSONL; no live hardware")
    parser.add_argument("--input-dir",required=True,type=Path)
    parser.add_argument("--output-dir",required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(summarize(args.input_dir,args.output_dir),indent=2))
