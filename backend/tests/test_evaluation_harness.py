"""Tests for the harness's *reporting* behaviour.

`tests/test_evaluation.py` proves the arithmetic. This file proves the harness
cannot quietly produce a flattering summary, which is the failure mode that
actually matters for a security-relevant system: not a wrong number, but a
right number presented in a way that gets quoted as an accuracy claim.

The provider is a stub rather than the real engine, so these run everywhere -
including with no model weights present - and so they cannot accidentally depend
on YuNet finding a face in a test fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.dataset import Dataset, Sample, expand_trials
from evaluation.harness import EngineInfo, TrialResult, build_report, render_markdown

REAL = EngineInfo(
    name="YuNet128Provider",
    version="sface-128d-v1",
    dimension=128,
    is_simulation=False,
    preprocessing_version="aligned112-rgb-v1",
)
SIM = EngineInfo(
    name="SimulationProvider",
    version="traya-pseudo-embedding-v2",
    dimension=320,
    is_simulation=True,
    preprocessing_version="crop16-luma-v1",
)


def _sample(i: int, subject: int, condition: str = "ideal") -> Sample:
    return Sample(f"s{i}", Path(f"s{i}.png"), subject, condition, "")


def _dataset(
    n_subjects: int = 8,
    per_subject: int = 2,
    conditions: tuple[str, ...] = ("ideal", "lowlight", "profile"),
    **kw,
):
    """A corpus spanning several condition values, so axes are actually varied."""
    samples = [
        _sample(subject * 1000 + n * 10 + c, subject, conditions[c % len(conditions)])
        for subject in range(1, n_subjects + 1)
        for n in range(per_subject)
        for c in range(len(conditions))
    ]
    return Dataset(
        name=kw.get("name", "corpus"),
        description=kw.get("description", "photographs of consenting volunteers"),
        root=Path("."),
        samples=tuple(samples),
        subjects=tuple(range(1, n_subjects + 1)),
        conditions=tuple(conditions),
        consent=kw.get("consent", "written consent on file"),
        provenance="",
    )


def _results(dataset: Dataset, genuine_scores=(0.9, 0.85, 0.8), impostor_scores=(0.3, 0.25, 0.2)):
    """Build trial results with explicit scores, bypassing any provider."""
    trials = expand_trials(dataset)
    out = []
    gi = ii = 0
    for t in trials:
        if t.label:
            score = genuine_scores[gi % len(genuine_scores)]
            gi += 1
        else:
            score = impostor_scores[ii % len(impostor_scores)]
            ii += 1
        out.append(
            TrialResult(
                trial=t,
                score=score,
                latency_ms=0.05,
                probe_detected=True,
                reference_detected=True,
            )
        )
    return out


class TestHonestyLabels:
    def test_a_thin_corpus_is_labelled_a_smoke_test_everywhere(self):
        ds = _dataset(n_subjects=2, per_subject=2)
        report = build_report(ds, REAL, _results(ds), [0.6])
        assert report.evaluation_grade is False
        assert "SMOKE TEST" in report.headline()
        assert "SMOKE TEST" in render_markdown(report)

    def test_the_reason_is_specific_not_just_false(self):
        """'Not evaluation grade' is useless. '2 subjects, 5 is the floor' is not."""
        ds = _dataset(n_subjects=2, per_subject=2)
        report = build_report(ds, REAL, _results(ds), [0.6])
        joined = " ".join(report.reasons)
        assert "subject" in joined
        assert any(str(n) in joined for n in (2, 1))

    def test_a_well_formed_corpus_is_marked_evaluation_grade(self):
        ds = _dataset(n_subjects=8, per_subject=2)
        assert ds.is_evaluation_grade() is True
        report = build_report(ds, REAL, _results(ds), [0.6])
        assert report.evaluation_grade is True
        assert "SMOKE TEST" not in report.headline()

    def test_synthetic_is_never_evaluation_grade_however_large(self):
        ds = _dataset(n_subjects=50, per_subject=4, description="synthetic render faces")
        assert ds.is_evaluation_grade() is False
        report = build_report(ds, REAL, _results(ds), [0.6])
        assert any("synthetic" in r for r in report.reasons)

    def test_a_one_axis_corpus_is_not_evaluation_grade(self):
        ds = _dataset(n_subjects=8, per_subject=2, conditions=("lowlight",))
        report = build_report(ds, REAL, _results(ds), [0.6])
        assert report.evaluation_grade is False
        assert "pose" in report.totals["coverage_gaps"]

    def test_the_engine_is_named_in_the_markdown(self):
        """A similarity of 0.9 is meaningless without knowing which engine made it."""
        ds = _dataset(n_subjects=8, per_subject=2)
        md = render_markdown(build_report(ds, SIM, _results(ds), [0.6]))
        assert "SimulationProvider" in md
        assert "320D" in md
        assert "SIMULATION" in EngineInfo(
            name="SimulationProvider", version="v", dimension=320, is_simulation=True
        ).banner()

    def test_the_real_engine_is_not_labelled_simulation(self):
        assert "SIMULATION" not in REAL.banner()
        assert "real" in REAL.banner()


class TestDroppedTrials:
    def test_undetected_faces_are_counted_not_scored(self):
        """A detection failure must not become a score of 0.

        Scoring it as 0 would add impostor-like mass at the bottom of the
        distribution and quietly *improve* the reported separability.
        """
        ds = _dataset(n_subjects=8, per_subject=2)
        results = _results(ds)
        results[0] = TrialResult(
            trial=results[0].trial,
            score=float("nan"),
            latency_ms=0.0,
            probe_detected=False,
            reference_detected=True,
            error="s1: no face detected",
        )
        report = build_report(ds, REAL, results, [0.6])
        assert report.detection["trials_dropped"] == 1
        assert report.totals["n_genuine"] + report.totals["n_impostor"] == len(results) - 1

    def test_an_all_failed_run_produces_no_eer(self):
        """Every trial dropped must read as n/a, never as a perfect score."""
        ds = _dataset(n_subjects=8, per_subject=2)
        results = [
            TrialResult(
                trial=r.trial,
                score=float("nan"),
                latency_ms=0.0,
                probe_detected=False,
                reference_detected=False,
                error="boom",
            )
            for r in _results(ds)
        ]
        report = build_report(ds, REAL, results, [0.6])
        assert report.aggregate["eer"] is None
        assert report.aggregate["margin"]["margin"] is None
        md = render_markdown(report)
        assert "EER: n/a" in md


class TestOperatingPoints:
    def test_a_rate_with_few_trials_carries_a_wide_interval(self):
        """The headline reason this harness exists: 0/4 is not a 0% false accept rate."""
        ds = _dataset(n_subjects=2, per_subject=2, conditions=("ideal",))
        report = build_report(ds, REAL, _results(ds), [0.6], target_far=0.01)
        assert report.at_target_far is not None
        far = report.at_target_far["far"]
        assert far["denominator"] == 4, "2 subjects x 2 samples gives 4 impostor pairs"
        # 0/4 leaves a Wilson upper bound near 0.49. The point is the width, not
        # the exact figure: four clean impostor trials cannot certify anything.
        assert far["ci95"][1] > 0.45, "4 impostor trials cannot bound FAR below ~49%"
        assert "95% CI" in render_markdown(report)

    def test_thresholds_are_reported_at_the_seeded_production_values(self):
        ds = _dataset(n_subjects=8, per_subject=2)
        report = build_report(ds, REAL, _results(ds), [0.6, 0.82])
        reported = {round(p["threshold"], 4) for p in report.operating_points}
        assert 0.6 in reported
        assert 0.82 in reported

    def test_a_tighter_threshold_never_reduces_far(self):
        ds = _dataset(n_subjects=8, per_subject=2)
        report = build_report(ds, REAL, _results(ds), [0.6])
        points = sorted(report.operating_points, key=lambda p: p["threshold"])
        fas = [p["far"]["value"] for p in points]
        assert fas == sorted(fas, reverse=True), (
            "raising the threshold can only ever reject more impostors"
        )

    def test_a_condition_with_one_class_reports_no_eer(self):
        ds = _dataset(n_subjects=8, per_subject=2)
        report = build_report(ds, REAL, _results(ds), [0.6])
        for data in report.per_condition.values():
            if data["n_genuine"] == 0 or data["n_impostor"] == 0:
                assert data["eer"] is None


class TestSerialisation:
    def test_the_report_round_trips_as_json(self):
        """A report that cannot be written cannot be traced, which defeats the point."""
        import json

        ds = _dataset(n_subjects=8, per_subject=2)
        report = build_report(ds, REAL, _results(ds), [0.6])
        parsed = json.loads(report.to_json())
        assert parsed["engine"]["dimension"] == 128
        assert parsed["totals"]["n_genuine"] > 0

    def test_nan_scores_do_not_break_json(self):
        import json

        ds = _dataset(n_subjects=8, per_subject=2)
        results = _results(ds)
        results[0] = TrialResult(results[0].trial, float("nan"), 0.0, False, True)
        parsed = json.loads(build_report(ds, REAL, results, [0.6]).to_json())
        assert parsed["trials"][0]["score"] is None

    def test_the_markdown_reports_both_latencies(self):
        ds = _dataset(n_subjects=8, per_subject=2)
        report = build_report(ds, REAL, _results(ds), [0.6], embed_latencies=[30.0, 80.0])
        md = render_markdown(report)
        assert "Embedding" in md and "Match" in md
        assert report.latency["embed_p95_ms"] == 80.0
        assert report.latency["n_embeddings"] == 2
