"""Source-metadata tests with fake ROS messages and fake Node. No ROS startup."""
import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_odometry_observation import (OdometryObserver, SCHEMA, checked_observation,
    decode_observation, stamp_ns)
from driver_telemetry_recording import TelemetryRecorder
from test_driver_motion_integration import selected_node


def message(sec=1000, nano=1, v=0., w=0., child='base_link', pose='odom'):
    return NS(header=NS(stamp=NS(sec=sec, nanosec=nano), frame_id=pose), child_frame_id=child,
              twist=NS(twist=NS(linear=NS(x=v, y=0.), angular=NS(z=w))))


def sender_node():
    class FakeNode:
        def __init__(self, name):
            self.name=name; self.subscriptions=[]; self.publishers=[]
        def create_subscription(self, *args):
            self.subscriptions.append(args)
        def create_publisher(self, *args):
            pub=Mock(); self.publishers.append((args, pub)); return pub
    scope=dict(Node=FakeNode, math=__import__('math'),
        logger=NS(warning=Mock()), Odometry=object, Imu=object, String=object, Int32=object, Twist=object)
    node=selected_node((ROOT/'src/webrtc_stream.py').read_text(),'TelemetryNode')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'fake_sender_node','exec'),scope)
    with patch.dict(sys.modules, {'std_msgs.msg':NS(Float32=object),
                                  'kobuki_ros_interfaces.msg':NS(SensorState=object)}):
        result=scope['TelemetryNode']('/odom','/mode','/page','/core','/imu','/pedal')
    return result


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.now=10.
        self.observer=OdometryObserver(clock=lambda:self.now)

    def checked(self):
        value=self.observer.snapshot()
        self.assertEqual(checked_observation(value), value)
        self.assertEqual(json.loads(json.dumps(value,allow_nan=False)), value)
        return value

    def test_not_received_is_distinct_from_received_zero(self):
        initial=self.checked()
        self.assertIs(initial['callback_received'],False)
        self.assertIsNone(initial['linear_mps'])
        self.assertFalse(initial['sample_fields_valid'])
        self.observer.observe(message())
        received=self.checked()
        self.assertIs(received['callback_received'],True)
        self.assertEqual(received['linear_mps'],0.)
        self.assertEqual(received['angular_radps'],0.)
        self.assertTrue(received['sample_fields_valid'])
        self.assertEqual(received['header_stamp_ns'],1000_000_000_001)
        self.assertEqual(received['motion_frame_id'],'base_link')
        self.assertEqual(received['pose_frame_id'],'odom')
        self.assertFalse(received['source_freshness_verified'])

    def test_signed_values_and_callback_snapshot_coherence(self):
        for v,w in ((.2,-.1),(-.2,.1),(0.,0.)):
            self.now+=1
            self.observer.observe(message(sec=1000+int(self.now),v=v,w=w,child='robot/base_link'))
            value=self.checked()
            self.assertEqual((value['linear_mps'],value['angular_radps']),(v,w))
            self.assertEqual(value['motion_frame_id'],'robot/base_link')

    def test_callback_age_advances_without_new_measurement(self):
        self.observer.observe(message()); self.now=11.25
        value=self.checked()
        self.assertEqual(value['callback_age_sec'],1.25)
        self.assertEqual(value['stamp_progress_age_sec'],1.25)
        self.assertEqual(value['callback_sequence'],1)
        self.assertFalse(value['source_freshness_verified'])

    def test_repeated_callbacks_do_not_rejuvenate_stamp_progress(self):
        self.observer.observe(message()); self.now=12.
        self.observer.observe(message()); value=self.checked()
        self.assertEqual(value['callback_age_sec'],0.)
        self.assertEqual(value['stamp_progress_age_sec'],2.)
        self.assertEqual(value['stamp_status'],'repeated')
        self.assertEqual(value['callback_sequence'],2)
        self.now=13.; self.observer.observe(message(sec=1001))
        self.assertEqual(self.checked()['stamp_status'],'advanced')
        self.assertEqual(self.checked()['stamp_progress_age_sec'],0.)

    def test_stamp_reversal_preserved_and_not_relabelled_as_fresh(self):
        self.observer.observe(message(sec=1001)); self.now=11.
        self.observer.observe(message(sec=1000)); value=self.checked()
        self.assertEqual(value['stamp_status'],'reversed')
        self.assertEqual(value['header_stamp_ns'],1000_000_000_001)
        self.assertEqual(value['stamp_progress_age_sec'],1.)
        self.now=12.;self.observer.observe(message(sec=1002))
        self.assertEqual(self.checked()['stamp_status'],'advanced')

    def test_zero_missing_bad_stamp_is_received_but_invalid_fields(self):
        for sec,nano in ((0,0),(-1,0),(1,10**9),(True,0),(1,False),(1.2,0),(2**31,0)):
            with self.subTest(sec=sec,nano=nano):
                self.observer.observe(message(sec=sec,nano=nano))
                value=self.checked()
                self.assertTrue(value['callback_received'])
                self.assertFalse(value['sample_fields_valid'])
                self.assertIsNone(value['header_stamp_ns'])
                self.assertEqual(value['stamp_status'],'missing')
        self.assertIsNone(stamp_ns(None,None))

    def test_bad_sample_fields_sanitized_not_zero_filled(self):
        self.observer.observe(message(v=float('nan'),w=True,child='',pose='bad frame'))
        value=self.checked()
        self.assertEqual(set(value['invalid_fields']), {'linear_mps','angular_radps','motion_frame_id','pose_frame_id'})
        for key in value['invalid_fields']:
            self.assertIsNone(value[key])
        self.assertFalse(value['sample_fields_valid'])

    def test_missing_message_structure_is_diagnostic_not_exception(self):
        self.observer.observe(NS()); value=self.checked()
        self.assertTrue(value['callback_received'])
        self.assertEqual(set(value['invalid_fields']),
                         {'header_stamp_ns','motion_frame_id','pose_frame_id','linear_mps','angular_radps'})

    def test_snapshot_and_observation_lock_contention_are_nonblocking(self):
        with self.observer.lock:
            self.assertFalse(self.observer.observe(message()))
            value=self.checked()
            self.assertEqual(value['stamp_status'],'observer_busy')
            self.assertIsNone(value['callback_received'])
            self.assertEqual(value['dropped_callbacks'],1)
        self.assertEqual(self.checked()['stamp_status'],'not_received')

    def test_clock_reversal_or_nonfinite_never_returns_prior_valid_sample(self):
        self.observer.observe(message()); self.now=11.; self.checked()
        for now in (10.5,float('nan'),float('inf'),True):
            self.now=now; value=self.checked()
            self.assertEqual(value['stamp_status'],'clock_invalid')
            self.assertIsNone(value['linear_mps'])
        self.now=9.; self.assertFalse(self.observer.observe(message()))
        self.now=12.; self.assertEqual(self.checked()['stamp_status'],'clock_invalid')
        self.observer.observe(message(sec=1002)); self.assertTrue(self.checked()['callback_received'])

    def test_returned_data_is_owned_copy(self):
        self.observer.observe(message()); value=self.checked()
        value['linear_mps']=99.; value['invalid_fields'].append('linear_mps')
        self.assertEqual(self.checked()['linear_mps'],0.)
        self.assertEqual(self.checked()['invalid_fields'],[])

    def test_strict_decoder_rejects_wrong_types_authority_and_missing_fields(self):
        self.observer.observe(message()); baseline=self.checked()
        for key,item in (('usable_for_ffb',True),('callback_sequence',True),('header_stamp_ns',True),
                         ('callback_age_sec',.2),('header_clock_relation_verified',True),
                         ('motion_frame_id','bad frame'),('sample_fields_valid',False),
                         ('extra',1),('invalid_fields',['bogus']),('sender_id','unknown')):
            value=copy.deepcopy(baseline);value[key]=item
            with self.subTest(key=key):
                normalized,reason=decode_observation(value)
                self.assertIsNone(normalized);self.assertEqual(reason,'invalid_odometry_metadata')
        self.assertEqual(decode_observation(dict(baseline,schema='future')),
                         (None,'unsupported_odometry_schema'))
        self.assertEqual(decode_observation(None),(None,'invalid_odometry_metadata'))

    def test_parallel_reads_do_not_mix_velocities_from_two_messages(self):
        values=[]
        def writer():
            for i in range(1,1001):
                self.observer.observe(message(sec=i,v=i*.001,w=-i*.001))
        worker=threading.Thread(target=writer); worker.start()
        while worker.is_alive():
            values.append(self.checked())
        worker.join(timeout=1.)
        values.append(self.checked())
        for value in values:
            if value['callback_received'] is True:
                self.assertEqual(value['linear_mps'],-value['angular_radps'])
                self.assertAlmostEqual(value['linear_mps'],value['header_stamp_ns']//10**9*.001)


class SenderAndRecordingTests(unittest.TestCase):
    def test_actual_sender_node_initial_zero_and_received_zero_differ_only_metadata(self):
        node=sender_node(); now=[10.]
        node._odom_observer=OdometryObserver(clock=lambda:now[0])
        initial=node.get_telemetry_dict()
        self.assertEqual(initial['linear_x'],0.)
        self.assertFalse(initial['odometry_observation']['callback_received'])
        node.odom_callback(message())
        value=node.get_telemetry_dict()
        self.assertEqual(value['linear_x'],0.)
        self.assertEqual(value['angular_z'],0.)
        self.assertTrue(value['odometry_observation']['callback_received'])
        self.assertTrue(value['odometry_observation']['sample_fields_valid'])

    def test_metadata_exception_does_not_change_legacy_telemetry(self):
        node=sender_node()
        node._odom_observer=NS(observe=Mock(side_effect=RuntimeError('synthetic observer failure')))
        node.odom_callback(message(v=.2,w=-.1))
        result=node.get_telemetry_dict()
        self.assertEqual(result['linear_x'],.2);self.assertEqual(result['angular_z'],-.1)
        self.assertIsNone(result['odometry_observation'])

    def test_snapshot_exception_keeps_legacy_telemetry(self):
        node=sender_node(); node._odom_observer=NS(snapshot=Mock(side_effect=RuntimeError('synthetic failure')))
        self.assertIsNone(node.get_telemetry_dict()['odometry_observation'])
        self.assertEqual(node.get_telemetry_dict()['speed_mps'],0.)

    def test_observer_construction_failure_keeps_original_subscriptions_and_values(self):
        with patch('driver_odometry_observation.OdometryObserver',side_effect=RuntimeError('synthetic init error')):
            node=sender_node()
        self.assertTrue(node.subscriptions);self.assertTrue(node.publishers)
        node.odom_callback(message(v=.2,w=-.1))
        value=node.get_telemetry_dict()
        self.assertIsNone(value['odometry_observation'])
        self.assertEqual(value['linear_x'],.2);self.assertEqual(value['angular_z'],-.1)

    def test_bad_frame_metadata_does_not_change_original_numeric_values(self):
        node=sender_node();node.odom_callback(message(v=.2,w=-.1,child=''))
        value=node.get_telemetry_dict()
        self.assertEqual(value['linear_x'],.2);self.assertEqual(value['angular_z'],-.1)
        self.assertFalse(value['odometry_observation']['sample_fields_valid'])
        self.assertIsNone(value['odometry_observation']['motion_frame_id'])

    def test_new_record_schema_preserves_legacy_and_atomic_observation_separately(self):
        now=[10.]; observer=OdometryObserver(clock=lambda:now[0]);observer.observe(message(v=.2,w=-.1))
        observation=observer.snapshot()
        with tempfile.TemporaryDirectory() as temp:
            recorder=TelemetryRecorder(Path(temp)/'recording',max_bytes=20000,max_records=10,queue_size=10,
                                       clock=lambda:100.)
            recorder.start()
            try:
                self.assertTrue(recorder.offer('a'*32,dict(linear_x=9.9,angular_z=8.8,
                                                          odometry_observation=observation),1.))
                observation['linear_mps']=123.; observation['invalid_fields'].append('linear_mps')
            finally: status=recorder.close()
            self.assertIsNone(status['error'])
            row=json.loads((recorder.directory/'received_telemetry.jsonl').read_bytes())
            self.assertEqual(row['schema'],'driver_received_telemetry_v2')
            self.assertEqual(row['linear_mps'],9.9)
            self.assertIsNone(row['measurement_valid'])
            self.assertEqual(row['odometry_observation']['linear_mps'],.2)
            self.assertEqual(row['odometry_observation']['angular_radps'],-.1)
            self.assertEqual(row['odometry_metadata_state'],'versioned_odometry_observation')

    def test_old_unknown_and_invalid_metadata_do_not_grant_a_new_measurement(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder=TelemetryRecorder(Path(temp)/'recording',max_bytes=20000,max_records=10,queue_size=10,
                                       clock=lambda:100.)
            recorder.start()
            payloads=[dict(linear_x=0.),dict(linear_x=0.,odometry_observation={'schema':'future'}),
                      dict(linear_x=0.,odometry_observation=None)]
            try:
                for i,payload in enumerate(payloads):
                    self.assertTrue(recorder.offer('a'*32,payload,float(i+1)))
            finally:recorder.close()
            rows=[json.loads(line) for line in (recorder.directory/'received_telemetry.jsonl').read_bytes().splitlines()]
            self.assertEqual(rows[0]['schema'],'driver_received_telemetry_v1')
            self.assertNotIn('odometry_observation',rows[0])
            self.assertEqual(rows[1]['odometry_metadata_state'],'unsupported_odometry_schema')
            self.assertEqual(rows[2]['odometry_metadata_state'],'invalid_odometry_metadata')
            for row in rows[1:]:
                self.assertIsNone(row['odometry_observation'])
                self.assertIsNone(row['measurement_valid'])


if __name__=='__main__':
    unittest.main()
