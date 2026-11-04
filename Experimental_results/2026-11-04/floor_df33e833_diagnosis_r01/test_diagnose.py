"""Synthetic tests for the audit helper; no camera/GPU or reference fitting."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from diagnose import replay_quality

ACCEPTED="temporally_consistent_IMAGE_support_NOT_verified_floor_contact"


def row(index,reason=ACCEPTED,available=True):
    support=[[x,400] for x in range(310,330)] if available else None
    return dict(frame=index+1,source_time_sec=10+index/30,
        support_completion_shadow=dict(candidate=dict(point=[320,400] if available else None,
            support=support,reason="visible" if available else "missing")),
        fixed_floor_shadow=dict(image_quality_reason=reason,image_quality_accepted=reason==ACCEPTED))


class AuditReplayTests(unittest.TestCase):
    def test_unknown_initial_history_is_labelled_not_faked(self):
        records=replay_quality([row(n) for n in range(5)])
        self.assertEqual([r["warmup"] for r in records],[True,True,False,False,False])
        self.assertEqual([r["match"] for r in records],[False,False,True,True,True])

    def test_missing_observation_and_three_frame_recovery_are_preserved(self):
        rows=[row(n) for n in range(3)]
        rows.extend([row(3,"unavailable_support:missing",False),
            row(4,"support_confirmation_pending"),row(5,"support_confirmation_pending"),row(6)])
        records=replay_quality(rows)
        self.assertTrue(all(r["match"] for r in records[2:]))
        self.assertEqual([r["replayed_confirmation_count"] for r in records[4:7]],[1,2,3])

    def test_empty_point_cannot_reuse_old_support(self):
        rows=[row(n) for n in range(3)]+[row(3,"unavailable_support:missing",False)]
        rows[-1]["support_completion_shadow"]["candidate"]["support"]=[[x,400] for x in range(310,330)]
        self.assertFalse(replay_quality(rows)[-1]["replayed_accepted"])

    def test_mismatched_logged_acceptance_is_not_silently_corrected(self):
        rows=[row(n) for n in range(4)]
        rows[-1]["fixed_floor_shadow"].update(image_quality_reason="support_confirmation_pending",image_quality_accepted=False)
        self.assertFalse(replay_quality(rows)[-1]["match"])

    def test_inputs_remain_unchanged_and_time_must_increase(self):
        rows=[row(n) for n in range(5)]
        before=copy.deepcopy(rows)
        replay_quality(rows)
        self.assertEqual(rows,before)
        rows[1]["source_time_sec"]=rows[0]["source_time_sec"]
        with self.assertRaisesRegex(ValueError,"strictly increasing"):
            replay_quality(rows)


if __name__=="__main__":
    unittest.main()
