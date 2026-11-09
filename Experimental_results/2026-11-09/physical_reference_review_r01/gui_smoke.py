"""Xvfb-only scripted GUI checks on SYNTHETIC fixtures, not human review."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import cv2
import numpy as np
import matplotlib
matplotlib.use('TkAgg',force=True)
from matplotlib import pyplot as plt
from matplotlib.backend_bases import KeyEvent,MouseEvent

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
import review_physical_reference as review


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    checks={}
    with tempfile.TemporaryDirectory(prefix='theta_physical_review_gui_') as name:
        root=Path(name)
        image=root/'decoded_synthetic_f000001.png'
        pixels=np.zeros((720,1280,3),np.uint8)
        pixels[390:411,290:346]=255
        ok,encoded=cv2.imencode('.png',pixels);assert ok
        image.write_bytes(encoded.tobytes());before=review.digest(image)
        base=dict(image=image.name,sha256=before,session='synthetic',frame=1)
        items=[dict(base,id='synthetic_paper',kind='paper',paper_sides_mm=[296,210]),
               dict(base,id='synthetic_cone',kind='cone_near_edge')]
        queue=dict(schema=review.QUEUE_SCHEMA,items=items,**{k:False for k in review.FLAGS})
        path=root/'queue.json';review.dump_new(path,queue)
        errors=[];calls=[];original_show=plt.show
        def show(block=True):
            fig=plt.gcf();fig.canvas.draw();ax=fig.axes[0]
            call=len(calls);calls.append(call)
            def events():
                try:
                    checks['no_image_save_toolbar']=fig.canvas.manager.toolbar is None
                    def key(k):KeyEvent('key_press_event',fig.canvas,key=k)._process()
                    def click(point):
                        x,y=ax.transData.transform(point)
                        MouseEvent('button_press_event',fig.canvas,x,y,button=1)._process()
                    if call==0:
                        key('y');checks['incomplete_confirmation_not_saved']=not (root/'decisions/synthetic_paper.json').exists()
                        x,y=ax.transData.transform([317,400])
                        for _ in range(3):MouseEvent('scroll_event',fig.canvas,x,y,button='up',step=1)._process()
                        checks['zoom_changes_view_only']=ax.get_xlim()[1]-ax.get_xlim()[0]<1280
                        selected=[[290,390],[345,390],[345,410],[290,410]]
                        for point in selected:click(point)
                        key('w');key('y')
                        record=review.read_json(root/'decisions/synthetic_paper.json')
                        checks['zoom_click_native_coordinates']=bool(np.max(np.abs(np.array(record['points_native_xy'])-selected))<.01)
                        checks['paper_dimension_recorded']=record['side_assignment']=='long_01'
                    else:
                        click([300,415]);key('u')
                        record=review.read_json(root/'decisions/synthetic_cone.json')
                        checks['unclear_clears_guess']=record['status']=='unclear' and record['points_native_xy']==[]
                except Exception as exc:
                    errors.append(type(exc).__name__+': '+str(exc));plt.close('all')
            fig.canvas.get_tk_widget().after(60,events)
            original_show(block=block)
        with patch.object(review,'ROOT',root),patch.object(plt,'show',show):
            result=review.review(path,root/'decisions','SYNTHETIC_GUI_AUTOMATION_NOT_HUMAN','TkAgg')
        checks.update(two_windows_exercised=len(calls)==2,pending_zero_for_synthetic_only=result['pending']==0,
            synthetic_pixels_unchanged=review.digest(image)==before,no_image_exports=len(list(root.glob('*.png')))==1,
            no_unhandled_callback_errors=not errors)
        checks={key:bool(value) for key,value in checks.items()}
        output=dict(status='PASS_SYNTHETIC_GUI_ONLY' if all(checks.values()) else 'FAIL',checks=checks,errors=errors,
            real_human_reviews_performed=0,real_source_images_modified=False,physical_metric_verified=False,
            usable_for_ffb=False)
    review.dump_new(args.output,output);print(json.dumps(output,indent=2))
    return 0 if all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
