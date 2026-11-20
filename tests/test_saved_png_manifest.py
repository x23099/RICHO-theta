"""Manifest builder tests with synthetic PNGs; no camera or network."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'Experimental_results/2026-11-21/cones_vp8_suite_r01/prepare_manifest.py'


def write_png(directory, number, shape=(720, 1280, 3)):
    image = np.zeros(shape, np.uint8)
    image[100:200, 100:200] = (0, 0, 255) if number % 2 else (0, 255, 255)
    path = directory / f'decoded_testsession_f{number:06d}.png'
    cv2.imwrite(str(path), image)
    return path


class ManifestTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.frames = self.directory / 'frames'
        self.frames.mkdir()

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, timeout=60)

    def test_two_valid_frames_produce_a_pinned_manifest(self):
        write_png(self.frames, 1)
        write_png(self.frames, 2)
        output = self.directory / 'manifest.json'
        result = self.run_script('--input-dir', self.frames, '--roi', 270, 0, 350, 720,
                                 '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(output.read_bytes())
        self.assertEqual(value['schema'], 'saved_png_manifest_v1')
        self.assertEqual(value['roi_native_xyxy'], [270, 0, 350, 720])
        self.assertEqual(len(value['images']), 2)
        self.assertEqual(value['images'][0]['name'], 'decoded_testsession_f000001.png')
        self.assertEqual(len({item['sha256'] for item in value['images']}), 2)
        self.assertFalse(value['usable_for_ffb'])

    def test_wrong_size_and_duplicate_content_are_rejected(self):
        write_png(self.frames, 1)
        write_png(self.frames, 2, shape=(480, 640, 3))
        result = self.run_script('--input-dir', self.frames, '--roi', 270, 0, 350, 720,
                                 '--output', self.directory / 'bad.json')
        self.assertNotEqual(result.returncode, 0)
        (self.frames / 'decoded_testsession_f000002.png').unlink()
        first = write_png(self.frames, 2)
        cv2.imwrite(str(first), cv2.imread(str(self.frames / 'decoded_testsession_f000001.png')))
        result = self.run_script('--input-dir', self.frames, '--roi', 270, 0, 350, 720,
                                 '--output', self.directory / 'dup.json')
        self.assertNotEqual(result.returncode, 0)

    def test_existing_output_and_bad_roi_are_rejected(self):
        write_png(self.frames, 1)
        write_png(self.frames, 2)
        output = self.directory / 'exists.json'
        output.write_text('{}')
        self.assertNotEqual(self.run_script('--input-dir', self.frames, '--roi', 270, 0, 350, 720,
                                            '--output', output).returncode, 0)
        self.assertNotEqual(self.run_script('--input-dir', self.frames, '--roi', 700, 0, 800, 720,
                                            '--output', self.directory / 'roi.json').returncode, 0)


if __name__ == '__main__':
    unittest.main()
