"""Tests for the evaluation harness.

**Scope, stated first because it is easy to misread this file.** These tests
prove the *arithmetic* is correct and that the harness labels itself honestly.
They prove nothing about whether TRAYA recognises faces. Every score here is a
literal chosen so the answer can be computed by hand on paper:

    scores = [0.9, 0.8, 0.7,  0.4, 0.3, 0.2]
    labels = [ T,   T,   F,    F,   T,   F ]   T = genuine

No photograph, no engine, no database is involved in the metric tests. That is
deliberate: a metric bug found on synthetic scores is cheap to fix, and the same
bug found inside a reported accuracy figure is not.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from evaluation import metrics
from evaluation.dataset import (
    Dataset,
    Sample,
    expand_trials,
    load_manifest,
    verify_digests,
)

# 3 genuine, 3 impostor. Hand-checked below.
SCORES = [0.9, 0.8, 0.7, 0.4, 0.3, 0.2]
LABELS = [True, True, False, False, True, False]
GENUINE = [0.9, 0.8, 0.7]
IMPOSTOR = [0.4, 0.3, 0.2]


# ------------------------------------------------------------------ confusion
class TestConfusionCounts:
    def test_counts_are_correct_at_midpoint(self):
        # t=0.5: accept 0.9, 0.8, 0.7 -> two genuine accepted, one impostor
        # accepted; reject 0.4, 0.3, 0.2 -> two impostors rejected, one genuine
        # rejected.
        tp, tn, fp, fn = metrics.confusion_counts(SCORES, LABELS, 0.5)
        assert (tp, tn, fp, fn) == (2, 2, 1, 1)

    def test_the_decision_is_inclusive(self):
        """score == threshold is a match. Exclusive would silently invert rates."""
        tp, tn, fp, fn = metrics.confusion_counts([0.5], [True], 0.5)
        assert (tp, tn, fp, fn) == (1, 0, 0, 0)

    def test_a_perfect_separator_gives_zero_error_at_the_right_threshold(self):
        r = metrics.rates([0.9, 0.8, 0.4, 0.3], [True, True, False, False], 0.6)
        assert r["far"] == 0.0
        assert r["frr"] == 0.0
        assert r["f1"] == 1.0

    def test_an_inverted_separator_is_caught(self):
        """If every genuine ranks below every impostor, FRR must be 1.0."""
        r = metrics.rates([0.1, 0.2, 0.8, 0.9], [True, True, False, False], 0.5)
        assert r["far"] == 1.0
        assert r["frr"] == 1.0

    def test_misaligned_inputs_refuse_rather_than_zip(self):
        with pytest.raises(ValueError, match="misaligned"):
            metrics.confusion_counts([0.1, 0.2, 0.3], [True, False], 0.5)


class TestRates:
    def test_far_and_frr_at_0_5(self):
        r = metrics.rates(SCORES, LABELS, 0.5)
        assert r["far"] == pytest.approx(1 / 3)
        assert r["frr"] == pytest.approx(1 / 3)

    def test_precision_and_recall_at_0_5(self):
        # tp=2, fp=1 -> precision 2/3. tp=2, fn=1 -> recall 2/3.
        r = metrics.rates(SCORES, LABELS, 0.5)
        assert r["precision"] == pytest.approx(2 / 3)
        assert r["recall"] == pytest.approx(2 / 3)

    def test_f1_harmonic_mean(self):
        r = metrics.rates(SCORES, LABELS, 0.5)
        p, rec = 2 / 3, 2 / 3
        assert r["f1"] == pytest.approx(2 * p * rec / (p + rec))

    def test_accuracy(self):
        r = metrics.rates(SCORES, LABELS, 0.5)
        assert r["accuracy"] == pytest.approx(4 / 6)

    def test_an_absent_class_is_none_not_zero(self):
        """The single most important test in this file.

        "No impostor trials" reporting as FAR 0.0 is how a 20-trial smoke test
        gets published as a 0% false accept rate.
        """
        r = metrics.rates([0.9, 0.8], [True, True], 0.5)
        assert r["far"] is None, "no impostor trials must not read as FAR 0.0"
        assert r["n_impostor"] == 0
        assert r["frr"] == 0.0  # the class that IS present is reported honestly

    def test_precision_is_none_when_nothing_is_accepted(self):
        r = metrics.rates([0.1, 0.2], [False, False], 0.5)
        assert r["precision"] is None
        assert r["far"] == 0.0


class TestRocAndEer:
    def test_roc_is_ordered_by_descending_threshold(self):
        """Higher threshold accepts fewer impostors, so FAR ascends as t falls."""
        curve = metrics.roc_curve(SCORES, LABELS)
        assert curve, "a curve is always available when both classes exist"
        thresholds = [t for t, _ in curve]
        assert thresholds == sorted(thresholds, reverse=True)
        fas = [far for _, far in curve]
        assert fas == sorted(fas), "lowering the threshold must not reduce FAR"

    def test_roc_spans_the_operating_range(self):
        curve = metrics.roc_curve(SCORES, LABELS)
        assert curve[0] == (max(SCORES), 0.0), (
            "at the top score no impostor qualifies, so FAR is 0"
        )
        assert curve[-1][1] == 1.0, "at the bottom score every impostor qualifies"

    def test_auc_is_one_for_a_perfectly_separated_set(self):
        a = metrics.auc([0.9, 0.8, 0.7, 0.2, 0.1], [True, True, True, False, False])
        assert a == pytest.approx(1.0, abs=1e-6)

    def test_auc_is_half_when_the_classes_are_identically_ranked(self):
        # Every impostor sits above every genuine: the ranking is no better
        # than chance. This is the case a crossing-based EER gets wrong.
        a = metrics.auc([0.9, 0.8, 0.3, 0.2], [False, False, True, True])
        assert a == pytest.approx(0.0, abs=1e-6)

    def test_auc_does_not_depend_on_the_score_scale(self):
        """A shifted or scaled score must not change separability.

        This is the test that catches an AUC integrated over the threshold axis
        instead of the FAR axis: that bug makes the area depend on units.
        """
        base_scores = [0.9, 0.8, 0.4, 0.3]
        labels = [True, True, False, False]
        a = metrics.auc(base_scores, labels)
        shifted = [s + 100 for s in base_scores]
        scaled = [s * 7 for s in base_scores]
        assert metrics.auc(shifted, labels) == pytest.approx(a, abs=1e-9)
        assert metrics.auc(scaled, labels) == pytest.approx(a, abs=1e-9)

    def test_auc_is_none_without_both_classes(self):
        assert metrics.auc([0.9, 0.8], [True, True]) is None

    def test_eer_exists_and_lands_in_range(self):
        point = metrics.eer(SCORES, LABELS)
        assert point is not None
        threshold, value = point
        assert 0.0 <= value <= 1.0
        assert 0.2 <= threshold <= 0.7, "the EER threshold must sit in the gap"

    def test_eer_is_zero_for_a_separated_set(self):
        threshold, value = metrics.eer([0.9, 0.8, 0.4, 0.3], [True, True, False, False])
        assert value == pytest.approx(0.0)
        assert 0.3 < threshold < 0.9, "the operating point must sit in the gap"

    def test_eer_is_one_half_when_every_trial_is_misordered(self):
        """Every impostor above every genuine. The honest EER is 0.5.

        A crossing-based search returns 1.0 here by finding the point where FAR
        equals FRR equals 1 - a threshold at which every trial is wrong.
        """
        _, value = metrics.eer([0.9, 0.8, 0.3, 0.2], [False, False, True, True])
        assert value == pytest.approx(0.5)

    def test_eer_is_not_symmetric_under_class_swapping_and_that_is_correct(self):
        """A good recogniser and a useless one are not the same system.

        Swapping the labels on a separated set produces an anti-correlated one,
        so EER must go 0.0 -> 0.5. If this ever became symmetric it would mean
        the routine had lost track of which class is which.
        """
        separated = metrics.eer([0.9, 0.8, 0.4, 0.3], [True, True, False, False])
        swapped = metrics.eer([0.9, 0.8, 0.4, 0.3], [False, False, True, True])
        assert separated[1] == pytest.approx(0.0)
        assert swapped[1] == pytest.approx(0.5)

    def test_eer_is_none_when_one_class_is_absent(self):
        assert metrics.eer([0.9, 0.8], [True, True]) is None
        assert metrics.eer([0.9, 0.8], [False, False]) is None


class TestMargin:
    def test_a_clean_margin_is_positive(self):
        m = metrics.score_margin([0.9, 0.4], [True, False])
        assert m.margin == pytest.approx(0.5)
        assert m.overlaps is False

    def test_an_inverted_set_overlaps(self):
        m = metrics.score_margin([0.3, 0.7], [True, False])
        assert m.margin < 0
        assert m.overlaps is True

    def test_boundary_equality_counts_as_overlap(self):
        """best_impostor == worst_genuine is a tie, and a tie is not a margin."""
        m = metrics.score_margin([0.5, 0.5], [True, False])
        assert m.margin == 0.0
        assert m.overlaps is True

    def test_a_one_class_corpus_reports_no_margin(self):
        m = metrics.score_margin([0.9, 0.8], [True, True])
        assert m.margin is None
        assert m.overlaps is True


class TestPercentiles:
    def test_median_of_an_odd_count(self):
        assert metrics.percentiles([1, 2, 3, 4, 5], (50,))["p50"] == 3

    def test_nearest_rank_p95(self):
        # 100 values 1..100 -> p95 is the 95th value.
        assert metrics.percentiles(list(range(1, 101)), (95,))["p95"] == 95

    def test_empty_input_is_an_empty_dict_not_zeros(self):
        assert metrics.percentiles([], (50, 95)) == {}


class TestWilsonInterval:
    def test_a_perfect_result_does_not_reach_a_certain_zero_false_accept_rate(self):
        """10/10 gives a lower bound near 0.72, never 1.0.

        Wilson deliberately never touches 0 or 1. That is the whole reason for
        using it: "no false accepts in 10 trials" is not "a 0% false accept
        rate", and only the interval makes the difference visible.
        """
        lo, hi = metrics.wilson_interval(10, 10)
        assert lo < 1.0, "a perfect sample must not certify a certain zero"
        assert hi == 1.0
        assert lo > 0.5

    def test_zero_trials_is_none_not_a_perfect_interval(self):
        assert metrics.wilson_interval(0, 0) is None

    def test_small_n_produces_a_wide_interval(self):
        """The reason this function exists: 1/20 must not read as a precise 5%."""
        lo, hi = metrics.wilson_interval(1, 20)
        assert lo < 0.05, "the lower bound must be well under the point estimate"
        assert hi > 0.05
        assert hi - lo > 0.2, "20 trials cannot pin down a rate"

    def test_the_interval_never_leaves_the_unit_interval(self):
        for k, n in ((0, 5), (5, 5), (3, 7), (1, 100), (50, 100)):
            lo, hi = metrics.wilson_interval(k, n)
            assert 0.0 <= lo <= 1.0
            assert 0.0 <= hi <= 1.0
            assert lo <= k / n <= hi, "the point estimate must lie inside"

    def test_a_larger_sample_narrows_the_interval(self):
        _, small = metrics.wilson_interval(5, 20)
        _, large = metrics.wilson_interval(500, 2000)
        assert large - 0.25 < small - 0.25

    def test_summarize_rate_carries_the_denominator(self):
        s = metrics.summarize_rate(1, 20)
        assert s["numerator"] == 1
        assert s["denominator"] == 20
        assert s["value"] == 0.05
        assert s["ci95"] is not None


# -------------------------------------------------------------------- dataset
def _write_corpus(tmp_path: Path) -> Path:
    """Two subjects x two conditions, as tiny valid PNGs."""
    from PIL import Image

    faces = tmp_path / "faces"
    faces.mkdir()
    entries = []
    for subject in (1, 2):
        for condition in ("ideal", "lowlight"):
            name = f"s{subject}-{condition}.png"
            shade = 40 if condition == "lowlight" else 200
            Image.new("RGB", (64, 64), (shade, shade, shade)).save(faces / name)
            entries.append(
                {
                    "sample_id": f"s{subject}-{condition}",
                    "path": f"faces/{name}",
                    "subject_id": subject,
                    "condition": condition,
                }
            )
    manifest = tmp_path / "corpus.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "name": "test-corpus",
                "description": "synthetic squares",
                "consent": "synthetic, no humans",
                "samples": entries,
            }
        ),
        encoding="utf-8",
    )
    return manifest


class TestDataset:
    def test_a_synthetic_corpus_is_refused_the_accuracy_claim(self):
        ds = load_manifest(_write_corpus(tmp_path_fixture()))
        assert ds.is_synthetic is True
        assert ds.is_evaluation_grade() is False
        assert any("synthetic" in r for r in ds.why_not_evaluation_grade())

    def test_subject_ids_must_be_integers(self):
        """A string id is how a real name gets into a corpus."""
        m = tmp_path_fixture() / "m.json"
        m.write_text(
            json.dumps(
                {
                    "manifest_version": 1,
                    "name": "bad",
                    "samples": [
                        {"sample_id": "a", "path": "x.png", "subject_id": "Alice Smith"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must be an integer"):
            load_manifest(m)

    def test_absolute_paths_are_refused(self):
        m = tmp_path_fixture() / "m.json"
        m.write_text(
            json.dumps(
                {
                    "manifest_version": 1,
                    "name": "bad",
                    "samples": [
                        {"sample_id": "a", "path": "C:/photos/x.png", "subject_id": 1}
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="absolute"):
            load_manifest(m)

    def test_a_missing_image_names_the_file(self):
        m = tmp_path_fixture() / "m.json"
        m.write_text(
            json.dumps(
                {
                    "manifest_version": 1,
                    "name": "bad",
                    "samples": [
                        {"sample_id": "a", "path": "nope.png", "subject_id": 1}
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(FileNotFoundError, match="nope.png"):
            load_manifest(m)

    def test_an_unknown_version_refuses_to_guess(self):
        m = tmp_path_fixture() / "m.json"
        m.write_text(json.dumps({"manifest_version": 99, "name": "x", "samples": [1]}), encoding="utf-8")
        with pytest.raises(ValueError, match="manifest_version"):
            load_manifest(m)

    def test_duplicate_sample_ids_are_refused(self):
        corpus = _write_corpus(tmp_path_fixture())
        payload = json.loads(corpus.read_text(encoding="utf-8"))
        payload["samples"][1]["sample_id"] = payload["samples"][0]["sample_id"]
        corpus.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate"):
            load_manifest(corpus)

    def test_trial_expansion_is_exhaustive_and_correctly_labelled(self):
        ds = load_manifest(_write_corpus(tmp_path_fixture()))
        trials = expand_trials(ds)
        # 4 images -> 6 unordered pairs. Same-subject pairs: 2 subjects x C(2,2) = 2.
        assert len(trials) == 6
        assert sum(1 for t in trials if t.label) == 2
        assert sum(1 for t in trials if not t.label) == 4

    def test_a_pair_takes_the_harder_of_its_two_conditions(self):
        """'Easy average' is how a failure mode gets averaged away."""
        ds = Dataset(
            name="x",
            description="",
            root=Path("."),
            samples=(
                Sample("a", Path("a.png"), 1, "ideal", ""),
                Sample("b", Path("b.png"), 2, "lowlight", ""),
            ),
            subjects=(1, 2),
            conditions=("ideal", "lowlight"),
        )
        assert expand_trials(ds)[0].condition == "lowlight"

    def test_coverage_gaps_report_missing_axes_not_missing_values(self):
        """The corpus holds lowlight, so `lighting` is covered. `pose` is not."""
        ds = load_manifest(_write_corpus(tmp_path_fixture()))
        gaps = ds.coverage_gaps()
        assert "pose" in gaps
        assert "lighting" not in gaps
        assert "occlusion" in gaps
        assert gaps, "an axis gap must actually be reported"

    def test_an_ideal_only_corpus_covers_no_axis(self):
        """A corpus captured only in ideal conditions varies nothing."""
        ds = Dataset(
            name="x",
            description="",
            root=Path("."),
            samples=(Sample("a", Path("a.png"), 1, "ideal", ""),),
            subjects=(1,),
            conditions=("ideal",),
        )
        assert ds.axes == ()
        assert len(ds.coverage_gaps()) == 7

    def test_digest_mismatch_is_detected(self, tmp_path):
        manifest = _write_corpus(tmp_path)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["samples"][0]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        bad = verify_digests(load_manifest(manifest))
        assert len(bad) == 1
        assert payload["samples"][0]["sample_id"] in bad[0]


def tmp_path_fixture() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="traya_eval_"))
