"""Evidence lineage, original-value preservation, and paired-population tests."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import unittest

import numpy as np

from compare_saved import HERE,ROOT,OLD,UNIFORM,CONTRACT,VARIANTS,SCENES,flag,frame_key,digest_frame_keys,row_digest,lineage,floor_scope,describe
from cone_dataset import read_csv,sha256


class HelperTests(unittest.TestCase):
    def test_explicit_bool_contract(self):
        self.assertTrue(flag('True'));self.assertFalse(flag('False'))
        for value in ('',True,1,'true','False '):
            with self.assertRaises(ValueError):flag(value)

    def test_unknown_model_and_floor_role_refused(self):
        with self.assertRaises(ValueError):lineage('other')
        with self.assertRaises(ValueError):floor_scope(dict(role='other',model='angular_nominal'))

    def test_frame_digest_order_independent_and_identity_sensitive(self):
        a=[('r01',1),('r01',2)]
        self.assertEqual(digest_frame_keys(a),digest_frame_keys(list(reversed(a))))
        self.assertNotEqual(digest_frame_keys(a),digest_frame_keys([('r01',1),('r02',2)]))

    def test_empty_statistics_remain_missing_not_zero_distance(self):
        d=describe([],1.3);self.assertEqual(d['n'],0)
        self.assertTrue(all(v is None for k,v in d.items() if k!='n'))

    def test_bias_percentile_and_base_height_are_separate(self):
        rows=[dict(raw_z_forward_m='1.0',raw_base_height_m='-0.2'),dict(raw_z_forward_m='1.2',raw_base_height_m='-0.1')]
        result=describe(rows,1.3)
        self.assertAlmostEqual(result['z_bias_m'],-.2)
        self.assertAlmostEqual(result['z_abs_error_max_m'],.3)
        self.assertAlmostEqual(result['base_height_median_m'],-.15)


class FrozenComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r01';cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.rows=read_csv(cls.output/'all_frame_comparison.csv')
        cls.index=defaultdict(dict)
        for r in cls.rows:cls.index[frame_key(r)][r['variant']]=r
        cls.membership=read_csv(cls.output/'common_frame_membership.csv')
        cls.paired=read_csv(cls.output/'matched_condition_summary.csv')
        cls.numeric=read_csv(cls.output/'method_own_numeric_summary.csv')
        cls.floor=read_csv(cls.output/'floor_point_lineage.csv')
        cls.sources={str((OLD/'results_r01/cone_all_frame_results.csv').relative_to(ROOT)):read_csv(OLD/'results_r01/cone_all_frame_results.csv'),
            str((UNIFORM/'metric_results_r01/all_frame_metrics.csv').relative_to(ROOT)):read_csv(UNIFORM/'metric_results_r01/all_frame_metrics.csv')}

    def test_every_source_and_output_hash_matches(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)

    def test_all_75636_source_rows_preserved_once(self):
        counts=Counter((r['source_table'],int(r['source_csv_data_row'])) for r in self.rows)
        self.assertEqual(len(self.rows),75636);self.assertEqual(len(counts),75636)
        self.assertEqual(set(counts.values()),{1})
        for table,rows in self.sources.items():self.assertEqual({n for t,n in counts if t==table},set(range(1,len(rows)+1)))

    def test_every_original_numeric_value_and_reason_exact(self):
        for row in self.rows:
            source=self.sources[row['source_table']][int(row['source_csv_data_row'])-1]
            self.assertEqual(row['source_row_sha256'],row_digest(source))
            old='z_forward_m' if 'z_forward_m' in source else 'raw_floor_z_m'
            self.assertEqual(row['raw_z_forward_m'],source[old])
            self.assertEqual(row['source_reason'],source['reason'])
            self.assertEqual(frame_key(row),frame_key(source))

    def test_11_variants_per_frame_not_11_independent_trials(self):
        self.assertEqual(len(self.index),6876)
        self.assertTrue(all(set(v)==set(VARIANTS) for v in self.index.values()))
        self.assertEqual(Counter(r['variant'] for r in self.rows),{v:6876 for v in VARIANTS})

    def test_current_frame_binding_and_time_roles_match_source(self):
        observations={frame_key(r):r for r in read_csv(ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv')}
        scene={frame_key(r):r for r in self.sources[str((UNIFORM/'metric_results_r01/all_frame_metrics.csv').relative_to(ROOT))] if r['model']=='uniform_images'}
        for row in self.rows:
            ob=observations[frame_key(row)]
            for key in ('dataset','condition','reference_z_m'):self.assertEqual(row[key],ob[key])
            self.assertEqual(float(row['time_sec']),float(ob['time_sec']))
            self.assertEqual(row['audit_time_role'],scene[frame_key(row)]['time_role'])

    def test_fixed_models_never_promoted_to_own_session_diagnostic(self):
        for row in self.rows:
            if row['variant'].split('/')[0] not in SCENES:self.assertEqual(row['source_diagnostic_available'],'False')

    def test_scene_diagnostic_flags_and_values_unchanged(self):
        old={(frame_key(r),r['model']):r for r in read_csv(CONTRACT/'results_r01/frame_decisions.csv')}
        for row in self.rows:
            model=row['variant'].split('/')[0]
            if model in SCENES:
                prior=old[frame_key(row),model]
                self.assertEqual(row['source_diagnostic_available'],prior['offline_diagnostic_available'])
                if flag(row['source_diagnostic_available']):self.assertEqual(row['raw_z_forward_m'],prior['offline_diagnostic_distance_m'])

    def test_own_scene_is_only_up_not_independent_full_tf(self):
        registry=read_csv(self.output/'variant_registry.csv')
        self.assertEqual(len(registry),11)
        for row in registry:
            self.assertEqual(row['full_extrinsics_independently_verified'],'False')
            if row['model'] in SCENES:
                self.assertEqual(row['pose_scope'],'own_recording_up_cross_recording_heading_prior')
                self.assertEqual(row['heading_basis'],'cross_recording_paper5_prior')
                self.assertEqual(row['up_derived_from_own_recording'],'True')

    def test_paper5_is_cross_capture_for_every_cone_frame(self):
        selected=[r for r in self.rows if r['variant'].startswith('angular_paper5_rotation/')]
        self.assertEqual(len(selected),20628)
        self.assertEqual({r['pose_scope'] for r in selected},{'cross_recording_paper5_rotation'})

    def test_all_common_members_derived_without_distance_error_cutoff(self):
        for member in self.membership:
            variants=self.index[frame_key(member)]
            numeric=all(flag(r['raw_numerically_estimated']) for r in variants.values())
            diagnostic=all(flag(variants[m+'/floor_bottom_proxy']['source_diagnostic_available']) for m in SCENES)
            quality=flag(member['saved_image_quality_accepted'])
            common=numeric and diagnostic and quality
            self.assertEqual(flag(member['in_common_frame_set']),common)
            self.assertEqual(flag(member['in_paired_reference_comparison']),common and bool(member['reference_z_m']))

    def test_unlabeled_common_frames_not_given_a_distance_reference(self):
        members=[r for r in self.membership if flag(r['in_common_frame_set'])]
        labeled=[r for r in members if flag(r['in_paired_reference_comparison'])]
        self.assertEqual(len(members),1107);self.assertEqual(len(labeled),751)
        self.assertEqual(sum(not r['reference_z_m'] for r in members),356)

    def test_every_variant_uses_identical_paired_frame_keys(self):
        groups=defaultdict(list)
        for r in self.paired:groups[r['dataset'],r['condition'],r['time_window']].append(r)
        for group in groups.values():
            self.assertEqual(len(group),11)
            self.assertEqual(len({r['frame_keys_sha256'] for r in group}),1)
            self.assertEqual(len({r['n'] for r in group}),1)

    def test_empty_six_reference_conditions_are_not_dropped(self):
        groups={r['dataset']+'/'+r['condition'] for r in self.paired}
        empty={r['dataset']+'/'+r['condition'] for r in self.paired if r['n']=='0' and r['time_window']=='all'}
        self.assertEqual(len(groups),8);self.assertEqual(len(empty),6)
        for r in self.paired:
            if r['n']=='0':self.assertEqual(r['z_median_m'],'');self.assertEqual(r['z_bias_m'],'')

    def test_half_recording_time_is_not_confused_with_all_time(self):
        uniform=[r for r in self.paired if r['variant']=='uniform_images/floor_bottom_proxy']
        counts={(r['condition'],r['time_window']):int(r['n']) for r in uniform if r['dataset']=='sequence'}
        self.assertEqual(counts,{('cone_130','all'):218,('cone_130','heldout_time'):6,('cone_200','all'):533,('cone_200','heldout_time'):533})

    def test_paired_statistics_recomputed_from_same_members(self):
        for r in self.paired:
            keys=[frame_key(m) for m in self.membership if flag(m['in_paired_reference_comparison']) and m['dataset']==r['dataset'] and m['condition']==r['condition']
                and (r['time_window']=='all' or self.index[frame_key(m)][r['variant']]['audit_time_role']=='heldout')]
            values=[self.index[k][r['variant']] for k in keys]
            expected=describe(values,float(r['reference_z_m']))
            self.assertEqual(r['frame_keys_sha256'],digest_frame_keys(keys))
            self.assertEqual(int(r['n']),expected['n'])
            if values:
                self.assertAlmostEqual(float(r['z_median_m']),expected['z_median_m'])
                self.assertAlmostEqual(float(r['z_abs_error_max_m']),expected['z_abs_error_max_m'])

    def test_bad_occlusion_is_retained_raw_but_not_in_common_set(self):
        selected=[m for m in self.membership if m['dataset']=='sequence' and int(m['frame']) in (1133,1134,1135)]
        self.assertEqual(len(selected),3)
        for m in selected:
            self.assertEqual(m['in_common_frame_set'],'False')
            self.assertEqual(len(self.index[frame_key(m)]),11)
            self.assertGreater(float(self.index[frame_key(m)]['uniform_images/floor_bottom_proxy']['raw_z_forward_m']),3.)

    def test_recovery_not_old_distance_imputation(self):
        m=next(m for m in self.membership if m['dataset']=='sequence' and m['frame']=='1139')
        self.assertEqual(m['in_common_frame_set'],'True')
        self.assertTrue(all(r['distance_imputed']=='False' for r in self.rows))

    def test_floor_point_lineage_original_values_and_fit_role(self):
        original=read_csv(OLD/'results_r01/floor_reference_results.csv')
        self.assertEqual(len(self.floor),24)
        for r,old in zip(self.floor,original):
            for k,v in old.items():self.assertEqual(r[k],v)
            self.assertEqual(r['source_row_sha256'],row_digest(old))
            self.assertEqual(flag(r['this_point_used_for_this_model_fit']),r['model']=='angular_paper5_rotation' and r['role']=='fit')
        self.assertEqual(sum(flag(r['this_point_used_for_this_model_fit']) for r in self.floor),5)

    def test_floor_point_counts_not_video_frame_trial_counts(self):
        rows=read_csv(self.output/'floor_scope_summary.csv')
        self.assertEqual(len(rows),9)
        for r in rows:self.assertEqual(int(r['points']),{'fit':5,'same_recording_holdout':2,'cross_recording_not_fitted':1}[r['source_location_role']])

    def test_cross_capture_floor_error_not_conflated_with_same_capture(self):
        rows=[r for r in read_csv(self.output/'floor_scope_summary.csv') if r['model']=='angular_paper5_rotation']
        same=next(r for r in rows if r['source_location_role']=='same_recording_holdout')
        cross=next(r for r in rows if r['source_location_role']=='cross_recording_not_fitted')
        self.assertAlmostEqual(float(same['planar_rmse_m']),.021663233195895047)
        self.assertAlmostEqual(float(cross['maximum_abs_z_error_m']),.24750932475615128)

    def test_no_physical_or_hardware_approval(self):
        for r in self.rows:
            self.assertEqual(r['physical_metric_verified'],'False');self.assertEqual(r['usable_for_ffb'],'False')
        self.assertFalse(self.summary['physical_output']);self.assertTrue(self.summary['no_new_geometry'])
        self.assertTrue(self.summary['no_new_recording']);self.assertFalse(self.summary['source_images_edited'])


if __name__=='__main__':unittest.main()
