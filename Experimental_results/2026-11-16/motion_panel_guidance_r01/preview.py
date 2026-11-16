"""Offscreen synthetic label previews ONLY; no driver/ROS/camera startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from driver_motion_presentation import panel_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError('new preview directory required')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    app = QApplication([])
    numeric = dict(available=True, age_ms=25., reason='synthetic',
        result=dict(horizontal_camera_foot_range_m=1.234, session='a'*32, frame=123),
        display_review=dict(reference_generation=1))
    fixtures = {'numeric': numeric, 'no_candidate': dict(available=False, reason='no_candidate'),
                'self_body_occlusion': dict(numeric, available=False, reason='possible_self_body_occlusion')}
    output.mkdir(parents=True)
    records = {}
    for name, snapshot in fixtures.items():
        container = QWidget()
        container.setStyleSheet('background-color: #050505;')
        layout = QVBoxLayout(container)
        title = QLabel('OFFLINE SYNTHETIC LABEL PREVIEW - NOT A LIVE DRIVER SCREEN')
        title.setStyleSheet('color: #bbbbbb; font-size: 13px;')
        layout.addWidget(title)
        label = QLabel(panel_text(snapshot, target_roi=[270, 0, 350, 720]))
        label.setTextFormat(Qt.PlainText)
        label.setStyleSheet('color: #ffdd55; font-size: 13px; padding: 8px;')
        label.setWordWrap(True)
        layout.addWidget(label)
        container.resize(1650, 220)
        container.show()
        app.processEvents()
        assert label.textFormat() == Qt.PlainText
        assert label.height() >= label.heightForWidth(label.width())
        path = output/(name+'.png')
        assert not path.exists() and container.grab().save(str(path), 'PNG')
        records[name] = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            width=container.width(), height=container.height(), text=label.text(),
            label_width=label.width(), label_height=label.height(),
            required_height=label.heightForWidth(label.width()), plain_text=True,
            source='synthetic_fixture_NOT_camera_or_live_UI')
        container.close()
    manifest = dict(schema='synthetic_motion_label_preview_v1', state='pass', previews=records,
        code_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (Path(__file__), ROOT/'src/driver_motion_presentation.py', ROOT/'src/webrtc_receive_ui.py')},
        local_camera_ros_network_or_vehicle_started=False, full_driver_ui_started=False)
    with (output/'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps(dict(state='pass', previews=len(records), synthetic_only=True)))


if __name__ == '__main__':
    main()
