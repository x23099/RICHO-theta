"""Visible-color contour bottom, not a physical contact detector; OFFLINE."""
import math
import cv2
import numpy as np


def colour_bottom(image,box,v_min=30):
    from cone_observation import checked_bbox
    if image.shape!=(720,1280,3) or image.dtype!=np.uint8:
        raise ValueError("native1280x720 uint8 BGR required")
    if v_min not in (20,30,50):raise ValueError("only the three frozen V thresholds allowed")
    x1,y1,x2,y2=checked_bbox(box,1280,720)
    left,top,right,bottom=math.floor(x1)-4,math.floor(y1)-4,math.ceil(x2)+4,math.ceil(y2)+4
    result=dict(colour_candidate=False,reason="",pixel_x=None,pixel_y=None,contour_area_px=None,
        contour_width_px=None,contour_height_px=None,contour_max_y=None,bbox_y2=y2,
        contour_max_y_minus_bbox_y2_px=None,significant_contours=0,
        floor_contact_verified=False,usable_for_ffb=False)
    if left<0 or top<0 or right>1280 or bottom>720:
        return dict(result,reason="expanded_roi_outside_native_image")
    hsv=cv2.cvtColor(image[top:bottom,left:right],cv2.COLOR_BGR2HSV)
    mask=cv2.bitwise_or(cv2.inRange(hsv,(0,80,v_min),(10,255,255)),
                       cv2.inRange(hsv,(170,80,v_min),(179,255,255)))
    mask=cv2.bitwise_or(mask,cv2.inRange(hsv,(15,80,v_min),(40,255,255)))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    contours=sorted((c for c in contours if cv2.contourArea(c)>=20),key=cv2.contourArea,reverse=True)
    result["significant_contours"]=len(contours)
    if not contours:return dict(result,reason="no_supported_colour_contour")
    contour=contours[0]
    result["contour_area_px"]=float(cv2.contourArea(contour))
    if len(contours)>1 and cv2.contourArea(contours[1])>=.25*cv2.contourArea(contour):
        return dict(result,reason="ambiguous_competing_colour_contours")
    bx,by,bw,bh=cv2.boundingRect(contour)
    result.update(contour_width_px=bw,contour_height_px=bh)
    if bx==0 or by==0 or bx+bw>=right-left or by+bh>=bottom-top:
        return dict(result,reason="colour_contour_reaches_roi_edge")
    if bw<5 or bh<8:return dict(result,reason="insufficient_colour_extent")
    points=contour[:,0,:]
    count=max(3,int(math.ceil(.08*len(points))))
    # Deterministic order; never use reference distance or geometry to choose pixels.
    ordered=points[np.lexsort((points[:,0],-points[:,1]))][:count]
    pixel=np.median(ordered,axis=0)+[left,top]
    maximum=int(points[:,1].max()+top)
    return dict(result,colour_candidate=True,reason="unverified_visible_colour_bottom",
        pixel_x=float(pixel[0]),pixel_y=float(pixel[1]),contour_max_y=maximum,
        contour_max_y_minus_bbox_y2_px=maximum-y2)
