"""Explicit r04 dependency count; no GPU, files, model or remote path access."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01'))
import audit


class SourceManifestTests(unittest.TestCase):
    def summary(self,count=24):
        source={f'src/fixture_{i}.py':'a'*64 for i in range(24)}
        if count==25:source['src/cone_colour_support_candidate.py']='a'*64
        return dict(source_sha256=source,blocks=[dict(comparison_enabled=False),
            dict(comparison_enabled=True,comparison_final_status=dict(source_sha256={}))])

    def test_original_default_count_remains_24(self):
        with patch.object(audit.replay,'hash_regular',return_value='a'*64) as hashed:
            self.assertEqual(len(audit.checked_source_hashes(self.summary())),24)
            self.assertEqual(hashed.call_count,24)
            with self.assertRaisesRegex(ValueError,'expected benchmark'):
                audit.checked_source_hashes(self.summary(25))

    def test_new_count_must_be_explicit_and_keeps_input_unchanged(self):
        summary=self.summary(25);old=copy.deepcopy(summary)
        with patch.object(audit.replay,'hash_regular',return_value='a'*64) as hashed:
            self.assertEqual(len(audit.checked_source_hashes(summary,expected_count=25)),25)
            self.assertEqual(hashed.call_count,25)
        self.assertEqual(summary,old)

    def test_colour_dependency_required_not_arbitrary_25th(self):
        summary=self.summary(25)
        summary['source_sha256']['src/other.py']=summary['source_sha256'].pop('src/cone_colour_support_candidate.py')
        with patch.object(audit.replay,'hash_regular') as hashed:
            with self.assertRaisesRegex(ValueError,'colour dependency SHA required'):
                audit.checked_source_hashes(summary,expected_count=25)
            hashed.assert_not_called()

    def test_invalid_expected_count_rejected(self):
        for value in (True,25.,None,0,23,26):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'explicit supported source count'):
                audit.checked_source_hashes(self.summary(),expected_count=value)

    def test_same_source_hash_from_worker_merges_once(self):
        summary=self.summary(25)
        summary['blocks'][1]['comparison_final_status']['source_sha256']={'fixture_0.py':'a'*64}
        with patch.object(audit.replay,'hash_regular',return_value='a'*64):
            self.assertEqual(len(audit.checked_source_hashes(summary,expected_count=25)),25)

    def test_conflicting_worker_source_hash_rejected(self):
        summary=self.summary(25)
        summary['blocks'][1]['comparison_final_status']['source_sha256']={'fixture_0.py':'b'*64}
        with self.assertRaisesRegex(ValueError,'inconsistent source SHA'):
            audit.checked_source_hashes(summary,expected_count=25)

    def test_unsafe_path_rejected_before_accessing_that_path(self):
        for name in ('/remote/not_opened.py','src/../not_opened.py'):
            summary=self.summary(25);summary['source_sha256'].pop('src/fixture_0.py')
            summary['source_sha256'][name]='a'*64
            with patch.object(audit.replay,'hash_regular',return_value='a'*64) as hashed:
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'unsafe recorded source path'):
                    audit.checked_source_hashes(summary,expected_count=25)
                self.assertTrue(all(str(call.args[0]).startswith(str(ROOT)+'/') for call in hashed.call_args_list))

    def test_mismatching_local_source_hash_rejected(self):
        with patch.object(audit.replay,'hash_regular',return_value='b'*64):
            with self.assertRaisesRegex(ValueError,'source SHA mismatch'):
                audit.checked_source_hashes(self.summary(25),expected_count=25)


if __name__=='__main__':unittest.main()
