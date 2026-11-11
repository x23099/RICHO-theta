"""Rejected cadence selection: explicit opportunity losses, no actual replay."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cadence_r01'))
from simulate import select


class CadenceSelectionTests(unittest.TestCase):
    def events(self):
        return [dict(clock=n/30,ordinal=n,original_frame=n%8,numeric=n%8==7) for n in range(160)]

    def test_unlimited_keeps_every_opportunity(self):
        result=select(self.events(),0)
        self.assertEqual((result['selected'],result['numeric_selected']),(160,20))

    def test_15hz_phase_can_hide_all_numeric_opportunities(self):
        result=select(self.events(),15)
        self.assertEqual((result['selected'],result['numeric_selected']),(80,0))

    def test_10hz_does_not_preserve_every_numeric_opportunity(self):
        result=select(self.events(),10)
        self.assertEqual(result['selected'],54)
        self.assertEqual(result['numeric_selected'],7)
        self.assertEqual(result['numeric_skipped'],13)


if __name__=='__main__':unittest.main()
