"""Panel wording only; no live camera, ROS, GPU, geometry or control startup."""
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_motion_bridge import panel_text as original_panel_text
from driver_motion_presentation import panel_text, reason_text, scope_text


def selected_node(source, *names):
    node = ast.parse(source)
    for name in names:
        node = next(item for item in node.body if getattr(item, 'name', None) == name)
    return node


class MotionPresentationTests(unittest.TestCase):
    def numeric(self):
        return dict(available=True, reason='EXPERIMENTAL_FIXED_MOUNT_NOT_VERIFIED_CONTACT', age_ms=16.,
            result=dict(session='e52bb32f'+'0'*24, frame=34957, horizontal_camera_foot_range_m=1.0051490635900895),
            display_review=dict(reference_generation=1))

    def test_numeric_keeps_original_value_source_age_generation_and_warning(self):
        snapshot = self.numeric()
        text = panel_text(snapshot, target_roi=[270, 0, 350, 720])
        self.assertTrue(text.startswith(original_panel_text(snapshot)+'\n'))
        for expected in ('1.005 m', 'frame 34957', 'receive-age 16 ms', 'body-review gen 1',
                         'NOT used for control/FFB', 'x=270..350', 'y=0..720', '元魚眼1280x720',
                         '画面全体の測距ではありません', '接地・精度の認定ではありません'):
            self.assertIn(expected, text)

    def test_formatter_does_not_mutate_nested_snapshot_or_roi(self):
        snapshot = self.numeric()
        before, roi = copy.deepcopy(snapshot), [270, 0, 350, 720]
        panel_text(snapshot, target_roi=roi)
        self.assertEqual(snapshot, before)
        self.assertEqual(roi, [270, 0, 350, 720])

    def test_withheld_never_uses_retained_numeric_result(self):
        snapshot = dict(self.numeric(), available=False, reason='motion_result_stale')
        text = panel_text(snapshot, target_roi=[270, 0, 350, 720])
        self.assertIn('WITHHELD', text)
        self.assertIn('motion_result_stale', text)
        self.assertIn('古い距離は表示しません', text)
        self.assertNotIn('1.005', text)

    def test_no_candidate_is_not_claimed_to_be_definitely_outside_roi(self):
        text = reason_text('no_candidate')
        self.assertIn('候補を取得できていません', text)
        self.assertNotIn('範囲外', text)
        self.assertNotIn('故障', text)

    def test_body_occlusion_is_a_possibility_and_not_verified_contact(self):
        text = panel_text(dict(available=False, reason='possible_self_body_occlusion'))
        self.assertIn('重なる可能性', text)
        self.assertIn('possible_self_body_occlusion', text)

    def test_reference_and_colour_crop_reasons_are_distinct(self):
        self.assertIn('未読込み', reason_text('display_body_reference_unavailable'))
        self.assertIn('現在の入力に対して有効ではありません', reason_text('display_body_reference_not_current'))
        self.assertIn('解析枠の端', reason_text('colour_contour_reaches_roi_edge'))
        self.assertNotEqual(reason_text('display_body_reference_unavailable'), reason_text('no_candidate'))

    def test_unknown_reason_code_is_retained_without_invented_diagnosis(self):
        text = panel_text(dict(available=False, reason='new_future_reason'))
        self.assertIn('new_future_reason', text)
        self.assertIn('詳細は上記のコード', text)

    def test_worker_error_prefix_has_explanation_and_keeps_details(self):
        text = panel_text(dict(available=False, reason='motion_worker_failed: synthetic'))
        self.assertIn('synthetic', text)
        self.assertIn('測距処理でエラー', text)

    def test_roi_comes_from_configuration_and_none_is_not_central_roi(self):
        self.assertIn('x=100..200', scope_text((100, 20, 200, 600)))
        self.assertNotIn('270', scope_text((100, 20, 200, 600)))
        self.assertIn('ROI指定なし', scope_text(None))
        self.assertNotIn('中央', scope_text(None))

    def test_invalid_roi_rejected_without_changing_snapshot(self):
        for roi in ([True, 0, 350, 720], [270, 0, 350], [350, 0, 270, 720], [0, 0, 641, 720]):
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                scope_text(roi)

    def test_ui_tick_passes_actual_roi_and_updates_before_video_frame(self):
        node = selected_node((ROOT/'src/webrtc_receive_ui.py').read_text(), 'ThetaDriverUI', 'update_frame')
        scope = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'synthetic_ui_tick', 'exec'), scope)
        label = SimpleNamespace(setText=Mock())
        ui = SimpleNamespace(motion=SimpleNamespace(snapshot=lambda:dict(available=False, reason='no_candidate')),
            args=SimpleNamespace(motion_target_roi=[100, 0, 200, 720]), motion_label=label,
            server_thread=None)
        scope['update_frame'](ui)
        text = label.setText.call_args[0][0]
        self.assertIn('x=100..200', text)
        self.assertIn('候補を取得できていません', text)

    def test_ui_label_uses_plain_text_and_presentation_is_only_in_ui(self):
        source = (ROOT/'src/webrtc_receive_ui.py').read_text()
        node = selected_node(source, 'ThetaDriverUI', 'init_ui')
        self.assertIn('self.motion_label.setTextFormat(Qt.PlainText)', ast.unparse(node))
        for path in ('driver_motion_process.py', 'driver_body_display_guard.py', 'cone_motion_range.py',
                     'driver_motion_bridge.py', 'webrtc_stream.py'):
            self.assertNotIn('driver_motion_presentation', (ROOT/'src'/path).read_text())


if __name__ == '__main__':
    unittest.main()
