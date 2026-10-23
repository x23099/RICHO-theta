"""Frozen evidence ledger and stateless offline contract regression tests."""
from collections import Counter
from dataclasses import fields,replace
import json
import math
from pathlib import Path
import unittest

from audit_metrics import HERE,UNIFORM,explicit_bool,frame_key
from cone_dataset import read_csv,sha256
from eligibility import Evidence,decide,DIAGNOSTIC_CHECKS,PHYSICAL_CHECKS


def complete_diagnostic():
    return Evidence(**{field:True for field,_ in DIAGNOSTIC_CHECKS},raw_forward_m=2.)


class ContractTests(unittest.TestCase):
    def test_diagnostic_is_not_physical_acceptance(self):
        result=decide(complete_diagnostic())
        self.assertEqual(result['offline_diagnostic_distance_m'],2.)
        self.assertEqual(result['state'],'OFFLINE_DIAGNOSTIC_ONLY')
        self.assertFalse(result['physical_metric_checks_satisfied'])
        self.assertIsNone(result['physically_supported_distance_m'])

    def test_each_diagnostic_prerequisite_is_required(self):
        for field,reason in DIAGNOSTIC_CHECKS:
            with self.subTest(field=field):
                result=decide(replace(complete_diagnostic(),**{field:False}))
                self.assertEqual(result['diagnostic_blockers'],(reason,))
                self.assertIsNone(result['offline_diagnostic_distance_m'])
                self.assertEqual(result['state'],'HOLD')

    def test_all_blockers_retained_not_only_first(self):
        result=decide(Evidence(**{field:False for field,_ in DIAGNOSTIC_CHECKS},raw_forward_m=None))
        self.assertEqual(len(result['diagnostic_blockers']),len(DIAGNOSTIC_CHECKS)+1)
        self.assertEqual(len(result['physical_blockers']),len(PHYSICAL_CHECKS))
        self.assertEqual(len(result['all_blockers']),13)

    def test_nonfinite_missing_and_nonpositive_forward_withheld(self):
        for value in (None,math.nan,math.inf,-math.inf,0.,-1.):
            with self.subTest(value=value):
                result=decide(replace(complete_diagnostic(),raw_forward_m=value))
                self.assertIsNone(result['offline_diagnostic_distance_m'])
                self.assertFalse(result['numerical_candidate_available'])

    def test_raw_finite_rejected_value_is_audit_only(self):
        result=decide(replace(complete_diagnostic(),raw_forward_m=5.39,image_support_quality=False))
        self.assertEqual(result['audited_raw_forward_m'],5.39)
        self.assertIsNone(result['offline_diagnostic_distance_m'])
        self.assertIsNone(result['physically_supported_distance_m'])

    def test_zero_and_negative_raw_are_not_hidden_as_valid(self):
        for value in (0.,-1.):
            result=decide(replace(complete_diagnostic(),raw_forward_m=value))
            self.assertEqual(result['audited_raw_forward_m'],value)
            self.assertFalse(result['offline_diagnostic_available'])

    def test_boolean_evidence_is_never_implicitly_coerced(self):
        for field in [f.name for f in fields(Evidence) if f.name!='raw_forward_m']:
            for value in ('False','True',0,1,None):
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                    replace(complete_diagnostic(),**{field:value})

    def test_raw_type_is_not_implicitly_coerced(self):
        for value in (True,False,'2.0',[],{}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                replace(complete_diagnostic(),raw_forward_m=value)

    def test_frozen_bool_reader_rejects_other_encodings(self):
        self.assertTrue(explicit_bool('True'));self.assertFalse(explicit_bool('False'))
        for value in ('true','false','',1,None):
            with self.assertRaises(ValueError):explicit_bool(value)

    def test_untyped_evidence_refused(self):
        with self.assertRaises(TypeError):decide({})

    def test_each_physical_check_is_required_independently(self):
        full=replace(complete_diagnostic(),**{field:True for field,_ in PHYSICAL_CHECKS})
        for field,reason in PHYSICAL_CHECKS:
            with self.subTest(field=field):
                result=decide(replace(full,**{field:False}))
                self.assertEqual(result['offline_diagnostic_distance_m'],2.)
                self.assertEqual(result['physical_blockers'],(reason,))
                self.assertIsNone(result['physically_supported_distance_m'])

    def test_synthetic_all_checks_is_still_not_runtime_or_ffb(self):
        synthetic=replace(complete_diagnostic(),**{field:True for field,_ in PHYSICAL_CHECKS})
        result=decide(synthetic)
        self.assertTrue(result['physical_metric_checks_satisfied'])
        self.assertEqual(result['physically_supported_distance_m'],2.)
        self.assertEqual(result['state'],'PHYSICAL_CHECKS_SATISFIED_OFFLINE_ONLY')
        for key in ('usable_for_ffb','realtime_ready','clear_path_inferred','distance_imputed'):
            self.assertFalse(result[key])

    def test_all_physical_proofs_do_not_bypass_diagnostic_hold(self):
        synthetic=replace(complete_diagnostic(),**{field:True for field,_ in PHYSICAL_CHECKS},current_frame_observation=False)
        self.assertIsNone(decide(synthetic)['physically_supported_distance_m'])

    def test_no_previous_frame_distance_on_missing_or_bad_observation(self):
        valid=complete_diagnostic()
        events=[valid,replace(valid,current_frame_observation=False,raw_forward_m=None),
            replace(valid,image_support_quality=False,raw_forward_m=5.39),replace(valid,raw_forward_m=1.9)]
        self.assertEqual([decide(e)['offline_diagnostic_distance_m'] for e in events],[2.,None,None,1.9])

    def test_interleaving_and_future_evidence_do_not_change_pure_decision(self):
        # This property is only for this helper, NOT for upstream offline pose fit.
        e=complete_diagnostic();held=replace(e,own_session_pose_candidate=False)
        expected=decide(held)
        for other in (e,replace(e,raw_forward_m=20.),held):decide(other)
        self.assertEqual(decide(held),expected)
        self.assertEqual([decide(v) for v in [e,held]],[decide(v) for v in [e,held,e]][:2])

    def test_evidence_is_immutable_and_does_not_take_ground_truth(self):
        self.assertNotIn('reference_z_m',{f.name for f in fields(Evidence)})
        with self.assertRaises(AttributeError):complete_diagnostic().raw_forward_m=3.


class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r01'
        cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.rows=read_csv(cls.output/'frame_decisions.csv')
        cls.evidence=read_csv(cls.output/'frame_evidence.csv')
        cls.matrix=read_csv(cls.output/'session_readiness.csv')
        cls.old=read_csv(UNIFORM/'metric_results_r01/all_frame_metrics.csv')

    def test_sources_and_outputs_still_match_frozen_hashes(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)

    def test_complete_two_model_frame_ledger_no_row_dropping(self):
        key=lambda r:(*frame_key(r),r['model'])
        self.assertEqual(len(self.rows),13752)
        self.assertEqual(len({key(r) for r in self.rows}),13752)
        self.assertEqual({key(r) for r in self.rows},{key(r) for r in self.old})
        self.assertEqual(Counter(r['model'] for r in self.rows),{'uniform_images':6876,'pooled_planes':6876})

    def test_historical_diagnostic_decisions_and_values_exactly_preserved(self):
        for new,old in zip(self.rows,self.old):
            self.assertEqual(new['offline_diagnostic_available'],old['measurement_emitted'])
            self.assertEqual(new['offline_diagnostic_distance_m'],old['emitted_floor_z_m'])
        self.assertEqual(self.summary['diagnostic_available_by_model'],{'uniform_images':1107,'pooled_planes':1107})

    def test_all_current_physical_proof_fields_unverified(self):
        expected={reason for _,reason in PHYSICAL_CHECKS}
        for row in self.rows:
            self.assertEqual(set(json.loads(row['physical_blockers_json'])),expected)
            self.assertEqual(row['physically_supported_distance_m'],'')
            self.assertEqual(row['physical_metric_checks_satisfied'],'False')
        for e in self.evidence:
            for field,_ in PHYSICAL_CHECKS:self.assertEqual(e[field],'False')

    def test_no_clear_safe_imputation_or_hardware_output(self):
        for row in self.rows:
            for key in ('usable_for_ffb','realtime_ready','clear_path_inferred','distance_imputed'):
                self.assertEqual(row[key],'False')

    def test_other_recordings_do_not_borrow_own_pose(self):
        own=[r for r in self.matrix if explicit_bool(r['uniform_own_pose_candidate'])]
        self.assertEqual(len(own),1)
        self.assertTrue(own[0]['session'].startswith('floor_cone_same_pose_'))
        for row in self.rows:
            if row['session']!=own[0]['session']:
                self.assertFalse(explicit_bool(row['offline_diagnostic_available']))
                self.assertIn('no_own_session_temporally_checked_pose',json.loads(row['diagnostic_blockers_json']))

    def test_nine_raw_recordings_not_claimed_as_all_cone_metric(self):
        self.assertEqual(len(self.matrix),9)
        self.assertEqual(sum(int(r['raw_frames']) for r in self.matrix),14526)
        self.assertEqual(sum(int(r['cone_metric_frames']) for r in self.matrix),6876)
        floor=[r for r in self.matrix if r['input_role']=='floor_reference_only_no_cone_metric_ledger']
        self.assertEqual(len(floor),1);self.assertEqual(int(floor[0]['raw_frames']),7650)

    def test_sampled_bbox_coverage_not_confused_with_full_frame_coverage(self):
        self.assertEqual(sum(int(r['sampled_scene_images']) for r in self.matrix),492)
        self.assertEqual(sum(int(r['sampled_saved_bbox_frames']) for r in self.matrix),176)
        self.assertEqual(sum(int(r['sampled_scene_images']) for r in self.matrix if r['sampled_saved_bbox_frames']=='0'),316)

    def test_multiple_blocker_counts_are_explicitly_overlapping(self):
        for row in read_csv(self.output/'blocking_reasons.csv'):
            self.assertEqual(row['causes_overlap'],'True')
            self.assertLessEqual(int(row['frame_count']),int(row['model_frames']))

    def test_bad_raw_occlusion_candidates_preserved_but_not_emitted(self):
        selected=[r for r in self.rows if r['dataset']=='sequence' and int(r['frame']) in (1133,1134,1135)]
        self.assertEqual(len(selected),6)
        for row in selected:
            self.assertTrue(float(row['audited_raw_forward_m'])>0)
            self.assertEqual(row['offline_diagnostic_distance_m'],'')
            self.assertIn('image_support_withheld',json.loads(row['diagnostic_blockers_json']))

    def test_recovery_is_current_frame_value_not_pre_occlusion_copy(self):
        recovered=[r for r in self.rows if r['dataset']=='sequence' and r['frame']=='1139']
        self.assertEqual(len(recovered),2)
        for row in recovered:
            self.assertEqual(row['offline_diagnostic_available'],'True')
            self.assertEqual(row['offline_diagnostic_distance_m'],row['audited_raw_forward_m'])
            self.assertEqual(row['distance_imputed'],'False')

    def test_every_serialized_result_replays_from_explicit_evidence(self):
        for e,row in zip(self.evidence,self.rows):
            values={f.name:(float(e[f.name]) if e[f.name] else None) if f.name=='raw_forward_m' else explicit_bool(e[f.name]) for f in fields(Evidence)}
            result=decide(Evidence(**values))
            self.assertEqual(result['state'],row['state'])
            self.assertEqual(result['all_blockers'],tuple(json.loads(row['all_blockers_json'])))


if __name__=='__main__':unittest.main()
