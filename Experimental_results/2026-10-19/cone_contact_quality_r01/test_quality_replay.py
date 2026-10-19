import copy
import json
from pathlib import Path
import unittest

import replay as subject
from cone_dataset import read_csv, sha256
from cone_observation import ConeGroundProjector
from cone_observation_quality import ConeObservationQualityGate


GEOMETRY = dict(camera_height=.59, pitch_deg=1, roll_deg=2, yaw_deg=0, radius_scale=.86,
                front_cx_offset=-80, front_cy_offset=-21, back_cx_offset=82, back_cy_offset=-18)


def box(**changes):
    return dict(dict(x1=290, y1=320, x2=330, y2=400, confidence=.9, class_id=0,
                     _colour=dict(valid=True, reason="unverified_visible_colour_bottom", x=310, y=398)), **changes)


def synthetic(count=20, session="s"):
    ledger = [dict(dataset="test", session=session, frame=i, time_sec=i/30,
                   condition="unlabelled", reference_x_m=None, reference_z_m=None)
              for i in range(1, count+1)]
    return ledger, {subject.key(r): [box()] for r in ledger}


def cached(frame, selected):
    return dict(dataset=frame["dataset"], session=frame["session"], frame=str(frame["frame"]),
                time_sec=str(frame["time_sec"]), v_min="30", candidates=str(len(selected)),
                colour_candidate="True", colour_reason="unverified_visible_colour_bottom",
                pixel_x="310", pixel_y="398", bbox_pixel_x="310", bbox_pixel_y="400")


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.projector = subject.ColourProjector(ConeGroundProjector(
            GEOMETRY, width=1280, height=720, front_lens="left", confidence_threshold=.5))

    def project(self, row, width=1280, height=720):
        return self.projector.project(row, frame_width=width, frame_height=height)

    def test_reuses_floor_math_without_mutating_source(self):
        row = box()
        before = copy.deepcopy(row)
        result = self.project(row)
        expected = subject.project_pixel((310, 398), GEOMETRY)
        self.assertTrue(result["projection_candidate"])
        self.assertEqual((result["x_m"], result["z_m"]), expected)
        self.assertFalse(result["floor_contact_verified"])
        self.assertFalse(result["usable_for_ffb"])
        self.assertEqual(row, before)

    def test_class_confidence_native_resolution_and_bbox_guards_preserved(self):
        for changes in (dict(confidence=.49), dict(class_id=1), dict(confidence="nan"),
                        dict(x1="nan"), dict(x1=0), dict(x1=900, x2=930)):
            self.assertFalse(self.project(box(**changes))["projection_candidate"])
        self.assertEqual(self.project(box(), width=640)["reason"], "calibration_resolution_mismatch")

    def test_colour_missing_and_failure_never_falls_back_to_bbox(self):
        row = box()
        row.pop("_colour")
        self.assertFalse(self.project(row)["projection_candidate"])
        result = self.project(box(_colour=dict(valid=False, reason="no_supported_colour_contour")))
        self.assertEqual(result["reason"], "colour:no_supported_colour_contour")
        self.assertIsNone(result["z_m"])

    def test_invalid_colour_pixel_never_projects(self):
        for x, y in ((float("nan"), 398), (310, float("inf")), (310, 720), (-1, 398),
                     (310, 410), (500, 398), (None, 398)):
            self.assertFalse(self.project(box(_colour=dict(valid=True, x=x, y=y)))["projection_candidate"])

    def test_bbox_floor_failure_does_not_substitute_for_colour_ray_test(self):
        # Valid detection; bbox floor ray/range may fail. Color pixel is evaluated independently.
        row = box(y1=340, y2=365, _colour=dict(valid=True, x=310, y=367))
        result = self.project(row)
        expected = subject.project_pixel((310, 367), GEOMETRY)
        self.assertEqual(result["projection_candidate"], expected is not None)

    def test_reference_labels_do_not_affect_projection(self):
        self.assertEqual(self.project(box()), self.project(box(reference_z_m=99, frame=1134, condition="occluded")))


class BookkeepingTests(unittest.TestCase):
    def setUp(self):
        self.ledger, self.selected = synthetic(5)
        self.pixels = [cached(r, self.selected[subject.key(r)]) for r in self.ledger]

    def test_cache_join_is_exact_and_non_mutating(self):
        before = copy.deepcopy(self.selected)
        joined = subject.join_colour_pixels(self.ledger, self.selected, self.pixels)
        self.assertEqual(set(joined), set(self.selected))
        self.assertEqual(self.selected, before)
        self.assertEqual(joined[subject.key(self.ledger[0])][0]["_colour"]["y"], 398)

    def test_cache_omitted_extra_duplicate_frame_refused(self):
        for pixels in (self.pixels[:-1], self.pixels+[self.pixels[0]],
                       self.pixels+[dict(self.pixels[0], frame="99")]):
            with self.assertRaises(ValueError):
                subject.join_colour_pixels(self.ledger, self.selected, pixels)

    def test_cache_time_bbox_count_boolean_and_finite_values_checked(self):
        for changes in (dict(time_sec="1.5"), dict(candidates="2"), dict(bbox_pixel_y="401"),
                        dict(colour_candidate="maybe"), dict(pixel_x="nan"),
                        dict(colour_candidate="False")):
            pixels = [dict(self.pixels[0], **changes)]+self.pixels[1:]
            with self.assertRaises(ValueError):
                subject.join_colour_pixels(self.ledger, self.selected, pixels)

    def test_no_target_and_multiple_are_not_selected_by_score(self):
        self.selected[subject.key(self.ledger[2])] = []
        self.selected[subject.key(self.ledger[3])] = [box(), box(confidence=.6)]
        rows = subject.replay(self.ledger, self.selected, {"test": GEOMETRY})
        for row in rows:
            if row["frame"] in (3, 4):
                self.assertFalse(row["quality_accepted"])
                self.assertEqual(row["reason"], "no_candidate" if row["frame"] == 3 else "ambiguous_candidates")
                self.assertIsNone(row["observed_z_m"])

    def test_nonsequential_duplicate_and_nonmonotonic_frames_refused(self):
        for ledger in (self.ledger[1:], self.ledger+[self.ledger[-1]],
                       [self.ledger[0], dict(self.ledger[1], time_sec=0)]+self.ledger[2:]):
            with self.assertRaises(ValueError):
                subject.replay(ledger, self.selected, {"test": GEOMETRY})

    def test_replay_deterministic_causal_and_labels_not_gate_inputs(self):
        ledger, selected = synthetic(60)
        full = subject.replay(ledger, selected, {"test": GEOMETRY})
        self.assertEqual(full, subject.replay(ledger, selected, {"test": GEOMETRY}))
        prefix = ledger[:25]
        self.assertEqual(full[:50], subject.replay(prefix, {subject.key(r): selected[subject.key(r)] for r in prefix}, {"test": GEOMETRY}))
        changed = [dict(r, reference_z_m=99, condition="arbitrary", reference_x_m=-8) for r in ledger]
        other = subject.replay(changed, selected, {"test": GEOMETRY})
        for a, b in zip(full, other):
            for field in ("quality_accepted", "observed_x_m", "observed_z_m", "nis", "reason", "confirmation_count"):
                self.assertEqual(a[field], b[field])

    def test_session_state_is_independent(self):
        first, a = synthetic(20, "a")
        second, b = synthetic(5, "b")
        combined = subject.replay(first+second, {**a, **b}, {"test": GEOMETRY})
        self.assertEqual(combined[-10:], subject.replay(second, b, {"test": GEOMETRY}))

    def test_colour_loss_requires_reconfirmation_without_bbox_fallback(self):
        ledger, selected = synthetic(12)
        selected[subject.key(ledger[5])] = [box(_colour=dict(valid=False, reason="no_supported_colour_contour"))]
        rows = subject.replay(ledger, selected, {"test": GEOMETRY})
        colour = [r for r in rows if r["method"] == "colour"]
        self.assertTrue(colour[4]["quality_accepted"])
        self.assertIsNone(colour[5]["observed_z_m"])
        self.assertTrue(colour[5]["internal_prediction"])
        self.assertEqual([r["quality_accepted"] for r in colour[6:9]], [False, False, True])
        bbox = [r for r in rows if r["method"] == "bbox"]
        self.assertTrue(all(r["quality_accepted"] for r in bbox[2:]))


class FullReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = subject.HERE / "results_r02"
        cls.ledger, cls.candidates, cls.models, cls.hashes = subject.load_inputs()
        cls.rows = subject.replay(cls.ledger, cls.candidates, cls.models)

    def test_all_frames_models_methods_and_no_prediction_fill(self):
        self.assertEqual(len(self.rows), 5143*6)
        self.assertEqual(len({(subject.key(r), r["model"], r["method"]) for r in self.rows}), len(self.rows))
        self.assertTrue(all(not r["floor_contact_verified"] and not r["usable_for_ffb"] for r in self.rows))
        for r in self.rows:
            if not r["quality_accepted"]:
                self.assertIsNone(r["observed_z_m"])
                self.assertIsNone(r["filtered_z_m"])

    def test_saved_all_rows_exactly_reproduce(self):
        saved = read_csv(self.directory / "observations.csv")
        self.assertEqual(len(saved), len(self.rows))
        for a, b in zip(self.rows, saved):
            self.assertEqual({k: "" if v is None else str(v) for k, v in a.items()}, b)

    def test_previous_bbox_decisions_and_observed_positions_unchanged(self):
        self.assertEqual(subject.bbox_regression(self.rows, subject.PREVIOUS / "results_r01/observations.csv"), 15429)

    def test_all_summaries_and_withheld_intervals_reproduce(self):
        for name, values in (("summary.csv", subject.summarize(self.rows)),
                             ("withheld_runs.csv", subject.withheld_runs(self.rows))):
            self.assertEqual([{k: "" if v is None else str(v) for k, v in r.items()} for r in values], read_csv(self.directory / name))

    def test_existing_occlusion_is_withheld_and_recovery_requires_confirmation(self):
        for model in self.models:
            for method in ("bbox", "colour"):
                group = {r["frame"]: r for r in self.rows if r["dataset"] == "sequence" and r["model"] == model and r["method"] == method}
                self.assertTrue(all(not group[i]["quality_accepted"] for i in range(1125, 1135)))
                self.assertFalse(group[1135]["quality_accepted"])
                self.assertFalse(group[1136]["quality_accepted"])
                expected = 1138 if method == "colour" and model != "paper_centre2" else 1137
                self.assertTrue(all(not group[i]["quality_accepted"] for i in range(1135, expected)))
                self.assertTrue(group[expected]["quality_accepted"])
                if expected == 1138:
                    # Stable Z alone is insufficient: X jumps >15cm, restarting confirmation.
                    first, second = group[1135], group[1136]
                    self.assertGreater(abs(second["candidate_x_m"]-first["candidate_x_m"]), .15)
                    self.assertLess(abs(second["candidate_z_m"]-first["candidate_z_m"]), .03)
                    self.assertEqual(second["confirmation_count"], 1)

    def test_static_bias_is_not_mistaken_for_quality_failure(self):
        summary = subject.summarize(self.rows)
        row = next(r for r in summary if (r["dataset"], r["condition"], r["model"], r["method"])
                   == ("static", "center_200", "height_only59", "colour"))
        self.assertGreater(row["quality_accepted"], 500)
        self.assertGreater(row["accepted_z_bias_m"], .3)

    def test_no_target_and_multiple_frames_remain_missing(self):
        no_target = [r for r in self.rows if r["dataset"] == "static" and r["reference_z_m"] is None]
        self.assertEqual(len(no_target), 332*6)
        self.assertTrue(all(not r["quality_accepted"] for r in no_target))
        ambiguous = [r for r in self.rows if r["candidates"] > 1]
        self.assertTrue(ambiguous)
        self.assertTrue(all(r["reason"] == "ambiguous_candidates" for r in ambiguous))

    def test_all_frozen_inputs_outputs_and_runtime_hashes_unchanged(self):
        saved = json.loads((self.directory / "provenance.json").read_text())
        for path, digest in {**self.hashes, **saved["source_sha256"]}.items():
            self.assertEqual(sha256(Path(path)), digest, path)
        for name, digest in saved["output_sha256"].items():
            self.assertEqual(sha256(self.directory / name), digest, name)


if __name__ == "__main__":
    unittest.main()
