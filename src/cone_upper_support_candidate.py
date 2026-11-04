"""Bounded UPPER-only closure comparator; OFFLINE ONLY, never live authority.

Preserve every existing lateral-comparator acceptance. For a top-only clipped
seeded component, enlarge ONLY the top boundary in two finite steps. Require
identical closed components/support, preserved original lower-envelope columns,
and an observed point inside the original float bbox. No fitted/extrapolated
point, lower/side rescue, metric geometry, temporal shortcut, or FFB output.
"""
import copy
import hashlib
import math

import cv2
import numpy as np

from angular_fisheye_geometry import unproject
from cone_distance_core import support_from_colour_mask
from cone_observation import checked_bbox
from cone_support_completion_candidate import observe_lateral_completion
from theta_rtc_frames import native_frame


def _lower_support(pixels):
    """Actual trimmed lower columns, not an inferred point or contact proof."""
    xs=np.unique(pixels[:,0])
    lo,hi=xs[0],xs[-1]
    return [[int(x),int(pixels[pixels[:,0]==x,1].max())] for x in xs
            if lo+.1*(hi-lo)<=x<=hi-.1*(hi-lo)]


def _upper_context(image, box, camera, colour, seed, top_padding):
    x1,y1,x2,y2=checked_bbox(box,1280,720)
    left,right=math.floor(x1)-4,math.ceil(x2)+4
    top,bottom=math.floor(y1)-top_padding,math.ceil(y2)+4
    info=dict(crop_xyxy=[left,top,right,bottom],top_padding_px=top_padding,
        lateral_padding_px=4,bottom_padding_px=4,reason="",component=None)
    if left<0 or top<0 or right>1280 or bottom>720:
        return dict(info,reason="context_outside_native_image"),None
    _,valid=unproject([[x,y] for x in (left,right-1) for y in (top,bottom-1)],
                      camera,image_size=(1280,720))
    if not valid.all():
        return dict(info,reason="context_outside_front_angular_domain"),None
    a,b,c,d=seed
    if not (left<=a<c<=right and top<=b<d<=bottom):
        return dict(info,reason="original_seed_outside_context"),None
    hsv=cv2.cvtColor(image[top:bottom,left:right],cv2.COLOR_BGR2HSV)
    # Frozen ranges used by the existing colour/lateral comparators. No
    # threshold tuning, seed reselection, or red fallback after a yellow fail.
    if colour=="red":
        mask=cv2.inRange(hsv,(0,80,30),(10,255,255)) | cv2.inRange(hsv,(170,80,30),(179,255,255))
    elif colour=="yellow":
        mask=cv2.inRange(hsv,(15,80,30),(40,255,255))
    else:
        raise ValueError("original seed-selected red or yellow required")
    observation=support_from_colour_mask(mask,left,top)
    labels=cv2.connectedComponents(mask,connectivity=8)[1]
    present=np.unique(labels[b-top:d-top,a-left:c-left])
    present=present[present!=0]
    if len(present)!=1:
        return dict(info,reason="seed_not_one_colour_component",observation=observation),None
    label=int(present[0])
    contours=sorted((c for c in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)[0]
        if cv2.contourArea(c)>=20),key=cv2.contourArea,reverse=True)
    if not contours or labels[contours[0][0,0,1],contours[0][0,0,0]]!=label:
        return dict(info,reason="largest_colour_component_not_seeded",observation=observation),None
    yy,xx=np.nonzero(labels==label)
    pixels=np.column_stack((xx+left,yy+top)).astype("<i4")
    touches=dict(left=bool(np.any(xx==0)),right=bool(np.any(xx==right-left-1)),
        top=bool(np.any(yy==0)),bottom=bool(np.any(yy==bottom-top-1)))
    component=dict(pixel_count=len(pixels),pixel_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
        bounds_xyxy=[int(xx.min()+left),int(yy.min()+top),int(xx.max()+left),int(yy.max()+top)],
        touches=touches,observed_lower_support=_lower_support(pixels))
    if observation["point"] is not None:
        px,py=observation["point"]
        if labels[py-top,px-left]!=label:
            return dict(info,reason="support_not_connected_to_original_seed",component=component,observation=observation),None
    return dict(info,reason=observation["reason"],component=component,observation=observation),pixels


def observe_upper_completion(image, box, camera):
    """Experimental image observation only; existing 3-frame gate still needed.

    Top pads p=clip(ceil(.2*bbox_height),8,16), 2p (max 32px); all other
    boundaries stay at 4px. Never imported by the live receiver/engine.
    """
    native_frame(image)
    x1,y1,x2,y2=checked_bbox(box,1280,720)
    baseline=observe_lateral_completion(image,box,camera)
    result=copy.deepcopy(baseline)
    result.update(method="bounded_upper_completion_shadow_v1",
        original_comparison=copy.deepcopy(baseline),upper_completion_attempted=False,
        upper_completion_granted=False,upper_completion_reason="not_eligible",upper_contexts=[],
        controlling_distance=False,physical_metric_verified=False,floor_contact_verified=False,usable_for_ffb=False)
    if baseline["point"] is not None:
        return dict(result,upper_completion_reason="existing_comparison_point_preserved")
    if baseline["reason"]!="colour_contour_reaches_roi_edge" or baseline["selected_colour"] not in ("red","yellow"):
        return result
    original,old_pixels=_upper_context(image,box,camera,baseline["selected_colour"],baseline["seed_xyxy"],4)
    result["upper_contexts"].append(original)
    if old_pixels is None:
        return dict(result,upper_completion_reason=original["reason"])
    touches=original["component"]["touches"]
    if not touches["top"] or any(touches[k] for k in ("left","right","bottom")):
        return dict(result,upper_completion_reason="not_top_only_contact")
    if original["reason"]!="colour_contour_reaches_roi_edge":
        return dict(result,upper_completion_reason="original_context_rejected:"+original["reason"])
    result["upper_completion_attempted"]=True
    padding=min(16,max(8,math.ceil(.2*(y2-y1))))
    contexts=[]
    for pad in (padding,2*padding):
        context,pixels=_upper_context(image,box,camera,baseline["selected_colour"],baseline["seed_xyxy"],pad)
        result["upper_contexts"].append(context)
        if pixels is None or context["observation"]["point"] is None:
            return dict(result,upper_completion_reason="context_rejected:"+context["reason"])
        if any(context["component"]["touches"].values()):
            return dict(result,upper_completion_reason="context_component_not_closed")
        contexts.append((context,pixels))
    (first,first_pixels),(second,_)=contexts
    if (first["component"]["pixel_sha256"]!=second["component"]["pixel_sha256"]
            or first["observation"]!=second["observation"]):
        return dict(result,upper_completion_reason="component_or_support_changes_across_contexts")
    if not {tuple(p) for p in old_pixels}<={tuple(p) for p in first_pixels}:
        return dict(result,upper_completion_reason="original_seeded_pixels_not_preserved")
    if original["component"]["observed_lower_support"]!=first["observation"]["support"]:
        return dict(result,upper_completion_reason="original_observed_lower_support_changed")
    point=first["observation"]["point"]
    if point not in original["component"]["observed_lower_support"]:
        return dict(result,upper_completion_reason="point_not_in_original_observed_support")
    if not (x1<=point[0]<=x2 and y1<=point[1]<=y2):
        return dict(result,upper_completion_reason="upper_point_outside_original_bbox")
    result.update(first["observation"])
    result.update(reason="unverified_upper_completed_colour_support",upper_completion_granted=True,
        upper_completion_reason="same_closed_component_and_original_lower_support_in_two_contexts")
    return result
