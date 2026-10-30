"""Algebraic observability controls; no physical camera claim."""
import unittest

import numpy as np

from summarize_intrinsic_consistency import central_jacobian, profile_intrinsics


class AuditSummaryTests(unittest.TestCase):
    def test_central_jacobian_of_linear_function(self):
        matrix = np.arange(12, dtype=float).reshape(4, 3)/10
        actual = central_jacobian(lambda p: matrix@p, np.array([.1, .2, .3]), 1e-6)
        np.testing.assert_allclose(actual, matrix, atol=1e-9)

    def test_bad_derivative_step_refused(self):
        for step in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                central_jacobian(lambda p: p, np.ones(2), step)

    def test_pose_elimination_has_dimension_ceiling(self):
        pose = np.eye(16)[:, :9]
        intrinsic = np.eye(16)[:, 8:]
        result = profile_intrinsics(pose, intrinsic)
        self.assertEqual(result["pose_rank"], 9)
        self.assertEqual(result["rank_ceiling_after_pose_elimination"], 7)
        self.assertEqual(result["normalized_profile_singular_values"][-1], 0)

    def test_complementary_full_rank_directions(self):
        result = profile_intrinsics(np.eye(16)[:, :8], np.eye(16)[:, 8:])
        np.testing.assert_allclose(result["normalized_profile_singular_values"], 1)
        self.assertEqual(result["rank_ceiling_after_pose_elimination"], 8)

    def test_nonmatching_or_nonfinite_inputs_refused(self):
        for a, b in ((np.ones((16, 9)), np.ones((8, 8))),
                     (np.full((16, 9), np.nan), np.ones((16, 8)))):
            with self.assertRaises(ValueError):
                profile_intrinsics(a, b)

    def test_zero_sensitivity_finite_and_not_claimed_observable(self):
        result = profile_intrinsics(np.eye(16)[:, :9], np.zeros((16, 8)))
        self.assertEqual(result["smallest_largest_ratio"], 0)
        self.assertIsNone(result["normalized_profile_condition"])


if __name__ == "__main__":
    unittest.main()
