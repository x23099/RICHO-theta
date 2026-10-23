"""Verify exact frame/value binding and distinguish originals from analysis art."""
import base64
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import cv2
import numpy as np

from render_examples import HERE,HEADER,NS,svg_for
from prepare_frames import row_sha
from cone_dataset import read_csv,sha256


class VisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=HERE/'originals_r01';cls.visual=HERE/'visualizations_r01'
        cls.frames=read_csv(cls.original/'frame_manifest.csv');cls.views=read_csv(cls.visual/'visualization_manifest.csv')
        cls.metrics=read_csv(Path(cls.frames[0]['source_metric_csv']))
        cls.observed=read_csv(Path(cls.frames[0]['source_observed_csv']))

    def test_input_and_output_hashes_are_unchanged(self):
        for folder in (self.original,self.visual):
            d=json.loads((folder/'summary.json').read_text())
            for p,h in d['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
            for name,h in d['output_sha256'].items():self.assertEqual(sha256(folder/name),h,name)

    def test_three_originals_have_native_shape_and_decoded_hash(self):
        self.assertEqual(len(self.frames),3)
        for r in self.frames:
            image=cv2.imread(str(self.original/r['original_png']))
            self.assertEqual(image.shape,(720,1280,3))
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(),r['decoded_bgr_sha256'])
            self.assertEqual(r['original_image_edited'],'False')

    def test_original_pngs_match_independent_video_frame_read(self):
        cap=cv2.VideoCapture(self.frames[0]['source_raw_path'])
        for r in self.frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(r['frame'])-1);ok,image=cap.read();self.assertTrue(ok)
            np.testing.assert_array_equal(image,cv2.imread(str(self.original/r['original_png'])))
        cap.release()

    def test_exact_saved_metric_row_and_observed_row_not_nearest_frame(self):
        for r in self.frames:
            metric=next(v for v in self.metrics if v['scenario']==r['scenario'] and v['session']==r['session'] and v['frame']==r['frame'])
            observed=next(v for v in self.observed if v['session']==r['session'] and v['frame']==r['frame'])
            self.assertEqual(row_sha(metric),r['source_metric_row_sha256']);self.assertEqual(row_sha(observed),r['source_observed_row_sha256'])
            self.assertEqual(metric['diagnostic_z_m'],r['diagnostic_z_m']);self.assertEqual(metric['reference_z_m'],r['reference_z_m'])
            self.assertEqual(float(metric['time_sec']),float(observed['time_sec']))

    def test_available_examples_selected_by_time_not_distance_error(self):
        for r in self.frames:
            if r['diagnostic_available']=='False':continue
            valid=sorted([v for v in self.metrics if v['scenario']==r['scenario'] and v['condition']==r['condition'] and v['diagnostic_available']=='True'],key=lambda v:int(v['frame']))
            self.assertEqual(valid[len(valid)//2]['frame'],r['frame'])

    def test_svg_embeds_original_bytes_without_modification_or_rescale(self):
        for r in self.views:
            root=ET.parse(self.visual/r['svg']).getroot();image=root.find(f'{{{NS}}}g/{{{NS}}}image')
            href=image.attrib['{http://www.w3.org/1999/xlink}href']
            embedded=base64.b64decode(href.split(',',1)[1])
            self.assertEqual(embedded,Path(r['original_png']).read_bytes())
            self.assertEqual(image.attrib['width'],'1280');self.assertEqual(image.attrib['height'],'720')
            self.assertEqual(image.attrib['x'],'0');self.assertEqual(image.attrib['y'],str(HEADER))

    def test_numeric_labels_come_from_diagnostic_not_reference_distance(self):
        for r in self.views:
            root=ET.parse(self.visual/r['svg']).getroot();text=' '.join(root.itertext())
            if r['diagnostic_available']=='True':
                self.assertIn(f"推定 Z = {float(r['diagnostic_z_m']):.3f} m",text)
            self.assertIn(f"設置 Z（申告）= {float(r['reference_z_m']):.2f} m",text)

    def test_marker_uses_same_frame_native_bottom_not_ground_truth(self):
        original={r['label']:r for r in self.frames}
        for r in self.views:
            if r['diagnostic_available']=='False':continue
            root=ET.parse(self.visual/r['svg']).getroot()
            marker=next(e for e in root.iter() if e.attrib.get('id')=='observed-bottom-marker')
            point=json.loads(original[r['label']]['native_colour_pair_json'])[1]
            self.assertEqual(float(marker.attrib['cx']),point[0]);self.assertEqual(float(marker.attrib['cy']),point[1]+HEADER)

    def test_withheld_has_no_fabricated_number_or_measurement_marker(self):
        r=next(r for r in self.views if r['label']=='occlusion_hold')
        root=ET.parse(self.visual/r['svg']).getroot();text=' '.join(root.itertext())
        self.assertIn('推定 Z = 保留（数値なし）',text)
        self.assertFalse(any(e.attrib.get('id')=='observed-bottom-marker' for e in root.iter()))
        self.assertEqual(r['diagnostic_z_m'],'')

    def test_renderer_refuses_inconsistent_availability(self):
        r=dict(self.frames[0],diagnostic_available='False',diagnostic_z_m='2.0')
        with self.assertRaises(ValueError):svg_for(r,b'')
        r.update(diagnostic_available='True',diagnostic_z_m='')
        with self.assertRaises(ValueError):svg_for(r,b'')

    def test_warnings_and_units_are_embedded_in_every_figure(self):
        for r in self.views:
            text=' '.join(ET.parse(self.visual/r['svg']).getroot().itertext())
            for required in ('録画後の再計算','条件付き診断値','物理距離・接地点の検証は未完了','実機FFBへの使用なし','斜め距離ではありません'):
                self.assertIn(required,text)

    def test_png_dimensions_and_nonannotated_photo_region_unchanged(self):
        for r in self.views:
            png=cv2.imread(str(self.visual/r['png']));raw=cv2.imread(r['original_png'])
            self.assertEqual(png.shape,(980,1280,3))
            np.testing.assert_array_equal(png[HEADER:HEADER+720,900:1280],raw[:,900:1280])

    def test_no_live_or_physical_approval_in_metadata(self):
        for r in self.views:
            metadata=json.loads(ET.parse(self.visual/r['svg']).getroot().find(f'{{{NS}}}metadata').text)
            self.assertTrue(metadata['post_recording_visualization'])
            self.assertFalse(metadata['physical_metric_verified']);self.assertFalse(metadata['usable_for_ffb'])


if __name__=='__main__':unittest.main()
