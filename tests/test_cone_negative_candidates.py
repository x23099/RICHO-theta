"""Synthetic export-only background queue tests; no GPU or human approval."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cone_dataset import dataset_yaml, label_path, mark_review, read_csv, sha256, validate, write_csv
from prepare_cone_negative_candidates import load_plan, merge_negatives, prepare, sample_frames


class NegativeCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reference, self.session = self.root / 'reference', self.root / 'session'
        rows, reviews = [], []
        for index, split in enumerate(('train', 'val')):
            image = f'images/{split}/old.png'
            path = self.reference / image
            path.parent.mkdir(parents=True)
            pixels = np.full((96, 160, 3), 10 + index, np.uint8)
            cv2.imwrite(str(path), pixels)
            row = dict(image=image, split=split, group_id=split, session=split, frame=1,
                time_sec=0, width=160, height=96, png_sha256=sha256(path),
                decoded_bgr_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
                source_raw_sha256=str(index) * 64)
            rows.append(row)
            label = label_path(self.reference, image)
            label.parent.mkdir(parents=True)
            label.write_text('0 0.5 0.5 0.2 0.2\n')
            reviews.append(dict(image=image, status='positive', note='synthetic test only', label_sha256=sha256(label)))
        write_csv(self.reference / 'manifest.csv', rows)
        write_csv(self.reference / 'reviews.csv', reviews)
        (self.reference / 'dataset.json').write_text(json.dumps(dict(schema_version=1,
            classes=['traffic_cone'], development_only=True, available_splits=['train', 'val'],
            manifest_sha256=sha256(self.reference / 'manifest.csv'))))
        (self.reference / 'data.yaml').write_text(dataset_yaml(self.reference, development_only=True))
        self.session.mkdir()
        (self.session / 'metadata.json').write_text(json.dumps(dict(requested_camera_width=160, requested_camera_height=96)))
        write_csv(self.session / 'detections.csv', [dict(frame=i, time_sec=i/30) for i in range(1, 5)])
        writer = cv2.VideoWriter(str(self.session / 'raw.avi'), cv2.VideoWriter_fourcc(*'MJPG'), 30, (160, 96))
        self.assertTrue(writer.isOpened())
        for i in range(4):
            writer.write(np.full((96, 160, 3), 60 + i*20, np.uint8))
        writer.release()
        self.plan = self.root / 'plan.csv'
        self.entry = dict(session_dir=str(self.session), group_id='legacy', samples=3, notes='synthetic capture')
        write_csv(self.plan, [self.entry])
        self.output = self.root / 'queue'

    def export(self):
        return prepare(self.plan, self.reference, self.output)

    def test_export_preserves_pixels_and_never_creates_negatives(self):
        before = sha256(self.session / 'raw.avi')
        self.assertEqual(self.export()['images'], 3)
        self.assertFalse((self.output / 'data.yaml').exists())
        self.assertFalse(list((self.output / 'labels').rglob('*.txt')))
        self.assertTrue(all(r['status'] == 'pending' for r in read_csv(self.output / 'reviews.csv')))
        self.assertEqual(before, sha256(self.session / 'raw.avi'))
        for row in read_csv(self.output / 'manifest.csv'):
            pixels = cv2.imread(str(self.output / row['image']))
            self.assertEqual(pixels.shape, (96, 160, 3))
            self.assertEqual(hashlib.sha256(pixels.tobytes()).hexdigest(), row['decoded_bgr_sha256'])
        with self.assertRaises(ValueError):
            validate(self.output)

    def test_review_tool_can_explicitly_confirm_a_negative(self):
        self.export()
        image = read_csv(self.output / 'manifest.csv')[0]['image']
        mark_review(self.output, image, 'negative', 'human full-frame review: SYNTHETIC TEST ONLY')
        self.assertEqual(label_path(self.output, image).read_text(), '')
        self.assertEqual(read_csv(self.output / 'reviews.csv')[0]['status'], 'negative')

    def test_existing_output_is_not_overwritten(self):
        self.export()
        before = sha256(self.output / 'manifest.csv')
        with self.assertRaisesRegex(ValueError, 'NEW output'):
            self.export()
        self.assertEqual(before, sha256(self.output / 'manifest.csv'))

    def approve_one(self):
        image = read_csv(self.output / 'manifest.csv')[0]['image']
        mark_review(self.output, image, 'negative', 'human full-frame review: SYNTHETIC TEST ONLY')
        return image

    def test_merge_pending_is_not_implicit_negative(self):
        self.export()
        target = self.root / 'merged'
        with self.assertRaisesRegex(ValueError, 'no human-confirmed'):
            merge_negatives(self.output, self.reference, target)
        self.assertFalse(target.exists())

    def test_merge_only_explicit_negatives_preserves_all_reference_content(self):
        self.export(); self.approve_one()
        before = sha256(self.reference / 'manifest.csv')
        target = self.root / 'merged'
        result = merge_negatives(self.output, self.reference, target)
        self.assertEqual(result['negative_images_added'], 1)
        self.assertEqual(result['candidates_held'], 2)
        self.assertEqual(result['counts']['train']['negative'], 1)
        self.assertEqual(before, sha256(self.reference / 'manifest.csv'))
        for row in read_csv(self.reference / 'manifest.csv'):
            self.assertEqual((target / row['image']).read_bytes(), (self.reference / row['image']).read_bytes())
            self.assertEqual(label_path(target, row['image']).read_bytes(), label_path(self.reference, row['image']).read_bytes())

    def test_changed_source_or_label_refuses_merge(self):
        self.export(); image = self.approve_one()
        label_path(self.output, image).write_text('0 0.5 0.5 0.2 0.2\n')
        with self.assertRaisesRegex(ValueError, 'empty label'):
            merge_negatives(self.output, self.reference, self.root / 'merged')
        label_path(self.output, image).write_text('')
        (self.session / 'metadata.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'raw source changed'):
            merge_negatives(self.output, self.reference, self.root / 'merged')

    def test_assistant_observation_cannot_be_merged_as_human_negative(self):
        self.export()
        image = read_csv(self.output / 'manifest.csv')[0]['image']
        mark_review(self.output, image, 'negative', 'assistant sees no cone; not human review')
        with self.assertRaisesRegex(ValueError, 'human full-frame'):
            merge_negatives(self.output, self.reference, self.root / 'merged')

    def test_source_video_in_reference_refused(self):
        rows = read_csv(self.reference / 'manifest.csv')
        rows[1]['source_raw_sha256'] = sha256(self.session / 'raw.avi')
        write_csv(self.reference / 'manifest.csv', rows)
        meta = json.loads((self.reference / 'dataset.json').read_text())
        meta['manifest_sha256'] = sha256(self.reference / 'manifest.csv')
        (self.reference / 'dataset.json').write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_existing_group_cannot_be_renamed_train(self):
        write_csv(self.plan, [dict(self.entry, group_id='val')])
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.export()

    def test_duplicate_video_under_different_session_refused(self):
        other = self.root / 'other'
        shutil.copytree(self.session, other)
        write_csv(self.plan, [self.entry, dict(self.entry, session_dir=str(other))])
        with self.assertRaisesRegex(ValueError, 'duplicate video'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_short_long_and_nonmonotonic_recordings_refused(self):
        for count in (3, 5):
            write_csv(self.session / 'detections.csv', [dict(frame=i, time_sec=i/30) for i in range(1, count+1)])
            with self.assertRaisesRegex(ValueError, 'video .* than CSV'):
                self.export()
            self.assertFalse(self.output.exists())
        write_csv(self.session / 'detections.csv', [dict(frame=i, time_sec=0) for i in range(1, 5)])
        with self.assertRaisesRegex(ValueError, 'increasing'):
            self.export()

    def test_plan_and_sampling_validation(self):
        self.assertEqual(sample_frames(4, 3), [1, 3, 4])
        self.assertEqual(sample_frames(4, 1), [2])
        for count, samples in ((0, 1), (3, 4), (3, 0)):
            with self.assertRaises(ValueError):
                sample_frames(count, samples)
        write_csv(self.plan, [self.entry, self.entry])
        with self.assertRaisesRegex(ValueError, 'unique sessions'):
            load_plan(self.plan)


if __name__ == '__main__':
    unittest.main()
