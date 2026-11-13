"""Four-file pin intake: synthetic PNG and metadata, no live/GPU/control."""
import importlib.util
import json
from pathlib import Path
import unittest

import test_guarded_current_pin_intake as prior

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('body_pin_intake',ROOT/'Experimental_results/2026-11-13/body_display_reference_static_r01/intake.py')
intake=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(intake)


class BodyPinIntakeTests(unittest.TestCase):
    def fixture(self):
        data=prior.CurrentPinTests().fixture();config=ROOT/'src/cone_distance_diagnostic_config.json'
        settings=json.loads(config.read_bytes())
        profile=ROOT/'Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'
        engine=dict(schema='driver_motion_engine_v1',config_sha256=intake.pin.sha(config.read_bytes()),
            weights_sha256=settings['weights_sha256'],profile_sha256=intake.pin.sha(profile.read_bytes()),
            physical_metric_verified=False,usable_for_ffb=False,published_to_ros=False,mount_or_floor_tilt_compensated=False,
            guarded_comparison=dict(requested=True,worker_started=True,main_display_modified=False,controlling_distance=False),
            body_display_guard=dict(enabled=True,raw_main_result_modified=False,display_rejection_only=True,
                reference_source='same_stream_explicit_pin_load',controlling_distance=False,usable_for_ffb=False,
                code_sha256={name:intake.pin.sha((ROOT/'src'/name).read_bytes()) for name in intake.GUARD_SOURCES}))
        data['motion_engine_summary.json']=json.dumps(engine).encode();return data

    def test_matching_four_files_verify_recorded_mode_not_gui(self):
        result=intake.check(self.fixture())
        self.assertTrue(result['display_guard_enabled']);self.assertEqual(result['display_guard_code_files_rehashed'],7)
        self.assertTrue(result['display_guard_gui_output_NOT_verified']);self.assertEqual(len(result['pin_files_sha256']),3)

    def test_missing_summary_rejected(self):
        data=self.fixture();del data['motion_engine_summary.json']
        with self.assertRaisesRegex(ValueError,'engine summary required'):intake.check(data)

    def test_disabled_gate_or_authority_changed_rejected(self):
        for change in ('disabled','authority'):
            data=self.fixture();e=json.loads(data['motion_engine_summary.json'])
            if change=='disabled':e['body_display_guard']['enabled']=False
            else:e['published_to_ros']=True
            data['motion_engine_summary.json']=json.dumps(e).encode()
            with self.subTest(change=change),self.assertRaises(ValueError):intake.check(data)

    def test_changed_helper_sha_rejected(self):
        data=self.fixture();e=json.loads(data['motion_engine_summary.json'])
        e['body_display_guard']['code_sha256']['driver_body_display_guard.py']='0'*64
        data['motion_engine_summary.json']=json.dumps(e).encode()
        with self.assertRaisesRegex(ValueError,'display code SHA mismatch'):intake.check(data)

    def test_extra_payload_and_mixed_pin_still_rejected(self):
        data=self.fixture();data['extra.json']=b'{}'
        with self.assertRaisesRegex(ValueError,'exactly three'):intake.check(data)
        data=self.fixture();s=json.loads(data['comparison_status.json']);s['pin']['frame']+=1
        data['comparison_status.json']=json.dumps(s).encode()
        with self.assertRaises(ValueError):intake.check(data)

    def test_profile_mismatch_rejected(self):
        data=self.fixture();e=json.loads(data['motion_engine_summary.json']);e['profile_sha256']='0'*64
        data['motion_engine_summary.json']=json.dumps(e).encode()
        with self.assertRaisesRegex(ValueError,'profile SHA mismatch'):intake.check(data)


if __name__=='__main__':unittest.main()
